"""Confirmed-byte heartbeat transactions against actual sealed KV sync/readback."""
import json
import unittest
from datetime import timedelta
from unittest import mock

import test_ranking_sealed_quota_integration as integration
from test_ranking_sealed_quota_integration import START, Clock
import ranking_confirmed_heartbeat as heartbeat
import publish_sealed_snapshot as publisher
import top20_carry_forward as carry
from sealed_kv_fakes import POINTER_KEY
import sealed_product_policy as products


class ConfirmedHeartbeatTests(unittest.TestCase):
    def setUp(self):
        self.h = integration.SealedQuotaIntegration()
        self.h.setUp()
        self.addCleanup(self.h.doCleanups)
        self.addCleanup(self.h.tearDown)
        self.product_paths = {name: self.h.tmp / "no-input" / name for name in ("identity", "prices", "market")}
        original = publisher.build_seal

        def seal(bodies, meta, lazy=None):
            bodies["v213:activation-claim"] = json.dumps({
                "schema_version": 1, "run_id": meta["run_id"],
                "transaction_id": meta["transaction_id"], "claimed_at": "2026-11-01T00:00:00Z",
                "payload_digests": {"immutable_capture": "a" * 64}}, separators=(",", ":"))
            return original(bodies, meta, lazy)

        patcher = mock.patch.object(publisher, "build_seal", seal)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_failed_six_local_seal_retries_at_seven_without_new_evidence(self):
        first, _ = self.h.publish(START)
        original_dir = self.h.snapshots / first["run_id"]
        original_objects = (original_dir / "objects.json").read_bytes()
        original_receipt = (self.h.snapshots / carry.CONFIRMED_NAME).read_bytes()
        # A locally completed 06 seal is not publication proof. No sync/ACK occurs.
        failed = self.h.evaluate(START + timedelta(hours=6))
        self.assertNotEqual(failed["run_id"], first["run_id"])
        self.assertEqual((self.h.snapshots / carry.CONFIRMED_NAME).read_bytes(), original_receipt)
        Clock.instant = START + timedelta(hours=7)
        staged = heartbeat.stage(self.h.snapshots, Clock.instant, product_paths=self.product_paths)
        self.assertEqual(staged["status"], "STAGED_CONFIRMED_HEARTBEAT")
        before = json.loads(original_objects)
        after = json.loads((self.h.snapshots / staged["run_id"] / "objects.json").read_bytes())
        old_prefix = f"snapshot:{first['run_id']}:"
        staged_pointer = json.loads((self.h.snapshots / staged["run_id"] / "pointer.raw.json").read_bytes())
        detail = products.parts(after, staged_pointer)
        self.assertEqual(detail["core_run_id"], first["run_id"])
        for logical, value in detail["core"].items():
            if logical != products.PIPELINE_KEY:
                self.assertEqual(before[old_prefix + logical], value)
        self.assertEqual(detail["core"][products.PIPELINE_KEY], integration.stamp(Clock.instant))
        self.assertEqual(detail["manifest"]["ranking_persisted_at"], integration.stamp(Clock.instant))
        old_claim = json.loads(before[old_prefix + "v213:activation-claim"])
        new_claim = json.loads(detail["core"]["v213:activation-claim"])
        self.assertEqual(old_claim, new_claim)
        self.assertEqual((self.h.snapshots / carry.CONFIRMED_NAME).read_bytes(), original_receipt)
        result = self.h.upload(staged)
        self.assertEqual(result.exit, 0, result.outcome)
        self.assertEqual(result.record["pointer_state"], "READBACK_CONFIRMED")
        self.assertEqual(result.record["objects_verified"], len(after))
        self.assertEqual(self.h.kv.puts[-1][0], POINTER_KEY)
        confirmed = carry.confirmed_snapshot(self.h.snapshots)
        self.assertEqual(confirmed["run_id"], staged["run_id"])
        self.assertEqual(confirmed["pointer"]["public_data_as_of"], first["public_data_as_of"])
        files = {p: p.read_bytes() for p in self.h.snapshots.rglob("*") if p.is_file()}
        Clock.instant = START + timedelta(hours=8)
        retained = heartbeat.stage(self.h.snapshots, Clock.instant, product_paths=self.product_paths)
        self.assertEqual(retained["retention_reason"], "NO_CHANGE")
        self.assertEqual(files, {p: p.read_bytes() for p in self.h.snapshots.rglob("*") if p.is_file()})
        self.assertEqual((original_dir / "objects.json").read_bytes(), original_objects)

    def test_ranking_budget_does_not_starve_market_and_midnight_resumes_rank_heartbeat(self):
        self.h.publish(START)
        import ranking_write_policy as policy
        budget = policy.DailyWriteBudget(self.h.budget_path)
        used = json.loads(self.h.budget_path.read_bytes())["reserved"]
        self.assertTrue(budget.reserve(400 - used, START))
        Clock.instant = START + timedelta(hours=7)
        staged = heartbeat.stage(self.h.snapshots, Clock.instant, product_paths=self.product_paths)
        self.assertEqual((staged["status"], staged["ranking_status"]), ("STAGED_INDEPENDENT_PRODUCTS", "REUSED"))
        result = self.h.upload(staged)
        self.assertEqual((result.exit, result.record["ranking_writes_reserved"], result.record["market_writes_reserved"]), (0, 0, 12))
        previous = carry.confirmed_snapshot(self.h.snapshots)
        detail = products.parts(previous["objects"], previous["pointer"])
        original_core = detail["core_run_id"]
        self.assertEqual(detail["manifest"]["ranking_persisted_at"], integration.stamp(START))
        self.assertEqual(detail["manifest"]["product_persisted_at"]["market"], integration.stamp(Clock.instant))
        Clock.instant = START + timedelta(days=1)
        staged = heartbeat.stage(self.h.snapshots, Clock.instant, product_paths=self.product_paths)
        self.assertEqual(staged["status"], "STAGED_CONFIRMED_HEARTBEAT")
        result = self.h.upload(staged)
        self.assertEqual((result.exit, result.record["pointer_state"]), (0, "READBACK_CONFIRMED"))
        confirmed = carry.confirmed_snapshot(self.h.snapshots)
        detail = products.parts(confirmed["objects"], confirmed["pointer"])
        self.assertEqual(detail["core_run_id"], original_core)
        self.assertEqual(json.loads(detail["lazy"][publisher.BOTTLENECK_V3_KEY])["generated_at"], integration.stamp(START))


if __name__ == "__main__":
    unittest.main()
