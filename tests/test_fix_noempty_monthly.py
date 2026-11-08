import sys
from datetime import date
from pathlib import Path
import pytest
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import build_market_quotes_options as product
from validate_v213_market_products import validate_covered_call_cycle, MarketProductValidationError

TODAY=date(2026,11,8)
STAMP="2026-11-08T14:16:09Z"
FIRST="2026-11-20"
SECOND="2026-12-18"
SPOT=15.5

def row(expiry,dte,strike,bid,ask,last=None):
    return {"expiry":expiry,"dte":dte,"strike":strike,"bid":bid,"ask":ask,
            "last":last,"size":100,"oi":100,"volume":5}

def run_monthly(rows):
    return product._cycles_from_calls(
        rows,"SIVE.ST",SPOT,STAMP,currency="SEK",source="synthetic unit test",
        provenance="https://example.com/options-test",rights="operator_accepted_unlicensed",missing="no listed monthly",
        today=TODAY,venue="STOCKHOLM",underlying="SIVE.ST",identity=product.NORDIC_OPTION_IDENTITY
    )["monthly"]

def check(cycle):
    validate_covered_call_cycle(cycle,evaluated_at=STAMP,document_at=STAMP,period="monthly")

def test_next_standard_monthly_below_hurdle_is_visible_not_unavailable():
    got=run_monthly([row(FIRST,12,17.0,.01,.02),row(SECOND,40,18.0,.07,.08)])
    assert "unavailable" not in got
    assert got["quote_observation"]["kind"]=="TWO_SIDED"
    assert got["expiry"]==SECOND
    assert got["suggestions"]==[]
    assert 0<got["quote_observation"]["annualized_yield"]<.06
    check(got)

def test_no_two_sided_but_last_trade_keeps_observation_and_does_not_claim_bid():
    got=run_monthly([row(FIRST,12,17.0,None,None,.09),row(SECOND,40,18.0,None,None,.02)])
    assert "unavailable" not in got
    assert got["quote_observation"]["kind"]=="NO_TWO_SIDED"
    assert got["quote_observation"]["bid"] is None
    assert got["quote_observation"]["ask"] is None
    assert got["quote_observation"]["last"] == .09
    check(got)

def test_missing_quote_values_never_fabricate_premium_or_yield():
    got=run_monthly([row(FIRST,12,17.0,None,None),row(SECOND,40,18.0,None,None)])
    assert got["quote_observation"]["annualized_yield"] is None
    assert got["quote_observation"]["last"] is None
    check(got)

def test_observation_rejects_changed_annual_or_weekly_label():
    cycle=run_monthly([row(FIRST,12,17.0,.01,.02)])
    cycle["quote_observation"]["annualized_yield"]=.99
    with pytest.raises(MarketProductValidationError):
        check(cycle)
    cycle=run_monthly([row(FIRST,12,17.0,.01,.02)])
    with pytest.raises(MarketProductValidationError):
        validate_covered_call_cycle(cycle,evaluated_at=STAMP,document_at=STAMP,period="weekly")

def test_no_seven_day_monthly_preserves_legacy_validation_without_quote_observation():
    # The >=7-day search is prioritized; without such a listing, a legacy
    # short-dated standard monthly may still be processed by the older strategy validator.
    got=run_monthly([row("2026-11-13",5,17.0,.1,.2)])
    assert "quote_observation" not in got
