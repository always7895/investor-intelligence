#!/usr/bin/env python3
"""Deterministic verifier of ORDERS-V3-AUTOUPDATE-01 (docs/REVENUE_GUIDANCE_AUTOUPDATE.md).

Pure: no network, no file writes, no clock. Given a reviewed extraction profile, the effective predecessor record and
the captured official documents of one results event, it either builds the successor revenue-guidance record with
one machine decision per operative input, or returns a typed WAITING/BLOCKED outcome. The same function is run by the
updater (to produce a generation entry) and by the overlay loader (to re-derive and admit it from the stored bytes),
so an entry is admitted only when the installed code reproduces it byte for byte from the captures.

Inputs are canonicalized with a versioned normalizer (EDGAR's per-response watermark attribute zeroed at equal
length, strict UTF-8, HTML parsed into text blocks joined by one space and into table rows); every passage is an exact
substring of that canonical text addressed by character offsets. Numbers are decimals compared exactly at the
source's declared precision; there is no first-match, nearest-number or tolerance rule for source identification."""
from __future__ import annotations

import hashlib
import io
import json
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from html.parser import HTMLParser
from typing import Any, Mapping

import revenue_guidance

VERIFIER_VERSION = "rg-auto-verify-1"
NORMALIZER_VERSION = "rg-canon-1"
PROFILES_SCHEMA = "revenue-guidance-extraction-profiles-v1"

MAX_DOCUMENT_BYTES = 16 * 1024 * 1024
MAX_CANONICAL_TEXT = 4 * 1024 * 1024
MAX_PASSAGE = 1000
MAX_REGEX_LENGTH = 400
SEC_ARCHIVES = "https://www.sec.gov/Archives/edgar/data/"

OUTCOMES = ("VERIFIED", "WAITING", "BLOCKED")
REASONS = (
    "NO_MATCH", "AMBIGUOUS", "PERIOD_MISMATCH", "UNIT_MISMATCH", "SOURCE_DISAGREEMENT", "WAITING_PERIODIC_FILING",
    "WITHDRAWAL", "OUT_OF_ORDER", "UNSUPPORTED_TEMPLATE", "CALENDAR_RULE_UNPROVEN", "CALENDAR_ALLOCATION_UNPROVEN",
    "ACTUAL_NOT_FOUND", "RELEASE_ROW_NOT_FOUND", "CANONICALIZATION_FAILED", "CAPTURE_LIMIT", "INPUT_MISSING",
    "EVENT_UNRESOLVED", "INCOMPLETE_EVENT_COVERAGE", "NETWORK_UNAVAILABLE", "STATE_CORRUPT", "APPROVAL_BINDING",
    "PROFILE_DISABLED", "RESTATEMENT", "REVISION", "INPUT_MALFORMED", "RECORD_INVALID", "EVENT_DETECTED",
)
WATERMARK = re.compile(rb'bazadebezolkohpepadr="([0-9]+)"')
SPACE = re.compile("[\\s\u00a0\u1680\u2000-\u200b\u202f\u205f\u3000]+")
HIDDEN_TAGS = ("ix:header", "script", "style", "head")
# EDGAR serves every document with this one injected fragment (bot-detection watermark and script); it is the only
# markup removed before the inline XBRL is read as XML (the watermark digits are already zeroed by canonical_bytes).
EDGAR_INJECTION = re.compile(rb'<script >bazadebezolkohpepadr="[0-9]+"</script><script type="text/javascript" '
                             rb'src="https://www\.sec\.gov/akam/[0-9]+/[0-9a-f]+"  defer></script>')
IX = "{http://www.xbrl.org/2013/inlineXBRL}"
XBRLI = "{http://www.xbrl.org/2003/instance}"
BLOCK_TAGS = {"p", "div", "li", "tr", "td", "th", "table", "br", "h1", "h2", "h3", "h4", "h5", "h6", "ul", "ol", "center"}
ORDINALS = {"first": 1, "second": 2, "third": 3, "fourth": 4}
# Transitions a first-release profile never processes automatically; sentence-local, no whitelist can cancel one
# (Astra A1 R6, A1-r2 N5). Calibrated on 186 captured releases of the nine issuers plus the OLED/CMG withdrawals.
_OBJECT = r"(?:guidance|outlook|forecasts?|financial targets?|financial expectations|expectations)"
TRANSITIONS = (
    ("WITHDRAWAL", re.compile(r"\b(?:withdr[ae]w\w*|rescind\w*|suspend\w*|retract\w*|discontinu\w*|"
                              r"no longer (?:provid|expect|affirm|reaffirm|giv)\w*)\b[^.;]{0,120}?\b" + _OBJECT + r"\b", re.I)),
    ("WITHDRAWAL", re.compile(r"\b" + _OBJECT + r"\b[^.;]{0,100}?\b(?:has|have|had|is|are|was|were|being|been)\s+(?:been\s+)?"
                              r"(?:withdrawn|rescinded|suspended|retracted|discontinued)\b", re.I)),
    ("RESTATEMENT", re.compile(r"\b(?:no longer (?:be )?relied upon|should not (?:be )?relied upon|non-reliance)\b", re.I)),
    ("RESTATEMENT", re.compile(r"\b(?<!Amended and )restat(?:e|es|ed|ing|ement|ements)\b(?!\s+(?:Certificate|Bylaws|By-laws|Articles|Charter|"
                               r"Equity|Incentive|Plan|Agreement|Credit))", re.I)),
    ("REVISION", re.compile(r"\b(?:revis|lower|reduc|rais|increas|updat|replac|supersed|cut)\w*\b[^.;]{0,80}?\b(?:previous(?:ly)?|prior|earlier)\b"
                            r"[^.;]{0,60}?\b" + _OBJECT + r"\b", re.I)),
)
RULE_KINDS = ("LAST_SUNDAY_OF_JANUARY", "THURSDAY_CLOSEST_TO_AUGUST_31")
COVER_FACTS = ("dei:DocumentType", "dei:DocumentPeriodEndDate")
# Reviewed namespace identities: a prefix is only a spelling; names are compared as (namespace URI, local name).
NAMESPACES = {
    "us-gaap": re.compile(r"^http://fasb\.org/us-gaap/20[0-9]{2}$"),
    "dei": re.compile(r"^http://xbrl\.sec\.gov/dei/20[0-9]{2}$"),
    "iso4217": re.compile(r"^http://www\.xbrl\.org/2003/iso4217$"),
}
# Reviewed inline-XBRL transformations for queried revenue facts, as (registry namespace URI, local name). A fact
# without a format attribute must show a plain decimal. Anything else, or an unbound format prefix, is unsupported.
TRANSFORM_2020 = "http://www.xbrl.org/inlineXBRL/transformation/2020-02-12"
NUMBER_FORMATS = {(TRANSFORM_2020, "num-dot-decimal"), (TRANSFORM_2020, "fixed-zero")}


class Blocked(Exception):
    """A typed, expected outcome (WAITING or BLOCKED) with its reason."""

    def __init__(self, outcome: str, reason: str, detail: str = ""):
        super().__init__(f"{outcome}:{reason}:{detail}")
        self.outcome, self.reason, self.detail = outcome, reason, detail[:300]


def _block(reason: str, detail: str = "") -> Blocked:
    return Blocked("BLOCKED", reason, detail)


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical_json(obj: Any) -> str:
    """Canonical JSON (keys sorted, UTF-8 kept, integral floats written as integers) - revenue_guidance's rule."""
    def norm(value: Any) -> Any:
        if isinstance(value, float):
            if value != value or value in (float("inf"), float("-inf")):
                raise ValueError("non-finite number")
            return int(value) if value.is_integer() else value
        if isinstance(value, (list, tuple)):
            return [norm(x) for x in value]
        if isinstance(value, dict):
            return {str(k): norm(v) for k, v in sorted(value.items())}
        return value
    return json.dumps(norm(obj), sort_keys=True, separators=(",", ":"), ensure_ascii=False)


# ----------------------------------------------------------------------------------------------------------------
# Canonical document
# ----------------------------------------------------------------------------------------------------------------

def canonical_bytes(raw: bytes) -> bytes:
    """EDGAR injects a per-response watermark attribute; its digits are zeroed at equal length (the registry rule)."""
    return WATERMARK.sub(lambda m: b'bazadebezolkohpepadr="' + b"0" * len(m.group(1)) + b'"', raw)


@dataclass
class Fact:
    concept: str
    context: str
    unit_id: str
    shown: str
    fmt: str
    scale: str
    sign: str
    ns: Mapping[str, str]

    def value(self) -> Decimal:
        """Only the queried concepts are converted; a figure that is not a plain number blocks (never guessed)."""
        text = self.shown.replace(",", "")
        transform = Document.expanded(self.fmt, self.ns) if self.fmt else None
        if transform is not None and transform not in NUMBER_FORMATS:
            raise _block("UNSUPPORTED_TEMPLATE", f"inline XBRL format {self.fmt[:40]!r} in {transform[0][:60]}")
        if transform == (TRANSFORM_2020, "fixed-zero"):
            number = Decimal(0)
        elif re.fullmatch(r"[0-9]{1,15}(?:\.[0-9]{1,6})?", text):
            number = Decimal(text)
        else:
            raise _block("SOURCE_DISAGREEMENT", f"inline XBRL value {self.shown[:20]!r}")
        if not re.fullmatch(r"-?[0-9]{1,2}", self.scale or "0") or not -6 <= int(self.scale or "0") <= 12:
            raise _block("SOURCE_DISAGREEMENT", "inline XBRL scale")
        number = number.scaleb(int(self.scale or "0"))
        if self.sign not in ("", "-"):
            raise _block("SOURCE_DISAGREEMENT", "inline XBRL sign")
        return -number if self.sign == "-" else number


@dataclass
class Context:
    cik: str | None = None
    start: str | None = None
    end: str | None = None
    instant: str | None = None
    has_segment: bool = False  # any dimension, in xbrli:segment or xbrli:scenario
    valid: bool = True  # the supported shape (see `_context_shape`); a fact on any other shape is never read


@dataclass
class Document:
    """Canonical text (blocks joined by one space), block offsets, tables (rows of cells with the offsets of their
    first and last cell) and, for an inline XBRL document, its facts, contexts, units, cover facts and namespace
    declarations as read by the XML parser (`parse_ixbrl`)."""
    text: str
    blocks: list[tuple[int, int]]
    tables: list[list[tuple[list[str], int, int]]]
    facts: list[Fact] = field(default_factory=list)
    contexts: dict[str, Context] = field(default_factory=dict)
    cover: list[tuple[str, Mapping[str, str], str]] = field(default_factory=list)
    units: dict[str, tuple[str, Mapping[str, str]] | None] = field(default_factory=dict)
    namespaces: dict[str, set[str]] = field(default_factory=dict)
    unsupported: list[str] = field(default_factory=list)
    canonical_sha256: str = ""

    @staticmethod
    def expanded(qname: str, ns: Mapping[str, str]) -> tuple[str, str]:
        """(namespace URI, local name) of a prefixed name, resolved in the scope of the element that carries it."""
        prefix, sep, local = qname.partition(":")
        if not sep or not prefix or not local:
            raise _block("UNSUPPORTED_TEMPLATE", f"unprefixed name {qname[:40]!r}")
        uri = ns.get(prefix)  # XML prefixes are case-sensitive
        if uri is None:
            raise _block("UNSUPPORTED_TEMPLATE", f"prefix {prefix!r} is not bound where {qname[:40]!r} is used")
        return uri, local

    def check_xbrl_structure(self) -> None:
        """Supported layout: a well-formed inline XBRL document (read by a namespace-aware XML parser, so elements
        are identified by namespace and prefixes keep their exact case and scope) in which no prefix is bound to more
        than one namespace."""
        if self.unsupported:
            raise _block("UNSUPPORTED_TEMPLATE", self.unsupported[0][:200])
        rebound = sorted(p for p, uris in self.namespaces.items() if len(uris) != 1)
        if rebound:
            raise _block("UNSUPPORTED_TEMPLATE", f"namespace prefix {rebound[0]!r} bound more than once")

    def cover_value(self, name: str) -> str:
        """The one value of a dei cover fact (all occurrences under any prefix bound to the reviewed dei namespace)."""
        self.check_xbrl_structure()
        _, local = name.split(":", 1)
        values: set[str] = set()
        for qname, ns, value in self.cover:
            uri, fact_local = self.expanded(qname, ns)
            if fact_local == local and NAMESPACES["dei"].match(uri):
                values.add(value)
        if len(values) != 1:
            raise _block("SOURCE_DISAGREEMENT", f"{name} has {len(values)} values")
        return next(iter(values))


class _Parser(HTMLParser):
    """Text blocks and table rows of an HTML document (inline XBRL data is read separately as XML)."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.blocks: list[str] = []
        self.current: list[str] = []
        self.tables: list[list[list[tuple[str, int]]]] = []
        self.table_stack: list[list[list[tuple[str, int]]]] = []
        self.cell: list[str] | None = None
        self.hidden = 0

    def _flush(self) -> int | None:
        text = SPACE.sub(" ", "".join(self.current)).strip()
        self.current = []
        if text:
            self.blocks.append(text)
            return len(self.blocks) - 1
        return None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in HIDDEN_TAGS:
            self.hidden += 1
        if self.hidden:
            return
        if tag == "table" and self.cell is not None:
            self._end_cell()
        if tag in BLOCK_TAGS and self.cell is None:
            self._flush()
        if tag == "table":
            self.table_stack.append([])
        elif tag == "tr" and self.table_stack:
            self.table_stack[-1].append([])
        elif tag in ("td", "th") and self.table_stack:
            self.cell = []

    def _end_cell(self) -> None:
        index = self._flush()
        if not self.table_stack[-1]:
            self.table_stack[-1].append([])
        if index is not None:
            self.table_stack[-1][-1].append((self.blocks[index], index))
        self.cell = None

    def handle_endtag(self, tag: str) -> None:
        if tag in HIDDEN_TAGS and self.hidden:
            self.hidden -= 1
            return
        if self.hidden:
            return
        if tag in ("td", "th") and self.table_stack and self.cell is not None:
            self._end_cell()
        elif tag in BLOCK_TAGS and self.cell is None:
            self._flush()
        if tag == "table" and self.table_stack:
            self.tables.append(self.table_stack.pop())

    def handle_data(self, data: str) -> None:
        if not self.hidden:
            self.current.append(data)
            if self.cell is not None:
                self.cell.append(data)


def parse_ixbrl(canonical: bytes) -> dict[str, Any]:
    """Facts, contexts, units, cover facts and namespace declarations of an inline XBRL document, read with a
    namespace-aware XML parser: elements are identified by (namespace, local name), and every fact, cover fact and
    unit measure keeps the exact prefix bindings in scope at its own element (XML semantics: case-sensitive, scoped,
    attribute values never declare anything). Anything the parser cannot read faithfully is recorded as unsupported."""
    out: dict[str, Any] = {"facts": [], "contexts": {}, "units": {}, "cover": [], "namespaces": {}, "unsupported": [], "duplicates": []}
    if len(EDGAR_INJECTION.findall(canonical)) > 1 or b"<!ENTITY" in canonical:
        out["unsupported"].append("unexpected markup before the inline XBRL document")
        return out
    data = EDGAR_INJECTION.sub(b"", canonical, count=1)
    scopes: list[Mapping[str, str]] = [{}]
    pending: dict[str, str] = {}
    measure_scope: dict[int, Mapping[str, str]] = {}
    try:
        for event, item in ET.iterparse(io.BytesIO(data), events=("start-ns", "start", "end")):
            if event == "start-ns":
                prefix, uri = item
                pending[prefix] = uri
                out["namespaces"].setdefault(prefix, set()).add(uri)
                continue
            if event == "start":
                scopes.append({**scopes[-1], **pending} if pending else scopes[-1])
                pending = {}
                continue
            scope = scopes.pop()
            tag = item.tag
            if tag == IX + "nonFraction":
                out["facts"].append(Fact(item.get("name", ""), item.get("contextRef", ""), item.get("unitRef", ""),
                                         SPACE.sub("", "".join(item.itertext())), (item.get("format") or "").strip(),
                                         item.get("scale", ""), item.get("sign", ""), scope))
            elif tag == IX + "nonNumeric":
                name = item.get("name", "")
                if name.partition(":")[2] in ("DocumentType", "DocumentPeriodEndDate"):
                    out["cover"].append((name, scope, SPACE.sub(" ", "".join(item.itertext())).strip()))
            elif tag == XBRLI + "measure":
                measure_scope[id(item)] = scope
            elif tag == XBRLI + "unit":
                uid = item.get("id", "")
                if uid in out["units"]:
                    out["duplicates"].append(uid)
                # Supported: a simple unit whose only child is one measure (its own text, read in its own scope).
                children = list(item)
                simple = len(children) == 1 and children[0].tag == XBRLI + "measure" and len(children[0]) == 0
                out["units"][uid] = ((children[0].text or "").strip(), measure_scope[id(children[0])]) if simple else None
            elif tag == XBRLI + "context":
                cid = item.get("id", "")
                if cid in out["contexts"]:
                    out["duplicates"].append(cid)
                out["contexts"][cid] = _context_shape(item)
    except ET.ParseError as error:
        out["unsupported"].append(f"not well-formed XML: {error}")
    return out


def _context_shape(item: Any) -> Context:
    """The supported context shape, else an invalid context: one entity with exactly one identifier (and at most one
    segment), exactly one period that is either one startDate plus one endDate, one instant or one forever, and at most
    one scenario; each date element a leaf with text. Nothing is first-matched."""
    children = list(item)
    tags = [c.tag for c in children]
    entity = [c for c in children if c.tag == XBRLI + "entity"]
    period = [c for c in children if c.tag == XBRLI + "period"]
    valid = (len(entity) == 1 and len(period) == 1 and tags.count(XBRLI + "scenario") <= 1
             and all(t in (XBRLI + "entity", XBRLI + "period", XBRLI + "scenario") for t in tags))
    cik = start = end = instant = None
    if valid:
        e_children = list(entity[0])
        identifiers = [c for c in e_children if c.tag == XBRLI + "identifier"]
        valid = (len(identifiers) == 1 and len(identifiers[0]) == 0 and bool((identifiers[0].text or "").strip())
                 and all(c.tag in (XBRLI + "identifier", XBRLI + "segment") for c in e_children)
                 and [c.tag for c in e_children].count(XBRLI + "segment") <= 1)
        if valid:
            cik = (identifiers[0].text or "").strip()
        p_children = list(period[0])
        p_tags = [c.tag for c in p_children]
        leaves = all(len(c) == 0 and bool((c.text or "").strip()) or c.tag == XBRLI + "forever" for c in p_children)
        if p_tags == [XBRLI + "startDate", XBRLI + "endDate"] and leaves:
            start, end = ((c.text or "").strip() for c in p_children)
        elif p_tags == [XBRLI + "instant"] and leaves:
            instant = (p_children[0].text or "").strip()
        elif p_tags != [XBRLI + "forever"]:
            valid = False
    return Context(cik=cik, start=start, end=end, instant=instant, valid=valid,
                   has_segment=any(e.tag in (XBRLI + "segment", XBRLI + "scenario") for e in item.iter()))


def parse_document(raw: bytes) -> Document:
    if len(raw) > MAX_DOCUMENT_BYTES:
        raise _block("CAPTURE_LIMIT", "document over 16 MiB")
    canonical = canonical_bytes(raw)
    try:
        html_text = canonical.decode("utf-8")
    except UnicodeDecodeError as error:
        raise _block("CANONICALIZATION_FAILED", f"not UTF-8 at byte {error.start}") from error
    parser = _Parser()
    parser.feed(html_text)
    parser.close()
    parser._flush()
    offsets: list[tuple[int, int]] = []
    position = 0
    for block in parser.blocks:
        offsets.append((position, position + len(block)))
        position += len(block) + 1
    text = " ".join(parser.blocks)
    if len(text) > MAX_CANONICAL_TEXT:
        raise _block("CAPTURE_LIMIT", "canonical text over 4 MiB")
    tables = []
    for table in parser.tables:
        rows = []
        for row in table:
            if row:
                rows.append(([c for c, _ in row], offsets[row[0][1]][0], offsets[row[-1][1]][1]))
        if rows:
            tables.append(rows)
    if IX[1:-1].encode("ascii") in canonical:
        x = parse_ixbrl(canonical)
        if x["duplicates"]:
            raise _block("SOURCE_DISAGREEMENT", f"duplicate XBRL context/unit ids {x['duplicates'][:3]}")
        doc = Document(text=text, blocks=offsets, tables=tables, facts=x["facts"], contexts=x["contexts"], cover=x["cover"],
                       units=x["units"], namespaces=x["namespaces"], unsupported=x["unsupported"])
    else:
        doc = Document(text=text, blocks=offsets, tables=tables, unsupported=["not an inline XBRL document"])
    doc.canonical_sha256 = sha256(text.encode("utf-8"))
    return doc


# ----------------------------------------------------------------------------------------------------------------
# Profiles (reviewed policy; strict keys; regexes are reviewed configuration, never taken from documents)
# ----------------------------------------------------------------------------------------------------------------

PROFILE_KEYS = {"symbol", "profile_id", "revision", "company_name", "cik", "currency", "accounting_basis", "scope",
                "release", "guidance", "actuals", "calendar", "ir_title_pattern", "wire_title_pattern", "ir_host",
                "ir_page_pattern", "wire_page_pattern"}
RELEASE_KEYS = {"form", "item", "exhibit_name_pattern", "summary_table_units_pattern", "summary_revenue_row_pattern"}
GUIDANCE_KEYS = {"kind", "section_heading_pattern", "intro_pattern", "revenue_pattern", "family_pattern", "max_gap", "max_blocks_after_heading",
                 "table_period_pattern", "table_value_pattern", "table_column_pattern", "table_row_pattern", "band_kind"}
ACTUAL_KEYS = {"mode", "concepts", "measure"}
CALENDAR_KEYS = {"rule", "rule_quote", "allocation", "allocation_pattern", "label_format"}


def _regex(value: Any, where: str) -> re.Pattern[str]:
    if not isinstance(value, str) or not value or len(value) > MAX_REGEX_LENGTH:
        raise ValueError(f"PROFILE_REGEX {where}")
    try:
        return re.compile(value)
    except re.error as error:
        raise ValueError(f"PROFILE_REGEX {where}: {error}") from None


def validate_profiles(data: Any) -> dict[str, dict[str, Any]]:
    """Strict validation of the reviewed profile file; returns {symbol: profile} for the enabled symbols only."""
    if not isinstance(data, dict) or set(data) != {"schema", "policy_id", "enabled_symbols", "profiles"}:
        raise ValueError("PROFILES_ROOT_KEYS")
    if data["schema"] != PROFILES_SCHEMA or not isinstance(data["policy_id"], str) or len(data["policy_id"]) > 60:
        raise ValueError("PROFILES_SCHEMA")
    enabled = data["enabled_symbols"]
    if not isinstance(enabled, list) or len(enabled) > 16 or len(set(enabled)) != len(enabled):
        raise ValueError("PROFILES_ENABLED")
    by_symbol: dict[str, dict[str, Any]] = {}
    for prof in data["profiles"] if isinstance(data["profiles"], list) else []:
        if not isinstance(prof, dict) or set(prof) != PROFILE_KEYS:
            raise ValueError(f"PROFILE_KEYS {sorted(set(prof) ^ PROFILE_KEYS) if isinstance(prof, dict) else prof}")
        sym = prof["symbol"]
        if not isinstance(sym, str) or not re.fullmatch(r"[A-Z][A-Z0-9.\-]{0,15}", sym) or sym in by_symbol:
            raise ValueError("PROFILE_SYMBOL")
        if type(prof["cik"]) is not int or not 0 < prof["cik"] < 10**10:
            raise ValueError(f"PROFILE_CIK {sym}")
        if prof["currency"] != "USD" or prof["accounting_basis"] != "GAAP" or prof["scope"] != "COMPANY":
            raise ValueError(f"PROFILE_BASIS {sym}")
        if not isinstance(prof["revision"], int) or not isinstance(prof["profile_id"], str):
            raise ValueError(f"PROFILE_ID {sym}")
        rel, gui, act, cal = prof["release"], prof["guidance"], prof["actuals"], prof["calendar"]
        if not isinstance(rel, dict) or set(rel) != RELEASE_KEYS or rel["form"] != "8-K" or rel["item"] != "2.02":
            raise ValueError(f"PROFILE_RELEASE {sym}")
        for key in ("exhibit_name_pattern", "summary_table_units_pattern", "summary_revenue_row_pattern"):
            _regex(rel[key], f"{sym}.release.{key}")
        if not isinstance(gui, dict) or not set(gui) <= GUIDANCE_KEYS or gui.get("kind") not in ("SENTENCE", "OUTLOOK_TABLE"):
            raise ValueError(f"PROFILE_GUIDANCE {sym}")
        needed = ({"kind", "section_heading_pattern", "intro_pattern", "revenue_pattern", "family_pattern", "max_gap",
                   "max_blocks_after_heading", "band_kind"}
                  if gui["kind"] == "SENTENCE" else
                  {"kind", "table_period_pattern", "table_value_pattern", "table_column_pattern", "table_row_pattern", "band_kind"})
        if set(gui) != needed or gui["band_kind"] not in ("PERCENT", "ABSOLUTE"):
            raise ValueError(f"PROFILE_GUIDANCE_KEYS {sym}")
        for key in needed - {"kind", "max_gap", "max_blocks_after_heading", "band_kind"}:
            _regex(gui[key], f"{sym}.guidance.{key}")
        if gui["kind"] == "SENTENCE" and (type(gui["max_gap"]) is not int or not 0 <= gui["max_gap"] <= 40
                                          or type(gui["max_blocks_after_heading"]) is not int or not 0 <= gui["max_blocks_after_heading"] <= 4):
            raise ValueError(f"PROFILE_GAP {sym}")
        if not isinstance(act, dict) or set(act) != ACTUAL_KEYS or act["mode"] != "INLINE_XBRL_PERIODIC" or act["measure"] != "iso4217:USD":
            raise ValueError(f"PROFILE_ACTUALS {sym}")
        if not isinstance(act["concepts"], list) or not 1 <= len(act["concepts"]) <= 3 or not all(
                isinstance(c, str) and re.fullmatch(r"us-gaap:[A-Za-z]{3,120}", c) for c in act["concepts"]):
            raise ValueError(f"PROFILE_CONCEPTS {sym}")
        if not isinstance(cal, dict) or set(cal) != CALENDAR_KEYS or cal["rule"] not in RULE_KINDS or cal["allocation"] != "Q4_EXTRA_WEEK":
            raise ValueError(f"PROFILE_CALENDAR {sym}")
        if not isinstance(cal["rule_quote"], str) or not 20 <= len(cal["rule_quote"]) <= 300:
            raise ValueError(f"PROFILE_RULE_QUOTE {sym}")
        _regex(cal["allocation_pattern"], f"{sym}.calendar.allocation_pattern")
        if "(?P<year>" not in cal["allocation_pattern"]:
            raise ValueError(f"PROFILE_ALLOCATION_YEAR {sym}")
        if not isinstance(cal["label_format"], str) or not re.fullmatch(r"[A-Z ]{0,4}\{q\}[A-Z \-]{0,4}\{yy\}", cal["label_format"]):
            raise ValueError(f"PROFILE_LABEL {sym}")
        for key in ("ir_title_pattern", "wire_title_pattern"):
            _regex(prof[key], f"{sym}.{key}")
            if "(?P<q>" not in prof[key] or "(?P<fy>" not in prof[key]:
                raise ValueError(f"PROFILE_TITLE_GROUPS {sym}.{key}")
        host = prof["ir_host"]
        if not isinstance(host, str) or not re.fullmatch(r"[a-z0-9-]{1,40}(?:\.[a-z0-9-]{1,40}){1,4}", host) or host.endswith("sec.gov"):
            raise ValueError(f"PROFILE_IR_HOST {sym}")
        for key, prefix in (("ir_page_pattern", "^https://" + re.escape(host) + "/"), ("wire_page_pattern", "^https://www\\.nasdaq\\.com/press-release/")):
            _regex(prof[key], f"{sym}.{key}")
            if not prof[key].startswith(prefix) or not prof[key].endswith("$"):
                raise ValueError(f"PROFILE_PAGE_PATTERN {sym}.{key}")
        by_symbol[sym] = prof
    if not set(enabled) <= set(by_symbol):
        raise ValueError("PROFILES_ENABLED_WITHOUT_PROFILE")
    return {sym: by_symbol[sym] for sym in enabled}


# ----------------------------------------------------------------------------------------------------------------
# Fiscal calendar (52/53-week, from the declared rule; the extra week needs its own documentary statement)
# ----------------------------------------------------------------------------------------------------------------

def fiscal_year_end(rule: str, fiscal_year: int) -> date:
    if rule == "LAST_SUNDAY_OF_JANUARY":
        d = date(fiscal_year, 1, 31)
        return d - timedelta(days=(d.weekday() - 6) % 7)
    if rule == "THURSDAY_CLOSEST_TO_AUGUST_31":
        target = date(fiscal_year, 8, 31)
        candidates = [target + timedelta(days=k) for k in range(-3, 4)]
        return next(c for c in candidates if c.weekday() == 3)
    raise ValueError(f"UNKNOWN_RULE {rule}")


def fiscal_quarter(rule: str, fiscal_year: int, quarter: int) -> tuple[date, date]:
    start = fiscal_year_end(rule, fiscal_year - 1) + timedelta(days=1)
    end_of_year = fiscal_year_end(rule, fiscal_year)
    weeks = ((end_of_year - start).days + 1) // 7
    if (end_of_year - start).days + 1 != weeks * 7 or weeks not in (52, 53):
        raise ValueError("CALENDAR_ARITHMETIC")
    q_start = start + timedelta(weeks=13 * (quarter - 1))
    q_end = end_of_year if quarter == 4 else q_start + timedelta(weeks=13) - timedelta(days=1)
    return q_start, q_end


def year_weeks(rule: str, fiscal_year: int) -> int:
    start = fiscal_year_end(rule, fiscal_year - 1) + timedelta(days=1)
    return ((fiscal_year_end(rule, fiscal_year) - start).days + 1) // 7


def next_quarter(quarter: int, fiscal_year: int, step: int = 1) -> tuple[int, int]:
    index = fiscal_year * 4 + (quarter - 1) + step
    return index % 4 + 1, index // 4


def label(fmt: str, quarter: int, fiscal_year: int) -> str:
    return fmt.replace("{q}", str(quarter)).replace("{yy}", f"{fiscal_year % 100:02d}")


# ----------------------------------------------------------------------------------------------------------------
# Guidance
# ----------------------------------------------------------------------------------------------------------------

MULT = {"billion": Decimal(10) ** 9, "million": Decimal(10) ** 6}


def _amount(number: str, unit: str) -> Decimal:
    if unit.lower() not in MULT:
        raise _block("UNIT_MISMATCH", unit)
    try:
        return Decimal(number.replace(",", "")) * MULT[unit.lower()]
    except InvalidOperation:
        raise _block("UNIT_MISMATCH", number) from None


def _period_words(text: str) -> tuple[int, int]:
    m = re.fullmatch(r"(first|second|third|fourth) quarter of fiscal (?:year )?(\d{4})", text.strip(), re.I)
    if not m:
        raise _block("PERIOD_MISMATCH", f"period wording {text[:60]!r}")
    return ORDINALS[m.group(1).lower()], int(m.group(2))


def extract_guidance(doc: Document, profile: Mapping[str, Any]) -> dict[str, Any]:
    """The one revenue outlook of the release: (quarter, fiscal_year, point, low, high, representation, passage,
    offsets). Cardinality: exactly one; any competing revenue outlook blocks."""
    g = profile["guidance"]
    if g["kind"] == "SENTENCE":
        family = list(re.finditer(g["family_pattern"], doc.text))
        revenue = list(re.finditer(g["revenue_pattern"], doc.text))
        intros = list(re.finditer(g["intro_pattern"], doc.text))
        if not revenue and not family:
            raise _block("NO_MATCH", "no revenue outlook sentence")
        if len(revenue) != 1 or len(family) != 1 or family[0].start() != revenue[0].start() or len(intros) != 1:
            raise _block("AMBIGUOUS", f"revenue={len(revenue)} family={len(family)} intro={len(intros)}")
        intro, rev = intros[0], revenue[0]
        gap = doc.text[intro.end():rev.start()]
        if rev.start() < intro.end() or len(gap) > g["max_gap"] or re.search(r"[A-Za-z0-9]", gap):
            raise _block("AMBIGUOUS", "revenue sentence is not the outlook statement's own item")
        intro_block = next(i for i, (s, e) in enumerate(doc.blocks) if s <= intro.start() < e + 1)
        window = range(max(0, intro_block - 1 - g["max_blocks_after_heading"]), intro_block)
        if not any(re.fullmatch(g["section_heading_pattern"], doc.text[slice(*doc.blocks[i])]) for i in window):
            raise _block("NO_MATCH", "outlook statement is not under its Outlook heading")
        quarter, fiscal_year = _period_words(intro.group("period"))
        point = _amount(rev.group("point"), rev.group("unit"))
        band = Decimal(rev.group("band"))
        if g["band_kind"] != "PERCENT":
            raise _block("UNSUPPORTED_TEMPLATE", "sentence band kind")
        low, high = point * (1 - band / 100), point * (1 + band / 100)
        start, end = intro.start(), rev.end()
        representation = f"${rev.group('point')} {rev.group('unit')}, plus or minus {rev.group('band')}%"
    else:
        found = []
        for rows in doc.tables:
            header, _, _ = rows[0]
            if not header or not re.fullmatch(g["table_period_pattern"], header[0]):
                continue
            cols = [i for i, c in enumerate(header) if re.fullmatch(g["table_column_pattern"], c)]
            rev_rows = [r for r in rows[1:] if r[0] and re.fullmatch(g["table_row_pattern"], r[0][0])]
            if not cols or len(rev_rows) != 1:
                raise _block("AMBIGUOUS", "outlook table columns or revenue row")
            cells, _, row_end = rev_rows[0]
            values = []
            for i in cols:
                if i >= len(cells):
                    raise _block("AMBIGUOUS", "outlook column without value")
                m = re.fullmatch(g["table_value_pattern"], cells[i])
                if not m:
                    raise _block("NO_MATCH", f"outlook value {cells[i][:60]!r}")
                values.append((m.group("point"), m.group("unit"), m.group("band"), m.group("band_unit")))
            found.append((header[0], values, rows[0][1], row_end))
        if not found:
            raise _block("NO_MATCH", "no outlook table")
        distinct = {(h, v) for h, vals, _, _ in found for v in vals}
        if len({h for h, _ in distinct}) != 1 or len({v for _, v in distinct}) != 1:
            raise _block("SOURCE_DISAGREEMENT", f"outlook tables disagree: {sorted(distinct)[:4]}")
        period_label, (p, unit, b, bunit) = next(iter(distinct))
        m = re.fullmatch(g["table_period_pattern"], period_label)
        quarter, fiscal_year = int(m.group("q")), 2000 + int(m.group("yy"))
        point, band = _amount(p, unit), _amount(b, bunit)
        low, high = point - band, point + band
        start, end = found[0][2], found[0][3]
        representation = f"${p} {unit} ± ${b} {bunit}"
    passage = doc.text[start:end]
    if len(passage) > MAX_PASSAGE:
        raise _block("UNSUPPORTED_TEMPLATE", "passage over 1000 characters")
    if not (0 < low <= point <= high):
        raise _block("UNIT_MISMATCH", "range order")
    return {"quarter": quarter, "fiscal_year": fiscal_year, "point": point, "low": low, "high": high,
            "representation": representation, "passage": passage, "offsets": [start, end]}


def detect_transitions(doc: Document) -> list[tuple[str, str]]:
    """(reason, matched text) for every withdrawal, suspension, non-reliance/restatement or revision of earlier
    guidance stated anywhere in the document."""
    return [(reason, m.group(0)[:200]) for reason, pattern in TRANSITIONS for m in pattern.finditer(doc.text)]


def competing_outlooks(doc: Document, profile: Mapping[str, Any], guidance: Mapping[str, Any]) -> bool:
    """True when another publication of the release states a revenue outlook different from the verified one (or more
    outlook statements than the release itself)."""
    g = profile["guidance"]
    if g["kind"] == "SENTENCE":
        family = list(re.finditer(g["family_pattern"], doc.text))
        values = {(m.group("point"), m.group("unit"), m.group("band")) for m in re.finditer(g["revenue_pattern"], doc.text)}
        return len(family) != 1 or len(values) != 1 or _amount(*next(iter(values))[:2]) != guidance["point"]
    # Table profiles: every outlook value that follows a revenue row label (flattened table text) must be the verified one.
    value = re.compile(g["table_value_pattern"])
    values = set()
    for row in re.finditer(r"(?<![A-Za-z])(?:" + g["table_row_pattern"] + r")(?![A-Za-z])", doc.text):
        pos = row.end()
        while True:
            m = value.match(doc.text, pos + len(doc.text[pos:]) - len(doc.text[pos:].lstrip()))
            if not m:
                break
            values.add((m.group("point"), m.group("unit"), m.group("band"), m.group("band_unit")))
            pos = m.end()
    if len(values) != 1:
        return True
    p, unit, b, bunit = next(iter(values))
    return _amount(p, unit) != guidance["point"] or _amount(p, unit) - _amount(b, bunit) != guidance["low"]


def detect_withdrawal(doc: Document) -> list[str]:
    return [text for reason, text in detect_transitions(doc) if reason == "WITHDRAWAL"]


def copy_key(text: str) -> str:
    """Comparison form for another publication of the same release: whitespace and list bullets removed."""
    return re.sub(r"[\s\u2022\u00b7\u25aa\u25cf]+", "", text)


# ----------------------------------------------------------------------------------------------------------------
# Actuals from the periodic filings' inline XBRL, reconciled to the release
# ----------------------------------------------------------------------------------------------------------------

def xbrl_duration(doc: Document, concepts: list[str], measure: str, cik: int, start: date, end: date) -> tuple[str, Decimal]:
    """The one company-wide value for exactly [start, end] in this filing: facts of any listed (reviewed equivalent)
    concept in a context without dimensions whose unit resolves to exactly `measure`; every such fact of every listed
    concept must agree. Returns the first listed concept that carries it."""
    doc.check_xbrl_structure()
    wanted = {}
    for concept in concepts:
        prefix, local = concept.split(":", 1)
        wanted[local] = (concept, NAMESPACES[prefix])
    m_prefix, m_local = measure.split(":", 1)
    found: dict[str, set[Decimal]] = {}
    for f in doc.facts:
        if ":" not in f.concept or f.concept.partition(":")[2] not in wanted:
            continue
        uri, local = doc.expanded(f.concept, f.ns)
        reviewed, pattern = wanted[local]
        if not pattern.match(uri):
            if uri.startswith("http://fasb.org/us-gaap/") or local in ("Revenues",):
                raise _block("UNSUPPORTED_TEMPLATE", f"{f.concept} in namespace {uri[:60]}")
            continue
        ctx = doc.contexts.get(f.context)
        if ctx is None:
            raise _block("SOURCE_DISAGREEMENT", f"fact without context {f.context}")
        if not ctx.valid:
            raise _block("UNSUPPORTED_TEMPLATE", f"context {f.context} is not a supported shape")
        if ctx.has_segment or ctx.start != start.isoformat() or ctx.end != end.isoformat():
            continue
        if ctx.cik is None or not ctx.cik.isdigit() or int(ctx.cik) != cik:
            raise _block("SOURCE_DISAGREEMENT", f"context entity {ctx.cik}")
        unit = doc.units.get(f.unit_id)
        if unit is None or ":" not in unit[0]:
            raise _block("UNIT_MISMATCH", f"{f.concept} unit {f.unit_id} is not a single measure")
        unit_uri, unit_local = doc.expanded(unit[0], unit[1])
        if unit_local != m_local or not NAMESPACES[m_prefix].match(unit_uri):
            raise _block("UNIT_MISMATCH", f"{f.concept} unit {f.unit_id} is {unit[0]!r} in {unit_uri[:60]}")
        found.setdefault(reviewed, set()).add(f.value())
    values = set().union(*found.values()) if found else set()
    if len(values) > 1:
        raise _block("SOURCE_DISAGREEMENT", f"{start}..{end} has {len(values)} values across {sorted(found)}")
    if not values:
        raise _block("ACTUAL_NOT_FOUND", f"{start}..{end}")
    value = values.pop()
    if value <= 0:
        raise _block("SOURCE_DISAGREEMENT", "non-positive revenue")
    return next(c for c in concepts if c in found), value


def cover_period_end(doc: Document) -> date:
    text = doc.cover_value("dei:DocumentPeriodEndDate").replace("\u00a0", " ")
    for fmt in ("%Y-%m-%d", "%B %d, %Y", "%b %d, %Y", "%B %d,%Y"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    raise _block("SOURCE_DISAGREEMENT", f"cover period end {text[:30]!r}")


def release_revenue(doc: Document, profile: Mapping[str, Any], period_label: str) -> Decimal:
    """The release's summary-table revenue for the quarter the table leads with (first column = GAAP)."""
    rel = profile["release"]
    hits = []
    for rows in doc.tables:
        cells = [c for r, _, _ in rows for c in r]
        if not any(re.search(rel["summary_table_units_pattern"], c) for c in cells):
            continue
        header = next((r for r, _, _ in rows if period_label in r), None)
        rev = [r for r, _, _ in rows if r and re.fullmatch(rel["summary_revenue_row_pattern"], r[0])]
        if header is None or len(rev) != 1:
            continue
        labels = [c for c in header if re.fullmatch(r"[A-Z0-9 \-]{2,12}|[A-Z]/[A-Z]", c)]
        numbers = [c.replace("$", "").replace(",", "").strip() for c in rev[0][1:] if c not in ("$", "%")]
        numbers = [n for n in numbers if re.fullmatch(r"\d+(?:\.\d+)?", n)]
        if not labels or len(numbers) < len(labels):
            continue
        if labels[0] != period_label:
            raise _block("PERIOD_MISMATCH", f"release reports {labels[0]}, outlook implies {period_label}")
        hits.append(Decimal(numbers[labels.index(period_label)]) * MULT["million"])
    if not hits:
        raise _block("RELEASE_ROW_NOT_FOUND", period_label)
    if len(set(hits)) != 1:
        raise _block("SOURCE_DISAGREEMENT", f"release revenue rows {sorted(set(hits))}")
    return hits[0]


# ----------------------------------------------------------------------------------------------------------------
# Event binding: every filing identity comes from the captured EDGAR submissions feed and accession index
# ----------------------------------------------------------------------------------------------------------------

ARCHIVE_URL = re.compile(r"^https://www\.sec\.gov/Archives/edgar/data/([0-9]{1,10})/([0-9]{18})/([A-Za-z0-9][A-Za-z0-9._-]{0,119})$")
MAX_PACKAGE_DOCUMENTS = 8


@dataclass
class Filing:
    accession: str
    form: str
    filed: str
    report: str
    primary: str
    items: tuple[str, ...]


def dashed(accession18: str) -> str:
    return f"{accession18[:10]}-{accession18[10:12]}-{accession18[12:]}"


def archive_parts(url: str, cik: int) -> tuple[str, str]:
    """(accession, file name) of an EDGAR archive URL of this issuer, else APPROVAL_BINDING."""
    m = ARCHIVE_URL.match(str(url))
    if not m or int(m.group(1)) != cik:
        raise _block("APPROVAL_BINDING", f"not an archive document of CIK {cik}")
    return dashed(m.group(2)), m.group(3)


def parse_submissions(raw: bytes, cik: int) -> dict[str, Filing]:
    try:
        data = json.loads(raw.decode("utf-8"))
        if int(data["cik"]) != cik:
            raise _block("APPROVAL_BINDING", "submissions of another issuer")
        recent = data["filings"]["recent"]
        columns = [recent[k] for k in ("accessionNumber", "form", "filingDate", "reportDate", "primaryDocument", "items")]
    except (UnicodeDecodeError, ValueError, KeyError, TypeError):
        raise _block("EVENT_UNRESOLVED", "submissions feed shape") from None
    if not all(isinstance(c, list) and len(c) == len(columns[0]) for c in columns):
        raise _block("EVENT_UNRESOLVED", "submissions feed columns")
    out: dict[str, Filing] = {}
    for acc, form, filed, report, primary, items in zip(*columns):
        if not all(isinstance(x, str) for x in (acc, form, filed, report, primary, items)):
            raise _block("EVENT_UNRESOLVED", "submissions feed values")
        if acc in out:
            raise _block("SOURCE_DISAGREEMENT", f"accession {acc} listed twice")
        out[acc] = Filing(acc, form, filed, report, primary, tuple(i.strip() for i in items.split(",") if i.strip()))
    return out


def parse_index(raw: bytes) -> list[str]:
    try:
        names = [item["name"] for item in json.loads(raw.decode("utf-8"))["directory"]["item"]]
    except (UnicodeDecodeError, ValueError, KeyError, TypeError):
        raise _block("EVENT_UNRESOLVED", "accession index shape") from None
    if not all(isinstance(n, str) for n in names) or len(set(names)) != len(names):
        raise _block("EVENT_UNRESOLVED", "accession index names")
    return names


def package_names(names: list[str]) -> list[str]:
    """The HTML documents of a filing (the form and its exhibits), without EDGAR's index and XBRL viewer pages."""
    return sorted(n for n in names if n.lower().endswith((".htm", ".html")) and "index" not in n.lower()
                  and not re.fullmatch(r"R[0-9]+\.htm", n))


# ----------------------------------------------------------------------------------------------------------------
# Successor
# ----------------------------------------------------------------------------------------------------------------

def _doc_entry(symbol: str, company: str, doc_id: str, kind: str, capture: Mapping[str, Any], filed: str, title: str) -> dict[str, Any]:
    return {"id": doc_id, "issuer": symbol, "publisher": company, "title": title[:160], "source_kind": kind,
            "url": capture["url"], "published_date": filed, "retrieved_at": capture["retrieved_at"],
            "sha256": capture["sha256"], "byte_size": capture["bytes"], "lineage_id": doc_id}


def _f(value: Decimal) -> float:
    return float(value)


def build_successor(profile: Mapping[str, Any], predecessor: Mapping[str, Any], event: Mapping[str, Any],
                    captures: Mapping[str, Mapping[str, Any]], verified_at: str) -> dict[str, Any]:
    """One results event -> {"outcome": VERIFIED|WAITING|BLOCKED, "reason", "detail", "record", "decisions"}.

    `event` holds only discovery leads: {"accession", "filed", "periodic": {"YYYY-MM-DD" (quarter end): capture key},
    "calendar": key, "allocation_sources": [keys], "ir_item": {"id","title","date"} | None,
    "wire_item": {...} | None}; every identity (form, items, filing and report dates, exhibit membership, primary
    documents) is re-established from the captured submissions feed and accession index. `captures`: key ->
    {"url", "retrieved_at", "bytes", "raw_sha256", "sha256" (watermark-zeroed bytes), "raw": bytes, ...} with the fixed
    keys "submissions", "index", "exhibit", "package:<name>", "ir_copy", "wire_copy"; bytes are re-hashed and re-parsed
    here, nothing is trusted from a stored digest or outcome. Malformed input is a typed BLOCKED outcome."""
    try:
        return _build(profile, predecessor, event, captures, verified_at)
    except Blocked as b:
        return {"outcome": b.outcome, "reason": b.reason, "detail": b.detail, "record": None, "decisions": []}
    except (KeyError, TypeError, ValueError, AttributeError, IndexError, InvalidOperation) as error:
        return {"outcome": "BLOCKED", "reason": "INPUT_MALFORMED", "detail": f"{type(error).__name__}"[:300], "record": None,
                "decisions": []}


class _Inputs:
    """The captures of one event, each re-hashed, re-parsed and bound to the decision time."""

    def __init__(self, captures: Mapping[str, Mapping[str, Any]], verified_at: str):
        self.captures, self.verified_at = captures, verified_at
        self.parsed: dict[str, Document] = {}

    def raw(self, key: str | None) -> tuple[Mapping[str, Any], bytes]:
        if not isinstance(key, str) or key not in self.captures:
            raise _block("INPUT_MISSING", str(key)[:60])
        cap = self.captures[key]
        raw = cap["raw"]
        if not isinstance(raw, bytes) or len(raw) != cap["bytes"] or sha256(raw) != cap["raw_sha256"] or sha256(canonical_bytes(raw)) != cap["sha256"]:
            raise _block("APPROVAL_BINDING", f"capture {key} bytes do not match their identity")
        if not (isinstance(cap["retrieved_at"], str) and cap["retrieved_at"] <= self.verified_at):
            raise _block("APPROVAL_BINDING", f"capture {key} retrieved after the decision time")
        return cap, raw

    def doc(self, key: str | None) -> tuple[Mapping[str, Any], Document]:
        cap, raw = self.raw(key)
        if key not in self.parsed:
            self.parsed[key] = parse_document(raw)
        return cap, self.parsed[key]


def _build(profile, predecessor, event, captures, verified_at):
    sym, cik, company = profile["symbol"], profile["cik"], profile["company_name"]
    inputs = _Inputs(captures, verified_at)
    cal = profile["calendar"]
    day = verified_at[:10]
    # ---- the results filing, from the captured submissions feed and accession index
    subs_cap, subs_raw = inputs.raw("submissions")
    if subs_cap["url"] != f"https://data.sec.gov/submissions/CIK{cik:010d}.json":
        raise _block("APPROVAL_BINDING", "submissions capture of another issuer")
    filings = parse_submissions(subs_raw, cik)
    acc = event["accession"]
    filing = filings.get(acc)
    if filing is None or filing.form != "8-K" or "2.02" not in filing.items:
        raise _block("EVENT_UNRESOLVED", "not an item 2.02 results filing of this issuer")
    if event["filed"] != filing.filed or not filing.filed <= day or not filing.filed <= subs_cap["retrieved_at"][:10]:
        raise _block("APPROVAL_BINDING", "event date is not the filing date on EDGAR before the decision")
    index_cap, index_raw = inputs.raw("index")
    if index_cap["url"] != f"{SEC_ARCHIVES}{cik}/{acc.replace('-', '')}/index.json":
        raise _block("APPROVAL_BINDING", "index capture of another accession")
    names = parse_index(index_raw)
    exhibits = [n for n in names if re.search(profile["release"]["exhibit_name_pattern"], n)]
    if len(exhibits) != 1:
        raise _block("UNSUPPORTED_TEMPLATE" if not exhibits else "AMBIGUOUS", f"{len(exhibits)} release exhibits")
    rel_cap, rel = inputs.doc("exhibit")
    if archive_parts(rel_cap["url"], cik) != (acc, exhibits[0]):
        raise _block("APPROVAL_BINDING", "exhibit capture is not the accession's release exhibit")
    package = package_names(names)
    if len(package) > MAX_PACKAGE_DOCUMENTS:
        raise _block("CAPTURE_LIMIT", f"{len(package)} documents in the results filing")
    # Transitions anywhere in the results package (the release, the form, commentary exhibits) dominate.
    for name in package:
        key = "exhibit" if name == exhibits[0] else f"package:{name}"
        cap, doc = inputs.doc(key)
        if archive_parts(cap["url"], cik) != (acc, name):
            raise _block("APPROVAL_BINDING", f"package capture {name} is not in the accession")
        found = detect_transitions(doc)
        if found:
            raise _block(found[0][0], f"{name}: {found[0][1]}")
    # ---- guidance and the quarter it implies
    guidance = extract_guidance(rel, profile)
    gq, gfy = guidance["quarter"], guidance["fiscal_year"]
    aq, afy = next_quarter(gq, gfy, -1)                       # the quarter this release reports
    rule = cal["rule"]
    try:
        a_start, a_end = fiscal_quarter(rule, afy, aq)
    except ValueError as error:
        raise _block("CALENDAR_RULE_UNPROVEN", str(error)) from None
    if a_end.isoformat() >= filing.filed:
        raise _block("PERIOD_MISMATCH", "reported quarter does not end before the release")
    # Every trailing actual is re-derived from its own filing below, so a later release may follow a predecessor
    # older than one quarter; an older or same-quarter release after a newer predecessor is refused.
    pred_anchor = max(q["end"] for q in predecessor.get("reported_quarters") or [{"end": "0000-00-00"}])
    if pred_anchor >= a_end.isoformat():
        raise _block("OUT_OF_ORDER", f"predecessor anchor {pred_anchor}, release reports {a_start}..{a_end}")

    def periodic(key: str, forms: tuple[str, ...], report: date | None) -> tuple[Mapping[str, Any], Document, Filing]:
        cap, doc = inputs.doc(key)
        p_acc, name = archive_parts(cap["url"], cik)
        f = filings.get(p_acc)
        if f is None or f.form not in forms or name != f.primary or not f.filed <= day:
            raise _block("APPROVAL_BINDING", f"capture {key} is not a filed {'/'.join(forms)} of this issuer")
        if doc.cover_value("dei:DocumentType") != f.form:
            raise _block("SOURCE_DISAGREEMENT", f"cover document type of {p_acc}")
        if report is not None and (f.report != report.isoformat() or cover_period_end(doc) != report or not f.filed > report.isoformat()):
            raise _block("SOURCE_DISAGREEMENT", f"{p_acc} does not report {report}")
        return cap, doc, f

    # ---- calendar rule from the newest 10-K on EDGAR at the decision
    tenks = sorted((f for f in filings.values() if f.form == "10-K" and f.filed <= day), key=lambda f: (f.filed, f.accession))
    cal_cap, cal_doc, cal_filing = periodic(event["calendar"], ("10-K",), None)
    if not tenks or cal_filing.accession != tenks[-1].accession:
        raise _block("CALENDAR_RULE_UNPROVEN", "calendar source is not the newest 10-K")
    q_pos = cal_doc.text.find(cal["rule_quote"])
    if q_pos < 0:
        raise _block("CALENDAR_RULE_UNPROVEN", "rule quote not in the calendar filing")
    quarters_back = [next_quarter(aq, afy, -k) for k in (3, 2, 1, 0)]
    forward = [next_quarter(aq, afy, k) for k in (1, 2, 3, 4)]
    # ---- actuals: each trailing quarter from its own periodic filing; Q4 = FY (10-K) minus 9M (Q3 10-Q)
    by_end = event.get("periodic") or {}
    concepts, measure = profile["actuals"]["concepts"], profile["actuals"]["measure"]
    documents: dict[str, dict[str, Any]] = {}
    decisions: list[dict[str, Any]] = []
    consumed: list[dict[str, str]] = [{"channel": "SEC_SUBMISSIONS", "id": acc, "date": filing.filed}]
    reported = []
    for q, fy in quarters_back:
        q_start, q_end = fiscal_quarter(rule, fy, q)
        key = by_end.get(q_end.isoformat())
        if key is None:
            if (q, fy) == (aq, afy):
                raise Blocked("WAITING", "WAITING_PERIODIC_FILING", f"{q_end}")
            raise _block("INPUT_MISSING", f"periodic filing for {q_end}")
        cap, doc, f = periodic(key, ("10-Q", "10-K") if q == 4 else ("10-Q",), q_end)
        doc_id = f"{sym}-{f.accession}"
        documents[doc_id] = _doc_entry(sym, company, doc_id, "SEC_PERIODIC", cap, f.filed, f"{company} Form {f.form} ({f.accession})")
        consumed.append({"channel": "SEC_SUBMISSIONS", "id": f.accession, "date": f.filed})
        lbl = label(cal["label_format"], q, fy)
        if q < 4:
            concept, value = xbrl_duration(doc, concepts, measure, cik, q_start, q_end)
            row = {"fiscal_label": lbl, "start": q_start.isoformat(), "end": q_end.isoformat(), "revenue": _f(value),
                   "currency": "USD", "scope": "COMPANY", "accounting_basis": "GAAP", "document_id": doc_id,
                   "locator": f"XBRL {concept} {q_start}..{q_end}"}
            operands = {"concept": concept, "start": q_start.isoformat(), "end": q_end.isoformat(), "value": str(value)}
        else:
            if f.form != "10-K":
                raise _block("SOURCE_DISAGREEMENT", f"fourth quarter {q_end} is not reported by a 10-K")
            fy_start = fiscal_quarter(rule, fy, 1)[0]
            _, q3_end = fiscal_quarter(rule, fy, 3)
            key9 = by_end.get(q3_end.isoformat())
            if key9 is None:
                raise _block("INPUT_MISSING", f"Q3 filing for {q3_end}")
            cap9, doc9, f9 = periodic(key9, ("10-Q",), q3_end)
            concept, longer = xbrl_duration(doc, concepts, measure, cik, fy_start, q_end)
            concept9, shorter = xbrl_duration(doc9, concepts, measure, cik, fy_start, q3_end)
            value = longer - shorter
            if value <= 0:
                raise _block("SOURCE_DISAGREEMENT", "fourth-quarter derivation not positive")
            doc9_id = f"{sym}-{f9.accession}"
            documents[doc9_id] = _doc_entry(sym, company, doc9_id, "SEC_PERIODIC", cap9, f9.filed, f"{company} Form {f9.form} ({f9.accession})")
            row = {"fiscal_label": lbl, "start": q_start.isoformat(), "end": q_end.isoformat(), "revenue": _f(value),
                   "currency": "USD", "scope": "COMPANY", "accounting_basis": "GAAP", "document_id": doc_id,
                   "locator": f"XBRL {concept} {fy_start}..{q_end} minus ..{q3_end}",
                   "derivation": {"kind": "YTD_DIFFERENCE", "longer_document_id": doc_id, "longer_value": _f(longer),
                                  "longer_start": fy_start.isoformat(), "shorter_document_id": doc9_id,
                                  "shorter_value": _f(shorter), "shorter_end": q3_end.isoformat()}}
            operands = {"concept": concept, "longer": [fy_start.isoformat(), q_end.isoformat(), str(longer)],
                        "shorter_concept": concept9, "shorter": [fy_start.isoformat(), q3_end.isoformat(), str(shorter)],
                        "shorter_capture": key9}
        reported.append(row)
        decisions.append({"kind": "ACTUAL", "ref": q_end.isoformat(), "decision": "XBRL_FACT" if q < 4 else "XBRL_YTD_DIFFERENCE",
                          "capture": key, "operands": operands})
    # ---- 53-week years: the issuer's own statement of the extra-week quarter
    allocation_evidence = []
    for fy in sorted({fy for _, fy in quarters_back + forward}):
        if year_weeks(rule, fy) != 53:
            continue
        proof = None
        sources = set(by_end.values()) | {event["calendar"]} | set(event.get("allocation_sources") or [])
        for key in sorted(sources):
            _, d, _ = periodic(key, ("10-Q", "10-K"), None)
            for m in re.finditer(cal["allocation_pattern"], d.text):
                if int(m.group("year")) == fy:
                    proof = (key, m.start(), m.end(), m.group(0))
                    break
            if proof:
                break
        if proof is None:
            # The issuer states the extra-week quarter in a later periodic report: wait for it, never assume it.
            raise Blocked("WAITING", "CALENDAR_ALLOCATION_UNPROVEN", f"fiscal {fy} has 53 weeks")
        allocation_evidence.append({"fiscal_year": fy, "capture": proof[0], "offsets": [proof[1], proof[2]], "quote": proof[3]})
    # ---- the release's own revenue for the reported quarter equals the filing's; plausibility of the guided amount
    a_label = label(cal["label_format"], aq, afy)
    release_value = release_revenue(rel, profile, a_label)
    if Decimal(str(reported[-1]["revenue"])) != release_value:
        raise _block("SOURCE_DISAGREEMENT", f"release {release_value} vs filing {reported[-1]['revenue']}")
    ratio = guidance["point"] / release_value
    if not (Decimal("0.25") <= ratio <= Decimal("4")):
        raise _block("UNIT_MISMATCH", f"guided point is {ratio:.3f}x the reported quarter")
    decisions.append({"kind": "ACTUAL", "ref": f"release:{a_end.isoformat()}", "decision": "RELEASE_ROW_EQUALS_FILING",
                      "capture": "exhibit", "operands": {"label": a_label, "value": str(release_value)}})
    # ---- forward intervals from the calendar rule; the first is the guided quarter
    rel_id = f"{sym}-{acc}"
    cal_id = f"{sym}-{cal_filing.accession}"
    documents[rel_id] = _doc_entry(sym, company, rel_id, "SEC_8K_EXHIBIT", rel_cap, filing.filed, f"{company} earnings release with outlook ({acc})")
    documents.setdefault(cal_id, _doc_entry(sym, company, cal_id, "SEC_PERIODIC", cal_cap, cal_filing.filed, f"{company} Form 10-K ({cal_filing.accession})"))
    intervals = []
    for i, (q, fy) in enumerate(forward):
        s, e = fiscal_quarter(rule, fy, q)
        intervals.append({"fiscal_label": label(cal["label_format"], q, fy) if i == 0 else None, "start": s.isoformat(),
                          "end": e.isoformat(), "calendar_document_id": cal_id, "calendar_locator": cal["rule_quote"]})
    g_start, g_end = fiscal_quarter(rule, gfy, gq)
    if (g_start.isoformat(), g_end.isoformat()) != (intervals[0]["start"], intervals[0]["end"]):
        raise _block("PERIOD_MISMATCH", "guided quarter is not the next quarter")
    decisions.append({"kind": "CALENDAR", "ref": "calendar", "decision": "RULE_QUOTED", "capture": event["calendar"],
                      "operands": {"rule": rule, "offsets": [q_pos, q_pos + len(cal["rule_quote"])], "allocation": allocation_evidence}})
    claim = {"id": f"{sym}-Q-GUIDANCE", "document_id": rel_id,
             "locator": f"canonical[{guidance['offsets'][0]}:{guidance['offsets'][1]}] {NORMALIZER_VERSION}",
             "passage": guidance["passage"], "metric": "REVENUE", "assertion_kind": "COMPANY_GUIDANCE", "currency": "USD",
             "unit_multiplier": 1, "amount": None, "low": _f(guidance["low"]), "high": _f(guidance["high"]),
             "stated_point": _f(guidance["point"]), "original_representation": guidance["representation"],
             "scope": "COMPANY", "scope_label": "全公司", "accounting_basis": "GAAP",
             "fiscal_label": label(cal["label_format"], gq, gfy), "period_kind": "QUARTER",
             "period_start": g_start.isoformat(), "period_end": g_end.isoformat()}
    decisions.append({"kind": "CLAIM", "ref": claim["id"], "decision": "VERBATIM_IN_SOURCE", "capture": "exhibit",
                      "operands": {"offsets": guidance["offsets"], "point": str(guidance["point"]), "low": str(guidance["low"]),
                                   "high": str(guidance["high"]), "quarter": gq, "fiscal_year": gfy}})
    # ---- other publications of the same release: an official IR copy is required, a wire copy is optional; each is
    # the same release only when its captured page at exactly the listed address states the same outlook passage.
    key_text = copy_key(guidance["passage"])

    def same_release(item: Any, capture_key: str, title_pattern: str, page_pattern: str) -> bool:
        if not isinstance(item, Mapping) or set(item) != {"id", "title", "date"} or capture_key not in captures:
            return False
        m = re.fullmatch(title_pattern, str(item["title"]))
        if not m or (ORDINALS.get(m.group("q").lower()), int(m.group("fy"))) != (aq, afy) or item["date"] != filing.filed:
            return False
        cap, page = inputs.doc(capture_key)
        if cap["url"] != item["id"] or not re.fullmatch(page_pattern, str(item["id"])) or key_text not in copy_key(page.text):
            return False
        transitions = detect_transitions(page)
        if transitions:
            raise _block(transitions[0][0], f"{capture_key}: {transitions[0][1]}")
        # The same reviewed structural extraction must find exactly the verified outlook in the copy: any other,
        # malformed or unsupported outlook statement in a recognised template blocks.
        try:
            again = extract_guidance(page, profile)
        except Blocked as b:
            raise _block("SOURCE_DISAGREEMENT", f"{capture_key}: {b.reason} {b.detail}") from None
        if any(again[k] != guidance[k] for k in ("quarter", "fiscal_year", "point", "low", "high")):
            raise _block("SOURCE_DISAGREEMENT", f"{capture_key} states another revenue outlook")
        if competing_outlooks(page, profile, guidance):
            raise _block("SOURCE_DISAGREEMENT", f"{capture_key} states another revenue outlook")
        return True

    ir_item = event.get("ir_item")
    if not ir_item or "ir_copy" not in captures:
        # The official IR index may list the release later than EDGAR: wait for the issuer's own publication.
        raise Blocked("WAITING", "INCOMPLETE_EVENT_COVERAGE", "official IR publication of this release not captured yet")
    if not same_release(ir_item, "ir_copy", profile["ir_title_pattern"], profile["ir_page_pattern"]):
        raise _block("INCOMPLETE_EVENT_COVERAGE", "the IR publication is not this release")
    consumed.append({"channel": "ISSUER_IR", "id": ir_item["id"], "date": ir_item["date"]})
    wire_item = event.get("wire_item")
    wire_proven = same_release(wire_item, "wire_copy", profile["wire_title_pattern"], profile["wire_page_pattern"])
    if wire_proven:
        consumed.append({"channel": "WIRE_PRESS_RELEASES", "id": wire_item["id"], "date": wire_item["date"]})
    channels = dict(predecessor.get("release_channels") or {})
    channels["ir_guidance_release_title"] = ir_item["title"]
    decisions.append({"kind": "ROUTING", "ref": "routing", "decision": "EVENT_CONSUMED", "capture": "submissions",
                      "operands": {"accession": acc, "form": filing.form, "items": ",".join(filing.items), "filed": filing.filed,
                                   "exhibit": exhibits[0], "package": package, "ir_item": dict(ir_item),
                                   "wire_item": dict(wire_item) if wire_proven else None,
                                   "consumed": sorted(consumed, key=lambda c: (c["channel"], c["id"]))}})
    record = {"symbol": sym, "company_name": company, "status": "GUIDANCE", "reason": None,
              "url_prefixes": [SEC_ARCHIVES], "documents": sorted(documents.values(), key=lambda d: d["id"]),
              "claims": [claim], "reported_quarters": reported, "forward_intervals": intervals, "fy_reconciliation": None,
              "release_channels": channels, "reviewed_later_documents": []}
    try:
        revenue_guidance.validate_issuer_record(record, sym)
    except ValueError as error:
        raise _block("RECORD_INVALID", str(error)) from None
    return {"outcome": "VERIFIED", "reason": None, "detail": "", "record": record,
            "decisions": [dict(d, reviewed_at=verified_at) for d in decisions]}
