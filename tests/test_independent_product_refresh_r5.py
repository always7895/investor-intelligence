"""Round 5 independent product collector is strictly non-ranking and bounded by parent."""
from __future__ import annotations
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HELPER = ROOT / "scripts/run_independent_product_refresh.ps1"
COLLECTORS = (
    ("build_zh_names.py", "168"),
    ("build_identity_shards.py", "20"),
    ("build_price_shards.py", "2.9"),
    ("build_market_quotes_options.py", "0.9"),
)


class ProductCacheCollectorR5Tests(unittest.TestCase):
    def test_only_four_independent_collectors_and_accurate_failure(self):
        shells = [s for s in ("powershell", "pwsh") if shutil.which(s)]
        if not shells:
            self.skipTest("PowerShell unavailable")
        for shell in shells:
            for failing in (None, "build_market_quotes_options.py"):
                with self.subTest(shell=shell, failing=failing), tempfile.TemporaryDirectory() as td:
                    base = Path(td)
                    scripts = base / "scripts"
                    scripts.mkdir()
                    shutil.copyfile(HELPER, scripts / HELPER.name)
                    for name, expected_hours in COLLECTORS:
                        (scripts / name).write_text(
                            "from pathlib import Path\nimport sys\n"
                            f"assert sys.argv[1:] == ['--if-older-than-hours', '{expected_hours}']\n"
                            f"with (Path(__file__).resolve().parents[1] / 'steps.log').open('a') as out: out.write('{name}\\n')\n"
                            f"sys.exit({1 if failing == name else 0})\n",
                            encoding="utf-8")
                    env = {**os.environ, "PROJECT_PYTHON": sys.executable}
                    done = subprocess.run([shell, "-NoProfile", "-NonInteractive", "-File",
                                           str(scripts / HELPER.name)], cwd=base,
                                          capture_output=True, env=env, timeout=60)
                    observed = (base / "steps.log").read_text(encoding="utf-8").splitlines()
                    self.assertEqual(observed, [name for name, _ in COLLECTORS])
                    self.assertEqual(done.returncode, 1 if failing else 0,
                                     done.stdout.decode("utf-8", "replace"))
                    self.assertIn("INDEPENDENT_PRODUCT_STEP market_observations exit=", done.stdout.decode("utf-8", "replace"))


if __name__ == "__main__":
    unittest.main()
