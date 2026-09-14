from __future__ import annotations

import io
import json
import socket
import ssl
import sys
import subprocess
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import MagicMock, patch
from urllib.error import HTTPError, URLError
from urllib.request import HTTPSHandler, ProxyHandler

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from fetch_public_source_observations import (
    ENDPOINTS, MAX_BYTES, NoRedirect, collect, fetch_bytes, main, verified_tls_context,
    diagnose_transport_exception, _unwrap_exception_chain,
)
from adapters import AdapterError


class PublicSourceTransportTests(unittest.TestCase):
    def test_trust_bundle_supplements_defaults_without_weakening_flags(self):
        context = ssl.create_default_context()
        flags = context.verify_flags
        with patch("fetch_public_source_observations.ssl.create_default_context", return_value=context):
            actual = verified_tls_context()
        self.assertIs(actual, context)
        self.assertEqual(actual.verify_mode, ssl.CERT_REQUIRED)
        self.assertTrue(actual.check_hostname)
        self.assertEqual(actual.verify_flags, flags)

    def test_insecure_context_rejected_before_network(self):
        context = MagicMock()
        context.verify_mode = ssl.CERT_NONE
        context.check_hostname = False
        with patch("fetch_public_source_observations.ssl.create_default_context", return_value=context):
            with self.assertRaisesRegex(ValueError, "TLS_VERIFICATION_REQUIRED"):
                verified_tls_context()

    def test_absent_trust_package_is_not_an_insecure_fallback(self):
        with patch.dict(sys.modules, {"certifi": None}):
            with self.assertRaisesRegex(ValueError, "VERIFIED_CA_BUNDLE_UNAVAILABLE"):
                verified_tls_context()

    def test_actual_fetch_configures_tls_proxy_redirect_timeout_and_size(self):
        context = verified_tls_context()
        opener = MagicMock()
        response = opener.open.return_value.__enter__.return_value
        response.status = 200
        response.read.return_value = b"synthetic body"
        with patch("fetch_public_source_observations.verified_tls_context", return_value=context), patch(
            "fetch_public_source_observations.build_opener", return_value=opener
        ) as build:
            self.assertEqual(fetch_bytes(ENDPOINTS["ecb_news"]), b"synthetic body")
        handlers = build.call_args.args
        self.assertTrue(any(isinstance(item, HTTPSHandler) and item._context is context for item in handlers))
        self.assertTrue(any(isinstance(item, ProxyHandler) and item.proxies == {} for item in handlers))
        self.assertTrue(any(isinstance(item, NoRedirect) for item in handlers))
        self.assertEqual(opener.open.call_args.kwargs["timeout"], 20)
        response.read.assert_called_once_with(MAX_BYTES + 1)
        request = opener.open.call_args.args[0]
        self.assertFalse(request.has_header("Authorization"))
        self.assertFalse(request.has_header("Cookie"))

    def test_tls_failure_stays_failed_and_does_not_retry(self):
        def reject(_url):
            raise URLError(ssl.SSLCertVerificationError(1, "synthetic-private-error"))
        transport = MagicMock(side_effect=reject)
        result = collect(["ecb_news"], transport=transport)
        self.assertEqual(result["status"], "FAILED")
        self.assertEqual(result["sources"][0]["failure_kind"], "TLS_VERIFICATION_FAILED")
        self.assertNotIn("synthetic-private-error", str(result))
        transport.assert_called_once()

    def test_direct_cli_from_unrelated_directory_needs_no_pythonpath(self):
        with tempfile.TemporaryDirectory() as directory:
            result = subprocess.run([sys.executable, str(ROOT / "scripts/fetch_public_source_observations.py"),
                                     "--help"], cwd=directory, capture_output=True, text=True, encoding="utf-8")
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("--fetch", result.stdout)
            result = subprocess.run([sys.executable, str(ROOT / "scripts/fetch_public_source_observations.py"),
                                     "--output", str(Path(directory) / "not-written.json")],
                                    cwd=directory, capture_output=True, text=True, encoding="utf-8")
            self.assertNotEqual(result.returncode, 0)
            self.assertFalse((Path(directory) / "not-written.json").exists())

    def test_redirect_is_rejected_without_following_target(self):
        with self.assertRaises(ValueError):
            NoRedirect().redirect_request(None, None, 302, "", {}, "https://example.test/")

    def test_typed_http_errors_classify_status_and_do_not_leak_sentinels(self):
        for code in (404, 429, 500, 503):
            sentinel_url = f"https://example.test/private?case_id=SECRET_TOKEN_{code}"
            sentinel_msg = f"SECRET_MSG_{code}"
            sentinel_hdr = f"SECRET_HDR_{code}"
            sentinel_body = f"SECRET_BODY_{code}".encode()
            err = HTTPError(sentinel_url, code, sentinel_msg, {"X-Secret": sentinel_hdr}, io.BytesIO(sentinel_body))
            transport = MagicMock(side_effect=err)
            result = collect(["federal_reserve_news"], transport=transport)
            self.assertEqual(result["status"], "FAILED")
            self.assertFalse(result["publication_eligible"])
            self.assertEqual(len(result["sources"]), 1)
            row = result["sources"][0]
            self.assertEqual(row["source_id"], "federal_reserve_news")
            self.assertEqual(row["status"], "FAILED")
            self.assertEqual(row["failure_kind"], "REQUEST_FAILED")
            self.assertEqual(row["failure_code"], "HTTP_ERROR")
            self.assertEqual(row["http_status"], code)
            self.assertEqual(row["record_count"], 0)
            transport.assert_called_once()

            serialized = json.dumps(result)
            for sentinel in (f"SECRET_TOKEN_{code}", sentinel_msg, sentinel_hdr, f"SECRET_BODY_{code}", "example.test"):
                self.assertNotIn(sentinel, serialized)

    def test_malformed_http_statuses_reject_status_field(self):
        for bad_status in ("404", True, False, 99, 600, None, [500]):
            err = HTTPError("https://example.test/", 500, "Error", {}, None)
            err.code = bad_status
            transport = MagicMock(side_effect=err)
            result = collect(["federal_reserve_news"], transport=transport)
            self.assertEqual(result["status"], "FAILED")
            self.assertFalse(result["publication_eligible"])
            row = result["sources"][0]
            self.assertEqual(row["status"], "FAILED")
            self.assertEqual(row["failure_kind"], "REQUEST_FAILED")
            self.assertEqual(row["failure_code"], "HTTP_ERROR")
            self.assertNotIn("http_status", row)
            transport.assert_called_once()

    def test_wrapped_and_direct_timeout_dns_certificate_connection(self):
        cases = [
            (TimeoutError("SECRET_DIRECT_TIMEOUT"), "TIMEOUT", "REQUEST_FAILED"),
            (URLError(TimeoutError("SECRET_WRAPPED_TIMEOUT")), "TIMEOUT", "REQUEST_FAILED"),
            (socket.gaierror(-2, "SECRET_DIRECT_GAI"), "DNS_RESOLUTION_FAILED", "REQUEST_FAILED"),
            (URLError(socket.gaierror(-2, "SECRET_WRAPPED_GAI")), "DNS_RESOLUTION_FAILED", "REQUEST_FAILED"),
            (ssl.SSLCertVerificationError(1, "SECRET_DIRECT_CERT"), "TLS_VERIFICATION_FAILED", "TLS_VERIFICATION_FAILED"),
            (URLError(ssl.SSLCertVerificationError(1, "SECRET_WRAPPED_CERT")), "TLS_VERIFICATION_FAILED", "TLS_VERIFICATION_FAILED"),
            (ConnectionRefusedError("SECRET_DIRECT_CONN"), "CONNECTION_FAILED", "REQUEST_FAILED"),
            (URLError(ConnectionRefusedError("SECRET_WRAPPED_CONN")), "CONNECTION_FAILED", "REQUEST_FAILED"),
        ]
        for exc, expected_code, expected_kind in cases:
            transport = MagicMock(side_effect=exc)
            result = collect(["federal_reserve_news"], transport=transport)
            self.assertEqual(result["status"], "FAILED")
            self.assertFalse(result["publication_eligible"])
            row = result["sources"][0]
            self.assertEqual(row["status"], "FAILED")
            self.assertEqual(row["failure_kind"], expected_kind)
            self.assertEqual(row["failure_code"], expected_code)
            self.assertNotIn("http_status", row)
            self.assertEqual(row["record_count"], 0)
            transport.assert_called_once()

            serialized = json.dumps(result)
            self.assertNotIn("SECRET_", serialized)

    def test_exact_redirect_marker_classified(self):
        for exc in (
            ValueError("NEWS_REDIRECT_REJECTED"),
            URLError(ValueError("NEWS_REDIRECT_REJECTED")),
        ):
            transport = MagicMock(side_effect=exc)
            result = collect(["federal_reserve_news"], transport=transport)
            self.assertEqual(result["status"], "FAILED")
            self.assertFalse(result["publication_eligible"])
            row = result["sources"][0]
            self.assertEqual(row["status"], "FAILED")
            self.assertEqual(row["failure_kind"], "REQUEST_FAILED")
            self.assertEqual(row["failure_code"], "REDIRECT_REJECTED")
            self.assertNotIn("http_status", row)
            self.assertEqual(row["record_count"], 0)
            transport.assert_called_once()

    def test_unknown_error_classified_conservatively(self):
        for exc in (
            RuntimeError("SECRET_UNKNOWN_RUNTIME_EXCEPTION"),
            OSError("SECRET_UNKNOWN_OS_EXCEPTION"),
        ):
            transport = MagicMock(side_effect=exc)
            result = collect(["federal_reserve_news"], transport=transport)
            self.assertEqual(result["status"], "FAILED")
            self.assertFalse(result["publication_eligible"])
            row = result["sources"][0]
            self.assertEqual(row["status"], "FAILED")
            self.assertEqual(row["failure_kind"], "REQUEST_FAILED")
            self.assertEqual(row["failure_code"], "UNKNOWN_ERROR")
            self.assertNotIn("http_status", row)
            self.assertEqual(row["record_count"], 0)
            transport.assert_called_once()
            self.assertNotIn("SECRET_", json.dumps(result))

    def test_actual_main_caller_end_to_end_mock_opener(self):
        opener = MagicMock()
        sentinel_url = "https://internal.test/private?key=SECRET_TOKEN_MAIN"
        sentinel_msg = "SECRET_MSG_MAIN"
        sentinel_hdr = "SECRET_HDR_MAIN"
        sentinel_body = b"SECRET_BODY_MAIN"
        mock_err = HTTPError(sentinel_url, 503, sentinel_msg, {"X-Secret": sentinel_hdr}, io.BytesIO(sentinel_body))
        opener.open.side_effect = mock_err

        with tempfile.TemporaryDirectory() as td:
            output_file = Path(td) / "obs.json"
            stdout_capture = io.StringIO()
            with patch("fetch_public_source_observations.build_opener", return_value=opener), \
                 patch.object(sys, "argv", ["fetch_public_source_observations.py", "--fetch", "--source", "federal_reserve_news", "--output", str(output_file)]), \
                 redirect_stdout(stdout_capture):
                exit_code = main()

            self.assertEqual(exit_code, 1)
            self.assertTrue(output_file.exists())
            file_text = output_file.read_text(encoding="utf-8")
            saved = json.loads(file_text)
            self.assertEqual(saved["status"], "FAILED")
            self.assertFalse(saved["publication_eligible"])
            self.assertEqual(len(saved["sources"]), 1)
            row = saved["sources"][0]
            self.assertEqual(row["source_id"], "federal_reserve_news")
            self.assertEqual(row["status"], "FAILED")
            self.assertEqual(row["failure_kind"], "REQUEST_FAILED")
            self.assertEqual(row["failure_code"], "HTTP_ERROR")
            self.assertEqual(row["http_status"], 503)
            self.assertEqual(row["record_count"], 0)

            stdout_text = stdout_capture.getvalue()
            stdout_obj = json.loads(stdout_text)
            self.assertEqual(stdout_obj["status"], "FAILED")
            self.assertFalse(stdout_obj["publication_eligible"])
            self.assertEqual(stdout_obj["sources"][0]["failure_code"], "HTTP_ERROR")
            self.assertEqual(stdout_obj["sources"][0]["http_status"], 503)

            for sentinel in ("SECRET_TOKEN_MAIN", sentinel_msg, sentinel_hdr, "SECRET_BODY_MAIN", "internal.test"):
                self.assertNotIn(sentinel, file_text)
                self.assertNotIn(sentinel, stdout_text)

            opener.open.assert_called_once()

    def test_positive_actual_collector_fixture_and_empty_rss_stays_failed(self):
        valid_rss = (
            b'<rss version="2.0"><channel><item>'
            b'<title>Valid Observation</title>'
            b'<link>https://www.federalreserve.gov/press/valid.htm</link>'
            b'<pubDate>Mon, 07 Sep 2026 10:00:00 GMT</pubDate>'
            b'</item></channel></rss>'
        )
        transport_ok = MagicMock(return_value=valid_rss)
        result_ok = collect(["federal_reserve_news"], transport=transport_ok)
        self.assertEqual(result_ok["status"], "OK")
        self.assertFalse(result_ok["publication_eligible"])
        self.assertEqual(result_ok["sources"][0]["status"], "OK")
        self.assertEqual(result_ok["sources"][0]["record_count"], 1)
        self.assertEqual(len(result_ok["items"]), 1)
        transport_ok.assert_called_once()

        transport_empty = MagicMock(return_value=b"")
        result_empty = collect(["federal_reserve_news"], transport=transport_empty)
        self.assertEqual(result_empty["status"], "FAILED")
        self.assertFalse(result_empty["publication_eligible"])
        self.assertEqual(result_empty["sources"][0]["status"], "FAILED")
        self.assertEqual(result_empty["sources"][0]["failure_kind"], "INVALID_PAYLOAD")
        self.assertEqual(result_empty["sources"][0]["failure_code"], "INVALID_PAYLOAD")
        self.assertEqual(result_empty["sources"][0]["record_count"], 0)
        transport_empty.assert_called_once()

        transport_no_items = MagicMock(return_value=b"<rss><channel></channel></rss>")
        result_no_items = collect(["federal_reserve_news"], transport=transport_no_items)
        self.assertEqual(result_no_items["status"], "FAILED")
        self.assertFalse(result_no_items["publication_eligible"])
        self.assertEqual(result_no_items["sources"][0]["status"], "FAILED")
        self.assertEqual(result_no_items["sources"][0]["failure_kind"], "INVALID_PAYLOAD")
        self.assertEqual(result_no_items["sources"][0]["failure_code"], "INVALID_PAYLOAD")
        self.assertEqual(result_no_items["sources"][0]["record_count"], 0)
        transport_no_items.assert_called_once()

    def test_generic_tls_preserves_old_failure_kind_and_diagnoses_tls_error(self):
        cases = [
            ssl.SSLError("generic-tls-error"),
            URLError(ssl.SSLError("generic-tls-wrapped")),
        ]
        for exc in cases:
            transport = MagicMock(side_effect=exc)
            result = collect(["federal_reserve_news"], transport=transport)
            self.assertEqual(result["status"], "FAILED")
            self.assertFalse(result["publication_eligible"])
            row = result["sources"][0]
            self.assertEqual(row["status"], "FAILED")
            self.assertEqual(row["failure_kind"], "REQUEST_FAILED")
            self.assertEqual(row["failure_code"], "TLS_ERROR")
            self.assertNotIn("http_status", row)
            self.assertEqual(row["record_count"], 0)
            transport.assert_called_once()
            self.assertNotIn("generic-tls", json.dumps(result))

    def test_wrapped_adapter_error_outer_kind_compatibility(self):
        direct_err = AdapterError("payload malformed")
        diag_direct = diagnose_transport_exception(direct_err)
        self.assertEqual(diag_direct.failure_kind, "INVALID_PAYLOAD")
        self.assertEqual(diag_direct.failure_code, "INVALID_PAYLOAD")

        outer_cause = RuntimeError("transport wrapper")
        outer_cause.__cause__ = AdapterError("inner payload malformed")
        diag_cause = diagnose_transport_exception(outer_cause)
        self.assertEqual(diag_cause.failure_kind, "REQUEST_FAILED")
        self.assertEqual(diag_cause.failure_code, "INVALID_PAYLOAD")

        outer_url = URLError(AdapterError("inner payload malformed in url error"))
        diag_url = diagnose_transport_exception(outer_url)
        self.assertEqual(diag_url.failure_kind, "REQUEST_FAILED")
        self.assertEqual(diag_url.failure_code, "INVALID_PAYLOAD")

        transport = MagicMock(side_effect=outer_cause)
        result = collect(["federal_reserve_news"], transport=transport)
        self.assertEqual(result["sources"][0]["failure_kind"], "REQUEST_FAILED")
        self.assertEqual(result["sources"][0]["failure_code"], "INVALID_PAYLOAD")
        self.assertNotIn("malformed", json.dumps(result))

    def test_unrelated_implicit_http_context_not_diagnosed_as_current_http(self):
        try:
            raise HTTPError("https://example.test/stale", 500, "Old Error", {}, None)
        except Exception:
            try:
                raise TimeoutError("current-real-timeout")
            except Exception as exc:
                exc_timeout = exc

        diag = diagnose_transport_exception(exc_timeout)
        self.assertEqual(diag.failure_kind, "REQUEST_FAILED")
        self.assertEqual(diag.failure_code, "TIMEOUT")
        self.assertIsNone(diag.http_status)

        transport = MagicMock(side_effect=exc_timeout)
        result = collect(["federal_reserve_news"], transport=transport)
        row = result["sources"][0]
        self.assertEqual(row["failure_kind"], "REQUEST_FAILED")
        self.assertEqual(row["failure_code"], "TIMEOUT")
        self.assertNotIn("http_status", row)
        self.assertNotIn("stale", json.dumps(result))
        self.assertNotIn("current-real-timeout", json.dumps(result))

    def test_cycle_and_depth_termination(self):
        err1 = Exception("node1")
        err2 = Exception("node2")
        err1.__cause__ = err2
        err2.__cause__ = err1
        chain = _unwrap_exception_chain(err1)
        self.assertEqual(len(chain), 2)
        self.assertEqual(chain, [err1, err2])

        self_err = Exception("self")
        self_err.__cause__ = self_err
        chain_self = _unwrap_exception_chain(self_err)
        self.assertEqual(len(chain_self), 1)

        u1 = URLError("first")
        u2 = URLError("second")
        u1.reason = u2
        u2.reason = u1
        chain_url = _unwrap_exception_chain(u1)
        self.assertEqual(len(chain_url), 2)

        root = Exception("root")
        curr = root
        for i in range(1, 15):
            nxt = Exception(f"node_{i}")
            curr.__cause__ = nxt
            curr = nxt
        deep_chain = _unwrap_exception_chain(root)
        self.assertEqual(len(deep_chain), 8)
        self.assertEqual(deep_chain[0], root)

        self.assertEqual(_unwrap_exception_chain(None), [])

    def test_redirect_marker_exact_tuple_matching(self):
        diag_ok = diagnose_transport_exception(ValueError("NEWS_REDIRECT_REJECTED"))
        self.assertEqual(diag_ok.failure_code, "REDIRECT_REJECTED")

        diag_extra = diagnose_transport_exception(ValueError("NEWS_REDIRECT_REJECTED", "extra_argument"))
        self.assertEqual(diag_extra.failure_code, "UNKNOWN_ERROR")

        diag_diff = diagnose_transport_exception(ValueError("OTHER_ERROR"))
        self.assertEqual(diag_diff.failure_code, "UNKNOWN_ERROR")

        diag_empty = diagnose_transport_exception(ValueError())
        self.assertEqual(diag_empty.failure_code, "UNKNOWN_ERROR")



if __name__ == "__main__":
    unittest.main()
