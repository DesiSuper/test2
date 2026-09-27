import io
import html as html_lib
from aiohttp import web
from utils import temp
from web.web_assets import fast_json


async def upload_tg_photo(channel_id: int, image_bytes: bytes, filename: str = "image.jpg"):
    """Upload image bytes to a Telegram channel and return the file_id of the largest photo size."""
    with io.BytesIO(image_bytes) as buf:
        buf.name = filename
        msg = await temp.BOT.send_photo(chat_id=channel_id, photo=buf)
    if msg and msg.photo:
        return msg.photo.sizes[-1].file_id if hasattr(msg.photo, "sizes") and msg.photo.sizes else msg.photo.file_id
    return None


async def serve_tg_image(file_id: str, max_age: int = 31536000):
    """Download a Telegram photo by file_id and return an aiohttp Response with cache headers."""
    result = await temp.BOT.download_media(file_id, in_memory=True)
    if not result:
        return web.Response(status=404)
    img_bytes = result.getvalue() if hasattr(result, 'getvalue') else result
    return web.Response(
        body=img_bytes,
        content_type="image/jpeg",
        headers={"Cache-Control": f"public, max-age={max_age}"}
    )


def sanitize(text: str) -> str:
    """HTML-escape user input to prevent XSS."""
    return html_lib.escape(text) if text else ""


def json_ok(data: dict = None):
    return web.json_response(data or {"success": True}, dumps=fast_json)


def json_err(msg: str, status: int = 400):
    return web.json_response({"error": msg}, status=status, dumps=fast_json)
