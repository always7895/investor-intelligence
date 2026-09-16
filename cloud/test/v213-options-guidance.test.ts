import { describe, expect, it } from "vitest";
import { assertLineMessages, type LineOutboundMessage } from "../src/line-messages";
import {
  CAVEAT_DISCLAIMER,
  CONSERVATIVE_DELTA_BAND,
  buildOptionsGuidanceFlexBubble,
  buildOptionsGuidanceText,
  buildPositionSizingFlexBubble,
  buildPositionSizingText,
  generateOptionsOrderGuidance,
  generatePositionSizingFramework,
  type GenerateOptionsOrderGuidanceParams,
} from "../src/v213/options-guidance";

const baseline: GenerateOptionsOrderGuidanceParams = {
  ticker: "nvda",
  strategy: "covered_call",
  underlyingPrice: 128.4,
  strike: 135,
  expiry: "2026-12-18",
  dte: 94,
  delta: 0.25,
  bid: 2.1,
  mid: 2.25,
  ask: 2.4,
  openInterest: 1200,
  volume: 350,
};

type FlexMsg = Extract<LineOutboundMessage, { type: "flex" }>;

function gd(overrides: Partial<GenerateOptionsOrderGuidanceParams> = {}) {
  return generateOptionsOrderGuidance({ ...baseline, ...overrides });
}

describe("Options order guidance (AGENTS.md authorization)", () => {
  describe("Delta conservative band targeting 0.20-0.30", () => {
    it("targets the conservative band for CC and CSP", () => {
      expect(CONSERVATIVE_DELTA_BAND).toEqual([0.2, 0.3]);
      expect(gd({ delta: 0.25 }).delta_assessment).toBe("TARGET_CONSERVATIVE_BAND");
      expect(gd({ strategy: "cash_secured_put", delta: 0.2 }).delta_assessment).toBe("TARGET_CONSERVATIVE_BAND");
      expect(gd({ strategy: "cash_secured_put", delta: 0.3 }).delta_assessment).toBe("TARGET_CONSERVATIVE_BAND");
    });
    it("flags too-aggressive (>0.30) and too-far-OTM (<0.20) strikes", () => {
      expect(gd({ delta: 0.31 }).delta_assessment).toBe("TOO_AGGRESSIVE");
      expect(gd({ delta: 0.45 }).delta_assessment).toBe("TOO_AGGRESSIVE");
      expect(gd({ delta: 0.199 }).delta_assessment).toBe("TOO_FAR_OTM");
      expect(gd({ delta: 0.1 }).delta_assessment).toBe("TOO_FAR_OTM");
    });
    it("reports UNAVAILABLE when delta is not provided", () => {
      const g = gd({ delta: null });
      expect(g.delta).toBeNull();
      expect(g.delta_assessment).toBe("UNAVAILABLE");
    });
  });

  describe("Limit reference band (selling at fair/mid, never market)", () => {
    it("recommends the mid price inside the quoted book with LIMIT order type", () => {
      const g = gd();
      expect(g.order_type).toBe("LIMIT");
      expect(g.limit_reference_band.lower).toBeCloseTo(2.1, 10);
      expect(g.limit_reference_band.upper).toBeCloseTo(2.4, 10);
      expect(g.limit_reference_band.recommended_limit).toBeCloseTo(2.25, 10);
      expect(g.bid).toBeCloseTo(2.1, 10);
      expect(g.mid).toBeCloseTo(2.25, 10);
      expect(g.ask).toBeCloseTo(2.4, 10);
    });
    it("never suggests a market order for either strategy", () => {
      expect(gd({ strategy: "cash_secured_put" }).order_type).toBe("LIMIT");
      expect(gd().caveat_disclaimer).toContain("NOT broker execution");
    });
  });

  describe("Annualized yield exactness (premium/strike x 365/dte x 100)", () => {
    it("computes exact annualized yield at dte 365", () => {
      const g = gd({ strike: 125, mid: 4.35, dte: 365 });
      expect(g.annualized_yield_pct).toBeCloseTo(3.48, 10);
      expect(g.annualized_yield_pct).toBeCloseTo((4.35 / 125) * (365 / 365) * 100, 12);
    });
    it("computes exact annualized yield at dte 30", () => {
      const g = gd({ strike: 125, mid: 4.35, dte: 30 });
      expect(g.annualized_yield_pct).toBeCloseTo(42.34, 9);
      expect(g.annualized_yield_pct).toBeCloseTo((4.35 / 125) * (365 / 30) * 100, 12);
    });
    it("scales monotonically with shorter dte", () => {
      const long = gd({ dte: 94 }).annualized_yield_pct!;
      const short = gd({ dte: 30 }).annualized_yield_pct!;
      expect(short).toBeGreaterThan(long);
    });
  });

  describe("Liquidity thresholds (OI >= 100, Volume >= 50, Spread <= 10% of mid)", () => {
    it("qualifies at all thresholds and at the 10% spread boundary", () => {
      expect(gd({ openInterest: 100, volume: 50, bid: 4.75, mid: 5.0, ask: 5.25 }).liquidity_status).toBe("QUALIFIED");
      expect(gd({ openInterest: 1000, volume: 5000, bid: 2.15, mid: 2.25, ask: 2.35 }).liquidity_status).toBe("QUALIFIED");
    });
    it("flags low open interest below 100", () => {
      expect(gd({ openInterest: 99 }).liquidity_status).toBe("LOW_OI");
      expect(gd({ openInterest: 0 }).liquidity_status).toBe("LOW_OI");
    });
    it("flags low volume below 50 when OI is sufficient", () => {
      expect(gd({ volume: 49 }).liquidity_status).toBe("LOW_VOLUME");
      expect(gd({ openInterest: 500, volume: 10 }).liquidity_status).toBe("LOW_VOLUME");
    });
    it("flags wide spreads above 10% of mid", () => {
      expect(gd({ openInterest: 500, volume: 200, bid: 4.14, mid: 4.5, ask: 4.87 }).liquidity_status).toBe("WIDE_SPREAD");
    });
  });

  describe("Input validation (fail closed)", () => {
    it("rejects non-positive strike, dte, quotes", () => {
      expect(() => gd({ strike: 0 })).toThrow("OPTIONS_GUIDANCE_INVALID_STRIKE");
      expect(() => gd({ dte: 0 })).toThrow("OPTIONS_GUIDANCE_INVALID_DTE");
      expect(() => gd({ bid: -1 })).toThrow("OPTIONS_GUIDANCE_INVALID_BID");
    });
    it("rejects non-integer dte and malformed expiry/ticker/strategy", () => {
      expect(() => gd({ dte: 1.5 })).toThrow("OPTIONS_GUIDANCE_INVALID_DTE");
      expect(() => gd({ expiry: "not-a-date" })).toThrow("OPTIONS_GUIDANCE_INVALID_EXPIRY");
      expect(() => gd({ ticker: "!!bad" })).toThrow("OPTIONS_GUIDANCE_INVALID_TICKER");
      expect(() => gd({ strategy: "naked_short" as never })).toThrow("OPTIONS_GUIDANCE_INVALID_STRATEGY");
      expect(() => gd({ delta: 1.4 })).toThrow("OPTIONS_GUIDANCE_INVALID_DELTA");
    });
    it("keeps underlying price nullable", () => {
      expect(gd({ underlyingPrice: null }).underlying_price).toBeNull();
      expect(gd().underlying_price).toBe(128.4);
    });
  });

  describe("Position sizing framework (Serenity-grounded)", () => {
    it("caps: core 12, chokepoint 4, speculative 2; 20% cash reserve floor", () => {
      const core = generatePositionSizingFramework("STEADY_CORE_COMPOUNDER");
      const choke = generatePositionSizingFramework("BOTTLENECK_CHOKEPOINT");
      const spec = generatePositionSizingFramework("SPECULATIVE_HIGH_DILUTION");
      expect(core.max_allocation_cap_pct).toBe(12);
      expect(choke.max_allocation_cap_pct).toBe(4);
      expect(spec.max_allocation_cap_pct).toBe(2);
      for (const s of [core, choke, spec]) {
        expect(s.cash_reserve_requirement_pct).toBe(20);
        expect(s.tranche_pacing).toContain("3-4 tranches");
        expect(s.tranche_pacing).toContain("6-18 months");
        expect(s.financing_risk_overlay).toContain("-50% cap penalty");
      }
    });
  });

  describe("Flex and Text builders", () => {
    it("emits a valid line flex with required fields and disclaimers", () => {
      const g = gd();
      const msg = buildOptionsGuidanceFlexBubble(g) as FlexMsg;
      assertLineMessages([msg]);
      expect(msg.type).toBe("flex");
      expect(msg.altText).toContain("NVDA");
      expect(JSON.stringify(msg.contents)).toContain("LIMIT");
      expect(JSON.stringify(msg.contents)).toContain("Annualized yield");
      expect(JSON.stringify(msg.contents)).toContain("NOT broker execution");
    });
    it("renders full text with band, yield, liquidity and disclaimer", () => {
      const g = gd({ delta: null, bid: 2.2, mid: 2.25, ask: 2.3 });
      const text = buildOptionsGuidanceText(g);
      expect(text).toContain("NVDA");
      expect(text).toContain("Covered Call");
      expect(text).toContain("LIMIT");
      expect(text).toContain(('Delta' as string) + '：' + ('N/A' as string));
      expect(text).toContain("Annualized yield 6.5%");
      expect(text).toContain("Qualified");
      expect(text).toContain(CAVEAT_DISCLAIMER);
    });
    it("sanSan-msth renders sizing messages with caps and pacing", () => {
      const s = generatePositionSizingFramework("BOTTLENECK_CHOKEPOINT");
      const text = buildPositionSizingText(s, "TSM");
      expect(text).toContain("TSM");
      expect(text).toContain("4%");
      expect(text).toContain("20%");
      expect(text).toContain("3-4 tranches");
      expect(text).toContain("-50% cap penalty");
      expect(text).toContain(CAVEAT_DISCLAIMER);
      const msg = buildPositionSizingFlexBubble(s, "TSM") as FlexMsg;
      assertLineMessages([msg]);
      expect(msg.type).toBe("flex");
      expect(msg.altText).toContain("4%");
      expect(JSON.stringify(msg.contents)).toContain("3-4 tranches");
    });
    it("never uses a market order anywhere in rendered output", () => {
      const body = JSON.stringify(buildOptionsGuidanceFlexBubble(gd({ strategy: "cash_secured_put" })));
      const txt = buildOptionsGuidanceText(gd({ strategy: "cash_secured_put" }));
      expect(body).not.toContain("MARKET");
      expect(body).toContain("LIMIT");
      expect(txt).toContain("LIMIT");
    });  });
});