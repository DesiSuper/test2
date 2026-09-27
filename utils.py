import logging
import re
import time
import pytz
from datetime import datetime
from hydrogram import enums

from info import ADMINS, IS_PREMIUM, TIME_ZONE
# ✅ DRY: premium plan का reset-state dict database layer से ही आता है (एक ही जगह
# define है), ताकि utils/premium/users_chats_db तीनों में वही 11 keys रहें।
from database.users_chats_db import db, DEFAULT_PLAN_STATUS as RESET_PLAN_STATUS

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────
# 🧠 TEMP RUNTIME STORAGE (Central context bucket)
# ✅ FIX: USER_SESSIONS और REG_PENDING पहले यहाँ declared नहीं थे — login_routes.py
# में `hasattr()` चेक करके runtime पर बनाए जाते थे, और web_assets.py / dashboard_
# routes.py / users_chats_db.py में फिर `hasattr()` से पढ़े जाते थे। उसका नतीजा यह
# था कि पहले login से पहले users_chats_db.get_today_logged_in_users_count() का
# RAM-session वाला हिस्सा चुपचाप skip हो जाता था। अब सारे buckets एक ही जगह
# declared हैं, इसलिए कहीं भी hasattr guard की ज़रूरत नहीं।
# ─────────────────────────────────────────────
class temp(object):
    START_TIME = 0
    BANNED_USERS, BANNED_CHATS = [], []
    ME, BOT, U_NAME, B_NAME = None, None, None, None
    CANCEL = False
    ADMIN_TOKENS, ADMIN_SESSIONS, FILES, PM_FILES = {}, {}, {}, {}
    USER_SESSIONS = {}   # web dashboard login sessions  (web/login_routes.py)
    REG_PENDING = {}     # web registration OTP flow      (web/login_routes.py)

# ─────────────────────────────────────────────
# 🛡️ RATE LIMITER UTILITY (Aggressive RAM Flush Sync)
# ─────────────────────────────────────────────
_rate_limits = {}

def is_rate_limited(user_id, action, seconds):
    """हैवी प्रीमियम कमांड्स पर स्पैम रोकता है और रैम को फ़ोर्स फ्लश करता है।"""
    key = f"{user_id}:{action}"
    now = time.time()
    
    # स्मार्ट पीरियोдिक क्लीनअप (Koyeb RAM Safe Protection)
    if len(_rate_limits) > 300: # रैम लीक गार्ड थ्रेशोल्ड लिमिट 300 पर लॉक
        expired_keys = [k for k, exp in _rate_limits.items() if exp < now]
        for k in expired_keys:
            _rate_limits.pop(k, None)
            
    if key in _rate_limits and _rate_limits[key] > now:
        return True
        
    _rate_limits[key] = now + seconds
    return False

# ─────────────────────────────────────────────
# 👮 BOT CHAT ADMIN LOOKUP GUARD
# ─────────────────────────────────────────────
async def is_check_admin(bot, chat_id, user_id):
    try:
        return (await bot.get_chat_member(chat_id, user_id)).status in (
            enums.ChatMemberStatus.ADMINISTRATOR, 
            enums.ChatMemberStatus.OWNER
        )
    except: 
        return False

# ─────────────────────────────────────────────
# 🌍 SHARED LOCAL-TIME HELPER (naive datetime, TIME_ZONE-aware)
# ─────────────────────────────────────────────
# ⚠️ नोट: database/users_chats_db.py में भी एक get_local_now() है, लेकिन वो
# tzinfo-AWARE datetime लौटाता है (delete-queue scheduling के लिए)। यह वाला
# जानबूझकर naive (tzinfo-stripped) रखा गया है क्योंकि premium plan के 'expire'
# स्ट्रिंग्स strptime से naive datetime के रूप में पार्स होते हैं और naive vs
# tz-aware datetime compare करने पर Python TypeError देता है। इसलिए दोनों को
# जानबूझकर अलग रखा गया है, मर्ज मत करना।
def get_local_now():
    tz = pytz.timezone(TIME_ZONE)
    return datetime.now(tz).replace(tzinfo=None)

# ─────────────────────────────────────────────
# 💎 PREMIUM AUTO-VALIDATOR (Perfect info.py TIME_ZONE Sync)
# ─────────────────────────────────────────────
async def is_premium(user_id, bot=None):
    # एडमिन को हमेशा लाइफटाइम बाईपास अनलॉक रहेगा
    if not IS_PREMIUM or user_id in ADMINS: 
        return True
        
    mp = await db.get_plan(user_id)
    if not mp.get("premium"): 
        return False
    
    raw_expire = mp.get("expire")
    if raw_expire:
        # ✅ DRY: पहले यहाँ strptime try/except inline लिखा था, जो utils के ही
        # parse_expire_time() की हुबहू कॉपी थी — अब वही helper इस्तेमाल होता है।
        expire = parse_expire_time(raw_expire)
        # ✅ FIX: हार्डकोडिंग हटाकर 'info.py' के कस्टमाइज्ड 'TIME_ZONE' से शुद्ध सिंक कॉम्पैरिजन
        now_local = get_local_now()

        # नोट: unparseable expire string भी reset trigger करती है (पहले जैसा ही) —
        # वरना corrupt record वाला user हमेशा के लिए free premium पर रह जाता।
        if not expire or expire < now_local:
            if bot:
                try:
                    await bot.send_message(
                        user_id,
                        "❌ <b>Your Premium Membership Plan has Expired!</b>\n\n"
                        "Contact Admin or use /plan to activate again."
                    )
                except:
                    pass

            # प्रीमियम ख़त्म होते ही डेटाबेस में सारे रिमाइंडर फ़्लैग्स और स्टेटस को तुरंत
            # रिफ्रेश/रीसेट करें। ✅ DRY: यह 11-key वाला ब्लॉक पहले यहाँ + premium.py में
            # 3 बार कॉपी था, अब database.users_chats_db.DEFAULT_PLAN_STATUS से आता है।
            await db.update_plan(user_id, dict(RESET_PLAN_STATUS))
            return False
    return True

# ❌ FIX: 'broadcast_messages' (पुराना भारी ब्रॉडकास्ट इंजन कबाड़) पूरी तरह डिलीटेड। 
# इससे नो-रिपिटिशन रूल और क्लीन आर्किटेक्चर लागू होता है।

# ─────────────────────────────────────────────
# ⚙️ TTL SETTINGS CACHE (Bounded Memory Leak Proof)
# ─────────────────────────────────────────────
_settings_cache = {}
_CACHE_TTL = 300 

async def get_settings(group_id):
    now = time.time()
    if group_id in _settings_cache:
        data, ts = _settings_cache[group_id]
        if now - ts < _CACHE_TTL:
            return data
            
    data = await db.get_settings(group_id)
    
    # ✅ FIX: इन-मेमोरी डिक्शनरी को अनकैप्ड बढ़ने से रोकने के लिए बाउंडेड कैशे गार्ड
    if len(_settings_cache) > 200:
        sorted_keys = sorted(_settings_cache, key=lambda k: _settings_cache[k][1])
        for k in sorted_keys[:50]:
            _settings_cache.pop(k, None)
        
    _settings_cache[group_id] = (data, now)
    return data

async def save_group_settings(group_id, key, value):
    data = await get_settings(group_id)
    data[key] = value
    _settings_cache[group_id] = (data, time.time())
    await db.update_settings(group_id, data)

# ─────────────────────────────────────────────
# 📦 FORMATTING & RAIN TIME UTILS
# ─────────────────────────────────────────────
def get_size(size):
    units = ["Bytes", "KB", "MB", "GB", "TB"]
    size, i = float(size), 0
    while size >= 1024 and i < 4:
        size, i = size / 1024, i + 1
    return f"{size:.2f} {units[i]}"

def get_readable_time(seconds):
    res, periods = "", [('d', 86400), ('h', 3600), ('m', 60), ('s', 1)]
    for name, sec in periods:
        if seconds >= sec:
            val, seconds = divmod(seconds, sec)
            res += f"{int(val)}{name} "
    return res.strip() or "0s"

def get_duration_str(seconds):
    """Video/audio duration ko media-player style string me badalta hai.

    get_readable_time() se jaan-boojhkar alag hai: wo "1h 2m 3s" deta hai (uptime ke
    liye), jabki video cards par duniya bhar me "1:02:03" chalta hai.
    - duration na ho / 0 ho to "" (khali) — UI me chip hi nahi banega, "0:00" jaisa
      bekaar text nahi dikhega.
    - 1 ghante se chhota:  "M:SS"      (e.g. 12:34)
    - 1 ghante ya zyada:   "H:MM:SS"   (e.g. 1:02:03)
    """
    try:
        total = int(seconds)
    except (TypeError, ValueError):
        return ""
    if total <= 0:
        return ""
    hours, rem = divmod(total, 3600)
    minutes, secs = divmod(rem, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"

def get_wish():
    # ✅ FIX: कचरा टेक्स्ट और अशुद्धियों को हटाकर कस्टमाइज्ड टाइमज़ोन विश इंजन सिंक किया गया
    tz = pytz.timezone(TIME_ZONE)
    h = datetime.now(tz).hour
    return "ɢᴏᴏᴅ ᴍᴏʀɴɪɴɢ 🌞" if h < 12 else "ɢᴏᴏᴅ ᴀꜰᴛᴇʀɴᴏᴏɴ 🌗" if h < 18 else "ɢᴏᴏᴅ ᴇᴠᴇɴɪɴɢ 🌘"

async def get_seconds(time_string):
    # ✅ BUG FIX: पहले सिर्फ़ पूरे शब्द (min/hour/day) ही मान्य थे, आम shorthand
    # जैसे "1m"/"1h"/"1d" (जो admins आमतौर पर टाइप करते हैं, और जो खुद
    # get_readable_time() भी आउटपुट में इस्तेमाल करता है) रेगेक्स से मैच ही नहीं
    # होते थे — चुपचाप 0 return होता, जिससे "5m" वाला default delay लग जाता और
    # keyword में गलती से यूज़र का दिया समय (जैसे "1m") जुड़ जाता।
    # ⚠️ ऑर्डर ज़रूरी है: लंबे शब्द ("month","hour") पहले लिखे हैं ताकि रेगेक्स
    # उन्हें छोटे prefix ("m","h") के तौर पर गलती से आधा-अधूरा मैच न कर ले।
    match = re.match(
        r"(\d+)\s*(month|min|mo|m|hour|hr|h|day|d|year|y|sec|s)$",
        time_string.strip(),
        re.IGNORECASE
    )
    if not match:
        return 0
    unit = match.group(2).lower()
    return int(match.group(1)) * {
        "s": 1, "sec": 1,
        "m": 60, "min": 60,
        "h": 3600, "hr": 3600, "hour": 3600,
        "d": 86400, "day": 86400,
        "mo": 2592000, "month": 2592000,
        "y": 31536000, "year": 31536000,
    }.get(unit, 0)

# 🛠️ PREMIUM LIFECYCLE TIME PARSERS
def parse_expire_time(e):
    if isinstance(e, datetime): 
        return e
    try: 
        return datetime.strptime(e, "%Y-%m-%d %H:%M:%S") if e else None
    except: 
        return None

# ❌ DEAD CODE REMOVED: यहाँ एक get_ist_str() था जो dt में +5:30 जोड़कर फॉर्मेट
# करता था। पूरे repo में इसकी एक भी call नहीं थी (plugins/premium.py का अपना
# format_plan_expiry() ही असली इस्तेमाल होता है, और वो +5:30 नहीं जोड़ता क्योंकि
# premium का expire पहले से local time में स्टोर है)। नाम एक जैसा होने से यह सिर्फ़
# confusion पैदा करता था, इसलिए हटा दिया गया।

async def safe_del(c, cid, mids):
    try: 
        await c.delete_messages(cid, mids)
    except: 
        pass
