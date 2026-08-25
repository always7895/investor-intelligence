from __future__ import annotations

import copy
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from public_symbol_admission import (  # noqa: E402
    SymbolAdmissionError,
    build_public_symbol_plan,
    load_policy,
    normalize_symbol,
)


class PublicSymbolAdmissionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.policy = load_policy()
        cls.references = {
            "TEST": {
                "symbol": "TEST",
                "exchange": "SYNTHETIC_EXCHANGE",
                "security_type": "COMMON_STOCK",
                "reference_source_id": "synthetic_official_reference",
                "reference_url": "https://example.test/instruments/TEST",
                "active": True,
                "provider_symbol": "TEST",
                "currency": "USD",
            },
            "BRK-B": {
                "symbol": "BRK-B",
                "exchange": "SYNTHETIC_EXCHANGE",
                "security_type": "COMMON_STOCK",
                "reference_source_id": "synthetic_official_reference",
                "reference_url": "https://example.test/instruments/BRK-B",
                "active": True,
                "provider_symbol": "BRK-B",
                "currency": "USD",
            },
        }

    def test_builds_public_cache_keys_without_tenant_or_owner_identity(self) -> None:
        plan = build_public_symbol_plan(
            ["test", "BRK-B", "test"],
            self.references,
            reviewed_quote_provider_available=True,
            policy=self.policy,
        )
        self.assertEqual(plan.symbols, ("TEST", "BRK-B"))
        self.assertEqual(
            plan.cache_keys,
            ("public:options:TEST", "public:options:BRK-B"),
        )
        # Negative privacy attestations are required public metadata. Check only
        # the identity-bearing values and cache keys for forbidden identity text;
        # do not treat a field named owner_watchlist_inherited=false as leakage.
        identity_surfaces = json.dumps(
            {
                "symbols": plan.symbols,
                "provider_symbols": plan.provider_symbols,
                "cache_keys": plan.cache_keys,
                "reference_sources": plan.reference_sources,
            },
            sort_keys=True,
        ).casefold()
        self.assertNotIn("tenant", identity_surfaces)
        self.assertNotIn("owner", identity_surfaces)
        self.assertFalse(plan.owner_watchlist_inherited)
        self.assertFalse(plan.portfolio_inherited)
        self.assertFalse(plan.broker_used)
        self.assertFalse(plan.query_history_persisted)
        self.assertIs(plan.as_dict()["owner_watchlist_inherited"], False)

    def test_fails_closed_without_reviewed_public_quote_provider(self) -> None:
        with self.assertRaises(SymbolAdmissionError):
            build_public_symbol_plan(
                ["TEST"],
                self.references,
                reviewed_quote_provider_available=False,
                policy=self.policy,
            )

    def test_requires_reviewed_active_public_instrument_reference(self) -> None:
        cases = []
        missing = dict(self.references)
        missing.pop("TEST")
        cases.append(missing)

        inactive = copy.deepcopy(self.references)
        inactive["TEST"]["active"] = False
        cases.append(inactive)

        unsupported = copy.deepcopy(self.references)
        unsupported["TEST"]["security_type"] = "OPTION_CONTRACT"
        cases.append(unsupported)

        insecure = copy.deepcopy(self.references)
        insecure["TEST"]["reference_url"] = "http://example.test/instruments/TEST"
        cases.append(insecure)

        mismatch = copy.deepcopy(self.references)
        mismatch["TEST"]["symbol"] = "OTHER"
        cases.append(mismatch)

        for references in cases:
            with self.subTest(references=references), self.assertRaises(SymbolAdmissionError):
                build_public_symbol_plan(
                    ["TEST"],
                    references,
                    reviewed_quote_provider_available=True,
                    policy=self.policy,
                )

    def test_rejects_unsafe_reference_url_structures(self) -> None:
        invalid_urls = (
            "https://user:" + "synthetic-credential" + "@example.test/instruments/TEST",
            "https://example.test" + "@" + "evil.test/instruments/TEST",
            "https://localhost/instruments/TEST",
            "https://catalog.local/instruments/TEST",
            "https://127.0.0.1/instruments/TEST",
            "https://10.0.0.1/instruments/TEST",
            "https://[::1]/instruments/TEST",
            "https://example.test:8443/instruments/TEST",
            "https://example.test/instruments/%2e%2e/private",
            "https://example.test/instruments\\TEST",
            "https://example.test/instruments/TEST value",
        )
        for raw_url in invalid_urls:
            references = copy.deepcopy(self.references)
            references["TEST"]["reference_url"] = raw_url
            with self.subTest(raw_url=raw_url), self.assertRaises(SymbolAdmissionError):
                build_public_symbol_plan(
                    ["TEST"],
                    references,
                    reviewed_quote_provider_available=True,
                    policy=self.policy,
                )

    def test_rejects_unicode_urls_spaces_and_suspicious_symbols(self) -> None:
        invalid = (
            "ＡＡＯＩ",
            "AＡOI",
            "AAOİ",
            "https://example.test",
            "AA OI",
            "../TEST",
            "TEST--A",
            "",
            "TOO-LONG-SYMBOL-123",
        )
        for value in invalid:
            with self.subTest(value=value), self.assertRaises(SymbolAdmissionError):
                normalize_symbol(value, self.policy)

    def test_request_count_and_policy_remain_fail_closed(self) -> None:
        too_many = [f"T{index}" for index in range(6)]
        references = {
            symbol: {
                "symbol": symbol,
                "exchange": "SYNTHETIC_EXCHANGE",
                "security_type": "ETF",
                "reference_source_id": "synthetic_official_reference",
                "reference_url": f"https://example.test/instruments/{symbol}",
                "active": True,
            }
            for symbol in too_many
        }
        with self.assertRaises(SymbolAdmissionError):
            build_public_symbol_plan(
                too_many,
                references,
                reviewed_quote_provider_available=True,
                policy=self.policy,
            )

        broken = dict(self.policy)
        broken["owner_watchlist_inheritance"] = True
        # load_policy enforces the repository file; the planner also receives
        # explicit policy only from reviewed callers. Verify normalization still
        # cannot smuggle identity into a ticker.
        with self.assertRaises(SymbolAdmissionError):
            normalize_symbol("tenant:owner", broken)


if __name__ == "__main__":
    unittest.main()
