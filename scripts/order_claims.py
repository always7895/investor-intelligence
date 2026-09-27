"""Reviewed, dated order claims from issuer disclosures after (or beside) the periodic filing (Astra contract ORDERS-V2-01;
operator 2026-09-27: "未來訂單預估, 根據現有最新消息隨時修正").

`config/order-claims-v2.json` is a registry of primary documents and the claims they support, not a ticker-to-number
override. Each claim cites its document, locator and a verbatim passage, names its metric, scope, currency, unit and
measurement date, and states how it relates to earlier claims (ORIGINAL, REPLACES, SUPPLEMENTS, CANCELS). A claim may
correct or cancel the periodic filing's RPO itself by targeting `FILING:<accession>`. Nothing here fetches: documents
were captured and verified before a writer added them (receipts stay outside the runtime). Each issuer binds the URL
prefixes of its reviewed publishers (a shared CDN only under the issuer's own path).

Selection at a build cutoff (the sealed document's `generated_at`), per issuer:
- a document counts once it was published, retrieved and reviewed by the cutoff (a date-only publication from the end of
  that UTC day); a claim measured after the cutoff never counts;
- CANCELS removes its targets; REPLACES supersedes its targets (same series: metric, scope, currency, unit and basis);
- the same disclosure mirrored by several documents of one lineage counts once;
- in a stock series (RPO_STOCK, BACKLOG_STOCK) the newest measurement is current, whatever it is (zero, unquantified or a
  range included), and older ones are history; different observations for the same newest date are
  CONFLICTING_DISCLOSURES, never a recency or source-rank pick;
- the company-wide US-dollar RPO series is the one comparable with the filing; two such series current at once are
  ambiguous (CONFLICTING_DISCLOSURES); a RECOGNITION_SCHEDULE counts only for that current stock;
- every other claim (contract value, order intake, guidance, backlog, supplements) is a dated reference, never added.
The same rules run again in cloud/src/v213/order-forecast.ts over the sealed evidence.

Deliberately unsupported (Astra contract amendment, ORDERS-V2-01 revision 2): explicit recognition amounts and
schedules with their own period fields (a schedule's windows are its stock's measurement date + 6 / 12 / 24 months), and
schedules for a backlog or for the filing's own stock. Such claims are refused when the registry is loaded.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parents[1]
REGISTRY_PATH = ROOT / "config" / "order-claims-v2.json"
SCHEMA = "order-claims-v2"
SOURCE_KINDS = ("SEC_PERIODIC", "SEC_8K_EXHIBIT", "ISSUER_EARNINGS_RELEASE", "ISSUER_PREPARED_REMARKS", "ISSUER_CONTRACT_ANNOUNCEMENT")
SEC_FORMS = {"SEC_PERIODIC": ("10-Q", "10-K", "20-F", "40-F"), "SEC_8K_EXHIBIT": ("8-K", "6-K")}
SEC_PREFIX = "https://www.sec.gov/Archives/edgar/data/"
METRICS = ("RPO_STOCK", "BACKLOG_STOCK", "SIGNED_CONTRACT_VALUE", "ORDER_INTAKE", "RECOGNITION_SCHEDULE", "ORDER_GUIDANCE")
STOCK_METRICS = ("RPO_STOCK", "BACKLOG_STOCK")
PERIOD_METRICS = ("ORDER_INTAKE", "ORDER_GUIDANCE")  # flows: a period is required
NO_PERIOD_METRICS = ("RPO_STOCK", "BACKLOG_STOCK", "RECOGNITION_SCHEDULE")  # measured on a date; windows follow from it
PERIOD_KINDS = ("QUARTER", "HALF_YEAR", "YEAR", "MULTI_YEAR", "OTHER")
ASSERTIONS = ("DISCLOSED_FACT", "COMPANY_GUIDANCE")
SCOPES = ("COMPANY", "SEGMENT", "CONTRACT")
REVISIONS = ("ORIGINAL", "REPLACES", "SUPPLEMENTS", "CANCELS")
OVERLAPS = ("DISJOINT_PROVEN", "INCLUDED", "UNKNOWN")
MULTIPLIERS = (1, 1_000, 1_000_000, 1_000_000_000)
CURRENCIES = ("USD", "KRW", "TWD", "SEK", "JPY", "EUR", "GBP", "HKD", "CNY")
SHARE_KEYS = ("m6", "m12", "m24")
FILING_TARGET = "FILING:"
# The filing's RPO is measured under ASC 606; only a company-wide US-dollar RPO on that basis is comparable with it.
FILING_BASIS = "ASC 606"
# Dates outside this range are refused, so date arithmetic (a publication day + 1, a stock + 24 months) never overflows.
MIN_YEAR, MAX_YEAR = 1990, 2100
# Optional fields are omitted, never null (the Worker applies the same rule).
OPTIONAL_CLAIM_FIELDS = ("null_reason", "bounds", "scope_label", "period_start", "period_end", "period_kind", "stock_claim_id",
                         "shares", "summary")
# Per issuer, the characters its evidence adds to the detail (URL, locator, shown quote, summary, scope, revision reason):
# the detail of twenty issuers must fit the LINE limits without cutting evidence (Astra review of revision 2, fix 7).
PRESENTATION_BUDGET = 2400
SHOWN_PASSAGE = 160
MAX_DOCUMENTS, MAX_CLAIMS = 400, 800
# Per issuer, sized so twenty complete cards and every detail fit the LINE limits (Astra review of revision 1, fix 7).
MAX_ISSUER_CLAIMS, MAX_ISSUER_DOCUMENTS = 8, 4
MAX_PASSAGE, MAX_URL, MAX_ID, MAX_LABEL, MAX_SUMMARY = 1000, 400, 120, 160, 60
MAX_VALUE = 1e16
ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,119}$")
SYMBOL = re.compile(r"^[A-Z0-9][A-Z0-9.\-]{0,19}$")
SHA256 = re.compile(r"^[0-9a-f]{64}$")
ACCESSION = re.compile(r"^[0-9]{10}-[0-9]{2}-[0-9]{6}$")
DAY = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$")
INSTANT = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$")
HOST = r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)*\.[a-z]{2,63}"
PREFIX = re.compile(r"^https://" + HOST + r"/(?:[A-Za-z0-9._~-]+/)*$")
URL = re.compile(r"^https://" + HOST + r"/[\x21-\x7e]*$")
# One text policy for Python and the Worker (cloud/src/v213/order-forecast.ts cleanText): refused are C0, DEL, C1,
# line/paragraph separators, zero-width, bidirectional and other format characters, the byte-order mark and any
# surrogate (Python strings hold supplementary-plane characters as one code point, so a surrogate here is unpaired);
# a text is blank when nothing remains after removing the listed spaces (not str.strip, whose set differs from
# JavaScript's trim).
FORBIDDEN_CHARS = re.compile("[\x00-\x1f\x7f-\x9f\u180e\u200b-\u200f\u2028-\u202e\u2060-\u206f\ufeff\ud800-\udfff]")
SPACES = re.compile("[ \u00a0\u1680\u2000-\u200a\u202f\u205f\u3000]")


class RegistryError(ValueError):
    """The registry is malformed; the message names the first problem."""


def _fail(message: str) -> None:
    raise RegistryError(message)


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in pairs:
        if key in out:
            _fail(f"DUPLICATE_KEY {str(key)[:40]}")
        out[key] = value
    return out


def day(value: Any) -> date | None:
    if not isinstance(value, str) or not DAY.match(value) or not MIN_YEAR <= int(value[:4]) <= MAX_YEAR:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def instant(value: Any) -> datetime | None:
    if not isinstance(value, str) or not INSTANT.match(value) or not MIN_YEAR <= int(value[:4]) <= MAX_YEAR:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def number(value: Any) -> float | None:
    """A finite, non-boolean number within +/-MAX_VALUE, else None (never an overflow)."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if isinstance(value, int) and abs(value) > MAX_VALUE:
        return None
    result = float(value)
    return result if math.isfinite(result) and abs(result) <= MAX_VALUE else None


def clean_text(value: Any, limit: int) -> str | None:
    if not isinstance(value, str) or FORBIDDEN_CHARS.search(value) or not SPACES.sub("", value) or len(value) > limit:
        return None
    return value


def _text(value: Any, limit: int, what: str, *, optional: bool = False) -> str | None:
    if value is None and optional:
        return None
    if clean_text(value, limit) is None:
        _fail(f"BAD_TEXT {what}")
    return value


def _ident(value: Any, what: str) -> str:
    if not isinstance(value, str) or not ID.match(value):
        _fail(f"BAD_ID {what}")
    return value


def _object(value: Any, what: str) -> dict:
    if not isinstance(value, dict):
        _fail(f"NOT_AN_OBJECT {what}")
    return value


def _keys(raw: Mapping[str, Any], required: tuple[str, ...], optional: tuple[str, ...], what: str) -> None:
    missing = [key for key in required if key not in raw]
    extra = [key for key in raw if key not in required and key not in optional]
    if missing or extra:
        _fail(f"BAD_FIELDS {what} missing={missing[:3]} extra={[str(k)[:20] for k in extra[:3]]}")


def url_ok(value: Any, prefixes: list[str]) -> bool:
    """A plain https URL under a reviewed prefix whose path cannot leave it: no dot segments, empty segments,
    backslashes or percent-encoded dots, slashes or backslashes (a URL consumer would normalize those)."""
    if not isinstance(value, str) or len(value) > MAX_URL or not URL.match(value) or "#" in value or "\\" in value:
        return False
    path = value[8:].split("/", 1)[1].split("?", 1)[0] if "/" in value[8:] else ""
    segments = path.split("/")
    if any(segment in (".", "..") for segment in segments) or "//" in "/" + path \
            or any(code in value.lower() for code in ("%2e", "%2f", "%5c")):
        return False
    return any(value.startswith(prefix) for prefix in prefixes)


def eligible_at(document: Mapping[str, Any]) -> datetime:
    """When a document may count: its stated publication instant, else the end of its publication day (UTC)."""
    stated = instant(document.get("published_at"))
    if stated is not None:
        return stated
    return datetime.combine(day(document["published_date"]) + timedelta(days=1), datetime.min.time(), tzinfo=timezone.utc)


def value_of(claim: Mapping[str, Any]) -> float | None:
    amount = number(claim.get("amount"))
    return None if amount is None else amount * claim["unit_multiplier"]


def _canonical(value: Any) -> Any:
    """Numbers as floats, so 30, 30.0 and 3e1 are one value, and zero is unsigned (-0.0 + 0.0 == +0.0): JavaScript keeps
    neither distinction when it serializes."""
    if isinstance(value, Mapping):
        return {key: _canonical(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_canonical(item) for item in value]
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value) + 0.0
    return value


def observation(claim: Mapping[str, Any]) -> str:
    """What a claim observed, for mirror and conflict comparison: its value, its bounds or its shares (numbers compared by
    value, never by their JSON spelling)."""
    return json.dumps(_canonical([value_of(claim), claim.get("bounds"), claim.get("shares")]), sort_keys=True)


def series_dims(claim: Mapping[str, Any]) -> list:
    return [claim["symbol"], claim["metric"], claim["scope"], claim.get("scope_label"), claim["currency"],
            claim["unit_multiplier"], claim["basis"]]


def _document(raw: Any, issuers: Mapping[str, Any]) -> dict[str, Any]:
    raw = _object(raw, "document")
    _keys(raw, ("id", "issuer", "publisher", "title", "source_kind", "url", "published_date", "retrieved_at", "sha256",
                "byte_size", "lineage_id"), ("published_at", "sec"), "document")
    doc_id = _ident(raw["id"], "document.id")
    if any(key in raw and raw[key] is None for key in ("published_at", "sec")):
        _fail(f"NULL_OPTIONAL_FIELD {doc_id}")
    if not isinstance(raw["issuer"], str) or raw["issuer"] not in issuers:
        _fail(f"UNKNOWN_ISSUER {doc_id}")
    _text(raw["publisher"], MAX_LABEL, "publisher")
    _text(raw["title"], MAX_LABEL, "title")
    kind = raw["source_kind"]
    if kind not in SOURCE_KINDS:
        _fail(f"BAD_SOURCE_KIND {doc_id}")
    prefixes = [SEC_PREFIX] if kind in SEC_FORMS else issuers[raw["issuer"]]["url_prefixes"]
    if not url_ok(raw["url"], prefixes):
        _fail(f"UNREVIEWED_URL {doc_id}")
    published = day(raw["published_date"])
    if published is None:
        _fail(f"BAD_PUBLISHED {doc_id}")
    if "published_at" in raw and (instant(raw["published_at"]) is None or instant(raw["published_at"]).date() != published):
        _fail(f"BAD_PUBLISHED_AT {doc_id}")
    retrieved = instant(raw["retrieved_at"])
    if retrieved is None or retrieved < datetime.combine(published, datetime.min.time(), tzinfo=timezone.utc):
        _fail(f"BAD_RETRIEVED {doc_id}")
    if not isinstance(raw["sha256"], str) or not SHA256.match(raw["sha256"]):
        _fail(f"BAD_SHA256 {doc_id}")
    size = raw["byte_size"]
    if isinstance(size, bool) or not isinstance(size, int) or not 0 < size <= 50_000_000:
        _fail(f"BAD_SIZE {doc_id}")
    _ident(raw["lineage_id"], "lineage_id")
    if kind in SEC_FORMS:
        sec = _object(raw.get("sec"), "sec")
        _keys(sec, ("accession", "form") + (("exhibit",) if kind == "SEC_8K_EXHIBIT" else ()), (), "sec")
        if not isinstance(sec["accession"], str) or not ACCESSION.match(sec["accession"]) or sec["form"] not in SEC_FORMS[kind]:
            _fail(f"BAD_SEC {doc_id}")
        if kind == "SEC_8K_EXHIBIT":
            _text(sec["exhibit"], 20, "exhibit")
    elif "sec" in raw:
        _fail(f"SEC_FIELDS_INVENTED {doc_id}")
    return raw


def _claim(raw: Any, documents: Mapping[str, dict[str, Any]]) -> dict[str, Any]:
    raw = _object(raw, "claim")
    _keys(raw, ("id", "symbol", "document_id", "locator", "passage", "metric", "assertion_kind", "currency", "unit_multiplier",
                "amount", "as_of", "scope", "series_id", "basis", "revision", "review"),
          ("null_reason", "bounds", "scope_label", "period_start", "period_end", "period_kind", "stock_claim_id", "shares",
           "summary"), "claim")
    claim_id = _ident(raw["id"], "claim.id")
    if any(key in raw and raw[key] is None for key in OPTIONAL_CLAIM_FIELDS):
        _fail(f"NULL_OPTIONAL_FIELD {claim_id}")
    document = documents.get(raw["document_id"]) if isinstance(raw["document_id"], str) else None
    if document is None:
        _fail(f"DANGLING_DOCUMENT {claim_id}")
    if not isinstance(raw["symbol"], str) or not SYMBOL.match(raw["symbol"]) or raw["symbol"] != document["issuer"]:
        _fail(f"ISSUER_MISMATCH {claim_id}")
    _text(raw["locator"], MAX_LABEL, "locator")
    _text(raw["passage"], MAX_PASSAGE, "passage")
    _text(raw.get("summary"), MAX_SUMMARY, "summary", optional=True)
    metric = raw["metric"]
    if metric not in METRICS or raw["assertion_kind"] not in ASSERTIONS or raw["scope"] not in SCOPES \
            or raw["currency"] not in CURRENCIES or isinstance(raw["unit_multiplier"], bool) or raw["unit_multiplier"] not in MULTIPLIERS:
        _fail(f"BAD_ENUM {claim_id}")
    if (metric == "ORDER_GUIDANCE") != (raw["assertion_kind"] == "COMPANY_GUIDANCE"):
        _fail(f"GUIDANCE_TYPING {claim_id}")
    amount, bounds = raw["amount"], raw.get("bounds")
    if amount is None:
        if metric != "RECOGNITION_SCHEDULE" or "null_reason" in raw:
            _text(raw.get("null_reason"), MAX_LABEL, "null_reason")
    else:
        value = number(amount)
        if value is None or value < 0 or value * raw["unit_multiplier"] > MAX_VALUE or "null_reason" in raw or bounds is not None:
            _fail(f"BAD_AMOUNT {claim_id}")
    if bounds is not None:
        if not isinstance(bounds, dict) or not bounds or set(bounds) - {"lower", "upper"} or metric == "RECOGNITION_SCHEDULE" \
                or any(number(v) is None or number(v) < 0 or number(v) * raw["unit_multiplier"] > MAX_VALUE for v in bounds.values()) \
                or ("lower" in bounds and "upper" in bounds and number(bounds["lower"]) > number(bounds["upper"])):
            _fail(f"BAD_BOUNDS {claim_id}")
    if day(raw["as_of"]) is None:
        _fail(f"BAD_AS_OF {claim_id}")
    if raw["scope"] != "COMPANY":
        _text(raw.get("scope_label"), MAX_LABEL, "scope_label")
    elif "scope_label" in raw:
        _fail(f"COMPANY_SCOPE_LABEL {claim_id}")
    has_period = any(key in raw for key in ("period_start", "period_end", "period_kind"))
    if metric in PERIOD_METRICS and not has_period or metric in NO_PERIOD_METRICS and has_period:
        _fail(f"PERIOD_FIELDS {claim_id}")
    if has_period:
        start, end = day(raw.get("period_start")), day(raw.get("period_end"))
        if start is None or end is None or end <= start or raw.get("period_kind") not in PERIOD_KINDS:
            _fail(f"BAD_PERIOD {claim_id}")
    _ident(raw["series_id"], "series_id")
    _text(raw["basis"], MAX_LABEL, "basis")
    if metric == "RECOGNITION_SCHEDULE":
        shares = raw.get("shares")
        _ident(raw.get("stock_claim_id"), "stock_claim_id")
        if raw["stock_claim_id"].startswith(FILING_TARGET) or amount is not None or not isinstance(shares, dict) or not shares \
                or set(shares) - set(SHARE_KEYS):
            _fail(f"BAD_SCHEDULE {claim_id}")
        stated = [number(shares[key]) for key in SHARE_KEYS if key in shares]
        if any(v is None or not 0 < v <= 100 for v in stated) or any(b < a for a, b in zip(stated, stated[1:])):
            _fail(f"BAD_SHARES {claim_id}")
    elif "shares" in raw or "stock_claim_id" in raw:
        _fail(f"SCHEDULE_FIELDS {claim_id}")
    revision = _object(raw["revision"], "revision")
    _keys(revision, ("kind",), ("targets", "reason", "overlap"), "revision")
    kind = revision["kind"]
    if kind not in REVISIONS:
        _fail(f"BAD_REVISION {claim_id}")
    targets = revision.get("targets", [])
    if not isinstance(targets, list) or len(targets) > 8 or not all(isinstance(t, str) for t in targets) or len(set(targets)) != len(targets):
        _fail(f"BAD_TARGETS {claim_id}")
    for target in targets:
        if target.startswith(FILING_TARGET):
            if not ACCESSION.match(target[len(FILING_TARGET):]) or kind not in ("REPLACES", "CANCELS") or metric != "RPO_STOCK" \
                    or raw["scope"] != "COMPANY" or raw["currency"] != "USD" or raw["basis"] != FILING_BASIS:
                _fail(f"BAD_FILING_TARGET {claim_id}")
        else:
            _ident(target, "target")
    if kind == "ORIGINAL" and (targets or "overlap" in revision or "reason" in revision):
        _fail(f"ORIGINAL_WITH_TARGETS {claim_id}")
    if kind in ("REPLACES", "CANCELS"):
        if not targets or "overlap" in revision:
            _fail(f"REVISION_TARGETS {claim_id}")
        _text(revision.get("reason"), MAX_LABEL, "revision.reason")
    if kind == "SUPPLEMENTS":
        if revision.get("overlap") not in OVERLAPS or "reason" in revision:
            _fail(f"SUPPLEMENT_OVERLAP {claim_id}")
    review = _object(raw["review"], "review")
    _keys(review, ("checked_at", "receipt"), (), "review")
    checked = instant(review["checked_at"])
    if checked is None or checked < instant(document["retrieved_at"]):
        _fail(f"BAD_CHECKED_AT {claim_id}")
    _ident(review["receipt"], "review.receipt")
    return raw


def validate(raw: Any) -> dict[str, Any]:
    """The registry, fully checked (structure, bounds, links and the revision graph); RegistryError otherwise."""
    raw = _object(raw, "registry")
    _keys(raw, ("schema", "issuers", "documents", "claims"), (), "registry")
    if raw["schema"] != SCHEMA:
        _fail("WRONG_SCHEMA")
    issuers, documents, claims = raw["issuers"], raw["documents"], raw["claims"]
    if not isinstance(issuers, dict) or not isinstance(documents, list) or not isinstance(claims, list):
        _fail("BAD_TOP_LEVEL")
    if len(issuers) > 100 or len(documents) > MAX_DOCUMENTS or len(claims) > MAX_CLAIMS:
        _fail("REGISTRY_TOO_LARGE")
    for symbol, issuer in issuers.items():
        if not SYMBOL.match(symbol):
            _fail("BAD_ISSUER")
        issuer = _object(issuer, "issuer")
        _keys(issuer, ("name", "url_prefixes"), (), "issuer")
        _text(issuer["name"], MAX_LABEL, "issuer.name")
        prefixes = issuer["url_prefixes"]
        if not isinstance(prefixes, list) or not 0 < len(prefixes) <= 4 \
                or not all(isinstance(p, str) and len(p) <= 120 and PREFIX.match(p) and not p.startswith("https://www.sec.gov/") for p in prefixes):
            _fail(f"BAD_URL_PREFIXES {symbol}")
    by_document: dict[str, dict[str, Any]] = {}
    for document in documents:
        checked = _document(document, issuers)
        if checked["id"] in by_document:
            _fail(f"DUPLICATE_DOCUMENT {checked['id']}")
        by_document[checked["id"]] = checked
    by_claim: dict[str, dict[str, Any]] = {}
    for claim in claims:
        checked = _claim(claim, by_document)
        if checked["id"] in by_claim:
            _fail(f"DUPLICATE_CLAIM {checked['id']}")
        by_claim[checked["id"]] = checked
    series: dict[str, list] = {}
    for claim in by_claim.values():
        if series.setdefault(claim["series_id"], series_dims(claim)) != series_dims(claim):
            _fail(f"SERIES_DIMENSIONS {claim['series_id']}")
        if claim["metric"] == "RECOGNITION_SCHEDULE":
            stock = by_claim.get(claim["stock_claim_id"])
            if stock is None or stock["metric"] != "RPO_STOCK" or stock["symbol"] != claim["symbol"] \
                    or stock["currency"] != claim["currency"] or stock["scope"] != "COMPANY" or claim["scope"] != "COMPANY" \
                    or stock["as_of"] != claim["as_of"] or stock["basis"] != claim["basis"] \
                    or stock["document_id"] != claim["document_id"] and \
                    eligible_at(by_document[stock["document_id"]]) > eligible_at(by_document[claim["document_id"]]):
                _fail(f"SCHEDULE_STOCK {claim['id']}")
        for target_id in claim["revision"].get("targets", []):
            if target_id.startswith(FILING_TARGET):
                continue
            target = by_claim.get(target_id)
            if target is None or target_id == claim["id"] or target["series_id"] != claim["series_id"]:
                _fail(f"BAD_TARGET {claim['id']}")
            if eligible_at(by_document[target["document_id"]]) > eligible_at(by_document[claim["document_id"]]):
                _fail(f"TARGET_NEWER {claim['id']}")
    _acyclic(by_claim)
    return raw


def _acyclic(by_claim: Mapping[str, Mapping[str, Any]]) -> None:
    state: dict[str, int] = {}

    def visit(node: str) -> None:
        if state.get(node) == 1:
            _fail(f"REVISION_CYCLE {node}")
        if state.get(node) == 2:
            return
        state[node] = 1
        for target in by_claim[node]["revision"].get("targets", []):
            if target in by_claim:
                visit(target)
        state[node] = 2
    for node in by_claim:
        visit(node)


def load(path: Path | None = None) -> dict[str, Any]:
    """{"status": OK | EMPTY | UNAVAILABLE | INVALID, "sha256", "registry", "reason"}; never raises. The default path is
    read at call time (REGISTRY_PATH), so a caller or test can point it elsewhere."""
    try:
        raw_bytes = (path or REGISTRY_PATH).read_bytes()
    except OSError:
        return {"status": "UNAVAILABLE", "sha256": None, "registry": None, "reason": "CLAIM_REGISTRY_UNAVAILABLE"}
    digest = hashlib.sha256(raw_bytes).hexdigest()
    try:
        registry = validate(json.loads(raw_bytes.decode("utf-8"), object_pairs_hook=_unique_object))
    except RegistryError as error:
        return {"status": "INVALID", "sha256": digest, "registry": None, "reason": f"INVALID_REGISTRY {str(error)[:80]}"}
    except Exception as error:  # noqa: BLE001 - malformed external JSON never escapes as an exception
        return {"status": "INVALID", "sha256": digest, "registry": None, "reason": f"INVALID_REGISTRY {type(error).__name__}"}
    return {"status": "OK" if registry["claims"] else "EMPTY", "sha256": digest, "registry": registry, "reason": None}


def select(documents: list[Mapping[str, Any]], claims: list[Mapping[str, Any]], cutoff: datetime,
           filing: Mapping[str, str] | None = None) -> dict[str, Any]:
    """Selection over one issuer's documents and claims at `cutoff`, with the periodic filing ({"accession", "filed"} or
    None): {"status", "active", "current_stock", "schedule", "filing", "excluded": [[id, reason]]}. A claim targeting
    FILING:<accession> resolves only against that filing and only when published after it; anything else is
    UNRESOLVED_REVISION. Deterministic, and the same function the Worker runs over the sealed evidence."""
    docs = {document["id"]: document for document in documents}
    excluded: dict[str, str] = {}
    eligible = []
    for claim in sorted(claims, key=lambda c: c["id"]):
        document = docs[claim["document_id"]]
        if eligible_at(document) > cutoff or instant(document["retrieved_at"]) > cutoff \
                or instant(claim["checked_at"]) > cutoff or day(claim["as_of"]) > cutoff.date():
            excluded[claim["id"]] = "AFTER_CUTOFF"
        else:
            eligible.append(claim)
    live = {claim["id"] for claim in eligible}
    filing_state = "ACTIVE" if filing else None
    status = "OK"
    for claim in eligible:
        kind = claim["revision"]["kind"]
        for target in claim["revision"].get("targets", []):
            reason = "CANCELLED" if kind == "CANCELS" else "SUPERSEDED" if kind == "REPLACES" else None
            if target.startswith(FILING_TARGET):
                if filing and target == FILING_TARGET + filing["accession"] \
                        and docs[claim["document_id"]]["published_date"] >= filing["filed"]:
                    filing_state = reason
                else:  # another, an unknown or a later filing: the relationship cannot be resolved here
                    status = "UNRESOLVED_REVISION"
                    excluded[claim["id"]] = "UNRESOLVED_FILING_TARGET"
            elif reason and target in live:
                excluded[target] = reason
    candidates = [claim for claim in eligible if claim["id"] not in excluded]
    seen: set[tuple] = set()
    for claim in candidates:  # one disclosure mirrored by several documents of a lineage counts once
        key = (docs[claim["document_id"]]["lineage_id"], claim["series_id"], claim["as_of"], observation(claim))
        if key in seen:
            excluded[claim["id"]] = "MIRROR"
        else:
            seen.add(key)
    candidates = [claim for claim in candidates if claim["id"] not in excluded]
    current: dict[str, Mapping[str, Any]] = {}
    for series_id in sorted({c["series_id"] for c in candidates if c["metric"] in STOCK_METRICS}):
        rows = sorted((c for c in candidates if c["series_id"] == series_id), key=lambda c: (c["as_of"], c["id"]))
        newest = rows[-1]["as_of"]
        tops = [c for c in rows if c["as_of"] == newest]
        for row in rows:
            if row["as_of"] != newest:
                excluded[row["id"]] = "HISTORY"
        if len({observation(c) for c in tops}) > 1:
            status = "CONFLICTING_DISCLOSURES" if status == "OK" else status
            for row in tops:
                excluded[row["id"]] = "CONFLICT"
        else:
            current[series_id] = tops[0]
            for row in tops[1:]:
                excluded[row["id"]] = "MIRROR"
    comparable = [c for c in current.values() if c["metric"] == "RPO_STOCK" and c["scope"] == "COMPANY"
                  and c["currency"] == "USD" and c["assertion_kind"] == "DISCLOSED_FACT" and c["basis"] == FILING_BASIS]
    stock = None
    if len(comparable) > 1:
        status = "CONFLICTING_DISCLOSURES" if status == "OK" else status
        for row in comparable:
            excluded[row["id"]] = "AMBIGUOUS_SERIES"
    elif comparable:
        stock = comparable[0]
    # Equal observations of the current stock (mirrors or independent documents) are one observation: every schedule
    # attached to any of them is compared, so a contradiction never hides behind an alias and no id decides the result.
    aliases = set()
    if stock is not None:
        aliases = {c["id"] for c in eligible if c["series_id"] == stock["series_id"] and c["as_of"] == stock["as_of"]
                   and observation(c) == observation(stock) and excluded.get(c["id"]) in (None, "MIRROR")}
    attached = [c for c in eligible if c["metric"] == "RECOGNITION_SCHEDULE" and excluded.get(c["id"]) in (None, "MIRROR")
                and c["stock_claim_id"] in aliases]
    for claim in candidates:
        if claim["metric"] == "RECOGNITION_SCHEDULE" and claim["id"] not in excluded and claim not in attached:
            excluded[claim["id"]] = "STOCK_NOT_CURRENT"
    schedules = []
    if len({observation(c) for c in attached}) > 1:
        status = "CONFLICTING_DISCLOSURES" if status == "OK" else status
        for row in attached:
            excluded[row["id"]] = "CONFLICT"
    elif attached:
        schedules = [min(attached, key=lambda c: c["id"])]
        for row in attached:
            if row["id"] != schedules[0]["id"]:
                excluded[row["id"]] = "MIRROR"
            else:
                excluded.pop(row["id"], None)
    active = sorted(claim["id"] for claim in eligible if claim["id"] not in excluded)
    return {"status": status, "active": active, "current_stock": stock["id"] if stock else None,
            "schedule": schedules[0]["id"] if schedules else None, "filing": filing_state,
            "excluded": sorted([claim_id, reason] for claim_id, reason in excluded.items())}


def issuer_evidence(loaded: Mapping[str, Any], symbol: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[str], str | None]:
    """(documents, claims with their public check time, url_prefixes, limit_reason) of one issuer from a loaded registry."""
    registry = loaded.get("registry") or {"documents": [], "claims": [], "issuers": {}}
    claims = [{**{k: v for k, v in c.items() if k != "review"}, "checked_at": c["review"]["checked_at"]}
              for c in registry["claims"] if c["symbol"] == symbol]
    wanted = {c["document_id"] for c in claims}
    documents = [dict(d) for d in registry["documents"] if d["id"] in wanted]
    prefixes = list((registry.get("issuers") or {}).get(symbol, {}).get("url_prefixes", []))
    if len(claims) > MAX_ISSUER_CLAIMS or len(documents) > MAX_ISSUER_DOCUMENTS or presentation_size(documents, claims) > PRESENTATION_BUDGET:
        return [], [], prefixes, "EVIDENCE_LIMIT"
    return documents, claims, prefixes, None


def _units(value: Any) -> int:
    """UTF-16 code units, the length LINE text limits and the Worker measure (a supplementary-plane character is two)."""
    return len(value.encode("utf-16-le")) // 2 if isinstance(value, str) else 0


def presentation_size(documents: list[Mapping[str, Any]], claims: list[Mapping[str, Any]]) -> int:
    """UTF-16 units the claims add to the detail: document URL, locator, the shown part of the quote, summary, scope label
    and revision reason of each claim (cloud/src/v213/order-forecast.ts presentationSize is the same rule)."""
    urls = {document["id"]: document["url"] for document in documents}
    return sum(_units(urls[c["document_id"]]) + _units(c["locator"]) + _units(c["passage"][:SHOWN_PASSAGE]) + _units(c.get("summary"))
               + _units(c.get("scope_label")) + _units(c["revision"].get("reason")) for c in claims)
