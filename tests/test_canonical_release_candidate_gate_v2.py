from __future__ import annotations

import importlib.util
import json
import shutil
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load_gate():
    spec = importlib.util.spec_from_file_location(
        "canonical_release_candidate_gate_v2_under_test",
        ROOT / "scripts" / "canonical_release_candidate_gate_v2.py",
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("Unable to load canonical_release_candidate_gate_v2.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


gate = load_gate()


class CanonicalReleaseCandidateGateTests(unittest.TestCase):
    def test_current_repository_passes_meta_gate(self) -> None:
        self.assertEqual(gate.audit_repository(ROOT), [])

    def test_workflow_requires_isolated_binary_only_hash_locked_pip(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            directory = root / ".github" / "workflows"
            directory.mkdir(parents=True)
            (directory / "unsafe.yml").write_text(
                """name: unsafe
on:
  workflow_dispatch:
permissions:
  contents: read
jobs:
  audit:
    runs-on: [self-hosted, Windows, X64, investor-intelligence]
    steps:
      - uses: actions/checkout@df4cb1c069e1874edd31b4311f1884172cec0e10
        with:
          persist-credentials: false
      - shell: pwsh
        run: |
          & $env:PROJECT_PYTHON -m pip install --require-hashes -r requirements-ci.txt
""",
                encoding="utf-8",
            )
            findings = gate._audit_workflows(root)
        self.assertTrue(any("--isolated" in finding for finding in findings))
        self.assertTrue(any("--only-binary=:all:" in finding for finding in findings))
        self.assertTrue(any("pip check" in finding for finding in findings))

    def test_workflow_rejects_issue_write_and_self_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            directory = root / ".github" / "workflows"
            directory.mkdir(parents=True)
            (directory / "unsafe.yml").write_text(
                """name: unsafe
on:
  workflow_dispatch:
permissions:
  issues: write
jobs:
  audit:
    runs-on: [self-hosted, Windows, X64, investor-intelligence]
    steps:
      - shell: pwsh
        run: git push origin HEAD
""",
                encoding="utf-8",
            )
            findings = gate._audit_workflows(root)
        self.assertTrue(any("write permission" in finding for finding in findings))
        self.assertTrue(any("forbidden mutation" in finding for finding in findings))

    def test_release_status_must_remain_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "cloud").mkdir(parents=True)
            (root / "config").mkdir()
            (root / "cloud" / "package.json").write_text(
                json.dumps({"scripts": {"test": "vitest"}}), encoding="utf-8"
            )
            (root / "config" / "release-status.json").write_text(
                json.dumps(
                    {"release_ready": True, "deployed": False, "billing_enabled": False}
                ),
                encoding="utf-8",
            )
            findings = gate._audit_release_fail_closed(root)
        self.assertTrue(any("release_ready must remain false" in finding for finding in findings))

    def test_legacy_single_cache_binding_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for relative in (
                "cloud/src",
                "cloud",
                "scripts",
                "config",
            ):
                (root / relative).mkdir(parents=True, exist_ok=True)
            (root / "cloud/src/storage.ts").write_text(
                "PUBLIC_CACHE TENANT_PRIVATE_CACHE EPHEMERAL_SECURITY_CACHE",
                encoding="utf-8",
            )
            (root / "cloud/src/worker.ts").write_text("public worker", encoding="utf-8")
            (root / "cloud/wrangler.toml").write_text(
                '\n'.join(
                    [
                        'binding = "PUBLIC_CACHE"',
                        'binding = "TENANT_PRIVATE_CACHE"',
                        'binding = "EPHEMERAL_SECURITY_CACHE"',
                        'binding = "CACHE"',
                    ]
                ),
                encoding="utf-8",
            )
            (root / "scripts/build_line_public_options.py").write_text(
                "public only", encoding="utf-8"
            )
            (root / "config/runtime-policy.json").write_text(
                json.dumps(
                    {
                        "privacy": {
                            "owner_data_available_to_line": False,
                            "owner_watchlist_inherited_by_line": False,
                            "portfolio_available_to_line": False,
                            "broker_account_available_to_line": False,
                            "private_sync_available_to_line": False,
                        },
                        "line": {
                            "ibkr_bridge": False,
                            "brokerage_connection": False,
                            "portfolio_tools": False,
                            "private_sync_route": False,
                        },
                        "local_broker_runtime": {
                            "line_or_worker_may_call_ibkr": False,
                            "ibkr_output_may_enter_public_kv": False,
                            "ibkr_output_may_enter_line_model_context": False,
                        },
                    }
                ),
                encoding="utf-8",
            )
            findings = gate._audit_line_and_storage_boundary(root)
        self.assertTrue(any("legacy shared CACHE binding" in finding for finding in findings))


if __name__ == "__main__":
    unittest.main()
