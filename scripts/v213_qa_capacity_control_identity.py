"""
v213_qa_capacity_control_identity.py — PURE, IMMUTABLE identity foundation
(Gate B, slice GB-S1).

This module provides small, pure, side-effect-free validation primitives and a
frozen identity record for the FOUR accepted harness claims. It is NOT
authority verification, NOT Gate B acceptance, NOT a process launcher, and NOT
a complete controller.

SEMANTIC BOUNDARY (checked claims establish syntax/equality ONLY):
  * The strict Git/SHA256 validators check STRING SHAPE ONLY. A validated
    value does not prove Git tree/artifact observation, review approval, or
    authorize any action. The generic Git validator may validate its syntax
    but NEVER grants acceptance.
  * The frozen identity record pins the four accepted harness claims. Passing
    its validator means the caller mapping is syntactically and exactly equal
    to those pins. It does NOT establish provenance or standing authority.
  * The future control-review SHA is a DISTINCT role and is never silently set
    to the runtime source_head. No field here carries execution authority.

PURITY:
  * Public APIs are pure: no CLI activation, no mutable acceptance switch, no
    authority gate/window builder, no namespace writes, no Win32/process/
    network/clock/environment/Git lookups, no file/path loaders, no JSON
    canonicalization, no newline/encoding/BOM normalization, no configurable
    digest algorithm, no default-now or host snapshot assumptions.
  * The only imported standard modules are `hashlib` (pure digest primitive)
    and `dataclasses` (frozen record construction).
"""
import hashlib
from dataclasses import dataclass

__all__ = [
    "IdentityValidationError",
    "validate_git_commit",
    "validate_sha256",
    "ControllerIdentity",
    "ACCEPTED_CONTROLLER_IDENTITY",
    "validate_controller_identity_mapping",
    "verify_bytes_sha256",
]

_HEX = frozenset("0123456789abcdef")


class IdentityValidationError(ValueError):
    """Consistent ValueError-derived error for all identity validation failures."""


def _check_lowercase_hex(value, length, kind):
    if type(value) is not str:
        raise IdentityValidationError(
            f"{kind} must be an exact built-in str, got {type(value).__name__}")
    if len(value) != length:
        raise IdentityValidationError(
            f"{kind} must be exactly {length} chars, got {len(value)}")
    for ch in value:
        if ch not in _HEX:
            raise IdentityValidationError(
                f"{kind} must be ASCII lowercase hex only; bad char {ch!r}")
    return value


def validate_git_commit(value):
    """Strict source/control Git commit validator: exact built-in str, 40 ASCII
    lowercase hex. No trimming, case-folding, numeric coercion, bool/None, or
    bypassing subclasses. Returns the same validated string. Syntax only; this
    NEVER grants acceptance."""
    return _check_lowercase_hex(value, 40, "git_commit")


def validate_sha256(value):
    """Strict SHA256 digest validator: exact built-in str, 64 ASCII lowercase
    hex. NEVER use this SHA256 shape for source/control Git commit IDs."""
    return _check_lowercase_hex(value, 64, "sha256")


@dataclass(frozen=True)
class ControllerIdentity:
    """Frozen identity record for exactly the FOUR accepted harness claims.
    Immutable; field reassignment raises FrozenInstanceError. Establishes
    syntax/equality only; carries no execution authority."""
    source_head: str
    harness_sha256: str
    request_sha256: str
    run_plan_sha256: str


# Immutable accepted pin constant. No caller may override these production
# expected pins; the validator always compares against this record.
ACCEPTED_CONTROLLER_IDENTITY = ControllerIdentity(
    source_head="6922278ac865727fdcdded96535f94aaaabeb8b3",
    harness_sha256="ef6bef33bd510a9f3dc155145ae895749c512670d14c91eaa8ed782f7f024324",
    request_sha256="1fa1910c8db0dda712d6997717e7c5519c22de9465222dd302e96456bcc3f7b0",
    run_plan_sha256="3e36a3be4b1a4e5d42d3dd6927cf4e160aa26ea72a011df73a9ce6fbc304866d",
)

# Exact field set for THIS new 4-field controller identity-claim record.
_IDENTITY_FIELDS = ("source_head", "harness_sha256", "request_sha256", "run_plan_sha256")


def validate_controller_identity_mapping(mapping):
    """Validate a caller-supplied dict against exactly the new 4-field
    controller identity-claim schema, then return a fresh FROZEN record.

    * `type(mapping) is dict` required (no subclass / no retained mapping).
    * Exact key set required: missing or unknown fields rejected.
    * Every field shape AND exact pinned equality checked independently.
    * Shape-valid but wrong value fails.
    * No caller override of production expected pins.
    Establishes syntax/equality only; carries no execution authority.
    """
    if type(mapping) is not dict:
        raise IdentityValidationError(
            f"identity mapping must be an exact built-in dict, got {type(mapping).__name__}")
    # Exact built-in str key-type validation BEFORE set/sort/diagnostics.
    # Constant error text; never calls repr of untrusted keys.
    for key in mapping:
        if type(key) is not str:
            raise IdentityValidationError(
                "identity mapping keys must be exact built-in str")
    keys = set(mapping)
    expected_keys = set(_IDENTITY_FIELDS)
    if keys != expected_keys:
        missing = sorted(expected_keys - keys)
        unknown = sorted(keys - expected_keys)
        raise IdentityValidationError(
            f"identity mapping fields must be exactly {list(_IDENTITY_FIELDS)}; "
            f"missing={missing} unknown={unknown}")

    source_head = validate_git_commit(mapping["source_head"])
    if source_head != ACCEPTED_CONTROLLER_IDENTITY.source_head:
        raise IdentityValidationError("source_head does not equal accepted pin")
    harness_sha256 = validate_sha256(mapping["harness_sha256"])
    if harness_sha256 != ACCEPTED_CONTROLLER_IDENTITY.harness_sha256:
        raise IdentityValidationError("harness_sha256 does not equal accepted pin")
    request_sha256 = validate_sha256(mapping["request_sha256"])
    if request_sha256 != ACCEPTED_CONTROLLER_IDENTITY.request_sha256:
        raise IdentityValidationError("request_sha256 does not equal accepted pin")
    run_plan_sha256 = validate_sha256(mapping["run_plan_sha256"])
    if run_plan_sha256 != ACCEPTED_CONTROLLER_IDENTITY.run_plan_sha256:
        raise IdentityValidationError("run_plan_sha256 does not equal accepted pin")

    # Fresh frozen copy; the caller's mutable mapping is NOT retained.
    return ControllerIdentity(
        source_head=source_head,
        harness_sha256=harness_sha256,
        request_sha256=request_sha256,
        run_plan_sha256=run_plan_sha256,
    )


def verify_bytes_sha256(data, expected_sha256):
    """Pure bytes SHA256 verifier. `data` must be actual built-in bytes;
    `expected_sha256` a validated 64-lowercase-hex string. Hashes EXACT bytes,
    compares, returns the digest or raises. No file/path loader, JSON
    canonicalization, newline/encoding/BOM normalization, or configurable
    digest algorithm. Generic primitive; not proof of provenance."""
    if type(data) is not bytes:
        raise IdentityValidationError(
            f"bytes verifier requires exact built-in bytes, got {type(data).__name__}")
    expected = validate_sha256(expected_sha256)
    digest = hashlib.sha256(data).hexdigest()
    if digest != expected:
        raise IdentityValidationError("bytes sha256 digest does not match expected")
    return digest