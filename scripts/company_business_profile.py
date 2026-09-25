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
EXTRACTOR_VERSION = 5  # cached sentences from another extractor are re-derived
SEC_HOSTS = ("data.sec.gov", "www.sec.gov")
MAX_DOCUMENT_BYTES = 40_000_000
SEC_MIN_INTERVAL_SECONDS = 0.25  # well inside SEC fair access (10 requests/second)
MAX_INDUSTRY_CHARS = 100  # Worker lineSafeText limit for the industry field
MAX_PHRASE_CHARS = 40
_HEADINGS = (
    re.compile(r"item\s*1\s*[.:\-–—]?\s*business\b", re.I),
    re.compile(r"item\s*4\s*[.:\-–—]?\s*information\s+on\s+the\s+company\b", re.I),
)
_SELF = re.compile(r"\b(?:is|are)\s+(?:a|an|the|one\s+of)\b", re.I)
_ACTIVITY = re.compile(r"\b(?:design|develop|manufactur|produc|provid|operat|offer|sell|make|suppl)\w*\b", re.I)
_ROLE_NOUN = re.compile(r"\b(?:company|leader|provider|manufacturer|developer|designer|supplier|maker|producer)\b", re.I)
_SKIP = re.compile(r"item\s*1a|forward-looking|table of contents|risk factors", re.I)
_OFF_TOPIC = re.compile(r"\b(?:committee|compensation|board of directors|we believe|see|form 10-k|form 20-f|"
                        r"annual report|shareholders?|stockholders?|employees|properties|party to|defendant|"
                        r"accounting firm|pcaob|audit\w*|demand is|demand for|fiscal year|"
                        r"incorporated|headquarter\w*|dividends?|subsidiar\w*|restrictions?|ability to)\b", re.I)
_OVERVIEW = re.compile(r"\b(?:Business Overview|Company Overview|Overview|Our Company)\b(?=\s+[A-Z])")
_LEAD = re.compile(r"^(?:overview|general|our company|business overview)\s+", re.I)
_CJK = re.compile(r"[一-鿿]")
_THINK = re.compile(r"<think>.*?</think>", re.S)
PROMPT = ("將以下英文公司業務描述濃縮翻譯為繁體中文業務片語（最多28字）：不要寫公司名稱，"
          "不要寫「全球」「領先」等形容，只寫公司做什麼與主要產品；不得加入原文沒有的資訊或數字。只輸出片語。\n")


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


def _self_patterns(entity_name: str | None, tickers: Sequence[str] = ()) -> tuple[re.Pattern[str], re.Pattern[str]]:
    """(sentence opens with the company as subject, strong self-description)."""
    words = re.findall(r"[A-Za-z0-9&]+", entity_name or "")
    names = [word for word in [*(words[:1]), *tickers] if isinstance(word, str) and len(word) >= 2]
    subjects = [r"\bwe", r"\bthe company", r"\bour company"]
    escaped = [r"\b" + re.escape(name) for name in names]
    lead = re.compile("(?:" + "|".join(escaped + subjects) + r")\b", re.I)
    named = [rf"\b{re.escape(name)}\b[\w.,&'’ -]{{0,40}}?" for name in names]
    own = re.compile(rf"(?:{'|'.join(named + subjects)})(?:,[^.]{{0,80}},)?\s+(?:is|are)\s+(?:now\s+|currently\s+|today\s+)?"
                     r"(?:a|an|the|one\s+of)\b", re.I)
    return lead, own


def _clip(sentence: str) -> str | None:
    """Long list sentences keep their first clauses (<=400 chars) instead of being lost."""
    if len(sentence) <= 400:
        return sentence
    cut = sentence[:400]
    boundary = max(cut.rfind(";"), cut.rfind(","))
    return cut[:boundary] if boundary >= 120 else None


def _score(sentence: str, lead: re.Pattern[str], own: re.Pattern[str]) -> tuple[int, str]:
    match = own.search(sentence)
    if match:
        sentence, score = sentence[match.start():], 5  # drop heading residue before the subject
    else:
        score = 2 if _SELF.search(sentence) else 0
        score += 1 if lead.match(sentence) else 0
    score += 2 if _ACTIVITY.search(sentence) else 0
    score += 1 if _ROLE_NOUN.search(sentence) else 0
    score -= 4 if _OFF_TOPIC.search(sentence) else 0
    return score, sentence


def _sentences(text: str, start: int, width: int):
    offset = start
    for raw in re.split(r"(?<=[.!?])\s+", text[start:start + width]):
        yield offset, raw.strip()
        offset += len(raw) + 1


def _best(text: str, windows: Sequence[int], lead: re.Pattern[str], own: re.Pattern[str], *, width: int,
          minimum: int, strong_only: bool = False) -> str | None:
    best: tuple[int, int, str] | None = None
    for start in windows:
        for offset, raw in _sentences(text, start, width):
            candidate = _clip(_LEAD.sub("", raw))
            if candidate is None or len(candidate) < 60 or _SKIP.search(candidate):
                continue
            if strong_only and not own.search(candidate):
                continue
            score, sentence = _score(candidate, lead, own)
            if len(sentence) >= 40 and score >= minimum and (best is None or (score, -offset) > (best[0], -best[1])):
                best = (score, offset, sentence)
    return best[2] if best else None


def _overview_excerpt(text: str, start: int, lead: re.Pattern[str]) -> str | None:
    """First 1-3 on-topic sentences after an Overview heading (<=600 chars)."""
    match = _OVERVIEW.search(text, start, start + 12000)
    if not match:
        return None
    parts: list[str] = []
    for _, raw in _sentences(text, match.end(), 3000):
        candidate = _clip(raw)
        if candidate is None or len(candidate) < 40 or _SKIP.search(candidate) or _OFF_TOPIC.search(candidate):
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
    else the Overview paragraph; else the best activity sentence; else, without a
    usable heading, a strong self-description anywhere in the report.
    """
    lead, own = _self_patterns(entity_name, tickers)
    windows = sorted(match.end() for heading in _HEADINGS for match in heading.finditer(text))
    found = _best(text, windows, lead, own, width=12000, minimum=6)
    for start in windows if found is None else ():
        found = _overview_excerpt(text, start, lead)
        if found:
            break
    found = found or _best(text, windows, lead, own, width=12000, minimum=3)
    return found or _best(text, [0], lead, own, width=600000, minimum=6, strong_only=True)


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
    if len(_CJK.findall(text)) < len(text) * 0.5:
        return None
    if not set(re.findall(r"\d", text)) <= set(re.findall(r"\d", sentence)):
        return None
    if any(banned in text for banned in _banned_phrases()):
        return None
    return text


def local_translator(config_path: Path = LOCAL_RUNTIME_CONFIG, *, timeout: float = 30.0) -> Callable[[str], str | None]:
    """Translator bound to the configured loopback reasoner; failures return None."""
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
        request = Request(base_url + "/chat/completions", data=body,
                          headers={"Content-Type": "application/json"}, method="POST")
        try:
            with opener.open(request, timeout=timeout) as response:
                payload = json.loads(response.read())
            return validate_phrase(str(payload["choices"][0]["message"]["content"] or ""), sentence)
        except Exception:
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
