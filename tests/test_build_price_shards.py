"""Per-market delayed price shards from official bulk feeds: parsing, stated dates, failure isolation, the optional London
feeds and the exit status, sealing. No network."""
from __future__ import annotations

import contextlib
import io
import json
import sys
import tempfile
import unittest
import urllib.error
from datetime import datetime, timedelta, timezone
from email.message import Message
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import build_price_shards as prices  # noqa: E402
import publish_sealed_snapshot as publisher  # noqa: E402

US = json.dumps({"data": {"asOf": None, "rows": [{"symbol": "NVDA", "lastsale": "$224.58", "pctchange": "-0.412%"},
                                                 {"symbol": "BRK/B", "lastsale": "$505.18", "pctchange": "0.1%"}]
                          + [{"symbol": f"U{i}", "lastsale": "$1.00", "pctchange": ""} for i in range(3000)]}}).encode()
US_ASOF = json.dumps({"data": {"asof": "Last price as of Sep 24, 2026"}}).encode()
TWSE = json.dumps([{"Date": "1150924", "Code": "2059", "ClosingPrice": "12350.00", "Change": "-40.0000"}]
                  + [{"Date": "1150924", "Code": f"9{i:03d}", "ClosingPrice": "10", "Change": "0"} for i in range(800)]).encode()
TPEX = json.dumps([{"Date": "1150924", "SecuritiesCompanyCode": "5351", "Close": "108.00", "Change": "-1.50 "}]
                  + [{"Date": "1150924", "SecuritiesCompanyCode": f"8{i:03d}", "Close": "除權", "Change": ""} for i in range(10)]
                  + [{"Date": "1150924", "SecuritiesCompanyCode": f"7{i:03d}", "Close": "5", "Change": "0"} for i in range(600)]).encode()


def nordic(n: int, extra: list | None = None) -> bytes:
    rows = (extra or []) + [{"symbol": f"N{i}", "lastSalePrice": "1,234.50", "percentageChange": "-0.65%", "currency": "SEK",
                             "assetClass": "SHARES"} for i in range(n)]
    return json.dumps({"data": {"instrumentListing": {"rows": rows}}}).encode()


EURONEXT = ("﻿Name;ISIN;Symbol;Market;Currency;Open;High;Low;Last;Time;TZ;Volume;Turnover;Closing Price;Closing Price DateTime\n"
            + "SOITEC;FR0013227113;SOI;Euronext Paris;EUR;1;1;1;143.10;x;CET;1;1;143.05;25/09/2026\n"
            + "".join(f"S{i};X;S{i};Euronext Paris;EUR;1;1;1;2;x;CET;1;1;2;25/09/2026\n" for i in range(800))
            + "OSLO;NO1;OSL;Oslo Børs;NOK;1;1;1;1;x;CET;1;1;1;25/09/2026\n").encode("utf-8")
def lse(n: int, extra: list | None = None) -> bytes:
    rows = (extra or []) + [{"tidm": f"L{i}", "issuername": f"LONDON {i} PLC", "description": f"LONDON {i} PLC ORD 1P",
                             "category": "EQUITY", "currency": "GBX", "lastprice": 100 + i, "percentualchange": 0.5} for i in range(n)]
    return json.dumps([{"content": [{"name": "priceexplorersearch", "value": {"content": rows}}]}]).encode()


IQE = {"tidm": "IQE", "issuername": "IQE PLC", "description": "IQE PLC ORD 1P", "category": "EQUITY", "currency": "GBX",
       "lastprice": 46.4, "percentualchange": 5.3348}
BODIES = {"nasdaq-us-screener": US, "lse-main-market": lse(800), "lse-aim": lse(400, [IQE]), "twse-day-all": TWSE, "tpex-daily-close": TPEX,
          "nasdaq-stockholm-main": nordic(250, [{"symbol": "SIVE", "lastSalePrice": "32.78", "percentageChange": "1.2%",
                                                 "currency": "SEK", "assetClass": "SHARES"}]),
          "nasdaq-stockholm-first-north": nordic(150), "euronext-equities": EURONEXT}


def fetch(url: str) -> bytes:
    if url == prices.US_ASOF_URL:
        return US_ASOF
    return next(BODIES[feed] for feed, (_, feed_url) in prices.FEEDS.items() if feed_url == url)


def http_error() -> urllib.error.HTTPError:
    return urllib.error.HTTPError("https://api.londonstockexchange.com/api/v1/components/refresh", 503, "Service Unavailable", Message(), None)


def fetch_with(overrides: dict):
    """fetch() with per-feed overrides keyed by feed id: bytes replace that feed's body, an Exception instance is raised.
    Nothing global is mutated."""
    by_url = {prices.FEEDS[feed][1]: value for feed, value in overrides.items()}

    def inner(url: str) -> bytes:
        value = by_url.get(url)
        if isinstance(value, BaseException):
            raise value
        return fetch(url) if value is None else value
    return inner


REAL_BUILD = prices.build
LONDON = ("lse-main-market", "lse-aim")


def run_main(output: Path, fetch_fn) -> tuple[int, dict]:
    """prices.main() against an injected fetch: no network, no Yahoo, the output in a temp directory."""
    def build(fetch_arg=None, now=None):  # main() calls build(now=now)
        return REAL_BUILD(fetch_fn, now)
    out = io.StringIO()
    with mock.patch.object(prices, "build", build), mock.patch.object(prices, "yahoo_symbols", return_value={}), \
            contextlib.redirect_stdout(out):
        code = prices.main(["--output", str(output)])
    return code, json.loads(out.getvalue())


class PriceShardTests(unittest.TestCase):
    def test_rows_dates_and_keys(self):
        document = prices.build(fetch, datetime(2026, 9, 26, 1, tzinfo=timezone.utc))
        self.assertEqual((document["failed"], document["skipped_optional_feeds"]), ([], []))
        shards = document["shards"]
        self.assertEqual(shards["US"]["rows"]["NVDA"], [224.58, -0.412, "2026-09-24", "USD", 0])  # stated date, not today
        self.assertIn("BRK.B", shards["US"]["rows"])
        self.assertEqual(shards["TAIWAN"]["rows"]["2059"][:3], [12350.0, -0.323, "2026-09-24"])  # ROC date
        self.assertEqual(shards["TAIWAN"]["rows"]["5351"][4], 1)  # TPEx is the second Taiwan source
        self.assertFalse(any(key.startswith("8") for key in shards["TAIWAN"]["rows"]))  # no price, no row
        self.assertEqual(shards["SWEDEN"]["rows"]["SIVE"], [32.78, 1.2, None, "SEK", 0])  # the feed states no trade date
        self.assertEqual(shards["EUROPE"]["rows"]["EURONEXT PARIS|SOI"], [143.05, None, "2026-09-25", "EUR", 0])
        self.assertNotIn("OSLO BØRS|OSL", shards["EUROPE"]["rows"])
        self.assertEqual(shards["UK"]["rows"]["IQE"], [46.4, 5.3348, None, "GBX", 1])  # AIM is the second London source

    def test_a_failed_feed_drops_only_its_market(self):
        saved = BODIES["tpex-daily-close"]
        BODIES["tpex-daily-close"] = b"not json"
        try:
            document = prices.build(fetch, datetime(2026, 9, 26, 1, tzinfo=timezone.utc))
        finally:
            BODIES["tpex-daily-close"] = saved
        self.assertNotIn("TAIWAN", document["shards"])  # never half a market
        self.assertIn("US", document["shards"])
        self.assertEqual(document["failed"], ["tpex-daily-close:JSONDecodeError"])
        self.assertEqual(document["skipped_optional_feeds"], [])

    def test_publisher_seals_fresh_markets_as_lazy_objects(self):
        now = datetime.now(timezone.utc).replace(microsecond=0)
        document = prices.build(fetch, now)
        document["shards"]["EUROPE"]["generated_at"] = (now - timedelta(days=5)).strftime("%Y-%m-%dT%H:%M:%SZ")
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "prices.json"
            path.write_text(json.dumps(document), encoding="utf-8")
            bodies = publisher.lazy_price_bodies(path, now)
        self.assertEqual(sorted(bodies), ["v213:prices:v1:SWEDEN", "v213:prices:v1:TAIWAN", "v213:prices:v1:UK", "v213:prices:v1:US"])
        self.assertEqual(json.loads(bodies["v213:prices:v1:TAIWAN"])["rows"]["2059"][0], 12350.0)

    def test_publisher_and_cross_checks_ignore_the_top_level_skipped_key(self):
        now = datetime.now(timezone.utc).replace(microsecond=0)
        document = prices.build(fetch_with({feed: http_error() for feed in LONDON}), now)
        self.assertEqual(document["skipped_optional_feeds"], ["lse-main-market:HTTPError", "lse-aim:HTTPError"])
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "prices.json"
            path.write_text(json.dumps(document), encoding="utf-8")
            bodies = publisher.lazy_price_bodies(path, now)
            checks = publisher._exchange_cross_checks(["NVDA", "IQE.L"], {"NVDA": {"price": 224.58, "currency": "USD"}}, path)
        self.assertEqual(sorted(bodies), ["v213:prices:v1:EUROPE", "v213:prices:v1:SWEDEN", "v213:prices:v1:TAIWAN", "v213:prices:v1:US"])
        self.assertTrue(all("skipped_optional_feeds" not in json.loads(body) for body in bodies.values()))  # per-market bodies only
        self.assertEqual(sorted(checks), ["NVDA"])  # the dropped UK market gives no exchange close, nothing else changes
        self.assertEqual(checks["NVDA"]["diff"], 0.0)


class OptionalLondonFeedTests(unittest.TestCase):
    NOW = datetime(2026, 9, 26, 1, tzinfo=timezone.utc)

    def test_london_failure_is_skipped_not_failed(self):
        document = prices.build(fetch_with({feed: http_error() for feed in LONDON}), self.NOW)
        self.assertEqual(document["failed"], [])
        self.assertEqual(document["skipped_optional_feeds"], ["lse-main-market:HTTPError", "lse-aim:HTTPError"])
        self.assertNotIn("UK", document["shards"])
        self.assertEqual(sorted(document["shards"]), ["EUROPE", "SWEDEN", "TAIWAN", "US"])

    def test_one_london_feed_down_drops_the_whole_uk_market_and_a_small_one_is_skipped_too(self):
        down = prices.build(fetch_with({"lse-aim": http_error()}), self.NOW)
        self.assertEqual((down["failed"], down["skipped_optional_feeds"]), ([], ["lse-aim:HTTPError"]))
        self.assertNotIn("UK", down["shards"])  # never half a market, optional or not
        small = prices.build(fetch_with({"lse-main-market": lse(10)}), self.NOW)
        self.assertEqual((small["failed"], small["skipped_optional_feeds"]), ([], ["lse-main-market:TOO_SMALL:10"]))
        self.assertNotIn("UK", small["shards"])

    def test_required_failure_stays_failed_beside_a_skipped_london_feed(self):
        document = prices.build(fetch_with({"tpex-daily-close": b"not json", "lse-aim": http_error()}), self.NOW)
        self.assertEqual(document["failed"], ["tpex-daily-close:JSONDecodeError"])
        self.assertEqual(document["skipped_optional_feeds"], ["lse-aim:HTTPError"])
        self.assertNotIn("TAIWAN", document["shards"])
        self.assertNotIn("UK", document["shards"])

    def test_every_feed_failing_still_raises_and_names_the_optional_ones(self):
        down = fetch_with({feed: http_error() for feed in prices.FEEDS})
        with self.assertRaises(prices.PriceShardError) as caught:
            prices.build(down, self.NOW)
        self.assertIn("PRICE_FEEDS_ALL_FAILED", str(caught.exception))
        self.assertIn("lse-aim:HTTPError", str(caught.exception))
        self.assertIn("nasdaq-us-screener:HTTPError", str(caught.exception))


class MainExitStatusTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.output = Path(self._tmp.name) / "data" / "cache" / "price_shards_latest.json"

    def written(self) -> dict:
        return json.loads(self.output.read_bytes().decode("utf-8"))

    def test_all_feeds_ok_exits_0(self):
        code, summary = run_main(self.output, fetch)
        self.assertEqual((code, summary["status"], summary["failed"], summary["skipped_optional_feeds"]), (0, "OK", [], []))
        document = self.written()
        self.assertEqual((document["failed"], document["skipped_optional_feeds"]), ([], []))
        self.assertEqual(sorted(document["shards"]), ["EUROPE", "SWEDEN", "TAIWAN", "UK", "US"])
        self.assertFalse(self.output.with_name(self.output.name + ".tmp").exists())

    def test_only_london_failed_exits_0_with_the_file_written(self):
        code, summary = run_main(self.output, fetch_with({feed: http_error() for feed in LONDON}))
        self.assertEqual(code, 0)
        self.assertEqual((summary["status"], summary["failed"]), ("OK", []))
        self.assertEqual(summary["skipped_optional_feeds"], ["lse-main-market:HTTPError", "lse-aim:HTTPError"])
        document = self.written()
        self.assertEqual(document["failed"], [])
        self.assertEqual(document["skipped_optional_feeds"], ["lse-main-market:HTTPError", "lse-aim:HTTPError"])
        self.assertEqual(sorted(document["shards"]), ["EUROPE", "SWEDEN", "TAIWAN", "US"])  # UK dropped, nothing estimated

    def test_london_outage_carries_the_previous_uk_shard_forward_as_before(self):
        previous = REAL_BUILD(fetch, datetime.now(timezone.utc) - timedelta(days=2))
        self.output.parent.mkdir(parents=True)
        self.output.write_bytes(json.dumps(previous).encode("utf-8"))
        code, _ = run_main(self.output, fetch_with({"lse-aim": http_error()}))  # one of the two feeds is enough to drop the market
        self.assertEqual(code, 0)
        document = self.written()
        self.assertEqual(document["failed"], [])
        self.assertEqual(document["skipped_optional_feeds"], ["lse-aim:HTTPError"])
        self.assertEqual(document["shards"]["UK"], previous["shards"]["UK"])  # old shard, old generated_at, both London sources
        self.assertGreater(document["shards"]["US"]["generated_at"], document["shards"]["UK"]["generated_at"])

    def test_a_required_feed_failed_exits_2_even_beside_a_skipped_london_feed(self):
        code, summary = run_main(self.output, fetch_with({"tpex-daily-close": b"not json"}))
        self.assertEqual((code, summary["failed"], summary["skipped_optional_feeds"]), (2, ["tpex-daily-close:JSONDecodeError"], []))
        self.assertTrue(self.output.is_file())
        code, summary = run_main(self.output, fetch_with({"tpex-daily-close": b"not json", "lse-aim": http_error()}))
        self.assertEqual((code, summary["failed"], summary["skipped_optional_feeds"]),
                         (2, ["tpex-daily-close:JSONDecodeError"], ["lse-aim:HTTPError"]))
        self.assertEqual(self.written()["failed"], ["tpex-daily-close:JSONDecodeError"])

    def test_every_feed_failing_exits_1_and_keeps_the_previous_file(self):
        self.output.parent.mkdir(parents=True)
        self.output.write_bytes(b'{"previous":true}')
        code, summary = run_main(self.output, fetch_with({feed: http_error() for feed in prices.FEEDS}))
        self.assertEqual((code, summary["status"]), (1, "FAILED"))
        self.assertIn("PRICE_FEEDS_ALL_FAILED", summary["error"])
        self.assertEqual(self.output.read_bytes(), b'{"previous":true}')  # the last good file keeps serving


class YahooShardTests(unittest.TestCase):
    def test_japan_rows_carry_their_own_date_and_change(self):
        import pandas as pd
        symbols = {f"{1000 + i}.T": str(1000 + i) for i in range(2100)}
        index = pd.to_datetime(["2026-09-24", "2026-09-25"])

        def download(batch, **_):
            columns = {name: [100.0, 101.0] for name in batch if name != "1005.T"}
            columns["1005.T"] = [float("nan"), float("nan")]  # no price: no row
            return pd.concat({"Close": pd.DataFrame(columns, index=index)}, axis=1)
        shard = prices.yahoo_shard("JAPAN", symbols, datetime(2026, 9, 26, 1, tzinfo=timezone.utc), download)
        self.assertEqual(shard["rows"]["1000"], [101.0, 1.0, "2026-09-25", "JPY", 0])
        self.assertNotIn("1005", shard["rows"])
        self.assertEqual(shard["sources"][0]["id"], "yahoo-daily-close")
        self.assertIsNone(prices.yahoo_shard("KOREA", {"005930.KS": "005930"}, datetime(2026, 9, 26, tzinfo=timezone.utc), download))


if __name__ == "__main__":
    unittest.main()
