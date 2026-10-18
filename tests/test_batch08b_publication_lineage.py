"""Exact-claim lineage must qualify the real activation-bundle caller."""
import unittest

from tests import batch08b_fixtures as f

NEGATIVES = (
    "origin", "hash", "publisher", "chain", "absent", "schema", "unsupported",
    "empty", "claim_status", "claim_flag", "declared_conflict", "conflict",
    "claim_value", "unadmitted", "stale", "unbound_id", "unbound_claim",
    "expired_row", "expired_audit", "future_audit", "long_expiry", "malformed",
    "missing_lineage", "duplicate_claim", "second_claim", "audit_type",
    "claims_type", "evidence_type", "claim_type", "id_type", "empty_id",
    "ids_type", "row_type", "row_claims_type", "missing_value",
)


class PublicationLineageTests(unittest.TestCase):
    def test_positive_independent_lineages_keep_factors(self):
        result = f.bundle_result(f.documents("independent", positive=True))
        self.assertEqual(result["mode"], "EVIDENCE_QUALIFIED")
        self.assertEqual(result["qualified_count"], 20)
        self.assertTrue(result["validated"])
        self.assertEqual(result["factors"]["demand_wave"], 1)
        self.assertEqual(result["factors"]["tam_capture"], 1)

    def test_positive_mirror_stops_the_whole_bundle(self):
        result = f.bundle_result(f.documents("origin", positive=True))
        self.assertEqual(result.get("error_type"), "SerenityEvidenceError")
        self.assertIn("positive Serenity advantages require", result["error"])

    def test_unmodified_synthetic_self_test(self):
        with f.frozen():
            f.builder.self_test()


def negative(case):
    def test(self):
        docs = f.documents(case)
        result = f.bundle_result(docs)
        self.assertEqual(result.get("mode"), "LIMITED_RESEARCH_CANDIDATE", case)
        self.assertFalse(result["validated"])
        self.assertIn("INDEPENDENT_CLAIM_CORROBORATION", result["missing"])
        self.assertIn("LIMITED_RESEARCH_CANDIDATE", result["missing"])
        self.assertEqual(result["logic"]["company_capture"], "UNPROVEN")
        self.assertEqual(result["logic"]["model_inference_confidence"], "LIMITED")
        self.assertEqual(result["qualified_count"], 19)
    return test


for _case in NEGATIVES:
    setattr(PublicationLineageTests, "test_reject_" + _case, negative(_case))


if __name__ == "__main__":
    unittest.main()
