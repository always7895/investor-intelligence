"""R3A declared usable-capacity headroom shadow — focused tests (synthetic only).

NOT full qualification; NOT acceptance. Wholly fictional SYNTH IDs/labels.
"""
import copy
import os
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts import v213_capacity_response_shadow as m

EXPECTED_FIELDS = frozenset({
    "profile", "as_of", "status", "reasons", "headroom",
    "demand_claim_id", "capacity_claim_id", "demand_lineage_id", "capacity_lineage_id",
    "shadow_only", "source_authenticated", "comparability_authenticated",
    "independence_assessed", "production_authorized",
})


def make_measure(claim_id, kind, quantity="100", node="N1", spec="S1", cust="C1",
                 unit="U1", start="2025-01-01", end="2025-12-31", state="2025-06-01", lineage="L1"):
    return {
        "claim_id": claim_id, "lineage_id": lineage, "node_id": node, "spec_id": spec,
        "customer_id": cust, "unit": unit, "measure_kind": "PERIOD_TOTAL",
        "period_start": start, "period_end": end, "state_as_of": state,
        "kind": kind, "quantity": quantity,
    }


def make_payload(as_of, demand, capacity):
    return {"as_of": as_of, "demand": demand, "capacity": capacity}


def assert_flags_false(result):
    self_true = result["shadow_only"]
    assert self_true is True
    for f in ("source_authenticated", "comparability_authenticated",
              "independence_assessed", "production_authorized"):
        assert result[f] is False


class TestR3CapacityHeadroom(unittest.TestCase):
    def test_full_outputs_surplus_balanced_shortfall_zero(self):
        for demand_q, cap_q, status, headroom in [
            ("100", "150", "CLAIMED_SURPLUS", "50"),
            ("100", "100", "CLAIMED_BALANCED", "0"),
            ("150", "100", "CLAIMED_SHORTFALL", "-50"),
            ("0", "0", "CLAIMED_BALANCED", "0"),
        ]:
            with self.subTest(demand_q=demand_q, cap_q=cap_q):
                result = m.evaluate_capacity_headroom(make_payload("2025-06-01",
                    make_measure("D1", "CURRENT_REQUIRED", demand_q),
                    make_measure("C1", "CURRENT_QUALIFIED_USABLE", cap_q)))
                self.assertEqual(set(result.keys()), EXPECTED_FIELDS)
                self.assertEqual(result["profile"], "R3_DECLARED_USABLE_HEADROOM_V1")
                self.assertEqual(result["as_of"], "2025-06-01")
                self.assertEqual(result["status"], status)
                self.assertEqual(result["reasons"], [])
                self.assertEqual(result["headroom"], headroom)
                self.assertEqual(result["demand_claim_id"], "D1")
                self.assertEqual(result["capacity_claim_id"], "C1")
                self.assertEqual(result["demand_lineage_id"], "L1")
                self.assertEqual(result["capacity_lineage_id"], "L1")
                self.assertIs(result["shadow_only"], True)
                self.assertIs(result["source_authenticated"], False)
                self.assertIs(result["comparability_authenticated"], False)
                self.assertIs(result["independence_assessed"], False)
                self.assertIs(result["production_authorized"], False)

    def test_decimal_millionth_max_grammar(self):
        for demand_q, cap_q, status, headroom in [
            ("100.000001", "100", "CLAIMED_SHORTFALL", "-0.000001"),
            ("0", "1000000000000", "CLAIMED_SURPLUS", "1000000000000"),
            ("100.5", "100", "CLAIMED_SHORTFALL", "-0.5"),
            ("100.10", "100", "CLAIMED_SHORTFALL", "-0.1"),
            ("100.000000", "100", "CLAIMED_BALANCED", "0"),
        ]:
            with self.subTest(demand_q=demand_q, cap_q=cap_q):
                result = m.evaluate_capacity_headroom(make_payload("2025-06-01",
                    make_measure("D1", "CURRENT_REQUIRED", demand_q),
                    make_measure("C1", "CURRENT_QUALIFIED_USABLE", cap_q)))
                self.assertEqual(result["status"], status)
                self.assertEqual(result["headroom"], headroom)
        for bad in ("1000000000000.000001", "1e5", "-1", "1.2.3", "01", "1 000",
                    "NaN", "Infinity", "100.1234567", "1" * 21, "０", "+1"):
            with self.subTest(bad=bad), self.assertRaises(ValueError) as ctx:
                m.evaluate_capacity_headroom(make_payload("2025-06-01",
                    make_measure("D1", "CURRENT_REQUIRED", bad),
                    make_measure("C1", "CURRENT_QUALIFIED_USABLE", "100")))
            self.assertEqual(str(ctx.exception), "INVALID_CAPACITY_SHADOW_INPUT")

    def test_unknown_reasons_independent_and_combined(self):
        reason_cases = [
            ("CAPACITY_NOT_CURRENT_QUALIFIED_USABLE", lambda d, c: c.update(kind="NAMEPLATE")),
            ("DEMAND_NOT_CURRENT_REQUIRED", lambda d, c: d.update(kind="FORECAST")),
            ("MISSING_QUANTITY", lambda d, c: d.update(quantity=None)),
            ("SCOPE_MISMATCH", lambda d, c: d.update(node_id="N2")),
            ("UNIT_MISMATCH", lambda d, c: d.update(unit="U2")),
            ("PERIOD_MISMATCH", lambda d, c: d.update(period_start="2024-01-01")),
            ("STATE_AS_OF_MISMATCH", lambda d, c: d.update(state_as_of="2025-01-01")),
            ("OUTSIDE_PERIOD", lambda d, c: (d.update(period_start="2025-07-01"),
                                             c.update(period_start="2025-07-01"))),
        ]
        for reason, mutate in reason_cases:
            with self.subTest(reason=reason):
                d, c = make_measure("D1", "CURRENT_REQUIRED"), make_measure("C1", "CURRENT_QUALIFIED_USABLE")
                mutate(d, c)
                result = m.evaluate_capacity_headroom(make_payload("2025-06-01", d, c))
                self.assertEqual(result["status"], "UNKNOWN")
                self.assertIsNone(result["headroom"])
                self.assertEqual(result["reasons"], [reason])
                self.assertIs(result["shadow_only"], True)
                self.assertIs(result["source_authenticated"], False)
                self.assertIs(result["comparability_authenticated"], False)
                self.assertIs(result["independence_assessed"], False)
                self.assertIs(result["production_authorized"], False)
        d = make_measure("D1", "FORECAST", quantity=None, node="N2", unit="U2",
                         start="2024-01-01", end="2024-06-01", state="2025-01-01")
        c = make_measure("C1", "NAMEPLATE", quantity=None, node="N3", unit="U3",
                         start="2024-06-01", end="2024-12-01", state="2025-02-01")
        result = m.evaluate_capacity_headroom(make_payload("2025-06-01", d, c))
        self.assertEqual(result["status"], "UNKNOWN")
        self.assertIsNone(result["headroom"])
        self.assertEqual(result["reasons"], [
            "CAPACITY_NOT_CURRENT_QUALIFIED_USABLE", "DEMAND_NOT_CURRENT_REQUIRED",
            "MISSING_QUANTITY", "SCOPE_MISMATCH", "UNIT_MISMATCH",
            "PERIOD_MISMATCH", "STATE_AS_OF_MISMATCH", "OUTSIDE_PERIOD",
        ])
        self.assertIs(result["shadow_only"], True)
        self.assertIs(result["source_authenticated"], False)
        self.assertIs(result["comparability_authenticated"], False)
        self.assertIs(result["independence_assessed"], False)
        self.assertIs(result["production_authorized"], False)

    def test_all_fields_validation_even_excluded(self):
        for mutate in [lambda x: x.update(quantity="1e5"),
                       lambda x: x.update(period_start="2025-13-01"),
                       lambda x: x.update(claim_id=""),
                       lambda x: x.update(kind=123)]:
            with self.subTest():
                c = make_measure("C1", "NAMEPLATE")
                mutate(c)
                with self.assertRaises(ValueError) as ctx:
                    m.evaluate_capacity_headroom(make_payload("2025-06-01",
                        make_measure("D1", "CURRENT_REQUIRED"), c))
                self.assertEqual(str(ctx.exception), "INVALID_CAPACITY_SHADOW_INPUT")
        with self.assertRaises(ValueError) as ctx:
            m.evaluate_capacity_headroom(make_payload("2025-06-01",
                make_measure("D1", "CURRENT_REQUIRED"),
                make_measure("D1", "NAMEPLATE")))
        self.assertEqual(str(ctx.exception), "INVALID_CAPACITY_SHADOW_INPUT")

    def test_duplicate_claim_and_shared_lineage(self):
        with self.assertRaises(ValueError) as ctx:
            m.evaluate_capacity_headroom(make_payload("2025-06-01",
                make_measure("D1", "CURRENT_REQUIRED"),
                make_measure("D1", "CURRENT_QUALIFIED_USABLE")))
        self.assertEqual(str(ctx.exception), "INVALID_CAPACITY_SHADOW_INPUT")
        result = m.evaluate_capacity_headroom(make_payload("2025-06-01",
            make_measure("D1", "CURRENT_REQUIRED", lineage="L1"),
            make_measure("C1", "CURRENT_QUALIFIED_USABLE", lineage="L1")))
        self.assertEqual(result["status"], "CLAIMED_BALANCED")
        self.assertIs(result["independence_assessed"], False)

    def test_boundaries_halfopen_minmax_leap(self):
        d = make_measure("D1", "CURRENT_REQUIRED", start="2025-01-01", end="2025-07-01", state="2025-01-01")
        c = make_measure("C1", "CURRENT_QUALIFIED_USABLE", start="2025-01-01", end="2025-07-01", state="2025-01-01")
        self.assertEqual(m.evaluate_capacity_headroom(make_payload("2025-01-01", d, c))["status"], "CLAIMED_BALANCED")
        d_end = make_measure("D1", "CURRENT_REQUIRED", start="2025-01-01", end="2025-07-01", state="2025-07-01")
        c_end = make_measure("C1", "CURRENT_QUALIFIED_USABLE", start="2025-01-01", end="2025-07-01", state="2025-07-01")
        result = m.evaluate_capacity_headroom(make_payload("2025-07-01", d_end, c_end))
        self.assertEqual(result["status"], "UNKNOWN")
        self.assertEqual(result["reasons"], ["OUTSIDE_PERIOD"])
        d2 = make_measure("D1", "CURRENT_REQUIRED", start="0001-01-01", end="9999-12-31", state="0001-01-01")
        c2 = make_measure("C1", "CURRENT_QUALIFIED_USABLE", start="0001-01-01", end="9999-12-31", state="0001-01-01")
        self.assertEqual(m.evaluate_capacity_headroom(make_payload("0001-01-01", d2, c2))["status"], "CLAIMED_BALANCED")
        d3 = make_measure("D1", "CURRENT_REQUIRED", start="2024-02-29", end="2024-03-01", state="2024-02-29")
        c3 = make_measure("C1", "CURRENT_QUALIFIED_USABLE", start="2024-02-29", end="2024-03-01", state="2024-02-29")
        self.assertEqual(m.evaluate_capacity_headroom(make_payload("2024-02-29", d3, c3))["status"], "CLAIMED_BALANCED")
        with self.assertRaises(ValueError) as ctx:
            m.evaluate_capacity_headroom(make_payload("2025-06-01",
                make_measure("D1", "CURRENT_REQUIRED", start="2025-02-29"),
                make_measure("C1", "CURRENT_QUALIFIED_USABLE")))
        self.assertEqual(str(ctx.exception), "INVALID_CAPACITY_SHADOW_INPUT")

    def test_exact_types_keys_subclasses_poison_key(self):
        eq_called = []
        class PoisonKey:
            def __eq__(self, other):
                eq_called.append(True)
                return True
            def __hash__(self):
                return 0
        payload = make_payload("2025-06-01",
            make_measure("D1", "CURRENT_REQUIRED"),
            make_measure("C1", "CURRENT_QUALIFIED_USABLE"))
        payload[PoisonKey()] = "poison"
        with self.assertRaises(ValueError) as ctx:
            m.evaluate_capacity_headroom(payload)
        self.assertEqual(str(ctx.exception), "INVALID_CAPACITY_SHADOW_INPUT")
        self.assertEqual(eq_called, [])
        nested_eq = []
        class NestedPoison:
            def __eq__(self, other):
                nested_eq.append(True)
                return True
            def __hash__(self):
                return 1
        p2 = make_payload("2025-06-01",
            make_measure("D1", "CURRENT_REQUIRED"),
            make_measure("C1", "CURRENT_QUALIFIED_USABLE"))
        p2["demand"][NestedPoison()] = "nested"
        with self.assertRaises(ValueError) as ctx:
            m.evaluate_capacity_headroom(p2)
        self.assertEqual(str(ctx.exception), "INVALID_CAPACITY_SHADOW_INPUT")
        self.assertEqual(nested_eq, [])
        for mutate in [lambda p: p["demand"].pop("quantity"),
                       lambda p: p["demand"].update(extra="x"),
                       lambda p: p["demand"].update(quantity=True),
                       lambda p: p["demand"].update(quantity=100),
                       lambda p: p["demand"].update(quantity=b"100"),
                       lambda p: p["demand"].update(quantity=100.0)]:
            with self.subTest():
                p = make_payload("2025-06-01",
                    make_measure("D1", "CURRENT_REQUIRED"),
                    make_measure("C1", "CURRENT_QUALIFIED_USABLE"))
                mutate(p)
                with self.assertRaises(ValueError) as ctx:
                    m.evaluate_capacity_headroom(p)
                self.assertEqual(str(ctx.exception), "INVALID_CAPACITY_SHADOW_INPUT")
        class StrSub(str):
            pass
        p3 = make_payload("2025-06-01",
            make_measure("D1", "CURRENT_REQUIRED"),
            make_measure("C1", "CURRENT_QUALIFIED_USABLE"))
        p3["demand"]["quantity"] = StrSub("100")
        with self.assertRaises(ValueError) as ctx:
            m.evaluate_capacity_headroom(p3)
        self.assertEqual(str(ctx.exception), "INVALID_CAPACITY_SHADOW_INPUT")

    def test_mutability_and_flags(self):
        payload = make_payload("2025-06-01",
            make_measure("D1", "CURRENT_REQUIRED"),
            make_measure("C1", "CURRENT_QUALIFIED_USABLE"))
        original = copy.deepcopy(payload)
        m.evaluate_capacity_headroom(payload)
        self.assertEqual(payload, original)
        for kind in ("CURRENT_QUALIFIED_USABLE", "NAMEPLATE", "ANNOUNCED", "MODELED", "UNKNOWN"):
            result = m.evaluate_capacity_headroom(make_payload("2025-06-01",
                make_measure("D1", "CURRENT_REQUIRED"),
                make_measure("C1", kind)))
            self.assertIs(result["shadow_only"], True)
            self.assertIs(result["source_authenticated"], False)
            self.assertIs(result["comparability_authenticated"], False)
            self.assertIs(result["independence_assessed"], False)
            self.assertIs(result["production_authorized"], False)

    def test_bounded_import_api_guards(self):
        from contextlib import ExitStack
        from datetime import date as real_date
        from unittest import mock
        import builtins, io, os, socket, time
        src = (ROOT / "scripts" / "v213_capacity_response_shadow.py").read_bytes()
        code = compile(src, "v213_capacity_response_shadow.py", "exec")
        ns = {"__name__": "r3a_inert_probe"}
        calls, dates = [], []
        def deny(name):
            def blocked(*args, **kwargs):
                calls.append(name)
                raise AssertionError("R3_FORBIDDEN_" + name)
            return blocked
        class DateGate:
            @staticmethod
            def fromisoformat(value):
                dates.append(value)
                return real_date.fromisoformat(value)
            today = staticmethod(deny("date.today"))
        payload = make_payload("2025-06-01", make_measure("D1", "CURRENT_REQUIRED"),
                               make_measure("C1", "CURRENT_QUALIFIED_USABLE"))
        original = copy.deepcopy(payload)
        before_path = list(sys.path)
        with ExitStack() as stack:
            for name in ("builtins.open", "io.open", "os.open", "os.getenv", "os.environ.get",
                         "socket.socket", "socket.create_connection",
                         "time.time", "time.monotonic"):
                stack.enter_context(mock.patch(name, side_effect=deny(name)))
            stack.enter_context(mock.patch.object(type(os.environ), "__getitem__",
                                                  side_effect=deny("os.environ[]")))
            with self.assertRaisesRegex(AssertionError, r"R3_FORBIDDEN_os.environ\[\]"):
                os.environ["R3A_SYNTHETIC_GUARD_PROBE"]
            self.assertEqual(calls, ["os.environ[]"])
            calls.clear()  # Only the verified synthetic reachability probe is cleared.
            stack.enter_context(mock.patch("datetime.date", DateGate))
            stack.enter_context(mock.patch.object(m, "date", DateGate))
            exec(code, ns)
            for api in (ns["evaluate_capacity_headroom"], m.evaluate_capacity_headroom):
                result = api(payload)
                self.assertEqual((result["status"], result["headroom"]), ("CLAIMED_BALANCED", "0"))
        self.assertEqual(calls, [])
        self.assertEqual(len(dates), 14)  # Explicit paths were reached: seven dates per call.
        self.assertEqual(payload, original)
        self.assertEqual(sys.path, before_path)
        self.assertEqual(Path(m.__file__).resolve(), ROOT / "scripts" / "v213_capacity_response_shadow.py")

    def test_invalid_dates(self):
        for bad in ("20250101", "2025-W01-1", "2025-01-01T00:00:00", " 2025-01-01",
                    "2025-01-01 ", "2025-13-01", "2025-00-01", "2025-01-00",
                    "0000-01-01", "10000-01-01", "２０２５-01-01"):
            with self.subTest(bad=bad), self.assertRaises(ValueError) as ctx:
                m.evaluate_capacity_headroom(make_payload("2025-06-01",
                    make_measure("D1", "CURRENT_REQUIRED", start=bad),
                    make_measure("C1", "CURRENT_QUALIFIED_USABLE")))
            self.assertEqual(str(ctx.exception), "INVALID_CAPACITY_SHADOW_INPUT")
        from datetime import date
        p = make_payload("2025-06-01",
            make_measure("D1", "CURRENT_REQUIRED"),
            make_measure("C1", "CURRENT_QUALIFIED_USABLE"))
        p["demand"]["period_start"] = date(2025, 1, 1)
        with self.assertRaises(ValueError) as ctx:
            m.evaluate_capacity_headroom(p)
        self.assertEqual(str(ctx.exception), "INVALID_CAPACITY_SHADOW_INPUT")

    def test_invalid_ids(self):
        for bad in ("", "a" * 65, "-bad", ".bad", ":bad", "bad id", "bad\nid", "a b"):
            with self.subTest(bad=bad), self.assertRaises(ValueError) as ctx:
                m.evaluate_capacity_headroom(make_payload("2025-06-01",
                    make_measure("D1", "CURRENT_REQUIRED", node=bad),
                    make_measure("C1", "CURRENT_QUALIFIED_USABLE")))
            self.assertEqual(str(ctx.exception), "INVALID_CAPACITY_SHADOW_INPUT")

    def test_payload_type_checks(self):
        with self.assertRaises(ValueError) as ctx:
            m.evaluate_capacity_headroom("not a dict")
        self.assertEqual(str(ctx.exception), "INVALID_CAPACITY_SHADOW_INPUT")
        for mutate in [lambda p: p.update({123: "bad"}),
                       lambda p: p.pop("as_of"),
                       lambda p: p.update(extra="x")]:
            with self.subTest():
                p = make_payload("2025-06-01",
                    make_measure("D1", "CURRENT_REQUIRED"),
                    make_measure("C1", "CURRENT_QUALIFIED_USABLE"))
                mutate(p)
                with self.assertRaises(ValueError) as ctx:
                    m.evaluate_capacity_headroom(p)
                self.assertEqual(str(ctx.exception), "INVALID_CAPACITY_SHADOW_INPUT")

    def test_measure_kind_validation(self):
        for bad_kind in ("INSTANT", 123):
            with self.subTest(bad_kind=bad_kind):
                d = make_measure("D1", "CURRENT_REQUIRED")
                d["measure_kind"] = bad_kind
                with self.assertRaises(ValueError) as ctx:
                    m.evaluate_capacity_headroom(make_payload("2025-06-01", d,
                        make_measure("C1", "CURRENT_QUALIFIED_USABLE")))
                self.assertEqual(str(ctx.exception), "INVALID_CAPACITY_SHADOW_INPUT")

    def test_kind_validation(self):
        for bad_kind in ("INVALID", 123):
            with self.subTest(bad_kind=bad_kind):
                d = make_measure("D1", "CURRENT_REQUIRED")
                d["kind"] = bad_kind
                with self.assertRaises(ValueError) as ctx:
                    m.evaluate_capacity_headroom(make_payload("2025-06-01", d,
                        make_measure("C1", "CURRENT_QUALIFIED_USABLE")))
                self.assertEqual(str(ctx.exception), "INVALID_CAPACITY_SHADOW_INPUT")

    def test_start_end_validation(self):
        for start, end in [("2025-01-01", "2025-01-01"), ("2025-06-01", "2025-01-01")]:
            with self.subTest(start=start, end=end):
                d = make_measure("D1", "CURRENT_REQUIRED", start=start, end=end)
                with self.assertRaises(ValueError) as ctx:
                    m.evaluate_capacity_headroom(make_payload("2025-06-01", d,
                        make_measure("C1", "CURRENT_QUALIFIED_USABLE")))
                self.assertEqual(str(ctx.exception), "INVALID_CAPACITY_SHADOW_INPUT")

    def test_quantity_none(self):
        for dq, cq in [(None, None), (None, "100"), ("100", None)]:
            with self.subTest(dq=dq, cq=cq):
                result = m.evaluate_capacity_headroom(make_payload("2025-06-01",
                    make_measure("D1", "CURRENT_REQUIRED", quantity=dq),
                    make_measure("C1", "CURRENT_QUALIFIED_USABLE", quantity=cq)))
                self.assertEqual(result["status"], "UNKNOWN")
                self.assertIn("MISSING_QUANTITY", result["reasons"])
                self.assertIs(result["shadow_only"], True)
                self.assertIs(result["source_authenticated"], False)
                self.assertIs(result["comparability_authenticated"], False)
                self.assertIs(result["independence_assessed"], False)
                self.assertIs(result["production_authorized"], False)




class TestR3ContractMatrix(unittest.TestCase):
    def valid(self):
        return make_payload('2025-06-01', make_measure('SYNTH-D', 'CURRENT_REQUIRED'),
                            make_measure('SYNTH-C', 'CURRENT_QUALIFIED_USABLE'))

    def invalid(self, value):
        with self.assertRaises(ValueError) as ctx:
            m.evaluate_capacity_headroom(value)
        self.assertEqual(ctx.exception.args, ('INVALID_CAPACITY_SHADOW_INPUT',))

    def test_literal_unknown_all_fields_and_no_mutation(self):
        p = self.valid()
        p['capacity']['kind'] = 'ANNOUNCED'
        before = copy.deepcopy(p)
        self.assertEqual(m.evaluate_capacity_headroom(p), {
            'profile': 'R3_DECLARED_USABLE_HEADROOM_V1', 'as_of': '2025-06-01',
            'status': 'UNKNOWN', 'reasons': ['CAPACITY_NOT_CURRENT_QUALIFIED_USABLE'],
            'headroom': None, 'demand_claim_id': 'SYNTH-D', 'capacity_claim_id': 'SYNTH-C',
            'demand_lineage_id': 'L1', 'capacity_lineage_id': 'L1', 'shadow_only': True,
            'source_authenticated': False, 'comparability_authenticated': False,
            'independence_assessed': False, 'production_authorized': False,
        })
        self.assertEqual(p, before)
        for kind in ('FORECAST', 'UNKNOWN'):
            p = self.valid(); p['demand']['kind'] = kind
            r = m.evaluate_capacity_headroom(p)
            self.assertEqual(r['reasons'], ['DEMAND_NOT_CURRENT_REQUIRED'])
            self.assertIsNone(r['headroom'])
            for field in ('source_authenticated', 'comparability_authenticated',
                          'independence_assessed', 'production_authorized'):
                self.assertIs(r[field], False)
        for field in ('node_id', 'spec_id', 'customer_id'):
            p = self.valid(); p['capacity'][field] += '-OTHER'
            self.assertEqual(m.evaluate_capacity_headroom(p)['reasons'], ['SCOPE_MISMATCH'])
        p = self.valid(); p['capacity']['unit'] = 'u1'
        self.assertEqual(m.evaluate_capacity_headroom(p)['reasons'], ['UNIT_MISMATCH'])

    def test_builtin_type_and_closed_key_matrix(self):
        from datetime import date
        from decimal import Decimal
        class DS(dict): pass
        class SS(str): pass
        for v in (None, [], (), True, DS(self.valid())):
            self.invalid(v)
        for side in ('demand', 'capacity'):
            for v in (None, [], (), True, DS(self.valid()[side])):
                p = self.valid(); p[side] = v; self.invalid(p)
            for field in self.valid()[side]:
                p = self.valid(); p[side].pop(field); self.invalid(p)
                p = self.valid(); p[side]['EXTRA'] = 1; self.invalid(p)
                original = self.valid()[side][field]
                for bad in (SS(original), None, True, 1, b'X', [], {}):
                    if field == 'quantity' and bad is None: continue
                    with self.subTest(side=side, field=field, bad_type=type(bad).__name__):
                        p = self.valid(); p[side][field] = bad; self.invalid(p)
            for bad in (Decimal('100'), float('nan'), float('inf'), -0.0):
                p = self.valid(); p[side]['quantity'] = bad; self.invalid(p)
        for bad in (SS('2025-06-01'), date(2025, 6, 1), None, True, 20250601, b'2025-06-01'):
            p = self.valid(); p['as_of'] = bad; self.invalid(p)
        for original in ('as_of', 'demand', 'capacity'):
            p = self.valid(); p[SS(original)] = p.pop(original); self.invalid(p)
        for side in ('demand', 'capacity'):
            p = self.valid(); p[side][SS('unit')] = p[side].pop('unit'); self.invalid(p)

    def test_colliding_poison_key_checks_before_equality(self):
        calls = []
        class Poison:
            def __init__(self, key): self.key = key
            def __hash__(self): return hash(self.key)
            def __eq__(self, other):
                calls.append('equality')
                raise AssertionError('POISON_EQUALITY_CALLED')
        p = self.valid(); value = p.pop('as_of'); p[Poison('as_of')] = value
        self.invalid(p)
        for side in ('demand', 'capacity'):
            p = self.valid(); value = p[side].pop('unit'); p[side][Poison('unit')] = value
            self.invalid(p)
        self.assertEqual(calls, [])

    def test_numeric_limits_canonical_output_and_decimal_context_independence(self):
        from decimal import localcontext
        pairs = [
            ('1000000000000.000000', '1000000000000', '0', 'CLAIMED_BALANCED'),
            ('0.000000', '0', '0', 'CLAIMED_BALANCED'),
            ('0', '0.000001', '0.000001', 'CLAIMED_SURPLUS'),
            ('1.230000', '1.230001', '0.000001', 'CLAIMED_SURPLUS'),
            ('1.230001', '1.230000', '-0.000001', 'CLAIMED_SHORTFALL'),
            ('0', '12.340000', '12.34', 'CLAIMED_SURPLUS'),
            ('1000000000000', '0', '-1000000000000', 'CLAIMED_SHORTFALL'),
        ]
        with localcontext() as ctx:
            ctx.prec = 1
            for d, c, amount, status in pairs:
                p = self.valid(); p['demand']['quantity'] = d; p['capacity']['quantity'] = c
                result = m.evaluate_capacity_headroom(p)
                self.assertEqual((result['headroom'], result['status']), (amount, status))
        for value in ('', '0.0000000', '1000000000000.0000000', '1000000000001',
                      '1000000000000.000001', '１２', '١٢', '1,000', '+0', '-0',
                      '.5', '1.', ' 1', '1\n', '1E0', '00.1', 'inf', 'nan'):
            for side in ('demand', 'capacity'):
                p = self.valid(); p[side]['quantity'] = value; self.invalid(p)

    def test_all_date_positions_and_max_exclusive_end(self):
        bad_dates = ('0000-01-01', '10000-01-01', '1900-02-29', '2025-02-29',
                     '2024-04-31', '20250101', '2025-W01-1', '2025-1-01',
                     '2025-01-01T00:00:00Z', '2025-01-01+00:00',
                     '２０２５-01-01', '2025-01-01\n')
        for bad in bad_dates:
            p = self.valid(); p['as_of'] = bad; self.invalid(p)
            for side in ('demand', 'capacity'):
                for field in ('period_start', 'period_end', 'state_as_of'):
                    p = self.valid(); p[side][field] = bad; self.invalid(p)
        p = self.valid(); p['as_of'] = '9999-12-31'
        for side in ('demand', 'capacity'):
            p[side].update(period_start='0001-01-01', period_end='9999-12-31', state_as_of='9999-12-31')
        r = m.evaluate_capacity_headroom(p)
        self.assertEqual((r['status'], r['reasons'], r['headroom']), ('UNKNOWN', ['OUTSIDE_PERIOD'], None))
        p['as_of'] = '9999-12-30'
        for side in ('demand', 'capacity'): p[side]['state_as_of'] = '9999-12-30'
        self.assertEqual(m.evaluate_capacity_headroom(p)['status'], 'CLAIMED_BALANCED')
        p = self.valid(); p['as_of'] = '2000-02-29'
        for side in ('demand', 'capacity'):
            p[side].update(period_start='2000-02-29', period_end='2000-03-01', state_as_of='2000-02-29')
        self.assertEqual(m.evaluate_capacity_headroom(p)['status'], 'CLAIMED_BALANCED')
        p = self.valid(); p['capacity']['period_end'] = '2025-12-30'
        self.assertEqual(m.evaluate_capacity_headroom(p)['reasons'], ['PERIOD_MISMATCH'])

    def test_excluded_measures_validate_entire_schema_and_id_boundaries(self):
        for side, kind in (('capacity', 'ANNOUNCED'), ('capacity', 'MODELED'),
                           ('capacity', 'UNKNOWN'), ('demand', 'FORECAST'), ('demand', 'UNKNOWN')):
            for field, bad in (('quantity', 'NaN'), ('unit', ''), ('spec_id', 'bad value'),
                               ('customer_id', 'X' * 65), ('lineage_id', None),
                               ('state_as_of', '1900-02-29'), ('measure_kind', 'RATE')):
                p = self.valid(); p[side]['kind'] = kind; p[side][field] = bad; self.invalid(p)
        for field in ('claim_id', 'lineage_id', 'node_id', 'spec_id', 'customer_id', 'unit'):
            p = self.valid()
            p['demand'][field] = 'D' * 64
            p['capacity'][field] = 'C' * 64 if field == 'claim_id' else 'D' * 64
            self.assertEqual(m.evaluate_capacity_headroom(p)['status'], 'CLAIMED_BALANCED')
            for bad in ('X' * 65, 'Ａ', 'a\tb', 'a\x00b', '_X', ' X', 'X '):
                p = self.valid(); p['demand'][field] = bad; self.invalid(p)


if __name__ == "__main__":
    unittest.main()