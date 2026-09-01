#!/usr/bin/env python3
"""H6B1: full current Top 20 order/outlook population in shadow mode.

This stage uses the accepted H6A public-logic baseline, the installed v2.1.2
five-field Top 20, and evidence-bound public order/outlook sources to build a
seven-field preview. It does not deploy or send LINE messages.

The order layer is intentionally fail-closed:
- booked/contracted/backlog-like evidence is separated from pipeline/guidance;
- forward outlook is INFERENCE unless contractually committed;
- unsupported total order/revenue estimates are prohibited.
"""
from __future__ import annotations

import argparse
import copy
import html
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Mapping, Sequence

SCRIPT_DIR = Path(__file__).resolve().parent
ROOT = SCRIPT_DIR.parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import v213_top20_order_outlook_contract as contract

POLICY_PATH = ROOT / "config" / "v213-serenity-h6b-policy.json"
DISPLAY_COLUMNS = contract.DISPLAY_COLUMNS
H6A_SHA = "143a534d972429289ba17d79948bbccb6f106f9c"

TSEM_CONTRACTS = "https://ir.towersemi.com/news-releases/news-release-details/tower-semiconductor-signs-customer-contracts-13-billion-silicon/"
TSEM_EXPANSION = "https://towersemi.com/2026/07/14/07142026/"
COHR_NVIDIA = "https://www.coherent.com/news/press-releases/nvidia-and-coherent-announce-strategic-partnership"
COHR_FY26 = "https://www.coherent.com/news/press-releases/fourth-quarter-and-fiscal-year-2026-results"
SIVE_Q2 = "https://www.sivers-semiconductors.com/press/sivers-semiconductors-reports-q2-2026-results-as-product-growth-record-pipeline-and-customer-ramps-position-company-for-growth-acceleration/"
SIVE_CEO_Q2 = "https://www.sivers-semiconductors.com/2026/09/01/vickram-vathulyas-letter-to-shareholders-interim-report-q2-2026/"

CURRENT_FALLBACK = contract.NO_CURRENT_ORDERS
FUTURE_FALLBACK = contract.NO_FUTURE_ESTIMATE
AMOUNT_RE = re.compile(
    r"(?:(?:US|USD)\s*)?\$\s*\d[\d,.]*(?:\.\d+)?\s*(?:million|billion|m|b)?"
    r"|(?:USD|US\$)\s*\d[\d,.]*(?:\.\d+)?\s*(?:million|billion|m|b)?",
    re.I,
)
YEAR_RE = re.compile(r"\b20(?:26|27|28|29|30)\b")
SPACE_RE = re.compile(r"\s+")
FORM_PRIORITY = {"10-Q": 0, "10-K": 1, "8-K": 2, "20-F": 3, "6-K": 4}


class H6BError(RuntimeError):
    pass


class _VisibleTextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._skip = 0
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() in {"script", "style", "noscript", "svg"}:
            self._skip += 1

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() in {"script", "style", "noscript", "svg"} and self._skip:
            self._skip -= 1

    def handle_data(self, data: str) -> None:
        if not self._skip:
            text = SPACE_RE.sub(" ", data).strip()
            if text:
                self.parts.append(text)


def visible_text(payload: str) -> str:
    if "<" not in payload or ">" not in payload:
        return SPACE_RE.sub(" ", html.unescape(payload)).strip()
    parser = _VisibleTextParser()
    try:
        parser.feed(payload)
    except Exception:
        return SPACE_RE.sub(" ", html.unescape(re.sub(r"<[^>]+>", " ", payload))).strip()
    return SPACE_RE.sub(" ", " ".join(parser.parts)).strip()


def load_policy(path: Path = POLICY_PATH) -> dict[str, Any]:
    try:
        policy = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise H6BError(f"invalid H6B policy: {path}") from exc
    if policy.get("schema_version") != 1 or policy.get("product_version") != "2.1.3":
        raise H6BError("unexpected H6B policy schema/product")
    if policy.get("canonical_serenity_skill") != "skills/serenity-public-research/SKILL.md":
        raise H6BError("canonical Serenity skill is not pinned")
    if policy.get("legacy_fidelity_confidence_status") != "deprecated_do_not_use_for_downstream_decisions":
        raise H6BError("legacy fidelity confidence is not deprecated")
    if policy.get("order_fields", {}).get("numeric_total_order_estimate_prohibited") is not True:
        raise H6BError("order hallucination guard is not fail-closed")
    if policy.get("dependency_fail_closed", {}).get("hard_dependency_requires_independent_scarcity_or_effective_capacity_evidence") is not True:
        raise H6BError("hard dependency gate is not fail-closed")
    return policy


def _user_agent() -> str:
    email = str(os.environ.get("SEC_CONTACT_EMAIL") or "").strip()
    if email and "@" in email:
        return f"InvestorIntelligence/2.1.3 H6B public research {email}"
    return "InvestorIntelligence/2.1.3 H6B public research"


def fetch_raw(url: str, *, timeout: float = 20.0) -> str:
    headers = {
        "User-Agent": _user_agent(),
        "Accept": "text/html,application/json,text/plain,*/*",
        "Accept-Language": "en-US,en;q=0.8",
        "Cache-Control": "no-cache",
    }
    request = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            data = response.read(24 * 1024 * 1024 + 1)
            if len(data) > 24 * 1024 * 1024:
                raise H6BError(f"response too large: {url}")
            charset = response.headers.get_content_charset() or "utf-8"
            return data.decode(charset, errors="replace")
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise H6BError(f"fetch failed: {url}: {exc.__class__.__name__}") from exc


def fetch_text(url: str, *, timeout: float = 20.0) -> str:
    return visible_text(fetch_raw(url, timeout=timeout))


def _must(text: str, patterns: Sequence[str], label: str) -> None:
    if not all(re.search(pattern, text, re.I | re.S) for pattern in patterns):
        raise H6BError(f"required official evidence missing: {label}")


def _outlook(
    current: str,
    future: str,
    *,
    current_urls: Sequence[str] = (),
    future_urls: Sequence[str] = (),
    confidence: str,
    as_of: str,
    current_classification: str = "SUPPORTED",
    future_classification: str = "INFERENCE",
    evidence_status: str = "EVIDENCE_BOUND",
) -> dict[str, Any]:
    return {
        "current_orders_summary": current,
        "future_orders_estimate": future,
        "current_order_source_urls": list(dict.fromkeys(current_urls)),
        "future_order_source_urls": list(dict.fromkeys(future_urls)),
        "confidence": confidence,
        "as_of": as_of,
        "numeric_total_order_estimate_prohibited": True,
        "evidence_status": evidence_status,
        "claim_grounding": {
            "current_orders_summary": current_classification,
            "future_orders_estimate": future_classification,
        },
    }


def unavailable_outlook() -> dict[str, Any]:
    return _outlook(
        CURRENT_FALLBACK,
        FUTURE_FALLBACK,
        confidence="UNAVAILABLE",
        as_of="",
        current_classification="UNAVAILABLE",
        future_classification="UNAVAILABLE",
        evidence_status="UNAVAILABLE",
    )


def _h6a_row(h6a: Mapping[str, Any], ticker: str) -> dict[str, Any] | None:
    for row in h6a.get("results") or []:
        if isinstance(row, Mapping) and str(row.get("ticker") or "").upper() == ticker:
            return dict(row)
    return None


def axti_outlook(h6a: Mapping[str, Any]) -> dict[str, Any] | None:
    row = _h6a_row(h6a, "AXTI")
    if not row:
        return None
    block = row.get("h5_qualified_substitute_capacity")
    outlook = block.get("order_outlook") if isinstance(block, Mapping) else None
    if not isinstance(outlook, Mapping):
        return None
    urls = [str(url) for url in outlook.get("evidence_urls") or [] if str(url).startswith("https://")]
    current = str(outlook.get("current_orders_summary") or "").strip()
    future = str(outlook.get("future_orders_estimate") or "").strip()
    if len(urls) < 3 or not current or not future or outlook.get("numeric_total_order_estimate_prohibited") is not True:
        return None
    return _outlook(
        current,
        future,
        current_urls=urls,
        future_urls=urls,
        confidence="HIGH_FOR_CONTRACTED_VISIBILITY_NOT_TOTAL_REVENUE",
        as_of="2026-07-26",
        current_classification="SUPPORTED",
        future_classification="INFERENCE",
    )


def tsem_outlook(fetcher=fetch_text) -> dict[str, Any]:
    contracts = fetcher(TSEM_CONTRACTS)
    expansion = fetcher(TSEM_EXPANSION)
    _must(contracts, [r"\$1\.3\s+billion", r"2027\s+revenue", r"\$290\s+million", r"prepayments?", r"2028"], "TSEM contracted SiPho visibility")
    _must(expansion, [r"fourth quarter of 2027|Q4\s*2027", r"Silicon Photonics", r"accelerating customer demand"], "TSEM capacity/ramp outlook")
    return _outlook(
        "SiPho客戶合約對應2027收入US$13億；已收US$2.9億產能預付款",
        "2028契約晶圓承諾高於2027，另有追加預付款；新SiPho產能預計2027Q4就緒，不推估未揭露總額",
        current_urls=[TSEM_CONTRACTS],
        future_urls=[TSEM_CONTRACTS, TSEM_EXPANSION],
        confidence="HIGH_CONTRACTED",
        as_of="2026-07-14",
        current_classification="SUPPORTED",
        future_classification="SUPPORTED_AND_INFERENCE",
    )


def cohr_outlook(fetcher=fetch_text) -> dict[str, Any]:
    partnership = fetcher(COHR_NVIDIA)
    fy26 = fetcher(COHR_FY26)
    _must(partnership, [r"multiyear strategic agreement", r"multibillion-dollar purchase commitment", r"future access and capacity rights"], "COHR NVIDIA purchase commitment")
    _must(fy26, [r"exceptional customer demand", r"expanding production capacity", r"multiple new growth platforms.*ramp"], "COHR FY2027 demand/ramp outlook")
    return _outlook(
        "與NVIDIA多年非獨家協議含數十億美元採購承諾及未來先進雷射/光網路產能權利",
        "FY2027公司稱客戶需求強、持續擴產且多個新平台開始ramp；未揭露可可靠量化的總未來訂單",
        current_urls=[COHR_NVIDIA],
        future_urls=[COHR_NVIDIA, COHR_FY26],
        confidence="HIGH_CONTRACTED_AND_OFFICIAL_OUTLOOK",
        as_of="2026-08-12",
        current_classification="SUPPORTED",
        future_classification="INFERENCE",
    )


def sive_outlook(fetcher=fetch_text) -> dict[str, Any]:
    q2 = fetcher(SIVE_Q2)
    letter = fetcher(SIVE_CEO_Q2)
    _must(q2, [r"Pipeline grows to USD 1\.2 billion", r"USD 8\.2 m production order", r"2027 production ramp"], "SIVE Q2 orders/pipeline")
    _must(letter, [r"\$8\.2M production order", r"initial \$3M production order", r"initial \$3\.4M program order", r"anticipate production orders in H1 2027"], "SIVE Sep-1 order outlook")
    return _outlook(
        "已揭露production orders：ALL.SPACE US$8.2M、Tachyon初始US$3M、SemiNex初始US$3.4M；US$1.2B為opportunity pipeline、非已下單",
        "公司預期LiDAR客戶Q4'26/2027需求及Jabil H1'27 production orders；屬公司前瞻、非已簽總額",
        current_urls=[SIVE_Q2, SIVE_CEO_Q2],
        future_urls=[SIVE_CEO_Q2],
        confidence="HIGH_FOR_DISCLOSED_ORDERS_MEDIUM_FOR_FORWARD_OUTLOOK",
        as_of="2026-09-01",
        current_classification="SUPPORTED",
        future_classification="INFERENCE",
    )


def sec_ticker_map(fetcher=fetch_raw) -> dict[str, str]:
    raw = fetcher("https://www.sec.gov/files/company_tickers.json")
    try:
        doc = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise H6BError("SEC ticker map invalid JSON") from exc
    result: dict[str, str] = {}
    for item in doc.values() if isinstance(doc, Mapping) else []:
        if not isinstance(item, Mapping):
            continue
        ticker = str(item.get("ticker") or "").upper().strip()
        try:
            cik = f"{int(item.get('cik_str')):010d}"
        except (TypeError, ValueError):
            continue
        if ticker:
            result[ticker] = cik
    return result


def recent_filing_urls(ticker: str, cik: str, fetcher=fetch_raw) -> list[tuple[str, str, str]]:
    raw = fetcher(f"https://data.sec.gov/submissions/CIK{cik}.json")
    try:
        doc = json.loads(raw)
    except json.JSONDecodeError:
        return []
    recent = ((doc.get("filings") or {}).get("recent") or {}) if isinstance(doc, Mapping) else {}
    forms = recent.get("form") or []
    accessions = recent.get("accessionNumber") or []
    primary_docs = recent.get("primaryDocument") or []
    dates = recent.get("filingDate") or []
    rows: list[tuple[str, str, str, int]] = []
    for form, accession, primary, date in zip(forms, accessions, primary_docs, dates):
        form = str(form)
        if form not in FORM_PRIORITY:
            continue
        accession_clean = str(accession).replace("-", "")
        primary = str(primary)
        date = str(date)
        if not accession_clean or not primary:
            continue
        url = f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{accession_clean}/{primary}"
        rows.append((url, date, form, FORM_PRIORITY[form]))
        if len(rows) >= 12:
            break
    rows.sort(key=lambda x: (x[1], -x[3]), reverse=True)
    return [(url, date, form) for url, date, form, _ in rows[:5]]


def _sentence_windows(text: str) -> list[str]:
    chunks = re.split(r"(?<=[.!?])\s+|\s{2,}", text)
    return [SPACE_RE.sub(" ", chunk).strip() for chunk in chunks if 30 <= len(chunk.strip()) <= 1500]


def _amount_in(text: str) -> str | None:
    match = AMOUNT_RE.search(text)
    return SPACE_RE.sub(" ", match.group(0)).strip() if match else None


def generic_sec_outlook(ticker: str, cik_map: Mapping[str, str], raw_fetcher=fetch_raw, text_fetcher=fetch_text) -> dict[str, Any]:
    cik = cik_map.get(ticker.upper())
    if not cik:
        return unavailable_outlook()
    candidates = recent_filing_urls(ticker, cik, fetcher=raw_fetcher)
    best: tuple[int, str, str, str, str] | None = None
    future_hint: tuple[str, str] | None = None
    labels = [
        (0, "剩餘履約義務", re.compile(r"remaining performance obligations?", re.I)),
        (1, "backlog", re.compile(r"\bbacklog\b", re.I)),
        (2, "order book", re.compile(r"\border book\b", re.I)),
        (3, "production order", re.compile(r"\bproduction orders?\b", re.I)),
        (4, "bookings", re.compile(r"\bbookings\b", re.I)),
    ]
    for url, filing_date, form in candidates:
        try:
            text = text_fetcher(url)
        except H6BError:
            continue
        for sentence in _sentence_windows(text):
            amount = _amount_in(sentence)
            if not amount:
                continue
            lower = sentence.lower()
            if "purchase obligation" in lower and not re.search(r"customer.{0,80}(order|commitment|prepay|reservation)", lower):
                continue
            for priority, label, pattern in labels:
                if pattern.search(sentence):
                    if re.search(r"\b(if|may|could|might)\b.{0,80}" + pattern.pattern, sentence, re.I):
                        continue
                    candidate = (priority, filing_date, label, amount, url)
                    if best is None or candidate[0] < best[0] or (candidate[0] == best[0] and candidate[1] > best[1]):
                        best = candidate
                    years = [y for y in YEAR_RE.findall(sentence) if y >= "2026"]
                    if years:
                        future_hint = (max(years), url)
                    break
        time.sleep(0.05)
    if best is None:
        return unavailable_outlook()
    priority, filing_date, label, amount, url = best
    current = f"官方文件揭露{label}約{amount}（{filing_date}）；未以其他來源補估總額"
    if future_hint:
        year, future_url = future_hint
        future = f"官方訂單/履約語境延伸至{year}；僅作能見度判斷，不推估未揭露總額"
        future_urls = [future_url]
        future_class = "INFERENCE"
    else:
        future = FUTURE_FALLBACK
        future_urls = []
        future_class = "UNAVAILABLE"
    return _outlook(
        current,
        future,
        current_urls=[url],
        future_urls=future_urls,
        confidence="MEDIUM_GENERIC_SEC_EXPLICIT_ORDER_METRIC",
        as_of=filing_date,
        current_classification="SUPPORTED",
        future_classification=future_class,
    )


def order_outlook_for_ticker(ticker: str, h6a: Mapping[str, Any], cik_map: Mapping[str, str], *, fetcher=fetch_text, raw_fetcher=fetch_raw) -> dict[str, Any]:
    ticker = ticker.upper()
    try:
        if ticker == "AXTI":
            known = axti_outlook(h6a)
            if known:
                return known
        if ticker == "TSEM":
            return tsem_outlook(fetcher)
        if ticker == "COHR":
            return cohr_outlook(fetcher)
        if ticker in {"SIVE", "SIVEF"}:
            return sive_outlook(fetcher)
    except H6BError:
        pass
    return generic_sec_outlook(ticker, cik_map, raw_fetcher=raw_fetcher, text_fetcher=fetcher)


def reconcile_methodology(h6a: Mapping[str, Any]) -> dict[str, Any]:
    rows = copy.deepcopy(list(h6a.get("results") or []))
    changes: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        row["legacy_fidelity_confidence_deprecated"] = True
        ticker = str(row.get("ticker") or "").upper()
        h6 = row.setdefault("h6_logic_refinement", {})
        split = h6.setdefault("financing_operating_split", {})
        if ticker == "SIVE":
            signals = row.get("supported_signals") or {}
            capture = (row.get("public_logic_fidelity") or {}).get("company_capture") or {}
            gf_edges = int(row.get("independent_graph_edge_count") or 0)
            if "customer_named_ramp" in (signals.get("commercial_validation") or []) and str(capture.get("state") or "") == "POSITIVE" and gf_edges >= 1:
                old = str(split.get("operating_thesis_state") or "")
                split["operating_thesis_state"] = "COMMERCIAL_VALIDATION"
                split["combined_research_state"] = "OPERATING_THESIS_WITH_MATERIAL_FINANCING_OVERHANG"
                split["h6b_reason"] = "official customer production-ramp evidence and independent GF linkage support commercial validation of the operating axis; dependency remains BENEFICIARY/UNPROVEN"
                changes.append({
                    "ticker": "SIVE",
                    "kind": "operating_axis_reconciled",
                    "from": old,
                    "to": "COMMERCIAL_VALIDATION",
                    "dependency_role_preserved": (row.get("public_logic_fidelity") or {}).get("dependency_role"),
                })
    return {
        "canonical_serenity_skill": "skills/serenity-public-research/SKILL.md",
        "legacy_serenity_skill": "skills/serenity-bottleneck.md",
        "legacy_fidelity_confidence_deprecated": True,
        "archetype_results": rows,
        "changes": changes,
    }


def verify_h6a(h6a: Mapping[str, Any], policy: Mapping[str, Any]) -> dict[str, Any]:
    summary = h6a.get("summary") or {}
    if int(summary.get("completed") or 0) != 7 or int(summary.get("failed") or -1) != 0:
        raise H6BError("H6A baseline is not 7/7 PASS")
    if int(summary.get("hard_dependency_count") or -1) != 0 or bool(summary.get("production_ranking_changed")):
        raise H6BError("H6A baseline violates hard-dependency/production guard")
    attestation = h6a.get("h6_source_history_attestation") or {}
    checkpoint = policy["h6a_source_history_checkpoint"]
    if int(attestation.get("entries") or 0) != int(checkpoint["entries"]) or str(attestation.get("latest_hash") or "") != str(checkpoint["latest_hash"]) or attestation.get("structural_chain_verified") is not True:
        raise H6BError("H6A source-history checkpoint mismatch")
    return {"entries": int(attestation["entries"]), "latest_hash": str(attestation["latest_hash"]), "structural_chain_verified": True}


def verify_v212(v212: Mapping[str, Any]) -> list[dict[str, Any]]:
    records = v212.get("records")
    if v212.get("product_version") != "2.1.2" or not isinstance(records, list) or len(records) != 20:
        raise H6BError("installed v2.1.2 Top20 report is not accepted 20-row input")
    expected = ["股票", "長期投資報酬率（近2年年化）", "短期投資報酬率（近6個月）", "行業別", "獲利簡述"]
    if list(v212.get("display_columns") or []) != expected:
        raise H6BError("installed v2.1.2 display contract changed")
    rows = [dict(row) for row in records]
    for index, row in enumerate(rows, start=1):
        if int(row.get("rank") or 0) != index:
            raise H6BError("v2.1.2 rank order mismatch")
    return rows


def build(h6a: Mapping[str, Any], v212: Mapping[str, Any], *, fetcher=fetch_text, raw_fetcher=fetch_raw) -> dict[str, Any]:
    policy = load_policy()
    checkpoint = verify_h6a(h6a, policy)
    base_rows = verify_v212(v212)
    try:
        cik_map = sec_ticker_map(fetcher=raw_fetcher)
    except H6BError:
        cik_map = {}

    rows: list[dict[str, Any]] = []
    supported = inferred = unavailable = 0
    for base_row in base_rows:
        ticker = str(base_row.get("ticker") or "").upper()
        outlook = order_outlook_for_ticker(ticker, h6a, cik_map, fetcher=fetcher, raw_fetcher=raw_fetcher)
        normalized = contract.seven_field_record(base_row, outlook)
        normalized["orders_evidence_status"] = outlook.get("evidence_status")
        normalized["orders_claim_grounding"] = outlook.get("claim_grounding")
        rows.append(normalized)
        current_class = str((outlook.get("claim_grounding") or {}).get("current_orders_summary") or "")
        future_class = str((outlook.get("claim_grounding") or {}).get("future_orders_estimate") or "")
        if current_class == "SUPPORTED":
            supported += 1
        else:
            unavailable += 1
        if future_class in {"INFERENCE", "SUPPORTED_AND_INFERENCE", "SUPPORTED"}:
            inferred += 1

    contract.validate_records(rows)
    methodology = reconcile_methodology(h6a)
    for row in methodology["archetype_results"]:
        role = str((row.get("public_logic_fidelity") or {}).get("dependency_role") or "")
        if role in {"SINGLE_SOURCE", "SEMI_MONOPOLY", "QUALIFICATION_CONSTRAINED", "CAPACITY_BOTTLENECK"}:
            raise H6BError(f"unexpected hard dependency promotion in H6B1: {row.get('ticker')}")

    return {
        "schema_version": 1,
        "product_version": "2.1.3",
        "mode": "H6B1_FULL_TOP20_ORDER_OUTLOOK_SHADOW_ONLY",
        "base_h6a_sha": H6A_SHA,
        "production_ranking_changed": False,
        "line_delivery_performed": False,
        "display_columns": DISPLAY_COLUMNS,
        "records": rows,
        "order_population_summary": {
            "rows": len(rows),
            "current_order_supported_rows": supported,
            "current_order_unavailable_rows": unavailable,
            "future_order_evidence_bound_rows": inferred,
            "all_rows_explicitly_populated": len(rows) == 20,
            "numeric_total_order_estimate_prohibited": True,
        },
        "methodology_reconciliation": methodology,
        "source_history_checkpoint": {
            **checkpoint,
            "cross_run_checkpoint_available": True,
            "h6b1_does_not_append_source_views": True,
        },
        "next_stage": "H6B2_REAL_LINE_SEVEN_FIELD_TEST_PUSH",
    }


def self_test() -> None:
    policy = load_policy()
    assert policy["canonical_serenity_skill"].endswith("SKILL.md")
    assert policy["legacy_fidelity_confidence_status"].startswith("deprecated")
    h6a = {
        "summary": {"completed": 7, "failed": 0, "hard_dependency_count": 0, "production_ranking_changed": False},
        "h6_source_history_attestation": {"entries": 4, "latest_hash": "3b1e34fdd385ec3816a4f60a9f803cd1a3f64d2899cdc81c49e4cf5f36ed8102", "structural_chain_verified": True},
        "results": [{
            "ticker": "SIVE",
            "supported_signals": {"commercial_validation": ["customer_named_ramp"]},
            "public_logic_fidelity": {"company_capture": {"state": "POSITIVE"}, "dependency_role": "BENEFICIARY"},
            "independent_graph_edge_count": 1,
            "h6_logic_refinement": {"financing_operating_split": {"operating_thesis_state": "INSUFFICIENT_EVIDENCE", "financing_severity": "MATERIAL_OVERHANG"}},
        }],
    }
    method = reconcile_methodology(h6a)
    sive = method["archetype_results"][0]
    assert sive["h6_logic_refinement"]["financing_operating_split"]["operating_thesis_state"] == "COMMERCIAL_VALIDATION"
    assert sive["public_logic_fidelity"]["dependency_role"] == "BENEFICIARY"

    def fake_fetch(url: str) -> str:
        if url == TSEM_CONTRACTS:
            return "$1.3 billion for 2027 revenue; $290 million customer prepayments; larger contractual wafer commitment for 2028"
        if url == TSEM_EXPANSION:
            return "Silicon Photonics capacity supports accelerating customer demand; full production readiness expected during the fourth quarter of 2027"
        if url == COHR_NVIDIA:
            return "multiyear strategic agreement with a multibillion-dollar purchase commitment and future access and capacity rights"
        if url == COHR_FY26:
            return "exceptional customer demand, expanding production capacity, and multiple new growth platforms beginning to ramp"
        if url == SIVE_Q2:
            return "Pipeline grows to USD 1.2 billion; USD 8.2 m production order; supporting a 2027 production ramp"
        if url == SIVE_CEO_Q2:
            return "$8.2M production order; initial $3M production order; initial $3.4M program order; anticipate production orders in H1 2027"
        raise AssertionError(url)

    assert "US$13億" in tsem_outlook(fake_fetch)["current_orders_summary"]
    assert "數十億美元" in cohr_outlook(fake_fetch)["current_orders_summary"]
    assert "US$8.2M" in sive_outlook(fake_fetch)["current_orders_summary"]
    sample = contract.seven_field_record({"rank": 1, "ticker": "TEST", "long_term_return_pct": 1.0, "short_term_return_pct": 2.0, "industry": "半導體", "profit_summary": "獲利"}, unavailable_outlook())
    assert sample["current_orders"] == CURRENT_FALLBACK
    assert sample["future_orders_estimate"] == FUTURE_FALLBACK
    assert sample["numeric_total_order_estimate_prohibited"] is True
    print("V213_H6B1_FULL_TOP20_SELF_TEST = PASS")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--h6a-report", type=Path)
    parser.add_argument("--v212-report", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--preview", type=Path)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return 0
    if not args.h6a_report or not args.v212_report or not args.output or not args.preview:
        parser.error("--h6a-report, --v212-report, --output and --preview are required")
    h6a = json.loads(args.h6a_report.read_text(encoding="utf-8-sig"))
    v212 = json.loads(args.v212_report.read_text(encoding="utf-8-sig"))
    document = build(h6a, v212)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.preview.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(document, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    args.preview.write_text(contract.render(document["records"]) + "\n", encoding="utf-8")
    print(json.dumps({
        "status": "PASS",
        "output": str(args.output),
        "preview": str(args.preview),
        "rows": len(document["records"]),
        "current_order_supported_rows": document["order_population_summary"]["current_order_supported_rows"],
        "future_order_evidence_bound_rows": document["order_population_summary"]["future_order_evidence_bound_rows"],
        "production_ranking_changed": False,
        "line_delivery_performed": False,
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
