"""V19 A1: the operator-accepted (unlicensed) Nasdaq US option chain (the Yahoo fallback), a third pinned provider beside Yahoo and Nasdaq Nordic.

Every row runs against a throw-away root whose catalog carries the test copies of the pinned entries (tests/fixtures/v11_operator_accepted_options.py);
a parity test compares the Nasdaq US copy with the repository catalog. Positive rows, the pins (id, decision, scopes), forged and mismatched claims, the
revert, the freshness guard, the transport failures, the carry-forward exclusion, the KV key set, and the real producer -> real sealer chain
(tests/fixtures/v19_nasdaq_us_options_cases.py). No network.
"""
from __future__ import annotations

import copy
import io
import json
import sys
import tempfile
import unittest
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import build_market_quotes_options as builder  # noqa: E402
import options_carry_forward as carry  # noqa: E402
import public_options_provider_gate as gate  # noqa: E402
import publish_sealed_snapshot as publisher  # noqa: E402
from tests.fixtures import options_nonus_publisher_cases as nonus  # noqa: E402
from tests.fixtures import v11_operator_accepted_options as support  # noqa: E402
from tests.fixtures import v19_nasdaq_us_options_cases as cases  # noqa: E402

TODAY = support.NASDAQ_TODAY
NASDAQ_CLAIM = {**support.NASDAQ_IDENTITY, "quote_basis": "delayed"}
YAHOO_CLAIM = {**support.IDENTITY, "quote_basis": "delayed"}
NORDIC_CLAIM = {**support.NORDIC_IDENTITY, "quote_basis": "delayed"}
ALL = sorted([support.NASDAQ_ID, support.NORDIC_ID, support.YAHOO_ID])
DENIED = gate.OPTION_RIGHTS_NOT_ADMITTED


def all_document() -> dict:
    return support.catalog_document(with_nordic=True, with_nasdaq=True)


def provider_of(document: dict, provider_id: str) -> dict:
    return next(item for item in document["providers"] if item["id"] == provider_id)


def audit(document: dict, root: Path, today: date = TODAY):
    support.write_catalog(root, document)
    return gate.audit_public_options_providers(root, today=today)


def policy_of(document: dict, root: Path, today: date = TODAY):
    support.write_catalog(root, document)
    return gate.load_public_option_policy(root, today=today)


def last_trade_text(day: date) -> str:
    return cases.last_trade(day)


class NasdaqPositiveTests(unittest.TestCase):
    def test_all_three_pinned_entries_pass_the_audit_and_are_the_only_eligible_providers(self) -> None:
        with support.catalog_root(all_document()) as root:
            findings, summary = gate.audit_public_options_providers(root, today=TODAY)
        self.assertEqual(findings, [])
        self.assertEqual(summary["fully_eligible_provider_ids"], ALL)
        self.assertEqual((summary["fully_eligible_count"], summary["operator_accepted_count"], summary["runtime_enabled_count"]), (3, 3, 3))
        self.assertEqual(summary["automation_prohibited_count"], 4)

    def test_policy_admits_exactly_the_nasdaq_us_scope_and_nothing_else(self) -> None:
        policy = support.all_policy()
        self.assertEqual(policy.provider_ids(), ALL)
        for claim in (NASDAQ_CLAIM, YAHOO_CLAIM, NORDIC_CLAIM):
            self.assertIsNone(gate.public_option_cycle_admission(claim, policy), claim["provider_id"])
        for field, value in (("quote_basis", "previous_session_last"), ("quote_basis", "realtime"), ("quote_basis", "asof_close"),
                             ("jurisdiction", "SE"), ("jurisdiction", "NO"), ("venue", "NASDAQ_STOCKHOLM_OPTIONS"), ("venue", "US_LISTED_OPTIONS "),
                             ("instrument_kind", "eod_index"), ("publication_scope", "local_research"),
                             ("provider_id", "nasdaq_public_option_chain "), ("provider_id", " nasdaq_public_option_chain"),
                             ("provider_id", "nyse_options_reference"), ("provider_id", "nasdaq_us_option_chain")):
            self.assertEqual(gate.public_option_cycle_admission({**NASDAQ_CLAIM, field: value}, policy), DENIED, (field, value))
        for field in NASDAQ_CLAIM:
            self.assertEqual(gate.public_option_cycle_admission({k: v for k, v in NASDAQ_CLAIM.items() if k != field}, policy), DENIED, field)
            self.assertEqual(gate.public_option_cycle_admission({**NASDAQ_CLAIM, field: None}, policy), DENIED, field)
        # the carried basis belongs to Yahoo alone
        self.assertEqual(gate.public_option_cycle_admission({**NASDAQ_CLAIM, "quote_basis": "previous_session_last"}, policy), DENIED)
        # a label, source text or a caller flag never admits
        self.assertEqual(gate.public_option_cycle_admission(
            {"rights_status": "operator_accepted_unlicensed", "source": builder_source(), "quote_basis": "delayed"}, policy), DENIED)

    def test_the_identities_never_cross(self) -> None:
        policy = support.all_policy()
        mixes = (
            {**NASDAQ_CLAIM, "provider_id": support.YAHOO_ID, "quote_basis": "previous_session_last"},  # Yahoo's carried basis is Yahoo's own
            {**NASDAQ_CLAIM, "provider_id": support.NORDIC_ID},
            {**NORDIC_CLAIM, "provider_id": support.NASDAQ_ID},
            {**YAHOO_CLAIM, "provider_id": support.NORDIC_ID},
        )
        self.assertIsNone(gate.public_option_cycle_admission(mixes[0], policy))
        for claim in mixes[1:]:
            self.assertEqual(gate.public_option_cycle_admission(claim, policy), DENIED, claim)

    def test_the_builder_claims_exactly_the_catalog_identity_and_the_others_are_unchanged(self) -> None:
        self.assertEqual(builder.NASDAQ_US_OPTION_IDENTITY, support.NASDAQ_IDENTITY)
        self.assertEqual(builder.NASDAQ_US_RIGHTS_LABEL, "operator_accepted_unlicensed")
        self.assertEqual(builder.YAHOO_OPTION_IDENTITY, support.IDENTITY)
        self.assertEqual(builder.NORDIC_OPTION_IDENTITY, support.NORDIC_IDENTITY)
        self.assertEqual(builder.NASDAQ_US_MAX_ASOF_AGE_DAYS, 4)
        scopes = {(item["jurisdiction"], item["venue"], item["instrument_kind"], item["quote_basis"], item["publication_scope"])
                  for item in support.NASDAQ_ENTRY["admitted_scopes"]}
        self.assertEqual(scopes, gate.OPERATOR_ACCEPTED_PROVIDERS[support.NASDAQ_ID]["scopes"])
        self.assertEqual(scopes, {("US", "US_LISTED_OPTIONS", "equity_option", "delayed", "public_line_quote")})  # delayed only: no carry-forward
        self.assertEqual(gate.OPERATOR_ACCEPTED_PROVIDERS[support.NASDAQ_ID]["operator_decision"],
                         {"decision_id": support.NASDAQ_DECISION_ID, "decided_at": "2026-10-19", "record": "docs/PUBLIC_OPTIONS_PROVIDER_RIGHTS_REVIEW.md"})
        self.assertEqual(sorted(gate.OPERATOR_ACCEPTED_PROVIDERS), ALL)  # exactly these three

    def test_the_repository_catalog_entry_equals_the_pinned_copy(self) -> None:
        repository = json.loads((ROOT / "config" / "public-options-provider-candidates.json").read_text(encoding="utf-8"))
        found = [item for item in repository["providers"] if item["id"] == support.NASDAQ_ID]
        self.assertEqual(len(found), 1)
        strip = lambda entry: {key: value for key, value in entry.items() if key not in ("name", "review_notes")}  # noqa: E731
        self.assertEqual(strip(found[0]), strip(support.NASDAQ_ENTRY))
        self.assertIn("NOT a rights review and NOT a licence", found[0]["review_notes"])
        self.assertIn(support.NASDAQ_DECISION_ID, found[0]["review_notes"])
        self.assertIn("Revert: set runtime_enabled and line_quote_eligible to false together", found[0]["review_notes"])
        self.assertEqual(strip(provider_of(repository, support.YAHOO_ID)), strip(support.YAHOO_ENTRY))
        self.assertEqual(strip(provider_of(repository, support.NORDIC_ID)), strip(support.NORDIC_ENTRY))
        findings, summary = gate.audit_public_options_providers(ROOT, today=TODAY)
        self.assertEqual(findings, [])
        self.assertEqual(summary["fully_eligible_provider_ids"], ALL)

    def test_the_worker_constants_mirror_the_python_pins_and_the_label_matches_the_nordic_one(self) -> None:
        source = (ROOT / "cloud" / "src" / "v213" / "public-options-admission.ts").read_text(encoding="utf-8")
        pinned = gate.OPERATOR_ACCEPTED_PROVIDERS[support.NASDAQ_ID]
        self.assertIn("nasdaq_public_option_chain: {", source)
        for value in pinned["operator_decision"].values():
            self.assertIn(f'"{value}"', source)
        for scope in pinned["scopes"]:
            self.assertIn("JSON.stringify([" + ", ".join(f'"{part}"' for part in scope) + "])", source)
        labels = (ROOT / "cloud" / "src" / "v213" / "source-labels.ts").read_text(encoding="utf-8")
        self.assertIn('"Nasdaq 美股期權鏈（公開報價頁 API，非官方授權，延遲；Yahoo 備援）"', labels)
        self.assertIn(f'"{builder_source()}"', labels)
        self.assertIn("非官方授權", labels.split(f'"{builder.NORDIC_SOURCE}"')[1].splitlines()[0])


def builder_source() -> str:
    return "Nasdaq US option chain (public quote page API, delayed; Yahoo fallback)"


class NasdaqPinTests(unittest.TestCase):
    def test_a_forged_or_altered_nasdaq_entry_makes_the_whole_catalog_unusable(self) -> None:
        mutations = {
            "decision id": lambda p: p["operator_decision"].__setitem__("decision_id", "OPERATOR-DECISION-SOMETHING-ELSE"),
            "decision id of the Nordic decision": lambda p: p["operator_decision"].__setitem__("decision_id", support.NORDIC_DECISION_ID),
            "decision date": lambda p: p["operator_decision"].__setitem__("decided_at", "2026-10-17"),
            "decision record": lambda p: p["operator_decision"].__setitem__("record", "docs/README.md"),
            "extra decision key": lambda p: p["operator_decision"].__setitem__("approved_by", "someone"),
            "decision removed": lambda p: p.pop("operator_decision"),
            "review date": lambda p: p.__setitem__("rights_reviewed_at", "2026-10-18"),
            "claims automation": lambda p: p.__setitem__("automated_access_allowed", True),
            "claims prohibition": lambda p: p.__setitem__("automated_access_allowed", False),
            "no adapter": lambda p: p.__setitem__("adapter_status", "not_implemented"),
            "foreign venue scope": lambda p: p["admitted_scopes"][0].__setitem__("venue", "OTHERVENUE"),
            "nordic venue scope": lambda p: p["admitted_scopes"][0].__setitem__("venue", "NASDAQ_STOCKHOLM_OPTIONS"),
            "foreign basis scope": lambda p: p["admitted_scopes"][0].__setitem__("quote_basis", "realtime"),
            "carried basis scope": lambda p: p["admitted_scopes"].append({**p["admitted_scopes"][0], "quote_basis": "previous_session_last"}),
            "scope outside the pin": lambda p: p["admitted_scopes"].append({**p["admitted_scopes"][0], "venue": "US_LISTED_OPTIONS_EXTRA"}),
            "extra scope of another jurisdiction": lambda p: (p["jurisdictions"].append("SE"), p["admitted_scopes"].append(
                {**p["admitted_scopes"][0], "jurisdiction": "SE", "venue": "NASDAQ_STOCKHOLM_OPTIONS"})),
            "no scopes": lambda p: p.__setitem__("admitted_scopes", []),
            "reviewed status without review": lambda p: p.__setitem__("rights_status", "reviewed_public_access"),
            "padded id": lambda p: p.__setitem__("id", "nasdaq_public_option_chain "),
            "window closed": lambda p: p.__setitem__("review_valid_through", "2026-10-18"),
            "window before the decision": lambda p: p.__setitem__("review_valid_through", "2026-10-16"),
        }
        with support.catalog_root(all_document()) as root:
            for name, mutate in mutations.items():
                with self.subTest(name):
                    document = all_document()
                    mutate(provider_of(document, support.NASDAQ_ID))
                    document["production_quote_provider_selected"] = True
                    findings, _ = audit(document, root)
                    self.assertTrue(findings, name)
                    policy = policy_of(document, root)
                    self.assertEqual(policy.provider_ids(), [], name)  # the others are refused with it: one malformed provider voids the catalog
                    for claim in (NASDAQ_CLAIM, YAHOO_CLAIM, NORDIC_CLAIM):
                        self.assertEqual(gate.public_option_cycle_admission(claim, policy), DENIED, (name, claim["provider_id"]))

    def test_a_duplicate_of_the_pinned_id_or_another_provider_claiming_the_status_is_refused(self) -> None:
        with support.catalog_root(all_document()) as root:
            document = all_document()
            document["providers"].append(copy.deepcopy(support.NASDAQ_ENTRY))  # a duplicate of the pinned id
            findings, _ = audit(document, root)
            self.assertTrue(findings, findings)
            self.assertEqual(policy_of(document, root).provider_ids(), [])
            base = all_document()
            others = [item["id"] for item in base["providers"] if item["id"] not in ALL]
            self.assertGreaterEqual(len(others), 10)
            for provider_id in others:
                with self.subTest(provider=provider_id):
                    document = copy.deepcopy(base)
                    forged = provider_of(document, provider_id)
                    forged.update({key: copy.deepcopy(support.NASDAQ_ENTRY[key]) for key in (
                        "rights_status", "automated_access_allowed", "rights_reviewed_at", "adapter_status", "runtime_enabled",
                        "line_quote_eligible", "review_valid_through", "admitted_scopes", "operator_decision")})
                    findings, _ = audit(document, root)
                    self.assertTrue(any("accepted only for the pinned operator decisions" in item for item in findings), findings)
                    self.assertEqual(policy_of(document, root).provider_ids(), [])

    def test_the_decisions_cannot_be_swapped_between_the_providers(self) -> None:
        with support.catalog_root(all_document()) as root:
            document = all_document()  # Yahoo carrying the Nasdaq US decision
            provider_of(document, support.YAHOO_ID).update(
                operator_decision=copy.deepcopy(support.NASDAQ_ENTRY["operator_decision"]), rights_reviewed_at="2026-10-19")
            findings, _ = audit(document, root)
            self.assertTrue(any("operator_decision must equal the pinned operator decision" in item for item in findings), findings)
            document = all_document()  # Nasdaq US carrying the Yahoo decision
            provider_of(document, support.NASDAQ_ID).update(
                operator_decision=copy.deepcopy(support.YAHOO_ENTRY["operator_decision"]), rights_reviewed_at="2026-10-13")
            findings, _ = audit(document, root)
            self.assertTrue(any("operator_decision must equal the pinned operator decision" in item for item in findings), findings)
            document = all_document()  # Nasdaq US row carrying the Yahoo scopes (adds the carried basis)
            provider_of(document, support.NASDAQ_ID)["admitted_scopes"] = copy.deepcopy(support.YAHOO_ENTRY["admitted_scopes"])
            findings, _ = audit(document, root)
            self.assertTrue(any("admitted_scopes must be a subset" in item for item in findings), findings)

    def test_the_four_pinned_prohibitions_stay_rejected(self) -> None:
        policy = support.all_policy()
        for provider_id in ("cboe_public_options_market_data", "occ_public_market_data", "marketdata_app_free_forever", "tradier_broker_market_data_api",
                            "taifex_public_options", "nyse_options_reference"):
            self.assertIsNone(policy.provider(provider_id), provider_id)
            self.assertEqual(gate.public_option_cycle_admission({**NASDAQ_CLAIM, "provider_id": provider_id}, policy), DENIED)

    def test_the_catalog_row_without_the_pin_is_refused(self) -> None:
        """Catalog row present, Python pin missing: the whole catalog is unusable (the Worker twin is in the Vitest file)."""
        with support.catalog_root(all_document()) as root:
            support.write_catalog(root, all_document())
            pins = {key: value for key, value in gate.OPERATOR_ACCEPTED_PROVIDERS.items() if key != support.NASDAQ_ID}
            with mock.patch.object(gate, "OPERATOR_ACCEPTED_PROVIDERS", pins):
                findings, _ = gate.audit_public_options_providers(root, today=TODAY)
                self.assertTrue(findings)
                policy = gate.load_public_option_policy(root, today=TODAY)
            self.assertEqual(policy.provider_ids(), [])
            for claim in (NASDAQ_CLAIM, YAHOO_CLAIM, NORDIC_CLAIM):
                self.assertEqual(gate.public_option_cycle_admission(claim, policy), DENIED)


class NasdaqRevertAndWindowTests(unittest.TestCase):
    def test_reverting_nasdaq_alone_changes_nothing_else(self) -> None:
        with support.catalog_root(all_document()) as root:
            document = all_document()
            for field in ("runtime_enabled", "line_quote_eligible"):  # the documented revert: both flags off together
                provider_of(document, support.NASDAQ_ID)[field] = False
            findings, summary = audit(document, root)
            self.assertEqual(findings, [])
            self.assertEqual(summary["fully_eligible_provider_ids"], sorted([support.NORDIC_ID, support.YAHOO_ID]))
            policy = policy_of(document, root)
            self.assertEqual(gate.public_option_cycle_admission(NASDAQ_CLAIM, policy), DENIED)
            self.assertIsNone(gate.public_option_cycle_admission(YAHOO_CLAIM, policy))
            self.assertIsNone(gate.public_option_cycle_admission(NORDIC_CLAIM, policy))

    def test_a_partial_revert_is_refused_and_a_full_revert_admits_nothing(self) -> None:
        with support.catalog_root(all_document()) as root:
            document = all_document()
            provider_of(document, support.NASDAQ_ID)["line_quote_eligible"] = False
            findings, _ = audit(document, root)
            self.assertTrue(any("must change atomically" in item for item in findings), findings)
            document = all_document()
            for provider_id in ALL:
                for field in ("runtime_enabled", "line_quote_eligible"):
                    provider_of(document, provider_id)[field] = False
            document["production_quote_provider_selected"] = False
            findings, summary = audit(document, root)
            self.assertEqual(findings, [])
            self.assertEqual(summary["fully_eligible_count"], 0)
            self.assertEqual(policy_of(document, root).provider_ids(), [])

    def test_the_review_window_closes_on_its_own_date(self) -> None:
        with support.catalog_root(all_document()) as root:
            support.write_catalog(root, all_document())
            self.assertEqual(gate.load_public_option_policy(root, today=date(2026, 10, 19)).provider_ids(), ALL)                    # the decision day
            self.assertEqual(gate.load_public_option_policy(root, today=date(2026, 10, 18)).provider_ids(), sorted([support.NORDIC_ID, support.YAHOO_ID]))  # before: no Nasdaq US
            self.assertEqual(gate.load_public_option_policy(root, today=date(2027, 10, 13)).provider_ids(), ALL)                    # last Yahoo day
            self.assertEqual(gate.load_public_option_policy(root, today=date(2027, 10, 14)).provider_ids(), [])                     # Yahoo window closed
            document = all_document()
            for provider_id in (support.YAHOO_ID, support.NORDIC_ID):
                provider_of(document, provider_id)["review_valid_through"] = "2028-10-13"
            support.write_catalog(root, document)
            self.assertEqual(gate.load_public_option_policy(root, today=date(2027, 10, 19)).provider_ids(), ALL)                    # Nasdaq US last day
            self.assertEqual(gate.load_public_option_policy(root, today=date(2027, 10, 20)).provider_ids(), [])


class NasdaqProducerSealerTests(unittest.TestCase):
    """The real producer CLI and the real sealer (no admission seam): the fallback cycles are admitted only under the catalog that carries Nasdaq US."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.allowed = cases.produce_and_seal(support.all_policy())
        cls.without = cases.produce_and_seal(support.both_policy(support.NASDAQ_TODAY))  # Yahoo + Nordic only: the Nasdaq US row is unadmitted
        cls.reverted = cases.produce_and_seal(policy_without_nasdaq())

    def test_producer_fallback_cycles_claim_the_nasdaq_us_identity_with_the_delayed_basis(self) -> None:
        for period in ("weekly", "monthly"):
            cycle = self.allowed["options"][cases.NASDAQ_TICKER][period]
            self.assertNotIn("unavailable", cycle, period)
            self.assertEqual({key: cycle[key] for key in support.NASDAQ_IDENTITY}, support.NASDAQ_IDENTITY)
            self.assertEqual((cycle["quote_basis"], cycle["currency"], cycle["rights_status"]), ("delayed", "USD", "operator_accepted_unlicensed"))
            self.assertEqual(cycle["source"], builder_source())
        sibling = self.allowed["options"][cases.US_SIBLING]["monthly"]  # Yahoo cycles unchanged: the Yahoo identity
        self.assertEqual({key: sibling[key] for key in support.IDENTITY}, support.IDENTITY)

    def test_without_the_nasdaq_us_entry_the_fallback_cycles_are_refused_and_yahoo_is_unchanged(self) -> None:
        for sealed in (self.without, self.reverted):
            for period in ("weekly", "monthly"):
                self.assertEqual(sealed["options"][cases.NASDAQ_TICKER][period], {"unavailable": gate.OPTION_RIGHTS_UNAVAILABLE_ZH}, period)
            self.assertEqual(sealed["options"][cases.US_SIBLING]["monthly"], self.allowed["options"][cases.US_SIBLING]["monthly"])

    def test_a_forged_claim_is_refused_by_the_real_sealer(self) -> None:
        base = self.allowed["options"][cases.NASDAQ_TICKER]["monthly"]
        forged = {"carried basis": {**base, "quote_basis": "previous_session_last"},
                  "foreign venue": {**base, "venue": "STOCKHOLM"},
                  "foreign provider": {**base, "provider_id": "nyse_options_reference"},
                  "padded provider": {**base, "provider_id": "nasdaq_public_option_chain "},
                  "no identity": {key: value for key, value in base.items() if key != "provider_id"}}
        policy = support.all_policy()
        document = {"schema": "v213-market-observations-v2", "generated_at": base["timestamp"], "options": {}, "quotes": {
            f"Q{i}": {"symbol": f"Q{i}", "price": 100.0, "previous_close": 99.0, "change_pct": 0.01, "currency": "USD", "asof": base["timestamp"],
                      "source": "Yahoo Finance (unofficial, delayed)", "source_url": f"https://finance.yahoo.com/quote/Q{i}"} for i in range(2)}}
        for index, cycle in enumerate(forged.values()):
            document["options"][f"F{index}"] = {"monthly": {**cycle, "ticker": f"F{index}"}}
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "market_quotes_options.json"
            path.write_text(json.dumps(document), encoding="utf-8")
            with mock.patch.object(gate, "load_public_option_policy", return_value=policy):
                bodies = publisher.lazy_market_bodies(path, cases.SEAL_AT)
        sealed = json.loads(bodies["v213:options:v2"])["options"]
        for index, name in enumerate(forged):
            row = sealed[f"F{index}"]["monthly"]
            self.assertEqual(list(row), ["unavailable"], name)  # refused by the validator or the rights gate: never a quote
        for name, cycle in forged.items():
            self.assertEqual(gate.public_option_cycle_admission(cycle, policy), DENIED, name)

    def test_the_sealed_object_key_set_is_unchanged_by_the_fallback(self) -> None:
        """Zero new KV keys: a run in which Yahoo fails for one ticker seals the same objects and the same top-level shape as an all-Yahoo run."""
        with tempfile.TemporaryDirectory(prefix="v19_keys_") as folder:
            fallback_bodies = self.seal_bodies(cases.specs(), Path(folder) / "a")
            yahoo_bodies = self.seal_bodies(nonus.healthy_us(11), Path(folder) / "b")
        self.assertEqual(sorted(fallback_bodies), sorted(yahoo_bodies))
        self.assertEqual(sorted(fallback_bodies), ["v213:options:v2", "v213:quotes:v1"])
        fallback = json.loads(fallback_bodies["v213:options:v2"])
        yahoo = json.loads(yahoo_bodies["v213:options:v2"])
        self.assertEqual(sorted(fallback), sorted(yahoo))
        self.assertEqual(len(fallback["options"]), len(yahoo["options"]))  # one ticker entry per underlying either way: no extra object
        self.assertEqual(sorted(json.loads(fallback_bodies["v213:quotes:v1"])), sorted(json.loads(yahoo_bodies["v213:quotes:v1"])))

    @staticmethod
    def seal_bodies(spec_list: list, directory: Path) -> dict:
        directory.mkdir(parents=True, exist_ok=True)
        rc, output = cases.run_producer(spec_list, directory)
        assert rc == 0, rc
        with mock.patch.object(gate, "load_public_option_policy", return_value=support.all_policy()):
            return publisher.lazy_market_bodies(output, cases.SEAL_AT)

    def test_the_committed_worker_fixture_is_byte_for_byte_the_real_producer_and_sealer_output(self) -> None:
        with tempfile.TemporaryDirectory(prefix="v19_fixture_verify_") as folder:
            target = Path(folder) / "fixture.json"
            cases.write_fixture(target)
            self.assertEqual(cases.FIXTURE_PATH.read_bytes(), target.read_bytes())
        self.assertNotIn(b"\r", cases.FIXTURE_PATH.read_bytes())


def policy_without_nasdaq():
    """The policy of a catalog on which Nasdaq US was reverted (both flags off) while Yahoo and Nordic stay enabled."""
    document = all_document()
    for field in ("runtime_enabled", "line_quote_eligible"):
        provider_of(document, support.NASDAQ_ID)[field] = False
    with support.catalog_root(document) as root:
        return gate.load_public_option_policy(root, today=TODAY)


class NasdaqFreshnessAndTransportTests(unittest.TestCase):
    """nasdaq_us_options itself, with only the transport replaced: the as-of guard and the fail-closed read states."""

    STAMP = "2026-10-19T14:00:00Z"
    RUN_DATE = cases.WORLD_TODAY

    def setUp(self) -> None:
        self.saved = builder.http_json

    def tearDown(self) -> None:
        builder.http_json = self.saved

    def payload(self, last_trade):
        data = {"table": {"rows": cases.nasdaq_rows()}}
        if last_trade is not None:
            data["lastTrade"] = last_trade
        return {"data": data}

    def run_with(self, last_trade):
        builder.http_json = lambda url: self.payload(last_trade)
        return builder.nasdaq_us_options("SYNTHNQ00", 100.0, self.RUN_DATE, self.STAMP)

    def assert_stale(self, out) -> None:
        for cycle in builder.CYCLES:
            self.assertEqual(out[cycle], {"unavailable": "Nasdaq 報價日期過舊或無法確認"}, cycle)
        self.assertEqual({item["status"] for item in out.health}, {"STALE_ASOF"})
        self.assertTrue(all(item["read"] is False and item["two_sided"] is False for item in out.health))

    def test_a_fresh_as_of_date_is_shown(self) -> None:
        for age in (0, 1, 3, 4):  # the edge: four calendar days still passes (weekend plus a holiday)
            out = self.run_with(last_trade_text(self.RUN_DATE - timedelta(days=age)))
            for cycle in builder.CYCLES:
                self.assertNotIn("unavailable", out[cycle], (age, cycle))
                self.assertEqual({k: out[cycle][k] for k in support.NASDAQ_IDENTITY}, support.NASDAQ_IDENTITY)
            self.assertEqual({item["status"] for item in out.health}, {"READ"}, age)

    def test_a_five_day_old_date_is_stale(self) -> None:
        self.assert_stale(self.run_with(last_trade_text(self.RUN_DATE - timedelta(days=5))))

    def test_a_missing_or_garbled_date_is_stale(self) -> None:
        for text in (None, "", "LAST TRADE: $343.46", "LAST TRADE: $343.46 (AS OF)", "LAST TRADE: $343.46 (AS OF FOO 15, 2026)",
                     "LAST TRADE: $343.46 (AS OF OCT 32, 2026)", "LAST TRADE: $343.46 (AS OF 2026-10-19)", 12345, ["AS OF OCT 19, 2026"],
                     "LAST TRADE: $343.46 (AS OF OCTOPUS 19, 2026)", "LAST TRADE: $343.46 (AS OF OCT 19, 20260)",
                     "LAST TRADE: $343.46 (AS OF OCTO 19, 2026)", "LAST TRADE: $343.46 (AS OF FEB 30, 2026)",
                     "LAST TRADE: $343.46 (AS OF OCT 19, 2026JUNK)", "LAST TRADE: $343.46 (AS OF OCT 19, 2026_0)",
                     "LAST TRADE: $343.46 (AS OF OCT 19, 2026-10)", "LAST TRADE: $343.46 (AS OF OCT 19, 2026.5)"):
            with self.subTest(text=text):
                self.assert_stale(self.run_with(text))

    def test_future_as_of_dates_are_refused(self) -> None:
        for days in (1, 365):
            with self.subTest(future_days=days):
                self.assert_stale(self.run_with(last_trade_text(self.RUN_DATE + timedelta(days=days))))

    def test_actual_producer_and_publisher_preserve_as_of_boundaries(self) -> None:
        for age in (0, 4, 5, -1, -365):
            with self.subTest(age_days=age):
                document = cases.produce_and_seal(support.all_policy(), cases.specs({
                    "nasdaq_last_trade": last_trade_text(self.RUN_DATE - timedelta(days=age)),
                }))
                for period in builder.CYCLES:
                    cycle = document["options"][cases.NASDAQ_TICKER][period]
                    if 0 <= age <= 4:
                        self.assertNotIn("unavailable", cycle, (age, period))
                        self.assertEqual(cycle["provider_id"], support.NASDAQ_ID)
                    else:
                        self.assertEqual(cycle, {"unavailable": builder.NASDAQ_US_STALE_TEXT}, (age, period))
                    # Refusing Nasdaq cannot contaminate a healthy Yahoo sibling.
                    self.assertEqual(document["options"]["SYNTHUS00"][period]["provider_id"], support.YAHOO_ID)

    def test_actual_producer_and_publisher_refuse_malformed_month_and_year_tokens(self) -> None:
        # R/ASTRA-V23-INDEPENDENT-ACCEPT-CLAUDECODE-a43bef58.txt M1: a month is a whole month name or abbreviation and a year exactly four digits;
        # a garbled token is "date unconfirmed" through the real producer and compact publisher, never the date its first letters spell.
        # R2 (R/ASTRA-V23-INDEPENDENT-ACCEPT-R2-CLAUDECODE-a43bef58.txt M1-R2): the year token ends at ")" or whitespace, so a letter,
        # underscore or other continuation after four digits is garbled too.
        day = self.RUN_DATE
        abbr, full = day.strftime("%b").upper(), day.strftime("%B").upper()
        refused = (f"{abbr}OPUS {day.day}, {day.year}", f"{abbr} {day.day}, {day.year}0", f"{abbr} {day.day}, {day.year}1", f"{abbr}X {day.day}, {day.year}",
                   f"{abbr} {day.day}, {day.year}JUNK", f"{abbr} {day.day}, {day.year}_0", f"{abbr} {day.day}, {day.year}-10",
                   f"{abbr} {day.day}, {day.year}.5")
        admitted = (f"{full} {day.day}, {day.year}", f"{abbr}. {day.day}, {day.year}", f"{abbr.title()} {day.day} {day.year}",
                    f"{abbr} {day.day}, {day.year} 16:00 ET")
        for token in refused + admitted:
            with self.subTest(token=token):
                document = cases.produce_and_seal(support.all_policy(), cases.specs({
                    "nasdaq_last_trade": f"LAST TRADE: $343.46 (AS OF {token})",
                }))
                for period in builder.CYCLES:
                    cycle = document["options"][cases.NASDAQ_TICKER][period]
                    if token in admitted:
                        self.assertNotIn("unavailable", cycle, (token, period))
                        self.assertEqual(cycle["provider_id"], support.NASDAQ_ID)
                    else:
                        self.assertEqual(cycle, {"unavailable": builder.NASDAQ_US_STALE_TEXT}, (token, period))
                    self.assertEqual(document["options"]["SYNTHUS00"][period]["provider_id"], support.YAHOO_ID)

    def test_a_bot_challenge_or_non_json_body_is_a_read_error_never_a_quote(self) -> None:
        bodies = (b"<html><head><title>Access Denied</title></head><body>challenge</body></html>", b"", b"not json", b"\xff\xfe\x00")
        for body in bodies:
            with self.subTest(body=body[:20]):
                response = mock.MagicMock()
                response.__enter__.return_value = response
                response.read.side_effect = [body, b""]
                builder.http_json = self.saved
                with mock.patch("urllib.request.urlopen", return_value=response) as opened:
                    out = builder.nasdaq_us_options("SYNTHNQ00", 100.0, self.RUN_DATE, self.STAMP)
                self.assertEqual(opened.call_count, 1)  # no retry, no second route
                for cycle in builder.CYCLES:
                    self.assertEqual(out[cycle], {"unavailable": "Nasdaq 期權鏈讀取失敗"}, cycle)
                self.assertEqual({item["status"] for item in out.health}, {"READ_ERROR"})

    def test_a_json_body_of_the_wrong_shape_is_a_read_error(self) -> None:
        for payload in ({"status": {"rCode": 400}}, {"data": None}, {"data": {"table": None}}, [], "challenge"):
            with self.subTest(payload=payload):
                builder.http_json = lambda url, payload=payload: payload
                out = builder.nasdaq_us_options("SYNTHNQ00", 100.0, self.RUN_DATE, self.STAMP)
                self.assertEqual({item["status"] for item in out.health}, {"READ_ERROR"})

    def test_yahoo_stays_first_and_a_stale_fallback_never_replaces_a_read_yahoo_reason(self) -> None:
        calls: list[str] = []
        builder.http_json = lambda url: calls.append(url) or self.payload(None)
        with mock.patch.object(builder, "us_options", side_effect=OSError("yahoo down")):
            out = builder.us_cycles("SYNTHNQ00", 100.0, self.RUN_DATE, self.STAMP)
        self.assertEqual(len(calls), 1)  # asked once, no retry
        self.assertEqual(out["weekly"], {"unavailable": "期權鏈讀取失敗（Yahoo 與 Nasdaq 備援）"})
        calls.clear()
        good = {"ticker": "X", "expiry": "2026-10-23"}
        with mock.patch.object(builder, "us_options", return_value=builder.CyclesResult({"weekly": good, "monthly": good}, health=[])):
            builder.us_cycles("SYNTHNQ00", 100.0, self.RUN_DATE, self.STAMP)
        self.assertEqual(calls, [])  # Yahoo read every cycle: no Nasdaq request

    def test_the_fallback_cycle_is_never_captured_by_the_carry_forward(self) -> None:
        out = self.run_with(last_trade_text(self.RUN_DATE))
        in_session = datetime(2026, 10, 19, 15, 0, tzinfo=timezone.utc)
        for cycle in builder.CYCLES:
            self.assertEqual(out[cycle]["provider_id"], support.NASDAQ_ID)
        state = carry.CarryForward(Path(tempfile.gettempdir()) / "v19-unused-state.json", policy=support.all_policy())
        self.assertEqual(state.capture({"SYNTHNQ00": {"weekly": out["weekly"], "monthly": out["monthly"]}}, in_session), 0)
        self.assertEqual(state.cycles, {})
        self.assertEqual(carry.CARRIED_PROVIDER_ID, support.YAHOO_ID)


if __name__ == "__main__":
    unittest.main()
