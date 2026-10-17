#!/usr/bin/env python3
"""Strict loader for the phrase-zh-policy-v1 wording policy (inert library).

Implements only the "Digest-bound phrase wording policy" section of
docs/PHRASE_ZH_QUALIFIED_PRESENTATION_CONTRACT.md. It grants nothing: a
successful load is a format fact about one pinned file, never approval of a
phrase, a translator, a surface or a publication. Nothing in scripts/ or cloud/
calls it, no policy file exists for it, and the production trust root that
supplies the pin is BLOCKED_IMPLEMENTATION_TRUST_ROOT. The pin argument is an
injected test dependency; production must not take it from the policy itself,
the environment, a download or a cache sidecar.

No import side effects: standard library only, no I/O, clock or network at import.
Every failure returns status POLICY_UNAVAILABLE with one fixed reason code; no
default or empty ban set is ever produced.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCHEMA = "phrase-zh-policy-v1"
STATUS_OK = "POLICY_OK"
STATUS_UNAVAILABLE = "POLICY_UNAVAILABLE"
MAX_POLICY_BYTES = 65_536
MAX_DEPTH = 16
MIN_PHRASE_CODEPOINTS = 4
MAX_PHRASE_CODEPOINTS = 40
MAX_PHRASE_UTF16_UNITS = 80
MAX_BANS = 256
MAX_BAN_CODEPOINTS = 100
MAX_BAN_UTF8_BYTES = 400
SURFACE_IDS = ("BOTTLENECK_V3_DETAIL_BUSINESS", "POTENTIAL_REPORT_BUSINESS", "TOP20_DEEP_BUSINESS")
V1_ALLOWED_SURFACES = ("POTENTIAL_REPORT_BUSINESS",)
SEMANTIC_RULES = ("ENTITY_SCOPE", "EXACT_QUANTITIES_UNITS", "NEGATION_MODALITY", "NO_MATERIAL_OMISSION",
                  "NO_UNSUPPORTED_CLAIMS", "PERIOD_BASIS", "TRADITIONAL_CHINESE")
PROVENANCE_SCHEMA = "phrase-zh-generation-v1"
REVIEW_SCHEMA = "phrase-zh-review-v1"

FORBIDDEN_CONTROLS = tuple(sorted(
    {*range(0x0000, 0x0020), 0x007C, *range(0x007F, 0x00A0), *range(0x200B, 0x2010),
     *range(0x2028, 0x202F), *range(0x2060, 0x2070), 0xFEFF, 0xFF5C}))
_FORBIDDEN_SET = frozenset(FORBIDDEN_CONTROLS)
_WHITESPACE = frozenset({*range(0x0009, 0x000E), 0x0085, 0x00A0, 0x1680, *range(0x2000, 0x200B),
                         0x2028, 0x2029, 0x202F, 0x205F, 0x3000})
REQUIRED_KEYS = frozenset({
    "schema", "policy_id", "revision", "effective_from", "expires_at", "locale", "allowed_surfaces",
    "min_phrase_codepoints", "max_phrase_codepoints", "max_phrase_utf16_units", "banned_phrases_zh",
    "banned_phrases_en", "forbidden_controls", "semantic_rules", "required_provenance_schema",
    "required_review_schema", "policy_sha256"})

REASONS = frozenset({
    "PIN_INVALID", "DECISION_TIME_INVALID", "FILE_ABSENT", "READ_ERROR", "OVERSIZE", "DIGEST_MISMATCH",
    "MALFORMED", "DUPLICATE_KEY", "NONFINITE", "FLOAT_NOT_ALLOWED", "DEPTH", "SCALAR_INVALID", "KEY_SET",
    "TYPE", "VALUE", "ORDER", "CONTROLS", "SEMANTIC_RULES", "WHITESPACE", "EXPIRED", "NOT_YET_EFFECTIVE",
    "INTERNAL_DIGEST"})

_ID64 = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}")
_ID32 = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,31}")
_HEX64 = re.compile(r"[0-9a-f]{64}")
_TIME = re.compile(r"([0-9]{4})-([0-9]{2})-([0-9]{2})T([0-9]{2}):([0-9]{2}):([0-9]{2})Z")


class _Refuse(Exception):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class PhrasePolicy:
    """Format-validated policy facts. Holding one grants no approval of anything."""

    policy_id: str
    revision: str
    effective_from: str
    expires_at: str
    allowed_surfaces: tuple[str, ...]
    banned_phrases_zh: tuple[str, ...]
    banned_phrases_en: tuple[str, ...]
    policy_file_sha256: str
    policy_sha256: str


@dataclass(frozen=True)
class LoadResult:
    status: str
    reason: str | None
    policy: PhrasePolicy | None


def _unavailable(reason: str) -> LoadResult:
    return LoadResult(STATUS_UNAVAILABLE, reason, None)


def canonical_policy_sha256(policy: dict[str, Any]) -> str:
    """SHA-256 of the sorted-key compact UTF-8 JSON of the policy without its own digest field."""
    body = {key: value for key, value in policy.items() if key != "policy_sha256"}
    text = json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def load(policy_path: Any, expected_file_sha256: Any, *, decision_time: Any) -> LoadResult:
    """Load one pinned policy file; any deviation returns POLICY_UNAVAILABLE with a fixed reason."""
    try:
        return _load(policy_path, expected_file_sha256, decision_time)
    except _Refuse as refusal:
        return _unavailable(refusal.reason)
    except RecursionError:
        return _unavailable("DEPTH")
    except Exception:  # noqa: BLE001 - nothing is ever allowed to escape as success
        return _unavailable("MALFORMED")


def _load(policy_path: Any, expected: Any, decision_time: Any) -> LoadResult:
    if not isinstance(expected, str) or not _HEX64.fullmatch(expected):
        raise _Refuse("PIN_INVALID")
    if not isinstance(decision_time, datetime) or decision_time.tzinfo is None or decision_time.utcoffset() is None:
        raise _Refuse("DECISION_TIME_INVALID")
    now = decision_time.astimezone(timezone.utc).replace(tzinfo=None)
    raw = _read_bounded(policy_path)
    if not hmac.compare_digest(hashlib.sha256(raw).hexdigest(), expected):  # pin is checked on the held bytes BEFORE parsing
        raise _Refuse("DIGEST_MISMATCH")
    text = _decode(raw)
    document = _parse(text)
    _walk(document, 1)
    policy = _validate(document, now)
    return LoadResult(STATUS_OK, None, PhrasePolicy(
        policy_id=policy["policy_id"], revision=policy["revision"], effective_from=policy["effective_from"],
        expires_at=policy["expires_at"], allowed_surfaces=tuple(policy["allowed_surfaces"]),
        banned_phrases_zh=tuple(policy["banned_phrases_zh"]), banned_phrases_en=tuple(policy["banned_phrases_en"]),
        policy_file_sha256=expected, policy_sha256=policy["policy_sha256"]))


def _read_bounded(policy_path: Any) -> bytes:
    try:
        with Path(policy_path).open("rb") as handle:
            raw = handle.read(MAX_POLICY_BYTES + 1)
    except FileNotFoundError:
        raise _Refuse("FILE_ABSENT") from None
    except (OSError, TypeError, ValueError):
        raise _Refuse("READ_ERROR") from None
    if len(raw) > MAX_POLICY_BYTES:
        raise _Refuse("OVERSIZE")
    return raw


def _decode(raw: bytes) -> str:
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        raise _Refuse("MALFORMED") from None
    if text.startswith("﻿"):
        raise _Refuse("MALFORMED")
    return text


def _pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise _Refuse("DUPLICATE_KEY")
        result[key] = value
    return result


def _refuse_constant(_name: str) -> Any:
    raise _Refuse("NONFINITE")


def _refuse_float(_text: str) -> Any:
    raise _Refuse("FLOAT_NOT_ALLOWED")


def _parse(text: str) -> Any:
    try:
        return json.loads(text, object_pairs_hook=_pairs, parse_constant=_refuse_constant, parse_float=_refuse_float)
    except _Refuse:
        raise
    except RecursionError:
        raise _Refuse("DEPTH") from None
    except ValueError:
        raise _Refuse("MALFORMED") from None


def _scalar_ok(text: str) -> bool:
    return not any(0xD800 <= ord(char) <= 0xDFFF for char in text)


def _walk(value: Any, depth: int) -> None:
    """Refuse container nesting deeper than MAX_DEPTH and any lone surrogate in a key or string."""
    if isinstance(value, dict):
        if depth > MAX_DEPTH:
            raise _Refuse("DEPTH")
        for key, item in value.items():
            if not _scalar_ok(key):
                raise _Refuse("SCALAR_INVALID")
            _walk(item, depth + 1)
    elif isinstance(value, list):
        if depth > MAX_DEPTH:
            raise _Refuse("DEPTH")
        for item in value:
            _walk(item, depth + 1)
    elif isinstance(value, str):
        if not _scalar_ok(value):
            raise _Refuse("SCALAR_INVALID")


def _is_int(value: Any) -> bool:
    return type(value) is int  # bool is never an integer here


def _literal(policy: dict[str, Any], key: str, expected: Any) -> None:
    value = policy[key]
    if type(value) is not type(expected):
        raise _Refuse("TYPE")
    if value != expected:
        raise _Refuse("VALUE")


def _ident(policy: dict[str, Any], key: str, pattern: re.Pattern[str]) -> None:
    value = policy[key]
    if not isinstance(value, str):
        raise _Refuse("TYPE")
    if not pattern.fullmatch(value):
        raise _Refuse("VALUE")


def _time(policy: dict[str, Any], key: str) -> datetime:
    value = policy[key]
    if not isinstance(value, str):
        raise _Refuse("TYPE")
    match = _TIME.fullmatch(value)
    if not match:
        raise _Refuse("VALUE")
    year, month, day, hour, minute, second = (int(part) for part in match.groups())
    if not 2000 <= year <= 2099:
        raise _Refuse("VALUE")
    try:
        return datetime(year, month, day, hour, minute, second)
    except ValueError:
        raise _Refuse("VALUE") from None


def _string_array(value: Any) -> list[str]:
    if not isinstance(value, list):
        raise _Refuse("TYPE")
    if not all(isinstance(item, str) for item in value):
        raise _Refuse("TYPE")
    return value


def _strictly_ascending(items: list[Any]) -> bool:
    # Python compares str by Unicode scalar value, i.e. code-point order, never UTF-16 code units.
    return all(left < right for left, right in zip(items, items[1:]))


def _ban_list(value: Any) -> None:
    items = _string_array(value)
    if not 1 <= len(items) <= MAX_BANS:
        raise _Refuse("VALUE")
    for item in items:
        if not 1 <= len(item) <= MAX_BAN_CODEPOINTS or len(item.encode("utf-8")) > MAX_BAN_UTF8_BYTES:
            raise _Refuse("VALUE")
        codepoints = {ord(char) for char in item}
        if codepoints & _FORBIDDEN_SET:
            raise _Refuse("CONTROLS")
        if (codepoints & _WHITESPACE) or item != item.strip(" ") or "  " in item:
            raise _Refuse("WHITESPACE")
    if not _strictly_ascending(items):
        raise _Refuse("ORDER")


def _validate(policy: Any, now: datetime) -> dict[str, Any]:
    if not isinstance(policy, dict):
        raise _Refuse("TYPE")
    if set(policy) != REQUIRED_KEYS:
        raise _Refuse("KEY_SET")
    _literal(policy, "schema", SCHEMA)
    _ident(policy, "policy_id", _ID64)
    _ident(policy, "revision", _ID32)
    effective_from = _time(policy, "effective_from")
    expires_at = _time(policy, "expires_at")
    _literal(policy, "locale", "zh-TW")
    surfaces = _string_array(policy["allowed_surfaces"])
    if not 1 <= len(surfaces) <= 3 or not all(item in SURFACE_IDS for item in surfaces):
        raise _Refuse("VALUE")
    if not _strictly_ascending(surfaces):
        raise _Refuse("ORDER")
    if tuple(surfaces) != V1_ALLOWED_SURFACES:
        raise _Refuse("VALUE")
    for key, expected in (("min_phrase_codepoints", MIN_PHRASE_CODEPOINTS),
                          ("max_phrase_codepoints", MAX_PHRASE_CODEPOINTS),
                          ("max_phrase_utf16_units", MAX_PHRASE_UTF16_UNITS)):
        if not _is_int(policy[key]):
            raise _Refuse("TYPE")
        if policy[key] != expected:
            raise _Refuse("VALUE")
    _ban_list(policy["banned_phrases_zh"])
    _ban_list(policy["banned_phrases_en"])
    controls = policy["forbidden_controls"]
    if not isinstance(controls, list) or not all(_is_int(item) for item in controls):
        raise _Refuse("TYPE")
    if not _strictly_ascending(controls):
        raise _Refuse("ORDER")
    if tuple(controls) != FORBIDDEN_CONTROLS:
        raise _Refuse("CONTROLS")
    rules = _string_array(policy["semantic_rules"])
    if not _strictly_ascending(rules):
        raise _Refuse("ORDER")
    if tuple(rules) != SEMANTIC_RULES:
        raise _Refuse("SEMANTIC_RULES")
    _literal(policy, "required_provenance_schema", PROVENANCE_SCHEMA)
    _literal(policy, "required_review_schema", REVIEW_SCHEMA)
    digest = policy["policy_sha256"]
    if not isinstance(digest, str):
        raise _Refuse("TYPE")
    if not _HEX64.fullmatch(digest):
        raise _Refuse("VALUE")
    if effective_from >= expires_at:
        raise _Refuse("VALUE")
    if now < effective_from:
        raise _Refuse("NOT_YET_EFFECTIVE")
    if now >= expires_at:
        raise _Refuse("EXPIRED")
    if not hmac.compare_digest(canonical_policy_sha256(policy), digest):
        raise _Refuse("INTERNAL_DIGEST")
    return policy
