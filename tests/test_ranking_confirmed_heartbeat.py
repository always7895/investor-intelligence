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


class ConfirmedHeartbeatTests(unittest.TestCase):
    def setUp(self):
        self.h = integration.SealedQuotaIntegration()
        self.h.setUp()
        self.addCleanup(self.h.doCleanups)
        self.addCleanup(self.h.tearDown)
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
        staged = heartbeat.stage(self.h.snapshots, Clock.instant)
        self.assertEqual(staged["status"], "STAGED_CONFIRMED_HEARTBEAT")
        before = json.loads(original_objects)
        after = json.loads((self.h.snapshots / staged["run_id"] / "objects.json").read_bytes())
        old_prefix = f"snapshot:{first['run_id']}:"
        new_prefix = f"snapshot:{staged['run_id']}:"
        for key, value in before.items():
            if key in (old_prefix + carry.SEALED_MANIFEST_KEY, old_prefix + "v213:activation-claim"):
                continue
            self.assertEqual(after[new_prefix + key[len(old_prefix):] if key.startswith(old_prefix) else key], value)
        old_claim = json.loads(before[old_prefix + "v213:activation-claim"])
        new_claim = json.loads(after[new_prefix + "v213:activation-claim"])
        self.assertEqual(old_claim["claimed_at"], new_claim["claimed_at"])
        self.assertEqual(old_claim["payload_digests"], new_claim["payload_digests"])
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
        retained = heartbeat.stage(self.h.snapshots, Clock.instant)
        self.assertEqual(retained["retention_reason"], "NO_CHANGE")
        self.assertEqual(files, {p: p.read_bytes() for p in self.h.snapshots.rglob("*") if p.is_file()})
        self.assertEqual((original_dir / "objects.json").read_bytes(), original_objects)

    def test_budget_retains_without_local_stage_then_midnight_resumes(self):
        self.h.publish(START)
        self.h.budget_path.parent.mkdir(parents=True, exist_ok=True)
        import ranking_write_policy as policy
        budget = policy.DailyWriteBudget(self.h.budget_path)
        used = json.loads(self.h.budget_path.read_bytes())["reserved"]
        self.assertTrue(budget.reserve(400 - used, START))
        before = set(self.h.snapshots.iterdir())
        Clock.instant = START + timedelta(hours=7)
        retained = heartbeat.stage(self.h.snapshots, Clock.instant)
        self.assertEqual(retained["retention_reason"], "WRITE_BUDGET")
        self.assertEqual(set(self.h.snapshots.iterdir()), before)
        Clock.instant = START + timedelta(days=1)
        staged = heartbeat.stage(self.h.snapshots, Clock.instant)
        self.assertEqual(staged["status"], "STAGED_CONFIRMED_HEARTBEAT")
        result = self.h.upload(staged)
        self.assertEqual(result.exit, 0, result.outcome)
        self.assertEqual(result.record["pointer_state"], "READBACK_CONFIRMED")


if __name__ == "__main__":
    unittest.main()
