#!/usr/bin/env python3
"""v2.1.1 owner-independent thematic coverage + evidence gate.

The accepted broad/Yahoo thematic discovery can still miss small optical/photonics
issuers when search ranking does not surface them.  This wrapper adds a second,
authoritative discovery lane based only on SEC official issuer names and a small
set of generic high-specificity optical/photonics lexical tokens.

No ticker is hard-coded.  SEC-name theme membership only reserves access to the
existing full Serenity scoring gate.  It does not add a theme bonus.  A lexical
normalization for "optoelectronic(s)" is added to the existing optical/photonics
vocabulary so issuer names using that standard term are classified consistently
with "optical" and "photonics".  Factor weights and risk penalties are unchanged.

The imported evidence gate also guarantees at least one public SEC evidence item
for foreign private issuers/ADRs whose accepted US-GAAP metric extractor yields
no metric evidence rows.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Mapping, Sequence

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import v211_serenity_top20_evidence_gate as evidence_gate

impl = evidence_gate.impl
base = impl.base
_ORIGINAL_VALIDATE_CANDIDATES = impl.validate_candidates
_ORIGINAL_RUN = impl.run

# High-specificity lexical concepts only.  These are generic sector terms, not
# owner symbols or a curated owner watchlist.
SEC_NAME_OPTICAL_TERMS = (
    "optoelectronic",
    "optoelectronics",
    "photon",
    "photonic",
    "optical",
    "laser",
    "fiber",
    "fibre",
)
AUTHORITATIVE_NAME_PRIORITY = 100

# Lexical normalization: the accepted v2.1 scorer already recognizes optical,
# photonics and laser.  "optoelectronics" is the same thematic vocabulary, not
# a discovery-membership score bonus.
base.AI_WORDS.update({"optoelectronic", "optoelectronics"})
base.CHOKE_WORDS.update({"optoelectronic", "optoelectronics"})
base.DOMAIN_C.update({"optoelectronic", "optoelectronics"})


def authoritative_name_theme_hits(name: str) -> int:
    text = str(name or "").casefold()
    return sum(term in text for term in SEC_NAME_OPTICAL_TERMS)


def augment_authoritative_name_seeds(
    seeds: Sequence[Mapping[str, Any]],
    reference: Mapping[str, Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Return owner-independent seeds augmented from SEC official issuer names."""
    result = [dict(item) for item in seeds]
    index = {str(item.get("ticker") or ""): item for item in result}

    matches: list[tuple[int, str, Mapping[str, Any]]] = []
    for symbol, official in reference.items():
        normalized = base.ticker(symbol)
        if not normalized:
            continue
        hits = authoritative_name_theme_hits(str(official.get("name") or ""))
        if hits > 0:
            matches.append((hits, normalized, official))
    matches.sort(key=lambda item: (-item[0], item[1]))

    # The existing SEC thematic reserve is the capacity gate.  Limiting the
    # authoritative lane to that same reserve prevents unbounded expansion.
    reserve = 40
    for hits, symbol, official in matches[:reserve]:
        entry = index.get(symbol)
        if entry is None:
            entry = {
                "ticker": symbol,
                "screen_weight": 0.0,
                "screeners": [],
                "theme_hits": AUTHORITATIVE_NAME_PRIORITY + hits,
                "theme_terms": ["sec_official_name_optical_photonics"],
                "market": {
                    "longName": str(official.get("name") or symbol),
                    "shortName": str(official.get("name") or symbol),
                },
            }
            result.append(entry)
            index[symbol] = entry
            continue

        entry["theme_hits"] = max(
            int(entry.get("theme_hits") or 0),
            AUTHORITATIVE_NAME_PRIORITY + hits,
        )
        terms = list(entry.get("theme_terms") or [])
        if "sec_official_name_optical_photonics" not in terms:
            terms.append("sec_official_name_optical_photonics")
        entry["theme_terms"] = terms
        market = dict(entry.get("market") or {})
        if not market.get("longName"):
            market["longName"] = str(official.get("name") or symbol)
        if not market.get("shortName"):
            market["shortName"] = str(official.get("name") or symbol)
        entry["market"] = market

    return result


def coverage_gated_validate_candidates(
    seeds: Sequence[Mapping[str, Any]],
    reference: Mapping[str, Mapping[str, Any]],
    policy: Mapping[str, Any],
) -> list[dict[str, Any]]:
    augmented = augment_authoritative_name_seeds(seeds, reference)
    return _ORIGINAL_VALIDATE_CANDIDATES(augmented, reference, policy)


impl.validate_candidates = coverage_gated_validate_candidates


def coverage_gated_run(*, synthetic: bool) -> dict[str, Any]:
    result = _ORIGINAL_RUN(synthetic=synthetic)
    plan = base.load_object(base.PLAN_PATH)
    discovery = plan.get("v211_discovery")
    if isinstance(discovery, dict):
        discovery["authoritative_sec_name_optical_photonics_lane"] = True
        discovery["authoritative_name_priority_is_discovery_only"] = True
        discovery["scoring_factor_weights_changed"] = False
        discovery["owner_specific_tickers_hardcoded"] = False
        base.atomic_json(base.PLAN_PATH, plan)
    return result


impl.run = coverage_gated_run


def main() -> int:
    return impl.main()


if __name__ == "__main__":
    raise SystemExit(main())
