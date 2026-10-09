"""Thin client to the EXISTING local Mapika (decider-system-one) CPU sidecar.

Protocol (read from the installed sidecar, not guessed):
  POST /v1/systemone  {"state": ..., "questions": {q: {"type": "choice", "options": [...]}}, "independent": true}
  -> {"model": str, "answers": {q: {"choice": str|None, "confidence": 0..1, "type": "choice", "probs": {...}}}}

Hard policy: loopback-only endpoint, no proxy environment (Session.trust_env=False),
no redirects, unknown/missing/malformed response fields fail closed (never
default-healthy). No cloud fallback, no escalation.
"""
from __future__ import annotations

import math
from typing import Any
from urllib.parse import urlsplit

import requests

ALLOWED_HOSTS = ("127.0.0.1", "localhost")
CHOICE = "choice"
SCALE = "scale"


class DeciderError(RuntimeError):
    """Fail-closed decision backend error (no healthy default)."""


def assert_loopback(url: str) -> str:
    parts = urlsplit(url)
    if parts.scheme != "http" or parts.hostname not in ALLOWED_HOSTS or parts.username or parts.password:
        raise DeciderError("DECIDER_ENDPOINT_MUST_BE_LOOPBACK")
    return url


class DecisionBackendClient:
    def __init__(self, base_url: str, timeout: float = 5.0, min_confidence: float = 0.70) -> None:
        assert_loopback(base_url)
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        # Declared backend routing minimum: strict finite numeric 0..1 (not
        # bool/string). Missing/invalid fails closed (never a healthy default).
        if isinstance(min_confidence, bool) or not isinstance(min_confidence, (int, float)):
            raise DeciderError("DECIDER_MIN_CONFIDENCE_INVALID")
        min_confidence = float(min_confidence)
        if not math.isfinite(min_confidence) or not 0.0 <= min_confidence <= 1.0:
            raise DeciderError("DECIDER_MIN_CONFIDENCE_INVALID")
        self.min_confidence = min_confidence
        self._session = requests.Session()
        self._session.trust_env = False  # HTTP_PROXY/HTTPS_PROXY/ALL_PROXY ignored

    def _post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        try:
            response = self._session.post(
                self.base_url + path,
                json=payload,
                timeout=self.timeout,
                allow_redirects=False,
                proxies={"http": None, "https": None},
            )
        except requests.RequestException as exc:
            # Normalize transport failures (ConnectionError/Timeout/etc.) to a
            # bounded DeciderError (no healthy default). This does NOT catch the
            # test SocketGuard's RuntimeError (not a requests.RequestException),
            # so guard blocks are never hidden here.
            raise DeciderError(f"DECIDER_TRANSPORT_FAILED:{type(exc).__name__}") from exc
        if 300 <= response.status_code < 400:
            raise DeciderError("DECIDER_REDIRECT_REFUSED")
        if response.status_code != 200:
            raise DeciderError(f"DECIDER_UPSTREAM_FAILED:{response.status_code}")
        try:
            data = response.json()
        except ValueError:
            raise DeciderError("DECIDER_RESPONSE_INVALID") from None
        return data if isinstance(data, dict) else {}

    def health(self) -> dict[str, Any]:
        try:
            response = self._session.get(
                self.base_url + "/health",
                timeout=self.timeout,
                allow_redirects=False,
                proxies={"http": None, "https": None},
            )
        except requests.RequestException as exc:
            raise DeciderError(f"DECIDER_HEALTH_TRANSPORT_FAILED:{type(exc).__name__}") from exc
        if response.status_code != 200:
            raise DeciderError(f"DECIDER_HEALTH_FAILED:{response.status_code}")
        try:
            data = response.json()
        except ValueError:
            raise DeciderError("DECIDER_HEALTH_INVALID") from None
        return data if isinstance(data, dict) else {}

    def system_one(self, state: Any, questions: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(questions, dict) or not questions:
            raise DeciderError("DECIDER_QUESTIONS_REQUIRED")
        for spec in questions.values():
            if not isinstance(spec, dict) or spec.get("type") != CHOICE or not isinstance(spec.get("options"), list):
                raise DeciderError("DECIDER_QUESTION_SPEC_INVALID")
        # Actual sidecar normalizer (render_question): questions carry
        # type + nonempty instructions + criteria/options (list supported).
        rendered = {
            q: {"type": CHOICE, "instructions": q, "options": list(spec["options"])}
            for q, spec in questions.items()
        }
        data = self._post("/v1/systemone", {"state": state, "questions": rendered, "independent": True})
        answers = data.get("answers")
        if not isinstance(answers, dict) or not answers:
            raise DeciderError("DECIDER_ANSWERS_MISSING")
        return answers

    def answer(self, state: Any, question: str, options: list[str]) -> tuple[str, float]:
        """Return (choice, confidence) for one fixed-choice question, or raise.
        Actual sidecar answer shape: {type, choice, confidence, certainty,
        probabilities} — the field is `probabilities`, not `probs`."""
        answers = self.system_one(state, {question: {"type": CHOICE, "options": list(options)}})
        entry = answers.get(question)
        if not isinstance(entry, dict):
            raise DeciderError("DECIDER_ANSWER_MISSING")
        if entry.get("type") != CHOICE:
            raise DeciderError("DECIDER_ANSWER_TYPE_INVALID")
        choice = entry.get("choice")
        if not isinstance(choice, str) or choice not in options:
            raise DeciderError("DECIDER_CHOICE_INVALID")
        confidence = entry.get("confidence")
        if isinstance(confidence, bool) or not isinstance(confidence, (int, float)):
            raise DeciderError("DECIDER_CONFIDENCE_INVALID")
        confidence = float(confidence)
        if not math.isfinite(confidence) or not 0.0 <= confidence <= 1.0:
            raise DeciderError("DECIDER_CONFIDENCE_OUT_OF_RANGE")
        if confidence < self.min_confidence:
            raise DeciderError("DECIDER_CONFIDENCE_BELOW_MINIMUM")
        probabilities = entry.get("probabilities")
        if not isinstance(probabilities, dict) or not probabilities:
            raise DeciderError("DECIDER_PROBABILITIES_INVALID")
        # Keys must exactly match the fixed options (all option keys emitted).
        if set(probabilities) != set(options):
            raise DeciderError("DECIDER_PROBABILITIES_KEYS_INVALID")
        # Each value: finite numeric in 0..1 (bool/non-numeric/NaN/inf rejected).
        for value in probabilities.values():
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise DeciderError("DECIDER_PROBABILITIES_VALUE_INVALID")
            value = float(value)
            if not math.isfinite(value) or not 0.0 <= value <= 1.0:
                raise DeciderError("DECIDER_PROBABILITIES_VALUE_OUT_OF_RANGE")
        # Vector must be normalized (sum == 1, tolerating legitimate 4dp rounding).
        total = sum(float(v) for v in probabilities.values())
        if abs(total - 1.0) > 0.0001:
            raise DeciderError("DECIDER_PROBABILITIES_UNNORMALIZED")
        # The chosen option's probability must match the confidence (4dp).
        if abs(float(probabilities[choice]) - confidence) > 0.0001:
            raise DeciderError("DECIDER_PROBABILITIES_CHOICE_MISMATCH")
        return choice, confidence