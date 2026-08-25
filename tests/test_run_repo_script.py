from __future__ import annotations

import importlib.util
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load_launcher():
    spec = importlib.util.spec_from_file_location(
        "run_repo_script_under_test",
        ROOT / "scripts" / "run_repo_script.py",
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("Unable to load scripts/run_repo_script.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


launcher = load_launcher()


class RepositoryScriptLauncherTests(unittest.TestCase):
    def test_resolves_only_regular_lowercase_sibling_scripts(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "safe_script.py"
            target.write_text("print('ok')\n", encoding="utf-8")
            self.assertEqual(launcher.resolve_script("safe_script.py", root), target.resolve())

            for value in (
                "../safe_script.py",
                "subdir/safe_script.py",
                "SAFE.py",
                "safe-script.py",
                "safe_script.txt",
                "",
            ):
                with self.subTest(value=value), self.assertRaises(
                    launcher.RepositoryScriptError
                ):
                    launcher.resolve_script(value, root)

    def test_rejects_missing_and_symlink_scripts(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with self.assertRaises(launcher.RepositoryScriptError):
                launcher.resolve_script("missing.py", root)

            target = root / "target.py"
            target.write_text("print('ok')\n", encoding="utf-8")
            link = root / "linked.py"
            try:
                link.symlink_to(target)
            except (OSError, NotImplementedError):
                self.skipTest("Symlink creation is unavailable")
            with self.assertRaises(launcher.RepositoryScriptError):
                launcher.resolve_script("linked.py", root)

    def test_executes_release_verifier_help_with_sibling_imports_available(self) -> None:
        completed = subprocess.run(
            [
                sys.executable,
                str(ROOT / "scripts" / "run_repo_script.py"),
                "verify_release_package.py",
                "--help",
            ],
            cwd=ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=30,
        )
        self.assertEqual(completed.returncode, 0, completed.stdout)
        self.assertIn("--archive", completed.stdout)
        self.assertIn("--sbom", completed.stdout)


if __name__ == "__main__":
    unittest.main()
