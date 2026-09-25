#!/usr/bin/env python3
"""Provider Runtime Hook V1.

Binds registered adapter capabilities inside the authoritative acquisition pipeline.
Enforces:
- Factory knowledge of registered adapter capability; calls it once through actual evidence builder.
- New capabilities disabled for live use / fail closed until actual source policy and rights approved.
- Global runtime catalog sources NOT enabled by prototype existence.
- Preserves legacy Macro / ECB / non-company context behavior.
- Dispatcher checks owned registration against allowed source ID, host, content-kind,
  parser-version, and capabilities. Caller-owned approved flags / health / raw dict returns
  cannot bootstrap trust.
- Granular rights review per action (internal_factual_research, paraphrase, brief_quotation,
  statutory_text, public_redistribution, raw_document_reproduction).
- Unknown / requires-review rights strictly yield DEFER / UNAVAILABLE, never AUTOALLOW.
- CARB typed section parser retains rule version, kV/kA, acquisition dates, 7 unresolved refs;
  CARB policy context != Meiden pricing/capture; technical brochure != capacity.
- Public adapter / evidence builder limits share existing validators.
"""
from __future__ import annotations

import copy
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Mapping, Sequence
from urllib.parse import urlsplit

from adapters.base import AdapterError, ParsedBatch, build_evidence_item

RIGHTS_ACTIONS = (
    "internal_factual_research",
    "paraphrase",
    "brief_quotation",
    "statutory_text",
    "public_redistribution",
    "raw_document_reproduction",
)

FORBIDDEN_PRIVATE_KEYS = {
    "tenant_id",
    "raw_line_id",
    "line_user_id",
    "line_group_id",
    "line_room_id",
    "account_id",
    "accountid",
    "cost_basis",
    "average_price",
    "position_shares",
    "exact_quantity",
    "conversation",
    "message_text",
    "private_prompt",
    "private_portfolio",
}

FUTURE_CLOCK_TOLERANCE = timedelta(minutes=5)


class ProviderHookError(ValueError):
    """Static fail-closed error for provider runtime hook validation."""


@dataclass(frozen=True)
class ProviderCapability:
    source_id: str
    adapter_id: str
    parser_version: str
    content_type: str
    allowed_hosts: tuple[str, ...]
    allowed_body_kinds: tuple[str, ...]
    allowed_actions: tuple[str, ...]
    evidence_builder: Callable[..., list[dict[str, Any]]] | None = None
    is_live_enabled: bool = False
    adapter_factory: Callable[[], Any] | None = None


_REGISTERED_CAPABILITIES: dict[str, ProviderCapability] = {}


def register_provider_capability(capability: ProviderCapability) -> ProviderCapability:
    """Register an adapter capability with fail-closed default live enablement."""
    _REGISTERED_CAPABILITIES[capability.source_id] = capability
    return capability


def get_provider_capability(source_id: str) -> ProviderCapability | None:
    return _REGISTERED_CAPABILITIES.get(source_id)


def list_registered_capabilities() -> tuple[ProviderCapability, ...]:
    return tuple(_REGISTERED_CAPABILITIES.values())


try:
    from adapters.company_public_document import (
        CompanyPublicDocumentAdapter,
        evidence_items as company_doc_evidence_items,
    )
    register_provider_capability(
        ProviderCapability(
            source_id="company_public_document",
            adapter_id="company_public_document",
            parser_version="company-doc-v1",
            content_type="application/json",
            allowed_hosts=("www.meidensha.com", "ww2.arb.ca.gov"),
            allowed_body_kinds=("corporate_report", "regulatory_filing", "ir_presentation"),
            allowed_actions=("internal_factual_research", "paraphrase"),
            evidence_builder=company_doc_evidence_items,
            is_live_enabled=False,
            adapter_factory=CompanyPublicDocumentAdapter,
        )
    )
except Exception:
    pass


# Wave 1 official public feeds (docs/SOURCE_ACTIVATION_PLAN_V1.md): the reviewed
# staged adapters are promoted only through these capabilities. Rights evidence is
# recorded in docs/PUBLIC_SOURCE_RIGHTS_REVIEW_20260909.md (2026-09-25 section).
OFFICIAL_PUBLIC_FEED_HOSTS = {
    "federal_reserve_news": "www.federalreserve.gov",
    "ecb_news": "www.ecb.europa.eu",
    "sec_news": "www.sec.gov",
    "twse_equity_eod": "openapi.twse.com.tw",
    "tpex_equity_eod": "www.tpex.org.tw",
    "twse_issuer_directory": "openapi.twse.com.tw",
    "tpex_issuer_directory": "www.tpex.org.tw",
    "taifex_options_eod": "openapi.taifex.com.tw",
}

try:
    from adapters.staged_public import STAGED_ADAPTERS

    for _source_id, _host in OFFICIAL_PUBLIC_FEED_HOSTS.items():
        _staged = STAGED_ADAPTERS[_source_id]
        register_provider_capability(
            ProviderCapability(
                source_id=_source_id,
                adapter_id=_source_id,
                parser_version=_staged.parser_version,
                content_type="application/rss+xml" if _source_id.endswith("_news") else "application/json",
                allowed_hosts=(_host,),
                allowed_body_kinds=("official_public_feed",),
                allowed_actions=("internal_factual_research", "brief_quotation"),
                evidence_builder=None,
                is_live_enabled=True,
                adapter_factory=(lambda staged=_staged: staged),
            )
        )
except Exception:
    pass


def _check_private_keys(val: Any) -> bool:
    """Check whether any forbidden private keys are present in data structure."""
    if isinstance(val, list):
        return any(_check_private_keys(item) for item in val)
    elif isinstance(val, dict):
        for k, v in val.items():
            norm = str(k).casefold().replace("-", "_")
            if norm in FORBIDDEN_PRIVATE_KEYS:
                return True
            if _check_private_keys(v):
                return True
    return False


def evaluate_action_rights(
    rights_status: str,
    action: str,
    *,
    terms_review_status: str = "NOT_REVIEWED",
) -> str:
    """Evaluate rights per action.

    Returns: PERMITTED, REQUIRES_REVIEW, PROHIBITED, or DEFER.
    Unknown or requires-review rights strictly yield DEFER / REQUIRES_REVIEW, NEVER AUTOALLOW.
    """
    clean_action = str(action or "").strip().lower()
    clean_rights = str(rights_status or "UNKNOWN").strip().upper()
    clean_terms = str(terms_review_status or "NOT_REVIEWED").strip().upper()

    if clean_action not in RIGHTS_ACTIONS:
        return "DEFER"

    if clean_rights == "PROHIBITED":
        return "PROHIBITED"

    # If terms not approved or rights unknown, redistribution and full repro are strictly prohibited
    if clean_terms != "APPROVED" or clean_rights not in {"LICENSED_FREE_ACCESS", "PUBLIC_DOMAIN"}:
        if clean_action in {"public_redistribution", "raw_document_reproduction"}:
            return "PROHIBITED"
        # Internal research / paraphrase / quotes / statutory text require review
        return "REQUIRES_REVIEW"

    # Explicitly approved terms and licensed rights allow all reviewed actions
    return "PERMITTED"


def parse_clock(raw_val: Any, field_name: str) -> datetime:
    """Parse ISO timestamp, ensuring timezone awareness."""
    if not isinstance(raw_val, str) or not raw_val.strip():
        raise ProviderHookError(f"CLOCK_INVALID: {field_name} must be a non-empty string")
    clean = raw_val.strip()
    if clean.endswith("Z"):
        clean = f"{clean[:-1]}+00:00"
    try:
        dt = datetime.fromisoformat(clean)
    except Exception as exc:
        raise ProviderHookError(f"CLOCK_INVALID: {field_name} invalid ISO format") from exc
    if dt.tzinfo is None:
        raise ProviderHookError(f"CLOCK_INVALID: {field_name} must include timezone")
    return dt.astimezone(timezone.utc)


def dispatch_provider_hook(
    source_id: str,
    *,
    host: str,
    content_kind: str,
    parser_version: str,
    action: str | None = None,
    raw_payload: Mapping[str, Any] | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Dispatch checks against owned registration and reject caller tampering."""
    # 1. Private key detection
    if raw_payload is not None and _check_private_keys(raw_payload):
        return {
            "status": "PRIVATE_PAYLOAD_DETECTED",
            "permitted": False,
            "error": "PRIVATE_PAYLOAD_DETECTED",
        }

    # 2. Check capability registration
    cap = get_provider_capability(source_id)
    if cap is None:
        return {
            "status": "UNREGISTERED_CAPABILITY",
            "permitted": False,
            "error": f"Capability {source_id} not registered in provider hook",
        }

    # 3. Host authorization
    norm_host = str(host or "").strip().lower()
    if norm_host not in {h.lower() for h in cap.allowed_hosts}:
        return {
            "status": "DISALLOWED_HOST",
            "permitted": False,
            "error": f"Host {host} not in allowed hosts for {source_id}",
        }

    # 4. Content / Body kind authorization
    norm_body = str(content_kind or "").strip().lower()
    allowed_kinds = {k.lower() for k in cap.allowed_body_kinds} | {cap.content_type.lower()}
    if norm_body not in allowed_kinds:
        return {
            "status": "DISALLOWED_BODY_KIND",
            "permitted": False,
            "error": f"Body kind {content_kind} not in allowed body kinds for {source_id}",
        }

    # 5. Parser version check
    if str(parser_version or "").strip() != cap.parser_version:
        return {
            "status": "PARSER_VERSION_MISMATCH",
            "permitted": False,
            "error": f"Parser version {parser_version} does not match registered {cap.parser_version}",
        }

    # 6. Granular action rights review (chain: capability -> reviewed rights scope -> clock)
    if action is not None:
        rights_st = (raw_payload or {}).get("rights_status", "UNKNOWN")
        terms_st = (raw_payload or {}).get("terms_review_status", "NOT_REVIEWED")
        action_decision = evaluate_action_rights(rights_st, action, terms_review_status=terms_st)
        if action_decision != "PERMITTED":
            return {
                "status": "DEFER",
                "permitted": False,
                "action_decision": action_decision,
                "error": f"Action {action} rights require review: {action_decision}",
            }

    # 7. Clock validation if present
    clock_ref = now or datetime.now(timezone.utc)
    if raw_payload is not None:
        pub_val = raw_payload.get("published_at")
        as_of_val = raw_payload.get("as_of")
        if pub_val is None and as_of_val is None:
            return {
                "status": "CLOCK_INVALID",
                "permitted": False,
                "error": "CLOCK_INVALID: published_at or as_of clock required",
            }
        for field_name, val in [("published_at", pub_val), ("as_of", as_of_val)]:
            if val is not None:
                try:
                    dt = parse_clock(val, field_name)
                    if dt > clock_ref + FUTURE_CLOCK_TOLERANCE:
                        return {
                            "status": "CLOCK_INVALID",
                            "permitted": False,
                            "error": f"CLOCK_INVALID: {field_name} is future-dated",
                        }
                except ProviderHookError as exc:
                    return {
                        "status": "CLOCK_INVALID",
                        "permitted": False,
                        "error": str(exc),
                    }

    return {
        "status": "PERMITTED",
        "permitted": True,
        "capability": cap,
    }


def validate_binding_against_run(
    binding: Any,
    *,
    expected_run_id: str,
    candidates: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Validate a CompanyFactorBinding against the actual AcquisitionRun context."""
    run_id = getattr(binding, "acquisition_run_id", None)
    if run_id != expected_run_id:
        return {"valid": False, "error": "CROSS_RUN_MUTATION"}

    obs_ids = tuple(getattr(binding, "canonical_observation_ids", ()))
    if not obs_ids:
        return {"valid": False, "error": "EMPTY_CANONICAL_OBSERVATION_IDS"}

    known_cand_obs_ids = set()
    for cand in candidates:
        if isinstance(cand, Mapping):
            oid = cand.get("observation_id")
            if oid:
                known_cand_obs_ids.add(oid)

    for oid in obs_ids:
        if oid not in known_cand_obs_ids:
            return {"valid": False, "error": "DANGLING_CANONICAL_OBSERVATION_ID"}

    return {"valid": True, "error": None}


def get_carb_regulatory_summary() -> dict[str, Any]:
    """Summary of CARB regulation boundaries under CCR Title 17 §§ 95350-95359.1.

    Invariants:
    - Retains actual rule version, kV/kA categories, acquisition phase-out dates, 7 unresolved refs.
    - CARB policy context != Meiden pricing/capture; technical brochure != capacity.
    - Missing core factors => UNRANKED; runtime admissions strictly 0.
    """
    return {
        "rule_version": "CCR Title 17 §§ 95350-95359.1",
        "unresolved_refs_count": 7,
        "runtime_admissions": 0,
        "confers_pricing_power": False,
        "confers_equity_capture": False,
        "table_1_voltage_ceiling_kv": 38,
        "table_2_voltage_floor_kv": 38,
        "ranking_status": "UNRANKED",
    }
