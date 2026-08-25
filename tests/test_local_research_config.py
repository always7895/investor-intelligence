from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from local_research_config import (  # noqa: E402
    DEFAULT_LOCAL_PREFERENCES,
    LocalResearchConfigError,
    load_local_preferences,
    load_research_universe,
)


class LocalResearchConfigTests(unittest.TestCase):
    def test_repository_contains_no_owner_watchlist_or_preference_file(self) -> None:
        self.assertFalse((ROOT / "config" / "watchlist.json").exists())
        self.assertFalse((ROOT / "config" / "user-preferences.json").exists())
        ignore = (ROOT / ".gitignore").read_text(encoding="utf-8")
        self.assertIn("config/*.local.json", ignore)

    def test_explicit_synthetic_universe_is_normalized(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "research-universe.local.json"
            path.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "privacy_class": "local_user_configuration",
                        "stocks": [
                            {
                                "ticker": "test",
                                "name": "Synthetic Test Company",
                                "category": "Synthetic",
                                "source": "synthetic-fixture",
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            records = load_research_universe(path)
        self.assertEqual([item["ticker"] for item in records], ["TEST"])

    def test_invalid_duplicate_or_empty_universe_fails_closed(self) -> None:
        documents = (
            {"privacy_class": "local_user_configuration", "stocks": []},
            {
                "privacy_class": "local_user_configuration",
                "stocks": [{"ticker": "../BAD"}],
            },
            {
                "privacy_class": "local_user_configuration",
                "stocks": [{"ticker": "TEST"}, {"ticker": "test"}],
            },
            {
                "privacy_class": "public",
                "stocks": [{"ticker": "TEST"}],
            },
        )
        for document in documents:
            with tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / "research-universe.local.json"
                path.write_text(json.dumps(document), encoding="utf-8")
                with self.subTest(document=document), self.assertRaises(
                    LocalResearchConfigError
                ):
                    load_research_universe(path)

    def test_missing_preferences_use_disabled_generic_default(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            value = load_local_preferences(Path(directory) / "missing.local.json")
        self.assertEqual(value, DEFAULT_LOCAL_PREFERENCES)
        self.assertFalse(value["long_term_overlay"]["enabled"])
        self.assertEqual(value["long_term_overlay"]["owner"], "local_user")
        self.assertFalse(
            value["long_term_overlay"]["affects_methodology_research_score"]
        )


if __name__ == "__main__":
    unittest.main()
