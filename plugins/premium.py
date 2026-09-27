import io
import qrcode
import asyncio
import logging
import gc
from datetime import timedelta

# ─────────────────────────────────────────────────────────
# 🔥 CRITICAL EXPLICIT PATCH: Forced Event Loop for Pyromod & uvloop Sync
# ─────────────────────────────────────────────────────────
try:
    asyncio.get_running_loop()
except RuntimeError:
    try:
        import uvloop
        asyncio.set_event_loop_policy(uvloop.EventLoopPolicy())
    except ImportError:
        pass
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

# Ab pyromod bina kisi thread crash ke safely load hoga
import pyromod.listen  # noqa: F401  (side-effect import: Client.listen() isi se aata hai)
from hydrogram import Client, filters
from hydrogram.types import InlineKeyboardButton, InlineKeyboardMarkup

# डेटाबेस इम्पोर्ट्स
from database.users_chats_db import db, web_db 
from info import (
    IS_PREMIUM, PRE_DAY_AMOUNT, RECEIPT_SEND_USERNAME,
    UPI_ID, UPI_NAME, ADMINS, LOG_CHANNEL,
    PREMIUM_REMINDER_BUSY_GAP
)
from Script import script
# DUPLICATION FIX: parse_expire_time, safe_del, get_local_now pehle yahan
# duplicate the huye the, ab utils.py se reuse ho rahe hain (utils.py hi wo
# jagah hai jise filter.py/commands.py/search_api.py sab use karte hain).
# Is file ka apna 'is_premium(uid, bot)' poori tarah hataya gaya - wo kahin
# bhi call nahi hota tha (dead code), baki sab jagah utils.is_premium hi
# use hota hai.
# ✅ DRY: RESET_PLAN_STATUS bhi ab utils/database se aata hai - pehle yahan 11-key
# wala reset dict 3 baar (check_premium_expired, manage_premium, pay_action) copy tha.
from utils import (
    get_local_now, parse_expire_time, safe_del, RESET_PLAN_STATUS
)

logger = logging.getLogger(__name__)
VERIFY_CACHE = {}

ADMIN_MSG = "👑 <b>You are the Admin!</b>\nYou have Lifetime Premium access."
ADMIN_ALERT = "👑 You are the Admin! You have Lifetime Premium access."

# =========================================
# Is file ke liye bacha hua akela lifecycle helper
# =========================================
# NOTE: naam badla (pehle get_ist_str tha) - utils.py mein usi naam ka ek dead
# function tha jo dt mein +5:30 jodta tha, aur dono ka kaam alag tha, isliye
# confusion hota tha. Premium plan ka 'expire' get_local_now() (naive, pehle se
# local time) se banta hai, isliye yahan +5:30 NAHI jodna hai - jodne par time
# double-shifted (galat) dikhega.
def format_plan_expiry(dt):
    """Premium expiry ko sundar padhne-yogya string mein render karta hai"""
    return dt.strftime("%d %B %Y, %I:%M %p") if dt else "Unknown"

# =========================================
# ⏰ SMART AUTOMATED REMINDER PIPELINE
# =========================================
async def check_premium_expired(bot):
    intervals = [
        (715, 725, "reminded_12h", "⏰ <b>Premium Reminder</b>\n\nYour plan expires in <b>12 Hours</b>.\n🗓 {}"),
        (355, 365, "reminded_6h", "⚠️ <b>Premium Alert</b>\n\nYour plan expires in <b>6 Hours</b>.\n🗓 {}"),
        (175, 185, "reminded_3h", "⚠️ <b>Urgent Alert</b>\n\nYour plan expires in <b>3 Hours</b>.\n🗓 {}"),
        (55, 65, "reminded_1h", "🚨 <b>Critical Alert</b>\n\nYour plan expires in <b>1 Hour</b>.\n🗓 {}"),
        (25, 35, "reminded_30m", "⏳ <b>Final Warning</b>\n\nYour plan expires in <b>30 Minutes</b>.\nRenew immediately!"),
        (5, 15, "reminded_10m", "🔥 <b>Expiring Soon</b>\n\nYour plan expires in <b>10 Minutes</b>.\nService will stop soon.")
    ]
    
    while True:
        try:
            now = get_local_now()
            limit_time = (now + timedelta(hours=13)).strftime("%Y-%m-%d %H:%M:%S")
            
            cursor = db.premium.find(
                {"status.premium": True, "status.expire": {"$lte": limit_time}},
                {"id": 1, "status": 1}
            )
            
            async for p in cursor:
                uid, mp = p["id"], p.get("status", {})
                exp = parse_expire_time(mp.get("expire"))
                if not exp: continue
                
                left_mins = (exp - now).total_seconds() / 60
                
                if left_mins <= 0:
                    if mp.get("last_reminder_id"): await safe_del(bot, uid, [mp.get("last_reminder_id")])
                    try: 
                        await bot.send_message(
                            uid, 
                            "❌ <b>Your Premium Plan has Expired!</b>\n\nRenew now to unlock access.", 
                            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("💎 Buy Premium Plan", callback_data="buy_prem")]])
                        )
                    except: pass
                    await db.update_plan(uid, dict(RESET_PLAN_STATUS))
                    continue

                for min_t, max_t, flag, text in intervals:
                    if min_t <= left_mins <= max_t and not mp.get(flag):
                        if mp.get("last_reminder_id"): await safe_del(bot, uid, [mp.get("last_reminder_id")])
                        try:
                            msg = await bot.send_message(uid, text.format(format_plan_expiry(exp)), reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("💎 Renew Now", callback_data="buy_prem")]]))
                            mp.update({flag: True, "last_reminder_id": msg.id})
                            await db.update_plan(uid, mp)
                        except: pass
                        break
                        
            gc.collect()
            
        except Exception as e: 
            logger.error(f"Premium Loop Error: {e}")
        
        await asyncio.sleep(PREMIUM_REMINDER_BUSY_GAP)

# =========================================
# 📱 REBUILT USER & ADMIN COMMANDS
# =========================================
@Client.on_message(filters.command("myplan") & filters.private)
async def myplan_cmd(c, m):
    if not IS_PREMIUM: return
    if m.from_user.id in ADMINS: return await m.reply(ADMIN_MSG, quote=True)
        
    mp = await db.get_plan(m.from_user.id)
    if not mp.get("premium"):
        return await m.reply("❌ <b>No Active Premium Subscription Found!</b>\n\nTap below to activate plan.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("💎 Buy Premium Plan", callback_data="buy_prem")]]))
    
    exp = parse_expire_time(mp.get("expire"))
    now = get_local_now()
    left = f"{(exp - now).days} days, {(exp - now).seconds // 3600} hours" if exp else "Unknown"
    await m.reply(f"💎 <b>Premium Status Summary</b>\n\n📦 <b>Plan Active:</b> {mp.get('plan')}\n🗓 <b>Expires On:</b> {format_plan_expiry(exp)}\n⏲ <b>Time Remaining:</b> {left}", quote=True)

@Client.on_message(filters.command("plan") & filters.private)
async def plan_cmd(c, m):
    if not IS_PREMIUM: return
    if m.from_user.id in ADMINS: return await m.reply(ADMIN_MSG, quote=True)
    await m.reply(script.PLAN_TXT.format(PRE_DAY_AMOUNT, RECEIPT_SEND_USERNAME), reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("💎 Activate Premium Now", callback_data="buy_prem")]]))

@Client.on_message(filters.command(["add_prm", "rm_prm"]) & filters.user(ADMINS))
async def manage_premium(c, m):
    if not IS_PREMIUM: return
    cmd, is_add = m.command, m.command[0] == "add_prm"
    if len(cmd) < 2: return await m.reply(f"Usage: `/{cmd[0]} user_id {'days' if is_add else ''}`")
    
    try: uid, days = int(cmd[1]), int(cmd[2][:-1] if cmd[2].endswith('d') else cmd[2]) if is_add and len(cmd) > 2 else 0
    except: return await m.reply("❌ Invalid ID/Days Format Specified!")

    if is_add:
        if days <= 0: return await m.reply("❌ <b>Error:</b> Days must be at least 1.")
        ex = get_local_now() + timedelta(days=days)
        data = {**RESET_PLAN_STATUS, "expire": ex.strftime("%Y-%m-%d %H:%M:%S"), "plan": f"{days} Days", "premium": True}
        m_usr, m_adm = f"🎉 <b>Premium Plan Activated!</b>\n\n🗓 <b>Duration Added:</b> {days} Days\n📅 <b>Expires On:</b> {format_plan_expiry(ex)}\n\nEnjoy our superfast streaming services! ❤️", f"✅ Added {days} days premium to token `{uid}`."
    else:
        data, m_usr, m_adm = {"expire": None, "plan": "", "premium": False}, "❌ <b>Your Premium Access has been Removed by Admin.</b>", f"🗑 Revoked premium privileges from token `{uid}`."

    await db.update_plan(uid, data)
    await m.reply(m_adm)
    
    for action in (lambda: c.send_message(uid, m_usr), lambda: c.send_message(LOG_CHANNEL, f"#PremiumUpdate\nUser: `{uid}`\nAction: {cmd[0]}")):
        try: await action()
        except: pass

@Client.on_message(filters.command("prm_list") & filters.user(ADMINS))
async def prm_list(c, m):
    if not IS_PREMIUM: return
    msg, count, text = await m.reply("🔄 Fetching Active Members Database..."), 0, "💎 <b>Active Premium Members List</b>\n\n"
    async for u in await db.get_premium_users():
        if u.get("status", {}).get("premium"):
            count += 1
            text += f"👤 <code>{u['id']}</code> | 🗓 {u['status'].get('plan')}\n"
    await msg.edit(text + (f"\n<b>Total Users Count:</b> {count}" if count > 0 else "📭 No active premium users found."))

@Client.on_message(filters.command("web_users") & filters.user(ADMINS))
async def list_web_users(c, m):
    msg = await m.reply("🔄 Fetching Web Server Registration Logs...")
    count = 0
    text = "🌐 <b>Fast Finder Registered Web Users</b>\n\n"
    async for u in web_db.col.find({}, {"tg_id": 1, "email": 1, "joined_date": 1}): 
        count += 1
        joined = u.get('joined_date')
        joined_str = joined.strftime("%d %b %Y") if joined else "Unknown"
        text += f"👤 <b>TG ID:</b> <code>{u['tg_id']}</code>\n📧 <b>Email:</b> {u['email']}\n📅 <b>Joined On:</b> {joined_str}\n\n"
        
    if count == 0:
        await msg.edit("📭 अभी तक किसी भी यूजर ने वेबसाइट डैशबोर्ड पर रजिस्टर नहीं किया है।")
    else:
        text += f"<b>Total Web Dashboard Users:</b> {count}"
        await msg.edit(text)

# =========================================
# 📤 INLINE INTERFACE CALLBACKS
# =========================================
@Client.on_callback_query(filters.regex("^myplan$"))
async def myplan_cb(client, query):
    if query.from_user.id in ADMINS: return await query.answer(ADMIN_ALERT, show_alert=True)
    if not IS_PREMIUM: return await query.answer("Premium system disabled.", show_alert=True)
    
    mp = await db.get_plan(query.from_user.id)
    btn = [[InlineKeyboardButton("⬅️ Back Menu", callback_data="back_start")]]
    
    if not mp.get('premium'):
        btn.insert(0, [InlineKeyboardButton('💎 Buy Premium Plan', callback_data='activate_plan')])
        return await query.message.edit_caption("❌ No active premium subscription plan found.", reply_markup=InlineKeyboardMarkup(btn))
    
    exp = parse_expire_time(mp.get('expire'))
    now = get_local_now()
    left = f"{(exp - now).days} days, {(exp - now).seconds//3600} hours" if exp else "Unknown"
    await query.message.edit_caption(f"💎 <b>Premium Subscription Status</b>\n\n📦 Plan Model: {mp.get('plan')}\n⏳ Expires: {format_plan_expiry(exp)}\n⏱ Duration Left: {left}\n\nUse /plan to extend duration.", reply_markup=InlineKeyboardMarkup(btn))

@Client.on_callback_query(filters.regex(r"^(buy_prem|activate_plan)$"))
async def buy_callback(c, q):
    if q.from_user.id in ADMINS: return await q.answer(ADMIN_ALERT, show_alert=True)

    prm_msg = await q.message.edit(f"💎 <b>Select Plan Duration Mode</b>\n\nReply to this message with total days (e.g. <code>30</code>).\nPrice: ₹{PRE_DAY_AMOUNT} / Per Day\n\n⏳ Timeout Session: 60s")
    try:
        resp = await c.listen(q.message.chat.id, timeout=60)
        await safe_del(c, q.message.chat.id, [prm_msg.id, resp.id])
        days = int(resp.text)
        
        if days <= 0: return await q.message.reply("❌ <b>Invalid Duration Selection!</b> Days must be at least 1.")
        amount = days * int(PRE_DAY_AMOUNT)
        
        img = await asyncio.to_thread(qrcode.make, f"upi://pay?pa={UPI_ID}&pn={UPI_NAME}&am={amount}&cu=INR")
        bio = io.BytesIO()
        img.save(bio, format="PNG")
        bio.seek(0)
        
        qr_msg = await q.message.reply_photo(photo=bio, caption=f"💳 <b>UPI SECURE PAYMENT INSTANT GENERATED</b>\n\n» Amount To Pay: <code>₹{amount}</code>\n» Subscription Pack: <code>{days} Days</code>\n\nScan QR & pay. Then send payment screenshot here within 5 mins 👇\n\n⏳ Timeout Session: 5 mins")
        receipt = await c.listen(q.message.chat.id, timeout=300)
        
        if not receipt.photo: return await q.message.reply("❌ <b>Invalid Asset Sent!</b> Please send valid transaction receipt photo only.")
        
        await safe_del(c, q.message.chat.id, [qr_msg.id])
        VERIFY_CACHE[q.from_user.id] = (await q.message.reply("✅ <b>Transaction Sent to Admin Panel for Verification!</b>\nYour premium pack will activate shortly.")).id
        
        await receipt.copy(RECEIPT_SEND_USERNAME, caption=f"#Payment\n👤 Profile: {q.from_user.mention} (<code>{q.from_user.id}</code>)\n💰 Amount: ₹{amount} ({days} days)", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("✅ Approve Payment", callback_data=f"pay_confirm_{q.from_user.id}_{days}"), InlineKeyboardButton("❌ Reject Invoice", callback_data=f"pay_reject_{q.from_user.id}")]]))
    except ValueError: await q.message.reply("❌ Invalid Numeric Entry!")
    except asyncio.TimeoutError:
        VERIFY_CACHE.pop(q.from_user.id, None)
        await q.message.reply("⏳ <b>Transaction Window Timeout!</b> Process cancelled.")
    except Exception as e: await q.message.reply(f"❌ <b>Execution Error:</b> <code>{e}</code>")

@Client.on_callback_query(filters.regex(r"^pay_(confirm|reject)_"))
async def pay_action(c, q):
    if q.from_user.id not in ADMINS: return await q.answer("❌ Verification Access Denied!", show_alert=True)
    
    tokens = q.data.split("_")
    act = tokens[1]
    uid = int(tokens[2])

    if act == "confirm":
        days = int(tokens[3])
        ex = get_local_now() + timedelta(days=days)
        await db.update_plan(uid, {**RESET_PLAN_STATUS, "expire": ex.strftime("%Y-%m-%d %H:%M:%S"), "plan": f"{days} Days", "premium": True})
        await q.message.edit_caption(caption=q.message.caption + f"\n\n✅ <b>Approved by:</b> {q.from_user.mention}", reply_markup=None)
        try: await c.send_message(uid, f"🎉 <b>Congratulations Member!</b>\n\n✅ Your premium plan of <b>{days} Days</b> is successfully Active.\n📅 <b>Expires On:</b> {format_plan_expiry(ex)}\n\nEnjoy our lightning fast search, streaming & download benefits! ❤️")
        except: pass
    else:
        await q.message.edit_caption(caption=q.message.caption + f"\n\n❌ <b>Rejected by:</b> {q.from_user.mention}", reply_markup=None)
        try: await c.send_message(uid, "❌ <b>Subscription Invoice Verification Rejected!</b>\nPlease check screenshot or contact admin manually.")
        except: pass
        
    if uid in VERIFY_CACHE:
        await safe_del(c, uid, [VERIFY_CACHE.pop(uid)])
    gc.collect()
