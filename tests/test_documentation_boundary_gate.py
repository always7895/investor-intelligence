from __future__ import annotations

import copy
import importlib.util
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load_gate():
    path = ROOT / "scripts" / "documentation_boundary_gate.py"
    spec = importlib.util.spec_from_file_location("documentation_boundary_gate", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("Unable to load documentation boundary gate")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class DocumentationBoundaryGateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.gate = load_gate()
        self.documents = self.gate.load_documents(ROOT)
        self.runtime = self.gate.load_runtime(ROOT)
        self.workflows = self.gate.load_workflows(ROOT)

    def test_current_repository_passes_documentation_boundary(self) -> None:
        self.assertEqual(self.gate.audit_repository(ROOT), [])

    def test_stale_private_sync_route_is_rejected(self) -> None:
        documents = dict(self.documents)
        path = "docs/LINE_BOT_QA_SPEC.md"
        documents[path] += "\n/internal/private-sync\n"
        findings = self.gate.audit_loaded(
            documents,
            self.runtime,
            self.workflows,
            set(),
        )
        self.assertTrue(any("/internal/private-sync" in item for item in findings))

    def test_missing_line_normative_marker_is_rejected(self) -> None:
        documents = dict(self.documents)
        path = "docs/PRIVACY_MULTI_TENANT_POLICY.md"
        documents[path] = documents[path].replace(
            "LINE_IBKR_BRIDGE=FORBIDDEN",
            "LINE_IBKR_BRIDGE=REMOVED_FOR_TEST",
        )
        findings = self.gate.audit_loaded(
            documents,
            self.runtime,
            self.workflows,
            set(),
        )
        self.assertTrue(any("missing normative marker" in item for item in findings))

    def test_missing_zero_cost_marker_is_rejected(self) -> None:
        documents = dict(self.documents)
        path = "docs/ZERO_COST_POLICY.md"
        documents[path] = documents[path].replace(
            "CLOUD_INFERENCE=DISABLED",
            "CLOUD_INFERENCE=OPTIONAL_FOR_TEST",
        )
        findings = self.gate.audit_loaded(
            documents,
            self.runtime,
            self.workflows,
            set(),
        )
        self.assertTrue(
            any(
                path in item and "CLOUD_INFERENCE=DISABLED" in item
                for item in findings
            )
        )

    def test_missing_public_options_marker_is_rejected(self) -> None:
        documents = dict(self.documents)
        path = "docs/OPTIONS_RECOMMENDATION_SPEC.md"
        documents[path] = documents[path].replace(
            "LINE_POSITION_ELIGIBILITY=FORBIDDEN",
            "LINE_POSITION_ELIGIBILITY=ENABLED_FOR_TEST",
        )
        findings = self.gate.audit_loaded(
            documents,
            self.runtime,
            self.workflows,
            set(),
        )
        self.assertTrue(
            any(
                path in item and "LINE_POSITION_ELIGIBILITY=FORBIDDEN" in item
                for item in findings
            )
        )

    def test_runtime_policy_cannot_reenable_line_portfolio_tools(self) -> None:
        runtime = copy.deepcopy(self.runtime)
        runtime["line"]["portfolio_tools"] = True
        findings = self.gate.audit_loaded(
            self.documents,
            runtime,
            self.workflows,
            set(),
        )
        self.assertTrue(any("line.portfolio_tools" in item for item in findings))

    def test_runtime_policy_cannot_reenable_cloud_inference(self) -> None:
        runtime = copy.deepcopy(self.runtime)
        runtime["models"]["cloud"]["enabled"] = True
        findings = self.gate.audit_loaded(
            self.documents,
            runtime,
            self.workflows,
            set(),
        )
        self.assertTrue(any("models.cloud.enabled" in item for item in findings))

    def test_runtime_policy_cannot_enable_broker_lineage_in_public_options(self) -> None:
        runtime = copy.deepcopy(self.runtime)
        runtime["data"]["line_option_snapshot_rejects_broker_lineage"] = False
        findings = self.gate.audit_loaded(
            self.documents,
            runtime,
            self.workflows,
            set(),
        )
        self.assertTrue(
            any(
                "data.line_option_snapshot_rejects_broker_lineage" in item
                for item in findings
            )
        )

    def test_workflow_must_execute_documentation_gate(self) -> None:
        workflows = dict(self.workflows)
        workflows[self.gate.WORKFLOW_PATH] = workflows[
            self.gate.WORKFLOW_PATH
        ].replace(self.gate.WORKFLOW_INVOCATION, "scripts/removed_gate.py")
        findings = self.gate.audit_loaded(
            self.documents,
            self.runtime,
            workflows,
            set(),
        )
        self.assertTrue(any("must invoke" in item for item in findings))

    def test_removed_delivery_asset_is_rejected(self) -> None:
        findings = self.gate.audit_loaded(
            self.documents,
            self.runtime,
            self.workflows,
            {"scripts/deliver.py"},
        )
        self.assertTrue(any("scripts/deliver.py" in item for item in findings))


if __name__ == "__main__":
    unittest.main()
