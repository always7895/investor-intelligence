"""Stage1G deterministic Python publisher -> E1/HV shared-history coverage fixture.

Synthetic, locally derived, no network and no publisher main or Production.
The tests import produce_bridge(); regeneration is an explicit CLI action.
"""
from __future__ import annotations
import copy
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
import publish_sealed_snapshot as publisher

FIXTURE = ROOT / "cloud/test/fixtures/v21-three-strategies.json"
OUTPUT = ROOT / "cloud/test/fixtures/stage1g-hv-coverage.json"


class MemoryInput:
    def __init__(self, document: dict):
        self.content = json.dumps(document, ensure_ascii=False, separators=(",", ":")).encode("utf-8")

    def read_bytes(self) -> bytes:
        return self.content


def produce_bridge() -> dict:
    cases = json.loads(FIXTURE.read_text(encoding="utf-8"))["cases"]
    cycle = copy.deepcopy(cases["yahoo_monthly_hv"])
    clock = cycle["timestamp"]
    now = datetime.strptime(clock, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    source = {"schema": "v213-market-observations-v2", "generated_at": clock,
              "quotes": {}, "options": {cycle["ticker"]: {"monthly": cycle}}}
    bodies = publisher.lazy_market_bodies(MemoryInput(source), now)
    assert set(bodies) == {"v213:options:v2", "v213:quotes:v1"}
    coverage = publisher.lazy_options_coverage_body(bodies["v213:options:v2"], now)
    assert set(coverage) == {publisher.COVERAGE_KEY}
    observed = json.loads(coverage[publisher.COVERAGE_KEY])["observed"]
    assert len(observed) == 1 and observed[0]["cycle_count"] == observed[0]["ticker_key_count"] == 1
    options = json.loads(bodies["v213:options:v2"])["options"]["AAA"]
    assert options["monthly"]["historical_volatility"] == "@" and len(options["_hv"]) == 11
    return {"schema": "stage1g-synthetic-publisher-worker-hv-parity-v1",
            "clock": clock, "options_body": bodies["v213:options:v2"],
            "coverage_body": coverage[publisher.COVERAGE_KEY]}


if __name__ == "__main__":
    doc = produce_bridge()
    OUTPUT.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    print("STAGE1G_HV_COVERAGE_FIXTURE_REGENERATED", OUTPUT.stat().st_size)
