from __future__ import annotations

import unittest
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from secure_public_url import (  # noqa: E402
    PublicUrlError,
    ReviewedUrlBoundary,
    validate_public_url,
    validate_redirect_chain,
)


class SecurePublicFetchCanonicalTests(unittest.TestCase):
    def setUp(self) -> None:
        self.boundary = ReviewedUrlBoundary(
            hosts=("data.example.test", "cdn.example.test"),
            path_prefixes=("/api/v1", "/bulk"),
            maximum_redirects=2,
        )

    @staticmethod
    def public_resolver(_host: str) -> tuple[str, ...]:
        return ("93.184.216.34", "2606:2800:220:1:248:1893:25c8:1946")

    def test_accepts_reviewed_https_host_path_and_public_dns(self) -> None:
        value = validate_public_url(
            "https://data.example.test/api/v1/series?format=json",
            self.boundary,
            resolver=self.public_resolver,
        )
        self.assertEqual(value, "https://data.example.test/api/v1/series?format=json")

    def test_rejects_http_userinfo_non443_ip_literals_and_unreviewed_hosts(self) -> None:
        urls = (
            "http://data.example.test/api/v1/series",
            "https://user:" + "synthetic-credential" + "@data.example.test/api/v1/series",
            "https://data.example.test:8443/api/v1/series",
            "https://127.0.0.1/api/v1/series",
            "https://data.example.test.evil.invalid/api/v1/series",
            "https://cdn.example.test/other/path",
        )
        for url in urls:
            with self.subTest(url=url), self.assertRaises(PublicUrlError):
                validate_public_url(url, self.boundary, resolver=self.public_resolver)

    def test_rejects_private_mixed_reserved_and_empty_dns_answers(self) -> None:
        answer_sets = (
            ("127.0.0.1",),
            ("10.0.0.1",),
            ("169.254.169.254",),
            ("::1",),
            ("93.184.216.34", "10.0.0.1"),
            (),
        )
        for answers in answer_sets:
            with self.subTest(answers=answers), self.assertRaises(PublicUrlError):
                validate_public_url(
                    "https://data.example.test/api/v1/series",
                    self.boundary,
                    resolver=lambda _host, answers=answers: answers,
                )

    def test_every_redirect_is_revalidated_and_bounded(self) -> None:
        chain = (
            "https://data.example.test/api/v1/series",
            "https://cdn.example.test/bulk/series.csv",
        )
        self.assertEqual(
            validate_redirect_chain(chain, self.boundary, resolver=self.public_resolver),
            chain,
        )

        with self.assertRaises(PublicUrlError):
            validate_redirect_chain(
                (
                    "https://data.example.test/api/v1/series",
                    "https://evil.invalid/api/v1/series",
                ),
                self.boundary,
                resolver=self.public_resolver,
            )
        with self.assertRaises(PublicUrlError):
            validate_redirect_chain(
                (
                    "https://data.example.test/api/v1/a",
                    "https://cdn.example.test/bulk/b",
                    "https://data.example.test/api/v1/c",
                    "https://cdn.example.test/bulk/d",
                ),
                self.boundary,
                resolver=self.public_resolver,
            )

    def test_rejects_path_traversal_and_encoded_traversal(self) -> None:
        for url in (
            "https://data.example.test/api/v1/../private",
            "https://data.example.test/api/v1/%2e%2e/private",
            "https://data.example.test/api/v1/%5cprivate",
        ):
            with self.subTest(url=url), self.assertRaises(PublicUrlError):
                validate_public_url(url, self.boundary, resolver=self.public_resolver)


if __name__ == "__main__":
    unittest.main()
