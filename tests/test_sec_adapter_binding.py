from __future__ import annotations

import dataclasses
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from adapters.base import (  # noqa: E402
    AdapterError,
    FetchReceipt,
    canonical_json,
    make_batch,
    mint_fetch_receipt,
    validate_fetch_receipt,
)
from adapters.sec_edgar import (  # noqa: E402
    SEC_REGISTRY_SOURCE_ID,
    SecClaimBinding,
    bind_sec_claim,
)
from source_registry import (  # noqa: E402
    DEFAULT_CLAIM_POLICY_PATH,
    DEFAULT_FEDERATION_POLICY_PATH,
    Registry,
    load_json,
    load_registry,
    qualify_claim_evidence,
)

CIK = "0000320193"
PERIOD = "2026-07-31"
FILED = "2026-08-15"
RETRIEVED = "2026-08-15T00:00:00+00:00"
NOW = "2026-08-15T00:00:00+00:00"
CANON_URL = f"https://data.sec.gov/api/xbrl/companyfacts/CIK{CIK}.json"
CLAIM_POLICY = load_json(DEFAULT_CLAIM_POLICY_PATH)
FEDERATION_POLICY = load_json(DEFAULT_FEDERATION_POLICY_PATH)
REGISTRY = load_registry()


def _companyfacts_bytes(filed: str = FILED, value: int = 1000) -> bytes:
    document = {
        "cik": CIK,
        "entityName": "Apple Inc.",
        "facts": {
            "us-gaap": {
                "Revenues": {
                    "label": "Revenues",
                    "units": {
                        "USD": [
                            {
                                "val": value,
                                "end": PERIOD,
                                "filed": filed,
                                "accn": "0000320193-26-000001",
                                "form": "10-Q",
                                "fy": 2026,
                                "fp": "Q3",
                            }
                        ],
                        "shares": [
                            {
                                "val": 5,
                                "end": "2026-06-30",
                                "filed": filed,
                                "accn": "0000320193-26-000002",
                                "form": "10-Q",
                            }
                        ],
                    },
                }
            }
        },
    }
    return json.dumps(document).encode("utf-8")


def _receipt(content: bytes, *, url: str = CANON_URL) -> FetchReceipt:
    return mint_fetch_receipt(
        source_id=SEC_REGISTRY_SOURCE_ID,
        canonical_url=url,
        retrieved_at=RETRIEVED,
        http_status=200,
        body=content,
        transport_metadata={"capture": "response_seam"},
    )


def _raw_batch(content: bytes):
    return make_batch(
        source_id=SEC_REGISTRY_SOURCE_ID,
        parser_version="sec-edgar-json-v1",
        content=content,
        retrieved_at=RETRIEVED,
        records=_parsed_records(content),
    )


def _parsed_records(content: bytes):
    from adapters.sec_edgar import SecEdgarAdapter

    return SecEdgarAdapter().parse(
        content,
        content_type="application/json",
        retrieved_at=RETRIEVED,
        context={"request_url": CANON_URL},
    ).records


def _enabled_registry() -> Registry:
    sources = []
    for source in REGISTRY.sources:
        if source.source_id == SEC_REGISTRY_SOURCE_ID:
            source = dataclasses.replace(
                source,
                runtime_enabled=True,
                admission_status="RUNTIME_ENABLED",
                adapter_status="implemented",
            )
        sources.append(source)
    return Registry(
        schema_version=REGISTRY.schema_version,
        sources=tuple(sources),
        catalog_files=REGISTRY.catalog_files,
    )


class ReceiptIntegrityTests(unittest.TestCase):
    def test_direct_construction_is_invalid(self) -> None:
        with self.assertRaises(TypeError):
            FetchReceipt(  # type: ignore[call-arg]
                source_id=SEC_REGISTRY_SOURCE_ID,
                canonical_url=CANON_URL,
                retrieved_at=RETRIEVED,
                http_status=200,
                content_sha256="0" * 64,
            )

    def test_deep_mutation_is_rejected(self) -> None:
        receipt = _receipt(_companyfacts_bytes())
        with self.assertRaises(AttributeError):
            receipt.http_status = 201  # type: ignore[misc]
        with self.assertRaises((AttributeError, TypeError)):
            receipt.transport_metadata["injected"] = True  # type: ignore[index]

    def test_string_and_bool_status_fakes_are_invalid(self) -> None:
        content = _companyfacts_bytes()
        with self.assertRaises(AdapterError):
            mint_fetch_receipt(
                source_id=SEC_REGISTRY_SOURCE_ID,
                canonical_url=CANON_URL,
                retrieved_at=RETRIEVED,
                http_status="200",  # type: ignore[arg-type]
                body=content,
            )
        with self.assertRaises(AdapterError):
            mint_fetch_receipt(
                source_id=SEC_REGISTRY_SOURCE_ID,
                canonical_url=CANON_URL,
                retrieved_at=RETRIEVED,
                http_status=True,  # type: ignore[arg-type]
                body=content,
            )

    def test_byte_hash_and_url_tamper_fail(self) -> None:
        content = _companyfacts_bytes()
        receipt = _receipt(content)
        validate_fetch_receipt(receipt, source_id=SEC_REGISTRY_SOURCE_ID, content=content)
        with self.assertRaises(AdapterError):
            validate_fetch_receipt(
                receipt, source_id=SEC_REGISTRY_SOURCE_ID, content=content + b"x"
            )
        with self.assertRaises(AdapterError):
            validate_fetch_receipt(
                receipt,
                source_id=SEC_REGISTRY_SOURCE_ID,
                content=content,
                expected_urls=("https://data.sec.gov/api/xbrl/companyfacts/CIK9999999999.json",),
            )


class BindSecClaimTests(unittest.TestCase):
    def test_happy_path_projection_fields(self) -> None:
        content = _companyfacts_bytes()
        binding = bind_sec_claim(
            content, _receipt(content), REGISTRY, "issuer_financial_statement", CIK, PERIOD
        )
        record = binding.projected_records[0]
        self.assertEqual(record["entity"], CIK)
        self.assertEqual(record["identifier"], CIK)
        self.assertEqual(record["period"], PERIOD)
        self.assertEqual(record["currency"], "USD")
        self.assertEqual(record["filing_identifier"], "0000320193-26-000001")
        self.assertEqual(record["jurisdiction"], "US")
        self.assertEqual(record["unit"], "USD")
        self.assertEqual(record["taxonomy"], "us-gaap")
        self.assertEqual(record["tag"], "Revenues")
        self.assertEqual(record["fact_period"], {"start": None, "end": PERIOD})
        self.assertIsNone(binding.resolved_symbol)
        self.assertNotIn("symbol", record)
        self.assertEqual(binding.projected_record_digest, canonical_json(binding.projected_records))

    def test_expected_period_mandatory_and_quarter_mismatch_fails(self) -> None:
        content = _companyfacts_bytes()
        with self.assertRaises(AdapterError):
            bind_sec_claim(content, _receipt(content), REGISTRY, "issuer_financial_statement", CIK)
        with self.assertRaises(AdapterError):
            bind_sec_claim(
                content, _receipt(content), REGISTRY, "issuer_financial_statement", CIK, "2026-06-30"
            )

    def test_symbol_only_from_explicit_resolved_alias(self) -> None:
        content = _companyfacts_bytes()
        binding = bind_sec_claim(
            content,
            _receipt(content),
            REGISTRY,
            "issuer_financial_statement",
            CIK,
            PERIOD,
            resolved_symbol_alias={"cik": CIK, "symbol": "AAPL"},
        )
        self.assertEqual(binding.resolved_symbol, "AAPL")
        self.assertEqual(binding.projected_records[0]["symbol"], "AAPL")
        with self.assertRaises(AdapterError):
            bind_sec_claim(
                content,
                _receipt(content),
                REGISTRY,
                "issuer_financial_statement",
                CIK,
                PERIOD,
                resolved_symbol_alias={"cik": "9999999999", "symbol": "AAPL"},
            )

    def test_units_retained_raw_and_non_usd_fail_monetary(self) -> None:
        shares_only = json.dumps(
            {
                "cik": CIK,
                "entityName": "Apple Inc.",
                "facts": {
                    "us-gaap": {
                        "ShareCount": {
                            "label": "Share Count",
                            "units": {
                                "shares": [
                                    {
                                        "val": 5,
                                        "end": PERIOD,
                                        "filed": FILED,
                                        "accn": "0000320193-26-000001",
                                        "form": "10-Q",
                                    }
                                ]
                            },
                        }
                    }
                },
            }
        ).encode("utf-8")
        with self.assertRaises(AdapterError):
            bind_sec_claim(
                shares_only,
                _receipt(shares_only),
                REGISTRY,
                "issuer_financial_statement",
                CIK,
                PERIOD,
            )

    def test_four_clocks_separate_and_date_precision_bounds(self) -> None:
        content = _companyfacts_bytes()
        binding = bind_sec_claim(
            content, _receipt(content), REGISTRY, "issuer_financial_statement", CIK, PERIOD
        )
        self.assertEqual(
            binding.clock_labels,
            ("fact_period", "filing_time", "source_event_time", "evidence_as_of", "retrieved_at"),
        )
        self.assertEqual(
            binding.evidence_as_of,
            f"{FILED}T00:00:00+00:00|evidence_as_of|date_precision|earliest_bound",
        )
        parts = binding.evidence_as_of.split("|")
        self.assertEqual(parts[1], "evidence_as_of")
        self.assertEqual(parts[2], "date_precision")
        self.assertEqual(parts[3], "earliest_bound")

    def test_future_source_clock_rejected(self) -> None:
        content = _companyfacts_bytes(filed="2026-08-16")
        with self.assertRaises(AdapterError):
            bind_sec_claim(
                content, _receipt(content), REGISTRY, "issuer_financial_statement", CIK, PERIOD
            )

    def test_receipt_required_no_auto_attestation(self) -> None:
        content = _companyfacts_bytes()
        with self.assertRaises((TypeError, AdapterError)):
            bind_sec_claim(
                content, None, REGISTRY, "issuer_financial_statement", CIK, PERIOD  # type: ignore[arg-type]
            )
        with self.assertRaises(AdapterError):
            bind_sec_claim(
                content,
                {"http_status": 200},  # type: ignore[arg-type]
                REGISTRY,
                "issuer_financial_statement",
                CIK,
                PERIOD,
            )

    def test_strict_cik_no_permissive_digit_stripping(self) -> None:
        content = _companyfacts_bytes()
        with self.assertRaises(AdapterError):
            bind_sec_claim(
                content, _receipt(content), REGISTRY, "issuer_financial_statement", "320193", PERIOD
            )

    def test_receipt_url_host_path_pinned_to_reviewed_sec_endpoints(self) -> None:
        content = _companyfacts_bytes()
        bad_urls = (
            "https://evil.example.com/api/xbrl/companyfacts/CIK0000320193.json",
            "https://data.sec.gov:8443/api/xbrl/companyfacts/CIK0000320193.json",
            "https://user@data.sec.gov/api/xbrl/companyfacts/CIK0000320193.json",
            "https://data.sec.gov/api/xbrl/companyfacts/CIK0000320193.json?x=1",
            "https://data.sec.gov/api/xbrl/companyfacts/CIK0000320193.json#f",
            "https://data.sec.gov/Archives/CIK0000320193.json",
            "https://data.sec.gov/submissions/CIK320193.json",
        )
        for url in bad_urls:
            with self.subTest(url=url):
                with self.assertRaises(AdapterError):
                    bind_sec_claim(
                        content,
                        _receipt(content, url=url),
                        REGISTRY,
                        "issuer_financial_statement",
                        CIK,
                        PERIOD,
                    )
        # Positive unchanged: the reviewed companyfacts URL still binds.
        binding = bind_sec_claim(
            content, _receipt(content), REGISTRY, "issuer_financial_statement", CIK, PERIOD
        )
        self.assertEqual(binding.canonical_url, CANON_URL)


class QualifierSecGuardTests(unittest.TestCase):
    def _observation(self, batch, expected_subject, as_of: str = "2026-08-15T00:00:00+00:00"):
        return {
            "parsed_batch": batch,
            "as_of": as_of,
            "http_status": 200,
            "declared_access": "free",
            "observed_health": None,
            "subject": dict(expected_subject),
            "data_origin_lineage": {
                "publisher_identity": SEC_REGISTRY_SOURCE_ID,
                "independence_group": "us_sec",
                "original_disclosure_id": "0000320193-26-000001",
            },
            "transport_lineage": {
                "fetch_source": SEC_REGISTRY_SOURCE_ID,
                "path": CANON_URL,
            },
        }

    def _expected_subject(self):
        return {"entity": CIK, "period": PERIOD}

    def test_real_registry_disabled_remains_non_qualifying(self) -> None:
        content = _companyfacts_bytes()
        binding = bind_sec_claim(
            content, _receipt(content), REGISTRY, "issuer_financial_statement", CIK, PERIOD
        )
        result = qualify_claim_evidence(
            REGISTRY,
            "issuer_financial_statement",
            CLAIM_POLICY,
            [self._observation(_raw_batch(content), self._expected_subject())],
            now=NOW,
            expected_subject=self._expected_subject(),
            federation_policy=FEDERATION_POLICY,
            sec_binding=binding,
        )
        self.assertFalse(result["qualified"])
        self.assertTrue(any("runtime" in e["reason"] for e in result["rejected"]))

    def test_enabled_test_clone_qualifies_with_valid_binding(self) -> None:
        content = _companyfacts_bytes()
        binding = bind_sec_claim(
            content, _receipt(content), REGISTRY, "issuer_financial_statement", CIK, PERIOD
        )
        result = qualify_claim_evidence(
            _enabled_registry(),
            "issuer_financial_statement",
            CLAIM_POLICY,
            [self._observation(_raw_batch(content), self._expected_subject())],
            now=NOW,
            expected_subject=self._expected_subject(),
            federation_policy=FEDERATION_POLICY,
            sec_binding=binding,
        )
        self.assertTrue(result["qualified"])
        self.assertFalse(result["publication_eligible"])

    def test_caller_http_200_without_receipt_cannot_bypass(self) -> None:
        content = _companyfacts_bytes()
        result = qualify_claim_evidence(
            _enabled_registry(),
            "issuer_financial_statement",
            CLAIM_POLICY,
            [self._observation(_raw_batch(content), self._expected_subject())],
            now=NOW,
            expected_subject=self._expected_subject(),
            federation_policy=FEDERATION_POLICY,
        )
        self.assertFalse(result["qualified"])
        self.assertTrue(any("sec binding" in e["reason"] for e in result["rejected"]))

    def test_projected_record_tamper_fails_digest(self) -> None:
        content = _companyfacts_bytes()
        binding = bind_sec_claim(
            content, _receipt(content), REGISTRY, "issuer_financial_statement", CIK, PERIOD
        )
        tampered = _companyfacts_bytes(value=999)
        tampered_batch = make_batch(
            source_id=SEC_REGISTRY_SOURCE_ID,
            parser_version="sec-edgar-json-v1",
            content=tampered,
            retrieved_at=RETRIEVED,
            records=_parsed_records(tampered),
        )
        result = qualify_claim_evidence(
            _enabled_registry(),
            "issuer_financial_statement",
            CLAIM_POLICY,
            [self._observation(tampered_batch, self._expected_subject())],
            now=NOW,
            expected_subject=self._expected_subject(),
            federation_policy=FEDERATION_POLICY,
            sec_binding=binding,
        )
        self.assertFalse(result["qualified"])
        self.assertTrue(any("sec binding" in e["reason"] for e in result["rejected"]))

    def test_stale_event_clock_rejected_at_qualify(self) -> None:
        content = _companyfacts_bytes(filed="2026-01-05")
        binding = bind_sec_claim(
            content, _receipt(content), REGISTRY, "issuer_financial_statement", CIK, PERIOD
        )
        result = qualify_claim_evidence(
            _enabled_registry(),
            "issuer_financial_statement",
            CLAIM_POLICY,
            [self._observation(_raw_batch(content), self._expected_subject(), as_of="2026-01-05T00:00:00+00:00")],
            now=NOW,
            expected_subject=self._expected_subject(),
            federation_policy=FEDERATION_POLICY,
            sec_binding=binding,
        )
        self.assertFalse(result["qualified"])
        self.assertTrue(any("stale" in e["reason"] for e in result["rejected"]))

    def test_generic_providers_unchanged_and_binding_scope_enforced(self) -> None:
        # A non-SEC batch with a sec_binding is rejected (scope enforcement).
        content = _companyfacts_bytes()
        binding = bind_sec_claim(
            content, _receipt(content), REGISTRY, "issuer_financial_statement", CIK, PERIOD
        )
        non_sec_batch = make_batch(
            source_id="tw_mops",
            parser_version="test-1",
            content=b"other-bytes",
            retrieved_at=RETRIEVED,
            records=[{"entity": "X", "period": PERIOD, "currency": "USD", "value": 1, "filing_identifier": "F"}],
        )
        observation = self._observation(non_sec_batch, {"entity": "X", "period": PERIOD})
        observation["data_origin_lineage"]["publisher_identity"] = "tw_mops"
        observation["data_origin_lineage"]["independence_group"] = "tw_mops"
        observation["transport_lineage"]["fetch_source"] = "tw_mops"
        observation["transport_lineage"]["path"] = "https://twm.com.tw/x"
        result = qualify_claim_evidence(
            _enabled_registry(),
            "issuer_financial_statement",
            CLAIM_POLICY,
            [observation],
            now=NOW,
            expected_subject={"entity": "X", "period": PERIOD},
            federation_policy=FEDERATION_POLICY,
            sec_binding=binding,
        )
        self.assertFalse(result["qualified"])
        self.assertTrue(any("sec binding" in e["reason"] for e in result["rejected"]))

    def test_registry_us_adapter_mapping_change_after_bind_fails_qualify(self) -> None:
        content = _companyfacts_bytes()
        binding = bind_sec_claim(
            content, _receipt(content), REGISTRY, "issuer_financial_statement", CIK, PERIOD
        )
        drifted_sources = []
        for source in REGISTRY.sources:
            if source.source_id == SEC_REGISTRY_SOURCE_ID:
                source = dataclasses.replace(
                    source,
                    runtime_enabled=True,
                    admission_status="RUNTIME_ENABLED",
                    adapter_status="implemented",
                    adapter_id="tampered_adapter",
                )
            drifted_sources.append(source)
        drifted = Registry(
            schema_version=REGISTRY.schema_version,
            sources=tuple(drifted_sources),
            catalog_files=REGISTRY.catalog_files,
        )
        result = qualify_claim_evidence(
            drifted,
            "issuer_financial_statement",
            CLAIM_POLICY,
            [self._observation(_raw_batch(content), self._expected_subject())],
            now=NOW,
            expected_subject=self._expected_subject(),
            federation_policy=FEDERATION_POLICY,
            sec_binding=binding,
        )
        self.assertFalse(result["qualified"])
        self.assertTrue(any("adapter mapping" in e["reason"] for e in result["rejected"]))

    def test_as_of_substitution_within_ttl_still_rejected(self) -> None:
        content = _companyfacts_bytes()
        binding = bind_sec_claim(
            content, _receipt(content), REGISTRY, "issuer_financial_statement", CIK, PERIOD
        )
        # Fresh (within TTL, not future) but not the bound-derived clock.
        result = qualify_claim_evidence(
            _enabled_registry(),
            "issuer_financial_statement",
            CLAIM_POLICY,
            [self._observation(_raw_batch(content), self._expected_subject(), as_of="2026-08-14T23:30:00+00:00")],
            now=NOW,
            expected_subject=self._expected_subject(),
            federation_policy=FEDERATION_POLICY,
            sec_binding=binding,
        )
        self.assertFalse(result["qualified"])
        self.assertTrue(any("bound-derived" in e["reason"] for e in result["rejected"]))

    def test_transport_path_replacement_must_match_receipt_canonical_url(self) -> None:
        content = _companyfacts_bytes()
        binding = bind_sec_claim(
            content, _receipt(content), REGISTRY, "issuer_financial_statement", CIK, PERIOD
        )
        observation = self._observation(_raw_batch(content), self._expected_subject())
        observation["transport_lineage"]["path"] = f"https://data.sec.gov/submissions/CIK{CIK}.json"
        result = qualify_claim_evidence(
            _enabled_registry(),
            "issuer_financial_statement",
            CLAIM_POLICY,
            [observation],
            now=NOW,
            expected_subject=self._expected_subject(),
            federation_policy=FEDERATION_POLICY,
            sec_binding=binding,
        )
        self.assertFalse(result["qualified"])
        self.assertTrue(any("receipt canonical URL" in e["reason"] for e in result["rejected"]))
class FetchSeamOfflineTests(unittest.TestCase):
    def test_no_endpoints_expansion_and_bytes_api_preserved(self) -> None:
        import fetch_public_source_observations as fpo

        # No SEC API (submissions/companyfacts) admission was added; the
        # pre-existing static feed table is unchanged.
        self.assertNotIn("data.sec.gov", " ".join(fpo.ENDPOINTS.values()))
        self.assertFalse(
            any("companyfacts" in key or "submissions" in key for key in fpo.ENDPOINTS)
        )
        self.assertIn(fpo.fetch_bytes.__annotations__.get("return"), (bytes, "bytes"))

    def test_receipt_minting_transport_offline(self) -> None:
        import fetch_public_source_observations as fpo

        captured: dict[str, bytes] = {}

        def injected_transport(url: str) -> bytes:
            body = b'{"offline": true, "url": "' + url.encode("utf-8") + b'"}'
            captured[url] = body
            return body

        wrapper = fpo.ReceiptMintingTransport(injected_transport, source_id="test_source")
        body = wrapper("https://example.invalid/payload.json")
        receipts = wrapper.receipts()
        self.assertEqual(len(receipts), 1)
        self.assertEqual(receipts[0].http_status, 200)
        self.assertEqual(receipts[0].canonical_url, "https://example.invalid/payload.json")
        self.assertEqual(captured["https://example.invalid/payload.json"], body)
        validate_fetch_receipt(receipts[0], source_id="test_source", content=body)

        row = {
            "source_id": "test_source",
            "source_request_url": "https://example.invalid/payload.json",
            "content_sha256": receipts[0].content_sha256,
        }
        self.assertIs(fpo.receipt_for_observation(row, receipts), receipts[0])
        row["content_sha256"] = "0" * 64
        with self.assertRaises(AdapterError):
            fpo.receipt_for_observation(row, receipts)


if __name__ == "__main__":
    unittest.main()