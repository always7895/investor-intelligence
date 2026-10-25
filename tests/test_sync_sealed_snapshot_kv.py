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
                "🪵  Logs were written to \"C:\\Users\\<user>\\AppData\\Roaming\\xdg.config\\.wrangler\\logs\\wrangler.log\"\n")


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

    def test_other_failures_keep_their_retries_and_safe_category(self):
        calls = []
        sync._run_cli = lambda args: calls.append(args) or completed(1, "✘ [ERROR] fetch failed for 0123456789abcdef0123456789abcdef")
        sync._run_with_retry(["kv", "key", "get"])
        self.assertEqual(len(calls), sync.ATTEMPTS)
        self.assertEqual(sync.LAST_ERROR, ["NETWORK_FAILURE"])


def get_failure(status: str) -> str:
    # The form wrangler 4.123 prints for a non-OK KV value GET (wrangler-dist fetchKVGetValueBase); synthetic ids.
    return ("✘ [ERROR] Failed to fetch https://api.cloudflare.com/client/v4/accounts/0123456789abcdef0123456789abcdef/storage/kv/"
            f"namespaces/fedcba9876543210fedcba9876543210/values/snapshot%3Acurrent - {status}\n\n")


UPSTREAM_STDERR = ("✘ [ERROR] A request to the Cloudflare API (/accounts/0123456789abcdef0123456789abcdef/storage/kv/namespaces/x/values/k)"
                   " failed.\n\n  Upstream service unavailable [code: 7009]\n\n")


class KvUpstreamUnavailableTests(unittest.TestCase):
    """V14: Cloudflare's code 7009 (Upstream service unavailable) is a named transient with the usual bounded retries."""

    def setUp(self):
        self.saved = (sync._run_cli, sync.time.sleep)
        self.sleeps = []
        sync.time.sleep = self.sleeps.append

    def tearDown(self):
        sync._run_cli, sync.time.sleep = self.saved

    def run_put(self, *results):
        queue = list(results)
        calls = []
        sync._run_cli = lambda args: calls.append(args) or queue.pop(0)
        return sync._run_with_retry(["kv", "key", "put", "k", "--path", "f", "--remote"]), calls, queue

    def test_code_7009_is_transient_and_the_next_attempt_publishes(self):
        self.assertEqual(sync.classify_cli_error("", UPSTREAM_STDERR), "TRANSIENT_HTTP")
        p, calls, queue = self.run_put(completed(1, UPSTREAM_STDERR), completed(0, ""))
        self.assertEqual((p.returncode, len(calls), queue), (0, 2, []))
        self.assertEqual(self.sleeps, [sync.RETRY_SECONDS])
        self.assertEqual(sync.LAST_CALL, dict(attempts=2, exit_code=0, error_category="NONE"))

    def test_a_persistent_7009_stops_at_the_bound(self):
        p, calls, queue = self.run_put(*[completed(1, UPSTREAM_STDERR)] * 4)
        self.assertEqual((p.returncode, len(calls), len(queue)), (1, sync.ATTEMPTS, 1))
        self.assertEqual(self.sleeps, [sync.RETRY_SECONDS, 2 * sync.RETRY_SECONDS])
        self.assertEqual(sync.LAST_ERROR, ["TRANSIENT_HTTP"])

    def test_credential_and_daily_limit_codes_keep_their_precedence(self):
        self.assertEqual(sync.classify_cli_error("", UPSTREAM_STDERR + "Authentication error [code: 10000]"), "AUTHENTICATION_ERROR")
        self.assertEqual(sync.classify_cli_error("", UPSTREAM_STDERR + LIMIT_STDERR), sync.KV_DAILY_LIMIT)


class KvGetFailureFormTests(unittest.TestCase):
    """V13: the KV GET failure form is classified by its status; a rejected credential is retried within the same bound."""

    def setUp(self):
        self.saved = (sync._run_cli, sync.time.sleep)
        self.sleeps = []
        sync.time.sleep = self.sleeps.append

    def tearDown(self):
        sync._run_cli, sync.time.sleep = self.saved

    def run_get(self, *results):
        queue = list(results)
        calls = []
        sync._run_cli = lambda args: calls.append(args) or queue.pop(0)
        p = sync._run_with_retry(["kv", "key", "get", "snapshot:current", "--remote"])
        return p, calls, queue

    def test_a_get_401_right_after_a_token_refresh_is_retried_with_the_same_credential(self):
        p, calls, queue = self.run_get(completed(1, get_failure("401: Unauthorized")),
                                       subprocess.CompletedProcess(["npx"], 0, stdout="{}", stderr=""))
        self.assertEqual((p.returncode, len(calls), queue), (0, 2, []))
        self.assertEqual(self.sleeps, [sync.AUTH_RETRY_SECONDS])
        self.assertEqual(sync.LAST_CALL, dict(attempts=2, exit_code=0, error_category="NONE"))

    def test_a_persistent_get_401_stops_at_the_bound_and_keeps_its_category(self):
        p, calls, queue = self.run_get(*[completed(1, get_failure("401: Unauthorized"))] * 4)
        self.assertEqual((p.returncode, len(calls), len(queue)), (1, sync.ATTEMPTS, 1))
        self.assertEqual(self.sleeps, [sync.AUTH_RETRY_SECONDS, 2 * sync.AUTH_RETRY_SECONDS])
        self.assertEqual(sync.LAST_ERROR, ["UNKNOWN"])
        self.assertEqual(sync.LAST_CALL, dict(attempts=3, exit_code=1, error_category="UNKNOWN"))

    def test_get_429_and_5xx_are_named_transients(self):
        for status in ("429: Too Many Requests", "500: Internal Server Error", "503: Service Unavailable"):
            with self.subTest(status=status):
                self.sleeps.clear()
                self.assertEqual(sync.classify_cli_error("", get_failure(status)), "TRANSIENT_HTTP")
                p, calls, _ = self.run_get(*[completed(1, get_failure(status))] * 3)
                self.assertEqual((p.returncode, len(calls)), (1, sync.ATTEMPTS))
                self.assertEqual(self.sleeps, [sync.RETRY_SECONDS, 2 * sync.RETRY_SECONDS])
                self.assertEqual(sync.LAST_ERROR, ["TRANSIENT_HTTP"])

    def test_other_get_statuses_stay_terminal_and_nothing_of_the_line_is_kept(self):
        for status in ("404: Not Found", "403: Forbidden", "400: Bad Request"):
            with self.subTest(status=status):
                self.sleeps.clear()
                p, calls, queue = self.run_get(completed(1, get_failure(status)), completed(0, ""))
                self.assertEqual((p.returncode, len(calls), len(queue)), (1, 1, 1))
                self.assertEqual(self.sleeps, [])
                self.assertEqual(sync.LAST_CALL, dict(attempts=1, exit_code=1, error_category="UNKNOWN"))
                self.assertNotIn("0123456789abcdef", repr((sync.LAST_CALL, sync.LAST_ERROR)))


if __name__ == "__main__":
    unittest.main()
