import logging
import re
import base64
import asyncio
import time
from struct import pack
from bson.objectid import ObjectId
import motor.motor_asyncio
from hydrogram.file_id import FileId
from hydrogram.errors import FloodWait
from info import DATABASE_URL, DATABASE_NAME, USE_CAPTION_FILTER, DELETE_CHANNEL
from utils import temp

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────
# ⚙️ MOTOR CONNECTION — Memory-Leak & RAM Guard Optimized
# ─────────────────────────────────────────────────────────
client = motor.motor_asyncio.AsyncIOMotorClient(
    DATABASE_URL,
    maxPoolSize=15,             
    minPoolSize=0,              
    maxIdleTimeMS=30000,        
    serverSelectionTimeoutMS=5000,
    connectTimeoutMS=10000,
    socketTimeoutMS=20000,
    retryWrites=True,
    retryReads=True,
)
db = client[DATABASE_NAME]

primary = db["Primary"]
cloud   = db["Cloud"]
archive = db["Archive"]
actors  = db["Actors"]  # 🎭 एक्टर प्रोफाइल के लिए डेटाबेस कलेक्शन
posts   = db["Posts"]   # 📝 नया पोस्ट्स (CMS) कलेक्शन

COLLECTIONS = {
    "primary": primary,
    "cloud":   cloud,
    "archive": archive,
    "actors":  actors,
}

# ✅ DRY: COLLECTIONS में "actors" भी है, पर उसका schema फाइलों जैसा (file_ref /
# file_name / thumb_url) नहीं है। इसलिए ensure_indexes(), delete_files() और
# warmup.py — तीनों में अलग-अलग `if name == "actors": continue` लिखा गया था
# (warmup.py में दो बार)। एक जगह छूट जाने पर actor के ObjectId को Telegram
# file_id समझकर भेजने की कोशिश होती थी। अब सिर्फ़ file-schema वाले collections
# का यह subset इस्तेमाल होता है, exclusion की कोई कॉपी नहीं बची।
FILE_COLLECTIONS = {k: v for k, v in COLLECTIONS.items() if k != "actors"}

# ⚡ GLOBAL STATUS EXPENSIVE COUNT CACHE
_stats_cache = None
_stats_cache_time = 0
STATS_CACHE_TTL = 60  

# ─────────────────────────────────────────────────────────
# ⚡ INDEXES — Dynamic Configuration
# ─────────────────────────────────────────────────────────
async def ensure_indexes():
    # 1. File-collection Indexes (actors का schema अलग है, उसके indexes नीचे बने हैं)
    for name, col in FILE_COLLECTIONS.items():
        try:
            if USE_CAPTION_FILTER:
                await col.create_index([("file_name", "text"), ("caption", "text")], name=f"{name}_text")
            else:
                await col.create_index([("file_name", "text")], name=f"{name}_text")
            
            await col.create_index("file_name", name=f"{name}_filename_idx")
            await col.create_index([("added_on", -1)], name=f"{name}_added_on_idx")
            logger.info(f"✅ Fast Search & Non-Bloated Indexes OK: {name}")
        except Exception as e:
            if "already exists" in str(e) or "IndexKeySpecsConflict" in str(e): pass
            else: logger.warning(f"Index warning [{name}]: {e}")

    # 2. Actors Specific Indexes
    try:
        await actors.create_index([("name", "text")], name="actors_name_text")
        logger.info("✅ Actor Profile System Indexes OK")
    except Exception as e:
        if "already exists" not in str(e) and "IndexKeySpecsConflict" not in str(e):
            logger.warning(f"Actor Index warning: {e}")

    # 3. Posts Specific Indexes (NEW)
    try:
        await posts.create_index([("title", "text"), ("tags", "text")], name="posts_search_idx")
        logger.info("✅ Posts CMS Search Indexes OK")
    except Exception as e:
        if "already exists" not in str(e) and "IndexKeySpecsConflict" not in str(e):
            logger.warning(f"Posts Index warning: {e}")

# ─────────────────────────────────────────────────────────
# 📊 DB STATS
# ─────────────────────────────────────────────────────────
async def db_count_documents():
    global _stats_cache, _stats_cache_time
    now = time.time()
    if _stats_cache and (now - _stats_cache_time < STATS_CACHE_TTL):
        return _stats_cache

    try:
        p_task = primary.estimated_document_count()
        c_task = cloud.estimated_document_count()
        a_task = archive.estimated_document_count()
        
        thumb_query = {"thumb_url": {"$exists": True, "$type": "string", "$ne": "NO_THUMB"}}
        pt_task = primary.count_documents(thumb_query)
        ct_task = cloud.count_documents(thumb_query)
        at_task = archive.count_documents(thumb_query)

        p, c, a, pt, ct, at = await asyncio.gather(p_task, c_task, a_task, pt_task, ct_task, at_task)
        
        _stats_cache = {
            "primary": p, "cloud": c, "archive": a, "total": p + c + a,
            "primary_thumb": pt, "cloud_thumb": ct, "archive_thumb": at, "total_thumb": pt + ct + at
        }
        _stats_cache_time = now
        return _stats_cache
    except Exception as e:
        logger.error(f"Count Breakdown error: {e}")
        return {"primary": 0, "cloud": 0, "archive": 0, "total": 0, "primary_thumb": 0, "cloud_thumb": 0, "archive_thumb": 0, "total_thumb": 0}


# ─────────────────────────────────────────────────────────
# 🗂️ UNIVERSAL DIRECTORY COUNTS (actors / apps / websites)
# ✅ DRY + FAST: यह 4-लाइन वाला ब्लॉक 3 जगह कॉपी था (commands./stats,
# commands.ui_cb, web/stats_routes)। अब एक ही helper है, और तीनों count_documents
# पहले sequentially चलते थे (3 round-trips) — अब asyncio.gather से parallel हैं,
# यानी stats page/command पर ~2 round-trip का समय बचता है।
# ─────────────────────────────────────────────────────────
async def get_directory_counts():
    """(total, actors, apps, websites) लौटाता है; DB फेल हो तो सब 0।"""
    try:
        total, apps, websites = await asyncio.gather(
            actors.count_documents({}),
            actors.count_documents({"category": "app"}),
            actors.count_documents({"category": "website"}),
        )
        return total, total - apps - websites, apps, websites
    except Exception as e:
        logger.error(f"Directory Stats Error: {e}")
        return 0, 0, 0, 0


# ─────────────────────────────────────────────────────────
# 📝 POSTS CMS CATEGORY COUNTS
# ✅ DRY: यही aggregation commands.py (_get_post_stats) और web/stats_routes.py दोनों
# में अलग-अलग लिखी थी। पूरा array RAM में लोड करने की बजाय MongoDB ही group-by
# करता है। posts collection handle भी अब एक ही है (web/post_routes.py पहले अपना
# अलग `motor_db.db["Posts"]` बनाता था)।
# ─────────────────────────────────────────────────────────
async def get_post_category_counts():
    """(total, movies, web_series, app_video, adult) लौटाता है।"""
    counts = {}
    try:
        pipeline = [{"$group": {"_id": {"$ifNull": ["$category", "Uncategorized"]},
                                "count": {"$sum": 1}}}]
        async for doc in posts.aggregate(pipeline):
            counts[doc["_id"]] = doc["count"]
    except Exception as e:
        logger.error(f"Post Stats Error: {e}")
    return (sum(counts.values()),
            counts.get("Movies", 0),
            counts.get("Web Series", 0),
            counts.get("App Video", 0),
            counts.get("Porn", 0))

# ─────────────────────────────────────────────────────────
# 📐 MEDIA META (resolution + container) — INDEX-TIME CAPTURE
# ✅ width / height / mime_type Telegram se SIRF indexing ke waqt milte hain.
# Inhe baad me nikaalne ke liye poora channel dobara scan karna padega
# (flood-wait + ghante), isliye ye teen fields abhi hi save kar lete hain —
# aage se "1080p only", "mkv only", aspect-ratio jaise filter isi se banenge.
# Document par width/height hota hi nahi (getattr se safe) aur mime_type kabhi
# None bhi ho sakta hai, isliye dono ke liye sane default (0 / "") rakhe hain.
#
# ⚠️ v2 (2026-09-25, bug report: sab par 1280×720): Telegram ke w/h attributes
# par aankh-band bharosa GALAT nikla — uploader ne 1080p file par bhi default
# 1280×720 likh rakha tha. Isliye ab media_probe.py file ke ACTUAL BYTES
# (container header) se asli w/h/duration nikalta hai, aur probed values
# Telegram attributes ko OVERRIDE karti hain (neeche `probed` param). Version
# bump se purane (v1, possibly-jhoothe) docs migration me dobara uthenge aur
# probe se sach likha jayega — ye re-run ek baar ka hai, uske baad v2 final.
# ─────────────────────────────────────────────────────────
META_SCHEMA_VERSION = 2  # v1 → Telegram attrs copy; v2 → probed real w/h/duration

def build_media_meta(media, probed=None):
    """media object se {v, w, h, mime} dict banata hai (pure function — testable).

    `probed` = media_probe.probe_telegram_file() ka result ({w, h, duration}).
    File ke actual bytes se nikle w/h Telegram attributes se ZYADA sachche hain
    (uploader aksar default 1280×720 likh deta hai), isliye probed dims mile to
    wahi likhte hain. probed None/partial ho to attributes (purana behaviour).
    """
    w = int(getattr(media, "width", 0) or 0)
    h = int(getattr(media, "height", 0) or 0)
    if probed:
        try:
            pw, ph = int(probed.get("w") or 0), int(probed.get("h") or 0)
        except (TypeError, ValueError):
            pw = ph = 0
        if pw > 0 and ph > 0:
            w, h = pw, ph
    return {
        "v": META_SCHEMA_VERSION,
        "w": w,
        "h": h,
        "mime": str(getattr(media, "mime_type", None) or ""),
    }

def msg_media(msg):
    """Telegram message se asli media object (video/document/...) nikalta hai; na ho to None.

    ✅ DRY: ye helper pehle web/search_api.py me `_msg_media` ke naam se tha.
    Meta-migration plugin ko bhi wahi chahiye, isliye yahan ek hi jagah rakha.
    """
    return getattr(msg, msg.media.value, None) if getattr(msg, "media", None) else None

# ─────────────────────────────────────────────────────────
# 🎬 ASLI MEDIA TYPE — "document" me chhupi video/audio bhi pakadta hai
# ⚠️ YE WOH GADBAD HAI JO REPAIR HOGI: kuch asli video files Telegram par
#    "document" ki tarah store ho gayi thi (client ne unhe file ki tarah bheja,
#    video ki tarah nahi), to index ke waqt `type(media).__name__` = "document"
#    likh diya gaya. File khud video hai — uska mime_type `video/mp4` /
#    `video/x-matroska` hota hai. Isliye document ke liye mime_type dekh kar
#    asli type nikalte hain, taaki galat type wapas se na bane.
#
# ⚠️ LEKIN: Document object par `duration` / `width` / `height`
#    ATTRIBUTE HI NAHI HOTA (sirf file_id, file_name, mime_type, file_size,
#    thumbs). To aisi file ka duration/w/h is tarah NAHI mil sakta — uske liye
#    file download karke probe karna padega (ya dobara index). Sirf TYPE theek
#    ho jayega, aur ye bhi bina re-index ke.
#
# ℹ️ `image/*` (jpg/png/gif document) jaan-boojhkar nahi chhedte — Telegram
#    khud unhe document hi rakhta hai, aur search UI video/document maangta hai.
# ─────────────────────────────────────────────────────────
_DOC_MIME_TYPE_MAP = (
    ("video/", "video"),
    ("audio/", "audio"),
)

def media_true_type(media):
    """Media ka asli type — Telegram object se, warna mime_type se.

    Document jo asli me video/audio hai use "video"/"audio" deta hai (pure
    function, isliye seedhe testable).
    """
    obj_type = type(media).__name__.lower()
    if obj_type != "document":
        return obj_type
    mime = (getattr(media, "mime_type", None) or "").lower()
    for prefix, real in _DOC_MIME_TYPE_MAP:
        if mime.startswith(prefix):
            return real
    return obj_type

# ─────────────────────────────────────────────────────────
# 🔄 OLD-INDEX META MIGRATION (duration + width/height + mime_type)
# ✅ Purani indexed files me ye fields missing hain (baad me add hue the).
# Inhe nikaalne ke liye poora channel dobara index karne ki zaroorat NAHI —
# DB me saved `file_ref` (Telegram file_id) se hi file cached-media ki tarah
# wapas mangwa sakte hain, aur jo message milta hai usme duration / width /
# height / mime_type sab hota hai (warmup.py bilkul yahi karta hai).
#
# ⚠️ Jo is tarah NAHI mil sakta: msg_id / chat_id / msg_date (asli upload date).
#    Unke liye channel ko dobara index karna hi padega.
# ─────────────────────────────────────────────────────────
def build_meta_migration_query():
    """Jin docs me duration ya meta adhoora hai, unka mongo filter.

    - `meta.v` missing/!= current  → meta kabhi likha hi nahi gaya, ya purana
      schema (v1 docs dobara uthenge — unke w/h Telegram attributes se copy hue
      the jo jhoothe ho sakte hain; v2 run me probe se asli dims likhenge).
      ℹ️ v1→v2 re-run ek baar ka hai (audio/PDF docs bhi ek baar chhuenge —
      unpar probe skip hota hai, sirf v2 finalize hota hai; query simple rakhne
      ke liye inhe exclude nahi kiya).
    - `file_type` "document" hai par `meta.mime` video/audio ka → asli me video/audio
      file galat tarah se index hui thi (mime_type se pakad kar theek karte hain).
      ℹ️ Ye files Telegram par ASLI VIDEO hain (play bhi hoti hain) — sirf DB
      me purane code ke bug se "document" likh gaya tha. Isliye inhe fetch karne
      par poora Video object milta hai, aur duration + w + h + mime + type sab
      ek saath theek ho jaata hai.
    - `meta.err` wale (tooti hui file_ref) skip — warna har run me dobara fail honge

    ℹ️ "duration adhoora" wala branch jaan-boojhkar NAHI hai: jo doc par
    `meta.v` already set hai uski duration 0 hi rahegi (Document object par
    duration attribute hota hi nahi), to wo har run me dobara uthati — bina koi
    fayda. Pehli baar process hone ke baad doc query se apne aap nikal jaati hai.
    (Document-as-video ka duration ab probe se mil jaata hai — attributes se nahi.)
    """
    return {
        "$and": [
            {"meta.err": {"$exists": False}},
            {"$or": [
                {"meta.v": {"$ne": META_SCHEMA_VERSION}},
                {"$and": [
                    {"file_type": "document"},
                    {"meta.mime": {"$regex": r"^(video|audio)/"}},
                ]},
            ]},
        ],
    }

async def apply_media_meta_update(col, file_id, media, current_type=None, probed=None, skip_version=False):
    """Fetched media object se duration + meta.w/h/mime DB me likh deta hai.

    duration sirf tab likhte hain jab media par ho — documents par duration
    attribute hota hi nahi, aur unki legit 0 duration overwrap nahi karni.
    `meta.err` hata deta hai (agli baar query me dobara na aaye).

    🎬 `current_type` diya ho to galat `file_type` bhi theek karta hai:
    document likha hai par asli me video/audio hai (mime_type se pata chalta
    hai) → "video"/"audio" likh deta hai. Isse wo doc query se nikal jaata hai,
    to ye ek hi baar chalta hai (infinite loop nahi hota).

    🔍 `probed` (media_probe se asli w/h/duration) mile to wahi jeetta hai —
    Telegram attributes uploader ke likhe hote hain aur jhoothe ho sakte hain
    (1280×720 default wala bug), jabki probe file ke actual bytes se bolta hai.

    ⚠️ `skip_version=True` tab pass karo jab probe attempt hui par real dims
    nahi mile — meta.v nahi likhega taaki /migrate_meta ise dobara uthakar
    probe kar sake. Web backfill (search_api.py) bhi yahi pattern use karta hai.
    """
    meta = build_media_meta(media, probed)
    set_payload = {f"meta.{k}": v for k, v in meta.items()}

    # ⚠️ FIX: probe fail hone par meta.v skip karo — fake resolution permanently
    # save nahi honi chahiye, retry possible rehna chahiye
    if skip_version:
        set_payload.pop("meta.v", None)

    probed_dur = 0
    if probed:
        try:
            probed_dur = int(probed.get("duration") or 0)
        except (TypeError, ValueError):
            probed_dur = 0
    if probed_dur > 0:
        set_payload["duration"] = probed_dur
    else:
        duration = getattr(media, "duration", None)
        if duration:
            set_payload["duration"] = int(duration)

    if current_type is not None:
        true_type = media_true_type(media)
        if true_type != current_type:
            set_payload["file_type"] = true_type

    await col.update_one(
        {"_id": file_id},
        {"$set": set_payload, "$unset": {"meta.err": ""}},
    )
    return meta

async def mark_meta_migration_error(col, file_id):
    """Tooti hui file_ref wale doc ko mark karo taaki har run me dobara na uthe."""
    await col.update_one(
        {"_id": file_id},
        {"$set": {"meta.err": int(time.time())}},
    )

# ─────────────────────────────────────────────────────────
# 💾 SAVE FILE
# ─────────────────────────────────────────────────────────
async def save_file(media, collection_type="primary", probed=None):
    try:
        file_id = unpack_new_file_id(media.file_id)
        if not file_id: return "err"

        f_name  = re.sub(r"@\w+|(_|\-|\.|\+)", " ", str(media.file_name or "")).strip()
        caption = re.sub(r"@\w+|(_|\-|\.|\+)", " ", str(media.caption  or "")).strip()
        # ✅ asli type (document me chhupi video/audio bhi "video"/"audio") —
        # warna wahi gadbad dobara hoti jo purani files me hui hai
        file_type = media_true_type(media)
        col = COLLECTIONS.get(collection_type, primary)

        existing_doc = await col.find_one({"_id": file_id}, {"_id": 1})
        if existing_doc:
            return "dup"

        # ✅ NEW: video/audio ki duration (seconds) bhi save karte hain — sirf web UI
        # me dikhane ke liye (Telegram bot ke messages me jaan-boojhkar nahi bhejte).
        # hydrogram me Video/Animation/Audio par .duration hota hai, Document par nahi,
        # isliye getattr se safe rakha hai (documents ke liye 0 → UI me chip hide).
        # 🔍 probed (actual-bytes) duration mile to wahi — uploader ka attribute
        # aksar default/guess hota hai (1280×720 wala bug duration par bhi lagu tha).
        probed_dur = 0
        if probed:
            try:
                probed_dur = int(probed.get("duration") or 0)
            except (TypeError, ValueError):
                probed_dur = 0
        duration = probed_dur if probed_dur > 0 else int(getattr(media, "duration", 0) or 0)
        meta = build_media_meta(media, probed)

        # ✅ meta ko dotted keys ($set: {"meta.w": ...}) se likhna zaroori hai —
        # agar poora "meta" sub-document ek $set me bhejte, to future me kisi
        # naye meta field ke backfill ka data isi write se mit jaata.
        update_set = {
            "file_ref":  media.file_id,
            "file_name": f_name,
            "file_size": media.file_size,
            "file_type": file_type,
            "duration":  duration,
            "meta.v":    meta["v"],
            "meta.w":    meta["w"],
            "meta.h":    meta["h"],
            "meta.mime": meta["mime"],
        }

        update_payload = {"$set": update_set, "$setOnInsert": {"added_on": time.time()}}
        unset_payload = {}

        if USE_CAPTION_FILTER and caption: update_set["caption"] = caption
        else: unset_payload["caption"] = ""

        if unset_payload: update_payload["$unset"] = unset_payload

        await col.update_one({"_id": file_id}, update_payload, upsert=True)
        return "suc"
    except Exception as e:
        logger.error(f"save_file error: {e}")
        return "err"

# ─────────────────────────────────────────────────────────
# 🔍 REGEX BUILDER WITH SHORT-QUERY SHIELD
# ─────────────────────────────────────────────────────────
ALLOWED_SHORT = {"hd", "4k", "3d", "8k", "5.1", "7.1", "kg", "rr", "uhd", "hevc", "x265", "x264"}

def _build_regex(query: str):
    query = query.strip()
    if not query: return None
    q_lower = query.lower()
    
    if len(query) < 2 or (len(query) == 2 and q_lower not in ALLOWED_SHORT): return None
    if ' ' not in query: raw = r'(\b|[\.\+\-_])' + re.escape(query) + r'(\b|[\.\+\-_])'
    else: raw = re.escape(query).replace(r'\ ', r'.*[\s\.\+\-_]')

    try: return re.compile(raw, flags=re.IGNORECASE)
    except Exception: return re.compile(re.escape(query), flags=re.IGNORECASE)

# ─────────────────────────────────────────────────────────
# 📑 SHARED PROJECTION (पहले यह 7 जगह हुबहू टाइप किया गया था)
# ✅ meta bhi projection me hai — web/search API ko resolution & container
# chahiye hoti hai (filter/dropdown ke liye), aur yeh sirf ~40 bytes/doc ka hai.
# ─────────────────────────────────────────────────────────
FILE_PROJECTION = {"_id": 1, "file_name": 1, "file_size": 1, "file_type": 1,
                   "file_ref": 1, "caption": 1, "thumb_url": 1, "duration": 1,
                   "meta": 1}
FILE_PROJECTION_SCORED = {**FILE_PROJECTION, "score": {"$meta": "textScore"}}

# ─────────────────────────────────────────────────────────
# 🖼️ RESOLUTION TEXT (poster/poster-text chip ke liye)
# User ki requirement: "jo resolution rahega wahi show karega" — isliye yahan
# koi '720p'/'1080p' guess nahi hai. 1280×720 par "1280×720", 1245×655 par
# "1245×655" — jaisa hai waisa.
# ─────────────────────────────────────────────────────────
# filename me explicit "1280x720" likha ho to (purani files ke liye fallback).
# ⚠️ digits aur 'x' ke beech me SPACE allowed nahi — "2021 x265" (saal + codec)
# jaisi aam filename par "2021×265" galat resolution nikal aata tha.
_FILENAME_RES_RE = re.compile(r"\b(\d{3,4})[x×](\d{3,4})\b", re.IGNORECASE)
# resolution ki sanity range (chhota ~320x240, bada ~8K)
_RES_MIN_W, _RES_MAX_W = 320, 7680
_RES_MIN_H, _RES_MAX_H = 200, 4320

def get_resolution_text(width, height, file_name=""):
    """Asli resolution '1280×720' format me deta hai; na mile to khaali string.

    Resolution pata na chale (meta missing ya 0) to khaali — UI me chip banta hi
    nahi (duration chip jaise hi null-tolerant behaviour).
    """
    try:
        w = int(width or 0)
        h = int(height or 0)
    except (TypeError, ValueError):
        return ""

    if w > 0 and h > 0:
        return f"{w}×{h}"

    # meta khali (purani file) — filename me explicit resolution likha ho to use kalo
    if file_name:
        m = _FILENAME_RES_RE.search(str(file_name))
        if m:
            fw, fh = int(m.group(1)), int(m.group(2))
            if _RES_MIN_W <= fw <= _RES_MAX_W and _RES_MIN_H <= fh <= _RES_MAX_H:
                return f"{fw}×{fh}"
    return ""

def doc_resolution_text(doc):
    """DB doc se resolution text (meta missing/None hone par bhi safe)."""
    meta = doc.get("meta") or {}
    return get_resolution_text(meta.get("w", 0), meta.get("h", 0), doc.get("file_name", ""))

# ─────────────────────────────────────────────────────────
# 🧩 QUERY → MONGO FILTER BUILDER (single source of truth)
# ✅ DRY: यह वही logic है जो पहले _search() और get_search_results() दोनों में
# अलग-अलग लिखा था (clean_query → strict_query → $text, वरना regex $or, और lang
# होने पर $and wrap)। दोनों copies में कभी भी divergence हो सकता था — यानी bot
# और web एक ही query पर अलग filter चला सकते थे। अब एक ही जगह बनता है।
# ─────────────────────────────────────────────────────────
def _strict_text_query(raw_query: str) -> str:
    """quotes हटाकर हर शब्द को individually quoted strict $text query बनाता है"""
    clean = (raw_query or "").replace('"', '').replace("'", "").strip()
    words = clean.split()
    return " ".join(f'"{w}"' for w in words)

def build_query_filter(raw_query: str, regex, lang=None):
    """(mongo_filter, is_text_search) लौटाता है; कुछ भी match न बन पाए तो (None, False)"""
    strict_query = _strict_text_query(raw_query)
    if strict_query:
        flt = {"$text": {"$search": strict_query}}
        if lang:
            flt = {"$and": [flt, {"file_name": re.compile(lang, re.IGNORECASE)}]}
        return flt, True

    if regex:
        flt = ({"$or": [{"file_name": regex}, {"caption": regex}]}
               if USE_CAPTION_FILTER else {"file_name": regex})
        if lang:
            flt = {"$and": [flt, {"file_name": re.compile(lang, re.IGNORECASE)}]}
        return flt, False

    return None, False

def _tag_docs(docs, col_name: str):
    """हर doc पर file_id/source_col भरता है (UI/JSON दोनों को चाहिए)"""
    for doc in docs:
        doc["file_id"] = doc["_id"]
        doc["source_col"] = col_name
    return docs

# ─────────────────────────────────────────────────────────
# 🚀 SMART SEARCH
# ─────────────────────────────────────────────────────────
async def _search(col, raw_query: str, regex, offset: int, limit: int, lang=None, bypass_count=False):
    flt, is_text = build_query_filter(raw_query, regex, lang)
    if not flt:
        return [], 0

    col_name = col.name.lower()

    if is_text:
        cursor = col.find(flt, FILE_PROJECTION_SCORED).sort([("score", {"$meta": "textScore"})])
        cursor.skip(offset).limit(limit)
        docs = await cursor.to_list(length=limit)
        if docs:
            _tag_docs(docs, col_name)
            count = 0 if bypass_count else await col.count_documents(flt)
            return docs, count
        # text-search खाली आया तो नीचे regex fallback चलता है
        flt, is_text = build_query_filter("", regex, lang)
        if not flt:
            return [], 0

    cursor = col.find(flt, FILE_PROJECTION).sort('_id', -1)
    cursor.skip(offset).limit(limit)
    docs = await cursor.to_list(length=limit)
    _tag_docs(docs, col_name)

    count = 0 if bypass_count else (await col.count_documents(flt) if docs else 0)
    return docs, count

async def get_count(col, flt, bypass):
    if bypass: return 1000
    return await col.count_documents(flt)

# ─────────────────────────────────────────────────────────
# 🌐 PUBLIC SEARCH API (NEW UPGRADE: CROSS-COLLECTION MERGE)
# ─────────────────────────────────────────────────────────
async def get_search_results(query, max_results, offset=0, lang=None, collection_type="primary", bypass_count=False, cached_counts=None, counts_out=None):
    if not query: return [], "", 0, collection_type
    raw_query  = str(query).strip()
    regex      = _build_regex(raw_query)

    # ✅ DRY: पहले यहाँ query-cleaning दोबारा inline लिखी थी; अब वही shared
    # build_query_filter() इस्तेमाल होता है जो _search() भी use करता है।
    flt, is_text = build_query_filter(raw_query, regex, lang)
    if not flt:
        return [], "", 0, collection_type

    results, total, actual_src = [], 0, collection_type

    if collection_type == "all":

        # ✅ FIX: filter.py (bot साइड) पहले से computed counts (cached_counts) भेजता है
        # ताकि सिर्फ़ page बदलने पर तीनों collections को दोबारा count_documents ना
        # करना पड़े (fast pagination)। bypass_count यहाँ हमेशा False रहता है (bot
        # हमेशा असली गिनती चाहता है, web अलग से bypass_count=True भेजता है)।
        if cached_counts and all(k in cached_counts for k in ("primary", "cloud", "archive")):
            cnt_p, cnt_c, cnt_a = cached_counts["primary"], cached_counts["cloud"], cached_counts["archive"]
        else:
            cnt_p, cnt_c, cnt_a = await asyncio.gather(
                get_count(primary, flt, bypass_count),
                get_count(cloud, flt, bypass_count),
                get_count(archive, flt, bypass_count)
            )

        # ✅ FIX: caller (bot) को असली breakdown counts वापस दो ताकि UI में दिखा सके
        # और अगली बार cached_counts के तौर पर वापस भेज सके
        if counts_out is not None:
            counts_out["primary"], counts_out["cloud"], counts_out["archive"] = cnt_p, cnt_c, cnt_a

        total = cnt_p + cnt_c + cnt_a

        sources = []
        if cnt_p > 0: sources.append("Primary")
        if cnt_c > 0: sources.append("Cloud")
        if cnt_a > 0: sources.append("Archive")

        if len(sources) > 1:
            actual_src = "All"
        elif len(sources) == 1:
            actual_src = sources[0]
        else:
            actual_src = "None"

        rem_limit = max_results
        curr_offset = offset
        projection = FILE_PROJECTION_SCORED if is_text else FILE_PROJECTION

        for col, cnt in [(primary, cnt_p), (cloud, cnt_c), (archive, cnt_a)]:
            if cnt == 0 or rem_limit <= 0: continue

            if curr_offset >= cnt:
                curr_offset -= cnt
                continue

            cursor = col.find(flt, projection)
            cursor = cursor.sort([("score", {"$meta": "textScore"})]) if is_text else cursor.sort('_id', -1)
            cursor.skip(curr_offset).limit(rem_limit)
            docs = await cursor.to_list(length=rem_limit)

            results.extend(_tag_docs(docs, col.name.lower()))

            rem_limit -= len(docs)
            curr_offset = 0

    else:
        col = COLLECTIONS.get(collection_type, primary)
        results, total = await _search(col, raw_query, regex, offset, max_results, lang, bypass_count=bypass_count)
        actual_src = collection_type.capitalize()
        if not results: total = 0
        # ✅ FIX: single-collection टैब (primary/cloud/archive) के लिए भी counts_out भरो
        if counts_out is not None:
            counts_out[collection_type] = total

    if bypass_count:
        has_more = len(results) == max_results
        next_offset = offset + max_results if has_more else ""
        total = offset + len(results) + (1 if has_more else 0)
    else:
        next_offset = offset + max_results
        next_offset = "" if next_offset >= total else next_offset

    return results, next_offset, total, actual_src


# ─────────────────────────────────────────────────────────
# 🧠 DB-BASED SPELL SUGGESTIONS (Google Suggest के बजाय अपने ही
# catalog से "Did you mean" सुझाव — इसलिए सुझाया गया नाम हमेशा
# वाकई मौजूद कंटेंट से जुड़ा होता है, Google जैसा "फिर भी नहीं मिला"
# वाला case नहीं आता, और कोई external API call भी नहीं लगती)
# ─────────────────────────────────────────────────────────
def _clean_title_guess(file_name: str) -> str:
    """✅ FIX: पहले यहाँ quality/resolution/year/extension जैसे tokens को
    ढूंढकर काट दिया जाता था और फिर casing भी बदली जाती थी — इससे suggestion
    का टेक्स्ट DB में save असली file_name से अलग दिखता था (जैसे "l" की जगह
    "L", या "1080p l Test" वाला हिस्सा पूरी तरह गायब)। अब suggestion हमेशा
    file_name जैसा DB में है बिल्कुल वैसा ही (सिर्फ extra/multiple spaces
    normalize करके) दिखाया जाता है — कोई trimming, cleaning या case-change
    नहीं।"""
    if not file_name: return ""
    return re.sub(r'\s+', ' ', file_name).strip()


def _dedupe_titles(docs, limit: int, seen: set):
    """docs से unique, non-empty titles निकालता है (case-insensitive dedupe)।

    ✅ DRY: यह 8-लाइन वाला loop get_db_spell_suggestions() में दो बार हुबहू लिखा
    था (text-search candidates और prefix-fallback candidates के लिए)। `seen` को
    in-place update करता है ताकि दोनों चरणों में dedupe आपस में जुड़ा रहे।
    """
    out = []
    for doc in docs:
        title = _clean_title_guess(doc.get("file_name", ""))
        key = title.lower()
        if not title or key in seen:
            continue
        seen.add(key)
        out.append(title)
        if len(out) >= limit:
            break
    return out

async def get_db_spell_suggestions(query, limit=5, collection_type="all"):
    q = str(query or "").strip()
    if not q: return []

    cols = [primary, cloud, archive] if collection_type == "all" else [COLLECTIONS.get(collection_type, primary)]
    seen = {q.lower()}
    candidates = []

    try:
        # ✅ unquoted $text search जानबूझकर लगाया — get_search_results वाला strict
        # (हर शब्द quoted, phrase-जैसा) search typo पर कुछ नहीं देगा। यहाँ ढीला
        # OR-style stemmed match चाहिए ताकि छोटी spelling गलतियों पर भी करीबी
        # titles मिल जाएँ।
        tasks = [
            col.find(
                {"$text": {"$search": q}},
                {"file_name": 1, "score": {"$meta": "textScore"}}
            ).sort([("score", {"$meta": "textScore"})]).limit(15).to_list(length=15)
            for col in cols
        ]
        results_lists = await asyncio.gather(*tasks, return_exceptions=True)
    except Exception as e:
        logger.debug(f"DB spell suggestion text-search failed: {e}")
        return []

    for res in results_lists:
        if isinstance(res, Exception):
            continue
        candidates.extend(res)

    candidates.sort(key=lambda d: d.get("score", 0), reverse=True)

    suggestions = _dedupe_titles(candidates, limit, seen)

    # ✅ FIX: पूरी तरह अनजान/बिगड़ा हुआ query (जैसे "Hootx") पर ऊपर वाला
    # stemmed $text search भी कभी-कभी कुछ नहीं देता (कोई शब्द match ही नहीं
    # होता), और तब पहले suggestions पूरी तरह खाली रह जाते थे। अब उस case में
    # query के पहले 3 अक्षरों से एक ढीला "prefix" regex fallback चलाया जाता है
    # — ताकि कम से कम मिलते-जुलते शुरुआती अक्षरों वाले titles तो सुझाए जा सकें।
    if not suggestions and len(q) >= 3:
        prefix = re.escape(q[:3])
        prefix_regex = re.compile(r'(\b|[\s.\-_])' + prefix, re.IGNORECASE)
        try:
            tasks = [
                col.find(
                    {"file_name": prefix_regex},
                    {"file_name": 1}
                ).limit(15).to_list(length=15)
                for col in cols
            ]
            prefix_results = await asyncio.gather(*tasks, return_exceptions=True)
        except Exception as e:
            logger.debug(f"DB spell suggestion prefix-fallback failed: {e}")
            prefix_results = []

        prefix_candidates = []
        for res in prefix_results:
            if isinstance(res, Exception):
                continue
            prefix_candidates.extend(res)

        suggestions.extend(_dedupe_titles(prefix_candidates, limit - len(suggestions), seen))

    return suggestions


# ─────────────────────────────────────────────────────────
# 🆕 RECENT FILES (कोई query ना हो तब dashboard पर दिखाने के लिए
# — सबसे नई अपलोड की गई फाइलें, ताकि पेज खाली ना लगे)
# ─────────────────────────────────────────────────────────
async def get_recent_files(max_results, offset=0, collection_type="all"):
    proj = {**FILE_PROJECTION, "added_on": 1}

    if collection_type == "all":
        take = offset + max_results + 1  # +1 ताकि has_more पता चल सके
        merged = []
        for col in (primary, cloud, archive):
            cursor = col.find({}, proj).sort([('added_on', -1), ('_id', -1)]).limit(take)
            docs = await cursor.to_list(length=take)
            for doc in docs:
                doc["file_id"] = doc["_id"]
                doc["source_col"] = col.name.lower()
            merged.extend(docs)

        merged.sort(key=lambda d: (d.get("added_on") or 0, str(d["_id"])), reverse=True)
        has_more = len(merged) > offset + max_results
        page = merged[offset: offset + max_results]
        next_offset = offset + max_results if has_more else ""
        return page, next_offset

    col = COLLECTIONS.get(collection_type, primary)
    cursor = col.find({}, proj).sort([('added_on', -1), ('_id', -1)]).skip(offset).limit(max_results)
    docs = await cursor.to_list(length=max_results)
    for doc in docs:
        doc["file_id"] = doc["_id"]
        doc["source_col"] = collection_type
    has_more = len(docs) == max_results
    next_offset = offset + max_results if has_more else ""
    return docs, next_offset


# ─────────────────────────────────────────────────────────
# 🗑 DELETE FILES  (✅ DELETE_CHANNEL बैकअप इंजन)
# सिर्फ़ /delete (regex targeted delete) और web के /api/delete में डिलीट होने से
# पहले फाइल DELETE_CHANNEL में फॉरवर्ड होती है। /delete_all (पूरा collection wipe)
# में बैकअप जानबूझकर स्किप किया गया है।
# ─────────────────────────────────────────────────────────
async def _backup_before_delete(doc):
    """किसी फाइल डॉक्युमेंट को डिलीट से पहले DELETE_CHANNEL में बैकअप भेजता है।
    बैकअप फेल हो जाए तो भी डिलीट को नहीं रोकता — बस warning log करके आगे बढ़ता है
    (ताकि Telegram flood/network दिक्कत की वजह से admin का delete operation अटके नहीं)।"""
    if not DELETE_CHANNEL or not getattr(temp, "BOT", None):
        return
    file_ref = doc.get("file_ref")
    if not file_ref:
        return
    caption = f"🗑 <b>Deleted File Backup</b>\n\n📄 <code>{doc.get('file_name', 'Unknown')}</code>"
    for _attempt in range(2):  # 1 असली कोशिश + 1 FloodWait के बाद रिट्राई
        try:
            await temp.BOT.send_cached_media(chat_id=DELETE_CHANNEL, file_id=file_ref, caption=caption)
            return
        except FloodWait as e:
            await asyncio.sleep(e.value)
        except Exception as e:
            logger.warning(f"Delete-backup failed for {doc.get('_id')}: {e}")
            return


async def delete_files(query, collection_type="all"):
    deleted = 0
    try:
        cols = [col for name, col in FILE_COLLECTIONS.items()
                if collection_type == "all" or name == collection_type]

        if query == "*":
            # ✅ /delete_all (पूरा collection wipe) — यहाँ DELETE_CHANNEL में बैकअप
            # जानबूझकर नहीं भेजा जाता (हज़ारों फाइलें हो सकती हैं, flood/समय दोनों
            # की समस्या होगी)। सिर्फ़ /delete (regex-आधारित) और web से backup होता है।
            flt = {}
            for col in cols:
                res = await col.delete_many(flt)
                deleted += res.deleted_count
            return deleted

        regex = _build_regex(str(query))
        if not regex: return 0
        flt = {"file_name": regex}

        for col in cols:
            # ✅ /delete (regex मैच वाला targeted delete) — DB से हटाने से पहले
            # हर matching फाइल का बैकअप DELETE_CHANNEL में भेजा जाता है
            async for doc in col.find(flt, {"_id": 1, "file_name": 1, "file_ref": 1}):
                await _backup_before_delete(doc)
            res = await col.delete_many(flt)
            deleted += res.deleted_count
        return deleted
    except Exception as e:
        logger.error(f"delete_files error: {e}")
        return deleted


async def delete_single_file(file_id, collection_type="primary"):
    """एक फाइल को डिलीट करने से पहले DELETE_CHANNEL में बैकअप भेजता है, फिर DB से हटाता है।
    web/search_api.py के /api/delete endpoint से इस्तेमाल होता है (delete_files की
    तरह ही _backup_before_delete reuse करता है, दोबारा नहीं लिखा)।"""
    try:
        col = COLLECTIONS.get(collection_type)
        if col is None:
            return False
        doc = await col.find_one({"_id": file_id}, {"_id": 1, "file_name": 1, "file_ref": 1})
        if not doc:
            return False
        await _backup_before_delete(doc)
        res = await col.delete_one({"_id": file_id})
        return bool(res.deleted_count)
    except Exception as e:
        logger.error(f"delete_single_file error: {e}")
        return False

async def get_file_details(file_id):
    try:
        for col in [primary, cloud, archive]:
            doc = await col.find_one({"_id": file_id}, FILE_PROJECTION)
            if doc:
                doc["file_id"] = doc["_id"]  
                return doc
        return None
    except Exception as e:
        logger.error(f"get_file_details error: {e}")
        return None

def encode_file_id(s: bytes) -> str:
    r, n = b"", 0
    for i in s + bytes([22]) + bytes([4]):
        if i == 0: n += 1
        else:
            if n: r += b"\x00" + bytes([n]); n = 0
            r += bytes([i])
    return base64.urlsafe_b64encode(r).decode().rstrip("=")

def unpack_new_file_id(new_file_id: str):
    try:
        decoded = FileId.decode(new_file_id)
        return encode_file_id(pack("<iiqq", int(decoded.file_type), decoded.dc_id, decoded.media_id, decoded.access_hash))
    except Exception as e:
        logger.error(f"unpack_new_file_id error: {e}")
        return None

# ─────────────────────────────────────────────────────────
# 🎭 ACTOR TAGS MULTI-PIPELINE SEARCH ENGINE (100% ISOLATED & DOUBLE CHECKED)
# ─────────────────────────────────────────────────────────
async def get_actor_search_results(actor_name, tags_list, max_results, offset=0, collection_type="all"):
    """नाम और सभी कस्टमाइज्ड टैग्स को मिलाकर सिंक करता है ताकि वाइल्डकार्ड क्रैश न हो।"""
    all_terms = []
    
    if actor_name and str(actor_name).strip():
        all_terms.append(str(actor_name).strip())
        
    if tags_list and isinstance(tags_list, list):
        for t in tags_list:
            if t and str(t).strip():
                all_terms.append(str(t).strip())
                
    if not all_terms:
        return [], ""
                
    escaped_terms = [re.escape(term) for term in all_terms if term]
    combined_raw = r'(' + '|'.join(escaped_terms) + r')'
    
    try:
        regex = re.compile(combined_raw, flags=re.IGNORECASE)
    except Exception:
        regex = re.compile(re.escape(actor_name) if actor_name else "NO_ACTOR_MATCH_FOUND", flags=re.IGNORECASE)
        
    reg_flt = {"$or": [{"file_name": regex}, {"caption": regex}]} if USE_CAPTION_FILTER else {"file_name": regex}
    results = []
    cols = [primary, cloud, archive] if collection_type == "all" else [COLLECTIONS.get(collection_type, primary)]
    
    for col in cols:
        cursor = col.find(reg_flt, FILE_PROJECTION).sort('_id', -1)
        cursor.skip(offset).limit(max_results)
        docs = await cursor.to_list(length=max_results)
        if docs:
            for doc in docs:
                doc["file_id"] = doc["_id"]
                doc["source_col"] = col.name.lower()
            results.extend(docs)
            if len(results) >= max_results:
                results = results[:max_results]
                break

    has_more = len(results) == max_results
    next_offset = offset + max_results if has_more else ""
    return results, next_offset

# ─────────────────────────────────────────────────────────
# 🗑️ ACTOR PROFILE & GALLERY ELEMENT PURGE PIPELINE (NEW UPGRADE)
# ─────────────────────────────────────────────────────────
async def delete_actor_profile(actor_id):
    """डेटाबेस से एक्टर की पूरी प्रोफाइल डिलीट करता है।"""
    try:
        res = await actors.delete_one({"_id": ObjectId(actor_id)})
        return bool(res.deleted_count)
    except Exception as e:
        logger.error(f"delete_actor_profile error: {e}")
        return False

async def delete_gallery_image_by_index(actor_id, index: int):
    """गैलरी एरे में से स्पेसिफिक इंडेक्स वाली इमेज हटाता है।

    ✅ FIX: पहले यह index से value निकालकर `$pull: {gallery: value}` करता था —
    Telegram identical photos को एक ही file_id देता है, इसलिए duplicate होने पर
    एक delete में सारी copies उड़ जाती थीं (या semantics गलत हो जाते थे)।
    अब index-based delete का सही atomic तरीका: पहले उस position को `$unset`
    (null बन जाता है), फिर null entries को `$pull` — सिर्फ़ वही एक element हटता है।

    साथ ही `gallery_updated_at` bump होता है ताकि frontend की versioned image
    URLs (&v=) बदल जाएँ और browser का 1-साल वाला immutable cache bust हो जाए।
    """
    try:
        oid = ObjectId(actor_id)
        doc = await actors.find_one({"_id": oid})
        if not doc or "gallery" not in doc: return False
        gallery = doc["gallery"]
        if index < 0 or index >= len(gallery): return False
        res = await actors.update_one(
            {"_id": oid},
            {"$unset": {f"gallery.{index}": 1}, "$set": {"gallery_updated_at": int(time.time())}},
        )
        if not res.modified_count: return False
        # $unset array element को null छोड़ता है — उसे निकालना ज़रूरी है
        await actors.update_one({"_id": oid}, {"$pull": {"gallery": None}})
        return True
    except Exception as e:
        logger.error(f"delete_gallery_image error: {e}")
        return False
