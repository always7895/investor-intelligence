from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import v213_serenity_h6b1_metric_semantic_guard_v9 as mod


class H6B1R14Tests(unittest.TestCase):
    def test_self_test(self) -> None:
        mod.self_test()

    def test_existing_quantitative_inference_is_preserved(self) -> None:
        url = "https://www.sec.gov/Archives/edgar/data/1/000000000000000001/company.htm"
        row = mod.base._outlook(
            "SEC揭露RPO（剩餘履約義務；非全部客戶訂單）約$4.9 billion（文件日2026-08-01）；RPO常排除短期合約，不能視為公司全部客戶訂單",
            "公司預期約43%的該RPO於未來12個月認列；這是既有合約履約節奏，非新增訂單預測",
            current_urls=[url],
            future_urls=[url],
            confidence="HIGH_SEC_RPO_SEMANTICALLY_SCOPED",
            as_of="2026-08-01",
            current_classification="SUPPORTED",
            future_classification="INFERENCE",
        )

        def fail_raw(_url: str) -> str:
            raise AssertionError("quantitative rows must not be re-fetched")

        def fail_text(_url: str) -> str:
            raise AssertionError("quantitative rows must not be re-fetched")

        self.assertEqual(
            mod._quantitative_upgrade_same_accession(row, raw_fetcher=fail_raw, text_fetcher=fail_text),
            row,
        )

    def test_unavailable_future_is_not_promoted_by_r14(self) -> None:
        url = "https://www.sec.gov/Archives/edgar/data/1/000000000000000001/company.htm"
        row = mod.base._outlook(
            "SEC揭露RPO（剩餘履約義務；非全部客戶訂單）約$4.9 billion（文件日2026-08-01）；RPO常排除短期合約，不能視為公司全部客戶訂單",
            mod.base.FUTURE_FALLBACK,
            current_urls=[url],
            confidence="HIGH_SEC_RPO_SEMANTICALLY_SCOPED",
            as_of="2026-08-01",
            current_classification="SUPPORTED",
            future_classification="UNAVAILABLE",
        )

        def fail_raw(_url: str) -> str:
            raise AssertionError("R14 must not replace R13's unavailable policy")

        def fail_text(_url: str) -> str:
            raise AssertionError("R14 must not replace R13's unavailable policy")

        self.assertEqual(
            mod._quantitative_upgrade_same_accession(row, raw_fetcher=fail_raw, text_fetcher=fail_text),
            row,
        )

    def test_quantitative_detector(self) -> None:
        self.assertTrue(mod._future_is_quantitative("約43%於未來12個月認列；非新增訂單預測"))
        self.assertTrue(mod._future_is_quantitative("約$144 million於未來12個月認列；非新增訂單預測"))
        self.assertTrue(mod._future_is_quantitative("約三分之一於未來12個月認列；非新增訂單預測"))
        self.assertFalse(mod._future_is_quantitative("未來12個月認列，但未提供可安全量化的比例；非新增訂單預測"))


if __name__ == "__main__":
    unittest.main()
