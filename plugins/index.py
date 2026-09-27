import re
import time
import asyncio
import logging
import gc
from hydrogram import Client, filters, enums
from hydrogram.errors import FloodWait
from info import ADMINS, LOG_CHANNEL
from database.ia_filterdb import save_file
from media_probe import probe_telegram_file, should_probe_media
from hydrogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from utils import temp, get_readable_time
from Script import script

logger = logging.getLogger(__name__)
lock = asyncio.Lock()

# ─────────────────────────────────────────────
# 🧩 SHARED UI BUILDERS
# ✅ DRY: collection-picker का button-set + edit-text यहाँ दो बार हुबहू लिखा था
# (`ident == 'yes'` और `ident == 'ask_skip'` branches में) और indexing status text
# तीन बार (cancel / progress / complete)। एक जगह counter rename करना हो तो 3 जगह
# edit करना पड़ता था। अब दोनों एक ही helper से बनते हैं।
# ─────────────────────────────────────────────
def collection_picker_markup(chat, lst_msg_id, skip):
    """Primary / Cloud / Archive चुनने वाला inline keyboard"""
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton('✅ PRIMARY', callback_data=f'index#start#{chat}#{lst_msg_id}#{skip}#primary'),
            InlineKeyboardButton('📂 CLOUD', callback_data=f'index#start#{chat}#{lst_msg_id}#{skip}#cloud')
        ],
        [
            InlineKeyboardButton('📦 ARCHIVES', callback_data=f'index#start#{chat}#{lst_msg_id}#{skip}#archive')
        ],
        [
            InlineKeyboardButton('❌ CANCEL', callback_data='close_data')
        ]
    ])

async def show_collection_picker(query, chat, lst_msg_id, skip):
    await query.message.edit(
        "🗂️ <b>Select Collection to Index:</b>\n"
        f"⏭️ Skip: <code>{skip}</code>\n\n"
        "• <b>PRIMARY</b> - Main database\n"
        "• <b>CLOUD</b> - Cloud storage\n"
        "• <b>ARCHIVES</b> - Archive storage",
        reply_markup=collection_picker_markup(chat, lst_msg_id, skip)
    )

def index_status_text(collection_type, time_taken, current, saved, duplicate,
                      deleted, no_media, unsupported, errors, badfiles):
    """Indexing progress/final report — cancel, progress और complete तीनों यही use करते हैं"""
    return (
        f"📚 Collection: <code>{collection_type.upper()}</code>\n"
        f"⏱ Time: <code>{time_taken}</code>\n\n"
        f"📨 Total Received: <code>{current}</code>\n"
        f"📁 Saved Files: <code>{saved}</code>\n"
        f"🔄 Duplicates: <code>{duplicate}</code>\n"
        f"🗑 Deleted: <code>{deleted}</code>\n"
        f"❌ No Media: <code>{no_media + unsupported}</code>\n"
        f"⚠️ Unsupported: <code>{unsupported}</code>\n"
        f"❗ Errors: <code>{errors}</code>\n"
        f"🚫 Bad Files: <code>{badfiles}</code>"
    )

@Client.on_callback_query(filters.regex(r'^index'))
async def index_files(bot, query):
    data_parts = query.data.split("#")
    ident = data_parts[1]
    
    if ident == 'yes':
        chat = data_parts[2]
        lst_msg_id = data_parts[3]
        skip = data_parts[4]
        
        await show_collection_picker(query, chat, lst_msg_id, skip)

    elif ident == 'ask_skip':
        chat = data_parts[2]
        lst_msg_id = data_parts[3]
        
        await query.message.edit("📝 <b>Send the number of messages to skip:</b>\n\nSend <code>0</code> to start from beginning.")
        
        try:
            msg = await bot.listen(chat_id=query.message.chat.id, user_id=query.from_user.id, timeout=60)
            skip = int(msg.text)
            await msg.delete()
        except:
            return await query.message.edit("❌ Invalid number or Timeout. Try again.")
            
        await show_collection_picker(query, chat, lst_msg_id, skip)

    
    elif ident == 'start':
        chat = data_parts[2]
        lst_msg_id = data_parts[3]
        skip = data_parts[4]
        collection = data_parts[5]
        
        msg = query.message
        await msg.edit(f"Starting Indexing to <b>{collection.upper()}</b> collection...")
        
        try: chat = int(chat)
        except: pass
        
        await index_files_to_db(int(lst_msg_id), chat, msg, bot, int(skip), collection)
    
    elif ident == 'cancel':
        temp.CANCEL = True
        await query.message.edit("Trying to cancel Indexing...")


@Client.on_message(filters.private & filters.user(ADMINS) & (filters.forwarded | filters.text))
async def auto_index(bot, message):
    if message.text and not message.text.startswith("https://t.me"):
        if not message.forward_from_chat:
            return
    
    if lock.locked():
        return await message.reply('⏳ Wait until previous indexing process completes.')
    
    if message.forward_from_chat and message.forward_from_chat.type == enums.ChatType.CHANNEL:
        last_msg_id = message.forward_from_message_id
        chat_id = message.forward_from_chat.username or message.forward_from_chat.id
    
    elif message.text and message.text.startswith("https://t.me"):
        try:
            msg_link = message.text.split("/")
            last_msg_id = int(msg_link[-1])
            chat_id = msg_link[-2]
            if chat_id.isnumeric():
                chat_id = int(("-100" + chat_id))
        except:
            return await message.reply('❌ Invalid message link!')
    else:
        return
    
    try:
        chat = await bot.get_chat(chat_id)
    except Exception as e:
        return await message.reply(f'❌ Error: {e}')

    if chat.type != enums.ChatType.CHANNEL:
        return await message.reply("⚠️ I can only index channels.")

    buttons = [
        [
            InlineKeyboardButton('⚡ START INDEXING (Skip 0)', callback_data=f'index#yes#{chat_id}#{last_msg_id}#0')
        ],
        [
            InlineKeyboardButton('📝 CUSTOM SKIP', callback_data=f'index#ask_skip#{chat_id}#{last_msg_id}')
        ],
        [
            InlineKeyboardButton('❌ CANCEL', callback_data='close_data')
        ]
    ]
    await message.reply(
        f'🗂️ <b>Ready to Index:</b>\n\n'
        f'📢 Channel: <b>{chat.title}</b>\n'
        f'📨 Total Messages: <code>{last_msg_id}</code>\n\n'
        f'Choose an option:',
        reply_markup=InlineKeyboardMarkup(buttons)
    )


async def index_files_to_db(lst_msg_id, chat, msg, bot, skip, collection_type="primary"):
    start_time = time.time()
    last_update_time = time.time()
    
    total_files = 0
    duplicate = 0
    errors = 0
    deleted = 0
    no_media = 0
    unsupported = 0
    badfiles = 0
    current = skip
    
    # लॉगर इन्फो के लिए चैनल टाइटल निकालें
    try:
        chat_obj = await bot.get_chat(chat)
        chat_title = chat_obj.title
        chat_id_str = str(chat_obj.id)
    except:
        chat_title = "Unknown Channel"
        chat_id_str = str(chat)

    async with lock:
        try:
            async for message in bot.iter_messages(chat, lst_msg_id, skip):
                time_taken = get_readable_time(time.time() - start_time)
                
                if temp.CANCEL:
                    temp.CANCEL = False
                    await msg.edit(
                        "<b>✅ Successfully Cancelled!</b>\n"
                        + index_status_text(collection_type, time_taken, current, total_files,
                                            duplicate, deleted, no_media, unsupported, errors, badfiles)
                    )
                    
                    # ✅ FIX: कैंसिल होने पर भी LOG_CHANNEL में पूरी रिपोर्ट पुश करें
                    if LOG_CHANNEL:
                        try:
                            await bot.send_message(
                                LOG_CHANNEL,
                                script.LOG_INDEX_TXT.format(chat_title, chat_id_str, collection_type.upper(), current, total_files, duplicate, unsupported, errors) + "\n\n⚠️ <b>Status:</b> <code>Cancelled by Admin 🛑</code>"
                            )
                        except: pass
                    return
                
                current += 1
                
                # टेलीग्राम फ्लड प्रिवेंटर — हर 50 मैसेज + न्यूनतम 4 सेकंड का टाइम इंटरवल गैप
                if current % 50 == 0 and (time.time() - last_update_time > 4):
                    last_update_time = time.time()
                    btn = [[
                        InlineKeyboardButton('CANCEL', callback_data=f'index#cancel#{chat}#{lst_msg_id}#{skip}')
                    ]]
                    try:
                        await msg.edit_text(
                            text="<b>📊 Indexing Progress</b>\n"
                                 + index_status_text(collection_type, time_taken, current, total_files,
                                                     duplicate, deleted, no_media, unsupported, errors, badfiles),
                            reply_markup=InlineKeyboardMarkup(btn)
                        )
                    except FloodWait as e:
                        await asyncio.sleep(e.value)
                    except Exception:
                        pass
                    
                    # कोएब रैम कैशे क्लीनअप सिंक
                    gc.collect()
                
                if message.empty:
                    deleted += 1
                    continue
                elif not message.media:
                    no_media += 1
                    continue
                elif message.media not in [enums.MessageMediaType.VIDEO, enums.MessageMediaType.DOCUMENT]:
                    unsupported += 1
                    continue
                
                media = getattr(message, message.media.value, None)
                if not media:
                    unsupported += 1
                    continue
                
                file_size = getattr(media, 'file_size', 0)
                if collection_type != 'archive' and file_size < 2097152:
                    badfiles += 1
                    continue
                
                media.caption = message.caption


                # 🔍 Asli w/h/duration file BYTES se probe — nayi files me wahi
                # 1280×720-default gadbad na aaye jo purani files me aayi thi
                # (uploader ke Telegram attributes par bharosa nahi).
                # Best-effort: fail ho to attributes use hote hain. Probe kabhi
                # indexing nahi rokta — FloodWait bhi yahin dabta hai (warna ek
                # flood par poora index cancel ho jaata, jo outer handler karta hai).
                probed = {}
                try:
                    if should_probe_media(media, getattr(media, 'file_name', '') or ''):
                        probed = await probe_telegram_file(
                            bot, media.file_id,
                            file_size=file_size or 0,
                            file_name=str(getattr(media, 'file_name', '') or ''),
                        )
                except Exception as e:
                    logger.debug(f"[INDEX] probe skipped: {str(e)[:80]}")
                    probed = {}

                sts = await save_file(media, collection_type=collection_type,
                                      probed=probed or None)
                
                if sts == 'suc':
                    total_files += 1
                elif sts == 'dup':
                    duplicate += 1
                elif sts == 'err':
                    errors += 1
                    
        except Exception as e:
            logger.error(f"Indexing Crash Intercepted: {e}")
            await msg.reply(f'❌ Index canceled due to Error - {e}')
        else:
            time_taken = get_readable_time(time.time() - start_time)
            await msg.edit(
                "<b>✅ Successfully Indexed!</b>\n"
                + index_status_text(collection_type, time_taken, current, total_files,
                                    duplicate, deleted, no_media, unsupported, errors, badfiles)
            )
            
            # 📢 ✅ FIX: इंडेक्सिंग सफलतापूर्वक ख़त्म होते ही LOG_CHANNEL में सुपर रिपोर्ट भेजें
            if LOG_CHANNEL:
                try:
                    await bot.send_message(
                        LOG_CHANNEL,
                        script.LOG_INDEX_TXT.format(
                            chat_title, 
                            chat_id_str, 
                            collection_type.upper(), 
                            current, 
                            total_files, 
                            duplicate, 
                            unsupported, 
                            errors
                        )
                    )
                except Exception as log_err:
                    logger.error(f"Failed to send indexing log to LOG_CHANNEL: {log_err}")
        finally:
            gc.collect() # अंतिम इन-मेमोरी क्लीनअप पैश ताकि कोएब रैम खाली रहे
