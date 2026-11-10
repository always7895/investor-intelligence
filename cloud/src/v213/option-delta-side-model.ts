/** Stage 1E side-scoped Delta verifier; mirrors scripts/option_delta_side_model.py.
 * The compact three-cell side wire retains the 1.9MB lazy-body ceiling.
 * Historical per-leg IV bounds and clamp are RECOMPUTED from actual Bid/Ask
 * by the independent Worker, never trusted as repeated producer metadata. */
import type { HistoricalVolatility } from "./historical-volatility";


export const SIDE_MODEL_SCHEMA = "STAGE1E_PER_SIDE_V1" as const;
export type SideBasis = "QUOTE_IMPLIED" | "HISTORICAL_VOL" | null;
export type SideCompact = readonly [SideBasis, number, number | null];
export type SideCycleDeltaModel = string;
const RE = /^E1\|([QH-]),([0-9]{1,5}),(-|[0-9]+(?:\.[0-9]+)?)\|([QH-]),([0-9]{1,5}),(-|[0-9]+(?:\.[0-9]+)?)$/u;
const finite = (x: unknown): x is number => typeof x === "number" && Number.isFinite(x);
const positive = (x: unknown): x is number => finite(x) && x > 0;
const record = (x: unknown): x is Record<string, unknown> => x !== null && typeof x === "object" && !Array.isArray(x);
const quoteOk = (leg: Record<string, unknown>) =>
  positive(leg.strike) && positive(leg.bid) && positive(leg.ask) && leg.bid <= leg.ask;
export const DELTA_UNCERTAINTY_TRIGGER = 0.10;
export function isSideCycleDeltaModel(value: unknown): value is SideCycleDeltaModel {
  return typeof value === "string" && value.startsWith("E1|");
}
export function parseSideDeltaModel(value: unknown): {calls: SideCompact; puts: SideCompact} | null {
  if (typeof value !== "string" || value.length > 100) return null;
  const m = RE.exec(value);
  if (!m) return null;
  function decode(a: string, b: string, c: string): SideCompact | null {
    const basis: SideBasis = a === "H" ? "HISTORICAL_VOL" : a === "Q" ? "QUOTE_IMPLIED" : null;
    const n = Number(b), example = c === "-" ? null : Number(c);
    if (!Number.isInteger(n) || n > 100000 || (example !== null && (!positive(example) || n === 0))) return null;
    return [basis, n, example];
  }
  const calls = decode(m[1]!, m[2]!, m[3]!);
  const puts = decode(m[4]!, m[5]!, m[6]!);
  return calls && puts ? {calls, puts} : null;
}
export function validSideCycleDeltaModel(value: unknown, _history: HistoricalVolatility | undefined): value is SideCycleDeltaModel {
  return parseSideDeltaModel(value) !== null;
}
function cdf(x: number): number {
  if (x <= -8) return 0;
  if (x >= 8) return 1;
  const magnitude = Math.abs(x);
  if (magnitude === 0) return 0.5;
  const squared = magnitude * magnitude;
  let term = magnitude, sum = term, correction = 0;
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
function priceDelta(spot: number, strike: number, years: number, sigma: number, put: boolean): [number, number] | null {
  if (!positive(spot) || !positive(strike) || !positive(years) || !finite(sigma) || sigma < 0) return null;
  const discounted = strike * Math.exp(-0.04 * years);
  if (!finite(discounted)) return null;
  if (sigma === 0) return [Math.max(put ? discounted - spot : spot - discounted, 0), 0];
  const scaled = sigma * Math.sqrt(years);
  if (!positive(scaled)) return null;
  const d1 = (Math.log(spot) - Math.log(strike) + 0.04 * years) / scaled + scaled / 2;
  const d2 = d1 - scaled;
  if (!finite(d1) || !finite(d2)) return null;
  const delta = cdf(put ? -d1 : d1);
  const price = put ? discounted * cdf(-d2) - spot * cdf(-d1) : spot * cdf(d1) - discounted * cdf(d2);
  return finite(price) && finite(delta) ? [Math.max(price, 0), delta] : null;
}
function inverse(price: number, spot: number, strike: number, years: number, put: boolean): number | null {
  if (!finite(price) || price < 0 || !positive(spot) || !positive(strike) || !positive(years)) return null;
  const minimum = priceDelta(spot, strike, years, 0, put)?.[0];
  const maximum = put ? strike * Math.exp(-0.04 * years) : spot;
  if (minimum === undefined || !finite(maximum) || price < minimum || price >= maximum) return null;
  if (price === minimum) return 0;
  let low = 0, high = 1;
  for (let n = 0; n < 1024; n++) {
    const highPrice = priceDelta(spot, strike, years, high, put)?.[0];
    if (highPrice === undefined) return null;
    if (highPrice >= price) break;
    low = high;
    high *= 2;
    if (!finite(high)) return null;
  }
  for (let n = 0; n < 100; n++) {
    const mid = low / 2 + high / 2;
    if (mid === low || mid === high) break;
    const observed = priceDelta(spot, strike, years, mid, put)?.[0];
    if (observed === undefined) return null;
    if (observed < price) low = mid;
    else high = mid;
  }
  const sigma = low / 2 + high / 2;
  return positive(sigma) ? sigma : null;
}
function roundedIv(sigma: number): number {
  const thirtySeconds = sigma * 32;
  if (Number.isSafeInteger(thirtySeconds) && thirtySeconds % 2 === 1) {
    const lower = Math.floor(sigma * 10_000);
    return (lower + lower % 2) / 10_000;
  }
  return Number(sigma.toFixed(4));
}
function deltaUncertainty(leg: Record<string,unknown>, spot: number, dte: number, put: boolean): number | null {
  if (!quoteOk(leg) || !positive(spot) || !finite(dte) || dte < 0) return null;
  const strike = Number(leg.strike), years = Math.max(dte,1) / 365;
  const lo = inverse(Number(leg.bid),spot,strike,years,put);
  const hi = inverse(Number(leg.ask),spot,strike,years,put);
  if (lo === null || hi === null || lo > hi) return null;
  const dl = priceDelta(spot,strike,years,lo,put)?.[1];
  const dh = priceDelta(spot,strike,years,hi,put)?.[1];
  return dl === undefined || dh === undefined ? null : Math.abs(dh-dl);
}

export function sideModelLegConsistent(
  leg: Record<string, unknown>, model: SideCycleDeltaModel,
  history: HistoricalVolatility | undefined, spot: number, dte: number,
  put: boolean, band?: readonly [number, number], buy = false,
): boolean {
  try {
    if (!record(leg) || !validSideCycleDeltaModel(model, history) || !quoteOk(leg)
      || !positive(spot) || !finite(dte) || dte < 0 || !finite(leg.delta)
      || leg.delta < 0 || leg.delta > 1) return false;
    const strike = Number(leg.strike), bid = Number(leg.bid), ask = Number(leg.ask);
    const shown = Number(leg.delta);
    const parsed = parseSideDeltaModel(model);
    if (!parsed) return false;
    const basis = (put ? parsed.puts : parsed.calls)[0];
    const years = Math.max(dte, 1) / 365;
    let exact: number | null = null;
    let sigma: number | null = null;
    if (basis === "HISTORICAL_VOL") {
      if (!history || history.observations !== 61 || !finite(history.hv20) || history.hv20 < 0
        || !finite(history.hv60) || history.hv60 < 0 || leg.delta_basis !== "HISTORICAL_VOL"
        || (Object.hasOwn(leg, "iv") && leg.iv !== null)) return false;
      const bidIv = inverse(bid, spot, strike, years, put);
      const askIv = inverse(ask, spot, strike, years, put);
      if (bidIv === null || askIv === null || bidIv > askIv) return false;
      sigma = Math.min(askIv, Math.max(history.hv20, history.hv60, bidIv));
      if (!positive(sigma)) return false;
      const quote=priceDelta(spot,strike,years,sigma,put);
      exact=quote?.[1] ?? null;
      if (Object.hasOwn(leg,"limit_price")) {
        if (!quote || !finite(leg.limit_price)) return false;
        const mid=(bid+ask)/2, price=Math.min(mid,Math.max(bid,quote[0]));
        const rounded=buy ? Math.ceil(price*100-1e-9)/100 : Math.floor(price*100+1e-9)/100;
        if (Math.abs(leg.limit_price-Math.min(mid,Math.max(bid,rounded)))>1e-8) return false;
      }
    } else if (basis === "QUOTE_IMPLIED") {
      if ((deltaUncertainty(leg, spot, dte, put) ?? 0) > DELTA_UNCERTAINTY_TRIGGER
        || !["QUOTE_IMPLIED", "QUOTED_IV", "QUOTED"].includes(String(leg.delta_basis))) return false;
      if (leg.delta_basis === "QUOTED") {
        if (Object.hasOwn(leg, "iv") && leg.iv !== null) return false;
        exact = leg.delta;
      } else if (leg.delta_basis === "QUOTED_IV" && !Object.hasOwn(leg, "iv")) {
        // The six-key put/collar legs seal only provider-IV-derived Delta,
        // exactly as the Stage1C format did. No invented opposite quote.
        exact = leg.delta;
      } else {
        if (leg.delta_basis === "QUOTED_IV") {
          if (!positive(leg.iv)) return false;
          sigma = leg.iv;
        } else {
          sigma = inverse(bid / 2 + ask / 2, spot, strike, years, put);
          if (!positive(sigma)) return false;
          if (Object.hasOwn(leg, "iv") && (!finite(leg.iv)
            || Math.abs(leg.iv - roundedIv(sigma)) > 0.00005 + 1e-12)) return false;
        }
        exact = priceDelta(spot, strike, years, sigma, put)?.[1] ?? null;
      }
    } else return false;
    if (exact === null || Math.abs(shown - exact) > 0.0005 + 1e-12) return false;
    if (band && (!finite(band[0]) || !finite(band[1]) || band[0] < 0 || band[1] > 1
      || band[0] > band[1] || exact < band[0] - 1e-12 || exact > band[1] + 1e-12)) return false;
    return true;
  } catch {
    return false;
  }
}
