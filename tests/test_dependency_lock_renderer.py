from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load_renderer():
    spec = importlib.util.spec_from_file_location(
        "render_pip_report_lock_under_test",
        ROOT / "scripts/render_pip_report_lock.py",
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("Unable to load scripts/render_pip_report_lock.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


renderer = load_renderer()


class PipReportLockRendererTests(unittest.TestCase):
    def test_renders_sorted_exact_hash_lock(self):
        report = {
            "install": [
                {
                    "metadata": {"name": "Requests", "version": "2.34.2"},
                    "download_info": {
                        "archive_info": {"hashes": {"sha256": "b" * 64}}
                    },
                },
                {
                    "metadata": {"name": "pandas", "version": "2.3.3"},
                    "download_info": {
                        "archive_info": {"hash": "sha256=" + "a" * 64}
                    },
                },
            ]
        }
        rendered = renderer.render_lock(report, {"requests", "pandas"})
        lines = [
            line
            for line in rendered.splitlines()
            if line and not line.startswith("#")
        ]
        self.assertEqual(
            lines,
            [
                f"pandas==2.3.3 --hash=sha256:{'a' * 64}",
                f"requests==2.34.2 --hash=sha256:{'b' * 64}",
            ],
        )

    def test_rejects_missing_digest(self):
        report = {
            "install": [
                {
                    "metadata": {"name": "requests", "version": "2.34.2"},
                    "download_info": {"archive_info": {}},
                }
            ]
        }
        with self.assertRaises(ValueError):
            renderer.render_lock(report, {"requests"})


if __name__ == "__main__":
    unittest.main()
