// Analytic offline Black-Scholes references; no live quotes or IV inversion.
import { describe, expect, it } from "vitest";
import type { HistoricalVolatility } from "../src/v213/historical-volatility";
import { modelLegConsistent, validDeltaModel, type DeltaModel } from "../src/v213/option-delta-model";

const HISTORY: HistoricalVolatility = {
  ticker: "NVDA", currency: "USD", hv20: 0.42, hv60: 0.38, observations: 61,
  start_date_20: "2026-10-09", start_date_60: "2026-08-14", asof_date: "2026-11-06",
  source_url: "https://query1.finance.yahoo.com/v8/finance/chart/NVDA?interval=1d&range=6mo",
  source_sha256: "a".repeat(64), price_basis: "PROVIDER_ADJUSTED_CLOSE",
};
const QUOTE: DeltaModel = { basis: "QUOTE_IMPLIED", sigma: 1, iv_bid: 0.9, iv_ask: 1.1 };
const HISTORICAL: DeltaModel = { basis: "HISTORICAL_VOL", sigma: 1, iv_bid: 0.9, iv_ask: 1.1 };
const SPOT = 100;
const YEARS = 365;
// Setting K=S*exp(.04+.5-d1) gives exactly the stated d1 at sigma=1, T=1.
const REFERENCES = [
  { d1: -1, cdf1: 0.15865525393145705, cdf2: 0.02275013194817921 },
  { d1: 0, cdf1: 0.5, cdf2: 0.15865525393145705 },
  { d1: 1, cdf1: 0.8413447460685429, cdf2: 0.5 },
  { d1: 3, cdf1: 0.9986501019683699, cdf2: 0.9772498680518208 },
  { d1: 7, cdf1: 0.9999999999987201, cdf2: 0.9999999990134123 },
];
function referenceLeg(reference = REFERENCES[1]!, put = false, wide = false): Record<string, unknown> {
  const strike = SPOT * Math.exp(0.54 - reference.d1);
  const discountedStrike = strike * Math.exp(-0.04);
  const delta = put ? 1 - reference.cdf1 : reference.cdf1;
  const price = put
    ? discountedStrike * (1 - reference.cdf2) - SPOT * delta
    : SPOT * delta - discountedStrike * reference.cdf2;
  return {
    strike, bid: price * (wide ? 0.7 : 0.95), ask: price * (wide ? 1.3 : 1.05),
    delta: Number(delta.toFixed(3)), delta_basis: wide ? "HISTORICAL_VOL" : "QUOTE_IMPLIED",
  };
}

describe("sealed common delta model", () => {
  it("admits a common quote interval midpoint without historical evidence", () => {
    expect(validDeltaModel(QUOTE, undefined)).toBe(true);
    expect(validDeltaModel({ ...QUOTE, sigma: 0.2, iv_bid: 0, iv_ask: 0.4 }, undefined)).toBe(true);
    expect(validDeltaModel({ ...QUOTE, sigma: 6, iv_bid: 5, iv_ask: 7 }, undefined)).toBe(true);
    expect(validDeltaModel({ ...QUOTE, sigma: 1e308, iv_bid: 1e308, iv_ask: 1e308 }, undefined)).toBe(true);
  });

  it.each([
    { hv20: 0.42, hv60: 0.38, low: 0.2, high: 0.8, sigma: 0.42 },
    { hv20: 0.38, hv60: 0.42, low: 0.2, high: 0.8, sigma: 0.42 },
    { hv20: 0.2, hv60: 0.3, low: 0.4, high: 0.8, sigma: 0.4 },
    { hv20: 0.9, hv60: 0.3, low: 0.2, high: 0.8, sigma: 0.8 },
    { hv20: 0, hv60: 0, low: 0.2, high: 0.8, sigma: 0.2 },
  ])("uses both windows and clamps to the quote interval: %s", ({ hv20, hv60, low, high, sigma }) => {
    const model: DeltaModel = { basis: "HISTORICAL_VOL", sigma, iv_bid: low, iv_ask: high };
    expect(validDeltaModel(model, { ...HISTORY, hv20, hv60 })).toBe(true);
    expect(validDeltaModel({ ...model, sigma: sigma + 0.001 }, { ...HISTORY, hv20, hv60 })).toBe(false);
  });

  it("refuses missing historical evidence or nonfinite historical windows", () => {
    expect(validDeltaModel(HISTORICAL, undefined)).toBe(false);
    expect(validDeltaModel(HISTORICAL, { ...HISTORY, hv20: NaN })).toBe(false);
    expect(validDeltaModel(HISTORICAL, { ...HISTORY, hv60: Infinity })).toBe(false);
    expect(validDeltaModel(HISTORICAL, { ...HISTORY, hv60: -0.1 })).toBe(false);
  });

  it.each<[string, unknown]>([
    ["basis", "QUOTED"], ["basis", "QUOTED_IV"], ["basis", "HISTORICAL_VOL"], ["basis", true],
    ["sigma", 0], ["sigma", -1], ["sigma", NaN], ["sigma", Infinity], ["sigma", true],
    ["sigma", "1"], ["sigma", 1.01], ["iv_bid", -1], ["iv_bid", 1.2], ["iv_bid", NaN],
    ["iv_bid", true], ["iv_ask", 0], ["iv_ask", 0.8], ["iv_ask", Infinity], ["iv_ask", false],
  ])("rejects invalid %s=%s", (key, value) => {
    expect(validDeltaModel({ ...QUOTE, [key]: value }, undefined)).toBe(false);
  });

  it("requires exactly the new four-key model and refuses empty IV intersections", () => {
    for (const value of [undefined, null, [], true, 1, "model", {}]) {
      expect(validDeltaModel(value, HISTORY)).toBe(false);
    }
    for (const key of Object.keys(QUOTE)) {
      expect(validDeltaModel(Object.fromEntries(Object.entries(QUOTE).filter(([name]) => name !== key)), undefined)).toBe(false);
    }
    expect(validDeltaModel({ ...QUOTE, extra: true }, undefined)).toBe(false);
    expect(validDeltaModel({ ...QUOTE, [Symbol("extra")]: true }, undefined)).toBe(false);
    expect(validDeltaModel(Object.create(QUOTE), undefined)).toBe(false);
    expect(validDeltaModel({ ...QUOTE, iv_bid: 1.1, iv_ask: 0.9 }, undefined)).toBe(false);
  });
});

describe("per-leg common sigma consistency", () => {
  it.each(REFERENCES)("matches analytic call price and full-precision delta at d1=$d1", reference => {
    expect(modelLegConsistent(referenceLeg(reference), QUOTE, SPOT, YEARS, false, [reference.cdf1, reference.cdf1])).toBe(true);
  });

  it.each(REFERENCES.slice(0, 4))("matches analytic absolute put delta at d1=$d1", reference => {
    const delta = 1 - reference.cdf1;
    expect(modelLegConsistent(referenceLeg(reference, true), QUOTE, SPOT, YEARS, true, [delta, delta])).toBe(true);
  });

  it("keeps one common sigma and monotone deltas across a coherent call cohort", () => {
    const farther = referenceLeg(REFERENCES[0]);
    const nearer = referenceLeg(REFERENCES[1]);
    expect([farther, nearer].every(leg => modelLegConsistent(leg, QUOTE, SPOT, YEARS, false))).toBe(true);
    expect(farther.strike).toBeGreaterThan(Number(nearer.strike));
    expect(farther.delta).toBeLessThan(Number(nearer.delta));
    expect(modelLegConsistent({ ...farther, delta: nearer.delta }, QUOTE, SPOT, YEARS, false)).toBe(false);
  });

  it("accepts wide legs only with a coherent historical model and null CC IV", () => {
    const history = { ...HISTORY, hv20: 1, hv60: 0.8 };
    expect(validDeltaModel(HISTORICAL, history)).toBe(true);
    expect(modelLegConsistent(referenceLeg(undefined, false, true), HISTORICAL, SPOT, YEARS, false)).toBe(true);
    expect(modelLegConsistent({ ...referenceLeg(undefined, false, true), iv: null }, HISTORICAL, SPOT, YEARS, false)).toBe(true);
    expect(modelLegConsistent({ ...referenceLeg(undefined, false, true), iv: 1 }, HISTORICAL, SPOT, YEARS, false)).toBe(false);
    expect(modelLegConsistent({ ...referenceLeg(undefined, false, true), iv: undefined }, HISTORICAL, SPOT, YEARS, false)).toBe(false);
  });

  it("refuses either common basis for a mixed tight/wide cohort", () => {
    const legs = [referenceLeg(), referenceLeg(undefined, false, true)];
    for (const model of [QUOTE, HISTORICAL]) {
      expect(legs.every(leg => modelLegConsistent({ ...leg, delta_basis: model.basis }, model, SPOT, YEARS, false))).toBe(false);
    }
  });

  it("treats a spread of exactly 0.25 as tight and strictly larger as wide", () => {
    // d1=0 at sigma=.2; call price is between 6 and 7.714285..., with delta=.5.
    const spot = 100 * Math.exp(-0.06);
    const model: DeltaModel = { basis: "QUOTE_IMPLIED", sigma: 0.2, iv_bid: 0.1, iv_ask: 0.3 };
    const leg = { strike: 100, bid: 7, ask: 9, delta: 0.5, delta_basis: "QUOTE_IMPLIED" };
    // Use d1=0 sigma=1 reference, scaling its spot and strike to give a price near 8.
    const reference = REFERENCES[1]!;
    const strike = SPOT * Math.exp(0.54);
    const price = SPOT / 2 - strike * Math.exp(-0.04) * reference.cdf2;
    const scale = 8 / price;
    const boundary = { ...leg, strike: strike * scale };
    expect(modelLegConsistent(boundary, QUOTE, SPOT * scale, YEARS, false)).toBe(true);
    expect(modelLegConsistent({ ...boundary, ask: 9 + 1e-8 }, QUOTE, SPOT * scale, YEARS, false)).toBe(false);
    expect(modelLegConsistent({ ...boundary, ask: 9 + 1e-8, delta_basis: "HISTORICAL_VOL" }, HISTORICAL, SPOT * scale, YEARS, false)).toBe(true);
    // Retain an independent sigma=.2 reference, not a manufactured model price.
    const callPrice = spot / 2 - 100 * Math.exp(-0.04) * 0.42074029056089696;
    expect(modelLegConsistent({ ...leg, bid: callPrice * 0.95, ask: callPrice * 1.05 }, model, spot, YEARS, false)).toBe(true);
  });

  it.each<[string, unknown]>([
    ["bid", null], ["ask", null], ["bid", 0], ["ask", 0], ["bid", true], ["ask", Infinity],
    ["strike", NaN], ["strike", 0], ["delta", true], ["delta", NaN], ["delta", -0.5],
    ["delta", 0.501], ["delta_basis", "QUOTED"], ["delta_basis", "HISTORICAL_VOL"],
  ])("refuses inconsistent leg %s=%s", (key, value) => {
    expect(modelLegConsistent({ ...referenceLeg(), [key]: value }, QUOTE, SPOT, YEARS, false)).toBe(false);
  });

  it("rejects crossed quotes and checks the raw price, not only the rounded delta", () => {
    expect(modelLegConsistent({ ...referenceLeg(), bid: 100, ask: 90 }, QUOTE, SPOT, YEARS, false)).toBe(false);
    expect(modelLegConsistent({ ...referenceLeg(), bid: 1, ask: 1.1 }, QUOTE, SPOT, YEARS, false)).toBe(false);
    expect(modelLegConsistent({ ...referenceLeg(), bid: 90, ask: 95 }, QUOTE, SPOT, YEARS, false)).toBe(false);
  });

  it("checks full-precision delta bands independently of displayed rounding", () => {
    const leg = referenceLeg(REFERENCES[0]);
    expect(modelLegConsistent(leg, QUOTE, SPOT, YEARS, false, [0.158, 0.159])).toBe(true);
    expect(modelLegConsistent(leg, QUOTE, SPOT, YEARS, false, [0.159, 0.2])).toBe(false);
    expect(modelLegConsistent(leg, QUOTE, SPOT, YEARS, false, [0.1, 0.1585])).toBe(false);
    expect(modelLegConsistent(leg, QUOTE, SPOT, YEARS, false, [0.2, 0.1])).toBe(false);
    expect(modelLegConsistent(leg, QUOTE, SPOT, YEARS, false, [NaN, 1])).toBe(false);
  });

  it("enforces displayed delta and CC IV rounding tolerances", () => {
    const leg = referenceLeg();
    expect(modelLegConsistent({ ...leg, delta: 0.5005, iv: 1 }, QUOTE, SPOT, YEARS, false)).toBe(true);
    expect(modelLegConsistent({ ...leg, delta: 0.500501 }, QUOTE, SPOT, YEARS, false)).toBe(false);
    expect(modelLegConsistent({ ...leg, iv: 1.00005 }, QUOTE, SPOT, YEARS, false)).toBe(true);
    expect(modelLegConsistent({ ...leg, iv: 1.000051 }, QUOTE, SPOT, YEARS, false)).toBe(false);
    expect(modelLegConsistent({ ...leg, iv: null }, QUOTE, SPOT, YEARS, false)).toBe(false);
    expect(modelLegConsistent({ ...leg, iv: true }, QUOTE, SPOT, YEARS, false)).toBe(false);
  });

  it("mirrors Python ties-to-even when rounding common sigma for CC IV", () => {
    const sigma = 0.03125;
    const spot = 100 * Math.exp(-0.04 - sigma * sigma / 2);
    const model: DeltaModel = { basis: "QUOTE_IMPLIED", sigma, iv_bid: sigma, iv_ask: sigma };
    const leg = { strike: 100, bid: 1, ask: 1.25, delta: 0.5, delta_basis: "QUOTE_IMPLIED", iv: 0.0312 };
    expect(modelLegConsistent(leg, model, spot, YEARS, false)).toBe(true);
    expect(modelLegConsistent({ ...leg, iv: 0.0313 }, model, spot, YEARS, false)).toBe(false);
  });

  it("uses at least one calendar day and the unchanged 4% rate", () => {
    const sigma = Math.sqrt(365);
    const spot = 100 * Math.exp(-0.04 / 365 - 0.5);
    const price = spot / 2 - 100 * Math.exp(-0.04 / 365) * 0.15865525393145705;
    const model: DeltaModel = { basis: "QUOTE_IMPLIED", sigma, iv_bid: sigma, iv_ask: sigma };
    const leg = { strike: 100, bid: price * 0.95, ask: price * 1.05, delta: 0.5, delta_basis: "QUOTE_IMPLIED" };
    for (const dte of [0, 1]) expect(modelLegConsistent(leg, model, spot, dte, false, [0.5, 0.5])).toBe(true);
    expect(modelLegConsistent(leg, model, spot, -1, false)).toBe(false);
    expect(modelLegConsistent(leg, model, spot, 2, false)).toBe(false);
    expect(modelLegConsistent(leg, model, spot, NaN, false)).toBe(false);
    expect(modelLegConsistent(leg, model, Infinity, 1, false)).toBe(false);
  });
});
