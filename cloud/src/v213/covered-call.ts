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
}
export interface CoveredCallCycle {
  ticker: string; strategy: "COVERED_CALL"; expiry: string; dte: number; spot: number; currency: "USD" | "SEK";
  multiplier: 100; quote_basis: "delayed"; timestamp: string; source: string; provenance: string; rights_status: string;
  suggestions: CoveredCallSuggestion[];
}

const finite = (value: unknown): value is number => typeof value === "number" && Number.isFinite(value);
const close = (value: number, expected: number) => Math.abs(value - expected) <= Math.max(1e-4, Math.abs(expected) * 1e-3);

/** A strictly validated cycle, or null (the caller then shows the option as unavailable). */
export function validateCoveredCallCycle(raw: unknown): CoveredCallCycle | null {
  if (!raw || typeof raw !== "object") return null;
  const cycle = raw as Record<string, any>;
  if (cycle.strategy !== "COVERED_CALL" || (cycle.currency !== "USD" && cycle.currency !== "SEK") || cycle.multiplier !== 100
    || cycle.quote_basis !== "delayed" || typeof cycle.ticker !== "string" || !/^[A-Z0-9.\- ]{1,16}$/.test(cycle.ticker)
    || typeof cycle.expiry !== "string" || !/^\d{4}-\d{2}-\d{2}$/.test(cycle.expiry) || !Number.isInteger(cycle.dte)
    || cycle.dte < 1 || cycle.dte > 60 || !finite(cycle.spot) || cycle.spot <= 0 || typeof cycle.source !== "string"
    || typeof cycle.provenance !== "string" || !cycle.provenance.startsWith("https://") || typeof cycle.timestamp !== "string"
    || !Array.isArray(cycle.suggestions) || cycle.suggestions.length < 1 || cycle.suggestions.length > 2) return null;
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
  }
  if (cycle.suggestions.length === 2 && !(cycle.suggestions[0].strike > cycle.suggestions[1].strike)) return null;
  return cycle as CoveredCallCycle;
}

const money = (value: number, currency: string) => currency === "USD" ? `$${value.toFixed(2)}` : `${value.toFixed(2)} ${currency}`;
const pct = (value: number, digits = 1) => `${(value * 100).toFixed(digits)}%`;
const ROLE = {
  HIGH_STRIKE: ["建議一：高履約價（不易被賣掉）", "在年化權利金至少 6% 的前提下選最高履約價；股價需上漲超過右側幅度才會被指派。"],
  BALANCED: ["建議二：平衡型（收較多權利金）", "履約價較低、權利金較高；被指派機率也較高。"],
} as const;

function suggestionSection(cycle: CoveredCallCycle, item: CoveredCallSuggestion) {
  const [title, note] = ROLE[item.role];
  const assignment = item.delta === null ? "被指派機率參考：交易所未提供 Delta" : `被指派機率參考：Delta ${item.delta.toFixed(2)}（約 ${Math.round(item.delta * 100)}%，模型值）`;
  return section(title, [
    uiBox([statTile("履約價", money(item.strike, cycle.currency), undefined, `距現價 +${pct(item.upside_to_strike)}`),
      statTile("建議賣出限價", money(item.limit_price, cycle.currency), undefined, `Bid ${money(item.bid, cycle.currency)}／Ask ${money(item.ask, cycle.currency)}`)],
      { layout: "horizontal", spacing: "sm" }),
    uiBox([statTile("每口權利金", money(item.premium_per_contract, cycle.currency), undefined, "100 股／口"),
      statTile("年化收益", pct(item.annualized_yield), undefined, `期間 ${pct(item.period_yield, 2)}`)], { layout: "horizontal", spacing: "sm" }),
    meter(Math.min(1, item.upside_to_strike / 0.5) * 100),
    uiText(assignment, "xs", T.ink),
    uiText(`流動性：OI ${item.oi ?? "未提供"}｜成交量 ${item.volume ?? "未提供"}｜價差占中價 ${item.spread_pct === null ? "未提供" : pct(item.spread_pct, 0)}`, "xxs", T.muted),
    footnote(note),
  ], item.role === "HIGH_STRIKE" ? "key" : "detail");
}

export function buildCoveredCallMessages(cycle: CoveredCallCycle, periodLabel: string, style: "flex" | "text"): LineOutboundMessage[] {
  if (style === "text") {
    const lines = [
      `【備兌買權建議｜${cycle.ticker} ${periodLabel}】到期 ${cycle.expiry}（${cycle.dte} 天）｜現價 ${money(cycle.spot, cycle.currency)}`,
      ...cycle.suggestions.map(item => [
        ROLE[item.role][0],
        `履約價 ${money(item.strike, cycle.currency)}（距現價 +${pct(item.upside_to_strike)}）｜建議賣出限價 ${money(item.limit_price, cycle.currency)}（Bid ${money(item.bid, cycle.currency)}／Ask ${money(item.ask, cycle.currency)}）`,
        `每口權利金 ${money(item.premium_per_contract, cycle.currency)}｜期間收益 ${pct(item.period_yield, 2)}｜年化 ${pct(item.annualized_yield)}｜Delta ${item.delta === null ? "未提供" : item.delta.toFixed(2)}`,
      ].join("\n")),
      `前提：持有 100 股、賣出 1 口買權；股價超過履約價時可能被指派，上漲收益封頂於履約價。`,
      `來源：${sourceZh(cycle.source)}（延遲報價，${cycle.timestamp}）${cycle.provenance}`,
      "公開行情觀察，非個人化投資建議；本服務不下單。",
    ];
    const messages: LineOutboundMessage[] = [{ type: "text", text: lines.join("\n").slice(0, 4900) }];
    assertLineMessages(messages);
    return messages;
  }
  const bubble = {
    type: "bubble", size: "mega",
    header: productHeader(`備兌買權建議 · ${periodLabel} · 延遲報價`, `${cycle.ticker}｜到期 ${cycle.expiry}`, [
      uiBox([chip(`${cycle.dte} 天`), chip(`現價 ${money(cycle.spot, cycle.currency)}`)], { layout: "horizontal", spacing: "sm" }),
    ]),
    body: uiBox([
      ...cycle.suggestions.map(item => suggestionSection(cycle, item)),
      footnote("前提：持有 100 股、賣出 1 口買權收取權利金；股價超過履約價可能被指派，上漲收益封頂於履約價。限價：價差 25% 內取中間價，較寬時取 Bid＋四分之一價差。"),
    ], { paddingAll: "lg", spacing: "md" }),
    footer: uiBox([
      footnote(`來源：${sourceZh(cycle.source)}，${cycle.timestamp}`),
      footnote("公開行情觀察，非個人化投資建議；本服務不下單。"),
      menuAction("期權策略教學", "期權教學"),
      menuAction("回功能選單", "選單"),
    ], footerStyle),
  };
  const messages: LineOutboundMessage[] = [{ type: "flex", altText: `備兌買權建議：${cycle.ticker} ${cycle.expiry}`,
    contents: { type: "carousel", contents: [bubble] } }];
  assertLineMessages(messages);
  return messages;
}
