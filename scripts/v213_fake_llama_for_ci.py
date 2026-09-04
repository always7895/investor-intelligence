#!/usr/bin/env python3
"""Loopback-only fake llama.cpp/router used by v2.1.3 Windows CI."""
from __future__ import annotations

import argparse
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--model", default="RVN-Q6_K-multilingual-mtp")
    parser.add_argument("--mode", choices=("llama", "legacy-gateway"), default="llama")
    args = parser.parse_args()
    if args.host not in {"127.0.0.1", "localhost"}:
        raise SystemExit("CI fake server must bind to loopback")

    class Handler(BaseHTTPRequestHandler):
        server_version = "InvestorIntelligenceCiFake/1"

        def log_message(self, _fmt: str, *_args: object) -> None:
            return

        def send_json(self, status: int, value: object) -> None:
            payload = json.dumps(value).encode("utf-8")
            self.send_response(status)
            self.send_header("content-type", "application/json; charset=utf-8")
            self.send_header("content-length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def do_GET(self) -> None:  # noqa: N802
            path = urlsplit(self.path).path
            if args.mode == "legacy-gateway":
                if path == "/health":
                    self.send_json(
                        200,
                        {
                            "ok": True,
                            "service": "v212-local-llm-gateway",
                            "llama_reachable": True,
                        },
                    )
                else:
                    self.send_json(404, {"error": "NOT_FOUND"})
                return
            if path == "/health":
                self.send_json(200, {"ok": True, "status": "ok"})
                return
            if path in {"/v1/models", "/models"}:
                self.send_json(200, {"data": [{"id": args.model}]})
                return
            self.send_json(404, {"error": "NOT_FOUND"})

        def do_POST(self) -> None:  # noqa: N802
            if args.mode != "llama" or urlsplit(self.path).path != "/v1/chat/completions":
                self.send_json(404, {"error": "NOT_FOUND"})
                return
            try:
                length = int(self.headers.get("content-length", "0") or "0")
                body = json.loads(self.rfile.read(length).decode("utf-8"))
            except Exception:
                self.send_json(400, {"error": "JSON_INVALID"})
                return
            if str(body.get("model") or "") != args.model:
                self.send_json(400, {"error": "MODEL_MISMATCH"})
                return
            self.send_json(
                200,
                {
                    "id": "ci-fake",
                    "object": "chat.completion",
                    "model": args.model,
                    "choices": [
                        {"index": 0, "message": {"role": "assistant", "content": "OK"}}
                    ],
                },
            )

    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print(
        f"CI fake {args.mode} listening on http://{args.host}:{args.port}; model={args.model}",
        flush=True,
    )
    server.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
