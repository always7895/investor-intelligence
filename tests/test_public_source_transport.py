from __future__ import annotations

import ssl
import sys
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch
from urllib.error import URLError
from urllib.request import HTTPSHandler, ProxyHandler

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from fetch_public_source_observations import (
    ENDPOINTS, MAX_BYTES, NoRedirect, collect, fetch_bytes, verified_tls_context,
)


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


if __name__ == "__main__":
    unittest.main()
