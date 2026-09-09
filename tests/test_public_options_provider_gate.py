from __future__ import annotations

import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from public_options_provider_gate import audit_public_options_providers  # noqa: E402


class PublicOptionsProviderGateTests(unittest.TestCase):
    def test_rejects_invalid_or_future_review_dates(self) -> None:
        for value in ("2026-02-30", "2026-99-99", "9999-01-01"):
            with self.subTest(value=value):
                temporary, root = self.fixture_root()
                with temporary:
                    path, document = self.read_candidates(root)
                    document["providers"][0]["rights_reviewed_at"] = value
                    self.write_candidates(path, document)
                    findings, _ = audit_public_options_providers(root)
                self.assertTrue(any("requires a review date" in item for item in findings))

    def test_rejects_non_boolean_activation_and_access_flags(self) -> None:
        for field in ("runtime_enabled", "line_quote_eligible", "automated_access_allowed"):
            for value in (0, 1, "false", "true"):
                with self.subTest(field=field, value=value):
                    temporary, root = self.fixture_root()
                    with temporary:
                        path, document = self.read_candidates(root)
                        document["providers"][0][field] = value
                        self.write_candidates(path, document)
                        findings, _ = audit_public_options_providers(root)
                    self.assertTrue(any(field + " must be" in item for item in findings))

    def test_repository_has_reviewed_rejections_but_no_live_provider(self) -> None:
        findings, summary = audit_public_options_providers()
        self.assertEqual(findings, [])
        self.assertGreaterEqual(summary["candidate_count"], 12)
        self.assertGreaterEqual(summary["authority_count"], 10)
        self.assertGreaterEqual(summary["jurisdiction_count"], 6)
        self.assertEqual(summary["automation_prohibited_count"], 4)
        self.assertEqual(summary["pending_rights_count"], 7)
        self.assertEqual(summary["reviewed_public_access_count"], 1)
        self.assertEqual(summary["fully_eligible_count"], 0)
        self.assertEqual(summary["runtime_enabled_count"], 0)
        self.assertEqual(summary["line_quote_eligible_count"], 0)
        self.assertFalse(summary["production_provider_selected"])
        self.assertEqual(
            summary["development_provider"],
            "yfinance_unreviewed_delayed",
        )

    def fixture_root(self) -> tuple[tempfile.TemporaryDirectory[str], Path]:
        temporary = tempfile.TemporaryDirectory()
        root = Path(temporary.name)
        for relative in (
            "config/public-options-provider-candidates.json",
            "config/public-options-development-provider.json",
            "config/runtime-policy.json",
            "cloud/wrangler.toml",
            "scripts/build_line_public_options.py",
        ):
            target = root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(ROOT / relative, target)
        return temporary, root

    @staticmethod
    def read_candidates(root: Path) -> tuple[Path, dict]:
        path = root / "config/public-options-provider-candidates.json"
        return path, json.loads(path.read_text(encoding="utf-8"))

    @staticmethod
    def write_candidates(path: Path, document: dict) -> None:
        path.write_text(
            json.dumps(document, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    def test_rejects_unreviewed_provider_activation(self) -> None:
        temporary, root = self.fixture_root()
        try:
            path, document = self.read_candidates(root)
            pending = document["providers"][2]
            pending["runtime_enabled"] = True
            pending["line_quote_eligible"] = True
            self.write_candidates(path, document)
            findings, _summary = audit_public_options_providers(root)
        finally:
            temporary.cleanup()
        self.assertTrue(any("lacks rights review" in item for item in findings))
        self.assertTrue(any("does not allow automation" in item for item in findings))
        self.assertTrue(any("lacks reviewed adapter" in item for item in findings))

    def test_rejects_partial_activation_and_current_data_switch(self) -> None:
        temporary, root = self.fixture_root()
        try:
            candidates_path, document = self.read_candidates(root)
            document["providers"][2]["runtime_enabled"] = True
            self.write_candidates(candidates_path, document)
            wrangler_path = root / "cloud/wrangler.toml"
            wrangler_path.write_text(
                wrangler_path.read_text(encoding="utf-8").replace(
                    'CURRENT_PUBLIC_DATA_ENABLED = "false"',
                    'CURRENT_PUBLIC_DATA_ENABLED = "true"',
                ),
                encoding="utf-8",
            )
            findings, _summary = audit_public_options_providers(root)
        finally:
            temporary.cleanup()
        self.assertTrue(any("must change atomically" in item for item in findings))
        self.assertTrue(any("CURRENT_PUBLIC_DATA_ENABLED" in item for item in findings))

    def test_rejects_yfinance_production_promotion(self) -> None:
        temporary, root = self.fixture_root()
        try:
            path = root / "config/public-options-development-provider.json"
            document = json.loads(path.read_text(encoding="utf-8"))
            document["production_eligible"] = True
            document["may_be_published_as_current"] = True
            path.write_text(json.dumps(document), encoding="utf-8")
            findings, _summary = audit_public_options_providers(root)
        finally:
            temporary.cleanup()
        self.assertTrue(any("production_eligible" in item for item in findings))
        self.assertTrue(any("may_be_published_as_current" in item for item in findings))

    def test_rejects_broker_or_unsafe_builder_reintroduction(self) -> None:
        temporary, root = self.fixture_root()
        try:
            path = root / "scripts/build_line_public_options.py"
            path.write_text(
                path.read_text(encoding="utf-8")
                + "\nfrom fetch_options_ibkr import fetch_options\n",
                encoding="utf-8",
            )
            findings, _summary = audit_public_options_providers(root)
        finally:
            temporary.cleanup()
        self.assertTrue(any("must not import broker" in item for item in findings))

    def test_pinned_automation_prohibition_cannot_be_overridden(self) -> None:
        temporary, root = self.fixture_root()
        try:
            path, document = self.read_candidates(root)
            provider = document["providers"][0]
            provider["rights_status"] = "reviewed_public_access"
            provider["automated_access_allowed"] = True
            provider["adapter_status"] = "adapter_reviewed"
            provider["runtime_enabled"] = True
            provider["line_quote_eligible"] = True
            self.write_candidates(path, document)
            findings, _summary = audit_public_options_providers(root)
        finally:
            temporary.cleanup()
        self.assertTrue(any("pinned as automation-prohibited" in item for item in findings))
        self.assertTrue(any("cannot allow automated access" in item for item in findings))
        self.assertTrue(any("cannot receive an executable adapter" in item for item in findings))

    def test_shared_redistribution_and_broker_boundaries_are_pinned(self) -> None:
        temporary, root = self.fixture_root()
        try:
            path, document = self.read_candidates(root)
            by_id = {provider["id"]: provider for provider in document["providers"]}
            for provider_id in (
                "marketdata_app_free_forever",
                "tradier_broker_market_data_api",
            ):
                provider = by_id[provider_id]
                provider["rights_status"] = "reviewed_public_access"
                provider["automated_access_allowed"] = True
                provider["adapter_status"] = "adapter_reviewed"
                provider["runtime_enabled"] = True
                provider["line_quote_eligible"] = True
            self.write_candidates(path, document)
            findings, _summary = audit_public_options_providers(root)
        finally:
            temporary.cleanup()
        self.assertGreaterEqual(
            sum("pinned as automation-prohibited" in item for item in findings),
            2,
        )
        self.assertGreaterEqual(
            sum("cannot receive an executable adapter" in item for item in findings),
            2,
        )

    def test_pending_rights_review_must_remain_unknown_and_unactivated(self) -> None:
        temporary, root = self.fixture_root()
        try:
            path, document = self.read_candidates(root)
            provider = next(
                item
                for item in document["providers"]
                if item["rights_status"] == "review_before_enable"
            )
            provider["automated_access_allowed"] = True
            provider["rights_reviewed_at"] = "2026-08-25"
            self.write_candidates(path, document)
            findings, _summary = audit_public_options_providers(root)
        finally:
            temporary.cleanup()
        self.assertTrue(any("requires automated_access_allowed=null" in item for item in findings))
        self.assertTrue(any("requires rights_reviewed_at=null" in item for item in findings))

    def test_prohibited_decision_requires_evidence_and_review_date(self) -> None:
        temporary, root = self.fixture_root()
        try:
            path, document = self.read_candidates(root)
            provider = document["providers"][1]
            provider["rights_evidence_url"] = "http://example.test/terms"
            provider["rights_reviewed_at"] = None
            provider["review_notes"] = ""
            self.write_candidates(path, document)
            findings, _summary = audit_public_options_providers(root)
        finally:
            temporary.cleanup()
        self.assertTrue(any("rights_evidence_url must be safe HTTPS" in item for item in findings))
        self.assertTrue(any("requires a review date" in item for item in findings))
        self.assertTrue(any("review_notes are required" in item for item in findings))


if __name__ == "__main__":
    unittest.main()
