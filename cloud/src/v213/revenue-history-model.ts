/**
 * HISTORY_YOY_V1 (V13 item 1): a deterministic, Worker-only revenue estimate drawn from an issuer's own reported quarters.
 * It is derived at render time from data the sealer already validated (the four reported quarters, the four forward
 * intervals, the sealed fundamentals). Nothing here is sealed, nothing changes a sealed status, a tile, a score or a rank:
 * the guidance / consensus state stays UNAVAILABLE with its failed-evidence rows, and this block is appended beside them.
 * Guidance or consensus, when admitted, always wins (the inputs are only ever attached to an unavailable revenue state).
 * The Python reference is tests/test_v13_history_reference.py (shared vectors cloud/test/fixtures/v13-history-vectors.json).
 */

export interface HistoryActual { start: string; end: string; revenue: number; currency: string }
export interface HistoryInterval { start: string; end: string }
/** The validated inputs the parser attaches to an unavailable revenue state that passed the eligibility list. */
export interface HistoryInputs { actuals: HistoryActual[]; intervals: HistoryInterval[]; currency: string }
export interface HistoryFundamentals {
  source?: string | null; source_url?: string | null; quarter_end?: string | null;
  revenue_yoy?: number | null; revenue_yoy_prev?: number | null;
}
export interface HistoryEstimate {
  tier: "A" | "B";
  /** The growth actually applied (null in tier B). */
  g: number | null;
  /** The raw growth before the cap (null in tier B). */
  g_raw: number | null;
  capped: "UPPER" | "LOWER" | null;
  rates: { label: "最新季" | "前一季"; value: number }[];
  /** Why tier B was used (null in tier A). */
  tier_b_reason: "NO_ALIGNED_YOY" | "YOY_OUT_OF_RANGE" | null;
  currency: string;
  quarters: { start: string; end: string; revenue: number }[];
  forward: { start: string; end: string; amount: number }[];
  B: number; ttm6: number; ttm12: number; m6: number; m12: number; change6: number; change12: number;
  anchor: string; start: string;
  source: string | null; source_url: string | null;
}
export type HistoryRefusal = "NO_INPUTS" | "BAD_ACTUALS" | "CALENDAR_UNALIGNED" | "ANCHOR_STALE" | "NEWER_QUARTER_REPORTED" | "REVENUE_AVAILABLE";
export type HistoryResult = { ok: true; estimate: HistoryEstimate } | { ok: false; reason: HistoryRefusal };
/** What the renderers receive: the estimate, or a refusal that is shown to the reader (an old anchor, or a newer reported
 * quarter the sealed quarters do not hold yet). */
export type HistoryView = ({ status: "ESTIMATE" } & HistoryEstimate) | { status: "STALE_ANCHOR"; anchor: string }
  | { status: "NEWER_QUARTER"; anchor: string; latest: string };

export const HISTORY_METHOD = "HISTORY_YOY_V1";
export const HISTORY_MAX_ANCHOR_DAYS = 200;
export const HISTORY_CALENDAR_TOLERANCE_DAYS = 14;
export const HISTORY_YOY_ALIGN_DAYS = 10;
/** A sealed fundamentals quarter this many days or more after the anchor means a later quarter is already reported. */
export const HISTORY_NEWER_QUARTER_DAYS = 45;
export const HISTORY_GROWTH_FLOOR = -0.5;
export const HISTORY_GROWTH_CAP = 1.0;
export const HISTORY_YOY_FAULT = 3;
/** Sealed revenue reasons for which the model may appear (everything else fails closed). */
export const HISTORY_ELIGIBLE_REASONS: ReadonlySet<string> = new Set(
  ["INPUTS_MISSING", "NOT_DISCLOSED", "FRESHNESS_UNVERIFIED", "STALE", "SAMPLE_INSUFFICIENT", "PERIOD_MISMATCH"]);

export const HISTORY_HEADING = "歷史模型推估（依公司過去財報；非公司財測、非分析師共識、非訂單）";
export const HISTORY_FOOTNOTE = "歷史模型＝以已報四季營收與年增外推（無可比年增時以最近一季持平），未計入其他資訊，實際可能大幅偏離。";
export const HISTORY_PRICE_TAG = "歷史模型；P/S與股數不變；非目標價";

const DAY_MS = 86_400_000;
const isDay = (v: unknown): v is string => typeof v === "string" && /^[0-9]{4}-[0-9]{2}-[0-9]{2}$/.test(v)
  && new Date(Date.parse(`${v}T00:00:00Z`)).toISOString().slice(0, 10) === v;
const dayMs = (v: string) => Date.parse(`${v}T00:00:00Z`);
const daysBetween = (from: string, to: string) => Math.round((dayMs(to) - dayMs(from)) / DAY_MS);
const isNum = (v: unknown): v is number => typeof v === "number" && Number.isFinite(v);
const signedPct = (value: number) => {
  const text = Math.abs(value * 100).toFixed(0);
  return text === "0" ? "0%" : `${value > 0 ? "+" : "−"}${text}%`;
};

/** Mean of the usable rates (the median of one or two values). */
function middle(values: number[]): number {
  const sorted = [...values].sort((a, b) => a - b);
  const n = sorted.length;
  return n % 2 === 1 ? sorted[(n - 1) / 2]! : (sorted[n / 2 - 1]! + sorted[n / 2]!) / 2;
}

/** The pure model. `inputs` are the validated sealed quarters; `fund` the sealed fundamentals (may be null). */
export function evaluateHistory(inputs: HistoryInputs | null | undefined, fund: HistoryFundamentals | null | undefined, reportDay: string): HistoryResult {
  if (!inputs || !Array.isArray(inputs.actuals) || !Array.isArray(inputs.intervals) || !isDay(reportDay)) return { ok: false, reason: "NO_INPUTS" };
  if (inputs.actuals.length < 4 || inputs.intervals.length !== 4) return { ok: false, reason: "NO_INPUTS" };
  const a = inputs.actuals.slice(-4);
  const f = inputs.intervals;
  const currency = inputs.currency;
  if (typeof currency !== "string" || currency.length === 0) return { ok: false, reason: "BAD_ACTUALS" };
  for (const q of a) {
    if (!q || !isDay(q.start) || !isDay(q.end) || q.start > q.end || !isNum(q.revenue) || !(q.revenue > 0) || q.currency !== currency) return { ok: false, reason: "BAD_ACTUALS" };
  }
  for (const q of f) if (!q || !isDay(q.start) || !isDay(q.end) || q.start > q.end) return { ok: false, reason: "CALENDAR_UNALIGNED" };
  // Contiguous actuals and intervals, the first interval right after the anchor.
  for (let i = 1; i < 4; i++) {
    if (daysBetween(a[i - 1]!.end, a[i]!.start) !== 1 || daysBetween(f[i - 1]!.end, f[i]!.start) !== 1) return { ok: false, reason: "CALENDAR_UNALIGNED" };
  }
  const anchor = a[3]!.end;
  if (daysBetween(anchor, f[0]!.start) !== 1) return { ok: false, reason: "CALENDAR_UNALIGNED" };
  // Each forward quarter has its own year-ago actual: A(k).end + 364 d within +/-14 d of F(k).end.
  for (let k = 0; k < 4; k++) {
    if (Math.abs(daysBetween(a[k]!.end, f[k]!.end) - 364) > HISTORY_CALENDAR_TOLERANCE_DAYS) return { ok: false, reason: "CALENDAR_UNALIGNED" };
  }
  const age = daysBetween(anchor, reportDay);
  if (age < 0 || age > HISTORY_MAX_ANCHOR_DAYS) return { ok: false, reason: "ANCHOR_STALE" };
  // A later quarter is already reported (the sealed fundamentals hold it, the sealed quarters do not): the first forward
  // quarter would be presented as an estimate of a known past, so no figure is shown.
  if (fund && isDay(fund.quarter_end) && daysBetween(anchor, fund.quarter_end) >= HISTORY_NEWER_QUARTER_DAYS) return { ok: false, reason: "NEWER_QUARTER_REPORTED" };

  // Growth: only rates that belong to the anchor quarter (10 d) are usable.
  const rates: HistoryEstimate["rates"] = [];
  if (fund && isDay(fund.quarter_end) && Math.abs(daysBetween(fund.quarter_end, anchor)) <= HISTORY_YOY_ALIGN_DAYS) {
    if (isNum(fund.revenue_yoy)) rates.push({ label: "最新季", value: fund.revenue_yoy });
    if (isNum(fund.revenue_yoy_prev)) rates.push({ label: "前一季", value: fund.revenue_yoy_prev });
  }
  let tier: "A" | "B" = "B";
  let tierBReason: HistoryEstimate["tier_b_reason"] = "NO_ALIGNED_YOY";
  let gRaw: number | null = null;
  let g: number | null = null;
  let capped: HistoryEstimate["capped"] = null;
  if (rates.length > 0) {
    gRaw = middle(rates.map(r => r.value));
    if (Math.abs(gRaw) > HISTORY_YOY_FAULT) {
      tierBReason = "YOY_OUT_OF_RANGE";
    } else {
      tier = "A";
      tierBReason = null;
      g = Math.min(HISTORY_GROWTH_CAP, Math.max(HISTORY_GROWTH_FLOOR, gRaw));
      capped = gRaw > HISTORY_GROWTH_CAP ? "UPPER" : gRaw < HISTORY_GROWTH_FLOOR ? "LOWER" : null;
    }
  }
  const amounts = f.map((_, k) => tier === "A" ? a[k]!.revenue * (1 + g!) : a[3]!.revenue);
  if (!amounts.every(v => Number.isFinite(v) && v > 0)) return { ok: false, reason: "BAD_ACTUALS" };
  const B = a[0]!.revenue + a[1]!.revenue + a[2]!.revenue + a[3]!.revenue;
  const m6 = amounts[0]! + amounts[1]!;
  const m12 = amounts[0]! + amounts[1]! + amounts[2]! + amounts[3]!;
  const ttm6 = a[2]!.revenue + a[3]!.revenue + m6;
  const ttm12 = m12;
  return { ok: true, estimate: {
    tier, g, g_raw: gRaw, capped, rates, tier_b_reason: tierBReason, currency,
    quarters: a.map(q => ({ start: q.start, end: q.end, revenue: q.revenue })),
    forward: f.map((q, k) => ({ start: q.start, end: q.end, amount: amounts[k]! })),
    B, ttm6, ttm12, m6, m12, change6: ttm6 / B - 1, change12: ttm12 / B - 1,
    anchor, start: f[0]!.start,
    source: typeof fund?.source === "string" ? fund.source : null, source_url: typeof fund?.source_url === "string" ? fund.source_url : null,
  } };
}

/** The parsed forecast's relevant fields (structural, so this module needs no import of the parser). */
export interface HistoryForecastView {
  historyInputs?: HistoryInputs | null; revenueStatus?: "AVAILABLE" | "UNAVAILABLE";
  m6?: { basis?: string | null }; m12?: { basis?: string | null };
}

/** The estimate for a parsed forecast, or null: never when revenue is available (guidance / consensus always wins). */
export function buildHistoryEstimate(forecast: HistoryForecastView | null | undefined, fund: HistoryFundamentals | null | undefined, reportDay: string): HistoryEstimate | null {
  const result = historyResultOf(forecast, fund, reportDay);
  return result && result.ok ? result.estimate : null;
}

function historyResultOf(forecast: HistoryForecastView | null | undefined, fund: HistoryFundamentals | null | undefined, reportDay: string): HistoryResult | null {
  if (!forecast || !forecast.historyInputs) return null;
  if (forecast.revenueStatus !== "UNAVAILABLE") return { ok: false, reason: "REVENUE_AVAILABLE" };
  for (const h of [forecast.m6, forecast.m12]) if (h && (h.basis === "COMPANY_GUIDANCE" || h.basis === "CONSENSUS")) return { ok: false, reason: "REVENUE_AVAILABLE" };
  return evaluateHistory(forecast.historyInputs, fund, reportDay);
}

/** What the renderers show: the estimate, the old-anchor notice, or nothing. */
export function historyViewOf(forecast: HistoryForecastView | null | undefined, fund: HistoryFundamentals | null | undefined, reportDay: string): HistoryView | null {
  const result = historyResultOf(forecast, fund, reportDay);
  if (!result) return null;
  if (result.ok) return { status: "ESTIMATE", ...result.estimate };
  const anchor = forecast?.historyInputs?.actuals.slice(-1)[0]?.end;
  if (typeof anchor !== "string") return null;
  if (result.reason === "ANCHOR_STALE") return { status: "STALE_ANCHOR", anchor };
  if (result.reason === "NEWER_QUARTER_REPORTED" && typeof fund?.quarter_end === "string") return { status: "NEWER_QUARTER", anchor, latest: fund.quarter_end };
  return null;
}

type Money = (amount: number, currency: string | null) => string;

function basisText(e: HistoryEstimate): string {
  if (e.tier === "B") return e.tier_b_reason === "YOY_OUT_OF_RANGE" ? "年增逾300%超出模型範圍，以最近一季營收持平推算" : "無可比年增，以最近一季營收持平推算";
  const only = e.rates.length === 1 ? e.rates[0]!.label : null;
  const label = e.rates.length === 2 ? "近兩季年增平均" : only === "前一季" ? "前一季年增" : "最新季年增";
  const cap = e.capped === "UPPER" ? "；年增已設上限 +100%" : e.capped === "LOWER" ? "；年增已設下限 −50%" : "";
  return `去年同期已報營收×(1+${label} ${signedPct(e.g!)})${cap}`;
}

/** The block's lines. Compact: heading, two rows, two price rows, footnote. Detail adds the model inputs. */
export function historyBlockLines(view: HistoryView | null | undefined, money: Money, detail = false): string[] {
  if (!view) return [];
  if (view.status === "STALE_ANCHOR") return [`歷史模型推估：歷史財報已逾${HISTORY_MAX_ANCHOR_DAYS}天（最近一季至${view.anchor}），暫不推估`];
  if (view.status === "NEWER_QUARTER") return [`歷史模型推估：公司已公布至${view.latest}的較新季度，尚未收錄（已收錄至${view.anchor}），暫不推估`];
  const e = view;
  const row = (label: string, amount: number) => `${label}：${money(amount, e.currency)}（${basisText(e)}；自${e.start}起，非今日起）`;
  const price = (label: string, change: number) => `若${label}達成歷史模型推估 → 股價情境約 ${signedPct(change)}（${HISTORY_PRICE_TAG}）`;
  const lines = [
    HISTORY_HEADING,
    row("約6個月（2財季）", e.m6),
    row("約1年（4財季）", e.m12),
    price("約6個月（2財季）", e.change6),
    price("約1年（4財季）", e.change12),
    HISTORY_FOOTNOTE,
  ];
  if (!detail) return lines;
  lines.push(`歷史模型方法：${HISTORY_METHOD}；基準日（最近一季結束）${e.anchor}；已報四季營收合計 ${money(e.B, e.currency)}`);
  lines.push(`歷史模型輸入（已報四季）：${e.quarters.map(q => `${q.end} ${money(q.revenue, e.currency)}`).join("，")}`);
  if (e.tier === "A") {
    lines.push(`歷史模型年增：${e.rates.map(r => `${r.label} ${signedPct(r.value)}`).join("，")}；採用 ${signedPct(e.g_raw!)}${e.capped ? `，設限後 ${signedPct(e.g!)}（範圍 −50% 至 +100%）` : "（未設限；範圍 −50% 至 +100%）"}；各季以其去年同季營收乘以(1+年增)，不複利`);
  } else if (e.tier_b_reason === "YOY_OUT_OF_RANGE") {
    lines.push(`歷史模型年增：${e.rates.map(r => `${r.label} ${signedPct(r.value)}`).join("，")}；年增絕對值逾300%，超出模型適用範圍，改以最近一季營收持平推算`);
  } else {
    lines.push("歷史模型年增：無與基準日對齊的可用年增，改以最近一季營收持平推算");
  }
  lines.push(`歷史模型逐季：${e.forward.map((q, k) => `第${k + 1}季（${q.start}至${q.end}）${money(q.amount, e.currency)}`).join("，")}`);
  if (e.source) lines.push(`年增來源：${e.source}${e.source_url ? `：${e.source_url}` : ""}`.slice(0, 300));
  return lines;
}
