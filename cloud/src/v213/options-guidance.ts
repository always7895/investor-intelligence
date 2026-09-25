import { assertLineMessages, type LineOutboundMessage } from "../line-messages";
import { LINE_THEME as T, divider, footnote, kpiTile, labelValue, panel, productHeader, uiBox, uiText } from "./line-theme";

/**
 * Options order guidance & position sizing (AGENTS.md "Recommendations &
 * Options Guidance" authority): explicit, actionable, data-grounded order
 * parameters plus Serenity-style position frameworks. These outputs are
 * DATA OBSERVATIONS AND ORDER PARAMETERS - they never mutate a broker and
 * they never execute a trade.
 */


export type OptionsStrategy = "covered_call" | "cash_secured_put";
export type DeltaAssessment = "TARGET_CONSERVATIVE_BAND" | "TOO_AGGRESSIVE" | "TOO_FAR_OTM" | "UNAVAILABLE";
export type LiquidityStatus = "QUALIFIED" | "LOW_VOLUME" | "LOW_OI" | "WIDE_SPREAD";
export type SizingArchetype = "STEADY_CORE_COMPOUNDER" | "BOTTLENECK_CHOKEPOINT" | "SPECULATIVE_HIGH_DILUTION";

export const CONSERVATIVE_DELTA_BAND: readonly [number, number] = [0.2, 0.3];
export const LIQUIDITY_MIN_OPEN_INTEREST = 100;
export const LIQUIDITY_MIN_VOLUME = 50;
export const LIQUIDITY_MAX_SPREAD_RATIO = 0.1;
export const CASH_RESERVE_MIN_PCT = 20;
export const MAX_ALLOCATION_CAP_PCT: Record<SizingArchetype, number> = {
  STEADY_CORE_COMPOUNDER: 12,
  BOTTLENECK_CHOKEPOINT: 4,
  SPECULATIVE_HIGH_DILUTION: 2,
};

export const CAVEAT_DISCLAIMER =
  "數據觀察與訂單參數、非券商執行：本卡僅提供基於認證快照的掛單參數參考（委託類型／限價區間／到期與DTE／Delta／流動性）。實際掛單、成交、履約風險由操作人在券商端獨立完成；不構成投資建議 期權可能損失全部權利金。" +
  " (Data observation & limit-order parameters, NOT broker execution or a recommendation. Place and manage the order at your broker; options can lose all premium.)";

export interface LimitReferenceBand {
  lower: number;
  upper: number;
  recommended_limit: number;
}

export interface OptionsOrderGuidance {
  ticker: string;
  strategy: OptionsStrategy;
  underlying_price: number | null;
  strike: number;
  expiry: string;
  dte: number;
  delta: number | null;
  delta_assessment: DeltaAssessment;
  order_type: "LIMIT";
  bid: number;
  mid: number;
  ask: number;
  limit_reference_band: LimitReferenceBand;
  annualized_yield_pct: number | null;
  liquidity_status: LiquidityStatus;
  caveat_disclaimer: string;
}

export interface PositionSizingFramework {
  archetype: SizingArchetype;
  max_allocation_cap_pct: number;
  cash_reserve_requirement_pct: number;
  tranche_pacing: string;
  financing_risk_overlay: string;
}

export interface GenerateOptionsOrderGuidanceParams {
  ticker: string;
  strategy: OptionsStrategy;
  underlyingPrice: number | null;
  strike: number;
  expiry: string;
  dte: number;
  delta: number | null;
  bid: number;
  mid: number;
  ask: number;
  openInterest: number;
  volume: number;
}

function requireFinitePositive(label: string, value: number): number {
  if (!Number.isFinite(value) || value <= 0) {
    throw new Error(`OPTIONS_GUIDANCE_INVALID_${label}`);
  }
  return value;
}

const STRATEGY_LABEL: Record<OptionsStrategy, string> = {
  covered_call: "備兌開倉 Covered Call",
  cash_secured_put: "現金擔保賣沽 Cash-Secured Put",
};

const DELTA_LABEL: Record<DeltaAssessment, string> = {
  TARGET_CONSERVATIVE_BAND: "保守目標區 0.20-0.30",
  TOO_AGGRESSIVE: "偏激進 (>0.30)",
  TOO_FAR_OTM: "偏遠虛値 (<0.20)",
  UNAVAILABLE: "Delta 未提供",
};

const LIQUIDITY_LABEL: Record<LiquidityStatus, string> = {
  QUALIFIED: "流動性充足 Qualified",
  LOW_VOLUME: "成交量偏低 Low Volume (<50)",
  LOW_OI: "未平倉偏低 Low OI (<100)",
  WIDE_SPREAD: "價差偏寬 Wide Spread (>10% of mid)",
};

const ARCHETYPE_LABEL: Record<SizingArchetype, string> = {
  STEADY_CORE_COMPOUNDER: "穩定核心複利型 Steady Core Compounder",
  BOTTLENECK_CHOKEPOINT: "瓶頸扼點型 Bottleneck Chokepoint",
  SPECULATIVE_HIGH_DILUTION: "高稀釋投機型 Speculative High-Dilution",
};

export function assessDeltaBand(delta: number | null): DeltaAssessment {
  if (delta === null || !Number.isFinite(delta)) return "UNAVAILABLE";
  const [low, high] = CONSERVATIVE_DELTA_BAND;
  if (delta > high) return "TOO_AGGRESSIVE";
  if (delta < low) return "TOO_FAR_OTM";
  return "TARGET_CONSERVATIVE_BAND";
}

export function assessLiquidity(openInterest: number, volume: number, bid: number, mid: number, ask: number): LiquidityStatus {
  if (!Number.isFinite(openInterest) || openInterest < LIQUIDITY_MIN_OPEN_INTEREST) return "LOW_OI";
  if (!Number.isFinite(volume) || volume < LIQUIDITY_MIN_VOLUME) return "LOW_VOLUME";
  const spread = ask - bid;
  if (!Number.isFinite(spread) || spread > LIQUIDITY_MAX_SPREAD_RATIO * mid) return "WIDE_SPREAD";
  return "QUALIFIED";
}

export function generateOptionsOrderGuidance(params: GenerateOptionsOrderGuidanceParams): OptionsOrderGuidance {
  const ticker = String(params.ticker ?? "").trim().toUpperCase();
  if (!/^[A-Z0-9][A-Z0-9.\-]{0,11}$/.test(ticker)) {
    throw new Error("OPTIONS_GUIDANCE_INVALID_TICKER");
  }
  const strike = requireFinitePositive("STRIKE", params.strike);
  const dte = requireFinitePositive("DTE", params.dte);
  if (!Number.isInteger(dte)) throw new Error("OPTIONS_GUIDANCE_INVALID_DTE");
  const bid = requireFinitePositive("BID", params.bid);
  const ask = requireFinitePositive("ASK", params.ask);
  const mid = requireFinitePositive("MID", params.mid);
  const expiry = String(params.expiry ?? "").trim();
  if (!/^\d{4}-\d{2}-\d{2}$/.test(expiry)) throw new Error("OPTIONS_GUIDANCE_INVALID_EXPIRY");
  const strategy: OptionsStrategy = (params.strategy === "covered_call" || params.strategy === "cash_secured_put")
    ? params.strategy
    : (() => { throw new Error("OPTIONS_GUIDANCE_INVALID_STRATEGY"); })();
  const underlying = params.underlyingPrice === null
    ? null
    : requireFinitePositive("UNDERLYING_PRICE", params.underlyingPrice);
  const delta: number | null = params.delta === null
    ? null
    : params.delta;
  if (delta !== null && (!Number.isFinite(delta) || delta <= 0 || delta >= 1)) {
    throw new Error("OPTIONS_GUIDANCE_INVALID_DELTA");
  }

  // Sell limit recommendation sits at the fair (mid) price inside the quoted
  // book; market orders are strictly discouraged when selling premium.
  return {
    ticker,
    strategy,
    underlying_price: underlying,
    strike,
    expiry,
    dte,
    delta,
    delta_assessment: assessDeltaBand(delta),
    order_type: "LIMIT",
    bid,
    mid,
    ask,
    limit_reference_band: { lower: bid, upper: ask, recommended_limit: mid },
    // premium sold at mid (fair value): (premium/strike) * (365/dte) * 100
    annualized_yield_pct: (mid / strike) * (365 / dte) * 100,
    liquidity_status: assessLiquidity(params.openInterest, params.volume, bid, mid, ask),
    caveat_disclaimer: CAVEAT_DISCLAIMER,
  };
}

export function generatePositionSizingFramework(archetype: SizingArchetype): PositionSizingFramework {
  const cap = MAX_ALLOCATION_CAP_PCT[archetype];
  if (cap === undefined) throw new Error("POSITION_SIZING_INVALID_ARCHETYPE");
  return {
    archetype,
    max_allocation_cap_pct: cap,
    cash_reserve_requirement_pct: CASH_RESERVE_MIN_PCT,
    tranche_pacing: "3-4 tranches across 6-18 months (分批建倉：6-18 個月內 3-4 批)",
    financing_risk_overlay: "-50% cap penalty when a material financing overhang exists (重大融資懸崖時，配置上限再减半)",
  };
}

function fmt(n: number): string {
  return n.toFixed(2);
}

export function buildOptionsGuidanceText(guidance: OptionsOrderGuidance): string {
  const band = guidance.limit_reference_band;
  return [
    `【期權掛單參數｜${guidance.ticker}｜${STRATEGY_LABEL[guidance.strategy]}】`,
    `標的價格：${guidance.underlying_price === null ? "N/A" : fmt(guidance.underlying_price)}；Strike ${fmt(guidance.strike)}；到期 ${guidance.expiry}（DTE ${guidance.dte}）`,
    `Delta：${guidance.delta === null ? "N/A" : fmt(guidance.delta)}（${DELTA_LABEL[guidance.delta_assessment]}）；保守目標區 0.20-0.30`,
    `委託類型：${guidance.order_type}（建議避免市場單）`,
    `限價參考帶：Bid ${fmt(guidance.bid)} / Mid ${fmt(guidance.mid)} / Ask ${fmt(guidance.ask)}；建議掛單 ${fmt(band.recommended_limit)}（參考區間 ${fmt(band.lower)}-${fmt(band.upper)}）`,
    guidance.annualized_yield_pct === null
      ? "Annualized yield: N/A (cannot be calculated from certified data)"
      : `Annualized yield ${guidance.annualized_yield_pct.toFixed(1)}% (premium = mid; premium/strike x 365/dte)`,
    `流動性：${LIQUIDITY_LABEL[guidance.liquidity_status]}`,
    guidance.caveat_disclaimer,
  ].join("\n");
}

export function buildOptionsGuidanceFlexBubble(guidance: OptionsOrderGuidance): LineOutboundMessage {
  const band = guidance.limit_reference_band;
  const yieldText = guidance.annualized_yield_pct === null
    ? "Annualized yield: N/A"
    : `Annualized yield: ${guidance.annualized_yield_pct.toFixed(1)}%`;
  const msg: LineOutboundMessage = {
    type: "flex",
    altText: `期權掛單參數：${guidance.ticker} ${guidance.expiry} Strike ${fmt(guidance.strike)}（${guidance.strategy}；LIMIT ${fmt(band.recommended_limit)}）`,
    contents: {
      type: "carousel",
      contents: [{
        type: "bubble", size: "mega",
        header: productHeader("韭菜守護者 · 期權掛單參數 / Order parameters", guidance.ticker, [
          uiText(STRATEGY_LABEL[guidance.strategy], "sm", T.onDarkMuted),
        ]),
        body: uiBox([
          uiBox([
            kpiTile("建議限價 / Limit", fmt(band.recommended_limit), T.ink),
            kpiTile("Strike", fmt(guidance.strike), T.ink),
            kpiTile("DTE", String(guidance.dte), T.ink),
          ], { layout: "horizontal", spacing: "sm" }),
          labelValue("到期 / Expiry", `${guidance.expiry}（DTE ${guidance.dte}）｜標的價格 ${guidance.underlying_price === null ? "N/A" : fmt(guidance.underlying_price)}`),
          labelValue("Delta", `${guidance.delta === null ? "N/A" : fmt(guidance.delta)}｜${DELTA_LABEL[guidance.delta_assessment]}（目標 0.20-0.30）`),
          divider(),
          labelValue("委託與報價 / Order & quotes", `委託 ${guidance.order_type}｜Bid ${fmt(guidance.bid)} / Mid ${fmt(guidance.mid)} / Ask ${fmt(guidance.ask)}`),
          labelValue("限價區間 / Limit band", `Band ${fmt(band.lower)}-${fmt(band.upper)}｜建議避免市場單`),
          labelValue("收益 / Yield", yieldText, { weight: "bold" }),
          panel([
            uiText(`流動性：${LIQUIDITY_LABEL[guidance.liquidity_status]}`, "sm", T.ink, { weight: "bold" }),
            footnote(guidance.caveat_disclaimer),
          ], "caution"),
        ], { paddingAll: "xl", spacing: "lg", backgroundColor: T.paper }),
      }],
    },
  };
  assertLineMessages([msg]);
  return msg;
}

export function buildPositionSizingText(sizing: PositionSizingFramework, ticker: string): string {
  return [
    `【倉位配置框架｜${ticker}｜${ARCHETYPE_LABEL[sizing.archetype]}】`,
    `單一只標的最大配置上限：${sizing.max_allocation_cap_pct}%`,
    `現金儲備要求：>= ${sizing.cash_reserve_requirement_pct}%（緩衝 buffer，任何時點不得低於下限）`,
    `建倉節奏：${sizing.tranche_pacing}`,
    `融資風險疊層：${sizing.financing_risk_overlay}`,
    CAVEAT_DISCLAIMER,
  ].join("\n");
}

export function buildPositionSizingFlexBubble(sizing: PositionSizingFramework, ticker: string): LineOutboundMessage {
  const msg: LineOutboundMessage = {
    type: "flex",
    altText: `倉位配置框架：${ticker}｜上限 ${sizing.max_allocation_cap_pct}%｜現金儲備 >= ${sizing.cash_reserve_requirement_pct}%`,
    contents: {
      type: "carousel",
      contents: [{
        type: "bubble", size: "mega",
        header: productHeader("韭菜守護者 · 倉位配置框架 / Position sizing", ticker, [
          uiText(ARCHETYPE_LABEL[sizing.archetype], "sm", T.onDarkMuted),
        ]),
        body: uiBox([
          uiBox([
            kpiTile("單一標的上限 / Cap", `${sizing.max_allocation_cap_pct}%`, T.ink),
            kpiTile("現金儲備 / Cash", `>= ${sizing.cash_reserve_requirement_pct}%`, T.ink),
          ], { layout: "horizontal", spacing: "sm" }),
          labelValue("建倉節奏 / Pacing", sizing.tranche_pacing),
          divider(),
          labelValue("融資風險疊層 / Financing overlay", sizing.financing_risk_overlay),
          panel([footnote(CAVEAT_DISCLAIMER)], "caution"),
        ], { paddingAll: "xl", spacing: "lg", backgroundColor: T.paper }),
      }],
    },
  };
  assertLineMessages([msg]);
  return msg;
}