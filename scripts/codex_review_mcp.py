#!/usr/bin/env python3
"""Read-only review MCP server (stdio, JSON-RPC 2.0, stdlib only) over the official Codex CLI signed in with ChatGPT.

Operator 2026-09-26: reviews go to ChatGPT on Windows through MCP. The desktop app (OpenAI.Codex) ships codex.exe, which
has no MCP server mode in this build, so this server runs `codex exec` non-interactively in a read-only sandbox with an
ephemeral session and returns the final message. The ChatGPT chat UI is never automated (its terms forbid automated
extraction); the Codex quota applies, and an exhausted quota is reported as CODEX_QUOTA_EXHAUSTED instead of retried.

Operator 2026-09-26: "Pro first, xhigh once it is used up". The CLI has no Pro tier, so the default effort `auto` runs
the top effort `ultra` and, only when that attempt reports an exhausted quota, runs the same prompt once at `xhigh`.
An explicit effort is a single attempt.

The chat model "6 Pro" of the ChatGPT app is not offered to the CLI or the app server (model/list checked
2026-09-26), and its chat UI may not be scripted, so a Pro review is a packet the operator pastes into ChatGPT.

Tools
- chatgpt_review      prompt (required), cwd (under WORKSPACE, default the source repository), model (default
                      gpt-6-sol, only models the CLI lists), effort (default auto = ultra then xhigh; high, xhigh, max or
                      ultra). An exhausted quota names the reset time the CLI reports: CODEX_QUOTA_EXHAUSTED until <time>.
- chatgpt_pro_packet  prompt (required), name, clipboard (default false): writes the review request to
                      PACKET_DIR/chatgpt-pro-<name>.md for the operator to paste into ChatGPT with 6 Pro selected (and
                      copies it to the clipboard on request). Nothing is sent; the reply comes back through the operator.
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
SERVER_INFO = {"name": "chatgpt-codex-review", "version": "1.1.0"}
WORKSPACE = Path(r"D:\Investor-Intelligence-LINE-Pi\_workspace")
DEFAULT_CWD = WORKSPACE / "source"
DEFAULT_MODEL = "gpt-6-sol"  # the independent reviewer model of the control plane
EFFORTS = ("auto", "high", "xhigh", "max", "ultra")
AUTO_EFFORTS = ("ultra", "xhigh")  # the "Pro" tier first, then the operator's fallback
MAX_PROMPT = 200_000
TIMEOUT_SECONDS = 3600
PACKET_DIR = Path(os.environ.get("TEMP", tempfile.gettempdir())) / "ii-live"
RESET_RE = re.compile(r"try again (?:at|in) ([^.\r\n]{3,60})", re.IGNORECASE)
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
    effort = str(args.get("effort") or "auto")
    if effort not in EFFORTS:
        raise ToolError("EFFORT_MUST_BE_AUTO_HIGH_XHIGH_MAX_OR_ULTRA")
    attempts = AUTO_EFFORTS if effort == "auto" else (effort,)
    for index, attempt in enumerate(attempts):
        try:
            answer = _run_codex(prompt, cwd, model, attempt)
        except ToolError as error:
            if str(error).startswith("CODEX_QUOTA_EXHAUSTED") and index + 1 < len(attempts):
                continue
            raise
        result = {"model": model, "effort": attempt, "cwd": str(cwd), "answer": answer}
        if index:
            result["fallback_from"] = list(attempts[:index])
        return result
    raise ToolError("CODEX_NO_ATTEMPT")  # unreachable: attempts is never empty


def _run_codex(prompt: str, cwd: Path, model: str, effort: str) -> str:
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
            reset = RESET_RE.search(tail)
            raise ToolError("CODEX_QUOTA_EXHAUSTED" + (f" until {reset.group(1).strip()}" if reset else ""))
        raise ToolError(f"CODEX_FAILED exit={completed.returncode}: {tail.strip()[-600:]}")
    return answer


def chatgpt_pro_packet(args: dict[str, Any]) -> dict[str, Any]:
    prompt = str(args.get("prompt") or "")
    if not prompt.strip() or len(prompt) > MAX_PROMPT:
        raise ToolError("PROMPT_REQUIRED_MAX_200000_CHARS")
    name = re.sub(r"[^A-Za-z0-9._-]+", "-", str(args.get("name") or "review")).strip("-.")[:60] or "review"
    PACKET_DIR.mkdir(parents=True, exist_ok=True)
    path = PACKET_DIR / f"chatgpt-pro-{name}.md"
    path.write_text(prompt, encoding="utf-8")
    copied = False
    if args.get("clipboard") is True:
        completed = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command",
                                    "Set-Clipboard -Value (Get-Content -LiteralPath $env:II_PACKET -Raw -Encoding utf8)"],
                                   env={**os.environ, "II_PACKET": str(path)}, capture_output=True, timeout=60)
        copied = completed.returncode == 0
    return {"packet": str(path), "chars": len(prompt), "clipboard": copied,
            "next": "Paste into ChatGPT with 6 Pro selected (極高 when Pro is used up) and paste the reply back."}


TOOLS = {
    "chatgpt_review": (chatgpt_review, "Independent read-only review by ChatGPT (Codex CLI, read-only sandbox). Put the full "
                       "review request, the diff or file paths and the answer format in `prompt`.",
                       {"type": "object", "additionalProperties": False, "required": ["prompt"], "properties": {
                           "prompt": {"type": "string"}, "cwd": {"type": "string"},
                           "model": {"type": "string", "description": f"default {DEFAULT_MODEL}"},
                           "effort": {"type": "string", "enum": list(EFFORTS),
                                      "description": "default auto: ultra, then xhigh when the quota is exhausted"}}}),
    "chatgpt_pro_packet": (chatgpt_pro_packet, "Review packet for ChatGPT 6 Pro: written to a file (and the clipboard on "
                           "request) for the operator to paste; nothing is sent automatically.",
                           {"type": "object", "additionalProperties": False, "required": ["prompt"], "properties": {
                               "prompt": {"type": "string"}, "name": {"type": "string"},
                               "clipboard": {"type": "boolean", "description": "default false"}}}),
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
