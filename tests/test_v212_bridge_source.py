from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BRIDGE = ROOT / "run-v212-local-llm-bridge.ps1"


class V212BridgeSourceTests(unittest.TestCase):
    def test_wait_tunnel_does_not_bind_reserved_pid_variable(self) -> None:
        text = BRIDGE.read_text(encoding="utf-8-sig")
        self.assertNotRegex(text, r"(?i)function\s+Wait-TunnelUrl\s*\(\s*\[int\]\s*\$Pid\b")
        self.assertRegex(text, r"function\s+Wait-TunnelUrl\s*\(\s*\[int\]\s*\$ProcessId\b")
        self.assertIn("Get-Process -Id $ProcessId", text)

    def test_bridge_keeps_loopback_gateway_boundary(self) -> None:
        text = BRIDGE.read_text(encoding="utf-8-sig")
        self.assertIn("'--host','127.0.0.1'", text)
        self.assertIn("LOCAL_LLM_SHARED_SECRET", text)
        self.assertIn("LOCAL_LLM_ALLOWED_HOSTS", text)


if __name__ == "__main__":
    unittest.main()
