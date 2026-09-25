"""C2 rendering tests over real C1 assessments; text fixtures, not live evidence."""
from __future__ import annotations

from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))

import test_v213_forward_premises_shadow as c1  # noqa: E402
from v213_forward_comparison_render import (  # noqa: E402
    NOTICE, REVISED, TITLE, WITHHELD, ForwardRenderError, build_forward_comparison_artifact,
    render_forward_comparison_block,
)

READY = "\n".join((
    TITLE,
    "公司指引 2027-01-01/2027-12-31 營收：4,800 million USD（GAAP，consolidated；2 個獨立來源；主張 guidance）",
    "已申報基準 2025-01-01～2025-12-31 營收：4,000 USD（us-gaap:Revenues；accession 0000999001-26-000001；"
    "申報 2026-02-20；CIK 0000999001）",
    NOTICE,
))


class ForwardComparisonRenderTests(unittest.TestCase):
    def test_ready_pair_renders_exact_side_by_side_text(self):
        self.assertEqual(render_forward_comparison_block(c1.assess()), READY)

    def test_unresolved_premises_withhold_both_values(self):
        text = render_forward_comparison_block(c1.assess(base=c1.binding(alias=None)))
        self.assertEqual(text.splitlines()[:2], [TITLE, WITHHELD])
        self.assertIn("IDENTITY_ASSOCIATION（BASELINE_SYMBOL_ALIAS_ABSENT）", text)
        self.assertNotIn("CONSUMER_ADMISSION", text)
        for value in ("4,800", "4,000", "4800", "4000"):
            self.assertNotIn(value, text)

    def test_revised_baseline_is_disclosed(self):
        revised = c1.binding(facts=[c1.fact(), c1.fact(filed="2026-05-01", value=4100,
                                                       accn="0000999001-26-000002")])
        text = render_forward_comparison_block(c1.assess(base=revised))
        self.assertIn("4,100 USD", text)
        self.assertIn(REVISED, text)
        self.assertEqual(text.splitlines()[-1], NOTICE)

    def test_fractional_values_render_without_float_noise(self):
        claim = c1.forward_claim()
        result = c1.research(claim, values=(4800.5, 4800.5))
        self.assertIn("4,800.5 million USD", render_forward_comparison_block(c1.assess(claim=claim, result=result)))

    def test_local_artifact_is_digest_bound_and_never_publishable(self):
        import hashlib
        import json
        artifact = build_forward_comparison_artifact(c1.assess())
        self.assertEqual(artifact["text"], READY)
        self.assertIs(artifact["publication_eligible"], False)
        self.assertEqual(artifact["audience"], "OPERATOR_LOCAL_ONLY")
        body = {k: v for k, v in artifact.items() if k != "sha256"}
        canonical = json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        self.assertEqual(artifact["sha256"], hashlib.sha256(canonical).hexdigest())
        self.assertEqual(build_forward_comparison_artifact(c1.assess())["sha256"], artifact["sha256"])

    def test_rejects_non_assessment_input(self):
        for value in (None, {}, c1.assess().to_dict()):
            with self.subTest(value=type(value).__name__):
                with self.assertRaises(ForwardRenderError):
                    render_forward_comparison_block(value)


if __name__ == "__main__":
    unittest.main()
