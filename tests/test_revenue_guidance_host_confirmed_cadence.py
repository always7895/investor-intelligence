"""Offline host cadence against real sync receipts; IMPLEMENTED_UNVERIFIED.

The actual host rank decision and sealed publisher/sync/readback paths run over
FakeKV. Native admission/capture/model/output collaborators are in-memory test
boundaries, not claims of custody, real remote ACK or production delivery.
"""
from __future__ import annotations

import copy
import json
import os
from datetime import timedelta
from types import SimpleNamespace
import unittest
from unittest import mock

import test_ranking_sealed_quota_integration as integration
from test_ranking_sealed_quota_integration import START, stamp
from sealed_kv_fakes import NETWORK, POINTER_KEY
import bottleneck_top20_v3 as ranking
import publish_sealed_snapshot as publisher
import revenue_guidance_host as host
import top20_carry_forward as carry
import top20_rotation_provenance as rotation


REVISION = "gir1:" + "a" * 64


class HostConfirmedCadenceTests(unittest.TestCase):
    def setUp(self):
        self.h = integration.SealedQuotaIntegration()
        self.h.setUp()
        self.addCleanup(self.h.doCleanups)
        self.addCleanup(self.h.tearDown)
        patcher = mock.patch.dict(os.environ, {"II_SNAPSHOT_ROOT": str(self.h.snapshots),
                                               "II_R2B_SHADOW_LOG": ""})
        patcher.start()
        self.addCleanup(patcher.stop)
        self.local = None

    def evaluate_host(self, moment, symbols):
        evaluated = {"generated_at": stamp(moment),
                     "top": [{"symbol": symbol} for symbol in symbols]}
        state = {"Intent": None, "StateRequired": True,
                 "InputRevision": REVISION, "PendingRevision": REVISION}
        snapshot = SimpleNamespace(symbols=lambda: symbols, cutoff=stamp(moment),
                                   input_digest="b" * 64, generation_id="test-generation",
                                   generation_sha256="c" * 64)
        session = SimpleNamespace(phase="idle", guard=object(), witness=object(), machine_enabled=False,
            lease=SimpleNamespace(read_journal=mock.Mock(return_value=SimpleNamespace(state=state))),
            input_revision=mock.Mock(return_value=REVISION), snapshot=mock.Mock(return_value=snapshot),
            remaining=mock.Mock())

        def publish(rank, body, record):
            # A real local completion can exist while the remote pointer is A.
            self.local = json.loads(rank)
            return {"rank": host.digest(rank), "body": host.digest(body), "record": host.digest(record)}

        outputs = SimpleNamespace(latest_ranking=mock.Mock(return_value=copy.deepcopy(self.local)),
                                  publish=mock.Mock(side_effect=publish))
        captured = mock.Mock()
        captured.collect.return_value = moment.date()
        captured.manifest.return_value = {"test": "immutable-capture-boundary"}
        consumption = SimpleNamespace(snapshot=snapshot, rows=[(symbol, 0) for symbol in symbols])
        with mock.patch.object(host, "_Capture", return_value=captured), \
                mock.patch.object(host, "now", return_value=moment), \
                mock.patch.object(host.overlay, "B1Store"), \
                mock.patch.object(host.overlay, "B1Outputs", return_value=outputs), \
                mock.patch.object(host.revision, "compute_input_revision", return_value=REVISION), \
                mock.patch.object(ranking, "build", return_value=evaluated), \
                mock.patch.object(publisher, "ForecastConsumption", return_value=consumption) as consume, \
                mock.patch.object(publisher, "captured_bottleneck_v3_body", return_value={
                    publisher.BOTTLENECK_V3_KEY: json.dumps(evaluated)}) as build_body, \
                mock.patch.object(rotation, "append_if_configured") as append:
            result = host._Session.rank(session, {"Mode": "Dirty", "Revision": REVISION})
        outputs.latest_ranking.assert_not_called()
        append.assert_not_called()
        self.assertEqual(state["PendingRevision"], REVISION)
        self.assertEqual(session.phase, "idle")
        if result.get("PublicationSuppressed"):
            self.assertFalse(result["Completed"])
            self.assertTrue(result["ServingLastGood"])
            self.assertEqual(result["Reason"], "NO_CHANGE")
            self.assertIsNone(session.witness)
            consume.assert_not_called()
            build_body.assert_not_called()
            outputs.publish.assert_not_called()
        else:
            self.assertEqual(result, {"Completed": True, "Revision": REVISION, "ReusedLiveConsumption": False})
            self.assertNotIn("ServingLastGood", result)
            self.assertIsInstance(session.witness, host._LiveWitness)
            self.assertFalse(session.witness.acked)
            consume.assert_called_once_with(snapshot)
            outputs.publish.assert_called_once()
        return result

    def test_failed_change_retries_hourly_before_six_hours_and_across_utc_reset(self):
        first_time = START + timedelta(hours=21)
        first, uploaded = self.h.publish(first_time)
        self.assertEqual(uploaded.record["pointer_state"], "READBACK_CONFIRMED")
        receipt = (self.h.snapshots / carry.CONFIRMED_NAME).read_bytes()
        pointer = self.h.kv.store[POINTER_KEY]
        changed = list(reversed(self.h.symbols))
        failed_time = first_time + timedelta(hours=1)
        self.assertTrue(self.evaluate_host(failed_time, changed)["Completed"])
        self.assertEqual([row["symbol"] for row in self.local["top"]], changed)
        staged = self.h.evaluate(failed_time, changed)
        objects = json.loads((self.h.snapshots / staged["run_id"] / "objects.json").read_bytes())
        # Fail an immutable object before pointer launch; local B is completed,
        # but actual all-object/pointer confirmation still describes remote A.
        failed_key = next(key for key in sorted(objects) if not key.startswith("blob:v1:"))
        self.h.kv.fail_put(failed_key, None, NETWORK)
        failed = self.h.upload(staged)
        self.assertNotEqual(failed.exit, 0)
        self.assertEqual(failed.record["pointer_state"], "NOT_ATTEMPTED")
        self.assertEqual(self.h.kv.store[POINTER_KEY], pointer)
        self.assertEqual((self.h.snapshots / carry.CONFIRMED_NAME).read_bytes(), receipt)
        self.assertEqual(carry.confirmed_snapshot(self.h.snapshots)["run_id"], first["run_id"])
        self.h.kv.clear_hooks()
        # Neither the failed local completion nor a UTC-day reset is publication.
        for hour in (23, 24):
            moment = START + timedelta(hours=hour)
            with self.subTest(hour=hour):
                self.assertTrue(self.evaluate_host(moment, changed)["Completed"])
                self.assertLess((moment - first_time).total_seconds(), 21600)
                self.assertEqual((self.h.snapshots / carry.CONFIRMED_NAME).read_bytes(), receipt)
        next_day = START + timedelta(days=1)
        confirmed, readback = self.h.publish(next_day, changed)
        self.assertEqual(readback.record["pointer_state"], "READBACK_CONFIRMED")
        self.assertEqual(carry.confirmed_snapshot(self.h.snapshots)["run_id"], confirmed["run_id"])
        # Only genuine B readback may suppress a same-order later evaluation.
        result = self.evaluate_host(next_day + timedelta(hours=1), changed)
        self.assertTrue(result["PublicationSuppressed"])

    def test_confirmed_order_not_local_completion_controls_suppression(self):
        self.h.publish(START)
        self.local = {"generated_at": stamp(START + timedelta(minutes=30)),
                      "top": [{"symbol": symbol} for symbol in reversed(self.h.symbols)]}
        before = copy.deepcopy(self.local)
        result = self.evaluate_host(START + timedelta(hours=1), self.h.symbols)
        self.assertTrue(result["PublicationSuppressed"])
        self.assertEqual(self.local, before)

    def test_missing_ambiguous_corrupt_and_unconfirmed_proofs_cannot_suppress_local_b(self):
        first, _ = self.h.publish(START)
        receipt_path = self.h.snapshots / carry.CONFIRMED_NAME
        receipt = receipt_path.read_bytes()
        pending = self.h.snapshots / carry.AMBIGUOUS_NAME
        changed = list(reversed(self.h.symbols))
        # Real staged B bytes without upload/readback are never publication proof.
        staged = self.h.evaluate(START + timedelta(hours=1), changed)
        self.assertNotEqual(staged["run_id"], first["run_id"])
        for kind in ("no-root", "relative-root", "missing-receipt", "pending-pointer", "corrupt-receipt", "unconfirmed-stage"):
            with self.subTest(proof=kind):
                receipt_path.write_bytes(receipt)
                pending.unlink(missing_ok=True)
                root = str(self.h.snapshots)
                if kind == "no-root":
                    root = ""
                elif kind == "relative-root":
                    root = "relative-snapshots"
                elif kind == "missing-receipt":
                    receipt_path.unlink()
                elif kind == "pending-pointer":
                    pending.write_text("corrupt pending bytes still invalidate old receipt", encoding="utf-8")
                elif kind == "corrupt-receipt":
                    receipt_path.write_text("[]", encoding="utf-8")
                self.local = {"generated_at": stamp(START + timedelta(hours=1)),
                              "top": [{"symbol": symbol} for symbol in changed]}
                files = {path: path.read_bytes() for path in self.h.snapshots.rglob("*") if path.is_file()}
                operations = len(self.h.kv.log)
                with mock.patch.dict(os.environ, {"II_SNAPSHOT_ROOT": root}):
                    self.assertTrue(self.evaluate_host(START + timedelta(hours=2), changed)["Completed"])
                self.assertEqual(len(self.h.kv.log), operations)
                self.assertEqual(files, {path: path.read_bytes() for path in self.h.snapshots.rglob("*") if path.is_file()})


if __name__ == "__main__":
    unittest.main()
