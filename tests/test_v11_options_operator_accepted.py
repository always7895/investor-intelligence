"""V11 W1: the operator-accepted (unlicensed) Yahoo option provider, admitted THROUGH the catalog and admission machinery.

Every row runs against a throw-away root whose catalog carries the test copy of the pinned entry (tests/fixtures/v11_operator_accepted_options.py),
so the Python gate, the policy and the producer identity are proved without depending on the repository catalog edit; a parity test compares the
copy with the repository catalog when the entry is there. Positive rows, every other provider decision still rejected, forged status refused.
"""
from __future__ import annotations

import copy
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import build_market_quotes_options as builder  # noqa: E402
import public_options_provider_gate as gate  # noqa: E402
from tests.fixtures import v11_operator_accepted_options as support  # noqa: E402

CLAIM = {**support.IDENTITY, "quote_basis": "delayed"}


def audit(document: dict, root: Path):
    support.write_catalog(root, document)
    return gate.audit_public_options_providers(root, today=support.TODAY)


def provider_of(document: dict, provider_id: str) -> dict:
    return next(item for item in document["providers"] if item["id"] == provider_id)


class OperatorAcceptedPositiveTests(unittest.TestCase):
    def test_the_pinned_entry_passes_the_audit_and_is_the_only_eligible_provider(self) -> None:
        with support.catalog_root() as root:
            findings, summary = gate.audit_public_options_providers(root, today=support.TODAY)
        self.assertEqual(findings, [])
        self.assertEqual(summary["fully_eligible_provider_ids"], [support.YAHOO_ID])
        self.assertEqual((summary["fully_eligible_count"], summary["operator_accepted_count"], summary["runtime_enabled_count"]), (1, 1, 1))
        self.assertTrue(summary["production_provider_selected"])
        self.assertEqual(summary["automation_prohibited_count"], 4)  # the four pinned decisions are untouched

    def test_policy_admits_exactly_the_admitted_scopes_and_nothing_else(self) -> None:
        with support.catalog_root() as root:
            policy = gate.load_public_option_policy(root, today=support.TODAY)
        self.assertEqual(policy.provider_ids(), [support.YAHOO_ID])
        for basis in ("delayed", "previous_session_last"):
            self.assertIsNone(gate.public_option_cycle_admission({**CLAIM, "quote_basis": basis}, policy), basis)
        denied = gate.OPTION_RIGHTS_NOT_ADMITTED
        for field, value in (("provider_id", "cboe_public_options_market_data"), ("provider_id", "yahoo_finance_option_chain "), ("jurisdiction", "SE"),
                             ("venue", "NASDAQ_STOCKHOLM"), ("instrument_kind", "eod_index"), ("quote_basis", "realtime"),
                             ("quote_basis", "asof_close"), ("publication_scope", "local_research")):
            self.assertEqual(gate.public_option_cycle_admission({**CLAIM, field: value}, policy), denied, (field, value))
        for field in CLAIM:  # a missing or non-string claim is never guessed from labels
            self.assertEqual(gate.public_option_cycle_admission({k: v for k, v in CLAIM.items() if k != field}, policy), denied, field)
            self.assertEqual(gate.public_option_cycle_admission({**CLAIM, field: None}, policy), denied, field)
        # A label, source text or a caller flag never admits: only the claimed identity joins the catalog.
        self.assertEqual(gate.public_option_cycle_admission({"rights_status": "reviewed_public_access", "source": "Yahoo Finance option chain"}, policy), denied)

    def test_review_window_and_revert_both_fail_closed(self) -> None:
        with support.catalog_root() as root:
            self.assertEqual(gate.load_public_option_policy(root, today=support.TODAY).provider_ids(), [support.YAHOO_ID])
            self.assertEqual(gate.load_public_option_policy(root, today=support.TODAY.replace(year=2028)).provider_ids(), [])  # window closed
            document = support.catalog_document()
            for field in ("runtime_enabled", "line_quote_eligible"):  # the documented revert: both flags off together, root selection off
                provider_of(document, support.YAHOO_ID)[field] = False
            document["production_quote_provider_selected"] = False
            findings, summary = audit(document, root)
            self.assertEqual(findings, [])
            self.assertEqual(summary["fully_eligible_count"], 0)
            self.assertEqual(gate.load_public_option_policy(root, today=support.TODAY).provider_ids(), [])

    def test_the_builder_claims_exactly_the_catalog_identity(self) -> None:
        self.assertEqual(builder.YAHOO_OPTION_IDENTITY, support.IDENTITY)
        self.assertEqual(builder.YAHOO_RIGHTS_LABEL, "operator_accepted_unlicensed")
        scopes = {(item["jurisdiction"], item["venue"], item["instrument_kind"], item["quote_basis"], item["publication_scope"])
                  for item in support.YAHOO_ENTRY["admitted_scopes"]}
        self.assertEqual(scopes, gate.OPERATOR_ACCEPTED_PROVIDERS[support.YAHOO_ID]["scopes"])
        self.assertIn((CLAIM["jurisdiction"], CLAIM["venue"], CLAIM["instrument_kind"], "delayed", CLAIM["publication_scope"]), scopes)

    def test_the_repository_catalog_entry_equals_the_pinned_copy_when_it_is_present(self) -> None:
        repository = support.json.loads((ROOT / "config" / "public-options-provider-candidates.json").read_text(encoding="utf-8"))
        found = [item for item in repository["providers"] if item["id"] == support.YAHOO_ID]
        if not found:
            self.skipTest("the repository catalog does not carry the operator-accepted entry yet")
        entry = {key: value for key, value in found[0].items() if key not in ("name", "review_notes")}
        expected = {key: value for key, value in support.YAHOO_ENTRY.items() if key not in ("name", "review_notes")}
        self.assertEqual(entry, expected)
        self.assertTrue(repository["production_quote_provider_selected"])
        findings, summary = gate.audit_public_options_providers(ROOT)
        self.assertEqual(findings, [])
        self.assertEqual(summary["fully_eligible_provider_ids"], [support.YAHOO_ID])

    def test_the_worker_constants_mirror_the_python_pins(self) -> None:
        source = (ROOT / "cloud" / "src" / "v213" / "public-options-admission.ts").read_text(encoding="utf-8")
        pinned = gate.OPERATOR_ACCEPTED_PROVIDERS[support.YAHOO_ID]
        self.assertIn(f'yahoo_finance_option_chain: {{', source)
        for value in pinned["operator_decision"].values():
            self.assertIn(f'"{value}"', source)
        for scope in pinned["scopes"]:
            self.assertIn("JSON.stringify([" + ", ".join(f'"{part}"' for part in scope) + "])", source)
        self.assertIn(f'const OPERATOR_ACCEPTED_STATUS = "{gate.OPERATOR_ACCEPTED_STATUS}"', source)
        self.assertIn(f'new Set(["delayed", "{gate.CARRIED_QUOTE_BASIS}"])', source)
        self.assertEqual(gate.ALLOWED_QUOTE_BASES, {"delayed", "previous_session_last"})


class OperatorAcceptedRejectionTests(unittest.TestCase):
    def test_every_other_provider_decision_stays_rejected_even_with_the_status_forged_on(self) -> None:
        with support.catalog_root() as root:
            base = support.catalog_document()
            others = [item["id"] for item in base["providers"] if item["id"] != support.YAHOO_ID]
            self.assertGreaterEqual(len(others), 12)
            for provider_id in others:
                with self.subTest(provider=provider_id):
                    document = copy.deepcopy(base)
                    forged = provider_of(document, provider_id)
                    forged.update({key: copy.deepcopy(support.YAHOO_ENTRY[key]) for key in (
                        "rights_status", "automated_access_allowed", "rights_reviewed_at", "adapter_status", "runtime_enabled",
                        "line_quote_eligible", "review_valid_through", "admitted_scopes", "operator_decision")})
                    findings, _ = audit(document, root)
                    self.assertTrue(any("accepted only for the pinned operator decisions" in item for item in findings), findings)
                    self.assertEqual(gate.load_public_option_policy(root, today=support.TODAY).provider_ids(), [])  # the whole catalog is refused
                    claim = {**CLAIM, "provider_id": provider_id}
                    self.assertEqual(gate.public_option_cycle_admission(claim, gate.load_public_option_policy(root, today=support.TODAY)),
                                     gate.OPTION_RIGHTS_NOT_ADMITTED)

    def test_the_four_pinned_prohibitions_and_the_reviewed_taifex_rows_are_untouched(self) -> None:
        with support.catalog_root() as root:
            policy = gate.load_public_option_policy(root, today=support.TODAY)
        for provider_id in ("cboe_public_options_market_data", "occ_public_market_data", "marketdata_app_free_forever",
                            "tradier_broker_market_data_api", "taifex_public_options", "nasdaq_public_option_chain"):
            self.assertIsNone(policy.provider(provider_id), provider_id)
            self.assertEqual(gate.public_option_cycle_admission({**CLAIM, "provider_id": provider_id}, policy), gate.OPTION_RIGHTS_NOT_ADMITTED)

    def test_a_forged_or_altered_yahoo_entry_is_refused(self) -> None:
        mutations = {
            "decision id": lambda p: p["operator_decision"].__setitem__("decision_id", "OPERATOR-DECISION-SOMETHING-ELSE"),
            "decision date": lambda p: p["operator_decision"].__setitem__("decided_at", "2026-10-12"),
            "decision record": lambda p: p["operator_decision"].__setitem__("record", "docs/README.md"),
            "extra decision key": lambda p: p["operator_decision"].__setitem__("approved_by", "someone"),
            "decision removed": lambda p: p.pop("operator_decision"),
            "review date": lambda p: p.__setitem__("rights_reviewed_at", "2026-10-12"),
            "claims automation": lambda p: p.__setitem__("automated_access_allowed", True),
            "claims prohibition": lambda p: p.__setitem__("automated_access_allowed", False),
            "no adapter": lambda p: p.__setitem__("adapter_status", "not_implemented"),
            "foreign venue scope": lambda p: p["admitted_scopes"][0].__setitem__("venue", "OTHERVENUE"),
            "foreign basis scope": lambda p: p["admitted_scopes"][0].__setitem__("quote_basis", "realtime"),
            "scope outside the pin": lambda p: p["admitted_scopes"].append({**p["admitted_scopes"][0], "jurisdiction": "SE"}),
            "no scopes": lambda p: p.__setitem__("admitted_scopes", []),
            "reviewed status without review": lambda p: p.__setitem__("rights_status", "reviewed_public_access"),
        }
        with support.catalog_root() as root:
            for name, mutate in mutations.items():
                with self.subTest(name):
                    document = support.catalog_document()
                    mutate(provider_of(document, support.YAHOO_ID))
                    document["production_quote_provider_selected"] = True
                    findings, _ = audit(document, root)
                    self.assertTrue(findings, name)
                    self.assertEqual(gate.load_public_option_policy(root, today=support.TODAY).provider_ids(), [], name)

    def test_the_decision_field_is_valid_only_with_the_operator_status(self) -> None:
        with support.catalog_root() as root:
            document = support.catalog_document()
            provider_of(document, "taifex_public_options")["operator_decision"] = copy.deepcopy(support.YAHOO_ENTRY["operator_decision"])
            findings, _ = audit(document, root)
        self.assertTrue(any("operator_decision is allowed only with rights_status" in item for item in findings), findings)

    def test_root_selection_must_follow_the_eligible_set(self) -> None:
        with support.catalog_root() as root:
            document = support.catalog_document()
            document["production_quote_provider_selected"] = False
            findings, _ = audit(document, root)
            self.assertTrue(any("eligible provider requires explicit production_quote_provider_selected=true" in item for item in findings), findings)
            self.assertEqual(gate.load_public_option_policy(root, today=support.TODAY).provider_ids(), [])

    def test_an_operator_accepted_provider_never_enables_the_live_current_data_switch(self) -> None:
        with support.catalog_root() as root:
            wrangler = root / "cloud" / "wrangler.toml"
            wrangler.write_text(wrangler.read_text(encoding="utf-8").replace('CURRENT_PUBLIC_DATA_ENABLED = "false"',
                                                                             'CURRENT_PUBLIC_DATA_ENABLED = "true"'), encoding="utf-8")
            findings, _ = gate.audit_public_options_providers(root, today=support.TODAY)
        self.assertTrue(any("CURRENT_PUBLIC_DATA_ENABLED" in item for item in findings), findings)

    def test_partial_activation_of_the_operator_accepted_provider_is_refused(self) -> None:
        with support.catalog_root() as root:
            document = support.catalog_document()
            provider_of(document, support.YAHOO_ID)["line_quote_eligible"] = False
            findings, _ = audit(document, root)
        self.assertTrue(any("must change atomically" in item for item in findings), findings)


class SealerCallerTests(unittest.TestCase):
    """The real sealer (lazy_market_bodies) with the catalog policy: a Yahoo-identity cycle joins v213:options:v2, a cycle without a claimed
    identity (Nasdaq fallback, Stockholm) keeps the fixed unavailable reason."""

    def test_the_sealer_admits_the_claimed_identity_and_refuses_an_unclaimed_one(self) -> None:
        import json
        import tempfile
        from datetime import datetime, timezone

        import publish_sealed_snapshot as publisher

        def row(strike, bid, ask, delta):
            return {"strike": strike, "bid": bid, "ask": ask, "delta": delta, "iv": None, "oi": 10, "volume": 1}

        now = datetime(2026, 10, 13, 15, 5, tzinfo=timezone.utc)  # 11:05 New York, inside the regular session
        stamp = "2026-10-13T15:00:00Z"
        rows = [row(115, 0.9, 1.0, 0.1), row(105, 2.4, 2.5, 0.35)]
        live = builder.cycle_result("T00", "2026-11-13", 31, 100.0, rows, currency="USD", source="Yahoo Finance option chain (unofficial, delayed)",
                                    provenance="https://finance.yahoo.com/quote/T00/options?date=2026-11-13", rights=builder.YAHOO_RIGHTS_LABEL,
                                    stamp=stamp, asof="2026-10-13", identity=builder.YAHOO_OPTION_IDENTITY)
        unclaimed = builder.cycle_result("T01", "2026-11-13", 31, 100.0, rows, currency="USD", source="Nasdaq US option chain (fallback)",
                                         provenance="https://www.nasdaq.com/market-activity/stocks/t01/option-chain", rights="candidate_local_review",
                                         stamp=stamp, asof="2026-10-13")
        self.assertEqual({key: live[key] for key in support.IDENTITY}, support.IDENTITY)
        self.assertNotIn("provider_id", unclaimed)
        quotes = {f"T0{i}": {"symbol": f"T0{i}", "price": 100.0, "previous_close": 99.0, "change_pct": 0.01, "currency": "USD", "asof": stamp,
                             "source": "Yahoo Finance (unofficial, delayed)", "source_url": f"https://finance.yahoo.com/quote/T0{i}"} for i in range(2)}
        document = {"schema": "v213-market-observations-v2", "generated_at": stamp, "quotes": quotes,
                    "options": {"T00": {"monthly": live}, "T01": {"monthly": unclaimed}}}
        policy = support.yahoo_policy()
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "market_quotes_options.json"
            path.write_text(json.dumps(document), encoding="utf-8")
            with mock.patch.object(gate, "load_public_option_policy", return_value=policy):
                bodies = publisher.lazy_market_bodies(path, now)
            empty = publisher.lazy_market_bodies(path, now)  # the repository catalog as it is: no operator-accepted entry needed for the refusal below
        options = json.loads(bodies["v213:options:v2"])["options"]
        self.assertEqual(options["T00"]["monthly"]["provider_id"], support.YAHOO_ID)
        self.assertEqual(options["T00"]["monthly"]["quote_basis"], "delayed")
        self.assertEqual(options["T01"]["monthly"], {"unavailable": gate.OPTION_RIGHTS_UNAVAILABLE_ZH})
        self.assertEqual(json.loads(empty["v213:options:v2"])["options"]["T01"]["monthly"], {"unavailable": gate.OPTION_RIGHTS_UNAVAILABLE_ZH})


if __name__ == "__main__":
    unittest.main()
