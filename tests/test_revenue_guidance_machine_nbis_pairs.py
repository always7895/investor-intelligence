"""Synthetic NBIS paired declarations, not genuine/native/live qualification.

D8-D11 are characterization pins, not fixes. The cross-language table checks
DECLARED expectations only. M12 TS_ADMITS_TODAY is owned by a later product lane.
M13 and Scenario R are NOT_EXERCISED. No tracked profile is enabled here.
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
import revenue_guidance_machine as machine
from tests import nbis_e2e_support as h
from tests import nbis_synthetic_sources as f

# JSON-shaped values deliberately distinguish declared lists from runtime tuples.
ROW_TABLE = [
    {"id": "C0", "kind": "CTRL", "py_a": ["RESULT", None], "py_b": ["RESULT", ["AUTO_VERIFIED", None]], "ts": [True, "AVAILABLE"]},
    {"id": "M01", "kind": "CHAR", "py_a": ["RESULT", None], "py_b": ["RESULT", ["BLOCKED", "APPROVAL_BINDING"]], "ts": [False, "UNAVAILABLE"]},
    {"id": "M02", "kind": "NEG", "py_a": ["RAISED", "StateError", "ATTEMPT_NBIS_SCHEMA"], "py_b": ["RESULT", ["BLOCKED", "STATE_CORRUPT"]], "ts": [False, "UNAVAILABLE"]},
    {"id": "M03", "kind": "NEG", "py_a": ["RAISED", "StateError", "ATTEMPT_NBIS_SCHEMA"], "py_b": ["RESULT", ["BLOCKED", "STATE_CORRUPT"]], "ts": [False, "UNAVAILABLE"]},
    {"id": "M04", "kind": "NEG", "py_a": ["RAISED", "StateError", "ATTEMPT_NBIS_SCHEMA"], "py_b": ["RESULT", ["BLOCKED", "STATE_CORRUPT"]], "ts": [False, "UNAVAILABLE"]},
    {"id": "M05", "kind": "CHAR", "py_a": ["RESULT", None], "py_b": ["RESULT", ["BLOCKED", "APPROVAL_BINDING"]], "ts": [False, "UNAVAILABLE"]},
    {"id": "M06", "kind": "NEG", "py_a": ["RAISED", "StateError", "ATTEMPT_NBIS_SCHEMA"], "py_b": ["RESULT", ["BLOCKED", "STATE_CORRUPT"]], "ts": [False, "UNAVAILABLE"]},
    {"id": "M06b", "kind": "CHAR", "py_a": ["RESULT", None], "py_b": ["RESULT", ["BLOCKED", "APPROVAL_BINDING"]], "ts": [False, "UNAVAILABLE"]},
    {"id": "M07c", "kind": "CTRL", "py_a": ["RESULT", None], "py_b": ["RESULT", ["AUTO_VERIFIED", None]], "ts": [True, "AVAILABLE"]},
    {"id": "M07", "kind": "NEG", "py_a": ["RAISED", "StateError", "ATTEMPT_CAPTURES"], "py_b": ["RESULT", ["BLOCKED", "STATE_CORRUPT"]], "ts": [False, "UNAVAILABLE"]},
    {"id": "M08", "kind": "NEG", "py_a": ["RESULT", None], "py_b": ["RESULT", ["BLOCKED", "APPROVAL_BINDING"]], "ts": [False, "UNAVAILABLE"]},
    {"id": "M09", "kind": "NEG", "py_a": ["RAISED", "StateError", "ATTEMPT_CAPTURES"], "py_b": ["RESULT", ["BLOCKED", "STATE_CORRUPT"]], "ts": [False, "UNAVAILABLE"]},
    {"id": "M10c", "kind": "CTRL", "py_a": ["RESULT", "dict"], "py_b": None, "ts": [True, "AVAILABLE"]},
    {"id": "M10", "kind": "NEG", "py_a": ["RAISED", "MachinePublicationBlocked", "MACHINE_EVIDENCE_LIMIT"], "py_b": None, "ts": [False, "UNAVAILABLE"]},
    {"id": "M11", "kind": "CHAR", "py_a": ["RESULT", None], "py_b": ["RESULT", ["BLOCKED", "APPROVAL_BINDING"]], "ts": [False, "UNAVAILABLE"]},
    {"id": "M12", "kind": "CHAR", "py_a": ["RESULT", None], "py_b": ["RESULT", ["BLOCKED", "APPROVAL_BINDING"]], "ts": [True, "AVAILABLE"]},
]


def shaped(value):
    return json.loads(json.dumps(value))


def replace_dash(value):
    if isinstance(value, dict):
        return {k: replace_dash(v) for k, v in value.items()}
    if isinstance(value, list):
        return [replace_dash(v) for v in value]
    return value.replace("\u2013", "-") if isinstance(value, str) else value


def extra_triple():
    return {"channel": "ISSUER_IR", "id": "https://example.invalid/synthetic-g4b3-extra", "date": "2032-02-19"}


def prepare(root, row_id):
    state = root / "state"
    gen = f.overlay.generation_at(state, h.CUTOFF_TEXT)
    profiles = f.verify.validate_profiles(json.loads((root / "profiles.json").read_bytes()))
    curated = {r["symbol"]: r for r in json.loads((root / "registry.json").read_bytes())["issuers"]}
    ident = f.overlay.identity((root / "profiles.json").read_bytes(), (root / "registry.json").read_bytes(), (root / "approval.json").read_bytes())
    entries = copy.deepcopy(gen["issuers"])
    entry = entries["NBIS"]
    producer = entry["open"][entry["index"]["verified"][-1]["position"]]
    decisions = producer["decisions"]
    op = lambda kind: next(d["operands"] for d in decisions if d["kind"] == kind)
    package = next(p for p in producer["event"]["packages"] if p["accession"] == producer["event"]["accession"])
    membership = next(d["operands"] for d in decisions if d["kind"] == "MEMBERSHIP" and d["ref"] == package["accession"])
    if row_id == "M01":
        op("FY_RECONCILIATION")["operand"] = copy.deepcopy(op("CALENDAR")["proofs"][0])
    elif row_id == "M02":
        op("CALENDAR")["tagged_proofs"].pop()
    elif row_id == "M03":
        next(d for d in decisions if d["kind"] == "ACTUAL" and d["ref"].endswith("-12-31"))["operands"]["derivation"]["operation"] = "SIX_MONTHS_MINUS_FINAL_QUARTER"
    elif row_id == "M04":
        del membership["link_accounts"][package["statement"]]
    elif row_id == "M05":
        op("ROUTING")["consumed"].append(extra_triple())
    elif row_id == "M06":
        producer["decisions"] = replace_dash(decisions)
    elif row_id == "M06b":
        sc = op("CLAIM")["scope_context"]
        sc["quote"] = sc["quote"].replace("$9.0B", "$8.0B")
    elif row_id in ("M07c", "M07"):
        target = 32 if row_id == "M07c" else 33
        sha = producer["captures"][package["statement"]]
        n = len(producer["captures"])
        for index in range(target - n):
            producer["captures"][f"nbis:{package['accession']}:member:pad{index:02d}"] = sha
    elif row_id == "M08":
        sha = producer["captures"][package["statement"]]
        path = state / "captures" / sha[:2] / (sha + ".json")
        full = json.loads(path.read_bytes())
        if set(full) != f.overlay.CAPTURE_META_KEYS:
            raise ValueError("CAPTURE_META_KEYS")
        full["role"] = "REPLAY_NBIS_ACTUALS_STATEMENT"
        path.write_text(json.dumps(full, sort_keys=True), encoding="utf-8")
    elif row_id == "M09":
        producer["event"]["adapter"] = "SEC_8K_202_INLINE_XBRL_V1"
    elif row_id == "M11":
        producer["event"]["later_documents"].append({**extra_triple(), "label": "Synthetic later material", "disposition": "POSSIBLY_RELEVANT"})
    elif row_id == "M12":
        body = membership["report_period"]["body"][0]
        body["quote"] = "X" + body["quote"][1:]
    elif row_id != "C0":
        raise ValueError("UNKNOWN_ROW")
    return state, gen, profiles, curated, ident, entries, producer


def bundle(target):
    fixture = json.loads((ROOT / "tests/fixtures/revenue-guidance-machine-nbis-auto-functional.json").read_bytes())
    report, binding = json.loads(fixture["report"]), json.loads(fixture["binding"])
    envelope = report["top"][2]["outlook"]["order_forecast_v3"]
    base = len(machine.compact(envelope, machine.ENVELOPE_BYTES))
    envelope["machine"]["producer_canonical_json"] += " " * (target - base)
    report_raw = machine.compact(report, machine.REPORT_BYTES)
    binding["report_sha256"] = machine.sha256(report_raw)
    binding_raw = machine.compact(binding, machine.BINDING_BYTES)
    size = len(machine.compact(envelope, 10 ** 9))
    return size, binding["report_sha256"] == machine.sha256(report_raw), report_raw, binding_raw


def limit_outcome(report_raw, binding_raw):
    return type(machine.validate_public_bundle(report_raw, binding_raw, machine.sha256(report_raw), machine.sha256(binding_raw))).__name__


class NbisPairTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix="synthetic-g4b3-pairs-")
        cls.addClassCleanup(cls.temp.cleanup)
        cls.base = Path(cls.temp.name) / "base"
        cls.base.mkdir()
        cls.chain = h.Chain(cls.base)
        cls.chain.produce()

    def run_row(self, row):
        if row["id"] in ("M10c", "M10"):
            # Check construction separately from the product limit outcome.
            # No overlay admission B; py_b=null makes that non-exercise explicit.
            target = 256000 if row["id"] == "M10c" else 256001
            size, sha_ok, report_raw, binding_raw = bundle(target)
            self.assertEqual((size, sha_ok), (target, True))
            actual = f.outcome_of(lambda: limit_outcome(report_raw, binding_raw))
            f.observe_boundary(row["id"] + "-A", actual)
            self.assertEqual(shaped(actual), row["py_a"])
            return
        with tempfile.TemporaryDirectory(prefix="synthetic-g4b3-row-") as tmp:
            holder = {}
            def validate():
                root = Path(tmp) / "copy"
                shutil.copytree(self.base, root)
                holder["args"] = prepare(root, row["id"])
                return f.overlay.validate_attempt(holder["args"][-1])
            a = f.outcome_of(validate)
            def admit():
                state, gen, profiles, curated, ident, entries, _ = holder["args"]
                result = f.overlay.admit(state, gen, h.CUTOFF_TEXT, profiles, curated, ident, allow_replay=False, entries=entries)["NBIS"]
                return result["mode"], result["reason"]
            b = f.outcome_of(admit)
            f.observe_boundary(row["id"] + "-A", a)
            f.observe_boundary(row["id"] + "-B", b)
            self.assertEqual(shaped(a), row["py_a"])
            self.assertEqual(shaped(b), row["py_b"])

    def test_99_PP_DRIFT(self):
        def compare():
            text = (ROOT / "cloud/test/v213-revenue-guidance-machine-nbis-pairs.test.ts").read_text(encoding="utf-8")
            block = text.split("// ROWTABLE-BEGIN\n")[1].split("// ROWTABLE-END")[0].strip()
            match = re.fullmatch(r"const ROW_TABLE = (\[.*\]);", block, re.S)
            declared = json.loads(match.group(1))
            return (declared == ROW_TABLE and len({r["id"] for r in declared}) == len(declared), len(declared))
        actual = f.outcome_of(compare)
        f.observe_boundary("PP-DRIFT", actual)
        self.assertEqual(actual, ("RESULT", (True, 16)))


def row_test(row):
    def test(self):
        self.run_row(row)
    return test


for index, row in enumerate(ROW_TABLE):
    setattr(NbisPairTests, f"test_{index:02d}_{row['id']}", row_test(row))


if __name__ == "__main__":
    unittest.main()
