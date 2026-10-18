// Operator 2026-10-11: the middle covered-call tier and the current-calendar-week weekly expiry. Synthetic values only, fixed clocks.
// Twin of tests/test_option_tiers_weekly.py (same vectors). The operator's example: as of Wed 2026-10-07 with 2026-10-09 and
// 2026-10-16 listed the weekly is 2026-10-09; as of Sat 2026-10-10 it is 2026-10-16.
import { describe, expect, it, beforeEach, vi } from "vitest";
import { buildCoveredCallMessages, validateCoveredCallCycle } from "../src/v213/covered-call";
import {
  EXPIRY_DAY_CLOSE_LOCAL_MINUTES, MIDDLE_DELTA, MIDDLE_MONEYNESS, MIN_ANNUALIZATION_DAYS, MONTHLY_DTE_BUCKET, SHORT_DTE_NOTICE_MAX,
  WEEKLY_DTE_BUCKET, effectiveDays, exchangeDate, exchangeLocal, expiryDayOpen, limitMiddle, pickMiddle, roundTick, selectWeeklyExpiry,
  weekEndMs, weeklyWeekFor, weeklyWindowEndMs, dayMs, isoDay,
} from "../src/v213/option-recommendation-rules";
import { generateOptionsOrderGuidance, buildOptionsGuidanceText } from "../src/v213/options-guidance";
import { admitSyntheticTickers, resetAdmissionToReal } from "./synthetic-option-admission";

vi.mock("../src/v213/public-options-admission", async importOriginal => {
  const real = await importOriginal<typeof import("../src/v213/public-options-admission")>();
  return { ...real, admitPublicOption: vi.fn(real.admitPublicOption) };
});
beforeEach(() => { resetAdmissionToReal(); });

const at = (text: string) => Date.parse(text);
const LISTED = ["2026-10-09", "2026-10-16"];

describe("shared rules: constants (parity with scripts/option_recommendation_rules.py)", () => {
  it("pins the windows, the tiny-DTE floor and the middle-tier targets", () => {
    expect(WEEKLY_DTE_BUCKET).toEqual([0, 14]);
    expect(MONTHLY_DTE_BUCKET).toEqual([21, 45]);
    expect([MIN_ANNUALIZATION_DAYS, SHORT_DTE_NOTICE_MAX, MIDDLE_DELTA, MIDDLE_MONEYNESS]).toEqual([1, 2, 0.25, 1.025]);
    expect(EXPIRY_DAY_CLOSE_LOCAL_MINUTES).toEqual({ US: 960, STOCKHOLM: 1050, TAIFEX: 810 });
    expect([0, 1, 2, 30].map(effectiveDays)).toEqual([1, 1, 2, 30]);
  });
});

describe("shared rules: exchange clock", () => {
  it("US date follows New York, not UTC, across both DST edges", () => {
    expect(exchangeDate(at("2026-10-07T00:30:00Z"), "US")).toBe("2026-10-06");
    expect(exchangeDate(at("2026-10-07T14:00:00Z"), "US")).toBe("2026-10-07");
    const hm = (t: string, venue: "US" | "STOCKHOLM") => { const l = exchangeLocal(at(t), venue); return `${Math.floor(l.minutes / 60)}:${String(l.minutes % 60).padStart(2, "0")}`; };
    expect(hm("2026-03-08T06:59:00Z", "US")).toBe("1:59");
    expect(hm("2026-03-08T07:00:00Z", "US")).toBe("3:00");
    expect(hm("2026-11-01T05:59:00Z", "US")).toBe("1:59");
    expect(hm("2026-11-01T06:00:00Z", "US")).toBe("1:00");
    expect(exchangeDate(at("2026-11-02T04:59:00Z"), "US")).toBe("2026-11-01");
    expect(hm("2026-03-29T00:59:00Z", "STOCKHOLM")).toBe("1:59");
    expect(hm("2026-03-29T01:00:00Z", "STOCKHOLM")).toBe("3:00");
  });
  it("Stockholm and Taipei clocks", () => {
    expect(exchangeDate(at("2026-10-07T22:30:00Z"), "STOCKHOLM")).toBe("2026-10-08");
    expect(exchangeDate(at("2026-12-01T23:30:00Z"), "STOCKHOLM")).toBe("2026-12-02");
    expect(exchangeDate(at("2026-10-09T17:00:00Z"), "TAIFEX")).toBe("2026-10-10");
  });
  it("the expiry day is open only before the regular-session close", () => {
    for (const [venue, before, close] of [["US", "2026-10-09T19:59:00Z", "2026-10-09T20:00:00Z"],
      ["STOCKHOLM", "2026-10-09T15:29:00Z", "2026-10-09T15:30:00Z"], ["TAIFEX", "2026-10-09T05:29:00Z", "2026-10-09T05:30:00Z"]] as const) {
      expect(expiryDayOpen(at(before), venue)).toBe(true);
      expect(expiryDayOpen(at(close), venue)).toBe(false);
    }
  });
});

describe("shared rules: the current-week weekly", () => {
  const pick = (listed: string[], asOf: string, open = true) => selectWeeklyExpiry(listed, asOf, open);
  it("the operator's example: Wednesday picks this Friday's expiry, never the 16th", () => {
    expect(pick(LISTED, "2026-10-07")).toEqual({ expiry: "2026-10-09", week: "CURRENT" });
    expect(pick(LISTED, "2026-10-08")).toEqual({ expiry: "2026-10-09", week: "CURRENT" });
    expect(pick(LISTED, "2026-10-05")).toEqual({ expiry: "2026-10-09", week: "CURRENT" });
  });
  it("weekend and after the last weekly use the earliest expiry of next week", () => {
    expect(pick(LISTED, "2026-10-10")).toEqual({ expiry: "2026-10-16", week: "NEXT" });
    expect(pick(LISTED, "2026-10-11")).toEqual({ expiry: "2026-10-16", week: "NEXT" });
    expect(pick(LISTED, "2026-10-09", false)).toEqual({ expiry: "2026-10-16", week: "NEXT" });
    expect(pick(LISTED, "2026-10-09", true)).toEqual({ expiry: "2026-10-09", week: "CURRENT" });
  });
  it("the earliest listed expiry wins for Mon/Wed/Fri series", () => {
    const listed = ["2026-10-12", "2026-10-14", "2026-10-16"];
    expect(pick(listed, "2026-10-12")?.expiry).toBe("2026-10-12");
    expect(pick(listed, "2026-10-13")?.expiry).toBe("2026-10-14");
    expect(pick(listed, "2026-10-15")?.expiry).toBe("2026-10-16");
  });
  it("nothing beyond next week is a weekly and the old 3-14 window is gone", () => {
    expect(pick(["2026-10-23"], "2026-10-07")).toBeNull();
    expect(pick(["2026-10-19"], "2026-10-07")).toBeNull();
    expect(pick(["2026-10-18"], "2026-10-07")).toEqual({ expiry: "2026-10-18", week: "NEXT" });
    expect(pick(["2026-10-06"], "2026-10-07")).toBeNull();
    expect(pick([], "2026-10-07")).toBeNull();
    expect(pick(["not-a-date", "2026-02-30", "2026-10-09"], "2026-10-07")?.expiry).toBe("2026-10-09");
    expect(pick(LISTED, "2026-02-30")).toBeNull();
  });
  it("TAIFEX Wednesday and Friday weeklies need only listed dates", () => {
    const listed = ["2026-10-07", "2026-10-09", "2026-10-14", "2026-10-16"];
    expect(pick(listed, "2026-10-05")?.expiry).toBe("2026-10-07");
    expect(pick(listed, "2026-10-08")?.expiry).toBe("2026-10-09");
    expect(pick(listed, "2026-10-10")).toEqual({ expiry: "2026-10-14", week: "NEXT" });
    expect(pick(listed, "2026-10-07", false)?.expiry).toBe("2026-10-09");
  });
  it("calendar-week helpers", () => {
    const a = dayMs("2026-10-07")!;
    expect(isoDay(weekEndMs(a))).toBe("2026-10-11");
    expect(isoDay(weekEndMs(dayMs("2026-10-11")!))).toBe("2026-10-11");
    expect(isoDay(weekEndMs(dayMs("2026-10-12")!))).toBe("2026-10-18");
    expect(isoDay(weeklyWindowEndMs(a))).toBe("2026-10-18");
    expect(weeklyWeekFor("2026-10-09", "2026-10-07")).toBe("CURRENT");
    expect(weeklyWeekFor("2026-10-07", "2026-10-07")).toBe("CURRENT");
    expect(weeklyWeekFor("2026-10-16", "2026-10-07")).toBe("NEXT");
    expect(weeklyWeekFor("2026-10-18", "2026-10-07")).toBe("NEXT");
    expect(weeklyWeekFor("2026-10-19", "2026-10-07")).toBeNull();
    expect(weeklyWeekFor("2026-10-06", "2026-10-07")).toBeNull();
    expect(dayMs("2026-02-30")).toBeNull();
    expect(dayMs(20261007)).toBeNull();
  });
});

describe("shared rules: the middle tier and the middle of a limit range", () => {
  it("pickMiddle is strictly between and nearest the middle delta", () => {
    const rows = [{ strike: 110, delta: 0.12 }, { strike: 108, delta: 0.27 }, { strike: 107, delta: 0.24 }, { strike: 106, delta: 0.28 }];
    expect(pickMiddle(rows, 112, 105, 100)?.strike).toBe(107);
    expect(pickMiddle(rows, 110, 106, 100)?.strike).toBe(107);
    expect(pickMiddle(rows, 108, 107, 100)).toBeNull();
    expect(pickMiddle([{ strike: 108, delta: 0.125 }, { strike: 109, delta: 0.375 }], 112, 105, 100)?.strike).toBe(109);
  });
  it("without deltas the strike nearest the middle moneyness wins", () => {
    expect(pickMiddle([{ strike: 110, delta: null }, { strike: 102.5, delta: null }, { strike: 104, delta: null }], 112, 101, 100)?.strike).toBe(102.5);
    expect(pickMiddle([{ strike: 110, delta: 0.1 }, { strike: 103, delta: null }], 112, 101, 100)?.strike).toBe(103);
  });
  it("limitMiddle is on the tick and ordered low <= middle <= high", () => {
    expect(roundTick(1.075)).toBe(1.08);
    expect(limitMiddle(1.05, 1.10)).toBe(1.08);
    expect(limitMiddle(2, 2)).toBe(2);
    expect(limitMiddle(1.0, 1.01)).toBe(1.01);
    expect(limitMiddle(3.4, 3.0)).toBe(3.2);
    for (const [low, high] of [[0.01, 0.02], [4.25, 4.5], [0.37, 0.39], [12.34, 12.36]] as const) {
      const middle = limitMiddle(low, high);
      expect(middle).toBeGreaterThanOrEqual(low);
      expect(middle).toBeLessThanOrEqual(high);
      expect(middle).toBe(Number(middle.toFixed(2)));
    }
    expect(limitMiddle(0.10, 0.20, 0.05)).toBe(0.15);
  });
});

// ---- the Worker validator and renderer ---------------------------------------------------------------------------------
function tierItem(role: string, strike: number, bid: number, ask: number, delta: number, spot: number, dte: number) {
  const mid = Number(((bid + ask) / 2).toFixed(4));
  const limit = Number((Math.floor(mid / 0.01 + 1e-9) * 0.01).toFixed(2));
  return { role, strike, bid, ask, mid, limit_price: limit, premium_per_contract: limit * 100, period_yield: limit / spot,
    annualized_yield: limit / spot * 365 / Math.max(dte, 1), upside_to_strike: strike / spot - 1, delta, delta_basis: "QUOTED", iv: 0.4,
    oi: 10, volume: 1, spread_pct: (ask - bid) / mid };
}

function tierCycle(options: { dte?: number; expiry?: string; asof?: string | null; week?: string | null; middle?: boolean } = {}, overrides: Record<string, unknown> = {}): any {
  const { dte = 2, expiry = "2026-10-09", asof = "2026-10-07", week = "CURRENT", middle = true } = options;
  const cycle: any = { ticker: "NVDA", strategy: "COVERED_CALL", expiry, dte, spot: 100, currency: "USD", multiplier: 100, quote_basis: "delayed",
    timestamp: "2026-10-07T14:00:00Z", source: "Yahoo Finance option chain (unofficial, delayed)", provenance: "https://finance.yahoo.com/quote/NVDA/options",
    rights_status: "unadmitted_third_party",
    suggestions: [tierItem("HIGH_STRIKE", 112, 0.10, 0.12, 0.08, 100, dte), tierItem("BALANCED", 106, 0.60, 0.66, 0.28, 100, dte)] };
  if (middle) cycle.middle_suggestion = tierItem("MIDDLE", 108, 0.35, 0.40, 0.20, 100, dte);
  if (asof !== null) cycle.asof_date = asof;
  if (week !== null) cycle.weekly_week = week;
  return Object.assign(cycle, overrides);
}
const NOW = at("2026-10-07T14:05:00Z");
const DOC = "2026-10-07T14:00:00Z";
const check = (cycle: unknown, period: "weekly" | "monthly" = "weekly") => validateCoveredCallCycle(cycle, NOW, DOC, period);

describe("Worker validator: middle tier", () => {
  it("accepts a valid three-tier cycle, the older two-tier shape and a null middle marker", () => {
    expect(check(tierCycle())?.middle_suggestion?.strike).toBe(108);
    const old = tierCycle({ middle: false, asof: null, week: null });
    for (const key of ["middle_suggestion", "asof_date", "weekly_week"]) expect(old).not.toHaveProperty(key);
    expect(check(old)).not.toBeNull();
    expect(check(tierCycle({ middle: false }))).not.toBeNull();
    expect(check(tierCycle({}, { middle_suggestion: null }))).not.toBeNull();
  });
  it("the middle must be strictly between the two strikes", () => {
    for (const strike of [112, 106, 113, 105]) {
      const cycle = tierCycle();
      cycle.middle_suggestion = tierItem("MIDDLE", strike, 0.35, 0.40, 0.20, 100, 2);
      expect(check(cycle), String(strike)).toBeNull();
    }
  });
  it("needs both neighbours, the role MIDDLE and the same item checks", () => {
    const one = tierCycle(); one.suggestions = one.suggestions.slice(0, 1);
    expect(check(one)).toBeNull();
    const role = tierCycle(); role.middle_suggestion.role = "BALANCED";
    expect(check(role)).toBeNull();
    expect(check(tierCycle({}, { middle_suggestion: "x" }))).toBeNull();
    const mutations: Record<string, unknown> = { annualized_yield: 0.5, limit_price: 0.99, delta: 1.5, delta_basis: "GUESS", iv: -1, oi: -3, volume: Number.POSITIVE_INFINITY, strike: 99 };
    for (const [key, value] of Object.entries(mutations)) {
      const bad = tierCycle(); bad.middle_suggestion[key] = value;
      expect(check(bad), key).toBeNull();
    }
  });
  it("the suggestions list stays capped at the two original roles", () => {
    const three = tierCycle({ middle: false }); three.suggestions.splice(1, 0, tierItem("MIDDLE", 108, 0.35, 0.40, 0.20, 100, 2));
    expect(check(three)).toBeNull();
    const swapped = tierCycle({ middle: false }); swapped.suggestions[1].role = "MIDDLE";
    expect(check(swapped)).toBeNull();
  });
  it("does not mutate its input", () => {
    const cycle = tierCycle();
    const before = structuredClone(cycle);
    check(cycle);
    expect(cycle).toEqual(before);
  });
});

describe("Worker validator: current-week weekly and tiny DTE", () => {
  it("DTE 0-2 weekly rows are valid (no more 3-14 window); negative and beyond 60 are not", () => {
    for (const dte of [0, 1, 2]) {
      const expiry = `2026-10-${String(7 + dte).padStart(2, "0")}`;
      expect(check(tierCycle({ dte, expiry })), String(dte)).not.toBeNull();
    }
    expect(check(tierCycle({ dte: -1, expiry: "2026-10-06" }))).toBeNull();
    expect(check(tierCycle({ dte: 61, expiry: "2026-12-07" }), "monthly")).toBeNull();
  });
  it("a DTE 0 row is accepted while the US session is open and rejected after the close", () => {
    const open = at("2026-10-09T19:30:00Z");   // 15:30 New York
    const closed = at("2026-10-09T20:30:00Z"); // 16:30 New York
    const row = (stamp: string) => tierCycle({ dte: 0, expiry: "2026-10-09", asof: "2026-10-09" }, { timestamp: stamp });
    expect(validateCoveredCallCycle(row("2026-10-09T19:25:00Z"), open, "2026-10-09T19:25:00Z", "weekly")).not.toBeNull();
    expect(validateCoveredCallCycle(row("2026-10-09T20:25:00Z"), closed, "2026-10-09T20:25:00Z", "weekly")).toBeNull();
  });
  it("annualized yield is over at least one day at DTE 0", () => {
    const zero = tierCycle({ dte: 0, expiry: "2026-10-07" });
    expect(zero.suggestions[0].annualized_yield).toBeCloseTo(zero.suggestions[0].limit_price / 100 * 365, 9);
    expect(check(zero)).not.toBeNull();
    zero.suggestions[0].annualized_yield = zero.suggestions[0].limit_price / 100 * 365 * 2;
    expect(check(zero)).toBeNull();
  });
  it("the as-of date applies the calendar-week rule", () => {
    expect(check(tierCycle({ dte: 9, expiry: "2026-10-16", week: "NEXT" }))).not.toBeNull();
    expect(check(tierCycle({ dte: 11, expiry: "2026-10-18", week: "NEXT" }))).not.toBeNull();
    expect(check(tierCycle({ dte: 12, expiry: "2026-10-19", week: "NEXT" }))).toBeNull();
    expect(check(tierCycle({ dte: 9, expiry: "2026-10-16", week: "CURRENT" }))).toBeNull();
    expect(check(tierCycle({ dte: 2, expiry: "2026-10-09", week: "NEXT" }))).toBeNull();
    expect(check(tierCycle({ asof: "2026-02-30" }))).toBeNull();
    expect(check(tierCycle({}, { asof_date: 20261007 }))).toBeNull();
    expect(check(tierCycle({ asof: "2026-10-08" }))).toBeNull();
    expect(check(tierCycle(), "monthly")).toBeNull();
  });
  it("the week marker is weekly-only and two-valued", () => {
    expect(check(tierCycle({ asof: null, week: "LATER" }))).toBeNull();
    expect(check(tierCycle({ dte: 30, expiry: "2026-11-06", asof: null, week: "CURRENT" }), "monthly")).toBeNull();
    expect(check(tierCycle({ dte: 30, expiry: "2026-11-06", week: null }), "monthly")).not.toBeNull();
  });
});

function render(cycle: any, style: "flex" | "text" = "flex"): string {
  admitSyntheticTickers("NVDA");
  const valid = validateCoveredCallCycle(cycle)!;
  expect(valid).not.toBeNull();
  const messages = buildCoveredCallMessages(valid, "每週期權", style);
  return style === "text" ? (messages[0] as { text: string }).text : JSON.stringify(messages);
}

describe("LINE card: three tiers, week marker, tiny-DTE notice", () => {
  it("flex shows the three tiers in order with gap-free numbering", () => {
    const flex = render(tierCycle());
    const [one = -1, two = -1, three = -1] = ["建議一：高履約價（不易被賣掉）", "建議二：中間型（權利金與被指派機率居中）", "建議三：平衡型（收較多權利金）"].map(title => flex.indexOf(title));
    expect(one).toBeGreaterThan(-1);
    expect(two).toBeGreaterThan(one);
    expect(three).toBeGreaterThan(two);
    for (const strike of ["$112.00", "$108.00", "$106.00"]) expect(flex).toContain(strike);
    expect(flex).toContain("履約價與權利金介於高履約價與平衡型之間；被指派機率也居中。");
  });
  it("without a middle the two original titles are unchanged", () => {
    const flex = render(tierCycle({ middle: false }));
    expect(flex).toContain("建議一：高履約價（不易被賣掉）");
    expect(flex).toContain("建議二：平衡型（收較多權利金）");
    expect(flex).not.toContain("建議三");
    expect(flex).not.toContain("中間型");
    const only = tierCycle({ middle: false }); only.suggestions = only.suggestions.slice(0, 1);
    expect(render(only)).not.toContain("建議二");
  });
  it("text lists the tiers in order and a 3-tier text with maximal-length fields keeps the disclaimers within 4900", () => {
    const text = render(tierCycle(), "text");
    expect(text.indexOf("建議一")).toBeLessThan(text.indexOf("建議二：中間型"));
    expect(text.indexOf("建議二：中間型")).toBeLessThan(text.indexOf("建議三：平衡型"));
    const maximal = tierCycle({}, { provenance: `https://finance.yahoo.com/quote/NVDA/options?${"a".repeat(3000)}` });
    const long = render(maximal, "text");
    expect(long.length).toBeLessThanOrEqual(4900);
    expect(long).toContain("本服務不下單");
  });
  it("marks which calendar week the expiry is in, only for rows that carry the marker", () => {
    expect(render(tierCycle(), "text")).toContain("本週到期（以交易所當地日期 2026-10-07 判斷）");
    expect(render(tierCycle({ dte: 9, expiry: "2026-10-16", week: "NEXT" }), "text")).toContain("本週已無剩餘週選，顯示下週最早到期日");
    expect(render(tierCycle({ dte: 9, expiry: "2026-10-16", week: "NEXT" }))).toContain("本週已無剩餘週選，顯示下週最早到期日");
    const old = render(tierCycle({ asof: null, week: null }), "text");
    expect(old).not.toContain("本週到期");
    expect(old).not.toContain("下週");
  });
  it("labels DTE 0-2 as an amplified annualized figure and never at DTE 3 or more", () => {
    const zero = tierCycle({ dte: 0, expiry: "2026-10-07" });
    expect(render(zero)).toContain("今日到期");
    expect(render(zero, "text")).toContain("年化收益以至少 1 天換算");
    expect(render(tierCycle({ dte: 2 }), "text")).toContain("距到期僅 2 天");
    expect(render(tierCycle({ dte: 3, expiry: "2026-10-10", week: "CURRENT" }), "text")).not.toContain("年化收益以至少 1 天換算");
    expect(render(tierCycle({ dte: 9, expiry: "2026-10-16", week: "NEXT" }), "text")).not.toContain("年化收益以至少 1 天換算");
  });
});

describe("options guidance: weekly window and the expiry day", () => {
  const params = { ticker: "nvda", strategy: "covered_call" as const, underlyingPrice: 128.4, strike: 135, expiry: "2026-10-16", dte: 2, delta: 0.25,
    bid: 2.1, mid: 2.25, ask: 2.4, openInterest: 1200, volume: 350, cycle: "weekly" as const };
  it("a current-week expiry that is also the third-Friday monthly still matches a weekly request and says so", () => {
    const g = generateOptionsOrderGuidance(params);
    expect(g.expiry_cycle).toBe("MONTHLY");
    expect(g.cycle_matches_request).toBe(true);
    expect(g.dte_window_status).toBe("WITHIN_CYCLE_WINDOW");
    const text = buildOptionsGuidanceText(g);
    expect(text).toContain("週期權 Weekly｜DTE 2（標準區間 0-14 天，符合標準區間）｜本週到期，同時是標準月選到期日");
    expect(text).not.toContain("超出標準區間");
    expect(text).not.toContain("查詢為週期權");
  });
  it("a weekly request far beyond the window still does not match", () => {
    const g = generateOptionsOrderGuidance({ ...params, dte: 30 });
    expect(g.cycle_matches_request).toBe(false);
    expect(g.dte_window_status).toBe("OUTSIDE_CYCLE_WINDOW");
  });
  it("DTE 0 is accepted and annualized over at least one day", () => {
    const g = generateOptionsOrderGuidance({ ...params, dte: 0, expiry: "2026-10-09", mid: 1, strike: 100 });
    expect(g.annualized_yield_pct).toBeCloseTo(365, 6);
    expect(buildOptionsGuidanceText(g)).toContain("到期日極近");
    expect(() => generateOptionsOrderGuidance({ ...params, dte: -1 })).toThrow("OPTIONS_GUIDANCE_INVALID_DTE");
  });
});
