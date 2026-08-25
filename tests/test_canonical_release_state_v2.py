from __future__ import annotations

import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class CanonicalReleaseStateTests(unittest.TestCase):
    def test_candidate_state_is_fail_closed(self) -> None:
        state = json.loads(
            (ROOT / "state" / "canonical-release-candidate-v2.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(state["schema_version"], 1)
        for key in (
            "release_ready",
            "deployed",
            "billing_enabled",
            "line_connected",
            "ibkr_connected",
            "private_sync_enabled",
            "paid_fallback_enabled",
            "git_history_rewritten",
            "final_package_published",
        ):
            with self.subTest(key=key):
                self.assertIs(state[key], False)
        self.assertEqual(state["status"], "PENDING_EXACT_HEAD_ACCEPTANCE")
        self.assertGreaterEqual(len(state["required_exact_head_gates"]), 10)


if __name__ == "__main__":
    unittest.main()
