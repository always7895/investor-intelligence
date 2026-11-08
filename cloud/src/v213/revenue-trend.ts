/**
 * TREND_YOY_V1 (lane V33b): the lowest-priority revenue estimate of a Top20 card, computed by the Python producer
 * (scripts/revenue_trend.py) and sealed as the OPTIONAL entry field `revenue_trend`. This module only validates that
 * sealed object (it recomputes every figure from the sealed quarters and the sealed fundamentals: a few multiplications,
 * no per-request heavy work) and words it. Nothing here changes a sealed status, tile, score or rank.
 *
 * It applies ONLY where no existing basis does: a v3 forecast whose revenue state is unavailable for one of the V13
 * fail-closed reasons (revenue-history-model.ts) with no guidance and no consensus. A horizon that already has an
 * available figure (contracted recognition) keeps it. An absent, malformed or inconsistent field is ignored (the card
 * reads exactly as before). The estimate is labelled an estimate; it is never an actual and never company guidance.
 * Same arithmetic and constants as HISTORY_YOY_V1, so the two never disagree for the same inputs.
 */
import { HISTORY_ELIGIBLE_REASONS, HISTORY_GROWTH_CAP, HISTORY_GROWTH_FLOOR, HISTORY_YOY_FAULT } from "./revenue-history-model";

export interface TrendHorizon { start: string; end: string; amount: number; change: number }
export interface TrendEstimate {
  currency: string; anchor: string; tier: "A" | "B";
  quarters: { end: string; revenue: number }[];
  rates: { label: "latest" | "previous"; value: number }[];
  growthRaw: number | null; growth: number | null; capped: "UPPER" | "LOWER" | null;
  tierBReason: "NO_ALIGNED_YOY" | "YOY_OUT_OF_RANGE" | null;
  baseline: number; m6: TrendHorizon; m12: TrendHorizon; source: string; sourceUrl: string;
}
/** The parsed forecast's relevant fields (structural, so this module needs no import of the parser). */
export interface TrendForecastView {
  version?: number; revenueStatus?: "AVAILABLE" | "UNAVAILABLE"; revenueBasis?: string | null; revenueReason?: string | null;
  revenueDiagnostic?: string | null; m6: { status: string; basis?: string | null }; m12: { status: string; basis?: string | null };
}
export interface TrendFundamentals { source?: string; source_url?: string; quarter_end?: string; revenue_yoy?: number | null; revenue_yoy_prev?: number | null }

export const TREND_METHOD = "TREND_YOY_V1";
export const TREND_SCHEMA = "revenue-trend-v1";
export const TREND_LABEL = "趨勢推估（依已申報營收外推，非公司指引）";
export const TREND_CHIP = "趨勢推估·非公司指引";
export const TREND_FOOTNOTE = "趨勢推估＝以已報四季營收與年增外推（無可比年增時以最近一季持平），未計入其他資訊，實際可能大幅偏離。";
export const TREND_PRICE_TAG = "趨勢推估；P/S與股數不變；非目標價";
const TREND_MAX_ANCHOR_DAYS = 200;
const QUARTER_GAP = [76, 106] as const;
const DAY_MS = 86_400_000;
const isNum = (v: unknown): v is number => typeof v === "number" && Number.isFinite(v);
const isDay = (v: unknown): v is string => typeof v === "string" && /^[0-9]{4}-[0-9]{2}-[0-9]{2}$/.test(v)
  && new Date(Date.parse(`${v}T00:00:00Z`)).toISOString().slice(0, 10) === v && Number(v.slice(0, 4)) >= 1990 && Number(v.slice(0, 4)) <= 2100;
const dayMs = (v: string) => Date.parse(`${v}T00:00:00Z`);
const between = (a: string, b: string) => Math.round((dayMs(b) - dayMs(a)) / DAY_MS);
const shift = (v: string, days: number) => new Date(dayMs(v) + days * DAY_MS).toISOString().slice(0, 10);
const near = (a: unknown, b: unknown) => isNum(a) && isNum(b) && Math.abs(a - b) <= 1e-6 * Math.max(1, Math.abs(a), Math.abs(b));
const exactKeys = (v: any, keys: string[]) => !!v && typeof v === "object" && !Array.isArray(v)
  && Object.keys(v).length === keys.length && keys.every(k => Object.hasOwn(v, k));
const signedPct = (value: number) => {
  const text = Math.abs(value * 100).toFixed(0);
  return text === "0" ? "0%" : `${value > 0 ? "+" : "−"}${text}%`;
};

/** The same day `months` calendar months later, clamped to the month's last day. */
function addMonthsTo(day: string, months: number): string {
  const [year, month, date] = day.split("-").map(Number) as [number, number, number];
  const index = month - 1 + months;
  const y = year + Math.floor(index / 12);
  const m = ((index % 12) + 12) % 12;
  const last = new Date(Date.UTC(y, m + 1, 0)).getUTCDate();
  return new Date(Date.UTC(y, m, Math.min(date, last))).toISOString().slice(0, 10);
}
const middle = (values: number[]) => {
  const sorted = [...values].sort((a, b) => a - b);
  const n = sorted.length;
  return n % 2 === 1 ? sorted[(n - 1) / 2]! : (sorted[n / 2 - 1]! + sorted[n / 2]!) / 2;
};

/** The sealed `revenue_trend` object when it is exactly the producer's shape AND every figure recomputes from its own
 * quarters and the sealed fundamentals; otherwise null (never a partial or approximate acceptance). */
export function validTrend(raw: unknown, fund: TrendFundamentals | null | undefined, reportDay: string): TrendEstimate | null {
  const t = raw as any;
  if (!exactKeys(t, ["schema", "method", "currency", "anchor", "tier", "quarters", "rates", "growth_raw", "growth", "capped",
    "tier_b_reason", "baseline", "m6", "m12", "source", "source_url"])) return null;
  if (t.schema !== TREND_SCHEMA || t.method !== TREND_METHOD || !fund || !isDay(reportDay)) return null;
  if (typeof t.currency !== "string" || !/^[A-Z]{3}$/.test(t.currency) || !isDay(t.anchor) || t.anchor !== fund.quarter_end) return null;
  const age = between(t.anchor, reportDay);
  if (age < 0 || age > TREND_MAX_ANCHOR_DAYS) return null;
  if (typeof t.source !== "string" || t.source !== fund.source || typeof t.source_url !== "string" || t.source_url !== fund.source_url) return null;
  if (!Array.isArray(t.quarters) || t.quarters.length !== 4) return null;
  for (const q of t.quarters) if (!exactKeys(q, ["end", "revenue"]) || !isDay(q.end) || !isNum(q.revenue) || !(q.revenue > 0)) return null;
  const q = t.quarters as { end: string; revenue: number }[];
  if (q[3]!.end !== t.anchor) return null;
  for (let i = 1; i < 4; i++) {
    const gap = between(q[i - 1]!.end, q[i]!.end);
    if (gap < QUARTER_GAP[0] || gap > QUARTER_GAP[1]) return null;
  }
  // The rates are the sealed fundamentals' own rates for the anchor quarter, nothing else.
  const expectedRates: TrendEstimate["rates"] = [];
  if (isNum(fund.revenue_yoy)) expectedRates.push({ label: "latest", value: fund.revenue_yoy });
  if (isNum(fund.revenue_yoy_prev)) expectedRates.push({ label: "previous", value: fund.revenue_yoy_prev });
  if (!Array.isArray(t.rates) || t.rates.length !== expectedRates.length) return null;
  for (const [i, rate] of (t.rates as any[]).entries()) {
    if (!exactKeys(rate, ["label", "value"]) || rate.label !== expectedRates[i]!.label || !near(rate.value, expectedRates[i]!.value)) return null;
  }
  let tier: "A" | "B" = "B";
  let tierBReason: TrendEstimate["tierBReason"] = "NO_ALIGNED_YOY";
  let growthRaw: number | null = null, growth: number | null = null;
  let capped: TrendEstimate["capped"] = null;
  if (expectedRates.length > 0) {
    growthRaw = middle(expectedRates.map(r => r.value));
    if (Math.abs(growthRaw) > HISTORY_YOY_FAULT) tierBReason = "YOY_OUT_OF_RANGE";
    else {
      tier = "A"; tierBReason = null;
      growth = Math.min(HISTORY_GROWTH_CAP, Math.max(HISTORY_GROWTH_FLOOR, growthRaw));
      capped = growthRaw > HISTORY_GROWTH_CAP ? "UPPER" : growthRaw < HISTORY_GROWTH_FLOOR ? "LOWER" : null;
    }
  }
  if (t.tier !== tier || t.tier_b_reason !== tierBReason || t.capped !== capped
    || (growthRaw === null ? t.growth_raw !== null : !near(t.growth_raw, growthRaw))
    || (growth === null ? t.growth !== null : !near(t.growth, growth))) return null;
  const revenues = q.map(x => x.revenue);
  const forward = revenues.map(r => tier === "A" ? r * (1 + growth!) : revenues[3]!);
  const baseline = revenues[0]! + revenues[1]! + revenues[2]! + revenues[3]!;
  const amount6 = forward[0]! + forward[1]!;
  const amount12 = forward[0]! + forward[1]! + forward[2]! + forward[3]!;
  const ttm6 = revenues[2]! + revenues[3]! + amount6;
  if (![baseline, amount6, amount12, ttm6].every(v => Number.isFinite(v) && v > 0) || !near(t.baseline, baseline)) return null;
  const start = shift(t.anchor, 1);
  const horizon = (value: any, months: number, amount: number, change: number): TrendHorizon | null =>
    exactKeys(value, ["start", "end", "amount", "change"]) && value.start === start && value.end === shift(addMonthsTo(start, months), -1)
      && near(value.amount, amount) && near(value.change, change) ? { start, end: value.end, amount: value.amount, change: value.change } : null;
  const m6 = horizon(t.m6, 6, amount6, ttm6 / baseline - 1);
  const m12 = horizon(t.m12, 12, amount12, amount12 / baseline - 1);
  if (!m6 || !m12) return null;
  return { currency: t.currency, anchor: t.anchor, tier, quarters: q.map(x => ({ end: x.end, revenue: x.revenue })),
    rates: expectedRates, growthRaw, growth, capped, tierBReason, baseline, m6, m12, source: t.source, sourceUrl: t.source_url };
}

/** Whether the trend may stand in at all: a v3 forecast with an unavailable revenue state of an eligible reason, no
 * guidance or consensus on either horizon, and no diagnostic that suspends the revenue path on purpose. */
export function trendEligible(forecast: TrendForecastView | null | undefined): boolean {
  if (!forecast || forecast.version !== 3 || forecast.revenueStatus !== "UNAVAILABLE" || forecast.revenueBasis != null) return false;
  if (typeof forecast.revenueReason !== "string" || !HISTORY_ELIGIBLE_REASONS.has(forecast.revenueReason)) return false;
  if (forecast.revenueDiagnostic != null && forecast.revenueDiagnostic !== "CONSENSUS_DEFERRED") return false;
  for (const h of [forecast.m6, forecast.m12]) if (h.basis === "COMPANY_GUIDANCE" || h.basis === "CONSENSUS") return false;
  return true;
}

/** The trend horizon that fills a card row, or null: only a horizon without an available existing figure takes it. */
export function trendHorizonFor(trend: TrendEstimate | null | undefined, forecast: TrendForecastView, key: "m6" | "m12"): TrendHorizon | null {
  return trend && trendEligible(forecast) && forecast[key].status !== "AVAILABLE" ? trend[key] : null;
}

/** "去年同期已報營收×(1+年增 +59%)；年增已設上限 +100%" or the flat fallback. */
export function trendBasisText(t: TrendEstimate): string {
  if (t.tier === "B") return t.tierBReason === "YOY_OUT_OF_RANGE" ? "年增逾300%超出模型範圍，以最近一季營收持平推算" : "無可比年增，以最近一季營收持平推算";
  const label = t.rates.length === 2 ? "近兩季年增平均" : t.rates[0]!.label === "previous" ? "前一季年增" : "最新季年增";
  const cap = t.capped === "UPPER" ? "；年增已設上限 +100%" : t.capped === "LOWER" ? "；年增已設下限 −50%" : "";
  return `去年同期已報營收×(1+${label} ${signedPct(t.growth!)})${cap}`;
}

/** Lines for the text edition and the detail: heading, two figure rows, two price rows, footnote (+ inputs when `detail`). */
export function trendBlockLines(t: TrendEstimate | null | undefined, money: (amount: number, currency: string | null) => string,
  forecast: TrendForecastView, detail = false): string[] {
  if (!t || !trendEligible(forecast)) return [];
  const keys = (["m6", "m12"] as const).filter(key => forecast[key].status !== "AVAILABLE");
  if (keys.length === 0) return [];
  const name = { m6: "約6個月（2財季）", m12: "約1年（4財季）" } as const;
  const lines = [`${TREND_LABEL}｜截至最近已申報季末 ${t.anchor}`];
  for (const key of keys) lines.push(`${name[key]}：${money(t[key].amount, t.currency)}（${trendBasisText(t)}；自${t[key].start}起，非今日起）`);
  for (const key of keys) lines.push(`若${name[key]}達成趨勢推估 → 股價情境約 ${signedPct(t[key].change)}（${TREND_PRICE_TAG}）`);
  lines.push(TREND_FOOTNOTE);
  if (!detail) return lines;
  lines.push(`趨勢推估方法：${TREND_METHOD}；已報四季營收合計 ${money(t.baseline, t.currency)}；輸入：${t.quarters.map(x => `${x.end} ${money(x.revenue, t.currency)}`).join("，")}`);
  lines.push(t.tier === "A"
    ? `趨勢推估年增：${t.rates.map(r => `${r.label === "latest" ? "最新季" : "前一季"} ${signedPct(r.value)}`).join("，")}；採用 ${signedPct(t.growthRaw!)}${t.capped ? `，設限後 ${signedPct(t.growth!)}（範圍 −50% 至 +100%）` : "（未設限；範圍 −50% 至 +100%）"}；各季以其去年同季營收乘以(1+年增)，不複利`
    : "趨勢推估年增：無可用年增，改以最近一季營收持平推算");
  lines.push(`趨勢推估來源：${t.source}：${t.sourceUrl}`.slice(0, 300));
  return lines;
}
