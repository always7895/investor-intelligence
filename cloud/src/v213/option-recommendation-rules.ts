/** Shared option-recommendation rules (operator 2026-10-11): the current-week weekly expiry and the middle strike tier.
 * Twin of scripts/option_recommendation_rules.py (same constants and rules; cloud/test/v213-options-tiers-weekly.test.ts pins
 * the parity). Pure functions, no I/O; the exchange clock uses explicit DST rules, not Intl.
 *
 * WEEKLY (calendar week, exchange local, Monday-Sunday): the earliest listed expiry from the as-of date through that week's
 * Sunday; only when none remains (weekend, after the week's last weekly, the expiry day after the session close) the earliest
 * listed expiry of the NEXT calendar week; nothing later is ever a weekly. Monthly is unchanged (21-45 DTE, nearest 30).
 * ANNUALIZATION: days = max(dte, 1), so DTE 0 never divides by zero and is never annualized over under one day; DTE 0-2 is
 * labelled on the card. MIDDLE tier: a strike strictly between the HIGH_STRIKE and BALANCED strikes. */

export const WEEKLY_DTE_BUCKET: readonly [number, number] = [0, 14];   // outer bound; the exact rule is the calendar-week rule
export const MONTHLY_DTE_BUCKET: readonly [number, number] = [21, 45];
export const MONTHLY_TARGET_DTE = 30;
export const MIN_ANNUALIZATION_DAYS = 1;
export const SHORT_DTE_NOTICE_MAX = 2;
export const MIDDLE_DELTA = 0.25;
export const MIDDLE_MONEYNESS = 1.025;
export type WeeklyWeek = "CURRENT" | "NEXT";
export type OptionVenue = "US" | "STOCKHOLM" | "TAIFEX";
/** Regular-session close in exchange-local minutes after midnight (expiry-day cut-off; no holiday calendar is inferred). */
export const EXPIRY_DAY_CLOSE_LOCAL_MINUTES: Readonly<Record<OptionVenue, number>> = { US: 16 * 60, STOCKHOLM: 17 * 60 + 30, TAIFEX: 13 * 60 + 30 };

const DAY_MS = 86_400_000;

export function effectiveDays(dte: number): number {
  return Math.max(Math.trunc(dte), MIN_ANNUALIZATION_DAYS);
}

/** UTC-midnight epoch ms of a real YYYY-MM-DD date, or null for a malformed or impossible one. */
export function dayMs(iso: unknown): number | null {
  if (typeof iso !== "string" || !/^\d{4}-\d{2}-\d{2}$/.test(iso)) return null;
  const ms = Date.parse(`${iso}T00:00:00Z`);
  return Number.isFinite(ms) && new Date(ms).toISOString().slice(0, 10) === iso ? ms : null;
}

export const isoDay = (ms: number): string => new Date(ms).toISOString().slice(0, 10);
/** Monday = 0 .. Sunday = 6. */
const mondayIndex = (ms: number): number => (new Date(ms).getUTCDay() + 6) % 7;

/** nth (1-based) or last (nth = -1) given weekday (Monday = 0) of a month (month 1-12), as UTC-midnight ms. */
function nthWeekday(year: number, month: number, weekday: number, nth: number): number {
  if (nth > 0) {
    const first = Date.UTC(year, month - 1, 1);
    return first + (((weekday - mondayIndex(first)) % 7 + 7) % 7 + 7 * (nth - 1)) * DAY_MS;
  }
  const last = Date.UTC(year, month, 1) - DAY_MS;
  return last - (((mondayIndex(last) - weekday) % 7 + 7) % 7) * DAY_MS;
}

function utcOffsetHours(nowMs: number, venue: OptionVenue): number {
  const year = new Date(nowMs).getUTCFullYear();
  if (venue === "US") {  // second Sunday of March 02:00 EST (07:00 UTC) .. first Sunday of November 02:00 EDT (06:00 UTC)
    const start = nthWeekday(year, 3, 6, 2) + 7 * 3_600_000;
    const end = nthWeekday(year, 11, 6, 1) + 6 * 3_600_000;
    return nowMs >= start && nowMs < end ? -4 : -5;
  }
  if (venue === "STOCKHOLM") {  // last Sunday of March 01:00 UTC .. last Sunday of October 01:00 UTC
    const start = nthWeekday(year, 3, 6, -1) + 3_600_000;
    const end = nthWeekday(year, 10, 6, -1) + 3_600_000;
    return nowMs >= start && nowMs < end ? 2 : 1;
  }
  return 8;
}

/** Exchange-local calendar date (YYYY-MM-DD) and minutes after midnight of an instant. */
export function exchangeLocal(nowMs: number, venue: OptionVenue): { date: string; minutes: number } {
  const local = new Date(nowMs + utcOffsetHours(nowMs, venue) * 3_600_000);
  return { date: local.toISOString().slice(0, 10), minutes: local.getUTCHours() * 60 + local.getUTCMinutes() };
}

export const exchangeDate = (nowMs: number, venue: OptionVenue): string => exchangeLocal(nowMs, venue).date;

/** True while an option expiring today (exchange local) is still tradable: before the regular-session close. */
export function expiryDayOpen(nowMs: number, venue: OptionVenue): boolean {
  return exchangeLocal(nowMs, venue).minutes < EXPIRY_DAY_CLOSE_LOCAL_MINUTES[venue];
}

/** Sunday of the Monday-Sunday calendar week containing the date (ms in, ms out). */
export const weekEndMs = (ms: number): number => ms + (6 - mondayIndex(ms)) * DAY_MS;
/** Last date a weekly can have: the Sunday of the next calendar week. */
export const weeklyWindowEndMs = (asOfMs: number): number => weekEndMs(asOfMs) + 7 * DAY_MS;

/** CURRENT or NEXT when the expiry lies in [asOf, next Sunday], else null (outside the weekly rule). Dates are YYYY-MM-DD. */
export function weeklyWeekFor(expiry: string, asOf: string): WeeklyWeek | null {
  const e = dayMs(expiry), a = dayMs(asOf);
  if (e === null || a === null || e < a || e > weeklyWindowEndMs(a)) return null;
  return e <= weekEndMs(a) ? "CURRENT" : "NEXT";
}

/** The weekly rule on listed expiry dates: earliest in [asOf, Sunday of this week]; else earliest in the next calendar week;
 * else null. The expiry day (asOf itself) counts only while expiryDayOpenNow. */
export function selectWeeklyExpiry(expiries: readonly string[], asOf: string, expiryDayOpenNow = true): { expiry: string; week: WeeklyWeek } | null {
  const a = dayMs(asOf);
  if (a === null) return null;
  const currentEnd = weekEndMs(a);
  const listed = [...new Set(expiries.filter(day => dayMs(day) !== null))].sort();
  for (const day of listed) {
    const e = dayMs(day)!;
    if (e < a || (e === a && !expiryDayOpenNow)) continue;
    if (e <= currentEnd) return { expiry: day, week: "CURRENT" };
  }
  for (const day of listed) {
    const e = dayMs(day)!;
    if (e > currentEnd && e <= currentEnd + 7 * DAY_MS) return { expiry: day, week: "NEXT" };
  }
  return null;
}

/** The middle-tier row among usable candidates (strike and optional delta): strictly between the balanced and the high strike;
 * delta nearest MIDDLE_DELTA when every candidate has one, else strike nearest MIDDLE_MONEYNESS; ties go to the higher strike. */
export function pickMiddle<T extends { strike: number; delta?: number | null }>(candidates: readonly T[], highStrike: number, balancedStrike: number, spot: number): T | null {
  const between = candidates.filter(row => balancedStrike < row.strike && row.strike < highStrike);
  if (between.length === 0) return null;
  const everyDelta = between.every(row => row.delta !== null && row.delta !== undefined);
  const score = (row: T) => everyDelta ? Math.abs((row.delta as number) - MIDDLE_DELTA) : Math.abs(row.strike / spot - MIDDLE_MONEYNESS);
  return between.reduce((best, row) => {
    const [a, b] = [score(row), score(best)];
    return a < b || (a === b && row.strike > best.strike) ? row : best;
  });
}

/** Round half up to the price tick (default 0.01), with two decimals. */
export function roundTick(value: number, tick = 0.01): number {
  return Number((Math.floor(value / tick + 0.5 + 1e-9) * tick).toFixed(2));
}

/** Middle of a two-price limit range: (low + high) / 2 on the tick, clamped into [low, high] (low <= middle <= high). */
export function limitMiddle(low: number, high: number, tick = 0.01): number {
  const lower = Math.min(low, high), upper = Math.max(low, high);
  return Math.min(Math.max(roundTick((lower + upper) / 2, tick), lower), upper);
}
