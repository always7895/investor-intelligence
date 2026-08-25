from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load_gate():
    spec = importlib.util.spec_from_file_location(
        "workflow_supply_chain_gate_under_test",
        ROOT / "scripts/workflow_supply_chain_gate.py",
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("Unable to load scripts/workflow_supply_chain_gate.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


gate = load_gate()


def workflow_text(
    run_lines: str,
    checkout_sha: str | None = None,
    concurrency_group: str = "supply-chain-${{ github.ref }}",
) -> str:
    checkout_sha = checkout_sha or gate.CHECKOUT_V6_SHA
    indented = "\n".join(f"          {line}" for line in run_lines.splitlines())
    return f"""name: Supply Chain Test

on:
  workflow_dispatch:

permissions:
  contents: read

concurrency:
  group: {concurrency_group}
  cancel-in-progress: true

jobs:
  audit:
    runs-on: [self-hosted, Windows, X64, investor-intelligence]
    steps:
      - name: Checkout
        uses: actions/checkout@{checkout_sha}
        with:
          persist-credentials: false
      - name: Exercise install command
        shell: pwsh
        run: |
{indented}
"""


SAFE_PIP = (
    "& $env:PROJECT_PYTHON -m pip install --isolated "
    "--disable-pip-version-check --only-binary=:all: "
    "--index-url https://pypi.org/simple --require-hashes -r requirements-ci.txt\n"
    "& $env:PROJECT_PYTHON -m pip check"
)


class WorkflowSupplyChainGateTests(unittest.TestCase):
    def audit(self, text: str) -> list[str]:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            directory = root / ".github" / "workflows"
            directory.mkdir(parents=True)
            (directory / "audit.yml").write_text(text, encoding="utf-8")
            return gate.audit_workflows(root)

    def test_accepts_isolated_binary_only_hash_locked_official_index_install(self):
        self.assertEqual(self.audit(workflow_text(SAFE_PIP)), [])

    def test_rejects_pip_install_missing_each_required_control(self):
        fragments = (
            "--isolated ",
            "--disable-pip-version-check ",
            "--only-binary=:all: ",
            "--index-url https://pypi.org/simple ",
            "--require-hashes ",
            "-r requirements-ci.txt",
        )
        for fragment in fragments:
            run_lines = SAFE_PIP.replace(fragment, "", 1)
            findings = self.audit(workflow_text(run_lines))
            with self.subTest(fragment=fragment):
                self.assertTrue(any("pip install is missing" in item for item in findings))

    def test_rejects_dependency_install_without_pip_check(self):
        findings = self.audit(workflow_text(SAFE_PIP.splitlines()[0]))
        self.assertTrue(any("must run pip check" in item for item in findings))

    def test_accepts_powershell_npm_ci_with_all_required_flags(self):
        findings = self.audit(
            workflow_text(
                "& $env:PROJECT_NPM ci --ignore-scripts --no-audit --no-fund\n"
                "if ($LASTEXITCODE -ne 0) { throw 'npm ci failed.' }"
            )
        )
        self.assertEqual(findings, [])

    def test_rejects_unquoted_powershell_call_operator_after_run_key(self):
        text = workflow_text("Write-Host 'safe'")
        text = text.replace(
            "        run: |\n          Write-Host 'safe'",
            "        run: & $env:PROJECT_PYTHON scripts/security_check.py",
        )
        findings = self.audit(text)
        self.assertTrue(any("use `run: |`" in finding for finding in findings))

    def test_rejects_powershell_npm_ci_missing_lifecycle_guard(self):
        findings = self.audit(
            workflow_text("& $env:PROJECT_NPM ci --no-audit --no-fund")
        )
        self.assertTrue(any("--ignore-scripts" in finding for finding in findings))

    def test_rejects_powershell_npm_install(self):
        findings = self.audit(
            workflow_text("& $env:PROJECT_NPM install --no-audit --no-fund")
        )
        self.assertTrue(any("npm install is forbidden" in finding for finding in findings))

    def test_rejects_checkout_sha_other_than_reviewed_v6(self):
        findings = self.audit(
            workflow_text(
                "Write-Host 'no install'",
                checkout_sha="11bd71901bbe5b1630ceea73d27597364c9af683",
            )
        )
        self.assertTrue(any("reviewed v6.0.3 SHA" in finding for finding in findings))

    def test_rejects_per_commit_concurrency_group(self):
        findings = self.audit(
            workflow_text(
                "Write-Host 'no install'",
                concurrency_group="supply-chain-${{ github.sha }}",
            )
        )
        self.assertTrue(any("stable per branch/PR" in finding for finding in findings))


if __name__ == "__main__":
    unittest.main()
