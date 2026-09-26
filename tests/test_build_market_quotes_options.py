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
                self.assertEqual(builder.universe(), ["PATH", "AFRM"])
            finally:
                builder.TOP20, builder.V3, builder.LAYERS = saved


class BroadUniverseTests(unittest.TestCase):
    NOW = datetime(2026, 9, 26, 6, 0, tzinfo=timezone.utc)

    def fake_http(self, url):
        if url == builder.US_SCREENER:
            rows = [{"symbol": f"S{i}", "marketCap": str(1000 - i)} for i in range(150)]
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
        saved = (sys.modules.get("yfinance"), builder.us_options, builder.nordic_options, builder.broad_universe, builder.universe)
        sys.modules["yfinance"] = type(sys)("yfinance")
        sys.modules["yfinance"].Ticker = FakeTicker
        builder.us_options, builder.nordic_options = fake_us, fake_nordic
        builder.broad_universe = lambda now: {"us": ["AZN", "BAD", "BROKEN"], "sweden": {"AZN.ST": "TX9", "VOLV-B.ST": "TX100"}}
        builder.universe = lambda: ["NVDA", "SIVE.ST", "2330.TW"]
        try:
            document = builder.build(self.NOW)
        finally:
            yf, builder.us_options, builder.nordic_options, builder.broad_universe, builder.universe = saved
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
