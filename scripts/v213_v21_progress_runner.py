#!/usr/bin/env python3
"""Progress-only wrapper around the accepted v2.1 Top20 engine.

It monkey-patches observation functions only to emit unbuffered progress lines.
The scoring, ordering, evidence, output files and exception semantics remain in
``v21_serenity_top20``.
"""
from __future__ import annotations

import argparse
import json
import sys

import requests
import v21_serenity_top20 as engine


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--synthetic", action="store_true")
    args = parser.parse_args()

    original_companyfacts = engine.sec_companyfacts
    counter = {"value": 0}

    def progress_companyfacts(candidate, policy, http, headers):
        counter["value"] += 1
        limit = int(policy.get("sec_candidate_limit", 50))
        ticker = str(candidate.get("ticker") or "?")
        print(
            f"II_PROGRESS Top20 SEC companyfacts {counter['value']}/{limit} | {ticker}",
            flush=True,
        )
        return original_companyfacts(candidate, policy, http, headers)

    engine.sec_companyfacts = progress_companyfacts
    try:
        print("II_PROGRESS Top20 candidate discovery starting", flush=True)
        result = engine.run(synthetic=args.synthetic)
        print("II_PROGRESS Top20 scoring/output complete", flush=True)
        print(json.dumps(result, ensure_ascii=False, indent=2), flush=True)
        return 0
    except (engine.PipelineError, OSError, ValueError, requests.RequestException) as exc:
        print(f"V2.1 Serenity engine failed: {exc}", file=sys.stderr, flush=True)
        return 1
    finally:
        engine.sec_companyfacts = original_companyfacts


if __name__ == "__main__":
    raise SystemExit(main())
