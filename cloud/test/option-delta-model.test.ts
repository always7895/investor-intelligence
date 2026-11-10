// Legacy dictionaries are compatibility inputs only; verify the active side-model boundary.
import { describe, expect, it } from "vitest";
import type { DeltaModel } from "../src/v213/covered-call";
import { isSideCycleDeltaModel, parseSideDeltaModel, validSideCycleDeltaModel } from "../src/v213/option-delta-side-model";

describe("retired common-sigma wire", () => {
  it.each(["QUOTE_IMPLIED", "HISTORICAL_VOL"] as const)("refuses legacy %s dictionaries at the active verifier", basis => {
    const legacy: DeltaModel = { basis, sigma: 0.4, iv_bid: 0.2, iv_ask: 0.8 };
    expect(isSideCycleDeltaModel(legacy)).toBe(false);
    expect(parseSideDeltaModel(legacy)).toBeNull();
    expect(validSideCycleDeltaModel(legacy, undefined)).toBe(false);
  });
  it("still admits independent quote/HV sides, not a shared sigma", () => {
    const wire = "E1|H,2,105|Q,1,95";
    expect(isSideCycleDeltaModel(wire)).toBe(true);
    expect(validSideCycleDeltaModel(wire, undefined)).toBe(true);
    expect(parseSideDeltaModel(wire)).toEqual({ calls: ["HISTORICAL_VOL", 2, 105], puts: ["QUOTE_IMPLIED", 1, 95] });
  });
});
