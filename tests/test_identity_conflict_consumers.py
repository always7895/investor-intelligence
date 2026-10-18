"""ICON12 consumers: how the name and price consumers of the identity shards treat a contradictory variant of one venue:symbol
key (kept by build_identity_shards.py since ICON2). Synthetic shards in temporary files; no network.

names_for (withheld for a contested key) is pinned in tests/test_build_zh_names.py. Here: us_symbols (membership only, unchanged by
design: a cashtag only asks whether the symbol exists on a US venue, never which variant is right) and yahoo_symbols (a key enters
the Yahoo price universe only when every retained variant is a COMMON_STOCK of the same market)."""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import build_price_shards as prices  # noqa: E402
import serenity_signals as serenity  # noqa: E402


def row(symbol, venue, market, klass="COMMON_STOCK", name=None):
    return [symbol, venue, market, "Country", name or f"{symbol} Corp", None, klass, "USD", 0, None]


def write(directory: str, rows: list) -> Path:
    path = Path(directory) / "identity.json"
    path.write_text(json.dumps({"symbol_shards": {"X": {"rows": rows}}}), encoding="utf-8")
    return path


class IdentityConflictConsumerTests(unittest.TestCase):
    def test_us_symbols_is_market_membership_and_ignores_variant_disagreement(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = write(tmp, [
                row("CLEAN", "NASDAQ", "US"),
                row("CLASSVAR", "NASDAQ", "US"), row("CLASSVAR", "NASDAQ", "US", "ETF", "Class Var ETF"),
                row("MARKETVAR", "NASDAQ", "US"), row("MARKETVAR", "NASDAQ", "UK"),
                row("ONLYUK", "LSE", "UK"), row("ONLYUK", "LSE", "UK", name="Only UK Alt"),
            ])
            self.assertEqual(serenity.us_symbols(path), {"CLEAN", "CLASSVAR", "MARKETVAR"})
            self.assertEqual(serenity.us_symbols(Path(tmp) / "absent.json"), set())  # unchanged fail-closed read
            known = serenity.us_symbols(path)
            mapping = {"cashtags": {}, "names": {}}
            self.assertEqual(set(serenity.listings_in("$CLASSVAR and $ONLYUK and $CLEAN", mapping, known)), {"CLASSVAR", "CLEAN"})

    def test_yahoo_universe_keeps_clean_keys_and_drops_keys_whose_variants_disagree(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = write(tmp, [
                row("7203", "TSE", "JAPAN"),  # clean Japan common stock
                row("6758", "TSE", "JAPAN"), row("6758", "TSE", "JAPAN", name="Sony Alt"),  # variants agree on class and market
                row("1111", "TSE", "JAPAN"), row("1111", "TSE", "JAPAN", "ETF", "Eleven ETF"),  # class disagreement
                row("2222", "TSE", "JAPAN", "ETF"), row("2222", "TSE", "JAPAN", "COMMON_STOCK", "Twenty Two"),  # first row is the ETF
                row("3333", "TSE", "JAPAN"), row("3333", "TSE", "KOREA"),  # market disagreement
                row("005930", "KRX", "KOREA"),
                row("035720", "KOSDAQ", "KOREA", "ETF"),  # a single non-common row stays out, as before
                row("0700", "HKEX", "HK"),  # not a Yahoo-priced market here
            ])
            expected_japan = {"7203.T": "7203", "6758.T": "6758"}
            self.assertEqual(prices.yahoo_symbols(path), {"JAPAN": expected_japan, "KOREA": {"005930.KS": "005930"}})
            self.assertEqual(set(prices.yahoo_symbols(path)), set(prices.YAHOO_MARKETS))

    def test_yahoo_universe_is_unchanged_for_a_shard_without_variants(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = write(tmp, [row("7203", "TSE", "JAPAN"), row("247540", "KOSDAQ", "KOREA"), row("AAPL", "NASDAQ", "US")])
            self.assertEqual(prices.yahoo_symbols(path), {"JAPAN": {"7203.T": "7203"}, "KOREA": {"247540.KQ": "247540"}})


if __name__ == "__main__":
    unittest.main()
