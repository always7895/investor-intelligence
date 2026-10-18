#!/usr/bin/env python3
"""Deterministic generator for the publication-mode contract v2 fixtures.

Writes, under --out-root (default: --root):

* tests/fixtures/v213-r75-publication-mode/mixed.json
    the 10 EVIDENCE_QUALIFIED rows get a structurally valid ``claim_evidence_audit``
    (two independent lineages, one agreeing value); the 10 LIMITED rows get the
    non-qualifying audit the producer emits for them (never recounted). The embedded
    JSON strings are re-serialised, ``bundle.sha256`` and ``contract_sha256`` are
    recomputed together.
* tests/fixtures/v213-r75-publication-mode/all-limited.json
    only ``contract_id`` and ``contract_sha256`` move.
* tests/fixtures/v213-r75-publication-mode/claim-recount-vectors.json
    the ONE shared vector file executed by the Python unittest
    (tests/test_v213_publication_mode_claim_recount.py) and by Vitest
    (cloud/test/v213-claim-recount.test.ts). Expectations are authored here as
    literals; they are never computed by either implementation.

Idempotent: running it twice (or on already regenerated fixtures) yields the same
bytes. ``--check`` writes nothing and exits 1 when a file would change.

    python -I tests/fixtures/make_v213_r75_publication_mode_v2_fixtures.py
    python -I tests/fixtures/make_v213_r75_publication_mode_v2_fixtures.py --check

The contract hash is the repository's canonical-JSON hash (the same function as
scripts/v213_r75_activation_preflight.py contract_sha256 and the Worker's
r75PublicationModeContractHash).
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
CONTRACT_RELATIVE = "config/v213-r75-publication-mode-v2.json"
FIXTURE_DIR = "tests/fixtures/v213-r75-publication-mode"
EQ = "EVIDENCE_QUALIFIED"
STAMP_VALID_HOURS = 1


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def compact(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def render(value: Any) -> bytes:
    """Fixture file format: indent 2, sorted keys, CRLF, trailing newline."""
    text = json.dumps(value, indent=2, ensure_ascii=False, sort_keys=True) + "\n"
    return text.replace("\n", "\r\n").encode("utf-8")


# --------------------------------------------------------------------------- audits


def _hex(seed: str) -> str:
    return sha256_text(seed)


def evidence_row(ticker: str, index: int, stamp: str, expiry: str, claim_id: str, **overrides: Any) -> dict[str, Any]:
    row = {
        "observation_id": f"{ticker}-obs-{index}",
        "source_id": f"synthetic-source-{index}",
        "url": f"https://source-{index}.example.test/{ticker}/revenue",
        "domain": f"source-{index}.example.test",
        "source_class": "primary_filing" if index == 0 else "independent_press",
        "publisher": f"Synthetic Publisher {index}",
        "published_at": stamp,
        "retrieved_at": stamp,
        "as_of": stamp,
        "source_health": "HEALTHY",
        "primary": index == 0,
        "independence_group": f"{ticker}-publisher-{index}",
        "origin_group": f"{ticker}-origin-{index}",
        "claim_ids": [claim_id],
        "claim_type": "issuer_financial_statement",
        "freshness": "CURRENT",
        "confidence": 1.0 if index == 0 else 0.6,
        "valid_until": expiry,
        "content_sha256": _hex(f"{ticker}-content-{index}"),
        "passage": "Synthetic fixture passage; not a real filing.",
        "value": 100,
        "admitted": True,
        "correction_status": "ORIGINAL",
        "supersedes_observation_id": None,
        "subject": ticker,
        "metric": "revenue",
        "period": "2026Q2",
        "unit": "USD",
    }
    row.update(overrides)
    return row


def supported_audit(ticker: str, stamp: str, expiry: str, lineages: int = 2) -> dict[str, Any]:
    claim_id = f"{ticker}:revenue"
    rows = [evidence_row(ticker, index, stamp, expiry, claim_id) for index in range(lineages)]
    claim = {
        "claim_id": claim_id,
        "status": "SUPPORTED",
        "independent_evidence_families": lineages,
        "primary_source_count": 1,
        "high_confidence_eligible": True,
        "confidence": 1.0,
        "value": 100,
        "authority_candidate": {"observation_id": rows[0]["observation_id"], "value": 100},
        "conflict_set": [],
        "evidence_ids": [row["observation_id"] for row in rows],
        "superseded_observation_ids": [],
        "reasons": [],
    }
    return {
        "schema_version": 2,
        "status": "SUPPORTED",
        "claims": [claim],
        "evidence": rows,
        "validated_at": stamp,
        "valid_until": expiry,
        "rejected_observation_count": 0,
        "input_limit_exceeded": False,
        "all_material_claims_supported": True,
        "full_research_eligible": False,
    }


def limited_audit(ticker: str, stamp: str, expiry: str) -> dict[str, Any]:
    """What the producer emits for a row without exact-claim support (never recounted)."""
    audit = supported_audit(ticker, stamp, expiry, lineages=1)
    claim = audit["claims"][0]
    claim.update(
        status="SINGLE_SOURCE", high_confidence_eligible=False, confidence=0.49,
        independent_evidence_families=1, reasons=["INDEPENDENT_CORROBORATION_REQUIRED"],
    )
    audit.update(status="UNAVAILABLE", all_material_claims_supported=False)
    return audit


# --------------------------------------------------------------------------- fixtures


def _timestamp_plus_hours(stamp: str, hours: int) -> str:
    from datetime import datetime, timedelta, timezone

    parsed = datetime.fromisoformat(stamp.replace("Z", "+00:00")).astimezone(timezone.utc)
    return (parsed + timedelta(hours=hours)).isoformat().replace("+00:00", "Z")


def regenerate_fixture(document: dict[str, Any], contract_id: str, contract_hash: str, with_audits: bool) -> dict[str, Any]:
    result = copy.deepcopy(document)
    result["contract_id"] = contract_id
    result["contract_sha256"] = contract_hash
    if not with_audits:
        return result
    bundle = result["bundle"]
    stamp = str(result["evaluated_at"])
    expiry = _timestamp_plus_hours(stamp, STAMP_VALID_HOURS)
    source = json.loads(bundle["payloads"]["source_independence_json"])
    for record in source["records"]:
        mode = record.get("publication_evidence_mode")
        ticker = str(record["ticker"])
        record["claim_evidence_audit"] = (
            supported_audit(ticker, stamp, expiry) if mode == EQ else limited_audit(ticker, stamp, expiry)
        )
    text = compact(source)
    bundle["payloads"]["source_independence_json"] = text
    bundle["sha256"]["source_independence_json"] = sha256_text(text)
    return result


# --------------------------------------------------------------------------- vectors


def _row(audit: Any, **extra: Any) -> dict[str, Any]:
    row: dict[str, Any] = {"ticker": "T00"}
    row.update(extra)
    if audit is not None:
        row["claim_evidence_audit"] = audit
    return row


def vectors() -> dict[str, Any]:
    stamp, expiry = "2026-01-02T03:04:05Z", "2026-01-02T04:04:05Z"

    def valid(lineages: int = 2) -> dict[str, Any]:
        return supported_audit("T00", stamp, expiry, lineages)

    def case(name: str, rule: str, expected: bool, audit: Any, minimum: Any = 2, **extra: Any) -> dict[str, Any]:
        return {"name": name, "rule": rule, "minimum_families": minimum, "expected": expected, "row": _row(audit, **extra)}

    def mutated(fn) -> dict[str, Any]:
        audit = valid()
        fn(audit)
        return audit

    def ev(audit: dict[str, Any], index: int) -> dict[str, Any]:
        return audit["evidence"][index]

    cases: list[dict[str, Any]] = [case("valid two independent lineages", "positive", True, valid())]

    # Rule 1: audit shape.
    cases += [
        case("rule1 audit absent", "1", False, None),
        case("rule1 audit is a list", "1", False, []),
        case("rule1 audit is null", "1", False, None, claim_evidence_audit=None),
        case("rule1 schema_version 1", "1", False, mutated(lambda a: a.update(schema_version=1))),
        case("rule1 schema_version string", "1", False, mutated(lambda a: a.update(schema_version="2"))),
        case("rule1 schema_version true", "1", False, mutated(lambda a: a.update(schema_version=True))),
        case("rule1 schema_version missing", "1", False, mutated(lambda a: a.pop("schema_version"))),
        case("rule1 all_material_claims_supported false", "1", False, mutated(lambda a: a.update(all_material_claims_supported=False))),
        case("rule1 all_material_claims_supported string", "1", False, mutated(lambda a: a.update(all_material_claims_supported="true"))),
        case("rule1 claims missing", "1", False, mutated(lambda a: a.pop("claims"))),
        case("rule1 claims empty", "1", False, mutated(lambda a: a.update(claims=[]))),
        case("rule1 claims is an object", "1", False, mutated(lambda a: a.update(claims={}))),
        case("rule1 evidence missing", "1", False, mutated(lambda a: a.pop("evidence"))),
        case("rule1 evidence is an object", "1", False, mutated(lambda a: a.update(evidence={}))),
    ]

    # Rule 2: claim shape.
    two_claims = valid()
    second = copy.deepcopy(two_claims["claims"][0])
    second["claim_id"] = "T00:margin"
    two_claims["claims"].append(second)
    for row in copy.deepcopy(two_claims["evidence"]):
        row["observation_id"] = row["observation_id"].replace("obs", "mobs")
        row["claim_ids"] = ["T00:margin"]
        row["independence_group"] += "-m"
        row["origin_group"] += "-m"
        row["content_sha256"] = _hex(row["observation_id"])
        two_claims["evidence"].append(row)
    second["evidence_ids"] = ["T00-mobs-0", "T00-mobs-1"]
    duplicate = valid()
    duplicate["claims"].append(copy.deepcopy(duplicate["claims"][0]))
    unsupported_second = copy.deepcopy(two_claims)
    unsupported_second["claims"][1]["status"] = "UNAVAILABLE"
    cases += [
        case("rule2 two supported claims", "2", True, two_claims),
        case("rule2 second claim unsupported", "2", False, unsupported_second),
        case("rule2 claim is null", "2", False, mutated(lambda a: a.update(claims=[None]))),
        case("rule2 claim_id missing", "2", False, mutated(lambda a: a["claims"][0].pop("claim_id"))),
        case("rule2 claim_id blank", "2", False, mutated(lambda a: a["claims"][0].update(claim_id="  "))),
        case("rule2 claim_id not a string", "2", False, mutated(lambda a: a["claims"][0].update(claim_id=5))),
        case("rule2 duplicate claim_id", "2", False, duplicate),
        case("rule2 status SINGLE_SOURCE", "2", False, mutated(lambda a: a["claims"][0].update(status="SINGLE_SOURCE"))),
        case("rule2 high_confidence_eligible false", "2", False, mutated(lambda a: a["claims"][0].update(high_confidence_eligible=False))),
        case("rule2 high_confidence_eligible string", "2", False, mutated(lambda a: a["claims"][0].update(high_confidence_eligible="true"))),
        case("rule2 conflict_set non-empty", "2", False, mutated(lambda a: a["claims"][0].update(conflict_set=[{"observation_id": "x", "value": 99}]))),
        case("rule2 conflict_set absent", "2", True, mutated(lambda a: a["claims"][0].pop("conflict_set"))),
        case("rule2 conflict_set null", "2", True, mutated(lambda a: a["claims"][0].update(conflict_set=None))),
        case("rule2 evidence_ids missing", "2", False, mutated(lambda a: a["claims"][0].pop("evidence_ids"))),
        case("rule2 evidence_ids is a string", "2", False, mutated(lambda a: a["claims"][0].update(evidence_ids="T00-obs-0 T00-obs-1"))),
    ]

    # Rule 3: which evidence rows are bound to the claim.
    three = valid(3)
    three["evidence"][2]["admitted"] = False
    cases += [
        case("rule3 non-admitted extra row ignored", "3", True, three),
        case("rule3 admitted false drops a lineage", "3", False, mutated(lambda a: ev(a, 1).update(admitted=False))),
        case("rule3 admitted string is not admitted", "3", False, mutated(lambda a: ev(a, 1).update(admitted="true"))),
        case("rule3 freshness STALE drops a lineage", "3", False, mutated(lambda a: ev(a, 1).update(freshness="STALE"))),
        case("rule3 observation not in evidence_ids", "3", False, mutated(lambda a: a["claims"][0].update(evidence_ids=["T00-obs-0"]))),
        case("rule3 row claim_ids missing", "3", False, mutated(lambda a: ev(a, 1).pop("claim_ids"))),
        case("rule3 row claim_ids lacks the claim", "3", False, mutated(lambda a: ev(a, 1).update(claim_ids=["other"]))),
        case("rule3 row claim_ids is a string", "3", False, mutated(lambda a: ev(a, 1).update(claim_ids="T00:revenue"))),
        case("rule3 null evidence row skipped", "3", True, mutated(lambda a: a["evidence"].append(None))),
        case("rule3 bound rows may all be absent", "3", False, mutated(lambda a: a.update(evidence=[]))),
    ]

    # Rule 4: lineage merge and the families threshold.
    chain = valid(4)
    ev(chain, 1)["independence_group"] = ev(chain, 0)["independence_group"]
    ev(chain, 2)["origin_group"] = ev(chain, 1)["origin_group"]
    ev(chain, 3)["content_sha256"] = ev(chain, 2)["content_sha256"]
    two_of_three = valid(3)
    ev(two_of_three, 1)["origin_group"] = ev(two_of_three, 0)["origin_group"]
    cases += [
        case("rule4 same publisher merges", "4", False, mutated(lambda a: ev(a, 1).update(independence_group=ev(a, 0)["independence_group"]))),
        case("rule4 same origin merges", "4", False, mutated(lambda a: ev(a, 1).update(origin_group=ev(a, 0)["origin_group"]))),
        case("rule4 same content hash merges", "4", False, mutated(lambda a: ev(a, 1).update(content_sha256=ev(a, 0)["content_sha256"]))),
        case("rule4 transitive chain is one lineage", "4", False, chain),
        case("rule4 three rows two lineages", "4", True, two_of_three),
        case("rule4 minimum 3 with two lineages", "4", False, valid(2), minimum=3),
        case("rule4 minimum 3 with three lineages", "4", True, valid(3), minimum=3),
        case("rule4 minimum 1 is refused", "4", False, valid(), minimum=1),
        case("rule4 minimum 0 is refused", "4", False, valid(), minimum=0),
        case("rule4 minimum true is refused", "4", False, valid(), minimum=True),
        case("rule4 minimum string is refused", "4", False, valid(), minimum="2"),
        case("rule4 publisher text not coerced", "4", False, mutated(lambda a: (ev(a, 0).update(independence_group=7, origin_group=None, content_sha256=3.5)))),
        case("rule4 payload origin fallback merges", "4", False, mutated(lambda a: (ev(a, 0).pop("origin_group"), ev(a, 1).pop("origin_group"), ev(a, 0).update(payload={"origin_group": "shared"}), ev(a, 1).update(payload={"origin_group": "shared"}), ev(a, 0).update(independence_group="p0"), ev(a, 1).update(independence_group="p1"), ev(a, 0).update(content_sha256="a" * 64), ev(a, 1).update(content_sha256="b" * 64)))),
        case("rule4 truthy non-string origin blocks payload fallback", "4", True, mutated(lambda a: (ev(a, 0).update(origin_group=5, payload={"origin_group": "shared"}), ev(a, 1).pop("origin_group"), ev(a, 1).update(payload={"origin_group": "shared"})))),
    ]

    # Rule 5: value agreement.
    cases += [
        case("rule5 values differ", "5", False, mutated(lambda a: ev(a, 1).update(value=101))),
        case("rule5 string value vs number", "5", False, mutated(lambda a: ev(a, 1).update(value="100"))),
        case("rule5 float equals int", "5", True, mutated(lambda a: ev(a, 1).update(value=100.0))),
        case("rule5 row value missing", "5", False, mutated(lambda a: ev(a, 1).pop("value"))),
        case("rule5 claim value missing", "5", False, mutated(lambda a: a["claims"][0].pop("value"))),
        case("rule5 null equals null", "5", True, mutated(lambda a: ([r.update(value=None) for r in a["evidence"]], a["claims"][0].update(value=None)))),
        case("rule5 bool equals int as in Python", "5", True, mutated(lambda a: ([r.update(value=True) for r in a["evidence"]], a["claims"][0].update(value=1)))),
        case("rule5 list values compare structurally", "5", True, mutated(lambda a: ([r.update(value=[1, {"k": [2.0]}]) for r in a["evidence"]], a["claims"][0].update(value=[1, {"k": [2]}])))),
        case("rule5 non-bound row may disagree", "5", True, mutated(lambda a: a["evidence"].append(evidence_row("T00", 9, stamp, expiry, "other", value=1)))),
    ]

    # Rule 6: fail closed on anything else; time terms are not part of the recount.
    cases += [
        case("rule6 truthy non-mapping payload fails closed", "6", False, mutated(lambda a: (ev(a, 0).pop("origin_group"), ev(a, 0).update(payload="oops")))),
        case("rule6 falsy payload is treated as empty", "6", True, mutated(lambda a: (ev(a, 0).pop("origin_group"), ev(a, 0).update(payload=[])))),
        case("time expired audit is still structurally qualified", "time", True, mutated(lambda a: (a.update(validated_at="2020-01-01T00:00:00Z", valid_until="2020-01-01T01:00:00Z"), [r.update(valid_until="2020-01-01T01:00:00Z") for r in a["evidence"]]))),
        case("time fields absent are not required", "time", True, mutated(lambda a: (a.pop("validated_at"), a.pop("valid_until"), [r.pop("valid_until") for r in a["evidence"]]))),
        case("time fields malformed are not parsed", "time", True, mutated(lambda a: (a.update(validated_at="not a time", valid_until=7), [r.update(valid_until="x") for r in a["evidence"]]))),
    ]

    def obs(**kw: Any) -> dict[str, Any]:
        return dict(kw)

    lineage: list[dict[str, Any]] = [
        {"name": "empty", "observations": [], "expected": 0},
        {"name": "two distinct", "observations": [obs(independence_group="a", origin_group="o1", content_sha256="h1"), obs(independence_group="b", origin_group="o2", content_sha256="h2")], "expected": 2},
        {"name": "same publisher", "observations": [obs(independence_group="a", content_sha256="h1"), obs(independence_group="a", content_sha256="h2")], "expected": 1},
        {"name": "same origin", "observations": [obs(independence_group="a", origin_group="o"), obs(independence_group="b", origin_group="o")], "expected": 1},
        {"name": "same hash", "observations": [obs(independence_group="a", content_sha256="h"), obs(independence_group="b", content_sha256="h")], "expected": 1},
        {"name": "transitive chain", "observations": [obs(independence_group="a", origin_group="o1", content_sha256="h1"), obs(independence_group="b", origin_group="o2", content_sha256="h2"), obs(independence_group="a", origin_group="o2", content_sha256="h3")], "expected": 1},
        {"name": "late observation bridges two components", "observations": [obs(independence_group="p1"), obs(origin_group="o1"), obs(independence_group="p1", origin_group="o1")], "expected": 1},
        {"name": "two components plus a singleton", "observations": [obs(independence_group="a"), obs(independence_group="a", origin_group="x"), obs(independence_group="c")], "expected": 2},
        {"name": "no usable key is skipped", "observations": [obs(), obs(independence_group="a")], "expected": 1},
        {"name": "non-string identities are ignored not coerced", "observations": [obs(independence_group=5, origin_group=["x"], content_sha256=7), obs(independence_group="a")], "expected": 1},
        {"name": "identities are stripped", "observations": [obs(independence_group=" p "), obs(independence_group="p")], "expected": 1},
        {"name": "whitespace-only identities are skipped", "observations": [obs(independence_group="   ", origin_group="\t", content_sha256="\n"), obs(independence_group="a")], "expected": 1},
        {"name": "payload origin fallback", "observations": [obs(independence_group="a", origin_group="", payload={"origin_group": "o"}), obs(independence_group="b", payload={"origin_group": "o"})], "expected": 1},
        {"name": "truthy non-string origin blocks fallback", "observations": [obs(independence_group="a", origin_group=5, payload={"origin_group": "o"}), obs(independence_group="b", payload={"origin_group": "o"})], "expected": 2},
        {"name": "falsy payload is empty", "observations": [obs(independence_group="a", payload=[]), obs(independence_group="a", payload="")], "expected": 1},
        {"name": "python-only whitespace is stripped", "observations": [obs(independence_group="\u001cp\u001c"), obs(independence_group="p")], "expected": 1},
        {"name": "zero width no-break space is not stripped", "observations": [obs(independence_group="﻿p"), obs(independence_group="p")], "expected": 2},
        {"name": "ideographic space is stripped", "observations": [obs(independence_group="　p"), obs(independence_group="p")], "expected": 1},
        {"name": "case sensitive", "observations": [obs(independence_group="P"), obs(independence_group="p")], "expected": 2},
        {"name": "key namespaces do not collide", "observations": [obs(independence_group="x"), obs(origin_group="x"), obs(content_sha256="x")], "expected": 3},
        {"name": "non-mapping entries are skipped", "observations": [None, 5, "x", [1], obs(independence_group="a")], "expected": 1},
    ]
    lineage_errors: list[dict[str, Any]] = [
        {"name": "truthy string payload raises", "observations": [obs(independence_group="a", payload="oops")]},
        {"name": "truthy list payload raises", "observations": [obs(independence_group="a", payload=[1])]},
        {"name": "truthy number payload raises", "observations": [obs(independence_group="a", payload=3)]},
    ]
    return {
        "schema_version": 1,
        "contract_id": "v213-r75-publication-mode-v2",
        "note": (
            "Shared by tests/test_v213_publication_mode_claim_recount.py and "
            "cloud/test/v213-claim-recount.test.ts. Expectations are authored literals. "
            "Regenerate with tests/fixtures/make_v213_r75_publication_mode_v2_fixtures.py."
        ),
        "lineage_cases": lineage,
        "lineage_error_cases": lineage_errors,
        "recount_cases": cases,
    }


# --------------------------------------------------------------------------- main


def build(root: Path) -> dict[str, bytes]:
    contract = json.loads((root / CONTRACT_RELATIVE).read_text(encoding="utf-8-sig"))
    contract_id = str(contract["contract_id"])
    contract_hash = sha256_text(canonical_json(contract))
    outputs: dict[str, bytes] = {}
    for name, with_audits in (("mixed.json", True), ("all-limited.json", False)):
        relative = f"{FIXTURE_DIR}/{name}"
        document = json.loads((root / relative).read_text(encoding="utf-8-sig"))
        outputs[relative] = render(regenerate_fixture(document, contract_id, contract_hash, with_audits))
    outputs[f"{FIXTURE_DIR}/claim-recount-vectors.json"] = render(vectors())
    return outputs


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--out-root", type=Path)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    out_root = args.out_root or args.root
    outputs = build(args.root)
    changed = []
    for relative, data in outputs.items():
        target = out_root / relative
        if not target.exists() or target.read_bytes() != data:
            changed.append(relative)
            if not args.check:
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(data)
    verb = "would change" if args.check else "wrote"
    print(f"V213_R75_PUBLICATION_MODE_V2_FIXTURES: {verb} {len(changed)} of {len(outputs)} files: " + ", ".join(changed))
    return 1 if (args.check and changed) else 0


if __name__ == "__main__":
    sys.exit(main())
