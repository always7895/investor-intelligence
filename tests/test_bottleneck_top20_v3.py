"""Bottleneck-explosion Top20 v3 building blocks: SEC quarter series (fiscal quarters, derived fourth quarters),
capture and size scoring, Serenity lead parsing and stance, Leopold issuer matching, the sealed compact form.
Synthetic values only; no network."""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import bottleneck_top20_v3 as engine  # noqa: E402
import leopold_positions as leopold  # noqa: E402
import publish_sealed_snapshot as publisher  # noqa: E402
import serenity_signals as serenity  # noqa: E402


def fact(start: str, end: str, value: float, filed: str) -> dict:
    return {"start": start, "end": end, "val": value, "filed": filed, "form": "10-Q", "fp": "Q"}


FACTS = {"facts": {"us-gaap": {
    # A deprecated tag with old quarters must not win over the current tag.
    "Revenues": {"units": {"USD": [fact(f"20{y}-01-01", f"20{y}-03-31", 1.0, f"20{y}-05-01") for y in range(10, 19)]}},
    "RevenueFromContractWithCustomerIncludingAssessedTax": {"units": {"USD": [
        fact("2024-06-30", "2024-09-28", 100, "2024-11-01"), fact("2024-09-29", "2024-12-28", 110, "2025-02-01"),
        fact("2024-12-29", "2025-03-29", 120, "2025-05-01"),
        fact("2024-06-30", "2025-03-29", 330, "2025-05-01"),   # nine-month YTD
        fact("2024-06-30", "2025-06-28", 460, "2025-08-15"),   # fiscal year: Q4 = 460 - 330 = 130
        fact("2025-06-29", "2025-09-27", 150, "2025-11-01"), fact("2025-09-28", "2025-12-27", 180, "2026-02-01"),
        fact("2025-12-28", "2026-03-28", 220, "2026-05-01"),
        fact("2025-06-29", "2026-03-28", 550, "2026-05-01"),
        fact("2025-06-29", "2026-06-27", 830, "2026-08-15"),   # Q4 = 830 - 550 = 280 -> +115% on 130
    ]}},
    "GrossProfit": {"units": {"USD": [fact("2025-12-28", "2026-03-28", 110, "2026-05-01"), fact("2024-12-29", "2025-03-29", 48, "2025-05-01")]}},
}, "dei": {"EntityCommonStockSharesOutstanding": {"units": {"shares": [
    {"end": "2025-08-01", "val": 100}, {"end": "2026-08-01", "val": 120}]}}}}}


class QuarterSeriesTests(unittest.TestCase):
    def test_fiscal_quarters_and_derived_fourth_quarter(self):
        tag, series = engine._quarter_series(FACTS, engine.REVENUE_TAGS)
        self.assertEqual(tag, "us-gaap:RevenueFromContractWithCustomerIncludingAssessedTax")
        self.assertEqual(series["2026-06-27"]["val"], 280)
        self.assertEqual(series["2026-06-27"]["derived"], "annual_minus_9m")
        fundamentals = engine.sec_fundamentals("X", 1, FACTS)
        self.assertEqual(fundamentals["quarter_end"], "2026-06-27")
        self.assertAlmostEqual(fundamentals["revenue_yoy"], 280 / 130 - 1)
        self.assertAlmostEqual(fundamentals["revenue_yoy_prev"], 220 / 120 - 1)
        self.assertAlmostEqual(fundamentals["shares_yoy"], 0.2)


class OutlookTests(unittest.TestCase):
    """Operator 2026-09-26: every Top20 entry shows current orders, a future estimate and the price scenario if realized."""

    def frame(self, rows):
        import pandas as pd
        return pd.DataFrame(rows, index=list(rows and ["0y", "+1y"][:len(rows)])) if rows else pd.DataFrame()

    def test_consensus_scenarios_keep_analyst_counts_and_skip_negative_eps(self):
        from types import SimpleNamespace
        ticker = SimpleNamespace(
            revenue_estimate=self.frame([{"avg": 400e9, "numberOfAnalysts": 53}, {"avg": 680e9, "numberOfAnalysts": 58}]),
            earnings_estimate=self.frame([{"avg": 9.3, "numberOfAnalysts": 51}, {"avg": 15.7, "numberOfAnalysts": 50}]))
        consensus = engine.yahoo_consensus(ticker, "NVDA", 225.0, {"targetMeanPrice": 327.7, "numberOfAnalystOpinions": 59})
        self.assertAlmostEqual(consensus["revenue_growth"], 0.7)
        self.assertEqual((consensus["revenue_analysts"], consensus["target_analysts"]), (58, 59))
        self.assertTrue(consensus["source_url"].endswith("/NVDA/analysis"))
        fund = {"rpo": 3.2e9, "rpo_unit": "USD", "rpo_end": "2026-07-26", "rpo_yoy": 0.68, "source": "SEC EDGAR XBRL companyfacts",
                "source_url": "https://data.sec.gov/api/xbrl/companyfacts/CIK0001045810.json"}
        result = engine.outlook("NVDA", fund, consensus)
        self.assertEqual((result["orders"]["kind"], result["orders"]["amount"], result["orders"]["as_of"]), ("RPO", 3.2e9, "2026-07-26"))
        self.assertEqual([row["kind"] for row in result["scenarios"]], ["REVENUE_CONSTANT_PS", "EPS_CONSTANT_PE", "ANALYST_TARGET"])
        self.assertAlmostEqual(result["scenarios"][1]["change"], 15.7 / 9.3 - 1)
        self.assertAlmostEqual(result["scenarios"][2]["change"], 327.7 / 225.0 - 1)
        loss = SimpleNamespace(revenue_estimate=ticker.revenue_estimate,
                               earnings_estimate=self.frame([{"avg": -0.23, "numberOfAnalysts": 1}, {"avg": -0.17, "numberOfAnalysts": 1}]))
        kinds = [row["kind"] for row in engine.outlook("POET", None, engine.yahoo_consensus(loss, "POET", None, {}))["scenarios"]]
        self.assertEqual(kinds, ["REVENUE_CONSTANT_PS"])  # no P/E scenario on losses, no target without a price
        empty = SimpleNamespace(revenue_estimate=self.frame([]), earnings_estimate=self.frame([]))
        self.assertIsNone(engine.yahoo_consensus(empty, "X", 1.0, {}))
        self.assertEqual(engine.outlook("X", None, None), {"orders": None, "consensus": None, "scenarios": []})

    def test_korean_backlog_comes_from_the_ir_config_or_states_why_not(self):
        orders = engine.outlook("298040.KS", None, None)["orders"]
        self.assertEqual((orders["kind"], orders["amount"], orders["currency"], orders["as_of"]), ("BACKLOG", 17507000000000, "KRW", "2026-06-30"))
        self.assertEqual(orders["guidance"]["amount"], 12000000000000)
        self.assertTrue(orders["source_url"].startswith("https://www.hyosungheavyindustries.com/"))
        self.assertEqual(engine.outlook("267260.KS", None, None)["orders"]["kind"], "NOT_DISCLOSED")
        self.assertIsNone(engine.outlook("999999.KS", None, None)["orders"])

    def test_sec_fundamentals_carry_the_latest_rpo_amount(self):
        facts = json.loads(json.dumps(FACTS))
        facts["facts"]["us-gaap"]["RevenueRemainingPerformanceObligation"] = {"units": {"USD": [
            {"end": "2025-06-28", "val": 100}, {"end": "2026-06-27", "val": 150}]}}
        fundamentals = engine.sec_fundamentals("X", 1, facts)
        self.assertEqual((fundamentals["rpo"], fundamentals["rpo_end"], fundamentals["rpo_unit"]), (150, "2026-06-27", "USD"))
        self.assertAlmostEqual(fundamentals["rpo_yoy"], 0.5)


class ScoringTests(unittest.TestCase):
    def test_capture_normalizes_over_available_evidence(self):
        full, _ = engine.capture_score({"revenue_yoy": 1.0, "revenue_yoy_prev": 0.7, "gross_margin_change": 0.10, "rpo_yoy": 0.5})
        partial, detail = engine.capture_score({"revenue_yoy": 1.0, "revenue_yoy_prev": None, "gross_margin_change": None, "rpo_yoy": None})
        self.assertAlmostEqual(full, 30.0)
        self.assertAlmostEqual(partial, 30.0)
        self.assertEqual(set(detail), {"revenue_yoy"})
        self.assertEqual(engine.capture_score(None)[0], 0.0)

    def test_size_rewards_small_scarce_layers(self):
        self.assertEqual(engine.size_score(1e9), 10)
        self.assertEqual(engine.size_score(5e9), 8)
        self.assertEqual(engine.size_score(3e11), 1.0)
        self.assertEqual(engine.size_score(None), 0.0)


class LeadTests(unittest.TestCase):
    MAPPING = json.loads((ROOT / "config" / "serenity-ticker-map-v1.json").read_text(encoding="utf-8"))

    def archive(self, posts):
        return {"source_url": serenity.ARCHIVE_URL, "repository": serenity.ARCHIVE_REPO, "retrieved_at": "2026-09-26T00:00:00Z",
                "sha256": "0" * 64, "posts": posts}

    def post(self, text, days_ago, likes=100):
        created = (datetime(2026, 9, 26, tzinfo=timezone.utc) - timedelta(days=days_ago)).strftime("%Y-%m-%dT%H:%M:%SZ")
        return {"id": str(days_ago), "text": text, "createdAtISO": created, "isRetweet": False, "metrics": {"likes": likes},
                "sourceUrl": f"https://x.com/aleabitoreddit/status/{days_ago}"}

    def test_cashtags_names_stance_and_window(self):
        posts = [self.post("Still holding $SIVE, added more on the dip", 3), self.post("Sivers is my favourite CW laser play", 10),
                 self.post("Trimmed everything except Samsung, started a new position in $ESMT", 5),
                 self.post("I'm short $ZZZT here, bearish", 4), self.post("I'm short $ZZZT again", 2),
                 self.post("$NVDA old post", 400)]
        document = serenity.build_signals(self.archive(posts), self.MAPPING, {"NVDA", "ZZZT"}, datetime(2026, 9, 26, tzinfo=timezone.utc))
        rows = {row["symbol"]: row for row in document["signals"]}
        self.assertEqual(rows["SIVE.ST"]["mentions"], 2)
        self.assertEqual(rows["SIVE.ST"]["stance"], "BULLISH")
        self.assertIn("005930.KS", rows)
        self.assertEqual(rows["3006.TW"]["stance"], "BULLISH")  # a mixed "trimmed X, started Y" post is not bearish on Y
        self.assertEqual(rows["ZZZT"]["stance"], "BEARISH")
        self.assertNotIn("NVDA", rows)  # outside the 120-day window
        self.assertEqual(document["source"]["authority"], "LEAD_ONLY_NOT_COMPANY_FACT")

    def test_leopold_issuer_matching(self):
        index = {"taiwan semiconductor manufacturing": "TSM", "core scientific tx": "CORZ", "micron technology": "MU"}
        self.assertEqual(leopold.match_ticker("MICRON TECHNOLOGY INC", index), "MU")
        self.assertEqual(leopold.match_ticker("TAIWAN SEMICONDUCTOR MANUFAC", index), "TSM")
        self.assertEqual(leopold.match_ticker("CORE SCIENTIFIC INC NEW", index), "CORZ")
        self.assertIsNone(leopold.match_ticker("UNKNOWN WIDGETS CORP", index))


class SealedFormTests(unittest.TestCase):
    def test_compact_sealed_form_and_age_bound(self):
        now = datetime.now(timezone.utc).replace(microsecond=0)
        entry = {"rank": 1, "symbol": "SIVE.ST", "name": "Sivers", "layer": "optics", "archetype": "EXPLOSION", "score": 60.9,
                 "role": "CW laser", "role_source": {"url": "https://x.com/a/status/1", "date": "2026-09-03"},
                 "score_parts": {"layer_heat": 5, "capture": 4, "capture_detail": {}, "lead": 14, "confirmation": 15, "size": 10, "penalty": 0},
                 "fundamentals": None, "market": {"source": "Yahoo", "source_url": "https://finance.yahoo.com/quote/SIVE.ST", "asof": "2026-09-25",
                                                  "ret_6m": 1.9, "ret_1y": 8.5, "cagr_2y": 1.6, "currency": "SEK", "price": 32.7},
                 "market_cap_usd": 1.05e9, "serenity": {"mentions": 218, "bullish": 65, "bearish": 9, "stance": "BULLISH",
                                                         "latest_at": "2026-09-17T00:00:00Z", "latest_url": "https://x.com/a/status/2", "intensity": 90},
                 "leopold": None}
        doc = {"schema": "v213-bottleneck-top20-v3", "generated_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
               "leads": {"serenity": {"url": serenity.ARCHIVE_URL, "latest_post_at": "2026-09-17T23:56:29Z"}, "leopold": {"filing": None}},
               "top": [{**entry, "rank": index + 1, "symbol": f"S{index}"} for index in range(12)],
               "industries": [{"rank": 1, "id": "optics", "name_zh": "光通訊", "chain": "network_optics", "leopold_constraint": "x",
                               "explosiveness": 52.1, "median_revenue_yoy": 0.3, "median_acceleration": 0.1, "median_return_6m": 0.5,
                               "fund_13f_weight": 0.0, "serenity_heat": 12.0, "news": None}]}
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "v3.json"
            path.write_text(json.dumps(doc), encoding="utf-8")
            body = publisher.lazy_bottleneck_v3_body(path, now)[publisher.BOTTLENECK_V3_KEY]
            sealed = json.loads(body)
            self.assertEqual(sealed["schema"], "v213-bottleneck-top20-v3-sealed")
            self.assertNotIn("capture_detail", sealed["top"][0]["parts"])
            self.assertNotIn("intensity", sealed["top"][0]["serenity"])
            self.assertEqual(publisher.lazy_bottleneck_v3_body(path, now + timedelta(hours=14)), {})

    def test_outlook_is_sealed_with_known_keys_only(self):
        raw = {"orders": {"kind": "RPO", "amount": 3.2e9, "currency": "USD", "as_of": "2026-07-26", "yoy": 0.68, "source": "SEC",
                          "source_url": "https://data.sec.gov/x", "secret": "x"},
               "consensus": {"revenue_growth": 0.66, "revenue_analysts": 58, "eps_growth": float("nan"), "source": "Yahoo",
                             "source_url": "https://finance.yahoo.com/quote/NVDA/analysis", "asof": "2026-09-26"},
               "scenarios": [{"kind": "REVENUE_CONSTANT_PS", "change": 0.66}, {"kind": "MOON", "change": 9.0},
                             {"kind": "EPS_CONSTANT_PE", "change": float("inf")}]}
        sealed = publisher._sealed_outlook(raw)
        self.assertNotIn("secret", sealed["orders"])
        self.assertIsNone(sealed["consensus"]["eps_growth"])
        self.assertEqual(sealed["scenarios"], [{"kind": "REVENUE_CONSTANT_PS", "change": 0.66}])
        self.assertIsNone(publisher._sealed_outlook({"orders": {"kind": "RPO", "amount": 1, "source_url": "http://x"}})["orders"])
        self.assertEqual(publisher._sealed_outlook({"orders": {"kind": "NOT_DISCLOSED", "reason": "none"}})["orders"]["kind"], "NOT_DISCLOSED")
        self.assertIsNone(publisher._sealed_outlook("x"))
        backlog = publisher._sealed_outlook({"orders": {
            "kind": "BACKLOG", "amount": 17507e9, "currency": "KRW", "as_of": "2026-06-30", "yoy": 0.63, "scope": "重工業部門",
            "source": "deck p.9", "source_url": "https://www.hyosungheavyindustries.com/download/5816",
            "intake_quarter": {"amount": 3324.2e9, "yoy": 0.51, "junk": "x"},
            "guidance": {"kind": "ANNUAL_NEW_ORDERS", "year": 2026, "amount": 12e12, "previous": float("nan"), "note": "x"}}})["orders"]
        self.assertEqual(backlog["intake_quarter"], {"amount": 3324.2e9, "yoy": 0.51})
        self.assertEqual(backlog["guidance"], {"kind": "ANNUAL_NEW_ORDERS", "year": 2026.0, "amount": 12e12, "previous": None})

    def test_sealed_entries_carry_the_sourced_chinese_name_and_listing_age(self):
        now = datetime.now(timezone.utc).replace(microsecond=0)
        market = {"source": "Yahoo", "source_url": "https://finance.yahoo.com/quote/SNDK", "asof": "2026-09-25", "ret_6m": 1.9,
                  "ret_1y": 17.8, "cagr_2y": None, "cagr_listed": 4.1, "history_start": "2025-02-13", "currency": "USD"}
        entry = {"rank": 1, "symbol": "SNDK", "name": "Sandisk", "layer": "memory", "archetype": "COMPOUNDER", "score": 70.0,
                 "role": "NAND", "role_source": {"url": "https://x.com/a/status/1", "date": "2026-09-03"},
                 "score_parts": {"layer_heat": 5, "capture": 4, "lead": 14, "confirmation": 15, "size": 10, "penalty": 0},
                 "fundamentals": None, "market": market, "market_cap_usd": 5e10, "serenity": None, "leopold": None}
        doc = {"schema": "v213-bottleneck-top20-v3", "generated_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"), "leads": {},
               "top": [{**entry, "rank": index + 1, "symbol": "SNDK" if index == 0 else f"S{index}"} for index in range(12)],
               "industries": [{"rank": 1, "id": "memory", "name_zh": "記憶體", "chain": "chips_memory", "leopold_constraint": "x",
                               "explosiveness": 52.1, "median_revenue_yoy": 0.3, "median_acceleration": 0.1, "median_return_6m": 0.5,
                               "fund_13f_weight": 0.0, "serenity_heat": 12.0, "news": None}]}
        saved = publisher.build_zh_names.names_for
        publisher.build_zh_names.names_for = lambda symbols: {"SNDK": ["晟碟", "ZHWIKI"]}
        try:
            with tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp) / "v3.json"
                path.write_text(json.dumps(doc), encoding="utf-8")
                sealed = json.loads(publisher.lazy_bottleneck_v3_body(path, now)[publisher.BOTTLENECK_V3_KEY])
        finally:
            publisher.build_zh_names.names_for = saved
        self.assertEqual((sealed["top"][0]["name_zh"], sealed["top"][0]["name_zh_source"]), ("晟碟", "ZHWIKI"))
        self.assertEqual(sealed["top"][0]["role_zh"], "NAND快閃記憶體；FQ4毛利率84.6%")  # from the installed config
        self.assertTrue(sealed["industries"][0]["leopold_constraint_zh"].startswith("CoWoS與HBM"))
        self.assertIsNone(sealed["top"][0]["outlook"])  # a document built before outlooks existed
        self.assertIsNone(sealed["top"][1]["name_zh"])
        self.assertEqual((sealed["top"][0]["market"]["cagr_listed"], sealed["top"][0]["market"]["history_start"]), (4.1, "2025-02-13"))


if __name__ == "__main__":
    unittest.main()
