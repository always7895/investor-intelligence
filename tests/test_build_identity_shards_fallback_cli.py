"""I1-04 (BATCH04 matrix): SEC-cache fallback validation, the degraded CLI exit 2, retry and write durability.

Synthetic bytes in private temporary directories only: no network (build is fed by an in-memory fetch or
replaced), no subprocess, nothing written outside the temporary roots. The sidecar acquisition clock and the
STALE/FUTURE sidecar bounds are covered by tests/test_batch05_cache_carry.py and are not repeated here.
"""
from __future__ import annotations

import contextlib
from datetime import datetime, timedelta, timezone
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import build_identity_shards as shards  # noqa: E402
from tests.test_identity_batch04 import NOW, build_document  # noqa: E402

GOOD = [[1, "Synthetic Nasdaq", "CACHE", "Nasdaq"], [2, "Synthetic NYSE", "CACHED", "NYSE"]]
US_ERROR = "IDENTITY_FEED_FAILED other-us-listed: OSError"


def body(rows, fields=shards.SEC_FIELDS, **extra):
    return json.dumps({"fields": list(fields), "data": rows, **extra}).encode("utf-8")


class DriftingPath(type(Path())):
    """A real file whose metadata changes between the reader's two stat() calls (no lock is claimed)."""

    def stat(self, *, follow_symlinks=True):
        self.__dict__["calls"] = self.__dict__.get("calls", 0) + 1
        if self.__dict__["calls"] == 2:
            moved = (NOW - timedelta(hours=2)).timestamp()
            os.utime(self, (moved, moved))
        return super().stat(follow_symlinks=follow_symlinks)


class SecCacheValidation(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix="i1-sec-cache-")
        self.addCleanup(temp.cleanup)
        self.dir = Path(temp.name)
        self.path = self.dir / "company_tickers_exchange.json"

    def write(self, raw, age=timedelta(hours=1)):
        self.path.write_bytes(raw)
        stamp = (NOW - age).timestamp()
        os.utime(self.path, (stamp, stamp))
        return self.path

    def outcome(self, path, minimum=2):
        try:
            _, retrieved, rows, skipped = shards.load_sec_cache(path, NOW, minimum)
        except shards.IdentityShardError as error:
            return ("REFUSED", str(error))
        return ("ACCEPTED", retrieved, [row[:2] for row in rows], skipped)

    def test_layout_coverage_and_conflict_rows(self):
        accepted = ("ACCEPTED", NOW - timedelta(hours=1), [["CACHE", "NASDAQ"], ["CACHED", "NYSE"]], 0)
        rows = [
            ("control", body(GOOD), 2, accepted),
            ("fields-missing", body([row[:3] for row in GOOD], fields=("cik", "name", "ticker")), 2,
             ("REFUSED", "IDENTITY_SEC_CACHE_SCHEMA")),
            ("fields-duplicate", body([row + [9] for row in GOOD], fields=(*shards.SEC_FIELDS, "cik")), 2,
             ("REFUSED", "IDENTITY_SEC_CACHE_SCHEMA")),
            ("fields-not-text", body([row + [9] for row in GOOD], fields=(*shards.SEC_FIELDS, 7)), 2,
             ("REFUSED", "IDENTITY_SEC_CACHE_SCHEMA")),
            ("row-length", body([GOOD[0], GOOD[1][:3]]), 2, ("REFUSED", "IDENTITY_SEC_CACHE_SCHEMA")),
            ("row-not-list", body([GOOD[0], {"cik": 2}]), 2, ("REFUSED", "IDENTITY_SEC_CACHE_SCHEMA")),
            ("envelope-not-raw", body(GOOD, schema="cache-envelope"), 2, ("REFUSED", "IDENTITY_SEC_CACHE_FAILED ValueError")),
            ("not-json", b"{", 2, ("REFUSED", "IDENTITY_SEC_CACHE_FAILED JSONDecodeError")),
            ("not-utf8", b"\xff\xfe", 2, ("REFUSED", "IDENTITY_SEC_CACHE_FAILED UnicodeDecodeError")),
            ("duplicate-key", b'{"fields":[],"fields":[],"data":[]}', 2, ("REFUSED", "IDENTITY_SEC_CACHE_FAILED ValueError")),
            ("coverage-minimum", body(GOOD), 3, ("REFUSED", "IDENTITY_SEC_CACHE_COVERAGE 2")),
            ("coverage-one-exchange", body([[1, "Alpha", "AAA", "Nasdaq"], [2, "Beta", "BBB", "Nasdaq"]]), 2,
             ("REFUSED", "IDENTITY_SEC_CACHE_COVERAGE 2")),
            ("conflict-name", body(GOOD + [[1, "Renamed Nasdaq", "CACHE", "Nasdaq"]]), 2,
             ("REFUSED", "IDENTITY_SEC_CACHE_CONFLICT")),
            ("conflict-cik", body(GOOD + [[3, "Synthetic Nasdaq", "CACHE", "Nasdaq"]]), 2,
             ("REFUSED", "IDENTITY_SEC_CACHE_CONFLICT")),
            ("exact-duplicate-collapses", body(GOOD + [["0000000001", " Synthetic Nasdaq ", "CACHE", "Nasdaq"]]), 2, accepted),
            ("same-ticker-other-exchange", body(GOOD + [[3, "Cache NYSE", "CACHE", "NYSE"]]), 3,
             ("ACCEPTED", NOW - timedelta(hours=1), [["CACHE", "NASDAQ"], ["CACHE", "NYSE"], ["CACHED", "NYSE"]], 0)),
            ("unusable-rows-skipped", body(GOOD + [[3, "Otc Co", "OTCX", "OTC"], [4, "Lower", "lower", "Nasdaq"],
                                                   [True, "Bool Cik", "BOOL", "NYSE"], [5.0, "Float Cik", "FLT", "NYSE"],
                                                   [0, "Zero Cik", "ZERO", "NYSE"], [6, "  ", "EMPTY", "NYSE"],
                                                   [7, None, "NONE", "NYSE"], [8, "Name", None, "NYSE"]]), 2,
             ("ACCEPTED", NOW - timedelta(hours=1), [["CACHE", "NASDAQ"], ["CACHED", "NYSE"]], 8)),
        ]
        for name, raw, minimum, expected in rows:
            with self.subTest(name=name):
                self.assertEqual(self.outcome(self.write(raw), minimum), expected)

    def test_unverified_mtime_age_bounds(self):
        # No sidecar: the mtime is an availability bound only (LOCAL_CACHE_MTIME_UNVERIFIED), at most 7 days, never future.
        rows = [("seven-days", timedelta(days=7),
                 ("ACCEPTED", NOW - timedelta(days=7), [["CACHE", "NASDAQ"], ["CACHED", "NYSE"]], 0)),
                ("one-second-over",timedelta(days=7, seconds=1), ("REFUSED", "IDENTITY_SEC_CACHE_STALE")),
                ("one-second-ahead", timedelta(seconds=-1), ("REFUSED", "IDENTITY_SEC_CACHE_FUTURE"))]
        for name, age, expected in rows:
            with self.subTest(name=name):
                self.assertEqual(self.outcome(self.write(body(GOOD), age)), expected)
        provenance = {}
        shards.load_sec_cache(self.write(body(GOOD)), NOW, 2, provenance=provenance)
        self.assertEqual(provenance, {"retrieval_basis": "LOCAL_CACHE_MTIME_UNVERIFIED", "cache_integrity": "UNVERIFIED"})

    def test_file_type_size_and_drift(self):
        self.assertEqual(self.outcome(self.dir), ("REFUSED", "IDENTITY_SEC_CACHE_NOT_A_FILE"))
        self.assertEqual(self.outcome(self.dir / "absent.json"), ("REFUSED", "IDENTITY_SEC_CACHE_FAILED FileNotFoundError"))
        raw = body(GOOD)
        with mock.patch.object(shards, "SEC_MAX_BYTES", len(raw) - 1):
            self.assertEqual(self.outcome(self.write(raw)), ("REFUSED", "IDENTITY_SEC_CACHE_TOO_LARGE"))
        with mock.patch.object(shards, "SEC_MAX_BYTES", len(raw)):
            self.assertEqual(self.outcome(self.write(raw))[0], "ACCEPTED")
        drifting = DriftingPath(self.write(raw))
        self.assertEqual(self.outcome(drifting), ("REFUSED", "IDENTITY_SEC_CACHE_CHANGED"))
        self.assertEqual(drifting.__dict__["calls"], 2)

    def test_unusable_cache_reraises_the_original_us_error(self):
        caches = {"conflict": body(GOOD + [[3, "Synthetic Nasdaq", "CACHE", "Nasdaq"]]),
                  "one-exchange": body([[1, "Alpha", "AAA", "Nasdaq"]]),
                  "schema": body([row[:3] for row in GOOD], fields=("cik", "name", "ticker")),
                  "stale": body(GOOD)}
        causes = {"conflict": "IDENTITY_SEC_CACHE_CONFLICT", "one-exchange": "IDENTITY_SEC_CACHE_COVERAGE 1",
                  "schema": "IDENTITY_SEC_CACHE_SCHEMA", "stale": "IDENTITY_SEC_CACHE_STALE"}
        for name, raw in caches.items():
            with self.subTest(name=name):
                path = self.write(raw, timedelta(days=8) if name == "stale" else timedelta(hours=1))
                with self.assertRaises(shards.IdentityShardError) as caught:
                    build_document(fail_us=True, cache=path)
                self.assertEqual((str(caught.exception), str(caught.exception.__cause__)), (US_ERROR, causes[name]))
        with self.assertRaises(shards.IdentityShardError) as caught:
            build_document(fail_us=True, cache=None)
        self.assertEqual((str(caught.exception), caught.exception.__cause__), (US_ERROR, None))


class DegradedCli(unittest.TestCase):
    """main() with build replaced: exit 0/1/2, the summary line, retry of a degraded file and atomic replacement."""

    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix="i1-cli-")
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.output = self.root / "out" / "identity_shards_latest.json"
        patcher = mock.patch.object(shards, "load_zh_names", return_value=({}, None))
        patcher.start()
        self.addCleanup(patcher.stop)

    def degraded(self):
        cache = self.root / "company_tickers_exchange.json"
        cache.write_bytes(body(GOOD))
        old = (NOW - timedelta(days=1)).timestamp()
        os.utime(cache, (old, old))
        return build_document(fail_us=True, cache=cache)

    def run_main(self, document=None, error=None, *, hours=None):
        build = mock.Mock(return_value=document, side_effect=error)
        argv = ["--output", str(self.output)] + ([] if hours is None else ["--if-older-than-hours", str(hours)])
        out = io.StringIO()
        with mock.patch.object(shards, "build", build), contextlib.redirect_stdout(out):
            code = shards.main(argv)
        lines = out.getvalue().splitlines()
        return code, [json.loads(line) for line in lines], build.call_count

    def leftovers(self):
        return sorted(p.name for p in self.output.parent.iterdir()) if self.output.parent.exists() else []

    def test_degraded_build_exits_2_and_writes_like_a_normal_build(self):
        document = self.degraded()
        code, summaries, calls = self.run_main(document)
        self.assertEqual((code, calls, len(summaries)), (2, 1, 1))
        summary = summaries[0]
        self.assertEqual(summary["status"], "DEGRADED_US_FALLBACK")
        self.assertEqual(summary["fallback"], {"feed": shards.SEC_FEED, "retrieved_at": "2026-09-14T12:00:00Z",
                                               "retrieval_basis": "LOCAL_CACHE_MTIME_UNVERIFIED", "reason": US_ERROR})
        self.assertEqual(self.output.read_bytes(), shards.dumps(document).encode("utf-8"))
        self.assertEqual(self.leftovers(), [self.output.name])

    def test_healthy_build_exits_0_without_fallback(self):
        document = build_document()
        code, summaries, calls = self.run_main(document)
        self.assertEqual((code, calls, summaries[0]["status"], "fallback" in summaries[0]), (0, 1, "OK", False))
        self.assertEqual(self.output.read_bytes(), shards.dumps(document).encode("utf-8"))
        self.assertEqual(self.leftovers(), [self.output.name])

    def test_failures_exit_1_and_keep_the_last_good_file(self):
        self.output.parent.mkdir(parents=True)
        self.output.write_bytes(b'{"previous":"good"}')
        code, summaries, _ = self.run_main(error=shards.IdentityShardError("IDENTITY_FEED_FAILED twse-listed: OSError"))
        self.assertEqual((code, summaries), (1, [{"status": "FAILED", "error": "IDENTITY_FEED_FAILED twse-listed: OSError"}]))
        oversize = {"symbol_shards": {"A": {"rows": ["x" * 1_900_000]}}, "name_shards": {}}
        code, summaries, _ = self.run_main(oversize)
        self.assertEqual(code, 1)
        self.assertTrue(summaries[0]["error"].startswith("IDENTITY_SHARD_TOO_LARGE "), summaries[0])
        self.assertEqual(self.output.read_bytes(), b'{"previous":"good"}')
        self.assertEqual(self.leftovers(), [self.output.name])

    def test_a_fresh_degraded_file_is_retried_but_a_fresh_ok_file_is_skipped(self):
        fresh = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        self.output.parent.mkdir(parents=True)
        self.output.write_text(shards.dumps(dict(self.degraded(), generated_at=fresh)), encoding="utf-8")
        healthy = build_document()
        code, summaries, calls = self.run_main(healthy, hours=24)
        self.assertEqual((code, calls, summaries[0]["status"]), (0, 1, "OK"))
        self.output.write_text(shards.dumps(dict(healthy, generated_at=fresh)), encoding="utf-8")
        before = self.output.read_bytes()
        code, summaries, calls = self.run_main(error=AssertionError("a fresh OK file must not rebuild"), hours=24)
        self.assertEqual((code, calls, summaries[0]["status"]), (0, 0, "SKIPPED_FRESH"))
        self.assertEqual(self.output.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
