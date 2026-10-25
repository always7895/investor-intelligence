#!/usr/bin/env python3
"""Strict independent public universe identity discovery and coverage ledger.

This module provides opt-in, offline discovery of listed issuer and security
identities from official public listing reference datasets (NASDAQ, Other US,
and TWSE).

Boundaries and non-negotiables:
- Lead identity evidence ONLY. Not company-level facts, market growth,
  chokepoint pricing power, revenue capture, or ranking proof.
- Partial coverage MUST NOT be described as full market coverage. Explicitly
  reports observed active venues vs configured coverage gaps.
- Stable (venue, symbol) deduplication only. Never merge share classes or ADRs
  by normalized name. Preserves leading zeros (TWSE) and official Chinese names.
- Documented ETF and TestIssue flags are excluded; preferred/warrants/units/funds
  are flagged REVIEW_REQUIRED, never silently classified as common equity.
- Conflicting duplicate identity rows are quarantined for review, never silently
  deduplicated via first-wins.
- No network access at import or runtime; validates collection SHA256 receipts
  against expected official URLs and rejects credentialed or unknown endpoints.
- Name similarity leads are explicitly unverified; authoritative issuer linkage
  requires CIK/LEI/ISIN relations from admitted sources, absent in listing feeds.
- All outputs DISCOVERY_ONLY, NOT_PUBLICATION_QUALIFIED; score=null, rank=null,
  admitted_company_count=0.
"""
from __future__ import annotations

import argparse
import dataclasses
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import sys
from typing import Any, Mapping

SCHEMA_VERSION = 1
MAX_COLLECTION_FILES = 10
MAX_RECORD_BOUND_DEFAULT = 100_000
MAX_FILE_BYTES = 50 * 1024 * 1024  # 50 MB bound per listing file

# Expected fixed official receipt URLs for source validation (fail-closed against unknown publishers)
EXPECTED_OFFICIAL_URLS: dict[str, str] = {
    "nasdaq-listed": "https://www.nasdaqtrader.com/dynamic/SymDir/nasdaqlisted.txt",
    "other-us-listed": "https://www.nasdaqtrader.com/dynamic/SymDir/otherlisted.txt",
    "twse-listed": "https://openapi.twse.com.tw/v1/opendata/t187ap03_L",
}

ALLOWLISTED_SOURCE_IDS: frozenset[str] = frozenset(EXPECTED_OFFICIAL_URLS.keys())
ALLOWLISTED_BASENAMES: frozenset[str] = frozenset(
    {f"{sid}.json" for sid in ALLOWLISTED_SOURCE_IDS} | {"receipts.json"}
)

# Canonical venue mappings for Other US listings (Exchange field)
OTHER_US_EXCHANGE_MAP: dict[str, str] = {
    "A": "NYSE American",
    "N": "NYSE",
    "P": "NYSE Arca",
    "Z": "Cboe BZX",
    "V": "IEX",
}

# Recognized Nasdaq market category codes
NASDAQ_MARKET_CATEGORIES: dict[str, str] = {
    "Q": "Nasdaq Global Select Market",
    "G": "Nasdaq Global Market",
    "S": "Nasdaq Capital Market",
}

# Configured / supported venues in code
ALL_CONFIGURED_VENUES: tuple[dict[str, str], ...] = (
    {"venue": "NASDAQ", "jurisdiction": "US", "feed": "nasdaq-listed", "scope": "PARTIAL_US_EQUITIES"},
    {"venue": "NYSE", "jurisdiction": "US", "feed": "other-us-listed", "scope": "PARTIAL_US_EQUITIES"},
    {"venue": "NYSE American", "jurisdiction": "US", "feed": "other-us-listed", "scope": "PARTIAL_US_EQUITIES"},
    {"venue": "NYSE Arca", "jurisdiction": "US", "feed": "other-us-listed", "scope": "PARTIAL_US_EQUITIES"},
    {"venue": "Cboe BZX", "jurisdiction": "US", "feed": "other-us-listed", "scope": "PARTIAL_US_EQUITIES"},
    {"venue": "IEX", "jurisdiction": "US", "feed": "other-us-listed", "scope": "PARTIAL_US_EQUITIES"},
    {"venue": "TWSE", "jurisdiction": "TW", "feed": "twse-listed", "scope": "PARTIAL_TAIWAN_EQUITIES"},
)

# Uncovered markets and asset classes that must be explicitly acknowledged
UNCOVERED_REGIONS_AND_ASSETS: tuple[str, ...] = (
    "EUROPE_EXCHANGES_LSE_EURONEXT_XETRA_SIX",
    "JAPAN_JPX_TSE",
    "HONG_KONG_HKEX",
    "KOREA_KRX",
    "CANADA_TSX_TSXV",
    "CHINA_SSE_SZSE",
    "US_OTC_PINK_SHEETS",
    "TAIWAN_TPEX_TAIPEI_EXCHANGE_EMERGING_STOCK_BOARD",
    "GLOBAL_FIXED_INCOME_AND_BONDS",
    "COMMODITIES_AND_DERIVATIVES",
    "PRIVATE_EQUITY_AND_UNLISTED_CORPORATIONS",
)

# Forbidden private data keys to guard against leakage
FORBIDDEN_PRIVATE_KEYS: frozenset[str] = frozenset({
    "tenant_id",
    "raw_line_id",
    "line_user_id",
    "line_group_id",
    "line_room_id",
    "account_id",
    "accountid",
    "cost_basis",
    "average_price",
    "position_shares",
    "exact_quantity",
    "conversation",
    "message_text",
    "private_prompt",
    "private_portfolio",
})

# Patterns for non-common-stock security classification
_RE_PREFERRED = re.compile(
    r"(?:\bpreferred\b|\bpfd\b|%\s*pr\b|\bseries\s+[a-z0-9]+\s+pref|\bpr[a-z]?\b|\b特別股\b)",
    re.IGNORECASE,
)
_RE_WARRANT = re.compile(
    r"(?:\bwarrant\b|\bwarrants\b|\bwt\b|\bwts\b|\b認購權證\b|\b認售權證\b)",
    re.IGNORECASE,
)
_RE_UNIT = re.compile(r"(?:\bunits?\b|\bunt\b)", re.IGNORECASE)
_RE_RIGHTS = re.compile(r"(?:\brights?\b|\brts?\b)", re.IGNORECASE)
_RE_FUND_OR_DEBT = re.compile(
    r"(?:\bnotes?\b|\bdebentures?\b|\bsenior\s+notes?\b|\bfloating\s+rate\b|\bsubordinated\b|\bindex\s+fund\b|\b受益憑證\b)",
    re.IGNORECASE,
)
_RE_ADR = re.compile(
    r"(?:\bamerican\s+depositary\s+shares?\b|\bads\b|\badr\b|\bdepositary\s+shares?\b)",
    re.IGNORECASE,
)


class DiscoveryValidationError(ValueError):
    """Raised when collection files, schema or integrity checks fail."""


@dataclass(frozen=True)
class DiscoveredSecurity:
    venue: str
    symbol: str
    security_name: str
    security_class: str
    status: str
    source_feed: str
    jurisdiction: str
    issuer_name_lead: str
    exclusion_reason: str | None = None
    review_reasons: tuple[str, ...] = ()
    feed_metadata: dict[str, Any] = dataclasses.field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "venue": self.venue,
            "symbol": self.symbol,
            "security_name": self.security_name,
            "security_class": self.security_class,
            "status": self.status,
            "source_feed": self.source_feed,
            "jurisdiction": self.jurisdiction,
            "issuer_name_lead": self.issuer_name_lead,
            "exclusion_reason": self.exclusion_reason,
            "review_reasons": list(self.review_reasons),
            "feed_metadata": dict(self.feed_metadata),
        }


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


def _is_symlink_or_junction_or_reparse(path: Path) -> bool:
    try:
        if path.is_symlink() or os.path.islink(path):
            return True
        if hasattr(os.path, "isjunction") and os.path.isjunction(path):
            return True
        if hasattr(path, "is_junction") and path.is_junction():
            return True
        if sys.platform == "win32":
            st = os.lstat(path)
            attrs = getattr(st, "st_file_attributes", 0)
            if attrs & 0x0400:  # FILE_ATTRIBUTE_REPARSE_POINT
                return True
            reparse_tag = getattr(st, "st_reparse_tag", 0)
            if reparse_tag != 0:
                return True
    except OSError:
        pass
    return False


def _check_no_symlink(path: Path) -> None:
    current = path.absolute()
    visited: set[Path] = set()
    while current not in visited:
        visited.add(current)
        if _is_symlink_or_junction_or_reparse(current):
            raise DiscoveryValidationError(
                f"Symlinks, junctions, or reparse points rejected in path or ancestor: {current.name or current}"
            )
        parent = current.parent
        if parent == current:
            break
        current = parent


def _validate_regular_file_bounds(path: Path, max_bytes: int = MAX_FILE_BYTES) -> None:
    _check_no_symlink(path)
    if not path.exists():
        raise DiscoveryValidationError(f"File does not exist: {path.name}")
    if not path.is_file():
        raise DiscoveryValidationError(f"Path is not a regular file: {path.name}")
    try:
        size = path.stat().st_size
    except OSError as err:
        raise DiscoveryValidationError(f"Cannot stat file: {err.__class__.__name__}") from None
    if size > max_bytes:
        raise DiscoveryValidationError(
            f"File size {size} exceeds maximum bound {max_bytes} bytes: {path.name}"
        )


def _validate_receipt_url(source_id: str, url: str) -> None:
    if not isinstance(url, str) or not url.strip():
        raise DiscoveryValidationError(f"Missing URL for source {source_id}")
    # Fail closed on credentialed URLs
    if re.search(r"//[^/@]+@", url):
        raise DiscoveryValidationError(f"Credentialed URLs forbidden: {source_id}")
    expected = EXPECTED_OFFICIAL_URLS.get(source_id)
    if not expected:
        raise DiscoveryValidationError(f"Unrecognized source ID: {source_id}")
    if url.strip() != expected:
        raise DiscoveryValidationError(
            f"Source URL mismatch for {source_id}: publisher URL not in expected official mapping"
        )


def validate_collection_directory(collection_dir: Path) -> dict[str, Any]:
    """Validate collection directory ownership, receipt SHA integrity, and file bounds."""
    _check_no_symlink(collection_dir)
    if not collection_dir.exists():
        raise DiscoveryValidationError(f"Collection directory does not exist: {collection_dir.name}")
    if not collection_dir.is_dir():
        raise DiscoveryValidationError(f"Collection path is not a directory: {collection_dir.name}")

    receipts_path = collection_dir / "receipts.json"
    _validate_regular_file_bounds(receipts_path)

    all_entries = list(collection_dir.iterdir())
    if len(all_entries) > MAX_COLLECTION_FILES:
        raise DiscoveryValidationError(
            f"Collection directory contains {len(all_entries)} files, exceeding limit {MAX_COLLECTION_FILES}"
        )

    for entry in all_entries:
        _check_no_symlink(entry)
        if entry.is_dir():
            raise DiscoveryValidationError(f"Subdirectories forbidden in collection: {entry.name}")

    try:
        receipts_data = json.loads(receipts_path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise DiscoveryValidationError(f"Failed to parse receipts.json: {exc.__class__.__name__}") from None

    if not isinstance(receipts_data, dict) or "sources" not in receipts_data:
        raise DiscoveryValidationError("receipts.json must contain a top-level 'sources' list")

    sources = receipts_data["sources"]
    if not isinstance(sources, list):
        raise DiscoveryValidationError("'sources' in receipts.json must be a list")

    receipt_sources_info: list[dict[str, Any]] = []
    for s in sources:
        if not isinstance(s, dict) or "source" not in s:
            raise DiscoveryValidationError("Source receipt entry missing 'source' identifier")
        source_id = s["source"]
        if source_id not in ALLOWLISTED_SOURCE_IDS:
            raise DiscoveryValidationError(f"Source ID not in allowlist: {source_id}")

        url = s.get("url", "")
        _validate_receipt_url(source_id, url)

        expected_file = collection_dir / f"{source_id}.json"
        # Bound projected file: no escape from collection directory
        if expected_file.resolve().parent != collection_dir.resolve():
            raise DiscoveryValidationError(f"Dynamic receipt path escapes collection directory: {source_id}")

        if not expected_file.exists():
            status = s.get("status", "UNAVAILABLE")
            receipt_sources_info.append({
                "source_id": source_id,
                "status": status,
                "file_present": False,
                "receipt": s,
            })
            continue

        _validate_regular_file_bounds(expected_file)
        actual_sha = sha256_file(expected_file)
        expected_sha = s.get("projectedSha256")
        if expected_sha and actual_sha != expected_sha:
            raise DiscoveryValidationError(
                f"SHA256 mismatch for {source_id}: expected {expected_sha}, got {actual_sha}"
            )

        receipt_sources_info.append({
            "source_id": source_id,
            "status": s.get("status", "RETRIEVED_NOT_ADMITTED"),
            "file_present": True,
            "path": expected_file,
            "receipt": s,
            "sha256": actual_sha,
        })

    return {
        "receipts_sha256": sha256_file(receipts_path),
        "receipts_data": receipts_data,
        "sources": receipt_sources_info,
    }


def _classify_name_and_symbol(name: str, symbol: str) -> tuple[str, list[str]]:
    """Determine security class and review reasons from name and symbol heuristics."""
    reasons: list[str] = []
    sec_class = "COMMON_STOCK_OR_EQUITY"

    if _RE_PREFERRED.search(name) or symbol.endswith("-P") or ".PR" in symbol:
        sec_class = "PREFERRED_STOCK"
        reasons.append("PREFERRED_SECURITY_DETECTED")
    elif _RE_WARRANT.search(name) or symbol.endswith("W") and len(symbol) >= 5:
        sec_class = "WARRANT"
        reasons.append("WARRANT_SECURITY_DETECTED")
    elif _RE_UNIT.search(name) or symbol.endswith("U") and len(symbol) >= 5:
        sec_class = "UNIT"
        reasons.append("UNIT_SECURITY_DETECTED")
    elif _RE_RIGHTS.search(name) or symbol.endswith("R") and len(symbol) >= 5:
        sec_class = "RIGHTS"
        reasons.append("RIGHTS_SECURITY_DETECTED")
    elif _RE_FUND_OR_DEBT.search(name):
        sec_class = "FUND_OR_DEBT"
        reasons.append("FUND_OR_DEBT_SECURITY_DETECTED")
    elif _RE_ADR.search(name):
        sec_class = "ADR"

    return sec_class, reasons


def parse_nasdaq_record(row: Mapping[str, Any]) -> DiscoveredSecurity:
    """Parse one projected record from nasdaq-listed.json."""
    if not isinstance(row, dict):
        raise DiscoveryValidationError(f"Expected dict record, got {type(row)}")

    raw_symbol = row.get("Symbol")
    if not isinstance(raw_symbol, str) or not raw_symbol.strip():
        raise DiscoveryValidationError("Nasdaq record missing valid Symbol")
    symbol = raw_symbol.strip()

    raw_name = row.get("Security Name")
    if not isinstance(raw_name, str) or not raw_name.strip():
        raise DiscoveryValidationError("Nasdaq record missing valid Security Name")
    security_name = raw_name.strip()

    is_etf = row.get("ETF")
    if not isinstance(is_etf, str) or is_etf not in ("Y", "N"):
        raise DiscoveryValidationError(f"Invalid ETF flag (must be 'Y' or 'N'): {is_etf!r}")

    is_test = row.get("Test Issue")
    if not isinstance(is_test, str) or is_test not in ("Y", "N"):
        raise DiscoveryValidationError(f"Invalid Test Issue flag (must be 'Y' or 'N'): {is_test!r}")

    mkt_cat = row.get("Market Category")
    review_reasons: list[str] = []
    if not isinstance(mkt_cat, str) or mkt_cat not in NASDAQ_MARKET_CATEGORIES:
        review_reasons.append(f"UNKNOWN_MARKET_CATEGORY_{mkt_cat}")

    if is_test == "Y":
        return DiscoveredSecurity(
            venue="NASDAQ",
            symbol=symbol,
            security_name=security_name,
            security_class="TEST_ISSUE",
            status="EXCLUDED",
            source_feed="nasdaq-listed",
            jurisdiction="US",
            issuer_name_lead=security_name.split(" - ")[0].strip(),
            exclusion_reason="TEST_ISSUE",
            feed_metadata={"etf": is_etf, "test_issue": is_test, "market_category": mkt_cat},
        )

    if is_etf == "Y":
        return DiscoveredSecurity(
            venue="NASDAQ",
            symbol=symbol,
            security_name=security_name,
            security_class="EXCHANGE_TRADED_FUND",
            status="EXCLUDED",
            source_feed="nasdaq-listed",
            jurisdiction="US",
            issuer_name_lead=security_name.split(" - ")[0].strip(),
            exclusion_reason="EXCHANGE_TRADED_FUND",
            feed_metadata={"etf": is_etf, "test_issue": is_test, "market_category": mkt_cat},
        )

    sec_class, name_reasons = _classify_name_and_symbol(security_name, symbol)
    review_reasons.extend(name_reasons)

    status = "REVIEW_REQUIRED" if review_reasons else "DISCOVERED_CANDIDATE"

    return DiscoveredSecurity(
        venue="NASDAQ",
        symbol=symbol,
        security_name=security_name,
        security_class=sec_class,
        status=status,
        source_feed="nasdaq-listed",
        jurisdiction="US",
        issuer_name_lead=security_name.split(" - ")[0].strip(),
        exclusion_reason=None,
        review_reasons=tuple(review_reasons),
        feed_metadata={"etf": is_etf, "test_issue": is_test, "market_category": mkt_cat},
    )


def parse_other_us_record(row: Mapping[str, Any]) -> DiscoveredSecurity:
    """Parse one projected record from other-us-listed.json."""
    if not isinstance(row, dict):
        raise DiscoveryValidationError(f"Expected dict record, got {type(row)}")

    raw_symbol = row.get("ACT Symbol")
    if not isinstance(raw_symbol, str) or not raw_symbol.strip():
        raise DiscoveryValidationError("Other US record missing valid ACT Symbol")
    symbol = raw_symbol.strip()

    raw_name = row.get("Security Name")
    if not isinstance(raw_name, str) or not raw_name.strip():
        raise DiscoveryValidationError("Other US record missing valid Security Name")
    security_name = raw_name.strip()

    is_etf = row.get("ETF")
    if not isinstance(is_etf, str) or is_etf not in ("Y", "N"):
        raise DiscoveryValidationError(f"Invalid ETF flag (must be 'Y' or 'N'): {is_etf!r}")

    is_test = row.get("Test Issue")
    if not isinstance(is_test, str) or is_test not in ("Y", "N"):
        raise DiscoveryValidationError(f"Invalid Test Issue flag (must be 'Y' or 'N'): {is_test!r}")

    raw_exch = row.get("Exchange")
    review_reasons: list[str] = []
    if not isinstance(raw_exch, str) or raw_exch not in OTHER_US_EXCHANGE_MAP:
        venue = f"UNKNOWN_VENUE_{raw_exch}"
        review_reasons.append(f"UNKNOWN_EXCHANGE_CODE_{raw_exch}")
    else:
        venue = OTHER_US_EXCHANGE_MAP[raw_exch]

    if is_test == "Y":
        return DiscoveredSecurity(
            venue=venue,
            symbol=symbol,
            security_name=security_name,
            security_class="TEST_ISSUE",
            status="EXCLUDED",
            source_feed="other-us-listed",
            jurisdiction="US",
            issuer_name_lead=security_name.split(" - ")[0].strip(),
            exclusion_reason="TEST_ISSUE",
            feed_metadata={"etf": is_etf, "test_issue": is_test, "raw_exchange": raw_exch},
        )

    if is_etf == "Y":
        return DiscoveredSecurity(
            venue=venue,
            symbol=symbol,
            security_name=security_name,
            security_class="EXCHANGE_TRADED_FUND",
            status="EXCLUDED",
            source_feed="other-us-listed",
            jurisdiction="US",
            issuer_name_lead=security_name.split(" - ")[0].strip(),
            exclusion_reason="EXCHANGE_TRADED_FUND",
            feed_metadata={"etf": is_etf, "test_issue": is_test, "raw_exchange": raw_exch},
        )

    sec_class, name_reasons = _classify_name_and_symbol(security_name, symbol)
    review_reasons.extend(name_reasons)

    status = "REVIEW_REQUIRED" if review_reasons else "DISCOVERED_CANDIDATE"

    return DiscoveredSecurity(
        venue=venue,
        symbol=symbol,
        security_name=security_name,
        security_class=sec_class,
        status=status,
        source_feed="other-us-listed",
        jurisdiction="US",
        issuer_name_lead=security_name.split(" - ")[0].strip(),
        exclusion_reason=None,
        review_reasons=tuple(review_reasons),
        feed_metadata={"etf": is_etf, "test_issue": is_test, "raw_exchange": raw_exch},
    )


def parse_twse_record(row: Mapping[str, Any]) -> DiscoveredSecurity:
    """Parse one record from twse-listed.json, strictly preserving leading zeros and Chinese text."""
    if not isinstance(row, dict):
        raise DiscoveryValidationError(f"Expected dict record, got {type(row)}")

    raw_symbol = row.get("公司代號")
    if not isinstance(raw_symbol, str) or not raw_symbol.strip():
        raise DiscoveryValidationError("TWSE record missing valid 公司代號")
    symbol = raw_symbol.strip()

    raw_name = row.get("公司名稱")
    if not isinstance(raw_name, str) or not raw_name.strip():
        raise DiscoveryValidationError("TWSE record missing valid 公司名稱")
    security_name = raw_name.strip()

    short_name = str(row.get("公司簡稱", "")).strip()
    industry_code = str(row.get("產業別", "")).strip()
    listing_date = str(row.get("上市日期", "")).strip()

    sec_class, name_reasons = _classify_name_and_symbol(security_name, symbol)
    review_reasons = list(name_reasons)

    if "ETF" in security_name or "指數股票型" in security_name:
        return DiscoveredSecurity(
            venue="TWSE",
            symbol=symbol,
            security_name=security_name,
            security_class="EXCHANGE_TRADED_FUND",
            status="EXCLUDED",
            source_feed="twse-listed",
            jurisdiction="TW",
            issuer_name_lead=short_name or security_name,
            exclusion_reason="EXCHANGE_TRADED_FUND",
            feed_metadata={"short_name": short_name, "industry_code": industry_code, "listing_date": listing_date},
        )

    status = "REVIEW_REQUIRED" if review_reasons else "DISCOVERED_CANDIDATE"

    return DiscoveredSecurity(
        venue="TWSE",
        symbol=symbol,
        security_name=security_name,
        security_class=sec_class,
        status=status,
        source_feed="twse-listed",
        jurisdiction="TW",
        issuer_name_lead=short_name or security_name,
        exclusion_reason=None,
        review_reasons=tuple(review_reasons),
        feed_metadata={
            "short_name": short_name,
            "industry_code": industry_code,
            "listing_date": listing_date,
        },
    )


def execute_universe_discovery(
    collection_dir: Path,
    record_bound: int = MAX_RECORD_BOUND_DEFAULT,
) -> dict[str, Any]:
    """Execute strict offline universe discovery across validated public collections."""
    validation = validate_collection_directory(collection_dir)
    receipts_data = validation["receipts_data"]
    sources_info = validation["sources"]

    total_ingested = 0
    valid_processed = 0
    excluded_counts: dict[str, int] = {}
    review_counts: dict[str, int] = {}
    venue_counts: dict[str, int] = {}
    duplicate_records: list[dict[str, Any]] = []
    duplicate_conflicts: list[dict[str, Any]] = []

    # Stable (venue, symbol) identity registry
    discovered_map: dict[tuple[str, str], DiscoveredSecurity] = {}
    issuer_lead_map: dict[str, list[tuple[str, str]]] = {}
    provider_failures: list[dict[str, Any]] = []

    for src in sources_info:
        source_id = src["source_id"]
        receipt = src["receipt"]
        if not src.get("file_present") or src.get("status") not in ("RETRIEVED_NOT_ADMITTED", 200):
            provider_failures.append({
                "source": source_id,
                "status": src.get("status", "UNAVAILABLE"),
                "http_status": receipt.get("httpStatus"),
                "reason": "SOURCE_UNAVAILABLE_OR_FAILED_RETRIEVAL",
            })
            continue

        file_path = src["path"]
        try:
            content = json.loads(file_path.read_text(encoding="utf-8"))
        except Exception as exc:
            provider_failures.append({
                "source": source_id,
                "status": "PARSE_ERROR",
                "error_type": exc.__class__.__name__,
                "reason": "JSON_DECODE_FAILURE",
            })
            continue

        records = content.get("records")
        if not isinstance(records, list):
            provider_failures.append({
                "source": source_id,
                "status": "MALFORMED_RECORDS_LIST",
                "reason": "RECORDS_FIELD_NOT_A_LIST",
            })
            continue

        for row in records:
            if total_ingested >= record_bound:
                break
            total_ingested += 1

            try:
                if source_id == "nasdaq-listed":
                    item = parse_nasdaq_record(row)
                elif source_id == "other-us-listed":
                    item = parse_other_us_record(row)
                elif source_id == "twse-listed":
                    item = parse_twse_record(row)
                else:
                    raise DiscoveryValidationError(f"Unsupported source_id: {source_id}")
            except DiscoveryValidationError:
                review_counts["SCHEMA_VIOLATION"] = review_counts.get("SCHEMA_VIOLATION", 0) + 1
                continue

            valid_processed += 1

            if item.status == "EXCLUDED":
                reason = item.exclusion_reason or "GENERIC_EXCLUSION"
                excluded_counts[reason] = excluded_counts.get(reason, 0) + 1
                continue

            if item.status == "REVIEW_REQUIRED":
                for r in item.review_reasons:
                    review_counts[r] = review_counts.get(r, 0) + 1
                sec_cls = item.security_class
                review_counts[sec_cls] = review_counts.get(sec_cls, 0) + 1

            # Strict stable deduplication by (venue, symbol)
            identity_key = (item.venue, item.symbol)
            if identity_key in discovered_map:
                existing = discovered_map[identity_key]
                is_exact = (
                    existing.security_name == item.security_name
                    and existing.security_class == item.security_class
                    and existing.status == item.status
                    and existing.exclusion_reason == item.exclusion_reason
                )
                if is_exact:
                    duplicate_records.append({
                        "venue": item.venue,
                        "symbol": item.symbol,
                        "first_source": existing.source_feed,
                        "duplicate_source": item.source_feed,
                        "reason": "EXACT_DUPLICATE_DEDUPED",
                    })
                else:
                    # Conflicting duplicate: Never silent first-wins, never boost sources!
                    combined_reasons = tuple(
                        sorted(set(existing.review_reasons) | {"CONFLICTING_DUPLICATE_IDENTITY"})
                    )
                    quarantined = DiscoveredSecurity(
                        venue=existing.venue,
                        symbol=existing.symbol,
                        security_name=f"{existing.security_name} | CONFLICT: {item.security_name}",
                        security_class=(
                            existing.security_class
                            if existing.security_class == item.security_class
                            else "AMBIGUOUS_CONFLICTING_CLASS"
                        ),
                        status="REVIEW_REQUIRED",
                        source_feed=f"{existing.source_feed}+{item.source_feed}",
                        jurisdiction=existing.jurisdiction,
                        issuer_name_lead=existing.issuer_name_lead,
                        exclusion_reason=None,
                        review_reasons=combined_reasons,
                        feed_metadata={
                            "first_feed": existing.feed_metadata,
                            "conflicting_feed": item.feed_metadata,
                        },
                    )
                    discovered_map[identity_key] = quarantined
                    review_counts["CONFLICTING_DUPLICATE_IDENTITY"] = (
                        review_counts.get("CONFLICTING_DUPLICATE_IDENTITY", 0) + 1
                    )
                    duplicate_conflicts.append({
                        "venue": item.venue,
                        "symbol": item.symbol,
                        "first_source": existing.source_feed,
                        "conflicting_source": item.source_feed,
                        "first_record": {
                            "security_name": existing.security_name,
                            "security_class": existing.security_class,
                            "status": existing.status,
                        },
                        "conflicting_record": {
                            "security_name": item.security_name,
                            "security_class": item.security_class,
                            "status": item.status,
                        },
                        "conflict_reasons": ["CONFLICTING_DUPLICATE_IDENTITY"],
                    })
                continue

            discovered_map[identity_key] = item
            venue_counts[item.venue] = venue_counts.get(item.venue, 0) + 1

            # Track unverified issuer name leads
            lead = item.issuer_name_lead
            if lead:
                issuer_lead_map.setdefault(lead, []).append(identity_key)

    candidates_discovered = [
        item for item in discovered_map.values() if item.status == "DISCOVERED_CANDIDATE"
    ]

    # Unverified name similarity groupings (heuristic only, NOT authoritative issuer lineages)
    unverified_name_clusters = {k: v for k, v in issuer_lead_map.items() if len(v) > 1}

    # Verify no private data leaked into items
    for item in discovered_map.values():
        d = item.to_dict()
        intersection = FORBIDDEN_PRIVATE_KEYS.intersection(d.keys())
        if intersection:
            raise DiscoveryValidationError(f"Forbidden private key detected in discovery record: {intersection}")

    discovery_status = (
        "PARTIAL_OR_FAILED"
        if len(provider_failures) == len(sources_info) or total_ingested == 0
        else "SUCCESS_PARTIAL_COVERAGE"
    )

    # Distinguish observed active venues from configured supported venues and coverage gaps
    observed_active_venues = [
        entry for entry in ALL_CONFIGURED_VENUES
        if venue_counts.get(entry["venue"], 0) > 0
    ]
    observed_coverage_gaps = [
        {
            "venue": entry["venue"],
            "feed": entry["feed"],
            "reason": "ZERO_OBSERVED_RECORDS_IN_FEED",
        }
        for entry in ALL_CONFIGURED_VENUES
        if venue_counts.get(entry["venue"], 0) == 0
    ]

    return {
        "schema_version": SCHEMA_VERSION,
        "scope": "PUBLIC_LISTING_IDENTITY_DISCOVERY_ONLY",
        "generated_at_utc": utc_now_iso(),
        "status": discovery_status,
        "publication_qualified": False,
        "claim_admission": False,
        "ranking_admission": False,
        "admitted_company_count": 0,
        "score": None,
        "rank": None,
        "full_market_coverage_claimed": False,
        "audit_boundaries": {
            "public_official_listing_datasets_are_lead_identity_evidence_only": True,
            "company_collector_and_graph_research_required_before_admission": True,
            "no_price_or_return_inferred_from_listings": True,
            "unverified_chinese_names_preserved_not_translated": True,
            "unverified_name_similarity_leads_are_not_authoritative_issuers": True,
            "candidate_counts_do_not_indicate_industry_growth": True,
            "local_file_hash_checks_detect_payload_tamper_only_not_origin_or_rights": True,
            "source_publication_age_remains_unverified": True,
            "authoritative_cik_lei_isin_absent_no_lineage_merged": True,
        },
        "collection_audit": {
            "collection_path": str(collection_dir),
            "receipts_sha256": validation["receipts_sha256"],
            "sources_declared": len(sources_info),
            "sources_intact": len([s for s in sources_info if s.get("file_present")]),
            "sources_failed": len(provider_failures),
            "provider_failures": provider_failures,
        },
        "market_coverage": {
            "configured_supported_venues": list(ALL_CONFIGURED_VENUES),
            "observed_active_venues": observed_active_venues,
            "covered_venues": observed_active_venues,
            "observed_coverage_gaps": observed_coverage_gaps,
            "uncovered_regions_and_asset_classes": list(UNCOVERED_REGIONS_AND_ASSETS),
            "uncovered_statement": (
                "Coverage is strictly partial (observed active venues in US and Taiwan TWSE listed companies only). "
                "Venues with 0 observed records (such as IEX) are treated as coverage gaps. "
                "It does NOT cover European, Japanese, Asian (non-TWSE), OTC, or TPEx equities, nor fixed income or private companies."
            ),
        },
        "summary_counts": {
            "total_records_ingested": total_ingested,
            "valid_records_processed": valid_processed,
            "unique_security_identities": len(discovered_map),
            "candidates_discovered": len(candidates_discovered),
            "excluded_records": {
                "by_reason": excluded_counts,
                "total": sum(excluded_counts.values()),
            },
            "review_required_records": {
                "by_reason": review_counts,
                "total": len([i for i in discovered_map.values() if i.status == "REVIEW_REQUIRED"]),
            },
            "duplicates_detected": len(duplicate_records) + len(duplicate_conflicts),
            "exact_duplicates": len(duplicate_records),
            "duplicate_conflicts": duplicate_conflicts,
            "by_venue": venue_counts,
        },
        "lineage_diagnostics": {
            "authoritative_lineage_available": False,
            "authoritative_identifier_types_missing": ["CIK", "LEI", "ISIN"],
            "unverified_name_clusters_count": len(unverified_name_clusters),
            "unverified_name_similarity_clusters_count": len(unverified_name_clusters),
            "sample_unverified_clusters": {
                k: [f"{v}:{s}" for v, s in pairs]
                for k, pairs in list(unverified_name_clusters.items())[:10]
            },
            "diagnostic_note": (
                "Securities sharing the same unverified issuer name lead are heuristic groupings based solely on "
                "name text strings, NOT authoritative issuer lineages. Authoritative issuer linkage requires CIK, LEI, "
                "or ISIN relations from admitted sources, which are absent in these listing feeds. "
                "These clusters must NOT be counted as verified issuers, nor used to merge identities or claim independent company sources."
            ),
        },
        "records": [item.to_dict() for item in discovered_map.values()],
    }


def write_discovery_report(report: dict[str, Any], output_path: Path) -> None:
    """Write discovery report to disk with create-exclusive semantics."""
    _check_no_symlink(output_path)
    if output_path.exists():
        raise FileExistsError(f"Output path already exists (exclusive write required): {output_path.name}")

    parent = output_path.parent
    _check_no_symlink(parent)
    if not parent.exists():
        raise DiscoveryValidationError(f"Output directory does not exist: {parent.name}")

    data = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    with output_path.open("xb") as f:
        f.write(data.encode("utf-8"))


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Investor Intelligence - Independent Public Universe Identity Discovery (No Admission)"
    )
    parser.add_argument(
        "--collection",
        type=Path,
        required=True,
        help="Path to collection directory containing receipts.json and canonical listings",
    )
    parser.add_argument(
        "--output",
        type=Path,
        required=True,
        help="Path to write the discovery report JSON (must not exist, create-exclusive)",
    )
    parser.add_argument(
        "--max-records",
        type=int,
        default=MAX_RECORD_BOUND_DEFAULT,
        help="Maximum records to process (for safety bounds / fast testing)",
    )
    return parser


def main() -> int:
    parser = build_arg_parser()
    args = parser.parse_args()

    collection_path = args.collection.resolve()
    output_path = args.output.resolve()

    try:
        report = execute_universe_discovery(collection_path, record_bound=args.max_records)
        write_discovery_report(report, output_path)
    except Exception as exc:
        sys.stderr.write(f"PUBLIC_UNIVERSE_DISCOVERY_ERROR: {exc}\n")
        return 1

    counts = report["summary_counts"]
    audit = report["collection_audit"]
    print("=== PUBLIC UNIVERSE DISCOVERY SUMMARY ===")
    print(f"Status: {report['status']}")
    print(f"Scope: {report['scope']}")
    print(f"Admitted Companies: {report['admitted_company_count']} (DISCOVERY_ONLY, NOT_PUBLICATION_QUALIFIED)")
    print(f"Collection: {audit['collection_path']}")
    print(f"Sources Evaluated: {audit['sources_declared']}, Intact: {audit['sources_intact']}, Failed: {audit['sources_failed']}")
    print(f"Records Ingested: {counts['total_records_ingested']}")
    print(f"Valid Processed: {counts['valid_records_processed']}")
    print(f"Unique Identities Discovered: {counts['unique_security_identities']}")
    print(f"Candidate Equities: {counts['candidates_discovered']}")
    print(f"Excluded Records (ETF/Test): {counts['excluded_records']['total']}")
    print(f"Review Required Records: {counts['review_required_records']['total']}")
    print(f"Duplicates Detected: {counts['duplicates_detected']}")
    if counts.get("duplicate_conflicts"):
        print(f"Conflicting Duplicates Quarantined: {len(counts['duplicate_conflicts'])}")
    print("Breakdown by Venue:")
    for v, c in sorted(counts["by_venue"].items()):
        print(f"  - {v}: {c}")
    print(f"Unverified Name-Similarity Clusters: {report['lineage_diagnostics']['unverified_name_similarity_clusters_count']}")
    print(f"Coverage Notice: {report['market_coverage']['uncovered_statement']}")
    print(f"Output File: {output_path}")
    print("=========================================")
    return 0


if __name__ == "__main__":
    sys.exit(main())
