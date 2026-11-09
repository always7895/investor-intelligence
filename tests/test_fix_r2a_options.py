import sys,json,copy
from pathlib import Path
from datetime import date
from unittest.mock import patch
import pytest
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"scripts"))
import build_market_quotes_options as builder
from validate_v213_market_products import validate_covered_call_cycle,validate_options_coverage_document,MarketProductValidationError
ASOF=date(2026,11,8)
STAMP="2026-11-08T14:16:09Z"
EX="2026-11-20"
def row(strike,bid,ask,iv,*,put=False):
    return {"expiry":EX,"dte":12,"strike":strike,"bid":bid,"ask":ask,"iv":iv,
            "size":100,"oi":200,"volume":10}
def candidate(two_sided=True):
    calls=[row(107.5,0.01,0.02,0.50),row(110,0.01,0.02,0.50),
           row(120,0.01,0.02,0.5)]
    puts=[row(90,0.25,0.30,0.7,put=True),row(95,0.55,0.65,0.50,put=True)]
    if not two_sided:
        for c in calls:c["bid"]=None;c["ask"]=None
    return builder._cycles_from_calls(calls,"UNIT",100,STAMP,currency="USD",
        source="synthetic test observations",provenance="https://example.org/typed-public-chain",
        rights="operator_accepted_unlicensed",missing="monthly absence",
        venue="US",today=ASOF,identity=builder.YAHOO_OPTION_IDENTITY,puts=puts)["monthly"]

def test_monthly_three_strategies_are_independent_from_low_premium_quote():
    cycle=candidate()
    assert "unavailable" not in cycle
    assert cycle["quote_observation"]["kind"]=="TWO_SIDED"
    assert cycle["suggestions"]==[]
    assert cycle["strategies"]["cc"]["unavailable"]
    assert ("unavailable" not in cycle["strategies"]["csp"] or
            "unavailable" not in cycle["strategies"]["collar"])
    validate_covered_call_cycle(cycle,STAMP,STAMP,"monthly")

def test_monthly_no_two_sided_call_keeps_safe_put_strategy_only():
    cycle=candidate(two_sided=False)
    assert cycle["quote_observation"]["kind"]=="NO_TWO_SIDED"
    assert cycle["quote_observation"]["annualized_yield"] is None
    if "strategies" in cycle:
        assert cycle["strategies"]["cc"]["unavailable"]
    validate_covered_call_cycle(cycle,STAMP,STAMP,"monthly")

def test_monthly_weekly_expiry_cannot_pass_python_format_validator():
    cycle=candidate()
    wrong=copy.deepcopy(cycle)
    wrong["expiry"]="2026-11-13"
    wrong["dte"]=5
    wrong["asof_date"]=ASOF.isoformat()
    wrong["monthly_rule"]="THIRD_FRIDAY"
    with pytest.raises(MarketProductValidationError):
        validate_covered_call_cycle(wrong,STAMP,STAMP,"monthly")

def test_versioned_coverage_source_integrity_and_closed_schema():
    path=ROOT.parent/"data/after_coverage_body.json"
    if not path.is_file():
        pytest.skip("requires copied public sealed coverage data, present only in operator workspace")
    doc=json.loads(path.read_text(encoding="utf-8"))
    assert doc["schema"]=="v213-options-coverage-v2"
    assert doc["catalog_version"].startswith("sha256:")
    assert len(doc["providers"])>=18
    validate_options_coverage_document(doc)
    broken=copy.deepcopy(doc)
    broken["catalog_version"]="unverified"
    with pytest.raises(MarketProductValidationError):
        validate_options_coverage_document(broken)
    leaked=copy.deepcopy(doc)
    leaked["providers"][0]["bid"]=0.01
    with pytest.raises(MarketProductValidationError):
        validate_options_coverage_document(leaked)

def test_nasdaq_us_format_parsing_rejects_unsupported_dates_and_prices():
    assert builder._nasdaq_us_group_date("Nov 20, 2026")==date(2026,11,20)
    assert builder._nasdaq_us_group_date("2026-11-20")==date(2026,11,20)
    assert builder._nasdaq_us_group_date("2026-11-31") is None
    assert builder._nasdaq_us_quote("$1.25")==1.25
    assert builder._nasdaq_us_quote("1,200.50")==1200.50
    assert builder._nasdaq_us_quote("1e309") is None
    assert builder._nasdaq_us_quote("unavailable") is None

def test_nordic_decimal_quote_but_no_identity_guess():
    assert builder._nordic_price("0,75")==0.75
    assert builder._nordic_price("1,50")==1.5
    assert builder._nordic_price("1,200.25") is None
    assert builder._nordic_price("not_available") is None


# G01: missing standard monthly never authorizes a weekly observation.
def test_cached_weekly_contract_is_not_a_monthly_observation():
    evidence={"expiry":"2026-12-11","dte":33,"strike":110.0,
              "bid":0.30,"ask":0.32,"last":None,"oi":20,"volume":3,"size":100}
    cycle=builder._cycles_from_calls(
        [evidence],"UNIT",100,STAMP,currency="USD",source="synthetic chain",
        provenance="https://example.org/source",rights="operator_accepted_unlicensed",
        missing="no standard",today=ASOF,venue="US",
        identity=builder.YAHOO_OPTION_IDENTITY)["monthly"]
    assert "2026-11-20" in cycle["unavailable"]
    assert set(cycle) == {"unavailable"}


def test_yahoo_queries_missing_nearest_standard_and_never_substitutes_weekly_or_successor():
    from types import SimpleNamespace
    from unittest.mock import patch
    fake_call=SimpleNamespace(strike=110.0,bid=0.35,ask=0.37,lastPrice=0.36,
        impliedVolatility=0.50,openInterest=80,volume=8,contractSize="REGULAR",currency="USD")
    chain=SimpleNamespace(calls=SimpleNamespace(itertuples=lambda:iter([fake_call])),puts=None)
    class Ticker:
        options=["2026-12-11"]  # cached expiry list lacks both standard monthlies
        def __init__(self, mode):
            self.mode=mode
            self.requests=[]
        def option_chain(self, expiry):
            self.requests.append(expiry)
            if expiry=="2026-12-11" or (self.mode=="success" and expiry=="2026-11-20"):
                return chain
            raise ValueError("No chain returned for that expiry")
    import sys
    for mode in ("success", "only_weekly"):
        ticker=Ticker(mode)
        with patch.dict(sys.modules,{"yfinance":SimpleNamespace(Ticker=lambda _:ticker)}):
            result=builder.us_options("UNIT",100,ASOF,STAMP)
        month=result["monthly"]
        assert ticker.requests == ["2026-11-20"]
        if mode == "success":
            assert month["expiry"] == "2026-11-20"
            validate_covered_call_cycle(month,STAMP,STAMP,"monthly")
        else:
            assert set(month) == {"unavailable"}
            assert "2026-11-20" in month["unavailable"]


def test_nasdaq_queries_standard_expiry_when_initial_chain_lists_only_weekly():
    from unittest.mock import patch
    all_requests=[]
    def payload(expiry):
        item={"strike":"110","c_Bid":"0.30","c_Ask":"0.35",
              "c_Openinterest":"10","c_Volume":"1"}
        return {"data":{"lastTrade":"LAST TRADE: $100 (AS OF NOV 8, 2026)",
                "table":{"rows":[{"expirygroup":expiry},item] if expiry else []}}}
    def http(url):
        all_requests.append(url)
        if "fromdate=2026-11-20" in url:return payload("November 20, 2026")
        return payload("December 11, 2026")
    with patch.object(builder,"http_json",side_effect=http):
        result=builder.nasdaq_us_options("UNIT",100,ASOF,STAMP)["monthly"]
    assert result["expiry"]=="2026-11-20"
    assert len(all_requests)==2
    assert result.get("suggestions") or result.get("quote_observation")
    validate_covered_call_cycle(result,STAMP,STAMP,"monthly")


def test_nordic_rechecks_nearest_standard_then_refuses_if_not_listed():
    from unittest.mock import patch
    from tests.test_monthly_options_fallback import nordic_row
    initial=nordic_row(date(2026,12,11))
    standard=nordic_row(date(2026,11,20))
    for refreshed,available in (([initial,standard],True), ([initial],False)):
        requests=[]
        def http(url):
            requests.append(url)
            rows=[initial] if len(requests)==1 else refreshed
            return {"data":{"instrumentListing":{"rows":rows}}}
        with patch.object(builder,"http_json",side_effect=http):
            cycle=builder.nordic_options("SIVE.ST","SIVE",100,ASOF,STAMP,
                "synthetic",spot_currency="SEK")["monthly"]
        assert len(requests)==2
        if available:
            assert cycle["expiry"]=="2026-11-20"
            validate_covered_call_cycle(cycle,STAMP,STAMP,"monthly")
        else:
            assert set(cycle)=={"unavailable"}
            assert "2026-11-20" in cycle["unavailable"]
