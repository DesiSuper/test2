import math
import io
import logging
from hydrogram import Client, utils, raw
from hydrogram.types import Message
from hydrogram.session import Session, Auth
from hydrogram.errors import AuthBytesInvalid
from hydrogram.file_id import FileId, FileType, ThumbnailSource
from utils import temp

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────
# ✅ FIX: async हटाया — ये pure math functions हैं,
#         await करने की कोई ज़रूरत नहीं थी
# ─────────────────────────────────────────────────────────
def chunk_size(length):
    return 2 ** max(min(math.ceil(math.log2(length / 1024)), 10), 2) * 1024

def offset_fix(offset, chunksize):
    return offset - (offset % chunksize)


class TGCustomYield:
    def __init__(self):
        self.main_bot = temp.BOT

    @staticmethod
    async def generate_file_properties(msg: Message) -> FileId:
        return FileId.decode(getattr(msg, msg.media.value).file_id)

    # ─────────────────────────────────────────────────────────
    # ✅ FIX: msg की जगह FileId (d) accept करता है
    #         ताकि caller में double decode न हो
    # ─────────────────────────────────────────────────────────
    async def generate_media_session(self, c: Client, d: FileId) -> Session:
        ms = c.media_sessions.get(d.dc_id)

        if not ms:
            test_mode = await c.storage.test_mode()
            if d.dc_id != await c.storage.dc_id():
                ms = Session(
                    c, d.dc_id,
                    await Auth(c, d.dc_id, test_mode).create(),
                    test_mode, is_media=True
                )
                await ms.start()
                for _ in range(3):
                    try:
                        ex = await c.invoke(raw.functions.auth.ExportAuthorization(dc_id=d.dc_id))
                        await ms.send(raw.functions.auth.ImportAuthorization(id=ex.id, bytes=ex.bytes))
                        break
                    except AuthBytesInvalid:
                        continue
                else:
                    await ms.stop()
                    raise AuthBytesInvalid
            else:
                ms = Session(c, d.dc_id, await c.storage.auth_key(), test_mode, is_media=True)
                await ms.start()
            c.media_sessions[d.dc_id] = ms

        return ms

    @staticmethod
    async def get_location(f: FileId):
        if f.file_type == FileType.PHOTO:
            return raw.types.InputPhotoFileLocation(
                id=f.media_id, access_hash=f.access_hash,
                file_reference=f.file_reference, thumb_size=f.thumbnail_size
            )
        return raw.types.InputDocumentFileLocation(
            id=f.media_id, access_hash=f.access_hash,
            file_reference=f.file_reference, thumb_size=f.thumbnail_size
        )

    # ─────────────────────────────────────────────────────────
    # 🍿 STREAMING ENGINE — 4GB तक smooth, zero RAM spike
    # ─────────────────────────────────────────────────────────
    async def yield_file(
        self, msg: Message,
        offset: int, first_cut: int, last_cut: int,
        parts: int, chunk_size: int
    ):
        # ✅ FIX: एक बार decode, दोनों जगह use
        file_props = await self.generate_file_properties(msg)
        ms  = await self.generate_media_session(self.main_bot, file_props)
        loc = await self.get_location(file_props)

        try:
            for i in range(1, parts + 1):
                r = await ms.send(
                    raw.functions.upload.GetFile(location=loc, offset=offset, limit=chunk_size)
                )
                if not isinstance(r, raw.types.upload.File) or not r.bytes:
                    break

                chunk = r.bytes  # already bytes — safe to yield directly

                # ✅ FIX: buffer_pool + memoryview हटाया
                #         bytes already immutable copy हैं, overwrite का खतरा नहीं
                if parts == 1:
                    yield chunk[first_cut:last_cut]
                elif i == 1:
                    yield chunk[first_cut:]
                elif i == parts:
                    yield chunk[:last_cut]
                else:
                    yield chunk

                offset += len(chunk)

                # ✅ FIX: gc.collect() loop से हटाया
                #         Python GC खुद handle करता है streaming में
                #         manually call करने से हर 20 chunks पर latency spike आती थी

        except Exception as e:
            logger.error(f"Streaming error at offset {offset}: {e}")

