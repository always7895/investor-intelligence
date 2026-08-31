#!/usr/bin/env python3
"""v2.1.1 evidence-gated Serenity runner.

This wrapper preserves the accepted v2.1.1 candidate-discovery and v2.1.0
seven-factor scoring behavior, while guaranteeing that every scored public
research record carries at least one public SEC evidence item. Some foreign
private issuers/ADRs can return companyfacts payloads that parse successfully
but yield no metric evidence under the accepted US-GAAP metric extractor. Such
records must not enter the signed research universe with an empty evidence
array.

When the metric extractor returns no evidence, this wrapper adds only a neutral
SEC legal-entity/ticker-reference evidence record. It does not add Serenity
points, does not add metrics, and does not inherit any owner watchlist.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Mapping, Sequence

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import v211_serenity_top20 as impl

_ORIGINAL_SCORE_CANDIDATE = impl.base.score_candidate


def evidence_gated_score_candidate(
    candidate: Mapping[str, Any],
    metric: Mapping[str, Any],
    evidence: Sequence[Any],
    policy: Mapping[str, Any],
) -> dict[str, Any]:
    safe_evidence = list(evidence)
    if not safe_evidence:
        safe_evidence = [
            impl.base.Evidence(
                "sec_edgar",
                "T0",
                "legal_entity_reference",
                f"SEC ticker reference for {candidate['ticker']}",
                str(policy["sec_ticker_exchange_url"]),
                impl.base.iso_now(),
            )
        ]
    return _ORIGINAL_SCORE_CANDIDATE(candidate, metric, safe_evidence, policy)


# Patch only the scoring call used by impl.run(). The final Serenity formula is
# unchanged; the patch supplies a public evidence floor when metrics produced no
# evidence rows.
impl.base.score_candidate = evidence_gated_score_candidate


def main() -> int:
    return impl.main()


if __name__ == "__main__":
    raise SystemExit(main())
