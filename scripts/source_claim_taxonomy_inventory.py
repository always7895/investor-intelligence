#!/usr/bin/env python3
"""Inventory the declared claim taxonomy against the live claim families.

This module reads the declared taxonomy manifest (``config/source-claim-taxonomy.json``)
and the coverage policy (``config/source-claim-coverage-policy.json``) and reports how many
declared claim classes exist, how many live claim families exist, and which declared classes
exactly match a live family identifier.

The inventory is a pure count/intersection report. It performs NO routing, NO qualification,
NO publication-eligibility decision, and NO network access. A declared class is matched to a
live family only on exact, case-sensitive identifier equality; an uppercase declared name is
never mapped to a semantically similar live family.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[1]
DEFAULT_TAXONOMY_PATH = BASE_DIR / "config" / "source-claim-taxonomy.json"
DEFAULT_POLICY_PATH = BASE_DIR / "config" / "source-claim-coverage-policy.json"

IDENTIFIER_PATTERN = re.compile(r"^[A-Za-z][A-Za-z0-9_]*$")
TAXONOMY_KEYS = frozenset({"schema_version", "claim_classes"})
SCHEMA_VERSION = 1
PRIVATE_ERROR = "taxonomy-inventory: invalid input"


class TaxonomyInventoryError(ValueError):
    """Declared taxonomy inventory validation failure."""


def _reject_duplicate_keys(pairs):
    seen = set()
    for key, _value in pairs:
        if key in seen:
            raise TaxonomyInventoryError("duplicate JSON key")
        seen.add(key)
    return dict(pairs)


def load_json_strict(path: Path):
    """Load a JSON file, rejecting duplicate keys at every nesting level."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        raise TaxonomyInventoryError("input not available") from None
    try:
        return json.loads(text, object_pairs_hook=_reject_duplicate_keys)
    except json.JSONDecodeError:
        raise TaxonomyInventoryError("invalid JSON") from None


def _validate_taxonomy(taxonomy) -> list[str]:
    if not isinstance(taxonomy, Mapping):
        raise TaxonomyInventoryError("taxonomy must be an object")
    if set(taxonomy.keys()) != TAXONOMY_KEYS:
        raise TaxonomyInventoryError("taxonomy has unknown or missing keys")
    version = taxonomy["schema_version"]
    if isinstance(version, bool) or not isinstance(version, int) or version != SCHEMA_VERSION:
        raise TaxonomyInventoryError("taxonomy schema_version must be 1")
    claim_classes = taxonomy["claim_classes"]
    if not isinstance(claim_classes, list):
        raise TaxonomyInventoryError("claim_classes must be a list")
    ids: list[str] = []
    seen: set[str] = set()
    for element in claim_classes:
        if not isinstance(element, str):
            raise TaxonomyInventoryError("claim class must be a string")
        if not IDENTIFIER_PATTERN.fullmatch(element):
            raise TaxonomyInventoryError("claim class must be a valid identifier")
        if element in seen:
            raise TaxonomyInventoryError("duplicate claim class")
        seen.add(element)
        ids.append(element)
    return ids


def _validate_policy(policy) -> list[str]:
    if not isinstance(policy, Mapping):
        raise TaxonomyInventoryError("policy must be an object")
    if "claim_families" not in policy:
        raise TaxonomyInventoryError("policy must define claim_families")
    claim_families = policy["claim_families"]
    if not isinstance(claim_families, Mapping):
        raise TaxonomyInventoryError("claim_families must be an object")
    ids: list[str] = []
    for key in claim_families.keys():
        if not isinstance(key, str):
            raise TaxonomyInventoryError("claim family must be a string")
        if not IDENTIFIER_PATTERN.fullmatch(key):
            raise TaxonomyInventoryError("claim family must be a valid identifier")
        ids.append(key)
    return ids


def inventory(taxonomy, policy) -> dict:
    """Return the declared taxonomy inventory against the live claim families.

    Pure function: no IO, no routing, no qualification, no publication decision.
    Raises ``TaxonomyInventoryError`` on any malformed, duplicate, or invalid input.
    """
    declared_ids = _validate_taxonomy(taxonomy)
    legacy_ids = _validate_policy(policy)
    legacy_set = set(legacy_ids)
    exact_matches = [cid for cid in declared_ids if cid in legacy_set]
    unmapped = [cid for cid in declared_ids if cid not in legacy_set]
    return {
        "declared_claim_count": len(declared_ids),
        "declared_claim_ids": list(declared_ids),
        "legacy_family_count": len(legacy_ids),
        "legacy_family_ids": list(legacy_ids),
        "exact_id_matches": exact_matches,
        "unmapped_claim_ids": unmapped,
        "publication_eligible": False,
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="source_claim_taxonomy_inventory",
        description="Inventory the declared claim taxonomy against the live claim families.",
    )
    parser.add_argument("--taxonomy", default=str(DEFAULT_TAXONOMY_PATH))
    parser.add_argument("--policy", default=str(DEFAULT_POLICY_PATH))
    args = parser.parse_args(argv)
    try:
        taxonomy = load_json_strict(Path(args.taxonomy))
        policy = load_json_strict(Path(args.policy))
        result = inventory(taxonomy, policy)
    except Exception:
        print(PRIVATE_ERROR, file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())