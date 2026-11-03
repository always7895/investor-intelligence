import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import { bubblesOf, type Node } from "./flex-density-fixtures";
import { doc } from "./bottleneck-v3-fixture";
import { buildBottleneckDetail, buildBottleneckTop20Messages, outlookForecast, parseBottleneckV3 } from "../src/v213/bottleneck-v3";
import {
  TREND_CHIP, TREND_LABEL, trendBlockLines, trendEligible, trendHorizonFor, validTrend, type TrendForecastView,
} from "../src/v213/revenue-trend";

// V33b: TREND_YOY_V1. The Python producer is scripts/revenue_trend.py; the vectors are shared with tests/test_revenue_trend.py.
const vectors = JSON.parse(readFileSync("test/fixtures/revenue-trend-vectors.json", "utf-8"));
const proof = JSON.parse(readFileSync("../tests/fixtures/v213-orders-v3-proof-states.json", "utf-8"));
const GENERATED = Date.parse(proof.generated_at);
const REPORT_DAY: string = vectors.report_day;
const money = (amount: number, currency: string | null) => `${currency ?? "USD"} ${amount.toFixed(1)}`;
const clone = <T,>(value: T): T => structuredClone(value);

function explicitRows(node: Node): number {
  if (node.type === "text") return (node.text ?? (node.contents ?? []).map(span => span.text ?? "").join("")).split("\n").length;
  const rows = (node.contents ?? []).map(explicitRows);
  return node.layout === "horizontal" ? Math.max(0, ...rows) : rows.reduce((a, b) => a + b, 0);
}

/** The shared document with `symbol`'s sealed proof outlook on entry 1 and the vector's fundamentals; `trend` is the sealed
 * optional field (absent when undefined). */
function build(symbol: string, caseName: string | null, tweak?: (trend: any) => void) {
  const raw = doc(GENERATED);
  const entry: any = raw.top[1]!;
  entry.symbol = symbol;
  entry.outlook = clone(proof.entries[symbol]);
  if (caseName) {
    const sample = vectors.cases[caseName];
    entry.fundamentals = { ...entry.fundamentals, ...sample.fund };
    entry.revenue_trend = clone(sample.trend);
    tweak?.(entry.revenue_trend);
  }
  const parsed = parseBottleneckV3(raw, GENERATED + 3600_000)!;
  const messages = buildBottleneckTop20Messages(parsed, "flex");
  const bubbles = bubblesOf(messages);
  return { parsed, entry: parsed.top[1]!, card: bubbles[1]!, rendered: JSON.stringify(bubbles[1]!), shared: JSON.stringify(bubbles.at(-1)), messages };
}

describe("TREND_YOY_V1 validation (cloud/src/v213/revenue-trend.ts)", () => {
  it("accepts every shared vector and keeps the producer's figures", () => {
    for (const [name, sample] of Object.entries<any>(vectors.cases)) {
      const t = validTrend(sample.trend, sample.fund, REPORT_DAY);
      expect(t, name).not.toBeNull();
      expect(t!.m6.amount, name).toBeCloseTo(sample.trend.m6.amount, 6);
      expect(t!.m12.change, name).toBeCloseTo(sample.trend.m12.change, 9);
    }
    const growth = validTrend(vectors.cases.growth.trend, vectors.cases.growth.fund, REPORT_DAY)!;
    expect([growth.tier, growth.capped, growth.growth]).toEqual(["A", null, 0.4]);
    expect(growth.m6.amount).toBeCloseTo(294e6, 3);
    expect(growth.m12.amount).toBeCloseTo(672e6, 3);
    expect(growth.m6.change).toBeCloseTo((120 + 150 + 294) / 480 - 1, 9);
    expect(growth.m6.end).toBe("2026-12-31");
    expect(growth.m12.end).toBe("2027-06-30");
  });

  it("reproduces the clamp and the flat fallback", () => {
    const upper = validTrend(vectors.cases.upper_clamp.trend, vectors.cases.upper_clamp.fund, REPORT_DAY)!;
    expect([upper.capped, upper.growth]).toEqual(["UPPER", 1]);
    const lower = validTrend(vectors.cases.lower_clamp.trend, vectors.cases.lower_clamp.fund, REPORT_DAY)!;
    expect([lower.capped, lower.growth]).toEqual(["LOWER", -0.5]);
    const fault = validTrend(vectors.cases.flat_out_of_range.trend, vectors.cases.flat_out_of_range.fund, REPORT_DAY)!;
    expect([fault.tier, fault.tierBReason, fault.m12.amount]).toEqual(["B", "YOY_OUT_OF_RANGE", 600e6]);
    const none = validTrend(vectors.cases.flat_no_rate.trend, vectors.cases.flat_no_rate.fund, REPORT_DAY)!;
    expect([none.tier, none.tierBReason]).toEqual(["B", "NO_ALIGNED_YOY"]);
  });

  it("refuses any object that does not recompute from its own inputs and the sealed fundamentals", () => {
    const sample = vectors.cases.growth;
    const tampered: Record<string, (t: any) => void> = {
      "amount": t => { t.m12.amount *= 1.01; },
      "change": t => { t.m6.change += 0.01; },
      "growth": t => { t.growth = 0.9; },
      "tier": t => { t.tier = "B"; },
      "window end": t => { t.m6.end = "2026-12-30"; },
      "window start": t => { t.m12.start = "2026-06-30"; },
      "baseline": t => { t.baseline *= 1.01; },
      "quarter revenue": t => { t.quarters[0].revenue = 1e9; },
      "quarter gap": t => { t.quarters[1].end = "2026-01-31"; },
      "anchor": t => { t.anchor = "2026-03-31"; },
      "rate": t => { t.rates[0].value = 0.6; },
      "dropped rate": t => { t.rates.pop(); },
      "source": t => { t.source = "SEC EDGAR XBRL companyfacts"; },
      "source url": t => { t.source_url = "https://example.com/x"; },
      "currency": t => { t.currency = "usd"; },
      "schema": t => { t.schema = "revenue-trend-v2"; },
      "extra key": t => { t.extra = 1; },
      "missing key": t => { delete t.capped; },
      "non-finite": t => { t.m6.amount = null; },
    };
    for (const [name, mutate] of Object.entries(tampered)) {
      const t = clone(sample.trend);
      mutate(t);
      expect(validTrend(t, sample.fund, REPORT_DAY), name).toBeNull();
    }
    expect(validTrend(sample.trend, { ...sample.fund, revenue_yoy: 0.55 }, REPORT_DAY), "fundamentals rate changed").toBeNull();
    expect(validTrend(sample.trend, { ...sample.fund, quarter_end: "2026-03-31" }, REPORT_DAY)).toBeNull();
    expect(validTrend(sample.trend, null, REPORT_DAY)).toBeNull();
    expect(validTrend(undefined, sample.fund, REPORT_DAY)).toBeNull();
    expect(validTrend("x", sample.fund, REPORT_DAY)).toBeNull();
    expect(validTrend(sample.trend, sample.fund, "2027-01-20"), "an anchor older than 200 days").toBeNull();
    expect(validTrend(sample.trend, sample.fund, "2026-06-29"), "an anchor after the report day").toBeNull();
  });
});

describe("TREND_YOY_V1 priority (revenue-trend.ts)", () => {
  const view = (over: Partial<TrendForecastView> = {}): TrendForecastView => ({
    version: 3, revenueStatus: "UNAVAILABLE", revenueBasis: null, revenueReason: "INPUTS_MISSING", revenueDiagnostic: null,
    m6: { status: "UNAVAILABLE" }, m12: { status: "UNAVAILABLE" }, ...over });
  const trend = validTrend(vectors.cases.growth.trend, vectors.cases.growth.fund, REPORT_DAY)!;

  it("applies only where no existing basis does", () => {
    expect(trendEligible(view())).toBe(true);
    expect(trendEligible(view({ revenueReason: "NOT_DISCLOSED", revenueDiagnostic: "CONSENSUS_DEFERRED" }))).toBe(true);
    expect(trendEligible(view({ revenueStatus: "AVAILABLE", revenueBasis: "COMPANY_GUIDANCE", revenueReason: null }))).toBe(false);
    expect(trendEligible(view({ revenueBasis: "CONSENSUS" }))).toBe(false);
    expect(trendEligible(view({ m6: { status: "AVAILABLE", basis: "COMPANY_GUIDANCE" } }))).toBe(false);
    expect(trendEligible(view({ m12: { status: "AVAILABLE", basis: "CONSENSUS" } }))).toBe(false);
    for (const reason of ["INVALID", "WITHDRAWN", "CONFLICTING_DISCLOSURES", "EVIDENCE_LIMIT", "UNAVAILABLE", null, undefined]) {
      expect(trendEligible(view({ revenueReason: reason as any })), String(reason)).toBe(false);
    }
    for (const diagnostic of ["IR_COVERAGE_MISSING", "UNREVIEWED_INPUTS", "MACHINE_INPUTS_UNAVAILABLE"] as const) {
      expect(trendEligible(view({ revenueDiagnostic: diagnostic })), diagnostic).toBe(false);
    }
    expect(trendEligible(view({ version: 2 }))).toBe(false);
    expect(trendEligible(null)).toBe(false);
  });

  it("fills only a horizon without an available figure", () => {
    expect(trendHorizonFor(trend, view(), "m6")).toBe(trend.m6);
    const mixed = view({ m6: { status: "AVAILABLE", basis: "RECOGNITION" } });
    expect(trendHorizonFor(trend, mixed, "m6")).toBeNull();
    expect(trendHorizonFor(trend, mixed, "m12")).toBe(trend.m12);
    expect(trendHorizonFor(undefined, view(), "m6")).toBeNull();
    expect(trendBlockLines(trend, money, mixed).filter(line => line.startsWith("約6個月"))).toEqual([]);
    expect(trendBlockLines(trend, money, view({ revenueDiagnostic: "IR_COVERAGE_MISSING" }))).toEqual([]);
  });
});

describe("TREND_YOY_V1 on the Top20 card (POET: no reviewed record, INPUTS_MISSING)", () => {
  it("baseline: without the field the card keeps 未揭露 and 無法估價 exactly as before", () => {
    const base = build("POET", null);
    expect(base.entry.trend).toBeUndefined();
    expect(base.rendered).toContain("營收推估暫不可用");
    expect(base.rendered).toContain("未揭露");
    expect(base.rendered).toContain("無法估價");
    expect(base.rendered).not.toContain(TREND_CHIP);
    expect(base.rendered).not.toContain("趨勢推估");
    expect(JSON.stringify(base.messages)).not.toContain(TREND_LABEL);
  });

  it("shows the labelled estimate and a price scenario from the same estimate", () => {
    const withTrend = build("POET", "growth");
    expect(withTrend.entry.trend?.anchor).toBe("2026-06-30");
    const text = withTrend.rendered;
    expect(text).toContain(TREND_CHIP);
    expect(text).not.toContain("營收推估暫不可用");
    expect(text).not.toContain("未揭露\",\"size\":\"sm\"");
    expect(text).toContain("約半年趨勢推估");
    expect(text).toContain("約1年趨勢推估");
    expect(text).toContain("US$294M");
    expect(text).toContain("US$672M");
    expect(text).toMatch(/\+18%/); // (120+150+294)/480-1 = 17.5% -> 18%
    expect(text).toContain("+40%"); // 672/480-1
    expect(text).not.toContain("無法估價");
    expect(text).toContain(TREND_LABEL); // the footer reminder names the label
    expect(text).toContain("截至 2026-06-30");
    // never presented as an actual or as company guidance
    expect(text).not.toContain("公司財測＋模型");
    expect(text).not.toContain("實績");
    expect(explicitRows(withTrend.card.body as Node)).toBeLessThanOrEqual(10);
    expect(new TextEncoder().encode(text).length).toBeLessThan(46000);
    expect(withTrend.shared).toContain(TREND_LABEL);
    expect(withTrend.shared).toContain("近兩季年增平均 +40%");
  });

  it("states the clamp on the card source note", () => {
    const upper = build("POET", "upper_clamp");
    expect(upper.shared).toContain("年增已設上限 +100%");
    const flat = build("POET", "flat_out_of_range");
    expect(flat.shared).toContain("以最近一季營收持平推算");
  });

  it("an old bundle, or an invalid field, renders byte-identically to the baseline", () => {
    const base = build("POET", null);
    const sameFund = build("POET", "growth", t => { t.m12.amount *= 2; });
    expect(sameFund.entry.trend).toBeUndefined();
    // the vector fundamentals differ from the document's, so compare against a baseline with the same fundamentals
    const raw = doc(GENERATED);
    (raw.top[1] as any).symbol = "POET";
    (raw.top[1] as any).outlook = clone(proof.entries.POET);
    (raw.top[1] as any).fundamentals = { ...(raw.top[1] as any).fundamentals, ...vectors.cases.growth.fund };
    const reference = JSON.stringify(buildBottleneckTop20Messages(parseBottleneckV3(raw, GENERATED + 3600_000)!, "flex"));
    expect(JSON.stringify(sameFund.messages)).toBe(reference);
    expect(base.rendered).toContain("無法估價");
  });

  it("keeps 無法估價 with its reason when the trend inputs are missing", () => {
    const missing = build("POET", "growth", t => { t.quarters = t.quarters.slice(1); });
    expect(missing.entry.trend).toBeUndefined();
    expect(missing.rendered).toContain("營收推估暫不可用");
    expect(missing.rendered).toContain("無法估價");
    expect(missing.rendered).toContain("未揭露");
  });

  it("the detail text and the card lines carry the full labelled block", () => {
    const withTrend = build("POET", "growth");
    const lines = outlookForecast(withTrend.parsed, withTrend.entry).map(([text]) => text);
    expect(lines).toContain(`${TREND_LABEL}｜截至最近已申報季末 2026-06-30`);
    expect(lines.some(line => line.startsWith("約6個月（2財季）：") && line.includes("近兩季年增平均 +40%"))).toBe(true);
    expect(lines.some(line => line.startsWith("若約1年（4財季）達成趨勢推估 → 股價情境約 +40%"))).toBe(true);
    const detail = buildBottleneckDetail(withTrend.parsed, "POET", "text");
    const flat = typeof detail === "string" ? detail : detail.map(message => (message.type === "text" ? message.text : "")).join(" ");
    expect(flat).toContain("趨勢推估方法：TREND_YOY_V1");
    expect(flat).toContain("趨勢推估年增：最新季 +50%，前一季 +30%");
  });
});

describe("TREND_YOY_V1 never overrides an existing basis or a suspended path", () => {
  it("company guidance wins (MU)", () => {
    const mu = build("MU", "growth");
    expect(mu.entry.trend).toBeDefined(); // valid object, but not eligible
    expect(mu.rendered).not.toContain(TREND_CHIP);
    expect(mu.rendered).not.toContain("趨勢推估");
    expect(mu.shared).not.toContain(TREND_LABEL);
    const baseline = build("MU", null);
    expect(baseline.entry.forecast?.revenueBasis).toBe("COMPANY_GUIDANCE");
  });

  it("a suspended official-IR path stays suspended (SNDK, AAOI) and contracted recognition stays (SNDK)", () => {
    for (const symbol of ["SNDK", "AAOI"]) {
      const built = build(symbol, "growth");
      expect(built.entry.forecast?.revenueDiagnostic, symbol).toBe("IR_COVERAGE_MISSING");
      expect(built.rendered, symbol).not.toContain("趨勢推估");
    }
    expect(build("SNDK", "growth").rendered).toContain("約1年訂單認列");
  });

  it("a deferred consensus route (000660.KS, NOT_DISCLOSED) is eligible and labelled", () => {
    const kr = build("000660.KS", "growth");
    expect(kr.entry.forecast?.revenueReason).toBe("NOT_DISCLOSED");
    expect(kr.rendered).toContain(TREND_CHIP);
    expect(kr.rendered).toContain("約半年趨勢推估");
  });
});
