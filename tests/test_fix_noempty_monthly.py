import sys
from datetime import date, timedelta
from pathlib import Path
import pytest
import math
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import build_market_quotes_options as product
import option_delta_model as md
import option_delta_side_model as side_math
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

def test_nearest_standard_monthly_low_yield_is_still_a_strategy():
    # Quotes must themselves support a coherent common IV. The original 0.01/0.02
    # pair was a 66% spread, which correctly becomes history-missing observation.
    fair=md.bs_call_price(SPOT,17.5,12/365,.30)
    bid=math.floor(fair*.97*1_000_000)/1_000_000
    ask=math.ceil(fair*1.03*1_000_000)/1_000_000
    got=run_monthly([row(FIRST,12,17.5,bid,ask),row(SECOND,40,18.0,2.0,2.1)])
    assert "unavailable" not in got
    assert "quote_observation" not in got
    assert got["expiry"]==FIRST
    assert got["suggestions"]
    assert 0<got["suggestions"][0]["annualized_yield"]<.02
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
    cycle=run_monthly([row(FIRST,12,17.0,None,None,.01)])
    cycle["quote_observation"]["annualized_yield"]=.99
    with pytest.raises(MarketProductValidationError):
        check(cycle)
    cycle=run_monthly([row(FIRST,12,17.0,None,None,.01)])
    with pytest.raises(MarketProductValidationError):
        validate_covered_call_cycle(cycle,evaluated_at=STAMP,document_at=STAMP,period="weekly")

def test_weekly_does_not_fill_missing_standard_monthly():
    got=run_monthly([row("2026-11-13",5,17.0,.1,.2)])
    assert set(got)=={"unavailable"}
    assert FIRST in got["unavailable"]


@pytest.mark.parametrize("dte", range(7))
@pytest.mark.parametrize("bid,ask,last", [(None,None,.09), (None,None,None), (.01,.04,None)])
def test_short_standard_monthly_keeps_source_evidence_and_finite_annualization(dte,bid,ask,last):
    today=date.fromisoformat(FIRST)-timedelta(days=dte)
    stamp=today.isoformat()+"T12:00:00Z"
    cycle=product._cycles_from_calls(
        [row(FIRST,dte,17.0,bid,ask,last),row(SECOND,dte+28,18.0,2.0,2.1)],
        "SIVE.ST",SPOT,stamp,currency="SEK",source="synthetic unit test",
        provenance="https://example.com/options-test",rights="operator_accepted_unlicensed",
        missing="no listed monthly",today=today,venue="STOCKHOLM",
        identity=product.NORDIC_OPTION_IDENTITY)["monthly"]
    assert cycle["expiry"]==FIRST
    # Pin exact Stage1G outcome; a relative spread alone is not an HV trigger.
    # The 0.01/0.04 two-sided case stays QUOTE_IMPLIED at all seven DTEs.
    if bid is not None:
        uncertainty=side_math.quote_delta_uncertainty(
            {"strike":17.0,"bid":bid,"ask":ask},SPOT,dte,put=False)
        assert uncertainty is not None and uncertainty<=.10
        assert "quote_observation" not in cycle
        assert len(cycle["suggestions"]) >= 1
        leg=cycle["suggestions"][0]
        assert leg["bid"]==bid and leg["ask"]==ask
        assert leg["delta_basis"]=="QUOTE_IMPLIED"
        assert bid<=leg["limit_price"]<=(bid+ask)/2
        assert math.isfinite(leg["annualized_yield"]) and leg["annualized_yield"]>=0
    else:
        observation=cycle["quote_observation"]
        assert cycle["suggestions"]==[]
        assert observation["kind"]=="NO_TWO_SIDED"
        assert observation["annualized_yield"] == (None if last is None else round(last/SPOT*365/max(dte,1),6))
    validate_covered_call_cycle(cycle,evaluated_at=stamp,document_at=stamp,period="monthly")


def test_standard_expiry_can_be_weekly_and_monthly_until_close():
    today=date(2026,11,20)
    stamp="2026-11-20T16:29:00Z"
    quoted={**row(FIRST,0,17.0,.10,.12),"delta":.10}
    cycles=product._cycles_from_calls(
        [quoted],"SIVE.ST",SPOT,stamp,currency="SEK",source="synthetic unit test",
        provenance="https://example.com/options-test",rights="operator_accepted_unlicensed",
        missing="no listed expiry",today=today,venue="STOCKHOLM",
        identity=product.NORDIC_OPTION_IDENTITY)
    assert cycles["weekly"]["expiry"]==cycles["monthly"]["expiry"]==FIRST
    assert cycles["weekly"]["dte"]==cycles["monthly"]["dte"]==0
    for period in ("weekly","monthly"):
        validate_covered_call_cycle(cycles[period],stamp,stamp,period)


def test_explicit_source_calendar_shift_is_preserved_but_not_inferred():
    today=date(2026,6,18)
    stamp="2026-06-18T12:00:00Z"
    shifted={**row("2026-06-18",0,17.0,.10,.12),"delta":.10}
    kwargs=dict(currency="SEK",source="synthetic verified calendar input",
        provenance="https://example.com/options-test",rights="operator_accepted_unlicensed",
        missing="no listed expiry",today=today,venue="STOCKHOLM",
        identity=product.NORDIC_OPTION_IDENTITY)
    unproven=product._cycles_from_calls([shifted],"SIVE.ST",SPOT,stamp,**kwargs)["monthly"]
    assert "2026-06-19" in unproven["unavailable"]
    proven=product._cycles_from_calls([shifted],"SIVE.ST",SPOT,stamp,
        verified_monthly_expiries=[today],**kwargs)["monthly"]
    assert (proven["expiry"],proven["monthly_rule"])==("2026-06-18","HOLIDAY_SHIFT")
    validate_covered_call_cycle(proven,stamp,stamp,"monthly")
