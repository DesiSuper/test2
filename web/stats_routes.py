import asyncio
from aiohttp import web
from web.web_assets import build_page, get_auth
# ✅ DRY: directory + post-category counts अब ia_filterdb के shared helpers से आते
# हैं। पहले यहाँ actors.count_documents × 4 और posts aggregation खुद लिखी थी, और
# वही ब्लॉक plugins/commands.py में भी (दो बार) कॉपी था — यानी 3 copies।
from database.ia_filterdb import db_count_documents, get_directory_counts, get_post_category_counts
from database.users_chats_db import db as user_db
from info import PORT

stats_routes = web.RouteTableDef()

_STATS_CSS = """<style>
@keyframes fadeUp{from{opacity:0;transform:translateY(16px)}to{opacity:1;transform:translateY(0)}}
@keyframes growBar{from{width:0!important}}
@keyframes pulse{0%,100%{box-shadow:0 0 0 0 currentColor}50%{box-shadow:0 0 0 5px transparent}}
.anim-card{animation:fadeUp .5s ease both}
.hero-stat{background:linear-gradient(135deg,var(--card) 0%,var(--bg3) 100%);border:1px solid var(--border);border-radius:16px;padding:28px 32px;margin-bottom:24px;display:flex;align-items:center;gap:28px;position:relative;overflow:hidden;transition:background .35s,border-color .35s;}
.hero-stat::before{content:'';position:absolute;top:0;left:0;right:0;height:3px;background:linear-gradient(90deg,#3399ff,#9933ff,#e50914);}
.hero-num{font-size:52px;font-weight:900;letter-spacing:-2px;line-height:1;flex-shrink:0;color:var(--text);}
.hero-right{flex:1;min-width:0;} .hero-badges{display:flex;gap:8px;flex-wrap:wrap;margin-bottom:14px;} .hero-badge{font-size:11px;font-weight:600;padding:4px 12px;border-radius:99px;}
.hero-thumb{text-align:right;flex-shrink:0;} .hero-thumb-val{font-size:22px;font-weight:800;color:#e50914;}
.multi-bar{display:flex;height:6px;border-radius:99px;overflow:hidden;background:var(--bg4);margin-bottom:6px;transition:background .35s;}
.multi-bar-seg{height:100%;animation:growBar .8s cubic-bezier(.4,0,.2,1) both;} .multi-bar-legend{display:flex;gap:14px;font-size:11px;color:var(--muted);} .mbl-dot{display:inline-block;width:8px;height:8px;border-radius:2px;margin-right:4px;vertical-align:middle;}
.stats-grid-3{display:grid;grid-template-columns:repeat(3,1fr);gap:16px;margin-bottom:20px;} .stats-grid-2{display:grid;grid-template-columns:1fr 1fr;gap:16px;margin-bottom:28px;}
.st-card{background:var(--card);border:1px solid var(--border);border-radius:12px;padding:20px;position:relative;overflow:hidden;transition:background .35s,border-color .35s,transform .2s,box-shadow .2s;}
.st-card:hover{transform:translateY(-2px);box-shadow:0 8px 24px rgba(0,0,0,.25);} .st-card-bar{position:absolute;top:0;left:0;right:0;height:3px;}
.st-label{font-size:11px;font-weight:700;color:var(--muted);text-transform:uppercase;letter-spacing:.6px;margin-bottom:10px;margin-top:6px;transition:color .35s;}
.st-val{font-size:32px;font-weight:900;letter-spacing:-1px;margin-bottom:12px;line-height:1;} .st-sub{font-size:12px;color:var(--muted);transition:color .35s;}
.prog-wrap{background:var(--bg4);border-radius:99px;height:5px;margin-bottom:10px;overflow:hidden;transition:background .35s;} .prog-bar{height:100%;border-radius:99px;animation:growBar .8s cubic-bezier(.4,0,.2,1) both;}
.thumb-badge{display:inline-flex;align-items:center;gap:5px;font-size:11px;background:var(--bg3);border:1px solid var(--border);border-radius:6px;padding:4px 10px;color:var(--muted);transition:background .35s,border-color .35s;} .pct-label{font-size:13px;font-weight:700;}
.user-sub-row{display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-top:12px;} .user-sub-cell{background:var(--bg3);border:1px solid var(--border);border-radius:8px;padding:8px 12px;transition:background .35s,border-color .35s;} .user-sub-cell-lbl{font-size:10px;color:var(--muted);margin-bottom:2px;} .user-sub-cell-val{font-size:15px;font-weight:700;}
.flush-btn{margin-top:12px;width:100%;background:transparent;border:1px solid var(--border);border-radius:7px;padding:8px 12px;font-size:12px;font-weight:600;color:var(--muted);cursor:pointer;font-family:inherit;transition:all .2s;display:flex;align-items:center;justify-content:center;gap:6px;}
.flush-btn:hover{background:var(--bg3);color:var(--text);border-color:var(--accent);} .flush-btn:active{transform:scale(.97);}
.telemetry-title{font-size:11px;font-weight:700;letter-spacing:2px;text-transform:uppercase;color:var(--muted);margin-bottom:14px;display:flex;align-items:center;gap:8px;} .telemetry-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:14px;}
.t-card{background:var(--bg2);border:1px solid var(--border);border-radius:10px;padding:16px 18px;display:flex;align-items:flex-start;gap:12px;transition:background .35s,border-color .35s;}
.t-dot{width:10px;height:10px;border-radius:50%;flex-shrink:0;margin-top:4px;} .t-dot-pulse{animation:pulse 1.8s ease-in-out infinite;color:#28a745;}
.t-lbl{font-size:10px;font-weight:700;color:var(--muted);text-transform:uppercase;letter-spacing:.5px;margin-bottom:4px;transition:color .35s;} .t-val{font-size:14px;font-weight:700;} .t-sub{font-size:11px;color:var(--muted);margin-top:2px;transition:color .35s;}
@media(max-width:800px){.stats-grid-3,.telemetry-grid{grid-template-columns:1fr 1fr;}.stats-grid-2{grid-template-columns:1fr;}.hero-stat{flex-direction:column;align-items:flex-start;}.hero-num{font-size:36px;}}
</style>"""

_STATS_JS = """<script>
(function(){
  function countUp(el, target, duration) {
    var start = performance.now();
    var fmt = function(n){ return Math.floor(n).toLocaleString('en-IN'); };
    requestAnimationFrame(function step(now) {
      var p = Math.min((now - start) / duration, 1);
      el.textContent = fmt((1 - Math.pow(1 - p, 3)) * target);
      if (p < 1) requestAnimationFrame(step);
    });
  }
  document.querySelectorAll('[data-count]').forEach(function(el) {
    setTimeout(function(){ countUp(el, parseFloat(el.dataset.count), 900); }, parseFloat(el.dataset.delay || '0'));
  });
  document.querySelectorAll('.anim-card').forEach(function(el, i) { el.style.animationDelay = (i * 0.07) + 's'; });

  // ✅ ADDED: Database Storage Stats Fetcher
  async function loadDbStats() {
      try {
          let r = await fetch('/api/db_stats');
          let d = await r.json();
          if(d.used) {
              document.getElementById('db-used-val').innerText = d.used;
              document.getElementById('db-prog-bar').style.width = d.percent + '%';
              document.getElementById('db-pct-val').innerText = d.percent + '%';
              
              // Warning if storage is above 85%
              if(d.percent > 85) {
                  document.getElementById('db-used-val').style.color = '#e50914';
                  document.getElementById('db-prog-bar').style.background = 'linear-gradient(90deg,#e50914,#ff4d4d)';
                  document.getElementById('db-pct-val').style.color = '#e50914';
              }
          }
      } catch(e) {
          document.getElementById('db-used-val').innerText = 'Error';
      }
  }
  setTimeout(loadDbStats, 300); // Start after UI loads
})();

// Flush RAM Cache functionality
// ✅ FIX: पहले यह सिर्फ़ setTimeout से "cleared" दिखा देता था, कोई असली API call नहीं थी
async function triggerCacheFlush() {
    var btn = document.getElementById('flushBtn');
    var originalText = btn.innerHTML;
    btn.innerHTML = '⏳ Flushing...';
    btn.disabled = true;
    try {
        let r = await fetch('/api/flush_cache', {method:'POST'});
        let d = await r.json().catch(() => ({}));
        if (!r.ok || d.error) throw new Error(d.error || ('HTTP ' + r.status));
        btn.style.color = '#28a745';
        btn.style.borderColor = '#28a745';
        btn.innerHTML = '✅ Cache Cleared!';
    } catch(e) {
        btn.style.color = '#e50914';
        btn.style.borderColor = '#e50914';
        btn.innerHTML = '❌ Error';
    } setTimeout(() => {
        btn.innerHTML = originalText;
        btn.style.color = '';
        btn.style.borderColor = '';
        btn.disabled = false;
    }, 2500);
}
</script>"""

async def _get_total_plays():
    """🎥 वेबसाइट/मिनी-ऐप पर कुल stream plays"""
    stats_doc = await user_db.settings.find_one({"id": "global_stream_stats"}, {"total_web_plays": 1})
    return stats_doc.get("total_web_plays", 0) if stats_doc else 0


@stats_routes.get('/stats')
async def stats(req):
    role, _ = await get_auth(req)
    if role != 'admin': return web.HTTPFound('/dashboard')

    default_s = {'total': 0, 'primary': 0, 'cloud': 0, 'archive': 0, 'primary_thumb': 0, 'cloud_thumb': 0, 'archive_thumb': 0, 'total_thumb': 0}

    async def _safe(coro, default):
        """हर counter अलग-अलग fail-safe है — एक DB error पूरा /stats पेज नहीं गिराएगा"""
        try:
            return await coro
        except Exception:
            return default

    # ⚡ FAST: ये सब counts एक-दूसरे से independent हैं, इसलिए पहले 10+ sequential
    # round-trips की जगह अब सब parallel चलते हैं (stats पेज का मुख्य delay यही था)।
    (s, u, total_plays, logged_in_today, premium_users,
     (tot_dir, act_dir, app_dir, web_dir), post_stats) = await asyncio.gather(
        _safe(db_count_documents(), default_s),
        _safe(user_db.total_users_count(), 0),
        _safe(_get_total_plays(), 0),
        _safe(user_db.get_today_logged_in_users_count(), 0),
        _safe(user_db.get_premium_users_count(), 0),
        get_directory_counts(),
        get_post_category_counts(),
    )
    if not isinstance(s, dict):
        s = default_s

    post_total, post_movies, post_webseries, post_appvid, post_porn = post_stats
    # कोई पुराना/कस्टम category value जो ऊपर के 4 fixed buckets में फिट नहीं होता
    post_other = post_total - post_movies - post_webseries - post_appvid - post_porn

    p_tot, c_tot, a_tot = s.get('primary', 0), s.get('cloud', 0), s.get('archive', 0)
    grand_total = s.get('total', 1) or 1
    p_pct, c_pct, a_pct = int((p_tot / grand_total) * 100), int((c_tot / grand_total) * 100), int((a_tot / grand_total) * 100)

    body = f'''{_STATS_CSS}<div class="main" style="padding-top:40px;">
  <div class="hero-stat anim-card">
    <div>
      <div style="font-size:12px;color:var(--muted);text-transform:uppercase;letter-spacing:1.5px;margin-bottom:8px;">Total Cloud Archive Matrix</div>
      <div class="hero-num" data-count="{s.get('total', 0)}" data-delay="0">{s.get('total', 0):,}</div>
    </div>
    <div class="hero-right">
      <div class="hero-badges">
        <span class="hero-badge" style="background:#3399ff22;color:#3399ff;border:1px solid #3399ff44;">🎬 {p_tot:,} Movies</span>
        <span class="hero-badge" style="background:#ff993322;color:#ff9933;border:1px solid #ff993344;">📺 {c_tot:,} Series</span>
        <span class="hero-badge" style="background:#9933ff22;color:#9933ff;border:1px solid #9933ff44;">🗄️ {a_tot:,} Archive</span>
      </div>
      <div class="multi-bar">
        <div class="multi-bar-seg" style="width:{p_pct}%;background:#3399ff;animation-delay:.3s;"></div>
        <div class="multi-bar-seg" style="width:{c_pct}%;background:#ff9933;animation-delay:.45s;"></div>
        <div class="multi-bar-seg" style="width:{a_pct}%;background:#9933ff;animation-delay:.6s;"></div>
      </div>
      <div class="multi-bar-legend">
        <span><span class="mbl-dot" style="background:#3399ff;"></span>Movies {p_pct}%</span>
        <span><span class="mbl-dot" style="background:#ff9933;"></span>Series {c_pct}%</span>
        <span><span class="mbl-dot" style="background:#9933ff;"></span>Archive {a_pct}%</span>
      </div>
    </div>
    <div class="hero-thumb">
      <div style="font-size:11px;color:var(--muted);margin-bottom:4px;">Total Thumbnails</div>
      <div class="hero-thumb-val" data-count="{s.get('total_thumb', 0)}" data-delay="100">{s.get('total_thumb', 0):,}</div>
      <div style="font-size:11px;color:var(--muted);margin-top:2px;">cached assets</div>
    </div>
  </div>
  <div class="stats-grid-3">
    <div class="st-card anim-card"><div class="st-card-bar" style="background:#3399ff;"></div><div class="st-label">Primary Cloud — Movies</div><div class="st-val" style="color:#3399ff;" data-count="{p_tot}" data-delay="120">{p_tot:,}</div><div class="prog-wrap"><div class="prog-bar" style="width:{p_pct}%;background:linear-gradient(90deg,#3399ff,#66bbff);animation-delay:.4s;"></div></div><div style="display:flex;justify-content:space-between;align-items:center;"><span class="thumb-badge">🖼️ {s.get('primary_thumb', 0):,} cached</span><span class="pct-label" style="color:#3399ff;">{p_pct}%</span></div></div>
    <div class="st-card anim-card"><div class="st-card-bar" style="background:#ff9933;"></div><div class="st-label">Cloud Library — Series</div><div class="st-val" style="color:#ff9933;" data-count="{c_tot}" data-delay="180">{c_tot:,}</div><div class="prog-wrap"><div class="prog-bar" style="width:{c_pct}%;background:linear-gradient(90deg,#ff9933,#ffcc77);animation-delay:.45s;"></div></div><div style="display:flex;justify-content:space-between;align-items:center;"><span class="thumb-badge">🖼️ {s.get('cloud_thumb', 0):,} cached</span><span class="pct-label" style="color:#ff9933;">{c_pct}%</span></div></div>
    <div class="st-card anim-card"><div class="st-card-bar" style="background:#9933ff;"></div><div class="st-label">Backup Warehouse — Archive</div><div class="st-val" style="color:#9933ff;" data-count="{a_tot}" data-delay="240">{a_tot:,}</div><div class="prog-wrap"><div class="prog-bar" style="width:{a_pct}%;background:linear-gradient(90deg,#9933ff,#cc77ff);animation-delay:.5s;"></div></div><div style="display:flex;justify-content:space-between;align-items:center;"><span class="thumb-badge">🖼️ {s.get('archive_thumb', 0):,} cached</span><span class="pct-label" style="color:#9933ff;">{a_pct}%</span></div></div>
  </div>
  
  <div class="stats-grid-3">
    <div class="st-card anim-card"><div class="st-card-bar" style="background:#e50914;"></div><div class="st-label">Global Image Assets</div><div class="st-val" style="color:#e50914;" data-count="{s.get('total_thumb', 0)}" data-delay="300">{s.get('total_thumb', 0):,}</div><div class="st-sub" style="margin-bottom:12px;">Verified blob identifiers across all DBs</div><button class="flush-btn" id="flushBtn" onclick="triggerCacheFlush()">🧹 Flush RAM Cache</button></div>
    
    <div class="st-card anim-card">
        <div class="st-card-bar" style="background:#00d2c4;"></div>
        <div class="st-label">Global Video Stream Plays</div>
        <div class="st-val" style="color:#00d2c4;" data-count="{total_plays}" data-delay="320">{total_plays:,}</div>
        <div class="st-sub">Total video play counter requests filtered</div>
        <div class="user-sub-row">
            <div class="user-sub-cell" style="grid-column: span 2; text-align: center; background: rgba(0, 210, 196, 0.05);">
                <div class="user-sub-cell-lbl">Platform Traffic Status</div>
                <div class="user-sub-cell-val" style="color:#00d2c4; font-size: 13px;">📊 Streaming Live Counters Active</div>
            </div>
        </div>
    </div>

    <div class="st-card anim-card">
        <div class="st-card-bar" style="background:#28a745;"></div>
        <div class="st-label">MongoDB Storage Limit</div>
        <div class="st-val" id="db-used-val" style="color:#28a745;">Loading..</div>
        <div class="st-sub">Free Tier Maximum: 512.0 MB</div>
        <div class="prog-wrap" style="margin-top:10px;">
            <div class="prog-bar" id="db-prog-bar" style="width:0%; background:linear-gradient(90deg,#28a745,#5cd675); transition: width 1s ease;"></div>
        </div>
        <div style="display:flex;justify-content:space-between;align-items:center;">
            <span class="thumb-badge">💾 Used Space</span>
            <span class="pct-label" id="db-pct-val" style="color:#28a745;">0%</span>
        </div>
    </div>
  </div>
  
  <div class="stats-grid-2">
    <div class="st-card anim-card">
        <div class="st-card-bar" style="background:var(--muted);"></div>
        <div class="st-label">Total System Subscribers</div>
        <div class="st-val" data-count="{u}" data-delay="350">{u:,}</div>
        <div class="st-sub">Active database records</div>
        <div class="user-sub-row">
            <div class="user-sub-cell">
                <div class="user-sub-cell-lbl">Logged In Today</div>
                <div class="user-sub-cell-val" style="color:#00d2c4;" data-count="{logged_in_today}" data-delay="380">{logged_in_today}</div>
            </div>
            <div class="user-sub-cell">
                <div class="user-sub-cell-lbl">Premium Users</div>
                <div class="user-sub-cell-val" style="color:#ff9933;" data-count="{premium_users}" data-delay="400">{premium_users}</div>
            </div>
        </div>
    </div>
    
    <div class="st-card anim-card">
        <div class="st-card-bar" style="background:#e50914;"></div>
        <div class="st-label">Universal Directory Profiles</div>
        <div class="st-val" style="color:#e50914;" data-count="{tot_dir}" data-delay="360">{tot_dir:,}</div>
        <div class="st-sub">Total profiles created across all categories</div>
        <div class="user-sub-row">
            <div class="user-sub-cell">
                <div class="user-sub-cell-lbl">🎭 Actors</div>
                <div class="user-sub-cell-val" style="color:#3399ff;" data-count="{act_dir}" data-delay="380">{act_dir:,}</div>
            </div>
            <div class="user-sub-cell">
                <div class="user-sub-cell-lbl">📱 Apps</div>
                <div class="user-sub-cell-val" style="color:#28a745;" data-count="{app_dir}" data-delay="400">{app_dir:,}</div>
            </div>
            <div class="user-sub-cell" style="grid-column: span 2; display: flex; justify-content: space-between; align-items: center;">
                <div class="user-sub-cell-lbl" style="margin:0;">🌐 Websites</div>
                <div class="user-sub-cell-val" style="color:#9933ff;" data-count="{web_dir}" data-delay="420">{web_dir:,}</div>
            </div>
        </div>
    </div>

    <div class="st-card anim-card">
        <div class="st-card-bar" style="background:#00d2c4;"></div>
        <div class="st-label">Content Posts Created</div>
        <div class="st-val" style="color:#00d2c4;" data-count="{post_total}" data-delay="380">{post_total:,}</div>
        <div class="st-sub">Total posts published across all categories</div>
        <div class="user-sub-row">
            <div class="user-sub-cell">
                <div class="user-sub-cell-lbl">🎬 Movies</div>
                <div class="user-sub-cell-val" style="color:#3399ff;" data-count="{post_movies}" data-delay="400">{post_movies:,}</div>
            </div>
            <div class="user-sub-cell">
                <div class="user-sub-cell-lbl">📺 Web Series</div>
                <div class="user-sub-cell-val" style="color:#ff9933;" data-count="{post_webseries}" data-delay="420">{post_webseries:,}</div>
            </div>
            <div class="user-sub-cell">
                <div class="user-sub-cell-lbl">📱 App Video</div>
                <div class="user-sub-cell-val" style="color:#28a745;" data-count="{post_appvid}" data-delay="440">{post_appvid:,}</div>
            </div>
            <div class="user-sub-cell">
                <div class="user-sub-cell-lbl">🔞 Porn</div>
                <div class="user-sub-cell-val" style="color:#e50914;" data-count="{post_porn}" data-delay="460">{post_porn:,}</div>
            </div>
            {f'<div class="user-sub-cell" style="grid-column: span 2; display: flex; justify-content: space-between; align-items: center;"><div class="user-sub-cell-lbl" style="margin:0;">🗂️ Other/Uncategorized</div><div class="user-sub-cell-val" style="color:var(--muted);" data-count="{post_other}" data-delay="480">{post_other:,}</div></div>' if post_other > 0 else ''}
        </div>
    </div>
    </div>
  <div class="telemetry-title anim-card">💻 Server Core Telemetry Diagnostics</div>
  <div class="telemetry-grid">
    <div class="t-card anim-card"><div class="t-dot t-dot-pulse" style="background:#28a745;"></div><div><div class="t-lbl">Koyeb Worker Pod</div><div class="t-val" style="color:#28a745;">🟢 Operational</div><div class="t-sub">Port {PORT} · 0 errors</div></div></div>
    <div class="t-card anim-card"><div class="t-dot" style="background:#3399ff;"></div><div><div class="t-lbl">Database I/O Pool</div><div class="t-val" style="color:#3399ff;">15 Connections Max</div><div class="t-sub">Active pool · healthy</div></div></div>
    <div class="t-card anim-card"><div class="t-dot" style="background:#ff9933;"></div><div><div class="t-lbl">RAM Protection Guard</div><div class="t-val" style="color:#ff9933;">Strictly Bounded</div><div class="t-sub">Enforced memory limit</div></div></div>
  </div>
</div>{_STATS_JS}'''
    return build_page("Stats - Fast Finder", body, "", "stats", role)
