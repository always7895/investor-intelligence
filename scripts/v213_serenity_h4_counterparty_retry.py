#!/usr/bin/env python3
"""H4 shadow-only retry for independent SIVE/GlobalFoundries corroboration.

This adapter patches only the already-produced H4 shadow report. It uses an
official GlobalFoundries page with browser-compatible headers and requires an
explicit Sivers + GlobalFoundries relationship marker before adding an
independent graph edge. It never creates a dependency signal or hard bottleneck
classification and never mutates Production.
"""
from __future__ import annotations

import argparse
import html
import json
import re
from pathlib import Path
from typing import Any, Mapping

import requests

BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/151.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Cache-Control": "no-cache",
    "Pragma": "no-cache",
}

GF_OFFICIAL_URLS = [
    "https://gf.com/technologies/silicon-photonics/",
]

HARD_ROLES = {
    "SINGLE_SOURCE",
    "SEMI_MONOPOLY",
    "QUALIFICATION_CONSTRAINED",
    "CAPACITY_BOTTLENECK",
}


def _visible_text(raw: str) -> str:
    text = re.sub(r"(?is)<(?:script|style|noscript).*?>.*?</(?:script|style|noscript)>", " ", raw)
    text = re.sub(r"(?s)<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", html.unescape(text)).strip()


def fetch_official_text(url: str, *, timeout: tuple[int, int] = (10, 35)) -> str:
    response = requests.get(url, headers=BROWSER_HEADERS, timeout=timeout)
    response.raise_for_status()
    raw = response.content[:3_000_000].decode(response.encoding or "utf-8", errors="replace")
    return _visible_text(raw)


def validate_gf_sivers_corroboration(text: str) -> bool:
    """Require an explicit Sivers relationship on an official GF page.

    A generic GF silicon-photonics page is not enough. The page must visibly
    contain Sivers and GlobalFoundries/GF plus collaboration/solution context.
    """
    value = str(text or "")
    if not re.search(r"\bSivers\b", value, re.I):
        return False
    if not re.search(r"\b(?:GlobalFoundries|GF)\b", value, re.I):
        return False
    relationship_patterns = [
        r"Sivers\s*&\s*GlobalFoundries\s+Advance\s+AI\s+Data\s+Center\s+Optical\s+Solutions",
        r"Sivers.{0,240}(?:collaboration|silicon photonics|SCALE|optical solutions)",
        r"(?:collaboration|silicon photonics|SCALE|optical solutions).{0,240}Sivers",
    ]
    return any(re.search(pattern, value, re.I | re.S) for pattern in relationship_patterns)


def corroborate_sive_globalfoundries() -> dict[str, Any]:
    attempts: list[dict[str, Any]] = []
    for url in GF_OFFICIAL_URLS:
        row: dict[str, Any] = {
            "counterparty": "GlobalFoundries Inc.",
            "url": url,
            "relationship": "official ecosystem collaboration",
            "independent": True,
            "official_counterparty": True,
            "ok": False,
        }
        try:
            text = fetch_official_text(url)
            row["ok"] = validate_gf_sivers_corroboration(text)
            row["matched_sivers"] = bool(re.search(r"\bSivers\b", text, re.I))
            row["matched_globalfoundries"] = bool(re.search(r"\b(?:GlobalFoundries|GF)\b", text, re.I))
        except Exception as exc:
            row["error"] = type(exc).__name__
        attempts.append(row)
        if row["ok"]:
            break
    return {
        "official_counterparty_ok": any(row.get("ok") for row in attempts),
        "attempts": attempts,
    }


def _sive_result(document: Mapping[str, Any]) -> dict[str, Any]:
    rows = document.get("results")
    if not isinstance(rows, list):
        raise ValueError("H4 results missing")
    matches = [row for row in rows if isinstance(row, dict) and str(row.get("ticker")) == "SIVE"]
    if len(matches) != 1:
        raise ValueError("H4 must contain exactly one SIVE result")
    return matches[0]


def patch_document(document: dict[str, Any], corroboration: Mapping[str, Any]) -> dict[str, Any]:
    result = _sive_result(document)
    before_role = str((result.get("public_logic_fidelity") or {}).get("dependency_role") or "")
    if before_role in HARD_ROLES:
        raise ValueError("Refusing to retry a SIVE row that already has a hard dependency role")

    retry = dict(corroboration)
    result["h4_counterparty_retry"] = retry
    if retry.get("official_counterparty_ok"):
        successful = next(row for row in retry.get("attempts") or [] if row.get("ok"))
        url = str(successful["url"])
        existing_corr = result.setdefault("independent_corroboration", [])
        if not any(str(row.get("url") or "") == url for row in existing_corr if isinstance(row, dict)):
            existing_corr.append(dict(successful))

        graph = (result.get("public_logic_fidelity") or {}).setdefault("supply_chain_graph", [])
        edge = {
            "from": "SIVE",
            "to": "GlobalFoundries Inc.",
            "relationship": "official ecosystem collaboration",
            "evidence_url": url,
            "as_of": "2026-06-02T00:00:00Z",
            "independent": True,
            "proof_scope": "relationship_corroboration_only_not_bottleneck_proof",
        }
        if not any(
            isinstance(row, dict)
            and str(row.get("from")) == edge["from"]
            and str(row.get("to")) == edge["to"]
            and str(row.get("evidence_url")) == edge["evidence_url"]
            for row in graph
        ):
            graph.append(edge)

        result["public_logic_fidelity"]["graph_touches_focal_company"] = True
        result["independent_graph_edge_count"] = max(1, int(result.get("independent_graph_edge_count") or 0))

    after_role = str((result.get("public_logic_fidelity") or {}).get("dependency_role") or "")
    if after_role != before_role:
        raise ValueError("Counterparty retry is not allowed to change dependency_role")
    if after_role in HARD_ROLES:
        raise ValueError("Counterparty retry created a hard dependency role")

    summary = document.setdefault("summary", {})
    summary["independent_graph_edge_count"] = sum(
        int(row.get("independent_graph_edge_count") or 0)
        for row in document.get("results") or []
        if isinstance(row, dict)
    )
    summary["production_ranking_changed"] = False
    document["h4_counterparty_retry_applied"] = True
    return document


def self_test() -> None:
    good = (
        "GlobalFoundries silicon photonics. Sivers & GlobalFoundries Advance AI Data Center "
        "Optical Solutions. The collaboration supports SCALE optical engines."
    )
    bad = "GlobalFoundries silicon photonics supports CPO and many ecosystem partners."
    assert validate_gf_sivers_corroboration(good)
    assert not validate_gf_sivers_corroboration(bad)

    doc = {
        "summary": {"production_ranking_changed": False},
        "results": [{
            "ticker": "SIVE",
            "independent_graph_edge_count": 0,
            "independent_corroboration": [],
            "public_logic_fidelity": {
                "dependency_role": "BENEFICIARY",
                "supply_chain_graph": [],
                "graph_touches_focal_company": False,
            },
        }],
    }
    corr = {
        "official_counterparty_ok": True,
        "attempts": [{
            "counterparty": "GlobalFoundries Inc.",
            "url": GF_OFFICIAL_URLS[0],
            "relationship": "official ecosystem collaboration",
            "independent": True,
            "official_counterparty": True,
            "ok": True,
        }],
    }
    patched = patch_document(doc, corr)
    sive = _sive_result(patched)
    assert sive["independent_graph_edge_count"] == 1
    assert sive["public_logic_fidelity"]["dependency_role"] == "BENEFICIARY"
    assert patched["summary"]["independent_graph_edge_count"] == 1
    print("V213_H4_COUNTERPARTY_RETRY_SELF_TEST = PASS")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return 0
    if not args.input or not args.output:
        parser.error("--input and --output are required")
    document = json.loads(args.input.read_text(encoding="utf-8"))
    if str(document.get("mode")) != "h4_independent_and_non_us_shadow_only_no_production_mutation":
        raise SystemExit("Refusing non-H4 shadow input")
    corroboration = corroborate_sive_globalfoundries()
    if not corroboration["official_counterparty_ok"]:
        raise SystemExit("No independent official GlobalFoundries/Sivers corroboration obtained")
    patched = patch_document(document, corroboration)
    args.output.write_text(json.dumps(patched, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({
        "status": "PASS",
        "sive_official_counterparty_retry_ok": True,
        "independent_graph_edge_count": patched["summary"].get("independent_graph_edge_count", 0),
        "output": str(args.output),
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
