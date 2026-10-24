"""Independent analyst fields through actual provider callers and compact publisher; no network."""
import copy
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock
from datetime import datetime, timezone
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import bottleneck_top20_v3 as engine
import publish_sealed_snapshot as publisher
import order_claims
NOW = datetime(2026, 10, 23, 12, tzinfo=timezone.utc)
FIXTURE = ROOT / "tests/fixtures/partial-analyst-outlook.json"

def frame(values):
    import pandas as pd
    return pd.DataFrame(values, index=["0y", "+1y"][:len(values)]) if values else pd.DataFrame()

def produce(loss=False, eps_n=5, target_n=4):
    ticker = SimpleNamespace(revenue_estimate=frame([]), earnings_estimate=frame([
        {"avg": -2 if loss else 2, "numberOfAnalysts": 5}, {"avg": -1 if loss else 3, "numberOfAnalysts": eps_n}]))
    with mock.patch.object(engine, "utc_now", return_value=NOW):
        consensus = engine.yahoo_consensus(ticker, "SYNTH", 100, {"targetMeanPrice": 125, "numberOfAnalystOpinions": target_n})
    return publisher._sealed_outlook(engine.outlook("SYNTH", None, consensus), NOW)

def official_references():
    claims = order_claims.load(ROOT / "config/order-claims-v2.json")
    # Bind the tracked revenue pair explicitly; never let host-local overlay/receipt caches affect this fixture.
    return {symbol: publisher._with_order_forecast(symbol, None, None, None, NOW, claims,
            revenue_registry=publisher.revenue_guidance.load_registry(ROOT / "config/revenue-guidance-v1.json"),
            revenue_approval=publisher.revenue_guidance.load_approval(ROOT / "config/revenue-guidance-approval-v1.json"),
            release_checks_cache={}) for symbol in ("APLD", "NBIS")}

def fixture():
    return {"scope": "SYNTHETIC_ACTUAL_PRODUCER_AND_COMPACT_PUBLISHER", "generated_at": "2026-10-23T12:00:00Z",
            "partial": produce(), "loss": produce(True), "all_thin": produce(eps_n=1,target_n=1), "no_basis": produce(True,target_n=0), "official": official_references(), "mixed": [produce(eps_n=1), produce(target_n=1)],
            "order_clocks": [{"input": day, "outlook": publisher._sealed_outlook({**produce(), "orders": {"kind":"RPO","amount":100,"currency":"USD","as_of":day,"source":"SEC","source_url":"https://data.sec.gov/x"}},NOW)} for day in [None,"2026-02-30","2026-10-24","2026-10-23","2021-04-03"]]}

class PartialAnalystTests(unittest.TestCase):
    def test_partial_eps_and_target_survive_missing_revenue_through_publisher(self):
        out = produce();c = out["consensus"]
        self.assertIsNone(c["revenue_growth"])
        self.assertEqual((c["eps_growth"], c["target_upside"]), (.5, .25))
        self.assertEqual([r["kind"] for r in out["scenarios"]], ["EPS_CONSTANT_PE", "ANALYST_TARGET"])
        self.assertIsNone(out["orders"])
    def test_negative_eps_baseline_never_creates_growth(self):
        out = produce(True)
        self.assertIsNone(out["consensus"]["eps_growth"])
        self.assertEqual(out["consensus"]["eps_fy1"], -1)
        self.assertEqual([r["kind"] for r in out["scenarios"]], ["ANALYST_TARGET"])
    def test_one_property_failure_does_not_swallow_other_fields(self):
        class FailedRevenue:
            @property
            def revenue_estimate(self): raise OSError("offline provider failure")
            earnings_estimate = frame([{"avg": 2, "numberOfAnalysts": 5}, {"avg": 3, "numberOfAnalysts": 5}])
        with mock.patch.object(engine, "utc_now", return_value=NOW):
            c = engine.yahoo_consensus(FailedRevenue(), "SYNTH", 100, {"targetMeanPrice": 125, "numberOfAnalystOpinions": 4})
        self.assertEqual(c["eps_growth"], .5);self.assertEqual(c["target_upside"], .25)
        class FailedEps:
            revenue_estimate = frame([])
            @property
            def earnings_estimate(self): raise OSError("offline")
        self.assertEqual(engine.yahoo_consensus(FailedEps(), "SYNTH", 100, {"targetMeanPrice": 125, "numberOfAnalystOpinions": 4})["target_mean"], 125)
    def test_all_missing_and_invalid_target_terms_stay_missing(self):
        t = SimpleNamespace(revenue_estimate=frame([]), earnings_estimate=frame([]))
        for target, count in [(None, 4), (-1, 4), (float("inf"), 4), (125, None), (125, 0), (125, 1.5), (True, 4), (125, True), (10**400, 4)]:
            with self.subTest(target=target, count=count):
                self.assertIsNone(engine.yahoo_consensus(t, "SYNTH", 100, {"targetMeanPrice": target, "numberOfAnalystOpinions": count}))
    def test_publisher_refuses_invalid_clock_counts_and_forged_scenarios(self):
        out=produce()
        for change in [{"source_url":"https://unreviewed.example/analysis"}, {"asof":"2026-10-24"}, {"asof":"2026-10-22"}, {"asof":"2026-02-30"}, {"target_analysts":1.5,"eps_analysts":0}, {"target_mean":float("inf"),"eps_fy1":float("nan")}, {"target_mean":10**400,"eps_fy1":10**400}]:
            bad=copy.deepcopy(out);bad["consensus"].update(change)
            self.assertIsNone(publisher._sealed_outlook(bad,NOW)["consensus"])
        bad=copy.deepcopy(out);bad["consensus"]["raw_unknown"]={"never":"public"};bad["scenarios"]=[{"kind":"ANALYST_TARGET","change":99}]
        sealed=publisher._sealed_outlook(bad,NOW)
        self.assertNotIn("raw_unknown",sealed["consensus"]);self.assertEqual(sealed["scenarios"],[])
    def test_live_and_captured_callers_have_identical_partial_fields(self):
        with tempfile.TemporaryDirectory() as folder:
            base=Path(folder);(base/"chart").write_text("{}")
            (base/"summary").write_text(json.dumps({"quoteSummary":{"result":[{"price":{"currency":"USD"},"financialData":{"targetMeanPrice":{"raw":125},"numberOfAnalystOpinions":{"raw":4}},"earningsTrend":{"trend":[{"period":"0y","earningsEstimate":{"avg":{"raw":2}}},{"period":"+1y","earningsEstimate":{"avg":{"raw":3},"numberOfAnalysts":{"raw":5}}}]}}]}}))
            class Captured:
                def operand(self,key): return base/("chart" if key.startswith("yahoo/chart/") else "summary" if key.startswith("yahoo/summary/") else "missing")
            with mock.patch.object(engine,"_chart_bars",return_value=({},[])), mock.patch.object(engine.listing_lineage,"long_term_returns",return_value={"asof":"2026-10-23","price":100}):
                actual=engine.captured_yahoo_data("SYNTH",Captured(),None,NOW)["consensus"]
            self.assertEqual(actual,produce()["consensus"])
    def test_bad_order_clock_does_not_erase_valid_consensus(self):
        for day in [None, "2026-02-30", "2026-10-24", "2026-10-23", "2021-04-03"]:
            raw = produce();raw["orders"] = {"kind":"RPO","amount":100,"currency":"USD","as_of":day,"source":"SEC","source_url":"https://data.sec.gov/x"}
            sealed=publisher._sealed_outlook(raw,NOW)
            self.assertEqual(sealed["orders"] is not None, day in ["2026-10-23","2021-04-03"])
            self.assertEqual(sealed["consensus"],produce()["consensus"])
    def test_live_call_uses_explicit_capture_clock(self):
        t = SimpleNamespace(revenue_estimate=frame([]),earnings_estimate=frame([]))
        with mock.patch.object(engine,"utc_now",return_value=NOW.replace(year=2027)):
            c=engine.yahoo_consensus(t,"SYNTH",100,{"targetMeanPrice":125,"numberOfAnalystOpinions":4},as_of=NOW)
        self.assertEqual(c["asof"],"2026-10-23")
    def test_official_references_are_dated_contracts_not_recognition(self):
        for symbol, out in official_references().items():
            forecast = out["order_forecast"]
            self.assertEqual(len(forecast["references"]), 1)
            self.assertEqual(forecast["status"], "UNAVAILABLE")
            for horizon in ("m6", "m12"):
                self.assertEqual(forecast[horizon]["status"], "UNAVAILABLE")
                self.assertIsNone(forecast[horizon].get("basis"))
            encoded = json.dumps(out, ensure_ascii=False)
            self.assertNotIn("\\u", encoded)
            self.assertIn("2026-08-31" if symbol == "APLD" else "2026-08-12", encoded)

    def test_shared_worker_fixture_is_exact_actual_output(self):
        self.assertEqual(json.loads(FIXTURE.read_bytes()),fixture())
