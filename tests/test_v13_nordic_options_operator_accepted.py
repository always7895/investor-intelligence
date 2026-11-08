"""V13 item 3b: the operator-accepted (unlicensed) Nasdaq Nordic option provider, a second pinned provider beside Yahoo.

Every row runs against a throw-away root whose catalog carries the test copies of the pinned entries (tests/fixtures/v11_operator_accepted_options.py);
a parity test compares the Nordic copy with the repository catalog. Positive rows, the pins (id, decision, scopes), forged and mismatched claims,
the revert, the review window, and the real producer -> real sealer chain (tests/fixtures/v13_nordic_options_cases.py).
"""
from __future__ import annotations

import copy
import json
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import build_market_quotes_options as builder  # noqa: E402
import public_options_provider_gate as gate  # noqa: E402
from tests.fixtures import v11_operator_accepted_options as support  # noqa: E402
from tests.fixtures import v13_nordic_options_cases as cases  # noqa: E402

TODAY = support.NORDIC_TODAY
NORDIC_CLAIM = {**support.NORDIC_IDENTITY, "quote_basis": "delayed"}
YAHOO_CLAIM = {**support.IDENTITY, "quote_basis": "delayed"}
BOTH = sorted([support.NORDIC_ID, support.YAHOO_ID])
DENIED = gate.OPTION_RIGHTS_NOT_ADMITTED


def both_document() -> dict:
    return support.catalog_document(with_nordic=True)


def audit(document: dict, root: Path, today: date = TODAY):
    support.write_catalog(root, document)
    return gate.audit_public_options_providers(root, today=today)


def provider_of(document: dict, provider_id: str) -> dict:
    return next(item for item in document["providers"] if item["id"] == provider_id)


def policy_of(document: dict, root: Path, today: date = TODAY):
    support.write_catalog(root, document)
    return gate.load_public_option_policy(root, today=today)


class NordicPositiveTests(unittest.TestCase):
    def test_both_pinned_entries_pass_the_audit_and_are_the_only_eligible_providers(self) -> None:
        with support.catalog_root(both_document()) as root:
            findings, summary = gate.audit_public_options_providers(root, today=TODAY)
        self.assertEqual(findings, [])
        self.assertEqual(summary["fully_eligible_provider_ids"], BOTH)
        self.assertEqual((summary["fully_eligible_count"], summary["operator_accepted_count"], summary["runtime_enabled_count"]), (2, 2, 2))
        self.assertTrue(summary["production_provider_selected"])
        self.assertEqual(summary["automation_prohibited_count"], 4)

    def test_policy_admits_exactly_the_nordic_scope_and_nothing_else(self) -> None:
        policy = support.both_policy()
        self.assertEqual(policy.provider_ids(), BOTH)
        self.assertIsNone(gate.public_option_cycle_admission(NORDIC_CLAIM, policy))
        self.assertIsNone(gate.public_option_cycle_admission(YAHOO_CLAIM, policy))  # Yahoo unchanged beside it
        for basis in ("delayed", "previous_session_last"):
            self.assertIsNone(gate.public_option_cycle_admission({**support.IDENTITY, "quote_basis": basis}, policy), basis)
        for field, value in (("quote_basis", "previous_session_last"), ("quote_basis", "realtime"), ("quote_basis", "asof_close"),
                             ("jurisdiction", "US"), ("jurisdiction", "NO"), ("venue", "US_LISTED_OPTIONS"), ("venue", "STOCKHOLM"),
                             ("venue", "NASDAQ_STOCKHOLM_OPTIONS "), ("instrument_kind", "eod_index"), ("publication_scope", "local_research"),
                             ("provider_id", "nasdaq_nordic_option_chain "), ("provider_id", "nyse_options_reference")):
            self.assertEqual(gate.public_option_cycle_admission({**NORDIC_CLAIM, field: value}, policy), DENIED, (field, value))
        for field in NORDIC_CLAIM:
            self.assertEqual(gate.public_option_cycle_admission({k: v for k, v in NORDIC_CLAIM.items() if k != field}, policy), DENIED, field)
            self.assertEqual(gate.public_option_cycle_admission({**NORDIC_CLAIM, field: None}, policy), DENIED, field)
        # a label, source text or a caller flag never admits
        self.assertEqual(gate.public_option_cycle_admission(
            {"rights_status": "operator_accepted_unlicensed", "source": "Nasdaq Nordic option chain", "quote_basis": "delayed"}, policy), DENIED)

    def test_the_two_identities_never_cross(self) -> None:
        policy = support.both_policy()
        # a Nordic row claiming the Yahoo identity, a Yahoo row claiming the Nordic one, and every mixed scope are refused
        mixes = (
            {**NORDIC_CLAIM, "provider_id": support.YAHOO_ID},
            {**YAHOO_CLAIM, "provider_id": support.NORDIC_ID},
            {**YAHOO_CLAIM, "jurisdiction": "SE"},
            {**YAHOO_CLAIM, "venue": "NASDAQ_STOCKHOLM_OPTIONS"},
            {**NORDIC_CLAIM, "jurisdiction": "US"},
            {**NORDIC_CLAIM, "venue": "US_LISTED_OPTIONS"},
        )
        for claim in mixes:
            self.assertEqual(gate.public_option_cycle_admission(claim, policy), DENIED, claim)

    def test_the_builder_claims_exactly_the_catalog_identity_and_yahoo_is_unchanged(self) -> None:
        self.assertEqual(builder.NORDIC_OPTION_IDENTITY, support.NORDIC_IDENTITY)
        self.assertEqual(builder.NORDIC_RIGHTS_LABEL, "operator_accepted_unlicensed")
        self.assertEqual(builder.YAHOO_OPTION_IDENTITY, support.IDENTITY)
        self.assertEqual(builder.YAHOO_RIGHTS_LABEL, "operator_accepted_unlicensed")
        scopes = {(item["jurisdiction"], item["venue"], item["instrument_kind"], item["quote_basis"], item["publication_scope"])
                  for item in support.NORDIC_ENTRY["admitted_scopes"]}
        self.assertEqual(scopes, gate.OPERATOR_ACCEPTED_PROVIDERS[support.NORDIC_ID]["scopes"])
        self.assertEqual(scopes, {("SE", "NASDAQ_STOCKHOLM_OPTIONS", "equity_option", "delayed", "public_line_quote")})  # delayed only: no carry-forward
        self.assertEqual(gate.OPERATOR_ACCEPTED_PROVIDERS[support.NORDIC_ID]["operator_decision"],
                         {"decision_id": support.NORDIC_DECISION_ID, "decided_at": "2026-10-17", "record": "docs/PUBLIC_OPTIONS_PROVIDER_RIGHTS_REVIEW.md"})
        self.assertEqual(sorted(gate.OPERATOR_ACCEPTED_PROVIDERS), sorted(BOTH + [support.NASDAQ_ID]))  # these two plus the V19 Nasdaq US pin

    def test_the_repository_catalog_entry_equals_the_pinned_copy(self) -> None:
        repository = json.loads((ROOT / "config" / "public-options-provider-candidates.json").read_text(encoding="utf-8"))
        found = [item for item in repository["providers"] if item["id"] == support.NORDIC_ID]
        self.assertEqual(len(found), 1)
        strip = lambda entry: {key: value for key, value in entry.items() if key not in ("name", "review_notes")}  # noqa: E731
        self.assertEqual(strip(found[0]), strip(support.NORDIC_ENTRY))
        self.assertEqual(found[0]["rights_evidence_url"], "https://www.nasdaq.com/legal")
        self.assertIn("NOT a rights review and NOT a licence", found[0]["review_notes"])
        self.assertIn(support.NORDIC_DECISION_ID, found[0]["review_notes"])
        yahoo = [item for item in repository["providers"] if item["id"] == support.YAHOO_ID]
        self.assertEqual(strip(yahoo[0]), strip(support.YAHOO_ENTRY))  # the Yahoo entry is byte-for-byte what it was
        findings, summary = gate.audit_public_options_providers(ROOT, today=TODAY)
        self.assertEqual(findings, [])
        self.assertEqual(summary["fully_eligible_provider_ids"], sorted(BOTH + [support.NASDAQ_ID]))  # V19 added the third pinned provider

    def test_the_worker_constants_mirror_the_python_pins(self) -> None:
        source = (ROOT / "cloud" / "src" / "v213" / "public-options-admission.ts").read_text(encoding="utf-8")
        pinned = gate.OPERATOR_ACCEPTED_PROVIDERS[support.NORDIC_ID]
        self.assertIn("nasdaq_nordic_option_chain: {", source)
        for value in pinned["operator_decision"].values():
            self.assertIn(f'"{value}"', source)
        for scope in pinned["scopes"]:
            self.assertIn("JSON.stringify([" + ", ".join(f'"{part}"' for part in scope) + "])", source)
        self.assertIn("yahoo_finance_option_chain: {", source)


class NordicPinTests(unittest.TestCase):
    def test_a_forged_or_altered_nordic_entry_makes_the_whole_catalog_unusable(self) -> None:
        mutations = {
            "decision id": lambda p: p["operator_decision"].__setitem__("decision_id", "OPERATOR-DECISION-SOMETHING-ELSE"),
            "decision id of the Yahoo decision": lambda p: p["operator_decision"].__setitem__("decision_id", support.DECISION_ID),
            "decision date": lambda p: p["operator_decision"].__setitem__("decided_at", "2026-10-13"),
            "decision record": lambda p: p["operator_decision"].__setitem__("record", "docs/README.md"),
            "extra decision key": lambda p: p["operator_decision"].__setitem__("approved_by", "someone"),
            "decision removed": lambda p: p.pop("operator_decision"),
            "review date": lambda p: p.__setitem__("rights_reviewed_at", "2026-10-16"),
            "claims automation": lambda p: p.__setitem__("automated_access_allowed", True),
            "claims prohibition": lambda p: p.__setitem__("automated_access_allowed", False),
            "no adapter": lambda p: p.__setitem__("adapter_status", "not_implemented"),
            "foreign venue scope": lambda p: p["admitted_scopes"][0].__setitem__("venue", "OTHERVENUE"),
            "yahoo venue scope": lambda p: p["admitted_scopes"][0].__setitem__("venue", "US_LISTED_OPTIONS"),
            "foreign basis scope": lambda p: p["admitted_scopes"][0].__setitem__("quote_basis", "realtime"),
            "carried basis scope": lambda p: p["admitted_scopes"].append({**p["admitted_scopes"][0], "quote_basis": "previous_session_last"}),
            "scope outside the pin": lambda p: p["admitted_scopes"].append({**p["admitted_scopes"][0], "venue": "NASDAQ_STOCKHOLM_OPTIONS_EXTRA"}),
            "scope of another jurisdiction": lambda p: (p["jurisdictions"].append("US"), p["admitted_scopes"].append(
                {**p["admitted_scopes"][0], "jurisdiction": "US", "venue": "US_LISTED_OPTIONS"})),
            "no scopes": lambda p: p.__setitem__("admitted_scopes", []),
            "reviewed status without review": lambda p: p.__setitem__("rights_status", "reviewed_public_access"),
            "window closed": lambda p: p.__setitem__("review_valid_through", "2026-10-18"),
            "window before the decision": lambda p: p.__setitem__("review_valid_through", "2026-10-16"),
        }
        with support.catalog_root(both_document()) as root:
            for name, mutate in mutations.items():
                with self.subTest(name):
                    document = both_document()
                    mutate(provider_of(document, support.NORDIC_ID))
                    document["production_quote_provider_selected"] = True
                    findings, _ = audit(document, root)
                    self.assertTrue(findings, name)
                    policy = policy_of(document, root)
                    self.assertEqual(policy.provider_ids(), [], name)  # Yahoo is refused with it: one malformed provider voids the catalog
                    self.assertEqual(gate.public_option_cycle_admission(YAHOO_CLAIM, policy), DENIED, name)
                    self.assertEqual(gate.public_option_cycle_admission(NORDIC_CLAIM, policy), DENIED, name)

    def test_a_second_provider_claiming_the_nordic_id_or_a_third_claiming_the_status_is_refused(self) -> None:
        with support.catalog_root(both_document()) as root:
            document = both_document()
            document["providers"].append(copy.deepcopy(support.NORDIC_ENTRY))  # a duplicate of the pinned id
            findings, _ = audit(document, root)
            self.assertTrue(findings, findings)
            self.assertEqual(policy_of(document, root).provider_ids(), [])
            base = both_document()
            others = [item["id"] for item in base["providers"] if item["id"] not in BOTH + [support.NASDAQ_ID]]  # the Nasdaq US id is pinned since V19
            self.assertGreaterEqual(len(others), 11)
            for provider_id in others:
                with self.subTest(provider=provider_id):
                    document = copy.deepcopy(base)
                    forged = provider_of(document, provider_id)
                    forged.update({key: copy.deepcopy(support.NORDIC_ENTRY[key]) for key in (
                        "rights_status", "automated_access_allowed", "rights_reviewed_at", "adapter_status", "runtime_enabled",
                        "line_quote_eligible", "review_valid_through", "admitted_scopes", "operator_decision")})
                    forged["jurisdictions"] = ["SE"]
                    findings, _ = audit(document, root)
                    self.assertTrue(any("accepted only for the pinned operator decisions" in item for item in findings), findings)
                    self.assertEqual(policy_of(document, root).provider_ids(), [])

    def test_the_two_decisions_cannot_be_swapped_between_the_providers(self) -> None:
        with support.catalog_root(both_document()) as root:
            document = both_document()  # Yahoo carrying the Nordic decision and scope
            provider_of(document, support.YAHOO_ID).update(
                operator_decision=copy.deepcopy(support.NORDIC_ENTRY["operator_decision"]), rights_reviewed_at="2026-10-17")
            findings, _ = audit(document, root)
            self.assertTrue(any("operator_decision must equal the pinned operator decision" in item for item in findings), findings)
            document = both_document()  # Nordic carrying the Yahoo decision
            provider_of(document, support.NORDIC_ID).update(
                operator_decision=copy.deepcopy(support.YAHOO_ENTRY["operator_decision"]), rights_reviewed_at="2026-10-13")
            findings, _ = audit(document, root)
            self.assertTrue(any("operator_decision must equal the pinned operator decision" in item for item in findings), findings)
            document = both_document()  # Nordic row carrying a Yahoo scope
            provider_of(document, support.NORDIC_ID)["admitted_scopes"] = copy.deepcopy(support.YAHOO_ENTRY["admitted_scopes"])
            provider_of(document, support.NORDIC_ID)["jurisdictions"] = ["US"]
            findings, _ = audit(document, root)
            self.assertTrue(any("admitted_scopes must be a subset" in item for item in findings), findings)
            document = both_document()  # Yahoo row carrying the Nordic scope
            provider_of(document, support.YAHOO_ID)["admitted_scopes"] = copy.deepcopy(support.NORDIC_ENTRY["admitted_scopes"])
            provider_of(document, support.YAHOO_ID)["jurisdictions"] = ["SE"]
            findings, _ = audit(document, root)
            self.assertTrue(any("admitted_scopes must be a subset" in item for item in findings), findings)

    def test_the_four_pinned_prohibitions_stay_rejected(self) -> None:
        policy = support.both_policy()
        for provider_id in ("cboe_public_options_market_data", "occ_public_market_data", "marketdata_app_free_forever", "tradier_broker_market_data_api",
                            "taifex_public_options", "nyse_options_reference"):
            self.assertIsNone(policy.provider(provider_id), provider_id)
            self.assertEqual(gate.public_option_cycle_admission({**NORDIC_CLAIM, "provider_id": provider_id}, policy), DENIED)


class NordicRevertAndWindowTests(unittest.TestCase):
    def test_reverting_nordic_alone_changes_nothing_else(self) -> None:
        with support.catalog_root(both_document()) as root:
            document = both_document()
            for field in ("runtime_enabled", "line_quote_eligible"):  # the documented revert: both flags off together
                provider_of(document, support.NORDIC_ID)[field] = False
            findings, summary = audit(document, root)
            self.assertEqual(findings, [])
            self.assertEqual(summary["fully_eligible_provider_ids"], [support.YAHOO_ID])
            policy = policy_of(document, root)
            self.assertEqual(policy.provider_ids(), [support.YAHOO_ID])
            self.assertEqual(gate.public_option_cycle_admission(NORDIC_CLAIM, policy), DENIED)
            self.assertIsNone(gate.public_option_cycle_admission(YAHOO_CLAIM, policy))
            self.assertIsNone(gate.public_option_cycle_admission({**YAHOO_CLAIM, "quote_basis": "previous_session_last"}, policy))

    def test_reverting_both_admits_nothing_and_a_partial_revert_is_refused(self) -> None:
        with support.catalog_root(both_document()) as root:
            document = both_document()
            for provider_id in BOTH:
                for field in ("runtime_enabled", "line_quote_eligible"):
                    provider_of(document, provider_id)[field] = False
            document["production_quote_provider_selected"] = False
            findings, summary = audit(document, root)
            self.assertEqual(findings, [])
            self.assertEqual(summary["fully_eligible_count"], 0)
            self.assertEqual(policy_of(document, root).provider_ids(), [])
            document = both_document()
            provider_of(document, support.NORDIC_ID)["line_quote_eligible"] = False
            findings, _ = audit(document, root)
            self.assertTrue(any("must change atomically" in item for item in findings), findings)

    def test_the_review_window_closes_on_its_own_date(self) -> None:
        with support.catalog_root(both_document()) as root:
            support.write_catalog(root, both_document())
            self.assertEqual(gate.load_public_option_policy(root, today=date(2026, 10, 17)).provider_ids(), BOTH)  # the decision day
            self.assertEqual(gate.load_public_option_policy(root, today=date(2026, 10, 16)).provider_ids(), [support.YAHOO_ID])  # before the decision: no Nordic
            self.assertEqual(gate.load_public_option_policy(root, today=date(2027, 10, 13)).provider_ids(), BOTH)  # last Yahoo day
            self.assertEqual(gate.load_public_option_policy(root, today=date(2027, 10, 14)).provider_ids(), [])    # Yahoo window closed: whole catalog
            # Nordic alone: with the Yahoo window renewed, Nordic is admitted through 2027-10-17 and refused the day after.
            document = both_document()
            provider_of(document, support.YAHOO_ID)["review_valid_through"] = "2028-10-13"
            support.write_catalog(root, document)
            self.assertEqual(gate.load_public_option_policy(root, today=date(2027, 10, 17)).provider_ids(), BOTH)
            self.assertEqual(gate.load_public_option_policy(root, today=date(2027, 10, 18)).provider_ids(), [])


class NordicProducerSealerTests(unittest.TestCase):
    """The real producer CLI and the real sealer (no admission seam): Stockholm cycles are admitted only under the catalog that carries Nordic."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.both = cases.produce_and_seal(support.both_policy())
        cls.yahoo_only = cases.produce_and_seal(support.yahoo_policy(support.NORDIC_TODAY))
        cls.reverted = cases.produce_and_seal(cases_policy_without_nordic())

    def test_producer_stockholm_cycles_claim_the_nordic_identity_with_the_delayed_basis(self) -> None:
        for period in ("weekly", "monthly"):
            cycle = self.both["options"][cases.SIVE][period]
            self.assertNotIn("unavailable", cycle, period)
            self.assertEqual({key: cycle[key] for key in support.NORDIC_IDENTITY}, support.NORDIC_IDENTITY)
            self.assertEqual((cycle["quote_basis"], cycle["currency"], cycle["rights_status"]), ("delayed", "SEK", "operator_accepted_unlicensed"))
            self.assertEqual(cycle["source"], builder.NORDIC_SOURCE)
        us_cycle = self.both["options"][cases.US_SIBLING]["monthly"]  # US cycles unchanged: the Yahoo identity
        self.assertEqual({key: us_cycle[key] for key in support.IDENTITY}, support.IDENTITY)
        self.assertEqual(us_cycle["currency"], "USD")

    def test_without_the_nordic_entry_the_stockholm_cycles_are_refused_and_yahoo_is_unchanged(self) -> None:
        for sealed in (self.yahoo_only, self.reverted):
            for period in ("weekly", "monthly"):
                self.assertEqual(sealed["options"][cases.SIVE][period], {"unavailable": gate.OPTION_RIGHTS_UNAVAILABLE_ZH}, period)
            self.assertEqual(sealed["options"][cases.US_SIBLING]["monthly"], self.both["options"][cases.US_SIBLING]["monthly"])

    def test_a_forged_claim_is_refused_by_the_real_sealer(self) -> None:
        from unittest import mock

        import publish_sealed_snapshot as publisher

        base = self.both["options"][cases.SIVE]["monthly"]
        forged = {"carried basis": {**base, "quote_basis": "previous_session_last"},
                  "foreign venue": {**base, "venue": "STOCKHOLM"},
                  "foreign provider": {**base, "provider_id": "nyse_options_reference"},
                  "no identity": {key: value for key, value in base.items() if key != "provider_id"}}
        policy = support.both_policy()
        document = {"schema": "v213-market-observations-v2", "generated_at": base["timestamp"], "options": {}, "quotes": {
            f"Q{i}": {"symbol": f"Q{i}", "price": 100.0, "previous_close": 99.0, "change_pct": 0.01, "currency": "USD", "asof": base["timestamp"],
                      "source": "Yahoo Finance (unofficial, delayed)", "source_url": f"https://finance.yahoo.com/quote/Q{i}"} for i in range(2)}}
        for index, cycle in enumerate(forged.values()):
            document["options"][f"F{index}.ST"] = {"monthly": {**cycle, "ticker": f"F{index}.ST"}}
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "market_quotes_options.json"
            path.write_text(json.dumps(document), encoding="utf-8")
            with mock.patch.object(gate, "load_public_option_policy", return_value=policy):
                bodies = publisher.lazy_market_bodies(path, cases.SEAL_AT)
        sealed = json.loads(bodies["v213:options:v2"])["options"]
        for index, name in enumerate(forged):
            row = sealed[f"F{index}.ST"]["monthly"]
            self.assertEqual(list(row), ["unavailable"], name)  # refused by the validator or the rights gate: never a quote
            self.assertNotIn("suggestions", row, name)
        for name, cycle in forged.items():  # the rights gate alone (identity join) also refuses every one of them
            self.assertEqual(gate.public_option_cycle_admission(cycle, policy), DENIED, name)
        # A Nordic cycle that claims the Yahoo identity (or the reverse) matches no scope of ITS provider's market; the Python gate judges the claimed
        # identity only, the Worker loader's market/currency/jurisdiction coherence refuses it (cloud/test/v13-nordic-options-operator-accepted.test.ts).
        self.assertEqual(gate.public_option_cycle_admission({**base, "provider_id": support.YAHOO_ID, "jurisdiction": "SE"}, policy), DENIED)
        self.assertEqual(gate.public_option_cycle_admission({**base, "provider_id": support.NORDIC_ID, "jurisdiction": "US"}, policy), DENIED)

    def test_the_committed_worker_fixture_is_byte_for_byte_the_real_producer_and_sealer_output(self) -> None:
        with tempfile.TemporaryDirectory(prefix="v13_fixture_verify_") as folder:
            target = Path(folder) / "fixture.json"
            cases.write_fixture(target)
            self.assertEqual(cases.FIXTURE_PATH.read_bytes(), target.read_bytes())
        self.assertNotIn(b"\r", cases.FIXTURE_PATH.read_bytes())


def cases_policy_without_nordic():
    """The policy of a catalog on which Nordic was reverted (both flags off) while Yahoo stays enabled."""
    document = both_document()
    for field in ("runtime_enabled", "line_quote_eligible"):
        provider_of(document, support.NORDIC_ID)[field] = False
    with support.catalog_root(document) as root:
        return gate.load_public_option_policy(root, today=TODAY)


if __name__ == "__main__":
    unittest.main()
