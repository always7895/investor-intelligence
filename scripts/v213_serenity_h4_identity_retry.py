#!/usr/bin/env python3
"""Resilient official-primary identity retry for H4 shadow results.

Shadow-only. This adapter does not create Serenity dependency signals or modify
Production. It retries SIVE official-source identity validation with ordinary
browser headers and stable investor/regulatory pages because some issuer sites
reject the default python-requests user agent even though the pages are public.
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
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/151 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Cache-Control": "no-cache",
}
MAX_BODY = 2_500_000

SIVE_PROFILE = {
    "canonical_company_name": "Sivers Semiconductors AB",
    "exchange": "Nasdaq Stockholm",
    "official_domain": "sivers-semiconductors.com",
    "official_urls": [
        "https://www.sivers-semiconductors.com/investors/interim-reports/",
        "https://www.sivers-semiconductors.com/press/sivers-semiconductors-updates-financial-reporting-calendar/",
        "https://www.sivers-semiconductors.com/press/sivers-globalfoundries-advance-ai-data-center-optical-solutions/",
    ],
}


def visible_text(raw: str) -> str:
    text = re.sub(r"(?is)<(?:script|style|noscript).*?>.*?</(?:script|style|noscript)>", " ", raw)
    text = re.sub(r"(?s)<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", html.unescape(text)).strip()


def fetch_text(url: str, *, timeout: tuple[int, int] = (10, 35)) -> str:
    response = requests.get(url, headers=BROWSER_HEADERS, timeout=timeout, allow_redirects=True)
    response.raise_for_status()
    raw = response.content[:MAX_BODY].decode(response.encoding or "utf-8", errors="replace")
    return visible_text(raw)


def validates_sive_identity(text: str) -> bool:
    body = str(text or "")
    company_ok = bool(re.search(r"\bSivers\s+Semiconductors(?:\s+AB)?\b", body, re.I))
    market_ok = bool(re.search(r"\b(?:Nasdaq\s+Stockholm|STO\s*:\s*SIVE|SIVE\s*:\s*ST)\b", body, re.I))
    return company_ok and market_ok


def retry_sive_identity() -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for url in SIVE_PROFILE["official_urls"]:
        row: dict[str, Any] = {"url": url, "ok": False}
        try:
            text = fetch_text(url)
            row["ok"] = validates_sive_identity(text)
            row["text_excerpt"] = text[:600] if row["ok"] else ""
            if not row["ok"]:
                row["error"] = "IDENTITY_MARKERS_NOT_FOUND"
        except Exception as exc:
            row["error"] = type(exc).__name__
        rows.append(row)
    return {
        "canonical_company_name": SIVE_PROFILE["canonical_company_name"],
        "exchange": SIVE_PROFILE["exchange"],
        "official_sources": rows,
        "official_primary_ok": any(row.get("ok") for row in rows),
        "identity_status": "PASS" if any(row.get("ok") for row in rows) else "DEGRADED",
        "validation_rule": "official Sivers domain + company identity + Nasdaq Stockholm/STO:SIVE/SIVE:ST marker",
    }


def patch_report(document: Mapping[str, Any]) -> dict[str, Any]:
    output = json.loads(json.dumps(document))
    results = output.get("results") if isinstance(output.get("results"), list) else []
    sive = next((row for row in results if isinstance(row, dict) and str(row.get("ticker") or "") == "SIVE"), None)
    if sive is None:
        raise ValueError("SIVE result is missing from H4 report")
    identity = sive.get("identity_verification") if isinstance(sive.get("identity_verification"), dict) else {}
    retry = retry_sive_identity()
    identity["official_primary_retry"] = retry
    if retry["official_primary_ok"]:
        identity["canonical_company_name"] = retry["canonical_company_name"]
        identity["exchange"] = retry["exchange"]
        identity["official_primary_ok"] = True
        identity["identity_status"] = "PASS"
    sive["identity_verification"] = identity
    output.setdefault("summary", {})["sive_official_primary_retry_ok"] = bool(retry["official_primary_ok"])
    output["h4_identity_retry_shadow_only"] = True
    return output


def atomic_write(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(path)


def self_test() -> None:
    assert validates_sive_identity("Sivers Semiconductors AB (STO:SIVE) reports results")
    assert validates_sive_identity("Sivers Semiconductors will publish before trading on Nasdaq Stockholm")
    assert validates_sive_identity("Sivers Semiconductors ... (SIVE:ST)")
    assert not validates_sive_identity("Sivers Semiconductors provides photonics solutions")
    assert not validates_sive_identity("Nasdaq Stockholm lists many technology companies")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        print(json.dumps({"status": "PASS", "adapter": "h4_sive_official_primary_identity_retry"}))
        return 0
    if not args.input or not args.output:
        parser.error("--input and --output are required unless --self-test is used")
    document = json.loads(args.input.read_text(encoding="utf-8-sig"))
    patched = patch_report(document)
    atomic_write(args.output, patched)
    print(json.dumps({
        "status": "PASS",
        "sive_official_primary_retry_ok": bool((patched.get("summary") or {}).get("sive_official_primary_retry_ok")),
        "output": str(args.output),
    }))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
