#!/usr/bin/env python3
"""Compatibility entrypoint for the final v2.1.3 source-independence gate.

The implementation lives in ``v213_source_independence_gate_v4.py``. This stable
path is retained because existing launchers and qualification scripts invoke the
v3 filename.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

V4_PATH = Path(__file__).resolve().with_name("v213_source_independence_gate_v4.py")
if not V4_PATH.is_file():
    raise RuntimeError(f"Missing final source-independence implementation: {V4_PATH}")
spec = importlib.util.spec_from_file_location(
    "investor_intelligence_v213_source_gate_v4_entrypoint",
    V4_PATH,
)
if spec is None or spec.loader is None:
    raise RuntimeError(f"Unable to load final source-independence gate: {V4_PATH}")
v4 = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = v4
spec.loader.exec_module(v4)

if __name__ == "__main__":
    if "--wrapper-self-test" in sys.argv:
        v4.self_test()
        raise SystemExit(0)
    raise SystemExit(v4.gate.main())
