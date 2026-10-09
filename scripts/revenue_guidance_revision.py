# revenue_guidance_revision.py
#
# PROVIDER-CORE-01 / Deliverable A — stable effective input revision helper.
#
# Exports:
#   revision_material(snapshot) -> dict  — detached, JSON-compatible mapping of the
#       "guidance-input-revision-v1" schema; no elapsed clock, no cutoff/path/seal/GUID.
#   compute_input_revision(snapshot) -> str  — canonical "gir1:<lower-case SHA256>" token.
#
# Both functions require a genuine EffectiveInputs produced by revenue_guidance_overlay
# (validated lazily via require_snapshot); no file I/O, no seal construction and no
# platform call enters this module at import time or during normal operation.
#
# The revision token is the single algorithm the future capability backend uses for its
# opaque ReadInputRevision result.  Do NOT duplicate the per-issuer projection logic here
# in PowerShell; the PS module receives only the opaque token.
#
# Field sources (addendum-verified):
#   item.record_sha256     — the issuer item's own field; this is the LIVE value
#                            (not manifest_issuer.usable_record_sha256, which is the
#                            already-stored copy written from item.record_sha256 at
#                            manifest build time — they match when the snapshot is fresh,
#                            but the contract says to read from the item directly).
#   manifest_issuer.usable_record_sha256  — also read (named field from manifest issuer
#                                           entry); included in the per-issuer revision
#                                           projection alongside item.record_sha256.
#   manifest_issuer.discovery_record_sha256 — the hash of the discovery record stored in
#                                             the manifest issuer entry.
#   manifest_issuer.detections — triples [channel, id, date] (manifest form);
#   item.detections — list of dicts with a "disposition" key plus channel/id/date;
#       the addendum requires disposition from the ITEM (manifest detections are triples).
#   receipt_admission — from the item (not the manifest receipt sub-object).
#
# CODE_ONLY_WRITTEN_NOT_EXECUTED.  Not functional ACCEPT.

from __future__ import annotations

from typing import Any

# ---------------------------------------------------------------------------
# Schema constant (revision v1)
# ---------------------------------------------------------------------------
_REVISION_SCHEMA = "guidance-input-revision-v1"

# Required top-level keys in manifest.inputs for a supported (non-CURATED_ONLY) snapshot.
# CURATED_ONLY manifests have neither "profiles" nor "receipts"; they are UNSUPPORTED.
_REQUIRED_INPUT_KEYS: frozenset[str] = frozenset({"registry", "approval", "profiles", "receipts"})

# Required keys in manifest.implementation.
_REQUIRED_IMPL_KEYS: frozenset[str] = frozenset(
    {"implementation_sha256", "verifier_version", "normalizer_version"}
)

# Required keys in each manifest issuer entry.
_REQUIRED_MANIFEST_ISSUER_KEYS: frozenset[str] = frozenset(
    {"disposition", "reason", "admission_kind", "discovery_origin",
     "discovery_reference", "discovery_record_sha256", "usable_record_sha256", "overflow"}
)

# Required keys in each item.detections element (from IssuerInputs).
_REQUIRED_DETECTION_KEYS: frozenset[str] = frozenset({"channel", "id", "date", "disposition"})

# Fixed bounded error for unsupported/incomplete manifest shape.  Every raise carries a
# fixed bounded token: the absence / unsupported-shape raise path uses
# UNSUPPORTED_REVISION_MATERIAL; the existing MANIFEST_* / ISSUER_* fixed shape tokens
# remain.  No path, payload or private detail is ever included.
class UnsupportedManifestShape(Exception):
    """Fixed-token error for an absent required block/key/attribute or a reduced manifest
    shape (including CURATED_ONLY).  Never carries raw details.  Also exported as
    RevisionUnavailable."""
    FIXED_TOKEN = "UNSUPPORTED_REVISION_MATERIAL"


# Contract-facing name: raising RevisionUnavailable("UNSUPPORTED_REVISION_MATERIAL") is
# the single absence/unsupported-shape signal; no AttributeError or raw detail escapes.
RevisionUnavailable = UnsupportedManifestShape


# ---------------------------------------------------------------------------
# Internal helpers — no I/O, no clock, no seal.
# ---------------------------------------------------------------------------

def _require_manifest_inputs(manifest: dict[str, Any]) -> dict[str, Any]:
    """Return a copy of manifest.inputs, restricted to the allowlisted required keys.
    Raises UnsupportedManifestShape when the block is absent or missing required keys.
    Preserves genuine B1 typed fault-marker strings exactly (e.g. "FAULT:INVALID:...").
    Does not add defaults or invent missing keys."""
    raw = manifest.get("inputs")
    if not isinstance(raw, dict):
        raise UnsupportedManifestShape("MANIFEST_INPUTS_ABSENT")
    missing = _REQUIRED_INPUT_KEYS - raw.keys()
    if missing:
        raise UnsupportedManifestShape("MANIFEST_INPUTS_INCOMPLETE")
    # Explicit allowlist projection: only the required keys are included in the revision.
    return {k: raw[k] for k in sorted(_REQUIRED_INPUT_KEYS)}


def _require_manifest_implementation(manifest: dict[str, Any]) -> dict[str, Any]:
    """Return a copy of manifest.implementation restricted to the allowlisted keys.
    Raises UnsupportedManifestShape when the block is absent or missing required keys."""
    raw = manifest.get("implementation")
    if not isinstance(raw, dict):
        raise UnsupportedManifestShape("MANIFEST_IMPLEMENTATION_ABSENT")
    missing = _REQUIRED_IMPL_KEYS - raw.keys()
    if missing:
        raise UnsupportedManifestShape("MANIFEST_IMPLEMENTATION_INCOMPLETE")
    return {k: raw[k] for k in sorted(_REQUIRED_IMPL_KEYS)}


def _require_manifest_issuer(sym: str, manifest_issuers: dict[str, Any]) -> dict[str, Any]:
    """Return the manifest issuer entry for sym; raises UnsupportedManifestShape if absent
    or missing required keys.  Does not default to {} for a missing entry."""
    entry = manifest_issuers.get(sym)
    if not isinstance(entry, dict):
        raise UnsupportedManifestShape("MANIFEST_ISSUER_ABSENT")
    missing = _REQUIRED_MANIFEST_ISSUER_KEYS - entry.keys()
    if missing:
        raise UnsupportedManifestShape("MANIFEST_ISSUER_INCOMPLETE")
    return entry


def _item_present(item: Any, key: str) -> bool:
    """True when key is a present mapping key / object attribute (explicit None counts)."""
    if isinstance(item, dict):
        return key in item
    return hasattr(item, key)


def _require_item_field(item: Any, key: str) -> Any:
    """Read a REQUIRED item field, checking presence before reading.  An absent mapping
    key / object attribute raises the fixed RevisionUnavailable token; an explicit None
    value is returned as-is (genuine null preserved, never substituted by absence)."""
    if not _item_present(item, key):
        raise RevisionUnavailable("UNSUPPORTED_REVISION_MATERIAL")
    if isinstance(item, dict):
        return item[key]
    return getattr(item, key)


def _issuer_entry(sym: str, item: Any, manifest_issuer: dict[str, Any]) -> dict[str, Any]:
    """Build the per-issuer revision projection.

    item fields used (sourced from IssuerInputs directly, per addendum):
      disposition, reason, admission_kind, record_sha256 (live item field),
      discovery_origin, discovery_reference, overflow, detections, receipt_admission.

    manifest_issuer fields used (stored at manifest build time):
      usable_record_sha256, discovery_record_sha256.

    Detections: item.detections must be a list of dicts each containing the four
    required keys.  A non-list or any non-dict element raises UnsupportedManifestShape
    rather than being silently dropped or defaulted.

    receipt_admission: presence is required (an absent field raises the fixed token,
    never a disposition fallback null); an explicit null is preserved; a present value
    that is neither dict nor None raises the fixed token.

    Every required item attribute/mapping key is presence-checked before being read;
    absence raises RevisionUnavailable("UNSUPPORTED_REVISION_MATERIAL"), never
    AttributeError or a silent default.  Genuine typed fault-marker strings and
    explicit nulls are copied through unchanged.
    """
    # --- item fields (required: presence checked, explicit None preserved) ---
    disposition      = _require_item_field(item, "disposition")
    reason           = _require_item_field(item, "reason")
    admission_kind   = _require_item_field(item, "admission_kind")
    item_record_sha  = _require_item_field(item, "record_sha256")
    discovery_origin = _require_item_field(item, "discovery_origin")
    discovery_ref    = _require_item_field(item, "discovery_reference")
    overflow         = _require_item_field(item, "overflow")

    # --- manifest stored fields ---
    manifest_usable_sha = manifest_issuer["usable_record_sha256"]    # explicit key (presence confirmed above)
    manifest_disc_sha   = manifest_issuer["discovery_record_sha256"]

    # --- material detections from item (disposition present in item form) ---
    raw_detections = _require_item_field(item, "detections")
    if not isinstance(raw_detections, list):
        raise UnsupportedManifestShape("ISSUER_DETECTIONS_NOT_LIST")
    material_detections: list[dict[str, Any]] = []
    for d in raw_detections:
        if not isinstance(d, dict):
            raise UnsupportedManifestShape("ISSUER_DETECTION_NOT_DICT")
        missing_keys = _REQUIRED_DETECTION_KEYS - d.keys()
        if missing_keys:
            raise UnsupportedManifestShape("ISSUER_DETECTION_INCOMPLETE")
        material_detections.append({
            "channel":     d["channel"],
            "id":          d["id"],
            "date":        d["date"],
            "disposition": d["disposition"],
        })
    # Canonical sort: (channel, id, date, disposition); None < string via empty-string proxy
    def _det_key(e: dict[str, Any]) -> tuple:
        return (
            "" if e["channel"] is None else str(e["channel"]),
            "" if e["id"] is None else str(e["id"]),
            "" if e["date"] is None else str(e["date"]),
            "" if e["disposition"] is None else str(e["disposition"]),
        )
    material_detections.sort(key=_det_key)

    # --- receipt_admission summary from item ---
    # Presence is required (absent raises the fixed token — no disposition fallback
    # null); an explicit null is preserved; the five summary keys are membership-
    # checked BEFORE projection (absence raises the fixed token, never an invented
    # default), then read by exact key so an explicit None is preserved.
    if not _item_present(item, "receipt_admission"):
        raise RevisionUnavailable("UNSUPPORTED_REVISION_MATERIAL")
    raw_receipt: Any = item["receipt_admission"] if isinstance(item, dict) else getattr(item, "receipt_admission")
    if raw_receipt is None:
        receipt_summary: Any = None                         # explicit null preserved
    elif isinstance(raw_receipt, dict):
        _receipt_keys = ("reference", "receipt_digest", "checked_at", "rows", "decision")
        missing_keys = [k for k in _receipt_keys if k not in raw_receipt]
        if missing_keys:
            # Omitted summary member: refuse with the fixed bounded token, not KeyError.
            raise UnsupportedManifestShape("UNSUPPORTED_REVISION_MATERIAL")
        receipt_summary = {k: raw_receipt[k] for k in _receipt_keys}
    else:
        raise UnsupportedManifestShape("ISSUER_RECEIPT_ADMISSION_INVALID")

    return {
        "symbol":                        sym,
        "disposition":                   disposition,
        "reason":                        reason,
        "admission_kind":                admission_kind,
        "record_sha256":                 item_record_sha,
        "manifest_usable_record_sha256": manifest_usable_sha,
        "discovery_origin":              discovery_origin,
        "discovery_reference":           discovery_ref,
        "discovery_record_sha256":       manifest_disc_sha,
        "overflow":                      overflow,
        "material_detections":           material_detections,
        "receipt_admission":             receipt_summary,
    }


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def revision_material(snapshot: Any) -> dict[str, Any]:
    """Return a detached JSON-compatible mapping of schema "guidance-input-revision-v1".

    Raises UnsupportedManifestShape (fixed bounded token) when the snapshot's manifest
    does not carry the required revision-v1 source blocks — including CURATED_ONLY
    snapshots, which lack manifest.implementation and the required inputs.profiles /
    inputs.receipts keys.  No curated adapter or invented identity is supplied.

    Preserves genuine B1 typed fault-marker strings (e.g. "FAULT:INVALID:...") in
    manifest.inputs exactly as stored.  Preserves explicit null fields from the snapshot
    (generation_sha256, per-issuer reason, record_sha256, etc.) without defaulting them.

    Lazy imports revenue_guidance_overlay and revenue_guidance_auto_verify so that
    importing THIS module performs no native/API calls.
    """
    import revenue_guidance_overlay as _overlay  # noqa: PLC0415

    # Validate genuine sealed snapshot; raises EffectiveInputsError on type/seal mismatch.
    # No cutoff argument: no cutoff enters the revision.
    eff: Any = _overlay.require_snapshot(snapshot)

    manifest: dict[str, Any] = eff.manifest           # fresh copy via .part()
    state_condition: Any     = eff.condition
    generation_sha256: Any   = eff.generation_sha256

    # Require the full revision-v1 source blocks; CURATED_ONLY and any reduced shape raise.
    manifest_inputs         = _require_manifest_inputs(manifest)
    manifest_implementation = _require_manifest_implementation(manifest)

    manifest_issuers_raw: Any = manifest.get("issuers")
    if not isinstance(manifest_issuers_raw, dict):
        raise UnsupportedManifestShape("MANIFEST_ISSUERS_ABSENT")
    manifest_issuers: dict[str, Any] = manifest_issuers_raw

    # Per-issuer projection — symbol-sorted.
    symbols: list[str] = eff.symbols()
    issuer_entries: dict[str, Any] = {}
    for sym in sorted(symbols):
        item = eff.issuer(sym)
        if item is None:
            # symbols() returned sym but issuers part has no entry: unsupported shape.
            raise UnsupportedManifestShape("ISSUER_ITEM_ABSENT")
        m_issuer = _require_manifest_issuer(sym, manifest_issuers)
        issuer_entries[sym] = _issuer_entry(sym, item, m_issuer)

    return {
        "schema":                   _REVISION_SCHEMA,
        "manifest_inputs":          manifest_inputs,
        "manifest_implementation":  manifest_implementation,
        "state_condition":          state_condition,
        "generation_sha256":        generation_sha256,
        "issuers":                  issuer_entries,
    }


def compute_input_revision(snapshot: Any) -> str:
    """Return the opaque "gir1:<lower-case SHA256>" revision token for the snapshot.

    Canonicalizes the revision_material with the verifier's canonical_json rule
    (lazy import), hashes the UTF-8 encoding, and returns the token.
    Never overwrites snapshot.input_digest or claims native provenance.
    Returns a copy; does not mutate the snapshot or the material mapping.
    """
    # Lazy imports.
    import revenue_guidance_auto_verify as _verify  # noqa: PLC0415

    material = revision_material(snapshot)
    canonical_bytes = _verify.canonical_json(material).encode("utf-8")
    digest = _verify.sha256(canonical_bytes)
    return f"gir1:{digest.lower()}"
