#!/usr/bin/env python3
"""Finds the local OpenAI-compatible model server and the model to use (operator 2026-09-26: the local model's port
and ID change, for example TabbyAPI :5000 with Qwen3.8-27B-EXL3-5.5bpw-v2 replaced by ninfer :8080 with Qwen3.8-27B;
every local caller must still connect without a manual edit).

Servers, in order: an explicit base (II_LLAMA_BASE_URL or --base), the launcher's saved selection
(<user_config_root>/v213-model-selection.json llama_base_url), the configured base (config/local-runtime-independence-
v1.json primary_reasoner.base_url), the well-known ports (TabbyAPI 5000, llama.cpp/ninfer 8080, Ollama 11434, LM Studio
1234, 5001, 8081), then every other loopback TCP listener. Port 8000 (the System One decider) is never probed. Each probe
is one read-only GET of /v1/models, then /models, with a short timeout, no proxy and no redirect; only a reply in the
OpenAI list shape counts.

Model, per server: the wanted model (II_LOCAL_LLM_MODEL, --want, else the saved selection, else the configured model)
when served (id or alias, case-insensitive); else a served model of the same family (the id up to its parameter-count
token, e.g. Qwen3.8-27B for Qwen3.8-27B-EXL3-5.5bpw-v2); else the only model the server lists. Several unrelated models
and no family match give no automatic choice. The best match wins across servers (exact, then family, then only);
the earlier server wins a tie. The result names the served id, so callers verify replies against the model that is
actually loaded and label it; nothing is substituted silently.

CLI: python scripts/local_model_endpoint.py [--want MODEL] [--base URL] -> one JSON line; exit 0 when found, 3 when not.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Callable, Iterable
from urllib.parse import urlsplit
from urllib.request import ProxyHandler, Request, build_opener

ROOT = Path(__file__).resolve().parents[1]
LOCAL_RUNTIME_CONFIG = ROOT / "config" / "local-runtime-independence-v1.json"
KNOWN_PORTS = (5000, 8080, 11434, 1234, 5001, 8081)
NEVER_PROBED = {8000}  # System One decider
MAX_LISTENERS = 48
PROBE_TIMEOUT = 2.0
_SIZE_TOKEN = re.compile(r"^\d+(?:\.\d+)?[BbMm]$")
_LOOPBACK = ("127.0.0.1", "localhost", "::1")
RANK = {"exact": 0, "family": 1, "only": 2}


def model_family(model_id: str) -> str:
    """Qwen3.8-27B-EXL3-5.5bpw-v2 -> qwen3.8-27b; an id without a parameter-count token is its own family."""
    parts = str(model_id or "").strip().split("-")
    for index, token in enumerate(parts):
        if _SIZE_TOKEN.match(token):
            return "-".join(parts[: index + 1]).lower()
    return str(model_id or "").strip().lower()


def loopback_base(url: str) -> str | None:
    """http://127.0.0.1:PORT or http://localhost:PORT (optionally ending in /v1) without credentials, query or fragment."""
    try:
        parts = urlsplit(str(url or "").strip())
        port = parts.port
    except ValueError:
        return None
    if parts.scheme != "http" or parts.hostname not in _LOOPBACK or parts.username or parts.password or parts.query or parts.fragment:
        return None
    if parts.path.rstrip("/") not in ("", "/v1") or port in NEVER_PROBED:
        return None
    return f"http://{'127.0.0.1' if parts.hostname == 'localhost' else parts.hostname}:{port or 80}"


def listening_ports() -> list[int]:
    """Loopback-reachable TCP listeners (Windows netstat); an empty list when unavailable."""
    try:
        text = subprocess.run(["netstat", "-ano", "-p", "TCP"], capture_output=True, text=True, timeout=10,
                              errors="replace").stdout
    except (OSError, subprocess.SubprocessError):
        return []
    ports: set[int] = set()
    for line in text.splitlines():
        fields = line.split()
        if len(fields) >= 4 and fields[0].upper() == "TCP" and "LISTEN" in fields[3].upper():
            host, _, port = fields[1].rpartition(":")
            if host in ("127.0.0.1", "0.0.0.0", "[::]", "[::1]") and port.isdigit():
                ports.add(int(port))
    return sorted(port for port in ports if 1024 <= port <= 65535 and port not in NEVER_PROBED)


def _user_config_root() -> Path | None:
    try:
        state = json.loads(Path(os.environ["LOCALAPPDATA"], "InvestorIntelligence", "install-state.json").read_text(encoding="utf-8-sig"))
        return Path(state["user_config_root"])
    except Exception:
        return None


def saved_selection() -> dict[str, str]:
    root = _user_config_root()
    try:
        value = json.loads((root / "v213-model-selection.json").read_text(encoding="utf-8-sig")) if root else {}
    except Exception:
        value = {}
    return {"model": str(value.get("model") or ""), "base": str(value.get("llama_base_url") or "")}


def configured_reasoner(path: Path = LOCAL_RUNTIME_CONFIG) -> dict[str, str]:
    try:
        reasoner = json.loads(path.read_text(encoding="utf-8"))["primary_reasoner"]
        return {"model": str(reasoner.get("model") or ""), "base": str(reasoner.get("base_url") or "")}
    except Exception:
        return {"model": "", "base": ""}


def read_catalog(base: str) -> list[dict[str, Any]] | None:
    """Model rows ({"id", "aliases"}) from GET /v1/models or /models; None when the server gives no list."""
    opener = build_opener(ProxyHandler({}))
    for suffix in ("/v1/models", "/models"):
        try:
            request = Request(base + suffix, headers={"Accept": "application/json", "Cache-Control": "no-cache"})
            with opener.open(request, timeout=PROBE_TIMEOUT) as response:  # noqa: S310 - loopback only
                if response.geturl().rstrip("/") != (base + suffix).rstrip("/"):
                    continue  # a redirect is not a model catalog
                payload = json.loads(response.read(2_000_000).decode("utf-8"))
        except Exception:
            continue
        rows = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(rows, list):
            continue
        models = []
        for row in rows[:256]:
            ident = row if isinstance(row, str) else (row.get("id") if isinstance(row, dict) else None)
            if isinstance(ident, str) and ident.strip():
                aliases = row.get("aliases") if isinstance(row, dict) and isinstance(row.get("aliases"), list) else []
                models.append({"id": ident.strip(), "aliases": [str(alias) for alias in aliases if isinstance(alias, str)]})
        if models:
            return models
    return None


def choose_model(catalog: list[dict[str, Any]], wanted: Iterable[str]) -> tuple[str, str] | None:
    """(served id, exact|family|only) for one server's catalog."""
    wanted = [str(model).strip() for model in wanted if str(model or "").strip()]
    for model in wanted:
        for row in catalog:
            if model.lower() in [row["id"].lower(), *(alias.lower() for alias in row["aliases"])]:
                return row["id"], "exact"
    for model in wanted:
        family = model_family(model)
        matches = [row["id"] for row in catalog if model_family(row["id"]) == family]
        if len(matches) == 1:
            return matches[0], "family"
    if len(catalog) == 1:
        return catalog[0]["id"], "only"
    return None


def candidate_bases(explicit: str = "") -> list[str]:
    """The addresses probed first; other loopback listeners follow only when none of these serves the wanted model."""
    saved, configured = saved_selection(), configured_reasoner()
    ordered = [explicit, os.getenv("II_LLAMA_BASE_URL", ""), saved["base"], configured["base"],
               *(f"http://127.0.0.1:{port}" for port in KNOWN_PORTS)]
    bases: list[str] = []
    for value in ordered:
        base = loopback_base(value)
        if base and base not in bases:
            bases.append(base)
    return bases


def resolve(want: str = "", base: str = "", *, catalog_reader: Callable[[str], list[dict[str, Any]] | None] = read_catalog,
            listeners: Callable[[], list[int]] = listening_ports) -> dict[str, Any]:
    wanted = [want, os.getenv("II_LOCAL_LLM_MODEL", ""), saved_selection()["model"], configured_reasoner()["model"]]
    wanted = [model for index, model in enumerate(wanted) if model and model not in wanted[:index]]
    bases = candidate_bases(base)
    best: dict[str, Any] | None = None
    seen: list[dict[str, Any]] = []

    def scan(batch: list[str]) -> None:
        nonlocal best
        with ThreadPoolExecutor(max_workers=8) as pool:
            catalogs = list(pool.map(catalog_reader, batch))
        for server, catalog in zip(batch, catalogs):
            if not catalog:
                continue
            seen.append({"base_url": server, "models": [row["id"] for row in catalog][:16]})
            choice = choose_model(catalog, wanted)
            if choice and (best is None or RANK[choice[1]] < RANK[best["match"]]):
                best = {"base_url": server, "model": choice[0], "match": choice[1]}

    scan(bases)
    if best is None or best["match"] != "exact":
        extra = [f"http://127.0.0.1:{port}" for port in listeners() if port not in NEVER_PROBED]
        extra = [server for server in extra if server not in bases][:MAX_LISTENERS]
        scan(extra)
        bases += extra
    if best is None:
        return {"error": "LOCAL_MODEL_NOT_FOUND" if not seen else "LOCAL_MODEL_AMBIGUOUS", "wanted": wanted,
                "servers": seen, "probed": len(bases)}
    best.update({"wanted": wanted, "servers": seen, "probed": len(bases),
                 "changed": bool(wanted) and best["model"].lower() != wanted[0].lower()})
    return best


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--want", default="")
    parser.add_argument("--base", default="")
    args = parser.parse_args(list(argv) if argv is not None else None)
    result = resolve(args.want, args.base)
    print(json.dumps(result, ensure_ascii=True, separators=(",", ":")))
    return 0 if "error" not in result else 3


if __name__ == "__main__":
    sys.exit(main())
