// V13 item 1: the Worker-only HISTORY_YOY_V1 revenue estimate drawn from an issuer's own reported quarters.
// Python twin: tests/test_v13_history_reference.py (shared vectors cloud/test/fixtures/v13-history-vectors.json, packaged with cloud/test).
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";
import {
  buildHistoryEstimate, evaluateHistory, historyBlockLines, historyViewOf, HISTORY_ELIGIBLE_REASONS, HISTORY_HEADING,
  type HistoryFundamentals, type HistoryInputs,
} from "../src/v213/revenue-history-model";
import { forecastCard, forecastLines, forecastText, historyInputsOf, parseOrderForecastV3, type OrderForecast } from "../src/v213/order-forecast";
import {
  buildBottleneckDetail, buildBottleneckTop20Messages, outlookForecast, parseBottleneckV3,
} from "../src/v213/bottleneck-v3";
import { assertLineMessages } from "../src/line-messages";
import { doc, HOUR } from "./bottleneck-v3-fixture";

const vectors = JSON.parse(readFileSync(resolve(__dirname, "fixtures/v13-history-vectors.json"), "utf-8"));
const golden = JSON.parse(readFileSync("../tests/fixtures/v213-orders-v3-golden-sealed.json", "utf-8"));
const GOLDEN_GENERATED = "2026-09-28T15:00:00Z";
const GOLDEN_DAY = "2026-09-28";
const BLOCKED = ["SNDK", "AVGO", "MTSI", "AAOI", "ALAB"];
const DEFERRED = ["000660.KS", "005930.KS"];
const money = (amount: number, currency: string | null) => `${currency ?? ""} ${Math.round(amount * 100) / 100}`;
const parseGolden = (sym: string): OrderForecast =>
  parseOrderForecastV3(golden[sym].order_forecast_v3, GOLDEN_DAY, sym, GOLDEN_GENERATED, golden[sym].order_forecast);

// The shared hand-checkable quarters (identical to the Python reference's base case).
const A = [
  { start: "2025-06-29", end: "2025-09-27", revenue: 100, currency: "USD" },
  { start: "2025-09-28", end: "2025-12-27", revenue: 110, currency: "USD" },
  { start: "2025-12-28", end: "2026-03-28", revenue: 120, currency: "USD" },
  { start: "2026-03-29", end: "2026-06-27", revenue: 130, currency: "USD" },
];
const F = [
  { start: "2026-06-28", end: "2026-09-26" }, { start: "2026-09-27", end: "2026-12-26" },
  { start: "2026-12-27", end: "2027-03-27" }, { start: "2027-03-28", end: "2027-06-26" },
];
const inputs = (over: Partial<HistoryInputs> = {}): HistoryInputs => ({ actuals: A, intervals: F, currency: "USD", ...over });
const FUND: HistoryFundamentals = { source: "Yahoo Finance", source_url: "https://finance.yahoo.com/quote/X", quarter_end: "2026-06-27", revenue_yoy: 0.3, revenue_yoy_prev: 0.2 };
const DAY = "2026-07-20";
const est = (i = inputs(), fund: HistoryFundamentals | null = FUND, day = DAY) => {
  const r = evaluateHistory(i, fund, day);
  if (!r.ok) throw new Error(`refused ${r.reason}`);
  return r.estimate;
};
/** The block text with the one permitted negation removed. */
const stripNegation = (text: string) => text.replaceAll("非公司財測、非分析師共識、非訂單", "");
const FORBIDDEN = /財測|共識|訂單/;

describe("HISTORY_YOY_V1 model", () => {
  it("history_vectors_match_the_python_reference", () => {
    expect(vectors.cases.length).toBeGreaterThanOrEqual(20);
    for (const c of vectors.cases) {
      const r = evaluateHistory(c.inputs, c.fund, c.report_day);
      expect(r.ok, c.id).toBe(c.expected.ok);
      if (!c.expected.ok) { expect((r as any).reason, c.id).toBe(c.expected.reason); continue; }
      const e = (r as any).estimate;
      expect(e.tier, c.id).toBe(c.expected.tier);
      expect(e.capped, c.id).toBe(c.expected.capped);
      for (const key of ["g", "g_raw"] as const) {
        if (c.expected[key] === null) expect(e[key], `${c.id} ${key}`).toBeNull();
        else expect(e[key], `${c.id} ${key}`).toBeCloseTo(c.expected[key], 12);
      }
      for (const key of ["B", "m6", "m12", "ttm6", "ttm12", "change6", "change12"] as const) {
        expect(Math.abs(e[key] - c.expected[key]) <= 1e-9 * Math.max(1, Math.abs(c.expected[key])), `${c.id} ${key}`).toBe(true);
      }
    }
  });

  it("history_tier_a_matches_hand_calc", () => {
    const e = est();
    // g = mean(0.30, 0.20) = 0.25; the forward quarters are the year-ago quarters x 1.25 (seasonality kept, no compounding).
    expect(e.tier).toBe("A");
    expect(e.g).toBeCloseTo(0.25, 12);
    expect(e.forward.map(q => q.amount)).toEqual([125, 137.5, 150, 162.5]);
    expect(e.B).toBe(460);
    expect(e.m6).toBe(262.5);
    expect(e.m12).toBe(575);
    expect(e.ttm6).toBe(120 + 130 + 262.5);
    expect(e.change6).toBeCloseTo(512.5 / 460 - 1, 12);
    expect(e.start).toBe("2026-06-28");
    expect(e.anchor).toBe("2026-06-27");
  });

  it("history_m12_change_equals_g", () => {
    for (const [a, b] of [[0.3, 0.2], [-0.1, -0.2], [0.05, null], [null, 0.4], [1.8, 1.4], [-0.9, -0.8]] as const) {
      const e = est(inputs(), { ...FUND, revenue_yoy: a, revenue_yoy_prev: b });
      expect(e.tier).toBe("A");
      expect(e.change12).toBeCloseTo(e.g!, 12);
    }
  });

  it("history_tier_b_flat_run_rate_when_no_aligned_yoy", () => {
    for (const fund of [null, { ...FUND, revenue_yoy: null, revenue_yoy_prev: null }, { ...FUND, quarter_end: "2026-03-28" }, { ...FUND, quarter_end: "2026-07-08" }]) {
      const e = est(inputs(), fund);
      expect(e.tier).toBe("B");
      expect(e.g).toBeNull();
      expect(e.forward.map(q => q.amount)).toEqual([130, 130, 130, 130]);
      expect(e.m6).toBe(260);
      expect(e.m12).toBe(520);
    }
    // A fundamentals quarter within 10 days of the anchor is aligned.
    expect(est(inputs(), { ...FUND, quarter_end: "2026-07-05" }).tier).toBe("A");
  });

  it("history_cap_applies_at_100pct_and_is_labelled", () => {
    const up = est(inputs(), { ...FUND, revenue_yoy: 1.8, revenue_yoy_prev: 1.4 });
    expect(up.g).toBe(1);
    expect(up.capped).toBe("UPPER");
    expect(up.change12).toBeCloseTo(1, 12);
    const text = historyBlockLines({ status: "ESTIMATE", ...up }, money).join("\n");
    expect(text).toContain("年增已設上限 +100%");
    const down = est(inputs(), { ...FUND, revenue_yoy: -0.8, revenue_yoy_prev: -0.7 });
    expect(down.g).toBe(-0.5);
    expect(historyBlockLines({ status: "ESTIMATE", ...down }, money).join("\n")).toContain("年增已設下限 −50%");
    // Exactly +100% is not a cap event.
    expect(est(inputs(), { ...FUND, revenue_yoy: 1, revenue_yoy_prev: 1 }).capped).toBeNull();
  });

  it("history_extreme_yoy_over_300pct_falls_to_tier_b", () => {
    const e = est(inputs(), { ...FUND, revenue_yoy: 4.2, revenue_yoy_prev: 3.8 });
    expect(e.tier).toBe("B");
    expect(e.tier_b_reason).toBe("YOY_OUT_OF_RANGE");
    expect(e.m12).toBe(520);
    const words = historyBlockLines({ status: "ESTIMATE", ...e }, money, true).join("\n");
    expect(words).toContain("超出模型適用範圍");
    expect(words).toContain("年增逾300%超出模型範圍，以最近一季營收持平推算");
    expect(words).not.toContain("資料異常");
    expect(est(inputs(), { ...FUND, revenue_yoy: 3, revenue_yoy_prev: 3 }).tier).toBe("A");
  });

  it("history_refuses_unaligned_calendar", () => {
    const shifted = F.map((q, i) => i >= 2 ? { start: q.start, end: i === 2 ? "2027-04-30" : "2027-07-31" } : q);
    const r = evaluateHistory(inputs({ intervals: shifted }), FUND, DAY);
    expect(r).toEqual({ ok: false, reason: "CALENDAR_UNALIGNED" });
    // The first forward interval must follow the anchor immediately.
    const gap = [{ start: "2026-07-05", end: F[0]!.end }, ...F.slice(1)];
    expect(evaluateHistory(inputs({ intervals: gap }), FUND, DAY)).toEqual({ ok: false, reason: "CALENDAR_UNALIGNED" });
    // 14 days off is the tolerance edge, 15 is refused.
    const edge = (extra: number) => F.map(q => ({ start: q.start, end: new Date(Date.parse(`${q.end}T00:00:00Z`) + extra * 86_400_000).toISOString().slice(0, 10) }));
    const stitched = (extra: number) => edge(extra).map((q, i, all) => ({ start: i === 0 ? F[0]!.start : new Date(Date.parse(`${all[i - 1]!.end}T00:00:00Z`) + 86_400_000).toISOString().slice(0, 10), end: q.end }));
    expect(evaluateHistory(inputs({ intervals: stitched(14) }), FUND, DAY).ok).toBe(true);
    expect(evaluateHistory(inputs({ intervals: stitched(15) }), FUND, DAY).ok).toBe(false);
  });

  it("history_refuses_anchor_older_than_200_days", () => {
    expect(evaluateHistory(inputs(), FUND, "2027-01-13").ok).toBe(true);
    expect(evaluateHistory(inputs(), FUND, "2027-01-14")).toEqual({ ok: false, reason: "ANCHOR_STALE" });
    expect(evaluateHistory(inputs(), FUND, "2026-06-01")).toEqual({ ok: false, reason: "ANCHOR_STALE" });
    // The reader sees the reason in words, and no figure.
    const view = historyViewOf({ historyInputs: inputs(), revenueStatus: "UNAVAILABLE", m6: {}, m12: {} }, FUND, "2027-01-14");
    expect(view).toEqual({ status: "STALE_ANCHOR", anchor: "2026-06-27" });
    expect(historyBlockLines(view, money)).toEqual(["歷史模型推估：歷史財報已逾200天（最近一季至2026-06-27），暫不推估"]);
  });

  it("history_refuses_when_a_newer_quarter_is_already_reported", () => {
    // The sealed fundamentals hold a quarter ending 45+ days after the anchor: the first forward quarter is a known past.
    expect(evaluateHistory(inputs(), { ...FUND, quarter_end: "2026-09-26" }, "2026-10-17")).toEqual({ ok: false, reason: "NEWER_QUARTER_REPORTED" });
    expect(evaluateHistory(inputs(), { ...FUND, quarter_end: "2026-08-11" }, DAY)).toEqual({ ok: false, reason: "NEWER_QUARTER_REPORTED" });
    expect(est(inputs(), { ...FUND, quarter_end: "2026-08-10" }).tier).toBe("B");
    const view = historyViewOf({ historyInputs: inputs(), revenueStatus: "UNAVAILABLE", m6: {}, m12: {} }, { ...FUND, quarter_end: "2026-09-26" }, "2026-10-17");
    expect(view).toEqual({ status: "NEWER_QUARTER", anchor: "2026-06-27", latest: "2026-09-26" });
    expect(historyBlockLines(view, money)).toEqual(["歷史模型推估：公司已公布至2026-09-26的較新季度，尚未收錄（已收錄至2026-06-27），暫不推估"]);
    expect(historyBlockLines(view, money).join("")).not.toMatch(/[0-9]+(\.[0-9]+)?(B|M|兆)/);
  });

  it("history_refuses_currency_mix_or_nonpositive_revenue", () => {
    expect(evaluateHistory(inputs({ actuals: [A[0]!, A[1]!, A[2]!, { ...A[3]!, currency: "EUR" }] }), FUND, DAY)).toEqual({ ok: false, reason: "BAD_ACTUALS" });
    expect(evaluateHistory(inputs({ actuals: [A[0]!, { ...A[1]!, revenue: 0 }, A[2]!, A[3]!] }), FUND, DAY)).toEqual({ ok: false, reason: "BAD_ACTUALS" });
    expect(evaluateHistory(inputs({ actuals: [A[0]!, { ...A[1]!, revenue: -5 }, A[2]!, A[3]!] }), FUND, DAY).ok).toBe(false);
    expect(evaluateHistory(inputs({ actuals: A.slice(1) }), FUND, DAY)).toEqual({ ok: false, reason: "NO_INPUTS" });
    expect(evaluateHistory(null, FUND, DAY)).toEqual({ ok: false, reason: "NO_INPUTS" });
  });
});

describe("HISTORY_YOY_V1 eligibility (fail closed)", () => {
  const actuals = A.map(q => ({ ...q, scope: "COMPANY" }));
  const evc = (over: Record<string, unknown> = {}): any => ({ limit: false, scopedLimit: false, conflict: false, hasWithdrawn: false, hasRecordEvidence: true,
    approvalSealed: true, machineAdmitted: false, actuals, intervals: F, currency: "USD", ...over });
  const ev = (over: Record<string, unknown> = {}): any => ({ consensus_fault: null, release_check_fault: null, ...over });

  it("history_eligible_reasons_are_exactly_the_designed_list", () => {
    expect([...HISTORY_ELIGIBLE_REASONS].sort()).toEqual(["FRESHNESS_UNVERIFIED", "INPUTS_MISSING", "NOT_DISCLOSED", "PERIOD_MISMATCH", "SAMPLE_INSUFFICIENT", "STALE"]);
    for (const reason of HISTORY_ELIGIBLE_REASONS) expect(historyInputsOf(reason, ev(), evc()), reason).not.toBeNull();
  });

  it("history_never_for_withdrawn_conflicting_invalid_unreviewed_evidence_limit_barrier", () => {
    for (const reason of ["WITHDRAWN", "CONFLICTING_DISCLOSURES", "INVALID", "EVIDENCE_LIMIT", "QUARTER_END_EXCEEDED_70D", "EXPIRED", "NO_REVENUE_BASIS", null, undefined]) {
      expect(historyInputsOf(reason as any, ev(), evc()), String(reason)).toBeNull();
    }
    const base = "NOT_DISCLOSED";
    expect(historyInputsOf(base, ev(), evc({ approvalSealed: false }))).toBeNull();                       // UNREVIEWED_INPUTS
    expect(historyInputsOf(base, ev(), evc({ approvalSealed: false, machineAdmitted: true }))).not.toBeNull();
    expect(historyInputsOf(base, ev(), evc({ scopedLimit: true }))).toBeNull();
    expect(historyInputsOf(base, ev(), evc({ limit: true }))).toBeNull();
    expect(historyInputsOf(base, ev(), evc({ conflict: true }))).toBeNull();
    expect(historyInputsOf(base, ev(), evc({ hasWithdrawn: true }))).toBeNull();
    expect(historyInputsOf(base, ev(), evc({ hasRecordEvidence: false }))).toBeNull();
    expect(historyInputsOf(base, ev(), evc(), { kind: "BARRIER", scoped: false, barrierReason: "STALE" } as any)).toBeNull();
    expect(historyInputsOf(base, ev(), evc(), { kind: "AUTO", scoped: false, barrierReason: null } as any)).not.toBeNull();
    expect(historyInputsOf(base, ev({ consensus_fault: "CONSENSUS_CACHE_MALFORMED" }), evc())).toBeNull();
    expect(historyInputsOf(base, ev({ release_check_fault: "RELEASE_CHECK_MALFORMED" }), evc())).toBeNull();
    // Actuals that are not four positive single-currency company-scope figures.
    expect(historyInputsOf(base, ev(), evc({ actuals: actuals.slice(1) }))).toBeNull();
    expect(historyInputsOf(base, ev(), evc({ actuals: actuals.map((q, i) => i === 3 ? { ...q, scope: "SEGMENT" } : q) }))).toBeNull();
    expect(historyInputsOf(base, ev(), evc({ actuals: actuals.map((q, i) => i === 1 ? { ...q, revenue: 0 } : q) }))).toBeNull();
    expect(historyInputsOf(base, ev(), evc({ actuals: actuals.map((q, i) => i === 2 ? { ...q, currency: "EUR" } : q) }))).toBeNull();
    expect(historyInputsOf(base, ev(), evc({ intervals: F.slice(1) }))).toBeNull();
    expect(historyInputsOf(base, ev(), evc({ currency: "EUR" }))).toBeNull();
  });

  it("history_never_when_guidance_or_consensus_available", () => {
    // Precedence is unchanged: admitted revenue (guidance or consensus) never reaches the model, even with inputs attached.
    for (const sym of ["NVDA", "MU", "LITE", "MRVL", "AMD", "CRDO", "BE", "NBIS", "CRWV"]) {
      const f = parseGolden(sym);
      expect(f.revenueStatus, sym).toBe("AVAILABLE");
      expect(f.historyInputs ?? null, sym).toBeNull();
      expect(f.m6.basis, sym).toBe("COMPANY_GUIDANCE");
      expect(buildHistoryEstimate(f, { ...FUND, quarter_end: f.reportedQuarters?.[3]?.end }, GOLDEN_DAY), sym).toBeNull();
    }
    const forged = { historyInputs: inputs(), revenueStatus: "AVAILABLE" as const, m6: { basis: "CONSENSUS" }, m12: { basis: "CONSENSUS" } };
    expect(buildHistoryEstimate(forged, FUND, DAY)).toBeNull();
    expect(buildHistoryEstimate({ ...forged, revenueStatus: "UNAVAILABLE" }, FUND, DAY)).toBeNull();
    expect(buildHistoryEstimate({ ...forged, revenueStatus: "UNAVAILABLE", m6: {}, m12: {} }, FUND, DAY)).not.toBeNull();
  });
});

describe("history block in the golden's failed-evidence states", () => {
  const anchorOf = (f: OrderForecast) => f.historyInputs!.actuals[3]!.end;
  const fundFor = (f: OrderForecast): HistoryFundamentals => ({ source: "SEC EDGAR XBRL companyfacts", source_url: "https://data.sec.gov/api/xbrl/companyfacts/CIK0000000001.json",
    quarter_end: anchorOf(f), revenue_yoy: 0.4, revenue_yoy_prev: 0.2 });
  const view = (f: OrderForecast) => historyViewOf(f, fundFor(f), GOLDEN_DAY);

  it("history_ir_coverage_missing_golden_issuers_get_estimate", () => {
    for (const sym of [...BLOCKED, ...DEFERRED]) {
      const f = parseGolden(sym);
      expect(f.revenueStatus, sym).toBe("UNAVAILABLE");
      expect(f.historyInputs, sym).toBeTruthy();
      const e = buildHistoryEstimate(f, fundFor(f), GOLDEN_DAY)!;
      expect(e, sym).not.toBeNull();
      expect(e.tier).toBe("A");
      expect(e.g).toBeCloseTo(0.3, 12);
      expect(e.change12).toBeCloseTo(0.3, 12);
      expect(e.B).toBeCloseTo(f.historyInputs!.actuals.reduce((s, q) => s + q.revenue, 0), 3);
      // The status of the sealed state is untouched: both tiles stay UNAVAILABLE with their sealed reason.
      expect(f.m6.status).toBe("UNAVAILABLE");
      expect(f.m12.status).toBe("UNAVAILABLE");
      const surfaces = {
        card: forecastCard(f, money, view(f)).map(([t]) => t).join("\n"),
        text: forecastText(f, money, view(f)),
        detail: forecastLines(f, money, view(f)).join("\n"),
      };
      for (const [name, body] of Object.entries(surfaces)) {
        expect(body, `${sym} ${name}`).toContain(HISTORY_HEADING);
        expect(body, `${sym} ${name}`).toContain("若約6個月（2財季）達成歷史模型推估 → 股價情境約 +");
      }
    }
    // The AVAILABLE issuers carry none.
    expect(parseGolden("NVDA").historyInputs ?? null).toBeNull();
  });

  it("history_keeps_failed_state_rows_verbatim_before_model_block", () => {
    for (const sym of [...BLOCKED, ...DEFERRED]) {
      const f = parseGolden(sym);
      const plain = forecastCard(f, money).map(([t]) => t);
      const withModel = forecastCard(f, money, view(f)).map(([t]) => t);
      const block = historyBlockLines(view(f), money);
      expect(block.length).toBe(6);
      // The first rows are the failed-state rows exactly as before; the block follows the suspension line.
      const suspensionIdx = plain.findIndex(t => t.startsWith("營收推估："));
      expect(suspensionIdx, sym).toBe(3);
      expect(withModel.slice(0, suspensionIdx + 1), sym).toEqual(plain.slice(0, suspensionIdx + 1));
      expect(withModel.slice(suspensionIdx + 1, suspensionIdx + 1 + block.length), sym).toEqual(block);
      // Everything after the block is the old card, byte for byte (the failed price rows included).
      expect(withModel.slice(suspensionIdx + 1 + block.length), sym).toEqual(plain.slice(suspensionIdx + 1));
      expect(withModel[1]).toMatch(/^約6個月（2財季）：/);
      // The old card is unchanged when no history view is passed.
      expect(forecastCard(f, money, null).map(([t]) => t)).toEqual(plain);
    }
    expect(forecastCard(parseGolden("SNDK"), money, view(parseGolden("SNDK"))).map(([t]) => t)[1]).toBe("約6個月（2財季）：官方IR查核未完成，暫停營收推估");
  });

  it("history_label_never_says_guidance_consensus_or_orders", () => {
    for (const sym of [...BLOCKED, ...DEFERRED]) {
      const f = parseGolden(sym);
      for (const detail of [false, true]) {
        const lines = historyBlockLines(view(f), money, detail);
        for (const line of lines) {
          expect(stripNegation(line), `${sym} ${line}`).not.toMatch(FORBIDDEN);
          expect(line).not.toContain("預計認列");
        }
        expect(lines[0]).toBe(HISTORY_HEADING);
      }
    }
    // Tier B, capped and stale variants too.
    const variants = [est(inputs(), null), est(inputs(), { ...FUND, revenue_yoy: 5, revenue_yoy_prev: 5 }), est(inputs(), { ...FUND, revenue_yoy: 2, revenue_yoy_prev: 2 }),
      est(inputs(), { ...FUND, revenue_yoy: -2, revenue_yoy_prev: -2 })];
    for (const e of variants) for (const line of historyBlockLines({ status: "ESTIMATE", ...e }, money, true)) expect(stripNegation(line), line).not.toMatch(FORBIDDEN);
    expect(stripNegation(historyBlockLines({ status: "STALE_ANCHOR", anchor: "2026-06-27" }, money)[0]!)).not.toMatch(FORBIDDEN);
  });
});

describe("history block through the real handlers (20 entries)", () => {
  const REPORT_MS = Date.parse(GOLDEN_GENERATED);
  const ORDER = ["SNDK", "AVGO", "MTSI", "AAOI", "ALAB", "000660.KS", "005930.KS", "NVDA", "MU", "LITE", "MRVL", "AMD", "CRDO", "BE", "NBIS", "CRWV"];
  function build() {
    const raw = doc(REPORT_MS) as any;
    raw.top.forEach((entry: any, i: number) => {
      const sym = ORDER[i];
      if (!sym) return;
      entry.symbol = sym;
      const f = parseGolden(sym);
      entry.outlook = { orders: null, consensus: null, scenarios: [], order_forecast: golden[sym].order_forecast, order_forecast_v3: golden[sym].order_forecast_v3 };
      const anchor = f.historyInputs?.actuals[3]?.end ?? f.reportedQuarters?.[3]?.end ?? "2026-06-30";
      entry.fundamentals = { ...entry.fundamentals, quarter_end: anchor, revenue_yoy: 0.4, revenue_yoy_prev: 0.2 };
    });
    return raw;
  }

  it("history_ranking_and_scores_unchanged", () => {
    const raw = build();
    const before = JSON.stringify(raw.top.map((e: any) => [e.rank, e.symbol, e.score, e.parts, e.archetype]));
    const parsed = parseBottleneckV3(raw, REPORT_MS + HOUR)!;
    expect(parsed).not.toBeNull();
    expect(JSON.stringify(parsed.top.map(e => [e.rank, e.symbol, e.score, e.parts, e.archetype]))).toBe(before);
    // Rendering never mutates the document, and the sealed tiles of the blocked issuers keep their sealed states.
    const snapshot = JSON.stringify(parsed.top.map(e => ({ ...e, forecast: { ...e.forecast, historyInputs: undefined } })));
    buildBottleneckTop20Messages(parsed, "flex"); buildBottleneckTop20Messages(parsed, "text");
    for (const sym of BLOCKED) buildBottleneckDetail(parsed, sym, "flex");
    expect(JSON.stringify(parsed.top.map(e => ({ ...e, forecast: { ...e.forecast, historyInputs: undefined } })))).toBe(snapshot);
    for (const sym of BLOCKED) {
      const f = parsed.top.find(e => e.symbol === sym)!.forecast!;
      expect([f.m6.status, f.m12.status, f.revenueStatus]).toEqual(["UNAVAILABLE", "UNAVAILABLE", "UNAVAILABLE"]);
      expect(f.m6.reason).toBe("FRESHNESS_UNVERIFIED");
    }
  });

  it("history_payload_within_line_limits_all_20", () => {
    const parsed = parseBottleneckV3(build(), REPORT_MS + HOUR)!;
    expect(parsed.top).toHaveLength(20);
    const flex = buildBottleneckTop20Messages(parsed, "flex");
    expect(() => assertLineMessages(flex)).not.toThrow();
    expect(() => assertLineMessages(buildBottleneckTop20Messages(parsed, "text"))).not.toThrow();
    // Every blocked/deferred card carries the model block (the compact card, or the lean card when twenty full cards do not fit).
    const serialized = JSON.stringify(flex);
    expect(serialized.split(HISTORY_HEADING).length - 1).toBe(BLOCKED.length + DEFERRED.length);
    expect(stripNegation(serialized.split(HISTORY_HEADING).slice(1).map(s => s.slice(0, 700)).join(""))).not.toContain("預計認列");
    for (const entry of parsed.top) {
      for (const mode of ["flex", "text"] as const) {
        const detail = buildBottleneckDetail(parsed, entry.symbol, mode);
        if (Array.isArray(detail)) expect(() => assertLineMessages(detail)).not.toThrow();
      }
    }
    for (const sym of [...BLOCKED, ...DEFERRED]) {
      const detail = JSON.stringify(buildBottleneckDetail(parsed, sym, "text"));
      expect(detail, sym).toContain(HISTORY_HEADING);
      expect(detail, sym).toContain("歷史模型方法：HISTORY_YOY_V1");
      const card = outlookForecast(parsed, parsed.top.find(e => e.symbol === sym)!).map(([t]) => t);
      expect(card.indexOf(HISTORY_HEADING), sym).toBeGreaterThan(2);
    }
    // The available issuers' cards do not mention the model at all.
    for (const sym of ["NVDA", "CRWV"]) {
      expect(outlookForecast(parsed, parsed.top.find(e => e.symbol === sym)!).map(([t]) => t).join("\n")).not.toContain("歷史模型");
    }
  });
});
