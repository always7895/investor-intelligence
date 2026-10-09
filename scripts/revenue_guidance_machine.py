"""F03 genuine same-owner machine serialization and public selection data.

SOURCE ONLY / IMPLEMENTED_UNVERIFIED. No loader/provider fallback, private seal
construction, financial mutation, native qualification or execution authority.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
from typing import Any

import revenue_guidance_auto_verify as verify
import revenue_guidance_overlay as overlay

MACHINE_SCHEMA = "v213-order-forecast-machine-v1"
MACHINE_ATTACHMENT = "revenue-guidance-machine-evidence-v1"
BINDING_SCHEMA = "revenue-guidance-public-binding-v1"
BINDING_KEY = "v213:revenue-guidance-binding:v1"
REPORT_KEY = "v213:bottleneck-top20:v3"
ENVELOPE_BYTES = 256000
BINDING_BYTES = 64000
REPORT_BYTES = 1900000
SHA = re.compile(r"^[0-9a-f]{64}$")
GIR = re.compile(r"^gir1:[0-9a-f]{64}$")
INSTANT = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$")
TOKEN_PATTERN = re.compile(r"^[0-9a-f]{32}$")
IDENTITY_KEYS = ("verifier_version", "normalizer_version", "implementation_sha256",
                 "profiles_sha256", "baseline_registry_sha256", "baseline_approval_sha256")
ISSUER_KEYS = {"symbol", "disposition", "reason", "admission_kind", "identity",
               "attempt_sha256", "record_sha256", "receipt_digest"}
BINDING_KEYS = {"schema", "report_sha256", "cutoff", "revision", "input_digest",
                "generation_id", "generation_sha256", "source_manifest_sha256", "issuers"}
REASONS = frozenset({"GUIDANCE_MACHINE_PROVIDER_UNAVAILABLE", "MACHINE_INPUTS_UNAVAILABLE",
                     "MACHINE_EVIDENCE_LIMIT", "MACHINE_EXPORT_UNAVAILABLE"})
PUBLIC_STAGE_ROOT = Path(__file__).resolve().parents[1] / "state" / "guidance-public-exports"


class MachinePublicationBlocked(Exception):
    """Fixed typed block; actual caller handlers must explicitly preserve it."""
    def __init__(self, reason="MACHINE_INPUTS_UNAVAILABLE"):
        self.reason = reason if reason in REASONS else "MACHINE_INPUTS_UNAVAILABLE"
        super().__init__(self.reason)


def sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def compact(value: Any, limit: int) -> bytes:
    try:
        raw = json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8")
    except (ValueError, TypeError, UnicodeError, OverflowError, RecursionError):
        raise MachinePublicationBlocked("MACHINE_EVIDENCE_LIMIT") from None
    if len(raw) > limit:
        raise MachinePublicationBlocked("MACHINE_EVIDENCE_LIMIT")
    return raw


def strict_json(raw: bytes, limit: int):
    def unique(pairs):
        out = {}
        for key, value in pairs:
            if key in out:
                raise ValueError()
            out[key] = value
        return out
    try:
        if type(raw) is not bytes or not raw or len(raw) > limit:
            raise ValueError()
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=unique,
                           parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
        stack, nodes = [(value, 0)], 0
        while stack:
            item, depth = stack.pop()
            nodes += 1
            if depth > 32 or nodes > 200000:
                raise ValueError()
            if type(item) is dict:
                stack.extend((v, depth + 1) for v in item.values())
            elif type(item) is list:
                stack.extend((v, depth + 1) for v in item)
        return value
    except (ValueError, TypeError, UnicodeError, RecursionError):
        raise MachinePublicationBlocked("MACHINE_INPUTS_UNAVAILABLE") from None


@dataclass(frozen=True)
class IssuerBinding:
    symbol: str
    disposition: str
    reason: str | None
    admission_kind: str | None
    identity: tuple[tuple[str, Any], ...]
    attempt_sha256: str | None
    record_sha256: str | None
    receipt_digest: str | None

    def public(self):
        return {"symbol": self.symbol, "disposition": self.disposition, "reason": self.reason,
                "admission_kind": self.admission_kind, "identity": dict(self.identity),
                "attempt_sha256": self.attempt_sha256, "record_sha256": self.record_sha256,
                "receipt_digest": self.receipt_digest}


@dataclass(frozen=True)
class MachineBindings:
    cutoff: str
    input_digest: str
    generation_id: str | None
    generation_sha256: str | None
    issuers: tuple[tuple[str, IssuerBinding], ...]

    def issuer(self, symbol):
        for key, value in self.issuers:
            if key == symbol and value.symbol == symbol:
                return value
        raise MachinePublicationBlocked()

    def public(self):
        return {"cutoff": self.cutoff, "input_digest": self.input_digest,
                "generation_id": self.generation_id, "generation_sha256": self.generation_sha256,
                "issuers": {key: value.public() for key, value in self.issuers}}


@dataclass(frozen=True)
class ResolvedMachineInputs:
    snapshot: overlay.EffectiveInputs
    bindings: MachineBindings


def _issuer_binding(snapshot, symbol):
    item = snapshot.issuer(symbol)
    if item is None or item.symbol != symbol:
        raise ValueError()
    if item.disposition == "CURATED":
        if item.evidence is not None or item.producer is not None or item.receipt_admission is not None:
            raise ValueError()
        if ((item.usable_record is None) != (item.record_sha256 is None) or
                item.admission_kind != ("HUMAN_PROFILE" if item.usable_record is not None else None)):
            raise ValueError()
        return IssuerBinding(symbol, item.disposition, item.reason, item.admission_kind, (), None,
                             item.record_sha256, None)
    ev = item.evidence
    if (type(ev) is not dict or ev["issuer"] != symbol or ev["disposition"] != item.disposition or
            ev["reason"] != item.reason or ev["admission_kind"] != item.admission_kind or
            type(ev["identity"]) is not dict or set(ev["identity"]) != set(IDENTITY_KEYS)):
        raise ValueError()
    receipt = ev["receipt"]
    if receipt is not None:
        if item.receipt_admission is None or receipt != {k: item.receipt_admission[k] for k in receipt}:
            raise ValueError()
    elif item.receipt_admission is not None:
        raise ValueError()
    receipt_pin = None if receipt is None else receipt["receipt_digest"]
    attempt_pin = None
    if item.disposition == "AUTO_VERIFIED":
        if (item.admission_kind != "MACHINE_REPLAY" or item.usable_record is None or
                item.producer is None or item.producer["outcome"] != "VERIFIED" or
                not snapshot.generation_id or not snapshot.generation_sha256 or receipt is None or
                not receipt["reference"] or item.receipt_admission["decision"] is not None):
            raise ValueError()
        producer = ev["producer"]
        if type(producer) is not dict:
            raise ValueError()
        record_text = verify.canonical_json(item.usable_record)
        attempt_text = verify.canonical_json(item.producer)
        decisions_text = verify.canonical_json(item.producer["decisions"])
        if (sha256(record_text.encode()) != item.record_sha256 or producer["record_sha256"] != item.record_sha256 or
                sha256(attempt_text.encode()) != producer["attempt_sha256"] or
                sha256(decisions_text.encode()) != producer["decisions_sha256"] or
                verify.canonical_json(item.producer["record"]) != record_text or
                receipt["reference"] != overlay.reference(item.usable_record)[0]):
            raise ValueError()
        if ev["decisions"] != [{k: d[k] for k in ("kind", "ref", "decision", "capture", "operands")}
                                for d in item.producer["decisions"]]:
            raise ValueError()
        if ev["consumed"] != sorted([list(row) for row in overlay.consumed_identities(item.producer)]):
            raise ValueError()
        attempt_pin = producer["attempt_sha256"]
        if any(not SHA.fullmatch(str(pin)) for pin in (attempt_pin, item.record_sha256, receipt_pin)):
            raise ValueError()
    elif item.disposition in ("WAITING", "BLOCKED", "SUSPENDED"):
        if (item.admission_kind is not None or item.usable_record is not None or item.record_sha256 is not None or
                ev["producer"] is not None or ev["decisions"] or ev["consumed"]):
            raise ValueError()  # retained historical producer is NEVER admitted here
    else:
        raise ValueError()
    return IssuerBinding(symbol, item.disposition, item.reason, item.admission_kind,
                         tuple((k, ev["identity"][k]) for k in IDENTITY_KEYS), attempt_pin,
                         item.record_sha256, receipt_pin)


def resolve_machine_inputs(snapshot, cutoff: datetime, symbols: tuple[str, ...]) -> ResolvedMachineInputs:
    """REAL same-owner resolver: genuine already-acquired snapshot only.

    No acquire callback placeholder/default path loader or serialized admission.
    Host owns native acquisition and passes THIS same object to model consumption.
    """
    if snapshot is None:
        raise MachinePublicationBlocked("GUIDANCE_MACHINE_PROVIDER_UNAVAILABLE")
    try:
        snapshot = overlay.require_snapshot(snapshot, cutoff)
        if type(symbols) is not tuple or not 10 <= len(symbols) <= 20 or len(set(symbols)) != len(symbols):
            raise ValueError()
        if not SHA.fullmatch(snapshot.input_digest):
            raise ValueError()
        entries = tuple((s, _issuer_binding(snapshot, s)) for s in sorted(symbols))
        return ResolvedMachineInputs(snapshot, MachineBindings(snapshot.cutoff, snapshot.input_digest,
                                    snapshot.generation_id, snapshot.generation_sha256, entries))
    except MachinePublicationBlocked:
        raise
    except (overlay.EffectiveInputsError, ValueError, KeyError, TypeError, AttributeError, UnicodeError):
        raise MachinePublicationBlocked() from None


def require_machine_inputs(resolved, cutoff, symbols):
    if resolved is None:
        raise MachinePublicationBlocked("GUIDANCE_MACHINE_PROVIDER_UNAVAILABLE")
    if type(resolved) is not ResolvedMachineInputs or type(resolved.bindings) is not MachineBindings:
        raise MachinePublicationBlocked()
    checked = resolve_machine_inputs(resolved.snapshot, cutoff, tuple(symbols))
    if checked.bindings != resolved.bindings:
        raise MachinePublicationBlocked()
    return resolved


def make_machine_envelope(payload, symbol, resolved):
    try:
        snapshot = overlay.require_snapshot(resolved.snapshot, resolved.bindings.cutoff)
        binding = resolved.bindings.issuer(symbol)
        if binding != _issuer_binding(snapshot, symbol) or type(payload) is not dict or payload["version"] != 3:
            raise ValueError()
        item = snapshot.issuer(symbol)
        auto = (payload.get("evidence") or {}).get("auto_update")
        if binding.disposition == "CURATED":
            if auto is not None:
                raise ValueError()
            return None  # caller keeps the independently validated human/transport route
        expected = {**item.evidence, "cutoff": snapshot.cutoff, "input_digest": snapshot.input_digest,
                    "generation_sha256": snapshot.generation_sha256}
        if auto != expected:
            raise ValueError()
        record = producer = decisions = None
        if binding.disposition == "AUTO_VERIFIED":
            record = verify.canonical_json(item.usable_record)
            producer = verify.canonical_json(item.producer)
            decisions = verify.canonical_json(item.producer["decisions"])
        reference = None if item.evidence["receipt"] is None else item.evidence["receipt"]["reference"]
        history = [] if reference is None else overlay.receipt_rows(snapshot.release_checks, symbol, reference, snapshot.cutoff)
        attachment = {"schema": MACHINE_ATTACHMENT, "issuer": symbol, "cutoff": snapshot.cutoff,
                      "input_digest": snapshot.input_digest, "generation_id": snapshot.generation_id,
                      "generation_sha256": snapshot.generation_sha256, "identity": dict(binding.identity),
                      "record_canonical_json": record, "producer_canonical_json": producer,
                      "decisions_canonical_json": decisions, "receipt_history": history}
        result = {"schema": MACHINE_SCHEMA, "admission_mode": "B1_MACHINE_V1", "payload": payload,
                  "machine": attachment}
        compact(result, ENVELOPE_BYTES)  # ENTIRE envelope, no trimming/rehydrating scoped EVIDENCE_LIMIT
        return result
    except MachinePublicationBlocked:
        raise
    except (ValueError, KeyError, TypeError, AttributeError, overlay.EffectiveInputsError, UnicodeError):
        raise MachinePublicationBlocked() from None


def make_public_binding(resolved, report: bytes, revision: str, source_manifest: bytes) -> bytes:
    try:
        if not GIR.fullmatch(revision) or type(strict_json(source_manifest, 8 * 1024 * 1024)) is not dict:
            raise ValueError()
        doc = strict_json(report, REPORT_BYTES)
        symbols = tuple(row["symbol"] for row in doc["top"])
        cutoff = datetime.strptime(doc["generated_at"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        require_machine_inputs(resolved, cutoff, symbols)
        if doc["schema"] != "v213-bottleneck-top20-v3-sealed":
            raise ValueError()
        binding = {"schema": BINDING_SCHEMA, "report_sha256": sha256(report), "revision": revision,
                   "source_manifest_sha256": sha256(source_manifest),
                   **resolved.bindings.public()}
        return compact(binding, BINDING_BYTES)
    except MachinePublicationBlocked:
        raise
    except (ValueError, KeyError, TypeError, AttributeError, UnicodeError):
        raise MachinePublicationBlocked() from None


def validate_public_bundle(report, binding_raw, expected_report_sha, expected_binding_sha):
    """PUBLIC data consistency; expected digests MUST originate in the live parent channel."""
    try:
        if any(type(h) is not str or not SHA.fullmatch(h) for h in (expected_report_sha, expected_binding_sha)):
            raise ValueError()
        if sha256(report) != expected_report_sha or sha256(binding_raw) != expected_binding_sha:
            raise ValueError()
        binding, doc = strict_json(binding_raw, BINDING_BYTES), strict_json(report, REPORT_BYTES)
        if (type(binding) is not dict or set(binding) != BINDING_KEYS or binding["schema"] != BINDING_SCHEMA or
                binding["report_sha256"] != expected_report_sha or binding["cutoff"] != doc["generated_at"] or
                doc["schema"] != "v213-bottleneck-top20-v3-sealed" or not GIR.fullmatch(binding["revision"]) or
                not SHA.fullmatch(binding["input_digest"]) or not SHA.fullmatch(binding["source_manifest_sha256"])):
            raise ValueError()
        datetime.strptime(binding["cutoff"], "%Y-%m-%dT%H:%M:%SZ")
        if (binding["generation_id"] is None) != (binding["generation_sha256"] is None):
            raise ValueError()
        if binding["generation_sha256"] is not None and not SHA.fullmatch(binding["generation_sha256"]):
            raise ValueError()
        rows = doc["top"]
        symbols = [row["symbol"] for row in rows]
        if (not 10 <= len(rows) <= 20 or len(set(symbols)) != len(symbols) or
                type(binding["issuers"]) is not dict or set(binding["issuers"]) != set(symbols)):
            raise ValueError()
        for row in rows:
            symbol = row["symbol"]
            pin = binding["issuers"][symbol]
            if type(pin) is not dict or set(pin) != ISSUER_KEYS or pin["symbol"] != symbol:
                raise ValueError()
            envelope = row["outlook"]["order_forecast_v3"]
            if pin["disposition"] == "CURATED":
                if pin["identity"] != {} or pin["attempt_sha256"] is not None or pin["receipt_digest"] is not None:
                    raise ValueError()
                if isinstance(envelope, dict) and envelope.get("schema") == MACHINE_SCHEMA:
                    raise ValueError()
                continue
            if (envelope["schema"] != MACHINE_SCHEMA or envelope["admission_mode"] != "B1_MACHINE_V1" or
                    set(pin["identity"]) != set(IDENTITY_KEYS)):
                raise ValueError()
            compact(envelope, ENVELOPE_BYTES)
            ev = envelope["payload"]["evidence"]["auto_update"]
            material = envelope["machine"]
            if (material["issuer"] != symbol or material["cutoff"] != binding["cutoff"] or
                    material["input_digest"] != binding["input_digest"] or
                    material["generation_id"] != binding["generation_id"] or
                    material["generation_sha256"] != binding["generation_sha256"] or material["identity"] != pin["identity"] or
                    any(ev[k] != pin[k] for k in ("disposition", "reason", "admission_kind", "identity"))):
                raise ValueError()
        return binding
    except MachinePublicationBlocked:
        raise
    except (ValueError, KeyError, TypeError, AttributeError, UnicodeError):
        raise MachinePublicationBlocked() from None


def read_staged_bundle(token, expected_report_sha, expected_binding_sha):
    """Fixed finite public DATA location, no packet-selected pathname or expected hash."""
    try:
        if type(token) is not str or not TOKEN_PATTERN.fullmatch(token):
            raise ValueError()
        root = PUBLIC_STAGE_ROOT
        for parent in (*reversed(root.parents), root):
            stat = parent.lstat()
            if parent.is_symlink() or getattr(stat, "st_file_attributes", 0) & 0x400:
                raise ValueError()
        values = []
        for suffix, limit in ((".body.txt", REPORT_BYTES), (".binding.json", BINDING_BYTES)):
            path = root / (token + suffix)
            before = path.lstat()
            if (path.is_symlink() or getattr(before, "st_file_attributes", 0) & 0x400 or
                    before.st_nlink != 1 or not 0 < before.st_size <= limit):
                raise ValueError()
            with path.open("rb") as handle:
                actual = os.fstat(handle.fileno())
                raw = handle.read(limit + 1)
                after = os.fstat(handle.fileno())
                if (actual.st_ino, actual.st_dev, actual.st_size, actual.st_mtime_ns) != (
                        before.st_ino, before.st_dev, before.st_size, before.st_mtime_ns) or (
                        actual.st_ino, actual.st_dev, actual.st_size, actual.st_mtime_ns) != (
                        after.st_ino, after.st_dev, after.st_size, after.st_mtime_ns):
                    raise ValueError()
            if len(raw) != before.st_size:
                raise ValueError()
            values.append(raw)
        report, binding = values
        validate_public_bundle(report, binding, expected_report_sha, expected_binding_sha)
        return {REPORT_KEY: report.decode("utf-8"), BINDING_KEY: binding.decode("utf-8")}
    except MachinePublicationBlocked:
        raise
    except (OSError, ValueError, KeyError, TypeError, AttributeError, UnicodeError):
        raise MachinePublicationBlocked("MACHINE_EXPORT_UNAVAILABLE") from None
