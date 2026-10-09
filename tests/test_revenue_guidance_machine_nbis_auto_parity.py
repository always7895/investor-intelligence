"""SYNTHETIC_NBIS_AUTO_NOT_GENUINE_NATIVE_OR_LIVE: frozen producer parity."""
from datetime import datetime, timezone
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
from tests.test_revenue_guidance_nbis_refusals import curated_denylist

CUTOFF = datetime(2032, 2, 20, 13, tzinfo=timezone.utc)
CUTOFF_TEXT = "2032-02-20T13:00:00Z"
SCOPE = "SYNTHETIC_NBIS_AUTO_NOT_GENUINE_NATIVE_OR_LIVE"
FIXTURE = ROOT / "tests/fixtures/revenue-guidance-machine-nbis-auto-functional.json"


def _run(root: Path):
    chain = h.Chain(root)
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
        row["market"]["asof"] = "2032-02-20"
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


def rendered_numbers(deny):
    return [str(int(value)) if value == value.to_integral_value() else format(value, "f")
            for value in deny["numbers"] if value >= 1000000]


class NbisAutoProducerTests(unittest.TestCase):
    def test_n4_1_frozen_auto_payload(self):
        with tempfile.TemporaryDirectory(prefix="synthetic-nbis-machine-") as tmp:
            def invoke():
                result = produce(Path(tmp))
                top = json.loads(result["report"])["top"]
                env = top[2]["outlook"]["order_forecast_v3"]
                payload, evidence = env["payload"], env["payload"]["evidence"]
                return (result["scope"], len(top), top[2]["symbol"], payload["revenue_status"],
                        payload["m6"]["amount"], payload["m12"]["amount"],
                        evidence["auto_update"]["disposition"],
                        env["machine"]["producer_canonical_json"] is not None,
                        bool(env["machine"]["receipt_history"]), evidence["approval_sha256"],
                        evidence["approval_approved_at"], evidence["approval_decisions"])
            actual = f.outcome_of(invoke)
            f.observe_boundary("N4-1", actual)
            self.assertEqual(actual, ("RESULT", (
                "SYNTHETIC_NBIS_AUTO_NOT_GENUINE_NATIVE_OR_LIVE", 10, "NBIS", "AVAILABLE",
                3700000000.0, 7400000000.0, "AUTO_VERIFIED", True, True, None, None, None)))

    def test_n4_2_frozen_bytes_and_fresh_root_determinism(self):
        with tempfile.TemporaryDirectory(prefix="synthetic-nbis-a-") as a, tempfile.TemporaryDirectory(prefix="synthetic-nbis-b-") as b:
            def invoke():
                frozen = FIXTURE.read_bytes()
                first = serialize(produce(Path(a)))
                second = serialize(produce(Path(b)))
                return first == frozen, second == first
            actual = f.outcome_of(invoke)
            f.observe_boundary("N4-2", actual)
            self.assertEqual(actual, ("RESULT", (True, True)))

    def test_n4_3_ten_symbol_dispositions(self):
        with tempfile.TemporaryDirectory(prefix="synthetic-nbis-dispositions-") as tmp:
            def invoke():
                result, snapshot = _run(Path(tmp))
                return tuple(snapshot.issuer(row["symbol"]).disposition
                             for row in json.loads(result["report"])["top"])
            actual = f.outcome_of(invoke)
            f.observe_boundary("N4-3", actual)
            self.assertEqual(actual, ("RESULT", (
                "CURATED", "CURATED", "AUTO_VERIFIED", "CURATED", "CURATED",
                "CURATED", "CURATED", "CURATED", "CURATED", "CURATED")))

    def test_n4_4_frozen_fixture_hygiene(self):
        def invoke():
            from decimal import Decimal

            def leaves(value, path=()):
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

            deny = curated_denylist()[1]
            counts = [0, 0, 0, 0, 0]
            exceptions = [0, 0, 0, 0]
            approved_cik_url = (
                r"https://www\.sec\.gov/Archives/edgar/data/1513845/"
                r"0000000000[0-9]{8}/[A-Za-z0-9._-]+"
                r"|https://data\.sec\.gov/submissions/CIK0001513845\.json")
            for path, value in leaves(json.loads(FIXTURE.read_bytes())):
                text = value if isinstance(value, str) else json.dumps(value)
                for index, kind in enumerate(("accessions", "hashes", "names")):
                    counts[index] += sum(item in text for item in deny[kind])
                # URL leaves use RF's exact denylist membership, not a prefix
                # ban on the synthetic SEC URLs permitted by the closed policy.
                if isinstance(value, str) and value in deny["urls"]:
                    if value == "https://group.nebius.com/newsroom" and path[-1:] == ("url",):
                        exceptions[0] += 1
                    elif value == "https://www.sec.gov/Archives/edgar/data/" and path[-2:] == ("url_prefixes", 0):
                        exceptions[1] += 1
                    else:
                        counts[3] += 1
                numeric_cik = (type(value) in (int, float) and value == 1513845
                               and path[-2:] == ("release_channels", "sec_cik"))
                approved_url = (isinstance(value, str) and "1513845" in value
                                and re.fullmatch(approved_cik_url, value) is not None)
                exceptions[2] += int(numeric_cik)
                exceptions[3] += int(approved_url)
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
            return tuple(counts) + (tuple(exceptions),)
        actual = f.outcome_of(invoke)
        f.observe_boundary("N4-4", actual)
        self.assertEqual(actual, ("RESULT", (0, 0, 0, 0, 0, (5, 3, 3, 97))))


if __name__ == "__main__":
    unittest.main()
