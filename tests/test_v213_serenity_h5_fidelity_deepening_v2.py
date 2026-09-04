#!/usr/bin/env python3
from __future__ import annotations

import re
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import v213_serenity_h5_fidelity_deepening_v2 as h5v2


class SerenityH5V2SourcePrecisionTests(unittest.TestCase):
    def test_public_source_times_are_not_fake_utc(self) -> None:
        for row in h5v2.DATE_ONLY_SEEDS:
            self.assertEqual(row["time_precision"], "DATE_ONLY")
            self.assertRegex(row["published_at"], r"^\d{4}-\d{2}-\d{2}$")
            self.assertFalse(row["published_at"].endswith("Z"))

    def test_direct_public_source_urls_are_preserved(self) -> None:
        ids = {row["source_id"] for row in h5v2.DATE_ONLY_SEEDS}
        self.assertEqual(
            ids,
            {
                "x-2013947011490615486",
                "x-2021053268420591653",
                "x-2033889361801175094",
                "x-2034752613246542215",
            },
        )
        self.assertTrue(all(row["source_url"].startswith("https://x.com/aleabitoreddit/status/") for row in h5v2.DATE_ONLY_SEEDS))

    def test_history_written_by_v2_keeps_date_precision(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "history.jsonl"
            result = h5v2.base.ensure_source_history(path)
            self.assertTrue(result["chain_verified"])
            rows = h5v2.base.read_history(path)
            self.assertEqual(len(rows), len(h5v2.DATE_ONLY_SEEDS))
            for row in rows:
                self.assertEqual(row["time_precision"], "DATE_ONLY")
                self.assertRegex(row["published_at"], r"^\d{4}-\d{2}-\d{2}$")

    def test_source_view_remains_non_factual_dependency_proof(self) -> None:
        views = h5v2.base.source_views_for_ticker("AXTI")
        self.assertTrue(views)
        self.assertTrue(all(view["factual_dependency_proof"] is False for view in views))


if __name__ == "__main__":
    unittest.main()
