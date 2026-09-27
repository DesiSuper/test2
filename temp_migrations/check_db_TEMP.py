# ⚠️⚠️⚠️ TEMPORARY FILE — use only once for DB Copy/Migration ⚠️⚠️⚠️
# Usage:
#   1. Drop this into your /plugins/ folder and restart the bot
#   2. Send in PM:
#        /check_db MONGO_URL [DB_NAME]
#      Example:
#        /check_db mongodb+srv://user:pass@cluster0.xxxxx.mongodb.net/?retryWrites=true&w=majority
#      (Skip the URL to use the default DATABASE_URL/DATABASE_NAME from info.py)
#   3. Bot shows connection status, collections, document counts and storage size
#   4. Then shows 3 buttons:
#        📦 Copy    → copies the whole DB to a new URI
#        📁 Select  → pick one collection to copy
#        🔁 Migrate → copies the whole DB + shows a "now update env var" message
#   5. After tapping a button (or picking a collection), reply with the
#      destination MongoDB URI — optionally followed by a DB_NAME
#   6. If the destination collection already has documents, bot asks:
#        ▶️ Resume   → only copies documents newer than what's already there
#        ♻️ Replace  → drops the destination collection, then copies fresh
#        ⏭️ Skip     → leaves that collection untouched, moves to the next one
#        ❌ Cancel   → stops the whole operation
#   7. Copy runs with a live progress bar
#   8. Once done, delete the message that contains the password
#   9. Remove this file from /plugins/ and restart the bot when finished
#
# Notes on resume: if the bot restarts mid-copy, in-memory state is lost, so
# you'll need to re-run /check_db and pick the collection/DB again. But when
# you do, the destination-already-has-data check + "Resume" option means only
# the missing documents (by _id) get copied — it won't rescan or redo the
# part that's already there.

import asyncio
import time
import motor.motor_asyncio
from pymongo.errors import BulkWriteError
from hydrogram import Client, filters
from hydrogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from info import ADMINS, DATABASE_URL, DATABASE_NAME

BATCH_SIZE = 500
STATUS_EDIT_INTERVAL = 4  # seconds between progress message edits
DECISION_TIMEOUT = 300  # seconds to wait for existing-collection decision

# user_id -> {"action": "copy_db"/"copy_collection"/"migrate", "collection": str|None}
PENDING = {}
# user_id -> True  (while the collection-picker step is active)
CHOOSING_COLLECTION = {}
# user_id -> {"url": str, "db_name": str}  — the DB last checked via /check_db
SOURCE = {}
# user_id -> asyncio.Future  — waiting on a resume/replace/skip/cancel decision
DECISION_FUTURES = {}


def _size_fmt(num_bytes):
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if num_bytes < 1024:
            return f"{num_bytes:.2f} {unit}"
        num_bytes /= 1024
    return f"{num_bytes:.2f} PB"


def _progress_bar(done, total, width=12):
    pct = 0 if total <= 0 else min(100, int(done * 100 / total))
    filled = int(width * pct / 100)
    return "▓" * filled + "░" * (width - filled) + f" {pct}%"


@Client.on_message(filters.private & filters.user(ADMINS) & filters.command("check_db"))
async def check_db_cmd(bot, message):
    # /check_db [MONGO_URL] [DB_NAME] — no URL given -> use info.py default
    if len(message.command) > 1:
        check_url = message.command[1]
        check_db_name = message.command[2] if len(message.command) > 2 else DATABASE_NAME
    else:
        check_url = DATABASE_URL
        check_db_name = DATABASE_NAME

    SOURCE[message.from_user.id] = {"url": check_url, "db_name": check_db_name}
    status = await message.reply("🔎 Checking DB info...")

    try:
        old_client = motor.motor_asyncio.AsyncIOMotorClient(check_url)
        old_db = old_client[check_db_name]
        await old_client.admin.command("ping")
    except Exception as e:
        return await status.edit(f"❌ Could not connect (Auth/Network Error):\n{e}")

    try:
        collections = await old_db.list_collection_names()

        # count all collections concurrently instead of one-by-one
        counts = await asyncio.gather(
            *(old_db[c].estimated_document_count() for c in collections)
        )
        db_stats = await old_db.command("dbStats")
        storage_used = _size_fmt(db_stats.get("storageSize", 0))
        old_client.close()

        col_lines = [f"📁 {c}\n    Docs : {n:,}" for c, n in zip(collections, counts)]

        text = (
            f"✅ MongoDB Connected\n\n"
            f"Database : {check_db_name}\n"
            f"Collections : {len(collections)}\n\n"
            + "\n\n".join(col_lines) +
            f"\n\nStorage : {storage_used}"
        )

        buttons = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("📦 Copy", callback_data="dbop:copy_db"),
                InlineKeyboardButton("📁 Select", callback_data="dbop:copy_collection"),
                InlineKeyboardButton("🔁 Migrate", callback_data="dbop:migrate"),
            ],
            [InlineKeyboardButton("❌ Cancel", callback_data="dbop:cancel")],
        ])
        await status.edit(text, reply_markup=buttons)
    except Exception as e:
        await status.edit(f"❌ Failed to fetch DB info:\n{e}")


@Client.on_callback_query(filters.user(ADMINS) & filters.regex(r"^dbop:"))
async def dbop_callback(bot, cq):
    action = cq.data.split(":", 1)[1]

    if action == "cancel":
        PENDING.pop(cq.from_user.id, None)
        CHOOSING_COLLECTION.pop(cq.from_user.id, None)
        return await cq.message.edit("❌ Cancelled.")

    if action == "copy_collection":
        src = SOURCE.get(cq.from_user.id, {"url": DATABASE_URL, "db_name": DATABASE_NAME})
        try:
            old_client = motor.motor_asyncio.AsyncIOMotorClient(src["url"])
            old_db = old_client[src["db_name"]]
            collections = await old_db.list_collection_names()
            old_client.close()
        except Exception as e:
            return await cq.message.edit(f"❌ Could not load collections:\n{e}")

        if not collections:
            return await cq.message.edit("❌ No collections found.")

        rows = [[InlineKeyboardButton(c, callback_data=f"colsel:{c}")] for c in collections]
        rows.append([InlineKeyboardButton("❌ Cancel", callback_data="dbop:cancel")])
        CHOOSING_COLLECTION[cq.from_user.id] = True
        await cq.message.edit("📁 Which collection do you want to copy?", reply_markup=InlineKeyboardMarkup(rows))
        return await cq.answer()

    # copy_db or migrate
    PENDING[cq.from_user.id] = {"action": action, "collection": None}
    label = "Full DB Copy" if action == "copy_db" else "Migrate"
    await cq.message.edit(
        f"✏️ Send the new MongoDB URI for {label} (reply in this chat):\n\n"
        f"mongodb+srv://user:pass@cluster0.xxxxx.mongodb.net/?retryWrites=true&w=majority\n\n"
        f"Optionally add a DB_NAME after it, separated by a space:\n"
        f"mongodb+srv://... mydbname\n\n"
        f"Send /cancel to abort."
    )
    await cq.answer()


@Client.on_callback_query(filters.user(ADMINS) & filters.regex(r"^colsel:"))
async def collection_selected(bot, cq):
    col_name = cq.data.split(":", 1)[1]
    CHOOSING_COLLECTION.pop(cq.from_user.id, None)
    PENDING[cq.from_user.id] = {"action": "copy_collection", "collection": col_name}

    await cq.message.edit(
        f"✏️ Send the new MongoDB URI to copy collection '{col_name}':\n\n"
        f"mongodb+srv://user:pass@cluster0.xxxxx.mongodb.net/?retryWrites=true&w=majority\n\n"
        f"Optionally add a DB_NAME after it, separated by a space:\n"
        f"mongodb+srv://... mydbname\n\n"
        f"Send /cancel to abort."
    )
    await cq.answer()


@Client.on_callback_query(filters.user(ADMINS) & filters.regex(r"^existwarn:"))
async def existing_collection_decision(bot, cq):
    action = cq.data.split(":", 1)[1]  # resume / replace / skip / cancel
    fut = DECISION_FUTURES.get(cq.from_user.id)
    if fut and not fut.done():
        fut.set_result(action)
    label = {"resume": "▶️ Resume", "replace": "♻️ Replace", "skip": "⏭️ Skip", "cancel": "❌ Cancel"}[action]
    await cq.message.edit(f"Chosen: {label}")
    await cq.answer()


@Client.on_message(filters.private & filters.user(ADMINS) & filters.command("cancel"))
async def cancel_pending(bot, message):
    had = PENDING.pop(message.from_user.id, None) or CHOOSING_COLLECTION.pop(message.from_user.id, None)
    fut = DECISION_FUTURES.get(message.from_user.id)
    if fut and not fut.done():
        fut.set_result("cancel")
        had = True
    if had:
        await message.reply("❌ Cancelled.")


async def _ask_existing_collection_decision(bot, chat_id, user_id, col_name, dest_count):
    """Shows Resume/Replace/Skip/Cancel buttons and waits for the admin's choice."""
    fut = asyncio.get_event_loop().create_future()
    DECISION_FUTURES[user_id] = fut

    buttons = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("▶️ Resume", callback_data="existwarn:resume"),
            InlineKeyboardButton("♻️ Replace", callback_data="existwarn:replace"),
        ],
        [
            InlineKeyboardButton("⏭️ Skip", callback_data="existwarn:skip"),
            InlineKeyboardButton("❌ Cancel", callback_data="existwarn:cancel"),
        ],
    ])
    await bot.send_message(
        chat_id,
        f"⚠️ Destination collection '{col_name}' already contains {dest_count:,} docs.\n\n"
        f"▶️ Resume — copy only what's missing\n"
        f"♻️ Replace — drop it and copy fresh\n"
        f"⏭️ Skip — leave it untouched, move on\n"
        f"❌ Cancel — stop the whole operation",
        reply_markup=buttons,
    )

    try:
        return await asyncio.wait_for(fut, timeout=DECISION_TIMEOUT)
    except asyncio.TimeoutError:
        return "skip"
    finally:
        DECISION_FUTURES.pop(user_id, None)


@Client.on_message(
    filters.private & filters.user(ADMINS) & filters.text & ~filters.command(["check_db", "cancel"])
)
async def receive_new_url(bot, message):
    pending = PENDING.get(message.from_user.id)
    if not pending:
        return  # no pending action for this user — let other handlers process this message

    parts = message.text.strip().split()
    if not parts or not parts[0].startswith("mongodb"):
        return await message.reply("⚠️ That doesn't look like a valid MongoDB URI. Send again, or /cancel.")

    new_url = parts[0]
    db_name = parts[1] if len(parts) > 1 else DATABASE_NAME
    action = pending["action"]
    target_collection = pending.get("collection")
    PENDING.pop(message.from_user.id, None)

    label = {
        "copy_db": "Copy Database",
        "copy_collection": f"Copy Collection ({target_collection})",
        "migrate": "Migration",
    }[action]
    status = await message.reply(f"🚚 Starting {label}...\n\nConnecting to the new DB...")

    src = SOURCE.get(message.from_user.id, {"url": DATABASE_URL, "db_name": DATABASE_NAME})
    try:
        old_client = motor.motor_asyncio.AsyncIOMotorClient(src["url"])
        new_client = motor.motor_asyncio.AsyncIOMotorClient(new_url)
        old_db = old_client[src["db_name"]]
        new_db = new_client[db_name]
        await new_client.admin.command("ping")
    except Exception as e:
        return await status.edit(
            f"❌ Could not connect to the new DB (Auth/Network Error):\n{e}\n\n"
            f"👉 Make sure 0.0.0.0/0 is whitelisted in Atlas Network Access."
        )

    all_collections = await old_db.list_collection_names()
    if not all_collections:
        return await status.edit("❌ No collections found in the source DB.")

    if action == "copy_collection":
        if target_collection not in all_collections:
            return await status.edit(f"❌ Collection '{target_collection}' no longer exists.")
        collections_to_copy = [target_collection]
    else:
        collections_to_copy = all_collections

    grand_total = 0
    grand_failed = 0
    last_edit = time.time()

    for col_name in collections_to_copy:
        old_col = old_db[col_name]
        new_col = new_db[col_name]

        # --- existing-collection check ---
        query = {}
        dest_count = await new_col.count_documents({})
        if dest_count > 0:
            decision = await _ask_existing_collection_decision(
                bot, message.chat.id, message.from_user.id, col_name, dest_count
            )
            if decision == "cancel":
                old_client.close()
                new_client.close()
                return await status.edit("❌ Operation cancelled.")
            elif decision == "skip":
                continue
            elif decision == "replace":
                await new_col.drop()
                query = {}
            else:  # resume
                last_doc = await new_col.find_one({}, sort=[("_id", -1)])
                if last_doc:
                    query = {"_id": {"$gt": last_doc["_id"]}}

        total = await old_col.count_documents(query)
        if total == 0:
            continue  # nothing left to copy for this collection

        copied, failed, batch = 0, 0, []

        # sort by _id so resume (query on _id) always picks up where it left off
        cursor = old_col.find(query, batch_size=BATCH_SIZE).sort("_id", 1)
        async for doc in cursor:
            batch.append(doc)
            if len(batch) >= BATCH_SIZE:
                ins, err = await _insert_batch(new_col, batch)
                copied += ins
                failed += err
                batch = []
                if time.time() - last_edit > STATUS_EDIT_INTERVAL:
                    last_edit = time.time()
                    try:
                        await status.edit(
                            f"🚚 {label} in progress...\n\n"
                            f"📁 {col_name}: {copied}/{total}\n"
                            f"{_progress_bar(copied, total)}"
                        )
                    except Exception:
                        pass

        if batch:
            ins, err = await _insert_batch(new_col, batch)
            copied += ins
            failed += err

        # copy non-default indexes so the new collection performs the same
        try:
            existing_indexes = await new_col.index_information()
            async for index in old_col.list_indexes():
                if index["name"] == "_id_" or index["name"] in existing_indexes:
                    continue
                keys = list(index["key"].items())
                opts = {k: v for k, v in index.items() if k not in ("key", "v", "ns")}
                await new_col.create_index(keys, **opts)
        except Exception:
            pass  # index copy is best-effort, never block the data copy

        grand_total += copied
        grand_failed += failed
        try:
            await status.edit(
                f"✅ {col_name} done: {copied}/{total}\n{_progress_bar(copied, total)}\n\n"
                f"⏳ Moving to next collection..."
            )
        except Exception:
            pass

    old_client.close()
    new_client.close()

    failed_note = f"\n⚠️ {grand_failed} documents failed to copy (real errors, not just duplicates).\n" if grand_failed else ""

    if action == "migrate":
        final_text = (
            f"🎉 Migration complete!\n\n"
            f"📦 Collections: {len(collections_to_copy)}\n"
            f"📄 Documents copied: {grand_total}\n"
            f"{failed_note}\n"
            f"👉 Now update DATABASE_URL in Koyeb to the new URI and restart the bot.\n"
            f"⚠️ Then delete this message and remove this file from plugins."
        )
    elif action == "copy_collection":
        final_text = (
            f"🎉 Collection copy complete!\n\n"
            f"📁 Collection: {target_collection}\n"
            f"📄 Documents copied: {grand_total}\n"
            f"{failed_note}\n"
            f"ℹ️ The original DB is untouched, nothing else to change.\n"
            f"⚠️ Delete this message (it contains a password)."
        )
    else:
        final_text = (
            f"🎉 Database copy complete!\n\n"
            f"📦 Collections: {len(collections_to_copy)}\n"
            f"📄 Documents copied: {grand_total}\n"
            f"{failed_note}\n"
            f"ℹ️ The original DB is untouched, nothing else to change.\n"
            f"The new DB is just a ready backup/copy.\n"
            f"⚠️ Delete this message (it contains a password)."
        )

    await status.edit(final_text)


async def _insert_batch(new_col, batch):
    """
    Returns (inserted_count, real_failed_count).
    ordered=False so one bad doc doesn't block the rest of the batch.
    Duplicate-key errors (code 11000, e.g. re-running a copy) are NOT counted
    as real failures — they just mean that doc was already there. Any other
    write error (validation, disk full, etc.) IS counted as a real failure,
    instead of the old behaviour of silently reporting the whole batch as
    "copied" when the entire insert_many call raised.
    """
    try:
        res = await new_col.insert_many(batch, ordered=False)
        return len(res.inserted_ids), 0
    except BulkWriteError as e:
        write_errors = e.details.get("writeErrors", [])
        dup_errors = sum(1 for we in write_errors if we.get("code") == 11000)
        real_errors = len(write_errors) - dup_errors
        inserted = len(batch) - len(write_errors)
        return inserted, real_errors
    except Exception:
        # total failure (auth error, network drop, disk full, etc.) — don't
        # pretend this batch succeeded
        return 0, len(batch)
