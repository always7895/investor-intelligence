#!/usr/bin/env python3
"""Read-only review MCP server (stdio, JSON-RPC 2.0, stdlib only) over the official Codex CLI signed in with ChatGPT.

Operator 2026-09-26: reviews go to ChatGPT on Windows through MCP. The desktop app (OpenAI.Codex) ships codex.exe, which
has no MCP server mode in this build, so this server runs `codex exec` non-interactively in a read-only sandbox with an
ephemeral session and returns the final message. The ChatGPT chat UI is never automated (its terms forbid automated
extraction); the Codex quota applies, and an exhausted quota is reported as CODEX_QUOTA_EXHAUSTED instead of retried.

Tool
- chatgpt_review  prompt (required), cwd (under WORKSPACE, default the source repository), model (default gpt-6-sol,
                  only models the CLI lists), effort (default xhigh; high, xhigh, max or ultra)
"""
from __future__ import annotations

import glob
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

PROTOCOL_VERSION = "2025-06-18"
SERVER_INFO = {"name": "chatgpt-codex-review", "version": "1.0.0"}
WORKSPACE = Path(r"D:\Investor-Intelligence-LINE-Pi\_workspace")
DEFAULT_CWD = WORKSPACE / "source"
DEFAULT_MODEL = "gpt-6-sol"  # the independent reviewer model of the control plane
EFFORTS = ("high", "xhigh", "max", "ultra")
MAX_PROMPT = 200_000
TIMEOUT_SECONDS = 3600
QUOTA_RE = re.compile(r"usage limit|rate limit|quota|too many requests|429", re.IGNORECASE)


class ToolError(Exception):
    """A caller-visible failure (bad input, CLI missing, quota); never carries credentials."""


def codex_exe() -> str:
    """CODEX_EXE, else the newest codex.exe the desktop app installed (its folder name changes with updates)."""
    explicit = os.getenv("CODEX_EXE", "")
    if explicit and Path(explicit).is_file():
        return explicit
    found = glob.glob(os.path.join(os.getenv("LOCALAPPDATA", ""), "OpenAI", "Codex", "bin", "*", "codex.exe"))
    if not found:
        raise ToolError("CODEX_CLI_NOT_INSTALLED")
    return max(found, key=os.path.getmtime)


def listed_models() -> set[str]:
    try:
        cache = json.loads(Path.home().joinpath(".codex", "models_cache.json").read_text(encoding="utf-8"))
        return {str(model.get("slug")) for model in cache.get("models", []) if model.get("visibility") == "list"}
    except (OSError, ValueError, AttributeError):
        return {DEFAULT_MODEL}


def _inside_workspace(raw: str) -> Path:
    path = Path(raw).resolve() if raw else DEFAULT_CWD
    if path != WORKSPACE and WORKSPACE not in path.parents or not path.is_dir():
        raise ToolError("CWD_MUST_BE_A_DIRECTORY_UNDER_THE_WORKSPACE")
    return path


def chatgpt_review(args: dict[str, Any]) -> dict[str, Any]:
    prompt = str(args.get("prompt") or "")
    if not prompt.strip() or len(prompt) > MAX_PROMPT:
        raise ToolError("PROMPT_REQUIRED_MAX_200000_CHARS")
    cwd = _inside_workspace(str(args.get("cwd") or ""))
    model = str(args.get("model") or DEFAULT_MODEL)
    if model not in listed_models():
        raise ToolError(f"MODEL_NOT_LISTED: {model[:40]}")
    effort = str(args.get("effort") or "xhigh")
    if effort not in EFFORTS:
        raise ToolError("EFFORT_MUST_BE_HIGH_XHIGH_MAX_OR_ULTRA")
    with tempfile.TemporaryDirectory(prefix="codex-review-") as tmp:
        last = Path(tmp) / "last-message.txt"
        command = [codex_exe(), "exec", "--sandbox", "read-only", "--ephemeral", "--skip-git-repo-check", "--color", "never",
                   "-C", str(cwd), "-m", model, "-c", f'model_reasoning_effort="{effort}"', "-o", str(last), "-"]
        try:
            completed = subprocess.run(command, input=prompt, capture_output=True, text=True, encoding="utf-8",
                                       errors="replace", timeout=TIMEOUT_SECONDS, cwd=str(cwd))
        except subprocess.TimeoutExpired as error:
            raise ToolError("CODEX_TIMEOUT") from error
        answer = last.read_text(encoding="utf-8", errors="replace").strip() if last.exists() else ""
    if completed.returncode != 0 or not answer:
        tail = (completed.stderr or completed.stdout or "")[-1200:]
        if QUOTA_RE.search(tail):
            raise ToolError("CODEX_QUOTA_EXHAUSTED")
        raise ToolError(f"CODEX_FAILED exit={completed.returncode}: {tail.strip()[-600:]}")
    return {"model": model, "effort": effort, "cwd": str(cwd), "answer": answer}


TOOLS = {
    "chatgpt_review": (chatgpt_review, "Independent read-only review by ChatGPT (Codex CLI, read-only sandbox). Put the full "
                       "review request, the diff or file paths and the answer format in `prompt`.",
                       {"type": "object", "additionalProperties": False, "required": ["prompt"], "properties": {
                           "prompt": {"type": "string"}, "cwd": {"type": "string"},
                           "model": {"type": "string", "description": f"default {DEFAULT_MODEL}"},
                           "effort": {"type": "string", "enum": list(EFFORTS), "description": "default xhigh"}}}),
}


def handle(message: dict[str, Any]) -> dict[str, Any] | None:
    method, identifier = message.get("method"), message.get("id")
    if identifier is None:
        return None
    if method == "initialize":
        requested = str((message.get("params") or {}).get("protocolVersion") or PROTOCOL_VERSION)
        result: dict[str, Any] = {"protocolVersion": requested, "capabilities": {"tools": {}}, "serverInfo": SERVER_INFO}
    elif method == "ping":
        result = {}
    elif method == "tools/list":
        result = {"tools": [{"name": name, "description": text, "inputSchema": schema} for name, (_, text, schema) in TOOLS.items()]}
    elif method == "tools/call":
        params = message.get("params") or {}
        entry = TOOLS.get(str(params.get("name")))
        if not entry:
            return {"jsonrpc": "2.0", "id": identifier, "error": {"code": -32602, "message": f"unknown tool {params.get('name')}"}}
        try:
            payload = entry[0](dict(params.get("arguments") or {}))
            result = {"content": [{"type": "text", "text": json.dumps(payload, ensure_ascii=False)}], "isError": False}
        except ToolError as error:
            result = {"content": [{"type": "text", "text": str(error)}], "isError": True}
        except Exception as error:
            result = {"content": [{"type": "text", "text": f"INTERNAL_ERROR {type(error).__name__}"}], "isError": True}
    else:
        return {"jsonrpc": "2.0", "id": identifier, "error": {"code": -32601, "message": f"method not found: {method}"}}
    return {"jsonrpc": "2.0", "id": identifier, "result": result}


def main() -> int:
    sys.stdin.reconfigure(encoding="utf-8")
    sys.stdout.reconfigure(encoding="utf-8", newline="\n")
    for line in sys.stdin:
        if not line.strip():
            continue
        try:
            message = json.loads(line)
        except ValueError:
            response: dict[str, Any] | None = {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "parse error"}}
        else:
            response = handle(message) if isinstance(message, dict) else {"jsonrpc": "2.0", "id": None,
                                                                           "error": {"code": -32600, "message": "batch not supported"}}
        if response is not None:
            sys.stdout.write(json.dumps(response, ensure_ascii=False) + "\n")
            sys.stdout.flush()
    return 0


if __name__ == "__main__":
    sys.exit(main())
