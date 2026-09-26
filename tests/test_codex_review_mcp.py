"""Codex review MCP: read-only sandbox command line, workspace-bound cwd, model/effort allowlists, quota reporting.
No Codex process is started (subprocess.run is replaced)."""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import codex_review_mcp as server  # noqa: E402


def call(arguments):
    response = server.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "chatgpt_review", "arguments": arguments}})
    return response["result"]


class CodexReviewTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.workspace = Path(self.tmp.name).resolve()
        (self.workspace / "source").mkdir()
        self.saved = (server.WORKSPACE, server.DEFAULT_CWD, server.codex_exe, server.listed_models, server.subprocess.run)
        server.WORKSPACE, server.DEFAULT_CWD = self.workspace, self.workspace / "source"
        server.codex_exe = lambda: "codex.exe"
        server.listed_models = lambda: {"gpt-6-sol", "gpt-6-astra"}
        self.commands = []

    def tearDown(self):
        server.WORKSPACE, server.DEFAULT_CWD, server.codex_exe, server.listed_models, server.subprocess.run = self.saved
        self.tmp.cleanup()

    def fake_run(self, answer="VERDICT: APPROVE", returncode=0, stderr="", exhausted=()):
        def run(command, **kwargs):
            self.commands.append((command, kwargs))
            if any(f'model_reasoning_effort="{effort}"' in command for effort in exhausted):
                return SimpleNamespace(returncode=1, stdout="", stderr="ERROR: You've hit your usage limit.")
            if answer:
                Path(command[command.index("-o") + 1]).write_text(answer, encoding="utf-8")
            return SimpleNamespace(returncode=returncode, stdout="", stderr=stderr)
        server.subprocess.run = run

    def test_runs_codex_exec_read_only_and_returns_the_last_message(self):
        self.fake_run()
        result = call({"prompt": "review this"})
        self.assertFalse(result["isError"])
        payload = json.loads(result["content"][0]["text"])
        self.assertEqual((payload["model"], payload["effort"], payload["answer"]), ("gpt-6-sol", "ultra", "VERDICT: APPROVE"))
        self.assertNotIn("fallback_from", payload)
        self.assertEqual(len(self.commands), 1)
        command, kwargs = self.commands[0]
        self.assertEqual(command[1:5], ["exec", "--sandbox", "read-only", "--ephemeral"])
        self.assertIn('model_reasoning_effort="ultra"', command)
        self.assertEqual(command[-1], "-")
        self.assertEqual(kwargs["input"], "review this")
        self.assertNotIn("danger-full-access", command)
        self.assertNotIn("--dangerously-bypass-approvals-and-sandbox", command)

    def test_rejects_cwd_outside_the_workspace_unlisted_models_and_efforts(self):
        self.fake_run()
        for arguments, code in (({"prompt": "x", "cwd": "C:\\Windows"}, "CWD_MUST_BE"), ({"prompt": "x", "model": "gpt-reserve"}, "MODEL_NOT_LISTED"),
                                ({"prompt": "x", "effort": "low"}, "EFFORT_MUST_BE"), ({"prompt": " "}, "PROMPT_REQUIRED")):
            result = call(arguments)
            self.assertTrue(result["isError"])
            self.assertIn(code, result["content"][0]["text"])
        self.assertEqual(self.commands, [])

    def test_auto_falls_back_to_xhigh_only_when_ultra_quota_is_exhausted(self):
        self.fake_run(exhausted=("ultra",))
        payload = json.loads(call({"prompt": "review"})["content"][0]["text"])
        self.assertEqual((payload["effort"], payload["fallback_from"]), ("xhigh", ["ultra"]))
        self.assertEqual([c[0][c[0].index("-c") + 1] for c in self.commands],
                         ['model_reasoning_effort="ultra"', 'model_reasoning_effort="xhigh"'])

    def test_auto_reports_quota_when_xhigh_is_exhausted_too_and_other_failures_do_not_fall_back(self):
        self.fake_run(exhausted=("ultra", "xhigh"))
        result = call({"prompt": "review"})
        self.assertEqual((result["isError"], result["content"][0]["text"]), (True, "CODEX_QUOTA_EXHAUSTED"))
        self.assertEqual(len(self.commands), 2)
        self.commands.clear()
        self.fake_run(answer="", returncode=2, stderr="model crashed")
        result = call({"prompt": "review"})
        self.assertIn("CODEX_FAILED exit=2", result["content"][0]["text"])
        self.assertEqual(len(self.commands), 1)

    def test_an_exhausted_quota_is_reported_not_retried(self):
        self.fake_run(answer="", returncode=1, stderr="ERROR: You've hit your usage limit. Try again later.")
        result = call({"prompt": "review", "effort": "max"})
        self.assertTrue(result["isError"])
        self.assertEqual(result["content"][0]["text"], "CODEX_QUOTA_EXHAUSTED")
        self.assertEqual(len(self.commands), 1)


if __name__ == "__main__":
    unittest.main()
