#!/usr/bin/env python3
"""v2.1.3 exact-model gateway with claim-level source independence.

The gateway inherits transport and authentication from v2.1.2, then binds every
Serenity public-logic response to the v2.1.3 source-independence sidecar.  It does
not claim access to Serenity's private process, official formula, or official
score.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone
from http.server import ThreadingHTTPServer
from pathlib import Path
from typing import Any, Mapping

import requests

SCRIPT_DIR = Path(__file__).resolve().parent
ROOT = SCRIPT_DIR.parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import v212_local_llm_gateway as base

ORIGINAL_ENRICH = base.enrich_messages
SOURCE_AUDIT_PATH = ROOT / "data" / "cache" / "v213_source_independence_latest.json"
FEDERATION_PATH = ROOT / "data" / "cache" / "v213_source_federation_latest.json"
SOURCE_AUDIT_MAX_AGE_SECONDS = 7200
METHODOLOGY_RE = re.compile(
    r"(?:serenity|瓶頸|瓶颈|供應鏈|供应链|chokepoint|bottleneck|"
    r"supply\s*chain|source|來源|来源|evidence|證據|证据|thesis|投資邏輯)",
    re.I,
)

PUBLIC_LOGIC_DIRECTIVE = """
[V2.1.3 SERENITY PUBLIC-LOGIC HIGH-FIDELITY RECONSTRUCTION]
This is a public-logic reconstruction. It is not Serenity's private method,
official formula, or official score. Keep these layers separate:
1. Dated identifiable Serenity public-source view. If no validated source is
   attached, report NOT_ATTACHED; never fill it from model memory.
2. Architecture and demand wave.
3. Evidence-bound dependency graph.
4. Bottleneck-versus-expansion state.
5. Company capture and optionality.
6. Valuation expectations and timing/source delta.
7. Thesis killers and counterfactuals.
8. Thesis lifecycle.
9. The repository's legacy deterministic score, labelled only as System
   operationalization and never as a Serenity score.
10. Explicitly labelled model inference with uncertainty.
11. The user's long-term preference as a separate overlay.

SOURCE-INDEPENDENCE RULES:
- v213_source_independence_latest.json is the claim-level control plane. If it is
  absent, stale, FAIL, mismatched to the ticker, or marks the ticker ineligible,
  cap confidence at LIMITED and use UNPROVEN/INSUFFICIENT_EVIDENCE for unsupported
  architecture, dependency, bottleneck, capture, order, timing, or killer claims.
- Count independent publisher families and registrable domains, not URL volume.
  Mirrors, syndicated copies, tracking variants, the same domain, and the same
  corporate source family do not become independent corroboration by repetition.
- A social post proves what its author said, not the underlying company fact.
- Yahoo/yfinance remains a compatibility adjusted-close calculation provider. It
  is not sufficient thesis evidence and cannot establish dependency, scarcity,
  company capture, orders, or thesis killers.
- Stooq, Nasdaq, and optional Alpha Vantage independently corroborate the market
  path. Market data does not prove a bottleneck or company-specific operating fact.
- FRED is official macro context only. It cannot satisfy the company/regulatory
  primary-evidence requirement for a company claim.
- A narrow SEC/regulatory filing, exchange announcement, or issuer disclosure may
  establish its disclosed fact. Broader inference requires another independent,
  claim-relevant source family and domain.
- Conflicting sources remain visible and confidence-reducing. Conflicting sources
  are never averaged away to manufacture precision.
- Source diversity is necessary but is not truth by itself. Evidence quality,
  claim relevance, dates, entity identity, and disconfirming evidence still govern.

CLAIM RULES:
- Keywords, sector labels, revenue growth, gross margin, beta, short interest,
  price action, or a named customer alone do not prove a chokepoint.
- Positive bottleneck status requires an evidence-bound graph edge touching the
  focal company, a claim-relevant primary source, and independent corroboration.
- Gross margin alone does not prove replacement friction. Require qualification,
  switching-cost, concentrated supply, or unique process/IP evidence.
- Revenue growth alone does not prove TAM capture. Test realized share/BOM capture,
  order visibility, contract structure, financing durability, and economics.
- Issuer-only commercial statements remain provisional until corroborated by a
  counterparty, regulator, exchange, credible independent publication, or realized
  audited revenue.
- Explicitly test dilution/ATM, toxic financing, customer loss, architecture bypass,
  newly qualified competitors, qualification or ramp delay, scarcity removal,
  pricing collapse, export/jurisdiction risk, funding failure, and factual
  contradiction.
- A severe, evidence-bound primary thesis killer may override positive evidence
  asymmetrically.
- Never invent a universal lead time, holding period, dependency edge, order value,
  customer relationship, or timing estimate.
""".strip()


def _last_user_text(messages: list[dict[str, Any]]) -> str:
    for item in reversed(messages):
        if isinstance(item, dict) and str(item.get("role") or "") == "user":
            return str(item.get("content") or "")
    return ""


def _parse_timestamp(value: Any) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed.astimezone(timezone.utc) if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None


def _load_json(path: Path) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
        return value if isinstance(value, dict) else None
    except (OSError, json.JSONDecodeError):
        return None


def _load_fresh_source_audit() -> tuple[dict[str, Any] | None, str, int | None]:
    document = _load_json(SOURCE_AUDIT_PATH)
    if document is None:
        return None, "MISSING_OR_UNREADABLE", None
    generated = _parse_timestamp(document.get("generated_at"))
    if generated is None:
        return None, "INVALID_GENERATED_AT", None
    age = int((datetime.now(timezone.utc) - generated).total_seconds())
    if age < -300:
        return None, "FUTURE_TIMESTAMP", age
    if age > SOURCE_AUDIT_MAX_AGE_SECONDS:
        return None, "STALE", age
    return document, "FRESH", age


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _format_source_audit_context(
    document: Mapping[str, Any] | None,
    ticker: str,
    availability: str,
    age_seconds: int | None,
) -> tuple[str, bool]:
    header = "[V2.1.3 SOURCE-INDEPENDENCE AUDIT]"
    if not isinstance(document, Mapping):
        return (
            "\n".join(
                [
                    header,
                    "source=v213_source_independence_latest.json",
                    f"availability={availability}",
                    f"age_seconds={age_seconds if age_seconds is not None else 'unknown'}",
                    "Mandatory behavior: cap confidence at LIMITED. Treat source-dependent claims as UNPROVEN/INSUFFICIENT_EVIDENCE and identify the missing evidence.",
                ]
            ),
            False,
        )

    portfolio = _as_dict(document.get("portfolio"))
    status = str(document.get("status") or "UNKNOWN")
    lines = [
        header,
        "source=v213_source_independence_latest.json",
        f"availability={availability}",
        f"age_seconds={age_seconds if age_seconds is not None else 'unknown'}",
        f"document_status={status}",
        f"policy_version={document.get('policy_version', 'unknown')}",
        "portfolio_source_families=" + ", ".join(str(value) for value in _as_list(portfolio.get("source_families"))),
        "portfolio_source_domains=" + ", ".join(str(value) for value in _as_list(portfolio.get("source_domains"))),
        "portfolio_claim_source_families=" + ", ".join(str(value) for value in _as_list(portfolio.get("claim_source_family_list"))),
        "portfolio_claim_source_domains=" + ", ".join(str(value) for value in _as_list(portfolio.get("claim_source_domain_list"))),
        f"portfolio_non_yahoo_market_coverage={portfolio.get('non_yahoo_market_coverage_ratio', 0)}",
        f"portfolio_claim_primary_coverage={portfolio.get('claim_primary_coverage_ratio', 0)}",
        f"portfolio_market_conflict_tickers={portfolio.get('market_conflict_ticker_count', 0)}",
        f"fred_macro_status={portfolio.get('fred_macro_status', 'UNKNOWN')} (macro context only, never company-claim primary evidence)",
    ]

    if status != "PASS":
        lines.append("Portfolio source policy is not PASS; cap confidence at LIMITED for every ticker.")

    if not ticker:
        lines.append("No ticker was resolved; no ticker-specific HIGH-confidence inference is eligible.")
        return "\n".join(lines), False

    records = _as_list(document.get("records"))
    record = next(
        (
            item
            for item in records
            if isinstance(item, dict)
            and str(item.get("ticker") or "").strip().upper() == ticker
        ),
        None,
    )
    if not isinstance(record, dict):
        lines.extend(
            [
                f"ticker={ticker}",
                "ticker_record=NOT_FOUND",
                "Mandatory behavior: cap confidence at LIMITED and do not borrow another ticker's evidence.",
            ]
        )
        return "\n".join(lines), False

    metrics = _as_dict(record.get("source_metrics"))
    market = _as_dict(record.get("market_corroboration"))
    public_logic = _as_dict(record.get("public_logic_state"))
    eligible = status == "PASS" and record.get("eligible_for_high_confidence_model_inference") is True
    lines.extend(
        [
            f"ticker={ticker}",
            f"evidence_independence_score={record.get('evidence_independence_score', 'N/A')} (not a Serenity score)",
            f"claim_relevant_independent_families={metrics.get('claim_relevant_independent_families', 0)}",
            f"claim_relevant_independent_domains={metrics.get('claim_relevant_independent_domains', 0)}",
            f"claim_relevant_primary_sources={metrics.get('claim_relevant_primary_sources', 0)}",
            f"claim_dated_evidence_ratio={metrics.get('claim_dated_evidence_ratio', 0)}",
            "claim_families=" + ", ".join(str(value) for value in _as_list(metrics.get("claim_families"))),
            "claim_domains=" + ", ".join(str(value) for value in _as_list(metrics.get("claim_domains"))),
            f"all_primary_or_official_sources={metrics.get('primary_or_official_sources', 0)} (may include macro; do not substitute this for claim primary)",
            f"market_corroboration_status={market.get('status', 'UNAVAILABLE')}",
            f"independent_market_provider_count={market.get('independent_provider_count', 0)}",
            "public_logic_state=" + json.dumps(public_logic, ensure_ascii=False, sort_keys=True),
            "missing_or_review=" + (
                ", ".join(str(value) for value in _as_list(record.get("missing_or_review")))
                or "none"
            ),
            f"high_confidence_model_inference_eligible={str(eligible).lower()}",
        ]
    )

    sources = [item for item in _as_list(record.get("sources")) if isinstance(item, dict)]
    sources.sort(
        key=lambda item: (
            str(item.get("claim_type") or "") in {
                "market_return_calculation",
                "independent_market_corroboration",
                "macro_context",
            },
            str(item.get("family") or ""),
            str(item.get("domain") or ""),
        )
    )
    lines.append("independent_evidence_units:")
    for source in sources[:14]:
        lines.append(
            "- family={family} | domain={domain} | claim={claim} | as_of={as_of} | claim_primary={primary} | url={url}".format(
                family=str(source.get("family") or "unknown"),
                domain=str(source.get("domain") or "unknown"),
                claim=str(source.get("claim_type") or "unknown"),
                as_of=str(source.get("as_of") or "undated"),
                primary=str(source.get("claim_primary") is True).lower(),
                url=str(source.get("url") or ""),
            )
        )
    if not sources:
        lines.append("- none")

    if eligible:
        lines.append("Mandatory behavior: HIGH is only eligible for the exact claims supported by the listed evidence; unsupported extensions remain LIMITED or UNPROVEN.")
    else:
        lines.append("Mandatory behavior: cap confidence at LIMITED; use UNPROVEN/INSUFFICIENT_EVIDENCE for unsupported claims.")
    return "\n".join(lines), eligible


def _source_audit_context(ticker: str) -> tuple[str, bool]:
    document, availability, age_seconds = _load_fresh_source_audit()
    return _format_source_audit_context(document, ticker, availability, age_seconds)


def _supplemental_federation_context(ticker: str) -> str:
    document = _load_json(FEDERATION_PATH)
    if document is None:
        return "SUPPLEMENTAL LIVE SOURCE FEDERATION: unavailable; it does not override the claim-level audit."
    generated = _parse_timestamp(document.get("generated_at"))
    if generated is None:
        return "SUPPLEMENTAL LIVE SOURCE FEDERATION: invalid timestamp; it does not override the claim-level audit."
    age = int((datetime.now(timezone.utc) - generated).total_seconds())
    if age < -300 or age > SOURCE_AUDIT_MAX_AGE_SECONDS:
        return "SUPPLEMENTAL LIVE SOURCE FEDERATION: stale; it does not override the claim-level audit."
    gates = _as_dict(document.get("gates"))
    lines = [
        "[SUPPLEMENTAL LIVE SOURCE FEDERATION]",
        "This inventory cannot upgrade a claim that failed the claim-level source-independence audit.",
        "successful_families=" + ", ".join(str(value) for value in _as_list(gates.get("successful_families"))),
        "official_successful_families=" + ", ".join(str(value) for value in _as_list(gates.get("official_successful_families"))),
        f"unresolved_material_conflicts={gates.get('unresolved_material_conflict_count', 0)}",
    ]
    if ticker:
        rows = _as_list(document.get("ticker_sources"))
        row = next(
            (
                item
                for item in rows
                if isinstance(item, dict)
                and str(item.get("ticker") or "").strip().upper() == ticker
            ),
            None,
        )
        if isinstance(row, dict):
            lines.extend(
                [
                    f"ticker={ticker}",
                    "observed_families=" + ", ".join(str(value) for value in _as_list(row.get("independent_families"))),
                    "market_observation_families=" + ", ".join(str(value) for value in _as_list(row.get("market_observation_families"))),
                ]
            )
    return "\n".join(lines)


def enrich_messages(messages: list[dict[str, Any]]):
    enriched, context = ORIGINAL_ENRICH(messages)
    user_text = _last_user_text(messages)
    context_ticker = context.get("ticker") if isinstance(context, dict) else None
    extracted = base.extract_ticker(user_text)
    ticker = str(context_ticker or extracted or "").strip().upper()
    methodology_requested = bool(ticker) or bool(METHODOLOGY_RE.search(user_text))
    if methodology_requested:
        audit_context, eligible = _source_audit_context(ticker)
        directive = (
            PUBLIC_LOGIC_DIRECTIVE
            + "\n\n"
            + audit_context
            + "\n\n"
            + _supplemental_federation_context(ticker)
        )
        if enriched and enriched[0].get("role") == "system":
            enriched[0] = {
                "role": "system",
                "content": str(enriched[0].get("content") or "") + "\n\n" + directive,
            }
        else:
            enriched.insert(0, {"role": "system", "content": directive})
        context = dict(context) if isinstance(context, dict) else {}
        context["serenity_public_logic_fidelity"] = "2.1.3-source-independence-v3"
        context["legacy_quantitative_overlay_label"] = "System operationalization score"
        context["private_process_reproduction_claimed"] = False
        context["official_serenity_formula_claimed"] = False
        context["source_independence_sidecar"] = "v213_source_independence_latest.json"
        context["source_independence_high_confidence_eligible"] = eligible
        context["model_confidence_cap"] = "HIGH_ELIGIBLE" if eligible else "LIMITED"
    return enriched, context


def _available_model_ids() -> list[str]:
    base_url = base.llama_base_url()
    for suffix in ("/v1/models?reload=1", "/models?reload=1", "/v1/models"):
        try:
            response = requests.get(base_url + suffix, timeout=(2, 8))
            response.raise_for_status()
            payload = response.json()
            rows = payload.get("data") if isinstance(payload, dict) else None
            if not isinstance(rows, list):
                continue
            result: list[str] = []
            for row in rows:
                if not isinstance(row, dict):
                    continue
                model_id = str(row.get("id") or "").strip()
                if model_id and model_id not in result:
                    result.append(model_id)
            if result:
                return result
        except Exception:
            continue
    return []


def _source_audit_health() -> dict[str, Any]:
    document, availability, age_seconds = _load_fresh_source_audit()
    return {
        "source_independence_audit_available": document is not None,
        "source_independence_audit_freshness": availability,
        "source_independence_audit_age_seconds": age_seconds,
        "source_independence_status": (
            str(document.get("status") or "UNKNOWN")
            if isinstance(document, dict)
            else "UNAVAILABLE"
        ),
        "source_independence_policy_version": (
            str(document.get("policy_version") or "")
            if isinstance(document, dict)
            else ""
        ),
    }


def _build_health_payload(
    selected: str,
    models: list[str],
    upstream_health: bool,
    audit_health: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    canonical = next(
        (item for item in models if item.casefold() == selected.casefold()),
        "",
    )
    selected_available = bool(selected and canonical)
    payload: dict[str, Any] = {
        "ok": True,
        "service": "v213-local-llm-gateway",
        "health_schema_version": 2,
        "llama_reachable": bool(upstream_health and selected_available),
        "selected_model": canonical or selected,
        "selected_model_available": selected_available,
        "available_model_count": len(models),
    }
    payload.update(dict(audit_health or {}))
    return payload


class V213GatewayHandler(base.GatewayHandler):
    server_version = "InvestorIntelligenceLocalGateway/2.1.3"

    def do_GET(self) -> None:  # noqa: N802
        if self.path.split("?", 1)[0] != "/health":
            super().do_GET()
            return
        selected = os.getenv("II_LOCAL_LLM_MODEL", "").strip()
        try:
            response = requests.get(
                base.llama_base_url() + "/health",
                timeout=(2, 5),
            )
            upstream_health = response.ok
        except Exception:
            upstream_health = False
        self._json(
            200,
            _build_health_payload(
                selected,
                _available_model_ids(),
                upstream_health,
                _source_audit_health(),
            ),
        )


def _self_test() -> None:
    preferred = "RVN-Q6_K-multilingual-mtp"
    exact = _build_health_payload(
        preferred,
        ["gemma4", preferred],
        True,
        {"source_independence_status": "PASS"},
    )
    assert exact["service"] == "v213-local-llm-gateway"
    assert exact["health_schema_version"] == 2
    assert exact["llama_reachable"] is True
    assert exact["selected_model"] == preferred
    assert exact["selected_model_available"] is True
    assert exact["source_independence_status"] == "PASS"

    missing_model = _build_health_payload(preferred, ["gemma4"], True)
    assert missing_model["llama_reachable"] is False
    assert missing_model["selected_model_available"] is False

    sample = {
        "status": "PASS",
        "policy_version": "test",
        "portfolio": {
            "source_families": ["regulator_filing", "reputable_secondary", "stooq_market"],
            "source_domains": ["sec.gov", "reuters.com", "stooq.com"],
            "claim_source_family_list": ["regulator_filing", "reputable_secondary"],
            "claim_source_domain_list": ["sec.gov", "reuters.com"],
            "non_yahoo_market_coverage_ratio": 1.0,
            "claim_primary_coverage_ratio": 1.0,
            "market_conflict_ticker_count": 0,
            "fred_macro_status": "LIVE",
        },
        "records": [
            {
                "ticker": "TEST",
                "evidence_independence_score": 90,
                "eligible_for_high_confidence_model_inference": True,
                "source_metrics": {
                    "claim_relevant_independent_families": 2,
                    "claim_relevant_independent_domains": 2,
                    "claim_relevant_primary_sources": 1,
                    "claim_dated_evidence_ratio": 1.0,
                    "claim_families": ["regulator_filing", "reputable_secondary"],
                    "claim_domains": ["sec.gov", "reuters.com"],
                    "primary_or_official_sources": 2,
                },
                "market_corroboration": {
                    "status": "CORROBORATED",
                    "independent_provider_count": 1,
                },
                "public_logic_state": {"model_inference_confidence": "HIGH_ELIGIBLE"},
                "missing_or_review": [],
                "sources": [],
            }
        ],
    }
    context, eligible = _format_source_audit_context(sample, "TEST", "FRESH", 10)
    assert eligible is True
    assert "claim_relevant_primary_sources=1" in context
    assert "fred_macro_status=LIVE (macro context only" in context

    unavailable, unavailable_eligible = _format_source_audit_context(
        None,
        "TEST",
        "MISSING_OR_UNREADABLE",
        None,
    )
    assert unavailable_eligible is False
    assert "cap confidence at LIMITED" in unavailable

    assert "SOURCE-INDEPENDENCE RULES" in PUBLIC_LOGIC_DIRECTIVE
    assert "v213_source_independence_latest.json" in PUBLIC_LOGIC_DIRECTIVE
    assert "Yahoo/yfinance" in PUBLIC_LOGIC_DIRECTIVE
    assert "Conflicting sources" in PUBLIC_LOGIC_DIRECTIVE
    assert "FRED is official macro context only" in PUBLIC_LOGIC_DIRECTIVE
    print("V213_LOCAL_LLM_GATEWAY_HEALTH_SELF_TEST = PASS")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default=base.HOST)
    parser.add_argument("--port", type=int, default=base.PORT)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        _self_test()
        return 0
    if args.host not in {"127.0.0.1", "localhost"}:
        raise SystemExit("Gateway must bind to loopback only")
    if len(os.getenv("II_LOCAL_LLM_SHARED_SECRET", "")) < 32:
        raise SystemExit("II_LOCAL_LLM_SHARED_SECRET must be configured")
    base.enrich_messages = enrich_messages
    server = ThreadingHTTPServer((args.host, args.port), V213GatewayHandler)
    print(
        "Investor Intelligence v2.1.3 local gateway listening on "
        f"http://{args.host}:{args.port}",
        flush=True,
    )
    server.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
