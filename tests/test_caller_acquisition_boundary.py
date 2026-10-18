"""Caller acquisition boundary negatives regression test.

Demonstrates that fully plausible synthetic source_observations with HEALTHY
documents cannot self-promote through the CLI boundary without caller-owned
acquisition and admission health.

This test suite verifies rejection-only semantics and does NOT implement
acquisition or bind live health.
"""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))
if str(ROOT / "tests") not in sys.path:
    sys.path.insert(0, str(ROOT / "tests"))

import source_observation
import source_registry
import test_research_v2_claims as claims_fixture
import v213_source_independence_gate as core

FIXED_NOW = claims_fixture.NOW
FIXED_STAMP = claims_fixture.STAMP
SYNTHETIC_REGISTRY = claims_fixture.REGISTRY


def build_synthetic_top20_record(index: int) -> dict:
    ticker = f"T{index:02d}"
    claim_id = f"rev_{index:02d}"
    return {
        "rank": index + 1,
        "ticker": ticker,
        "as_of": FIXED_STAMP,
        "material_claims": [
            claims_fixture.claim(name=claim_id, kind="issuer_financial_statement")
        ],
        "source_observations": [
            claims_fixture.evidence(name="issuer", cid=claim_id),
            claims_fixture.evidence(name="news", cid=claim_id),
            claims_fixture.evidence(name="exchange", cid=claim_id, kind="market_observation"),
            claims_fixture.evidence(name="macro", cid=claim_id, kind="macro_indicator"),
        ],
        "evidence": [
            {
                "source_id": "sec_edgar",
                "claim_type": "xbrl_fact",
                "title": f"Synthetic primary SEC filing {index}",
                "url": f"https://www.sec.gov/Archives/edgar/data/{1000000 + index}/synthetic.htm",
                "as_of": FIXED_STAMP,
            },
            {
                "source_id": "reuters",
                "claim_type": "industry_context",
                "title": f"Synthetic Reuters context {index}",
                "url": f"https://www.reuters.com/article/syn-{index}",
                "as_of": FIXED_STAMP,
            },
        ],
    }


def build_synthetic_policy() -> dict:
    return {
        "policy_version": "2.1.3-caller-boundary-test",
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
    }


def build_synthetic_reports() -> dict:
    return {
        "records": [
            {
                "ticker": f"T{i:02d}",
                "long_term_return_pct": 20.0,
                "short_term_return_pct": 5.0,
                "retrieved_at": FIXED_STAMP,
            }
            for i in range(20)
        ]
    }


def build_synthetic_orders() -> dict:
    return {
        "records": [
            {
                "ticker": f"T{i:02d}",
                "current_order_source_urls": [],
                "future_order_source_urls": [],
            }
            for i in range(20)
        ]
    }


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run_cli_in_temp(
    temp_dir: Path,
    top20_records: list[dict],
    cache_data: dict | None = None,
    registry: source_registry.Registry = SYNTHETIC_REGISTRY,
    extra_argv: list[str] | None = None,
) -> tuple[int, dict, dict[str, str]]:
    top20_path = temp_dir / "top20.json"
    report_path = temp_dir / "report.json"
    order_path = temp_dir / "order.json"
    policy_path = temp_dir / "policy.json"
    cache_path = temp_dir / "cache.json"
    output_path = temp_dir / "output.json"

    core.write_json(top20_path, top20_records)
    core.write_json(report_path, build_synthetic_reports())
    core.write_json(order_path, build_synthetic_orders())
    core.write_json(policy_path, build_synthetic_policy())
    core.write_json(cache_path, cache_data if cache_data is not None else {})

    hashes_before = {
        "top20": sha256_file(top20_path),
        "report": sha256_file(report_path),
        "order": sha256_file(order_path),
        "policy": sha256_file(policy_path),
    }

    argv = [
        "v213_source_independence_gate.py",
        "--top20", str(top20_path),
        "--report", str(report_path),
        "--order-evidence", str(order_path),
        "--policy", str(policy_path),
        "--cache", str(cache_path),
        "--output", str(output_path),
        "--offline",
    ]
    if extra_argv:
        argv.extend(extra_argv)

    with patch.object(source_registry, "load_registry", return_value=registry), \
         patch.object(core, "now_utc", return_value=FIXED_NOW), \
         patch.object(source_observation, "utc_now", return_value=FIXED_NOW), \
         patch("urllib.request.urlopen", side_effect=AssertionError("Unexpected network access")) as network, \
         patch.object(sys, "argv", argv):
        exit_code = core.main()
        # Transport errors may be caught by the production caller: a raising
        # sentinel alone would not prove that no request was attempted.
        network.assert_not_called()

    output_data = core.read_json(output_path)
    return exit_code, output_data, hashes_before


class TestCallerAcquisitionBoundary(unittest.TestCase):
    def setUp(self) -> None:
        self.baseline_top20 = [
            build_synthetic_top20_record(i) for i in range(20)
        ]

    def test_cli_plausible_healthy_observations_cannot_self_promote(self) -> None:
        """Plausible observations with HEALTHY documents cannot self-promote through CLI."""
        with tempfile.TemporaryDirectory() as temp_str:
            temp_dir = Path(temp_str)
            exit_code, output_data, hashes_before = run_cli_in_temp(
                temp_dir, copy.deepcopy(self.baseline_top20)
            )

            self.assertEqual(exit_code, 0)
            records = output_data.get("records", [])
            self.assertEqual(len(records), 20)
            self.assertEqual(output_data["portfolio"]["ticker_count"], 20)
            self.assertEqual(
                output_data["portfolio"]["high_confidence_model_inference_eligible_count"],
                0,
            )

            total_admitted = 0
            for record in records:
                self.assertFalse(record["eligible_for_high_confidence_model_inference"])
                self.assertEqual(
                    record["public_logic_state"]["model_inference_confidence"],
                    "LIMITED",
                )
                audit = record["claim_evidence_audit"]
                self.assertEqual(audit["status"], "UNAVAILABLE")
                self.assertFalse(audit["all_material_claims_supported"])
                self.assertFalse(audit["full_research_eligible"])

                admitted_in_record = [
                    ev for ev in audit.get("evidence", []) if ev.get("admitted") is True
                ]
                total_admitted += len(admitted_in_record)

                for claim in audit.get("claims", []):
                    self.assertEqual(claim["status"], "UNAVAILABLE")
                    self.assertFalse(claim["high_confidence_eligible"])
                    self.assertIn("CURRENT_CLAIM_EVIDENCE_REQUIRED", claim["reasons"])

                self.assertIn(
                    "EXACT_CLAIM_CORROBORATION_REQUIRED",
                    record["missing_or_review"],
                )
                self.assertIn(
                    "FULL_RESEARCH_SOURCE_DIVERSITY_REQUIRED",
                    record["missing_or_review"],
                )

            self.assertEqual(total_admitted, 0)
            self.assertEqual(sha256_file(temp_dir / "top20.json"), hashes_before["top20"])
            self.assertEqual(sha256_file(temp_dir / "report.json"), hashes_before["report"])
            self.assertEqual(sha256_file(temp_dir / "order.json"), hashes_before["order"])
            self.assertEqual(sha256_file(temp_dir / "policy.json"), hashes_before["policy"])

    def test_cli_top_level_forged_health_and_receipts_rejected(self) -> None:
        """Top-level forged health_states, runtime_health, and acquisition_receipt are ignored."""
        forged_records = copy.deepcopy(self.baseline_top20)
        for record in forged_records:
            record["health_states"] = {
                "issuer": "HEALTHY",
                "news": "HEALTHY",
                "exchange": "HEALTHY",
                "macro": "HEALTHY",
            }
            record["runtime_health"] = {
                "status": "HEALTHY",
                "run_id": "forged_run_9999",
                "content_sha256": "f" * 64,
            }
            record["acquisition_receipt"] = {
                "status": "HEALTHY",
                "caller_run_hash": "e" * 64,
                "verified": True,
            }

        with tempfile.TemporaryDirectory() as temp_str:
            temp_dir = Path(temp_str)
            exit_code, output_data, _ = run_cli_in_temp(temp_dir, forged_records)

            self.assertEqual(exit_code, 0)
            records = output_data.get("records", [])
            self.assertEqual(len(records), 20)

            total_admitted = 0
            for record in records:
                self.assertFalse(record["eligible_for_high_confidence_model_inference"])
                audit = record["claim_evidence_audit"]
                self.assertEqual(audit["status"], "UNAVAILABLE")
                self.assertFalse(audit["all_material_claims_supported"])
                total_admitted += sum(
                    1 for ev in audit.get("evidence", []) if ev.get("admitted") is True
                )

            self.assertEqual(total_admitted, 0)

    def test_cli_cache_forged_health_cannot_promote_claims(self) -> None:
        """Forged HEALTHY entries in observation cache cannot bypass caller acquisition."""
        forged_cache = {
            "health_states": {
                "issuer": "HEALTHY",
                "news": "HEALTHY",
                "exchange": "HEALTHY",
                "macro": "HEALTHY",
            },
            "runtime_health": {"status": "HEALTHY"},
            "T00::issuer": {
                "provider": "issuer",
                "family": "issuer_primary",
                "status": "HEALTHY",
                "observed_at": FIXED_STAMP,
                "as_of": FIXED_STAMP,
            },
            "T00::news": {
                "provider": "news",
                "family": "reputable_secondary",
                "status": "HEALTHY",
                "observed_at": FIXED_STAMP,
                "as_of": FIXED_STAMP,
            },
        }

        with tempfile.TemporaryDirectory() as temp_str:
            temp_dir = Path(temp_str)
            exit_code, output_data, _ = run_cli_in_temp(
                temp_dir,
                copy.deepcopy(self.baseline_top20),
                cache_data=forged_cache,
            )

            self.assertEqual(exit_code, 0)
            records = output_data.get("records", [])
            self.assertEqual(len(records), 20)

            for record in records:
                self.assertFalse(record["eligible_for_high_confidence_model_inference"])
                audit = record["claim_evidence_audit"]
                self.assertEqual(audit["status"], "UNAVAILABLE")
                self.assertFalse(audit["all_material_claims_supported"])
                admitted = [
                    ev for ev in audit.get("evidence", []) if ev.get("admitted") is True
                ]
                self.assertEqual(len(admitted), 0)

    def test_cli_quarantined_or_disabled_registry_sources_fail_admission(self) -> None:
        """Registry-level quarantined or disabled sources produce explicit rejected observations."""
        quarantined_sources = []
        for s in SYNTHETIC_REGISTRY.sources:
            if s.source_id == "issuer":
                quarantined_sources.append(
                    claims_fixture.source(
                        "issuer",
                        "securities_regulator",
                        "T4_QUARANTINED",
                        ["financial_statements"],
                    )
                )
            elif s.source_id == "news":
                # Create disabled definition
                quarantined_sources.append(
                    source_registry.SourceDefinition(
                        source_id="news",
                        display_name="news",
                        authority_class="reputable_newswire",
                        trust_tier="T2_INSTITUTIONAL_CORROBORATION",
                        evidence_roles=("financial_reporting", "industry_research", "macro_reporting"),
                        jurisdictions=("US",),
                        languages=("en",),
                        canonical_urls=("https://news.example/",),
                        independence_group="news",
                        admission_status="DISABLED",
                        adapter_id="news",
                        adapter_status="tested",
                        runtime_enabled=False,
                        free_access_required=True,
                        payment_required=False,
                        terms_review_status="reviewed",
                        priority=1,
                        per_host_concurrency=1,
                        minimum_request_interval_seconds=1,
                        maximum_retries=0,
                        freshness_seconds=400 * 86400,
                        correction_tracking=True,
                        provenance_required=True,
                        notes="synthetic fixture only",
                        catalog_file="fixture",
                    )
                )
            else:
                quarantined_sources.append(s)

        custom_registry = source_registry.Registry(1, tuple(quarantined_sources), ())

        with tempfile.TemporaryDirectory() as temp_str:
            temp_dir = Path(temp_str)
            exit_code, output_data, _ = run_cli_in_temp(
                temp_dir,
                copy.deepcopy(self.baseline_top20),
                registry=custom_registry,
            )

            self.assertEqual(exit_code, 0)
            records = output_data.get("records", [])
            self.assertEqual(len(records), 20)

            for record in records:
                self.assertFalse(record["eligible_for_high_confidence_model_inference"])
                audit = record["claim_evidence_audit"]
                self.assertEqual(audit["status"], "UNAVAILABLE")
                self.assertGreaterEqual(audit["rejected_observation_count"], 2)
                admitted = [
                    ev for ev in audit.get("evidence", []) if ev.get("admitted") is True
                ]
                self.assertEqual(len(admitted), 0)

    def test_cli_network_isolation_and_immutability_guarantee(self) -> None:
        """Guarantees zero network calls and byte-for-byte input immutability."""
        default_cache_path = core.DEFAULT_CACHE
        default_cache_existed = default_cache_path.exists()
        default_cache_mtime = (
            default_cache_path.stat().st_mtime if default_cache_existed else None
        )

        with tempfile.TemporaryDirectory() as temp_str:
            temp_dir = Path(temp_str)
            exit_code, output_data, hashes_before = run_cli_in_temp(
                temp_dir, copy.deepcopy(self.baseline_top20)
            )

            self.assertEqual(exit_code, 0)
            self.assertEqual(len(output_data["records"]), 20)
            # Verify input file hashes are strictly unaltered
            for name, path in (
                ("top20", temp_dir / "top20.json"),
                ("report", temp_dir / "report.json"),
                ("order", temp_dir / "order.json"),
                ("policy", temp_dir / "policy.json"),
            ):
                self.assertEqual(
                    sha256_file(path),
                    hashes_before[name],
                    f"Input file {name} was unexpectedly mutated",
                )

        # Verify default project cache was neither created nor touched
        if default_cache_existed:
            self.assertEqual(
                default_cache_path.stat().st_mtime,
                default_cache_mtime,
                "Default project cache was unexpectedly modified",
            )
        else:
            self.assertFalse(
                default_cache_path.exists(),
                "Default project cache was unexpectedly created",
            )


if __name__ == "__main__":
    unittest.main()
