"""Revenue guidance registry, fiscal quarter forward model, and valuation sensitivity for Top20 v3
(Astra contract ORDERS-V3-01; operator 2026-09-27; Astra staleness amendment 2026-09-28; release-check-cache-spec).

Tile 2 heading: 訂單認列／營收推估
Tile 3 heading: 營收實現後股價情境

This module is authoritative for:
1. Loading and validating config/revenue-guidance-v1.json (registry schema, document provenance, sha256 digests).
2. Four-fiscal-quarter forward model anchored at latest reported quarter end A:
   - Quarter guidance only: f1 = G, f2 = f3 = f4 = G (持平於公司財測)
   - FY guidance: R = FY - YTD over remaining n quarters, f1..fn = R/n, then flat at fn
   - Concurrent quarter + FY guidance: f1 = G, f2..fn = (R-G)/(n-1), then flat at fn
   - Quarterly consensus adapter: f1 = C1, f2 = C2, f3 = f4 = C2 (or f1 only: f1..f4 = C1)
3. Freshness and post-quarter-end bridge (Astra amendment & release-check-cache-spec):
   - Latest-release receipt age <= 24 hours at cutoff C, covering IR and regulatory channels.
   - Guidance publication age <= 200 days at cutoff C.
   - Date-only publication: published_date < cutoff_day (if equal, requires exact published_at <= cutoff).
   - For each ended, unreported quarter after A used by the path (UTC_date(C) > quarter.end):
     require UTC_date(C) <= quarter.end + 70 calendar days.
     Day +70 is eligible; day +71 is STALE.
     Eligible quarters generate mandatory warning wording:
     Quarter path: 財測季度已於{end}結束，實際營收尚未公布；截至{checked_at}查核；仍為財測／模型，非實績
     FY path: 全年財測推算季度已於{end}結束，實際營收尚未公布；截至{checked_at}查核；仍為財測／模型，非實績
4. Arithmetic:
   B = a1 + a2 + a3 + a4
   amount6 = f1 + f2, amount12 = f1 + f2 + f3 + f4
   TTM6 = a3 + a4 + f1 + f2, TTM12 = f1 + f2 + f3 + f4
   change6 = TTM6 / B - 1, change12 = TTM12 / B - 1
   Numeric tolerance: abs(a - b) <= 1e-9 * max(1, abs(a), abs(b))
"""
from __future__ import annotations

import hashlib
import json
import math
import re
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
REGISTRY_PATH = ROOT / "config" / "revenue-guidance-v1.json"
APPROVAL_PATH = ROOT / "config" / "revenue-guidance-approval-v1.json"
RELEASE_CHECKS_CACHE_PATH = ROOT / "data" / "cache" / "revenue_guidance_release_checks.json"

SCHEMA = "revenue-guidance-v1"
VERSION = 1
RELEASE_CHECKS_SCHEMA = "revenue-guidance-release-checks-v1"
# A1 (Astra acceptance r7): the enforced reviewed profile beside the registry. The registry bytes and every record
# must hash to the approval's digests; every used input (claim, actual, calendar, FY reconciliation, reaffirmation,
# routing) needs a review decision at or before the build cutoff and at or after the retrieval of the document it
# covers. Anything else suspends the issuer's revenue path as UNAVAILABLE / INVALID with the distinct
# UNREVIEWED_INPUTS diagnostic; independent order recognition is never affected.
APPROVAL_SCHEMA = "revenue-guidance-approval-v1"
APPROVAL_DECISION_KINDS = ("CLAIM", "ACTUAL", "CALENDAR", "FY_RECONCILIATION", "REAFFIRMATION", "ROUTING")
APPROVAL_DECISION_VALUES = (
    "VERBATIM_IN_SOURCE", "VALUE_IN_SOURCE", "DERIVATION_OPERANDS_IN_SOURCE", "RULE_QUOTED", "NONDISCLOSURE_CONFIRMED",
)
MAX_APPROVAL_RECORDS = 64
MAX_APPROVAL_DECISIONS = 32
MAX_APPROVAL_REF = 120

SOURCE_KINDS = (
    "SEC_PERIODIC",
    "SEC_8K_EXHIBIT",
    "SEC_6K_EXHIBIT",
    "ISSUER_EARNINGS_RELEASE",
    "ISSUER_TRANSCRIPT",
    "ISSUER_PRESENTATION",
    "OFFICIAL_FISCAL_CALENDAR",
    "OFFICIAL_FINANCIAL_STATEMENT",
)
CURRENCIES = ("USD", "KRW", "TWD", "SEK", "JPY", "EUR", "GBP", "HKD", "CNY")
ACCOUNTING_BASES = ("GAAP", "NON_GAAP", "IFRS", "K-IFRS")
MULTIPLIERS = (1, 1_000, 1_000_000, 1_000_000_000)
STATUSES = (
    "GUIDANCE",
    "NOT_DISCLOSED",
    "INPUTS_MISSING",
    "STALE",
    "CONFLICTING_DISCLOSURES",
    "WITHDRAWN",
    "INVALID",
)

REASONS_V3 = {
    "NOT_DISCLOSED",
    "INPUTS_MISSING",
    "STALE",
    "WITHDRAWN",
    "CONFLICTING_DISCLOSURES",
    "INVALID",
    "NO_REVENUE_HISTORY",
    "NO_REVENUE_BASIS",
    "FRESHNESS_UNVERIFIED",
    "SAMPLE_INSUFFICIENT",
    "PERIOD_MISMATCH",
    "EVIDENCE_LIMIT",
}

MAX_DOCUMENTS_PER_ISSUER = 16
MAX_CLAIMS_PER_ISSUER = 8
MAX_ACTUALS_PER_ISSUER = 8
MAX_FORWARD_INTERVALS = 4
MAX_CONSENSUS_QUARTERS = 2
MAX_PASSAGE = 1000
MAX_URL = 400
MAX_DOC_BYTES = 50 * 1024 * 1024
MAX_GUIDANCE_AGE_DAYS = 200
RECEIPT_MAX_AGE_HOURS = 24
QUARTER_END_BRIDGE_DAYS = 70
REL_TOL = 1e-9

ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,119}$")
SYMBOL_RE = re.compile(r"^[A-Z0-9][A-Z0-9.\-]{0,19}$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
DAY_RE = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$")
INSTANT_RE = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$")
HOST_PATTERN = r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)*\.[a-z]{2,63}"
URL_RE = re.compile(r"^https://" + HOST_PATTERN + r"/[\x21-\x7e]*$")
WIRE_ITEM_RE = re.compile(r"^https://www\.nasdaq\.com/press-release/[A-Za-z0-9._~%-]+$")
PREFIX_RE = re.compile(r"^https://" + HOST_PATTERN + r"/(?:[A-Za-z0-9._~-]+/)*$")
FORBIDDEN_CHARS = re.compile(r"[\x00-\x1f\x7f-\x9f\u180e\u200b-\u200f\u2028-\u202e\u2060-\u206f\ufeff\ud800-\udfff]")
SPACES = re.compile(r"[ \u00a0\u1680\u2000-\u200a\u202f\u205f\u3000]")

MIN_YEAR, MAX_YEAR = 1990, 2100


class GuidanceError(ValueError):
    """The revenue guidance registry or record is malformed."""


def _fail(msg: str) -> None:
    raise GuidanceError(msg)


def is_finite_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def close(a: Any, b: Any, rel_tol: float = REL_TOL) -> bool:
    if not (isinstance(a, (int, float)) and isinstance(b, (int, float))):
        return False
    if type(a) is bool or type(b) is bool:
        return False
    if not (math.isfinite(a) and math.isfinite(b)):
        return False
    return abs(a - b) <= rel_tol * max(1.0, abs(a), abs(b))


def day_after(d_str: str | date) -> str:
    d = date.fromisoformat(str(d_str)) if isinstance(d_str, str) else d_str
    return str(d + timedelta(days=1))


def _canonicalize_for_json(val: Any) -> Any:
    if val is None or isinstance(val, (bool, str, int)):
        return val
    if isinstance(val, float):
        if not math.isfinite(val):
            raise ValueError(f"Non-finite number {val}")
        if val.is_integer():
            return int(val)
        return val
    if isinstance(val, (list, tuple)):
        return [_canonicalize_for_json(x) for x in val]
    if isinstance(val, (dict, Mapping)):
        return {str(k): _canonicalize_for_json(v) for k, v in sorted(val.items())}
    raise TypeError(f"Unsupported canonical JSON type: {type(val)}")


def canonical_json(obj: Any) -> str:
    """Canonical JSON encoding: keys recursively sorted, UTF-8 characters preserved, canonical numbers."""
    canon_obj = _canonicalize_for_json(obj)
    return json.dumps(canon_obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def parse_day(value: Any) -> date | None:
    if not isinstance(value, str) or not DAY_RE.match(value) or not MIN_YEAR <= int(value[:4]) <= MAX_YEAR:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def parse_instant(value: Any) -> datetime | None:
    if not isinstance(value, str) or not INSTANT_RE.match(value) or not MIN_YEAR <= int(value[:4]) <= MAX_YEAR:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def clean_text(value: Any, max_len: int) -> str | None:
    if not isinstance(value, str) or len(value) > max_len or FORBIDDEN_CHARS.search(value):
        return None
    cleaned = SPACES.sub(" ", value).strip()
    return cleaned if cleaned else None


def validate_url(url: Any, prefixes: list[str]) -> bool:
    if not isinstance(url, str) or len(url) > MAX_URL or not URL_RE.match(url) or "#" in url or "\\" in url:
        return False
    path = url[8:].split("/", 1)[1].split("?")[0] if "/" in url[8:] else ""
    if any(segment in (".", "..") for segment in path.split("/")) or f"/{path}".find("//") != -1:
        return False
    if any(code in url.lower() for code in ("%2e", "%2f", "%5c")):
        return False
    return any(url.startswith(prefix) for prefix in prefixes)


ALLOWED_RECEIPT_KEYS = {
    "issuer", "checked_at", "status", "guidance_document_id", "guidance_published_date",
    "anchor_end", "coverage", "channels", "later_documents", "digest"
}
ALLOWED_CHANNEL_KEYS = {"kind", "url", "status", "checked_through", "complete"}
ALLOWED_LATER_DOC_KEYS = {"channel", "date", "id", "label", "disposition"}


def _receipt_domain(value: Any, path: str = "receipt") -> None:
    """The shared receipt canonical domain (Astra r5 item 3): receipts carry only strings, booleans, null,
    lists and objects. Out-of-domain scalars (any number, even 1e-7 whose Python/JS canonical spellings differ,
    1e-07 vs 1e-7; integral 1e21, 1e+21 vs 1e21) are refused before hashing, in both languages, so a
    Python-validated receipt can never hash differently from the Worker's."""
    if value is None or isinstance(value, (str, bool)):
        return
    if isinstance(value, (int, float)):
        raise GuidanceError(f"RECEIPT_OUT_OF_DOMAIN_SCALAR {path}")
    if isinstance(value, (list, tuple)):
        for i, item in enumerate(value):
            _receipt_domain(item, f"{path}[{i}]")
        return
    if isinstance(value, Mapping):
        for k, v in value.items():
            _receipt_domain(v, f"{path}.{k}")
        return
    raise GuidanceError(f"RECEIPT_UNSUPPORTED_TYPE {path}")


def compute_receipt_digest(receipt: Mapping[str, Any]) -> str:
    """Compute the SHA-256 of canonical JSON of receipt without its digest field (typed receipt domain: no numbers)."""
    if not isinstance(receipt, Mapping):
        return ""
    _receipt_domain(receipt)
    obj = {str(k): v for k, v in receipt.items() if k != "digest"}
    raw = canonical_json(obj).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


VALID_RECEIPT_CHANNELS = {"SEC_SUBMISSIONS", "WIRE_PRESS_RELEASES", "ISSUER_IR"}
# The channel set a receipt must carry exactly, split by the reviewed wiring (Astra W1 ruling): the classic two
# channels without an official IR channel, plus ISSUER_IR when the registry record carries one.
CLASSIC_RECEIPT_CHANNELS = {"SEC_SUBMISSIONS", "WIRE_PRESS_RELEASES"}
VALID_LATER_DISPOSITIONS = {"RESULTS_RELEASE", "POSSIBLY_RELEVANT", "IRRELEVANT", "REVIEWED_IRRELEVANT"}
# The official IR channel kinds (scripts/issuer_ir_feeds.py); the registry's release_channels.ir binds one.
IR_CHANNEL_KINDS = ("Q4_PRESS_RELEASES", "RSS", "NEWSROOM_HTML")


def recompute_receipt_status(
    receipt: Mapping[str, Any],
    reviewed_later_documents: list[Mapping[str, Any]] | None = None,
    cutoff_day: date | None = None,
    guidance_published_date: date | None = None,
    cutoff_instant: datetime | None = None,
    expected_cik: int | None = None,
    expected_wire_symbol: str | None = None,
    expected_ir_host: str | None = None,
) -> str:
    """Recompute receipt status from channels and later_documents per release-check-cache-spec.md.

    ``expected_ir_host`` (Astra W1 ruling, astra-ir-coverage): when the issuer's reviewed registry carries an
    official IR channel, the receipt must carry the ISSUER_IR channel reading that exact host, and its coverage
    is SEC_WIRE_IR; without an IR channel the classic SEC_AND_WIRE channel set is required (a stray IR channel
    on such a receipt is unbound and fails closed)."""
    if not isinstance(receipt, Mapping):
        return "FRESHNESS_UNVERIFIED"
    for k in receipt:
        if k not in ALLOWED_RECEIPT_KEYS:
            return "FRESHNESS_UNVERIFIED"

    channels = receipt.get("channels")
    if not isinstance(channels, list) or not channels:
        return "FRESHNESS_UNVERIFIED"

    chk_at = parse_instant(receipt.get("checked_at"))
    if not chk_at:
        return "FRESHNESS_UNVERIFIED"
    if cutoff_instant and chk_at > cutoff_instant:
        return "FRESHNESS_UNVERIFIED"
    if cutoff_day and chk_at.date() > cutoff_day:
        return "FRESHNESS_UNVERIFIED"

    seen_channels: set[str] = set()
    for ch in channels:
        if not isinstance(ch, dict):
            return "FRESHNESS_UNVERIFIED"
        for k in ch:
            if k not in ALLOWED_CHANNEL_KEYS:
                return "FRESHNESS_UNVERIFIED"
        kind = ch.get("kind")
        if not isinstance(kind, str) or kind not in VALID_RECEIPT_CHANNELS or kind in seen_channels:
            return "FRESHNESS_UNVERIFIED"
        seen_channels.add(kind)
        if ch.get("status") != "OK" or type(ch.get("complete")) is not bool or ch.get("complete") is not True:
            return "FRESHNESS_UNVERIFIED"
        ct = parse_day(ch.get("checked_through"))
        if not ct:
            return "FRESHNESS_UNVERIFIED"
        # Coverage must reach the check date! Fresh checked_at cannot refresh stale coverage
        if ct < chk_at.date():
            return "FRESHNESS_UNVERIFIED"
        if cutoff_day and ct > cutoff_day:
            return "FRESHNESS_UNVERIFIED"
        if guidance_published_date and ct < guidance_published_date:
            return "FRESHNESS_UNVERIFIED"
        url = ch.get("url")
        if not isinstance(url, str) or not URL_RE.match(url):
            return "FRESHNESS_UNVERIFIED"
        if kind == "SEC_SUBMISSIONS":
            if not re.match(r"^https://data\.sec\.gov/submissions/CIK[0-9]{10}\.json$", url):
                return "FRESHNESS_UNVERIFIED"
            if expected_cik is not None and not url.endswith(f"CIK{expected_cik:010d}.json"):
                return "FRESHNESS_UNVERIFIED"
        if kind == "WIRE_PRESS_RELEASES":
            if not (url.startswith("https://api.nasdaq.com/") or url.startswith("https://www.nasdaq.com/")):
                return "FRESHNESS_UNVERIFIED"
            sym = expected_wire_symbol or str(receipt.get("issuer") or "")
            if sym and f"symbol:{sym.lower()}" not in url.lower():
                return "FRESHNESS_UNVERIFIED"
        if kind == "ISSUER_IR":
            # The IR channel must read the issuer's own official feed host, as reviewed in the registry.
            if expected_ir_host is None or urlsplit(url).netloc != expected_ir_host:
                return "FRESHNESS_UNVERIFIED"

    required_channels = CLASSIC_RECEIPT_CHANNELS | ({"ISSUER_IR"} if expected_ir_host else set())
    if seen_channels != required_channels:
        return "FRESHNESS_UNVERIFIED"

    reviewed_ids: dict[str, str] = {}
    if isinstance(reviewed_later_documents, list):
        for rld in reviewed_later_documents:
            if isinstance(rld, dict) and "id" in rld and rld.get("disposition") == "REVIEWED_IRRELEVANT":
                # reviewed_at is required, must be a valid instant and at or before cutoff
                r_at = parse_instant(rld.get("reviewed_at"))
                if r_at is None:
                    continue
                if cutoff_instant and r_at > cutoff_instant:
                    continue
                if cutoff_day and r_at.date() > cutoff_day:
                    continue
                reviewed_ids[str(rld["id"])] = "REVIEWED_IRRELEVANT"

    later_docs = receipt.get("later_documents")
    if later_docs is None:
        later_docs = []
    if not isinstance(later_docs, list):
        return "FRESHNESS_UNVERIFIED"

    has_results_release = False
    has_unreviewed_possibly_relevant = False

    for ldoc in later_docs:
        if not isinstance(ldoc, dict):
            return "FRESHNESS_UNVERIFIED"
        for k in ldoc:
            if k not in ALLOWED_LATER_DOC_KEYS:
                return "FRESHNESS_UNVERIFIED"
        l_ch = ldoc.get("channel")
        if l_ch not in VALID_RECEIPT_CHANNELS:
            return "FRESHNESS_UNVERIFIED"
        l_date = parse_day(ldoc.get("date"))
        if not l_date or (cutoff_day and l_date > cutoff_day):
            return "FRESHNESS_UNVERIFIED"
        lid = ldoc.get("id")
        if not isinstance(lid, str) or not clean_text(lid, 400):
            return "FRESHNESS_UNVERIFIED"
        disp = ldoc.get("disposition")
        if disp not in VALID_LATER_DISPOSITIONS:
            return "FRESHNESS_UNVERIFIED"

        if disp == "RESULTS_RELEASE":
            has_results_release = True
        elif disp == "POSSIBLY_RELEVANT":
            if lid not in reviewed_ids:
                has_unreviewed_possibly_relevant = True
        elif disp == "REVIEWED_IRRELEVANT":
            # Must have an authentic linked review in reviewed_later_documents
            if lid not in reviewed_ids:
                return "FRESHNESS_UNVERIFIED"

    if has_results_release:
        return "RESULTS_PUBLISHED"
    if has_unreviewed_possibly_relevant:
        return "REVIEW_REQUIRED"
    return "OK"


def guidance_reference_document_id(claim: Mapping[str, Any], docs_by_id: Mapping[str, Any]) -> str | None:
    """The document a latest-release check starts from: the claim's own document or, when the company reaffirmed the
    figure later without restating it (`reaffirmed_by`), the most recently published reaffirmation (ties keep the
    claim's own document). Releases after that date are what could revise the figure."""
    best = claim.get("document_id")
    best_day = str((docs_by_id.get(best) or {}).get("published_date") or "")
    for item in claim.get("reaffirmed_by") or []:
        doc_id = item.get("document_id") if isinstance(item, Mapping) else None
        day = str((docs_by_id.get(doc_id) or {}).get("published_date") or "")
        if doc_id in docs_by_id and day > best_day:
            best, best_day = doc_id, day
    return best


def guidance_reference(record: Mapping[str, Any]) -> dict[str, Any]:
    """The one release-check reference of a record's whole active claim set (ORDERS-V3-AUTOUPDATE-01 B0): every
    active claim's reference document (its own document, or its latest reaffirmation) must be the same document;
    distinct references are a conflict (no reference, never the first or the newest). The descriptor binds every
    active claim (period, basis, scope, numeric source digest and reference) independent of claim order. The
    release-check collector, the sealer's model gate and the auto-update admission all use this one helper."""
    docs_by_id = {d.get("id"): d for d in record.get("documents") or [] if isinstance(d, Mapping)}
    active = select_active_guidance_claims(record)
    descriptor = []
    refs = set()
    for c in active:
        ref = guidance_reference_document_id(c, docs_by_id)
        refs.add(ref)
        source = docs_by_id.get(c.get("document_id")) or {}
        descriptor.append({"id": str(c.get("id")), "period_kind": c.get("period_kind"),
                           "period_start": c.get("period_start") or c.get("start"), "period_end": c.get("period_end") or c.get("end"),
                           "scope": c.get("scope"), "accounting_basis": c.get("accounting_basis"),
                           "document_id": c.get("document_id"), "source_sha256": source.get("sha256"), "reference_document_id": ref})
    descriptor.sort(key=lambda d: (str(d["period_kind"]), str(d["period_start"]), d["id"]))
    reference = next(iter(refs)) if len(refs) == 1 else None
    if reference is not None and reference not in docs_by_id:
        reference = None
    return {"document_id": reference, "published_date": (docs_by_id.get(reference) or {}).get("published_date") if reference else None,
            "conflict": len(refs) > 1, "claims": descriptor}


def select_active_guidance_claims(record: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    """The deterministic active guidance-claim set of a reviewed record (Astra r5 items 2 and 11): the QUARTER /
    FISCAL_YEAR claims that are not superseded or withdrawn, selected independent of array order (canonical period
    fields, ties broken by claim id). The sealer (build_forward_quarters) and the release-check collector
    (receipt_for) must both start from this set, never from claims[0]."""
    claims = [c for c in record.get("claims") or [] if isinstance(c, Mapping)]
    active: list[Mapping[str, Any]] = []
    superseded: set[str] = set()
    for c in claims:
        rev = c.get("revision") or {}
        if not isinstance(rev, Mapping):
            continue
        if rev.get("kind") in ("SUPERSEDED", "WITHDRAWN", "WITHDRAWAL"):
            superseded.add(str(c.get("id")))
        for target in rev.get("targets") or []:
            if isinstance(target, str):
                superseded.add(target)
        if isinstance(rev.get("supersedes"), str):
            superseded.add(rev["supersedes"])
    for c in claims:
        if c.get("period_kind") not in ("QUARTER", "FISCAL_YEAR"):
            continue
        if str(c.get("id")) in superseded:
            continue
        if c.get("scope") not in ("COMPANY", "CONSOLIDATED"):
            continue
        active.append(c)
    return sorted(active, key=lambda c: (str(c.get("period_kind")), str(c.get("period_start") or c.get("start") or ""), str(c.get("id") or "")))


def validate_receipt(
    receipt: Mapping[str, Any],
    issuer: str,
    anchor_end: str | None,
    guidance_doc_id: str | None,
    cutoff: datetime,
    reviewed_later_documents: list[Mapping[str, Any]] | None = None,
    guidance_published_date: str | None = None,
    expected_cik: int | None = None,
    expected_wire_symbol: str | None = None,
    expected_ir: Mapping[str, Any] | None = None,
) -> tuple[bool, str, str | None]:
    """Validate a release-check receipt against the schema and sealed parameters.

    Only the runtime cache shape (release-check-cache-spec.md) is accepted:
    channels, digest, coverage, later_documents, issuer.

    ``expected_ir`` (Astra W1 ruling): the registry's official IR channel (kind + https url). When present the
    receipt must carry SEC_WIRE_IR coverage with the ISSUER_IR channel on the registry's IR host; a receipt
    without that coverage is the distinct IR_COVERAGE_MISSING diagnostic (the company-guidance path suspends).

    Returns (valid, status, error_reason).
    """
    if not isinstance(receipt, Mapping):
        return False, "FRESHNESS_UNVERIFIED", "RECEIPT_NOT_OBJECT"

    checked_at = parse_instant(receipt.get("checked_at"))
    if not checked_at or checked_at > cutoff:
        return False, "FRESHNESS_UNVERIFIED", "CHECKED_AT_FUTURE_OR_INVALID"

    receipt_age_sec = (cutoff - checked_at).total_seconds()
    if receipt_age_sec < 0 or receipt_age_sec > RECEIPT_MAX_AGE_HOURS * 3600:
        return False, "STALE", "RECEIPT_AGE_EXCEEDED"

    if receipt.get("issuer") != issuer:
        return False, "FRESHNESS_UNVERIFIED", "ISSUER_MISMATCH"

    digest = receipt.get("digest")
    if not isinstance(digest, str) or not SHA256_RE.match(digest):
        return False, "INVALID", "DIGEST_INVALID_FORMAT"

    expected_digest = compute_receipt_digest(receipt)
    if digest != expected_digest:
        return False, "INVALID", "DIGEST_MISMATCH"

    # Coverage must match the reviewed channel wiring (Astra W1 ruling): SEC_WIRE_IR exactly when the record
    # carries an official IR channel, SEC_AND_WIRE otherwise. The missing-coverage case is the distinct
    # IR_COVERAGE_MISSING diagnostic, never a generic INVALID_COVERAGE.
    if expected_ir is not None:
        if receipt.get("coverage") != "SEC_WIRE_IR":
            return False, "FRESHNESS_UNVERIFIED", "IR_COVERAGE_MISSING"
    elif receipt.get("coverage") != "SEC_AND_WIRE":
        return False, "FRESHNESS_UNVERIFIED", "INVALID_COVERAGE"

    if anchor_end and receipt.get("anchor_end") != anchor_end:
        return False, "FRESHNESS_UNVERIFIED", "ANCHOR_END_MISMATCH"

    if guidance_doc_id and receipt.get("guidance_document_id") != guidance_doc_id:
        return False, "FRESHNESS_UNVERIFIED", "GUIDANCE_DOC_ID_MISMATCH"

    pub_d = parse_day(guidance_published_date) if guidance_published_date else None
    if guidance_published_date and receipt.get("guidance_published_date") != guidance_published_date:
        return False, "FRESHNESS_UNVERIFIED", "GUIDANCE_PUB_DATE_MISMATCH"

    expected_ir_host = urlsplit(str(expected_ir.get("url"))).netloc if expected_ir is not None else None
    status = recompute_receipt_status(
        receipt,
        reviewed_later_documents,
        cutoff_day=cutoff.date(),
        guidance_published_date=pub_d,
        cutoff_instant=cutoff,
        expected_cik=expected_cik,
        expected_wire_symbol=expected_wire_symbol,
        expected_ir_host=expected_ir_host,
    )
    if receipt.get("status") != status:
        return False, "INVALID", "STATUS_RECOMPUTE_MISMATCH"

    if status == "RESULTS_PUBLISHED":
        return False, "STALE", "RESULTS_PUBLISHED"
    if status == "REVIEW_REQUIRED":
        return False, "STALE", "REVIEW_REQUIRED"
    if status == "FRESHNESS_UNVERIFIED":
        return False, "FRESHNESS_UNVERIFIED", "CHANNELS_FAILED_OR_INCOMPLETE"

    return True, status, None


def load_release_checks_cache(path: Path | None = None) -> dict[str, Any]:
    """Load runtime release-check cache (data/cache/revenue_guidance_release_checks.json)."""
    target = path or RELEASE_CHECKS_CACHE_PATH
    if not target.exists():
        return {"schema": RELEASE_CHECKS_SCHEMA, "generated_at": None, "issuers": {}}
    try:
        data = json.loads(target.read_bytes().decode("utf-8"))
        if not isinstance(data, dict) or data.get("schema") != RELEASE_CHECKS_SCHEMA:
            return {"schema": RELEASE_CHECKS_SCHEMA, "generated_at": None, "issuers": {}}
        return data
    except Exception:
        return {"schema": RELEASE_CHECKS_SCHEMA, "generated_at": None, "issuers": {}}


def load_approval(path: Path | None = None) -> dict[str, Any]:
    """Load and validate config/revenue-guidance-approval-v1.json, the enforced reviewed profile (A1).

    The approval binds the exact registry bytes (``registry_sha256``) and each used registry record
    (``record_sha256`` over the record's canonical JSON: sort_keys, separators (",", ":"), ensure_ascii=False)
    to timestamped review decisions covering every operative input: each claim (CLAIM), each reported actual
    (ACTUAL, ref = the quarter end), the fiscal calendar (CALENDAR, ref "calendar"), the FY reconciliation
    (FY_RECONCILIATION, ref "fy_reconciliation"), each reaffirmation (REAFFIRMATION, ref = the claim id) and the
    routing decision (ROUTING, ref "routing"). A pending skeleton (null registry_sha256, no records) is a valid
    file that approves nothing: every issuer then fails closed as UNREVIEWED_INPUTS. A missing file is
    UNAVAILABLE; a malformed file is INVALID. All of those suspend the revenue path, never the order view.
    """
    pending = {"status": "UNAVAILABLE", "sha256": None, "registry_sha256": None, "approved_at": None,
               "reviewer": None, "records": {}}
    target = path or APPROVAL_PATH
    if not target.exists():
        return pending
    try:
        raw = target.read_bytes()
    except OSError:
        return pending
    sha256 = hashlib.sha256(raw).hexdigest()
    try:
        data = json.loads(raw.decode("utf-8"))
    except Exception as exc:
        return {"status": "INVALID", "sha256": sha256, "error": str(exc), "registry_sha256": None, "approved_at": None,
                "reviewer": None, "records": {}}
    if not isinstance(data, dict) or set(data.keys()) != {"schema", "registry_sha256", "approved_at", "reviewer", "records"}:
        return {"status": "INVALID", "sha256": sha256, "error": "APPROVAL_KEYS", "registry_sha256": None, "approved_at": None,
                "reviewer": None, "records": {}}
    if data.get("schema") != APPROVAL_SCHEMA:
        return {"status": "INVALID", "sha256": sha256, "error": "APPROVAL_SCHEMA", "registry_sha256": None, "approved_at": None,
                "reviewer": None, "records": {}}
    reg_sha = data.get("registry_sha256")
    if reg_sha is not None and (not isinstance(reg_sha, str) or not SHA256_RE.match(reg_sha)):
        return {"status": "INVALID", "sha256": sha256, "error": "APPROVAL_REGISTRY_SHA", "registry_sha256": None, "approved_at": None,
                "reviewer": None, "records": {}}
    approved_at_raw = data.get("approved_at")
    approved_at = parse_instant(approved_at_raw)
    if approved_at_raw is not None and approved_at is None:
        return {"status": "INVALID", "sha256": sha256, "error": "APPROVAL_APPROVED_AT", "registry_sha256": None, "approved_at": None,
                "reviewer": None, "records": {}}
    reviewer = data.get("reviewer")
    if reviewer is not None and not clean_text(reviewer, 120):
        return {"status": "INVALID", "sha256": sha256, "error": "APPROVAL_REVIEWER", "registry_sha256": None, "approved_at": None,
                "reviewer": None, "records": {}}
    raw_records = data.get("records")
    if not isinstance(raw_records, dict):
        return {"status": "INVALID", "sha256": sha256, "error": "APPROVAL_RECORDS_TYPE", "registry_sha256": None, "approved_at": None,
                "reviewer": None, "records": {}}
    # A pending skeleton approves nothing: null registry identity with no records.
    if reg_sha is None:
        if approved_at is not None or reviewer is not None or raw_records:
            return {"status": "INVALID", "sha256": sha256, "error": "APPROVAL_PENDING_INCOHERENT", "registry_sha256": None, "approved_at": None,
                    "reviewer": None, "records": {}}
        return {"status": "OK", "sha256": sha256, "registry_sha256": None, "approved_at": None, "reviewer": None, "records": {}}
    if approved_at is None or reviewer is None:
        return {"status": "INVALID", "sha256": sha256, "error": "APPROVAL_PENDING_FIELDS", "registry_sha256": reg_sha, "approved_at": None,
                "reviewer": None, "records": {}}
    if len(raw_records) > MAX_APPROVAL_RECORDS:
        return {"status": "INVALID", "sha256": sha256, "error": "APPROVAL_RECORDS_LIMIT", "registry_sha256": reg_sha, "approved_at": approved_at_raw,
                "reviewer": reviewer, "records": {}}
    records: dict[str, Any] = {}
    for sym, rec in raw_records.items():
        if not isinstance(sym, str) or not SYMBOL_RE.match(sym):
            return {"status": "INVALID", "sha256": sha256, "error": f"APPROVAL_SYMBOL_{sym}", "registry_sha256": reg_sha, "approved_at": approved_at_raw,
                    "reviewer": reviewer, "records": {}}
        if not isinstance(rec, dict) or set(rec.keys()) != {"record_sha256", "decisions"}:
            return {"status": "INVALID", "sha256": sha256, "error": f"APPROVAL_RECORD_KEYS_{sym}", "registry_sha256": reg_sha, "approved_at": approved_at_raw,
                    "reviewer": reviewer, "records": {}}
        rec_sha = rec.get("record_sha256")
        if not isinstance(rec_sha, str) or not SHA256_RE.match(rec_sha):
            return {"status": "INVALID", "sha256": sha256, "error": f"APPROVAL_RECORD_SHA_{sym}", "registry_sha256": reg_sha, "approved_at": approved_at_raw,
                    "reviewer": reviewer, "records": {}}
        decisions = rec.get("decisions")
        if not isinstance(decisions, list) or not decisions or len(decisions) > MAX_APPROVAL_DECISIONS:
            return {"status": "INVALID", "sha256": sha256, "error": f"APPROVAL_DECISIONS_{sym}", "registry_sha256": reg_sha, "approved_at": approved_at_raw,
                    "reviewer": reviewer, "records": {}}
        for dec in decisions:
            if not isinstance(dec, dict) or set(dec.keys()) != {"kind", "ref", "decision", "reviewed_at"}:
                return {"status": "INVALID", "sha256": sha256, "error": f"APPROVAL_DECISION_KEYS_{sym}", "registry_sha256": reg_sha, "approved_at": approved_at_raw,
                        "reviewer": reviewer, "records": {}}
            if dec["kind"] not in APPROVAL_DECISION_KINDS or dec["decision"] not in APPROVAL_DECISION_VALUES:
                return {"status": "INVALID", "sha256": sha256, "error": f"APPROVAL_DECISION_ENUM_{sym}", "registry_sha256": reg_sha, "approved_at": approved_at_raw,
                        "reviewer": reviewer, "records": {}}
            if not isinstance(dec["ref"], str) or not (1 <= len(dec["ref"]) <= MAX_APPROVAL_REF) or FORBIDDEN_CHARS.search(dec["ref"]):
                return {"status": "INVALID", "sha256": sha256, "error": f"APPROVAL_DECISION_REF_{sym}", "registry_sha256": reg_sha, "approved_at": approved_at_raw,
                        "reviewer": reviewer, "records": {}}
            if parse_instant(dec["reviewed_at"]) is None:
                return {"status": "INVALID", "sha256": sha256, "error": f"APPROVAL_DECISION_TIME_{sym}", "registry_sha256": reg_sha, "approved_at": approved_at_raw,
                        "reviewer": reviewer, "records": {}}
        records[sym] = {"record_sha256": rec_sha, "decisions": [dict(d) for d in decisions]}
    return {"status": "OK", "sha256": sha256, "registry_sha256": reg_sha, "approved_at": approved_at_raw, "reviewer": reviewer, "records": records}


def check_reviewed_profile(
    issuer: str,
    record: Mapping[str, Any] | None,
    approval: Mapping[str, Any] | None,
    registry_sha256: str | None,
    cutoff: datetime,
) -> str | None:
    """The A1 admission boundary for one issuer's revenue path. Returns None when the record's inputs are
    covered by an enforced reviewed profile, else the UNREVIEWED_INPUTS failure code (the reason stays INVALID,
    never AVAILABLE). Every failure mode is distinct: a missing/malformed approval, a changed registry, a changed
    record, a missing decision, or a time incoherence (an approval or review later than the build cutoff, or
    earlier than the retrieval of the document it covers)."""
    if not isinstance(approval, Mapping) or approval.get("status") != "OK":
        return "APPROVAL_UNAVAILABLE"
    if approval.get("registry_sha256") is None:
        return "APPROVAL_PENDING"
    if approval.get("registry_sha256") != registry_sha256:
        return "REGISTRY_CHANGED"
    rec = (approval.get("records") or {}).get(issuer)
    if not isinstance(rec, Mapping):
        return "RECORD_NOT_APPROVED"
    try:
        record_digest = hashlib.sha256(canonical_json(record).encode("utf-8")).hexdigest()
    except (GuidanceError, TypeError, ValueError):
        return "RECORD_CANONICALIZED_FAILED"
    if record_digest != rec.get("record_sha256"):
        return "RECORD_CHANGED"
    approved_at = parse_instant(approval.get("approved_at"))
    if approved_at is None or approved_at > cutoff:
        return "APPROVAL_TIME_INCOHERENT"

    docs = [d for d in record.get("documents", []) if isinstance(d, Mapping)]
    doc_by_id: dict[str, Mapping[str, Any]] = {}
    max_retrieved: datetime | None = None
    for doc in docs:
        retrieved = parse_instant(doc.get("retrieved_at"))
        if retrieved is None:
            return "RECORD_RETRIEVAL_MALFORMED"
        doc_by_id[str(doc.get("id"))] = doc
        max_retrieved = retrieved if max_retrieved is None or retrieved > max_retrieved else max_retrieved
    if max_retrieved is not None and approved_at < max_retrieved:
        return "APPROVAL_BEFORE_RETRIEVAL"

    decisions = rec.get("decisions")
    if not isinstance(decisions, list) or not decisions:
        return "DECISIONS_MISSING"
    seen: dict[str, set[str]] = {}
    decision_times: list[tuple[str, str, datetime]] = []
    for dec in decisions:
        if not isinstance(dec, Mapping) or dec.get("kind") not in APPROVAL_DECISION_KINDS \
                or dec.get("decision") not in APPROVAL_DECISION_VALUES:
            return "DECISION_MALFORMED"
        ref = dec.get("ref")
        if not isinstance(ref, str) or not (1 <= len(ref) <= MAX_APPROVAL_REF):
            return "DECISION_MALFORMED"
        reviewed_at = parse_instant(dec.get("reviewed_at"))
        if reviewed_at is None or reviewed_at > cutoff:
            return "DECISION_TIME_INCOHERENT"
        seen.setdefault(str(dec["kind"]), set()).add(ref)
        decision_times.append((str(dec["kind"]), ref, reviewed_at))

    def lower_bound(kind: str, ref: str) -> datetime | None:
        """The retrieval of the document a decision covers (the record-wide maximum where it covers all)."""
        if kind == "CLAIM":
            claim = next((c for c in record.get("claims", []) if isinstance(c, Mapping) and str(c.get("id")) == ref), None)
            doc = doc_by_id.get(str((claim or {}).get("document_id"))) if claim else None
            return parse_instant(doc.get("retrieved_at")) if doc else max_retrieved
        if kind == "ACTUAL":
            actual = next((q for q in record.get("reported_quarters", [])
                           if isinstance(q, Mapping) and str(q.get("end")) == ref), None)
            doc = doc_by_id.get(str((actual or {}).get("document_id"))) if actual else None
            return parse_instant(doc.get("retrieved_at")) if doc else max_retrieved
        if kind == "REAFFIRMATION":
            claim = next((c for c in record.get("claims", []) if isinstance(c, Mapping) and str(c.get("id")) == ref), None)
            bounds = []
            for item in (claim or {}).get("reaffirmed_by") or []:
                doc = doc_by_id.get(str((item or {}).get("document_id"))) if isinstance(item, Mapping) else None
                if doc is not None:
                    bounds.append(parse_instant(doc.get("retrieved_at")))
            return max([b for b in bounds if b is not None], default=max_retrieved)
        if kind == "CALENDAR":
            bounds = []
            for intv in record.get("forward_intervals", []):
                doc = doc_by_id.get(str(intv.get("calendar_document_id"))) if isinstance(intv, Mapping) else None
                if doc is not None:
                    bounds.append(parse_instant(doc.get("retrieved_at")))
            return max([b for b in bounds if b is not None], default=max_retrieved)
        return max_retrieved  # FY_RECONCILIATION and ROUTING cover the record's whole reviewed set

    for dec in decisions:
        reviewed_at = parse_instant(dec["reviewed_at"])  # type: ignore[index]
        floor = lower_bound(str(dec["kind"]), str(dec["ref"]))
        if floor is not None and reviewed_at < floor:
            return "DECISION_BEFORE_RETRIEVAL"

    claims = [c for c in record.get("claims", []) if isinstance(c, Mapping)]
    for claim in claims:
        cid = str(claim.get("id"))
        if cid not in seen.get("CLAIM", set()):
            return "CLAIM_DECISION_MISSING"
        if claim.get("reaffirmed_by") and cid not in seen.get("REAFFIRMATION", set()):
            return "REAFFIRMATION_DECISION_MISSING"
    for actual in record.get("reported_quarters", []):
        if isinstance(actual, Mapping) and str(actual.get("end")) not in seen.get("ACTUAL", set()):
            return "ACTUAL_DECISION_MISSING"
    if "calendar" not in seen.get("CALENDAR", set()):
        return "CALENDAR_DECISION_MISSING"
    if isinstance(record.get("fy_reconciliation"), Mapping) and "fy_reconciliation" not in seen.get("FY_RECONCILIATION", set()):
        return "FY_DECISION_MISSING"
    if "routing" not in seen.get("ROUTING", set()):
        return "ROUTING_DECISION_MISSING"
    return None


def select_latest_release_receipt(
    issuer: str,
    cache: Mapping[str, Any] | None,
    cutoff: datetime,
) -> dict[str, Any] | None:
    """Select per issuer the newest receipt with checked_at <= cutoff."""
    if not cache or not isinstance(cache, Mapping):
        return None
    issuers = cache.get("issuers", {})
    if not isinstance(issuers, Mapping):
        return None
    receipts = issuers.get(issuer)
    if not isinstance(receipts, list) or not receipts:
        return None

    at_or_before = []
    for r in receipts:
        if isinstance(r, dict):
            chk = parse_instant(r.get("checked_at"))
            if chk and chk <= cutoff:
                at_or_before.append((chk, r))

    if not at_or_before:
        return None
    at_or_before.sort(key=lambda pair: pair[0], reverse=True)
    return at_or_before[0][1]


def compute_model_point(claim: Mapping[str, Any]) -> tuple[float, str]:
    """Derive model_point and its derivation method from a guidance claim."""
    multiplier = claim.get("unit_multiplier", 1)
    if not isinstance(multiplier, (int, float)) or isinstance(multiplier, bool) or multiplier not in MULTIPLIERS:
        _fail("INVALID_MULTIPLIER")

    # If numeric fields are present, they must be finite numbers (not boolean, not string, not nan/inf)
    for k in ("low", "high", "stated_point", "amount", "plus_minus_amount", "plus_minus_percent"):
        if k in claim and claim[k] is not None:
            if not is_finite_number(claim[k]):
                _fail(f"INVALID_NUMERIC_FIELD {k}={claim[k]}")

    orig_rep = claim.get("original_representation")
    if orig_rep in ("GREATER_THAN", "LESS_THAN"):
        _fail(f"ONE_SIDED_GUIDANCE_NOT_ALLOWED {orig_rep}")

    low, high = claim.get("low"), claim.get("high")
    stated_point = claim.get("stated_point")
    pm_amount = claim.get("plus_minus_amount")
    pm_pct = claim.get("plus_minus_percent")

    low_val = float(low) * multiplier if low is not None else None
    high_val = float(high) * multiplier if high is not None else None
    stated_val = float(stated_point) * multiplier if stated_point is not None else None

    if orig_rep == "PLUS_MINUS_AMOUNT" or pm_amount is not None:
        if stated_val is None or pm_amount is None:
            _fail("PLUS_MINUS_AMOUNT_REQUIRES_STATED_AND_AMOUNT")
        pm_val = float(pm_amount) * multiplier
        if pm_val < 0 or stated_val - pm_val < 0:
            _fail(f"INVALID_PLUS_MINUS_BOUNDS stated={stated_val} pm={pm_val}")
        if low_val is not None and not close(low_val, stated_val - pm_val):
            _fail(f"PLUS_MINUS_AMOUNT_LOW_MISMATCH low={low_val} expected={stated_val - pm_val}")
        if high_val is not None and not close(high_val, stated_val + pm_val):
            _fail(f"PLUS_MINUS_AMOUNT_HIGH_MISMATCH high={high_val} expected={stated_val + pm_val}")
        return stated_val, "STATED_POINT"

    if orig_rep == "PLUS_MINUS_PERCENT" or pm_pct is not None:
        if stated_val is None or pm_pct is None:
            _fail("PLUS_MINUS_PERCENT_REQUIRES_STATED_AND_PERCENT")
        pct_val = float(pm_pct)
        if pct_val < 0 or stated_val * (1.0 - pct_val / 100.0) < 0:
            _fail(f"INVALID_PLUS_MINUS_PERCENT_BOUNDS stated={stated_val} pct={pct_val}")
        if low_val is not None and not close(low_val, stated_val * (1.0 - pct_val / 100.0)):
            _fail(f"PLUS_MINUS_PERCENT_LOW_MISMATCH low={low_val} expected={stated_val * (1.0 - pct_val / 100.0)}")
        if high_val is not None and not close(high_val, stated_val * (1.0 + pct_val / 100.0)):
            _fail(f"PLUS_MINUS_PERCENT_HIGH_MISMATCH high={high_val} expected={stated_val * (1.0 + pct_val / 100.0)}")
        return stated_val, "STATED_POINT"

    # Stated range: low and high both present
    if low_val is not None and high_val is not None:
        if low_val < 0 or high_val < 0:
            _fail(f"NEGATIVE_RANGE low={low_val}, high={high_val}")
        if low_val > high_val:
            _fail(f"RANGE_INVERTED low={low_val} > high={high_val}")
        if stated_val is not None:
            if stated_val < low_val or stated_val > high_val:
                _fail(f"STATED_POINT_OUT_OF_RANGE stated={stated_val}, low={low_val}, high={high_val}")
            return stated_val, "STATED_POINT"
        return (low_val + high_val) / 2.0, "MIDPOINT"

    # Stated point only
    if stated_val is not None:
        if stated_val < 0:
            _fail(f"NEGATIVE_STATED_POINT {stated_val}")
        return stated_val, "POINT_ONLY"

    amount = claim.get("amount")
    if amount is not None:
        amt_val = float(amount) * multiplier
        if amt_val < 0:
            _fail(f"NEGATIVE_AMOUNT {amt_val}")
        return amt_val, "POINT_ONLY"

    _fail(f"UNQUANTIFIED_GUIDANCE_CLAIM {claim.get('id')}")


def load_registry(path: Path | None = None) -> dict[str, Any]:
    """Load and validate config/revenue-guidance-v1.json. Returns a registry dictionary."""
    target_path = path or REGISTRY_PATH
    if not target_path.exists():
        return {"status": "UNAVAILABLE", "sha256": None, "issuers": {}}

    raw_bytes = target_path.read_bytes()
    sha256 = hashlib.sha256(raw_bytes).hexdigest()
    try:
        data = json.loads(raw_bytes.decode("utf-8"))
    except Exception as exc:
        return {"status": "INVALID", "sha256": sha256, "error": str(exc), "issuers": {}}

    if not isinstance(data, dict):
        return {"status": "INVALID", "sha256": sha256, "error": "ROOT_NOT_DICT", "issuers": {}}

    if data.get("schema") != SCHEMA:
        return {"status": "INVALID", "sha256": sha256, "error": "SCHEMA_MISMATCH", "issuers": {}}

    ver = data.get("version")
    if type(ver) is not int or ver != VERSION:
        return {"status": "INVALID", "sha256": sha256, "error": "VERSION_MISMATCH", "issuers": {}}

    allowed_root_keys = {"schema", "version", "issuers", "notes", "generated_at", "as_of", "consensus_enabled"}
    if not set(data.keys()).issubset(allowed_root_keys):
        return {"status": "INVALID", "sha256": sha256, "error": "UNEXPECTED_ROOT_KEYS", "issuers": {}}

    # A3/A6 (Astra acceptance r7): the registry root's explicit consensus gate. A missing flag fails closed to
    # disabled: the first rollout defers the Korean analyst-consensus path (ORDERS-V3-CONSENSUS-01) and build_v3
    # never routes to it, with the CONSENSUS_DEFERRED diagnostic on the NOT_DISCLOSED records.
    consensus_enabled = data.get("consensus_enabled", False)
    if type(consensus_enabled) is not bool:
        return {"status": "INVALID", "sha256": sha256, "error": "INVALID_CONSENSUS_ENABLED", "issuers": {}}

    raw_issuers = data.get("issuers")
    issuers_map: dict[str, dict[str, Any]] = {}

    if isinstance(raw_issuers, list):
        seen_symbols = set()
        for rec in raw_issuers:
            if not isinstance(rec, dict) or "symbol" not in rec:
                return {"status": "INVALID", "sha256": sha256, "error": "MALFORMED_ISSUER_ITEM", "issuers": {}}
            sym = rec["symbol"]
            if not isinstance(sym, str) or not SYMBOL_RE.match(sym):
                return {"status": "INVALID", "sha256": sha256, "error": f"INVALID_SYMBOL_TYPE_{sym}", "issuers": {}}
            if sym in seen_symbols:
                return {"status": "INVALID", "sha256": sha256, "error": f"DUPLICATE_SYMBOL_{sym}", "issuers": {}}
            seen_symbols.add(sym)
            issuers_map[sym] = rec
    elif isinstance(raw_issuers, dict):
        for sym, rec in raw_issuers.items():
            if not isinstance(rec, dict) or rec.get("symbol") != sym:
                return {"status": "INVALID", "sha256": sha256, "error": f"KEY_SYMBOL_MISMATCH_{sym}", "issuers": {}}
            issuers_map[sym] = rec
    else:
        return {"status": "INVALID", "sha256": sha256, "error": "INVALID_ISSUERS_TYPE", "issuers": {}}

    status = "EMPTY" if not issuers_map else "OK"
    return {"status": status, "sha256": sha256, "issuers": issuers_map, "consensus_enabled": consensus_enabled, "path": str(target_path)}


def validate_issuer_record(record: Mapping[str, Any], expected_symbol: str | None = None) -> dict[str, Any]:
    """Validate a single issuer record against the schema rules."""
    if not isinstance(record, Mapping):
        _fail("RECORD_NOT_DICT")

    symbol = record.get("symbol")
    if not isinstance(symbol, str) or not SYMBOL_RE.match(symbol):
        _fail(f"INVALID_SYMBOL {symbol}")

    if expected_symbol is not None and symbol != expected_symbol:
        _fail(f"SYMBOL_MISMATCH {symbol} != {expected_symbol}")

    # company_name is REQUIRED
    company_name = record.get("company_name")
    if not isinstance(company_name, str) or not clean_text(company_name, 160):
        _fail(f"INVALID_COMPANY_NAME for {symbol}")

    status = record.get("status")
    if status not in STATUSES:
        _fail(f"INVALID_STATUS {status} for {symbol}")

    prefixes = record.get("url_prefixes", [])
    if not isinstance(prefixes, list) or not prefixes or len(prefixes) > 8:
        _fail(f"INVALID_URL_PREFIXES for {symbol}")
    for p in prefixes:
        if not isinstance(p, str) or not PREFIX_RE.match(p) or len(p) > 120:
            _fail(f"INVALID_URL_PREFIX {p} for {symbol}")

    documents = record.get("documents", [])
    if not isinstance(documents, list) or len(documents) > MAX_DOCUMENTS_PER_ISSUER:
        _fail(f"DOCUMENTS_LIMIT_EXCEEDED for {symbol}")

    ALLOWED_DOC_KEYS = {
        "id", "issuer", "publisher", "title", "source_kind", "url",
        "published_date", "published_at", "retrieved_at", "sha256", "byte_size", "lineage_id"
    }

    doc_ids: set[str] = set()
    docs_by_id: dict[str, dict[str, Any]] = {}
    for doc in documents:
        if not isinstance(doc, dict):
            _fail(f"INVALID_DOCUMENT for {symbol}")
        doc_id = doc.get("id")
        if not isinstance(doc_id, str) or not ID_RE.match(doc_id) or doc_id in doc_ids:
            _fail(f"INVALID_OR_DUPLICATE_DOC_ID {doc_id} for {symbol}")
        doc_ids.add(doc_id)

        for k, v in doc.items():
            if k not in ALLOWED_DOC_KEYS:
                _fail(f"UNKNOWN_DOC_KEY {k} in doc {doc_id} for {symbol}")
            if isinstance(v, str) and len(v) > 1000:
                _fail(f"DOC_FIELD_TOO_LARGE {k} in doc {doc_id} for {symbol}")

        # Enforce that document issuer matches record symbol
        if doc.get("issuer") != symbol:
            _fail(f"DOC_ISSUER_MISMATCH doc {doc_id} issuer={doc.get('issuer')} != {symbol}")
        if expected_symbol is not None and doc.get("issuer") != expected_symbol:
            _fail(f"DOC_ISSUER_EXPECTED_MISMATCH doc {doc_id} issuer={doc.get('issuer')} != {expected_symbol}")

        if not clean_text(doc.get("publisher"), 120):
            _fail(f"INVALID_PUBLISHER for {doc_id}")
        if doc.get("source_kind") not in SOURCE_KINDS:
            _fail(f"INVALID_SOURCE_KIND {doc.get('source_kind')} for {doc_id}")
        url = doc.get("url")
        if not validate_url(url, prefixes):
            _fail(f"INVALID_DOC_URL {url} for {doc_id}")
        if doc.get("source_kind") in ("SEC_PERIODIC", "SEC_8K_EXHIBIT", "SEC_6K_EXHIBIT"):
            if not str(url).startswith("https://www.sec.gov/Archives/edgar/data/"):
                _fail(f"INVALID_SEC_DOC_URL {url} for {doc_id}")
        pub_d = parse_day(doc.get("published_date"))
        if not pub_d:
            _fail(f"INVALID_PUBLISHED_DATE for {doc_id}")
        ret_inst = parse_instant(doc.get("retrieved_at"))
        if not ret_inst:
            _fail(f"INVALID_RETRIEVED_AT for {doc_id}")
        if pub_d > ret_inst.date():
            _fail(f"PUBLISHED_AFTER_RETRIEVED for {doc_id}")
        pub_inst = doc.get("published_at")
        if pub_inst is not None:
            p_inst = parse_instant(pub_inst)
            if not p_inst or p_inst.date() != pub_d or p_inst > ret_inst:
                _fail(f"INVALID_PUBLISHED_AT for {doc_id}")
        sha = doc.get("sha256")
        if not isinstance(sha, str) or not SHA256_RE.match(sha):
            _fail(f"INVALID_SHA256 for {doc_id}")
        size = doc.get("byte_size")
        if type(size) is not int or size <= 0 or size > MAX_DOC_BYTES:
            _fail(f"INVALID_BYTE_SIZE for {doc_id}")
        lineage_id = doc.get("lineage_id")
        if not isinstance(lineage_id, str) or not ID_RE.match(lineage_id):
            _fail(f"INVALID_LINEAGE_ID for {doc_id}")

        docs_by_id[doc_id] = doc

    # Validate claims
    claims = record.get("claims", [])
    if not isinstance(claims, list) or len(claims) > MAX_CLAIMS_PER_ISSUER:
        _fail(f"CLAIMS_LIMIT_EXCEEDED for {symbol}")

    ALLOWED_CLAIM_KEYS = {
        "id", "document_id", "locator", "passage", "quote", "metric", "assertion_kind",
        "currency", "unit_multiplier", "amount", "low", "high", "stated_point",
        "plus_minus_amount", "plus_minus_percent", "original_representation",
        "scope", "scope_label", "fiscal_label", "period_kind", "period_start",
        "period_end", "start", "end", "accounting_basis", "reaffirmed_by", "corroborated_by", "revision"
    }

    claim_ids: set[str] = set()
    primary_currency: str | None = None
    primary_accounting_basis: str | None = None

    for c in claims:
        if not isinstance(c, dict):
            _fail(f"INVALID_CLAIM for {symbol}")
        cid = c.get("id")
        if not isinstance(cid, str) or not ID_RE.match(cid) or cid in claim_ids:
            _fail(f"INVALID_OR_DUPLICATE_CLAIM_ID {cid} for {symbol}")
        claim_ids.add(cid)

        for k in c:
            if k not in ALLOWED_CLAIM_KEYS:
                _fail(f"UNKNOWN_CLAIM_KEY {k} in claim {cid} for {symbol}")

        if c.get("document_id") not in doc_ids:
            _fail(f"UNKNOWN_DOCUMENT_ID {c.get('document_id')} in claim {cid}")
        if c.get("metric") != "REVENUE":
            _fail(f"INVALID_METRIC {c.get('metric')} in claim {cid} (must be REVENUE)")
        if c.get("assertion_kind") != "COMPANY_GUIDANCE":
            _fail(f"INVALID_ASSERTION_KIND {c.get('assertion_kind')} in claim {cid}")

        curr = c.get("currency")
        if curr not in CURRENCIES:
            _fail(f"INVALID_CURRENCY {curr} in claim {cid}")
        if primary_currency is None:
            primary_currency = curr
        elif primary_currency != curr:
            _fail(f"CURRENCY_INCONSISTENCY {curr} != {primary_currency} in claim {cid}")

        # accounting_basis is REQUIRED; must be supported and consistent across the record.
        acct_basis = c.get("accounting_basis")
        if not acct_basis or acct_basis not in ACCOUNTING_BASES:
            _fail(f"INVALID_ACCOUNTING_BASIS {acct_basis} in claim {cid}")
        if primary_accounting_basis is None:
            primary_accounting_basis = acct_basis
        elif primary_accounting_basis != acct_basis:
            _fail(f"ACCOUNTING_BASIS_INCONSISTENCY {acct_basis} != {primary_accounting_basis} in claim {cid}")

        # Claim scope: must be COMPANY, CONSOLIDATED, or SEGMENT
        c_scope = c.get("scope")
        if c_scope not in ("COMPANY", "CONSOLIDATED", "SEGMENT"):
            _fail(f"INVALID_CLAIM_SCOPE {c_scope} in claim {cid}")

        orig_rep = c.get("original_representation")
        if not orig_rep or not clean_text(orig_rep, 160):
            _fail(f"MISSING_ORIGINAL_REPRESENTATION in claim {cid}")

        fiscal_lbl = c.get("fiscal_label")
        if not fiscal_lbl or not clean_text(fiscal_lbl, 60):
            _fail(f"MISSING_FISCAL_LABEL in claim {cid}")

        unit_mult = c.get("unit_multiplier")
        if type(unit_mult) is not int or unit_mult not in MULTIPLIERS:
            _fail(f"INVALID_MULTIPLIER in claim {cid}")

        rev = c.get("revision")
        if rev is not None:
            if not isinstance(rev, dict):
                _fail(f"INVALID_REVISION in claim {cid}")
            r_kind = rev.get("kind")
            VALID_REVISIONS = {"SUPERSEDED", "WITHDRAWN", "WITHDRAWAL", "CORRECTION", "REAFFIRMATION"}
            if r_kind not in VALID_REVISIONS:
                _fail(f"UNKNOWN_REVISION_KIND {r_kind} in claim {cid}")
            targets = list(rev.get("targets") or [])
            if rev.get("supersedes"):
                targets.append(rev["supersedes"])
            for t in targets:
                if not isinstance(t, str):
                    _fail(f"INVALID_TARGET_TYPE in claim {cid}")
                if t == cid:
                    _fail(f"REVISION_SELF_TARGET in claim {cid}")

        reaffirmed = c.get("reaffirmed_by")
        if reaffirmed is not None:
            if not isinstance(reaffirmed, list):
                _fail(f"INVALID_REAFFIRMED_BY in claim {cid}")
            for ritem in reaffirmed:
                if not isinstance(ritem, dict):
                    _fail(f"INVALID_REAFFIRMED_ITEM in claim {cid}")
                r_doc = ritem.get("document_id")
                if not r_doc or r_doc not in doc_ids:
                    _fail(f"UNKNOWN_REAFFIRMED_DOC_ID {r_doc} in claim {cid}")
                if not clean_text(ritem.get("locator"), 160) or not clean_text(ritem.get("passage"), MAX_PASSAGE):
                    _fail(f"INVALID_REAFFIRMED_TEXT in claim {cid}")

        corroborated = c.get("corroborated_by")
        if corroborated is not None:
            if not isinstance(corroborated, list):
                _fail(f"INVALID_CORROBORATED_BY in claim {cid}")
            for citem in corroborated:
                if not isinstance(citem, dict):
                    _fail(f"INVALID_CORROBORATED_ITEM in claim {cid}")
                c_doc = citem.get("document_id")
                if not c_doc or c_doc not in doc_ids:
                    _fail(f"UNKNOWN_CORROBORATED_DOC_ID {c_doc} in claim {cid}")
                if not clean_text(citem.get("locator"), 160) or not clean_text(citem.get("passage"), MAX_PASSAGE):
                    _fail(f"INVALID_CORROBORATED_TEXT in claim {cid}")

        quote = c.get("passage") or c.get("quote")
        if not clean_text(quote, MAX_PASSAGE):
            _fail(f"INVALID_QUOTE in claim {cid}")
        if not clean_text(c.get("locator"), 120):
            _fail(f"INVALID_LOCATOR in claim {cid}")

        pkind = c.get("period_kind")
        if pkind not in ("QUARTER", "FISCAL_YEAR"):
            _fail(f"INVALID_PERIOD_KIND {pkind} in claim {cid}")

        p_start = parse_day(c.get("period_start") or c.get("start"))
        p_end = parse_day(c.get("period_end") or c.get("end"))
        if not p_start or not p_end or p_start > p_end:
            _fail(f"INVALID_PERIOD_DATES in claim {cid}")

        # Validate numbers via compute_model_point
        compute_model_point(c)

    for c in claims:
        rev = c.get("revision")
        if rev is not None and isinstance(rev, dict):
            targets = list(rev.get("targets") or [])
            if rev.get("supersedes"):
                targets.append(rev["supersedes"])
            for t in targets:
                if t not in claim_ids:
                    _fail(f"ORPHAN_REVISION_TARGET {t} in claim {c.get('id')} for {symbol}")
                t_claim = next((other for other in claims if other.get("id") == t), None)
                if t_claim:
                    t_doc = docs_by_id.get(t_claim.get("document_id"))
                    c_doc = docs_by_id.get(c.get("document_id"))
                    if t_doc and c_doc:
                        t_d = parse_day(t_doc.get("published_date"))
                        c_d = parse_day(c_doc.get("published_date"))
                        if t_d and c_d and t_d > c_d:
                            _fail(f"REVISION_TARGET_NEWER_THAN_REVISING_DOC in claim {c.get('id')}")

    # Validate reported_quarters (actuals)
    reported = record.get("reported_quarters", [])
    if not isinstance(reported, list) or len(reported) > MAX_ACTUALS_PER_ISSUER:
        _fail(f"REPORTED_QUARTERS_LIMIT_EXCEEDED for {symbol}")

    prev_end: date | None = None
    for idx, q in enumerate(reported):
        if not isinstance(q, dict):
            _fail(f"INVALID_REPORTED_QUARTER_ROW {idx} for {symbol}")
        s, e = parse_day(q.get("start")), parse_day(q.get("end"))
        if not s or not e or s > e:
            _fail(f"INVALID_REPORTED_QUARTER_DATES in row {idx} for {symbol}")
        if prev_end is not None:
            if s != prev_end + timedelta(days=1):
                _fail(f"NON_CONSECUTIVE_ACTUALS between rows {idx-1} and {idx} for {symbol}")
        prev_end = e

        rev = q.get("revenue")
        if not is_finite_number(rev) or rev < 0:
            _fail(f"INVALID_ACTUAL_REVENUE {rev} in row {idx} for {symbol}")

        q_curr = q.get("currency")
        if q_curr not in CURRENCIES:
            _fail(f"INVALID_ACTUAL_CURRENCY {q_curr} in row {idx} for {symbol}")
        if primary_currency and q_curr != primary_currency:
            _fail(f"ACTUAL_CURRENCY_MISMATCH {q_curr} != {primary_currency} in row {idx} for {symbol}")

        # Scope on actuals is REQUIRED: must be COMPANY or CONSOLIDATED
        q_scope = q.get("scope")
        if q_scope not in ("COMPANY", "CONSOLIDATED"):
            _fail(f"INVALID_ACTUAL_SCOPE {q_scope} in row {idx} for {symbol}")

        # Document evidence and accounting basis on actuals are REQUIRED fields
        q_basis = q.get("accounting_basis")
        if not q_basis or q_basis not in ACCOUNTING_BASES:
            _fail(f"INVALID_ACTUAL_BASIS {q_basis} in row {idx} for {symbol}")
        if primary_accounting_basis and q_basis != primary_accounting_basis:
            _fail(f"ACTUAL_BASIS_MISMATCH {q_basis} != {primary_accounting_basis} in row {idx} for {symbol}")

        q_doc_id = q.get("document_id")
        if not q_doc_id or q_doc_id not in doc_ids:
            _fail(f"UNKNOWN_DOCUMENT_ID {q_doc_id} in actual row {idx} for {symbol}")
        q_locator = q.get("locator")
        if not q_locator or not clean_text(q_locator, 120):
            _fail(f"INVALID_ACTUAL_LOCATOR in row {idx} for {symbol}")

        # Check derivation if present (e.g. Q4 = FY - 9M)
        deriv = q.get("derivation")
        if deriv is not None:
            if not isinstance(deriv, dict) or deriv.get("kind") != "YTD_DIFFERENCE":
                _fail(f"INVALID_DERIVATION in row {idx} for {symbol}")
            longer_id, shorter_id = deriv.get("longer_document_id"), deriv.get("shorter_document_id")
            if longer_id not in doc_ids or shorter_id not in doc_ids:
                _fail(f"UNKNOWN_DERIVATION_DOC_IDS in row {idx} for {symbol}")
            l_val, s_val = deriv.get("longer_value"), deriv.get("shorter_value")
            if not is_finite_number(l_val) or not is_finite_number(s_val):
                _fail(f"NON_NUMERIC_DERIVATION_VALUES in row {idx} for {symbol}")
            if not close(float(l_val) - float(s_val), float(rev)):
                _fail(f"DERIVATION_RECONCILIATION_FAILED {l_val} - {s_val} != {rev} in row {idx} for {symbol}")

    # Validate forward_intervals
    intervals = record.get("forward_intervals", [])
    if status == "GUIDANCE":
        if not isinstance(intervals, list) or len(intervals) != MAX_FORWARD_INTERVALS:
            _fail(f"FORWARD_INTERVALS_MUST_BE_4 for {symbol}")

        prev_f_end: date | None = None
        for idx, intv in enumerate(intervals):
            if not isinstance(intv, dict):
                _fail(f"INVALID_FORWARD_INTERVAL {idx} for {symbol}")
            s, e = parse_day(intv.get("start")), parse_day(intv.get("end"))
            if not s or not e or s > e:
                _fail(f"INVALID_FORWARD_INTERVAL_DATES {idx} for {symbol}")
            if prev_f_end is not None:
                if s != prev_f_end + timedelta(days=1):
                    _fail(f"FORWARD_INTERVAL_GAP_OR_OVERLAP between {idx-1} and {idx} for {symbol}")
            prev_f_end = e

            cal_doc = intv.get("calendar_document_id")
            if not cal_doc or cal_doc not in doc_ids:
                _fail(f"CALENDAR_DOC_REQUIRED in interval {idx} for {symbol}")
            cal_loc = intv.get("calendar_locator")
            if not cal_loc or not clean_text(cal_loc, MAX_PASSAGE):
                _fail(f"CALENDAR_LOCATOR_REQUIRED in interval {idx} for {symbol}")

    # Validate fy_reconciliation if present
    reconcil = record.get("fy_reconciliation")
    if reconcil is not None:
        if not isinstance(reconcil, dict):
            _fail(f"INVALID_FY_RECONCILIATION for {symbol}")
        fy_cid = reconcil.get("fy_claim_id")
        if not fy_cid or fy_cid not in claim_ids:
            _fail(f"UNKNOWN_FY_CLAIM_ID {fy_cid} in fy_reconciliation for {symbol}")
        fy_claim = next((c for c in claims if c.get("id") == fy_cid), None)
        if not fy_claim:
            _fail(f"UNKNOWN_FY_CLAIM {fy_cid} in fy_reconciliation for {symbol}")
        fy_start = parse_day(fy_claim.get("period_start") or fy_claim.get("start"))
        fy_end = parse_day(fy_claim.get("period_end") or fy_claim.get("end"))
        if not fy_start or not fy_end or fy_start > fy_end:
            _fail(f"INVALID_FY_CLAIM_DATES for {symbol}")
        ytd_s, ytd_e = parse_day(reconcil.get("ytd_start")), parse_day(reconcil.get("ytd_end"))
        if not ytd_s or not ytd_e or ytd_s > ytd_e:
            _fail(f"INVALID_YTD_DATES in fy_reconciliation for {symbol}")
        if ytd_s != fy_start:
            _fail(f"FY_START_MISMATCH {ytd_s} != {fy_start} in fy_reconciliation for {symbol}")
        span_days = (fy_end - fy_start).days
        if span_days < 350 or span_days > 380:
            _fail(f"INVALID_FY_SPAN_DAYS {span_days} in fy_reconciliation for {symbol}")
        ytd_rev = reconcil.get("ytd_revenue")
        if not is_finite_number(ytd_rev) or ytd_rev < 0:
            _fail(f"INVALID_YTD_REVENUE {ytd_rev} in fy_reconciliation for {symbol}")
        q_ends = reconcil.get("ytd_quarter_ends")
        if q_ends is not None:
            if not isinstance(q_ends, list) or len(q_ends) > 8:
                _fail(f"INVALID_YTD_QUARTER_ENDS in fy_reconciliation for {symbol}")
            # A legitimate zero current-FY year-to-date (Astra r5 item 13): no reported quarter yet, so the end
            # list is empty and the span is the degenerate zero-day point at the fiscal start with zero revenue;
            # any non-empty list keeps the original non-degenerate rules.
            if not q_ends:
                if ytd_s != ytd_e or ytd_s != fy_start or ytd_rev != 0:
                    _fail(f"EMPTY_YTD_MUST_BE_ZERO_DEGENERATE in fy_reconciliation for {symbol}")
            for qe in q_ends:
                qe_d = parse_day(qe)
                if not qe_d or qe_d < ytd_s or qe_d > ytd_e:
                    _fail(f"YTD_QUARTER_END_OUT_OF_RANGE {qe} in fy_reconciliation for {symbol}")

        # Check constituent quarters reconciliation if reported quarters exist in that YTD period
        matching_actuals = [
            q for q in reported
            if parse_day(q.get("start")) and parse_day(q.get("end"))
            and parse_day(q["start"]) >= ytd_s and parse_day(q["end"]) <= ytd_e  # type: ignore[operator]
        ]
        if matching_actuals:
            first_act_start = parse_day(matching_actuals[0].get("start"))
            if ytd_s != first_act_start:
                _fail(f"YTD_START_ACTUAL_MISMATCH {ytd_s} != {first_act_start} in fy_reconciliation for {symbol}")
            sum_actuals = sum(float(q["revenue"]) for q in matching_actuals)
            if not close(sum_actuals, float(ytd_rev)):
                _fail(f"YTD_RECONCILIATION_MISMATCH sum(quarters)={sum_actuals} != ytd_revenue={ytd_rev}")

    # Nondisclosure evidence for NOT_DISCLOSED status
    nd_ev = record.get("nondisclosure_evidence")
    if nd_ev is not None:
        if not isinstance(nd_ev, dict):
            _fail(f"INVALID_NONDISCLOSURE_EVIDENCE for {symbol}")
        doc_ids_list = nd_ev.get("document_ids")
        if not isinstance(doc_ids_list, list) or not doc_ids_list or not all(isinstance(d, str) and d in doc_ids for d in doc_ids_list):
            _fail(f"INVALID_NONDISCLOSURE_DOC_IDS for {symbol}")
        if not clean_text(nd_ev.get("note"), 400):
            _fail(f"INVALID_NONDISCLOSURE_NOTE for {symbol}")

    # Optional release-channel wiring (writer-owned collector targets; validated when present).
    release_channels = record.get("release_channels")
    if release_channels is not None:
        if not isinstance(release_channels, dict):
            _fail(f"INVALID_RELEASE_CHANNELS for {symbol}")
        cik = release_channels.get("sec_cik")
        if cik is not None and (isinstance(cik, bool) or type(cik) is not int or cik <= 0):
            _fail(f"INVALID_RELEASE_CHANNEL_CIK for {symbol}")
        news_query = release_channels.get("news_query")
        if news_query is not None and not clean_text(news_query, 40):
            _fail(f"INVALID_RELEASE_CHANNEL_QUERY for {symbol}")
        # The official IR channel (Astra W1 ruling, astra-ir-coverage): a known feed kind with an https feed URL,
        # paired with the reviewed guidance-release title the collector matches the reference-date item against.
        ir = release_channels.get("ir")
        ir_title = release_channels.get("ir_guidance_release_title")
        if ir is not None or ir_title is not None:
            if not isinstance(ir, Mapping):
                _fail(f"INVALID_RELEASE_CHANNEL_IR for {symbol}")
            if ir.get("kind") not in IR_CHANNEL_KINDS:
                _fail(f"INVALID_RELEASE_CHANNEL_IR_KIND for {symbol}")
            ir_url = ir.get("url")
            if not isinstance(ir_url, str) or len(ir_url) > MAX_URL or not URL_RE.match(ir_url):
                _fail(f"INVALID_RELEASE_CHANNEL_IR_URL for {symbol}")
            if not clean_text(ir_title, 200):
                _fail(f"INVALID_RELEASE_CHANNEL_IR_TITLE for {symbol}")

    # Optional reviewed later documents (writer review of receipt later_documents; release-check-cache-spec).
    reviewed_later = record.get("reviewed_later_documents")
    if reviewed_later is not None:
        if not isinstance(reviewed_later, list) or len(reviewed_later) > 16:
            _fail(f"REVIEWED_LATER_DOCUMENTS_LIMIT_EXCEEDED for {symbol}")
        for rld in reviewed_later:
            if not isinstance(rld, dict):
                _fail(f"INVALID_REVIEWED_LATER_DOCUMENT for {symbol}")
            # An EDGAR accession, the wire item's URL (release-check-cache-spec: later_documents ids of the wire
            # channel), or an official IR item URL on the record's own IR channel host (Astra W1 ruling: a reviewed
            # official-IR item, e.g. a Q4/RSS/NEWSROOM press-release page; the host binding keeps it on the issuer's
            # own reviewed IR site, never on a third-party mirror).
            rid = rld.get("id")
            ir_host = None
            ir_rc = release_channels.get("ir") if isinstance(release_channels, dict) else None
            if isinstance(ir_rc, Mapping) and isinstance(ir_rc.get("url"), str) and ir_rc["url"].startswith("https://"):
                ir_host = urlsplit(ir_rc["url"]).netloc
            ir_item = isinstance(rid, str) and len(rid) <= MAX_URL and bool(URL_RE.match(rid)) \
                and ir_host is not None and urlsplit(rid).netloc == ir_host
            if not isinstance(rid, str) or not (ID_RE.match(rid) or (len(rid) <= MAX_URL and WIRE_ITEM_RE.match(rid)) or ir_item):
                _fail(f"INVALID_REVIEWED_LATER_DOCUMENT_ID for {symbol}")
            if rld.get("disposition") != "REVIEWED_IRRELEVANT":
                _fail(f"INVALID_REVIEWED_LATER_DISPOSITION for {symbol}")
            if "reviewed_at" not in rld or parse_instant(rld.get("reviewed_at")) is None:
                _fail(f"INVALID_REVIEWED_LATER_REVIEWED_AT for {symbol}")
            note = rld.get("note")
            if note is not None and not clean_text(note, 300):
                _fail(f"INVALID_REVIEWED_LATER_NOTE for {symbol}")

    return dict(record)


def _fy_period_violation(fy_claim: Mapping[str, Any], ytd_start: date) -> str | None:
    """A fiscal-year claim must start at the YTD start and span a ~365-day fiscal year
    (the same rules the Worker enforces as V3_FY_YTD_START_MISMATCH / V3_FY_SPAN_BOUNDS)."""
    fy_start = parse_day(fy_claim.get("period_start") or fy_claim.get("start"))
    fy_end = parse_day(fy_claim.get("period_end") or fy_claim.get("end"))
    if not fy_start or not fy_end:
        return "INVALID"
    if fy_start != ytd_start:
        return "PERIOD_MISMATCH"
    if not 350 <= (fy_end - fy_start).days <= 380:
        return "INVALID"
    return None


def build_forward_quarters(
    issuer: str,
    record: Mapping[str, Any],
    cutoff: datetime,
    release_checks_cache: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the 4 forward quarters model and check staleness / post-quarter-end bridge."""
    if record.get("symbol") != issuer:
        return {
            "status": "UNAVAILABLE",
            "reason": "INVALID",
            "warning": None,
            "forward_quarters": [],
            "f1": 0.0, "f2": 0.0, "f3": 0.0, "f4": 0.0,
            "basis_type": None,
            "claims_used": [],
            "receipt": None,
        }

    status = record.get("status")
    if status != "GUIDANCE":
        reason = record.get("reason") or status or "NOT_DISCLOSED"
        if reason not in REASONS_V3:
            reason = "INVALID"
        return {
            "status": "UNAVAILABLE",
            "reason": reason,
            "warning": None,
            "forward_quarters": [],
            "f1": 0.0, "f2": 0.0, "f3": 0.0, "f4": 0.0,
            "basis_type": None,
            "claims_used": [],
            "receipt": None,
        }

    cutoff_day = cutoff.date()

    # Validate document sources and dates against cutoff
    docs_by_id: dict[str, dict[str, Any]] = {}
    for doc in record.get("documents", []):
        if not isinstance(doc, dict):
            return {"status": "UNAVAILABLE", "reason": "INVALID", "warning": None,
                    "forward_quarters": [], "f1": 0.0, "f2": 0.0, "f3": 0.0, "f4": 0.0,
                    "basis_type": None, "claims_used": [], "receipt": None}
        if doc.get("issuer") != issuer:
            return {"status": "UNAVAILABLE", "reason": "INVALID", "warning": None,
                    "forward_quarters": [], "f1": 0.0, "f2": 0.0, "f3": 0.0, "f4": 0.0,
                    "basis_type": None, "claims_used": [], "receipt": None}
        ret_inst = parse_instant(doc.get("retrieved_at"))
        if not ret_inst or ret_inst > cutoff:
            return {"status": "UNAVAILABLE", "reason": "INVALID", "warning": None,
                    "forward_quarters": [], "f1": 0.0, "f2": 0.0, "f3": 0.0, "f4": 0.0,
                    "basis_type": None, "claims_used": [], "receipt": None}
        pub_d = parse_day(doc.get("published_date"))
        if pub_d and pub_d > cutoff_day:
            return {"status": "UNAVAILABLE", "reason": "INVALID", "warning": None,
                    "forward_quarters": [], "f1": 0.0, "f2": 0.0, "f3": 0.0, "f4": 0.0,
                    "basis_type": None, "claims_used": [], "receipt": None}
        pub_inst = parse_instant(doc.get("published_at"))
        if pub_inst and (pub_inst > cutoff or pub_inst > ret_inst):
            return {"status": "UNAVAILABLE", "reason": "INVALID", "warning": None,
                    "forward_quarters": [], "f1": 0.0, "f2": 0.0, "f3": 0.0, "f4": 0.0,
                    "basis_type": None, "claims_used": [], "receipt": None}
        docs_by_id[doc["id"]] = doc

    # Validate claim review dates against cutoff
    for c in record.get("claims", []):
        if not isinstance(c, dict):
            return {"status": "UNAVAILABLE", "reason": "INVALID", "warning": None,
                    "forward_quarters": [], "f1": 0.0, "f2": 0.0, "f3": 0.0, "f4": 0.0,
                    "basis_type": None, "claims_used": [], "receipt": None}
        if c.get("symbol", issuer) != issuer:
            return {"status": "UNAVAILABLE", "reason": "INVALID", "warning": None,
                    "forward_quarters": [], "f1": 0.0, "f2": 0.0, "f3": 0.0, "f4": 0.0,
                    "basis_type": None, "claims_used": [], "receipt": None}
        chk = parse_instant(c.get("checked_at"))
        if chk and chk > cutoff:
            return {"status": "UNAVAILABLE", "reason": "INVALID", "warning": None,
                    "forward_quarters": [], "f1": 0.0, "f2": 0.0, "f3": 0.0, "f4": 0.0,
                    "basis_type": None, "claims_used": [], "receipt": None}

    # Validate reviewed later documents against cutoff
    for rld in record.get("reviewed_later_documents", []):
        if isinstance(rld, dict):
            r_at = parse_instant(rld.get("reviewed_at"))
            if r_at and r_at > cutoff:
                return {"status": "UNAVAILABLE", "reason": "INVALID", "warning": None,
                        "forward_quarters": [], "f1": 0.0, "f2": 0.0, "f3": 0.0, "f4": 0.0,
                        "basis_type": None, "claims_used": [], "receipt": None}

    # 1. Establish latest reported anchor quarter A
    reported_quarters = record.get("reported_quarters", [])
    anchor_end_day: date | None = None
    if isinstance(reported_quarters, list) and len(reported_quarters) >= 4:
        anchor_end_day = parse_day(reported_quarters[-1].get("end"))
    elif record.get("anchor_end"):
        anchor_end_day = parse_day(record.get("anchor_end"))
    elif record.get("anchor_quarter"):
        anchor_end_day = parse_day(record.get("anchor_quarter", {}).get("end"))

    if not anchor_end_day:
        return {"status": "UNAVAILABLE", "reason": "INPUTS_MISSING", "warning": None,
                "forward_quarters": [], "f1": 0, "f2": 0, "f3": 0, "f4": 0, "basis_type": None, "claims_used": [], "receipt": None}

    # 2. Check forward intervals: exactly 4, strictly contiguous, and strictly adjacent to A (f1.start == A + 1 day).
    intervals = record.get("forward_intervals", [])
    if not isinstance(intervals, list) or len(intervals) != 4:
        return {"status": "UNAVAILABLE", "reason": "INPUTS_MISSING", "warning": None,
                "forward_quarters": [], "f1": 0, "f2": 0, "f3": 0, "f4": 0, "basis_type": None, "claims_used": [], "receipt": None}

    interval_objs: list[dict[str, Any]] = []
    prev_end: date | None = None
    for intv in intervals:
        s, e = parse_day(intv.get("start")), parse_day(intv.get("end"))
        if not s or not e or s > e:
            return {"status": "UNAVAILABLE", "reason": "INVALID", "warning": None,
                    "forward_quarters": [], "f1": 0, "f2": 0, "f3": 0, "f4": 0, "basis_type": None, "claims_used": [], "receipt": None}
        if prev_end is not None and s != prev_end + timedelta(days=1):
            return {"status": "UNAVAILABLE", "reason": "PERIOD_MISMATCH", "warning": None,
                    "forward_quarters": [], "f1": 0, "f2": 0, "f3": 0, "f4": 0, "basis_type": None, "claims_used": [], "receipt": None}
        prev_end = e
        interval_objs.append({"fiscal_label": intv.get("fiscal_label", ""), "start": s, "end": e})

    # Strict A-to-f1 adjacency
    if interval_objs[0]["start"] != anchor_end_day + timedelta(days=1):
        return {"status": "UNAVAILABLE", "reason": "PERIOD_MISMATCH", "warning": None,
                "forward_quarters": [], "f1": 0, "f2": 0, "f3": 0, "f4": 0, "basis_type": None, "claims_used": [], "receipt": None}

    # No overlap with reported actuals
    if isinstance(reported_quarters, list):
        for q in reported_quarters:
            q_end = parse_day(q.get("end"))
            if q_end and q_end >= interval_objs[0]["start"]:
                return {"status": "UNAVAILABLE", "reason": "PERIOD_MISMATCH", "warning": None,
                        "forward_quarters": [], "f1": 0, "f2": 0, "f3": 0, "f4": 0, "basis_type": None, "claims_used": [], "receipt": None}

    # 3. Select active eligible guidance claims
    claims = record.get("claims", [])
    docs_by_id = {d["id"]: d for d in record.get("documents", []) if isinstance(d, dict) and "id" in d}

    eligible_claims = []
    for c in claims:
        doc = docs_by_id.get(c.get("document_id"))
        if not doc:
            continue
        # Date-only publication rule & time coherence
        pub_d = parse_day(doc.get("published_date"))
        ret_inst = parse_instant(doc.get("retrieved_at"))
        pub_inst = parse_instant(doc.get("published_at"))

        if not pub_d or not ret_inst:
            continue
        if ret_inst > cutoff:
            continue

        # Date-only publication: only eligible after the end of that UTC day
        if pub_inst:
            if pub_inst > cutoff or pub_inst > ret_inst:
                continue
        else:
            if pub_d >= cutoff_day:
                continue

        # 200-day guidance age boundary
        guidance_age = (cutoff_day - pub_d).days
        if guidance_age < 0 or guidance_age > MAX_GUIDANCE_AGE_DAYS:
            continue

        # Consolidated scope only for company guidance model
        if c.get("scope") not in ("COMPANY", "CONSOLIDATED"):
            continue

        eligible_claims.append(c)
    if not eligible_claims:
        # Check if company guidance was STALE, WITHDRAWN, or CONFLICTING
        for c in claims:
            doc = docs_by_id.get(c.get("document_id"))
            if doc:
                pub_d = parse_day(doc.get("published_date"))
                if pub_d and (cutoff_day - pub_d).days > MAX_GUIDANCE_AGE_DAYS:
                    return {"status": "UNAVAILABLE", "reason": "STALE", "warning": None,
                            "forward_quarters": [], "f1": 0, "f2": 0, "f3": 0, "f4": 0, "basis_type": None, "claims_used": [], "receipt": None}
                rev = c.get("revision") or {}
                if rev.get("kind") == "WITHDRAWN":
                    return {"status": "UNAVAILABLE", "reason": "WITHDRAWN", "warning": None,
                            "forward_quarters": [], "f1": 0, "f2": 0, "f3": 0, "f4": 0, "basis_type": None, "claims_used": [], "receipt": None}
        return {"status": "UNAVAILABLE", "reason": "INPUTS_MISSING", "warning": None,
                "forward_quarters": [], "f1": 0, "f2": 0, "f3": 0, "f4": 0, "basis_type": None, "claims_used": [], "receipt": None}

    # Deterministic claim selection: separate QUARTER and FISCAL_YEAR, independent of array order (Astra r5 item 11).
    # Superseded and withdrawn claims are historical references, never active input; a withdrawn claim is permitted
    # in the record (it seals the WITHDRAWN routing state) and a later CORRECTION / REAFFIRMATION stays allowed.
    has_withdrawn = any((c.get("revision") or {}).get("kind") in ("WITHDRAWN", "WITHDRAWAL") for c in claims
                         if isinstance(c, Mapping))
    superseded_ids = set()
    for c in eligible_claims:
        rev = c.get("revision") or {}
        if rev.get("kind") in ("SUPERSEDED", "WITHDRAWN", "WITHDRAWAL"):
            superseded_ids.add(c["id"])
        for target in rev.get("targets", []):
            superseded_ids.add(target)
        if rev.get("supersedes"):
            superseded_ids.add(rev.get("supersedes"))

    active_claims = sorted([c for c in eligible_claims if c["id"] not in superseded_ids],
                          key=lambda c: (str(c.get("period_kind")), str(c.get("period_start") or c.get("start") or ""),
                                         str(c.get("id") or "")))

    if not active_claims:
        if has_withdrawn:
            return {"status": "UNAVAILABLE", "reason": "WITHDRAWN", "warning": None,
                    "forward_quarters": [], "f1": 0.0, "f2": 0.0, "f3": 0.0, "f4": 0.0,
                    "basis_type": None, "claims_used": [], "receipt": None}
        return {"status": "UNAVAILABLE", "reason": "INPUTS_MISSING", "warning": None,
                "forward_quarters": [], "f1": 0.0, "f2": 0.0, "f3": 0.0, "f4": 0.0,
                "basis_type": None, "claims_used": [], "receipt": None}

    quarter_claims = [c for c in active_claims if c.get("period_kind") == "QUARTER"]
    fy_claims = [c for c in active_claims if c.get("period_kind") == "FISCAL_YEAR"]

    # Competing unresolved conflicts: any two active claims covering the same canonical period, or a second quarter
    # claim whose period does not match the first forward interval (the canonical period fields, not array order).
    period_of = lambda c: (str(c.get("period_start") or c.get("start")), str(c.get("period_end") or c.get("end")))
    q_periods = [period_of(c) for c in quarter_claims]
    if len(quarter_claims) > 1:
        if any(p == q_periods[0] for p in q_periods[1:]) or len(set(q_periods)) > 1:
            return {"status": "UNAVAILABLE", "reason": "CONFLICTING_DISCLOSURES", "warning": None,
                    "forward_quarters": [], "f1": 0, "f2": 0, "f3": 0, "f4": 0, "basis_type": None, "claims_used": [], "receipt": None}

    if len(fy_claims) > 1:
        return {"status": "UNAVAILABLE", "reason": "CONFLICTING_DISCLOSURES", "warning": None,
                "forward_quarters": [], "f1": 0, "f2": 0, "f3": 0, "f4": 0, "basis_type": None, "claims_used": [], "receipt": None}

    quarter_claim = quarter_claims[0] if quarter_claims else None
    fy_claim = fy_claims[0] if fy_claims else None

    if not quarter_claim and not fy_claim:
        return {"status": "UNAVAILABLE", "reason": "INPUTS_MISSING", "warning": None,
                "forward_quarters": [], "f1": 0, "f2": 0, "f3": 0, "f4": 0, "basis_type": None, "claims_used": [], "receipt": None}

    # Match claims to forward intervals
    if quarter_claim:
        q_start, q_end = parse_day(quarter_claim.get("period_start") or quarter_claim.get("start")), parse_day(quarter_claim.get("period_end") or quarter_claim.get("end"))
        if q_start != interval_objs[0]["start"] or q_end != interval_objs[0]["end"]:
            return {"status": "UNAVAILABLE", "reason": "PERIOD_MISMATCH", "warning": None,
                    "forward_quarters": [], "f1": 0, "f2": 0, "f3": 0, "f4": 0, "basis_type": None, "claims_used": [], "receipt": None}

    # 4. Release check receipt selection and validation
    # Astra W1 ruling (astra-ir-coverage): the company-guidance path requires official-IR coverage, not just
    # SEC + wire. A record without a reviewed IR channel, or a receipt without SEC_WIRE_IR coverage, suspends
    # the revenue path (FRESHNESS_UNVERIFIED with the distinct IR_COVERAGE_MISSING diagnostic); it never falls
    # back to NOT_DISCLOSED, zero or consensus.
    rc_cfg = record.get("release_channels") or {}
    ir_spec = rc_cfg.get("ir") if isinstance(rc_cfg, Mapping) else None
    if not isinstance(ir_spec, Mapping):
        ir_spec = None

    receipt = select_latest_release_receipt(issuer, release_checks_cache, cutoff)
    if not receipt:
        return {"status": "UNAVAILABLE", "reason": "FRESHNESS_UNVERIFIED", "diagnostic": "IR_COVERAGE_MISSING",
                "warning": None, "forward_quarters": [], "f1": 0, "f2": 0, "f3": 0, "f4": 0, "basis_type": None,
                "claims_used": [], "receipt": None}
    if ir_spec is None:
        # The record carries no official IR channel: its company-guidance freshness is unverified by design.
        return {"status": "UNAVAILABLE", "reason": "FRESHNESS_UNVERIFIED", "diagnostic": "IR_COVERAGE_MISSING",
                "warning": None, "forward_quarters": [], "f1": 0, "f2": 0, "f3": 0, "f4": 0, "basis_type": None,
                "claims_used": [], "receipt": receipt}

    # One reference for the whole active claim set (B0): distinct references never pick one claim's document.
    active_doc_id = guidance_reference(record)["document_id"]
    active_doc = docs_by_id.get(active_doc_id) if active_doc_id else None
    active_doc_pub = active_doc.get("published_date") if active_doc else None
    reviewed_later = record.get("reviewed_later_documents")
    # Channel identity is bound to the reviewed issuer wiring (Astra r5 item 2): the receipt's SEC feed must be the
    # issuer's own CIK submissions feed and the wire feed its own symbol, not merely any URL of that shape; the IR
    # channel must read the registry's own IR host (Astra W1 ruling).
    expected_cik = rc_cfg.get("sec_cik") if isinstance(rc_cfg, Mapping) else None
    expected_wire = rc_cfg.get("wire_symbol") if isinstance(rc_cfg, Mapping) else None
    valid_rc, rc_status, rc_err = validate_receipt(
        receipt, issuer, str(anchor_end_day), active_doc_id, cutoff, reviewed_later, active_doc_pub,
        expected_cik=expected_cik, expected_wire_symbol=expected_wire, expected_ir=ir_spec)

    if not valid_rc:
        reason = "FRESHNESS_UNVERIFIED" if rc_status == "FRESHNESS_UNVERIFIED" else rc_status
        diagnostic = "IR_COVERAGE_MISSING" if rc_err == "IR_COVERAGE_MISSING" else None
        return {"status": "UNAVAILABLE", "reason": reason, "diagnostic": diagnostic, "warning": None,
                "forward_quarters": [], "f1": 0, "f2": 0, "f3": 0, "f4": 0, "basis_type": None, "claims_used": [], "receipt": receipt}

    if rc_status == "RESULTS_PUBLISHED":
        return {"status": "UNAVAILABLE", "reason": "STALE", "warning": None,
                "forward_quarters": [], "f1": 0, "f2": 0, "f3": 0, "f4": 0, "basis_type": None, "claims_used": [], "receipt": receipt}
    if rc_status == "REVIEW_REQUIRED":
        return {"status": "UNAVAILABLE", "reason": "STALE", "warning": None,
                "forward_quarters": [], "f1": 0, "f2": 0, "f3": 0, "f4": 0, "basis_type": None, "claims_used": [], "receipt": receipt}
    if rc_status != "OK":
        return {"status": "UNAVAILABLE", "reason": "FRESHNESS_UNVERIFIED", "warning": None,
                "forward_quarters": [], "f1": 0, "f2": 0, "f3": 0, "f4": 0, "basis_type": None, "claims_used": [], "receipt": receipt}

    # 5. Model construction
    f_amounts: list[float] = [0.0, 0.0, 0.0, 0.0]
    derivations: list[str] = ["", "", "", ""]
    is_fy_allocation = False

    if quarter_claim and not fy_claim:
        g_val, _ = compute_model_point(quarter_claim)
        if g_val < 0 or not math.isfinite(g_val):
            return {"status": "UNAVAILABLE", "reason": "INVALID", "warning": None,
                    "forward_quarters": [], "f1": 0, "f2": 0, "f3": 0, "f4": 0, "basis_type": None, "claims_used": [], "receipt": receipt}
        f_amounts = [g_val, g_val, g_val, g_val]
        derivations[0] = "公司財測"
        derivations[1] = "模型：之後各季持平於公司財測"
        derivations[2] = "模型：之後各季持平於公司財測"
        derivations[3] = "模型：之後各季持平於公司財測"

    elif fy_claim and not quarter_claim:
        fy_val, _ = compute_model_point(fy_claim)
        reconcil = record.get("fy_reconciliation")
        if not isinstance(reconcil, dict):
            return {"status": "UNAVAILABLE", "reason": "INPUTS_MISSING", "warning": None,
                    "forward_quarters": [], "f1": 0, "f2": 0, "f3": 0, "f4": 0, "basis_type": None, "claims_used": [], "receipt": receipt}

        if reconcil.get("fy_claim_id") != fy_claim["id"]:
            return {"status": "UNAVAILABLE", "reason": "INVALID", "warning": None,
                    "forward_quarters": [], "f1": 0, "f2": 0, "f3": 0, "f4": 0, "basis_type": None, "claims_used": [], "receipt": receipt}

        ytd_s_d, ytd_e_d = parse_day(reconcil.get("ytd_start")), parse_day(reconcil.get("ytd_end"))
        if not ytd_s_d or not ytd_e_d or ytd_s_d > ytd_e_d:
            return {"status": "UNAVAILABLE", "reason": "INVALID", "warning": None,
                    "forward_quarters": [], "f1": 0, "f2": 0, "f3": 0, "f4": 0, "basis_type": None, "claims_used": [], "receipt": receipt}

        fy_violation = _fy_period_violation(fy_claim, ytd_s_d)
        if fy_violation:
            return {"status": "UNAVAILABLE", "reason": fy_violation, "warning": None,
                    "forward_quarters": [], "f1": 0, "f2": 0, "f3": 0, "f4": 0, "basis_type": None, "claims_used": [], "receipt": receipt}

        if ytd_e_d != anchor_end_day:
            return {"status": "UNAVAILABLE", "reason": "PERIOD_MISMATCH", "warning": None,
                    "forward_quarters": [], "f1": 0, "f2": 0, "f3": 0, "f4": 0, "basis_type": None, "claims_used": [], "receipt": receipt}

        q_ends = reconcil.get("ytd_quarter_ends")
        if not isinstance(q_ends, list):
            return {"status": "UNAVAILABLE", "reason": "INVALID", "warning": None,
                    "forward_quarters": [], "f1": 0, "f2": 0, "f3": 0, "f4": 0, "basis_type": None, "claims_used": [], "receipt": receipt}

        matching_actuals = [q for q in reported_quarters if q.get("end") in q_ends]
        if len(matching_actuals) != len(q_ends):
            return {"status": "UNAVAILABLE", "reason": "PERIOD_MISMATCH", "warning": None,
                    "forward_quarters": [], "f1": 0, "f2": 0, "f3": 0, "f4": 0, "basis_type": None, "claims_used": [], "receipt": receipt}

        ytd = reconcil.get("ytd_revenue")
        if not is_finite_number(ytd) or ytd < 0:
            return {"status": "UNAVAILABLE", "reason": "INVALID", "warning": None,
                    "forward_quarters": [], "f1": 0, "f2": 0, "f3": 0, "f4": 0, "basis_type": None, "claims_used": [], "receipt": receipt}

        if not close(sum(float(q["revenue"]) for q in matching_actuals), float(ytd)):
            return {"status": "UNAVAILABLE", "reason": "INVALID", "warning": None,
                    "forward_quarters": [], "f1": 0, "f2": 0, "f3": 0, "f4": 0, "basis_type": None, "claims_used": [], "receipt": receipt}

        k = len(q_ends)
        n = 4 - k
        if not 1 <= n <= 4:
            return {"status": "UNAVAILABLE", "reason": "PERIOD_MISMATCH", "warning": None,
                    "forward_quarters": [], "f1": 0, "f2": 0, "f3": 0, "f4": 0, "basis_type": None, "claims_used": [], "receipt": receipt}

        fy_end = parse_day(fy_claim.get("period_end") or fy_claim.get("end"))
        if not fy_end or interval_objs[n - 1]["end"] != fy_end:
            return {"status": "UNAVAILABLE", "reason": "PERIOD_MISMATCH", "warning": None,
                    "forward_quarters": [], "f1": 0, "f2": 0, "f3": 0, "f4": 0, "basis_type": None, "claims_used": [], "receipt": receipt}

        R = fy_val - float(ytd)
        if R < -REL_TOL:
            return {"status": "UNAVAILABLE", "reason": "INVALID", "warning": None,
                    "forward_quarters": [], "f1": 0, "f2": 0, "f3": 0, "f4": 0, "basis_type": None, "claims_used": [], "receipt": receipt}
        if R < 0:
            R = 0.0

        quarter_share = R / float(n)
        for i in range(n):
            f_amounts[i] = quarter_share
            derivations[i] = "模型：全年財測扣已報營收，剩餘各季均分"
        for i in range(n, 4):
            f_amounts[i] = quarter_share
            derivations[i] = "模型：後續各季持平於財測推算末季"
        is_fy_allocation = True

    elif quarter_claim and fy_claim:
        g_val, _ = compute_model_point(quarter_claim)
        fy_val, _ = compute_model_point(fy_claim)
        reconcil = record.get("fy_reconciliation")
        if not isinstance(reconcil, dict):
            return {"status": "UNAVAILABLE", "reason": "INPUTS_MISSING", "warning": None,
                    "forward_quarters": [], "f1": 0, "f2": 0, "f3": 0, "f4": 0, "basis_type": None, "claims_used": [], "receipt": receipt}

        if reconcil.get("fy_claim_id") != fy_claim["id"]:
            return {"status": "UNAVAILABLE", "reason": "INVALID", "warning": None,
                    "forward_quarters": [], "f1": 0, "f2": 0, "f3": 0, "f4": 0, "basis_type": None, "claims_used": [], "receipt": receipt}

        ytd_s_d, ytd_e_d = parse_day(reconcil.get("ytd_start")), parse_day(reconcil.get("ytd_end"))
        if not ytd_s_d or not ytd_e_d or ytd_s_d > ytd_e_d:
            return {"status": "UNAVAILABLE", "reason": "INVALID", "warning": None,
                    "forward_quarters": [], "f1": 0, "f2": 0, "f3": 0, "f4": 0, "basis_type": None, "claims_used": [], "receipt": receipt}

        fy_violation = _fy_period_violation(fy_claim, ytd_s_d)
        if fy_violation:
            return {"status": "UNAVAILABLE", "reason": fy_violation, "warning": None,
                    "forward_quarters": [], "f1": 0, "f2": 0, "f3": 0, "f4": 0, "basis_type": None, "claims_used": [], "receipt": receipt}

        if ytd_e_d != anchor_end_day:
            return {"status": "UNAVAILABLE", "reason": "PERIOD_MISMATCH", "warning": None,
                    "forward_quarters": [], "f1": 0, "f2": 0, "f3": 0, "f4": 0, "basis_type": None, "claims_used": [], "receipt": receipt}

        q_ends = reconcil.get("ytd_quarter_ends")
        if not isinstance(q_ends, list):
            return {"status": "UNAVAILABLE", "reason": "INVALID", "warning": None,
                    "forward_quarters": [], "f1": 0, "f2": 0, "f3": 0, "f4": 0, "basis_type": None, "claims_used": [], "receipt": receipt}

        matching_actuals = [q for q in reported_quarters if q.get("end") in q_ends]
        if len(matching_actuals) != len(q_ends):
            return {"status": "UNAVAILABLE", "reason": "PERIOD_MISMATCH", "warning": None,
                    "forward_quarters": [], "f1": 0, "f2": 0, "f3": 0, "f4": 0, "basis_type": None, "claims_used": [], "receipt": receipt}

        ytd = reconcil.get("ytd_revenue")
        if not is_finite_number(ytd) or ytd < 0:
            return {"status": "UNAVAILABLE", "reason": "INVALID", "warning": None,
                    "forward_quarters": [], "f1": 0, "f2": 0, "f3": 0, "f4": 0, "basis_type": None, "claims_used": [], "receipt": receipt}

        if not close(sum(float(q["revenue"]) for q in matching_actuals), float(ytd)):
            return {"status": "UNAVAILABLE", "reason": "INVALID", "warning": None,
                    "forward_quarters": [], "f1": 0, "f2": 0, "f3": 0, "f4": 0, "basis_type": None, "claims_used": [], "receipt": receipt}

        fy_end = parse_day(fy_claim.get("period_end") or fy_claim.get("end"))
        k = len(q_ends)
        n = 4 - k
        if not 1 <= n <= 4:
            return {"status": "UNAVAILABLE", "reason": "PERIOD_MISMATCH", "warning": None,
                    "forward_quarters": [], "f1": 0, "f2": 0, "f3": 0, "f4": 0, "basis_type": None, "claims_used": [], "receipt": receipt}

        if not fy_end or interval_objs[n - 1]["end"] != fy_end:
            return {"status": "UNAVAILABLE", "reason": "PERIOD_MISMATCH", "warning": None,
                    "forward_quarters": [], "f1": 0, "f2": 0, "f3": 0, "f4": 0, "basis_type": None, "claims_used": [], "receipt": receipt}

        R = fy_val - float(ytd)
        if R < -REL_TOL:
            return {"status": "UNAVAILABLE", "reason": "INVALID", "warning": None,
                    "forward_quarters": [], "f1": 0, "f2": 0, "f3": 0, "f4": 0, "basis_type": None, "claims_used": [], "receipt": receipt}

        if n == 1:
            if not close(R, g_val):
                return {"status": "UNAVAILABLE", "reason": "CONFLICTING_DISCLOSURES", "warning": None,
                        "forward_quarters": [], "f1": 0, "f2": 0, "f3": 0, "f4": 0, "basis_type": None, "claims_used": [], "receipt": receipt}
            f_amounts = [g_val, g_val, g_val, g_val]
            derivations[0] = "公司財測"
            derivations[1] = "模型：後續各季持平於財測推算末季"
            derivations[2] = "模型：後續各季持平於財測推算末季"
            derivations[3] = "模型：後續各季持平於財測推算末季"
        else:
            residual = R - g_val
            if residual < -REL_TOL:
                return {"status": "UNAVAILABLE", "reason": "INVALID", "warning": None,
                        "forward_quarters": [], "f1": 0, "f2": 0, "f3": 0, "f4": 0, "basis_type": None, "claims_used": [], "receipt": receipt}
            if residual < 0:
                residual = 0.0
            f_amounts[0] = g_val
            derivations[0] = "公司財測"
            rem_share = residual / float(n - 1)
            for i in range(1, n):
                f_amounts[i] = rem_share
                derivations[i] = "模型：全年財測扣已報營收及下季財測，剩餘各季均分"
            for i in range(n, 4):
                f_amounts[i] = rem_share
                derivations[i] = "模型：後續各季持平於財測推算末季"
        is_fy_allocation = True

    # Check finite nonnegative forward amounts
    if any(amt < 0 or not math.isfinite(amt) for amt in f_amounts):
        return {"status": "UNAVAILABLE", "reason": "INVALID", "warning": None,
                "forward_quarters": [], "f1": 0, "f2": 0, "f3": 0, "f4": 0, "basis_type": None, "claims_used": [], "receipt": receipt}

    # 6. Staleness / post-quarter-end bridge (Astra amendment)
    ended_quarters = []
    for idx, intv in enumerate(interval_objs):
        q_end = intv["end"]
        if cutoff_day > q_end:
            overdue_days = (cutoff_day - q_end).days
            if overdue_days > QUARTER_END_BRIDGE_DAYS:
                return {
                    "status": "UNAVAILABLE",
                    "reason": "STALE",
                    "warning": None,
                    "forward_quarters": [],
                    "f1": 0, "f2": 0, "f3": 0, "f4": 0,
                    "basis_type": None,
                    "claims_used": [],
                    "receipt": receipt,
                }
            ended_quarters.append((idx, intv))

    warning = None
    if ended_quarters:
        earliest_idx, earliest_intv = ended_quarters[0]
        affected_ends = [str(q[1]["end"]) for q in ended_quarters]
        ends_str = "、".join(affected_ends)
        chk_str = receipt.get("checked_at", "")
        if is_fy_allocation:
            wtext = f"全年財測推算季度已於{ends_str}結束，實際營收尚未公布；截至{chk_str}查核；仍為財測／模型，非實績"
        else:
            wtext = f"財測季度已於{ends_str}結束，實際營收尚未公布；截至{chk_str}查核；仍為財測／模型，非實績"
        warning = {
            "quarter_index": earliest_idx,
            "quarter_end": str(earliest_intv["end"]),
            "checked_at": chk_str,
            "text": wtext,
            "is_fy": is_fy_allocation,
            "affected_ends": affected_ends,
        }

    forward_list = []
    for i, (intv, amt, deriv) in enumerate(zip(interval_objs, f_amounts, derivations)):
        forward_list.append({
            "quarter_index": i + 1,
            "fiscal_label": intv["fiscal_label"],
            "start": str(intv["start"]),
            "end": str(intv["end"]),
            "amount": amt,
            "derivation": deriv,
        })

    return {
        "status": "AVAILABLE",
        "reason": None,
        "diagnostic": None,
        "warning": warning,
        "forward_quarters": forward_list,
        "f1": f_amounts[0], "f2": f_amounts[1], "f3": f_amounts[2], "f4": f_amounts[3],
        "basis_type": "COMPANY_GUIDANCE",
        "claims_used": [c for c in (quarter_claim, fy_claim) if c],
        "receipt": receipt,
    }


def build_consensus_forward_quarters(
    symbol: str,
    consensus_entry: Mapping[str, Any] | None,
    intervals: list[Mapping[str, Any]],
    cutoff: datetime,
    expected_currency: str | None = None,
) -> dict[str, Any]:
    """Build forward quarters from quarterly consensus adapter if available and valid."""
    if not consensus_entry or not isinstance(consensus_entry, Mapping):
        return {"status": "UNAVAILABLE", "reason": "INPUTS_MISSING", "warning": None,
                "forward_quarters": [], "f1": 0, "f2": 0, "f3": 0, "f4": 0, "basis_type": None, "consensus": None}

    if consensus_entry.get("symbol") != symbol:
        return {"status": "UNAVAILABLE", "reason": "INVALID", "warning": None,
                "forward_quarters": [], "f1": 0, "f2": 0, "f3": 0, "f4": 0, "basis_type": None, "consensus": None}

    # The provider currency and scope are sealed metadata (Astra r5 item 15): a valid currency, and the record's own
    # currency when one is known; the per-quarter currency must agree with both.
    entry_curr = consensus_entry.get("currency")
    if not isinstance(entry_curr, str) or entry_curr not in CURRENCIES:
        return {"status": "UNAVAILABLE", "reason": "INVALID", "warning": None,
                "forward_quarters": [], "f1": 0, "f2": 0, "f3": 0, "f4": 0, "basis_type": None, "consensus": None}
    if expected_currency and entry_curr != expected_currency:
        return {"status": "UNAVAILABLE", "reason": "INVALID", "warning": None,
                "forward_quarters": [], "f1": 0, "f2": 0, "f3": 0, "f4": 0, "basis_type": None, "consensus": None}
    entry_scope = consensus_entry.get("scope")
    if entry_scope is not None and entry_scope not in ("CONSOLIDATED", "COMPANY"):
        return {"status": "UNAVAILABLE", "reason": "INVALID", "warning": None,
                "forward_quarters": [], "f1": 0, "f2": 0, "f3": 0, "f4": 0, "basis_type": None, "consensus": None}

    captured_at = parse_instant(consensus_entry.get("captured_at") or consensus_entry.get("retrieved_at"))
    if not captured_at or (cutoff - captured_at).total_seconds() > RECEIPT_MAX_AGE_HOURS * 3600 or captured_at > cutoff:
        return {"status": "UNAVAILABLE", "reason": "STALE", "warning": None,
                "forward_quarters": [], "f1": 0, "f2": 0, "f3": 0, "f4": 0, "basis_type": None, "consensus": None}

    quarters = consensus_entry.get("quarters", [])
    if not isinstance(quarters, list) or not quarters or len(quarters) > 2:
        return {"status": "UNAVAILABLE", "reason": "INVALID" if isinstance(quarters, list) and len(quarters) > 2 else "INPUTS_MISSING", "warning": None,
                "forward_quarters": [], "f1": 0, "f2": 0, "f3": 0, "f4": 0, "basis_type": None, "consensus": None}

    if len(intervals) != 4:
        return {"status": "UNAVAILABLE", "reason": "INPUTS_MISSING", "warning": None,
                "forward_quarters": [], "f1": 0, "f2": 0, "f3": 0, "f4": 0, "basis_type": None, "consensus": None}

    q1_est = quarters[0] if len(quarters) > 0 else None
    q2_est = quarters[1] if len(quarters) > 1 else None
    # An explicit null second quarter is malformed evidence, never an absence (Astra r5 item 15).
    if len(quarters) > 1 and q2_est is None:
        return {"status": "UNAVAILABLE", "reason": "INVALID", "warning": None,
                "forward_quarters": [], "f1": 0, "f2": 0, "f3": 0, "f4": 0, "basis_type": None, "consensus": None}

    # Validate q1
    if not q1_est or not isinstance(q1_est, dict):
        return {"status": "UNAVAILABLE", "reason": "INPUTS_MISSING", "warning": None,
                "forward_quarters": [], "f1": 0, "f2": 0, "f3": 0, "f4": 0, "basis_type": None, "consensus": None}

    q1_period = q1_est.get("period")
    if q1_period and q1_period not in ("0q", "Q1", "QUARTER"):
        return {"status": "UNAVAILABLE", "reason": "PERIOD_MISMATCH", "warning": None,
                "forward_quarters": [], "f1": 0, "f2": 0, "f3": 0, "f4": 0, "basis_type": None, "consensus": None}
    q1_scope = q1_est.get("scope")
    if q1_scope and q1_scope not in ("CONSOLIDATED", "COMPANY"):
        return {"status": "UNAVAILABLE", "reason": "INVALID", "warning": None,
                "forward_quarters": [], "f1": 0, "f2": 0, "f3": 0, "f4": 0, "basis_type": None, "consensus": None}
    q1_curr = q1_est.get("currency")
    if q1_curr and (q1_curr not in CURRENCIES or (expected_currency and q1_curr != expected_currency)):
        return {"status": "UNAVAILABLE", "reason": "INVALID", "warning": None,
                "forward_quarters": [], "f1": 0, "f2": 0, "f3": 0, "f4": 0, "basis_type": None, "consensus": None}

    # An explicit resolved start must be the interval's start (a 2020 start beside a 2026 interval is a mismatch, not a guess).
    q1_start = parse_day(q1_est.get("start"))
    f1_start = parse_day(intervals[0].get("start"))
    if q1_est.get("start") is not None and (not q1_start or not f1_start or q1_start != f1_start):
        return {"status": "UNAVAILABLE", "reason": "PERIOD_MISMATCH", "warning": None,
                "forward_quarters": [], "f1": 0, "f2": 0, "f3": 0, "f4": 0, "basis_type": None, "consensus": None}

    q1_end = parse_day(q1_est.get("end"))
    f1_end = parse_day(intervals[0].get("end"))
    if not q1_end or q1_end != f1_end:
        return {"status": "UNAVAILABLE", "reason": "PERIOD_MISMATCH", "warning": None,
                "forward_quarters": [], "f1": 0, "f2": 0, "f3": 0, "f4": 0, "basis_type": None, "consensus": None}

    # Consensus does NOT use +70d bridge: if guided quarter ended, EXPIRED/STALE
    if cutoff.date() > q1_end:
        return {"status": "UNAVAILABLE", "reason": "STALE", "warning": None,
                "forward_quarters": [], "f1": 0, "f2": 0, "f3": 0, "f4": 0, "basis_type": None, "consensus": None}

    q1_analysts = q1_est.get("analysts")
    if type(q1_analysts) is not int or q1_analysts < 3:
        return {"status": "UNAVAILABLE", "reason": "SAMPLE_INSUFFICIENT", "warning": None,
                "forward_quarters": [], "f1": 0, "f2": 0, "f3": 0, "f4": 0, "basis_type": None, "consensus": None}

    q1_rev = q1_est.get("revenue") if q1_est.get("revenue") is not None else q1_est.get("avg")
    if not is_finite_number(q1_rev) or q1_rev < 0:
        return {"status": "UNAVAILABLE", "reason": "INVALID", "warning": None,
                "forward_quarters": [], "f1": 0, "f2": 0, "f3": 0, "f4": 0, "basis_type": None, "consensus": None}

    c1 = float(q1_rev)

    # Check q2: distinguish malformed from absent from insufficient sample
    q2_valid = False
    c2 = 0.0
    q2_low_sample = False
    f2_end = parse_day(intervals[1].get("end"))

    if q2_est is not None:
        if not isinstance(q2_est, dict):
            return {"status": "UNAVAILABLE", "reason": "INVALID", "warning": None,
                    "forward_quarters": [], "f1": 0, "f2": 0, "f3": 0, "f4": 0, "basis_type": None, "consensus": None}
        q2_period = q2_est.get("period")
        if q2_period and q2_period not in ("+1q", "Q2", "QUARTER"):
            return {"status": "UNAVAILABLE", "reason": "PERIOD_MISMATCH", "warning": None,
                    "forward_quarters": [], "f1": 0, "f2": 0, "f3": 0, "f4": 0, "basis_type": None, "consensus": None}
        q2_scope = q2_est.get("scope")
        if q2_scope and q2_scope not in ("CONSOLIDATED", "COMPANY"):
            return {"status": "UNAVAILABLE", "reason": "INVALID", "warning": None,
                    "forward_quarters": [], "f1": 0, "f2": 0, "f3": 0, "f4": 0, "basis_type": None, "consensus": None}
        q2_curr = q2_est.get("currency")
        if q2_curr and (q2_curr not in CURRENCIES or (expected_currency and q2_curr != expected_currency)):
            return {"status": "UNAVAILABLE", "reason": "INVALID", "warning": None,
                    "forward_quarters": [], "f1": 0, "f2": 0, "f3": 0, "f4": 0, "basis_type": None, "consensus": None}
        q2_start = parse_day(q2_est.get("start"))
        f2_start = parse_day(intervals[1].get("start"))
        if q2_est.get("start") is not None and (not q2_start or not f2_start or q2_start != f2_start):
            return {"status": "UNAVAILABLE", "reason": "PERIOD_MISMATCH", "warning": None,
                    "forward_quarters": [], "f1": 0, "f2": 0, "f3": 0, "f4": 0, "basis_type": None, "consensus": None}

        q2_end = parse_day(q2_est.get("end"))
        if not q2_end or q2_end != f2_end:
            return {"status": "UNAVAILABLE", "reason": "PERIOD_MISMATCH", "warning": None,
                    "forward_quarters": [], "f1": 0, "f2": 0, "f3": 0, "f4": 0, "basis_type": None, "consensus": None}

        q2_rev = q2_est.get("revenue") if q2_est.get("revenue") is not None else q2_est.get("avg")
        if not is_finite_number(q2_rev) or q2_rev < 0:
            return {"status": "UNAVAILABLE", "reason": "INVALID", "warning": None,
                    "forward_quarters": [], "f1": 0, "f2": 0, "f3": 0, "f4": 0, "basis_type": None, "consensus": None}

        q2_analysts = q2_est.get("analysts")
        if type(q2_analysts) is not int or q2_analysts < 0:
            return {"status": "UNAVAILABLE", "reason": "INVALID", "warning": None,
                    "forward_quarters": [], "f1": 0, "f2": 0, "f3": 0, "f4": 0, "basis_type": None, "consensus": None}

        if q2_analysts >= 3 and cutoff.date() <= q2_end:
            q2_valid = True
            c2 = float(q2_rev)
        elif q2_analysts < 3:
            q2_low_sample = True

    f_amounts: list[float] = [0.0, 0.0, 0.0, 0.0]
    derivations: list[str] = ["", "", "", ""]

    if q2_valid:
        f_amounts = [c1, c2, c2, c2]
        derivations[0] = "分析師共識"
        derivations[1] = "分析師共識"
        derivations[2] = "模型：持平於次季分析師共識"
        derivations[3] = "模型：持平於次季分析師共識"
    else:
        f_amounts = [c1, c1, c1, c1]
        second_deriv = "僅一季共識（次季分析師樣本不足），其後持平模型" if q2_low_sample else "僅一季共識，其後持平模型"
        derivations[0] = "分析師共識"
        derivations[1] = second_deriv
        derivations[2] = second_deriv
        derivations[3] = second_deriv

    forward_list = []
    for i, (intv, amt, deriv) in enumerate(zip(intervals, f_amounts, derivations)):
        forward_list.append({
            "quarter_index": i + 1,
            "fiscal_label": intv.get("fiscal_label", ""),
            "start": str(intv.get("start")),
            "end": str(intv.get("end")),
            "amount": amt,
            "derivation": deriv,
        })

    return {
        "status": "AVAILABLE",
        "reason": None,
        "warning": None,
        "forward_quarters": forward_list,
        "f1": f_amounts[0], "f2": f_amounts[1], "f3": f_amounts[2], "f4": f_amounts[3],
        "basis_type": "CONSENSUS",
        "consensus": consensus_entry,
    }


def compute_v3_arithmetic(
    reported_actuals: list[float],
    forward_quarters: list[float],
) -> dict[str, Any]:
    """Compute B, amount6, amount12, TTM6, TTM12, change6, change12 according to Section 4.

    Tolerance: abs(a - b) <= 1e-9 * max(1, abs(a), abs(b))
    """
    if len(forward_quarters) != 4:
        return {"status": "INVALID", "error": "FORWARD_QUARTERS_MUST_BE_4"}

    for x in forward_quarters:
        if not is_finite_number(x) or x < 0:
            return {"status": "INVALID", "error": "NON_FINITE_OR_NEGATIVE_FORWARD_AMOUNT"}

    for a in reported_actuals:
        if not is_finite_number(a) or a < 0:
            return {"status": "INVALID", "error": "NON_FINITE_OR_NEGATIVE_ACTUAL"}

    f1, f2, f3, f4 = forward_quarters
    amount6 = f1 + f2
    amount12 = f1 + f2 + f3 + f4

    if not math.isfinite(amount6) or not math.isfinite(amount12):
        return {"status": "INVALID", "error": "OVERFLOW_AMOUNT"}

    if len(reported_actuals) < 4:
        return {
            "status": "MISSING_HISTORY",
            "amount6": amount6,
            "amount12": amount12,
            "baseline_b": None,
            "ttm6": None,
            "ttm12": None,
            "change6": None,
            "change12": None,
            "scenario_status": "NO_BASIS",
            "scenario_reason": "NO_REVENUE_HISTORY",
        }

    a1, a2, a3, a4 = reported_actuals[-4:]
    B = a1 + a2 + a3 + a4
    if B <= 0 or not math.isfinite(B):
        return {
            "status": "INVALID",
            "error": "INVALID_BASELINE_B",
        }

    TTM6 = a3 + a4 + f1 + f2
    TTM12 = f1 + f2 + f3 + f4
    change6 = TTM6 / B - 1.0
    change12 = TTM12 / B - 1.0

    if not math.isfinite(change6) or not math.isfinite(change12):
        return {"status": "INVALID", "error": "OVERFLOW_CHANGE"}

    return {
        "status": "AVAILABLE",
        "amount6": amount6,
        "amount12": amount12,
        "baseline_b": B,
        "ttm6": TTM6,
        "ttm12": TTM12,
        "change6": change6,
        "change12": change12,
        "scenario_status": "AVAILABLE",
        "scenario_reason": None,
    }
