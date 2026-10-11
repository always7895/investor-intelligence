"""G1A callers: the public, metadata-only global options SOURCE and GAP object (sealed lazy key v213:options-coverage:v1) built by
publish_sealed_snapshot.lazy_options_coverage_body, executed for real on the canonical catalog and on synthetic sealed options
bodies (no network, no subprocess, no write outside tempfile; the catalog and the ADR map are only read). The Worker side is
cloud/test/v213-options-coverage.test.ts.

The frozen clock is 2026-09-30T17:00:00Z, the instant of cloud/test/fixtures/options-nonus-publisher.json whose Python-produced
covered-call cycles (SYNTHUS00 and SYNTHUS01, weekly and monthly) are re-used here. No provider is admitted by the catalog; the
positive observed path admits ONE synthetic provider id inside a test through a patched policy (never in config)."""
from __future__ import annotations

import copy
import hashlib
import json
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import public_options_provider_gate as option_rights  # noqa: E402
import publish_sealed_snapshot as publisher  # noqa: E402
import validate_v213_market_products as products  # noqa: E402

NOW = datetime(2026, 9, 30, 17, 0, 0, tzinfo=timezone.utc)
CATALOG_PATH = ROOT / "config" / "public-options-provider-candidates.json"
ADR_MAP_PATH = ROOT / "config" / "option-adr-map-v1.json"
FIXTURE = json.loads((ROOT / "cloud" / "test" / "fixtures" / "options-nonus-publisher.json").read_text(encoding="utf-8"))
SYNTHETIC_ID = "synthetic_g1a_test_only"
SYNTHETIC_IDENTITY = {"provider_id": SYNTHETIC_ID, "jurisdiction": "US", "venue": "SYNTHVENUE", "instrument_kind": "equity_option",
                      "quote_basis": "delayed", "publication_scope": "public_line_quote"}
FORBIDDEN_KEYS = {"strike", "bid", "ask", "mid", "delta", "premium", "premium_per_contract", "limit_price", "settlement", "suggestions"}


def sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def fixture_document() -> dict:
    """The Python-produced options document of the dte_us_matrix case (generated_at == NOW), cycles untouched."""
    return json.loads(FIXTURE["cases"]["dte_us_matrix"]["bodies"]["options"])


def body_of(document) -> str:
    return json.dumps(document, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


def admitted_options_document(extra: dict | None = None) -> dict:
    """Two tickers x two periods of validated cycles, each carrying the synthetic provider identity; plus whatever `extra` adds."""
    source = fixture_document()["options"]
    options = {}
    for ticker in ("SYNTHUS00", "SYNTHUS01"):
        options[ticker] = {period: {**copy.deepcopy(source[ticker][period]), **SYNTHETIC_IDENTITY} for period in ("weekly", "monthly")}
    options.update(extra or {})
    return {"schema": "v213-options-v2", "generated_at": "2026-09-30T17:00:00Z", "options": options}


def synthetic_policy() -> option_rights.PublicOptionPolicy:
    scope = {key: SYNTHETIC_IDENTITY[key] for key in sorted(option_rights.SCOPE_KEYS)}
    return option_rights.PublicOptionPolicy({SYNTHETIC_ID: {"id": SYNTHETIC_ID, "admitted_scopes": [scope]}})


def build(options_body: str | None, now: datetime = NOW) -> dict:
    """The real builder; returns the parsed object or {} when it refuses."""
    produced = publisher.lazy_options_coverage_body(options_body, now)
    if not produced:
        return {}
    assert list(produced) == [publisher.COVERAGE_KEY]
    return json.loads(produced[publisher.COVERAGE_KEY])


def keys_in(value) -> set:
    if isinstance(value, dict):
        return set(value) | {key for child in value.values() for key in keys_in(child)}
    if isinstance(value, list):
        return {key for child in value for key in keys_in(child)}
    return set()


class CatalogDerivedSectionsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.catalog = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
        self.before = (sha(CATALOG_PATH.read_text(encoding="utf-8")), sha(ADR_MAP_PATH.read_text(encoding="utf-8")))
        self.document = build(None)

    def tearDown(self) -> None:
        self.assertEqual(self.before, (sha(CATALOG_PATH.read_text(encoding="utf-8")), sha(ADR_MAP_PATH.read_text(encoding="utf-8"))))

    def test_declared_sections_equal_an_independent_derivation_from_the_canonical_catalog(self):
        document = self.document
        self.assertEqual(document["schema"], "v213-options-coverage-v1")
        self.assertEqual(document["purpose"], "SOURCE_COVERAGE_METADATA_ONLY")
        self.assertEqual(document["generated_at"], "2026-09-30T17:00:00Z")
        self.assertEqual(document["data_completeness"], "NOT_REAUDITED")
        self.assertEqual(document["notes"], sorted(products.COVERAGE_NOTES))
        self.assertEqual(document["notes"], publisher.COVERAGE_NOTE_CODES)
        self.assertEqual([row["provider_id"] for row in document["providers"]], [p["id"] for p in self.catalog["providers"]])
        for row, provider in zip(document["providers"], self.catalog["providers"]):
            self.assertEqual((row["name"], row["authority"], row["jurisdictions"], row["data_roles"], row["rights_status"],
                              row["rights_reviewed_at"], row["adapter_status"], row["runtime_enabled"], row["line_quote_eligible"]),
                             (provider["name"], provider["authority"], provider["jurisdictions"], provider["data_roles"],
                              provider["rights_status"], provider["rights_reviewed_at"], provider["adapter_status"],
                              provider["runtime_enabled"], provider["line_quote_eligible"]))
            self.assertEqual(row["declared"], "CATALOG_DECLARED_UNVERIFIED")
        by_code: dict = {}
        for provider in self.catalog["providers"]:
            for code in provider["jurisdictions"]:
                by_code.setdefault(code, []).append(provider["id"])
        # literal catalog codes only: GLOBAL is its own row and is never expanded to countries
        self.assertEqual([(row["code"], row["provider_ids"], row["catalog_provider_count"]) for row in document["jurisdictions"]],
                         [(code, ids, len(ids)) for code, ids in sorted(by_code.items())])
        self.assertIn("GLOBAL", by_code)
        self.assertEqual({row["code"] for row in document["jurisdictions"]}, set(by_code))
        routing = json.loads(ADR_MAP_PATH.read_text(encoding="utf-8"))
        self.assertEqual([row["market"] for row in document["local_capabilities"]], sorted(routing["covered_markets"]))
        self.assertEqual({(row["capability"], row["status"]) for row in document["local_capabilities"]},
                         {("COVERED_CALL_DELAYED_LOCAL_CANDIDATE", "LOCAL_UNADMITTED_NO_CATALOG_IDENTITY")})

    def test_no_provider_is_admitted_and_no_observation_is_manufactured(self):
        document = self.document
        self.assertEqual({row["public_admission"] for row in document["providers"]}, {"NOT_ADMITTED"})
        self.assertEqual(document["catalog_summary"], {"catalog_provider_count": len(self.catalog["providers"]),
                                                       "public_admitted_provider_count": 0, "production_provider_selected": False})
        self.assertIsNone(document["options_link"])
        self.assertEqual(document["observed"], [])  # no options body: unknown, never a zero row

    def test_the_object_validates_stays_bounded_is_byte_stable_and_holds_no_quote_field(self):
        produced = publisher.lazy_options_coverage_body(None, NOW)[publisher.COVERAGE_KEY]
        products.validate_options_coverage_document(json.loads(produced))
        self.assertLessEqual(len(produced.encode("utf-8")), products.MAX_COVERAGE_BODY_BYTES)
        self.assertEqual(produced, publisher.lazy_options_coverage_body(None, NOW)[publisher.COVERAGE_KEY])
        self.assertFalse(keys_in(json.loads(produced)) & FORBIDDEN_KEYS)

    def test_generated_at_is_the_utc_instant_of_a_non_utc_clock(self):
        plus_two = datetime(2026, 9, 30, 19, 0, 0, tzinfo=timezone(timedelta(hours=2)))
        self.assertEqual(build(None, plus_two)["generated_at"], "2026-09-30T17:00:00Z")


class ObservedRowsTests(unittest.TestCase):
    def test_a_valid_body_is_linked_by_digest_and_counts_nothing_without_an_admitted_provider(self):
        text = body_of(admitted_options_document())
        document = build(text)
        self.assertEqual(document["options_link"], {"key": "v213:options:v2", "sha256": sha(text), "utf8_bytes": len(text.encode("utf-8"))})
        self.assertEqual(document["observed"], [])  # the real catalog admits nobody, so no cycle counts
        self.assertEqual(document["catalog_summary"]["public_admitted_provider_count"], 0)

    def test_an_admitted_provider_gives_one_aggregated_row_per_identity(self):
        base = admitted_options_document()["options"]
        extra = {
            "UNAVAIL": {"weekly": {"unavailable": "producer says no"}, "monthly": {"unavailable": "producer says no"}},
            "bad key!": base["SYNTHUS00"],  # a ticker syntax the loader never accepts: skipped
            "SYNTHUS02": {"daily": copy.deepcopy(base["SYNTHUS00"]["weekly"])},  # no arbitrary period key is interpreted
        }
        text = body_of(admitted_options_document(extra))
        with mock.patch.object(option_rights, "load_public_option_policy", return_value=synthetic_policy()):
            document = build(text)
        self.assertEqual(document["observed"], [{**SYNTHETIC_IDENTITY, "cycle_count": 4, "ticker_key_count": 2,
                                                 "quote_as_of_max": "2026-09-30T17:00:00Z"}])
        self.assertEqual(document["options_link"]["sha256"], sha(text))
        self.assertEqual(document["catalog_summary"]["public_admitted_provider_count"], 1)
        self.assertEqual({row["public_admission"] for row in document["providers"]}, {"NOT_ADMITTED"})  # a catalog row is never relabelled
        self.assertFalse(keys_in(document) & FORBIDDEN_KEYS)

    def test_a_row_that_fails_validation_or_claims_another_identity_is_not_counted(self):
        document = admitted_options_document()
        document["options"]["SYNTHUS00"]["weekly"]["multiplier"] = 10  # contract terms invalid
        document["options"]["SYNTHUS01"]["monthly"]["venue"] = "OTHERVENUE"  # not an admitted scope
        with mock.patch.object(option_rights, "load_public_option_policy", return_value=synthetic_policy()):
            observed = build(body_of(document))["observed"]
        self.assertEqual([(row["venue"], row["cycle_count"], row["ticker_key_count"]) for row in observed], [("SYNTHVENUE", 2, 2)])

    def test_an_unprovable_options_body_gives_an_empty_list_and_a_null_link(self):
        stale = admitted_options_document()
        stale["generated_at"] = "2026-09-30T10:59:59Z"  # 6 h 1 s old
        future = admitted_options_document()
        future["generated_at"] = "2026-09-30T17:05:01Z"  # 301 s ahead
        edge_future = admitted_options_document()
        edge_future["generated_at"] = "2026-09-30T17:05:00Z"  # exactly 300 s ahead is still inside the tolerance
        corrupt = admitted_options_document()
        corrupt["options"]["BROKEN"] = "not an object"
        noncanonical = admitted_options_document()
        noncanonical["generated_at"] = "2026-09-30 17:00:00"
        wrong_schema = admitted_options_document()
        wrong_schema["schema"] = "v213-options-v1"
        not_a_document = [1, 2, 3]
        with mock.patch.object(option_rights, "load_public_option_policy", return_value=synthetic_policy()):
            for label, value in (("stale", stale), ("future", future), ("corrupt ticker", corrupt), ("noncanonical clock", noncanonical),
                                 ("wrong schema", wrong_schema), ("not a document", not_a_document)):
                with self.subTest(label):
                    produced = build(body_of(value))
                    self.assertEqual((produced["observed"], produced["options_link"]), ([], None))
            edge = build(body_of(edge_future))
            self.assertIsNotNone(edge["options_link"])  # inside the tolerance the body is still linked

    def test_a_body_that_is_not_json_makes_the_builder_refuse_instead_of_publishing_a_link(self):
        self.assertEqual(publisher.lazy_options_coverage_body("{not json", NOW), {})  # fail closed: the Worker then reports COVERAGE_ABSENT


class RefusalTests(unittest.TestCase):
    def test_audit_findings_make_the_builder_refuse(self):
        with mock.patch.object(option_rights, "audit_public_options_providers", return_value=(["CATALOG_FINDING"], {})):
            self.assertEqual(publisher.lazy_options_coverage_body(None, NOW), {})

    def test_an_oversized_object_makes_the_builder_refuse(self):
        produced = publisher.lazy_options_coverage_body(None, NOW)[publisher.COVERAGE_KEY]
        size = len(produced.encode("utf-8"))
        with mock.patch.object(products, "MAX_COVERAGE_BODY_BYTES", size - 1):
            self.assertEqual(publisher.lazy_options_coverage_body(None, NOW), {})
        with mock.patch.object(products, "MAX_COVERAGE_BODY_BYTES", size):
            self.assertEqual(list(publisher.lazy_options_coverage_body(None, NOW)), [publisher.COVERAGE_KEY])  # exactly at the bound

    def test_a_schema_failure_makes_the_builder_refuse(self):
        with mock.patch.object(products, "validate_options_coverage_document", side_effect=products.MarketProductValidationError("X")):
            self.assertEqual(publisher.lazy_options_coverage_body(None, NOW), {})

    def test_the_validator_rejects_a_forged_or_widened_object(self):
        good = build(None)
        products.validate_options_coverage_document(good)
        observed = {**SYNTHETIC_IDENTITY, "cycle_count": 1, "ticker_key_count": 1, "quote_as_of_max": "2026-09-30T17:00:00Z"}
        forged_cases = {
            "extra top-level key": {**good, "strike": 1.0},
            "extra observed field": {**good, "observed": [{**observed, "bid": 1.0}]},
            "unknown note": {**good, "notes": [*good["notes"], "INVENTED"]},
            "wrong completeness": {**good, "data_completeness": "AUDITED"},
            "jurisdiction relation skewed": {**good, "jurisdictions": good["jurisdictions"][:-1]},
            "non-canonical instant": {**good, "generated_at": "2026-02-30T00:00:00Z"},
        }
        for label, value in forged_cases.items():
            with self.subTest(label), self.assertRaises(products.MarketProductValidationError):
                products.validate_options_coverage_document(value)


if __name__ == "__main__":
    unittest.main()
