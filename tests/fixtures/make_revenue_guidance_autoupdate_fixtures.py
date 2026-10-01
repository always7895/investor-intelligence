#!/usr/bin/env python3
"""Builds tests/fixtures/revenue-guidance-autoupdate/ from a public capture directory (ORDERS-V3-AUTOUPDATE-01).

The capture directory (the writer's `_workspace/audit-runtime/autoupdate-fixtures`, produced by its capture_fixtures.py)
holds exact HTTP entity bytes under raw/<sha256> and an inventory.json of url/sha256/bytes/retrieved_at/issuer/role and
filing metadata. This script selects the documents the NVDA and MU replay chains and the withdrawal cases need, stores
each as raw/<sha256>.gz (gzip of the exact bytes; the SHA-256 names the decompressed bytes and every reader re-checks
it) and writes inventory.json with the original metadata. Retrieval instants are the genuine capture instants; replay
clocks used by tests are separate and never written here.

Usage: python tests/fixtures/make_revenue_guidance_autoupdate_fixtures.py <capture-dir>"""
from __future__ import annotations

import gzip
import hashlib
import json
import re
import sys
from pathlib import Path

OUT = Path(__file__).resolve().parent / "revenue-guidance-autoupdate"
RELEASES = {"NVDA": ("2025-11-19", "2026-02-25", "2026-05-20", "2026-08-26"), "MU": ("2025-09-23", "2025-12-17", "2026-03-18", "2026-06-24")}
BASELINE = {"NVDA": "2025-11-19", "MU": "2025-09-23"}  # only the release exhibit (the baseline's reference document)
KEEP = ("url", "sha256", "bytes", "retrieved_at", "issuer", "role", "form", "filed", "accession", "report_date", "name",
        "items", "period", "note", "content_type")
EXHIBIT = re.compile(r"q[1-4]fy[0-9]{2}pr\.htm|a20[0-9]{2}q[1-4]ex991-pressrelease\.htm")


def select(rows: list[dict]) -> list[dict]:
    chosen: dict[str, dict] = {}

    def take(row: dict) -> None:
        old = chosen.get(row["url"])
        if old is None or row["retrieved_at"] > old["retrieved_at"]:
            chosen[row["url"]] = row

    chain = set()
    for row in rows:
        sym, role = row.get("issuer"), row.get("role")
        if sym in RELEASES and role == "FILING_DOCUMENT" and row.get("filed") in RELEASES[sym]:
            if row.get("filed") == BASELINE[sym]:
                if EXHIBIT.fullmatch(row.get("name", "")):
                    take(row)
            else:
                take(row)  # the whole results package of a chain release
                chain.add(row["accession"])
        elif sym in RELEASES and role in ("SEC_SUBMISSIONS", "PERIODIC_FILING", "IR_PRESS_RELEASE_FEED", "WIRE_FEED_PAGE",
                                          "IR_RELEASE_PAGE", "WIRE_RELEASE_PAGE"):
            take(row)
        elif role == "WITHDRAWAL_CASE":
            take(row)
    for row in rows:
        if row.get("role") == "SEC_INDEX" and row.get("accession") in chain:
            take(row)
    return sorted(chosen.values(), key=lambda r: (r["issuer"], r["role"], r.get("filed") or "", r["url"]))


def main(argv: list[str]) -> int:
    src = Path(argv[1])
    rows = json.loads((src / "inventory.json").read_text(encoding="utf-8"))
    if (OUT / "raw").exists():
        for old in (OUT / "raw").iterdir():
            old.unlink()
    (OUT / "raw").mkdir(parents=True, exist_ok=True)
    out = []
    for row in select(rows):
        data = (src / "raw" / row["sha256"]).read_bytes()
        if hashlib.sha256(data).hexdigest() != row["sha256"] or len(data) != row["bytes"]:
            raise SystemExit(f"capture mismatch {row['url']}")
        (OUT / "raw" / f"{row['sha256']}.gz").write_bytes(gzip.compress(data, compresslevel=9, mtime=0))
        out.append({k: row[k] for k in KEEP if k in row})
    (OUT / "inventory.json").write_text(json.dumps(out, ensure_ascii=False, indent=1) + "\n", encoding="utf-8", newline="\n")
    print(len(out), "documents,", sum(r["bytes"] for r in out), "bytes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
