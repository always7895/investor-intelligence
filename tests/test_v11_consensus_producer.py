"""Operator 2026-10-13 (R/OPERATOR-DECISION-CONSENSUS-AND-OFFHOURS-OPTIONS-20261013.txt A1): the analyst-consensus revenue
route is on, labelled analyst consensus, not company guidance, unofficial. These tests drive the producer chain the refresh
runs - Yahoo quoteSummary body -> revenue_consensus_quarterly.refresh_symbol (cache file) -> load_cache / select_for_cutoff ->
the real sealer (publish_sealed_snapshot._with_order_forecast and captured_bottleneck_v3_body) -> order_forecast.build_v3 -
over the reviewed fixture registry with the registry gate on and off (tests/fixtures/make_v11_consensus_sealed.py builds the
cases; the Worker tests read its committed output). No network: the transport is a fake body."""
from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import order_forecast as ofc  # noqa: E402
import publish_sealed_snapshot as publisher  # noqa: E402
import revenue_consensus_quarterly as collector  # noqa: E402
import revenue_guidance  # noqa: E402


def load_generator():
    path = ROOT / "tests" / "fixtures" / "make_v11_consensus_sealed.py"
    spec = importlib.util.spec_from_file_location("make_v11_consensus_sealed", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


GEN = load_generator()
CUTOFF_TEXT = "2026-09-28T15:00:00Z"
CUTOFF = GEN.utc(CUTOFF_TEXT)
SOURCE = "https://query2.finance.yahoo.com/v10/finance/quoteSummary/{}?modules=earningsTrend,financialData"
LABEL = "分析師共識（非公司財測、非官方）"
CONSENSUS_KEYS = {"symbol", "currency", "scope", "captured_at", "source_url", "quarters"}
QUARTER_KEYS = {"period", "scope", "currency", "start", "end", "revenue", "analysts"}


def v3_of(outlooks: dict, symbol: str) -> dict:
    return outlooks[symbol]["order_forecast_v3"]


class ConsensusRouteProducerTests(unittest.TestCase):
    """build_v3 / the sealer with the gate on: the labelled consensus basis, its precedence rules and its fail-closed states."""

    @classmethod
    def setUpClass(cls):
        cls.built = GEN.build()["cases"]

    def outlooks(self, name: str) -> dict:
        return self.built[name]["outlooks"]

    def test_gate_on_seals_the_labelled_consensus_basis_for_a_korean_issuer(self):
        v3 = v3_of(self.outlooks("available"), "000660.KS")
        self.assertEqual((v3["status"], v3["revenue_status"], v3["revenue_basis"], v3["revenue_reason"], v3["revenue_diagnostic"]),
                         ("AVAILABLE", "AVAILABLE", "CONSENSUS", None, None))
        self.assertTrue(v3["evidence"]["consensus_enabled"])
        label = f"{LABEL}｜Yahoo Finance，37 位分析師，截至 2026-09-28"
        self.assertEqual((v3["m6"]["basis_label"], v3["m12"]["basis_label"]), (label, label))
        c1, c2 = 100287043740000, 113906353020000
        self.assertAlmostEqual(v3["m6"]["amount"], c1 + c2)
        self.assertAlmostEqual(v3["m12"]["amount"], c1 + 3 * c2)
        actuals = [24448.9e9, 32826.7e9, 52576.3e9, 79318.7e9]
        self.assertAlmostEqual(v3["baseline_b"], sum(actuals), delta=1e6)
        self.assertAlmostEqual(v3["m6"]["scenario"]["change"], (actuals[2] + actuals[3] + c1 + c2) / sum(actuals) - 1, places=9)
        # the sealed capture is the bounded projection the Worker re-validates, with its provider and capture instant
        consensus = v3["evidence"]["consensus"]
        self.assertEqual(set(consensus), CONSENSUS_KEYS)
        self.assertEqual(consensus["source_url"], SOURCE.format("000660.KS"))
        self.assertEqual(consensus["captured_at"], "2026-09-28T12:00:00Z")
        self.assertTrue(all(set(q) <= QUARTER_KEYS and q["analysts"] == 37 for q in consensus["quarters"]))
        self.assertEqual([q["period"] for q in consensus["quarters"]], ["0q", "+1q"])

    def test_the_label_names_the_smaller_analyst_count_of_the_quarters_used(self):
        v3 = v3_of(self.outlooks("available"), "005930.KS")  # 25 analysts, then 2: one consensus quarter, flat after it
        self.assertEqual(v3["m6"]["basis_label"], f"{LABEL}｜Yahoo Finance，25 位分析師，截至 2026-09-28")
        self.assertEqual([q["derivation"] for q in v3["forward_quarters"]][1], "僅一季共識（次季分析師樣本不足），其後持平模型")
        self.assertAlmostEqual(v3["m6"]["amount"], 2 * 204646748150000)

    def test_a_non_korean_issuer_with_no_numeric_guidance_gets_the_route(self):
        v3 = v3_of(self.outlooks("available"), "ACME")
        self.assertEqual((v3["revenue_basis"], v3["m6"]["currency"], v3["evidence"]["reported_quarters"][0]["accounting_basis"]),
                         ("CONSENSUS", "USD", "GAAP"))
        self.assertEqual(v3["m6"]["basis_label"], f"{LABEL}｜Yahoo Finance，11 位分析師，截至 2026-09-28")

    def test_company_guidance_keeps_precedence_over_a_capture(self):
        v3 = v3_of(self.outlooks("guidance_precedence"), "NVDA")
        self.assertEqual((v3["revenue_basis"], v3["m6"]["basis_label"]), ("COMPANY_GUIDANCE", "公司營收財測＋模型（非訂單）"))
        self.assertIsNone(v3["evidence"]["consensus"])  # a capture of a GUIDANCE record is never sealed or used

    def test_contracted_recognition_stays_separate_and_is_never_added(self):
        v3 = v3_of(self.outlooks("with_recognition"), "ACME")
        self.assertEqual(v3["revenue_basis"], "CONSENSUS")
        self.assertAlmostEqual(v3["m12"]["amount"], 1.25e9 + 3 * 1.35e9)  # consensus plus model only
        self.assertAlmostEqual(v3["contracted_recognition"]["m12"]["amount"], 3.2e8 * 0.39)
        self.assertIsNone(v3["contracted_recognition"]["m6"])
        self.assertEqual(v3["m12"]["contracted_recognition"], v3["contracted_recognition"]["m12"])

    def test_gate_off_keeps_the_deferred_state_whatever_the_cache_holds(self):
        v3 = v3_of(self.outlooks("gate_off"), "000660.KS")
        self.assertEqual((v3["revenue_status"], v3["revenue_reason"], v3["revenue_diagnostic"], v3["revenue_basis"]),
                         ("UNAVAILABLE", "NOT_DISCLOSED", "CONSENSUS_DEFERRED", None))
        self.assertFalse(v3["evidence"]["consensus_enabled"])
        self.assertIsNone(v3["evidence"]["consensus"])

    def test_gate_on_never_seals_the_deferred_diagnostic(self):
        for name, outlooks in ((n, c["outlooks"]) for n, c in self.built.items() if n != "gate_off"):
            for symbol, outlook in outlooks.items():
                self.assertNotEqual(outlook["order_forecast_v3"]["revenue_diagnostic"], "CONSENSUS_DEFERRED", f"{name} {symbol}")

    def test_a_missing_capture_stands_as_nondisclosure_with_no_figure(self):
        v3 = v3_of(self.outlooks("no_capture"), "000660.KS")
        self.assertEqual((v3["revenue_status"], v3["revenue_reason"], v3["revenue_diagnostic"], v3["revenue_basis"]),
                         ("UNAVAILABLE", "NOT_DISCLOSED", None, None))
        self.assertIsNone(v3["evidence"]["consensus"])
        self.assertIsNone(v3["evidence"]["consensus_fault"])
        self.assertEqual((v3["m6"]["status"], v3["m12"]["status"]), ("UNAVAILABLE", "UNAVAILABLE"))

    def test_a_capture_older_than_24_hours_is_stale_and_seals_beside_that_reason(self):
        v3 = v3_of(self.outlooks("stale_age"), "000660.KS")  # captured 2026-09-27T10:00Z, built 2026-09-28T15:00Z (29 hours)
        self.assertEqual((v3["revenue_status"], v3["revenue_reason"], v3["revenue_basis"]), ("UNAVAILABLE", "STALE", None))
        self.assertEqual(v3["evidence"]["consensus"]["captured_at"], "2026-09-27T10:00:00Z")
        self.assertEqual(v3["m6"]["reason"], "STALE")

    def test_a_capture_taken_before_the_quarter_ended_is_expired(self):
        # Operator 2026-10-14 bridge: captured 2026-09-30T20:00Z (before the day after the end), built 2026-10-01: STALE.
        v3 = v3_of(self.outlooks("quarter_ended"), "000660.KS")
        self.assertEqual((v3["revenue_status"], v3["revenue_reason"], v3["revenue_basis"]), ("UNAVAILABLE", "STALE", None))
        self.assertEqual(v3["evidence"]["consensus"]["quarters"][0]["end"], "2026-09-30")

    def test_an_expired_consensus_leaves_the_contracted_recognition_alone(self):
        v3 = v3_of(self.outlooks("recognition_stale"), "ACME")
        self.assertEqual((v3["status"], v3["revenue_status"], v3["revenue_reason"], v3["revenue_basis"]), ("AVAILABLE", "UNAVAILABLE", "STALE", None))
        self.assertEqual((v3["m6"]["status"], v3["m6"]["reason"], v3["m12"]["status"], v3["m12"]["basis"]),
                         ("UNAVAILABLE", "STALE", "AVAILABLE", "RECOGNITION"))
        self.assertAlmostEqual(v3["m12"]["amount"], 3.2e8 * 0.39)
        self.assertEqual(v3["evidence"]["consensus"]["captured_at"], "2026-12-10T02:00:00Z")  # 71 days after the 2026-09-30 end

    def test_a_capture_of_another_quarter_is_a_period_mismatch(self):
        v3 = v3_of(self.outlooks("period_mismatch"), "000660.KS")  # Yahoo's 0q is 4Q26 while the reviewed record anchors 3Q26
        self.assertEqual((v3["revenue_status"], v3["revenue_reason"], v3["revenue_basis"]), ("UNAVAILABLE", "PERIOD_MISMATCH", None))
        self.assertEqual(v3["evidence"]["consensus"]["quarters"][0]["end"], "2026-12-31")

    def test_an_unreadable_cache_is_a_typed_channel_fault_never_a_nondisclosure(self):
        v3 = v3_of(self.outlooks("cache_fault"), "000660.KS")
        self.assertEqual((v3["revenue_status"], v3["revenue_reason"], v3["revenue_basis"]), ("UNAVAILABLE", "INVALID", None))
        self.assertEqual(v3["evidence"]["consensus_fault"], "CONSENSUS_CACHE_LOAD_FAILED")
        self.assertIsNone(v3["evidence"]["consensus"])

    def test_no_refused_state_carries_a_figure_or_a_label(self):
        for name in ("stale_age", "quarter_ended", "period_mismatch", "no_capture", "cache_fault", "gate_off"):
            v3 = v3_of(self.outlooks(name), "000660.KS")
            self.assertEqual((v3["m6"]["status"], v3["m12"]["status"], v3["baseline_b"], v3["forward_quarters"]),
                             ("UNAVAILABLE", "UNAVAILABLE", None, []), name)
            self.assertNotIn(LABEL, json.dumps(v3, ensure_ascii=False), name)

    # ---- direct build_v3 rows: refusals that never reach a labelled figure ----------------------------------------------

    def registry(self, gate=True):
        with tempfile.TemporaryDirectory() as tmp:
            path = GEN.registry_file(Path(tmp), gate)
            registry = revenue_guidance.load_registry(path)
            _, approval = GEN.golden.make_approval(path)
        return registry, approval

    def build(self, symbol, capture, *, gate=True, approval=None, cutoff=CUTOFF):
        registry, default_approval = self.registry(gate)
        return ofc.build_v3(symbol, None, None, cutoff.date(), cutoff, GEN.EMPTY_CLAIMS, revenue_registry=registry,
                            consensus_cache={symbol: capture} if capture is not None else {},
                            revenue_approval=approval or default_approval, release_checks_cache={})

    def capture(self, symbol="000660.KS", **override):
        entry = {"symbol": symbol, "captured_at": "2026-09-28T12:00:00Z", "currency": "KRW", "scope": "CONSOLIDATED",
                 "source_url": SOURCE.format(symbol),
                 "quarters": [{"period": "0q", "end": "2026-09-30", "revenue": 100e12, "analysts": 37, "currency": "KRW", "scope": "CONSOLIDATED"},
                              {"period": "+1q", "end": "2026-12-31", "revenue": 110e12, "analysts": 37, "currency": "KRW", "scope": "CONSOLIDATED"}]}
        entry.update(override)
        return entry

    def test_control_the_hand_built_capture_routes(self):
        v3 = self.build("000660.KS", self.capture())
        self.assertEqual((v3["revenue_status"], v3["revenue_basis"]), ("AVAILABLE", "CONSENSUS"))

    def test_a_capture_without_a_known_source_is_refused_as_invalid_and_never_sealed(self):
        for source in (None, "", "https://example.com/v10/finance/quoteSummary/000660.KS", "http://query2.finance.yahoo.com/x",
                       "https://query2.finance.yahoo.com.evil.example/x", "https://user@query2.finance.yahoo.com/x"):
            capture = self.capture()
            if source is None:
                del capture["source_url"]
            else:
                capture["source_url"] = source
            v3 = self.build("000660.KS", capture)
            self.assertEqual((v3["revenue_status"], v3["revenue_reason"], v3["revenue_basis"]), ("UNAVAILABLE", "INVALID", None), str(source))
            self.assertIsNone(v3["evidence"]["consensus"], str(source))

    def test_a_capture_of_another_currency_is_refused_as_invalid(self):
        capture = self.capture(currency="USD")
        for q in capture["quarters"]:
            q["currency"] = "USD"
        v3 = self.build("000660.KS", capture)
        self.assertEqual((v3["revenue_reason"], v3["revenue_basis"]), ("INVALID", None))

    def test_fewer_than_three_analysts_is_a_sample_shortfall_never_a_figure(self):
        capture = self.capture()
        capture["quarters"][0]["analysts"] = 2
        v3 = self.build("000660.KS", capture)
        self.assertEqual((v3["revenue_status"], v3["revenue_reason"], v3["revenue_basis"]), ("UNAVAILABLE", "SAMPLE_INSUFFICIENT", None))

    def test_an_unreviewed_record_never_reaches_the_consensus(self):
        registry, approval = self.registry()
        stale_approval = {**approval, "registry_sha256": "0" * 64}  # the registry changed after its review
        v3 = self.build("000660.KS", self.capture(), approval=stale_approval)
        self.assertEqual((v3["revenue_reason"], v3["revenue_diagnostic"], v3["revenue_basis"]), ("INVALID", "UNREVIEWED_INPUTS", None))
        self.assertIsNone(v3["evidence"]["consensus"])

    def test_the_gate_is_a_json_true_only(self):
        for value in (False, None, "true", 1, "yes"):
            with tempfile.TemporaryDirectory() as tmp:
                data = json.loads(GEN.REGISTRY.read_text(encoding="utf-8"))
                data["consensus_enabled"] = value
                path = Path(tmp) / "registry.json"
                path.write_text(json.dumps(data), encoding="utf-8")
                registry = revenue_guidance.load_registry(path)
                if value is not False:
                    self.assertEqual(registry["status"], "INVALID", repr(value))  # a non-boolean gate is an invalid registry
                    continue
                _, approval = GEN.golden.make_approval(path)
                v3 = ofc.build_v3("000660.KS", None, None, CUTOFF.date(), CUTOFF, GEN.EMPTY_CLAIMS, revenue_registry=registry,
                                  consensus_cache={"000660.KS": self.capture()}, revenue_approval=approval, release_checks_cache={})
                self.assertEqual(v3["revenue_diagnostic"], "CONSENSUS_DEFERRED", repr(value))


class ConsensusRouteSealerCallerTests(unittest.TestCase):
    """The real caller of the sealer: captured_bottleneck_v3_body reads the cache file the collector wrote."""

    def run_caller(self, cache_bytes: bytes | None, captures: list | None = None):
        generated = CUTOFF
        stamp = CUTOFF_TEXT
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            registry_path = GEN.registry_file(directory, True)
            registry = revenue_guidance.load_registry(registry_path)
            _, approval = GEN.golden.make_approval(registry_path)
            cache = directory / "revenue_consensus_quarterly.json"
            if captures:
                GEN.collect(cache, captures)
            elif cache_bytes is not None:
                cache.write_bytes(cache_bytes)
            claims = directory / "order-claims-v2.json"
            claims.write_text(json.dumps({"schema": "order-claims-v2", "issuers": {}, "documents": [], "claims": []}), encoding="utf-8")
            entry = {"rank": 1, "symbol": "S1", "name": "S One", "layer": "optics", "archetype": "EXPLOSION", "score": 60.9,
                     "role": "CW laser", "role_source": {"url": "https://x.com/a/status/1", "date": "2026-09-03"},
                     "score_parts": {"layer_heat": 5, "capture": 4, "lead": 14, "confirmation": 15, "size": 10, "penalty": 0},
                     "fundamentals": None, "market": {"source": "Yahoo", "source_url": "https://finance.yahoo.com/quote/S1",
                                                      "asof": "2026-09-25", "ret_6m": 0.9, "ret_1y": 0.5, "cagr_2y": 0.6,
                                                      "currency": "USD", "price": 1.0},
                     "market_cap_usd": 1.05e9, "serenity": None, "leopold": None}
            symbols = ["000660.KS", "005930.KS", "ACME", "NVDA"] + [f"S{index}" for index in range(5, 21)]
            doc = {"schema": "v213-bottleneck-top20-v3", "generated_at": stamp,
                   "leads": {"serenity": {"url": None, "latest_post_at": None}, "leopold": {"filing": None}},
                   "top": [{**entry, "rank": index + 1, "symbol": symbol} for index, symbol in enumerate(symbols)], "industries": []}
            with mock.patch.object(collector, "DEFAULT_CACHE_PATH", cache), \
                    mock.patch.object(publisher.company_deep_report, "load_order_scenarios", lambda *a, **k: {}), \
                    mock.patch.object(publisher.company_deep_report, "load_reports", lambda *a, **k: {}), \
                    mock.patch.object(publisher.order_claims, "REGISTRY_PATH", claims):
                body = publisher.captured_bottleneck_v3_body(
                    json.dumps(doc).encode("utf-8"), generated,
                    effective_inputs=publisher.revenue_guidance_overlay.curated_snapshot(generated, registry, approval, {}))
        self.assertTrue(body, "the 20-entry document must seal")
        sealed = json.loads(body[publisher.BOTTLENECK_V3_KEY])
        return {row["symbol"]: row["outlook"]["order_forecast_v3"] for row in sealed["top"]}

    def test_the_caller_seals_the_labelled_consensus_from_the_collector_cache(self):
        captures = [("000660.KS", "2026-09-28T12:00:00Z", GEN.yahoo_raw("KRW", [("0q", "2026-09-30", 1.0e14, 37), ("+1q", "2026-12-31", 1.1e14, 36)])),
                    ("ACME", "2026-09-28T12:00:00Z", GEN.yahoo_raw("USD", [("0q", "2026-09-30", 1.25e9, 12), ("+1q", "2026-12-31", 1.35e9, 11)])),
                    ("NVDA", "2026-09-28T12:00:00Z", GEN.yahoo_raw("USD", [("0q", "2026-09-30", 60e9, 40)]))]
        sealed = self.run_caller(None, captures)
        self.assertEqual((sealed["000660.KS"]["revenue_basis"], sealed["000660.KS"]["m6"]["basis_label"]),
                         ("CONSENSUS", f"{LABEL}｜Yahoo Finance，36 位分析師，截至 2026-09-28"))
        self.assertEqual((sealed["ACME"]["revenue_basis"], sealed["ACME"]["m6"]["currency"]), ("CONSENSUS", "USD"))
        # no capture for the second Korean issuer: nondisclosure with no figure; NVDA's capture is ignored (guidance record)
        self.assertEqual((sealed["005930.KS"]["revenue_reason"], sealed["005930.KS"]["revenue_basis"], sealed["005930.KS"]["revenue_diagnostic"]),
                         ("NOT_DISCLOSED", None, None))
        self.assertNotEqual(sealed["NVDA"]["revenue_basis"], "CONSENSUS")
        self.assertIsNone(sealed["NVDA"]["evidence"]["consensus"])
        self.assertEqual(sealed["S10"]["revenue_reason"], "INPUTS_MISSING")  # an issuer without a reviewed record is unchanged

    def test_the_caller_turns_an_unreadable_cache_into_the_typed_fault_for_every_issuer(self):
        sealed = self.run_caller(b'{"000660.KS": [')
        self.assertEqual((sealed["000660.KS"]["revenue_reason"], sealed["000660.KS"]["evidence"]["consensus_fault"]),
                         ("INVALID", "CONSENSUS_CACHE_LOAD_FAILED"))
        self.assertEqual(sealed["005930.KS"]["revenue_reason"], "INVALID")
        self.assertEqual(sealed["ACME"]["revenue_reason"], "INVALID")
        self.assertIsNone(sealed["000660.KS"]["revenue_basis"])

    def test_the_caller_with_no_cache_file_leaves_every_nondisclosure_without_a_figure(self):
        sealed = self.run_caller(None)
        for symbol in ("000660.KS", "005930.KS", "ACME"):
            self.assertEqual((sealed[symbol]["revenue_reason"], sealed[symbol]["revenue_basis"], sealed[symbol]["revenue_diagnostic"]),
                             ("NOT_DISCLOSED", None, None), symbol)


class ConsensusFixtureIsCurrentTests(unittest.TestCase):
    def test_the_committed_worker_fixture_equals_a_fresh_build(self):
        committed = json.loads(GEN.OUTPUT.read_text(encoding="utf-8"))
        self.assertEqual(json.loads(json.dumps(GEN.build(), ensure_ascii=False)), committed)


if __name__ == "__main__":
    unittest.main()
