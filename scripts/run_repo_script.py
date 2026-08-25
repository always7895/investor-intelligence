#!/usr/bin/env python3
"""Run one reviewed sibling script under isolated portable Python.

Some reviewed portable Python distributions intentionally omit both the current
working directory and the script directory from ``sys.path``. This launcher adds
only the repository's static ``scripts/`` directory, rejects path traversal and
then executes exactly one named sibling ``.py`` file. It never loads plugins,
searches external paths or executes arbitrary code strings.
"""
from __future__ import annotations

import re
import runpy
import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent
SCRIPT_NAME_RE = re.compile(r"^[a-z][a-z0-9_]{1,79}\.py$")


class RepositoryScriptError(ValueError):
    """Raised when the requested repository script is not a safe sibling."""


def resolve_script(name: object, scripts_dir: Path = SCRIPTS_DIR) -> Path:
    value = str(name or "").strip()
    if not SCRIPT_NAME_RE.fullmatch(value):
        raise RepositoryScriptError("Script name must be one lowercase sibling .py filename")
    target = (scripts_dir / value).resolve()
    try:
        target.relative_to(scripts_dir.resolve())
    except ValueError as exc:
        raise RepositoryScriptError("Script path escapes the reviewed scripts directory") from exc
    if target == Path(__file__).resolve():
        raise RepositoryScriptError("The repository launcher cannot recursively launch itself")
    if not target.is_file() or target.is_symlink():
        raise RepositoryScriptError(f"Reviewed repository script does not exist: {value}")
    return target


def run_script(name: object) -> None:
    target = resolve_script(name)
    scripts_text = str(SCRIPTS_DIR)
    if scripts_text not in sys.path:
        sys.path.insert(0, scripts_text)
    sys.argv = [str(target), *sys.argv[2:]]
    runpy.run_path(str(target), run_name="__main__")


def main() -> int:
    if len(sys.argv) < 2:
        print("REPOSITORY SCRIPT LAUNCH FAILED: a sibling script name is required")
        return 2
    try:
        run_script(sys.argv[1])
    except (OSError, RepositoryScriptError) as exc:
        print(f"REPOSITORY SCRIPT LAUNCH FAILED: {exc}")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
