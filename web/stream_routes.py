import math, secrets, mimetypes, logging
from urllib.parse import quote
from aiohttp import web
from info import BIN_CHANNEL
from utils import temp
from web.utils.custom_dl import TGCustomYield, chunk_size, offset_fix
from web.utils.render_template import media_watch


routes = web.RouteTableDef()
logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────
# 🏠 ROOT ROUTE
# ─────────────────────────────────────────────
@routes.get("/", allow_head=True)
async def root_route_handler(request):
    # ✅ BUG FIX: pehle `getattr(temp, 'U_NAME', 'AutoFilterBot')` tha, par temp.U_NAME
    # class me already `None` declared hai — isliye getattr ka default KABHI apply nahi
    # hota tha aur bot_username `None` aata tha. Uske baad `.replace(..., None)`
    # TypeError deta tha, yaani homepage `/` pura 500 crash karta tha jab tak bot client
    # start na ho jaaye. Ab `or` se sahi fallback milta hai.
    bot_username = temp.U_NAME or 'AutoFilterBot'

    html_content = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Fast Finder — Movies, Series & More</title>
<link href="https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;700;900&display=swap" rel="stylesheet">
<style>
:root{--bg:#000;--text:#fff;--box:rgba(0,0,0,.7);--tag-bg:rgba(51,51,51,.8);--red:#E50914;--red-hover:#b30710}
html.light{--bg:#f3f3f3;--text:#141414;--box:#fff;--tag-bg:#e6e6e6}
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:'DM Sans',sans-serif;background:var(--bg);color:var(--text);min-height:100vh;display:flex;flex-direction:column;transition:background 0.3s, color 0.3s}
.hero-bg{position:fixed;inset:0;background:linear-gradient(to top,var(--bg) 0,rgba(0,0,0,.4) 50%,rgba(0,0,0,.8) 100%),url('https://assets.nflxext.com/ffe/siteui/vlv3/f841d4c7-10e1-40af-bcae-07a3f8dc141a/f6d7434e-d6de-4185-a6d4-c77a2d08737b/IN-en-20220502-popsignuptwoweeks-perspective_alpha_website_medium.jpg') center/cover;z-index:-1;transition:all 0.3s}
html.light .hero-bg{background:linear-gradient(to top,var(--bg) 0,rgba(255,255,255,.6) 50%,rgba(255,255,255,.9) 100%),url('https://assets.nflxext.com/ffe/siteui/vlv3/f841d4c7-10e1-40af-bcae-07a3f8dc141a/f6d7434e-d6de-4185-a6d4-c77a2d08737b/IN-en-20220502-popsignuptwoweeks-perspective_alpha_website_medium.jpg') center/cover}
.navbar{display:flex;justify-content:space-between;align-items:center;padding:25px 5%;z-index:10}
.logo{font-size:28px;font-weight:900;color:var(--red);text-decoration:none;display:flex;align-items:center;gap:8px;letter-spacing:1px;text-transform:uppercase}
.nf-icon{background:var(--red);color:#fff;padding:2px 8px;border-radius:3px;font-size:24px;line-height:1}
.header-actions{display:flex;align-items:center;gap:12px}
.theme-btn{background:transparent;border:1px solid var(--text);color:var(--text);padding:8px 16px;border-radius:4px;font-family:'DM Sans',sans-serif;font-weight:700;font-size:14px;cursor:pointer;transition:.2s}
.theme-btn:hover{background:var(--text);color:var(--bg)}
.admin-btn{background:var(--red);color:#fff;text-decoration:none;padding:8px 16px;border-radius:4px;font-weight:700;font-size:14px;transition:.2s;border:1px solid var(--red)}
.admin-btn:hover{background:var(--red-hover);border-color:var(--red-hover)}
.hero-content{flex:1;display:flex;flex-direction:column;justify-content:center;align-items:center;text-align:center;padding:20px;z-index:10;max-width:800px;margin:0 auto}
.hero-title{font-size:4rem;font-weight:900;margin-bottom:15px;line-height:1.1}
.hero-sub{font-size:1.5rem;font-weight:500;margin-bottom:30px}
.search-container{display:flex;width:100%;max-width:650px;flex-direction:row}
.search-input{flex:1;padding:20px 25px;font-size:1.2rem;border:1px solid #808080;border-radius:4px 0 0 4px;background:var(--box);color:var(--text);outline:none;transition:.2s}
.search-input:focus{border-color:var(--text)}
.search-btn{background:var(--red);color:#fff;border:none;padding:0 35px;font-size:1.5rem;font-weight:700;border-radius:0 4px 4px 0;cursor:pointer;display:flex;align-items:center;gap:10px;transition:.2s}
.search-btn:hover{background:var(--red-hover)}
.quick-picks{margin-top:40px;display:flex;flex-wrap:wrap;justify-content:center;gap:10px}
.qp-title{width:100%;font-size:1rem;color:var(--text);opacity:0.7;margin-bottom:10px;font-weight:500;text-transform:uppercase;letter-spacing:1px}
.tag{background:var(--tag-bg);border:1px solid var(--text);padding:8px 18px;border-radius:50px;font-size:14px;font-weight:700;cursor:pointer;transition:.2s}
.tag:hover{background:var(--text);color:var(--bg)}
@media (max-width:600px){.hero-title{font-size:2.5rem}.hero-sub{font-size:1.2rem}.search-container{flex-direction:column;gap:10px}.search-input{border-radius:4px;border:1px solid #808080;padding:15px}.search-btn{border-radius:4px;padding:15px;justify-content:center;font-size:1.2rem}.logo{font-size:20px}.nf-icon{font-size:18px}.theme-btn, .admin-btn{padding:6px 12px;font-size:12px;}}
</style>
</head>
<body>
<div class="hero-bg"></div>
<header class="navbar">
    <a href="/" class="logo"><span class="nf-icon">F</span> FAST FINDER</a>
    <div class="header-actions">
        <button class="theme-btn" id="theme-btn">Theme</button>
        <a href="/login" class="admin-btn">Sign In</a>
    </div>
</header>
<main class="hero-content">
    <h1 class="hero-title">Unlimited movies, TV shows, and more.</h1>
    <p class="hero-sub">Search and stream instantly via Telegram.</p>
    <div class="search-container">
        <input type="text" id="searchInput" class="search-input" placeholder="Search genres, qualities, formats..." autocomplete="off">
        <button class="search-btn" onclick="startSearch()">Search ></button>
    </div>
    <div class="quick-picks">
        <div class="qp-title">Trending Searches</div>
        <span class="tag" onclick="fillAndSearch('Action')">Action</span>
        <span class="tag" onclick="fillAndSearch('Comedy')">Comedy</span>
        <span class="tag" onclick="fillAndSearch('Thriller')">Thriller</span>
        <span class="tag" onclick="fillAndSearch('Anime')">Anime</span>
        <span class="tag" onclick="fillAndSearch('4K')">4K UHD</span>
        <span class="tag" onclick="fillAndSearch('Sci-Fi')">Sci-Fi</span>
    </div>
</main>
<script>
(function(){if(localStorage.getItem('theme')==='light')document.documentElement.classList.add('light')})();
document.getElementById('theme-btn').addEventListener('click',()=>{
    let isLight = document.documentElement.classList.toggle('light');
    localStorage.setItem('theme', isLight ? 'light' : 'dark');
});
function startSearch(){
    const q=document.getElementById('searchInput').value.trim();
    const base=`https://t.me/BOT_USERNAME_PLACEHOLDER`;
    window.open(q?`${base}?start=${encodeURIComponent(q)}`:base,'_blank');
}
function fillAndSearch(q){
    document.getElementById('searchInput').value=q;
    startSearch();
}
document.getElementById('searchInput').addEventListener('keydown',e=>{
    if(e.key==='Enter') startSearch();
});
</script>
</body>
</html>""".replace("BOT_USERNAME_PLACEHOLDER", bot_username)

    return web.Response(text=html_content, content_type='text/html')


# ─────────────────────────────────────────────
# 📺 STREAM / WATCH ROUTE
# 🔓 PUBLIC: Telegram bot /link command aur auto-filter se generate hote hain
#    ye links — login ki zaroorat nahi, warna bot se search karne wale
#    users ko har baar login ka jhanjhat hoga.
# ─────────────────────────────────────────────
@routes.get("/watch/{message_id}")
async def watch_handler(request):
    try:
        return web.Response(
            text=await media_watch(int(request.match_info['message_id'])),
            content_type='text/html'
        )
    except ValueError:
        return web.Response(status=400, text="Invalid Message ID")
    except Exception as e:
        logger.error(f"Watch Error: {e}")
        return web.Response(status=500, text="Internal Server Error")


# ─────────────────────────────────────────────
# 📐 HTTP RANGE PARSER (extracted + hardened)
# ✅ BUG FIX: पहले यह parsing media_download() के अंदर inline थी और `r_head` try-block
# के अंदर assign होकर बाहर इस्तेमाल होता था — अगर `int()` कहीं बीच में फेंकता तो
# `r_head` unbound रह सकता था। साथ ही unsatisfiable range (start > file_size) पर
# 416 की जगह आगे बढ़कर negative Content-Length बन सकता था। अब सब एक pure function
# में है, इसलिए इसे test भी किया जा सकता है।
# return: (first_byte, last_byte, length, is_partial) या None (416 भेजना है)
# ─────────────────────────────────────────────
def parse_range(header, file_size):
    """Range header को validated (start, end, length, partial) में बदलता है।"""
    partial = bool(header)
    try:
        if header:
            parts = header.replace("bytes=", "").split("-")
            first = int(parts[0]) if parts[0] else 0
            last = int(parts[1]) if len(parts) > 1 and parts[1].strip() else file_size - 1
        else:
            first, last = 0, file_size - 1
    except Exception:
        first, last, partial = 0, file_size - 1, False

    last = min(last, file_size - 1)          # upper bound clamp
    if first < 0 or last < first:            # unsatisfiable
        return None
    return first, last, last - first + 1, partial


# ─────────────────────────────────────────────
# 📥 DOWNLOAD & STREAMING CORE
# 🔓 PUBLIC: /link command se generate hota hai — login nahi chahiye
# ─────────────────────────────────────────────
@routes.get("/download/{message_id}")
async def download_handler(request):
    try:
        return await media_download(request, int(request.match_info['message_id']))
    except ValueError:
        return web.Response(status=400, text="Invalid Message ID")
    except Exception as e:
        logger.error(f"Download Error: {e}")
        return web.Response(status=500, text="Internal Server Error")


async def media_download(request, message_id: int):
    try:
        media_msg = await temp.BOT.get_messages(BIN_CHANNEL, message_id)
        media = getattr(media_msg, media_msg.media.value, None) if media_msg and media_msg.media else None
        if not media:
            return web.Response(status=404, text="Media Not Supported or Not Found")

        file_size = media.file_size
        file_name = getattr(media, 'file_name', None)
        if not file_name:
            file_name = (
                f"video_{secrets.token_hex(3)}.mp4"
                if getattr(media_msg, 'video', None)
                else f"file_{secrets.token_hex(3)}.bin"
            )

        mime_type = (
            getattr(media, 'mime_type', None)
            or mimetypes.guess_type(file_name)[0]
            or "application/octet-stream"
        )

        # ── Range Header Parse + Clamp/Validate (देखें parse_range) ──
        parsed = parse_range(request.headers.get('Range'), file_size)
        if parsed is None:
            return web.Response(
                status=416,
                body="416: Range Not Satisfiable",
                headers={"Content-Range": f"bytes */{file_size}"}
            )
        fb, ub, req_len, is_partial = parsed

        # ✅ FIX: chunk_size और offset_fix अब plain def हैं — await हटाया
        ncs    = chunk_size(req_len)
        offset = offset_fix(fb, ncs)

        # ✅ FIX: parts की सही गणना
        #    पुराना: math.ceil(req_len / ncs) — गलत था जब offset और fb में gap हो
        #    नया:   offset से ub तक का पूरा span cover करो
        first_cut = fb - offset
        last_cut  = (ub % ncs) + 1
        parts     = math.ceil((req_len + first_cut) / ncs)

        body = TGCustomYield().yield_file(
            media_msg, offset, first_cut, last_cut, parts, ncs
        )

        enc_fn = quote(file_name)

        return web.Response(
            status=206 if is_partial else 200,
            body=body,
            headers={
                "Content-Type":        mime_type,
                "Content-Range":       f"bytes {fb}-{ub}/{file_size}",
                "Content-Disposition": f'attachment; filename="{enc_fn}"; filename*=UTF-8\'\'{enc_fn}',
                "Accept-Ranges":       "bytes",
                "Content-Length":      str(req_len),
            }
        )

    except Exception as e:
        logger.error(f"Stream Error: {e}")
        return web.Response(status=500, text="Server Error")
