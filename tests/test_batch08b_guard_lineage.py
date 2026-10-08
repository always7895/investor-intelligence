"""AMEND2 producer -> wire -> shared guard -> real bundle, with frozen clocks."""
import copy
import json
import unittest
from datetime import timedelta
from pathlib import Path
from unittest import mock

from tests import batch08b_fixtures as f
from tests import test_research_v2_claims as research
from tests.test_batch08b_publication_lineage import NEGATIVES
import source_observation
import claim_lineage_qualification as shared
import v213_build_v21_public_snapshot as guard

UNIT = timedelta(microseconds=1)


def producer(case):
    if case == "empty":
        doc = {}
    else:
        names = ("issuer", "news", "news-two") if case == "mirror_plus_independent" else ("issuer", "news")
        rows = [research.evidence(name) for name in names]
        for row in rows:
            row["published_at"] = row["retrieved_at"] = row["payload"]["as_of"] = f.NOW.isoformat()
            row["payload"]["subject"] = "T00"
        if case in {"mirror", "mirror_plus_independent"}:
            rows[1]["payload"]["origin_group"] = rows[0]["payload"]["origin_group"]
        claim = research.claim()
        claim["subject"] = "T00"
        doc = research.document(rows, [claim])
    audit = source_observation.reconcile_research_claims(doc, registry=research.REGISTRY,
        now=f.NOW, health_states={name: "HEALTHY" for name in research.REGISTRY.by_id()})
    return json.loads(json.dumps(audit))


def guarded_result(docs, policy=None, delay=timedelta(0)):
    policy = copy.deepcopy(policy or f.builder._read_policy())
    rows = json.loads(docs[0]["payloads"]["top20_json"])
    audits = {row["ticker"]: row for row in docs[-1]["records"]}
    # Match production: every row sees the same policy before the bundle build.
    removed = [guard._guard_row(row, audits[row["ticker"]], policy, f.NOW) for row in rows][0]
    f.builder._replace_top20_payload(docs[0], rows)
    with mock.patch.object(f, "NOW", f.NOW + delay), mock.patch.object(f.builder, "_read_policy", return_value=policy):
        result = f.bundle_result(docs)
    return removed, rows[0], result


class ProducerIntegrationTests(unittest.TestCase):
    def test_real_two_lineages_and_sec_mirror_plus_independent(self):
        for case in ("independent", "mirror_plus_independent"):
            with self.subTest(case=case):
                docs = f.documents(positive=True)
                audit = producer(case)
                self.assertEqual(audit["claims"][0]["independent_evidence_families"], 2)
                self.assertTrue(audit["all_material_claims_supported"])
                docs[-1]["records"][0]["claim_evidence_audit"] = audit
                self.assertTrue(shared.claim_lineage_qualified(docs[-1]["records"][0], f.builder._read_policy(), f.NOW))
                removed, row, result = guarded_result(docs, delay=shared.GUARD_VALIDITY_MARGIN)
                self.assertEqual(removed, [])
                self.assertEqual(row["serenity_factors"]["tam_capture"], 1)
                self.assertEqual(result.get("mode"), "EVIDENCE_QUALIFIED", result.get("error"))

    def test_real_mirror_and_empty_withhold_then_build_limited(self):
        for case in ("mirror", "empty"):
            with self.subTest(case=case):
                docs = f.documents(positive=True)
                audit = producer(case)
                if case == "empty":
                    self.assertEqual((audit["schema_version"], audit["status"], audit["claims"]), (2, "UNAVAILABLE", []))
                else:
                    self.assertEqual(audit["claims"][0]["independent_evidence_families"], 1)
                docs[-1]["records"][0]["claim_evidence_audit"] = audit
                self.assertFalse(shared.claim_lineage_qualified(docs[-1]["records"][0], f.builder._read_policy(), f.NOW))
                removed, row, result = guarded_result(docs)
                self.assertIn("tam_capture", removed)
                self.assertEqual(row["serenity_factors"]["tam_capture"], 0)
                self.assertIn(f.builder.LIMITED_RISK_FLAG, row["risk_flags"])
                self.assertEqual(result.get("mode"), "LIMITED_RESEARCH_CANDIDATE", result.get("error"))
                self.assertEqual(row["rating"], guard._rating(row["serenity_score"]))

    def test_coherence_for_every_synthetic_lineage_case(self):
        for case, seconds in ((case, delay) for case in ("independent", *NEGATIVES) for delay in (0, 1799, 1800)):
            with self.subTest(case=case, seconds=seconds):
                docs = f.documents(case, positive=True)
                removed, row, result = guarded_result(docs, delay=timedelta(seconds=seconds))
                self.assertNotIn("error", result)
                if not removed:
                    self.assertEqual(case, "independent")
                    self.assertEqual(result["mode"], "EVIDENCE_QUALIFIED")
                else:
                    self.assertEqual(result["mode"], "LIMITED_RESEARCH_CANDIDATE")
                    self.assertTrue(all(row["serenity_factors"][name] == 0 for name in removed))

    def test_missing_or_invalid_policy_minimum_fails_closed_in_both_callers(self):
        for value in (None, 0, 1, -1, True, "2", 2.5, 3):
            with self.subTest(value=value):
                policy = f.builder._read_policy()
                if value is None:
                    policy.pop("minimum_claim_source_families_per_ticker")
                else:
                    policy["minimum_claim_source_families_per_ticker"] = value
                docs = f.documents(positive=True)
                removed, _, result = guarded_result(docs, policy)
                # _read_policy is patched: this tests consumers, not its whole-policy validator.
                self.assertEqual(removed, ["demand_wave", "tam_capture"])
                self.assertNotIn("error", result)
                self.assertEqual(result["mode"], "LIMITED_RESEARCH_CANDIDATE")
                self.assertEqual(result["qualified_count"], 0)
                modes = [r["publication_evidence_mode"] for r in json.loads(result["raw_bundle"]["payloads"]["source_independence_json"])["records"]]
                self.assertEqual(modes, ["LIMITED_RESEARCH_CANDIDATE"] * 20)
        policy = f.builder._read_policy()
        policy["minimum_claim_source_families_per_ticker"] = 2
        removed, _, result = guarded_result(f.documents(positive=True), policy)
        self.assertEqual(removed, [])
        self.assertEqual(result["mode"], "EVIDENCE_QUALIFIED")
        self.assertEqual(result["qualified_count"], 20)

    def test_floor_two_matches_real_policy_validator_for_one_and_two_lineages(self):
        for minimum in (1, 2):
            for case in ('independent', 'origin'):
                with self.subTest(minimum=minimum, case=case):
                    policy = f.builder._read_policy()
                    policy['minimum_claim_source_families_per_ticker'] = minimum
                    original_read = Path.read_text
                    def read(path, *args, **kwargs):
                        if path == f.builder.FRESHNESS_POLICY_PATH:
                            return json.dumps(policy)
                        return original_read(path, *args, **kwargs)
                    # Exercise the actual whole-policy validator, not a patched _read_policy.
                    with mock.patch.object(Path, 'read_text', read):
                        if minimum == 1:
                            with self.assertRaises(f.builder.SerenityEvidenceError):
                                f.builder._read_policy()
                        else:
                            self.assertEqual(f.builder._read_policy()['minimum_claim_source_families_per_ticker'], 2)
                    docs = f.documents(case, positive=True)
                    row = docs[-1]['records'][0]
                    self.assertEqual(source_observation.compute_independent_lineages(
                        row['claim_evidence_audit']['evidence']), 2 if case == 'independent' else 1)
                    expected = minimum == 2 and case == 'independent'
                    self.assertEqual(shared.claim_lineage_qualified(row, policy, f.NOW), expected)
                    removed, top, result = guarded_result(docs, policy)
                    self.assertNotIn('error', result)
                    self.assertEqual(removed, [] if expected else ['demand_wave', 'tam_capture'])
                    self.assertEqual(top['serenity_factors']['tam_capture'], 1 if expected else 0)
                    self.assertEqual(result['mode'], 'EVIDENCE_QUALIFIED' if expected else 'LIMITED_RESEARCH_CANDIDATE')

    def test_shared_function_is_used_by_both_callers(self):
        self.assertIs(f.builder._claim_lineage_qualified, shared.claim_lineage_qualified)
        self.assertIs(guard.claim_lineage_qualified, shared.claim_lineage_qualified)


class FreshnessBoundaryTests(unittest.TestCase):
    def test_literal_1800_second_reserve_and_builder_delays(self):
        self.assertEqual(shared.GUARD_VALIDITY_MARGIN, timedelta(seconds=1800))
        for offset in (-1, 0, 1):
            for seconds in (0, 1799, 1800):
                with self.subTest(offset=offset, seconds=seconds):
                    docs = f.documents(positive=True)
                    audit = docs[-1]["records"][0]["claim_evidence_audit"]
                    audit["valid_until"] = (f.NOW + timedelta(seconds=1800) + UNIT * offset).isoformat()
                    removed, _, result = guarded_result(docs, delay=timedelta(seconds=seconds))
                    self.assertNotIn("error", result)
                    self.assertEqual(removed, [] if offset > 0 else ["demand_wave", "tam_capture"])
                    self.assertEqual(result["mode"], "EVIDENCE_QUALIFIED" if timedelta(seconds=seconds) < timedelta(seconds=1800) + UNIT * offset else "LIMITED_RESEARCH_CANDIDATE")

    def check_boundary(self, boundary, offset, expected):
        docs = f.documents(positive=True)
        policy = f.builder._read_policy()
        audit = docs[-1]["records"][0]["claim_evidence_audit"]
        delta = UNIT * offset
        margin = timedelta(0)
        if boundary == "future":
            policy["clock_skew_tolerance_minutes"] = 2
            audit["validated_at"] = (f.NOW + timedelta(minutes=2) + delta).isoformat()
        elif boundary == "validation_order":
            audit["validated_at"] = (f.NOW + timedelta(minutes=1) + delta).isoformat()
            audit["valid_until"] = (f.NOW + timedelta(minutes=1)).isoformat()
        elif boundary == "two_hour_cap":
            audit["valid_until"] = (f.NOW + timedelta(hours=2) + delta).isoformat()
        elif boundary in {"audit_expiry", "evidence_expiry"}:
            target = audit if boundary == "audit_expiry" else audit["evidence"][1]
            target["valid_until"] = (f.NOW + delta).isoformat()
            audit["validated_at"] = (f.NOW - timedelta(minutes=1)).isoformat()
        elif boundary in {"audit_margin", "evidence_margin"}:
            target = audit if boundary == "audit_margin" else audit["evidence"][1]
            target["valid_until"] = (f.NOW + shared.GUARD_VALIDITY_MARGIN + delta).isoformat()
            margin = shared.GUARD_VALIDITY_MARGIN
        actual = shared.claim_lineage_qualified(docs[-1]["records"][0], policy, f.NOW, validity_margin=margin)
        self.assertEqual(actual, expected, (boundary, offset))
        if margin:
            removed, _, result = guarded_result(docs, policy, delay=margin)
            self.assertEqual(not removed, expected)
            self.assertNotIn("error", result)
            self.assertEqual(result["mode"], "EVIDENCE_QUALIFIED" if expected else "LIMITED_RESEARCH_CANDIDATE")
        else:
            # Direct builder oracle must see policy skew, not an internal constant.
            with mock.patch.object(f.builder, "_read_policy", return_value=policy):
                result = f.bundle_result(docs)
            if expected:
                self.assertEqual(result.get("mode"), "EVIDENCE_QUALIFIED", (boundary, offset, result.get("error")))
            else:
                self.assertEqual(result.get("error_type"), "SerenityEvidenceError")
                self.assertIn("T00: positive Serenity advantages require independently", result["error"])

    def test_policy_skew_larger_than_five_is_not_hard_coded(self):
        policy = f.builder._read_policy()
        policy["clock_skew_tolerance_minutes"] = 8
        docs = f.documents(positive=True)
        docs[-1]["records"][0]["claim_evidence_audit"]["validated_at"] = (f.NOW + timedelta(minutes=7)).isoformat()
        with mock.patch.object(f.builder, "_read_policy", return_value=policy):
            self.assertEqual(f.bundle_result(docs).get("mode"), "EVIDENCE_QUALIFIED")

    def test_invalid_skew_and_negative_margin_refuse(self):
        row = f.documents()[-1]["records"][0]
        for value in (None, -1, True, "5"):
            policy = f.builder._read_policy()
            policy["clock_skew_tolerance_minutes"] = value
            self.assertFalse(shared.claim_lineage_qualified(row, policy, f.NOW))
        self.assertFalse(shared.claim_lineage_qualified(row, f.builder._read_policy(), f.NOW, validity_margin=-UNIT))


def boundary_test(boundary, offset, expected):
    def test(self):
        self.check_boundary(boundary, offset, expected)
    return test


for _boundary in ("future", "validation_order", "two_hour_cap", "audit_expiry", "evidence_expiry", "audit_margin", "evidence_margin"):
    for _offset in (-1, 0, 1):
        _expected = _offset <= 0 if _boundary in {"future", "validation_order", "two_hour_cap"} else _offset > 0
        setattr(FreshnessBoundaryTests, "test_" + _boundary + "_" + { -1: "minus", 0: "at", 1: "plus"}[_offset], boundary_test(_boundary, _offset, _expected))


if __name__ == "__main__":
    unittest.main()
