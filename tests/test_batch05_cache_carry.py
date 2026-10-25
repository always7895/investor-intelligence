"""BATCH05 real local writers/readers; synthetic bytes, private temp files only."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import build_identity_shards as shards
import company_deep_report as cdr
import sec_ticker_cache as cache_codec
from tests.test_identity_batch04 import build_document
from tests.test_publish_sealed_snapshot_carry_forward import synthetic_bundle, reseal
import publish_sealed_snapshot as publisher

NOW = datetime(2026, 9, 15, 12, tzinfo=timezone.utc)
BODY = json.dumps({"fields": ["cik", "name", "ticker", "exchange"], "data": [
    [1, "Synthetic Nasdaq", "CACHE", "Nasdaq"], [2, "Synthetic NYSE", "CACHED", "NYSE"]
]}, ensure_ascii=False).encode("utf-8")


class CacheCarryBatch05Tests(unittest.TestCase):
    def test_writer_to_identity_reader_preserves_body_origin_and_acquisition_not_mtime(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "company_tickers_exchange.json"
            sidecar = cache_codec.sidecar_path(path)
            self.assertEqual(sidecar.name, "company_tickers_exchange.acquisition.json")
            fetch = mock.Mock(return_value=BODY)
            with mock.patch.object(cdr, "datetime", wraps=datetime) as clock:
                clock.now.return_value = NOW - timedelta(days=1)
                self.assertEqual(cdr.ticker_ciks(fetch, today=NOW.date(), cache=path),
                                 {"CACHE": "0000000001", "CACHED": "0000000002"})
                written = path.read_bytes()
                record = json.loads(sidecar.read_bytes())
                self.assertEqual(set(record), {"schema", "origin_url", "body_sha256", "acquired_at"})
                self.assertEqual(record["schema"], cache_codec.SCHEMA)
                self.assertEqual(record["origin_url"], shards.SEC_URL)
                self.assertEqual(record["body_sha256"], hashlib.sha256(BODY).hexdigest())
                self.assertEqual(record["acquired_at"], "2026-09-14T12:00:00Z")
                self.assertEqual(written, BODY)
                old = (NOW - timedelta(days=30)).timestamp()
                os.utime(path, (old, old))
                os.utime(sidecar, (old, old))
                clock.now.return_value = NOW
                cdr.ticker_ciks(fetch, today=NOW.date(), cache=path)
            fetch.assert_called_once_with(shards.SEC_URL)
            doc = build_document(fail_us=True, cache=path)
            feed = next(f for f in doc["feeds"] if f["id"] == shards.SEC_FEED)
            self.assertEqual(feed["retrieval_basis"], "ACQUISITION_SIDECAR")
            self.assertEqual(feed["cache_integrity"], "ORIGIN_BODY_ACQUISITION_BOUND")
            self.assertEqual(feed["sha256"], hashlib.sha256(BODY).hexdigest())
            self.assertEqual(doc["generated_at"], "2026-09-14T12:00:00Z")
            self.assertEqual(path.read_bytes(), written)

    def test_bad_or_missing_sidecar_is_unverified_in_both_age_readers(self):
        good = cache_codec.acquisition_bytes(BODY, NOW)
        cases = {"missing": None, "malformed": b"{", "array": b"[]",
                 "oversize": b" " * (cache_codec.MAX_SIDECAR_BYTES + 1),
                 "duplicate": good[:-1] + b',"origin_url":"https://example.com/duplicate"}'}
        for name, patch in {
            "hash": {"body_sha256": "0" * 64},
            "hash-type": {"body_sha256": 1},
            "origin": {"origin_url": "https://example.com/not-sec"},
            "clock": {"acquired_at": "2026-02-30T12:00:00Z"},
            "clock-type": {"acquired_at": None},
            "clock-zone": {"acquired_at": "2026-09-15T12:00:00+00:00"},
            "unknown-schema": {"schema": "sec-ticker-acquisition-v999"},
            "extra": {"body_utf8": BODY.decode()},
            "nonfinite": {"acquired_at": float("nan")},
        }.items():
            record = json.loads(good)
            record.update(patch)
            cases[name] = json.dumps(record).encode()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "sec.json"
            sidecar = cache_codec.sidecar_path(path)
            for name, metadata in cases.items():
                with self.subTest(name=name):
                    path.write_bytes(BODY)
                    sidecar.unlink(missing_ok=True)
                    if metadata is not None:
                        sidecar.write_bytes(metadata)
                    # Distinct acquisition/mtime clocks expose accidental promotion.
                    modified = NOW - timedelta(days=1)
                    os.utime(path, (modified.timestamp(), modified.timestamp()))
                    self.assertIsNone(cache_codec.acquired_at(BODY, path))
                    doc = build_document(fail_us=True, cache=path)
                    feed = next(f for f in doc["feeds"] if f["id"] == shards.SEC_FEED)
                    self.assertEqual(feed["cache_integrity"], "UNVERIFIED")
                    self.assertEqual(feed["retrieval_basis"], "LOCAL_CACHE_MTIME_UNVERIFIED")
                    self.assertEqual(doc["generated_at"], "2026-09-14T12:00:00Z")
                    fetch = mock.Mock(side_effect=AssertionError("no network"))
                    self.assertEqual(cdr.ticker_ciks(fetch, today=NOW.date(), cache=path),
                                     {"CACHE": "0000000001", "CACHED": "0000000002"})
                    fetch.assert_not_called()
                    self.assertEqual(path.read_bytes(), BODY)
                    self.assertEqual(sidecar.read_bytes() if sidecar.exists() else None, metadata)
                    # Unverified availability still has the old age bound.
                    stale = (NOW - timedelta(days=8)).timestamp()
                    os.utime(path, (stale, stale))
                    with self.assertRaisesRegex(shards.IdentityShardError, "STALE"):
                        shards.load_sec_cache(path, NOW, 2)

    def test_changed_body_does_not_inherit_sidecar_acquisition(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "sec.json"
            changed = BODY.replace(b"Synthetic Nasdaq", b"Changed Nasdaq")
            path.write_bytes(changed)
            cache_codec.sidecar_path(path).write_bytes(cache_codec.acquisition_bytes(BODY, NOW))
            os.utime(path, (NOW.timestamp(), NOW.timestamp()))
            provenance = {}
            loaded = shards.load_sec_cache(path, NOW, 2, provenance=provenance)
            self.assertEqual(loaded[0], changed)
            self.assertEqual(provenance["cache_integrity"], "UNVERIFIED")
            self.assertIsNone(cache_codec.acquired_at(changed, path))

    def test_seven_day_boundary_and_future_sidecar_are_not_renewed_by_mtime(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "sec.json"
            path.write_bytes(BODY)
            sidecar = cache_codec.sidecar_path(path)
            sidecar.write_bytes(cache_codec.acquisition_bytes(BODY, NOW - timedelta(days=7)))
            future = (NOW + timedelta(days=1)).timestamp()
            os.utime(path, (future, future))
            self.assertEqual(shards.load_sec_cache(path, NOW, 2)[1], NOW - timedelta(days=7))
            with self.assertRaisesRegex(shards.IdentityShardError, "STALE"):
                shards.load_sec_cache(path, NOW + timedelta(seconds=1), 2)
            sidecar.write_bytes(cache_codec.acquisition_bytes(BODY, NOW + timedelta(seconds=1)))
            os.utime(path, (NOW.timestamp(), NOW.timestamp()))
            with self.assertRaisesRegex(shards.IdentityShardError, "FUTURE"):
                shards.load_sec_cache(path, NOW, 2)
            with self.assertRaisesRegex(shards.IdentityShardError, "IDENTITY_FEED_FAILED"):
                build_document(fail_us=True, cache=path)

    def test_stale_sidecar_is_refetched_not_renewed_by_touch(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "sec.json"
            path.write_bytes(BODY)
            sidecar = cache_codec.sidecar_path(path)
            sidecar.write_bytes(cache_codec.acquisition_bytes(BODY, NOW - timedelta(days=8)))
            os.utime(path, (NOW.timestamp(), NOW.timestamp()))
            os.utime(sidecar, (NOW.timestamp(), NOW.timestamp()))
            fetch = mock.Mock(return_value=BODY)
            with mock.patch.object(cdr, "datetime", wraps=datetime) as clock:
                clock.now.return_value = NOW
                cdr.ticker_ciks(fetch, today=NOW.date(), cache=path)
            fetch.assert_called_once_with(shards.SEC_URL)
            self.assertEqual(path.read_bytes(), BODY)
            self.assertEqual(cache_codec.acquired_at(BODY, path), NOW)

    def test_interrupted_write_leaves_raw_body_without_old_attestation(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "sec.json"
            sidecar = cache_codec.sidecar_path(path)
            path.write_bytes(BODY)
            sidecar.write_bytes(cache_codec.acquisition_bytes(BODY, NOW - timedelta(days=8)))
            original = Path.write_bytes
            def crash(target, data):
                if target == sidecar:
                    self.assertEqual(path.read_bytes(), BODY)
                    self.assertFalse(sidecar.exists())
                    raise OSError("synthetic interruption before sidecar write")
                return original(target, data)
            with mock.patch.object(cdr, "datetime", wraps=datetime) as clock, mock.patch.object(Path, "write_bytes", crash):
                clock.now.return_value = NOW
                with self.assertRaisesRegex(OSError, "synthetic interruption"):
                    cdr.ticker_ciks(mock.Mock(return_value=BODY), today=NOW.date(), cache=path)
            self.assertEqual(path.read_bytes(), BODY)
            self.assertFalse(sidecar.exists())
            self.assertIsNone(cache_codec.acquired_at(BODY, path))

    def test_new_cache_write_remains_compatible_with_real_raw_readers(self):
        # Exercise the real host collect() through ticker parsing/CIK planning;
        # all input/IO seams fake, stop at the first acquisition boundary.
        from types import SimpleNamespace
        import revenue_guidance_host as host
        import leopold_positions as leopold
        class ParsedTickers(Exception):
            pass
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "sec.json"
            with mock.patch.object(cdr, "datetime", wraps=datetime) as clock:
                clock.now.return_value = NOW
                cdr.ticker_ciks(mock.Mock(return_value=BODY), today=NOW.date(), cache=path)
            capture = object.__new__(host._Capture)
            configs = {"config/" + p: b"{}" for p in host.CONFIG_FILES.values()}
            configs["config/" + host.CONFIG_FILES["layers"]] = json.dumps({"layers": [{
                "capturers": [{"symbol": "CACHE"}, {"symbol": "CACHED"}], "filing_terms": []
            }]}).encode()
            capture.origin = SimpleNamespace(files=configs)
            capture.owner = SimpleNamespace(remaining=mock.Mock())
            capture.entries, capture.observations = {}, {}
            capture.plan_keys, capture.plan_specs = {}, {}
            def fake_file(name, relative, cap=None):
                raw = path.read_bytes() if name == "tickers" else None
                capture.entries[name] = raw
                capture.observations[name] = {}
                return raw
            capture.file = mock.Mock(side_effect=fake_file)
            capture._acquire = mock.Mock(side_effect=ParsedTickers)
            with mock.patch.object(host, "now", return_value=NOW):
                with self.assertRaises(ParsedTickers):
                    capture.collect(SimpleNamespace(load_cision=lambda: None))
            plan = capture._acquire.call_args.args[0]
            planned_urls = [entry[1] for entry in plan]
            self.assertIn("https://data.sec.gov/api/xbrl/companyfacts/CIK0000000001.json", planned_urls)
            self.assertIn("https://data.sec.gov/api/xbrl/companyfacts/CIK0000000002.json", planned_urls)
            self.assertEqual(leopold.ticker_index(path), {"synthetic nasdaq": "CACHE", "synthetic nyse": "CACHED"})
            self.assertEqual(path.read_bytes(), BODY)
            self.assertEqual(set(json.loads(path.read_bytes())), {"fields", "data"})

    def test_stale_auxiliary_reports_and_federation_never_cross_carry_boundary(self):
        bundle = synthetic_bundle(NOW - timedelta(hours=1))
        old = "2000-01-01T00:00:00Z"
        bundle["payloads"]["report_text"] = "STALE_REPORT_SENTINEL " + old
        bundle["payloads"]["source_federation_json"] = json.dumps({
            "generated_at": old, "records": [{"source": "STALE_FEDERATION_SENTINEL"}]})
        reseal(bundle)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bundle.json"
            path.write_text(json.dumps(bundle), encoding="utf-8")
            with mock.patch.object(publisher, "LIVE_NOW", NOW):
                state = publisher.carry_state(path)
                self.assertEqual(state["state"], "CARRIED_FORWARD")
                bodies, _ = publisher.build_bodies(state)
            self.assertNotIn("STALE_REPORT_SENTINEL", bodies["reports:latest"])
            self.assertNotIn("STALE_FEDERATION_SENTINEL", bodies["v213:source-federation:latest"])
            self.assertEqual(json.loads(bodies["v213:source-federation:latest"])["status"], "INSUFFICIENT_EVIDENCE")
            # Beyond the publisher's 13h carry bound: a new seal does not renew the report.
            with mock.patch.object(publisher, "LIVE_NOW", NOW + timedelta(hours=13)):
                stale = publisher.carry_state(path)
                self.assertEqual(stale["state"], "INSUFFICIENT")
                self.assertEqual(stale["reason"], "TOP20_REPORT_TOO_OLD")


if __name__ == "__main__":
    unittest.main()
