"""Deploy gate reads Production, replays live bytes and parses UTC anchors in PowerShell 5.1 and 7 (no network).

Regression 2026-09-25: Wrangler 4 KV commands default to the local Miniflare store, so the gate's
"live" pointer was the local copy; PowerShell 7 shifted UTC anchors by the local offset; and the reader
replay read a result file that no test wrote any more. Production was nine days stale while the gate passed.
"""
from __future__ import annotations

import hashlib
import json
import re
import shutil
import contextlib
import io
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import fetch_live_public_snapshot as live  # noqa: E402

GATE = (ROOT / "scripts" / "deploy_production_gate.ps1").read_text(encoding="utf-8")
RUN = "20260925T125615Z-92f5d828bc6c"
CORE = "20260925T105615Z-abcdefabcdef"
STAMP = "2026-09-25T12:56:15Z"
CORE_STAMP = "2026-09-25T10:56:15Z"


def fake_store(tamper: bool = False, reused: bool = False) -> dict[str, bytes]:
    core, data_at = (CORE, CORE_STAMP) if reused else (RUN, STAMP)
    bodies = {key: json.dumps({"synthetic": key, "records": ["合成"]}, ensure_ascii=False).encode("utf-8")
              for key in sorted(live.EAGER_KEYS)}
    bodies["last_successful_pipeline_timestamp"] = STAMP.encode("utf-8")
    contract = json.loads((ROOT / "config" / "v213-r75-publication-mode-v2.json").read_text(encoding="utf-8"))
    bodies["v213:activation-claim"] = json.dumps({"schema_version": 1, "run_id": core, "transaction_id": "1" * 32,
        "payload_digests": {name: "a" * 64 for name in contract["payload_names"]}, "claimed_at": data_at},
        separators=(",", ":")).encode("utf-8")
    definitions = {key: {"sha256": hashlib.sha256(body).hexdigest(), "utf8_bytes": len(body)} for key, body in bodies.items()}
    store = {f"snapshot:{RUN if reused and key == live.LIVENESS_KEY else core}:{key}": body for key, body in bodies.items()}
    if reused:
        for key, value in (("v213:bottleneck-top20:v3", {"generated_at": data_at, "marker": "UNCHANGED_RANKING"}),
                           ("v213:quotes:v1", {"generated_at": STAMP, "marker": "FRESH_QUOTES"})):
            body = json.dumps(value, separators=(",", ":")).encode("utf-8")
            definitions[key] = {"sha256": hashlib.sha256(body).hexdigest(), "utf8_bytes": len(body)}
            store["blob:v1:" + definitions[key]["sha256"]] = body
    seal = {"schema_version": 1, "contract_id": "v213-stored-snapshot-v1", "run_id": RUN, "transaction_id": "1" * 32,
            "generated_at": STAMP, "public_data_as_of": data_at, "provider_scope": "public_only",
            "owner_watchlist_inherited": False, "objects": definitions}
    if reused:
        seal.update(core_run_id=core, ranking_persisted_at=data_at, product_persisted_at={"market": STAMP, "identity": data_at})
    raw = json.dumps(seal, separators=(",", ":")).encode("utf-8")
    store[f"snapshot:{RUN}:v213:snapshot-seal:v1"] = raw
    store["snapshot:current"] = json.dumps({"schema_version": 2, "run_id": RUN, "transaction_id": "1" * 32,
        "seal_sha256": hashlib.sha256(raw).hexdigest(), "public_data_as_of": data_at, "promoted_at": STAMP,
        "provider_scope": "public_only", "owner_watchlist_inherited": False}, separators=(",", ":")).encode("utf-8")
    if tamper:
        store[f"snapshot:{core}:v213:top20-report:latest"] += b" "
    return store


class GateContractTests(unittest.TestCase):

    def test_utc_anchor_in_windows_powershell_and_pwsh(self):
        function = re.search(r"function ConvertTo-UtcAnchor.*?\n}\n", GATE, re.S).group(0)
        probe = function + ("$p = '{\"a\":\"2026-09-25T12:56:15Z\",\"b\":\"2026-09-25T12:56:15\"}' | ConvertFrom-Json\n"
                            "(ConvertTo-UtcAnchor $p.a).ToString('o'); (ConvertTo-UtcAnchor $p.b).ToString('o'); "
                            "[string](ConvertTo-UtcAnchor '')\n")
        shells = [s for s in ("powershell", "pwsh") if shutil.which(s)]
        if not shells:
            self.skipTest("PowerShell not available")
        for shell in shells:
            out = subprocess.run([shell, "-NoProfile", "-NonInteractive", "-Command", probe], capture_output=True,
                                 text=True, timeout=120).stdout.split()
            self.assertEqual(out[:2], ["2026-09-25T12:56:15.0000000Z"] * 2, shell)

    def test_gate_ages_verified_global_liveness_not_old_data_or_an_unverified_promotion(self):
        from datetime import datetime, timedelta, timezone
        shells = [shell for shell in ("powershell", "pwsh") if shutil.which(shell)]
        if not shells:
            self.skipTest("PowerShell not available")
        functions = "".join(re.search(rf"function {name}.*?\n}}\n", GATE, re.S).group(0)
                            for name in ("ConvertTo-UtcAnchor", "Get-PointerAgeSeconds"))
        now = datetime.now(timezone.utc)
        stamp = lambda hours: (now - timedelta(hours=hours)).strftime("%Y-%m-%dT%H:%M:%S.000Z")
        pointer = {"run_id": RUN, "seal_sha256": "a" * 64, "public_data_as_of": stamp(4), "promoted_at": stamp(0)}
        copy = {"run_id": RUN, "seal_sha256": "a" * 64, "pipeline_liveness_at": stamp(0.1)}
        cases = {"fresh_global_old_data": copy, "stale_global_fresh_promotion": {**copy, "pipeline_liveness_at": stamp(4)},
                 "wrong_hash": {**copy, "seal_sha256": "b" * 64}, "missing_hash": {**copy, "seal_sha256": None},
                 "wrong_global": {**copy, "run_id": CORE}, "missing_clock": {k: v for k, v in copy.items() if k != "pipeline_liveness_at"},
                 "no_copy": None}
        probe = functions + f"$p = '{json.dumps(pointer)}' | ConvertFrom-Json\n"
        for name, value in cases.items():
            probe += (f"$c = '{json.dumps(value)}' | ConvertFrom-Json\n"
                      f"try {{ '{name}=' + (Get-PointerAgeSeconds $p $c) }} catch {{ '{name}=FAIL' }}\n")
        for shell in shells:
            done = subprocess.run([shell, "-NoProfile", "-NonInteractive", "-Command", probe], capture_output=True,
                                  text=True, timeout=120)
            rows = dict(line.split("=", 1) for line in done.stdout.splitlines() if "=" in line)
            self.assertLess(int(rows["fresh_global_old_data"]), 1200, (shell, rows, done.stderr[-400:]))
            self.assertGreater(int(rows["stale_global_fresh_promotion"]), 7200, shell)
            for name in ("wrong_hash", "missing_hash", "wrong_global", "missing_clock", "no_copy"):
                self.assertEqual(rows.get(name), "FAIL", (shell, name, rows))


class ProductionKvAddressingTests(unittest.TestCase):
    """Every production KV command names Production explicitly; the local store is never a silent target."""

    def test_deploy_gate_has_only_remote_reads_and_no_kv_mutation(self):
        # Negative pin: do not trust a mere count of the existing GET.
        live_lines = "\n".join(line for line in GATE.splitlines()
                               if line.strip() and not line.lstrip().startswith("#"))
        gets = re.findall(r"(?im)^.*\bkv\s+key\s+get\b[^\n]*", live_lines)
        self.assertEqual(len(gets), 1, gets)
        self.assertTrue(all("--remote" in line and "--local" not in line for line in gets))
        self.assertNotRegex(live_lines, r"(?i)\bkv\s+(?:key\s+(?:put|delete|remove)|bulk\b|(?:put|delete)\b)")

    def test_freshness_watchdog_cannot_launch_wrangler_or_mutate_kv(self):
        watchdog = (ROOT / "scripts" / "freshness_watchdog.ps1").read_text(encoding="utf-8")
        live_lines = "\n".join(line for line in watchdog.splitlines()
                               if line.strip() and not line.lstrip().startswith("#"))
        self.assertIn("--read-freshness", live_lines)
        self.assertIn("sync_sealed_snapshot_kv.py", live_lines)
        self.assertNotRegex(live_lines, r"(?i)\bwrangler(?:\.cmd|\.exe|\.js)?\b")
        self.assertNotRegex(live_lines, r"(?i)\bkv\s+(?:key\s+(?:put|delete|remove)|bulk\b|(?:put|delete)\b)")

    def test_sync_and_rollback_pass_remote_on_every_kv_command(self):
        import rollback_sealed_snapshot as rollback
        import sync_sealed_snapshot_kv as sync
        calls = []
        fake = lambda args, **kw: calls.append(list(args)) or subprocess.CompletedProcess(args, 0, "{}", "")
        # Both staging and fake CLI cwd belong to this fixture, never the checkout.
        with tempfile.TemporaryDirectory() as tmp, \
                patch.object(rollback, "ROOT", Path(tmp)), \
                patch.object(sync, "ROOT", Path(tmp)), \
                patch.object(sync, "CLOUD_DIR", Path(tmp) / "cloud"), \
                patch.object(sync, "_cli_command", return_value=["synthetic-cli"]):
            source = Path(tmp) / "body.bin"
            source.write_bytes(b"{}")
            originals = (sync.subprocess.run, rollback.subprocess.run)
            sync.subprocess.run = rollback.subprocess.run = fake
            try:
                sync.client_put("snapshot:current", source)
                sync.client_get("snapshot:current")
                rollback.wrangler_kv_get("snapshot:current")
                rollback.wrangler_kv_put("snapshot:current", "{}")
            finally:
                sync.subprocess.run, rollback.subprocess.run = originals
        self.assertEqual(len(calls), 4)
        self.assertTrue(all("--remote" in call and "--local" not in call for call in calls), calls)

    def test_watchdog_reads_verified_global_liveness_and_retained_core_report(self):
        import sync_sealed_snapshot_kv as sync
        store = fake_store(reused=True)
        report_key = f"snapshot:{CORE}:v213:top20-report:latest"
        report = json.dumps({"records": [{"name": "合成"}] * 20, "generated_at": CORE_STAMP},
                            ensure_ascii=False).encode("utf-8")
        store[report_key] = report
        seal_key = f"snapshot:{RUN}:v213:snapshot-seal:v1"
        seal = json.loads(store[seal_key])
        seal["objects"]["v213:top20-report:latest"] = {"sha256": hashlib.sha256(report).hexdigest(), "utf8_bytes": len(report)}
        store[seal_key] = json.dumps(seal, separators=(",", ":")).encode("utf-8")
        pointer = json.loads(store["snapshot:current"])
        pointer["seal_sha256"] = hashlib.sha256(store[seal_key]).hexdigest()
        store["snapshot:current"] = json.dumps(pointer, separators=(",", ":")).encode("utf-8")
        calls = []

        def fake(args, **kwargs):
            calls.append(list(args))
            return subprocess.CompletedProcess(args, 0, store[args[4]].decode("utf-8"), "")

        with tempfile.TemporaryDirectory() as tmp, patch.object(sync, "CLOUD_DIR", Path(tmp)), \
                patch.object(sync, "_cli_command", return_value=["synthetic-cli"]), \
                patch.object(sync.subprocess, "run", side_effect=fake):
            outcome = Path(tmp) / "outcome.json"
            with patch.object(sys, "argv", ["sync", "--read-freshness", "--outcome-path", str(outcome)]), \
                    contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(sync.main(), 0)
            record = json.loads(outcome.read_text(encoding="utf-8"))
        self.assertEqual((record["operation"], record["status"], record["top20_state"]), ("WATCHDOG", "SUCCEEDED", "RECORDS_20"))
        self.assertEqual(record["anchor"], "2026-09-25T12:56:15+00:00")
        self.assertEqual(record["report_generated_at"], "2026-09-25T10:56:15+00:00")
        self.assertEqual(record["public_data_as_of"], "2026-09-25T10:56:15+00:00")
        self.assertEqual(record["core_run_id"], CORE)
        self.assertIn(report_key, [call[4] for call in calls])
        self.assertNotIn(f"snapshot:{RUN}:v213:top20-report:latest", [call[4] for call in calls])
        self.assertTrue(all(call[1:4] == ["kv", "key", "get"] and "--remote" in call and "--local" not in call for call in calls))


class LiveSnapshotCopyTests(unittest.TestCase):
    def test_copies_exact_bytes_and_verifies_the_seal(self):
        store = fake_store()
        with tempfile.TemporaryDirectory() as tmp:
            result = live.copy_snapshot(store.__getitem__, Path(tmp))
            index = json.loads((Path(tmp) / "index.json").read_text(encoding="utf-8"))
            self.assertEqual(result, {"run_id": RUN, "core_run_id": RUN,
                "seal_sha256": json.loads(store["snapshot:current"])["seal_sha256"], "pipeline_liveness_at": STAMP,
                "objects": len(store) - 2, "seal_mismatches": []})
            self.assertEqual(set(index), set(store))
            self.assertTrue(all((Path(tmp) / name).read_bytes() == store[key] for key, name in index.items()))

    def test_reports_seal_mismatch_and_rejects_bad_run_id(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(live.copy_snapshot(fake_store(tamper=True).__getitem__, Path(tmp) / "bad-body")["seal_mismatches"],
                             ["v213:top20-report:latest"])
            with self.assertRaises(ValueError):
                live.copy_snapshot({"snapshot:current": b'{"run_id":"../x"}'}.__getitem__, Path(tmp) / "bad-run")

    def test_remote_getter_always_passes_remote(self):
        calls = []
        original = live.subprocess.run
        live.subprocess.run = lambda args, **kw: calls.append(args) or subprocess.CompletedProcess(args, 0, b"{}", b"")
        try:
            with patch.object(live.sync, "_cli_command", return_value=["NODE", "LOCKED_WRANGLER_JS"]):
                live.remote_getter()("snapshot:current")
        finally:
            live.subprocess.run = original
        self.assertEqual(calls[0][:2], ["NODE", "LOCKED_WRANGLER_JS"])  # the sync's locked CLI, never npx --yes
        self.assertEqual([part for part in calls[0] if "npx" in part or part == "--yes"], [])
        self.assertIn("--remote", calls[0])
        self.assertNotIn("put", calls[0])

    def test_copies_reused_core_and_fresh_lazy_bodies_with_distinct_verified_identities(self):
        store = fake_store(reused=True)
        reads = []

        def get(key):
            reads.append(key)
            return store[key]

        with tempfile.TemporaryDirectory() as tmp:
            result = live.copy_snapshot(get, Path(tmp))
            index = json.loads((Path(tmp) / "index.json").read_text(encoding="utf-8"))
            self.assertEqual((result["run_id"], result["core_run_id"], result["seal_mismatches"]), (RUN, CORE, []))
            self.assertEqual(set(index), set(store))
            self.assertEqual([key for key in reads if key.startswith(f"snapshot:{RUN}:")],
                             [f"snapshot:{RUN}:v213:snapshot-seal:v1", f"snapshot:{RUN}:last_successful_pipeline_timestamp"])
            self.assertEqual(store[f"snapshot:{RUN}:{live.LIVENESS_KEY}"].decode(), STAMP)
            self.assertEqual(json.loads(store["snapshot:current"])["public_data_as_of"], CORE_STAMP)
            self.assertEqual(json.loads(store[f"snapshot:{CORE}:v213:activation-claim"])["claimed_at"], CORE_STAMP)
            self.assertEqual(reads.count("snapshot:current"), 2)
            for key, filename in index.items():
                self.assertEqual((Path(tmp) / filename).read_bytes(), store[key])

    def test_root_metadata_hash_and_claim_substitution_fail_before_writing_a_copy(self):
        root_key = f"snapshot:{RUN}:v213:snapshot-seal:v1"
        for mode in ("root_hash", "partial", "wrong_global", "wrong_core", "unknown_extension", "claim_run", "claim_time",
                     "missing_global_liveness", "old_global_liveness"):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as tmp:
                store = fake_store(reused=True)
                root = json.loads(store[root_key])
                pointer = json.loads(store["snapshot:current"])
                if mode == "partial":
                    del root["ranking_persisted_at"]
                elif mode == "wrong_global":
                    root["run_id"] = CORE
                elif mode == "wrong_core":
                    root["core_run_id"] = RUN
                elif mode == "unknown_extension":
                    root["unreviewed"] = True
                elif mode in ("claim_run", "claim_time"):
                    claim_key = f"snapshot:{CORE}:v213:activation-claim"
                    claim = json.loads(store[claim_key])
                    claim["run_id" if mode == "claim_run" else "claimed_at"] = RUN if mode == "claim_run" else STAMP
                    store[claim_key] = json.dumps(claim, separators=(",", ":")).encode("utf-8")
                    root["objects"]["v213:activation-claim"] = {"sha256": hashlib.sha256(store[claim_key]).hexdigest(),
                                                              "utf8_bytes": len(store[claim_key])}
                elif mode == "missing_global_liveness":
                    store[f"snapshot:{CORE}:{live.LIVENESS_KEY}"] = store.pop(f"snapshot:{RUN}:{live.LIVENESS_KEY}")
                elif mode == "old_global_liveness":
                    body = CORE_STAMP.encode("utf-8")
                    store[f"snapshot:{RUN}:{live.LIVENESS_KEY}"] = body
                    root["objects"][live.LIVENESS_KEY] = {"sha256": hashlib.sha256(body).hexdigest(), "utf8_bytes": len(body)}
                store[root_key] = json.dumps(root, separators=(",", ":")).encode("utf-8")
                pointer["seal_sha256"] = "f" * 64 if mode == "root_hash" else hashlib.sha256(store[root_key]).hexdigest()
                store["snapshot:current"] = json.dumps(pointer, separators=(",", ":")).encode("utf-8")
                out = Path(tmp) / "copy"
                with self.assertRaises((ValueError, LookupError)):
                    live.copy_snapshot(store.__getitem__, out)
                self.assertFalse(out.exists())

    def test_length_is_checked_even_when_body_sha_matches_and_pointer_movement_is_refused(self):
        store = fake_store()
        root_key = f"snapshot:{RUN}:v213:snapshot-seal:v1"
        root = json.loads(store[root_key])
        root["objects"]["v213:top20-report:latest"]["utf8_bytes"] += 1
        store[root_key] = json.dumps(root, separators=(",", ":")).encode("utf-8")
        pointer = json.loads(store["snapshot:current"])
        pointer["seal_sha256"] = hashlib.sha256(store[root_key]).hexdigest()
        store["snapshot:current"] = json.dumps(pointer, separators=(",", ":")).encode("utf-8")
        with tempfile.TemporaryDirectory() as tmp:
            result = live.copy_snapshot(store.__getitem__, Path(tmp) / "length")
            self.assertEqual(result["seal_mismatches"], ["v213:top20-report:latest"])
            reads = 0

            def moved(key):
                nonlocal reads
                if key == "snapshot:current":
                    reads += 1
                    if reads > 1:
                        return store[key] + b" "
                return store[key]

            with self.assertRaisesRegex(ValueError, "LIVE_POINTER_MOVED"):
                live.copy_snapshot(moved, Path(tmp) / "moved")
            self.assertFalse((Path(tmp) / "moved").exists())


class ReplayAcceptanceTests(unittest.TestCase):
    """State-aware replay acceptance (T6): record count, report age and the INSUFFICIENT state, in PS 5.1 and 7."""

    EXPIRED_REUSED = {"fresh": False, "top20_records": 0, "report_generated_at": None, "broadcast_ready": False,
                      "expected_core": CORE, "run_id": CORE, "legacy_report_expired_refused": True,
                      "pipeline_liveness_fresh": True, "legacy_age_hours": 48, "refusal_is_insufficient": False,
                      "guidance_machine_probe": "REFUSED", "guidance_machine_dated_facts_only": True}

    CASES = {
        # name: (replay fields, expected records, expected verdict prefix)
        "carried_20": ({"fresh": True, "top20_records": 20, "age_hours": 3}, 20, "PASS"),
        "golden_2_without_expectation": ({"fresh": True, "top20_records": 2, "age_hours": 0.1}, 0, "PASS"),
        "golden_2_when_20_expected": ({"fresh": True, "top20_records": 2, "age_hours": 0.1}, 20, "TOP20_RECORDS 2 expected 20"),
        "stale_report": ({"fresh": True, "top20_records": 20, "age_hours": 15}, 20, "REPORT_AGE"),
        "insufficient_without_expectation": ({"fresh": False, "refusal_is_insufficient": True}, 0, "PASS_INSUFFICIENT"),
        "insufficient_when_20_expected": ({"fresh": False, "refusal_is_insufficient": True}, 20, "TOP20_NOT_FRESH"),
        "other_refusal": ({"fresh": False, "refusal_is_insufficient": False}, 0, "READER_REPLAY_NOT_FRESH"),
        "old_reader": ({"fresh": True, "top20_records": 20, "age_hours": 1, "reader_contract_version": "v1"}, 0,
                       "READER_CONTRACT_VERSION"),
        "previous_v3_reader": ({"fresh": True, "top20_records": 20, "age_hours": 1, "reader_contract_version": "v213-reader-replay-v3"}, 0,
                               "READER_CONTRACT_VERSION"),
        "previous_v4_reader": ({"fresh": True, "top20_records": 20, "age_hours": 1, "reader_contract_version": "v213-reader-replay-v4"}, 0,
                               "READER_CONTRACT_VERSION"),
        "reused_core": ({"fresh": True, "top20_records": 20, "age_hours": 1, "expected_core": CORE, "run_id": CORE}, 20, "PASS"),
        "global_cannot_replace_core": ({"fresh": True, "top20_records": 20, "age_hours": 1, "expected_core": CORE}, 20, "REPLAY_RUN_MISMATCH"),
        "core_cannot_replace_global": ({"fresh": True, "top20_records": 20, "age_hours": 1, "expected_core": CORE, "run_id": CORE,
                                       "seal_run_id": CORE}, 20, "REPLAY_RUN_MISMATCH"),
        "missing_global": ({"fresh": True, "top20_records": 20, "age_hours": 1, "seal_run_id": None}, 20, "REPLAY_RUN_MISMATCH"),
        "missing_seal_hash": ({"fresh": True, "top20_records": 20, "age_hours": 1, "drop_hash": True}, 20, "REPLAY_SEAL_MISMATCH"),
        "wrong_seal_hash": ({"fresh": True, "top20_records": 20, "age_hours": 1, "seal_sha256": "b" * 64}, 20, "REPLAY_SEAL_MISMATCH"),
        "same_ids_different_seal": ({"fresh": True, "top20_records": 20, "age_hours": 1, "expected_core": CORE, "run_id": CORE,
                                     "seal_sha256": "c" * 64}, 20, "REPLAY_SEAL_MISMATCH"),
        "expired_reused_facts_only": ({**EXPIRED_REUSED}, 0, "PASS_REUSED_CORE"),
        "expired_reused_explicit_record_count": ({**EXPIRED_REUSED}, 20, "TOP20_NOT_FRESH"),
        "expired_reused_wrong_hash": ({**EXPIRED_REUSED, "seal_sha256": "b" * 64}, 0, "REPLAY_SEAL_MISMATCH"),
        "expired_reused_broken_binding": ({**EXPIRED_REUSED, "guidance_machine_dated_facts_only": False}, 0, "GUIDANCE_MACHINE_BINDING"),
        "expired_reused_stale_pipeline": ({**EXPIRED_REUSED, "pipeline_liveness_fresh": False}, 0, "READER_REPLAY_NOT_FRESH"),
        "expired_reused_not_actually_old": ({**EXPIRED_REUSED, "legacy_age_hours": 1}, 0, "READER_REPLAY_NOT_FRESH"),
        "expired_reused_broadcast_regression": ({**EXPIRED_REUSED, "broadcast_ready": True}, 0, "READER_REPLAY_NOT_FRESH"),
        "new_core_cannot_excuse_legacy_expiry": ({**EXPIRED_REUSED, "expected_core": RUN, "run_id": RUN,
                                               "guidance_machine_probe": "ABSENT"}, 0, "READER_REPLAY_NOT_FRESH"),
        "new_core_dated_facts_are_not_machine_admission": ({"fresh": True, "top20_records": 20, "age_hours": 1,
                    "guidance_machine_probe": "REFUSED", "guidance_machine_dated_facts_only": True}, 20, "GUIDANCE_MACHINE_BINDING"),
        "machine_binding_refused": ({"fresh": True, "top20_records": 20, "age_hours": 1, "guidance_machine_probe": "REFUSED"}, 20,
                                    "GUIDANCE_MACHINE_BINDING"),
        "machine_binding_admitted": ({"fresh": True, "top20_records": 20, "age_hours": 1, "guidance_machine_probe": "ADMITTED"}, 20,
                                     "PASS"),
        "machine_binding_absent": ({"fresh": True, "top20_records": 20, "age_hours": 1, "guidance_machine_probe": "ABSENT"}, 20,
                                   "PASS"),
        "other_run": ({"fresh": True, "top20_records": 20, "age_hours": 1, "run_id": "20260101T000000Z-000000000000"}, 0,
                      "REPLAY_RUN_MISMATCH"),
    }

    def test_verdicts(self):
        from datetime import datetime, timedelta, timezone
        shells = [s for s in ("powershell", "pwsh") if shutil.which(s)]
        if not shells:
            self.skipTest("PowerShell not available")
        functions = "".join(re.search(rf"function {name}.*?\n}}\n", GATE, re.S).group(0)
                            for name in ("ConvertTo-UtcAnchor", "Test-ReplayAcceptance"))
        probe = functions
        now = datetime.now(timezone.utc)
        for name, (fields, expected, _) in self.CASES.items():
            replay = {"reader_contract_version": "v213-reader-replay-v5", "run_id": RUN, "seal_run_id": RUN,
                      "seal_sha256": "a" * 64, "integrity": "sealed", "macro_overview_sealed": True,
                      **{k: v for k, v in fields.items() if k not in ("age_hours", "expected_core", "drop_hash", "legacy_age_hours")}}
            if fields.get("drop_hash"):
                del replay["seal_sha256"]
            if "age_hours" in fields:
                replay["report_generated_at"] = (now - timedelta(hours=fields["age_hours"])).strftime("%Y-%m-%dT%H:%M:%S.000Z")
            if "legacy_age_hours" in fields:
                replay["legacy_report_original_generated_at"] = (now - timedelta(hours=fields["legacy_age_hours"])).strftime("%Y-%m-%dT%H:%M:%S.000Z")
            probe += (f"$r = '{json.dumps(replay)}' | ConvertFrom-Json\n"
                      f"'{name}=' + (Test-ReplayAcceptance $r '{RUN}' '{fields.get('expected_core', RUN)}' '{'a' * 64}' {expected} 50400)\n")
        for shell in shells:
            out = subprocess.run([shell, "-NoProfile", "-NonInteractive", "-Command", probe], capture_output=True,
                                 text=True, timeout=120)
            verdicts = dict(line.split("=", 1) for line in out.stdout.splitlines() if "=" in line)
            for name, (_, _, prefix) in self.CASES.items():
                self.assertTrue(verdicts.get(name, "").startswith(prefix), (shell, name, verdicts.get(name), out.stderr[-400:]))
            self.assertEqual(verdicts["carried_20"], "PASS", shell)

    def test_gate_uses_the_acceptance_and_records_the_config(self):
        self.assertIn("Test-ReplayAcceptance $replay $expectedGlobalRunId $expectedCoreRunId $expectedSealSha256 $ExpectTop20Records $reportMaxAge", GATE)
        self.assertLess(GATE.index("$expectedSealSha256 = [string]$copied.seal_sha256"), GATE.index("$vitest run test/live-kv-replay.test.ts"))
        self.assertIn("[string]$sealHash.Value -cne $SealSha256", GATE)
        self.assertIn("[string]$copied.seal_sha256 -cne [string]$Pointer.seal_sha256", GATE)
        self.assertIn("[string]$Replay.run_id -cne $CoreRunId", GATE)
        self.assertIn("[string]$globalIdentity.Value -cne $RunId", GATE)
        self.assertIn("v213-top20-report-freshness-v1.json", GATE)
        self.assertIn("Get-FileHash -LiteralPath $configPath -Algorithm SHA256", GATE)
        self.assertIn("[int]$ExpectTop20Records = 0", GATE)


class LazyKeyParityTests(unittest.TestCase):
    def test_gate_copy_knows_every_lazy_key_the_worker_seals(self):
        import fetch_live_public_snapshot as fetcher
        worker = (ROOT / "cloud" / "src" / "v213" / "snapshot-seal.ts").read_text(encoding="utf-8")
        pattern = re.search(r"SNAPSHOT_LAZY_KEY_RE = /(.+)/;", worker).group(1)
        for key in ("v213:identity:v2:sym:R", "v213:identity:v2:name:15", "v213:quotes:v1", "v213:options:v2",
                    "v213:bottleneck-top20:v3", "v213:prices:v1:UK", "v213:prices:v1:TAIWAN"):
            self.assertTrue(re.fullmatch(pattern, key), key)
            self.assertTrue(fetcher.LAZY_KEY.fullmatch(key), key)
        for key in ("v213:prices:v1:MARS", "v213:top20-report:latest"):
            self.assertFalse(re.fullmatch(pattern, key), key)
            self.assertFalse(fetcher.LAZY_KEY.fullmatch(key), key)


class SyncLedgerTests(unittest.TestCase):
    """KV growth is bounded: run keys and blobs carry an expiry, the pointer none; a blob this machine stored recently
    is reused without any KV call; the ledger only records blobs after the pointer moved."""

    def test_ttls_and_ledger_reuse(self):
        import sync_sealed_snapshot_kv as sync
        store: dict[str, str] = {}
        puts: list[tuple[str, int | None]] = []

        def put(key, path, ttl=None):
            puts.append((key, ttl))
            store[key] = Path(path).read_bytes().decode("utf-8")
            return True

        blob_body = '{"x": 1}'
        blob_key = "blob:v1:" + sync.sha(blob_body)
        run_key = "snapshot:20260926T010000Z-aaaaaaaaaaaa:v213:top20-report:latest"
        objects = {run_key: "run-body", blob_key: blob_body}
        pointer = json.dumps({"run_id": "20260926T010000Z-aaaaaaaaaaaa", "seal_sha256": "ab" * 32})
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp) / "20260926T010000Z-aaaaaaaaaaaa"
            run_dir.mkdir()
            (run_dir / "objects.json").write_text(json.dumps(objects), encoding="utf-8")
            (run_dir / "pointer.raw.json").write_text(pointer, encoding="utf-8")
            saved = (sync.client_put, sync.client_get, sync.LEDGER, sys.argv)
            sync.client_put, sync.client_get, sync.LEDGER = put, store.get, Path(tmp) / "ledger.json"
            sys.argv = ["sync", "--run-dir", str(run_dir)]
            try:
                with contextlib.redirect_stdout(io.StringIO()):
                    self.assertEqual(sync.main(), 0)
                self.assertEqual(dict(puts), {run_key: sync.RUN_KEY_TTL_SECONDS, blob_key: sync.BLOB_TTL_SECONDS,
                                              "snapshot:current": None})
                self.assertIn(blob_key[len("blob:v1:"):], json.loads((Path(tmp) / "ledger.json").read_text(encoding="utf-8")))
                self.assertFalse((run_dir / ".kv-stage").exists())
                puts.clear()
                with contextlib.redirect_stdout(io.StringIO()):
                    self.assertEqual(sync.main(), 0)
                self.assertEqual(dict(puts), {run_key: sync.RUN_KEY_TTL_SECONDS, "snapshot:current": None})
                self.assertNotIn(blob_key, dict(puts))  # reuse avoids PUT; readback is still mandatory
            finally:
                sync.client_put, sync.client_get, sync.LEDGER, sys.argv = saved


class SyncRetryTests(unittest.TestCase):
    """A transient Cloudflare/network failure is retried (bounded); the final error is summarised without ids."""

    def test_put_retries_then_succeeds_and_gives_up_after_three(self):
        import sync_sealed_snapshot_kv as sync
        calls = []
        outcomes = []
        # Entirely synthetic diagnostic, never an account ID or credential.
        diagnostic = "ECONNRESET SYNTHETIC_PRIVATE_DIAGNOSTIC"

        def fake(args, **kw):
            calls.append(list(args))
            code = outcomes.pop(0)
            return subprocess.CompletedProcess(args, code, "{}", "" if code == 0 else diagnostic)

        with tempfile.TemporaryDirectory() as tmp, \
                patch.object(sync, "CLOUD_DIR", Path(tmp)), \
                patch.object(sync, "_cli_command", return_value=["synthetic-cli"]), \
                patch.object(sync.subprocess, "run", side_effect=fake), \
                patch.object(sync.time, "sleep") as sleep:
            source = Path(tmp) / "body.json"
            source.write_text("{}", encoding="utf-8")
            self.assertEqual(sync.ATTEMPTS, 3)
            outcomes[:] = [1, 1, 0]
            self.assertTrue(sync.client_put("snapshot:current", source))
            self.assertEqual(len(calls), 3)
            self.assertEqual(outcomes, [])
            self.assertEqual(sync.LAST_CALL, dict(attempts=3, exit_code=0, error_category="NONE"))
            self.assertEqual([call.args[0] for call in sleep.call_args_list],
                             [sync.RETRY_SECONDS, 2 * sync.RETRY_SECONDS])
            self.assertTrue(all("--remote" in call and "--local" not in call for call in calls))
            calls.clear()
            sleep.reset_mock()
            outcomes[:] = [1, 1, 1]
            self.assertFalse(sync.client_put("snapshot:current", source))
            self.assertEqual(len(calls), 3)
            self.assertEqual(outcomes, [])
            self.assertEqual(sync.LAST_ERROR, ["NETWORK_FAILURE"])
            self.assertEqual(sync.LAST_CALL, dict(attempts=3, exit_code=1, error_category="NETWORK_FAILURE"))
            self.assertEqual(sleep.call_count, 2)
            self.assertTrue(all("--remote" in call and "--local" not in call for call in calls))
            for diagnostic, category in (("SYNTHETIC_PRIVATE_DIAGNOSTIC", "UNKNOWN"),
                                         ("[ERROR] free usage limit SYNTHETIC_PRIVATE_DIAGNOSTIC", "DAILY_KV_LIMIT")):
                with self.subTest(category=category):
                    calls.clear()
                    sleep.reset_mock()
                    outcomes[:] = [1, 0]
                    self.assertFalse(sync.client_put("snapshot:current", source))
                    self.assertEqual(len(calls), 1)
                    self.assertEqual(outcomes, [0])  # terminal: the would-be success is never consumed
                    sleep.assert_not_called()
                    self.assertEqual(sync.LAST_ERROR, [category])
                    self.assertEqual(sync.LAST_CALL, dict(attempts=1, exit_code=1, error_category=category))
                    self.assertNotIn("SYNTHETIC_PRIVATE_DIAGNOSTIC", json.dumps(sync.LAST_CALL))
                    self.assertIn("--remote", calls[0])
                    self.assertNotIn("--local", calls[0])
            # A rejected credential (the invocation that refreshed the OAuth token, 2026-10-16/17) is retried with the same
            # credential under the same bound and the longer wait; it stays AUTHENTICATION_ERROR when every attempt is rejected.
            diagnostic = "AuthenticationError: SYNTHETIC_PRIVATE_DIAGNOSTIC"
            for codes, accepted in (([1, 0], True), ([1, 1, 1], False)):
                with self.subTest(credential_rejections=codes):
                    calls.clear()
                    sleep.reset_mock()
                    outcomes[:] = list(codes)
                    self.assertEqual(sync.client_put("snapshot:current", source), accepted)
                    self.assertEqual((len(calls), outcomes), (len(codes), []))
                    self.assertEqual([call.args[0] for call in sleep.call_args_list],
                                     [sync.AUTH_RETRY_SECONDS * attempt for attempt in range(1, len(codes))])
                    expected = dict(attempts=len(codes), exit_code=0, error_category="NONE") if accepted else \
                        dict(attempts=3, exit_code=1, error_category="AUTHENTICATION_ERROR")
                    self.assertEqual(sync.LAST_CALL, expected)
                    self.assertNotIn("SYNTHETIC_PRIVATE_DIAGNOSTIC", json.dumps(sync.LAST_CALL))


if __name__ == "__main__":
    unittest.main()
