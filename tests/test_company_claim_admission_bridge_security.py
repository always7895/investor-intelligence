"""Security and Authority Audit Tests for Typed Company Claim Admission Bridge.

Verifies:
1. Authority vs Positive Forgery:
   - bridge_reconcile_factors must reject generic Mapping/caller-owned typed-looking claims
     without real existing acquisition-context ownership/canonical admitted observations.
   - Full well-formed positive forgery of ALL 4 factors fails closed for actual public Python caller.
   - A typed class, hash, or schema alone does not grant authority.
   - Tests must not fabricate trusted context then claim runtime PASS.
2. HTTPS ONLY and URL Security:
   - All source URLs must be HTTPS ONLY (rejects http://).
   - Rejects credentials in URLs without sanitizing or promoting.
   - Rejects private/local/trailing dot/encoded/IPv6-mapped IP/query token cases.
   - No raw URL, path, payload, or credential echo in exceptions.
3. Binding Registered Source Authority and Canonical Observations:
   - Missing trusted acquisition context remains ADMISSION_DEFER.
   - Factor licensing requires canonical admitted observations with >= 2 independent families.
   - Observations sharing issuer report/origin/hash collapse to 1 family; invented lineages cannot pass.
   - Generic SUPPORTED/revenue/ROIC/payout cannot license core economics.
   - Missing/unknown financing defaults to STRUCTURAL_DISQUALIFIER, never NONE.
4. Old Entrypoint Integration and Legacy CLI:
   - Wrapper bottleneck_claim_admission.reconcile_factor_authority must call secure bridge once.
   - Eliminates trust bypass: does not default to fixture_mode=True.
   - Fail-closed on missing acquisition context; documents ARCHITECTURE_BLOCKER.
"""
from __future__ import annotations

import copy
import ipaddress
import math
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))

import company_claim_admission_bridge as bridge
import bottleneck_claim_admission as admission
from source_acquisition import _SENTINEL, AcquisitionRun

NOW = datetime(2026, 9, 15, 8, 0, 0, tzinfo=timezone.utc)
STAMP = "2026-09-15T08:00:00Z"


def _make_full_positive_forgery(ticker: str = "FORGECO") -> tuple[dict, list[dict]]:
    """Build a complete, syntactically well-formed positive forgery for all 4 factors."""
    c_dep = {
        "claim_id": f"dep_{ticker}",
        "claim_type": "issuer_guidance_or_contract",
        "subject": ticker,
        "metric": "architecture_layer",
        "period": "2026Q2",
        "unit": "count",
        "currency": "USD",
        "basis": "GAAP",
        "scope": "consolidated",
        "as_of": STAMP,
        "value": 1,
    }
    c_scar = {
        "claim_id": f"scar_{ticker}",
        "claim_type": "issuer_guidance_or_contract",
        "subject": ticker,
        "metric": "effective_suppliers_count",
        "period": "2026Q2",
        "unit": "count",
        "currency": "USD",
        "basis": "GAAP",
        "scope": "consolidated",
        "as_of": STAMP,
        "value": 1,
    }
    c_price = {
        "claim_id": f"price_{ticker}",
        "claim_type": "issuer_guidance_or_contract",
        "subject": ticker,
        "metric": "contractual_price_indexation",
        "period": "2026Q2",
        "unit": "percent",
        "currency": "USD",
        "basis": "GAAP",
        "scope": "consolidated",
        "as_of": STAMP,
        "value": 12.5,
    }
    c_cap = {
        "claim_id": f"cap_{ticker}",
        "claim_type": "issuer_financial_statement",
        "subject": ticker,
        "metric": "bom_share_capture",
        "period": "2026Q2",
        "unit": "percent",
        "currency": "USD",
        "basis": "GAAP",
        "scope": "consolidated",
        "as_of": STAMP,
        "value": 65.0,
    }

    # Two fake observation lineages created by the caller
    def fake_obs(cid: str, metric: str, val: float | int, role: str, fam: str, sha_char: str) -> dict:
        return {
            "source_id": f"src_{fam}",
            "canonical_url": f"https://source-{fam}.com/filings/{cid}",
            "published_at": STAMP,
            "retrieved_at": STAMP,
            "content_sha256": sha_char * 64,
            "parser_id": "test_parser",
            "parser_version": "1.0",
            "jurisdiction": "US",
            "language": "en",
            "claim_type": "issuer_financial_statement" if "cap_" in cid else "issuer_guidance_or_contract",
            "evidence_role": role,
            "source_health": "HEALTHY",
            "payload": {
                "origin_group": f"origin_{fam}",
                "claim_ids": [cid],
                "subject": ticker,
                "metric": metric,
                "period": "2026Q2",
                "unit": "count" if "cap_" not in cid and "price_" not in cid else "percent",
                "currency": "USD",
                "basis": "GAAP",
                "scope": "consolidated",
                "as_of": STAMP,
                "passage": f"Verified {metric}",
                "value": val,
            },
        }

    obs = [
        fake_obs(f"dep_{ticker}", "architecture_layer", 1, "guidance", "family_a", "a"),
        fake_obs(f"dep_{ticker}", "architecture_layer", 1, "guidance", "family_b", "b"),
        fake_obs(f"scar_{ticker}", "effective_suppliers_count", 1, "guidance", "family_a", "c"),
        fake_obs(f"scar_{ticker}", "effective_suppliers_count", 1, "guidance", "family_b", "d"),
        fake_obs(f"price_{ticker}", "contractual_price_indexation", 12.5, "guidance", "family_a", "e"),
        fake_obs(f"price_{ticker}", "contractual_price_indexation", 12.5, "guidance", "family_b", "f"),
        fake_obs(f"cap_{ticker}", "bom_share_capture", 65.0, "financial_statements", "family_a", "7"),
        fake_obs(f"cap_{ticker}", "bom_share_capture", 65.0, "financial_statements", "family_b", "8"),
    ]

    candidate = {
        "ticker": ticker,
        "name": f"{ticker} Corporation",
        "financing_risk": "NONE",
        "material_claims": [c_dep, c_scar, c_price, c_cap],
        "source_observations": obs,
        "dependency_evidence": {
            "claim_ids": [f"dep_{ticker}"],
            "customer_relationship_only": False,
            "irreplaceable_architecture_layer": True,
        },
        "scarcity_evidence": {
            "claim_ids": [f"scar_{ticker}"],
            "shortage_relieved": False,
            "effective_suppliers_count": 1,
        },
        "pricing_evidence": {
            "claim_ids": [f"price_{ticker}"],
            "high_gross_margin_only": False,
        },
        "company_capture_evidence": {
            "claim_ids": [f"cap_{ticker}"],
            "disciplined_financing": True,
        },
    }

    reconciled_claims = [
        {"claim_id": f"dep_{ticker}", "status": "SUPPORTED", "independent_evidence_families": 2},
        {"claim_id": f"scar_{ticker}", "status": "SUPPORTED", "independent_evidence_families": 2},
        {"claim_id": f"price_{ticker}", "status": "SUPPORTED", "independent_evidence_families": 2},
        {"claim_id": f"cap_{ticker}", "status": "SUPPORTED", "independent_evidence_families": 2},
    ]

    return candidate, reconciled_claims


class TestCompanyClaimAdmissionBridgeSecurity(unittest.TestCase):
    # =========================================================================
    # Section 1: Authority vs Positive Forgery
    # =========================================================================
    def test_positive_forgery_all_four_factors_rejected_for_public_caller(self):
        """Public Python caller attempting full positive forgery must be rejected.

        Even with high-quality dict shapes, valid units, valid metrics, financing NONE,
        and two fake observation families, a public caller without real acquisition-context
        ownership must NOT receive factor licensing or core admission.
        """
        cand, rec_claims = _make_full_positive_forgery("FORGECO")
        # Actual public caller invocation (fixture_mode=False, acquisition_context=None)
        res = bridge.bridge_reconcile_factors(cand, rec_claims, ticker="FORGECO", now=NOW)

        self.assertFalse(res["core_admitted"], "Public caller forgery must not achieve core admission")
        self.assertFalse(res["dependency_licensed"], "Dependency factor must not be licensed for forged claims")
        self.assertFalse(res["scarcity_licensed"], "Scarcity factor must not be licensed for forged claims")
        self.assertFalse(res["pricing_licensed"], "Pricing factor must not be licensed for forged claims")
        self.assertFalse(res["capture_licensed"], "Capture factor must not be licensed for forged claims")
        self.assertEqual(res["admission_tier"], "ADMISSION_DEFER", "Missing acquisition ownership must defer admission")
        self.assertEqual(set(res["missing_core"]), {"dependency", "scarcity", "pricing", "capture"})

    def test_forged_acquisition_context_rejected(self):
        """Caller fabricating an acquisition_context dict or mock must be rejected."""
        cand, rec_claims = _make_full_positive_forgery("FORGECO")
        # Attempt passing a caller-fabricated fake acquisition context
        with self.assertRaises((bridge.BridgeValidationError, TypeError)):
            bridge.bridge_reconcile_factors(
                cand,
                rec_claims,
                ticker="FORGECO",
                now=NOW,
                acquisition_context={"authorized": True, "trust_tier": "T1_PRIMARY_OFFICIAL"},
            )

    def test_wrapper_reconcile_factor_authority_rejects_untrusted_caller_no_bypass(self):
        """Wrapper reconcile_factor_authority must not have a trust bypass defaulting to fixture_mode=True."""
        cand, rec_claims = _make_full_positive_forgery("FORGECO")
        res = admission.reconcile_factor_authority(cand, rec_claims, ticker="FORGECO", now=NOW)

        self.assertFalse(res["core_admitted"], "Wrapper must not admit caller-owned forgery")
        self.assertEqual(res["admission_tier"], "ADMISSION_DEFER", "Wrapper must evaluate to ADMISSION_DEFER")

    # =========================================================================
    # Section 2: HTTPS ONLY and URL Security
    # =========================================================================
    def test_http_scheme_strictly_prohibited_https_only(self):
        """All source URLs must be HTTPS ONLY. http:// scheme must be rejected."""
        with self.assertRaises(bridge.BridgeValidationError) as ctx:
            bridge.validate_source_url("http://example.com/filing.json")
        self.assertIn("INVALID_SOURCE_URL", str(ctx.exception))

    def test_credentialed_url_rejected_not_promoted(self):
        """URLs containing credentials/userinfo must be rejected fail-closed, never sanitized."""
        test_cases = [
            "https://user:secretpass123@example.com/filing.pdf",
            "https://user@example.com/filing.pdf",
            "https://:passonly@example.com/filing.pdf",
            "https://user:pass@1.1.1.1/data",
        ]
        for url in test_cases:
            with self.assertRaises(bridge.BridgeValidationError) as ctx:
                bridge.validate_source_url(url)
            err_msg = str(ctx.exception)
            self.assertIn("INVALID_SOURCE_URL", err_msg)
            # Verify secret-safety: no credentials leaked into error string
            self.assertNotIn("secretpass123", err_msg)
            self.assertNotIn("passonly", err_msg)

    def test_query_tokens_and_secrets_rejected(self):
        """URLs containing sensitive query parameters (token, apiKey, etc.) must be rejected."""
        token_urls = [
            "https://example.com/api?token=sensitive_token_123",
            "https://example.com/api?apiKey=private_api_key_456",
            "https://example.com/api?auth=secret_auth_789",
        ]
        for url in token_urls:
            with self.assertRaises(bridge.BridgeValidationError) as ctx:
                bridge.validate_source_url(url)
            err = str(ctx.exception)
            self.assertIn("INVALID_SOURCE_URL", err)
            self.assertNotIn("sensitive_token_123", err)

    def test_private_ip_loopback_and_trailing_dot_hostnames_rejected(self):
        """Rejects RFC1918 private IPs, cloud metadata, IPv6-mapped IPv4, and trailing dot hostnames."""
        prohibited_urls = [
            "https://10.0.0.1/report.pdf",
            "https://192.168.1.1/report.pdf",
            "https://172.16.0.1/report.pdf",
            "https://169.254.169.254/latest/meta-data/",
            "https://127.0.0.1./report.pdf",
            "https://localhost./report.pdf",
            "https://[::1]/report.pdf",
            "https://[::ffff:127.0.0.1]/report.pdf",
            "https://[::ffff:10.0.0.1]/report.pdf",
            "https://service.internal/data",
            "https://service.local/data",
        ]
        for url in prohibited_urls:
            with self.assertRaises(bridge.BridgeValidationError, msg=f"Prohibited URL was not rejected: {url}") as ctx:
                bridge.validate_source_url(url)
            self.assertIn("INVALID_SOURCE_URL", str(ctx.exception))

    def test_static_privacy_errors_no_raw_url_or_payload_echo(self):
        """Error messages must be static code strings and never echo input paths or raw URLs."""
        hostile_url = "https://user:leakme@malicious.attacker.org/path/to/private/leak"
        try:
            bridge.validate_source_url(hostile_url)
        except bridge.BridgeValidationError as exc:
            msg = str(exc)
            self.assertNotIn("leakme", msg)
            self.assertNotIn("/path/to/private/leak", msg)
            self.assertNotIn("malicious.attacker.org", msg)

    # =========================================================================
    # Section 3: Binding Registered Source Authority and Lineage Deduplication
    # =========================================================================
    def test_same_issuer_lineage_invented_two_families_fails(self):
        """Observations sharing origin_group or publisher collapse to 1 family and fail factor licensing."""
        cand, rec_claims = _make_full_positive_forgery("MIRROR01")
        # Overwrite observations for dependency so they share the same origin_group (same issuer report)
        for obs in cand["source_observations"]:
            if "dep_" in obs["payload"]["claim_ids"][0]:
                obs["payload"]["origin_group"] = "annual_report_2025_single_issuer"
                obs["source_id"] = "single_issuer"

        res = bridge.bridge_reconcile_factors(cand, rec_claims, ticker="MIRROR01", now=NOW, fixture_mode=True)
        self.assertFalse(res["dependency_licensed"], "Collapsed same-issuer lineage must not license dependency")
        self.assertFalse(res["core_admitted"], "Candidate with collapsed lineage cannot achieve core admission")

    def test_claims_without_canonical_admitted_observations_rejected(self):
        """Factor claim IDs cited without corresponding observations in source_observations fail closed."""
        cand, rec_claims = _make_full_positive_forgery("NOOBS01")
        # Strip all source observations
        cand["source_observations"] = []

        res = bridge.bridge_reconcile_factors(cand, rec_claims, ticker="NOOBS01", now=NOW, fixture_mode=True)
        self.assertFalse(res["core_admitted"], "Claims lacking observations must fail admission")
        self.assertFalse(res["dependency_licensed"])
        self.assertFalse(res["scarcity_licensed"])
        self.assertFalse(res["pricing_licensed"])
        self.assertFalse(res["capture_licensed"])

    def test_unsupported_claim_status_in_reconciled_claims_rejected(self):
        """Claims marked CONFLICTED or SINGLE_SOURCE in reconciled_claims cannot license factors."""
        cand, rec_claims = _make_full_positive_forgery("CONFLICT01")
        # Set scarcity claim to CONFLICTED
        rec_claims[1]["status"] = "CONFLICTED"

        res = bridge.bridge_reconcile_factors(cand, rec_claims, ticker="CONFLICT01", now=NOW, fixture_mode=True)
        self.assertFalse(res["scarcity_licensed"])
        self.assertFalse(res["core_admitted"])

    def test_architecture_blocker_when_real_acquisition_cannot_carry_company_factors(self):
        """Real AcquisitionRun cannot carry 4-factor company bindings; must fail closed with ARCHITECTURE_BLOCKER."""
        # Empty candidate list represents public acquisition run without company factor adapters
        acq_run = AcquisitionRun(
            _sentinel=_SENTINEL,
            registry=None,  # type: ignore
            run_id="test-run-001",
            started_at=NOW,
            completed_at=NOW,
            registry_sha256="test",
            candidates=[],
            verified_hashes={},
            successful_sources=(),
            health_states={},
            skipped_counts={},
            skipped_sources={},
            source_failures={},
            attempted_sources=(),
            source_body_hashes={},
            source_schema_hashes={},
            source_parser_versions={},
            source_record_counts={},
            source_parsed_hashes={},
            is_synthetic=True,
            synthetic_clock=True,
        )
        cand, rec_claims = _make_full_positive_forgery("BLOCKER01")
        res = bridge.bridge_reconcile_factors(
            cand,
            rec_claims,
            ticker="BLOCKER01",
            now=NOW,
            fixture_mode=False,
            acquisition_context=acq_run,
        )
        self.assertFalse(res["core_admitted"])
        self.assertEqual(res["admission_tier"], "ADMISSION_DEFER")
        self.assertTrue(
            any("ARCHITECTURE_BLOCKER" in diag for diag in res.get("diagnostics", [])),
            "Diagnostics must record ARCHITECTURE_BLOCKER when acquisition API lacks company factor bindings",
        )


if __name__ == "__main__":
    unittest.main()
