/** Covered-call sell suggestions (operator 2026-09-26; middle tier and current-week weekly 2026-10-11): for a holder of 100
 * shares, up to three strikes (HIGH_STRIKE, an optional MIDDLE, BALANCED) that collect premium while keeping the strike as high
 * as possible so the shares are not called away. Produced hourly by
 * scripts/build_market_quotes_options.py from delayed public option chains and sealed in `v213:options:v2`.
 * Observation only: the bot never places an order. Mirror of validate_covered_call_cycle (Python). */
import { assertLineMessages, type LineOutboundMessage } from "../line-messages";
import { splitLineText } from "../core";
import { sourceZh } from "./source-labels";
import { formatVisibleMoment } from "./line-formatters";
import {
  effectiveDays, dayMs, exchangeDate, expiryDayOpen, MONTHLY_DTE_BUCKET, monthlyRuleConsistent, shortDteNoticeZh, SHORT_DTE_NOTICE_MAX, usRegularSessionOpen, WEEKLY_DTE_BUCKET, weeklyWeekFor,
  type MonthlyRule, type WeeklyWeek,
} from "./option-recommendation-rules";
import { admitPublicOption, OptionRightsNotAdmittedError } from "./public-options-admission";
import {
  LINE_THEME as T, accentHeading, altSummary, chip, detailsButton, footerStyle, menuAction, productHeader, uiBox, uiText,
} from "./line-theme";

export interface CoveredCallSuggestion {
  role: "HIGH_STRIKE" | "MIDDLE" | "BALANCED"; strike: number; bid: number; ask: number | null; mid: number | null; limit_price: number;
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
export interface StrategyLeg { strike: number; bid: number | null; ask: number | null; limit_price: number; delta: number; delta_basis: "QUOTED" | "QUOTED_IV" | "QUOTE_IMPLIED" }
export interface SellStrategyLeg extends StrategyLeg { bid: number }
export interface BuyStrategyLeg extends StrategyLeg { ask: number }
export interface CspItem extends SellStrategyLeg {
  role: "CONSERVATIVE" | "BALANCED"; premium_per_contract: number; cash_required: number; annualized_yield: number; breakeven: number; downside_buffer: number;
}
export interface CollarItem {
  role: "CONSERVATIVE" | "BALANCED"; call: SellStrategyLeg; net_premium_per_share: number; max_loss_per_share: number; max_gain_per_share: number;
  break_even: number; worst_case_net_per_share: number;
}
/** The label every real block repeats; each value equals the cycle's own (checked). */
export interface StrategyLabel { rights_status: string; provider_id: string; quote_basis: string; timestamp: string }
export interface StrategyUnavailable { unavailable: string }
export type CspBlock = ({ suggestions: CspItem[] } & StrategyLabel) | StrategyUnavailable;
export type CollarBlock = ({ put: BuyStrategyLeg; items: CollarItem[] } & StrategyLabel) | StrategyUnavailable;
export interface CycleStrategies { cc?: StrategyUnavailable; csp?: CspBlock; collar?: CollarBlock }

export interface MonthlyQuoteObservation {
  /** Informational observation, never an admitted covered-call sell tier or an order instruction. */
  kind: "TWO_SIDED" | "NO_TWO_SIDED";
  strike: number; bid: number | null; ask: number | null; last: number | null;
  /** Bid/spot annualized, or a clearly indicative last/spot figure. Null when no source price exists. */
  annualized_yield: number | null;
  oi: number | null; volume: number | null;
}

export interface CoveredCallCycle {
  ticker: string; strategy: "COVERED_CALL"; expiry: string; dte: number; spot: number; currency: "USD" | "SEK";
  multiplier: 100; quote_basis: "delayed" | typeof PREVIOUS_SESSION_BASIS; timestamp: string; source: string; provenance: string; rights_status: string;
  /** Producer-CLAIMED join identity for public admission (never authority; absent on local candidates). */
  provider_id?: string; jurisdiction?: string; venue?: string; instrument_kind?: string; publication_scope?: string;
  /** One or two covered-call tiers; EMPTY only beside a validated monthly observation or real csp/collar block. */
  suggestions: CoveredCallSuggestion[];
  /** V21 additive; absent on older sealed rows (the card then shows the cash-secured put and the collar as no data). A block that failed
   * validation has already been replaced by {unavailable} by validateCoveredCallCycle. */
  strategies?: CycleStrategies;
  /** Observation-only monthly row after strategy screening; preserves expiry and rights checks. */
  quote_observation?: MonthlyQuoteObservation;
  /** Optional additive middle tier (role MIDDLE, strike strictly between the two suggestions); absent in older sealed rows. */
  middle_suggestion?: CoveredCallSuggestion;
  /** Exchange-local date (YYYY-MM-DD) the expiry rule was applied on, and for weekly cycles whether the expiry is in the
   * CURRENT calendar week or (only when this week has no remaining weekly) the NEXT; both absent in older sealed rows. */
  asof_date?: string; weekly_week?: WeeklyWeek;
  /** Monthly cycles only: which branch of the standard-monthly rule chose the expiry (THIRD_FRIDAY, HOLIDAY_SHIFT or LATER_LISTED); absent in older rows. */
  monthly_rule?: MonthlyRule;
}

const finite = (value: unknown): value is number => typeof value === "number" && Number.isFinite(value);
const DELTA_BASES = new Set(["QUOTED", "QUOTED_IV", "QUOTE_IMPLIED"]);
/** The high strike's assignment cap (scripts/build_market_quotes_options.py MAX_HIGH_STRIKE_DELTA). */
const MAX_HIGH_STRIKE_DELTA = 0.20;
const close = (value: number, expected: number, absoluteTolerance = 1e-4) => Number.isFinite(expected)
  && Math.abs(value - expected) <= Math.max(absoluteTolerance, Math.abs(expected) * 1e-3);

/** Required executable side stays positive; optional sides are explicit null, never zero or invented.
 * Keep the established bounded envelope for already-sealed two-sided limits. */
function validLimitQuote(bid: unknown, ask: unknown, limit: unknown, buy: boolean): boolean {
  if (!finite(limit) || limit <= 0) return false;
  if (bid !== null && !(finite(bid) && bid > 0)) return false;
  if (ask !== null && !(finite(ask) && ask > 0)) return false;
  if (buy ? !finite(ask) : !finite(bid)) return false;
  if (bid === null || ask === null) return limit === (buy ? ask : bid);
  if (!finite(bid) || !finite(ask) || bid > ask || limit < bid || limit > ask) return false;
  const mid = bid / 2 + ask / 2;
  return buy ? limit >= mid - 1e-9 && limit <= ask : limit >= bid && limit <= mid + 1e-9;
}

/** Recommendation usability must not upgrade a one-sided capture into a two-sided prior session. */
function hasOneSidedRecommendation(cycle: Record<string, unknown>): boolean {
  const oneSided = (leg: unknown) => isRecord(leg) && (leg.bid === null || leg.ask === null);
  if (Array.isArray(cycle.suggestions) && cycle.suggestions.some(oneSided)) return true;
  if (oneSided(cycle.middle_suggestion)) return true;
  const strategies = cycle.strategies;
  if (!isRecord(strategies)) return false;
  const csp = strategies.csp, collar = strategies.collar;
  return (isRecord(csp) && Array.isArray(csp.suggestions) && csp.suggestions.some(oneSided))
    || (isRecord(collar) && (oneSided(collar.put)
      || (Array.isArray(collar.items) && collar.items.some(item => isRecord(item) && oneSided(item.call)))));
}

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
 * option-recommendation-rules.ts applies), monthly 0-60 admits the nearest standard monthly of the current producer (DTE 0 is the expiry
 * day) and the 14-60 rows of the previous producer that are still sealed. */
const PERIOD_DTE_BUCKETS: Record<string, readonly [number, number]> = { weekly: WEEKLY_DTE_BUCKET, monthly: MONTHLY_DTE_BUCKET };

/** UTC midnight epoch ms of a YYYY-MM-DD calendar date, or null for an impossible date (e.g. 2026-02-30) that the shape
 * regex alone would admit. */
function parseCalendarDateUtcMidnight(raw: string): number | null {
  const ms = Date.parse(`${raw}T00:00:00Z`);
  if (!Number.isFinite(ms)) return null;
  return new Date(ms).toISOString().slice(0, 10) === raw ? ms : null;
}

/** Recompute the observation arithmetic, never trust producer-supplied percentages alone. */
function validMonthlyQuoteObservation(raw: unknown, cycle: Record<string, any>): raw is MonthlyQuoteObservation {
  if (!raw || typeof raw!=="object" || Array.isArray(raw)) return false;
  const obs=raw as Record<string,unknown>;
  const exact=["kind","strike","bid","ask","last","annualized_yield","oi","volume"];
  if (Object.keys(obs).length!==exact.length || !exact.every(key=>Object.hasOwn(obs,key))) return false;
  if (!["TWO_SIDED","NO_TWO_SIDED"].includes(String(obs.kind)) ||
    !finite(obs.strike) || obs.strike<=cycle.spot || Math.round(obs.strike*100)/100!==obs.strike ||
    !Number.isInteger(cycle.dte) || cycle.dte<0 || cycle.dte>60) return false;
  for(const key of ["oi","volume"]){
    const x=obs[key];
    if(x!==null && !(finite(x) && x>=0 && Number.isInteger(x))) return false;
  }
  let quote:number|null=null;
  if(obs.kind==="TWO_SIDED") {
    if(!finite(obs.bid) || !finite(obs.ask) || !(obs.bid>0 && obs.ask>=obs.bid) || obs.last!==null) return false;
    quote=obs.bid;
  } else {
    if(obs.bid!==null || obs.ask!==null || (obs.last!==null && !(finite(obs.last) && obs.last>0))) return false;
    quote=obs.last as number|null;
  }
  if(quote===null) return obs.annualized_yield===null;
  return finite(obs.annualized_yield) && close(obs.annualized_yield,quote/cycle.spot*365/effectiveDays(cycle.dte));
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
  if (carried && hasOneSidedRecommendation(cycle)) return null;

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

  // Selected rows have already passed the producer's expiry selector. Admit monthly 0-60 DTE (the previous producer's 14-60 rows
  // are inside it) without requiring any marker; keep weekly bounds and period binding unchanged.
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
  // Optional additive monthly_rule (never required, never weekly): the expiry must sit where the named branch says.
  if (cycle.monthly_rule !== undefined && cycle.monthly_rule !== null
    && (period === "weekly" || typeof cycle.monthly_rule !== "string" || !monthlyRuleConsistent(cycle.expiry, cycle.monthly_rule))) return null;

  // Reject old weekly-in-monthly rows; no relabelled observation path remains.
  if (Object.hasOwn(cycle, "monthly_nonstandard")) return null;
  if (period === "monthly") {
    const standard = monthlyRuleConsistent(cycle.expiry, "THIRD_FRIDAY")
      || (typeof cycle.monthly_rule === "string" && monthlyRuleConsistent(cycle.expiry, cycle.monthly_rule));
    if (!standard) return null;
  }

  const roles = cycle.suggestions.map((item: any) => item?.role).join(",");
  if (roles !== "" && roles !== "HIGH_STRIKE" && roles !== "HIGH_STRIKE,BALANCED") return null;
  /** Per-item checks shared by the two suggestions and the optional middle tier. */
  const itemValid = (item: any): boolean => {
    if (!item || typeof item !== "object") return false;
    if (!["strike", "bid", "limit_price", "premium_per_contract", "period_yield", "annualized_yield", "upside_to_strike"]
      .every(key => finite(item[key]))) return false;
    if (!(item.strike > cycle.spot) || Math.round(item.strike * 100) / 100 !== item.strike
      || !validLimitQuote(item.bid, item.ask, item.limit_price, false)) return false;
    if (item.ask === null) {
      if (item.mid !== null || item.spread_pct !== null || item.delta_basis === "QUOTE_IMPLIED") return false;
      if (item.delta !== null && item.delta !== undefined && !["QUOTED", "QUOTED_IV"].includes(item.delta_basis)) return false;
    } else if (!finite(item.mid) || !close(item.mid, item.bid / 2 + item.ask / 2)) return false;
    // Producer rounds per-contract money to cents, including when the bounded limit clamps to an off-tick Bid.
    if (!close(item.premium_per_contract, item.limit_price * 100, 0.005 + 1e-9) || !close(item.period_yield, item.limit_price / cycle.spot)
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
  if(cycle.quote_observation!==undefined){
    // The observed call is never an executable sell tier; the put-side strategies,
    // when present, retain their independent strict validator and source binding.
    if(period!=="monthly" || cycle.suggestions.length!==0 ||
      cycle.middle_suggestion!==undefined || !validMonthlyQuoteObservation(cycle.quote_observation,cycle)) return null;
    if(cycle.strategies===undefined) return cycle as CoveredCallCycle;
    const kept=sanitizeStrategies(cycle, true);
    return kept===null || kept===undefined ? null : {...cycle,strategies:kept} as CoveredCallCycle;
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

/** One quoted leg: exact keys are checked by the caller, cent-exact OTM strike, executable quote
 * side, bounded limit, absolute delta in the band, and a supported (never fabricated) delta basis. */
function legValid(leg: unknown, spot: number, kind: { buy: boolean; put: boolean; band: readonly [number, number] }): boolean {
  if (!isRecord(leg) || !LEG_KEYS.every(key => Object.hasOwn(leg, key))) return false;
  if (!["strike", "limit_price", "delta"].every(key => finite(leg[key]))) return false;
  if (!(kind.put ? leg.strike > 0 && leg.strike < spot : leg.strike > spot && spot > 0)
    || Math.round(leg.strike * 100) / 100 !== leg.strike) return false;
  if (!validLimitQuote(leg.bid, leg.ask, leg.limit_price, kind.buy)) return false;
  if ((leg.bid === null || leg.ask === null) && leg.delta_basis === "QUOTE_IMPLIED") return false;
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
      if (!close(item.premium_per_contract, item.limit_price * 100, 0.005 + 1e-9) || !close(item.cash_required, item.strike * 100)
        || !close(item.annualized_yield, item.limit_price / item.strike * 365 / days) || !close(item.breakeven, item.strike - item.limit_price)
        || !close(item.downside_buffer, 1 - item.strike / spot)) return false;
    }
    return items.length === 1 || items[1].strike > items[0].strike;
  }
  const items = labelValid(block, cycle, "items", ["put"]);
  if (!items || !isRecord(block.put) || !hasExactKeys(block.put, LEG_KEYS) || !legValid(block.put, spot, { buy: true, put: true, band: PROTECTIVE_PUT_DELTA_BAND })) return false;
  const put = block.put as BuyStrategyLeg;
  for (const item of items) {
    if (!hasExactKeys(item, COLLAR_KEYS) || !isRecord(item.call) || !hasExactKeys(item.call, LEG_KEYS)
      || !legValid(item.call, spot, { buy: false, put: false, band: CONSERVATIVE_DELTA_BAND })) return false;
    if (!["net_premium_per_share", "max_loss_per_share", "max_gain_per_share", "break_even", "worst_case_net_per_share"].every(key => finite(item[key]))) return false;
    const call = item.call as SellStrategyLeg;
    const net = call.limit_price - put.limit_price;
    if (!close(item.net_premium_per_share, net) || !close(item.max_loss_per_share, spot - put.strike - net)
      || !close(item.max_gain_per_share, call.strike - spot + net) || !close(item.break_even, spot - net)
      || !close(item.worst_case_net_per_share, call.bid - put.ask)) return false;
  }
  return items.length === 1 || items[1].call.strike < items[0].call.strike;
}

/** The cycle's strategies after block-level degradation: undefined when there is none (absent, not an object, or nothing left), null when
 * the CYCLE is invalid (a covered call beside a `cc` block, no covered call without a valid `cc` unavailable block, or no covered call and
 * no real csp/collar block unless a monthly observation has already validated). Bad csp/collar blocks degrade independently. */
function sanitizeStrategies(cycle: Record<string, unknown>, validatedObservation = false): CycleStrategies | null | undefined {
  const raw = cycle.strategies;
  if (!isRecord(raw)) return undefined;
  if (!Array.isArray(cycle.suggestions)) return null;
  const kept: Record<string, unknown> = {};
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
  if (noCoveredCall && !validatedObservation && !real("csp") && !real("collar")) return null;
  return kept as CycleStrategies;
}

const money = (value: number, currency: string) => currency === "USD" ? `$${value.toFixed(2)}` : `${value.toFixed(2)} ${currency}`;
const pct = (value: number, digits = 1) => `${(value * 100).toFixed(digits)}%`;
const quoteMoney = (value: number | null, currency: string) => value === null ? "未提供" : money(value, currency);
const quoteMid = (bid: number | null, ask: number | null) => bid === null || ask === null ? null : bid / 2 + ask / 2;

/** Always derive visible spread from the actual validated sides, never a supplied percentage. */
function liquidityZh(bid: number | null, ask: number | null): string {
  const mid = quoteMid(bid, ask);
  if (bid === null || ask === null || mid === null) return "流動性警示：單邊報價；中價／價差無法計算";
  const spread = (ask - bid) / mid;
  return `價差占中價 ${pct(spread, 0)}${spread > 0.25 ? "；流動性警示：價差寬，限價可能無法成交" : ""}`;
}
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
  HIGH_STRIKE: ["高履約價（不易被賣掉）", "價外、有有效 Bid 且 Delta 不高於 0.20 的最高履約價（不設年化收益下限）；股價需上漲超過右側幅度才會被指派。"],
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

/** Period marker: rows that carry weekly_week say which calendar week the expiry is in; rows that carry monthly_rule say when the
 * monthly is not the plain third Friday of the nearest month. */
function weekNoteZh(cycle: CoveredCallCycle): string | null {
  if (cycle.weekly_week === "CURRENT") return "本週到期";
  if (cycle.weekly_week === "NEXT") return "本週已無剩餘週選，顯示下週最早到期日";
  if (cycle.monthly_rule === "HOLIDAY_SHIFT") return "該月第三個星期五無到期日，顯示當週最後一個上市到期日";
  if (cycle.monthly_rule === "LATER_LISTED") return "本月標準月選已到期或未上市，顯示下一個標準月選";
  return null;
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
// Overview, then the available strategy details and a single final disclosure. A strategy without data keeps its overview row
// ("無資料") and has no detail bubble. Everything shown is a quote or a figure recomputed by the validator; nothing is advice.
const NO_STRATEGIES_REASON = "封存資料未提供此策略的篩選結果；無法判定賣權鏈或報價是否可用";
const CSP_TITLE = "現金擔保賣權（備足現金賣出賣權）";
const COLLAR_TITLE = "領口策略（持股＋買保護賣權＋賣買權）";
const CC_TITLE = "備兌買權（持股賣出買權）";

type CspData = Extract<CspBlock, { suggestions: CspItem[] }>;
type CollarData = Extract<CollarBlock, { items: CollarItem[] }>;
type Shown<T> = { block: T } | { none: string };

function cspShown(cycle: CoveredCallCycle): Shown<CspData> {
  if (!cycle.strategies) return { none: NO_STRATEGIES_REASON };
  const block = cycle.strategies.csp;
  if (!block) return { none: NO_STRATEGIES_REASON };
  return "unavailable" in block ? { none: block.unavailable } : { block };
}
function collarShown(cycle: CoveredCallCycle): Shown<CollarData> {
  if (!cycle.strategies) return { none: NO_STRATEGIES_REASON };
  const block = cycle.strategies.collar;
  if (!block) return { none: NO_STRATEGIES_REASON };
  return "unavailable" in block ? { none: block.unavailable } : { block };
}
const ccNone = (cycle: CoveredCallCycle) => cycle.strategies?.cc?.unavailable ?? "本輪沒有符合條件的備兌買權";

const BASIS_ZH = { QUOTED: "交易所提供", QUOTED_IV: "模型值，依報價隱含波動率", QUOTE_IMPLIED: "模型值，由買賣報價反推" } as const;
const legDeltaZh = (leg: StrategyLeg) => `Delta ${leg.delta.toFixed(2)}（約 ${Math.round(leg.delta * 100)}%，${BASIS_ZH[leg.delta_basis]}）`;
const bidAskZh = (leg: Pick<StrategyLeg, "bid" | "ask">, currency: string) => `Bid ${quoteMoney(leg.bid, currency)}／中價 ${quoteMoney(quoteMid(leg.bid, leg.ask), currency)}／Ask ${quoteMoney(leg.ask, currency)}`;
const tierNameZh = (role: string) => role === "CONSERVATIVE" ? "保守型（Delta 約 0.20 起）" : "平衡型（收較多權利金）";
const signedMoney = (value: number, currency: string) => `${value < 0 ? "-" : "+"}${money(Math.abs(value), currency)}`;

interface CardContext {
  cycle: CoveredCallCycle; periodLabel: string; carried: boolean; carriedLabel: string | null; operatorNotice: string | null; monthlyNotice: string | null; dteZh: string; spotLabel: string;
}
function cardContext(cycle: CoveredCallCycle, periodLabel: string): CardContext {
  const carried = cycle.quote_basis === PREVIOUS_SESSION_BASIS;
  return { cycle, periodLabel, carried, carriedLabel: carried ? previousSessionLabelZh(cycle.timestamp) : null,
    monthlyNotice: periodLabel === "每月期權" ? shortDteNoticeZh(cycle.dte) : null,
    operatorNotice: null, dteZh: carried ? `擷取時 ${cycle.dte} 天` : cycle.dte === 0 ? "今日到期" : `${cycle.dte} 天`, spotLabel: carried ? "前一時段現價" : "現價" };
}

/** Collar figures per contract (x100 of the per-share values the validator recomputed). */
const perContract = (value: number) => value * 100;


function strategyHero(label: string, value: string) {
  return uiBox([{ type: "text", size: "3xl", weight: "bold", wrap: true, contents: [
    { type: "span", text: `${label}\n`, size: "xs", color: T.subtle, weight: "regular" },
    { type: "span", text: value, size: "3xl", color: T.ink, weight: "bold" },
  ] }], { backgroundColor: T.accentTint, cornerRadius: "md", paddingAll: "sm" });
}

function strategyTableRow(values: string[], first = false) {
  return uiBox(values.map((value, index) => uiText(value, "xs", T.ink,
    { flex: 1, align: index ? "end" : "start", weight: "bold" })), {
    layout: "horizontal", backgroundColor: first ? T.accentTint : T.soft,
    cornerRadius: "md", paddingAll: "sm", spacing: "sm",
  });
}

function overviewRows(ctx: CardContext) {
  const { cycle } = ctx;
  const cc = displayTiers(cycle)[0];
  const csp = cspShown(cycle);
  const collar = collarShown(cycle);
  const row = (name: string, value: string) => uiBox([
    uiText(name, "xs", T.ink, { flex: 1, weight: "bold" }),
    uiText(value, "xs", T.ink, { flex: 2, align: "end" }),
  ], { layout: "horizontal", backgroundColor: T.soft, cornerRadius: "md", paddingAll: "sm", spacing: "sm" });
  return [
    row("備兌買權", cc ? `履約 ${money(cc.strike, cycle.currency)}｜年化 ${pct(cc.annualized_yield)}` : "無資料"),
    row("現金擔保賣權", "none" in csp ? "無資料" : `履約 ${money(csp.block.suggestions[0]!.strike, cycle.currency)}｜年化 ${pct(csp.block.suggestions[0]!.annualized_yield)}`),
    row("領口策略", "none" in collar ? "無資料" : `Call ${money(collar.block.items[0]!.call.strike, cycle.currency)}｜淨 ${signedMoney(perContract(collar.block.items[0]!.net_premium_per_share), cycle.currency)}`),
  ];
}



/** Header chips shared by every bubble. */
function headerBox(ctx: CardContext, eyebrow: string) {
  const { cycle } = ctx;
  return productHeader(`${eyebrow} · ${ctx.periodLabel} · ${ctx.carried ? "前一時段報價" : "延遲報價"}`, `${cycle.ticker}｜到期 ${cycle.expiry}`, [
    uiBox([chip(ctx.dteZh), chip(`${ctx.spotLabel} ${money(cycle.spot, cycle.currency)}`), chip(`計價 ${cycle.currency}`)], { layout: "horizontal", spacing: "sm" }),
    ...(weekNoteZh(cycle) ? [uiBox([chip(weekNoteZh(cycle)!)], { layout: "horizontal", spacing: "sm" })] : []),
    ...(ctx.monthlyNotice ? [chip(ctx.monthlyNotice, T.cycleCaution, T.cycleCautionText)] : []),
  ]);
}

const LIMIT_SELECTION_RULE = "LIMIT：雙邊由中價向下取0.01起掛；未成交每次降0.01，不低於Bid；不保證成交";
const BUY_LIMIT_RULE = "LIMIT：買進Put由中價向上取0.01起掛，不高於Ask；不保證成交";
function limitRuleZh(leg: Pick<StrategyLeg, "bid" | "ask">, buy = false): string {
  if (leg.bid === null || leg.ask === null) return buy
    ? "LIMIT：缺Bid，中價／價差無法計算；以Ask作保守參考，不高於Ask；不保證成交"
    : "LIMIT：缺Ask，中價／價差無法計算；以Bid作保守參考；未成交不再下調至Bid以下；不保證成交";
  return buy ? BUY_LIMIT_RULE : LIMIT_SELECTION_RULE;
}

function bidCaseZh(bid: number, capital: number, cycle: CoveredCallCycle): string {
  const period = bid / capital;
  return `Bid情境：每口權利金 ${money(bid * 100, cycle.currency)}｜期間收益 ${pct(period, 2)}｜年化 ${pct(period * 365 / effectiveDays(cycle.dte))}（非保證）`;
}

/** These exact tier details are shown in both Text and the strategy's visible Flex bubble. */
function ccTierLines(cycle: CoveredCallCycle, item: CoveredCallSuggestion, index: number): string[] {
  return [
    tierTitle(item, index),
    `履約價 ${money(item.strike, cycle.currency)}（距現價 +${pct(item.upside_to_strike)}）｜建議賣出限價 ${money(item.limit_price, cycle.currency)}（${bidAskZh(item, cycle.currency)}）`,
    limitRuleZh(item),
    `LIMIT每口權利金 ${money(item.premium_per_contract, cycle.currency)}｜期間收益 ${pct(item.period_yield, 2)}｜年化 ${pct(item.annualized_yield)}｜Delta ${item.delta === null || item.delta === undefined ? "未提供" : `${item.delta.toFixed(2)}${deltaBasisZh(item) ? `（${deltaBasisZh(item)}）` : ""}`}`,
    bidCaseZh(item.bid, cycle.spot, cycle),
    `流動性：OI ${countZh(item.oi)}｜成交量 ${countZh(item.volume)}｜${liquidityZh(item.bid, item.ask)}`,
  ];
}

function cspTierLines(cycle: CoveredCallCycle, item: CspItem, index: number): string[] {
  const cur = cycle.currency;
  return [
    `建議${ORDINAL_ZH[index] ?? String(index + 1)}：${tierNameZh(item.role)}`,
    `履約價 ${money(item.strike, cur)}（低於現價 ${pct(item.downside_buffer)}）｜建議賣出限價 ${money(item.limit_price, cur)}（${bidAskZh(item, cur)}）`,
    limitRuleZh(item), liquidityZh(item.bid, item.ask),
    `LIMIT每口權利金 ${money(item.premium_per_contract, cur)}｜需備現金 ${money(item.cash_required, cur)}｜期間收益 ${pct(item.limit_price / item.strike, 2)}｜年化 ${pct(item.annualized_yield)}（以備妥現金計）｜損益兩平 ${money(item.breakeven, cur)}`,
    bidCaseZh(item.bid, item.strike, cycle),
    `被指派機率參考：${legDeltaZh(item)}`,
  ];
}

function collarPutLines(cycle: CoveredCallCycle, put: BuyStrategyLeg): string[] {
  return [
    `保護賣權（買進）履約價 ${money(put.strike, cycle.currency)}｜建議買入限價 ${money(put.limit_price, cycle.currency)}（${bidAskZh(put, cycle.currency)}）｜${legDeltaZh(put)}`,
    limitRuleZh(put, true), liquidityZh(put.bid, put.ask),
  ];
}

function collarTierLines(cycle: CoveredCallCycle, put: BuyStrategyLeg, item: CollarItem, index: number): string[] {
  const cur = cycle.currency;
  const net = perContract(item.net_premium_per_share);
  const conservative = item.call.bid - put.ask;
  const annualize = 365 / effectiveDays(cycle.dte) / cycle.spot;
  return [
    `建議${ORDINAL_ZH[index] ?? String(index + 1)}：${tierNameZh(item.role)}`,
    `賣出買權履約價 ${money(item.call.strike, cur)}｜建議賣出限價 ${money(item.call.limit_price, cur)}（${bidAskZh(item.call, cur)}）｜${legDeltaZh(item.call)}`,
    limitRuleZh(item.call), liquidityZh(item.call.bid, item.call.ask),
    `LIMIT每口淨權利金（${net >= 0 ? "收入" : "支出"}）${money(Math.abs(net), cur)}｜淨權利金年化 ${pct(item.net_premium_per_share * annualize)}`,
    `Bid情境（Call Bid－Put Ask）：每口淨權利金 ${signedMoney(perContract(conservative), cur)}｜淨權利金年化 ${pct(conservative * annualize)}（非保證，非總報酬）`,
    `最大損失 ${money(perContract(item.max_loss_per_share), cur)}／口｜最大獲利 ${money(perContract(item.max_gain_per_share), cur)}／口｜損益兩平 ${money(item.break_even, cur)}`,
  ];
}

/** Keep immediate warnings on each card; complete qualifications are in the final bubble. */
function footerBox(risk: string, buttons: unknown[] = []) {
  return uiBox([
    { type: "text", size: "xxs", color: T.subtle, wrap: true, contents: [
      { type: "span", text: "風險｜", color: T.subtle, weight: "bold" },
      { type: "span", text: `${risk}；非投資建議；不下單`, color: T.subtle },
    ] },
    ...buttons,
  ], footerStyle);
}
const detailButtons = (ctx: CardContext) => [
  detailsButton(`${ctx.cycle.ticker} 完整報價與出處`, `${ctx.cycle.ticker} ${ctx.periodLabel.includes("每月") ? "每月" : "每週"}期權 文字`),
  menuAction("期權策略教學", "期權教學"),
];

function overviewBubble(ctx: CardContext) {
  const cycle = ctx.cycle;
  const available = Number(displayTiers(cycle).length > 0) + Number("block" in cspShown(cycle)) + Number("block" in collarShown(cycle));
  const risk = "可能虧損、指派及漲幅封頂";
  return {
    type: "bubble", size: "mega", header: headerBox(ctx, "三種保守期權策略"),
    body: uiBox([uiBox([strategyHero("可用策略", `${available} / 3`), accentHeading("策略對照")]),
      uiBox(overviewRows(ctx)), uiText("賣權年化以備妥現金計；各檔報價見策略頁，出處與缺漏原因見末頁", "xxs", T.subtle)],
      { paddingAll: "lg", spacing: "sm" }),
    footer: footerBox(risk, detailButtons(ctx)),
  };
}
function ccDetailBubble(ctx: CardContext) {
  const { cycle } = ctx;
  const tiers = displayTiers(cycle);
  const rows = tiers.map((item, index) => uiBox([
    uiText(`${["①", "②", "③"][index] ?? ""}${money(item.strike, cycle.currency)}`, "xs", T.ink, { flex: 1, weight: "bold" }),
    uiText(money(item.premium_per_contract, cycle.currency), "xs", T.ink, { flex: 1, align: "end", weight: "bold" }),
    uiText(pct(item.annualized_yield), "xs", T.ink, { flex: 1, align: "end", weight: "bold" }),
  ], { layout: "horizontal", backgroundColor: index === 0 ? T.accentTint : T.soft,
    cornerRadius: "md", paddingAll: "sm", spacing: "sm" }));
  return {
    type: "bubble", size: "mega", header: headerBox(ctx, "備兌買權"),
    body: uiBox([
      uiBox([
      ...(tiers.length ? [uiBox([{ type: "text", size: "3xl", weight: "bold", wrap: true, contents: [
        { type: "span", text: "首檔年化權利金\n", size: "xs", color: T.subtle, weight: "regular" },
        { type: "span", text: pct(tiers[0]!.annualized_yield), size: "3xl", color: T.ink, weight: "bold" },
      ] }], { backgroundColor: T.accentTint, cornerRadius: "md", paddingAll: "sm" })] : []),
      accentHeading("履約價｜LIMIT權利金／口｜年化"),
      ], { spacing: "sm" }),
      uiBox(rows.length ? rows : [chip("無符合檔位")], { spacing: "xs" }),
      ...tiers.map((item, index) => uiText(ccTierLines(cycle, item, index).join("\n"), "xs", T.ink)),
    ], { paddingAll: "lg", spacing: "md" }),
    footer: footerBox("正股仍有下跌風險；可能被指派、漲幅封頂", detailButtons(ctx)),
  };
}
function cspDetailBubble(ctx: CardContext, block: CspData) {
  const { cycle } = ctx;
  const rows = block.suggestions.map((item, index) => strategyTableRow([
    `${index === 0 ? "①" : "②"}${money(item.strike, cycle.currency)}`,
    money(item.premium_per_contract, cycle.currency), pct(item.annualized_yield),
  ], index === 0));
  return {
    type: "bubble", size: "mega", header: headerBox(ctx, "現金擔保賣權"),
    body: uiBox([uiBox([strategyHero("首檔年化（以備妥現金計）", pct(block.suggestions[0]!.annualized_yield)),
      accentHeading("履約價｜LIMIT權利金／口｜年化")]), uiBox(rows),
      ...block.suggestions.map((item, index) => uiText(cspTierLines(cycle, item, index).join("\n"), "xs", T.ink)),
    ], { paddingAll: "lg", spacing: "sm" }),
    footer: footerBox("可能被指派買股；損失可超過權利金", detailButtons(ctx)),
  };
}
function collarDetailBubble(ctx: CardContext, block: CollarData) {
  const { cycle } = ctx;
  const first = block.items[0]!;
  const rows = block.items.map((item, index) => strategyTableRow([
    `${index === 0 ? "①" : "②"}${money(item.call.strike, cycle.currency)}`,
    signedMoney(perContract(item.net_premium_per_share), cycle.currency),
    money(perContract(item.max_loss_per_share), cycle.currency),
  ], index === 0));
  return {
    type: "bubble", size: "mega", header: headerBox(ctx, "領口策略"),
    body: uiBox([uiBox([strategyHero("首檔淨權利金／口（買賣相抵）", signedMoney(perContract(first.net_premium_per_share), cycle.currency)),
      accentHeading("Call履約｜淨權利金／口｜最大損失／口")]), uiBox(rows),
      uiText(collarPutLines(cycle, block.put).join("\n"), "xs", T.ink),
      ...block.items.map((item, index) => uiText(collarTierLines(cycle, block.put, item, index).join("\n"), "xs", T.ink)),
      uiText("每組100股＋買1口Put＋賣1口Call", "xxs", T.subtle),
    ], { paddingAll: "lg", spacing: "sm" }),
    footer: footerBox("保護需付費；下跌有界、上漲封頂", detailButtons(ctx)),
  };
}

/** Shared source, rights, formulas and risk disclosures; tier details stay on their strategy bubbles. */
function disclosureBubble(ctx: CardContext) {
  const { cycle } = ctx;
  const tiers = displayTiers(cycle);
  const deltaBases = [...new Set(tiers.map(deltaBasisZh).filter((basis): basis is string => basis !== null))];
  const csp = cspShown(cycle);
  const collar = collarShown(cycle);
  const lines = [
    `來源：${sourceZh(cycle.source)}，${ctx.carried ? "前一交易時段擷取時間" : "擷取時間"} ${formatVisibleMoment(cycle.timestamp)}（報價時間未提供）${cycle.provenance}`,
    ...(ctx.operatorNotice ? [ctx.operatorNotice] : []),
    ...(ctx.carriedLabel ? [ctx.carriedLabel] : []),
    "公開延遲；非投資建議；年化非保證；不下單",
    ...(tiers.length ? [
      ...(deltaBases.length === 1 ? [`Delta ${deltaBases[0]}，僅供指派機率參考`] : deltaBases.length > 1 ? ["Delta 僅供指派機率參考"] : []),
      "期間收益＝限價÷現價；年化收益＝期間收益×365÷DTE",
      "最高履約價為價外、Delta 不高於 0.20 且有有效 Bid 者，不設年化收益下限；超履約可能被指派、上漲收益封頂；正股仍有下跌風險",
    ] : []),
    ...("block" in csp ? ["跌破履約價可能被指派；被指派時需以履約價買進正股（100股），損失可大於權利金"] : []),
    ...("block" in collar ? ["保護賣權需付權利金；下跌有界，上漲於Call履約價封頂；最大盈虧為到期估算"] : []),
    ...(cycle.suggestions.length === 0 ? [`【備兌買權】無資料：${ccNone(cycle)}`] : []),
    ...("none" in csp ? [`【${CSP_TITLE}】無資料：${csp.none}`] : []),
    ...("none" in collar ? [`【${COLLAR_TITLE}】無資料：${collar.none}`] : []),
    "Bid情境是報價側保守比較，非保證成交或總報酬；領口淨權利金年化＝淨額÷現價×365÷至少1日",
    ...(cycle.dte <= SHORT_DTE_NOTICE_MAX ? ["短期年化至少按1日換算；數字放大，僅供比較"] : []),
  ];
  return {
    type: "bubble", size: "mega",
    header: productHeader("期權策略", "資料來源與說明"),
    body: uiBox(lines.map(line => uiText(line, "xxs", T.subtle)), { paddingAll: "lg", spacing: "sm" }),
  };
}

/** The strategies in text form (the text edition and the full detail behind the details button). */
function textStrategyLines(cycle: CoveredCallCycle): string[] {
  const lines: string[] = [];
  if (cycle.suggestions.length === 0) lines.push(`【備兌買權】無資料：${ccNone(cycle)}`);
  const csp = cspShown(cycle);
  if ("none" in csp) lines.push(`【${CSP_TITLE}】無資料：${csp.none}`);
  else {
    lines.push(`【${CSP_TITLE}】前提：賣出 1 口賣權並備足履約價 × 100 的現金；股價跌破履約價可能被指派；被指派時需以履約價買進正股（100股）。`);
    csp.block.suggestions.forEach((item, index) => lines.push(cspTierLines(cycle, item, index).join("\n")));
  }
  const collar = collarShown(cycle);
  if ("none" in collar) lines.push(`【${COLLAR_TITLE}】無資料：${collar.none}`);
  else {
    const { put } = collar.block;
    lines.push(`【${COLLAR_TITLE}】前提：持有 100 股，買進 1 口賣權並賣出 1 口買權；保護賣權需付權利金，下跌損失以保護賣權為界，上漲收益封頂。`,
      collarPutLines(cycle, put).join("\n"));
    collar.block.items.forEach((item, index) => lines.push(collarTierLines(cycle, put, item, index).join("\n")));
  }
  return lines;
}


function monthlyObservationMessages(cycle:CoveredCallCycle,style:"flex"|"text",operatorAccepted:boolean):LineOutboundMessage[] {
  const o=cycle.quote_observation!;
  const csp=cspShown(cycle), collar=collarShown(cycle);
  const hasBid=o.kind==="TWO_SIDED";
  const shortNotice=shortDteNoticeZh(cycle.dte);
  const rate=o.annualized_yield===null?"無可用權利金價，年化不計":pct(o.annualized_yield);
  const eligibility=hasBid ? "未符合保守策略篩選，非策略" : "無雙邊報價，非策略";
  const band=hasBid ? "Bid "+money(o.bid!,cycle.currency)+"／Ask "+money(o.ask!,cycle.currency)
    : "無雙邊報價；Last "+(o.last!==null?money(o.last,cycle.currency):"來源未提供");
  const premium=hasBid?"以Bid估算、非保證":"由Last推算、無雙邊報價、不可執行";
  const txt=[
    "【每月期權｜上市買權報價觀察（非交易建議）】"+cycle.ticker,
    "到期 "+cycle.expiry+"（DTE "+cycle.dte+"）｜履約價 "+money(o.strike,cycle.currency),
    band+"｜參考年化 "+rate+"（"+premium+"；"+eligibility+"）",
    "OI "+countZh(o.oi)+"｜成交量 "+countZh(o.volume),
    ...(shortNotice ? [shortNotice] : []),
    "來源 "+sourceZh(cycle.source)+"｜擷取 "+formatVisibleMoment(cycle.timestamp),
    "延遲來源觀察，非可執行報價；不自動下單。"
  ].concat(textStrategyLines(cycle),operatorAccepted?[OPERATOR_ACCEPTED_NOTICE_ZH]:[]);
  if(style==="text"){
    const messages: LineOutboundMessage[] = splitLineText(txt.join("\n")).map(text => ({ type: "text", text }));
    assertLineMessages(messages);
    return messages;
  }
  const bubble={type:"bubble",size:"mega",
    header:productHeader("每月期權・報價觀察","到期 "+cycle.expiry,[
      uiText(cycle.ticker+"｜DTE "+cycle.dte+"｜"+cycle.currency,"xxs",T.headerMuted)]),
    body:uiBox([
      uiText("履約價 "+money(o.strike,cycle.currency),"lg",T.ink,{weight:"bold"}),
      uiText(band,"sm",T.ink),uiText("參考年化 "+rate,"sm",T.ink,{weight:"bold"}),
      chip(eligibility,T.soft,T.subtle),
      uiText("期限 "+cycle.expiry+"｜"+premium,"xs",T.muted),
      ...(shortNotice ? [uiText(shortNotice,"xs",T.muted)] : []),
      uiText("OI "+countZh(o.oi)+"｜成交量 "+countZh(o.volume),"xs",T.subtle),
      uiText("擷取 "+formatVisibleMoment(cycle.timestamp)+"｜"+sourceZh(cycle.source),"xxs",T.subtle),
      uiText("備兌買權："+ccNone(cycle),"xs",T.subtle),
      uiText("現金擔保賣權："+("none" in csp ? csp.none : "已核驗獨立策略報價"),"xs",T.subtle),
      uiText("領口策略："+("none" in collar ? collar.none : "已核驗獨立策略報價"),"xs",T.subtle),
      ...(operatorAccepted?[uiText(OPERATOR_ACCEPTED_NOTICE_ZH,"xxs",T.subtle)]:[])
    ],{paddingAll:"lg",spacing:"sm"}),
    footer:footerBox("報價非可執行，流動性與指派風險；非投資建議、不下單")};
  const messages:LineOutboundMessage[]=[{type:"flex",
    altText:altSummary({topic:cycle.ticker+" 月期權報價觀察",status:eligibility,next:"查看文字來源"}),
    contents:{type:"carousel",contents:[
      bubble,
      ...("block" in csp ? [cspDetailBubble(cardContext(cycle,"每月期權"), csp.block)] : []),
      ...("block" in collar ? [collarDetailBubble(cardContext(cycle,"每月期權"), collar.block)] : []),
    ]}}];
  assertLineMessages(messages);
  return messages;
}

export function buildCoveredCallMessages(cycle: CoveredCallCycle, periodLabel: string, style: "flex" | "text"): LineOutboundMessage[] {
  // Independent public-rights guard (validateCoveredCallCycle stays format-only for local data): the trusted catalog decides, never
  // rights_status, source text or a caller flag, so a new caller cannot bypass the loader's enforcement.
  // Judged against the real current time: if the review window closes after the loader admitted the row, this dedicated typed error
  // (the only one a public caller converts to an unavailable report) denies instead of rendering.
  const admission = admitPublicOption(cycle);
  if (!admission.ok) throw new OptionRightsNotAdmittedError();
  if(cycle.quote_observation) return monthlyObservationMessages(cycle,style,admission.operator_accepted===true);
  const ctx = cardContext(cycle, periodLabel);
  ctx.operatorNotice = admission.operator_accepted === true ? OPERATOR_ACCEPTED_NOTICE_ZH : null;
  const { carried, carriedLabel, operatorNotice, dteZh, spotLabel } = ctx;
  if (style === "text") {
    const lines = [
      `【${cycle.suggestions.length > 0 ? "備兌買權建議" : "期權策略"}｜${cycle.ticker} ${periodLabel}】到期 ${cycle.expiry}（${carried ? dteZh : `${cycle.dte} 天`}）｜${spotLabel} ${money(cycle.spot, cycle.currency)}（計價 ${cycle.currency}）`,
      ...(carriedLabel ? [carriedLabel] : []),
      ...(weekNoteZh(cycle) ? [`${weekNoteZh(cycle)}${cycle.asof_date ? `（以交易所當地日期 ${cycle.asof_date} 判斷）` : ""}`] : []),
      ...(shortDteNoticeZh(cycle.dte) ? [shortDteNoticeZh(cycle.dte)!] : []),
      ...(cycle.suggestions.length > 0 ? [`【${CC_TITLE}】前提：持有 100 股、賣出 1 口買權；股價超過履約價時可能被指派，上漲收益封頂於履約價。`, "期間收益＝限價÷現價；年化收益＝期間收益×365÷DTE"] : []),
      ...displayTiers(cycle).map((item, index) => ccTierLines(cycle, item, index).join("\n")),
      ...textStrategyLines(cycle),
      `來源：${sourceZh(cycle.source)}（延遲報價，${carried ? "前一交易時段擷取時間" : "擷取時間"} ${formatVisibleMoment(cycle.timestamp)}；來源報價時間未提供）${cycle.provenance}`,
      ...(operatorNotice ? [operatorNotice] : []),
      "公開行情觀察，非個人化投資建議；延遲／非即時可執行；年化收益非保證報酬；正股仍承擔下跌風險；賣出賣權可能被指派買進正股；本服務不下單。",
    ];
    const messages: LineOutboundMessage[] = splitLineText(lines.join("\n")).map(text => ({ type: "text", text }));
    assertLineMessages(messages);
    return messages;
  }
  const csp = cspShown(cycle);
  const collar = collarShown(cycle);
  const bubbles: unknown[] = [overviewBubble(ctx),
    ...(cycle.suggestions.length > 0 ? [ccDetailBubble(ctx)] : []),
    ...("block" in csp ? [cspDetailBubble(ctx, csp.block)] : []),
    ...("block" in collar ? [collarDetailBubble(ctx, collar.block)] : []),
    disclosureBubble(ctx)];
  const messages: LineOutboundMessage[] = [{ type: "flex", altText: altSummary({ topic: `${cycle.ticker} ${cycle.expiry} 三種保守期權策略`,
    status: `${carried ? "前一時段報價" : "延遲報價"}，非投資建議`, next: "左右滑動查看備兌買權、賣權與領口" }),
    contents: { type: "carousel", contents: bubbles } }];
  assertLineMessages(messages);
  return messages;
}
