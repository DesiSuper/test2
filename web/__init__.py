# Credit - adarsh-goel

from aiohttp import web
from web.stream_routes import routes
from web.admin_routes import register_admin_components
from web.search_api import search_routes

# =========================================
# 🚀 WEB APP INITIALIZATION
# =========================================

# client_max_size=100MB set kiya hai taaki 'Payload Too Large' error na aaye
web_app = web.Application(client_max_size=100 * 1024 * 1024)

# Routes load karna
web_app.add_routes(routes)

# सर्च एपीआई राउट्स लोड करें
web_app.add_routes(search_routes)

# ⬇️ यहाँ मास्टर कंपोनेंट पाइपलाइन को लोड करके सारे पेजों को एक साथ सिंक कर दिया गया ⬇️
register_admin_components(web_app)
