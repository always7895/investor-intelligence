"""BATCH08 follow-ups through the real callers; synthetic inputs, frozen clocks, no network."""
import copy
import json
import unittest
from datetime import timedelta
from unittest import mock

from tests import batch08b_fixtures as f
from tests import batch08c_fixtures as c
from tests.test_batch08b_guard_lineage import guarded_result
import claim_lineage_qualification as shared
import source_registry
import v213_build_v21_public_snapshot as guard

DEI = ("dei", "EntityCommonStockSharesOutstanding")


def dei_rows(facts):
    return facts["facts"][DEI[0]][DEI[1]]["units"]["shares"]


class DeiPrecedenceTests(unittest.TestCase):
    def assert_outstanding(self, facts, expected):
        fund = f.engine.sec_fundamentals("SYN", 1, facts)
        self.assertIsNotNone(fund)
        self.assertEqual(fund["shares_basis"], "OUTSTANDING")
        self.assertIsNotNone(fund.get("shares_yoy"))
        self.assertAlmostEqual(fund["shares_yoy"], expected)
        self.assertEqual(f.rank(facts)["top"][0]["fundamentals"], fund)

    def test_later_original_filing_beats_an_earlier_amendment(self):
        # Latest filed wins whatever the form: an earlier '/A' row never outranks a later original.
        for reverse in (False, True):
            with self.subTest(reverse=reverse):
                facts = f.share_facts()
                rows = dei_rows(facts)
                originals = copy.deepcopy(rows)
                for row in rows:
                    row.update(filed="2026-08-10", form="10-Q")
                rows.extend([{**originals[0], "filed": "2026-08-01", "form": "10-Q/A", "val": 80},
                             {**originals[-1], "filed": "2026-08-01", "form": "10-Q/A", "val": 160}])
                if reverse:
                    rows.reverse()
                self.assert_outstanding(facts, 0.2)

    def test_unit_without_valid_rows_yields_to_the_next_unit(self):
        facts = f.share_facts()
        units = facts["facts"][DEI[0]][DEI[1]]["units"]
        valid = units.pop("shares")
        units["malformed"] = [{"end": None, "val": 500}, {"end": "2026-08-01", "val": None}]
        units["shares"] = valid
        self.assert_outstanding(facts, 0.2)

    def test_first_share_tag_with_valid_rows_wins_and_later_tags_are_fallbacks(self):
        tags = f.engine.SHARES_TAGS + [("dei", "SyntheticSecondShareCount")]
        second = [{"end": "2025-08-01", "val": 100}, {"end": "2026-08-01", "val": 150}]
        with mock.patch.object(f.engine, "SHARES_TAGS", tags):
            facts = f.share_facts()
            facts["facts"]["dei"]["SyntheticSecondShareCount"] = {"units": {"shares": copy.deepcopy(second)}}
            self.assert_outstanding(facts, 0.2)
            facts = f.share_facts()
            facts["facts"]["dei"].pop(DEI[1])
            facts["facts"]["dei"]["SyntheticSecondShareCount"] = {"units": {"shares": copy.deepcopy(second)}}
            self.assert_outstanding(facts, 0.5)


class DilutionPenaltyBucketTests(unittest.TestCase):
    def penalty(self, facts):
        fund = f.engine.sec_fundamentals("SYN", 1, facts)
        ranked = f.rank(facts)["top"][0]
        self.assertEqual(ranked["fundamentals"], fund)
        return fund, ranked["score_parts"]["penalty"]

    def test_aligned_cover_count_selects_each_penalty_bucket(self):
        for current, expected in ((103, 0), (110, 2), (130, 4)):
            with self.subTest(current=current):
                facts = f.share_facts()
                dei_rows(facts)[-1]["val"] = current
                fund, penalty = self.penalty(facts)
                self.assertEqual(fund["shares_basis"], "OUTSTANDING")
                self.assertIsNotNone(fund.get("shares_yoy"))
                self.assertAlmostEqual(fund["shares_yoy"], current / 100 - 1)
                self.assertEqual(penalty, expected)

    def test_stale_cover_count_cannot_set_the_penalty(self):
        # The VSH shape: a stale 1% cover figure would carry no penalty; the aligned diluted figure does.
        facts = f.share_facts("stale")
        dei_rows(facts)[-1]["val"] = 101
        fund, penalty = self.penalty(facts)
        self.assertEqual(fund["shares_basis"], "DILUTED_WEIGHTED_AVERAGE")
        self.assertIsNotNone(fund.get("shares_yoy"))
        self.assertAlmostEqual(fund["shares_yoy"], 162 / 80 - 1)
        self.assertEqual(penalty, 4)


class NonStringFactEndTests(unittest.TestCase):
    def with_rpo(self, facts, extra=()):
        facts["facts"]["us-gaap"]["RevenueRemainingPerformanceObligation"] = {"units": {"USD": [
            *extra, {"end": "2025-06-28", "val": 100}, {"end": "2026-06-27", "val": 150}]}}
        return facts

    def test_non_string_revenue_and_rpo_ends_skip_the_row_not_the_build(self):
        expected = f.engine.sec_fundamentals("SYN", 1, self.with_rpo(f.share_facts()))
        self.assertAlmostEqual(expected["rpo_yoy"], 0.5)
        for end in (17, None, ["2026-06-27"], {"end": "2026-06-27"}, "2026-13-01"):
            with self.subTest(end=end):
                facts = self.with_rpo(f.share_facts(), [{"end": end, "val": 5}])
                revenue = facts["facts"]["us-gaap"]["RevenueFromContractWithCustomerIncludingAssessedTax"]
                revenue["units"]["USD"].append({"start": "2026-03-29", "end": end, "val": 999,
                                                "filed": "2026-09-01", "form": "10-Q", "fp": "Q"})
                try:
                    fund = f.engine.sec_fundamentals("SYN", 1, facts)
                    ranked = f.rank(facts)["top"][0]["fundamentals"]
                except Exception as exc:  # the pre-fix module raised out of the whole ranking build
                    self.fail(f"{type(exc).__name__}: {exc}")
                self.assertEqual(fund, expected)
                self.assertEqual(ranked, expected)


class MalformedPayloadClaimIdsTests(unittest.TestCase):
    def run_with(self, value, reverse):
        original = c.binding._build_test_four_factor_records

        def records(ticker):
            sec, ir = original(ticker)
            # Only the IR dependency declaration loses claim_id, so its payload claim_ids is the fallback.
            ir[0]["factor_binding"] = {k: v for k, v in ir[0]["factor_binding"].items() if k != "claim_id"}
            ir[0]["payload"]["claim_ids"] = value
            return sec, ir

        with mock.patch.object(c.binding, "_build_test_four_factor_records", records):
            return c.binding_run(reverse=reverse)

    def test_list_fallback_is_unchanged(self):
        for reverse in (False, True):
            with self.subTest(reverse=reverse):
                run = self.run_with(["dep_SYNB08C"], reverse)
                self.assertIsNotNone(run.binding_for_factor("SYNB08C", "dependency"))
                self.assertEqual(len(run.company_factor_bindings), 4)
                self.assertTrue(c.admission_result(run)["core_admitted"])

    def test_malformed_claim_ids_refuse_only_that_group_and_never_raise(self):
        for value in (7, True, {"dep_SYNB08C": 1}, "dep_SYNB08C", [7], []):
            for reverse in (False, True):
                with self.subTest(value=value, reverse=reverse):
                    try:
                        run = self.run_with(value, reverse)
                        result = c.admission_result(run)
                    except Exception as exc:  # pre-fix: acquisition or bridge raised for the whole run
                        self.fail(f"{type(exc).__name__}: {exc}")
                    self.assertIsNone(run.binding_for_factor("SYNB08C", "dependency"))
                    self.assertEqual({b.factor for b in run.company_factor_bindings}, {"scarcity", "pricing", "capture"})
                    self.assertFalse(result["dependency_licensed"])
                    self.assertFalse(result["core_admitted"])
                    for factor in ("scarcity", "pricing", "capture"):
                        self.assertTrue(result[factor + "_licensed"], factor)


class ClaimLineageStrictnessTests(unittest.TestCase):
    def row(self):
        row = f.documents()[-1]["records"][0]
        self.assertTrue(shared.claim_lineage_qualified(row, f.builder._read_policy(), f.NOW))
        return row

    def check(self, row, expected):
        self.assertEqual(shared.claim_lineage_qualified(row, f.builder._read_policy(), f.NOW), expected)

    def test_naive_timestamps_are_utc(self):
        row = self.row()
        audit = row["claim_evidence_audit"]
        expiry = (f.NOW + timedelta(hours=1)).replace(tzinfo=None).isoformat()
        audit["validated_at"] = f.NOW.replace(tzinfo=None).isoformat()
        audit["valid_until"] = expiry
        for evidence in audit["evidence"]:
            evidence["valid_until"] = expiry
        self.check(row, True)

    def test_padded_timestamps_are_stripped(self):
        row = self.row()
        audit = row["claim_evidence_audit"]
        for target in (audit, *audit["evidence"]):
            for key in ("validated_at", "valid_until"):
                if key in target:
                    target[key] = "  " + target[key] + " "
        self.check(row, True)

    def test_truthy_non_boolean_flags_refuse(self):
        for path in ("all_material_claims_supported", "high_confidence_eligible"):
            with self.subTest(path=path):
                row = self.row()
                audit = row["claim_evidence_audit"]
                target = audit if path == "all_material_claims_supported" else audit["claims"][0]
                target[path] = 1
                self.check(row, False)

    def test_non_list_claims_or_evidence_refuse(self):
        for key in ("claims", "evidence"):
            with self.subTest(key=key):
                row = self.row()
                audit = row["claim_evidence_audit"]
                audit[key] = tuple(audit[key])
                self.check(row, False)

    def test_blank_claim_id_refuses_even_when_rows_bind_it(self):
        row = self.row()
        audit = row["claim_evidence_audit"]
        audit["claims"][0]["claim_id"] = " "
        for evidence in audit["evidence"]:
            evidence["claim_ids"] = [" "]
        self.check(row, False)


class GuardBuilderCoherenceTests(unittest.TestCase):
    """A positive factor the guard keeps must never make the bundle builder refuse every ticker."""

    def docs(self, s0=None, s1=None):
        docs = f.documents(positive=True)
        sources = docs[-1]["records"][0]["sources"]
        sources[0].update(s0 or {})
        sources[1].update(s1 or {})
        return docs

    def support(self, docs):
        return guard._fresh_claim_support(docs[-1]["records"][0], now=f.NOW, maximum_age_days=135.0)

    def test_control_keeps_positive_factors(self):
        docs = self.docs()
        self.assertEqual((self.support(docs).get("family_count"), self.support(docs).get("non_primary_count")), (2, 1))
        removed, row, result = guarded_result(docs)
        self.assertEqual(removed, [])
        self.assertEqual(row["serenity_factors"]["tam_capture"], 1)
        self.assertEqual(result.get("mode"), "EVIDENCE_QUALIFIED", result.get("error"))

    def test_one_claim_family_is_withheld_instead_of_refusing_the_bundle(self):
        docs = self.docs(s0={"family": "reputable_secondary"})
        support = self.support(docs)
        self.assertEqual((support["unit_count"], support["domain_count"], support["primary_count"]), (2, 2, 1))
        self.assertEqual(support.get("family_count"), 1)
        self.assertFalse(support["supported"])
        removed, row, result = guarded_result(docs)
        self.assertEqual(removed, ["demand_wave", "tam_capture"])
        self.assertEqual(row["serenity_factors"]["tam_capture"], 0)
        self.assertNotIn("error", result)
        self.assertEqual(result["mode"], "LIMITED_RESEARCH_CANDIDATE")
        self.assertEqual(result["qualified_count"], 19)

    def test_no_non_primary_corroborator_is_withheld_instead_of_refusing_the_bundle(self):
        cases = (
            {"family": "issuer_primary", "domain": "issuer.example", "url": "https://issuer.example/t00"},
            {"primary": 1},
        )
        for s1 in cases:
            with self.subTest(s1=s1):
                docs = self.docs(s1=s1)
                support = self.support(docs)
                self.assertEqual(support.get("family_count"), 2)
                self.assertEqual(support.get("non_primary_count"), 0)
                self.assertFalse(support["supported"])
                removed, row, result = guarded_result(docs)
                self.assertEqual(removed, ["demand_wave", "tam_capture"])
                self.assertEqual(row["serenity_factors"]["demand_wave"], 0)
                self.assertNotIn("error", result)
                self.assertEqual(result["mode"], "EVIDENCE_QUALIFIED")
                self.assertEqual(result["factors"]["tam_capture"], 0)
                self.assertEqual(result["qualified_count"], 20)

    def test_policy_family_minimum_reaches_the_guard(self):
        docs = self.docs()
        audit_row = docs[-1]["records"][0]
        evidence = audit_row["claim_evidence_audit"]["evidence"]
        third = copy.deepcopy(evidence[1])
        third.update(observation_id="obs-2", independence_group="publisher-2",
                     origin_group="origin-2", content_sha256="3" * 64)
        evidence.append(third)
        audit_row["claim_evidence_audit"]["claims"][0]["evidence_ids"].append("obs-2")
        policy = f.builder._read_policy()
        policy["minimum_claim_source_families_per_ticker"] = 3
        self.assertTrue(shared.claim_lineage_qualified(
            audit_row, policy, f.NOW, validity_margin=shared.GUARD_VALIDITY_MARGIN))
        row = json.loads(docs[0]["payloads"]["top20_json"])[0]
        self.assertEqual(guard._guard_row(row, audit_row, policy, f.NOW), ["demand_wave", "tam_capture"])
        policy["minimum_claim_source_families_per_ticker"] = 2
        row = json.loads(docs[0]["payloads"]["top20_json"])[0]
        self.assertEqual(guard._guard_row(row, audit_row, policy, f.NOW), [])


class GuardReserveRegistryTests(unittest.TestCase):
    def test_no_runtime_source_expires_inside_the_guard_reserve(self):
        # Evidence expires at published_at + freshness_seconds, so such a source could never be retained
        # by the guard; enabling one needs the separate reserve/validity design decision first.
        reserve = shared.GUARD_VALIDITY_MARGIN.total_seconds()
        short = sorted(source.source_id for source in source_registry.load_registry().runtime_sources()
                       if source.freshness_seconds is not None and source.freshness_seconds <= reserve)
        self.assertEqual(short, [])


if __name__ == "__main__":
    unittest.main()
