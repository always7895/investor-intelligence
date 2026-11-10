"""Score-neutral R3 research and append-only provenance behaviors; synthetic inputs, no network."""
from __future__ import annotations

import copy
import hashlib
import hmac
import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import ExitStack, redirect_stdout
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import bottleneck_top20_v3 as ranking
import top20_rotation_provenance as rotation
import validated_rule_engine as rules

CUTOFF = date(2026, 11, 8)
KEY = b"synthetic-shadow-test-key-not-a-real-key-123456"


def fundamentals():
    return {"source": "SEC EDGAR XBRL companyfacts", "source_url": "https://data.sec.gov/api/xbrl/companyfacts/EXAMPLE.json",
            "filed": "2026-10-20", "quarter_end": "2026-09-30", "revenue_yoy": 0.30, "revenue_yoy_prev": 0.20,
            "gross_margin_change": -0.01, "shares_yoy": 0.05, "shares_basis": "DILUTED_WEIGHTED_AVERAGE",
            "rpo_yoy": 0.22, "rpo_end": "2026-09-30", "rpo_filed": "2026-10-20",
            "rpo_prior_end": "2025-09-30", "rpo_prior_filed": "2025-10-21"}


def market():
    return {"source": "Yahoo Finance adjusted daily close (unofficial)", "source_url": "https://finance.yahoo.com/quote/EXAMPLE",
            "asof": "2026-11-06", "ret_6m": 0.10, "ret_6m_start": "2026-05-08", "cagr_2y": 0.12,
            "max_drawdown_12m": -0.20, "drawdown_start": "2025-11-06"}


def document(top=("A", "B"), candidates=("A", "B", "C")):
    return {"top": [{"symbol": symbol, "score": 100 - rank} for rank, symbol in enumerate(top)],
            "candidate_fingerprints": [{"symbol": symbol, **{name: rotation.digest([name, symbol])
                for name in rotation.INPUT_FAMILIES}} for symbol in candidates],
            "input_context": {"prices": "captured-price-digest", "serenity": "captured-author-digest",
                              "context": {"config": "public-config-digest", "fx": "public-fx-digest"}},
            "screener_shadow": [{"symbol": symbol, "conditions": rules.evaluate(fundamentals(), market(), cutoff=CUTOFF, symbol=symbol)}
                                for symbol in candidates]}


def journal_document(*, reverse=False):
    symbols = tuple(f"A{index}" for index in range(10))
    return document(top=tuple(reversed(symbols)) if reverse else symbols, candidates=symbols)


class ScreenerBehavior(unittest.TestCase):
    def evaluate(self, fund=None, prices=None, cutoff=CUTOFF):
        output = rules.evaluate(fund if fund is not None else fundamentals(),
                                prices if prices is not None else market(), cutoff=cutoff, symbol="A")
        return output, {row["rule_id"]: row for row in output["rules"]}

    def test_frozen_thresholds_and_document_shortfalls_are_explicit_and_score_neutral(self):
        fund, prices = fundamentals(), market()
        before = copy.deepcopy((fund, prices))
        output, by = self.evaluate(fund, prices)
        self.assertEqual(by["R01_REV_GROWTH_20"]["status"], "PASS")
        self.assertEqual(by["R02_REV_ACCEL_10PP"]["status"], "PASS")
        self.assertEqual(by["R03_GM_EXPAND_2PP"]["status"], "FAIL")
        self.assertEqual(by["R05_DILUTION_BELOW_5"]["status"], "PASS")
        self.assertEqual(by["R07_PRICE_2Y_POSITIVE"]["status"], "PASS")
        self.assertEqual(by["R09_MAX_DRAWDOWN_12M"]["status"], "PASS")
        for name in ("R10_ATM_MATERIAL_DILUTION", "R13_INDEPENDENT_13F_POSITION_CHANGE"):
            self.assertEqual(by[name]["status"], "UNKNOWN")
            self.assertTrue(by[name]["reason_zh"])
        self.assertEqual(output["state"], "UNVERIFIED")
        self.assertEqual(output["rules_kept"], 0)
        self.assertEqual((fund, prices), before)
        self.assertFalse(any("score" in row for row in output["rules"]))
        self.assertEqual({row["rule_id"] for row in rules.display_projection(output)["rules"]}, set(by))

    def test_benchmark_relative_rules_require_aligned_adjusted_benchmarks_not_positive_stock(self):
        prices = market()
        _, missing = self.evaluate(prices=prices)
        self.assertEqual(missing["R06_REL_MOMENTUM_6M"]["status"], "UNKNOWN")
        prices["benchmarks"] = {name: {**market(), "ret_6m": ret} for name, ret in (("QQQ", 0.03), ("SOXX", 0.20))}
        _, by = self.evaluate(prices=prices)
        self.assertEqual(by["R06_REL_MOMENTUM_6M"]["status"], "PASS")
        self.assertEqual(by["R08_REL_MOMENTUM_SOXX_6M"]["status"], "FAIL")
        prices["benchmarks"]["QQQ"]["ret_6m_start"] = "2026-05-01"
        _, by = self.evaluate(prices=prices)
        self.assertEqual(by["R06_REL_MOMENTUM_6M"]["status"], "UNKNOWN")

    def test_dates_fail_closed_and_hashes_describe_evidence_not_wallclock(self):
        output, _ = self.evaluate()
        later, _ = self.evaluate(cutoff=date(2026, 11, 9))
        self.assertEqual(output["input_sha256"], later["input_sha256"])
        for stamp in (None, "2026-11-10", "2026-11-08junk", "not-a-date"):
            _, by = self.evaluate({**fundamentals(), "filed": stamp, "rpo_filed": stamp}, {**market(), "asof": stamp})
            self.assertTrue(all(row["status"] == "UNKNOWN" for row in by.values()))
            self.assertTrue(all(row["reason_zh"] and row["freshness"] != "FRESH" for row in by.values()))
        stale, by = self.evaluate(cutoff=date(2027, 11, 8))
        self.assertTrue(all(row["status"] == "UNKNOWN" for row in by.values()))
        self.assertEqual(stale["input_sha256"], output["input_sha256"])
        self.assertTrue(any(row["freshness"] == "STALE" for row in by.values()))

    def test_rpo_uses_own_filing_dates_not_unrelated_revenue_filing(self):
        _, by = self.evaluate({**fundamentals(), "rpo_filed": "2026-11-10"})
        self.assertEqual(by["R01_REV_GROWTH_20"]["status"], "PASS")
        self.assertEqual(by["R04_RPO_GROWTH_20"]["status"], "UNKNOWN")
        _, by = self.evaluate({**fundamentals(), "rpo_prior_filed": None})
        self.assertEqual(by["R04_RPO_GROWTH_20"]["status"], "UNKNOWN")

    def test_price_adjustment_unknown_cannot_be_overridden_by_a_number(self):
        _, by = self.evaluate(prices={**market(), "return_reasons": {"cagr_2y": "PUBLIC_DISTRIBUTION_UNRESOLVED"}})
        self.assertEqual(by["R07_PRICE_2Y_POSITIVE"]["status"], "UNKNOWN")
        _, by = self.evaluate({**fundamentals(), "revenue_yoy": float("nan"), "shares_yoy": True})
        self.assertEqual(by["R01_REV_GROWTH_20"]["status"], "UNKNOWN")
        self.assertEqual(by["R05_DILUTION_BELOW_5"]["status"], "UNKNOWN")


class RotationBehavior(unittest.TestCase):
    def test_identical_inputs_have_no_false_rotation_and_shuffled_candidates_do_not_change_hashes(self):
        doc = document()
        original = copy.deepcopy(doc)
        first = rotation.build_record(doc, None, asof="2026-11-08T00:00:00Z")
        second_doc = copy.deepcopy(doc)
        second_doc["candidate_fingerprints"].reverse()
        second_doc["screener_shadow"].reverse()
        second = rotation.build_record(second_doc, first, asof="2026-11-08T01:00:00Z")
        self.assertEqual(second["input_sha256"], first["input_sha256"])
        self.assertEqual(second["diff"]["reason_code"], "NO_CHANGE")
        self.assertEqual(second["diff"]["changed_input_families"], [])
        self.assertEqual(second["diff"]["changed_candidates"], [])
        self.assertEqual(second["diff"]["changed_screener_symbols"], [])
        self.assertFalse(second["diff"]["ranking_changed"])
        self.assertEqual(doc, original)

    def test_rank_only_change_is_not_misreported_as_changed_prices_or_filings(self):
        first = rotation.build_record(document(), None, asof="2026-11-08T00:00:00Z")
        second = rotation.build_record(document(top=("B", "A")), first, asof="2026-11-08T01:00:00Z")
        self.assertEqual(second["diff"]["changed_input_families"], [])
        self.assertTrue(second["diff"]["ranking_changed"])
        self.assertEqual(second["diff"]["reason_code"], "RANKING_CHANGED_WITHOUT_INPUT_CHANGE")
        self.assertEqual(second["diff"]["entered"], [])
        self.assertEqual(len(second["diff"]["moved"]), 2)
        # Full-candidate provenance is mandatory, even for an otherwise valid Top20.
        incomplete = document()
        incomplete.pop("candidate_fingerprints")
        with self.assertRaises(ValueError):
            rotation.build_record(incomplete, first, asof="2026-11-08T01:00:00Z")

    def test_overflow_input_change_and_removed_candidate_have_specific_family_evidence(self):
        first = rotation.build_record(document(), None, asof="2026-11-08T00:00:00Z")
        changed = document()
        changed["candidate_fingerprints"][-1]["events"] = rotation.digest("new-public-filing")
        second = rotation.build_record(changed, first, asof="2026-11-08T01:00:00Z")
        self.assertEqual(second["diff"]["changed_input_families"], ["events"])
        self.assertEqual(second["diff"]["changed_candidates"], [{"symbol": "C", "families": ["events"], "change": "UPDATED"}])
        self.assertEqual(second["diff"]["reason_code"], "INPUT_CHANGED_RANKING_UNCHANGED")
        removed = rotation.build_record(document(candidates=("A", "B")), first, asof="2026-11-08T02:00:00Z")
        self.assertEqual(removed["diff"]["changed_candidates"][0]["change"], "REMOVED")

    def test_source_context_and_full_rule_evidence_are_committed_as_compact_digests(self):
        doc = document()
        first = rotation.build_record(doc, None, asof="2026-11-08T00:00:00Z")
        doc["input_context"]["context"]["fx"] = "new-public-fx-digest"
        second = rotation.build_record(doc, first, asof="2026-11-08T01:00:00Z")
        self.assertEqual(second["diff"]["changed_input_families"], ["context"])
        self.assertNotIn("new-public-fx-digest", json.dumps(second))
        self.assertEqual(len(second["screener_shadow"]), 3)
        source = {entry["symbol"]: entry["conditions"]["rules"] for entry in doc["screener_shadow"]}
        for symbol in second["screener_shadow"]:
            retained = [{name: row.get(name) for name in (
                "rule_id", "status", "filed_at", "period_end", "quote_asof", "source_url",
                "freshness", "complete", "provenance_hash", "reason_zh")}
                for row in source[symbol["symbol"]]]
            retained.sort(key=lambda row: row["rule_id"])
            self.assertEqual(symbol["rules_sha256"], rotation.digest(retained))
            self.assertEqual(sum(symbol["status_counts"].values()), len(rules.RULES))
            self.assertNotIn("rules", symbol)
        self.assertNotIn("source_url", rotation.canonical(second).decode("utf-8"))
        self.assertEqual(second["candidate_fingerprints"], doc["candidate_fingerprints"])
        self.assertLess(len(rotation.canonical(second)), len(rotation.canonical(doc)))
        self.assertEqual(second["rules_kept"], 0)

    def test_full_signed_chain_must_validate_before_any_append(self):
        for defect in ("signature", "entry_hash", "chain", "truncated"):
            with self.subTest(defect=defect), tempfile.TemporaryDirectory() as td:
                path = Path(td) / "shadow.jsonl"
                for hour in range(3):
                    rotation.append_signed(path, journal_document(), key=KEY, asof=f"2026-11-08T{hour * 6:02d}:00:00Z")
                rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
                self.assertEqual(rotation.verify_log(path, KEY)["ranked"], [f"A{index}" for index in range(10)])
                if defect != "truncated":
                    rows[0]["diff"]["reason_zh"] = "已改寫的合成測試資料"
                if defect in {"entry_hash", "chain"}:
                    rows[0].pop("signature")
                    if defect == "chain":
                        rows[0].pop("entry_sha256")
                        rows[0]["entry_sha256"] = rotation.digest(rows[0])
                    rows[0]["signature"] = hmac.new(KEY, rotation.canonical(rows[0]), hashlib.sha256).hexdigest()
                raw = b"\n".join(rotation.canonical(row) for row in rows) + (b"" if defect == "truncated" else b"\n")
                path.write_bytes(raw)
                with self.assertRaises(ValueError):
                    rotation.append_signed(path, journal_document(), key=KEY, asof="2026-11-08T18:00:00Z")
                self.assertEqual(path.read_bytes(), raw)
                self.assertEqual(json.loads(path.with_name(path.name + ".lock").read_text()), {"released": True})

    def test_failed_refresh_does_not_advance_last_good_signed_observation(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "shadow.jsonl"
            rotation.append_signed(path, journal_document(), key=KEY, asof="2026-11-08T00:00:00Z")
            before = path.read_bytes()
            for failure in ({"refresh_state": "REFRESH_FAILED"}, {"source_failures": ["synthetic-provider"]}):
                result = rotation.append_signed(path, {**document(), **failure},
                                                key=KEY, asof="2026-11-08T01:00:00Z")
                self.assertEqual(result["state"], "REFRESH_FAILED")
                self.assertEqual(result["asof_utc"], "2026-11-08T00:00:00Z")
                self.assertEqual(path.read_bytes(), before)

    def test_real_record_limit_and_short_signing_key_are_nonblocking(self):
        for limit, key in ((64, KEY.decode()), (rotation.MAX_RECORD_BYTES, "short-key")):
            with self.subTest(limit=limit), tempfile.TemporaryDirectory() as td:
                path = Path(td) / "shadow.jsonl"
                doc = journal_document()
                with patch.object(rotation, "MAX_RECORD_BYTES", limit), patch.dict(
                        os.environ, {"II_R2B_SHADOW_SIGNING_KEY": key}), self.assertLogs(rotation.LOGGER, "WARNING"):
                    self.assertEqual(rotation.append_if_configured(doc, path=path,
                        asof="2026-11-08T00:00:00Z"), "UNVERIFIED")
                self.assertFalse(path.exists())
                self.assertEqual(doc["rotation_provenance"]["notice_zh"], rotation.UNVERIFIED_NOTICE_ZH)

    def test_host_preserves_raw_body_completion_binding_when_shadow_fails(self):
        import publish_sealed_snapshot as publisher
        import revenue_guidance_host as host
        for failure in (ValueError("SHADOW_WRITER_BUSY"), OSError("synthetic-io-failure")):
            with self.subTest(kind=type(failure).__name__), tempfile.TemporaryDirectory() as td, ExitStack() as stack:
                cutoff = datetime(2026, 11, 8, tzinfo=timezone.utc)
                symbols = tuple(f"A{index}" for index in range(10))
                doc = document(top=symbols, candidates=symbols)
                doc["generated_at"] = "2026-11-08T00:00:00Z"
                rev = "gir1:" + "a" * 64
                state = {"Intent": None, "StateRequired": True, "InputRevision": rev, "PendingRevision": rev}
                snapshot = SimpleNamespace(symbols=lambda: symbols, cutoff=doc["generated_at"],
                    input_digest="synthetic-input", generation_id="synthetic-generation", generation_sha256="b" * 64)
                consumption = SimpleNamespace(snapshot=snapshot, rows=[(symbol,) for symbol in symbols])
                session = SimpleNamespace(phase="idle", guard=object(), witness=None, machine_enabled=False,
                    lease=SimpleNamespace(read_journal=Mock(return_value=SimpleNamespace(state=state))),
                    input_revision=Mock(return_value=rev), snapshot=Mock(return_value=snapshot), remaining=Mock())
                captured = Mock()
                captured.collect.return_value = cutoff.date()
                captured.catalog.return_value = {}
                captured.manifest.return_value = {}
                published = {}
                def publish(raw, body, record):
                    published.update(raw=raw, body=body, record=record)
                    return {"rank": host.digest(raw), "body": host.digest(body), "record": host.digest(record)}
                outputs = SimpleNamespace(publish=publish, latest_ranking=lambda: None)
                def seal(raw, *args, **kwargs):
                    self.assertEqual(json.loads(raw)["rotation_provenance"], {
                        "status": "UNVERIFIED", "notice_zh": rotation.UNVERIFIED_NOTICE_ZH})
                    return {publisher.BOTTLENECK_V3_KEY: "synthetic-sealed-body"}
                stack.enter_context(patch.object(host, "_Capture", return_value=captured))
                stack.enter_context(patch.object(host, "now", return_value=cutoff))
                stack.enter_context(patch.object(host.overlay, "B1Store"))
                stack.enter_context(patch.object(host.overlay, "B1Outputs", return_value=outputs))
                stack.enter_context(patch.object(host.revision, "compute_input_revision", return_value=rev))
                stack.enter_context(patch.object(ranking, "build", return_value=doc))
                stack.enter_context(patch.object(publisher, "ForecastConsumption", return_value=consumption))
                stack.enter_context(patch.object(publisher, "captured_bottleneck_v3_body", side_effect=seal))
                stack.enter_context(patch.dict(os.environ, {
                    "II_R2B_SHADOW_SIGNING_KEY": KEY.decode(), "II_R2B_SHADOW_LOG": str(Path(td) / "shadow.jsonl")}))
                stack.enter_context(patch.object(rotation, "append_signed", side_effect=failure))
                stack.enter_context(self.assertLogs(rotation.LOGGER, "WARNING"))
                result = host._Session.rank(session, {"Mode": "Dirty", "Revision": rev})
                self.assertTrue(result["Completed"])
                completion = json.loads(published["record"])
                self.assertEqual(completion["shadow_attestation"], "UNVERIFIED")
                self.assertEqual(completion["ranking_sha256"], host.digest(published["raw"]))
                self.assertEqual(completion["output_sha256"], host.digest(published["body"]))
                self.assertIsNotNone(session.witness)
                self.assertEqual(session.phase, "idle")

    def test_missing_key_same_clock_skip_and_concurrent_changed_writer(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "shadow.jsonl"
            unconfigured = document()
            with patch.dict("os.environ", {}, clear=True):
                self.assertEqual(rotation.append_if_configured(unconfigured, path=path, asof="2026-11-08T00:00:00Z"), "UNCONFIGURED")
            self.assertNotIn("rotation_provenance", unconfigured)
            self.assertFalse(path.exists())
            rotation.append_signed(path, journal_document(), key=KEY, asof="2026-11-08T00:00:00Z")
            raw = path.read_bytes()
            self.assertEqual(rotation.append_signed(path, journal_document(), key=KEY,
                asof="2026-11-08T00:00:00+00:00")["state"], "SKIPPED_NO_CHANGE")
            lock = path.with_name(path.name + ".lock")
            lock.write_bytes(rotation.canonical({"pid": os.getpid(), "created_at": 0}))
            with self.assertRaises(ValueError):
                rotation.append_signed(path, journal_document(reverse=True), key=KEY, asof="2026-11-08T01:00:00Z")
            self.assertEqual(path.read_bytes(), raw)
            self.assertTrue(lock.exists())

    def test_all_candidate_family_fingerprints_are_still_required(self):
        for family in rotation.INPUT_FAMILIES:
            with self.subTest(family=family):
                doc = document()
                doc["candidate_fingerprints"][-1].pop(family)  # Overflow candidate, not a ranked row.
                with self.assertRaisesRegex(ValueError, "SHADOW_FINGERPRINTS_INVALID"):
                    rotation.build_record(doc, None, asof="2026-11-08T00:00:00Z")
        incomplete = document()
        incomplete["candidate_fingerprints"].pop(0)
        with self.assertRaisesRegex(ValueError, "SHADOW_FINGERPRINTS_INCOMPLETE"):
            rotation.build_record(incomplete, None, asof="2026-11-08T00:00:00Z")

    def test_258_changes_retain_bounded_authenticated_checkpoint_tail(self):
        with tempfile.TemporaryDirectory() as td, patch.object(rotation, "MAX_SEGMENT_BYTES", 32 * 1024):
            path = Path(td) / "shadow.jsonl"
            start = datetime(2026, 11, 8, tzinfo=timezone.utc)
            for hour in range(258):
                doc = journal_document(reverse=bool(hour % 2))
                doc["unrelated_full_ranking_document"] = "not-journal-content" * 100000
                result = rotation.append_signed(path, doc, key=KEY, asof=(start + timedelta(hours=hour)).isoformat())
                self.assertEqual(result["state"], "SIGNED")
                segments = rotation._segments(path)
                self.assertLessEqual(len(segments), rotation.MAX_RETAINED_SEGMENTS)
                for segment in segments:
                    self.assertNotIn(b"not-journal-content", segment.read_bytes())
                    self.assertLessEqual(segment.stat().st_size, rotation.MAX_SEGMENT_BYTES)
            self.assertEqual(rotation.verify_log(path, KEY)["sequence"], 258)
            checkpoint = path.with_name(path.name + ".checkpoint")
            self.assertTrue(checkpoint.exists())
            self.assertLessEqual(sum(item.stat().st_size for item in Path(td).iterdir()),
                rotation.MAX_RETAINED_SEGMENTS * rotation.MAX_SEGMENT_BYTES + rotation.MAX_RECORD_BYTES + 8192)
            wrapper = json.loads(checkpoint.read_bytes())
            wrapper["anchor"]["ranked"].reverse()
            checkpoint.write_bytes(rotation.canonical(wrapper))
            with self.assertRaisesRegex(ValueError, "SHADOW_SIGNATURE_INVALID"):
                rotation.verify_log(path, KEY)

    def test_failed_checkpoint_cannot_grow_a_new_segment_on_each_retry(self):
        start = datetime(2026, 11, 8, tzinfo=timezone.utc)
        def candidate(index):
            doc = journal_document()
            shift = index % len(doc["top"])
            doc["top"] = doc["top"][shift:] + doc["top"][:shift]
            return doc
        limit = len(rotation.canonical(rotation.build_record(candidate(0), None, asof=start.isoformat()))) + 1024
        with tempfile.TemporaryDirectory() as td, patch.object(rotation, "MAX_SEGMENT_BYTES", limit):
            path = Path(td) / "shadow.jsonl"
            for index in range(rotation.MAX_RETAINED_SEGMENTS):
                rotation.append_signed(path, candidate(index), key=KEY, asof=(start + timedelta(minutes=index)).isoformat())
            with patch.object(rotation.os, "replace", side_effect=OSError("synthetic-checkpoint-failure")):
                ceiling = None
                for index in range(8, 18):
                    with self.assertRaises(OSError):
                        rotation.append_signed(path, candidate(index), key=KEY,
                            asof=(start + timedelta(minutes=index)).isoformat())
                    segments = rotation._segments(path)
                    self.assertEqual(len(segments), rotation.MAX_RETAINED_SEGMENTS + 1)
                    total = sum(segment.stat().st_size for segment in segments)
                    if ceiling is None:
                        ceiling = total
                    self.assertEqual(total, ceiling)

    def test_258_hourly_evaluations_write_only_6h_heartbeats_and_never_move_skip_clock(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "shadow.jsonl"
            start = datetime(2026, 11, 8, tzinfo=timezone.utc)
            writes = 0
            for hour in range(258):
                doc = journal_document()
                doc["input_context"]["context"]["source"] = hour  # Source-only changes are not writes.
                before = {item.name: item.read_bytes() for item in Path(td).iterdir()}
                result = rotation.append_signed(path, doc, key=KEY, asof=(start + timedelta(hours=hour)).isoformat())
                if hour % 6 == 0:
                    self.assertEqual(result["state"], "SIGNED")
                    writes += 1
                else:
                    self.assertEqual(result["state"], "SKIPPED_NO_CHANGE")
                    self.assertEqual({item.name: item.read_bytes() for item in Path(td).iterdir()}, before)
                self.assertEqual(rotation.verify_log(path, KEY)["asof_utc"],
                    (start + timedelta(hours=hour - hour % 6)).isoformat().replace("+00:00", "Z"))
            self.assertEqual(writes, 43)
            self.assertEqual(rotation.verify_log(path, KEY)["sequence"], 43)

    def test_whole_chain_rejects_tampering_or_a_missing_earlier_segment(self):
        for defect in ("signature", "missing_segment", "non_monotonic"):
            with self.subTest(defect=defect), tempfile.TemporaryDirectory() as td, patch.object(
                    rotation, "MAX_SEGMENT_BYTES", 32 * 1024):
                path = Path(td) / "shadow.jsonl"
                for hour in range(10):
                    rotation.append_signed(path, journal_document(reverse=bool(hour % 2)), key=KEY, asof=f"2026-11-08T{hour:02d}:00:00Z")
                segments = rotation._segments(path)
                self.assertGreater(len(segments), 2)
                if defect == "missing_segment":
                    segments[1].unlink()
                else:
                    rows = [json.loads(line) for line in segments[1].read_bytes().splitlines()]
                    if defect == "signature":
                        rows[0]["ranked"].reverse()
                    else:
                        rows[0].pop("signature")
                        rows[0].pop("entry_sha256")
                        rows[0]["asof_utc"] = "2026-11-07T00:00:00Z"
                        rows[0]["entry_sha256"] = rotation.digest(rows[0])
                        rows[0]["signature"] = hmac.new(KEY, rotation.canonical(rows[0]), hashlib.sha256).hexdigest()
                    segments[1].write_bytes(b"".join(rotation.canonical(row) + b"\n" for row in rows))
                before = {segment: segment.read_bytes() for segment in segments if segment.exists()}
                with self.assertRaises(ValueError):
                    rotation.verify_log(path, KEY)
                with self.assertRaises(ValueError):
                    rotation.append_signed(path, journal_document(), key=KEY, asof="2026-11-08T11:00:00Z")
                self.assertEqual({segment: segment.read_bytes() for segment in before}, before)

    def test_stale_lock_requires_both_dead_owner_and_age(self):
        for alive, created_at, recovered in ((False, 0, True), (False, 999, False),
                                              (True, 0, False), (None, 0, False)):
            with self.subTest(alive=alive, created_at=created_at), tempfile.TemporaryDirectory() as td:
                path = Path(td) / "shadow.jsonl"
                lock = path.with_name(path.name + ".lock")
                original = rotation.canonical({"pid": 123456, "created_at": created_at})
                lock.write_bytes(original)
                with patch.object(rotation.time, "time", return_value=1000), patch.object(
                        rotation, "_process_alive", return_value=alive) as query:
                    if recovered:
                        self.assertEqual(rotation.append_signed(path, journal_document(), key=KEY,
                            asof="2026-11-08T00:00:00Z")["state"], "SIGNED")
                        self.assertEqual(json.loads(lock.read_bytes()), {"released": True})
                    else:
                        with self.assertRaisesRegex(ValueError, "SHADOW_WRITER_BUSY"):
                            rotation.append_signed(path, journal_document(), key=KEY, asof="2026-11-08T00:00:00Z")
                        self.assertFalse(path.exists())
                        self.assertEqual(lock.read_bytes(), original)
                    if created_at == 999:
                        query.assert_not_called()

    def test_active_os_lock_cannot_be_recovered_or_replaced(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "shadow.jsonl"
            lock = path.with_name(path.name + ".lock")
            fd = rotation._acquire_lock(lock)
            try:
                os.lseek(fd, 0, os.SEEK_SET)
                original = os.read(fd, 513)
                with patch.object(rotation, "_process_alive", return_value=False), patch.object(
                        rotation.time, "time", return_value=10**12):
                    with self.assertRaisesRegex(ValueError, "SHADOW_WRITER_BUSY"):
                        rotation.append_signed(path, journal_document(), key=KEY, asof="2026-11-08T00:00:00Z")
                os.lseek(fd, 0, os.SEEK_SET)
                self.assertEqual(os.read(fd, 513), original)
                self.assertFalse(path.exists())
            finally:
                rotation._write_lock(fd, {"released": True})
                rotation._file_lock(fd, release=True)
                os.close(fd)

    def test_windows_process_query_never_calls_kill_or_requests_stop_rights(self):
        import ctypes
        kernel = Mock()
        kernel.OpenProcess.return_value = 17
        def exit_code(handle, code):
            code._obj.value = 259
            return True
        kernel.GetExitCodeProcess.side_effect = exit_code
        with patch.object(ctypes, "WinDLL", return_value=kernel, create=True), patch.object(
                ctypes, "get_last_error", return_value=87, create=True), patch.object(os, "kill") as kill:
            self.assertTrue(rotation._windows_process_alive(123456))
            kernel.OpenProcess.assert_called_once_with(0x1000, False, 123456)
            kernel.CloseHandle.assert_called_once_with(17)
            kernel.OpenProcess.return_value = None
            self.assertFalse(rotation._windows_process_alive(123456))
            with patch.object(ctypes, "get_last_error", return_value=5):
                self.assertIsNone(rotation._windows_process_alive(123456))
            with patch.object(rotation.os, "name", "nt"), patch.object(
                    rotation, "_windows_process_alive", return_value=False) as query:
                self.assertFalse(rotation._process_alive(123456))
                query.assert_called_once_with(123456)
            kill.assert_not_called()

    def test_configured_journal_failures_attach_fixed_advisory_and_sanitized_log(self):
        failures = (ValueError("SHADOW_RECORD_LIMIT"), ValueError("SHADOW_WRITER_BUSY"),
                    ValueError("SHADOW_SIGNING_KEY_UNAVAILABLE"), OSError("synthetic-private-path"),
                    RuntimeError("synthetic-private-message"))
        for failure in failures:
            with self.subTest(kind=type(failure).__name__), tempfile.TemporaryDirectory() as td:
                doc = document()
                before_top = copy.deepcopy(doc["top"])
                with patch.dict(os.environ, {"II_R2B_SHADOW_SIGNING_KEY": KEY.decode()}), patch.object(
                        rotation, "append_signed", side_effect=failure), self.assertLogs(rotation.LOGGER, "WARNING") as logs:
                    state = rotation.append_if_configured(doc, path=Path(td) / "shadow.jsonl",
                                                          asof="2026-11-08T00:00:00Z")
                self.assertEqual(state, "UNVERIFIED")
                self.assertEqual(doc["rotation_provenance"], {
                    "status": "UNVERIFIED", "notice_zh": rotation.UNVERIFIED_NOTICE_ZH})
                self.assertEqual(doc["top"], before_top)
                self.assertIn("SHADOW_", logs.output[0])
                self.assertNotIn("synthetic-private", logs.output[0])
                self.assertNotIn(KEY.decode(), logs.output[0])

    def test_cli_publishes_new_ranking_despite_configured_shadow_failure(self):
        for failure in (ValueError("SHADOW_RECORD_LIMIT"), ValueError("SHADOW_WRITER_BUSY"),
                        ValueError("SHADOW_SIGNING_KEY_UNAVAILABLE"), OSError("synthetic-io-failure")):
            with self.subTest(kind=str(failure)), tempfile.TemporaryDirectory() as td:
                symbols = tuple(f"A{index}" for index in range(10))
                doc = document(top=symbols, candidates=symbols)
                for rank, row in enumerate(doc["top"], 1):
                    row.update(rank=rank, layer="synthetic")
                doc.update(industries=[], excluded=[], generated_at="2026-11-08T00:00:00Z")
                output = Path(td) / "ranking.json"
                output.write_text('{"old":true}', encoding="utf-8")
                with patch.object(ranking, "build", return_value=doc), patch.object(
                        ranking, "sec_fetch_factory", return_value=None), patch.object(
                        ranking, "utc_now", return_value=datetime(2026, 11, 8, tzinfo=timezone.utc)), patch.dict(
                        os.environ, {"II_R2B_SHADOW_SIGNING_KEY": KEY.decode()}), patch.object(
                        rotation, "append_signed", side_effect=failure), self.assertLogs(
                        rotation.LOGGER, "WARNING"), redirect_stdout(io.StringIO()) as stdout:
                    result = ranking.main(["--output", str(output), "--shadow-log", str(Path(td) / "shadow.jsonl"), "--no-news"])
                self.assertEqual(result, 0)
                published = json.loads(output.read_text(encoding="utf-8"))
                self.assertEqual(len(published["top"]), 10)
                self.assertEqual(published["rotation_provenance"], {
                    "status": "UNVERIFIED", "notice_zh": rotation.UNVERIFIED_NOTICE_ZH})
                self.assertEqual(json.loads(stdout.getvalue())["shadow"], "UNVERIFIED")
                self.assertFalse(output.with_name(output.name + ".tmp").exists())


if __name__ == "__main__":
    unittest.main()
