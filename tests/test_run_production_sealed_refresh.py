"""Hourly sealed refresh: native stderr is logged, never fatal; the sync gets exactly the run the publisher printed;
every failure is written to the log (regression 2026-09-25 15:56Z: a stderr line under Windows PowerShell 5.1 with
ErrorActionPreference Stop aborted the run after publish with no log line, and the pointer aged).

Runs a copy of the script against stub publish/sync/lock scripts; the real operation lock is never taken."""
from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "run_production_sealed_refresh.ps1"
RUN_ID = "20260926T000000Z-0123456789ab"
LOCK_STUB = "function Enter-V213OperationLock { param($Owner, $TimeoutSeconds) $true }\nfunction Exit-V213OperationLock { }\n"
PUBLISH_OK = (f'import sys\nprint("{{")\nprint(\'  "run_id": "{RUN_ID}",\')\nprint("}}")\n'
              'print("SyntheticWarning: noisy stderr line", file=sys.stderr)\n')
PUBLISH_NO_RUN = 'print("{}")\n'
SYNC_OK = 'import sys\nprint("SYNCED " + sys.argv[-1])\nprint("wrangler notice on stderr", file=sys.stderr)\n'
SYNC_FAIL = 'import sys\nprint("Traceback: synthetic failure", file=sys.stderr)\nsys.exit(3)\n'


def shells() -> list[str]:
    return [shell for shell in ("powershell", "pwsh") if shutil.which(shell)]


class HourlyRefreshScriptTests(unittest.TestCase):
    def run_copy(self, shell: str, publish: str, sync: str) -> tuple[int, str]:
        with tempfile.TemporaryDirectory() as tmp:
            scripts = Path(tmp) / "scripts"
            scripts.mkdir()
            shutil.copy(SCRIPT, scripts / SCRIPT.name)
            (scripts / "v213_operation_lock.ps1").write_text(LOCK_STUB, encoding="utf-8")
            (scripts / "run_daily_data_refresh.ps1").write_text("exit 0\n", encoding="utf-8")
            (scripts / "publish_sealed_snapshot.py").write_text(publish, encoding="utf-8")
            (scripts / "sync_sealed_snapshot_kv.py").write_text(sync, encoding="utf-8")
            done = subprocess.run([shell, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File",
                                   str(scripts / SCRIPT.name)], capture_output=True, timeout=180)
            log = (Path(tmp) / "data" / "cache" / "sealed-refresh.log").read_text(encoding="utf-8", errors="replace")
            return done.returncode, log

    def test_stderr_is_logged_and_the_printed_run_is_synced(self):
        if not shells():
            self.skipTest("PowerShell not available")
        for shell in shells():
            code, log = self.run_copy(shell, PUBLISH_OK, SYNC_OK)
            self.assertEqual(code, 0, (shell, log))
            self.assertIn("SyntheticWarning: noisy stderr line", log)
            self.assertIn(f"SYNCED ", log)
            self.assertIn(RUN_ID, log.split("SYNCED ", 1)[1].splitlines()[0])
            self.assertIn(f"REFRESH OK run={RUN_ID} pointer last", log)

    def test_sync_failure_and_missing_run_id_are_logged(self):
        if not shells():
            self.skipTest("PowerShell not available")
        for shell in shells():
            code, log = self.run_copy(shell, PUBLISH_OK, SYNC_FAIL)
            self.assertEqual(code, 3, (shell, log))
            self.assertIn("Traceback: synthetic failure", log)
            self.assertIn("SYNC FAILED exit=3", log)
            code, log = self.run_copy(shell, PUBLISH_NO_RUN, SYNC_OK)
            self.assertNotEqual(code, 0)
            self.assertIn("GENERATE FAILED run id not printed", log)
            self.assertNotIn("SYNCED", log)

    def test_no_newest_folder_guess(self):
        text = SCRIPT.read_text(encoding="utf-8")
        self.assertNotIn("Sort-Object LastWriteTime", text)
        self.assertIn("Invoke-LoggedNative", text)


if __name__ == "__main__":
    unittest.main()
