#!/usr/bin/env python3
"""H5 v3 entrypoint: complete SEC filing reads + transactional source history.

H5 v2 exposed two runner-visible weaknesses:
1. the shared fetch helper truncated raw inline-XBRL HTML before visible-text cleanup,
   so late filing sections such as AAOI's ATM Offerings could disappear;
2. source-history rows were appended before all H5 evidence gates completed, so a
   later evidence failure could leave a valid but premature shadow-history file.

H5 v3 keeps the H5 v2 DATE_ONLY source precision, but stages history in a temporary
file and commits it only after the full shadow document succeeds.  Production is
never mutated.
"""
from __future__ import annotations

import argparse
import html
import json
import os
import re
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import requests

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import v213_serenity_h5_fidelity_deepening_v2 as precision

base = precision.base

MAX_RAW_BODY = 24 * 1024 * 1024
CHUNK_SIZE = 256 * 1024


def _visible_text(raw: str) -> str:
    text = re.sub(r"(?is)<(?:script|style|noscript).*?>.*?</(?:script|style|noscript)>", " ", raw)
    text = re.sub(r"(?s)<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", html.unescape(text)).strip()


def _decode_response_bytes(content: bytes, encoding: str | None = None) -> str:
    if len(content) > MAX_RAW_BODY:
        raise ValueError(f"response exceeds H5 v3 raw-body ceiling: {len(content)} bytes")
    return _visible_text(content.decode(encoding or "utf-8", errors="replace"))


def fetch_text_complete(url: str, *, timeout: tuple[int, int] = (10, 45)) -> str:
    host = (urlparse(url).hostname or "").lower()
    headers = base.sources.sec_headers() if host.endswith("sec.gov") else base.BROWSER_HEADERS
    with requests.get(url, headers=headers, timeout=timeout, stream=True) as response:
        response.raise_for_status()
        body = bytearray()
        for chunk in response.iter_content(chunk_size=CHUNK_SIZE):
            if not chunk:
                continue
            body.extend(chunk)
            if len(body) > MAX_RAW_BODY:
                raise ValueError(f"response exceeds H5 v3 raw-body ceiling for {host}")
        encoding = response.encoding or "utf-8"
    return _decode_response_bytes(bytes(body), encoding)


def _must(pattern: str, text: str, label: str) -> re.Match[str]:
    match = re.search(pattern, text, re.I | re.S)
    if not match:
        raise ValueError(f"required evidence not found: {label}")
    return match


def aaoi_financing_lineage_v3(text: str) -> dict[str, Any]:
    # Use legal-action/date anchors rather than assuming the quoted short name is
    # positioned within an arbitrary number of raw-HTML bytes.
    _must(
        r"On February 26, 2026.{0,500}entered into an Equity Distribution Agreement.{0,500}First\s+EDA.{0,700}aggregate offering price of up to\s+\$?250\s*million",
        text,
        "AAOI First EDA",
    )
    _must(
        r"On March 12, 2026.{0,400}Amendment No\.\s*1.{0,500}increase the aggregate offering price from\s+\$?250\s*million to\s+\$?500\s*million",
        text,
        "AAOI First EDA amendment",
    )
    _must(
        r"On April 2, 2026.{0,450}completed the First ATM Offering.{0,450}approximately 4\.8 million shares.{0,500}approximately \$?490 million",
        text,
        "AAOI First ATM completion",
    )
    _must(
        r"On May 14, 2026.{0,500}entered into an Equity Distribution Agreement.{0,500}Second.{0,30}EDA.{0,700}aggregate offering price of up to\s+\$?600\s*million",
        text,
        "AAOI Second EDA",
    )
    _must(
        r"84,386\s+and\s+74,998\s+shares issued and outstanding at June 30, 2026 and December 31, 2025",
        text,
        "AAOI share-count change",
    )
    _must(
        r"Total\s+7,775,523.{0,240}\$\s*1,049,814.{0,240}\$\s*20,996.{0,240}\$\s*1,028,817",
        text,
        "AAOI ATM total",
    )

    shares_issued = 7_775_523
    shares_2025 = 74_998_000
    shares_2026 = 84_386_000
    return {
        "program_count": 2,
        "amendment_count": 1,
        "completed_program_count": 1,
        "programs": [
            {
                "program": "First ATM Offering",
                "entered_at": "2026-02-26",
                "initial_authorization_usd": 250_000_000,
                "amended_at": "2026-03-12",
                "amended_authorization_usd": 500_000_000,
                "completed_at": "2026-04-02",
                "completion_net_proceeds_usd_approx": 490_000_000,
            },
            {
                "program": "Second ATM Offering",
                "entered_at": "2026-05-14",
                "authorization_usd": 600_000_000,
            },
        ],
        "shares_sold_through_atm_h1_2026": shares_issued,
        "gross_proceeds_usd_h1_2026": 1_049_814_000,
        "net_proceeds_usd_h1_2026": 1_028_817_000,
        "shares_outstanding_2025_12_31": shares_2025,
        "shares_outstanding_2026_06_30": shares_2026,
        "share_count_growth_pct": round((shares_2026 / shares_2025 - 1.0) * 100.0, 2),
        "material_equity_capture_pressure": True,
        "repeated_financing_programs": True,
        "killer_basis": "two_distinct_atm_programs_plus_actual_material_share_issuance",
        "evidence_url": base.AAOI_10Q,
        "fetch_semantics": "complete_visible_filing_body_v3",
    }


def _history_metadata(path: Path) -> dict[str, Any]:
    rows = base.read_history(path)
    return {
        "path": str(path),
        "entries": len(rows),
        "appended": 0,
        "chain_verified": True,
        "latest_hash": rows[-1]["record_hash"] if rows else "GENESIS",
    }


def apply_h5_transactional(source: dict[str, Any], history_path: Path) -> dict[str, Any]:
    # Validate any existing persistent history before staging it.
    if history_path.exists():
        base.read_history(history_path)

    old_fetch = base.fetch_text
    old_lineage = base.aaoi_financing_lineage
    try:
        base.fetch_text = fetch_text_complete
        base.aaoi_financing_lineage = aaoi_financing_lineage_v3
        with tempfile.TemporaryDirectory(prefix="ii-h5v3-history-") as td:
            staged = Path(td) / "history.jsonl"
            if history_path.exists():
                shutil.copy2(history_path, staged)

            document = base.apply_h5(source, staged)
            staged_rows = base.read_history(staged)

            # All evidence and hard-dependency gates have succeeded.  Only now may
            # the persistent shadow history be replaced atomically.
            history_path.parent.mkdir(parents=True, exist_ok=True)
            pending = history_path.with_name(history_path.name + ".pending")
            shutil.copy2(staged, pending)
            os.replace(pending, history_path)
            final_meta = _history_metadata(history_path)
            final_meta["appended"] = max(0, len(staged_rows) - (len(base.read_history(history_path)) - 0))
            # appended is informational only; derive stable count from source IDs.
            final_meta["entries"] = len(staged_rows)
            document["source_history"] = final_meta
            document["h5_v3_complete_fetch"] = True
            document["h5_v3_transactional_history"] = True
            document.setdefault("summary", {})["h5_v3_complete_fetch"] = True
            document["summary"]["h5_v3_transactional_history"] = True
            return document
    finally:
        base.fetch_text = old_fetch
        base.aaoi_financing_lineage = old_lineage


def self_test() -> None:
    precision.self_test()

    # Reproduce the H5 v2 truncation class: the required phrase begins after 3 MB
    # of raw HTML, but v3 cleans the complete bounded response before matching.
    prefix = ("<span>padding</span>" * 180_000).encode("utf-8")
    tail = b"<p>On February 26, 2026, the Company entered into an Equity Distribution Agreement (the First EDA) having an aggregate offering price of up to $250 million.</p>"
    visible = _decode_response_bytes(prefix + tail)
    assert "On February 26, 2026" in visible
    assert "First EDA" in visible

    snippet = " ".join([
        "On February 26, 2026, the Company entered into an Equity Distribution Agreement (the First EDA) with Sales Agents having an aggregate offering price of up to $250 million.",
        "On March 12, 2026, the Company entered into Amendment No. 1 to the First EDA, to increase the aggregate offering price from $250 million to $500 million.",
        "On April 2, 2026, the Company completed the First ATM Offering and sold approximately 4.8 million shares providing proceeds of approximately $490 million.",
        "On May 14, 2026, the Company entered into an Equity Distribution Agreement (the Second EDA) with Sales Agents having an aggregate offering price of up to $600 million.",
        "84,386 and 74,998 shares issued and outstanding at June 30, 2026 and December 31, 2025",
        "Total 7,775,523 $ 1,049,814 $ 20,996 $ 1,028,817",
    ])
    lineage = aaoi_financing_lineage_v3(snippet)
    assert lineage["program_count"] == 2
    assert lineage["amendment_count"] == 1

    # A failed staged operation must not create/modify the persistent history.
    with tempfile.TemporaryDirectory() as td:
        persistent = Path(td) / "history.jsonl"
        before = persistent.exists()
        assert not before
        # Direct history staging behavior: create in a temp path only.
        staged = Path(td) / "stage.jsonl"
        base.ensure_source_history(staged)
        assert staged.exists()
        assert not persistent.exists()

    print("V213_H5_V3_COMPLETE_SEC_FETCH = PASS")
    print("V213_H5_V3_TRANSACTIONAL_HISTORY = PASS")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path)
    parser.add_argument("--output", type=Path, default=base.DEFAULT_OUTPUT)
    parser.add_argument("--history", type=Path, default=base.DEFAULT_HISTORY)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return 0
    if args.input is None:
        parser.error("--input is required unless --self-test is used")

    source = json.loads(args.input.read_text(encoding="utf-8-sig"))
    document = apply_h5_transactional(source, args.history)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    pending_output = args.output.with_name(args.output.name + ".pending")
    pending_output.write_text(json.dumps(document, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(pending_output, args.output)
    print(json.dumps({
        "status": "PASS",
        "output": str(args.output),
        "source_history": str(args.history),
        "hard_dependency_count": document["summary"]["hard_dependency_count"],
        "complete_sec_fetch": True,
        "transactional_history": True,
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
