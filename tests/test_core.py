"""
Core-logic regression tests.

Ye suite un pure/deterministic functions ko cover karti hai jinhe refactor ke
dauraan chheda gaya hai — taaki "bug hatao / code optimize karo" wale changes
ko objectively verify kiya ja sake (MongoDB/Telegram connection ki zaroorat
nahi, sab mock/stub hai).

Run:  python -m unittest discover -s tests -v
"""
import os
import sys
import inspect
import unittest

# ── info.py ko import-time validation se bachane ke liye env stubs ──
os.environ.setdefault("API_ID", "123456")
os.environ.setdefault("API_HASH", "test_hash")
os.environ.setdefault("BOT_TOKEN", "123456:test_token")
os.environ.setdefault("ADMINS", "111 222")
os.environ.setdefault("LOG_CHANNEL", "-1001234567890")
os.environ.setdefault("BIN_CHANNEL", "-1009876543210")
os.environ.setdefault("DATABASE_URL", "mongodb://localhost:27017")
os.environ.setdefault("DATABASE_NAME", "testdb")
os.environ.setdefault("URL", "https://example.com")
os.environ.setdefault("TIME_ZONE", "Asia/Kolkata")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestTimeParsing(unittest.TestCase):
    """utils.get_seconds — duration string parser (bot /dlink delay ke liye)."""

    def test_shorthand_units(self):
        from utils import get_seconds
        import asyncio
        cases = {
            "1s": 1, "30sec": 30,
            "1m": 60, "5min": 300, "2 min": 120,
            "1h": 3600, "2hr": 7200, "3 hour": 10800,
            "1d": 86400, "2day": 172800,
            "1mo": 2592000, "2month": 5184000,
            "1y": 31536000, "1year": 31536000,
        }
        for text, expected in cases.items():
            with self.subTest(text=text):
                self.assertEqual(asyncio.run(get_seconds(text)), expected)

    def test_invalid_returns_zero(self):
        from utils import get_seconds
        import asyncio
        for text in ("", "abc", "hour", "10 fortnights", None if False else "  "):
            with self.subTest(text=text):
                self.assertEqual(asyncio.run(get_seconds(text)), 0)

    def test_longer_words_not_split_as_prefix(self):
        """"1month" ko "1m" ki tarah 60s nahi maan lena chahiye."""
        from utils import get_seconds
        import asyncio
        self.assertEqual(asyncio.run(get_seconds("1month")), 2592000)
        self.assertEqual(asyncio.run(get_seconds("1hour")), 3600)


class TestFormatting(unittest.TestCase):
    def test_get_size(self):
        from utils import get_size
        self.assertEqual(get_size(0), "0.00 Bytes")
        self.assertEqual(get_size(1024), "1.00 KB")
        self.assertEqual(get_size(1024 ** 2), "1.00 MB")
        self.assertEqual(get_size(1536), "1.50 KB")
        # TB se aage unit overflow na ho
        self.assertEqual(get_size(1024 ** 5), "1024.00 TB")

    def test_get_readable_time(self):
        from utils import get_readable_time
        self.assertEqual(get_readable_time(0), "0s")
        self.assertEqual(get_readable_time(59), "59s")
        self.assertEqual(get_readable_time(60), "1m")
        self.assertEqual(get_readable_time(3661), "1h 1m 1s")
        self.assertEqual(get_readable_time(90061), "1d 1h 1m 1s")

    def test_get_wish_is_non_empty(self):
        from utils import get_wish
        self.assertTrue(get_wish())


class TestPremiumPlanDefaults(unittest.TestCase):
    """Premium reset-state dict ab ek hi jagah define hota hai."""

    def test_single_source_of_truth(self):
        from database.users_chats_db import DEFAULT_PLAN_STATUS, db
        from utils import RESET_PLAN_STATUS
        self.assertEqual(RESET_PLAN_STATUS, DEFAULT_PLAN_STATUS)
        # Database.df_prm bhi wahi base use kare (trial ke saath)
        for key in ("premium", "expire", "plan", "last_reminder_id"):
            self.assertIn(key, db.df_prm)
        self.assertIn("trial", db.df_prm)

    def test_reset_status_marks_inactive(self):
        from database.users_chats_db import DEFAULT_PLAN_STATUS
        self.assertFalse(DEFAULT_PLAN_STATUS["premium"])
        self.assertIsNone(DEFAULT_PLAN_STATUS["expire"])
        self.assertEqual(DEFAULT_PLAN_STATUS["plan"], "")
        for flag in ("12h", "6h", "3h", "1h", "30m", "10m"):
            self.assertFalse(DEFAULT_PLAN_STATUS[f"reminded_{flag}"])

    def test_copies_are_independent(self):
        """Shared dict ko mutate karke global state kharab na ho."""
        from database.users_chats_db import DEFAULT_PLAN_STATUS
        snapshot = dict(DEFAULT_PLAN_STATUS)
        copy = dict(DEFAULT_PLAN_STATUS)
        copy["premium"] = True
        copy["plan"] = "30 Days"
        self.assertEqual(DEFAULT_PLAN_STATUS, snapshot)


class TestRegexBuilder(unittest.TestCase):
    """ia_filterdb._build_regex — short-query shield."""

    def test_short_queries_rejected(self):
        from database.ia_filterdb import _build_regex
        self.assertIsNone(_build_regex(""))
        self.assertIsNone(_build_regex("  "))
        self.assertIsNone(_build_regex("a"))
        # 2-char jo allowlist me nahi
        self.assertIsNone(_build_regex("zz"))

    def test_allowed_short_terms_accepted(self):
        from database.ia_filterdb import _build_regex
        for term in ("4k", "hd", "3d", "8k", "rr", "kg"):
            with self.subTest(term=term):
                self.assertIsNotNone(_build_regex(term))

    def test_multiword_and_boundaries(self):
        from database.ia_filterdb import _build_regex
        rx = _build_regex("avengers endgame")
        self.assertIsNotNone(rx)
        self.assertTrue(rx.search("Avengers.Endgame.2019"))
        self.assertTrue(rx.search("the avengers endgame 1080p"))

    def test_single_word_needs_boundary(self):
        from database.ia_filterdb import _build_regex
        rx = _build_regex("avengers")
        self.assertTrue(rx.search("Avengers.2012.1080p"))
        # regex special chars escape hone chahiye (crash/galat match nahi)
        self.assertIsNotNone(_build_regex("a+b.c"))
        self.assertIsNotNone(_build_regex("(2020)"))


class TestFileIdCodec(unittest.TestCase):
    def test_encode_decode_roundtrip_is_stable(self):
        from database.ia_filterdb import encode_file_id, unpack_new_file_id
        # Real-looking hydrogram video file_id
        fid = "BAACAgUAAxkBAAIBZ2mF7QABYQACAgAD"
        out = unpack_new_file_id(fid)
        if out is not None:  # decode ho gaya to re-encode deterministic hona chahiye
            self.assertEqual(out, unpack_new_file_id(fid))
        self.assertIsInstance(encode_file_id(b"\x00\x00\x01\x02"), str)

    def test_bad_file_id_returns_none(self):
        from database.ia_filterdb import unpack_new_file_id
        self.assertIsNone(unpack_new_file_id("not-a-valid-file-id!!!"))


class TestStreamingMath(unittest.TestCase):
    """web/utils/custom_dl chunk math + HTTP Range parsing."""

    def test_chunk_size_is_power_of_two_kb(self):
        from web.utils.custom_dl import chunk_size
        for length in (1024, 5 * 1024, 10 ** 6, 10 ** 9, 4 * 10 ** 9):
            with self.subTest(length=length):
                cs = chunk_size(length)
                self.assertGreaterEqual(cs, 4 * 1024)
                self.assertLessEqual(cs, 1024 * 1024)
                self.assertEqual(cs % 1024, 0)
                self.assertEqual(cs & (cs - 1), 0, "chunk size 2 ki power hona chahiye")

    def test_offset_fix_aligns_down(self):
        from web.utils.custom_dl import offset_fix, chunk_size
        cs = chunk_size(10 ** 7)
        self.assertEqual(offset_fix(0, cs), 0)
        self.assertEqual(offset_fix(cs, cs), cs)
        self.assertEqual(offset_fix(cs + 1, cs), cs)
        self.assertEqual(offset_fix(cs - 1, cs), 0)

    def test_range_parse_helper(self):
        """Range header parsing ka extracted helper."""
        from web.stream_routes import parse_range
        size = 1000
        self.assertEqual(parse_range(None, size), (0, 999, 1000, False))
        self.assertEqual(parse_range("bytes=0-499", size), (0, 499, 500, True))
        self.assertEqual(parse_range("bytes=500-", size), (500, 999, 500, True))
        self.assertEqual(parse_range("bytes=-", size), (0, 999, 1000, True))
        # clamp: upper bound file size se aage na jaaye
        self.assertEqual(parse_range("bytes=0-99999", size), (0, 999, 1000, True))
        # invalid / unsatisfiable -> None
        self.assertIsNone(parse_range("bytes=2000-3000", size))
        self.assertIsNone(parse_range("bytes=500-100", size))
        # garbage header crash na kare. NOTE: pehle yeh case 206 (partial) deta tha
        # kyunki `r_head` truthy tha — RFC ke hisaab se galat, kyunki Range parse hi
        # nahi hua. Ab full content (200) jaata hai, jo zyada sahi hai.
        self.assertEqual(parse_range("garbage", size), (0, 999, 1000, False))


class TestSearchQueryFilters(unittest.TestCase):
    """ia_filterdb query-filter builder (text + regex + lang)."""

    def test_text_filter_for_normal_query(self):
        from database.ia_filterdb import build_query_filter
        flt, is_text = build_query_filter("avengers endgame", None, None)
        self.assertTrue(is_text)
        self.assertIn("$text", flt)
        self.assertEqual(flt["$text"]["$search"], '"avengers" "endgame"')

    def test_regex_fallback_when_no_words(self):
        from database.ia_filterdb import build_query_filter, _build_regex
        rx = _build_regex("4k")
        flt, is_text = build_query_filter("", rx, None)
        self.assertFalse(is_text)
        self.assertIn("$or", flt)

    def test_lang_filter_wraps_with_and(self):
        from database.ia_filterdb import build_query_filter
        flt, _ = build_query_filter("avengers", None, "hindi")
        self.assertIn("$and", flt)
        self.assertEqual(len(flt["$and"]), 2)

    def test_empty_query_gives_none(self):
        from database.ia_filterdb import build_query_filter
        flt, is_text = build_query_filter("", None, None)
        self.assertIsNone(flt)

    def test_quotes_stripped(self):
        from database.ia_filterdb import build_query_filter
        flt, _ = build_query_filter('"avengers"', None, None)
        self.assertEqual(flt["$text"]["$search"], '"avengers"')


class _FakeCursor:
    def __init__(self, docs): self._d = docs
    def sort(self, *a, **k): return self
    def skip(self, *a, **k): return self
    def limit(self, *a, **k): return self
    async def to_list(self, length=None): return [dict(x) for x in self._d]


class _FakeCol:
    """Motor collection ka minimal stand-in (text vs regex branch alag docs deta hai)."""
    name = "Primary"

    def __init__(self, text_docs, regex_docs, count):
        self.text_docs, self.regex_docs, self.count = text_docs, regex_docs, count
        self.filters = []

    def find(self, flt, proj):
        self.filters.append(flt)
        is_text = "$text" in flt or "$and" in flt
        return _FakeCursor(self.text_docs if is_text else self.regex_docs)

    async def count_documents(self, flt): return self.count


class TestSearchFallthrough(unittest.TestCase):
    """
    _search() refactor ka riskiest hissa: text-search khali aane par regex fallback
    chalna chahiye, aur dono na bane to safely khali return hona chahiye.
    """
    DOC = {"_id": "F1", "file_name": "Avengers 2012", "file_size": 100}

    def _run(self, *a, **k):
        import asyncio
        from database.ia_filterdb import _search
        return asyncio.run(_search(*a, **k))

    def test_text_hit_returns_immediately(self):
        from database.ia_filterdb import _build_regex
        col = _FakeCol([self.DOC], [], 7)
        docs, cnt = self._run(col, "avengers", _build_regex("avengers"), 0, 10)
        self.assertEqual(len(docs), 1)
        self.assertEqual(cnt, 7)
        # UI/JSON ke liye file_id + source_col tag hona zaroori hai
        self.assertEqual(docs[0]["file_id"], "F1")
        self.assertEqual(docs[0]["source_col"], "primary")
        self.assertEqual(len(col.filters), 1, "text hit par regex query nahi chalni chahiye")

    def test_empty_text_falls_back_to_regex(self):
        from database.ia_filterdb import _build_regex
        col = _FakeCol([], [self.DOC], 3)
        docs, cnt = self._run(col, "avengers", _build_regex("avengers"), 0, 10)
        self.assertEqual(len(docs), 1)
        self.assertEqual(cnt, 3)
        self.assertEqual(len(col.filters), 2, "text miss ke baad regex query chalni chahiye")

    def test_empty_text_and_no_regex_is_safe(self):
        col = _FakeCol([], [], 0)
        docs, cnt = self._run(col, "avengers", None, 0, 10)
        self.assertEqual((docs, cnt), ([], 0))

    def test_pure_regex_path(self):
        from database.ia_filterdb import _build_regex
        col = _FakeCol([], [self.DOC], 5)
        docs, cnt = self._run(col, "", _build_regex("4k"), 0, 10)
        self.assertEqual((len(docs), cnt), (1, 5))

    def test_nothing_usable_is_safe(self):
        col = _FakeCol([], [], 0)
        self.assertEqual(self._run(col, "", None, 0, 10), ([], 0))

    def test_bypass_count_skips_counting(self):
        col = _FakeCol([self.DOC], [], 99)
        docs, cnt = self._run(col, "avengers", None, 0, 10, bypass_count=True)
        self.assertEqual(len(docs), 1)
        self.assertEqual(cnt, 0)


class TestSuggestionDedupe(unittest.TestCase):
    def test_dedupe_case_insensitive_and_limit(self):
        from database.ia_filterdb import _dedupe_titles
        docs = [
            {"file_name": "Avengers 2012"},
            {"file_name": "avengers 2012"},
            {"file_name": "  Avengers   2012 "},
            {"file_name": "Avengers Endgame"},
            {"file_name": ""},
        ]
        out = _dedupe_titles(docs, limit=5, seen={"other"})
        self.assertEqual(out, ["Avengers 2012", "Avengers Endgame"])

    def test_respects_seen_and_limit(self):
        from database.ia_filterdb import _dedupe_titles
        docs = [{"file_name": f"Title {i}"} for i in range(10)]
        self.assertEqual(len(_dedupe_titles(docs, limit=3, seen=set())), 3)
        self.assertEqual(_dedupe_titles([{"file_name": "Title 1"}], limit=5, seen={"title 1"}), [])

    def test_whitespace_normalized_not_lowercased(self):
        from database.ia_filterdb import _clean_title_guess
        self.assertEqual(_clean_title_guess("  A   b  "), "A b")
        self.assertEqual(_clean_title_guess(""), "")


class TestRuntimeState(unittest.TestCase):
    """temp runtime buckets ab class-level declared hain (hasattr guards nahi)."""

    def test_all_buckets_declared(self):
        from utils import temp
        for name in ("BANNED_USERS", "BANNED_CHATS", "ADMIN_TOKENS", "ADMIN_SESSIONS",
                     "FILES", "PM_FILES", "USER_SESSIONS", "REG_PENDING"):
            with self.subTest(name=name):
                self.assertTrue(hasattr(temp, name), f"temp.{name} declared hona chahiye")

    def test_rate_limiter_blocks_then_allows(self):
        import utils
        utils._rate_limits.clear()
        self.assertFalse(utils.is_rate_limited(1, "act", 60))
        self.assertTrue(utils.is_rate_limited(1, "act", 60))
        # doosra action independent
        self.assertFalse(utils.is_rate_limited(1, "other", 60))
        # doosra user independent
        self.assertFalse(utils.is_rate_limited(2, "act", 60))
        # expiry ke baad allow
        utils._rate_limits["1:act"] -= 61
        self.assertFalse(utils.is_rate_limited(1, "act", 60))
        utils._rate_limits.clear()

    def test_settings_cache_bounded(self):
        import utils
        self.assertGreater(utils._CACHE_TTL, 0)


class TestNoDuplicateRegistrations(unittest.TestCase):
    """
    Regression guard: pehle do alag files me `^close_` callback handler aur do
    jagah `/health` route register the — dono hi chalte/register hote the.
    """

    @staticmethod
    def _plugin_handlers(pattern):
        """
        hydrogram ka class-level decorator har function par `func.handlers` list
        laga deta hai (Client instance banne par wahi register hote hain). Isliye
        plugin modules ke saare functions scan karke matching pattern ginte hain.
        """
        import inspect
        import plugins.commands as cmd
        import plugins.filter as flt

        found = []
        for mod in (cmd, flt):
            for name, obj in vars(mod).items():
                if not inspect.isfunction(obj):
                    continue
                for handler, _group in getattr(obj, "handlers", []):
                    flt_obj = handler.filters
                    # hydrogram RegexFilter apna compiled pattern `.p` me rakhta hai
                    compiled = getattr(flt_obj, "p", None)
                    if getattr(compiled, "pattern", None) == pattern:
                        found.append(f"{mod.__name__}.{name}")
        return found

    def test_single_close_callback_handler(self):
        handlers = self._plugin_handlers("^close_")
        self.assertEqual(len(handlers), 1,
                         f"`^close_` par ek hi handler hona chahiye, mile: {handlers}")
        self.assertIn("plugins.filter.close_callback", handlers)

    def test_single_health_route(self):
        from web import web_app
        # aiohttp har GET route ke saath HEAD bhi register karta hai, isliye route
        # count nahi — distinct handler count dekhte hain.
        handlers = {r.handler for r in web_app.router.routes()
                    if getattr(r, "resource", None) and r.resource.canonical == "/health"}
        self.assertEqual(len(handlers), 1,
                         f"/health par ek hi handler hona chahiye, mile: {handlers}")
        # aur wo handler web layer ka ho (bot.py wala dead copy hata diya gaya hai)
        self.assertEqual(list(handlers)[0].__module__, "web.dashboard_routes")


class TestSharedWebHelpers(unittest.TestCase):
    def test_fast_json_single_definition(self):
        from web.web_assets import fast_json
        from web import search_api, actor_routes, post_routes
        for mod in (search_api, actor_routes, post_routes):
            with self.subTest(mod=mod.__name__):
                self.assertIs(mod.fast_json, fast_json,
                              "fast_json shared definition se aana chahiye")

    def test_fast_json_output(self):
        from web.web_assets import fast_json
        self.assertEqual(fast_json({"a": 1}), '{"a":1}')
        self.assertEqual(fast_json([1, 2]), "[1,2]")


class TestStatsHelpers(unittest.TestCase):
    """Directory/post counts ab ek shared helper se aate hain (parallel)."""

    def test_post_category_counts_shape(self):
        import asyncio
        from unittest import mock
        import database.ia_filterdb as fdb

        class FakeCursor:
            def __init__(self, docs): self._docs = docs
            def __aiter__(self): return self._gen()
            async def _gen(self):
                for d in self._docs: yield d

        docs = [{"_id": "Movies", "count": 3}, {"_id": "Web Series", "count": 2}]
        with mock.patch.object(fdb, "posts") as m:
            m.aggregate.return_value = FakeCursor(docs)
            total, movies, series, appvid, porn = asyncio.run(fdb.get_post_category_counts())
        self.assertEqual((total, movies, series, appvid, porn), (5, 3, 2, 0, 0))

    def test_directory_counts_parallel(self):
        import asyncio
        from unittest import mock
        import database.ia_filterdb as fdb

        async def fake_count(query=None, *a, **k):
            if not query: return 10
            if query.get("category") == "app": return 3
            if query.get("category") == "website": return 2
            return 0

        with mock.patch.object(fdb, "actors") as m:
            m.count_documents.side_effect = fake_count
            tot, act, app, web = asyncio.run(fdb.get_directory_counts())
        self.assertEqual((tot, act, app, web), (10, 5, 3, 2))

    def test_directory_counts_failure_is_safe(self):
        import asyncio
        from unittest import mock
        import database.ia_filterdb as fdb
        with mock.patch.object(fdb, "actors") as m:
            m.count_documents.side_effect = RuntimeError("db down")
            self.assertEqual(asyncio.run(fdb.get_directory_counts()), (0, 0, 0, 0))


class TestIndexPluginHelpers(unittest.TestCase):
    def test_status_text_contains_all_counters(self):
        from plugins.index import index_status_text
        txt = index_status_text("primary", "1m 2s", current=100, saved=80, duplicate=5,
                                deleted=3, no_media=4, unsupported=2, errors=6, badfiles=7)
        for needle in ("PRIMARY", "1m 2s", "100", "80", "5", "3", "2", "6", "7"):
            self.assertIn(needle, txt)
        # no_media + unsupported ek hi line me jud kar dikhta hai (4 + 2 = 6)
        self.assertIn("No Media: <code>6</code>", txt)

    def test_collection_picker_lists_three_collections(self):
        from plugins.index import collection_picker_markup
        markup = collection_picker_markup("-1001", 500, 0)
        flat = [b for row in markup.inline_keyboard for b in row]
        labels = " ".join(b.text for b in flat)
        for word in ("PRIMARY", "CLOUD", "ARCHIVES", "CANCEL"):
            self.assertIn(word, labels)
        starts = [b.callback_data for b in flat if b.callback_data.startswith("index#start#")]
        self.assertEqual(len(starts), 3)


class TestCommandsStatsPayload(unittest.TestCase):
    def test_stats_payload_matches_script_placeholders(self):
        import asyncio
        from unittest import mock
        import plugins.commands as cmds
        from Script import script

        counts = {"total": 100, "primary": 60, "primary_thumb": 10, "cloud": 30,
                  "cloud_thumb": 5, "archive": 10, "archive_thumb": 1, "total_thumb": 16}

        async def run():
            with mock.patch.object(cmds, "db_count_documents", return_value=counts), \
                 mock.patch.object(cmds, "get_directory_counts", return_value=(9, 6, 2, 1)), \
                 mock.patch.object(cmds, "get_post_category_counts", return_value=(7, 3, 2, 1, 1)), \
                 mock.patch.object(cmds.db, "total_users_count", return_value=11), \
                 mock.patch.object(cmds.db, "total_chat_count", return_value=4), \
                 mock.patch.object(cmds.db, "get_premium_users_count", return_value=2):
                return await cmds.build_stats_texts()

        admin_txt, user_txt = asyncio.run(run())
        # STATUS_TXT me 21 placeholders hain — format crash na ho aur values aayen
        self.assertIn("100", admin_txt)
        self.assertIn("11", admin_txt)
        self.assertIn("9", admin_txt)
        self.assertIn("100", user_txt)
        self.assertEqual(script.STATUS_TXT.count("{}"), 21)
        self.assertEqual(script.USER_STATUS_TXT.count("{}"), 10)


class TestPremiumTimeHelpers(unittest.TestCase):
    def test_parse_expire_time(self):
        from utils import parse_expire_time
        from datetime import datetime
        self.assertIsNone(parse_expire_time(None))
        self.assertIsNone(parse_expire_time("garbage"))
        self.assertEqual(parse_expire_time("2030-01-02 03:04:05"), datetime(2030, 1, 2, 3, 4, 5))
        d = datetime(2030, 1, 1)
        self.assertIs(parse_expire_time(d), d)

    def test_format_plan_expiry(self):
        from plugins.premium import format_plan_expiry
        from datetime import datetime
        self.assertEqual(format_plan_expiry(None), "Unknown")
        self.assertEqual(format_plan_expiry(datetime(2030, 1, 2, 3, 4, 5)), "02 January 2030, 03:04 AM")


class TestRoleResolution(unittest.TestCase):
    def test_admin_short_circuits(self):
        import asyncio
        from unittest import mock
        from web.search_api import _resolve_role_for_tg
        with mock.patch("web.search_api.is_premium") as m:
            self.assertEqual(asyncio.run(_resolve_role_for_tg(111)), "admin")
            m.assert_not_called()

    def test_premium_user_and_expired(self):
        import asyncio
        from unittest import mock
        from web.search_api import _resolve_role_for_tg

        async def yes(*a, **k): return True
        async def no(*a, **k): return False

        with mock.patch("web.search_api.is_premium", side_effect=yes), \
             mock.patch("web.search_api.IS_PREMIUM", True):
            self.assertEqual(asyncio.run(_resolve_role_for_tg(999)), "user")

        with mock.patch("web.search_api.is_premium", side_effect=no), \
             mock.patch("web.search_api.IS_PREMIUM", True):
            self.assertIsNone(asyncio.run(_resolve_role_for_tg(999)))

        # premium system off hone par sabko access
        with mock.patch("web.search_api.is_premium", side_effect=no), \
             mock.patch("web.search_api.IS_PREMIUM", False):
            self.assertEqual(asyncio.run(_resolve_role_for_tg(999)), "user")


class TestStreamTunnelHelper(unittest.TestCase):
    def test_stream_path_selection(self):
        from web.search_api import stream_target_path
        self.assertEqual(stream_target_path(5, "watch"), "/watch/5")
        self.assertEqual(stream_target_path(5, "download"), "/download/5")
        # unknown mode -> watch (default), crash nahi
        self.assertEqual(stream_target_path(7, "weird"), "/watch/7")


class TestHomepageRobustness(unittest.TestCase):
    """
    Regression: `getattr(temp, 'U_NAME', 'AutoFilterBot')` ka default kabhi apply
    nahi hota tha (temp.U_NAME class me None declared hai), isliye bot client start
    hone se pehle `/` homepage TypeError dekar 500 crash karta tha.
    """

    def test_homepage_survives_unset_bot_username(self):
        import asyncio
        from unittest import mock
        from utils import temp
        from web.stream_routes import root_route_handler

        with mock.patch.object(temp, "U_NAME", None):
            req = mock.MagicMock()
            resp = asyncio.run(root_route_handler(req))
        self.assertEqual(resp.status, 200)
        self.assertIn("AutoFilterBot", resp.text)

    def test_homepage_uses_real_username_when_set(self):
        import asyncio
        from unittest import mock
        from utils import temp
        from web.stream_routes import root_route_handler

        with mock.patch.object(temp, "U_NAME", "MyRealBot"):
            req = mock.MagicMock()
            resp = asyncio.run(root_route_handler(req))
        self.assertEqual(resp.status, 200)
        self.assertIn("MyRealBot", resp.text)


class TestHealthEndpoint(unittest.TestCase):
    def test_single_handler_reports_uptime(self):
        import asyncio
        import json
        from unittest import mock
        from utils import temp
        from web.dashboard_routes import koyeb_health_check

        with mock.patch.object(temp, "START_TIME", 1000.0), \
             mock.patch("web.dashboard_routes.time.time", return_value=1042.5):
            resp = asyncio.run(koyeb_health_check(mock.MagicMock()))
        data = json.loads(resp.text)
        self.assertEqual(data["status"], "alive")
        self.assertEqual(data["uptime_seconds"], 42.5)


class TestDurationFormatting(unittest.TestCase):
    """Video duration -> media-player style string (sirf web UI ke liye)."""

    def test_missing_and_zero_give_empty(self):
        from utils import get_duration_str
        for bad in (None, 0, "", "abc", -5, []):
            with self.subTest(bad=bad):
                self.assertEqual(get_duration_str(bad), "")

    def test_seconds_only(self):
        from utils import get_duration_str
        self.assertEqual(get_duration_str(1), "0:01")
        self.assertEqual(get_duration_str(9), "0:09")
        self.assertEqual(get_duration_str(59), "0:59")

    def test_minutes_padded_seconds(self):
        from utils import get_duration_str
        self.assertEqual(get_duration_str(60), "1:00")
        self.assertEqual(get_duration_str(754), "12:34")
        self.assertEqual(get_duration_str(3599), "59:59")

    def test_hours_format(self):
        from utils import get_duration_str
        self.assertEqual(get_duration_str(3600), "1:00:00")
        self.assertEqual(get_duration_str(3723), "1:02:03")
        self.assertEqual(get_duration_str(2 * 3600 + 5 * 60 + 7), "2:05:07")
        # 10 ghante se zyada par bhi sahi
        self.assertEqual(get_duration_str(12 * 3600 + 34 * 60 + 56), "12:34:56")

    def test_accepts_string_and_float(self):
        from utils import get_duration_str
        self.assertEqual(get_duration_str("3723"), "1:02:03")
        self.assertEqual(get_duration_str(3723.9), "1:02:03")

    def test_differs_from_readable_time(self):
        """get_readable_time (uptime) aur get_duration_str (video) alag formats hain."""
        from utils import get_readable_time, get_duration_str
        self.assertEqual(get_readable_time(3723), "1h 2m 3s")
        self.assertEqual(get_duration_str(3723), "1:02:03")


class TestDurationInApiResponse(unittest.TestCase):
    """Web search API ke JSON me duration field aana chahiye (bot messages me nahi)."""

    def test_duration_exposed_in_results(self):
        from web.search_api import _build_results_list
        docs = [{"_id": "F1", "file_ref": "R1", "file_name": "Movie 2020",
                 "file_size": 1048576, "file_type": "video", "duration": 7260,
                 "source_col": "primary", "thumb_url": ""}]
        out = _build_results_list(docs, "tg")[0]
        self.assertEqual(out["duration"], "2:01:00")

    def test_missing_duration_gives_empty_not_zero(self):
        from web.search_api import _build_results_list
        # purani files me duration field hi nahi hai
        docs = [{"_id": "F2", "file_ref": "R2", "file_name": "Old Movie",
                 "file_size": 100, "file_type": "video", "source_col": "cloud",
                 "thumb_url": ""}]
        out = _build_results_list(docs, "tg")[0]
        self.assertEqual(out["duration"], "")

    def test_document_without_duration_is_empty(self):
        from web.search_api import _build_results_list
        docs = [{"_id": "F3", "file_ref": "R3", "file_name": "book.pdf",
                 "file_size": 100, "file_type": "document", "duration": 0,
                 "source_col": "primary", "thumb_url": ""}]
        self.assertEqual(_build_results_list(docs, "tg")[0]["duration"], "")

    def test_text_mode_also_has_duration(self):
        from web.search_api import _build_results_list
        docs = [{"_id": "F4", "file_ref": "R4", "file_name": "Ep 01",
                 "file_size": 100, "file_type": "video", "duration": 1500,
                 "source_col": "archive", "thumb_url": ""}]
        self.assertEqual(_build_results_list(docs, "none")[0]["duration"], "25:00")


class TestDurationStorage(unittest.TestCase):
    """Indexing ke waqt duration DB me save hona chahiye."""

    def test_save_file_persists_duration(self):
        import asyncio
        from unittest import mock
        import database.ia_filterdb as fdb

        class FakeMedia:
            file_id = "CQADtest"
            file_name = "Movie_2020.mp4"
            caption = None
            file_size = 12345
            duration = 7260

        captured = {}

        class FakeCol:
            async def find_one(self, *a, **k): return None
            async def update_one(self, flt, payload, **k):
                captured.update(payload)

        with mock.patch.object(fdb, "unpack_new_file_id", return_value="ABC123"), \
             mock.patch.object(fdb, "COLLECTIONS", {"primary": FakeCol()}):
            # FakeMedia ka class-name lowercase 'fakemedia' banta hai — file_type ke liye theek
            result = asyncio.run(fdb.save_file(FakeMedia(), "primary"))

        self.assertEqual(result, "suc")
        self.assertEqual(captured["$set"]["duration"], 7260)
        self.assertEqual(captured["$set"]["file_size"], 12345)

    def test_save_file_without_duration_attr_is_zero(self):
        """Document par .duration hota hi nahi — crash nahi hona chahiye."""
        import asyncio
        from unittest import mock
        import database.ia_filterdb as fdb

        class FakeDoc:
            file_id = "CQADtest"
            file_name = "book.pdf"
            caption = None
            file_size = 999

        captured = {}

        class FakeCol:
            async def find_one(self, *a, **k): return None
            async def update_one(self, flt, payload, **k):
                captured.update(payload)

        with mock.patch.object(fdb, "unpack_new_file_id", return_value="ABC999"), \
             mock.patch.object(fdb, "COLLECTIONS", {"primary": FakeCol()}):
            result = asyncio.run(fdb.save_file(FakeDoc(), "primary"))

        self.assertEqual(result, "suc")
        self.assertEqual(captured["$set"]["duration"], 0)

    def test_projection_includes_duration(self):
        from database.ia_filterdb import FILE_PROJECTION, FILE_PROJECTION_SCORED
        self.assertEqual(FILE_PROJECTION.get("duration"), 1)
        self.assertEqual(FILE_PROJECTION_SCORED.get("duration"), 1)


class TestDurationBackfill(unittest.TestCase):
    """Purani files: thumbnail fetch ke waqt duration free me backfill hota hai."""

    def _run(self, existing, duration_on_msg):
        import asyncio
        from unittest import mock
        from web.search_api import _backfill_duration

        writes = []

        class FakeCol:
            async def update_one(self, flt, payload, **k): writes.append(payload)

        class FakeMedia: duration = duration_on_msg

        msg = mock.MagicMock()
        msg.media = mock.MagicMock()
        msg.media.value = "video"
        msg.video = FakeMedia()

        asyncio.run(_backfill_duration(FakeCol(), "FID", existing, msg))
        return writes

    def test_backfills_when_missing(self):
        writes = self._run({"_id": "FID", "duration": 0}, 3600)
        self.assertEqual(writes, [{"$set": {"duration": 3600}}])

    def test_skips_when_already_present(self):
        writes = self._run({"_id": "FID", "duration": 3600}, 9999)
        self.assertEqual(writes, [], "already-present duration par dobara write nahi hona chahiye")

    def test_skips_when_msg_has_no_duration(self):
        writes = self._run({"_id": "FID", "duration": 0}, 0)
        self.assertEqual(writes, [])

    def test_never_raises(self):
        """Thumbnail flow ko duration ki wajah se kabhi fail nahi hona chahiye."""
        import asyncio
        from web.search_api import _backfill_duration

        class BoomCol:
            async def update_one(self, *a, **k): raise RuntimeError("db down")

        asyncio.run(_backfill_duration(BoomCol(), "FID", {}, None))  # raise nahi karna chahiye


class TestMediaMetaCapture(unittest.TestCase):
    """Indexing ke waqt width/height/mime_type DB me save hone chahiye.

    Ye teen fields Telegram se sirf index ke waqt milte hain — baad me nikaalne
    ke liye poora channel dobara scan karna padta (flood + time).
    """

    def test_build_media_meta_from_video(self):
        from database.ia_filterdb import build_media_meta, META_SCHEMA_VERSION

        class FakeVideo:
            width = 1920
            height = 1080
            mime_type = "video/mp4"

        meta = build_media_meta(FakeVideo())
        self.assertEqual(meta["w"], 1920)
        self.assertEqual(meta["h"], 1080)
        self.assertEqual(meta["mime"], "video/mp4")
        self.assertEqual(meta["v"], META_SCHEMA_VERSION)

    def test_build_media_meta_document_has_no_dimensions(self):
        """Document par width/height attribute hota hi nahi — crash nahi hona chahiye."""
        from database.ia_filterdb import build_media_meta

        class FakeDoc:
            mime_type = "application/pdf"

        meta = build_media_meta(FakeDoc())
        self.assertEqual(meta["w"], 0)
        self.assertEqual(meta["h"], 0)
        self.assertEqual(meta["mime"], "application/pdf")

    def test_build_media_meta_none_mime_becomes_empty_string(self):
        from database.ia_filterdb import build_media_meta

        class Weird:
            width = 1280
            height = 720
            mime_type = None

        meta = build_media_meta(Weird())
        self.assertEqual(meta["mime"], "")
        self.assertEqual((meta["w"], meta["h"]), (1280, 720))

    def test_save_file_persists_meta_as_dotted_keys(self):
        """meta dotted ($set: meta.w) se likhna chahiye taaki naya meta field
        backfill karte waqt purane meta keys mit na jaayein."""
        import asyncio
        from unittest import mock
        import database.ia_filterdb as fdb

        class FakeVideo:
            file_id = "CQADtest"
            file_name = "Movie_2020_1080p.mkv"
            caption = None
            file_size = 12345
            duration = 7260
            width = 1920
            height = 1080
            mime_type = "video/x-matroska"

        captured = {}

        class FakeCol:
            async def find_one(self, *a, **k): return None
            async def update_one(self, flt, payload, **k): captured.update(payload)

        with mock.patch.object(fdb, "unpack_new_file_id", return_value="ABC123"), \
             mock.patch.object(fdb, "COLLECTIONS", {"primary": FakeCol()}):
            result = asyncio.run(fdb.save_file(FakeVideo(), "primary"))

        self.assertEqual(result, "suc")
        self.assertEqual(captured["$set"]["meta.w"], 1920)
        self.assertEqual(captured["$set"]["meta.h"], 1080)
        self.assertEqual(captured["$set"]["meta.mime"], "video/x-matroska")
        self.assertNotIn("meta", captured["$set"],
                         "poora meta sub-document ek $set me nahi, dotted keys honi chahiye")

    def test_save_file_document_meta_is_zero_not_missing(self):
        import asyncio
        from unittest import mock
        import database.ia_filterdb as fdb

        class FakeDoc:
            file_id = "CQADtest"
            file_name = "book.pdf"
            caption = None
            file_size = 999

        captured = {}

        class FakeCol:
            async def find_one(self, *a, **k): return None
            async def update_one(self, flt, payload, **k): captured.update(payload)

        with mock.patch.object(fdb, "unpack_new_file_id", return_value="ABC999"), \
             mock.patch.object(fdb, "COLLECTIONS", {"primary": FakeCol()}):
            result = asyncio.run(fdb.save_file(FakeDoc(), "primary"))

        self.assertEqual(result, "suc")
        self.assertEqual(captured["$set"]["meta.w"], 0)
        self.assertEqual(captured["$set"]["meta.h"], 0)
        self.assertEqual(captured["$set"]["meta.mime"], "")

    def test_projection_includes_meta(self):
        from database.ia_filterdb import FILE_PROJECTION, FILE_PROJECTION_SCORED
        self.assertEqual(FILE_PROJECTION.get("meta"), 1)
        self.assertEqual(FILE_PROJECTION_SCORED.get("meta"), 1)


class TestMediaMetaBackfill(unittest.TestCase):
    """Purani files: thumbnail fetch ke waqt meta free me backfill hota hai."""

    def _run(self, existing, width=1920, height=1080, mime="video/x-matroska", has_media=True):
        import asyncio
        from unittest import mock
        from web.search_api import _backfill_media_meta

        writes = []

        class FakeCol:
            async def update_one(self, flt, payload, **k): writes.append(payload)

        # class body me `width = width` likhne se NameError aata hai (class-body
        # name lookup enclosing function scope nahi karta), isliye attributes
        # class banne ke baad set kiye jaate hain.
        class FakeMedia:
            pass

        FakeMedia.width = width
        FakeMedia.height = height
        FakeMedia.mime_type = mime

        msg = mock.MagicMock()
        msg.media = mock.MagicMock()
        msg.media.value = "video"
        msg.video = FakeMedia() if has_media else None

        asyncio.run(_backfill_media_meta(FakeCol(), "FID", existing, msg))
        return writes

    def test_backfills_when_missing(self):
        from database.ia_filterdb import META_SCHEMA_VERSION
        writes = self._run({"_id": "FID"})
        self.assertEqual(writes, [{"$set": {
            "meta.v": META_SCHEMA_VERSION, "meta.w": 1920, "meta.h": 1080,
            "meta.mime": "video/x-matroska"
        }}])

    def test_skips_when_already_present(self):
        writes = self._run({"_id": "FID", "meta": {"v": 1, "w": 640, "h": 480, "mime": "video/mp4"}})
        self.assertEqual(writes, [], "meta pehle se hai to dobara write nahi hona chahiye")

    def test_skips_when_msg_has_nothing_useful(self):
        """Document (na width/height, na mime) par likhne layak kuch nahi hai."""
        writes = self._run({"_id": "FID"}, width=0, height=0, mime="")
        self.assertEqual(writes, [])

    def test_skips_when_msg_media_missing(self):
        writes = self._run({"_id": "FID"}, has_media=False)
        self.assertEqual(writes, [])

    def test_never_raises(self):
        """Thumbnail flow ko meta backfill ki wajah se kabhi fail nahi hona chahiye."""
        import asyncio
        from web.search_api import _backfill_media_meta

        class BoomCol:
            async def update_one(self, *a, **k): raise RuntimeError("db down")

        asyncio.run(_backfill_media_meta(BoomCol(), "FID", {}, None))  # raise nahi karna chahiye


class TestDurationOnlyOnWeb(unittest.TestCase):
    """User ne kaha 'sirf web per' — Telegram bot ke messages me duration nahi jaana chahiye."""

    def test_bot_filter_caption_has_no_duration(self):
        import inspect
        import plugins.filter as flt
        src = inspect.getsource(flt.get_filter_ui)
        self.assertNotIn("duration", src,
                         "bot ke result message me duration nahi jaana chahiye (sirf web)")

    def test_bot_search_script_has_no_duration(self):
        from Script import script
        for name in ("NOT_FILE_TXT", "FILE_CAPTION"):
            self.assertNotIn("duration", getattr(script, name).lower())


class TestDurationInWebUI(unittest.TestCase):
    """Render huye HTML/JS me duration chip actually maujood ho."""

    def test_dashboard_renders_duration_chip(self):
        from web.dashboard_routes import JS_ENGINE
        self.assertIn("dur-chip", JS_ENGINE)
        self.assertIn("tc-dur", JS_ENGINE)
        self.assertIn("f.duration", JS_ENGINE)

    def test_dashboard_css_defines_chips(self):
        from web.web_assets import CSS
        self.assertIn(".dur-chip{", CSS)
        self.assertIn(".tc-dur{", CSS)

    def test_miniapp_renders_duration_chip(self):
        import os
        path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                            "web", "miniapp.html")
        with open(path, encoding="utf-8") as fh:
            html = fh.read()
        self.assertIn('class="dc"', html)
        self.assertIn('class="td"', html)
        self.assertIn("f.duration", html)
        self.assertIn(".dc{", html)

    def test_actor_page_renders_duration_chip(self):
        import inspect
        import web.actor_routes as ar
        src = inspect.getsource(ar.actor_profile_display)
        self.assertIn("dur-chip", src)
        self.assertIn("tc-dur", src)


# ─────────────────────────────────────────────
# 🧭 COMMAND LIST ↔ HANDLER SYNC
# ─────────────────────────────────────────────
def _walk_command_filters(f, depth=0, seen=None):
    """Hydrogram filter tree ko todo, CommandFilter.commands nikaalo.

    AndFilter/OrFilter child ko `.base` / `.other` me rakhte hain
    (pyrogram jaisa `.f1`/`.f2` NAHI), isliye recursive walk zaroori hai.
    """
    seen = set() if seen is None else seen
    if f is None or depth > 12 or id(f) in seen:
        return []
    seen.add(id(f))
    if type(f).__name__ == "CommandFilter":
        return list(f.commands)
    out = []
    for name in (vars(f) if hasattr(f, "__dict__") else []):
        try:
            v = getattr(f, name)
        except Exception:
            continue
        if isinstance(v, list):
            for it in v:
                out += _walk_command_filters(it, depth + 1, seen)
        elif v.__class__.__module__.startswith(("hydrogram", "pyrogram")):
            out += _walk_command_filters(v, depth + 1, seen)
    return out


def _live_bot_commands():
    """Har plugin import karke actually-registered commands ka set."""
    import importlib
    import pkgutil
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    live = set()
    for mod in sorted(pkgutil.iter_modules([os.path.join(root, "plugins")])):
        m = importlib.import_module("plugins." + mod.name)
        for _name, obj in vars(m).items():
            for handler, _grp in (getattr(obj, "handlers", None) or []):
                live.update(_walk_command_filters(handler.filters))
    return live


def _listed_commands():
    """Script.py ke help panels me jo commands likhe hain."""
    import re
    import Script

    listed = set()
    for block in ("USER_COMMAND_TXT", "ADMIN_COMMAND_TXT"):
        txt = getattr(Script.script, block, "")
        txt = re.sub(r"</?[a-z]+>", "", txt)   # HTML tags command nahi hain
        listed.update(re.findall(r"/([a-z_]+)", txt))
    return listed


class TestCommandListMatchesHandlers(unittest.TestCase):
    """Help panel ka command list jhoot na bole — dono taraf exact match."""

    def test_no_dead_commands_in_list(self):
        dead = sorted(_listed_commands() - _live_bot_commands())
        self.assertEqual(
            dead, [],
            "Ye commands help panel me listed hain par inka koi handler nahi: "
            + ", ".join("/" + c for c in dead),
        )

    def test_no_undocumented_live_commands(self):
        undoc = sorted(_live_bot_commands() - _listed_commands())
        self.assertEqual(
            undoc, [],
            "Ye commands live hain par help panel me listed nahi: "
            + ", ".join("/" + c for c in undoc),
        )

    def test_list_is_not_empty(self):
        # Sanity: agar parser toot jaye to dono set khali ho jaate aur
        # upar wale dono tests "pass" ho jaate. Isse wo pakda jayega.
        self.assertGreaterEqual(len(_listed_commands()), 25)
        self.assertGreaterEqual(len(_live_bot_commands()), 25)

    def test_removed_dead_commands_stay_removed(self):
        listed = _listed_commands()
        for gone in ("fileid", "ask", "ai", "mute", "unmute", "ban", "warn",
                     "resetwarn", "addblacklist", "removeblacklist",
                     "blacklist", "dlink", "removedlink", "dlinklist"):
            self.assertNotIn(gone, listed, f"/{gone} wapas list me aa gaya")


class TestResolutionChip(unittest.TestCase):
    """Resolution chip asli W×H dikhaye — koi '720p'/'1080p' guess nahi.

    User ki requirement: "jo resolution rahega wahi show karega".
    """

    def test_shows_actual_resolution(self):
        from database.ia_filterdb import get_resolution_text
        self.assertEqual(get_resolution_text(1280, 720), "1280×720")
        self.assertEqual(get_resolution_text(1920, 1080), "1920×1080")
        self.assertEqual(get_resolution_text(3840, 2160), "3840×2160")
        self.assertEqual(get_resolution_text(2560, 1440), "2560×1440")

    def test_odd_resolution_shown_as_is(self):
        """1245×655 jaisi non-standard file par bhi jhooth nahi — waisa hi dikhe."""
        from database.ia_filterdb import get_resolution_text
        self.assertEqual(get_resolution_text(1245, 655), "1245×655")
        self.assertEqual(get_resolution_text(1920, 800), "1920×800")
        self.assertEqual(get_resolution_text(1278, 536), "1278×536")

    def test_portrait_video_shows_actual_dimensions(self):
        """1080×1920 vertical clip par bhi asli dimensions (koi '1080p' guess nahi)."""
        from database.ia_filterdb import get_resolution_text
        self.assertEqual(get_resolution_text(1080, 1920), "1080×1920")

    def test_missing_dimensions_give_empty(self):
        from database.ia_filterdb import get_resolution_text
        self.assertEqual(get_resolution_text(0, 0), "")
        self.assertEqual(get_resolution_text(0, 720), "")   # width missing
        self.assertEqual(get_resolution_text(1280, 0), "")  # height missing
        self.assertEqual(get_resolution_text(None, None), "")
        self.assertEqual(get_resolution_text("", ""), "")

    def test_filename_fallback_only_for_explicit_resolution(self):
        from database.ia_filterdb import get_resolution_text
        # purani file — meta khali, par filename me resolution likha hai
        self.assertEqual(get_resolution_text(0, 0, "Movie 2021 1280x720 hindi"), "1280×720")
        self.assertEqual(get_resolution_text(0, 0, "Movie 2021 1920X1080"), "1920×1080")
        self.assertEqual(get_resolution_text(0, 0, "Movie 2021 1280×720"), "1280×720")
        # 'x264'/'x265' aur "saal + codec" resolution nahi hain
        self.assertEqual(get_resolution_text(0, 0, "Movie 2021 x265 1080p"), "")
        self.assertEqual(get_resolution_text(0, 0, "Movie 2021 x264"), "")
        self.assertEqual(get_resolution_text(0, 0, "Movie 2021 720p"), "")
        self.assertEqual(get_resolution_text(0, 0, "Movie 2021"), "")
        # 'x' ke aas-paas space wale form bhi skip — "2021 x265" jaisa false
        # positive ("2021×265") rokne ke liye ye jaan-boojhkar chhoda gaya hai
        self.assertEqual(get_resolution_text(0, 0, "Movie 3840 × 2160"), "")

    def test_no_p_labels_anywhere(self):
        """Regression: '720p'/'1080p' style labels wapas na aa jaayein."""
        from database.ia_filterdb import get_resolution_text
        for w, h in [(1280, 720), (1920, 1080), (1245, 655), (640, 360)]:
            out = get_resolution_text(w, h)
            self.assertNotIn("p", out, f"{w}x{h} par p-label aa gaya: {out}")

    def test_doc_resolution_text_safe_without_meta(self):
        from database.ia_filterdb import doc_resolution_text
        self.assertEqual(doc_resolution_text({"meta": {"w": 1920, "h": 1080}}), "1920×1080")
        self.assertEqual(doc_resolution_text({"meta": {"w": 1245, "h": 655}}), "1245×655")
        self.assertEqual(doc_resolution_text({"file_name": "Old 1280x720 Movie"}), "1280×720")
        self.assertEqual(doc_resolution_text({"file_name": "Old Movie"}), "")
        self.assertEqual(doc_resolution_text({}), "")
        self.assertEqual(doc_resolution_text({"meta": None, "file_name": "x"}), "")
        # documents (meta me sirf mime) par kuch nahi
        self.assertEqual(doc_resolution_text({"meta": {"w": 0, "h": 0, "mime": "application/pdf"},
                                              "file_name": "book.pdf"}), "")


class TestResInApiResponse(unittest.TestCase):
    """Web search API ke JSON me resolution field aana chahiye."""

    def test_res_from_meta(self):
        from web.search_api import _build_results_list
        docs = [{"_id": "F1", "file_ref": "R1", "file_name": "Movie 2020",
                 "file_size": 1048576, "file_type": "video", "duration": 7260,
                 "meta": {"v": 1, "w": 1920, "h": 1080, "mime": "video/mp4"},
                 "source_col": "primary", "thumb_url": ""}]
        self.assertEqual(_build_results_list(docs, "tg")[0]["res"], "1920×1080")

    def test_res_falls_back_to_filename(self):
        from web.search_api import _build_results_list
        docs = [{"_id": "F2", "file_ref": "R2", "file_name": "Old Movie 1280x720",
                 "file_size": 100, "file_type": "video",
                 "source_col": "cloud", "thumb_url": ""}]
        self.assertEqual(_build_results_list(docs, "none")[0]["res"], "1280×720")

    def test_res_empty_when_unknown(self):
        from web.search_api import _build_results_list
        docs = [{"_id": "F3", "file_ref": "R3", "file_name": "book.pdf",
                 "file_size": 100, "file_type": "document",
                 "source_col": "primary", "thumb_url": ""}]
        self.assertEqual(_build_results_list(docs, "tg")[0]["res"], "")


class TestResInWebUI(unittest.TestCase):
    """Resolution chip dashboard + miniapp + actor-profile teeno me dikhna chahiye."""

    def test_shared_css_has_resolution_chip(self):
        import web.web_assets as wa
        # res-chip/tc-res dashboard + actor-profile dono me use hote hain (shared CSS)
        self.assertIn(".res-chip", wa.CSS)
        self.assertIn(".tc-res", wa.CSS)

    def test_dashboard_renders_res_chip(self):
        import web.dashboard_routes as dash
        self.assertIn("resChip", dash.JS_ENGINE)
        self.assertIn("resText", dash.JS_ENGINE)
        self.assertIn("durChip+resChip", dash.JS_ENGINE)
        self.assertIn("durText+resText", dash.JS_ENGINE)

    def test_miniapp_renders_res_chip(self):
        path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                            "web", "miniapp.html")
        with open(path, encoding="utf-8") as f:
            html = f.read()
        self.assertIn('class="rc"', html)
        self.assertIn('class="tr"', html)
        self.assertIn("${dc}${rc}", html)
        self.assertIn("${td}${tr}", html)

    def test_actor_profile_renders_res_chip(self):
        import inspect
        import web.actor_routes as ar
        src = inspect.getsource(ar)
        self.assertIn('"res": doc_resolution_text(d)', src)
        self.assertIn("+durC+resC+", src)
        self.assertIn("+durT+resT+", src)

    def test_no_filter_dropdowns_present_yet(self):
        """Quality/year dropdowns jaan-boojhkar baad ke liye rakhe hain — abhi
        inka koi UI/param mojood nahi hona chahiye."""
        import web.dashboard_routes as dash
        import web.search_api as sa
        self.assertNotIn("curQy", dash.JS_ENGINE)
        self.assertNotIn("pickQy", dash.SEARCH_ZONE)
        self.assertNotIn("qy", sa.api_search.__code__.co_names)
        from database.ia_filterdb import build_query_filter
        self.assertNotIn("quality", build_query_filter.__code__.co_varnames)


def build_q():
    from database.ia_filterdb import build_meta_migration_query
    return build_meta_migration_query()


def _doc_matches(query, doc):
    """Query ko doc par match karta hai — MongoDB jaisa semantics.

    - top-level "$and" list = AND; har element me keys implicitly AND hote hain
    - "$exists": field hai ya nahi
    - "$ne": missing field bhi match karta hai (missing = None, None != 1)
    - "$in" me None missing field ko bhi match karta hai
    """
    def _resolve(field, d):
        """Dotted path resolve karo — 'meta.v' → d['meta']['v'] (MongoDB jaisa)."""
        cur = d
        for part in field.split("."):
            if not isinstance(cur, dict) or part not in cur:
                return None, False
            cur = cur[part]
        return cur, True

    def _field_match(field, spec, d):
        actual, present = _resolve(field, d)
        if isinstance(spec, dict) and spec and all(k.startswith("$") for k in spec):
            for op, val in spec.items():
                if op == "$exists":
                    if present != val:
                        return False
                elif op == "$ne":
                    if present and actual == val:
                        return False
                elif op == "$regex":
                    import re as _re
                    actual_str = "" if not present else str(actual)
                    if not _re.search(val, actual_str):
                        return False
                elif op == "$in":
                    # missing field = None; `$in: [null]` missing ko bhi match karta hai
                    if (actual if present else None) not in val:
                        return False
                else:
                    raise AssertionError(f"test matcher me '{op}' handle nahi hai")
            return True
        return present and actual == spec

    def _cond_match(cond, d):
        for key, val in cond.items():
            if key == "$or":
                if not any(_cond_match(c, d) for c in val):
                    return False
            elif key == "$and":
                if not all(_cond_match(c, d) for c in val):
                    return False
            elif not _field_match(key, val, d):
                return False
        return True

    return all(_cond_match(part, doc) for part in query.get("$and", [query]))


class TestMetaMigrationQuery(unittest.TestCase):
    """Purani files ke liye migration query — sirf adhoore docs chune."""

    def test_matches_video_without_meta(self):
        self.assertTrue(_doc_matches(build_q(), {"file_type": "video"}))

    def test_document_with_video_mime_is_matched(self):
        """Asli video file par 'document' likha hai — mime_type se pakad kar theek karo."""
        doc = {"file_type": "document", "meta": {"v": 1, "mime": "video/mp4"}}
        self.assertTrue(_doc_matches(build_q(), doc))

    def test_document_with_matroska_mime_is_matched(self):
        doc = {"file_type": "document", "meta": {"v": 1, "mime": "video/x-matroska"}}
        self.assertTrue(_doc_matches(build_q(), doc))

    def test_document_with_audio_mime_is_matched(self):
        doc = {"file_type": "document", "meta": {"v": 1, "mime": "audio/mpeg"}}
        self.assertTrue(_doc_matches(build_q(), doc))

    def test_real_document_not_matched(self):
        """Asli document (pdf/jpg) ko chhedna nahi — wo dobara na ute."""
        from database.ia_filterdb import META_SCHEMA_VERSION as V
        for mime in ("application/pdf", "image/jpeg", "image/gif", ""):
            doc = {"file_type": "document", "meta": {"v": V, "mime": mime}}
            self.assertFalse(_doc_matches(build_q(), doc), mime)

    def test_already_fixed_video_not_matched(self):
        """Type theek ho chuka (video) aur meta bhi hai — dobara na uthe."""
        from database.ia_filterdb import META_SCHEMA_VERSION as V
        doc = {"file_type": "video", "duration": 0, "meta": {"v": V, "mime": "video/mp4"}}
        self.assertFalse(_doc_matches(build_q(), doc))

    def test_video_with_meta_but_zero_duration_not_matched(self):
        """Document object par duration attribute hi nahi — retry karne se kuch
        nahi milega, isliye aisa doc dobara nahi uthta (infinite loop se bachne ke liye)."""
        from database.ia_filterdb import META_SCHEMA_VERSION as V
        doc = {"file_type": "video", "duration": 0, "meta": {"v": V, "w": 1920, "h": 1080}}
        self.assertFalse(_doc_matches(build_q(), doc))

    def test_complete_video_not_matched(self):
        from database.ia_filterdb import META_SCHEMA_VERSION as V
        doc = {"file_type": "video", "duration": 7260,
               "meta": {"v": V, "w": 1920, "h": 1080, "mime": "video/mp4"}}
        self.assertFalse(_doc_matches(build_q(), doc))

    def test_documents_not_matched_forever(self):
        """Documents ki duration legitimately 0 hoti hai — wo har run me na ute."""
        from database.ia_filterdb import META_SCHEMA_VERSION as V
        doc = {"file_type": "document", "duration": 0,
               "meta": {"v": V, "w": 0, "h": 0, "mime": "application/pdf"}}
        self.assertFalse(_doc_matches(build_q(), doc))

    def test_document_without_meta_is_matched(self):
        # meta hi nahi hai → match (mime_type bhi chahiye)
        self.assertTrue(_doc_matches(build_q(), {"file_type": "document"}))

    def test_errored_refs_skipped(self):
        """meta.err wale (tooti file_ref) dobara na uthe."""
        doc = {"file_type": "video", "meta": {"err": 1690000000}}
        self.assertFalse(_doc_matches(build_q(), doc))

    def test_query_is_deterministic(self):
        self.assertEqual(build_q(), build_q())


class TestMediaTrueType(unittest.TestCase):
    """Document me chhupi video/audio ka asli type — mime_type se."""

    def setUp(self):
        from database.ia_filterdb import media_true_type
        globals()["media_true_type"] = media_true_type

    def test_video_object(self):
        class V:
            pass
        V.__name__ = "Video"
        self.assertEqual(media_true_type(V()), "video")

    def test_document_with_video_mime(self):
        class D:
            mime_type = "video/mp4"
        D.__name__ = "Document"
        self.assertEqual(media_true_type(D()), "video")

    def test_document_with_matroska_mime(self):
        class D:
            mime_type = "video/x-matroska"
        D.__name__ = "Document"
        self.assertEqual(media_true_type(D()), "video")

    def test_document_with_audio_mime(self):
        class D:
            mime_type = "audio/mpeg"
        D.__name__ = "Document"
        self.assertEqual(media_true_type(D()), "audio")

    def test_real_document_stays_document(self):
        class D:
            mime_type = "application/pdf"
        D.__name__ = "Document"
        self.assertEqual(media_true_type(D()), "document")

    def test_image_document_stays_document(self):
        """jpg/gif document ko jaan-boojhkar document hi rehne dete hain."""
        for mime in ("image/jpeg", "image/png", "image/gif"):
            class D:
                mime_type = mime
            D.__name__ = "Document"
            self.assertEqual(media_true_type(D()), "document")

    def test_document_without_mime(self):
        class D:
            mime_type = None
        D.__name__ = "Document"
        self.assertEqual(media_true_type(D()), "document")

    def test_uppercase_mime(self):
        class D:
            mime_type = "VIDEO/MP4"
        D.__name__ = "Document"
        self.assertEqual(media_true_type(D()), "video")


class TestApplyMediaMetaUpdateTypeFix(unittest.TestCase):
    """Migration ke waqt galat file_type bhi theek hona chahiye."""

    def _run(self, media, current_type):
        import asyncio
        import database.ia_filterdb as fdb

        writes = []

        class FakeCol:
            async def update_one(self, flt, payload, **k):
                writes.append((flt, payload))

        asyncio.run(fdb.apply_media_meta_update(FakeCol(), "FID", media, current_type))
        return writes[0][1]

    def test_document_with_video_mime_gets_video_type(self):
        class D:
            width = 0
            height = 0
            mime_type = "video/mp4"
        D.__name__ = "Document"

        payload = self._run(D(), "document")
        self.assertEqual(payload["$set"]["file_type"], "video")
        self.assertEqual(payload["$set"]["meta.mime"], "video/mp4")
        # Document par duration/width/height attribute hi nahi — likha hi nahi jaata
        self.assertNotIn("duration", payload["$set"])
        self.assertEqual(payload["$set"]["meta.w"], 0)
        self.assertEqual(payload["$unset"], {"meta.err": ""})

    def test_correct_type_not_rewritten(self):
        class V:
            width = 1920
            height = 1080
            mime_type = "video/mp4"
            duration = 120
        V.__name__ = "Video"

        payload = self._run(V(), "video")
        self.assertNotIn("file_type", payload["$set"])
        self.assertEqual(payload["$set"]["duration"], 120)

    def test_animation_not_touched(self):
        class A:
            width = 500
            height = 500
            mime_type = "video/mp4"
            duration = 5
        A.__name__ = "Animation"

        payload = self._run(A(), "animation")
        self.assertNotIn("file_type", payload["$set"])


class TestApplyMediaMetaUpdate(unittest.TestCase):
    """Migration ka DB write — duration/meta dotted keys se."""

    def _run(self, media):
        import asyncio
        from unittest import mock
        import database.ia_filterdb as fdb

        writes = []

        class FakeCol:
            async def update_one(self, flt, payload, **k):
                writes.append((flt, payload))

        meta = asyncio.run(fdb.apply_media_meta_update(FakeCol(), "FID", media))
        return writes, meta

    def test_writes_all_fields_as_dotted_keys(self):
        class FakeVideo:
            width = 1920
            height = 1080
            mime_type = "video/x-matroska"
            duration = 7260

        from database.ia_filterdb import META_SCHEMA_VERSION as V
        writes, meta = self._run(FakeVideo())
        flt, payload = writes[0]
        self.assertEqual(flt, {"_id": "FID"})
        self.assertEqual(payload["$set"]["duration"], 7260)
        self.assertEqual(payload["$set"]["meta.w"], 1920)
        self.assertEqual(payload["$set"]["meta.h"], 1080)
        self.assertEqual(payload["$set"]["meta.mime"], "video/x-matroska")
        self.assertEqual(payload["$set"]["meta.v"], V)
        self.assertNotIn("meta", payload["$set"], "dotted keys honi chahiye")
        self.assertEqual(payload["$unset"], {"meta.err": ""})
        self.assertEqual(meta, {"v": V, "w": 1920, "h": 1080, "mime": "video/x-matroska"})

    def test_document_keeps_zero_duration(self):
        """Document par duration attribute hi nahi — 0 overwrite nahi honi chahiye."""
        class FakeDoc:
            width = 0
            height = 0
            mime_type = "application/pdf"

        writes, _ = self._run(FakeDoc())
        payload = writes[0][1]
        self.assertNotIn("duration", payload["$set"])
        self.assertEqual(payload["$set"]["meta.mime"], "application/pdf")

    def test_media_without_duration_attribute(self):
        class Weird:
            width = 640
            height = 480
            mime_type = "video/mp4"

        writes, _ = self._run(Weird())
        self.assertNotIn("duration", writes[0][1]["$set"])

    def test_skip_version_omits_meta_v(self):
        """Probe fail hone par skip_version=True se meta.v nahi likhna chahiye
        — taaki /migrate_meta ise dobara uthakar probe kar sake."""
        import asyncio
        import database.ia_filterdb as fdb

        writes = []

        class FakeCol:
            async def update_one(self, flt, payload, **k):
                writes.append((flt, payload))

        class FakeVideo:
            width = 1280       # potentially fake Telegram default
            height = 720
            mime_type = "video/mp4"
            duration = 120

        asyncio.run(fdb.apply_media_meta_update(
            FakeCol(), "FID", FakeVideo(), skip_version=True))
        payload = writes[0][1]
        # meta.v should NOT be in $set when skip_version=True
        self.assertNotIn("meta.v", payload["$set"],
                         "skip_version=True par meta.v nahi likhna chahiye")
        # other meta fields should still be written
        self.assertIn("meta.w", payload["$set"])
        self.assertIn("meta.h", payload["$set"])
        self.assertIn("meta.mime", payload["$set"])

    def test_skip_version_false_writes_meta_v(self):
        """Normal case — skip_version=False (default) par meta.v likhna chahiye."""
        import asyncio
        import database.ia_filterdb as fdb

        writes = []

        class FakeCol:
            async def update_one(self, flt, payload, **k):
                writes.append((flt, payload))

        class FakeVideo:
            width = 1920
            height = 1080
            mime_type = "video/mp4"
            duration = 120

        asyncio.run(fdb.apply_media_meta_update(
            FakeCol(), "FID", FakeVideo(), skip_version=False))
        payload = writes[0][1]
        self.assertIn("meta.v", payload["$set"],
                      "skip_version=False par meta.v likhna chahiye")

class TestMigrationPlugin(unittest.TestCase):
    """/migrate_meta command aur uska engine registered hona chahiye."""

    def test_command_handler_registered(self):
        import temp_migrations.meta_migrate as mm
        self.assertTrue(callable(mm.migrate_meta_cmd))
        self.assertTrue(callable(mm.migrate_meta_cancel))
        self.assertTrue(callable(mm.start_meta_migration))

    def test_command_listed_in_help(self):
        from Script import script
        self.assertIn("/migrate_meta", script.ADMIN_COMMAND_TXT)

    def test_ui_has_all_counters(self):
        from temp_migrations.meta_migrate import get_migration_ui
        ui = get_migration_ui(50, 100, 40, 5, 5, 60, 60, 50, type_fixed=7)
        for token in ("40", "50", "100", "Filled", "Skipped", "Failed", "Type Fixed", "7"):
            self.assertIn(token, ui)


class TestIndexTimeTypeGuard(unittest.TestCase):
    """Index-time par wahi gadbad dobara na ho: video/audio file par galti se
    'document' likh diya jata tha. `save_file` ko media_true_type use karna chahiye."""

    def test_save_file_uses_true_type(self):
        import database.ia_filterdb as fdb
        self.assertIn("media_true_type", fdb.save_file.__code__.co_names)

    def test_save_file_does_not_use_raw_class_name(self):
        """`type(media).__name__.lower()` seedha nahi hona chahiye."""
        import database.ia_filterdb as fdb
        src = inspect.getsource(fdb.save_file)
        self.assertNotIn("type(media).__name__.lower()", src)


def _fake_media(type_name, **attrs):
    """Telegram jaisa fake media object — `type(m).__name__` == type_name.

    (class body me `__name__ = ...` kaam nahi karta: `type.__name__` metaclass
    par data-descriptor hai, isliye class-dict entry ko shadow kar deta hai.)
    """
    return type(type_name, (), attrs)()


def _video(w=1920, h=1080, dur=7260, mime="video/x-matroska"):
    """Telegram par ASLI VIDEO — duration/width/height/mime sab hota hai."""
    return _fake_media("Video", width=w, height=h, duration=dur,
                       mime_type=mime, file_size=10 ** 8)


def _document(mime="application/pdf"):
    return _fake_media("Document", mime_type=mime, file_size=10 ** 7)


def _audio(dur=245, mime="audio/mpeg"):
    return _fake_media("Audio", duration=dur, mime_type=mime, file_size=10 ** 7)


class TestWrongFileTypeRepair(unittest.TestCase):
    """⭐ ASLI BUG: file Telegram par VIDEO hai (play bhi hoti hai), par purane
    code ke bug se DB me `file_type: "document"` likh gaya tha. Migration ko
    type + duration + w + h + mime — sab theek karna chahiye, bina re-index."""

    def _apply(self, doc, media):
        import asyncio
        import database.ia_filterdb as fdb

        writes = []

        class FakeCol:
            async def update_one(self, flt, payload, **k):
                writes.append((flt, payload))

        asyncio.run(fdb.apply_media_meta_update(
            FakeCol(), doc["_id"], media, current_type=doc.get("file_type")))
        return writes[0][1]

    def test_document_labelled_video_gets_full_fix(self):
        doc = {"_id": "F1", "file_type": "document", "file_ref": "V1"}
        payload = self._apply(doc, _video())

        self.assertEqual(payload["$set"]["file_type"], "video")
        self.assertEqual(payload["$set"]["duration"], 7260)
        self.assertEqual(payload["$set"]["meta.w"], 1920)
        self.assertEqual(payload["$set"]["meta.h"], 1080)
        self.assertEqual(payload["$set"]["meta.mime"], "video/x-matroska")
        self.assertEqual(payload["$unset"], {"meta.err": ""})

    def test_already_migrated_wrong_type_only_type_written(self):
        """Pehle wale migration run me meta/duration bhul chuke the, sirf type galat."""
        doc = {"_id": "F2", "file_type": "document", "duration": 7260,
               "meta": {"v": 1, "w": 1920, "h": 1080, "mime": "video/x-matroska"}}
        payload = self._apply(doc, _video())
        self.assertEqual(payload["$set"]["file_type"], "video")
        # baaki sab wapas wahi value — koi data nahi mitta
        self.assertEqual(payload["$set"]["meta.w"], 1920)
        self.assertEqual(payload["$set"]["duration"], 7260)

    def test_mp4_video(self):
        doc = {"_id": "F3", "file_type": "document"}
        payload = self._apply(doc, _video(1280, 720, 3600, "video/mp4"))
        self.assertEqual(payload["$set"]["file_type"], "video")
        self.assertEqual(payload["$set"]["meta.mime"], "video/mp4")
        self.assertEqual(payload["$set"]["duration"], 3600)

    def test_wrongly_labelled_audio(self):
        doc = {"_id": "F4", "file_type": "document"}

        payload = self._apply(doc, _audio())
        self.assertEqual(payload["$set"]["file_type"], "audio")
        self.assertEqual(payload["$set"]["duration"], 245)

    def test_real_document_type_untouched(self):
        doc = {"_id": "F5", "file_type": "document"}
        payload = self._apply(doc, _document())
        self.assertNotIn("file_type", payload["$set"])
        self.assertEqual(payload["$set"]["meta.mime"], "application/pdf")

    def test_correct_video_type_untouched(self):
        doc = {"_id": "F6", "file_type": "video"}
        payload = self._apply(doc, _video())
        self.assertNotIn("file_type", payload["$set"])
        self.assertEqual(payload["$set"]["duration"], 7260)


class TestMigrationThrottle(unittest.TestCase):
    """User ka instruction: per-file gap 1-3s — na flood-wait lage, na spam-report."""

    def test_gap_is_between_1_and_3_seconds(self):
        import temp_migrations.meta_migrate as mm
        consts = mm.start_meta_migration.__code__.co_consts
        self.assertIn(1.0, consts)
        self.assertIn(3.0, consts)
        self.assertNotIn(0.6, consts)
        self.assertNotIn(1.2, consts)


# ─────────────────────────────────────────────
# 🔍 TRUE MEDIA PROBE (bug: sab par 1280×720)
# Telegram attributes uploader ke likhe hote hain (aksar default 1280×720),
# isliye asli w/h/duration file BYTES (container header) se nikalte hain.
# Neeche byte-fixtures se pure parsers test hote hain (network nahi).
# ─────────────────────────────────────────────
def _mp4_box(typ, payload):
    import struct
    return struct.pack(">I", 8 + len(payload)) + typ + payload


def _mp4_tkhd(w, h, ver=0, rotate90=False):
    import struct
    head = bytes([ver, 0, 0, 0]) + b"\x00" * (32 if ver == 1 else 20)
    head += b"\x00" * 8  # reserved
    head += struct.pack(">HHhH", 0, 0, 0x0100, 0)  # layer/alt/volume/reserved
    a, b, c, d = (0, 65536, -65536, 0) if rotate90 else (65536, 0, 0, 65536)
    head += struct.pack(">iiiiiiiii", a, b, 0, c, d, 0, 0, 0, 1 << 30)
    head += struct.pack(">II", w * 65536, h * 65536)
    return head


def _mp4_mvhd(ts, dur, ver=0):
    import struct
    if ver == 1:
        return bytes([1, 0, 0, 0]) + b"\x00" * 16 + struct.pack(">IQ", ts, dur)
    return bytes([0, 0, 0, 0]) + b"\x00" * 8 + struct.pack(">II", ts, dur)


def _mp4_hdlr(handler=b"vide"):
    return b"\x00" * 8 + handler + b"\x00" * 12 + b"Handler\x00"


def _mp4_trak(w, h, handler=b"vide", tkhd_ver=0, rotate90=False):
    mdia = _mp4_box(b"mdia", _mp4_box(b"mdhd", b"\x00" * 32)
                    + _mp4_box(b"hdlr", _mp4_hdlr(handler))
                    + _mp4_box(b"minf", b"\x00" * 16))
    return _mp4_box(b"trak", _mp4_box(b"tkhd", _mp4_tkhd(w, h, tkhd_ver, rotate90)) + mdia)


def _mp4_moov(w=1920, h=1080, ts=90000, dur=6480000, audio_first=False):
    traks = b""
    if audio_first:
        traks += _mp4_trak(0, 0, handler=b"soun")
    traks += _mp4_trak(w, h)
    return _mp4_box(b"moov", _mp4_box(b"mvhd", _mp4_mvhd(ts, dur)) + traks)


def _mp4_ftyp():
    return _mp4_box(b"ftyp", b"isom\x00\x00\x00\x01isomiso2mp41")


def _ebml_size(n):
    for ln in range(1, 9):
        if n < (1 << (7 * ln)) - 1:
            raw = n.to_bytes(ln, "big")
            return bytes([raw[0] | (0x80 >> (ln - 1))]) + raw[1:]
    raise ValueError("too big")


def _ebml_el(eid, payload):
    return eid + _ebml_size(len(payload)) + payload


def _ebml_uint(n):
    return n.to_bytes(max(1, (n.bit_length() + 7) // 8), "big")


def _mkv_fixture(pw=1920, ph=800, dur=7200.0, display=None,
                 second_video=False, audio_track=False):
    # NOTE: `dur` seconds me hai; raw Duration element = sec*1e9/scale (scale=1e6)
    import struct
    video = _ebml_el(b"\xb0", _ebml_uint(pw)) + _ebml_el(b"\xba", _ebml_uint(ph))
    if display:
        video += (_ebml_el(b"\x54\xb0", _ebml_uint(display[0]))
                  + _ebml_el(b"\x54\xba", _ebml_uint(display[1])))
    tracks = _ebml_el(b"\xae", _ebml_el(b"\xd7", b"\x01")
                       + _ebml_el(b"\x83", b"\x01") + _ebml_el(b"\xe0", video))
    if second_video:
        v2 = _ebml_el(b"\xe0", _ebml_el(b"\xb0", _ebml_uint(640))
                       + _ebml_el(b"\xba", _ebml_uint(480)))
        tracks += _ebml_el(b"\xae", _ebml_el(b"\xd7", b"\x02")
                            + _ebml_el(b"\x83", b"\x01") + v2)
    if audio_track:
        tracks += _ebml_el(b"\xae", _ebml_el(b"\xd7", b"\x03")
                            + _ebml_el(b"\x83", b"\x02") + _ebml_el(b"\xe1", b"\x00" * 8))
    info = (_ebml_el(b"\x2a\xd7\xb1", _ebml_uint(1000000))
            + _ebml_el(b"\x44\x89", struct.pack(">d", dur * 1000.0)))
    seg = _ebml_el(b"\x15\x49\xa9\x66", info) + _ebml_el(b"\x16\x54\xae\x6b", tracks)
    seg_full = b"\x18\x53\x80\x67" + b"\xff" + seg  # Segment, unknown size (typical)
    return _ebml_el(b"\x1a\x45\xdf\xa3", _ebml_el(b"\x42\x86", b"\x01")) + seg_full


def _riff_chunk(cid, payload):
    import struct
    out = cid + struct.pack("<I", len(payload)) + payload
    if len(payload) & 1:
        out += b"\x00"
    return out


def _riff_list(ltype, inner):
    import struct
    body = ltype + inner
    return b"LIST" + struct.pack("<I", len(body)) + body


def _avi_fixture(w=1280, h=720, mspf=40000, frames=1800,
                 audio=True, neg_h=False):
    import struct
    avih = struct.pack("<IIIIIIIIIIIIII", mspf, 0, 0, 0x10, frames, 0, 2,
                       0, w, h, 0, 0, 0, 0)
    strf_v = struct.pack("<IiiHHIIIIII", 40, w, -h if neg_h else h,
                         1, 24, 0, 0, 0, 0, 0, 0)
    inner = (_riff_chunk(b"avih", avih)
             + _riff_list(b"strl", _riff_chunk(b"strh", b"vids" + b"\x00" * 52)
                          + _riff_chunk(b"strf", strf_v)))
    if audio:
        strf_a = bytes.fromhex("0100020044ac000010b1020004001000")
        inner += _riff_list(b"strl", _riff_chunk(b"strh", b"auds" + b"\x00" * 52)
                            + _riff_chunk(b"strf", strf_a))
    hdrl = _riff_list(b"hdrl", inner)
    movi = _riff_list(b"movi", b"\x00" * 64)  # frames — parser ise skip kare
    body = b"AVI " + hdrl + movi
    return b"RIFF" + struct.pack("<I", len(body)) + body


class TestProbeMP4(unittest.TestCase):
    """MP4/MOV: moov → mvhd (duration) + video trak → tkhd (w/h)."""

    def test_faststart_head(self):
        from media_probe import parse_mp4
        head = _mp4_ftyp() + _mp4_moov() + _mp4_box(b"mdat", b"\x00" * 200)
        w, h, dur = parse_mp4(head)
        self.assertEqual((w, h), (1920, 1080))
        self.assertAlmostEqual(dur, 72.0)  # 6480000/90000

    def test_audio_trak_first_still_finds_video(self):
        from media_probe import parse_mp4
        head = _mp4_ftyp() + _mp4_moov(audio_first=True)
        w, h, _ = parse_mp4(head)
        self.assertEqual((w, h), (1920, 1080))

    def test_v1_boxes(self):
        from media_probe import parse_mp4
        trak = _mp4_trak(3840, 2160, tkhd_ver=1)
        moov = _mp4_box(b"moov", _mp4_box(b"mvhd", _mp4_mvhd(1000, 3600000, ver=1)) + trak)
        w, h, dur = parse_mp4(_mp4_ftyp() + moov)
        self.assertEqual((w, h), (3840, 2160))
        self.assertAlmostEqual(dur, 3600.0)

    def test_rotated_video_gives_display_dims(self):
        """90° rotated clip (portrait): tkhd coded 1920×1080 → display 1080×1920."""
        from media_probe import parse_mp4
        trak = _mp4_trak(1920, 1080, rotate90=True)
        moov = _mp4_box(b"moov", _mp4_box(b"mvhd", _mp4_mvhd(90000, 90000)) + trak)
        w, h, _ = parse_mp4(_mp4_ftyp() + moov)
        self.assertEqual((w, h), (1080, 1920))

    def test_moov_at_end_head_has_nothing(self):
        """moov-at-end file ka head sirf ftyp+mdat rakhta hai → (0,0,None)."""
        import struct
        from media_probe import parse_mp4
        head = _mp4_ftyp() + struct.pack(">I", 0x7FFFFFFF) + b"mdat" + b"\x00" * 500
        self.assertEqual(parse_mp4(head), (0, 0, None))

    def test_garbage_never_raises(self):
        from media_probe import parse_mp4
        for bad in (b"", b"\x00" * 10, b"RIFF....AVI ", b"\xff" * 100,
                    _mp4_ftyp()[:10]):
            self.assertEqual(parse_mp4(bad), (0, 0, None))


class TestProbeMP4Tail(unittest.TestCase):
    """moov-at-end: tail bytes me moov scan + validation."""

    def test_finds_moov_in_tail(self):
        from media_probe import parse_mp4_tail
        tail = b"\x00" * 1000 + _mp4_moov(1920, 800) + b"\x00" * 100
        w, h, dur = parse_mp4_tail(tail)
        self.assertEqual((w, h), (1920, 800))
        self.assertAlmostEqual(dur, 72.0)

    def test_skips_false_moov_in_mdat(self):
        """mdat-data me 'moov' bytes milenge — invalid size wala skip ho."""
        from media_probe import parse_mp4_tail
        fake = b"\x00" * 500 + b"moov" + b"\x00" * 500  # size bytes = 0 → invalid
        tail = fake + _mp4_moov(1280, 536)
        w, h, _ = parse_mp4_tail(tail)
        self.assertEqual((w, h), (1280, 536))

    def test_no_moov_returns_empty(self):
        from media_probe import parse_mp4_tail
        self.assertEqual(parse_mp4_tail(b"\x00" * 5000), (0, 0, None))
        self.assertEqual(parse_mp4_tail(b"short"), (0, 0, None))


class TestProbeMKV(unittest.TestCase):
    """MKV/WebM: EBML Segment → Tracks → PixelWidth/Height + Info Duration."""

    def test_scope_movie(self):
        from media_probe import parse_mkv
        w, h, dur = parse_mkv(_mkv_fixture())
        self.assertEqual((w, h), (1920, 800))
        self.assertAlmostEqual(dur, 7200.0)

    def test_display_dims_win_over_pixel(self):
        """Anamorphic: Pixel 1440×1080 par Display 1920×1080 → display sach hai."""
        from media_probe import parse_mkv
        w, h, _ = parse_mkv(_mkv_fixture(pw=1440, ph=1080, display=(1920, 1080)))
        self.assertEqual((w, h), (1920, 1080))

    def test_first_video_track_wins(self):
        from media_probe import parse_mkv
        w, h, _ = parse_mkv(_mkv_fixture(second_video=True, audio_track=True))
        self.assertEqual((w, h), (1920, 800))

    def test_truncated_buffer_safe(self):
        from media_probe import parse_mkv
        full = _mkv_fixture()
        for cut in (10, 40, 80, len(full) - 5):
            w, h, dur = parse_mkv(full[:cut])  # raise nahi hona chahiye
            self.assertIsInstance(w, int)
            self.assertIsInstance(h, int)

    def test_non_ebml_rejected(self):
        from media_probe import parse_mkv
        self.assertEqual(parse_mkv(b"RIFF" + b"\x00" * 100), (0, 0, None))
        self.assertEqual(parse_mkv(b""), (0, 0, None))


class TestProbeAVI(unittest.TestCase):
    """AVI: hdrl → vids strf (BITMAPINFOHEADER) + avih duration."""

    def test_basic(self):
        from media_probe import parse_avi
        w, h, dur = parse_avi(_avi_fixture())
        self.assertEqual((w, h), (1280, 720))
        self.assertAlmostEqual(dur, 72.0)  # 1800*40000/1e6

    def test_negative_height_is_abs(self):
        """top-down AVI me biHeight negative — dims same."""
        from media_probe import parse_avi
        w, h, _ = parse_avi(_avi_fixture(neg_h=True))
        self.assertEqual((w, h), (1280, 720))

    def test_garbage_safe(self):
        from media_probe import parse_avi
        self.assertEqual(parse_avi(b"RIFFgarbage"), (0, 0, None))
        self.assertEqual(parse_avi(_avi_fixture()[:20]), (0, 0, None))


class TestProbeDispatcher(unittest.TestCase):
    """probe_bytes: magic dispatch + sanity bounds (DB me zehar nahi)."""

    def test_mkv_dispatch(self):
        from media_probe import probe_bytes
        out = probe_bytes(_mkv_fixture())
        self.assertEqual((out["w"], out["h"], out["duration"]), (1920, 800, 7200))

    def test_mp4_faststart(self):
        from media_probe import probe_bytes
        out = probe_bytes(_mp4_ftyp() + _mp4_moov())
        self.assertEqual((out["w"], out["h"], out["duration"]), (1920, 1080, 72))

    def test_mp4_tail_fallback(self):
        import struct
        from media_probe import probe_bytes
        head = _mp4_ftyp() + struct.pack(">I", 0x7FFFFFFF) + b"mdat" + b"\x00" * 500
        tail = b"\x00" * 1000 + _mp4_moov(1920, 800)
        out = probe_bytes(head, tail, "movie.mp4")
        self.assertEqual((out["w"], out["h"]), (1920, 800))

    def test_avi_dispatch(self):
        from media_probe import probe_bytes
        out = probe_bytes(_avi_fixture())
        self.assertEqual((out["w"], out["h"], out["duration"]), (1280, 720, 72))

    def test_pdf_and_garbage_give_empty(self):
        from media_probe import probe_bytes
        self.assertEqual(probe_bytes(b"%PDF-1.4 garbage" + b"\x00" * 100, None, "a.pdf"), {})
        self.assertEqual(probe_bytes(b"\x00" * 5000), {})
        self.assertEqual(probe_bytes(b"", None, "x.mkv"), {})
        self.assertEqual(probe_bytes(None), {})

    def test_insane_dims_dropped_duration_kept(self):
        """Parser bug se 10000×10 aaye to dims drop (duration sahi ho to rakho)."""
        from media_probe import probe_bytes
        out = probe_bytes(_mp4_ftyp() + _mp4_moov(w=10000, h=10))
        self.assertNotIn("w", out)
        self.assertNotIn("h", out)
        self.assertEqual(out.get("duration"), 72)

    def test_extension_hint_only_for_video_exts(self):
        from media_probe import probe_bytes
        # unknown magic + non-video ext → bilkul koshish nahi
        self.assertEqual(probe_bytes(b"ZZZZ" + b"\x00" * 5000, None, "a.pdf"), {})


class TestShouldProbe(unittest.TestCase):
    """Sirf video-ish media par bandwidth kharch ho (PDF/MP3 par nahi)."""

    def test_video_objects(self):
        from media_probe import should_probe_media
        for t in ("Video", "Animation", "VideoNote"):
            m = type(t, (), {})()
            self.assertTrue(should_probe_media(m), t)

    def test_document_with_video_mime_or_ext(self):
        from media_probe import should_probe_media
        d1 = type("Document", (), {"mime_type": "video/x-matroska"})()
        self.assertTrue(should_probe_media(d1))
        d2 = type("Document", (), {"mime_type": "", "file_name": "m.mkv"})()
        self.assertTrue(should_probe_media(d2))
        d3 = type("Document", (), {"mime_type": None})()
        self.assertTrue(should_probe_media(d3, "Movie.mp4"))

    def test_non_video_skipped(self):
        from media_probe import should_probe_media
        self.assertFalse(should_probe_media(None))
        pdf = type("Document", (), {"mime_type": "application/pdf",
                                    "file_name": "a.pdf"})()
        self.assertFalse(should_probe_media(pdf))
        audio = type("Audio", (), {"mime_type": "audio/mpeg"})()
        self.assertFalse(should_probe_media(audio))
        photo = type("Photo", (), {})()
        self.assertFalse(should_probe_media(photo))


class TestProbedOverride(unittest.TestCase):
    """Probed (actual-bytes) values Telegram attributes ko override karein."""

    def test_build_meta_prefers_probed(self):
        from database.ia_filterdb import build_media_meta
        v = type("Video", (), {"width": 1280, "height": 720,
                               "mime_type": "video/mp4"})()
        meta = build_media_meta(v, {"w": 1920, "h": 1080})
        self.assertEqual((meta["w"], meta["h"]), (1920, 1080))
        self.assertEqual(meta["mime"], "video/mp4")

    def test_build_meta_partial_probe_keeps_attrs(self):
        """Adhoora probe (sirf w) attributes ko kharab na kare."""
        from database.ia_filterdb import build_media_meta
        v = type("Video", (), {"width": 1280, "height": 720,
                               "mime_type": "video/mp4"})()
        meta = build_media_meta(v, {"w": 1920})
        self.assertEqual((meta["w"], meta["h"]), (1280, 720))
        meta2 = build_media_meta(v, None)
        self.assertEqual((meta2["w"], meta2["h"]), (1280, 720))

    def test_apply_uses_probed_duration(self):
        import asyncio
        import database.ia_filterdb as fdb
        writes = []

        class FakeCol:
            async def update_one(self, flt, payload, **k):
                writes.append(payload)

        v = type("Video", (), {"width": 1280, "height": 720, "duration": 100,
                               "mime_type": "video/mp4"})()
        asyncio.run(fdb.apply_media_meta_update(
            FakeCol(), "FID", v, "video", {"w": 1920, "h": 1080, "duration": 7260}))
        payload = writes[0]
        self.assertEqual(payload["$set"]["duration"], 7260)
        self.assertEqual(payload["$set"]["meta.w"], 1920)
        self.assertEqual(payload["$set"]["meta.h"], 1080)

    def test_apply_falls_back_to_attr_duration(self):
        import asyncio
        import database.ia_filterdb as fdb
        writes = []

        class FakeCol:
            async def update_one(self, flt, payload, **k):
                writes.append(payload)

        v = type("Video", (), {"width": 1280, "height": 720, "duration": 120,
                               "mime_type": "video/mp4"})()
        asyncio.run(fdb.apply_media_meta_update(FakeCol(), "FID", v, "video", {}))
        self.assertEqual(writes[0]["$set"]["duration"], 120)

    def test_save_file_persists_probed(self):
        import asyncio
        from unittest import mock
        import database.ia_filterdb as fdb

        class FakeVideo:
            file_id = "CQADtest"
            file_name = "Movie_1080p.mkv"
            caption = None
            file_size = 12345
            duration = 100  # jhootha attribute
            width = 1280
            height = 720
            mime_type = "video/x-matroska"

        captured = {}

        class FakeCol:
            async def find_one(self, *a, **k):
                return None

            async def update_one(self, flt, payload, **k):
                captured.update(payload)

        with mock.patch.object(fdb, "unpack_new_file_id", return_value="ABC123"), \
             mock.patch.object(fdb, "COLLECTIONS", {"primary": FakeCol()}):
            result = asyncio.run(fdb.save_file(
                FakeVideo(), "primary", {"w": 1920, "h": 1080, "duration": 7260}))
        self.assertEqual(result, "suc")
        self.assertEqual(captured["$set"]["meta.w"], 1920)
        self.assertEqual(captured["$set"]["meta.h"], 1080)
        self.assertEqual(captured["$set"]["duration"], 7260)


class _FakeFileClient:
    """hydrogram Client ka range-download hissa (get_file async-generator)."""

    def __init__(self, head_chunks, tail_chunks=()):
        self.head_chunks = list(head_chunks)
        self.tail_chunks = list(tail_chunks)
        self.calls = []

    async def get_file(self, fid, file_size=0, limit=0, offset=0,
                       progress=None, progress_args=()):
        self.calls.append((offset, limit))
        chunks = self.tail_chunks if offset > 0 else self.head_chunks
        for c in chunks[:limit or len(chunks)]:
            yield c


class TestProbeTelegramFile(unittest.TestCase):
    """Orchestrator: head → parsers → (mp4: tail) → ffprobe. Network mocked."""

    def _run(self, client, file_size=0, file_name="m.mkv"):
        import asyncio
        from unittest import mock
        from media_probe import probe_telegram_file
        with mock.patch("hydrogram.file_id.FileId.decode", return_value=object()):
            return asyncio.run(probe_telegram_file(
                client, "REF", file_size=file_size, file_name=file_name))

    def test_mkv_head_only_no_tail_fetch(self):
        out = self._run(_FakeFileClient([_mkv_fixture()]), file_size=10 ** 9)
        self.assertEqual((out["w"], out["h"], out["duration"]), (1920, 800, 7200))

    def test_mp4_faststart_no_tail_fetch(self):
        client = _FakeFileClient([_mp4_ftyp() + _mp4_moov()])
        out = self._run(client, file_size=2 * 10 ** 9, file_name="m.mp4")
        self.assertEqual((out["w"], out["h"]), (1920, 1080))
        self.assertTrue(all(off == 0 for off, _ in client.calls),
                        "moov head me mila to tail fetch bekaar hai")

    def test_mp4_tail_fetched_when_needed(self):
        import struct
        head = _mp4_ftyp() + struct.pack(">I", 0x7FFFFFFF) + b"mdat" + b"\x00" * 500
        tail = b"\x00" * 1000 + _mp4_moov(1920, 800)
        client = _FakeFileClient([head], [tail])
        out = self._run(client, file_size=100 * 1024 * 1024, file_name="m.mp4")
        self.assertEqual((out["w"], out["h"]), (1920, 800))
        self.assertTrue(any(off > 0 for off, _ in client.calls), "tail fetch hona chahiye")

    def test_empty_fetch_gives_empty(self):
        self.assertEqual(self._run(_FakeFileClient([])), {})

    def test_no_client_no_ref_gives_empty(self):
        import asyncio
        from media_probe import probe_telegram_file
        self.assertEqual(asyncio.run(probe_telegram_file(None, "REF")), {})
        self.assertEqual(asyncio.run(probe_telegram_file(object(), "")), {})

    def test_floodwait_propagates(self):
        """Probe ka FloodWait dabana nahi — migration ka handler soyega."""
        import asyncio
        from unittest import mock
        from hydrogram.errors import FloodWait
        from media_probe import probe_telegram_file

        class FloodClient:
            async def get_file(self, *a, **k):
                raise FloodWait(7)
                yield b""  # async-generator banane ke liye (kabhi chalega nahi)

        with mock.patch("hydrogram.file_id.FileId.decode", return_value=object()):
            with self.assertRaises(FloodWait):
                asyncio.run(probe_telegram_file(FloodClient(), "REF"))

    def test_ffprobe_used_as_last_resort(self):
        from unittest import mock
        head = b"TSHEAD" + b"\x00" * 5000  # unknown magic
        with mock.patch("media_probe.ffprobe_head", return_value={"w": 640, "h": 480}):
            out = self._run(_FakeFileClient([head]), file_name="a.ts")
        self.assertEqual((out["w"], out["h"]), (640, 480))


class TestFfprobeFallback(unittest.TestCase):
    """Rare containers (TS/FLV/...) ke liye ffprobe — best-effort, kabhi raise nahi."""

    def test_parses_video_stream_and_rotation(self):
        import json
        from unittest import mock
        from media_probe import ffprobe_head
        payload = json.dumps({
            "streams": [{"codec_type": "video", "width": 1920, "height": 1080,
                         "tags": {"rotate": "90"}}],
            "format": {"duration": "72.4"},
        }).encode()
        proc = mock.Mock(returncode=0, stdout=payload)
        with mock.patch("media_probe.shutil.which", return_value="/usr/bin/ffprobe"), \
             mock.patch("media_probe.subprocess.run", return_value=proc):
            out = ffprobe_head(b"\x00" * 2048)
        self.assertEqual((out["w"], out["h"]), (1080, 1920))  # rotate swap
        self.assertEqual(out["duration"], 72)

    def test_missing_binary_or_failure_gives_empty(self):
        from unittest import mock
        from media_probe import ffprobe_head
        with mock.patch("media_probe.shutil.which", return_value=None):
            self.assertEqual(ffprobe_head(b"\x00" * 2048), {})
        proc = mock.Mock(returncode=1, stdout=b"")
        with mock.patch("media_probe.shutil.which", return_value="/usr/bin/ffprobe"), \
             mock.patch("media_probe.subprocess.run", return_value=proc):
            self.assertEqual(ffprobe_head(b"\x00" * 2048), {})
        self.assertEqual(ffprobe_head(b"tiny"), {})  # bahut chhota head


class TestMigrationQueryV2(unittest.TestCase):
    """v1 docs (Telegram-attrs wale) dobara uthenge — probe se sach likhega."""

    def test_v1_complete_video_requeued(self):
        doc = {"file_type": "video", "duration": 7260,
               "meta": {"v": 1, "w": 1280, "h": 720, "mime": "video/mp4"}}
        self.assertTrue(_doc_matches(build_q(), doc))

    def test_v2_complete_video_skipped(self):
        from database.ia_filterdb import META_SCHEMA_VERSION as V
        doc = {"file_type": "video", "duration": 7260,
               "meta": {"v": V, "w": 1920, "h": 1080, "mime": "video/mp4"}}
        self.assertFalse(_doc_matches(build_q(), doc))

    def test_v1_pdf_requeued_once_for_finalize(self):
        doc = {"file_type": "document", "duration": 0,
               "meta": {"v": 1, "w": 0, "h": 0, "mime": "application/pdf"}}
        self.assertTrue(_doc_matches(build_q(), doc))

    def test_v2_backfilled_doc_with_video_mime_still_matched(self):
        """Backfill ne mime likha par type nahi — migration type+probe karega."""
        from database.ia_filterdb import META_SCHEMA_VERSION as V
        doc = {"file_type": "document",
               "meta": {"v": V, "w": 0, "h": 0, "mime": "video/x-matroska"}}
        self.assertTrue(_doc_matches(build_q(), doc))


class TestBackfillProbe(unittest.TestCase):
    """Lazy backfill bhi probe kare; probe-fail par meta.v na likhe (migration retry)."""

    def _run(self, existing, probed_result="__noprobe__"):
        import asyncio
        from unittest import mock
        from web.search_api import _backfill_media_meta
        writes = []

        class FakeCol:
            async def update_one(self, flt, payload, **k):
                writes.append(payload)

        media = type("Video", (), {"width": 1280, "height": 720,
                                   "mime_type": "video/mp4", "file_id": "REF123",
                                   "file_name": "m.mkv", "file_size": 100})()
        msg = mock.MagicMock()
        msg.media = mock.MagicMock()
        msg.media.value = "video"
        msg.video = media
        if probed_result == "__noprobe__":
            # temp.BOT None (test env) → probe skip → {} (fail jaisa)
            asyncio.run(_backfill_media_meta(FakeCol(), "FID", existing, msg))
        else:
            with mock.patch("web.search_api.probe_telegram_file",
                            new=mock.AsyncMock(return_value=probed_result)):
                asyncio.run(_backfill_media_meta(FakeCol(), "FID", existing, msg))
        return writes

    def test_probe_fail_writes_attrs_without_v(self):
        writes = self._run({"_id": "FID"})
        payload = writes[0]["$set"]
        self.assertEqual(payload["meta.w"], 1280)  # UI ke liye attributes abhi
        self.assertNotIn("meta.v", payload, "v nahi → migration dobara probe karega")

    def test_probe_success_writes_v_and_corrects_duration(self):
        from database.ia_filterdb import META_SCHEMA_VERSION as V
        writes = self._run({"_id": "FID", "duration": 100},
                           {"w": 1920, "h": 1080, "duration": 3600})
        payload = writes[0]["$set"]
        self.assertEqual(payload["meta.v"], V)
        self.assertEqual(payload["meta.w"], 1920)
        self.assertEqual(payload["meta.h"], 1080)
        self.assertEqual(payload["duration"], 3600)


class TestMigrationUIProbed(unittest.TestCase):
    """Migration console me probe counter dikhe."""

    def test_ui_has_probed_line(self):
        from temp_migrations.meta_migrate import get_migration_ui
        ui = get_migration_ui(10, 100, 8, 1, 1, 5, 5, 5, type_fixed=2, probed=7)
        self.assertIn("Probed", ui)
        self.assertIn("7", ui)


if __name__ == "__main__":
    unittest.main(verbosity=2)
