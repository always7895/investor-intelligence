"""W1 guard: the legacy thesis phase is displayed only as the labelled legacy admission gate (WORKER05 pattern).

Inventory 2026-10-10: in cloud/src only deep-analysis.ts and potential-ranking.ts render phase labels, both behind
舊版准入狀態, and line-theme.ts paints the phase ladder without text labels. The remaining displayed bare legacy label
was the Python deep-report 資料階段 section, which now names the gate, the operating phase and the financing view
apart. Source reads only; no network, subprocess or file write.
"""
from __future__ import annotations

import copy
import unittest
from pathlib import Path

from tests.test_company_deep_report import CONFIG, FACTS, ROTATION, TODAY, cdr
from tests.test_thesis_phase import STORY, sig, tp

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "cloud" / "src"
LABEL_RENDERERS = {"v213/deep-analysis.ts", "v213/potential-ranking.ts"}
LADDER = "v213/line-theme.ts"
PHASE_TEXT = ("已失效", "資料階段", "受阻（", "初現（", "驗證中（", "商業驗證（", "法人進場", "共識擁擠", "緩解中")
PHASE_ENUMS = ("BROKEN", "RELIEVING", "EARLY_VALIDATION", "COMMERCIAL_VALIDATION", "INSTITUTIONAL_VALIDATION")
GATE = "舊版准入狀態"


def worker_sources():
    return {path.relative_to(SRC).as_posix(): path.read_text(encoding="utf-8") for path in sorted(SRC.rglob("*.ts"))}


class WorkerLabelInventoryTests(unittest.TestCase):
    def test_no_worker_file_outside_the_reviewed_renderers_shows_a_phase_label(self):
        sources = worker_sources()
        self.assertTrue(LABEL_RENDERERS | {LADDER} <= set(sources))
        for name, text in sources.items():
            if name in LABEL_RENDERERS:
                continue
            with self.subTest(file=name):
                self.assertEqual([token for token in PHASE_TEXT if token in text], [])
                if name != LADDER:
                    self.assertEqual([token for token in PHASE_ENUMS if token in text], [])

    def test_bare_legacy_labels_are_gone_and_every_render_site_names_the_gate(self):
        sources = worker_sources()
        for name, text in sources.items():
            with self.subTest(file=name):
                self.assertNotIn("已失效", text)
                self.assertNotIn("資料階段", text)
        for name in sorted(LABEL_RENDERERS):
            text = sources[name]
            sites = [line for line in text.splitlines()
                     if ("PHASE_ZH[" in line or "legacyGateLabel(" in line) and "function legacyGateLabel(" not in line]
            with self.subTest(file=name):
                self.assertTrue(sites)
                self.assertEqual([line.strip() for line in sites if GATE not in line], [])
        deep = sources["v213/deep-analysis.ts"]
        self.assertEqual(deep.count("PHASE_NAME["), 1)  # read only inside the closed own-key helper
        self.assertIn("Object.prototype.hasOwnProperty.call(PHASE_NAME, phase)", deep)


class PythonLabelSourceTests(unittest.TestCase):
    def test_deep_report_never_shows_a_finance_only_block_as_a_failed_thesis(self):
        facts = copy.deepcopy(FACTS)
        facts["facts"]["us-gaap"]["WeightedAverageNumberOfDilutedSharesOutstanding"]["units"]["shares"][0]["val"] = 130
        report = cdr.build_report("SYN", "0000000001", facts=facts, submissions={"sic": "3674"}, business=None,
                                  rotation=ROTATION, rotation_config=CONFIG, today=TODAY)
        self.assertEqual(report["phase"]["phase"], "BROKEN")
        text = {s["title"]: s["text"] for s in report["sections"]}
        self.assertTrue(text["資料階段"].startswith(GATE + "：受阻（可能含融資條件，不等同營運論點失效）；營運階段："))
        self.assertFalse(any("已失效" in s["text"] for s in report["sections"]))

    def test_industry_outlook_label_can_never_carry_a_broken_gate(self):
        # industry_rotation's own 資料階段 outlook stays a bare label: industry scope excludes falsifiers entirely.
        signals = STORY + [sig("DILUTION", "2025-09-30", "issuer", value=40), sig("ATM_CAPACITY", "2025-09-30", "issuer", value=90),
                           sig("THESIS_KILLER", "2025-09-30", "issuer"), sig("CUSTOMER_LOSS", "2025-09-30", "issuer")]
        policy = tp.load_policy()
        for when in ("2025-03-05", "2025-10-03", "2026-02-05"):
            with self.subTest(when=when):
                self.assertNotEqual(tp.assess_phase(signals, when, policy=policy, scope="industry")["phase"], "BROKEN")


if __name__ == "__main__":
    unittest.main()
