#!/usr/bin/env python3
"""Opt-in collection of official announcement and equity EOD endpoints; local only."""
from __future__ import annotations

import argparse
import json
import platform
import ssl
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable
from urllib.request import HTTPSHandler, HTTPRedirectHandler, ProxyHandler, Request, build_opener

# The hash-verified embedded Python intentionally ignores cwd/PYTHONPATH.
# Admit only this installed script directory for direct CLI execution.
sys.path.insert(0, str(Path(__file__).resolve().parent))

from adapters import AdapterError
from adapters.staged_public import parse_source_payload
from adapters.official_rss import FEEDS
from adapters.taiwan_equities import EQUITY_FEEDS
from adapters.issuer_directory import ISSUER_FEEDS
from source_observation import atomic_write_json

ENDPOINTS = {**{key: value[0] for key, value in FEEDS.items()}, **EQUITY_FEEDS, **ISSUER_FEEDS}
MAX_BYTES = 8_000_000


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError("NEWS_REDIRECT_REJECTED")


def verified_tls_context() -> ssl.SSLContext:
    # certifi is supplied by requirements-ci.txt's immutable dependency lock.
    # Add its public CA roots to system trust; never replace TLS defaults or
    # disable strict flags/hostname verification to make a source pass.
    try:
        import certifi
    except ImportError:
        raise ValueError("VERIFIED_CA_BUNDLE_UNAVAILABLE") from None
    context = ssl.create_default_context()
    context.load_verify_locations(cafile=certifi.where())
    if context.verify_mode != ssl.CERT_REQUIRED or not context.check_hostname:
        raise ValueError("TLS_VERIFICATION_REQUIRED")
    return context


def fetch_bytes(url: str) -> bytes:
    if url not in set(ENDPOINTS.values()):
        raise ValueError("UNADMITTED_FEED")
    # No environment proxy credentials, cookie jar, authorization or redirects.
    opener = build_opener(ProxyHandler({}), NoRedirect(), HTTPSHandler(context=verified_tls_context()))
    request = Request(url, headers={"User-Agent": "InvestorIntelligence-PublicRSS/1.0",
                                    "Accept": "application/json, application/rss+xml, application/xml, text/xml"})
    with opener.open(request, timeout=20) as response:
        if response.status != 200:
            raise ValueError("NEWS_HTTP_FAILURE")
        body = response.read(MAX_BYTES + 1)
    if len(body) > MAX_BYTES:
        raise ValueError("RSS_TOO_LARGE")
    return body


def collect(sources: list[str], *, transport: Callable[[str], bytes] = fetch_bytes) -> dict:
    if not sources or any(source not in ENDPOINTS for source in sources):
        raise ValueError("UNKNOWN_NEWS_SOURCE")
    items, health = [], []
    for source in dict.fromkeys(sources):
        try:
            content = transport(ENDPOINTS[source])
            retrieved = datetime.now(timezone.utc).isoformat()
            batch = parse_source_payload(source, content, content_type="application/rss+xml" if source in FEEDS else "application/json", retrieved_at=retrieved)
            items.extend({**row, "retrieved_at": batch.retrieved_at,
                          "content_sha256": batch.content_sha256} for row in batch.records)
            health.append({"source_id": source, "status": "PARTIAL" if batch.warnings else "OK",
                           "record_count": batch.record_count, "warnings": list(batch.warnings),
                           **({"records_with_close": sum(row.get("close") is not None for row in batch.records)}
                              if source in EQUITY_FEEDS else {})})
        except Exception as exc:
            # Preserve failures, never dump provider exceptions/HTML into output.
            tls_failure = isinstance(getattr(exc, "reason", exc), ssl.SSLCertVerificationError)
            health.append({"source_id": source, "status": "FAILED", "record_count": 0,
                           "failure_kind": "TLS_VERIFICATION_FAILED" if tls_failure else
                           "INVALID_PAYLOAD" if isinstance(exc, AdapterError) else "REQUEST_FAILED"})
    status = "OK" if all(row["status"] == "OK" for row in health) else "PARTIAL" if items else "FAILED"
    return {"schema_version": 1, "status": status, "mode": "LOCAL_PUBLIC_SOURCE_OBSERVATIONS",
            "runtime": {"python": platform.python_version(), "openssl": ssl.OPENSSL_VERSION,
                        "transport": "SYSTEM_PLUS_CERTIFI" if transport is fetch_bytes else "INJECTED_TEST_TRANSPORT"},
            "publication_eligible": False, "sources": health, "items": items}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fetch", action="store_true", help="explicitly authorize public network reads")
    parser.add_argument("--source", action="append", choices=tuple(ENDPOINTS))
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if not args.fetch:
        parser.error("--fetch is required; no implicit network requests")
    result = collect(args.source or list(ENDPOINTS))
    atomic_write_json(args.output, result)
    summary = [{key: value for key, value in row.items() if key != "warnings"}
               | {"warning_count": len(row.get("warnings", []))} for row in result["sources"]]
    print(json.dumps({"status": result["status"], "sources": summary, "runtime": result.get("runtime"),
                      "item_count": len(result["items"]), "publication_eligible": False}))
    return 0 if result["status"] == "OK" else 1


if __name__ == "__main__":
    raise SystemExit(main())
