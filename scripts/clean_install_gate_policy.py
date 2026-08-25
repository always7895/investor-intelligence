#!/usr/bin/env python3
"""Static policy for gates that are meaningful inside a release ZIP.

Repository-only gates need Git metadata or CI workflow sources and therefore run
before packaging. Package-compatible gates operate only on files intentionally
included in the verified release payload and are repeated after extraction.
"""
from __future__ import annotations

PACKAGE_COMPATIBLE_GATE_SCRIPTS = (
    "scripts/security_check.py",
    "scripts/kv_namespace_isolation_gate.py",
    "scripts/authoritative_source_catalog.py",
    "scripts/source_diversity_gate.py",
    "scripts/source_claim_coverage_gate.py",
    "scripts/authoritative_adapter_gate.py",
    "scripts/public_options_provider_gate.py",
    "scripts/phase8_fault_injection_gate.py",
    "scripts/release_candidate_gate.py",
)

PACKAGE_COMPATIBLE_TEST_PATTERNS = (
    "test_public_artifact_closed_schema.py",
    "test_authoritative_source_catalog.py",
    "test_replayed_authoritative_adapters.py",
    "test_staged_gleif_ecb_adapters.py",
    "test_source_diversity_gate.py",
    "test_source_claim_coverage_gate.py",
    "test_public_options_provider_gate.py",
    "test_kv_namespace_isolation_gate.py",
    "test_release_candidate_gate.py",
    "test_phase8_fault_injection_gate.py",
)

REPOSITORY_ONLY_GATE_SCRIPTS = (
    "scripts/line_public_boundary_gate.py",
    "scripts/workflow_supply_chain_gate.py",
    "scripts/full_history_privacy_scan.py",
)
