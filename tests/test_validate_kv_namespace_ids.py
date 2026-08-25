from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from validate_kv_namespace_ids import (  # noqa: E402
    ALL_NAMES,
    validate_namespace_ids,
)


class ValidateKvNamespaceIdsTests(unittest.TestCase):
    def valid_environment(self) -> dict[str, str]:
        return {
            name: f"synthetic-{index:02d}-abcdef1234567890"
            for index, name in enumerate(ALL_NAMES, start=1)
        }

    def test_six_distinct_ids_pass_without_exposing_values(self) -> None:
        environment = self.valid_environment()
        result = validate_namespace_ids(environment)
        self.assertTrue(result.configured)
        self.assertTrue(result.valid)
        public = result.as_public_dict()
        self.assertFalse(public["values_exposed"])
        serialized = str(public)
        for value in environment.values():
            self.assertNotIn(value, serialized)

    def test_missing_ids_are_reported_by_label_only(self) -> None:
        environment = self.valid_environment()
        missing = ALL_NAMES[2]
        environment.pop(missing)
        result = validate_namespace_ids(environment)
        self.assertFalse(result.configured)
        self.assertFalse(result.valid)
        self.assertIn(missing, result.missing_labels)

    def test_duplicate_ids_across_any_role_fail(self) -> None:
        environment = self.valid_environment()
        environment[ALL_NAMES[-1]] = environment[ALL_NAMES[0]]
        result = validate_namespace_ids(environment)
        self.assertFalse(result.valid)
        self.assertEqual(len(result.duplicate_role_groups), 1)
        self.assertEqual(
            set(result.duplicate_role_groups[0]),
            {ALL_NAMES[0], ALL_NAMES[-1]},
        )

    def test_placeholders_fail_even_when_all_labels_exist(self) -> None:
        environment = self.valid_environment()
        environment[ALL_NAMES[0]] = "REPLACE_WITH_PUBLIC_NAMESPACE_ID"
        result = validate_namespace_ids(environment)
        self.assertFalse(result.configured)
        self.assertFalse(result.valid)
        self.assertIn(ALL_NAMES[0], result.placeholder_labels)


if __name__ == "__main__":
    unittest.main()
