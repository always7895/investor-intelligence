"""Keep the standalone CI audits locked to the consolidated activation forwarding.

The 2026-09-05 consolidation (a43f420) turned
activate-v213-seven-field-schedule-serenity-latest.ps1 into a thin forwarder of
activate-v213-diversified-schedule.ps1.  The static and BLS audits used to
demand byte-equivalence with the canonical wrapper and broke every Windows CI
run on the Pi branch because of it.  These tests pin the new forwarding
architecture: the audits must pass on the real tree and must still fail closed
when the alias drifts from its forward target.
"""
from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STATIC_AUDIT = ROOT / "scripts" / "v213_serenity_latest_static_audit.py"
BLS_AUDIT = ROOT / "scripts" / "v213_optional_bls_alignment_audit.py"
ALIAS = "activate-v213-seven-field-schedule-serenity-latest.ps1"
TARGET = "activate-v213-diversified-schedule.ps1"
CANONICAL = "activate-v213-seven-field-schedule.ps1"


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ActivationForwardingAuditTests(unittest.TestCase):
    def test_static_audit_passes_on_the_real_tree(self) -> None:
        completed = subprocess.run(
            [sys.executable, str(STATIC_AUDIT)],
            cwd=ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=120,
        )
        self.assertEqual(completed.returncode, 0, completed.stdout)
        self.assertIn("alias_forwarding=true", completed.stdout)

    def test_bls_alignment_audit_passes_on_the_real_tree(self) -> None:
        completed = subprocess.run(
            [sys.executable, str(BLS_AUDIT)],
            cwd=ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=120,
        )
        self.assertEqual(completed.returncode, 0, completed.stdout)
        self.assertIn("alias_forwarding=true", completed.stdout)

    def test_parameter_block_extraction_is_fail_closed(self) -> None:
        audit = load_module("serenity_static_audit_under_test", STATIC_AUDIT)
        self.assertEqual(
            audit.parameter_block("no binding here"), "<missing param block>"
        )
        synthetic = "[CmdletBinding()]\nparam(\n    [string]$A = ''\n    [switch]$B\n)\nbody\n"
        self.assertEqual(
            audit.parameter_block(synthetic),
            "[CmdletBinding()]\nparam(\n    [string]$A = ''\n    [switch]$B\n)\n",
        )

    def _run_static_audit_with_text_override(self, corrupt) -> tuple[int, str]:
        audit = load_module("serenity_static_audit_case", STATIC_AUDIT)
        real_text = audit.text

        def fake_text(path: str) -> str:
            return corrupt(path, real_text(path))

        audit.text = fake_text
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            code = audit.main()
        return code, buffer.getvalue()

    def test_static_audit_rejects_a_repointed_forwarding_alias(self) -> None:
        code, output = self._run_static_audit_with_text_override(
            lambda path, value: (
                value.replace(TARGET, CANONICAL) if path == ALIAS else value
            )
        )
        self.assertEqual(code, 1)
        self.assertIn(f"{ALIAS} no longer forwards to {TARGET}", output)

    def test_static_audit_rejects_an_alias_that_drops_parameter_forwarding(self) -> None:
        code, output = self._run_static_audit_with_text_override(
            lambda path, value: (
                value.replace("@PSBoundParameters", "@SomeSubset")
                if path == ALIAS
                else value
            )
        )
        self.assertEqual(code, 1)
        self.assertIn(
            f"{ALIAS} no longer forwards all bound parameters and exit codes",
            output,
        )

    def test_static_audit_rejects_alias_parameter_contract_drift(self) -> None:
        code, output = self._run_static_audit_with_text_override(
            lambda path, value: (
                value.replace("[switch]$AllowTestTunnelException\n)",
                              "[switch]$AllowTestTunnelException\n    [switch]$NewSwitch\n)")
                if path == ALIAS
                else value
            )
        )
        self.assertEqual(code, 1)
        self.assertIn(
            f"{ALIAS} parameter contract drifted from {TARGET}", output
        )

    def test_static_audit_rejects_lost_timestamp_guard_and_stale_audit_path(self) -> None:
        guard = "ToString('o',[Globalization.CultureInfo]::InvariantCulture)"

        def corrupt(path: str, value: str) -> str:
            if path in (TARGET, CANONICAL):
                value = value.replace(guard, "return $property.Value # guard gone")
            if path == CANONICAL:
                value = value + "\nv213_serenity_latest_multisource_audit.py\n"
            return value

        code, output = self._run_static_audit_with_text_override(corrupt)
        self.assertEqual(code, 1)
        self.assertIn(
            f"{TARGET} lost the JSON UTC-offset preservation guard", output
        )
        self.assertIn(
            f"{CANONICAL} lost the JSON UTC-offset preservation guard", output
        )
        self.assertIn(
            f"{CANONICAL} regressed to the stale strict post-bundle audit path",
            output,
        )

    def test_packager_keeps_the_forwarding_enforcement_message(self) -> None:
        package = (ROOT / "scripts" / "ci_v213_r70_package.ps1").read_text(
            encoding="utf-8-sig"
        )
        self.assertIn(
            "Source activation compatibility alias no longer forwards to the "
            "source-independence-aware implementation.",
            package,
        )
        self.assertIn(
            "Source activation compatibility alias parameter contract drifted "
            "from its forward target.",
            package,
        )
        # The old byte-equivalence gate must not silently return.
        self.assertNotIn(
            "Source activation compatibility alias differs from the canonical "
            "source-independence-aware wrapper.",
            package,
        )
        # Marker checks must stay literal: PowerShell -like reads the
        # [Globalization.CultureInfo] brackets as a character class.
        self.assertNotIn("-notlike", package)
        self.assertNotIn("-like ", package)
        self.assertIn(".Contains($activationMarker)", package)

    def _run_bls_audit_with_root(self, root: Path) -> str:
        audit = load_module("serenity_bls_audit_case", BLS_AUDIT)
        audit.ROOT = root
        audit.POLICY_PATH = root / "config" / "v213-source-federation-policy.json"
        audit.CONTRACT_PATH = root / "config" / "v213-r75-publication-mode-v1.json"
        audit.CANONICAL_ACTIVATION = root / CANONICAL
        audit.COMPATIBILITY_ALIAS = root / ALIAS
        audit.FORWARD_TARGET = root / TARGET
        try:
            audit.main()
        except SystemExit as exc:
            return str(exc.code)
        return ""

    def test_bls_audit_rejects_alias_parameter_contract_drift(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            for name in (ALIAS, TARGET, CANONICAL):
                shutil.copyfile(ROOT / name, root / name)
            for config in (
                "config/v213-source-federation-policy.json",
                "config/v213-r75-publication-mode-v1.json",
            ):
                destination = root / config
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_text(
                    (ROOT / config).read_text(encoding="utf-8-sig"), encoding="utf-8"
                )
            alias_path = root / ALIAS
            drifted = alias_path.read_text(encoding="utf-8-sig").replace(
                "[switch]$AllowTestTunnelException\n)",
                "[switch]$AllowTestTunnelException\n    [switch]$NewSwitch\n)",
            )
            self.assertNotEqual(drifted, alias_path.read_text(encoding="utf-8-sig"))
            alias_path.write_text(drifted, encoding="utf-8")
            message = self._run_bls_audit_with_root(root)
            self.assertIn(
                f"{ALIAS} parameter contract drifted from {TARGET}", message
            )

    def test_bls_audit_rejects_a_repointed_forwarding_alias(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            for name in (ALIAS, TARGET, CANONICAL):
                shutil.copyfile(ROOT / name, root / name)
            for config in (
                "config/v213-source-federation-policy.json",
                "config/v213-r75-publication-mode-v1.json",
            ):
                destination = root / config
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_text(
                    (ROOT / config).read_text(encoding="utf-8-sig"), encoding="utf-8"
                )
            alias_path = root / ALIAS
            repointed = alias_path.read_text(encoding="utf-8-sig").replace(
                TARGET, CANONICAL
            )
            alias_path.write_text(repointed, encoding="utf-8")
            message = self._run_bls_audit_with_root(root)
            self.assertIn(
                f"{ALIAS} no longer forwards to {TARGET}", message
            )


if __name__ == "__main__":
    unittest.main()
