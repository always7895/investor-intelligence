#!/usr/bin/env python3
"""v2.1.3 local-model gateway overlay for Serenity public-logic fidelity.

The underlying transport/security/source collectors remain v2.1.2. This wrapper
adds methodology directives so open-ended stock research does not confuse the
legacy quantitative overlay with Serenity's public discretionary reasoning.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import v212_local_llm_gateway as base

ORIGINAL_ENRICH = base.enrich_messages

PUBLIC_LOGIC_DIRECTIVE = """
[V2.1.3 SERENITY PUBLIC-LOGIC FIDELITY]
For substantive stock research, keep these layers separate:
1. Serenity source view: only what a dated identifiable Serenity public post supports.
2. Public-logic fidelity state: architecture/supercycle -> supply-chain dependency graph -> information gap -> bottleneck-vs-expansion -> company capture/optionality -> thesis killers -> thesis lifecycle -> timing/source delta.
3. System operationalization score: the repository's legacy deterministic 100-point overlay. Never call it an official Serenity score or Serenity formula.
4. Model inference: your evidence-based conclusion, explicitly labelled.
5. User long-term overlay: separate user preference; never attribute it to Serenity.

Fail-closed rules:
- A keyword, sector label, high gross margin, revenue growth, beta, or short interest does not prove a chokepoint.
- A bottleneck claim needs an evidenced dependency such as single/semi-monopoly, qualified-supplier concentration, qualification friction, binding capacity, unique process/IP, or named customer dependency.
- Social posts prove what the author said, not the underlying company fact; corroborate company economics with primary/corroborating evidence.
- Revenue growth alone does not prove TAM capture; high gross margin alone does not prove replacement friction.
- Explicitly search for dilution/ATM, toxic financing, customer loss, architecture bypass, new qualified competitors, qualification/volume-ramp delay, scarcity removal, pricing collapse, jurisdiction/export risk, funding failure, and factual contradiction.
- A severe architecture/dependency break can override a positive system score.
- Do not exclude a foreign listing merely because SEC companyfacts is unavailable.
- Preserve company-specific timing. Do not invent a universal 8-12 month lead or two-year hold rule.
- If evidence cannot support the supply-chain graph or dependency role, label it UNPROVEN/INSUFFICIENT_EVIDENCE rather than guessing.
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
    ticker = base.extract_ticker(user_text)
    methodology_requested = "serenity" in user_text.casefold() or ticker is not None
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
    return enriched, context


def main() -> int:
    base.enrich_messages = enrich_messages
    base.GatewayHandler.server_version = "InvestorIntelligenceLocalGateway/2.1.3"
    return base.main()


if __name__ == "__main__":
    raise SystemExit(main())
