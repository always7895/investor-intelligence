#!/usr/bin/env python3
"""Company business profile for the Top20 industry field (operator rule 2026-09-25).

The industry field should say what the company actually does. The English business sentence is an
extractor-selected excerpt (not verbatim: a heading, a defined-term parenthetical or an incorporation clause may be
dropped) of Item 1 (10-K) or Item 4 (20-F) of the latest annual report on SEC EDGAR. The Chinese phrase is an UNVERIFIED
derived presentation candidate (a callback translation of that one sentence, format-checked against it; model identity
and semantic fidelity UNKNOWN), kept for research and never public report text. Without a valid candidate the caller
keeps its classification label. No cloud model, paid service or invented description.
"""
from __future__ import annotations

import hashlib
import html
import json
import os
import re
import ssl
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, HTTPSHandler, ProxyHandler, Request, build_opener

ROOT = Path(__file__).resolve().parents[1]
LOCAL_RUNTIME_CONFIG = ROOT / "config" / "local-runtime-independence-v1.json"
WORDING_POLICY = ROOT / "config" / "v213-sourced-wording-policy.json"
CACHE_ROOT = ROOT / "data" / "cache" / "v21" / "business_profiles"
ANNUAL_FORMS = ("10-K", "20-F")
EXTRACTOR_VERSION = 6  # cached sentences from another extractor are re-derived
SEC_HOSTS = ("data.sec.gov", "www.sec.gov")
MAX_DOCUMENT_BYTES = 40_000_000
SEC_MIN_INTERVAL_SECONDS = 0.25  # well inside SEC fair access (10 requests/second)
MAX_INDUSTRY_CHARS = 100  # Worker lineSafeText limit for the industry field
MAX_PHRASE_CHARS = 40
CACHE_SCHEMA = 2  # a cached phrase is reusable only with the v2 binding this extractor writes; older cache files are a miss
MAX_CACHE_BYTES = 65_536
FRESH_SOURCE_FACTS = "FRESH_FETCH_THIS_RUN"  # same literal as company_deep_report.FRESH_BUSINESS_SOURCE
CACHE_ONLY_NOT_FRESH = "CACHE_ONLY_NOT_FRESH"
TRANSLATION_UNVERIFIED = "UNVERIFIED_DERIVED_PRESENTATION_CANDIDATE"
_HEADINGS = (
    re.compile(r"item\s*1\s*[.:\-–—]?\s*business\b", re.I),
    re.compile(r"items?\s*1\s*(?:and|&)\s*2\s*[.:\-–—]?\s*business\b", re.I),  # "Items 1 and 2. Business and Properties"
    re.compile(r"item\s*4\s*[.:\-–—]?\s*information\s+on\s+the\s+company\b", re.I),
)
# Sentence ends that are abbreviations, not sentence boundaries ("Coeur Mining, Inc. (“Coeur”) ... is a").
_ABBREVIATION_END = re.compile(r"(?:\b(?:Inc|Corp|Co|Ltd|Ltda|Cos|Bros|No|Nos|St|Mt|vs|approx)|\b[A-Z]\.[A-Z]|\bL\.P|\bS\.A|\bN\.V|\bU\.S)\.$")
_SELF = re.compile(r"\b(?:is|are)\s+(?:primarily\s+|principally\s+|mainly\s+)?(?:(?:a|an|the|one\s+of)\b|engaged\s+in\b)", re.I)
_ACTIVITY = re.compile(r"\b(?:design|develop|manufactur|produc|provid|operat|offer|sell|make|suppl|engag|conduct|"
                       r"explor|refin|insur|underwrit|retail|mine|mining)\w*\b", re.I)
_ROLE_NOUN = re.compile(r"\b(?:company|leader|provider|manufacturer|developer|designer|supplier|maker|producer|insurer|"
                        r"retailer|bank|operator|trust|REIT|firm|platform|distributor|miner|explorer|refiner|carrier|utility)\b", re.I)
_SKIP = re.compile(r"item\s*1a|forward-looking|table of contents|risk factors", re.I)
# Hard off-topic: never a business self-description (governance, accounting, legal, boilerplate, 20-F cross-reference).
_OFF_TOPIC = re.compile(r"\b(?:committee|compensation|board of directors|we believe|see|form 10-k|form 20-f|"
                        r"shareholders?|stockholders?|employees|party to|defendant|"
                        r"accounting firm|pcaob|audit\w*|demand is|demand for|fiscal year|"
                        r"dividends?|restrictions?|ability to|held for sale|fair value|carrying value|costs to sell|"
                        r"impairment|allegations?|damages?|litigation|lawsuits?|logo|trademarks?|symbol|equal employment|"
                        r"integral part|presentation currency|functional currency|disclaimer|documents on display|"
                        r"not applicable|sifi|risks?|exposed to|uncertaint\w*|references? to|refers? to|subject to|"
                        r"standard & poor’?'?s \d+ company|we are a component|we are the agent|agent on behalf|"
                        r"operates? through (?:its|our) subsidiaries|"
                        r"only (?:material|significant) assets?|assets (?:primarily )?consist|liabilit\w*|lessee|lessor|"
                        r"principal to|performance obligations?|revenue recognition)\b", re.I)
# Words that do not distinguish the registrant from an affiliate (corporate forms and first-person subjects).
_GENERIC_NAME_WORDS = {"the", "inc", "incorporated", "corp", "corporation", "co", "company", "companies", "ltd", "limited",
                       "plc", "holding", "holdings", "group", "nv", "sa", "se", "ag", "and", "of", "de", "du", "la", "llc", "lp",
                       "we", "our", "us"}
# Soft off-topic: penalised only when the sentence is not the company's own "X is a ..." statement
# ("was incorporated in 1921 and is primarily a gold producer", "is a holding company ... through its subsidiaries").
_OFF_TOPIC_SOFT = re.compile(r"\b(?:annual report|properties|incorporated|headquarter\w*|subsidiar\w*)\b", re.I)
# Cross-reference tables (page-number lists) are never prose.
_TOC = re.compile(r"(?:\b\d{1,3}\s*,\s*){2,}\d{1,3}\b")
# Only defined-term parentheticals are dropped; content lists such as "(e.g., structural steel, ...)" stay.
# Index membership is not what the company does: the clause is dropped, the rest of the sentence kept.
_INDEX_CLAUSE = re.compile(r"\s*,?\s*and\s+is\s+(?:part|a\s+(?:member|component))\s+of\s+the\s+S&P\s+\d+(?:\s+index)?", re.I)
_PARENTHETICAL = re.compile(r"\s*\((?=[^()]{0,220}\))[^()]*?(?:[“”\"]|together with|collectively|referred to|individually|"
                            r"the company|\bwe\b)[^()]*\)", re.I)
_INCORPORATED = re.compile(r"\s+was\s+(?:incorporated|founded|organized|formed)\s+in\s+[^.,]{0,40}?\s+and(?=\s+(?:is|are)\b)", re.I)
# Characters that occur only in Simplified Chinese; a phrase containing one is not Traditional Chinese.
_SIMPLIFIED = set("确发业务产们这个来时为说对会过动实现开关东车长门问间题经济电话网体国际广场农专与应数据设备储术质资证银贷险厂矿炼钢铁药医疗营销户购买卖价额亿币汇导区块链云软计视频"
                  "络线规划环节约统权础层级构运输仓库厅楼单页码标签优质领导积极极组织员职责条让认识记录报纸杂乐观听读写复杂简单结众")
_OVERVIEW = re.compile(r"\b(?:Business Overview|Company Overview|Overview|Our Company)\b(?=\s+[A-Z])")
_LEAD = re.compile(r"^(?:overview|general|our company|business overview)\s+", re.I)
_CJK = re.compile(r"[一-鿿]")
_THINK = re.compile(r"<think>.*?</think>", re.S)
PROMPT = ("將以下英文公司業務描述濃縮翻譯為繁體中文業務片語（最多28字）：不要寫公司名稱，"
          "不要寫「全球」「領先」等形容，只寫公司做什麼與主要產品；不得加入原文沒有的資訊或數字；"
          "提到數量時照抄原文數字，不要改成「數萬」「數千」等約略說法。只輸出片語。\n")
# Vague quantities stand in for a number the filing states exactly ("數萬家門店" for 20,959 stores).
_VAGUE_QUANTITY = re.compile(r"數[十百千萬億]|上[百千萬]|成千上萬")


def latest_annual_filing(submissions: Mapping[str, Any], cik: str) -> dict[str, str] | None:
    """Latest 10-K or 20-F from an EDGAR submissions document (newest first)."""
    recent = (submissions.get("filings") or {}).get("recent") or {}
    forms = recent.get("form") or []
    for index, form in enumerate(forms):
        if form in ANNUAL_FORMS:
            accession = str(recent["accessionNumber"][index])
            document = str(recent["primaryDocument"][index])
            url = (f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/"
                   f"{accession.replace('-', '')}/{document}")
            return {"form": form, "filed": str(recent["filingDate"][index]), "accession": accession, "url": url}
    return None


def business_text(raw: bytes) -> str:
    text = raw.decode("utf-8", "ignore")
    text = re.sub(r"(?is)<(script|style)\b.*?</\1>", " ", text)
    text = re.sub(r"(?s)<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", html.unescape(text).replace("\xa0", " ")).strip()


def _full_name(entity_name: str | None) -> re.Pattern[str] | None:
    """First two words of the registrant name: "Antero Resources" beats an affiliate such as "Antero Midstream"."""
    words = [w for w in re.findall(r"[A-Za-z0-9&]+", entity_name or "") if len(w) >= 2]
    return re.compile(rf"\b{re.escape(words[0])}\s+{re.escape(words[1])}\b", re.I) if len(words) >= 2 else None


def _self_patterns(entity_name: str | None, tickers: Sequence[str] = ()) -> tuple[re.Pattern[str], re.Pattern[str]]:
    """(sentence opens with the company as subject, strong self-description)."""
    words = re.findall(r"[A-Za-z0-9&]+", entity_name or "")
    names = [word for word in [*(words[:1]), *tickers] if isinstance(word, str) and len(word) >= 2]
    subjects = [r"\bwe", r"\bthe company", r"\bour company"]
    escaped = [r"\b" + re.escape(name) for name in names]
    lead = re.compile("(?:" + "|".join(escaped + subjects) + r")\b", re.I)
    # The rest of the name is capitalised tokens or corporate suffixes only (case-sensitive inside the
    # case-insensitive pattern), so "Best Buy Marketplace, where there is a risk" is not a self-description.
    tail = (r"(?:[\s,]+(?-i:[A-Z][\w&'’.\-]*|&|and|of|de|du|la)|,?\s+(?-i:Inc\.?|Corp\.?|Co\.?|Ltd\.?|plc|N\.V\.|S\.A\.|SE|AG)"
            r"){0,6}")
    named = [rf"\b{re.escape(name)}\b{tail}" for name in names]
    # Subject, then optional defined-term parentheticals, "and its (consolidated) subsidiaries", an appositive,
    # or "was incorporated in 1921 and", then the self-describing verb ("is (primarily) a", "are engaged in").
    own = re.compile(rf"(?:{'|'.join(named + subjects)})(?:\s*\([^()]{{0,220}}\))*"
                     r"(?:\s+and\s+(?:its|our)\s+(?:consolidated\s+)?subsidiaries(?:\s*\([^()]{0,220}\))*)?"
                     r"(?:,[^.]{0,80},)?"
                     r"(?:\s+was\s+(?:incorporated|founded|organized|formed)\s+in\s+[^.,]{0,40}?\s+and)?"
                     r"\s+(?:is|are)\s+(?:now\s+|currently\s+|today\s+|primarily\s+|principally\s+|mainly\s+)?"
                     r"(?:(?:a|an|the|one\s+of)\b|engaged\s+in\b)", re.I)
    return lead, own


def _clip(sentence: str) -> str | None:
    """Long list sentences keep their first clauses (<=400 chars) instead of being lost."""
    if len(sentence) <= 400:
        return sentence
    cut = sentence[:400]
    boundary = max(cut.rfind(";"), cut.rfind(","))
    return cut[:boundary] if boundary >= 120 else None


def _affiliate(subject: str, registrant_words: set[str] | None) -> bool:
    """Subject names words outside the registrant's name ("Antero Midstream" for Antero Resources)."""
    if not registrant_words:
        return False
    head = _PARENTHETICAL.sub("", re.split(r"\s+(?:is|are|was)\s", subject, maxsplit=1)[0])
    words = {w.lower() for w in re.findall(r"[A-Za-z0-9&]+", head) if w[:1].isupper()}
    return bool(words - registrant_words - _GENERIC_NAME_WORDS)


def _score(sentence: str, lead: re.Pattern[str], own: re.Pattern[str],
           full: re.Pattern[str] | None = None, registrant_words: set[str] | None = None) -> tuple[int, str]:
    match = own.search(sentence)
    if match:
        # Drop heading residue before the subject, defined-term parentheticals and the incorporation clause.
        score = 6 if full is not None and full.search(match.group(0)) else 5
        score -= 3 if _affiliate(match.group(0), registrant_words) else 0
        sentence = _INDEX_CLAUSE.sub("", _INCORPORATED.sub("", _PARENTHETICAL.sub("", sentence[match.start():])))
    else:
        score = 2 if _SELF.search(sentence) else 0
        score += 1 if lead.match(sentence) else 0
        score -= 4 if _OFF_TOPIC_SOFT.search(sentence) else 0
    score += 2 if _ACTIVITY.search(sentence) else 0
    score += 1 if _ROLE_NOUN.search(sentence) else 0
    score -= 4 if _OFF_TOPIC.search(sentence) else 0
    return score, sentence


def _sentences(text: str, start: int, width: int):
    """Sentences with their offsets; a fragment ending in an abbreviation ("Inc.", "U.S.") joins the next."""
    offset, pending, pending_offset = start, "", start
    for raw in re.split(r"(?<=[.!?])\s+", text[start:start + width]):
        piece = raw.strip()
        if pending:
            piece, fragment_offset = pending + " " + piece, pending_offset
        else:
            fragment_offset = offset
        offset += len(raw) + 1
        if _ABBREVIATION_END.search(piece) and len(piece) < 1500:
            pending, pending_offset = piece, fragment_offset
            continue
        pending = ""
        yield fragment_offset, piece
    if pending:
        yield pending_offset, pending


def _joined_sentences(text: str, start: int, width: int):
    """_sentences, with a piece that starts lowercase or with a digit joined to the one before
    ("approximately $26. 3 billion", "48 U.S. states"): a real sentence starts with a capital, quote or bracket."""
    previous: tuple[int, str] | None = None
    for offset, piece in _sentences(text, start, width):
        if previous is not None and piece[:1].isalnum() and not piece[:1].isupper() and len(previous[1]) < 1500:
            previous = (previous[0], previous[1] + " " + piece)
            continue
        if previous is not None:
            yield previous
        previous = (offset, piece)
    if previous is not None:
        yield previous


def _best(text: str, windows: Sequence[int], lead: re.Pattern[str], own: re.Pattern[str], *, width: int,
          minimum: int, strong_only: bool = False, full: re.Pattern[str] | None = None,
          registrant_words: set[str] | None = None) -> str | None:
    best: tuple[int, int, str, str | None] | None = None
    for start in windows:
        pieces = list(_joined_sentences(text, start, width))
        for position, (offset, raw) in enumerate(pieces):
            candidate = _clip(_LEAD.sub("", raw))
            if candidate is None or len(candidate) < 30 or _SKIP.search(candidate) or _TOC.search(candidate):
                continue
            is_own = own.search(candidate) is not None
            if (strong_only and not is_own) or (not is_own and len(candidate) < 60):
                continue  # short sentences qualify only as self-descriptions ("CF Industries is a producer of ammonia.")
            score, sentence = _score(candidate, lead, own, full, registrant_words)
            if len(sentence) >= 30 and score >= minimum and (best is None or (score, -offset) > (best[0], -best[1])):
                following = pieces[position + 1][1] if position + 1 < len(pieces) else None
                best = (score, offset, sentence, following)
    if best is None:
        return None
    sentence, following = best[2], best[3]
    # A self-description without an activity ("X is a Bermuda exempted company ...") takes the next sentence when
    # that one continues with the same subject and says what the company does ("Arch provides insurance ...").
    if (following and not _ACTIVITY.search(sentence) and lead.match(following) and _ACTIVITY.search(following)
            and not _OFF_TOPIC.search(following) and len(sentence) + len(following) < 400):
        sentence = f"{sentence} {following}"
    return sentence


def _overview_excerpt(text: str, start: int, lead: re.Pattern[str]) -> str | None:
    """First 1-3 on-topic sentences after an Overview heading (<=600 chars)."""
    match = _OVERVIEW.search(text, start, start + 12000)
    if not match:
        return None
    parts: list[str] = []
    for _, raw in _joined_sentences(text, match.end(), 3000):
        candidate = _clip(raw)
        if (candidate is None or len(candidate) < 40 or _SKIP.search(candidate) or _OFF_TOPIC.search(candidate)
                or _OFF_TOPIC_SOFT.search(candidate) or _TOC.search(candidate)):
            break
        if not parts and not (lead.search(candidate) or _ACTIVITY.search(candidate)):
            break
        if sum(len(part) + 1 for part in parts) + len(candidate) > 600:
            break
        parts.append(candidate)
        if len(parts) == 3 or sum(len(part) for part in parts) >= 300:
            break
    return " ".join(parts) or None


def business_sentence(text: str, entity_name: str | None = None, tickers: Sequence[str] = ()) -> str | None:
    """Source excerpt that says what the company does (Item 1 / 20-F Item 4).

    Order: a strong self-description ("X is a ... company that develops ...") in
    any business-heading window (tables of contents come first and MD&A
    cross-references later, so every window is scored and ties go to the earliest);
    else the Overview paragraph; else a strong self-description anywhere in the
    report (20-F filers that answer Item 4 through a cross-reference index);
    else the best activity sentence in a heading window.
    """
    lead, own = _self_patterns(entity_name, tickers)
    options = {"full": _full_name(entity_name),
               "registrant_words": {w.lower() for w in re.findall(r"[A-Za-z0-9&]+", entity_name or "")} | {t.lower() for t in tickers}}
    windows = sorted(match.end() for heading in _HEADINGS for match in heading.finditer(text))
    found = _best(text, windows, lead, own, width=12000, minimum=6, **options)
    for start in windows if found is None else ():
        found = _overview_excerpt(text, start, lead)
        if found:
            break
    found = found or _best(text, [0], lead, own, width=600000, minimum=6, strong_only=True, **options)
    # Weak fallback only in the opening description (competition/pricing sections come later): better the
    # label alone than "We carefully monitor pricing ..." as what the company does.
    return found or _best(text, windows, lead, own, width=4000, minimum=3, **options)


class ProfileBlocked(RuntimeError):
    """SEC answered 403/429; no further profile request is sent in this run."""


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError("BUSINESS_PROFILE_REDIRECT_REJECTED")


def _tls_context() -> ssl.SSLContext:
    context = ssl.create_default_context()
    try:
        import certifi
        context.load_verify_locations(cafile=certifi.where())
    except ImportError:
        pass  # system trust only; verification is never relaxed
    return context


def sec_fetcher(headers: Mapping[str, str], *, min_interval: float = SEC_MIN_INTERVAL_SECONDS) -> Callable[[str], bytes]:
    """Rate-limited SEC reader: declared contact, no proxy/redirect/cookies, 403/429 fence."""
    opener = build_opener(ProxyHandler({}), _NoRedirect(), HTTPSHandler(context=_tls_context()))
    outgoing = {**dict(headers), "Accept": "application/json, text/html", "Accept-Encoding": "identity"}
    state = {"last": 0.0, "blocked": False}

    def fetch(url: str) -> bytes:
        parts = urlsplit(url)
        if parts.scheme != "https" or parts.hostname not in SEC_HOSTS:
            raise ValueError("BUSINESS_PROFILE_URL_UNADMITTED")
        if state["blocked"]:
            raise ProfileBlocked("BUSINESS_PROFILE_SEC_FENCED")
        wait = min_interval - (time.monotonic() - state["last"])
        if wait > 0:
            time.sleep(wait)
        state["last"] = time.monotonic()
        try:
            with opener.open(Request(url, headers=outgoing), timeout=30) as response:
                body = response.read(MAX_DOCUMENT_BYTES + 1)
        except HTTPError as error:
            if error.code in (403, 429):
                state["blocked"] = True
                raise ProfileBlocked("BUSINESS_PROFILE_SEC_FENCED") from None
            raise
        if len(body) > MAX_DOCUMENT_BYTES:
            raise ValueError("BUSINESS_PROFILE_TOO_LARGE")
        return body

    return fetch


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _no_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("BUSINESS_CACHE_DUPLICATE_KEY")
        result[key] = value
    return result


def _reject_constant(name: str) -> Any:
    raise ValueError("BUSINESS_CACHE_NONFINITE")


def _finite_float(text: str) -> float:
    value = float(text)
    if value != value or value in (float("inf"), float("-inf")):
        raise ValueError("BUSINESS_CACHE_NONFINITE")  # a literal such as 1e999 overflows to infinity
    return value


def _utf8_safe(text: str) -> bool:
    """False for text holding a lone surrogate (a JSON surrogate escape): it cannot be encoded to UTF-8, so it must never reach
    a digest, the cache or a sidecar. Candidate and upstream text is checked BEFORE any binding, commitment or cache write."""
    try:
        text.encode("utf-8")
    except UnicodeEncodeError:
        return False
    return True


def _read_cache(path: Path) -> dict[str, Any] | None:
    """Bounded, strict read of the mutable business cache: one binary read of at most MAX_CACHE_BYTES (overflow is refused
    before decoding), UTF-8, no duplicate key at any depth, no NaN/Infinity (including an overflowing literal such as 1e999),
    an object root. Any problem is a cache miss (None); raw cache values are never printed or persisted here."""
    try:
        with open(path, "rb") as stream:
            raw = stream.read(MAX_CACHE_BYTES + 1)
        if len(raw) > MAX_CACHE_BYTES:
            return None
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=_no_duplicate_keys, parse_float=_finite_float,
                           parse_constant=_reject_constant)
    except (OSError, ValueError, RecursionError):
        return None
    return value if isinstance(value, dict) else None


def _digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
                                     allow_nan=False).encode("utf-8")).hexdigest()


def _phrase_binding(record: Mapping[str, Any], phrase: str) -> str:
    """Consistency binding of a cached phrase to the fresh source it was derived from. A mutable cache file can recompute it,
    so it detects staleness only and is NOT authentication: a reused phrase stays an UNVERIFIED candidate."""
    return _digest({"schema": "business-phrase-binding-v2", "cik": record["cik"], "accession": record["accession"],
                    "url": record["url"], "extractor_version": EXTRACTOR_VERSION, "document_sha256": record["document_sha256"],
                    "sentence_en": record["sentence_en"], "phrase_zh": phrase})


def _write_cache(path: Path, value: Mapping[str, Any]) -> None:
    """Best-effort atomic cache write. Every CAUGHT failure (mkdir, temp allocation, encoding, write, replace: OSError, ValueError,
    TypeError) leaves the profile usable and removes the temp file when one was created; the cache is only an optimization.
    Not claimed: other exception types, and a descriptor closed only by this process exit if closing it after a failed fdopen fails."""
    temporary: str | None = None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        handle, temporary = tempfile.mkstemp(prefix=path.name, suffix=".tmp", dir=path.parent)
        try:
            stream = os.fdopen(handle, "w", encoding="utf-8", newline="\n")
        except BaseException:
            os.close(handle)
            raise
        with stream:
            json.dump(value, stream, ensure_ascii=False, indent=2, sort_keys=True)
        os.replace(temporary, path)
    except (OSError, ValueError, TypeError):
        if temporary is not None:
            try:
                os.unlink(temporary)
            except OSError:
                pass


def resolve_business_profile(cik: str, fetch: Callable[[str], bytes], translate: Callable[[str], str | None] | None,
                             *, cache_root: Path = CACHE_ROOT, now: Callable[[], str] = _utc_now) -> dict[str, Any] | None:
    """Current profile. Every call re-reads the filing index AND the annual document through ``fetch`` (an extra
    existing-document request on a cache hit): the mutable business cache never supplies English or source facts, so the
    sentence, document hash and filing identity are fresh values from those bytes. A cached Chinese phrase is reused only
    as an UNVERIFIED presentation candidate bound to that fresh sentence, document, filing and extractor version; a missing
    or mismatched binding (every legacy cache file) or a phrase that is not valid UTF-8 text is a cache miss, and the same
    holds for a callback phrase, while the fresh source facts stay usable. Fetched bytes do not by themselves prove the
    remote origin, and the phrase is only format-checked: model identity and semantic fidelity stay UNKNOWN."""
    if not re.fullmatch(r"\d{10}", str(cik)):
        raise ValueError("BUSINESS_PROFILE_CIK_INVALID")
    raw_index = fetch(f"https://data.sec.gov/submissions/CIK{cik}.json")
    checked_at = now()
    submissions = json.loads(raw_index)
    filing = latest_annual_filing(submissions, cik)
    if filing is None:
        return None
    raw = fetch(filing["url"])
    sentence = business_sentence(business_text(raw), submissions.get("name"), submissions.get("tickers") or ())
    if sentence is None:
        return None
    record = {"cik": cik, "sic": submissions.get("sic"), "sic_description": submissions.get("sicDescription"),
              **filing, "document_sha256": hashlib.sha256(raw).hexdigest(), "document_retrieved_at": now(),
              "sentence_en": sentence}
    if not all(_utf8_safe(value) for value in record.values() if isinstance(value, str)):
        return None  # upstream text with a lone surrogate can never be encoded into a digest, the cache or a sidecar
    path = cache_root / f"CIK{cik}.json"
    cached = _read_cache(path)
    phrase, method = None, None
    if (cached is not None and cached.get("accession") == filing["accession"] and cached.get("url") == filing["url"]
            and type(cached.get("extractor_version")) is int and cached["extractor_version"] == EXTRACTOR_VERSION
            and type(cached.get("cache_schema")) is int and cached["cache_schema"] == CACHE_SCHEMA
            and cached.get("document_sha256") == record["document_sha256"] and cached.get("sentence_en") == sentence
            and isinstance(cached.get("phrase_zh"), str)):
        candidate = validate_phrase(cached["phrase_zh"], sentence)
        if (candidate is not None and candidate == cached["phrase_zh"]
                and cached.get("phrase_binding_sha256") == _phrase_binding(record, candidate)):
            phrase, method = candidate, "CACHED_CANDIDATE"
    if phrase is None and translate is not None:
        produced = translate(sentence)
        phrase = validate_phrase(produced, sentence) if isinstance(produced, str) else None
        method = "TRANSLATION_CALLBACK" if phrase else None
    _write_cache(path, {**record, "extractor_version": EXTRACTOR_VERSION, "cache_schema": CACHE_SCHEMA,
                        **({"phrase_zh": phrase, "phrase_binding_sha256": _phrase_binding(record, phrase)} if phrase else {})})
    index_sha256 = hashlib.sha256(raw_index).hexdigest()
    source_evidence = _digest({"schema": "business-source-v2", "cik": cik, "accession": filing["accession"], "url": filing["url"],
                               "form": filing["form"], "filed": filing["filed"], "document_sha256": record["document_sha256"],
                               "index_sha256": index_sha256, "sentence_en": sentence, "extractor_version": EXTRACTOR_VERSION})
    derived, derived_evidence = None, None
    if phrase:
        derived = {"kind": "UNVERIFIED_DERIVED_PRESENTATION", "method": method, "validation": "FORMAT_CHECKS_ONLY",
                   "review": "NONE", "model": "UNKNOWN", "extractor_version": EXTRACTOR_VERSION}
        derived_evidence = _digest({"schema": "business-derived-v2", "source_evidence_sha256": source_evidence,
                                    "phrase_zh": phrase, "derived": derived})
    evidence = _digest({"schema": "business-evidence-v2", "source": source_evidence, "derived": derived_evidence})
    return {**record, "retrieved_at": checked_at, "index_sha256": index_sha256, "source_facts": FRESH_SOURCE_FACTS,
            "source_evidence_sha256": source_evidence, "derived_evidence_sha256": derived_evidence,
            "evidence_sha256": evidence, "phrase_zh": phrase, "derived": derived,
            "translation": TRANSLATION_UNVERIFIED if phrase else "UNAVAILABLE"}


def cache_entry(cik: str, *, cache_root: Path = CACHE_ROOT) -> dict[str, Any] | None:
    """Filing identifiers of a cached profile for audit only (bounded strict read). It is NOT fresh source evidence and carries
    neither the English sentence nor the Chinese phrase, so a failed fetch can never present a stale or tampered cache as a
    current SEC fact."""
    if not re.fullmatch(r"\d{10}", str(cik)):
        return None
    cached = _read_cache(cache_root / f"CIK{cik}.json")
    if cached is None:
        return None
    return {**{key: cached[key] for key in ("form", "filed", "accession")
               if isinstance(cached.get(key), str) and len(cached[key]) <= 64 and _utf8_safe(cached[key])},
            "source_facts": CACHE_ONLY_NOT_FRESH}


def _banned_phrases() -> tuple[str, ...]:
    try:
        return tuple(json.loads(WORDING_POLICY.read_text(encoding="utf-8"))["banned_phrases_zh"])
    except (OSError, ValueError, KeyError):
        return ()


def validate_phrase(phrase: str, sentence: str) -> str | None:
    """Accept only a short Traditional-Chinese phrase that adds no numbers or vague wording."""
    text = _THINK.sub("", phrase or "").strip().strip("「」\"'").rstrip("。.").strip()
    if (not 4 <= len(text) <= MAX_PHRASE_CHARS or any(mark in text for mark in ("\n", "\r", "｜"))
            or not _utf8_safe(text)):
        return None
    if len(_CJK.findall(text)) < len(text) * 0.5 or any(char in _SIMPLIFIED for char in text):
        return None
    if not set(re.findall(r"\d", text)) <= set(re.findall(r"\d", sentence)):
        return None
    if any(banned in text for banned in _banned_phrases()) or _VAGUE_QUANTITY.search(text):
        return None
    return text


def local_translator(config_path: Path = LOCAL_RUNTIME_CONFIG, *, timeout: float = 60.0,
                     attempts: int = 2, resolver: Callable[..., dict] | None = None) -> Callable[[str], str | None]:
    """Translator bound to the local loopback reasoner; failures return None.

    The GPU lane is shared, so a timed-out or rejected answer is asked once more
    (2026-09-25: 5 of 20 Top20 translations were lost to transient timeouts).
    The server and model are found on first use (scripts/local_model_endpoint.py; operator 2026-09-26: the local
    model's port and ID change): the configured model where served, else the same family or the only model served.
    A reply must name the model actually found, and that model is reported through ``translate.model``.

    Explicit Strata intent (F04): every call first resolves the shared request binding (local reads only) BEFORE any resolver,
    configured fallback or cached target. A valid binding is the only authority (an injected resolver cannot waive it): the
    translation is requested from exactly the bound root/model through the shared selected-only transport, with the profile's
    thinking/effort settings, its own output and timeout ceilings (the short bound below stays a lower ceiling), at most three
    attempts inside ONE total deadline (the smaller of the caller timeout and the profile timeout, never multiplied by the
    attempts; late replies are refused), and only a complete single-choice ``stop`` reply naming the exact model is accepted.
    The identity is revalidated before and after EVERY attempt and after the reply; the cached identity is dropped when the
    binding appears, changes or is removed, and any operational failure of the selected path is None, never a raised error.
    An invalid/unavailable explicit state yields None (label-only): never the configured fallback, never a legacy target."""
    import local_model_endpoint

    config = json.loads(config_path.read_text(encoding="utf-8"))
    reasoner = config["primary_reasoner"]
    configured = str(reasoner["base_url"]).rstrip("/")
    if urlsplit(configured).hostname not in ("127.0.0.1", "localhost", "::1"):
        raise ValueError("LOCAL_REASONER_NOT_LOOPBACK")
    opener = build_opener(ProxyHandler({}))
    endpoint: dict[str, Any] = {}  # {"mode": LEGACY|EXPLICIT, "digest", "chat", "model", "binding", "profile"}

    def forget() -> None:
        endpoint.clear()
        translate.model = None  # type: ignore[attr-defined]

    def target() -> bool:
        """Revalidates the shared intent on EVERY call; False means unavailable (no fallback of any kind)."""
        try:
            intent = local_model_endpoint.selected_intent()
        except Exception:  # finite boundary: any failure of the selected path is unavailable, never legacy
            forget()
            return False
        if intent["mode"] == "EXPLICIT_STRATA":
            if (endpoint.get("mode") != "EXPLICIT" or endpoint.get("digest") != intent["binding_sha256"]
                    or endpoint.get("profile_sha256") != intent["profile_sha256"]):
                forget()  # a legacy or previous identity never survives a new/changed binding
                try:
                    found = local_model_endpoint.resolve()  # selected-only metadata, identity rechecked inside
                except Exception:
                    return False
                if (not isinstance(found, dict) or found.get("mode") != "EXPLICIT_STRATA"
                        or found.get("binding_sha256") != intent["binding_sha256"]):
                    return False
                endpoint.update(mode="EXPLICIT", digest=intent["binding_sha256"], profile_sha256=intent["profile_sha256"],
                                model=intent["binding"]["model"], binding=intent["binding"], profile=intent["profile"])
                translate.model = endpoint["model"]  # type: ignore[attr-defined]
            return True
        if endpoint.get("mode") != "LEGACY":
            forget()  # an explicit identity never survives a removed binding
            found = (resolver or local_model_endpoint.resolve)(str(reasoner["model"]), configured)
            if found.get("mode") == "EXPLICIT_STRATA" or found.get("error") == "LOCAL_MODEL_BINDING_UNAVAILABLE":
                return False  # intent appeared meanwhile: unavailable, not the configured fallback
            if "error" in found:  # nothing answers: the configured target fails closed below
                endpoint.update(chat=configured + "/chat/completions", model=str(reasoner["model"]))
            else:
                endpoint.update(chat=found["base_url"] + "/v1/chat/completions", model=found["model"])
            endpoint["mode"] = "LEGACY"
            translate.model = endpoint["model"]  # type: ignore[attr-defined]
        return True

    def unchanged() -> bool:
        try:
            now = local_model_endpoint.selected_intent()
        except Exception:
            return False
        if endpoint.get("mode") == "EXPLICIT":  # same-byte unchanged intent is not a change
            return (now["mode"] == "EXPLICIT_STRATA" and now["binding_sha256"] == endpoint.get("digest")
                    and now["profile_sha256"] == endpoint.get("profile_sha256"))
        return now["mode"] == "LEGACY_ABSENT"

    def ask_explicit(sentence: str) -> str | None:
        try:
            import v213_model_profile as shared
        except Exception:
            return None
        binding, profile = endpoint["binding"], endpoint["profile"]
        thinking = profile["enable_thinking"]
        ceiling = profile["max_output_tokens"] if thinking else min(120, profile["max_output_tokens"])
        tries = min(max(1, attempts), 3)
        deadline = time.monotonic() + min(float(timeout), profile["timeout_ms"] / 1000)  # ONE budget for all attempts
        payload = {
            "model": binding["model"], "temperature": 0, "max_tokens": ceiling, "stream": False,
            "chat_template_kwargs": {"enable_thinking": thinking}, "reasoning_effort": profile["reasoning_effort"],
            "messages": [{"role": "system", "content": "你是財經翻譯。只輸出繁體中文（台灣用語，例如資料中心、客製化）譯文，不要解釋。"},
                         {"role": "user", "content": PROMPT + sentence}],
        }
        for _ in range(tries):
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            if not unchanged():  # identity BEFORE every POST: a removed/changed binding is never retried, old or new
                forget()
                return None
            try:
                reply = shared.binding_json_http(binding, "POST", "/v1/chat/completions", payload=payload,
                                                 timeout=remaining, max_bytes=65536)
            except Exception:
                reply = None
            if not unchanged():  # identity AFTER every return/failure, before a retry or content acceptance
                forget()
                return None
            if reply is None:
                continue
            if time.monotonic() >= deadline:
                return None  # a late reply is refused
            # Only the exact bound model may write the phrase (no silent substitution by the server).
            if not isinstance(reply, dict) or reply.get("model") != binding["model"]:
                return None
            try:
                choices = reply["choices"]
                content = choices[0]["message"]["content"]
                if len(choices) != 1 or choices[0].get("finish_reason") != "stop" or not isinstance(content, str):
                    continue
            except (KeyError, IndexError, TypeError, AttributeError):
                continue
            phrase = validate_phrase(content, sentence)
            if phrase:
                return phrase
        return None

    def translate(sentence: str) -> str | None:
        if not target():
            return None
        if endpoint["mode"] == "EXPLICIT":
            try:
                phrase = ask_explicit(sentence)
            except Exception:  # None boundary: an operational failure of the selected path never raises out of translate
                forget()
                return None
        else:
            phrase = ask_legacy(sentence)
        if phrase is not None and not unchanged():  # a binding appearing/changing/removed meanwhile voids the phrase
            forget()
            return None
        return phrase

    def ask_legacy(sentence: str) -> str | None:
        chat_url, model = endpoint["chat"], endpoint["model"]
        body = json.dumps({
            "model": model, "temperature": 0, "max_tokens": 120,
            "chat_template_kwargs": {"enable_thinking": False},
            "messages": [{"role": "system", "content": "你是財經翻譯。只輸出繁體中文（台灣用語，例如資料中心、客製化）譯文，不要解釋。"},
                         {"role": "user", "content": PROMPT + sentence}],
        }).encode("utf-8")
        for _ in range(max(1, attempts)):
            request = Request(chat_url, data=body, headers={"Content-Type": "application/json"}, method="POST")
            try:
                with opener.open(request, timeout=timeout) as response:
                    payload = json.loads(response.read())
                # Only the model found on the server may write the phrase (no silent substitution by the server).
                if payload.get("model") != model:
                    return None
                phrase = validate_phrase(str(payload["choices"][0]["message"]["content"] or ""), sentence)
            except Exception:
                phrase = None
            if phrase:
                return phrase
        return None

    translate.model = None  # type: ignore[attr-defined]
    return translate


def compose_industry(label: str, phrase: str | None) -> str:
    """「細分產業：主要業務」 within the Worker limit; the label alone when no phrase.

    「｜」 is the report column separator and is rejected by the Worker.
    """
    label = (label or "未分類").strip()
    if not phrase:
        return label[:MAX_INDUSTRY_CHARS]
    return f"{label}：{phrase}"[:MAX_INDUSTRY_CHARS]
