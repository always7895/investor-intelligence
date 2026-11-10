"""Stage 1F review ruling: delta-uncertainty independent-side model.

Pure offline mathematics; caller verifies contracts, historical source, clock and
quote eligibility. A side that contains any *uncertain* eligible leg (bid/ask implied-delta
difference greater than 0.10) uses HV20/HV60 per-leg IV clamps. No side shares a sigma or IV intersection with another side.
All-tight sides retain the Stage 1C order: provided IV, signed provider Delta,
then the two-sided quote midpoint IV. Only offending wide legs may be dropped
to preserve strike monotonicity. No function here prices an order.
"""
from __future__ import annotations

import math
import re
from decimal import Decimal, ROUND_FLOOR, ROUND_CEILING
from typing import Any

import option_delta_model as bs

MODEL_SCHEMA = "STAGE1E_PER_SIDE_V1"
MODEL_KEYS = frozenset(("schema", "calls", "puts"))
MODES = ("SOURCE_IV", "SOURCE_DELTA", "MID_IV", "HISTORICAL_VOL")
MODE_BASES = {"SOURCE_IV": "QUOTED_IV", "SOURCE_DELTA": "QUOTED",
              "MID_IV": "QUOTE_IMPLIED", "HISTORICAL_VOL": "HISTORICAL_VOL"}
DELTA_UNCERTAINTY_TRIGGER = 0.10
REASON_MONOTONE = "Delta 不確定性過高的履約價非單調；僅剔除此不確定合約"
REASON_MISSING_HISTORY = "Delta 不確定側缺少經核驗的 61 筆調整後收盤價 HV20/HV60，不提供該側策略"
REASON_INVALID_IV = "該雙邊報價不能建立可核驗的逐腿 IV 區間；僅剔除此合約"


def finite(value: Any) -> bool:
    # Extremely large untrusted integers can raise OverflowError in isfinite.
    # Treat them as invalid source values; never abort the whole option chain.
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return False
    try:
        return math.isfinite(value)
    except (OverflowError, ValueError, TypeError):
        return False


def positive(value: Any) -> bool:
    return finite(value) and value > 0


def quote_ok(value: Any) -> bool:
    return (isinstance(value, dict) and positive(value.get("strike"))
            and positive(value.get("bid")) and positive(value.get("ask"))
            and value["bid"] <= value["ask"])


def quote_delta_uncertainty(row: dict[str, Any], spot: float, dte: int, *, put: bool) -> float | None:
    """Absolute change in option delta across its own *two-sided* quote IV range.

    Wide quoted prices are harmless when their Delta uncertainty is <= 0.10.
    No cross-leg or common-IV intersection is implied. An uninvertible leg
    cannot trigger historical inference and may still have verifiable source
    Greeks under the Stage1C quoted path.
    """
    if not quote_ok(row) or not positive(spot) or not finite(dte) or dte < 0:
        return None
    years = max(dte, 1) / 365
    inverse = bs.implied_vol_put if put else bs.implied_vol
    low = inverse(row["bid"], spot, row["strike"], years)
    high = inverse(row["ask"], spot, row["strike"], years)
    if low is None or high is None or not 0 <= low <= high:
        return None
    left = _delta(spot, row["strike"], years, low, put)
    right = _delta(spot, row["strike"], years, high, put)
    if left is None or right is None or not finite(left) or not finite(right):
        return None
    return abs(right - left)


def is_uncertain(row: dict[str, Any], spot: float, dte: int, *, put: bool) -> bool:
    difference = quote_delta_uncertainty(row, spot, dte, put=put)
    return difference is not None and difference > DELTA_UNCERTAINTY_TRIGGER


def _delta(spot: float, strike: float, years: float, sigma: float, put: bool) -> float | None:
    value = bs.bs_call_delta(spot, strike, years, sigma, digits=None)
    return 1 - value if put and value is not None else value


def _leg_result(row: dict[str, Any], value: float, basis: str, sigma: float | None) -> dict[str, Any]:
    return {**row, "delta": round(value, 3), "delta_exact": value,
            "delta_basis": basis,
            "iv": None if basis in ("HISTORICAL_VOL", "QUOTED") else round(sigma, 4) if sigma is not None else None}


def _source_delta(row: dict[str, Any], put: bool) -> float | None:
    value = row.get("delta")
    if not finite(value) or not -1 <= value <= 1:
        return None
    if put and value < 0:
        return -value
    if not put and value >= 0:
        return value
    return None


def _entry(row: dict[str, Any], *, mode: str, sigma: float | None,
           bounds: tuple[float | None, float | None], exact: float) -> dict[str, Any]:
    return {"strike": row["strike"], "bid": row["bid"], "ask": row["ask"],
            "mode": mode, "sigma": sigma, "iv_bid": bounds[0], "iv_ask": bounds[1],
            "delta_exact": exact}


def _tolerant_price(value: float, target: float, spot: float, strike: float) -> bool:
    return abs(value - target) <= 1e-9 + max(spot, strike, abs(target)) * 1e-9


def _eligible_note(row: dict[str, Any], spot: float, put: bool) -> str | None:
    strike = row.get("strike")
    side = "Put" if put else "Call"
    if not positive(strike) or (strike >= spot if put else strike <= spot):
        return None  # ITM and impossible strikes are outside the candidate universe
    if not quote_ok(row):
        return f"{side} 賣出 Bid／買進 Ask 非有效雙邊報價；跳過此合約"
    if round(strike, 2) != strike:
        return f"{side} 履約價不可精確顯示到分；跳過此合約"
    return None


def _fits(a: dict[str, Any], b: dict[str, Any], put: bool) -> bool:
    # Sorted ascending in strike: call delta must be non-increasing,
    # absolute put delta non-decreasing. Work at full precision.
    return a["delta_exact"] <= b["delta_exact"] + 1e-12 if put else a["delta_exact"] >= b["delta_exact"] - 1e-12


def _monotone_side(rows: list[dict[str, Any]], put: bool, skipped: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not rows:
        return []
    ordered = sorted(rows, key=lambda r: (r["strike"], r["bid"], r["ask"]))
    if not any(r["_wide"] for r in ordered):
        return ordered  # all-tight Stage 1C path is byte-for-byte unchanged
    tight = [r for r in ordered if not r["_wide"]]
    accepted: list[dict[str, Any]] = []
    for row in ordered:
        if not row["_wide"]:
            # Tight source/quote legs are Stage1C evidence; never drop one.
            accepted.append(row)
            continue
        lower = accepted[-1] if accepted else None
        future_tight = next((r for r in tight if r["strike"] > row["strike"]), None)
        if (lower is not None and not _fits(lower, row, put)) or (
            future_tight is not None and not _fits(row, future_tight, put)
        ):
            skipped.append({"strike": row["strike"], "reason": REASON_MONOTONE})
            continue
        accepted.append(row)
    return accepted


def calculate_side(rows: list[dict[str, Any]], spot: float, dte: int,
                   history: dict[str, Any] | None, *, put: bool = False,
                   cent_exact_only: bool = True) -> dict[str, Any]:
    """Compute the full eligible side; does not bind calls to puts or delete tight legs.

    Rows are raw parsed quotes with original source IV and signed Delta. The
    returned computed rows are used for tier selection, while compact_wire()
    seals only the actually recommended quoted legs.
    """
    side_name = "puts" if put else "calls"
    skipped: list[dict[str, Any]] = []
    eligible: list[dict[str, Any]] = []
    for row in rows:
        note = _eligible_note(row, spot, put)
        if not cent_exact_only and note is not None and "履約價不可精確顯示到分" in note:
            note = None
        if note is not None:
            skipped.append({"strike": row.get("strike") if positive(row.get("strike")) else None, "reason": note})
        elif quote_ok(row) and (row["strike"] < spot if put else row["strike"] > spot) and (not cent_exact_only or round(row["strike"], 2) == row["strike"]):
            eligible.append(row)
    if not eligible:
        return {"side": side_name, "basis": None, "computed": [], "skipped": skipped,
                "reason": "本側沒有可核驗、價外、雙邊的完整合約"}
    basis = ("HISTORICAL_VOL" if any(is_uncertain(row, spot, dte, put=put) for row in eligible)
             else "QUOTE_IMPLIED")
    if not positive(spot) or not finite(dte) or dte < 0:
        return {"side": side_name, "basis": basis, "computed": [], "skipped": skipped,
                "reason": "現價或到期天數不可核驗"}
    if basis == "HISTORICAL_VOL" and (
        not isinstance(history, dict) or history.get("observations") != 61
        or not all(finite(history.get(key)) and history[key] >= 0 for key in ("hv20", "hv60"))
    ):
        return {"side": side_name, "basis": basis, "computed": [], "skipped": skipped,
                "reason": REASON_MISSING_HISTORY}
    years = max(dte, 1) / 365
    inverse = bs.implied_vol_put if put else bs.implied_vol
    computed: list[dict[str, Any]] = []
    for raw in eligible:
        sigma: float | None = None
        iv_bid: float | None = None
        iv_ask: float | None = None
        mode: str
        exact: float | None = None
        if basis == "HISTORICAL_VOL":
            iv_bid = inverse(raw["bid"], spot, raw["strike"], years)
            iv_ask = inverse(raw["ask"], spot, raw["strike"], years)
            if not (iv_bid is not None and iv_ask is not None and finite(iv_bid) and positive(iv_ask)
                    and iv_bid <= iv_ask):
                skipped.append({"strike": raw["strike"], "reason": REASON_INVALID_IV})
                continue
            sigma = max(iv_bid, min(iv_ask, max(history["hv20"], history["hv60"])))
            mode = "HISTORICAL_VOL"
            if not positive(sigma):
                skipped.append({"strike": raw["strike"], "reason": REASON_INVALID_IV})
                continue
            exact = _delta(spot, raw["strike"], years, sigma, put)
        else:
            provided_iv = raw.get("iv")
            if positive(provided_iv):
                exact = _delta(spot, raw["strike"], years, provided_iv, put)
                if exact is not None:
                    sigma, mode = provided_iv, "SOURCE_IV"
            if exact is None:
                source = _source_delta(raw, put)
                if source is not None:
                    exact, mode = source, "SOURCE_DELTA"
            if exact is None:
                sigma = inverse((raw["bid"] + raw["ask"]) / 2, spot, raw["strike"], years)
                if positive(sigma):
                    exact, mode = _delta(spot, raw["strike"], years, sigma, put), "MID_IV"
        if exact is None or not finite(exact) or not 0 <= exact <= 1:
            skipped.append({"strike": raw["strike"], "reason": "無可核驗的逐腿 Delta，僅剔除此合約"})
            continue
        entry = _entry(raw, mode=mode, sigma=sigma, bounds=(iv_bid, iv_ask), exact=exact)
        computed.append({**_leg_result(raw, exact, MODE_BASES[mode], sigma), "_wide": is_uncertain(raw, spot, dte, put=put), "_entry": entry})
    computed = _monotone_side(computed, put, skipped)
    reason = None
    if not computed:
        reason = (REASON_MISSING_HISTORY if basis == "HISTORICAL_VOL" and history is None
                  else "本側已跳過無效或 Delta 非單調合約，無可用履約價")
    return {"side": side_name, "basis": basis, "computed": computed,
            "skipped": skipped, "reason": reason}


def side_model_wire(result: dict[str, Any], chosen: list[dict[str, Any]]) -> str:
    """Compact side code B,count,first-nonmonotone-uncertain; Greeks recomputed.

    QUOTE_IMPLIED/Q, HISTORICAL_VOL/H, unavailable/-.
    """
    first = next((x["strike"] for x in result["skipped"]
                  if x["reason"] == REASON_MONOTONE), None)
    basis = {"QUOTE_IMPLIED": "Q", "HISTORICAL_VOL": "H", None: "-"}[result["basis"]]
    return f"{basis},{len(result['skipped'])},{str(first) if first is not None else '-'}"


def cycle_model_wire(calls: dict[str, Any], puts: dict[str, Any],
                     call_chosen: list[dict[str, Any]], put_chosen: list[dict[str, Any]]) -> str:
    return "E1|" + side_model_wire(calls, call_chosen) + "|" + side_model_wire(puts, put_chosen)


def is_side_model(value: Any) -> bool:
    return isinstance(value, str) and value.startswith("E1|")


def parsed_side_model(value: Any) -> dict[str, tuple[str | None, int, float | None]] | None:
    if not is_side_model(value) or len(value) > 100:
        return None
    if re.fullmatch(r"E1\|[QH-],[0-9]{1,5},(?:-|[0-9]+(?:\.[0-9]+)?)\|[QH-],[0-9]{1,5},(?:-|[0-9]+(?:\.[0-9]+)?)", value) is None:
        return None
    parts = value.split("|")[1:]
    names = ("calls", "puts")
    out = {}
    for name, part in zip(names, parts):
        letter, count, example = part.split(",")
        value_basis = {"Q": "QUOTE_IMPLIED", "H": "HISTORICAL_VOL", "-": None}[letter]
        n = int(count)
        if n > 100000 or (example != "-" and n == 0):
            return None
        example_float = None if example == "-" else float(example)
        if example_float is not None and not positive(example_float):
            return None
        out[name] = (value_basis, n, example_float)
    return out


def valid_side_model(value: Any, history: Any) -> bool:
    return parsed_side_model(value) is not None


LIMIT_TICK = Decimal("0.01")


def decimal_tick_limit(bid: float, ask: float, theoretical: float, *,
                       buy: bool, tick: Decimal = LIMIT_TICK) -> float | None:
    """Stage1G executable tick limit. Decimal(str(number)) prevents float-mid
    contamination. Snap AFTER clamping the model, never clamp a snapped limit
    back to an off-tick midpoint (the Stage1F N1 defect).

    A malformed quote with no tick in [bid, floor_tick(mid)] has no valid
    executable price; refuse it rather than manufacturing an off-tick order.
    """
    if not (positive(bid) and positive(ask) and finite(theoretical)
            and theoretical >= 0 and bid <= ask and tick > 0):
        return None
    lower, upper = (Decimal(str(v)) for v in (bid, ask))
    # Model prices come from independent Python/Worker BS inversions. A
    # difference of a few IEEE ULPs straddling e.g. 0.0500000000000000
    # must NOT move a buy LIMIT by a full executable cent.
    model = Decimal(str(theoretical)).quantize(Decimal("0.000000000001"))
    mid = (lower + upper) / 2
    mid_floor = (mid / tick).to_integral_value(rounding=ROUND_FLOOR) * tick
    first_tick = (lower / tick).to_integral_value(rounding=ROUND_CEILING) * tick
    if first_tick > mid_floor:
        return None
    clamped = max(lower, min(mid, model))
    snapped = (clamped / tick).to_integral_value(
        rounding=ROUND_CEILING if buy else ROUND_FLOOR) * tick
    # Keep an exact tick throughout, even if the post-round cap is binding.
    return float(min(mid_floor, max(first_tick, snapped)).quantize(tick))


def model_based_limit(leg: dict[str, Any], spot: float, dte: int, sigma: float,
                      *, put: bool, buy: bool) -> float | None:
    """Compute the clamped-volatility model starting price; return only an
    executable $/SEK 0.01 tick within real Bid and floor_tick(mid).
    It is not a guaranteed fill or a midpoint-based quote.
    """
    if not quote_ok(leg) or not positive(spot) or not positive(sigma):
        return None
    years = max(dte, 1) / 365
    theoretical = (bs.bs_put_price if put else bs.bs_call_price)(
        spot, leg["strike"], years, sigma)
    if theoretical is None or not finite(theoretical):
        return None
    return decimal_tick_limit(leg["bid"], leg["ask"], theoretical, buy=buy)


def limit_from_computed(row: dict[str, Any], spot: float, dte: int, *,
                        put: bool=False, buy: bool=False) -> float | None:
    if row.get("delta_basis") != "HISTORICAL_VOL":
        return None
    entry=row.get("_entry")
    limit = model_based_limit(row, spot, dte,
                              entry.get("sigma") if isinstance(entry, dict) else None,
                              put=put, buy=buy)
    if limit is None:
        raise ValueError("STAGE1G_HISTORICAL_LIMIT_NO_VALID_TICK")
    return limit


def model_leg_consistent(leg: Any, model: Any, history: Any,
                         spot: float, dte: int, *, put: bool, buy: bool = False,
                         band: tuple[float, float] | None = None) -> bool:
    if (not isinstance(leg, dict) or not valid_side_model(model, history) or not quote_ok(leg)
        or not positive(spot) or not finite(dte) or dte < 0):
        return False
    parsed = parsed_side_model(model)
    if parsed is None:
        return False
    basis = parsed["puts" if put else "calls"][0]
    shown = leg.get("delta")
    if not finite(shown) or not 0 <= shown <= 1:
        return False
    years = max(dte, 1) / 365
    sigma = None
    exact = None
    leg_basis = leg.get("delta_basis")
    if basis == "HISTORICAL_VOL":
        sigmas = bs._history_sigmas(history)
        if sigmas is None or leg_basis != "HISTORICAL_VOL":
            return False
        inverse = bs.implied_vol_put if put else bs.implied_vol
        iv_bid = inverse(leg["bid"], spot, leg["strike"], years)
        iv_ask = inverse(leg["ask"], spot, leg["strike"], years)
        if (iv_bid is None or iv_ask is None or not finite(iv_bid)
            or not positive(iv_ask) or iv_bid > iv_ask):
            return False
        sigma = min(iv_ask, max(*sigmas, iv_bid))
        if not positive(sigma):
            return False
        exact = _delta(spot, leg["strike"], years, sigma, put)
        if "iv" in leg and leg["iv"] is not None:
            return False
        if "limit_price" in leg:
            limit=model_based_limit(leg,spot,dte,sigma,put=put,buy=buy)
            if limit is None or not finite(leg.get("limit_price")) or abs(leg["limit_price"]-limit)>1e-8:
                return False
    elif basis == "QUOTE_IMPLIED":
        if is_uncertain(leg, spot, dte, put=put) or leg_basis not in ("QUOTE_IMPLIED", "QUOTED_IV", "QUOTED"):
            return False
        if leg_basis == "QUOTED":
            # Stage 1C explicitly permitted a valid source Delta independently
            # of a midpoint model; retain the old quote-side evidence rule.
            if "iv" in leg and leg["iv"] is not None:
                return False
            exact = shown
        else:
            if leg_basis == "QUOTED_IV" and "iv" in leg and positive(leg["iv"]):
                sigma = leg["iv"]
            elif leg_basis == "QUOTED_IV":
                # Put/collar six-key legs omit IV by design. Stage1C used the
                # verified source IV and sealed only the resulting Delta.
                exact = shown
            else:
                inverse = bs.implied_vol_put if put else bs.implied_vol
                sigma = inverse(leg["bid"] / 2 + leg["ask"] / 2, spot, leg["strike"], years)
                if not positive(sigma):
                    return False
                if "iv" in leg and (not finite(leg["iv"]) or abs(leg["iv"] - round(sigma, 4)) > .00005 + 1e-12):
                    return False
            if sigma is not None:
                exact = _delta(spot, leg["strike"], years, sigma, put)
    else:
        return False
    if exact is None or not finite(exact) or abs(shown - exact) > .0005 + 1e-12:
        return False
    if band is not None and (not isinstance(band, (tuple, list)) or len(band) != 2
                             or not 0 <= band[0] <= exact <= band[1] <= 1):
        return False
    return True
