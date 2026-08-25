from __future__ import annotations

import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from manual_option_calculator_gate import audit_manual_option_calculator  # noqa: E402


class ManualOptionCalculatorGateTests(unittest.TestCase):
    def fixture_root(self) -> tuple[tempfile.TemporaryDirectory[str], Path]:
        temporary = tempfile.TemporaryDirectory()
        root = Path(temporary.name)
        for relative in (
            "cloud/src/manual-options.ts",
            "cloud/src/worker.ts",
            "cloud/test/manual-options.test.ts",
            "docs/MANUAL_OPTION_CALCULATOR.md",
        ):
            target = root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(ROOT / relative, target)
        return temporary, root

    def test_current_repository_passes_ephemeral_calculator_gate(self) -> None:
        self.assertEqual(audit_manual_option_calculator(), [])

    def test_network_or_storage_capability_is_rejected(self) -> None:
        temporary, root = self.fixture_root()
        try:
            path = root / "cloud" / "src" / "manual-options.ts"
            path.write_text(
                path.read_text(encoding="utf-8")
                + "\nasync function unsafe() { await fetch('https://example.test'); }\n",
                encoding="utf-8",
            )
            findings = audit_manual_option_calculator(root)
        finally:
            temporary.cleanup()
        self.assertTrue(any("forbidden capability" in finding for finding in findings))

    def test_worker_must_rate_limit_before_calculation(self) -> None:
        temporary, root = self.fixture_root()
        try:
            path = root / "cloud" / "src" / "worker.ts"
            text = path.read_text(encoding="utf-8")
            rate = '  if (!(await rateLimit(env, tenantId, query.intent))) {'
            block_start = text.index(rate)
            calculator = '  const manualOption = manualOptionQuoteAnswer(text);'
            calculator_start = text.index(calculator)
            calculator_end = text.index(
                "\n\n  const deterministic = await deterministicAnswer",
                calculator_start,
            )
            calculator_block = text[calculator_start:calculator_end]
            text = (
                text[:block_start]
                + calculator_block
                + "\n\n"
                + text[block_start:calculator_start]
                + text[calculator_end:]
            )
            path.write_text(text, encoding="utf-8")
            findings = audit_manual_option_calculator(root)
        finally:
            temporary.cleanup()
        self.assertTrue(any("after rate limiting" in finding for finding in findings))

    def test_model_or_broker_lineage_is_rejected(self) -> None:
        temporary, root = self.fixture_root()
        try:
            path = root / "cloud" / "src" / "manual-options.ts"
            path.write_text(
                path.read_text(encoding="utf-8")
                + "\nconst forbidden = 'fetch_options_ibkr';\n",
                encoding="utf-8",
            )
            findings = audit_manual_option_calculator(root)
        finally:
            temporary.cleanup()
        self.assertTrue(any("broker" in finding or "forbidden" in finding for finding in findings))


if __name__ == "__main__":
    unittest.main()
