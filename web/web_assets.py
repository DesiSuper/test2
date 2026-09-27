import time
import orjson
from aiohttp import web
from info import ADMINS, MAX_WEB_RESULTS
from utils import temp
from database.users_chats_db import db as user_db

# ─────────────────────────────────────────────
# ⚡ SHARED JSON DUMPER
# ✅ DRY: यह function पहले search_api.py, actor_routes.py और post_routes.py — तीनों
# में अलग-अलग copy-paste था। तीनों route files यहाँ से import करती हैं।
# ─────────────────────────────────────────────
def fast_json(data):
    """orjson बाइट्स (bytes) में डेटा देता है, aiohttp के लिए इसे स्ट्रिंग में डिकोड करना होता है"""
    return orjson.dumps(data).decode('utf-8')

# ─────────────────────────────────────────────
# 🎛️ CENTRALIZED DEFAULT VIEW MODES
# ✅ DRY: हर page (dashboard, posts, actors, actor-profile, miniapp) का default
# view mode अब यहीं एक जगह से control होता है — बदलना हो तो सिर्फ़ ये दो lines।
#
# DEFAULT_CATALOG_MODE → /posts और /actors directory grids ('poster' | 'text')
# DEFAULT_MEDIA_MODE   → dashboard, miniapp और actor-profile media results ('tg' | 'none')
# ─────────────────────────────────────────────
DEFAULT_CATALOG_MODE = "text"
DEFAULT_MEDIA_MODE = "none"

# ─────────────────────────────────────────────
# 🎨 SHARED DIRECTORY CSS
# ✅ DRY: /actors और /posts दोनों grid pages में यह ~24-rule CSS ब्लॉक हुबहू कॉपी
# था। एक जगह भी class बदलने पर दूसरा पेज टूट जाता। अब दोनों इसी को embed करते हैं।
# ─────────────────────────────────────────────
DIRECTORY_CSS = """
    <style>
        .dir-grid { display: grid; grid-template-columns: repeat(2, 1fr); gap: 12px; }
        @media(min-width: 768px) { .dir-grid { grid-template-columns: repeat(5, 1fr); gap: 20px; } }

        .search-box { background:var(--card); border:1px solid var(--border); padding:16px; border-radius:12px; margin-bottom:25px; box-shadow:0 4px 15px rgba(0,0,0,0.1); }
        .s-row-1 { display: flex; gap: 10px; margin-bottom: 12px; position: relative; }
        .s-input { flex: 1; background:var(--bg3); border:1px solid var(--border); padding:12px 16px; color:var(--text); border-radius:8px; outline:none; font-family:inherit; font-weight:600; font-size:14px; transition:0.2s; }
        .s-input:focus { border-color:var(--accent); }
        .s-spinner { display:none; position:absolute; right:14px; top:50%; transform:translateY(-50%); width:16px; height:16px; border:2px solid var(--border); border-top-color:var(--accent); border-radius:50%; animation:sSpin .6s linear infinite; }
        .s-row-1.loading .s-spinner { display:block; }
        @keyframes sSpin { to { transform:translateY(-50%) rotate(360deg); } }
        .s-btn { background:var(--accent); color:#fff; border:none; padding:0 24px; border-radius:8px; font-weight:800; cursor:pointer; transition:0.2s; white-space:nowrap; }
        .s-btn:hover { background:var(--accent-hover); transform:scale(1.02); }

        .s-row-2 { display: flex; gap: 10px; flex-wrap:wrap; align-items:center; }
        .cdd-wrap { position: relative; background: var(--bg3); border: 1px solid var(--border); border-radius: 8px; padding: 10px 14px; cursor: pointer; font-weight: 700; font-size: 13px; color: var(--text); flex: 1; min-width: 100px; display: flex; justify-content: space-between; align-items: center; user-select: none; transition:0.2s; }
        .cdd-wrap:hover { border-color: var(--accent); }
        .cdd-menu { position: absolute; top: calc(100% + 5px); left: 0; right: 0; background: var(--bg2); border: 1px solid var(--border); border-radius: 8px; overflow: hidden; z-index: 100; display: none; box-shadow: 0 4px 15px rgba(0,0,0,0.3); }
        .cdd-item { padding: 10px 14px; border-bottom: 1px solid var(--border); transition: 0.2s; }
        .cdd-item:last-child { border-bottom: none; }
        .cdd-item:hover { background: var(--bg3); color: var(--accent); }

        .pg-bar { display:flex; justify-content:center; align-items:center; gap:15px; margin-top:30px; }
        .pg-btn { background:var(--bg4); color:var(--text); border:1px solid var(--border); padding:8px 20px; border-radius:6px; font-weight:700; cursor:pointer; font-size:13px; transition:0.2s; }
        .pg-btn:hover:not(:disabled) { background:var(--accent); color:#fff; border-color:var(--accent); }
        .pg-btn:disabled { opacity:0.4; cursor:not-allowed; }
        .pg-info { color:var(--text); font-weight:800; font-size:14px; background:var(--bg3); padding:6px 14px; border-radius:6px; border:1px solid var(--border); }

        /* 📄 Text View mode overrides */
        .card-body { display: none; }
        .grid-text-mode .poster-wrap { display: none !important; }
        .grid-text-mode .act-card { display:flex; align-items:center; padding:5px; background:var(--card); }
        .grid-text-mode .card-body { display: block !important; text-align:left !important; padding:10px 15px !important; flex:1; }
    </style>
"""

# ----------------- ULTRA-PREMIUM GLASS DIAGNOSTICS ASSETS -----------------
CSS = """
*{box-sizing:border-box;margin:0;padding:0}:root{--bg:#0a0a0c;--bg2:#111116;--bg3:#1d1d26;--bg4:#2a2a38;--accent:#e50914;--accent-hover:#b30710;--text:#ffffff;--muted:#a0a0b0;--border:#262636;--card:#14141f;--sidebar-w:260px;--primary-p:0%;--cloud-p:0%;--archive-p:0%}.light{--bg:#f4f5f7;--bg2:#ffffff;--bg3:#eef0f4;--bg4:#dbdee6;--text:#0a0a0c;--muted:#62627a;--border:#d2d5df;--card:#ffffff}body{font-family:'DM Sans',sans-serif;background:var(--bg);color:var(--text);min-height:100vh;overflow-x:hidden;transition:.2s}.topbar{background:var(--bg2);padding:0 4%;display:flex;align-items:center;height:68px;position:sticky;top:0;z-index:100;gap:15px;box-shadow:0 4px 20px rgba(0,0,0,0.4);border-bottom:1px solid var(--border)}.ham-btn{background:0 0;border:0;cursor:pointer;color:var(--text);display:flex;flex-direction:column;gap:5px;padding:6px}.ham-line{width:22px;height:2px;background:currentColor;transition:.2s}.logo{font-size:18px;font-weight:900;letter-spacing:1px;color:var(--accent);display:flex;align-items:center;gap:8px;text-decoration:none;flex:1}.nf-icon{background:var(--accent);color:#fff;padding:2px 7px;border-radius:3px;font-size:18px;line-height:1}.theme-btn{margin-left:auto;background:0 0;border:1px solid var(--border);border-radius:4px;padding:6px 12px;font-size:12px;font-weight:700;color:var(--text);cursor:pointer}.theme-btn:hover{background:var(--bg3)}.sidebar-overlay{position:fixed;inset:0;background:rgba(0,0,0,.7);z-index:150;opacity:0;pointer-events:none;transition:.2s}.sidebar-overlay.open{opacity:1;pointer-events:all}.sidebar{position:fixed;top:0;left:0;height:100%;width:var(--sidebar-w);background:var(--bg2);border-right:1px solid var(--border);z-index:160;display:flex;flex-direction:column;transform:translateX(-100%);transition:.3s}.sidebar.open{transform:translateX(0)}.sb-header{padding:20px;border-bottom:1px solid var(--border);display:flex;justify-content:space-between}.sb-logo{font-size:14px;font-weight:900;color:var(--accent);display:flex;align-items:center;gap:8px}.sb-close{background:0 0;border:0;color:var(--muted);font-size:22px;cursor:pointer}.sb-nav{padding:15px 10px;flex:1}.sb-section{font-size:11px;font-weight:700;color:var(--muted);padding:8px 12px}.sb-link{display:flex;padding:12px 15px;border-radius:4px;text-decoration:none;color:var(--muted);font-size:15px;font-weight:500;margin-bottom:4px}.sb-link.active{background:var(--accent);color:#fff}.sb-footer{padding:15px 10px;border-top:1px solid var(--border)}.sb-logout{display:block;padding:12px;border-radius:4px;text-align:center;text-decoration:none;color:var(--text);font-weight:700;border:1px solid var(--border)}.search-zone{padding:20px 4%;background:var(--bg)}.search-row{display:flex;gap:10px;flex-wrap:wrap}.search-wrap{flex:1;position:relative;min-width:200px}.s-icon{position:absolute;left:15px;top:50%;transform:translateY(-50%);color:var(--muted)}.search-input{width:100%;background:var(--bg2);border:1px solid var(--border);border-radius:4px;padding:12px 15px 12px 42px;color:var(--text);font-size:15px;outline:0}.search-btn{background:var(--accent);color:#fff;border:0;border-radius:4px;padding:12px 24px;font-weight:700;cursor:pointer}.main{padding:0 4% 40px;max-width:1400px;margin:0 auto}.stats-row{display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:20px;margin-bottom:30px}.scard{background:var(--card);padding:24px;border-radius:8px;position:relative;box-shadow:0 8px 32px rgba(0,0,0,0.2);border:1px solid var(--border);transition:0.3s}.scard:hover{transform:translateY(-2px);box-shadow:0 12px 40px rgba(0,0,0,0.4)}.scard-label{font-size:12px;font-weight:700;color:var(--muted);margin-bottom:10px;text-transform:uppercase;letter-spacing:1px}.scard-val{font-size:36px;font-weight:900;color:var(--text);margin-bottom:8px;font-family:'Courier New',monospace}.scard-sub{font-size:13px;color:var(--muted);display:flex;justify-content:between;align-items:center}.big-stat{background:linear-gradient(135deg, var(--card) 0%, var(--bg2) 100%);padding:40px 20px;border-radius:8px;text-align:center;margin-bottom:30px;border:1px solid var(--border);box-shadow:0 10px 40px rgba(0,0,0,0.3)}.big-stat-val{font-size:72px;font-weight:900;color:var(--accent);margin-bottom:10px;letter-spacing:-1px;font-family:'Courier New',monospace}.big-stat-label{font-size:14px;color:var(--muted);font-weight:700;letter-spacing:3px;text-transform:uppercase}.custom-progress-container{width:100%;height:6px;background:var(--bg4);border-radius:3px;margin:12px 0 6px;overflow:hidden}.custom-progress-bar{height:100%;border-radius:3px;transition:width 1s cubic-bezier(0.4, 0, 0.2, 1)}.custom-progress-bar.primary-fill{background:#3399ff;width:var(--primary-p)}.custom-progress-bar.cloud_fill{background:#ff9933;width:var(--cloud-p)}.custom-progress-bar.archive-fill{background:#9933ff;width:var(--archive-p)}.mode-none .poster-box{display:none}
.empty{text-align:center;padding:80px 20px;color:var(--muted);grid-column:1/-1}.empty-icon{font-size:40px;margin-bottom:15px}.toast{position:fixed;bottom:20px;right:20px;background:var(--accent);color:#fff;padding:12px 20px;border-radius:4px;font-weight:700;z-index:300;transform:translateX(150%);transition:.3s}.toast.show{transform:translateX(0)}.toast.error{background:#000;border:1px solid var(--accent)}.login-bg{background:linear-gradient(rgba(0,0,0,.8) 0,rgba(0,0,0,.4) 50%,rgba(0,0,0,.8) 100%),url('https://assets.nflxext.com/ffe/siteui/vlv3/f841d4c7-10e1-40af-bcae-07a3f8dc141a/f6d7434e-d6de-4185-a6d4-c77a2d08737b/IN-en-20220502-popsignuptwoweeks-perspective_alpha_website_medium.jpg') center/cover;background-attachment:fixed;min-height:100vh;display:flex;flex-direction:column}.light .login-bg{background:linear-gradient(rgba(255,255,255,.85) 0,rgba(255,255,255,.6) 50%,rgba(255,255,255,.9) 100%),url('https://assets.nflxext.com/ffe/siteui/vlv3/f841d4c7-10e1-40af-bcae-07a3f8dc141a/f6d7434e-d6de-4185-a6d4-c77a2d08737b/IN-en-20220502-popsignuptwoweeks-perspective_alpha_website_medium.jpg') center/cover;background-attachment:fixed}.login-wrap{flex:1;display:flex;align-items:center;justify-content:center;padding:20px;min-height:calc(100vh - 68px)}.login-card{background:var(--card);padding:50px;border-radius:12px;width:100%;max-width:450px;box-shadow:0 15px 40px rgba(0,0,0,.3);border:1px solid var(--border)}.login-card h2{font-size:32px;margin-bottom:28px;color:var(--text)}.login-card input{width:100%;background:var(--bg);border:1px solid var(--border);padding:16px;color:var(--text);margin-bottom:16px;border-radius:6px;outline:none}.login-card input:focus{border-color:var(--accent)}.login-card .submit-btn{width:100%;background:var(--accent);color:#fff;border:0;padding:16px;font-weight:700;margin-top:24px;border-radius:6px;cursor:pointer}.err-box{background:#e87c03;color:#fff;padding:10px 20px;border-radius:4px;margin-bottom:16px}.success-box{background:#28a745;color:#fff;padding:10px 20px;border-radius:4px;margin-bottom:16px}.edit-modal{position:fixed;inset:0;background:rgba(0,0,0,.85);z-index:200;display:flex;align-items:center;justify-content:center;opacity:0;pointer-events:none;transition:.2s;overflow-y:auto;padding:20px 10px}.edit-modal.open{opacity:1;pointer-events:all}.em-card{background:var(--card);border:1px solid var(--border);border-radius:12px;padding:25px;width:100%;max-width:480px;box-shadow:0 10px 30px rgba(0,0,0,.5);position:relative;margin:auto}.em-close{position:absolute;top:15px;right:20px;background:0 0;border:0;color:var(--muted);font-size:24px;cursor:pointer;z-index:10}.em-title{font-size:18px;font-weight:700;margin-bottom:20px;display:flex;align-items:center;gap:8px}.em-input{width:100%;background:var(--bg);border:1px solid var(--border);padding:12px;color:var(--text);margin-bottom:15px;border-radius:6px;outline:none;font-size:14px}.em-input:focus{border-color:var(--accent)}.thumb-preview-box{width:100%;aspect-ratio:16/9;background:var(--bg3);border:1px solid var(--border);border-radius:6px;margin-bottom:15px;overflow:hidden;position:relative;display:flex;align-items:center;justify-content:center}.t-prev-img{max-width:100%;max-height:100%;object-fit:contain}.em-upload-btn{display:block;text-align:center;background:var(--bg4);border:1px dashed var(--border);padding:12px;border-radius:6px;cursor:pointer;font-weight:700;font-size:13px;margin-bottom:20px;transition:0.2s}.em-upload-btn:hover{background:var(--bg3);border-color:var(--text)}.em-save-btn{width:100%;background:var(--accent);color:#fff;border:0;padding:14px;font-weight:700;border-radius:6px;cursor:pointer;font-size:15px;transition:0.2s}.em-save-btn:hover{background:var(--accent-hover)}.em-save-btn:disabled{opacity:.5;cursor:not-allowed}.cropper-container-box{width:100%;aspect-ratio:16/9;margin-bottom:15px;border-radius:6px;overflow:hidden;display:none;background:#000}.cropper-view-box{box-outline:none;outline:2px solid var(--accent)!important;outline-color:var(--accent)!important}.cropper-line,.cropper-point{background-color:var(--accent)!important;opacity:0.8}.cropper-bg{background-image:none!important;background-color:#000!important}.cropper-modal{opacity:.8!important;background-color:#000!important}
/* --- Global Admin Edit Buttons --- */
.poster-admin{position:absolute;bottom:0;left:0;right:0;display:flex;gap:6px;padding:7px 8px;opacity:0;transform:translateY(8px);transition:opacity .2s ease,transform .22s ease;pointer-events:none;z-index:4}
.file-card.admin-active .poster-admin{opacity:1;transform:translateY(0);pointer-events:all}
.text-admin-row{display:none;gap:5px;padding:5px 11px 0}
.file-card.admin-active .text-admin-row{display:flex}
.btn-edit,.btn-del{flex:1;padding:6px 0;border-radius:6px;font-size:11px;font-weight:700;cursor:pointer;transition:background .12s,transform .1s;border:none}
.btn-edit{background:rgba(42,42,48,.90);backdrop-filter:blur(10px);color:#fff;border:1px solid rgba(255,255,255,.18)}
.btn-edit:hover{background:rgba(80,80,88,.95)}
.btn-del{background:rgba(160,8,8,.78);backdrop-filter:blur(10px);color:#fff;border:1px solid rgba(229,9,20,.45)}
.btn-del:hover{background:rgba(229,9,20,.92)}

/* ── MASTER UNIVERSAL ASSET CARD & GRID (DRY OPTIMIZED & NEW ANIMATIONS) ── */
.res-grid{display:grid;grid-template-columns:1fr;gap:4px;margin-bottom:24px}
@media(min-width:600px){.res-grid{grid-template-columns:repeat(3,1fr);gap:14px}}
.res-grid.mode-none .poster-box{display:none}

/* ✅ NEW PREMIUM 3D HOVER EFFECT - Global For All Pages */
.file-card{background:var(--card);border-radius:10px;overflow:hidden;border:1px solid var(--border);display:flex;flex-direction:column;transition:all .3s cubic-bezier(.25,.8,.25,1);cursor:pointer;position:relative;box-shadow:0 4px 10px rgba(0,0,0,0.2)}
.file-card:hover{transform:translateY(-6px) scale(1.02);border-color:var(--accent);box-shadow:0 15px 35px rgba(0,0,0,.6),0 0 15px rgba(229,9,20,.3);z-index:2}
.file-card:active{transform:scale(.96);transition:transform .1s}

/* ── STAGGERED CARD ENTRANCE ANIMATION ── */
@keyframes cardEnter{
  0%  {opacity:0;transform:translateY(36px) scale(0.93)}
  55% {opacity:1;transform:translateY(-5px) scale(1.015)}
  75% {transform:translateY(2px) scale(0.998)}
  100%{opacity:1;transform:translateY(0) scale(1)}
}
.card-enter{opacity:0}
.card-enter.card-visible{animation:cardEnter .6s cubic-bezier(.34,1.2,.64,1) forwards}

/* ── Poster box (With Shimmer Effect) ── */
.poster-box{position:relative;padding-top:56.25%;background:linear-gradient(90deg, var(--bg3) 0px, var(--bg4) 50%, var(--bg3) 100%);background-size:200% 100%;animation:shimmer 1.5s infinite linear;overflow:hidden;width:100%}
@keyframes shimmer{0%{background-position:200% 0}100%{background-position:-200% 0}}

/* ✅ ENHANCED POSTER ZOOM REVEAL */
.fc-poster{position:absolute;inset:0;width:100%;height:100%;object-fit:cover;opacity:0;transition:opacity .3s ease,transform .5s cubic-bezier(.25,1,.5,1)}
.fc-poster.loaded{opacity:1}
.file-card:hover .fc-poster{transform:scale(1.08)}

.thumb-error{position:absolute;inset:0;display:flex;align-items:center;justify-content:center;background:#1f1f1f;z-index:2}
.poster-top{position:absolute;top:0;left:0;right:0;display:flex;align-items:center;gap:5px;padding:8px;z-index:3}
.type-chip{background:rgba(0,0,0,.72);backdrop-filter:blur(8px);color:#fff;border-radius:5px;padding:3px 8px;font-size:10px;font-weight:800;letter-spacing:.8px;border:1px solid rgba(255,255,255,.14);line-height:1.4}
.size-chip{background:rgba(0,0,0,.60);backdrop-filter:blur(8px);color:#e0e0e0;border-radius:5px;padding:3px 8px;font-size:10px;font-weight:600;border:1px solid rgba(255,255,255,.08);line-height:1.4}.dur-chip{background:rgba(0,0,0,.72);backdrop-filter:blur(8px);color:#fff;border-radius:5px;padding:3px 8px;font-size:10px;font-weight:700;letter-spacing:.3px;border:1px solid rgba(255,255,255,.14);line-height:1.4;font-variant-numeric:tabular-nums}.dur-chip::before{content:"\\23F1\\00a0";font-size:9px;opacity:.75}.tc-dur{color:var(--muted);font-size:11px;font-weight:600;font-variant-numeric:tabular-nums}.tc-dur::before{content:"\\23F1\\00a0";font-size:10px}.res-chip{background:rgba(0,0,0,.72);backdrop-filter:blur(8px);color:#ffd166;border-radius:5px;padding:3px 8px;font-size:10px;font-weight:800;letter-spacing:.3px;border:1px solid rgba(255,209,102,.35);line-height:1.4}.tc-res{color:#ffd166;font-size:11px;font-weight:800}
.source-pill{margin-left:auto;border-radius:20px;padding:3px 8px;font-size:9px;font-weight:700;letter-spacing:.4px;display:inline-flex;align-items:center;gap:4px;backdrop-filter:blur(8px)}
.source-pill.primary{background:#14532d;color:#4ade80;border:1px solid #22c55e}
.source-pill.cloud{background:#1e3a5f;color:#93c5fd;border:1px solid #60a5fa}
.source-pill.archive{background:#7c2d12;color:#fdba74;border:1px solid #fb923c}
.source-dot{width:5px;height:5px;border-radius:50%;flex-shrink:0}
.primary .source-dot{background:#22c55e;box-shadow:0 0 4px #22c55e}
.cloud .source-dot{background:#60a5fa;box-shadow:0 0 4px #60a5fa}
.archive .source-dot{background:#fb923c;box-shadow:0 0 4px #fb923c}

.fc-body{padding:10px 11px 12px;flex:1;display:flex;flex-direction:column;justify-content:center}
.fc-name{color:var(--text);font-size:12.5px;font-weight:600;line-height:1.45;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden;cursor:pointer;transition:color .18s;text-decoration:none}
.fc-name:hover{color:var(--accent);text-decoration:underline;text-decoration-color:var(--accent);text-underline-offset:2px}

.fc-text-info{display:flex;align-items:center;gap:6px;padding:10px 11px 0;flex-wrap:wrap;margin-bottom:4px}
.tc-type{background:var(--bg4);color:var(--muted);border-radius:5px;padding:2px 7px;font-size:9px;font-weight:800;letter-spacing:.8px;border:1px solid var(--border)}
.tc-size{color:var(--muted);font-size:11px}

.spin-wrap{display:flex;flex-direction:column;align-items:center;gap:16px;padding:60px 20px;color:var(--muted);grid-column:1/-1}
.spinner{width:36px;height:36px;border:3px solid var(--border);border-top-color:var(--accent);border-radius:50%;animation:spin .8s linear infinite}
@keyframes spin{to{transform:rotate(360deg)}}

/* ✅ GLOBAL PREMIUM PAGINATION (For Dashboard & Other Pages) */
.pagination{display:none;align-items:center;justify-content:center;gap:12px;margin-top:8px;padding-bottom:20px}
.pg-btn{background:var(--bg4);color:var(--text);border:1px solid var(--border);border-radius:6px;padding:8px 18px;font-size:12px;font-weight:700;cursor:pointer;transition:background .15s,transform .15s,box-shadow .15s}
.pg-btn:disabled{background:var(--bg3);color:var(--muted);cursor:not-allowed;opacity:.45}
.pg-btn:not(:disabled):hover{background:var(--accent);color:#fff;border-color:var(--accent);box-shadow:0 4px 16px rgba(229,9,20,.35)}
.pg-btn:not(:disabled):active{transform:scale(.93);box-shadow:none}
.pg-info{color:var(--muted);font-size:12px;font-weight:600}

/* ── ACTOR DIRECTORY CARD (DRY GLOBAL) ── */
.act-card{background:var(--card);border:1px solid var(--border);border-radius:10px;overflow:hidden;transition:transform .22s cubic-bezier(.4,0,.2,1),border-color .22s,box-shadow .22s;cursor:pointer;box-shadow:0 4px 10px rgba(0,0,0,0.2)}
.act-card:hover{transform:translateY(-6px);border-color:rgba(229,9,20,.6);box-shadow:0 8px 22px rgba(229,9,20,.25)}
.act-card:active{transform:scale(0.95);transition:transform .1s}

/* act-card uses .card-enter (shared) */
.act-poster{position:absolute;inset:0;width:100%;height:100%;object-fit:cover;transition:transform .4s cubic-bezier(.4,0,.2,1)}
.act-card:hover .act-poster{transform:scale(1.1)}
.act-text-card:active{transform:scale(0.97);transition:transform .1s}
"""

JS = """
(function(){if(localStorage.getItem('theme')==='light')document.documentElement.classList.add('light')})();
function toggleThemeFixed(){var l=document.documentElement.classList.toggle('light');localStorage.setItem('theme',l?'light':'dark');}
function openSidebar(){document.getElementById('sidebar').classList.add('open');document.getElementById('sbOverlay').classList.add('open');document.getElementById('hamBtn').classList.add('open');}
function closeSidebar(){document.getElementById('sidebar').classList.remove('open');document.getElementById('sbOverlay').classList.remove('open');document.getElementById('hamBtn').classList.remove('open');}
var curQ='',curOff=0,nextOff='',curCol='all',curPage=1;
var pMode=localStorage.getItem('posterMode')||'__DEFAULT_MEDIA_MODE__';
var LIMIT_VAL = __LIMIT_PLACEHOLDER__;

var activeFid = '', activeCol = '', cropperInstance = null;

function handleThumbError(fileId) {
    var img = document.getElementById('img-poster-' + fileId);
    if (img) { img.style.opacity = '0'; }
    var errBox = document.getElementById('thumb-err-' + fileId);
    if (!errBox) {
        var box = document.getElementById('poster-box-' + fileId);
        if (box) {
            var div = document.createElement('div');
            div.id = 'thumb-err-' + fileId;
            div.className = 'thumb-error';
            div.innerHTML = '<div style="position:absolute; inset:0; display:flex; flex-direction:column; align-items:center; justify-content:center; background:#1f1f1f; padding:10px;"><span style="font-size:11px; color:var(--muted); text-align:center;">थंबनेल लोड नहीं हुआ</span></div>';
            box.appendChild(div);
        }
    }
}

async function reloadThumb(fileId) {
    var timestamp = new Date().getTime();
    var img = document.getElementById('img-poster-' + fileId);
    if (img) {
        img.src = '/api/thumb?file_id=' + fileId + '&retry=true&t=' + timestamp;
        img.classList.remove('loaded');
    }
    var errBox = document.getElementById('thumb-err-' + fileId);
    if (errBox) { errBox.remove(); }
}

var _tt;
function showToast(m,t){
    t=t||'success';
    var x=document.getElementById('toast');
    if(!x){x=document.createElement('div');x.id='toast';x.className='toast';document.body.appendChild(x);}
    x.textContent=m;x.className='toast '+t+' show';
    clearTimeout(_tt);
    _tt=setTimeout(function(){x.classList.remove('show');},3000);
}

function toggleAdminBtns(card,e){
    e.stopPropagation();
    var isActive=card.classList.contains('admin-active');
    document.querySelectorAll('.file-card.admin-active').forEach(function(c){c.classList.remove('admin-active');});
    if(!isActive) card.classList.add('admin-active');
}

document.addEventListener('click',function(){
    document.querySelectorAll('.file-card.admin-active').forEach(function(c){c.classList.remove('admin-active');});
});

async function deleteFile(fid,col){
    if(!confirm('Are you sure you want to delete this file?'))return;
    try{
        var r=await fetch('/api/delete',{method:'POST',body:JSON.stringify({file_id:fid,collection:col}),headers:{'Content-Type':'application/json'}});
        var res=await r.json();
        if(res.success){ showToast('✅ File deleted successfully!'); refreshGridAfterEdit(); }
        else{ showToast(res.error||'Delete failed!','error'); }
    }catch(e){showToast('Delete failed','error');}
}

function editFile(fid, col, encName, encCaption){
    var currentName = decodeURIComponent(encName);
    var currentCaption = (encCaption && encCaption !== 'undefined') ? decodeURIComponent(encCaption) : '';
    activeFid = fid; activeCol = col;
    if(cropperInstance){cropperInstance.destroy();cropperInstance=null;}
    document.getElementById('emName').value=currentName;
    document.getElementById('emFile').value='';
    document.getElementById('cropContainer').style.display='none';
    if(document.getElementById('emMoveCol')) document.getElementById('emMoveCol').value = col;
    if(document.getElementById('emAddCaption')) document.getElementById('emAddCaption').value = currentCaption;
    
    var prevBox=document.getElementById('emPreviewBox');
    prevBox.style.display='flex';
    prevBox.innerHTML='<img src="/api/thumb?file_id='+fid+'&col='+activeCol+'" class="t-prev-img" onerror="this.src=\\'https://placehold.co/600x338/181818/FFF?text=No+Thumbnail\\';">';
    document.getElementById('editCombinedModal').classList.add('open');
}

function closeCombinedModal(){
    document.getElementById('editCombinedModal').classList.remove('open');
    if(cropperInstance){cropperInstance.destroy();cropperInstance=null;}
}

function handleLocalPreview(input){
    if(input.files&&input.files[0]){
        var reader=new FileReader();
        reader.onload=function(e){
            if(cropperInstance) cropperInstance.destroy();
            document.getElementById('emPreviewBox').style.display='none';
            var cropWrap=document.getElementById('cropContainer');
            cropWrap.style.display='block';
            cropWrap.innerHTML='<img id="cropImage" src="'+e.target.result+'" style="max-width:100%;">';
            var img=document.getElementById('cropImage');
            cropperInstance=new Cropper(img,{aspectRatio:16/9,viewMode:1,background:false,zoomable:true,movable:true});
        };
        reader.readAsDataURL(input.files[0]);
    }
}

async function saveAllChanges(){
    var newName=document.getElementById('emName').value.trim();
    var addCaption=document.getElementById('emAddCaption') ? document.getElementById('emAddCaption').value.trim() : '';
    var moveCol=document.getElementById('emMoveCol') ? document.getElementById('emMoveCol').value : activeCol;
    if(!newName){showToast('File name cannot be empty!','error');return;}
    
    var btn=document.getElementById('emSaveBtn');
    btn.disabled=true; btn.innerText='Processing...';
    try{
        var thumbUpdated = false;
        
        if(cropperInstance){
            showToast('✂️ Cropping & Uploading...');
            var canvas=cropperInstance.getCroppedCanvas({width:1280,height:720,imageSmoothingEnabled:true,imageSmoothingQuality:'high'});
            var blob=await new Promise(r=>canvas.toBlob(r,'image/jpeg',0.9));
            if(blob){
                var fd=new FormData(); fd.append('file_id',activeFid); fd.append('collection',activeCol); fd.append('image',blob,'cropped.jpg');
                var upRes=await fetch('/api/upload_thumb',{method:'POST',body:fd});
                var upData=await upRes.json();
                if(!upData.success){showToast('Upload failed!','error'); btn.disabled=false; btn.innerText='Save Changes'; return;}
                thumbUpdated = true;
            }
        }
        var payload = { file_id: activeFid, collection: activeCol, new_name: newName, add_caption: addCaption, target_collection: moveCol };
        var r=await fetch('/api/edit_name',{method:'POST',body:JSON.stringify(payload),headers:{'Content-Type':'application/json'}});
        var res=await r.json();
        
        if(res.success||cropperInstance){
            showToast('✨ File updated successfully!');
            closeCombinedModal();
            
            if (activeCol !== moveCol) {
                refreshGridAfterEdit();
                return;
            }
            
            var nameElement = document.getElementById('name-title-' + activeFid);
            if (nameElement) nameElement.innerText = newName;
            
            if (thumbUpdated) reloadThumb(activeFid);
            
        } else showToast(res.error||'Update failed!','error');
    }catch(e){showToast('Network Error','error');}
    finally{btn.disabled=false; btn.innerText='Save Changes';}
}

function refreshGridAfterEdit() {
    if (typeof doSearch === 'function') doSearch(curOff);
    else if (typeof triggerActorSearchAjax === 'function') triggerActorSearchAjax();
    else window.location.reload();
}
function staggerCards(container){
    var cards=container.querySelectorAll('.card-enter');
    if(!cards.length) return;
    var seen=0;
    var obs=new IntersectionObserver(function(entries){
        entries.forEach(function(entry){
            if(!entry.isIntersecting) return;
            var c=entry.target;
            var delay=Math.min(seen,10)*0.08; seen++;
            c.style.animationDelay=delay+'s';
            c.classList.add('card-visible');
            var totalDur=(0.6+delay)*1000;
            setTimeout(function(){ c.classList.remove('card-enter','card-visible'); c.style.animationDelay=''; },totalDur);
            obs.unobserve(c);
        });
    },{threshold:0.08});
    cards.forEach(function(c){ obs.observe(c); });
}
""".replace("__LIMIT_PLACEHOLDER__", str(MAX_WEB_RESULTS)).replace("__DEFAULT_MEDIA_MODE__", DEFAULT_MEDIA_MODE)

def _h(html): return web.Response(text=html, content_type='text/html', charset='utf-8')

async def get_auth(req):
    s_user = req.cookies.get('user_session')
    session = temp.USER_SESSIONS.get(s_user) if s_user else None
    if session and session['expiry'] > time.time():
        tg_id = session['tg_id']
        if tg_id in ADMINS: return 'admin', tg_id
        return 'user', tg_id
    return None, None

# ✅ FIX: यह एक ही जगह से premium/plan चेक करने वाला shared helper है।
# पहले सिर्फ dashboard_routes.py अपने अंदर यह चेक करता था, actors/posts पेज नहीं करते थे
# जिससे expired user login करके /actors और /posts freely खोल सकता था (sync issue)।
# अब सभी route files (dashboard, actors, posts) इसी एक function को call करेंगे,
# ताकि logic कहीं भी duplicate न हो और तीनों जगह एक जैसा behave करे।
async def require_active_plan(role, tg_id):
    """Admin हमेशा allowed. 'user' role के लिए plan.premium चेक होता है।"""
    if role != 'user':
        return True
    mp = await user_db.get_plan(tg_id)
    return bool(mp.get("premium"))

# ✅ DRY: पहले admin/user के लिए दो अलग 1-लाइनर nav_links f-strings थीं जिनमें
# चार लिंक हुबहू दोहराए गए थे (सिर्फ़ "Database Stats" admin-only था) — एक लिंक का label/
# href बदलना हो तो दोनों लाइनें edit करनी पड़ती थीं। अब एक ही menu list से बनता है।
NAV_MENU = (
    ("dash",   "/dashboard", "Home"),
    ("posts",  "/posts",     "📝 Posts"),
    ("actors", "/actors",    "🎭 Actors"),
    ("stats",  "/stats",     "Database Stats"),
    ("profile", "/profile",  "Profile Settings"),
)

# ⚡ FAST: head का static हिस्सा (fonts + ~25KB CSS + JS) module-load पर एक ही बार
# बन जाता है। पहले build_page() हर request पर पूरा CSS/JS दोबारा f-string में
# इंटरपोलेट करके नई string बनाता था — यानी हर page-view पर ~25KB की बेकार
# allocation + copy। अब सिर्फ़ title/body जुड़ते हैं।
_HEAD_PRE = '<!DOCTYPE html><html><head>'
_HEAD_POST = (
    '</title><meta name="viewport" content="width=device-width,initial-scale=1">'
    '<link href="https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;700;900&display=swap" rel="stylesheet">'
    '<link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/cropperjs/1.6.1/cropper.min.css">'
    f'<style>{CSS}</style>'
    '<script src="https://cdnjs.cloudflare.com/ajax/libs/cropperjs/1.6.1/cropper.min.js"></script>'
    f'<script>{JS}</script></head>'
)

# Admin-only edit modal भी constant है — हर request पर दोबारा evaluate करने की ज़रूरत नहीं
_ADMIN_MODALS = """
    <div class="edit-modal" id="editCombinedModal" onclick="if(event.target===this)closeCombinedModal()">
        <div class="em-card">
            <button class="em-close" onclick="closeCombinedModal()">&#10005;</button>
            <div class="em-title">✏️ Edit Title Metadata</div>

            <div class="scard-label">File Name</div>
            <input type="text" id="emName" class="em-input">

            <div class="scard-label" style="margin-top:5px;">➕ Add Search Tags to Caption (Optional)</div>
            <input type="text" id="emAddCaption" class="em-input" placeholder="e.g. Ajay Devgan, 1080p, Comedy...">

            <div class="scard-label">📂 Move File to Collection</div>
            <select id="emMoveCol" class="em-input" style="font-weight:600; cursor:pointer;">
                <option value="primary">🟢 Primary</option>
                <option value="cloud">🔵 Cloud</option>
                <option value="archive">🟠 Archive</option>
            </select>

            <div class="scard-label" style="margin-top:5px;">Poster Thumbnail (YouTube Studio Mode)</div>
            <div class="thumb-preview-box" id="emPreviewBox"></div>
            <div class="cropper-container-box" id="cropContainer"></div>

            <label class="em-upload-btn">
                📂 Choose New Image / Poster
                <input type="file" id="emFile" accept="image/*" style="display:none;" onchange="handleLocalPreview(this)">
            </label>

            <button class="em-save-btn" id="emSaveBtn" onclick="saveAllChanges()">Save Changes</button>
        </div>
    </div>
    """

_NAV_SHELL = ('<div class="sidebar-overlay" id="sbOverlay" onclick="closeSidebar()"></div>'
    '<div class="sidebar" id="sidebar"><div class="sb-header"><div class="sb-logo">'
    '<span class="nf-icon">F</span> FAST FINDER</div>'
    '<button class="sb-close" onclick="closeSidebar()">&#10005;</button></div>'
    '<nav class="sb-nav"><div class="sb-section">Menu</div>{links}</nav>'
    '<div class="sb-footer"><a href="/logout" class="sb-logout">Sign Out</a></div></div>'
    '<div class="topbar"><button class="ham-btn" id="hamBtn" onclick="openSidebar()">'
    '<span class="ham-line"></span><span class="ham-line"></span><span class="ham-line"></span></button>'
    '<a class="logo" href="/dashboard"><span class="nf-icon">F</span> FAST FINDER</a>'
    '<div class="topbar-right"><button class="theme-btn" onclick="toggleThemeFixed()">Theme</button></div></div>')

_NAV_GUEST = ('<div class="topbar" style="position:absolute; width:100%; box-shadow:none; background:transparent;">'
    '<a class="logo" href="/" style="font-size:24px"><span class="nf-icon" style="font-size:24px">F</span> FAST FINDER</a>'
    '<div class="topbar-right"><button class="theme-btn" onclick="toggleThemeFixed()">Theme</button></div></div>')


def build_page(title, body, cls="", active_tab="", role=None):
    if role:
        links = "".join(
            f'<a href="{href}" class="sb-link {"active" if active_tab == tab else ""}">{label}</a>'
            for tab, href, label in NAV_MENU
            if role == "admin" or tab != "stats"   # Database Stats admin-only है
        )
        nav = _NAV_SHELL.format(links=links)
    else:
        nav = _NAV_GUEST

    modals = _ADMIN_MODALS if role == 'admin' else ""

    return _h(_HEAD_PRE + '<title>' + title + _HEAD_POST
              + f'<body class="{cls}">' + nav + body + modals + '</body></html>')


def form_wrapper(title, content, err="", msg=""):
    e = f'<div class="err-box">{err}</div>' if err else ""
    m = f'<div class="success-box">{msg}</div>' if msg else ""
    return f'<div class="login-wrap"><div class="login-card"><h2>{title}</h2>{e}{m}{content}</div></div>'
