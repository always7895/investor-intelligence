#!/usr/bin/env python3
"""R75 exact-model local gateway.

The caller may omit ``model`` or repeat the model selected in the launcher.  A
request may never substitute another router model.  The upstream request is
always rewritten to the selected model ID.
"""
from __future__ import annotations

import argparse
import hmac
import json
import os
from http.server import ThreadingHTTPServer
from typing import Any

import requests

import v213_local_llm_gateway as v213


class R75GatewayHandler(v213.V213GatewayHandler):
    server_version = "InvestorIntelligenceLocalGateway/2.1.3-R75"

    def do_POST(self) -> None:  # noqa: N802
        if self.path.split("?", 1)[0] != "/v1/chat/completions":
            self._json(404, {"error": "NOT_FOUND"})
            return
        expected_secret = os.getenv("II_LOCAL_LLM_SHARED_SECRET", "")
        supplied_secret = self.headers.get("x-investor-shared-secret", "")
        if len(expected_secret) < 32 or not hmac.compare_digest(
            expected_secret,
            supplied_secret,
        ):
            self._json(401, {"error": "UNAUTHORIZED"})
            return
        try:
            length = int(self.headers.get("content-length", "0") or "0")
        except ValueError:
            length = 0
        if length <= 0 or length > v213.base.MAX_BODY:
            self._json(413, {"error": "BODY_SIZE_INVALID"})
            return
        try:
            body = json.loads(self.rfile.read(length).decode("utf-8"))
        except Exception:
            self._json(400, {"error": "JSON_INVALID"})
            return
        if not isinstance(body, dict):
            self._json(400, {"error": "JSON_OBJECT_REQUIRED"})
            return
        messages = body.get("messages")
        if not isinstance(messages, list):
            self._json(400, {"error": "MESSAGES_REQUIRED"})
            return

        selected = os.getenv("II_LOCAL_LLM_MODEL", "").strip()
        requested = str(body.get("model") or "").strip()
        if not selected:
            self._json(503, {"error": "SELECTED_MODEL_NOT_CONFIGURED"})
            return
        if requested and requested.casefold() != selected.casefold():
            self._json(
                409,
                {
                    "error": "MODEL_PIN_MISMATCH",
                    "selected_model": selected,
                    "requested_model": requested,
                },
            )
            return

        try:
            enriched, context = v213.enrich_messages(messages)
            temperature = v213.base.safe_float(body.get("temperature"))
            upstream: dict[str, Any] = {
                "model": selected,
                "messages": enriched,
                "temperature": min(
                    0.4,
                    max(0.0, temperature if temperature is not None else 0.2),
                ),
                "max_tokens": min(
                    1800,
                    max(256, int(body.get("max_tokens") or 1400)),
                ),
                "stream": False,
            }
            response = requests.post(
                v213.base.llama_url(),
                json=upstream,
                headers={"content-type": "application/json"},
                timeout=(5, 180),
            )
            if not response.ok:
                self._json(
                    502,
                    {
                        "error": "LLAMA_UPSTREAM_FAILED",
                        "status": response.status_code,
                    },
                )
                return
            result = response.json()
            if isinstance(result, dict):
                result["ii_exact_model_pin"] = {
                    "selected_model": selected,
                    "request_model_substitution_allowed": False,
                }
                if isinstance(context, dict):
                    result["ii_source_ensemble"] = {
                        "successful_source_families": context.get(
                            "successful_source_families",
                            [],
                        ),
                        "source_diversity_status": context.get(
                            "source_diversity_status",
                            "UNKNOWN",
                        ),
                        "model_confidence_cap": context.get(
                            "model_confidence_cap",
                            "LIMITED",
                        ),
                    }
            self._json(200, result)
        except Exception as exc:
            self._json(
                502,
                {
                    "error": "LOCAL_GATEWAY_FAILED",
                    "detail": type(exc).__name__,
                },
            )


def self_test() -> None:
    selected = "qwen38-xhigh"
    assert selected.casefold() == "QWEN38-XHIGH".casefold()
    assert selected.casefold() != "other-model".casefold()
    health = v213._build_health_payload(
        selected,
        [selected, "other-model"],
        True,
        {"source_independence_status": "PASS"},
    )
    assert health["selected_model"] == selected
    assert health["selected_model_available"] is True
    print(
        "V213_R75_LOCAL_LLM_GATEWAY_SELF_TEST = PASS; "
        "exact_model_pin=true; model_substitution=false"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default=v213.base.HOST)
    parser.add_argument("--port", type=int, default=v213.base.PORT)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return 0
    if args.host not in {"127.0.0.1", "localhost"}:
        raise SystemExit("Gateway must bind to loopback only")
    if len(os.getenv("II_LOCAL_LLM_SHARED_SECRET", "")) < 32:
        raise SystemExit("II_LOCAL_LLM_SHARED_SECRET must be configured")
    selected = os.getenv("II_LOCAL_LLM_MODEL", "").strip()
    if not selected:
        raise SystemExit("II_LOCAL_LLM_MODEL must be configured")
    v213.base.enrich_messages = v213.enrich_messages
    server = ThreadingHTTPServer((args.host, args.port), R75GatewayHandler)
    print(
        "Investor Intelligence v2.1.3 R75 exact-model gateway listening on "
        f"http://{args.host}:{args.port}; model={selected}",
        flush=True,
    )
    server.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
