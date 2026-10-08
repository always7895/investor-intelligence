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
from urllib.parse import urljoin, urlsplit

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
HTML_UNREADABLE = "HTML marked section or declaration not readable"
PLAIN_HTML = "not an inline XBRL document"
IXBRL_MARKUP = re.compile(rb"inlinexbrl|<(?:[^\s<>/!?:=\"']+:)?non(?:Fraction|Numeric)\b", re.I)
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
# Enumerated, versioned source/event/actuals modes. Only implemented modes are accepted; each fixes its event form,
# evidence roles and actuals reader. NBIS's closed 6-K table mode is source-only,
# inactive/unqualified; CRWV's IR-package/PDF mode remains a later slice.
SEC_8K_202_INLINE_XBRL_V1 = "SEC_8K_202_INLINE_XBRL_V1"
NBIS_6K_TABLE_REAFFIRMATION_V1 = "NBIS_6K_TABLE_REAFFIRMATION_V1"
ADAPTERS = (SEC_8K_202_INLINE_XBRL_V1, NBIS_6K_TABLE_REAFFIRMATION_V1)
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
    except (ValueError, LookupError) as error:
        if isinstance(error, (KeyError, IndexError)):
            raise
        raise _block("INPUT_MALFORMED", type(error).__name__) from None
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


def _feed_html(parser, canonical: bytes) -> None:
    try:
        text = canonical.decode("utf-8")
    except UnicodeDecodeError as error:
        raise _block("CANONICALIZATION_FAILED", f"not UTF-8 at byte {error.start}") from error
    try:
        parser.feed(text)
        parser.close()
    except AssertionError:
        raise _block("UNSUPPORTED_TEMPLATE", HTML_UNREADABLE) from None
    except (ValueError, IndexError) as error:
        raise _block("INPUT_MALFORMED", type(error).__name__) from None


def parse_document(raw: bytes) -> Document:
    if len(raw) > MAX_DOCUMENT_BYTES:
        raise _block("CAPTURE_LIMIT", "document over 16 MiB")
    canonical = canonical_bytes(raw)
    parser = _Parser()
    _feed_html(parser, canonical)
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
        doc = Document(text=text, blocks=offsets, tables=tables, unsupported=[PLAIN_HTML])
    doc.canonical_sha256 = sha256(text.encode("utf-8"))
    return doc


# ----------------------------------------------------------------------------------------------------------------
# Profiles (reviewed policy; strict keys; regexes are reviewed configuration, never taken from documents)
# ----------------------------------------------------------------------------------------------------------------

PROFILE_KEYS = {"symbol", "profile_id", "revision", "adapter", "company_name", "cik", "currency", "accounting_basis", "scope",
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
        if prof["adapter"] not in ADAPTERS:
            raise ValueError(f"PROFILE_ADAPTER {sym}: {str(prof['adapter'])[:40]}")
        rel, gui, act, cal = prof["release"], prof["guidance"], prof["actuals"], prof["calendar"]
        if prof["adapter"] == NBIS_6K_TABLE_REAFFIRMATION_V1:
            validate_nbis_profile(prof)
            by_symbol[sym] = prof
            continue  # distinct CLOSED dialect, never the union of A1/NBIS nested keys
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


def a1_report_period(guidance: Mapping[str, Any], profile: Mapping[str, Any]) -> dict[str, Any]:
    """SEC_8K_202_INLINE_XBRL_V1: the quarter a release reports is the one before its single quarterly outlook (the
    verifier then proves it from the release's own summary table and the quarter's periodic filing). Other adapters
    will prove the report period from their own statements."""
    quarter, fiscal_year = next_quarter(guidance["quarter"], guidance["fiscal_year"], -1)
    try:
        start, end = fiscal_quarter(profile["calendar"]["rule"], fiscal_year, quarter)
    except ValueError as error:
        raise _block("CALENDAR_RULE_UNPROVEN", str(error)) from None
    return {"quarter": quarter, "fiscal_year": fiscal_year, "start": start, "end": end}


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


def parse_submissions(raw: bytes, cik: int, *, foreign_items_absence: bool = False) -> dict[str, Filing]:
    try:
        data = json.loads(raw.decode("utf-8"))
        if int(data["cik"]) != cik:
            raise _block("APPROVAL_BINDING", "submissions of another issuer")
        recent = data["filings"]["recent"]
        columns = [recent[k] for k in ("accessionNumber", "form", "filingDate", "reportDate", "primaryDocument")]
        # Only the foreign 6-K adapter may represent an actually absent items
        # column as no items. Never manufacture 2.02 or change A1's strict feed.
        columns.append([""] * len(columns[0]) if foreign_items_absence and "items" not in recent else recent["items"])
    except (UnicodeDecodeError, ValueError, KeyError, TypeError, RecursionError, OverflowError):
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
    except (UnicodeDecodeError, ValueError, KeyError, TypeError, RecursionError, OverflowError):
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
    documents) is re-established from the captured submissions feed and accession index. The distinct NBIS mode
    instead accepts only NBIS_EVENT_KEYS, package/member aliases and original channel_history; it never mixes A1
    fields into that dialect. `captures`: key ->
    {"url", "retrieved_at", "bytes", "raw_sha256", "sha256" (watermark-zeroed bytes), "raw": bytes, ...} with the fixed
    keys "submissions", "index", "exhibit", "package:<name>", "ir_copy", "wire_copy"; bytes are re-hashed and re-parsed
    here, nothing is trusted from a stored digest or outcome. Malformed input is a typed BLOCKED outcome."""
    try:
        if profile.get("adapter") not in BUILDERS:
            raise _block("UNSUPPORTED_TEMPLATE", f"adapter {str(profile.get('adapter'))[:40]}")
        return BUILDERS[profile["adapter"]](profile, predecessor, event, captures, verified_at)
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
    report = a1_report_period(guidance, profile)
    aq, afy, a_start, a_end = report["quarter"], report["fiscal_year"], report["start"], report["end"]
    rule = cal["rule"]
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
    record = {"symbol": sym, "company_name": company, "status": "GUIDANCE", "reason": None,
              "url_prefixes": [SEC_ARCHIVES], "documents": sorted(documents.values(), key=lambda d: d["id"]),
              "claims": [claim], "reported_quarters": reported, "forward_intervals": intervals, "fy_reconciliation": None,
              "release_channels": channels, "reviewed_later_documents": []}
    try:
        revenue_guidance.validate_issuer_record(record, sym)
    except ValueError as error:
        raise _block("RECORD_INVALID", str(error)) from None
    # The whole active claim set must share one release-check reference: this results release.
    reference = revenue_guidance.guidance_reference(record)
    if reference["conflict"] or reference["document_id"] != rel_id:
        raise _block("RECORD_INVALID", "the successor's active claims do not share this release as their reference")
    decisions.append({"kind": "ROUTING", "ref": "routing", "decision": "EVENT_CONSUMED", "capture": "submissions",
                      "operands": {"adapter": profile["adapter"], "accession": acc, "form": filing.form, "items": ",".join(filing.items),
                                   "filed": filing.filed, "exhibit": exhibits[0], "package": package, "ir_item": dict(ir_item),
                                   "wire_item": dict(wire_item) if wire_proven else None,
                                   "consumed": sorted(consumed, key=lambda c: (c["channel"], c["id"])),
                                   "report_period": {"quarter": aq, "fiscal_year": afy, "start": a_start.isoformat(), "end": a_end.isoformat()},
                                   "reference": {"document_id": reference["document_id"], "claims": reference["claims"]}}})
    return {"outcome": "VERIFIED", "reason": None, "detail": "", "record": record,
            "decisions": [dict(d, reviewed_at=verified_at) for d in decisions]}


# NBIS is a separate source dialect. No fallback from the tagged A1 reader.
NBIS_EVENT_KEYS = {"adapter", "accession", "filed", "packages", "channel_history", "ir_item", "wire_item", "later_documents"}
NBIS_PACKAGE_KEYS = {"accession", "filed", "index", "form", "statement", "letter", "members"}
NBIS_STATEMENT_HEADING = "Unaudited Condensed Consolidated Statements of Operations"
NBIS_SCOPE_RULE = "EXPLICIT_GROUP_GAAP"
NBIS_GRID_LIMITS = {"nodes": 200000, "tables": 256, "rows": 512, "columns": 64, "span": 32,
                    "cells": 32768, "expanded_slots": 32768, "work": 64 * 1024 * 1024,
                    "text": MAX_CANONICAL_TEXT, "cell_text": 8192, "depth": 8, "attributes": 64}
NBIS_MONTHS = {"March": (3, 31), "June": (6, 30), "September": (9, 30), "December": (12, 31)}
NBIS_FACT_KEYS = {"capture", "document_id", "raw_sha256", "source_sha256", "locator", "headers", "shown",
                  "start", "end", "value", "currency", "unit_multiplier", "scope", "accounting_basis", "precision"}


def validate_nbis_profile(p):
    """Validate inactive profiles too; values are policy, not a source attestation."""
    if (p["symbol"] != "NBIS" or p["cik"] != 1513845 or p["company_name"] != "Nebius Group N.V."
            or p["profile_id"] != "NBIS-SEC-6K-TABLE-REAFFIRMATION" or type(p["revision"]) is not int or p["revision"] < 1):
        raise ValueError("NBIS_PROFILE_IDENTITY")
    r, g, a, c = (p[k] for k in ("release", "guidance", "actuals", "calendar"))
    if (not isinstance(r, dict) or set(r) != {"form", "statement_name_pattern", "letter_name_pattern"}
            or r["form"] != "6-K"):
        raise ValueError("NBIS_RELEASE_KEYS")
    for k in ("statement_name_pattern", "letter_name_pattern"):
        _regex(r[k], "NBIS.release." + k)
    if (not isinstance(g, dict) or set(g) != {"kind", "scope_rule"} or g["kind"] != "FY_RANGE_ALL_METRICS_REAFFIRMATION"
            or g["scope_rule"] != NBIS_SCOPE_RULE):
        raise ValueError("NBIS_GUIDANCE_KEYS")
    if (not isinstance(a, dict) or set(a) != {"mode", "heading", "row", "unit", "precision", "rounding"}
            or a != {"mode": "NBIS_CONSOLIDATED_TABLE_V1", "heading": NBIS_STATEMENT_HEADING, "row": "Revenues",
                     "unit": "USD_MILLIONS", "precision": "0.1", "rounding": "HALF_UP_HALF_OPEN"}):
        raise ValueError("NBIS_ACTUALS_KEYS")
    if not isinstance(c, dict) or c != {"rule": "CALENDAR_YEAR_TABLE_V1", "label_format": "Q{q} FY{yy}"}:
        raise ValueError("NBIS_CALENDAR_KEYS")
    for k in ("ir_title_pattern", "wire_title_pattern", "ir_page_pattern", "wire_page_pattern"):
        _regex(p[k], "NBIS." + k)
    host = p["ir_host"]
    if (not isinstance(host, str) or not re.fullmatch(r"[a-z0-9-]{1,40}(?:\.[a-z0-9-]{1,40}){1,4}", host)
            or host.endswith("sec.gov") or not p["ir_page_pattern"].startswith("^https://" + re.escape(host) + "/")
            or not p["wire_page_pattern"].startswith(r"^https://www\.nasdaq\.com/press-release/")
            or not all(p[k].endswith("$") for k in ("ir_page_pattern", "wire_page_pattern"))):
        raise ValueError("NBIS_PAGE_POLICY")


def _nbis_work(budget, amount):
    if type(amount) is not int or amount < 0 or budget["work"] + amount > NBIS_GRID_LIMITS["work"]:
        raise _block("CAPTURE_LIMIT", "NBIS total structural/header/text work")
    budget["work"] += amount


class _NbisGrid(HTMLParser):
    """Finite structural grid; preserve cell/span/header identity, not flattened numeric positions.

    This preflight runs BEFORE the existing canonical document reader. Spans occupy
    explicit grid slots, overlaps/unfinished cells and unsupported layouts refuse.
    No browser, image/OCR, XML fallback or document-wide monetary number search.
    """
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.nodes = self.total_text = self.cells = self.depth = self.hidden = self.expanded_slots = 0
        self.budget = {"work": 0}
        self.stack, self.tables, self.context = [], [], ""

    def handle_starttag(self, tag, attrs):
        self.nodes += 1
        _nbis_work(self.budget, 1 + len(attrs))
        if self.nodes > NBIS_GRID_LIMITS["nodes"] or len(attrs) > NBIS_GRID_LIMITS["attributes"]:
            raise _block("CAPTURE_LIMIT", "NBIS HTML nodes/attributes")
        if tag in HIDDEN_TAGS:
            self.hidden += 1
        if self.hidden:
            return
        if tag == "table":
            self.depth += 1
            if self.depth > NBIS_GRID_LIMITS["depth"] or len(self.tables) + len(self.stack) >= NBIS_GRID_LIMITS["tables"]:
                raise _block("CAPTURE_LIMIT", "NBIS table nesting/count")
            self.stack.append({"prefix": self.context[-4096:], "grid": {}, "row": -1, "col": 0,
                               "cell": None, "width": 0, "row_open": False, "budget": self.budget})
        elif self.stack and tag == "tr":
            t = self.stack[-1]
            if t["cell"] is not None or t["row_open"]:
                raise _block("UNSUPPORTED_TEMPLATE", "unfinished NBIS cell")
            t["row"] += 1
            t["row_open"] = True
            t["col"] = 0
            if t["row"] >= NBIS_GRID_LIMITS["rows"]:
                raise _block("CAPTURE_LIMIT", "NBIS table rows")
        elif self.stack and tag in ("td", "th"):
            t = self.stack[-1]
            if t["cell"] is not None or t["row"] < 0 or not t["row_open"]:
                raise _block("UNSUPPORTED_TEMPLATE", "NBIS cell outside/inside cell")
            self.cells += 1
            if self.cells > NBIS_GRID_LIMITS["cells"]:
                raise _block("CAPTURE_LIMIT", "NBIS cells")
            relevant = [k for k, _ in attrs if k in ("rowspan", "colspan")]
            if len(relevant) != len(set(relevant)):
                raise _block("UNSUPPORTED_TEMPLATE", "duplicate NBIS span attribute")
            attributes = dict(attrs)
            spans = []
            for k in ("rowspan", "colspan"):
                v = attributes.get(k, "1")
                if not isinstance(v, str) or not re.fullmatch(r"[1-9][0-9]?", v) or int(v) > NBIS_GRID_LIMITS["span"]:
                    raise _block("UNSUPPORTED_TEMPLATE", "unsupported NBIS span")
                spans.append(int(v))
            while (t["row"], t["col"]) in t["grid"]:
                _nbis_work(self.budget, 1)
                t["col"] += 1
            rs, cs = spans
            if t["col"] + cs > NBIS_GRID_LIMITS["columns"] or t["row"] + rs > NBIS_GRID_LIMITS["rows"]:
                raise _block("CAPTURE_LIMIT", "NBIS grid dimensions")
            # Reserve TOTAL expanded slots before any cell/span materialization.
            # A 32x32 authored cell costs 1024 slots, not one authored-cell token.
            slots = rs * cs
            if self.expanded_slots + slots > NBIS_GRID_LIMITS["expanded_slots"]:
                raise _block("CAPTURE_LIMIT", "NBIS total expanded grid")
            _nbis_work(self.budget, slots)
            for r in range(t["row"], t["row"] + rs):
                for c in range(t["col"], t["col"] + cs):
                    if (r, c) in t["grid"]:
                        raise _block("UNSUPPORTED_TEMPLATE", "overlapping NBIS spans")
            self.expanded_slots += slots
            t["cell"] = {"row": t["row"], "col": t["col"], "rowspan": rs, "colspan": cs,
                         "text": "", "header": tag == "th", "tag": tag}

    def handle_data(self, data):
        if self.hidden:
            return
        self.total_text += len(data)
        if self.total_text > NBIS_GRID_LIMITS["text"]:
            raise _block("CAPTURE_LIMIT", "NBIS source text")
        _nbis_work(self.budget, len(self.context) + len(data))
        self.context = (self.context + data)[-4096:]
        # A nested layout table must not silently drop an adverse parent-cell
        # passage; charge every retained representation before concatenation.
        for t in self.stack:
            cell = t["cell"]
            if cell is not None:
                if len(cell["text"]) + len(data) > NBIS_GRID_LIMITS["cell_text"]:
                    raise _block("CAPTURE_LIMIT", "NBIS cell text")
                _nbis_work(self.budget, len(cell["text"]) + len(data))
                cell["text"] += data

    def handle_endtag(self, tag):
        self.nodes += 1
        _nbis_work(self.budget, 1)
        if self.nodes > NBIS_GRID_LIMITS["nodes"]:
            raise _block("CAPTURE_LIMIT", "NBIS total HTML nodes")
        if tag in HIDDEN_TAGS and self.hidden:
            self.hidden -= 1
            return
        if self.hidden or not self.stack:
            return
        t = self.stack[-1]
        if tag in ("td", "th"):
            cell = t["cell"]
            if cell is None or cell["tag"] != tag:
                raise _block("UNSUPPORTED_TEMPLATE", "unmatched NBIS cell close")
            _nbis_work(self.budget, len(cell["text"]) + cell["rowspan"] * cell["colspan"])
            cell["text"] = SPACE.sub(" ", cell["text"]).strip()
            for r in range(cell["row"], cell["row"] + cell["rowspan"]):
                for c in range(cell["col"], cell["col"] + cell["colspan"]):
                    if (r, c) in t["grid"]:
                        raise _block("UNSUPPORTED_TEMPLATE", "overlapping NBIS spans")
                    t["grid"][r, c] = cell
            t["col"] = cell["col"] + cell["colspan"]
            t["width"] = max(t["width"], t["col"])
            t["cell"] = None
        elif tag == "tr":
            if t["cell"] is not None or not t["row_open"]:
                raise _block("UNSUPPORTED_TEMPLATE", "unmatched NBIS row close")
            t["row_open"] = False
        elif tag == "table":
            _nbis_work(self.budget, len(t["grid"]))
            if t["cell"] is not None or t["row_open"] or any(r > t["row"] for r, _ in t["grid"]):
                raise _block("UNSUPPORTED_TEMPLATE", "unfinished NBIS table/span")
            self.tables.append(self.stack.pop())
            self.depth -= 1


def nbis_document(raw):
    if type(raw) is not bytes or len(raw) > MAX_DOCUMENT_BYTES:
        raise _block("CAPTURE_LIMIT", "NBIS document bytes")
    grid = _NbisGrid()
    _feed_html(grid, canonical_bytes(raw))
    if grid.stack or grid.hidden:
        raise _block("UNSUPPORTED_TEMPLATE", "unclosed NBIS document")
    return parse_document(raw), grid.tables


def nbis_quarter(year, quarter):
    if type(year) is not int or type(quarter) is not int or not 1 <= quarter <= 4:
        raise _block("PERIOD_MISMATCH", "NBIS quarter")
    start = date(year, 3 * quarter - 2, 1)
    end = date(year + (quarter == 4), (3 * quarter) % 12 + 1, 1) - timedelta(days=1)
    return start, end


def nbis_statement(raw, filed):
    """Return exact table operands. Report anchor comes from statement headers, not guidance."""
    doc, tables = nbis_document(raw)
    # Documentary basis is mandatory, not a profile/symbol inference.
    if not re.search(r"(?:U\.S\. GAAP|accounting principles generally accepted in the United States)", doc.text, re.I):
        raise _block("UNSUPPORTED_TEMPLATE", "NBIS GAAP basis not evidenced")
    found = []
    for ti, t in enumerate(tables):
        _nbis_work(t["budget"], len(t["prefix"]) + len(t["grid"]))
        prefix = SPACE.sub(" ", t["prefix"]).strip()
        own = list({id(v): v for v in t["grid"].values()}.values())
        text_size = len(prefix) + sum(len(v["text"]) + 1 for v in own)
        _nbis_work(t["budget"], text_size)
        if text_size > NBIS_GRID_LIMITS["text"]:
            raise _block("CAPTURE_LIMIT", "NBIS table text materialization")
        text = prefix + " " + " ".join(v["text"] for v in own)
        if NBIS_STATEMENT_HEADING.casefold() not in text.casefold():
            continue
        units = re.findall(r"\bin millions of U\.S\. dollars(?:, except share and per share data)?\b", text, re.I)
        rows = {v["row"] for v in own if v["text"] == "Revenues"}
        if len(rows) != 1 or not units:
            continue
        rr = next(iter(rows))
        values = []
        for cell in own:
            if cell["row"] != rr or not re.fullmatch(r"[0-9]{1,12}(?:,[0-9]{3})*\.[0-9]", cell["text"]):
                continue
            headers = []
            _nbis_work(t["budget"], rr)
            header_size = 0
            for r in range(rr):
                h = t["grid"].get((r, cell["col"]))
                if h is not None and h["text"]:
                    _nbis_work(t["budget"], len(h["text"]) + header_size)
                    if h["text"] not in headers:
                        header_size += len(h["text"]) + 1
                        if header_size > NBIS_GRID_LIMITS["cell_text"]:
                            raise _block("CAPTURE_LIMIT", "NBIS header text")
                        headers.append(h["text"])
            _nbis_work(t["budget"], header_size)
            joined = " ".join(headers)
            duration = list(re.finditer(r"\b(Three|Six|Nine|Twelve) months ended (March|June|September|December) ([0-9]{1,2})\b", joined, re.I))
            years = [h for h in headers if re.fullmatch(r"20[0-9]{2}", h)]
            if len(duration) != 1 or len(years) != 1 or re.search(r"\bChange\b|%", joined, re.I):
                raise _block("UNSUPPORTED_TEMPLATE", "NBIS duration/year/header hierarchy")
            m = duration[0]
            month, dom = NBIS_MONTHS[m.group(2).title()]
            if int(m.group(3)) != dom:
                raise _block("PERIOD_MISMATCH", "NBIS non-calendar header")
            end = date(int(years[0]), month, dom)
            months = {"three": 3, "six": 6, "nine": 9, "twelve": 12}[m.group(1).lower()]
            if months > month or (months != 3 and months != month):
                raise _block("PERIOD_MISMATCH", "NBIS duration is not evidenced quarter/YTD")
            start = date(end.year, month - months + 1, 1)
            value = Decimal(cell["text"].replace(",", "")) * MULT["million"]
            if not value.is_finite() or value <= 0 or end.isoformat() >= filed:
                raise _block("SOURCE_DISAGREEMENT", "NBIS value/period/publication")
            values.append({"start": start.isoformat(), "end": end.isoformat(), "value": str(value), "shown": cell["text"],
                           "headers": headers, "locator": f"grid[{ti}].r[{rr}].c[{cell['col']}]", "currency": "USD",
                           "unit_multiplier": 1000000, "scope": "COMPANY", "accounting_basis": "GAAP", "precision": "0.1"})
        if values:
            found.append(values)
    if len(found) != 1:
        raise _block("AMBIGUOUS" if found else "RELEASE_ROW_NOT_FOUND", "NBIS unique consolidated statement")
    operands = found[0]
    identities = [(v["start"], v["end"]) for v in operands]
    if len(set(identities)) != len(identities):
        raise _block("AMBIGUOUS", "NBIS duplicate period cells")
    quarters = [v for v in operands if (date.fromisoformat(v["end"]).month - date.fromisoformat(v["start"]).month) == 2]
    if not quarters:
        raise _block("PERIOD_MISMATCH", "NBIS report quarter missing")
    anchor = max(v["end"] for v in quarters)
    current = [v for v in operands if v["end"][:4] == anchor[:4]]
    return doc, current, anchor


NBIS_FY_RANGE = (r"On track to achieve \$(?P<low>[0-9]{1,6}(?:\.[0-9]{1,6})?)B–"
                 r"\$(?P<high>[0-9]{1,6}(?:\.[0-9]{1,6})?)B revenue in (?P<year>20[0-9]{2}) "
                 r"and \$[0-9]{1,6}(?:\.[0-9]{1,6})?B–\$[0-9]{1,6}(?:\.[0-9]{1,6})?B ARR")
NBIS_SCOPE_SENTENCE = (r"Nebius Group(?: N\.V\.)?(?:'s)? consolidated revenue guidance (?:is|has been) "
                       r"(?:prepared|presented) (?:in accordance with|on the basis of) U\.S\. GAAP\.")
NBIS_POSITIVE_BLOCK = "NBIS_POSITIVE_FY_BLOCK_V2"
NBIS_LETTER_ACTUAL = (r"Consolidated revenues? for the (first|second|third|fourth) quarter (?:of )?(20[0-9]{2}) "
                      r"(?:was|were) \$([0-9]{1,12}\.[0-9]) million\.?")


def nbis_positive_guidance_block(quote):
    """Closed FULL positive block, not range/scope substring membership.

    Exactly the range and its positive GAAP proposition (either order), optionally
    preceded by the matching FY heading. No unaccounted governing words,
    quotation, denial, hypothetical/history, qualifier or mixed actual sentence.
    Unsupported layouts refuse; this never creates missing documentary proof.
    """
    if not isinstance(quote, str) or not 0 < len(quote) <= MAX_PASSAGE:
        return None
    heading = r"(?:(?P<heading>20[0-9]{2} Guidance update) )?"
    for body in (r"(?P<range>" + NBIS_FY_RANGE + r")\.? (?P<scope>" + NBIS_SCOPE_SENTENCE + r")",
                 r"(?P<scope>" + NBIS_SCOPE_SENTENCE + r") (?P<range>" + NBIS_FY_RANGE + r")\.?"):
        m = re.fullmatch(heading + body, quote)
        if m is None:
            continue
        year = int(m.group("year"))
        if m.group("heading") is not None and m.group("heading") != f"{year} Guidance update":
            raise _block("PERIOD_MISMATCH", "NBIS closed guidance block heading/FY")
        low, high = Decimal(m.group("low")) * MULT["billion"], Decimal(m.group("high")) * MULT["billion"]
        if not 0 < low <= high:
            raise _block("UNIT_MISMATCH", "NBIS closed FY endpoints")
        return {"year": year, "low": low, "high": high, "range_span": list(m.span("range")),
                "scope_span": list(m.span("scope")), "heading_span": list(m.span("heading")) if m.group("heading") else None}
    return None


def nbis_guidance_proof(sc):
    """Recompute exact complete-block coverage and absolute source spans."""
    fields = {"offsets", "quote", "scope_offsets", "range_offsets", "heading", "rule", "grammar"}
    if not isinstance(sc, dict) or set(sc) != fields or sc["rule"] != NBIS_SCOPE_RULE or sc["grammar"] != NBIS_POSITIVE_BLOCK:
        raise _block("INPUT_MALFORMED", "NBIS positive guidance proof shape")
    value = nbis_positive_guidance_block(sc["quote"])
    if value is None or not isinstance(sc["offsets"], list) or len(sc["offsets"]) != 2 or any(type(n) is not int or n < 0 for n in sc["offsets"]):
        raise _block("UNSUPPORTED_TEMPLATE", "NBIS unsupported governing guidance context")
    start, end = sc["offsets"]
    if end - start != len(sc["quote"]) or end > MAX_CANONICAL_TEXT:
        raise _block("INPUT_MALFORMED", "NBIS whole guidance block span")
    for name in ("range", "scope"):
        offsets = sc[name + "_offsets"]
        if not isinstance(offsets, list) or len(offsets) != 2 or any(type(n) is not int or not 0 <= n <= MAX_CANONICAL_TEXT for n in offsets):
            raise _block("INPUT_MALFORMED", "NBIS typed positive sentence spans")
        if offsets != [start + n for n in value[name + "_span"]]:
            raise _block("APPROVAL_BINDING", "NBIS positive sentence source spans")
    h = sc["heading"]
    if not isinstance(h, dict) or set(h) != {"offsets", "quote"} or h["quote"] != f"{value['year']} Guidance update":
        raise _block("INPUT_MALFORMED", "NBIS full positive heading")
    expected = [start + n for n in value["heading_span"]] if value["heading_span"] else [start - len(h["quote"]) - 1, start - 1]
    if (not isinstance(h["offsets"], list) or len(h["offsets"]) != 2 or any(type(n) is not int for n in h["offsets"])
            or h["offsets"] != expected or expected[0] < 0):
        raise _block("APPROVAL_BINDING", "NBIS full heading/block adjacency")
    return value


def nbis_letter_actual(quote):
    m = re.fullmatch(NBIS_LETTER_ACTUAL, quote, re.I) if isinstance(quote, str) and len(quote) <= MAX_PASSAGE else None
    if m is None:
        raise _block("UNSUPPORTED_TEMPLATE", "NBIS complete positive quarter-actual sentence")
    start, end = nbis_quarter(int(m.group(2)), ORDINALS[m.group(1).lower()])
    return start.isoformat(), end.isoformat(), Decimal(m.group(3)) * MULT["million"]


def nbis_original_guidance(doc):
    headings = list(re.finditer(r"\b(20[0-9]{2}) Guidance update\b", doc.text))
    matches = list(re.finditer(NBIS_FY_RANGE, doc.text))  # locate only, NEVER admission by substring
    if len(headings) != 1 or len(matches) != 1:
        raise _block("AMBIGUOUS" if matches else "NO_MATCH", "NBIS unique full FY revenue/ARR clause")
    h, m = headings[0], matches[0]
    blocks = [(i, s, e) for i, (s, e) in enumerate(doc.blocks) if s <= m.start() and m.end() <= e and e - s <= MAX_PASSAGE]
    if len(blocks) != 1:
        raise _block("UNSUPPORTED_TEMPLATE", "NBIS complete guidance block missing")
    i, s, e = blocks[0]
    value = nbis_positive_guidance_block(doc.text[s:e])
    if value is None:
        raise _block("UNSUPPORTED_TEMPLATE", "NBIS unaccounted/negated/quoted governing guidance context")
    if value["heading_span"] is None and (i == 0 or doc.blocks[i - 1] != (h.start(), h.end())):
        raise _block("UNSUPPORTED_TEMPLATE", "NBIS complete adjacent positive heading block")
    sc = {"offsets": [s, e], "quote": doc.text[s:e], "scope_offsets": [s + n for n in value["scope_span"]],
          "range_offsets": [s + n for n in value["range_span"]], "heading": {"offsets": [h.start(), h.end()], "quote": h.group(0)},
          "rule": NBIS_SCOPE_RULE, "grammar": NBIS_POSITIVE_BLOCK}
    nbis_guidance_proof(sc)
    if re.search(r"\$[0-9][^.;]{0,100}\brevenue\b", doc.text[:m.start()] + doc.text[m.end():], re.I):
        raise _block("AMBIGUOUS", "NBIS additional competing revenue-guidance clause")
    return {"year": value["year"], "low": value["low"], "high": value["high"], "offsets": sc["range_offsets"],
            "passage": doc.text[sc["range_offsets"][0]:sc["range_offsets"][1]], "scope_context": sc}


def nbis_reaffirmation(doc, year):
    matches = list(re.finditer(r"We are reaffirming our full-year (20[0-9]{2}) guidance across all metrics\.", doc.text))
    if (len(matches) != 1 or int(matches[0].group(1)) != year or "Dear shareholders" not in doc.text
            or "Financial model proving itself as we scale" not in doc.text):
        raise _block("UNSUPPORTED_TEMPLATE", "NBIS explicit all-metrics same-FY reaffirmation")
    if re.search(r"\b(?:not|no longer|except|excluding)\b[^.;]{0,120}\b(?:reaffirm|revenue|all metrics)\b", doc.text, re.I):
        raise _block("SOURCE_DISAGREEMENT", "NBIS negated/excepted reaffirmation")
    if re.search(r"\$[0-9][^.;]{0,160}\b(?:revenue|guidance|outlook)\b|\b(?:revenue|guidance|outlook)\b[^.;]{0,160}\$[0-9]", doc.text, re.I):
        raise _block("UNSUPPORTED_TEMPLATE", "NBIS competing numeric outlook in all-metrics letter")
    return {"year": year, "offsets": [matches[0].start(), matches[0].end()], "passage": matches[0].group(0)}


def nbis_bind_operand(value, capture_key, cap, document_id):
    """Exact documentary operand, including BOTH byte identities and its own interval."""
    expected = NBIS_FACT_KEYS - {"capture", "document_id", "raw_sha256", "source_sha256"}
    if not isinstance(value, dict) or set(value) != expected:
        raise _block("INPUT_MALFORMED", "NBIS operand keys")
    start, end = revenue_guidance.parse_day(value["start"]), revenue_guidance.parse_day(value["end"])
    if not start or not end or start > end or not isinstance(value["value"], str):
        raise _block("PERIOD_MISMATCH", "NBIS operand interval/value type")
    amount = Decimal(value["value"])
    if (not amount.is_finite() or amount <= 0 or amount > 9007199254690991 or amount != amount.to_integral_value()
            or value["currency"] != "USD"
            or type(value["unit_multiplier"]) is not int or value["unit_multiplier"] != 1000000
            or value["scope"] != "COMPANY" or value["accounting_basis"] != "GAAP" or value["precision"] != "0.1"
            or not isinstance(value["shown"], str)
            or not re.fullmatch(r"[0-9]{1,12}(?:,[0-9]{3})*\.[0-9]", value["shown"])
            or Decimal(value["shown"].replace(",", "")) * MULT["million"] != amount):
        raise _block("SOURCE_DISAGREEMENT", "NBIS operand measure/disclosed precision")
    if (not isinstance(value["headers"], list) or not 1 <= len(value["headers"]) <= NBIS_GRID_LIMITS["rows"]
            or any(not isinstance(h, str) or len(h) > NBIS_GRID_LIMITS["cell_text"] for h in value["headers"])
            or not isinstance(value["locator"], str)
            or not re.fullmatch(r"grid\[[0-9]{1,3}\]\.r\[[0-9]{1,3}\]\.c\[[0-9]{1,2}\]", value["locator"])):
        raise _block("UNSUPPORTED_TEMPLATE", "NBIS operand locator/header")
    return dict(value, capture=capture_key, document_id=document_id, raw_sha256=cap["raw_sha256"], source_sha256=cap["sha256"])


def nbis_difference(longer, shorter, direct, operation):
    """The two interval algebra shapes are DISTINCT; no generic fiscal-date fudge."""
    for operand in (longer, shorter, direct):
        if not isinstance(operand, dict) or set(operand) != NBIS_FACT_KEYS:
            raise _block("INPUT_MALFORMED", "NBIS bound derivation operand")
    for field in ("currency", "unit_multiplier", "scope", "accounting_basis", "precision"):
        if len({operand[field] for operand in (longer, shorter, direct)}) != 1:
            raise _block("SOURCE_DISAGREEMENT", "NBIS derivation basis/measure")
    ls, le = (date.fromisoformat(longer[k]) for k in ("start", "end"))
    ss, se = (date.fromisoformat(shorter[k]) for k in ("start", "end"))
    ds, de = (date.fromisoformat(direct[k]) for k in ("start", "end"))
    if operation == "SIX_MONTHS_MINUS_FINAL_QUARTER":
        if not (ls.month == 1 and ls.day == 1 and le.month == 6 and le.day == 30
                and ss == date(ls.year, 4, 1) and se == le and ls.year == le.year
                and ds == ls and de == ss - timedelta(days=1)):
            raise _block("PERIOD_MISMATCH", "NBIS 6M-minus-final-Q intervals")
    elif operation == "FULL_YEAR_MINUS_INITIAL_NINE_MONTHS":
        if not (ls.month == 1 and ls.day == 1 and le == date(ls.year, 12, 31)
                and ss == ls and se == date(ls.year, 9, 30)
                and ds == se + timedelta(days=1) and de == le):
            raise _block("PERIOD_MISMATCH", "NBIS FY-minus-initial-9M intervals")
    else:
        raise _block("UNSUPPORTED_TEMPLATE", "NBIS subtraction operation")
    amounts = [Decimal(o["value"]) for o in (longer, shorter, direct)]
    if any(not n.is_finite() or n <= 0 for n in amounts):
        raise _block("SOURCE_DISAGREEMENT", "NBIS nonpositive/nonfinite operands")
    result = amounts[0] - amounts[1]
    if result <= 0 or result != amounts[2]:
        raise _block("SOURCE_DISAGREEMENT", "NBIS exact direct/difference reconciliation")
    return {"operation": operation, "longer": dict(longer), "shorter": dict(shorter), "direct": dict(direct),
            "output": {"start": direct["start"], "end": direct["end"], "value": str(result), "currency": "USD",
                       "unit_multiplier": 1000000, "scope": "COMPANY", "accounting_basis": "GAAP", "precision": "0.1"}}


def nbis_tagged_reconciliation(doc, operand, cik, has_ixbrl_markup: bool):
    """Comparable facts only; absence is permitted in THIS foreign table dialect.

    When a comparable US-GAAP concept/period exists, use the original namespace,
    entity, context, unit and equivalent-concept checks. Disclosed half-up 0.1M
    corresponds to [display-0.05M, display+0.05M), never a percentage tolerance.
    """
    concepts = ("us-gaap:Revenues", "us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax")
    if doc.unsupported == [PLAIN_HTML] and not has_ixbrl_markup:
        return {"present": False, "policy": "FOREIGN_TABLE_TAGGED_ABSENCE_V1"}
    doc.check_xbrl_structure()
    comparable = []
    for fact in doc.facts:
        local = fact.concept.partition(":")[2] if ":" in fact.concept else fact.concept
        if local not in {c.split(":")[1] for c in concepts}:
            continue
        uri, name = Document.expanded(fact.concept, fact.ns)
        if not NAMESPACES["us-gaap"].fullmatch(uri):
            if uri.startswith("http://fasb.org/us-gaap/") or name == "Revenues":
                raise _block("UNSUPPORTED_TEMPLATE", "NBIS revenue fact namespace conflict")
            continue
        context = doc.contexts.get(fact.context)
        if context is None or not context.valid:
            raise _block("UNSUPPORTED_TEMPLATE", "NBIS comparable fact context")
        if context.start != operand["start"] or context.end != operand["end"]:
            continue
        if context.has_segment or context.cik is None or not context.cik.isdigit() or int(context.cik) != cik:
            raise _block("SOURCE_DISAGREEMENT", "NBIS comparable tagged entity/company scope")
        unit = doc.units.get(fact.unit_id)
        if unit is None:
            raise _block("UNIT_MISMATCH", "NBIS comparable tagged unit")
        measure_uri, measure = Document.expanded(unit[0], unit[1])
        if measure != "USD" or not NAMESPACES["iso4217"].fullmatch(measure_uri):
            raise _block("UNIT_MISMATCH", "NBIS comparable tagged currency")
        proof = {"concept": fact.concept, "namespace": uri, "context": fact.context, "entity": context.cik,
                 "unit": fact.unit_id, "measure": unit[0], "measure_namespace": measure_uri,
                 "start": context.start, "end": context.end, "scope": "COMPANY", "accounting_basis": "GAAP",
                 "value": format(fact.value(), "f")}
        if proof not in comparable:
            if len(comparable) >= 64:
                raise _block("CAPTURE_LIMIT", "NBIS comparable source fact proof domain")
            comparable.append(proof)
    if not comparable:
        return {"present": False, "policy": "FOREIGN_TABLE_TAGGED_ABSENCE_V1"}
    _, number = xbrl_duration(doc, concepts, "iso4217:USD", cik,
                             date.fromisoformat(operand["start"]), date.fromisoformat(operand["end"]))
    shown = Decimal(operand["value"])
    half = Decimal("0.05") * MULT["million"]
    if not number.is_finite() or not shown - half <= number < shown + half:
        raise _block("SOURCE_DISAGREEMENT", "NBIS half-up disclosed-precision interval")
    return {"present": True, "policy": "HALF_UP_HALF_OPEN", "value": format(number, "f"), "facts": comparable,
            "lower_inclusive": format(shown - half, "f"), "upper_exclusive": format(shown + half, "f")}


def nbis_validate_tagged(tagged, operand):
    """Closed original-document/context proof; exact Decimal, no tolerance."""
    def fail():
        raise _block("INPUT_MALFORMED", "NBIS source-bound tagged proof")
    def number(v):
        if not isinstance(v, str) or len(v) > 40 or re.fullmatch(r"[0-9]+(?:\.[0-9]+)?", v) is None:
            fail()
        return Decimal(v)
    if not isinstance(tagged, dict) or type(tagged.get("present")) is not bool:
        fail()
    if not tagged["present"]:
        if tagged != {"present": False, "policy": "FOREIGN_TABLE_TAGGED_ABSENCE_V1"}:
            fail()
        return
    if set(tagged) != {"present", "policy", "value", "lower_inclusive", "upper_exclusive", "facts"} or tagged["policy"] != "HALF_UP_HALF_OPEN":
        fail()
    shown, value = number(operand["value"]), number(tagged["value"])
    if (number(tagged["lower_inclusive"]) != shown - Decimal(50000)
            or number(tagged["upper_exclusive"]) != shown + Decimal(50000) or not shown - Decimal(50000) <= value < shown + Decimal(50000)):
        raise _block("SOURCE_DISAGREEMENT", "NBIS exact half-up source fact fences")
    facts = tagged["facts"]
    fields = {"concept", "namespace", "context", "entity", "unit", "measure", "measure_namespace", "start", "end", "scope", "accounting_basis", "value"}
    if not isinstance(facts, list) or not 1 <= len(facts) <= 64:
        fail()
    seen = set()
    for f in facts:
        if (not isinstance(f, dict) or set(f) != fields or any(not isinstance(f[k], str) or not 0 < len(f[k]) <= 240 for k in fields)
                or re.fullmatch(r"[A-Za-z_][A-Za-z0-9_.-]*:(?:Revenues|RevenueFromContractWithCustomerExcludingAssessedTax)", f["concept"]) is None
                or NAMESPACES["us-gaap"].fullmatch(f["namespace"]) is None
                or re.fullmatch(r"[0-9]{1,10}", f["entity"]) is None or int(f["entity"]) != 1513845
                or re.fullmatch(r"[A-Za-z_][A-Za-z0-9_.-]*:USD", f["measure"]) is None
                or NAMESPACES["iso4217"].fullmatch(f["measure_namespace"]) is None
                or (f["start"], f["end"]) != (operand["start"], operand["end"])
                or f["scope"] != operand["scope"] or f["accounting_basis"] != operand["accounting_basis"] or number(f["value"]) != value):
            fail()
        identity = canonical_json(f)
        if identity in seen:
            fail()
        seen.add(identity)


def nbis_calendar(operands, anchor):
    """Prove the December year end from actual 12M/quarter header relationships."""
    if not isinstance(operands, list) or not 1 <= len(operands) <= 64:
        raise _block("CAPTURE_LIMIT", "NBIS calendar operands")
    year_proofs = [o for o in operands if o["start"] == o["end"][:4] + "-01-01"
                   and o["end"] == o["end"][:4] + "-12-31"]
    if not year_proofs:
        raise _block("CALENDAR_RULE_UNPROVEN", "NBIS captured full-year statement missing")
    ae = date.fromisoformat(anchor)
    if ae.month % 3 or ae != nbis_quarter(ae.year, ae.month // 3)[1]:
        raise _block("CALENDAR_RULE_UNPROVEN", "NBIS non-calendar actual anchor")
    proofs = []
    for o in operands:
        start, end = (date.fromisoformat(o[k]) for k in ("start", "end"))
        if end.month % 3 or end != nbis_quarter(end.year, end.month // 3)[1]:
            raise _block("CALENDAR_RULE_UNPROVEN", "NBIS quarter/end header relationship")
        if start != nbis_quarter(end.year, end.month // 3)[0] and start != date(end.year, 1, 1):
            raise _block("CALENDAR_RULE_UNPROVEN", "NBIS header duration/start relationship")
        proofs.append(dict(o))
    intervals = []
    year, quarter = ae.year, ae.month // 3
    for _ in range(4):
        year, quarter = (year + 1, 1) if quarter == 4 else (year, quarter + 1)
        start, end = nbis_quarter(year, quarter)
        intervals.append({"start": start.isoformat(), "end": end.isoformat()})
    return {"rule": "CALENDAR_YEAR_TABLE_V1", "proofs": proofs, "intervals": intervals,
            "full_year": [dict(o) for o in year_proofs]}


def nbis_comparative_transitions(doc, earliest_selected_start):
    """Narrow prior-period note classification; cannot join changed current bases.

    Only a complete canonical block positively naming comparative discontinued
    operations and explicit FULL date intervals ending before ALL selected history
    can account for a RESTATEMENT hit. Missing dates/current-period hits refuse.
    Other A1 adverse transition detectors remain unchanged even in this dialect.
    """
    notes = []
    for reason, pattern in TRANSITIONS:
        for match in pattern.finditer(doc.text):
            blocks = [(s, e) for s, e in doc.blocks if s <= match.start() and match.end() <= e]
            if reason != "RESTATEMENT" or len(blocks) != 1:
                raise _block(reason, "NBIS operative transition")
            s, e = blocks[0]
            if e - s > MAX_PASSAGE:
                raise _block(reason, "NBIS comparative note exceeds inspectable passage")
            quote = doc.text[s:e]
            spans = list(re.finditer(r"\b(20[0-9]{2}-[0-9]{2}-[0-9]{2}) through (20[0-9]{2}-[0-9]{2}-[0-9]{2})\b", quote))
            if (not re.search(r"\bcomparative\b", quote, re.I) or not re.search(r"\bdiscontinued operations\b", quote, re.I)
                    or not spans or re.search(r"\b(?:non-reliance|no longer|current|guidance|outlook)\b", quote, re.I)):
                raise _block(reason, "NBIS no narrow comparative discontinued-period proof")
            periods = []
            for span in spans:
                start, end = (revenue_guidance.parse_day(span.group(k)) for k in (1, 2))
                if not start or not end or start > end or end.isoformat() >= earliest_selected_start:
                    raise _block(reason, "NBIS comparative interval intersects selected history")
                periods.append({"start": start.isoformat(), "end": end.isoformat()})
            notes.append({"offsets": [s, e], "quote": quote, "periods": periods, "classification": "PRIOR_COMPARATIVE_ONLY"})
    return notes


NBIS_ROLES = {"submissions": "SEC_SUBMISSIONS", "index": "SEC_INDEX", "form": "NBIS_RESULTS_FORM",
              "statement": "NBIS_ACTUALS_STATEMENT", "letter": "NBIS_SHAREHOLDER_LETTER", "member": "NBIS_RESULTS_PACKAGE",
              "ir_copy": "IR_RELEASE_PAGE", "wire_copy": "WIRE_RELEASE_PAGE"}
NBIS_DECISIONS = {
    "MEMBERSHIP": ("PACKAGE_PROVEN", {"accession", "filed", "form", "members", "report_period", "basis", "comparative_notes", "guidance_state", "link_accounts"}),
    "ACTUAL": ("TABLE_DIRECT_OR_RECONCILED", {"operand", "derivation", "tagged"}),
    "CALENDAR": ("TABLE_CALENDAR_PROVEN", {"rule", "proofs", "intervals", "full_year", "tagged_proofs"}),
    "CLAIM": ("FY_RANGE_IN_SOURCE", {"offsets", "low", "high", "fiscal_year", "scope_context"}),
    "REAFFIRMATION": ("ALL_METRICS_SAME_FY", {"claim_id", "original_capture", "reference_capture", "original", "current"}),
    "FY_RECONCILIATION": ("REPORTED_YTD_PROVEN", {"fy_claim_id", "start", "end", "value", "quarters", "operand"}),
    "ROUTING": ("EVENT_CONSUMED", {"adapter", "accession", "form", "filed", "packages", "channel_history", "channel_links", "ir_item", "wire_item", "consumed", "report_period", "reference"}),
}


def validate_nbis_event(event, complete=True):
    if not isinstance(event, dict) or set(event) != NBIS_EVENT_KEYS or event["adapter"] != NBIS_6K_TABLE_REAFFIRMATION_V1:
        raise _block("INPUT_MALFORMED", "NBIS event dialect")
    for key in ("accession", "filed"):
        pattern = r"[0-9]{10}-[0-9]{2}-[0-9]{6}" if key == "accession" else r"20[0-9]{2}-[0-9]{2}-[0-9]{2}"
        if event[key] is None and not complete:
            continue
        if not isinstance(event[key], str) or not re.fullmatch(pattern, event[key]):
            raise _block("INPUT_MALFORMED", "NBIS event identity")
    if (event["accession"] is None) != (event["filed"] is None) or (event["filed"] is not None and
            revenue_guidance.parse_day(event["filed"]) is None):
        raise _block("INPUT_MALFORMED", "NBIS event date")
    if event["accession"] is None and (event["packages"] or event["channel_history"] or event["ir_item"] or event["wire_item"]):
        raise _block("INPUT_MALFORMED", "NBIS unresolved event operands")
    packages = event["packages"]
    if not isinstance(packages, list) or len(packages) > 8:
        raise _block("CAPTURE_LIMIT", "NBIS event packages")
    seen = set()
    for p in packages:
        if not isinstance(p, dict) or set(p) != NBIS_PACKAGE_KEYS or p["accession"] in seen:
            raise _block("INPUT_MALFORMED", "NBIS package dialect/duplicates")
        if not isinstance(p["accession"], str) or not re.fullmatch(r"[0-9]{10}-[0-9]{2}-[0-9]{6}", p["accession"]):
            raise _block("INPUT_MALFORMED", "NBIS package accession")
        seen.add(p["accession"])
        if revenue_guidance.parse_day(p["filed"]) is None:
            raise _block("INPUT_MALFORMED", "NBIS package date")
        if any(not isinstance(p[k], str) or len(p[k]) > 140 for k in ("index", "form", "statement", "letter")):
            raise _block("INPUT_MALFORMED", "NBIS package capture references")
        if (not isinstance(p["members"], dict) or not 1 <= len(p["members"]) <= MAX_PACKAGE_DOCUMENTS
                or any(not isinstance(k, str) or not re.fullmatch(r"[A-Za-z0-9._-]{1,120}", k)
                       or not isinstance(v, str) or len(v) > 140 for k, v in p["members"].items())):
            raise _block("INPUT_MALFORMED", "NBIS complete member map")
        if len(set(p["members"].values())) != len(p["members"]) or any(p[k] not in p["members"].values() for k in ("form", "statement", "letter")):
            raise _block("INPUT_MALFORMED", "NBIS role/member uniqueness")
        if p["filed"] > event["filed"]:
            raise _block("INPUT_MALFORMED", "NBIS future package")
    if complete and not any(p["accession"] == event["accession"] and p["filed"] == event["filed"] for p in packages):
        raise Blocked("WAITING", "INPUT_MISSING", "NBIS current complete package")
    history = event["channel_history"]
    if not isinstance(history, list) or len(history) > 16:
        raise _block("CAPTURE_LIMIT", "NBIS historical channel domain")
    history_ids = set()
    for h in history:
        if (not isinstance(h, dict) or set(h) != {"accession", "channel", "item", "capture"}
                or h["accession"] == event["accession"] or h["accession"] not in seen or h["channel"] not in ("ISSUER_IR", "WIRE_PRESS_RELEASES")
                or not isinstance(h["capture"], str) or h["capture"] != "nbis:" + h["accession"] + (":ir_copy" if h["channel"] == "ISSUER_IR" else ":wire_copy")
                or not isinstance(h["item"], dict) or set(h["item"]) != {"id", "title", "date"}):
            raise _block("INPUT_MALFORMED", "NBIS historical channel binding")
        item = h["item"]
        if (not isinstance(item["id"], str) or not 1 <= len(item["id"]) <= 400 or not item["id"].startswith("https://")
                or not isinstance(item["title"], str) or not 1 <= len(item["title"]) <= 200
                or item["date"] != next(p["filed"] for p in packages if p["accession"] == h["accession"])):
            raise _block("INPUT_MALFORMED", "NBIS historical channel item")
        triple = (h["channel"], item["id"], item["date"])
        if triple in history_ids:
            raise _block("AMBIGUOUS", "NBIS duplicate historical publication")
        history_ids.add(triple)
    for item in (event["ir_item"], event["wire_item"]):
        if item is not None and (not isinstance(item, dict) or set(item) != {"id", "title", "date"}
                                 or any(not isinstance(item[k], str) for k in item)
                                 or len(item["id"]) > 400 or len(item["title"]) > 200
                                 or revenue_guidance.parse_day(item["date"]) is None):
            raise _block("INPUT_MALFORMED", "NBIS channel lead")
    later = event["later_documents"]
    if (not isinstance(later, list) or len(later) > 256 or any(not isinstance(d, dict)
            or set(d) != {"channel", "date", "id", "label", "disposition"}
            or d["channel"] not in ("SEC_SUBMISSIONS", "ISSUER_IR", "WIRE_PRESS_RELEASES")
            or d["disposition"] not in ("RESULTS_RELEASE", "POSSIBLY_RELEVANT")
            or revenue_guidance.parse_day(d["date"]) is None
            or any(not isinstance(d[k], str) or len(d[k]) > (400 if k == "id" else 200) for k in ("id", "label")) for d in later)):
        raise _block("INPUT_MALFORMED", "NBIS material history")


def _nbis_basis(doc, company):
    if company.casefold() not in doc.text.casefold():
        raise _block("SOURCE_DISAGREEMENT", "NBIS financial source issuer")
    proofs, continuing = [], []
    for s, e in doc.blocks:
        text = doc.text[s:e]
        if not 0 < len(text) <= MAX_PASSAGE:
            continue
        # The documentary accounting propositions also need FULL positive
        # blocks, not a GAAP keyword inside a governing denial/quotation.
        gaap = re.fullmatch(r"(?:These|The) unaudited condensed consolidated financial statements (?:have been|are) prepared "
                            r"in accordance with (?:U\.S\. GAAP|accounting principles generally accepted in the United States)\.?", text, re.I)
        basis = re.fullmatch(r"Revenues (?:in|presented in) (?:the|these) unaudited condensed consolidated statements of operations "
                             r"(?:are|represent) revenues from continuing operations for all periods presented\.?", text, re.I)
        if gaap:
            if len(proofs) >= 16:
                raise _block("CAPTURE_LIMIT", "NBIS accounting-basis proof domain")
            proofs.append({"offsets": [s, e], "quote": text})
        if basis:
            if len(continuing) >= 16:
                raise _block("CAPTURE_LIMIT", "NBIS continuing-basis proof domain")
            continuing.append({"offsets": [s, e], "quote": text})
    if not proofs or not continuing:
        raise _block("UNSUPPORTED_TEMPLATE", "NBIS explicit documentary GAAP/continuing revenue basis missing")
    return {"gaap": proofs, "continuing_revenue": continuing, "company": company}


def _nbis_form_report(doc, company, statement_end):
    if company.casefold() not in doc.text.casefold() or not re.search(r"\bFORM 6-K\b", doc.text, re.I):
        raise _block("SOURCE_DISAGREEMENT", "NBIS issuer/form body")
    matches = list(re.finditer(r"financial results for (?:the )?(first|second|third|fourth) quarter (?:of )?(20[0-9]{2})", doc.text, re.I))
    if not 1 <= len(matches) <= 16:
        raise _block("CAPTURE_LIMIT" if matches else "EVENT_UNRESOLVED", "NBIS report-body proof domain")
    periods = {nbis_quarter(int(m.group(2)), ORDINALS[m.group(1).lower()])[1].isoformat() for m in matches}
    if periods != {statement_end}:
        raise _block("PERIOD_MISMATCH", "NBIS form results body versus statement reporting header")
    return [{"offsets": [m.start(), m.end()], "quote": m.group(0)} for m in matches]


class _NbisLinks(_NbisGrid):
    """Same preflight limits as the financial reader; links are evidence, not fetch instructions."""
    def __init__(self, base):
        super().__init__()
        self.base, self.links, self.link_text = base, set(), 0

    def handle_starttag(self, tag, attrs):
        super().handle_starttag(tag, attrs)
        # Hidden content is not display evidence, but opaque HTML attributes
        # still cannot be assumed decorative. Do this check before hidden return.
        if (tag in ("base", "link") or any(k.startswith("on") or k in ("src", "action", "formaction", "background", "srcset", "data", "poster")
                or (k == "href" and tag != "a") or (k == "style" and v and re.search(r"url\s*\(", v, re.I)) for k, v in attrs)):
            raise _block("UNSUPPORTED_TEMPLATE", "NBIS unaccounted executable/resource/acquisition attribute")
        if tag in ("script", "iframe", "object", "embed", "canvas", "img", "svg", "video", "audio", "blockquote", "q", "cite"):
            # No size/alt-text/decorative guess can account for image-only or
            # externally embedded financial/adverse content in this dialect.
            raise _block("UNSUPPORTED_TEMPLATE", "NBIS opaque operative content cannot be inspected")
        if self.hidden:
            return
        if tag == "a":
            values = [v for k, v in attrs if k == "href"]
            if len(values) > 1:
                raise _block("UNSUPPORTED_TEMPLATE", "NBIS duplicate href")
            if not values:
                return
            value = values[0]
            if not isinstance(value, str) or len(value) > 1200:
                raise _block("CAPTURE_LIMIT", "NBIS href")
            _nbis_work(self.budget, len(value) + len(self.base))
            target = urljoin(self.base, value)
            parsed = urlsplit(target)
            # Only literal document-local anchors cannot acquire another body.
            # No contact/admin/host wildcard or normalization clears a resource.
            if value.startswith("#"):
                return
            if re.search(r"\.(?:pdf|pptx?|docx?|png|jpe?g|gif|svg|mp[34]|webm|zip)$", parsed.path, re.I):
                raise _block("UNSUPPORTED_TEMPLATE", "NBIS uninspectable linked material")
            if (parsed.scheme != "https" or parsed.username or parsed.password or parsed.port not in (None, 443)
                    or parsed.query or parsed.fragment):
                raise _block("UNSUPPORTED_TEMPLATE", "NBIS unknown linked acquisition shape")
            if target not in self.links:
                if len(self.links) >= 256 or self.link_text + len(target) > 64000:
                    raise _block("CAPTURE_LIMIT", "NBIS total package links")
                self.link_text += len(target)
                self.links.add(target)


def _nbis_package_links(raw, base):
    if type(raw) is not bytes or len(raw) > MAX_DOCUMENT_BYTES or not isinstance(base, str) or len(base) > 400:
        raise _block("CAPTURE_LIMIT", "NBIS linked document")
    # Check the original canonical bytes so planner and builder offsets agree.
    try:
        canonical_bytes(raw).decode("utf-8")
    except UnicodeDecodeError as error:
        raise _block("CANONICALIZATION_FAILED", f"not UTF-8 at byte {error.start}") from error
    # The ORIGINAL exact EDGAR administrative injection is the only executable
    # fragment excluded from this inspectability preflight. Source/capture hashes
    # and the financial normalizer remain over the untouched original bytes.
    inspectable = EDGAR_INJECTION.sub(b"", raw)
    if re.search(rb"\b(?:url\s*\(|content\s*:)", inspectable, re.I):
        raise _block("UNSUPPORTED_TEMPLATE", "NBIS opaque CSS-generated/media content")
    reader = _NbisLinks(base)
    _feed_html(reader, canonical_bytes(inspectable))
    if reader.stack or reader.hidden:
        raise _block("UNSUPPORTED_TEMPLATE", "NBIS unclosed linked document")
    return reader.links


def nbis_link_accounts(raw, base, targets, required=()):
    """Every collected potentially operative href binds an actual original member.

    No host/extension/title/admin wildcard. Unclassified links refuse, including
    external HTML and extensionless updates; this is NOT a crawling permission.
    Only literal document-local anchors are non-acquisition syntax, never an
    external/contact/admin exemption. Replay rereads the original raw hrefs.
    """
    links = _nbis_package_links(raw, base)
    by_url = {}
    for key, url in targets.items():
        if url in by_url:
            raise _block("AMBIGUOUS", "NBIS multiple original captures for a link URL")
        by_url[url] = key
    if not set(required) <= links:
        raise _block("INCOMPLETE_EVENT_COVERAGE", "NBIS required original package links missing")
    accounts = []
    for url in sorted(links):
        if url not in by_url:
            raise _block("INCOMPLETE_EVENT_COVERAGE", "NBIS unaccounted operative link")
        accounts.append({"url": url, "capture": by_url[url]})
    return accounts


def nbis_members(names, accession):
    """Whole index admission, not an HTML-only filter hiding other formats.

    Only the bound index itself is administrative. Every other member must be an
    inspectable HTML form/exhibit. Unreviewed aggregate/text/XML/PDF/image/media
    representations remain explicit unsupported inputs, not implicit clearance.
    """
    if (not isinstance(names, list) or not 1 <= len(names) <= 128 or len(names) != len(set(names))
            or any(not isinstance(n, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,119}", n) for n in names)):
        raise _block("CAPTURE_LIMIT", "NBIS bounded index member domain")
    members = []
    for name in names:
        if name == "index.json":
            continue
        if not name.lower().endswith((".htm", ".html")):
            raise _block("UNSUPPORTED_TEMPLATE", "NBIS unknown/uninspectable index member: " + name[:80])
        members.append(name)
    if not 1 <= len(members) <= MAX_PACKAGE_DOCUMENTS:
        raise _block("CAPTURE_LIMIT", "NBIS whole operative package")
    return sorted(members)


def _build_nbis(profile, predecessor, event, captures, verified_at):
    """Complete pure composition; only captured documentary inputs can create numbers."""
    validate_nbis_profile(profile)
    validate_nbis_event(event)
    sym, cik, company = profile["symbol"], profile["cik"], profile["company_name"]
    if revenue_guidance.parse_instant(verified_at) is None:
        raise _block("INPUT_MALFORMED", "NBIS decision clock")
    inputs = _Inputs(captures, verified_at)
    def raw(key, role):
        cap, data = inputs.raw(key)
        if revenue_guidance.parse_instant(cap["retrieved_at"]) is None:
            raise _block("APPROVAL_BINDING", "NBIS original retrieval clock")
        if cap["role"] not in (role, "REPLAY_" + role):
            raise _block("APPROVAL_BINDING", "NBIS source role")
        return cap, data
    subs_cap, subs_raw = raw("submissions", NBIS_ROLES["submissions"])
    if subs_cap["url"] != f"https://data.sec.gov/submissions/CIK{cik:010d}.json":
        raise _block("APPROVAL_BINDING", "NBIS submissions issuer")
    filings = parse_submissions(subs_raw, cik, foreign_items_absence=True)
    documents, decoded, operands, decisions, consumed = {}, {}, [], [], []
    if not event["packages"]:
        raise Blocked("WAITING", "INPUT_MISSING", "NBIS complete accession-index/form/exhibit packages")
    package_reports = []
    link_targets = {}
    for p in event["packages"]:
        base = f"{SEC_ARCHIVES}{cik}/{p['accession'].replace('-', '')}/"
        for name, key in p["members"].items():
            role = NBIS_ROLES["form"] if key == p["form"] else NBIS_ROLES["statement"] if key == p["statement"] else NBIS_ROLES["letter"] if key == p["letter"] else NBIS_ROLES["member"]
            cap, _ = raw(key, role)
            if cap["url"] != base + name:
                raise _block("APPROVAL_BINDING", "NBIS original link-target identity")
            link_targets[key] = cap["url"]
    channel_links = {}
    for p in event["packages"]:
        accession = p["accession"]
        f = filings.get(accession)
        if (f is None or f.form != "6-K" or f.filed != p["filed"] or f.filed > verified_at[:10]
                or f.filed > subs_cap["retrieved_at"][:10]):
            raise _block("APPROVAL_BINDING", "NBIS package submissions identity/date")
        index_cap, index_raw = raw(p["index"], NBIS_ROLES["index"])
        base = f"{SEC_ARCHIVES}{cik}/{accession.replace('-', '')}/"
        if index_cap["url"] != base + "index.json":
            raise _block("APPROVAL_BINDING", "NBIS index accession")
        names = parse_index(index_raw)
        members = nbis_members(names, accession)
        if set(p["members"]) != set(members):
            raise _block("INCOMPLETE_EVENT_COVERAGE", "NBIS complete inspectable membership")
        statements = [n for n in members if re.fullmatch(profile["release"]["statement_name_pattern"], n)]
        letters = [n for n in members if re.fullmatch(profile["release"]["letter_name_pattern"], n)]
        if len(statements) != 1 or len(letters) != 1 or f.primary not in members:
            raise _block("UNSUPPORTED_TEMPLATE", "NBIS supported form/statement/letter membership")
        if (p["members"][f.primary] != p["form"] or p["members"][statements[0]] != p["statement"]
                or p["members"][letters[0]] != p["letter"]):
            raise _block("APPROVAL_BINDING", "NBIS exact role/member association")
        local, member_links = {}, {}
        for name, key in sorted(p["members"].items()):
            role = NBIS_ROLES["form"] if key == p["form"] else NBIS_ROLES["statement"] if key == p["statement"] else NBIS_ROLES["letter"] if key == p["letter"] else NBIS_ROLES["member"]
            cap, data = raw(key, role)
            if cap["url"] != base + name or cap["retrieved_at"][:10] < f.filed:
                raise _block("APPROVAL_BINDING", "NBIS member URL/publication")
            doc, _ = nbis_document(data)
            member_links[key] = nbis_link_accounts(data, cap["url"], link_targets)  # EVERY collected href accounted
            doc_id = f"{sym}-{accession}-{name}"
            if len(doc_id) > 120:
                raise _block("CAPTURE_LIMIT", "NBIS document ID")
            documents[doc_id] = _doc_entry(sym, company, doc_id, "SEC_6K_EXHIBIT", cap, f.filed, f"{company} {name} ({accession})")
            local[key] = (cap, doc, doc_id)
            decoded[key] = local[key]
        form_cap, form_raw = raw(p["form"], NBIS_ROLES["form"])
        if not {p["statement"], p["letter"]} <= {a["capture"] for a in member_links[p["form"]]}:
            raise _block("INCOMPLETE_EVENT_COVERAGE", "NBIS form furnishing exact operative exhibits")
        statement_cap, statement_raw = raw(p["statement"], NBIS_ROLES["statement"])
        statement, values, report_end = nbis_statement(statement_raw, f.filed)
        body_proof = _nbis_form_report(local[p["form"]][1], company, report_end)
        basis = _nbis_basis(statement, company)
        basis["corroboration"] = nbis_corroboration(statement_raw, values, local[p["letter"]][1], p["letter"])
        statement_id = local[p["statement"]][2]
        bound = [nbis_bind_operand(v, p["statement"], statement_cap, statement_id) for v in values]
        operands.extend(bound)
        package_reports.append((p, report_end))
        decisions.append({"kind": "MEMBERSHIP", "ref": accession, "decision": "PACKAGE_PROVEN", "capture": p["index"],
                          "operands": {"accession": accession, "filed": f.filed, "form": p["form"],
                                       "members": dict(p["members"]), "report_period": {"end": report_end, "body": body_proof},
                                       "basis": basis, "comparative_notes": [], "guidance_state": None, "link_accounts": member_links}})
        consumed.append({"channel": "SEC_SUBMISSIONS", "id": accession, "date": f.filed})
    current = [(p, e) for p, e in package_reports if p["accession"] == event["accession"] and p["filed"] == event["filed"]]
    if len(current) != 1:
        raise _block("APPROVAL_BINDING", "NBIS selected current results package")
    current_p, anchor = current[0]
    anchor_day = date.fromisoformat(anchor)
    predecessor_anchor = max(q["end"] for q in predecessor.get("reported_quarters") or [{"end": "0000-00-00"}])
    if predecessor_anchor > anchor:
        raise _block("OUT_OF_ORDER", "NBIS actual anchor regression")
    calendar = nbis_calendar(operands, anchor)
    # Calendar carries every parsed source operand used below, not period-only
    # identities collapsing multiple original documents. Deduplicate FULL facts.
    tagged_by_identity = {}
    markup_by_capture = {}
    for operand in calendar["proofs"]:
        identity = canonical_json(operand)
        if identity not in tagged_by_identity:
            key = operand["capture"]
            if key not in markup_by_capture:
                markup_by_capture[key] = bool(IXBRL_MARKUP.search(decoded[key][0]["raw"]))
            tagged_by_identity[identity] = {"operand": dict(operand), "tagged": nbis_tagged_reconciliation(
                decoded[key][1], operand, cik, markup_by_capture[key])}
    calendar["tagged_proofs"] = list(tagged_by_identity.values())
    aq, afy = anchor_day.month // 3, anchor_day.year
    trailing = []
    for step in (3, 2, 1, 0):
        q, year = next_quarter(aq, afy, -step)
        trailing.append(nbis_quarter(year, q))
    earliest = trailing[0][0].isoformat()
    for d in decisions:
        if d["kind"] == "MEMBERSHIP":
            p = next(p for p in event["packages"] if p["accession"] == d["ref"])
            for key in p["members"].values():
                notes = nbis_comparative_transitions(decoded[key][1], earliest)
                d["operands"]["comparative_notes"].extend({"capture": key, **n} for n in notes)
    def choose(start, end):
        rows = [o for o in operands if (o["start"], o["end"]) == (start.isoformat(), end.isoformat())]
        if not rows:
            raise Blocked("WAITING", "INPUT_MISSING", f"NBIS proven statement operand {start}..{end}")
        # Reviewed identical disclosed repetitions are corroboration, not an
        # arbitrary first-number source. Conflicting scope/value/precision blocks.
        fields = ("value", "currency", "unit_multiplier", "scope", "accounting_basis", "precision")
        if any(any(o[k] != rows[0][k] for k in fields) for o in rows[1:]):
            raise _block("SOURCE_DISAGREEMENT", "NBIS duplicate statement interval conflict")
        return min(rows, key=lambda o: (o["document_id"], o["locator"]))
    reported = []
    for start, end in trailing:
        direct = choose(start, end)
        derivation = None
        if end.month == 12:
            derivation = nbis_difference(choose(date(end.year, 1, 1), end),
                                        choose(date(end.year, 1, 1), date(end.year, 9, 30)), direct,
                                        "FULL_YEAR_MINUS_INITIAL_NINE_MONTHS")
        if end.month == 3 and anchor_day >= date(end.year, 6, 30):
            derivation = nbis_difference(choose(date(end.year, 1, 1), date(end.year, 6, 30)),
                                        choose(date(end.year, 4, 1), date(end.year, 6, 30)), direct,
                                        "SIX_MONTHS_MINUS_FINAL_QUARTER")
        row = {"fiscal_label": label(profile["calendar"]["label_format"], end.month // 3, end.year),
               "start": start.isoformat(), "end": end.isoformat(), "revenue": _f(Decimal(direct["value"])),
               "currency": "USD", "scope": "COMPANY", "accounting_basis": "GAAP", "document_id": direct["document_id"],
               "locator": direct["locator"]}
        if derivation is not None:
            lo, sh = derivation["longer"], derivation["shorter"]
            row["derivation"] = {"kind": "YTD_DIFFERENCE", "longer_document_id": lo["document_id"],
                                 "longer_value": _f(Decimal(lo["value"])), "longer_start": lo["start"],
                                 "shorter_document_id": sh["document_id"], "shorter_value": _f(Decimal(sh["value"])), "shorter_end": sh["end"]}
        reported.append(row)
        decisions.append({"kind": "ACTUAL", "ref": end.isoformat(), "decision": "TABLE_DIRECT_OR_RECONCILED",
                          "capture": direct["capture"], "operands": {"operand": direct, "derivation": derivation,
                          "tagged": tagged_by_identity[canonical_json(direct)]["tagged"]}})
    fy = calendar["intervals"][0]["start"][:4]
    originals = []
    for p, _ in package_reports:
        key = p["letter"]
        doc = decoded[key][1]
        if f"{fy} Guidance update" in doc.text:
            originals.append((p, nbis_original_guidance(doc)))
    if len(originals) != 1:
        raise _block("AMBIGUOUS" if originals else "INPUT_MISSING", "NBIS unique original numeric FY source")
    original_p, original = originals[0]
    original_key = original_p["letter"]
    # Every later supplied results package must positively preserve this numeric
    # source's SAME FY, not merely pass an adverse-word blacklist. No intermediate
    # letter can carry a new range or silently switch to a different claim scope.
    for d in decisions:
        if d["kind"] != "MEMBERSHIP":
            continue
        p = next(p for p in event["packages"] if p["accession"] == d["ref"])
        if p["accession"] == original_p["accession"]:
            d["operands"]["guidance_state"] = {"kind": "ORIGINAL_RANGE", **original,
                                               "low": str(original["low"]), "high": str(original["high"])}
        elif p["filed"] >= original_p["filed"]:
            if p["filed"] == original_p["filed"]:
                raise _block("AMBIGUOUS", "NBIS same-day unproven separate original-guidance event")
            d["operands"]["guidance_state"] = {"kind": "REAFFIRMATION", **nbis_reaffirmation(decoded[p["letter"]][1], original["year"])}
    if original["year"] != int(fy):
        raise _block("PERIOD_MISMATCH", "NBIS guidance versus first forward FY")
    original_cap, _, original_id = decoded[original_key]
    claim_id = f"{sym}-FY{fy}-GUIDANCE"
    claim = {"id": claim_id, "document_id": original_id,
             "locator": f"canonical[{original['offsets'][0]}:{original['offsets'][1]}] {NORMALIZER_VERSION}",
             "passage": original["passage"], "metric": "REVENUE", "assertion_kind": "COMPANY_GUIDANCE", "currency": "USD",
             "unit_multiplier": 1, "amount": None, "low": _f(original["low"]), "high": _f(original["high"]),
             "stated_point": None, "original_representation": "RANGE", "scope": "COMPANY", "scope_label": "全公司",
             "accounting_basis": "GAAP", "fiscal_label": f"FY{fy}", "period_kind": "FISCAL_YEAR",
             "period_start": f"{fy}-01-01", "period_end": f"{fy}-12-31"}
    decisions.append({"kind": "CLAIM", "ref": claim_id, "decision": "FY_RANGE_IN_SOURCE", "capture": original_key,
                      "operands": {"offsets": original["offsets"], "low": str(original["low"]), "high": str(original["high"]),
                                   "fiscal_year": original["year"], "scope_context": original["scope_context"]}})
    if current_p != original_p:
        if original_p["filed"] >= current_p["filed"]:
            raise _block("OUT_OF_ORDER", "NBIS reaffirmation must be genuinely later")
        reaffirmation = nbis_reaffirmation(decoded[current_p["letter"]][1], original["year"])
        current_key = current_p["letter"]
        current_id = decoded[current_key][2]
        claim["reaffirmed_by"] = [{"document_id": current_id,
                                  "locator": f"canonical[{reaffirmation['offsets'][0]}:{reaffirmation['offsets'][1]}] {NORMALIZER_VERSION}",
                                  "passage": reaffirmation["passage"]}]
        decisions.append({"kind": "REAFFIRMATION", "ref": claim_id, "decision": "ALL_METRICS_SAME_FY", "capture": current_key,
                          "operands": {"claim_id": claim_id, "original_capture": original_key, "reference_capture": current_key,
                                       "original": {**original, "low": str(original["low"]), "high": str(original["high"])}, "current": reaffirmation}})
    # No intervening material can disappear merely because the reference moved.
    # Historical public-channel items are captured independently and prove their
    # own package links, dates and body. A current copy cannot clear old items.
    for h in event["channel_history"]:
        p = next(p for p in event["packages"] if p["accession"] == h["accession"])
        cap, data = raw(h["capture"], "IR_RELEASE_PAGE" if h["channel"] == "ISSUER_IR" else "WIRE_RELEASE_PAGE")
        page, _ = nbis_document(data)
        item = h["item"]
        if cap["url"] != item["id"] or item["title"] not in page.text or company not in page.text:
            raise _block("SOURCE_DISAGREEMENT", "NBIS historical page identity/body")
        pattern = profile["ir_page_pattern"] if h["channel"] == "ISSUER_IR" else profile["wire_page_pattern"]
        if not re.fullmatch(pattern, cap["url"]):
            raise _block("APPROVAL_BINDING", "NBIS historical official host/path")
        expected = {raw(p[k], NBIS_ROLES[k])[0]["url"] for k in ("statement", "letter")}
        channel_links[h["capture"]] = nbis_link_accounts(data, cap["url"], link_targets, expected)
        nbis_comparative_transitions(page, earliest)
        consumed.append({"channel": h["channel"], "id": item["id"], "date": item["date"]})
    # Channel copies require concrete current-package links, not date/title equivalence.
    for channel, slot, pattern in (("ISSUER_IR", "ir_item", "ir_page_pattern"), ("WIRE_PRESS_RELEASES", "wire_item", "wire_page_pattern")):
        item = event[slot]
        key = "ir_copy" if channel == "ISSUER_IR" else "wire_copy"
        if item is None:
            if channel == "ISSUER_IR":
                raise Blocked("WAITING", "INCOMPLETE_EVENT_COVERAGE", "NBIS official IR member/channel publication")
            continue
        cap, data = raw(key, NBIS_ROLES[key])
        page, _ = nbis_document(data)
        if (cap["url"] != item["id"] or item["date"] != current_p["filed"]
                or not re.fullmatch(profile[pattern], item["id"]) or company.casefold() not in page.text.casefold()):
            raise _block("APPROVAL_BINDING", "NBIS channel actual publication identity")
        # Require actual href attributes for BOTH operative exhibits. Complete
        # adverse text is scanned independently; no free manifest-role clearance.
        required = {decoded[current_p[k]][0]["url"] for k in ("statement", "letter")}
        channel_links[key] = nbis_link_accounts(data, cap["url"], link_targets, required)
        nbis_comparative_transitions(page, earliest)
        consumed.append({"channel": channel, "id": item["id"], "date": item["date"]})
    covered = {(c["channel"], c["id"], c["date"]) for c in consumed}
    if any(original_p["filed"] <= d["date"] and (d["channel"], d["id"], d["date"]) not in covered
           for d in event["later_documents"]):
        raise _block("EVENT_UNRESOLVED", "NBIS unaccounted intervening/same-day/later material")
    # Same-anchor advancement must be later than the actual predecessor reference,
    # not just later than the original numeric letter in this captured package.
    predecessor_reference = revenue_guidance.guidance_reference(predecessor)
    if predecessor_anchor == anchor and (current_p == original_p or not predecessor_reference["published_date"]
                                         or event["filed"] <= predecessor_reference["published_date"]):
        raise _block("OUT_OF_ORDER", "NBIS same-anchor without later reaffirmation")
    fy_start = date(int(fy), 1, 1)
    ytd_rows = [q for q in reported if q["start"] >= fy_start.isoformat()]
    ytd_operand = None
    if ytd_rows:
        ytd_operand = choose(fy_start, anchor_day)
        ytd_value = sum((Decimal(str(q["revenue"])) for q in ytd_rows), Decimal(0))
        if ytd_value != Decimal(ytd_operand["value"]):
            raise _block("SOURCE_DISAGREEMENT", "NBIS exact reported-YTD reconciliation")
        ytd_end = anchor
    else:
        if fy_start != anchor_day + timedelta(days=1):
            raise _block("PERIOD_MISMATCH", "NBIS zero-reported-YTD fiscal adjacency")
        ytd_value, ytd_end = Decimal(0), fy_start.isoformat()
    recon = {"fy_claim_id": claim_id, "ytd_start": fy_start.isoformat(), "ytd_end": ytd_end,
             "ytd_revenue": _f(ytd_value), "ytd_quarter_ends": [q["end"] for q in ytd_rows]}
    decisions.append({"kind": "FY_RECONCILIATION", "ref": claim_id, "decision": "REPORTED_YTD_PROVEN",
                      "capture": current_p["statement"], "operands": {"fy_claim_id": claim_id, "start": recon["ytd_start"],
                      "end": recon["ytd_end"], "value": str(ytd_value), "quarters": recon["ytd_quarter_ends"], "operand": ytd_operand}})
    calendar_source = calendar["full_year"][0]
    intervals = [{"fiscal_label": label(profile["calendar"]["label_format"], date.fromisoformat(i["end"]).month // 3,
                                       date.fromisoformat(i["end"]).year), **i,
                  "calendar_document_id": calendar_source["document_id"], "calendar_locator": calendar_source["locator"]}
                 for i in calendar["intervals"]]
    decisions.append({"kind": "CALENDAR", "ref": "calendar", "decision": "TABLE_CALENDAR_PROVEN",
                      "capture": calendar_source["capture"], "operands": calendar})
    if len(documents) > 16 or len(decisions) + 1 > 32:
        raise _block("CAPTURE_LIMIT", "NBIS record/decision domain")
    channels = dict(predecessor.get("release_channels") or {})
    channels["ir_guidance_release_title"] = event["ir_item"]["title"]
    record = {"symbol": sym, "company_name": company, "status": "GUIDANCE", "reason": None, "url_prefixes": [SEC_ARCHIVES],
              "documents": sorted(documents.values(), key=lambda d: d["id"]), "claims": [claim], "reported_quarters": reported,
              "forward_intervals": intervals, "fy_reconciliation": recon, "release_channels": channels, "reviewed_later_documents": []}
    revenue_guidance.validate_issuer_record(record, sym)
    reference = revenue_guidance.guidance_reference(record)
    if reference["conflict"] or reference["document_id"] != decoded[current_p["letter"]][2]:
        raise _block("RECORD_INVALID", "NBIS complete active-reference conflict")
    decisions.append({"kind": "ROUTING", "ref": "routing", "decision": "EVENT_CONSUMED", "capture": "submissions",
                      "operands": {"adapter": profile["adapter"], "accession": event["accession"], "form": "6-K", "filed": event["filed"],
                                   "packages": event["packages"], "channel_history": event["channel_history"], "channel_links": channel_links,
                                "ir_item": event["ir_item"], "wire_item": event["wire_item"],
                                   "consumed": sorted(consumed, key=lambda c: (c["channel"], c["id"], c["date"])),
                                   "report_period": {"quarter": aq, "fiscal_year": afy, "start": trailing[-1][0].isoformat(), "end": anchor},
                                   "reference": {"document_id": reference["document_id"], "claims": reference["claims"]}}})
    complete_decisions = [dict(d, reviewed_at=verified_at) for d in decisions]
    validate_nbis_decisions(complete_decisions, {k: c["raw_sha256"] for k, c in captures.items()}, event, record, verified_at)
    return {"outcome": "VERIFIED", "reason": None, "detail": "", "record": record, "decisions": complete_decisions}


def nbis_corroboration(raw, values, letter, letter_capture):
    """Reconcile exact Financial Highlights/current group repetitions, never use
    Change/comparatives/segment figures as an alternate actuals source."""
    _, tables = nbis_document(raw)
    proof, current_year = [], max(v["end"][:4] for v in values)
    expected = {(v["start"], v["end"]): Decimal(v["value"]) for v in values}
    selected = []
    for ti, t in enumerate(tables):
        cells = list({id(v): v for v in t["grid"].values()}.values())
        size = len(t["prefix"]) + sum(len(v["text"]) + 1 for v in cells)
        _nbis_work(t["budget"], size)
        text = t["prefix"] + " " + " ".join(v["text"] for v in cells)
        if "Financial Highlights" not in text or "Consolidated results" not in text:
            continue
        rows = {v["row"] for v in cells if v["text"] == "Revenues"}
        if len(rows) != 1:
            raise _block("AMBIGUOUS", "NBIS highlights consolidated revenue row")
        row = next(iter(rows))
        checked = []
        for cell in cells:
            if cell["row"] != row or not re.fullmatch(r"[0-9]{1,12}(?:,[0-9]{3})*\.[0-9]", cell["text"]):
                continue
            heads = []
            for r in range(row):
                h = t["grid"].get((r, cell["col"]))
                _nbis_work(t["budget"], 1 + (len(h["text"]) if h else 0))
                if h and h["text"] not in heads:
                    heads.append(h["text"])
            if sum(len(h) for h in heads) > NBIS_GRID_LIMITS["cell_text"]:
                raise _block("CAPTURE_LIMIT", "NBIS highlights headers")
            joined = " ".join(heads)
            if re.search(r"\bChange\b|%", joined, re.I):
                continue  # explicitly not a monetary actual
            years = [h for h in heads if re.fullmatch(r"20[0-9]{2}", h)]
            durations = list(re.finditer(r"\b(Three|Six|Nine|Twelve) months ended (March|June|September|December) ([0-9]{1,2})\b", joined, re.I))
            if len(years) != 1 or len(durations) != 1:
                raise _block("UNSUPPORTED_TEMPLATE", "NBIS highlights period hierarchy")
            if years[0] != current_year:
                continue
            m = durations[0]
            month, day = NBIS_MONTHS[m.group(2).title()]
            n = {"three": 3, "six": 6, "nine": 9, "twelve": 12}[m.group(1).lower()]
            if int(m.group(3)) != day or n > month or "in millions of U.S. dollars" not in text:
                raise _block("UNIT_MISMATCH", "NBIS highlights measure/period")
            interval = (date(int(years[0]), month - n + 1, 1).isoformat(), date(int(years[0]), month, day).isoformat())
            amount = Decimal(cell["text"].replace(",", "")) * MULT["million"]
            if interval not in expected or amount != expected[interval]:
                raise _block("SOURCE_DISAGREEMENT", "NBIS highlights/current statement")
            checked.append({"locator": f"grid[{ti}].r[{row}].c[{cell['col']}]", "start": interval[0],
                            "end": interval[1], "value": str(amount), "shown": cell["text"], "headers": heads})
        if checked:
            selected.append(checked)
    if len(selected) != 1:
        raise _block("AMBIGUOUS" if selected else "RELEASE_ROW_NOT_FOUND", "NBIS unique current highlights corroboration")
    proof.extend({"kind": "HIGHLIGHTS", **v} for v in selected[0])
    # Only an explicitly consolidated, period-named monetary repetition is
    # comparable. Unscoped revenue/AI-cloud/ARR never becomes a group actual.
    for s, e in letter.blocks:
        quote = letter.text[s:e]
        if not re.search(r"\bConsolidated revenues?\b", quote, re.I):
            continue
        # Skip ONLY an entirely parsed positive FY block, never a block merely
        # containing 'guidance'. Mixed/negated/unknown clauses remain unsupported.
        if nbis_positive_guidance_block(quote) is not None:
            continue
        start, end, amount = nbis_letter_actual(quote)
        if expected.get((start, end)) != amount:
            raise _block("SOURCE_DISAGREEMENT", "NBIS group-letter/current statement")
        if len(proof) >= 32:
            raise _block("CAPTURE_LIMIT", "NBIS comparable letter proof domain")
        proof.append({"kind": "LETTER", "capture": letter_capture, "offsets": [s, e], "quote": quote,
                      "start": start, "end": end, "value": str(amount)})
    return proof


def validate_nbis_decisions(decisions, captures, event, record, reviewed_at):
    """Closed bounded decision dialect; admission ALSO independently reruns the
    complete pure builder on original stored raw bytes. This is not raw replay."""
    def require(condition):
        if not condition:
            raise _block("INPUT_MALFORMED", "NBIS nested decision schema")
    def day(v):
        return isinstance(v, str) and revenue_guidance.parse_day(v) is not None
    def text(v, n=1000):
        return isinstance(v, str) and 0 < len(v) <= n
    def decimal(v):
        require(text(v, 40) and re.fullmatch(r"[0-9]+(?:\.[0-9]+)?", v) is not None)
        number = Decimal(v)
        require(number.is_finite() and number >= 0)
        return number
    def span(v):
        require(isinstance(v, list) and len(v) == 2 and all(type(n) is int and 0 <= n <= MAX_CANONICAL_TEXT for n in v) and v[0] < v[1])
    def quote(v):
        require(isinstance(v, dict) and set(v) == {"offsets", "quote"} and text(v["quote"]))
        span(v["offsets"])
    def fact(v):
        require(isinstance(v, dict) and set(v) == NBIS_FACT_KEYS and v["capture"] in captures
                and text(v["document_id"], 120) and all(re.fullmatch(r"[0-9a-f]{64}", v[k]) for k in ("raw_sha256", "source_sha256"))
                and v["raw_sha256"] == captures[v["capture"]] and day(v["start"]) and day(v["end"]) and v["start"] <= v["end"])
        decimal(v["value"])  # controlled grammar before Decimal conversion in the public operand helper
        nbis_bind_operand({k: v[k] for k in NBIS_FACT_KEYS - {"capture", "document_id", "raw_sha256", "source_sha256"}},
                          v["capture"], {"raw_sha256": v["raw_sha256"], "sha256": v["source_sha256"]}, v["document_id"])
        referenced[canonical_json(v)] = v
    require(isinstance(decisions, list) and 1 <= len(decisions) <= 32)
    link_targets = {key: f"{SEC_ARCHIVES}1513845/{p['accession'].replace('-', '')}/{name}"
                    for p in event["packages"] for name, key in p["members"].items()}
    def links(rows):
        require(isinstance(rows, list) and len(rows) <= 256)
        urls = []
        for row in rows:
            require(isinstance(row, dict) and set(row) == {"url", "capture"} and row["capture"] in link_targets
                    and row["capture"] in captures and row["url"] == link_targets[row["capture"]])
            urls.append(row["url"])
        require(urls == sorted(set(urls)))
    counts = {k: 0 for k in NBIS_DECISIONS}
    unique, referenced = set(), {}
    for d in decisions:
        require(isinstance(d, dict) and set(d) == {"kind", "ref", "decision", "capture", "operands", "reviewed_at"})
        kind = d["kind"]
        require(kind in NBIS_DECISIONS and text(d["ref"], 80) and d["capture"] in captures and d["reviewed_at"] == reviewed_at)
        decision, domain = NBIS_DECISIONS[kind]
        op = d["operands"]
        require(d["decision"] == decision and isinstance(op, dict) and set(op) == domain)
        require((kind, d["ref"]) not in unique)
        unique.add((kind, d["ref"]))
        counts[kind] += 1
        if kind == "ACTUAL":
            fact(op["operand"])
            require(op["operand"]["capture"] == d["capture"] and op["operand"]["end"] == d["ref"])
            deriv = op["derivation"]
            if deriv is not None:
                require(isinstance(deriv, dict) and set(deriv) == {"operation", "longer", "shorter", "direct", "output"})
                for k in ("longer", "shorter", "direct"):
                    fact(deriv[k])
                require(deriv == nbis_difference(deriv["longer"], deriv["shorter"], deriv["direct"], deriv["operation"]))
                require(deriv["direct"] == op["operand"])
            nbis_validate_tagged(op["tagged"], op["operand"])
        elif kind == "CLAIM":
            span(op["offsets"])
            require(type(op["fiscal_year"]) is int and 2000 <= op["fiscal_year"] <= 2099 and 0 < decimal(op["low"]) <= decimal(op["high"]))
            value = nbis_guidance_proof(op["scope_context"])
            require(op["offsets"] == op["scope_context"]["range_offsets"] and op["fiscal_year"] == value["year"]
                    and decimal(op["low"]) == value["low"] and decimal(op["high"]) == value["high"])
        elif kind == "REAFFIRMATION":
            require(op["claim_id"] == d["ref"] and op["original_capture"] in captures and op["reference_capture"] == d["capture"])
            for k, fields in (("original", {"year", "low", "high", "offsets", "passage", "scope_context"}),
                              ("current", {"year", "offsets", "passage"})):
                require(isinstance(op[k], dict) and set(op[k]) == fields and text(op[k]["passage"]))
                span(op[k]["offsets"])
            require(op["original"]["year"] == op["current"]["year"])
        elif kind == "CALENDAR":
            require(isinstance(op["proofs"], list) and 1 <= len(op["proofs"]) <= 64)
            for v in op["proofs"]:
                fact(v)
            anchor = record["reported_quarters"][-1]["end"]
            require({k: v for k, v in op.items() if k != "tagged_proofs"} == nbis_calendar(op["proofs"], anchor))
        elif kind == "FY_RECONCILIATION":
            require(op["fy_claim_id"] == d["ref"] and day(op["start"]) and day(op["end"]) and op["start"] <= op["end"]
                    and isinstance(op["quarters"], list) and len(op["quarters"]) <= 4 and all(day(v) for v in op["quarters"]))
            decimal(op["value"])
            if op["operand"] is not None:
                fact(op["operand"])
            else:
                require(op["start"] == op["end"] and decimal(op["value"]) == 0 and op["quarters"] == [])
        elif kind == "MEMBERSHIP":
            require(op["accession"] == d["ref"] and day(op["filed"]) and op["form"] in captures and isinstance(op["members"], dict)
                    and 1 <= len(op["members"]) <= MAX_PACKAGE_DOCUMENTS and all(k in captures for k in op["members"].values()))
            require(isinstance(op["link_accounts"], dict) and set(op["link_accounts"]) == set(op["members"].values()))
            for rows in op["link_accounts"].values():
                links(rows)
            package = next((p for p in event["packages"] if p["accession"] == op["accession"]), None)
            require(package is not None and op["members"] == package["members"] and op["form"] == package["form"])
            require({package["statement"], package["letter"]} <= {v["capture"] for v in op["link_accounts"][op["form"]]})
            require(isinstance(op["report_period"], dict) and set(op["report_period"]) == {"end", "body"} and day(op["report_period"]["end"]))
            require(isinstance(op["report_period"]["body"], list) and 1 <= len(op["report_period"]["body"]) <= 16)
            for v in op["report_period"]["body"]:
                quote(v)
            basis = op["basis"]
            require(isinstance(basis, dict) and set(basis) == {"gaap", "continuing_revenue", "company", "corroboration"}
                    and basis["company"] == "Nebius Group N.V.")
            for k in ("gaap", "continuing_revenue"):
                require(isinstance(basis[k], list) and 1 <= len(basis[k]) <= 16)
                for v in basis[k]:
                    quote(v)
            require(isinstance(basis["corroboration"], list) and 1 <= len(basis["corroboration"]) <= 32)
            for v in basis["corroboration"]:
                fields = {"kind", "locator", "start", "end", "value", "shown", "headers"} if v.get("kind") == "HIGHLIGHTS" else {"kind", "capture", "offsets", "quote", "start", "end", "value"}
                require(isinstance(v, dict) and set(v) == fields and v["kind"] in ("HIGHLIGHTS", "LETTER") and day(v["start"]) and day(v["end"]))
                decimal(v["value"])
                if v["kind"] == "LETTER":
                    span(v["offsets"]); require(text(v["quote"]) and v["capture"] == package["letter"] and v["capture"] in captures
                                               and v["offsets"][1] - v["offsets"][0] == len(v["quote"]))
                    start, end, amount = nbis_letter_actual(v["quote"])
                    require((v["start"], v["end"]) == (start, end) and decimal(v["value"]) == amount)
                else:
                    require(text(v["locator"], 120) and text(v["shown"], 40) and isinstance(v["headers"], list) and len(v["headers"]) <= 512
                            and all(text(h, 8192) for h in v["headers"]))
            state = op["guidance_state"]
            if state is not None:
                fields = {"kind", "year", "offsets", "passage", "low", "high", "scope_context"} if state.get("kind") == "ORIGINAL_RANGE" else {"kind", "year", "offsets", "passage"}
                require(isinstance(state, dict) and set(state) == fields and state["kind"] in ("ORIGINAL_RANGE", "REAFFIRMATION")
                        and type(state["year"]) is int and 2000 <= state["year"] <= 2099 and text(state["passage"]))
                span(state["offsets"])
                if state["kind"] == "ORIGINAL_RANGE":
                    value = nbis_guidance_proof(state["scope_context"])
                    require(state["year"] == value["year"] and decimal(state["low"]) == value["low"] and decimal(state["high"]) == value["high"]
                            and state["offsets"] == state["scope_context"]["range_offsets"])
                    s = state["scope_context"]["offsets"][0]
                    require(state["passage"] == state["scope_context"]["quote"][state["offsets"][0] - s:state["offsets"][1] - s])
            require(isinstance(op["comparative_notes"], list) and len(op["comparative_notes"]) <= 32)
            for v in op["comparative_notes"]:
                require(isinstance(v, dict) and set(v) == {"capture", "offsets", "quote", "periods", "classification"}
                        and v["capture"] in captures and v["classification"] == "PRIOR_COMPARATIVE_ONLY" and text(v["quote"]))
                span(v["offsets"])
                require(isinstance(v["periods"], list) and 1 <= len(v["periods"]) <= 16)
                for period in v["periods"]:
                    require(isinstance(period, dict) and set(period) == {"start", "end"} and day(period["start"]) and day(period["end"]) and period["start"] <= period["end"])
        elif kind == "ROUTING":
            require(op["adapter"] == NBIS_6K_TABLE_REAFFIRMATION_V1 and op["form"] == "6-K"
                    and all(op[k] == event[k] for k in ("accession", "filed", "packages", "channel_history", "ir_item", "wire_item")))
            expected_channels = {h["capture"] for h in event["channel_history"]}
            expected_channels.update(k for k, slot in (("ir_copy", "ir_item"), ("wire_copy", "wire_item")) if event[slot] is not None)
            require(isinstance(op["channel_links"], dict) and set(op["channel_links"]) == expected_channels)
            for key, rows in op["channel_links"].items():
                require(key in captures)
                links(rows)
                p = next(p for p in event["packages"] if p["accession"] == (event["accession"] if key in ("ir_copy", "wire_copy") else
                         next(h["accession"] for h in event["channel_history"] if h["capture"] == key)))
                require({p["statement"], p["letter"]} <= {v["capture"] for v in rows})
            require(isinstance(op["consumed"], list) and 1 <= len(op["consumed"]) <= 32)
            triples = []
            for v in op["consumed"]:
                require(isinstance(v, dict) and set(v) == {"channel", "id", "date"} and v["channel"] in
                        ("SEC_SUBMISSIONS", "ISSUER_IR", "WIRE_PRESS_RELEASES") and text(v["id"], 400) and day(v["date"]))
                triples.append((v["channel"], v["id"], v["date"]))
            require(len(triples) == len(set(triples)))
            require(isinstance(op["report_period"], dict) and set(op["report_period"]) == {"quarter", "fiscal_year", "start", "end"}
                    and type(op["report_period"]["quarter"]) is int and 1 <= op["report_period"]["quarter"] <= 4
                    and type(op["report_period"]["fiscal_year"]) is int and day(op["report_period"]["start"]) and day(op["report_period"]["end"]))
            ref = revenue_guidance.guidance_reference(record)
            require(op["reference"] == {"document_id": ref["document_id"], "claims": ref["claims"]} and not ref["conflict"])
    require(counts["MEMBERSHIP"] == len(event["packages"]) and counts["ACTUAL"] == 4 and counts["CLAIM"] == 1
            and counts["CALENDAR"] == 1 and counts["FY_RECONCILIATION"] == 1 and counts["ROUTING"] == 1 and counts["REAFFIRMATION"] <= 1)
    cal = next(d["operands"] for d in decisions if d["kind"] == "CALENDAR")
    expected = list(dict.fromkeys(canonical_json(v) for v in cal["proofs"]))
    require(set(referenced) == set(expected))  # every direct/longer/shorter/YTD/full-year/calendar operand covered
    proofs = cal["tagged_proofs"]
    require(isinstance(proofs, list) and len(proofs) == len(expected) and 1 <= len(proofs) <= 64)
    seen = {}
    for proof in proofs:
        require(isinstance(proof, dict) and set(proof) == {"operand", "tagged"})
        fact(proof["operand"])
        identity = canonical_json(proof["operand"])
        require(identity in expected and identity not in seen)
        nbis_validate_tagged(proof["tagged"], proof["operand"])
        seen[identity] = proof["tagged"]
    require(list(seen) == expected)
    for d in decisions:
        if d["kind"] == "ACTUAL":
            require(d["operands"]["tagged"] == seen[canonical_json(d["operands"]["operand"])])


BUILDERS = {SEC_8K_202_INLINE_XBRL_V1: _build, NBIS_6K_TABLE_REAFFIRMATION_V1: _build_nbis}
