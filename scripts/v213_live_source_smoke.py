#!/usr/bin/env python3
"""Non-mutating live smoke test for reviewed v2.1.3 source families.

This does not publish data or touch Production. It verifies the current response
shape of the official World Bank, BLS, ECB and Nasdaq endpoints and performs one
GLEIF legal-entity query. SEC live access remains exercised by the normal local
pipeline, which supplies the owner's configured fair-access contact rather than
inventing one in CI.
"""
from __future__ import annotations

import argparse
import json
import sys
from typing import Any

import requests

import v213_source_federation as federation


def run_live() -> dict[str, Any]:
    session = requests.Session()
    session.headers.update({
        "user-agent": "Investor Intelligence reviewed public-source smoke test",
        "accept-encoding": "gzip, deflate",
    })
    result: dict[str, Any] = {}
    world_bank = federation.fetch_world_bank(session)
    result["world_bank"] = {
        "status": world_bank["status"],
        "as_of": world_bank["as_of"],
        "series": world_bank["detail"]["series"],
    }
    bls = federation.fetch_bls(session)
    result["bls"] = {
        "status": bls["status"],
        "series_count": len(bls["detail"]["series"]),
    }
    ecb = federation.fetch_ecb(session)
    result["ecb"] = {
        "status": ecb["status"],
        "as_of": ecb["as_of"],
        "series": ecb["detail"]["series"],
    }
    listings, nasdaq = federation.fetch_nasdaq(session)
    result["nasdaq"] = {
        "status": nasdaq["status"],
        "symbol_count": len(listings),
        "nvda_present": "NVDA" in listings,
    }
    gleif = federation.fetch_gleif(session, "NVIDIA Corporation")
    result["gleif"] = {
        "status": "HEALTHY" if gleif else "DEGRADED",
        "matched": bool(gleif),
        "lei_present": bool(gleif and gleif.get("lei")),
    }
    required_healthy = all(
        result[name]["status"] == "HEALTHY"
        for name in ("world_bank", "bls", "ecb", "nasdaq")
    )
    if not required_healthy or not result["nasdaq"]["nvda_present"]:
        raise RuntimeError("Required official live-source smoke gate failed")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true")
    args = parser.parse_args()
    if not args.live:
        print("V213_LIVE_SOURCE_SMOKE_SELF_TEST = PASS; live_network_not_requested=true")
        return 0
    result = run_live()
    print("V213_LIVE_SOURCE_SMOKE = PASS")
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (RuntimeError, requests.RequestException, ValueError, KeyError) as exc:
        print(f"V213_LIVE_SOURCE_SMOKE = FAIL; {type(exc).__name__}: {exc}", file=sys.stderr)
        raise SystemExit(1)
