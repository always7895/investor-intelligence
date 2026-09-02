#!/usr/bin/env python3
"""v2.1.3 model-bound gateway with source-aware Serenity public logic."""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone
from http.server import ThreadingHTTPServer
from pathlib import Path
from typing import Any

import requests

SCRIPT_DIR = Path(__file__).resolve().parent
ROOT = SCRIPT_DIR.parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import v212_local_llm_gateway as base

ORIGINAL_ENRICH = base.enrich_messages
FEDERATION_PATH = ROOT / "data" / "cache" / "v213_source_federation_latest.json"
METHODOLOGY_RE = re.compile(
    r"(?:serenity|瓶頸|瓶颈|供應鏈|供应链|chokepoint|bottleneck|supply\s*chain)",
    re.I,
)

PUBLIC_LOGIC_DIRECTIVE = """
[V2.1.3 SERENITY PUBLIC-LOGIC HIGH-FIDELITY RECONSTRUCTION]
Keep five layers separate:
1. Serenity source view: only what a dated, identifiable Serenity public post supports. If none is attached, say so.
2. Public-logic state: architecture -> evidence-bound dependency graph -> information gap -> bottleneck/expansion -> company capture -> validation -> killers -> lifecycle/timing/source delta.
3. System operationalization score: project-authored compatibility field, never an official Serenity score or formula.
4. Model inference: explicitly labelled inference with confidence, missing evidence and disconfirming evidence.
5. User overlay: a separate preference, never attributed to Serenity.

SOURCE AND INDEPENDENCE RULES:
- The 100-source catalog is an inventory, not proof that every source was used. Use only live-source families stated in the current federation context.
- Count an independent publisher family, not URL quantity. Different URLs, mirrors, syndicated copies and the same issuer's IR plus same-issuer filing count once for independence.
- Different issuers filing on SEC may be independent publishers; a counterparty filing can corroborate the focal issuer. Search snippets and social reposts never form independent proof.
- Yahoo/yfinance is a T3 candidate/market observation, not an authoritative issuer, dependency, order or bottleneck source.
- A single market-data family is degraded. It cannot produce high market confidence and caps valuation inference.
- Conflicting primary material values remain CONFLICT_UNRESOLVED; do not average them.

CLAIM RULES:
- A keyword, sector label, high gross margin, revenue growth, beta, short interest or price action does not prove a chokepoint.
- A named customer alone does not prove scarcity. Positive bottleneck status requires an evidence-bound graph edge touching the focal company, at least two independent primary/corroborating publisher families, at least one primary family, and at least one family independent of the focal issuer.
- Gross margin alone does not prove replacement friction. Require qualification, switching cost, supply concentration or unique process/IP evidence from independent families.
- Revenue growth alone does not prove TAM capture. Test realized share/BOM capture, order visibility and company-specific economics.
- Issuer-only commercial statements are provisional. Strong commercial validation requires counterparty/regulator corroboration or realized audited revenue.
- Explicitly test financing durability, dilution/ATM, toxic financing, customer loss, architecture bypass, new qualified competitors, ramp delay, scarcity removal, pricing collapse, export/jurisdiction risk and factual contradiction.
- A severe, evidence-backed primary thesis killer may override positive evidence asymmetrically; do not require two-source positive-proof symmetry before acknowledging a primary-source destruction event.
- Preserve company-specific timing. Never invent a universal lead or holding period.
- If architecture, graph, dependency role or capture is unsupported, label it UNPROVEN/INSUFFICIENT_EVIDENCE.
- Never claim 100% reproduction of Serenity's private method. Use: public-logic high-fidelity reconstruction.
""".strip()


def _last_user_text(messages: list[dict[str, Any]]) -> str:
    for item in reversed(messages):
        if isinstance(item, dict) and str(item.get("role") or "") == "user":
            return str(item.get("content") or "")
    return ""


def _parse_timestamp(value: Any) -> datetime | None:
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).astimezone(timezone.utc)
    except (TypeError, ValueError):
        return None


def _live_federation_context(ticker: str) -> str:
    try:
        doc = json.loads(FEDERATION_PATH.read_text(encoding="utf-8-sig"))
        generated = _parse_timestamp(doc.get("generated_at")) if isinstance(doc, dict) else None
        if generated is None or (datetime.now(timezone.utc) - generated).total_seconds() > 7200:
            return "LIVE SOURCE FEDERATION: unavailable or stale; source-dependent claims must fail closed."
        gates = doc.get("gates") if isinstance(doc.get("gates"), dict) else {}
        successful = ", ".join(str(v) for v in gates.get("successful_families") or [])
        official = ", ".join(str(v) for v in gates.get("official_successful_families") or [])
        conflicts = int(gates.get("unresolved_material_conflict_count") or 0)
        lines = [
            "LIVE SOURCE FEDERATION (catalog is an inventory; these families were actually observed):",
            f"successful_families={successful or 'none'}",
            f"official_successful_families={official or 'none'}",
            f"ticker_multisource_coverage={gates.get('ticker_coverage_ratio', 0)}",
            f"unresolved_material_conflicts={conflicts}",
            "market rule: Yahoo/yfinance is T3 observation only; one market family is degraded.",
        ]
        if ticker:
            rows = doc.get("ticker_sources") if isinstance(doc.get("ticker_sources"), list) else []
            row = next((item for item in rows if isinstance(item, dict) and str(item.get("ticker")) == ticker), None)
            if row:
                lines.extend([
                    f"ticker={ticker}",
                    "independent_families=" + ", ".join(str(v) for v in row.get("independent_families") or []),
                    "official_identity_or_filing_families=" + ", ".join(str(v) for v in row.get("official_identity_or_filing_families") or []),
                    "market_observation_families=" + ", ".join(str(v) for v in row.get("market_observation_families") or []),
                    f"market_provider_confidence={row.get('market_provider_confidence', 'UNKNOWN')}",
                    f"issuer_financial_claim_family_count={row.get('issuer_financial_claim_family_count', 0)}",
                ])
        return "\n".join(lines)
    except Exception:
        return "LIVE SOURCE FEDERATION: unreadable; source-dependent claims must fail closed."


def enrich_messages(messages: list[dict[str, Any]]):
    enriched, context = ORIGINAL_ENRICH(messages)
    user_text = _last_user_text(messages)
    context_ticker = context.get("ticker") if isinstance(context, dict) else None
    ticker = str(context_ticker or "").strip().upper() or base.extract_ticker(user_text)
    methodology_requested = bool(ticker) or bool(METHODOLOGY_RE.search(user_text))
    if methodology_requested:
        directive = PUBLIC_LOGIC_DIRECTIVE + "\n\n" + _live_federation_context(ticker)
        if enriched and enriched[0].get("role") == "system":
            enriched[0] = {
                "role": "system",
                "content": str(enriched[0].get("content") or "") + "\n\n" + directive,
            }
        else:
            enriched.insert(0, {"role": "system", "content": directive})
        context = dict(context)
        context["serenity_public_logic_fidelity"] = "v2.1.3-evidence-standard-v3"
        context["legacy_quantitative_overlay_label"] = "System operationalization score"
        context["private_process_reproduction_claimed"] = False
        context["source_catalog_is_live_use"] = False
        context["cross_run_source_delta_append_only_verified"] = False
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


def _build_health_payload(selected: str, models: list[str], upstream_health: bool) -> dict[str, Any]:
    canonical = next((item for item in models if item.casefold() == selected.casefold()), "")
    selected_available = bool(selected and canonical)
    return {
        "ok": True,
        "service": "v213-local-llm-gateway",
        "health_schema_version": 2,
        "llama_reachable": bool(upstream_health and selected_available),
        "selected_model": canonical or selected,
        "selected_model_available": selected_available,
        "available_model_count": len(models),
    }


class V213GatewayHandler(base.GatewayHandler):
    server_version = "InvestorIntelligenceLocalGateway/2.1.3"

    def do_GET(self) -> None:  # noqa: N802
        if self.path.split("?", 1)[0] != "/health":
            super().do_GET()
            return
        selected = os.getenv("II_LOCAL_LLM_MODEL", "").strip()
        try:
            response = requests.get(base.llama_base_url() + "/health", timeout=(2, 5))
            upstream_health = response.ok
        except Exception:
            upstream_health = False
        self._json(200, _build_health_payload(selected, _available_model_ids(), upstream_health))


def _self_test() -> None:
    preferred = "RVN-Q6_K-multilingual-mtp"
    exact = _build_health_payload(preferred, ["gemma4", preferred], True)
    assert exact["service"] == "v213-local-llm-gateway"
    assert exact["health_schema_version"] == 2
    assert exact["llama_reachable"] is True
    assert exact["selected_model"] == preferred
    assert exact["selected_model_available"] is True
    missing = _build_health_payload(preferred, ["gemma4"], True)
    assert missing["llama_reachable"] is False
    assert missing["selected_model_available"] is False
    assert "publisher family" in PUBLIC_LOGIC_DIRECTIVE
    assert "catalog is an inventory" in PUBLIC_LOGIC_DIRECTIVE
    assert "single market-data family" in PUBLIC_LOGIC_DIRECTIVE
    assert "severe" in PUBLIC_LOGIC_DIRECTIVE
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
        f"Investor Intelligence v2.1.3 local gateway listening on http://{args.host}:{args.port}",
        flush=True,
    )
    server.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
