"""SYNTHETIC_NBIS_REAFFIRM_NOT_GENUINE_NATIVE_OR_LIVE: Scenario R frozen producer parity (G4c).

The Scenario Z producer of tests/test_revenue_guidance_machine_nbis_auto_parity.py, run on the Scenario R
packages and clocks: the current letter reaffirms the full-year range of the earlier original letter, so the
machine record carries one REAFFIRMATION decision. FIXTURE is serialize(produce(root)); it binds
implementation_sha256, so it is regenerated only on the final merged tree. Synthetic only: no tracked
profile is enabled and nothing here is genuine, native or live.
"""
import json
from pathlib import Path
import re
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT))
import order_claims
import publish_sealed_snapshot as publisher
import revenue_guidance_machine as machine
import revenue_guidance_overlay as overlay
from tests import nbis_e2e_support as h
from tests import nbis_synthetic_sources as f
from tests.test_revenue_guidance_machine_nbis_auto_parity import rendered_numbers
from tests.test_revenue_guidance_nbis_refusals import curated_denylist

CUTOFF_TEXT = h.CLOCKS["R"][2]
CUTOFF = h.moment(CUTOFF_TEXT)
SCOPE = "SYNTHETIC_NBIS_REAFFIRM_NOT_GENUINE_NATIVE_OR_LIVE"
FIXTURE = ROOT / "tests/fixtures/revenue-guidance-machine-nbis-reaffirm-functional.json"


def _run(root: Path):
    chain = h.Chain(root, mode="R")
    chain.produce()
    shell = json.loads((ROOT / "tests/fixtures/revenue-guidance-wire-v1-functional.json").read_bytes())
    report = json.loads(shell["expected_legacy_body"][machine.REPORT_KEY])
    report["top"][2].update(symbol="NBIS", name="Nebius", name_zh="NBIS")
    report["generated_at"] = CUTOFF_TEXT
    symbols = tuple(row["symbol"] for row in report["top"])
    snapshot = overlay.load_effective_inputs(
        cutoff=CUTOFF_TEXT, state_root=chain.state, registry_path=chain.registry,
        approval_path=chain.approval, profiles_path=chain.profiles,
        receipts_path=chain.receipts, symbols=symbols, allow_replay=False)
    resolved = machine.resolve_machine_inputs(snapshot, CUTOFF, symbols)
    claims = order_claims.load(root / "missing-synthetic-order-claims.json")
    for row in report["top"]:
        row["market"]["asof"] = CUTOFF_TEXT[:10]
        row["outlook"] = publisher._with_order_forecast(
            row["symbol"], None, None, None, CUTOFF, claims, consensus_cache={},
            effective_inputs=snapshot, guidance_machine_enabled=True, machine_inputs=resolved)
    raw = machine.compact(report, machine.REPORT_BYTES)
    binding = machine.make_public_binding(
        resolved, raw, "gir1:" + "a" * 64, b'{"fixture":"historical-auto-replay"}')
    machine.validate_public_bundle(raw, binding, machine.sha256(raw), machine.sha256(binding))
    return ({"scope": SCOPE, "report": raw.decode("utf-8"), "binding": binding.decode("utf-8")}, snapshot)


def produce(root: Path):
    return _run(root)[0]


def serialize(result):
    return (json.dumps(result, indent=2, ensure_ascii=False) + "\n").encode("utf-8")


def leaves(value, path=()):
    """Every scalar leaf, descending into strings that hold JSON objects or arrays."""
    if isinstance(value, dict):
        for key, child in value.items():
            yield from leaves(child, path + (key,))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from leaves(child, path + (index,))
    elif isinstance(value, str):
        try:
            decoded = json.loads(value)
        except json.JSONDecodeError:
            decoded = None
        if isinstance(decoded, (dict, list)):
            yield from leaves(decoded, path)
        else:
            yield path, value
    else:
        yield path, value


class NbisReaffirmProducerTests(unittest.TestCase):
    """Expected values are DESIGNED from Scenario R (FY2034 range 7.2B-7.6B, midpoint 7.4B; YTD 1711.1M + 1822.2M
    over two reported quarters, two remaining quarters), not observed: Scenario R has run only on pure seams."""

    def test_r4_1_frozen_reaffirmation_payload(self):
        with tempfile.TemporaryDirectory(prefix="synthetic-nbis-reaffirm-") as tmp:
            def invoke():
                result = produce(Path(tmp))
                top = json.loads(result["report"])["top"]
                env = top[2]["outlook"]["order_forecast_v3"]
                payload, evidence = env["payload"], env["payload"]["evidence"]
                decisions = json.loads(env["machine"]["decisions_canonical_json"])
                record = json.loads(env["machine"]["record_canonical_json"])
                states = sorted(d["operands"]["guidance_state"]["kind"] for d in decisions
                                if d["kind"] == "MEMBERSHIP" and d["operands"]["guidance_state"] is not None)
                return (result["scope"], len(top), top[2]["symbol"], payload["revenue_status"],
                        payload["m6"]["amount"], payload["m12"]["amount"],
                        evidence["auto_update"]["disposition"],
                        env["machine"]["producer_canonical_json"] is not None,
                        bool(env["machine"]["receipt_history"]), evidence["approval_sha256"],
                        evidence["approval_approved_at"], evidence["approval_decisions"],
                        sum(d["kind"] == "REAFFIRMATION" for d in decisions), states,
                        len(record["claims"][0]["reaffirmed_by"]), record["fy_reconciliation"]["ytd_quarter_ends"])
            actual = f.outcome_of(invoke)
            f.observe_boundary("R4-1", actual)
            self.assertEqual(actual, ("RESULT", (
                "SYNTHETIC_NBIS_REAFFIRM_NOT_GENUINE_NATIVE_OR_LIVE", 10, "NBIS", "AVAILABLE",
                3866700000.0, 7733400000.0, "AUTO_VERIFIED", True, True, None, None, None,
                1, ["ORIGINAL_RANGE", "REAFFIRMATION"], 1, ["2034-03-31", "2034-06-30"])))

    def test_r4_2_frozen_bytes_and_fresh_root_determinism(self):
        with tempfile.TemporaryDirectory(prefix="synthetic-nbis-reaffirm-a-") as a, \
                tempfile.TemporaryDirectory(prefix="synthetic-nbis-reaffirm-b-") as b:
            def invoke():
                frozen = FIXTURE.read_bytes()
                first = serialize(produce(Path(a)))
                second = serialize(produce(Path(b)))
                return first == frozen, second == first
            actual = f.outcome_of(invoke)
            f.observe_boundary("R4-2", actual)
            self.assertEqual(actual, ("RESULT", (True, True)))

    def test_r4_3_ten_symbol_dispositions(self):
        with tempfile.TemporaryDirectory(prefix="synthetic-nbis-reaffirm-dispositions-") as tmp:
            def invoke():
                result, snapshot = _run(Path(tmp))
                return tuple(snapshot.issuer(row["symbol"]).disposition
                             for row in json.loads(result["report"])["top"])
            actual = f.outcome_of(invoke)
            f.observe_boundary("R4-3", actual)
            self.assertEqual(actual, ("RESULT", (
                "CURATED", "CURATED", "AUTO_VERIFIED", "CURATED", "CURATED",
                "CURATED", "CURATED", "CURATED", "CURATED", "CURATED")))

    def test_r4_4_frozen_fixture_carries_no_genuine_identifier(self):
        # The Scenario Z hygiene rule (test_n4_4) over the R fixture. Only the five denylist counts are pinned; the
        # permitted synthetic SEC URL / CIK exception counts are not observed for R and are deliberately not pinned.
        def invoke():
            from decimal import Decimal
            deny = curated_denylist()[1]
            counts = [0, 0, 0, 0, 0]
            approved_cik_url = (
                r"https://www\.sec\.gov/Archives/edgar/data/1513845/"
                r"0000000000[0-9]{8}/[A-Za-z0-9._-]+"
                r"|https://data\.sec\.gov/submissions/CIK0001513845\.json")
            for path, value in leaves(json.loads(FIXTURE.read_bytes())):
                text = value if isinstance(value, str) else json.dumps(value)
                for index, kind in enumerate(("accessions", "hashes", "names")):
                    counts[index] += sum(item in text for item in deny[kind])
                if isinstance(value, str) and value in deny["urls"]:
                    allowed = ((value == "https://group.nebius.com/newsroom" and path[-1:] == ("url",))
                               or (value == "https://www.sec.gov/Archives/edgar/data/" and path[-2:] == ("url_prefixes", 0)))
                    counts[3] += int(not allowed)
                numeric_cik = (type(value) in (int, float) and value == 1513845
                               and path[-2:] == ("release_channels", "sec_cik"))
                approved_url = (isinstance(value, str) and "1513845" in value
                                and re.fullmatch(approved_cik_url, value) is not None)
                if isinstance(value, str) and "1513845" in value and not approved_url:
                    counts[4] += 1
                for number in rendered_numbers(deny):
                    if type(value) in (int, float):
                        hit = Decimal(str(value)) == Decimal(number)
                    elif isinstance(value, str):
                        hit = re.search(r"(?<![0-9.])" + re.escape(number) + r"(?![0-9])", value) is not None
                    else:
                        hit = False
                    if hit and not (number == "1513845" and (numeric_cik or approved_url)):
                        counts[4] += 1
            return tuple(counts)
        actual = f.outcome_of(invoke)
        f.observe_boundary("R4-4", actual)
        self.assertEqual(actual, ("RESULT", (0, 0, 0, 0, 0)))


if __name__ == "__main__":
    unittest.main()
