"""Adaptive reasoning effort for local answers (operator request 2026-09-25).

The EXE model profile's ``reasoning_effort`` is the ceiling. Each request gets the
highest effort whose thinking budget fits the response-time budget at the measured
decode rate; a System One (decider) screen can send simple questions straight to
no-thinking. The ceiling is never raised; the model, Router preset and profile
hash are unchanged. A decider failure only removes the screen, it never blocks.
"""
from __future__ import annotations

import math
import threading
from typing import Any, Mapping

EFFORT_ORDER = ("none", "minimal", "low", "medium", "high", "xhigh", "max")
# Approximate thinking tokens each effort needs before the answer starts.
THINKING_TOKENS = {"none": 0, "minimal": 128, "low": 256, "medium": 512, "high": 1024, "xhigh": 2048, "max": 4096}
# Conservative start; the RTX 5090 lane measured about 90 tokens/s (2026-09-25).
DEFAULT_TOKENS_PER_SECOND = 60.0
TIME_SAFETY = 0.75        # share of the timeout generation may use
FIXED_OVERHEAD_SECONDS = 1.5  # prompt processing, relay and LINE delivery
SCREEN_QUESTION = "Does this question need multi-step reasoning?"
SCREEN_OPTIONS = ["SIMPLE", "COMPLEX"]


class DecodeRate:
    """Thread-safe exponential moving average of observed decode tokens per second."""

    def __init__(self, initial: float = DEFAULT_TOKENS_PER_SECOND, alpha: float = 0.3,
                 floor: float = 5.0, ceiling: float = 400.0) -> None:
        if not (0 < alpha <= 1 and 0 < floor <= initial <= ceiling):
            raise ValueError("DECODE_RATE_CONFIG_INVALID")
        self._value, self._alpha, self._floor, self._ceiling = float(initial), alpha, floor, ceiling
        self._lock = threading.Lock()

    @property
    def value(self) -> float:
        with self._lock:
            return self._value

    def observe(self, tokens: float, seconds: float) -> None:
        """Ignore tiny or invalid samples; clamp outliers into [floor, ceiling]."""
        if not (isinstance(tokens, (int, float)) and isinstance(seconds, (int, float))):
            return
        if not (math.isfinite(tokens) and math.isfinite(seconds)) or tokens < 32 or seconds <= 0.05:
            return
        sample = min(self._ceiling, max(self._floor, tokens / seconds))
        with self._lock:
            self._value += self._alpha * (sample - self._value)


def thinking_budget(timeout_ms: int, answer_tokens: int, rate: float) -> int:
    """Tokens left for thinking after the answer, inside the safe share of the timeout."""
    usable_seconds = timeout_ms / 1000 * TIME_SAFETY - FIXED_OVERHEAD_SECONDS
    return max(0, int(usable_seconds * rate) - max(0, answer_tokens))


def select_effort(ceiling: str, *, timeout_ms: int, answer_tokens: int, rate: float,
                  screen: str | None = None, max_output_tokens: int | None = None) -> dict[str, Any]:
    """Highest effort <= ceiling that fits the time budget; SIMPLE screens skip thinking."""
    if ceiling not in EFFORT_ORDER:
        raise ValueError("REASONING_CEILING_INVALID")
    if type(timeout_ms) is not int or timeout_ms <= 0 or type(answer_tokens) is not int or answer_tokens <= 0:
        raise ValueError("REASONING_BUDGET_INPUT_INVALID")
    budget = thinking_budget(timeout_ms, answer_tokens, rate)
    cap = max_output_tokens if max_output_tokens is not None else answer_tokens + THINKING_TOKENS["max"]
    effective, reason = "none", "TIME_BUDGET"
    if ceiling == "none":
        reason = "CEILING_NONE"
    elif screen == "SIMPLE":
        reason = "SYSTEM_ONE_SIMPLE"
    else:
        for effort in EFFORT_ORDER[1:EFFORT_ORDER.index(ceiling) + 1]:
            if THINKING_TOKENS[effort] <= budget and answer_tokens + THINKING_TOKENS[effort] <= cap:
                effective = effort
        if effective == ceiling:
            reason = "CEILING"
    return {"ceiling": ceiling, "effective": effective, "enable_thinking": effective != "none",
            "max_tokens": min(cap, answer_tokens + THINKING_TOKENS[effective]),
            "thinking_budget_tokens": budget, "decode_tokens_per_second": round(rate, 1),
            "screen": screen, "reason": reason}


def system_one_screen(client: Any, features: Mapping[str, Any]) -> str | None:
    """Fast CPU screen through the existing decider; None when unavailable or unsure."""
    if client is None:
        return None
    try:
        choice, _confidence = client.answer(dict(features), SCREEN_QUESTION, list(SCREEN_OPTIONS))
    except Exception:
        return None
    return choice if choice in SCREEN_OPTIONS else None


def apply_plan(upstream: Mapping[str, Any], plan: Mapping[str, Any]) -> dict[str, Any]:
    """Request-only override: thinking switch, effort label and token bound for this call."""
    request = dict(upstream)
    request["chat_template_kwargs"] = {**dict(upstream.get("chat_template_kwargs") or {}),
                                       "enable_thinking": bool(plan["enable_thinking"])}
    request["reasoning_effort"] = plan["effective"]
    request["max_tokens"] = int(plan["max_tokens"])
    return request


def estimate_tokens(result: Any) -> int:
    """Rough generated-token count when the server omits usage: CJK ~1/char, other text ~4 chars/token."""
    try:
        message = result["choices"][0]["message"]
    except (KeyError, IndexError, TypeError):
        return 0
    text = "".join(str(message.get(key) or "") for key in ("reasoning_content", "content"))
    cjk = sum(1 for ch in text if "　" <= ch <= "鿿" or "＀" <= ch <= "￯")
    return cjk + (len(text) - cjk) // 4


def question_features(query: str) -> dict[str, Any]:
    """Small, content-free description of the question for the decider (no raw text)."""
    text = query or ""
    return {"query_chars": len(text), "has_digits": any(ch.isdigit() for ch in text),
            "question_marks": text.count("?") + text.count("？"),
            "clauses": sum(text.count(mark) for mark in ("，", ",", "；", ";", "、")) + 1}
