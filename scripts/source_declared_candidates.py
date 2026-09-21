#!/usr/bin/env python3
"""Route one explicitly approved declared-claim candidate profile.

This module implements a NARROW EXPLICIT CANDIDATE PROFILE, not general
canonical qualification. It supports exactly one approved pair: the declared
claim class ``MACRO`` with the candidate profile ``statistical-series-v1``.
That pair is a fixed, code-owned mapping to the legacy claim family
``macro_indicator`` (an explicitly approved statistical-series candidate
subset). It is NOT a caller-selected mapping and NOT complete MACRO support.

The module performs NO qualification, NO subject binding, NO geographic
binding, NO evidence qualification, NO scoring, NO source admission, NO
fetching, and NO network access. It validates the declaration through the
existing ``source_claim_taxonomy_inventory.inventory`` helper, requires a
valid existing federation ceiling through
``source_registry.activation_max_age``, and delegates candidate routing to the
existing ``source_registry.route_claim`` helper. The delegated route is passed
through unchanged and reported as ``CANDIDATES_ONLY`` metadata.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from source_claim_taxonomy_inventory import (
    DEFAULT_TAXONOMY_PATH,
    inventory,
    load_json_strict,
)
from source_registry import (
    DEFAULT_CLAIM_POLICY_PATH,
    DEFAULT_FEDERATION_POLICY_PATH,
    DEFAULT_POLICY_PATH,
    DEFAULT_SOURCE_DIR,
    activation_max_age,
    load_registry,
    route_claim,
)

# Fixed approved pair and the code-owned legacy family mapping. This is a
# single, explicitly approved statistical-series candidate subset; it is not a
# mapping table and not complete MACRO support.
CLAIM_CLASS = "MACRO"
PROFILE = "statistical-series-v1"
MAPPED_FAMILY = "macro_indicator"

PRIVATE_ERROR = "declared-candidates: invalid input"


class DeclaredCandidatesError(ValueError):
    """Declared candidate profile validation failure."""


def route_declared_candidates(
    registry,
    taxonomy,
    claim_policy,
    federation_policy,
    *,
    claim_class,
    profile,
):
    """Route one explicitly approved declared-claim candidate profile.

    Supports exactly the approved pair ``MACRO`` + ``statistical-series-v1``,
    mapped to the code-owned legacy family ``macro_indicator``. Performs no
    qualification, subject binding, geographic binding, scoring, admission,
    fetching, or network access. The delegated ``route_claim`` result is
    returned unchanged inside a ``CANDIDATES_ONLY`` envelope.
    """
    # 1. Exact approved pair (strict strings). Any other pair is refused.
    if claim_class != CLAIM_CLASS or profile != PROFILE:
        raise DeclaredCandidatesError("unsupported claim/profile pair")

    # 2. Validate the declaration via the existing inventory and ensure MACRO
    #    is actually declared.
    report = inventory(taxonomy, claim_policy)
    if CLAIM_CLASS not in report["declared_claim_ids"]:
        raise DeclaredCandidatesError("MACRO is not a declared claim class")

    # 3. Require a valid existing federation ceiling; never drop it.
    ceiling = activation_max_age(federation_policy)
    if ceiling is None:
        raise DeclaredCandidatesError("missing or invalid federation ceiling")

    # 4. Delegate candidate routing to the existing helper with the fixed
    #    code-owned family, runtime-only, and the supplied federation policy.
    #    No predicate cloning and no alteration of the returned route.
    route = route_claim(
        registry,
        MAPPED_FAMILY,
        claim_policy,
        runtime_only=True,
        federation_policy=federation_policy,
    )

    # 5. Build the CANDIDATES_ONLY envelope with the unchanged delegated route.
    return {
        "stage": "CANDIDATES_ONLY",
        "claim_class": CLAIM_CLASS,
        "profile": PROFILE,
        "mapped_family": MAPPED_FAMILY,
        "route_performed": True,
        "qualification_performed": False,
        "subject_binding_performed": False,
        "geographic_binding_performed": False,
        "publication_eligible": False,
        "route": route,
    }


class _SafeParser(argparse.ArgumentParser):
    """Argument parser that never echoes raw messages (which may be private)."""

    def error(self, message):  # noqa: ARG002 - message intentionally ignored
        print(PRIVATE_ERROR, file=sys.stderr)
        raise SystemExit(2)


def main(argv=None) -> int:
    parser = _SafeParser(
        prog="source_declared_candidates",
        description="Route one explicitly approved declared-claim candidate profile.",
    )
    parser.add_argument("--claim-class", required=True)
    parser.add_argument("--profile", required=True)
    parser.add_argument("--catalog-dir", default=None)
    parser.add_argument("--taxonomy", default=None)
    parser.add_argument("--claim-policy", default=None)
    parser.add_argument("--federation-policy", default=None)
    try:
        args = parser.parse_args(argv)
    except SystemExit:
        # parser.error already printed the private-safe message.
        return 2
    try:
        source_dir = Path(args.catalog_dir) if args.catalog_dir else DEFAULT_SOURCE_DIR
        taxonomy_path = Path(args.taxonomy) if args.taxonomy else DEFAULT_TAXONOMY_PATH
        claim_policy_path = (
            Path(args.claim_policy) if args.claim_policy else DEFAULT_CLAIM_POLICY_PATH
        )
        federation_policy_path = (
            Path(args.federation_policy)
            if args.federation_policy
            else DEFAULT_FEDERATION_POLICY_PATH
        )
        registry = load_registry(source_dir, DEFAULT_POLICY_PATH)
        taxonomy = load_json_strict(taxonomy_path)
        claim_policy = load_json_strict(claim_policy_path)
        federation_policy = load_json_strict(federation_policy_path)
        envelope = route_declared_candidates(
            registry,
            taxonomy,
            claim_policy,
            federation_policy,
            claim_class=args.claim_class,
            profile=args.profile,
        )
        print(json.dumps(envelope, indent=2, sort_keys=True))
        return 0
    except Exception:
        print(PRIVATE_ERROR, file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())