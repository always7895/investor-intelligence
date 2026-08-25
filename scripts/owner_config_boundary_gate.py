#!/usr/bin/env python3
"""Fail closed when owner-specific research configuration enters the repository.

Local research universe/preferences may exist only in ignored ``*.local.json``
files or explicit external paths. Shared LINE/Worker code must not import the
local configuration loader.
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FORBIDDEN_TRACKED = (
    ROOT / "config" / "watchlist.json",
    ROOT / "config" / "user-preferences.json",
)
REQUIRED_EXAMPLES = (
    ROOT / "config" / "research-universe.example.json",
    ROOT / "config" / "user-preferences.example.json",
)
SHARED_BOUNDARY_PATHS = (
    ROOT / "cloud",
    ROOT / "scripts" / "build_line_public_options.py",
    ROOT / "scripts" / "sync_to_kv.py",
    ROOT / "scripts" / "line_public_boundary_gate.py",
)
FORBIDDEN_SHARED_MARKERS = (
    "local_research_config",
    "research-universe.local.json",
    "user-preferences.local.json",
    "LOCAL_RESEARCH_UNIVERSE_PATH",
    "LOCAL_USER_PREFERENCES_PATH",
)


def _iter_text_files(path: Path):
    if path.is_file():
        yield path
        return
    if not path.is_dir():
        return
    for candidate in path.rglob("*"):
        if candidate.is_file() and candidate.suffix.casefold() in {
            ".py",
            ".ts",
            ".json",
            ".toml",
            ".md",
        }:
            yield candidate


def main() -> int:
    errors: list[str] = []
    for path in FORBIDDEN_TRACKED:
        if path.exists():
            errors.append(f"forbidden tracked owner configuration exists: {path.relative_to(ROOT)}")
    for path in REQUIRED_EXAMPLES:
        if not path.is_file():
            errors.append(f"required generic example missing: {path.relative_to(ROOT)}")

    ignore = (ROOT / ".gitignore").read_text(encoding="utf-8")
    if "config/*.local.json" not in ignore:
        errors.append(".gitignore must ignore config/*.local.json")

    universe_example = json.loads(REQUIRED_EXAMPLES[0].read_text(encoding="utf-8"))
    if universe_example.get("privacy_class") != "local_user_configuration":
        errors.append("research universe example lacks local privacy classification")
    tickers = [
        str(item.get("ticker") or "").upper()
        for item in universe_example.get("stocks", [])
        if isinstance(item, dict)
    ]
    if tickers != ["EXAMPLE"]:
        errors.append("research universe example must contain only the generic EXAMPLE ticker")

    for boundary in SHARED_BOUNDARY_PATHS:
        for path in _iter_text_files(boundary):
            text = path.read_text(encoding="utf-8", errors="replace")
            for marker in FORBIDDEN_SHARED_MARKERS:
                if marker in text:
                    errors.append(
                        f"shared LINE/Worker boundary references local owner configuration: "
                        f"{path.relative_to(ROOT)}"
                    )
                    break

    if errors:
        for error in sorted(set(errors)):
            print(f"ERROR: {error}")
        return 1
    print("OWNER CONFIGURATION BOUNDARY PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
