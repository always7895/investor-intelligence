// Covered-call suggestions: strict validation mirror and LINE rendering. Synthetic values only.
import { describe, expect, it, beforeEach, vi } from "vitest";
import { buildCoveredCallMessages, validateCoveredCallCycle } from "../src/v213/covered-call";

import { admitSyntheticTickers, resetAdmissionToReal } from "./synthetic-option-admission";
import { OptionRightsNotAdmittedError } from "../src/v213/public-options-admission";

// TESTFIX1 / OPTIONS_TEST_POLICY1: per-test sealed-ticker admission only; rights NONE remains the default.
// Real no-mock caller coverage: v213-public-options-admission-regression.test.ts.
vi.mock("../src/v213/public-options-admission", async importOriginal => {
  const real = await importOriginal<typeof import("../src/v213/public-options-admission")>();
  return { ...real, admitPublicOption: vi.fn(real.admitPublicOption) };
});
beforeEach(() => { resetAdmissionToReal(); });


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
  it("TESTFIX1 rights NONE: denies the covered-call renderer without opt-in", () => {
    const valid = validateCoveredCallCycle(cycle())!;
    for (const presentation of ["text", "flex"] as const) {
      let rendered: unknown;
      expect(() => { rendered = buildCoveredCallMessages(valid, "每月期權", presentation); }).toThrow(OptionRightsNotAdmittedError);
      expect(JSON.stringify(rendered) ?? "").not.toContain("$245.00");
    }
  });

  it("accepts a consistent cycle and refuses inconsistent ones", () => {
    expect(validateCoveredCallCycle(cycle())).not.toBeNull();
    const aboveMid = cycle(); (aboveMid.suggestions[0] as any).limit_price = 1.6; expect(validateCoveredCallCycle(aboveMid)).toBeNull();
    const inTheMoney = cycle({ suggestions: [suggestion("HIGH_STRIKE", 220, 6, 6.2, 6.1)] }); expect(validateCoveredCallCycle(inTheMoney)).toBeNull();
    const reversed = cycle({ suggestions: [suggestion("HIGH_STRIKE", 235, 3.65, 3.8, 3.72), suggestion("BALANCED", 245, 1.5, 1.55, 1.52)] });
    expect(validateCoveredCallCycle(reversed)).toBeNull();
    const badYield = cycle(); (badYield.suggestions[1] as any).annualized_yield = 0.9; expect(validateCoveredCallCycle(badYield)).toBeNull();
    expect(validateCoveredCallCycle(cycle({ currency: "EUR" }))).toBeNull();
    for (const delta of [null, undefined, 0.2000000005, 0.2001, 0.9, -0.01, Number.POSITIVE_INFINITY, Number.NaN]) {  // the high strike always needs delta <= 0.20
      const uncapped = cycle(); (uncapped.suggestions[0] as any).delta = delta;
      expect(validateCoveredCallCycle(uncapped)).toBeNull();
    }
    const atLimit = cycle(); (atLimit.suggestions[0] as any).delta = 0.2;
    expect(validateCoveredCallCycle(atLimit)).not.toBeNull();
  });

  it("renders two sell suggestions with limit, premium, yield and assignment reference, no payoff placeholders", () => {
    admitSyntheticTickers("NVDA"); // Explicit quote subjects for this test only.
    const valid = validateCoveredCallCycle(cycle())!;
    // V25-FIX3 wraps required quote figures at line boundaries; preserve visible-value assertions across those breaks.
    const flex = JSON.stringify(buildCoveredCallMessages(valid, "每月期權", "flex")).replaceAll("\\n", " ");
    expect(flex).toContain("建議一：高履約價（不易被賣掉）");
    expect(flex).toContain("建議二：平衡型（收較多權利金）");
    expect(flex).toContain("$245.00");
    expect(flex).toContain("$152.00");
    expect(flex).toContain("Delta 0.17");
    expect(flex).toContain("https://finance.yahoo.com/quote/NVDA/options");
    expect(flex).toContain("資料來源與說明");
    expect(flex).toContain("Delta 不高於 0.20");
    expect(flex).toContain("不設年化收益下限");
    expect(flex).not.toContain("年化權利金至少");
    // V25-FIX3 measures the complete formula independent of Flex line wrapping.
    expect(flex.replace(/\s/g, "")).toContain("期間收益＝限價÷現價；年化收益＝期間收益×365÷DTE");
    expect(flex).toContain("僅供指派機率參考");
    // V25 master: the Delta basis and the yield formulas are stated once per bubble, not once per tier.
    expect(flex.split("僅供指派機率參考").length - 1).toBe(1);
    expect(flex.replace(/\s/g, "").split("年化收益＝期間收益×365÷DTE").length - 1).toBe(1);
    // V25-FIX3 asserts the action embedded in the returned Flex message reaches the real text command.
    expect(flex).toContain("NVDA 每月期權 文字");
    expect(flex).not.toContain("UNAVAILABLE");
    const text = (buildCoveredCallMessages(valid, "每月期權", "text") as { text: string }[])[0]!.text;
    // V25-FIX3 verifies optional liquidity detail through the existing text edition.
    expect(text).toContain("流動性：OI");
    expect(text).toContain("建議賣出限價 $1.52");
    expect(text).toContain("本服務不下單");
  });

  it("labels a delta implied by the quote itself and refuses unknown bases or volatilities", () => {
    admitSyntheticTickers("NVDA"); // Explicit quote subjects for this test only.
    const implied = cycle({ currency: "SEK", spot: 32.78, suggestions: [{ ...suggestion("HIGH_STRIKE", 62, 0.2, 0.35, 0.27, 32.78, 20),
      delta: 0.061, delta_basis: "QUOTE_IMPLIED", iv: 1.5658 }], dte: 20 });
    const valid = validateCoveredCallCycle(implied)!;
    expect(valid).not.toBeNull();
    const flex = JSON.stringify(buildCoveredCallMessages(valid, "每月期權", "flex")).replaceAll("\\n", " ");
    // V25 keeps the sealed value and its derivation basis beside the figure in Flex.
    expect(flex).toContain("Delta 0.06");
    expect(flex).toContain("模型值，波動率由買賣報價反推 157%");
    const text = (buildCoveredCallMessages(valid, "每月期權", "text") as { text: string }[])[0]!.text;
    expect(text).toContain("Delta 0.06（模型值，波動率由買賣報價反推 157%）");
    const unknown = structuredClone(implied); (unknown.suggestions as any)[0].delta_basis = "GUESSED";
    expect(validateCoveredCallCycle(unknown)).toBeNull();
    const badVol = structuredClone(implied); (badVol.suggestions as any)[0].iv = -1;
    expect(validateCoveredCallCycle(badVol)).toBeNull();
    const noDelta = cycle(); (noDelta.suggestions[1] as any).delta = undefined;
    // V25-FIX3 wraps unavailable deltas without dropping their status.
    expect(JSON.stringify(buildCoveredCallMessages(validateCoveredCallCycle(noDelta)!, "每月期權", "flex")).replaceAll("\\n", " ")).toContain("Delta 未提供");
  });
});

describe("source-page option date provenance", () => {
  const fetched = "2026-11-09T05:50:30Z";
  const now = Date.parse(fetched);
  const sourceCycle = (overrides: Record<string, unknown> = {}): Record<string, unknown> => cycle({
    expiry: "2026-11-20", dte: 11, spot: 186.64, timestamp: fetched, asof_date: "2026-11-09",
    monthly_rule: "THIRD_FRIDAY", source_quote_date: "2026-11-06",
    source: "Nasdaq US option chain (public quote page API, delayed; Yahoo fallback)",
    provenance: "https://www.nasdaq.com/market-activity/stocks/nvda/option-chain",
    suggestions: [suggestion("HIGH_STRIKE", 220, 0.05, 0.10, 0.07, 186.64, 11)], ...overrides,
  });

  it("keeps NVDA 186.64, the November 6 source day and November 9 acquisition separate in Text and Flex", () => {
    admitSyntheticTickers("NVDA");
    const valid = validateCoveredCallCycle(sourceCycle(), now, fetched, "monthly");
    expect(valid).not.toBeNull();
    expect(valid?.source_quote_date).toBe("2026-11-06");
    expect(valid?.timestamp).toBe(fetched);
    expect(valid?.asof_date).toBe("2026-11-09");
    for (const style of ["text", "flex"] as const) {
      const rendered = JSON.stringify(buildCoveredCallMessages(valid!, "每月期權", style));
      expect(rendered).toContain("$186.64");
      expect(rendered).toContain("來源頁報價觀察日期 2026-11-06");
      expect(rendered).toContain("非本卡試算現價之觀察日期");
      expect(rendered).toContain("lastTrade 指正股");
      expect(rendered).toContain("不代表期權腿成交時間");
      expect(rendered).toContain("各期權腿的觀察時間未提供");
      expect(rendered).toContain("擷取時間");
      expect(rendered).not.toContain("2026-11-06T00:00");
    }
  });

  it("shows the same source date and unknown leg timing on observation-only Text and Flex", () => {
    admitSyntheticTickers("NVDA");
    const valid = validateCoveredCallCycle(sourceCycle({
      suggestions: [],
      quote_observation: { kind: "NO_TWO_SIDED", strike: 220, bid: null, ask: null, last: 0.08,
        annualized_yield: 0.08 / 186.64 * 365 / 11, oi: 100, volume: 10 },
    }), now, fetched, "monthly");
    expect(valid).not.toBeNull();
    expect(valid?.timestamp).toBe(fetched);
    for (const style of ["text", "flex"] as const) {
      const rendered = JSON.stringify(buildCoveredCallMessages(valid!, "每月期權", style));
      expect(rendered).toContain("來源頁報價觀察日期 2026-11-06");
      expect(rendered).toContain("各期權腿的觀察時間未提供");
      expect(rendered).toContain("不代表期權腿成交時間");
      expect(rendered).toContain("Last $0.08");
    }
  });

  it("rejects malformed, non-calendar, future and stale days without borrowing other clocks", () => {
    for (const source_quote_date of [null, undefined, false, 20261106, [], {}, "", "2026-11-6",
      "2026-02-30", "2026-02-29", "0000-11-06", "2026-11-06T00:00:00Z", "2026-11-10", "2026-11-04"]) {
      expect(validateCoveredCallCycle(sourceCycle({ source_quote_date }), now, fetched, "monthly")).toBeNull();
    }
    const inconsistent = sourceCycle({
      asof_date: "2026-11-08", dte: 12, source_quote_date: "2026-11-09",
      suggestions: [suggestion("HIGH_STRIKE", 220, 0.05, 0.10, 0.07, 186.64, 12)],
    });
    expect(validateCoveredCallCycle(inconsistent, now, fetched, "monthly")).toBeNull();
    expect(validateCoveredCallCycle(sourceCycle(), now + 6 * 3600_000 + 1, fetched, "monthly")).toBeNull();
  });

  it("keeps an absent legacy date unknown rather than deriving it from capture or expiry-rule date", () => {
    admitSyntheticTickers("NVDA");
    const { source_quote_date: _omitted, ...legacy } = sourceCycle();
    const valid = validateCoveredCallCycle(legacy, now, fetched, "monthly");
    expect(valid).not.toBeNull();
    expect(valid).not.toHaveProperty("source_quote_date");
    for (const style of ["text", "flex"] as const) {
      const rendered = JSON.stringify(buildCoveredCallMessages(valid!, "每月期權", style));
      expect(rendered).toContain("來源頁報價觀察日期 未提供");
      expect(rendered).not.toContain("來源頁報價觀察日期 2026-11-09");
    }
  });

  it("carries the original source day, not the current exchange date, and still rejects future-to-capture dates", () => {
    admitSyntheticTickers("NVDA");
    const captured = "2026-11-06T15:00:00Z";
    const carryCycle = sourceCycle({
      timestamp: captured, asof_date: "2026-11-06", dte: 14, source_quote_date: "2026-11-05",
      source: "Yahoo Finance option chain (unofficial, delayed)",
      provenance: "https://finance.yahoo.com/quote/NVDA/options", quote_basis: "previous_session_last",
      suggestions: [suggestion("HIGH_STRIKE", 220, 0.05, 0.10, 0.07, 186.64, 14)],
    });
    const valid = validateCoveredCallCycle(carryCycle, now, fetched, "monthly", { allowPreviousSession: true });
    expect(valid).not.toBeNull();
    expect(valid?.source_quote_date).toBe("2026-11-05");
    expect(valid?.timestamp).toBe(captured);
    for (const style of ["text", "flex"] as const) {
      const rendered = JSON.stringify(buildCoveredCallMessages(valid!, "每月期權", style));
      expect(rendered).toContain("來源頁報價觀察日期 2026-11-05");
      expect(rendered).toContain("前一交易時段擷取時間");
      expect(rendered).not.toContain("來源頁報價觀察日期 2026-11-09");
    }
    expect(validateCoveredCallCycle({ ...carryCycle, source_quote_date: "2026-11-09" },
      now, fetched, "monthly", { allowPreviousSession: true })).toBeNull();
  });
});
