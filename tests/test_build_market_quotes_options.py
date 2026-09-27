"""Covered-call suggestions: strike choice (as high as possible while the premium is worth collecting), sell limit,
derived yields, validation before sealing. No network."""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

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
        self.assertEqual(document["collection"], {"underlyings": 3, "unfinished": 0, "deadline_seconds": 5})

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


if __name__ == "__main__":
    unittest.main()
