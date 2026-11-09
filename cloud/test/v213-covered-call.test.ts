// Covered-call suggestions: strict validation mirror and LINE rendering. Synthetic values only.
import { describe, expect, it, beforeEach, vi } from "vitest";
import { buildCoveredCallMessages, validateCoveredCallCycle } from "../src/v213/covered-call";
import { syntheticCalls } from "./synthetic-coherent-options";

import { admitSyntheticTickers, resetAdmissionToReal } from "./synthetic-option-admission";
import { OptionRightsNotAdmittedError } from "../src/v213/public-options-admission";

// TESTFIX1 / OPTIONS_TEST_POLICY1: per-test sealed-ticker admission only; rights NONE remains the default.
// Real no-mock caller coverage: v213-public-options-admission-regression.test.ts.
vi.mock("../src/v213/public-options-admission", async importOriginal => {
  const real = await importOriginal<typeof import("../src/v213/public-options-admission")>();
  return { ...real, admitPublicOption: vi.fn(real.admitPublicOption) };
});
beforeEach(() => { resetAdmissionToReal(); });



function cycle(overrides: Record<string, unknown> = {}) {
  return { ticker: "NVDA", strategy: "COVERED_CALL", expiry: "2026-10-23", dte: 27, spot: 225, currency: "USD", multiplier: 100,
    quote_basis: "delayed", timestamp: "2026-09-26T00:00:00Z", source: "Yahoo Finance option chain (unofficial, delayed)",
    provenance: "https://finance.yahoo.com/quote/NVDA/options", rights_status: "unadmitted_third_party",
    ...syntheticCalls(225, 27, 245, 235), ...overrides };
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
    const aboveMid = cycle(); aboveMid.suggestions[0]!.limit_price = aboveMid.suggestions[0]!.ask!; expect(validateCoveredCallCycle(aboveMid)).toBeNull();
    const inTheMoney = cycle(); inTheMoney.suggestions[0]!.strike = 220; expect(validateCoveredCallCycle(inTheMoney)).toBeNull();
    const reversed = cycle(); reversed.suggestions.reverse();
    expect(validateCoveredCallCycle(reversed)).toBeNull();
    const badYield = cycle(); badYield.suggestions[1]!.annualized_yield = 0.9; expect(validateCoveredCallCycle(badYield)).toBeNull();
    expect(validateCoveredCallCycle(cycle({ currency: "EUR" }))).toBeNull();
    for (const delta of [null, undefined, 0.2000000005, 0.2001, 0.9, -0.01, Number.POSITIVE_INFINITY, Number.NaN]) {  // the high strike always needs delta <= 0.20
      const uncapped = cycle(); Object.assign(uncapped.suggestions[0]!, { delta });
      expect(validateCoveredCallCycle(uncapped)).toBeNull();
    }
    const legacy = cycle(); Reflect.deleteProperty(legacy, "delta_model");
    expect(validateCoveredCallCycle(legacy)).toBeNull();
  });

  it("renders two sell suggestions with limit, premium, yield and assignment reference, no payoff placeholders", () => {
    admitSyntheticTickers("NVDA"); // Explicit quote subjects for this test only.
    const valid = validateCoveredCallCycle(cycle())!;
    // V25-FIX3 wraps required quote figures at line boundaries; preserve visible-value assertions across those breaks.
    const flex = JSON.stringify(buildCoveredCallMessages(valid, "每月期權", "flex")).replaceAll("\\n", " ");
    expect(flex).toContain("建議一：高履約價（不易被賣掉）");
    expect(flex).toContain("建議二：平衡型（收較多權利金）");
    expect(flex).toContain("$245.00");
    expect(flex).toContain(`$${valid.suggestions[0]!.premium_per_contract.toFixed(2)}`);
    expect(flex).toContain(`Delta ${valid.suggestions[0]!.delta!.toFixed(2)}`);
    expect(flex).toContain("https://finance.yahoo.com/quote/NVDA/options");
    // V25-FIX3 measures the complete formula independent of Flex line wrapping.
    expect(flex.replace(/\s/g, "")).toContain("期間收益＝限價÷現價；年化收益＝期間收益×365÷DTE");
    // V25-FIX3 asserts the action embedded in the returned Flex message reaches the real text command.
    expect(flex).toContain("NVDA 每月期權 文字");
    expect(flex).not.toContain("UNAVAILABLE");
    const text = (buildCoveredCallMessages(valid, "每月期權", "text") as { text: string }[])[0]!.text;
    // V25-FIX3 verifies optional liquidity detail through the existing text edition.
    expect(text).toContain("流動性：OI");
    expect(text).toContain(`建議賣出限價 $${valid.suggestions[0]!.limit_price}`);
    expect(text).toContain("Delta 以買賣報價 IV 共同區間估算");
    expect(text).toContain("限價成交前不計入收益");
    for (const required of ["Bid情境", "每15分鐘", "最多4次", "0.01", "不低於Bid"]) expect(text).toContain(required);
    expect(text).toContain("本服務不下單");
  });

  it("discloses the common quote model and rejects obsolete, missing and one-sided Greeks", () => {
    admitSyntheticTickers("NVDA");
    const implied = cycle({ currency: "SEK", spot: 32.78, dte: 20, ...syntheticCalls(32.78, 20, 62) });
    const valid = validateCoveredCallCycle(implied)!;
    expect(valid).not.toBeNull();
    for (const style of ["text", "flex"] as const) {
      const rendered = JSON.stringify(buildCoveredCallMessages(valid, "每月期權", style));
      expect(rendered).toContain("Delta 以買賣報價 IV 共同區間估算");
      expect(rendered).toContain("共同波動率");
      expect(rendered).toContain("限價成交前不計入收益");
    }
    for (const delta_basis of ["QUOTED", "QUOTED_IV", "GUESSED"]) {
      const unknown = structuredClone(implied); Object.assign(unknown.suggestions[0]!, { delta_basis });
      expect(validateCoveredCallCycle(unknown)).toBeNull();
    }
    const badVol = structuredClone(implied); badVol.suggestions[0]!.iv = -1;
    expect(validateCoveredCallCycle(badVol)).toBeNull();
    const noDelta = cycle(); Object.assign(noDelta.suggestions[1]!, { delta: undefined });
    expect(validateCoveredCallCycle(noDelta)).toBeNull();
    const oneSided = cycle(); Object.assign(oneSided.suggestions[0]!, { ask: null, mid: null });
    expect(validateCoveredCallCycle(oneSided)).toBeNull();
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
    ...syntheticCalls(186.64, 11, 220), ...overrides,
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
      ...syntheticCalls(186.64, 12, 220),
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
      ...syntheticCalls(186.64, 14, 220),
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
