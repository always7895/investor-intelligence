"""Deterministic offline producer -> sealer bridge fixtures for OPTIONS-NONUS-02 (r3).

Every case runs the REAL scripts.build_market_quotes_options.main (build/observe/health/guard/write) with only the
transports (Yahoo module, Nasdaq HTTP) and the universe stubbed, then the REAL scripts.publish_sealed_snapshot.lazy_market_bodies
and captures the exact emitted body strings and hashes. Nothing here hand-builds a final cycle DTO, mocks the health guard or
the sealer, or restamps an old file. The intended outcome of every case is asserted BEFORE the fixture is written.
An explicit test-only admission seam at sealing admits only the scenario's exact ticker set; the real format
validator still runs and the real rights predicate is restored on exit. The canonical catalog stays NONE.

Provenance labels: rows marked RETAINED are the sanitized sample fields of the archived 2026-09-30 Nasdaq Nordic SIVE option
chain (bid/ask empty, contract currency empty; the archive is NOT needed at test time, its hash is embedded). Everything else is
SYNTHETIC: the prices are computed deterministically by a Black-Scholes helper, not fetched observations, and every
complete-universe case is a synthetic scenario.
"""
from __future__ import annotations

import contextlib
import hashlib
import io
import json
import math
import sys
import tempfile
import types
import urllib.parse
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))

import build_market_quotes_options as builder  # noqa: E402
import publish_sealed_snapshot as publisher  # noqa: E402
import public_options_provider_gate as option_rights  # noqa: E402

FIXTURE_PATH = ROOT / "cloud" / "test" / "fixtures" / "options-nonus-publisher.json"
BRIDGE_SCHEMA = "options-nonus-publisher-bridge-v2"
TODAY = date(2026, 9, 30)
NOW = datetime(2026, 9, 30, 17, 0, 0, tzinfo=timezone.utc)        # sealing time (after the retained samples were retrieved)
PRIOR_NOW = datetime(2026, 9, 30, 13, 0, 0, tzinfo=timezone.utc)  # the legitimately retained previous output
CLOCK = NOW.strftime("%Y-%m-%dT%H:%M:%SZ")

PROVENANCE = {
    "retained_source_samples": {
        "sive_option_chain": {
            "url": "https://api.nasdaq.com/api/nordic/instruments/TX2540138/option-chain", "retrieved_at_utc": "2026-09-30T16:27:45Z",
            "archive_file": "sive-nordic-actual-options.json", "archive_sha256": "3E48226773DFAFB16C932390CF9D4F3DB4FAD5B3AEC83549A697FF96F6F2B468".lower(),
            "embedded": "the first four call rows (2026-10-16) exactly as retained; bid/ask and contract currency were empty",
        },
        "volvb_option_chain": {
            "url": "https://api.nasdaq.com/api/nordic/instruments/TX100/option-chain", "retrieved_at_utc": "2026-09-30T16:27:42Z",
            "archive_file": "volv-nordic-chain-summary.json", "archive_sha256": "BDD2DFCE4475C3FE30BCDD336E952EE1E4FACE2FF11D5F9AC13149EAAF9A4EB4".lower(),
            "embedded": "the first call row (2026-10-02, symbol VOLVB6J02Y280 = the weekly source form) exactly as retained; bid/ask and contract currency were empty",
        },
        "sive_search": {
            "url": "https://api.nasdaq.com/api/nordic/search?searchText=SIVE", "archive_file": "sive-nordic-search.json",
            "archive_sha256": "187C8AAB942CCAD3DA6BB1A9F5B26654B85BAA14E8B6A4ACD3CD89B354C99E58".lower(),
            "embedded": "the SHARES instrument (TX2540138, SEK) exactly as retained",
        },
    },
    "synthetic": "all prices, all other tickers, every 11-sibling universe and every boundary row are SYNTHETIC scenario data",
}

RETAINED_SIVE_SHARE = {"orderbookId": "TX2540138", "fullName": "Sivers Semiconductors", "isin": "SE0003917798", "symbol": "SIVE",
                       "assetClass": "SHARES", "currency": "SEK"}
RETAINED_SIVE_CALLS = [
    {"fullName": f"SIVE 16OCT26 {text}C", "orderbookId": ob, "isin": isin, "symbol": f"SIVE6J{text}", "expirationDate": "2026-10-16",
     "strikePrice": f"{strike:.2f}", "contractSize": "100", "bidPrice": "", "askPrice": "", "lastSalePrice": "", "settlementPrice": "",
     "openInterest": "", "volume": "", "assetClass": "OPTIONS", "currency": ""}
    for text, strike, ob, isin in (("15.50", 15.5, "TX7555268", "SE0030140737"), ("16", 16.0, "TX7555270", "SE0030140745"),
                                   ("16.50", 16.5, "TX7555272", "SE0030140752"), ("17", 17.0, "TX7554188", "SE0030138988"))]

RETAINED_VOLVB_WEEKLY = {
    "fullName": "VOLVB 02OCT26 280C", "orderbookId": "TX7633144", "isin": "SE0030412573", "symbol": "VOLVB6J02Y280", "expirationDate": "2026-10-02",
    "strikePrice": "280.00", "contractSize": "100", "bidPrice": "", "askPrice": "", "lastSalePrice": "", "settlementPrice": "", "openInterest": "",
    "volume": "", "assetClass": "OPTIONS", "currency": ""}
_CALL_LETTERS = "ABCDEFGHIJKL"
_MONTHS = ("JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC")


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def dte_date(dte: int) -> str:
    return (TODAY + timedelta(days=dte)).isoformat()


def _name_date(dte: int) -> str:
    day = TODAY + timedelta(days=dte)
    return f"{day.day:02d}{_MONTHS[day.month - 1]}{day.year % 100:02d}"


def _strike_text(strike: float) -> str:
    return f"{strike:.4f}".rstrip("0").rstrip(".")


def synthetic_quote(spot: float, strike: float, dte: int, vol: float = 0.6) -> tuple[float, float]:
    """SYNTHETIC two-sided quote around the Black-Scholes price (deterministic; not an observation)."""
    price = builder.bs_call_price(spot, strike, dte / 365, vol)
    return math.floor(price * 0.97 * 100) / 100, math.ceil(price * 1.03 * 100) / 100


def qualifying(spot: float, dte: int, strike: float | None = None) -> tuple[float, float, float]:
    """(strike, bid, ask) that the UNCHANGED strategy filters accept at this spot/DTE (asserted, never relaxed)."""
    candidates = [strike] if strike else [float(k) for k in range(int(spot * 1.02), int(spot * 1.8))]
    for k in candidates:
        bid, ask = synthetic_quote(spot, k, dte)
        if bid <= 0:
            continue
        found = builder.covered_call_suggestions([{"strike": k, "bid": bid, "ask": ask, "iv": None, "delta": None, "oi": 1, "volume": 1}], spot, dte,
                                                 cent_exact_only=False)  # the unchanged ECONOMIC filters; display precision is asserted separately
        if found and found[0]["delta"] is not None and found[0]["delta"] <= 0.18:  # margin below the 0.20 filter, which is never relaxed
            return k, bid, ask
    raise AssertionError(f"no qualifying synthetic quote for spot={spot} dte={dte}")


def native_symbol(root: str, dte: int, strike: float) -> str:
    """SYNTHETIC symbol coherent with the row's own declared expiry and strike, in the two source forms the retained receipts prove:
    monthly ROOT + year digit + call-month letter + strike (SIVE6J15.50) and weekly ROOT + year digit + call-month letter + day +
    series letter + strike (VOLVB6J02Y280)."""
    day = TODAY + timedelta(days=int(dte))
    stem = f"{root}{day.year % 10}{_CALL_LETTERS[day.month - 1]}"
    return f"{stem}{day.day:02d}Y{_strike_text(strike)}" if dte <= 14 else f"{stem}{_strike_text(strike)}"


def nordic_row(root: str, dte: int, strike: float, *, bid: Any = "", ask: Any = "", currency: Any = "SEK", size: Any = "100",
               **override: Any) -> dict[str, Any]:
    text = _strike_text(strike)
    row = {"fullName": f"{root} {_name_date(dte)} {text}C", "orderbookId": f"SYNTH-{root}-{dte}-{text}", "isin": f"SYNTH{root}{dte}",
           "symbol": native_symbol(root, dte, strike), "expirationDate": dte_date(dte), "strikePrice": f"{strike:.2f}", "contractSize": size,
           "bidPrice": bid if isinstance(bid, str) else f"{bid:.2f}", "askPrice": ask if isinstance(ask, str) else f"{ask:.2f}",
           "lastSalePrice": "", "settlementPrice": "", "openInterest": "", "volume": "", "assetClass": "OPTIONS", "currency": currency}
    row.update(override)
    return row


def qualifying_row(root: str, dte: int, spot: float, **override: Any) -> dict[str, Any]:
    strike, bid, ask = qualifying(spot, dte)
    return nordic_row(root, dte, strike, bid=bid, ask=ask, **override)


# ------------------------------------------------------------------------------------------------ source specs

def st(symbol: str, rows: Any, *, spot: float = 100.0, spot_currency: Any = "SEK", cached: bool = True, search_currency: Any = "SEK",
       search_share: dict[str, Any] | None = None) -> dict[str, Any]:
    root = symbol[:-3].replace("-", "")
    return {"kind": "ST", "symbol": symbol, "rows": rows, "spot": spot, "spot_currency": spot_currency, "cached": cached,
            "orderbook": f"SYNTH-SHARE-{root}", "search_currency": search_currency, "search_share": search_share}


def us(symbol: str, chains: dict[int, list[tuple[float, float, float]]], *, spot: float = 100.0, yahoo_expiries: list[int] | None = None,
       nasdaq_rows: list[dict[str, Any]] | None = None, yahoo_error: bool = False) -> dict[str, Any]:
    return {"kind": "US", "symbol": symbol, "chains": chains, "spot": spot, "yahoo_expiries": sorted(chains) if yahoo_expiries is None else yahoo_expiries,
            "nasdaq_rows": nasdaq_rows, "yahoo_error": yahoo_error}


def healthy_us(count: int, prefix: str = "SYNTHUS") -> list[dict[str, Any]]:
    out = []
    for i in range(count):
        chains = {}
        for dte in (7, 28):
            strike, bid, ask = qualifying(100.0, dte)
            chains[dte] = [(strike, bid, ask)]
        out.append(us(f"{prefix}{i:02d}", chains))
    return out


def zero_us(symbol: str) -> dict[str, Any]:
    return us(symbol, {28: [(120.0, 0.0, 0.0)]})


def healthy_st(symbol: str, spot: float = 100.0) -> dict[str, Any]:
    root = symbol[:-3].replace("-", "")
    return st(symbol, [qualifying_row(root, 28, spot)], spot=spot)


def zero_st(symbol: str) -> dict[str, Any]:
    root = symbol[:-3].replace("-", "")
    return st(symbol, [nordic_row(root, 28, 120.0, bid="0.00", ask="0.00")])


# ---------------------------------------------------------------------------------------------- real main harness

class _Result:
    def __init__(self, rc: int, status: dict[str, Any], doc: dict[str, Any] | None, output: Path | None, requests: list[str]):
        self.rc, self.status, self.doc, self.output, self.requests = rc, status, doc, output, requests


@contextlib.contextmanager
def _sealed_world(specs: list[dict[str, Any]], now: datetime, requests: list[str]):
    by_symbol = {spec["symbol"]: spec for spec in specs}
    chains: dict[str, Any] = {}
    searches: dict[str, dict[str, Any]] = {}
    for spec in specs:
        if spec["kind"] == "ST":
            chains[(spec["search_share"] or {}).get("orderbookId", spec["orderbook"])] = spec["rows"]
            native = spec["symbol"][:-3].replace("-", " ")
            share = {"orderbookId": spec["orderbook"], "fullName": native, "symbol": native, "assetClass": "SHARES"}
            if spec["search_currency"] is not None:
                share["currency"] = spec["search_currency"]
            searches[native] = spec["search_share"] or share

    class Ticker:
        def __init__(self, symbol: str) -> None:
            self.spec = by_symbol[symbol]

        @property
        def fast_info(self) -> dict[str, Any]:
            currency = self.spec["spot_currency"] if self.spec["kind"] == "ST" else "USD"
            return {"lastPrice": self.spec["spot"], "previousClose": self.spec["spot"], "currency": currency}

        @property
        def options(self) -> list[str]:
            if self.spec["yahoo_error"]:
                raise RuntimeError("synthetic Yahoo expiry-list failure")
            return [dte_date(dte) for dte in self.spec["yahoo_expiries"]]

        def option_chain(self, expiry: str) -> Any:
            dte = (date.fromisoformat(expiry) - TODAY).days
            rows = [types.SimpleNamespace(strike=k, bid=b, ask=a, impliedVolatility=0.6, openInterest=10, volume=5)
                    for k, b, a in self.spec["chains"].get(dte, [])]
            return types.SimpleNamespace(calls=types.SimpleNamespace(itertuples=lambda: iter(rows)))

    def http(url: str) -> Any:
        requests.append(url)
        if "/nordic/search?" in url:
            native = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)["searchText"][0]
            share = searches.get(native)
            return {"data": [{"group": "Shares Main Market", "instruments": [share]}] if share else []}
        if "/nordic/instruments/" in url:
            behaviour = chains[url.split("/instruments/")[1].split("/")[0]]
            if isinstance(behaviour, Exception):
                raise behaviour
            if isinstance(behaviour, dict) and "raw" in behaviour:
                return behaviour["raw"]
            return {"data": {"instrumentListing": {"rows": behaviour}}}
        if "/api/quote/" in url:
            for spec in specs:
                if spec["kind"] == "US" and f"/api/quote/{spec['symbol'].replace('-', '.').lower()}/option-chain" in url:
                    return {"data": {"table": {"rows": spec["nasdaq_rows"] or []}}}
            return {"data": {"table": {"rows": []}}}
        raise AssertionError("UNEXPECTED_TRANSPORT:" + url)

    def forbidden(*_a: Any, **_k: Any) -> Any:
        raise AssertionError("CREDENTIAL_OR_RUNTIME_PATH_FORBIDDEN")

    def no_network(*_a: Any, **_k: Any) -> Any:
        raise RuntimeError("NETWORK_ACCESS_FORBIDDEN_IN_FIXTURE_GENERATOR")

    symbols = [spec["symbol"] for spec in specs]
    sweden = {spec["symbol"]: spec["orderbook"] for spec in specs if spec["kind"] == "ST" and spec["cached"]}
    with contextlib.ExitStack() as stack:
        stack.enter_context(mock.patch.dict(sys.modules, {"yfinance": types.SimpleNamespace(Ticker=Ticker)}))
        for name, value in (("http_json", http), ("universe", lambda: list(symbols)),
                            ("broad_universe", lambda _now: {"us": [], "sweden": dict(sweden)}), ("utc_now", lambda: now),
                            ("alpha_vantage_quote", forbidden), ("alpha_vantage_key", forbidden), ("cached_universe", forbidden)):
            stack.enter_context(mock.patch.object(builder, name, value))
        stack.enter_context(mock.patch("socket.socket.connect", no_network))
        stack.enter_context(mock.patch("urllib.request.urlopen", no_network))
        yield


def run_main(specs: list[dict[str, Any]], now: datetime, directory: Path, *, prior: bytes | None = None) -> _Result:
    requests: list[str] = []
    output = directory / "market_quotes_options.json"
    if prior is not None:
        output.write_bytes(prior)
    captured = io.StringIO()
    with _sealed_world(specs, now, requests), contextlib.redirect_stdout(captured):
        rc = builder.main(["--output", str(output)])
    status = json.loads(captured.getvalue().strip().splitlines()[-1])
    doc = json.loads(output.read_text(encoding="utf-8")) if rc == 0 else None
    return _Result(rc, status, doc, output, requests)


def seal(path: Path, at: datetime, *, synthetic_tickers: frozenset[str]) -> dict[str, str]:
    """Explicit fixture-only seam; no catalog mutation or production admission claim."""
    tickers = frozenset(synthetic_tickers)
    if not tickers or set(json.loads(path.read_bytes())["options"]) != tickers:
        raise AssertionError("synthetic admission must match the exact sealed scenario tickers")
    real_admission = option_rights.public_option_cycle_admission

    def admit_fixture_cycle(cycle: Any, policy: Any) -> str | None:
        if isinstance(cycle, dict) and cycle.get("ticker") in tickers:
            return None
        return real_admission(cycle, policy)

    # Patch the predicate the real publisher calls, never main/build/health/format/sealer.
    with mock.patch.object(option_rights, "public_option_cycle_admission", side_effect=admit_fixture_cycle):
        bodies = publisher.lazy_market_bodies(path, at)
    if set(bodies) != {"v213:options:v2", "v213:quotes:v1"}:
        raise AssertionError("the real sealer refused the file")
    return bodies


# --------------------------------------------------------------------------------------------------- expectations

def cycle_of(bodies: dict[str, str], symbol: str, cycle: str) -> dict[str, Any]:
    return json.loads(bodies["v213:options:v2"])["options"][symbol][cycle]


def expect_available(case: str, bodies: dict[str, str], symbol: str, cycle: str, *, currency: str | None = None) -> None:
    value = cycle_of(bodies, symbol, cycle)
    assert "unavailable" not in value, f"{case}: {symbol}/{cycle} should be a strategy but is {value}"
    assert value["ticker"] == symbol and value["multiplier"] == 100, f"{case}: {symbol}/{cycle} identity {value.get('ticker')}"
    if currency:
        assert value["currency"] == currency, f"{case}: {symbol}/{cycle} currency {value.get('currency')}"


def expect_unavailable(case: str, bodies: dict[str, str], symbol: str, cycle: str, *contains: str, forbid: tuple[str, ...] = ()) -> None:
    value = cycle_of(bodies, symbol, cycle)
    assert "unavailable" in value, f"{case}: {symbol}/{cycle} must be unavailable but is {value.get('ticker')} {value.get('currency')}"
    text = value["unavailable"]
    assert len(text) <= 180, f"{case}: {symbol}/{cycle} diagnostic is {len(text)} units"
    for needle in contains:
        assert needle in text, f"{case}: {symbol}/{cycle} lacks {needle!r}: {text}"
    for needle in forbid:
        assert needle not in text, f"{case}: {symbol}/{cycle} must not say {needle!r}: {text}"


def expect_health(case: str, result: _Result, venue: str, read: int, healthy: int) -> None:
    got = result.doc["collection"]["chain_health"][venue]
    assert (got["read"], got["healthy"]) == (read, healthy), f"{case}: {venue} health {got['read']}/{got['healthy']} != {read}/{healthy}"


OUT_OF_POLICY = "所列到期不在"
NO_RECORDS = "無可用之買權紀錄；是否上市未確認"
UNPARSEABLE = "買權資料無法解析；不推斷是否上市"
READ_FAILED = "讀取或解析失敗"
TERMS_UNCONFIRMED = "合約單位或幣別來源未確認"
NONSTANDARD = "合約單位非標準100股"
NO_TWO_SIDED = "所選到期無有效雙邊報價"
STRATEGY_MISS = "沒有年化權利金達 6% 且有雙邊報價的履約價"
PRECISION = "兩位以上小數"  # recommendation capability of the two-decimal display, not a source-identity or quote failure


# ------------------------------------------------------------------------------------------------------- cases

def case_retained_sive_sept30() -> tuple[str, str, list[dict[str, Any]], Any]:
    sive_rows = list(RETAINED_SIVE_CALLS) + [
        {"fullName": "SIVE 16OCT26 FUTC", "assetClass": "FUTURES_FORWARDS", "expirationDate": "2026-10-16", "strikePrice": "0.00",
         "contractSize": "100", "bidPrice": "", "askPrice": ""},
        nordic_row("SIVE", 51, 36.0, currency="")]  # SYNTHETIC row standing for the reported 2026-11-20 listing
    specs = [st("SIVE.ST", sive_rows, spot=31.48, cached=False, search_share=RETAINED_SIVE_SHARE),
             st("VOLV-B.ST", [dict(RETAINED_VOLVB_WEEKLY), qualifying_row("VOLVB", 28, 310.0)], spot=310.0), healthy_st("AZN.ST", 100.0), *healthy_us(10)]
    specs.append(us("AZN", {28: [qualifying(100.0, 28)]}, spot=100.0))

    def check(case: str, result: _Result, bodies: dict[str, str]) -> None:
        assert result.rc == 0, result.status
        expect_unavailable(case, bodies, "SIVE.ST", "monthly", "本次回應有上市買權；所列到期不在21–45天策略範圍", "2026-10-16（16天）", "2026-11-20（51天）")
        expect_unavailable(case, bodies, "SIVE.ST", "weekly", "本次回應有上市買權；所列到期不在3–14天策略範圍", "2026-10-16（16天）")
        expect_unavailable(case, bodies, "VOLV-B.ST", "weekly", "所列到期不在3–14天策略範圍", "2026-10-02（2天）", forbid=("無法解析",))  # the real weekly shape is a proven listing
        for symbol in ("VOLV-B.ST", "AZN.ST"):
            expect_available(case, bodies, symbol, "monthly", currency="SEK")
        expect_available(case, bodies, "AZN", "monthly", currency="USD")
        expect_available(case, bodies, "SYNTHUS00", "monthly", currency="USD")
        assert any("/nordic/search?searchText=SIVE" in url for url in result.requests), "the search fallback must resolve the SHARES fixture"
        expect_health(case, result, "STOCKHOLM", 2, 2)
    return ("retained_sive_sept30", "RETAINED-shape SIVE rows (16 and 51 DTE) beside healthy SYNTHETIC SEK/USD siblings, admitted through real main", specs, check)


def case_currency_evidence_matrix() -> tuple[str, str, list[dict[str, Any]], Any]:
    specs: list[dict[str, Any]] = [healthy_st("VOLV-B.ST", 310.0), *healthy_us(2)]
    row = lambda root, **kw: [qualifying_row(root, 28, 100.0, **kw)]  # noqa: E731
    contract_variants = {"CURSEK": {"currency": "SEK"}, "CURNULL": {"currency": None}, "CUREMPTY": {"currency": ""}, "CURWS": {"currency": "  "},
                         "CURFALSE": {"currency": False}, "CURZERO": {"currency": 0}, "CURLIST": {"currency": []}, "CURDICT": {"currency": {}},
                         "CURNAN": {"currency": float("nan")}, "CURINT": {"currency": 752}, "CURLOWER": {"currency": "sek"}, "CURUSD": {"currency": "USD"}}
    for root, override in contract_variants.items():
        specs.append(st(f"{root}.ST", row(root, **override), cached=False))
    missing = qualifying_row("CURMISSING", 28, 100.0)
    del missing["currency"]
    specs.append(st("CURMISSING.ST", [missing], cached=False))
    specs.append(st("SPOTUSD.ST", row("SPOTUSD"), spot_currency="USD"))
    specs.append(st("SPOTNONE.ST", row("SPOTNONE"), spot_currency=None))
    specs.append(st("SEARCHEUR.ST", row("SEARCHEUR"), cached=False, search_currency="EUR"))
    specs.append(st("SEARCHNONE.ST", row("SEARCHNONE"), cached=False, search_currency=None))

    def check(case: str, result: _Result, bodies: dict[str, str]) -> None:
        assert result.rc == 0, result.status
        expect_available(case, bodies, "CURSEK.ST", "monthly", currency="SEK")
        for root in ("CURNULL", "CUREMPTY", "CURWS", "CURFALSE", "CURZERO", "CURLIST", "CURDICT", "CURNAN", "CURINT", "CURLOWER", "CURMISSING"):
            expect_unavailable(case, bodies, f"{root}.ST", "monthly", TERMS_UNCONFIRMED, forbid=("不在",))
        expect_unavailable(case, bodies, "CURUSD.ST", "monthly", "合約幣別與 SEK 不符")
        expect_unavailable(case, bodies, "SPOTUSD.ST", "monthly", "標的報價或上市幣別與 SEK 不符")
        expect_unavailable(case, bodies, "SPOTNONE.ST", "monthly", "標的報價或上市幣別未確認為 SEK")
        expect_unavailable(case, bodies, "SEARCHEUR.ST", "monthly", "標的報價或上市幣別與 SEK 不符")
        expect_unavailable(case, bodies, "SEARCHNONE.ST", "monthly", "標的報價或上市幣別未確認為 SEK")
        expect_available(case, bodies, "VOLV-B.ST", "monthly", currency="SEK")
        expect_available(case, bodies, "SYNTHUS00", "monthly", currency="USD")
        expect_health(case, result, "STOCKHOLM", 2, 2)  # only the proven SEK control and the sibling enter R
    return ("currency_evidence_matrix", "SYNTHETIC: contract/spot/search currency evidence matrix through real main; only explicit agreeing SEK is a strategy", specs, check)


def case_native_symbol_identity_matrix() -> tuple[str, str, list[dict[str, Any]], Any]:
    specs: list[dict[str, Any]] = [healthy_st("VOLV-B.ST", 310.0), *healthy_us(2)]
    k, b, a = qualifying(13.7, 14, strike=15.5)
    week = lambda root: [nordic_row(root, 14, k, bid=b, ask=a)]  # noqa: E731 - the reviewed decimal-strike weekly shape (15.50, 14 DTE)
    specs.append(st("SYMCTL.ST", week("SYMCTL"), spot=13.7))
    specs.append(st("SYMMON.ST", [qualifying_row("SYMMON", 28, 100.0)]))
    specs.append(st("SYMWEEK.ST", [qualifying_row("SYMWEEK", 7, 100.0)]))
    day14 = TODAY + timedelta(days=14)
    wrong = {"SYMSTRIKE": native_symbol("SYMSTRIKE", 14, 16.0), "SYMMONTH": f"SYMMONTH{day14.year % 10}K{_strike_text(k)}",
             "SYMYEAR": f"SYMYEAR{(day14.year + 1) % 10}{_CALL_LETTERS[day14.month - 1]}{day14.day:02d}Y{_strike_text(k)}",
             "SYMPUT": f"SYMPUT{day14.year % 10}V{day14.day:02d}Y{_strike_text(k)}", "SYMPREFIX": native_symbol("SYMPREFIXR", 14, k),
             "SYMDAY": f"SYMDAY{day14.year % 10}{_CALL_LETTERS[day14.month - 1]}{(day14.day % 28) + 1:02d}Y{_strike_text(k)}",
             "SYMUNSUP": f"SYMUNSUP-6J-{_strike_text(k)}", "SYMEMPTY": "", "SYMTYPE": 7}
    for root, symbol in wrong.items():
        specs.append(st(f"{root}.ST", [nordic_row(root, 14, k, bid=b, ask=a, symbol=symbol)], spot=13.7))
    none_row = nordic_row("SYMNONE", 14, k, bid=b, ask=a)
    del none_row["symbol"]
    specs.append(st("SYMNONE.ST", [none_row], spot=13.7))
    tags = {}
    for tag in ("Z", "A", "W"):  # the ONLY evidenced weekly tag is Y: every other tag is unproven, never a free slot
        root = f"SYMTAG{tag}"
        tags[root] = f"{root}{day14.year % 10}{_CALL_LETTERS[day14.month - 1]}{day14.day:02d}{tag}{_strike_text(k)}"
        specs.append(st(f"{root}.ST", [nordic_row(root, 14, k, bid=b, ask=a, symbol=tags[root])], spot=13.7))
    specs.append(st("SYMPREC.ST", [nordic_row("SYMPREC", 14, k, bid=b, ask=a, strikePrice="15.5000000001")], spot=13.7))  # 1e-10 off 15.5
    refused = (*wrong, "SYMNONE", *tags, "SYMPREC")

    def check(case: str, result: _Result, bodies: dict[str, str]) -> None:
        assert result.rc == 0, result.status
        assert cycle_of(bodies, "SYMCTL.ST", "weekly")["suggestions"][0]["strike"] == 15.5
        expect_available(case, bodies, "SYMCTL.ST", "weekly", currency="SEK")
        expect_available(case, bodies, "SYMMON.ST", "monthly", currency="SEK")
        expect_available(case, bodies, "SYMWEEK.ST", "weekly", currency="SEK")
        for root in refused:
            for cycle in ("weekly", "monthly"):
                expect_unavailable(case, bodies, f"{root}.ST", cycle, UNPARSEABLE, forbid=(OUT_OF_POLICY, "無可用"))
        expect_health(case, result, "STOCKHOLM", 4, 4)  # only the three proven contracts and the sibling enter R/H
    return ("native_symbol_identity_matrix", "SYNTHETIC: same-root different strike/month/year/put-call/prefix/day/unsupported/absent native symbols versus the decimal, monthly and weekly source forms", specs, check)


def case_strike_precision_matrix() -> tuple[str, str, list[dict[str, Any]], Any]:
    specs: list[dict[str, Any]] = [healthy_st("VOLV-B.ST", 310.0), *healthy_us(3)]
    spot = 13.7
    ksub, bsub, asub = qualifying(spot, 14, strike=15.505)  # coherent supported sub-cent contract: valid listing, valid quotes
    kcent, bcent, acent = qualifying(spot, 14, strike=15.6)
    ktrail, btrail, atrail = qualifying(spot, 14, strike=15.5)
    subcent = lambda root, **kw: nordic_row(root, 14, ksub, bid=bsub, ask=asub, strikePrice="15.505", **kw)  # noqa: E731
    specs.append(st("SUBCENT.ST", [subcent("SUBCENT")], spot=spot))
    trailing_symbol = native_symbol("TRAIL", 14, 15.5)[: -len("15.5")] + "15.5000"
    specs.append(st("TRAIL.ST", [nordic_row("TRAIL", 14, ktrail, bid=btrail, ask=atrail, fullName=f"TRAIL {_name_date(14)} 15.5000C",
                                              strikePrice="15.5000", symbol=trailing_symbol)], spot=spot))
    specs.append(st("MIXED.ST", [subcent("MIXED"), nordic_row("MIXED", 14, kcent, bid=bcent, ask=acent)], spot=spot))
    specs.append(st("SUBZERO.ST", [nordic_row("SUBZERO", 14, ksub, bid="0.00", ask="0.00", strikePrice="15.505")], spot=spot))
    specs.append(us("YSUBCENT", {14: [(ksub, bsub, asub)]}, spot=spot))
    specs.append(us("YCENT", {14: [(ktrail, btrail, atrail)]}, spot=spot))

    def check(case: str, result: _Result, bodies: dict[str, str]) -> None:
        assert result.rc == 0, result.status
        for key in ("SUBCENT.ST", "YSUBCENT"):
            expect_unavailable(case, bodies, key, "weekly", PRECISION, forbid=(NO_TWO_SIDED, STRATEGY_MISS, "無法解析", "所列到期不在", "未確認"))
        expect_available(case, bodies, "TRAIL.ST", "weekly", currency="SEK")
        assert cycle_of(bodies, "TRAIL.ST", "weekly")["suggestions"][0]["strike"] == 15.5
        expect_available(case, bodies, "YCENT", "weekly", currency="USD")
        expect_available(case, bodies, "MIXED.ST", "weekly", currency="SEK")
        strikes = [row["strike"] for row in cycle_of(bodies, "MIXED.ST", "weekly")["suggestions"]]
        assert strikes and all(k == round(k, 2) for k in strikes) and 15.505 not in strikes and 15.6 in strikes, f"{case}: mixed strikes {strikes}"
        expect_unavailable(case, bodies, "SUBZERO.ST", "weekly", NO_TWO_SIDED, forbid=(PRECISION,))
        expect_health(case, result, "STOCKHOLM", 5, 4)  # the sub-cent chains stay in R/H (valid listing and quotes); only SUBZERO is unhealthy
        expect_health(case, result, "US", 8, 8)
    return ("strike_precision_matrix", "SYNTHETIC: a coherent supported sub-cent strike stays in R/H but is never recommended as another strike (two-decimal display)", specs, check)


def case_identity_matrix() -> tuple[str, str, list[dict[str, Any]], Any]:
    specs: list[dict[str, Any]] = [healthy_st("VOLV-B.ST", 310.0), *healthy_us(2)]

    def one(root: str, **override: Any) -> list[dict[str, Any]]:
        return [qualifying_row(root, 28, 100.0, **override)]
    wrong = {"IDROOT": {"fullName": "OTHER 28OCT26 125C"}, "IDDATE": {}, "IDSTRIKE": {"strikePrice": "126.00"}, "IDSYMBOL": {"symbol": "OTHER6J125"},
             "IDNAMENONE": {"fullName": None}, "IDBADDATE": {"expirationDate": "2026-13-45"}, "IDBADSTRIKE": {"strikePrice": None}}
    rows_idroot = one("IDROOT", fullName="OTHER 28OCT26 125C")
    bad_date = qualifying_row("IDDATE", 28, 100.0)
    bad_date["expirationDate"] = dte_date(29)  # the call name says 28 days, the row's own expiry field says 29
    for root, override in wrong.items():
        if root == "IDDATE":
            specs.append(st("IDDATE.ST", [bad_date]))
        elif root == "IDROOT":
            specs.append(st("IDROOT.ST", rows_idroot))
        else:
            specs.append(st(f"{root}.ST", one(root, **override)))
    put_only = qualifying_row("IDPUT", 28, 100.0)
    put_only["fullName"] = put_only["fullName"][:-1] + "P"
    specs.append(st("IDPUT.ST", [put_only]))
    specs.append(st("IDFUTCOPT.ST", [nordic_row("IDFUTCOPT", 28, 0.0, bid="99.00", ask="99.50", fullName=f"IDFUTCOPT {_name_date(28)} FUTC", strikePrice="0.00")]))
    specs.append(st("IDFUTC.ST", [nordic_row("IDFUTC", 28, 0.0, bid="99.00", ask="99.50", fullName=f"IDFUTC {_name_date(28)} FUTC", strikePrice="0.00", assetClass="FUTURES_FORWARDS")]))
    specs.append(st("IDUNKNOWN.ST", one("IDUNKNOWN", assetClass="UNKNOWN_DERIVATIVE")))
    missing_class = qualifying_row("IDNOCLASS", 28, 100.0)
    del missing_class["assetClass"]
    specs.append(st("IDNOCLASS.ST", [missing_class]))
    specs.append(st("IDMALONLY.ST", [None, 5, "x", [], {"assetClass": "OPTIONS", "fullName": None}]))
    specs.append(st("IDMIXED.ST", [None, "x", qualifying_row("IDMIXED", 28, 100.0)]))
    specs.append(st("IDROWSNONE.ST", {"raw": {"data": {"instrumentListing": {"rows": None}}}}))
    specs.append(st("IDROWSDICT.ST", {"raw": {"data": {"instrumentListing": {"rows": {}}}}}))
    specs.append(st("IDENVELOPE.ST", {"raw": {"data": None}}))
    specs.append(st("IDENVLIST.ST", {"raw": {"data": []}}))
    specs.append(st("IDEXC.ST", RuntimeError("synthetic transport failure")))
    specs.append(st("IDEMPTY.ST", []))

    def check(case: str, result: _Result, bodies: dict[str, str]) -> None:
        assert result.rc == 0, result.status
        for root in ("IDROOT", "IDDATE", "IDSTRIKE", "IDSYMBOL", "IDNAMENONE", "IDBADDATE", "IDBADSTRIKE", "IDMALONLY"):
            expect_unavailable(case, bodies, f"{root}.ST", "monthly", UNPARSEABLE, forbid=(OUT_OF_POLICY, "無 21"))
        for root in ("IDPUT", "IDFUTCOPT", "IDFUTC", "IDUNKNOWN", "IDNOCLASS", "IDEMPTY"):
            expect_unavailable(case, bodies, f"{root}.ST", "monthly", NO_RECORDS, forbid=("所列到期", "不存在"))
        for root in ("IDROWSNONE", "IDROWSDICT", "IDENVELOPE", "IDENVLIST", "IDEXC"):
            expect_unavailable(case, bodies, f"{root}.ST", "monthly", READ_FAILED, forbid=("未含", "無可用"))
        expect_available(case, bodies, "IDMIXED.ST", "monthly", currency="SEK")
        expect_available(case, bodies, "VOLV-B.ST", "monthly", currency="SEK")
        expect_health(case, result, "STOCKHOLM", 2, 2)
    return ("identity_matrix", "SYNTHETIC: call identity/date/strike/class and malformed-envelope/row matrix through real main", specs, check)


def case_terms_and_quote_states() -> tuple[str, str, list[dict[str, Any]], Any]:
    specs: list[dict[str, Any]] = [healthy_st("VOLV-B.ST", 310.0), *healthy_us(2)]
    q = lambda dte: qualifying(100.0, dte)  # noqa: E731

    def chain(root: str, *rows: dict[str, Any]) -> dict[str, Any]:
        return st(f"{root}.ST", list(rows))
    k16, b16, a16 = q(16)
    k28, b28, a28 = q(28)
    specs += [
        chain("TSIZE50", nordic_row("TSIZE50", 16, k16, bid=b16, ask=a16), nordic_row("TSIZE50", 28, k28, bid=b28, ask=a28, size="50")),
        chain("TSIZE1005", nordic_row("TSIZE1005", 28, k28, bid=b28, ask=a28, size="100.5")),
        chain("TSIZENONE", nordic_row("TSIZENONE", 16, k16, bid=b16, ask=a16), nordic_row("TSIZENONE", 28, k28, bid=b28, ask=a28, size=None)),
        chain("TCCYNONE", nordic_row("TCCYNONE", 16, k16, bid=b16, ask=a16), nordic_row("TCCYNONE", 28, k28, bid=b28, ask=a28, currency=None)),
        chain("TOUTSIDE", nordic_row("TOUTSIDE", 28, k28, bid=b28, ask=a28), nordic_row("TOUTSIDE", 40, k28, bid=b28, ask=a28, size="50")),
        chain("QNOQUOTE", nordic_row("QNOQUOTE", 28, k28)),
        chain("QONESIDED", nordic_row("QONESIDED", 28, k28, bid="0.50", ask="")),
        chain("QZERO", nordic_row("QZERO", 28, k28, bid="0.00", ask="0.00")),
        chain("QCROSSED", nordic_row("QCROSSED", 28, k28, bid="0.60", ask="0.50")),
        chain("QLASTSALE", nordic_row("QLASTSALE", 28, k28, lastSalePrice="0.55", settlementPrice="0.55", openInterest="500", volume="40")),
        chain("QMISS", nordic_row("QMISS", 28, k28, bid="0.01", ask="0.02")),
        chain("QGOOD", nordic_row("QGOOD", 28, k28, bid=b28, ask=a28)),
        chain("TSZEXACT", nordic_row("TSZEXACT", 28, k28, bid=b28, ask=a28, size="100.00")),
        chain("TSZLEADING", nordic_row("TSZLEADING", 28, k28, bid=b28, ask=a28, size="0100")),
        chain("TSZEXP", nordic_row("TSZEXP", 28, k28, bid=b28, ask=a28, size="1e2")),
        chain("TSZPREC", nordic_row("TSZPREC", 28, k28, bid=b28, ask=a28, size="100.000000000000000001")),
        chain("TSZLONG", nordic_row("TSZLONG", 28, k28, bid=b28, ask=a28, size="100." + "0" * 40)),
    ]

    def check(case: str, result: _Result, bodies: dict[str, str]) -> None:
        assert result.rc == 0, result.status
        expect_unavailable(case, bodies, "TSIZE50.ST", "monthly", NONSTANDARD, forbid=("所列到期不在21",))
        expect_unavailable(case, bodies, "TSIZE50.ST", "weekly", "所列到期不在3–14天策略範圍", "2026-10-16（16天）")
        expect_unavailable(case, bodies, "TSIZE1005.ST", "monthly", NONSTANDARD)
        expect_unavailable(case, bodies, "TSIZENONE.ST", "monthly", TERMS_UNCONFIRMED, forbid=(NONSTANDARD, "所列到期不在21"))
        expect_unavailable(case, bodies, "TCCYNONE.ST", "monthly", TERMS_UNCONFIRMED, forbid=("所列到期不在21",))
        expect_available(case, bodies, "TOUTSIDE.ST", "monthly", currency="SEK")
        for root in ("QNOQUOTE", "QONESIDED", "QZERO", "QCROSSED", "QLASTSALE"):
            expect_unavailable(case, bodies, f"{root}.ST", "monthly", NO_TWO_SIDED, forbid=(STRATEGY_MISS, "沒有上市", "無上市"))
        expect_unavailable(case, bodies, "QMISS.ST", "monthly", STRATEGY_MISS, forbid=(NO_TWO_SIDED,))
        expect_available(case, bodies, "QGOOD.ST", "monthly", currency="SEK")
        expect_available(case, bodies, "TSZEXACT.ST", "monthly", currency="SEK")  # a validated exact-100 numeric representation
        for root in ("TSZLEADING", "TSZEXP"):  # an unsupported encoding is unconfirmed, never a proven non-100 share count
            expect_unavailable(case, bodies, f"{root}.ST", "monthly", TERMS_UNCONFIRMED, forbid=(NONSTANDARD,))
        expect_unavailable(case, bodies, "TSZPREC.ST", "monthly", NONSTANDARD)  # exactly not 100: never rounded into the standard
        expect_unavailable(case, bodies, "TSZLONG.ST", "monthly", TERMS_UNCONFIRMED, forbid=(NONSTANDARD,))  # over the bounded precision
        expect_available(case, bodies, "VOLV-B.ST", "monthly", currency="SEK")
        # R counts only chains read with an eligible selected expiry: 5 without a two-sided quote, QMISS/QGOOD/TSZEXACT/TOUTSIDE/VOLV-B with one.
        expect_health(case, result, "STOCKHOLM", 10, 5)
    return ("terms_and_quote_states", "SYNTHETIC: mixed contract terms versus DTE reasoning and raw quote states (lastSale/settlement/OI are never quotes)", specs, check)


NORDIC_DTES = (3, 14, 15, 20, 21, 45, 46, 60)


def case_dte_nordic_matrix() -> tuple[str, str, list[dict[str, Any]], Any]:
    specs: list[dict[str, Any]] = [*healthy_us(2)]
    for dte in NORDIC_DTES:
        root = f"ND{dte}"
        specs.append(st(f"{root}.ST", [qualifying_row(root, dte, 100.0)]))
    specs += [healthy_st(f"NF{i}.ST") for i in range(3)]

    def check(case: str, result: _Result, bodies: dict[str, str]) -> None:
        assert result.rc == 0, result.status
        for dte in NORDIC_DTES:
            symbol = f"ND{dte}.ST"
            for cycle, (low, high) in (("weekly", (3, 14)), ("monthly", (21, 45))):
                if low <= dte <= high:
                    expect_available(case, bodies, symbol, cycle, currency="SEK")
                    assert cycle_of(bodies, symbol, cycle)["dte"] == dte
                else:
                    expect_unavailable(case, bodies, symbol, cycle, f"所列到期不在{low}–{high}天策略範圍", dte_date(dte))
    return ("dte_nordic_matrix", "SYNTHETIC: Stockholm selector boundaries weekly 3/14/15 and monthly 15/20/21/45/46/60 through real main", specs, check)


US_DTES = (3, 14, 15, 20, 21, 45, 46, 60)


def case_dte_us_matrix() -> tuple[str, str, list[dict[str, Any]], Any]:
    specs: list[dict[str, Any]] = []
    for dte in US_DTES:
        k, b, a = qualifying(100.0, dte)
        specs.append(us(f"UY{dte}", {dte: [(k, b, a)]}))
        strike, bid, ask = k, b, a
        date_text = (TODAY + timedelta(days=dte)).strftime("%B %d, %Y")
        specs.append(us(f"UN{dte}", {}, yahoo_expiries=[], nasdaq_rows=[
            {"expirygroup": date_text}, {"strike": f"{strike:.1f}", "c_Bid": f"{bid:.2f}", "c_Ask": f"{ask:.2f}", "c_Openinterest": "10", "c_Volume": "5"}]))
    specs.append(us("UYMISS", {7: [(120.0, 0.01, 0.02)], 28: [(120.0, 0.01, 0.02)]}))
    specs.append(us("UYEMPTY", {}, yahoo_expiries=[]))
    specs.append(us("UYZERO", {7: [(120.0, 0.0, 0.0)], 28: [(120.0, 0.0, 0.0)]}))
    specs.append(us("UYONESIDED", {7: [(120.0, 0.5, None)], 28: [(120.0, 0.5, None)]}))
    specs += healthy_us(2)

    def check(case: str, result: _Result, bodies: dict[str, str]) -> None:
        assert result.rc == 0, result.status
        for prefix in ("UY", "UN"):
            for dte in US_DTES:
                symbol = f"{prefix}{dte}"
                for cycle, (low, high) in (("weekly", (3, 14)), ("monthly", (21, 45))):
                    if low <= dte <= high:
                        expect_available(case, bodies, symbol, cycle, currency="USD")
                        assert cycle_of(bodies, symbol, cycle)["dte"] == dte, (symbol, cycle)
                    else:
                        assert "unavailable" in cycle_of(bodies, symbol, cycle), f"{case}: {symbol}/{cycle} must not emit a strategy at {dte} DTE"
        miss = cycle_of(bodies, "UYMISS", "monthly")
        assert "unavailable" in miss and "年化權利金" in miss["unavailable"], miss
        nasdaq = [u for u in result.requests if "/api/quote/" in u]
        assert not any("/api/quote/uymiss/" in u for u in nasdaq), "a successfully read strategy miss must not trigger a Nasdaq retry"
        assert sum(1 for u in nasdaq if "/api/quote/uyempty/" in u) == 1, "an unread Yahoo chain gets exactly one Nasdaq retry"
        for symbol in ("UYZERO", "UYONESIDED"):
            for cycle in ("weekly", "monthly"):
                expect_unavailable(case, bodies, symbol, cycle, "所選到期無有效雙邊報價", forbid=("年化權利金",))
            assert not any(f"/api/quote/{symbol.lower()}/" in u for u in nasdaq), f"{symbol}: a read chain is never retried"
    return ("dte_us_matrix", "SYNTHETIC: Yahoo and Nasdaq-fallback selector boundaries, retry preserved for unread chains and not for read strategy misses", specs, check)


def _prior_bytes(directory: Path) -> tuple[bytes, dict[str, str]]:
    specs = [healthy_st("VOLV-B.ST", 310.0), *healthy_us(10)]
    result = run_main(specs, PRIOR_NOW, directory)
    if result.rc != 0 or result.output is None:
        raise AssertionError(f"the legitimate prior run must be admitted: {result.status}")
    return result.output.read_bytes(), seal(result.output, NOW, synthetic_tickers=frozenset(spec["symbol"] for spec in specs))


def _depletion_specs(venue: str, chains: int, healthy: int) -> list[dict[str, Any]]:
    if venue == "US":  # one monthly chain per underlying keeps R equal to the number of underlyings
        good = qualifying(100.0, 28)
        specs = [us(f"DEPUS{i:02d}", {28: [good if i < healthy else (120.0, 0.0, 0.0)]}) for i in range(chains)]
        return specs + [healthy_st("VOLV-B.ST", 310.0)]
    specs = [healthy_st("DEPSTOK.ST") if i < healthy else zero_st(f"DEPST{i:02d}.ST") for i in range(chains)]
    return specs + [*healthy_us(1)]


DEPLETION_CASES = (("depleted_us_1_of_11", "US", 11, 1, False), ("us_1_of_10_admitted", "US", 10, 1, True),
                   ("depleted_stockholm_1_of_11", "STOCKHOLM", 11, 1, False), ("stockholm_1_of_10_admitted", "STOCKHOLM", 10, 1, True))


def generate_fixture_document() -> dict[str, Any]:
    cases: dict[str, Any] = {}
    with tempfile.TemporaryDirectory(prefix="options_nonus_gen_") as tmp:
        base = Path(tmp)
        for index, builder_fn in enumerate((case_retained_sive_sept30, case_currency_evidence_matrix, case_native_symbol_identity_matrix, case_strike_precision_matrix, case_identity_matrix,
                                            case_terms_and_quote_states, case_dte_nordic_matrix, case_dte_us_matrix)):
            case_id, description, specs, check = builder_fn()
            directory = base / f"c{index}"
            directory.mkdir()
            result = run_main(specs, NOW, directory)
            assert result.rc == 0, f"{case_id}: main exit {result.rc} {result.status}"
            bodies = seal(result.output, NOW, synthetic_tickers=frozenset(spec["symbol"] for spec in specs))
            check(case_id, result, bodies)
            cases[case_id] = {"description": description, "kind": "ADMITTED", "producer_exit": 0, "collection": result.doc["collection"],
                              "bodies": {"options": bodies["v213:options:v2"], "quotes": bodies["v213:quotes:v1"]},
                              "hashes": {"options_sha256": _sha(bodies["v213:options:v2"]), "quotes_sha256": _sha(bodies["v213:quotes:v1"])},
                              "transport_requests": len(result.requests)}
        prior_dir = base / "prior"
        prior_dir.mkdir()
        prior, prior_bodies = _prior_bytes(prior_dir)
        for index, (case_id, venue, chains, healthy, admitted) in enumerate(DEPLETION_CASES):
            directory = base / f"d{index}"
            directory.mkdir()
            specs = _depletion_specs(venue, chains, healthy)
            result = run_main(specs, NOW, directory, prior=prior)
            if admitted:
                assert result.rc == 0, f"{case_id}: a {healthy}/{chains} venue must be admitted: {result.status}"
                got = result.doc["collection"]["chain_health"][venue]
                assert (got["read"], got["healthy"]) == (chains, healthy), f"{case_id}: {got}"
                bodies = seal(result.output, NOW, synthetic_tickers=frozenset(spec["symbol"] for spec in specs))
                cases[case_id] = {"description": f"SYNTHETIC: {venue} {healthy}/{chains} chains two-sided is admitted (boundary)", "kind": "ADMITTED",
                                  "producer_exit": 0, "collection": result.doc["collection"],
                                  "bodies": {"options": bodies["v213:options:v2"], "quotes": bodies["v213:quotes:v1"]},
                                  "hashes": {"options_sha256": _sha(bodies["v213:options:v2"]), "quotes_sha256": _sha(bodies["v213:quotes:v1"])},
                                  "transport_requests": len(result.requests)}
            else:
                assert result.rc == 1 and result.status.get("error") == "OPTION_TWO_SIDED_COVERAGE_LOW", f"{case_id}: {result.status}"
                assert result.status["venues"][venue] == {"read": chains, "healthy": healthy}, f"{case_id}: {result.status}"
                assert result.status["affected_venues"] == [venue], f"{case_id}: {result.status}"
                assert result.output is not None and result.output.read_bytes() == prior, f"{case_id}: old bytes must be unchanged"
                assert seal(result.output, NOW, synthetic_tickers=frozenset(json.loads(prior)["options"])) == prior_bodies, f"{case_id}: the retained old file is sealed unchanged"
                cases[case_id] = {"description": f"SYNTHETIC: {venue} {healthy}/{chains} chains two-sided REJECTS the whole candidate; the candidate is NOT published",
                                  "kind": "REJECTED", "producer_exit": 1, "status": result.status, "prior_file_unchanged": True,
                                  "prior_sha256": hashlib.sha256(prior).hexdigest(),
                                  "retained_old_bodies": {"options": prior_bodies["v213:options:v2"], "quotes": prior_bodies["v213:quotes:v1"]},
                                  "retained_old_hashes": {"options_sha256": _sha(prior_bodies["v213:options:v2"]), "quotes_sha256": _sha(prior_bodies["v213:quotes:v1"])},
                                  "retained_old_generated_at": PRIOR_NOW.strftime("%Y-%m-%dT%H:%M:%SZ")}
    return {"schema": BRIDGE_SCHEMA, "clock": CLOCK, "provenance": PROVENANCE, "cases": cases}


def encode_fixture(document: dict[str, Any]) -> bytes:
    return (json.dumps(document, indent=1, ensure_ascii=False, sort_keys=True) + "\n").encode("utf-8")


def write_fixture(path: Path | None = None) -> Path:
    target = path or FIXTURE_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(encode_fixture(generate_fixture_document()))
    return target


if __name__ == "__main__":
    out = write_fixture()
    print(f"OPTIONS-NONUS-02 bridge fixture written: {out} ({out.stat().st_size} bytes)")
