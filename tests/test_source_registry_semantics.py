from __future__ import annotations

import json
import subprocess
import sys
import unittest
from dataclasses import replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from adapters.base import make_batch, schema_fingerprint  # noqa: E402
from source_registry import (  # noqa: E402
    CAPABILITY_STATES,
    DEFAULT_CLAIM_POLICY_PATH,
    DEFAULT_FEDERATION_POLICY_PATH,
    DEFAULT_POLICY_PATH,
    ParsedBatch,
    SourceDefinition,
    SourceRegistryError,
    classify_capability,
    coverage_lanes,
    load_json,
    load_registry,
    qualify_claim_evidence,
    route_claim,
)

CLAIM_POLICY = load_json(DEFAULT_CLAIM_POLICY_PATH)
FEDERATION_POLICY = load_json(DEFAULT_FEDERATION_POLICY_PATH)
REGISTRY = load_registry()
REGISTRY_BY_ID = REGISTRY.by_id()

_OFFICIAL_ID = "us_sec_edgar"
_EXCHANGE_ID = "tw_mops"
_T3_ID = "reuters_public"
_PLANNED_ID = "kr_dart"
_NO_FRESHNESS_ID = "us_sec_freshness_none"

NOW = "2026-09-19T00:00:00Z"
CLAIM = "issuer_financial_statement"
EXPECTED_SUBJECT = {"entity": "ACME", "period": "2026-Q2"}


def _filing_record(value: str = "100", period: str = "2026-Q2", entity: str = "ACME") -> dict[str, object]:
    return {
        "entity": entity,
        "period": period,
        "currency": "USD",
        "value": value,
        "filing_identifier": "F-001",
    }


def _make_source(**overrides: object) -> SourceDefinition:
    base: dict[str, object] = {
        "source_id": "fixture_source",
        "display_name": "Fixture Source",
        "authority_class": "securities_regulator",
        "trust_tier": "T1_PRIMARY_OFFICIAL",
        "evidence_roles": ("issuer_filings",),
        "jurisdictions": ("US",),
        "languages": ("en",),
        "canonical_urls": ("https://example.invalid/registry",),
        "independence_group": "fixture_group",
        "admission_status": "IDENTITY_VERIFIED",
        "adapter_id": "fixture_source",
        "adapter_status": "implemented",
        "runtime_enabled": False,
        "free_access_required": True,
        "payment_required": False,
        "terms_review_status": "approved",
        "priority": 100,
        "per_host_concurrency": 2,
        "minimum_request_interval_seconds": 0.0,
        "maximum_retries": 3,
        "freshness_seconds": 3600,
        "correction_tracking": True,
        "provenance_required": True,
        "notes": "fixture",
        "catalog_file": "fixture",
    }
    base.update(overrides)
    return SourceDefinition(**base)  # type: ignore[arg-type]


class QualifyClaimEvidenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        import tempfile

        scratch_root = ROOT / ".tmp"
        scratch_root.mkdir(parents=True, exist_ok=True)
        cls._tmp = tempfile.TemporaryDirectory(
            prefix="source-registry-semantics-", dir=scratch_root
        )
        cls.addClassCleanup(cls._tmp.cleanup)
        root = Path(cls._tmp.name)
        src = root / "src"
        src.mkdir()
        wanted = {_OFFICIAL_ID, _EXCHANGE_ID, _T3_ID, _PLANNED_ID}
        raw_by_id: dict[str, dict[str, object]] = {}
        for catalog_path in (ROOT / "config" / "sources").glob("*.json"):
            document = load_json(catalog_path)
            for raw in document.get("sources", []):
                if raw.get("source_id") in wanted:
                    raw_by_id[str(raw["source_id"])] = raw
        records = []
        for source_id in (_OFFICIAL_ID, _EXCHANGE_ID, _T3_ID, _PLANNED_ID):
            record = json.loads(json.dumps(raw_by_id[source_id]))
            if source_id == _PLANNED_ID:
                # Disabled + planned adapter: the unavailable/diagnostic case.
                record["runtime"]["enabled"] = False  # type: ignore[index]
                record["adapter"]["status"] = "planned"  # type: ignore[index]
                record["runtime"]["freshness_seconds"] = None  # type: ignore[index]
                records.append(record)
                continue
            record["runtime"]["enabled"] = True  # type: ignore[index]
            record["admission_status"] = "RUNTIME_ENABLED"
            record["adapter"]["status"] = "implemented"  # type: ignore[index]
            record["access"]["terms_review_status"] = "approved"  # type: ignore[index]
            if source_id == _T3_ID:
                record["evidence_roles"] = ["issuer_filings", "financial_news_lead"]
            records.append(record)
        # Fifth source: enabled + implemented but with no catalog freshness
        # bound (to prove an absent TTL bound is refused, not unlimited).
        no_freshness = json.loads(json.dumps(raw_by_id[_OFFICIAL_ID]))
        no_freshness["source_id"] = _NO_FRESHNESS_ID
        no_freshness["independence_group"] = _NO_FRESHNESS_ID
        no_freshness["adapter"]["id"] = _NO_FRESHNESS_ID  # type: ignore[index]
        no_freshness["runtime"]["enabled"] = True  # type: ignore[index]
        no_freshness["admission_status"] = "RUNTIME_ENABLED"
        no_freshness["adapter"]["status"] = "implemented"  # type: ignore[index]
        no_freshness["access"]["terms_review_status"] = "approved"  # type: ignore[index]
        no_freshness["runtime"]["freshness_seconds"] = None  # type: ignore[index]
        records.append(no_freshness)
        (src / "fixture-catalog.json").write_text(
            json.dumps({"schema_version": 1, "sources": records}, ensure_ascii=False),
            encoding="utf-8",
        )
        policy_path = root / "registry-policy.json"
        policy_path.write_bytes(DEFAULT_POLICY_PATH.read_bytes())
        cls.registry = load_registry(src, policy_path)
        cls.registry_by_id = cls.registry.by_id()
        claim_policy = json.loads(json.dumps(CLAIM_POLICY))
        # Add the T3 source's actual authority class as a candidate so the
        # tests can prove T3 candidates never count as primary.
        claim_policy["claim_family_semantics"][CLAIM]["authority_classes"].append(
            REGISTRY_BY_ID[_T3_ID].authority_class
        )
        claim_policy["claim_family_semantics"]["blank_descriptor_family"] = {
            "authority_classes": [],
            "evidence_roles": [],
            "fallback_sources": [],
        }
        claim_policy["claim_families"]["blank_descriptor_family"] = {
            "minimum_primary_sources": 1,
            "minimum_independent_groups": 1,
            "required_fields": ["period"],
        }
        cls.claim_policy = claim_policy

    def _group(self, source_id: str) -> str:
        return self.registry_by_id[source_id].independence_group

    def _batch(self, source_id: str, records: list[dict[str, object]], content: bytes) -> ParsedBatch:
        return make_batch(  # type: ignore[return-value]
            source_id=source_id,
            parser_version="test-1",
            content=content,
            retrieved_at=NOW,
            records=records,
        )

    def _observation(
        self,
        source_id: str,
        *,
        content: bytes,
        disclosure_id: str,
        declared_access: str = "free",
        observed_health: str | None = None,
        as_of: str = NOW,
        subject: dict[str, object] | None = None,
        http_status: object = 200,
        group: str | None = None,
        fetch_source: str | None = None,
        path: str | None = None,
        include_lineage: bool = True,
        records: list[dict[str, object]] | None = None,
    ) -> dict[str, object]:
        observation: dict[str, object] = {
            "parsed_batch": self._batch(source_id, records or [_filing_record()], content),
            "as_of": as_of,
            "http_status": http_status,
            "declared_access": declared_access,
            "observed_health": observed_health,
            "subject": subject if subject is not None else dict(EXPECTED_SUBJECT),
        }
        if include_lineage:
            observation["data_origin_lineage"] = {
                "publisher_identity": source_id,
                "independence_group": group if group is not None else self._group(source_id),
                "original_disclosure_id": disclosure_id,
            }
            observation["transport_lineage"] = {
                "fetch_source": fetch_source if fetch_source is not None else source_id,
                "path": path if path is not None else f"https://{source_id}.invalid/filings/{disclosure_id}",
            }
        return observation

    def _qualify(
        self,
        observations: list[dict[str, object]],
        *,
        expected_subject: dict[str, object] | None = EXPECTED_SUBJECT,
        federation_policy: object = FEDERATION_POLICY,
        claim_policy: object | None = None,
    ) -> dict[str, object]:
        kwargs: dict[str, object] = {
            "now": NOW,
            "federation_policy": federation_policy,
        }
        if expected_subject is not None:
            kwargs["expected_subject"] = expected_subject
        return qualify_claim_evidence(
            self.registry,
            CLAIM,
            claim_policy if claim_policy is not None else self.claim_policy,
            observations,
            **kwargs,  # type: ignore[arg-type]
        )

    # --- existing user minimums (strict schema) ---

    def test_official_plus_independent_exchange_is_two_origins(self) -> None:
        result = self._qualify(
            [
                self._observation(_OFFICIAL_ID, content=b"official-bytes", disclosure_id="SEC-F-001"),
                self._observation(_EXCHANGE_ID, content=b"exchange-bytes", disclosure_id="MOPS-F-001"),
            ]
        )
        self.assertTrue(result["qualified"])
        self.assertEqual(result["valid_origins"], 2)
        self.assertEqual(result["independent_groups"], 2)
        self.assertFalse(result["publication_eligible"])

    def test_mirrors_count_as_one_origin(self) -> None:
        same_publisher = self._qualify(
            [
                self._observation(_OFFICIAL_ID, content=b"official-bytes", disclosure_id="SEC-F-001"),
                self._observation(_OFFICIAL_ID, content=b"official-bytes", disclosure_id="SEC-F-001"),
            ]
        )
        self.assertEqual(same_publisher["valid_origins"], 1)
        self.assertEqual(same_publisher["independent_groups"], 1)
        same_content = self._qualify(
            [
                self._observation(_OFFICIAL_ID, content=b"identical-bytes", disclosure_id="SEC-A"),
                self._observation(_OFFICIAL_ID, content=b"identical-bytes", disclosure_id="SEC-B"),
            ]
        )
        self.assertEqual(same_content["valid_origins"], 1)

    def test_unavailable_sources_do_not_block_healthy_lane(self) -> None:
        result = self._qualify(
            [
                self._observation(_OFFICIAL_ID, content=b"official-bytes", disclosure_id="SEC-F-001"),
                self._observation(_EXCHANGE_ID, content=b"exchange-bytes", disclosure_id="MOPS-F-001"),
                self._observation(
                    _OFFICIAL_ID,
                    content=b"rate-limited-bytes",
                    disclosure_id="SEC-F-002",
                    observed_health="http_429",
                ),
                self._observation(
                    _EXCHANGE_ID,
                    content=b"auth-bytes",
                    disclosure_id="MOPS-F-002",
                    declared_access="auth",
                ),
                self._observation(
                    _OFFICIAL_ID,
                    content=b"premium-bytes",
                    disclosure_id="SEC-F-003",
                    declared_access="premium",
                ),
            ]
        )
        self.assertTrue(result["qualified"])
        self.assertEqual(result["valid_origins"], 2)
        self.assertEqual(len(result["rejected"]), 3)

    def test_stale_future_wrong_subject_and_missing_lineage_fail(self) -> None:
        stale = self._qualify(
            [
                self._observation(
                    _OFFICIAL_ID,
                    content=b"stale-bytes",
                    disclosure_id="SEC-F-001",
                    as_of="2026-09-01T00:00:00Z",
                ),
            ]
        )
        self.assertFalse(stale["qualified"])
        self.assertTrue(any("stale" in e["reason"] for e in stale["rejected"]))

        future = self._qualify(
            [
                self._observation(
                    _OFFICIAL_ID,
                    content=b"future-bytes",
                    disclosure_id="SEC-F-001",
                    as_of="2026-09-20T00:00:00Z",
                ),
            ]
        )
        self.assertFalse(future["qualified"])
        self.assertTrue(any("future" in e["reason"] for e in future["rejected"]))

        wrong_subject = self._qualify(
            [
                self._observation(
                    _OFFICIAL_ID,
                    content=b"entity-bytes",
                    disclosure_id="SEC-F-001",
                    subject={"entity": "OTHER", "period": "2026-Q2"},
                ),
            ]
        )
        self.assertFalse(wrong_subject["qualified"])
        self.assertTrue(any("subject" in e["reason"] for e in wrong_subject["rejected"]))

        missing_lineage = self._qualify(
            [
                self._observation(
                    _OFFICIAL_ID,
                    content=b"lineage-bytes",
                    disclosure_id="SEC-F-001",
                    include_lineage=False,
                ),
            ]
        )
        self.assertFalse(missing_lineage["qualified"])
        self.assertTrue(any("lineage" in e["reason"] for e in missing_lineage["rejected"]))

    def test_registration_alone_never_qualifies(self) -> None:
        result = self._qualify([])
        self.assertFalse(result["qualified"])
        self.assertEqual(result["valid_origins"], 0)
        self.assertFalse(result["publication_eligible"])

    def test_material_conflict_is_not_rescued_by_counts(self) -> None:
        result = self._qualify(
            [
                self._observation(_OFFICIAL_ID, content=b"official-bytes", disclosure_id="SEC-F-001"),
                self._observation(
                    _EXCHANGE_ID,
                    content=b"conflict-bytes",
                    disclosure_id="MOPS-F-001",
                    records=[_filing_record(value="999")],
                ),
            ]
        )
        self.assertFalse(result["qualified"])
        self.assertTrue(result["material_conflict"])

    # --- round-1 defect negatives (one per reported defect) ---

    def test_defect1_disabled_runtime_and_t3_and_non_candidate_do_not_qualify(self) -> None:
        # Disabled runtime source must never qualify.
        disabled = self._observation(_PLANNED_ID, content=b"planned-bytes", disclosure_id="KR-F-001")
        result = self._qualify([disabled])
        self.assertFalse(result["qualified"])
        self.assertTrue(any("runtime" in e["reason"] for e in result["rejected"]))
        # T3 media is a candidate but never counts as primary.
        t3 = self._qualify(
            [
                self._observation(_T3_ID, content=b"t3-bytes", disclosure_id="RE-F-001"),
            ]
        )
        self.assertFalse(t3["qualified"])
        self.assertEqual(t3.get("primary_origins", 0), 0)

    def test_defect2_hashes_recomputed_and_strict_types(self) -> None:
        good = self._observation(_OFFICIAL_ID, content=b"hash-bytes", disclosure_id="SEC-F-001")
        batch = good["parsed_batch"]
        # Non-64-hex content hash.
        bad_hash = self._observation(_OFFICIAL_ID, content=b"hash-bytes", disclosure_id="SEC-F-001")
        bad_hash["parsed_batch"] = replace(batch, content_sha256="not-a-hash")
        result = self._qualify([bad_hash])
        self.assertFalse(result["qualified"])
        self.assertTrue(any("content" in e["reason"] for e in result["rejected"]))
        # Stale schema fingerprint must be recomputed and rejected.
        bad_schema = self._observation(_OFFICIAL_ID, content=b"hash-bytes", disclosure_id="SEC-F-001")
        bad_schema["parsed_batch"] = replace(batch, schema_sha256="0" * 64)
        result = self._qualify([bad_schema])
        self.assertFalse(result["qualified"])
        self.assertTrue(any("schema" in e["reason"] for e in result["rejected"]))
        # record_count as bool / records as list are rejected.
        bad_count = self._observation(_OFFICIAL_ID, content=b"hash-bytes", disclosure_id="SEC-F-001")
        bad_count["parsed_batch"] = replace(batch, record_count=True)  # type: ignore[arg-type]
        result = self._qualify([bad_count])
        self.assertFalse(result["qualified"])
        bad_records = self._observation(_OFFICIAL_ID, content=b"hash-bytes", disclosure_id="SEC-F-001")
        bad_records["parsed_batch"] = replace(batch, records=list(batch.records))  # type: ignore[arg-type]
        result = self._qualify([bad_records])
        self.assertFalse(result["qualified"])
        # bool True is explicitly NOT an actual HTTP 200.
        bool_status = self._observation(_OFFICIAL_ID, content=b"hash-bytes", disclosure_id="SEC-F-001")
        bool_status["http_status"] = True
        result = self._qualify([bool_status])
        self.assertFalse(result["qualified"])
        self.assertTrue(any("HTTP 200" in e["reason"] for e in result["rejected"]))

    def test_defect3_retrieved_at_clock_and_ttl_bounds(self) -> None:
        # batch.retrieved_at stale while as_of fresh.
        observation = self._observation(_OFFICIAL_ID, content=b"clock-bytes", disclosure_id="SEC-F-001")
        observation["parsed_batch"] = make_batch(  # type: ignore[assignment]
            source_id=_OFFICIAL_ID,
            parser_version="test-1",
            content=b"clock-bytes",
            retrieved_at="2026-09-01T00:00:00Z",
            records=[_filing_record()],
        )
        result = self._qualify([observation])
        self.assertFalse(result["qualified"])
        self.assertTrue(any("retrieved" in e["reason"] or "stale" in e["reason"] for e in result["rejected"]))
        # No applicable TTL bound (source freshness None, no federation policy) must refuse.
        no_bound = self._observation(_NO_FRESHNESS_ID, content=b"nobound-bytes", disclosure_id="NF-F-001")
        result = self._qualify([no_bound], federation_policy=None)
        self.assertFalse(result["qualified"])
        self.assertTrue(any("TTL" in e["reason"] or "bound" in e["reason"] for e in result["rejected"]))

    def test_defect4_subject_binding_mandatory_from_records_and_envelope(self) -> None:
        # Missing expected_subject must raise (no silent optional binding).
        with self.assertRaises(SourceRegistryError):
            self._qualify(
                [self._observation(_OFFICIAL_ID, content=b"subj-bytes", disclosure_id="SEC-F-001")],
                expected_subject=None,
            )
        # Envelope subject missing a required identity key.
        missing_key = self._qualify(
            [
                self._observation(
                    _OFFICIAL_ID,
                    content=b"subj-bytes",
                    disclosure_id="SEC-F-001",
                    subject={"entity": "ACME"},
                ),
            ]
        )
        self.assertFalse(missing_key["qualified"])
        # Record period differs from expected period.
        record_mismatch = self._qualify(
            [
                self._observation(
                    _OFFICIAL_ID,
                    content=b"subj-bytes",
                    disclosure_id="SEC-F-001",
                    records=[_filing_record(period="2025-Q4")],
                ),
            ]
        )
        self.assertFalse(record_mismatch["qualified"])
        self.assertTrue(any("subject" in e["reason"] or "period" in e["reason"] for e in record_mismatch["rejected"]))

    def test_defect5_origin_publisher_and_group_exact_no_group_only_fallback(self) -> None:
        # Group-only fallback (unregistered publisher, existing group) must reject.
        group_only = self._observation(
            _OFFICIAL_ID,
            content=b"origin-bytes",
            disclosure_id="SEC-F-001",
        )
        group_only["data_origin_lineage"]["publisher_identity"] = "unregistered_publisher"  # type: ignore[index]
        result = self._qualify([group_only])
        self.assertFalse(result["qualified"])
        self.assertTrue(any("match" in e["reason"] or "registered" in e["reason"] for e in result["rejected"]))
        # Publisher/group contradiction must reject.
        contradictory = self._observation(
            _OFFICIAL_ID,
            content=b"origin-bytes",
            disclosure_id="SEC-F-001",
            group=self._group(_EXCHANGE_ID),
        )
        result = self._qualify([contradictory])
        self.assertFalse(result["qualified"])
        self.assertTrue(any("group" in e["reason"] for e in result["rejected"]))

    def test_defect6_lineage_names_and_transport_required(self) -> None:
        # Legacy 'origin' key is not the required data_origin_lineage name.
        legacy = self._observation(
            _OFFICIAL_ID, content=b"lineage-bytes", disclosure_id="SEC-F-001", include_lineage=False
        )
        legacy["origin"] = {
            "publisher_identity": _OFFICIAL_ID,
            "independence_group": self._group(_OFFICIAL_ID),
            "original_disclosure_id": "SEC-F-001",
        }
        result = self._qualify([legacy])
        self.assertFalse(result["qualified"])
        self.assertTrue(any("lineage" in e["reason"] for e in result["rejected"]))
        # Transport fetch_source must match the batch source.
        wrong_fetch = self._observation(
            _OFFICIAL_ID,
            content=b"lineage-bytes",
            disclosure_id="SEC-F-001",
            fetch_source=_EXCHANGE_ID,
        )
        result = self._qualify([wrong_fetch])
        self.assertFalse(result["qualified"])
        # Non-HTTPS transport path must reject.
        bad_path = self._observation(
            _OFFICIAL_ID,
            content=b"lineage-bytes",
            disclosure_id="SEC-F-001",
            path="ftp://insecure.invalid/filings/SEC-F-001",
        )
        result = self._qualify([bad_path])
        self.assertFalse(result["qualified"])

    def test_defect7_mirror_equivalence_union_order_independent(self) -> None:
        # Different publishers sharing one LOCAL disclosure id are independent
        # origins (disclosure ids are publisher-qualified, never cross-publisher).
        shared_id = self._qualify(
            [
                self._observation(_OFFICIAL_ID, content=b"pub-a-bytes", disclosure_id="GENERIC-1"),
                self._observation(_EXCHANGE_ID, content=b"pub-b-bytes", disclosure_id="GENERIC-1"),
            ]
        )
        self.assertEqual(shared_id["valid_origins"], 2)
        # Same publisher with multiple ids is one origin.
        multi_id = self._qualify(
            [
                self._observation(_OFFICIAL_ID, content=b"pub-a-bytes", disclosure_id="SEC-A"),
                self._observation(_OFFICIAL_ID, content=b"pub-a-2-bytes", disclosure_id="SEC-B"),
            ]
        )
        self.assertEqual(multi_id["valid_origins"], 1)
        # Order independence.
        first = self._qualify(
            [
                self._observation(_OFFICIAL_ID, content=b"order-a-bytes", disclosure_id="SEC-A"),
                self._observation(_EXCHANGE_ID, content=b"order-b-bytes", disclosure_id="MOPS-B"),
            ]
        )
        second = self._qualify(
            [
                self._observation(_EXCHANGE_ID, content=b"order-b-bytes", disclosure_id="MOPS-B"),
                self._observation(_OFFICIAL_ID, content=b"order-a-bytes", disclosure_id="SEC-A"),
            ]
        )
        self.assertEqual(first["valid_origins"], second["valid_origins"])
        self.assertEqual(first["independent_groups"], second["independent_groups"])

    # --- round-2 executable counterexample regressions ---

    def test_defectA_minima_use_mirror_collapsed_classes_not_raw_groups(self) -> None:
        policy = json.loads(json.dumps(self.claim_policy))
        policy["claim_families"][CLAIM]["minimum_independent_groups"] = 2
        result = self._qualify(
            [
                self._observation(_OFFICIAL_ID, content=b"same-bytes", disclosure_id="SEC-F-001"),
                self._observation(_EXCHANGE_ID, content=b"same-bytes", disclosure_id="MOPS-F-001"),
            ],
            claim_policy=policy,
        )
        self.assertFalse(result["qualified"])
        self.assertFalse(result["evidence_qualified"])
        self.assertEqual(result["valid_origins"], 1)
        self.assertEqual(result["independent_groups"], 1)

    def test_defectB_disclosure_id_is_publisher_qualified(self) -> None:
        result = self._qualify(
            [
                self._observation(_OFFICIAL_ID, content=b"payload-a-bytes", disclosure_id="D"),
                self._observation(_EXCHANGE_ID, content=b"payload-b-bytes", disclosure_id="D"),
            ]
        )
        self.assertTrue(result["qualified"])
        self.assertEqual(result["valid_origins"], 2)
        self.assertEqual(result["independent_groups"], 2)

    def test_defectC_record_loop_resets_per_observation_no_unbound(self) -> None:
        # First record missing a required field: rejected, no crash.
        first_bad = self._qualify(
            [
                self._observation(
                    _OFFICIAL_ID,
                    content=b"rec-a-bytes",
                    disclosure_id="SEC-F-001",
                    records=[
                        {"entity": "ACME", "period": "2026-Q2", "value": "100", "filing_identifier": "F-1"},
                        _filing_record(),
                    ],
                ),
            ]
        )
        self.assertFalse(first_bad["qualified"])
        self.assertTrue(any("currency" in e["reason"] for e in first_bad["rejected"]))
        # A valid first record must not mask a bad second record.
        second_bad = self._qualify(
            [
                self._observation(
                    _OFFICIAL_ID,
                    content=b"rec-b-bytes",
                    disclosure_id="SEC-F-001",
                    records=[
                        _filing_record(),
                        {"entity": "ACME", "period": "2026-Q2", "value": "100", "filing_identifier": "F-2"},
                    ],
                ),
            ]
        )
        self.assertFalse(second_bad["qualified"])
        self.assertTrue(any("currency" in e["reason"] for e in second_bad["rejected"]))

    def test_defectD_primary_authority_comes_from_origin_not_transport(self) -> None:
        # Batch from the T1 official, but origin re-attributed to a registered
        # T3 publisher (matching T3 group): must reject, not count as primary.
        t3_group = self._group(_T3_ID)
        observation = self._observation(
            _OFFICIAL_ID, content=b"origin-bytes", disclosure_id="SEC-F-001"
        )
        observation["data_origin_lineage"] = {  # type: ignore[index]
            "publisher_identity": _T3_ID,
            "independence_group": t3_group,
            "original_disclosure_id": "SEC-F-001",
        }
        result = self._qualify([observation])
        self.assertFalse(result["qualified"])
        self.assertEqual(result["primary_origins"], 0)
        self.assertTrue(any("match" in e["reason"] for e in result["rejected"]))

    def test_defectE_transport_path_requires_canonical_host_bound_https(self) -> None:
        for bad_path in ("https://", "https://user:pass@host.invalid/x", "http://host.invalid/x"):
            observation = self._observation(
                _OFFICIAL_ID,
                content=b"path-bytes",
                disclosure_id="SEC-F-001",
                path=bad_path,
            )
            result = self._qualify([observation])
            self.assertFalse(result["qualified"], bad_path)
            self.assertTrue(any("HTTPS" in e["reason"] or "URL" in e["reason"] for e in result["rejected"]), bad_path)
        good = self._qualify(
            [
                self._observation(
                    _OFFICIAL_ID,
                    content=b"path-bytes",
                    disclosure_id="SEC-F-001",
                    path="https://host.invalid/filings/SEC-F-001",
                ),
            ]
        )
        self.assertTrue(good["qualified"])

    def test_defectF_conflict_not_masked_by_shared_value(self) -> None:
        result = self._qualify(
            [
                self._observation(
                    _OFFICIAL_ID,
                    content=b"multi-bytes",
                    disclosure_id="SEC-F-001",
                    records=[_filing_record(value="100"), _filing_record(value="200")],
                ),
                self._observation(
                    _EXCHANGE_ID,
                    content=b"single-bytes",
                    disclosure_id="MOPS-F-001",
                    records=[_filing_record(value="100")],
                ),
            ]
        )
        self.assertFalse(result["qualified"])
        self.assertTrue(result["material_conflict"])

    def test_route_capability_facts_refine_fallback_without_bypass(self) -> None:
        baseline = route_claim(
            self.registry,
            CLAIM,
            self.claim_policy,
            runtime_only=False,
            federation_policy=FEDERATION_POLICY,
        )
        self.assertIn(_OFFICIAL_ID, baseline["fallback_chain"]["source_ids"])
        result = route_claim(
            self.registry,
            CLAIM,
            self.claim_policy,
            runtime_only=False,
            federation_policy=FEDERATION_POLICY,
            capability_facts={
                _OFFICIAL_ID: {"observed_health": "http_429"},
                _T3_ID: {"declared_access": "premium"},
            },
        )
        fallback = result["fallback_chain"]
        self.assertEqual(fallback["unavailable_diagnostics"].get(_OFFICIAL_ID), "RATE_LIMITED")
        self.assertEqual(fallback["unavailable_diagnostics"].get(_T3_ID), "PREMIUM_ONLY")
        self.assertNotIn(_OFFICIAL_ID, fallback["source_ids"])
        self.assertNotIn(_T3_ID, fallback["source_ids"])
        # Healthy candidates remain in the fallback.
        self.assertIn(_EXCHANGE_ID, fallback["source_ids"])
        # String-state bypass is rejected by the same strict classifier.
        with self.assertRaises(SourceRegistryError):
            route_claim(
                self.registry,
                CLAIM,
                self.claim_policy,
                runtime_only=False,
                federation_policy=FEDERATION_POLICY,
                capability_facts={_OFFICIAL_ID: {"observed_health": "definitely_fine"}},
            )

    def test_subject_binding_fields_mandatory_per_family(self) -> None:
        with self.assertRaises(SourceRegistryError):
            self._qualify(
                [self._observation(_OFFICIAL_ID, content=b"bind-bytes", disclosure_id="SEC-F-001")],
                expected_subject={"foo": "bar"},
            )

    def test_minima_validation_centralized_fail_closed(self) -> None:
        # Table-driven: permissive/invalid minima fail closed in BOTH route and
        # qualify (0, -1, True, 1.5, missing).
        for bad in (0, -1, True, 1.5, None):
            policy = json.loads(json.dumps(self.claim_policy))
            family = policy["claim_families"][CLAIM]
            if bad is None:
                family.pop("minimum_primary_sources")
            else:
                family["minimum_primary_sources"] = bad
            with self.assertRaises(SourceRegistryError):
                route_claim(
                    self.registry, CLAIM, policy, federation_policy=FEDERATION_POLICY
                )
            with self.assertRaises(SourceRegistryError):
                self._qualify([], claim_policy=policy)
        # Valid min 1 + empty evidence denies (nonempty fully-valid invariant).
        result = self._qualify([])
        self.assertFalse(result["qualified"])
        self.assertFalse(result["evidence_qualified"])
        self.assertEqual(result["valid_origins"], 0)

    def test_defect8_conflict_disjoint_values_across_independent_groups(self) -> None:
        # Two origins, one differing value each, no shared value: conflict.
        result = self._qualify(
            [
                self._observation(
                    _OFFICIAL_ID,
                    content=b"conflict-a-bytes",
                    disclosure_id="SEC-F-001",
                    records=[_filing_record(value="100")],
                ),
                self._observation(
                    _EXCHANGE_ID,
                    content=b"conflict-b-bytes",
                    disclosure_id="MOPS-F-001",
                    records=[_filing_record(value="200")],
                ),
            ]
        )
        self.assertFalse(result["qualified"])
        self.assertTrue(result["material_conflict"])

    def test_defect9_route_fallback_derived_unavailable_excluded_blank_descriptor_fails(self) -> None:
        envelope = route_claim(
            self.registry,
            CLAIM,
            self.claim_policy,
            runtime_only=False,
            federation_policy=FEDERATION_POLICY,
        )
        fallback = envelope["fallback_chain"]
        self.assertIn("source_ids", fallback)
        self.assertIn("unavailable_diagnostics", fallback)
        # Fallback derives from healthy route candidates in authority order.
        candidates = envelope["candidate_sources"]
        self.assertEqual(
            fallback["source_ids"],
            [c for c in candidates if c not in fallback["unavailable_diagnostics"]],
        )
        # The planned-adapter source is unavailable and excluded.
        self.assertIn(_PLANNED_ID, fallback["unavailable_diagnostics"])
        self.assertNotIn(_PLANNED_ID, fallback["source_ids"])
        # Blank descriptor filters must fail closed, not match all sources.
        with self.assertRaises(SourceRegistryError):
            route_claim(
                self.registry,
                "blank_descriptor_family",
                self.claim_policy,
                federation_policy=FEDERATION_POLICY,
            )


class CapabilityClassifierTests(unittest.TestCase):
    def test_exact_eight_states(self) -> None:
        free = _make_source()
        self.assertEqual(classify_capability(free), "PUBLIC")
        self.assertEqual(classify_capability(_make_source(per_host_concurrency=1)), "PUBLIC_LIMITED")
        self.assertEqual(classify_capability(free, declared_access="key"), "OPTIONAL_KEY")
        self.assertEqual(classify_capability(free, declared_access="auth"), "AUTH_REQUIRED")
        self.assertEqual(classify_capability(_make_source(payment_required=True)), "PREMIUM_ONLY")
        self.assertEqual(classify_capability(free, observed_health="http_429"), "RATE_LIMITED")
        self.assertEqual(
            classify_capability(free, observed_health="transport_failure"), "TEMP_UNAVAILABLE"
        )
        self.assertEqual(classify_capability(_make_source(adapter_status="planned")), "UNSUPPORTED")
        self.assertEqual(len(CAPABILITY_STATES), 8)

    def test_free_access_flag_is_not_auth_evidence_and_budgets_are_not_429(self) -> None:
        self.assertEqual(classify_capability(_make_source(free_access_required=True)), "PUBLIC")
        self.assertEqual(
            classify_capability(_make_source(per_host_concurrency=1)), "PUBLIC_LIMITED"
        )

    def test_forbidden_never_downgrades_to_public(self) -> None:
        self.assertEqual(
            classify_capability(_make_source(), observed_health="forbidden"), "AUTH_REQUIRED"
        )
        self.assertEqual(
            classify_capability(_make_source(), observed_health="payment_prompted"), "PREMIUM_ONLY"
        )

    def test_malformed_states_fail_closed(self) -> None:
        with self.assertRaises(SourceRegistryError):
            classify_capability(_make_source(), declared_access="FREE")
        with self.assertRaises(SourceRegistryError):
            classify_capability(_make_source(), observed_health="timeout")


class RouteClaimTests(unittest.TestCase):
    def test_all_ten_claim_kinds_yield_full_envelopes(self) -> None:
        for claim_kind in sorted(CLAIM_POLICY["claim_families"]):
            envelope = route_claim(
                REGISTRY, claim_kind, CLAIM_POLICY, federation_policy=FEDERATION_POLICY
            )
            for key in (
                "claim_kind",
                "candidate_sources",
                "authority_order",
                "freshness_requirement",
                "minimum_lineages",
                "fallback_chain",
            ):
                self.assertIn(key, envelope)
            self.assertEqual(envelope["claim_kind"], claim_kind)
            ceiling = envelope["freshness_requirement"]["activation_gate_ceiling_seconds"]
            ttl = envelope["freshness_requirement"]["retrieval_max_age_seconds"]
            if ceiling is not None and ttl is not None:
                self.assertLessEqual(ttl, ceiling)

    def test_unknown_claim_kind_fails_closed(self) -> None:
        with self.assertRaises(SourceRegistryError):
            route_claim(REGISTRY, "not_a_claim", CLAIM_POLICY)

    def test_mirror_or_irrelevant_sources_cannot_change_ranking_or_admission(self) -> None:
        base = route_claim(
            REGISTRY, "issuer_financial_statement", CLAIM_POLICY, runtime_only=False
        )
        again = route_claim(
            REGISTRY, "issuer_financial_statement", CLAIM_POLICY, runtime_only=False
        )
        self.assertEqual(base["authority_order"], again["authority_order"])
        trust_rank = {
            "T1_PRIMARY_OFFICIAL": 1,
            "T2_INSTITUTIONAL_CORROBORATION": 2,
            "T3_REPUTABLE_SECONDARY_LEAD": 3,
        }
        for left, right in zip(base["authority_order"], base["authority_order"][1:]):
            l, r = REGISTRY_BY_ID[left], REGISTRY_BY_ID[right]
            self.assertLessEqual(
                (trust_rank[l.trust_tier], -l.priority, l.source_id),
                (trust_rank[r.trust_tier], -r.priority, r.source_id),
            )
        for source_id in base["authority_order"]:
            self.assertIn(
                REGISTRY_BY_ID[source_id].admission_status,
                ("DISCOVERED", "IDENTITY_VERIFIED", "RUNTIME_ENABLED"),
            )


class CoverageLaneTests(unittest.TestCase):
    def test_nine_lanes_and_explicit_missing_clearing(self) -> None:
        lanes = coverage_lanes(REGISTRY, CLAIM_POLICY)
        self.assertEqual(
            sorted(lanes),
            [
                "centralBank",
                "clearing",
                "exchange",
                "governmentStatistics",
                "international",
                "issuerIR",
                "majorFinancialMedia",
                "regulator",
                "reputableMarketData",
            ],
        )
        self.assertTrue(lanes["clearing"]["explicit_missing"])
        self.assertFalse(lanes["clearing"]["present"])
        self.assertEqual(lanes["clearing"]["source_count"], 0)
        for lane in ("regulator", "exchange", "centralBank", "international"):
            self.assertTrue(lanes[lane]["present"])
            self.assertGreater(lanes[lane]["source_count"], 0)


class SemanticCliTests(unittest.TestCase):
    SCRIPT = ROOT / "scripts" / "source_registry.py"

    def _run(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(self.SCRIPT), *args],
            capture_output=True,
            text=True,
            timeout=120,
        )

    def test_route_cli_yields_envelope_and_preserves_legacy_commands(self) -> None:
        route = self._run("route", "--claim-kind", "macro_indicator")
        self.assertEqual(route.returncode, 0)
        envelope = json.loads(route.stdout)
        self.assertEqual(envelope["claim_kind"], "macro_indicator")
        self.assertIn("authority_order", envelope)
        self.assertIn("fallback_chain", envelope)

        legacy_coverage = self._run("coverage")
        self.assertEqual(legacy_coverage.returncode, 0)
        ledger = json.loads(legacy_coverage.stdout)
        self.assertNotIn("lanes", ledger)

        lanes = self._run("coverage", "--lanes")
        self.assertEqual(lanes.returncode, 0)
        document = json.loads(lanes.stdout)
        self.assertIn("ledger", document)
        self.assertIn("lanes", document)
        self.assertTrue(document["lanes"]["clearing"]["explicit_missing"])

    def test_route_cli_unknown_claim_fails_closed(self) -> None:
        result = self._run("route", "--claim-kind", "not_a_claim")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("SOURCE_REGISTRY_INVALID", result.stdout)
        with self.assertRaises(ValueError):
            json.loads(result.stdout)


if __name__ == "__main__":
    unittest.main()