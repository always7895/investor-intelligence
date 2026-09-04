from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import v212_local_llm_gateway as gateway  # noqa: E402


class LocalLlmGatewayTests(unittest.TestCase):
    def test_generic_ticker_parsing_and_option_intent(self) -> None:
        self.assertEqual(gateway.extract_ticker("ABCD 評分"), "ABCD")
        self.assertEqual(gateway.extract_ticker("XYZ呢"), "XYZ")
        self.assertIsNone(gateway.extract_ticker("你好"))
        self.assertTrue(gateway.asks_options("ABCD 這週 sell call"))

    def test_llama_upstream_must_be_loopback(self) -> None:
        with patch.dict(os.environ, {"II_LLAMA_BASE_URL": "http://127.0.0.1:9999"}, clear=False):
            self.assertEqual(gateway.llama_base_url(), "http://127.0.0.1:9999")
        with patch.dict(os.environ, {"II_LLAMA_BASE_URL": "https://example.com"}, clear=False):
            with self.assertRaises(RuntimeError):
                gateway.llama_base_url()

    def test_source_ensemble_requires_independent_successes(self) -> None:
        ok = lambda source: gateway.SourceResult(source, True, "2026-08-31T00:00:00Z", {"ok": True})
        miss = lambda source: gateway.SourceResult(source, False, "2026-08-31T00:00:00Z", {}, "NO_DATA")
        with (
            patch.object(gateway, "collect_sec", return_value=ok("sec_edgar")),
            patch.object(gateway, "collect_yahoo", return_value=ok("yahoo_finance_public_unofficial")),
            patch.object(gateway, "collect_gleif", return_value=ok("gleif_lei")),
            patch.object(gateway, "collect_bls", return_value=miss("bls_public_data")),
            patch.object(gateway, "collect_world_bank", return_value=ok("world_bank_indicators")),
        ):
            context = gateway.build_source_context("ABCD", "ABCD 怎麼看")
        self.assertEqual(context["source_diversity_status"], "PASS")
        self.assertGreaterEqual(context["successful_source_family_count"], 3)
        self.assertEqual(len(set(context["successful_source_families"])), context["successful_source_family_count"])

    def test_source_failures_remain_explicit_and_degrade(self) -> None:
        ok = lambda source: gateway.SourceResult(source, True, "2026-08-31T00:00:00Z", {"ok": True})
        miss = lambda source: gateway.SourceResult(source, False, "2026-08-31T00:00:00Z", {}, "NO_DATA")
        with (
            patch.object(gateway, "collect_sec", return_value=miss("sec_edgar")),
            patch.object(gateway, "collect_yahoo", return_value=ok("yahoo_finance_public_unofficial")),
            patch.object(gateway, "collect_gleif", return_value=miss("gleif_lei")),
            patch.object(gateway, "collect_bls", return_value=ok("bls_public_data")),
            patch.object(gateway, "collect_world_bank", return_value=miss("world_bank_indicators")),
        ):
            context = gateway.build_source_context("XYZ", "XYZ 怎麼看")
        self.assertEqual(context["source_diversity_status"], "DEGRADED")
        failed = [item for item in context["sources"] if not item["ok"]]
        self.assertTrue(failed)
        self.assertTrue(all(item["error"] for item in failed))

    def test_option_question_requests_on_demand_public_chain(self) -> None:
        ok = lambda source: gateway.SourceResult(source, True, "2026-08-31T00:00:00Z", {"ok": True})
        with (
            patch.object(gateway, "collect_sec", return_value=ok("sec_edgar")),
            patch.object(gateway, "collect_gleif", return_value=ok("gleif_lei")),
            patch.object(gateway, "collect_bls", return_value=ok("bls_public_data")),
            patch.object(gateway, "collect_world_bank", return_value=ok("world_bank_indicators")),
            patch.object(gateway, "collect_yahoo", return_value=ok("yahoo_finance_public_unofficial")) as yahoo,
        ):
            gateway.build_source_context("ABCD", "ABCD sell call")
        yahoo.assert_called_once_with("ABCD", include_options=True)


if __name__ == "__main__":
    unittest.main()
