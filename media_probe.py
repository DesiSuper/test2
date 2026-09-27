"""🎯 TRUE MEDIA PROBE — asli video resolution nikaalne wala engine.

❓ YE MODULE KYUN BANA (bug report 2026-09-25):
   /migrate_meta ke baad web par SABHI videos par "1280×720" dikh raha tha,
   jabki asli files alag resolution ki thi (1080p file bhi 1280×720).
   Wajah: migration/indexing Telegram ke stored `width`/`height` attributes ko
   aankh-band karke copy karte the — par ye attributes UPLOADER ne likhe hote
   hain (DocumentAttributeVideo), aur aksar upload-bots/scripts inhe probe kiye
   bina hi default `1280×720` likh dete hain. Matlab Telegram ka attribute JHOOTH
   ho sakta hai, aur hamara DB usi jhooth ko "asli resolution" samajh raha tha.

✅ FIX: resolution ab file ke ACTUAL BYTES (container header) se nikala jaata hai:
   - MKV/WebM → EBML Tracks → PixelWidth/PixelHeight (+ Display W/H)
   - MP4/MOV/M4V → moov → video trak → tkhd width/height (+ mvhd duration)
   - AVI → hdrl → vids strf → BITMAPINFOHEADER w/h (+ avih duration)
   Poori file download NAHI hoti — sirf shuru ke ~2MB (head) aur zaroorat par
   aakhir ke ~4MB (tail, sirf moov-at-end wale MP4 ke liye) MTProto range se
   aate hain. Har cheez fail-soft hai: probe fail → Telegram attributes (purana
   behaviour), migration/backfill/index kabhi probe ki wajah se fail nahi hote.

   Parsers pure-Python hain (koi binary dependency nahi), isliye unit-testable
   bhi hain aur Koyeb (512MB) par bhi halke hain. Aakhir me ek ffprobe fallback
   bhi hai (TS/FLV/WMV jaise rare containers ke liye — Dockerfile me ffmpeg
   pehle se installed hai), jo na mile to chupchaap skip ho jaata hai.
"""

import asyncio
import json
import logging
import shutil
import struct
import subprocess

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────
# ⚙️ TUNABLES
# ─────────────────────────────────────────────────────────
HEAD_MB = 2          # har file ke shuru se itne MB (MKV/AVI/faststart-MP4 ke liye kaafi)
TAIL_MB = 4          # moov-at-end wale MP4 ke liye aakhir se itne MB (moov ~MBs ka hota hai)
FETCH_TIMEOUT = 30   # ek range-fetch par max itne seconds (uske baad jo mila usi se kaam)
FFPROBE_TIMEOUT = 20  # ffprobe fallback par max itne seconds

# sanity bounds (parser bug / corrupt header DB me zehar na ghole)
_MIN_W, _MAX_W = 16, 7680    # 8K tak
_MIN_H, _MAX_H = 16, 4320
_MAX_DURATION_SEC = 2 * 86400  # 2 din se lambi "movie" jhooth hai

# document-as-video pehchaanne ke liye video extensions
VIDEO_EXTS = frozenset({
    ".mkv", ".mp4", ".m4v", ".mov", ".avi", ".webm",
    ".ts", ".m2ts", ".flv", ".wmv", ".mpg", ".mpeg",
})


# ─────────────────────────────────────────────────────────
# 🎬 PROBE KARNA CHAHIYE YA NAHI (gating — faltu download roko)
# ─────────────────────────────────────────────────────────
def should_probe_media(media, file_name=""):
    """Sirf video-ish media par probe karo (PDF/MP3 par bandwidth waste nahi).

    - Video/Animation/VideoNote object → hamesha True
    - Document + video/* mime → True (file ki tarah bheji gayi video)
    - Document + video extension (.mkv/.mp4/...) → True (mime missing ho tab bhi)
    - baaki sab (pdf/audio/image/...) → False
    """
    if media is None:
        return False
    obj_type = type(media).__name__.lower()
    if obj_type in ("video", "animation", "videonote", "video_note"):
        return True
    if obj_type != "document":
        return False
    mime = (getattr(media, "mime_type", None) or "").lower()
    if mime.startswith("video/"):
        return True
    name = str(file_name or getattr(media, "file_name", "") or "").lower()
    dot = name.rfind(".")
    if dot != -1 and name[dot:] in VIDEO_EXTS:
        return True
    return False


# ─────────────────────────────────────────────────────────
# 📦 MP4 / MOV / M4V  (ISO BMFF boxes)
# ─────────────────────────────────────────────────────────
def _read_box(buf, pos, end):
    """Ek box header padho → (type, payload_start, payload_end, next_pos) ya None.

    Truncated buffer (box aage tak claim kare) par payload ko buffer-end tak
    cap kar dete hain taaki jo mila usi se parse ho sake, crash nahi.
    """
    if pos + 8 > end:
        return None
    size = int.from_bytes(buf[pos:pos + 4], "big")
    typ = bytes(buf[pos + 4:pos + 8])
    hdr = 8
    if size == 1:  # largesize
        if pos + 16 > end:
            return None
        size = int.from_bytes(buf[pos + 8:pos + 16], "big")
        hdr = 16
    elif size == 0:  # box file ke end tak
        size = end - pos
    if typ == b"uuid":
        hdr += 16
        if pos + hdr > end:
            return None
    if size < hdr or size <= 0:
        return None
    payload_end = pos + size
    if payload_end > end:
        payload_end = end  # truncated — jitna hai utna
    nxt = pos + size
    if nxt > end or nxt <= pos:
        nxt = end
    return (typ, pos + hdr, payload_end, nxt)


def _parse_tkhd(payload):
    """trak header se (width, height). Rotation matrix 90°/270° ho to swap."""
    ln = len(payload)
    if ln < 84:
        return (0, 0)
    ver = payload[0]
    off = 88 if ver == 1 else 76  # width/height ka offset (16.16 fixed)
    if ln < off + 8:
        return (0, 0)
    w = int(round(int.from_bytes(payload[off:off + 4], "big") / 65536))
    h = int(round(int.from_bytes(payload[off + 4:off + 8], "big") / 65536))
    # rotation matrix tkhd me width se 36 bytes pehle (9 x fixed values)
    moff = off - 36
    try:
        a = int.from_bytes(payload[moff:moff + 4], "big", signed=True)
        b = int.from_bytes(payload[moff + 4:moff + 8], "big", signed=True)
        c = int.from_bytes(payload[moff + 12:moff + 16], "big", signed=True)
        d = int.from_bytes(payload[moff + 16:moff + 20], "big", signed=True)
    except Exception:
        return (w, h)
    if a == 0 and d == 0 and b != 0 and c != 0:
        w, h = h, w  # 90°/270° rotated (portrait reels/shorts) → display dims
    return (w, h)


def _parse_mvhd(payload):
    """movie header se duration (seconds) ya None."""
    ln = len(payload)
    if ln < 20:
        return None
    try:
        if payload[0] == 1:
            if ln < 32:
                return None
            timescale = int.from_bytes(payload[20:24], "big")
            duration = int.from_bytes(payload[24:32], "big")
        else:
            timescale = int.from_bytes(payload[12:16], "big")
            duration = int.from_bytes(payload[16:20], "big")
    except Exception:
        return None
    if timescale > 0 and duration > 0:
        return duration / timescale
    return None


def _hdlr_is_video(payload):
    """mdia/hdlr ka handler_type 'vide' hai ya nahi."""
    return len(payload) >= 12 and bytes(payload[8:12]) == b"vide"


def _parse_trak(buf, start, end):
    """Ek trak box se video-track ke (w, h). Non-video trak par (0, 0)."""
    tw = th = 0
    saw_hdlr = False
    is_video = False
    pos = start
    while pos + 8 <= end:
        box = _read_box(buf, pos, end)
        if not box:
            break
        typ, ps, pe, nxt = box
        if typ == b"tkhd":
            tw, th = _parse_tkhd(buf[ps:pe])
        elif typ == b"mdia":
            # mdia ke andar hdlr dhoondo (ek level)
            p2 = ps
            while p2 + 8 <= pe:
                b2 = _read_box(buf, p2, pe)
                if not b2:
                    break
                t2, s2, e2, n2 = b2
                if t2 == b"hdlr":
                    saw_hdlr = True
                    is_video = _hdlr_is_video(buf[s2:e2])
                    break
                p2 = n2
        pos = nxt
    if is_video or not saw_hdlr:
        # hdlr na mile (truncated buffer) to tkhd par bharosa — galat hone par
        # bhi sanity-check + Telegram-fallback aage sambhal lenge
        return (tw, th)
    return (0, 0)


def _parse_moov_payload(buf, start, end):
    """moov ke andar mvhd (duration) + pehle video trak (w/h)."""
    w = h = 0
    dur = None
    pos = start
    while pos + 8 <= end:
        box = _read_box(buf, pos, end)
        if not box:
            break
        typ, ps, pe, nxt = box
        if typ == b"mvhd" and dur is None:
            dur = _parse_mvhd(buf[ps:pe])
        elif typ == b"trak" and (w <= 0 or h <= 0):
            tw, th = _parse_trak(buf, ps, pe)
            if tw > 0 and th > 0:
                w, h = tw, th
        pos = nxt
    return (w, h, dur)


def parse_mp4(data):
    """Head-buffer me top-level boxes walk karke moov dhoondo → (w, h, dur|None).

    moov-at-end wali file ka head sirf ftyp+mdat rakhta hai → (0, 0, None),
    uske liye parse_mp4_tail() hai.
    """
    try:
        end = len(data)
        pos = 0
        while pos + 8 <= end:
            box = _read_box(data, pos, end)
            if not box:
                break
            typ, ps, pe, nxt = box
            if typ == b"moov":
                return _parse_moov_payload(data, ps, pe)
            pos = nxt
    except Exception:
        pass
    return (0, 0, None)


def parse_mp4_tail(tail):
    """File ke aakhri bytes me moov dhoondo (moov-at-end wale MP4 ke liye).

    Tail buffer mdat ke beech se shuru hota hai, isliye top-level walk kaam
    nahi karega — 'moov' signature scan + strict validation (pehla child mvhd
    jaisa sane box hona chahiye, warna mdat-data ka false positive hai).
    Pehla VALID moov jisme w/h mile wahi result hai.
    """
    try:
        end = len(tail)
        if end < 64:
            return (0, 0, None)
        idx = 0
        while True:
            i = tail.find(b"moov", idx)
            if i < 4:
                return (0, 0, None)
            size = int.from_bytes(tail[i - 4:i], "big")
            if size == 1:  # largesize
                if i + 12 > end:
                    idx = i + 4
                    continue
                size = int.from_bytes(tail[i + 4:i + 12], "big")
                ps = i + 12
            else:
                ps = i + 4
            # moov kam se kam mvhd jitna bada to hoga; buffer se bahar claim
            # kare to cap (moov ka head hi chahiye — mvhd/tkhd shuru me hote hain)
            if size < 32:
                idx = i + 4
                continue
            pe = i - 4 + size
            if pe > end:
                pe = end
            if pe - ps < 24:
                idx = i + 4
                continue
            child = _read_box(tail, ps, pe)
            if not child or child[0] not in (b"mvhd", b"trak", b"udta", b"meta", b"iods"):
                idx = i + 4
                continue
            w, h, dur = _parse_moov_payload(tail, ps, pe)
            if w > 0 and h > 0:
                return (w, h, dur)
            idx = i + 4
    except Exception:
        pass
    return (0, 0, None)


# ─────────────────────────────────────────────────────────
# 🗃️ MKV / WEBM  (EBML)
# ─────────────────────────────────────────────────────────
_SEGMENT, _INFO, _TRACKS, _TRACK_ENTRY, _VIDEO = 0x18538067, 0x1549A966, 0x1654AE6B, 0xAE, 0xE0
_MASTER_IDS = frozenset({_SEGMENT, _INFO, _TRACKS, _TRACK_ENTRY, _VIDEO})
_PIXEL_W, _PIXEL_H = 0xB0, 0xBA
_DISPLAY_W, _DISPLAY_H = 0x54B0, 0x54BA
_DURATION, _TIMECODESCALE = 0x4489, 0x2AD7B1


def _read_vint(buf, pos, end, for_id):
    """EBML variable-int → (value, length) ya None. Size me all-1s = unknown (-1)."""
    if pos >= end:
        return None
    first = buf[pos]
    length = 1
    mask = 0x80
    while length <= 8 and not (first & mask):
        length += 1
        mask >>= 1
    if length > 8 or pos + length > end:
        return None
    if for_id:
        val = 0
        for k in range(length):
            val = (val << 8) | buf[pos + k]
    else:
        val = first & (mask - 1)
        for k in range(1, length):
            val = (val << 8) | buf[pos + k]
        if val == (1 << (7 * length)) - 1:
            val = -1  # unknown size (Segment aksar aisa hi hota hai)
    return (val, length)


def _ebml_uint(buf):
    val = 0
    for b in bytes(buf):
        val = (val << 8) | b
    return val


def _ebml_float(buf):
    raw = bytes(buf)
    try:
        if len(raw) == 4:
            return struct.unpack(">f", raw)[0]
        if len(raw) == 8:
            return struct.unpack(">d", raw)[0]
    except Exception:
        pass
    return None


def _walk_ebml(buf, pos, end, st, depth=0):
    """Master elements me recurse karo; leaves collect karo. Sirf PEHLE video
    track ke dims + Info ka duration chahiye (Cluster/Attachments skip)."""
    if depth > 8 or st.get("done"):
        return
    in_video = st.get("in_video", False)
    while pos < end:
        if st.get("done"):
            return
        r = _read_vint(buf, pos, end, True)
        if not r:
            return
        eid, ln = r
        pos += ln
        r = _read_vint(buf, pos, end, False)
        if not r:
            return
        size, ln2 = r
        pos += ln2
        elem_end = end if size < 0 else min(pos + size, end)
        if size >= 0 and elem_end <= pos:
            return  # zero-size/corrupt element — aage progress impossible (infinite loop guard)
        if eid in _MASTER_IDS and size != 0:
            if eid == _VIDEO:
                if st.get("video_seen"):
                    pos = elem_end  # doosra video track — ignore
                    if size < 0:
                        return
                    continue
                st["video_seen"] = True
                st["in_video"] = True
                _walk_ebml(buf, pos, elem_end, st, depth + 1)
                st["in_video"] = in_video
                # pehla Video element poora padh liya (Pixel + Display dono) —
                # duration bhi mil chuki ho to aage scan bekaar hai
                st["video_done"] = True
                if st.get("dur") is not None:
                    st["done"] = True
                    return
            else:
                _walk_ebml(buf, pos, elem_end, st, depth + 1)
        else:
            _ebml_leaf(eid, buf, pos, elem_end, st, in_video)
        if size < 0:
            return  # unknown-size element baaki buffer kha gaya
        pos = elem_end


def _ebml_leaf(eid, buf, start, end, st, in_video):
    ln = end - start
    if ln <= 0 or ln > 16:
        return  # PixelW/Duration jaise leaves chhote hote hain; bada = garbage
    try:
        if eid == _PIXEL_W and in_video and not st.get("pw"):
            st["pw"] = _ebml_uint(buf[start:end])
        elif eid == _PIXEL_H and in_video and not st.get("ph"):
            st["ph"] = _ebml_uint(buf[start:end])
        elif eid == _DISPLAY_W and in_video and not st.get("dw"):
            st["dw"] = _ebml_uint(buf[start:end])
        elif eid == _DISPLAY_H and in_video and not st.get("dh"):
            st["dh"] = _ebml_uint(buf[start:end])
        elif eid == _DURATION and st.get("dur") is None:
            st["dur"] = _ebml_float(buf[start:end])
        elif eid == _TIMECODESCALE and st.get("scale") is None:
            st["scale"] = _ebml_uint(buf[start:end]) or 1000000
    except Exception:
        pass
    # ⚠️ done sirf tab jab Video element POORA padh liya ho (Display W/H aakhir
    # me aate hain) — Pixel milte hi rukne se Display miss ho jaata tha.
    if st.get("video_done") and st.get("dur") is not None:
        st["done"] = True  # sab mil gaya — aage scan bekaar


def parse_mkv(data):
    """EBML header skip → Segment walk → (w, h, dur|None).

    Display W/H mile to wahi (anamorphic ka asli display size), warna Pixel W/H.
    """
    try:
        end = len(data)
        if end < 16:
            return (0, 0, None)
        r = _read_vint(data, 0, end, True)
        if not r or r[0] != 0x1A45DFA3:
            return (0, 0, None)
        pos = r[1]
        r = _read_vint(data, pos, end, False)
        if not r or r[0] < 0:
            return (0, 0, None)
        pos += r[1] + r[0]  # EBML header skip
        # top-level par Segment dhoondo (beech me Void/CRC ho sakta hai)
        while pos < end:
            r = _read_vint(data, pos, end, True)
            if not r:
                return (0, 0, None)
            eid, ln = r
            pos += ln
            r = _read_vint(data, pos, end, False)
            if not r:
                return (0, 0, None)
            size, ln2 = r
            pos += ln2
            if eid == _SEGMENT:
                seg_end = end if size < 0 else min(pos + size, end)
                st = {"scale": 1000000, "dur": None}
                _walk_ebml(data, pos, seg_end, st)
                dw, dh = st.get("dw", 0), st.get("dh", 0)
                if dw and dh:
                    w, h = dw, dh
                else:
                    w, h = st.get("pw", 0), st.get("ph", 0)
                dur = None
                if st.get("dur"):
                    try:
                        dur = float(st["dur"]) * float(st.get("scale") or 1000000) / 1e9
                    except Exception:
                        dur = None
                return (w or 0, h or 0, dur)
            if size < 0:
                return (0, 0, None)
            if pos + size <= pos:
                return (0, 0, None)  # infinite loop guard
            pos = min(pos + size, end)
    except Exception:
        pass
    return (0, 0, None)


# ─────────────────────────────────────────────────────────
# 📼 AVI  (RIFF)
# ─────────────────────────────────────────────────────────
def _u32le(buf, pos):
    return int.from_bytes(buf[pos:pos + 4], "little")


def _avi_walk(buf, start, end, parent):
    """RIFF chunks walk. Sirf hdrl/strl me ghuso (movi = frames, skip!)."""
    w = h = 0
    dur = None
    strl_vids = False
    pos = start
    while pos + 8 <= end:
        cid = bytes(buf[pos:pos + 4])
        try:
            size = _u32le(buf, pos + 4)
        except Exception:
            break
        ds = pos + 8
        de = min(ds + size, end)
        nxt = de + (size & 1)  # WORD-align pad
        if nxt <= pos or size < 0:
            break
        if cid == b"LIST" and de - ds >= 4:
            lt = bytes(buf[ds:ds + 4])
            if parent == "root" and lt == b"hdrl":
                rw, rh, rd = _avi_walk(buf, ds + 4, de, "hdrl")
            elif parent == "hdrl" and lt == b"strl":
                rw, rh, rd = _avi_walk(buf, ds + 4, de, "strl")
            else:
                rw, rh, rd = 0, 0, None
            if rw and rh and not (w and h):
                w, h = rw, rh
            if rd and dur is None:
                dur = rd
        elif cid == b"avih" and parent in ("hdrl", "root") and de - ds >= 20:
            # avih standard me hdrl ke andar pehla chunk hota hai (root tolerant rakha hai)
            mspf = _u32le(buf, ds)
            frames = _u32le(buf, ds + 16)
            if mspf > 0 and frames > 0:
                dur = frames * mspf / 1e6
        elif cid == b"strh" and parent == "strl" and de - ds >= 4:
            strl_vids = bytes(buf[ds:ds + 4]) == b"vids"
        elif cid == b"strf" and parent == "strl" and strl_vids and de - ds >= 12:
            try:
                ww = int.from_bytes(buf[ds + 4:ds + 8], "little", signed=True)
                hh = int.from_bytes(buf[ds + 8:ds + 12], "little", signed=True)
            except Exception:
                ww = hh = 0
            if ww and hh:
                w, h = abs(ww), abs(hh)  # negative height = top-down, dims same
        pos = min(nxt, end)
    return (w, h, dur)


def parse_avi(data):
    """RIFF/AVI header → (w, h, dur|None)."""
    try:
        end = len(data)
        if end < 32 or bytes(data[0:4]) != b"RIFF" or bytes(data[8:12]) != b"AVI ":
            return (0, 0, None)
        riff_size = _u32le(data, 4)
        list_end = min(12 + riff_size, end)
        return _avi_walk(data, 12, list_end, "root")
    except Exception:
        pass
    return (0, 0, None)


# ─────────────────────────────────────────────────────────
# 🧭 DISPATCHER — magic bytes se parser chuno (pure function)
# ─────────────────────────────────────────────────────────
def _sane_wh(w, h):
    try:
        w, h = int(w), int(h)
    except (TypeError, ValueError):
        return (0, 0)
    if _MIN_W <= w <= _MAX_W and _MIN_H <= h <= _MAX_H:
        return (w, h)
    return (0, 0)


def _sane_dur(dur):
    try:
        d = float(dur)
    except (TypeError, ValueError):
        return None
    if 0 < d <= _MAX_DURATION_SEC:
        return int(round(d))
    return None


def probe_bytes(head, tail=None, file_name=""):
    """Head (+optional tail) bytes se {w, h, duration} — sirf sane findings.

    Returns {} jab kuch na mile (caller Telegram attributes par girta hai).
    Kabhi raise nahi karta — garbage input par bhi sirf {}.
    """
    try:
        if not head or len(head) < 12:
            return {}
        w = h = 0
        dur = None
        if bytes(head[0:4]) == b"RIFF" and bytes(head[8:12]) == b"AVI ":
            w, h, dur = parse_avi(head)
        elif bytes(head[0:4]) == b"\x1a\x45\xdf\xa3":
            w, h, dur = parse_mkv(head)
        elif bytes(head[4:8]) == b"ftyp":
            w, h, dur = parse_mp4(head)
            if (w <= 0 or h <= 0) and tail and len(tail) >= 64:
                w2, h2, dur2 = parse_mp4_tail(tail)
                if w2 > 0 and h2 > 0:
                    w, h = w2, h2
                if dur is None:
                    dur = dur2
        else:
            # magic anjaana — extension hint par ek koshish (bharosa magic par hi)
            ext = ""
            if file_name and "." in str(file_name):
                ext = str(file_name).rsplit(".", 1)[-1].lower()
            if ext in ("mp4", "m4v", "mov"):
                w, h, dur = parse_mp4(head)
                if (w <= 0 or h <= 0) and tail and len(tail) >= 64:
                    w2, h2, dur2 = parse_mp4_tail(tail)
                    if w2 > 0 and h2 > 0:
                        w, h = w2, h2
                    if dur is None:
                        dur = dur2
            elif ext in ("mkv", "webm"):
                w, h, dur = parse_mkv(head)
            elif ext == "avi":
                w, h, dur = parse_avi(head)
            else:
                return {}
    except Exception:
        return {}
    out = {}
    w, h = _sane_wh(w, h)
    if w and h:
        out["w"], out["h"] = w, h
    dur = _sane_dur(dur)
    if dur:
        out["duration"] = dur
    return out


# ─────────────────────────────────────────────────────────
# 📥 MTProto RANGE FETCH — poori file nahi, sirf head/tail
# ─────────────────────────────────────────────────────────
async def fetch_file_range(client, file_ref, file_size, offset_mb, chunks_mb,
                           timeout=FETCH_TIMEOUT):
    """Telegram se [offset_mb, offset_mb+chunks_mb) MB slice lao (max ~cap bytes).

    hydrogram ka public `client.get_file()` use hota hai — DC session + CDN
    redirect sab wahi sambhalta hai. Timeout/partial par jo mila wahi (fail-soft);
    sirf FloodWait caller tak jaata hai (migration ka anti-flood handler pakdega).
    """
    if not client or not file_ref or chunks_mb <= 0:
        return b""
    try:
        from hydrogram.file_id import FileId
        from hydrogram.errors import FloodWait
    except Exception:
        return b""
    try:
        fid = FileId.decode(file_ref)
    except Exception:
        return b""
    out = bytearray()
    cap = chunks_mb * 1024 * 1024
    try:
        async def _collect():
            async for chunk in client.get_file(
                fid, file_size=file_size or 0,
                limit=chunks_mb, offset=offset_mb,
            ):
                if not chunk:
                    break
                out.extend(chunk)
                if len(out) >= cap:
                    break
        await asyncio.wait_for(_collect(), timeout=timeout)
    except FloodWait:
        raise
    except Exception as e:
        logger.debug(f"[PROBE] range fetch fail (offset={offset_mb}MB): {str(e)[:80]}")
    return bytes(out)


# ─────────────────────────────────────────────────────────
# 🛟 FFPROBE FALLBACK — rare containers (TS/FLV/WMV/...) ke liye
# ─────────────────────────────────────────────────────────
def _ffprobe_available():
    try:
        return shutil.which("ffprobe") is not None
    except Exception:
        return False


def ffprobe_head(head):
    """Head bytes par ffprobe (sirf jab pure parsers haar jaayein).

    Returns probe_bytes() jaisa dict ya {}. Binary na mile / timeout / garbage
    — har haal me {} (caller attributes par girta hai).
    """
    if not head or len(head) < 1024 or not _ffprobe_available():
        return {}
    try:
        proc = subprocess.run(
            ["ffprobe", "-v", "error", "-print_format", "json",
             "-show_format", "-show_streams", "-probesize", str(len(head)),
             "-analyzeduration", "2000000", "-i", "pipe:0"],
            input=bytes(head), capture_output=True, timeout=FFPROBE_TIMEOUT,
        )
    except Exception:
        return {}
    try:
        if proc.returncode != 0 or not proc.stdout:
            return {}
        info = json.loads(proc.stdout.decode("utf-8", "replace"))
    except Exception:
        return {}
    out = {}
    try:
        for stream in info.get("streams", []) or []:
            if stream.get("codec_type") != "video":
                continue
            w = int(stream.get("width") or 0)
            h = int(stream.get("height") or 0)
            # portrait clips: ffprobe coded dims + rotate tag deta hai
            try:
                rot = int(float((stream.get("tags") or {}).get("rotate", 0)))
            except (TypeError, ValueError):
                rot = 0
            if rot in (90, 270):
                w, h = h, w
            w, h = _sane_wh(w, h)
            if w and h:
                out["w"], out["h"] = w, h
            break  # pehla video stream hi chahiye
        dur = (info.get("format") or {}).get("duration")
        dur = _sane_dur(dur)
        if dur:
            out["duration"] = dur
    except Exception:
        pass
    return out


# ─────────────────────────────────────────────────────────
# 🎯 MAIN ENTRY — ek Telegram file ka sach (w/h/duration)
# ─────────────────────────────────────────────────────────
async def probe_telegram_file(client, file_ref, file_size=0, file_name="",
                              head_mb=HEAD_MB, tail_mb=TAIL_MB):
    """Poora probe-pipeline: head fetch → pure parsers → (mp4: tail) → ffprobe.

    Returns {'w','h'[,'duration']} (sirf sane values) ya {} — {} ka matlab
    "pata nahi chala, Telegram attributes use karo". FloodWait re-raise hota hai,
    baaki har error andar hi dab jaata hai (migration/backfill kabhi na ruke).
    """
    if not client or not file_ref:
        return {}
    try:
        from hydrogram.errors import FloodWait
    except Exception:
        FloodWait = ()  # pragma: no cover — hydrogram hamesha hota hai
    try:
        head = await fetch_file_range(client, file_ref, file_size, 0, head_mb)
    except FloodWait:
        raise
    except Exception:
        return {}
    if not head:
        return {}
    out = probe_bytes(head, None, file_name)
    if out.get("w") and out.get("h"):
        return out
    # MP4 jisme head me moov na mila (moov-at-end) → tail fetch karke dekho
    tail = None
    try:
        is_mp4 = len(head) >= 12 and bytes(head[4:8]) == b"ftyp"
        if not is_mp4 and file_name and "." in str(file_name):
            is_mp4 = str(file_name).rsplit(".", 1)[-1].lower() in ("mp4", "m4v", "mov")
        if is_mp4 and file_size and file_size > (head_mb + 1) * 1024 * 1024:
            total_mb = max(int(file_size) // (1024 * 1024), 1)
            tail_off = max(0, total_mb - tail_mb)
            try:
                tail = await fetch_file_range(
                    client, file_ref, file_size, tail_off, tail_mb)
            except FloodWait:
                raise
            except Exception:
                tail = None
            if tail:
                out2 = probe_bytes(head, tail, file_name)
                if out2.get("w") and out2.get("h"):
                    return out2
                # dims na mile par duration mil gayi ho to use rakho
                if out2.get("duration") and not out.get("duration"):
                    out["duration"] = out2["duration"]
    except FloodWait:
        raise
    except Exception as e:
        logger.debug(f"[PROBE] tail pass fail: {str(e)[:80]}")
    if out.get("w") and out.get("h"):
        return out
    # aakhri koshish: ffprobe (TS/FLV/WMV ya tedhe headers ke liye)
    try:
        fb = await asyncio.get_running_loop().run_in_executor(None, ffprobe_head, head)
    except Exception:
        fb = {}
    if fb.get("w") and fb.get("h"):
        # ffprobe dims + (pure-parser duration behtar ho to wahi)
        if out.get("duration") and not fb.get("duration"):
            fb["duration"] = out["duration"]
        return fb
    if fb.get("duration") and not out.get("duration"):
        out["duration"] = fb["duration"]
    return out
