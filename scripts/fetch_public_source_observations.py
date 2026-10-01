#!/usr/bin/env python3
"""Local public observations; daily options require explicit --source opt-in."""
from __future__ import annotations

import argparse
import json
import platform
import socket
import ssl
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, NamedTuple, Sequence
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPSHandler, HTTPRedirectHandler, ProxyHandler, Request, build_opener

# The hash-verified embedded Python intentionally ignores cwd/PYTHONPATH.
# Admit only this installed script directory for direct CLI execution.
sys.path.insert(0, str(Path(__file__).resolve().parent))

from adapters import AdapterError
from adapters.base import FetchReceipt, mint_fetch_receipt
from adapters.staged_public import parse_source_payload
from adapters.official_rss import FEEDS
from adapters.taiwan_equities import EQUITY_FEEDS
from adapters.issuer_directory import ISSUER_FEEDS
from adapters.taifex_options_eod import TAIFEX_EOD_FEEDS
from adapters.ecb_fx_reference import ECBFxReferenceAdapter
from source_observation import atomic_write_json

ENDPOINTS = {**{key: value[0] for key, value in FEEDS.items()}, **EQUITY_FEEDS, **ISSUER_FEEDS}
DEFAULT_SOURCES = tuple(ENDPOINTS)  # Preserve existing default collection; no implicit options activation.
ENDPOINTS = {**ENDPOINTS, **TAIFEX_EOD_FEEDS}
ACQUISITION_ONLY_ENDPOINTS = {
    ECBFxReferenceAdapter.source_id: ECBFxReferenceAdapter.REQUEST_URL,
}
MAX_BYTES = 8_000_000


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError("NEWS_REDIRECT_REJECTED")


REDIRECT_MARKER = "NEWS_REDIRECT_REJECTED"
TLS_EXCEPTIONS = (ssl.SSLCertVerificationError, ssl.CertificateError, ssl.SSLError)
DNS_EXCEPTIONS = (socket.gaierror, socket.herror)
TIMEOUT_EXCEPTIONS = (TimeoutError, socket.timeout)
CONNECTION_EXCEPTIONS = (ConnectionError, ConnectionRefusedError, ConnectionResetError, BrokenPipeError)


class TransportDiagnostic(NamedTuple):
    failure_kind: str
    failure_code: str
    http_status: int | None = None


def _extract_http_status(err: HTTPError) -> int | None:
    for attr in ("code", "status"):
        val = getattr(err, attr, None)
        if type(val) is int and 100 <= val <= 599:
            return val
    return None


def _unwrap_exception_chain(exc: BaseException) -> list[BaseException]:
    chain: list[BaseException] = []
    if not isinstance(exc, BaseException):
        return chain
    visited: set[int] = set()
    queue: list[BaseException] = [exc]
    while queue and len(chain) < 8:
        node = queue.pop(0)
        if id(node) in visited:
            continue
        visited.add(id(node))
        chain.append(node)
        if len(chain) >= 8:
            break
        if isinstance(node, URLError) and isinstance(node.reason, BaseException) and id(node.reason) not in visited:
            queue.append(node.reason)
        cause = getattr(node, "__cause__", None)
        if isinstance(cause, BaseException) and id(cause) not in visited:
            queue.append(cause)
    return chain


def diagnose_transport_exception(exc: BaseException) -> TransportDiagnostic:
    if isinstance(getattr(exc, "reason", exc), ssl.SSLCertVerificationError):
        failure_kind = "TLS_VERIFICATION_FAILED"
    elif isinstance(exc, AdapterError):
        failure_kind = "INVALID_PAYLOAD"
    else:
        failure_kind = "REQUEST_FAILED"

    chain = _unwrap_exception_chain(exc)

    failure_code = "UNKNOWN_ERROR"
    http_status: int | None = None

    for node in chain:
        if isinstance(node, AdapterError):
            failure_code = "INVALID_PAYLOAD"
            break
        if isinstance(node, ValueError) and getattr(node, "args", None) == (REDIRECT_MARKER,):
            failure_code = "REDIRECT_REJECTED"
            break
        if isinstance(node, HTTPError):
            failure_code = "HTTP_ERROR"
            http_status = _extract_http_status(node)
            break
        if isinstance(node, (ssl.SSLCertVerificationError, ssl.CertificateError)):
            failure_code = "TLS_VERIFICATION_FAILED"
            break
        if isinstance(node, ssl.SSLError):
            failure_code = "TLS_ERROR"
            break
        if isinstance(node, DNS_EXCEPTIONS):
            failure_code = "DNS_RESOLUTION_FAILED"
            break
        if isinstance(node, TIMEOUT_EXCEPTIONS):
            failure_code = "TIMEOUT"
            break
        if isinstance(node, CONNECTION_EXCEPTIONS):
            failure_code = "CONNECTION_FAILED"
            break

    return TransportDiagnostic(failure_kind=failure_kind, failure_code=failure_code, http_status=http_status)


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
    if url not in set(ENDPOINTS.values()) and url not in set(ACQUISITION_ONLY_ENDPOINTS.values()):
        raise ValueError("UNADMITTED_FEED")
    headers = {"User-Agent": "InvestorIntelligence-PublicRSS/1.0",
               "Accept": "application/json, application/rss+xml, application/xml, text/xml"}
    if urlsplit(url).hostname == "www.sec.gov":
        # SEC fair access requires a declared contact; fail closed before any opener exists.
        from sec_contact_headers import sec_identity_headers
        headers.update(sec_identity_headers())
    # No environment proxy credentials, cookie jar, authorization or redirects.
    opener = build_opener(ProxyHandler({}), NoRedirect(), HTTPSHandler(context=verified_tls_context()))
    request = Request(url, headers=headers)
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
            diagnostic = diagnose_transport_exception(exc)
            health_row: dict = {
                "source_id": source,
                "status": "FAILED",
                "record_count": 0,
                "failure_kind": diagnostic.failure_kind,
                "failure_code": diagnostic.failure_code,
            }
            if diagnostic.http_status is not None:
                health_row["http_status"] = diagnostic.http_status
            health.append(health_row)
    status = "OK" if all(row["status"] == "OK" for row in health) else "PARTIAL" if items else "FAILED"
    return {"schema_version": 1, "status": status, "mode": "LOCAL_PUBLIC_SOURCE_OBSERVATIONS",
            "runtime": {"python": platform.python_version(), "openssl": ssl.OPENSSL_VERSION,
                        "transport": "SYSTEM_PLUS_CERTIFI" if transport is fetch_bytes else "INJECTED_TEST_TRANSPORT"},
            "publication_eligible": False, "sources": health, "items": items}


class ReceiptMintingTransport:
    """Additive seam in the existing fetch owner.

    Wraps an existing transport (real ``fetch_bytes`` or an injected offline
    response transport) and mints an immutable :class:`FetchReceipt` for each
    successful response from the actual response status and raw body bytes at
    the response-capture seam. The wrapped transport's bytes API and
    ``collect`` outputs are unchanged; existing network admission is
    unchanged (no ENDPOINTS expansion).
    """

    def __init__(self, inner: Callable[[str], bytes], *, source_id: str) -> None:
        self._inner = inner
        self._source_id = source_id
        self._receipts: list[FetchReceipt] = []

    def __call__(self, url: str) -> bytes:
        body = self._inner(url)
        self._receipts.append(
            mint_fetch_receipt(
                source_id=self._source_id,
                canonical_url=url,
                retrieved_at=datetime.now(timezone.utc).isoformat(),
                http_status=200,
                body=body,
                transport_metadata={"capture": "response_seam", "opener": type(self._inner).__name__},
            )
        )
        return body

    def receipts(self) -> tuple[FetchReceipt, ...]:
        return tuple(self._receipts)


def receipt_for_observation(
    row: Mapping[str, Any],
    receipts: Sequence[FetchReceipt],
) -> FetchReceipt:
    """Select the minted receipt that binds one collected observation row
    (source pair + exact raw-body hash). Missing receipt fails closed."""
    for receipt in receipts:
        if (
            receipt.source_id == row.get("source_id")
            and receipt.canonical_url == row.get("source_request_url")
            and receipt.content_sha256 == row.get("content_sha256")
        ):
            return receipt
    raise AdapterError("no minted fetch receipt binds this observation row")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fetch", action="store_true", help="explicitly authorize public network reads")
    parser.add_argument("--source", action="append", choices=tuple(ENDPOINTS))
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if not args.fetch:
        parser.error("--fetch is required; no implicit network requests")
    result = collect(args.source or list(DEFAULT_SOURCES))
    atomic_write_json(args.output, result)
    summary = [{key: value for key, value in row.items() if key != "warnings"}
               | {"warning_count": len(row.get("warnings", []))} for row in result["sources"]]
    print(json.dumps({"status": result["status"], "sources": summary, "runtime": result.get("runtime"),
                      "item_count": len(result["items"]), "publication_eligible": False}))
    return 0 if result["status"] == "OK" else 1


if __name__ == "__main__":
    raise SystemExit(main())
