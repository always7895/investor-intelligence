import type { HistoricalVolatility } from "./historical-volatility";
import { MAX_QUOTE_IMPLIED_SPREAD_RATIO } from "./option-recommendation-rules";

export interface DeltaModel {
  basis: "QUOTE_IMPLIED" | "HISTORICAL_VOL";
  sigma: number;
  iv_bid: number;
  iv_ask: number;
}

const MODEL_KEYS = new Set(["basis", "sigma", "iv_bid", "iv_ask"]);
const NUMERIC_TOLERANCE = 1e-12;

function finite(value: unknown): value is number {
  return typeof value === "number" && Number.isFinite(value);
}

export function validDeltaModel(value: unknown, history: HistoricalVolatility | undefined): value is DeltaModel {
  try {
    if (typeof value !== "object" || value === null || Array.isArray(value)) return false;
    const keys = Reflect.ownKeys(value);
    if (keys.length !== MODEL_KEYS.size || keys.some(key => typeof key !== "string" || !MODEL_KEYS.has(key))) return false;
    if (!("basis" in value) || !("sigma" in value) || !("iv_bid" in value) || !("iv_ask" in value)) return false;
    if (!finite(value.sigma) || !finite(value.iv_bid) || !finite(value.iv_ask)
      || value.iv_bid < 0 || value.sigma <= 0 || value.iv_ask <= 0
      || value.iv_bid > value.sigma || value.sigma > value.iv_ask) return false;
    let expected: number;
    if (value.basis === "QUOTE_IMPLIED") {
      expected = value.iv_bid / 2 + value.iv_ask / 2;
    } else if (value.basis === "HISTORICAL_VOL") {
      // Identity, source and clock admission belong to validHistoricalVolatility at the caller.
      if (!history || history.observations !== 61 || !finite(history.hv20) || history.hv20 < 0
        || !finite(history.hv60) || history.hv60 < 0) return false;
      expected = Math.min(value.iv_ask, Math.max(history.hv20, history.hv60, value.iv_bid));
    } else {
      return false;
    }
    return Math.abs(value.sigma - expected) <= NUMERIC_TOLERANCE;
  } catch {
    return false;
  }
}

function normalCdf(x: number): number {
  if (x <= -8) return 0;
  if (x >= 8) return 1;
  const magnitude = Math.abs(x);
  if (magnitude === 0) return 0.5;
  // Integral series: phi(x) * (x + x^3/3 + x^5/(3*5) + ...).
  // All terms are positive; compensated summation preserves near-tail accuracy.
  const squared = magnitude * magnitude;
  let term = magnitude;
  let sum = term;
  let correction = 0;
  for (let denominator = 3; ; denominator += 2) {
    term *= squared / denominator;
    const adjusted = term - correction;
    const next = sum + adjusted;
    correction = (next - sum) - adjusted;
    sum = next;
    if (term <= sum * Number.EPSILON) break;
  }
  const integral = Math.exp(-squared / 2) / Math.sqrt(2 * Math.PI) * sum;
  return Math.max(0, Math.min(1, x < 0 ? 0.5 - integral : 0.5 + integral));
}

function roundedIv(sigma: number): number {
  // Python round(sigma, 4) and toFixed agree except exact binary ties.
  // Such decimal half-steps are precisely odd multiples of 1/32.
  const thirtySeconds = sigma * 32;
  if (Number.isSafeInteger(thirtySeconds) && thirtySeconds % 2 === 1) {
    const lower = Math.floor(sigma * 10_000);
    return (lower + lower % 2) / 10_000;
  }
  return Number(sigma.toFixed(4));
}

export function modelLegConsistent(
  leg: Record<string, unknown>, model: DeltaModel, spot: number, dte: number,
  put: boolean, band?: readonly [number, number],
): boolean {
  try {
    if (!finite(spot) || spot <= 0 || !finite(dte) || dte < 0 || !finite(model.sigma) || model.sigma <= 0
      || (model.basis !== "QUOTE_IMPLIED" && model.basis !== "HISTORICAL_VOL")) return false;
    const { strike, bid, ask, delta, delta_basis: basis } = leg;
    if (!finite(strike) || strike <= 0 || !finite(bid) || !finite(ask) || bid <= 0 || ask < bid
      || !finite(delta) || delta < 0 || delta > 1 || basis !== model.basis) return false;
    const wide = (ask - bid) / (bid / 2 + ask / 2) > MAX_QUOTE_IMPLIED_SPREAD_RATIO;
    if (wide !== (model.basis === "HISTORICAL_VOL")) return false;
    const years = Math.max(dte, 1) / 365;
    const scaledVol = model.sigma * Math.sqrt(years);
    if (!finite(scaledVol) || scaledVol <= 0) return false;
    const d1 = (Math.log(spot) - Math.log(strike) + 0.04 * years) / scaledVol + scaledVol / 2;
    const d2 = d1 - scaledVol;
    const discountedStrike = strike * Math.exp(-0.04 * years);
    const absoluteDelta = normalCdf(put ? -d1 : d1);
    const price = put
      ? discountedStrike * normalCdf(-d2) - spot * absoluteDelta
      : spot * absoluteDelta - discountedStrike * normalCdf(d2);
    const priceTolerance = 1e-10 + Math.max(spot, strike) * 1e-12;
    if (!finite(price) || !finite(absoluteDelta) || price < bid - priceTolerance || price > ask + priceTolerance
      || Math.abs(delta - absoluteDelta) > 0.0005 + NUMERIC_TOLERANCE) return false;
    if (band && (!finite(band[0]) || !finite(band[1]) || band[0] < 0 || band[1] > 1 || band[0] > band[1]
      || absoluteDelta < band[0] - NUMERIC_TOLERANCE || absoluteDelta > band[1] + NUMERIC_TOLERANCE)) return false;
    if ("iv" in leg) {
      if (model.basis === "HISTORICAL_VOL") return leg.iv === null;
      if (!finite(leg.iv) || Math.abs(leg.iv - roundedIv(model.sigma)) > 0.00005 + NUMERIC_TOLERANCE) return false;
    }
    return true;
  } catch {
    return false;
  }
}
