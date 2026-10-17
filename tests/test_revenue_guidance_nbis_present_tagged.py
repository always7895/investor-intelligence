"""D5 present-tagged fence rows (BATCH10B GO D5), synthetic Scenario Z only; never NBIS admission or qualification.

The current-package statement gets one comparable us-gaap:Revenues fact for the Q4 operand (2031-10-01..2031-12-31,
shown 1,444.4 = 1444400000 USD, disclosed precision 0.1M). Disclosed half-up precision is the half-open interval
[1444350000, 1444450000): DISPLAY (the shown cell tagged) and HIDDEN 1444.35 verify, HIDDEN 1444.45 refuses, and two
disagreeing tagged values refuse instead of being averaged. Every row goes through the real builder, the attempt
validator and rederive on owned temporary stores (nbis_synthetic_sources.Scenario); nothing reaches the network.
"""
import unittest

from tests import nbis_synthetic_sources as f

CONTEXT_ID = "synthetic-d5-q4"
UNIT_ID = "synthetic-d5-usd"
US_GAAP = "http://fasb.org/us-gaap/2031"
ISO4217 = "http://www.xbrl.org/2003/iso4217"
DISPLAY_CELL = b"<td>1,444.4</td>"
ABSENCE = {"present": False, "policy": "FOREIGN_TABLE_TAGGED_ABSENCE_V1"}
Q4 = ("2031-10-01", "2031-12-31")
REFUSED = {"outcome": "BLOCKED", "reason": "SOURCE_DISAGREEMENT", "detail": "NBIS half-up disclosed-precision interval",
           "record": None, "decisions": []}


def fact(shown):
    return (f'<ix:nonFraction xmlns:us-gaap="{US_GAAP}" name="us-gaap:Revenues" contextRef="{CONTEXT_ID}" '
            f'unitRef="{UNIT_ID}" scale="6">{shown}</ix:nonFraction>').encode("ascii")


def header(hidden=b""):
    resources = (f'<ix:resources><xbrli:context id="{CONTEXT_ID}"><xbrli:entity>'
                 '<xbrli:identifier scheme="http://www.sec.gov/CIK">0001513845</xbrli:identifier></xbrli:entity>'
                 f'<xbrli:period><xbrli:startDate>{Q4[0]}</xbrli:startDate><xbrli:endDate>{Q4[1]}</xbrli:endDate>'
                 f'</xbrli:period></xbrli:context><xbrli:unit id="{UNIT_ID}"><xbrli:measure>iso4217:USD</xbrli:measure>'
                 '</xbrli:unit></ix:resources>').encode("ascii")
    hidden_block = b"<ix:hidden>" + hidden + b"</ix:hidden>" if hidden else b""
    return (f'<ix:header xmlns:xbrli="http://www.xbrl.org/2003/instance" xmlns:iso4217="{ISO4217}">'.encode("ascii")
            + hidden_block + resources + b"</ix:header>")


def proof(value):
    return {"concept": "us-gaap:Revenues", "namespace": US_GAAP, "context": CONTEXT_ID, "entity": "0001513845",
            "unit": UNIT_ID, "measure": "iso4217:USD", "measure_namespace": ISO4217, "start": Q4[0], "end": Q4[1],
            "scope": "COMPANY", "accounting_basis": "GAAP", "value": value}


def present(value):
    return {"present": True, "policy": "HALF_UP_HALF_OPEN", "value": value, "facts": [proof(value)],
            "lower_inclusive": "1444350000.00", "upper_exclusive": "1444450000.00"}


class PresentTaggedFenceRows(unittest.TestCase):
    def tagged_statement(self, raw, variant):
        # The displayed Q4 cell appears once in Financial Highlights and once in the statement of operations.
        self.assertEqual(raw.count(DISPLAY_CELL), 2)
        if variant == "DISPLAY":
            before, _, after = raw.rpartition(DISPLAY_CELL)
            raw = before + b"<td>" + fact("1,444.4") + b"</td>" + after
            return f.insert_before_body(self, raw, header())
        if variant == "CONFLICT":
            before, _, after = raw.rpartition(DISPLAY_CELL)
            raw = before + b"<td>" + fact("1,444.4") + b"</td>" + after
            return f.insert_before_body(self, raw, header(fact("1444.35")))
        return f.insert_before_body(self, raw, header(fact(variant)))

    def run_row(self, variant):
        with f.Scenario() as s:
            s.plan()
            key = s.event["packages"][0]["statement"]
            cap = s.loaded()[key]
            raw = self.tagged_statement(cap["raw"], variant)
            self.assertNotEqual(raw, cap["raw"])
            s.captures[key] = f.overlay.store_capture(s.root, raw, cap)

            def invoke():
                result = s.build()
                if result["outcome"] != "VERIFIED":
                    return result
                proofs = next(d["operands"]["tagged_proofs"] for d in result["decisions"] if d["kind"] == "CALENDAR")
                found = [(p["operand"]["capture"], p["operand"]["start"], p["operand"]["end"], p["tagged"])
                         for p in proofs if p["tagged"] != ABSENCE]
                actual = next(d["operands"]["tagged"] for d in result["decisions"]
                              if d["kind"] == "ACTUAL" and d["ref"] == Q4[1])
                others = [d["operands"]["tagged"] for d in result["decisions"]
                          if d["kind"] == "ACTUAL" and d["ref"] != Q4[1]]
                attempt = f.updater._attempt(s.lead["accession"], s.now, s.baseline, s.event, s.captures, result)
                valid = f.overlay.validate_attempt(attempt)
                again = f.overlay.rederive(s.root, s.profile, s.baseline, attempt, allow_replay=False, baseline=s.baseline)
                return {"outcome": result["outcome"], "reason": result["reason"], "detail": result["detail"],
                        "present_proofs": found, "q4_actual": actual,
                        "other_actuals_absent": len(others) == 3 and all(v == ABSENCE for v in others),
                        "attempt_valid": valid,
                        "rederive_equal": f.verify.canonical_json(again) == f.verify.canonical_json(result)}

            actual = f.outcome_of(invoke)
            f.observe_boundary("d5.present-tagged." + variant, actual)
            return key, actual

    def verified(self, key, value):
        return ("RESULT", {"outcome": "VERIFIED", "reason": None, "detail": "",
                           "present_proofs": [(key, Q4[0], Q4[1], present(value))], "q4_actual": present(value),
                           "other_actuals_absent": True, "attempt_valid": None, "rederive_equal": True})

    def test_display_cell_fact_equal_to_shown_value_verifies(self):
        key, actual = self.run_row("DISPLAY")
        self.assertEqual(actual, self.verified(key, "1444400000"))

    def test_hidden_fact_on_inclusive_lower_fence_verifies(self):
        key, actual = self.run_row("1444.35")
        self.assertEqual(actual, self.verified(key, "1444350000"))

    def test_hidden_fact_on_exclusive_upper_fence_refuses(self):
        _, actual = self.run_row("1444.45")
        self.assertEqual(actual, ("RESULT", REFUSED))

    def test_disagreeing_tagged_values_refuse_without_averaging(self):
        _, actual = self.run_row("CONFLICT")
        self.assertEqual(actual, ("RESULT", {"outcome": "BLOCKED", "reason": "SOURCE_DISAGREEMENT",
                                             "detail": "2031-10-01..2031-12-31 has 2 values across ['us-gaap:Revenues']",
                                             "record": None, "decisions": []}))


if __name__ == "__main__":
    unittest.main()
