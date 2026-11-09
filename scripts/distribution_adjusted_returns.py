"""Cash-held shareholder-entitlement returns, gated by independently reviewed inputs.

An evidence document cannot approve itself. The controlled corporate-action registry
may pin an exact input digest and every underlying primary document digest after
review of identity, prices, action-ledger completeness and public derived-data rights.
An empty/unavailable approval preserves NULL, including for seemingly official URLs.
No real MOD historical-price or rights receipt is currently registered.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation, localcontext
from typing import Any
from urllib.parse import urlsplit

RESEARCH_BENCHMARK_SHARES = 100000
MOD_THERMAL_EX_DATE = date(2026, 10, 2)
MOD_SOURCE = "https://www.sec.gov/Archives/edgar/data/67347/000110465926112870/tm2626618d1_8k.htm"
MOD_TERMS_SOURCE = "https://www.sec.gov/Archives/edgar/data/67347/000110465926108614/tm2625565d1_ex99-1.htm"
THRM_FINAL_SOURCE = "https://www.sec.gov/Archives/edgar/data/903129/000119312526410776/d214921dex991.htm"
UNAVAILABLE_REASON_ZH = (
    "尚缺可核對的一手歷史收盤價、完整配息與拆股紀錄及衍生報酬公開使用權；"
    "零股另須實際淨現金證明，跨配發權益日報酬暫不顯示。"
)
WINDOWS = {"ret_6m": (182, False), "ret_1y": (365, False), "cagr_2y": (730, True)}
SHA256 = re.compile(r"[0-9a-f]{64}\Z")
RECEIPT_FIELDS = frozenset({
    "evidence_sha256", "approved_on", "rights_scope", "primary_documents",
})


def _day(value: Any) -> date | None:
    if not isinstance(value, str):
        return None
    try:
        day = date.fromisoformat(value)
    except ValueError:
        return None
    return day if day.isoformat() == value else None


def _decimal(value: Any, *, positive: bool = False) -> Decimal | None:
    if type(value) not in (int, float, str) or len(str(value)) > 64:
        return None
    try:
        number = Decimal(str(value))
    except InvalidOperation:
        return None
    if not number.is_finite() or number < 0 or (positive and number == 0):
        return None
    return number if number == 0 or -12 <= number.adjusted() <= 12 else None


def _digest(value: Any) -> str | None:
    try:
        raw = json.dumps(value, sort_keys=True, separators=(",", ":"),
                         ensure_ascii=True, allow_nan=False).encode("utf-8")
    except (TypeError, ValueError, UnicodeError, RecursionError):
        return None
    return hashlib.sha256(raw).hexdigest()


def _primary_url(value: Any) -> bool:
    if not isinstance(value, str) or len(value) > 400 or any(ord(c) < 33 for c in value):
        return False
    try:
        parsed = urlsplit(value)
        return (parsed.scheme == "https" and parsed.hostname in {
            "www.sec.gov", "www.nyse.com", "www.nasdaq.com", "api.nasdaq.com",
        } and parsed.port is None and not parsed.username and not parsed.password
            and not parsed.fragment and bool(parsed.path))
    except ValueError:
        return False


def entitlement_ex_date(action: dict[str, Any]) -> date | None:
    """Known primary terms, not an ex-date asserted by a caller's pricing file.

    The September 17 SEC exhibit states due bills September 28 through October 1
    inclusive, ex-spin October 2. The October 1 8-K confirms actual completion.
    A generic distribution without reviewed ex-date terms remains conservative.
    """
    if (action.get("kind") == "DISTRIBUTION" and action.get("status") == "CLOSED"
            and action.get("target_symbol") == "MOD" and action.get("related_symbol") == "THRM"
            and action.get("distribution_date") == "2026-10-01"
            and action.get("source_date") == "2026-10-01"
            and action.get("source_url") == MOD_SOURCE
            and _decimal(action.get("shares_per_share")) == Decimal("0.44619")):
        return MOD_THERMAL_EX_DATE
    return None


def _crosses(start: date | None, end: date, action: dict[str, Any]) -> bool:
    ex = entitlement_ex_date(action)
    event = _day(action.get("distribution_date"))
    if ex is not None:
        return (start is None or start < ex) and ex <= end
    # With no reviewed trading terms, neither an event-day start nor a missing
    # start is proof of ex-entitlement prices. Do not infer an ex-date.
    return event is None or (event <= end and (start is None or start <= event))


def suppress_unproven_distribution_returns(market: dict[str, Any],
                                          distributions: list[dict[str, Any]]) -> dict[str, Any]:
    """Canonical fail-closed guard, independent of ranking/publisher imports."""
    if not distributions:
        return dict(market)
    asof = _day(market.get("asof"))
    if asof is None:
        raise ValueError("DISTRIBUTION_MARKET_ASOF")
    result = dict(market)
    # A prior overlay is never its own authorization on replay.
    for key in ("distribution_adjustment", "distribution_evidence",
                "distribution_adjusted_candidates", "distribution_unavailable_reason_zh"):
        result.pop(key, None)
    reasons = dict(result.get("return_reasons") or {})
    for action in distributions:
        for key, (days, _) in WINDOWS.items():
            if _crosses(asof - timedelta(days=days), asof, action):
                result[key] = None
                reasons[key] = "DISTRIBUTION_IN_WINDOW"
                if key == "cagr_2y" and result.get("long_term_basis") == "TWO_YEAR":
                    result["long_term_basis"] = "UNAVAILABLE"
        since = _day(result.get("cagr_listed_start"))
        if (result.get("cagr_listed") is not None or "cagr_listed" in reasons) and _crosses(since, asof, action):
            result["cagr_listed"] = None
            result["cagr_listed_start"] = None
            result["cagr_listed_span_days"] = None
            result["long_term_basis"] = "UNAVAILABLE"
            reasons["cagr_listed"] = "DISTRIBUTION_IN_WINDOW"
    if reasons:
        result["return_reasons"] = reasons
    if any(value == "DISTRIBUTION_IN_WINDOW" for value in reasons.values()):
        result["distribution_unavailable_reason_zh"] = UNAVAILABLE_REASON_ZH
    return result


def validate_entitlement_receipts(value: Any) -> None:
    """Validate optional installed-registry authority, never evidence-file flags.

    Each receipt pins the complete v2 window (including document bodies), explicit
    public-derived-return rights and the independently reviewed primary documents.
    Only the controlled/captured registry may supply these receipts to the APIs.
    """
    if type(value) is not list or len(value) > 30:
        raise ValueError("ENTITLEMENT_RECEIPTS")
    seen = set()
    for receipt in value:
        if (type(receipt) is not dict or set(receipt) != RECEIPT_FIELDS
                or not isinstance(receipt.get("evidence_sha256"), str)
                or not SHA256.fullmatch(receipt["evidence_sha256"])
                or receipt["evidence_sha256"] in seen
                or _day(receipt.get("approved_on")) is None
                or receipt.get("rights_scope") != "PUBLIC_DERIVED_RETURN"):
            raise ValueError("ENTITLEMENT_RECEIPT")
        seen.add(receipt["evidence_sha256"])
        documents = receipt.get("primary_documents")
        if type(documents) is not list or not 4 <= len(documents) <= 20:
            raise ValueError("ENTITLEMENT_RECEIPT_DOCUMENTS")
        urls = set()
        for doc in documents:
            if (type(doc) is not dict or set(doc) != {"source_url", "sha256"}
                    or not _primary_url(doc.get("source_url"))
                    or not isinstance(doc.get("sha256"), str)
                    or not SHA256.fullmatch(doc["sha256"])
                    or doc["source_url"] in urls):
                raise ValueError("ENTITLEMENT_RECEIPT_DOCUMENT")
            urls.add(doc["source_url"])


def _validated_documents(action: dict[str, Any], evidence: dict[str, Any],
                         end: date, *, require_receipt: bool) -> dict[str, dict[str, Any]] | None:
    receipts = action.get("entitlement_receipts", [])
    try:
        validate_entitlement_receipts(receipts)
    except ValueError:
        return None
    digest = _digest(evidence)
    if digest is None:
        return None
    approved = next((r for r in receipts if r["evidence_sha256"] == digest
                     and _day(r["approved_on"]) <= end), None)
    if require_receipt and approved is None:
        return None
    raw = evidence.get("primary_documents")
    if type(raw) is not list or not 4 <= len(raw) <= 20:
        return None
    if approved is not None and len(raw) != len(approved["primary_documents"]):
        return None
    pins = {d["source_url"]: d["sha256"] for d in approved["primary_documents"]} if approved else None
    documents = {}
    urls = set()
    for doc in raw:
        if (type(doc) is not dict or set(doc) != {
                "id", "role", "source_url", "source_date", "body", "sha256"}
                or not isinstance(doc.get("id"), str) or not 1 <= len(doc["id"]) <= 40
                or doc["id"] in documents or not _primary_url(doc.get("source_url")) or doc["source_url"] in urls
                or not isinstance(doc.get("role"), str)
                or doc["role"] not in {"PRICE", "TERMS", "RIGHTS", "ACTION_LEDGER", "CASH_IN_LIEU"}
                or not isinstance(doc.get("body"), str)
                or not 1 <= len(doc["body"]) <= 256 * 1024
                or _day(doc.get("source_date")) is None
                or _day(doc["source_date"]) > end
                or (approved is not None and _day(doc["source_date"]) > _day(approved["approved_on"]))):
            return None
        actual = hashlib.sha256(doc["body"].encode("utf-8")).hexdigest()
        if doc.get("sha256") != actual or (pins is not None and pins.pop(doc["source_url"], None) != actual):
            return None
        documents[doc["id"]] = doc
        urls.add(doc["source_url"])
    if pins or not {"PRICE", "TERMS", "RIGHTS", "ACTION_LEDGER"} <= {d["role"] for d in documents.values()}:
        return None
    if not {MOD_SOURCE, MOD_TERMS_SOURCE, THRM_FINAL_SOURCE} <= {d["source_url"] for d in documents.values() if d["role"] == "TERMS"}:
        return None
    return documents


def _observation(raw: Any, *, symbol: str, day: date, documents: dict[str, dict[str, Any]]) -> Decimal | None:
    if type(raw) is not dict or set(raw) != {
        "symbol", "security_id", "day", "currency", "price_basis", "split_basis",
        "close", "document_id", "source_excerpt",
    }:
        return None
    doc = documents.get(raw.get("document_id")) if isinstance(raw.get("document_id"), str) else None
    identities = {"MOD": "CIK:0000067347", "THRM": "CIK:0000903129"}
    hosts = {"MOD": {"www.nyse.com"}, "THRM": {"www.nasdaq.com", "api.nasdaq.com"}}
    excerpt = raw.get("source_excerpt")
    if (doc is None or doc["role"] != "PRICE" or raw.get("symbol") != symbol
            or raw.get("security_id") != identities.get(symbol)
            or raw.get("day") != day.isoformat() or raw.get("currency") != "USD"
            or raw.get("price_basis") != "UNADJUSTED_OFFICIAL"
            or raw.get("split_basis") != "AS_TRADED"
            or urlsplit(doc["source_url"]).hostname not in hosts.get(symbol, set())
            or _day(doc["source_date"]) < day
            or not isinstance(excerpt, str) or not excerpt or excerpt not in doc["body"]):
        return None
    return _decimal(raw.get("close"), positive=True)


def calculate_entitled_return(action: dict[str, Any], evidence: dict[str, Any], *,
                              start_day: date, end_day: date) -> dict[str, Any] | None:
    """Calculate a research scenario; a result alone NEVER authorizes publication.

    v2 source bodies, hashes, quoted excerpts, security/date/currency/basis and
    action ledgers must be consistent. Without independent controlled-registry
    approval these remain caller-supplied research observations, not authenticated
    primary evidence. The overlay independently requires the exact receipt pins.
    Cash is held (not reinvested); splits update quantities. CIL uses actual net
    proceeds paid by the endpoint, never fractional shares times an end close.
    """
    if (type(action) is not dict or type(evidence) is not dict
            or type(start_day) is not date or type(end_day) is not date
            or start_day >= end_day or entitlement_ex_date(action) is None):
        return None
    ex = entitlement_ex_date(action)
    if not (start_day < ex <= end_day and evidence.get("schema") == "distribution-entitlement-input-v2"
            and evidence.get("target_symbol") == "MOD" and evidence.get("related_symbol") == "THRM"
            and evidence.get("start_day") == start_day.isoformat()
            and evidence.get("end_day") == end_day.isoformat()
            and evidence.get("currency") == "USD"
            and evidence.get("method") == "CASH_HELD_NO_REINVESTMENT"
            and evidence.get("ex_date") == ex.isoformat()
            and evidence.get("record_date") == "2026-09-28"
            and evidence.get("due_bill_start") == "2026-09-28"
            and evidence.get("due_bill_end") == "2026-10-01"
            and evidence.get("ledger_start") == start_day.isoformat()
            and evidence.get("ledger_end") == end_day.isoformat()):
        return None
    documents = _validated_documents(action, evidence, end_day, require_receipt=False)
    if documents is None:
        return None
    ledger = documents.get(evidence.get("ledger_document_id")) if isinstance(evidence.get("ledger_document_id"), str) else None
    if ledger is None or ledger["role"] != "ACTION_LEDGER":
        return None
    prices = evidence.get("prices")
    if type(prices) is not dict or set(prices) != {"start_target", "end_target", "end_related"}:
        return None
    start_price = _observation(prices["start_target"], symbol="MOD", day=start_day, documents=documents)
    end_target = _observation(prices["end_target"], symbol="MOD", day=end_day, documents=documents)
    end_related = _observation(prices["end_related"], symbol="THRM", day=end_day, documents=documents)
    shares = evidence.get("benchmark_target_shares")
    if (any(x is None for x in (start_price, end_target, end_related))
            or type(shares) is not int or not 1 <= shares <= 1000000):
        return None
    events = evidence.get("cash_and_split_events")
    if type(events) is not list or len(events) > 300:
        return None
    ordered = []
    seen = set()
    for event in events:
        if type(event) is not dict or set(event) != {"symbol", "kind", "ex_date", "value", "source_excerpt"}:
            return None
        day = _day(event.get("ex_date"))
        kind, symbol = event.get("kind"), event.get("symbol")
        value = _decimal(event.get("value"), positive=kind == "SPLIT")
        excerpt = event.get("source_excerpt")
        if (day is None or not start_day < day <= end_day
                or not isinstance(symbol, str) or symbol not in {"MOD", "THRM"}
                or not isinstance(kind, str) or kind not in {"SPLIT", "DIVIDEND"} or value is None
                or not isinstance(excerpt, str) or not excerpt or excerpt not in ledger["body"]
                or (symbol, kind, day) in seen):
            return None
        # New THRM shares never carry the pre-combination special dividend.
        # Earlier related-security events likewise cannot enter this holding.
        if symbol == "THRM" and (day <= ex or (kind == "DIVIDEND" and day == date(2026, 10, 7))):
            return None
        # A simultaneous MOD split needs separately reviewed ratio-basis terms.
        if symbol == "MOD" and kind == "SPLIT" and day == ex:
            return None
        seen.add((symbol, kind, day))
        ordered.append((day, 0 if kind == "SPLIT" else 2, symbol, kind, value))
    ordered.append((ex, 1, "MOD", "DISTRIBUTION", Decimal("0.44619")))
    cil = evidence.get("cash_in_lieu")
    if type(cil) is not dict or set(cil) != {"amount", "currency", "paid_on", "document_id", "source_excerpt"}:
        return None
    cash_total = _decimal(cil.get("amount"))
    if cash_total is None or cil.get("currency") != "USD":
        return None
    with localcontext() as ctx:
        ctx.prec = 40
        quantities = {"MOD": Decimal(shares), "THRM": Decimal(0)}
        cash = Decimal(0)
        delivered = Decimal(0)
        whole = 0
        for _, _, symbol, kind, value in sorted(ordered):
            if kind == "SPLIT":
                quantities[symbol] *= value
                if quantities[symbol] != quantities[symbol].to_integral_value():
                    return None  # a split-generated fraction needs its own settlement evidence
            elif kind == "DIVIDEND":
                cash += quantities[symbol] * value
            else:
                delivered = quantities["MOD"] * value
                whole = int(delivered)
                quantities["THRM"] = Decimal(whole)
        fractional = delivered - whole
        if fractional:
            paid = _day(cil.get("paid_on"))
            doc = documents.get(cil.get("document_id")) if isinstance(cil.get("document_id"), str) else None
            excerpt = cil.get("source_excerpt")
            if (paid is None or not ex <= paid <= end_day or doc is None or doc["role"] != "CASH_IN_LIEU"
                    or not isinstance(excerpt, str) or not excerpt or excerpt not in doc["body"]):
                return None
        elif cash_total != 0 or any(cil.get(k) is not None for k in ("paid_on", "document_id", "source_excerpt")):
            return None
        base = Decimal(shares) * start_price
        terminal = quantities["MOD"] * end_target + quantities["THRM"] * end_related + cash + cash_total
        number = float(terminal / base - 1)
    if not math.isfinite(number):
        return None
    return {
        "status": "CALCULATED_RESEARCH_ONLY", "return": number,
        "start_day": start_day.isoformat(), "end_day": end_day.isoformat(),
        "benchmark_shares": shares, "distributed_whole_shares": whole,
        "cash_in_lieu_total": float(cash_total), "currency": "USD",
        "price_basis": "UNADJUSTED_OFFICIAL", "method": "CASH_HELD_NO_REINVESTMENT",
        "evidence_sha256": _digest(evidence),
    }


def restore_crossing_returns(market: dict[str, Any], action: dict[str, Any],
                             evidences: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Research projection still guards numeric windows; it never bypasses approval."""
    result = suppress_unproven_distribution_returns(market, [action])
    asof = _day(result.get("asof"))
    candidates = {}
    for name, (days, annualize) in WINDOWS.items():
        ev = evidences.get(name) if isinstance(evidences, dict) else None
        calculated = calculate_entitled_return(action, ev, start_day=asof - timedelta(days=days),
                                               end_day=asof) if asof and isinstance(ev, dict) else None
        if calculated is not None:
            number = calculated["return"]
            candidates[name] = (1 + number) ** (365.25 / days) - 1 if annualize else number
    result["distribution_adjusted_candidates"] = candidates
    return result


def apply_qualified_market(market: dict[str, Any], distributions: list[dict[str, Any]],
                           reviewed: dict[str, Any] | None) -> dict[str, Any]:
    """Atomic restoration of every crossing window using controlled registry pins."""
    guarded = suppress_unproven_distribution_returns(market, distributions)
    asof = _day(market.get("asof"))
    if not asof or type(reviewed) is not dict or len(distributions) != 1:
        return guarded
    action = distributions[0]
    reviewed_at = _day(reviewed.get("reviewed_at"))
    if not (reviewed.get("schema") == "distribution-entitlement-reviewed-v2"
            and reviewed.get("target_symbol") == action.get("target_symbol")
            and reviewed.get("related_symbol") == action.get("related_symbol")
            and reviewed.get("asof") == asof.isoformat()
            and reviewed_at is not None and reviewed_at <= asof
            and type(reviewed.get("windows")) is dict):
        return guarded
    values = {}
    for name, (days, annualize) in WINDOWS.items():
        start = asof - timedelta(days=days)
        if not _crosses(start, asof, action):
            continue
        evidence = reviewed["windows"].get(name)
        if type(evidence) is not dict or _validated_documents(action, evidence, asof, require_receipt=True) is None:
            return guarded
        calculation = calculate_entitled_return(action, evidence, start_day=start, end_day=asof)
        if calculation is None:
            return guarded
        number = calculation["return"]
        number = (1 + number) ** (365.25 / days) - 1 if annualize else number
        if not math.isfinite(number):
            return guarded
        values[name] = round(number, 10)
    if not values:
        return guarded
    result = dict(guarded)
    reasons = dict(result.get("return_reasons") or {})
    for name, value in values.items():
        result[name] = value
        reasons.pop(name, None)
    if reasons:
        result["return_reasons"] = reasons
    else:
        result.pop("return_reasons", None)
        result.pop("distribution_unavailable_reason_zh", None)
    if "cagr_2y" in values:
        result["long_term_basis"] = "TWO_YEAR"
    # Raw primary documents stay in controlled acquisition inputs, not public cards.
    result["distribution_evidence"] = {
        "schema": "distribution-entitlement-receipt-v2", "input_sha256": _digest(reviewed),
    }
    result["distribution_adjustment"] = {
        "status": "REVIEWED_PRIMARY_INPUTS", "source_url": action["source_url"],
        "distribution_date": action["distribution_date"], "related_symbol": action["related_symbol"],
        "shares_per_share": action["shares_per_share"], "evidence_sha256": _digest(reviewed),
        "values": values, "method": "SHAREHOLDER_ENTITLEMENT_TOTAL_RETURN",
    }
    return result


def load_evidence_document(source: Any) -> dict[str, dict[str, Any]]:
    """Bounded untrusted input catalog; loading never confers review authority."""
    if source is None or not source.exists():
        return {}
    raw = source.read_bytes()
    if type(raw) is not bytes or not 1 <= len(raw) <= 2 * 1024 * 1024:
        raise ValueError("ENTITLEMENT_EVIDENCE_SIZE")
    def pairs(items):
        out = {}
        for key, value in items:
            if key in out:
                raise ValueError("ENTITLEMENT_EVIDENCE_DUPLICATE_KEY")
            out[key] = value
        return out
    try:
        doc = json.loads(raw, object_pairs_hook=pairs,
                         parse_constant=lambda _: (_ for _ in ()).throw(ValueError("NONFINITE_JSON")))
    except (ValueError, UnicodeDecodeError) as exc:
        raise ValueError("ENTITLEMENT_EVIDENCE_JSON") from exc
    rows = doc.get("rows") if type(doc) is dict and doc.get("schema") == "distribution-evidence-catalog-v1" else None
    if type(rows) is not list or len(rows) > 30:
        raise ValueError("ENTITLEMENT_EVIDENCE_CATALOG")
    out = {}
    for row in rows:
        sym = row.get("target_symbol") if type(row) is dict else None
        if not isinstance(sym, str) or not re.fullmatch(r"[A-Z0-9][A-Z0-9.-]{0,14}", sym) or sym in out:
            raise ValueError("ENTITLEMENT_EVIDENCE_ROW")
        out[sym] = row
    return out
