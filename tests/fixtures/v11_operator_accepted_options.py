"""Test support for the V11 operator-accepted Yahoo option provider and the previous-session carry-forward.

The catalog entry below is the TEST'S OWN COPY of the pinned operator decision (R/OPERATOR-DECISION-OPTIONS-DISPLAY-ALL-20261013.txt): the
tests build a throw-away root whose catalog carries it, so the gate, the policy and the producer are exercised against exactly the state
the repository catalog is meant to reach, without depending on the repository catalog having been edited. A parity test compares this
copy with config/public-options-provider-candidates.json when the entry is present there. Nothing here is a rights decision.
"""
from __future__ import annotations

import contextlib
import copy
import json
import shutil
import sys
import tempfile
from datetime import date
from pathlib import Path
from typing import Any, Iterator

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import public_options_provider_gate as gate  # noqa: E402

YAHOO_ID = "yahoo_finance_option_chain"
DECISION_ID = "OPERATOR-DECISION-OPTIONS-DISPLAY-ALL-20261013"
TODAY = date(2026, 10, 13)
IDENTITY = {"provider_id": YAHOO_ID, "jurisdiction": "US", "venue": "US_LISTED_OPTIONS", "instrument_kind": "equity_option",
            "publication_scope": "public_line_quote"}

YAHOO_ENTRY: dict[str, Any] = {
    "id": YAHOO_ID,
    "name": "Yahoo Finance US option chains (unofficial, delayed; operator-accepted display)",
    "authority": "Yahoo Finance",
    "jurisdictions": ["US"],
    "data_roles": ["delayed_option_quotes"],
    "official_url": "https://finance.yahoo.com/",
    "rights_evidence_url": "https://legal.yahoo.com/us/en/yahoo/terms/otos/index.html",
    "rights_status": "operator_accepted_unlicensed",
    "automated_access_allowed": None,
    "rights_reviewed_at": "2026-10-13",
    "review_notes": "TEST COPY: not a rights review and not a licence; the operator decision of 2026-10-13 accepts the exposure.",
    "adapter_status": "candidate_implemented",
    "runtime_enabled": True,
    "line_quote_eligible": True,
    "review_valid_through": "2027-10-13",
    "admitted_scopes": [
        {"jurisdiction": "US", "venue": "US_LISTED_OPTIONS", "instrument_kind": "equity_option", "quote_basis": "delayed",
         "publication_scope": "public_line_quote"},
        {"jurisdiction": "US", "venue": "US_LISTED_OPTIONS", "instrument_kind": "equity_option", "quote_basis": "previous_session_last",
         "publication_scope": "public_line_quote"},
    ],
    "operator_decision": {"decision_id": DECISION_ID, "decided_at": "2026-10-13", "record": "docs/PUBLIC_OPTIONS_PROVIDER_RIGHTS_REVIEW.md"},
}

# V13 (operator 2026-10-17, R/OPERATOR-DECISION-OPTIONS-NORDIC-DISPLAY-20261017.txt): the second pinned provider, Nasdaq Nordic Stockholm.
NORDIC_ID = "nasdaq_nordic_option_chain"
NORDIC_DECISION_ID = "OPERATOR-DECISION-OPTIONS-NORDIC-DISPLAY-20261017"
NORDIC_TODAY = date(2026, 10, 19)
NORDIC_IDENTITY = {"provider_id": NORDIC_ID, "jurisdiction": "SE", "venue": "NASDAQ_STOCKHOLM_OPTIONS", "instrument_kind": "equity_option",
                   "publication_scope": "public_line_quote"}
NORDIC_ENTRY: dict[str, Any] = {
    "id": NORDIC_ID,
    "name": "Nasdaq Nordic Stockholm option chains (exchange public web data, delayed; operator-accepted display)",
    "authority": "Nasdaq Nordic",
    "jurisdictions": ["SE"],
    "data_roles": ["delayed_option_quotes"],
    "official_url": "https://www.nasdaq.com/european-market-activity",
    "rights_evidence_url": "https://www.nasdaq.com/legal",
    "rights_status": "operator_accepted_unlicensed",
    "automated_access_allowed": None,
    "rights_reviewed_at": "2026-10-17",
    "review_notes": "TEST COPY: not a rights review and not a licence; the operator decision of 2026-10-17 accepts the exposure.",
    "adapter_status": "candidate_implemented",
    "runtime_enabled": True,
    "line_quote_eligible": True,
    "review_valid_through": "2027-10-17",
    "admitted_scopes": [
        {"jurisdiction": "SE", "venue": "NASDAQ_STOCKHOLM_OPTIONS", "instrument_kind": "equity_option", "quote_basis": "delayed",
         "publication_scope": "public_line_quote"},
    ],
    "operator_decision": {"decision_id": NORDIC_DECISION_ID, "decided_at": "2026-10-17", "record": "docs/PUBLIC_OPTIONS_PROVIDER_RIGHTS_REVIEW.md"},
}

ROOT_FILES = (
    "config/public-options-provider-candidates.json",
    "config/public-options-development-provider.json",
    "config/runtime-policy.json",
    "cloud/wrangler.toml",
    "scripts/build_line_public_options.py",
)


def catalog_document(*, with_yahoo: bool = True, with_nordic: bool = False) -> dict[str, Any]:
    """The repository catalog with the test copies of the operator-accepted entries (replacing repository ones) and the matching root
    selection. The Nordic entry is opt-in so the Yahoo rows keep proving the Yahoo behaviour on its own."""
    document = json.loads((ROOT / "config" / "public-options-provider-candidates.json").read_text(encoding="utf-8"))
    document["providers"] = [item for item in document["providers"] if item["id"] not in (YAHOO_ID, NORDIC_ID)]
    if with_yahoo:
        document["providers"].append(copy.deepcopy(YAHOO_ENTRY))
    if with_nordic:
        document["providers"].append(copy.deepcopy(NORDIC_ENTRY))
    document["production_quote_provider_selected"] = any(
        item.get("runtime_enabled") is True and item.get("line_quote_eligible") is True and (
            gate._rights_reviewed(item) or gate._operator_accepted(item)) for item in document["providers"])
    return document


@contextlib.contextmanager
def catalog_root(document: dict[str, Any] | None = None) -> Iterator[Path]:
    """A throw-away repository root (the files the audit reads) whose catalog is `document` (default: with the Yahoo entry)."""
    with tempfile.TemporaryDirectory(prefix="v11_options_root_") as folder:
        root = Path(folder)
        for relative in ROOT_FILES:
            target = root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(ROOT / relative, target)
        write_catalog(root, catalog_document() if document is None else document)
        yield root


def write_catalog(root: Path, document: dict[str, Any]) -> None:
    (root / "config" / "public-options-provider-candidates.json").write_text(
        json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def both_policy(today: date = NORDIC_TODAY) -> Any:
    """The admission policy of a test catalog carrying both operator-accepted providers."""
    with catalog_root(catalog_document(with_nordic=True)) as root:
        return gate.load_public_option_policy(root, today=today)


def yahoo_policy(today: date = TODAY) -> Any:
    """The admission policy of the test catalog (Yahoo operator-accepted)."""
    with catalog_root() as root:
        return gate.load_public_option_policy(root, today=today)
