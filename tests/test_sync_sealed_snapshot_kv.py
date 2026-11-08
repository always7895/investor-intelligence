"""KV sync error handling: Cloudflare's free daily write limit is named in the log and not retried. No network."""
from __future__ import annotations

import subprocess
import sys
import unittest
import json
from unittest import mock
from tests.sealed_kv_fakes import (
    NETWORK, WRITE_THEN_FAIL, OLD_POINTER, POINTER_KEY, RUN, FakeKV, Fixture, KvTestCase, run_sy,
)
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



class FailureDetailTests(KvTestCase):
    def setUp(self):
        super().setUp()
        self.saved_detail = dict(sync.LAST_CALL_DETAIL)
        self.saved_call = dict(sync.LAST_CALL)
        self.saved_attempts = sync.TOTAL_ATTEMPTS
        self.saved_error = list(sync.LAST_ERROR)
        self.addCleanup(self.restore_globals)
        self.kv = FakeKV({POINTER_KEY: OLD_POINTER})
        self.ledger = self.tmp / "ledger.json"

    def restore_globals(self):
        sync.LAST_CALL_DETAIL.clear()
        sync.LAST_CALL_DETAIL.update(self.saved_detail)
        sync.LAST_CALL.clear()
        sync.LAST_CALL.update(self.saved_call)
        sync.TOTAL_ATTEMPTS = self.saved_attempts
        sync.LAST_ERROR[:] = self.saved_error

    def fixture(self):
        fixture = Fixture(RUN, "sy")
        fixture.write_to(self.tmp / "run")
        return fixture

    def run_fixture(self, fixture, failed_key=None, failure_text=None):
        def cli(args):
            result = self.kv.fake_run(["synthetic-cli", *args])
            if result.returncode != 0 and args[3] == failed_key and failure_text is not None:
                result.stderr = failure_text
            return result
        with mock.patch.object(sync, "_run_cli", side_effect=cli):
            return run_sy(sync, self.kv, self.tmp / "run", self.ledger, fixture.names, seam="B")

    def assert_detail(self, record, kind, status, code, attempts):
        self.assertEqual(record["failed_objects"], [{
            "key_kind": kind, "http_status": status, "provider_code": code, "attempt_count": attempts,
        }])

    def test_explicit_numeric_markers_and_failed_envelope(self):
        self.assertEqual(sync._cli_failure_detail("", "HTTP status: 504 [code: 7009]"),
                         {"http_status": 504, "provider_code": 7009})
        envelope = json.dumps({"success": False, "status": 401, "errors": [{"code": 10000, "message": "private-body"}]})
        self.assertEqual(sync._cli_failure_detail(envelope, ""),
                         {"http_status": 401, "provider_code": 10000})
        self.assertEqual(sync._cli_failure_detail("", "Failed to fetch opaque-endpoint - 503: unavailable [code: 7009]"),
                         {"http_status": 503, "provider_code": 7009})

    def test_missing_conflicting_and_unbounded_markers_are_not_guessed(self):
        for text in ("counter 504 7009", "HTTP 999 [code: 1234567]",
                     '{"success":true,"status":504,"errors":[{"code":7009}]}',
                     '{"success":false,"status":true,"errors":[{"code":true}]}'):
            with self.subTest(text=text):
                self.assertEqual(sync._cli_failure_detail(text, ""),
                                 {"http_status": None, "provider_code": None})
        self.assertEqual(sync._cli_failure_detail("", "HTTP 504 HTTP 401 [code: 7009] [code: 10000]"),
                         {"http_status": None, "provider_code": None})
        self.assertEqual(sync._cli_failure_detail("", "Upstream service unavailable [code: 7009]"),
                         {"http_status": None, "provider_code": 7009})

    def test_final_retry_metadata_does_not_describe_an_earlier_attempt(self):
        results = [completed(1, "HTTP 504 [code: 7009]"),
                   completed(1, "HTTP 504 [code: 7009]"),
                   completed(1, "HTTP 401 [code: 10000]")]
        with mock.patch.object(sync, "_run_cli", side_effect=results), mock.patch.object(sync.time, "sleep") as sleep:
            sync._run_with_retry(["kv", "key", "put"])
        self.assertEqual(sync.LAST_CALL, {"attempts": 3, "exit_code": 1, "error_category": "AUTHENTICATION_ERROR"})
        self.assertEqual(sync.LAST_CALL_DETAIL, {"http_status": 401, "provider_code": 10000})
        self.assertEqual([call.args[0] for call in sleep.call_args_list], [5.0, 10.0])

    def test_success_and_unavailable_cli_clear_previous_failure_metadata(self):
        sync.LAST_CALL_DETAIL.update(http_status=504, provider_code=7009)
        with mock.patch.object(sync, "_run_cli", return_value=completed(0, "")):
            sync._run_with_retry(["kv", "key", "get"])
        self.assertEqual(sync.LAST_CALL_DETAIL, {"http_status": None, "provider_code": None})
        sync.LAST_CALL_DETAIL.update(http_status=504, provider_code=7009)
        with mock.patch.object(sync, "_run_cli", side_effect=sync.CliUnavailable):
            sync._run_with_retry(["kv", "key", "put"])
        self.assertEqual(sync.LAST_CALL["attempts"], 0)
        self.assertEqual(sync.LAST_CALL_DETAIL, {"http_status": None, "provider_code": None})

    def test_timeout_is_counted_without_inventing_a_response(self):
        with mock.patch.object(sync, "_run_cli", side_effect=subprocess.TimeoutExpired(["synthetic-cli"], 300)), \
                mock.patch.object(sync.time, "sleep"):
            sync._run_with_retry(["kv", "key", "put"])
        self.assertEqual(sync.LAST_CALL["attempts"], 3)
        self.assertEqual(sync.LAST_CALL["error_category"], "TIMEOUT")
        self.assertEqual(sync.LAST_CALL_DETAIL, {"http_status": None, "provider_code": None})

    def test_failure_list_is_bounded_and_never_copies_the_key(self):
        record = sync._outcome("SYNC")
        sync.LAST_CALL.update(attempts=3)
        sync.LAST_CALL_DETAIL.update(http_status=504, provider_code=7009)
        for key in ("blob:v1:" + "private-digest", "snapshot:private-run:private-object", "private-other"):
            sync._record_failed_object(record, key)
        self.assert_detail(record, "blob:v1:", 504, 7009, 3)
        encoded = json.dumps(record, separators=(",", ":"))
        self.assertNotIn("private", encoded)
        self.assertLess(len(encoded.encode("utf-8")), 8192)
        record = sync._outcome("SYNC")
        sync._record_failed_object(record, "private-other")
        self.assert_detail(record, "unknown", 504, 7009, 3)

    def test_v213_prices_records_only_the_data_family(self):
        record = sync._outcome("SYNC")
        sync.LAST_CALL.update(attempts=3)
        sync.LAST_CALL_DETAIL.update(http_status=504, provider_code=7009)
        sync._record_failed_object(record, "v213:prices:private-suffix:private-value")
        self.assert_detail(record, "v213:prices", 504, 7009, 3)
        self.assertNotIn("private", json.dumps(record["failed_objects"]))

    def test_v213_identity_records_only_the_data_family(self):
        record = sync._outcome("SYNC")
        sync.LAST_CALL.update(attempts=3)
        sync.LAST_CALL_DETAIL.update(http_status=504, provider_code=7009)
        sync._record_failed_object(record, "v213:identity:private-suffix:private-value")
        self.assert_detail(record, "v213:identity", 504, 7009, 3)
        self.assertNotIn("private", json.dumps(record["failed_objects"]))

    def test_v213_malformed_families_use_the_other_bucket(self):
        sync.LAST_CALL.update(attempts=3)
        sync.LAST_CALL_DETAIL.update(http_status=504, provider_code=7009)
        for family in ("", "Prices", "price.name", "price name", "prices/other",
                       "prices\n", "pric\u00e9s", "x" * 33):
            with self.subTest(family=family):
                record = sync._outcome("SYNC")
                sync._record_failed_object(record, "v213:" + family + ":private-suffix")
                self.assert_detail(record, "v213:other", 504, 7009, 3)
                self.assertNotIn("private", json.dumps(record["failed_objects"]))

    def test_v213_valid_family_characters_and_length_bounds(self):
        sync.LAST_CALL.update(attempts=3)
        sync.LAST_CALL_DETAIL.update(http_status=504, provider_code=7009)
        for family in ("x", "prices_2-daily", "x" * 32, "prices"):
            for suffix in ("", ":private-suffix"):
                with self.subTest(family=family, suffix=suffix):
                    record = sync._outcome("SYNC")
                    sync._record_failed_object(record, "v213:" + family + suffix)
                    self.assert_detail(record, "v213:" + family, 504, 7009, 3)
                    self.assertLessEqual(len(record["failed_objects"][0]["key_kind"]), 37)
                    self.assertNotIn("private", json.dumps(record["failed_objects"]))

    def test_existing_failed_key_kinds_are_unchanged(self):
        sync.LAST_CALL.update(attempts=3)
        sync.LAST_CALL_DETAIL.update(http_status=504, provider_code=7009)
        for key, kind in (
                ("blob:v1:private-suffix", "blob:v1:"),
                ("snapshot:private-suffix", "snapshot:"),
                ("unknown:private-suffix", "unknown"),
                ("blob:v2:private-suffix", "unknown"),
                ("v213", "unknown")):
            with self.subTest(key=key):
                record = sync._outcome("SYNC")
                sync._record_failed_object(record, key)
                self.assert_detail(record, kind, 504, 7009, 3)
                self.assertNotIn("private", json.dumps(record["failed_objects"]))

    def test_failed_object_preserves_partial_writes_and_pointer_last(self):
        fixture = self.fixture()
        self.kv.fail_put(fixture.key["B2"], None, NETWORK)
        result = self.run_fixture(fixture, fixture.key["B2"], "HTTP 504 [code: 7009]")
        self.assertEqual(result.exit, 1)
        self.assertEqual(result.outcome, ("FAILED", "OBJECT_PUT", "TRANSIENT_HTTP", "NOT_ATTEMPTED"))
        self.assertEqual(result.record["objects_uploaded"], 1)
        self.assertEqual(result.ops, (("put", "B1"), ("put", "B2"), ("put", "B2"), ("put", "B2")))
        self.assertEqual(self.kv.store[POINTER_KEY], OLD_POINTER)
        self.assert_detail(result.record, "blob:v1:", 504, 7009, 3)
        serialized = json.dumps(result.record["failed_objects"])
        self.assertNotIn(fixture.key["B2"], serialized)
        self.assertNotIn(RUN, serialized)

    def test_failed_object_readback_blocks_pointer_with_final_status(self):
        fixture = self.fixture()
        self.kv.missing_get(fixture.key["B2"], None)
        result = self.run_fixture(fixture, fixture.key["B2"], "Failed to fetch opaque-endpoint - 503: unavailable [code: 7009]")
        self.assertEqual(result.outcome, ("FAILED", "OBJECT_READBACK", "TRANSIENT_HTTP", "NOT_ATTEMPTED"))
        self.assertEqual(self.kv.store[POINTER_KEY], OLD_POINTER)
        self.assertNotIn(("put", "POINTER"), result.ops)
        self.assert_detail(result.record, "blob:v1:", 503, 7009, 3)

    def test_readback_mismatch_has_no_invented_http_error(self):
        fixture = self.fixture()
        self.kv.corrupt_get(fixture.key["B2"], 1, b"altered-body")
        result = self.run_fixture(fixture)
        self.assertEqual(result.outcome, ("FAILED", "OBJECT_READBACK", "READBACK_MISMATCH", "NOT_ATTEMPTED"))
        self.assert_detail(result.record, "blob:v1:", None, None, 1)
        self.assertEqual(self.kv.store[POINTER_KEY], OLD_POINTER)

    def test_failed_pointer_put_keeps_ambiguous_state(self):
        fixture = self.fixture()
        self.kv.fail_put(POINTER_KEY, None, WRITE_THEN_FAIL)
        result = self.run_fixture(fixture, POINTER_KEY, "HTTP 504 [code: 7009]")
        self.assertEqual(result.outcome, ("FAILED", "POINTER_PUT", "TRANSIENT_HTTP", "ATTEMPTED_UNCONFIRMED"))
        self.assertNotEqual(self.kv.store[POINTER_KEY], OLD_POINTER)
        self.assert_detail(result.record, "snapshot:", 504, 7009, 3)
        self.assertNotIn(POINTER_KEY, json.dumps(result.record["failed_objects"]))

    def test_failed_pointer_readback_keeps_ambiguous_state(self):
        fixture = self.fixture()
        self.kv.missing_get(POINTER_KEY, None)
        result = self.run_fixture(fixture, POINTER_KEY, "HTTP 503 [code: 7009]")
        self.assertEqual(result.outcome, ("FAILED", "POINTER_READBACK", "TRANSIENT_HTTP", "ATTEMPTED_UNCONFIRMED"))
        self.assert_detail(result.record, "snapshot:", 503, 7009, 3)
        self.assertEqual(result.record["objects_verified"], 5)

    def test_recovered_retry_preserves_all_readbacks_and_no_failed_object(self):
        fixture = self.fixture()
        self.kv.fail_put(fixture.key["B1"], 1, NETWORK)
        result = self.run_fixture(fixture, fixture.key["B1"], "HTTP 504 [code: 7009]")
        self.assertEqual(result.exit, 0)
        self.assertEqual(result.record["failed_objects"], [])
        self.assertEqual(result.record["pointer_state"], "READBACK_CONFIRMED")
        self.assertEqual(result.record["objects_verified"], 5)
        self.assertEqual(result.ops[-2:], (("put", "POINTER"), ("get", "POINTER")))
        object_reads = [index for index, (op, key) in enumerate(result.ops) if op == "get" and key != "POINTER"]
        self.assertEqual(len(object_reads), 5)
        self.assertLess(max(object_reads), len(result.ops) - 2)

    def test_unavailable_cli_records_zero_attempts_and_null_response(self):
        fixture = self.fixture()
        with mock.patch.object(sync, "_run_cli", side_effect=sync.CliUnavailable):
            result = run_sy(sync, self.kv, self.tmp / "run", self.ledger, fixture.names, seam="B")
        self.assertEqual(result.outcome, ("FAILED", "OBJECT_PUT", "CLI_UNAVAILABLE", "NOT_ATTEMPTED"))
        self.assertEqual(result.ops, ())
        self.assert_detail(result.record, "blob:v1:", None, None, 0)


class V28PerStreamFailureDetailTests(unittest.TestCase):
    def test_pretty_stdout_envelope_with_unrelated_stderr(self):
        stdout = json.dumps({"success": False, "status": 504,
                             "errors": [{"code": 7009}]}, indent=2)
        stderr = "Warning: non-JSON diagnostic text"
        self.assertEqual(sync._cli_failure_detail(stdout, stderr),
                         {"http_status": 504, "provider_code": 7009})

    def test_pretty_stderr_envelope_with_unrelated_stdout(self):
        stderr = json.dumps({"success": False, "statusCode": 401,
                             "errors": [{"code": 10000}]}, indent=4)
        self.assertEqual(sync._cli_failure_detail("other diagnostic", stderr),
                         {"http_status": 401, "provider_code": 10000})

    def test_conflicting_statuses_still_fail_closed(self):
        stdout = json.dumps({"success": False, "status": 504}, indent=2)
        stderr = json.dumps({"success": False, "status_code": 503}, indent=2)
        self.assertIsNone(sync._cli_failure_detail(stdout, stderr)["http_status"])


if __name__ == "__main__":
    unittest.main()
