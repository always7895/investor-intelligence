from __future__ import annotations

import json
import math
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from adapters import (  # noqa: E402
    ADAPTERS,
    AdapterError,
    build_evidence_items,
    parse_source_payload,
)
from authoritative_adapter_gate import (  # noqa: E402
    audit_adapter_routes,
    catalog_source_map,
)

RETRIEVED_AT = "2026-08-24T12:00:00+00:00"


def sec_submissions_fixture() -> bytes:
    return json.dumps(
        {
            "cik": "0000320193",
            "name": "Synthetic Public Issuer",
            "filings": {
                "recent": {
                    "accessionNumber": ["0000320193-26-000001"],
                    "filingDate": ["2026-08-20"],
                    "reportDate": ["2026-06-30"],
                    "acceptanceDateTime": ["20260820160000"],
                    "act": ["34"],
                    "form": ["10-Q"],
                    "fileNumber": ["001-00001"],
                    "filmNumber": ["261234567"],
                    "items": [""],
                    "size": [123456],
                    "isXBRL": [1],
                    "isInlineXBRL": [1],
                    "primaryDocument": ["synthetic-20260630.htm"],
                    "primaryDocDescription": ["Synthetic quarterly report"],
                }
            },
        },
        separators=(",", ":"),
    ).encode("utf-8")


def sec_companyfacts_fixture(value: float = 123456789.0) -> bytes:
    return json.dumps(
        {
            "cik": 320193,
            "entityName": "Synthetic Public Issuer",
            "facts": {
                "us-gaap": {
                    "Revenues": {
                        "label": "Revenue",
                        "description": "Synthetic fixture only",
                        "units": {
                            "USD": [
                                {
                                    "start": "2026-04-01",
                                    "end": "2026-06-30",
                                    "val": value,
                                    "accn": "0000320193-26-000001",
                                    "fy": 2026,
                                    "fp": "Q2",
                                    "form": "10-Q",
                                    "filed": "2026-08-20",
                                    "frame": "CY2026Q2",
                                }
                            ]
                        },
                    }
                }
            },
        },
        separators=(",", ":"),
    ).encode("utf-8")


def world_bank_fixture(*, pages: int = 1, page: int = 1) -> bytes:
    return json.dumps(
        [
            {
                "page": page,
                "pages": pages,
                "per_page": 50,
                "total": 1,
                "lastupdated": "2026-07-01",
            },
            [
                {
                    "indicator": {
                        "id": "NY.GDP.MKTP.CD",
                        "value": "GDP (current US$)",
                    },
                    "country": {"id": "US", "value": "United States"},
                    "countryiso3code": "USA",
                    "date": "2025",
                    "value": 100.5,
                    "unit": "USD",
                    "obs_status": "",
                    "decimal": 0,
                    "source": {"id": "2", "value": "World Development Indicators"},
                    "sourceNote": "Synthetic fixture",
                }
            ],
        ],
        separators=(",", ":"),
    ).encode("utf-8")


class ReplayedAuthoritativeAdapterTests(unittest.TestCase):
    def test_static_registry_contains_only_replayed_reviewed_adapters(self) -> None:
        self.assertEqual(set(ADAPTERS), {"sec_edgar", "world_bank_indicators"})

    def test_sec_submissions_normalization_and_evidence(self) -> None:
        content = sec_submissions_fixture()
        batch = parse_source_payload(
            "sec_edgar",
            content,
            content_type="application/json",
            retrieved_at=RETRIEVED_AT,
            context={
                "request_url": "https://data.sec.gov/submissions/CIK0000320193.json"
            },
        )
        self.assertEqual(batch.record_count, 1)
        record = batch.records[0]
        self.assertEqual(record["cik"], "0000320193")
        self.assertEqual(record["form"], "10-Q")
        self.assertEqual(record["record_type"], "submission_filing")
        self.assertTrue(str(record["record_url"]).startswith("https://www.sec.gov/Archives/"))
        evidence = build_evidence_items(batch, registry_version="catalog-v1")
        self.assertEqual(len(evidence), 1)
        self.assertEqual(evidence[0]["claim_type"], "issuer_filing")
        self.assertEqual(evidence[0]["content_sha256"], batch.content_sha256)
        self.assertIn("accession_number", evidence[0]["material_fields"])

    def test_sec_companyfacts_normalization_and_evidence(self) -> None:
        batch = parse_source_payload(
            "sec_edgar",
            sec_companyfacts_fixture(),
            content_type="application/json; charset=utf-8",
            retrieved_at=RETRIEVED_AT,
            context={
                "request_url": "https://data.sec.gov/api/xbrl/companyfacts/CIK0000320193.json"
            },
        )
        record = batch.records[0]
        self.assertEqual(record["record_type"], "company_fact")
        self.assertEqual(record["tag"], "Revenues")
        self.assertEqual(record["unit"], "USD")
        evidence = build_evidence_items(batch, registry_version="catalog-v1")
        self.assertEqual(evidence[0]["claim_type"], "xbrl_fact")
        self.assertEqual(evidence[0]["field_values"]["value"], 123456789.0)

    def test_world_bank_normalization_evidence_and_pagination_warning(self) -> None:
        batch = parse_source_payload(
            "world_bank_indicators",
            world_bank_fixture(pages=2, page=1),
            content_type="application/json",
            retrieved_at=RETRIEVED_AT,
            context={
                "request_url": "https://api.worldbank.org/v2/country/USA/indicator/NY.GDP.MKTP.CD?format=json"
            },
        )
        self.assertEqual(batch.record_count, 1)
        self.assertIn("PAGINATION_INCOMPLETE", batch.warnings)
        record = batch.records[0]
        self.assertEqual(record["country_iso3"], "USA")
        self.assertEqual(record["indicator_id"], "NY.GDP.MKTP.CD")
        self.assertEqual(record["period_as_of"], "2025-12-31T00:00:00+00:00")
        evidence = build_evidence_items(batch, registry_version="catalog-v1")
        self.assertEqual(evidence[0]["claim_type"], "official_indicator_value")
        self.assertEqual(evidence[0]["field_values"]["value"], 100.5)

    def test_adapters_fail_closed_on_wrong_types_urls_and_shapes(self) -> None:
        cases = [
            (
                "sec_edgar",
                sec_submissions_fixture(),
                "text/html",
                {"request_url": "https://data.sec.gov/submissions/test.json"},
            ),
            (
                "sec_edgar",
                sec_submissions_fixture(),
                "application/json",
                {"request_url": "http://data.sec.gov/submissions/test.json"},
            ),
            (
                "world_bank_indicators",
                json.dumps({"unexpected": True}).encode(),
                "application/json",
                {"request_url": "https://api.worldbank.org/v2/test"},
            ),
            (
                "world_bank_indicators",
                world_bank_fixture(),
                "application/json",
                {"request_url": "http://api.worldbank.org/v2/test"},
            ),
        ]
        for source_id, content, content_type, context in cases:
            with self.subTest(source_id=source_id, context=context), self.assertRaises(
                AdapterError
            ):
                parse_source_payload(
                    source_id,
                    content,
                    content_type=content_type,
                    retrieved_at=RETRIEVED_AT,
                    context=context,
                )

    def test_sec_rejects_inconsistent_parallel_arrays(self) -> None:
        document = json.loads(sec_submissions_fixture())
        document["filings"]["recent"]["form"].append("8-K")
        with self.assertRaises(AdapterError):
            parse_source_payload(
                "sec_edgar",
                json.dumps(document).encode(),
                content_type="application/json",
                retrieved_at=RETRIEVED_AT,
                context={"request_url": "https://data.sec.gov/submissions/test.json"},
            )

    def test_non_finite_source_values_are_rejected(self) -> None:
        with self.assertRaises(AdapterError):
            parse_source_payload(
                "sec_edgar",
                sec_companyfacts_fixture(math.nan),
                content_type="application/json",
                retrieved_at=RETRIEVED_AT,
                context={
                    "request_url": "https://data.sec.gov/api/xbrl/companyfacts/CIK0000320193.json"
                },
            )

    def test_route_gate_passes_with_reviewed_and_pending_replay_separated(self) -> None:
        findings = audit_adapter_routes()
        self.assertEqual(findings, [])
        summary = audit_adapter_routes.last_summary
        self.assertGreaterEqual(summary["catalog_count"], 90)
        self.assertEqual(summary["reviewed_route_count"], 2)
        self.assertEqual(summary["pending_replay_count"], 2)
        self.assertEqual(summary["static_adapter_count"], 2)
        self.assertEqual(summary["runtime_enabled_count"], 0)

    def test_route_gate_rejects_dynamic_loading_and_unknown_route_fields(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            catalog = {"sources": list(catalog_source_map().values())}
            routes = json.loads(
                (ROOT / "config" / "authoritative-adapter-routes.json").read_text(
                    encoding="utf-8"
                )
            )
            routes["routes"][0]["unexpected_private_selector"] = True
            catalog_path = root / "catalog.json"
            route_path = root / "routes.json"
            registry_path = root / "__init__.py"
            catalog_path.write_text(json.dumps(catalog), encoding="utf-8")
            route_path.write_text(json.dumps(routes), encoding="utf-8")
            registry_path.write_text("import importlib\n", encoding="utf-8")
            findings = audit_adapter_routes(
                catalog_path=catalog_path,
                routes_path=route_path,
                static_registry_path=registry_path,
            )
        self.assertTrue(any("unknown field" in item for item in findings))
        self.assertTrue(any("dynamic code-loading" in item for item in findings))


if __name__ == "__main__":
    unittest.main()
