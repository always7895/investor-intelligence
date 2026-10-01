/** Covered-call sell suggestions (operator 2026-09-26): for a holder of 100 shares, two strikes that collect premium
 * while keeping the strike as high as possible so the shares are not called away. Produced hourly by
 * scripts/build_market_quotes_options.py from delayed public option chains and sealed in `v213:options:v2`.
 * Observation only: the bot never places an order. Mirror of validate_covered_call_cycle (Python). */
import { assertLineMessages, type LineOutboundMessage } from "../line-messages";
import { sourceZh } from "./source-labels";
import {
  LINE_THEME as T, chip, footerStyle, footnote, menuAction, meter, productHeader, section, statTile, uiBox, uiText,
} from "./line-theme";

export interface CoveredCallSuggestion {
  role: "HIGH_STRIKE" | "BALANCED"; strike: number; bid: number; ask: number; mid: number; limit_price: number;
  premium_per_contract: number; period_yield: number; annualized_yield: number; upside_to_strike: number;
  delta: number | null; iv: number | null; oi: number | null; volume: number | null; spread_pct: number | null;
  /** QUOTED: the venue's delta; QUOTED_IV: Black-Scholes from the quoted implied volatility; QUOTE_IMPLIED: Black-Scholes
   * from the volatility implied by the strike's own bid/ask mid (chains without Greeks). */
  delta_basis?: "QUOTED" | "QUOTED_IV" | "QUOTE_IMPLIED" | null;
}
export interface CoveredCallCycle {
  ticker: string; strategy: "COVERED_CALL"; expiry: string; dte: number; spot: number; currency: "USD" | "SEK";
  multiplier: 100; quote_basis: "delayed"; timestamp: string; source: string; provenance: string; rights_status: string;
  suggestions: CoveredCallSuggestion[];
}

const finite = (value: unknown): value is number => typeof value === "number" && Number.isFinite(value);
const DELTA_BASES = new Set(["QUOTED", "QUOTED_IV", "QUOTE_IMPLIED"]);
/** The high strike's assignment cap (scripts/build_market_quotes_options.py MAX_HIGH_STRIKE_DELTA). */
const MAX_HIGH_STRIKE_DELTA = 0.20;
const close = (value: number, expected: number) => Math.abs(value - expected) <= Math.max(1e-4, Math.abs(expected) * 1e-3);

const UTC_INSTANT_RE = /^\d{4}-(?:0[1-9]|1[0-2])-(?:0[1-9]|[12]\d|3[01])T(?:[01]\d|2[0-3]):[0-5]\d:[0-5]\d(?:\.\d+)?Z$/;

export function isValidUtcIsoInstant(raw: unknown): raw is string {
  if (typeof raw !== "string" || !UTC_INSTANT_RE.test(raw)) return false;
  const ms = Date.parse(raw);
  if (!Number.isFinite(ms)) return false;
  const iso = new Date(ms).toISOString();
  return raw.includes(".") ? iso === raw : iso === raw.replace("Z", ".000Z");
}

/** Producer DTE buckets (scripts/build_market_quotes_options.py): the selected cycle window a row must fall in. Not a
 * third-Friday calendar classification; the producer's own weekly/monthly DTE ranges. */
const PERIOD_DTE_BUCKETS: Record<string, [number, number]> = { weekly: [3, 14], monthly: [21, 45] };

/** UTC midnight epoch ms of a YYYY-MM-DD calendar date, or null for an impossible date (e.g. 2026-02-30) that the shape
 * regex alone would admit. */
function parseCalendarDateUtcMidnight(raw: string): number | null {
  const ms = Date.parse(`${raw}T00:00:00Z`);
  if (!Number.isFinite(ms)) return null;
  return new Date(ms).toISOString().slice(0, 10) === raw ? ms : null;
}

/** A strictly validated cycle, or null (the caller then shows the option as unavailable). */
export function validateCoveredCallCycle(raw: unknown, now?: number, documentGeneratedAt?: string, period?: "weekly" | "monthly"): CoveredCallCycle | null {
  if (!raw || typeof raw !== "object") return null;
  const cycle = raw as Record<string, any>;
  if (cycle.strategy !== "COVERED_CALL" || (cycle.currency !== "USD" && cycle.currency !== "SEK") || cycle.multiplier !== 100
    || cycle.quote_basis !== "delayed" || typeof cycle.ticker !== "string" || !/^[A-Z0-9.\- ]{1,16}$/.test(cycle.ticker)
    || typeof cycle.expiry !== "string" || !/^\d{4}-\d{2}-\d{2}$/.test(cycle.expiry) || !Number.isInteger(cycle.dte)
    || cycle.dte < 1 || cycle.dte > 60 || !finite(cycle.spot) || cycle.spot <= 0 || typeof cycle.source !== "string"
    || typeof cycle.provenance !== "string" || !cycle.provenance.startsWith("https://")
    || !isValidUtcIsoInstant(cycle.timestamp)
    || !Array.isArray(cycle.suggestions) || cycle.suggestions.length < 1 || cycle.suggestions.length > 2) return null;

  const rowTime = Date.parse(cycle.timestamp);
  if (typeof now === "number" && Number.isFinite(now)) {
    // Worker 6h maximum observation age
    if (now - rowTime > 6 * 3600_000) return null;
    // Worker <=5min clock tolerance into future
    if (rowTime - now > 300_000) return null;
  }
  if (typeof documentGeneratedAt === "string" && documentGeneratedAt.length > 0) {
    const docTime = Date.parse(documentGeneratedAt);
    if (Number.isFinite(docTime) && rowTime - docTime > 300_000) return null;
  }

  // Selected cycle window: the row's DTE must fall in the requested period's producer bucket (weekly 3-14 / monthly
  // 21-45). No period substitution and no third-Friday relabelling of producer DTE buckets.
  if (period) {
    const bucket = PERIOD_DTE_BUCKETS[period];
    if (bucket && !(cycle.dte >= bucket[0] && cycle.dte <= bucket[1])) return null;
  }

  // Real-calendar expiry beyond the shape regex: reject impossible dates, expired contracts and calendar-DTE mismatch.
  const expiryMs = parseCalendarDateUtcMidnight(cycle.expiry);
  if (expiryMs === null) return null;
  if (typeof now === "number" && Number.isFinite(now)) {
    const nowDateMs = Date.parse(`${new Date(now).toISOString().slice(0, 10)}T00:00:00Z`);
    const dayDiff = Math.round((expiryMs - nowDateMs) / 86_400_000);
    if (dayDiff < 0) return null;                        // expired contract
    if (Math.abs(dayDiff - cycle.dte) > 1) return null;  // calendar-DTE inconsistent (+/-1 tolerance, mirrors Python)
  }

  const roles = cycle.suggestions.map((item: any) => item?.role).join(",");
  if (roles !== "HIGH_STRIKE" && roles !== "HIGH_STRIKE,BALANCED") return null;
  for (const item of cycle.suggestions as any[]) {
    if (!["strike", "bid", "ask", "mid", "limit_price", "premium_per_contract", "period_yield", "annualized_yield", "upside_to_strike"]
      .every(key => finite(item[key]))) return null;
    if (!(item.strike > cycle.spot) || !(item.bid > 0 && item.bid <= item.ask) || !close(item.mid, (item.bid + item.ask) / 2)
      || item.limit_price < item.bid - 1e-9 || item.limit_price > item.mid + 1e-9) return null;
    if (!close(item.premium_per_contract, item.limit_price * 100) || !close(item.period_yield, item.limit_price / cycle.spot)
      || !close(item.annualized_yield, item.limit_price / cycle.spot * 365 / cycle.dte)
      || !close(item.upside_to_strike, item.strike / cycle.spot - 1)) return null;
    if (item.delta !== null && item.delta !== undefined && !(finite(item.delta) && item.delta >= 0 && item.delta <= 1)) return null;
    if (item.role === "HIGH_STRIKE" && !(finite(item.delta) && item.delta <= MAX_HIGH_STRIKE_DELTA)) return null;
    if (item.delta_basis !== null && item.delta_basis !== undefined && !DELTA_BASES.has(item.delta_basis)) return null;
    if (item.iv !== null && item.iv !== undefined && !(finite(item.iv) && item.iv > 0)) return null;
    // Optional supplied liquidity/spread fields must be a finite, non-negative number when present (amendment-02):
    // reject nonfinite (JSON 1e309 -> Infinity), wrong type (bool/string/array/object) and negatives, so a malformed
    // value can never reach text/Flex; a legitimate null/missing stays unknown (未提供).
    for (const key of ["oi", "volume", "spread_pct"] as const) {
      const value = item[key];
      if (value !== null && value !== undefined && !(finite(value) && value >= 0)) return null;
    }
  }
  if (cycle.suggestions.length === 2 && !(cycle.suggestions[0].strike > cycle.suggestions[1].strike)) return null;
  return cycle as CoveredCallCycle;
}

const money = (value: number, currency: string) => currency === "USD" ? `$${value.toFixed(2)}` : `${value.toFixed(2)} ${currency}`;
const pct = (value: number, digits = 1) => `${(value * 100).toFixed(digits)}%`;
/** Spread as a share of mid, or an explicit unknown when the producer did not supply it (never NaN). */
const spreadZh = (value: number | null | undefined) => typeof value === "number" && Number.isFinite(value) ? pct(value, 0) : "未提供";
/** Open interest / traded volume as an integer count, or an explicit unknown for absent or non-finite values (defence in
 * depth: the validator already rejects nonfinite optional fields, so this never renders NaN/Infinity). */
const countZh = (value: number | null | undefined) => typeof value === "number" && Number.isFinite(value) ? String(value) : "未提供";
/** The delta basis label shared by text and flex, or null when there is no delta to explain. */
function deltaBasisZh(item: CoveredCallSuggestion): string | null {
  if (item.delta === null || item.delta === undefined) return null;
  if (item.delta_basis === "QUOTED") return "交易所提供";
  if (item.delta_basis === "QUOTED_IV") return item.iv ? `模型值，依報價隱含波動率 ${pct(item.iv, 0)}` : "模型值，依報價隱含波動率";
  if (item.delta_basis === "QUOTE_IMPLIED") return item.iv ? `模型值，波動率由買賣報價反推 ${pct(item.iv, 0)}` : "模型值，由買賣報價反推";
  return "模型值";
}
const ROLE = {
  HIGH_STRIKE: ["建議一：高履約價（不易被賣掉）", "在年化權利金至少 6% 的前提下選最高履約價；股價需上漲超過右側幅度才會被指派。"],
  BALANCED: ["建議二：平衡型（收較多權利金）", "履約價較低、權利金較高；被指派機率也較高。"],
} as const;

function assignmentText(item: CoveredCallSuggestion): string {
  if (item.delta === null || item.delta === undefined) return "被指派機率參考：報價不足以推算 Delta";
  const basis = deltaBasisZh(item);
  return `被指派機率參考：Delta ${item.delta.toFixed(2)}（約 ${Math.round(item.delta * 100)}%${basis ? `，${basis}` : ""}）`;
}

function suggestionSection(cycle: CoveredCallCycle, item: CoveredCallSuggestion) {
  const [title, note] = ROLE[item.role];
  const assignment = assignmentText(item);
  return section(title, [
    uiBox([statTile("履約價", money(item.strike, cycle.currency), undefined, `距現價 +${pct(item.upside_to_strike)}`),
      statTile("建議賣出限價", money(item.limit_price, cycle.currency), undefined, `Bid ${money(item.bid, cycle.currency)}／中價 ${money(item.mid, cycle.currency)}／Ask ${money(item.ask, cycle.currency)}`)],
      { layout: "horizontal", spacing: "sm" }),
    uiBox([statTile("每口權利金", money(item.premium_per_contract, cycle.currency), undefined, "100 股／口"),
      statTile("年化收益", pct(item.annualized_yield), undefined, `期間 ${pct(item.period_yield, 2)}`)], { layout: "horizontal", spacing: "sm" }),
    meter(Math.min(1, item.upside_to_strike / 0.5) * 100),
    uiText(assignment, "xs", T.ink),
    uiText(`流動性：OI ${countZh(item.oi)}｜成交量 ${countZh(item.volume)}｜價差占中價 ${spreadZh(item.spread_pct)}`, "xxs", T.muted),
    footnote(note),
  ], item.role === "HIGH_STRIKE" ? "key" : "detail");
}

export function buildCoveredCallMessages(cycle: CoveredCallCycle, periodLabel: string, style: "flex" | "text"): LineOutboundMessage[] {
  if (style === "text") {
    const lines = [
      `【備兌買權建議｜${cycle.ticker} ${periodLabel}】到期 ${cycle.expiry}（${cycle.dte} 天）｜現價 ${money(cycle.spot, cycle.currency)}（計價 ${cycle.currency}）`,
      ...cycle.suggestions.map(item => [
        ROLE[item.role][0],
        `履約價 ${money(item.strike, cycle.currency)}（距現價 +${pct(item.upside_to_strike)}）｜建議賣出限價 ${money(item.limit_price, cycle.currency)}（Bid ${money(item.bid, cycle.currency)}／中價 ${money(item.mid, cycle.currency)}／Ask ${money(item.ask, cycle.currency)}）`,
        `每口權利金 ${money(item.premium_per_contract, cycle.currency)}｜期間收益 ${pct(item.period_yield, 2)}｜年化 ${pct(item.annualized_yield)}｜Delta ${item.delta === null || item.delta === undefined ? "未提供" : `${item.delta.toFixed(2)}${deltaBasisZh(item) ? `（${deltaBasisZh(item)}）` : ""}`}`,
        `流動性：OI ${countZh(item.oi)}｜成交量 ${countZh(item.volume)}｜價差占中價 ${spreadZh(item.spread_pct)}`,
      ].join("\n")),
      `前提：持有 100 股、賣出 1 口買權；股價超過履約價時可能被指派，上漲收益封頂於履約價。`,
      `來源：${sourceZh(cycle.source)}（延遲報價，擷取時間 ${cycle.timestamp}；來源報價時間未提供）${cycle.provenance}`,
      "公開行情觀察，非個人化投資建議；延遲／非即時可執行；年化收益非保證報酬；正股仍承擔下跌風險；本服務不下單。",
    ];
    const messages: LineOutboundMessage[] = [{ type: "text", text: lines.join("\n").slice(0, 4900) }];
    assertLineMessages(messages);
    return messages;
  }
  const bubble = {
    type: "bubble", size: "mega",
    header: productHeader(`備兌買權建議 · ${periodLabel} · 延遲報價`, `${cycle.ticker}｜到期 ${cycle.expiry}`, [
      uiBox([chip(`${cycle.dte} 天`), chip(`現價 ${money(cycle.spot, cycle.currency)}`), chip(`計價 ${cycle.currency}`)], { layout: "horizontal", spacing: "sm" }),
    ]),
    body: uiBox([
      ...cycle.suggestions.map(item => suggestionSection(cycle, item)),
      footnote("前提：持有 100 股、賣出 1 口買權收取權利金；股價超過履約價可能被指派，上漲收益封頂於履約價。限價：價差 25% 內取中間價，較寬時取 Bid＋四分之一價差。"),
    ], { paddingAll: "lg", spacing: "md" }),
    footer: uiBox([
      footnote(`來源：${sourceZh(cycle.source)}，擷取時間 ${cycle.timestamp}（來源報價時間未提供）`),
      footnote(`資料出處：${cycle.provenance}`),
      footnote("公開行情觀察，非個人化投資建議；延遲／非即時可執行；年化收益非保證報酬；正股仍承擔下跌風險；本服務不下單。"),
      menuAction("期權策略教學", "期權教學"),
      menuAction("回功能選單", "選單"),
    ], footerStyle),
  };
  const messages: LineOutboundMessage[] = [{ type: "flex", altText: `備兌買權建議：${cycle.ticker} ${cycle.expiry}`,
    contents: { type: "carousel", contents: [bubble] } }];
  assertLineMessages(messages);
  return messages;
}
