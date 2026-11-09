"""Free-primary event boundaries and synthetic one-cycle 13F publication; no network."""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import leopold_positions as lp
import public_event_research as events
import bottleneck_top20_v3 as ranking
import top20_rotation_provenance as rotation
from tests.test_corporate_actions_gap_a import seed as action_fixture
from tests.test_leopold_positions import INDEX, cover, folder, info_table, make_fetch
import tests.test_leopold_positions as lp_fixtures

DAY = date(2026, 11, 16)
NOW = datetime(2026, 11, 16, 12, tzinfo=timezone.utc)
Q2 = "0002045724-26-900001"
Q3 = "0002045724-26-900002"
Q2_A = "0002045724-26-900003"
Q3_A = "0002045724-26-900004"
Q3_NEW = "0002045724-26-900005"
SNDK = "80004C200"
MU = "595112103"


def fixture_refresh_scenario() -> dict:
    """Callable deterministic dry-run evidence; all accessions/amounts are SYNTHETIC.

    A newly published Q3 replaces Q2 in one build. A later-filed Q2 restatement
    changes only the comparison quarter. Q3 restatement removes its old rows;
    NEW HOLDINGS adds all entries, including same-CUSIP lots, without erasing any.
    """
    q2_rows = [("SANDISK CORP", SNDK, 1000000, 100, "SH", None)]
    q3_rows = [("SANDISK CORP", SNDK, 3000000, 300, "SH", None),
               ("MICRON TECHNOLOGY INC", MU, 1000000, 50, "SH", None)]
    q2_restated = [("SANDISK CORP", SNDK, 1500000, 150, "SH", None)]
    q3_restated = [("MICRON TECHNOLOGY INC", MU, 1200000, 60, "SH", None)]
    additions = [("MICRON TECHNOLOGY INC", MU, 200000, 10, "SH", None),
                 ("MICRON TECHNOLOGY INC", MU, 300000, 15, "SH", None)]
    filings = [("13F-HR", Q2, "2026-08-14", "2026-06-30"),
               ("13F-HR", Q3, "2026-11-12", "2026-09-30"),
               ("13F-HR/A", Q2_A, "2026-11-14", "2026-06-30"),
               ("13F-HR/A", Q3_A, "2026-11-15", "2026-09-30"),
               ("13F-HR/A", Q3_NEW, "2026-11-16", "2026-09-30")]
    tables = {Q2: info_table(q2_rows), Q3: info_table(q3_rows), Q2_A: info_table(q2_restated),
              Q3_A: info_table(q3_restated), Q3_NEW: info_table(additions)}
    primary = {Q2: cover(1, 1000000), Q3: cover(2, 4000000),
               Q2_A: cover(1, 1500000, amendment="RESTATEMENT"),
               Q3_A: cover(1, 1200000, amendment="RESTATEMENT"),
               Q3_NEW: cover(2, 500000, amendment="NEW HOLDINGS")}
    states = []
    for count in range(1, 6):
        doc = lp.build(make_fetch(filings[:count], tables, primary=primary), INDEX, NOW,
                       cusip_map={}, regime_events=[])
        states.append({"period": doc["filing"]["period"], "filed": doc["filing"]["filed"],
                       "prior_period": (doc["prior_filing"] or {}).get("period"),
                       "refresh_status": doc["refresh_status"],
                       "filing_url": doc["filing"]["url"],
                       "positions": {row["ticker"]: {"shares": row["long_shares"],
                                                       "prior_shares": row["prior_shares"],
                                                       "shares_change": row["shares_change"]}
                                     for row in doc["positions"]},
                       "amendments": doc["amendments"]})
    return {"kind": "SYNTHETIC_NO_LIVE_FETCH", "before_q3": states[0], "after_one_cycle": states[1],
            "late_prior_amendment": states[2], "q3_restatement": states[3], "q3_additions": states[4]}


def body_reviewed(symbol="EXTRA", cik=12345, role=None):
    row = {"symbol": symbol, "market": "US", "published_on": "2026-11-09",
           "source_url": f"https://www.sec.gov/Archives/edgar/data/{cik}/000001234526000001/notice.htm",
           "reviewed": True, "rights": "PUBLIC_RESEARCH_ONLY", "headline_zh": "測試用已核公告"}
    clause = "Synthetic fixture only: issuer has a signed optical components supply agreement."
    reviewed = events.bind_primary_body_review(row, ("<html>" + clause + "</html>").encode(),
                                               excerpt=clause, reviewed_on=DAY)
    if role:
        reviewed.update(role=role, issuer_cik=cik)
    return reviewed


class PublicEventBoundaryTests(unittest.TestCase):
    def test_metadata_boolean_is_not_a_reviewed_body_claim(self):
        row = body_reviewed()
        self.assertEqual(events.curated_company_event(row, cutoff=DAY)["status"], "PRIMARY_REVIEWED")
        unbound = {key: value for key, value in row.items() if key != "primary_body"}
        self.assertIsNone(events.curated_company_event(unbound, cutoff=DAY))
        self.assertIsNone(events.latest_event([unbound], symbol="EXTRA", cutoff=DAY))
        with self.assertRaisesRegex(ValueError, "PRIMARY_BODY_CLAUSE_MISSING"):
            events.bind_primary_body_review(unbound, b"<html>metadata only</html>",
                                             excerpt="A supposed deal that is not in this body.", reviewed_on=DAY)

    def test_four_key_projection_survives_feed_revalidation(self):
        row = body_reviewed()
        feed = events.build([row], cutoff=DAY)
        projected = events.latest_event(feed["events"], symbol="EXTRA", cutoff=DAY, reviewed_events=[row])
        self.assertEqual(set(projected), {"published_on", "source_url", "headline_zh", "status"})
        self.assertEqual(events.validate_latest_event(projected, cutoff=DAY, symbol="EXTRA",
                                                      reviewed_events=[row]), projected)
        self.assertIsNone(events.validate_latest_event({**projected, "headline_zh": "未核實改寫"},
                                                       cutoff=DAY, reviewed_events=[row]))
        self.assertIsNone(events.validate_latest_event(projected, cutoff=date(2026, 11, 8), reviewed_events=[row]))
        self.assertIsNone(events.validate_latest_event(projected, cutoff=DAY, symbol="OTHER", reviewed_events=[row]))

    def test_unregistered_later_claim_cannot_displace_the_registered_event(self):
        registered = body_reviewed()
        forged = {**registered, "published_on": "2026-11-15", "headline_zh": "快取捏造的新事件"}
        expected = events.curated_company_event(registered, cutoff=DAY)
        self.assertEqual(events.latest_event([registered, forged], symbol="EXTRA", cutoff=DAY,
                                            reviewed_events=[registered]), expected)
        self.assertIsNone(events.latest_event([forged], symbol="EXTRA", cutoff=DAY,
                                              reviewed_events=[registered]))
        self.assertIsNone(events.latest_event([registered], symbol="EXTRA", cutoff=DAY,
                                              reviewed_events=[]))

    def test_official_tw_kr_metadata_placeholders_only(self):
        for market, url in (("TW", events.TW_NOTICE_URLS[0]), ("KR", "https://dart.fss.or.kr/api/link.jsp?rcpNo=20261116000001")):
            row = {"published_on": "2026-11-09", "source_url": url,
                   "headline_zh": events.METADATA_LABELS[market], "status": "PRIMARY_METADATA_ONLY"}
            self.assertEqual(events.validate_latest_event(row, cutoff=DAY), row)
            self.assertIsNone(events.validate_latest_event({**row, "headline_zh": "已簽訂單"}, cutoff=DAY))
            self.assertIsNone(events.validate_latest_event({**row, "source_url": "https://evil.invalid/notice"}, cutoff=DAY))

    def test_positive_admission_needs_independent_body_reviews_not_metadata(self):
        issuer = body_reviewed(role="ISSUER")
        counterparty = body_reviewed(symbol="BUYER", cik=23456, role="COUNTERPARTY")
        row = {"symbol": "EXTRA", "market": "US", "layer_id": "optics", "role": "Optical components",
               "role_zh": "光學零件", "source_date": "2026-11-09", "reviewed": True,
               "admission": "REVIEWED_PRIMARY", "evidence": [issuer, counterparty]}
        accepted = events.admitted_candidate_rows([row], cutoff=DAY, layer_ids={"optics"})
        self.assertEqual([item["symbol"] for item in accepted], ["EXTRA"])
        self.assertEqual(events.admitted_candidate_rows(accepted, cutoff=DAY, layer_ids={"optics"}), accepted)
        for pieces in ([{key: value for key, value in issuer.items() if key != "primary_body"}, counterparty],
                       [issuer, issuer], [{**issuer, "symbol": "IMPOSTOR"}, counterparty],
                       [{**issuer, "issuer_cik": 99999}, counterparty]):
            self.assertEqual(events.admitted_candidate_rows([{**row, "evidence": pieces}],
                                                           cutoff=DAY, layer_ids={"optics"}), [])
        self.assertEqual(events.admitted_candidate_rows([row], cutoff=DAY, layer_ids={"other"}), [])

    def test_real_source_adapters_discover_beyond_fixed_universe_without_admission(self):
        index = ("CIK|Company Name|Form Type|Date Filed|Filename\n"
                 "12345|Synthetic issuer|8-K|2026-11-16|edgar/data/12345/0000012345-26-000001.txt\n"
                 "23456|Unknown issuer|425|2026-11-16|edgar/data/23456/0000023456-26-000001.txt\n").encode()
        tw = json.dumps([{"公司代號": "6633", "發言日期": "1151116", "主旨 ": "測試公告"}]).encode()
        otc = json.dumps([{"SecuritiesCompanyCode": "3631", "發言日期": "1151116"}]).encode()
        rss = b'<rss><channel><item><link>https://dart.fss.or.kr/api/link.jsp?rcpNo=20261116000001</link><pubDate>Mon, 16 Nov 2026 02:00:00 GMT</pubDate></item></channel></rss>'
        def fetch(url):
            if url == events.TW_NOTICE_URLS[0]:
                return tw
            if url == events.TW_NOTICE_URLS[1]:
                return otc
            if url == events.DART_RSS_URL:
                return rss
            return index
        result = events.refresh_public_discovery(cutoff=DAY, cik_map={"EXTRA": 12345}, fetch=fetch, lookback_days=1)
        self.assertEqual({row["symbol"] for row in result["discovered_candidates"]}, {"EXTRA", "6633.TW", "3631.TWO"})
        self.assertEqual(result["unresolved_notices"][0]["status"], "ISSUER_IDENTITY_UNVERIFIED")
        self.assertNotIn("symbol", result["unresolved_notices"][0])
        self.assertEqual(result["refresh_status"], "PARTIAL")
        self.assertEqual(result["freshness_status"], "NOT_FULLY_VERIFIED")
        feed = events.build(result["events"], cutoff=DAY, universe=result["discovered_candidates"])
        self.assertEqual(feed["admitted_candidates"], [])
        self.assertEqual(feed["score_authority"], "NONE")
        self.assertTrue(all(row["status"] == "PRIMARY_METADATA_ONLY" for row in feed["events"]))

    def test_malformed_sec_index_rows_cannot_claim_successful_zero_event_coverage(self):
        header = "CIK|Company Name|Form Type|Date Filed|Filename\n"
        for row in (
            "12345|Fixture|8-K|2026-99-16|edgar/data/12345/0000012345-26-000001.txt",
            "12345|Fixture|8-K|2026-11-16|edgar/data/23456/0000012345-26-000001.txt",
            "12345|Fixture|8-K|2026-11-16",
        ):
            with self.subTest(row=row):
                raw = (header + row).encode()
                with self.assertRaisesRegex(ValueError, "SEC_DAILY_INDEX_ROW_INVALID"):
                    events.sec_daily_index_events(raw, cik_map={"EXTRA": 12345}, cutoff=DAY)
                def fetch(url):
                    if "daily-index" in url:
                        return raw
                    raise OSError("fixture unavailable")
                result = events.refresh_public_discovery(cutoff=DAY, cik_map={"EXTRA": 12345},
                                                          fetch=fetch, lookback_days=1)
                sec = next(status for status in result["source_status"] if "daily-index" in status["source"])
                self.assertEqual(sec["status"], "INVALID_SOURCE")
                self.assertTrue(sec["reason_zh"])
                self.assertEqual(result["freshness_status"], "NOT_FULLY_VERIFIED")

    def test_unavailable_sources_have_explicit_zh_fail_closed_statuses(self):
        def unavailable(url):
            raise OSError("fixture source unavailable")
        result = events.refresh_public_discovery(cutoff=DAY, cik_map={}, fetch=unavailable, lookback_days=1)
        self.assertEqual(result["events"], [])
        self.assertTrue(all(row["status"] == "UNAVAILABLE" and row["reason_zh"] for row in result["source_status"]))
        self.assertEqual(result["refresh_status"], "PARTIAL")
        self.assertEqual(result["freshness_status"], "NOT_FULLY_VERIFIED")


class OrdinaryAdmissionAndClockTests(unittest.TestCase):
    def run_ranking(self, registrations, *, at=NOW):
        layer = {"id": "optics", "name_zh": "光學", "chain": "network_optics", "chain_rank": 5,
                 "leopold_constraint": "fixture", "filing_terms": [], "capturers": [
                     {"symbol": "BASE", "role": "Optical components", "source_url": "https://www.sec.gov/test",
                      "source_date": "2026-11-02"}]}
        issuer = body_reviewed(role="ISSUER")
        counterparty = body_reviewed(symbol="BUYER", cik=23456, role="COUNTERPARTY")
        admitted = {"symbol": "EXTRA", "market": "US", "layer_id": "optics", "role": "Optical components",
                    "role_zh": "光學零件", "source_date": "2026-11-09", "reviewed": True,
                    "admission": "REVIEWED_PRIMARY", "evidence": [issuer, counterparty]}
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "config").mkdir()
            (root / "data/cache").mkdir(parents=True)
            (root / "config/layers.json").write_text(json.dumps({"layers": [layer]}), encoding="utf-8")
            (root / "config/reviewed-open-candidates-v1.json").write_text(
                json.dumps([admitted] if registrations else []), encoding="utf-8")
            (root / "config/public-reviewed-events-v1.json").write_text("[]", encoding="utf-8")
            feed = events.build([], cutoff=DAY)
            feed["admitted_candidates"] = [admitted]  # cache alone must never authorize this row
            (root / "data/cache/public_event_research_latest.json").write_text(json.dumps(feed), encoding="utf-8")
            actions = action_fixture()
            actions["entries"][0]["review_by"] = DAY.isoformat()
            action_path = root / "config/actions.json"
            action_path.write_text(json.dumps(actions), encoding="utf-8")
            regimes = [{**regime, "review_by": DAY.isoformat()} for regime in lp.load_regime_events()]
            with patch.object(lp_fixtures, "NOW", at):
                holdings = lp_fixtures.base_build(regime_events=regimes)
            holdings_path = root / "data/cache/holdings.json"
            holdings_path.write_text(json.dumps(holdings), encoding="utf-8")
            def market(symbol, *args, **kwargs):
                first_bar = ranking.listing_lineage.request_start(DAY) + timedelta(days=8)
                bars = [(first_bar, 100.0), (DAY - timedelta(days=730), 120.0),
                        (DAY - timedelta(days=365), 140.0), (DAY - timedelta(days=182), 160.0), (DAY, 200.0)]
                returns = ranking.listing_lineage.long_term_returns(
                    bars, None, ranking.listing_lineage.request_start(at.date()))
                return {"name": symbol, "fundamentals": None,
                        "market": {**returns, "market_cap": 2e10, "currency": "USD",
                                   "source": "Yahoo Finance adjusted daily close (unofficial)",
                                   "source_url": "https://finance.yahoo.com/quote/" + symbol}}
            with patch.multiple(ranking, ROOT=root, LAYERS=root / "config/layers.json",
                    SERENITY=root / "missing-serenity.json", LEOPOLD=holdings_path,
                    cik_index=lambda captured=None: {"BASE": 1, "EXTRA": 12345},
                    yahoo_data=market, taiwan_monthly_revenue=lambda *a, **k: {},
                    cision_interim_revenue=lambda *a, **k: {}, nasdaq_consensus=lambda *a, **k: None), \
                    patch.object(ranking.corporate_actions, "DEFAULT_CONFIG", action_path), \
                    patch("urllib.request.urlopen", side_effect=AssertionError("network forbidden")):
                return ranking.build(None, at, with_news=False), holdings

    def test_runtime_feed_cannot_admit_or_retain_a_revoked_candidate(self):
        blocked, _ = self.run_ranking(False)
        admitted, _ = self.run_ranking(True)
        revoked, _ = self.run_ranking(False)
        self.assertEqual([row["symbol"] for row in blocked["top"]], ["BASE"])
        self.assertEqual({row["symbol"] for row in admitted["top"]}, {"BASE", "EXTRA"})
        self.assertEqual([row["symbol"] for row in revoked["top"]], ["BASE"])
        self.assertEqual([row["symbol"] for row in revoked["candidate_fingerprints"]], ["BASE"])

    def test_same_source_observations_across_midnight_do_not_claim_changed_inputs(self):
        first, first_holdings = self.run_ranking(False)
        second, second_holdings = self.run_ranking(False, at=NOW + timedelta(days=1))
        self.assertFalse(first_holdings["regime_review_overdue"])
        self.assertTrue(second_holdings["regime_review_overdue"])
        self.assertTrue(first["top"][0]["market"]["history_truncated"])
        self.assertFalse(second["top"][0]["market"]["history_truncated"])
        previous = rotation.build_record(first, None, asof=NOW.isoformat())
        current = rotation.build_record(second, previous, asof=(NOW + timedelta(days=1)).isoformat())
        self.assertEqual(current["input_sha256"], previous["input_sha256"])
        self.assertEqual(current["diff"]["changed_input_families"], [])
        self.assertEqual(current["diff"]["reason_code"], "NO_CHANGE")
        self.assertEqual(current["diff"]["changed_screener_symbols"], [])


class FilingPublicationTests(unittest.TestCase):
    def test_q3_replaces_q2_in_one_cycle_and_amendments_stay_in_period(self):
        scenario = fixture_refresh_scenario()
        self.assertEqual(scenario["before_q3"]["period"], "2026-06-30")
        current = scenario["after_one_cycle"]
        self.assertEqual((current["period"], current["filed"], current["prior_period"]),
                         ("2026-09-30", "2026-11-12", "2026-06-30"))
        self.assertEqual(current["positions"]["SNDK"]["shares_change"], 200)
        late_prior = scenario["late_prior_amendment"]
        self.assertEqual((late_prior["period"], late_prior["filed"]), ("2026-09-30", "2026-11-12"))
        self.assertEqual(late_prior["positions"]["SNDK"], {"shares": 300, "prior_shares": 150, "shares_change": 150})
        restated = scenario["q3_restatement"]
        self.assertEqual(set(restated["positions"]), {"MU"})
        self.assertEqual(restated["positions"]["MU"]["shares"], 60)
        additions = scenario["q3_additions"]
        self.assertEqual(set(additions["positions"]), {"MU"})
        self.assertEqual(additions["positions"]["MU"]["shares"], 85)
        self.assertTrue(additions["filing_url"].startswith(folder(Q3_NEW)))
        self.assertTrue(all(scenario[key]["refresh_status"] == "COMPLETE" for key in scenario if key != "kind"))
        self.assertEqual({row["period"] for row in additions["amendments"]}, {"2026-06-30", "2026-09-30"})

    def test_same_day_amendments_use_acceptance_times_not_accession_order(self):
        base = [("SANDISK CORP", SNDK, 1000000, 100, "SH", None)]
        restated = [("MICRON TECHNOLOGY INC", MU, 600000, 60, "SH", None)]
        added = [("MICRON TECHNOLOGY INC", MU, 100000, 10, "SH", None)]
        fetch = make_fetch([], {Q3: info_table(base), Q3_A: info_table(restated), Q3_NEW: info_table(added)},
                           primary={Q3: cover(1, 1000000), Q3_A: cover(1, 600000, amendment="RESTATEMENT"),
                                    Q3_NEW: cover(1, 100000, amendment="NEW HOLDINGS")})
        members = [(Q3, "2026-11-12", "2026-09-30", "13F-HR"),
                   (Q3_A, "2026-11-16", "2026-09-30", "13F-HR/A"),
                   (Q3_NEW, "2026-11-16", "2026-09-30", "13F-HR/A")]
        with self.assertRaisesRegex(ValueError, "LEOPOLD_AMENDMENT_ORDER_UNKNOWN"):
            lp.period_table(fetch, members)
        times = {Q3_A: "2026-11-16T12:00:00Z", Q3_NEW: "2026-11-16T11:00:00Z"}
        _, rows, _, newest = lp.period_table(fetch, members, acceptance_times=times)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["shares"], 60)
        self.assertEqual(newest[0], Q3_A)

    def test_mixed_period_unknown_amendment_and_missing_base_fail_closed(self):
        rows = [("SANDISK CORP", SNDK, 1000000, 100, "SH", None)]
        fetch = make_fetch([], {Q3_A: info_table(rows)}, primary={Q3_A: cover(1, 1000000)})
        with self.assertRaisesRegex(ValueError, "LEOPOLD_MIXED_OR_EMPTY_PERIOD"):
            lp.period_table(fetch, [(Q2, "2026-08-14", "2026-06-30", "13F-HR"),
                                    (Q3, "2026-11-12", "2026-09-30", "13F-HR")])
        member = [(Q3_A, "2026-11-15", "2026-09-30", "13F-HR/A")]
        with self.assertRaisesRegex(ValueError, "LEOPOLD_AMENDMENT_TYPE_UNKNOWN"):
            lp.period_table(fetch, member)
        fetch = make_fetch([], {Q3_A: info_table(rows)}, primary={Q3_A: cover(1, 1000000, amendment="NEW HOLDINGS")})
        with self.assertRaisesRegex(ValueError, "LEOPOLD_AMENDMENT_BASE_MISSING"):
            lp.period_table(fetch, member)

    def test_cover_period_and_future_publication_are_not_mixed(self):
        rows = [("SANDISK CORP", SNDK, 1000000, 100, "SH", None)]
        filings = [("13F-HR", Q2, "2026-08-14", "2026-06-30"), ("13F-HR", Q3, "2026-11-12", "2026-09-30")]
        wrong = cover(1, 1000000).replace(b"<coverPage>", b"<coverPage><reportCalendarOrQuarter>06-30-2026</reportCalendarOrQuarter>")
        fetch = make_fetch(filings, {Q2: info_table(rows), Q3: info_table(rows)}, primary={Q3: wrong})
        with self.assertRaisesRegex(ValueError, "LEOPOLD_COVER_PERIOD_MISMATCH"):
            lp.build(fetch, INDEX, NOW, cusip_map={}, regime_events=[])
        before = lp.build(fetch, INDEX, datetime(2026, 11, 11, tzinfo=timezone.utc), cusip_map={}, regime_events=[])
        self.assertEqual(before["filing"]["period"], "2026-06-30")

    def test_missing_ownership_document_is_partial_not_fresh(self):
        rows = [("SANDISK CORP", SNDK, 1000000, 100, "SH", None)]
        form4 = "0002045724-26-900009"
        filings = [("13F-HR", Q3, "2026-11-12", "2026-09-30"), ("4", form4, "2026-11-13", "")]
        fetch = make_fetch(filings, {Q3: info_table(rows)}, primary={Q3: cover(1, 1000000)}, documents={form4: "missing.xml"})
        doc = lp.build(fetch, INDEX, NOW, cusip_map={}, regime_events=[])
        self.assertEqual(doc["refresh_status"], "PARTIAL")
        self.assertEqual(doc["freshness_status"], "NOT_FULLY_VERIFIED")
        self.assertTrue(any(row["status"] == "DOCUMENT_UNAVAILABLE" for row in doc["source_issues"]))

    def test_other_reporting_person_is_never_substituted_for_fund(self):
        raw = b'<edgarSubmission><issuerName>Fixture</issuerName><issuerCusipNumber>80004C200</issuerCusipNumber><reportingPersonInfo><reportingPersonCIK>12345</reportingPersonCIK><aggregateAmountOwned>999999</aggregateAmountOwned></reportingPersonInfo></edgarSubmission>'
        parsed = lp.parse_event_document(raw)
        self.assertIsNone(parsed["shares"])
        self.assertFalse(parsed["reporting_owner_verified"])

    def test_old_event_filed_late_does_not_overwrite_newer_quarter_holdings(self):
        rows = [("SANDISK CORP", SNDK, 1000000, 100, "SH", None)]
        accession = "0002045724-26-900006"
        filings = [("13F-HR", Q3, "2026-11-12", "2026-09-30"),
                   ("SCHEDULE 13D/A", accession, "2026-11-13", "2026-07-01")]
        body = (b"<edgarSubmission><issuerCusipNumber>80004C200</issuerCusipNumber>"
                b"<dateOfEvent>07/01/2026</dateOfEvent><reportingPersonInfo>"
                b"<reportingPersonCIK>0002045724</reportingPersonCIK>"
                b"<aggregateAmountOwned>1</aggregateAmountOwned></reportingPersonInfo></edgarSubmission>")
        fetch = make_fetch(filings, {Q3: info_table(rows)},
                           extras={folder(accession) + "primary_doc.xml": body},
                           primary={Q3: cover(1, 1000000)})
        doc = lp.build(fetch, INDEX, NOW, cusip_map={}, regime_events=[])
        self.assertEqual(doc["events"][0]["shares"], 1)
        self.assertIsNone(doc["positions"][0]["post_period_event"])
        self.assertEqual(doc["positions"][0]["currency_factor"], 1.0)

    def test_historical_submissions_supply_base_without_cross_period_merge(self):
        rows = [("SANDISK CORP", SNDK, 1000000, 100, "SH", None)]
        member = [("13F-HR/A", Q3_NEW, "2026-11-16", "2026-09-30")]
        tables = {Q2: info_table(rows), Q3: info_table(rows), Q3_NEW: info_table(rows)}
        primary = {Q2: cover(1, 1000000), Q3: cover(1, 1000000),
                   Q3_NEW: cover(1, 1000000, amendment="NEW HOLDINGS")}
        base_fetch = make_fetch(member, tables, primary=primary)
        name = "CIK0002045724-submissions-001.json"
        submissions = json.loads(base_fetch(lp.SUBMISSIONS))
        submissions["filings"]["files"] = [{"name": name}]
        archive = {"form": ["13F-HR", "13F-HR"], "accessionNumber": [Q3, Q2],
                   "filingDate": ["2026-11-12", "2026-08-14"], "reportDate": ["2026-09-30", "2026-06-30"]}
        def fetch(url):
            if url == lp.SUBMISSIONS:
                return json.dumps(submissions).encode()
            if url == "https://data.sec.gov/submissions/" + name:
                return json.dumps(archive).encode()
            return base_fetch(url)
        doc = lp.build(fetch, INDEX, NOW, cusip_map={}, regime_events=[])
        self.assertEqual(doc["filing"]["period"], "2026-09-30")
        self.assertEqual(doc["positions"][0]["long_shares"], 200)
        self.assertEqual(doc["positions"][0]["prior_shares"], 100)
        self.assertEqual(doc["refresh_status"], "COMPLETE")

    def test_stale_quarter_represents_existing_discount_without_reweighting(self):
        self.assertEqual(lp.stale_quarter("2026-03-31", NOW)["factor"], 0.0)
        recent = lp.stale_quarter("2026-09-30", NOW)
        self.assertEqual(recent["factor"], 1.0)
        self.assertEqual(recent["applied_by"], "RANKING_AGE_GATE")

    def test_cli_polls_new_publication_even_inside_old_cache_age_window(self):
        rows = [("SANDISK CORP", SNDK, 1000000, 100, "SH", None)]
        filings = [("13F-HR", Q2, "2026-08-14", "2026-06-30"), ("13F-HR", Q3, "2026-11-01", "2026-09-30")]
        fetch = make_fetch(filings, {Q2: info_table(rows), Q3: info_table(rows)},
                           primary={Q2: cover(1, 1000000), Q3: cover(1, 1000000)})
        class Clock(datetime):
            @classmethod
            def now(cls, tz=None):
                return NOW
        with tempfile.TemporaryDirectory(dir=ROOT) as tmp:
            output = Path(tmp) / "positions.json"
            output.write_text(json.dumps({"generated_at": NOW.strftime("%Y-%m-%dT%H:%M:%SZ"),
                                          "filing": {"period": "2026-06-30"}, "refresh_status": "COMPLETE",
                                          "submissions_sha256": "0" * 64}), encoding="utf-8")
            with patch.object(lp, "datetime", Clock), patch.object(lp, "sec_fetcher", return_value=fetch), patch.object(lp, "ticker_index", return_value=INDEX), patch("builtins.print"):
                self.assertEqual(lp.main(["--output", str(output), "--if-older-than-hours", "24"]), 0)
            doc = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(doc["filing"]["period"], "2026-09-30")


if __name__ == "__main__":
    unittest.main()
