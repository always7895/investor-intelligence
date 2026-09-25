"""Hourly publisher carry-forward (single-writer design T5): the validated last-known-good Top20 bundle is sealed
byte for byte, report and row times are never re-stamped, and any defect seals an INSUFFICIENT Top20 with the
macro overview still sealed. Also covers the LKG helper (due, backoff, promotion). Synthetic values only."""
from __future__ import annotations

import hashlib
import json
import sys
import tempfile
import time
import unittest
from contextlib import redirect_stdout
from datetime import datetime, timedelta, timezone
from io import StringIO
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import publish_sealed_snapshot as publisher  # noqa: E402
import top20_carry_forward as carry  # noqa: E402
import v213_evidence_policy as policy  # noqa: E402

TICKERS = [f"T{index:02d}" for index in range(20)]


def iso(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def synthetic_bundle(generated: datetime, *, run_id: str = "20260926T010000Z-0123456789ab",
                     admission: dict[int, object] | None = None) -> dict:
    stamp = iso(generated)
    v213_records, v212_records, top20 = [], [], []
    for index, ticker in enumerate(TICKERS):
        shared = {"long_term_return_pct": 40.0 - index, "short_term_return_pct": 10.0 - index / 2,
                  "industry": "合成產業：合成業務描述", "profit_summary": "獲利；營收年增 +20.0%"}
        v213_records.append({
            "schema_version": 2, "rank": index + 1, "ticker": ticker, "name": f"Synthetic {index}", **shared,
            "current_orders": policy.NO_CURRENT_ORDERS, "future_orders_estimate": policy.NO_FUTURE_ORDER_ESTIMATE,
            "long_term_window": "2y_cagr", "short_term_window": "6m_price_return", "market_source": "yfinance",
            "profit_source": "sec_edgar", "orders_as_of": "", "orders_confidence": "UNAVAILABLE",
            "current_order_source_urls": [], "future_order_source_urls": [], "numeric_total_order_estimate_prohibited": True,
            "retrieved_at": stamp, "orders_state_as_of": iso(generated - timedelta(days=20)),
            "evidence_class": "current_state_claim", "freshness_policy_key": "current_state_claim_max_age_days",
            "test_only_admission": (admission or {}).get(index, False), "provider_scope": "public_only",
            "owner_watchlist_inherited": False,
        })
        v212_records.append({"ticker": ticker, "retrieved_at": stamp, **shared})
        top20.append({"ticker": ticker, "generated_at": iso(generated).replace(".000Z", "Z")})
    v213 = {"schema_version": 2, "product_version": "2.1.3", "generated_at": stamp,
            "freshness_policy": policy.policy_binding(), "evidence_capture_at": stamp,
            "display_columns": policy.DISPLAY_COLUMNS, "long_term_definition": "trailing_2y_adjusted_close_cagr",
            "short_term_definition": "trailing_6m_adjusted_close_price_return", "records": v213_records,
            "provider_scope": "public_only", "owner_watchlist_inherited": False}
    v212 = {"schema_version": 2, "generated_at": stamp, "records": v212_records}
    payloads = {
        "top20_json": json.dumps(top20, ensure_ascii=False), "v212_top20_report_json": json.dumps(v212, ensure_ascii=False),
        "v213_top20_report_json": json.dumps(v213, ensure_ascii=False), "source_plan_json": "[]",
        "report_text": "<!-- synthetic -->", "source_federation_json": "{}", "source_independence_json": "{}",
    }
    return {"schema_version": 4, "run_id": run_id, "generated_at": stamp, "public_data_as_of": stamp,
            "product_version": "2.1.3", "transaction_id": "0" * 32, "payloads": payloads,
            "sha256": {name: hashlib.sha256(text.encode("utf-8")).hexdigest() for name, text in payloads.items()}}


def write_bundle(directory: Path, bundle: dict, name: str | None = None) -> Path:
    path = directory / (name or f"{bundle['run_id']}.json")
    path.write_bytes(json.dumps(bundle, ensure_ascii=False).encode("utf-8"))
    return path


def reseal(bundle: dict) -> dict:
    bundle["sha256"] = {name: hashlib.sha256(text.encode("utf-8")).hexdigest() for name, text in bundle["payloads"].items()}
    return bundle


def edit_payload(bundle: dict, name: str, change) -> dict:
    doc = json.loads(bundle["payloads"][name])
    change(doc)
    bundle["payloads"][name] = json.dumps(doc, ensure_ascii=False)
    return reseal(bundle)


class PublisherCarryForwardTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.snapshots = self.dir / "snapshots"
        self.saved = {key: getattr(publisher, key) for key in
                      ("LIVE_NOW", "LIVE_STAMP", "EVALUATED_AT", "GENERATED_AT", "CLAIMED_AT", "PROMOTED_AT", "PUBLISHED_DATA_AS_OF")}

    def tearDown(self):
        for key, value in self.saved.items():
            setattr(publisher, key, value)
        self.tmp.cleanup()

    def publish(self, *args: str) -> tuple[dict, dict]:
        buffer = StringIO()
        with redirect_stdout(buffer):
            publisher.main(["--live-clock", "--snapshot-root", str(self.snapshots), *args])
        summary = json.loads(buffer.getvalue())
        run_dir = self.snapshots / summary["run_id"]
        objects = json.loads((run_dir / "objects.json").read_bytes().decode("utf-8"))
        prefix = f"snapshot:{summary['run_id']}:"
        return summary, {key[len(prefix):]: value for key, value in objects.items()}

    def test_two_seals_of_one_lkg_carry_identical_bytes_and_never_restamp(self):
        bundle = synthetic_bundle(datetime.now(timezone.utc) - timedelta(hours=2))
        path = write_bundle(self.dir, bundle)
        first, first_objects = self.publish("--top20-bundle", str(path))
        time.sleep(1.1)
        second, second_objects = self.publish("--top20-bundle", str(path))
        self.assertEqual(first["top20_state"], "CARRIED_FORWARD")
        self.assertNotEqual(first["run_id"], second["run_id"])
        for name, key in carry.CARRIED_OBJECTS.items():
            self.assertEqual(first_objects[key], bundle["payloads"][name])  # exact bytes: no time rewritten
            self.assertEqual(second_objects[key], bundle["payloads"][name])
        self.assertNotEqual(first_objects["v213:snapshot-seal:v1"], second_objects["v213:snapshot-seal:v1"])
        self.assertNotEqual(first_objects["last_successful_pipeline_timestamp"], second_objects["last_successful_pipeline_timestamp"])
        self.assertEqual([row[1] for row in first["ranked"]], TICKERS)
        self.assertEqual(first["ranked_count"], 20)
        self.assertEqual(first["top20_bundle_run_id"], bundle["run_id"])
        self.assertEqual(first["top20_bundle_sha256"], hashlib.sha256(path.read_bytes()).hexdigest())
        self.assertIn(publisher.MACRO_KEY, first_objects)

    def test_uncarried_objects_keep_their_placeholders(self):
        path = write_bundle(self.dir, synthetic_bundle(datetime.now(timezone.utc) - timedelta(hours=1)))
        _, objects = self.publish("--top20-bundle", str(path))
        self.assertEqual(objects["reports:latest"], '{"status":"INSUFFICIENT_EVIDENCE"}')
        self.assertEqual(objects["v213:source-federation:latest"], '{"status":"INSUFFICIENT_EVIDENCE","families":0}')
        self.assertEqual(objects["v213:source-independence:latest"], '{"status":"INSUFFICIENT_EVIDENCE","families":0}')
        self.assertEqual(objects["source_plan:latest"], "[]")
        self.assertEqual(objects["scores:latest"], "{}")
        claim = json.loads(objects["v213:activation-claim"])
        self.assertEqual(claim["payload_digests"]["v213_top20_report_json"],
                         hashlib.sha256(objects["v213:top20-report:latest"].encode("utf-8")).hexdigest())

    def test_every_defect_seals_insufficient_with_the_macro_overview(self):
        now = datetime.now(timezone.utc)
        cases = {
            "TOP20_BUNDLE_DIGEST": lambda b: b["sha256"].update(top20_json="0" * 64),
            "TOP20_BUNDLE_SCHEMA": lambda b: b.update(schema_version=3),
            "TOP20_BUNDLE_PAYLOAD_NAMES": lambda b: (b["payloads"].pop("report_text"), b["sha256"].pop("report_text")),
            "TOP20_ORDER_MISMATCH": lambda b: edit_payload(b, "top20_json", lambda rows: rows.reverse()),
            "TOP20_REPORT_INVALID:ADMISSION_MIXED": lambda b: b.update(synthetic_bundle(now - timedelta(hours=1), admission={7: True})),
            "TOP20_ACQUISITION_MISMATCH": lambda b: edit_payload(b, "v212_top20_report_json",
                                                                 lambda doc: doc["records"][3].update(industry="其他")),
        }
        for reason, spoil in cases.items():
            with self.subTest(reason=reason):
                bundle = synthetic_bundle(now - timedelta(hours=1))
                spoil(bundle)
                path = write_bundle(self.dir, bundle, f"{reason.replace(':', '_')}.json")
                summary, objects = self.publish("--top20-bundle", str(path))
                self.assertEqual((summary["top20_state"], summary["top20_reason"]), ("INSUFFICIENT", reason))
                self.assertEqual(objects["v21:top20:latest"], "[]")
                self.assertEqual(json.loads(objects["v213:top20-report:latest"]),
                                 {"status": "INSUFFICIENT_EVIDENCE", "reason": reason, "records": []})
                self.assertIn(publisher.MACRO_KEY, objects)
                self.assertEqual(summary["ranked"], [])

    def test_a_report_past_the_carry_bound_is_not_carried(self):
        # 14 h report bound minus one hourly seal: 13.5 h old is refused, 12.5 h old is carried.
        now = datetime.now(timezone.utc)
        old = write_bundle(self.dir, synthetic_bundle(now - timedelta(hours=13, minutes=30)), "old.json")
        summary, _ = self.publish("--top20-bundle", str(old))
        self.assertEqual((summary["top20_state"], summary["top20_reason"]), ("INSUFFICIENT", "TOP20_REPORT_TOO_OLD"))
        young = write_bundle(self.dir, synthetic_bundle(now - timedelta(hours=12, minutes=30)), "young.json")
        self.assertEqual(self.publish("--top20-bundle", str(young))[0]["top20_state"], "CARRIED_FORWARD")

    def test_forced_insufficient_and_missing_bundle(self):
        path = write_bundle(self.dir, synthetic_bundle(datetime.now(timezone.utc)))
        summary, _ = self.publish("--top20-bundle", str(path), "--top20-insufficient", "TOP20_STAGED_REPLAY_FAILED")
        self.assertEqual((summary["top20_state"], summary["top20_reason"]), ("INSUFFICIENT", "TOP20_STAGED_REPLAY_FAILED"))
        summary, _ = self.publish("--top20-bundle", str(self.dir / "absent.json"))
        self.assertEqual(summary["top20_reason"], "TOP20_BUNDLE_MISSING")

    def test_golden_path_keeps_its_summary_shape(self):
        buffer = StringIO()
        with redirect_stdout(buffer):
            publisher.main(["--snapshot-root", str(self.snapshots)])
        summary = json.loads(buffer.getvalue())
        self.assertNotIn("top20_state", summary)
        self.assertEqual([row[1] for row in summary["ranked"]], ["GEV", "6501"])
        self.assertTrue(summary["run_id"].startswith("20260915T120000Z-"))


class LkgHelperTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.lkg = self.dir / "lkg"

    def tearDown(self):
        self.tmp.cleanup()

    def test_due_promote_and_backoff(self):
        now = datetime.now(timezone.utc).replace(microsecond=0)
        self.assertEqual(carry.refresh_due(now, self.lkg)["reason"], "LKG_MISSING")
        aged = write_bundle(self.dir, synthetic_bundle(now - timedelta(hours=11, minutes=30), run_id="20260926T010000Z-aaaaaaaaaaaa"))
        self.assertEqual(carry.promote(aged, now, self.lkg)["promoted"], "20260926T010000Z-aaaaaaaaaaaa")
        self.assertEqual((self.lkg / "20260926T010000Z-aaaaaaaaaaaa.json").read_bytes(), aged.read_bytes())
        self.assertEqual(carry.refresh_due(now, self.lkg)["reason"], "LKG_AGED")
        carry.record("fail", now, "REFRESH_EXIT_1", self.lkg)
        self.assertEqual(carry.refresh_due(now + timedelta(hours=2), self.lkg)["reason"], "BACKOFF_ACTIVE")
        self.assertTrue(carry.refresh_due(now + timedelta(hours=3, minutes=1), self.lkg)["due"])
        fresh = write_bundle(self.dir, synthetic_bundle(now - timedelta(hours=1), run_id="20260926T020000Z-bbbbbbbbbbbb"))
        carry.promote(fresh, now, self.lkg)
        carry.record("ok", now, "", self.lkg)
        self.assertEqual(carry.refresh_due(now, self.lkg)["reason"], "LKG_FRESH")
        self.assertEqual(carry.newest_lkg(self.lkg).stem, "20260926T020000Z-bbbbbbbbbbbb")

    def test_an_invalid_or_older_candidate_never_replaces_the_lkg(self):
        now = datetime.now(timezone.utc).replace(microsecond=0)
        good = write_bundle(self.dir, synthetic_bundle(now - timedelta(hours=1), run_id="20260926T020000Z-bbbbbbbbbbbb"))
        carry.promote(good, now, self.lkg)
        older = write_bundle(self.dir, synthetic_bundle(now - timedelta(hours=1), run_id="20260926T010000Z-aaaaaaaaaaaa"))
        with self.assertRaisesRegex(carry.BundleRejected, "TOP20_CANDIDATE_NOT_NEWER"):
            carry.promote(older, now, self.lkg)
        broken = synthetic_bundle(now - timedelta(hours=1), run_id="20260926T030000Z-cccccccccccc")
        broken["sha256"]["top20_json"] = "0" * 64
        with self.assertRaisesRegex(carry.BundleRejected, "TOP20_BUNDLE_DIGEST"):
            carry.promote(write_bundle(self.dir, broken), now, self.lkg)
        self.assertEqual(sorted(p.name for p in self.lkg.glob("*.json")), ["20260926T020000Z-bbbbbbbbbbbb.json"])

    def test_keeps_only_the_newest_lkg_files(self):
        now = datetime.now(timezone.utc).replace(microsecond=0)
        for hour in range(1, 8):
            run = f"20260926T0{hour}0000Z-{hour:012x}"
            carry.promote(write_bundle(self.dir, synthetic_bundle(now - timedelta(hours=1), run_id=run)), now, self.lkg)
        self.assertEqual(len(list(self.lkg.glob("*.json"))), carry.KEEP_LKG)
        self.assertEqual(carry.newest_lkg(self.lkg).stem, "20260926T070000Z-000000000007")


class StagedReplayTests(unittest.TestCase):
    """stage_sealed_replay: exact staged bytes, state-aware expectations, and (when Node is installed) the real
    Worker readers over a synthetic carried run and an INSUFFICIENT run."""

    def test_expectations_are_state_aware(self):
        import stage_sealed_replay as replay
        base = {"reader_contract_version": replay.READER_CONTRACT_VERSION, "integrity": "sealed", "run_id": "R",
                "macro_overview_sealed": True}
        carried = {**base, "fresh": True, "top20_records": 20, "line_flex_messages": 4, "line_text_messages": 1,
                   "broadcast_ready": True, "v21_records": 20, "v212_records": 20, "test_only_admission": False}
        self.assertEqual(replay.expectations(carried, "CARRIED_FORWARD", "R"), [])
        self.assertEqual(replay.expectations({**carried, "top20_records": 2}, "CARRIED_FORWARD", "R"), ["TOP20_RECORDS"])
        insufficient = {**base, "fresh": False, "refusal_is_insufficient": True, "v21_records": 0}
        self.assertEqual(replay.expectations(insufficient, "INSUFFICIENT", "R"), [])
        self.assertIn("INSUFFICIENT_REFUSAL", replay.expectations({**insufficient, "refusal_is_insufficient": False}, "INSUFFICIENT", "R"))
        self.assertIn("RUN_ID", replay.expectations(carried, "CARRIED_FORWARD", "OTHER"))
        self.assertIn("FRESH", replay.expectations({**base, "fresh": False}, None, "R"))

    def test_real_readers_replay_both_states(self):
        import shutil
        import stage_sealed_replay as replay
        if not (shutil.which("npx") or shutil.which("npx.cmd")) or not (ROOT / "cloud" / "node_modules").is_dir():
            self.skipTest("Worker toolchain not installed")
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)

            def staged(*args: str) -> dict:
                buffer = StringIO()
                with redirect_stdout(buffer):
                    publisher.main(["--live-clock", "--snapshot-root", str(directory / "runs"), *args])
                return replay.replay(Path(json.loads(buffer.getvalue())["run_dir"]))

            outcome = staged("--top20-insufficient", "TOP20_STAGED_REPLAY_FAILED")
            self.assertEqual((outcome["status"], outcome["top20_state"], outcome["failed"]), ("PASS", "INSUFFICIENT", []), outcome)
            # The synthetic v21/v212 rows satisfy the Python pre-checks but not the Worker's full row contracts: the
            # replay through the real readers is what refuses them before any KV write.
            path = write_bundle(directory, synthetic_bundle(datetime.now(timezone.utc) - timedelta(hours=1)))
            outcome = staged("--top20-bundle", str(path))
            self.assertEqual(outcome["status"], "FAIL")
            self.assertEqual(set(outcome["failed"]), {"BROADCAST_READY", "V21_RECORDS", "V212_RECORDS"}, outcome)
            self.assertTrue(outcome["fresh"])
            # A real refresh bundle on this machine (not in CI) must replay cleanly when it is still carryable.
            local = ROOT / "data" / "cache" / "v213_activation_bundle_upload.json"
            try:
                carry.load_top20_bundle(local, datetime.now(timezone.utc))
            except carry.BundleRejected:
                return
            outcome = staged("--top20-bundle", str(local))
            self.assertEqual((outcome["status"], outcome["top20_records"], outcome["failed"]), ("PASS", 20, []), outcome)


if __name__ == "__main__":
    unittest.main()
