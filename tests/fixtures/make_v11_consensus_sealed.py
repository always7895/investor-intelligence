"""Regenerates tests/fixtures/v11-consensus-sealed.json: the sealed outlooks (order_forecast v2 + order_forecast_v3) of the
analyst-consensus revenue route (operator 2026-10-13, R/OPERATOR-DECISION-CONSENSUS-AND-OFFHOURS-OPTIONS-20261013.txt A1:
on, labelled analyst consensus, not company guidance, unofficial) for the Worker tests of the labelled rendering.

Every outlook is produced by the real chain: a Yahoo quoteSummary body (formatted=false shape) -> the collector's
revenue_consensus_quarterly.refresh_symbol (its cache file) -> load_cache / select_for_cutoff (the two calls
publish_sealed_snapshot.captured_bottleneck_v3_body makes, with its CONSENSUS_CACHE_LOAD_FAILED fault) -> the real sealer
function publish_sealed_snapshot._with_order_forecast, over the reviewed fixture registry of make_orders_v3_golden.py
with the registry gate on and one synthetic US issuer (ACME) whose record states no numeric guidance. No network.

Run from the repository root:
    python tests/fixtures/make_v11_consensus_sealed.py [--check]
--check exits 1 when the committed fixture differs from a fresh build."""
import copy
import importlib.util
import json
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import publish_sealed_snapshot  # noqa: E402
import revenue_consensus_quarterly  # noqa: E402

FIXTURES = ROOT / "tests" / "fixtures"
OUTPUT = FIXTURES / "v11-consensus-sealed.json"
REGISTRY = FIXTURES / "revenue-guidance-issuers-r2.json"
_spec = importlib.util.spec_from_file_location("make_orders_v3_golden", FIXTURES / "make_orders_v3_golden.py")
golden = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(golden)
import revenue_guidance  # noqa: E402  (after the golden module put scripts/ on the path)

YAHOO = "https://query2.finance.yahoo.com/v10/finance/quoteSummary/{symbol}?modules=earningsTrend,financialData"
SEALED_AT = datetime(2026, 9, 28, 15, 0, tzinfo=timezone.utc)  # the build clock of the golden (after the 14:45Z reviews)
EMPTY_CLAIMS = golden.EMPTY_CLAIMS


def utc(text: str) -> datetime:
    return datetime.strptime(text, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


def yahoo_raw(currency: str, quarters: list) -> dict:
    """A Yahoo quoteSummary body as the collector's session transport returns it (formatted=false: {"raw": n} cells)."""
    trend = [{"period": p, "endDate": end, "revenueEstimate": {"avg": {"raw": avg}, "numberOfAnalysts": {"raw": n}}}
             for p, end, avg, n in quarters]
    trend.append({"period": "0y", "endDate": "2026-12-31", "revenueEstimate": {"avg": {"raw": 1.0}, "numberOfAnalysts": {"raw": 40}}})
    return {"quoteSummary": {"result": [{"financialData": {"financialCurrency": currency}, "earningsTrend": {"trend": trend}}]}}


def acme_record(base: dict) -> dict:
    """A US issuer whose reviewed record states no numeric revenue guidance (cut from the SK hynix record's shape)."""
    rec = json.loads(json.dumps(base))
    text = json.dumps(rec, ensure_ascii=False)
    for old, new in (("000660-", "ACME-"), ("000660.KS", "ACME"), ("SK hynix Inc.", "Acme Optical Corp."),
                     ("https://news.skhynix.com/", "https://investors.acme-optical.com/"), ("K-IFRS", "GAAP"), ("KRW", "USD")):
        text = text.replace(old, new)
    rec = json.loads(text)
    for quarter, revenue in zip(rec["reported_quarters"], (8.0e8, 9.0e8, 1.0e9, 1.1e9)):
        quarter["revenue"] = revenue
    for doc in rec["documents"]:
        doc["title"] = doc["title"].replace("Announces", "Reports")
    rec["nondisclosure_evidence"]["note"] = "The 2Q26 results release states no numeric revenue guidance (qualitative outlook only)."
    return rec


def registry_file(directory: Path, gate: bool | None) -> Path:
    data = json.loads(REGISTRY.read_text(encoding="utf-8"))
    if gate is not None:
        data["consensus_enabled"] = gate
    data["issuers"].append(acme_record(next(r for r in data["issuers"] if r["symbol"] == "000660.KS")))
    path = directory / f"registry-{'unset' if gate is None else str(gate).lower()}.json"
    path.write_bytes((json.dumps(data, ensure_ascii=False, indent=1) + "\n").encode("utf-8"))
    return path


def collect(cache: Path, captures: list) -> None:
    """Run the collector for each (symbol, captured_at, raw) exactly as the refresh step does (a fake transport only)."""
    for symbol, at, raw in captures:
        entry = revenue_consensus_quarterly.refresh_symbol(symbol, utc(at), max_age_hours=6, fetch_json=lambda url, raw=raw: raw,
                                                           cache_path=cache)
        assert entry is not None, symbol


def selected(cache: Path, cutoff: datetime) -> dict:
    """The two calls (and the typed fault) of publish_sealed_snapshot.captured_bottleneck_v3_body."""
    try:
        return revenue_consensus_quarterly.select_for_cutoff(revenue_consensus_quarterly.load_cache(cache), cutoff)
    except Exception:
        return {"__fault__": "CONSENSUS_CACHE_LOAD_FAILED"}


def recognition(horizons: dict) -> dict:
    """The deep report's order scenario shape (tests/test_order_forecast.py recognition()): a 12-month RPO schedule."""
    return {"status": "DISCLOSED", "form": "10-Q", "filed": "2026-08-26", "url": "https://www.sec.gov/fixture", "rpo": 3.2e8,
            "rpo_as_of": "2026-07-26", "quarter_revenue": 1.1e9, "quarter_end": "2026-07-26", "quarter_start": "2026-04-27",
            "quarter_basis": "FRAME", "accession": "0001045810-26-000075", "passage": "fixture passage stating the schedule",
            "report_date": "2026-07-26", "horizons": horizons}


def seal(symbols, cutoff, registry, approval, cache_selected, checks, recognitions=None) -> dict:
    return {symbol: publish_sealed_snapshot._with_order_forecast(
        symbol, None, None, (recognitions or {}).get(symbol), cutoff, EMPTY_CLAIMS, revenue_registry=registry,
        consensus_cache=cache_selected, release_checks_cache=checks, revenue_approval=approval) for symbol in symbols}


def build() -> dict:
    KR = yahoo_raw("KRW", [("0q", "2026-09-30", 100287043740000, 37), ("+1q", "2026-12-31", 113906353020000, 37)])
    SAMSUNG = yahoo_raw("KRW", [("0q", "2026-09-30", 204646748150000, 25), ("+1q", "2026-12-31", 217123379910000, 2)])
    US = yahoo_raw("USD", [("0q", "2026-09-30", 1.25e9, 12), ("+1q", "2026-12-31", 1.35e9, 11)])
    NVDA = yahoo_raw("USD", [("0q", "2026-09-30", 60e9, 40), ("+1q", "2026-12-31", 65e9, 40)])
    NEXT = yahoo_raw("KRW", [("0q", "2026-12-31", 120e12, 37), ("+1q", "2027-03-31", 125e12, 37)])
    cases: dict = {}
    with tempfile.TemporaryDirectory() as tmp:
        directory = Path(tmp)
        on = revenue_guidance.load_registry(registry_file(directory, True))
        _, approval_on = golden.make_approval(registry_file(directory, True))
        checks = {"schema": "revenue-guidance-release-checks-v1", "generated_at": golden.CHECKED_AT,
                  "issuers": {s: [golden.receipt(r)] for s, r in on["issuers"].items() if r["status"] == "GUIDANCE"}}

        def case(name, cutoff_text, captures, symbols, *, fault=False, recognitions=None, registry=on, approval=approval_on):
            cache = directory / f"{name}.json"
            if fault:
                cache.write_bytes(b'{"000660.KS": [')  # a truncated cache file
            else:
                collect(cache, captures)
            cutoff = utc(cutoff_text)
            cases[name] = {"cutoff": cutoff_text, "outlooks": seal(symbols, cutoff, registry, approval, selected(cache, cutoff), checks, recognitions)}

        # Fresh captures: two Korean issuers (the second with a one-analyst-short second quarter) and a US issuer.
        case("available", "2026-09-28T15:00:00Z", [("000660.KS", "2026-09-28T12:00:00Z", KR), ("005930.KS", "2026-09-28T12:00:00Z", SAMSUNG),
                                                   ("ACME", "2026-09-28T12:00:00Z", US)], ["000660.KS", "005930.KS", "ACME"])
        # Contracted recognition stays separate beside the consensus revenue model.
        case("with_recognition", "2026-09-28T15:00:00Z", [("ACME", "2026-09-28T12:00:00Z", US)], ["ACME"],
             recognitions={"ACME": recognition({"m6": None, "m12": {"share_pct": 39, "derived": False}})})
        # Company guidance keeps precedence: NVDA has a capture too and is read from its guidance.
        case("guidance_precedence", "2026-09-28T15:00:00Z", [("NVDA", "2026-09-28T12:00:00Z", NVDA)], ["NVDA"])
        # The post-quarter-end bridge (operator 2026-10-14): the first consensus quarter (ended 2026-09-30) stays available with
        # the warning while the cutoff is within 70 days of the end and the capture was taken after it (day 1, day 13, day 70).
        case("bridge_day1", "2026-10-01T08:00:00Z", [("000660.KS", "2026-10-01T02:00:00Z", KR)], ["000660.KS"])
        case("bridge_day13", "2026-10-13T08:00:00Z", [("000660.KS", "2026-10-13T02:00:00Z", KR), ("ACME", "2026-10-13T02:00:00Z", US)],
             ["000660.KS", "ACME"])
        case("bridge_day70", "2026-12-09T08:00:00Z", [("000660.KS", "2026-12-09T02:00:00Z", KR)], ["000660.KS"])
        # A capture older than 24 hours, a capture taken before the quarter ended, a quarter ended 71 days ago, and a capture
        # of the next quarter beside a record that has not rolled: each is refused with its own state.
        case("stale_age", "2026-09-28T15:00:00Z", [("000660.KS", "2026-09-27T10:00:00Z", KR)], ["000660.KS"])
        case("quarter_ended", "2026-10-01T08:00:00Z", [("000660.KS", "2026-09-30T20:00:00Z", KR)], ["000660.KS"])
        case("bridge_day71", "2026-12-10T08:00:00Z", [("000660.KS", "2026-12-10T02:00:00Z", KR)], ["000660.KS"])
        case("period_mismatch", "2026-10-31T09:00:00Z", [("000660.KS", "2026-10-31T03:00:00Z", NEXT)], ["000660.KS"])
        # An expired consensus beside a valid contracted recognition: the recognition keeps its own tile, the revenue path says why not.
        case("recognition_stale", "2026-12-10T08:00:00Z", [("ACME", "2026-12-10T02:00:00Z", US)], ["ACME"],
             recognitions={"ACME": recognition({"m6": None, "m12": {"share_pct": 39, "derived": False}})})
        # No capture at all, and an unreadable cache file.
        case("no_capture", "2026-09-28T15:00:00Z", [], ["000660.KS"])
        case("cache_fault", "2026-09-28T15:00:00Z", [], ["000660.KS"], fault=True)
        # The gate off (the registry carries no flag, or false): the capture is never routed.
        off = revenue_guidance.load_registry(registry_file(directory, None))
        _, approval_off = golden.make_approval(registry_file(directory, None))
        case("gate_off", "2026-09-28T15:00:00Z", [("000660.KS", "2026-09-28T12:00:00Z", KR)], ["000660.KS"], registry=off, approval=approval_off)
    return {"schema": "v11-consensus-sealed-v1", "cases": cases}


if __name__ == "__main__":
    fresh = json.dumps(build(), ensure_ascii=False, indent=1) + "\n"
    if "--check" in sys.argv:
        sys.exit(0 if OUTPUT.read_text(encoding="utf-8") == fresh else 1)
    OUTPUT.write_bytes(fresh.encode("utf-8"))
