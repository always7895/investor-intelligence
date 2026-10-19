/** Covered-call sell suggestions (operator 2026-09-26; middle tier and current-week weekly 2026-10-11): for a holder of 100
 * shares, up to three strikes (HIGH_STRIKE, an optional MIDDLE, BALANCED) that collect premium while keeping the strike as high
 * as possible so the shares are not called away. Produced hourly by
 * scripts/build_market_quotes_options.py from delayed public option chains and sealed in `v213:options:v2`.
 * Observation only: the bot never places an order. Mirror of validate_covered_call_cycle (Python). */
import { assertLineMessages, type LineOutboundMessage } from "../line-messages";
import { sourceZh } from "./source-labels";
import {
  effectiveDays, dayMs, exchangeDate, expiryDayOpen, MONTHLY_DTE_BUCKET, SHORT_DTE_NOTICE_MAX, usRegularSessionOpen, WEEKLY_DTE_BUCKET, weeklyWeekFor,
  type WeeklyWeek,
} from "./option-recommendation-rules";
import { admitPublicOption, OptionRightsNotAdmittedError } from "./public-options-admission";
import {
  LINE_THEME as T, altSummary, bulletRow, chip, clampText, detailsButton, disclosureLine, footerStyle, footnote, heroStat, kvRow, menuAction, meter, productHeader, section, uiBox, uiText,
} from "./line-theme";

export interface CoveredCallSuggestion {
  role: "HIGH_STRIKE" | "MIDDLE" | "BALANCED"; strike: number; bid: number; ask: number; mid: number; limit_price: number;
  premium_per_contract: number; period_yield: number; annualized_yield: number; upside_to_strike: number;
  delta: number | null; iv: number | null; oi: number | null; volume: number | null; spread_pct: number | null;
  /** QUOTED: the venue's delta; QUOTED_IV: Black-Scholes from the quoted implied volatility; QUOTE_IMPLIED: Black-Scholes
   * from the volatility implied by the strike's own bid/ask mid (chains without Greeks). */
  delta_basis?: "QUOTED" | "QUOTED_IV" | "QUOTE_IMPLIED" | null;
}
/** Quote basis of the previous-session carry-forward (scripts/options_carry_forward.py): when the current chain has no valid two-sided
 * quote, the last valid in-session cycle of the most recent regular US session for the same ticker, period and expiry. The row keeps the
 * capture's own timestamp, spot, dte and asof_date; only this reader accepts it, and only through validateCoveredCallCycle's
 * allowPreviousSession option (an older reader refuses any basis but "delayed"). */
export const PREVIOUS_SESSION_BASIS = "previous_session_last";
/** Its own age bound (four calendar days, spanning a weekend or a holiday); live quotes keep the 6-hour bound. */
export const PREVIOUS_SESSION_MAX_AGE_MS = 4 * 86_400_000;

/** V21 (operator 2026-10-19): the additive `strategies` object of a cycle (scripts/validate_v213_market_products.py validate_strategies is
 * the Python mirror). One quoted option leg of the cash-secured put and the collar; delta is ABSOLUTE. */
export interface StrategyLeg { strike: number; bid: number; ask: number; limit_price: number; delta: number; delta_basis: "QUOTED" | "QUOTED_IV" | "QUOTE_IMPLIED" }
export interface CspItem extends StrategyLeg {
  role: "CONSERVATIVE" | "BALANCED"; premium_per_contract: number; cash_required: number; annualized_yield: number; breakeven: number; downside_buffer: number;
}
export interface CollarItem {
  role: "CONSERVATIVE" | "BALANCED"; call: StrategyLeg; net_premium_per_share: number; max_loss_per_share: number; max_gain_per_share: number;
  break_even: number; worst_case_net_per_share: number;
}
/** The label every real block repeats; each value equals the cycle's own (checked). */
export interface StrategyLabel { rights_status: string; provider_id: string; quote_basis: string; timestamp: string }
export interface StrategyUnavailable { unavailable: string }
export type CspBlock = ({ suggestions: CspItem[] } & StrategyLabel) | StrategyUnavailable;
export type CollarBlock = ({ put: StrategyLeg; items: CollarItem[] } & StrategyLabel) | StrategyUnavailable;
export interface CycleStrategies { cc?: StrategyUnavailable; csp?: CspBlock; collar?: CollarBlock }

export interface CoveredCallCycle {
  ticker: string; strategy: "COVERED_CALL"; expiry: string; dte: number; spot: number; currency: "USD" | "SEK";
  multiplier: 100; quote_basis: "delayed" | typeof PREVIOUS_SESSION_BASIS; timestamp: string; source: string; provenance: string; rights_status: string;
  /** Producer-CLAIMED join identity for public admission (never authority; absent on local candidates). */
  provider_id?: string; jurisdiction?: string; venue?: string; instrument_kind?: string; publication_scope?: string;
  /** One or two covered-call tiers; EMPTY only beside a validated real `strategies.csp` or `strategies.collar` block. */
  suggestions: CoveredCallSuggestion[];
  /** V21 additive; absent on older sealed rows (the card then shows the cash-secured put and the collar as no data). A block that failed
   * validation has already been replaced by {unavailable} by validateCoveredCallCycle. */
  strategies?: CycleStrategies;
  /** Optional additive middle tier (role MIDDLE, strike strictly between the two suggestions); absent in older sealed rows. */
  middle_suggestion?: CoveredCallSuggestion;
  /** Exchange-local date (YYYY-MM-DD) the expiry rule was applied on, and for weekly cycles whether the expiry is in the
   * CURRENT calendar week or (only when this week has no remaining weekly) the NEXT; both absent in older sealed rows. */
  asof_date?: string; weekly_week?: WeeklyWeek;
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
 * third-Friday calendar classification; weekly 0-14 is the outer bound (with asof_date the exact current-week rule of
 * option-recommendation-rules.ts applies), monthly 21-45. */
const PERIOD_DTE_BUCKETS: Record<string, readonly [number, number]> = { weekly: WEEKLY_DTE_BUCKET, monthly: MONTHLY_DTE_BUCKET };

/** UTC midnight epoch ms of a YYYY-MM-DD calendar date, or null for an impossible date (e.g. 2026-02-30) that the shape
 * regex alone would admit. */
function parseCalendarDateUtcMidnight(raw: string): number | null {
  const ms = Date.parse(`${raw}T00:00:00Z`);
  if (!Number.isFinite(ms)) return null;
  return new Date(ms).toISOString().slice(0, 10) === raw ? ms : null;
}

/** A strictly validated cycle, or null (the caller then shows the option as unavailable). The previous-session carry-forward basis is
 * refused unless the caller opts in (the sealed-options loader does; format-only and coverage callers do not) AND passes `now`: a
 * carried row is a USD (US-listed) capture taken inside a regular US session within four days, with its asof_date, whose contract
 * is still listed on the New York date of `now` (its dte and asof_date describe the capture, so the live dte rule does not apply). */
export function validateCoveredCallCycle(raw: unknown, now?: number, documentGeneratedAt?: string, period?: "weekly" | "monthly",
  options?: { readonly allowPreviousSession?: boolean }): CoveredCallCycle | null {
  if (!raw || typeof raw !== "object") return null;
  const cycle = raw as Record<string, any>;
  const carried = cycle.quote_basis === PREVIOUS_SESSION_BASIS && options?.allowPreviousSession === true;
  if (cycle.strategy !== "COVERED_CALL" || (cycle.currency !== "USD" && cycle.currency !== "SEK") || cycle.multiplier !== 100
    || (cycle.quote_basis !== "delayed" && !carried) || typeof cycle.ticker !== "string" || !/^[A-Z0-9.\- ]{1,16}$/.test(cycle.ticker)
    || typeof cycle.expiry !== "string" || !/^\d{4}-\d{2}-\d{2}$/.test(cycle.expiry) || !Number.isInteger(cycle.dte)
    || cycle.dte < 0 || cycle.dte > 60 || !finite(cycle.spot) || cycle.spot <= 0 || typeof cycle.source !== "string"
    || typeof cycle.provenance !== "string" || !cycle.provenance.startsWith("https://")
    || !isValidUtcIsoInstant(cycle.timestamp)
    || !Array.isArray(cycle.suggestions) || cycle.suggestions.length > 2) return null;
  if (carried && (typeof now !== "number" || !Number.isFinite(now) || cycle.currency !== "USD" || typeof cycle.asof_date !== "string")) return null;

  const rowTime = Date.parse(cycle.timestamp);
  if (typeof now === "number" && Number.isFinite(now)) {
    // Worker 6h maximum observation age (a carried row: its own four-day bound, and the capture must lie inside a regular US session)
    if (now - rowTime > (carried ? PREVIOUS_SESSION_MAX_AGE_MS : 6 * 3600_000)) return null;
    // Worker <=5min clock tolerance into future
    if (rowTime - now > 300_000) return null;
    if (carried && !usRegularSessionOpen(rowTime)) return null;
  }
  if (typeof documentGeneratedAt === "string" && documentGeneratedAt.length > 0) {
    const docTime = Date.parse(documentGeneratedAt);
    if (Number.isFinite(docTime) && rowTime - docTime > 300_000) return null;
  }

  // Selected cycle window: the row's DTE must fall in the requested period's producer bucket (weekly 0-14 / monthly
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
    if (carried) {
      // dte and asof_date describe the capture (checked against each other below); here the contract must still be listed: not expired
      // by the New York date, and on its expiry day only until the regular-session close.
      const today = exchangeDate(now, "US");
      if (cycle.expiry < today || (cycle.expiry === today && !expiryDayOpen(now, "US"))) return null;
    } else {
      // An expiry-day (DTE 0) row is a sell recommendation for a contract that stops trading at the regular-session close: reject
      // it once the venue's session is over (the UTC-date check above only fires after UTC midnight).
      if (cycle.dte === 0 && !expiryDayOpen(now, cycle.currency === "SEK" ? "STOCKHOLM" : "US")) return null;
      if (Math.abs(dayDiff - cycle.dte) > 1) return null;  // calendar-DTE inconsistent (+/-1 tolerance, mirrors Python)
    }
  }

  // Optional exchange-local as-of date and weekly week marker (older sealed rows carry neither). The date must be a real calendar
  // date, exactly consistent with expiry and dte, and within one day of the row's own instant; a weekly row must then satisfy
  // the current-week rule (this week's remaining expiry, or only when none, next week's); the week marker must agree.
  const asofMs = cycle.asof_date === undefined || cycle.asof_date === null ? null : dayMs(cycle.asof_date);
  if (cycle.asof_date !== undefined && cycle.asof_date !== null) {
    if (asofMs === null || Math.round((expiryMs - asofMs) / 86_400_000) !== cycle.dte
      || Math.abs(asofMs - Date.parse(`${new Date(rowTime).toISOString().slice(0, 10)}T00:00:00Z`)) > 86_400_000) return null;
    const expectedWeek = weeklyWeekFor(cycle.expiry, cycle.asof_date);
    if (period === "weekly" && expectedWeek === null) return null;
    if (cycle.weekly_week !== undefined && cycle.weekly_week !== null && cycle.weekly_week !== expectedWeek) return null;
  }
  if (cycle.weekly_week !== undefined && cycle.weekly_week !== null
    && ((cycle.weekly_week !== "CURRENT" && cycle.weekly_week !== "NEXT") || period === "monthly")) return null;

  const roles = cycle.suggestions.map((item: any) => item?.role).join(",");
  if (roles !== "" && roles !== "HIGH_STRIKE" && roles !== "HIGH_STRIKE,BALANCED") return null;
  /** Per-item checks shared by the two suggestions and the optional middle tier. */
  const itemValid = (item: any): boolean => {
    if (!item || typeof item !== "object") return false;
    if (!["strike", "bid", "ask", "mid", "limit_price", "premium_per_contract", "period_yield", "annualized_yield", "upside_to_strike"]
      .every(key => finite(item[key]))) return false;
    if (!(item.strike > cycle.spot) || !(item.bid > 0 && item.bid <= item.ask) || !close(item.mid, (item.bid + item.ask) / 2)
      || item.limit_price < item.bid - 1e-9 || item.limit_price > item.mid + 1e-9) return false;
    if (!close(item.premium_per_contract, item.limit_price * 100) || !close(item.period_yield, item.limit_price / cycle.spot)
      || !close(item.annualized_yield, item.limit_price / cycle.spot * 365 / effectiveDays(cycle.dte))
      || !close(item.upside_to_strike, item.strike / cycle.spot - 1)) return false;
    if (item.delta !== null && item.delta !== undefined && !(finite(item.delta) && item.delta >= 0 && item.delta <= 1)) return false;
    if (item.role === "HIGH_STRIKE" && !(finite(item.delta) && item.delta <= MAX_HIGH_STRIKE_DELTA)) return false;
    if (item.delta_basis !== null && item.delta_basis !== undefined && !DELTA_BASES.has(item.delta_basis)) return false;
    if (item.iv !== null && item.iv !== undefined && !(finite(item.iv) && item.iv > 0)) return false;
    // Optional supplied liquidity/spread fields must be a finite, non-negative number when present (amendment-02):
    // reject nonfinite (JSON 1e309 -> Infinity), wrong type (bool/string/array/object) and negatives, so a malformed
    // value can never reach text/Flex; a legitimate null/missing stays unknown (未提供).
    for (const key of ["oi", "volume", "spread_pct"] as const) {
      const value = item[key];
      if (value !== null && value !== undefined && !(finite(value) && value >= 0)) return false;
    }
    return true;
  };
  for (const item of cycle.suggestions as any[]) if (!itemValid(item)) return null;
  if (cycle.suggestions.length === 2 && !(cycle.suggestions[0].strike > cycle.suggestions[1].strike)) return null;
  if (cycle.middle_suggestion !== undefined && cycle.middle_suggestion !== null) {
    // The middle tier needs both neighbours, carries the role MIDDLE, passes the same checks and sits strictly between their
    // strikes (HIGH > MIDDLE > BALANCED). Limit prices are not required to be ordered, only strikes. Malformed: the cycle is null.
    const middle = cycle.middle_suggestion;
    if (cycle.suggestions.length !== 2 || middle.role !== "MIDDLE" || !itemValid(middle)
      || !(cycle.suggestions[0].strike > middle.strike && middle.strike > cycle.suggestions[1].strike)) return null;
  }
  const strategies = sanitizeStrategies(cycle);
  if (strategies === null) return null;
  if (strategies === undefined) {
    if (cycle.suggestions.length === 0) return null;  // no covered call and no strategies: nothing to show
    if (cycle.strategies === undefined) return cycle as CoveredCallCycle;
    const { strategies: _dropped, ...rest } = cycle;  // a malformed strategies value never reaches the card
    return rest as CoveredCallCycle;
  }
  return { ...cycle, strategies } as CoveredCallCycle;
}

// ---- V21 strategies: strict mirror of validate_strategy_block / validate_strategies / degrade_bad_strategy_blocks (Python) ----
const STRATEGY_NAMES = ["cc", "csp", "collar"] as const;
const STRATEGY_LABEL_KEYS = ["rights_status", "provider_id", "quote_basis", "timestamp"] as const;
const LEG_KEYS = ["strike", "bid", "ask", "limit_price", "delta", "delta_basis"] as const;
const CSP_KEYS = [...LEG_KEYS, "role", "premium_per_contract", "cash_required", "annualized_yield", "breakeven", "downside_buffer"] as const;
const COLLAR_KEYS = ["role", "call", "net_premium_per_share", "max_loss_per_share", "max_gain_per_share", "break_even", "worst_case_net_per_share"] as const;
/** scripts/option_recommendation_rules.py CONSERVATIVE_DELTA_BAND, PROTECTIVE_PUT_DELTA_BAND and DELTA_BAND_TOLERANCE. */
export const CONSERVATIVE_DELTA_BAND = [0.20, 0.30] as const;
export const PROTECTIVE_PUT_DELTA_BAND = [0.05, 0.25] as const;
const DELTA_BAND_TOLERANCE = 0.0005;
export const STRATEGY_DEGRADED_TEXT = "報價未通過驗證";
const STRATEGY_UNAVAILABLE_MAX = 200;

const isRecord = (value: unknown): value is Record<string, any> => typeof value === "object" && value !== null && !Array.isArray(value);
const hasExactKeys = (value: Record<string, any>, keys: readonly string[]) => {
  const own = Object.keys(value);
  return own.length === keys.length && keys.every(key => Object.hasOwn(value, key));
};
const validRoles = (items: any[]) => items.length === 1 ? items[0]?.role === "CONSERVATIVE"
  : items.length === 2 && items[0]?.role === "CONSERVATIVE" && items[1]?.role === "BALANCED";
const unavailableValid = (block: unknown): block is StrategyUnavailable => isRecord(block) && hasExactKeys(block, ["unavailable"])
  && typeof block.unavailable === "string" && block.unavailable.trim().length > 0 && block.unavailable.length <= STRATEGY_UNAVAILABLE_MAX;

/** One quoted leg: exact key set, strike on the right side of the spot, two-sided positive quote, limit on the right side of the mid
 * (sell: bid..mid; buy: mid..ask), absolute delta in the band, known delta basis. */
function legValid(leg: unknown, spot: number, kind: { buy: boolean; put: boolean; band: readonly [number, number] }): boolean {
  if (!isRecord(leg) || !LEG_KEYS.every(key => Object.hasOwn(leg, key))) return false;
  if (!["strike", "bid", "ask", "limit_price", "delta"].every(key => finite(leg[key]))) return false;
  if (!(kind.put ? leg.strike > 0 && leg.strike < spot : leg.strike > spot && spot > 0)) return false;
  if (!(leg.bid > 0 && leg.bid <= leg.ask)) return false;
  const mid = (leg.bid + leg.ask) / 2;
  if (kind.buy ? !(leg.limit_price >= mid - 1e-9 && leg.limit_price <= leg.ask + 1e-9) : !(leg.limit_price >= leg.bid - 1e-9 && leg.limit_price <= mid + 1e-9)) return false;
  if (!(leg.delta > 0 && leg.delta <= 1)) return false;
  if (!(leg.delta >= kind.band[0] - DELTA_BAND_TOLERANCE && leg.delta <= kind.band[1] + DELTA_BAND_TOLERANCE)) return false;
  return typeof leg.delta_basis === "string" && DELTA_BASES.has(leg.delta_basis);
}

function labelValid(block: Record<string, any>, cycle: Record<string, any>, itemsKey: string, extra: readonly string[] = []): any[] | null {
  if (!hasExactKeys(block, [itemsKey, ...extra, ...STRATEGY_LABEL_KEYS])) return null;
  for (const key of STRATEGY_LABEL_KEYS) if ((block[key] ?? null) !== (cycle[key] ?? null)) return null;
  const items = block[itemsKey];
  if (!Array.isArray(items) || items.length < 1 || items.length > 2 || !items.every(isRecord) || !validRoles(items)) return null;
  return items;
}

/** One csp or collar block against the cycle's spot, dte and label. */
function strategyBlockValid(name: "csp" | "collar", block: unknown, cycle: Record<string, any>): boolean {
  if (unavailableValid(block)) return true;
  if (!isRecord(block) || "unavailable" in block || !finite(cycle.spot) || !Number.isInteger(cycle.dte) || cycle.dte < 0) return false;
  const spot: number = cycle.spot;
  const days = effectiveDays(cycle.dte);
  if (name === "csp") {
    const items = labelValid(block, cycle, "suggestions");
    if (!items) return false;
    for (const item of items) {
      if (!hasExactKeys(item, CSP_KEYS) || !legValid(item, spot, { buy: false, put: true, band: CONSERVATIVE_DELTA_BAND })) return false;
      if (!["premium_per_contract", "cash_required", "annualized_yield", "breakeven", "downside_buffer"].every(key => finite(item[key]))) return false;
      if (!close(item.premium_per_contract, item.limit_price * 100) || !close(item.cash_required, item.strike * 100)
        || !close(item.annualized_yield, item.limit_price / item.strike * 365 / days) || !close(item.breakeven, item.strike - item.limit_price)
        || !close(item.downside_buffer, 1 - item.strike / spot)) return false;
    }
    return items.length === 1 || items[1].strike > items[0].strike;
  }
  const items = labelValid(block, cycle, "items", ["put"]);
  if (!items || !isRecord(block.put) || !hasExactKeys(block.put, LEG_KEYS) || !legValid(block.put, spot, { buy: true, put: true, band: PROTECTIVE_PUT_DELTA_BAND })) return false;
  const put = block.put as StrategyLeg;
  for (const item of items) {
    if (!hasExactKeys(item, COLLAR_KEYS) || !isRecord(item.call) || !hasExactKeys(item.call, LEG_KEYS)
      || !legValid(item.call, spot, { buy: false, put: false, band: CONSERVATIVE_DELTA_BAND })) return false;
    if (!["net_premium_per_share", "max_loss_per_share", "max_gain_per_share", "break_even", "worst_case_net_per_share"].every(key => finite(item[key]))) return false;
    const call = item.call as StrategyLeg;
    const net = call.limit_price - put.limit_price;
    if (!close(item.net_premium_per_share, net) || !close(item.max_loss_per_share, spot - put.strike - net)
      || !close(item.max_gain_per_share, call.strike - spot + net) || !close(item.break_even, spot - net)
      || !close(item.worst_case_net_per_share, call.bid - put.ask)) return false;
  }
  return items.length === 1 || items[1].call.strike < items[0].call.strike;
}

/** The cycle's strategies after block-level degradation: undefined when there is none (absent, not an object, or nothing left), null when
 * the CYCLE is invalid (a covered call beside a `cc` block, no covered call without a valid `cc` unavailable block, or no covered call and
 * no real csp/collar block). A failing csp or collar block becomes {unavailable} alone; unknown names are dropped. */
function sanitizeStrategies(cycle: Record<string, any>): CycleStrategies | null | undefined {
  const raw = cycle.strategies;
  if (!isRecord(raw)) return undefined;
  const kept: Record<string, any> = {};
  for (const name of STRATEGY_NAMES) {
    if (!Object.hasOwn(raw, name)) continue;
    const block = raw[name];
    if (name === "cc") { if (unavailableValid(block)) kept.cc = block; continue; }
    kept[name] = strategyBlockValid(name, block, cycle) ? block : { unavailable: STRATEGY_DEGRADED_TEXT };
  }
  if (Object.keys(kept).length === 0) return undefined;
  const noCoveredCall = cycle.suggestions.length === 0;
  if (noCoveredCall && !isRecord(kept.cc)) return null;
  if (!noCoveredCall && "cc" in kept) return null;
  const real = (name: "csp" | "collar") => isRecord(kept[name]) && !("unavailable" in kept[name]);
  if (noCoveredCall && !real("csp") && !real("collar")) return null;
  return kept as CycleStrategies;
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
/** Role label and note. The visible title is numbered by display position (一／二／三) so numbering never has a gap: the middle
 * tier is shown only when it exists, and without it the two original titles are unchanged. */
const ROLE = {
  HIGH_STRIKE: ["高履約價（不易被賣掉）", "在年化權利金至少 2% 的前提下選最高履約價；股價需上漲超過右側幅度才會被指派。"],
  MIDDLE: ["中間型（權利金與被指派機率居中）", "履約價與權利金介於高履約價與平衡型之間；被指派機率也居中。"],
  BALANCED: ["平衡型（收較多權利金）", "履約價較低、權利金較高；被指派機率也較高。"],
} as const;
const ORDINAL_ZH = ["一", "二", "三"] as const;

/** The tiers in display order: HIGH_STRIKE, the optional MIDDLE, BALANCED (strikes strictly descending). */
function displayTiers(cycle: CoveredCallCycle): CoveredCallSuggestion[] {
  const [high, balanced] = cycle.suggestions;
  return high ? [high, ...(cycle.middle_suggestion ? [cycle.middle_suggestion] : []), ...(balanced ? [balanced] : [])] : [];
}
const tierTitle = (item: CoveredCallSuggestion, index: number) => `建議${ORDINAL_ZH[index] ?? String(index + 1)}：${ROLE[item.role][0]}`;

/** Weekly marker: only rows that carry weekly_week (current producer) say which calendar week the expiry is in. */
function weekNoteZh(cycle: CoveredCallCycle): string | null {
  if (cycle.weekly_week === "CURRENT") return "本週到期";
  if (cycle.weekly_week === "NEXT") return "本週已無剩餘週選，顯示下週最早到期日";
  return null;
}

/** DTE 0-2: the annualized yield is computed over at least one day and is strongly amplified; say so on the card. */
function shortDteNoticeZh(cycle: CoveredCallCycle): string | null {
  if (cycle.dte > SHORT_DTE_NOTICE_MAX) return null;
  return `${cycle.dte === 0 ? "今日到期" : `距到期僅 ${cycle.dte} 天`}：年化收益以至少 1 天換算，數字被大幅放大，只供比較，不代表可持續收益。`;
}

function assignmentText(item: CoveredCallSuggestion): string {
  if (item.delta === null || item.delta === undefined) return "被指派機率參考：報價不足以推算 Delta";
  const basis = deltaBasisZh(item);
  return `被指派機率參考：Delta ${item.delta.toFixed(2)}（約 ${Math.round(item.delta * 100)}%${basis ? `，${basis}` : ""}）`;
}

/** V20: one tier as four figure rows (strike, limit, premium per contract, annualized), the assignment reference as a bullet and
 * the liquidity as one muted line. The role note (the tier's meaning) lives in the tier title and the text edition. */
function suggestionSection(cycle: CoveredCallCycle, item: CoveredCallSuggestion, index: number) {
  const title = tierTitle(item, index);
  const assignment = assignmentText(item);
  return section(title, [
    kvRow("履約價", money(item.strike, cycle.currency), { sub: `距現價 +${pct(item.upside_to_strike)}` }),
    kvRow("建議賣出限價", money(item.limit_price, cycle.currency), { emphasis: true, sub: `Bid ${money(item.bid, cycle.currency)}／中價 ${money(item.mid, cycle.currency)}／Ask ${money(item.ask, cycle.currency)}` }),
    kvRow("每口權利金", money(item.premium_per_contract, cycle.currency), { sub: "100 股／口" }),
    kvRow("年化收益", pct(item.annualized_yield), { sub: `期間 ${pct(item.period_yield, 2)}` }),
    meter(Math.min(1, item.upside_to_strike / 0.5) * 100),
    bulletRow(assignment),
    uiText(`流動性：OI ${countZh(item.oi)}｜成交量 ${countZh(item.volume)}｜價差占中價 ${spreadZh(item.spread_pct)}`, "xs", T.muted),
    // Only the tier whose note states the selection criterion (the annualized-yield floor) keeps its note.
    ...(item.role === "HIGH_STRIKE" ? [footnote(ROLE.HIGH_STRIKE[1])] : []),
  ], item.role === "HIGH_STRIKE" ? "key" : "detail");
}

/** "YYYY-MM-DD HH:mm" in New York for an instant, with the same Intl style the Worker uses for other local times (formatToParts, h23). */
function newYorkStampZh(ms: number): string {
  const parts = new Intl.DateTimeFormat("en-CA", { timeZone: "America/New_York", year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", hourCycle: "h23" }).formatToParts(new Date(ms));
  const part = (type: string) => parts.find(item => item.type === type)!.value;
  return `${part("year")}-${part("month")}-${part("day")} ${part("hour")}:${part("minute")}`;
}
/** The exact label every carried card carries, in flex and text: the capture time of the previous session's last valid quote. */
export const previousSessionLabelZh = (captureIso: string) => `前一交易時段最後報價（${newYorkStampZh(Date.parse(captureIso))} 美東）；開盤後價格會變動`;
/** The short disclosure of an operator-accepted provider (no redistribution licence); the source line already says unofficial and delayed. */
export const OPERATOR_ACCEPTED_NOTICE_ZH = "依營運者決定顯示；本資料未取得再散布授權。";

// ---- V21 (operator 2026-10-19): three conservative strategies on one card -----------------------------------------------------------------
// Overview, then the covered-call, cash-secured-put and collar details; a strategy without data keeps its overview row ("無資料") and has no
// detail bubble, so the card is 2 to 4 bubbles. Everything shown is a quote or a figure recomputed by the validator; nothing is advice.
const NO_STRATEGIES_REASON = "此筆為舊版資料，未含此策略報價";
const NO_SOURCE_PUT_REASON = "本輪來源未提供此策略報價";
const CSP_TITLE = "現金擔保賣權（備足現金賣出賣權）";
const COLLAR_TITLE = "領口策略（持股＋買保護賣權＋賣買權）";
const CC_TITLE = "備兌買權（持股賣出買權）";

type CspData = Extract<CspBlock, { suggestions: CspItem[] }>;
type CollarData = Extract<CollarBlock, { items: CollarItem[] }>;
type Shown<T> = { block: T } | { none: string };

function cspShown(cycle: CoveredCallCycle): Shown<CspData> {
  if (!cycle.strategies) return { none: NO_STRATEGIES_REASON };
  const block = cycle.strategies.csp;
  if (!block) return { none: NO_SOURCE_PUT_REASON };
  return "unavailable" in block ? { none: block.unavailable } : { block };
}
function collarShown(cycle: CoveredCallCycle): Shown<CollarData> {
  if (!cycle.strategies) return { none: NO_STRATEGIES_REASON };
  const block = cycle.strategies.collar;
  if (!block) return { none: NO_SOURCE_PUT_REASON };
  return "unavailable" in block ? { none: block.unavailable } : { block };
}
const ccNone = (cycle: CoveredCallCycle) => cycle.strategies?.cc?.unavailable ?? "本輪沒有符合條件的備兌買權";

const BASIS_ZH = { QUOTED: "交易所提供", QUOTED_IV: "模型值，依報價隱含波動率", QUOTE_IMPLIED: "模型值，由買賣報價反推" } as const;
const legDeltaZh = (leg: StrategyLeg) => `Delta ${leg.delta.toFixed(2)}（約 ${Math.round(leg.delta * 100)}%，${BASIS_ZH[leg.delta_basis]}）`;
const bidAskZh = (leg: StrategyLeg, currency: string) => `Bid ${money(leg.bid, currency)}／中價 ${money((leg.bid + leg.ask) / 2, currency)}／Ask ${money(leg.ask, currency)}`;
const tierNameZh = (role: string) => role === "CONSERVATIVE" ? "保守型（Delta 約 0.20 起）" : "平衡型（收較多權利金）";
const signedMoney = (value: number, currency: string) => `${value < 0 ? "-" : "+"}${money(Math.abs(value), currency)}`;

interface CardContext {
  cycle: CoveredCallCycle; periodLabel: string; carried: boolean; carriedLabel: string | null; operatorNotice: string | null; dteZh: string; spotLabel: string;
}
function cardContext(cycle: CoveredCallCycle, periodLabel: string): CardContext {
  const carried = cycle.quote_basis === PREVIOUS_SESSION_BASIS;
  return { cycle, periodLabel, carried, carriedLabel: carried ? previousSessionLabelZh(cycle.timestamp) : null,
    operatorNotice: null, dteZh: carried ? `擷取時 ${cycle.dte} 天` : cycle.dte === 0 ? "今日到期" : `${cycle.dte} 天`, spotLabel: carried ? "前一時段現價" : "現價" };
}

/** Collar figures per contract (x100 of the per-share values the validator recomputed). */
const perContract = (value: number) => value * 100;

/** Overview section of one strategy: one hero figure and up to three bullets, or an explicit no-data row. */
function overviewSection(title: string, tone: "key" | "detail", shown: { hero: ReturnType<typeof heroStat>; bullets: string[] } | { none: string }) {
  if ("none" in shown) return section(title, [bulletRow(`無資料：${clampText(shown.none, 44)}`)], tone);
  return section(title, [shown.hero, ...shown.bullets.map(text => bulletRow(text))], tone);
}

function ccOverview(ctx: CardContext) {
  const { cycle } = ctx;
  const first = cycle.suggestions[0];
  if (!first) return overviewSection(CC_TITLE, "key", { none: ccNone(cycle) });
  return overviewSection(CC_TITLE, "key", {
    hero: heroStat("每口權利金（保守檔）", money(first.premium_per_contract, cycle.currency), `年化 ${pct(first.annualized_yield)}`, T.ink),
    bullets: [`履約價 ${money(first.strike, cycle.currency)}（距現價 +${pct(first.upside_to_strike)}），限價 ${money(first.limit_price, cycle.currency)}`,
      ...(first.delta === null || first.delta === undefined ? [] : [`被指派機率參考：Delta ${first.delta.toFixed(2)}（約 ${Math.round(first.delta * 100)}%）`])],
  });
}
function cspOverview(ctx: CardContext) {
  const { cycle } = ctx;
  const shown = cspShown(cycle);
  if ("none" in shown) return overviewSection(CSP_TITLE, "detail", shown);
  const first = shown.block.suggestions[0]!;
  return overviewSection(CSP_TITLE, "detail", {
    hero: heroStat("每口權利金（保守檔）", money(first.premium_per_contract, cycle.currency), `年化 ${pct(first.annualized_yield)}（以備妥現金計）`, T.ink),
    bullets: [`履約價 ${money(first.strike, cycle.currency)}（低於現價 ${pct(first.downside_buffer)}），限價 ${money(first.limit_price, cycle.currency)}`,
      `需備現金 ${money(first.cash_required, cycle.currency)}（100 股）`, `損益兩平 ${money(first.breakeven, cycle.currency)}`],
  });
}
function collarOverview(ctx: CardContext) {
  const { cycle } = ctx;
  const shown = collarShown(cycle);
  if ("none" in shown) return overviewSection(COLLAR_TITLE, "detail", shown);
  const { put, items } = shown.block;
  const first = items[0]!;
  const net = perContract(first.net_premium_per_share);
  return overviewSection(COLLAR_TITLE, "detail", {
    hero: heroStat(net >= 0 ? "每口淨權利金（收入）" : "每口淨權利金（支出）", money(Math.abs(net), cycle.currency), "保守檔，買賣權利金相抵後", T.ink),
    bullets: [`買進賣權 ${money(put.strike, cycle.currency)}（限價 ${money(put.limit_price, cycle.currency)}），賣出買權 ${money(first.call.strike, cycle.currency)}（限價 ${money(first.call.limit_price, cycle.currency)}）`,
      `最大損失 ${money(perContract(first.max_loss_per_share), cycle.currency)}／口，最大獲利 ${money(perContract(first.max_gain_per_share), cycle.currency)}／口`],
  });
}

/** Header chips shared by every bubble. */
function headerBox(ctx: CardContext, eyebrow: string) {
  const { cycle } = ctx;
  return productHeader(`${eyebrow} · ${ctx.periodLabel} · ${ctx.carried ? "前一時段報價" : "延遲報價"}`, `${cycle.ticker}｜到期 ${cycle.expiry}`, [
    uiBox([chip(ctx.dteZh), chip(`${ctx.spotLabel} ${money(cycle.spot, cycle.currency)}`), chip(`計價 ${cycle.currency}`)], { layout: "horizontal", spacing: "sm" }),
    ...(weekNoteZh(cycle) ? [uiBox([chip(weekNoteZh(cycle)!)], { layout: "horizontal", spacing: "sm" })] : []),
  ]);
}

/** Footer shared by every bubble: ONE disclosure line with the source and rights label, the quote basis and capture time, the provenance, the
 * operator-accepted notice, this bubble's risk line and the standing disclaimer; optional buttons. */
function footerBox(ctx: CardContext, risk: string, buttons: unknown[] = []) {
  const { cycle } = ctx;
  return uiBox([
    disclosureLine([
      `來源：${sourceZh(cycle.source)}，${ctx.carried ? "前一交易時段擷取時間" : "擷取時間"} ${cycle.timestamp}（來源報價時間未提供）`,
      `資料出處：${cycle.provenance}`,
      ...(ctx.operatorNotice ? [ctx.operatorNotice] : []),
      risk,
      "公開行情觀察，非個人化投資建議；延遲／非即時可執行；年化收益非保證報酬；正股仍承擔下跌風險；本服務不下單",
    ]),
    ...buttons,
  ], footerStyle);
}
const detailButtons = (ctx: CardContext) => [
  detailsButton(`${ctx.cycle.ticker} 完整報價與出處`, `${ctx.cycle.ticker} ${ctx.periodLabel.includes("每月") ? "每月" : "每週"}期權 文字`),
  menuAction("期權策略教學", "期權教學"),
];

function overviewBubble(ctx: CardContext) {
  return {
    type: "bubble", size: "mega", header: headerBox(ctx, "三種保守期權策略"),
    body: uiBox([
      ...(ctx.carriedLabel ? [uiText(ctx.carriedLabel, "xs", T.ink)] : []),
      ccOverview(ctx), cspOverview(ctx), collarOverview(ctx),
      ...(shortDteNoticeZh(ctx.cycle) ? [bulletRow(shortDteNoticeZh(ctx.cycle)!, { color: T.caution })] : []),
    ], { paddingAll: "lg", spacing: "md" }),
    footer: footerBox(ctx, "股價不利時三種策略都可能虧損；各策略前提與最大損失見後續頁面", detailButtons(ctx)),
  };
}
function ccDetailBubble(ctx: CardContext) {
  const { cycle } = ctx;
  return {
    type: "bubble", size: "mega", header: headerBox(ctx, "備兌買權"),
    body: uiBox([
      ...(ctx.carriedLabel ? [uiText(ctx.carriedLabel, "xs", T.ink)] : []),
      ...displayTiers(cycle).map((item, index) => suggestionSection(cycle, item, index)),
      bulletRow("前提：持有 100 股、賣出 1 口買權；超過履約價可能被指派，上漲收益封頂。限價：價差 25% 內取中間價，較寬時取 Bid＋四分之一價差。"),
    ], { paddingAll: "lg", spacing: "md" }),
    footer: footerBox(ctx, "正股仍承擔下跌風險"),
  };
}
function cspSection(cycle: CoveredCallCycle, item: CspItem, index: number) {
  return section(`建議${ORDINAL_ZH[index] ?? String(index + 1)}：${tierNameZh(item.role)}`, [
    kvRow("履約價", money(item.strike, cycle.currency), { color: T.ink, sub: `低於現價 ${pct(item.downside_buffer)}` }),
    kvRow("建議賣出限價", money(item.limit_price, cycle.currency), { emphasis: true, color: T.ink, sub: bidAskZh(item, cycle.currency) }),
    kvRow("每口權利金", money(item.premium_per_contract, cycle.currency), { color: T.ink, sub: "100 股／口" }),
    kvRow("需備現金", money(item.cash_required, cycle.currency), { color: T.ink, sub: "履約價 × 100" }),
    kvRow("年化收益", pct(item.annualized_yield), { color: T.ink, sub: "以備妥現金計" }),
    kvRow("損益兩平", money(item.breakeven, cycle.currency), { color: T.ink }),
    bulletRow(`被指派（買進 100 股）機率參考：${legDeltaZh(item)}`),
  ], index === 0 ? "key" : "detail");
}
function cspDetailBubble(ctx: CardContext, block: CspData) {
  const { cycle } = ctx;
  return {
    type: "bubble", size: "mega", header: headerBox(ctx, "現金擔保賣權"),
    body: uiBox([
      ...block.suggestions.map((item, index) => cspSection(cycle, item, index)),
      bulletRow("前提：賣出 1 口賣權並備足履約價 × 100 的現金；股價跌破履約價可能被指派買進 100 股，損失可大於已收權利金。"),
    ], { paddingAll: "lg", spacing: "md" }),
    footer: footerBox(ctx, "被指派時需以履約價買進正股，正股下跌風險由賣方承擔"),
  };
}
function collarSection(cycle: CoveredCallCycle, put: StrategyLeg, item: CollarItem, index: number) {
  const net = perContract(item.net_premium_per_share);
  return section(`建議${ORDINAL_ZH[index] ?? String(index + 1)}：${tierNameZh(item.role)}`, [
    kvRow("賣出買權履約價", money(item.call.strike, cycle.currency), { color: T.ink, sub: `高於現價 ${pct(item.call.strike / cycle.spot - 1)}` }),
    kvRow("賣出限價", money(item.call.limit_price, cycle.currency), { emphasis: true, color: T.ink, sub: bidAskZh(item.call, cycle.currency) }),
    kvRow(net >= 0 ? "每口淨權利金（收入）" : "每口淨權利金（支出）", money(Math.abs(net), cycle.currency), { color: T.ink, sub: `賣出買權 − 買進賣權，${signedMoney(item.net_premium_per_share, cycle.currency)}／股` }),
    kvRow("最大損失", money(perContract(item.max_loss_per_share), cycle.currency), { color: T.ink, sub: `每口；股價跌破 ${money(put.strike, cycle.currency)} 後不再擴大` }),
    kvRow("最大獲利", money(perContract(item.max_gain_per_share), cycle.currency), { color: T.ink, sub: `每口；股價漲過 ${money(item.call.strike, cycle.currency)} 後封頂` }),
    kvRow("損益兩平", money(item.break_even, cycle.currency), { color: T.ink }),
    bulletRow(`被指派機率參考：${legDeltaZh(item.call)}`),
  ], index === 0 ? "key" : "detail");
}
function collarDetailBubble(ctx: CardContext, block: CollarData) {
  const { cycle } = ctx;
  const { put } = block;
  return {
    type: "bubble", size: "mega", header: headerBox(ctx, "領口策略"),
    body: uiBox([
      section("保護賣權（買進，兩個建議共用）", [
        kvRow("履約價", money(put.strike, cycle.currency), { color: T.ink, sub: `低於現價 ${pct(1 - put.strike / cycle.spot)}` }),
        kvRow("建議買入限價", money(put.limit_price, cycle.currency), { emphasis: true, color: T.ink, sub: bidAskZh(put, cycle.currency) }),
        bulletRow(`下跌保護程度參考：${legDeltaZh(put)}`),
      ], "detail"),
      ...block.items.map((item, index) => collarSection(cycle, put, item, index)),
      bulletRow("前提：持有 100 股，買進 1 口賣權並賣出 1 口買權；下跌損失以保護賣權為界，上漲收益封頂於買權履約價。"),
    ], { paddingAll: "lg", spacing: "md" }),
    footer: footerBox(ctx, "保護賣權需付權利金；最大損失／獲利為到期時每口理論值"),
  };
}

/** The strategies in text form (the text edition and the full detail behind the details button). */
function textStrategyLines(cycle: CoveredCallCycle): string[] {
  const cur = cycle.currency;
  const lines: string[] = [];
  if (cycle.suggestions.length === 0) lines.push(`【備兌買權】無資料：${ccNone(cycle)}`);
  const csp = cspShown(cycle);
  if ("none" in csp) lines.push(`【${CSP_TITLE}】無資料：${csp.none}`);
  else {
    lines.push(`【${CSP_TITLE}】前提：賣出 1 口賣權並備足履約價 × 100 的現金；股價跌破履約價可能被指派買進 100 股。`);
    csp.block.suggestions.forEach((item, index) => lines.push([
      `建議${ORDINAL_ZH[index] ?? String(index + 1)}：${tierNameZh(item.role)}`,
      `履約價 ${money(item.strike, cur)}（低於現價 ${pct(item.downside_buffer)}）｜建議賣出限價 ${money(item.limit_price, cur)}（${bidAskZh(item, cur)}）`,
      `每口權利金 ${money(item.premium_per_contract, cur)}｜需備現金 ${money(item.cash_required, cur)}｜年化 ${pct(item.annualized_yield)}（以備妥現金計）｜損益兩平 ${money(item.breakeven, cur)}`,
      `被指派機率參考：${legDeltaZh(item)}`,
    ].join("\n")));
  }
  const collar = collarShown(cycle);
  if ("none" in collar) lines.push(`【${COLLAR_TITLE}】無資料：${collar.none}`);
  else {
    const { put } = collar.block;
    lines.push([`【${COLLAR_TITLE}】前提：持有 100 股，買進 1 口賣權並賣出 1 口買權；下跌損失以保護賣權為界，上漲收益封頂。`,
      `保護賣權（買進）履約價 ${money(put.strike, cur)}｜建議買入限價 ${money(put.limit_price, cur)}（${bidAskZh(put, cur)}）｜${legDeltaZh(put)}`].join("\n"));
    collar.block.items.forEach((item, index) => {
      const net = perContract(item.net_premium_per_share);
      lines.push([
        `建議${ORDINAL_ZH[index] ?? String(index + 1)}：${tierNameZh(item.role)}`,
        `賣出買權履約價 ${money(item.call.strike, cur)}｜建議賣出限價 ${money(item.call.limit_price, cur)}（${bidAskZh(item.call, cur)}）｜${legDeltaZh(item.call)}`,
        `每口淨權利金（${net >= 0 ? "收入" : "支出"}）${money(Math.abs(net), cur)}｜最大損失 ${money(perContract(item.max_loss_per_share), cur)}／口｜最大獲利 ${money(perContract(item.max_gain_per_share), cur)}／口｜損益兩平 ${money(item.break_even, cur)}`,
      ].join("\n"));
    });
  }
  return lines;
}

export function buildCoveredCallMessages(cycle: CoveredCallCycle, periodLabel: string, style: "flex" | "text"): LineOutboundMessage[] {
  // Independent public-rights guard (validateCoveredCallCycle stays format-only for local data): the trusted catalog decides, never
  // rights_status, source text or a caller flag, so a new caller cannot bypass the loader's enforcement.
  // Judged against the real current time: if the review window closes after the loader admitted the row, this dedicated typed error
  // (the only one a public caller converts to an unavailable report) denies instead of rendering.
  const admission = admitPublicOption(cycle);
  if (!admission.ok) throw new OptionRightsNotAdmittedError();
  const ctx = cardContext(cycle, periodLabel);
  ctx.operatorNotice = admission.operator_accepted === true ? OPERATOR_ACCEPTED_NOTICE_ZH : null;
  const { carried, carriedLabel, operatorNotice, dteZh, spotLabel } = ctx;
  if (style === "text") {
    const lines = [
      `【${cycle.suggestions.length > 0 ? "備兌買權建議" : "期權策略"}｜${cycle.ticker} ${periodLabel}】到期 ${cycle.expiry}（${carried ? dteZh : `${cycle.dte} 天`}）｜${spotLabel} ${money(cycle.spot, cycle.currency)}（計價 ${cycle.currency}）`,
      ...(carriedLabel ? [carriedLabel] : []),
      ...(weekNoteZh(cycle) ? [`${weekNoteZh(cycle)}${cycle.asof_date ? `（以交易所當地日期 ${cycle.asof_date} 判斷）` : ""}`] : []),
      ...(shortDteNoticeZh(cycle) ? [shortDteNoticeZh(cycle)!] : []),
      ...(cycle.suggestions.length > 0 ? [`【${CC_TITLE}】前提：持有 100 股、賣出 1 口買權；股價超過履約價時可能被指派，上漲收益封頂於履約價。`] : []),
      ...displayTiers(cycle).map((item, index) => [
        tierTitle(item, index),
        `履約價 ${money(item.strike, cycle.currency)}（距現價 +${pct(item.upside_to_strike)}）｜建議賣出限價 ${money(item.limit_price, cycle.currency)}（Bid ${money(item.bid, cycle.currency)}／中價 ${money(item.mid, cycle.currency)}／Ask ${money(item.ask, cycle.currency)}）`,
        `每口權利金 ${money(item.premium_per_contract, cycle.currency)}｜期間收益 ${pct(item.period_yield, 2)}｜年化 ${pct(item.annualized_yield)}｜Delta ${item.delta === null || item.delta === undefined ? "未提供" : `${item.delta.toFixed(2)}${deltaBasisZh(item) ? `（${deltaBasisZh(item)}）` : ""}`}`,
        `流動性：OI ${countZh(item.oi)}｜成交量 ${countZh(item.volume)}｜價差占中價 ${spreadZh(item.spread_pct)}`,
      ].join("\n")),
      ...textStrategyLines(cycle),
      `來源：${sourceZh(cycle.source)}（延遲報價，${carried ? "前一交易時段擷取時間" : "擷取時間"} ${cycle.timestamp}；來源報價時間未提供）${cycle.provenance}`,
      ...(operatorNotice ? [operatorNotice] : []),
      "公開行情觀察，非個人化投資建議；延遲／非即時可執行；年化收益非保證報酬；正股仍承擔下跌風險；賣出賣權可能被指派買進正股；本服務不下單。",
    ];
    const messages: LineOutboundMessage[] = [{ type: "text", text: lines.join("\n").slice(0, 4900) }];
    assertLineMessages(messages);
    return messages;
  }
  const csp = cspShown(cycle);
  const collar = collarShown(cycle);
  const bubbles: unknown[] = [overviewBubble(ctx),
    ...(cycle.suggestions.length > 0 ? [ccDetailBubble(ctx)] : []),
    ...("block" in csp ? [cspDetailBubble(ctx, csp.block)] : []),
    ...("block" in collar ? [collarDetailBubble(ctx, collar.block)] : [])];
  // LINE caps a carousel at 50 KB; stay under 46 KB like packCarousels by dropping the last detail bubbles (the overview and the text
  // edition behind the details button always remain).
  const size = (value: unknown) => new TextEncoder().encode(JSON.stringify(value)).length;
  while (bubbles.length > 1 && size({ type: "carousel", contents: bubbles }) > 46_000) bubbles.pop();
  const messages: LineOutboundMessage[] = [{ type: "flex", altText: altSummary({ topic: `${cycle.ticker} ${cycle.expiry} 三種保守期權策略`,
    status: `${carried ? "前一時段報價" : "延遲報價"}，非投資建議`, next: "左右滑動查看備兌買權、賣權與領口" }),
    contents: { type: "carousel", contents: bubbles } }];
  assertLineMessages(messages);
  return messages;
}
