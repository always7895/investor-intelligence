"""G4a P2 F1/F2 synthetic NBIS reaffirmation rows; no genuine NBIS qualification.

F1: a later letter reaffirming a DIFFERENT full year is refused by the same-FY
conjunct of auto_verify.nbis_reaffirmation, not by template/negation/numeric
branches (exactly one changed year). F2: the same-anchor guard of _build_nbis
for Scenario R (current letter later than the original), beyond its first
disjunct: an unknown predecessor reference day, and a reference on or after
the event filing day, with an admitted genuinely later control.
Stores are owned TemporaryDirectory roots (Scenario); nothing is enabled.
"""
import unittest

from tests import nbis_synthetic_sources as f

REAFFIRM = b"We are reaffirming our full-year 2034 guidance across all metrics."
WRONG_FY = "NBIS explicit all-metrics same-FY reaffirmation"
SAME_ANCHOR = "NBIS same-anchor without later reaffirmation"


def blocked(reason, detail):
    return ("RESULT", {"outcome": "BLOCKED", "reason": reason, "detail": detail, "record": None, "decisions": []})


class WrongFiscalYearReaffirmation(unittest.TestCase):
    def test_other_full_year_is_refused(self):
        for year in (b"2035", b"2033"):
            with self.subTest(year=year), f.Scenario("R") as s:
                s.plan()
                key = s.event["packages"][0]["letter"]
                previous = f.overlay.load_capture(s.root, s.captures[key])
                raw = previous["raw"]
                changed = raw.replace(REAFFIRM, REAFFIRM.replace(b"2034", year))
                s.captures[key] = f.overlay.store_capture(s.root, changed, previous)
                actual = f.outcome_of(s.build)
                f.observe_boundary("f1.wrong-fy." + year.decode("ascii"), actual)
                self.assertEqual((raw.count(REAFFIRM), changed.count(REAFFIRM)), (1, 0))
                self.assertEqual(actual, blocked("UNSUPPORTED_TEMPLATE", WRONG_FY))


class SameAnchorReference(unittest.TestCase):
    """Scenario R: predecessor anchor equals the current anchor 2034-06-30."""

    def outcome(self, published_date):
        with f.Scenario("R") as s:
            s.plan()
            self.assertEqual((s.event["filed"], s.event["packages"][1]["filed"]), ("2034-08-13", "2034-05-14"))
            s.baseline["reported_quarters"][0]["end"] = "2034-06-30"
            if published_date != "UNCHANGED":
                s.baseline["documents"][0]["published_date"] = published_date
            def invoke():
                result = s.build()
                if result["outcome"] != "VERIFIED":
                    return result
                return {"outcome": result["outcome"], "reason": result["reason"], "detail": result["detail"],
                        "reaffirmations": sum(d["kind"] == "REAFFIRMATION" for d in result["decisions"])}
            return f.outcome_of(invoke)

    def test_genuinely_later_reference_is_admitted(self):
        actual = self.outcome("UNCHANGED")
        f.observe_boundary("f2.same-anchor.later-control", actual)
        self.assertEqual(actual, ("RESULT", {"outcome": "VERIFIED", "reason": None, "detail": "", "reaffirmations": 1}))

    def test_unknown_or_not_earlier_reference_is_refused(self):
        rows = [("unknown-day", None), ("same-day", "2034-08-13"), ("later-day", "2034-08-14")]
        for label, published_date in rows:
            with self.subTest(row=label):
                actual = self.outcome(published_date)
                f.observe_boundary("f2.same-anchor." + label, actual)
                self.assertEqual(actual, blocked("OUT_OF_ORDER", SAME_ANCHOR))


if __name__ == "__main__":
    unittest.main()
