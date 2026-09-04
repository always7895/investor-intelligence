#!/usr/bin/env python3
"""H4 semantic-reconciliation shadow.

Consumes a passed H4 v3 shadow report and repairs three residual semantic defects
found only after examining the real H4 output:

1. AAOI ATM event keys must represent actual dated financing actions, not par
   values / boilerplate fragments repeated across multiple filings.
2. TSEM's explicit SEC-filed announcement of a strategic capacity expansion is
   an observed expansion event, not generic/hypothetical text.
3. SIVE company-capture state must be reconciled after the official-primary
   retry adds a supported customer-ramp signal.

Shadow-only. It cannot add supply-chain dependency signals, graph edges, hard
bottleneck roles, or change Production rankings.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from copy import deepcopy
from pathlib import Path
from typing import Any, Mapping, Sequence

SCRIPT_DIR = Path(__file__).resolve().parent
ROOT = SCRIPT_DIR.parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import v213_serenity_evidence_rich_shadow as h3

DEFAULT_OUTPUT = ROOT / "data" / "cache" / "v213_serenity_h4_v4_semantic_shadow_latest.json"

MONTH = r"(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)"
DATE_RE = re.compile(rf"\b({MONTH}\s+\d{{1,2}},\s+20\d{{2}})\b", re.I)
ATM_CONTEXT_RE = re.compile(r"\b(?:at[- ]the[- ]market(?: offering)?|ATM offering|sales agreement)\b", re.I)
ATM_ACTION_RE = re.compile(r"\b(entered into|amended|amendment|increased|upsized|terminated|replaced)\b", re.I)
AMOUNT_RE = re.compile(r"\$\s*([\d,.]+)\s*(million|billion)?\b", re.I)

TSEM_EVENTIVE_RE = re.compile(
    r"\b(?:announces?|announced|will invest|will expand|expands?|strategic)\b.{0,120}\bcapacity expansion\b|"
    r"\bcapacity expansion\b.{0,120}\b(?:in japan|facility|fab|manufacturing|production|investment|meti)\b",
    re.I | re.S,
)
TSEM_HYPOTHETICAL_RE = re.compile(r"\b(?:if|may|might|could|would|risk|failure to|delay in)\b", re.I)


def _parse_amount_dollars(number: str, scale: str | None) -> float:
    value = float(number.replace(",", ""))
    if scale:
        if scale.casefold() == "million":
            value *= 1_000_000
        elif scale.casefold() == "billion":
            value *= 1_000_000_000
    return value


def strong_atm_event_keys(text: str) -> list[str]:
    """Return only dated, material ATM/sales-agreement financing events.

    The H3/H4 first pass used a wide window around any ATM reference. That could
    accidentally combine an action with unrelated `$0.001` par-value text or
    create `undated/noamount` pseudo-events. H4 v4 requires all of:
    - ATM/sales-agreement context;
    - an actual financing action;
    - an explicit date;
    - a material dollar amount (>= $1m).
    """
    clean = re.sub(r"\s+", " ", str(text or ""))
    keys: set[str] = set()
    for atm in ATM_CONTEXT_RE.finditer(clean):
        start = max(0, atm.start() - 420)
        end = min(len(clean), atm.end() + 620)
        window = clean[start:end]
        actions = list(ATM_ACTION_RE.finditer(window))
        dates = list(DATE_RE.finditer(window))
        amounts = list(AMOUNT_RE.finditer(window))
        if not actions or not dates or not amounts:
            continue
        action = min(actions, key=lambda m: abs((start + m.start()) - atm.start()))
        date = min(dates, key=lambda m: abs((start + m.start()) - atm.start()))
        material = []
        for amount in amounts:
            dollars = _parse_amount_dollars(amount.group(1), amount.group(2))
            if dollars >= 1_000_000:
                material.append((amount, dollars))
        if not material:
            continue
        amount_match, dollars = min(material, key=lambda item: abs((start + item[0].start()) - atm.start()))
        key = "|".join([
            action.group(1).casefold(),
            date.group(1).casefold(),
            f"${int(round(dollars))}",
        ])
        keys.add(key)
    return sorted(keys)


def reverify_aaoi_atm(result: Mapping[str, Any]) -> dict[str, Any]:
    audit = result.get("atm_event_audit") if isinstance(result.get("atm_event_audit"), Mapping) else {}
    urls = sorted(set(str(url) for url in audit.get("filing_urls") or [] if str(url)))
    event_sources: dict[str, set[str]] = {}
    errors: list[dict[str, str]] = []
    for url in urls:
        try:
            text = h3.fetch_sec_document(url)
            for key in strong_atm_event_keys(text):
                event_sources.setdefault(key, set()).add(url)
        except Exception as exc:
            errors.append({"url": url, "error": type(exc).__name__})
    keys = sorted(event_sources)
    return {
        "filing_urls": urls,
        "event_keys": keys,
        "event_sources": {key: sorted(event_sources[key]) for key in keys},
        "distinct_event_count": len(keys),
        "repeated_distinct_events": len(keys) >= 2,
        "errors": errors,
        "semantic_rule": "dated actual ATM/sales-agreement action + material amount >= $1m",
    }


def tsem_capacity_is_observed(excerpt: str) -> bool:
    text = re.sub(r"\s+", " ", str(excerpt or ""))
    if not TSEM_EVENTIVE_RE.search(text):
        return False
    # A filing headline saying "Announces ... Capacity Expansion" is eventive;
    # do not reject it just because another sentence elsewhere contains 'may'.
    event_span = TSEM_EVENTIVE_RE.search(text)
    assert event_span is not None
    local = text[max(0, event_span.start() - 60): min(len(text), event_span.end() + 60)]
    return not TSEM_HYPOTHETICAL_RE.search(local)


def _restore_tsem_capacity(row: dict[str, Any]) -> bool:
    audit = row.get("h3_claim_quality_audit") if isinstance(row.get("h3_claim_quality_audit"), dict) else {}
    rejected = list(audit.get("rejected") or [])
    restored: list[dict[str, Any]] = []
    remain: list[dict[str, Any]] = []
    for item in rejected:
        if (
            isinstance(item, Mapping)
            and str(item.get("signal") or "") == "capacity_expansion"
            and "sec.gov" in str(item.get("evidence_url") or "")
            and tsem_capacity_is_observed(str(item.get("excerpt") or ""))
        ):
            accepted = dict(item)
            accepted.pop("rejection_reason", None)
            accepted["semantic_retry_reason"] = "explicit_sec_filed_strategic_capacity_expansion_announcement"
            restored.append(accepted)
        else:
            remain.append(item)
    if not restored:
        return False

    audit["rejected"] = remain
    audit.setdefault("accepted", [])
    audit["accepted"] = list(audit["accepted"]) + restored
    row["h3_claim_quality_audit"] = audit
    row["h4_corrections"] = [
        correction for correction in list(row.get("h4_corrections") or [])
        if str(correction.get("signal") or "") != "capacity_expansion"
    ]

    supported = row.get("supported_signals") if isinstance(row.get("supported_signals"), dict) else {}
    expansion = list(supported.get("expansion") or [])
    if "capacity_expansion" not in expansion:
        expansion.append("capacity_expansion")
    supported["expansion"] = expansion
    row["supported_signals"] = supported

    fidelity = row.get("public_logic_fidelity") if isinstance(row.get("public_logic_fidelity"), dict) else {}
    url = str(restored[0].get("evidence_url") or "")
    fidelity["company_capture"] = {"state": "POSITIVE", "evidence_urls": [url] if url else []}
    fidelity["thesis_class"] = "EXPANSION_THESIS"
    if str(fidelity.get("thesis_state") or "") == "INSUFFICIENT_EVIDENCE":
        fidelity["thesis_state"] = "DISCOVERY"
    row["public_logic_fidelity"] = fidelity
    return True


def _reconcile_sive_capture(row: dict[str, Any]) -> bool:
    identity = row.get("identity_verification") if isinstance(row.get("identity_verification"), Mapping) else {}
    retry = identity.get("official_primary_retry") if isinstance(identity.get("official_primary_retry"), Mapping) else {}
    supported = row.get("supported_signals") if isinstance(row.get("supported_signals"), Mapping) else {}
    commercial = list(supported.get("commercial_validation") or [])
    if retry.get("official_primary_ok") is not True or "customer_named_ramp" not in commercial:
        return False

    urls: list[str] = []
    for source in identity.get("official_sources") or []:
        if isinstance(source, Mapping) and source.get("ok") and "q2-2026" in str(source.get("url") or "").casefold():
            urls.append(str(source.get("url")))
    if not urls:
        for source in retry.get("official_sources") or []:
            if isinstance(source, Mapping) and source.get("ok"):
                urls.append(str(source.get("url")))
    if not urls:
        return False

    fidelity = row.get("public_logic_fidelity") if isinstance(row.get("public_logic_fidelity"), dict) else {}
    fidelity["company_capture"] = {"state": "POSITIVE", "evidence_urls": list(dict.fromkeys(urls))}
    # Do not promote thesis_class or dependency_role. Customer ramp is company
    # capture/commercial evidence, not proof of a chokepoint.
    row["public_logic_fidelity"] = fidelity
    return True


def _remove_aaoi_atm_killer_if_not_repeated(row: dict[str, Any], atm: Mapping[str, Any]) -> bool:
    row["atm_event_audit"] = dict(atm)
    if atm.get("repeated_distinct_events"):
        return False
    fidelity = row.get("public_logic_fidelity") if isinstance(row.get("public_logic_fidelity"), dict) else {}
    killers = [str(item) for item in fidelity.get("thesis_killers") or []]
    if "repeated_atm_or_material_dilution" not in killers:
        return False
    fidelity["thesis_killers"] = [item for item in killers if item != "repeated_atm_or_material_dilution"]
    if str(fidelity.get("company_capture", {}).get("state") or "") == "MIXED":
        fidelity["company_capture"]["state"] = "POSITIVE"
    if str(fidelity.get("thesis_state") or "") == "THESIS_WEAKENING":
        fidelity["thesis_state"] = "DISCOVERY"
    row["public_logic_fidelity"] = fidelity
    return True


def semantic_retry(document: Mapping[str, Any]) -> dict[str, Any]:
    out = deepcopy(dict(document))
    rows = out.get("results")
    if not isinstance(rows, Sequence) or isinstance(rows, (str, bytes, bytearray)):
        raise ValueError("H4 results missing")

    corrections: list[dict[str, Any]] = []
    hard_before = sum(
        1 for row in rows if isinstance(row, Mapping)
        and str((row.get("public_logic_fidelity") or {}).get("dependency_role") or "")
        in {"SINGLE_SOURCE", "SEMI_MONOPOLY", "QUALIFICATION_CONSTRAINED", "CAPACITY_BOTTLENECK"}
    )

    for row in rows:
        if not isinstance(row, dict):
            continue
        ticker = str(row.get("ticker") or "")
        before_role = str((row.get("public_logic_fidelity") or {}).get("dependency_role") or "")
        if ticker == "AAOI":
            atm = reverify_aaoi_atm(row)
            removed = _remove_aaoi_atm_killer_if_not_repeated(row, atm)
            corrections.append({
                "ticker": ticker,
                "kind": "atm_event_semantics_reverified",
                "distinct_event_count": int(atm["distinct_event_count"]),
                "killer_removed": removed,
            })
        elif ticker == "TSEM":
            restored = _restore_tsem_capacity(row)
            corrections.append({"ticker": ticker, "kind": "capacity_event_reconciled", "restored": restored})
        elif ticker == "SIVE":
            reconciled = _reconcile_sive_capture(row)
            corrections.append({"ticker": ticker, "kind": "company_capture_reconciled", "reconciled": reconciled})

        after_role = str((row.get("public_logic_fidelity") or {}).get("dependency_role") or "")
        if after_role != before_role:
            raise ValueError(f"semantic retry attempted to change dependency_role for {ticker}: {before_role}->{after_role}")

    hard_after = sum(
        1 for row in rows if isinstance(row, Mapping)
        and str((row.get("public_logic_fidelity") or {}).get("dependency_role") or "")
        in {"SINGLE_SOURCE", "SEMI_MONOPOLY", "QUALIFICATION_CONSTRAINED", "CAPACITY_BOTTLENECK"}
    )
    if hard_after != hard_before:
        raise ValueError("semantic retry changed hard dependency count")

    summary = out.get("summary") if isinstance(out.get("summary"), dict) else {}
    summary["h4_v4_semantic_retry_applied"] = True
    summary["semantic_corrections"] = corrections
    summary["hard_dependency_count"] = hard_after
    summary["production_ranking_changed"] = False
    out["summary"] = summary
    out["h4_v4_semantic_retry_shadow_only"] = True
    out["production_ranking_changed"] = False
    return out


def self_test() -> None:
    sample = (
        "On March 12, 2026, we entered into an at-the-market Sales Agreement under which we may sell up to $250 million. "
        "Our common stock has a par value of $0.001 per share. "
        "On March 12, 2026, the at-the-market Sales Agreement was also described elsewhere as up to $250 million."
    )
    keys = strong_atm_event_keys(sample)
    assert keys == ["entered into|march 12, 2026|$250000000"]
    assert tsem_capacity_is_observed("The Registrant Announces Tower Semiconductor with METI Support Announces Strategic Capacity Expansion in Japan")
    assert not tsem_capacity_is_observed("If demand increases, we may consider capacity expansion in Japan")
    print("V213_H4_V4_SEMANTIC_SELF_TEST = PASS")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return 0
    if args.input is None:
        parser.error("--input is required unless --self-test is used")
    doc = json.loads(args.input.read_text(encoding="utf-8"))
    fixed = semantic_retry(doc)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(fixed, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"status": "PASS", "output": str(args.output)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
