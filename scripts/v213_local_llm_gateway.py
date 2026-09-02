#!/usr/bin/env python3
"""v2.1.3 local-model gateway overlay for Serenity public-logic fidelity.

The underlying transport/security/source collectors remain v2.1.2. This wrapper
adds methodology directives and a model-bound health contract so Production can
only be wired to the exact llama.cpp model selected by the owner.
"""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path
from typing import Any

import requests

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import v212_local_llm_gateway as base

ORIGINAL_ENRICH = base.enrich_messages
METHODOLOGY_RE = re.compile(
    r"(?:serenity|瓶頸|瓶颈|供應鏈|供应链|chokepoint|bottleneck|supply\s*chain)",
    re.I,
)

PUBLIC_LOGIC_DIRECTIVE = """
[V2.1.3 SERENITY PUBLIC-LOGIC FIDELITY]
For substantive stock research, keep these layers separate:
1. Serenity source view: only what a dated identifiable Serenity public post supports. If no validated source view is supplied, explicitly say that no Serenity source view is attached for this ticker.
2. Public-logic fidelity state: architecture/supercycle -> evidence-bound supply-chain dependency graph -> information gap -> bottleneck-vs-expansion -> company capture/optionality -> thesis killers -> thesis lifecycle -> timing/source delta.
3. System operationalization score: the repository's legacy deterministic 100-point overlay. Never call it an official Serenity score or Serenity formula.
4. Model inference: your evidence-based conclusion, explicitly labelled with confidence and missing-data warnings.
5. User long-term overlay: separate user preference; never attribute it to Serenity.

Fail-closed rules:
- A keyword, sector label, high gross margin, revenue growth, beta, or short interest does not prove a chokepoint.
- A named customer dependency alone does not prove scarcity or a chokepoint. Bottleneck status needs evidenced supply concentration, qualification friction, binding capacity, or unique process/IP plus a graph edge that actually touches the focal company. A BENEFICIARY label also needs company-fact evidence; do not infer it from theme membership alone.
- Every dependency, commercial-validation, and thesis-killer signal must be tied to a primary/corroborating evidence URL and a valid as-of date before it changes the fidelity state. A thesis that is still UNPROVEN cannot jump to COMMERCIAL_VALIDATION or INSTITUTIONAL_VALIDATION merely because a commercial event exists.
- Supply-chain graph edges and architecture timing used to support a bottleneck must be evidence-bound and dated. Unknown edges stay unknown.
- Social posts prove what the author said, not the underlying company fact; corroborate company economics with primary/corroborating evidence.
- Revenue growth alone does not prove TAM capture; high gross margin alone does not prove replacement friction.
- Explicitly test company capture: qualified capacity/share, pricing/contract structure, financing durability, BOM/product mix, vertical integration, customer concentration, execution/capex, and architecture-bypass risk.
- Explicitly search for dilution/ATM, toxic financing, customer loss, architecture bypass, new qualified competitors, qualification/volume-ramp delay, scarcity removal, pricing collapse, jurisdiction/export risk, funding failure, and factual contradiction.
- A severe architecture/dependency break or evidence-backed destruction of equity capture can override a positive system score. A qualitative company-capture label alone cannot break the thesis; the severe killer must itself be evidence-bound.
- Do not exclude a foreign listing merely because SEC companyfacts is unavailable.
- Preserve company-specific timing. Do not invent a universal 8-12 month lead or two-year hold rule.
- Retrieved Serenity source views and source-delta items must preserve a valid publication date and horizon; source-delta must be chronological within the snapshot. Do not claim cross-run append-only history unless a persistent history store has actually verified it.
- If evidence cannot support the architecture, graph, dependency role, or company capture, label it UNPROVEN/INSUFFICIENT_EVIDENCE rather than guessing.
- Never claim 100% reproduction of Serenity's private method. Use the label: public-logic high-fidelity reconstruction.
""".strip()


def _last_user_text(messages: list[dict[str, Any]]) -> str:
    for item in reversed(messages):
        if isinstance(item, dict) and str(item.get("role") or "") == "user":
            return str(item.get("content") or "")
    return ""


def enrich_messages(messages: list[dict[str, Any]]):
    enriched, context = ORIGINAL_ENRICH(messages)
    user_text = _last_user_text(messages)
    context_ticker = context.get("ticker") if isinstance(context, dict) else None
    ticker = str(context_ticker or "").strip().upper() or base.extract_ticker(user_text)
    methodology_requested = bool(ticker) or bool(METHODOLOGY_RE.search(user_text))
    if methodology_requested:
        if enriched and enriched[0].get("role") == "system":
            enriched[0] = {
                "role": "system",
                "content": str(enriched[0].get("content") or "") + "\n\n" + PUBLIC_LOGIC_DIRECTIVE,
            }
        else:
            enriched.insert(0, {"role": "system", "content": PUBLIC_LOGIC_DIRECTIVE})
        context = dict(context)
        context["serenity_public_logic_fidelity"] = "v2.1.3"
        context["legacy_quantitative_overlay_label"] = "System operationalization score"
        context["private_process_reproduction_claimed"] = False
        context["cross_run_source_delta_append_only_verified"] = False
    return enriched, context


def _available_model_ids() -> list[str]:
    base_url = base.llama_base_url()
    last_error: Exception | None = None
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
        except Exception as exc:  # health remains fail-closed
            last_error = exc
    if last_error:
        return []
    return []


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
        models = _available_model_ids()
        canonical = next((item for item in models if item.casefold() == selected.casefold()), "")
        selected_available = bool(selected and canonical)
        self._json(
            200,
            {
                "ok": True,
                "service": "v213-local-llm-gateway",
                "llama_reachable": bool(upstream_health and selected_available),
                "selected_model": canonical or selected,
                "selected_model_available": selected_available,
                "available_model_count": len(models),
            },
        )


def main() -> int:
    base.enrich_messages = enrich_messages
    base.GatewayHandler = V213GatewayHandler
    return base.main()


if __name__ == "__main__":
    raise SystemExit(main())
