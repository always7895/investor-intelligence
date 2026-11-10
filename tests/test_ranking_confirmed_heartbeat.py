"""Confirmed-byte heartbeat transactions against actual sealed KV sync/readback."""
import json
import os
import unittest
from pathlib import Path
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

    def test_machine_only_failure_hour_publishes_healthy_market_and_retains_ranking_digest(self):
        # 07:00 has no new machine result, but market collection is healthy.
        # Even though the ranking's 6h heartbeat is due, --products-only MUST
        # leave its confirmed cadence, core claim and exact ranked blob alone.
        first, _ = self.h.publish(START)
        prior = carry.confirmed_snapshot(self.h.snapshots)
        before = products.parts(prior["objects"], prior["pointer"])
        ranked = before["lazy"][publisher.BOTTLENECK_V3_KEY]
        now = START + timedelta(hours=7)
        Clock.instant = now
        quote = json.dumps({"schema": "v213-quotes-v1", "generated_at": integration.stamp(now), "quotes": {}})
        option = json.dumps({"schema": "v213-options-v2", "generated_at": integration.stamp(now), "options": {}})
        coverage = json.dumps({"schema": "v213-options-coverage-v1", "generated_at": integration.stamp(now), "coverage": {}})
        price = json.dumps({"schema": "v213-prices-v1", "generated_at": integration.stamp(now), "prices": {}})
        with mock.patch.object(publisher, "lazy_identity_bodies", return_value={}), \
                mock.patch.object(publisher, "lazy_price_bodies", return_value={"v213:prices:v1:US": price}), \
                mock.patch.object(publisher, "lazy_market_bodies", return_value={
                    "v213:quotes:v1": quote, "v213:options:v2": option}), \
                mock.patch.object(publisher, "lazy_options_coverage_body",
                                  return_value={"v213:options-coverage:v1": coverage}):
            staged = heartbeat.stage(self.h.snapshots, now, product_paths=self.product_paths, products_only=True)
        self.assertEqual(staged["status"], "STAGED_INDEPENDENT_PRODUCTS")
        staged_pointer = json.loads((self.h.snapshots / staged["run_id"] / "pointer.raw.json").read_bytes())
        staged_objects = json.loads((self.h.snapshots / staged["run_id"] / "objects.json").read_bytes())
        after = products.parts(staged_objects, staged_pointer)
        self.assertEqual(staged["ranking_status"], "REUSED")
        self.assertEqual(after["manifest"]["ranking_persisted_at"], integration.stamp(START))
        self.assertEqual(after["manifest"]["public_data_as_of"], before["manifest"]["public_data_as_of"])
        self.assertEqual(after["core_run_id"], first["run_id"])
        self.assertEqual(after["lazy"][publisher.BOTTLENECK_V3_KEY], ranked)
        self.assertEqual(after["lazy"]["v213:quotes:v1"], quote)
        self.assertEqual(after["lazy"]["v213:options:v2"], option)
        self.assertEqual(after["lazy"]["v213:options-coverage:v1"], coverage)
        self.assertEqual(after["lazy"]["v213:prices:v1:US"], price)
        for logical, value in before["core"].items():
            if logical != products.PIPELINE_KEY:
                self.assertEqual(after["core"][logical], value)
        result = self.h.upload(staged)
        self.assertEqual(result.exit, 0, result.outcome)
        self.assertEqual((result.record["ranking_writes_reserved"],
                          result.record["pointer_state"]), (0, "READBACK_CONFIRMED"))
        self.assertGreater(result.record["market_writes_reserved"], 0)
        served, pointer = self.h.serving()
        self.assertEqual(served.decode("utf-8"), ranked)
        self.assertEqual(pointer["run_id"], staged["run_id"])
        proof_target = os.getenv("R2B_ROUND3_MACHINE_HOUR_PROOF_OUT")
        if proof_target:
            allowed = Path(__file__).resolve().parents[2] / "evidence" / "round3"
            allowed.mkdir(parents=True, exist_ok=True)
            target = Path(proof_target).resolve()
            if not target.is_relative_to(allowed.resolve()) or target.exists():
                raise AssertionError("UNSAFE_OR_EXISTING_PROOF_TARGET")
            receipt = {
                "kind": "ONE_HOUR_MACHINE_ONLY_FAILURE_WITH_HEALTHY_MARKET_SOURCES",
                "hour_utc": integration.stamp(now),
                "scope": "SYNTHETIC_IO_REAL_SEAL_AND_SYNC_NOT_LIVE_PROVIDER",
                "ranked_rows_served": len(json.loads(served)["top"]),
                "machine_failure_runner_test": "MachineIndependentProductFailureTests",
                "no_secondary_ranking_producer": True,
                "ranking_reused": staged["ranking_status"] == "REUSED",
                "ranking_persisted_at": after["manifest"]["ranking_persisted_at"],
                "ranking_digest_before": products.digest(ranked),
                "ranking_digest_after": products.digest(after["lazy"][publisher.BOTTLENECK_V3_KEY]),
                "original_public_data_as_of": staged_pointer["public_data_as_of"],
                "market_source_generated_at": integration.stamp(now),
                "quotes_fresh": json.loads(after["lazy"]["v213:quotes:v1"])["generated_at"] == integration.stamp(now),
                "options_fresh": json.loads(after["lazy"]["v213:options:v2"])["generated_at"] == integration.stamp(now),
                "coverage_fresh": json.loads(after["lazy"]["v213:options-coverage:v1"])["generated_at"] == integration.stamp(now),
                "price_shard_fresh": json.loads(after["lazy"]["v213:prices:v1:US"])["generated_at"] == integration.stamp(now),
                "ranking_reservation": result.record["ranking_writes_reserved"],
                "product_reservation": result.record["market_writes_reserved"],
                "pointer_readback_confirmed": result.record["pointer_state"] == "READBACK_CONFIRMED",
                "no_new_machine_ack_or_forecast": True,
                "DUAL_ACCEPTED": False,
            }
            target.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

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
