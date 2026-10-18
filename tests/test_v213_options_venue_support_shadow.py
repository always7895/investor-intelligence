"""O1 declared venue/field coverage shadow - adversarial tests (synthetic only).

Exercises actual evaluate_declared_venue_matrix callable. NOT real support claims.
"""
import copy
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts import v213_options_venue_support_shadow as m


def make_scope(underlying_id="UND-A", exchange="EXX-1", venue="VEN-1",
               provider="PROV-1", adapter="ADPT-1", family="FAM-1",
               contract="CON-1", calendar="CAL-1", currency="AAA",
               multiplier=100, evidence=None, field_overrides=None):
    fc = {}
    for name in ("contract_identity", "expiry", "strike", "option_type", "bid",
                 "ask", "last", "volume", "open_interest", "iv", "greeks",
                 "trading_calendar", "quote_delay"):
        fc[name] = {"declared": "NOT_DECLARED", "evidence_ids": []}
    if field_overrides:
        for name, decl in field_overrides.items():
            fc[name] = decl
    ev = evidence if evidence is not None else []
    return {
        "underlying_id": underlying_id, "underlying_exchange": exchange,
        "options_venue": venue, "provider_id": provider, "adapter_id": adapter,
        "product_family": family, "contract_id": contract, "calendar_id": calendar,
        "currency": currency, "multiplier": multiplier,
        "data_origin": "SYNTHETIC_PUBLIC_DECLARATION_ONLY",
        "field_coverage": fc, "evidence": ev,
    }


def make_payload(scopes):
    return json.dumps({"schema_version": 1, "scopes": scopes})


def make_evidence(eid="EV-1", lineage="LIN-1", source="SRC-1",
                  observed="2026-01-01T00:00:00Z", valid_until="2026-12-31T00:00:00Z"):
    return {"evidence_id": eid, "lineage_id": lineage, "source_id": source,
            "observed_at": observed, "valid_until": valid_until}


AS_OF = "2026-06-01T00:00:00Z"


class TestO1VenueSupport(unittest.TestCase):
    def test_positive_two_scopes_distinct_terms(self):
        ev1 = make_evidence("EV-1")
        ev2 = make_evidence("EV-2")
        s1 = make_scope(venue="VEN-1", provider="PROV-1", currency="AAA", multiplier=100,
                        evidence=[ev1],
                        field_overrides={"bid": {"declared": "AVAILABLE", "evidence_ids": ["EV-1"]}})
        s2 = make_scope(venue="VEN-2", provider="PROV-2", currency="BBB", multiplier=1,
                        evidence=[ev2],
                        field_overrides={"ask": {"declared": "AVAILABLE", "evidence_ids": ["EV-2"]}})
        result = m.evaluate_declared_venue_matrix(make_payload([s1, s2]), as_of=AS_OF)
        self.assertEqual(result.schema_version, 1)
        self.assertEqual(result.as_of, AS_OF)
        self.assertEqual(len(result.scopes), 2)
        self.assertIs(result.qualified_support, False)
        self.assertIs(result.runtime_enabled, False)
        self.assertIs(result.admission_authorized, False)
        self.assertIs(result.independent_lineage_verified, False)
        self.assertIs(result.freshness_verified, False)
        for scope in result.scopes:
            self.assertIs(scope.qualified_support, False)
            self.assertIs(scope.runtime_enabled, False)
            self.assertIs(scope.admission_authorized, False)
            self.assertIs(scope.independent_lineage_verified, False)
            self.assertIs(scope.freshness_verified, False)
        bid = [f for f in result.scopes[0].field_results if f.field_name == "bid"][0]
        self.assertEqual(bid.derived_state, "DECLARED_AVAILABLE_UNVERIFIED")

    def test_frozen_no_dict(self):
        s1 = make_scope()
        result = m.evaluate_declared_venue_matrix(make_payload([s1]), as_of=AS_OF)
        self.assertFalse(hasattr(result, "__dict__"))
        self.assertFalse(hasattr(result.scopes[0], "__dict__"))
        self.assertFalse(hasattr(result.scopes[0].field_results[0], "__dict__"))
        self.assertIsInstance(result.scopes, tuple)
        self.assertIsInstance(result.scopes[0].field_results, tuple)
        self.assertIsInstance(result.scopes[0].evidence_results, tuple)

    def test_order_independence_no_merging(self):
        s1 = make_scope(venue="VEN-1")
        s2 = make_scope(venue="VEN-2")
        r1 = m.evaluate_declared_venue_matrix(make_payload([s1, s2]), as_of=AS_OF)
        r2 = m.evaluate_declared_venue_matrix(make_payload([s2, s1]), as_of=AS_OF)
        self.assertEqual(r1.scopes, r2.scopes)
        self.assertEqual(len(r1.scopes), 2)

    def test_temporal_boundaries(self):
        ev_in = make_evidence("EV-IN", observed="2026-01-01T00:00:00Z", valid_until="2026-12-31T00:00:00Z")
        ev_future = make_evidence("EV-FUT", observed="2026-07-01T00:00:00Z", valid_until="2026-12-31T00:00:00Z")
        ev_expired = make_evidence("EV-EXP", observed="2026-01-01T00:00:00Z", valid_until="2026-06-01T00:00:00Z")
        s = make_scope(evidence=[ev_in, ev_future, ev_expired],
                       field_overrides={"bid": {"declared": "AVAILABLE", "evidence_ids": ["EV-IN", "EV-FUT", "EV-EXP"]}})
        result = m.evaluate_declared_venue_matrix(make_payload([s]), as_of=AS_OF)
        states = {ev.evidence_id: ev.temporal_state for ev in result.scopes[0].evidence_results}
        self.assertEqual(states["EV-IN"], "DECLARED_IN_WINDOW_UNVERIFIED")
        self.assertEqual(states["EV-FUT"], "DECLARED_FUTURE")
        self.assertEqual(states["EV-EXP"], "DECLARED_EXPIRED")
        bid = [f for f in result.scopes[0].field_results if f.field_name == "bid"][0]
        self.assertEqual(bid.derived_state, "DECLARED_AVAILABLE_UNVERIFIED")

    def test_expired_reference_nonauthorizing(self):
        ev = make_evidence("EV-1", observed="2026-01-01T00:00:00Z", valid_until="2026-02-01T00:00:00Z")
        s = make_scope(evidence=[ev],
                       field_overrides={"bid": {"declared": "AVAILABLE", "evidence_ids": ["EV-1"]}})
        result = m.evaluate_declared_venue_matrix(make_payload([s]), as_of=AS_OF)
        bid = [f for f in result.scopes[0].field_results if f.field_name == "bid"][0]
        self.assertEqual(bid.derived_state, "DECLARED_AVAILABLE_NO_CURRENT_REFERENCES")

    def test_invalid_timestamps(self):
        for bad in ("2026-02-30T00:00:00Z", "2026-01-01T00:00:00+00:00",
                    "2026-01-01T00:00:00.000Z", "2026-01-01 00:00:00Z",
                    "1969-12-31T00:00:00Z", "2026-01-01T24:00:00Z",
                    "2026-01-01T00:60:00Z", " 2026-01-01T00:00:00Z"):
            with self.subTest(bad=bad), self.assertRaises(m.VenueMatrixError):
                m.evaluate_declared_venue_matrix(make_payload([make_scope()]), as_of=bad)

    def test_contradictory_interval(self):
        ev = make_evidence("EV-1", observed="2026-06-01T00:00:00Z", valid_until="2026-01-01T00:00:00Z")
        with self.assertRaises(m.VenueMatrixError) as ctx:
            m.evaluate_declared_venue_matrix(make_payload([make_scope(evidence=[ev])]), as_of=AS_OF)
        self.assertEqual(ctx.exception.code, "CONTRADICTORY_DECLARED_INTERVAL")

    def test_injected_keys_rejected(self):
        s = make_scope()
        s["evidence_status"] = "SUPPORTED"
        with self.assertRaises(m.VenueMatrixError):
            m.evaluate_declared_venue_matrix(make_payload([s]), as_of=AS_OF)
        s2 = make_scope()
        s2["rights_status"] = "OK"
        with self.assertRaises(m.VenueMatrixError):
            m.evaluate_declared_venue_matrix(make_payload([s2]), as_of=AS_OF)

    def test_duplicate_json_keys(self):
        payload = '{"schema_version": 1, "schema_version": 1, "scopes": []}'
        with self.assertRaises(m.VenueMatrixError) as ctx:
            m.evaluate_declared_venue_matrix(payload, as_of=AS_OF)
        self.assertEqual(ctx.exception.code, "DUPLICATE_KEY")

    def test_bool_float_version_multiplier(self):
        payload = json.dumps({"schema_version": True, "scopes": [make_scope()]})
        with self.assertRaises(m.VenueMatrixError):
            m.evaluate_declared_venue_matrix(payload, as_of=AS_OF)
        payload2 = json.dumps({"schema_version": 1.0, "scopes": [make_scope()]})
        with self.assertRaises(m.VenueMatrixError):
            m.evaluate_declared_venue_matrix(payload2, as_of=AS_OF)
        s = make_scope(multiplier=True)
        with self.assertRaises(m.VenueMatrixError):
            m.evaluate_declared_venue_matrix(make_payload([s]), as_of=AS_OF)
        s2 = make_scope(multiplier=100.0)
        with self.assertRaises(m.VenueMatrixError):
            m.evaluate_declared_venue_matrix(make_payload([s2]), as_of=AS_OF)

    def test_multiplier_bounds(self):
        for bad in (0, 1000001):
            with self.subTest(bad=bad), self.assertRaises(m.VenueMatrixError):
                m.evaluate_declared_venue_matrix(make_payload([make_scope(multiplier=bad)]), as_of=AS_OF)

    def test_invalid_currency(self):
        for bad in ("AB", "ABCD", "abc", "A1B"):
            with self.subTest(bad=bad), self.assertRaises(m.VenueMatrixError):
                m.evaluate_declared_venue_matrix(make_payload([make_scope(currency=bad)]), as_of=AS_OF)

    def test_identifier_validation(self):
        for bad in ("", "a" * 65, "-bad", ".bad", "bad id", "bad\nid"):
            with self.subTest(bad=bad), self.assertRaises(m.VenueMatrixError):
                m.evaluate_declared_venue_matrix(make_payload([make_scope(underlying_id=bad)]), as_of=AS_OF)

    def test_duplicate_scope_and_conflict(self):
        s1 = make_scope()
        s2 = make_scope()
        with self.assertRaises(m.VenueMatrixError) as ctx:
            m.evaluate_declared_venue_matrix(make_payload([s1, s2]), as_of=AS_OF)
        self.assertEqual(ctx.exception.code, "DUPLICATE_SCOPE")
        s3 = make_scope(currency="BBB")
        with self.assertRaises(m.VenueMatrixError) as ctx:
            m.evaluate_declared_venue_matrix(make_payload([s1, s3]), as_of=AS_OF)
        self.assertEqual(ctx.exception.code, "CONFLICTING_DECLARED_TERMS")

    def test_unresolved_evidence_reference(self):
        s = make_scope(field_overrides={"bid": {"declared": "AVAILABLE", "evidence_ids": ["EV-MISSING"]}})
        with self.assertRaises(m.VenueMatrixError) as ctx:
            m.evaluate_declared_venue_matrix(make_payload([s]), as_of=AS_OF)
        self.assertEqual(ctx.exception.code, "UNRESOLVED_EVIDENCE_REFERENCE")

    def test_available_requires_evidence(self):
        s = make_scope(field_overrides={"bid": {"declared": "AVAILABLE", "evidence_ids": []}})
        with self.assertRaises(m.VenueMatrixError):
            m.evaluate_declared_venue_matrix(make_payload([s]), as_of=AS_OF)

    def test_unavailable_requires_empty(self):
        ev = make_evidence("EV-1")
        s = make_scope(evidence=[ev],
                       field_overrides={"bid": {"declared": "UNAVAILABLE", "evidence_ids": ["EV-1"]}})
        with self.assertRaises(m.VenueMatrixError):
            m.evaluate_declared_venue_matrix(make_payload([s]), as_of=AS_OF)

    def test_trailing_data(self):
        payload = make_payload([make_scope()]) + " extra"
        with self.assertRaises(m.VenueMatrixError):
            m.evaluate_declared_venue_matrix(payload, as_of=AS_OF)

    def test_nonfinite_json(self):
        payload = '{"schema_version": 1, "scopes": [NaN]}'
        with self.assertRaises(m.VenueMatrixError) as ctx:
            m.evaluate_declared_venue_matrix(payload, as_of=AS_OF)
        self.assertEqual(ctx.exception.code, "NONFINITE_CONSTANT")

    def test_empty_scopes(self):
        with self.assertRaises(m.VenueMatrixError):
            m.evaluate_declared_venue_matrix('{"schema_version": 1, "scopes": []}', as_of=AS_OF)

    def test_input_immutability(self):
        s = make_scope()
        original = copy.deepcopy(s)
        m.evaluate_declared_venue_matrix(make_payload([s]), as_of=AS_OF)
        self.assertEqual(s, original)

    def test_valid_identifier_success(self):
        s = make_scope(underlying_id="BAD-1")
        result = m.evaluate_declared_venue_matrix(make_payload([s]), as_of=AS_OF)
        self.assertEqual(result.scopes[0].underlying_id, "BAD-1")

    def test_nested_frozen_graph(self):
        ev = make_evidence("EV-1")
        s = make_scope(evidence=[ev],
                       field_overrides={"bid": {"declared": "AVAILABLE", "evidence_ids": ["EV-1"]}})
        result = m.evaluate_declared_venue_matrix(make_payload([s]), as_of=AS_OF)
        self.assertFalse(hasattr(result, "__dict__"))
        scope = result.scopes[0]
        self.assertFalse(hasattr(scope, "__dict__"))
        self.assertFalse(hasattr(scope.field_results[0], "__dict__"))
        self.assertFalse(hasattr(scope.evidence_results[0], "__dict__"))
        with self.assertRaises(Exception):
            scope.underlying_id = "MUTATED"
        with self.assertRaises(Exception):
            scope.field_results[0].field_name = "MUTATED"

    def test_unicode_digits_rejected(self):
        # U+0662/U+0660 are decimal digits, not the U+2026 ellipsis from repair01.
        bad_values = ("\u0662\u0660\u0662\u0666-01-01T00:00:00Z",
                      "2026-\u0660\u0661-01T00:00:00Z",
                      "2026-01-\u0660\u0661T00:00:00Z")
        for bad in bad_values:
            self.assertEqual(len(bad), 20)
            for site in ("as_of", "observed_at", "valid_until"):
                ev = make_evidence()
                clock = bad if site == "as_of" else AS_OF
                if site != "as_of":
                    ev[site] = bad
                with self.subTest(site=site, bad=bad), self.assertRaises(m.VenueMatrixError):
                    m.evaluate_declared_venue_matrix(make_payload([make_scope(evidence=[ev])]), as_of=clock)

    def test_sanitized_errors(self):
        with self.assertRaises(m.VenueMatrixError) as ctx:
            m.evaluate_declared_venue_matrix('{bad json', as_of=AS_OF)
        self.assertEqual(ctx.exception.code, "INVALID_JSON")
        self.assertIsNone(ctx.exception.__cause__)
        self.assertTrue(ctx.exception.__suppress_context__)
        self.assertEqual(str(ctx.exception), "INVALID_JSON")

    def test_nested_boundaries(self):
        s = make_scope()
        s["unknown_field"] = "x"
        with self.assertRaises(m.VenueMatrixError):
            m.evaluate_declared_venue_matrix(make_payload([s]), as_of=AS_OF)
        del s["unknown_field"]
        del s["calendar_id"]
        with self.assertRaises(m.VenueMatrixError):
            m.evaluate_declared_venue_matrix(make_payload([s]), as_of=AS_OF)
        payload = '{"schema_version": 1, "scopes": [' + json.dumps(make_scope()) + '], "extra": 1}'
        with self.assertRaises(m.VenueMatrixError):
            m.evaluate_declared_venue_matrix(payload, as_of=AS_OF)
        scopes_32 = [make_scope(venue=f"VEN-{i}") for i in range(32)]
        m.evaluate_declared_venue_matrix(make_payload(scopes_32), as_of=AS_OF)
        scopes_33 = [make_scope(venue=f"VEN-{i}") for i in range(33)]
        with self.assertRaises(m.VenueMatrixError):
            m.evaluate_declared_venue_matrix(make_payload(scopes_33), as_of=AS_OF)
        evs_16 = [make_evidence(f"EV-{i}") for i in range(16)]
        m.evaluate_declared_venue_matrix(make_payload([make_scope(evidence=evs_16)]), as_of=AS_OF)
        evs_17 = [make_evidence(f"EV-{i}") for i in range(17)]
        with self.assertRaises(m.VenueMatrixError):
            m.evaluate_declared_venue_matrix(make_payload([make_scope(evidence=evs_17)]), as_of=AS_OF)
        big = "x" * 131072
        with self.assertRaises(m.VenueMatrixError):
            m.evaluate_declared_venue_matrix(big, as_of=AS_OF)

    def test_cross_provider_refs(self):
        ev1 = make_evidence("EV-1")
        ev2 = make_evidence("EV-2")
        s1 = make_scope(venue="VEN-1", provider="PROV-1", evidence=[ev1],
                        field_overrides={"bid": {"declared": "AVAILABLE", "evidence_ids": ["EV-2"]}})
        s2 = make_scope(venue="VEN-2", provider="PROV-2", evidence=[ev2])
        with self.assertRaises(m.VenueMatrixError) as ctx:
            m.evaluate_declared_venue_matrix(make_payload([s1, s2]), as_of=AS_OF)
        self.assertEqual(ctx.exception.code, "UNRESOLVED_EVIDENCE_REFERENCE")

    def test_mixed_temporal_retained(self):
        ev_in = make_evidence("EV-IN", observed="2026-01-01T00:00:00Z", valid_until="2026-12-31T00:00:00Z")
        ev_exp = make_evidence("EV-EXP", observed="2026-01-01T00:00:00Z", valid_until="2026-02-01T00:00:00Z")
        s = make_scope(evidence=[ev_in, ev_exp],
                       field_overrides={"bid": {"declared": "AVAILABLE", "evidence_ids": ["EV-IN", "EV-EXP"]}})
        result = m.evaluate_declared_venue_matrix(make_payload([s]), as_of=AS_OF)
        states = {ev.evidence_id: ev.temporal_state for ev in result.scopes[0].evidence_results}
        self.assertEqual(states["EV-IN"], "DECLARED_IN_WINDOW_UNVERIFIED")
        self.assertEqual(states["EV-EXP"], "DECLARED_EXPIRED")
        bid = [f for f in result.scopes[0].field_results if f.field_name == "bid"][0]
        self.assertEqual(bid.derived_state, "DECLARED_AVAILABLE_UNVERIFIED")

    def test_import_boundary(self):
        import ast
        src = (ROOT / "scripts" / "v213_options_venue_support_shadow.py").read_text(encoding="utf-8")
        tree = ast.parse(src)
        imports = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imports.add(alias.name)
            elif isinstance(node, ast.ImportFrom):
                imports.add(node.module)
        self.assertTrue(imports <= {"json", "re", "dataclasses", "datetime"})
        self.assertEqual(m.__file__, str(ROOT / "scripts" / "v213_options_venue_support_shadow.py"))

    def test_module_inert(self):
        self.assertTrue(hasattr(m, "evaluate_declared_venue_matrix"))
        self.assertTrue(hasattr(m, "VenueMatrixError"))
        self.assertTrue(hasattr(m, "MatrixResult"))
        self.assertFalse(hasattr(m, "main"))


class TestO1ContractEdges(unittest.TestCase):
    def evaluate(self, value):
        return m.evaluate_declared_venue_matrix(json.dumps(value), as_of=AS_OF)

    def fixture(self):
        return {"schema_version": 1, "scopes": [make_scope(evidence=[make_evidence()])]}

    def test_exact_payload_byte_budget_and_overflow(self):
        payload = make_payload([make_scope()])
        padded = payload + " " * (131072 - len(payload.encode("utf-8")))
        self.assertEqual(len(padded.encode("utf-8")), 131072)
        self.assertEqual(len(m.evaluate_declared_venue_matrix(padded, as_of=AS_OF).scopes), 1)
        with self.assertRaises(m.VenueMatrixError) as ctx:
            m.evaluate_declared_venue_matrix(padded + " ", as_of=AS_OF)
        self.assertEqual(ctx.exception.code, "PAYLOAD_TOO_LARGE")

    def test_exact_reference_budget_and_overflow(self):
        evs = [make_evidence(f"E-{i}") for i in range(16)]
        refs = [ev["evidence_id"] for ev in evs]
        scope = make_scope(evidence=evs, field_overrides={"bid": {"declared": "AVAILABLE", "evidence_ids": refs}})
        result = m.evaluate_declared_venue_matrix(make_payload([scope]), as_of=AS_OF)
        self.assertEqual(next(f for f in result.scopes[0].field_results if f.field_name == "bid").evidence_ids, tuple(sorted(refs)))
        scope["field_coverage"]["bid"]["evidence_ids"].append("E-16")
        with self.assertRaises(m.VenueMatrixError) as ctx:
            m.evaluate_declared_venue_matrix(make_payload([scope]), as_of=AS_OF)
        self.assertEqual(ctx.exception.code, "INVALID_EVIDENCE_IDS_COUNT")

    def test_duplicate_keys_at_each_object_level(self):
        payload = make_payload([make_scope(evidence=[make_evidence()])])
        for key, text in [("schema_version", '"schema_version": 1'),
                          ("underlying_id", '"underlying_id": "UND-A"'),
                          ("bid", '"bid": {"declared": "NOT_DECLARED", "evidence_ids": []}'),
                          ("declared", '"declared": "NOT_DECLARED"'),
                          ("evidence_id", '"evidence_id": "EV-1"')]:
            self.assertIn(text, payload)
            bad = payload.replace(text, text + ", " + text, 1)
            with self.subTest(key=key), self.assertRaises(m.VenueMatrixError) as ctx:
                m.evaluate_declared_venue_matrix(bad, as_of=AS_OF)
            self.assertEqual(ctx.exception.code, "DUPLICATE_KEY")

    def test_every_nested_schema_unknown_and_missing_keys(self):
        getters = [lambda x: x, lambda x: x["scopes"][0],
                   lambda x: x["scopes"][0]["field_coverage"],
                   lambda x: x["scopes"][0]["field_coverage"]["bid"],
                   lambda x: x["scopes"][0]["evidence"][0]]
        for getter in getters:
            for mutate in ("add", "remove"):
                value = self.fixture()
                obj = getter(value)
                if mutate == "add":
                    obj["INJECTED_PRIVATE_FIELD"] = None
                else:
                    del obj[next(iter(obj))]
                with self.subTest(mutate=mutate), self.assertRaises(m.VenueMatrixError):
                    self.evaluate(value)

    def test_nested_container_and_scalar_types(self):
        cases = [([],), (None,), (True,), ("bad",)]
        for (bad,) in cases:
            with self.subTest(root=bad), self.assertRaises(m.VenueMatrixError):
                self.evaluate(bad)
        for key in ("scopes",):
            for bad in ({}, "bad", 1, None):
                value = self.fixture(); value[key] = bad
                with self.assertRaises(m.VenueMatrixError): self.evaluate(value)
        for key in ("field_coverage", "evidence"):
            for bad in ("bad", 1, None):
                value = self.fixture(); value["scopes"][0][key] = bad
                with self.assertRaises(m.VenueMatrixError): self.evaluate(value)
        for key, bad in [("declared", True), ("declared", "QUALIFIED_SUPPORT"),
                         ("evidence_ids", {}), ("evidence_ids", [True])]:
            value = self.fixture(); value["scopes"][0]["field_coverage"]["bid"][key] = bad
            with self.assertRaises(m.VenueMatrixError): self.evaluate(value)

    def test_identifier_length_case_and_no_registry_inference(self):
        for length in (1, 64):
            scope = make_scope(underlying_id="A" * length, currency="ZZZ", multiplier=1000000)
            self.assertEqual(m.evaluate_declared_venue_matrix(make_payload([scope]), as_of=AS_OF).scopes[0].currency, "ZZZ")
        with self.assertRaises(m.VenueMatrixError):
            m.evaluate_declared_venue_matrix(make_payload([make_scope(underlying_id="A" * 65)]), as_of=AS_OF)
        result = m.evaluate_declared_venue_matrix(make_payload([make_scope(underlying_id="a"), make_scope(underlying_id="A")]), as_of=AS_OF)
        self.assertEqual([s.underlying_id for s in result.scopes], ["A", "a"])

    def test_duplicate_evidence_and_reference_ids(self):
        value = self.fixture(); value["scopes"][0]["evidence"].append(make_evidence())
        with self.assertRaises(m.VenueMatrixError): self.evaluate(value)
        value = self.fixture(); value["scopes"][0]["field_coverage"]["bid"] = {"declared": "AVAILABLE", "evidence_ids": ["EV-1", "EV-1"]}
        with self.assertRaises(m.VenueMatrixError): self.evaluate(value)

    def test_scope_local_same_evidence_spelling_never_merges(self):
        a = make_scope(provider="P-1", evidence=[make_evidence(observed="2026-01-01T00:00:00Z")], field_overrides={"bid": {"declared": "AVAILABLE", "evidence_ids": ["EV-1"]}})
        b = make_scope(provider="P-2", evidence=[make_evidence(observed="2026-07-01T00:00:00Z")], field_overrides={"bid": {"declared": "AVAILABLE", "evidence_ids": ["EV-1"]}})
        result = m.evaluate_declared_venue_matrix(make_payload([a, b]), as_of=AS_OF)
        self.assertEqual([s.evidence_results[0].temporal_state for s in result.scopes], ["DECLARED_IN_WINDOW_UNVERIFIED", "DECLARED_FUTURE"])
        self.assertTrue(all(s.independent_lineage_verified is False for s in result.scopes))

    def test_declared_not_supported_semantics(self):
        scope = make_scope(field_overrides={"bid": {"declared": "UNAVAILABLE", "evidence_ids": []}})
        result = m.evaluate_declared_venue_matrix(make_payload([scope]), as_of=AS_OF)
        fields = {f.field_name: f for f in result.scopes[0].field_results}
        self.assertEqual(fields["bid"].derived_state, "DECLARED_UNAVAILABLE_UNVERIFIED")
        self.assertEqual(fields["ask"].derived_state, "NOT_DECLARED_IN_INPUT")
        with self.assertRaises(m.VenueMatrixError):
            scope["field_coverage"]["ask"]["evidence_ids"] = ["EV-1"]
            m.evaluate_declared_venue_matrix(make_payload([scope]), as_of=AS_OF)

    def test_utc_halfopen_and_real_dates(self):
        ev = make_evidence(observed="2024-02-29T00:00:00Z", valid_until="2024-03-01T00:00:00Z")
        payload = make_payload([make_scope(evidence=[ev])])
        self.assertEqual(m.evaluate_declared_venue_matrix(payload, as_of=ev["observed_at"]).scopes[0].evidence_results[0].temporal_state, "DECLARED_IN_WINDOW_UNVERIFIED")
        self.assertEqual(m.evaluate_declared_venue_matrix(payload, as_of=ev["valid_until"]).scopes[0].evidence_results[0].temporal_state, "DECLARED_EXPIRED")
        for bad in ("2023-02-29T00:00:00Z", "1969-12-31T23:59:59Z", "2026-01-01T00:00:60Z", "2026-01-01T00:00:00+00:00", "2026-01-01T00:00:00.000Z"):
            with self.subTest(bad=bad), self.assertRaises(m.VenueMatrixError):
                m.evaluate_declared_venue_matrix(payload, as_of=bad)
        for good in ("1970-01-01T00:00:00Z", "9999-12-31T23:59:59Z"):
            self.assertEqual(m.evaluate_declared_venue_matrix(payload, as_of=good).as_of, good)

    def test_surrogate_extreme_integer_nesting_and_argument_types(self):
        for bad in ("\ud800", '{"schema_version":' + '9' * 5000 + ',"scopes":[]}', '[' * 1200 + '0' + ']' * 1200):
            with self.subTest(kind=bad[:8]), self.assertRaises(m.VenueMatrixError):
                m.evaluate_declared_venue_matrix(bad, as_of=AS_OF)
        class TextSubclass(str): pass
        for payload, clock in [(b'{}', AS_OF), (TextSubclass('{}'), AS_OF), ('{}', TextSubclass(AS_OF)), ('{}', None)]:
            with self.assertRaises(m.VenueMatrixError): m.evaluate_declared_venue_matrix(payload, as_of=clock)

    def test_displayed_diagnostics_do_not_echo_payload(self):
        import traceback
        secret_marker = "SYNTHETIC_NEVER_REAL_SECRET"
        cases = [(secret_marker, AS_OF), ("\ud800", AS_OF), (make_payload([make_scope()]), "2026-02-30T00:00:00Z")]
        for payload, clock in cases:
            try: m.evaluate_declared_venue_matrix(payload, as_of=clock)
            except m.VenueMatrixError as exc:
                self.assertTrue(exc.__suppress_context__)
                shown = ''.join(traceback.format_exception_only(type(exc), exc))
                self.assertNotIn(secret_marker, shown)
                self.assertNotIn("JSONDecodeError", ''.join(traceback.format_exception(type(exc), exc, exc.__traceback__)))
            else: self.fail("Malformed synthetic input accepted")

    def test_no_mutable_containers_or_dict_in_returned_graph(self):
        from dataclasses import fields, is_dataclass, FrozenInstanceError
        result = m.evaluate_declared_venue_matrix(make_payload([make_scope(evidence=[make_evidence()])]), as_of=AS_OF)
        def walk(value):
            self.assertNotIsInstance(value, (dict, list, set))
            self.assertFalse(hasattr(value, "__dict__"))
            if isinstance(value, tuple):
                for item in value: walk(item)
            elif is_dataclass(value):
                for field in fields(value): walk(getattr(value, field.name))
                with self.assertRaises(FrozenInstanceError): setattr(value, fields(value)[0].name, "MUTATED")
            else: self.assertIs(type(value), str if isinstance(value, str) else bool if isinstance(value, bool) else int)
        walk(result)

    def test_broker_and_admission_value_injections_reject(self):
        for origin in ("broker", "PUBLIC", None, True):
            value = self.fixture(); value["scopes"][0]["data_origin"] = origin
            with self.assertRaises(m.VenueMatrixError): self.evaluate(value)
        for key in ("qualified_support", "runtime_enabled", "admission_authorized", "rights_status", "account_id", "bid_value"):
            value = self.fixture(); value["scopes"][0][key] = True
            with self.assertRaises(m.VenueMatrixError): self.evaluate(value)


if __name__ == "__main__":
    unittest.main()