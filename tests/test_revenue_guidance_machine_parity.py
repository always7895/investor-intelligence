"""Synthetic BARRIER producer/serializer coverage, not AUTO/native/publication acceptance.

No model/serializer/resolver is mocked. Deliberately missing required state and
invalid synthetic baselines must remain unavailable through the actual publisher.
The historical clock and existing synthetic report shell are test inputs only.
Historical Worker fixtures bind the consumer-visible contract after projecting
only reviewed admission-source identity and its directly dependent digest fields.
"""
from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
import unittest
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT))
import order_claims
import publish_sealed_snapshot as publisher
import revenue_guidance_machine as machine
import revenue_guidance_overlay as overlay
from tests.revenue_guidance_machine_parity_support import consumer_view

CUTOFF = datetime(2026, 9, 28, 15, tzinfo=timezone.utc)
FIXTURE = ROOT / "tests/fixtures/revenue-guidance-machine-barrier-functional.json"


def produce(root: Path) -> dict:
    shell = json.loads((ROOT / "tests/fixtures/revenue-guidance-wire-v1-functional.json").read_text(encoding="utf-8"))
    report = json.loads(shell["expected_legacy_body"][machine.REPORT_KEY])
    symbols = tuple(row["symbol"] for row in report["top"])
    snapshot = overlay.load_effective_inputs(
        cutoff=CUTOFF, state_root=root / "missing-required-state", state_required=True,
        registry_bytes=b"{}", approval_bytes=b"{}", profiles_bytes=b"{}", receipts_bytes=b"{}",
        symbols=symbols)
    resolved = machine.resolve_machine_inputs(snapshot, CUTOFF, symbols)
    claims = order_claims.load(root / "missing-synthetic-order-claims.json")
    assert claims["status"] == "UNAVAILABLE" and claims["sha256"] is None
    for row in report["top"]:
        # Actual producer and actual serializer through their publisher caller.
        row["outlook"] = publisher._with_order_forecast(
            row["symbol"], None, None, None, CUTOFF, claims, consensus_cache={},
            effective_inputs=snapshot, guidance_machine_enabled=True, machine_inputs=resolved)
    report_raw = machine.compact(report, machine.REPORT_BYTES)
    binding_raw = machine.make_public_binding(
        resolved, report_raw, "gir1:" + "a" * 64, b'{"fixture":"synthetic-barrier"}')
    machine.validate_public_bundle(report_raw, binding_raw, machine.sha256(report_raw), machine.sha256(binding_raw))
    return {
        "scope": "SYNTHETIC_BARRIER_ONLY_NOT_AUTO_OR_NATIVE",
        "report": report_raw.decode("utf-8"), "binding": binding_raw.decode("utf-8"),
    }


class MachineBarrierProducerTests(unittest.TestCase):
    def test_real_producer_preserves_frozen_parity_and_fresh_root_determinism(self):
        with tempfile.TemporaryDirectory() as a, tempfile.TemporaryDirectory() as b:
            result = produce(Path(a))
            again = produce(Path(b))
        self.assertEqual(result, again)
        self.assertEqual(consumer_view(result), consumer_view(json.loads(FIXTURE.read_bytes())))
        report = json.loads(result["report"])
        nvda = next(row for row in report["top"] if row["symbol"] == "NVDA")["outlook"]["order_forecast_v3"]
        self.assertEqual(nvda["schema"], machine.MACHINE_SCHEMA)
        self.assertEqual(nvda["admission_mode"], "B1_MACHINE_V1")
        self.assertEqual(nvda["payload"]["evidence"]["auto_update"]["disposition"], "BLOCKED")
        self.assertEqual(nvda["payload"]["revenue_status"], "UNAVAILABLE")
        self.assertIsNone(nvda["machine"]["record_canonical_json"])
        self.assertIsNone(nvda["machine"]["producer_canonical_json"])
        self.assertEqual(nvda["machine"]["receipt_history"], [])


if __name__ == "__main__":
    unittest.main()
