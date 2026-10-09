"""Master-specified synthetic T3 caller tests; no source/admission proof.

T3 cases1/2/3/4/8: opaque axis differences, NOT semantic validation.
5/6/7: total periods, geometry and unresolved alignment/vintage, NOT fiscal admission.
9: unspecified shares/dilution stays unresolved.10/11/12/14/15: constant unresolved
support/admission/association, NOT real-source, conflict, rights or causal checks.
13: numeric inputs out of profile.16: point-in-time measure form out of profile.
Import-inert observation is separately adopted audit coverage, not these unit tests.
"""
from copy import deepcopy
from dataclasses import FrozenInstanceError, fields
import unittest

from scripts.v213_forward_comparison_shadow import (
    ForwardComparisonDiagnostic, ForwardComparisonError, diagnose_forward_comparison,
)

AXES = (
    "company_id", "security_id", "venue", "economic_scope", "metric_definition",
    "measure_form", "unit_scale", "currency_basis", "accounting_basis",
    "share_basis", "dilution_basis", "period_alignment",
)
FLAGS = (
    "independently_verified", "comparability_qualified", "scoring_eligible",
    "publication_eligible", "consumer_admission",
)
UNRESOLVED = [
    "IDENTITY_ASSOCIATION", "METRIC_UNIT_CURRENCY_ACCOUNTING",
    "PERIOD_ALIGNMENT_BASELINE_VINTAGE", "SHARE_COUNT_DILUTION",
    "FRESHNESS_LINEAGE_RIGHTS_COUNTEREVIDENCE", "CONSUMER_ADMISSION",
]
LIMITS = [
    "SAME_DECLARATION_NOT_SEMANTIC_EQUIVALENCE",
    "DIFFERENT_DECLARATION_NOT_PROVEN_INCOMPATIBILITY",
    "CALLER_DECLARATIONS_NOT_ADMITTED", "NO_QUANTITY_GROWTH_CONVERSION_OR_SCORE",
]
KINDS = (
    "CALLER_CLAIMED_COMMITMENT", "CALLER_CLAIMED_MANAGEMENT_GUIDANCE",
    "CALLER_ANALYTICAL_INFERENCE",
)
KEYS = {
    "baseline_period_start", "baseline_period_end", "baseline_declared_evidence_kind",
    "information_cutoff", "forward_period_start", "forward_period_end",
    "forward_declared_evidence_kind", "forward_time_role", "descriptor_relations",
    "declared_interval_relation", "scope", "qualification", "unresolved_premises",
    "limitations", *FLAGS,
}


def fixture():
    descriptors = {axis: "Declared." + axis for axis in AXES}
    descriptors["measure_form"] = "AGGREGATE_FLOW"
    return {
        "baseline": {
            "period_start": "2024-01-01T00:00:00Z",
            "period_end": "2025-01-01T00:00:00Z",
            "declared_evidence_kind": "CALLER_CLAIMED_REPORTED_ACTUAL",
            "descriptors": descriptors,
        },
        "forward": {
            "period": {
                "information_cutoff": "2026-06-01T00:00:00Z",
                "period_start": "2027-01-01T00:00:00Z",
                "period_end": "2028-01-01T00:00:00Z",
                "declared_evidence_kind": KINDS[0],
            },
            "descriptors": dict(descriptors),
        },
    }


def at(raw, path):
    for key in path:
        raw = raw[key]
    return raw


class DiagnosticTests(unittest.TestCase):
    def invalid(self, raw, message="FORWARD_COMPARISON_INVALID"):
        with self.assertRaises(ForwardComparisonError) as ctx:
            diagnose_forward_comparison(raw)
        self.assertEqual(str(ctx.exception), message)
        return ctx.exception

    def authority(self, result):
        self.assertEqual(set(result), KEYS)
        self.assertEqual(result["scope"], "CALLER_DECLARATION_DIAGNOSTIC_ONLY")
        self.assertEqual(result["qualification"], "UNQUALIFIED")
        for flag in FLAGS:
            self.assertIs(result[flag], False)
        self.assertEqual(result["unresolved_premises"], UNRESOLVED)

    def test_future_three_kinds_exact_output(self):
        for kind in KINDS:
            with self.subTest(kind=kind):
                raw = fixture()
                raw["forward"]["period"]["declared_evidence_kind"] = kind
                got = diagnose_forward_comparison(raw).to_dict()
                self.authority(got)
                self.assertEqual(got["baseline_period_start"], raw["baseline"]["period_start"])
                self.assertEqual(got["baseline_period_end"], raw["baseline"]["period_end"])
                self.assertEqual(got["baseline_declared_evidence_kind"], "CALLER_CLAIMED_REPORTED_ACTUAL")
                for output, source in (("information_cutoff", "information_cutoff"),
                                       ("forward_period_start", "period_start"),
                                       ("forward_period_end", "period_end")):
                    self.assertEqual(got[output], raw["forward"]["period"][source])
                self.assertEqual(got["forward_declared_evidence_kind"], kind)
                self.assertEqual(got["forward_time_role"], "FUTURE_START_TOTAL")
                self.assertEqual(got["declared_interval_relation"], "NONOVERLAPPING_TOTALS")
                self.assertEqual(got["descriptor_relations"], dict.fromkeys(AXES, "SAME_DECLARATION"))
                self.assertEqual(list(got["descriptor_relations"]), list(AXES))
                self.assertEqual(got["limitations"], LIMITS + ["FUTURE_PERIOD_NOT_REALIZATION_PROOF"])
                self.assertNotIn("Declared.", repr(got))

    def test_straddling_kinds_not_remainder(self):
        for kind in KINDS:
            raw = fixture()
            raw["forward"]["period"].update(period_start="2024-06-01T00:00:00Z", declared_evidence_kind=kind)
            got = diagnose_forward_comparison(raw).to_dict()
            self.authority(got)
            self.assertEqual(got["forward_time_role"], "STRADDLING_TOTAL")
            self.assertEqual(got["declared_interval_relation"], "OVERLAPPING_TOTALS")
            self.assertEqual(got["limitations"], LIMITS + ["STRADDLING_TOTAL_NOT_FUTURE_REMAINDER", "OVERLAP_NOT_INDEPENDENT_GROWTH_PERIODS"])

    def test_each_axis_difference_is_only_declared_difference(self):
        for axis in AXES:
            raw = fixture()
            raw["forward"]["descriptors"][axis] = "PER_SHARE_FLOW" if axis == "measure_form" else "Different"
            expected = dict.fromkeys(AXES, "SAME_DECLARATION")
            expected[axis] = "DIFFERENT_DECLARATION"
            got = diagnose_forward_comparison(raw).to_dict()
            self.assertEqual(got["descriptor_relations"], expected)
            self.authority(got)
        raw = fixture()
        raw["forward"]["descriptors"]["company_id"] = raw["baseline"]["descriptors"]["company_id"].lower()
        self.assertEqual(diagnose_forward_comparison(raw).to_dict()["descriptor_relations"]["company_id"], "DIFFERENT_DECLARATION")

    def test_each_axis_unspecified_left_right_both(self):
        for axis in AXES:
            for sides in (("baseline",), ("forward",), ("baseline", "forward")):
                raw = fixture()
                for side in sides:
                    raw[side]["descriptors"][axis] = None
                expected = dict.fromkeys(AXES, "SAME_DECLARATION")
                expected[axis] = "UNSPECIFIED"
                got = diagnose_forward_comparison(raw).to_dict()
                self.assertEqual(got["descriptor_relations"], expected)
                self.authority(got)

    def test_baseline_order_and_common_cutoff(self):
        raw = fixture()
        raw["baseline"]["period_end"] = raw["forward"]["period"]["information_cutoff"]
        self.authority(diagnose_forward_comparison(raw).to_dict())
        raw["baseline"]["period_end"] = "2026-06-01T00:00:01Z"
        self.invalid(raw, "BASELINE_PERIOD_NOT_HISTORICAL")
        for end in ("2024-01-01T00:00:00Z", "2023-12-31T23:59:59Z"):
            raw = fixture(); raw["baseline"]["period_end"] = end
            self.invalid(raw)

    def test_strict_overlap_abut_disjoint_and_equal_cutoff_start(self):
        for start, relation in (
            ("2024-12-31T23:59:59Z", "OVERLAPPING_TOTALS"),
            ("2025-01-01T00:00:00Z", "NONOVERLAPPING_TOTALS"),
            ("2025-01-01T00:00:01Z", "NONOVERLAPPING_TOTALS"),
        ):
            raw = fixture(); raw["forward"]["period"]["period_start"] = start
            got = diagnose_forward_comparison(raw).to_dict()
            self.assertEqual(got["declared_interval_relation"], relation)
            self.assertEqual(got["forward_time_role"], "STRADDLING_TOTAL")
            self.assertEqual("OVERLAP_NOT_INDEPENDENT_GROWTH_PERIODS" in got["limitations"], relation == "OVERLAPPING_TOTALS")
        raw = fixture()
        raw["forward"]["period"]["period_start"] = raw["forward"]["period"]["information_cutoff"]
        self.assertEqual(diagnose_forward_comparison(raw).forward_time_role, "FUTURE_START_TOTAL")

    def test_valid_calendar_and_year_edges(self):
        for start, end, cutoff, forward_start, forward_end in (
            ("0001-01-01T00:00:00Z", "0001-02-01T00:00:00Z", "0001-03-01T00:00:00Z", "0001-04-01T00:00:00Z", "0001-05-01T00:00:00Z"),
            ("2024-02-29T00:00:00Z", "2024-03-01T00:00:00Z", "2024-04-01T00:00:00Z", "2024-05-01T00:00:00Z", "2024-06-01T00:00:00Z"),
            ("9998-01-01T00:00:00Z", "9999-01-01T00:00:00Z", "9999-06-01T00:00:00Z", "9999-07-01T00:00:00Z", "9999-12-31T23:59:59Z"),
        ):
            raw = fixture(); raw["baseline"].update(period_start=start, period_end=end)
            raw["forward"]["period"].update(information_cutoff=cutoff, period_start=forward_start, period_end=forward_end)
            got = diagnose_forward_comparison(raw).to_dict()
            self.authority(got)
            self.assertEqual(got["baseline_period_start"], start)

    def test_bad_timestamp_values_each_time_position(self):
        bad = ["", "x" * 1000, "2023-02-29T00:00:00Z", "2024-13-01T00:00:00Z",
               "2024-01-32T00:00:00Z", "2024-01-01T24:00:00Z", "2024-01-01T00:60:00Z",
               "2024-01-01T00:00:60Z", "0000-01-01T00:00:00Z", "２０２４-01-01T00:00:00Z",
               "2024-01-01T00:00:00+00:00", "2024-01-01T00:00:00.0Z", "2024-01-01T00:00:00Z\n"]
        locations = [(('baseline',), 'period_start'), (('baseline',), 'period_end')]
        locations += [(('forward', 'period'), k) for k in ('information_cutoff', 'period_start', 'period_end')]
        for path, key in locations:
            for value in bad:
                raw = fixture(); at(raw, path)[key] = value
                self.invalid(raw)

    def test_kind_domains_and_forward_error_mapping(self):
        for kind in (*KINDS, "FACT", "VERIFIED", "", True, None, 1):
            raw = fixture(); raw["baseline"]["declared_evidence_kind"] = kind
            self.invalid(raw)
        for kind in ("FACT", "VERIFIED", "", "caller_analytical_inference", KINDS[0] + " ", None):
            raw = fixture(); raw["forward"]["period"]["declared_evidence_kind"] = kind
            error = self.invalid(raw)
            self.assertTrue(error.__suppress_context__)
        raw = fixture(); raw["forward"]["period"]["period_end"] = "2026-06-01T00:00:00Z"
        self.assertTrue(self.invalid(raw).__suppress_context__)
        raw = fixture(); raw["forward"]["period"]["period_start"] = "2028-01-01T00:00:00Z"
        self.invalid(raw)

    def test_measure_form_and_opaque_tokens(self):
        for side in ("baseline", "forward"):
            for value in ("STOCK_AT_INSTANT", "UNKNOWN", "aggregate_flow", "", "AGGREGATE_FLOW "):
                raw = fixture(); raw[side]["descriptors"]["measure_form"] = value
                self.invalid(raw)
        for token in ("A", "Z" * 128, "A_.:/+-9", "UnknownMetric"):
            raw = fixture(); raw["baseline"]["descriptors"]["metric_definition"] = token
            self.authority(diagnose_forward_comparison(raw).to_dict())
        for axis in AXES:
            if axis == "measure_form":
                continue
            for token in ("", "X" * 129, " leading", "trailing ", "a b", "漢", "_bad", "a\n", "a\\b"):
                raw = fixture(); raw["baseline"]["descriptors"][axis] = token
                self.invalid(raw)

    def test_all_closed_mapping_shapes_and_injected_authority_quantity(self):
        paths = [(), ('baseline',), ('forward',), ('forward', 'period'), ('baseline', 'descriptors'), ('forward', 'descriptors')]
        for path in paths:
            for extra in ("quantity", "amount", "CAGR", "growth", "score", *FLAGS):
                raw = fixture(); at(raw, path)[extra] = True
                self.invalid(raw)
            for key in tuple(at(fixture(), path)):
                raw = fixture(); del at(raw, path)[key]
                self.invalid(raw)
            raw = fixture(); target = at(raw, path); del target[next(iter(target))]; target[1] = None
            self.invalid(raw)

    def test_nonexact_maps_and_scalars_at_each_mapping(self):
        class DictSubclass(dict):
            def __len__(self):
                raise AssertionError("subclass hook called")
        paths = [(), ('baseline',), ('forward',), ('forward', 'period'), ('baseline', 'descriptors'), ('forward', 'descriptors')]
        for path in paths:
            for value in (None, True, 1, 0.5, "value", [], (), DictSubclass()):
                raw = fixture()
                if path:
                    at(raw, path[:-1])[path[-1]] = value
                else:
                    raw = value
                self.invalid(raw)

    def test_poison_string_keys_and_values_never_invoke_hooks(self):
        class Poison(str):
            armed = False
            def __hash__(self):
                if self.armed:
                    raise AssertionError("hash hook")
                return str.__hash__(self)
            def __eq__(self, other):
                raise AssertionError("equality hook")
            def __len__(self):
                raise AssertionError("length hook")
            def __str__(self):
                raise AssertionError("string hook")
        paths = [(), ('baseline',), ('forward',), ('forward', 'period'), ('baseline', 'descriptors'), ('forward', 'descriptors')]
        for path in paths:
            raw = fixture(); target = at(raw, path); key = next(iter(target)); value = target.pop(key)
            poison = Poison(key); target[poison] = value; poison.armed = True
            self.invalid(raw)
        locations = [(('baseline',), k) for k in ('period_start', 'period_end', 'declared_evidence_kind')]
        locations += [(('forward', 'period'), k) for k in ('information_cutoff', 'period_start', 'period_end', 'declared_evidence_kind')]
        locations += [((side, 'descriptors'), axis) for side in ('baseline', 'forward') for axis in AXES]
        for path, key in locations:
            raw = fixture(); at(raw, path)[key] = Poison("bad")
            self.invalid(raw)

    def test_nonstring_values_no_conversion(self):
        class NoConversion:
            def __str__(self):
                raise AssertionError("conversion")
        for value in (True, 1, 1.0, [], {}, NoConversion()):
            raw = fixture(); raw["baseline"]["descriptors"]["unit_scale"] = value
            self.invalid(raw)
            raw = fixture(); raw["baseline"]["period_start"] = value
            self.invalid(raw)

    def test_input_result_and_serialization_detachment(self):
        raw = fixture(); before = deepcopy(raw)
        result = diagnose_forward_comparison(raw)
        self.assertEqual(raw, before)
        self.assertEqual(result, diagnose_forward_comparison(raw))
        first = result.to_dict(); second = result.to_dict()
        self.assertIsNot(first["descriptor_relations"], second["descriptor_relations"])
        self.assertIsNot(first["unresolved_premises"], second["unresolved_premises"])
        self.assertIsNot(first["limitations"], second["limitations"])
        first["descriptor_relations"]["company_id"] = "FORGED"
        first["unresolved_premises"].clear(); first["limitations"].clear()
        first["consumer_admission"] = True
        self.assertEqual(result.to_dict(), second)
        raw["baseline"]["descriptors"]["company_id"] = "After"
        self.assertEqual(result.to_dict(), second)

    def test_frozen_slots_and_nonconstructor_authority(self):
        result = diagnose_forward_comparison(fixture())
        self.assertFalse(hasattr(result, "__dict__"))
        with self.assertRaises(FrozenInstanceError):
            result.information_cutoff = "changed"
        self.assertIsInstance(result.descriptor_relations, tuple)
        self.assertTrue(all(type(item) is tuple for item in result.descriptor_relations))
        for f in fields(result):
            if f.name in (*FLAGS, "scope", "qualification", "unresolved_premises"):
                self.assertFalse(f.init)
        constructor = {f.name: getattr(result, f.name) for f in fields(result) if f.init}
        for key in (*FLAGS, "scope", "qualification", "unresolved_premises", "limitations"):
            with self.assertRaises(TypeError):
                ForwardComparisonDiagnostic(**constructor, **{key: True})
        # Ordinary Python objects are not tamper-proof authority capabilities.

    def test_all_unspecified_stays_unqualified(self):
        raw = fixture()
        for side in ("baseline", "forward"):
            raw[side]["descriptors"] = dict.fromkeys(AXES)
        got = diagnose_forward_comparison(raw).to_dict()
        self.authority(got)
        self.assertEqual(got["descriptor_relations"], dict.fromkeys(AXES, "UNSPECIFIED"))

    def test_fiscal_share_currency_conflicts_stay_declarations(self):
        raw = fixture()
        for axis in ('company_id', 'economic_scope', 'metric_definition', 'currency_basis',
                     'accounting_basis', 'unit_scale', 'share_basis', 'dilution_basis', 'period_alignment'):
            raw["forward"]["descriptors"][axis] = "OtherDeclaredBasis"
        got = diagnose_forward_comparison(raw).to_dict()
        self.authority(got)
        self.assertIn("PERIOD_ALIGNMENT_BASELINE_VINTAGE", got["unresolved_premises"])
        self.assertIn("FRESHNESS_LINEAGE_RIGHTS_COUNTEREVIDENCE", got["unresolved_premises"])
        self.assertNotIn("Declared.", repr(got))


if __name__ == "__main__":
    unittest.main()
