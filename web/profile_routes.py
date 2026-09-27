from aiohttp import web
from web.web_assets import build_page, get_auth
from database.users_chats_db import db as user_db, web_db

profile_routes = web.RouteTableDef()

_PROFILE_CSS = """<style>
.prof-status{background:var(--bg3);padding:15px;border-radius:6px;margin-bottom:22px;transition:background .2s}
.prof-tab-bar{display:flex;gap:4px;background:var(--bg3);border:1px solid var(--border);border-radius:8px;padding:4px;margin-bottom:20px;transition:background .2s,border-color .2s}
.prof-tab{flex:1;padding:8px 0;border-radius:5px;border:none;cursor:pointer;font-size:13px;font-weight:600;font-family:inherit;background:transparent;color:var(--muted);transition:all .15s}
.prof-tab.active{background:var(--bg4);color:var(--text)}
.prof-panel{display:none}.prof-panel.active{display:block}
.prof-field{margin-bottom:18px}
.prof-input{width:100%;background:var(--bg3);border:1px solid var(--border);border-radius:6px;padding:10px 14px;font-size:14px;color:var(--text);font-family:inherit;outline:none;box-sizing:border-box;transition:border-color .15s,background .2s}
.prof-input:focus{border-color:var(--accent)} .prof-input::placeholder{color:var(--muted)} .prof-input:disabled{opacity:.55;cursor:default}
.prof-input.pass-input{padding-right:44px} .pass-wrap{position:relative}
.pass-toggle{position:absolute;right:12px;top:50%;transform:translateY(-50%);background:none;border:none;cursor:pointer;color:var(--muted);padding:0;display:flex;align-items:center}
.str-row{display:flex;gap:4px;margin-top:8px} .str-bar{flex:1;height:3px;border-radius:2px;background:var(--bg4);transition:background .2s}
.info-row{display:flex;align-items:center;gap:12px;background:var(--bg3);border:1px solid var(--border);border-radius:6px;padding:12px 14px;transition:background .2s,border-color .2s}
.info-row-lbl{font-size:11px;color:var(--muted);margin-bottom:2px} .info-row-val{font-size:13px;font-weight:600;color:var(--text)}
.prof-divider{border:none;border-top:1px solid var(--border);margin:18px 0} .prof-save-row{display:flex;justify-content:flex-end;margin-top:22px}
</style>"""

_SVG_EYE_HIDE = '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94"/><path d="M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19"/><line x1="1" y1="1" x2="23" y2="23"/></svg>'
_SVG_EYE_SHOW = '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/><circle cx="12" cy="12" r="3"/></svg>'

_PROFILE_JS = f"""<script>
(function(){{
  var tabs=document.querySelectorAll('.prof-tab'), panels=document.querySelectorAll('.prof-panel');
  tabs.forEach(function(t){{
    t.addEventListener('click',function(){{
      tabs.forEach(function(x){{x.classList.remove('active')}}); panels.forEach(function(x){{x.classList.remove('active')}});
      t.classList.add('active'); document.getElementById('panel-'+t.dataset.tab).classList.add('active');
    }});
  }});
  var toggleBtn=document.getElementById('passToggle'), passInput=document.getElementById('passInput');
  if(toggleBtn&&passInput){{
    toggleBtn.addEventListener('click',function(){{
      var show=passInput.type==='password'; passInput.type=show?'text':'password';
      toggleBtn.innerHTML=show?'{_SVG_EYE_HIDE}':'{_SVG_EYE_SHOW}';
    }});
  }}
  if(passInput){{
    passInput.addEventListener('input',function(){{
      var l=passInput.value.length, s=l===0?0:l<6?1:l<10?2:l<14?3:4;
      var colors=['var(--bg4)','#ef4444','#f59e0b','#4ade80','#22c55e'], labels=['','Weak','Moderate','Strong','Very Strong'];
      document.querySelectorAll('.str-bar').forEach(function(b,i){{b.style.background=(i<s)?colors[s]:'var(--bg4)';}});
      var lbl=document.getElementById('strLabel');
      if(lbl){{lbl.textContent=labels[s];lbl.style.color=colors[s];lbl.style.display=l?'block':'none';}}
    }});
  }}
}})();
</script>"""


@profile_routes.get('/profile')
async def profile_page(req):
    role, tg_id = await get_auth(req)
    if not role: return web.HTTPFound('/login')

    user = await web_db.col.find_one({"tg_id": tg_id}, {"email": 1})
    email = user.get('email', '') if user else ''
    mp = await user_db.get_plan(tg_id)

    # ✅ BUG FIX (था पहले): role=='user' का मतलब सिर्फ़ 'valid session' है, premium
    # active होना नहीं (get_auth() premium चेक नहीं करता) — इसलिए status text
    # अब असली mp.get('premium') बूलियन के आधार पर तय होता है, hardcoded नहीं।
    # ✅ BUG FIX (था पहले): mp.get('expire', 'Unknown') कभी 'Unknown' नहीं देता था
    # क्योंकि 'expire' key हमेशा मौजूद रहती है (df_prm डिफॉल्ट में None के साथ) —
    # non-premium user को literal "None" शब्द दिखता था। अब `or` से सही fallback है।
    if role == 'admin':
        st_txt, exp_txt, st_clr = "👑 Admin (Lifetime Access)", "Never (Lifetime)", "#e50914"
    elif mp.get('premium'):
        st_txt, exp_txt, st_clr = "💎 Premium User", (mp.get('expire') or 'Unknown'), "#3399ff"
    else:
        st_txt, exp_txt, st_clr = "🆓 Free Account (No Active Plan)", "Use /plan in Bot PM to activate", "#808080"
    
    import html
    err_h = f'<div class="err-box">{html.escape(req.query.get("err", ""))}</div>' if req.query.get('err') else ''
    msg_h = f'<div class="success-box">{html.escape(req.query.get("msg", ""))}</div>' if req.query.get('msg') else ''

    b = f'''{_PROFILE_CSS}<div class="main" style="padding-top:40px; max-width:700px;"><div class="scard">{err_h}{msg_h}<h2 style="margin-bottom:24px;">Account Settings</h2>
    <div class="prof-status" style="border-left:4px solid {st_clr};"><div style="font-size:12px;color:var(--muted);margin-bottom:5px;">Account Status</div><div style="font-size:18px;font-weight:700;color:{st_clr};margin-bottom:8px;">{st_txt}</div><div style="font-size:12px;color:var(--muted);margin-bottom:2px;">Subscription expires:</div><div style="font-size:15px;font-weight:500;">{exp_txt}</div></div>
    <div class="prof-tab-bar"><button class="prof-tab active" data-tab="account">Account Info</button><button class="prof-tab" data-tab="security">Security</button></div>
    <form action="/api/update_profile" method="post">
      <div class="prof-panel active" id="panel-account">
        <div class="prof-field"><div class="scard-label">Telegram ID (Non-changeable)</div><input class="prof-input" type="text" value="{tg_id}" disabled></div>
        <div class="prof-field"><div class="scard-label">Current Email</div><input class="prof-input" type="text" value="{email}" disabled></div>
        <div class="prof-field"><div class="scard-label">New Email Address *</div><input class="prof-input" type="email" name="new_email" value="{email}" placeholder="Enter new email..." required></div>
        <hr class="prof-divider">
        <div class="info-row"><svg width="18" height="18" viewBox="0 0 24 24" fill="#3399ff"><path d="M11.944 0A12 12 0 0 0 0 12a12 12 0 0 0 12 12 12 12 0 0 0 12-12A12 12 0 0 0 12 0a12 12 0 0 0-.056 0zm4.962 7.224c.1-.002.321.023.465.14a.506.506 0 0 1 .171.325c.016.093.036.306.02.472-.18 1.898-.962 6.502-1.36 8.627-.168.9-.499 1.201-.82 1.23-.696.065-1.225-.46-1.9-.902-1.056-.693-1.653-1.124-2.678-1.8-1.185-.78-.417-1.21.258-1.91.177-.184 3.247-2.977 3.307-3.23.007-.032.014-.15-.056-.212s-.174-.041-.249-.024c-.106.024-1.793 1.14-5.061 3.345-.48.33-.913.49-1.302.48-.428-.008-1.252-.241-1.865-.44-.752-.245-1.349-.374-1.297-.789.027-.216.325-.437.893-.663 3.498-1.524 5.83-2.529 6.998-3.014 3.332-1.386 4.025-1.627 4.476-1.635z"/></svg><div><div class="info-row-lbl">Linked Telegram Account</div><div class="info-row-val">ID: {tg_id}</div></div></div>
      </div>
      <div class="prof-panel" id="panel-security">
        <div class="prof-field"><div class="scard-label">New Password <span style="color:var(--muted);font-weight:400;text-transform:none;letter-spacing:0;font-size:11px;">(leave blank to keep current)</span></div>
          <div class="pass-wrap"><input class="prof-input pass-input" type="password" id="passInput" name="new_pass" placeholder="Enter new password..."><button type="button" class="pass-toggle" id="passToggle">{_SVG_EYE_SHOW}</button></div>
          <div class="str-row"><div class="str-bar"></div><div class="str-bar"></div><div class="str-bar"></div><div class="str-bar"></div></div><div id="strLabel" style="font-size:11px;margin-top:5px;display:none;"></div></div>
        <div class="info-row"><svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="var(--muted)" stroke-width="2"><rect x="3" y="11" width="18" height="11" rx="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/></svg><div><div class="info-row-lbl">Password protection</div><div class="info-row-val">Active</div></div></div>
      </div>
      <div class="prof-save-row"><button class="search-btn" type="submit" style="display:inline-flex;align-items:center;gap:8px;padding:11px 24px;"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><path d="M19 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11l5 5v11a2 2 0 0 1-2 2z"/><polyline points="17 21 17 13 7 13 7 21"/><polyline points="7 3 7 8 15 8"/></svg>Save Changes</button></div>
    </form></div></div>{_PROFILE_JS}'''
    return build_page("Profile - Fast Finder", b, "", "profile", role)


@profile_routes.post('/api/update_profile')
async def api_update_profile(req):
    role, tg_id = await get_auth(req)
    if not role: return web.HTTPFound('/login')

    d = await req.post()
    new_email = d.get('new_email', '').strip()
    new_pass = d.get('new_pass', '').strip()

    if not new_email: return web.HTTPFound('/profile?err=Email cannot be empty!')
    if await web_db.col.find_one({"email": new_email, "tg_id": {"$ne": tg_id}}, {"_id": 1}):
        return web.HTTPFound('/profile?err=This email is already in use by another account!')

    try:
        await web_db.update_profile(tg_id, new_email, new_pass)
        return web.HTTPFound('/profile?msg=Profile updated successfully!')
    except Exception as e:
        return web.HTTPFound(f'/profile?err=Update failed: {str(e)}')
