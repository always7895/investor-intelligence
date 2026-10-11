"""Latest-release receipts for the reviewed revenue-guidance registry (ORDERS-V3-01, writer-owned collector W1).

For every GUIDANCE issuer in config/revenue-guidance-v1.json this checks, after the guidance document's publication date,
three public channels and writes one receipt per issuer into data/cache/revenue_guidance_release_checks.json (the newest 8
per issuer, oldest first; the sealer picks the newest one at or before its cutoff and at most 24 hours old):
- SEC_SUBMISSIONS: EDGAR's submissions feed of the issuer (8-K items, 6-K, periodic reports);
- WIRE_PRESS_RELEASES: Nasdaq's press-release feed for the symbol (the issuer's wire releases), paged until it reaches the
  guidance date; items must name the issuer;
- ISSUER_IR: the issuer's own official IR press-release channel (scripts/issuer_ir_feeds.py, kind and feed URL reviewed in
  the registry's `release_channels.ir`): an item on the guidance day carrying the registry's guidance-release title is the
  guidance release itself (the reference point, not a later document); other same-day items stay ambiguous for review and
  later items are classified by the title classifier.
Coverage is stated as SEC_WIRE_IR when the record carries an official IR channel, SEC_AND_WIRE otherwise: for the
company-guidance path the official IR channel is part of the freshness proof (Astra W1 ruling), and an issuer whose IR
channel is missing, failed or incomplete keeps its projection unavailable (FRESHNESS_UNVERIFIED / IR_COVERAGE_MISSING).
Nothing found here becomes a number: a results release makes the record RESULTS_PUBLISHED and anything possibly relevant
REVIEW_REQUIRED until the writer reviews it (`reviewed_later_documents` in the registry). A channel that fails or cannot
be read to the guidance date makes the receipt FRESHNESS_UNVERIFIED. A run that cannot read the registry changes nothing
(the previous receipts keep their original times and age out). Every later-document id is written in the persisted form
of revenue_guidance_overlay.safe_document_id (BATCH10C F8-N1): an id with userinfo, a query or a fragment never reaches
the receipt verbatim. The persisted form is a safe id (BATCH10C F8-AMEND1), so such a receipt states its status as any
other receipt does (its recompute agrees) and bars nothing.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import urllib.request
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import issuer_ir_feeds  # noqa: E402
import revenue_guidance  # noqa: E402
import revenue_guidance_overlay as overlay  # noqa: E402

REGISTRY = ROOT / "config" / "revenue-guidance-v1.json"
OUTPUT = ROOT / "data" / "cache" / "revenue_guidance_release_checks.json"
SCHEMA = "revenue-guidance-release-checks-v1"
KEEP = 8
WIRE_PAGE = 50
WIRE_MAX_PAGES = 6
WIRE_USER_AGENT = "Mozilla/5.0 (InvestorIntelligence public observation)"
# 8-K items that cannot carry results or guidance on their own (agreements, debt, officers, charter, votes, exhibits).
IRRELEVANT_ITEMS = {"1.01", "1.02", "2.03", "3.02", "5.02", "5.03", "5.07", "9.01"}
PERIODIC_FORMS = {"10-Q", "10-K", "10-Q/A", "10-K/A", "20-F", "20-F/A", "40-F"}
RESULT_WORDS = re.compile(r"\b(results?|revenue|guidance|outlook|preliminary|forecast)\b", re.I)
NOT_RESULTS = re.compile(r"conference call|webcast|to (?:report|announce|present|host)|will (?:report|announce)|dividend|general meeting|annual meeting|shareholders'? meeting|stockholders'? meeting", re.I)


def utc_now() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def stamp(moment: datetime) -> str:
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ")


def canonical_digest(receipt: Mapping[str, Any]) -> str:
    return revenue_guidance.compute_receipt_digest(receipt)


GUIDANCE_CHANGE = re.compile(
    r"\b(?:withdraw\w*|revis\w*|rais\w*|lower\w*|reaffirm\w*|updat\w*|provid\w*|cut\w*|suspend\w*)\b.*"
    r"\b(?:guidance|outlook|targets?|forecasts?|expectations)\b|\b(?:guidance|outlook|targets?|forecasts?|expectations)\b.*"
    r"\b(?:update|revision|withdraw\w*|reaffirm\w*|change)\b|preliminary", re.I)
# Financial wording that makes a title a review item unless the WHOLE title is one of the known nonmaterial notices
# below (Astra A2 r7-r10: an allowlist of complete notice shapes, never the removal of phrases from a longer title).
FINANCIAL_WORDING = re.compile(
    r"\b(?:results?|revenues?|earnings|sales|guidance|outlook|targets?|forecasts?|expectations|preliminary|"
    r"expects?|expected|anticipat\w*|estimat\w*|projects?|projected|sees|"
    r"financial\s+(?:model|update|position|performance|results)|business\s+update)\b", re.I)
# An amount or a percentage next to reporting-period wording is a financial statement even without those words.
AMOUNT_WITH_PERIOD = re.compile(r"(?:[$€£¥₩]\s?\d|\d\s?%|\b\d+(?:\.\d+)?\s+(?:billion|million|trillion)\b)", re.I)
PERIOD_WORDING = re.compile(r"\b(?:quarter(?:ly)?|fiscal|year[- ]over[- ]year|yoy|q[1-4]|fy\d{2,4}|half[- ]year|full[- ]year)\b", re.I)
_PERIOD_WORD = (r"(?:first|second|third|fourth|1st|2nd|3rd|4th|q[1-4]|h[12]|quarter|quarterly|fiscal|full|year|full-year|"
                r"year-end|annual|half|half-year|fy\d{2,4}|\d{4}|its|the|our)")
_PERIOD = r"(?:" + _PERIOD_WORD + r"\s+){0,8}"
_MONTH = r"(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\.?"
_DATE = (r"(?:(?:(?:mon|tues|wednes|thurs|fri|satur|sun)day,?\s+)?" + _MONTH + r"\s+\d{1,2}(?:st|nd|rd|th)?(?:,?\s+\d{4})?"
         r"|\d{4}-\d{2}-\d{2})")
_WHEN = r"(?:\s+(?:on\s+|after\s+|before\s+)?" + _DATE + r")?(?:,?\s+(?:after|before)\s+(?:the\s+)?market\s+(?:close|open))?"
_CALL = r"(?:\s+and\s+(?:host\s+|hold\s+)?(?:a\s+|the\s+)?(?:conference\s+call|webcast)(?:\s+and\s+webcast)?)?"
_RESULTS = r"(?:financial\s+)?(?:results|earnings)"
NONMATERIAL_NOTICES = [
    # "X to Report Fiscal Fourth Quarter Results on September 30, 2026"
    re.compile(r"(?P<co>.+?)\s+(?:to|will)\s+(?:report|announce|release)\s+" + _PERIOD + _RESULTS + _WHEN + _CALL + _WHEN + r"\.?", re.I),
    # "X Announces Date of Second Quarter 2026 Results and Conference Call"
    re.compile(r"(?P<co>.+?)\s+(?:announces?|sets?|schedules?|confirms?)\s+(?:the\s+)?dates?\s+(?:of|for)\s+" + _PERIOD + _RESULTS
               + r"(?:\s+(?:release|announcement))?" + _CALL + _WHEN + r"\.?", re.I),
    # "X Announces Conference Call to Review Second Quarter Results"
    re.compile(r"(?P<co>.+?)\s+(?:announces?|to\s+host|will\s+host|schedules?|sets?)\s+(?:a\s+|the\s+)?(?:conference\s+call|webcast)"
               r"(?:\s+and\s+webcast)?\s+(?:to\s+(?:review|discuss)|on|for)\s+" + _PERIOD + _RESULTS + _WHEN + r"\.?", re.I),
    # "X Announces Results of Its Annual General Meeting"
    re.compile(r"(?P<co>.+?)\s+(?:announces?|reports?)\s+(?:the\s+)?(?:voting\s+)?results\s+of\s+(?:the\s+|its\s+)?(?:\d{4}\s+)?"
               r"(?:annual\s+|extraordinary\s+|special\s+)?(?:general\s+)?(?:shareholders'?\s+|stockholders'?\s+)?meeting"
               r"(?:\s+of\s+(?:shareholders|stockholders))?\.?", re.I),
    # "X Declares Quarterly Dividend Payment"
    re.compile(r"(?P<co>.+?)\s+declares?\s+(?:a\s+)?(?:regular\s+)?(?:quarterly\s+)?(?:cash\s+)?dividend(?:\s+payment)?\.?", re.I),
]


def is_wire_title_possibly_relevant(title: str) -> bool:
    """A press-release title (wire or official IR) that may carry results or a change of guidance/targets.

    Conservative (Astra acceptance A2, r7-r10): a title is exempt only when it is, as a whole, one of the known
    nonmaterial notices (a results-date notice, a date/conference-call announcement, a meeting-vote outcome or a
    dividend declaration) and the part before the notice names only the issuer (no financial wording, digits,
    amounts or percentages). Any other title with financial wording, or with an amount or percentage next to period
    wording, is a review item; an explicit change, withdrawal, reaffirmation or preliminary statement about
    guidance/outlook/targets always is.
    - "NVIDIA Withdraws Its Financial Targets" -> relevant;
    - "NVIDIA to Report Third Quarter Revenue, Up 50% Year over Year" -> relevant (not a whole notice);
    - "X to Report Fiscal Fourth Quarter Results on September 30, 2026" -> not relevant (a whole results-date notice);
    - "X Announces Results of Its Annual General Meeting" -> not relevant (votes);
    - "X Declares Quarterly Dividend Payment" -> not relevant.
    """
    text = " ".join(title.split())
    if GUIDANCE_CHANGE.search(text):
        return True
    for notice in NONMATERIAL_NOTICES:
        match = notice.fullmatch(text)
        if match and not (FINANCIAL_WORDING.search(match["co"]) or re.search(r"[\d$€£¥₩%&,;:]", match["co"].replace(", Inc.", "").replace(", Ltd.", ""))):
            return False
    return bool(FINANCIAL_WORDING.search(text) or (AMOUNT_WITH_PERIOD.search(text) and PERIOD_WORDING.search(text)))


def _get_json(url: str, headers: Mapping[str, str]) -> Any:
    with urllib.request.urlopen(urllib.request.Request(url, headers=dict(headers)), timeout=30) as response:
        return json.loads(response.read(8_000_000).decode("utf-8"))


def _wire_day(text: str) -> str | None:
    try:
        return datetime.strptime(text.strip(), "%b %d, %Y").date().isoformat()
    except (ValueError, AttributeError):
        return None


def sec_channel(cik: int, since: str, anchor_end: str, reviewed: set[str], fetch: Callable[[str], Any]) -> tuple[dict, list[dict]]:
    url = f"https://data.sec.gov/submissions/CIK{cik:010d}.json"
    try:
        recent = fetch(url)["filings"]["recent"]
        forms, dates, accs = recent["form"], recent["filingDate"], recent["accessionNumber"]
        # A truncated feed is an unverified channel, never a complete one: every parallel array must be present and
        # exactly as long as the form list (a shorter items array used to zip-truncate later filings away). An accession
        # becomes a receipt id, so a non-string one is a malformed feed too (BATCH10C F8-N1: no non-string id written).
        if not (isinstance(forms, list) and isinstance(dates, list) and isinstance(accs, list)
                and len(forms) == len(dates) == len(accs) and all(isinstance(a, str) for a in accs)):
            raise ValueError("SEC_FEED_INCOMPLETE")
        items_raw = recent.get("items")
        reports_raw = recent.get("reportDate")
        if items_raw is None:
            items_raw = [""] * len(forms)
        if reports_raw is None:
            reports_raw = [""] * len(forms)
        if not (isinstance(items_raw, list) and isinstance(reports_raw, list)
                and len(items_raw) == len(forms) and len(reports_raw) == len(forms)):
            raise ValueError("SEC_FEED_INCOMPLETE")
        rows = list(zip(forms, dates, items_raw, accs, reports_raw))
    except Exception:  # noqa: BLE001 - any failure is an unverified channel, never "no release"
        return {"kind": "SEC_SUBMISSIONS", "url": url, "status": "FAILED", "checked_through": None, "complete": False}, []
    # The recent block holds the latest ~1000 filings; it reaches back to the guidance date unless it is exhausted.
    complete = bool(rows) and min(filed for _, filed, _, _, _ in rows) <= since
    later = []
    for form, filed, items, accession, report_date in rows:
        # Filings strictly before the guidance day are out of scope. A filing on the guidance day itself stays
        # ambiguous (the feed is day-granular, no instants): it is preserved for review as possibly relevant, never
        # dropped and never auto-classified as a results release (Astra r5 item 2).
        if filed < since:
            continue
        if form not in ("8-K", "8-K/A", "6-K", "6-K/A") and form not in PERIODIC_FORMS:
            continue  # ownership, registration and proxy filings carry no revenue statement, on any day
        same_day = filed == since
        item_set = {part.strip() for part in (items or "").split(",") if part.strip()}
        if form in ("8-K", "8-K/A") and item_set and item_set <= IRRELEVANT_ITEMS:
            disposition = "IRRELEVANT"  # agreements, officers, votes, exhibits only: no results on any day
        elif same_day:
            disposition = "POSSIBLY_RELEVANT"
        elif form in ("8-K", "8-K/A"):
            if "2.02" in item_set:
                disposition = "RESULTS_RELEASE"
            elif item_set and item_set <= IRRELEVANT_ITEMS:
                disposition = "IRRELEVANT"
            else:
                disposition = "POSSIBLY_RELEVANT"
        elif form in PERIODIC_FORMS:
            disposition = "RESULTS_RELEASE" if (report_date or "") > anchor_end else "IRRELEVANT"
        elif form in ("6-K", "6-K/A"):
            disposition = "POSSIBLY_RELEVANT"
        else:
            continue  # ownership, registration and proxy filings carry no revenue statement
        accession = overlay.safe_document_id(accession)  # BATCH10C F8-N1: the persisted form (see receipt_for)
        if disposition == "POSSIBLY_RELEVANT" and accession in reviewed:
            disposition = "REVIEWED_IRRELEVANT"
        later.append({"channel": "SEC_SUBMISSIONS", "date": filed, "id": accession,
                      "label": f"{form} items {items}" if items else form, "disposition": disposition})
    return {"kind": "SEC_SUBMISSIONS", "url": url, "status": "OK", "checked_through": max(f for _, f, _, _, _ in rows) if rows else None,
            "complete": complete}, later


def wire_channel(symbol: str, names: list[str], since: str, reviewed: set[str], fetch: Callable[[str], Any]) -> tuple[dict, list[dict]]:
    base = f"https://api.nasdaq.com/api/news/topic/press_release?q=symbol:{symbol.lower()}|assetclass:stocks"
    later, oldest, newest, complete = [], None, None, False
    try:
        for page in range(WIRE_MAX_PAGES):
            data = fetch(f"{base}&limit={WIRE_PAGE}&offset={page * WIRE_PAGE}")["data"]
            rows = data.get("rows") or []
            for row in rows:
                day = _wire_day(row.get("created", ""))
                if day is None:
                    raise ValueError("WIRE_DATE")
                oldest = day if oldest is None or day < oldest else oldest
                newest = day if newest is None or day > newest else newest
                title = str(row.get("title") or "")
                # Wire dates are day-granular: items on the guidance day stay ambiguous and are preserved for review,
                # never dropped and never auto-classified (Astra r5 item 2).
                if day < since or not any(name.lower() in title.lower() for name in names):
                    continue
                item_id = overlay.safe_document_id("https://www.nasdaq.com" + str(row.get("url") or ""))
                relevant = is_wire_title_possibly_relevant(title)
                disposition = "POSSIBLY_RELEVANT" if relevant else "IRRELEVANT"
                if day == since and relevant:
                    disposition = "POSSIBLY_RELEVANT"
                if disposition == "POSSIBLY_RELEVANT" and item_id in reviewed:
                    disposition = "REVIEWED_IRRELEVANT"
                later.append({"channel": "WIRE_PRESS_RELEASES", "date": day, "id": item_id, "label": title[:200], "disposition": disposition})
            total = int(data.get("totalrecords") or 0)
            if (oldest is not None and oldest < since) or (page + 1) * WIRE_PAGE >= total or not rows:
                # Complete when the feed reaches back before the guidance date (or holds nothing older at all).
                complete = (oldest is not None and oldest < since) or ((page + 1) * WIRE_PAGE >= total and total > 0)
                break
    except Exception:  # noqa: BLE001
        return {"kind": "WIRE_PRESS_RELEASES", "url": base, "status": "FAILED", "checked_through": None, "complete": False}, []
    return {"kind": "WIRE_PRESS_RELEASES", "url": base, "status": "OK", "checked_through": newest, "complete": complete}, later


def ir_channel(ir_spec: Mapping[str, Any], ir_title: str, since: str, today: date,
              reviewed: set[str], fetch: Callable[[str], bytes] | None) -> tuple[dict, list[dict]]:
    """The official IR channel (Astra W1 ruling, astra-ir-coverage): the issuer's own press-release index, read through
    scripts/issuer_ir_feeds.read_channel. A failed or incomplete read is an unverified channel, never "no release".

    Items dated on the guidance reference day whose title equals the registry's `ir_guidance_release_title` are the
    guidance release itself (the reference point, not a later document). Any other same-day item stays ambiguous
    (POSSIBLY_RELEVANT for review); later items are classified with the existing title classifier (results / revenue /
    guidance / outlook / preliminary -> POSSIBLY_RELEVANT, otherwise IRRELEVANT) and reviewed ids are respected."""
    url = str(ir_spec.get("url"))
    result = issuer_ir_feeds.read_channel({"kind": ir_spec.get("kind"), "url": url}, date.fromisoformat(since), today, fetch)
    channel = {"kind": "ISSUER_IR", "url": url, "status": result["status"], "checked_through": None, "complete": result["complete"]}
    if result["status"] != "OK":
        return channel, []
    # A feed that does not list the reviewed guidance release itself on its day is not a complete read of the
    # interval (an empty or truncated answer never renews coverage; Astra final review A2).
    if not any(str(item["date"]) == since and str(item["title"]) == ir_title for item in result["items"]):
        channel["complete"] = False
    later: list[dict] = []
    for item in result["items"]:
        day, title, item_id = str(item["date"]), str(item["title"]), overlay.safe_document_id(str(item["id"]))
        if day == since:
            if title == ir_title:
                continue  # the guidance release itself, not a later document
            disposition = "POSSIBLY_RELEVANT"  # same-day ambiguity: preserved for review, never dropped
        else:
            disposition = "POSSIBLY_RELEVANT" if is_wire_title_possibly_relevant(title) else "IRRELEVANT"
        if disposition == "POSSIBLY_RELEVANT" and item_id in reviewed:
            disposition = "REVIEWED_IRRELEVANT"
        later.append({"channel": "ISSUER_IR", "date": day, "id": item_id, "label": title[:200], "disposition": disposition})
    return channel, later


def receipt_for(record: Mapping[str, Any], now: datetime, sec_fetch: Callable[[str], Any], wire_fetch: Callable[[str], Any],
                ir_fetch: Callable[[str], bytes] | None = None) -> dict | None:
    """One receipt for one GUIDANCE record, or None when the record does not name what is needed to check it."""
    symbol = record.get("symbol")
    channels = record.get("release_channels") or {}
    docs_by_id = {d["id"]: d for d in record.get("documents") or []}
    quarters = record.get("reported_quarters") or []
    if not quarters or not isinstance(channels.get("sec_cik"), int) or not channels.get("wire_names"):
        return None
    # The check starts from the validated selected/current claim set (Astra r5 item 2): deterministic, order-independent,
    # never claims[0] with a hardcoded fallback.
    # One reference for the whole active claim set (ORDERS-V3-AUTOUPDATE-01 B0): claims with distinct references
    # are not checkable from one reference (no receipt, so the record stays unavailable), never checked from the
    # first or the newest claim alone.
    ref_doc_id = revenue_guidance.guidance_reference(record)["document_id"]
    if not ref_doc_id or ref_doc_id not in docs_by_id:
        return None
    since, anchor_end = docs_by_id[ref_doc_id]["published_date"], quarters[-1]["end"]
    # BATCH10C F8-N1: reviewed ids compare in the persisted form the ids are written in (as overlay.unaccounted does).
    reviewed = {str(overlay.safe_document_id(r.get("id"))) for r in record.get("reviewed_later_documents") or []
                if r.get("disposition") == "REVIEWED_IRRELEVANT"}
    # The official IR channel (Astra W1 ruling): present when the record names a known kind, an https feed URL and the
    # reviewed guidance-release title; a missing title makes the channel unusable, never a silent skip.
    ir_spec = channels.get("ir")
    ir_title = channels.get("ir_guidance_release_title")
    has_ir = (isinstance(ir_spec, Mapping) and ir_spec.get("kind") in issuer_ir_feeds.KINDS
              and isinstance(ir_spec.get("url"), str) and str(ir_spec.get("url")).startswith("https://")
              and isinstance(ir_title, str) and len(ir_title) > 0)
    sec, sec_later = sec_channel(channels["sec_cik"], since, anchor_end, reviewed, sec_fetch)
    wire, wire_later = wire_channel(channels.get("wire_symbol") or symbol, list(channels["wire_names"]), since, reviewed, wire_fetch)
    all_channels: list[dict] = [sec, wire]
    ir_later: list[dict] = []
    coverage = "SEC_AND_WIRE"
    if has_ir:
        ir, ir_later = ir_channel(ir_spec, ir_title, since, now.date(), reviewed, ir_fetch)
        all_channels.append(ir)
        coverage = "SEC_WIRE_IR"
    # A channel read completely back to the guidance date is checked through the day of this check (not merely through
    # its newest item: a quiet issuer publishes nothing for weeks).
    for channel in all_channels:
        if channel["status"] == "OK":
            channel["checked_through"] = now.date().isoformat()
    later = sorted(sec_later + wire_later + ir_later, key=lambda d: (d["date"], d["channel"], d["id"]))
    dispositions = {d["disposition"] for d in later}
    # BATCH10C F8-N1 / F8-AMEND1: every listed id is in its persisted form, which is a safe id; one that is still raw
    # unsafe would be no freshness proof, and the receipt would say so itself, exactly as
    # revenue_guidance.recompute_receipt_status recomputes it.
    if any(c["status"] != "OK" or not c["complete"] for c in all_channels) or any(
            revenue_guidance.raw_unsafe_document_id(d["id"]) for d in later):
        status = "FRESHNESS_UNVERIFIED"
    elif "RESULTS_RELEASE" in dispositions:
        status = "RESULTS_PUBLISHED"
    elif "POSSIBLY_RELEVANT" in dispositions:
        status = "REVIEW_REQUIRED"
    else:
        status = "OK"
    receipt = {"issuer": symbol, "checked_at": stamp(now), "status": status, "guidance_document_id": ref_doc_id,
               "guidance_published_date": since, "anchor_end": anchor_end, "coverage": coverage,
               "channels": all_channels, "later_documents": later}
    receipt["digest"] = canonical_digest(receipt)
    return receipt


def retained_history(output: Path, snapshot: Any) -> dict[str, list[dict]]:
    """The retained receipt history, exactly the bytes the snapshot captured (ORDERS-V3-AUTOUPDATE-01 B1). Only a
    missing file is a first use; an unreadable, malformed or differently shaped history - or one that changed since
    the snapshot read it - stops the run and leaves the file as it is (a corrupt history is never replaced by a clean
    one: an item it listed may no longer appear in any feed)."""
    try:
        if type(output) is overlay.B1Object:
            raw = output.store.capture_mutable(output.components).data
        else:
            raw = output.read_bytes()
    except FileNotFoundError:
        raw = None
    except OSError as error:
        raise ValueError("RECEIPTS_HISTORY_UNREADABLE") from error
    captured = (snapshot.manifest.get("inputs") or {}).get("receipts")
    if captured is not None and captured != (hashlib.sha256(raw).hexdigest() if raw is not None else "FAULT:MISSING"):
        raise ValueError("RECEIPTS_HISTORY_CHANGED_OR_INVALID")
    if raw is None:
        return {}
    try:
        previous = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as error:
        raise ValueError("RECEIPTS_HISTORY_INVALID") from error
    if not overlay.valid_receipt_history(previous):
        raise ValueError("RECEIPTS_HISTORY_INVALID")
    return previous["issuers"]


def run(registry_path: Path | None, output: Path, now: datetime, sec_fetch: Callable[[str], Any] | None = None,
        wire_fetch: Callable[[str], Any] | None = None, ir_fetch: Callable[[str], bytes] | None = None,
        effective_inputs: Any = None, state_root: Path | None = None, *, network=None) -> dict:
    """Check every GUIDANCE discovery record of the shared effective-input snapshot (ORDERS-V3-AUTOUPDATE-01 B1): the
    curated records, and for the automatic issuers the record the updater continues from - also while waiting,
    blocked or suspended, and after a change of reviewed identity (the re-derived producer's reference, or the
    baseline's as a conservative rescan). The raw receipt is collected as always; nothing here consumes machine
    decisions or turns a status into OK."""
    capability = type(state_root) is overlay.B1Store
    if capability:
        state_root.require_live()
        if (registry_path is not None or type(output) is not overlay.B1Object or output.store is not state_root
                or output.components != ("receipts.json",) or any(f is not None for f in (sec_fetch, wire_fetch, ir_fetch))
                or type(network) is not ReceiptTransport or network.store is not state_root):
            raise ValueError("CAPABILITY_CHECKER_OPERANDS")
        if effective_inputs is None:
            effective_inputs = overlay.load_effective_inputs(cutoff=now, state_root=state_root, state_required=True)
        sec_fetch, wire_fetch, ir_fetch = network.json, network.json, network.get
        network.bind_records(overlay.require_snapshot(effective_inputs, now))
    elif effective_inputs is None:
        effective_inputs = overlay.load_effective_inputs(
            cutoff=now, state_root=state_root if state_root is not None else overlay.DEFAULT_STATE_ROOT,
            registry_path=registry_path, receipts_path=output)
    snapshot = overlay.require_snapshot(effective_inputs, now)
    if snapshot.registry.get("status") != "OK":
        raise ValueError("REGISTRY_INVALID")
    history = retained_history(output, snapshot)
    issuers: dict[str, list] = {}
    counts: dict[str, int] = {}
    failed: list[str] = []
    for symbol, record, _origin in snapshot.discovery_records():
        # A discovery input that cannot be checked (no valid record to take a reference from) is an explicit outcome.
        receipt = receipt_for(record, now, sec_fetch, wire_fetch, ir_fetch) if record is not None else None
        kept = [r for r in history.get(symbol) or [] if isinstance(r, dict) and r.get("checked_at", "") < stamp(now)]
        issuers[symbol] = (kept + ([receipt] if receipt else []))[-KEEP:]
        if receipt is None:
            status = "NOT_CHECKABLE"
            failed.append(symbol)
        elif receipt["status"] == "FRESHNESS_UNVERIFIED":
            status = "FRESHNESS_UNVERIFIED"
            failed.append(symbol)
        else:
            status = receipt["status"]
        counts[status] = counts.get(status, 0) + 1
    document = {"schema": SCHEMA, "generated_at": stamp(now), "issuers": issuers}
    encoded = json.dumps(document, ensure_ascii=False, indent=1).encode("utf-8")
    if capability:
        overlay._durable_write(output, encoded)  # same-epoch captured expected state + native readback
    else:
        temp = output.with_name(output.name + ".tmp")
        temp.parent.mkdir(parents=True, exist_ok=True)
        temp.write_bytes(encoded)
        temp.replace(output)
    # Scheduler semantics (Astra r5 item 17): a run in which no GUIDANCE issuer produced a verifiable receipt is a
    # failed run, not an OK one (the previous file keeps its original times; the caller may retry).
    return {"status": "FAILED" if not any(v == "OK" or v == "RESULTS_PUBLISHED" or v == "REVIEW_REQUIRED" for v in counts) else "OK",
            "issuers": len(issuers), "receipts": counts, "failed": failed}


class ReceiptTransport:
    """Actual bounded HTTPS transport for the controlled capability checker.

    Only exact SEC/wire URLs and admitted reviewed IR channels, public pinned DNS,
    no redirect/proxy, bounded response/request/cycle bytes and the lease deadline.
    No externally injected file/network callbacks in this capability branch.
    """
    def __init__(self, store, sec_headers):
        import revenue_guidance_autoupdate as updater
        if type(store) is not overlay.B1Store:
            raise ValueError("CAPABILITY_CHECKER_OPERANDS")
        store.require_live()
        self.store = store
        self.transport = updater.Transport(sec_headers)
        self.transport.bind_capability(store)
        self.allowed = {}
        self.bytes = 0

    def bind_records(self, snapshot):
        import urllib.parse
        for issuer, record, _origin in snapshot.discovery_records():
            if record is None:
                continue
            channels = record.get("release_channels") or {}
            cik = channels.get("sec_cik")
            if type(cik) is int:
                self.allowed[f"https://data.sec.gov/submissions/CIK{cik:010d}.json"] = issuer
            symbol = channels.get("wire_symbol") or record.get("symbol")
            if isinstance(symbol, str) and re.fullmatch(r"[A-Z][A-Z0-9.\-]{0,15}", symbol):
                base = f"https://api.nasdaq.com/api/news/topic/press_release?q=symbol:{symbol.lower()}|assetclass:stocks"
                for page in range(WIRE_MAX_PAGES):
                    self.allowed[f"{base}&limit={WIRE_PAGE}&offset={page * WIRE_PAGE}"] = issuer
            ir = channels.get("ir") or {}
            url = ir.get("url")
            if ir.get("kind") in issuer_ir_feeds.KINDS and isinstance(url, str):
                parts = urllib.parse.urlsplit(url)
                if parts.scheme == "https" and not parts.username and not parts.password and parts.port in (None, 443) and not parts.fragment:
                    self.allowed[url] = issuer

    def get(self, url):
        import urllib.parse
        import revenue_guidance_autoupdate as updater
        self.store.require_live()
        if url not in self.allowed:
            raise ValueError("CAPABILITY_CHECKER_URL")
        parts = urllib.parse.urlsplit(url)
        host = parts.hostname
        transport = self.transport
        address = transport._address(host)
        transport._budget(self.allowed[url])
        headers = dict(transport.sec_headers) if host in updater.SEC_HOSTS else {"User-Agent": WIRE_USER_AGENT}
        headers.update({"Host": host, "Accept-Encoding": "identity"})
        path = parts.path + ("?" + parts.query if parts.query else "")
        response = updater._connect(host, address, path, headers, min(updater.REQUEST_TIMEOUT, transport.remaining()))
        try:
            if response.status != 200 or str(response.headers.get("content-encoding", "identity")).lower() != "identity":
                raise ValueError("CAPABILITY_CHECKER_NETWORK")
            chunks, total = [], 0
            while True:
                transport.remaining()
                chunk = response.read(65536)
                if not chunk:
                    break
                total += len(chunk)
                self.bytes += len(chunk)
                transport.account_bytes(len(chunk))
                if total > 8 * 1024 * 1024 or self.bytes > updater.CYCLE_CAPTURE_BYTES:
                    raise ValueError("CAPABILITY_CHECKER_CAPACITY_UNAVAILABLE")
                chunks.append(chunk)
            return b"".join(chunks)
        finally:
            response.close()

    def json(self, url):
        return json.loads(self.get(url).decode("utf-8"))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--registry", type=Path, default=REGISTRY)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    parser.add_argument("--if-older-than-hours", type=float, default=0.0)
    parser.add_argument("--state-root", type=Path, default=overlay.DEFAULT_STATE_ROOT,
                        help="auto-update state root whose discovery records are checked (absent: curated records only)")
    args = parser.parse_args(argv)
    now = utc_now()
    if args.if_older_than_hours > 0 and args.output.exists():
        # A malformed or future generated_at never skips a run: the fresh shortcut applies only to a valid past stamp.
        try:
            generated = datetime.strptime(json.loads(args.output.read_text(encoding="utf-8"))["generated_at"], "%Y-%m-%dT%H:%M:%SZ")
            if generated <= now and (now - generated.replace(tzinfo=timezone.utc)).total_seconds() < args.if_older_than_hours * 3600:
                print(json.dumps({"status": "SKIPPED_FRESH"}))
                return 0
        except (OSError, ValueError, KeyError, TypeError):
            pass
    try:
        from sec_contact_headers import sec_identity_headers
        sec_headers = sec_identity_headers()
    except Exception as error:  # noqa: BLE001 - the SEC contact is required for EDGAR; never echo it
        print(json.dumps({"status": "FAILED", "error": type(error).__name__}))
        return 1
    try:
        result = run(args.registry, args.output, now, lambda url: _get_json(url, sec_headers),
                     lambda url: _get_json(url, {"User-Agent": WIRE_USER_AGENT, "Accept": "application/json"}),
                     issuer_ir_feeds.fetch_bytes, state_root=args.state_root)
    except Exception as error:  # noqa: BLE001 - keep the previous file and its original times
        print(json.dumps({"status": "FAILED", "error": type(error).__name__}))
        return 1
    print(json.dumps(result))
    # All-failed / not-checkable runs are failures for the scheduler, not clean zero exits (Astra r5 item 17).
    return 0 if result["status"] == "OK" else 1


if __name__ == "__main__":
    sys.exit(main())
