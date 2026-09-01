#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import v213_serenity_h5_fidelity_deepening_v3 as h5v3


class H5V3Tests(unittest.TestCase):
    def test_visible_body_keeps_late_text_after_old_three_mb_boundary(self) -> None:
        prefix = ("<span>padding</span>" * 180_000).encode("utf-8")
        tail = b"<p>On February 26, 2026 First EDA $250 million</p>"
        text = h5v3._decode_response_bytes(prefix + tail)
        self.assertIn("On February 26, 2026", text)
        self.assertIn("First EDA", text)

    def test_aaoi_lineage_uses_two_programs_not_amendment_as_program(self) -> None:
        snippet = " ".join([
            "On February 26, 2026, the Company entered into an Equity Distribution Agreement (the First EDA) with agents having an aggregate offering price of up to $250 million.",
            "On March 12, 2026, the Company entered into Amendment No. 1 to the First EDA, to increase the aggregate offering price from $250 million to $500 million.",
            "On April 2, 2026, the Company completed the First ATM Offering and sold approximately 4.8 million shares providing proceeds of approximately $490 million.",
            "On May 14, 2026, the Company entered into an Equity Distribution Agreement (the Second EDA) with agents having an aggregate offering price of up to $600 million.",
            "84,386 and 74,998 shares issued and outstanding at June 30, 2026 and December 31, 2025",
            "Total 7,775,523 $ 1,049,814 $ 20,996 $ 1,028,817",
        ])
        row = h5v3.aaoi_financing_lineage_v3(snippet)
        self.assertEqual(row["program_count"], 2)
        self.assertEqual(row["amendment_count"], 1)
        self.assertEqual(row["programs"][0]["entered_at"], "2026-02-26")
        self.assertEqual(row["programs"][1]["entered_at"], "2026-05-14")

    def test_history_reader_accepts_existing_date_only_chain(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "history.jsonl"
            first = h5v3.base.ensure_source_history(p)
            second = h5v3.base.ensure_source_history(p)
            self.assertTrue(first["chain_verified"])
            self.assertEqual(second["appended"], 0)
            self.assertEqual(len(h5v3.base.read_history(p)), len(h5v3.base.SERENITY_SOURCE_SEEDS))

    def test_transaction_failure_does_not_modify_existing_history(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "history.jsonl"
            h5v3.base.ensure_source_history(p)
            before = p.read_bytes()
            with mock.patch.object(h5v3.base, "apply_h5", side_effect=ValueError("synthetic failure")):
                with self.assertRaisesRegex(ValueError, "synthetic failure"):
                    h5v3.apply_h5_transactional({"results": [{}] * 7}, p)
            self.assertEqual(p.read_bytes(), before)

    def test_history_hash_tampering_fails_closed_before_apply(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "history.jsonl"
            h5v3.base.ensure_source_history(p)
            rows = p.read_text(encoding="utf-8").splitlines()
            first = json.loads(rows[0])
            first["paraphrase"] += " tampered"
            rows[0] = json.dumps(first, ensure_ascii=False, sort_keys=True)
            p.write_text("\n".join(rows) + "\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "record hash mismatch"):
                h5v3.apply_h5_transactional({"results": [{}] * 7}, p)

    def test_source_views_remain_date_only(self) -> None:
        for row in h5v3.base.SERENITY_SOURCE_SEEDS:
            self.assertEqual(row.get("time_precision"), "DATE_ONLY")
            self.assertRegex(str(row.get("published_at")), r"^\d{4}-\d{2}-\d{2}$")


if __name__ == "__main__":
    unittest.main()
