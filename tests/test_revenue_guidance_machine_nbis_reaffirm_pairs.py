"""Scenario R (G4c) synthetic NBIS paired declarations, not genuine/native/live qualification.

Python rows mutate the live Scenario R chain's VERIFIED producer (validate_attempt = A, admit = B);
the TS rows of cloud/test/v213-revenue-guidance-machine-nbis-reaffirm.test.ts mutate the frozen
Scenario R fixture. The cross-language table checks DECLARED expectations only. Every literal is
designed from the code, not yet observed. M13/M13s are characterizations: the TS validator checks
the REAFFIRMATION offsets by shape only (TS_ADMITS_TODAY, an open product finding); Python refuses
them only by rederivation. No tracked profile is enabled here.
"""
import copy
import json
from pathlib import Path
import re
import shutil
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "scripts"), str(ROOT)]
from tests import nbis_e2e_support as h
from tests import nbis_synthetic_sources as f

CUTOFF_TEXT = h.CLOCKS["R"][2]
TS_ROWS = ROOT / "cloud/test/v213-revenue-guidance-machine-nbis-reaffirm.test.ts"

# JSON-shaped values deliberately distinguish declared lists from runtime tuples.
ROW_TABLE = [
    {"id": "C0", "kind": "CTRL", "py_a": ["RESULT", None], "py_b": ["RESULT", ["AUTO_VERIFIED", None]], "ts": [True, "AVAILABLE"]},
    {"id": "M13", "kind": "CHAR", "py_a": ["RESULT", None], "py_b": ["RESULT", ["BLOCKED", "APPROVAL_BINDING"]], "ts": [True, "AVAILABLE"]},
    {"id": "M13s", "kind": "CHAR", "py_a": ["RESULT", None], "py_b": ["RESULT", ["BLOCKED", "APPROVAL_BINDING"]], "ts": [True, "AVAILABLE"]},
    {"id": "R01", "kind": "NEG", "py_a": ["RESULT", None], "py_b": ["RESULT", ["BLOCKED", "APPROVAL_BINDING"]], "ts": [False, "UNAVAILABLE"]},
    {"id": "R02", "kind": "NEG", "py_a": ["RESULT", None], "py_b": ["RESULT", ["BLOCKED", "APPROVAL_BINDING"]], "ts": [False, "UNAVAILABLE"]},
    {"id": "R03", "kind": "NEG", "py_a": ["RAISED", "StateError", "ATTEMPT_NBIS_SCHEMA"], "py_b": ["RESULT", ["BLOCKED", "STATE_CORRUPT"]], "ts": [False, "UNAVAILABLE"]},
]


def shaped(value):
    return json.loads(json.dumps(value))


def shift(offsets):
    return [offsets[0] + 1, offsets[1] + 1]


def prepare(root, row_id):
    state = root / "state"
    gen = f.overlay.generation_at(state, CUTOFF_TEXT)
    profiles = f.verify.validate_profiles(json.loads((root / "profiles.json").read_bytes()))
    curated = {r["symbol"]: r for r in json.loads((root / "registry.json").read_bytes())["issuers"]}
    ident = f.overlay.identity((root / "profiles.json").read_bytes(), (root / "registry.json").read_bytes(), (root / "approval.json").read_bytes())
    entries = copy.deepcopy(gen["issuers"])
    entry = entries["NBIS"]
    producer = entry["open"][entry["index"]["verified"][-1]["position"]]
    decisions = producer["decisions"]
    package = next(p for p in producer["event"]["packages"] if p["accession"] == producer["event"]["accession"])
    current_state = next(d["operands"] for d in decisions if d["kind"] == "MEMBERSHIP" and d["ref"] == package["accession"])["guidance_state"]
    reaffirmation = next(d for d in decisions if d["kind"] == "REAFFIRMATION")
    current = reaffirmation["operands"]["current"]
    if row_id == "M13":
        # Both ends move together: span length and passage are unchanged, only the source position is wrong.
        current["offsets"] = shift(current["offsets"])
    elif row_id == "M13s":
        current_state["offsets"] = shift(current_state["offsets"])
    elif row_id == "R01":
        current["passage"] = current["passage"].replace(str(current["year"]), str(current["year"] + 1))
    elif row_id == "R02":
        decisions.remove(reaffirmation)
    elif row_id == "R03":
        current_state["kind"] = "ORIGINAL_RANGE"
    elif row_id != "C0":
        raise ValueError("UNKNOWN_ROW")
    return state, gen, profiles, curated, ident, entries, producer


class NbisReaffirmPairTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix="synthetic-g4c-pairs-")
        cls.addClassCleanup(cls.temp.cleanup)
        cls.base = Path(cls.temp.name) / "base"
        cls.base.mkdir()
        cls.chain = h.Chain(cls.base, mode="R")
        cls.chain.produce()

    def run_row(self, row):
        with tempfile.TemporaryDirectory(prefix="synthetic-g4c-row-") as tmp:
            holder = {}
            def validate():
                root = Path(tmp) / "copy"
                shutil.copytree(self.base, root)
                holder["args"] = prepare(root, row["id"])
                return f.overlay.validate_attempt(holder["args"][-1])
            a = f.outcome_of(validate)
            def admit():
                state, gen, profiles, curated, ident, entries, _ = holder["args"]
                result = f.overlay.admit(state, gen, CUTOFF_TEXT, profiles, curated, ident, allow_replay=False, entries=entries)["NBIS"]
                return result["mode"], result["reason"]
            b = f.outcome_of(admit)
            f.observe_boundary(row["id"] + "-A", a)
            f.observe_boundary(row["id"] + "-B", b)
            self.assertEqual(shaped(a), row["py_a"])
            self.assertEqual(shaped(b), row["py_b"])

    def test_99_R_DRIFT(self):
        def compare():
            text = TS_ROWS.read_text(encoding="utf-8")
            block = text.split("// ROWTABLE-BEGIN\n")[1].split("// ROWTABLE-END")[0].strip()
            match = re.fullmatch(r"const ROW_TABLE = (\[.*\]);", block, re.S)
            declared = json.loads(match.group(1))
            return (declared == ROW_TABLE and len({r["id"] for r in declared}) == len(declared), len(declared))
        actual = f.outcome_of(compare)
        f.observe_boundary("R-DRIFT", actual)
        self.assertEqual(actual, ("RESULT", (True, 6)))


def row_test(row):
    def test(self):
        self.run_row(row)
    return test


for index, row in enumerate(ROW_TABLE):
    setattr(NbisReaffirmPairTests, f"test_{index:02d}_{row['id']}", row_test(row))


if __name__ == "__main__":
    unittest.main()
