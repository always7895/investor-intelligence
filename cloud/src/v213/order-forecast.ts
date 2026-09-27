/** The Top20 card's 6-month and 1-year ORDER figures and the price change if those orders are realized (operator
 * 2026-09-27; Astra contract "order horizons and order-linked price scenarios"). The sealer computes them with
 * scripts/order_forecast.py; this module re-validates every sealed record against the same rules (issuer, scope, currency,
 * evidence, windows, the cumulative schedule, and every derived value recomputed from its sealed inputs) and renders them.
 * A record that fails is shown as unavailable, never replaced by another figure; no analyst estimate enters either tile. */

export type ForecastReason = "NOT_DISCLOSED_HORIZON" | "PERIOD_MISMATCH" | "INPUTS_MISSING" | "INVALID" | "STALE" | "NO_GROWTH"
  | "GROWTH_OUT_OF_RANGE" | "NOT_DISCLOSED" | "NO_ORDERS" | "EXPIRED" | "SCHEDULE_CONTRADICTION" | "NO_GROWTH_LINEAGE" | "INVALID_SHARE" | "LEGACY"
  | "NO_REALIZATION_SCHEDULE" | "CONFLICTING_DISCLOSURES" | "EVIDENCE_LIMIT" | "UNQUANTIFIED_STOCK" | "UNRESOLVED_REVISION";
export interface ForecastScenario { status: "AVAILABLE" | "INSUFFICIENT_COVERAGE" | "NO_BASIS"; coverage?: number; change?: number;
  reason?: "NO_ORDER_BASIS" | "SCOPE_PARTIAL" | "NO_MATCHING_REVENUE" }
export interface ForecastHorizon {
  status: "AVAILABLE" | "UNAVAILABLE"; reason?: ForecastReason; basis?: "RECOGNITION" | "STOCK_EXTRAPOLATION";
  /** v2: where a recognition figure comes from (the periodic filing or a reviewed later claim) and its claims. */
  source?: "PERIODIC" | "REGISTRY"; stock_claim_id?: string; schedule_claim_id?: string;
  amount?: number; currency?: string; scope?: "COMPANY" | "SEGMENT"; scope_label?: string | null;
  start?: string; end?: string; as_of?: string; source_url?: string;
  rpo?: number; share_pct?: number; quarter_revenue?: number; quarter_end?: string; quarter_start?: string | null;
  quarter_basis?: "FRAME" | "DERIVED_Q4"; quarter_derivation?: QuarterDerivation;
  form?: string; filed?: string; accession?: string; passage?: string; report_period?: string;
  stock?: number; yoy?: number; baseline?: number; kind?: string; lineage?: "SERIES" | "COMPANY_STATED";
  yoy_prior_amount?: number; yoy_prior_as_of?: string; yoy_evidence?: string;
  scenario: ForecastScenario;
}
export interface QuarterDerivation { annual: number; annual_start: string; annual_accession: string; nine_months: number;
  nine_months_end: string; nine_months_accession: string }
export interface ForecastReference { kind: "RECOGNITION_24M" | "ANNUAL_NEW_ORDERS_GUIDANCE"; amount: number; currency: string | null;
  start?: string; end?: string; share_pct?: number; rpo?: number; as_of?: string; accession?: string; filed?: string; year?: number;
  source_url: string | null }
/** The validated forecast of either version, normalized for rendering: m6 / m12 are realization (recognition) horizons
 * only; an order-book extrapolation is a separate model sensitivity that never carries a price. */
export interface OrderForecast {
  version: 1 | 2; m6: ForecastHorizon; m12: ForecastHorizon; sensitivity: Sensitivity | null; references: ForecastReference[];
  supplements: ClaimView[]; superseded: SupersededView[]; registry24: RegistryReference[]; registry: string | null; cutoff: string | null;
  claims: ClaimView[]; currentStock: string | null; schedule: string | null;
}
const normalized = (version: 1 | 2, m6: ForecastHorizon, m12: ForecastHorizon): OrderForecast =>
  ({ version, m6, m12, sensitivity: null, references: [], supplements: [], superseded: [], registry24: [], registry: null, cutoff: null,
    claims: [], currentStock: null, schedule: null });
/** v1 records priced an order-book extrapolation; it is shown as a sensitivity now, and its horizons have no schedule. */
function fromV1(m6: ForecastHorizon, m12: ForecastHorizon, references: ForecastReference[]): OrderForecast {
  const stock = (h: ForecastHorizon) => h.status === "AVAILABLE" && h.basis === "STOCK_EXTRAPOLATION";
  if (!stock(m6) && !stock(m12)) return { ...normalized(1, m6, m12), references };
  const strip = (h: ForecastHorizon): ForecastHorizon => stock(h) ? { ...h, scenario: { status: "NO_BASIS", reason: "NO_ORDER_BASIS" } } : h;
  return { ...normalized(1, unavailable("NO_REALIZATION_SCHEDULE"), unavailable("NO_REALIZATION_SCHEDULE")),
    sensitivity: { m6: strip(m6), m12: strip(m12) }, references };
}

const MONTHS = { m6: 6, m12: 12 } as const;
const MAX_AGE_DAYS = 200;
const CURRENCIES = new Set(["USD", "KRW", "TWD", "SEK", "JPY", "EUR", "GBP", "HKD", "CNY"]);
const REASONS = new Set<string>(["NOT_DISCLOSED_HORIZON", "PERIOD_MISMATCH", "INPUTS_MISSING", "INVALID", "STALE", "NO_GROWTH",
  "GROWTH_OUT_OF_RANGE", "NOT_DISCLOSED", "NO_ORDERS", "EXPIRED", "SCHEDULE_CONTRADICTION", "NO_GROWTH_LINEAGE", "INVALID_SHARE"]);
const ACCESSION = /^[0-9]{10}-[0-9]{2}-[0-9]{6}$/;
/** The authority as written (scripts/order_forecast.py AUTHORITY): an ASCII DNS name ending in an alphabetic top-level
 * domain and an optional 1-5 digit port; the shared table is tests/fixtures/v213-order-forecast-urls.json. */
const AUTHORITY = /^([A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?)*\.[A-Za-z]{2,63})(?::([0-9]{1,5}))?$/;
const DAY_MS = 86_400_000;

const finite = (value: unknown): value is number => typeof value === "number" && Number.isFinite(value);
/** Relative closeness of two finite numbers (a non-finite operand never matches). */
const close = (a: unknown, b: unknown) => finite(a) && finite(b) && Math.abs(a - b) <= 1e-6 * Math.max(1, Math.abs(a), Math.abs(b));
function isoDay(value: unknown): value is string {
  if (typeof value !== "string" || !/^[0-9]{4}-[0-9]{2}-[0-9]{2}$/.test(value)) return false;
  const time = Date.parse(`${value}T00:00:00Z`);
  return Number.isFinite(time) && new Date(time).toISOString().slice(0, 10) === value;
}
const dayMs = (value: string) => Date.parse(`${value}T00:00:00Z`);
const days = (from: string, to: string) => Math.round((dayMs(to) - dayMs(from)) / DAY_MS);
/** A real https URL whose authority, as written, is a DNS name with an optional valid port (checked before URL parsing,
 * which would rewrite a backslash, a bare number or a Unicode host). */
function https(value: unknown): value is string {
  if (typeof value !== "string" || value.length > 400 || !/^[\x21-\x7e]+$/.test(value) || value.includes("\\")
    || value.slice(0, 8).toLowerCase() !== "https://") return false;
  const written = AUTHORITY.exec(value.slice(8).split(/[/?#]/)[0]!);
  if (!written || (written[2] !== undefined && !(Number(written[2]) > 0 && Number(written[2]) < 65536))) return false;
  try {
    const url = new URL(value);
    return url.protocol === "https:" && url.hostname === written[1]!.toLowerCase() && !url.username && !url.password;
  } catch {
    return false;
  }
}
const optText = (value: unknown, max: number): value is string | null | undefined =>
  value === undefined || value === null || (typeof value === "string" && value.length <= max);

/** The same day `months` calendar months later, clamped to the month's last day (scripts/order_forecast.py add_months). */
export function addMonths(day: string, months: number): string {
  const [year, month, date] = day.split("-").map(Number) as [number, number, number];
  const index = month - 1 + months;
  const y = year + Math.floor(index / 12);
  const m = ((index % 12) + 12) % 12;
  const last = new Date(Date.UTC(y, m + 1, 0)).getUTCDate();
  return new Date(Date.UTC(y, m, Math.min(date, last))).toISOString().slice(0, 10);
}

const unavailable = (reason: ForecastReason): ForecastHorizon => ({ status: "UNAVAILABLE", reason, scenario: { status: "NO_BASIS", reason: "NO_ORDER_BASIS" } });

/** The filing evidence every recognition record and its 24-month reference must carry (scripts/order_forecast.py). */
function validFiling(raw: any, reportDay: string): boolean {
  return raw.explicit === true && https(raw.source_url) && typeof raw.accession === "string" && ACCESSION.test(raw.accession)
    && typeof raw.passage === "string" && raw.passage.trim().length > 0 && raw.passage.length <= 300 && (raw.form === "10-Q" || raw.form === "10-K")
    && isoDay(raw.filed) && isoDay(raw.as_of) && days(raw.as_of, raw.filed) >= 0 && days(raw.filed, reportDay) >= 0
    && isoDay(raw.report_period) && Math.abs(days(raw.report_period, raw.as_of)) <= 45;
}

/** A fiscal fourth quarter = full year - nine months of the same fiscal year (scripts/order_forecast.py _derivation). */
function validDerivation(raw: any, revenue: number, quarterStart: string, quarterEnd: string): QuarterDerivation | null {
  if (!raw || typeof raw !== "object" || !finite(raw.annual) || !finite(raw.nine_months) || raw.annual <= 0 || raw.nine_months <= 0
    || !isoDay(raw.annual_start) || !isoDay(raw.nine_months_end) || typeof raw.annual_accession !== "string" || !ACCESSION.test(raw.annual_accession)
    || typeof raw.nine_months_accession !== "string" || !ACCESSION.test(raw.nine_months_accession)
    || days(raw.annual_start, quarterEnd) < 350 || days(raw.annual_start, quarterEnd) > 380
    || days(raw.annual_start, raw.nine_months_end) < 260 || days(raw.annual_start, raw.nine_months_end) > 285
    || quarterStart !== addMonthsDays(raw.nine_months_end, 1) || !close(raw.annual - raw.nine_months, revenue)) return null;
  return { annual: raw.annual, annual_start: raw.annual_start, annual_accession: raw.annual_accession, nine_months: raw.nine_months,
    nine_months_end: raw.nine_months_end, nine_months_accession: raw.nine_months_accession };
}
const addMonthsDays = (day: string, add: number) => new Date(dayMs(day) + add * DAY_MS).toISOString().slice(0, 10);

function validRecognition(raw: any, months: number, reportDay: string): ForecastHorizon {
  const level = finite(raw.quarter_revenue) && raw.quarter_revenue > 0 ? raw.quarter_revenue * months / 3 : NaN;
  const amount = finite(raw.rpo) && finite(raw.share_pct) ? raw.rpo * raw.share_pct / 100 : NaN;
  if (raw.scope !== "COMPANY" || raw.currency !== "USD" || !(raw.rpo > 0) || !(raw.share_pct > 0) || raw.share_pct > 100
    || !finite(level) || !finite(amount) || amount <= 0 || !close(raw.amount, amount) || raw.start !== raw.as_of || raw.end !== addMonths(raw.as_of, months)
    || !validFiling(raw, reportDay) || !isoDay(raw.quarter_end) || Math.abs(days(raw.quarter_end, raw.as_of)) > 45
    || !isoDay(raw.quarter_start) || days(raw.quarter_start, raw.quarter_end) < 60 || days(raw.quarter_start, raw.quarter_end) > 100) return unavailable("INVALID");
  let derivation: QuarterDerivation | null = null;
  if (raw.quarter_basis === "DERIVED_Q4") {
    derivation = validDerivation(raw.quarter_derivation, raw.quarter_revenue, raw.quarter_start, raw.quarter_end);
    if (!derivation) return unavailable("INVALID");
  } else if (raw.quarter_basis !== "FRAME" || raw.quarter_derivation !== undefined) return unavailable("INVALID");
  const coverage = amount / level;
  const scenario = raw.scenario;
  const ok = finite(coverage) && close(scenario?.coverage, coverage) && (coverage >= 1
    ? scenario.status === "AVAILABLE" && close(scenario.change, coverage - 1)
    : scenario.status === "INSUFFICIENT_COVERAGE" && scenario.change === undefined);
  if (!ok) return unavailable("INVALID");
  return { status: "AVAILABLE", basis: "RECOGNITION", amount, currency: "USD", scope: "COMPANY", start: raw.start, end: raw.end,
    as_of: raw.as_of, source_url: raw.source_url, rpo: raw.rpo, share_pct: raw.share_pct, quarter_revenue: raw.quarter_revenue,
    quarter_end: raw.quarter_end, quarter_start: raw.quarter_start, quarter_basis: raw.quarter_basis, ...(derivation ? { quarter_derivation: derivation } : {}),
    form: raw.form, filed: raw.filed, accession: raw.accession, passage: raw.passage, report_period: raw.report_period,
    scenario: coverage >= 1 ? { status: "AVAILABLE", coverage, change: coverage - 1 } : { status: "INSUFFICIENT_COVERAGE", coverage } };
}

function validStock(raw: any, months: number, reportDay: string): ForecastHorizon {
  if (!(raw.stock > 0) || !finite(raw.yoy) || raw.yoy <= -1 || raw.yoy > 1 || raw.start !== reportDay || raw.end !== addMonths(reportDay, months)
    || (raw.kind !== "RPO" && raw.kind !== "BACKLOG") || (raw.scope !== "COMPANY" && raw.scope !== "SEGMENT") || !optText(raw.scope_label, 40)) return unavailable("INVALID");
  const lineageOk = raw.lineage === "SERIES"
    ? raw.yoy_prior_amount > 0 && isoDay(raw.yoy_prior_as_of) && days(raw.yoy_prior_as_of, raw.as_of) >= 320
      && days(raw.yoy_prior_as_of, raw.as_of) <= 410 && close(raw.stock / raw.yoy_prior_amount - 1, raw.yoy)
    : raw.lineage === "COMPANY_STATED" && typeof raw.yoy_evidence === "string" && raw.yoy_evidence.trim().length > 0 && raw.yoy_evidence.length <= 300;
  if (!lineageOk) return unavailable("INVALID");
  const level = (day: string) => raw.stock * Math.pow(1 + raw.yoy, days(raw.as_of, day) / 365);
  const baseline = level(reportDay);
  const amount = level(raw.end);
  if (!finite(baseline) || !finite(amount) || baseline <= 0 || amount <= 0 || !close(raw.baseline, baseline) || !close(raw.amount, amount)) return unavailable("INVALID");
  const scenario = raw.scenario;
  const change = amount / baseline - 1;
  const scenarioOk = raw.scope === "COMPANY" ? scenario?.status === "AVAILABLE" && close(scenario.change, change)
    : scenario?.status === "NO_BASIS" && scenario.reason === "SCOPE_PARTIAL";
  if (!scenarioOk || !finite(change)) return unavailable("INVALID");
  return { status: "AVAILABLE", basis: "STOCK_EXTRAPOLATION", amount, currency: raw.currency, scope: raw.scope, scope_label: raw.scope_label ?? null,
    start: raw.start, end: raw.end, as_of: raw.as_of, source_url: raw.source_url, stock: raw.stock, yoy: raw.yoy, baseline, kind: raw.kind,
    lineage: raw.lineage, ...(raw.lineage === "SERIES" ? { yoy_prior_amount: raw.yoy_prior_amount, yoy_prior_as_of: raw.yoy_prior_as_of }
      : { yoy_evidence: raw.yoy_evidence }),
    scenario: raw.scope === "COMPANY" ? { status: "AVAILABLE", change } : { status: "NO_BASIS", reason: "SCOPE_PARTIAL" } };
}

function validHorizon(raw: any, months: number, reportDay: string): ForecastHorizon {
  if (!raw || typeof raw !== "object") return unavailable("INVALID");
  if (raw.status === "UNAVAILABLE") {
    return REASONS.has(raw.reason) && raw.scenario?.status === "NO_BASIS" ? unavailable(raw.reason) : unavailable("INVALID");
  }
  if (raw.status !== "AVAILABLE" || !finite(raw.amount) || !https(raw.source_url) || !isoDay(raw.as_of) || !isoDay(raw.start)
    || !isoDay(raw.end) || typeof raw.currency !== "string" || !CURRENCIES.has(raw.currency) || !raw.scenario || typeof raw.scenario !== "object") return unavailable("INVALID");
  const age = days(raw.as_of, reportDay);
  if (age < 0 || age > MAX_AGE_DAYS) return unavailable(age > MAX_AGE_DAYS ? "STALE" : "INVALID");
  if (days(reportDay, raw.end) <= 0) return unavailable("EXPIRED");  // a window that has ended is not a future estimate
  if (raw.basis === "RECOGNITION") return validRecognition(raw, months, reportDay);
  if (raw.basis === "STOCK_EXTRAPOLATION") return validStock(raw, months, reportDay);
  return unavailable("INVALID");
}

function validReference(raw: any, reportDay: string): ForecastReference | null {
  if (!raw || typeof raw !== "object" || !finite(raw.amount) || raw.amount <= 0) return null;
  if (raw.kind === "RECOGNITION_24M") {
    const amount = finite(raw.rpo) && finite(raw.share_pct) ? raw.rpo * raw.share_pct / 100 : NaN;
    const age = isoDay(raw.as_of) ? days(raw.as_of, reportDay) : NaN;
    if (!(raw.rpo > 0) || !(raw.share_pct > 0) || raw.share_pct > 100 || !finite(amount) || !close(raw.amount, amount) || raw.currency !== "USD"
      || !validFiling(raw, reportDay) || raw.start !== raw.as_of || raw.end !== addMonths(raw.as_of, 24) || !(age >= 0 && age <= MAX_AGE_DAYS)
      || days(reportDay, raw.end) <= 0) return null;
    return { kind: raw.kind, amount, currency: "USD", start: raw.start, end: raw.end, share_pct: raw.share_pct, rpo: raw.rpo, as_of: raw.as_of,
      accession: raw.accession, filed: raw.filed, source_url: raw.source_url };
  }
  if (raw.kind === "ANNUAL_NEW_ORDERS_GUIDANCE" && Number.isInteger(raw.year) && typeof raw.currency === "string" && CURRENCIES.has(raw.currency)
    && (raw.source_url === null || https(raw.source_url))) {
    return { kind: raw.kind, amount: raw.amount, currency: raw.currency, year: raw.year, source_url: raw.source_url };
  }
  return null;
}

/** The forecast-level reason from its horizons (scripts/order_forecast.py top_reason). */
function topReason(m6: any, m12: any): string | null {
  if (m6?.status === "AVAILABLE" || m12?.status === "AVAILABLE") return null;
  const reasons = [m12?.reason, m6?.reason];
  const real = reasons.filter(reason => reason !== "NOT_DISCLOSED_HORIZON" && reason !== "EXPIRED");
  return (real.length ? real : reasons)[0] ?? null;
}

/** The validated forecast for `issuer`; an older sealed document without one reads as unavailable (never the old analyst
 * tiles), and a record for another issuer, with an inconsistent status or mixed evidence, as invalid. */
export function parseOrderForecast(raw: unknown, reportDay: string, issuer: string, generatedAt?: string): OrderForecast {
  const legacy = normalized(1, unavailable("LEGACY"), unavailable("LEGACY"));
  const invalid = normalized(1, unavailable("INVALID"), unavailable("INVALID"));
  if (!raw || typeof raw !== "object") return legacy;
  const value = raw as any;
  if (value.version === 2) return parseV2(value, reportDay, issuer, generatedAt);
  if (value.version !== 1 || value.issuer !== issuer || !value.m6 || !value.m12 || !Array.isArray(value.references)) return invalid;
  const sealedAvailable = value.m6.status === "AVAILABLE" || value.m12.status === "AVAILABLE";
  if (value.status !== (sealedAvailable ? "AVAILABLE" : "UNAVAILABLE") || value.reason !== topReason(value.m6, value.m12)
    || (value.reason !== null && !REASONS.has(value.reason))) return invalid;
  let m6 = validHorizon(value.m6, MONTHS.m6, reportDay);
  let m12 = validHorizon(value.m12, MONTHS.m12, reportDay);
  const references: ForecastReference[] = Array.isArray(value.references)
    ? value.references.slice(0, 4).map((r: unknown) => validReference(r, reportDay)).filter((r: ForecastReference | null): r is ForecastReference => r !== null) : [];
  // Both horizons come from one piece of evidence: the same basis, source and as-of date (and the same RPO or book).
  if (m6.status === "AVAILABLE" && m12.status === "AVAILABLE" && (m6.basis !== m12.basis || m6.source_url !== m12.source_url
    || m6.as_of !== m12.as_of || m6.currency !== m12.currency || m6.scope !== m12.scope
    || (m6.basis === "RECOGNITION" ? m6.rpo !== m12.rpo || m6.quarter_revenue !== m12.quarter_revenue || m6.share_pct! > m12.share_pct!
        || m6.accession !== m12.accession || m6.filed !== m12.filed || m6.form !== m12.form || m6.passage !== m12.passage
        || m6.report_period !== m12.report_period || m6.quarter_start !== m12.quarter_start || m6.quarter_end !== m12.quarter_end
        || m6.quarter_basis !== m12.quarter_basis || JSON.stringify(m6.quarter_derivation) !== JSON.stringify(m12.quarter_derivation)
      : m6.stock !== m12.stock || m6.yoy !== m12.yoy || m6.kind !== m12.kind || m6.lineage !== m12.lineage
        || m6.yoy_prior_amount !== m12.yoy_prior_amount || m6.yoy_prior_as_of !== m12.yoy_prior_as_of || m6.yoy_evidence !== m12.yoy_evidence
        || m6.scope_label !== m12.scope_label))) {
    m6 = unavailable("INVALID");
    m12 = unavailable("INVALID");
  }
  if (new Set(references.map(ref => ref.kind)).size !== references.length || references.length !== (Array.isArray(value.references) ? value.references.length : 0)) {
    return invalid;  // a malformed or duplicated reference invalidates the record
  }
  const m24 = references.find(ref => ref.kind === "RECOGNITION_24M");
  for (const h of [m6, m12]) {
    if (m24 && h.status === "AVAILABLE" && (h.basis !== "RECOGNITION" || m24.share_pct! < h.share_pct! || m24.source_url !== h.source_url
      || m24.accession !== h.accession || m24.rpo !== h.rpo || m24.as_of !== h.as_of || m24.filed !== h.filed)) {
      return invalid;  // a cumulative schedule never shrinks, and all of it comes from one filing
    }
  }
  return fromV1(m6, m12, references);
}

// ---------------------------------------------------------------- version 2 (Astra contract ORDERS-V2-01)
// Reviewed, dated issuer claims beside the periodic filing (scripts/order_claims.py; scripts/order_forecast.py build_v2 and
// decide). The Worker trusts no sealed conclusion: it validates every document and claim with the same rules, recomputes
// the selection at the exact sealed build instant, recomputes every figure from the sealed periodic input, order book and
// claims (decideV2 mirrors decide), and compares the whole record. Any disagreement makes the whole record unavailable
// (never a v1, consensus or target figure); what is shown is the recomputed value.

export interface ClaimView {
  id: string; metric: string; assertion_kind: string; currency: string; value: number | null; bounds: { lower?: number; upper?: number } | null;
  as_of: string; scope: string; scope_label: string | null; summary: string | null; passage: string; locator: string;
  published_date: string; checked_date: string; source_url: string; source_kind: string; revision: string;
  revision_reason: string | null; targets: string[]; period: string | null; excluded: string | null;
}
export interface SupersededView { as_of: string; rpo: number; share_pct: number; start: string; end: string; filed: string;
  form: string; accession: string; source_url: string; by_claim_id: string; filing: string }
export interface Sensitivity { m6: ForecastHorizon; m12: ForecastHorizon }
export interface RegistryReference { amount: number; start: string; end: string; rpo: number; share_pct: number; stock_claim_id: string }

const V2_REASONS = new Set<string>([...REASONS, "NO_REALIZATION_SCHEDULE", "CONFLICTING_DISCLOSURES", "EVIDENCE_LIMIT", "UNQUANTIFIED_STOCK",
  "UNRESOLVED_REVISION"]);
const SOURCE_KINDS = new Set(["SEC_PERIODIC", "SEC_8K_EXHIBIT", "ISSUER_EARNINGS_RELEASE", "ISSUER_PREPARED_REMARKS", "ISSUER_CONTRACT_ANNOUNCEMENT"]);
const SEC_FORMS: Record<string, string[]> = { SEC_PERIODIC: ["10-Q", "10-K", "20-F", "40-F"], SEC_8K_EXHIBIT: ["8-K", "6-K"] };
const SEC_PREFIX = "https://www.sec.gov/Archives/edgar/data/";
const METRICS = ["RPO_STOCK", "BACKLOG_STOCK", "SIGNED_CONTRACT_VALUE", "ORDER_INTAKE", "RECOGNITION_SCHEDULE", "ORDER_GUIDANCE"];
const STOCK_METRICS = ["RPO_STOCK", "BACKLOG_STOCK"];
const PERIOD_METRICS = ["ORDER_INTAKE", "ORDER_GUIDANCE"];
const NO_PERIOD_METRICS = ["RPO_STOCK", "BACKLOG_STOCK", "RECOGNITION_SCHEDULE"];
const PERIOD_KINDS = ["QUARTER", "HALF_YEAR", "YEAR", "MULTI_YEAR", "OTHER"];
const MULTIPLIERS = new Set([1, 1_000, 1_000_000, 1_000_000_000]);
const FILING_TARGET = "FILING:";
const FILING_BASIS = "ASC 606";
const MIN_YEAR = 1990;
const MAX_YEAR = 2100;
const PRESENTATION_BUDGET = 2400;
const SHOWN_PASSAGE = 160;
const OPTIONAL_CLAIM_FIELDS = ["null_reason", "bounds", "scope_label", "period_start", "period_end", "period_kind", "stock_claim_id", "shares", "summary"];
const MAX_ISSUER_CLAIMS = 8;
const MAX_ISSUER_DOCUMENTS = 4;
const MAX_VALUE = 1e16;
const ID_RE = /^[A-Za-z0-9][A-Za-z0-9._:-]{0,119}$/;
const SYMBOL_RE = /^[A-Z0-9][A-Z0-9.\-]{0,19}$/;
const HOST = "[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?(?:\\.[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)*\\.[a-z]{2,63}";
const PREFIX_RE = new RegExp(`^https://${HOST}/(?:[A-Za-z0-9._~-]+/)*$`);
const URL_RE = new RegExp(`^https://${HOST}/[\\x21-\\x7e]*$`);
const INSTANT_RE = /^([0-9]{4}-[0-9]{2}-[0-9]{2})T([0-9]{2}):([0-9]{2}):([0-9]{2})Z$/;
// scripts/order_claims.py FORBIDDEN_CHARS and SPACES: one text policy. With the u flag the surrogate range matches only an
// unpaired surrogate (a pair is one supplementary-plane character). Lengths count code points.
const FORBIDDEN_CHARS = /[\u0000-\u001f\u007f-\u009f\u180e\u200b-\u200f\u2028-\u202e\u2060-\u206f\ufeff\ud800-\udfff]/u;
const SPACES = /[ \u00a0\u1680\u2000-\u200a\u202f\u205f\u3000]/g;

class EvidenceError extends Error {}
const need = (ok: unknown, what: string): void => { if (!ok) throw new EvidenceError(what); };
const isObject = (value: unknown): value is Record<string, any> => !!value && typeof value === "object" && !Array.isArray(value);
const ident = (value: unknown): value is string => typeof value === "string" && ID_RE.test(value);
const cleanText = (value: unknown, max: number): value is string =>
  typeof value === "string" && !FORBIDDEN_CHARS.test(value) && value.replace(SPACES, "").length > 0 && [...value].length <= max;
/** scripts/order_claims.py number: finite, non-boolean, within +/-1e16. */
const num = (value: unknown): value is number => finite(value) && Math.abs(value) <= MAX_VALUE;
/** A calendar day within scripts/order_claims.py MIN_YEAR..MAX_YEAR. */
const claimDay = (value: unknown): value is string => isoDay(value) && Number(value.slice(0, 4)) >= MIN_YEAR && Number(value.slice(0, 4)) <= MAX_YEAR;
/** A strict UTC instant (no rollover such as T24:00:00Z), within the same years. */
function instantMs(value: unknown): number | null {
  const m = typeof value === "string" ? INSTANT_RE.exec(value) : null;
  if (!m || !claimDay(m[1]) || Number(m[2]) > 23 || Number(m[3]) > 59 || Number(m[4]) > 59) return null;
  return Date.parse(value as string);
}
/** scripts/order_claims.py url_ok: under a reviewed prefix, with no path that a URL consumer would normalize elsewhere. */
function urlOk(value: unknown, prefixes: string[]): boolean {
  if (typeof value !== "string" || value.length > 400 || !URL_RE.test(value) || value.includes("#") || value.includes("\\")) return false;
  const rest = value.slice(8);
  const path = rest.includes("/") ? rest.slice(rest.indexOf("/") + 1).split("?")[0]! : "";
  if (path.split("/").some(segment => segment === "." || segment === "..") || `/${path}`.includes("//")
    || ["%2e", "%2f", "%5c"].some(code => value.toLowerCase().includes(code))) return false;
  return prefixes.some(prefix => value.startsWith(prefix));
}
const onlyKeys = (raw: Record<string, any>, required: string[], optional: string[]) =>
  required.every(key => key in raw) && Object.keys(raw).every(key => required.includes(key) || optional.includes(key));
/** When a document may count: its stated publication instant, else the end of its publication day (UTC). */
const eligibleAt = (doc: any): number => instantMs(doc.published_at) ?? dayMs(doc.published_date) + DAY_MS;
const valueOf = (claim: any): number | null => num(claim.amount) ? claim.amount * claim.unit_multiplier : null;
/** scripts/order_claims.py presentation_size: UTF-16 units the claims add to the detail (the shown part of the quote). */
export function presentationSize(documents: any[], claims: any[]): number {
  const urls = new Map(documents.map(d => [d.id, d.url as string]));
  const units = (s: unknown) => typeof s === "string" ? s.length : 0;
  return claims.reduce((total, c) => total + units(urls.get(c.document_id)) + units(c.locator)
    + units(typeof c.passage === "string" ? [...c.passage].slice(0, SHOWN_PASSAGE).join("") : "")
    + units(c.summary) + units(c.scope_label) + units(c.revision?.reason), 0);
}
const sortedJson = (value: unknown): string => JSON.stringify(value, (_key, v) =>
  isObject(v) ? Object.fromEntries(Object.entries(v).sort(([a], [b]) => (a < b ? -1 : a > b ? 1 : 0))) : v);
const observation = (claim: any) => sortedJson([valueOf(claim), claim.bounds ?? null, claim.shares ?? null]);
const seriesDims = (c: any) => JSON.stringify([c.symbol, c.metric, c.scope, c.scope_label ?? null, c.currency, c.unit_multiplier, c.basis]);

function checkDocument(doc: any, issuer: string, prefixes: string[]): void {
  need(isObject(doc) && onlyKeys(doc, ["id", "issuer", "publisher", "title", "source_kind", "url", "published_date", "retrieved_at",
    "sha256", "byte_size", "lineage_id"], ["published_at", "sec"]) && doc.published_at !== null && doc.sec !== null, "DOCUMENT_FIELDS");
  need(ident(doc.id) && doc.issuer === issuer && cleanText(doc.publisher, 160) && cleanText(doc.title, 160) && SOURCE_KINDS.has(doc.source_kind)
    && claimDay(doc.published_date) && ident(doc.lineage_id) && typeof doc.sha256 === "string" && /^[0-9a-f]{64}$/.test(doc.sha256)
    && Number.isInteger(doc.byte_size) && doc.byte_size > 0 && doc.byte_size <= 50_000_000, "DOCUMENT");
  const sec = doc.source_kind in SEC_FORMS;
  need(urlOk(doc.url, sec ? [SEC_PREFIX] : prefixes), "DOCUMENT_URL");
  need(!("published_at" in doc) || (instantMs(doc.published_at) !== null && doc.published_at.slice(0, 10) === doc.published_date), "PUBLISHED_AT");
  const retrieved = instantMs(doc.retrieved_at);
  need(retrieved !== null && retrieved >= dayMs(doc.published_date), "RETRIEVED");
  if (sec) {
    const exhibit = doc.source_kind === "SEC_8K_EXHIBIT";
    need(isObject(doc.sec) && onlyKeys(doc.sec, ["accession", "form", ...(exhibit ? ["exhibit"] : [])], [])
      && typeof doc.sec.accession === "string" && ACCESSION.test(doc.sec.accession) && SEC_FORMS[doc.source_kind]!.includes(doc.sec.form)
      && (!exhibit || cleanText(doc.sec.exhibit, 20)), "SEC");
  } else need(!("sec" in doc), "SEC_INVENTED");
}

function checkClaim(claim: any, docs: Map<string, any>, issuer: string): void {
  need(isObject(claim) && onlyKeys(claim, ["id", "symbol", "document_id", "locator", "passage", "metric", "assertion_kind", "currency",
    "unit_multiplier", "amount", "as_of", "scope", "series_id", "basis", "revision", "checked_at"], ["null_reason", "bounds", "scope_label",
    "period_start", "period_end", "period_kind", "stock_claim_id", "shares", "summary"])
    && OPTIONAL_CLAIM_FIELDS.every(key => !(key in claim) || claim[key] !== null), "CLAIM_FIELDS");
  const doc = typeof claim.document_id === "string" ? docs.get(claim.document_id) : undefined;
  need(ident(claim.id) && doc && claim.symbol === issuer && SYMBOL_RE.test(claim.symbol) && cleanText(claim.locator, 160)
    && cleanText(claim.passage, 1000) && (!("summary" in claim) || cleanText(claim.summary, 60)) && METRICS.includes(claim.metric)
    && (claim.assertion_kind === "DISCLOSED_FACT" || claim.assertion_kind === "COMPANY_GUIDANCE")
    && (claim.metric === "ORDER_GUIDANCE") === (claim.assertion_kind === "COMPANY_GUIDANCE") && ["COMPANY", "SEGMENT", "CONTRACT"].includes(claim.scope)
    && CURRENCIES.has(claim.currency) && typeof claim.unit_multiplier === "number" && MULTIPLIERS.has(claim.unit_multiplier)
    && claimDay(claim.as_of) && ident(claim.series_id) && cleanText(claim.basis, 160)
    && (claim.scope === "COMPANY" ? !("scope_label" in claim) : cleanText(claim.scope_label, 160)), "CLAIM");
  const checked = instantMs(claim.checked_at);
  need(checked !== null && checked >= instantMs(doc.retrieved_at)!, "CHECKED_AT");
  if (claim.amount === null) need(claim.metric === "RECOGNITION_SCHEDULE" ? !("null_reason" in claim) || cleanText(claim.null_reason, 160)
    : cleanText(claim.null_reason, 160), "NULL_REASON");
  else need(num(claim.amount) && claim.amount >= 0 && claim.amount * claim.unit_multiplier <= MAX_VALUE && !("null_reason" in claim)
    && !("bounds" in claim), "AMOUNT");
  if ("bounds" in claim) {
    const b = claim.bounds;
    need(isObject(b) && Object.keys(b).length > 0 && Object.keys(b).every(k => k === "lower" || k === "upper") && claim.metric !== "RECOGNITION_SCHEDULE"
      && Object.values(b).every(v => num(v) && (v as number) >= 0 && (v as number) * claim.unit_multiplier <= MAX_VALUE)
      && !("lower" in b && "upper" in b && b.lower > b.upper), "BOUNDS");
  }
  const hasPeriod = ["period_start", "period_end", "period_kind"].some(key => key in claim);
  need(!(PERIOD_METRICS.includes(claim.metric) && !hasPeriod) && !(NO_PERIOD_METRICS.includes(claim.metric) && hasPeriod), "PERIOD_FIELDS");
  if (hasPeriod) need(claimDay(claim.period_start) && claimDay(claim.period_end) && days(claim.period_start, claim.period_end) > 0
    && PERIOD_KINDS.includes(claim.period_kind), "PERIOD");
  if (claim.metric === "RECOGNITION_SCHEDULE") {
    const shares = claim.shares;
    need(ident(claim.stock_claim_id) && !claim.stock_claim_id.startsWith(FILING_TARGET) && claim.amount === null && isObject(shares)
      && Object.keys(shares).length > 0 && Object.keys(shares).every(key => ["m6", "m12", "m24"].includes(key)), "SCHEDULE");
    const stated = ["m6", "m12", "m24"].filter(key => key in shares).map(key => shares[key]);
    need(stated.every(v => num(v) && v > 0 && v <= 100) && stated.every((v, i) => i === 0 || v >= stated[i - 1]), "SHARES");
  } else need(!("shares" in claim) && !("stock_claim_id" in claim), "SCHEDULE_FIELDS");
  const revision = claim.revision;
  need(isObject(revision) && onlyKeys(revision, ["kind"], ["targets", "reason", "overlap"])
    && ["ORIGINAL", "REPLACES", "SUPPLEMENTS", "CANCELS"].includes(revision.kind), "REVISION");
  const targets = revision.targets ?? [];
  need(Array.isArray(targets) && targets.length <= 8 && targets.every((t: unknown) => typeof t === "string") && new Set(targets).size === targets.length, "TARGETS");
  for (const target of targets as string[]) {
    if (target.startsWith(FILING_TARGET)) need(ACCESSION.test(target.slice(FILING_TARGET.length)) && (revision.kind === "REPLACES" || revision.kind === "CANCELS")
      && claim.metric === "RPO_STOCK" && claim.scope === "COMPANY" && claim.currency === "USD" && claim.basis === FILING_BASIS, "FILING_TARGET");
    else need(ident(target), "TARGET_ID");
  }
  if (revision.kind === "ORIGINAL") need(targets.length === 0 && !("overlap" in revision) && !("reason" in revision), "ORIGINAL");
  if (revision.kind === "REPLACES" || revision.kind === "CANCELS") need(targets.length > 0 && !("overlap" in revision) && cleanText(revision.reason, 160), "REVISION_REASON");
  if (revision.kind === "SUPPLEMENTS") need(["DISJOINT_PROVEN", "INCLUDED", "UNKNOWN"].includes(revision.overlap) && !("reason" in revision), "OVERLAP");
}

function checkGraph(claims: Map<string, any>, docs: Map<string, any>): void {
  const series = new Map<string, string>();
  for (const claim of claims.values()) {
    need((series.get(claim.series_id) ?? seriesDims(claim)) === seriesDims(claim), "SERIES");
    series.set(claim.series_id, seriesDims(claim));
    if (claim.metric === "RECOGNITION_SCHEDULE") {
      const stock = claims.get(claim.stock_claim_id);
      need(stock && stock.metric === "RPO_STOCK" && stock.currency === claim.currency && stock.scope === "COMPANY" && claim.scope === "COMPANY"
        && stock.as_of === claim.as_of && stock.basis === claim.basis && (stock.document_id === claim.document_id
          || eligibleAt(docs.get(stock.document_id)) <= eligibleAt(docs.get(claim.document_id))), "SCHEDULE_STOCK");
    }
    for (const id of claim.revision.targets ?? []) {
      if (id.startsWith(FILING_TARGET)) continue;
      const target = claims.get(id);
      need(target && id !== claim.id && target.series_id === claim.series_id
        && eligibleAt(docs.get(target.document_id)) <= eligibleAt(docs.get(claim.document_id)), "TARGET");
    }
  }
  const state = new Map<string, number>();
  const visit = (id: string): void => {
    need(state.get(id) !== 1, "CYCLE");
    if (state.get(id) === 2) return;
    state.set(id, 1);
    for (const target of claims.get(id).revision.targets ?? []) if (claims.has(target)) visit(target);
    state.set(id, 2);
  };
  for (const id of claims.keys()) visit(id);
}

/** scripts/order_claims.py select, over the sealed evidence. */
export function selectClaims(documents: any[], claims: any[], cutoffMs: number, filing: { accession: string; filed: string } | null = null) {
  const docs = new Map(documents.map(d => [d.id, d]));
  const excluded = new Map<string, string>();
  const eligible: any[] = [];
  const cutoffDay = new Date(cutoffMs).toISOString().slice(0, 10);
  for (const claim of [...claims].sort((a, b) => (a.id < b.id ? -1 : a.id > b.id ? 1 : 0))) {
    const doc = docs.get(claim.document_id);
    if (eligibleAt(doc) > cutoffMs || instantMs(doc.retrieved_at)! > cutoffMs || instantMs(claim.checked_at)! > cutoffMs
      || dayMs(claim.as_of) > dayMs(cutoffDay)) excluded.set(claim.id, "AFTER_CUTOFF");
    else eligible.push(claim);
  }
  const live = new Set(eligible.map(c => c.id));
  let filingState: string | null = filing ? "ACTIVE" : null;
  let status = "OK";
  for (const claim of eligible) {
    const reason = claim.revision.kind === "CANCELS" ? "CANCELLED" : claim.revision.kind === "REPLACES" ? "SUPERSEDED" : null;
    for (const target of claim.revision.targets ?? []) {
      if (target.startsWith(FILING_TARGET)) {
        if (filing && target === FILING_TARGET + filing.accession && docs.get(claim.document_id).published_date >= filing.filed) filingState = reason;
        else { status = "UNRESOLVED_REVISION"; excluded.set(claim.id, "UNRESOLVED_FILING_TARGET"); }
      } else if (reason && live.has(target)) excluded.set(target, reason);
    }
  }
  let candidates = eligible.filter(c => !excluded.has(c.id));
  const seen = new Set<string>();
  for (const claim of candidates) {
    const key = JSON.stringify([docs.get(claim.document_id).lineage_id, claim.series_id, claim.as_of, observation(claim)]);
    if (seen.has(key)) excluded.set(claim.id, "MIRROR");
    else seen.add(key);
  }
  candidates = candidates.filter(c => !excluded.has(c.id));
  const current: any[] = [];
  const seriesIds = [...new Set(candidates.filter(c => STOCK_METRICS.includes(c.metric)).map(c => c.series_id as string))].sort();
  for (const seriesId of seriesIds) {
    const rows = candidates.filter(c => c.series_id === seriesId).sort((a, b) => (a.as_of + a.id < b.as_of + b.id ? -1 : 1));
    const newest = rows[rows.length - 1].as_of;
    const tops = rows.filter(c => c.as_of === newest);
    for (const row of rows) if (row.as_of !== newest) excluded.set(row.id, "HISTORY");
    if (new Set(tops.map(observation)).size > 1) {
      if (status === "OK") status = "CONFLICTING_DISCLOSURES";
      for (const row of tops) excluded.set(row.id, "CONFLICT");
    } else {
      current.push(tops[0]);
      for (const row of tops.slice(1)) excluded.set(row.id, "MIRROR");
    }
  }
  const comparable = current.filter(c => c.metric === "RPO_STOCK" && c.scope === "COMPANY" && c.currency === "USD"
    && c.assertion_kind === "DISCLOSED_FACT" && c.basis === FILING_BASIS);
  let stock: any = null;
  if (comparable.length > 1) {
    if (status === "OK") status = "CONFLICTING_DISCLOSURES";
    for (const row of comparable) excluded.set(row.id, "AMBIGUOUS_SERIES");
  } else if (comparable.length === 1) stock = comparable[0];
  // Equal observations of the current stock are one observation: every schedule attached to any of them is compared.
  const open = (id: string) => !excluded.has(id) || excluded.get(id) === "MIRROR";
  const aliases = new Set<string>(stock ? eligible.filter(c => c.series_id === stock.series_id && c.as_of === stock.as_of
    && observation(c) === observation(stock) && open(c.id)).map(c => c.id) : []);
  const attached = eligible.filter(c => c.metric === "RECOGNITION_SCHEDULE" && open(c.id) && aliases.has(c.stock_claim_id));
  for (const claim of candidates) {
    if (claim.metric === "RECOGNITION_SCHEDULE" && !excluded.has(claim.id) && !attached.includes(claim)) excluded.set(claim.id, "STOCK_NOT_CURRENT");
  }
  let schedules: any[] = [];
  if (new Set(attached.map(observation)).size > 1) {
    if (status === "OK") status = "CONFLICTING_DISCLOSURES";
    for (const row of attached) excluded.set(row.id, "CONFLICT");
  } else if (attached.length) {
    const chosen = [...attached].sort((a, b) => (a.id < b.id ? -1 : 1))[0];
    schedules = [chosen];
    for (const row of attached) { if (row.id !== chosen.id) excluded.set(row.id, "MIRROR"); else excluded.delete(row.id); }
  }
  const active = eligible.filter(c => !excluded.has(c.id)).map(c => c.id as string).sort();
  return { status, active, current_stock: stock ? stock.id : null, schedule: schedules[0] ? schedules[0].id : null, filing: filingState,
    excluded: [...excluded.entries()].map(([id, reason]): [string, string] => [id, reason])
      .sort((a, b) => (a[0] < b[0] ? -1 : a[0] > b[0] ? 1 : a[1] < b[1] ? -1 : 1)) };
}

// ---- scripts/order_forecast.py from_recognition / from_stock / decide, recomputed from the sealed inputs

const optNum = (value: unknown): number | null => finite(value) ? value : null;
const pyText = (value: unknown, limit: number): string | null =>
  typeof value === "string" && value.trim() ? [...value.trim()].slice(0, limit).join("") : null;
const pyDay = (value: unknown): string | null => isoDay(value) ? value : null;
const failedV = (reason: ForecastReason) => ({ m6: unavailable(reason), m12: unavailable(reason), references: [] as any[] });

function recognitionOf(orders: any, reportDay: string): { m6: any; m12: any; references: any[] } | null {
  if (orders === null || orders === undefined) return null;
  if (!isObject(orders)) return failedV("INVALID");
  const status = orders.status;
  if (status === "NOT_DISCLOSED" || status === "NO_PERIODIC_FILING") return null;
  if (status !== "DISCLOSED") return failedV(["PERIOD_MISMATCH", "INPUTS_MISSING", "INVALID", "STALE"].includes(status) ? status : "INVALID");
  const rpo = optNum(orders.rpo), revenue = optNum(orders.quarter_revenue);
  const asOf = pyDay(orders.rpo_as_of), quarterEnd = pyDay(orders.quarter_end), filed = pyDay(orders.filed);
  const quarterStart = pyDay(orders.quarter_start), reportPeriod = pyDay(orders.report_date);
  const url = https(orders.url) ? orders.url : null, horizons = orders.horizons;
  const accession = orders.accession, passage = pyText(orders.passage, 300), form = pyText(orders.form, 12);
  if ((orders.scope ?? "COMPANY") !== "COMPANY" || (orders.currency ?? "USD") !== "USD") return failedV("INVALID");
  if (!(rpo !== null && rpo > 0 && revenue !== null && revenue > 0) || !asOf || !quarterEnd || !quarterStart || !filed || !reportPeriod || !url
    || typeof accession !== "string" || !ACCESSION.test(accession) || !passage || !(form === "10-Q" || form === "10-K") || !isObject(horizons)
    || days(asOf, filed) < 0 || days(reportDay, filed) > 0 || Math.abs(days(asOf, reportPeriod)) > 45
    || days(quarterStart, quarterEnd) < 60 || days(quarterStart, quarterEnd) > 100) return failedV("INVALID");
  if (Math.abs(days(quarterEnd, asOf)) > 45) return failedV("PERIOD_MISMATCH");
  const age = days(asOf, reportDay);
  if (age < 0 || age > MAX_AGE_DAYS) return failedV(age > MAX_AGE_DAYS ? "STALE" : "INVALID");
  const basis = orders.quarter_basis ?? "FRAME";
  const quarter: any = { quarter_revenue: revenue, quarter_start: quarterStart, quarter_end: quarterEnd, quarter_basis: basis };
  if (basis === "DERIVED_Q4") {
    const derivation = validDerivation(orders.quarter_derivation, revenue, quarterStart, quarterEnd);
    if (!derivation) return failedV("INVALID");
    quarter.quarter_derivation = derivation;
  } else if (basis !== "FRAME") return failedV("INVALID");
  const share = (key: string): ["STATED" | "ABSENT" | "MALFORMED", number | null] => {
    const row = horizons[key];
    if (!isObject(row) || row.derived !== false) return ["ABSENT", null];
    const value = optNum(row.share_pct);
    return value !== null && value > 0 && value <= 100 ? ["STATED", value] : ["MALFORMED", null];
  };
  const shares: Record<string, ["STATED" | "ABSENT" | "MALFORMED", number | null]> = { m6: share("m6"), m12: share("m12"), m24: share("m24") };
  if (Object.values(shares).some(([kind]) => kind === "MALFORMED")) return failedV("INVALID_SHARE");
  const present = ["m6", "m12", "m24"].map(key => shares[key]!).filter(([kind]) => kind === "STATED").map(([, v]) => v as number);
  if (present.some((v, i) => i > 0 && v < present[i - 1]!)) return failedV("SCHEDULE_CONTRADICTION");
  const evidence = { source_url: url, form, filed, accession, passage, report_period: reportPeriod, explicit: true };
  const horizon = (key: string, months: number) => {
    const [kind, value] = shares[key]!;
    if (kind !== "STATED") return unavailable("NOT_DISCLOSED_HORIZON");
    const end = addMonths(asOf, months);
    if (days(reportDay, end) <= 0) return unavailable("EXPIRED");
    const amount = rpo * value! / 100;
    const level = revenue * months / 3;
    const coverage = level > 0 ? amount / level : NaN;
    if (![amount, level, coverage].every(n => Number.isFinite(n) && n > 0)) return unavailable("INVALID");
    const scenario = coverage >= 1 ? { status: "AVAILABLE", coverage, change: coverage - 1 } : { status: "INSUFFICIENT_COVERAGE", coverage };
    return { status: "AVAILABLE", basis: "RECOGNITION", amount, currency: "USD", scope: "COMPANY", start: asOf, end, as_of: asOf, rpo,
      share_pct: value, ...quarter, ...evidence, scenario };
  };
  const references: any[] = [];
  const [kind24, value24] = shares.m24!;
  if (kind24 === "STATED") {
    const end = addMonths(asOf, 24);
    const amount = rpo * value24! / 100;
    if (days(reportDay, end) > 0 && Number.isFinite(amount) && amount > 0) {
      references.push({ kind: "RECOGNITION_24M", amount, currency: "USD", start: asOf, end, as_of: asOf, rpo, share_pct: value24, ...evidence });
    }
  }
  return { m6: horizon("m6", 6), m12: horizon("m12", 12), references };
}

function stockOf(orders: any, reportDay: string): { m6: any; m12: any } | null {
  if (!isObject(orders) || !["RPO", "BACKLOG"].includes(orders.kind)) return null;
  const amount = optNum(orders.amount), growth = optNum(orders.yoy), asOf = pyDay(orders.as_of);
  const url = https(orders.source_url) ? orders.source_url : null, currency = orders.currency;
  const failed = (reason: ForecastReason) => ({ m6: unavailable(reason), m12: unavailable(reason) });
  if (!(amount !== null && amount > 0) || !asOf || !url || !CURRENCIES.has(currency)) return failed("INVALID");
  const age = days(asOf, reportDay);
  if (age < 0 || age > MAX_AGE_DAYS) return failed(age > MAX_AGE_DAYS ? "STALE" : "INVALID");
  if (growth === null) return failed("NO_GROWTH");
  if (!(growth > -1 && growth <= 1)) return failed("GROWTH_OUT_OF_RANGE");
  const prior = optNum(orders.yoy_prior_amount), priorAsOf = pyDay(orders.yoy_prior_as_of), stated = pyText(orders.yoy_evidence, 300);
  let lineage: any;
  if (prior !== null && priorAsOf && prior > 0 && days(priorAsOf, asOf) >= 320 && days(priorAsOf, asOf) <= 410
    && Math.abs(amount / prior - 1 - growth) <= Math.max(1e-9 * Math.max(Math.abs(amount / prior - 1), Math.abs(growth)), 1e-12)) {
    lineage = { lineage: "SERIES", yoy_prior_amount: prior, yoy_prior_as_of: priorAsOf };
  } else if (stated) lineage = { lineage: "COMPANY_STATED", yoy_evidence: stated };
  else return failed("NO_GROWTH_LINEAGE");
  const scope = orders.scope_kind === "COMPANY" ? "COMPANY" : "SEGMENT";
  const level = (day: string) => { const v = amount * Math.pow(1 + growth, days(asOf, day) / 365); return Number.isFinite(v) && v > 0 ? v : null; };
  const baseline = level(reportDay);
  const tile = (months: number) => {
    const end = addMonths(reportDay, months);
    const value = level(end);
    if (baseline === null || value === null || !Number.isFinite(value / baseline)) return unavailable("INVALID");
    return { status: "AVAILABLE", basis: "STOCK_EXTRAPOLATION", amount: value, currency, scope, scope_label: pyText(orders.scope, 40),
      start: reportDay, end, as_of: asOf, stock: amount, yoy: growth, baseline, source_url: url, kind: orders.kind, ...lineage };
  };
  return { m6: tile(6), m12: tile(12) };
}

const quarterOf = (periodic: { m6: any; m12: any } | null) => {
  const h = periodic ? [periodic.m12, periodic.m6].find(x => x.status === "AVAILABLE" && x.basis === "RECOGNITION") : undefined;
  if (!h) return null;
  return { quarter_revenue: h.quarter_revenue, quarter_start: h.quarter_start, quarter_end: h.quarter_end, quarter_basis: h.quarter_basis,
    ...(h.quarter_derivation ? { quarter_derivation: h.quarter_derivation } : {}) };
};

function registryHorizonOf(stock: any, schedule: any, key: "m6" | "m12", months: number, reportDay: string, quarter: any): any {
  const share = optNum(schedule.shares[key]);
  if (share === null) return unavailable("NOT_DISCLOSED_HORIZON");
  const age = days(stock.as_of, reportDay);
  if (age < 0 || age > MAX_AGE_DAYS) return unavailable(age > MAX_AGE_DAYS ? "STALE" : "INVALID");
  const end = addMonths(stock.as_of, months);
  if (days(reportDay, end) <= 0) return unavailable("EXPIRED");
  const rpo = valueOf(stock)!;
  const amount = rpo * share / 100;
  const h: any = { status: "AVAILABLE", basis: "RECOGNITION", source: "REGISTRY", amount, currency: "USD", scope: "COMPANY", start: stock.as_of, end,
    as_of: stock.as_of, rpo, share_pct: share, stock_claim_id: stock.id, schedule_claim_id: schedule.id };
  if (!quarter || Math.abs(days(quarter.quarter_end, stock.as_of)) > 45) return { ...h, scenario: { status: "NO_BASIS", reason: "NO_MATCHING_REVENUE" } };
  const coverage = amount / (quarter.quarter_revenue * months / 3);
  return { ...h, ...quarter, scenario: coverage >= 1 ? { status: "AVAILABLE", coverage, change: coverage - 1 } : { status: "INSUFFICIENT_COVERAGE", coverage } };
}

/** scripts/order_forecast.py _filing_shares: the filing's explicitly stated cumulative shares. */
function filingShares(periodicInput: any): Record<string, number> {
  const out: Record<string, number> = {};
  const horizons = isObject(periodicInput) ? periodicInput.horizons : null;
  for (const key of ["m6", "m12", "m24"]) {
    const row = isObject(horizons) ? horizons[key] : null;
    if (isObject(row) && row.derived === false && finite(row.share_pct)) out[key] = row.share_pct;
  }
  return out;
}
/** scripts/order_forecast.py filing_of. */
function filingOf(periodicInput: any): { accession: string; filed: string } | null {
  if (!isObject(periodicInput) || periodicInput.status !== "DISCLOSED") return null;
  const filed = pyDay(periodicInput.filed);
  return typeof periodicInput.accession === "string" && ACCESSION.test(periodicInput.accession) && filed
    ? { accession: periodicInput.accession, filed } : null;
}

/** scripts/order_forecast.py decide. */
function decideV2(periodicInput: any, stockInput: any, reportDay: string, selection: any, claims: Map<string, any>, limited: boolean) {
  const periodic = recognitionOf(periodicInput, reportDay);
  let references: any[] = periodic ? [...periodic.references] : [];
  const stock = selection?.current_stock ? claims.get(selection.current_stock) : null;
  const schedule = selection?.schedule ? claims.get(selection.schedule) : null;
  const filingState = selection?.filing ?? null;
  const filingAsOf = periodic ? pyDay(periodicInput?.rpo_as_of) : null;
  const filingValue = periodic ? optNum(periodicInput?.rpo) : null;
  const periodicOk = periodic !== null && filingState !== "SUPERSEDED" && filingState !== "CANCELLED";
  let m6: any, m12: any;
  const both = (reason: ForecastReason) => { m6 = unavailable(reason); m12 = unavailable(reason); };
  const sameDate = !!stock && periodicOk && filingAsOf !== null && stock.as_of === filingAsOf;
  if (limited) both("EVIDENCE_LIMIT");
  else if (selection?.status === "UNRESOLVED_REVISION" || selection?.status === "CONFLICTING_DISCLOSURES") both(selection.status);
  else if (sameDate && (!(valueOf(stock) === filingValue && !("bounds" in stock))
    || (schedule && sortedJson(schedule.shares) !== sortedJson(filingShares(periodicInput))))) both("CONFLICTING_DISCLOSURES");
  else if (stock && (!periodicOk || filingAsOf === null || stock.as_of > filingAsOf)) {
    const value = valueOf(stock);
    if (value === null || value <= 0 || (stock.bounds !== undefined && stock.bounds !== null)) both("UNQUANTIFIED_STOCK");
    else if (schedule) {
      const quarter = quarterOf(periodic);
      m6 = registryHorizonOf(stock, schedule, "m6", 6, reportDay, quarter);
      m12 = registryHorizonOf(stock, schedule, "m12", 12, reportDay, quarter);
      const share24 = optNum(schedule.shares.m24);
      const end24 = addMonths(stock.as_of, 24);
      const age = days(stock.as_of, reportDay);
      if (share24 !== null && days(reportDay, end24) > 0 && age >= 0 && age <= MAX_AGE_DAYS) {
        references.push({ kind: "REGISTRY_RECOGNITION_24M", amount: value * share24 / 100, currency: "USD", start: stock.as_of, end: end24,
          rpo: value, share_pct: share24, stock_claim_id: stock.id, schedule_claim_id: schedule.id });
      }
    } else both("NO_REALIZATION_SCHEDULE");
    if (periodic) {
      references = references.filter(r => r.kind !== "RECOGNITION_24M");
      const old = [periodic.m12, periodic.m6].find(h => h.status === "AVAILABLE");
      if (old) references.push({ kind: "SUPERSEDED_SCHEDULE", as_of: old.as_of, rpo: old.rpo, share_pct: old.share_pct, currency: "USD", start: old.start,
        end: old.end, form: old.form, filed: old.filed, accession: old.accession, source_url: old.source_url, by_claim_id: stock.id, filing: filingState ?? "ACTIVE" });
    }
  } else if (periodicOk) { m6 = periodic!.m6; m12 = periodic!.m12; }
  else {
    const kind = stockInput?.kind;
    both(kind === "RPO" || kind === "BACKLOG" || stock ? "NO_REALIZATION_SCHEDULE" : kind === "NOT_DISCLOSED" ? "NOT_DISCLOSED" : "NO_ORDERS");
    references = [];
  }
  for (const h of [m6, m12]) if (h.status === "AVAILABLE" && !("source" in h)) h.source = "PERIODIC";
  const used = new Set([m6, m12, ...references].flatMap(x => [x.stock_claim_id, x.schedule_claim_id]).filter(Boolean));
  for (const id of selection?.active ?? []) if (!used.has(id)) references.push({ kind: "CLAIM", claim_id: id });
  const g = stockInput?.guidance;
  if (isObject(g) && g.kind === "ANNUAL_NEW_ORDERS" && finite(g.amount) && g.amount > 0 && Number.isInteger(g.year) && CURRENCIES.has(stockInput.currency)) {
    references.push({ kind: "ANNUAL_NEW_ORDERS_GUIDANCE", amount: g.amount, currency: stockInput.currency, year: g.year,
      source_url: https(stockInput.source_url) ? stockInput.source_url : null });
  }
  const sens = stockOf(stockInput, reportDay);
  const sensitivity = sens && (sens.m6.status === "AVAILABLE" || sens.m12.status === "AVAILABLE")
    ? Object.fromEntries((["m6", "m12"] as const).map(k => [k, sens[k].status === "AVAILABLE" ? sens[k] : { status: "UNAVAILABLE", reason: sens[k].reason }]))
    : null;
  const available = m6.status === "AVAILABLE" || m12.status === "AVAILABLE";
  return { status: available ? "AVAILABLE" : "UNAVAILABLE", reason: topReason(m6, m12), m6, m12, stock_sensitivity: sensitivity, references };
}

/** Deep equality with relative closeness for numbers (the two languages may differ in the last bits of a power). */
function same(a: unknown, b: unknown): boolean {
  if (typeof a === "number" || typeof b === "number") return a === b || close(a, b);
  if (Array.isArray(a) || Array.isArray(b)) return Array.isArray(a) && Array.isArray(b) && a.length === b.length && a.every((v, i) => same(v, b[i]));
  if (isObject(a) || isObject(b)) {
    if (!isObject(a) || !isObject(b)) return false;
    const ka = Object.keys(a).sort(), kb = Object.keys(b).sort();
    return ka.length === kb.length && ka.every((k, i) => k === kb[i] && same(a[k], b[k]));
  }
  return a === b;
}

function claimView(claim: any, docs: Map<string, any>, excluded: Map<string, string>): ClaimView {
  const doc = docs.get(claim.document_id);
  const bounds = claim.bounds ? Object.fromEntries(Object.entries(claim.bounds).map(([k, v]) => [k, (v as number) * claim.unit_multiplier])) : null;
  return { id: claim.id, metric: claim.metric, assertion_kind: claim.assertion_kind, currency: claim.currency, value: valueOf(claim),
    bounds, as_of: claim.as_of, scope: claim.scope, scope_label: claim.scope_label ?? null, summary: claim.summary ?? null,
    passage: claim.passage, locator: claim.locator, published_date: doc.published_date, checked_date: claim.checked_at.slice(0, 10),
    source_url: doc.url, source_kind: doc.source_kind, revision: claim.revision.kind, revision_reason: claim.revision.reason ?? null,
    targets: claim.revision.targets ?? [], period: claim.period_start ? `${claim.period_start}–${claim.period_end}` : null,
    excluded: excluded.get(claim.id) ?? null };
}

function parseV2(value: any, reportDay: string, issuer: string, generatedAt: string | undefined): OrderForecast {
  const invalid = normalized(2, unavailable("INVALID"), unavailable("INVALID"));
  try {
    const ev = value.evidence;
    need(isObject(value) && onlyKeys(value, ["version", "issuer", "status", "reason", "m6", "m12", "stock_sensitivity", "references", "evidence"], [])
      && value.issuer === issuer && Array.isArray(value.references) && value.references.length <= MAX_ISSUER_CLAIMS + 4, "SHAPE");
    need(isObject(ev) && onlyKeys(ev, ["registry_status", "registry_sha256", "cutoff", "url_prefixes", "documents", "claims", "selection",
      "periodic", "stock_orders"], []) && ["OK", "EMPTY", "UNAVAILABLE", "INVALID"].includes(ev.registry_status)
      && typeof generatedAt === "string" && ev.cutoff === generatedAt && instantMs(ev.cutoff) !== null && ev.cutoff.slice(0, 10) === reportDay
      && Array.isArray(ev.documents) && Array.isArray(ev.claims) && Array.isArray(ev.url_prefixes)
      && (ev.periodic === null || isObject(ev.periodic)) && (ev.stock_orders === null || isObject(ev.stock_orders)), "EVIDENCE");
    need(ev.registry_status === "UNAVAILABLE" ? ev.registry_sha256 === null : typeof ev.registry_sha256 === "string" && /^[0-9a-f]{64}$/.test(ev.registry_sha256), "DIGEST");
    const cutoff = instantMs(ev.cutoff)!;
    const docs = new Map<string, any>();
    const claims = new Map<string, any>();
    let selection: any = null;
    let limited = false;
    const filing = filingOf(ev.periodic);
    if (ev.registry_status === "OK" || ev.registry_status === "EMPTY") {
      need(ev.url_prefixes.length <= 4 && ev.url_prefixes.every((p: unknown) => typeof p === "string" && p.length <= 120 && PREFIX_RE.test(p)
        && !p.startsWith("https://www.sec.gov/")), "PREFIXES");
      if (isObject(ev.selection) && ev.selection.status === "EVIDENCE_LIMIT") {
        need(onlyKeys(ev.selection, ["status"], []) && ev.documents.length === 0 && ev.claims.length === 0, "LIMIT");
        limited = true;
      } else {
        need(ev.documents.length <= MAX_ISSUER_DOCUMENTS && ev.claims.length <= MAX_ISSUER_CLAIMS, "BOUNDS");
        for (const doc of ev.documents) { checkDocument(doc, issuer, ev.url_prefixes); need(!docs.has(doc.id), "DUP_DOC"); docs.set(doc.id, doc); }
        for (const claim of ev.claims) { checkClaim(claim, docs, issuer); need(!claims.has(claim.id), "DUP_CLAIM"); claims.set(claim.id, claim); }
        need([...docs.keys()].every(id => [...claims.values()].some(c => c.document_id === id)), "UNUSED_DOC");
        need(presentationSize(ev.documents, ev.claims) <= PRESENTATION_BUDGET, "PRESENTATION_BUDGET");
        checkGraph(claims, docs);
        selection = selectClaims(ev.documents, ev.claims, cutoff, filing);
        need(same(selection, ev.selection), "SELECTION");
      }
    } else need(ev.documents.length === 0 && ev.claims.length === 0 && ev.selection === null && ev.url_prefixes.length === 0, "NO_REGISTRY");
    const expected = decideV2(ev.periodic, ev.stock_orders, reportDay, selection, claims, limited);
    for (const key of ["status", "reason", "m6", "m12", "stock_sensitivity", "references"] as const) need(same(value[key], expected[key]), `RECOMPUTE_${key}`);
    const excluded = new Map<string, string>((selection?.excluded ?? []) as [string, string][]);
    const views = [...claims.values()].map(c => claimView(c, docs, excluded));
    const references: ForecastReference[] = [];
    const supplements: ClaimView[] = [];
    const superseded: SupersededView[] = [];
    const registry: RegistryReference[] = [];
    for (const ref of expected.references) {
      if (ref.kind === "CLAIM") supplements.push(views.find(v => v.id === ref.claim_id)!);
      else if (ref.kind === "SUPERSEDED_SCHEDULE") superseded.push(ref);
      else if (ref.kind === "REGISTRY_RECOGNITION_24M") registry.push(ref);
      else references.push(ref);
    }
    // The current stock first: it explains the figures above (or their absence); then the other disclosures by id.
    supplements.sort((a, b) => Number(b.id === selection?.current_stock) - Number(a.id === selection?.current_stock));
    return { ...normalized(2, expected.m6, expected.m12), sensitivity: expected.stock_sensitivity as Sensitivity | null, references, supplements,
      superseded, registry24: registry, registry: ev.registry_status, cutoff: ev.cutoff, claims: views,
      currentStock: selection?.current_stock ?? null, schedule: selection?.schedule ?? null };
  } catch (error) {
    if (error instanceof EvidenceError) return invalid;
    throw error;
  }
}

// ---------------------------------------------------------------- rendering
// Wording from the Astra contract ORDERS-V2-01 (operator 2026-09-27: "未來訂單預估, 若實現股價要註明時間: 半年、1年實現的訂單,
// 股價預估成長多少"). Both horizons always appear as their own row with their own window; unavailable is never 0 or 無;
// every date shown is the date of the input it describes, never the build time.

const REASON_TEXT: Record<ForecastReason, string> = {
  NOT_DISCLOSED_HORIZON: "公司未揭露此期間認列時程", PERIOD_MISMATCH: "訂單與營收期間不一致", INPUTS_MISSING: "缺少 RPO 或同期營收",
  INVALID: "資料未通過驗證", STALE: "訂單資料逾200天", NO_GROWTH: "訂單無可比年增", GROWTH_OUT_OF_RANGE: "訂單年增超出可外推範圍",
  NOT_DISCLOSED: "公司未揭露訂單", NO_ORDERS: "未取得訂單資料", EXPIRED: "期間已結束", SCHEDULE_CONTRADICTION: "認列時程前後矛盾",
  NO_GROWTH_LINEAGE: "年增缺少可比基期", INVALID_SHARE: "揭露的認列比例無效", LEGACY: "訂單預估尚未產生",
  NO_REALIZATION_SCHEDULE: "公司未揭露認列時程", CONFLICTING_DISCLOSURES: "公司揭露互相矛盾，暫不估算", EVIDENCE_LIMIT: "證據超出上限，暫不估算",
  UNQUANTIFIED_STOCK: "最新揭露無可計算的訂單金額", UNRESOLVED_REVISION: "公司更正無法對應到本次申報，暫不估算",
};
const LABEL = { m6: "半年", m12: "1年" } as const;
const UNDISCLOSED = new Set<ForecastReason>(["NOT_DISCLOSED_HORIZON", "NO_REALIZATION_SCHEDULE", "NOT_DISCLOSED"]);
const SOURCE_KIND_TEXT: Record<string, string> = { SEC_PERIODIC: "SEC 定期報告", SEC_8K_EXHIBIT: "SEC 8-K 附件",
  ISSUER_EARNINGS_RELEASE: "公司財報新聞稿", ISSUER_PREPARED_REMARKS: "公司法說會講稿", ISSUER_CONTRACT_ANNOUNCEMENT: "公司合約公告" };
const METRIC_TEXT: Record<string, string> = { RPO_STOCK: "RPO", BACKLOG_STOCK: "在手訂單", SIGNED_CONTRACT_VALUE: "已簽合約",
  ORDER_INTAKE: "新接訂單", ORDER_GUIDANCE: "公司訂單指引", RECOGNITION_SCHEDULE: "認列時程" };
export const CONDITION_TEXT = "條件情境：營收達預計認列額，P/S與股數不變；非目標價、非今日起報酬";
export const RPO_TEXT = "RPO 為剩餘履約義務，非全部訂單；預計認列非保證";
export const SENSITIVITY_TITLE = "訂單餘額外推敏感度（非訂單實現情境）";
export const SENSITIVITY_TEXT = "模型推估，非公司揭露、非期間認列";

const signedPct = (value: number) => value === 0 ? "0%" : `${value > 0 ? "+" : "−"}${Math.abs(value * 100).toFixed(0)}%`;
const coveragePct = (value: number) => `${(value * 100) < 10 ? (value * 100).toFixed(1) : (value * 100).toFixed(0)}%`;
type Money = (amount: number, currency: string | null) => string;
type Key = "m6" | "m12";

function orderState(h: ForecastHorizon, money: Money): string {
  if (h.status === "AVAILABLE") return money(h.amount!, h.currency!);
  if (UNDISCLOSED.has(h.reason!)) return "未揭露";
  if (h.reason === "NO_ORDERS") return "未取得訂單資料";
  if (h.reason === "LEGACY") return "尚未產生";
  if (h.reason === "UNQUANTIFIED_STOCK") return "無可計算金額";
  if (h.reason === "STALE") return "資料逾200天";
  if (h.reason === "EXPIRED" || h.reason === "CONFLICTING_DISCLOSURES" || h.reason === "UNRESOLVED_REVISION") return REASON_TEXT[h.reason];
  return "資料未通過驗證";
}

/** "半年內預計認列：US$1.2B（起算日 2026-07-26（非今日起），至 2027-01-26）". */
function orderRow(forecast: OrderForecast, key: Key, money: Money): string {
  const h = forecast[key];
  const window = h.status === "AVAILABLE" ? `（起算日 ${h.start}（非今日起），至 ${h.end}）` : "";
  return `${LABEL[key]}內預計認列：${orderState(h, money)}${window}`;
}

/** "若半年內實現訂單 → 股價預估 +12%", or why it cannot be priced. */
function priceRow(forecast: OrderForecast, key: Key): string {
  const h = forecast[key];
  const head = `若${LABEL[key]}內實現訂單 → `;
  if (h.status === "AVAILABLE") {
    const s = h.scenario;
    if (s.status === "AVAILABLE") return `${head}股價預估 ${signedPct(s.change!)}`;
    if (s.status === "INSUFFICIENT_COVERAGE") return `${head}無法估價（訂單僅覆蓋同期營收 ${coveragePct(s.coverage!)}）`;
    return `${head}無法估價（${s.reason === "NO_MATCHING_REVENUE" ? "缺同期營收" : "缺認列時程"}）`;
  }
  if (h.reason === "CONFLICTING_DISCLOSURES" || h.reason === "UNRESOLVED_REVISION") return `${head}${REASON_TEXT[h.reason]}`;
  if (h.reason === "EXPIRED") return `${head}無法估價（期間已結束）`;
  if (h.reason === "NO_ORDERS") return `${head}無法估價（未取得訂單資料）`;
  if (h.reason === "UNQUANTIFIED_STOCK") return `${head}無法估價（最新揭露無可計算金額）`;
  if (h.reason === "STALE") return `${head}無法估價（資料逾200天）`;
  return `${head}無法估價（${UNDISCLOSED.has(h.reason!) || h.reason === "LEGACY" ? "缺認列時程" : "資料未通過驗證"}）`;
}

const basisOf = (forecast: OrderForecast) => [forecast.m12, forecast.m6].find(h => h.status === "AVAILABLE") ?? null;
const priced = (forecast: OrderForecast) => [forecast.m6, forecast.m12].some(h => h.status === "AVAILABLE" && h.scenario.status === "AVAILABLE");
const claimOf = (forecast: OrderForecast, id: string | null | undefined) => forecast.claims.find(c => c.id === id) ?? null;

/** "訂單資料截至 {as_of}｜來源公布 {published}｜本次查核 {checked}" for the figures shown; a filing has no review time. */
function contextLine(forecast: OrderForecast): string | null {
  const h = basisOf(forecast);
  if (!h) return null;
  if (h.source !== "REGISTRY") return `訂單資料截至 ${h.as_of}｜來源公布 ${h.filed}`;
  const stock = claimOf(forecast, h.stock_claim_id)!;
  const schedule = claimOf(forecast, h.schedule_claim_id)!;
  const scheduleDate = schedule.published_date !== stock.published_date ? `｜時程公布 ${schedule.published_date}` : "";
  const checked = stock.checked_date >= schedule.checked_date ? stock.checked_date : schedule.checked_date;
  return `訂單資料截至 ${h.as_of}｜來源公布 ${stock.published_date}${scheduleDate}｜本次查核 ${checked}`;
}

const observed = (c: ClaimView, money: Money) => c.value !== null ? money(c.value, c.currency)
  : c.bounds ? `${c.bounds.lower !== undefined ? `≥${money(c.bounds.lower, c.currency)}` : ""}${c.bounds.upper !== undefined ? `≤${money(c.bounds.upper, c.currency)}` : ""}（區間）`
  : "未揭露金額";

/** One line for a later disclosure shown beside the figures (never added to them). */
function claimLine(forecast: OrderForecast, c: ClaimView, money: Money): string {
  if (c.metric === "RPO_STOCK" || c.metric === "BACKLOG_STOCK") {
    const label = `${METRIC_TEXT[c.metric]}${c.scope === "COMPANY" ? "" : `（${c.scope_label}）`}`;
    if (c.id === forecast.currentStock) {
      // Why the rows above look as they do, from their actual state.
      const shown = basisOf(forecast);
      const why = shown?.source === "REGISTRY" || forecast.schedule ? "認列時程見上"
        : shown?.source === "PERIODIC" ? (c.as_of === shown.as_of && c.value === shown.rpo ? "與申報同日同額，沿用申報之認列時程"
          : c.as_of < shown.as_of! ? `早於申報量測（${shown.as_of}），僅供參考` : "僅供參考")
        : forecast.m12.reason === "NO_REALIZATION_SCHEDULE" ? "公司未揭露其認列時程" : REASON_TEXT[forecast.m12.reason ?? forecast.m6.reason!];
      return `最新揭露 ${label}：${observed(c, money)}（截至 ${c.as_of}，公布 ${c.published_date}）；${why}`;
    }
    return `其他揭露 ${label}：${observed(c, money)}（截至 ${c.as_of}，公布 ${c.published_date}；不併入上方數字）`;
  }
  const summary = c.summary ?? observed(c, money);
  if (c.revision === "CANCELS" || c.revision === "REPLACES") return `期後訂單更正（不併入 RPO）：${summary}（${c.published_date}；${c.revision_reason}）`;
  if (c.metric === "ORDER_GUIDANCE") return `公司訂單指引（非已簽約訂單，${c.period}）：${summary}（${c.published_date}）`;
  if (c.metric === "ORDER_INTAKE") return `新接訂單（${c.period}，不併入 RPO）：${summary}（${c.published_date}）`;
  return `期後訂單消息（不併入 RPO）：${summary}（${c.published_date}）`;
}

/** Later disclosures, supersession and the registry state. Summaries show one disclosure and a count; the detail all. */
function supplementLines(forecast: OrderForecast, money: Money, detail: boolean): string[] {
  if (forecast.version === 1) return [];
  const lines: string[] = [];
  if (forecast.registry === "UNAVAILABLE") lines.push("期後訂單補充：無法讀取");
  else if (forecast.registry === "INVALID") lines.push("期後訂單補充：資料未通過驗證");
  else if (!forecast.supplements.length && !forecast.superseded.length) lines.push("尚無已驗證的期後訂單補充");
  const shown = detail ? forecast.supplements : forecast.supplements.slice(0, 1);
  for (const c of shown) {
    lines.push(claimLine(forecast, c, money));
    if (detail) {
      const scope = c.scope === "COMPANY" ? "全公司" : c.scope_label;
      lines.push(`　${METRIC_TEXT[c.metric]}；${scope}；截至 ${c.as_of}${c.period ? `；期間 ${c.period}` : ""}${c.revision_reason ? `；${c.revision === "CANCELS" ? "取消" : "更正"}理由：${c.revision_reason}` : ""}`);
      lines.push(`　${SOURCE_KIND_TEXT[c.source_kind] ?? c.source_kind} ${c.published_date}（${c.locator}）${c.source_url}；原文：「${[...c.passage].slice(0, 160).join("")}」；本次查核 ${c.checked_date}`);
    }
  }
  if (!detail && forecast.supplements.length > 1) lines.push(`另有 ${forecast.supplements.length - 1} 則期後訂單消息（詳見瓶頸詳情）`);
  for (const old of forecast.superseded) {
    const by = claimOf(forecast, old.by_claim_id);
    const verb = old.filing === "CANCELLED" ? "撤回" : old.filing === "SUPERSEDED" ? "更正" : "更新";
    lines.push(`已由 ${by?.published_date ?? "（未知日期）"} 公司揭露${verb}；前值保留供查核`);
    if (detail) lines.push(`　前值：${old.form} ${old.filed}（${old.accession}）RPO ${money(old.rpo, "USD")}（截至 ${old.as_of}）× ${old.share_pct}% 於 ${old.start}–${old.end} 認列；${old.source_url}`);
  }
  if (detail) {
    for (const c of forecast.claims.filter(x => x.excluded === "SUPERSEDED" || x.excluded === "CANCELLED")) {
      const by = forecast.claims.find(x => x.targets.includes(c.id) && !x.excluded);
      lines.push(`　已${c.excluded === "CANCELLED" ? "取消" : "更正"}：${METRIC_TEXT[c.metric]} ${observed(c, money)}（${c.published_date}）→ 依 ${by?.published_date ?? "後續"} 揭露（${by?.revision_reason ?? ""}）`);
    }
  }
  return lines;
}

function sensitivityLines(forecast: OrderForecast, money: Money, detail: boolean): string[] {
  const s = forecast.sensitivity;
  if (!s) return [];
  const row = (key: Key) => {
    const h = s[key];
    return `${LABEL[key]}後訂單餘額外推：${h.status === "AVAILABLE" ? `${money(h.amount!, h.currency!)}（至 ${h.end}）` : REASON_TEXT[h.reason!]}`;
  };
  const lines = [SENSITIVITY_TITLE, row("m6"), row("m12"), SENSITIVITY_TEXT];
  const h = [s.m12, s.m6].find(x => x.status === "AVAILABLE");
  if (detail && h) {
    const growth = h.lineage === "SERIES" ? `對比 ${h.yoy_prior_as_of} 的 ${money(h.yoy_prior_amount!, h.currency!)}` : `公司自述：「${(h.yoy_evidence ?? "").slice(0, 80)}」`;
    lines.push(`　${h.scope === "SEGMENT" ? `${h.scope_label ?? "部門"}（非全公司）` : ""}${h.kind === "RPO" ? "RPO" : "在手訂單"}餘額 ${money(h.stock!, h.currency!)}（截至 ${h.as_of}）依年增${signedPct(h.yoy!)}（${growth}）自今日起外推；期末餘額，非期間認列；來源：${h.source_url}`);
  }
  return lines;
}

/** The card's order block, one entry per line: [text, heading]. Both horizons, their windows, the conditional price rows
 * and the dates of the data always appear together. */
export function forecastCard(forecast: OrderForecast, money: Money): [string, boolean][] {
  const lines: [string, boolean][] = [["未來訂單預估", true], [orderRow(forecast, "m6", money), false], [orderRow(forecast, "m12", money), false],
    ["訂單實現後股價情境", true], [priceRow(forecast, "m6"), false], [priceRow(forecast, "m12"), false]];
  if (priced(forecast)) lines.push([CONDITION_TEXT, false]);
  if (basisOf(forecast)) lines.push([RPO_TEXT, false]);
  const context = contextLine(forecast);
  if (context) lines.push([context, false]);
  for (const line of supplementLines(forecast, money, false)) lines.push([line, false]);
  for (const line of sensitivityLines(forecast, money, false)) lines.push([line, line === SENSITIVITY_TITLE]);
  return lines;
}

/** The same block in one line for the text form of the Top20. */
export function forecastText(forecast: OrderForecast, money: Money): string {
  const parts = [`未來訂單預估：${orderRow(forecast, "m6", money)}／${orderRow(forecast, "m12", money)}`,
    `訂單實現後股價情境：${priceRow(forecast, "m6")}／${priceRow(forecast, "m12")}${priced(forecast) ? `（${CONDITION_TEXT}）` : ""}`];
  if (basisOf(forecast)) parts.push(RPO_TEXT);
  const context = contextLine(forecast);
  if (context) parts.push(context);
  parts.push(...supplementLines(forecast, money, false));
  if (forecast.sensitivity) parts.push(`${SENSITIVITY_TITLE}：${sensitivityLines(forecast, money, false).slice(1, 3).join("／")}（${SENSITIVITY_TEXT}）`);
  return parts.join("｜");
}

/** The detail lines: each horizon with its window, inputs, assumptions and source, then later disclosures with their
 * revision reasons, the model sensitivity and the fixed-period references. */
export function forecastLines(forecast: OrderForecast, money: Money): string[] {
  const lines: string[] = ["未來訂單預估"];
  const sources = new Set<string>();
  for (const key of ["m6", "m12"] as const) {
    const h = forecast[key];
    if (h.status !== "AVAILABLE") {
      lines.push(`${LABEL[key]}內預計認列：${orderState(h, money)}（${REASON_TEXT[h.reason!]}）`);
      continue;
    }
    lines.push(`${orderRow(forecast, key, money)}＝RPO ${money(h.rpo!, h.currency!)}（截至 ${h.as_of}）× 公司揭露${LABEL[key]}內認列 ${h.share_pct}%；全公司`);
    if (h.source === "REGISTRY") {
      for (const c of [claimOf(forecast, h.stock_claim_id), claimOf(forecast, h.schedule_claim_id)]) {
        if (c) sources.add(`訂單來源：${SOURCE_KIND_TEXT[c.source_kind] ?? c.source_kind} ${c.published_date}（${c.locator}）${c.source_url}；原文：「${[...c.passage].slice(0, 160).join("")}」；本次查核 ${c.checked_date}${c.revision_reason ? `；${c.revision === "CANCELS" ? "取消" : "更正"}理由：${c.revision_reason}` : ""}`);
      }
    } else {
      sources.add(`訂單來源：${h.form ?? "申報"} ${h.filed}${h.accession ? `（${h.accession}）` : ""} ${h.source_url}${h.passage ? `；原文：「${h.passage.slice(0, 160)}」` : ""}`);
    }
  }
  lines.push("訂單實現後股價情境");
  for (const key of ["m6", "m12"] as const) {
    const h = forecast[key];
    lines.push(priceRow(forecast, key));
    if (h.status === "AVAILABLE" && h.scenario.status !== "NO_BASIS") {
      const quarter = h.quarter_basis === "DERIVED_Q4" && h.quarter_derivation
        ? `${h.quarter_end} 當季（第四季＝全年 ${money(h.quarter_derivation.annual, "USD")} − 前九個月 ${money(h.quarter_derivation.nine_months, "USD")}）`
        : `${h.quarter_end} 當季`;
      lines.push(`　同期營收水準＝${quarter} ${money(h.quarter_revenue!, h.currency!)}×${MONTHS[key] / 3}；覆蓋率 ${coveragePct(h.scenario.coverage!)}${h.scenario.status === "INSUFFICIENT_COVERAGE" ? "；其餘營收來源未由本訂單資料涵蓋" : ""}`);
    }
  }
  if (priced(forecast)) lines.push(`${CONDITION_TEXT}；未計新訂單、取消或遞延`);
  if (basisOf(forecast)) lines.push(RPO_TEXT);
  const context = contextLine(forecast);
  if (context) lines.push(context);
  lines.push(...sources);
  lines.push(...supplementLines(forecast, money, true));
  lines.push(...sensitivityLines(forecast, money, true));
  for (const ref of forecast.registry24) {
    lines.push(`參考（固定期間，非半年／1年）：24個月內認列 ${money(ref.amount, "USD")}（RPO × ${ref.share_pct}%，${ref.start}–${ref.end}）。`);
  }
  for (const ref of forecast.references) {
    lines.push(ref.kind === "RECOGNITION_24M"
      ? `參考（固定期間，非半年／1年）：24個月內認列 ${money(ref.amount, ref.currency)}（RPO × ${ref.share_pct}%，${ref.start}–${ref.end}）。`
      : `參考（固定期間，公司指引，非已簽約訂單）：${ref.year}年全年新接訂單指引 ${money(ref.amount, ref.currency)}。`);
  }
  return lines;
}
