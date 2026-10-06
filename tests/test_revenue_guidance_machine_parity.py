"""Synthetic BARRIER producer/serializer fixture, not AUTO/native/publication acceptance.

No model/serializer/resolver is mocked. Deliberately missing required state and
invalid synthetic baselines must remain unavailable through the actual publisher.
The historical clock and existing synthetic report shell are test inputs only.
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
import order_claims
import publish_sealed_snapshot as publisher
import revenue_guidance_machine as machine
import revenue_guidance_overlay as overlay

FIXTURE = ROOT / "tests/fixtures/revenue-guidance-machine-barrier-functional.json"
CUTOFF = datetime(2026, 9, 28, 15, tzinfo=timezone.utc)


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
    def test_real_producer_serializer_bytes_match_worker_fixture(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = produce(Path(tmp))
            again = produce(Path(tmp))
        self.assertEqual(result, again)
        report = json.loads(result["report"])
        nvda = next(row for row in report["top"] if row["symbol"] == "NVDA")["outlook"]["order_forecast_v3"]
        self.assertEqual(nvda["schema"], machine.MACHINE_SCHEMA)
        self.assertEqual(nvda["admission_mode"], "B1_MACHINE_V1")
        self.assertEqual(nvda["payload"]["evidence"]["auto_update"]["disposition"], "BLOCKED")
        self.assertEqual(nvda["payload"]["revenue_status"], "UNAVAILABLE")
        self.assertIsNone(nvda["machine"]["record_canonical_json"])
        self.assertIsNone(nvda["machine"]["producer_canonical_json"])
        self.assertEqual(nvda["machine"]["receipt_history"], [])
        self.assertEqual(result, json.loads(FIXTURE.read_text(encoding="utf-8")))


if __name__ == "__main__":
    unittest.main()
