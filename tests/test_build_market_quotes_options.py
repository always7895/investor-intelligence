"""Covered-call suggestions: strike choice (as high as possible while the premium is worth collecting), sell limit,
derived yields, validation before sealing. No network."""
from __future__ import annotations

import contextlib
import io
import json
import sys
import tempfile
import threading
import unittest
import urllib.request
from collections import namedtuple
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import build_market_quotes_options as builder  # noqa: E402
import publish_sealed_snapshot as publisher  # noqa: E402
from validate_v213_market_products import MarketProductValidationError, validate_covered_call_cycle  # noqa: E402


def row(strike, bid, ask, delta=None):
    return {"strike": strike, "bid": bid, "ask": ask, "delta": delta, "iv": None, "oi": 10, "volume": 1}


class SuggestionTests(unittest.TestCase):
    def test_highest_strike_worth_selling_then_a_balanced_one(self):
        spot, dte = 100.0, 30
        rows = [row(95, 7, 7.2, 0.7), row(105, 2.0, 2.1, 0.33), row(110, 1.0, 1.05, 0.2), row(115, 0.6, 0.65, 0.15),
                row(125, 0.3, 0.35, 0.08), row(140, 0.05, 0.1, 0.02), row(150, 0.4, 5.0, 0.01)]
        suggestions = builder.covered_call_suggestions(rows, spot, dte)
        # 125 pays 0.30 on the bid = 3.65% annualized < 6%; 115 pays 7.3% with delta 0.15 -> highest qualifying strike.
        self.assertEqual([s["role"] for s in suggestions], ["HIGH_STRIKE", "BALANCED"])
        self.assertEqual(suggestions[0]["strike"], 115)
        self.assertEqual(suggestions[1]["strike"], 105)  # delta nearest 0.30 below the first strike
        self.assertEqual(suggestions[0]["limit_price"], 0.62)  # mid 0.625 rounded down to the tick
        self.assertAlmostEqual(suggestions[0]["annualized_yield"], 0.62 / 100 * 365 / 30, places=6)

    def test_a_chain_without_delta_or_iv_is_capped_by_the_delta_its_quotes_imply(self):
        spot, dte, years = 100.0, 30, 30 / 365
        fair = lambda strike, vol: round(builder.bs_call_price(spot, strike, years, vol), 2)  # noqa: E731
        # 150 is quoted at a 160% volatility: it pays far more than 6% annualized, but the delta its quote implies is
        # over the 0.20 cap. 130 (45% volatility) pays too little; 120 (50%) is the highest strike within both limits.
        rows = [row(150, fair(150, 1.6) - 0.01, fair(150, 1.6) + 0.01), row(130, fair(130, 0.45) - 0.01, fair(130, 0.45) + 0.01),
                row(120, fair(120, 0.5) - 0.01, fair(120, 0.5) + 0.01), row(110, fair(110, 0.5) - 0.01, fair(110, 0.5) + 0.01)]
        suggestions = builder.covered_call_suggestions(rows, spot, dte)
        by_strike = {s["strike"]: s for s in suggestions}
        self.assertNotIn(150, by_strike)
        high = suggestions[0]
        self.assertEqual(high["role"], "HIGH_STRIKE")
        self.assertEqual(high["delta_basis"], "QUOTE_IMPLIED")
        self.assertLessEqual(high["delta"], builder.MAX_HIGH_STRIKE_DELTA)
        self.assertEqual(high["strike"], 120)
        self.assertAlmostEqual(high["iv"], 0.5, delta=0.02)
        self.assertAlmostEqual(high["delta"], builder.bs_call_delta(spot, high["strike"], years, high["iv"]), places=3)

    def test_implied_vol_inverts_the_price_and_rejects_impossible_quotes(self):
        price = builder.bs_call_price(100.0, 115.0, 0.1, 0.6)
        self.assertAlmostEqual(builder.implied_vol(price, 100.0, 115.0, 0.1), 0.6, places=3)
        self.assertIsNone(builder.implied_vol(100.0, 100.0, 115.0, 0.1))  # a call cannot cost the share
        self.assertIsNone(builder.implied_vol(0.0, 100.0, 115.0, 0.1))
        # A row whose quote implies no volatility has no assignment reference and cannot be the high strike.
        self.assertEqual(builder.covered_call_suggestions([row(115, 99.0, 99.5)], 100.0, 30), [])

    def test_the_delta_limit_is_checked_at_full_precision(self):
        # ChatGPT review counter-example: the quote implies delta 0.2003, which rounds to 0.200 for display.
        years = 30 / 365
        exact = builder.bs_call_delta(100.0, 110.0, years, builder.implied_vol(1.10, 100.0, 110.0, years), digits=None)
        self.assertGreater(exact, 0.20)
        self.assertEqual(round(exact, 3), 0.2)
        self.assertEqual(builder.covered_call_suggestions([row(110, 1.09, 1.11)], 100.0, 30), [])
        self.assertEqual(builder.covered_call_suggestions([row(110, 1.0, 1.05, 0.2)], 100.0, 30)[0]["strike"], 110)  # at the limit

    def test_quoted_iv_and_quoted_delta_keep_their_basis(self):
        iv_row = {**row(125, 0.50, 0.54), "iv": 0.8}
        suggestion = builder.covered_call_suggestions([iv_row], 100.0, 30)[0]
        self.assertEqual(suggestion["delta_basis"], "QUOTED_IV")
        self.assertEqual(suggestion["delta"], builder.bs_call_delta(100.0, 125.0, 30 / 365, 0.8))
        self.assertEqual(builder.covered_call_suggestions([row(120, 0.5, 0.54, 0.15)], 100.0, 30)[0]["delta_basis"], "QUOTED")

    def test_wide_spread_moves_the_limit_towards_the_bid_and_untradeable_quotes_are_ignored(self):
        suggestions = builder.covered_call_suggestions([row(120, 1.0, 1.6)], 100.0, 20)
        self.assertEqual(suggestions[0]["limit_price"], 1.15)  # spread 46% of mid -> bid + a quarter of the spread
        self.assertEqual(builder.covered_call_suggestions([row(120, 0.2, 2.0)], 100.0, 20), [])  # spread > mid

    def test_no_qualifying_strike_gives_an_explicit_reason(self):
        result = builder.cycle_result("X", "2026-10-23", 27, 100.0, [row(150, 0.01, 0.02, 0.01)], currency="USD", source="s",
                                      provenance="https://example.com", rights="unadmitted_third_party", stamp="2026-09-26T00:00:00Z")
        self.assertIn("unavailable", result)


class UniverseTests(unittest.TestCase):
    def test_carried_top20_tickers_join_the_universe_despite_the_state_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            lkg = Path(tmp)
            bundle = {"payloads": {"top20_json": json.dumps([{"ticker": "PATH"}, {"ticker": "AFRM"}])}}
            (lkg / "20260926T010000Z-0123456789ab.json").write_text(json.dumps(bundle), encoding="utf-8")
            (lkg / "refresh-state.json").write_text("{}", encoding="utf-8")
            saved = (builder.TOP20, builder.V3, builder.LAYERS)
            builder.TOP20, builder.V3, builder.LAYERS = lkg, lkg / "absent.json", lkg / "absent.json"
            try:
                self.assertEqual(builder.universe()[:2], ["PATH", "AFRM"])
                self.assertEqual(builder.universe()[2:], ["TSM", "UMC", "ASX"])  # ADRs answering their home listings' option queries
            finally:
                builder.TOP20, builder.V3, builder.LAYERS = saved


class BroadUniverseTests(unittest.TestCase):
    NOW = datetime(2026, 9, 26, 6, 0, tzinfo=timezone.utc)

    def fake_http(self, url):
        if url == builder.US_SCREENER:
            rows = [{"symbol": f"S{i}", "marketCap": str(1000 - i)} for i in range(250)]
            rows += [{"symbol": "BRK/B", "marketCap": "5000"}, {"symbol": "ZERO", "marketCap": ""}]
            return {"data": {"rows": rows}}
        if url == builder.STOCKHOLM_LARGE_CAP:
            return {"data": {"instrumentListing": {"rows": [
                {"symbol": "VOLV B", "orderbookId": "TX100", "assetClass": "SHARES", "currency": "SEK"},
                {"symbol": "NOOPT", "orderbookId": "TX1", "assetClass": "SHARES", "currency": "SEK"},
                {"symbol": "EURO", "orderbookId": "TX2", "assetClass": "SHARES", "currency": "EUR"}]}}}
        chain_rows = {"TX100": [{"assetClass": "FUTURES_FORWARDS"}, {"assetClass": "OPTIONS"}], "TX1": [{"assetClass": "FUTURES_FORWARDS"}]}
        orderbook = url.split("/instruments/")[1].split("/")[0]
        return {"data": {"instrumentListing": {"rows": chain_rows.get(orderbook, [])}}}

    def test_largest_us_listings_and_optionable_stockholm_large_caps(self):
        saved = builder.http_json
        builder.http_json = self.fake_http
        try:
            document = builder.build_broad(self.NOW)
        finally:
            builder.http_json = saved
        self.assertEqual(len(document["us"]), builder.US_LARGEST)
        self.assertEqual(document["us"][:2], ["BRK-B", "S0"])  # by market cap; Yahoo class-share symbol
        self.assertNotIn("ZERO", document["us"])
        self.assertEqual(document["sweden"], {"VOLV-B.ST": "TX100"})  # no options / not SEK -> excluded

    def test_cache_is_reused_then_rebuilt_and_a_failed_rebuild_keeps_a_recent_list(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "broad.json"
            cached = {"schema": "v213-options-universe-v1", "generated_at": "2026-09-26T00:00:00Z", "us": ["AAPL"],
                      "sweden": {"VOLV-B.ST": "TX100"}}
            saved = builder.build_broad
            try:
                path.write_text(json.dumps(dict(cached, sweden={})), encoding="utf-8")  # an empty list is never reused
                builder.build_broad = lambda now: (_ for _ in ()).throw(OSError("offline"))
                self.assertEqual(builder.broad_universe(self.NOW, path), {"us": [], "sweden": {}})
                path.write_text(json.dumps(cached), encoding="utf-8")
                builder.build_broad = lambda now: (_ for _ in ()).throw(AssertionError("fresh cache must be reused"))
                self.assertEqual(builder.broad_universe(self.NOW, path)["us"], ["AAPL"])
                later = self.NOW + timedelta(days=2)
                builder.build_broad = lambda now: (_ for _ in ()).throw(OSError("offline"))
                self.assertEqual(builder.broad_universe(later, path)["us"], ["AAPL"])  # stale but within 7 days
                self.assertEqual(builder.broad_universe(self.NOW + timedelta(days=8), path), {"us": [], "sweden": {}})
                rebuilt = dict(cached, generated_at="2026-09-28T06:00:00Z", us=["MSFT"])
                builder.build_broad = lambda now: rebuilt
                self.assertEqual(builder.broad_universe(later, path)["us"], ["MSFT"])
                self.assertEqual(json.loads(path.read_text(encoding="utf-8"))["us"], ["MSFT"])
            finally:
                builder.build_broad = saved

    def test_futures_rows_in_a_nordic_chain_are_not_calls(self):
        chain = [{"fullName": "VOLVB 16OCT26 FUTC", "assetClass": "FUTURES_FORWARDS", "expirationDate": "2026-10-16",
                  "strikePrice": "0.00", "bidPrice": "300", "askPrice": "301", "contractSize": "100"},
                 {"fullName": "VOLVB 23OCT26 330C", "assetClass": "OPTIONS", "expirationDate": "2026-10-23",
                  "strikePrice": "330.00", "bidPrice": "2.00", "askPrice": "2.10", "contractSize": "100"}]
        seen = []

        def fake_http(url):
            seen.append(url)
            return {"data": {"instrumentListing": {"rows": chain}}}
        saved = builder.http_json
        builder.http_json = fake_http
        try:
            out = builder.nordic_options("VOLV-B.ST", "VOLV-B", 310.0, self.NOW.date(), "2026-09-26T06:00:00Z", "TX100")
        finally:
            builder.http_json = saved
        self.assertEqual(seen, [builder.NORDIC_CHAIN.format(orderbook="TX100")])  # known order book: no search
        self.assertEqual(out["monthly"]["ticker"], "VOLV-B")
        self.assertEqual(out["monthly"]["suggestions"][0]["strike"], 330.0)
        self.assertIn("unavailable", out["weekly"])  # no call expires within 3-14 days

    def test_markets_never_share_a_key_and_one_failure_never_aborts_the_run(self):
        class FakeTicker:
            def __init__(self, symbol):
                if symbol == "BROKEN":
                    raise RuntimeError("quote failed")
                self.fast_info = {"lastPrice": 100.0, "previousClose": 99.0, "currency": "SEK" if symbol.endswith(".ST") else "USD"}
        calls = []

        def fake_us(symbol, spot, today, stamp):
            if symbol == "BAD":
                raise ValueError("malformed expiry")
            return {"weekly": {"unavailable": f"US {symbol}"}}

        def fake_nordic(symbol, base, spot, today, stamp, orderbook=None):
            calls.append((symbol, orderbook))
            return {"weekly": {"unavailable": f"STO {base}"}}
        saved = (sys.modules.get("yfinance"), builder.us_options, builder.nordic_options, builder.broad_universe, builder.universe,
                 builder.nasdaq_us_options, builder.alpha_vantage_quote)
        sys.modules["yfinance"] = type(sys)("yfinance")
        sys.modules["yfinance"].Ticker = FakeTicker
        builder.us_options, builder.nordic_options = fake_us, fake_nordic
        builder.nasdaq_us_options = lambda symbol, spot, today, stamp: {"weekly": {"unavailable": "Nasdaq 期權鏈讀取失敗"}}
        builder.alpha_vantage_quote = lambda symbol, stamp: None
        builder.broad_universe = lambda now: {"us": ["AZN", "BAD", "BROKEN"], "sweden": {"AZN.ST": "TX9", "VOLV-B.ST": "TX100"}}
        builder.universe = lambda: ["NVDA", "SIVE.ST", "2330.TW"]
        try:
            document = builder.build(self.NOW)
        finally:
            (yf, builder.us_options, builder.nordic_options, builder.broad_universe, builder.universe,
             builder.nasdaq_us_options, builder.alpha_vantage_quote) = saved
            if yf is None:
                sys.modules.pop("yfinance", None)
            else:
                sys.modules["yfinance"] = yf
        options = document["options"]
        self.assertEqual(sorted(options), ["AZN", "AZN.ST", "BAD", "NVDA", "SIVE.ST", "VOLV-B.ST"])
        self.assertEqual(options["AZN"]["weekly"]["unavailable"], "US AZN")
        self.assertEqual(options["AZN.ST"]["weekly"]["unavailable"], "STO AZN")
        self.assertIn("讀取失敗", options["BAD"]["weekly"]["unavailable"])  # the quote stays, the chain is unavailable
        self.assertIn("BAD", document["quotes"])
        self.assertNotIn("BROKEN", document["quotes"])
        self.assertIn("2330.TW", document["quotes"])  # quote only: no listed-option source for Taiwan here
        self.assertEqual(sorted(calls), [("AZN.ST", "TX9"), ("SIVE.ST", None), ("VOLV-B.ST", "TX100")])

    def _run_build(self, observe, symbols, deadline_seconds):
        saved = (builder.observe, builder.broad_universe, builder.universe)
        builder.observe = observe
        builder.broad_universe = lambda now: {"us": [], "sweden": {}}
        builder.universe = lambda: list(symbols)
        try:
            import time as clock
            started = clock.monotonic()
            document = builder.build(self.NOW, deadline_seconds=deadline_seconds)
            return document, clock.monotonic() - started
        finally:
            builder.observe, builder.broad_universe, builder.universe = saved

    @staticmethod
    def _quote(symbol):
        return {"symbol": symbol, "price": 100.0}

    def test_a_slow_source_is_cut_at_the_deadline_and_never_blocks_the_run(self):
        import threading
        never = threading.Event()  # never set: the hung workers are abandoned, not released

        def observe(symbol, today, stamp, orderbook=None):
            if symbol.startswith("SLOW"):
                never.wait()
            return self._quote(symbol), symbol, {"weekly": {"unavailable": "x"}}
        symbols = [f"FAST{i}" for i in range(12)] + [f"SLOW{i}" for i in range(8)]
        document, elapsed = self._run_build(observe, symbols, deadline_seconds=0.5)
        self.assertLess(elapsed, 2.0)  # bounded by the deadline, not by the hung requests
        self.assertEqual(document["collection"]["underlyings"], 20)
        # The snapshot and the count agree: every underlying is either in the document or counted unfinished.
        self.assertEqual(len(document["quotes"]) + document["collection"]["unfinished"], 20)
        self.assertFalse(any(symbol.startswith("SLOW") for symbol in document["quotes"]))

    def _cli(self, script: str, timeout: float = 30.0):
        """Runs a collector scenario in a separate interpreter and returns (exit code, seconds, stdout)."""
        import subprocess
        import time as clock
        prelude = (f"import sys, threading, time, json\nsys.path.insert(0, {str(ROOT / 'scripts')!r})\n"
                   "import build_market_quotes_options as b\n")
        started = clock.monotonic()
        done = subprocess.run([sys.executable, "-c", prelude + script], capture_output=True, text=True, timeout=timeout)
        return done.returncode, clock.monotonic() - started, done.stdout + done.stderr

    def test_the_cli_exits_at_the_deadline_with_hung_workers_and_keeps_the_last_good_file(self):
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder) / "market.json"
            output.write_text('{"previous": true}', encoding="utf-8")
            # Most underlyings hang forever: the run is incomplete, so the previous file stays and the process still exits.
            code, seconds, log = self._cli(
                "b.COLLECTION_DEADLINE_SECONDS = 1.0\n"
                "b.broad_universe = lambda now: {'us': [], 'sweden': {}}\n"
                "b.universe = lambda: [f'F{i}' for i in range(12)] + [f'H{i}' for i in range(30)]\n"
                "def observe(symbol, today, stamp, orderbook=None):\n"
                "    if symbol.startswith('H'): threading.Event().wait()\n"
                "    return {'symbol': symbol, 'price': 1.0}, symbol, {}\n"
                "b.observe = observe\n"
                f"sys.exit(b.main(['--output', {str(output)!r}]))\n")
            self.assertEqual(code, 1, log)
            self.assertIn("DEADLINE_INCOMPLETE", log)
            self.assertLess(seconds, 15.0, log)
            self.assertEqual(output.read_text(encoding="utf-8"), '{"previous": true}')
            # A few hung underlyings: the finished ones are published and the process exits despite the stuck workers.
            code, seconds, log = self._cli(
                "b.COLLECTION_DEADLINE_SECONDS = 1.0\n"
                "b.broad_universe = lambda now: {'us': [], 'sweden': {}}\n"
                "b.universe = lambda: [f'F{i}' for i in range(20)] + [f'H{i}' for i in range(3)]\n"
                "def observe(symbol, today, stamp, orderbook=None):\n"
                "    if symbol.startswith('H'): threading.Event().wait()\n"
                "    return {'symbol': symbol, 'price': 1.0}, symbol, {}\n"
                "b.observe = observe\n"
                f"sys.exit(b.main(['--output', {str(output)!r}]))\n")
            self.assertEqual(code, 0, log)
            self.assertLess(seconds, 15.0, log)
            written = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(sorted(written["quotes"]), sorted(f"F{i}" for i in range(20)))
            self.assertEqual(written["collection"]["unfinished"], 3)

    # A fake urlopen for the universe sources: screener bodies in full or trickling one byte every 0.2 s forever.
    _FAKE_SOURCES = (
        "import urllib.request\n"
        "class Body:\n"
        "    def __init__(self, data=None): self.data = data\n"
        "    def __enter__(self): return self\n"
        "    def __exit__(self, *exc): return False\n"
        "    def read(self, size=-1):\n"
        "        if self.data is None:\n"
        "            time.sleep(0.2); return b' '\n"
        "        data, self.data = self.data, b''\n"
        "        return data\n"
        "US = json.dumps({'data': {'rows': [{'symbol': f'S{i}', 'marketCap': str(1000 - i)} for i in range(250)]}}).encode()\n"
        "STO = json.dumps({'data': {'instrumentListing': {'rows': [{'symbol': f'N{i}', 'orderbookId': f'TX{i}', "
        "'assetClass': 'SHARES', 'currency': 'SEK'} for i in range(10)]}}}).encode()\n")

    def test_a_universe_body_that_never_finishes_is_cut_and_the_last_good_file_stays(self):
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder) / "market.json"
            output.write_text('{"previous": true}', encoding="utf-8")
            code, seconds, log = self._cli(
                self._FAKE_SOURCES
                + "urllib.request.urlopen = lambda request, timeout=None: Body()\n"  # headers arrive, the body never ends
                "b.REQUEST_TIMEOUT_SECONDS = 1.0\n"
                "b.COLLECTION_DEADLINE_SECONDS = 4.0\n"
                f"b.BROAD = __import__('pathlib').Path({str(Path(folder) / 'universe.json')!r})\n"
                "b.universe = lambda: []\n"
                f"sys.exit(b.main(['--output', {str(output)!r}]))\n")
            self.assertLess(seconds, 12.0, log)
            self.assertEqual(code, 1, log)  # nothing observed
            self.assertEqual(output.read_text(encoding="utf-8"), '{"previous": true}')
            self.assertFalse((Path(folder) / "universe.json").exists())

    def test_a_hanging_nordic_check_falls_back_to_the_cached_universe_within_the_deadline(self):
        with tempfile.TemporaryDirectory() as folder:
            output, cache = Path(folder) / "market.json", Path(folder) / "universe.json"
            cached = {"schema": "v213-options-universe-v1", "generated_at": "2020-01-01T00:00:00Z",
                      "us": [f"C{i}" for i in range(12)], "sweden": {"OLD.ST": "TX9"}}
            code, seconds, log = self._cli(
                self._FAKE_SOURCES
                + "def urlopen(request, timeout=None):\n"
                "    url = request.full_url\n"
                "    if url == b.US_SCREENER: return Body(US)\n"
                "    if url == b.STOCKHOLM_LARGE_CAP: return Body(STO)\n"
                "    return Body()\n"  # every Nordic option-chain body trickles forever
                "urllib.request.urlopen = urlopen\n"
                "b.REQUEST_TIMEOUT_SECONDS = 1.0\n"
                "b.COLLECTION_DEADLINE_SECONDS = 4.0\n"
                f"b.BROAD = __import__('pathlib').Path({str(cache)!r})\n"
                # the cache is older than a day (rebuild) but younger than a week (fallback): dated at run time
                "doc = json.loads(" + repr(json.dumps(cached)) + ")\n"
                "doc['generated_at'] = (__import__('datetime').datetime.now(__import__('datetime').timezone.utc)"
                " - __import__('datetime').timedelta(days=2)).strftime('%Y-%m-%dT%H:%M:%SZ')\n"
                "b.BROAD.write_text(json.dumps(doc), encoding='utf-8')\n"
                "before = b.BROAD.read_bytes()\n"
                "b.universe = lambda: []\n"
                "b.observe = lambda symbol, today, stamp, orderbook=None: ({'symbol': symbol, 'price': 1.0}, symbol, {})\n"
                f"code = b.main(['--output', {str(output)!r}])\n"
                "print(json.dumps({'cache_unchanged': b.BROAD.read_bytes() == before}))\n"
                "sys.exit(code)\n")
            self.assertLess(seconds, 12.0, log)
            self.assertEqual(code, 0, log)
            written = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(sorted(written["quotes"]), sorted([f"C{i}" for i in range(12)] + ["OLD.ST"]))
            self.assertTrue(json.loads(log.strip().splitlines()[-1])["cache_unchanged"])

    def test_a_slow_universe_rebuild_is_inside_the_deadline(self):
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder) / "market.json"
            # Every public request hangs until its timeout: the universe rebuild and the observations share one deadline,
            # each request's timeout is cut to the time left, and nothing starts after it.
            code, seconds, log = self._cli(
                "import urllib.request\n"
                "b.COLLECTION_DEADLINE_SECONDS = 2.0\n"
                f"b.BROAD = __import__('pathlib').Path({str(Path(folder) / 'universe.json')!r})\n"
                "calls = []\n"
                "def hang(request, timeout=None):\n"
                "    calls.append(timeout); time.sleep(timeout); raise TimeoutError('hung source')\n"
                "urllib.request.urlopen = hang\n"
                "b.universe = lambda: []\n"
                f"code = b.main(['--output', {str(output)!r}])\n"
                "print(json.dumps({'calls': len(calls), 'max_timeout': max(calls or [0])}))\n"
                "sys.exit(code)\n")
            self.assertLess(seconds, 12.0, log)
            self.assertNotEqual(code, 0, log)  # nothing observed: not published
            self.assertFalse(output.exists())
            stats = json.loads(log.strip().splitlines()[-1])
            self.assertLessEqual(stats["max_timeout"], 2.0)

    def test_a_rate_limited_underlying_is_left_out_and_the_others_complete(self):
        import urllib.error

        def observe(symbol, today, stamp, orderbook=None):
            if symbol == "LIMITED":
                raise urllib.error.HTTPError("https://example.invalid", 429, "Too Many Requests", {}, None)
            return self._quote(symbol), symbol, {}
        document, _ = self._run_build(observe, ["A", "LIMITED", "B"], deadline_seconds=5)
        self.assertEqual(sorted(document["quotes"]), ["A", "B"])
        self.assertEqual(document["collection"], {"underlyings": 3, "unfinished": 0, "deadline_seconds": 5,
                                                   "chain_health": {"US": {"read": 0, "healthy": 0, "expiry_list_error": 0, "empty_response": 0, "no_expiry": 0, "read_error": 0, "empty": 0},
                                                                    "STOCKHOLM": {"read": 0, "healthy": 0, "expiry_list_error": 0, "empty_response": 0, "no_expiry": 0, "read_error": 0, "empty": 0}}})

    def test_a_run_cut_short_for_most_underlyings_keeps_the_previous_file(self):
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder) / "market.json"
            output.write_text('{"previous": true}', encoding="utf-8")
            saved = builder.build
            builder.build = lambda now: {"quotes": {f"S{i}": {} for i in range(40)}, "options": {},
                                         "collection": {"underlyings": 100, "unfinished": 60, "deadline_seconds": 1200}}
            try:
                code = builder.main(["--output", str(output)])
            finally:
                builder.build = saved
            self.assertEqual(code, 1)
            self.assertEqual(output.read_text(encoding="utf-8"), '{"previous": true}')

    def test_an_unreadable_option_check_keeps_the_previous_list(self):
        def flaky(url):
            if "/instruments/" in url:
                raise OSError("429")
            return self.fake_http(url)
        saved = builder.http_json
        builder.http_json = flaky
        try:
            with self.assertRaises(ValueError):
                builder.build_broad(self.NOW)
        finally:
            builder.http_json = saved


class FallbackTests(unittest.TestCase):
    TODAY = datetime(2026, 9, 26, tzinfo=timezone.utc).date()
    STAMP = "2026-09-26T06:00:00Z"

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.saved = (builder.http_json, builder.us_options, builder.nasdaq_us_options, builder.alpha_vantage_key, builder.ALPHA_VANTAGE_BUDGET)
        builder.ALPHA_VANTAGE_BUDGET = Path(self.tmp.name) / "budget.json"
        self.urls = []

    def tearDown(self):
        (builder.http_json, builder.us_options, builder.nasdaq_us_options, builder.alpha_vantage_key, builder.ALPHA_VANTAGE_BUDGET) = self.saved
        self.tmp.cleanup()

    def test_nasdaq_us_chain_parses_expiry_groups_without_a_delta(self):
        def fake_http(url):
            self.urls.append(url)
            rows = [{"expirygroup": "October 2, 2026"},
                    {"expirygroup": "", "strike": "240.00", "c_Bid": "1.10", "c_Ask": "1.20", "c_Openinterest": "1,200", "c_Volume": "--"},
                    {"expirygroup": "October 23, 2026"},
                    {"expirygroup": "", "strike": "250.00", "c_Bid": "2.00", "c_Ask": "2.10", "c_Openinterest": "--", "c_Volume": "7"},
                    {"expirygroup": "", "strike": "260.00", "c_Bid": "--", "c_Ask": "0.90", "c_Openinterest": "5", "c_Volume": "1"}]
            return {"data": {"table": {"rows": rows}}}
        builder.http_json = fake_http
        out = builder.nasdaq_us_options("BRK-B", 225.0, self.TODAY, self.STAMP)
        self.assertIn("/quote/brk.b/option-chain", self.urls[0])
        self.assertIn("fromdate=2026-09-29", self.urls[0])
        self.assertEqual((out["weekly"]["expiry"], out["weekly"]["dte"]), ("2026-10-02", 6))
        self.assertEqual((out["monthly"]["expiry"], out["monthly"]["suggestions"][0]["strike"]), ("2026-10-23", 250.0))
        weekly = out["weekly"]["suggestions"][0]
        self.assertEqual(weekly["delta_basis"], "QUOTE_IMPLIED")  # the chain has no delta or IV: implied by the quote
        self.assertLessEqual(weekly["delta"], builder.MAX_HIGH_STRIKE_DELTA)
        self.assertEqual(out["weekly"]["suggestions"][0]["oi"], 1200)
        self.assertTrue(out["weekly"]["provenance"].startswith("https://www.nasdaq.com/"))
        self.assertEqual(out["weekly"]["rights_status"], "candidate_local_review")
        builder.http_json = lambda url: (_ for _ in ()).throw(OSError("blocked"))
        self.assertEqual(builder.nasdaq_us_options("NVDA", 225.0, self.TODAY, self.STAMP)["monthly"]["unavailable"], "Nasdaq 期權鏈讀取失敗")

    def test_only_cycles_yahoo_could_not_read_fall_back_to_nasdaq(self):
        calls = []
        good = {"ticker": "NVDA", "expiry": "2026-10-23"}
        builder.nasdaq_us_options = lambda symbol, spot, today, stamp: calls.append(symbol) or {"weekly": good, "monthly": good}
        builder.us_options = lambda symbol, spot, today, stamp: {"weekly": {"unavailable": "期權鏈讀取失敗"},
                                                                 "monthly": {"unavailable": "2026-10-23 到期的價外買權中，沒有年化權利金達 6%"}}
        out = builder.us_cycles("NVDA", 225.0, self.TODAY, self.STAMP)
        self.assertEqual(out["weekly"], good)
        self.assertIn("沒有年化權利金", out["monthly"]["unavailable"])  # a read chain keeps its own reason
        builder.us_options = lambda symbol, spot, today, stamp: {"weekly": good, "monthly": good}
        builder.us_cycles("NVDA", 225.0, self.TODAY, self.STAMP)
        self.assertEqual(calls, ["NVDA"])  # no Nasdaq request when Yahoo read every cycle
        builder.us_options = lambda symbol, spot, today, stamp: (_ for _ in ()).throw(ValueError("yahoo down"))
        builder.nasdaq_us_options = lambda symbol, spot, today, stamp: {c: {"unavailable": "Nasdaq 期權鏈讀取失敗"} for c in builder.CYCLES}
        out = builder.us_cycles("NVDA", 225.0, self.TODAY, self.STAMP)
        self.assertEqual(out["monthly"]["unavailable"], "期權鏈讀取失敗（Yahoo 與 Nasdaq 備援）")

    def test_alpha_vantage_quote_needs_a_key_keeps_a_daily_budget_and_never_exposes_the_key(self):
        def fake_http(url):
            self.urls.append(url)
            return {"Global Quote": {"05. price": "225.07", "08. previous close": "220.00", "07. latest trading day": "2026-09-25"}}
        builder.http_json = fake_http
        builder.alpha_vantage_key = lambda: None
        self.assertIsNone(builder.alpha_vantage_quote("NVDA", self.STAMP))
        self.assertEqual(self.urls, [])  # no key, no request
        builder.alpha_vantage_key = lambda: "TESTKEY9"
        quote = builder.alpha_vantage_quote("NVDA", self.STAMP)
        self.assertEqual((quote["price"], quote["asof"], quote["currency"]), (225.07, "2026-09-25", "USD"))
        self.assertAlmostEqual(quote["change_pct"], 225.07 / 220 - 1)
        self.assertNotIn("TESTKEY9", json.dumps(quote))
        self.assertTrue(quote["source_url"].startswith("https://www.alphavantage.co/query?function=GLOBAL_QUOTE&symbol=NVDA"))
        self.assertIn("apikey=TESTKEY9", self.urls[0])
        for _ in range(builder.ALPHA_VANTAGE_DAILY_BUDGET - 1):
            self.assertIsNotNone(builder.alpha_vantage_quote("NVDA", self.STAMP))
        self.assertIsNone(builder.alpha_vantage_quote("NVDA", self.STAMP))
        self.assertEqual(len(self.urls), builder.ALPHA_VANTAGE_DAILY_BUDGET)  # the budget stops requests, not only results
        self.assertIsNotNone(builder.alpha_vantage_quote("NVDA", "2026-09-27T06:00:00Z"))  # a new UTC day

    def test_observe_uses_the_alpha_vantage_quote_only_for_us_listings_yahoo_cannot_quote(self):
        class DownTicker:
            def __init__(self, symbol):
                raise RuntimeError("yahoo down")
        saved = (sys.modules.get("yfinance"), builder.alpha_vantage_quote, builder.us_cycles)
        sys.modules["yfinance"] = type(sys)("yfinance")
        sys.modules["yfinance"].Ticker = DownTicker
        asked = []
        builder.alpha_vantage_quote = lambda symbol, stamp: asked.append(symbol) or {"symbol": symbol, "price": 225.07, "source": "Alpha Vantage"}
        builder.us_cycles = lambda symbol, spot, today, stamp: {"weekly": {"unavailable": f"spot {spot}"}}
        try:
            quote, key, cycles = builder.observe("NVDA", self.TODAY, self.STAMP)
            self.assertIsNone(builder.observe("2330.TW", self.TODAY, self.STAMP))
        finally:
            yf, builder.alpha_vantage_quote, builder.us_cycles = saved
            if yf is None:
                sys.modules.pop("yfinance", None)
            else:
                sys.modules["yfinance"] = yf
        self.assertEqual((quote["source"], key, cycles["weekly"]["unavailable"]), ("Alpha Vantage", "NVDA", "spot 225.07"))
        self.assertEqual(asked, ["NVDA"])

    def test_a_rate_limit_reply_spends_the_day(self):
        builder.alpha_vantage_key = lambda: "K"
        builder.http_json = lambda url: self.urls.append(url) or {"Information": "standard API rate limit is 25 requests per day"}
        self.assertIsNone(builder.alpha_vantage_quote("NVDA", self.STAMP))
        self.assertIsNone(builder.alpha_vantage_quote("AMD", self.STAMP))
        self.assertEqual(len(self.urls), 1)


class SealingTests(unittest.TestCase):
    def cycle(self, now):
        expiry = (now + timedelta(days=27)).date().isoformat()
        return builder.cycle_result("NVDA", expiry, 27, 225.0, [row(245, 1.5, 1.55, 0.17), row(235, 3.65, 3.8, 0.33)], currency="USD",
                                    source="Yahoo", provenance="https://finance.yahoo.com/x", rights="unadmitted_third_party",
                                    stamp=now.strftime("%Y-%m-%dT%H:%M:%SZ"))

    def test_validator_and_sealing(self):
        now = datetime.now(timezone.utc).replace(microsecond=0)
        stamp = now.strftime("%Y-%m-%dT%H:%M:%SZ")
        good = self.cycle(now)
        validate_covered_call_cycle(good, evaluated_at=stamp)
        tampered = json.loads(json.dumps(good))
        tampered["suggestions"][0]["limit_price"] = 9.0
        with self.assertRaises(MarketProductValidationError):
            validate_covered_call_cycle(tampered, evaluated_at=stamp)
        self.assertEqual(good["suggestions"][0]["delta_basis"], "QUOTED")
        at_limit = json.loads(json.dumps(good))
        at_limit["suggestions"][0]["delta"] = 0.2
        validate_covered_call_cycle(at_limit, evaluated_at=stamp)  # exactly 0.20 passes
        for key, value in (("delta_basis", "GUESSED"), ("iv", 0.0), ("delta", None), ("delta", 0.2000000005),
                           ("delta", 0.2001), ("delta", 0.9), ("delta", -0.01), ("delta", float("inf"))):
            bad = json.loads(json.dumps(good))
            bad["suggestions"][0][key] = value
            with self.assertRaises(MarketProductValidationError):
                validate_covered_call_cycle(bad, evaluated_at=stamp)
        doc = {"schema": "v213-market-observations-v2", "generated_at": stamp, "quotes": {"NVDA": {"symbol": "NVDA", "price": 225.0}},
               "options": {"NVDA": {"monthly": good, "weekly": tampered}, "SIVE": {"weekly": {"unavailable": "無週期權"}}}}
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "obs.json"
            path.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
            bodies = publisher.lazy_market_bodies(path, now)
            options = json.loads(bodies["v213:options:v2"])
            self.assertEqual(options["schema"], "v213-options-v2")
            self.assertEqual(options["options"]["NVDA"]["monthly"]["suggestions"][0]["strike"], 245)
            self.assertIn("未通過驗證", options["options"]["NVDA"]["weekly"]["unavailable"])
            self.assertEqual(publisher.lazy_market_bodies(path, now + timedelta(hours=6)), {})


CallRow = namedtuple("CallRow", ["strike", "bid", "ask", "impliedVolatility", "openInterest", "volume", "lastPrice"],
                     defaults=(None, None, None, None, None, None, None))


class FakeOptionChainCalls:
    def __init__(self, rows: list[Any]):
        self._rows = rows

    def itertuples(self):
        return iter(self._rows)


class FakeOptionChain:
    def __init__(self, rows: list[Any]):
        self.calls = FakeOptionChainCalls(rows)


class FakeTicker:
    def __init__(self, symbol: str, price: float = 100.0, previous_close: float = 99.0,
                 currency: str = "USD", options: list[str] | Exception | None = None,
                 chains: dict[str, list[Any] | Exception] | None = None,
                 fast_info: dict[str, Any] | None = None):
        self.symbol = symbol
        self._fast_info = fast_info if fast_info is not None else {
            "lastPrice": price, "previousClose": previous_close, "currency": currency
        }
        self._options = options
        self._chains = chains or {}

    @property
    def fast_info(self) -> dict[str, Any]:
        return self._fast_info

    @property
    def options(self) -> list[str]:
        if isinstance(self._options, Exception):
            raise self._options
        if self._options is None:
            return []
        return self._options

    def option_chain(self, expiry: str) -> FakeOptionChain:
        chain_or_exc = self._chains.get(expiry)
        if isinstance(chain_or_exc, Exception):
            raise chain_or_exc
        if chain_or_exc is None:
            return FakeOptionChain([])
        return FakeOptionChain(chain_or_exc)


class FakeYFinanceModule:
    def __init__(self, tickers: dict[str, Any] | None = None, default_factory: Callable[[str], Any] | None = None):
        self.tickers = dict(tickers or {})
        self.default_factory = default_factory
        self.requested_symbols: list[str] = []

    def Ticker(self, symbol: str):
        self.requested_symbols.append(symbol)
        if symbol in self.tickers:
            t = self.tickers[symbol]
            if isinstance(t, Exception):
                raise t
            return t
        if self.default_factory:
            return self.default_factory(symbol)
        return FakeTicker(symbol)


class OptionPresessionAcceptanceTests(unittest.TestCase):
    NOW = datetime(2026, 9, 28, 6, 0, tzinfo=timezone.utc)
    STAMP = "2026-09-28T06:00:00Z"
    TODAY = NOW.date()

    def setUp(self):
        self.saved_yf = sys.modules.get("yfinance")
        self.saved_broad = builder.broad_universe
        self.saved_univ = builder.universe
        self.saved_now = builder.utc_now
        self.saved_av_key = builder.alpha_vantage_key
        self.saved_http = builder.http_json
        self.saved_urlopen = urllib.request.urlopen
        builder.alpha_vantage_key = lambda: None
        builder.utc_now = lambda: self.NOW
        builder.broad_universe = lambda now: {"us": [], "sweden": {}}
        builder.universe = lambda: []
        builder.http_json = lambda url: {"data": {"table": {"rows": []}, "instrumentListing": {"rows": []}}}

        def blocked_urlopen(*args, **kwargs):
            raise AssertionError("Hermetic test violation: external network request attempted!")
        urllib.request.urlopen = blocked_urlopen

    def tearDown(self):
        if self.saved_yf is None:
            sys.modules.pop("yfinance", None)
        else:
            sys.modules["yfinance"] = self.saved_yf
        builder.broad_universe = self.saved_broad
        builder.universe = self.saved_univ
        builder.utc_now = self.saved_now
        builder.alpha_vantage_key = self.saved_av_key
        builder.http_json = self.saved_http
        urllib.request.urlopen = self.saved_urlopen

    def _run_main_capture(self, argv: list[str]) -> tuple[int, dict[str, Any] | None, str]:
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = builder.main(argv)
        raw = buf.getvalue()
        first_line = raw.strip().splitlines()[0] if raw.strip() else ""
        try:
            data = json.loads(first_line)
        except Exception:
            data = None
        return code, data, raw

    def _make_prior_file(self, path: Path, *, generated_at: str = "2026-09-28T05:00:00Z",
                         status_unavailable: bool = False, corrupt: bool = False,
                         price: float = 123.45, asof: str | None = None,
                         source: str = "Yahoo Finance (unofficial, delayed)",
                         source_url: str = "https://finance.yahoo.com/quote/PRIOR") -> bytes:
        if corrupt:
            raw = b'{"schema": "v213-market-observations-v2", "generated_at": "' + generated_at.encode("utf-8") + b'", corrupt'
            path.write_bytes(raw)
            return raw
        try:
            base_t = datetime.strptime(generated_at, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        except ValueError:
            base_t = datetime(2026, 9, 28, 5, 0, tzinfo=timezone.utc)
        expiry = (base_t + timedelta(days=25)).date().isoformat()
        quote_asof = asof or generated_at
        if status_unavailable:
            opt_entry = {"monthly": {"unavailable": "prior unavailable"}}
        else:
            opt_entry = {
                "monthly": {
                    "ticker": "PRIOR", "strategy": "COVERED_CALL", "expiry": expiry, "dte": 25,
                    "spot": price, "currency": "USD", "multiplier": 100, "quote_basis": "delayed",
                    "timestamp": generated_at, "source": "Yahoo", "provenance": "https://example.com/prior",
                    "rights_status": "unadmitted_third_party",
                    "suggestions": [{
                        "role": "HIGH_STRIKE", "strike": 140.0, "bid": 2.0, "ask": 2.1, "mid": 2.05,
                        "limit_price": 2.05, "premium_per_contract": 205.0, "period_yield": 2.05 / price,
                        "annualized_yield": 2.05 / price * 365 / 25, "upside_to_strike": 140.0 / price - 1,
                        "delta": 0.15, "delta_basis": "QUOTE_IMPLIED", "iv": 0.45, "oi": 50, "volume": 20, "spread_pct": 0.0488
                    }]
                }
            }
        doc = {
            "schema": "v213-market-observations-v2",
            "generated_at": generated_at,
            "quotes": {"PRIOR": {"symbol": "PRIOR", "display": "PRIOR", "price": price, "previous_close": price * 0.98,
                                 "change_pct": 0.0204, "currency": "USD", "asof": quote_asof,
                                 "source": source, "source_url": source_url}},
            "options": {"PRIOR": opt_entry},
            "collection": {"underlyings": 1, "unfinished": 0, "deadline_seconds": 1200}
        }
        raw = json.dumps(doc, ensure_ascii=False).encode("utf-8")
        path.write_bytes(raw)
        return raw

    def test_01_reported_failure_shape_us_collapse_preserves_prior(self):
        """Matrix Item 1: >=10 fresh quotes and read US chains dominated by zero bid/ask, with lastPrice/volume
        present; retain one genuine two-sided/qualifying chain among at least 11 read chains. With a previous
        valid file, main returns 1, exact error/counts are emitted, and old bytes/mtime are unchanged. A valid
        Nordic cycle does not mask US failure."""
        with tempfile.TemporaryDirectory() as tmp:
            out_path = Path(tmp) / "market_quotes_options.json"
            staging_path = out_path.with_name(out_path.name + ".tmp")
            prior_bytes = self._make_prior_file(out_path)
            prior_mtime = out_path.stat().st_mtime_ns

            staging_bytes = b'{"staging": "preexisting_staging_content"}'
            staging_path.write_bytes(staging_bytes)
            staging_mtime = staging_path.stat().st_mtime_ns

            us_symbols = [f"US_{i}" for i in range(11)]  # 11 US underlyings: 10 zero bid/ask, 1 healthy
            expiry_date = "2026-10-23"  # DTE 25 relative to 2026-09-28 (monthly)

            tickers = {}
            for i, sym in enumerate(us_symbols):
                if i == 0:
                    # 1 healthy two-sided chain with lastPrice and volume present
                    calls = [CallRow(strike=115.0, bid=2.0, ask=2.1, lastPrice=2.05, volume=100, openInterest=50, impliedVolatility=0.35)]
                else:
                    # 10 zero bid/ask rows with lastPrice and volume present (reported failure shape!)
                    calls = [CallRow(strike=110.0, bid=0.0, ask=0.0, lastPrice=9.0, volume=100, openInterest=50, impliedVolatility=0.35)]
                tickers[sym] = FakeTicker(sym, price=100.0, options=[expiry_date], chains={expiry_date: calls})

            # SIVE.ST is a healthy Nordic cycle
            tickers["SIVE.ST"] = FakeTicker("SIVE.ST", price=100.0, currency="SEK")

            sys.modules["yfinance"] = FakeYFinanceModule(tickers)
            builder.broad_universe = lambda now: {"us": us_symbols, "sweden": {"SIVE.ST": "TX1"}}
            builder.universe = lambda: []

            def fake_http(url: str):
                if "TX1/option-chain" in url:
                    rows = [{"fullName": "SIVE 23OCT26 110C", "assetClass": "OPTIONS", "expirationDate": expiry_date,
                             "strikePrice": "110.00", "bidPrice": "0.95", "askPrice": "1.05", "contractSize": "100"}]
                    return {"data": {"instrumentListing": {"rows": rows}}}
                raise AssertionError(f"Unexpected HTTP call: {url}")

            builder.http_json = fake_http

            code, data, raw = self._run_main_capture(["--output", str(out_path)])

            self.assertEqual(code, 1, raw)
            self.assertIsNotNone(data, raw)
            self.assertEqual(data["status"], "FAILED")
            self.assertEqual(data["error"], "OPTION_TWO_SIDED_COVERAGE_LOW")
            self.assertEqual(data["venues"]["US"], {"read": 11, "healthy": 1})
            self.assertEqual(data["venues"]["STOCKHOLM"], {"read": 1, "healthy": 1})
            self.assertEqual(data["affected_venues"], ["US"])
            self.assertEqual(data["quotes"], 12)
            self.assertEqual(data["available_cycles"], 2)  # 1 from US_0 monthly, 1 from SIVE.ST monthly
            self.assertTrue(data["previous_file_present"])

            # Verify target file is byte-for-byte and mtime identical
            self.assertEqual(out_path.read_bytes(), prior_bytes)
            self.assertEqual(out_path.stat().st_mtime_ns, prior_mtime)

            # Verify pre-existing <output>.tmp bytes and mtime are preserved!
            self.assertEqual(staging_path.read_bytes(), staging_bytes)
            self.assertEqual(staging_path.stat().st_mtime_ns, staging_mtime)

    def test_02_all_zero_and_numeric_negatives(self):
        """Matrix Item 2: all-zero chains, bid-only/ask-only, missing, crossed, negative, NaN/infinity
        and boolean values do not count as healthy. Positive equal bid/ask does. No volume/last-price
        substitution. Test 0/1 and 0/many."""
        # Unit checks on _is_two_sided
        self.assertFalse(builder._is_two_sided(0, 0))
        self.assertFalse(builder._is_two_sided(0.0, 0.0))
        self.assertFalse(builder._is_two_sided(1.0, 0.0))
        self.assertFalse(builder._is_two_sided(0.0, 1.0))
        self.assertFalse(builder._is_two_sided(1.0, None))
        self.assertFalse(builder._is_two_sided(None, 1.0))
        self.assertFalse(builder._is_two_sided(None, None))
        self.assertFalse(builder._is_two_sided(2.0, 1.0))       # crossed
        self.assertFalse(builder._is_two_sided(-1.0, 1.0))      # negative bid
        self.assertFalse(builder._is_two_sided(1.0, -1.0))      # negative ask
        self.assertFalse(builder._is_two_sided(-1.0, -0.5))     # both negative
        self.assertFalse(builder._is_two_sided(float("nan"), 1.0))
        self.assertFalse(builder._is_two_sided(1.0, float("nan")))
        self.assertFalse(builder._is_two_sided(float("inf"), float("inf")))
        self.assertFalse(builder._is_two_sided(True, 1.0))       # boolean true
        self.assertFalse(builder._is_two_sided(1.0, False))      # boolean false
        self.assertFalse(builder._is_two_sided(True, False))

        # Positive equal bid/ask does count
        self.assertTrue(builder._is_two_sided(1.0, 1.0))
        self.assertTrue(builder._is_two_sided(0.05, 0.05))
        # Wide positive noncrossed spread counts for detector
        self.assertTrue(builder._is_two_sided(0.50, 10.0))

        # Depletion ratio rule
        self.assertTrue(builder.is_venue_coverage_depleted(1, 0))   # 0/1
        self.assertTrue(builder.is_venue_coverage_depleted(50, 0))  # 0/many
        self.assertTrue(builder.is_venue_coverage_depleted(11, 1))  # 1/11 < 10%
        self.assertFalse(builder.is_venue_coverage_depleted(10, 1)) # 1/10 == 10%
        self.assertFalse(builder.is_venue_coverage_depleted(0, 0))  # R=0 no diagnosis

        # Adapter path: yfinance chain with high volume and lastPrice but zero bid/ask
        calls = [CallRow(strike=100.0, bid=0.0, ask=0.0, lastPrice=15.0, volume=10000, openInterest=5000, impliedVolatility=0.35)]
        ticker = FakeTicker("TEST_ZERO", price=100.0, options=["2026-10-23"], chains={"2026-10-23": calls})
        sys.modules["yfinance"] = FakeYFinanceModule({"TEST_ZERO": ticker})
        res = builder.us_options("TEST_ZERO", 100.0, self.TODAY, self.STAMP)
        read_h = [x for x in res.health if x["read"]]
        self.assertEqual(len(read_h), 1)  # monthly selected and read
        self.assertFalse(read_h[0]["two_sided"])  # Volume & lastPrice cannot substitute for bid/ask!

    def test_03_threshold_boundaries(self):
        """Matrix Item 3: H/R = 1/11 rejects; 1/10 passes this guard; above 10% passes. Distinguish
        the guard result from any unrelated CLI prerequisite failures."""
        # Named integer ratio constants
        self.assertEqual(builder.OPTION_TWO_SIDED_COVERAGE_RATIO_NUMERATOR, 1)
        self.assertEqual(builder.OPTION_TWO_SIDED_COVERAGE_RATIO_DENOMINATOR, 10)
        self.assertEqual(builder.OPTION_TWO_SIDED_COVERAGE_THRESHOLD, 0.10)

        # Pure logic boundaries
        self.assertTrue(builder.is_venue_coverage_depleted(11, 1))
        self.assertFalse(builder.is_venue_coverage_depleted(10, 1))
        self.assertFalse(builder.is_venue_coverage_depleted(10, 2))
        self.assertFalse(builder.is_venue_coverage_depleted(100, 15))

        with tempfile.TemporaryDirectory() as tmp:
            out_path = Path(tmp) / "out.json"
            expiry_date = "2026-10-23"

            def run_with_raw_chains(us_count: int, healthy_count: int, total_quotes: int):
                us_syms = [f"US_{i}" for i in range(us_count)]
                tickers = {}
                for i, sym in enumerate(us_syms):
                    if i < healthy_count:
                        calls = [CallRow(strike=115.0, bid=2.0, ask=2.1, lastPrice=2.05, volume=100, openInterest=50, impliedVolatility=0.35)]
                    else:
                        calls = [CallRow(strike=110.0, bid=0.0, ask=0.0, lastPrice=9.0, volume=100, openInterest=50, impliedVolatility=0.35)]
                    tickers[sym] = FakeTicker(sym, price=100.0, options=[expiry_date], chains={expiry_date: calls})

                # Additional quote-only underlyings if needed to reach total_quotes
                extra_syms = []
                for i in range(len(us_syms), total_quotes):
                    sym = f"EXTRA_{i}"
                    extra_syms.append(sym)
                    tickers[sym] = FakeTicker(sym, price=50.0, options=[])

                sys.modules["yfinance"] = FakeYFinanceModule(tickers)
                builder.broad_universe = lambda now: {"us": us_syms + extra_syms, "sweden": {}}
                builder.universe = lambda: []
                return self._run_main_capture(["--output", str(out_path)])

            # 1/11 rejects via real raw chain pipeline
            c11, d11, r11 = run_with_raw_chains(us_count=11, healthy_count=1, total_quotes=12)
            self.assertEqual(c11, 1, r11)
            self.assertEqual(d11["error"], "OPTION_TWO_SIDED_COVERAGE_LOW")
            self.assertEqual(d11["venues"]["US"], {"read": 11, "healthy": 1})

            # 1/10 passes via real raw chain pipeline
            c10, d10, r10 = run_with_raw_chains(us_count=10, healthy_count=1, total_quotes=12)
            self.assertEqual(c10, 0, r10)
            self.assertEqual(d10["status"], "OK")
            self.assertEqual(d10["chain_health"]["US"]["read"], 10)
            self.assertEqual(d10["chain_health"]["US"]["healthy"], 1)
            written10 = json.loads(out_path.read_text(encoding="utf-8"))
            self.assertEqual(written10["collection"]["chain_health"]["US"]["read"], 10)
            self.assertEqual(written10["collection"]["chain_health"]["US"]["healthy"], 1)

            # 2/10 passes via real raw chain pipeline
            c10_2, d10_2, r10_2 = run_with_raw_chains(us_count=10, healthy_count=2, total_quotes=12)
            self.assertEqual(c10_2, 0, r10_2)
            self.assertEqual(d10_2["status"], "OK")
            self.assertEqual(d10_2["chain_health"]["US"]["read"], 10)
            self.assertEqual(d10_2["chain_health"]["US"]["healthy"], 2)

            # Distinguish from prerequisite failure: quotes < 10 returns TOO_FEW_QUOTES
            c_few, d_few, r_few = run_with_raw_chains(us_count=5, healthy_count=0, total_quotes=5)
            self.assertEqual(c_few, 1, r_few)
            self.assertEqual(d_few["error"], "TOO_FEW_QUOTES")

    def test_04_strategy_independent_health(self):
        """Matrix Item 4: two-sided chains whose strikes are all ITM, yield too little, lack an
        acceptable delta or exceed strategy spread limits remain healthy for detection even with zero
        suggestions; normal unavailability is written. Do not replace strategy rules with this health rule."""
        spot = 100.0
        # 1. All ITM (strike 80 < spot 100)
        row_itm = CallRow(strike=80.0, bid=21.0, ask=21.5, impliedVolatility=0.3, volume=10, openInterest=5)
        # 2. Yield too little (bid 0.05 -> yield ~2% < 6%)
        row_low_yield = CallRow(strike=150.0, bid=0.05, ask=0.10, impliedVolatility=0.3, volume=10, openInterest=5)
        # 3. Delta too high for high strike (delta 0.35 > 0.20)
        row_high_delta = CallRow(strike=105.0, bid=3.5, ask=3.6, impliedVolatility=0.45, volume=10, openInterest=5)
        # 4. Spread exceeds mid limit (bid 1.0, ask 5.0 -> spread 4.0 / 3.0 > 1.0)
        row_wide_spread = CallRow(strike=120.0, bid=1.0, ask=5.0, impliedVolatility=0.5, volume=10, openInterest=5)

        expiry_date = "2026-10-23"
        for test_row in [row_itm, row_low_yield, row_high_delta, row_wide_spread]:
            ticker = FakeTicker("TEST_SYM", price=spot, options=[expiry_date], chains={expiry_date: [test_row]})
            sys.modules["yfinance"] = FakeYFinanceModule({"TEST_SYM": ticker})
            res = builder.us_options("TEST_SYM", spot, self.TODAY, self.STAMP)
            read_h = [x for x in res.health if x["read"]]
            self.assertEqual(len(read_h), 1)
            self.assertTrue(read_h[0]["two_sided"])  # Strategy-independent: quote is two-sided!
            self.assertIn("unavailable", res["monthly"])

        # Integrated check: 12 symbols with two-sided quotes failing strategy produce status OK, not failure
        with tempfile.TemporaryDirectory() as tmp:
            out_path = Path(tmp) / "out.json"
            symbols = [f"US_{i}" for i in range(12)]
            tickers = {sym: FakeTicker(sym, price=spot, options=[expiry_date], chains={expiry_date: [row_itm]})
                       for sym in symbols}
            sys.modules["yfinance"] = FakeYFinanceModule(tickers)
            builder.broad_universe = lambda now: {"us": symbols, "sweden": {}}
            builder.universe = lambda: []

            code, data, raw = self._run_main_capture(["--output", str(out_path)])

            self.assertEqual(code, 0, raw)
            self.assertEqual(data["status"], "OK")
            written = json.loads(out_path.read_text(encoding="utf-8"))
            self.assertEqual(written["collection"]["chain_health"]["US"]["read"], 12)
            self.assertEqual(written["collection"]["chain_health"]["US"]["healthy"], 12)
            self.assertIn("unavailable", written["options"]["US_0"]["monthly"])

    def test_05a_factual_state_distinctions(self):
        """Matrix Item 5a: factual EMPTY / NO_EXPIRY / READ_ERROR / EXPIRY_LIST_ERROR / EMPTY_RESPONSE
        distinctions across Yahoo, Nasdaq US fallback and Nordic adapters. None enters R."""
        # 1. Yahoo expiry-list read failure: ticker.options raises Exception
        yf_mod = FakeYFinanceModule({"EXP_ERR": FakeTicker("EXP_ERR", options=OSError("Yahoo network drop"))})
        sys.modules["yfinance"] = yf_mod
        res_exp_err = builder.us_options("EXP_ERR", 100.0, self.TODAY, self.STAMP)
        for h in res_exp_err.health:
            self.assertEqual(h["status"], "EXPIRY_LIST_ERROR")
            self.assertFalse(h["read"])
            self.assertIsNone(h["expiry"])
            self.assertIn("Yahoo Finance 期權到期日清單", res_exp_err[h["cycle"]]["unavailable"])

        # 2. Yahoo successfully decoded empty expiry response: ticker.options == []
        yf_mod = FakeYFinanceModule({"EMPTY_EXP": FakeTicker("EMPTY_EXP", options=[])})
        sys.modules["yfinance"] = yf_mod
        res_empty_exp = builder.us_options("EMPTY_EXP", 100.0, self.TODAY, self.STAMP)
        for h in res_empty_exp.health:
            self.assertEqual(h["status"], "EMPTY_RESPONSE")
            self.assertFalse(h["read"])
            self.assertIsNone(h["expiry"])

        # 3. Yahoo nonempty expiries without a selected expiry in window
        yf_mod = FakeYFinanceModule({"NO_WIN": FakeTicker("NO_WIN", options=["2026-12-18"])})  # DTE 81 > 60
        sys.modules["yfinance"] = yf_mod
        res_no_win = builder.us_options("NO_WIN", 100.0, self.TODAY, self.STAMP)
        for h in res_no_win.health:
            self.assertEqual(h["status"], "NO_EXPIRY")
            self.assertFalse(h["read"])
            self.assertIsNone(h["expiry"])

        # 4. Yahoo chain read failure: ticker.option_chain(exp) raises Exception
        yf_mod = FakeYFinanceModule({"CHAIN_ERR": FakeTicker("CHAIN_ERR", options=["2026-10-23"],
                                                             chains={"2026-10-23": OSError("chain read error")})})
        sys.modules["yfinance"] = yf_mod
        res_chain_err = builder.us_options("CHAIN_ERR", 100.0, self.TODAY, self.STAMP)
        h_m = next(x for x in res_chain_err.health if x["cycle"] == "monthly")
        self.assertEqual(h_m["status"], "READ_ERROR")
        self.assertFalse(h_m["read"])
        self.assertEqual(h_m["expiry"], "2026-10-23")

        # 5. Yahoo empty selected chain (0 calls / rows)
        yf_mod = FakeYFinanceModule({"EMPTY_CH": FakeTicker("EMPTY_CH", options=["2026-10-23"],
                                                            chains={"2026-10-23": []})})
        sys.modules["yfinance"] = yf_mod
        res_empty_ch = builder.us_options("EMPTY_CH", 100.0, self.TODAY, self.STAMP)
        h_m2 = next(x for x in res_empty_ch.health if x["cycle"] == "monthly")
        self.assertEqual(h_m2["status"], "EMPTY")
        self.assertFalse(h_m2["read"])
        self.assertEqual(h_m2["expiry"], "2026-10-23")

        # 6. Nasdaq US successfully decoded empty response: table.rows == []
        builder.http_json = lambda url: {"data": {"table": {"rows": []}}}
        nasdaq_empty = builder.nasdaq_us_options("AAPL", 100.0, self.TODAY, self.STAMP)
        for h in nasdaq_empty.health:
            self.assertEqual(h["status"], "EMPTY_RESPONSE")
            self.assertFalse(h["read"])

        # 7. Nasdaq US nonempty responses without a selected expiry
        builder.http_json = lambda url: {"data": {"table": {"rows": [
            {"expirygroup": "December 18, 2026"},
            {"strike": "100.00", "c_Bid": "1.0", "c_Ask": "1.1", "c_Volume": "10", "c_Openinterest": "10"}
        ]}}}
        nasdaq_no_exp = builder.nasdaq_us_options("AAPL", 100.0, self.TODAY, self.STAMP)
        for h in nasdaq_no_exp.health:
            self.assertEqual(h["status"], "NO_EXPIRY")
            self.assertFalse(h["read"])

        # 8. Nasdaq US read failure: http_json raises
        def fail_http(url):
            raise OSError("nasdaq timeout")
        builder.http_json = fail_http
        nasdaq_err = builder.nasdaq_us_options("AAPL", 100.0, self.TODAY, self.STAMP)
        for h in nasdaq_err.health:
            self.assertEqual(h["status"], "READ_ERROR")
            self.assertFalse(h["read"])

        # 9. Nordic successfully decoded empty response: instrumentListing.rows == []
        builder.http_json = lambda url: {"data": {"instrumentListing": {"rows": []}}}
        nordic_empty = builder.nordic_options("VOLV-B.ST", "VOLV-B", 100.0, self.TODAY, self.STAMP, "TX1")
        for h in nordic_empty.health:
            self.assertEqual(h["status"], "EMPTY_RESPONSE")
            self.assertFalse(h["read"])

        # 10. Nordic nonempty responses without a selected expiry (e.g. futures only)
        builder.http_json = lambda url: {"data": {"instrumentListing": {"rows": [
            {"fullName": "VOLVB 16OCT26 FUTC", "assetClass": "FUTURES", "expirationDate": "2026-10-16"}
        ]}}}
        nordic_no_exp = builder.nordic_options("VOLV-B.ST", "VOLV-B", 100.0, self.TODAY, self.STAMP, "TX1")
        for h in nordic_no_exp.health:
            self.assertEqual(h["status"], "NO_EXPIRY")
            self.assertFalse(h["read"])

        # 11. Nordic read failure: http_json raises
        builder.http_json = fail_http
        nordic_err = builder.nordic_options("VOLV-B.ST", "VOLV-B", 100.0, self.TODAY, self.STAMP, "TX1")
        for h in nordic_err.health:
            self.assertEqual(h["status"], "READ_ERROR")
            self.assertFalse(h["read"])

        # 12. Aggregate in build(): none of these enter R!
        def make_obs(venue, und, status):
            h = [{"venue": venue, "underlying": und, "expiry": "2026-10-23" if status in ("READ_ERROR", "EMPTY") else None,
                  "cycle": "monthly", "status": status, "read": False, "two_sided": False}]
            return builder.Observation({"symbol": und, "price": 100.0, "source": "F", "source_url": "https://example.com"},
                                       und, builder.CyclesResult({}, health=h))

        test_observations = {
            "S_EXP_ERR": make_obs("US", "S_EXP_ERR", "EXPIRY_LIST_ERROR"),
            "S_EMPTY_EXP": make_obs("US", "S_EMPTY_EXP", "EMPTY_RESPONSE"),
            "S_NO_WIN": make_obs("US", "S_NO_WIN", "NO_EXPIRY"),
            "S_CHAIN_ERR": make_obs("US", "S_CHAIN_ERR", "READ_ERROR"),
            "S_EMPTY_CH": make_obs("US", "S_EMPTY_CH", "EMPTY"),
        }
        saved_obs = builder.observe
        try:
            builder.observe = lambda symbol, today, stamp, orderbook=None: test_observations[symbol]
            builder.broad_universe = lambda now: {"us": list(test_observations.keys()), "sweden": {}}
            builder.universe = lambda: []

            doc = builder.build(self.NOW)
            us_h = doc["collection"]["chain_health"]["US"]
            self.assertEqual(us_h["read"], 0)  # None entered R!
            self.assertEqual(us_h["healthy"], 0)
            self.assertEqual(us_h["expiry_list_error"], 1)
            self.assertEqual(us_h["empty_response"], 1)
            self.assertEqual(us_h["no_expiry"], 1)
            self.assertEqual(us_h["read_error"], 1)
            self.assertEqual(us_h["empty"], 1)
        finally:
            builder.observe = saved_obs

    def test_05b_yahoo_fallback_to_nasdaq_variants_and_request_counts(self):
        """Matrix Item 5b: Yahoo fallback to Nasdaq (success with quotes, success with zero quotes,
        empty response, failure) with exact aggregate counts and unchanged request counts."""
        # Variant 1: Yahoo success with quotes for weekly and monthly -> Nasdaq is NOT called (request count = 0)
        exp_w = "2026-10-02"  # DTE 4 (weekly)
        exp_m = "2026-10-23"  # DTE 25 (monthly)
        good_call_w = CallRow(strike=105.0, bid=1.0, ask=1.1, lastPrice=1.05, volume=50, openInterest=30, impliedVolatility=0.35)
        good_call_m = CallRow(strike=115.0, bid=2.0, ask=2.1, lastPrice=2.05, volume=100, openInterest=50, impliedVolatility=0.35)
        yf_good = FakeYFinanceModule({"V1": FakeTicker("V1", price=100.0, options=[exp_w, exp_m],
                                                       chains={exp_w: [good_call_w], exp_m: [good_call_m]})})
        sys.modules["yfinance"] = yf_good
        nasdaq_urls = []
        builder.http_json = lambda url: nasdaq_urls.append(url) or {"data": {"table": {"rows": []}}}

        res_v1 = builder.us_cycles("V1", 100.0, self.TODAY, self.STAMP)
        self.assertEqual(len(nasdaq_urls), 0)  # Unchanged request counts: Nasdaq NOT called!
        v1_h = [x for x in res_v1.health if x["read"]]
        self.assertEqual(len(v1_h), 2)
        self.assertTrue(all(x["two_sided"] for x in v1_h))

        # Variant 2: Yahoo expiry error -> Nasdaq fallback success with quotes
        yf_down = FakeYFinanceModule({"V2": FakeTicker("V2", price=100.0, options=OSError("yahoo down"))})
        sys.modules["yfinance"] = yf_down
        nasdaq_urls = []
        nasdaq_rows_with_quotes = [
            {"expirygroup": "October 23, 2026"},
            {"strike": "115.00", "c_Bid": "2.00", "c_Ask": "2.10", "c_Volume": "100", "c_Openinterest": "50"}
        ]
        builder.http_json = lambda url: nasdaq_urls.append(url) or {"data": {"table": {"rows": nasdaq_rows_with_quotes}}}

        res_v2 = builder.us_cycles("V2", 100.0, self.TODAY, self.STAMP)
        self.assertEqual(len(nasdaq_urls), 1)  # Called exactly once!
        v2_reads = [x for x in res_v2.health if x["read"]]
        self.assertEqual(len(v2_reads), 1)
        self.assertTrue(v2_reads[0]["two_sided"])

        # Variant 3: Yahoo expiry error -> Nasdaq fallback success with zero quotes (bid=0, ask=0)
        nasdaq_urls = []
        nasdaq_rows_zero = [
            {"expirygroup": "October 23, 2026"},
            {"strike": "110.00", "c_Bid": "0.00", "c_Ask": "0.00", "c_Volume": "100", "c_Openinterest": "50"}
        ]
        builder.http_json = lambda url: nasdaq_urls.append(url) or {"data": {"table": {"rows": nasdaq_rows_zero}}}

        res_v3 = builder.us_cycles("V2", 100.0, self.TODAY, self.STAMP)
        self.assertEqual(len(nasdaq_urls), 1)
        v3_reads = [x for x in res_v3.health if x["read"]]
        self.assertEqual(len(v3_reads), 1)
        self.assertFalse(v3_reads[0]["two_sided"])

        # Variant 4: Yahoo expiry error -> Nasdaq fallback empty response (rows: [])
        nasdaq_urls = []
        builder.http_json = lambda url: nasdaq_urls.append(url) or {"data": {"table": {"rows": []}}}

        res_v4 = builder.us_cycles("V2", 100.0, self.TODAY, self.STAMP)
        self.assertEqual(len(nasdaq_urls), 1)
        self.assertTrue(all(not x["read"] for x in res_v4.health))
        self.assertTrue(all(x["status"] == "EMPTY_RESPONSE" for x in res_v4.health))

        # Variant 5: Yahoo expiry error -> Nasdaq fallback failure (HTTP error)
        nasdaq_urls = []
        def fail_nasdaq(url):
            nasdaq_urls.append(url)
            raise OSError("nasdaq timeout")
        builder.http_json = fail_nasdaq

        res_v5 = builder.us_cycles("V2", 100.0, self.TODAY, self.STAMP)
        self.assertEqual(len(nasdaq_urls), 1)
        self.assertTrue(all(not x["read"] for x in res_v5.health))
        self.assertTrue(all(x["status"] == "READ_ERROR" for x in res_v5.health))

    def test_05c_reciprocal_stockholm_only_failure_through_main(self):
        """Matrix Item 5c: Reciprocal STOCKHOLM-only failure: healthy US chains but depleted
        Stockholm chains (11 read chains, only 1 healthy). Rejection preserves prior file and
        pre-existing <output>.tmp."""
        with tempfile.TemporaryDirectory() as tmp:
            out_path = Path(tmp) / "market_quotes_options.json"
            staging_path = out_path.with_name(out_path.name + ".tmp")
            prior_bytes = self._make_prior_file(out_path)
            prior_mtime = out_path.stat().st_mtime_ns

            staging_bytes = b'{"staging": "preexisting_staging_content"}'
            staging_path.write_bytes(staging_bytes)
            staging_mtime = staging_path.stat().st_mtime_ns

            # 10 healthy US underlyings
            us_symbols = [f"US_{i}" for i in range(10)]
            expiry_date = "2026-10-23"
            call_us = CallRow(strike=115.0, bid=2.0, ask=2.1, lastPrice=2.05, volume=100, openInterest=50, impliedVolatility=0.35)
            tickers = {sym: FakeTicker(sym, price=100.0, options=[expiry_date], chains={expiry_date: [call_us]})
                       for sym in us_symbols}

            # 11 Stockholm underlyings: 1 healthy, 10 zero quotes
            nordic_symbols = [f"N{i}.ST" for i in range(11)]
            for sym in nordic_symbols:
                tickers[sym] = FakeTicker(sym, price=100.0, currency="SEK")

            sys.modules["yfinance"] = FakeYFinanceModule(tickers)
            sweden_map = {f"N{i}.ST": f"TX_{i}" for i in range(11)}
            builder.broad_universe = lambda now: {"us": us_symbols, "sweden": sweden_map}
            builder.universe = lambda: []

            def fake_http(url: str):
                for i in range(11):
                    if f"TX_{i}/option-chain" in url:
                        if i == 0:
                            # 1 healthy two-sided quote
                            rows = [{"fullName": "N0 23OCT26 110C", "assetClass": "OPTIONS", "expirationDate": expiry_date,
                                     "strikePrice": "110.00", "bidPrice": "1.50", "askPrice": "1.60", "contractSize": "100"}]
                        else:
                            # 10 zero bid/ask quotes
                            rows = [{"fullName": f"N{i} 23OCT26 110C", "assetClass": "OPTIONS", "expirationDate": expiry_date,
                                     "strikePrice": "110.00", "bidPrice": "0.00", "askPrice": "0.00", "contractSize": "100"}]
                        return {"data": {"instrumentListing": {"rows": rows}}}
                raise AssertionError(f"Unexpected HTTP call: {url}")

            builder.http_json = fake_http

            code, data, raw = self._run_main_capture(["--output", str(out_path)])

            self.assertEqual(code, 1, raw)
            self.assertEqual(data["status"], "FAILED")
            self.assertEqual(data["error"], "OPTION_TWO_SIDED_COVERAGE_LOW")
            self.assertEqual(data["affected_venues"], ["STOCKHOLM"])
            self.assertEqual(data["venues"]["STOCKHOLM"], {"read": 11, "healthy": 1})
            self.assertEqual(data["venues"]["US"], {"read": 10, "healthy": 10})
            self.assertEqual(data["quotes"], 21)

            # Assert prior file and staging file preserved
            self.assertEqual(out_path.read_bytes(), prior_bytes)
            self.assertEqual(out_path.stat().st_mtime_ns, prior_mtime)
            self.assertEqual(staging_path.read_bytes(), staging_bytes)
            self.assertEqual(staging_path.stat().st_mtime_ns, staging_mtime)

    def test_05d_deduplication_and_discovery_exclusion(self):
        """Matrix Item 5d: Weekly and monthly sharing one expiry counted once. A discovery path
        that reads chains does not change counts."""
        # 1. Deduplication: weekly and monthly sharing one expiry counted once
        obs_shared_exp = builder.Observation(
            {"symbol": "SHARED", "price": 100.0, "source": "Fake", "source_url": "https://example.com"},
            "SHARED",
            builder.CyclesResult({}, health=[
                {"venue": "US", "underlying": "SHARED", "expiry": "2026-10-23", "cycle": "weekly", "status": "READ", "read": True, "two_sided": True},
                {"venue": "US", "underlying": "SHARED", "expiry": "2026-10-23", "cycle": "monthly", "status": "READ", "read": True, "two_sided": True},
            ])
        )

        saved_obs = builder.observe
        try:
            builder.observe = lambda symbol, today, stamp, orderbook=None: obs_shared_exp
            builder.broad_universe = lambda now: {"us": ["SHARED"], "sweden": {}}
            builder.universe = lambda: []

            doc = builder.build(self.NOW)
            # Deduped by (venue, underlying, expiry) -> read is 1, NOT 2!
            self.assertEqual(doc["collection"]["chain_health"]["US"]["read"], 1)
            self.assertEqual(doc["collection"]["chain_health"]["US"]["healthy"], 1)
        finally:
            builder.observe = saved_obs

        # 2. Discovery exclusion: universe discovery fetching Nordic or US chains does NOT enter chain_health
        def discovery_with_chains(now):
            # Discovery thread reads some nordic options or chains internally
            _ = builder.nordic_options("DISC.ST", "DISC", 100.0, self.TODAY, self.STAMP, "TX_DISC")
            return {"us": ["NORMAL_US"], "sweden": {}}

        call_normal = CallRow(strike=115.0, bid=2.0, ask=2.1, lastPrice=2.05, volume=100, openInterest=50, impliedVolatility=0.35)
        ticker_normal = FakeTicker("NORMAL_US", price=100.0, options=["2026-10-23"], chains={"2026-10-23": [call_normal]})
        sys.modules["yfinance"] = FakeYFinanceModule({"NORMAL_US": ticker_normal})

        builder.broad_universe = discovery_with_chains
        builder.universe = lambda: []

        def fake_http(url: str):
            if "TX_DISC/option-chain" in url:
                # Discovery chain returns healthy rows
                return {"data": {"instrumentListing": {"rows": [
                    {"fullName": "DISC 23OCT26 110C", "assetClass": "OPTIONS", "expirationDate": "2026-10-23",
                     "strikePrice": "110.00", "bidPrice": "1.50", "askPrice": "1.60", "contractSize": "100"}
                ]}}}
            raise AssertionError(f"Unexpected HTTP call: {url}")

        builder.http_json = fake_http

        doc_disc = builder.build(self.NOW)
        # Only NORMAL_US should be in chain_health; STOCKHOLM from discovery must NOT appear!
        self.assertEqual(doc_disc["collection"]["chain_health"]["US"]["read"], 1)
        self.assertEqual(doc_disc["collection"]["chain_health"]["US"]["healthy"], 1)
        self.assertEqual(doc_disc["collection"]["chain_health"]["STOCKHOLM"]["read"], 0)
        self.assertEqual(doc_disc["collection"]["chain_health"]["STOCKHOLM"]["healthy"], 0)

    def test_05e_only_selected_expiry_groups_count(self):
        """Matrix Item 5 (Astra r2 fix 1): a Nordic chain with several weekly and monthly expiry groups contributes only
        the selected weekly (nearest) and monthly (nearest 30 days) groups; differently healthy unselected groups and a
        non-standard contract size would change the counts if they were included."""
        def option(expiry: str, bid: str, ask: str, size: str = "100") -> dict[str, Any]:
            day = date.fromisoformat(expiry)
            return {"fullName": f"SEL {day.day:02d}{day.strftime('%b').upper()}{day.year % 100} 110C", "assetClass": "OPTIONS",
                    "expirationDate": expiry, "strikePrice": "110.00", "bidPrice": bid, "askPrice": ask, "contractSize": size}

        rows = [option("2026-10-02", "1.00", "1.10"),                 # weekly, selected (4 days): healthy
                option("2026-10-09", "0.00", "0.00"),                 # weekly, not selected: unhealthy
                option("2026-10-16", "1.00", "1.10"),                 # monthly, not selected (18 days): healthy
                option("2026-10-30", "0.00", "0.00"),                 # monthly, selected (32 days): unhealthy
                option("2026-10-30", "2.00", "2.10", size="10"),      # unsupported size in the selected group
                option("2026-11-20", "1.00", "1.10")]                 # monthly, not selected (53 days): healthy
        builder.http_json = lambda url: {"data": {"instrumentListing": {"rows": rows}}}
        cycles = builder.nordic_options("SEL.ST", "SEL", 100.0, self.TODAY, self.STAMP, "TX_SEL")
        selected = {h["cycle"]: (h["expiry"], h["read"], h["two_sided"]) for h in cycles.health}
        self.assertEqual(selected, {"weekly": ("2026-10-02", True, True), "monthly": ("2026-10-30", True, False)})

        sys.modules["yfinance"] = FakeYFinanceModule({"SEL.ST": FakeTicker("SEL.ST", price=100.0, currency="SEK")})
        builder.broad_universe = lambda now: {"us": [], "sweden": {"SEL.ST": "TX_SEL"}}
        doc = builder.build(self.NOW)
        self.assertEqual(doc["collection"]["chain_health"]["STOCKHOLM"]["read"], 2)     # all groups would give 5
        self.assertEqual(doc["collection"]["chain_health"]["STOCKHOLM"]["healthy"], 1)  # all groups would give 3

    def test_05f_partial_yahoo_fallback_counts_only_the_retry_cycle(self):
        """Matrix Item 5 (Astra r2 fix 1): Yahoo reads the weekly chain with zero quotes and fails the monthly chain;
        Nasdaq is asked once and returns weekly, monthly and an extra group, all quoted. The read Yahoo weekly keeps its
        unhealthy evidence; only the retried monthly comes from Nasdaq."""
        exp_w, exp_m = "2026-10-02", "2026-10-23"
        zero = CallRow(strike=110.0, bid=0.0, ask=0.0, lastPrice=1.2, volume=40, openInterest=30, impliedVolatility=0.35)
        ticker = FakeTicker("PART", price=100.0, options=[exp_w, exp_m], chains={exp_w: [zero], exp_m: OSError("chain down")})
        sys.modules["yfinance"] = FakeYFinanceModule({"PART": ticker})
        requests: list[str] = []

        def nasdaq(url: str) -> dict[str, Any]:
            requests.append(url)
            return {"data": {"table": {"rows": [
                {"expirygroup": "October 2, 2026"}, {"strike": "110.00", "c_Bid": "1.00", "c_Ask": "1.10"},
                {"expirygroup": "October 23, 2026"}, {"strike": "115.00", "c_Bid": "2.00", "c_Ask": "2.10"},
                {"expirygroup": "November 20, 2026"}, {"strike": "120.00", "c_Bid": "3.00", "c_Ask": "3.10"}]}}}

        builder.http_json = nasdaq
        builder.broad_universe = lambda now: {"us": ["PART"], "sweden": {}}
        doc = builder.build(self.NOW)
        self.assertEqual(len(requests), 1)
        self.assertEqual({k: doc["collection"]["chain_health"]["US"][k] for k in ("read", "healthy")}, {"read": 2, "healthy": 1})

    def test_06_late_completion_isolation(self):
        """Matrix Item 6: Late-completion isolation: release the slow worker after build returns, join the collector
        thread that ran it, and assert the returned document and a following run are unchanged."""
        slow_release_event = threading.Event()
        slow_worker_finished = threading.Event()

        def slow_observe(symbol: str, today: date, stamp: str, orderbook: str | None = None):
            if symbol == "SLOW":
                slow_release_event.wait(timeout=2.0)
                slow_worker_finished.set()
                quote = {"symbol": symbol, "price": 100.0, "source": "Fake", "source_url": "https://example.com"}
                h = [{"venue": "US", "underlying": symbol, "expiry": "2026-10-23",
                      "cycle": "monthly", "status": "READ", "read": True, "two_sided": True, "eligible_rows": 1}]
                return builder.Observation(quote, symbol, builder.CyclesResult({}, health=h))
            quote = {"symbol": symbol, "price": 100.0, "source": "Fake", "source_url": "https://example.com"}
            h = [{"venue": "US", "underlying": symbol, "expiry": "2026-10-23",
                  "cycle": "monthly", "status": "READ", "read": True, "two_sided": True, "eligible_rows": 1}]
            return builder.Observation(quote, symbol, builder.CyclesResult({}, health=h))

        saved_obs = builder.observe
        try:
            builder.observe = slow_observe
            builder.broad_universe = lambda now: {"us": [], "sweden": {}}
            builder.universe = lambda: ["FAST1", "FAST2", "SLOW"]

            # Run build with a short deadline (0.15s) so SLOW is abandoned
            before = set(threading.enumerate())
            doc1 = builder.build(self.NOW, deadline_seconds=0.15)
            late = [thread for thread in threading.enumerate() if thread not in before and thread.is_alive()]
            self.assertTrue(late, "the collector running SLOW should still be alive when build returns")
            snapshot = json.dumps(doc1, sort_keys=True)

            # SLOW was abandoned while still blocked
            self.assertEqual(doc1["collection"]["underlyings"], 3)
            self.assertEqual(doc1["collection"]["unfinished"], 1)
            self.assertEqual(doc1["collection"]["chain_health"]["US"]["read"], 2)
            self.assertNotIn("SLOW", doc1["quotes"])

            # Now release the slow worker and wait until every collector thread started by build has finished
            slow_release_event.set()
            self.assertTrue(slow_worker_finished.wait(timeout=5.0))
            for thread in late:
                thread.join(timeout=5.0)
                self.assertFalse(thread.is_alive(), thread.name)

            # Assert doc1 remains unchanged after slow worker completes!
            self.assertEqual(json.dumps(doc1, sort_keys=True), snapshot)
            self.assertEqual(doc1["collection"]["unfinished"], 1)
            self.assertEqual(doc1["collection"]["chain_health"]["US"]["read"], 2)
            self.assertNotIn("SLOW", doc1["quotes"])

            # Assert a subsequent run is clean and not contaminated
            builder.universe = lambda: ["RUN2_A", "RUN2_B"]
            doc2 = builder.build(self.NOW, deadline_seconds=5.0)
            self.assertEqual(doc2["collection"]["underlyings"], 2)
            self.assertEqual(doc2["collection"]["unfinished"], 0)
            self.assertEqual(doc2["collection"]["chain_health"]["US"]["read"], 2)
            self.assertIn("RUN2_A", doc2["quotes"])
            self.assertIn("RUN2_B", doc2["quotes"])
            self.assertNotIn("SLOW", doc2["quotes"])
        finally:
            slow_release_event.set()  # safety release
            builder.observe = saved_obs

    def test_07_target_states_and_staging_preservation(self):
        """Matrix Item 7: valid fresh prior, exactly-5h prior, >5h prior, corrupt prior, already-degraded
        prior and absent prior with the fixed clock. A pre-existing <output>.tmp keeps its bytes and mtime.
        Every depleted candidate returns failure without target/staging mutation."""
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)

            # Setup depleted raw chains (11 US underlyings: 1 healthy, 10 zero bid/ask)
            us_symbols = [f"US_{i}" for i in range(11)]
            expiry_date = "2026-10-23"
            tickers = {}
            for i, sym in enumerate(us_symbols):
                if i == 0:
                    calls = [CallRow(strike=115.0, bid=2.0, ask=2.1, lastPrice=2.05, volume=100, openInterest=50, impliedVolatility=0.35)]
                else:
                    calls = [CallRow(strike=110.0, bid=0.0, ask=0.0, lastPrice=9.0, volume=100, openInterest=50, impliedVolatility=0.35)]
                tickers[sym] = FakeTicker(sym, price=100.0, options=[expiry_date], chains={expiry_date: calls})

            sys.modules["yfinance"] = FakeYFinanceModule(tickers)
            builder.broad_universe = lambda now: {"us": us_symbols, "sweden": {}}
            builder.universe = lambda: []

            cases = [
                ("fresh.json", {"generated_at": "2026-09-28T05:00:00Z"}),      # 1h old
                ("exact_5h.json", {"generated_at": "2026-09-28T01:00:00Z"}),   # exactly 5h old
                ("gt_5h.json", {"generated_at": "2026-09-28T00:00:00Z"}),      # 6h old (>5h)
                ("corrupt.json", {"corrupt": True}),                            # corrupt prior
                ("degraded.json", {"status_unavailable": True}),                # already-degraded prior
                ("absent.json", None),                                          # absent prior
            ]

            for fname, prior_opts in cases:
                target_path = folder / fname
                staging_path = target_path.with_name(target_path.name + ".tmp")

                # Pre-existing staging file
                staging_bytes = f'{{"staging": "preexisting_staging_{fname}"}}'.encode("utf-8")
                staging_path.write_bytes(staging_bytes)
                staging_mtime = staging_path.stat().st_mtime_ns

                if prior_opts is not None:
                    prior_bytes = self._make_prior_file(target_path, **prior_opts)
                    prior_mtime = target_path.stat().st_mtime_ns
                else:
                    prior_bytes = None
                    prior_mtime = None

                code, data, raw = self._run_main_capture(["--output", str(target_path)])

                self.assertEqual(code, 1, f"Failed for {fname}: {raw}")
                self.assertEqual(data["error"], "OPTION_TWO_SIDED_COVERAGE_LOW")

                # Target file checks
                if prior_bytes is not None:
                    self.assertTrue(data["previous_file_present"])
                    self.assertEqual(target_path.read_bytes(), prior_bytes)
                    self.assertEqual(target_path.stat().st_mtime_ns, prior_mtime)
                else:
                    self.assertFalse(data["previous_file_present"])
                    self.assertFalse(target_path.exists(), f"Target {fname} should not have been created!")

                # Staging file checks: pre-existing <output>.tmp keeps bytes and mtime!
                self.assertEqual(staging_path.read_bytes(), staging_bytes)
                self.assertEqual(staging_path.stat().st_mtime_ns, staging_mtime)

    def test_08_recovery_and_precedence_and_cadence(self):
        """Matrix Item 8: rejected run followed by a healthy raw run that replaces normally;
        precedence of DEADLINE_INCOMPLETE and TOO_FEW_QUOTES; cadence --if-older-than-hours."""
        with tempfile.TemporaryDirectory() as tmp:
            out_path = Path(tmp) / "cadence_test.json"
            prior_bytes = self._make_prior_file(out_path, generated_at="2026-09-28T04:00:00Z")
            expiry_date = "2026-10-23"

            # 1. Depleted candidate fails with code 1, preserves prior
            us_symbols = [f"US_{i}" for i in range(11)]
            tickers_depleted = {}
            for i, sym in enumerate(us_symbols):
                if i == 0:
                    calls = [CallRow(strike=115.0, bid=2.0, ask=2.1, lastPrice=2.05, volume=100, openInterest=50, impliedVolatility=0.35)]
                else:
                    calls = [CallRow(strike=110.0, bid=0.0, ask=0.0, lastPrice=9.0, volume=100, openInterest=50, impliedVolatility=0.35)]
                tickers_depleted[sym] = FakeTicker(sym, price=100.0, options=[expiry_date], chains={expiry_date: calls})

            sys.modules["yfinance"] = FakeYFinanceModule(tickers_depleted)
            builder.broad_universe = lambda now: {"us": us_symbols, "sweden": {}}
            builder.universe = lambda: []

            c1, d1, _ = self._run_main_capture(["--output", str(out_path)])
            self.assertEqual(c1, 1)
            self.assertEqual(d1["error"], "OPTION_TWO_SIDED_COVERAGE_LOW")
            self.assertEqual(out_path.read_bytes(), prior_bytes)

            # 2. Genuine raw-chain recovery: 11 healthy raw chains replace normally
            healthy_calls = [CallRow(strike=115.0, bid=2.0, ask=2.1, lastPrice=2.05, volume=100, openInterest=50, impliedVolatility=0.35)]
            tickers_healthy = {sym: FakeTicker(sym, price=200.0, options=[expiry_date], chains={expiry_date: healthy_calls})
                               for sym in [f"HEALTHY_{i}" for i in range(11)]}
            sys.modules["yfinance"] = FakeYFinanceModule(tickers_healthy)
            builder.broad_universe = lambda now: {"us": list(tickers_healthy.keys()), "sweden": {}}

            c2, d2, _ = self._run_main_capture(["--output", str(out_path)])
            self.assertEqual(c2, 0)
            self.assertEqual(d2["status"], "OK")
            written = json.loads(out_path.read_text(encoding="utf-8"))
            self.assertEqual(written["generated_at"], self.STAMP)
            self.assertIn("HEALTHY_0", written["quotes"])
            self.assertNotIn("PRIOR", written["quotes"])  # only new data!

            # 3. Precedence: DEADLINE_INCOMPLETE beats chain health guard
            def fake_incomplete(now):
                return {"schema": "v213-market-observations-v2", "generated_at": "2026-09-28T06:30:00Z",
                        "quotes": {f"US_{i}": {"symbol": f"US_{i}", "price": 100.0} for i in range(12)},
                        "options": {},
                        "collection": {"underlyings": 20, "unfinished": 15, "deadline_seconds": 1200,
                                       "chain_health": {"US": {"read": 5, "healthy": 0, "no_expiry": 0, "read_error": 0, "empty": 0},
                                                        "STOCKHOLM": {"read": 0, "healthy": 0, "no_expiry": 0, "read_error": 0, "empty": 0}}}}
            saved_build = builder.build
            try:
                builder.build = fake_incomplete
                c3, d3, _ = self._run_main_capture(["--output", str(out_path)])
                self.assertEqual(c3, 1)
                self.assertEqual(d3["error"], "DEADLINE_INCOMPLETE")

                # 4. Precedence: TOO_FEW_QUOTES beats chain health guard
                def fake_few_quotes(now):
                    return {"schema": "v213-market-observations-v2", "generated_at": "2026-09-28T06:30:00Z",
                            "quotes": {f"US_{i}": {"symbol": f"US_{i}", "price": 100.0} for i in range(5)},
                            "options": {},
                            "collection": {"underlyings": 5, "unfinished": 0, "deadline_seconds": 1200,
                                           "chain_health": {"US": {"read": 5, "healthy": 0, "no_expiry": 0, "read_error": 0, "empty": 0},
                                                            "STOCKHOLM": {"read": 0, "healthy": 0, "no_expiry": 0, "read_error": 0, "empty": 0}}}}
                builder.build = fake_few_quotes
                c4, d4, _ = self._run_main_capture(["--output", str(out_path)])
                self.assertEqual(c4, 1)
                self.assertEqual(d4["error"], "TOO_FEW_QUOTES")
            finally:
                builder.build = saved_build

            # 5. Cadence: --if-older-than-hours 0.9 does not reset age upon rejected run
            builder.utc_now = lambda: datetime(2026, 9, 28, 6, 30, 0, tzinfo=timezone.utc)
            c_skip, d_skip, _ = self._run_main_capture(["--output", str(out_path), "--if-older-than-hours", "0.9"])
            self.assertEqual(c_skip, 0)
            self.assertEqual(d_skip["status"], "SKIPPED_FRESH")

            # At 07:10:00Z (age 1.17h >= 0.9h) -> runs depleted build
            builder.utc_now = lambda: datetime(2026, 9, 28, 7, 10, 0, tzinfo=timezone.utc)
            sys.modules["yfinance"] = FakeYFinanceModule(tickers_depleted)
            builder.broad_universe = lambda now: {"us": us_symbols, "sweden": {}}

            c_rej, d_rej, _ = self._run_main_capture(["--output", str(out_path), "--if-older-than-hours", "0.9"])
            self.assertEqual(c_rej, 1)
            self.assertEqual(d_rej["error"], "OPTION_TWO_SIDED_COVERAGE_LOW")

            # File generated_at is STILL 06:00:00Z (age is NOT reset!)
            on_disk = json.loads(out_path.read_text(encoding="utf-8"))
            self.assertEqual(on_disk["generated_at"], self.STAMP)

            # Immediate retry at 07:11:00Z (age 1.18h >= 0.9h) does NOT skip as fresh:
            builder.utc_now = lambda: datetime(2026, 9, 28, 7, 11, 0, tzinfo=timezone.utc)
            c_retry, d_retry, _ = self._run_main_capture(["--output", str(out_path), "--if-older-than-hours", "0.9"])
            self.assertEqual(c_retry, 1)
            self.assertEqual(d_retry["error"], "OPTION_TWO_SIDED_COVERAGE_LOW")

    def test_09_local_builder_to_sealer_path(self):
        """Matrix Item 9: call lazy_market_bodies on the file preserved by main. Verify bodies contain
        the old exact generated_at, cycle/quote timestamps, prices and provenance, and specifically
        assert the retained quote's asof, price, source and source_url. At 5h admit; at 5h+1s omit both;
        malformed/future generated_at fail closed. No publication or network."""
        with tempfile.TemporaryDirectory() as tmp:
            out_path = Path(tmp) / "obs.json"
            stamp_prior = "2026-09-28T01:00:00Z"
            asof_prior = "2026-09-28T00:55:00Z"
            price_prior = 123.45
            source_prior = "Yahoo Finance (unofficial, delayed)"
            source_url_prior = "https://finance.yahoo.com/quote/PRIOR"

            prior_bytes = self._make_prior_file(out_path, generated_at=stamp_prior, price=price_prior,
                                                asof=asof_prior, source=source_prior, source_url=source_url_prior)

            # Depleted run through real yfinance fixtures rejects and preserves prior file
            us_symbols = [f"US_{i}" for i in range(11)]
            expiry_date = "2026-10-23"
            tickers = {}
            for i, sym in enumerate(us_symbols):
                if i == 0:
                    calls = [CallRow(strike=115.0, bid=2.0, ask=2.1, lastPrice=2.05, volume=100, openInterest=50, impliedVolatility=0.35)]
                else:
                    calls = [CallRow(strike=110.0, bid=0.0, ask=0.0, lastPrice=9.0, volume=100, openInterest=50, impliedVolatility=0.35)]
                tickers[sym] = FakeTicker(sym, price=100.0, options=[expiry_date], chains={expiry_date: calls})

            sys.modules["yfinance"] = FakeYFinanceModule(tickers)
            builder.broad_universe = lambda now: {"us": us_symbols, "sweden": {}}
            builder.universe = lambda: []

            code, data, _ = self._run_main_capture(["--output", str(out_path)])
            self.assertEqual(code, 1)
            self.assertEqual(out_path.read_bytes(), prior_bytes)

            # Test lazy_market_bodies on preserved file
            t_gen = datetime(2026, 9, 28, 1, 0, 0, tzinfo=timezone.utc)

            # Exactly 5 hours: admitted
            t_5h = t_gen + timedelta(hours=5)
            bodies_5h = publisher.lazy_market_bodies(out_path, t_5h)
            self.assertIn("v213:quotes:v1", bodies_5h)
            self.assertIn("v213:options:v2", bodies_5h)

            q_doc = json.loads(bodies_5h["v213:quotes:v1"])
            opt_doc = json.loads(bodies_5h["v213:options:v2"])

            # Verify retained quote fields
            self.assertEqual(q_doc["generated_at"], stamp_prior)
            retained_q = q_doc["quotes"]["PRIOR"]
            self.assertEqual(retained_q["asof"], asof_prior)
            self.assertEqual(retained_q["price"], price_prior)
            self.assertEqual(retained_q["source"], source_prior)
            self.assertEqual(retained_q["source_url"], source_url_prior)

            # Verify retained options fields
            self.assertEqual(opt_doc["generated_at"], stamp_prior)
            retained_opt = opt_doc["options"]["PRIOR"]["monthly"]
            self.assertEqual(retained_opt["timestamp"], stamp_prior)
            self.assertEqual(retained_opt["provenance"], "https://example.com/prior")
            self.assertEqual(retained_opt["suggestions"][0]["limit_price"], 2.05)

            # 5 hours + 1 second: omitted (both quotes and options)
            t_5h_plus_1s = t_gen + timedelta(hours=5, seconds=1)
            bodies_expired = publisher.lazy_market_bodies(out_path, t_5h_plus_1s)
            self.assertEqual(bodies_expired, {})

            # In the future (1 second before generated_at): omitted
            t_future = t_gen - timedelta(seconds=1)
            bodies_future = publisher.lazy_market_bodies(out_path, t_future)
            self.assertEqual(bodies_future, {})

            # Malformed generated_at: omitted
            corrupt_path = Path(tmp) / "corrupt.json"
            self._make_prior_file(corrupt_path, generated_at="not-a-date")
            bodies_corrupt = publisher.lazy_market_bodies(corrupt_path, t_5h)
            self.assertEqual(bodies_corrupt, {})


if __name__ == "__main__":
    unittest.main()
