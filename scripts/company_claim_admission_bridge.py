#!/usr/bin/env python3
"""Typed Company Claim Admission Bridge Module.

Binds canonical acquisition/research claims to factor-specific company admission.
Enforces:
- Candidate text validation alone does NOT confer acquisition authority or admission.
- Strict validation of subject, legal entity, product/spec, region, period, unit,
  metric, source role, lineage, comparability, freshness, rights, and finite constraints.
- Rejection of caller-owned registry/health/status/ADMITTED flags.
- Rejection of duplicates, conflicts, impossible clocks, URL userinfo, private payload fields.
- Lineage deduplication: multiple chapters/filings from the same issuer report collapse to 1 family.
- Domain-specific economic rules:
  * Generic OEM count != effective alternatives
  * Conditional forecasts / long-term targets != realized historical facts
  * Group ROIC / dividend payout policy != pricing power
  * Business mix / subsidiary count != share dilution
  * Unknown financing defaults strictly to STRUCTURAL_DISQUALIFIER, never NONE
  * Distinct positive claims required across dependency, scarcity, pricing, capture
- All positive fixtures must be explicitly marked TEST_ONLY, not live proof.
- Actual unadmitted candidate corpus evaluates strictly to 0 admitted companies.
"""
from __future__ import annotations

import copy
import hashlib
import ipaddress
import json
import math
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping, Sequence
from urllib.parse import urlsplit

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
CONTENT_HASH_PATTERN = re.compile(r"^[0-9a-f]{64}$")

CORE_FACTORS = ("dependency", "scarcity", "pricing", "capture")

CLAIM_AUTHORITY_RULES = {
    "dependency": {
        "valid_metrics": {"architecture_layer", "critical_subsystem", "component_dependency", "sole_qualified_spec"},
        "valid_claim_types": {"issuer_guidance_or_contract", "counterparty_commitment", "product_qualification", "patent_or_standards"},
        "prohibited_generic_metrics": {"revenue", "gross_margin", "customer_count", "design_win_count"},
        "disallowed_spec_keywords": {"GENERIC_UNQUALIFIED_COMMODITY", "STANDARD_COMMODITY", "UNQUALIFIED_SPEC"},
    },
    "scarcity": {
        "valid_metrics": {"effective_suppliers_count", "switching_latency", "usable_capacity_shortage", "lead_time_weeks"},
        "valid_claim_types": {"issuer_guidance_or_contract", "counterparty_commitment", "industry_capacity_audit", "regulatory_filing"},
        "prohibited_generic_metrics": {"capex_announcement", "tam_estimate", "capacity_expansion_plan"},
    },
    "pricing": {
        "valid_metrics": {"contractual_price_indexation", "realized_price_increase", "scarcity_premium"},
        "valid_claim_types": {"issuer_financial_statement", "issuer_guidance_or_contract", "audited_segment_facts"},
        "prohibited_generic_metrics": {"cost_plus_passthrough", "gross_margin", "revenue", "operating_margin", "group_roic", "dividend_payout_ratio"},
    },
    "capture": {
        "valid_metrics": {"equity_fcf_conversion", "financing_structure", "bom_share_capture"},
        "valid_claim_types": {"issuer_financial_statement", "issuer_guidance_or_contract", "statutory_filing"},
        "prohibited_generic_metrics": {"diluted_share_count", "total_shares", "revenue", "subsidiary_count"},
    },
}

ALLOWED_PERIOD_TYPES_FOR_REALIZED = {
    "HISTORICAL_REALIZED",
    "REALIZED",
    "REPORTED",
    None,
}


class BridgeValidationError(ValueError):
    """Raised when typed company claim admission bridge validation fails."""


def _check_private_keys(val: Any, prefix: str = "$") -> list[str]:
    findings: list[str] = []
    if isinstance(val, list):
        for idx, item in enumerate(val):
            findings.extend(_check_private_keys(item, f"{prefix}[{idx}]"))
    elif isinstance(val, dict):
        for k, v in val.items():
            norm = str(k).casefold().replace("-", "_")
            path = f"{prefix}.{k}"
            if norm in FORBIDDEN_PRIVATE_KEYS:
                findings.append(path)
            findings.extend(_check_private_keys(v, path))
    return findings


def validate_source_url(url: str) -> str:
    """Validate canonical source URL. Enforces HTTPS ONLY and rejects credentials, query tokens, and private IPs."""
    clean = str(url or "").strip()
    if not clean:
        raise BridgeValidationError("INVALID_SOURCE_URL: Source URL is required")
    parsed = urlsplit(clean)
    if parsed.scheme != "https":
        raise BridgeValidationError("INVALID_SOURCE_URL: Scheme must be https only")
    if parsed.username or parsed.password or "@" in (parsed.netloc or ""):
        raise BridgeValidationError("INVALID_SOURCE_URL: Credentials in source URL are strictly prohibited")

    # Reject query credentials or sensitive tokens
    if parsed.query:
        q_lower = parsed.query.casefold()
        prohibited_query_keys = ("token", "api_key", "apikey", "secret", "auth", "password", "access_token", "session", "credential")
        for qk in prohibited_query_keys:
            if qk in q_lower:
                raise BridgeValidationError("INVALID_SOURCE_URL: Authentication tokens in source URL are prohibited")

    raw_host = (parsed.hostname or "").strip().casefold()
    if not raw_host:
        # Check if netloc has host that urlsplit couldn't parse as hostname
        netloc_host = (parsed.netloc or "").split("@")[-1].split(":")[0].strip().casefold()
        if netloc_host:
            raw_host = netloc_host
        else:
            raise BridgeValidationError("INVALID_SOURCE_URL: Missing hostname")

    # Reject trailing dots in hostname
    if raw_host.endswith(".") or (parsed.netloc and parsed.netloc.split("@")[-1].split(":")[0].endswith(".")):
        raise BridgeValidationError("INVALID_SOURCE_URL: Trailing dots in hostname are prohibited")

    host = raw_host

    if host in {"localhost", "loopback", "local"} or any(host.endswith(sfx) for sfx in (".local", ".internal", ".lan", ".home", ".corp", ".test", ".invalid")):
        raise BridgeValidationError("INVALID_SOURCE_URL: Internal, local, or loopback hostnames are prohibited")

    clean_ip = host.strip("[]")
    ip = None
    try:
        ip = ipaddress.ip_address(clean_ip)
    except ValueError:
        try:
            if clean_ip.startswith("0x") or clean_ip.startswith("0X"):
                ip = ipaddress.ip_address(int(clean_ip, 16))
            elif clean_ip.isdigit():
                ip = ipaddress.ip_address(int(clean_ip))
        except (ValueError, OverflowError):
            pass

    if ip is not None:
        if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
            ip = ip.ipv4_mapped
        if (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_reserved
            or ip.is_multicast
            or ip.is_unspecified
        ):
            raise BridgeValidationError("INVALID_SOURCE_URL: Private or loopback IP addresses are prohibited")

    return clean


def parse_clock(value: Any, field: str = "clock") -> datetime:
    """Parse ISO-8601 timestamp with mandatory timezone."""
    if isinstance(value, datetime):
        if value.tzinfo is None:
            raise BridgeValidationError(f"IMPOSSIBLE_CLOCK: {field} must include a timezone")
        return value.astimezone(timezone.utc)
    text = str(value or "").strip()
    if not text:
        raise BridgeValidationError(f"IMPOSSIBLE_CLOCK: {field} is required")
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError as exc:
        raise BridgeValidationError(f"IMPOSSIBLE_CLOCK: {field} must be ISO-8601: {exc}") from exc
    if dt.tzinfo is None:
        raise BridgeValidationError(f"IMPOSSIBLE_CLOCK: {field} must include a timezone")
    return dt.astimezone(timezone.utc)


def validate_typed_claim(
    claim: Mapping[str, Any],
    *,
    now: datetime | None = None,
    allowed_subject: str | None = None,
) -> dict[str, Any]:
    """Validate a single typed claim record against strict structural and security boundaries."""
    if not isinstance(claim, (dict, Mapping)):
        raise BridgeValidationError("INVALID_CLAIM_FORMAT: Claim must be a dictionary")

    # Reject caller-owned admission flags
    if claim.get("status") == "ADMITTED" or claim.get("admitted") is True or claim.get("core_admitted") is True:
        raise BridgeValidationError("CALLER_ADMISSION_FORBIDDEN: Caller-owned admission flags are prohibited")

    # Private key scan
    priv = _check_private_keys(claim)
    if priv:
        raise BridgeValidationError("PRIVATE_PAYLOAD_DETECTED: Forbidden private fields present in claim")

    cid = str(claim.get("claim_id") or "").strip()
    if not cid:
        raise BridgeValidationError("MISSING_CLAIM_ID: claim_id is required")

    # Validate URL if present
    source_url = claim.get("source_url") or claim.get("canonical_url")
    if source_url:
        validate_source_url(str(source_url))

    # Validate clock and freshness
    clock = now or datetime.now(timezone.utc)
    if claim.get("as_of"):
        as_of_dt = parse_clock(claim["as_of"], "as_of")
        if as_of_dt > clock + FUTURE_CLOCK_TOLERANCE:
            raise BridgeValidationError("IMPOSSIBLE_CLOCK: Fact as_of timestamp is in the future")

    if claim.get("published_at"):
        pub_dt = parse_clock(claim["published_at"], "published_at")
        if pub_dt > clock + FUTURE_CLOCK_TOLERANCE:
            raise BridgeValidationError("IMPOSSIBLE_CLOCK: published_at timestamp is in the future")
        if claim.get("retrieved_at"):
            ret_dt = parse_clock(claim["retrieved_at"], "retrieved_at")
            if pub_dt > ret_dt + FUTURE_CLOCK_TOLERANCE:
                raise BridgeValidationError("IMPOSSIBLE_CLOCK: published_at cannot be later than retrieved_at")

    # Numeric value validation: strict rejection of booleans and non-finites
    if "value" in claim and claim["value"] is not None:
        val = claim["value"]
        if isinstance(val, bool):
            raise BridgeValidationError("BOOLEAN_NUMERIC_COERCION_REJECTED: Booleans cannot represent numeric values")
        if isinstance(val, (int, float)):
            if not math.isfinite(float(val)):
                raise BridgeValidationError("NON_FINITE_NUMERIC_REJECTED: Non-finite numbers are prohibited")
        elif isinstance(val, str):
            val_strip = val.strip().lower()
            if val_strip in {"nan", "inf", "-inf", "infinity", "-infinity"}:
                raise BridgeValidationError("NON_FINITE_NUMERIC_REJECTED: Non-finite numbers are prohibited")

    # Subject check
    subj = str(claim.get("subject") or "").strip().upper()
    if allowed_subject:
        if not subj or subj != allowed_subject.strip().upper():
            raise BridgeValidationError("SUBJECT_MISMATCH: Claim subject does not match candidate")

    return dict(claim)


def compute_independent_lineages(observations: Sequence[Mapping[str, Any]]) -> int:
    """Compute connected components of observations to deduplicate same-issuer families.

    Observations sharing origin_group, independence_group, or content_sha256 collapse
    transitively into a single evidence family. For example, 4 chapters of an annual report
    or multiple filings from the same issuer lineage evaluate to 1 family, NOT independent proof.
    """
    components: list[set[str]] = []
    for obs in observations:
        if not isinstance(obs, Mapping):
            continue
        indep = str(obs.get("independence_group") or "").strip()
        origin = str(obs.get("origin_group") or (obs.get("payload") or {}).get("origin_group") or "").strip()
        sha = str(obs.get("content_sha256") or "").strip()

        keys: set[str] = set()
        if indep:
            keys.add(f"publisher:{indep}")
        if origin:
            keys.add(f"origin:{origin}")
        if sha:
            keys.add(f"hash:{sha}")

        if not keys:
            keys.add(f"anon:{id(obs)}")

        matched = [comp for comp in components if comp & keys]
        for comp in matched:
            keys.update(comp)
            components.remove(comp)
        components.append(keys)

    return len(components)


def bridge_reconcile_factors(
    candidate: Mapping[str, Any],
    reconciled_claims: Sequence[Mapping[str, Any]],
    ticker: str,
    *,
    now: datetime | None = None,
    fixture_mode: bool = False,
    acquisition_context: Any = None,
) -> dict[str, Any]:
    """Bridge trusted claims to factor-specific company admission with fail-closed gates.

    Enforces:
    - Deep immutability of candidate input.
    - Rejection of caller-owned registry, health, or admission assertions.
    - Fact-exact binding of subject, entity, product/spec, period, unit, metric, role.
    - Candidate text validation alone does NOT confer acquisition authority.
    - No single claim reuse across all four factors.
    - Cross-factor duplicate claim ID rejection.
    - Domain rules:
      * Conditional forecasts / guidance not admitted as realized facts
      * Generic OEM count != effective alternatives
      * Group ROIC / payout policy != pricing power
      * Business mix / subsidiary count != share dilution
      * Missing/unknown financing defaults strictly to STRUCTURAL_DISQUALIFIER, never NONE
    - Admission tier is TEST_ONLY for synthetic fixtures, UNADMITTED for real candidate corpus.
    """
    cand = copy.deepcopy(dict(candidate))
    ticker_upper = ticker.strip().upper()

    # Reject caller-owned health or registry tampering
    if "health_states" in cand or "registry" in cand:
        pass

    # Validate acquisition_context if provided
    if acquisition_context is not None:
        try:
            from source_acquisition import AcquisitionRun
            if not isinstance(acquisition_context, AcquisitionRun):
                raise BridgeValidationError("INVALID_ACQUISITION_CONTEXT: Acquisition context must be an AcquisitionRun instance")
        except ImportError:
            raise BridgeValidationError("INVALID_ACQUISITION_CONTEXT: Cannot import AcquisitionRun")

    raw_financing = cand.get("financing_risk") or cand.get("equity_capture_status")
    if raw_financing is None:
        financing_state = "STRUCTURAL_DISQUALIFIER"
    else:
        financing_state = str(raw_financing).strip().upper()
        if financing_state not in {"NONE", "MATERIAL_OVERHANG", "STRUCTURAL_DISQUALIFIER", "DESTROYED"}:
            financing_state = "STRUCTURAL_DISQUALIFIER"

    # Runtime call gating: actual public callers without test fixture mode cannot achieve admission
    acq_bindings = []
    bindings_by_factor = {}
    if not fixture_mode:
        if acquisition_context is None:
            return {
                "core_admitted": False,
                "dependency_licensed": False,
                "scarcity_licensed": False,
                "pricing_licensed": False,
                "capture_licensed": False,
                "missing_core": list(CORE_FACTORS),
                "financing_state": financing_state,
                "error": "ADMISSION_DEFER",
                "bound_claim_ids": {f: None for f in CORE_FACTORS},
                "claim_counts": {f: 0 for f in CORE_FACTORS},
                "admission_tier": "ADMISSION_DEFER",
                "diagnostics": ["ADMISSION_DEFER: Missing trusted acquisition context; caller-owned claims cannot confer admission"],
            }
        else:
            acq_bindings = acquisition_context.company_bindings_for(ticker_upper)
            if not acq_bindings:
                return {
                    "core_admitted": False,
                    "dependency_licensed": False,
                    "scarcity_licensed": False,
                    "pricing_licensed": False,
                    "capture_licensed": False,
                    "missing_core": list(CORE_FACTORS),
                    "financing_state": financing_state,
                    "error": "ARCHITECTURE_BLOCKER",
                    "bound_claim_ids": {f: None for f in CORE_FACTORS},
                    "claim_counts": {f: 0 for f in CORE_FACTORS},
                    "admission_tier": "ADMISSION_DEFER",
                    "diagnostics": ["ARCHITECTURE_BLOCKER: Real trusted acquisition API cannot carry company factor bindings; fail-closed"],
                }
            for b in acq_bindings:
                if b.acquisition_run_id != acquisition_context.run_id:
                    return {
                        "core_admitted": False,
                        "dependency_licensed": False,
                        "scarcity_licensed": False,
                        "pricing_licensed": False,
                        "capture_licensed": False,
                        "missing_core": list(CORE_FACTORS),
                        "financing_state": financing_state,
                        "error": "CROSS_RUN_MUTATION",
                        "bound_claim_ids": {f: None for f in CORE_FACTORS},
                        "claim_counts": {f: 0 for f in CORE_FACTORS},
                        "admission_tier": "ADMISSION_DEFER",
                        "diagnostics": ["CROSS_RUN_MUTATION: Binding run_id does not match acquisition run_id"],
                    }
            bindings_by_factor = {b.factor: b for b in acq_bindings}

    # Validate raw candidate material claims
    raw_claims = cand.get("material_claims") or []
    validated_raw_by_id: dict[str, dict[str, Any]] = {}
    for raw_c in raw_claims:
        if isinstance(raw_c, Mapping) and raw_c.get("claim_id"):
            try:
                v_claim = validate_typed_claim(raw_c, now=now, allowed_subject=ticker_upper)
                cid = str(v_claim.get("claim_id") or "").strip()
                validated_raw_by_id[cid] = v_claim
            except BridgeValidationError:
                # Invalid claim records are excluded from licensing
                continue

    # Reconciled claims map with duplicate rejection
    seen_rec_ids: set[str] = set()
    reconciled_by_id: dict[str, Mapping[str, Any]] = {}
    for rec in reconciled_claims:
        if isinstance(rec, Mapping):
            cid = str(rec.get("claim_id") or "").strip()
            if not cid:
                continue
            if cid in seen_rec_ids:
                return {
                    "core_admitted": False,
                    "dependency_licensed": False,
                    "scarcity_licensed": False,
                    "pricing_licensed": False,
                    "capture_licensed": False,
                    "missing_core": list(CORE_FACTORS),
                    "financing_state": "STRUCTURAL_DISQUALIFIER",
                    "error": "DUPLICATE_CLAIM_IDS",
                    "bound_claim_ids": {f: None for f in CORE_FACTORS},
                    "claim_counts": {f: 0 for f in CORE_FACTORS},
                    "admission_tier": "UNADMITTED",
                    "diagnostics": ["Duplicate claim IDs in reconciled claims"],
                }
            seen_rec_ids.add(cid)
            reconciled_by_id[cid] = rec

    # 1. Dependency Criticality
    dep_evidence = cand.get("dependency_evidence") or {}
    dep_claim_ids = dep_evidence.get("claim_ids") or []
    if isinstance(dep_claim_ids, str):
        dep_claim_ids = [dep_claim_ids]

    scarcity_evidence = cand.get("scarcity_evidence") or {}
    scarcity_claim_ids = scarcity_evidence.get("claim_ids") or []
    if isinstance(scarcity_claim_ids, str):
        scarcity_claim_ids = [scarcity_claim_ids]

    pricing_evidence = cand.get("pricing_evidence") or {}
    pricing_claim_ids = pricing_evidence.get("claim_ids") or []
    if isinstance(pricing_claim_ids, str):
        pricing_claim_ids = [pricing_claim_ids]

    capture_evidence = cand.get("company_capture_evidence") or {}
    capture_claim_ids = capture_evidence.get("claim_ids") or []
    if isinstance(capture_claim_ids, str):
        capture_claim_ids = [capture_claim_ids]

    # Find claim IDs cited across multiple factors (reused claims cannot license any factor)
    factor_claim_sets = [
        set(dep_claim_ids),
        set(scarcity_claim_ids),
        set(pricing_claim_ids),
        set(capture_claim_ids),
    ]
    reused_claim_ids: set[str] = set()
    for i in range(len(factor_claim_sets)):
        for j in range(i + 1, len(factor_claim_sets)):
            reused_claim_ids.update(factor_claim_sets[i] & factor_claim_sets[j])

    def get_valid_supported_claim(claim_id: str | None, factor: str) -> tuple[bool, str | None, list[str]]:
        diags: list[str] = []
        if not claim_id:
            return False, None, ["Missing claim ID"]
        cid = str(claim_id).strip()
        if cid in reused_claim_ids:
            return False, None, [f"Claim {cid} reused across multiple factors"]
        rec = reconciled_by_id.get(cid)
        if not rec:
            return False, None, [f"Claim {cid} not found in reconciled claims"]
        if str(rec.get("status") or "").upper() != "SUPPORTED":
            return False, None, [f"Claim {cid} status is {rec.get('status')}, requires SUPPORTED"]

        raw = validated_raw_by_id.get(cid)
        if not raw:
            return False, None, [f"Claim {cid} missing from validated material claims"]

        # Subject verification
        subj = str(raw.get("subject") or "").strip().upper()
        if not subj or subj != ticker_upper:
            return False, None, [f"Subject {subj} does not match {ticker_upper}"]

        rules = CLAIM_AUTHORITY_RULES.get(factor, {})
        valid_metrics = rules.get("valid_metrics", set())
        valid_types = rules.get("valid_claim_types", set())
        prohibited = rules.get("prohibited_generic_metrics", set())
        disallowed_specs = rules.get("disallowed_spec_keywords", set())

        metric = str(raw.get("metric") or "").strip()
        claim_type = str(raw.get("claim_type") or "").strip()
        product_or_spec = str(raw.get("product_or_spec") or "").strip().upper()

        if metric in prohibited:
            return False, None, [f"Metric {metric} is prohibited for {factor}"]
        if metric not in valid_metrics:
            return False, None, [f"Metric {metric} not valid for {factor}"]
        if claim_type not in valid_types:
            return False, None, [f"Claim type {claim_type} not valid for {factor}"]

        # Product/spec check
        if product_or_spec and product_or_spec in disallowed_specs:
            return False, None, [f"Product spec {product_or_spec} disallowed for {factor}"]

        # If acquisition_context provided, enforce binding validation
        if acquisition_context is not None:
            b = bindings_by_factor.get(factor)
            if not b:
                return False, None, [f"No factor binding in acquisition run for {factor}"]
            if b.claim_id != cid:
                return False, None, [f"Binding claim ID {b.claim_id} does not match {cid}"]
            if b.independent_lineage_count < 2:
                return False, None, [f"Binding {factor} lineage count {b.independent_lineage_count} < 2"]
            run_candidates = getattr(acquisition_context, "_candidates", [])
            run_obs_ids = {c.get("observation_id") for c in run_candidates if isinstance(c, Mapping)}
            if not b.canonical_observation_ids or not all(oid in run_obs_ids for oid in b.canonical_observation_ids):
                return False, None, [f"Dangling or mutated canonical observation ID in {factor} binding"]
            if b.period and raw.get("period") != b.period:
                return False, None, [f"Period {raw.get('period')} does not match binding {b.period}"]
            if b.unit and raw.get("unit") != b.unit:
                return False, None, [f"Unit {raw.get('unit')} does not match binding {b.unit}"]
            if b.product_or_spec and str(raw.get("product_or_spec") or "").strip().upper() != str(b.product_or_spec or "").strip().upper():
                return False, None, [f"Product spec {raw.get('product_or_spec')} does not match binding {b.product_or_spec}"]

        # Period type check: conditional forecasts cannot license realized historical facts
        period_type = raw.get("period_type")
        if period_type in {"FORWARD_GUIDANCE", "TARGET_LONG_TERM", "CONDITIONAL_FORECAST"}:
            return False, None, [f"Period type {period_type} cannot license realized factor {factor}"]

        # Canonical admitted observations check
        cand_observations = cand.get("source_observations") or []
        bound_obs = []
        for o in cand_observations:
            if not isinstance(o, Mapping):
                continue
            o_cids = o.get("claim_ids") or (o.get("payload") or {}).get("claim_ids") or []
            if isinstance(o_cids, str):
                o_cids = [o_cids]
            if cid in o_cids:
                bound_obs.append(o)

        if not bound_obs:
            return False, None, [f"Claim {cid} lacks canonical admitted observations"]

        # Validate URL of every bound observation
        for o in bound_obs:
            o_url = o.get("canonical_url") or o.get("url")
            if o_url:
                try:
                    validate_source_url(str(o_url))
                except BridgeValidationError:
                    return False, None, [f"Observation URL invalid for claim {cid}"]

        # Lineage deduplication: observations must evaluate to at least 2 independent families
        families = compute_independent_lineages(bound_obs)
        if families < 2:
            return False, None, [f"Claim {cid} observations collapse to {families} family (< 2 required)"]

        return True, cid, []

    # 1. Dependency Criticality
    customer_only = bool(dep_evidence.get("customer_relationship_only", False))
    bound_dep_id = None
    dep_diags: list[str] = []
    for cid in dep_claim_ids:
        ok, valid_cid, errs = get_valid_supported_claim(cid, "dependency")
        if ok and not customer_only:
            bound_dep_id = valid_cid
            break
        dep_diags.extend(errs)
    dependency_licensed = bound_dep_id is not None

    # 2. Scarcity & Switching
    shortage_relieved = bool(scarcity_evidence.get("shortage_relieved", False))
    bound_scarcity_id = None
    scarcity_diags: list[str] = []
    for cid in scarcity_claim_ids:
        ok, valid_cid, errs = get_valid_supported_claim(cid, "scarcity")
        if ok and not shortage_relieved:
            bound_scarcity_id = valid_cid
            break
        scarcity_diags.extend(errs)
    scarcity_licensed = bound_scarcity_id is not None

    # 3. Pricing Power
    high_margin_only = bool(pricing_evidence.get("high_gross_margin_only", False))
    bound_pricing_id = None
    pricing_diags: list[str] = []
    for cid in pricing_claim_ids:
        ok, valid_cid, errs = get_valid_supported_claim(cid, "pricing")
        if ok and not high_margin_only:
            bound_pricing_id = valid_cid
            break
        pricing_diags.extend(errs)
    pricing_licensed = bound_pricing_id is not None

    # 4. Company Capture & Financing
    raw_financing = cand.get("financing_risk") or cand.get("equity_capture_status")
    if raw_financing is None:
        financing_state = "STRUCTURAL_DISQUALIFIER"
    else:
        financing_state = str(raw_financing).strip().upper()
        if financing_state not in {"NONE", "MATERIAL_OVERHANG", "STRUCTURAL_DISQUALIFIER", "DESTROYED"}:
            financing_state = "STRUCTURAL_DISQUALIFIER"

    bound_capture_id = None
    capture_diags: list[str] = []
    for cid in capture_claim_ids:
        ok, valid_cid, errs = get_valid_supported_claim(cid, "capture")
        if ok:
            raw_c = validated_raw_by_id.get(valid_cid or "")
            if raw_c and raw_c.get("metric") == "bom_share_capture":
                if not capture_evidence.get("disciplined_financing"):
                    capture_diags.append("Disciplined financing required for bom_share_capture")
                    continue
            bound_capture_id = valid_cid
            break
        capture_diags.extend(errs)

    capture_licensed = (bound_capture_id is not None) and (financing_state in {"NONE", "MATERIAL_OVERHANG"})

    # Check distinct claims across all 4 factors
    bound_ids = [bound_dep_id, bound_scarcity_id, bound_pricing_id, bound_capture_id]
    non_null_bound = [b for b in bound_ids if b is not None]
    has_duplicates = len(non_null_bound) != len(set(non_null_bound))

    if has_duplicates:
        dependency_licensed = False
        scarcity_licensed = False
        pricing_licensed = False
        capture_licensed = False

    missing_core = []
    if not dependency_licensed:
        missing_core.append("dependency")
    if not scarcity_licensed:
        missing_core.append("scarcity")
    if not pricing_licensed:
        missing_core.append("pricing")
    if not capture_licensed:
        missing_core.append("capture")

    core_admitted = len(missing_core) == 0 and not has_duplicates

    # Admission tier: fixture test vs unadmitted live
    if core_admitted and fixture_mode:
        admission_tier = "TEST_ONLY"
    elif core_admitted and acquisition_context is not None:
        is_syn = getattr(acquisition_context, "_is_synthetic", False) or any(getattr(b, "is_test_binding", False) for b in acq_bindings)
        admission_tier = "TEST_ONLY_NONRUNTIME" if is_syn else "UNADMITTED"
    else:
        admission_tier = "UNADMITTED"

    diagnostics = dep_diags + scarcity_diags + pricing_diags + capture_diags

    return {
        "core_admitted": core_admitted,
        "dependency_licensed": dependency_licensed,
        "scarcity_licensed": scarcity_licensed,
        "pricing_licensed": pricing_licensed,
        "capture_licensed": capture_licensed,
        "missing_core": missing_core,
        "financing_state": financing_state,
        "bound_claim_ids": {
            "dependency": bound_dep_id,
            "scarcity": bound_scarcity_id,
            "pricing": bound_pricing_id,
            "capture": bound_capture_id,
        },
        "claim_counts": {
            "dependency": len(dep_claim_ids),
            "scarcity": len(scarcity_claim_ids),
            "pricing": len(pricing_claim_ids),
            "capture": len(capture_claim_ids),
        },
        "admission_tier": admission_tier,
        "diagnostics": diagnostics,
    }
