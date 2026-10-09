#!/usr/bin/env python3
"""Strict Global Identity Catalog and Index Builder.

Builds a structured, deduplicated global identity catalog from reviewed
official reference collections (NASDAQ, Other US, TWSE). Preserves native
symbols, leading zeros, official names, and share class distinctions.
Quarantines conflicting duplicate observations rather than resolving via first-wins.

Outputs a verified JSON catalog conforming to contract 'v213-global-identity-v1'.
"""
from __future__ import annotations

import argparse
import csv
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import hashlib
import io
import json
import os
from pathlib import Path
import re
import sys
from typing import Any, Mapping

SCHEMA_VERSION = 1
CONTRACT_ID = "v213-global-identity-v1"
MAX_FILE_BYTES = 50 * 1024 * 1024  # 50 MB per file

EXPECTED_OFFICIAL_URLS: dict[str, str] = {
    "nasdaq-listed": "https://www.nasdaqtrader.com/dynamic/SymDir/nasdaqlisted.txt",
    "other-us-listed": "https://www.nasdaqtrader.com/dynamic/SymDir/otherlisted.txt",
    "twse-listed": "https://openapi.twse.com.tw/v1/opendata/t187ap03_L",
}

VENUE_MAP_OTHER_US: dict[str, dict[str, str]] = {
    "A": {"venue": "NYSE American", "country": "United States", "market": "US"},
    "N": {"venue": "NYSE", "country": "United States", "market": "US"},
    "P": {"venue": "NYSE Arca", "country": "United States", "market": "US"},
    "Z": {"venue": "Cboe BZX", "country": "United States", "market": "US"},
    "V": {"venue": "IEX", "country": "United States", "market": "US"},
}

DANGEROUS_OBJECT_KEYS = {
    "__proto__",
    "constructor",
    "prototype",
    "toString",
    "valueOf",
    "hasOwnProperty",
    "isPrototypeOf",
}


class GlobalIdentityError(ValueError):
    """Raised when collection or index validation fails."""


def utc_now_iso() -> str:
    # Ensure exact strict ISO 8601 UTC with trailing 'Z' matching TypeScript roundtrip
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


def _is_symlink_or_junction(path: Path) -> bool:
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
            if attrs & 0x0400:
                return True
    except (OSError, ValueError):
        return True
    return False


def validate_path_safety(path: Path, must_exist: bool = True) -> Path:
    resolved = path.resolve()
    # Check traversal
    parts = path.parts
    if ".." in parts:
        raise GlobalIdentityError(f"Path traversal not permitted: {path}")
    if must_exist:
        if not resolved.exists():
            raise GlobalIdentityError(f"Path does not exist: {path}")
        if _is_symlink_or_junction(path) or _is_symlink_or_junction(resolved):
            raise GlobalIdentityError(f"Symlinks and junctions forbidden: {path}")
        # Check parents for symlinks
        for parent in path.parents:
            if parent.exists() and _is_symlink_or_junction(parent):
                raise GlobalIdentityError(f"Ancestor symlink forbidden: {parent}")
    return resolved


@dataclass(frozen=True)
class GlobalIdentityRecord:
    venue: str
    market: str
    country: str
    symbol: str
    native_symbol: str
    security_name: str
    native_name: str | None
    security_class: str
    currency: str
    source_feed: str
    source_url: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


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
_RE_ADR = re.compile(
    r"(?:\bamerican\s+depositary\s+shares?\b|\bads\b|\badr\b|\bdepositary\s+shares?\b)",
    re.IGNORECASE,
)
_RE_COMMON_STOCK = re.compile(
    r"\b(?:common stock|ordinary shares?|common shares?)\b",
    re.IGNORECASE,
)


def classify_security(name: str, is_etf: bool) -> str:
    if is_etf:
        return "ETF"
    if _RE_PREFERRED.search(name):
        return "PREFERRED_STOCK"
    if _RE_WARRANT.search(name):
        return "WARRANT"
    if _RE_UNIT.search(name):
        return "UNIT"
    if _RE_RIGHTS.search(name):
        return "RIGHTS"
    if _RE_ADR.search(name):
        return "ADR"
    if _RE_COMMON_STOCK.search(name):
        return "COMMON_STOCK"
    # ETF=N does not prove COMMON_STOCK if unverified
    return "REVIEW_REQUIRED"


def normalize_name_for_index(name: str) -> str:
    """Normalize company name for exact lowercase matching."""
    return re.sub(r"\s+", " ", name).strip().lower()


def parse_collection(collection_dir: Path) -> tuple[list[GlobalIdentityRecord], dict[str, list[dict[str, Any]]], str]:
    collection_dir = validate_path_safety(collection_dir, must_exist=True)
    if not collection_dir.is_dir():
        raise GlobalIdentityError(f"Collection path must be a directory: {collection_dir}")

    receipts_path = collection_dir / "receipts.json"
    if not receipts_path.is_file():
        raise GlobalIdentityError(f"Missing receipts.json in collection: {collection_dir}")
    validate_path_safety(receipts_path, must_exist=True)

    if receipts_path.stat().st_size > MAX_FILE_BYTES:
        raise GlobalIdentityError(f"receipts.json exceeds size limit: {receipts_path}")

    try:
        receipts_data = json.loads(receipts_path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise GlobalIdentityError(f"Invalid receipts.json: {exc}") from exc

    receipts_sha = sha256_file(receipts_path)
    sources = receipts_data.get("sources", [])
    if not isinstance(sources, list) or not sources:
        raise GlobalIdentityError("receipts.json sources must be a non-empty list")

    records: list[GlobalIdentityRecord] = []
    seen_venues_symbols: dict[str, GlobalIdentityRecord] = {}
    conflicts: dict[str, list[dict[str, Any]]] = {}

    for src in sources:
        if not isinstance(src, dict):
            continue
        source_id = src.get("source")
        url = src.get("url", "")
        if source_id not in EXPECTED_OFFICIAL_URLS:
            continue
        if EXPECTED_OFFICIAL_URLS[source_id] != url:
            raise GlobalIdentityError(f"Source URL mismatch for {source_id}: {url}")

        json_file = collection_dir / f"{source_id}.json"
        if not json_file.is_file():
            continue
        validate_path_safety(json_file, must_exist=True)
        if json_file.stat().st_size > MAX_FILE_BYTES:
            raise GlobalIdentityError(f"Data file exceeds size limit: {json_file}")

        expected_proj_sha = src.get("projectedSha256")
        actual_proj_sha = sha256_file(json_file)
        if expected_proj_sha and actual_proj_sha != expected_proj_sha:
            raise GlobalIdentityError(
                f"Projected SHA256 mismatch for {source_id}: expected {expected_proj_sha}, got {actual_proj_sha}"
            )

        try:
            payload = json.loads(json_file.read_text(encoding="utf-8"))
        except Exception as exc:
            raise GlobalIdentityError(f"Invalid JSON in {json_file}: {exc}") from exc

        rows: list[dict[str, Any]] = []
        if isinstance(payload, list):
            rows = payload
        elif isinstance(payload, dict):
            for k in ("data", "rows", "records"):
                if isinstance(payload.get(k), list):
                    rows = payload[k]
                    break

        for row in rows:
            if not isinstance(row, dict):
                continue
            rec: GlobalIdentityRecord | None = None

            if source_id == "nasdaq-listed":
                sym = str(row.get("Symbol") or "").strip().upper()
                if not sym or sym.startswith("FILE CREATION TIME"):
                    continue
                if str(row.get("Test Issue") or "N").strip().upper() == "Y":
                    continue
                name = str(row.get("Security Name") or "").strip()
                is_etf = str(row.get("ETF") or "N").strip().upper() == "Y"
                sec_class = classify_security(name, is_etf)
                rec = GlobalIdentityRecord(
                    venue="NASDAQ",
                    market="US",
                    country="United States",
                    symbol=sym,
                    native_symbol=sym,
                    security_name=name,
                    native_name=None,
                    security_class=sec_class,
                    currency="USD",
                    source_feed=source_id,
                    source_url=url,
                )

            elif source_id == "other-us-listed":
                sym = str(row.get("ACT Symbol") or row.get("Symbol") or "").strip().upper()
                if not sym or sym.startswith("FILE CREATION TIME"):
                    continue
                if str(row.get("Test Issue") or "N").strip().upper() == "Y":
                    continue
                ex_code = str(row.get("Exchange") or "").strip().upper()
                v_info = VENUE_MAP_OTHER_US.get(ex_code, {"venue": "OTHER_US", "country": "United States", "market": "US"})
                name = str(row.get("Security Name") or "").strip()
                is_etf = str(row.get("ETF") or "N").strip().upper() == "Y"
                sec_class = classify_security(name, is_etf)
                rec = GlobalIdentityRecord(
                    venue=v_info["venue"],
                    market=v_info["market"],
                    country=v_info["country"],
                    symbol=sym,
                    native_symbol=sym,
                    security_name=name,
                    native_name=None,
                    security_class=sec_class,
                    currency="USD",
                    source_feed=source_id,
                    source_url=url,
                )

            elif source_id == "twse-listed":
                code = str(row.get("公司代號") or row.get("Symbol") or "").strip()
                if not code:
                    continue
                name_zh = str(row.get("公司名稱") or "").strip()
                short_zh = str(row.get("公司簡稱") or "").strip()
                name_full = name_zh or short_zh
                rec = GlobalIdentityRecord(
                    venue="TWSE",
                    market="TAIWAN",
                    country="Taiwan",
                    symbol=code,
                    native_symbol=code,
                    security_name=name_full,
                    native_name=short_zh if short_zh != name_full else None,
                    security_class="REVIEW_REQUIRED",
                    currency="TWD",
                    source_feed=source_id,
                    source_url=url,
                )

            if rec is not None:
                key = f"{rec.venue}:{rec.symbol}"
                existing = seen_venues_symbols.get(key)
                if existing is None:
                    seen_venues_symbols[key] = rec
                    records.append(rec)
                else:
                    if (
                        existing.security_name == rec.security_name
                        and existing.security_class == rec.security_class
                    ):
                        continue
                    conflicts.setdefault(key, [existing.to_dict()]).append(rec.to_dict())

    if conflicts:
        records = [r for r in records if f"{r.venue}:{r.symbol}" not in conflicts]

    return records, conflicts, receipts_sha


def build_catalog_and_indexes(
    records: list[GlobalIdentityRecord],
    conflicts: dict[str, list[dict[str, Any]]],
    receipts_sha: str,
) -> dict[str, Any]:
    by_venue_and_symbol: dict[str, int] = {}
    by_symbol: dict[str, list[int]] = {}
    by_name: dict[str, list[int]] = {}

    for idx, rec in enumerate(records):
        # 1. Primary venue key
        primary_key = f"{rec.venue}:{rec.symbol}"
        by_venue_and_symbol[primary_key] = idx

        # 2. Native symbol (uppercase ASCII or native digits)
        sym_key = rec.native_symbol.upper()
        if sym_key not in DANGEROUS_OBJECT_KEYS:
            by_symbol.setdefault(sym_key, []).append(idx)

        # 3. Exact names (case-insensitive English name and native Chinese name)
        if rec.security_name:
            norm_name = normalize_name_for_index(rec.security_name)
            if norm_name and norm_name not in DANGEROUS_OBJECT_KEYS:
                by_name.setdefault(norm_name, []).append(idx)

        if rec.native_name:
            norm_native = normalize_name_for_index(rec.native_name)
            if norm_native and norm_native != norm_name and norm_native not in DANGEROUS_OBJECT_KEYS:
                by_name.setdefault(norm_native, []).append(idx)

    return {
        "schema_version": SCHEMA_VERSION,
        "contract_id": CONTRACT_ID,
        "generated_at": utc_now_iso(),
        "collection_receipts_sha256": receipts_sha,
        "records_count": len(records),
        "indexed_symbols_count": len(by_symbol),
        "indexed_names_count": len(by_name),
        "conflicts_count": len(conflicts),
        "records": [r.to_dict() for r in records],
        "indexes": {
            "by_venue_and_symbol": by_venue_and_symbol,
            "by_symbol": by_symbol,
            "by_name": by_name,
        },
        "conflicts": conflicts,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--collection", required=True, help="Path to collection directory")
    parser.add_argument("--output", required=True, help="Path to output JSON file")
    args = parser.parse_args()

    collection_path = Path(args.collection)
    output_path = Path(args.output)

    try:
        if ".." in output_path.parts:
            raise GlobalIdentityError("Path traversal not permitted in output path")
        validate_path_safety(output_path.parent, must_exist=True)

        records, conflicts, receipts_sha = parse_collection(collection_path)
        catalog = build_catalog_and_indexes(records, conflicts, receipts_sha)

        out_content = json.dumps(catalog, ensure_ascii=False, indent=2)
        output_path.write_text(out_content, encoding="utf-8")
        print(f"GLOBAL_IDENTITY_INDEX_SUCCESS: {len(records)} records indexed from {collection_path} to {output_path}")
        return 0
    except Exception as exc:
        print(f"GLOBAL_IDENTITY_INDEX_ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
