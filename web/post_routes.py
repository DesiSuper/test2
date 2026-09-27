import io, time, html, re
import asyncio
import aiohttp
from aiohttp import web
from bson.objectid import ObjectId
from utils import temp
from info import THUMBNAIL_STORAGE_CHANNEL
# ✅ DRY: Posts collection handle अब ia_filterdb से आता है — पहले यहाँ अलग से
# `motor_db.db["Posts"]` बनाया जाता था, जबकि ia_filterdb.py में वही collection
# पहले से मौजूद था (और उस पर text index भी बनता है)। दो handle एक ही collection
# पर रखने का कोई फायदा नहीं था।
from database.ia_filterdb import posts as posts_col
from web.web_assets import build_page, get_auth, require_active_plan, fast_json, DIRECTORY_CSS, DEFAULT_CATALOG_MODE
from web.utils.tg_media import upload_tg_photo, serve_tg_image

post_routes = web.RouteTableDef()

# ─────────────────────────────────────────────────────────
# 🛠️ ImgBB Auto-Converter Helper Functions
# ─────────────────────────────────────────────────────────
async def fetch_direct_ibb_url(session, url):
    url = url.strip()
    if not url: return None
    if "ibb.co" in url and "i.ibb.co" not in url:
        try:
            async with session.get(url, timeout=10) as resp:
                if resp.status == 200:
                    html_content = await resp.text()
                    match = re.search(r'<meta property="og:image" content="([^"]+)"', html_content)
                    if match: return match.group(1)
        except Exception: pass
    return url

async def convert_all_ibb_links(urls):
    async with aiohttp.ClientSession() as session:
        tasks = [fetch_direct_ibb_url(session, u) for u in urls if u.strip()]
        results = await asyncio.gather(*tasks)
        return [r for r in results if r]

# ─────────────────────────────────────────────────────────
# 🎨 SHARED WIZARD CSS + JS (DRY: Create aur Edit page दोनों इसे reuse करते हैं)
# Module-load पर एक बार बनता है, हर request पर सिर्फ़ string-embed होता है (Koyeb-friendly)
# ─────────────────────────────────────────────────────────
POST_WIZARD_CSS = '''
    <style>
        .page-header { display:flex; align-items:center; gap:15px; margin-bottom:25px; }
        .back-btn { background:var(--bg3); color:var(--text); text-decoration:none; padding:8px 16px; border-radius:6px; font-weight:700; font-size:13px; border:1px solid var(--border); transition:0.2s; display:inline-flex; align-items:center; }
        .back-btn:hover { background:var(--bg4); }
        .page-title { font-size:22px; font-weight:800; color:var(--text); margin:0; }
        
        .step-card { background:var(--bg2); border:1px solid var(--border); border-radius:12px; margin-bottom:20px; overflow:hidden; box-shadow:0 4px 15px rgba(0,0,0,0.1); }
        .step-header { padding:15px 20px; border-bottom:1px solid var(--border); display:flex; align-items:center; gap:12px; }
        .step-num { background:var(--bg4); color:var(--text); width:28px; height:28px; display:flex; align-items:center; justify-content:center; border-radius:50%; font-weight:800; font-size:13px; }
        .step-title { font-weight:800; font-size:13px; letter-spacing:1px; color:var(--text); text-transform:uppercase; }
        .step-body { padding:20px; }
        
        .s-label { display:block; font-size:11px; font-weight:800; color:var(--muted); margin-bottom:8px; text-transform:uppercase; letter-spacing:1px; }
        .s-input { width:100%; background:var(--bg); border:1px solid transparent; padding:14px; color:var(--text); border-radius:8px; margin-bottom:18px; outline:none; transition:0.2s; font-size:14px; font-weight:500; font-family:inherit; }
        .s-input:focus { border-color:var(--accent); }
        .s-input::placeholder { color:var(--muted); opacity:0.6; }
        
        .submit-btn { width:100%; background:var(--accent); color:#fff; border:none; padding:16px; border-radius:8px; font-weight:800; font-size:15px; cursor:pointer; transition:0.2s; letter-spacing:0.5px; margin-bottom:30px; }
        .submit-btn:hover { background:var(--accent-hover); transform:translateY(-2px); }
    </style>
'''

# 🔧 JS में {{f.file_id}} jaise placeholders हैं — इन्हें f-string मानने से बचाने के लिए
# यह constant सीधा JS string है (कोई .format()/f-string नहीं), इसलिए ${...} literal ही रहता है।
POST_WIZARD_JS = '''
    <script>
    var videoSearchReqId = 0;
    var videoSearchOffset = '';
    var videoSearchLastQ = '';
    async function searchVideosForPost(loadMore) {
        const q = document.getElementById('videoSearchInput').value.trim();
        if(!q) { videoSearchReqId++; document.getElementById('videoSearchResults').style.display = 'none'; return; }
        if(!loadMore) { videoSearchOffset = ''; videoSearchLastQ = q; }
        const myReq = ++videoSearchReqId;
        const resDiv = document.getElementById('videoSearchResults');
        const spinTimer = setTimeout(() => {
            if (myReq !== videoSearchReqId) return;
            if(!loadMore) { resDiv.style.display = 'block'; resDiv.innerHTML = '<div style="padding:15px; color:var(--muted); text-align:center; font-size:12px;">🔍 Searching...</div>'; }
        }, 200);
        try {
            const offParam = loadMore ? videoSearchOffset : 0;
            const response = await fetch('/api/search?q=' + encodeURIComponent(q) + '&mode=none&offset=' + offParam);
            if (myReq !== videoSearchReqId) { clearTimeout(spinTimer); return; }
            clearTimeout(spinTimer);
            const data = await response.json();
            if (myReq !== videoSearchReqId) return;
            resDiv.style.display = 'block';
            const moreBtn = document.getElementById('videoSearchMoreBtn');
            if(moreBtn) moreBtn.remove();
            if(!loadMore && (!data.results || data.results.length === 0)) { resDiv.innerHTML = '<div style="padding:15px; color:var(--muted); text-align:center; font-size:12px;">❌ No files found.</div>'; return; }
            let html = '';
            (data.results || []).forEach(f => {
                const safeName = f.name.replace(/'/g, "\\\\'").replace(/"/g, "&quot;");
                html += `<div style="padding:12px 15px; border-bottom:1px solid var(--border); cursor:pointer;" onmouseover="this.style.background='var(--bg2)'" onmouseout="this.style.background='transparent'" onclick="addVideoToPost('${f.file_id}', '${safeName}')"><div style="font-weight:700; font-size:13px; color:var(--text); white-space:nowrap; overflow:hidden; text-overflow:ellipsis;">${f.name}</div><div style="font-size:11px; color:var(--muted); margin-top:4px;">${f.size}</div></div>`;
            });
            if(loadMore) { resDiv.insertAdjacentHTML('beforeend', html); } else { resDiv.innerHTML = html; }
            videoSearchOffset = data.next_offset || '';
            if(videoSearchOffset) {
                resDiv.insertAdjacentHTML('beforeend', '<div id="videoSearchMoreBtn" style="padding:12px 15px; text-align:center; cursor:pointer; color:var(--accent); font-weight:700; font-size:12px;" onclick="searchVideosForPost(true)">⬇️ Show More</div>');
            }
        } catch(e) { resDiv.innerHTML = '<div style="padding:15px; color:var(--accent); text-align:center;">⚠️ Error!</div>'; }
    }
    function addVideoToPost(fileId, fileName) {
        document.getElementById('videoSearchResults').style.display = 'none';
        const container = document.getElementById('selectedVideosContainer');
        if(container.innerHTML.includes('No files selected yet.')) container.innerHTML = '';
        const div = document.createElement('div');
        div.style.cssText = "background:var(--bg); border:1px solid var(--border); padding:15px; border-radius:8px; display:flex; flex-wrap:wrap; gap:10px; align-items:center;";
        div.innerHTML = `
            <div style="width:100%; font-size:12px; font-weight:700; color:var(--muted); white-space:nowrap; overflow:hidden; text-overflow:ellipsis; margin-bottom:5px;">📁 ${fileName}</div>
            <input type="hidden" name="video_id" value="${fileId}">
            <input type="text" name="video_heading" placeholder="Group Name (e.g. Ep 1)" class="s-input" style="margin-bottom:0; flex:1; min-width:120px; padding:10px;" required>
            <input type="text" name="video_name" placeholder="Quality (e.g. 1080p)" class="s-input" style="margin-bottom:0; flex:1; min-width:100px; padding:10px; color:var(--accent);" required>
            <button type="button" onclick="this.parentElement.remove()" style="background:var(--bg3); color:var(--muted); border:1px solid var(--border); padding:10px 15px; border-radius:6px; cursor:pointer; font-weight:bold;">✖</button>`;
        container.appendChild(div);
    }
    </script>
'''

# ─────────────────────────────────────────────────────────
# 📝 1. ADMIN ROUTE: CREATE POST WIZARD (UI)
# ─────────────────────────────────────────────────────────
@post_routes.get('/admin/create_post')
async def create_post_page(req):
    role, _ = await get_auth(req)
    if role != 'admin': return web.HTTPFound('/dashboard')
    
    err = html.escape(req.query.get('err',''))
    msg = html.escape(req.query.get('msg',''))
    err_html = f'<div class="err-box" style="margin-bottom:20px;">{err}</div>' if err else ""
    msg_html = f'<div class="success-box" style="margin-bottom:20px;">{msg}</div>' if msg else ""
    
    html_content = POST_WIZARD_CSS + f'''
    <div class="main" style="max-width:700px; margin:0 auto; padding:30px 20px;">
        <div class="page-header">
            <a href="/posts" class="back-btn">← Cancel</a>
            <h2 class="page-title">New Post</h2>
        </div>
        
        {err_html}
        {msg_html}
        
        <form action="/api/post/publish" method="post" enctype="multipart/form-data">
            
            <div class="step-card">
                <div class="step-header"><span class="step-num">1</span><span class="step-title">Basic Information</span></div>
                <div class="step-body">
                    <label class="s-label">Post Title</label>
                    <input type="text" name="title" placeholder="e.g. Panchayat S03" class="s-input" required>
                    
                    <label class="s-label">Category</label>
                    <select name="category" class="s-input" style="cursor:pointer;" required>
                        <option value="Movies">🎬 Movies</option>
                        <option value="Web Series">📺 Web Series</option>
                        <option value="App Video">📱 App Video</option>
                        <option value="Porn">🔞 Porn</option>
                    </select>

                    <label class="s-label">Short Description</label>
                    <textarea name="description" placeholder="Write something about this post..." class="s-input" style="min-height:100px; resize:vertical;" required></textarea>
                    
                    <label class="s-label">Search Tags (Comma Separated)</label>
                    <input type="text" name="tags" placeholder="e.g. Action, Thriller" class="s-input" style="margin-bottom:0;">
                </div>
            </div>

            <div class="step-card">
                <div class="step-header"><span class="step-num">2</span><span class="step-title">Cover Image</span></div>
                <div class="step-body">
                    <label class="s-label">Image URL</label>
                    <input type="text" name="cover_url" placeholder="Paste link (viewer or direct)..." class="s-input">
                    <label class="s-label">Or Upload File</label>
                    <input type="file" name="cover_file" accept="image/*" class="s-input" style="padding:10px; margin-bottom:0; cursor:pointer;">
                </div>
            </div>

            <div class="step-card">
                <div class="step-header"><span class="step-num">3</span><span class="step-title">Screenshots</span></div>
                <div class="step-body">
                    <label class="s-label">Screenshot URLs</label>
                    <textarea name="screenshot_urls" placeholder="Paste viewer or direct links line by line..." class="s-input" style="min-height:80px;"></textarea>
                    <label class="s-label">And / Or Upload Files</label>
                    <input type="file" name="screenshot_files" accept="image/*" multiple class="s-input" style="padding:10px; margin-bottom:0; cursor:pointer;">
                </div>
            </div>

            <div class="step-card" style="border-color:var(--accent);">
                <div class="step-header" style="border-bottom-color:var(--accent);"><span class="step-num" style="background:var(--accent);">4</span><span class="step-title">Videos / Episodes</span></div>
                <div class="step-body">
                    <div style="display:flex; gap:10px; margin-bottom:15px;">
                        <input type="text" id="videoSearchInput" placeholder="Search files in database..." class="s-input" style="margin-bottom:0;" onkeydown="if(event.key==='Enter'){{ event.preventDefault(); clearTimeout(window.__vsTimer); searchVideosForPost(); }}" oninput="clearTimeout(window.__vsTimer); if(this.value.trim().length<2){{ window.videoSearchReqId = (window.videoSearchReqId||0)+1; var rd=document.getElementById('videoSearchResults'); if(rd) rd.style.display='none'; }} else {{ window.__vsTimer=setTimeout(searchVideosForPost,350); }}">
                        
                    </div>
                    <div id="videoSearchResults" style="background:var(--bg); border-radius:8px; max-height:200px; overflow-y:auto; display:none; margin-bottom:20px; border:1px solid var(--border);"></div>
                    
                    <label class="s-label">Selected Media</label>
                    <div id="selectedVideosContainer" style="display:flex; flex-direction:column; gap:10px; min-height:50px;">
                        <div style="color:var(--muted); font-size:12px; text-align:center; padding:15px; border:1px dashed var(--border); border-radius:8px;">No files selected yet.</div>
                    </div>
                </div>
            </div>

            <button type="submit" class="submit-btn">Publish Post</button>
        </form>
    </div>
    ''' + POST_WIZARD_JS
    return build_page("Create Post", html_content, "", "posts", role)

# ─────────────────────────────────────────────────────────
# ✏️ 2. ADMIN ROUTE: EDIT POST WIZARD (UI)
# ─────────────────────────────────────────────────────────
@post_routes.get('/admin/edit_post/{id}')
async def edit_post_page(req):
    role, _ = await get_auth(req)
    if role != 'admin': return web.HTTPFound('/dashboard')
    
    post_id = req.match_info['id']
    post = await posts_col.find_one({"_id": ObjectId(post_id)})
    if not post: return web.HTTPFound('/posts?err=Post not found')

    title = html.escape(post.get('title', ''))
    desc = html.escape(post.get('description', ''))
    tags = html.escape(", ".join(post.get('tags', [])))
    cover_url = post.get('cover_image', '')
    ss_urls = "\n".join(post.get('screenshots', []))
    
    # 📌 Fetch saved category and build dropdown
    saved_cat = post.get('category', 'Movies')
    cat_opts = ""
    for cat in ['Movies', 'Web Series', 'App Video', 'Porn']:
        sel = 'selected' if cat == saved_cat else ''
        cat_opts += f'<option value="{cat}" {sel}>{"🎬" if cat=="Movies" else "📺" if cat=="Web Series" else "📱" if cat=="App Video" else "🔞"} {cat}</option>'

    video_html = ""
    for v in post.get('videos', []):
        vid = v.get('file_id')
        vheading = html.escape(v.get('heading', 'Download Links'))
        vname = html.escape(v.get('custom_name', '1080p'))
        video_html += f'''
        <div style="background:var(--bg); border:1px solid var(--border); padding:15px; border-radius:8px; display:flex; flex-wrap:wrap; gap:10px; align-items:center;">
            <div style="width:100%; font-size:12px; font-weight:700; color:var(--muted); white-space:nowrap; overflow:hidden; text-overflow:ellipsis; margin-bottom:5px;">📁 Pre-selected Media</div>
            <input type="hidden" name="video_id" value="{vid}">
            <input type="text" name="video_heading" value="{vheading}" placeholder="Group Name" class="s-input" style="margin-bottom:0; flex:1; min-width:120px; padding:10px;" required>
            <input type="text" name="video_name" value="{vname}" placeholder="Quality" class="s-input" style="margin-bottom:0; flex:1; min-width:100px; padding:10px; color:var(--accent);" required>
            <button type="button" onclick="this.parentElement.remove()" style="background:var(--bg3); color:var(--muted); border:1px solid var(--border); padding:10px 15px; border-radius:6px; cursor:pointer; font-weight:bold;">✖</button>
        </div>'''
        
    if not video_html:
        video_html = '<div style="color:var(--muted); font-size:12px; text-align:center; padding:15px; border:1px dashed var(--border); border-radius:8px;">No files selected yet.</div>'

    html_content = POST_WIZARD_CSS + f'''
    <div class="main" style="max-width:700px; margin:0 auto; padding:30px 20px;">
        <div class="page-header">
            <a href="/post/{post_id}" class="back-btn">← Cancel</a>
            <h2 class="page-title">Edit Post</h2>
        </div>
        
        <form action="/api/post/update" method="post" enctype="multipart/form-data">
            <input type="hidden" name="post_id" value="{post_id}">
            
            <div class="step-card">
                <div class="step-header"><span class="step-num">1</span><span class="step-title">Basic Information</span></div>
                <div class="step-body">
                    <label class="s-label">Post Title</label>
                    <input type="text" name="title" value="{title}" class="s-input" required>
                    
                    <label class="s-label">Category</label>
                    <select name="category" class="s-input" style="cursor:pointer;" required>
                        {cat_opts}
                    </select>

                    <label class="s-label">Short Description</label>
                    <textarea name="description" class="s-input" style="min-height:100px; resize:vertical;" required>{desc}</textarea>
                    
                    <label class="s-label">Search Tags</label>
                    <input type="text" name="tags" value="{tags}" class="s-input" style="margin-bottom:0;">
                </div>
            </div>

            <div class="step-card">
                <div class="step-header"><span class="step-num">2</span><span class="step-title">Cover Image</span></div>
                <div class="step-body">
                    <label class="s-label">Image URL</label>
                    <input type="text" name="cover_url" value="{cover_url}" class="s-input">
                    <label class="s-label">Or Upload New File</label>
                    <input type="file" name="cover_file" accept="image/*" class="s-input" style="padding:10px; margin-bottom:0; cursor:pointer;">
                </div>
            </div>

            <div class="step-card">
                <div class="step-header"><span class="step-num">3</span><span class="step-title">Screenshots</span></div>
                <div class="step-body">
                    <label class="s-label">Screenshot URLs</label>
                    <textarea name="screenshot_urls" class="s-input" style="min-height:80px;">{ss_urls}</textarea>
                    <label class="s-label">And / Or Upload Files</label>
                    <input type="file" name="screenshot_files" accept="image/*" multiple class="s-input" style="padding:10px; margin-bottom:0; cursor:pointer;">
                </div>
            </div>

            <div class="step-card" style="border-color:var(--accent);">
                <div class="step-header" style="border-bottom-color:var(--accent);"><span class="step-num" style="background:var(--accent);">4</span><span class="step-title">Videos / Episodes</span></div>
                <div class="step-body">
                    <div style="display:flex; gap:10px; margin-bottom:15px;">
                        <input type="text" id="videoSearchInput" placeholder="Search files in database..." class="s-input" style="margin-bottom:0;" onkeydown="if(event.key==='Enter'){{ event.preventDefault(); clearTimeout(window.__vsTimer); searchVideosForPost(); }}" oninput="clearTimeout(window.__vsTimer); if(this.value.trim().length<2){{ window.videoSearchReqId = (window.videoSearchReqId||0)+1; var rd=document.getElementById('videoSearchResults'); if(rd) rd.style.display='none'; }} else {{ window.__vsTimer=setTimeout(searchVideosForPost,350); }}">
                        
                    </div>
                    <div id="videoSearchResults" style="background:var(--bg); border-radius:8px; max-height:200px; overflow-y:auto; display:none; margin-bottom:20px; border:1px solid var(--border);"></div>
                    
                    <label class="s-label">Selected Media</label>
                    <div id="selectedVideosContainer" style="display:flex; flex-direction:column; gap:10px; min-height:50px;">
                        {video_html}
                    </div>
                </div>
            </div>

            <button type="submit" class="submit-btn">💾 Save Changes</button>
        </form>
    </div>
    ''' + POST_WIZARD_JS
    return build_page("Edit Post", html_content, "", "posts", role)

# ─────────────────────────────────────────────────────────
# ⚙️ 3. API: PUBLISH & UPDATE POSTS
# ─────────────────────────────────────────────────────────
async def process_multipart_post(req, action="publish"):
    reader = await req.multipart()
    post_data = {"title": "", "description": "", "cover_image": "", "category": "Movies", "screenshots": [], "videos": [], "tags": []}
    if action == "publish": post_data["created_at"] = int(time.time())
    
    screenshot_urls_raw = ""
    temp_v_ids, temp_v_headings, temp_v_names = [], [], []
    post_id = None
    
    while True:
        part = await reader.next()
        if part is None: break
        p_name = part.name
        
        if p_name == 'post_id': post_id = (await part.read()).decode().strip()
        elif p_name == 'title': post_data["title"] = (await part.read()).decode().strip()
        elif p_name == 'description': post_data["description"] = (await part.read()).decode().strip()
        elif p_name == 'category': post_data["category"] = (await part.read()).decode().strip()
        elif p_name == 'tags': post_data["tags"] = [t.strip() for t in (await part.read()).decode().strip().split(",") if t.strip()]
        
        elif p_name == 'video_id': temp_v_ids.append((await part.read()).decode().strip())
        elif p_name == 'video_heading': temp_v_headings.append((await part.read()).decode().strip())
        elif p_name == 'video_name': temp_v_names.append((await part.read()).decode().strip())
        
        elif p_name == 'cover_url':
            url = (await part.read()).decode().strip()
            if url: post_data["cover_image"] = url
        elif p_name == 'cover_file' and part.filename:
            img_bytes = await part.read()
            tg_id = await upload_tg_photo(THUMBNAIL_STORAGE_CHANNEL, img_bytes, "cover.jpg")
            if tg_id:
                post_data["cover_image"] = f"TG_ID:{tg_id}"
        elif p_name == 'screenshot_urls': screenshot_urls_raw = (await part.read()).decode().strip()
        elif p_name == 'screenshot_files' and part.filename:
            img_bytes = await part.read()
            tg_id = await upload_tg_photo(THUMBNAIL_STORAGE_CHANNEL, img_bytes, f"ss_{int(time.time())}.jpg")
            if tg_id:
                post_data["screenshots"].append(f"TG_ID:{tg_id}")

    tasks = []
    if post_data["cover_image"] and "ibb.co" in post_data["cover_image"]:
        tasks.append(convert_all_ibb_links([post_data["cover_image"]]))

    raw_urls = []
    if screenshot_urls_raw:
        raw_urls = [u.strip() for u in screenshot_urls_raw.split('\n') if u.strip()]
        tasks.append(convert_all_ibb_links(raw_urls))
        
    if tasks:
        all_results = await asyncio.gather(*tasks)
        if len(tasks) == 1 and screenshot_urls_raw:
             post_data["screenshots"].extend(all_results[0])
        elif len(tasks) == 2:
             if all_results[0]: post_data["cover_image"] = all_results[0][0]
             post_data["screenshots"].extend(all_results[1])
        elif len(tasks) == 1 and not screenshot_urls_raw:
             if all_results[0]: post_data["cover_image"] = all_results[0][0]

    for vid, vheading, vname in zip(temp_v_ids, temp_v_headings, temp_v_names):
        if vid and vname: 
            post_data["videos"].append({"file_id": vid, "heading": vheading or "Download Links", "custom_name": vname})
        
    return post_data, post_id

@post_routes.post('/api/post/publish')
async def api_publish_post(req):
    role, _ = await get_auth(req)
    if role != 'admin': return web.json_response({"error": "Unauthorized"}, status=403, dumps=fast_json)
    try:
        post_data, _ = await process_multipart_post(req, "publish")
        await posts_col.insert_one(post_data)
        return web.HTTPFound('/posts?msg=Post published successfully!')
    except Exception as e: return web.HTTPFound(f'/admin/create_post?err=Server Error: {str(e)}')

@post_routes.post('/api/post/update')
async def api_update_post(req):
    role, _ = await get_auth(req)
    if role != 'admin': return web.HTTPFound('/dashboard')
    try:
        post_data, post_id = await process_multipart_post(req, "update")
        if not post_id: return web.HTTPFound('/posts?err=Missing Post ID')
        
        if not post_data.get("cover_image"):
            old_post = await posts_col.find_one({"_id": ObjectId(post_id)})
            if old_post and old_post.get("cover_image"): post_data["cover_image"] = old_post["cover_image"]

        await posts_col.update_one({"_id": ObjectId(post_id)}, {"$set": post_data})
        return web.HTTPFound(f'/post/{post_id}?msg=Post updated successfully!')
    except Exception as e: return web.HTTPFound(f'/posts?err=Server Error: {str(e)}')

@post_routes.post('/api/post/delete')
async def api_delete_post(req):
    role, _ = await get_auth(req)
    if role != 'admin': return web.json_response({"success": False})
    try:
        data = await req.json()
        await posts_col.delete_one({"_id": ObjectId(data.get('post_id'))})
        return web.json_response({"success": True})
    except: return web.json_response({"success": False})

# ─────────────────────────────────────────────────────────
# 🖼️ 4. API: SERVE TELEGRAM IMAGES FOR POSTS
# ─────────────────────────────────────────────────────────
@post_routes.get('/api/post/photo')
async def get_post_photo(req):
    tg_id = req.query.get("id")
    if not tg_id: return web.Response(status=400)
    try:
        return await serve_tg_image(tg_id, max_age=31536000)
    except: return web.Response(status=500)

# ─────────────────────────────────────────────────────────
# 🌐 5. PUBLIC ROUTE: POSTS DIRECTORY GRID (UPDATE SEARCH UI)
# ─────────────────────────────────────────────────────────
@post_routes.get('/posts')
async def posts_directory_page(req):
    role, tg_id = await get_auth(req)
    if not role: return web.HTTPFound('/login')
    if not await require_active_plan(role, tg_id): return web.HTTPFound('/premium_expired')
    
    all_posts = await posts_col.find({}).sort("created_at", -1).limit(21).to_list(length=21)
    has_next_init = len(all_posts) > 20
    all_posts = all_posts[:20]
    
    admin_btn = '''<button onclick="window.location.href='/admin/create_post'" style="background:var(--accent); color:#fff; border:none; padding:10px 15px; border-radius:8px; font-weight:800; cursor:pointer; font-size:13px; flex:1; min-width:130px; box-shadow:0 4px 15px rgba(229,9,20,0.3); transition:0.2s;">➕ Create</button>''' if role == 'admin' else ""
    
    search_ui = f'''
    {DIRECTORY_CSS}
    
    <div class="search-box">
        <div class="s-row-1" id="postSearchRow">
            <input type="text" id="post_q" class="s-input" placeholder="Search movies, series, posts...">
            <span class="s-spinner" id="postSpinner"></span>
        </div>
        <div class="s-row-2">
            <div class="cdd-wrap" onclick="togglePostCDD('view', event)">
                <span id="post_view_lbl">{'📄 Text' if DEFAULT_CATALOG_MODE == 'text' else '🖼️ Poster'}</span> <span style="font-size:10px; color:var(--muted);">▼</span>
                <div class="cdd-menu" id="post_view_menu">
                    <div class="cdd-item" onclick="pickPostView('poster', '🖼️ Poster', event)">🖼️ Poster</div>
                    <div class="cdd-item" onclick="pickPostView('text', '📄 Text', event)">📄 Text</div>
                </div>
            </div>
            <div class="cdd-wrap" onclick="togglePostCDD('cat', event)">
                <span id="post_cat_lbl">📁 All Categories</span> <span style="font-size:10px; color:var(--muted);">▼</span>
                <div class="cdd-menu" id="post_cat_menu">
                    <div class="cdd-item" onclick="pickPostCat('All', '📁 All Categories', event)">📁 All Categories</div>
                    <div class="cdd-item" onclick="pickPostCat('Movies', '🎬 Movies', event)">🎬 Movies</div>
                    <div class="cdd-item" onclick="pickPostCat('Web Series', '📺 Web Series', event)">📺 Web Series</div>
                    <div class="cdd-item" onclick="pickPostCat('App Video', '📱 App Video', event)">📱 App Video</div>
                    <div class="cdd-item" onclick="pickPostCat('Porn', '🔞 Porn', event)">🔞 Porn</div>
                </div>
            </div>
            {admin_btn}
        </div>
    </div>
    '''

    post_items = ""
    for p in all_posts:
        cover = p.get("cover_image", "")
        img_src = f"/api/post/photo?id={cover.replace('TG_ID:', '')}" if cover.startswith("TG_ID:") else cover
        cat_name = html.escape(p.get("category", "Uncategorized"))
        title_text = html.escape(p.get("title", "Untitled"))
        
        post_items += f'''<div class="act-card card-enter" onclick="window.location.href='/post/{str(p["_id"])}'">
            <div class="poster-wrap" style="position:relative; padding-top:135%; background:var(--bg3); overflow:hidden;">
                <img src="{img_src}" class="act-poster" loading="lazy">
                <div style="position:absolute; top:8px; left:8px; background:rgba(229,9,20,0.9); color:#fff; font-size:10px; padding:4px 8px; border-radius:4px; font-weight:800; backdrop-filter:blur(4px); z-index:2; text-transform:uppercase; box-shadow:0 2px 10px rgba(0,0,0,0.5);">🎬 {cat_name}</div>
                <div style="position:absolute; bottom:0; left:0; right:0; background:linear-gradient(to top, rgba(0,0,0,0.95) 0%, rgba(0,0,0,0.7) 40%, transparent 100%); padding:30px 12px 12px 12px; z-index:2; text-align:center;">
                    <div style="font-size:14.5px; font-weight:900; color:#fff; text-overflow:ellipsis; overflow:hidden; white-space:nowrap; text-shadow:0 2px 6px rgba(0,0,0,0.9); letter-spacing:0.5px;">{title_text}</div>
                </div>
            </div>
            <div class="card-body">
                <div style="font-size:14px; font-weight:800; color:var(--text); text-overflow:ellipsis; overflow:hidden; white-space:nowrap;">{title_text}</div>
                <div style="font-size:11px; color:var(--muted); font-weight:700; margin-top:4px;">{cat_name}</div>
            </div>
        </div>'''
    
    grid_mode_cls = ' grid-text-mode' if DEFAULT_CATALOG_MODE == 'text' else ''
    initial_grid = f'<div id="post_grid_container" class="dir-grid{grid_mode_cls}">{post_items}</div>' if all_posts else '<div style="text-align:center; padding:60px 20px; color:var(--muted);">No posts found.</div>'

    has_nxt_str = "true" if has_next_init else "false"

    js_logic = f'''
    <div class="pg-bar" id="post_pg_box" style="display:none;">
        <button class="pg-btn" id="post_pBtn" onclick="prevPost()" disabled>Previous</button>
        <span class="pg-info" id="post_pgInfo">Page 1</span>
        <button class="pg-btn" id="post_nBtn" onclick="nextPost()">Next</button>
    </div>

    <script>
    var pOff = 0, pLim = 20, pPage = 1;
    var postReqId = 0;
    var pNext = {has_nxt_str};
    var currentPCat = 'All'; var currentPView = '{DEFAULT_CATALOG_MODE}';
    var lastPQ = "", lastPCat = "All", lastPView = "{DEFAULT_CATALOG_MODE}", lastPOff = 0;

    document.addEventListener("DOMContentLoaded", () => {{
        if(sessionStorage.getItem('ff_post_state')) {{
            document.getElementById('post_q').value = sessionStorage.getItem('ff_post_q') || "";
            currentPCat = sessionStorage.getItem('ff_post_cat') || "All";
            currentPView = sessionStorage.getItem('ff_post_view') || "{DEFAULT_CATALOG_MODE}";
            pOff = parseInt(sessionStorage.getItem('ff_post_off') || "0");
            pPage = parseInt(sessionStorage.getItem('ff_post_page') || "1");

            const catMap = {{'All':'📁 All Categories', 'Movies':'🎬 Movies', 'Web Series':'📺 Web Series', 'App Video':'📱 App Video', 'Porn':'🔞 Porn'}};
            const viewMap = {{'poster':'🖼️ Poster', 'text':'📄 Text'}};
            document.getElementById('post_cat_lbl').innerText = catMap[currentPCat] || '📁 All Categories';
            document.getElementById('post_view_lbl').innerText = viewMap[currentPView] || viewMap['{DEFAULT_CATALOG_MODE}'];

            applyPostViewMode();
            searchPosts(true);
        }} else {{
            applyPostViewMode();
            updatePgUI();
            staggerCards(document.getElementById('post_grid_container'));
        }}
    }});

    function closeAllPostCDD() {{ document.getElementById('post_view_menu').style.display='none'; document.getElementById('post_cat_menu').style.display='none'; }}
    document.addEventListener('click', closeAllPostCDD);

    function togglePostCDD(type, e) {{
        e.stopPropagation();
        var menu = document.getElementById('post_' + type + '_menu');
        var isVis = menu.style.display === 'block';
        closeAllPostCDD();
        if (!isVis) menu.style.display = 'block';
    }}

    function pickPostView(val, lbl, e) {{ e.stopPropagation(); currentPView = val; document.getElementById('post_view_lbl').innerText = lbl; closeAllPostCDD(); applyPostViewMode(); resetPost(); searchPosts(); }}
    function pickPostCat(val, lbl, e) {{ e.stopPropagation(); currentPCat = val; document.getElementById('post_cat_lbl').innerText = lbl; closeAllPostCDD(); resetPost(); searchPosts(); }}

    function applyPostViewMode() {{
        var grid = document.getElementById('post_grid_container');
        if(currentPView === 'text') grid.classList.add('grid-text-mode');
        else grid.classList.remove('grid-text-mode');
    }}

    async function searchPosts(forceRestore = false) {{
        var q = document.getElementById('post_q').value.trim();

        if (!forceRestore && q === lastPQ && currentPCat === lastPCat && currentPView === lastPView && pOff === lastPOff) {{ return; }}

        lastPQ = q; lastPCat = currentPCat; lastPView = currentPView; lastPOff = pOff;

        sessionStorage.setItem('ff_post_state', '1');
        sessionStorage.setItem('ff_post_q', q);
        sessionStorage.setItem('ff_post_cat', currentPCat);
        sessionStorage.setItem('ff_post_view', currentPView);
        sessionStorage.setItem('ff_post_off', pOff);
        sessionStorage.setItem('ff_post_page', pPage);

        var myReq = ++postReqId;
        var grid = document.getElementById('post_grid_container');
        var row = document.getElementById('postSearchRow');
        var loadTimer = setTimeout(function() {{
            if (myReq !== postReqId) return;
            if (row) row.classList.add('loading');
        }}, 150);
        try {{
            var res = await fetch(`/api/posts/search?q=${{encodeURIComponent(q)}}&offset=${{pOff}}&category=${{encodeURIComponent(currentPCat)}}`);
            if (myReq !== postReqId) {{ clearTimeout(loadTimer); if (row) row.classList.remove('loading'); return; }}
            clearTimeout(loadTimer);
            if (row) row.classList.remove('loading');
            var data = await res.json();
            if (myReq !== postReqId) return;
            grid.innerHTML = data.html;
            staggerCards(grid);
            pNext = data.has_next;
            applyPostViewMode();
            updatePgUI();
        }} catch(e) {{ clearTimeout(loadTimer); if (row) row.classList.remove('loading'); grid.innerHTML = '<div style="grid-column:1/-1; text-align:center; color:var(--accent);">Error loading posts!</div>'; }}
    }}
    function updatePgUI() {{ var box = document.getElementById('post_pg_box'); box.style.display = (pOff === 0 && !pNext) ? 'none' : 'flex'; document.getElementById('post_pBtn').disabled = (pOff === 0); document.getElementById('post_nBtn').disabled = !pNext; document.getElementById('post_pgInfo').innerText = 'Page ' + pPage; }}
    function resetPost() {{ pOff = 0; pPage = 1; }}
    function nextPost() {{ if(pNext) {{ pOff += pLim; pPage++; searchPosts(); window.scrollTo(0, 50); }} }}
    function prevPost() {{ if(pOff > 0) {{ pOff = Math.max(0, pOff - pLim); pPage--; searchPosts(); window.scrollTo(0, 50); }} }}
    document.getElementById('post_q').addEventListener('keydown', function(e) {{ if(e.key === 'Enter') {{ clearTimeout(postLiveTimer); resetPost(); searchPosts(); }} }});
    var postLiveTimer;
    document.getElementById('post_q').addEventListener('input', function() {{
        clearTimeout(postLiveTimer);
        postLiveTimer = setTimeout(function() {{ resetPost(); searchPosts(); }}, 350);
    }});
    </script>'''

    return build_page("Posts Catalog", f'<div class="main" style="padding-top:20px; max-width:1100px; margin:0 auto; padding-left:20px; padding-right:20px;">{search_ui}{initial_grid}{js_logic}</div>', "", "posts", role)

@post_routes.get('/api/posts/search')
async def api_posts_search(req):
    role, _ = await get_auth(req)
    if not role: return web.json_response({"html": ""}, dumps=fast_json)
    q = req.query.get("q", "").strip()
    category = req.query.get("category", "All").strip()
    
    try: offset = int(req.query.get("offset", 0))
    except: offset = 0
    lim = 20
    
    query = {}
    if q: 
        safe_q = re.escape(q)
        query["$or"] = [{"title": {"$regex": safe_q, "$options": "i"}}, {"tags": {"$regex": safe_q, "$options": "i"}}]
    
    if category and category != "All":
        query["category"] = category
        
    docs = await posts_col.find(query).sort("created_at", -1).skip(offset).limit(lim + 1).to_list(length=lim + 1)
    has_next = len(docs) > lim
    docs = docs[:lim]
    
    if not docs: return web.json_response({"html": '<div style="grid-column:1/-1; text-align:center; color:var(--muted); padding:40px;">No posts matching your search.</div>', "has_next": False}, dumps=fast_json)
        
    html_out = ""
    for p in docs:
        cover = p.get("cover_image", "")
        img_src = f"/api/post/photo?id={cover.replace('TG_ID:', '')}" if cover.startswith("TG_ID:") else cover
        cat_name = html.escape(p.get("category", "Uncategorized"))
        title_text = html.escape(p.get("title", "Untitled"))
        
        html_out += f'''<div class="act-card card-enter" onclick="window.location.href='/post/{str(p["_id"])}'">
            <div class="poster-wrap" style="position:relative; padding-top:135%; background:var(--bg3); overflow:hidden;">
                <img src="{img_src}" class="act-poster" loading="lazy">
                <div style="position:absolute; top:8px; left:8px; background:rgba(229,9,20,0.9); color:#fff; font-size:10px; padding:4px 8px; border-radius:4px; font-weight:800; backdrop-filter:blur(4px); z-index:2; text-transform:uppercase; box-shadow:0 2px 10px rgba(0,0,0,0.5);">🎬 {cat_name}</div>
                <div style="position:absolute; bottom:0; left:0; right:0; background:linear-gradient(to top, rgba(0,0,0,0.95) 0%, rgba(0,0,0,0.7) 40%, transparent 100%); padding:30px 12px 12px 12px; z-index:2; text-align:center;">
                    <div style="font-size:14.5px; font-weight:900; color:#fff; text-overflow:ellipsis; overflow:hidden; white-space:nowrap; text-shadow:0 2px 6px rgba(0,0,0,0.9); letter-spacing:0.5px;">{title_text}</div>
                </div>
            </div>
            <div class="card-body">
                <div style="font-size:14px; font-weight:800; color:var(--text); text-overflow:ellipsis; overflow:hidden; white-space:nowrap;">{title_text}</div>
                <div style="font-size:11px; color:var(--muted); font-weight:700; margin-top:4px;">{cat_name}</div>
            </div>
        </div>'''
            
    return web.json_response({"html": html_out, "has_next": has_next}, dumps=fast_json)

# ─────────────────────────────────────────────────────────
# 🍿 6. PUBLIC ROUTE: SINGLE POST VIEW
# ─────────────────────────────────────────────────────────
@post_routes.get('/post/{id}')
async def single_post_display(req):
    role, tg_id = await get_auth(req)
    if not role: return web.HTTPFound('/login')
    if not await require_active_plan(role, tg_id): return web.HTTPFound('/premium_expired')
    
    try:
        post = await posts_col.find_one({"_id": ObjectId(req.match_info['id'])})
        if not post: return web.Response(text="Post Not Found", status=404)
    except: return web.Response(text="Invalid ID", status=400)
    
    cover = post.get("cover_image", "")
    img_src = f"/api/post/photo?id={cover.replace('TG_ID:', '')}" if cover.startswith("TG_ID:") else cover
    
    # 📌 Show Category along with tags
    cat = post.get("category", "")
    cat_html = f'<span style="background:var(--accent); border:1px solid var(--accent); color:#fff; font-size:12px; padding:5px 12px; border-radius:6px; font-weight:800; letter-spacing:0.5px;">📁 {html.escape(cat)}</span>' if cat else ""
    
    tags_html = "".join([f'<span style="background:var(--bg4); border:1px solid var(--border); color:var(--text); font-size:12px; padding:5px 12px; border-radius:6px; font-weight:700;">#{html.escape(t)}</span>' for t in post.get("tags", [])])
    tags_div = f'<div style="display:flex; flex-wrap:wrap; gap:10px; background:var(--bg); padding:15px; border-radius:8px; margin-top:15px; margin-bottom:15px;">{cat_html}{tags_html}</div>' if (tags_html or cat_html) else ""
    
    # 🍿 Premium Netflix Style Episodes Layout
    video_buttons = ""
    videos = post.get("videos", [])
    if not videos:
        video_buttons = '<div style="color:var(--muted); font-size:14px; font-weight:bold;">No media attached.</div>'
    else:
        grouped_vids = {}
        for v in videos:
            h = v.get("heading", "Download Links")
            if h not in grouped_vids: grouped_vids[h] = []
            grouped_vids[h].append(v)
            
        for heading, v_list in grouped_vids.items():
            video_buttons += f'''
            <div style="margin-bottom:20px; background:var(--bg2); border:1px solid var(--border); border-radius:10px; padding:15px; box-shadow:0 4px 12px rgba(0,0,0,0.1);">
                <div style="font-size:16px; font-weight:900; color:var(--text); margin-bottom:12px; display:flex; align-items:center; gap:10px;">
                    <span style="background:var(--accent); width:5px; height:18px; border-radius:4px;"></span>
                    {html.escape(heading)}
                </div>
                <div style="display:flex; flex-wrap:wrap; gap:10px; padding-left:15px;">'''
            
            for v in v_list:
                vid_id = v.get('file_id')
                v_name = html.escape(v.get('custom_name', 'Play'))
                video_buttons += f'<a href="/setup_stream?file_id={vid_id}&mode=watch" target="_blank" class="ep-btn">🎬 {v_name}</a>'
            
            video_buttons += '</div></div>'
    
    ss_html = ""
    for ss in post.get("screenshots", []):
        s_src = f"/api/post/photo?id={ss.replace('TG_ID:', '')}" if ss.startswith("TG_ID:") else ss
        ss_html += f'<div style="border:1px solid var(--border); border-radius:8px; overflow:hidden; aspect-ratio:16/9; background:var(--bg3); box-shadow:0 4px 15px rgba(0,0,0,0.2);"><img src="{s_src}" style="width:100%; height:100%; object-fit:cover; cursor:pointer; transition:0.3s;" onmouseover="this.style.transform=\'scale(1.03)\'" onmouseout="this.style.transform=\'scale(1)\'" onclick="window.open(this.src, \'_blank\')"></div>'
    
    # 📸 Screenshots Grid (No Box)
    gallery_section = f'''
    <h3 style="font-size:20px; font-weight:800; color:var(--text); border-bottom:1px solid var(--border); padding-bottom:12px; margin-bottom:20px; margin-top:40px; display:flex; align-items:center; gap:10px;">📸 Screenshots</h3>
    <div style="display:grid; grid-template-columns:repeat(auto-fit, minmax(280px, 1fr)); gap:20px;">{ss_html}</div>
    ''' if ss_html else ""

    admin_actions = f'''
    <div style="margin-top:30px; padding:20px; border:1px dashed rgba(160,8,8,0.5); border-radius:12px; display:flex; gap:10px; background:var(--bg2);">
        <a href="/admin/edit_post/{str(post['_id'])}" style="background:var(--bg3); border:1px solid var(--border); color:var(--text); padding:12px 24px; border-radius:8px; font-weight:800; text-decoration:none; font-size:14px; transition:0.2s;">✏️ Edit Post</a>
        <button onclick="if(confirm('Are you sure you want to delete this post?')) {{ fetch('/api/post/delete', {{method:'POST', body:JSON.stringify({{post_id:'{str(post['_id'])}'}})}}).then(r=>r.json()).then(d=>{{ if(d.success) window.location.href='/posts'; else alert('Failed to delete'); }}) }}" style="background:rgba(160,8,8,0.8); border:none; color:#fff; padding:12px 24px; border-radius:8px; font-weight:800; cursor:pointer; font-size:14px; transition:0.2s;">🗑️ Delete</button>
    </div>
    ''' if role == 'admin' else ""

    page_body = f'''
    <style>
        .ep-btn {{ background:var(--bg); border:1px solid var(--accent); color:var(--accent); font-weight:800; font-size:13px; text-decoration:none; padding:10px 20px; border-radius:6px; transition:0.2s; box-shadow:0 4px 10px rgba(0,0,0,0.2); display:inline-block; }}
        .ep-btn:hover {{ background:var(--accent); color:#fff; transform:translateY(-2px); }}
        .ep-btn:active {{ background:#fff !important; color:var(--accent) !important; border-color:#fff !important; transform:scale(0.92); transition:0s; }}
        
        /* 🔥 Hero Section Flexbox Layout */
        .hero-section {{ display:flex; flex-wrap:wrap; gap:30px; margin-bottom:35px; align-items:flex-start; }}
        .hero-poster {{ flex:1 1 250px; max-width:320px; margin:0 auto; width:100%; aspect-ratio:3/4; overflow:hidden; border-radius:12px; box-shadow:0 12px 35px rgba(0,0,0,0.4); border:1px solid var(--border); }}
        .hero-poster img {{ width:100%; height:100%; object-fit:cover; }}
        .hero-details {{ flex:2 1 400px; background:var(--bg2); border:1px solid var(--border); border-radius:12px; padding:30px; box-shadow:0 4px 15px rgba(0,0,0,0.1); }}
        
        @media(max-width:768px) {{
            .hero-poster {{ max-width:280px; }}
            .hero-details {{ padding:20px; }}
        }}
    </style>

    <div class="main" style="max-width:950px; margin:30px auto; padding:0 20px;">
        <div style="display:flex; align-items:center; gap:15px; margin-bottom:25px;">
            <a href="/posts" style="background:var(--bg3); color:var(--text); text-decoration:none; padding:8px 16px; border-radius:6px; font-weight:700; font-size:13px; border:1px solid var(--border); transition:0.2s;">← Catalog</a>
            <h2 style="font-size:22px; font-weight:800; color:var(--text); margin:0;">View Post</h2>
        </div>
        
        <div class="hero-section">
            <div class="hero-poster">
                <img src="{img_src}" alt="Poster">
            </div>
            <div class="hero-details">
                <h1 style="font-size:32px; font-weight:900; color:var(--text); margin:0;">{html.escape(post.get("title", ""))}</h1>
                {tags_div}
                <div style="font-size:15px; color:var(--muted); line-height:1.7; margin-top:10px; white-space:pre-line; font-weight:500;">
                    {html.escape(post.get("description", ""))}
                </div>
            </div>
        </div>

        <div style="margin-bottom:25px;">
            <h3 style="font-size:20px; font-weight:800; color:var(--text); border-bottom:1px solid var(--border); padding-bottom:12px; margin-bottom:25px; display:flex; align-items:center; gap:10px;">🍿 Episodes / Download Links</h3>
            {video_buttons}
        </div>
        
        {gallery_section}
        {admin_actions}

    </div>
    '''
    return build_page(f"{post.get('title', 'Post')} - Catalog", page_body, "", "posts", role)
