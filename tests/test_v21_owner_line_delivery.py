from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load(relative: str, name: str):
    path = ROOT / relative
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load {relative}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class V21OwnerLineDeliveryTests(unittest.TestCase):
    def test_repository_passes_v21_delivery_gate(self) -> None:
        gate = load("scripts/v21_owner_line_delivery_gate.py", "v21_owner_line_gate")
        self.assertEqual(gate.audit_repository(), [])

    def test_snapshot_builder_self_test(self) -> None:
        builder = load("scripts/build_v21_public_snapshot.py", "v21_public_snapshot_builder")
        builder.self_test()

    def test_policy_has_exact_schedule_and_fail_closed_boundaries(self) -> None:
        policy = json.loads(
            (ROOT / "config/v21-owner-line-policy.json").read_text(encoding="utf-8")
        )
        self.assertEqual(policy["scheduled_delivery"]["times"], ["08:00", "21:00"])
        self.assertEqual(
            policy["scheduled_delivery"]["cloudflare_crons_utc"],
            ["0 0 * * *", "0 13 * * *"],
        )
        self.assertEqual(policy["research"]["top_count"], 20)
        self.assertEqual(policy["research"]["reviewed_source_catalog_count"], 99)
        self.assertFalse(policy["research"]["all_catalog_sources_claimed_active"])
        self.assertFalse(policy["research"]["automatic_source_activation"])
        self.assertFalse(policy["scheduled_delivery"]["paid_fallback"])
        self.assertTrue(policy["forbidden"]["ibkr_bridge"])
        self.assertTrue(policy["forbidden"]["automatic_trading"])

    def test_builder_accepts_public_catalog_positions_topic(self) -> None:
        builder = load("scripts/build_v21_public_snapshot.py", "v21_public_snapshot_builder_topic")
        plan = {
            "schema_version": 1,
            "catalog_count": 99,
            "automatic_activation": False,
            "owner_watchlist_inherited": False,
            "provider_scope": "public_only",
            "line_public_eligible": True,
            "inventory": {
                "source_count": 99,
                "runtime_enabled_count": 0,
                "topic_counts": {"positions": 1},
            },
        }
        self.assertEqual(builder.validate_plan(plan)["inventory"]["topic_counts"]["positions"], 1)

    def test_builder_rejects_private_top20_field(self) -> None:
        builder = load("scripts/build_v21_public_snapshot.py", "v21_public_snapshot_builder_private")
        records = [builder.synthetic_record(index, "2026-08-30T00:00:00Z") for index in range(20)]
        records[0]["holding"] = {"shares": 1}
        with self.assertRaises(builder.SnapshotError):
            builder.validate_top20(records)

    def test_v21_worker_keeps_manual_calculator_order_and_bounds_events(self) -> None:
        worker = (ROOT / "cloud/src/v21/worker.ts").read_text(encoding="utf-8")
        rate = worker.index("await rateLimit(env, tenantId, query.intent)")
        manual = worker.index("const manualOption = manualOptionQuoteAnswer(text);")
        deterministic = worker.index("const deterministic = await deterministicAnswer")
        self.assertLess(rate, manual)
        self.assertLess(manual, deterministic)
        self.assertIn('events.length > 20', worker)
        self.assertIn('manual_option_calculator: "ephemeral_user_supplied_only"', worker)

    def test_production_setup_rewrites_external_config_to_absolute_main(self) -> None:
        setup = (ROOT / "setup-v21-owner-line.ps1").read_text(encoding="utf-8-sig")
        self.assertIn("$entryPath = (Join-Path $cloudRoot 'src\\v21\\worker.ts').Replace('\\', '/')", setup)
        self.assertIn("$template.Replace('main = \"src/v21/worker.ts\"'", setup)

    def test_legacy_shared_worker_and_line_remain_reply_only(self) -> None:
        worker = (ROOT / "cloud/src/worker.ts").read_text(encoding="utf-8")
        line = (ROOT / "cloud/src/line.ts").read_text(encoding="utf-8")
        self.assertNotIn("ScheduledController", worker)
        self.assertNotIn("pushText", worker)
        self.assertNotIn("PUSH_URL", line)
        self.assertNotIn("/message/push", line)
        self.assertIn("const manualOption = manualOptionQuoteAnswer(text);", worker)
        self.assertIn("const operationEpoch = await tenantWriteEpoch", worker)


if __name__ == "__main__":
    unittest.main()
