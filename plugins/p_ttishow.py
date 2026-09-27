import os
import sys
import random
import logging
import gc
from hydrogram import Client, filters, enums
from info import ADMINS, LOG_CHANNEL, PICS, IS_PREMIUM
from database.users_chats_db import db

# ✅ FIX: is_premium को अब plugins.premium की जगह utils से इम्पोर्ट किया गया है
from utils import is_premium, temp, get_settings, is_rate_limited
from Script import script

logger = logging.getLogger(__name__)

# ======================================================
# 👋 👋 WELCOME MESSAGE ENGINE — Complete User Entry Sync (FIXED)
# ======================================================
@Client.on_chat_member_updated()
async def welcome(c, m):
    # चेक करें कि क्या यह किसी ग्रुप/सुपरग्रुप में नए मेंबर की एंट्री है
    if not m.chat.type in (enums.ChatType.GROUP, enums.ChatType.SUPERGROUP):
        return
        
    if m.new_chat_member and not m.old_chat_member:
        new_user = m.new_chat_member.user
        
        # ── केस 1: जब खुद बोट ग्रुप में ऐड हो ──
        if new_user.id == temp.ME:
            u = m.from_user.mention if m.from_user else "Admin"
            await c.send_photo(
                m.chat.id, 
                random.choice(PICS), 
                f"👋 <b>Hello {u},\n\nThanks for adding me to {m.chat.title}!</b>\n\n📌 <i>Don't forget to grant me full Administrator privileges with delete message permissions to keep this group clean and automated.</i>"
            )
            
            if not await db.get_chat(m.chat.id):
                uname = f'@{m.chat.username}' if m.chat.username else 'Private'
                total = await c.get_chat_members_count(m.chat.id)
                await c.send_message(LOG_CHANNEL, script.NEW_GROUP_TXT.format(m.chat.title, m.chat.id, uname, total))       
                await db.add_chat(m.chat.id, m.chat.title)
            return

        # ── केस 2: ✅ FIX: जब कोई आम यूज़र (मेंबर) ग्रुप ज्वाइन करे ──
        # अब आपका वेलकम टेक्स्ट लाइव ग्रुप में परफेक्ट काम करेगा
        settings = await get_settings(m.chat.id)
        
        # यूज़र का मेंशन और ग्रुप का टाइटल पार्स करें
        welcome_cap = script.WELCOME_TEXT.format(
            mention=new_user.mention,
            title=m.chat.title
        )
        
        # ✅ FIX: स्ट्रिक्ट प्रीमियम मॉडल पैच - अगर आने वाला मेंबर प्रीमियम नहीं है, तो उसे सूचित करें
        if IS_PREMIUM and new_user.id not in ADMINS and not await is_premium(new_user.id, c):
            welcome_cap += "\n\n🔒 <b>Notice:</b> This is an <u>Admin & Premium Only</u> automated group. Please type /plan in bot PM to unlock your search access."
            
        try:
            w_msg = await c.send_message(m.chat.id, welcome_cap)
            
            # यदि ग्रुप में ऑटो-डिलीट ऑन है, तो वेलकम मैसेज को ५ मिनट (DELETE_TIME) में साफ़ करें
            if settings.get("auto_delete", True):
                await db.add_to_delete_queue(m.chat.id, w_msg.id, 300)
        except Exception as e:
            logger.debug(f"Failed to send welcome message: {e}")

# ======================================================
# 🔄 CORE HARD RESTART SESSION MANAGER
# ======================================================
@Client.on_message(filters.command('restart') & filters.user(ADMINS))
async def restart_bot(c, m):
    msg = await m.reply("<b>🔄 Restructuring Session Rebuilding...\nHard Restarting Bot Application Engine...</b>")
    import aiofiles
    async with aiofiles.open('restart.txt', 'w') as f: 
        await f.write(f"{m.chat.id} {msg.id}")
        
    # सॉकेट्स क्लोज़ करें और गार्बेज कलेक्ट करके फ्रेश पाइथन इंस्टेंस चालू करें
    gc.collect()
    os.execl(sys.executable, sys.executable, "bot.py")

@Client.on_message(filters.command(['leave', 'invite_link']) & filters.user(ADMINS))
async def chat_actions(c, m):
    if len(m.command) < 2: return await m.reply(f"Usage: `/{m.command[0]} chat_id`")
    try:
        cid = int(m.command[1])
        if m.command[0] == 'leave':
            await c.leave_chat(cid)
            await m.reply(f"✅ Successfully Left chat target `<code>{cid}</code>`")
        else:
            link = await c.create_chat_invite_link(cid)
            await m.reply(f"🔗 <b>Secure Invite Link Instant Generated:</b>\n\n{link.invite_link}")
    except Exception as e: 
        await m.reply(f"❌ <b>Execution Error:</b> <code>{e}</code>")

# ======================================================
# 🚫 BAN / UNBAN CONTROL CENTER (Runtime Protected)
# ======================================================
@Client.on_message(filters.command(['ban_grp', 'unban_grp', 'ban_user', 'unban_user']) & filters.user(ADMINS))
async def ban_system(c, m):
    cmd = m.command[0]
    if len(m.command) < 2: return await m.reply(f'Usage: `/{cmd} id [reason]`')
    try: 
        tgt_id = int(m.command[1])
    except: 
        return await m.reply("❌ Invalid Identification Numeric ID specified!")
    
    rsn = " ".join(m.command[2:]) or "Violation of Rules / Admin Action"
    
    if 'user' in cmd:
        if tgt_id in ADMINS: return await m.reply("❌ Security Core Violation: Cannot ban a designated Bot Admin!")
        if 'unban' in cmd:
            await db.unban_user(tgt_id)
            if tgt_id in temp.BANNED_USERS: temp.BANNED_USERS.remove(tgt_id)
            await m.reply(f"✅ User `<code>{tgt_id}</code>` Unbanned successfully.")
        else:
            await db.ban_user(tgt_id, rsn)
            if tgt_id not in temp.BANNED_USERS: temp.BANNED_USERS.append(tgt_id)
            await m.reply(f"✅ User `<code>{tgt_id}</code>` Banned from Global System.\nReason: <code>{rsn}</code>")
    else:
        if 'unban' in cmd:
            await db.re_enable_chat(tgt_id)
            if tgt_id in temp.BANNED_CHATS: temp.BANNED_CHATS.remove(tgt_id)
            await m.reply(f"✅ Group Chat `<code>{tgt_id}</code>` successfully re-enabled.")
        else:
            await db.disable_chat(tgt_id, rsn)
            if tgt_id not in temp.BANNED_CHATS: temp.BANNED_CHATS.append(tgt_id)
            await m.reply(f"✅ Group Chat `<code>{tgt_id}</code>` Blacklisted & Disabled.\nReason: <code>{rsn}</code>")
            try: await c.leave_chat(tgt_id)
            except: pass

# ======================================================
# 📜 DATABASE EXPORT MACHINE (Strict RAM Protection Sync)
# ======================================================
@Client.on_message(filters.command(['users', 'chats']) & filters.user(ADMINS))
async def export_db(c, m):
    is_user = m.command[0] == 'users'
    typ, fn = ('User', 'users.txt') if is_user else ('Chat', 'chats.txt')
    
    msg = await m.reply(f'🔄 <b>Querying MongoDB... Generating {typ} Backup List Document...</b>')
    cnt = 0
    try:
        with open(fn, 'w', encoding='utf-8') as f:
            if is_user:
                # स्ट्रिक्ट प्रोजेक्शन केवल 'id' और 'name' लोड करेगा (Zero RAM Overhead)
                cursor = db.users.find({}, {"id": 1, "name": 1})
                async for x in cursor:
                    f.write(f"ID: {x['id']} | Name: {x.get('name', 'N/A')}\n")
                    cnt += 1
            else:
                # स्ट्रिक्ट प्रोजेक्शन केवल 'id' और 'title' लोड करेगा
                cursor = db.groups.find({}, {"id": 1, "title": 1})
                async for x in cursor:
                    f.write(f"ID: {x['id']} | Title: {x.get('title', 'N/A')}\n")
                    cnt += 1
                
        if cnt == 0:
            if os.path.exists(fn): os.remove(fn)
            return await msg.edit(f"📭 {typ} Database Population is Empty.")

        await m.reply_document(fn, caption=f"📊 <b>Fast Finder Backup Report</b>\n\n👥 Total Registered {typ}s: <code>{cnt}</code>")
        await msg.delete()
        
    except Exception as e:
        logger.error(f"Error exporting database: {e}")
        await msg.edit(f"❌ Failed to generate structural database list: {e}")
    finally:
        if os.path.exists(fn): 
            os.remove(fn)
        # ✅ FIX: फाइल डिलीट होने के बाद इन-मेमोरी बफर्स को कोएब से फ्लश करने के लिए गारबेज कलेक्शन सिंक
        gc.collect()

# ======================================================
# 🆔 ADVANCED ID INSPECTOR (/id)
# ======================================================
@Client.on_message(filters.command("id"))
async def get_id(c, m):
    if is_rate_limited(m.from_user.id, "cmd_id", seconds=3):
        return

    r = m.reply_to_message
    u = r.from_user if r and r.from_user else m.from_user
    
    b = "👤 Member"
    if m.chat.type in (enums.ChatType.GROUP, enums.ChatType.SUPERGROUP):
        try:
            st = (await c.get_chat_member(m.chat.id, u.id)).status
            if st == enums.ChatMemberStatus.OWNER:
                b = "👑 Owner"
            elif st == enums.ChatMemberStatus.ADMINISTRATOR:
                b = "🛡️ Admin"
        except: 
            pass

    t = (f"🆔 <b>ID INFORMATION</b>\n\n"
         f"👤 <b>Name:</b> {u.first_name or ''} {u.last_name or ''}\n"
         f"🦹 <b>User ID:</b> <code>{u.id}</code>\n"
         f"🏷 <b>Username:</b> @{u.username or 'N/A'}\n"
         f"🌐 <b>DC ID:</b> <code>{u.dc_id or 'Unknown'}</code>\n"
         f"🤖 <b>Bot:</b> {'Yes' if u.is_bot else 'No'}\n"
         f"{b}\n🔗 <b>Profile:</b> <a href='tg://user?id={u.id}'>Open</a>\n\n"
         f"💬 <b>CHAT & MESSAGE</b>\n"
         f"🆔 <b>Chat ID:</b> <code>{m.chat.id}</code>\n"
         f"📩 <b>Msg ID:</b> <code>{m.id}</code>\n")

    if m.chat.type in (enums.ChatType.GROUP, enums.ChatType.SUPERGROUP):
        t += f"Status: <code>Active Premium Group</code>\n📛 <b>Title:</b> {m.chat.title}\n🔗 <b>Link:</b> @{m.chat.username or 'Private'}\n"

    if r and r.media:
        media = getattr(r, r.media.value, None)
        if media and getattr(media, "file_id", None):
            t += f"\n📂 <b>MEDIA DETAILS</b>\n🆔 <b>File ID:</b> <code>{media.file_id}</code>\n"

    await m.reply_text(t, parse_mode=enums.ParseMode.HTML, disable_web_page_preview=True)
