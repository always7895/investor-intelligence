#!/usr/bin/env python3
"""Deterministic synthetic tests for process-local source acquisition module.

Validates process-local AcquisitionRun capability, eligibility gates, hash
binding, sanitization, and fallback health rules without real network calls.
"""
from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
import hashlib
from pathlib import Path
import sys
import unittest
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))

from adapters.base import ADAPTERS, AdapterError, ParsedBatch, make_batch
from fetch_public_source_observations import ENDPOINTS, MAX_BYTES, fetch_bytes
from source_acquisition import (
    AcquisitionRun,
    acquire_runtime_sources,
    compute_registry_digest,
    safe_canonical_json,
)
from source_health import (
    CIRCUIT_OPEN,
    DEGRADED,
    HEALTHY,
    QUARANTINED,
    SourceHealthState,
    record_failure,
)
from source_registry import Registry, SourceDefinition, load_registry
import test_research_v2_claims as claims_fixture

NOW = datetime(2026, 9, 13, 12, tzinfo=timezone.utc)
STAMP = "2026-09-12T12:00:00+00:00"

BASE_SOURCE = replace(
    claims_fixture.REGISTRY.sources[0],
    adapter_status="implemented",
    terms_review_status="approved",
)
REGISTRY = Registry(1, (BASE_SOURCE,), ())


class FakeAdapter:
    def __init__(
        self,
        source_id: str = "issuer",
        parser_version: str = "1.0.0",
        records: list[dict] | None = None,
        warnings: list[str] | None = None,
        override_batch: ParsedBatch | None = None,
    ) -> None:
        self.source_id = source_id
        self.adapter_id = source_id
        self.parser_version = parser_version
        self._records = records
        self._warnings = warnings or []
        self._override_batch = override_batch

    def parse(
        self,
        content: bytes,
        *,
        content_type: str,
        retrieved_at: str,
        context: dict,
    ) -> ParsedBatch:
        if self._override_batch is not None:
            return self._override_batch
        records = self._records
        if records is None:
            records = [
                {
                    "canonical_url": f"https://{self.source_id}.example/report",
                    "published_at": STAMP,
                    "jurisdiction": "US",
                    "language": "en",
                    "claim_type": "issuer_financial_statement",
                    "evidence_role": "financial_statements",
                    "payload": {
                        "claim_ids": ["revenue"],
                        "subject": "SYN",
                        "metric": "revenue",
                        "period": "2026Q2",
                        "unit": "million",
                        "currency": "USD",
                        "value": 100,
                        "basis": "GAAP",
                        "scope": "consolidated",
                        "as_of": STAMP,
                        "passage": "Synthetic disclosed value, not live evidence.",
                        "origin_group": self.source_id,
                    },
                }
            ]
        return make_batch(
            source_id=self.source_id,
            parser_version=self.parser_version,
            content=content,
            retrieved_at=retrieved_at,
            records=records,
            warnings=list(self._warnings),
        )


class SourceAcquisitionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.endpoint_patch = patch.dict(
            ENDPOINTS, {"issuer": "https://issuer.example/report"}, clear=False
        )
        self.adapter_patch = patch.dict(
            ADAPTERS, {"issuer": FakeAdapter("issuer")}, clear=False
        )
        self.endpoint_patch.start()
        self.adapter_patch.start()

    def tearDown(self) -> None:
        self.adapter_patch.stop()
        self.endpoint_patch.stop()

    def test_01_success_single_source_capture(self) -> None:
        run = acquire_runtime_sources(
            registry=REGISTRY,
            transport=lambda url: b'{"fake": "data"}',
            clock=NOW,
        )
        candidates = run.candidates_for("SYN")
        self.assertEqual(len(candidates), 1)
        row = candidates[0]
        self.assertEqual(row["source_id"], "issuer")
        self.assertEqual(row["payload"]["value"], 100)
        self.assertEqual(run.health_for(row, now=NOW), HEALTHY)
        summary = run.summary()
        self.assertEqual(summary["status"], "ACQUIRED")
        self.assertEqual(summary["candidate_count"], 1)
        self.assertEqual(summary["successful_source_count"], 1)
        self.assertEqual(summary["registry_sha256"], compute_registry_digest(REGISTRY))

    def test_02_mutating_returned_row_fails_hash(self) -> None:
        run = acquire_runtime_sources(
            registry=REGISTRY,
            transport=lambda url: b'{"fake": "data"}',
            clock=NOW,
        )
        row = run.candidates_for("SYN")[0]
        row["source_display_name"] = "MUTATED_DISPLAY_NAME"
        self.assertEqual(run.health_for(row, now=NOW), DEGRADED)
        self.assertEqual(run.health_for("not a dict", now=NOW), DEGRADED)
        row["observation_id"] = "0" * 64
        self.assertEqual(run.health_for(row, now=NOW), DEGRADED)

    def test_03_claim_value_subject_mutation(self) -> None:
        run = acquire_runtime_sources(
            registry=REGISTRY,
            transport=lambda url: b'{"fake": "data"}',
            clock=NOW,
        )
        base = run.candidates_for("SYN")[0]

        mutated_val = dict(base)
        mutated_val["payload"] = dict(base["payload"], value=999)
        self.assertEqual(run.health_for(mutated_val, now=NOW), DEGRADED)

        mutated_subj = dict(base)
        mutated_subj["payload"] = dict(base["payload"], subject="MUTATED")
        self.assertEqual(run.health_for(mutated_subj, now=NOW), DEGRADED)

        mutated_cids = dict(base)
        mutated_cids["payload"] = dict(base["payload"], claim_ids=["other"])
        self.assertEqual(run.health_for(mutated_cids, now=NOW), DEGRADED)

    def test_04_freshness_future_and_expired(self) -> None:
        run = acquire_runtime_sources(
            registry=REGISTRY,
            transport=lambda url: b'{"fake": "data"}',
            clock=NOW,
        )
        row = run.candidates_for("SYN")[0]
        self.assertEqual(
            run.health_for(row, now=NOW + timedelta(minutes=16)), DEGRADED
        )
        self.assertEqual(
            run.health_for(row, now=NOW - timedelta(seconds=1)), DEGRADED
        )
        self.assertEqual(
            run.health_for(row, now=datetime(2026, 9, 13, 12, 0, 0)), DEGRADED
        )

    def test_05_saved_dict_cannot_construct(self) -> None:
        with self.assertRaises(TypeError):
            AcquisitionRun(registry=REGISTRY, run_id="invalid")  # type: ignore[call-arg]
        self.assertFalse(hasattr(AcquisitionRun, "from_dict"))
        with self.assertRaises(TypeError):
            acquire_runtime_sources(
                registry=REGISTRY,
                prior_states={"issuer": {"status": HEALTHY}},  # type: ignore[arg-type]
                clock=NOW,
            )

    def test_06_skipped_disabled_no_network(self) -> None:
        disabled = replace(BASE_SOURCE, runtime_enabled=False)
        transport_mock = MagicMock()
        run = acquire_runtime_sources(
            registry=Registry(1, (disabled,), ()),
            transport=transport_mock,
            clock=NOW,
        )
        transport_mock.assert_not_called()
        self.assertEqual(run.summary()["status"], "UNAVAILABLE")
        self.assertEqual(
            run.summary()["skipped_sources"]["issuer"], "NOT_RUNTIME_ENABLED"
        )

    def test_07_terms_and_payment_rejection(self) -> None:
        cases = [
            (replace(BASE_SOURCE, terms_review_status="pending"), "TERMS_NOT_APPROVED"),
            (replace(BASE_SOURCE, payment_required=True), "PAYMENT_REQUIRED"),
            (replace(BASE_SOURCE, free_access_required=False), "FREE_ACCESS_NOT_REQUIRED"),
            (replace(BASE_SOURCE, provenance_required=False), "PROVENANCE_NOT_REQUIRED"),
            (replace(BASE_SOURCE, trust_tier="T4_QUARANTINED"), "QUARANTINED_TIER"),
        ]
        for source, reason in cases:
            transport_mock = MagicMock()
            run = acquire_runtime_sources(
                registry=Registry(1, (source,), ()),
                transport=transport_mock,
                clock=NOW,
            )
            transport_mock.assert_not_called()
            self.assertEqual(run.summary()["skipped_sources"]["issuer"], reason)

    def test_08_staged_unregistered_adapter_and_no_endpoint_mismatch(self) -> None:
        transport_mock = MagicMock()
        # Missing endpoint
        with patch.dict(ENDPOINTS, {}, clear=True):
            run = acquire_runtime_sources(
                registry=REGISTRY, transport=transport_mock, clock=NOW
            )
            transport_mock.assert_not_called()
            self.assertEqual(
                run.summary()["skipped_sources"]["issuer"], "NO_REGISTERED_ENDPOINT"
            )

        # Unregistered adapter
        with patch.dict(ADAPTERS, {}, clear=True):
            run = acquire_runtime_sources(
                registry=REGISTRY, transport=transport_mock, clock=NOW
            )
            transport_mock.assert_not_called()
            self.assertEqual(
                run.summary()["skipped_sources"]["issuer"], "UNREGISTERED_ADAPTER"
            )

        # Adapter ID mismatch
        mismatched = FakeAdapter("issuer")
        mismatched.adapter_id = "other_adapter"
        with patch.dict(ADAPTERS, {"issuer": mismatched}, clear=True):
            run = acquire_runtime_sources(
                registry=REGISTRY, transport=transport_mock, clock=NOW
            )
            transport_mock.assert_not_called()
            self.assertEqual(
                run.summary()["skipped_sources"]["issuer"], "ADAPTER_ID_MISMATCH"
            )

        # Domain outside canonical
        with patch.dict(ENDPOINTS, {"issuer": "https://malicious.evil/report"}, clear=True):
            run = acquire_runtime_sources(
                registry=REGISTRY, transport=transport_mock, clock=NOW
            )
            transport_mock.assert_not_called()
            self.assertEqual(
                run.summary()["skipped_sources"]["issuer"], "ENDPOINT_DOMAIN_DISALLOWED"
            )

    def test_09_parser_hash_version_source_schema_count_mismatch(self) -> None:
        cases = [
            ("BATCH_PARSER_VERSION_MISMATCH", {"parser_version": "9.9.9"}),
            ("BATCH_SOURCE_ID_MISMATCH", {"source_id": "different"}),
            ("CONTENT_HASH_MISMATCH", {"content_sha256": "0" * 64}),
            ("RECORD_COUNT_MISMATCH", {"record_count": 42}),
            ("SCHEMA_HASH_MISMATCH", {"schema_sha256": "1" * 64}),
        ]
        for expected_code, override_kwargs in cases:
            valid_batch = FakeAdapter().parse(
                b"test", content_type="application/json", retrieved_at=STAMP, context={}
            )
            bad_batch = replace(valid_batch, **override_kwargs)
            with patch.dict(ADAPTERS, {"issuer": FakeAdapter(override_batch=bad_batch)}):
                run = acquire_runtime_sources(
                    registry=REGISTRY,
                    transport=lambda url: b"test",
                    clock=NOW,
                )
                self.assertEqual(len(run.candidates_for("SYN")), 0)
                self.assertEqual(
                    run.summary()["source_diagnostics"]["issuer"]["failure_code"],
                    expected_code,
                )

    def test_10_empty_warnings_invalid_normalized_payload(self) -> None:
        # Warnings
        with patch.dict(ADAPTERS, {"issuer": FakeAdapter(warnings=["PARSER_DEGRADED"])}):
            run = acquire_runtime_sources(
                registry=REGISTRY, transport=lambda url: b"test", clock=NOW
            )
            self.assertEqual(
                run.summary()["source_diagnostics"]["issuer"]["failure_code"],
                "BATCH_WARNINGS",
            )

        # Missing envelope payload
        invalid_record = [{"canonical_url": "https://issuer.example/report"}]
        with patch.dict(ADAPTERS, {"issuer": FakeAdapter(records=invalid_record)}):
            run = acquire_runtime_sources(
                registry=REGISTRY, transport=lambda url: b"test", clock=NOW
            )
            self.assertEqual(
                run.summary()["source_diagnostics"]["issuer"]["failure_code"],
                "NORMALIZATION_FAILED",
            )

    def test_11_transport_sentinel_sanitization(self) -> None:
        def leaking_transport(url: str) -> bytes:
            raise RuntimeError("API_SECRET_TOKEN_XYZ_DO_NOT_LEAK")

        run = acquire_runtime_sources(
            registry=REGISTRY,
            transport=leaking_transport,
            clock=NOW,
        )
        summary_text = str(run.summary())
        self.assertNotIn("API_SECRET_TOKEN_XYZ_DO_NOT_LEAK", summary_text)
        code = run.summary()["source_diagnostics"]["issuer"]["failure_code"]
        self.assertIn(code, {"UNKNOWN_ERROR", "TRANSPORT_FAILED"})
        state = run.health_states["issuer"]
        self.assertNotIn("API_SECRET_TOKEN_XYZ_DO_NOT_LEAK", str(state.last_error_code))

    def test_12_prior_failure_circuit_and_quarantine_no_fetch(self) -> None:
        transport_mock = MagicMock()
        init_state = SourceHealthState.initial("issuer", now=NOW)
        quarantined = replace(init_state, status=QUARANTINED)
        circuit = replace(init_state, status=CIRCUIT_OPEN)

        run_q = acquire_runtime_sources(
            registry=REGISTRY,
            transport=transport_mock,
            prior_states={"issuer": quarantined},
            clock=NOW,
        )
        transport_mock.assert_not_called()
        self.assertEqual(
            run_q.summary()["skipped_sources"]["issuer"], "PROBE_DISALLOWED_QUARANTINED"
        )
        self.assertEqual(run_q.health_for({"source_id": "issuer"}), QUARANTINED)

        run_c = acquire_runtime_sources(
            registry=REGISTRY,
            transport=transport_mock,
            prior_states={"issuer": circuit},
            clock=NOW,
        )
        transport_mock.assert_not_called()
        self.assertEqual(
            run_c.summary()["skipped_sources"]["issuer"], "PROBE_DISALLOWED_CIRCUIT_OPEN"
        )
        self.assertEqual(run_c.health_for({"source_id": "issuer"}), CIRCUIT_OPEN)

    def test_13_explicit_disabled_registry_negative_unavailable(self) -> None:
        real_reg = load_registry()
        disabled_sources = tuple(replace(s, runtime_enabled=False) for s in real_reg.sources)
        disabled_reg = Registry(real_reg.schema_version, disabled_sources, real_reg.catalog_files)
        transport_mock = MagicMock()
        run = acquire_runtime_sources(registry=disabled_reg, transport=transport_mock, clock=NOW)
        transport_mock.assert_not_called()
        self.assertEqual(len(run.candidates_for("SYN")), 0)
        self.assertEqual(run.summary()["status"], "UNAVAILABLE")
        self.assertEqual(run.summary()["candidate_count"], 0)
        self.assertEqual(run.summary()["successful_source_count"], 0)

    def test_default_registry_ecb_runtime_enabled(self) -> None:
        real_reg = load_registry()
        runtime_sources = [s for s in real_reg.sources if s.runtime_enabled]
        self.assertEqual(len(runtime_sources), 1)
        self.assertEqual(runtime_sources[0].source_id, "eu_ecb_fx_reference")
        ecb_data = next(s for s in real_reg.sources if s.source_id == "eu_ecb_data")
        self.assertFalse(ecb_data.runtime_enabled)
        self.assertEqual(ecb_data.freshness_seconds, 1800)

    def test_14_batch_overflow_fails_closed(self) -> None:
        base_record = {
            "canonical_url": "https://issuer.example/report",
            "published_at": STAMP,
            "jurisdiction": "US",
            "language": "en",
            "claim_type": "issuer_financial_statement",
            "evidence_role": "financial_statements",
            "payload": {
                "claim_ids": ["revenue"],
                "subject": "SYN",
                "metric": "revenue",
                "period": "2026Q2",
                "unit": "million",
                "currency": "USD",
                "value": 100,
                "basis": "GAAP",
                "scope": "consolidated",
                "as_of": STAMP,
                "passage": "Synthetic disclosed value.",
                "origin_group": "issuer",
            },
        }
        overflow_records = [base_record for _ in range(101)]
        with patch.dict(ADAPTERS, {"issuer": FakeAdapter(records=overflow_records)}):
            run = acquire_runtime_sources(
                registry=REGISTRY,
                transport=lambda url: b"test",
                clock=NOW,
            )
            self.assertEqual(len(run.candidates_for("SYN")), 0)
            self.assertEqual(
                run.summary()["source_diagnostics"]["issuer"]["failure_code"],
                "BATCH_OVERFLOW",
            )

    def test_15_registry_mutation_invalidates_health(self) -> None:
        run = acquire_runtime_sources(
            registry=REGISTRY,
            transport=lambda url: b'{"fake": "data"}',
            clock=NOW,
        )
        row = run.candidates_for("SYN")[0]
        self.assertEqual(run.health_for(row, now=NOW), HEALTHY)

        # Mutate registry object
        tampered_source = replace(BASE_SOURCE, display_name="TAMPERED")
        tampered_registry = Registry(1, (tampered_source,), ())
        run._registry = tampered_registry
        self.assertEqual(run.health_for(row, now=NOW), DEGRADED)

    def test_16_parser_retrieval_clock_mismatch(self) -> None:
        # RED case 1: parser batch retrieved_at differing from caller retrieval clock is rejected
        batch = FakeAdapter().parse(
            b"test", content_type="application/json", retrieved_at=STAMP, context={}
        )
        with patch.dict(ADAPTERS, {"issuer": FakeAdapter(override_batch=batch)}):
            run = acquire_runtime_sources(
                registry=REGISTRY,
                transport=lambda _: b"test",
                clock=NOW,
            )
            self.assertEqual(len(run.candidates_for("SYN")), 0)
            self.assertEqual(
                run.summary()["source_diagnostics"]["issuer"]["failure_code"],
                "BATCH_RETRIEVAL_TIME_MISMATCH",
            )

    def test_17_prior_state_source_identity_and_types(self) -> None:
        trans = MagicMock(return_value=b"test")
        # RED case 2: Identity mismatch rejected BEFORE transport
        with self.assertRaises(ValueError):
            acquire_runtime_sources(
                registry=REGISTRY,
                transport=trans,
                prior_states={"issuer": SourceHealthState.initial("other", now=NOW)},
                clock=NOW,
            )
        trans.assert_not_called()

        # Bool int rejected
        with self.assertRaises(ValueError):
            bad_success = replace(
                SourceHealthState.initial("issuer", now=NOW), total_successes=True
            )
            acquire_runtime_sources(
                registry=REGISTRY,
                transport=trans,
                prior_states={"issuer": bad_success},
                clock=NOW,
            )
        trans.assert_not_called()

        # Invalid status rejected
        with self.assertRaises(ValueError):
            bad_status = replace(
                SourceHealthState.initial("issuer", now=NOW), status="BOGUS_STATUS"
            )
            acquire_runtime_sources(
                registry=REGISTRY,
                transport=trans,
                prior_states={"issuer": bad_status},
                clock=NOW,
            )
        trans.assert_not_called()

        # Unaware clock in prior state rejected
        with self.assertRaises(ValueError):
            bad_clock = replace(
                SourceHealthState.initial("issuer", now=NOW), updated_at="2026-09-13T12:00:00"
            )
            acquire_runtime_sources(
                registry=REGISTRY,
                transport=trans,
                prior_states={"issuer": bad_clock},
                clock=NOW,
            )
        trans.assert_not_called()

        # No self-initial healthy proof: total_successes == 0 cannot produce HEALTHY in health_for
        run = acquire_runtime_sources(
            registry=REGISTRY,
            transport=lambda url: b'{"fake": "data"}',
            clock=NOW,
        )
        row = run.candidates_for("SYN")[0]
        unproven_state = replace(run._health_states["issuer"], total_successes=0)
        run._health_states["issuer"] = unproven_state
        self.assertEqual(run.health_for(row, now=NOW), DEGRADED)

    def test_18_cross_run_candidate_hash_uniqueness(self) -> None:
        # RED case 3: candidate from run1 rejected by run2 even at same clock
        run1 = acquire_runtime_sources(
            registry=REGISTRY, transport=lambda _: b"test", clock=NOW
        )
        run2 = acquire_runtime_sources(
            registry=REGISTRY, transport=lambda _: b"test", clock=NOW
        )
        cand1 = run1.candidates_for("SYN")[0]
        cand2 = run2.candidates_for("SYN")[0]
        self.assertEqual(cand1["acquisition_run_id"], run1.run_id)
        self.assertNotIn("run_id", cand1)

        self.assertNotEqual(run2.health_for(cand1, now=NOW), HEALTHY)
        self.assertEqual(run2.health_for(cand1, now=NOW), DEGRADED)

        # Candidate from run2 must be rejected by run1
        self.assertNotEqual(run1.health_for(cand2, now=NOW), HEALTHY)
        self.assertEqual(run1.health_for(cand2, now=NOW), DEGRADED)

        # Tampered candidate with mismatched acquisition_run_id is also degraded
        tampered = dict(cand2, acquisition_run_id=run1.run_id)
        self.assertEqual(run2.health_for(tampered, now=NOW), DEGRADED)

    def test_19_endpoint_canonicalization_and_url_validation(self) -> None:
        cases = [
            ("http://issuer.example/report", "http scheme disallowed"),
            ("https://user:pass@issuer.example/report", "userinfo disallowed"),
            ("https://issuer.example:8080/report", "nonstandard port disallowed"),
        ]
        for bad_url, label in cases:
            with self.subTest(label=label):
                trans_mock = MagicMock()
                with patch.dict(ENDPOINTS, {"issuer": bad_url}, clear=True):
                    run = acquire_runtime_sources(
                        registry=REGISTRY, transport=trans_mock, clock=NOW
                    )
                    trans_mock.assert_not_called()
                    self.assertEqual(
                        run.summary()["skipped_sources"]["issuer"],
                        "ENDPOINT_INVALID_URL",
                    )

    def test_20_malformed_batch_records_schema_validation_failed(self) -> None:
        bad_batch = ParsedBatch(
            source_id="issuer",
            parser_version="1.0.0",
            retrieved_at=NOW.isoformat(),
            content_sha256=hashlib.sha256(b"test").hexdigest(),
            schema_sha256="0" * 64,
            record_count=1,
            records=("not-a-dict",),  # type: ignore[arg-type]
        )
        with patch.dict(ADAPTERS, {"issuer": FakeAdapter(override_batch=bad_batch)}):
            run = acquire_runtime_sources(
                registry=REGISTRY,
                transport=lambda url: b"test",
                clock=NOW,
            )
            self.assertEqual(len(run.candidates_for("SYN")), 0)
            diag = run.summary()["source_diagnostics"]["issuer"]
            self.assertEqual(diag["status"], "FAILED")
            self.assertEqual(diag["failure_code"], "SCHEMA_VALIDATION_FAILED")
            self.assertEqual(
                run.health_states["issuer"].last_error_code, "SCHEMA_VALIDATION_FAILED"
            )

    def test_21_hostile_raw_values_fail_degraded(self) -> None:
        run = acquire_runtime_sources(
            registry=REGISTRY,
            transport=lambda url: b'{"fake": "data"}',
            clock=NOW,
        )
        base = run.candidates_for("SYN")[0]

        # NaN float value
        nan_dict = dict(base, hostile_nan=float("nan"))
        self.assertEqual(run.health_for(nan_dict, now=NOW), DEGRADED)

        # Circular reference
        cycle_dict = dict(base)
        cycle_dict["self"] = cycle_dict
        self.assertEqual(run.health_for(cycle_dict, now=NOW), DEGRADED)

        # Mixed unorderable keys in json
        unorderable = dict(base)
        unorderable[123] = "mixed_int_key"  # type: ignore[index]
        self.assertEqual(run.health_for(unorderable, now=NOW), DEGRADED)

    def test_22_stale_observation_rejected(self) -> None:
        # Source with 60s freshness policy
        stale_source = replace(BASE_SOURCE, freshness_seconds=60)
        stale_registry = Registry(1, (stale_source,), ())
        run = acquire_runtime_sources(
            registry=stale_registry,
            transport=lambda url: b'{"fake": "data"}',
            clock=NOW,
        )
        self.assertEqual(len(run.candidates_for("SYN")), 0)
        diag = run.summary()["source_diagnostics"]["issuer"]
        self.assertEqual(diag["failure_code"], "STALE_OBSERVATION")

        # Stale row explicitly evaluated in health_for returns DEGRADED
        run_ok = acquire_runtime_sources(
            registry=REGISTRY,
            transport=lambda url: b'{"fake": "data"}',
            clock=NOW,
        )
        cand = run_ok.candidates_for("SYN")[0]
        cand_stale = dict(cand, freshness_status="STALE")
        self.assertEqual(run_ok.health_for(cand_stale, now=NOW), DEGRADED)

    def test_23_clock_order_callable_and_live_authority_gate(self) -> None:
        t0 = NOW
        t1 = NOW + timedelta(seconds=1)
        t2 = NOW + timedelta(seconds=2)
        times = iter([t0, t1, t2])
        run = acquire_runtime_sources(
            registry=REGISTRY,
            transport=lambda url: b'{"fake": "data"}',
            clock=lambda: next(times),
        )
        summary = run.summary()
        self.assertEqual(summary["started_at"], t0.isoformat())
        self.assertEqual(summary["completed_at"], t2.isoformat())
        self.assertEqual(summary["transport_mode"], "INJECTED_TEST_TRANSPORT")
        self.assertTrue(summary["synthetic"])
        self.assertFalse(summary["release_qualified"])
        self.assertFalse(summary["live_proof"])
        self.assertTrue(summary["synthetic_clock"])

        # Live authority gate: fixed datetime without injected synthetic transport is rejected
        with self.assertRaises(ValueError):
            acquire_runtime_sources(registry=REGISTRY, clock=NOW)

    def test_24_registry_schema_version_and_parsed_record_hashes(self) -> None:
        run = acquire_runtime_sources(
            registry=REGISTRY,
            transport=lambda url: b'{"fake": "data"}',
            clock=NOW,
        )
        summary = run.summary()
        issuer_diag = summary["source_diagnostics"]["issuer"]
        self.assertIn("parsed_record_hashes", issuer_diag)
        self.assertEqual(len(issuer_diag["parsed_record_hashes"]), 1)
        self.assertIn("record_hashes", issuer_diag)

        # Mutate schema_version in registry
        row = run.candidates_for("SYN")[0]
        self.assertEqual(run.health_for(row, now=NOW), HEALTHY)
        tampered_registry = Registry(2, REGISTRY.sources, REGISTRY.catalog_files)
        run._registry = tampered_registry
        self.assertEqual(run.health_for(row, now=NOW), DEGRADED)

    def test_25_freshness_unset_and_payload_bounds_and_batch_types(self) -> None:
        # FRESHNESS_POLICY_UNSET: source without freshness_seconds fails closed
        unset_source = replace(BASE_SOURCE, freshness_seconds=None)
        unset_registry = Registry(1, (unset_source,), ())
        run_unset = acquire_runtime_sources(
            registry=unset_registry,
            transport=lambda url: b'{"fake": "data"}',
            clock=NOW,
        )
        self.assertEqual(len(run_unset.candidates_for("SYN")), 0)
        self.assertEqual(
            run_unset.summary()["source_diagnostics"]["issuer"]["failure_code"],
            "FRESHNESS_POLICY_UNSET",
        )

        # Row with freshness_status != "CURRENT" is not healthy
        run_ok = acquire_runtime_sources(
            registry=REGISTRY,
            transport=lambda url: b'{"fake": "data"}',
            clock=NOW,
        )
        cand = run_ok.candidates_for("SYN")[0]
        cand_unset = dict(cand, freshness_status="FRESHNESS_POLICY_UNSET")
        self.assertEqual(run_ok.health_for(cand_unset, now=NOW), DEGRADED)

        # Reject payload > MAX_BYTES
        run_large = acquire_runtime_sources(
            registry=REGISTRY,
            transport=lambda url: b"x" * (MAX_BYTES + 1),
            clock=NOW,
        )
        self.assertEqual(len(run_large.candidates_for("SYN")), 0)
        self.assertEqual(
            run_large.summary()["source_diagnostics"]["issuer"]["failure_code"],
            "PAYLOAD_TOO_LARGE",
        )

        # Reject empty and non-bytes payload
        run_empty = acquire_runtime_sources(
            registry=REGISTRY,
            transport=lambda url: b"",
            clock=NOW,
        )
        self.assertEqual(
            run_empty.summary()["source_diagnostics"]["issuer"]["failure_code"],
            "EMPTY_PAYLOAD",
        )
        run_nonbytes = acquire_runtime_sources(
            registry=REGISTRY,
            transport=lambda url: "string_not_bytes",  # type: ignore[arg-type]
            clock=NOW,
        )
        self.assertEqual(
            run_nonbytes.summary()["source_diagnostics"]["issuer"]["failure_code"],
            "EMPTY_PAYLOAD",
        )

        # Batch record_count typed as bool (True) must fail closed
        valid_batch = FakeAdapter().parse(
            b"test", content_type="application/json", retrieved_at=STAMP, context={}
        )
        bool_batch = replace(valid_batch, record_count=True)  # type: ignore[arg-type]
        with patch.dict(ADAPTERS, {"issuer": FakeAdapter(override_batch=bool_batch)}):
            run_bool = acquire_runtime_sources(
                registry=REGISTRY,
                transport=lambda url: b"test",
                clock=NOW,
            )
            self.assertEqual(len(run_bool.candidates_for("SYN")), 0)
            self.assertEqual(
                run_bool.summary()["source_diagnostics"]["issuer"]["failure_code"],
                "RECORD_COUNT_MISMATCH",
            )

        # Non-finite record in batch fails closed
        nan_rec = dict(valid_batch.records[0], nan_val=float("nan"))
        nan_batch = ParsedBatch(
            source_id="issuer",
            parser_version="1.0.0",
            retrieved_at=valid_batch.retrieved_at,
            content_sha256=valid_batch.content_sha256,
            schema_sha256=valid_batch.schema_sha256,
            record_count=1,
            records=(nan_rec,),
        )
        with patch.dict(ADAPTERS, {"issuer": FakeAdapter(override_batch=nan_batch)}):
            run_nan = acquire_runtime_sources(
                registry=REGISTRY,
                transport=lambda url: b"test",
                clock=NOW,
            )
            self.assertEqual(len(run_nan.candidates_for("SYN")), 0)
            self.assertEqual(
                run_nan.summary()["source_diagnostics"]["issuer"]["failure_code"],
                "SCHEMA_VALIDATION_FAILED",
            )

        # Non-dict record in batch fails closed
        nondict_batch = replace(valid_batch, records=(12345,))  # type: ignore[arg-type]
        with patch.dict(ADAPTERS, {"issuer": FakeAdapter(override_batch=nondict_batch)}):
            run_nondict = acquire_runtime_sources(
                registry=REGISTRY,
                transport=lambda url: b"test",
                clock=NOW,
            )
            self.assertEqual(len(run_nondict.candidates_for("SYN")), 0)
            self.assertEqual(
                run_nondict.summary()["source_diagnostics"]["issuer"]["failure_code"],
                "SCHEMA_VALIDATION_FAILED",
            )

    def test_26_same_host_rate_policy_and_budget_exceeded(self) -> None:
        source1 = replace(BASE_SOURCE, source_id="issuer", minimum_request_interval_seconds=2.0)
        source2 = replace(
            BASE_SOURCE,
            source_id="issuer2",
            adapter_id="issuer2",
            display_name="issuer2",
            minimum_request_interval_seconds=5.0,
            canonical_urls=("https://issuer.example/",),
        )
        two_reg = Registry(1, (source1, source2), ())

        endpoints = {
            "issuer": "https://issuer.example/one",
            "issuer2": "https://issuer.example/two",
        }
        issuer2_records = [
            {
                "canonical_url": "https://issuer.example/two",
                "published_at": STAMP,
                "jurisdiction": "US",
                "language": "en",
                "claim_type": "issuer_financial_statement",
                "evidence_role": "financial_statements",
                "payload": {
                    "claim_ids": ["revenue"],
                    "subject": "SYN",
                    "metric": "revenue",
                    "period": "2026Q2",
                    "unit": "million",
                    "currency": "USD",
                    "value": 200,
                    "basis": "GAAP",
                    "scope": "consolidated",
                    "as_of": STAMP,
                    "passage": "Synthetic disclosed value.",
                    "origin_group": "issuer2",
                },
            }
        ]
        adapters = {
            "issuer": FakeAdapter("issuer"),
            "issuer2": FakeAdapter("issuer2", records=issuer2_records),
        }

        # Case A: Sequential fetch on same host honors max(2.0, 5.0) = 5.0s
        sim_time = [100.0]
        sleep_calls = []

        def mock_monotonic() -> float:
            return sim_time[0]

        def mock_sleep(seconds: float) -> None:
            sleep_calls.append(seconds)
            sim_time[0] += seconds

        trans_mock = MagicMock(return_value=b'{"fake": "data"}')

        with patch.dict(ENDPOINTS, endpoints, clear=False), \
             patch.dict(ADAPTERS, adapters, clear=False), \
             patch("time.monotonic", side_effect=mock_monotonic), \
             patch("time.sleep", side_effect=mock_sleep):
            run = acquire_runtime_sources(
                registry=two_reg,
                transport=trans_mock,
                clock=NOW,
            )
            self.assertEqual(trans_mock.call_count, 2)
            self.assertEqual(sleep_calls, [5.0])
            self.assertEqual(run.summary()["candidate_count"], 2)

        # Case B: Rate limiting honored even after failed attempt
        sim_time = [100.0]
        sleep_calls = []
        call_seq = []

        def failing_first_trans(url: str) -> bytes:
            call_seq.append(url)
            if len(call_seq) == 1:
                raise ConnectionError("CONNECTION_FAILED")
            return b'{"fake": "data"}'

        with patch.dict(ENDPOINTS, endpoints, clear=False), \
             patch.dict(ADAPTERS, adapters, clear=False), \
             patch("time.monotonic", side_effect=mock_monotonic), \
             patch("time.sleep", side_effect=mock_sleep):
            run_fail = acquire_runtime_sources(
                registry=two_reg,
                transport=failing_first_trans,
                clock=NOW,
            )
            self.assertEqual(len(call_seq), 2)
            self.assertEqual(sleep_calls, [5.0])
            self.assertEqual(
                run_fail.summary()["source_diagnostics"]["issuer"]["status"],
                "FAILED",
            )
            self.assertEqual(
                run_fail.summary()["source_diagnostics"]["issuer2"]["status"],
                "SUCCESS",
            )

        # Case C: If waiting would exceed budget (900s), reject/skip RUN_BUDGET_EXCEEDED
        source_huge_interval = replace(
            BASE_SOURCE,
            source_id="issuer2",
            adapter_id="issuer2",
            display_name="issuer2",
            minimum_request_interval_seconds=950.0,
            canonical_urls=("https://issuer.example/",),
        )
        budget_reg = Registry(1, (source1, source_huge_interval), ())
        sim_time = [0.0]
        sleep_calls = []
        trans_mock_budget = MagicMock(return_value=b'{"fake": "data"}')

        with patch.dict(ENDPOINTS, endpoints, clear=False), \
             patch.dict(ADAPTERS, adapters, clear=False), \
             patch("time.monotonic", side_effect=mock_monotonic), \
             patch("time.sleep", side_effect=mock_sleep):
            run_budget = acquire_runtime_sources(
                registry=budget_reg,
                transport=trans_mock_budget,
                clock=NOW,
            )
            # Second source was NOT requested because 950s wait > 900s budget
            self.assertEqual(trans_mock_budget.call_count, 1)
            self.assertEqual(
                run_budget.summary()["skipped_sources"]["issuer2"],
                "RUN_BUDGET_EXCEEDED",
            )
            self.assertEqual(
                run_budget.summary()["skipped_source_counts"]["RUN_BUDGET_EXCEEDED"],
                1,
            )

    def test_27_exact_endpoint_retained_and_parser_context(self) -> None:
        target_url = "https://issuer.example/report?format=json&source=api_feed&ref=direct"
        received_urls = []
        received_contexts = []

        class ContextCheckingAdapter(FakeAdapter):
            def parse(
                self,
                content: bytes,
                *,
                content_type: str,
                retrieved_at: str,
                context: dict,
            ) -> ParsedBatch:
                received_contexts.append(dict(context))
                req_url = context.get("request_url")
                if not req_url:
                    raise AdapterError("MISSING_REQUEST_URL_CONTEXT")
                return super().parse(
                    content,
                    content_type=content_type,
                    retrieved_at=retrieved_at,
                    context=context,
                )

        def mock_trans(url: str) -> bytes:
            received_urls.append(url)
            return b'{"fake": "data"}'

        ctx_adapter = ContextCheckingAdapter("issuer")
        with patch.dict(ENDPOINTS, {"issuer": target_url}, clear=False), \
             patch.dict(ADAPTERS, {"issuer": ctx_adapter}, clear=False):
            run = acquire_runtime_sources(
                registry=REGISTRY,
                transport=mock_trans,
                clock=NOW,
            )
            # Exact endpoint bytes preserved for transport (query params not stripped)
            self.assertEqual(len(received_urls), 1)
            self.assertEqual(received_urls[0], target_url)
            # Context provided to reviewed parser
            self.assertEqual(len(received_contexts), 1)
            self.assertEqual(received_contexts[0].get("request_url"), target_url)
            self.assertEqual(run.summary()["candidate_count"], 1)

        # No-context parser missing fields is explicit failure
        with self.assertRaises(AdapterError):
            ctx_adapter.parse(
                b"test",
                content_type="application/json",
                retrieved_at=STAMP,
                context={},
            )


if __name__ == "__main__":
    unittest.main()
