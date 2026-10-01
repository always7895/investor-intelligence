#!/usr/bin/env python3
"""Deterministic synthetic tests for actual caller acquisition wiring.

Tests actual core.main -> build -> build_record -> reconcile integration
without live network calls or real environment credentials.
"""
from __future__ import annotations

import copy
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))

from adapters.base import ADAPTERS, make_batch
from fetch_public_source_observations import ENDPOINTS
import source_acquisition as acq
from source_acquisition import AcquisitionRun, acquire_runtime_sources
from source_observation import SourceObservationError, reconcile_research_claims
from source_registry import Registry, load_registry
import test_research_v2_claims as claims_fixture
from test_source_acquisition import BASE_SOURCE, FakeAdapter, NOW, STAMP
import v213_source_independence_gate as core

SYNTHETIC_REGISTRY = Registry(1, (BASE_SOURCE,), ())
TICKERS = ["SYN", "OTHER"] + [f"T{i:02d}" for i in range(2, 20)]


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def make_top20(saved_syn_rows: list[dict] | None = None) -> list[dict]:
    rows = [
        {
            "rank": 1,
            "ticker": "SYN",
            "as_of": STAMP,
            "material_claims": [
                claims_fixture.claim(name="revenue", kind="issuer_financial_statement")
            ],
            "source_observations": list(saved_syn_rows or []),
            "evidence": [],
        },
        {
            "rank": 2,
            "ticker": "OTHER",
            "as_of": STAMP,
            "material_claims": [
                claims_fixture.claim(name="other_rev", kind="issuer_financial_statement")
            ],
            "source_observations": [],
            "evidence": [],
        },
    ]
    for i in range(2, 20):
        t = f"T{i:02d}"
        rows.append({
            "rank": i + 1,
            "ticker": t,
            "as_of": STAMP,
            "material_claims": [claims_fixture.claim(name=f"rev_{i}", kind="issuer_financial_statement")],
            "source_observations": [],
            "evidence": [],
        })
    return rows


def make_env_files(temp_dir: Path, top20: list[dict]) -> tuple[dict[str, Path], dict[str, str]]:
    paths = {
        name: temp_dir / f"{name}.json"
        for name in ("top20", "report", "order", "policy", "cache", "output")
    }
    core.write_json(paths["top20"], top20)
    core.write_json(paths["report"], {"records": [
        {"ticker": t, "long_term_return_pct": 20.0, "short_term_return_pct": 5.0, "retrieved_at": STAMP}
        for t in TICKERS
    ]})
    core.write_json(paths["order"], {"records": [
        {"ticker": t, "current_order_source_urls": [], "future_order_source_urls": []}
        for t in TICKERS
    ]})
    core.write_json(paths["policy"], {
        "policy_version": "2.1.3-test",
        "market_data": {
            "long_term_absolute_tolerance_percentage_points": 30.0,
            "short_term_absolute_tolerance_percentage_points": 18.0,
        },
        "minimums": {
            "high_confidence_claim_independent_families": 2,
            "high_confidence_claim_primary_sources": 1,
            "high_confidence_claim_dated_ratio": 0.8,
            "maximum_single_family_share": 0.70,
            "portfolio_independent_source_families": 3,
            "portfolio_independent_domains": 3,
            "portfolio_claim_source_families": 2,
            "portfolio_claim_source_domains": 2,
            "non_yahoo_market_coverage_ratio": 0.75,
            "portfolio_claim_primary_coverage_ratio": 0.75,
        },
    })
    core.write_json(paths["cache"], {})
    hashes = {k: sha256_file(paths[k]) for k in ("top20", "report", "order", "policy")}
    return paths, hashes


class TestSourceAcquisitionCaller(unittest.TestCase):
    def run_cli(
        self,
        paths: dict[str, Path],
        extra_args: list[str] | None = None,
        registry: Registry = SYNTHETIC_REGISTRY,
        adapter: Any = None,
        fetch_bytes_return: bytes = b"test-payload",
    ) -> tuple[int, dict, MagicMock]:
        argv = [
            "v213_source_independence_gate.py",
            "--top20", str(paths["top20"]),
            "--report", str(paths["report"]),
            "--order-evidence", str(paths["order"]),
            "--policy", str(paths["policy"]),
            "--cache", str(paths["cache"]),
            "--output", str(paths["output"]),
            *(extra_args if extra_args is not None else ["--acquire-public"]),
        ]
        with patch.dict(os.environ, {"ALPHAVANTAGE_API_KEY": ""}), \
             patch.dict(ENDPOINTS, {"issuer": "https://issuer.example/report"}), \
             patch.dict(ADAPTERS, {"issuer": adapter or FakeAdapter("issuer")}), \
             patch.object(core, "collect_observations", side_effect=lambda t, c, k, o: (t, [])), \
             patch.object(core, "observe_fred", return_value={
                 "provider": "fred_official_macro", "family": "official_macro",
                 "domain": "stlouisfed.org", "url": "https://fred.stlouisfed.org",
                 "status": "UNAVAILABLE", "observed_at": STAMP,
             }), \
             patch.object(core, "now_utc", return_value=NOW), \
             patch.object(acq, "utc_now", return_value=NOW), \
             patch("source_observation.utc_now", return_value=NOW), \
             patch.object(acq, "fetch_bytes", return_value=fetch_bytes_return), \
             patch.object(acq, "load_registry", return_value=registry), \
             patch("source_registry.load_registry", return_value=registry), \
             patch("urllib.request.urlopen", side_effect=AssertionError("Unexpected network access")) as network, \
             patch.object(sys, "argv", argv):
            exit_code = core.main()
            network.assert_not_called()
        output_data = core.read_json(paths["output"]) if paths["output"].exists() else {}
        return exit_code, output_data, network

    def test_end_to_end_single_source_admitted_not_high(self) -> None:
        """Admitted single-source evidence is admitted but never high confidence."""
        with tempfile.TemporaryDirectory() as td:
            paths, hashes_before = make_env_files(Path(td), make_top20())
            code, out, _ = self.run_cli(paths)
            self.assertEqual(code, 0)
            for k in ("top20", "report", "order", "policy"):
                self.assertEqual(sha256_file(paths[k]), hashes_before[k])
            self.assertIn("acquisition_summary", out)
            self.assertEqual(out["acquisition_summary"]["status"], "ACQUIRED")
            self.assertEqual(out["acquisition_summary"]["candidate_count"], 1)

            records = {r["ticker"]: r for r in out["records"]}
            syn = records["SYN"]
            audit = syn["claim_evidence_audit"]
            self.assertEqual(len(audit["evidence"]), 1)
            ev = audit["evidence"][0]
            self.assertTrue(ev["admitted"])
            self.assertEqual(ev["source_health"], "HEALTHY")
            self.assertEqual(ev["value"], 100)
            self.assertEqual(audit["claims"][0]["status"], "SINGLE_SOURCE")
            self.assertFalse(audit["claims"][0]["high_confidence_eligible"])
            self.assertFalse(audit["all_material_claims_supported"])
            self.assertFalse(audit["full_research_eligible"])
            self.assertFalse(syn["eligible_for_high_confidence_model_inference"])
            self.assertEqual(syn["public_logic_state"]["model_inference_confidence"], "LIMITED")

            other = records["OTHER"]
            self.assertEqual(len(other["claim_evidence_audit"]["evidence"]), 0)
            self.assertEqual(other["claim_evidence_audit"]["claims"][0]["status"], "UNAVAILABLE")

    def test_unbound_saved_forged_row_cannot_borrow_healthy(self) -> None:
        """Saved observation with forged value or health cannot borrow HEALTHY."""
        forged_row = copy.deepcopy(claims_fixture.evidence(name="issuer", cid="revenue", value=999))
        forged_row["source_health"] = "HEALTHY"
        with tempfile.TemporaryDirectory() as td:
            paths, _ = make_env_files(Path(td), make_top20(saved_syn_rows=[forged_row]))
            code, out, _ = self.run_cli(paths)
            self.assertEqual(code, 0)
            syn = next(r for r in out["records"] if r["ticker"] == "SYN")
            audit = syn["claim_evidence_audit"]
            evidence_by_val = {e["value"]: e for e in audit["evidence"]}
            self.assertIn(999, evidence_by_val)
            self.assertFalse(evidence_by_val[999]["admitted"])
            self.assertEqual(evidence_by_val[999]["source_health"], "DEGRADED")
            self.assertTrue(evidence_by_val[100]["admitted"])

    def test_conflicting_same_source_values_both_retained(self) -> None:
        """Conflicting values from same source are both preserved and report CONFLICTED."""
        batch_records = [
            {
                "canonical_url": "https://issuer.example/report", "published_at": STAMP,
                "jurisdiction": "US", "language": "en", "claim_type": "issuer_financial_statement",
                "evidence_role": "financial_statements",
                "payload": {
                    "claim_ids": ["revenue"], "subject": "SYN", "metric": "revenue",
                    "period": "2026Q2", "unit": "million", "currency": "USD", "value": val,
                    "basis": "GAAP", "scope": "consolidated", "as_of": STAMP,
                    "passage": "Synthetic disclosed value", "origin_group": "issuer",
                },
            }
            for val in (100, 200)
        ]
        adapter = FakeAdapter("issuer", records=batch_records)
        with tempfile.TemporaryDirectory() as td:
            paths, _ = make_env_files(Path(td), make_top20())
            code, out, _ = self.run_cli(paths, adapter=adapter)
            self.assertEqual(code, 0)
            syn = next(r for r in out["records"] if r["ticker"] == "SYN")
            audit = syn["claim_evidence_audit"]
            self.assertEqual(len(audit["evidence"]), 2)
            self.assertEqual(audit["claims"][0]["status"], "CONFLICTED")
            self.assertIn("MATERIAL_VALUE_CONFLICT", audit["claims"][0]["reasons"])
            self.assertEqual(len(audit["claims"][0]["conflict_set"]), 2)

    def test_dict_context_rejected(self) -> None:
        """Dict or duck context is rejected with SourceObservationError."""
        rec = make_top20()[0]
        with self.assertRaises(SourceObservationError):
            reconcile_research_claims(rec, acquisition_run={"invalid": "duck"})
        with self.assertRaises(SourceObservationError):
            core.build_record(rec, {}, {}, [], {}, {}, acquisition_run={"invalid": "duck"})
        with self.assertRaises(SourceObservationError):
            core.build([rec], {}, {}, {}, {}, False, acquisition_run={"invalid": "duck"})

    def test_expired_context_and_fake_doc_context_ignored(self) -> None:
        """Expired acquisition run returns DEGRADED; fake document context is ignored."""
        with patch.dict(ENDPOINTS, {"issuer": "https://issuer.example/report"}), \
             patch.dict(ADAPTERS, {"issuer": FakeAdapter("issuer")}):
            run = acquire_runtime_sources(
                registry=SYNTHETIC_REGISTRY,
                transport=lambda u: b"payload",
                clock=NOW - timedelta(minutes=25),
            )
        cand = run.candidates_for("SYN")[0]
        self.assertEqual(run.health_for(cand, now=NOW), "DEGRADED")

        doc_with_fake = make_top20()
        doc_with_fake[0]["acquisition_run"] = {"status": "HEALTHY"}
        doc_with_fake[0]["health_states"] = {"issuer": "HEALTHY"}
        with tempfile.TemporaryDirectory() as td:
            paths, _ = make_env_files(Path(td), doc_with_fake)
            code, out, _ = self.run_cli(paths, extra_args=[])
            self.assertEqual(code, 0)
            syn = next(r for r in out["records"] if r["ticker"] == "SYN")
            self.assertEqual(len(syn["claim_evidence_audit"]["evidence"]), 0)
            self.assertEqual(syn["claim_evidence_audit"]["status"], "UNAVAILABLE")

    def test_flags_mutually_exclusive_and_no_flag_no_factory(self) -> None:
        """Combined --offline and --acquire-public fails before acquisition; no flag skips factory."""
        with tempfile.TemporaryDirectory() as td:
            paths, _ = make_env_files(Path(td), make_top20())
            with self.assertRaises(SystemExit) as cm:
                self.run_cli(paths, extra_args=["--offline", "--acquire-public"])
            self.assertEqual(cm.exception.code, 2)

            with patch.object(core, "acquire_runtime_sources") as mock_factory:
                code, out, _ = self.run_cli(paths, extra_args=["--offline"])
                self.assertEqual(code, 0)
                mock_factory.assert_not_called()
                self.assertNotIn("acquisition_summary", out)

    def test_explicit_disabled_registry_negative_unavailable(self) -> None:
        """Explicit disabled registry negative asserts transport not called and yields UNAVAILABLE."""
        real_reg = load_registry()
        disabled_sources = tuple(replace(s, runtime_enabled=False) for s in real_reg.sources)
        disabled_reg = Registry(real_reg.schema_version, disabled_sources, real_reg.catalog_files)
        mock_transport = MagicMock()
        run = acquire_runtime_sources(registry=disabled_reg, transport=mock_transport, clock=NOW)
        mock_transport.assert_not_called()
        self.assertEqual(run.summary()["status"], "UNAVAILABLE")
        self.assertEqual(run.summary()["candidate_count"], 0)

    def test_default_registry_ecb_runtime_enabled(self) -> None:
        """Default production registry has exactly eu_ecb_fx_reference enabled."""
        real_reg = load_registry()
        runtime_sources = [s for s in real_reg.sources if s.runtime_enabled]
        self.assertEqual(len(runtime_sources), 1)
        self.assertEqual(runtime_sources[0].source_id, "eu_ecb_fx_reference")
        ecb_data = next(s for s in real_reg.sources if s.source_id == "eu_ecb_data")
        self.assertFalse(ecb_data.runtime_enabled)
        self.assertEqual(ecb_data.freshness_seconds, 1800)

    def test_captured_candidate_wrong_ticker_rejected_preserved_row(self) -> None:
        """Saved captured candidate bound to wrong ticker is preserved but not admitted."""
        with patch.dict(ENDPOINTS, {"issuer": "https://issuer.example/report"}), \
             patch.dict(ADAPTERS, {"issuer": FakeAdapter("issuer")}), \
             patch.object(core, "now_utc", return_value=NOW):
            run = acquire_runtime_sources(registry=SYNTHETIC_REGISTRY, transport=lambda _: b"test", clock=NOW)
            cand = run.candidates_for("SYN")[0]
            rec_wrong = {"ticker": "OTHER", "material_claims": [claims_fixture.claim()], "source_observations": [cand]}
            res_wrong = core.build_record(rec_wrong, {}, {}, [], {}, {}, acquisition_run=run)
            ev_wrong = res_wrong["claim_evidence_audit"]["evidence"]
            self.assertEqual(len(ev_wrong), 1)
            self.assertFalse(ev_wrong[0]["admitted"])
            self.assertEqual(ev_wrong[0]["source_health"], "DEGRADED")
            self.assertEqual(res_wrong["claim_evidence_audit"]["claims"][0]["status"], "UNAVAILABLE")

            rec_right = {"ticker": "SYN", "material_claims": [claims_fixture.claim()], "source_observations": [cand]}
            res_right = core.build_record(rec_right, {}, {}, [], {}, {}, acquisition_run=run)
            ev_right = res_right["claim_evidence_audit"]["evidence"]
            self.assertEqual(len(ev_right), 1)
            self.assertTrue(ev_right[0]["admitted"])
            self.assertEqual(ev_right[0]["source_health"], "HEALTHY")

            with self.assertRaises(SourceObservationError):
                reconcile_research_claims(rec_right, registry=Registry(2, (), ()), acquisition_run=run, now=NOW)


if __name__ == "__main__":
    unittest.main()
