"""Historical Worker parity, excluding only admission-source identity and its digests.

load_effective_inputs hashes the reviewed implementation into input_digest;
publish_generation hashes that identity (and its parent chain) into generation_sha256.
Changing those public fields changes the enclosing report_sha256. No document,
capture, receipt, record, decision, profile, baseline or manifest digest is ignored.
"""
from __future__ import annotations

import json
import re

import revenue_guidance_machine as machine

_CANONICAL_FIELDS = frozenset({
    "record_canonical_json", "producer_canonical_json", "decisions_canonical_json",
})
_CANONICAL_IMPLEMENTATION = re.compile(r'(?<!\\)("implementation_sha256"\s*:\s*)"([0-9a-f]{64})"')


def _digest(value, field):
    if value is None:
        return None
    if type(value) is not str or not machine.SHA.fullmatch(value):
        raise AssertionError(f"invalid source-dependent digest: {field}")
    return f"<source-dependent:{field}>"


def _implementation_identity(value):
    """Walk structure, not hash-shaped strings; canonical JSON remains a string."""
    if isinstance(value, list):
        return [_implementation_identity(child) for child in value]
    if not isinstance(value, dict):
        return value
    result = {}
    for key, child in value.items():
        if key == "implementation_sha256":
            result[key] = _digest(child, key)
        elif key in _CANONICAL_FIELDS and isinstance(child, str):
            # Replace only this concrete JSON property token, NOT every matching
            # digest or a reserialized object. Whitespace/escaping and all other
            # canonical-string bytes remain parity-sensitive.
            json.loads(child)
            result[key] = _CANONICAL_IMPLEMENTATION.sub(
                lambda match: match[1] + json.dumps(_digest(match[2], "implementation_sha256")), child)
        else:
            result[key] = _implementation_identity(child)
    return result


def consumer_view(bundle):
    """Validate ORIGINAL wire integrity before projecting the explicit identity fields.

    Only binding.report_sha256, and input_digest/generation_sha256 on the binding,
    machine attachment and auto_update evidence are projected, plus the exact
    implementation_sha256 field (including inside the three canonical JSON strings).
    Null stays null; missing fields, extra fields and all other values remain visible.
    Producers still independently resolve/validate actual state before returning bytes.
    """
    raw, binding_raw = (bundle[name].encode("utf-8") for name in ("report", "binding"))
    machine.validate_public_bundle(raw, binding_raw, machine.sha256(raw), machine.sha256(binding_raw))
    result = dict(bundle)
    report, binding = json.loads(raw), json.loads(binding_raw)
    binding["report_sha256"] = _digest(binding["report_sha256"], "report_sha256")
    source_digests = {field: binding[field] for field in ("input_digest", "generation_sha256")}
    targets = [binding]
    for row in report["top"]:
        envelope = row["outlook"]["order_forecast_v3"]
        if isinstance(envelope, dict) and envelope.get("schema") == machine.MACHINE_SCHEMA:
            targets.extend((envelope["machine"], envelope["payload"]["evidence"]["auto_update"]))
    for target in targets:
        for field in ("input_digest", "generation_sha256"):
            if field in target:
                if target[field] != source_digests[field]:
                    raise AssertionError(f"source-dependent digest copies disagree: {field}")
                target[field] = _digest(target[field], field)
    result.update(report=_implementation_identity(report), binding=_implementation_identity(binding))
    return result
