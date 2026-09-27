from aiohttp import web
from web.login_routes import login_routes
from web.dashboard_routes import dashboard_routes
from web.stats_routes import stats_routes
from web.profile_routes import profile_routes
from web.actor_routes import actor_routes  
from web.post_routes import post_routes  # <-- नया पोस्ट रूट इम्पोर्ट किया (Step 1)

def register_admin_components(app: web.Application):
    """सारे अलग-अलग फाइलों के रूट्स को सिंगल सर्वर इंजन में सिंक करने की मास्टर पाइपलाइन"""
    app.add_routes(login_routes)
    app.add_routes(dashboard_routes)
    app.add_routes(stats_routes)
    app.add_routes(profile_routes)
    app.add_routes(actor_routes)       
    app.add_routes(post_routes)        # <-- पोस्ट रूट्स को सर्वर इंजन में सिंक किया (Step 2)
