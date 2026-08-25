from __future__ import annotations

import importlib.util
import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load_gate():
    path = ROOT / "scripts" / "line_public_boundary_gate.py"
    spec = importlib.util.spec_from_file_location("line_public_boundary_gate", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("Unable to load LINE public boundary gate")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class LinePublicBoundaryGateTests(unittest.TestCase):
    def test_current_repository_satisfies_line_public_boundary(self) -> None:
        gate = load_gate()
        self.assertEqual(gate.audit_repository(ROOT), [])

    def test_private_sync_and_owner_push_assets_are_absent(self) -> None:
        for relative in (
            "cloud/src/internal.ts",
            "cloud/test/internal.test.ts",
            "scripts/sync_private_to_worker.py",
            "tests/test_sync_private_to_worker.py",
            "scripts/deliver.py",
            "scripts/test_delivery.py",
            "config/delivery.example.json",
        ):
            self.assertFalse((ROOT / relative).exists(), relative)

    def test_owner_local_briefing_cannot_deliver_to_line(self) -> None:
        daily = (ROOT / "scripts/daily_briefing.py").read_text(encoding="utf-8")
        self.assertNotIn("from deliver import", daily)
        self.assertNotIn("send_report(", daily)
        self.assertNotIn("LINE_USER_ID", daily)
        self.assertIn("external delivery is structurally unavailable", daily)

        env_example = (ROOT / ".env.example").read_text(encoding="utf-8")
        self.assertNotIn("LINE_USER_ID=", env_example)
        self.assertIn("stores no raw LINE user ID", env_example)

    def test_worker_has_no_private_sync_or_unauthorized_reply_route(self) -> None:
        worker = (ROOT / "cloud/src/worker.ts").read_text(encoding="utf-8")
        self.assertNotIn('url.pathname === "/internal/private-sync"', worker)
        self.assertNotIn("handlePrivateSync", worker)
        self.assertNotIn("BOT_ACCESS_NOT_AUTHORIZED", worker)
        self.assertIn('source.type !== "user"', worker)
        self.assertIn('lineAccessMode(env) === "disabled"', worker)
        self.assertIn("tenantSecretsConfigured", worker)
        self.assertIn("direct_chat_only: true", worker)
        self.assertIn("ibkr_bridge: false", worker)
        self.assertIn("portfolio_access: false", worker)

    def test_shared_bot_is_allowlist_only_with_no_group_switch(self) -> None:
        security = (ROOT / "cloud/src/security.ts").read_text(encoding="utf-8")
        self.assertNotIn("PRIVATE_TENANT_HASHES", security)
        self.assertNotIn("OPERATOR_TENANT_HASHES", security)
        self.assertNotIn("tenantRole", security)
        self.assertNotIn("LINE_DIRECT_CHAT_ONLY", security)
        self.assertNotIn('mode === "public"', security)
        self.assertIn('export type LineAccessMode = "disabled" | "allowlist"', security)
        self.assertIn('chatType !== "user"', security)

    def test_runtime_policy_rejects_open_admission(self) -> None:
        policy = json.loads(
            (ROOT / "config/runtime-policy.json").read_text(encoding="utf-8")
        )
        authorization = policy["authorization"]
        self.assertEqual(
            authorization["supported_line_access_modes"],
            ["disabled", "allowlist"],
        )
        self.assertTrue(authorization["direct_chat_only"])
        self.assertEqual(
            authorization["unauthorized_event_behavior"],
            "silent_fail_closed",
        )
        self.assertEqual(
            authorization["missing_tenant_secret_behavior"],
            "silent_fail_closed",
        )

    def test_deployment_examples_have_no_group_or_raw_push_target_switch(self) -> None:
        for relative in (
            ".env.example",
            "cloud/.dev.vars.example",
            "cloud/wrangler.toml",
            ".github/workflows/phase5-line-bot-audit.yml",
        ):
            text = (ROOT / relative).read_text(encoding="utf-8")
            self.assertNotIn("LINE_DIRECT_CHAT_ONLY", text, relative)
            self.assertNotIn("LINE_USER_ID=", text, relative)


if __name__ == "__main__":
    unittest.main()
