from __future__ import annotations

import json
import tomllib
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class PrivacyAndCostPolicyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.policy = json.loads(
            (ROOT / "config" / "runtime-policy.json").read_text(encoding="utf-8")
        )

    def test_multi_tenant_privacy_defaults_fail_closed(self) -> None:
        privacy = self.policy["privacy"]
        self.assertTrue(privacy["multi_tenant"])
        self.assertEqual(privacy["tenant_id_derivation"], "hmac_sha256")
        self.assertFalse(privacy["raw_user_id_in_logs"])
        self.assertFalse(privacy["message_text_in_logs"])
        self.assertFalse(privacy["answer_text_in_logs"])
        self.assertEqual(privacy["default_memory"], "unavailable")
        self.assertFalse(privacy["memory_feature_available_for_initial_external_release"])
        self.assertFalse(privacy["cross_tenant_cache"])
        self.assertTrue(privacy["global_cache_public_inputs_only"])
        self.assertTrue(privacy["physical_namespace_separation"])
        self.assertFalse(privacy["legacy_combined_cache_binding_allowed"])
        self.assertFalse(privacy["group_chat_enabled"])
        self.assertFalse(privacy["owner_data_available_to_line"])
        self.assertFalse(privacy["owner_watchlist_inherited_by_line"])
        self.assertFalse(privacy["portfolio_available_to_line"])
        self.assertFalse(privacy["broker_account_available_to_line"])
        self.assertFalse(privacy["private_sync_available_to_line"])
        self.assertFalse(privacy["arbitrary_model_context_includes_option_chains"])
        self.assertEqual(
            privacy["first_person_financial_disclosure_behavior"],
            "reject_without_model_or_storage",
        )
        self.assertEqual(privacy["private_storage_encryption"], "aes_gcm")

    def test_line_has_no_owner_broker_or_privileged_role(self) -> None:
        authorization = self.policy["authorization"]
        self.assertEqual(authorization["default_line_access_mode"], "disabled")
        self.assertEqual(
            authorization["supported_line_access_modes"],
            ["disabled", "allowlist"],
        )
        self.assertTrue(authorization["allowlist_uses_hmac_tenant_ids"])
        self.assertTrue(authorization["direct_chat_only"])
        self.assertEqual(
            authorization["unauthorized_event_behavior"],
            "silent_fail_closed",
        )
        self.assertFalse(authorization["owner_or_operator_role_exists_in_shared_bot"])
        self.assertFalse(authorization["automatic_trading"])

        line = self.policy["line"]
        self.assertFalse(line["push_messages_enabled"])
        self.assertFalse(line["additional_paid_messages_allowed"])
        self.assertEqual(line["quota_exhaustion_behavior"], "fail_closed")
        self.assertFalse(line["ibkr_bridge"])
        self.assertFalse(line["brokerage_connection"])
        self.assertFalse(line["portfolio_tools"])
        self.assertFalse(line["private_sync_route"])

        local_broker = self.policy["local_broker_runtime"]
        self.assertFalse(local_broker["line_or_worker_may_call_ibkr"])
        self.assertFalse(local_broker["ibkr_output_may_enter_public_kv"])
        self.assertFalse(local_broker["ibkr_output_may_enter_line_model_context"])
        self.assertFalse(local_broker["broker_write_paths"])

    def test_three_physical_kv_namespaces_are_required(self) -> None:
        privacy = self.policy["privacy"]
        self.assertEqual(privacy["public_cache_binding"], "PUBLIC_CACHE")
        self.assertEqual(
            privacy["tenant_private_cache_binding"],
            "TENANT_PRIVATE_CACHE",
        )
        self.assertEqual(
            privacy["ephemeral_security_cache_binding"],
            "EPHEMERAL_SECURITY_CACHE",
        )
        namespace_policy = json.loads(
            (ROOT / "config" / "kv-namespace-policy.json").read_text(encoding="utf-8")
        )
        self.assertTrue(namespace_policy["same_namespace_id_forbidden"])
        self.assertTrue(namespace_policy["legacy_cache_binding_forbidden"])
        self.assertFalse(namespace_policy["memory_feature_default"])
        self.assertFalse(namespace_policy["generic_private_json_api_allowed"])
        self.assertEqual(namespace_policy["public_publisher_target"], "PUBLIC_CACHE")

        wrangler = tomllib.loads(
            (ROOT / "cloud" / "wrangler.toml").read_text(encoding="utf-8")
        )
        namespaces = wrangler.get("kv_namespaces", [])
        self.assertEqual(len(namespaces), 3)
        self.assertEqual(
            {item["binding"] for item in namespaces},
            {
                "PUBLIC_CACHE",
                "TENANT_PRIVATE_CACHE",
                "EPHEMERAL_SECURITY_CACHE",
            },
        )
        self.assertEqual(wrangler["vars"]["MEMORY_FEATURE_AVAILABLE"], "false")

    def test_free_only_policy_has_no_upgrade_or_paid_fallback(self) -> None:
        cost = self.policy["cost"]
        self.assertEqual(cost["mode"], "free_only_fail_closed")
        self.assertFalse(cost["paid_fallback"])
        self.assertFalse(cost["automatic_plan_upgrade"])
        self.assertFalse(cost["payment_method_required"])
        self.assertFalse(cost["paid_model_api_allowed"])
        self.assertFalse(cost["paid_market_data_required"])
        self.assertFalse(cost["paid_news_required"])
        self.assertFalse(cost["github_hosted_runners_allowed"])
        self.assertFalse(cost["github_actions_artifacts_required"])
        self.assertEqual(cost["cloudflare_plan"], "workers_free")

        cloud = self.policy["models"]["cloud"]
        self.assertFalse(cloud["enabled"])
        self.assertFalse(cloud["paid_plan_models_allowed"])

        data = self.policy["data"]
        self.assertTrue(data["required_sources_must_be_free"])
        self.assertFalse(data["paywall_bypass"])
        self.assertFalse(data["premium_api_dependency"])
        self.assertFalse(data["line_public_symbols_inherit_owner_watchlist"])
        self.assertFalse(data["line_public_legacy_artifact_fallback"])
        self.assertEqual(data["line_public_sync_target_binding"], "PUBLIC_CACHE")

    def test_local_model_is_private_authenticated_and_zero_fee(self) -> None:
        local = self.policy["models"]["local"]
        self.assertEqual(local["provider"], "llama.cpp")
        self.assertEqual(local["visibility"], "private")
        self.assertEqual(local["per_request_fee"], 0)
        self.assertTrue(local["allowed_hosts_required"])
        self.assertTrue(local["authenticated_route_required"])
        self.assertFalse(local["ip_literal_hosts_allowed"])
        self.assertFalse(local["non_443_ports_allowed"])
        self.assertFalse(local["redirects_allowed"])
        self.assertFalse(local["option_chains_in_arbitrary_context"])

    def test_release_remains_fail_closed_and_private_data_free(self) -> None:
        release = self.policy["release"]
        self.assertFalse(release["install_local_project_before_final_acceptance"])
        self.assertFalse(release["include_secrets"])
        self.assertFalse(release["include_user_data"])
        self.assertFalse(release["include_runner_state"])
        self.assertTrue(release["require_cross_tenant_privacy_acceptance"])
        self.assertTrue(release["require_line_broker_separation_acceptance"])
        self.assertTrue(release["require_physical_kv_namespace_acceptance"])
        self.assertTrue(release["require_fresh_namespace_migration"])
        self.assertFalse(release["copy_legacy_combined_kv"])

    def test_public_line_symbols_never_inherit_owner_watchlist(self) -> None:
        symbols = json.loads(
            (ROOT / "config" / "line-public-symbols.json").read_text(encoding="utf-8")
        )
        self.assertFalse(symbols["owner_watchlist_inheritance"])
        self.assertIsInstance(symbols["symbols"], list)

    def test_worker_source_has_no_private_sync_or_broker_runtime(self) -> None:
        worker_tree = "\n".join(
            path.read_text(encoding="utf-8")
            for path in sorted((ROOT / "cloud" / "src").glob("*.ts"))
        )
        self.assertNotIn("/internal/private-sync", worker_tree)
        self.assertNotIn("SERVICE_SYNC_TOKEN", worker_tree)
        self.assertNotIn("PRIVATE_TENANT_HASHES", worker_tree)
        self.assertNotIn("OPERATOR_TENANT_HASHES", worker_tree)
        self.assertNotIn("env.CACHE", worker_tree)
        self.assertNotIn("putPrivateJson", worker_tree)
        self.assertNotIn("privateJson", worker_tree)


if __name__ == "__main__":
    unittest.main()
