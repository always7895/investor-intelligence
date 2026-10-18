"""Publication-mode contract v2: structural claim recount (Python side).

Runs the ONE shared vector file that cloud/test/v213-claim-recount.test.ts also runs
against the Worker port, plus the real install-preflight caller (validate_bundle) on
the mixed fixture.
"""
import copy
import hashlib
import json
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import claim_lineage_qualification as shared
import source_observation
import v213_r75_activation_preflight as preflight

FIXTURES = ROOT / "tests" / "fixtures" / "v213-r75-publication-mode"
VECTORS = json.loads((FIXTURES / "claim-recount-vectors.json").read_text(encoding="utf-8-sig"))
MIXED = json.loads((FIXTURES / "mixed.json").read_text(encoding="utf-8-sig"))
POLICY = json.loads((ROOT / "config" / "v213-serenity-evidence-freshness-policy.json").read_text(encoding="utf-8-sig"))


def rewrite(bundle, name, document):
    body = json.dumps(document, ensure_ascii=False, separators=(",", ":"))
    bundle["payloads"][name] = body
    bundle["sha256"][name] = preflight.sha256_text(body)


class ContractV2Test(unittest.TestCase):
    def test_contract_identity_and_threshold_parity(self):
        contract = preflight.CONTRACT
        self.assertEqual(contract["contract_id"], "v213-r75-publication-mode-v2")
        self.assertEqual(contract["supersedes_contract_id"], "v213-r75-publication-mode-v1")
        self.assertEqual(VECTORS["contract_id"], contract["contract_id"])
        recount = contract["claim_recount"]
        self.assertEqual(recount["method"], "STRUCTURAL_ONLY")
        self.assertIs(recount["families_threshold_equals_producer_policy_minimum"], True)
        # The consumer threshold equals the producer policy minimum, stated and checked.
        self.assertEqual(
            contract["thresholds"][recount["families_threshold_key"]],
            POLICY[recount["producer_policy_key"]],
        )
        self.assertEqual(contract["thresholds"]["min_evidence_claim_families"], 2)
        self.assertEqual(recount["vector_file"], "tests/fixtures/v213-r75-publication-mode/claim-recount-vectors.json")

    def test_v1_contract_is_unchanged_history(self):
        raw = (ROOT / "config" / "v213-r75-publication-mode-v1.json").read_bytes()
        self.assertEqual(len(raw), 2247)
        self.assertEqual(hashlib.sha256(raw).hexdigest(), "ed57b880bba3b29e41831201dc12bc8100101448f491f687c0bec67e9403f920")
        v1 = json.loads(raw.decode("utf-8-sig"))
        self.assertEqual(preflight.sha256_text(preflight.canonical_json(v1)), "9b96f2fd68318e6476dc00d0d003162c0343d2aece5ef25f522fe7c33dca7bfd")

    def test_fixtures_carry_the_v2_contract(self):
        for name in preflight.CONTRACT["fixture_files"]:
            fixture = json.loads((ROOT / name).read_text(encoding="utf-8-sig"))
            self.assertEqual(fixture["contract_id"], preflight.CONTRACT["contract_id"])
            self.assertEqual(fixture["contract_sha256"], preflight.contract_sha256())


class SharedVectorTest(unittest.TestCase):
    def test_lineage_vectors(self):
        for case in VECTORS["lineage_cases"]:
            with self.subTest(case["name"]):
                self.assertEqual(source_observation.compute_independent_lineages(case["observations"]), case["expected"])

    def test_lineage_error_vectors(self):
        for case in VECTORS["lineage_error_cases"]:
            with self.subTest(case["name"]):
                with self.assertRaises(AttributeError):
                    source_observation.compute_independent_lineages(case["observations"])

    def test_recount_vectors(self):
        self.assertGreaterEqual(len(VECTORS["recount_cases"]), 60)
        for case in VECTORS["recount_cases"]:
            with self.subTest(case["name"]):
                observed = shared.claim_lineage_structurally_qualified(case["row"], case["minimum_families"])
                self.assertIs(observed, case["expected"])

    def test_every_rule_has_positive_and_negative_vectors(self):
        by_rule = {}
        for case in VECTORS["recount_cases"]:
            by_rule.setdefault(case["rule"], set()).add(case["expected"])
        for rule in ("1", "2", "3", "4", "5", "6"):
            self.assertIn(False, by_rule[rule], rule)
        for rule in ("2", "3", "4", "5", "6", "time", "positive"):
            self.assertIn(True, by_rule[rule], rule)


class PreflightCallerTest(unittest.TestCase):
    """The installer's validate_bundle, on the mixed fixture with each vector row injected."""

    NOW = datetime.fromisoformat(MIXED["evaluated_at"].replace("Z", "+00:00")).astimezone(timezone.utc)

    def run_bundle(self, mutate):
        bundle = copy.deepcopy(MIXED["bundle"])
        source = json.loads(bundle["payloads"]["source_independence_json"])
        mutate(source["records"])
        rewrite(bundle, "source_independence_json", source)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "bundle.json"
            path.write_text(json.dumps(bundle), encoding="utf-8")
            return preflight.validate_bundle(path, self.NOW)

    def test_unmodified_mixed_fixture_passes(self):
        receipt = self.run_bundle(lambda records: None)
        self.assertEqual(receipt["evidence_qualified_candidate_count"], 10)

    def test_vectors_through_the_installer_preflight(self):
        ran = 0
        for case in VECTORS["recount_cases"]:
            if case["minimum_families"] != 2:
                continue  # the preflight takes the threshold from the contract, not the vector
            ran += 1

            def inject(records, row=case["row"]):
                target = records[0]
                target.pop("claim_evidence_audit", None)
                if "claim_evidence_audit" in row:
                    target["claim_evidence_audit"] = copy.deepcopy(row["claim_evidence_audit"])

            with self.subTest(case["name"]):
                if case["expected"]:
                    self.assertEqual(self.run_bundle(inject)["evidence_qualified_candidate_count"], 10)
                else:
                    with self.assertRaises(preflight.PreflightError) as caught:
                        self.run_bundle(inject)
                    self.assertIn("EVIDENCE_QUALIFIED claim evidence recount failed", str(caught.exception))
        self.assertGreaterEqual(ran, 55)

    def test_saved_counts_alone_no_longer_qualify(self):
        # Counts pass (2 families, 2 domains, 1 primary, ratio 1.0) but the audit is gone.
        def strip(records):
            records[0].pop("claim_evidence_audit")

        with self.assertRaises(preflight.PreflightError) as caught:
            self.run_bundle(strip)
        self.assertIn("T00: EVIDENCE_QUALIFIED claim evidence recount failed", str(caught.exception))

    def test_limited_rows_are_never_recounted(self):
        def hostile(records):
            limited = [row for row in records if row["publication_evidence_mode"] == preflight.LIMITED]
            self.assertEqual(len(limited), 10)
            limited[0].pop("claim_evidence_audit")
            limited[1]["claim_evidence_audit"] = "not an audit"

        self.assertEqual(self.run_bundle(hostile)["limited_research_candidate_count"], 10)

    def test_metric_failure_still_reports_the_metric_first(self):
        def thin(records):
            records[0]["source_metrics"]["claim_relevant_independent_families"] = 1

        with self.assertRaises(preflight.PreflightError) as caught:
            self.run_bundle(thin)
        self.assertIn("fewer than two claim families", str(caught.exception))


class GuardAndBuilderEntryUnchangedTest(unittest.TestCase):
    """The shared module's timed entry keeps its behaviour after the structural split."""

    POLICY = {"minimum_claim_source_families_per_ticker": 2, "clock_skew_tolerance_minutes": 5}

    def valid_row(self):
        return copy.deepcopy(next(c for c in VECTORS["recount_cases"] if c["name"] == "valid two independent lineages")["row"])

    def test_timed_entry_still_enforces_expiry(self):
        row = self.valid_row()
        inside = datetime(2026, 1, 2, 3, 10, tzinfo=timezone.utc)
        after = datetime(2026, 1, 2, 5, 0, tzinfo=timezone.utc)
        self.assertTrue(shared.claim_lineage_qualified(row, self.POLICY, inside))
        self.assertFalse(shared.claim_lineage_qualified(row, self.POLICY, after))
        # The structural entry is blind to the same expiry by design (contract v2).
        self.assertTrue(shared.claim_lineage_structurally_qualified(row, 2))

    def test_timed_entry_still_enforces_evidence_expiry_and_reserve(self):
        row = self.valid_row()
        for evidence in row["claim_evidence_audit"]["evidence"]:
            evidence["valid_until"] = "2026-01-02T03:20:00Z"
        near = datetime(2026, 1, 2, 3, 10, tzinfo=timezone.utc)
        self.assertTrue(shared.claim_lineage_qualified(row, self.POLICY, near))
        self.assertFalse(shared.claim_lineage_qualified(row, self.POLICY, near, validity_margin=shared.GUARD_VALIDITY_MARGIN))

    def test_timed_entry_still_requires_a_second_lineage(self):
        row = self.valid_row()
        evidence = row["claim_evidence_audit"]["evidence"]
        evidence[1]["independence_group"] = evidence[0]["independence_group"]
        self.assertFalse(shared.claim_lineage_qualified(row, self.POLICY, datetime(2026, 1, 2, 3, 10, tzinfo=timezone.utc)))


if __name__ == "__main__":
    unittest.main()
