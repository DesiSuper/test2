import time
import random
import asyncio
import gc
import logging
from hydrogram import Client, filters
from hydrogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from hydrogram.errors import FloodWait, MessageNotModified, BadRequest
from info import ADMINS, BIN_CHANNEL, LOG_CHANNEL
from utils import temp, get_readable_time
from database.ia_filterdb import (FILE_COLLECTIONS, build_meta_migration_query,
                                  apply_media_meta_update, mark_meta_migration_error,
                                  msg_media, media_true_type)
from media_probe import probe_telegram_file, should_probe_media

logger = logging.getLogger(__name__)

# हर इतने files के बाद BIN_CHANNEL के temp messages एक ही call me delete hote हैं
# (ek-ek delete karne se 2x API calls lagti aur flood ka risk bhi zyada tha)
DELETE_BATCH = 100

# ─────────────────────────────────────────────────────────
# 🎨 PROGRESS UI
# ─────────────────────────────────────────────────────────
def get_migration_ui(processed, total, filled, skipped, failed, elapsed, eta, speed,
                     type_fixed=0, probed=0, running=True):
    percent = int((processed / max(total, 1)) * 100)
    dot = "🔴" if percent < 30 else ("🟡" if percent < 70 else "🟢")
    status = "▶️ Running" if running else "⏹ Stopped"
    lines = [
        "🔄 <b>FAST FINDER - META MIGRATION CONSOLE</b>",
        "──────────────────────────────",
        f"📁 <b>Missing Info Found:</b> <code>{total:,}</code> Files",
        f"📈 <b>Pipeline Index  :</b> <code>{processed:,} / {total:,}</code>",
        f"✅ <b>Filled (dur/w/h/mime):</b> <code>{filled:,}</code>",
        f"⏭️ <b>Skipped (no media)  :</b> <code>{skipped:,}</code>",
        f"❌ <b>Failed (broken ref) :</b> <code>{failed:,}</code>",
        f"🎬 <b>Type Fixed (doc→vid/aud):</b> <code>{type_fixed:,}</code>",
        f"🔍 <b>Probed (real W×H) :</b> <code>{probed:,}</code>",
        f"⏱️ <b>Time Remaining :</b> <code>{get_readable_time(eta)}</code>",
        f"⚡ <b>Velocity       :</b> <code>{speed:.1f} f/min</code>",
        "──────────────────────────────",
        f"{dot} <b>Core Progress Matrix:</b> <code>| {percent}% Synced |</code>",
        f"🎛️ <b>Status:</b> <code>{status}</code>",
    ]
    return "\n".join(lines)

# ─────────────────────────────────────────────────────────
# 🔄 CORE ENGINE
# ─────────────────────────────────────────────────────────
async def start_meta_migration(client, status_msg, user_id):
    logger.info(f"🔄 [META-MIGRATE] Engine triggered by admin: {user_id}")

    query = build_meta_migration_query()

    # पेंडिंग काउंट्स (तीनों collections parallel)
    counts = await asyncio.gather(
        *[col.count_documents(query) for col in FILE_COLLECTIONS.values()]
    )
    col_counts = dict(zip(FILE_COLLECTIONS.keys(), counts))
    total_to_process = sum(col_counts.values())

    if total_to_process == 0:
        return await status_msg.edit(
            "✨ <b>FAST FINDER DATABASE STATUS</b>\n\n"
            "🎉 <code>Everything is already up to date!</code>\n"
            "Kisi bhi file me duration / width / height / mime_type missing nahi hai."
        )

    await status_msg.edit(
        f"📊 <b>Missing info detected:</b> <code>{total_to_process:,}</code> files\n"
        f"Initializing single-bot safe stream pipeline...\n"
        f"🔍 <i>Asli resolution ab file bytes se probe hogi (Telegram ke attributes par bharosa nahi).</i>\n\n"
        f"<i>💡 Document likhi hui asli video/audio files ka type bhi theek ho jayega (mime_type se). Beech me bot restart ho jaaye to koi problem nahi — "
        f"jo files bhul chuki hain wo query se automatically hat jaati hain, "
        f"isi liye command dobara chalane se wahi se continue ho jayega.</i>"
    )

    processed = filled = skipped = failed = type_fixed = probed_ok = 0
    start_time = time.time()
    pending_deletes = []   # BIN_CHANNEL ke temp messages (batch delete hote hain)

    async def _flush_deletes():
        """Temp messages ko 100-100 ke batches me delete karo (flood-safe)."""
        nonlocal pending_deletes
        while pending_deletes:
            batch = pending_deletes[:DELETE_BATCH]
            pending_deletes = pending_deletes[DELETE_BATCH:]
            try:
                await client.delete_messages(BIN_CHANNEL, batch)
            except FloodWait as e:
                logger.warning(f"[META-MIGRATE] delete flood wait {e.value}s")
                await asyncio.sleep(e.value + 2)
                try:
                    await client.delete_messages(BIN_CHANNEL, batch)
                except Exception:
                    pass
            except Exception as e:
                logger.debug(f"[META-MIGRATE] delete batch failed: {e}")
            await asyncio.sleep(0.5)

    try:
        for col_name, collection in FILE_COLLECTIONS.items():
            if col_counts[col_name] == 0:
                continue

            logger.info(f"📁 [META-MIGRATE] Running secure loop over: {col_name.upper()}")

            # ✅ _id se sort + sirf zaroori fields — RAM bachane ke liye
            cursor = collection.find(
                query,
                {"_id": 1, "file_ref": 1, "file_id": 1, "file_name": 1,
                 "file_size": 1, "file_type": 1, "duration": 1, "meta": 1}
            ).sort("_id", 1)

            try:
                async for doc in cursor:
                    if temp.CANCEL:
                        temp.CANCEL = False
                        await status_msg.edit(
                            "🛑 <b>Migration Cancelled!</b>\n\n"
                            + get_migration_ui(processed, total_to_process, filled,
                                               skipped, failed,
                                               time.time() - start_time, 0, 0,
                                               type_fixed=type_fixed, probed=probed_ok,
                                               running=False)
                            + "\n\n<i>💡 Jitni files bhul chuki hain unme info save ho chuki hai — "
                              "command dobara chalane se baaki se continue hoga.</i>"
                        )
                        return

                    processed += 1
                    file_label = str(doc.get("file_name", "Unknown File"))[:35]
                    fid = doc.get("file_ref") or doc.get("file_id") or doc.get("_id")
                    if not fid:
                        skipped += 1
                        continue

                    msg = None
                    try:
                        # ⬇️ Asli kaam: saved file_id se file cached-media ki tarh mango.
                        #    Jo message milta hai usme duration/w/h/mime sab hota hai.
                        msg = await client.send_cached_media(chat_id=BIN_CHANNEL, file_id=fid)
                        media = msg_media(msg)

                        if not media:
                            skipped += 1
                        else:
                            # 🔍 Asli resolution file BYTES se probe karo — Telegram
                            # ke w/h attributes uploader ke likhe hote hain aur aksar
                            # default (1280×720) hote hain, jabki file kuch aur ho.
                            # Probe ke liye msg se mila FRESH file_id use hota hai
                            # (DB wala file_ref purana ho sakta hai). Sirf video-ish
                            # files par — PDF/MP3 par bandwidth waste nahi.
                            probed = {}
                            if should_probe_media(media, doc.get("file_name", "")):
                                try:
                                    fresh_ref = getattr(media, "file_id", None) or fid
                                    probed = await probe_telegram_file(
                                        client, fresh_ref,
                                        file_size=doc.get("file_size", 0) or 0,
                                        file_name=str(doc.get("file_name", "")),
                                    )
                                except FloodWait:
                                    raise  # bahar wala anti-flood handler pakdega
                                except Exception as e:
                                    logger.debug(f"[META-MIGRATE] probe fail "
                                                 f"({file_label}): {str(e)[:80]}")
                                    probed = {}

                            # 🎬 document likha hai par asli me video/audio hai
                            # (mime_type se pata) — wo bhi isi write me theek hota hai
                            # ⚠️ FIX: probe attempt hui par dims nahi mile → v mat likho
                            # ताकि अगले run में retry हो सके (web backfill jaisa safe pattern)
                            needs_probe = should_probe_media(media, doc.get("file_name", ""))
                            probe_failed = needs_probe and not (probed.get("w") and probed.get("h"))
                            await apply_media_meta_update(
                                collection, doc["_id"], media,
                                current_type=doc.get("file_type"),
                                probed=probed or None,
                                skip_version=probe_failed)
                            filled += 1
                            if media_true_type(media) != doc.get("file_type"):
                                type_fixed += 1
                                print(f"🎬 [TYPE FIXED] {doc.get('file_type')} → "
                                      f"{media_true_type(media)} "
                                      f"({processed}/{total_to_process}) ✅ {file_label}", flush=True)
                            pw, ph = (probed.get("w") or 0), (probed.get("h") or 0)
                            if pw and ph:
                                probed_ok += 1
                                mw = int(getattr(media, "width", 0) or 0)
                                mh = int(getattr(media, "height", 0) or 0)
                                if (mw, mh) != (pw, ph):
                                    print(f"🔍 [PROBED] {file_label}: TG {mw}x{mh} → "
                                          f"real {pw}x{ph} ({processed}/{total_to_process})",
                                          flush=True)
                                else:
                                    print(f"💾 [FILLED] ({processed}/{total_to_process}) ✅ "
                                          f"{file_label} (probe confirmed {pw}x{ph})", flush=True)
                            else:
                                print(f"💾 [FILLED] ({processed}/{total_to_process}) ✅ {file_label}",
                                      flush=True)

                        if msg:
                            pending_deletes.append(msg.id)
                            if len(pending_deletes) >= DELETE_BATCH:
                                await _flush_deletes()

                        # anti-flood gap: 1-3s random. Warmup jitna bhaari nahi
                        # (yahan upload nahi, sirf cached-send + delete hota hai),
                        # par itna dheema hi theek hai — Telegram spam-report bhi
                        # nahi karta aur flood-wait bhi nahi lagta.
                        await asyncio.sleep(random.uniform(1.0, 3.0))

                    except FloodWait as e:
                        if msg:
                            pending_deletes.append(msg.id)
                        wait_sec = e.value + 10
                        logger.warning(f"[META-MIGRATE] Flood wait {wait_sec}s")
                        try:
                            await status_msg.edit(
                                f"⏳ <b>Telegram Rate Limit Hit!</b>\n"
                                f"Sleeping <code>{wait_sec}s</code> — pipeline will auto-resume.\n"
                                f"📈 Progress so far: <code>{processed:,}/{total_to_process:,}</code>"
                            )
                        except Exception:
                            pass
                        await asyncio.sleep(wait_sec)

                    except BadRequest:
                        # tooti hui / delete ho chuki file_ref — mark karo taaki
                        # har run me dobara na uthе
                        if msg:
                            pending_deletes.append(msg.id)
                        await mark_meta_migration_error(collection, doc["_id"])
                        failed += 1
                        print(f"❌ [BAD REF] Broken file_id marked: {file_label}", flush=True)

                    except Exception as e:
                        if msg:
                            pending_deletes.append(msg.id)
                        logger.warning(f"[META-MIGRATE] error on {file_label}: {str(e)[:100]}")
                        await asyncio.sleep(2)

                    # हर 10 files पर UI update
                    if processed % 10 == 0 or processed == total_to_process:
                        elapsed = time.time() - start_time
                        eta = (total_to_process - processed) * (elapsed / max(processed, 1))
                        speed = (processed / max(elapsed, 1)) * 60
                        try:
                            await status_msg.edit(
                                get_migration_ui(processed, total_to_process, filled,
                                                 skipped, failed, elapsed, eta, speed,
                                                 type_fixed=type_fixed, probed=probed_ok)
                            )
                        except MessageNotModified:
                            pass
                        except Exception:
                            pass
                        gc.collect()

            finally:
                await cursor.close()

    finally:
        # cancel / error / complete — kisi bhi haal me bache temp messages saaf karo
        await _flush_deletes()

    # ✅ FINAL REPORT
    total_elapsed = time.time() - start_time
    final_report = (
        f"🎉 <b>META MIGRATION ACCOMPLISHED</b>\n"
        f"──────────────────────────────\n\n"
        f"🎯 <b>Total Scanned Docs:</b> <code>{processed:,}</code>\n"
        f"✅ <b>Filled Info        :</b> <code>{filled:,}</code> Files\n"
        f"⏭️ <b>Skipped (no media) :</b> <code>{skipped:,}</code>\n"
        f"❌ <b>Failed (broken ref):</b> <code>{failed:,}</code>\n"
        f"🎬 <b>Type Fixed (doc→video/audio):</b> <code>{type_fixed:,}</code>\n"
        f"🔍 <b>Probed Real Reso.  :</b> <code>{probed_ok:,}</code> Files\n"
        f"🕐 <b>Total Time         :</b> <code>{get_readable_time(total_elapsed)}</code>\n\n"
        f"⚡ <i>Dashboard, Mini App aur actor profiles par ab asli duration, "
        f"resolution (W×H) aur mime_type dikhega!</i>"
    )
    try:
        await status_msg.reply(final_report)
    except Exception:
        pass

    if LOG_CHANNEL:
        try:
            await client.send_message(
                LOG_CHANNEL,
                f"📢 <b>#Meta_Migration ✅</b>\n\n"
                f"» Scanned: <code>{processed:,}</code>\n"
                f"» Filled: <code>{filled:,}</code>\n"
                f"» Skipped: <code>{skipped:,}</code>\n"
                f"» Failed: <code>{failed:,}</code>\n"
                f"» Type Fixed: <code>{type_fixed:,}</code>\n"
                f"» Probed Real Reso.: <code>{probed_ok:,}</code>\n"
                f"» Time: <code>{get_readable_time(total_elapsed)}</code>"
            )
        except Exception:
            pass

# ─────────────────────────────────────────────────────────
# 📢 COMMAND ROUTE — /migrate_meta (ADMIN ONLY)
# ─────────────────────────────────────────────────────────
@Client.on_message(filters.command("migrate_meta") & filters.user(ADMINS))
async def migrate_meta_cmd(client, message):
    btn = [[InlineKeyboardButton("🛑 CANCEL MIGRATION", callback_data="meta_migrate_cancel")]]
    status_msg = await message.reply(
        "⚙️ <b>Meta Migration Core Starting...</b>",
        reply_markup=InlineKeyboardMarkup(btn),
    )
    await start_meta_migration(client, status_msg, message.from_user.id)

# ─────────────────────────────────────────────────────────
# 🔘 CANCEL ROUTE
# ─────────────────────────────────────────────────────────
@Client.on_callback_query(filters.regex(r"^meta_migrate_cancel$"))
async def migrate_meta_cancel(client, query):
    if query.from_user.id not in ADMINS:
        return await query.answer("❌ Admin credentials required.", show_alert=True)
    temp.CANCEL = True
    await query.answer("🛑 Cancellation signal sent...", show_alert=False)
    try:
        await query.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass
