"""KV sync error handling: Cloudflare's free daily write limit is named in the log and not retried. No network."""
from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import sync_sealed_snapshot_kv as sync  # noqa: E402

LIMIT_STDERR = ("✘ [ERROR] A request to the Cloudflare API (/accounts/0123456789abcdef0123456789abcdef/storage/kv/namespaces/x/values/k)"
                " failed.\n  your account has reached the free usage limit for this operation for today [code: 10048]\n"
                "🪵  Logs were written to \"C:\\Users\\someone\\AppData\\Roaming\\xdg.config\\.wrangler\\logs\\wrangler.log\"\n")


def completed(code: int, stderr: str) -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(["npx"], code, stdout="", stderr=stderr)


class DailyLimitTests(unittest.TestCase):
    def setUp(self):
        self.saved = (sync._run_cli, sync.RETRY_SECONDS)
        sync.RETRY_SECONDS = 0.0

    def tearDown(self):
        sync._run_cli, sync.RETRY_SECONDS = self.saved

    def test_the_daily_write_limit_is_named_and_not_retried(self):
        calls = []
        sync._run_cli = lambda args: calls.append(args) or completed(1, LIMIT_STDERR)
        self.assertEqual(sync._run_with_retry(["kv", "key", "put"]).returncode, 1)
        self.assertEqual(len(calls), 1)
        self.assertEqual(sync.LAST_ERROR, [sync.KV_DAILY_LIMIT])

    def test_other_failures_keep_their_retries_and_masked_last_line(self):
        calls = []
        sync._run_cli = lambda args: calls.append(args) or completed(1, "✘ [ERROR] fetch failed for 0123456789abcdef0123456789abcdef")
        sync._run_with_retry(["kv", "key", "get"])
        self.assertEqual(len(calls), sync.ATTEMPTS)
        self.assertEqual(sync.LAST_ERROR, ["✘ [ERROR] fetch failed for <id>"])


if __name__ == "__main__":
    unittest.main()
