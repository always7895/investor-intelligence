"""Bottleneck-explosion Top20 v3 building blocks: SEC quarter series (fiscal quarters, derived fourth quarters),
capture and size scoring, Serenity lead parsing and stance, Leopold issuer matching, the sealed compact form.
Synthetic values only; no network."""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import bottleneck_top20_v3 as engine  # noqa: E402
import listing_lineage as lineage  # noqa: E402
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
        self.assertEqual(engine.outlook("X", None, None), {"orders": None, "consensus": None, "scenarios": [], "consensus_second": None})

    def test_nasdaq_is_a_second_consensus_for_us_listings_only(self):
        replies = {"targetprice": {"data": {"consensusOverview": {"priceTarget": 324.32, "buy": 31, "hold": 2, "sell": 0}}},
                   "earnings-forecast": {"data": {"yearlyForecast": {"rows": [
                       {"fiscalEnd": "Jan 2027", "consensusEPSForecast": 9.25, "noOfEstimates": 17},
                       {"fiscalEnd": "Jan 2028", "consensusEPSForecast": 13.5, "noOfEstimates": 15}]}}}}
        urls = []
        fetch = lambda url: urls.append(url) or replies[url.rsplit("/", 1)[1]]
        second = engine.nasdaq_consensus("BRK-B", 225.0, fetch)
        self.assertIn("/analyst/brk.b/targetprice", urls[0])
        self.assertEqual((second["target_mean"], second["target_analysts"]), (324.32, 33))
        self.assertAlmostEqual(second["target_upside"], 324.32 / 225.0 - 1)
        self.assertAlmostEqual(second["eps_growth"], 13.5 / 9.25 - 1)
        self.assertEqual((second["eps_analysts"], second["eps_fiscal_end"]), (15, "Jan 2028"))
        self.assertIsNone(engine.nasdaq_consensus("SIVE.ST", 32.0, fetch))  # US listings only
        self.assertIsNone(engine.nasdaq_consensus("X", 1.0, lambda url: {"data": None}))  # nothing published
        self.assertIsNone(engine.nasdaq_consensus("X", 1.0, lambda url: (_ for _ in ()).throw(OSError("down"))))

    def test_taiwan_listings_carry_the_exchange_monthly_revenue(self):
        # TPEx mopsfin_t187ap05_O row for 5351 as published on 2026-09-17 (August 2026), shortened.
        tpex = [{"出表日期": "1150917", "資料年月": "11508", "公司代號": "5351", "公司名稱": "鈺創",
                 "營業收入-當月營收": "2260221", "營業收入-去年同月增減(%)": "525.3153",
                 "累計營業收入-前期比較增減(%)": "488.9214"},
                {"資料年月": "11508", "公司代號": "6488", "營業收入-去年同月增減(%)": "1.0"}]
        urls = []
        def fetch(url):
            urls.append(url)
            if "twse" in url:
                raise OSError("TWSE down")  # one feed failing leaves only its listings Yahoo-only
            return tpex
        rows = engine.taiwan_monthly_revenue(["5351.TWO", "2330.TW", "NVDA", "SIVE.ST"], fetch)
        self.assertEqual(sorted(urls), sorted(url for _, url in engine.TAIWAN_MONTHLY_REVENUE.values()))
        self.assertEqual(rows, {"5351.TWO": {"source_id": "TPEX", "source_url": "https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap05_O",
                                             "period": "2026-08", "revenue_yoy": 5.253153, "cumulative_yoy": 4.889214, "currency": "TWD"}})
        self.assertEqual(engine.taiwan_monthly_revenue(["NVDA"], lambda url: self.fail("no Taiwan listing, no request")), {})
        malformed = [{"資料年月": "11513", "公司代號": "5351", "營業收入-去年同月增減(%)": "1"},
                     {"資料年月": "115０８", "公司代號": "5351", "營業收入-去年同月增減(%)": "1"},  # full-width digits
                     {"資料年月": "11508", "公司代號": "5351", "營業收入-去年同月增減(%)": ""}]
        self.assertEqual(engine.taiwan_monthly_revenue(["5351.TWO"], lambda url: malformed), {})

    def test_stockholm_listing_takes_its_interim_report_from_cision_within_the_fetch_limits(self):
        rss = ("<rss><channel>"
               "<item><title>Sivers Semiconductors Makes Changes to Senior Leadership Team</title><link>https://news.cision.com/x/r/a,c1</link></item>"
               "<item><title>Sivers Semiconductors Reports Q2 2026 Results as Product Growth</title><link>https://news.cision.com/x/r/q2,c2</link></item>"
               "<item><title>Invitation to Presentation of Sivers Semiconductors' Q2 2026 Report</title><link>https://news.cision.com/x/r/inv,c3</link></item>"
               "<item><title>Sivers Semiconductors AB (publ), Publishes Interim Report Q1, January - March 2026</title><link>https://news.cision.com/x/r/q1,c4</link></item>"
               "</channel></rss>")
        page = ('<h1>Sivers Reports Q2 2026 Results</h1><p>Sivers today announced its interim report for the second quarter of '
                '2026.</p><p>Financial Highlights:</p>'
                '<li style=" margin-bottom:3pt;"><span>Net sales amounted to SEK 53.8 m (61.4), corresponding to a decrease of 12% '
                'year-over-year.</span></li>')
        urls = []
        feed = engine.CISION_RSS.format(slug="sivers-semiconductors")
        replies = {feed: rss, "https://news.cision.com/x/r/q2,c2": page}
        def fetch(url):
            urls.append(url)
            return replies[url]
        now = datetime(2026, 9, 26, 12, 0, tzinfo=timezone.utc)
        expected = {"SIVE.ST": {"source_id": "CISION", "source_url": "https://news.cision.com/x/r/q2,c2", "period": "2026-Q2",
                                 "revenue_yoy": round(53.8 / 61.4 - 1, 6), "cumulative_yoy": None, "currency": "SEK"}}
        with tempfile.TemporaryDirectory() as tmp:
            cache = Path(tmp) / "cision.json"
            self.assertEqual(engine.cision_interim_revenue(["SIVE.ST", "NVDA"], now, fetch, cache), expected)
            self.assertEqual(len(urls), 2)  # the feed, then the one new report page
            self.assertEqual(engine.cision_interim_revenue(["SIVE.ST"], now + timedelta(hours=2), fetch, cache), expected)
            self.assertEqual(len(urls), 2)  # one feed read a day
            self.assertEqual(engine.cision_interim_revenue(["SIVE.ST"], now + timedelta(hours=21), fetch, cache), expected)
            self.assertEqual(len(urls), 3)  # the feed again, the known report page not
            down = lambda url: (_ for _ in ()).throw(OSError("down"))  # noqa: E731
            self.assertEqual(engine.cision_interim_revenue(["SIVE.ST"], now + timedelta(hours=45), down, cache), expected)
            replies[feed] = rss.replace("q2,c2", "q3,c5").replace("Q2 2026", "Q3 2026")
            replies["https://news.cision.com/x/r/q3,c5"] = "<p>Net sales grew strongly.</p>"  # unreadable: no figure, no guess
            self.assertEqual(engine.cision_interim_revenue(["SIVE.ST"], now + timedelta(days=3), fetch, cache), expected)  # Q2 keeps serving
            replies["https://news.cision.com/x/r/q3,c5"] = (page.replace("53.8 m (61.4)", "70.0 m (56.0)")
                                                            .replace("second quarter", "third quarter").replace("Q2", "Q3"))
            q3 = engine.cision_interim_revenue(["SIVE.ST"], now + timedelta(days=4), fetch, cache)["SIVE.ST"]
            self.assertEqual((q3["period"], q3["revenue_yoy"]), ("2026-Q3", 0.25))
        with tempfile.TemporaryDirectory() as tmp:  # a page that stays unreadable is read on three days, then left alone
            urls.clear()
            replies["https://news.cision.com/x/r/q3,c5"] = "<p>challenge</p>"
            for day in range(5):
                engine.cision_interim_revenue(["SIVE.ST"], now + timedelta(days=day), fetch, Path(tmp) / "cision.json")
            self.assertEqual(sum(url.endswith("q3,c5") for url in urls), 3)
        self.assertEqual(engine.cision_interim_revenue(["NVDA"], now, lambda url: self.fail("not a Cision issuer"), None), {})

    def test_cision_failures_still_count_against_the_fetch_limits(self):
        # ChatGPT review: a raising request must not bypass the 20-hour feed limit or the three page attempts.
        now = datetime(2026, 9, 26, 12, 0, tzinfo=timezone.utc)
        feed = engine.CISION_RSS.format(slug="sivers-semiconductors")
        rss = "<rss><channel><item><title>Sivers Reports Q3 2026 Results</title><link>https://news.cision.com/x/r/q3,c9</link></item></channel></rss>"
        with tempfile.TemporaryDirectory() as tmp:
            cache, urls = Path(tmp) / "cision.json", []
            def down(url):
                urls.append(url)
                raise TimeoutError("timeout")
            for hour in range(0, 5):  # the feed times out: read once, not five times
                engine.cision_interim_revenue(["SIVE.ST"], now + timedelta(hours=hour), down, cache)
            self.assertEqual(urls, [feed])
        with tempfile.TemporaryDirectory() as tmp:
            cache, urls = Path(tmp) / "cision.json", []
            def page_down(url):
                urls.append(url)
                if url == feed:
                    return rss
                raise OSError("reset")
            for day in range(6):  # the page keeps failing: three attempts on three days, then no more
                engine.cision_interim_revenue(["SIVE.ST"], now + timedelta(days=day), page_down, cache)
            self.assertEqual(sum(url.endswith("q3,c9") for url in urls), 3)
            self.assertEqual(urls.count(feed), 6)
            engine.cision_interim_revenue(["SIVE.ST"], now + timedelta(days=6), lambda url: "<not xml", cache)  # invalid XML
            engine.cision_interim_revenue(["SIVE.ST"], now + timedelta(days=6, hours=1),
                                          lambda url: self.fail("an invalid feed still counts against the 20 hours"), cache)
        with tempfile.TemporaryDirectory() as tmp:  # a check cached by an older parser is discarded and read again
            cache = Path(tmp) / "cision.json"
            cache.write_text(json.dumps({"SIVE.ST": {"rss_read_at": "2026-09-26T11:00:00Z", "link": "https://news.cision.com/x/r/old",
                                                  "check": {"source_id": "CISION", "period": "2025-Q4"}}}), encoding="utf-8")
            self.assertEqual(engine.cision_interim_revenue(["SIVE.ST"], now, lambda url: "<rss><channel/></rss>", cache), {})

    def test_a_cision_page_must_name_its_quarter_and_state_net_sales_once(self):
        page = "<p>Interim report for the fourth quarter of 2025</p><h2>October - December 2025</h2><p>Net sales amounted to SEK 40 m (50).</p>"
        self.assertEqual(engine._report_check("Sivers Reports Q4 2025 Results", "https://news.cision.com/x", page)["revenue_yoy"], -0.2)
        # Astra: one figure under a cumulative heading is not a quarter, and the page must name the title's quarter.
        cumulative = "<h2>January - December 2025</h2><p>Net sales amounted to SEK 300 m (200).</p>"
        self.assertIsNone(engine._report_check("Sivers Reports Q4 2025 Results", "https://news.cision.com/x", cumulative))
        self.assertIsNone(engine._report_check("Sivers Reports Q4 2025 Results", "https://news.cision.com/x",
                                               "<p>Interim report for the fourth quarter of 2025</p>" + cumulative))
        self.assertIsNone(engine._report_check("Sivers Reports Q3 2025 Results", "https://news.cision.com/x", page))  # another quarter
        wrapped = "<h1>\nInterim report for the fourth\nquarter of 2025\n</h1>\n<h2>October -\nDecember 2025</h2>\n" + page.split("</h2>")[1]
        self.assertEqual(engine._report_check("Sivers Reports Q4 2025 Results", "https://news.cision.com/x", wrapped)["period"], "2025-Q4")
        # Astra: the figure's own section heading decides its scope, with or without a year, however far it is.
        q4, figure = "<h1>Interim report for the fourth quarter of 2025</h1>", "<p>Net sales amounted to SEK 300 m (200).</p>"
        for body in (q4 + "<h2>July - September 2025</h2>" + figure, q4 + "<h2>January - December</h2>" + figure,
                     q4 + "<h2>July - September</h2>" + figure, q4 + "<h2>Q3 2025</h2>" + figure,
                     q4 + "<h2>January - December 2025</h2><p>" + "Management discussed operating performance and comparative "
                     "figures for the reporting period. " * 4 + "</p>" + figure,
                     q4 + "<p>For January - December 2025, net sales were SEK 300 m (200).</p>",
                     "<h1>Interim report</h1>" + figure,
                     # Astra: source line breaks inside a heading must not hide it
                     q4 + "<h2>January -\nDecember 2025</h2>" + figure, q4 + "<h2>\nJanuary - December 2025.\n</h2>" + figure):
            self.assertIsNone(engine._report_check("Sivers Reports Q4 2025 Results", "https://news.cision.com/x", body))
        both = ("<h2>January - December 2025</h2><p>Net sales amounted to SEK 300 m (200).</p>"
                "<h2>October - December 2025</h2><p>Net sales amounted to SEK 40 m (50).</p>")
        self.assertIsNone(engine._report_check("Sivers Reports Q4 2025 Results", "https://news.cision.com/x", both))
        self.assertIsNone(engine._report_check("Year-end Report 2025", "https://news.cision.com/x", page))  # no quarter named

    def test_korean_revenue_comes_from_the_curated_ir_config_for_the_same_quarter_only(self):
        hynix = engine.korea_ir_revenue("000660.KS", "2026-06-30")
        self.assertEqual((hynix["source_id"], hynix["period"], hynix["currency"]), ("COMPANY_IR_KR", "2026-Q2", "KRW"))
        self.assertAlmostEqual(hynix["revenue_yoy"], 79318.7 / 22232 - 1, places=5)
        self.assertTrue(hynix["source_url"].startswith("https://news.skhynix.com/"))
        self.assertAlmostEqual(engine.korea_ir_revenue("005930.KS", "2026-06-30")["revenue_yoy"], 171499470 / 74566317 - 1, places=5)
        self.assertIsNone(engine.korea_ir_revenue("000660.KS", "2026-09-30"))  # a newer Yahoo quarter: no stale figure beside it
        self.assertIsNone(engine.korea_ir_revenue("298040.KS", "2026-06-30"))  # not in the config
        self.assertIsNone(engine.korea_ir_revenue("000660.KS", "2026-06-30", Path("absent.json")))
        sealed = publisher._sealed_revenue_check({**hynix, "currency": "USD"})
        self.assertEqual(sealed, hynix)  # the seal fixes KRW for this source
        self.assertIsNone(publisher._sealed_revenue_check({**hynix, "period": "2026-06"}))

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
    def setUp(self):
        saved = publisher.company_deep_report.load_order_scenarios
        publisher.company_deep_report.load_order_scenarios = lambda *args, **kwargs: {}
        self.addCleanup(setattr, publisher.company_deep_report, "load_order_scenarios", saved)
        # A temporary, valid and empty order-claim registry: sealing never reads the packaged config in these tests.
        registry_dir = tempfile.TemporaryDirectory()
        self.addCleanup(registry_dir.cleanup)
        registry = Path(registry_dir.name) / "order-claims-v2.json"
        registry.write_text(json.dumps({"schema": "order-claims-v2", "issuers": {}, "documents": [], "claims": []}), encoding="utf-8")
        saved_registry = publisher.order_claims.REGISTRY_PATH
        publisher.order_claims.REGISTRY_PATH = registry
        self.addCleanup(setattr, publisher.order_claims, "REGISTRY_PATH", saved_registry)

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
        monthly = {"source_id": "TPEX", "source_url": "https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap05_O", "period": "2026-08",
                   "revenue_yoy": 5.253153, "cumulative_yoy": 4.889214, "currency": "TWD"}
        doc["top"][1]["fundamentals"] = {"source": "Yahoo", "source_url": "https://finance.yahoo.com/quote/5351.TWO/financials",
                                         "quarter_end": "2026-06-30", "revenue": 4.9e9, "revenue_yoy": 5.58, "cross_check": monthly}
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "v3.json"
            path.write_text(json.dumps(doc), encoding="utf-8")
            body = publisher.lazy_bottleneck_v3_body(path, now)[publisher.BOTTLENECK_V3_KEY]
            sealed = json.loads(body)
            self.assertEqual(sealed["schema"], "v213-bottleneck-top20-v3-sealed")
            self.assertEqual(sealed["top"][1]["fundamentals"]["cross_check"], monthly)
            self.assertNotIn("revenue", sealed["top"][1]["fundamentals"])  # only the known keys are sealed
            self.assertIsNone(sealed["top"][0]["fundamentals"])
            self.assertNotIn("capture_detail", sealed["top"][0]["parts"])
            self.assertNotIn("intensity", sealed["top"][0]["serenity"])
            self.assertEqual(publisher.lazy_bottleneck_v3_body(path, now + timedelta(hours=14)), {})

    def test_exchange_cross_check_uses_exchange_feeds_only(self):
        shards = {"shards": {
            "US": {"sources": [{"id": "nasdaq-us-screener", "url": "https://api.nasdaq.com/api/screener/stocks"}], "rows": {"NVDA": [224.58, -0.4, "2026-09-24", "USD", 0]}},
            "JAPAN": {"sources": [{"id": "yahoo-daily-close", "url": "https://finance.yahoo.com/"}], "rows": {"4062": [5000.0, 1.0, "2026-09-25", "JPY", 0]}},
            "UK": {"sources": [{"id": "lse-aim", "url": "https://www.londonstockexchange.com/"}], "generated_at": "2026-09-26T00:00:00Z", "rows": {"IQE": [46.4, 5.3, None, "GBX", 0]}},
            "SWEDEN": {"sources": [{"id": "nasdaq-stockholm-main", "url": "https://api.nasdaq.com/api/nordic/"}], "rows": {"SIVE": [32.78, 0.0, None, "SEK", 0]}},
            "EUROPE": {"sources": [{"id": "euronext-equities", "url": "https://live.euronext.com/"}], "rows": {
                "EURONEXT PARIS|SOI": [21.5, 0.1, "2026-09-25", "EUR", 0], "EURONEXT PARIS|DUP": [1.0, 0, None, "EUR", 0], "EURONEXT BRUSSELS|DUP": [2.0, 0, None, "EUR", 0]}}}}
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "shards.json"
            path.write_text(json.dumps(shards), encoding="utf-8")
            checks = publisher._exchange_cross_checks(["NVDA", "4062.T", "IQE.L", "SIVE.ST", "SOI.PA", "DUP.PA"], {
                "NVDA": {"price": 225.07, "currency": "USD"}, "4062.T": {"price": 5010.0, "currency": "JPY"},
                "IQE.L": {"price": 46.5, "currency": "GBp"}, "SIVE.ST": {"price": 33.0, "currency": "USD"}}, path)
        self.assertEqual(checks["NVDA"]["source_id"], "nasdaq-us-screener")
        self.assertAlmostEqual(checks["NVDA"]["diff"], round(225.07 / 224.58 - 1, 5))
        self.assertNotIn("4062.T", checks)  # a Yahoo shard is not an independent source
        self.assertAlmostEqual(checks["IQE.L"]["diff"], round(46.5 / 46.4 - 1, 5))  # GBp and GBX are the same unit
        self.assertEqual(checks["IQE.L"]["asof"], "2026-09-26T00:00:00Z")
        self.assertIsNone(checks["SIVE.ST"]["diff"])  # different currencies are not compared
        self.assertEqual(checks["SOI.PA"]["price"], 21.5)  # Euronext rows are keyed by venue
        self.assertNotIn("DUP.PA", checks)  # a symbol on two venues is ambiguous

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
        second = publisher._sealed_outlook({"consensus_second": {"target_mean": 324.32, "target_upside": 0.44, "target_analysts": 33,
                                                                 "eps_growth": float("nan"), "source": "Nasdaq.com analyst estimates",
                                                                 "source_url": "https://www.nasdaq.com/x", "junk": 1}})["consensus_second"]
        self.assertEqual((second["target_mean"], second["eps_growth"]), (324.32, None))
        self.assertNotIn("junk", second)
        self.assertIsNone(publisher._sealed_outlook({"consensus_second": {"target_mean": 1, "source_url": "http://x"}})["consensus_second"])
        backlog = publisher._sealed_outlook({"orders": {
            "kind": "BACKLOG", "amount": 17507e9, "currency": "KRW", "as_of": "2026-06-30", "yoy": 0.63, "scope": "重工業部門",
            "source": "deck p.9", "source_url": "https://www.hyosungheavyindustries.com/download/5816",
            "intake_quarter": {"amount": 3324.2e9, "yoy": 0.51, "junk": "x"},
            "guidance": {"kind": "ANNUAL_NEW_ORDERS", "year": 2026, "amount": 12e12, "previous": float("nan"), "note": "x"}}})["orders"]
        self.assertEqual(backlog["intake_quarter"], {"amount": 3324.2e9, "yoy": 0.51})
        check = {"source_id": "TPEX", "source_url": "https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap05_O", "period": "2026-08",
                 "revenue_yoy": 5.253153, "cumulative_yoy": 4.889214, "currency": "TWD", "junk": 1}
        self.assertEqual(publisher._sealed_revenue_check(check), {k: v for k, v in check.items() if k != "junk"})
        for bad in ({**check, "source_id": "YAHOO"}, {**check, "source_url": "http://x"}, {**check, "period": "2026-13"},
                    {**check, "revenue_yoy": float("nan"), "cumulative_yoy": None}, {**check, "period": "2026-Q2"},
                    {**check, "period": "2026-０８"}, None):
            self.assertIsNone(publisher._sealed_revenue_check(bad))
        report = {"source_id": "CISION", "source_url": "https://news.cision.com/x/r/q2,c2", "period": "2026-Q2", "revenue_yoy": -0.123779,
                  "cumulative_yoy": None, "currency": "TWD"}
        self.assertEqual(publisher._sealed_revenue_check(report), {**report, "currency": "SEK"})  # the currency follows the source
        self.assertIsNone(publisher._sealed_revenue_check({**report, "period": "2026-08"}))
        self.assertEqual(backlog["guidance"], {"kind": "ANNUAL_NEW_ORDERS", "year": 2026.0, "amount": 12e12, "previous": None})

    def _seal_one(self, market, fundamentals=None, part="market"):
        """Seals twelve entries whose first is SNDK with the given market object; returns that sealed market object
        (or another part of the sealed entry)."""
        now = datetime.now(timezone.utc).replace(microsecond=0)
        entry = {"rank": 1, "symbol": "SNDK", "name": "Sandisk", "layer": "memory", "archetype": "COMPOUNDER", "score": 70.0,
                 "role": "NAND", "role_source": {"url": "https://x.com/a/status/1", "date": "2026-09-03"},
                 "score_parts": {"layer_heat": 5, "capture": 4, "lead": 14, "confirmation": 15, "size": 10, "penalty": 0},
                 "fundamentals": fundamentals, "market": market, "market_cap_usd": 5e10, "serenity": None, "leopold": None}
        doc = {"schema": "v213-bottleneck-top20-v3", "generated_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"), "leads": {},
               "top": [{**entry, "rank": index + 1, "symbol": "SNDK" if index == 0 else f"S{index}"} for index in range(12)],
               "industries": [{"rank": 1, "id": "memory", "name_zh": "記憶體", "chain": "chips_memory", "leopold_constraint": "x",
                               "explosiveness": 52.1, "median_revenue_yoy": 0.3, "median_acceleration": 0.1, "median_return_6m": 0.5,
                               "fund_13f_weight": 0.0, "serenity_heat": 12.0, "news": None}]}
        saved = publisher.build_zh_names.names_for
        publisher.build_zh_names.names_for = lambda symbols: {}
        try:
            with tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp) / "v3.json"
                path.write_text(json.dumps(doc), encoding="utf-8")
                return json.loads(publisher.lazy_bottleneck_v3_body(path, now)[publisher.BOTTLENECK_V3_KEY])["top"][0][part]
        finally:
            publisher.build_zh_names.names_for = saved

    def test_sealed_long_term_fields_are_validated_consistent_and_fail_closed(self):
        record = lineage.load()["SNDK"]
        base = {"source": "Yahoo", "source_url": "https://finance.yahoo.com/quote/SNDK", "asof": "2026-09-25", "ret_6m": 1.9,
                "ret_1y": 17.8, "cagr_2y": None, "history_start": "2025-02-13", "currency": "USD"}
        good = {**base, "lineage": {**record, "extra": "dropped"}, "history_request_start": "2023-09-25", "cagr_listed": 4.1,
                "cagr_listed_start": "2025-02-24", "cagr_listed_span_days": 578, "long_term_basis": "SINCE_REGULAR_WAY", "price": 1.0}
        sealed = self._seal_one(good)
        self.assertEqual(sealed["lineage"], record)  # extras stripped, citations kept
        self.assertEqual((sealed["cagr_listed"], sealed["cagr_listed_start"], sealed["cagr_listed_span_days"], sealed["long_term_basis"]),
                         (4.1, "2025-02-24", 578, "SINCE_REGULAR_WAY"))
        self.assertNotIn("price", sealed)
        later = datetime.now(timezone.utc).date() + timedelta(days=30)
        # PRESENT but broken metadata suppresses every long-term figure, the two-year one included.
        closed = {"lineage": {"kind": "UNKNOWN"}, "cagr_2y": None, "cagr_listed": None, "cagr_listed_start": None,
                  "cagr_listed_span_days": None, "long_term_basis": "UNAVAILABLE"}
        for broken in ({"cagr_listed_start": "2025-02-13"},            # a when-issued base
                       {"cagr_listed_span_days": 300},                 # too short to annualize
                       {"cagr_listed_span_days": 579},                 # the span does not match asof - start
                       {"asof": "2025-03-01"},                         # five days of history cannot carry a 578-day span
                       {"long_term_basis": "TWO_YEAR"},                # the basis contradicts the values
                       {"long_term_basis": "TWO_YEAR", "cagr_2y": 0.9, "cagr_listed": None, "cagr_listed_start": None,
                        "cagr_listed_span_days": None},                # a 2025 segment cannot have two years
                       {"asof": str(later), "cagr_listed_span_days": (later - date(2025, 2, 24)).days},  # after the report date
                       {"lineage": {**record, "regular_way_start": "2025-02-30"}},
                       {"lineage": {**record, "regular_way_start": "2025-06-24"}},  # 123 days after the event
                       {"lineage": {**record, "sources": []}},
                       {"lineage": {"kind": "UNKNOWN", "note": "extra"}},  # a malformed UNKNOWN object
                       {"history_request_start": "not a date"},
                       {"history_request_start": "2026-10-01"}):       # a request that starts after asof
            self.assertEqual({key: self._seal_one({**good, **broken})[key] for key in closed}, closed, broken)
        broken_two = self._seal_one({**good, "cagr_2y": 0.9, "long_term_basis": "TWO_YEAR", "cagr_listed": None,
                                     "cagr_listed_start": None, "cagr_listed_span_days": None})
        self.assertIsNone(broken_two["cagr_2y"])
        # ABSENT metadata (an older producer): the two-year value stays, the unverified since-listing figure never, and
        # no metadata is invented on the wire (the Worker applies the same legacy rule; resealing is idempotent).
        legacy = self._seal_one({**base, "cagr_listed": 4.1})
        self.assertEqual(legacy["cagr_2y"], None)
        for key in ("lineage", "long_term_basis", "history_request_start", "cagr_listed", "cagr_listed_start", "cagr_listed_span_days"):
            self.assertNotIn(key, legacy)
        seasoned = self._seal_one({**base, "cagr_2y": 0.8, "cagr_listed": None})
        self.assertEqual(seasoned["cagr_2y"], 0.8)
        self.assertNotIn("long_term_basis", seasoned)
        self.assertEqual(self._seal_one({key: value for key, value in seasoned.items() if key != "cross_check"}), seasoned)
        verified_two = self._seal_one({**base, "cagr_2y": 0.8, "history_start": "2023-09-25", "lineage": {"kind": "UNKNOWN"},
                                       "history_request_start": "2023-09-25", "cagr_listed": None, "cagr_listed_start": None,
                                       "cagr_listed_span_days": None, "long_term_basis": "TWO_YEAR"})
        self.assertEqual((verified_two["cagr_2y"], verified_two["long_term_basis"]), (0.8, "TWO_YEAR"))

    def test_a_fixed_cutoff_seal_carries_a_numeric_revision_to_the_worker_fixture(self):
        """Astra ORDERS-V2-01 review fix 10: the real sealing path at a fixed build instant, with a deep-report filing and a
        reviewed later RPO with its own schedule; a numeric revision of the registry changes the sealed figures; the
        sealed forecast is the Worker's caller fixture (cloud/test/v213-order-forecast-v2.test.ts)."""
        import os
        import order_forecast
        now = datetime(2026, 9, 27, 1, 0, 0, tzinfo=timezone.utc)
        fixture = ROOT / "tests" / "fixtures" / "v213-order-forecast-v2-sealed.json"
        recognition = {"status": "DISCLOSED", "form": "10-Q", "filed": "2026-08-10", "url": "https://www.sec.gov/Archives/sndk-q.htm",
                       "rpo": 40e9, "rpo_as_of": "2026-06-30", "quarter_revenue": 8e9, "quarter_start": "2026-04-01",
                       "quarter_end": "2026-06-30", "quarter_basis": "FRAME", "accession": "0000000000-26-000001",
                       "passage": "30% within six months and 55% within twelve months", "report_date": "2026-06-30",
                       "horizons": {"m6": {"share_pct": 30.0, "derived": False}, "m12": {"share_pct": 55.0, "derived": False}, "m24": None}}
        registry = {"schema": "order-claims-v2", "issuers": {"SNDK": {"name": "Sandisk", "url_prefixes": ["https://investor.sandisk.com/"]}},
                    "documents": [{"id": "SNDK-8K", "issuer": "SNDK", "publisher": "Sandisk", "title": "Results", "source_kind": "SEC_8K_EXHIBIT",
                                   "url": "https://www.sec.gov/Archives/edgar/data/2023554/sndk-8k.htm", "published_date": "2026-08-12",
                                   "retrieved_at": "2026-09-20T00:00:00Z", "sha256": "c" * 64, "byte_size": 800, "lineage_id": "SNDK-Q",
                                   "sec": {"accession": "0000000000-26-000002", "form": "8-K", "exhibit": "99.1"}}],
                    "claims": [{"id": "SNDK-RPO", "symbol": "SNDK", "document_id": "SNDK-8K", "locator": "table 3", "passage": "RPO was $44.0 billion",
                                "metric": "RPO_STOCK", "assertion_kind": "DISCLOSED_FACT", "currency": "USD", "unit_multiplier": 1000000000,
                                "amount": 44, "as_of": "2026-07-31", "scope": "COMPANY", "series_id": "SNDK:RPO", "basis": "ASC 606",
                                "revision": {"kind": "ORIGINAL"}, "review": {"checked_at": "2026-09-21T00:00:00Z", "receipt": "fixture"}},
                               {"id": "SNDK-SCHED", "symbol": "SNDK", "document_id": "SNDK-8K", "locator": "table 3",
                                "passage": "about 35% within six months and 60% within twelve months", "metric": "RECOGNITION_SCHEDULE",
                                "assertion_kind": "DISCLOSED_FACT", "currency": "USD", "unit_multiplier": 1000000000, "amount": None,
                                "as_of": "2026-07-31", "scope": "COMPANY", "series_id": "SNDK:SCHEDULE", "basis": "ASC 606",
                                "stock_claim_id": "SNDK-RPO", "shares": {"m6": 35.0, "m12": 60.0},
                                "revision": {"kind": "ORIGINAL"}, "review": {"checked_at": "2026-09-21T00:00:00Z", "receipt": "fixture"}}]}
        publisher.company_deep_report.load_order_scenarios = lambda *args, **kwargs: {"SNDK": recognition}
        path = publisher.order_claims.REGISTRY_PATH

        def seal() -> dict:
            path.write_text(json.dumps(registry), encoding="utf-8")
            entry = {"rank": 1, "symbol": "SNDK", "name": "Sandisk", "layer": "memory", "archetype": "COMPOUNDER", "score": 70.0,
                     "role": "NAND", "role_source": {"url": "https://x.com/a/status/1", "date": "2026-09-03"},
                     "score_parts": {"layer_heat": 5, "capture": 4, "lead": 14, "confirmation": 15, "size": 10, "penalty": 0},
                     "fundamentals": None, "market": {"source": "Yahoo", "source_url": "https://finance.yahoo.com/quote/SNDK",
                                                      "asof": "2026-09-25", "ret_6m": 0.1, "ret_1y": 0.2, "cagr_2y": 0.3,
                                                      "history_start": "2023-09-25", "currency": "USD"},
                     "market_cap_usd": 5e10, "serenity": None, "leopold": None}
            doc = {"schema": "v213-bottleneck-top20-v3", "generated_at": "2026-09-27T01:00:00Z", "leads": {},
                   "top": [{**entry, "rank": index + 1, "symbol": "SNDK" if index == 0 else f"S{index}"} for index in range(12)],
                   "industries": [{"rank": 1, "id": "memory", "name_zh": "記憶體", "chain": "chips_memory", "leopold_constraint": "x",
                                   "explosiveness": 52.1, "median_revenue_yoy": 0.3, "median_acceleration": 0.1, "median_return_6m": 0.5,
                                   "fund_13f_weight": 0.0, "serenity_heat": 12.0, "news": None}]}
            saved = publisher.build_zh_names.names_for
            publisher.build_zh_names.names_for = lambda symbols: {}
            try:
                with tempfile.TemporaryDirectory() as tmp:
                    v3 = Path(tmp) / "v3.json"
                    v3.write_text(json.dumps(doc), encoding="utf-8")
                    return json.loads(publisher.lazy_bottleneck_v3_body(v3, now)[publisher.BOTTLENECK_V3_KEY])["top"][0]["outlook"]["order_forecast"]
            finally:
                publisher.build_zh_names.names_for = saved

        sealed = seal()
        expected = order_forecast.build_v2("SNDK", None, recognition, now.date(), now, publisher.order_claims.load())
        self.assertEqual(sealed, json.loads(json.dumps(expected)))
        self.assertEqual((sealed["evidence"]["cutoff"], sealed["m12"]["source"], sealed["m12"]["amount"]), ("2026-09-27T01:00:00Z", "REGISTRY", 44e9 * 0.6))
        self.assertEqual(sealed["m12"]["scenario"]["status"], "INSUFFICIENT_COVERAGE")  # the filing's quarter is within 45 days
        if os.environ.get("II_WRITE_ORDER_V2_FIXTURE") == "1":
            fixture.write_text(json.dumps({"generated_at": "2026-09-27T01:00:00Z", "issuer": "SNDK", "forecast": sealed},
                                          ensure_ascii=False, indent=1) + "\n", encoding="utf-8", newline="\n")
        self.assertEqual(json.loads(fixture.read_text(encoding="utf-8"))["forecast"], sealed)
        registry["claims"][0]["amount"] = 46  # a numeric revision at the same cutoff
        revised = seal()
        self.assertEqual(revised["m12"]["amount"], 46e9 * 0.6)
        self.assertNotEqual(revised["evidence"]["registry_sha256"], sealed["evidence"]["registry_sha256"])

    def test_sealing_reads_the_reviewed_order_claims_and_binds_their_digest(self):
        """Astra ORDERS-V2-01: the real sealing path loads the registry once, at the build cutoff, with no network; a
        changed registry changes the evidence and its digest; a malformed one is named, never replaced by old output."""
        import hashlib
        market = {"source": "Yahoo", "source_url": "https://finance.yahoo.com/quote/SNDK", "asof": "2026-09-25", "ret_6m": 0.1,
                  "ret_1y": 0.2, "cagr_2y": 0.3, "history_start": "2023-09-25", "currency": "USD"}
        today = datetime.now(timezone.utc).date()
        published = str(today - timedelta(days=3))
        registry = {"schema": "order-claims-v2", "issuers": {"SNDK": {"name": "Sandisk", "url_prefixes": ["https://investor.sandisk.com/news/"]}},
                    "documents": [{"id": "SNDK-PR", "issuer": "SNDK", "publisher": "Sandisk", "title": "Release", "source_kind":
                                   "ISSUER_CONTRACT_ANNOUNCEMENT", "url": "https://investor.sandisk.com/news/1", "published_date": published,
                                   "retrieved_at": f"{published}T12:00:00Z", "sha256": "b" * 64, "byte_size": 900, "lineage_id": "SNDK-PR"}],
                    "claims": [{"id": "SNDK-DEAL", "symbol": "SNDK", "document_id": "SNDK-PR", "locator": "para 2", "passage": "a supply agreement",
                                "summary": "長期供貨合約", "metric": "SIGNED_CONTRACT_VALUE", "assertion_kind": "DISCLOSED_FACT", "currency": "USD",
                                "unit_multiplier": 1000000000, "amount": 3, "as_of": published, "scope": "CONTRACT", "scope_label": "供貨合約",
                                "series_id": "SNDK:DEAL", "basis": "contract value",
                                "revision": {"kind": "SUPPLEMENTS", "overlap": "UNKNOWN"},
                                "review": {"checked_at": f"{published}T13:00:00Z", "receipt": "fixture"}}]}
        path = publisher.order_claims.REGISTRY_PATH
        path.write_text(json.dumps(registry), encoding="utf-8")
        forecast = self._seal_one(market, None, "outlook")["order_forecast"]
        evidence = forecast["evidence"]
        self.assertEqual((evidence["registry_status"], evidence["registry_sha256"]), ("OK", hashlib.sha256(path.read_bytes()).hexdigest()))
        self.assertEqual(forecast["references"], [{"kind": "CLAIM", "claim_id": "SNDK-DEAL"}])
        self.assertNotIn("review", evidence["claims"][0])  # the receipt reference stays private; the check time is sealed
        self.assertEqual(evidence["claims"][0]["checked_at"], f"{published}T13:00:00Z")
        self.assertEqual(evidence["url_prefixes"], ["https://investor.sandisk.com/news/"])
        # Only the issuer's own evidence is sealed with each entry.
        self.assertEqual(self._seal_one(market, None, "outlook")["order_forecast"]["evidence"]["documents"][0]["issuer"], "SNDK")
        # A changed registry at the same cutoff changes the evidence; a malformed one is explicit, not yesterday's output.
        registry["claims"][0]["amount"] = 4
        path.write_text(json.dumps(registry), encoding="utf-8")
        changed = self._seal_one(market, None, "outlook")["order_forecast"]["evidence"]
        self.assertEqual(changed["claims"][0]["amount"], 4)
        self.assertNotEqual(changed["registry_sha256"], evidence["registry_sha256"])
        path.write_text("{not json", encoding="utf-8")
        broken = self._seal_one(market, None, "outlook")["order_forecast"]
        self.assertEqual((broken["evidence"]["registry_status"], broken["evidence"]["claims"], broken["references"]), ("INVALID", [], []))
        path.unlink()
        missing = self._seal_one(market, None, "outlook")["order_forecast"]["evidence"]
        self.assertEqual((missing["registry_status"], missing["registry_sha256"]), ("UNAVAILABLE", None))

    def test_sealing_produces_dual_fields_v2_and_v3(self):
        """Astra contract ORDERS-V3-01 section 6: dual fields order_forecast (v2) and order_forecast_v3 (v3)."""
        market = {"source": "Yahoo", "source_url": "https://finance.yahoo.com/quote/SNDK", "asof": "2026-09-25", "ret_6m": 0.1,
                  "ret_1y": 0.2, "cagr_2y": 0.3, "history_start": "2023-09-25", "currency": "USD"}
        outlook = self._seal_one(market, None, "outlook")
        self.assertIn("order_forecast", outlook)
        self.assertIn("order_forecast_v3", outlook)
        self.assertEqual(outlook["order_forecast"]["version"], 2)
        self.assertEqual(outlook["order_forecast_v3"]["version"], 3)
        self.assertEqual(outlook["order_forecast_v3"]["formula"], "ORDERS-V3-01")
        self.assertEqual(outlook["order_forecast_v3"]["horizon_convention"], "FISCAL_2Q_4Q")

    def test_the_order_forecast_is_built_at_sealing_from_the_deep_report_schedule(self):
        import order_forecast
        market = {"source": "Yahoo", "source_url": "https://finance.yahoo.com/quote/SNDK", "asof": "2026-09-25", "ret_6m": 0.1,
                  "ret_1y": 0.2, "cagr_2y": 0.3, "history_start": "2023-09-25", "currency": "USD"}
        today = datetime.now(timezone.utc).date()  # the sealer's report day; the filing dates are relative to it
        as_of, filed = today - timedelta(days=60), today - timedelta(days=20)
        recognition = {"status": "DISCLOSED", "form": "10-K", "filed": str(filed), "url": "https://www.sec.gov/Archives/sndk-20260703.htm",
                       "rpo": 59.8e9, "rpo_as_of": str(as_of), "quarter_revenue": 8.965e9, "quarter_start": str(as_of - timedelta(days=90)),
                       "quarter_end": str(as_of), "quarter_basis": "FRAME", "accession": "0001628280-26-057406", "passage": "19% ... next twelve months",
                       "report_date": str(as_of),
                       "horizons": {"m6": None, "m12": {"share_pct": 19.0, "derived": False}, "m24": None}}
        publisher.company_deep_report.load_order_scenarios = lambda *args, **kwargs: {"SNDK": recognition}
        sealed = self._seal_one(market, None, "outlook")
        legacy = order_forecast.build("SNDK", None, recognition, today)
        self.assertEqual(sealed["order_forecast"]["version"], 2)
        # The filing's schedule, unchanged, now tagged with its source; an empty registry adds nothing.
        self.assertEqual(sealed["order_forecast"]["m12"], {**legacy["m12"], "source": "PERIODIC"})
        self.assertEqual(sealed["order_forecast"]["evidence"]["registry_status"], "EMPTY")
        self.assertEqual(sealed["order_forecast"]["references"], [])
        m12 = sealed["order_forecast"]["m12"]
        self.assertEqual((m12["status"], m12["basis"], m12["amount"], m12["end"]),
                         ("AVAILABLE", "RECOGNITION", 59.8e9 * 0.19, str(order_forecast.add_months(as_of, 12))))
        self.assertEqual(m12["scenario"]["status"], "INSUFFICIENT_COVERAGE")  # 11.36B of a 35.86B year: about 32%
        self.assertEqual(sealed["order_forecast"]["m6"]["reason"], "NOT_DISCLOSED_HORIZON")
        self.assertEqual(sealed["order_forecast"]["issuer"], "SNDK")

    def test_the_share_count_basis_is_sealed_only_when_known(self):
        market = {"source": "Yahoo", "source_url": "https://finance.yahoo.com/quote/POET", "asof": "2026-09-25", "ret_6m": 0.1,
                  "ret_1y": 0.2, "cagr_2y": 0.3, "history_start": "2023-09-25", "currency": "USD"}
        fund = {"source": "Yahoo Finance quarterly income statement (unofficial)", "source_url": "https://finance.yahoo.com/quote/POET/financials",
                "quarter_end": "2026-06-30", "revenue_yoy": 0.5, "revenue_yoy_prev": None, "gross_margin": None,
                "gross_margin_change": None, "rpo_yoy": None, "shares_yoy": 1.003}
        diluted = self._seal_one(market, {**fund, "shares_basis": "DILUTED_WEIGHTED_AVERAGE"}, "fundamentals")
        self.assertEqual((diluted["shares_yoy"], diluted["shares_basis"]), (1.003, "DILUTED_WEIGHTED_AVERAGE"))
        unknown = self._seal_one(market, {**fund, "shares_basis": "GUESSED"}, "fundamentals")
        self.assertEqual((unknown["shares_yoy"], unknown["shares_basis"]), (None, None))  # an unknown basis is not published
        legacy = self._seal_one(market, fund, "fundamentals")  # an older producer: shares outstanding only, basis unstated
        self.assertEqual((legacy["shares_yoy"], legacy["shares_basis"]), (1.003, None))

    def test_the_sealed_long_term_fields_match_the_worker_contract_fixture(self):
        """tests/fixtures/v213-lineage-sealed-markets.json is the wire contract with the Worker: each case's input market
        sealed here must equal its recorded sealed form, which cloud/test/v213-bottleneck-v3.test.ts parses and renders."""
        golden = json.loads((ROOT / "tests" / "fixtures" / "v213-lineage-sealed-markets.json").read_text(encoding="utf-8"))
        self.assertGreaterEqual(len(golden["cases"]), 4)
        for case in golden["cases"]:
            sealed = self._seal_one(case["input"])
            sealed.pop("cross_check", None)  # the exchange cross-check depends on local price shards, not on this contract
            self.assertEqual(sealed, case["sealed"], case["name"])

    def test_sealed_entries_carry_the_sourced_chinese_name_and_listing_age(self):
        now = datetime.now(timezone.utc).replace(microsecond=0)
        market = {"source": "Yahoo", "source_url": "https://finance.yahoo.com/quote/SNDK", "asof": "2026-09-25", "ret_6m": 1.9,
                  "ret_1y": 17.8, "cagr_2y": None, "cagr_listed": 4.1, "history_start": "2025-02-13", "currency": "USD",
                  "lineage": lineage.load()["SNDK"], "history_request_start": "2023-09-25", "cagr_listed_start": "2025-02-24",
                  "cagr_listed_span_days": 578, "long_term_basis": "SINCE_REGULAR_WAY"}
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
        # A document built before outlooks existed: no orders or consensus, and an explicit order-forecast unavailability.
        self.assertEqual((sealed["top"][0]["outlook"]["orders"], sealed["top"][0]["outlook"]["consensus"]), (None, None))
        self.assertEqual(sealed["top"][0]["outlook"]["order_forecast"]["reason"], "NO_ORDERS")
        self.assertIsNone(sealed["top"][1]["name_zh"])
        self.assertEqual((sealed["top"][0]["market"]["cagr_listed"], sealed["top"][0]["market"]["history_start"]), (4.1, "2025-02-13"))
        self.assertEqual(sealed["top"][0]["market"]["lineage"]["related_entity"], {"name": "Western Digital", "symbol": "WDC"})


def daily(start, end, price):
    """Weekday closes from start to end (inclusive); price is a function of the date."""
    day, bars = date.fromisoformat(start), []
    while day <= date.fromisoformat(end):
        if day.weekday() < 5:
            bars.append((day, price(day)))
        day += timedelta(days=1)
    return bars


class ListingLineageTests(unittest.TestCase):
    REQUEST = date(2023, 9, 25)

    def test_the_curated_records_are_complete_and_sourced(self):
        records = lineage.load()
        self.assertEqual(sorted(records), ["ALAB", "CORZ", "CRWV", "NBIS", "SNDK"])
        self.assertEqual((records["SNDK"]["kind"], records["SNDK"]["event_date"], records["SNDK"]["regular_way_start"]),
                         ("SPINOFF", "2025-02-21", "2025-02-24"))
        self.assertEqual(records["NBIS"]["related_entity"], {"name": "Yandex N.V.", "symbol": "YNDX"})
        self.assertIsNone(records["ALAB"]["related_entity"])
        for record in records.values():
            self.assertTrue(all(source["url"].startswith("https://") for source in record["sources"]))

    def test_sandisk_counts_from_its_first_regular_way_session_not_when_issued_trading(self):
        record = lineage.load()["SNDK"]
        # When-issued SNDKV from 2025-02-13 at 36, regular way from 2025-02-24 at 50, 150 on the last day.
        bars = daily("2025-02-13", "2025-02-21", lambda day: 36.0) + daily("2025-02-24", "2026-09-24", lambda day: 50.0) \
            + [(date(2026, 9, 25), 150.0)]
        out = lineage.long_term_returns(bars, record, self.REQUEST)
        span = (date(2026, 9, 25) - date(2025, 2, 24)).days
        self.assertEqual((out["history_start"], out["cagr_listed_start"], out["cagr_listed_span_days"]), ("2025-02-13", "2025-02-24", span))
        self.assertAlmostEqual(out["cagr_listed"], 3.0 ** (365.25 / span) - 1, places=12)
        self.assertEqual((out["cagr_2y"], out["long_term_basis"], out["lineage"]["kind"]), (None, "SINCE_REGULAR_WAY", "SPINOFF"))
        self.assertAlmostEqual(out["ret_1y"], 2.0)
        # Without the record the when-issued bar would be the base: an unverified history is never annualized.
        unknown = lineage.long_term_returns(bars, None, self.REQUEST)
        self.assertEqual((unknown["cagr_listed"], unknown["long_term_basis"], unknown["lineage"]), (None, "UNAVAILABLE", {"kind": "UNKNOWN"}))
        self.assertTrue(lineage.truncated(unknown["history_start"], unknown["history_request_start"]))

    def test_a_missing_regular_way_session_or_bad_prices_leave_the_figure_unavailable(self):
        record = lineage.load()["SNDK"]
        late = daily("2025-02-25", "2026-09-25", lambda day: 50.0)
        self.assertEqual(lineage.long_term_returns(late, record, self.REQUEST)["long_term_basis"], "UNAVAILABLE")
        for bars in ([], [(date(2025, 2, 24), float("nan"))], daily("2025-02-24", "2026-09-25", lambda day: 0.0)):
            out = lineage.long_term_returns(bars, record, self.REQUEST)
            self.assertEqual((out.get("asof"), out["cagr_listed"], out["long_term_basis"]), (None, None, "UNAVAILABLE"))

    def test_annualization_needs_a_full_year_and_two_years_give_the_two_year_figure(self):
        record = {**lineage.load()["ALAB"], "event_date": "2024-01-01", "regular_way_start": "2024-01-02"}
        start = date(2024, 1, 2)
        for days, basis in ((364, "UNAVAILABLE"), (365, "SINCE_REGULAR_WAY"), (730, "TWO_YEAR")):
            bars = [(start, 10.0), (start + timedelta(days=days // 2), 12.0), (start + timedelta(days=days), 20.0)]
            out = lineage.long_term_returns(bars, record, self.REQUEST)
            self.assertEqual(out["long_term_basis"], basis, days)
            if basis == "SINCE_REGULAR_WAY":
                self.assertAlmostEqual(out["cagr_listed"], 2.0 ** (365.25 / 365) - 1)
            if basis == "TWO_YEAR":
                self.assertAlmostEqual(out["cagr_2y"], 2.0 ** 0.5 - 1)
                self.assertIsNone(out["cagr_listed"])

    def test_a_resumption_never_bridges_the_suspension(self):
        record = lineage.load()["NBIS"]
        bars = daily("2021-01-04", "2022-02-25", lambda day: 90.0) + daily("2024-10-21", "2026-09-25", lambda day: 20.0)
        out = lineage.long_term_returns(bars, record, date(2021, 1, 1))
        self.assertEqual((out["cagr_2y"], out["cagr_listed_start"], out["long_term_basis"]), (None, "2024-10-21", "SINCE_REGULAR_WAY"))
        self.assertAlmostEqual(out["cagr_listed"], 0.0)  # flat since the resumption, not -78% against the 2022 price
        late_vendor = daily("2024-10-23", "2026-09-25", lambda day: 20.0)  # a late first bar is not taken as the resumption
        self.assertEqual(lineage.long_term_returns(late_vendor, record, self.REQUEST)["long_term_basis"], "UNAVAILABLE")

    def test_two_year_listings_and_seasoned_listings_keep_the_two_year_figure(self):
        records = lineage.load()
        for symbol, start in (("ALAB", "2024-03-20"), ("CORZ", "2024-01-24"), (None, "2023-09-25")):
            bars = daily(start, "2026-09-25", lambda day: 10.0 + (day.toordinal() % 7))
            out = lineage.long_term_returns(bars, records.get(symbol), self.REQUEST)
            self.assertEqual(out["long_term_basis"], "TWO_YEAR", symbol)
            self.assertEqual(out["lineage"]["kind"], records[symbol]["kind"] if symbol else "UNKNOWN")
        self.assertFalse(lineage.truncated("2023-09-28", "2023-09-23"))  # a weekend start is an ordinary session start
        self.assertTrue(lineage.truncated("2023-10-03", "2023-09-23"))

    def test_malformed_or_uncovered_records_are_refused(self):
        good = json.loads(json.dumps(lineage.load()["SNDK"]))
        for change in ({"event_date": "2025-02-30"}, {"regular_way_start": "2025-02-20"}, {"regular_way_start": "2025-06-24"},
                       {"kind": "MERGER"}, {"related_entity": None}, {"sources": []},
                       {"sources": [{**good["sources"][0], "url": "http://www.sec.gov/x"}]},
                       {"sources": [{**good["sources"][0], "claims": ["kind", "event_date"]}]},
                       {"sources": [{**good["sources"][0], "published_at": "2025-13-01"}]}):
            self.assertIsNone(lineage.clean_record({**good, **change}), change)
        ipo = json.loads(json.dumps(lineage.load()["ALAB"]))
        self.assertIsNone(lineage.clean_record({**ipo, "related_entity": {"name": "Invented parent", "symbol": None}}))
        self.assertIsNotNone(lineage.clean_record(ipo))

    def test_the_gate_tells_missing_history_from_a_negative_return_and_adds_no_score(self):
        self.assertEqual(engine.long_term_gate({"cagr_2y": 0.4}), (0.4, []))
        self.assertEqual(engine.long_term_gate({"cagr_2y": None, "cagr_listed": 2.0, "lineage": {"kind": "SPINOFF"}}), (2.0, []))
        self.assertEqual(engine.long_term_gate({"cagr_2y": -0.1}), (-0.1, ["LONG_TERM_RETURN_NOT_POSITIVE"]))
        self.assertEqual(engine.long_term_gate({"cagr_2y": 0.0}), (0.0, ["LONG_TERM_RETURN_NOT_POSITIVE"]))
        self.assertEqual(engine.long_term_gate({"cagr_2y": None, "cagr_listed": None, "lineage": {"kind": "UNKNOWN"}}),
                         (None, ["HISTORY_OR_LINEAGE_UNVERIFIED"]))
        self.assertEqual(engine.long_term_gate({"cagr_2y": None, "cagr_listed": None, "lineage": {"kind": "IPO"}}),
                         (None, ["MARKET_HISTORY_UNDER_1Y"]))
        self.assertEqual(engine.long_term_gate(None), (None, ["HISTORY_OR_LINEAGE_UNVERIFIED"]))


class YahooBoundaryTests(unittest.TestCase):
    """Astra batch 25 item 4: the history request names its explicit start (not a 3y period), vendor extremes never
    crash (the market object is simply unavailable), no non-finite return leaks out, and the sealed lineage fields
    stay consistent."""

    def call_with_frame(self, frame, symbol="TEST", record=None):
        """engine.yahoo_data with a fake yfinance: Ticker(symbol).history(**kwargs) records the kwargs and returns
        `frame`; fast_info, info and quarterly_income_stmt are absent and must stay tolerated. sys.modules is
        restored in finally."""
        import types
        calls = []

        class Ticker:
            def __init__(self, symbol):
                self.symbol = symbol
            def history(self, **kwargs):
                calls.append(kwargs)
                return frame
        module = types.ModuleType("yfinance")
        module.Ticker = Ticker
        saved = sys.modules.get("yfinance")
        sys.modules["yfinance"] = module
        try:
            return calls, engine.yahoo_data(symbol, record)
        finally:
            if saved is None:
                sys.modules.pop("yfinance", None)
            else:
                sys.modules["yfinance"] = saved

    def frame(self, bars):
        import pandas as pd
        return pd.DataFrame({"Close": [close for _, close in bars]}, index=pd.DatetimeIndex([day for day, _ in bars]))

    def test_the_request_names_an_explicit_start_and_the_market_object_carries_it(self):
        today = datetime.now(timezone.utc).date()
        start = lineage.request_start(today)
        calls, out = self.call_with_frame(self.frame(daily(start.isoformat(), today.isoformat(), lambda day: 12.0)))
        self.assertEqual(calls, [{"start": start.isoformat(), "auto_adjust": True}])
        self.assertEqual(out["market"]["history_request_start"], start.isoformat())

    def test_vendor_extremes_leave_the_market_object_unavailable(self):
        import pandas as pd
        index = pd.DatetimeIndex([pd.Timestamp("2024-01-02"), pd.Timestamp("2024-01-03")])
        for frame in (pd.DataFrame(),                                             # empty frame
                      pd.DataFrame({"Open": [1.0]}, index=index),                # no Close column
                      pd.DataFrame({"Close": [float("nan")] * 2}, index=index),  # all-NaN closes
                      pd.DataFrame({"Close": [-1.0, 0.0]}, index=index),        # non-positive closes
                      pd.DataFrame({"Close": [float("inf")]}, index=pd.DatetimeIndex([pd.Timestamp("2024-01-02")]))):
            calls, out = self.call_with_frame(frame)
            self.assertEqual(out, {"symbol": "TEST"}, frame)

    def test_extreme_closes_never_leak_non_finite_returns(self):
        import math
        today = datetime.now(timezone.utc).date()
        bars = [(today - timedelta(days=400), 1e-300), (today, 1e300)]
        calls, out = self.call_with_frame(self.frame(bars))
        market = out["market"]
        self.assertEqual(market["price"], 1e300)
        for key in ("ret_6m", "ret_1y", "cagr_2y", "cagr_listed"):
            self.assertTrue(market[key] is None or math.isfinite(market[key]), key)

    def test_a_seasoned_series_gives_the_two_year_basis_without_truncation(self):
        import math
        today = datetime.now(timezone.utc).date()
        start = lineage.request_start(today)
        calls, out = self.call_with_frame(self.frame(daily(start.isoformat(), today.isoformat(), lambda day: 12.0)))
        self.assertEqual(out["market"]["long_term_basis"], "TWO_YEAR")
        self.assertFalse(out["market"]["history_truncated"])
        self.assertTrue(math.isfinite(out["market"]["cagr_2y"]))

    def test_sandisk_counts_from_its_regular_way_session_and_not_before(self):
        import math
        record = lineage.load()["SNDK"]
        today = datetime.now(timezone.utc).date()
        # When-issued SNDKV from 2025-02-13 at 36, regular way from 2025-02-24 at 50, 150 on the last day.
        bars = daily("2025-02-13", "2025-02-21", lambda day: 36.0) \
            + daily("2025-02-24", (today - timedelta(days=1)).isoformat(), lambda day: 50.0) + [(today, 150.0)]
        frame = self.frame(bars)
        calls, out = self.call_with_frame(frame, "SNDK", record)
        self.assertEqual((out["market"]["cagr_listed_start"], out["market"]["long_term_basis"]), ("2025-02-24", "SINCE_REGULAR_WAY"))
        self.assertTrue(math.isfinite(out["market"]["cagr_listed"]))
        calls, unverified = self.call_with_frame(frame, "SNDK", None)
        self.assertEqual(unverified["market"]["long_term_basis"], "UNAVAILABLE")
        self.assertTrue(unverified["market"]["history_truncated"])


class SharesDilutionTests(unittest.TestCase):
    """Batch 28: the dilution penalty keeps a figure when the dei share-count tag is absent (SEC dual-class filers)
    or the Yahoo statement carries no share count: the diluted weighted average, quarterly rows only."""

    DILUTED = "WeightedAverageNumberOfDilutedSharesOutstanding"

    def _facts(self, dei=True, diluted=True, year_ago=True):
        facts = json.loads(json.dumps(FACTS))
        if not dei:
            facts["facts"].pop("dei", None)
        if not diluted:
            return facts
        rows = [  # quarterly rows on the FACTS fiscal calendar (latest 2026-06-27), plus the rows that must be ignored
            {"start": "2024-06-30", "end": "2024-09-28", "val": 70e6, "filed": "2024-11-01"},
            {"start": "2024-09-29", "end": "2024-12-28", "val": 72e6, "filed": "2025-02-01"},
            {"start": "2024-12-29", "end": "2025-03-29", "val": 74e6, "filed": "2025-05-01"},
            {"start": "2025-06-29", "end": "2025-09-27", "val": 82e6, "filed": "2025-11-01"},
            {"start": "2025-09-28", "end": "2025-12-27", "val": 84e6, "filed": "2026-02-01"},
            {"start": "2025-12-28", "end": "2026-03-28", "val": 90e6, "filed": "2026-05-01"},
            {"start": "2026-03-29", "end": "2026-06-27", "val": 162e6, "filed": "2026-08-15"},
            {"start": "2025-12-28", "end": "2026-06-27", "val": 130e6, "filed": "2026-08-15"},  # six-month YTD, same end: ignored
            {"start": "2025-06-29", "end": "2026-06-27", "val": 420e6, "filed": "2026-08-15"}]  # annual: ignored
        if year_ago:
            rows.insert(3, {"start": "2025-03-30", "end": "2025-06-28", "val": 80e6, "filed": "2025-08-15"})
        facts["facts"]["us-gaap"][self.DILUTED] = {"units": {"shares": rows}}
        return facts

    def test_sec_falls_back_to_the_diluted_weighted_average_quarters(self):
        fundamentals = engine.sec_fundamentals("CRWV", 1, self._facts(dei=False))
        self.assertAlmostEqual(fundamentals["shares_yoy"], 162e6 / 80e6 - 1)  # the YTD and annual rows are ignored
        self.assertEqual(fundamentals["shares_basis"], "DILUTED_WEIGHTED_AVERAGE")

    def test_sec_takes_the_latest_filing_of_a_quarter_reported_twice(self):
        # Each 10-Q repeats the year-ago quarter as a comparative (real CRWV companyfacts): the latest filing wins, no crash.
        facts = self._facts(dei=False)
        facts["facts"]["us-gaap"][self.DILUTED]["units"]["shares"].append(
            {"start": "2025-03-30", "end": "2025-06-28", "val": 81e6, "filed": "2026-08-15"})
        fundamentals = engine.sec_fundamentals("CRWV", 1, facts)
        self.assertAlmostEqual(fundamentals["shares_yoy"], 162e6 / 81e6 - 1)

    def test_sec_dei_share_count_wins_over_the_diluted_fallback(self):
        fundamentals = engine.sec_fundamentals("CRWV", 1, self._facts())
        self.assertAlmostEqual(fundamentals["shares_yoy"], 0.2)  # dei 100 -> 120, not the diluted 162e6/80e6
        self.assertEqual(fundamentals["shares_basis"], "OUTSTANDING")

    def test_sec_without_a_year_ago_quarter_has_no_share_figure(self):
        fundamentals = engine.sec_fundamentals("CRWV", 1, self._facts(dei=False, year_ago=False))
        self.assertIsNone(fundamentals["shares_yoy"])
        self.assertIsNone(fundamentals["shares_basis"])

    def _yahoo(self, statement, symbol="POET"):
        """engine.yahoo_data with a fake yfinance whose Ticker carries the given quarterly_income_stmt; sys.modules
        is restored in finally (the YahooBoundaryTests pattern)."""
        import types
        frame = self._frame(daily("2024-01-02", "2026-09-25", lambda day: 12.0))

        class Ticker:
            def __init__(self, symbol):
                self.symbol = symbol
                self.quarterly_income_stmt = statement
            def history(self, **kwargs):
                return frame
        module = types.ModuleType("yfinance")
        module.Ticker = Ticker
        saved = sys.modules.get("yfinance")
        sys.modules["yfinance"] = module
        try:
            return engine.yahoo_data(symbol)
        finally:
            if saved is None:
                sys.modules.pop("yfinance", None)
            else:
                sys.modules["yfinance"] = saved

    def _frame(self, bars):
        import pandas as pd
        return pd.DataFrame({"Close": [close for _, close in bars]}, index=pd.DatetimeIndex([day for day, _ in bars]))

    def _stmt(self, shares):
        import pandas as pd  # like yfinance: metrics as the index, quarter-ends as the columns
        periods = ["2025-03-31", "2025-06-30", "2025-09-30", "2025-12-31", "2026-03-31", "2026-06-30"]
        data = {}
        for index, period in enumerate(periods):
            row = {"Total Revenue": 30e6 * (index + 1)}
            if shares is not None:  # a missing period stays NaN and is dropped, like the vendor's row
                row["Diluted Average Shares"] = shares.get(period, float("nan"))
            data[pd.Timestamp(period)] = row
        return pd.DataFrame(data)

    def test_yahoo_shares_come_from_the_diluted_average_shares_row(self):
        # POET: 81.05M on 2025-06-30 -> 162.37M on 2026-06-30, about +1.003
        fund = self._yahoo(self._stmt({"2025-06-30": 81_053_634, "2026-06-30": 162_367_291}))["fundamentals"]
        self.assertAlmostEqual(fund["shares_yoy"], 162_367_291 / 81_053_634 - 1)
        self.assertEqual(fund["shares_basis"], "DILUTED_WEIGHTED_AVERAGE")

    def test_yahoo_without_the_shares_row_stays_none(self):
        fund = self._yahoo(self._stmt(None))["fundamentals"]
        self.assertIsNone(fund["shares_yoy"])
        self.assertIsNone(fund["shares_basis"])

    def test_yahoo_implausible_share_growth_is_a_data_error(self):
        fund = self._yahoo(self._stmt({"2025-06-30": 8_000_000, "2026-06-30": 80_000_000}))["fundamentals"]
        self.assertIsNone(fund["shares_yoy"])  # +900% is outside (-0.5, 5.0)
        self.assertIsNone(fund["shares_basis"])

    def test_shares_yoy_needs_strictly_positive_finite_counts(self):
        self.assertIsNone(engine._shares_yoy(-120, -100))  # negative counts are not a -20% figure
        self.assertIsNone(engine._shares_yoy(0, 100))
        self.assertIsNone(engine._shares_yoy(100, 0))
        self.assertIsNone(engine._shares_yoy(100, float("nan")))
        self.assertAlmostEqual(engine._shares_yoy(120, 100), 0.2)

    def test_sec_fallback_ignores_older_quarters_when_the_quarter_end_row_is_missing(self):
        # Astra batch 28: with no diluted row ending on the financial quarter's end, an older quarter's growth
        # (here March) must not be shown and penalised as the current one.
        facts = self._facts(dei=False)
        rows = facts["facts"]["us-gaap"][self.DILUTED]["units"]["shares"]
        rows[:] = [row for row in rows if row["end"] != "2026-06-27"]
        fundamentals = engine.sec_fundamentals("CRWV", 1, facts)
        self.assertIsNone(fundamentals["shares_yoy"])
        self.assertIsNone(fundamentals["shares_basis"])

    def test_sec_quarter_filer_with_rows_only_to_the_third_quarter_has_no_share_figure(self):
        # A fourth fiscal quarter is often filed only as the annual figure: the quarter-length rows stop at Q3, so
        # the financial quarter (Q4, end 2026-06-27) has no diluted row of its own -> None, never the Q3 figure.
        facts = self._facts(dei=False)
        rows = facts["facts"]["us-gaap"][self.DILUTED]["units"]["shares"]
        rows[:] = [row for row in rows if row["end"] < "2026-03-29"]  # the 2026-06-27 YTD/annual rows remain: ignored
        fundamentals = engine.sec_fundamentals("CRWV", 1, facts)
        self.assertIsNone(fundamentals["shares_yoy"])
        self.assertIsNone(fundamentals["shares_basis"])

    def test_sec_negative_share_counts_are_a_data_error(self):
        facts = self._facts(dei=False)
        for row in facts["facts"]["us-gaap"][self.DILUTED]["units"]["shares"]:
            row["val"] = -row["val"]
        fundamentals = engine.sec_fundamentals("CRWV", 1, facts)
        self.assertIsNone(fundamentals["shares_yoy"])
        self.assertIsNone(fundamentals["shares_basis"])

    def test_sec_dei_negative_share_counts_are_a_data_error(self):
        facts = self._facts(diluted=False)
        for row in facts["facts"]["dei"]["EntityCommonStockSharesOutstanding"]["units"]["shares"]:
            row["val"] = -row["val"]
        fundamentals = engine.sec_fundamentals("CRWV", 1, facts)
        self.assertIsNone(fundamentals["shares_yoy"])
        self.assertIsNone(fundamentals["shares_basis"])

    def test_yahoo_shares_only_in_older_quarters_are_not_substituted(self):
        # Shares only for March 2025/2026 while the revenue runs to June 2026: the June quarter's column has no
        # share count -> None, never the March figure.
        fund = self._yahoo(self._stmt({"2025-03-31": 80_000_000, "2026-03-31": 160_000_000}))["fundamentals"]
        self.assertIsNone(fund["shares_yoy"])
        self.assertIsNone(fund["shares_basis"])

    def test_yahoo_zero_or_negative_share_counts_are_data_errors(self):
        fund = self._yahoo(self._stmt({"2025-06-30": 0, "2026-06-30": 162_367_291}))["fundamentals"]
        self.assertIsNone(fund["shares_yoy"])
        self.assertIsNone(fund["shares_basis"])
        fund = self._yahoo(self._stmt({"2025-06-30": 81_053_634, "2026-06-30": -162_367_291}))["fundamentals"]
        self.assertIsNone(fund["shares_yoy"])
        self.assertIsNone(fund["shares_basis"])


class OfficialPreviousQuarterTests(unittest.TestCase):
    """Astra contract L18-5351-CURATED-01: the reviewed official pair supplies Yahoo's missing previous-quarter comparator
    through the actual yahoo_data, build and sealer paths (fake yfinance, no network)."""

    NOW = datetime(2026, 9, 27, 12, 0, 0, tzinfo=timezone.utc)
    FIXTURE = ROOT / "tests" / "fixtures" / "v213-official-quarterly-revenue.json"
    OFFICIAL = {"2025-06-30": 744722000.0, "2025-09-30": 1.1e9, "2025-12-31": 1.9e9, "2026-03-31": 2735412000.0,
                "2026-06-30": 4898686000.0}

    # Yahoo's own shape for 5351.TWO on 2026-09-27 (_archive yahoo-5351-shape-20260927T1530Z.txt): six columns, the
    # 2025-03-31 revenue cell empty (NaN). OFFICIAL above omits that column; YAHOO_SHAPE keeps it.
    YAHOO_SHAPE = {**OFFICIAL, "2025-03-31": None}

    def _statement(self, revenue):
        import pandas as pd  # like yfinance: metrics as the index, quarter-ends as the columns, float cells (None -> NaN)
        return pd.DataFrame({pd.Timestamp(end): {"Total Revenue": value, "Gross Profit": None if value is None else value * 0.3}
                             for end, value in sorted(revenue.items())}).astype(float)

    def _fake_yfinance(self, statements, currency="TWD"):
        import types
        import pandas as pd
        bars = daily("2024-01-02", "2026-09-25", lambda day: 10.0 + (day - date(2024, 1, 1)).days * 0.02)
        frame = pd.DataFrame({"Close": [close for _, close in bars]}, index=pd.DatetimeIndex([day for day, _ in bars]))

        class Ticker:
            def __init__(self, symbol):
                self.quarterly_income_stmt = statements.get(symbol)
                self.fast_info = {"currency": "TWD", "marketCap": 3e10}
                self.info = {"financialCurrency": currency, "shortName": symbol}

            def history(self, **kwargs):
                return frame
        module = types.ModuleType("yfinance")
        module.Ticker = Ticker
        saved = sys.modules.get("yfinance")
        sys.modules["yfinance"] = module
        self.addCleanup(lambda: sys.modules.__setitem__("yfinance", saved) if saved is not None else sys.modules.pop("yfinance", None))

    def _fund(self, revenue=None, symbol="5351.TWO", currency="TWD", config_path=None):
        self._fake_yfinance({symbol: self._statement(self.YAHOO_SHAPE if revenue is None else revenue)}, currency)
        return engine.yahoo_data(symbol, as_of=self.NOW, config_path=config_path)["fundamentals"]

    def test_five_yahoo_quarters_take_the_official_previous_pair(self):
        fund = self._fund()
        self.assertEqual(fund["revenue_yoy"], 4898686000.0 / 744722000.0 - 1)   # the current YoY stays Yahoo's
        self.assertEqual(fund["revenue_yoy_prev"], 2735412 / 627130 - 1)          # both operands official
        self.assertEqual((fund["revenue_yoy_prev_basis"], fund["source"]),
                         ("OFFICIAL_CURATED", "Yahoo Finance quarterly income statement (unofficial)"))
        self.assertEqual(fund["revenue_yoy_prev_source"]["record_id"], "5351.TWO-2026Q2-prev-2026Q1")
        self.assertNotIn("revenue_yoy_prev_reason", fund)
        self.assertEqual(fund["revenue"], 4898686000.0)

    def test_an_empty_comparator_cell_is_absent_as_yahoo_reports_it(self):
        for empty in (None, float("nan")):
            fund = self._fund({**self.OFFICIAL, "2025-03-31": empty})
            self.assertEqual((fund["revenue_yoy_prev"], fund["revenue_yoy_prev_basis"]), (2735412 / 627130 - 1, "OFFICIAL_CURATED"))

    def test_a_later_empty_column_withholds_the_record(self):
        for later in ({"2026-09-30": None}, {"2026-09-30": None, "2025-03-31": None}):
            fund = self._fund({**self.OFFICIAL, **later})
            self.assertEqual((fund["quarter_end"], fund["revenue_yoy_prev"], fund["revenue_yoy_prev_basis"],
                              fund["revenue_yoy_prev_source"], fund["revenue_yoy_prev_reason"]),
                             ("2026-06-30", None, None, None, "PERIOD_MISMATCH"))
            self.assertIsNotNone(fund["revenue_yoy"])

    def test_an_available_or_zero_yahoo_comparator_is_never_replaced(self):
        own = self._fund({**self.OFFICIAL, "2025-03-31": 600000000.0})
        self.assertEqual((own["revenue_yoy_prev"], own["revenue_yoy_prev_basis"], own["revenue_yoy_prev_source"]),
                         (2735412000.0 / 600000000.0 - 1, "YAHOO", None))
        zero = self._fund({**self.OFFICIAL, "2025-03-31": 0.0})
        self.assertEqual((zero["revenue_yoy_prev"], zero["revenue_yoy_prev_basis"], zero["revenue_yoy_prev_source"]),
                         (None, "YAHOO", None))
        for invalid in (-5e8, float("inf")):   # present invalid values keep Yahoo's own (pre-existing) arithmetic
            fund = self._fund({**self.OFFICIAL, "2025-03-31": invalid})
            self.assertEqual((fund["revenue_yoy_prev_basis"], fund["revenue_yoy_prev_source"]), ("YAHOO", None), invalid)
            self.assertNotEqual(fund["revenue_yoy_prev"], 2735412 / 627130 - 1)

    def test_rejections_keep_the_yahoo_fundamentals_with_a_null_previous_yoy(self):
        bad = Path(tempfile.mkdtemp()) / "official.json"
        self.addCleanup(bad.unlink, missing_ok=True)
        bad.write_text("{ not json", encoding="utf-8")
        cases = {"NO_RECORD": dict(symbol="3008.TW"), "CURRENCY_UNVERIFIED": dict(currency="USD"),
                 "CROSS_CHECK_MISMATCH": dict(revenue={**self.OFFICIAL, "2026-03-31": 2735412000.0 + 1001}),
                 "PERIOD_MISMATCH": dict(revenue={**{k.replace("2026", "2027").replace("2025", "2026"): v
                                                     for k, v in self.OFFICIAL.items()}}),
                 "INVALID_RECORD": dict(config_path=bad)}
        for reason, arguments in cases.items():
            fund = self._fund(**arguments)
            self.assertIsNotNone(fund["revenue_yoy"], reason)
            self.assertEqual((fund["revenue_yoy_prev"], fund["revenue_yoy_prev_basis"], fund["revenue_yoy_prev_source"],
                              fund["revenue_yoy_prev_reason"]), (None, None, None, reason))

    def _build(self, currency, revenue=None):
        from unittest import mock
        layer = {"id": "memory", "name_zh": "記憶體", "chain": "chips_memory", "chain_rank": 4, "leopold_constraint": "x",
                 "filing_terms": ["HBM"], "capturers": [
                     {"symbol": symbol, "role": "memory", "source_url": "https://x.com/a/status/1", "source_date": "2026-09"}
                     for symbol in ("5351.TWO", "8299.TWO")]}
        tmp = Path(tempfile.mkdtemp())
        (tmp / "layers.json").write_text(json.dumps({"layers": [layer]}), encoding="utf-8")
        other = {**self.OFFICIAL, "2025-03-31": 7e8}   # a listing with its own six quarters
        self._fake_yfinance({"5351.TWO": self._statement(revenue or self.YAHOO_SHAPE), "8299.TWO": self._statement(other)}, currency)
        with mock.patch.multiple(engine, LAYERS=tmp / "layers.json", SERENITY=tmp / "none.json", LEOPOLD=tmp / "none.json",
                                 cik_index=lambda: {}, taiwan_monthly_revenue=lambda members: {},
                                 cision_interim_revenue=lambda members, now: {}, korea_ir_revenue=lambda *args: None,
                                 nasdaq_consensus=lambda *args: None, usd_rate=lambda currency, cache: 1 / 30), \
                mock.patch.object(engine.listing_lineage, "load", lambda: {}):
            document = engine.build(None, self.NOW, with_news=False)
        scores = {row["symbol"]: row["parts"] for row in document["all_scores"]}
        return document, scores

    def test_build_carries_the_supplement_into_capture_and_the_industry_acceleration(self):
        document, scores = self._build("TWD")
        accel = (4898686000.0 / 744722000.0 - 1) - (2735412 / 627130 - 1)
        own = 2735412000.0 / 7e8 - 1
        self.assertEqual(scores["5351.TWO"]["capture_detail"]["acceleration"], round(6 * engine.clip(accel, -0.2, 0.3), 2))
        self.assertAlmostEqual(document["industries"][0]["median_acceleration"],
                               __import__("statistics").median([accel, (4898686000.0 / 744722000.0 - 1) - own]))
        for rejected, rejected_scores in (self._build("USD"), self._build("TWD", {**self.YAHOO_SHAPE, "2026-09-30": None})):
            self.assertNotIn("acceleration", rejected_scores["5351.TWO"]["capture_detail"])
            self.assertAlmostEqual(rejected["industries"][0]["median_acceleration"], (4898686000.0 / 744722000.0 - 1) - own)

    def _seal(self, fund):
        entry = {"rank": 1, "symbol": "5351.TWO", "name": "Etron", "layer": "memory", "archetype": "EXPLOSION", "score": 70.0,
                 "role": "DRAM", "role_source": {"url": "https://x.com/a/status/1", "date": "2026-09-03"},
                 "score_parts": {"layer_heat": 5, "capture": 4, "lead": 14, "confirmation": 15, "size": 10, "penalty": 0},
                 "fundamentals": fund, "market": {"source": "Yahoo", "source_url": "https://finance.yahoo.com/quote/5351.TWO",
                                                  "asof": "2026-09-25", "ret_6m": 0.1, "ret_1y": 0.2, "cagr_2y": 0.3,
                                                  "history_start": "2023-09-25", "currency": "TWD"},
                 "market_cap_usd": 1e9, "serenity": None, "leopold": None}
        doc = {"schema": "v213-bottleneck-top20-v3", "generated_at": "2026-09-27T12:00:00Z", "leads": {},
               "top": [{**entry, "rank": index + 1, "symbol": "5351.TWO" if index == 0 else f"S{index}",
                        "fundamentals": fund if index == 0 else None} for index in range(12)],
               "industries": [{"rank": 1, "id": "memory", "name_zh": "記憶體", "chain": "chips_memory", "leopold_constraint": "x",
                               "explosiveness": 52.1, "median_revenue_yoy": 0.3, "median_acceleration": 0.1,
                               "median_return_6m": 0.5, "fund_13f_weight": 0.0, "serenity_heat": 12.0, "news": None}]}
        from unittest import mock
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.object(publisher.build_zh_names, "names_for", lambda symbols: {}), \
                mock.patch.object(publisher.company_deep_report, "load_order_scenarios", lambda *args, **kwargs: {}):
            path = Path(tmp) / "v3.json"
            path.write_text(json.dumps(doc), encoding="utf-8")
            body = publisher.lazy_bottleneck_v3_body(path, self.NOW)
        return json.loads(body[publisher.BOTTLENECK_V3_KEY])["top"][0]["fundamentals"] if body else None

    def test_the_sealer_keeps_the_rebuilt_evidence_and_is_the_worker_fixture(self):
        import os
        fund = self._fund()
        noisy = json.loads(json.dumps(fund))
        noisy["revenue_yoy_prev_source"]["documents"][0]["raw"] = "dropped"
        sealed = self._seal(noisy)
        self.assertEqual(sealed["revenue_yoy_prev_source"], fund["revenue_yoy_prev_source"])   # extras stripped
        self.assertEqual((sealed["revenue_yoy_prev_basis"], sealed["revenue_yoy_prev"]), ("OFFICIAL_CURATED", 2735412 / 627130 - 1))
        for key in ("revenue", "revenue_unit", "revenue_yoy_prev_reason"):
            self.assertNotIn(key, sealed)
        self.assertEqual(self._seal(sealed), sealed)   # resealing is idempotent
        if os.environ.get("II_WRITE_OFFICIAL_REVENUE_FIXTURE") == "1":
            self.FIXTURE.write_text(json.dumps({"generated_at": "2026-09-27T12:00:00Z", "symbol": "5351.TWO", "fundamentals": sealed},
                                               ensure_ascii=False, indent=1) + "\n", encoding="utf-8", newline="\n")
        self.assertEqual(json.loads(self.FIXTURE.read_text(encoding="utf-8"))["fundamentals"], sealed)

    def test_the_sealer_refuses_the_object_on_any_contradiction(self):
        fund = self._fund()
        mutations = [
            lambda f: f.update(revenue_yoy_prev_source=None),
            lambda f: f.update(revenue_yoy_prev_basis="YAHOO"),
            lambda f: f.update(revenue_yoy_prev_basis="OFFICIAL"),
            lambda f: f.update(revenue_yoy_prev=3.3),
            lambda f: f.update(revenue_yoy=f["revenue_yoy"] + 0.001),
            lambda f: f.update(quarter_end="2026-09-30"),
            lambda f: f["revenue_yoy_prev_source"].update(config_sha256="a" * 64),
            lambda f: f["revenue_yoy_prev_source"]["previous_pair"]["prior_year"].update(amount=627131),
            lambda f: f["revenue_yoy_prev_source"]["documents"][1].update(sha256="b" * 64),
            lambda f: f["revenue_yoy_prev_source"]["cross_check"]["previous_current"].update(yahoo_twd=1.0),
        ]
        for index, mutate in enumerate(mutations):
            with self.subTest(index=index):
                broken = json.loads(json.dumps(fund))
                mutate(broken)
                self.assertIsNone(self._seal(broken))
        legacy = {key: value for key, value in fund.items() if not key.startswith("revenue_yoy_prev_")}
        legacy["revenue_yoy_prev"] = 0.4
        sealed = self._seal(legacy)   # an older build carries neither field and keeps its legacy meaning
        self.assertEqual(sealed["revenue_yoy_prev"], 0.4)
        self.assertNotIn("revenue_yoy_prev_basis", sealed)
        yahoo = self._seal({**legacy, "revenue_yoy_prev_basis": "YAHOO", "revenue_yoy_prev_source": None})
        self.assertEqual((yahoo["revenue_yoy_prev_basis"], yahoo["revenue_yoy_prev_source"]), ("YAHOO", None))


if __name__ == "__main__":
    unittest.main()
