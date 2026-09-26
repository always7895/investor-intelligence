"""C1 premise-state tests with synthetic inputs through the real T3, SEC and claim engines.

A comparison_ready result is a premise-state fact about these fixtures, not
live evidence, consumer admission, publication or a growth measurement.
"""
from __future__ import annotations

import copy
from dataclasses import FrozenInstanceError
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from adapters.base import mint_fetch_receipt  # noqa: E402
from adapters.sec_edgar import SEC_REGISTRY_SOURCE_ID, bind_sec_claim  # noqa: E402
import source_observation as observations  # noqa: E402
from source_registry import Registry, SourceDefinition, load_registry  # noqa: E402
from v213_forward_comparison_shadow import diagnose_forward_comparison  # noqa: E402
from v213_forward_premises_shadow import (  # noqa: E402
    PREMISES, ForwardPremisesError, assess_forward_premises,
)

CIK = "0000999001"
CUTOFF = "2026-09-13T00:00:00Z"
RETRIEVED = "2026-09-13T06:00:00+00:00"
STAMP = "2026-09-12T12:00:00Z"
NOW = datetime(2026, 9, 13, 12, tzinfo=timezone.utc)
SEC_REGISTRY = load_registry()
AXES = (
    "company_id", "security_id", "venue", "economic_scope", "metric_definition",
    "measure_form", "unit_scale", "currency_basis", "accounting_basis",
    "share_basis", "dilution_basis", "period_alignment",
)


def source(name, authority, tier, roles):
    return SourceDefinition(
        source_id=name, display_name=name, authority_class=authority, trust_tier=tier,
        evidence_roles=tuple(roles), jurisdictions=("US",), languages=("en",),
        canonical_urls=(f"https://{name}.example/",), independence_group=name,
        admission_status="RUNTIME_ENABLED", adapter_id=name, adapter_status="tested",
        runtime_enabled=True, free_access_required=True, payment_required=False,
        terms_review_status="reviewed", priority=1, per_host_concurrency=1,
        minimum_request_interval_seconds=1, maximum_retries=0,
        freshness_seconds=400 * 86400, correction_tracking=True,
        provenance_required=True, notes="synthetic fixture only", catalog_file="fixture")


CLAIM_REGISTRY = Registry(1, (
    source("official", "official_issuer", "T1_PRIMARY_OFFICIAL", ["guidance"]),
    source("news", "reputable_newswire", "T2_INSTITUTIONAL_CORROBORATION", ["financial_reporting"]),
), ())


def fact(start="2025-01-01", end="2025-12-31", filed="2026-02-20", value=4000, accn="0000999001-26-000001"):
    return {"start": start, "end": end, "val": value, "filed": filed, "accn": accn,
            "form": "10-K", "fy": 2025, "fp": "FY"}


def binding(facts=None, tag="Revenues", retrieved=RETRIEVED, alias="SYN"):
    document = {"cik": CIK, "entityName": "Synthetic Co.", "facts": {"us-gaap": {
        tag: {"label": tag, "units": {"USD": [fact()] if facts is None else facts}}}}}
    raw = json.dumps(document).encode("utf-8")
    receipt = mint_fetch_receipt(
        source_id=SEC_REGISTRY_SOURCE_ID,
        canonical_url=f"https://data.sec.gov/api/xbrl/companyfacts/CIK{CIK}.json",
        retrieved_at=retrieved, http_status=200, body=raw,
        transport_metadata={"capture": "response_seam"})
    symbol = None if alias is None else {"cik": CIK, "symbol": alias}
    return bind_sec_claim(raw, receipt, SEC_REGISTRY, "issuer_financial_statement", CIK,
                          "2025-12-31", resolved_symbol_alias=symbol)


def diagnostic(baseline=("2025-01-01T00:00:00Z", "2026-01-01T00:00:00Z"),
               forward=("2027-01-01T00:00:00Z", "2028-01-01T00:00:00Z"), overrides=None):
    descriptors = {axis: "Declared." + axis for axis in AXES}
    descriptors["measure_form"] = "AGGREGATE_FLOW"
    right = dict(descriptors, **(overrides or {}))
    return diagnose_forward_comparison({
        "baseline": {"period_start": baseline[0], "period_end": baseline[1],
                     "declared_evidence_kind": "CALLER_CLAIMED_REPORTED_ACTUAL",
                     "descriptors": descriptors},
        "forward": {"period": {"information_cutoff": CUTOFF, "period_start": forward[0],
                               "period_end": forward[1],
                               "declared_evidence_kind": "CALLER_CLAIMED_MANAGEMENT_GUIDANCE"},
                    "descriptors": right},
    })


def forward_claim(**changes):
    claim = dict(claim_id="guidance", claim_type="issuer_guidance_or_contract", subject="SYN",
                 metric="revenue", period="2027-01-01/2027-12-31", unit="million",
                 currency="USD", basis="GAAP", scope="consolidated")
    claim.update(changes)
    return claim


def research(claim, values=(4800, 4800), published=STAMP):
    rows = []
    for index, (provider, value) in enumerate(zip(("official", "news"), values)):
        role = CLAIM_REGISTRY.by_id()[provider].evidence_roles[0]
        rows.append(dict(
            source_id=provider, canonical_url=f"https://{provider}.example/guidance",
            published_at=published, retrieved_at="2026-09-13T11:00:00Z",
            content_sha256=format(index + 1, "x") * 64, parser_id=provider, parser_version="1",
            jurisdiction="US", language="en", claim_type=claim["claim_type"],
            evidence_role=role, source_health="HEALTHY",
            payload=dict(claim_ids=[claim["claim_id"]], value=value, as_of=published,
                         passage="Synthetic guidance passage, not live evidence.",
                         origin_group=provider,
                         **{key: claim[key] for key in observations.RESEARCH_COMPARABILITY})))
    return observations.reconcile_research_claims(
        {"material_claims": [claim], "source_observations": rows}, registry=CLAIM_REGISTRY,
        now=NOW, health_states={key: "HEALTHY" for key in CLAIM_REGISTRY.by_id()})


def assess(diag=None, base=None, claim=None, result=None):
    claim = forward_claim() if claim is None else claim
    return assess_forward_premises(diagnostic() if diag is None else diag,
                                   binding() if base is None else base, claim,
                                   research(claim) if result is None else result)


def states(assessment):
    return {name: (state, reasons) for name, state, reasons in assessment.premise_states}


class ForwardPremisesTests(unittest.TestCase):
    def test_premise_order_matches_t3_unresolved_premises(self):
        self.assertEqual(PREMISES, diagnostic().unresolved_premises)

    def test_fully_aligned_pair_is_ready_but_never_admitted(self):
        result = assess()
        found = states(result)
        self.assertEqual([name for name, _, _ in result.premise_states], list(PREMISES))
        for name in PREMISES[:3] + PREMISES[4:5]:
            self.assertEqual(found[name], ("RESOLVED", ()), name)
        self.assertEqual(found["SHARE_COUNT_DILUTION"], ("NOT_APPLICABLE_AGGREGATE_METRIC", ()))
        self.assertEqual(found["CONSUMER_ADMISSION"], ("DEFERRED_TO_CONSUMER_CONTRACT", ()))
        self.assertTrue(result.comparison_ready)
        data = result.to_dict()
        self.assertEqual(data["baseline_view"]["value"], 4000)
        self.assertEqual(data["baseline_view"]["accession"], "0000999001-26-000001")
        self.assertEqual(data["forward_view"]["value"], 4800)
        self.assertEqual(data["forward_view"]["unit"], "million")
        for flag in ("scoring_eligible", "publication_eligible", "consumer_admission"):
            self.assertIs(data[flag], False)
        self.assertEqual(data["qualification"], "UNQUALIFIED")
        self.assertIn("NO_RATIO_GROWTH_CONVERSION_OR_SCORE", data["limitations"])
        emitted = set(data) | set(data["baseline_view"]) | set(data["forward_view"])
        self.assertFalse({"ratio", "growth", "implied_change", "cagr", "score"} & emitted)

    def test_result_is_frozen(self):
        with self.assertRaises(FrozenInstanceError):
            assess().comparison_ready = False

    def test_inputs_are_not_mutated(self):
        claim = forward_claim()
        result = research(claim)
        before = (copy.deepcopy(claim), copy.deepcopy(result))
        assess(claim=claim, result=result)
        self.assertEqual((claim, result), before)

    def test_identity_requires_sec_alias_bound_to_subject(self):
        for base, claim, reason in (
            (binding(alias=None), None, "BASELINE_SYMBOL_ALIAS_ABSENT"),
            (None, forward_claim(subject="OTHER"), "SUBJECT_NOT_BOUND_TO_BASELINE_CIK"),
        ):
            with self.subTest(reason=reason):
                result = assess(base=base, claim=claim)
                self.assertEqual(states(result)["IDENTITY_ASSOCIATION"], ("UNRESOLVED", (reason,)))
                self.assertFalse(result.comparison_ready)
        result = assess(diag=diagnostic(overrides={"company_id": "Other.company"}))
        self.assertIn("CALLER_COMPANY_DECLARATIONS_DIFFER", states(result)["IDENTITY_ASSOCIATION"][1])

    def test_metric_currency_basis_and_scope_fail_closed(self):
        for changes, reason in (
            ({"metric": "operating_income"}, "FORWARD_METRIC_NOT_V1_REVENUE"),
            ({"currency": "EUR"}, "CURRENCY_DIFFERS"),
            ({"basis": "ADJUSTED"}, "FORWARD_BASIS_NOT_GAAP"),
            ({"scope": "segment"}, "FORWARD_SCOPE_NOT_CONSOLIDATED"),
            ({"unit": "lakh"}, "FORWARD_UNIT_SCALE_UNKNOWN"),
        ):
            with self.subTest(changes=changes):
                result = assess(claim=forward_claim(**changes))
                state, reasons = states(result)["METRIC_UNIT_CURRENCY_ACCOUNTING"]
                self.assertEqual(state, "NOT_COMPARABLE")
                self.assertIn(reason, reasons)
                self.assertFalse(result.comparison_ready)
        result = assess(base=binding(tag="OperatingIncomeLoss"))
        self.assertIn("BASELINE_TAG_NOT_V1_REVENUE", states(result)["METRIC_UNIT_CURRENCY_ACCOUNTING"][1])
        self.assertEqual(states(result)["SHARE_COUNT_DILUTION"][0], "UNRESOLVED")
        result = assess(diag=diagnostic(overrides={"accounting_basis": "Other.basis"}))
        self.assertIn("CALLER_ACCOUNTING_BASIS_DECLARATIONS_DIFFER",
                      states(result)["METRIC_UNIT_CURRENCY_ACCOUNTING"][1])

    def test_unit_scale_difference_is_display_only(self):
        result = assess(diag=diagnostic(overrides={"unit_scale": "Other.scale"}))
        self.assertEqual(states(result)["METRIC_UNIT_CURRENCY_ACCOUNTING"], ("RESOLVED", ()))

    def test_period_binding_roles_and_lengths(self):
        cases = (
            ({"diag": diagnostic(baseline=("2025-01-01T00:00:00Z", "2025-12-31T00:00:00Z"))},
             "BASELINE_PERIOD_NOT_BOUND_TO_SEC_FACT"),
            ({"claim": forward_claim(period="FY2027")}, "FORWARD_PERIOD_LABEL_NOT_BOUND"),
            ({"diag": diagnostic(forward=("2027-01-01T00:00:00Z", "2027-04-01T00:00:00Z")),
              "claim": forward_claim(period="2027-01-01/2027-03-31")}, "PERIOD_LENGTH_CLASS_DIFFERS"),
            ({"diag": diagnostic(forward=("2026-07-01T00:00:00Z", "2027-07-01T00:00:00Z")),
              "claim": forward_claim(period="2026-07-01/2027-06-30")}, "FORWARD_ROLE_NOT_FUTURE_START_TOTAL"),
            ({"diag": diagnostic(forward=("2027-01-01T12:00:00Z", "2028-01-01T00:00:00Z"))},
             "FORWARD_PERIOD_NOT_DAY_ALIGNED"),
            ({"base": binding(retrieved="2026-09-12T23:00:00+00:00")}, "BASELINE_RETRIEVED_BEFORE_CUTOFF"),
            ({"base": binding(facts=[fact(filed="2026-09-13", accn="0000999001-26-000009")],
                              retrieved="2026-09-14T00:00:00+00:00")}, "BASELINE_NOT_FILED_BY_CUTOFF"),
        )
        for kwargs, reason in cases:
            with self.subTest(reason=reason):
                result = assess(**kwargs)
                state, reasons = states(result)["PERIOD_ALIGNMENT_BASELINE_VINTAGE"]
                self.assertEqual(state, "UNRESOLVED")
                self.assertIn(reason, reasons)
                self.assertFalse(result.comparison_ready)

    def test_latest_vintage_wins_and_conflicts_are_not_averaged(self):
        revised = binding(facts=[fact(), fact(filed="2026-05-01", value=4100, accn="0000999001-26-000002")])
        result = assess(base=revised)
        self.assertEqual(result.to_dict()["baseline_view"]["value"], 4100)
        self.assertIn("BASELINE_REVISED_WITHIN_DOCUMENT", result.limitations)
        self.assertTrue(result.comparison_ready)
        conflict = binding(facts=[fact(), fact(value=4200, accn="0000999001-26-000003")])
        result = assess(base=conflict)
        self.assertIn("BASELINE_VINTAGE_CONFLICT", states(result)["PERIOD_ALIGNMENT_BASELINE_VINTAGE"][1])
        self.assertEqual(result.baseline_view, ())
        self.assertFalse(result.comparison_ready)

    def test_declared_period_selects_annual_or_quarter_fact_sharing_an_end_date(self):
        both = binding(facts=[fact(), fact(start="2025-10-01", value=1100, accn="0000999001-26-000004")])
        annual = assess(base=both)
        self.assertEqual(annual.to_dict()["baseline_view"]["value"], 4000)
        self.assertNotIn("BASELINE_REVISED_WITHIN_DOCUMENT", annual.limitations)
        self.assertTrue(annual.comparison_ready)
        quarter = assess(
            diag=diagnostic(baseline=("2025-10-01T00:00:00Z", "2026-01-01T00:00:00Z"),
                            forward=("2027-01-01T00:00:00Z", "2027-04-01T00:00:00Z")),
            base=both, claim=forward_claim(period="2027-01-01/2027-03-31"))
        self.assertEqual(quarter.to_dict()["baseline_view"]["value"], 1100)
        self.assertTrue(quarter.comparison_ready)

    def test_forward_support_independence_and_cutoff(self):
        claim = forward_claim()
        conflicted = research(claim, values=(4800, 5000))
        state, reasons = states(assess(result=conflicted))["FRESHNESS_LINEAGE_RIGHTS_COUNTEREVIDENCE"]
        self.assertEqual((state, reasons), ("UNRESOLVED", ("FORWARD_STATUS_CONFLICTED",)))
        late = research(claim, published="2026-09-13T06:00:00Z")
        self.assertIn("FORWARD_EVIDENCE_AFTER_CUTOFF",
                      states(assess(result=late))["FRESHNESS_LINEAGE_RIGHTS_COUNTEREVIDENCE"][1])
        statement = forward_claim(claim_type="issuer_financial_statement")
        self.assertIn("FORWARD_CLAIM_NOT_GUIDANCE_OR_CONTRACT",
                      states(assess(claim=statement))["FRESHNESS_LINEAGE_RIGHTS_COUNTEREVIDENCE"][1])
        single = research(claim)
        single["claims"][0] = dict(single["claims"][0], status="SINGLE_SOURCE", independent_evidence_families=1)
        self.assertIn("FORWARD_STATUS_SINGLE_SOURCE",
                      states(assess(result=single))["FRESHNESS_LINEAGE_RIGHTS_COUNTEREVIDENCE"][1])

    def test_malformed_inputs_raise_fixed_error(self):
        claim = forward_claim()
        good = research(claim)
        for args in (
            ({}, binding(), claim, good),
            (diagnostic(), object(), claim, good),
            (diagnostic(), binding(), dict(claim, extra="x"), good),
            (diagnostic(), binding(), dict(claim, subject=" "), good),
            (diagnostic(), binding(), forward_claim(claim_id="missing"), good),
            (diagnostic(), binding(), claim, {"claims": [], "evidence": []}),
        ):
            with self.subTest(args=type(args[0]).__name__):
                with self.assertRaises(ForwardPremisesError) as caught:
                    assess_forward_premises(*args)
                self.assertEqual(str(caught.exception), "FORWARD_PREMISES_INVALID")


if __name__ == "__main__":
    unittest.main()
