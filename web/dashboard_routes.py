import time
from aiohttp import web
from web.web_assets import build_page, get_auth, form_wrapper, MAX_WEB_RESULTS, require_active_plan, DEFAULT_MEDIA_MODE
from utils import temp

dashboard_routes = web.RouteTableDef()

# ─────────────────────────────────────────────────────────────────────────────
# 🎨 DASHBOARD SPECIFIC CSS (सिर्फ सर्च बार और ड्रॉपडाउन के लिए, कार्ड्स ग्लोबल हैं)
# ─────────────────────────────────────────────────────────────────────────────
CARD_CSS = """
<style>
/* ── Search zone ── */
.search-zone{padding:16px 20px 0;max-width:1400px;margin:0 auto}
.search-row1{display:flex;align-items:center;gap:10px;margin-bottom:10px}
.search-row2{display:flex;align-items:center;justify-content:center;gap:10px;margin-bottom:16px}
@media(min-width:768px){
  .search-zone{padding:24px 24px 10px;display:flex;align-items:center;justify-content:center;gap:14px;flex-wrap:nowrap}
  .search-row1{flex:1;max-width:650px;margin-bottom:0}
  .search-row2{margin-bottom:0;justify-content:flex-start;flex-shrink:0}
}

.search-wrap{flex:1;min-width:0;display:flex;align-items:center;background:var(--bg3);border:1.5px solid var(--border);border-radius:12px;padding:0 6px 0 18px;gap:8px;overflow:hidden;min-height:38px;transition:border-color .18s}
.search-wrap:focus-within{border-color:var(--border)}
.search-spinner{display:none;width:15px;height:15px;flex-shrink:0;border:2px solid var(--border);border-top-color:var(--accent);border-radius:50%;animation:searchSpin .6s linear infinite}
.search-wrap.loading .search-spinner{display:inline-block}
@keyframes searchSpin{to{transform:rotate(360deg)}}
.search-input{flex:1;min-width:0;width:100%;background:transparent;border:none;outline:none;color:var(--text);caret-color:var(--accent);font-size:14px;font-weight:600;padding:6px 0;font-family:inherit;-webkit-tap-highlight-color:transparent}
.search-input::placeholder{color:var(--muted);font-weight:400}
.search-input:-webkit-autofill,
.search-input:-webkit-autofill:hover,
.search-input:-webkit-autofill:focus,
.search-input:-webkit-autofill:active{
  -webkit-box-shadow:0 0 0 100px var(--bg3) inset !important;
  box-shadow:0 0 0 100px var(--bg3) inset !important;
  -webkit-text-fill-color:var(--text) !important;
  caret-color:var(--accent) !important;
  border-radius:999px;
  transition:background-color 9999s ease-in-out 0s;
}
.search-btn{position:relative;overflow:hidden;flex-shrink:0;background:var(--accent);color:#fff;border:none;border-radius:12px;padding:0 20px;height:38px;font-size:14px;font-weight:700;cursor:pointer;white-space:nowrap;transition:transform .15s,box-shadow .15s,background .15s;letter-spacing:.3px}
.search-btn:hover{background:var(--accent-hover);transform:scale(1.03);box-shadow:0 6px 22px rgba(229,9,20,0.50)}
.search-btn:active{transform:scale(.96)}
/* ripple */
.search-btn::after{content:'';position:absolute;inset:0;background:rgba(255,255,255,0);border-radius:inherit;pointer-events:none}
.search-btn.ripple-go::after{animation:btnRipple .45s ease-out forwards}
@keyframes btnRipple{0%{background:rgba(255,255,255,0.28);transform:scale(.6)}100%{background:rgba(255,255,255,0);transform:scale(1.6)}}

/* ── Custom dropdown ── */
.cdd-wrap{flex:0 1 auto;min-width:0;position:relative;user-select:none}
.cdd-btn{width:170px;background:var(--bg3);color:var(--text);border:1.5px solid var(--border);border-radius:999px;padding:8px 28px 8px 14px;font-size:11px;font-weight:700;cursor:pointer;font-family:inherit;box-sizing:border-box;display:inline-flex;align-items:center;justify-content:flex-start;gap:5px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;transition:border-color .15s,box-shadow .15s}
.cdd-btn:hover,.cdd-btn.open{border-color:var(--accent);box-shadow:0 0 0 3px rgba(229,9,20,0.12)}
.cdd-arrow{position:absolute;right:12px;top:50%;transform:translateY(-50%);pointer-events:none;font-size:9px;color:var(--muted);transition:transform .2s}
.cdd-btn.open+.cdd-arrow{transform:translateY(-50%) rotate(180deg)}

.cdd-menu{position:absolute;top:calc(100% + 7px);left:50%;transform:translateX(-50%);min-width:max-content;background:var(--bg2,var(--bg3));border:1.5px solid var(--border);border-radius:16px;overflow:hidden;z-index:9999;box-shadow:0 8px 32px rgba(0,0,0,.45);animation:cddIn .15s ease}
@keyframes cddIn{
    from{opacity:0;transform:translate(-50%, -6px)}
    to{opacity:1;transform:translate(-50%, 0)}
}

.cdd-item{display:flex;align-items:center;gap:10px;padding:13px 14px;font-size:13px;font-weight:700;color:var(--text);cursor:pointer;transition:background .12s;border-bottom:1px solid var(--border)}
.cdd-item:last-child{border-bottom:none}
.cdd-item:hover{background:var(--bg3)}
.cdd-item.selected{color:var(--accent)}
.cdd-radio{width:18px;height:18px;border-radius:50%;border:2px solid var(--border);margin-left:auto;flex-shrink:0;display:flex;align-items:center;justify-content:center;transition:border-color .15s}
.cdd-item.selected .cdd-radio{border-color:var(--accent)}
.cdd-radio-dot{width:8px;height:8px;border-radius:50%;background:var(--accent);display:none}
.cdd-item.selected .cdd-radio-dot{display:block}
</style>
"""

# ─────────────────────────────────────────────────────────────────────────────
# 🎬 JS ENGINE — Smart Double Pre-fetching Engine Live Live
# ─────────────────────────────────────────────────────────────────────────────
JS_ENGINE = """
var curQ='',curOff=0,nextOff='',curCol='all',curPage=1;
var searchReqId=0;
var pMode=localStorage.getItem('posterMode')||'__DEFAULT_MEDIA_MODE__';
var LIMIT_VAL = __LIMIT_PLACEHOLDER__;

function closeCdds(){
    document.getElementById('cddColMenu').style.display='none';
    document.getElementById('cddColBtn').classList.remove('open');
    document.getElementById('cddModeMenu').style.display='none';
    document.getElementById('cddModeBtn').classList.remove('open');
}
function toggleCdd(which,e){
    if(e){e.stopPropagation();}
    var menuId=which==='col'?'cddColMenu':'cddModeMenu';
    var btnId=which==='col'?'cddColBtn':'cddModeBtn';
    var otherId=which==='col'?'cddModeMenu':'cddColMenu';
    var otherBtnId=which==='col'?'cddModeBtn':'cddColBtn';
    var menu=document.getElementById(menuId);
    var btn=document.getElementById(btnId);
    var isOpen=menu.style.display!=='none';
    document.getElementById(otherId).style.display='none';
    document.getElementById(otherBtnId).classList.remove('open');
    if(isOpen){menu.style.display='none';btn.classList.remove('open');}
    else{menu.style.display='block';btn.classList.add('open');}
}
function pickCol(val,label,el,e){
    if(e){e.stopPropagation();}
    curCol=val;
    document.getElementById('cddColLabel').textContent=label;
    document.querySelectorAll('#cddColMenu .cdd-item').forEach(function(i){i.classList.remove('selected');});
    el.classList.add('selected');
    document.getElementById('cddColMenu').style.display='none';
    document.getElementById('cddColBtn').classList.remove('open');
    doSearch(0,true);
}
function pickMode(val,label,el,e){
    if(e){e.stopPropagation();}
    pMode=val;
    localStorage.setItem('posterMode',pMode);
    document.getElementById('cddModeLabel').textContent=label;
    document.querySelectorAll('#cddModeMenu .cdd-item').forEach(function(i){i.classList.remove('selected');});
    el.classList.add('selected');
    document.getElementById('cddModeMenu').style.display='none';
    document.getElementById('cddModeBtn').classList.remove('open');
    doSearch(curOff,true);
}
document.addEventListener('click',function(e){
    if(!e.target.closest('.cdd-wrap')){closeCdds();}
});
document.querySelectorAll('.cdd-menu').forEach(function(m){
    m.addEventListener('click',function(e){e.stopPropagation();});
});
function changeCol(val){curCol=val;doSearch(0,true);}

/* ✅ DUPLICATE REMOVED: handleThumbError() यहाँ दोबारा defined था, जबकि
   web_assets.py के global JS में यह पहले से है (और वहाँ वाला version बेहतर है —
   पूरा poster-box overlay करता है, सिर्फ़ छोटा span नहीं)। build_page() global JS
   <head> में डालता है और यह script <body> में बाद में आता है, इसलिए यही कमज़ोर
   copy global वाली को shadow कर रही थी — यानी dashboard पर thumbnail-fail हमेशा
   घटिया दिखता था। अब सिर्फ़ global version चलता है। */

function triggerRipple(btn){btn.classList.remove('ripple-go');void btn.offsetWidth;btn.classList.add('ripple-go');setTimeout(function(){btn.classList.remove('ripple-go');},460);}

async function doSearch(o,allowEmpty){
    var q=document.getElementById('q').value.trim();
    if(!q && !allowEmpty){showToast('Please enter a movie name','error');return;}
    curQ=q;curOff=o;if(o===0)curPage=1;
    if(q){sessionStorage.setItem('ff_dash_q',q);}else{sessionStorage.removeItem('ff_dash_q');}

    var myReq=++searchReqId;
    var resDiv=document.getElementById('results');
    var qWrap=document.getElementById('qWrap');
    var loadTimer=setTimeout(function(){
        if(myReq!==searchReqId)return;
        if(qWrap)qWrap.classList.add('loading');
    },150);

    try{
        var r=await fetch('/api/search?q='+encodeURIComponent(q)+'&offset='+o+'&col='+curCol+'&mode='+pMode);
        if(myReq!==searchReqId){clearTimeout(loadTimer);if(qWrap)qWrap.classList.remove('loading');return;}
        clearTimeout(loadTimer);
        if(qWrap)qWrap.classList.remove('loading');
        var d=null;
        try{d=await r.json();}catch(parseErr){d=null;}
        if(myReq!==searchReqId)return;
        if(!r.ok || (d && d.error)){
            var msg=(d && d.error)?d.error:('Error fetching (HTTP '+r.status+')');
            showToast(msg,'error');
            if(!allowEmpty || q){
                resDiv.innerHTML='<div class="empty"><div class="empty-icon">&#9888;</div><p>'+msg+'</p></div>';
                document.getElementById('pageBox').style.display='none';
            }
            return;
        }
        document.getElementById('resInfo').style.display='none';
        if(!d.results||!d.results.length){
            resDiv.innerHTML = q
                ? '<div class="empty"><div class="empty-icon">&#9888;</div><p>No titles found for "'+q+'"</p></div>'
                : '<div class="empty"><div class="empty-icon">&#8981;</div><p>No files added yet.</p></div>';
            document.getElementById('pageBox').style.display='none';return;
        }
        var h='';
        d.results.forEach(function(f){
            var sc=(f.source||'primary').toLowerCase();
            if(!['primary','cloud','archive'].includes(sc))sc='primary';

            var encName = encodeURIComponent(f.name || '').replace(/'/g, "%27").replace(/"/g, "%22");
            var encCap = encodeURIComponent(f.caption || '').replace(/'/g, "%27").replace(/"/g, "%22");

            var adminBtns='';
            if(d.is_admin){
                adminBtns='<div class="poster-admin">'+
                    '<button class="btn-edit" onclick="event.stopPropagation();editFile(\\''+f.file_id+'\\',\\''+f.raw_collection+'\\',\\''+encName+'\\', \\''+encCap+'\\')">&#9999; Edit</button>'+
                    '<button class="btn-del" onclick="event.stopPropagation();deleteFile(\\''+f.file_id+'\\',\\''+f.raw_collection+'\\')">&#128465; Delete</button>'+
                '</div>';
            }

            /* ⏱️ Duration chip — sirf tab jab API ne asli duration bheja ho.
               Purani (bina-duration index huyi) files par f.duration khali aata hai,
               tab chip banta hi nahi — "0:00" jaisa bekaar text nahi dikhta. */
            var durChip  = f.duration ? '<span class="dur-chip">'+f.duration+'</span>' : '';
            var durText  = f.duration ? '<span class="tc-dur">'+f.duration+'</span>' : '';
            /* 🖼️ Resolution chip (1280×720 → "720p", 1920×1080 → "1080p") — duration chip
               jaisa hi null-tolerant: data na ho to chip banta hi nahi. */
            var resChip  = f.res ? '<span class="res-chip">'+f.res+'</span>' : '';
            var resText  = f.res ? '<span class="tc-res">'+f.res+'</span>' : '';

            var posterHtml='';
            if(pMode!=='none'){
                posterHtml='<div class="poster-box" id="poster-box-'+f.file_id+'" onclick="toggleAdminBtns(this.closest(\\'.file-card\\'),event)">'+
                    '<img src="'+f.tg_thumb+'" id="img-poster-'+f.file_id+'" class="fc-poster" onload="this.classList.add(\\'loaded\\')" onerror="handleThumbError(\\''+f.file_id+'\\')" loading="lazy" decoding="async">'+
                    '<div class="poster-top">'+
                        '<span class="type-chip">'+f.type.toUpperCase()+'</span>'+
                        '<span class="size-chip">'+f.size+'</span>'+
                        durChip+resChip+
                        '<span class="source-pill '+sc+'"><span class="source-dot"></span>'+sc.toUpperCase()+'</span>'+
                    '</div>'+
                    adminBtns+
                '</div>';
            }

            var textInfo='';
            if(pMode==='none'){
                textInfo='<div class="fc-text-info" onclick="toggleAdminBtns(this.closest(\\'.file-card\\'),event)">'+
                    '<span class="tc-type">'+f.type.toUpperCase()+'</span>'+
                    '<span class="tc-size">'+f.size+'</span>'+
                    durText+resText+
                    '<span class="source-pill '+sc+'" style="margin-left:auto"><span class="source-dot"></span>'+sc.toUpperCase()+'</span>'+
                '</div>';
                if(d.is_admin){
                    textInfo+='<div class="text-admin-row">'+
                        '<button class="btn-edit" onclick="event.stopPropagation();editFile(\\''+f.file_id+'\\',\\''+f.raw_collection+'\\',\\''+encName+'\\', \\''+encCap+'\\')">&#9999; Edit</button>'+
                        '<button class="btn-del" onclick="event.stopPropagation();deleteFile(\\''+f.file_id+'\\',\\''+f.raw_collection+'\\')">&#128465; Delete</button>'+
                    '</div>';
                }
            }

            h+='<div class="file-card card-enter">'+
                posterHtml+
                textInfo+
                '<div class="fc-body">'+
                    '<div class="fc-name" id="name-title-'+f.file_id+'" onclick="window.open(\\''+f.watch+'\\',\\'_blank\\')">'+f.name+'</div>'+
                '</div>'+
            '</div>';
        });
        resDiv.className='res-grid mode-'+pMode;
        resDiv.innerHTML=h;
        staggerCards(resDiv);
        nextOff=d.next_offset;
        document.getElementById('pageBox').style.display='flex';
        document.getElementById('pBtn').disabled=(o===0);
        document.getElementById('nBtn').disabled=!nextOff;
        document.getElementById('pgInfo').textContent='Page '+curPage;

        if(nextOff) {
            fetch('/api/search?q='+encodeURIComponent(q)+'&offset='+nextOff+'&col='+curCol+'&mode='+pMode);
        }
    }catch(e){clearTimeout(loadTimer);if(qWrap)qWrap.classList.remove('loading');showToast('Network error','error');}
}

function next(){if(nextOff){curPage++;doSearch(nextOff);scrollTo(0,0);}}
function prev(){if(curPage>1){curPage--;doSearch(Math.max(0,curOff-LIMIT_VAL));scrollTo(0,0);}}

document.addEventListener('DOMContentLoaded',function(){
    var q=document.getElementById('q');
    if(q){
        var qLiveTimer;
        q.addEventListener('input',function(){
            clearTimeout(qLiveTimer);
            var val=q.value.trim();
            if(val.length<2){
                searchReqId++;
                curQ='';
                var qw=document.getElementById('qWrap');if(qw)qw.classList.remove('loading');
                var ri=document.getElementById('resInfo');if(ri)ri.style.display='none';
                var pb=document.getElementById('pageBox');if(pb)pb.style.display='none';
                doSearch(0,true);
                return;
            }
            qLiveTimer=setTimeout(function(){doSearch(0);},350);
        });
        q.addEventListener('keydown',function(e){if(e.key==='Enter'){clearTimeout(qLiveTimer);doSearch(0);}});
    }
    var mItems=document.querySelectorAll('#cddModeMenu .cdd-item');
    mItems.forEach(function(i){i.classList.remove('selected');if(i.dataset.val===pMode)i.classList.add('selected');});
    document.getElementById('cddModeLabel').textContent=(pMode==='none')?'\u26a1 Text Only (Fastest)':'\ud83d\udcf8 Original TG Thumb';
    var savedQ=sessionStorage.getItem('ff_dash_q');
    if(savedQ && q){q.value=savedQ;doSearch(0);}else{doSearch(0,true);}
});
""".replace("__LIMIT_PLACEHOLDER__", str(MAX_WEB_RESULTS)).replace("__DEFAULT_MEDIA_MODE__", DEFAULT_MEDIA_MODE)

# 🎛️ Default mode dropdown state (centralized via DEFAULT_MEDIA_MODE in web_assets.py)
_MODE_TG_LBL = '\U0001f4f8 Original TG Thumb'
_MODE_NONE_LBL = '\u26a1 Text Only (Fastest)'
_DEF_MODE_LBL = _MODE_NONE_LBL if DEFAULT_MEDIA_MODE == 'none' else _MODE_TG_LBL
_SEL_TG = ' selected' if DEFAULT_MEDIA_MODE == 'tg' else ''
_SEL_NONE = ' selected' if DEFAULT_MEDIA_MODE == 'none' else ''

# ─────────────────────────────────────────────────────────────────────────────
# 🏠 SEARCH ZONE HTML
# ─────────────────────────────────────────────────────────────────────────────
SEARCH_ZONE = (
    '<div class="search-zone">'
        '<div class="search-row1">'
            '<div class="search-wrap" id="qWrap">'
                '<input class="search-input" id="q" placeholder="Titles, people, genres\u2026">'
                '<span class="search-spinner" id="qSpinner"></span>'
            '</div>'
        '</div>'
        '<div class="search-row2">'
            '<div class="cdd-wrap" id="cddColWrap">'
                '<div class="cdd-btn" id="cddColBtn" onclick="toggleCdd(\'col\')">'
                    '<span id="cddColLabel">\U0001f4c2 All Collections</span>'
                '</div>'
                '<span class="cdd-arrow">&#9660;</span>'
                '<div class="cdd-menu" id="cddColMenu" style="display:none">'
                    '<div class="cdd-item selected" data-val="all" onclick="pickCol(\'all\',\'\U0001f4c2 All Collections\',this)">\U0001f4c2 All Collections<span class="cdd-radio"><span class="cdd-radio-dot"></span></span></div>'
                    '<div class="cdd-item" data-val="primary" onclick="pickCol(\'primary\',\'\U0001f7e2 Primary\',this)">\U0001f7e2 Primary<span class="cdd-radio"><span class="cdd-radio-dot"></span></span></div>'
                    '<div class="cdd-item" data-val="cloud" onclick="pickCol(\'cloud\',\'\U0001f535 Cloud\',this)">\U0001f535 Cloud<span class="cdd-radio"><span class="cdd-radio-dot"></span></span></div>'
                    '<div class="cdd-item" data-val="archive" onclick="pickCol(\'archive\',\'\U0001f7e0 Archive\',this)">\U0001f7e0 Archive<span class="cdd-radio"><span class="cdd-radio-dot"></span></span></div>'
                '</div>'
            '</div>'
            '<div class="cdd-wrap" id="cddModeWrap">'
                '<div class="cdd-btn" id="cddModeBtn" onclick="toggleCdd(\'mode\')">'
                    '<span id="cddModeLabel">' + _DEF_MODE_LBL + '</span>'
                '</div>'
                '<span class="cdd-arrow">&#9660;</span>'
                '<div class="cdd-menu" id="cddModeMenu" style="display:none">'
                    '<div class="cdd-item' + _SEL_TG + '" data-val="tg" onclick="pickMode(\'tg\',\'\U0001f4f8 Original TG Thumb\',this)">\U0001f4f8 Original TG Thumb<span class="cdd-radio"><span class="cdd-radio-dot"></span></span></div>'
                    '<div class="cdd-item' + _SEL_NONE + '" data-val="none" onclick="pickMode(\'none\',\'\u26a1 Text Only (Fastest)\',this)">\u26a1 Text Only (Fastest)<span class="cdd-radio"><span class="cdd-radio-dot"></span></span></div>'
                '</div>'
            '</div>'
        '</div>'
    '</div>'
    '<div class="main" style="padding-top:4px;">'
        '<div class="results-info" id="resInfo" style="padding:0 12px 8px;">'
            '<span class="results-count" id="resCount"></span>'
        '</div>'
        '<div style="padding:0 2px">'
            '<div id="results" class="res-grid">'
                '<div class="empty"><div class="empty-icon">&#8981;</div>'
                '<p>Find your favorite movies and TV shows.</p></div>'
            '</div>'
            '<div class="pagination" id="pageBox" style="display:none;">'
                '<button class="pg-btn" id="pBtn" onclick="prev()" disabled>Previous</button>'
                '<span class="pg-info" id="pgInfo">Page 1</span>'
                '<button class="pg-btn" id="nBtn" onclick="next()">Next</button>'
            '</div>'
        '</div>'
    '</div>'
    '<div class="toast" id="toast"></div>'
)

# ✅ OPTIMIZATION 1: Pre-compile the entire body string ONCE when the app starts.
DASHBOARD_BODY = CARD_CSS + SEARCH_ZONE + f"<script>{JS_ENGINE}</script>"


@dashboard_routes.get('/dashboard')
async def dash(req):
    role, tg_id = await get_auth(req)
    if not role:
        return web.HTTPFound('/login')
    if not await require_active_plan(role, tg_id):
        return web.HTTPFound('/premium_expired')

    return build_page("Home - Fast Finder", DASHBOARD_BODY, "", "dash", role)


@dashboard_routes.get('/logout')
async def logout(req):
    s_user = req.cookies.get('user_session')
    temp.USER_SESSIONS.pop(s_user, None)
    res = web.HTTPFound('/login')
    res.del_cookie('user_session')
    return res


@dashboard_routes.get('/premium_expired')
async def premium_expired(req):
    role, tg_id = await get_auth(req)
    if not role:
        return web.HTTPFound('/login')
    content = (
        '<div style="text-align:center;">'
        '<div style="font-size:50px;margin-bottom:15px;">&#9203;</div>'
        '<p style="color:var(--muted);margin-bottom:30px;">Your access to Fast Finder Web has expired. '
        'Please renew your plan via our Telegram Bot.</p>'
        '<div class="scard red" style="text-align:left;margin-bottom:25px;padding:15px;">'
        '<div class="scard-label">How to Renew?</div>'
        '<div class="scard-sub" style="color:var(--text)">1. Go to Telegram Bot</div>'
        '<div class="scard-sub" style="color:var(--text)">2. Use command <b>/plan</b></div>'
        '<div class="scard-sub" style="color:var(--text)">3. Pay & Activate instantly</div>'
        '</div>'
        f'<a href="https://t.me/{temp.U_NAME}" class="submit-btn" style="text-decoration:none;display:block;">Open Telegram Bot</a>'
        '<a href="/logout" style="display:block;margin-top:20px;color:var(--muted);text-decoration:none;">Sign Out</a>'
        '</div>'
    )
    return build_page("Premium Expired", form_wrapper("Premium Expired", content), "login-bg")


# ✅ OPTIMIZATION 2: Koyeb Health Check Route
# ✅ DEDUPE: /health पहले यहाँ और bot.py — दोनों में रजिस्टर था। web/__init__.py
# पहले चलने की वजह से यही वाला match होता था, bot.py वाला कभी execute नहीं होता था
# (dead code)। अब route एक ही है, और bot.py वाले handler का useful हिस्सा (uptime)
# यहाँ merge कर दिया गया है।
@dashboard_routes.get('/health')
async def koyeb_health_check(req):
    return web.json_response({
        "status": "alive",
        "platform": "koyeb",
        "uptime_seconds": round(time.time() - temp.START_TIME, 2),
    })
