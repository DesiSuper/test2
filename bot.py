import logging
import asyncio
import os
import time
from typing import Union, AsyncGenerator
from datetime import datetime
import pytz

# ==========================================================
# 🔥 UVLOOP (High Performance C-Based Event Loop Engine)
# ==========================================================
try:
    import uvloop
    asyncio.set_event_loop_policy(uvloop.EventLoopPolicy())
except ImportError:
    pass

# ==========================================================
# 📊 LOGGING CENTER
# ==========================================================
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler()]
)
logging.getLogger('hydrogram').setLevel(logging.ERROR)
logging.getLogger('aiohttp.access').setLevel(logging.WARNING)
logging.getLogger('aiohttp.server').setLevel(logging.WARNING)

logger = logging.getLogger(__name__)

# ==========================================================
# CORE IMPORTS
# ==========================================================
from aiohttp import web
from hydrogram import Client, types, StopPropagation, idle 
from hydrogram.errors import FloodWait 
from hydrogram.handlers import MessageHandler 
from web import web_app
from info import (
    API_ID, API_HASH, BOT_TOKEN, PORT, ADMINS, 
    LOG_CHANNEL, TIME_ZONE
)
from utils import temp
from database.users_chats_db import db
from database.ia_filterdb import ensure_indexes
from plugins.premium import check_premium_expired

# ==========================================================
# ==========================================================
# ⏳ SMART AUTO-DELETE BACKGROUND WORKER (RAM Protected)
# ==========================================================
async def auto_delete_worker(bot):
    """रीस्टार्ट-प्रूफ मोंगोडीबी आधारित ऑटो-डिलीट इंजन - रैम और कैशे लीक प्रूफ पैच के साथ"""
    while True:
        try:
            cursor = await db.get_expired_delete_tasks()
            deleted_any = False
            
            async for task in cursor:
                chat_id = task["chat_id"]
                message_id = task["message_id"]
                
                try:
                    await bot.delete_messages(chat_id, message_id)
                    deleted_any = True
                except Exception as tg_err:
                    logger.debug(f"Message already deleted or unavailable in {chat_id}: {tg_err}")
                
                await db.remove_from_delete_queue(chat_id, message_id)
                
        except Exception as e:
            logger.error(f"Error in auto_delete_worker loop: {e}")
            
        await asyncio.sleep(15) # आपके नियमानुसार कतार चेकिंग का सुपरफास्ट इंटरवल

# ==========================================================
# BOT CLIENT CLASS
# ==========================================================
class Bot(Client):
    def __init__(self):
        super().__init__(
            name="Auto_Filter_Bot",
            api_id=API_ID,
            api_hash=API_HASH,
            bot_token=BOT_TOKEN,
            plugins={"root": "plugins"}
        )
        self._runner = None 
        self._premium_task = None 
        self._delete_task = None  

    async def start(self):
        # 1. Start Pyrogram/Hydrogram Client Instance
        await super().start()
        temp.START_TIME = time.time()

        # 2. Database Indexes Sync (Makkhan DB Tuning)
        await ensure_indexes()
        await db._ensure_indexes() 
        logger.info("✅ Database Connections & Indexes Fully Synced")

        # 3. Load banned users & chats into Runtime Buckets
        try:
            b_users, b_chats = await db.get_banned()
            temp.BANNED_USERS = [int(x) for x in b_users]
            temp.BANNED_CHATS = [int(x) for x in b_chats]
            logger.info(f"✅ Loaded {len(b_users)} banned users and {len(b_chats)} banned chats")
        except Exception as e:
            logger.error(f"Error loading banned list: {e}")

        # 4. Global Ban Middleware (The Strict Gatekeeper Security Guard)
        async def ban_check_middleware(client, message):
            uid = message.from_user.id if message.from_user else None
            cid = message.chat.id if message.chat else None
            if (uid and int(uid) in temp.BANNED_USERS) or (cid and int(cid) in temp.BANNED_CHATS):
                raise StopPropagation
        
        self.add_handler(MessageHandler(ban_check_middleware), group=-1)
        logger.info("🛡️ Premium Global Security Guard Activated")

        # 5. Persistent Hard Restart Logic Sync
        local_tz = pytz.timezone(TIME_ZONE)

        def build_status_msg():
            now = datetime.now(local_tz)
            return (
                "🤖 <b>Bot Restarted!</b>\n\n"
                "<blockquote>"
                f"📅 <b>Date:</b> {now.strftime('%d %B %Y')}\n"
                f"🕐 <b>Time:</b> {now.strftime('%I:%M:%S %p')}\n"
                f"🌏 <b>Timezone:</b> {TIME_ZONE}"
                "</blockquote>"
            )

        if os.path.exists("restart.txt"):
            try:
                with open("restart.txt", "r") as f:
                    content = f.read().strip().split()
                    if len(content) == 2:
                        chat_id, msg_id = map(int, content)
                        await self.edit_message_text(chat_id=chat_id, message_id=msg_id, text=build_status_msg())
            except Exception as e:
                logger.error(f"Restart message error: {e}")
            finally:
                try: os.remove("restart.txt")
                except: pass

        # 6. Set Centralized Context Registry Identity
        temp.BOT = self
        me = await self.get_me()
        temp.ME = me.id
        temp.U_NAME = me.username
        temp.B_NAME = me.first_name

        # 7. Start Web Server with Health Routes (Combined Non-Blocking Engine Loop)
        self._runner = web.AppRunner(web_app, access_log=None)
        await self._runner.setup()
        await web.TCPSite(self._runner, "0.0.0.0", PORT).start()
        logger.info(f"🌐 Web Server & Mini App Stream Live on Port {PORT}")

        # 8. Start Background Automation Tasks (Premium Engine & Auto-Delete Sync)
        self._premium_task = asyncio.create_task(check_premium_expired(self))
        self._delete_task = asyncio.create_task(auto_delete_worker(self)) 
        logger.info("⏳ Persistent Auto-Delete RAM Guard Activated")

        # 9. Send Startup Logs (Perfect info.py TIME_ZONE Sync)
        # ✅ FIX: हार्डकोडिंग हटाकर सीधे आपके कस्टमाइज्ड टाइमज़ोन इंजन से बाइंड किया गया
        startup_msg = build_status_msg()

        async def _safe_send(admin_id):
            try:
                await self.send_message(admin_id, startup_msg)
            except FloodWait as e:
                await asyncio.sleep(e.value)
                await self.send_message(admin_id, startup_msg)
            except Exception:
                pass

        await asyncio.gather(*[_safe_send(aid) for aid in ADMINS])

        if LOG_CHANNEL:
            try:
                await self.send_message(LOG_CHANNEL, f"<b>⚡ {me.mention} System Rebuilt & Synced Successfully on {TIME_ZONE}! 🚀</b>")
            except Exception as e:
                logger.warning(f"Failed to send log to LOG_CHANNEL: {e}")

        logger.info(f"@{me.username} is Smoothly Operational!")

    # ✅ GRACEFUL SHUTDOWN (Protects Database Pools & Containers)
    async def stop(self, *args):
        logger.info("Initiating Graceful Shutdown Pipeline...")
        
        if getattr(self, '_runner', None):
            await self._runner.cleanup()
            logger.info("✅ Web App Runner Cleaned Up")
        
        if getattr(self, '_premium_task', None):
            self._premium_task.cancel()
            try: await self._premium_task 
            except asyncio.CancelledError: pass
            logger.info("✅ Premium Expiry Engine Stopped")

        if getattr(self, '_delete_task', None):
            self._delete_task.cancel()
            try: await self._delete_task
            except asyncio.CancelledError: pass
            logger.info("✅ Auto-Delete Engine Flushed & Stopped")

        await super().stop()
        logger.info("System Halted Gracefully. All Memory Freed ✅")

    async def iter_messages(self, chat_id: Union[int, str], limit: int, offset: int = 0) -> AsyncGenerator["types.Message", None]:
        current = offset
        while current < limit:
            diff = min(200, limit - current)
            try:
                messages = await self.get_messages(chat_id, list(range(current, current + diff)))
                for message in messages:
                    if message and not message.empty: 
                        yield message
                current += diff
            except Exception as e:
                logger.error(f"Error fetching messages: {e}")
                return

# ==========================================================
# KICKSTART LIFE-CYCLE LOOP
# ==========================================================
async def main():
    bot = Bot()
    await bot.start()
    await idle()
    await bot.stop()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Process Interrupted Externally.")
