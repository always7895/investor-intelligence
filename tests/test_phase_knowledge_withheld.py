"""T11-F1A: inert phase_knowledge_withheld producer (industry_rotation), validator passthrough (macro builder),
Python/TypeScript parity vector and the hard rule that no knowledge date is ever derived."""
from __future__ import annotations

import builtins
import copy
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import build_v213_macro_industry_research as mb  # noqa: E402
import industry_rotation as rot  # noqa: E402
from test_industry_rotation import TODAY, config, post, sec_fetch  # noqa: E402

SYNTHETIC_FIVE_QUALIFIED = mb.SYNTHETIC_FIVE_QUALIFIED
VF_PATH = ROOT / "cloud/test/fixtures/phase-knowledge-withheld-parity-v1.json"
SAFE_MAX = 9007199254740991
Z = {"affected_industries": 0, "signals": 0}
BAD = ("RAISED", "ValueError", "INVALID_PHASE_KNOWLEDGE_WITHHELD")


def out(fn, *a):
    try:
        return ("RETURNED", fn(*a))
    except Exception as e:  # noqa: BLE001 - the observation itself is the test subject
        return ("RAISED", type(e).__name__, str(e))


def row(i, ids):
    return {"industry_id": i, "phase": {"withheld_signal_ids": ids}}


def block(a, s):
    return {"affected_industries": a, "signals": s}


def build_doc():
    return rot.build_rotation(config(), fetch_sec=sec_fetch(), post_bls=post, today=TODAY, member_cache=None, bls_cache=None)


class ProducerTests(unittest.TestCase):
    def test_empty_rows_unknown(self):
        self.assertEqual(out(rot.phase_knowledge_withheld, []), ("RETURNED", None))

    def test_verified_zero(self):
        self.assertEqual(out(rot.phase_knowledge_withheld, [row("a", [])]), ("RETURNED", Z))
        self.assertEqual(out(rot.phase_knowledge_withheld, [row("a", []), row("b", [])]), ("RETURNED", Z))

    def test_positive_counts_not_merged(self):
        rows = [row("a", ["s1", "s2"]), row("b", ["s3"])]
        self.assertEqual(out(rot.phase_knowledge_withheld, rows), ("RETURNED", block(2, 3)))

    def test_same_id_union_order_independent(self):
        rows = [row("a", ["s1", "s2"]), row("a", ["s1"])]
        self.assertEqual(out(rot.phase_knowledge_withheld, rows), ("RETURNED", block(1, 2)))
        self.assertEqual(out(rot.phase_knowledge_withheld, list(reversed(rows))), ("RETURNED", block(1, 2)))

    def test_unknown_row_blocks_zero(self):
        cases = [
            [row("a", []), {"industry_id": "b", "phase": {}}],
            [row("a", []), "x"],
            [row("a", []), {"industry_id": "b", "phase": {"withheld_signal_ids": None}}],
            [row("a", []), row("b", ["s", " "])],
            [row("a", []), row("b", [1])],
            [row("a", []), row("b", ("s1",))],
            [row("", [])],
            [row(" a", [])],
            [row(None, [])],
            [{"industry_id": "a"}],
        ]
        for i, rows in enumerate(cases):
            with self.subTest(case=i):
                self.assertEqual(out(rot.phase_knowledge_withheld, rows), ("RETURNED", None))

    def test_unknown_rows_are_lower_bound(self):
        rows = [row("a", ["s1"]), {"industry_id": "b", "phase": {}}]
        self.assertEqual(out(rot.phase_knowledge_withheld, rows), ("RETURNED", block(1, 1)))
        rows = [row("a", ["s1"]), row("b", ["s2", " "])]
        self.assertEqual(out(rot.phase_knowledge_withheld, rows), ("RETURNED", block(1, 1)))

    def test_safe_integer_bound(self):
        for offsets, expected in (
            ((0, SAFE_MAX - 1), ("RETURNED", block(1, SAFE_MAX))),
            ((0, SAFE_MAX), ("RETURNED", None)),
            ((SAFE_MAX, 0), ("RETURNED", None)),
        ):
            offs = iter(offsets)
            with self.subTest(offsets=offsets):
                with patch.object(rot, "sum", create=True, new=lambda it: builtins.sum(it) + next(offs)):
                    self.assertEqual(out(rot.phase_knowledge_withheld, [row("a", ["s1"])]), expected)

    def test_rotation_key_omitted_when_unknown(self):
        doc = build_doc()
        self.assertEqual("phase_knowledge_withheld" in doc, False)

    def test_rotation_key_present_when_known(self):
        real = rot.thesis_phase.assess_phase

        def wrapper_with(first):
            calls = []

            def w(*a, **k):
                result = copy.deepcopy(real(*a, **k))
                calls.append(1)
                result["withheld_signal_ids"] = list(first) if len(calls) == 1 else []
                return result
            return w

        with patch.object(rot.thesis_phase, "assess_phase", wrapper_with(["x-1", "x-2"])):
            doc = build_doc()
        self.assertEqual(out(lambda: doc["phase_knowledge_withheld"]), ("RETURNED", block(1, 2)))
        with patch.object(rot.thesis_phase, "assess_phase", wrapper_with([])):
            doc2 = build_doc()
        self.assertEqual(out(lambda: doc2["phase_knowledge_withheld"]), ("RETURNED", Z))


class MacroTests(unittest.TestCase):
    def test_validator_none_when_absent(self):
        for value in (None, {}, "x", {"a": 1}):
            with self.subTest(value=value):
                self.assertEqual(out(mb.validated_phase_knowledge_withheld, value), ("RETURNED", None))

    def test_validator_accepts_exact_blocks(self):
        for b in (Z, block(2, 5), block(1, 1), block(SAFE_MAX, SAFE_MAX)):
            with self.subTest(block=b):
                self.assertEqual(out(mb.validated_phase_knowledge_withheld, {"phase_knowledge_withheld": b}), ("RETURNED", b))

    def test_validator_refuses_malformed(self):
        values = [None, [], {}, {"affected_industries": 1}, {"affected_industries": 1, "signals": 1, "x": 1},
                  block("1", "1"), block(True, True), block(1.0, 1.0), block(-1, -1),
                  block(SAFE_MAX + 1, SAFE_MAX + 1), block(0, 1), block(1, 0), block(3, 2)]
        for i, value in enumerate(values):
            with self.subTest(case=i):
                self.assertEqual(out(mb.validated_phase_knowledge_withheld, {"phase_knowledge_withheld": value}), BAD)

    def test_overview_passthrough(self):
        q, _ = mb.evaluate_candidates(copy.deepcopy(SYNTHETIC_FIVE_QUALIFIED))
        rot0 = {"method": "m", "as_of": "2026-09-25", "quarter": "2026 Q2", "receipts": []}
        self.assertEqual(
            out(lambda: mb.build_macro_overview_output(q, [], rotation={**rot0, "phase_knowledge_withheld": block(2, 5)})["phase_knowledge_withheld"]),
            ("RETURNED", block(2, 5)))
        report = mb.build_macro_overview_output(q, [], rotation=rot0)
        self.assertEqual("phase_knowledge_withheld" in report, False)
        report = mb.build_macro_overview_output(q, [], rotation=None)
        self.assertEqual("phase_knowledge_withheld" in report, False)

    def test_overview_refuses_malformed(self):
        q, _ = mb.evaluate_candidates(copy.deepcopy(SYNTHETIC_FIVE_QUALIFIED))
        rot0 = {"method": "m", "as_of": "2026-09-25", "quarter": "2026 Q2", "receipts": []}
        self.assertEqual(
            out(lambda: mb.build_macro_overview_output(q, [], rotation={**rot0, "phase_knowledge_withheld": block(True, True)})), BAD)


class ParityTests(unittest.TestCase):
    @staticmethod
    def vectors():
        return json.loads(VF_PATH.read_text(encoding="utf-8"))["vectors"]

    def test_vectors_py(self):
        vectors = self.vectors()
        self.assertEqual(len(vectors), 19)
        for v in vectors:
            with self.subTest(vector=v["id"]):
                parsed = json.loads(v["json"])
                expected = ("RETURNED", parsed) if v["py"] == "ACCEPT" else BAD
                self.assertEqual(out(mb.validated_phase_knowledge_withheld, {"phase_knowledge_withheld": parsed}), expected)

    def test_emit_binding(self):
        by_prefix = {v["id"].split("-")[0]: v["json"] for v in self.vectors()}
        self.assertEqual(json.dumps(rot.phase_knowledge_withheld([row("a", [])]), separators=(",", ":")), by_prefix["v01"])
        self.assertEqual(json.dumps(rot.phase_knowledge_withheld([row("a", ["s1", "s2"]), row("b", ["s3"])]),
                                    separators=(",", ":")), by_prefix["v02"])

    def test_declared_divergence(self):
        self.assertEqual([v["id"] for v in self.vectors() if v["py"] != v["ts"]], ["v12-float-integral"])


class HardRuleTests(unittest.TestCase):
    def test_no_announced_at_derivation(self):
        for name in ("industry_rotation.py", "build_v213_macro_industry_research.py"):
            text = (ROOT / "scripts" / name).read_text(encoding="utf-8")
            self.assertEqual(text.count("announced"), 0, name)
        doc = build_doc()
        self.assertEqual('"announced_at"' in json.dumps(doc), False)

    def test_serenity_logic_documents_carrier(self):
        text = (ROOT / "skills/serenity-public-research/references/SERENITY_LOGIC.md").read_text(encoding="utf-8")
        self.assertEqual(text.count("`phase_knowledge_withheld`"), 1)
        self.assertEqual(text.count("announced_at"), 0)


if __name__ == "__main__":
    unittest.main()
