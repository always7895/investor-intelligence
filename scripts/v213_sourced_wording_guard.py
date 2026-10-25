#!/usr/bin/env python3
"""Sourced-wording guard for Top20 order fields (operator rule, 2026-09-25).

A field that uses vague wording, or states a number without any source URL,
is withheld with the existing fallback text; it is never rephrased. Pure: no
I/O beyond reading the policy file, no network, clock or model call.
"""
from __future__ import annotations

import copy
import json
import re
from pathlib import Path
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parents[1]
POLICY_PATH = ROOT / "config" / "v213-sourced-wording-policy.json"
_DIGIT = re.compile(r"[0-9０-９]")


class SourcedWordingPolicyError(ValueError):
    """Fixed policy-shape error."""


def load_policy(path: Path = POLICY_PATH) -> dict[str, Any]:
    policy = json.loads(path.read_text(encoding="utf-8"))
    fields = policy.get("fields")
    if policy.get("policy_id") != "v213-sourced-wording-v1" or not isinstance(fields, dict) or not fields:
        raise SourcedWordingPolicyError("SOURCED_WORDING_POLICY_INVALID")
    for spec in fields.values():
        if not isinstance(spec, dict) or not spec.get("fallback") or not spec.get("source_urls_field"):
            raise SourcedWordingPolicyError("SOURCED_WORDING_POLICY_INVALID")
    for key in ("banned_phrases_zh", "banned_phrases_en"):
        if not isinstance(policy.get(key), list) or not all(isinstance(p, str) and p for p in policy[key]):
            raise SourcedWordingPolicyError("SOURCED_WORDING_POLICY_INVALID")
    return policy


def _english_pattern(phrase: str) -> re.Pattern[str]:
    return re.compile(r"(?<![A-Za-z])" + re.escape(phrase) + r"(?![A-Za-z])", re.IGNORECASE)


def find_violations(text: str, source_urls: list[Any], policy: Mapping[str, Any]) -> list[str]:
    """Return stable violation codes for one field value; empty means compliant."""
    codes = []
    for phrase in policy["banned_phrases_zh"]:
        if phrase in text:
            codes.append(f"VAGUE_PHRASE:{phrase}")
    for phrase in policy["banned_phrases_en"]:
        if _english_pattern(phrase).search(text):
            codes.append(f"VAGUE_PHRASE:{phrase}")
    has_source = any(isinstance(url, str) and url.startswith("https://") for url in source_urls)
    if policy.get("digits_require_source") and _DIGIT.search(text) and not has_source:
        codes.append("NUMBER_WITHOUT_SOURCE")
    return codes


def guard_order_fields(row: Mapping[str, Any], policy: Mapping[str, Any] | None = None) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Return a copy with violating order fields withheld, plus per-field findings."""
    policy = policy or load_policy()
    guarded = copy.deepcopy(dict(row))
    findings = []
    for field, spec in policy["fields"].items():
        value = guarded.get(field)
        if not isinstance(value, str) or value == spec["fallback"]:
            continue
        urls = guarded.get(spec["source_urls_field"]) or []
        codes = find_violations(value, urls if isinstance(urls, list) else [], policy)
        if codes:
            guarded[field] = spec["fallback"]
            guarded[spec["source_urls_field"]] = []
            findings.append({"field": field, "codes": codes})
    all_withheld = all(guarded.get(field) == spec["fallback"] for field, spec in policy["fields"].items())
    if findings and all_withheld and "orders_confidence" in guarded:
        guarded["orders_confidence"] = "UNAVAILABLE"
    return guarded, findings
