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
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import fetch_live_public_snapshot as live  # noqa: E402

GATE = (ROOT / "scripts" / "deploy_production_gate.ps1").read_text(encoding="utf-8")
RUN = "20260925T125615Z-92f5d828bc6c"


def fake_store(tamper: bool = False) -> dict[str, bytes]:
    body = '{"records":["合成"]}'.encode("utf-8")
    seal = {"objects": {"v213:top20-report:latest": {"sha256": hashlib.sha256(body).hexdigest(), "utf8_bytes": len(body)}}}
    return {"snapshot:current": json.dumps({"run_id": RUN}).encode(),
            f"snapshot:{RUN}:v213:snapshot-seal:v1": json.dumps(seal).encode(),
            f"snapshot:{RUN}:v213:top20-report:latest": body + (b" " if tamper else b"")}


class GateContractTests(unittest.TestCase):
    def test_gate_reads_production_and_never_writes_kv(self):
        reads = re.findall(r"wrangler kv key get[^\n]*", GATE)
        self.assertTrue(reads)
        self.assertTrue(all("--remote" in line for line in reads))
        self.assertNotRegex(GATE, r"kv key put|kv bulk|kv key delete")

    def test_replay_uses_live_bytes_not_a_leftover_file(self):
        self.assertNotIn("test-live-replay-result.json", GATE)
        self.assertIn("live-kv-replay.test.ts", GATE)
        self.assertIn("fetch_live_public_snapshot.py", GATE)
        self.assertIn("-eq [string]$PostPointer.run_id", GATE)

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


class ProductionKvAddressingTests(unittest.TestCase):
    """Every production KV command names Production explicitly; the local store is never a silent target."""

    def test_sync_and_rollback_pass_remote_on_every_kv_command(self):
        import rollback_sealed_snapshot as rollback
        import sync_sealed_snapshot_kv as sync
        calls = []
        fake = lambda args, **kw: calls.append(list(args)) or subprocess.CompletedProcess(args, 0, "{}", "")
        (ROOT / "data" / "cache").mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=ROOT / "data" / "cache") as tmp:  # sync stages repo-relative paths
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

    def test_watchdog_reads_production_with_the_gate_anchor_parser(self):
        watchdog = (ROOT / "scripts" / "freshness_watchdog.ps1").read_text(encoding="utf-8")
        reads = re.findall(r"wrangler kv key get[^\n]*", watchdog)
        self.assertTrue(reads and all("--remote" in line for line in reads))
        self.assertNotRegex(watchdog, r"kv key put|kv bulk|kv key delete")
        parser = re.compile(r"function ConvertTo-UtcAnchor.*?\n}\n", re.S)
        self.assertEqual(parser.search(watchdog).group(0), parser.search(GATE).group(0))


class LiveSnapshotCopyTests(unittest.TestCase):
    def test_copies_exact_bytes_and_verifies_the_seal(self):
        store = fake_store()
        with tempfile.TemporaryDirectory() as tmp:
            result = live.copy_snapshot(store.__getitem__, Path(tmp))
            index = json.loads((Path(tmp) / "index.json").read_text(encoding="utf-8"))
            self.assertEqual(result, {"run_id": RUN, "objects": 1, "seal_mismatches": []})
            self.assertEqual(set(index), set(store))
            self.assertTrue(all((Path(tmp) / name).read_bytes() == store[key] for key, name in index.items()))

    def test_reports_seal_mismatch_and_rejects_bad_run_id(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(live.copy_snapshot(fake_store(tamper=True).__getitem__, Path(tmp))["seal_mismatches"],
                             ["v213:top20-report:latest"])
            with self.assertRaises(ValueError):
                live.copy_snapshot({"snapshot:current": b'{"run_id":"../x"}'}.__getitem__, Path(tmp))

    def test_remote_getter_always_passes_remote(self):
        calls = []
        original = live.subprocess.run
        live.subprocess.run = lambda args, **kw: calls.append(args) or subprocess.CompletedProcess(args, 0, b"{}", b"")
        try:
            live.remote_getter()("snapshot:current")
        finally:
            live.subprocess.run = original
        self.assertIn("--remote", calls[0])
        self.assertNotIn("put", calls[0])


if __name__ == "__main__":
    unittest.main()
