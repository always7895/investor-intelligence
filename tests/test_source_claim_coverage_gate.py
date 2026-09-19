from __future__ import annotations

import copy
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from source_claim_coverage_gate import (  # noqa: E402
    audit_claim_policy,
    load_object,
)


class SourceClaimCoverageGateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.policy = load_object(ROOT / "config" / "source-claim-coverage-policy.json")
        cls.catalog = load_object(ROOT / "config" / "authoritative-source-catalog.json")

    def test_current_claim_policy_is_complete_and_fail_closed(self) -> None:
        findings, summary = audit_claim_policy(self.policy, self.catalog)
        self.assertEqual(findings, [])
        self.assertGreaterEqual(summary["claim_family_count"], 9)
        self.assertGreaterEqual(summary["catalog_source_count"], 90)
        self.assertFalse(summary["automatic_source_activation"])
        self.assertFalse(summary["editorial_primary_evidence"])
        self.assertEqual(summary["conflict_behavior"], "fail_closed")
        self.assertIn("public_option_quote", summary["broker_forbidden_families"])

    def test_rejects_model_override_editorial_primary_and_silent_conflicts(self) -> None:
        for key, value in (
            ("model_may_override_authority", True),
            ("editorial_may_be_primary_evidence", True),
            ("conflicting_material_values_fail_closed", False),
            ("same_content_hash_counts_once", False),
        ):
            policy = copy.deepcopy(self.policy)
            policy[key] = value
            findings, _summary = audit_claim_policy(policy, self.catalog)
            with self.subTest(key=key):
                self.assertTrue(any(key in item for item in findings))

    def test_public_options_must_forbid_broker_derived_evidence(self) -> None:
        policy = copy.deepcopy(self.policy)
        policy["claim_families"]["public_option_quote"][
            "broker_or_account_derived_evidence_allowed"
        ] = True
        findings, _summary = audit_claim_policy(policy, self.catalog)
        self.assertTrue(any("broker/account-derived" in item for item in findings))

    def test_every_material_family_requires_primary_independent_scalar_fields(self) -> None:
        mutations = (
            ("minimum_primary_sources", 0),
            ("minimum_independent_groups", 0),
            ("required_fields", []),
            ("preferred_source_kinds", []),
        )
        for field, value in mutations:
            policy = copy.deepcopy(self.policy)
            policy["claim_families"]["macro_indicator"][field] = value
            findings, _summary = audit_claim_policy(policy, self.catalog)
            with self.subTest(field=field):
                self.assertTrue(any(f"macro_indicator.{field}" in item for item in findings))

    def test_required_claim_family_cannot_be_removed(self) -> None:
        policy = copy.deepcopy(self.policy)
        policy["claim_families"].pop("issuer_financial_statement")
        findings, _summary = audit_claim_policy(policy, self.catalog)
        self.assertTrue(any("required claim families missing" in item for item in findings))

    def test_descriptor_sections_reject_unknown_and_malformed_shapes(self) -> None:
        # Unknown top-level field is still rejected (whitelist preserved).
        policy = copy.deepcopy(self.policy)
        policy["totally_unknown_section"] = {}
        findings, _summary = audit_claim_policy(policy, self.catalog)
        self.assertTrue(any("totally_unknown_section" in item for item in findings))

        # claim_family_semantics: unknown family reference.
        policy = copy.deepcopy(self.policy)
        policy["claim_family_semantics"]["not_a_family"] = {
            "authority_classes": ["central_bank"],
            "evidence_roles": [],
        }
        findings, _summary = audit_claim_policy(policy, self.catalog)
        self.assertTrue(any("not_a_family" in item for item in findings))

        # claim_family_semantics: unknown sub-key.
        policy = copy.deepcopy(self.policy)
        policy["claim_family_semantics"]["macro_indicator"]["bogus_key"] = ["x"]
        findings, _summary = audit_claim_policy(policy, self.catalog)
        self.assertTrue(any("bogus_key" in item for item in findings))

        # claim_family_semantics: blank descriptor filters fail closed.
        policy = copy.deepcopy(self.policy)
        policy["claim_family_semantics"]["macro_indicator"] = {
            "authority_classes": [],
            "evidence_roles": [],
        }
        findings, _summary = audit_claim_policy(policy, self.catalog)
        self.assertTrue(any("must declare authority_classes or evidence_roles" in item for item in findings))

        # claim_family_semantics: non-string array content.
        policy = copy.deepcopy(self.policy)
        policy["claim_family_semantics"]["macro_indicator"]["authority_classes"] = [1, 2]
        findings, _summary = audit_claim_policy(policy, self.catalog)
        self.assertTrue(any("authority_classes must be a string array" in item for item in findings))

        # lane_semantics: unknown sub-key and blank filters.
        policy = copy.deepcopy(self.policy)
        policy["lane_semantics"]["clearing"]["bogus_lane_key"] = []
        policy["lane_semantics"]["blank_lane"] = {"authority_classes": [], "evidence_roles": []}
        findings, _summary = audit_claim_policy(policy, self.catalog)
        self.assertTrue(any("bogus_lane_key" in item for item in findings))
        self.assertTrue(any("lane_semantics.blank_lane" in item for item in findings))

        # Sections are optional: removing both keeps the policy valid.
        policy = copy.deepcopy(self.policy)
        policy.pop("claim_family_semantics")
        policy.pop("lane_semantics")
        findings, _summary = audit_claim_policy(policy, self.catalog)
        self.assertEqual(findings, [])


if __name__ == "__main__":
    unittest.main()
