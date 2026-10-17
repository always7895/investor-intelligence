"""Producer-side machine envelope bounds, double-wrap and forged-payload refusals.

The real historical AUTO producer of test_revenue_guidance_machine_auto_parity
supplies the genuine snapshot and resolved bindings; the real _with_order_forecast
caller and make_machine_envelope serializer are exercised. M10/M10c already pin
the reader-side 256000/256001 envelope limit; this module pins the producer side
and the public-bundle byte caps. Synthetic historical replay only, not native/live.
"""
from __future__ import annotations

from contextlib import nullcontext
import copy
import dataclasses
import hashlib
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT))
import order_claims
import publish_sealed_snapshot as publisher
import revenue_guidance_machine as machine
import revenue_guidance_wire as wire
from tests import test_revenue_guidance_machine_auto_parity as auto

PAD = "synthetic_pad"


def size(value):
    return len(machine.compact(value, 10 ** 9))


class MachineEnvelopeBoundTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix="synthetic-g1-envelope-")
        cls.addClassCleanup(cls.temp.cleanup)
        root = Path(cls.temp.name)
        real = machine.resolve_machine_inputs
        resolved = []
        def capture(*args):
            value = real(*args)
            resolved.append(value)
            return value
        with mock.patch.object(machine, "resolve_machine_inputs", side_effect=capture):
            cls.produced = auto.produce(root)
        cls.resolved = resolved[0]  # produce() resolves once, before its own binding check
        cls.claims = order_claims.load(root / "missing-synthetic-order-claims.json")

    def forecast(self, symbol="NVDA", *, wire_enabled=False, pad=None):
        real = publisher.order_forecast.build_v3
        def padded(*args, **kwargs):
            value = real(*args, **kwargs)
            return {**value, PAD: " " * pad} if args[0] == symbol else value
        patch = mock.patch.object(publisher.order_forecast, "build_v3", side_effect=padded) if pad is not None else nullcontext()
        with patch:
            return publisher._with_order_forecast(
                symbol, None, None, None, auto.CUTOFF, self.claims, consensus_cache={},
                effective_inputs=self.resolved.snapshot, guidance_wire_enabled=wire_enabled,
                guidance_machine_enabled=True, machine_inputs=self.resolved)["order_forecast_v3"]

    def blocked(self, call, expected="MACHINE_INPUTS_UNAVAILABLE"):
        with self.assertRaises(machine.MachinePublicationBlocked) as raised:
            call()
        self.assertEqual(raised.exception.reason, expected)

    def test_caller_reproduces_the_genuine_producer_envelope(self):
        produced = json.loads(self.produced["report"])["top"][0]
        self.assertEqual(produced["symbol"], "NVDA")
        self.assertEqual(produced["outlook"]["order_forecast_v3"], json.loads(machine.compact(self.forecast(), 10 ** 9)))
        self.assertEqual(self.resolved.bindings.issuer("NVDA").disposition, "AUTO_VERIFIED")
        self.assertEqual(machine.ENVELOPE_BYTES, 256000)

    def test_producer_envelope_limit_is_inclusive_and_never_clipped_or_rerouted(self):
        plain = self.forecast()
        base = size(self.forecast(pad=0))
        self.assertLess(base, machine.ENVELOPE_BYTES)
        exact = self.forecast(pad=machine.ENVELOPE_BYTES - base)
        self.assertEqual(size(exact), machine.ENVELOPE_BYTES)
        self.assertEqual(exact["payload"][PAD], " " * (machine.ENVELOPE_BYTES - base))
        self.assertEqual({k: v for k, v in exact["payload"].items() if k != PAD}, plain["payload"])
        self.assertEqual(exact["machine"], plain["machine"])
        for wire_enabled in (False, True):
            with self.subTest(wire_enabled=wire_enabled):
                self.blocked(lambda: self.forecast(wire_enabled=wire_enabled, pad=machine.ENVELOPE_BYTES - base + 1),
                             "MACHINE_EVIDENCE_LIMIT")

    def test_machine_and_wire_flags_wrap_exactly_once(self):
        auto_plain, auto_wired = self.forecast(), self.forecast(wire_enabled=True)
        self.assertEqual(auto_wired, auto_plain)
        self.assertEqual(set(auto_wired), {"schema", "admission_mode", "payload", "machine"})
        self.assertEqual((auto_wired["schema"], auto_wired["admission_mode"]), (machine.MACHINE_SCHEMA, "B1_MACHINE_V1"))
        self.assertEqual(auto_wired["payload"]["version"], 3)
        self.assertNotIn("schema", auto_wired["payload"])
        curated_plain, curated_wired = self.forecast("SNDK"), self.forecast("SNDK", wire_enabled=True)
        self.assertEqual(self.resolved.bindings.issuer("SNDK").disposition, "CURATED")
        self.assertEqual(curated_plain["version"], 3)
        self.assertNotIn("schema", curated_plain)
        self.assertEqual(curated_wired, {"schema": wire.TRANSPORT_SCHEMA, "admission_mode": wire.ADMISSION_MODE,
                                         "payload": curated_plain})

    def test_double_wrapped_or_forged_payloads_are_refused_by_the_serializer(self):
        envelope = self.forecast()
        payload = envelope["payload"]
        self.assertIsNotNone(machine.make_machine_envelope(copy.deepcopy(payload), "NVDA", self.resolved))
        def forged(change):
            value = copy.deepcopy(payload)
            change(value)
            return value
        auto_update = lambda v: v["evidence"]["auto_update"]  # noqa: E731
        cases = {
            "machine-envelope-as-payload": copy.deepcopy(envelope),
            "transport-envelope-as-payload": wire.envelope_v3_forecast(payload),
            "version-4": forged(lambda v: v.update(version=4)),
            "disposition": forged(lambda v: auto_update(v).update(disposition="CURATED")),
            "admission-kind": forged(lambda v: auto_update(v).update(admission_kind="HUMAN_PROFILE")),
            "extra-evidence-key": forged(lambda v: auto_update(v).update(approval="synthetic")),
            "input-digest": forged(lambda v: auto_update(v).update(input_digest="0" * 64)),
            "missing-auto-update": forged(lambda v: v["evidence"].pop("auto_update")),
        }
        for name, value in cases.items():
            with self.subTest(name):
                self.blocked(lambda: machine.make_machine_envelope(value, "NVDA", self.resolved))
        curated = copy.deepcopy(self.forecast("SNDK"))
        curated["evidence"] = {**(curated.get("evidence") or {}), "auto_update": copy.deepcopy(auto_update(payload))}
        self.blocked(lambda: machine.make_machine_envelope(curated, "SNDK", self.resolved))
        self.blocked(lambda: machine.make_machine_envelope(copy.deepcopy(payload), "ZZZZ", self.resolved))

    def test_resolver_accepts_only_the_genuine_snapshot_and_exact_symbol_tuple(self):
        snapshot, symbols = self.resolved.snapshot, tuple(sorted(self.resolved.bindings.public()["issuers"]))
        self.assertEqual(machine.resolve_machine_inputs(snapshot, auto.CUTOFF, symbols).bindings, self.resolved.bindings)
        self.blocked(lambda: machine.resolve_machine_inputs(None, auto.CUTOFF, symbols), "GUIDANCE_MACHINE_PROVIDER_UNAVAILABLE")
        later = auto.CUTOFF.replace(second=1)
        for name, call in (
                ("supplied-json", lambda: machine.resolve_machine_inputs(json.loads(json.dumps(self.resolved.bindings.public())),
                                                                         auto.CUTOFF, symbols)),
                ("other-cutoff", lambda: machine.resolve_machine_inputs(snapshot, later, symbols)),
                ("symbol-list", lambda: machine.resolve_machine_inputs(snapshot, auto.CUTOFF, list(symbols))),
                ("nine-symbols", lambda: machine.resolve_machine_inputs(snapshot, auto.CUTOFF, symbols[:9])),
                ("duplicate-symbol", lambda: machine.resolve_machine_inputs(snapshot, auto.CUTOFF, symbols[:9] + symbols[:1])),
                ("unknown-symbol", lambda: machine.resolve_machine_inputs(snapshot, auto.CUTOFF, symbols[:9] + ("ZZZZ",)))):
            with self.subTest(name):
                self.blocked(call)

    def test_resolved_inputs_cannot_be_substituted_or_edited(self):
        symbols = tuple(sorted(self.resolved.bindings.public()["issuers"]))
        self.assertIs(machine.require_machine_inputs(self.resolved, auto.CUTOFF, symbols), self.resolved)
        self.blocked(lambda: machine.require_machine_inputs(None, auto.CUTOFF, symbols), "GUIDANCE_MACHINE_PROVIDER_UNAVAILABLE")
        bindings = self.resolved.bindings
        edited = (dataclasses.replace(bindings, input_digest="0" * 64),
                  dataclasses.replace(bindings, issuers=tuple((k, dataclasses.replace(v, disposition="CURATED"))
                                                              for k, v in bindings.issuers)))
        for name, value in (("public-dict", {"snapshot": self.resolved.snapshot, "bindings": bindings.public()}),
                            ("namespace", SimpleNamespace(snapshot=self.resolved.snapshot, bindings=bindings)),
                            ("edited-digest", dataclasses.replace(self.resolved, bindings=edited[0])),
                            ("edited-disposition", dataclasses.replace(self.resolved, bindings=edited[1]))):
            with self.subTest(name):
                self.blocked(lambda: machine.require_machine_inputs(value, auto.CUTOFF, symbols))

    def test_compact_is_finite_exact_utf8_bytes(self):
        text = {"label": "\u00e9" * 10}
        raw = machine.compact(text, 10 ** 6)
        self.assertEqual(raw, json.dumps(text, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
        self.assertEqual(machine.compact(text, len(raw)), raw)
        self.blocked(lambda: machine.compact(text, len(raw) - 1), "MACHINE_EVIDENCE_LIMIT")
        for value in ({"x": float("nan")}, {"x": float("inf")}, {"x": object()}, {"x": b"bytes"}):
            with self.subTest(value=repr(value)):
                self.blocked(lambda: machine.compact(value, 10 ** 6), "MACHINE_EVIDENCE_LIMIT")


class PublicBundleByteBoundTests(unittest.TestCase):
    """Exact public report/binding byte caps on the frozen genuine AUTO bundle."""
    @classmethod
    def setUpClass(cls):
        fixture = json.loads(auto.FIXTURE.read_text(encoding="utf-8"))
        cls.report, cls.binding = fixture["report"].encode("utf-8"), fixture["binding"].encode("utf-8")

    def validate(self, report, binding):
        sha = lambda raw: hashlib.sha256(raw).hexdigest()  # noqa: E731
        return machine.validate_public_bundle(report, binding, sha(report), sha(binding))

    def rebound(self, report):
        doc = json.loads(self.binding)
        doc["report_sha256"] = hashlib.sha256(report).hexdigest()
        return json.dumps(doc, ensure_ascii=False, separators=(",", ":")).encode("utf-8")

    def test_binding_cap_is_exact(self):
        self.assertEqual(self.validate(self.report, self.binding)["report_sha256"], hashlib.sha256(self.report).hexdigest())
        at_cap = self.binding + b" " * (machine.BINDING_BYTES - len(self.binding))
        self.assertIsInstance(self.validate(self.report, at_cap), dict)
        with self.assertRaises(machine.MachinePublicationBlocked):
            self.validate(self.report, at_cap + b" ")

    def test_report_cap_is_exact_with_a_rebound_digest(self):
        at_cap = self.report + b" " * (machine.REPORT_BYTES - len(self.report))
        self.assertIsInstance(self.validate(at_cap, self.rebound(at_cap)), dict)
        over = at_cap + b" "
        with self.assertRaises(machine.MachinePublicationBlocked):
            self.validate(over, self.rebound(over))
        # A stale outer digest is refused independently of size.
        with self.assertRaises(machine.MachinePublicationBlocked):
            self.validate(at_cap, self.binding)


if __name__ == "__main__":
    unittest.main()
