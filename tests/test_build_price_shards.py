"""Per-market delayed price shards from official bulk feeds: parsing, stated dates, failure isolation, sealing. No
network."""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

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
BODIES = {"nasdaq-us-screener": US, "twse-day-all": TWSE, "tpex-daily-close": TPEX,
          "nasdaq-stockholm-main": nordic(250, [{"symbol": "SIVE", "lastSalePrice": "32.78", "percentageChange": "1.2%",
                                                 "currency": "SEK", "assetClass": "SHARES"}]),
          "nasdaq-stockholm-first-north": nordic(150), "euronext-equities": EURONEXT}


def fetch(url: str) -> bytes:
    if url == prices.US_ASOF_URL:
        return US_ASOF
    return next(BODIES[feed] for feed, (_, feed_url) in prices.FEEDS.items() if feed_url == url)


class PriceShardTests(unittest.TestCase):
    def test_rows_dates_and_keys(self):
        document = prices.build(fetch, datetime(2026, 9, 26, 1, tzinfo=timezone.utc))
        shards = document["shards"]
        self.assertEqual(shards["US"]["rows"]["NVDA"], [224.58, -0.412, "2026-09-24", "USD", 0])  # stated date, not today
        self.assertIn("BRK.B", shards["US"]["rows"])
        self.assertEqual(shards["TAIWAN"]["rows"]["2059"][:3], [12350.0, -0.323, "2026-09-24"])  # ROC date
        self.assertEqual(shards["TAIWAN"]["rows"]["5351"][4], 1)  # TPEx is the second Taiwan source
        self.assertFalse(any(key.startswith("8") for key in shards["TAIWAN"]["rows"]))  # no price, no row
        self.assertEqual(shards["SWEDEN"]["rows"]["SIVE"], [32.78, 1.2, None, "SEK", 0])  # the feed states no trade date
        self.assertEqual(shards["EUROPE"]["rows"]["EURONEXT PARIS|SOI"], [143.05, None, "2026-09-25", "EUR", 0])
        self.assertNotIn("OSLO BØRS|OSL", shards["EUROPE"]["rows"])

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

    def test_publisher_seals_fresh_markets_as_lazy_objects(self):
        now = datetime.now(timezone.utc).replace(microsecond=0)
        document = prices.build(fetch, now)
        document["shards"]["EUROPE"]["generated_at"] = (now - timedelta(days=5)).strftime("%Y-%m-%dT%H:%M:%SZ")
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "prices.json"
            path.write_text(json.dumps(document), encoding="utf-8")
            bodies = publisher.lazy_price_bodies(path, now)
        self.assertEqual(sorted(bodies), ["v213:prices:v1:SWEDEN", "v213:prices:v1:TAIWAN", "v213:prices:v1:US"])
        self.assertEqual(json.loads(bodies["v213:prices:v1:TAIWAN"])["rows"]["2059"][0], 12350.0)


if __name__ == "__main__":
    unittest.main()
