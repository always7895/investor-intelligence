// Covered-call suggestions: strict validation mirror and LINE rendering. Synthetic values only.
import { describe, expect, it } from "vitest";
import { buildCoveredCallMessages, validateCoveredCallCycle } from "../src/v213/covered-call";

function suggestion(role: "HIGH_STRIKE" | "BALANCED", strike: number, bid: number, ask: number, limit: number, spot = 225, dte = 27) {
  return { role, strike, bid, ask, mid: (bid + ask) / 2, limit_price: limit, premium_per_contract: limit * 100,
    period_yield: limit / spot, annualized_yield: limit / spot * 365 / dte, upside_to_strike: strike / spot - 1,
    delta: role === "HIGH_STRIKE" ? 0.17 : 0.33, iv: 0.45, oi: 1200, volume: 300, spread_pct: (ask - bid) / ((bid + ask) / 2) };
}

function cycle(overrides: Record<string, unknown> = {}) {
  return { ticker: "NVDA", strategy: "COVERED_CALL", expiry: "2026-10-23", dte: 27, spot: 225, currency: "USD", multiplier: 100,
    quote_basis: "delayed", timestamp: "2026-09-26T00:00:00Z", source: "Yahoo Finance option chain (unofficial, delayed)",
    provenance: "https://finance.yahoo.com/quote/NVDA/options", rights_status: "unadmitted_third_party",
    suggestions: [suggestion("HIGH_STRIKE", 245, 1.5, 1.55, 1.52), suggestion("BALANCED", 235, 3.65, 3.8, 3.72)], ...overrides };
}

describe("covered-call suggestions", () => {
  it("accepts a consistent cycle and refuses inconsistent ones", () => {
    expect(validateCoveredCallCycle(cycle())).not.toBeNull();
    const aboveMid = cycle(); (aboveMid.suggestions[0] as any).limit_price = 1.6; expect(validateCoveredCallCycle(aboveMid)).toBeNull();
    const inTheMoney = cycle({ suggestions: [suggestion("HIGH_STRIKE", 220, 6, 6.2, 6.1)] }); expect(validateCoveredCallCycle(inTheMoney)).toBeNull();
    const reversed = cycle({ suggestions: [suggestion("HIGH_STRIKE", 235, 3.65, 3.8, 3.72), suggestion("BALANCED", 245, 1.5, 1.55, 1.52)] });
    expect(validateCoveredCallCycle(reversed)).toBeNull();
    const badYield = cycle(); (badYield.suggestions[1] as any).annualized_yield = 0.9; expect(validateCoveredCallCycle(badYield)).toBeNull();
    expect(validateCoveredCallCycle(cycle({ currency: "EUR" }))).toBeNull();
  });

  it("renders two sell suggestions with limit, premium, yield and assignment reference, no payoff placeholders", () => {
    const valid = validateCoveredCallCycle(cycle())!;
    const flex = JSON.stringify(buildCoveredCallMessages(valid, "每月期權", "flex"));
    expect(flex).toContain("建議一：高履約價（不易被賣掉）");
    expect(flex).toContain("建議二：平衡型（收較多權利金）");
    expect(flex).toContain("$245.00");
    expect(flex).toContain("$152.00");
    expect(flex).toContain("Delta 0.17");
    expect(flex).not.toContain("UNAVAILABLE");
    const text = (buildCoveredCallMessages(valid, "每月期權", "text") as { text: string }[])[0]!.text;
    expect(text).toContain("建議賣出限價 $1.52");
    expect(text).toContain("本服務不下單");
  });

  it("labels a delta implied by the quote itself and refuses unknown bases or volatilities", () => {
    const implied = cycle({ currency: "SEK", spot: 32.78, suggestions: [{ ...suggestion("HIGH_STRIKE", 62, 0.2, 0.35, 0.27, 32.78, 20),
      delta: 0.061, delta_basis: "QUOTE_IMPLIED", iv: 1.5658 }], dte: 20 });
    const valid = validateCoveredCallCycle(implied)!;
    expect(valid).not.toBeNull();
    const flex = JSON.stringify(buildCoveredCallMessages(valid, "每月期權", "flex"));
    expect(flex).toContain("Delta 0.06（約 6%，模型值，波動率由買賣報價反推 157%）");
    const text = (buildCoveredCallMessages(valid, "每月期權", "text") as { text: string }[])[0]!.text;
    expect(text).toContain("Delta 0.06（由報價反推）");
    const unknown = structuredClone(implied); (unknown.suggestions as any)[0].delta_basis = "GUESSED";
    expect(validateCoveredCallCycle(unknown)).toBeNull();
    const badVol = structuredClone(implied); (badVol.suggestions as any)[0].iv = -1;
    expect(validateCoveredCallCycle(badVol)).toBeNull();
    const noDelta = cycle(); (noDelta.suggestions[1] as any).delta = undefined;
    expect(JSON.stringify(buildCoveredCallMessages(validateCoveredCallCycle(noDelta)!, "每月期權", "flex"))).toContain("報價不足以推算 Delta");
  });
});
