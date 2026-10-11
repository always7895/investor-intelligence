"""Historical AUTO replay -> genuine model/serializer; not native/live admission.

Only transport, time and random generation suffix are fixture inputs. The checker,
updater, effective-input resolver, financial model and machine serializer are real.
"""
from __future__ import annotations

import itertools
import json
from pathlib import Path
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT))
import order_claims
import publish_sealed_snapshot as publisher
import revenue_guidance_machine as machine
import revenue_guidance_overlay as overlay
from tests import test_revenue_guidance_autoupdate as replay

CUTOFF = datetime(2026, 2, 27, 13, tzinfo=timezone.utc)
FIXTURE = ROOT / "tests/fixtures/revenue-guidance-machine-auto-functional.json"


def produce(root: Path, taint=None) -> dict:
    chain = replay.Chain(root)
    sequence = itertools.count(1)
    with mock.patch.object(replay.updater.secrets, "token_hex", side_effect=lambda n: f"{next(sequence):0{2 * n}x}"):
        for instant in ("2025-12-17T23:00:00Z", "2025-12-19T12:00:00Z", "2026-02-26T12:00:00Z"):
            chain.check(instant)
            # A synthetic ordinary transport, NOT relabelled stored replay evidence.
            # The real producer creates fresh captures with its normal role contract.
            class FixtureTransport:
                def get(self, url, profile, symbol):
                    return replay.ReplayAsOf(instant[:10]).get(url, profile, symbol)
            replay.updater.run(chain.state, FixtureTransport(), replay.at(instant),
                               replay.PROFILES, chain.registry, chain.approval, chain.receipts)
        chain.check("2026-02-27T12:00:00Z")
        if taint is not None:
            taint(chain)
    shell = json.loads((ROOT / "tests/fixtures/revenue-guidance-wire-v1-functional.json").read_text(encoding="utf-8"))
    report = json.loads(shell["expected_legacy_body"][machine.REPORT_KEY])
    report["generated_at"] = "2026-02-27T13:00:00Z"
    symbols = tuple(row["symbol"] for row in report["top"])
    snapshot = overlay.load_effective_inputs(cutoff=report["generated_at"], state_root=chain.state,
        registry_path=chain.registry, approval_path=chain.approval, profiles_path=replay.PROFILES,
        receipts_path=chain.receipts, symbols=symbols, allow_replay=False)
    assert taint is not None or snapshot.issuer("NVDA").disposition == "AUTO_VERIFIED"
    resolved = machine.resolve_machine_inputs(snapshot, CUTOFF, symbols)
    claims = order_claims.load(root / "missing-synthetic-order-claims.json")
    for row in report["top"]:
        row["market"]["asof"] = "2026-02-27"
        row["outlook"] = publisher._with_order_forecast(
            row["symbol"], None, None, None, CUTOFF, claims, consensus_cache={},
            effective_inputs=snapshot, guidance_machine_enabled=True, machine_inputs=resolved)
    raw = machine.compact(report, machine.REPORT_BYTES)
    binding = machine.make_public_binding(resolved, raw, "gir1:" + "a" * 64, b'{"fixture":"historical-auto-replay"}')
    machine.validate_public_bundle(raw, binding, machine.sha256(raw), machine.sha256(binding))
    return {"scope": "SYNTHETIC_HISTORICAL_AUTO_NOT_NATIVE_OR_LIVE", "report": raw.decode("utf-8"), "binding": binding.decode("utf-8")}


class MachineAutoProducerTests(unittest.TestCase):
    def test_real_auto_producer_serializer_bytes_match_worker_fixture(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = produce(Path(tmp))
        envelope = json.loads(result["report"])["top"][0]["outlook"]["order_forecast_v3"]
        self.assertEqual(envelope["payload"]["revenue_status"], "AVAILABLE")
        self.assertEqual(envelope["payload"]["m6"]["amount"], 156e9)
        self.assertEqual(envelope["payload"]["m12"]["amount"], 312e9)
        self.assertEqual(envelope["payload"]["evidence"]["auto_update"]["disposition"], "AUTO_VERIFIED")
        self.assertIsNotNone(envelope["machine"]["producer_canonical_json"])
        self.assertTrue(envelope["machine"]["receipt_history"])
        self.assertEqual(result, json.loads(FIXTURE.read_text(encoding="utf-8")))


if __name__ == "__main__":
    unittest.main()
