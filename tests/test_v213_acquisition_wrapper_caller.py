#!/usr/bin/env python3
"""Caller-chain integration tests for v4 build_with_market_quality_degradation wrapper.

Verifies that the actual v3.main -> v4.gate.main -> core.main chain correctly forwards
acquisition_run keyword arguments to the original core builder while preserving
strict AcquisitionRun type validation, core macro_reference_context, and market policy
transformation.
"""
from __future__ import annotations

import copy
from datetime import datetime, timezone
import hashlib
import inspect
import io
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

import source_observation
from source_acquisition import AcquisitionRun, acquire_runtime_sources
from source_observation import SourceObservationError
from test_source_acquisition_caller import make_env_files, make_top20, sha256_file
import v213_source_independence_gate as core
import v213_source_independence_gate_v3 as v3
import v213_source_independence_gate_v4 as v4

FIXTURE_PATH = ROOT / "tests" / "fixtures" / "ecb-fxref-usd.xml"
FIXTURE_BYTES = FIXTURE_PATH.read_bytes()
ECB_URL = "https://www.ecb.europa.eu/rss/fxref-usd.html"
FIXED_CLOCK = datetime(2026, 9, 14, 10, 0, 0, tzinfo=timezone.utc)
STAMP = "2026-09-14T10:00:00+00:00"


class TestV213AcquisitionWrapperCaller(unittest.TestCase):
    def setUp(self) -> None:
        for target in ("urllib.request.OpenerDirector.open", "requests.sessions.Session.request"):
            blocker = patch(target, side_effect=AssertionError("NETWORK_DISABLED"))
            mocked = blocker.start()
            self.addCleanup(blocker.stop)
            self.addCleanup(mocked.assert_not_called)

    def run_v3_cli(
        self,
        paths: dict[str, Path],
        extra_args: list[str] | None = None,
        custom_factory: Any = None,
    ) -> tuple[int, dict[str, Any], list[str]]:
        requested_urls: list[str] = []

        def default_transport(url: str) -> bytes:
            if url == ECB_URL:
                return FIXTURE_BYTES
            raise ValueError(f"UNEXPECTED_URL: {url}")

        def transport_fn(url: str) -> bytes:
            requested_urls.append(url)
            return default_transport(url)

        def real_factory() -> AcquisitionRun:
            return acquire_runtime_sources(transport=transport_fn, clock=FIXED_CLOCK)

        factory_fn = custom_factory if custom_factory is not None else real_factory

        argv = [
            "v213_source_independence_gate_v3.py",
            "--top20", str(paths["top20"]),
            "--report", str(paths["report"]),
            "--order-evidence", str(paths["order"]),
            "--policy", str(paths["policy"]),
            "--cache", str(paths["cache"]),
            "--output", str(paths["output"]),
            *(extra_args if extra_args is not None else []),
        ]

        # Patch v3 pre/post file normalization functions to isolate unrelated SEC/federation enrichment
        # and avoid side-effects on repository-level caches.
        with patch.dict(os.environ, {"ALPHAVANTAGE_API_KEY": ""}), \
             patch.object(v3, "enrich_top20_with_latest_sec_filing_provenance", return_value=None), \
             patch.object(v3, "normalize_top20_evidence_publication_order", return_value=None), \
             patch.object(v3, "normalize_federation_to_final_top20", return_value=None), \
             patch.object(v3.v4.gate, "collect_observations", side_effect=lambda t, c, k, o: (t, [])), \
             patch.object(core, "collect_observations", side_effect=lambda t, c, k, o: (t, [])), \
             patch.object(v3.v4.gate, "observe_fred", return_value={
                 "provider": "fred_official_macro", "family": "official_macro",
                 "domain": "stlouisfed.org", "url": "https://fred.stlouisfed.org",
                 "status": "UNAVAILABLE", "observed_at": STAMP,
             }), \
             patch.object(core, "observe_fred", return_value={
                 "provider": "fred_official_macro", "family": "official_macro",
                 "domain": "stlouisfed.org", "url": "https://fred.stlouisfed.org",
                 "status": "UNAVAILABLE", "observed_at": STAMP,
             }), \
             patch.object(v3.v4.gate, "now_utc", return_value=FIXED_CLOCK), \
             patch.object(core, "now_utc", return_value=FIXED_CLOCK), \
             patch.object(source_observation, "utc_now", return_value=FIXED_CLOCK), \
             patch.object(v3.v4.gate, "acquire_runtime_sources", side_effect=factory_fn) as factory_gate, \
             patch.object(core, "acquire_runtime_sources", side_effect=factory_fn) as factory_core, \
             patch("urllib.request.urlopen", side_effect=AssertionError("Unexpected network access")) as network, \
             patch.object(sys, "argv", argv):
            try:
                exit_code = v3.main()
            finally:
                network.assert_not_called()
                if "--acquire-public" in argv and "--offline" not in argv:
                    factory_gate.assert_called_once_with()
                else:
                    factory_gate.assert_not_called()
                factory_core.assert_not_called()

        output_data = core.read_json(paths["output"]) if paths["output"].exists() else {}
        return exit_code, output_data, requested_urls

    def test_01_caller_chain_default_no_acquire(self) -> None:
        """Default run without --acquire-public: acquisition_run=None reaches core, no factory invoked."""
        with tempfile.TemporaryDirectory() as td:
            paths, hashes_before = make_env_files(Path(td), make_top20())
            code, out, requested_urls = self.run_v3_cli(paths, extra_args=[])
            self.assertEqual(code, 0)
            self.assertEqual(len(requested_urls), 0)
            self.assertNotIn("acquisition_summary", out)
            self.assertNotIn("macro_reference_context", out)
            self.assertEqual(out["schema_version"], 3)
            self.assertEqual(out["portfolio"]["market_corroboration_status"], "DEGRADED")
            self.assertEqual(out["portfolio"]["high_confidence_model_inference_eligible_count"], 0)
            for k in ("top20", "report", "order", "policy"):
                self.assertEqual(sha256_file(paths[k]), hashes_before[k])

    def test_02_caller_chain_acquire_public(self) -> None:
        """--acquire-public: exact run reaches core; macro-only SINGLE_SOURCE; no stock promotion."""
        with tempfile.TemporaryDirectory() as td:
            paths, hashes_before = make_env_files(Path(td), make_top20())
            code, out, requested_urls = self.run_v3_cli(paths, extra_args=["--acquire-public"])
            self.assertEqual(code, 0)
            self.assertEqual(len(requested_urls), 1)
            self.assertEqual(requested_urls[0], ECB_URL)

            # Core builder acquisition summary and macro context present
            self.assertIn("acquisition_summary", out)
            self.assertEqual(out["acquisition_summary"]["status"], "ACQUIRED")
            self.assertEqual(out["acquisition_summary"]["candidate_count"], 1)

            self.assertIn("macro_reference_context", out)
            macro_ctx = out["macro_reference_context"]
            self.assertTrue(macro_ctx["reference_only"])
            self.assertEqual(len(macro_ctx["reference_rows"]), 1)
            macro_audit = macro_ctx["claim_evidence_audit"]
            self.assertEqual(macro_audit["claims"][0]["status"], "SINGLE_SOURCE")
            self.assertFalse(macro_audit["claims"][0]["high_confidence_eligible"])

            # Macro-only: NO stock promotion
            self.assertEqual(out["portfolio"]["high_confidence_model_inference_eligible_count"], 0)
            for record in out["records"]:
                self.assertFalse(record["eligible_for_high_confidence_model_inference"])
                self.assertEqual(record["public_logic_state"]["model_inference_confidence"], "LIMITED")

            # Missing issuer evidence stays blocking despite admitted ECB context.
            self.assertEqual(out["portfolio"]["market_corroboration_status"], "DEGRADED")
            self.assertEqual(out["quality_status"], "FAIL")
            self.assertTrue(out["blocking_violations"])

            for k in ("top20", "report", "order", "policy"):
                self.assertEqual(sha256_file(paths[k]), hashes_before[k])

    def test_03_caller_chain_offline_plus_acquire_fails_before_factory(self) -> None:
        """--offline plus --acquire-public fails before factory is invoked."""
        factory_called: list[bool] = []
        def tracking_factory():
            factory_called.append(True)
            raise AssertionError("Factory should never be called when offline + acquire are combined")

        with tempfile.TemporaryDirectory() as td:
            paths, hashes_before = make_env_files(Path(td), make_top20())
            with patch("sys.stderr", new=io.StringIO()):
                with self.assertRaises(SystemExit) as ctx:
                    self.run_v3_cli(
                        paths,
                        extra_args=["--offline", "--acquire-public"],
                        custom_factory=tracking_factory,
                    )
            self.assertNotEqual(ctx.exception.code, 0)
            self.assertEqual(len(factory_called), 0)
            for k in ("top20", "report", "order", "policy"):
                self.assertEqual(sha256_file(paths[k]), hashes_before[k])

    def test_04_forged_object_fails_core_type_check_at_wrapper_direct_boundary(self) -> None:
        """Forged or duck-typed object fails core AcquisitionRun type check directly at wrapper boundary."""
        sample_top20 = make_top20()
        sample_policy = {
            "minimums": {},
            "market_data": {
                "long_term_absolute_tolerance_percentage_points": 30.0,
                "short_term_absolute_tolerance_percentage_points": 18.0,
            },
        }

        # Dict context attempt
        with self.assertRaises(SourceObservationError) as ctx:
            v3.v4.build_with_market_quality_degradation(
                sample_top20, {}, {}, sample_policy, {}, False,
                acquisition_run={"forged": True, "summary": lambda: {"status": "ACQUIRED"}},
            )
        self.assertIn("acquisition_run must be an AcquisitionRun instance", str(ctx.exception))

        # Duck-typed class attempting to confer metadata authority
        class ForgedRun:
            def summary(self):
                return {"status": "ACQUIRED", "candidate_count": 999}

            def candidates_for(self, subject):
                return [{"source_id": "eu_ecb_fx_reference"}]

        with self.assertRaises(SourceObservationError) as ctx2:
            v3.v4.build_with_market_quality_degradation(
                sample_top20, {}, {}, sample_policy, {}, False,
                acquisition_run=ForgedRun(),
            )
        self.assertIn("acquisition_run must be an AcquisitionRun instance", str(ctx2.exception))

    def test_05_actual_wrapper_and_original_builder_executed_not_spy(self) -> None:
        """Genuine wrapper and genuine original builder execute with exact identity forwarded by keyword."""
        wrapper_calls: list[tuple[tuple, dict]] = []
        original_calls: list[tuple[tuple, dict]] = []

        real_wrapper = v3.v4.build_with_market_quality_degradation
        real_original = v3.v4._original_build

        def tracking_wrapper(*args, **kwargs):
            wrapper_calls.append((args, kwargs))
            return real_wrapper(*args, **kwargs)

        def tracking_original(*args, **kwargs):
            original_calls.append((args, kwargs))
            return real_original(*args, **kwargs)

        with tempfile.TemporaryDirectory() as td:
            paths, hashes_before = make_env_files(Path(td), make_top20())
            with patch.object(v3.v4.gate, "build", side_effect=tracking_wrapper), \
                 patch.object(v3.v4, "_original_build", side_effect=tracking_original):
                code, out, requested_urls = self.run_v3_cli(paths, extra_args=["--acquire-public"])

            self.assertEqual(code, 0)
            self.assertEqual(len(wrapper_calls), 1)
            self.assertEqual(len(original_calls), 1)

            wrapper_kw = wrapper_calls[0][1]
            original_kw = original_calls[0][1]

            self.assertIn("acquisition_run", wrapper_kw)
            self.assertIn("acquisition_run", original_kw)

            # Exact object identity forwarding
            ar = wrapper_kw["acquisition_run"]
            self.assertIsInstance(ar, AcquisitionRun)
            self.assertIs(ar, original_kw["acquisition_run"])

            # Verify genuine transformations from both core builder and wrapper
            self.assertEqual(out["schema_version"], 3)
            self.assertEqual(out["acquisition_summary"]["status"], "ACQUIRED")
            self.assertTrue(out["macro_reference_context"]["reference_only"])
            self.assertEqual(out["portfolio"]["market_corroboration_status"], "DEGRADED")
            self.assertEqual(out["quality_status"], "FAIL")
            self.assertTrue(out["blocking_violations"])

            for k in ("top20", "report", "order", "policy"):
                self.assertEqual(sha256_file(paths[k]), hashes_before[k])

    def test_06_signature_regression_reproduces_old_type_error(self) -> None:
        """Simulate old wrapper signature to reproduce TypeError before fix and verify fix signature."""
        def unpatched_wrapper(top20, reports, orders, core_policy, cache, offline):
            return {}, {}

        # Reproduce old failure: TypeError: unpatched_wrapper() got an unexpected keyword argument 'acquisition_run'
        with self.assertRaises(TypeError) as ctx:
            unpatched_wrapper([], {}, {}, {}, {}, False, acquisition_run=None)
        self.assertIn("unexpected keyword argument 'acquisition_run'", str(ctx.exception))

        # Verify the fixed wrapper accepts keyword-only acquisition_run=None
        sig = inspect.signature(v3.v4.build_with_market_quality_degradation)
        self.assertIn("acquisition_run", sig.parameters)
        param = sig.parameters["acquisition_run"]
        self.assertEqual(param.kind, inspect.Parameter.KEYWORD_ONLY)
        self.assertIsNone(param.default)


if __name__ == "__main__":
    unittest.main()
