import type { V213Top20ReportRecord } from "./top20-report";

export interface TwoYearReturnEvidence {
  ticker: string;
  window: "two_year";
  actual_start: string;
  actual_end: string;
  start_adjusted_close: number;
  end_adjusted_close: number;
  elapsed_days: number;
  total_return_pct: number;
  market_source: "yfinance";
  basis: "adjusted_close";
  dividend_split_semantics: "auto_adjusted";
  currency?: string;
}

export interface ReturnEvidenceValidationResult {
  valid: boolean;
  candidateTotalReturnPct: number | null;
  totalReturnPct: number | null;
  display: string;
  admitted: false;
  rejectionReason?: string;
}

const REQUIRED_EVIDENCE_KEYS = new Set([
  "ticker",
  "window",
  "actual_start",
  "actual_end",
  "start_adjusted_close",
  "end_adjusted_close",
  "elapsed_days",
  "total_return_pct",
  "market_source",
  "basis",
  "dividend_split_semantics",
]);

const OPTIONAL_EVIDENCE_KEYS = new Set([
  "currency",
]);

function isLeapYear(year: number): boolean {
  return (year % 4 === 0 && year % 100 !== 0) || (year % 400 === 0);
}

function daysInMonth(year: number, month: number): number {
  const days = [31, isLeapYear(year) ? 29 : 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31];
  return days[month - 1] ?? 0;
}

/**
 * Strict calendar date validation for YYYY-MM-DD.
 * Rejects impossible dates like Feb 30, Apr 31, or Feb 29 on non-leap years.
 */
function parseStrictCalendarDate(dateStr: string): { year: number; month: number; day: number; utcMs: number } | null {
  if (typeof dateStr !== "string") return null;
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(dateStr);
  if (!match) return null;
  const year = Number(match[1]);
  const month = Number(match[2]);
  const day = Number(match[3]);
  if (year < 1900 || year > 2100) return null;
  if (month < 1 || month > 12) return null;
  const maxDay = daysInMonth(year, month);
  if (day < 1 || day > maxDay) return null;
  const utcMs = Date.UTC(year, month - 1, day);
  return { year, month, day, utcMs };
}

/**
 * Candidate pure math and schema validator for 2-year total return evidence.
 *
 * Checks endpoint arithmetic, strict calendar dates, elapsed day derivations,
 * 24-month calendar alignment, basis, dividend/split semantics, and clocks.
 *
 * NOTE: Candidate validation does NOT grant authoritative return admission.
 * Arithmetic and envelope matching can be synthesized; source authority,
 * provider identity/role binding, currency, original body digest, and
 * independent corroboration remain DEFERRED.
 */
export function validateTwoYearReturnCandidate(
  evidence: unknown,
  expectedTicker: string,
  retrievedAt?: string,
): ReturnEvidenceValidationResult {
  if (evidence === null || evidence === undefined) {
    return { valid: false, candidateTotalReturnPct: null, totalReturnPct: null, display: "UNAVAILABLE", admitted: false, rejectionReason: "EVIDENCE_MISSING" };
  }
  if (typeof evidence !== "object" || Array.isArray(evidence)) {
    return { valid: false, candidateTotalReturnPct: null, totalReturnPct: null, display: "UNAVAILABLE", admitted: false, rejectionReason: "EVIDENCE_NOT_OBJECT" };
  }

  const record = evidence as Record<string, unknown>;
  const keys = Object.keys(record);
  for (const k of keys) {
    if (!REQUIRED_EVIDENCE_KEYS.has(k) && !OPTIONAL_EVIDENCE_KEYS.has(k)) {
      return { valid: false, candidateTotalReturnPct: null, totalReturnPct: null, display: "UNAVAILABLE", admitted: false, rejectionReason: "EXTRA_OR_TAMPERED_KEY" };
    }
  }
  for (const req of REQUIRED_EVIDENCE_KEYS) {
    if (!(req in record)) {
      return { valid: false, candidateTotalReturnPct: null, totalReturnPct: null, display: "UNAVAILABLE", admitted: false, rejectionReason: "MISSING_REQUIRED_KEY" };
    }
  }

  if (typeof record.ticker !== "string" || record.ticker.toUpperCase() !== expectedTicker.toUpperCase()) {
    return { valid: false, candidateTotalReturnPct: null, totalReturnPct: null, display: "UNAVAILABLE", admitted: false, rejectionReason: "TICKER_MISMATCH" };
  }

  if (record.window !== "two_year") {
    return { valid: false, candidateTotalReturnPct: null, totalReturnPct: null, display: "UNAVAILABLE", admitted: false, rejectionReason: "WINDOW_NOT_TWO_YEAR" };
  }

  if (record.market_source !== "yfinance") {
    return { valid: false, candidateTotalReturnPct: null, totalReturnPct: null, display: "UNAVAILABLE", admitted: false, rejectionReason: "UNVERIFIED_SOURCE" };
  }

  if (record.basis !== "adjusted_close") {
    return { valid: false, candidateTotalReturnPct: null, totalReturnPct: null, display: "UNAVAILABLE", admitted: false, rejectionReason: "BASIS_NOT_ADJUSTED_CLOSE" };
  }

  if (record.dividend_split_semantics !== "auto_adjusted") {
    return { valid: false, candidateTotalReturnPct: null, totalReturnPct: null, display: "UNAVAILABLE", admitted: false, rejectionReason: "SEMANTICS_NOT_AUTO_ADJUSTED" };
  }

  if (record.currency !== undefined && record.currency !== "USD") {
    return { valid: false, candidateTotalReturnPct: null, totalReturnPct: null, display: "UNAVAILABLE", admitted: false, rejectionReason: "CURRENCY_MISMATCH" };
  }

  // Strict calendar date validation (rejects Feb 30, Apr 31, etc.)
  const startParsed = parseStrictCalendarDate(String(record.actual_start));
  const endParsed = parseStrictCalendarDate(String(record.actual_end));
  if (!startParsed || !endParsed) {
    return { valid: false, candidateTotalReturnPct: null, totalReturnPct: null, display: "UNAVAILABLE", admitted: false, rejectionReason: "INVALID_CALENDAR_DATE" };
  }

  if (startParsed.utcMs >= endParsed.utcMs) {
    return { valid: false, candidateTotalReturnPct: null, totalReturnPct: null, display: "UNAVAILABLE", admitted: false, rejectionReason: "INVALID_DATE_RANGE" };
  }

  // Exact calendar elapsed days derivation and check
  const derivedElapsedDays = Math.round((endParsed.utcMs - startParsed.utcMs) / 86400000);
  if (typeof record.elapsed_days !== "number" || !Number.isInteger(record.elapsed_days)) {
    return { valid: false, candidateTotalReturnPct: null, totalReturnPct: null, display: "UNAVAILABLE", admitted: false, rejectionReason: "INVALID_ELAPSED_DAYS" };
  }
  if (record.elapsed_days !== derivedElapsedDays) {
    return { valid: false, candidateTotalReturnPct: null, totalReturnPct: null, display: "UNAVAILABLE", admitted: false, rejectionReason: "ELAPSED_DAYS_MISMATCH" };
  }

  // Two-calendar-year target check: 24 calendar months before actual_end
  const targetYear = endParsed.year - 2;
  const targetMonth = endParsed.month;
  const targetMaxDay = daysInMonth(targetYear, targetMonth);
  const targetDay = Math.min(endParsed.day, targetMaxDay);
  const targetUtcMs = Date.UTC(targetYear, targetMonth - 1, targetDay);

  // Observation alignment: start observation must be within approved calendar tolerance (0 to 7 days before target)
  const alignmentGap = Math.round((targetUtcMs - startParsed.utcMs) / 86400000);
  if (alignmentGap < 0 || alignmentGap > 7) {
    return { valid: false, candidateTotalReturnPct: null, totalReturnPct: null, display: "UNAVAILABLE", admitted: false, rejectionReason: "START_OBSERVATION_GAP" };
  }

  if (derivedElapsedDays < 720 || derivedElapsedDays > 740) {
    return { valid: false, candidateTotalReturnPct: null, totalReturnPct: null, display: "UNAVAILABLE", admitted: false, rejectionReason: "ELAPSED_DAYS_OUT_OF_BOUNDS" };
  }

  // Clocks and Freshness validation
  if (retrievedAt !== undefined) {
    if (typeof retrievedAt !== "string" || !/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,3})?Z$/.test(retrievedAt)) {
      return { valid: false, candidateTotalReturnPct: null, totalReturnPct: null, display: "UNAVAILABLE", admitted: false, rejectionReason: "INVALID_RETRIEVED_AT" };
    }
    const retrievedMs = Date.parse(retrievedAt);
    if (!Number.isFinite(retrievedMs)) {
      return { valid: false, candidateTotalReturnPct: null, totalReturnPct: null, display: "UNAVAILABLE", admitted: false, rejectionReason: "INVALID_RETRIEVED_AT" };
    }
    const retDate = new Date(retrievedMs);
    const retUtcMs = Date.UTC(retDate.getUTCFullYear(), retDate.getUTCMonth(), retDate.getUTCDate());

    // End date cannot be after retrieval date (future end)
    if (endParsed.utcMs > retUtcMs) {
      return { valid: false, candidateTotalReturnPct: null, totalReturnPct: null, display: "UNAVAILABLE", admitted: false, rejectionReason: "FUTURE_END_DATE" };
    }

    // Stale end date check: market observation max age is 7 days under freshness policy
    const marketAgeDays = Math.round((retUtcMs - endParsed.utcMs) / 86400000);
    if (marketAgeDays > 7) {
      return { valid: false, candidateTotalReturnPct: null, totalReturnPct: null, display: "UNAVAILABLE", admitted: false, rejectionReason: "STALE_END_DATE" };
    }
  } else {
    // Current evaluation clock
    const nowDate = new Date();
    const nowUtcMs = Date.UTC(nowDate.getUTCFullYear(), nowDate.getUTCMonth(), nowDate.getUTCDate());
    if (endParsed.utcMs > nowUtcMs) {
      return { valid: false, candidateTotalReturnPct: null, totalReturnPct: null, display: "UNAVAILABLE", admitted: false, rejectionReason: "FUTURE_END_DATE" };
    }
  }

  // Price validation
  const startPrice = record.start_adjusted_close;
  const endPrice = record.end_adjusted_close;
  if (typeof startPrice === "boolean" || typeof endPrice === "boolean") {
    return { valid: false, candidateTotalReturnPct: null, totalReturnPct: null, display: "UNAVAILABLE", admitted: false, rejectionReason: "BOOLEAN_PRICES" };
  }
  if (typeof startPrice !== "number" || !Number.isFinite(startPrice) || startPrice <= 0 ||
      typeof endPrice !== "number" || !Number.isFinite(endPrice) || endPrice <= 0) {
    return { valid: false, candidateTotalReturnPct: null, totalReturnPct: null, display: "UNAVAILABLE", admitted: false, rejectionReason: "INVALID_PRICES" };
  }

  // Total return pct validation
  const totalPct = record.total_return_pct;
  if (typeof totalPct === "boolean" || typeof totalPct !== "number" || !Number.isFinite(totalPct) || totalPct < -100) {
    return { valid: false, candidateTotalReturnPct: null, totalReturnPct: null, display: "UNAVAILABLE", admitted: false, rejectionReason: "INVALID_TOTAL_RETURN_PCT" };
  }

  // Endpoint calculation validation: ((end / start) - 1) * 100
  const expectedReturn = ((endPrice / startPrice) - 1) * 100;
  if (Math.abs(expectedReturn - totalPct) > 0.05) {
    return { valid: false, candidateTotalReturnPct: null, totalReturnPct: null, display: "UNAVAILABLE", admitted: false, rejectionReason: "CALCULATION_MISMATCH" };
  }

  const display = `${totalPct >= 0 ? "+" : ""}${totalPct.toFixed(1)}%`;
  return {
    valid: true,
    candidateTotalReturnPct: totalPct,
    totalReturnPct: totalPct,
    display,
    admitted: false,
  };
}

/**
 * Validates canonical 2-year total return evidence candidate.
 * Preserved for backwards compatibility with existing candidate test suites.
 */
export function validateTwoYearReturnEvidence(
  evidence: unknown,
  expectedTicker: string,
  retrievedAt?: string,
): ReturnEvidenceValidationResult {
  return validateTwoYearReturnCandidate(evidence, expectedTicker, retrievedAt);
}

/**
 * Candidate display helper for isolated synthetic math tests.
 */
export function getTwoYearTotalReturnCandidateDisplay(record: Pick<V213Top20ReportRecord, "ticker" | "retrieved_at"> & {
  two_year_total_return_pct?: number | null;
  two_year_return_evidence?: TwoYearReturnEvidence | null;
}): string {
  if (!record.two_year_return_evidence) {
    return "UNAVAILABLE";
  }
  const result = validateTwoYearReturnCandidate(record.two_year_return_evidence, record.ticker, record.retrieved_at);
  return result.display;
}

/**
 * Derives the formatted 2Y total return string for actual card and deep analysis presentation.
 *
 * In all actual LINE card/deep callers, numeric 2Y total return is WITHHELD and displayed as
 * UNAVAILABLE. Authoritative return admission requires coordinated source authority, currency,
 * original source body digest, and role-binding receipts which are deferred.
 */
export function getTwoYearTotalReturnDisplay(_record?: Pick<V213Top20ReportRecord, "ticker" | "retrieved_at"> & {
  two_year_total_return_pct?: number | null;
  two_year_return_evidence?: TwoYearReturnEvidence | null;
}): string {
  return "UNAVAILABLE";
}
