#!/usr/bin/env python3
"""Company business profile for the Top20 industry field (operator rule 2026-09-25).

The industry field must say what the company actually does. The English business
sentence is taken verbatim from Item 1 (10-K) or Item 4 (20-F) of the latest annual
report on SEC EDGAR; the Chinese phrase is a local-model translation of that one
sentence, validated against it. Without a valid translation the caller keeps its
classification label. No cloud model, paid service or invented description.
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


def _read_cache(path: Path) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return value if isinstance(value, dict) else None


def _write_cache(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(prefix=path.name, suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(handle, "w", encoding="utf-8", newline="\n") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2, sort_keys=True)
        os.replace(temporary, path)
    except OSError:
        try:
            os.unlink(temporary)
        except OSError:
            pass


def resolve_business_profile(cik: str, fetch: Callable[[str], bytes], translate: Callable[[str], str | None] | None,
                             *, cache_root: Path = CACHE_ROOT, now: Callable[[], str] = _utc_now) -> dict[str, Any] | None:
    """Current profile: the filing index is re-read every run; the annual document
    and its validated translation are reused only for the same accession."""
    if not re.fullmatch(r"\d{10}", str(cik)):
        raise ValueError("BUSINESS_PROFILE_CIK_INVALID")
    raw_index = fetch(f"https://data.sec.gov/submissions/CIK{cik}.json")
    checked_at = now()
    submissions = json.loads(raw_index)
    filing = latest_annual_filing(submissions, cik)
    if filing is None:
        return None
    path = cache_root / f"CIK{cik}.json"
    cached = _read_cache(path)
    if (cached and cached.get("accession") == filing["accession"] and cached.get("url") == filing["url"]
            and cached.get("extractor_version") == EXTRACTOR_VERSION
            and isinstance(cached.get("sentence_en"), str) and re.fullmatch(r"[0-9a-f]{64}", str(cached.get("document_sha256")))):
        record = {key: cached[key] for key in ("cik", "sic", "sic_description", "form", "filed", "accession", "url",
                                               "document_sha256", "document_retrieved_at", "sentence_en") if key in cached}
        phrase = validate_phrase(str(cached.get("phrase_zh") or ""), record["sentence_en"])
    else:
        raw = fetch(filing["url"])
        sentence = business_sentence(business_text(raw), submissions.get("name"), submissions.get("tickers") or ())
        if sentence is None:
            return None
        record = {"cik": cik, "sic": submissions.get("sic"), "sic_description": submissions.get("sicDescription"),
                  **filing, "document_sha256": hashlib.sha256(raw).hexdigest(), "document_retrieved_at": now(),
                  "sentence_en": sentence}
        phrase = None
    if phrase is None and translate is not None:
        phrase = validate_phrase(translate(record["sentence_en"]) or "", record["sentence_en"])
    _write_cache(path, {**record, "extractor_version": EXTRACTOR_VERSION, **({"phrase_zh": phrase} if phrase else {})})
    evidence = hashlib.sha256(json.dumps({"document_sha256": record["document_sha256"],
                                          "index_sha256": hashlib.sha256(raw_index).hexdigest()},
                                         sort_keys=True).encode("utf-8")).hexdigest()
    return {**record, "retrieved_at": checked_at, "evidence_sha256": evidence, "phrase_zh": phrase,
            "translation": "LOCAL_MODEL_TRANSLATION_OF_SOURCE_SENTENCE" if phrase else "UNAVAILABLE"}


def _banned_phrases() -> tuple[str, ...]:
    try:
        return tuple(json.loads(WORDING_POLICY.read_text(encoding="utf-8"))["banned_phrases_zh"])
    except (OSError, ValueError, KeyError):
        return ()


def validate_phrase(phrase: str, sentence: str) -> str | None:
    """Accept only a short Traditional-Chinese phrase that adds no numbers or vague wording."""
    text = _THINK.sub("", phrase or "").strip().strip("「」\"'").rstrip("。.").strip()
    if not 4 <= len(text) <= MAX_PHRASE_CHARS or any(mark in text for mark in ("\n", "\r", "｜")):
        return None
    if len(_CJK.findall(text)) < len(text) * 0.5 or any(char in _SIMPLIFIED for char in text):
        return None
    if not set(re.findall(r"\d", text)) <= set(re.findall(r"\d", sentence)):
        return None
    if any(banned in text for banned in _banned_phrases()) or _VAGUE_QUANTITY.search(text):
        return None
    return text


def local_translator(config_path: Path = LOCAL_RUNTIME_CONFIG, *, timeout: float = 60.0,
                     attempts: int = 2) -> Callable[[str], str | None]:
    """Translator bound to the configured loopback reasoner; failures return None.

    The GPU lane is shared, so a timed-out or rejected answer is asked once more
    (2026-09-25: 5 of 20 Top20 translations were lost to transient timeouts)."""
    config = json.loads(config_path.read_text(encoding="utf-8"))
    reasoner = config["primary_reasoner"]
    base_url = str(reasoner["base_url"]).rstrip("/")
    if urlsplit(base_url).hostname not in ("127.0.0.1", "localhost", "::1"):
        raise ValueError("LOCAL_REASONER_NOT_LOOPBACK")
    opener = build_opener(ProxyHandler({}))

    def translate(sentence: str) -> str | None:
        body = json.dumps({
            "model": reasoner["model"], "temperature": 0, "max_tokens": 120,
            "chat_template_kwargs": {"enable_thinking": False},
            "messages": [{"role": "system", "content": "你是財經翻譯。只輸出繁體中文譯文，不要解釋。"},
                         {"role": "user", "content": PROMPT + sentence}],
        }).encode("utf-8")
        for _ in range(max(1, attempts)):
            request = Request(base_url + "/chat/completions", data=body,
                              headers={"Content-Type": "application/json"}, method="POST")
            try:
                with opener.open(request, timeout=timeout) as response:
                    payload = json.loads(response.read())
                # Only the configured exact model may write the phrase (no silent model substitution).
                if payload.get("model") != reasoner["model"]:
                    return None
                phrase = validate_phrase(str(payload["choices"][0]["message"]["content"] or ""), sentence)
            except Exception:
                phrase = None
            if phrase:
                return phrase
        return None

    return translate


def compose_industry(label: str, phrase: str | None) -> str:
    """「細分產業：主要業務」 within the Worker limit; the label alone when no phrase.

    「｜」 is the report column separator and is rejected by the Worker.
    """
    label = (label or "未分類").strip()
    if not phrase:
        return label[:MAX_INDUSTRY_CHARS]
    return f"{label}：{phrase}"[:MAX_INDUSTRY_CHARS]
