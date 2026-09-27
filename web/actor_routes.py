import io, time, html, re
from aiohttp import web
from bson.objectid import ObjectId
from utils import temp, get_size, get_duration_str
from info import MAX_WEB_RESULTS, ACTOR_STORAGE_CHANNEL
from database.ia_filterdb import actors, get_actor_search_results, delete_actor_profile, delete_gallery_image_by_index, doc_resolution_text
from web.web_assets import build_page, get_auth, form_wrapper, require_active_plan, fast_json, DIRECTORY_CSS, DEFAULT_CATALOG_MODE, DEFAULT_MEDIA_MODE
from web.utils.tg_media import upload_tg_photo, serve_tg_image

actor_routes = web.RouteTableDef()

# ─────────────────────────────────────────────────────────
# 🌐 MAIN HOMEPAGE: UNIVERSAL DIRECTORY WITH SEARCH & FILTERS
# ─────────────────────────────────────────────────────────
@actor_routes.get('/actors')
async def actors_directory_page(req):
    role, tg_id = await get_auth(req)
    if not role: return web.HTTPFound('/login')
    if not await require_active_plan(role, tg_id): return web.HTTPFound('/premium_expired')
    
    all_actors = await actors.find({}).sort("created_at", -1).limit(21).to_list(length=21)
    has_next_init = len(all_actors) > 20
    all_actors = all_actors[:20]
    
    admin_btn = '''<button onclick="window.location.href='/admin/create_actor'" style="background:var(--accent); color:#fff; border:none; padding:10px 15px; border-radius:8px; font-weight:800; cursor:pointer; font-size:13px; flex:1; min-width:130px; box-shadow:0 4px 15px rgba(229,9,20,0.3); transition:0.2s;">➕ Create Profile</button>''' if role == 'admin' else ""
    
    search_ui = f'''
    {DIRECTORY_CSS}

    <div class="search-box">
        <div class="s-row-1" id="dirSearchRow">
            <input type="text" id="dir_q" class="s-input" placeholder="Search...">
            <span class="s-spinner" id="dirSpinner"></span>
        </div>
        <div class="s-row-2">
            <div class="cdd-wrap" onclick="toggleDirCDD('cat', event)">
                <span id="dir_cat_lbl">📂 All</span> <span style="font-size:10px; color:var(--muted);">▼</span>
                <div class="cdd-menu" id="dir_cat_menu">
                    <div class="cdd-item" onclick="pickDirCat('all', '📂 All', event)">📂 All</div>
                    <div class="cdd-item" onclick="pickDirCat('actor', '🎭 Actor', event)">🎭 Actor</div>
                    <div class="cdd-item" onclick="pickDirCat('app', '📱 App', event)">📱 App</div>
                    <div class="cdd-item" onclick="pickDirCat('website', '🌐 Website', event)">🌐 Website</div>
                </div>
            </div>
            <div class="cdd-wrap" onclick="toggleDirCDD('mode', event)">
                <span id="dir_mode_lbl">{'📄 Text' if DEFAULT_CATALOG_MODE == 'text' else '🖼️ Poster'}</span> <span style="font-size:10px; color:var(--muted);">▼</span>
                <div class="cdd-menu" id="dir_mode_menu">
                    <div class="cdd-item" onclick="pickDirMode('poster', '🖼️ Poster', event)">🖼️ Poster</div>
                    <div class="cdd-item" onclick="pickDirMode('text', '📄 Text', event)">📄 Text</div>
                </div>
            </div>
            {admin_btn}
        </div>
    </div>
    '''

    act_items = ""
    for a in all_actors:
        cat = a.get("category", "actor")
        i = "🎭" if cat == "actor" else "📱" if cat == "app" else "🌐"
        v = int(a.get("photo_updated_at") or a.get("created_at") or 0)
        # ✅ Centralized default: text mode ⇒ initial server render भी text cards देता है (API text branch जैसा ही markup)
        if DEFAULT_CATALOG_MODE == "text":
            act_items += f'''<div class="act-text-card" style="background:var(--card); border:1px solid var(--border); padding:15px; border-radius:8px; display:flex; justify-content:space-between; align-items:center; cursor:pointer; transition:0.2s;" onclick="window.location.href=\'/actor/{str(a["_id"])}\'" onmouseover="this.style.borderColor='var(--accent)'" onmouseout="this.style.borderColor='var(--border)'"><div style="font-weight:800; color:var(--text); font-size:14px; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; max-width:65%;">{html.escape(a.get("name",""))}</div><div style="background:var(--bg3); padding:4px 10px; border-radius:6px; font-size:11px; font-weight:800; color:var(--muted); white-space:nowrap; border:1px solid var(--border);">{i} {cat.capitalize()}</div></div>'''
            continue
        act_items += f'<div class="act-card card-enter" onclick="window.location.href=\'/actor/{str(a["_id"])}\'">\n            <div class="poster-wrap" style="position:relative; padding-top:135%; background:var(--bg3); overflow:hidden;">\n                <img src="/api/actor/photo?id={str(a["_id"])}&v={v}" class="act-poster" loading="lazy">\n                <div style="position:absolute; top:8px; left:8px; background:rgba(229,9,20,0.9); color:#fff; font-size:10px; padding:4px 8px; border-radius:4px; font-weight:800; backdrop-filter:blur(4px); z-index:2; text-transform:uppercase; box-shadow:0 2px 10px rgba(0,0,0,0.5);">{i} {cat.capitalize()}</div>\n                <div style="position:absolute; bottom:0; left:0; right:0; background:linear-gradient(to top, rgba(0,0,0,0.95) 0%, rgba(0,0,0,0.7) 40%, transparent 100%); padding:30px 12px 12px 12px; z-index:2; text-align:center;">\n                    <div style="font-size:14.5px; font-weight:900; color:#fff; text-overflow:ellipsis; overflow:hidden; white-space:nowrap; text-shadow:0 2px 6px rgba(0,0,0,0.9); letter-spacing:0.5px;">{html.escape(a.get("name", ""))}</div>\n                </div>\n            </div>\n            <div class="card-body">\n                <div style="font-size:14px; font-weight:800; color:var(--text); text-overflow:ellipsis; overflow:hidden; white-space:nowrap;">{html.escape(a.get("name", ""))}</div>\n                <div style="font-size:11px; color:var(--muted); font-weight:700; margin-top:4px;">{html.escape(cat.capitalize())}</div>\n            </div>\n        </div>'
    
    dir_grid_style = ' style="display:flex; flex-direction:column; gap:10px;"' if DEFAULT_CATALOG_MODE == "text" else ""
    initial_grid = f'<div id="dir_grid_container" class="dir-grid"{dir_grid_style}>{act_items}</div>' if all_actors else '<div id="dir_grid_container" style="color:var(--muted); text-align:center; padding:60px 20px;">📇 No profiles found.</div>'
    
    has_nxt_str = "true" if has_next_init else "false"

    js_logic = f'''
    <div class="pg-bar" id="dir_pg_box" style="display:none;">
        <button class="pg-btn" id="dir_pBtn" onclick="prevDir()" disabled>Previous</button>
        <span class="pg-info" id="dir_pgInfo">Page 1</span>
        <button class="pg-btn" id="dir_nBtn" onclick="nextDir()">Next</button>
    </div>

    <script>
    var dirOffset = 0; var dirLimit = 20; var dirPage = 1;
    var hasNext = {has_nxt_str};
    var currentCat = 'all'; var currentMode = '{DEFAULT_CATALOG_MODE}';
    var lastQ = "", lastCat = "all", lastMode = "{DEFAULT_CATALOG_MODE}", lastOffset = 0;
    var dirReqId = 0;
    
    document.addEventListener("DOMContentLoaded", () => {{ 
        if(sessionStorage.getItem('ff_dir_state')) {{
            document.getElementById('dir_q').value = sessionStorage.getItem('ff_dir_q') || "";
            currentCat = sessionStorage.getItem('ff_dir_cat') || "all";
            currentMode = sessionStorage.getItem('ff_dir_mode') || "{DEFAULT_CATALOG_MODE}";
            dirOffset = parseInt(sessionStorage.getItem('ff_dir_off') || "0");
            dirPage = parseInt(sessionStorage.getItem('ff_dir_page') || "1");
            
            const catMap = {{'all':'📂 All', 'actor':'🎭 Actor', 'app':'📱 App', 'website':'🌐 Website'}};
            const modeMap = {{'poster':'🖼️ Poster', 'text':'📄 Text'}};
            document.getElementById('dir_cat_lbl').innerText = catMap[currentCat] || '📂 All';
            document.getElementById('dir_mode_lbl').innerText = modeMap[currentMode] || modeMap['{DEFAULT_CATALOG_MODE}'];
            
            searchDirectory(true);
        }} else {{
            updatePgUI();
            staggerCards(document.getElementById('dir_grid_container'));
        }}
    }});

    function closeAllDirCDD() {{ document.getElementById('dir_cat_menu').style.display='none'; document.getElementById('dir_mode_menu').style.display='none'; }}
    document.addEventListener('click', closeAllDirCDD);

    function toggleDirCDD(type, e) {{
        e.stopPropagation();
        var menu = document.getElementById('dir_' + type + '_menu');
        var isVis = menu.style.display === 'block';
        closeAllDirCDD();
        if (!isVis) menu.style.display = 'block';
    }}

    function pickDirCat(val, lbl, e) {{ e.stopPropagation(); currentCat = val; document.getElementById('dir_cat_lbl').innerText = lbl; closeAllDirCDD(); resetDir(); searchDirectory(); }}
    function pickDirMode(val, lbl, e) {{ e.stopPropagation(); currentMode = val; document.getElementById('dir_mode_lbl').innerText = lbl; closeAllDirCDD(); resetDir(); searchDirectory(); }}

    async function searchDirectory(forceRestore = false) {{
        var q = document.getElementById('dir_q').value.trim();
        
        if (!forceRestore && q === lastQ && currentCat === lastCat && currentMode === lastMode && dirOffset === lastOffset) {{ return; }}
        
        lastQ = q; lastCat = currentCat; lastMode = currentMode; lastOffset = dirOffset;
        
        sessionStorage.setItem('ff_dir_state', '1');
        sessionStorage.setItem('ff_dir_q', q);
        sessionStorage.setItem('ff_dir_cat', currentCat);
        sessionStorage.setItem('ff_dir_mode', currentMode);
        sessionStorage.setItem('ff_dir_off', dirOffset);
        sessionStorage.setItem('ff_dir_page', dirPage);

        var myReq = ++dirReqId;
        var grid = document.getElementById('dir_grid_container');
        var row = document.getElementById('dirSearchRow');
        var loadTimer = setTimeout(function() {{
            if (myReq !== dirReqId) return;
            if (row) row.classList.add('loading');
        }}, 150);
        
        try {{
            var res = await fetch('/api/directory/search?q=' + encodeURIComponent(q) + '&cat=' + currentCat + '&mode=' + currentMode + '&offset=' + dirOffset);
            if (myReq !== dirReqId) {{ clearTimeout(loadTimer); if (row) row.classList.remove('loading'); return; }}
            clearTimeout(loadTimer);
            if (row) row.classList.remove('loading');
            if (!res.ok) throw new Error("HTTP " + res.status);
            var data = await res.json();
            if (myReq !== dirReqId) return;
            grid.innerHTML = data.html;
            // Stagger entrance animation
            staggerCards(grid);
            hasNext = data.has_next;
            
            if(currentMode === 'text') {{
                grid.style.display = 'flex'; grid.style.flexDirection = 'column'; grid.style.gap = '10px';
            }} else {{
                grid.style.display = 'grid'; grid.style.gap = '';
            }}
            updatePgUI();
        }} catch(e) {{ clearTimeout(loadTimer); if (row) row.classList.remove('loading'); grid.innerHTML = '<div style="grid-column:1/-1; text-align:center; color:var(--accent); font-weight:bold;">Search Error!</div>'; }}
    }}
    
    function updatePgUI() {{
        var box = document.getElementById('dir_pg_box');
        if (dirOffset === 0 && !hasNext) {{ box.style.display = 'none'; }} else {{ box.style.display = 'flex'; }}
        document.getElementById('dir_pBtn').disabled = (dirOffset === 0);
        document.getElementById('dir_nBtn').disabled = !hasNext;
        document.getElementById('dir_pgInfo').innerText = 'Page ' + dirPage;
    }}
    
    function resetDir() {{ dirOffset = 0; dirPage = 1; }}
    function nextDir() {{ if(hasNext) {{ dirOffset += dirLimit; dirPage++; searchDirectory(); window.scrollTo(0, 50); }} }}
    function prevDir() {{ if(dirOffset > 0) {{ dirOffset = Math.max(0, dirOffset - dirLimit); dirPage--; searchDirectory(); window.scrollTo(0, 50); }} }}
    document.getElementById('dir_q').addEventListener('keydown', function(e) {{ if(e.key === 'Enter') {{ clearTimeout(dirLiveTimer); resetDir(); searchDirectory(); }} }});
    var dirLiveTimer;
    document.getElementById('dir_q').addEventListener('input', function() {{
        clearTimeout(dirLiveTimer);
        dirLiveTimer = setTimeout(function() {{ resetDir(); searchDirectory(); }}, 350);
    }});
    </script>
    '''

    page_body = f'''<div class="main" style="padding-top:20px; max-width:1100px; margin:0 auto; padding-left:20px; padding-right:20px;">{search_ui}{initial_grid}{js_logic}</div>'''
    return build_page("Directory Catalog - Fast Finder", page_body, "", "actors", role)

# ─────────────────────────────────────────────────────────
# 🔍 API: DIRECTORY UNIVERSAL SEARCH (WITH PAGINATION)
# ─────────────────────────────────────────────────────────
@actor_routes.get('/api/directory/search')
async def api_directory_search(req):
    role, _ = await get_auth(req)
    if not role: return web.json_response({"html": ""}, dumps=fast_json)
    
    q = req.query.get("q", "").strip()
    cat = req.query.get("cat", "all")
    mode = req.query.get("mode", DEFAULT_CATALOG_MODE)
    try: offset = int(req.query.get("offset", 0))
    except: offset = 0
    lim = 20
    
    query = {}
    if cat != "all": query["category"] = cat
    if q: 
        safe_q = re.escape(q)
        query["name"] = {"$regex": safe_q, "$options": "i"}
        
    try:
        docs = await actors.find(query).sort("created_at", -1).skip(offset).limit(lim + 1).to_list(length=lim + 1)
    except Exception:
        docs = []
    
    has_next = len(docs) > lim
    docs = docs[:lim]
    
    if not docs:
        return web.json_response({"html": '<div style="grid-column:1/-1; color:var(--muted); text-align:center; padding:60px 20px;">📇 No profiles matching your filters found.</div>', "has_next": False}, dumps=fast_json)
        
    html_out = ""
    if mode == "text":
        for a in docs:
            c = a.get("category", "actor")
            i = "🎭" if c == "actor" else "📱" if c == "app" else "🌐"
            html_out += f'''<div class="act-text-card" style="background:var(--card); border:1px solid var(--border); padding:15px; border-radius:8px; display:flex; justify-content:space-between; align-items:center; cursor:pointer; transition:0.2s;" onclick="window.location.href=\'/actor/{str(a["_id"])}\'" onmouseover="this.style.borderColor='var(--accent)'" onmouseout="this.style.borderColor='var(--border)'"><div style="font-weight:800; color:var(--text); font-size:14px; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; max-width:65%;">{html.escape(a.get("name",""))}</div><div style="background:var(--bg3); padding:4px 10px; border-radius:6px; font-size:11px; font-weight:800; color:var(--muted); white-space:nowrap; border:1px solid var(--border);">{i} {c.capitalize()}</div></div>'''
    else:
        for a in docs:
            c = a.get("category", "actor")
            i = "🎭" if c == "actor" else "📱" if c == "app" else "🌐"
            v = int(a.get("photo_updated_at") or a.get("created_at") or 0)
            html_out += f'''<div class="act-card card-enter" onclick="window.location.href=\'/actor/{str(a["_id"])}\'">\n            <div class="poster-wrap" style="position:relative; padding-top:135%; background:var(--bg3); overflow:hidden;">\n                <img src="/api/actor/photo?id={str(a["_id"])}&v={v}" class="act-poster" loading="lazy">\n                <div style="position:absolute; top:8px; left:8px; background:rgba(229,9,20,0.9); color:#fff; font-size:10px; padding:4px 8px; border-radius:4px; font-weight:800; backdrop-filter:blur(4px); z-index:2; text-transform:uppercase; box-shadow:0 2px 10px rgba(0,0,0,0.5);">{i} {c.capitalize()}</div>\n                <div style="position:absolute; bottom:0; left:0; right:0; background:linear-gradient(to top, rgba(0,0,0,0.95) 0%, rgba(0,0,0,0.7) 40%, transparent 100%); padding:30px 12px 12px 12px; z-index:2; text-align:center;">\n                    <div style="font-size:14.5px; font-weight:900; color:#fff; text-overflow:ellipsis; overflow:hidden; white-space:nowrap; text-shadow:0 2px 6px rgba(0,0,0,0.9); letter-spacing:0.5px;">{html.escape(a.get("name", ""))}</div>\n                </div>\n            </div>\n            <div class="card-body">\n                <div style="font-size:14px; font-weight:800; color:var(--text); text-overflow:ellipsis; overflow:hidden; white-space:nowrap;">{html.escape(a.get("name", ""))}</div>\n                <div style="font-size:11px; color:var(--muted); font-weight:700; margin-top:4px;">{html.escape(c.capitalize())}</div>\n            </div>\n        </div>'''
            
    return web.json_response({"html": html_out, "has_next": has_next}, dumps=fast_json)


# ─────────────────────────────────────────────────────────
# 🛠️ ADMIN ROUTE: CREATE PROFILE PAGE
# ─────────────────────────────────────────────────────────
@actor_routes.get('/admin/create_actor')
async def create_actor_page(req):
    role, _ = await get_auth(req)
    if role != 'admin': return web.HTTPFound('/dashboard')
    content = '''<form action="/api/create_actor" method="post" enctype="multipart/form-data"><input type="text" name="name" placeholder="Full Name (Actor / App / Website)" required><div class="scard-label" style="margin-bottom:4px; color:var(--muted);">Select Category</div><select name="category" style="width:100%; background:var(--bg3); border:1px solid var(--border); padding:12px; color:var(--text); border-radius:6px; margin-bottom:15px; outline:none; font-weight:600;" required><option value="actor">🎭 Actor Profile</option><option value="app">📱 App Profile</option><option value="website">🌐 Website Profile</option></select><textarea name="bio" placeholder="Biography / Description Details..." style="width:100%; background:var(--bg3); border:1px solid var(--border); padding:12px; color:var(--text); border-radius:6px; min-height:100px; outline:none; margin-bottom:15px; font-family:inherit;" required></textarea><div class="scard-label" style="margin-bottom:4px; color:var(--muted);">Search Tags (Comma Separated)</div><input type="text" name="tags" placeholder="e.g. SRK, Netflix, Mod" style="width:100%; background:var(--bg3); border:1px solid var(--border); padding:12px; color:var(--text); border-radius:6px; margin-bottom:15px; outline:none;"><div class="scard-label" style="margin-bottom:8px; color:var(--muted);">Profile Photo / Icon</div><input type="file" name="photo" accept="image/*" required style="padding:10px 0; color:var(--text);"><button class="submit-btn" type="submit" style="background:var(--accent); color:#fff; width:100%; padding:14px; border:0; border-radius:6px; font-weight:700; cursor:pointer; margin-top:10px;">Create Profile</button></form><div style="margin-top:15px; text-align:center;"><a href="/actors" style="color:var(--muted); text-decoration:none; font-size:13px;">← Back to Catalog</a></div>'''
    return build_page("Create New Profile", form_wrapper("Add New Entry", content, html.escape(req.query.get('err','')), html.escape(req.query.get('msg',''))), "login-bg", "actors", role)

@actor_routes.post('/api/create_actor')
async def api_create_actor(req):
    role, _ = await get_auth(req)
    if role != 'admin': return web.json_response({"error": "Unauthorized"}, status=403, dumps=fast_json)
    try:
        reader = await req.multipart()
        name, bio, tags_raw, image_bytes, category = None, None, "", None, "actor"
        while True:
            part = await reader.next()
            if part is None: break
            if part.name == 'name': name = (await part.read()).decode().strip()
            elif part.name == 'bio': bio = (await part.read()).decode().strip()
            elif part.name == 'tags': tags_raw = (await part.read()).decode().strip()
            elif part.name == 'category': category = (await part.read()).decode().strip()
            elif part.name == 'photo': image_bytes = await part.read()
            
        if not name or not bio or not image_bytes: return web.HTTPFound('/admin/create_actor?err=All fields are required!')
        
        tg_photo_id = await upload_tg_photo(ACTOR_STORAGE_CHANNEL, image_bytes, f"{name.replace(' ', '_')}.jpg")
        if not tg_photo_id: return web.HTTPFound('/admin/create_actor?err=Telegram Upload Failed!')
        now_ts = int(time.time())
        await actors.insert_one({"name": name, "bio": bio, "category": category, "tags": [t.strip() for t in tags_raw.split(",") if t.strip()], "photo_url": f"TG_ID:{tg_photo_id}", "is_actor_permanent": True, "photo_updated_at": now_ts, "social_links": {"instagram": "", "youtube": "", "twitter": ""}, "gallery": [], "is_gallery_permanent": True, "created_at": now_ts})
        return web.HTTPFound('/actors?msg=Profile created successfully!')
    except Exception as e: return web.HTTPFound(f'/admin/create_actor?err=Server Error: {str(e)}')


# ─────────────────────────────────────────────────────────
# 🖼️ PHOTO ENGINE (With Cache Control)
# ─────────────────────────────────────────────────────────
@actor_routes.get('/api/actor/photo')
async def get_actor_photo(req):
    actor_id, img_index = req.query.get("id"), req.query.get("gallery_idx")
    if not actor_id: return web.Response(status=400)
    try:
        doc = await actors.find_one({"_id": ObjectId(actor_id)})
        if not doc: return web.Response(status=404)
        if img_index is not None:
            raw_url = doc.get("gallery", [])[int(img_index)]
            headers = {"Cache-Control": "public, max-age=31536000, immutable", "Content-Disposition": 'inline; filename="photo.jpg"'}
        else:
            raw_url = doc.get("photo_url")
            headers = {"Cache-Control": "public, max-age=31536000, immutable", "Content-Disposition": 'inline; filename="avatar.jpg"'}
            
        if not raw_url or not raw_url.startswith("TG_ID:"): return web.Response(status=404)
        return await serve_tg_image(raw_url.replace("TG_ID:", ""), max_age=31536000)
    except Exception: return web.Response(status=500)


# ─────────────────────────────────────────────────────────
# 🌐 PROFILE VIEW: INDIVIDUAL DISPLAY & MEDIA
# ─────────────────────────────────────────────────────────
@actor_routes.get('/actor/{id}')
async def actor_profile_display(req):
    role, tg_id = await get_auth(req)
    if not role: return web.HTTPFound('/login')
    if not await require_active_plan(role, tg_id): return web.HTTPFound('/premium_expired')
    try:
        actor_id = req.match_info['id']
        actor = await actors.find_one({"_id": ObjectId(actor_id)})
        if not actor: return web.Response(text="Profile Not Found", status=404)
    except: return web.Response(text="Invalid ID", status=400)
        
    actor_name, tags_list, category = actor["name"], actor.get("tags", []), actor.get("category", "actor")
    social, gallery_list = actor.get("social_links", {"instagram": "", "youtube": "", "twitter": ""}), actor.get("gallery", [])
    
    cat_emoji = "🎭" if category == "actor" else "📱" if category == "app" else "🌐"
    cat_badge = f'<span style="background:var(--accent); color:#fff; font-size:11px; padding:3px 8px; border-radius:4px; font-weight:800; margin-right:6px;">{cat_emoji} {category.upper()}</span>'
    
    t_html = "".join([f'<span style="background:var(--bg3); border:1px solid var(--border); color:var(--muted); font-size:11px; padding:3px 8px; border-radius:4px; font-weight:600;">#{html.escape(t)}</span>' for t in tags_list])
    tags_chips_html = f'<div style="display:flex; gap:6px; flex-wrap:wrap; margin-top:8px;">{cat_badge}{t_html}</div>'
    
    s_html = "".join([f'<a href="{html.escape(social[k])}" target="_blank" style="background:{c}; color:#fff; padding:6px 14px; border-radius:6px; text-decoration:none; font-size:12px; font-weight:700;">{l}</a>' for k,c,l in [("instagram","#ff007f","📸 Instagram"),("youtube","#ff0000","📺 YouTube"),("twitter","#1da1f2","🐦 Twitter / X")] if social.get(k)])
    social_html = f'<div style="display:flex; gap:12px; margin-top:12px; flex-wrap:wrap;">{s_html}</div>'
    
    gallery_grid_html = f'''<div style="background:var(--card); border:1px dashed var(--border); padding:20px; border-radius:8px; text-align:center; margin-bottom:20px;"><form action="/api/actor/gallery_upload" method="post" enctype="multipart/form-data" style="margin:0;"><input type="hidden" name="actor_id" value="{actor_id}"><label style="background:var(--accent); color:#fff; padding:10px 20px; border-radius:6px; font-weight:700; cursor:pointer; font-size:13px; display:inline-block;">📂 Add Images to Gallery<input type="file" name="gallery_img" accept="image/*" multiple style="display:none;" onchange="this.form.submit()"></label><div style="color:var(--muted); font-size:11px; margin-top:8px;">You can select multiple photos at once</div></form></div>''' if role == 'admin' else ""
    if not gallery_list:
        gallery_grid_html += '<div style="color:var(--muted); text-align:center; padding:40px;"> 🖼️ Gallery is empty. Upload images to show here.</div>'
    else:
        # ✅ CACHE FIX: /api/actor/photo 1-साल immutable cache भेजता है — बिना version
        # param के delete/upload के बाद browser पुरानी image (पुराने gallery_idx URL से)
        # दिखाता रहता था, जिससे लगता था कि photo delete ही नहीं हुई। अब &v={gallery_v}
        # हर बदलाव पर URL बदल देता है।
        gallery_v = int(actor.get("gallery_updated_at") or actor.get("photo_updated_at") or actor.get("created_at") or 0)
        g_items = "".join([f'<div class="gallery-item-wrap" onclick="openLightbox(\'/api/actor/photo?id={actor_id}&gallery_idx={i}&v={gallery_v}\')"><img src="/api/actor/photo?id={actor_id}&gallery_idx={i}&v={gallery_v}" class="gallery-item" loading="lazy">' + (f'<button class="gallery-del-btn" onclick="deleteGalleryImage(\'{actor_id}\', {i}, event)">🗑️ Delete</button>' if role=='admin' else "") + '</div>' for i in range(len(gallery_list))])
        gallery_grid_html += f'<div class="gallery-grid">{g_items}</div>'

    admin_actions_html = f'''<div style="display:flex; gap:10px; margin-top:10px; flex-wrap:wrap;"><button onclick="openActorEditModal()" style="background:var(--bg4); border:1px solid var(--border); color:var(--text); padding:8px 16px; border-radius:6px; font-size:12px; font-weight:700; cursor:pointer;">✏️ Edit Profile & Socials</button><button onclick="deleteActorProfile('{actor_id}')" style="background:rgba(160,8,8,.78); border:1px solid rgba(229,9,20,.45); color:#fff; padding:8px 16px; border-radius:6px; font-size:12px; font-weight:700; cursor:pointer;">🗑️ Delete Profile</button><label style="background:var(--bg3); border:1px dashed var(--border); color:var(--text); padding:7px 14px; border-radius:6px; font-size:12px; font-weight:700; cursor:pointer; display:inline-block;">📸 Change Avatar<input type="file" id="avatarUpdateInput" accept="image/*" style="display:none;" onchange="updateActorAvatar('{actor_id}')"></label></div>''' if role == 'admin' else ""
        
    safe_bio = html.escape(actor.get("bio", ""))
    photo_v = int(actor.get("photo_updated_at") or actor.get("created_at") or 0)
    
    # 🎛️ Default media mode (centralized via DEFAULT_MEDIA_MODE in web_assets.py)
    ap_mode_tg_lbl = "🖼️ Original TG Thumb"
    ap_mode_none_lbl = "⚡ Text Only (Fastest)"
    ap_mode_lbl = ap_mode_none_lbl if DEFAULT_MEDIA_MODE == "none" else ap_mode_tg_lbl
    ap_sel_tg = " selected" if DEFAULT_MEDIA_MODE == "tg" else ""
    ap_sel_none = " selected" if DEFAULT_MEDIA_MODE == "none" else ""

    sel_actor = "selected" if category == "actor" else ""
    sel_app = "selected" if category == "app" else ""
    sel_web = "selected" if category == "website" else ""

    # ✅ CSS MINIFIED (DUPLICATES REMOVED)
    css_js_minified = f'''<style>.actor-tab-bar{{display:flex;gap:10px;border-bottom:2px solid var(--border);margin-bottom:25px}}.actor-tab{{background:0 0;border:none;color:var(--muted);padding:12px 20px;font-size:15px;font-weight:700;cursor:pointer;transition:.2s;position:relative;font-family:inherit}}.actor-tab.active{{color:var(--text)!important}}.actor-tab.active::after{{content:'';position:absolute;bottom:-2px;left:0;right:0;height:2px;background:var(--accent)}}.actor-panel{{display:none}}.actor-panel.active{{display:block!important}}.gallery-grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(140px,1fr));gap:14px}}@media(min-width:600px){{.gallery-grid{{grid-template-columns:repeat(auto-fill,minmax(180px,1fr))}}}}.gallery-item-wrap{{position:relative;border-radius:8px;overflow:hidden;border:1px solid var(--border);aspect-ratio:1;cursor:pointer}}.gallery-item{{width:100%;height:100%;object-fit:cover;transition:transform .2s}}.gallery-item-wrap:hover .gallery-item{{transform:scale(1.04)}}.gallery-del-btn{{position:absolute;bottom:8px;left:50%;transform:translateX(-50%);background:rgba(160,8,8,.85);border:1px solid var(--accent);color:#fff;padding:4px 10px;border-radius:4px;font-size:10px;font-weight:700;cursor:pointer;z-index:5;opacity:0;transition:opacity .15s}}.gallery-item-wrap:hover .gallery-del-btn{{opacity:1}}.lightbox{{position:fixed;inset:0;background:rgba(0,0,0,.92);backdrop-filter:blur(15px);z-index:99999;display:none;align-items:center;justify-content:center;opacity:0;transition:opacity .2s ease}}.lightbox.open{{display:flex;opacity:1}}.lightbox-img{{max-width:92%;max-height:88vh;object-fit:contain;border-radius:6px;box-shadow:0 10px 40px rgba(0,0,0,.8);transform:scale(.95);transition:transform .2s cubic-bezier(.4,0,.2,1)}}.lightbox.open .lightbox-img{{transform:scale(1)}}.lightbox-close{{position:absolute;top:20px;right:25px;background:none;border:none;color:#fff;font-size:32px;cursor:pointer;opacity:.7}}.lightbox-close:hover{{opacity:1}}.search-zone-actor{{padding:16px 0 0}}.search-row1-actor{{display:flex;align-items:center;gap:10px;margin-bottom:10px}}.search-row2-actor{{display:flex;align-items:center;justify-content:flex-start;gap:10px;margin-bottom:16px}}@media(min-width:768px){{.search-zone-actor{{display:flex;align-items:center;gap:10px;flex-wrap:nowrap;padding-bottom:16px}}.search-row1-actor{{flex:1;margin-bottom:0}}.search-row2-actor{{margin-bottom:0;flex-shrink:0}}}}.search-wrap-actor{{flex:1;min-width:0;display:flex;align-items:center;background:var(--bg3);border:1.5px solid var(--border);border-radius:12px;padding:0 6px 0 18px;gap:8px;overflow:hidden;min-height:38px}}.search-spinner-actor{{display:none;width:15px;height:15px;flex-shrink:0;border:2px solid var(--border);border-top-color:var(--accent);border-radius:50%;animation:searchSpinActor .6s linear infinite}}.search-wrap-actor.loading .search-spinner-actor{{display:inline-block}}@keyframes searchSpinActor{{to{{transform:rotate(360deg)}}}}.search-input-actor{{flex:1;min-width:0;width:100%;background:0 0;border:none;outline:none;color:var(--text);font-size:14px;font-weight:600;padding:6px 0;font-family:inherit}}.search-input-actor::placeholder{{color:var(--muted);font-weight:400}}.search-btn-actor{{flex-shrink:0;background:var(--accent);color:#fff;border:none;border-radius:12px;padding:0 20px;height:38px;font-size:14px;font-weight:700;cursor:pointer;white-space:nowrap;transition:transform .15s,background .15s}}.search-btn-actor:hover{{background:var(--accent-hover);transform:scale(1.03)}}.cdd-wrap-actor{{flex:0 1 auto;min-width:0;position:relative;user-select:none}}.cdd-btn-actor{{width:auto;background:var(--bg3);color:var(--text);border:1.5px solid var(--border);border-radius:999px;padding:8px 28px 8px 14px;font-size:11px;font-weight:700;cursor:pointer;font-family:inherit;box-sizing:border-box;display:inline-flex;align-items:center;gap:5px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;transition:border-color .15s}}.cdd-btn-actor.open,.cdd-btn-actor:hover{{border-color:var(--accent)}}.cdd-arrow-actor{{position:absolute;right:12px;top:50%;transform:translateY(-50%);pointer-events:none;font-size:9px;color:var(--muted);transition:transform .2s}}.cdd-btn-actor.open+.cdd-arrow-actor{{transform:translateY(-50%) rotate(180deg)}}.cdd-menu-actor{{position:absolute;top:calc(100% + 7px);left:50%;transform:translateX(-50%);min-width:max-content;background:var(--bg2);border:1.5px solid var(--border);border-radius:16px;overflow:hidden;z-index:9999;box-shadow:0 8px 32px rgba(0,0,0,.45);display:none}}.cdd-item-actor{{display:flex;align-items:center;gap:10px;padding:11px 14px;font-size:12px;font-weight:700;color:var(--text);cursor:pointer;transition:background .12s;border-bottom:1px solid var(--border)}}.cdd-item-actor:last-child{{border-bottom:none}}.cdd-item-actor:hover{{background:var(--bg3)}}.cdd-item-actor.selected{{color:var(--accent)}}.cdd-radio-actor{{width:16px;height:16px;border-radius:50%;border:2px solid var(--border);margin-left:auto;flex-shrink:0;display:flex;align-items:center;justify-content:center}}.cdd-item-actor.selected .cdd-radio-actor{{border-color:var(--accent)}}.cdd-radio-dot-actor{{width:6px;height:6px;border-radius:50%;background:var(--accent);display:none}}.cdd-item-actor.selected .cdd-radio-dot-actor{{display:block}}.actor-header-wrap{{display:flex;gap:25px;background:var(--card);border:1px solid var(--border);padding:25px;border-radius:12px;margin-bottom:35px;flex-direction:column;align-items:center;width:100%;box-sizing:border-box}}.avatar-box-master{{width:100%;max-width:340px;height:auto;aspect-ratio:3/4;background:var(--bg3);border-radius:8px;overflow:hidden;border:1px solid var(--border);flex-shrink:0}}@media(min-width:768px){{.actor-header-wrap{{flex-direction:row;align-items:stretch}}.avatar-box-master{{width:260px;height:350px;max-width:none;aspect-ratio:auto}}}}</style><div class="main" style="padding-top:30px;max-width:1100px;margin:0 auto;padding-left:20px;padding-right:20px"><div style="margin-bottom:15px"><a href="/actors" style="color:var(--muted);text-decoration:none;font-size:14px;font-weight:700">← Back to Catalog</a></div><div class="actor-header-wrap"><div class="avatar-box-master"><img id="actorMasterAvatarImage" src="/api/actor/photo?id={actor_id}&v={photo_v}" style="width:100%;height:100%;object-fit:cover"></div><div style="flex:1;min-width:300px;display:flex;flex-direction:column;justify-content:center;width:100%"><h1 style="font-size:32px;font-weight:900;color:var(--text);margin-bottom:2px">{html.escape(actor_name)}</h1>{tags_chips_html}{social_html}{admin_actions_html}</div></div><div class="actor-tab-bar"><button class="actor-tab active" onclick="switchActorTab(event,'tab-info')">ℹ️ Info</button><button class="actor-tab" onclick="switchActorTab(event,'tab-video')">🎬 Linked Media</button><button class="actor-tab" onclick="switchActorTab(event,'tab-gallery')">🖼️ Gallery</button></div><div id="tab-info" class="actor-panel active"><div style="background:var(--card);border:1px solid var(--border);padding:25px;border-radius:8px;line-height:1.7;color:var(--text);font-size:15px;white-space:pre-line">{safe_bio}</div></div><div id="tab-video" class="actor-panel"><div class="search-zone-actor"><div class="search-row1-actor"><div class="search-wrap-actor" id="actMovieWrap"><input type="text" id="actor_movie_q" value="" placeholder="Search inside this profile..." class="search-input-actor"><span class="search-spinner-actor" id="actMovieSpinner"></span></div></div><div class="search-row2-actor"><div class="cdd-wrap-actor"><div class="cdd-btn-actor" id="cddColBtnActor" onclick="toggleActorCdd('col',event)"><span id="cddColLabelActor">📂 All Collections</span></div><span class="cdd-arrow-actor">&#9660;</span><div class="cdd-menu-actor" id="cddColMenuActor"><div class="cdd-item-actor selected" data-val="all" onclick="pickActorCol('all','📂 All Collections',this,event)">📂 All Collections<span class="cdd-radio-actor"><span class="cdd-radio-dot-actor"></span></span></div><div class="cdd-item-actor" data-val="primary" onclick="pickActorCol('primary','🟢 Primary',this,event)">🟢 Primary<span class="cdd-radio-actor"><span class="cdd-radio-dot-actor"></span></span></div><div class="cdd-item-actor" data-val="cloud" onclick="pickActorCol('cloud','🔵 Cloud',this,event)">🔵 Cloud<span class="cdd-radio-actor"><span class="cdd-radio-dot-actor"></span></span></div><div class="cdd-item-actor" data-val="archive" onclick="pickActorCol('archive','🟠 Archive',this,event)">🟠 Archive<span class="cdd-radio-actor"><span class="cdd-radio-dot-actor"></span></span></div></div></div><div class="cdd-wrap-actor"><div class="cdd-btn-actor" id="cddModeBtnActor" onclick="toggleActorCdd('mode',event)"><span id="cddModeLabelActor">{ap_mode_lbl}</span></div><span class="cdd-arrow-actor">&#9660;</span><div class="cdd-menu-actor" id="cddModeMenuActor"><div class="cdd-item-actor{ap_sel_tg}" data-val="tg" onclick="pickActorMode('tg','🖼️ Original TG Thumb',this,event)">🖼️ Original TG Thumb<span class="cdd-radio-actor"><span class="cdd-radio-dot-actor"></span></span></div><div class="cdd-item-actor{ap_sel_none}" data-val="none" onclick="pickActorMode('none','⚡ Text Only (Fastest)',this,event)">⚡ Text Only (Fastest)<span class="cdd-radio-actor"><span class="cdd-radio-dot-actor"></span></span></div></div></div></div></div><div id="actor_video_results" class="res-grid"></div><div class="pagination" id="actor_page_box" style="display:none"><button class="pg-btn" id="actor_pBtn" onclick="actorPagePrev()" disabled>Previous</button><span class="pg-info" id="actor_pgInfo">Page 1</span><button class="pg-btn" id="actor_nBtn" onclick="actorPageNext()">Next</button></div></div><div id="tab-gallery" class="actor-panel">{gallery_grid_html}</div></div><div id="actorLightboxModal" class="lightbox" onclick="closeLightbox()"><button class="lightbox-close" onclick="closeLightbox()">&times;</button><img id="lightboxTargetImg" class="lightbox-img" src="" onclick="event.stopPropagation()"></div><div class="edit-modal" id="actorEditModal" onclick="if(event.target===this)closeActorEditModal()"><div class="em-card" style="max-width:550px;background:var(--card);border:1px solid var(--border);padding:25px;border-radius:12px"><button class="em-close" onclick="closeActorEditModal()" style="position:absolute;top:15px;right:20px;background:0 0;border:none;color:var(--muted);font-size:24px;cursor:pointer">&#10005;</button><div class="em-title" style="font-size:18px;font-weight:700;margin-bottom:20px;color:var(--text)">✏️ Edit Profile Matrix</div><form action="/api/actor/update_profile" method="post"><input type="hidden" name="actor_id" value="{actor_id}"><div class="scard-label">Full Name</div><input type="text" name="name" value="{html.escape(actor_name)}" class="em-input" style="width:100%;background:var(--bg);border:1px solid var(--border);padding:12px;color:var(--text);margin-bottom:15px;border-radius:6px" required><div class="scard-label">Category</div><select name="category" class="em-input" style="width:100%;background:var(--bg);border:1px solid var(--border);padding:12px;color:var(--text);margin-bottom:15px;border-radius:6px;outline:none;" required><option value="actor" {sel_actor}>🎭 Actor Profile</option><option value="app" {sel_app}>📱 App Profile</option><option value="website" {sel_web}>🌐 Website Profile</option></select><div class="scard-label">Biography Details</div><textarea name="bio" class="em-input" style="width:100%;background:var(--bg);border:1px solid var(--border);min-height:120px;font-family:inherit;padding:10px;line-height:1.5;color:var(--text);margin-bottom:15px;border-radius:6px" required>{safe_bio}</textarea><div class="scard-label">Search Tags (Comma Separated)</div><input type="text" name="tags" value="{html.escape(', '.join(tags_list))}" placeholder="e.g. SRK, Netflix" class="em-input" style="width:100%;background:var(--bg);border:1px solid var(--border);padding:12px;color:var(--text);margin-bottom:15px;border-radius:6px"><div class="em-title" style="font-size:14px;margin-top:15px;margin-bottom:10px;color:var(--text)">🌐 Social Media Channels</div><div class="scard-label">Instagram Link</div><input type="url" name="insta" value="{html.escape(social.get('instagram',''))}" placeholder="https://instagram.com/..." class="em-input" style="width:100%;background:var(--bg);border:1px solid var(--border);padding:12px;color:var(--text);margin-bottom:15px;border-radius:6px"><div class="scard-label">YouTube Channel Link</div><input type="url" name="yt" value="{html.escape(social.get('youtube',''))}" placeholder="https://youtube.com/..." class="em-input" style="width:100%;background:var(--bg);border:1px solid var(--border);padding:12px;color:var(--text);margin-bottom:15px;border-radius:6px"><div class="scard-label">Twitter / X Profile Link</div><input type="url" name="twitter" value="{html.escape(social.get('twitter',''))}" placeholder="https://x.com/..." class="em-input" style="width:100%;background:var(--bg);border:1px solid var(--border);padding:12px;color:var(--text);margin-bottom:20px;border-radius:6px"><button class="em-save-btn" type="submit" style="width:100%;background:var(--accent);color:#fff;border:none;padding:14px;font-weight:700;border-radius:6px;cursor:pointer;font-size:15px">Save Changes & Sync Grid</button></form></div></div><script>var actCurPage=1,actOffset=0,actNextOffset="",actLimit={MAX_WEB_RESULTS},actCol="all",actMode="{DEFAULT_MEDIA_MODE}",actMovieReqId=0;function closeActorCdds(){{document.getElementById('cddColMenuActor').style.display='none';document.getElementById('cddColBtnActor').classList.remove('open');document.getElementById('cddModeMenuActor').style.display='none';document.getElementById('cddModeBtnActor').classList.remove('open');}}function toggleActorCdd(w,e){{if(e)e.stopPropagation();var mid=w==='col'?'cddColMenuActor':'cddModeMenuActor',bid=w==='col'?'cddColBtnActor':'cddModeBtnActor',oid=w==='col'?'cddModeMenuActor':'cddColMenuActor',obid=w==='col'?'cddModeBtnActor':'cddColBtnActor';document.getElementById(oid).style.display='none';document.getElementById(obid).classList.remove('open');var m=document.getElementById(mid),b=document.getElementById(bid);if(m.style.display==='block'){{m.style.display='none';b.classList.remove('open');}}else{{m.style.display='block';b.classList.add('open');}}}}function pickActorCol(v,l,el,e){{if(e)e.stopPropagation();actCol=v;document.getElementById('cddColLabelActor').textContent=l;document.querySelectorAll('#cddColMenuActor .cdd-item-actor').forEach(i=>i.classList.remove('selected'));el.classList.add('selected');closeActorCdds();resetActorSearchPage();triggerActorSearchAjax();}}function pickActorMode(v,l,el,e){{if(e)e.stopPropagation();actMode=v;document.getElementById('cddModeLabelActor').textContent=l;document.querySelectorAll('#cddModeMenuActor .cdd-item-actor').forEach(i=>i.classList.remove('selected'));el.classList.add('selected');closeActorCdds();resetActorSearchPage();triggerActorSearchAjax();}}document.addEventListener('click',closeActorCdds);function openLightbox(s){{document.getElementById('lightboxTargetImg').src=s;var lb=document.getElementById('actorLightboxModal');lb.style.display='flex';setTimeout(()=>lb.classList.add('open'),10);}}function closeLightbox(){{var lb=document.getElementById('actorLightboxModal');lb.classList.remove('open');setTimeout(()=>lb.style.display='none',200);}}function switchActorTab(ev,tId){{document.querySelectorAll('.actor-panel').forEach(p=>p.classList.remove('active'));document.querySelectorAll('.actor-tab').forEach(t=>t.classList.remove('active'));document.getElementById(tId).classList.add('active');ev.currentTarget.classList.add('active');if(tId==='tab-video'&&!document.getElementById('actor_video_results').innerHTML)triggerActorSearchAjax();}}function openActorEditModal(){{document.getElementById('actorEditModal').classList.add('open');}}function closeActorEditModal(){{document.getElementById('actorEditModal').classList.remove('open');}}function resetActorSearchPage(){{actCurPage=1;actOffset=0;}}async function triggerActorSearchAjax(){{var q=document.getElementById('actor_movie_q').value.trim(),grid=document.getElementById('actor_video_results');var wrap=document.getElementById('actMovieWrap');var myReq=++actMovieReqId;var loadTimer=setTimeout(function(){{if(myReq!==actMovieReqId)return;if(wrap)wrap.classList.add('loading');}},150);try{{var r=await fetch('/api/actor/search?q='+encodeURIComponent(q)+'&offset='+actOffset+'&col='+actCol+'&mode='+actMode+'&id={actor_id}');if(myReq!==actMovieReqId){{clearTimeout(loadTimer);if(wrap)wrap.classList.remove('loading');return;}}clearTimeout(loadTimer);if(wrap)wrap.classList.remove('loading');var d=await r.json();if(myReq!==actMovieReqId)return;grid.className='res-grid mode-'+actMode;if(!d.results||!d.results.length){{grid.innerHTML='<div class="empty"><p>No video assets matching filters found.</p></div>';document.getElementById('actor_page_box').style.display='none';return;}}var h='';d.results.forEach(f=>{{var sc=(f.raw_collection||'primary').toLowerCase(),ph='';/*⏱️ duration chip: khali duration par chip banta hi nahi*/var durC=f.duration?'<span class="dur-chip">'+f.duration+'</span>':'',durT=f.duration?'<span class="tc-dur">'+f.duration+'</span>':'';var resC=f.res?'<span class="res-chip">'+f.res+'</span>':'',resT=f.res?'<span class="tc-res">'+f.res+'</span>':'';var encName=encodeURIComponent(f.name||'').replace(/'/g,"%27").replace(/"/g,"%22");var encCap=encodeURIComponent(f.caption||'').replace(/'/g,"%27").replace(/"/g,"%22");var isAdmin=document.getElementById('editCombinedModal')!==null;var adminBtns='';if(isAdmin){{adminBtns='<div class="poster-admin"><button class="btn-edit" onclick="event.stopPropagation();editFile(\\''+f.file_id+'\\',\\''+sc+'\\',\\''+encName+'\\',\\''+encCap+'\\')">&#9999; Edit</button><button class="btn-del" onclick="event.stopPropagation();deleteFile(\\''+f.file_id+'\\',\\''+sc+'\\')">&#128465; Delete</button></div>';}}if(actMode!=='none'){{ph='<div class="poster-box" onclick="toggleAdminBtns(this.closest(\\'.file-card\\'),event)"><img src="'+f.tg_thumb+'" class="fc-poster" onload="this.classList.add(\\'loaded\\')" loading="lazy"><div class="poster-top"><span class="type-chip">'+f.type.toUpperCase()+'</span><span class="size-chip">'+f.size+'</span>'+durC+resC+'<span class="source-pill '+sc+'"><span class="source-dot"></span>'+sc.toUpperCase()+'</span></div>'+adminBtns+'</div>';}}else{{var textBtns=isAdmin?'<div class="text-admin-row"><button class="btn-edit" onclick="event.stopPropagation();editFile(\\''+f.file_id+'\\',\\''+sc+'\\',\\''+encName+'\\',\\''+encCap+'\\')">&#9999; Edit</button><button class="btn-del" onclick="event.stopPropagation();deleteFile(\\''+f.file_id+'\\',\\''+sc+'\\')">&#128465; Delete</button></div>':'';ph='<div class="fc-text-info" onclick="toggleAdminBtns(this.closest(\\'.file-card\\'),event)"><span class="tc-type">'+f.type.toUpperCase()+'</span><span class="tc-size">'+f.size+'</span>'+durT+resT+'<span class="source-pill '+sc+'" style="margin-left:auto"><span class="source-dot"></span>'+sc.toUpperCase()+'</span></div>'+textBtns;}}h+='<div class="file-card card-enter">'+ph+'<div class="fc-body"><div class="fc-name" onclick="window.open(\\''+f.watch+'\\',\\'_blank\\')">'+f.name+'</div></div></div>';}});grid.innerHTML=h;staggerCards(grid);actNextOffset=d.next_offset;document.getElementById('actor_page_box').style.display='flex';document.getElementById('actor_pBtn').disabled=(actOffset===0);document.getElementById('actor_nBtn').disabled=!actNextOffset;document.getElementById('actor_pgInfo').textContent='Page '+actCurPage;}}catch(e){{clearTimeout(loadTimer);if(wrap)wrap.classList.remove('loading');grid.innerHTML='<div class="empty"><p>Matrix pipeline sync error.</p></div>';}}}}async function updateActorAvatar(aid){{var f=document.getElementById('avatarUpdateInput').files[0];if(!f)return;var fd=new FormData();fd.append('actor_id',aid);fd.append('photo',f);try{{var r=await fetch('/api/actor/update_avatar',{{method:'POST',body:fd}}),d=await r.json();if(d.success){{document.getElementById('actorMasterAvatarImage').src='/api/actor/photo?id='+aid+'&v='+(d.photo_updated_at||new Date().getTime());alert("Profile photo updated successfully!");}}else alert(d.error||"Upload failed!");}}catch(e){{alert("Network update error!");}}}}async function deleteGalleryImage(aid,idx,e){{if(e)e.stopPropagation();if(!confirm("Delete this photo from gallery permanently?"))return;try{{var r=await fetch('/api/actor/gallery_delete',{{method:'POST',body:JSON.stringify({{actor_id:aid,index:idx}}),headers:{{'Content-Type':'application/json'}}}}),d=await r.json();if(d.success){{alert("Image removed from gallery!");window.location.reload();}}else alert(d.error||"Delete failed!");}}catch(e){{alert("Network deletion error!");}}}}async function deleteActorProfile(id){{if(!confirm("Are you sure you want to permanently delete this profile?"))return;try{{var r=await fetch('/api/actor/delete?id='+id,{{method:'POST'}}),d=await r.json();if(d.success){{alert("Profile deleted successfully!");window.location.href='/actors';}}else alert(d.error||"Deletion failed!");}}catch(e){{alert("Network communication error!");}}}}function actorPageNext(){{if(actNextOffset){{actCurPage++;actOffset=actNextOffset;triggerActorSearchAjax();window.scrollTo(0,350);}}}}function actorPagePrev(){{if(actCurPage>1){{actCurPage--;actOffset=Math.max(0,actOffset-actLimit);triggerActorSearchAjax();window.scrollTo(0,350);}}}}document.getElementById('actor_movie_q').addEventListener('keydown',function(e){{if(e.key==='Enter'){{clearTimeout(actMovieLiveTimer);resetActorSearchPage();triggerActorSearchAjax();}}}});var actMovieLiveTimer;document.getElementById('actor_movie_q').addEventListener('input',function(){{clearTimeout(actMovieLiveTimer);actMovieLiveTimer=setTimeout(function(){{resetActorSearchPage();triggerActorSearchAjax();}},350);}});</script>'''
    
    return build_page(f"{actor_name} - Directory Profile", css_js_minified, "", "actors", role)

# ─────────────────────────────────────────────────────────
# ⚙️ PROFILE PAGE: INTERNAL FILE SEARCH API
# ─────────────────────────────────────────────────────────
@actor_routes.get('/api/actor/search')
async def api_actor_search_handler(req):
    role, _ = await get_auth(req)
    if not role: return web.json_response({"error": "Unauthorized"}, status=403, dumps=fast_json)
    actor_id, q_custom = req.query.get("id"), req.query.get("q", "").strip()
    # नोट: `mode` query-param अब पढ़ा नहीं जाता — इस handler में thumbnail हमेशा
    # tg_thumb के तौर पर भेजा जाता है, इसलिए variable bind करना dead code था।
    off, col = req.query.get("offset", "0"), req.query.get("col", "all").lower()
    
    if not actor_id: return web.json_response({"results": []}, dumps=fast_json)
    try: off = max(0, int(off))
    except: off = 0
        
    actor = await actors.find_one({"_id": ObjectId(actor_id)})
    if not actor: return web.json_response({"results": []}, dumps=fast_json)
    
    tags_list = actor.get("tags", [])
    search_query, final_tags = (q_custom, []) if q_custom else (tags_list[0] if tags_list else "", tags_list)
    if not search_query: return web.json_response({"results": [], "next_offset": ""}, dumps=fast_json)
        
    lim = MAX_WEB_RESULTS
    all_m, next_offset = await get_actor_search_results(search_query, final_tags, max_results=lim, offset=off, collection_type=col)
    
    # ✅ FIXED API: Added 'caption' and 'raw_collection' safely to JSON response
    results_list = [{
        "file_id": d.get("_id"),
        "name": d.get("file_name", "Unknown File"),
        "caption": d.get("caption", ""),
        "raw_collection": d.get("source_col", "primary"),
        "size": get_size(d.get("file_size", 0)),
        "duration": get_duration_str(d.get("duration")),  # ✅ web-only video duration
        "res": doc_resolution_text(d),  # ✅ resolution chip (asli W×H — meta ya file_name se)
        "type": d.get("file_type", "document").upper(),
        "source": d.get("source_col", "primary").capitalize(),
        "tg_thumb": f"/api/thumb?file_id={d.get('_id')}&col={d.get('source_col', 'primary')}&v={(d.get('thumb_url', '')[-8:] if str(d.get('thumb_url', '')).startswith('TG_ID:') else '0')}",
        "watch": f"/setup_stream?file_id={d.get('file_ref') or d.get('_id')}&mode=watch"
    } for d in all_m]
        
    return web.json_response({"results": results_list, "next_offset": next_offset}, dumps=fast_json)

# ─────────────────────────────────────────────────────────
# ⚙️ PROFILE: UPDATE PROFILE DATA
# ─────────────────────────────────────────────────────────
@actor_routes.post('/api/actor/update_profile')
async def api_actor_update_profile(req):
    role, _ = await get_auth(req)
    if role != 'admin': return web.json_response({"error": "Unauthorized"}, status=403, dumps=fast_json)
    
    d = await req.post()
    actor_id, name, bio = d.get('actor_id'), d.get('name', '').strip(), d.get('bio', '').strip()
    category = d.get('category', 'actor').strip()
    if not actor_id or not name or not bio: return web.HTTPFound('/actors?err=Missing assets data')
    
    await actors.update_one({"_id": ObjectId(actor_id)}, {"$set": {
        "name": name, "bio": bio, "category": category, "tags": [t.strip() for t in d.get('tags', '').strip().split(",") if t.strip()],
        "social_links": {"instagram": d.get('insta', '').strip(), "youtube": d.get('yt', '').strip(), "twitter": d.get('twitter', '').strip()}
    }})
    return web.HTTPFound(f'/actor/{actor_id}?msg=Profile and Social Networks synced successfully!')

# ─────────────────────────────────────────────────────────
# ⚙️ PROFILE: UPDATE AVATAR
# ─────────────────────────────────────────────────────────
@actor_routes.post('/api/actor/update_avatar')
async def api_actor_update_avatar(req):
    role, _ = await get_auth(req)
    if role != 'admin': return web.json_response({"error": "Unauthorized"}, status=403, dumps=fast_json)
    try:
        data = await req.post()
        if not data.get("actor_id") or not data.get("photo"): return web.json_response({"success": False, "error": "Invalid assets data"}, dumps=fast_json)
            
        tg_photo_id = await upload_tg_photo(ACTOR_STORAGE_CHANNEL, data.get("photo").file.read(), f"avatar_{data.get('actor_id')}_{int(time.time())}.jpg")
            
        if not tg_photo_id: return web.json_response({"success": False, "error": "Telegram upload failed"}, dumps=fast_json)
        
        # ✅ UPGRADE: डेटाबेस में अवतार चेंज होने पर परमानेंट 'is_actor_permanent: True' लॉक सिंक
        await actors.update_one({"_id": ObjectId(data.get("actor_id"))}, {"$set": {"photo_url": f"TG_ID:{tg_photo_id}", "is_actor_permanent": True, "photo_updated_at": int(time.time())}})
        return web.json_response({"success": True, "photo_updated_at": int(time.time())}, dumps=fast_json)
    except Exception as e: return web.json_response({"success": False, "error": str(e)}, dumps=fast_json)

# ─────────────────────────────────────────────────────────
# ⚙️ PROFILE: GALLERY UPLOAD
# ─────────────────────────────────────────────────────────
@actor_routes.post('/api/actor/gallery_upload')
async def api_actor_gallery_upload(req):
    role, _ = await get_auth(req)
    if role != 'admin': return web.json_response({"error": "Unauthorized"}, status=403, dumps=fast_json)
    try:
        reader = await req.multipart()
        actor_id = None
        tg_photo_ids = []
        image_number = 1
        while True:
            part = await reader.next()
            if part is None: break
            if part.name == 'actor_id':
                actor_id = (await part.read()).decode().strip()
            elif part.name == 'gallery_img':
                image_bytes = await part.read()
                if image_bytes:
                    tg_photo_id = await upload_tg_photo(ACTOR_STORAGE_CHANNEL, image_bytes, f"gallery_{actor_id}_{int(time.time())}_{image_number}.jpg")
                    if not tg_photo_id:
                        return web.HTTPFound(f'/actor/{actor_id}?err=Telegram Node Gallery Upload Failed ({image_number})')
                    tg_photo_ids.append(f"TG_ID:{tg_photo_id}")
                    image_number += 1
            
        if not actor_id or not tg_photo_ids:
            return web.HTTPFound('/actors?err=Assets reading packet failure')

        await actors.update_one(
            {"_id": ObjectId(actor_id)},
            {"$push": {"gallery": {"$each": tg_photo_ids}}, "$set": {"is_gallery_permanent": True, "gallery_updated_at": int(time.time())}}
        )
        return web.HTTPFound(f'/actor/{actor_id}?msg={len(tg_photo_ids)} portrait(s) uploaded successfully to star gallery!')
    except Exception as e: return web.HTTPFound(f'/actors?err=System core crash: {str(e)}')

# ─────────────────────────────────────────────────────────
# ⚙️ PROFILE: GALLERY DELETE
# ─────────────────────────────────────────────────────────
@actor_routes.post('/api/actor/gallery_delete')
async def api_actor_gallery_delete(req):
    role, _ = await get_auth(req)
    if role != 'admin': return web.json_response({"error": "Unauthorized"}, status=403, dumps=fast_json)
    try:
        body = await req.json()
        actor_id, index = body.get("actor_id"), body.get("index")
        if not actor_id or index is None:
            return web.json_response({"success": False, "error": "Missing actor_id/index"}, dumps=fast_json)
        # ✅ DUPLICATION FIX: यह लॉजिक अब database/ia_filterdb.py के
        # delete_gallery_image_by_index() से आता है (वही जगह जो पहले से मौजूद थी
        # और $pull का सुरक्षित atomic तरीका इस्तेमाल करती है, यहाँ दोबारा
        # find + manual splice + पूरा array $set नहीं लिखा गया)।
        ok = await delete_gallery_image_by_index(actor_id, int(index))
        if not ok:
            return web.json_response({"success": False, "error": "Actor not found or index out of bounds"}, dumps=fast_json)
        return web.json_response({"success": True}, dumps=fast_json)
    except Exception as e: return web.json_response({"success": False, "error": str(e)}, dumps=fast_json)

# ─────────────────────────────────────────────────────────
# ⚙️ PROFILE: DELETE WHOLE PROFILE
# ─────────────────────────────────────────────────────────
@actor_routes.post('/api/actor/delete')
async def api_actor_delete(req):
    role, _ = await get_auth(req)
    if role != 'admin': return web.json_response({"error": "Unauthorized"}, status=403, dumps=fast_json)
    if not req.query.get("id"): return web.json_response({"error": "Missing ID"}, status=400, dumps=fast_json)
    try:
        # ✅ DUPLICATION FIX: database/ia_filterdb.py का delete_actor_profile()
        # पहले से मौजूद था, यहाँ दोबारा actors.delete_one() लिखने की जरूरत नहीं।
        ok = await delete_actor_profile(req.query.get("id"))
        if not ok: return web.json_response({"error": "Actor not found"}, status=404, dumps=fast_json)
        return web.json_response({"success": True}, dumps=fast_json)
    except Exception as e: return web.json_response({"error": str(e)}, status=500, dumps=fast_json)
