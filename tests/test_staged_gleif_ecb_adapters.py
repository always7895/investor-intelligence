from __future__ import annotations

import json
import math
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from adapters.base import AdapterError  # noqa: E402
from adapters.ecb_sdmx import EcbSdmxAdapter, evidence_items as ecb_evidence  # noqa: E402
from adapters.gleif import GleifLeiAdapter, evidence_items as gleif_evidence  # noqa: E402

RETRIEVED_AT = "2026-08-24T12:00:00+00:00"


def ecb_fixture(value: str = "3.75") -> bytes:
    return (
        "KEY,FREQ,REF_AREA,INDICATOR,TIME_PERIOD,OBS_VALUE,UNIT,OBS_STATUS\n"
        f"FM.M.U2.EUR.4F.KR.MRR_FR.LEV,M,U2,MRR,2026-07,{value},PC,\n"
    ).encode("utf-8")


def gleif_fixture(lei: str = "5493001KJTIIGC8Y1R12") -> bytes:
    return json.dumps(
        {
            "data": {
                "type": "lei-records",
                "id": lei,
                "attributes": {
                    "lei": lei,
                    "entity": {
                        "legalName": {"name": "Synthetic Legal Entity", "language": "en"},
                        "otherNames": [{"name": "Synthetic Alias", "language": "en"}],
                        "legalAddress": {
                            "language": "en",
                            "addressLines": ["1 Synthetic Street"],
                            "city": "Test City",
                            "region": "TEST",
                            "country": "US",
                            "postalCode": "00000",
                        },
                        "headquartersAddress": {
                            "language": "en",
                            "addressLines": ["2 Synthetic Avenue"],
                            "city": "Test City",
                            "country": "US",
                        },
                        "registeredAt": "SYNTHETIC-REGISTRY",
                        "registeredAs": "SYNTHETIC-123",
                        "legalJurisdiction": "US-DE",
                        "category": "GENERAL",
                        "status": "ACTIVE",
                        "entityCreationDate": "2020-01-01T00:00:00Z",
                        "legalForm": {"id": "SYNTHETIC", "other": None},
                    },
                    "registration": {
                        "initialRegistrationDate": "2020-01-02T00:00:00Z",
                        "lastUpdateDate": "2026-08-20T00:00:00Z",
                        "status": "ISSUED",
                        "nextRenewalDate": "2027-01-02T00:00:00Z",
                        "managingLou": "SYNTHETICLOU0000000001",
                        "corroborationLevel": "FULLY_CORROBORATED",
                        "validationSources": "FULLY_CORROBORATED",
                    },
                },
            }
        },
        separators=(",", ":"),
    ).encode("utf-8")


class StagedGleifEcbAdapterTests(unittest.TestCase):
    def test_ecb_source_specific_host_path_and_evidence(self) -> None:
        adapter = EcbSdmxAdapter()
        batch = adapter.parse(
            ecb_fixture(),
            content_type="text/csv",
            retrieved_at=RETRIEVED_AT,
            context={
                "request_url": "https://data-api.ecb.europa.eu/service/data/FM/M.U2.EUR.4F.KR.MRR_FR.LEV?format=csvdata",
                "dataflow": "FM",
            },
        )
        self.assertEqual(batch.record_count, 1)
        record = batch.records[0]
        self.assertEqual(record["observation_value"], 3.75)
        self.assertEqual(record["time_period"], "2026-07")
        self.assertEqual(record["period_as_of"], "2026-07-31T00:00:00+00:00")
        evidence = ecb_evidence(batch, registry_version="catalog-v1")
        self.assertEqual(len(evidence), 1)
        self.assertEqual(evidence[0]["claim_type"], "official_indicator_value")
        self.assertEqual(evidence[0]["field_values"]["observation_value"], 3.75)

    def test_ecb_evidence_revision_never_derived_from_retrieval_time(self) -> None:
        adapter = EcbSdmxAdapter()
        context = {
            "request_url": (
                "https://data-api.ecb.europa.eu/service/data/FM/M.U2.EUR.4F.KR.MRR_FR.LEV"
                "?format=csvdata"
            ),
            "dataflow": "FM",
        }
        first = adapter.parse(
            ecb_fixture(),
            content_type="text/csv",
            retrieved_at=RETRIEVED_AT,
            context=dict(context),
        )
        second = adapter.parse(
            ecb_fixture(),
            content_type="text/csv",
            retrieved_at="2026-08-25T12:00:00+00:00",
            context=dict(context),
        )
        self.assertNotEqual(first.retrieved_at, second.retrieved_at)
        evidence_first = ecb_evidence(first, registry_version="catalog-v1")
        evidence_second = ecb_evidence(second, registry_version="catalog-v1")
        self.assertEqual(len(evidence_first), 1)
        self.assertEqual(len(evidence_second), 1)
        item_first, item_second = evidence_first[0], evidence_second[0]
        self.assertIsNone(item_first["published_at"])
        self.assertIsNone(item_second["published_at"])
        self.assertIsNone(item_first["revision_or_vintage"])
        self.assertIsNone(item_second["revision_or_vintage"])
        self.assertEqual(item_first["as_of"], item_second["as_of"])
        self.assertEqual(item_first["claim_id"], item_second["claim_id"])
        self.assertEqual(item_first["content_sha256"], item_second["content_sha256"])
        self.assertEqual(item_first["retrieved_at"], RETRIEVED_AT)
        self.assertEqual(
            item_second["retrieved_at"], "2026-08-25T12:00:00+00:00"
        )

    def test_ecb_rejects_legacy_wrong_host_path_type_and_nonfinite_values(self) -> None:
        adapter = EcbSdmxAdapter()
        cases = (
            (
                "https://sdw-wsrest.ecb.europa.eu/service/data/FM/test",
                "text/csv",
                ecb_fixture(),
            ),
            (
                "https://data-api.ecb.europa.eu/help/api/overview",
                "text/csv",
                ecb_fixture(),
            ),
            (
                "https://data-api.ecb.europa.eu/service/data/FM/test",
                "application/json",
                ecb_fixture(),
            ),
            (
                "https://data-api.ecb.europa.eu/service/data/FM/test",
                "text/csv",
                ecb_fixture("NaN"),
            ),
        )
        for url, content_type, content in cases:
            with self.subTest(url=url, content_type=content_type), self.assertRaises(
                AdapterError
            ):
                adapter.parse(
                    content,
                    content_type=content_type,
                    retrieved_at=RETRIEVED_AT,
                    context={"request_url": url, "dataflow": "FM"},
                )

    def test_gleif_normalization_and_evidence(self) -> None:
        adapter = GleifLeiAdapter()
        batch = adapter.parse(
            gleif_fixture(),
            content_type="application/vnd.api+json",
            retrieved_at=RETRIEVED_AT,
            context={
                "request_url": "https://api.gleif.org/api/v1/lei-records/5493001KJTIIGC8Y1R12"
            },
        )
        self.assertEqual(batch.record_count, 1)
        record = batch.records[0]
        self.assertEqual(record["lei"], "5493001KJTIIGC8Y1R12")
        self.assertEqual(record["legal_name"], "Synthetic Legal Entity")
        self.assertEqual(record["legal_jurisdiction"], "US-DE")
        self.assertEqual(record["entity_status"], "ACTIVE")
        evidence = gleif_evidence(batch, registry_version="catalog-v1")
        self.assertEqual(len(evidence), 1)
        self.assertEqual(evidence[0]["claim_type"], "legal_entity_reference")
        self.assertEqual(evidence[0]["field_values"]["lei"], record["lei"])

    def test_gleif_evidence_clocks_never_derived_from_retrieval_time(self) -> None:
        adapter = GleifLeiAdapter()
        context = {
            "request_url": "https://api.gleif.org/api/v1/lei-records/5493001KJTIIGC8Y1R12"
        }
        document = json.loads(gleif_fixture())
        document["data"]["attributes"]["registration"].pop("lastUpdateDate")
        missing_content = json.dumps(document, separators=(",", ":")).encode("utf-8")
        first = adapter.parse(
            missing_content,
            content_type="application/vnd.api+json",
            retrieved_at=RETRIEVED_AT,
            context=dict(context),
        )
        second = adapter.parse(
            missing_content,
            content_type="application/vnd.api+json",
            retrieved_at="2026-08-25T12:00:00+00:00",
            context=dict(context),
        )
        self.assertNotEqual(first.retrieved_at, second.retrieved_at)
        evidence_first = gleif_evidence(first, registry_version="catalog-v1")
        evidence_second = gleif_evidence(second, registry_version="catalog-v1")
        self.assertEqual(len(evidence_first), 1)
        self.assertEqual(len(evidence_second), 1)
        item_first, item_second = evidence_first[0], evidence_second[0]
        for item in (item_first, item_second):
            self.assertIsNone(item["published_at"])
            self.assertIsNone(item["as_of"])
            self.assertIsNone(item["revision_or_vintage"])
        self.assertEqual(item_first["claim_id"], item_second["claim_id"])
        self.assertEqual(item_first["content_sha256"], item_second["content_sha256"])
        self.assertEqual(item_first["retrieved_at"], RETRIEVED_AT)
        self.assertEqual(item_second["retrieved_at"], "2026-08-25T12:00:00+00:00")

        disclosed = adapter.parse(
            gleif_fixture(),
            content_type="application/vnd.api+json",
            retrieved_at=RETRIEVED_AT,
            context=dict(context),
        )
        disclosed_item = gleif_evidence(disclosed, registry_version="catalog-v1")[0]
        for field in ("published_at", "as_of", "revision_or_vintage"):
            self.assertEqual(disclosed_item[field], "2026-08-20T00:00:00Z")

    def test_gleif_rejects_bad_lei_duplicate_wrong_host_and_incomplete_records(self) -> None:
        adapter = GleifLeiAdapter()
        bad_lei = gleif_fixture("INVALID")
        with self.assertRaises(AdapterError):
            adapter.parse(
                bad_lei,
                content_type="application/json",
                retrieved_at=RETRIEVED_AT,
                context={"request_url": "https://api.gleif.org/api/v1/lei-records/INVALID"},
            )

        duplicate_document = json.loads(gleif_fixture())
        duplicate_document["data"] = [duplicate_document["data"], duplicate_document["data"]]
        with self.assertRaises(AdapterError):
            adapter.parse(
                json.dumps(duplicate_document).encode(),
                content_type="application/json",
                retrieved_at=RETRIEVED_AT,
                context={"request_url": "https://api.gleif.org/api/v1/lei-records"},
            )

        with self.assertRaises(AdapterError):
            adapter.parse(
                gleif_fixture(),
                content_type="application/json",
                retrieved_at=RETRIEVED_AT,
                context={"request_url": "https://gleif.example.test/api/v1/lei-records"},
            )

        document = json.loads(gleif_fixture())
        document["data"]["attributes"]["entity"].pop("legalName")
        with self.assertRaises(AdapterError):
            adapter.parse(
                json.dumps(document).encode(),
                content_type="application/json",
                retrieved_at=RETRIEVED_AT,
                context={"request_url": "https://api.gleif.org/api/v1/lei-records/test"},
            )

    def test_sdmx_helper_rejects_duplicate_normalized_headers_and_record_bombs(self) -> None:
        adapter = EcbSdmxAdapter()
        duplicate_header = (
            "KEY,TIME_PERIOD,OBS_VALUE, obs_value\n"
            "SYNTHETIC,2026-07,1,1\n"
        ).encode()
        with self.assertRaises(AdapterError):
            adapter.parse(
                duplicate_header,
                content_type="text/csv",
                retrieved_at=RETRIEVED_AT,
                context={
                    "request_url": "https://data-api.ecb.europa.eu/service/data/FM/test"
                },
            )


if __name__ == "__main__":
    unittest.main()
