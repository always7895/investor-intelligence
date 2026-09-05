"""Closed, authenticated compact context protocol; no research HTTP enrichment.

Legacy requests retain their existing evidence enrichment. Compact requests
must carry the shared safety policy verbatim. Transport smoke is fixed-input.
This changes request size/output bounds, never the user's llama.cpp preset.
"""
from __future__ import annotations
import json
from pathlib import Path

POLICY = json.loads((Path(__file__).resolve().parents[1] / "config/v213-compact-qa-v1.json").read_text(encoding="utf-8-sig"))


def complete_compact_response(result: object, selected: str) -> bool:
    if not isinstance(result, dict) or result.get("model") != selected:
        return False
    choices = result.get("choices")
    if not isinstance(choices, list) or len(choices) != 1 or not isinstance(choices[0], dict):
        return False
    choice = choices[0]
    message = choice.get("message")
    return (choice.get("finish_reason") == "stop" and isinstance(message, dict)
            and isinstance(message.get("content"), str) and bool(message["content"].strip()))


def compact_upstream(body: dict, selected: str) -> dict | None:
    mode = body.get("ii_context_mode")
    if mode is None:
        return None
    if selected != POLICY["model"] or body.get("model") != selected:
        raise ValueError("COMPACT_MODEL_MISMATCH")
    if mode not in (POLICY["mode"], POLICY["smoke_mode"]):
        raise ValueError("COMPACT_MODE_INVALID")
    messages = body.get("messages")
    maximum = POLICY["max_output_tokens"]
    if mode == POLICY["smoke_mode"]:
        if messages != [{"role": "user", "content": POLICY["smoke_prompt"]}]:
            raise ValueError("COMPACT_SMOKE_INPUT_INVALID")
        maximum = POLICY["smoke_output_tokens"]
    else:
        if not isinstance(messages, list) or not 2 <= len(messages) <= 2 + POLICY["max_history_turns"]:
            raise ValueError("COMPACT_MESSAGES_INVALID")
        if any(not isinstance(m, dict) or set(m) != {"role", "content"} or not isinstance(m["content"], str) for m in messages):
            raise ValueError("COMPACT_MESSAGE_SCHEMA_INVALID")
        prefix = POLICY["system"] + "\nDATA="
        if messages[0]["role"] != "system" or not messages[0]["content"].startswith(prefix):
            raise ValueError("COMPACT_POLICY_MISSING")
        data_text = messages[0]["content"][len(prefix):]
        if len(data_text) > POLICY["max_context_chars"]:
            raise ValueError("COMPACT_CONTEXT_TOO_LARGE")
        data = json.loads(data_text)
        if not isinstance(data, dict) or data.get("v") != 1 or data.get("freshness") not in ("FRESH", "STALE", "UNAVAILABLE"):
            raise ValueError("COMPACT_CONTEXT_INVALID")
        if data.get("mode") == "LIMITED_RESEARCH_CANDIDATE" and (data.get("high_eligible") is not False or data.get("validated_thesis") is not False):
            raise ValueError("COMPACT_LIMITED_UPGRADE_FORBIDDEN")
        if messages[-1]["role"] != "user" or not 0 < len(messages[-1]["content"]) <= POLICY["max_query_chars"]:
            raise ValueError("COMPACT_QUERY_TOO_LARGE")
        if any(m["role"] not in ("user", "assistant") or len(m["content"]) > POLICY["max_history_chars"] for m in messages[1:-1]):
            raise ValueError("COMPACT_HISTORY_INVALID")
    count = body.get("max_tokens", maximum)
    if type(count) is not int or not 1 <= count <= maximum or type(body.get("cache_prompt", True)) is not bool:
        raise ValueError("COMPACT_GENERATION_BOUNDS_INVALID")
    return {"model": selected, "messages": messages, "temperature": 0.2,
            "max_tokens": count, "stream": False, "cache_prompt": body.get("cache_prompt", True)}
