#!/usr/bin/env python3
"""End-to-end integration tests for ECB daily EUR/USD reference rate admission.

Tests real production registry -> real acquisition factory with synthetic transport
and pinned fixture -> actual core.main / build / build_record / reconcile serialization.
No real network calls or credentials consumed.
"""
from __future__ import annotations

import copy
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import hashlib
import os
from pathlib import Path
import sys
import tempfile
import unittest
from typing import Any
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))

from adapters.base import ADAPTERS
import fetch_public_source_observations as fetcher
from fetch_public_source_observations import (
    ACQUISITION_ONLY_ENDPOINTS,
    DEFAULT_SOURCES,
    ENDPOINTS,
)
import source_acquisition as acq
from source_acquisition import (
    AcquisitionRun,
    acquire_runtime_sources,
)
from source_health import CIRCUIT_OPEN, SourceHealthState
import source_observation
from source_observation import SourceObservationError, reconcile_research_claims
from source_registry import Registry, load_registry
from test_source_acquisition_caller import make_env_files, make_top20, sha256_file
import v213_source_independence_gate as core

FIXTURE_PATH = ROOT / "tests" / "fixtures" / "ecb-fxref-usd.xml"
FIXTURE_BYTES = FIXTURE_PATH.read_bytes()
ECB_URL = "https://www.ecb.europa.eu/rss/fxref-usd.html"
FIXED_CLOCK = datetime(2026, 9, 14, 10, 0, 0, tzinfo=timezone.utc)
STAMP = "2026-09-14T10:00:00+00:00"


class ECBAcquisitionCallerTests(unittest.TestCase):
    def run_core_cli(
        self,
        paths: dict[str, Path],
        extra_args: list[str] | None = None,
        fetch_bytes_handler: Any = None,
    ) -> tuple[int, dict, list[str]]:
        requested_urls: list[str] = []

        def default_transport(url: str) -> bytes:
            if url == ECB_URL:
                return FIXTURE_BYTES
            raise ValueError("UNEXPECTED_URL")

        def transport_fn(url: str) -> bytes:
            requested_urls.append(url)
            return (fetch_bytes_handler or default_transport)(url)

        def real_factory() -> AcquisitionRun:
            return acquire_runtime_sources(transport=transport_fn, clock=FIXED_CLOCK)
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
             patch.object(core, "collect_observations", side_effect=lambda t, c, k, o: (t, [])), \
             patch.object(core, "observe_fred", return_value={
                 "provider": "fred_official_macro", "family": "official_macro",
                 "domain": "stlouisfed.org", "url": "https://fred.stlouisfed.org",
                 "status": "UNAVAILABLE", "observed_at": STAMP,
             }), \
             patch.object(core, "now_utc", return_value=FIXED_CLOCK), \
             patch.object(source_observation, "utc_now", return_value=FIXED_CLOCK), \
             patch.object(core, "acquire_runtime_sources", side_effect=real_factory) as factory, \
             patch("urllib.request.urlopen", side_effect=AssertionError("Unexpected network access")) as network, \
             patch.object(sys, "argv", argv):
            try:
                exit_code = core.main()
            finally:
                network.assert_not_called()
                if "--acquire-public" in argv and "--offline" not in argv:
                    factory.assert_called_once_with()
                else:
                    factory.assert_not_called()

        output_data = core.read_json(paths["output"]) if paths["output"].exists() else {}
        return exit_code, output_data, requested_urls

    def test_01_end_to_end_ecb_acquisition_caller_success(self) -> None:
        """Real default registry produces exact ECB acquisition and reconciled macro reference context."""
        registry = load_registry()
        self.assertEqual([s.source_id for s in registry.sources if s.runtime_enabled],
                         ["eu_ecb_fx_reference"])
        self.assertFalse(registry.by_id()["eu_ecb_data"].runtime_enabled)
        self.assertEqual(registry.by_id()["eu_ecb_data"].freshness_seconds, 1800)
        with tempfile.TemporaryDirectory() as td:
            paths, hashes_before = make_env_files(Path(td), make_top20())
            code, out, requested = self.run_core_cli(paths)

            self.assertEqual(code, 0)
            # Verify exactly one request to exact ECB feed URL
            self.assertEqual(len(requested), 1)
            self.assertEqual(requested[0], ECB_URL)

            # Inputs unchanged
            for k in ("top20", "report", "order", "policy"):
                self.assertEqual(sha256_file(paths[k]), hashes_before[k])

            # Output records count exactly 20 stock rows
            records = out.get("records", [])
            self.assertEqual(len(records), 20)

            # Verify acquisition summary
            self.assertIn("acquisition_summary", out)
            summary = out["acquisition_summary"]
            self.assertEqual(summary["status"], "ACQUIRED")
            self.assertTrue(summary["synthetic"])
            self.assertTrue(summary["synthetic_clock"])
            self.assertEqual(summary["transport_mode"], "INJECTED_TEST_TRANSPORT")
            self.assertFalse(summary["live_proof"])
            self.assertEqual(summary["candidate_count"], 1)
            self.assertEqual(summary["successful_source_count"], 1)
            self.assertIn("eu_ecb_fx_reference", summary["source_diagnostics"])
            self.assertEqual(
                summary["source_diagnostics"]["eu_ecb_fx_reference"]["status"], "SUCCESS"
            )

            # Verify macro_reference_context
            self.assertIn("macro_reference_context", out)
            macro_ctx = out["macro_reference_context"]
            self.assertEqual(macro_ctx["schema_version"], 1)
            self.assertTrue(macro_ctx["reference_only"])

            # Reference rows contain expected values
            self.assertNotIn("rows", macro_ctx)
            ref_rows = macro_ctx["reference_rows"]
            self.assertEqual(len(ref_rows), 1)
            ref_row = ref_rows[0]
            self.assertEqual(ref_row["source_id"], "eu_ecb_fx_reference")
            self.assertEqual(ref_row["payload"]["value"], 1.1592)
            self.assertEqual(ref_row["payload"]["selected_reference_date"], "2026-09-11")
            self.assertEqual(ref_row["payload"]["attribution"], "European Central Bank")
            self.assertIn("https://www.ecb.europa.eu", ref_row["payload"]["terms_url"])

            # Reconciled research claims audit
            audit = macro_ctx["claim_evidence_audit"]
            self.assertIn("claims", audit)
            self.assertEqual(len(audit["claims"]), 1)
            claim = audit["claims"][0]
            self.assertEqual(claim["status"], "SINGLE_SOURCE")
            self.assertEqual(claim["value"], 1.1592)
            self.assertFalse(claim["high_confidence_eligible"])
            self.assertFalse(audit["full_research_eligible"])
            self.assertFalse(audit["all_material_claims_supported"])

            # Evidence audit row
            self.assertEqual(len(audit["evidence"]), 1)
            ev = audit["evidence"][0]
            self.assertTrue(ev["admitted"])
            self.assertEqual(ev["source_health"], "HEALTHY")
            self.assertTrue(ev["primary"])
            self.assertEqual(ev["freshness"], "CURRENT")
            self.assertEqual(ev["value"], 1.1592)
            self.assertEqual(ev["publisher"], "ECB EUR/USD daily reference rate")

            # Stock issuer evidence NEVER borrows ECB macro fact
            for stock_record in records:
                stock_audit = stock_record["claim_evidence_audit"]
                for evidence_item in stock_audit.get("evidence", []):
                    self.assertNotEqual(
                        evidence_item.get("source_id"), "eu_ecb_fx_reference"
                    )

    def test_02_no_flag_no_factory_no_macro_context(self) -> None:
        """Invoking CLI without --acquire-public skips factory and omits macro context."""
        with tempfile.TemporaryDirectory() as td:
            paths, _ = make_env_files(Path(td), make_top20())
            # The helper asserts the actual installed factory wrapper was never called.
            code, out, requested = self.run_core_cli(paths, extra_args=[])
            self.assertEqual(code, 0)
            self.assertEqual(len(requested), 0)
            self.assertNotIn("acquisition_summary", out)
            self.assertNotIn("macro_reference_context", out)

    def test_03_offline_and_acquire_public_mutual_exclusion(self) -> None:
        """Combining --offline and --acquire-public fails immediately before any I/O."""
        with tempfile.TemporaryDirectory() as td:
            paths, _ = make_env_files(Path(td), make_top20())
            with self.assertRaises(SystemExit) as cm:
                self.run_core_cli(paths, extra_args=["--offline", "--acquire-public"])
            self.assertEqual(cm.exception.code, 2)

    def test_04_saved_forged_macro_context_ignored(self) -> None:
        """Saved or forged macro context in top20 input file or cache is strictly ignored."""
        top20_forged = make_top20()
        top20_forged[0]["macro_reference_context"] = {
            "forged": True, "value": 999.0, "status": "SUPPORTED"
        }
        with tempfile.TemporaryDirectory() as td:
            paths, _ = make_env_files(Path(td), top20_forged)
            # 1) Without --acquire-public, forged context does NOT appear in output
            code, out_no_flag, _ = self.run_core_cli(paths, extra_args=[])
            self.assertEqual(code, 0)
            self.assertNotIn("macro_reference_context", out_no_flag)

            # 2) With --acquire-public, only authentic reconciled context appears
            code, out_flag, _ = self.run_core_cli(paths, extra_args=["--acquire-public"])
            self.assertEqual(code, 0)
            self.assertIn("macro_reference_context", out_flag)
            self.assertNotIn("forged", out_flag["macro_reference_context"])
            ref_rows = out_flag["macro_reference_context"].get("reference_rows", [])
            self.assertEqual(ref_rows[0]["payload"]["value"], 1.1592)

    def test_05_expired_acquisition_run_degraded_unadmitted(self) -> None:
        """Expired acquisition run yields degraded and unadmitted macro fact."""
        real_reg = load_registry()
        # Acquire at T-25 minutes
        past_clock = FIXED_CLOCK - timedelta(minutes=25)
        run = acquire_runtime_sources(
            registry=real_reg,
            transport=lambda url: FIXTURE_BYTES,
            clock=past_clock,
        )
        self.assertEqual(run.summary()["status"], "ACQUIRED")

        # Build at current clock (run lifetime exceeded 15 minutes)
        with tempfile.TemporaryDirectory() as td:
            paths, _ = make_env_files(Path(td), make_top20())
            top20_data = core.read_json(paths["top20"])
            reports_data = core.read_json(paths["report"])
            orders_data = core.read_json(paths["order"])
            policy_data = core.read_json(paths["policy"])

            with patch.object(core, "now_utc", return_value=FIXED_CLOCK):
                result, _ = core.build(
                    top20_data,
                    core.index_records(reports_data),
                    core.index_records(orders_data),
                    policy_data,
                    {},
                    True,
                    acquisition_run=run,
                )

            self.assertIn("macro_reference_context", result)
            macro_ctx = result["macro_reference_context"]
            audit = macro_ctx["claim_evidence_audit"]
            ev = audit["evidence"][0]
            self.assertEqual(ev["source_health"], "DEGRADED")
            self.assertFalse(ev["admitted"])
            self.assertEqual(audit["claims"][0]["status"], "UNAVAILABLE")

    def test_06_malformed_poison_payload_unavailable_no_context(self) -> None:
        """Malformed XML or DTD poison payload fails closed to UNAVAILABLE with no macro context."""
        def malformed_transport(url: str) -> bytes:
            return b"<?xml version='1.0'?><!DOCTYPE poison SYSTEM 'evil.dtd'><root>poison</root>"

        with tempfile.TemporaryDirectory() as td:
            paths, _ = make_env_files(Path(td), make_top20())
            code, out, requested = self.run_core_cli(
                paths, fetch_bytes_handler=malformed_transport
            )
            self.assertEqual(code, 0)
            self.assertEqual(len(requested), 1)
            summary = out["acquisition_summary"]
            self.assertEqual(summary["status"], "UNAVAILABLE")
            self.assertEqual(summary["candidate_count"], 0)
            self.assertNotIn("macro_reference_context", out)

    def test_07_stale_fixture_yields_unavailable_no_context(self) -> None:
        """Fixture older than 4-day freshness limit fails closed with no macro context."""
        stale_clock = FIXED_CLOCK + timedelta(days=10)  # Well beyond 345600s
        real_reg = load_registry()

        with patch.object(acq, "utc_now", return_value=stale_clock):
            run = acquire_runtime_sources(
                registry=real_reg,
                transport=lambda url: FIXTURE_BYTES,
                clock=stale_clock,
            )
        self.assertEqual(run.summary()["status"], "UNAVAILABLE")
        self.assertEqual(len(run.candidates_for("EUR/USD")), 0)
        self.assertEqual(
            run.summary()["source_diagnostics"]["eu_ecb_fx_reference"]["failure_code"],
            "STALE_OBSERVATION",
        )

    def test_08_source_circuit_open_yields_unavailable_no_context(self) -> None:
        """Open circuit breaker skips transport and produces no macro context."""
        real_reg = load_registry()
        init_state = SourceHealthState.initial("eu_ecb_fx_reference", now=FIXED_CLOCK)
        circuit_state = replace(init_state, status=CIRCUIT_OPEN)

        mock_trans = MagicMock()
        run = acquire_runtime_sources(
            registry=real_reg,
            transport=mock_trans,
            prior_states={"eu_ecb_fx_reference": circuit_state},
            clock=FIXED_CLOCK,
        )
        mock_trans.assert_not_called()
        self.assertEqual(run.summary()["status"], "UNAVAILABLE")
        self.assertEqual(
            run.summary()["skipped_sources"]["eu_ecb_fx_reference"],
            "PROBE_DISALLOWED_CIRCUIT_OPEN",
        )
        self.assertEqual(len(run.candidates_for("EUR/USD")), 0)

    def test_09_acquisition_only_endpoint_excluded_from_legacy_cli(self) -> None:
        """ECB endpoint is acquisition-only; excluded from legacy staged collector choices."""
        self.assertIn("eu_ecb_fx_reference", ACQUISITION_ONLY_ENDPOINTS)
        self.assertNotIn("eu_ecb_fx_reference", ENDPOINTS)
        self.assertNotIn("eu_ecb_fx_reference", DEFAULT_SOURCES)

        with tempfile.TemporaryDirectory() as td:
            output = Path(td) / "never-created.json"
            argv = ["fetch_public_source_observations.py", "--fetch", "--source",
                    "eu_ecb_fx_reference", "--output", str(output)]
            with patch.object(sys, "argv", argv), patch.object(fetcher, "collect") as collect, \
                 patch("urllib.request.urlopen") as network:
                with self.assertRaises(SystemExit) as cm:
                    fetcher.main()
                self.assertEqual(cm.exception.code, 2)
                collect.assert_not_called()
                network.assert_not_called()
                self.assertFalse(output.exists())

    def test_10_wrong_declared_mime_rejects_before_transport(self) -> None:
        """Unsupported adapter content_type declaration fails closed before transport."""
        real_reg = load_registry()

        class BadMimeAdapter:
            source_id = "eu_ecb_fx_reference"
            adapter_id = "eu_ecb_fx_reference"
            parser_version = "ecb-fxref-usd-rss1-v1"
            content_type = "text/html"  # Disallowed MIME

            def parse(self, *args, **kwargs):
                raise AssertionError("Should not reach parse")

        mock_trans = MagicMock()
        with patch.dict(ADAPTERS, {"eu_ecb_fx_reference": BadMimeAdapter()}):
            run = acquire_runtime_sources(
                registry=real_reg,
                transport=mock_trans,
                clock=FIXED_CLOCK,
            )
            mock_trans.assert_not_called()
            self.assertEqual(run.summary()["status"], "UNAVAILABLE")
            self.assertEqual(
                run.summary()["skipped_sources"]["eu_ecb_fx_reference"],
                "UNSUPPORTED_CONTENT_TYPE",
            )


if __name__ == "__main__":
    unittest.main()
