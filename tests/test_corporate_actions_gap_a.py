"""Offline pending-deal registry, target admission and independent acquirer scoring."""
from __future__ import annotations

import copy
import json
import sys
import tempfile
import unittest
from datetime import date, datetime, timezone
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
FIXTURE = ROOT / "tests" / "fixtures" / "gap-a-sec-submission-response.json"

def seed():
    return {
        "schema_version": 1,
        "entries": [{
            "target_market": "US", "target_symbol": "LITE",
            "acquirer_market": "US", "acquirer_symbol": "MRVL",
            "kind": "ALL_STOCK", "exchange_ratio": 4.5, "cash_per_share": None,
            "currency": None, "announced_on": "2026-11-02",
            "expected_close": "first half of calendar year 2028",
            "status": "PENDING", "status_on": "2026-11-02",
            "source_url": "https://www.sec.gov/Archives/edgar/data/0001633978/000119312526442758/d163169dex991.htm",
            "source_date": "2026-11-02", "review_by": "2026-11-14"
        }]
    }

class CorporateActionLoaderTests(unittest.TestCase):
    def test_loader_validates_exact_schema_and_overdue_is_visible(self):
        import corporate_actions as m
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "action.json"
            p.write_text(json.dumps(seed()), encoding="utf-8")
            current = m.load_actions(p, today=date(2026, 11, 7))
            self.assertEqual(m.pending_targets(current)["LITE"]["acquirer_symbol"], "MRVL")
            self.assertNotIn("REVIEW_OVERDUE", current["entries"][0]["flags"])
            overdue = m.load_actions(p, today=date(2026, 11, 15))
            self.assertIn("REVIEW_OVERDUE", overdue["entries"][0]["flags"])

    def test_loader_rejects_malformed_and_duplicate_pending_entries(self):
        import corporate_actions as m
        for label, mutation in (
            ("enum", lambda d: d["entries"][0].update(kind="EXCHANGE")),
            ("date", lambda d: d["entries"][0].update(status_on="2026-13-01")),
            ("chronology", lambda d: d["entries"][0].update(status_on="2026-11-01")),
            ("ratio", lambda d: d["entries"][0].update(exchange_ratio=0)),
            ("duplicate", lambda d: d["entries"].append(copy.deepcopy(d["entries"][0]))),
            ("url", lambda d: d["entries"][0].update(source_url="https://untrusted.invalid/a")),
            ("URL shape only", lambda d: d["entries"][0].update(source_url="https://www.sec.gov/Archives/not-a-filing")),
            ("bad port", lambda d: d["entries"][0].update(source_url="https://www.sec.gov:bad/Archives/edgar/data/1/000119312526442758/a.htm")),
            ("reversed status and source", lambda d: d["entries"][0].update(status_on="2026-11-04", source_date="2026-11-03")),
            ("field", lambda d: d["entries"][0].update(unreviewed=True)),
        ):
            with self.subTest(label=label), tempfile.TemporaryDirectory() as tmp:
                obj = seed()
                mutation(obj)
                p = Path(tmp) / "bad.json"
                p.write_text(json.dumps(obj), encoding="utf-8")
                with self.assertRaises((ValueError, OSError)):
                    m.load_actions(p, today=date(2026, 11, 7))

    def test_discover_uses_sec_recent_forms_and_reports_unregistered(self):
        import corporate_actions as m
        fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
        with tempfile.TemporaryDirectory() as d:
            layers = Path(d) / "layers.json"
            layers.write_text(json.dumps({"layers": [{"capturers": [
                {"symbol": "LITE"}, {"symbol": "TEST"}, {"symbol": "6501.T"}]}]}), encoding="utf-8")
            actions = Path(d) / "actions.json"
            actions.write_text(json.dumps(seed()), encoding="utf-8")
            fetched = []
            def fetch(url):
                fetched.append(url)
                return json.dumps(fixture).encode("utf-8")
            result = m.discover_filings(
                today=date(2026, 11, 7), fetch=fetch, cik_by={"LITE": 1633978, "TEST": 123456},
                layers_path=layers, config_path=actions)
            self.assertEqual([item["symbol"] for item in result["unregistered"]], ["TEST"])
            self.assertEqual([x["form"] for x in result["filings"]], ["425", "425"])
            self.assertEqual(len(fetched), 2)
            self.assertTrue(all(u.startswith("https://data.sec.gov/submissions/CIK") for u in fetched))
            obj = seed()
            obj["entries"].append({**copy.deepcopy(obj["entries"][0]), "target_symbol": "TEST"})
            actions.write_text(json.dumps(obj), encoding="utf-8")
            clean = m.discover_filings(today=date(2026, 11, 7), fetch=fetch,
                  cik_by={"LITE": 1633978, "TEST": 123456}, layers_path=layers, config_path=actions)
            self.assertEqual(clean["unregistered"], [])

    def test_discover_command_refuses_unregistered_425_and_accepts_registered(self):
        import contextlib
        import io
        import corporate_actions as m
        with tempfile.TemporaryDirectory() as d:
            base = Path(d)
            layers = base / "layers.json"
            layers.write_text(json.dumps({"layers": [{"capturers": [
                {"symbol": "LITE"}, {"symbol": "TEST"}, {"symbol": "6501.T"}]}]}), encoding="utf-8")
            tickers = base / "tickers.json"
            tickers.write_text(json.dumps({"fields": ["cik", "ticker"], "data": [
                [1633978, "LITE"], [123456, "TEST"]]}), encoding="utf-8")
            for cik in (1633978, 123456):
                (base / f"CIK{cik:010d}.json").write_bytes(FIXTURE.read_bytes())
            config = base / "registry.json"
            doc = seed()
            for approved, expected in ((False, 2), (True, 0)):
                if approved:
                    doc["entries"].append({**copy.deepcopy(doc["entries"][0]), "target_symbol": "TEST"})
                config.write_text(json.dumps(doc), encoding="utf-8")
                with contextlib.redirect_stdout(io.StringIO()) as stdout:
                    code = m.main(["discover", "--as-of", "2026-11-07",
                        "--config", str(config), "--layers", str(layers),
                        "--tickers", str(tickers), "--fixture-dir", str(base)])
                self.assertEqual(code, expected)
                payload = json.loads(stdout.getvalue())
                self.assertEqual(len(payload["unregistered"]), 0 if approved else 1)

    def test_missing_config_fails_build_closed_and_closed_or_terminated_do_not_suppress(self):
        import corporate_actions as m
        import bottleneck_top20_v3 as engine
        with patch.object(engine.corporate_actions, "load_actions", side_effect=FileNotFoundError("missing")):
            with self.assertRaises(FileNotFoundError):
                engine.build(None, datetime(2026, 11, 7, tzinfo=timezone.utc), with_news=False)
        for status in ("CLOSED", "TERMINATED"):
            with self.subTest(status=status), tempfile.TemporaryDirectory() as d:
                obj = seed()
                obj["entries"][0].update(status=status, status_on="2026-11-03", source_date="2026-11-03")
                p = Path(d) / "status.json"
                p.write_text(json.dumps(obj), encoding="utf-8")
                loaded = m.load_actions(p, today=date(2026, 11, 7))
                self.assertEqual(m.pending_targets(loaded), {})
                self.assertEqual(m.public_notes(loaded, asof=date(2026, 11, 7)), {})

    def test_null_review_date_is_explicit_and_never_backfilled(self):
        import corporate_actions as m
        with tempfile.TemporaryDirectory() as d:
            obj = seed()
            obj["entries"][0]["review_by"] = None
            p = Path(d) / "missing-review.json"
            p.write_text(json.dumps(obj), encoding="utf-8")
            entry = m.load_actions(p, today=date(2026, 11, 7))["entries"][0]
            self.assertIsNone(entry["review_by"])
            self.assertIn("REVIEW_DATE_UNSET", entry["flags"])

    def test_generic_registered_pending_target_is_not_lite_specific(self):
        import corporate_actions as m
        doc = seed()
        doc["entries"][0].update(target_symbol="TEST", acquirer_symbol="OTHER")
        loaded = m.load_actions_bytes(json.dumps(doc).encode(), today=date(2026, 11, 7))
        self.assertEqual(set(m.pending_targets(loaded)), {"TEST"})
        self.assertEqual(set(m.public_notes(loaded, asof=date(2026, 11, 7))), {"TEST", "OTHER"})
        self.assertEqual(m.pending_targets(loaded)["TEST"]["status"], "PENDING")

    def test_public_notes_fail_closed_for_overlapping_active_actions_in_either_order(self):
        import corporate_actions as m
        from tests.test_corporate_distributions_gap_c import distribution
        first = {**seed()["entries"][0], "target_symbol": "TEST", "acquirer_symbol": "OTHER"}
        dist = {**distribution(), "target_symbol": "TEST", "related_symbol": "CHILD"}
        conflicts = (
            [first, {**first, "target_symbol": "SECOND"}],
            [first, {**first, "target_symbol": "OTHER", "acquirer_symbol": "THIRD"}],
            [first, dist],
            [dist, {**dist, "distribution_date": "2026-09-01", "source_date": "2026-09-01"}],
        )
        for entries in conflicts:
            for ordered in (entries, list(reversed(entries))):
                with self.subTest(kinds=[entry["kind"] for entry in ordered]):
                    doc = m.load_actions_bytes(json.dumps({"schema_version": 1, "entries": ordered}).encode(),
                                               today=date(2026, 11, 8))
                    with self.assertRaisesRegex(ValueError, "^CORPORATE_ACTION_NOTE_CONFLICT$"):
                        m.public_notes(doc, asof=date(2026, 11, 8))

    def test_future_merger_does_not_conflict_with_a_distribution_at_an_earlier_cutoff(self):
        import corporate_actions as m
        from tests.test_corporate_distributions_gap_c import distribution
        entries = [{**seed()["entries"][0], "target_symbol": "TEST", "acquirer_symbol": "OTHER"},
                   {**distribution(), "target_symbol": "TEST", "related_symbol": "CHILD"}]
        doc = m.load_actions_bytes(json.dumps({"schema_version": 1, "entries": entries}).encode(),
                                   today=date(2026, 11, 8))
        notes = m.public_notes(doc, asof=date(2026, 11, 1))
        self.assertEqual(set(notes), {"TEST", "CHILD"})
        self.assertEqual(notes["TEST"]["kind"], "DISTRIBUTION")

    def test_top20_excludes_target_and_keeps_acquirer_score_with_note(self):
        import bottleneck_top20_v3 as engine
        # Exercise the real build scorer and exclusion list with its market/fundamental shapes.
        layer = {"id":"optics", "name_zh":"光學", "chain":"network_optics",
                 "chain_rank":5, "leopold_constraint":"x", "filing_terms":[],
                 "capturers":[{"symbol":ticker,"role":"optics",
                   "source_url":"https://www.sec.gov/test","source_date":"2026-11-02"}
                   for ticker in ("LITE","MRVL","AAA")]}
        with tempfile.TemporaryDirectory() as d:
            p = Path(d)
            (p/"layers.json").write_text(json.dumps({"layers":[layer]}),encoding="utf-8")
            def market(symbol, *args, **kwargs):
                return {"name":symbol, "symbol":symbol, "market_cap_usd":None,
                        "market":{"market_cap":2e10, "currency":"USD", "price":100,
                           "ret_6m":0.2,"ret_1y":0.25,"cagr_2y":0.15,"asof":"2026-11-06",
                           "source":"Yahoo","source_url":"https://finance.yahoo.com/quote/"+symbol},
                        "fundamentals":None}
            with patch.multiple(engine, LAYERS=p/"layers.json", SERENITY=p/"missing.json",
                   LEOPOLD=p/"missing-leopold.json", cik_index=lambda captured=None: {},
                   yahoo_data=market, taiwan_monthly_revenue=lambda *a:{},
                   cision_interim_revenue=lambda *a, **k:{},
                   nasdaq_consensus=lambda *a, **k:None), \
                 patch.object(engine.listing_lineage,"load",lambda *a,**k:{}):
                result = engine.build(None, datetime(2026,11,7,tzinfo=timezone.utc), with_news=False)
                with patch.object(engine.corporate_actions, "load_actions", return_value={"schema_version": 1, "entries": []}):
                    without_deal = engine.build(None, datetime(2026, 11, 7, tzinfo=timezone.utc), with_news=False)
            self.assertNotIn("LITE", [r["symbol"] for r in result["top"]])
            exclusion = next(r for r in result["excluded"] if r["symbol"]=="LITE")
            self.assertIn("DEAL_PENDING_TARGET", exclusion["reasons"])
            self.assertEqual(exclusion["acquirer"],"MRVL")
            mrvl = next(r for r in result["top"] if r["symbol"]=="MRVL")
            self.assertEqual(mrvl["corporate_action"]["exchange_ratio"],4.5)
            self.assertGreater(mrvl["score"],0)
            baseline = next(row for row in without_deal["top"] if row["symbol"] == "MRVL")
            self.assertEqual(mrvl["score"], baseline["score"])
            self.assertNotIn("corporate_action", baseline)
            self.assertIn("併購", exclusion["reason_zh"])

    def test_option_candidates_are_withheld_before_provider_call(self):
        import build_line_public_options as pub
        import build_v211_public_options as versioned
        symbols = [{"ticker":"LITE","market_data_ticker":"LITE","currency":"USD"},
                   {"ticker":"MRVL","market_data_ticker":"MRVL","currency":"USD"}]
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)
            def unavailable(*a,**k): raise AssertionError("provider must not be called on pending target")
            with patch.object(pub, "load_public_symbols", return_value=symbols), \
                 patch.object(pub, "load_market_prices", return_value={"LITE":99.0,"MRVL":88.0}), \
                 patch.object(pub, "load_policy", return_value={}), \
                 patch.object(pub, "get_option_suggestion", side_effect=lambda ticker,*a,**k: (
                       unavailable() if ticker=="LITE" else {"ticker":ticker,"provider_symbol":ticker,
                       "current_price":88,"retrieved_at":"2026-11-07T00:00:00Z",
                       "status":"OK","quote_source":"yfinance","periods":{}})):
                ordinary=pub.build_public_options(output_path=p/"public.json",sleep_seconds=0)
                enabled=versioned.build(output_path=p/"v211.json",sleep_seconds=0)
            for result in (ordinary,enabled):
                lite=next(item for item in result if item["ticker"]=="LITE")
                self.assertEqual(lite["status"],"DEAL_PENDING_TARGET")
                self.assertEqual(lite["periods"],{})
                self.assertIsNone(lite["current_price"])
                self.assertTrue(lite["line_public_eligible"])  # Worker transport schema, not an option recommendation
                self.assertNotIn("withheld_reason",lite)
                self.assertNotIn("recommended_candidates",json.dumps(lite))
