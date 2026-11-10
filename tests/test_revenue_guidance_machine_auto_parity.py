"""Historical AUTO replay -> genuine model/serializer; not native/live admission.

Only transport, time and random generation suffix are fixture inputs. The checker,
updater, effective-input resolver, financial model and machine serializer are real.

Historical Worker fixtures bind consumer-visible parity with only reviewed source
identity and its dependent digests projected; fresh-root bytes stay unnormalised.
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
from tests.revenue_guidance_machine_parity_support import consumer_view

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
    def test_real_auto_producer_preserves_frozen_parity_and_fresh_root_determinism(self):
        with tempfile.TemporaryDirectory() as a, tempfile.TemporaryDirectory() as b:
            result = produce(Path(a))
            again = produce(Path(b))
        self.assertEqual(result, again)
        self.assertEqual(consumer_view(result), consumer_view(json.loads(FIXTURE.read_bytes())))
        envelope = json.loads(result["report"])["top"][0]["outlook"]["order_forecast_v3"]
        self.assertEqual(envelope["payload"]["revenue_status"], "AVAILABLE")
        self.assertEqual(envelope["payload"]["m6"]["amount"], 156e9)
        self.assertEqual(envelope["payload"]["m12"]["amount"], 312e9)
        self.assertEqual(envelope["payload"]["evidence"]["auto_update"]["disposition"], "AUTO_VERIFIED")
        self.assertIsNotNone(envelope["machine"]["producer_canonical_json"])
        self.assertTrue(envelope["machine"]["receipt_history"])

    def test_parity_projection_is_limited_to_source_identity_dependencies(self):
        frozen = json.loads(FIXTURE.read_bytes())
        report, binding = json.loads(frozen["report"]), json.loads(frozen["binding"])
        material = report["top"][0]["outlook"]["order_forecast_v3"]["machine"]
        auto = report["top"][0]["outlook"]["order_forecast_v3"]["payload"]["evidence"]["auto_update"]
        for target in (material, auto, binding):
            target["input_digest"] = "b" * 64
            target["generation_sha256"] = "c" * 64
        for identity in (material["identity"], auto["identity"], binding["issuers"]["NVDA"]["identity"]):
            identity["implementation_sha256"] = "d" * 64
        changed = dict(frozen, report=json.dumps(report, ensure_ascii=False, separators=(",", ":")))
        binding["report_sha256"] = machine.sha256(changed["report"].encode("utf-8"))
        changed["binding"] = json.dumps(binding, ensure_ascii=False, separators=(",", ":"))
        self.assertEqual(consumer_view(changed), consumer_view(frozen))
        from tests.revenue_guidance_machine_parity_support import _implementation_identity
        canonical = '{"implementation_sha256":"' + "a" * 64 + '","sha256":"' + "a" * 64 + '","amount":7}'
        projected = _implementation_identity({"producer_canonical_json": canonical})
        other_identity = canonical.replace('"implementation_sha256":"' + "a" * 64,
                                           '"implementation_sha256":"' + "b" * 64)
        self.assertEqual(projected, _implementation_identity({"producer_canonical_json": other_identity}))
        self.assertIn('"sha256":"' + "a" * 64 + '"', projected["producer_canonical_json"])
        self.assertNotEqual(projected, _implementation_identity(
            {"producer_canonical_json": canonical.replace(',"amount":7', ', "amount":7')}))

    def test_parity_projection_preserves_financial_evidence_and_privacy_drift(self):
        frozen = json.loads(FIXTURE.read_bytes())
        expected = consumer_view(frozen)
        # Rebind each modified report so the parity check, not an incidental stale
        # report hash, must catch consumer-visible drift. Evidence hashes stay exact.
        changes = (
            (("payload", "m6", "amount"), 1),
            (("payload", "revenue_status"), "UNAVAILABLE"),
            (("payload", "evidence", "auto_update", "disposition"), "BLOCKED"),
            (("payload", "evidence", "documents", 0, "sha256"), "e" * 64),
            (("payload", "evidence", "auto_update", "producer", "captures", 0, "raw_sha256"), "e" * 64),
            (("machine", "receipt_history", 0, "digest"), "e" * 64),
            (("machine", "identity", "profiles_sha256"), "e" * 64),
            (("payload", "evidence", "private_path"), "synthetic-private-path"),
        )
        for path, value in changes:
            with self.subTest(path=path):
                report, binding = json.loads(frozen["report"]), json.loads(frozen["binding"])
                target = report["top"][0]["outlook"]["order_forecast_v3"]
                for key in path[:-1]:
                    target = target[key]
                target[path[-1]] = value
                # Preserve cross-copy identity integrity for the profile-drift case.
                if path == ("machine", "identity", "profiles_sha256"):
                    report["top"][0]["outlook"]["order_forecast_v3"]["payload"]["evidence"]["auto_update"]["identity"]["profiles_sha256"] = value
                    binding["issuers"]["NVDA"]["identity"]["profiles_sha256"] = value
                if path == ("payload", "evidence", "auto_update", "disposition"):
                    binding["issuers"]["NVDA"]["disposition"] = value
                changed = dict(frozen, report=json.dumps(report, ensure_ascii=False, separators=(",", ":")))
                binding["report_sha256"] = machine.sha256(changed["report"].encode("utf-8"))
                changed["binding"] = json.dumps(binding, ensure_ascii=False, separators=(",", ":"))
                self.assertNotEqual(consumer_view(changed), expected)
        binding = json.loads(frozen["binding"])
        binding["source_manifest_sha256"] = "e" * 64
        self.assertNotEqual(consumer_view(dict(frozen, binding=json.dumps(binding))), expected)
        binding["report_sha256"] = "f" * 64
        with self.assertRaises(machine.MachinePublicationBlocked):
            consumer_view(dict(frozen, binding=json.dumps(binding)))
        report, binding = json.loads(frozen["report"]), json.loads(frozen["binding"])
        report["top"][0]["outlook"]["order_forecast_v3"]["schema"] = "SYNTHETIC_UNKNOWN"
        raw = json.dumps(report, ensure_ascii=False, separators=(",", ":"))
        binding["report_sha256"] = machine.sha256(raw.encode("utf-8"))
        with self.assertRaises(machine.MachinePublicationBlocked):
            consumer_view(dict(frozen, report=raw, binding=json.dumps(binding)))
        for field in ("input_digest", "generation_sha256"):
            report, binding = json.loads(frozen["report"]), json.loads(frozen["binding"])
            report["top"][0]["outlook"]["order_forecast_v3"]["payload"]["evidence"]["auto_update"][field] = "e" * 64
            raw = json.dumps(report, ensure_ascii=False, separators=(",", ":"))
            binding["report_sha256"] = machine.sha256(raw.encode("utf-8"))
            with self.subTest(inconsistent_source_digest=field), self.assertRaisesRegex(AssertionError, "copies disagree"):
                consumer_view(dict(frozen, report=raw, binding=json.dumps(binding)))


if __name__ == "__main__":
    unittest.main()
