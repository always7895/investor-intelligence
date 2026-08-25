from __future__ import annotations

import json
import tomllib
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class FreeOnlyRuntimeTests(unittest.TestCase):
    def test_worker_has_no_ai_binding_or_scheduled_trigger(self) -> None:
        document = tomllib.loads(
            (ROOT / "cloud" / "wrangler.toml").read_text(encoding="utf-8")
        )
        self.assertNotIn("ai", document)
        self.assertNotIn("triggers", document)
        self.assertEqual(document["vars"]["CLOUDFLARE_PLAN"], "workers_free")
        self.assertEqual(document["vars"]["MEMORY_FEATURE_AVAILABLE"], "false")
        bindings = {
            item["binding"] for item in document.get("kv_namespaces", [])
        }
        self.assertEqual(
            bindings,
            {
                "PUBLIC_CACHE",
                "TENANT_PRIVATE_CACHE",
                "EPHEMERAL_SECURITY_CACHE",
            },
        )

    def test_runtime_has_no_cloud_generation_or_line_push_path(self) -> None:
        worker = (ROOT / "cloud" / "src" / "worker.ts").read_text(encoding="utf-8")
        qa = (ROOT / "cloud" / "src" / "qa.ts").read_text(encoding="utf-8")
        line = (ROOT / "cloud" / "src" / "line.ts").read_text(encoding="utf-8")
        self.assertNotIn("ScheduledController", worker)
        self.assertNotIn("pushText", worker)
        self.assertNotIn("env.AI", qa)
        self.assertNotIn("Workers AI", qa)
        self.assertNotIn("/message/push", line)
        self.assertNotIn("PUSH_URL", line)

    def test_owner_local_briefing_has_no_external_delivery_capability(self) -> None:
        self.assertFalse((ROOT / "scripts" / "deliver.py").exists())
        self.assertFalse((ROOT / "scripts" / "test_delivery.py").exists())
        self.assertFalse((ROOT / "config" / "delivery.example.json").exists())

        daily = (ROOT / "scripts" / "daily_briefing.py").read_text(encoding="utf-8")
        for forbidden in (
            "from deliver import",
            "send_report(",
            "LINE_USER_ID",
            "smtplib",
            "/message/push",
        ):
            self.assertNotIn(forbidden, daily)
        self.assertIn("external delivery is structurally unavailable", daily)

        env_example = (ROOT / ".env.example").read_text(encoding="utf-8")
        self.assertNotIn("LINE_USER_ID=", env_example)

    def test_runtime_policy_is_fail_closed(self) -> None:
        policy = json.loads(
            (ROOT / "config" / "runtime-policy.json").read_text(encoding="utf-8")
        )
        self.assertEqual(policy["schema_version"], 3)

        cost = policy["cost"]
        self.assertEqual(cost["mode"], "free_only_fail_closed")
        self.assertFalse(cost["paid_fallback"])
        self.assertFalse(cost["automatic_plan_upgrade"])

        cloud = policy["models"]["cloud"]
        self.assertFalse(cloud["enabled"])
        self.assertFalse(cloud["paid_plan_models_allowed"])

        local = policy["models"]["local"]
        self.assertEqual(local["provider"], "llama.cpp")
        self.assertEqual(local["visibility"], "private")
        self.assertEqual(local["per_request_fee"], 0)
        self.assertTrue(local["required_for_general_qa"])
        self.assertEqual(
            local["context_scope"],
            "public_snapshot_plus_current_tenant_opt_in_memory_when_available",
        )

        privacy = policy["privacy"]
        self.assertEqual(privacy["default_memory"], "unavailable")
        self.assertFalse(privacy["memory_feature_available_for_initial_external_release"])
        self.assertTrue(privacy["physical_namespace_separation"])
        self.assertEqual(privacy["public_cache_binding"], "PUBLIC_CACHE")
        self.assertEqual(
            privacy["tenant_private_cache_binding"], "TENANT_PRIVATE_CACHE"
        )
        self.assertEqual(
            privacy["ephemeral_security_cache_binding"],
            "EPHEMERAL_SECURITY_CACHE",
        )
        self.assertFalse(privacy["legacy_combined_cache_binding_allowed"])

        authorization = policy["authorization"]
        self.assertEqual(authorization["default_line_access_mode"], "disabled")
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
        self.assertFalse(authorization["owner_or_operator_role_exists_in_shared_bot"])

        line = policy["line"]
        self.assertFalse(line["push_messages_enabled"])
        self.assertFalse(line["ibkr_bridge"])
        self.assertFalse(line["brokerage_connection"])
        self.assertFalse(line["portfolio_tools"])
        self.assertFalse(line["private_sync_route"])

        data = policy["data"]
        self.assertEqual(data["line_public_sync_target_binding"], "PUBLIC_CACHE")

        release = policy["release"]
        self.assertTrue(release["require_physical_kv_namespace_acceptance"])
        self.assertTrue(release["require_fresh_namespace_migration"])
        self.assertFalse(release["copy_legacy_combined_kv"])


if __name__ == "__main__":
    unittest.main()
