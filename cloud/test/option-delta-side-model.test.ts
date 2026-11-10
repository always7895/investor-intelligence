import { describe, expect, it } from "vitest";
import {
  parseSideDeltaModel, validSideCycleDeltaModel, sideModelLegConsistent,
} from "../src/v213/option-delta-side-model";
import type { HistoricalVolatility } from "../src/v213/historical-volatility";

// Independent analytical Black-Scholes reference (d1=0, d2=-1 at sigma=1,T=1).
const spot = 100;
const strike = 100 * Math.exp(0.54);
const sigma = 1;
const price = spot * .5 - strike * Math.exp(-.04) * 0.15865525393145705;
const history = {
  ticker: "UNIT", currency: "USD", hv20: sigma, hv60: .8, observations: 61,
  start_date_20: "2026-09-24", start_date_60: "2026-07-28",
  asof_date: "2026-10-22", source_url: "https://query1.finance.yahoo.com/v8/finance/chart/UNIT?interval=1d&range=6mo",
  source_sha256: "a".repeat(64), price_basis: "PROVIDER_ADJUSTED_CLOSE",
} as HistoricalVolatility;

describe("Stage1E sealed per-side model", () => {
  it("requires an exact compact quote/HV side and rejects modified encodings", () => {
    expect(parseSideDeltaModel("E1|H,3,110.5|Q,0,-")).toEqual({
      calls: ["HISTORICAL_VOL", 3, 110.5], puts: ["QUOTE_IMPLIED", 0, null],
    });
    for (const text of [
      "E1|H,0,110.5|Q,0,-", "E1|H,-1,-|Q,0,-", "E1|X,0,-|Q,0,-",
      "E1|H,0,-|Q,0,-|extra", "E1|H,999999,-|Q,0,-", "E1|H,0,-|Q,0,1",
      "E1|H,0,-|Q,0,-?token=value",
    ]) expect(validSideCycleDeltaModel(text, history), text).toBe(false);
  });

  it("verifies each wide leg with the same verified historical windows and its own actual quote IV bounds", () => {
    const model = "E1|H,1,-|Q,0,-";
    const leg = {
      strike, bid: price * .7, ask: price * 1.3,
      delta: .5, delta_basis: "HISTORICAL_VOL", iv: null,
    };
    expect(validSideCycleDeltaModel(model, history)).toBe(true);
    expect(sideModelLegConsistent(leg, model, history, spot, 365, false)).toBe(true);
    expect(sideModelLegConsistent({ ...leg, delta: .51 }, model, history, spot, 365, false)).toBe(false);
    expect(sideModelLegConsistent({ ...leg, iv: 1 }, model, history, spot, 365, false)).toBe(false);
    expect(sideModelLegConsistent({ ...leg, ask: leg.bid * .95 }, model, history, spot, 365, false)).toBe(false);
    expect(sideModelLegConsistent(leg, model, undefined, spot, 365, false)).toBe(false);
  });

  it("keeps independently quoted tight legs when the other side requires HV", () => {
    const model = "E1|H,0,-|Q,1,-";
    const put = { strike: 90, bid: .5, ask: .54, delta: .15, delta_basis: "QUOTED" };
    expect(sideModelLegConsistent(put, model, history, spot, 28, true, [.10, .20])).toBe(true);
    expect(sideModelLegConsistent({ ...put, ask: 0 }, model, history, spot, 28, true)).toBe(false);
    expect(sideModelLegConsistent({ ...put, delta_basis: "HISTORICAL_VOL" }, model, history, spot, 28, true)).toBe(false);
    expect(sideModelLegConsistent(put, model, history, spot, 28, true, [.20, .30])).toBe(false);
  });

  it("does not promote a wide leg into a narrow source-Delta strategy", () => {
    const model = "E1|Q,0,-|Q,0,-";
    const wide = { strike: 115, bid: .5, ask: 2.5, delta: .15, delta_basis: "QUOTED" };
    expect(sideModelLegConsistent(wide, model, history, spot, 28, false)).toBe(false);
    expect(sideModelLegConsistent({ ...wide, ask: .54 }, model, history, spot, 28, false)).toBe(true);
  });
});
