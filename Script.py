class script(object):

    # 🍿 आपके लाइव फीचर्स और प्रीमियम मॉडल के अनुसार स्टार्ट टेक्स्ट (DM locked logic ready)
    START_TXT = """<blockquote><b><i>Hey {}, {}</i></b></blockquote>
<blockquote><b><i>I am a powerful & smart auto filter bot! I can provide movies and series with direct stream & download links. 🚀</i></b></blockquote>

🍿 <b><u>My Main Features:</u></b>

<blockquote><b><i>Smart Auto Filter In Chat Groups</i></b></blockquote>
<blockquote><b><i>📱 Advanced Mini App Cinematic Search</i></b></blockquote>
<blockquote><b><i>🎬 In-Built Player With Double-Tap Skip</i></b></blockquote>
<blockquote><b><i>⚡ Superfast Direct Download Links</i></b></blockquote>
<blockquote><b><i>🛡️ Auto Delete Queue (Restart Proof)</i></b></blockquote>
<blockquote><b><i>✨ Join Premium For Ads Free Experience</i></b></blockquote>"""

    # 📊 ✅ NEW PREMIUM UI: एकदम नया मॉडर्न लुक जिसमें Directory भी शामिल है (Admin Only)
    STATUS_TXT = """<b>🤖 Fast Finder System Telemetry</b>

<b>👥 <u>Network Dynamics:</u></b>
<blockquote><b>🤵 Users:</b> <code>{}</code>
<b>🏘️ Groups:</b> <code>{}</code>
<b>💎 Premium:</b> <code>{}</code></blockquote>

<b>🗄️ <u>Data Centre (Total: {}):</u></b>
<blockquote><b>🟢 Primary:</b> <code>{}</code> (🖼️ <code>{}</code>)
<b>🔵 Cloud:</b> <code>{}</code> (🖼️ <code>{}</code>)
<b>🟠 Archive:</b> <code>{}</code> (🖼️ <code>{}</code>)</blockquote>

<b>🗂️ <u>Universal Directory (Total: {}):</u></b>
<blockquote><b>🎭 Actors:</b> <code>{}</code>
<b>📱 Apps:</b> <code>{}</code>
<b>🌐 Websites:</b> <code>{}</code></blockquote>

<b>📝 <u>Posts CMS (Total: {}):</u></b>
<blockquote><b>🎬 Movies:</b> <code>{}</code>
<b>📺 Web Series:</b> <code>{}</code>
<b>📱 App Video:</b> <code>{}</code>
<b>🔞 Porn:</b> <code>{}</code></blockquote>

<b>⚙️ <u>Engine Metrics:</u></b>
<blockquote><b>🖼️ Global Thumbs:</b> <code>{}</code>
<b>⏱️ Uptime:</b> <code>{}</code></blockquote>"""

    # ✅ सिर्फ प्रीमियम/नॉर्मल यूज़र्स के लिए ग्लोबल लाइब्रेरी स्टैट्स
    USER_STATUS_TXT = """<b>📊 Fast Finder Global Library</b>

<b>🗄️ <u>Content Vault:</u></b>
<blockquote><b>🚀 Total Titles:</b> <code>{}</code>
<b>🟢 Primary:</b> <code>{}</code>
<b>🔵 Cloud:</b> <code>{}</code>
<b>🟠 Archive:</b> <code>{}</code></blockquote>

<b>🗂️ <u>Universal Directory:</u></b>
<blockquote><b>🌟 Total Profiles:</b> <code>{}</code>
<b>🎭 Actors:</b> <code>{}</code>
<b>📱 Apps:</b> <code>{}</code>
<b>🌐 Websites:</b> <code>{}</code></blockquote>

<b>📝 <u>Posts Published:</u></b> <code>{}</code>

<b>⏱️ System Running Since:</b> <code>{}</code>"""

    NEW_GROUP_TXT = """<b>#NewGroup 👥\n\n• Title: {}\n• ID: <code>{}</code>\n• Username: {}\n• Total Members: <code>{}</code></b>"""

    NEW_USER_TXT = """<b>#NewUser 👤\n\n• Name: {}\n• ID: <code>{}</code></b>"""

    NOT_FILE_TXT = """<b>❌ Hey {}, "{}" is not found in my database. 

💡 <u>Please Check:</u>
» Spelling should be correct (check Google)
» Search with movie name only ( things like 4k, Bluray, Season, Year हटा दें)</b>"""

    FILE_CAPTION = """<b>{file_name}</b>"""



    HELP_TXT = """<blockquote><b>👋 Hello {},</b></blockquote>

<b>Fast. Smart. Powerful.

Choose a category below. 👇</b>"""

    ADMIN_COMMAND_TXT = """<blockquote><b>👑 <u>Bot Admin Commands:</u> 👇</b></blockquote>

• /stats - Database stats
• /delete - Delete file
• /delete_all - Clear collection
• /add_prm - Add premium
• /rm_prm - Remove premium
• /prm_list - Premium users
• /web_users - Web users
• /warmup_thumbs - Refresh thumbnails
• /migrate_meta - Probe true resolution, fill missing meta &amp; fix file types
• /restart - Restart bot
• /users - Export users.txt backup
• /chats - Export chats.txt backup

<blockquote><b>🛠️ <u>Bot Maintenance:</u> 👇</b></blockquote>

• /leave &lt;chat_id&gt; - Leave a chat
• /invite_link &lt;chat_id&gt; - Generate invite link
• /ban_grp | /unban_grp &lt;id&gt; [reason] - Ban / unban a group
• /ban_user | /unban_user &lt;id&gt; [reason] - Ban / unban a user
• /check_db - Primary → cloud migration check
• /cancel - Cancel a running /check_db

<blockquote><b>⚙️ <u>Group Commands:</u> 👇</b></blockquote>

• /search - Auto Filter
• /settings - Group settings
• /button_style - Result style"""
    
    PLAN_TXT = """💎 <b>Fast Finder Premium Plans</b> 💎

Activate a premium plan to unlock exclusive, high-speed features!

⚡ <b>Price:</b> <code>₹{} / Per Day</code> ⚡

🚀 <b>Premium Features Include:</b>
» 🍿 Ad-Free Experience (No interruptions)
» 🎬 Online Streaming & Superfast Downloads
» 🔓 No Need to Join Extra Channels (No FSUB)
» ⚡ Zero Verification / Shortlinks Required
» 👑 Dedicated Admin Support

👨‍🚒 <b>Support & Verification:</b> {}"""

    USER_COMMAND_TXT = """<blockquote><b>👨‍💻 <u>Bot User Commands:</u> 👇</b></blockquote>

• /start - Main menu
• /plan - Premium plans
• /myplan - Premium status
• /id - User & Chat ID
• /link - Watch & Download link (reply to media, Premium)"""

    LOG_INDEX_TXT = """📢 <b>#Indexing_Report 📊</b>

<b>📂 Storage Parameters:</b>
» Chat Title: <code>{}</code>
» Chat ID: <code>{}</code>
» Collection Targeted: <code>{}</code>

<b>📈 Execution Statistics:</b>
» Total Processed: <code>{}</code> Files
» Successfully Saved: <code>{}</code> Files
» Duplicates Skipped: <code>{}</code> Files
» Unsupported Format: <code>{}</code> Files
» Errors Intercepted: <code>{}</code> Files

<b>⏱️ Engine Performance:</b>
» Status: <code>Completed Successfully ✅</code>
» Triggered By: <code>Authorized Bot Admin 👮‍♂️</code>"""
