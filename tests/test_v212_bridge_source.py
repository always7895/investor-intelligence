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

    def test_quick_tunnel_health_waits_for_dns_and_edge_readiness(self) -> None:
        text = BRIDGE.read_text(encoding="utf-8-sig")
        self.assertRegex(
            text,
            r"function\s+Wait-PublicTunnelHealth\s*\(\[string\]\$PublicUrl,\s*\[int\]\$ProcessId",
        )
        self.assertIn("Waiting for quick-tunnel DNS/edge readiness", text)
        self.assertIn("Resolve-DnsName -Name $hostName -Type A -Server 1.1.1.1", text)
        self.assertIn("'--resolve' $resolveArg", text)
        self.assertIn("Wait-PublicTunnelHealth $PublicUrl $tunnel.Id 90", text)
        self.assertNotIn(
            'Invoke-RestMethod -Method Get -Uri "$PublicUrl/health" -TimeoutSec 15',
            text,
        )


if __name__ == "__main__":
    unittest.main()
