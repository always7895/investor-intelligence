"""BATCH04 synthetic builder -> lazy bodies -> seal bytes, never live publication."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import build_identity_shards as shards
import publish_sealed_snapshot as publisher


def xlsx(rows):
    # Fixture bytes must not depend on ZipFile.writestr's wall-clock DOS timestamp.
    import io
    import zipfile
    from xml.sax.saxutils import escape
    cells = "".join("<row>" + "".join(f'<c t="inlineStr"><is><t>{escape(v)}</t></is></c>' for v in row) + "</row>" for row in rows)
    body = '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>' + cells + '</sheetData></worksheet>'
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as book:
        book.writestr(zipfile.ZipInfo("xl/worksheets/sheet1.xml", (1980, 1, 1, 0, 0, 0)), body)
    return buffer.getvalue()

STAMP = "2026-09-15T12:00:00Z"
NOW = datetime(2026, 9, 15, 12, tzinfo=timezone.utc)
RUN = "20260915T120000Z-b04b04b04b04"
FIXTURE = ROOT / "tests/fixtures/identity-batch04-functional.json"


def raw_feeds():
    nordic = json.dumps({"data": {"instrumentListing": {"rows": [
        {"symbol": "SIVE", "fullName": "Synthetic Orbit", "currency": "SEK", "assetClass": "SHARES"}
    ]}}}).encode()
    return {
        "nasdaq-listed": ("Symbol|Security Name|Test Issue|ETF\n"
                          "ACME|Acme Orbit|N|N\nACME|Acme Variant|N|N\nACME|Acme Orbit|N|N\nGOOD|Healthy Orbit|N|N\n").encode(),
        "other-us-listed": b"ACT Symbol|Security Name|Exchange|Test Issue|ETF\nOMEGA|Other Orbit|N|N|N\n",
        "twse-listed": json.dumps([{"公司代號": "2330", "公司名稱": "台積電", "公司簡稱": "台積電"}]).encode(),
        "tpex-listed": json.dumps([{"SecuritiesCompanyCode": "6000", "CompanyName": "合成", "CompanyAbbreviation": "合成"}]).encode(),
        "nasdaq-stockholm-main": nordic,
        "nasdaq-stockholm-first-north": nordic,
        "jpx-listed": xlsx([["Local Code", "Name (English)", "Section/Products"], ["2330", "Tokyo Orbit", "Prime Market"]]),
        "krx-listed": "<table><tr><th>name</th></tr><tr><td>합성</td><td>유가</td><td>005930</td></tr></table>".encode("euc-kr"),
        "euronext-equities": b"Name;ISIN;Symbol;Market;Currency\nParis Orbit;FR0000000001;PAR;Euronext Paris;EUR\n",
        "lse-main-market": json.dumps([{"content": [{"name": "priceexplorersearch", "value": {"content": [
            {"tidm": "LON", "issuername": "London Orbit", "description": "ORD", "category": "EQUITY", "currency": "GBX"}
        ]}}]}]).encode(),
        "lse-aim": json.dumps([{"content": [{"name": "priceexplorersearch", "value": {"content": [
            {"tidm": "AIM", "issuername": "AIM Orbit", "description": "ORD", "category": "EQUITY", "currency": "GBX"}
        ]}}]}]).encode(),
    }


def build_document(*, fail_us=False, cache=None):
    bodies = raw_feeds()
    def fetch(url):
        feed = next(name for name, value in shards.FEEDS.items() if value == url)
        if fail_us and feed == "other-us-listed":
            raise OSError("synthetic US pair failure")
        return bodies[feed]
    return shards.build(fetch, NOW, zh=({}, None), sec_cache=cache,
                        minimum_rows={name: 1 for name in shards.FEEDS})


def snapshot_fixture():
    document = build_document()
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "identity.json"
        path.write_text(shards.dumps(document), encoding="utf-8")
        lazy = publisher.lazy_identity_bodies(path, NOW)
    bodies = {key: json.dumps({"synthetic": "BATCH04"}) for key in [*publisher.OBJECT_KEYS, publisher.MACRO_KEY]}
    bodies["last_successful_pipeline_timestamp"] = STAMP
    meta = {"run_id": RUN, "transaction_id": "4" * 32}
    bodies["v213:activation-claim"] = publisher._dumps({"schema_version": 1, **meta,
        "payload_digests": {name: "a" * 64 for name in publisher.PAYLOAD_NAMES}, "claimed_at": STAMP})
    with mock.patch.multiple(publisher, GENERATED_AT=STAMP, PUBLISHED_DATA_AS_OF=STAMP, PROMOTED_AT=STAMP):
        seal, digest = publisher.build_seal(bodies, meta, lazy)
        pointer = publisher.pointer_text(meta, digest)
    values = {"snapshot:current": pointer, f"snapshot:{RUN}:{publisher.SEAL_KEY}": seal}
    values.update({f"snapshot:{RUN}:{key}": body for key, body in bodies.items()})
    blobs = {}
    for key, body in lazy.items():
        address = "blob:v1:" + hashlib.sha256(body.encode()).hexdigest()
        values[address] = body
        blobs[key] = address
    return {"scope": "SYNTHETIC_OFFLINE_NOT_PUBLICATION", "stamp": STAMP, "run": RUN,
            "document": document, "values": values, "blobs": blobs}


class IdentityBatch04Tests(unittest.TestCase):
    def test_variants_survive_but_equal_provenance_collapses(self):
        doc = build_document()
        rows = doc["symbol_shards"]["A"]["rows"]
        self.assertEqual([r[4] for r in rows if r[0] == "ACME"], ["Acme Orbit", "Acme Variant"])
        self.assertEqual(len(doc["symbol_shards"]["S"]["rows"]), 1)
        self.assertEqual(doc["symbol_shards"]["S"]["rows"][0][8], 4)
        refs = [tuple(r) for shard in doc["name_shards"].values() for r in shard["rows"]]
        self.assertEqual(len(refs), len(set(refs)))
        self.assertEqual(doc["records"], sum(len(s["rows"]) for s in doc["symbol_shards"].values()))

    def test_builder_publisher_bytes_match_worker_fixture(self):
        self.assertEqual(snapshot_fixture(), json.loads(FIXTURE.read_bytes()))

    def test_sec_utf16_and_normalized_bounds_precede_duplicate_detection(self):
        rows = [[1, "Valid", "OKAY", "Nasdaq"], [2, "\U0001f680" * 150, "WIDE", "NYSE"],
                [3, "\U0001f680" * 151, "OKAY", "Nasdaq"], [4, "\u0130" * 151, "GROW", "Nasdaq"],
                [5, "\ud800", "LONE", "Nasdaq"]]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "sec.json"
            path.write_text(json.dumps({"fields": list(shards.SEC_FIELDS), "data": rows}), encoding="utf-8")
            os.utime(path, (NOW.timestamp(), NOW.timestamp()))
            _, _, accepted, skipped = shards.load_sec_cache(path, NOW, 2)
        self.assertEqual([r[0] for r in accepted], ["OKAY", "WIDE"])
        self.assertEqual(accepted[1][4], "\U0001f680" * 150)
        self.assertEqual(skipped, 3)

    def test_fallback_replaces_us_pair_and_keeps_original_age(self):
        with mock.patch.object(shards, "load_sec_cache", side_effect=AssertionError("healthy build read cache")):
            self.assertFalse(any(f.get("fallback_for") for f in build_document()["feeds"]))
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "sec.json"
            path.write_text(json.dumps({"fields": list(shards.SEC_FIELDS), "data": [
                [1, "Cached Nasdaq", "CACHE", "Nasdaq"], [2, "Cached NYSE", "CACHED", "NYSE"]]}), encoding="utf-8")
            old = (NOW - timedelta(days=1)).timestamp()
            os.utime(path, (old, old))
            doc = build_document(fail_us=True, cache=path)
        self.assertEqual(doc["generated_at"], "2026-09-14T12:00:00Z")
        self.assertEqual([f["id"] for f in doc["feeds"] if f["id"] in (*shards.US_FEEDS, shards.SEC_FEED)], [shards.SEC_FEED])
        us = [row for part in doc["symbol_shards"].values() for row in part["rows"] if row[2] == "US"]
        self.assertEqual([row[0] for row in us], ["CACHE", "CACHED"])
        self.assertTrue(all(row[6] == "REVIEW_REQUIRED" for row in us))
        self.assertTrue(all(part["generated_at"] == doc["generated_at"] for part in doc["symbol_shards"].values()))


if __name__ == "__main__":
    unittest.main()
