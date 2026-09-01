from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import v213_serenity_h6b1_metric_semantic_guard_v10 as mod


class H6B1R15Tests(unittest.TestCase):
    def test_self_test(self) -> None:
        mod.self_test()

    def test_cjk_immediately_after_long_unit_is_quantitative(self) -> None:
        self.assertTrue(mod._future_is_quantitative_v10("約$144 million於未來12個月認列；非新增訂單預測"))
        self.assertTrue(mod._future_is_quantitative_v10("約$2,732.0 million（文件日2026-08-06）"))
        self.assertTrue(mod._future_is_quantitative_v10("約$3.2 billion；39%於未來12個月認列"))

    def test_cjk_immediately_after_short_unit_is_quantitative(self) -> None:
        self.assertTrue(mod._future_is_quantitative_v10("約$2.6M於未來12個月認列"))
        self.assertTrue(mod._future_is_quantitative_v10("約$7B；非新增訂單預測"))

    def test_ascii_suffix_is_rejected(self) -> None:
        self.assertFalse(mod._future_is_quantitative_v10("約$144 millionUSD於未來12個月認列"))
        self.assertFalse(mod._future_is_quantitative_v10("約$2.6MB於未來12個月認列"))

    def test_qualitative_future_remains_non_quantitative(self) -> None:
        self.assertFalse(
            mod._future_is_quantitative_v10(
                "未來12個月認列，但未提供可安全量化的比例；非新增訂單預測"
            )
        )


if __name__ == "__main__":
    unittest.main()
