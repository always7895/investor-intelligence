import { createHash } from "node:crypto";
import { validateMachineEnvelope, machineContextIsValid, machineEffectiveReceipt,
  type MachineBindings, type MachineAdmissionContext } from "./revenue-guidance-machine";

/** The Top20 card's 6-month and 1-year ORDER figures and the price change if those orders are realized (operator
 * 2026-09-27; Astra contract "order horizons and order-linked price scenarios"). The sealer computes them with
 * scripts/order_forecast.py; this module re-validates every sealed record against the same rules (issuer, scope, currency,
 * evidence, windows, the cumulative schedule, and every derived value recomputed from its sealed inputs) and renders them.
 * A record that fails is shown as unavailable, never replaced by another figure; no analyst estimate enters the v1/v2
 * tiles. Version 3 (Astra contract ORDERS-V3-01) adds a separate total-revenue model: company revenue guidance plus
 * model, or a validated quarterly analyst-consensus plus model, kept distinct from contracted order recognition. */

export type ForecastReason = "NOT_DISCLOSED_HORIZON" | "PERIOD_MISMATCH" | "INPUTS_MISSING" | "INVALID" | "STALE" | "NO_GROWTH"
  | "GROWTH_OUT_OF_RANGE" | "NOT_DISCLOSED" | "NO_ORDERS" | "EXPIRED" | "SCHEDULE_CONTRADICTION" | "NO_GROWTH_LINEAGE" | "INVALID_SHARE" | "LEGACY"
  | "NO_REALIZATION_SCHEDULE" | "CONFLICTING_DISCLOSURES" | "EVIDENCE_LIMIT" | "UNQUANTIFIED_STOCK" | "UNRESOLVED_REVISION"
  | "NO_REVENUE_HISTORY" | "NO_REVENUE_BASIS" | "WITHDRAWN" | "FRESHNESS_UNVERIFIED" | "QUARTER_END_EXCEEDED_70D" | "SAMPLE_INSUFFICIENT";
export interface ForecastScenario { status: "AVAILABLE" | "INSUFFICIENT_COVERAGE" | "NO_BASIS"; coverage?: number; change?: number;
  reason?: "NO_ORDER_BASIS" | "SCOPE_PARTIAL" | "NO_MATCHING_REVENUE" | "NO_REVENUE_HISTORY" | "NO_REVENUE_BASIS" | "INVALID_BASELINE" }
export interface ForecastHorizon {
  status: "AVAILABLE" | "UNAVAILABLE"; reason?: ForecastReason;
  basis?: "RECOGNITION" | "STOCK_EXTRAPOLATION" | "COMPANY_GUIDANCE" | "CONSENSUS";
  basis_label?: string;
  /** v2: where a recognition figure comes from (the periodic filing or a reviewed later claim) and its claims. */
  source?: "PERIODIC" | "REGISTRY"; stock_claim_id?: string; schedule_claim_id?: string;
  amount?: number; currency?: string; scope?: "COMPANY" | "SEGMENT"; scope_label?: string | null;
  start?: string; end?: string; as_of?: string; source_url?: string;
  horizon_label?: string; qualifier?: string; ttm_revenue?: number;
  warning?: { quarter_index: number; quarter_end: string; checked_at: string; text: string; is_fy: boolean } | null;
  contracted_recognition?: { amount: number; currency: string; start: string; end: string; as_of?: string; share_pct?: number; rpo?: number } | null;
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
  /** Distinct semantic data admission, never human approval/native certification. */
  machineAdmitted?: boolean;
  version: 1 | 2 | 3; issuer?: string; m6: ForecastHorizon; m12: ForecastHorizon; sensitivity: Sensitivity | null; references: ForecastReference[];
  supplements: ClaimView[]; superseded: SupersededView[]; registry24: RegistryReference[]; registry: string | null; cutoff: string | null;
  claims: ClaimView[]; currentStock: string | null; schedule: string | null;
  formula?: string; horizonConvention?: string; revenueStatus?: "AVAILABLE" | "UNAVAILABLE";
  revenueBasis?: "COMPANY_GUIDANCE" | "CONSENSUS" | null; revenueReason?: string | null;
  /** v3 (Astra W1 ruling, astra-ir-coverage; acceptance r7 A1/A3): the distinct diagnostic on an unavailable revenue
   * path - "IR_COVERAGE_MISSING" (官方IR查核未完成，暫停營收推估), "UNREVIEWED_INPUTS" (營收輸入未經審核，
   * 暫停營收推估) or "CONSENSUS_DEFERRED" (公司未提供營收財測；分析師共識路線本次未啟用); null for every other
   * state. Independent order recognition is never suppressed by any of them. "MACHINE_INPUTS_UNAVAILABLE" marks the
   * machine route's fail-closed fallback (missing or invalid sealed machine inputs); it adds no display line. */
  revenueDiagnostic?: "IR_COVERAGE_MISSING" | "UNREVIEWED_INPUTS" | "CONSENSUS_DEFERRED" | "MACHINE_INPUTS_UNAVAILABLE" | null;
  anchorDate?: string | null; baselineB?: number | null; reportedQuarters?: any[];
  forwardQuarters?: any[]; contractedRecognition?: any | null; assumptions?: string | null;
  latestReleaseCheck?: any; warning?: any | null;
  /** v3 (Astra r5 item 19; acceptance r7 A5): the bounded provenance list of every operative selected input, rendered
   * only from validated evidence: each selected operational claim (its representation, operative quote, locator and
   * URL), the reaffirmations, the used actuals' document/locator and derivation operands, the YTD block, the fiscal
   * calendar source and the selected consensus quarters (with their analyst counts). The detail renders the full
   * list; the compact card keeps its bounded two lines. */
  revenueSources?: {
    role: "GUIDANCE" | "CALENDAR" | "REAFFIRMATION" | "ACTUAL" | "YTD" | "CONSENSUS";
    representation?: string; passage?: string; publisher?: string; source_kind?: string; published_date?: string;
    captured_at?: string; url?: string; locator?: string; document_id?: string; quarter_end?: string;
    analysts?: number; period?: string; ytd_revenue?: number; derivation?: { longer_value: number; shorter_value: number };
  }[];
}
const normalized = (version: 1 | 2 | 3, m6: ForecastHorizon, m12: ForecastHorizon): OrderForecast =>
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
  if (value.version === 3) return parseV3(value, reportDay, issuer, generatedAt);
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

const V3_SOURCE_KINDS = new Set([
  "SEC_PERIODIC",
  "SEC_8K_EXHIBIT",
  "SEC_6K_EXHIBIT",
  "ISSUER_EARNINGS_RELEASE",
  "ISSUER_TRANSCRIPT",
  "ISSUER_PRESENTATION",
  "OFFICIAL_FISCAL_CALENDAR",
  "OFFICIAL_FINANCIAL_STATEMENT",
]);
const MAX_V3_DOCUMENTS = 16;
const MAX_V3_CLAIMS = 8;
const MAX_V3_ACTUALS = 8;
const MAX_V3_DOC_BYTES = 52_428_800; // 50 * 1024 * 1024
const MAX_V3_PASSAGE = 1000;
const MAX_V3_URL = 400;
const ACCOUNTING_BASES_V3 = new Set(["GAAP", "NON_GAAP", "IFRS", "K-IFRS"]);
// The official IR channel (Astra W1 ruling, astra-ir-coverage) joins the two classic release-check channels; the
// receipt's required channel set and coverage label are split by the record's reviewed wiring (see recomputeReceiptStatus).
const VALID_V3_RECEIPT_CHANNELS = new Set(["SEC_SUBMISSIONS", "WIRE_PRESS_RELEASES", "ISSUER_IR"]);
const VALID_V3_LATER_DISPOSITIONS = new Set(["RESULTS_RELEASE", "POSSIBLY_RELEVANT", "IRRELEVANT", "REVIEWED_IRRELEVANT"]);

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

const closeV3 = (a: unknown, b: unknown) => finite(a) && finite(b) && Math.abs(a - b) <= 1e-9 * Math.max(1, Math.abs(a), Math.abs(b));

function dayAfter(dStr: string): string {
  const d = new Date(dStr + "T00:00:00Z");
  d.setUTCDate(d.getUTCDate() + 1);
  return d.toISOString().slice(0, 10);
}

function canonicalJson(node: unknown): string {
  if (node === null) return "null";
  if (typeof node === "boolean") return node ? "true" : "false";
  if (typeof node === "number") {
    if (!Number.isFinite(node)) throw new TypeError("Non-finite number in canonical JSON");
    return JSON.stringify(node);
  }
  if (typeof node === "string") return JSON.stringify(node);
  if (Array.isArray(node)) return `[${node.map(canonicalJson).join(",")}]`;
  if (typeof node === "object") {
    const record = node as Record<string, unknown>;
    const sortedKeys = Object.keys(record).sort();
    return `{${sortedKeys.map((key) => `${JSON.stringify(key)}:${canonicalJson(record[key])}`).join(",")}}`;
  }
  throw new TypeError(`Unsupported canonical JSON type: ${typeof node}`);
}

function sha256Hex(text: string): string {
  return createHash("sha256").update(text).digest("hex");
}

/** The shared receipt canonical domain (Astra r5 item 3): receipts carry only strings, booleans, null, lists and
 * objects. Out-of-domain scalars (any number, even 1e-7 whose Python/JS canonical spellings differ - 1e-07 vs
 * 1e-7; integral 1e21, 1e+21 vs 1e21) are refused before hashing, in both languages, so a Python-validated receipt
 * can never hash differently from the Worker's.
 */
function receiptDomain(node: unknown, path: string): void {
  if (node === null || typeof node === "string" || typeof node === "boolean") return;
  if (typeof node === "number") throw new Error(`RECEIPT_OUT_OF_DOMAIN_SCALAR ${path}`);
  if (Array.isArray(node)) { node.forEach((v, i) => receiptDomain(v, `${path}[${i}]`)); return; }
  if (typeof node === "object") {
    for (const k of Object.keys(node as Record<string, unknown>)) receiptDomain((node as Record<string, unknown>)[k], `${path}.${k}`);
    return;
  }
  throw new Error(`RECEIPT_UNSUPPORTED_TYPE ${path}`);
}

export function computeReceiptDigest(receipt: any): string {
  if (!isObject(receipt)) return "";
  receiptDomain(receipt, "receipt");
  const withoutDigest: Record<string, unknown> = {};
  for (const k of Object.keys(receipt).sort()) {
    if (k !== "digest") withoutDigest[k] = receipt[k];
  }
  return sha256Hex(canonicalJson(withoutDigest));
}

// BATCH10C F8-AMEND1: the persisted form of a later-document id (scripts/revenue_guidance.py persisted_document_id,
// PERSISTED_DOCUMENT_ID_RE): <shown>#sha256:<64 lowercase hex> with no "@", "?" or "#" in <shown>. It is a safe id.
const PERSISTED_DOCUMENT_ID_RE = /^[^@?#]*#sha256:[0-9a-f]{64}$/;

// The Python transform: an id with "@", "?" or "#" that is not yet the persisted form becomes <shown>#sha256:<SHA-256
// of the exact original>, <shown> cut before its first "?" or "#" and after its last "@", at most 200 code points.
function persistedDocumentId(value: string): string {
  if (PERSISTED_DOCUMENT_ID_RE.test(value) || !/[@?#]/.test(value)) return value;
  const head = value.split(/[?#]/, 1)[0] ?? "";
  const shown = Array.from(head.slice(head.lastIndexOf("@") + 1)).slice(0, 200).join("");
  return `${shown}#sha256:${sha256Hex(value)}`;
}

function recomputeReceiptStatus(
  receipt: any,
  reviewedLater?: any[],
  cutoffDay?: string,
  guidancePublishedDate?: string,
  cutoffMs?: number,
  expectedCik?: number,
  expectedWireSymbol?: string,
  expectedIrHost?: string | null,
): string {
  if (!isObject(receipt)) return "FRESHNESS_UNVERIFIED";
  if (!onlyKeys(receipt, ["issuer", "checked_at", "status", "guidance_document_id", "guidance_published_date", "anchor_end", "coverage", "channels", "later_documents", "digest"], [])) {
    return "FRESHNESS_UNVERIFIED";
  }
  const channels = receipt?.channels;
  if (!Array.isArray(channels) || channels.length === 0) return "FRESHNESS_UNVERIFIED";
  const chkAt = typeof receipt.checked_at === "string" ? receipt.checked_at : "";
  const chkDay = chkAt.slice(0, 10);
  if (!claimDay(chkDay)) return "FRESHNESS_UNVERIFIED";
  const chkMs = instantMs(chkAt);
  if (chkMs === null || (cutoffMs !== undefined && chkMs > cutoffMs)) return "FRESHNESS_UNVERIFIED";

  const seenChannels = new Set<string>();
  for (const ch of channels) {
    if (!isObject(ch) || typeof ch.kind !== "string" || !VALID_V3_RECEIPT_CHANNELS.has(ch.kind) || seenChannels.has(ch.kind)) {
      return "FRESHNESS_UNVERIFIED";
    }
    if (!onlyKeys(ch, ["kind", "url", "status", "checked_through", "complete"], [])) return "FRESHNESS_UNVERIFIED";
    seenChannels.add(ch.kind);
    if (ch.status !== "OK" || ch.complete !== true || !claimDay(ch.checked_through)) {
      return "FRESHNESS_UNVERIFIED";
    }
    // Coverage must reach check date! Fresh checked_at cannot refresh stale coverage
    if (ch.checked_through < chkDay) return "FRESHNESS_UNVERIFIED";
    if (cutoffDay && ch.checked_through > cutoffDay) return "FRESHNESS_UNVERIFIED";
    if (guidancePublishedDate && ch.checked_through < guidancePublishedDate) return "FRESHNESS_UNVERIFIED";
    const url = ch.url;
    if (typeof url !== "string" || !URL_RE.test(url)) return "FRESHNESS_UNVERIFIED";
    if (ch.kind === "SEC_SUBMISSIONS") {
      if (!/^https:\/\/data\.sec\.gov\/submissions\/CIK[0-9]{10}\.json$/.test(url)) return "FRESHNESS_UNVERIFIED";
      if (expectedCik !== undefined && !url.endsWith(`CIK${String(expectedCik).padStart(10, "0")}.json`)) return "FRESHNESS_UNVERIFIED";
    }
    if (ch.kind === "WIRE_PRESS_RELEASES") {
      if (!(url.startsWith("https://api.nasdaq.com/") || url.startsWith("https://www.nasdaq.com/"))) return "FRESHNESS_UNVERIFIED";
      const sym = expectedWireSymbol ?? (typeof receipt.issuer === "string" ? receipt.issuer : "");
      if (sym && !url.toLowerCase().includes(`symbol:${sym.toLowerCase()}`)) return "FRESHNESS_UNVERIFIED";
    }
    // The official IR channel (Astra W1 ruling): an https feed whose host is the registry-reviewed IR host, never a
    // third-party mirror.
    if (ch.kind === "ISSUER_IR") {
      if (!url.startsWith("https://")) return "FRESHNESS_UNVERIFIED";
      let host = "";
      try { host = new URL(url).host; } catch { return "FRESHNESS_UNVERIFIED"; }
      if (expectedIrHost && host !== expectedIrHost) return "FRESHNESS_UNVERIFIED";
    }
  }
  // The receipt must carry exactly the channel set its reviewed wiring requires: the classic two channels, plus the
  // official IR channel when the record carries one (a missing IR channel is "incomplete", never "no release").
  const requiredChannels = expectedIrHost ? new Set(["SEC_SUBMISSIONS", "WIRE_PRESS_RELEASES", "ISSUER_IR"]) : new Set(["SEC_SUBMISSIONS", "WIRE_PRESS_RELEASES"]);
  if (seenChannels.size !== requiredChannels.size || ![...requiredChannels].every(k => seenChannels.has(k))) return "FRESHNESS_UNVERIFIED";

  const reviewedIds = new Set<string>();
  if (Array.isArray(reviewedLater)) {
    for (const rld of reviewedLater) {
      if (isObject(rld) && rld.disposition === "REVIEWED_IRRELEVANT" && typeof rld.id === "string") {
        if (!rld.reviewed_at || typeof rld.reviewed_at !== "string") continue; // review time is required!
        const rAt = instantMs(rld.reviewed_at);
        if (rAt === null) continue;
        if (cutoffMs !== undefined && rAt > cutoffMs) continue; // exact millisecond comparison!
        if (cutoffDay && rld.reviewed_at.slice(0, 10) > cutoffDay) continue;
        reviewedIds.add(rld.id);
        // BATCH10C F8-AMEND1: the checker writes and matches ids in the persisted form, so a reviewed raw id links it.
        reviewedIds.add(persistedDocumentId(rld.id));
      }
    }
  }

  const laterDocs = Array.isArray(receipt?.later_documents) ? receipt.later_documents : [];
  if (receipt?.later_documents !== undefined && !Array.isArray(receipt?.later_documents)) {
    return "FRESHNESS_UNVERIFIED";
  }

  let hasResultsRelease = false;
  let hasUnreviewedPossiblyRelevant = false;

  for (const ldoc of laterDocs) {
    if (!isObject(ldoc)) return "FRESHNESS_UNVERIFIED";
    if (!onlyKeys(ldoc, ["channel", "date", "id", "label", "disposition"], [])) return "FRESHNESS_UNVERIFIED";
    if (typeof ldoc.channel !== "string" || !VALID_V3_RECEIPT_CHANNELS.has(ldoc.channel)) return "FRESHNESS_UNVERIFIED";
    if (!claimDay(ldoc.date) || (cutoffDay && ldoc.date > cutoffDay)) return "FRESHNESS_UNVERIFIED";
    const lid = String(ldoc.id ?? "");
    if (!cleanText(lid, 400)) return "FRESHNESS_UNVERIFIED";
    // BATCH10C F8-N1: the Python raw-unsafe-id rule (scripts/revenue_guidance.py raw_unsafe_document_id), fail closed: a
    // non-string id, or one with userinfo ("@"), a query ("?") or a fragment ("#"), is never a freshness proof, unless
    // it is the persisted form, which is a safe id (F8-AMEND1).
    if (typeof ldoc.id !== "string" || (/[@?#]/.test(lid) && !PERSISTED_DOCUMENT_ID_RE.test(lid))) return "FRESHNESS_UNVERIFIED";
    const disp = ldoc.disposition;
    if (typeof disp !== "string" || !VALID_V3_LATER_DISPOSITIONS.has(disp)) return "FRESHNESS_UNVERIFIED";

    if (disp === "RESULTS_RELEASE") {
      hasResultsRelease = true;
    } else if (disp === "POSSIBLY_RELEVANT") {
      if (!reviewedIds.has(lid)) {
        hasUnreviewedPossiblyRelevant = true;
      }
    } else if (disp === "REVIEWED_IRRELEVANT") {
      if (!reviewedIds.has(lid)) {
        return "FRESHNESS_UNVERIFIED"; // Unlinked review cannot be accepted!
      }
    }
  }

  if (hasResultsRelease) return "RESULTS_PUBLISHED";
  if (hasUnreviewedPossiblyRelevant) return "REVIEW_REQUIRED";
  return "OK";
}

function validateModelPoint(claim: any): { point: number; derivation: string } {
  need(isObject(claim), "V3_CLAIM_NOT_OBJECT");
  const mult = claim.unit_multiplier;
  need(typeof mult === "number" && Number.isInteger(mult) && [1, 1000, 1000000, 1000000000].includes(mult), "V3_MULTIPLIER");

  // Reject boolean/non-number on all numeric fields if present
  for (const k of ["low", "high", "stated_point", "amount", "plus_minus_amount", "plus_minus_percent"]) {
    if (claim[k] !== undefined && claim[k] !== null) {
      need(typeof claim[k] === "number" && Number.isFinite(claim[k]), `V3_INVALID_NUMERIC_FIELD_${k}`);
    }
  }

  need(claim.original_representation !== "GREATER_THAN" && claim.original_representation !== "LESS_THAN", "V3_ONE_SIDED_GUIDANCE");
  if (typeof claim.original_representation === "string") {
    need(!claim.original_representation.toLowerCase().includes("greater than") && !claim.original_representation.toLowerCase().includes("less than"), "V3_ONE_SIDED_GUIDANCE_TEXT");
  }

  const low = claim.low !== undefined && claim.low !== null ? claim.low * mult : null;
  const high = claim.high !== undefined && claim.high !== null ? claim.high * mult : null;
  const stated = claim.stated_point !== undefined && claim.stated_point !== null ? claim.stated_point * mult : null;
  const pmAmount = claim.plus_minus_amount !== undefined && claim.plus_minus_amount !== null ? claim.plus_minus_amount * mult : null;
  const pmPct = claim.plus_minus_percent !== undefined && claim.plus_minus_percent !== null ? claim.plus_minus_percent : null;

  if (pmAmount !== null) {
    need(pmAmount >= 0, "V3_NEGATIVE_PLUS_MINUS_AMOUNT");
    need(stated !== null && stated >= 0, "V3_PLUS_MINUS_REQUIRES_STATED");
    const st = stated as number;
    need(st - pmAmount >= 0, "V3_PLUS_MINUS_AMOUNT_BOUNDS");
    if (low !== null) need(closeV3(low, st - pmAmount), "V3_PLUS_MINUS_LOW_MISMATCH");
    if (high !== null) need(closeV3(high, st + pmAmount), "V3_PLUS_MINUS_HIGH_MISMATCH");
    return { point: st, derivation: "STATED_POINT" };
  }

  if (pmPct !== null) {
    need(pmPct >= 0, "V3_NEGATIVE_PLUS_MINUS_PERCENT");
    need(stated !== null && stated >= 0, "V3_PLUS_MINUS_PERCENT_REQUIRES_STATED");
    const st = stated as number;
    const lowBound = st * (1.0 - pmPct / 100.0);
    const highBound = st * (1.0 + pmPct / 100.0);
    need(lowBound >= 0, "V3_PLUS_MINUS_PCT_BOUNDS");
    if (low !== null) need(closeV3(low, lowBound), "V3_PLUS_MINUS_PCT_LOW_MISMATCH");
    if (high !== null) need(closeV3(high, highBound), "V3_PLUS_MINUS_PCT_HIGH_MISMATCH");
    return { point: st, derivation: "STATED_POINT" };
  }

  if (low !== null && high !== null) {
    need(low >= 0 && high >= 0 && low <= high, "V3_RANGE");
    if (stated !== null) {
      need(stated >= low && stated <= high, "V3_STATED_POINT_RANGE");
      return { point: stated, derivation: "STATED_POINT" };
    }
    return { point: (low + high) / 2, derivation: "MIDPOINT" };
  }
  if (stated !== null) {
    need(stated >= 0, "V3_STATED_POINT_NONNEG");
    return { point: stated, derivation: "POINT_ONLY" };
  }
  if (claim.amount !== undefined && claim.amount !== null) {
    const amt = claim.amount * mult;
    need(amt >= 0, "V3_AMOUNT_NONNEG");
    return { point: amt, derivation: "POINT_ONLY" };
  }
  need(false, "V3_UNQUANTIFIED_CLAIM");
  return { point: 0, derivation: "" };
}

const VALID_V3_REVISIONS = new Set<string>([
  "SUPERSEDED", "WITHDRAWN", "WITHDRAWAL", "CORRECTION", "REAFFIRMATION"
]);

const REASONS_V3 = new Set<string>([
  "NOT_DISCLOSED", "INPUTS_MISSING", "STALE", "WITHDRAWN", "CONFLICTING_DISCLOSURES",
  "INVALID", "NO_REVENUE_HISTORY", "NO_REVENUE_BASIS", "FRESHNESS_UNVERIFIED",
  "SAMPLE_INSUFFICIENT", "PERIOD_MISMATCH", "EVIDENCE_LIMIT"
]);

// ===== Astra r5: shared version-3 evidence validation (items 4/5/6/7/8/9/10/11/12/13/15/20) =====
// The unavailable outcome is derived from the fully validated inputs, never trusted from a sealed early return:
// every evidence field below is validated BEFORE the sealed status is read, on every branch.

/** Bounded allowlisted projection (item 20): the sealed object's own field sets; unknown keys (including a forged
 * multi-megabyte field) are refused, never passed through into the outer Top20 object. */
const V3_TOP_KEYS = ["version", "issuer", "formula", "status", "reason", "revenue_status", "revenue_basis", "revenue_reason",
  "revenue_diagnostic", "horizon_convention", "anchor_date", "cutoff", "m6", "m12", "reported_quarters", "baseline_b",
  "forward_quarters", "warning", "contracted_recognition", "stock_sensitivity", "order_view", "references", "assumptions", "evidence"];
const V3_TOP_REQUIRED = ["version", "issuer", "formula", "horizon_convention", "status", "revenue_status",
  "revenue_basis", "anchor_date", "cutoff", "m6", "m12", "evidence"];
const V3_TOP_OPTIONAL = ["reason", "revenue_reason", "revenue_diagnostic", "reported_quarters", "baseline_b", "forward_quarters",
  "warning", "contracted_recognition", "stock_sensitivity", "order_view", "references", "assumptions"];
const V3_EV_KEYS = ["revenue_registry_status", "revenue_registry_sha256", "cutoff", "formula", "horizon_convention",
  "url_prefixes", "documents", "claims", "reported_quarters", "forward_intervals", "fy_reconciliation",
  "latest_release_check", "reviewed_later_documents", "consensus", "order_evidence", "release_channels",
  "consensus_fault", "release_check_fault"];
const V3_EV_REQUIRED = ["revenue_registry_status", "cutoff", "formula", "documents", "claims", "reported_quarters",
  "forward_intervals", "latest_release_check"];
const V3_EV_OPTIONAL = ["revenue_registry_sha256", "horizon_convention", "url_prefixes", "fy_reconciliation",
  "reviewed_later_documents", "consensus", "order_evidence", "release_channels", "consensus_fault", "release_check_fault",
  "consensus_enabled", "approval_sha256", "approval_approved_at", "approval_decisions"];
const V3_DOC_KEYS = ["id", "issuer", "publisher", "title", "source_kind", "url", "published_date", "published_at",
  "retrieved_at", "sha256", "byte_size", "lineage_id"];
const V3_CLAIM_KEYS = ["id", "document_id", "locator", "passage", "quote", "metric", "assertion_kind", "currency",
  "unit_multiplier", "amount", "low", "high", "stated_point", "plus_minus_amount", "plus_minus_percent",
  "original_representation", "scope", "scope_label", "fiscal_label", "period_kind", "period_start", "period_end",
  "start", "end", "accounting_basis", "reaffirmed_by", "corroborated_by", "revision", "checked_at"];
const V3_ACTUAL_KEYS = ["fiscal_label", "start", "end", "revenue", "currency", "scope", "accounting_basis",
  "document_id", "locator", "derivation"];
const V3_DOC_REQUIRED = ["id", "issuer", "publisher", "title", "source_kind", "url", "published_date", "retrieved_at",
  "sha256", "byte_size", "lineage_id"];
const V3_DOC_OPTIONAL = ["published_at"];
const V3_CLAIM_REQUIRED = ["id", "document_id", "metric", "assertion_kind", "accounting_basis", "currency", "locator",
  "original_representation", "fiscal_label"];
const V3_CLAIM_OPTIONAL = ["passage", "quote", "amount", "low", "high", "stated_point", "plus_minus_amount",
  "plus_minus_percent", "unit_multiplier", "scope", "scope_label", "period_kind", "period_start", "period_end",
  "start", "end", "reaffirmed_by", "corroborated_by", "revision", "checked_at"];
const V3_ACTUAL_REQUIRED = ["start", "end", "revenue", "currency", "scope", "accounting_basis", "document_id", "locator"];
const V3_ACTUAL_OPTIONAL = ["fiscal_label", "derivation"];
const V3_FAULT_MARKERS = new Set(["CONSENSUS_CACHE_LOAD_FAILED", "RELEASE_CHECK_CACHE_LOAD_FAILED"]);

/** The scoped evidence-limit result (items 5 and 20): a small, consistent unavailable object. The oversized
 * originals never travel sealed, so one limited issuer can no longer wipe the whole Top20 document. */
function v3EvidenceLimitResult(issuer: string): OrderForecast {
  const tile = (reason: string): ForecastHorizon => ({ status: "UNAVAILABLE", reason: "EVIDENCE_LIMIT" as ForecastReason,
    scenario: { status: "NO_BASIS", reason: reason === "EVIDENCE_LIMIT" ? "NO_REVENUE_BASIS" : "NO_ORDER_BASIS" } });
  return { ...normalized(3, tile("EVIDENCE_LIMIT"), tile("EVIDENCE_LIMIT")), issuer,
    revenueStatus: "UNAVAILABLE", revenueBasis: null, revenueReason: "EVIDENCE_LIMIT" };
}

interface V3EvidenceCheck {
  limit: boolean;
  docMap: Map<string, any>;
  claims: any[];
  eligibleActive: any[];          // scope-eligible, non-superseded claims (array order preserved for determinism checks)
  activeQuarter: any[];
  activeFy: any[];
  hasWithdrawn: boolean;
  conflict: boolean;              // two active quarter claims on the same canonical period
  actuals: any[];
  intervals: any[];
  receipt: any | null;
  recStatus: string | null;       // recomputed receipt status
  irCoverageMissing: boolean;     // the company-guidance path is suspended: no reviewed IR channel, or no SEC_WIRE_IR receipt
  consensus: any | null;
  currency: string | null;
  lowSample: boolean;
  staleEvidence: boolean;
  periodMismatch: boolean;
  // A4 r7: the scoped evidence-limit envelope (the revenue originals cleared, the bounded v2 order view kept so the
  // independently validated recognition re-derives), and the A1 reviewed profile sealed beside the record evidence.
  scopedLimit: boolean;
  hasRecordEvidence: boolean;
  approvalSealed: boolean;
  machineAdmitted: boolean;
}

const V3_DECISION_KINDS = new Set(["CLAIM", "ACTUAL", "CALENDAR", "FY_RECONCILIATION", "REAFFIRMATION", "ROUTING"]);
const V3_DECISION_VALUES = new Set(["VERBATIM_IN_SOURCE", "VALUE_IN_SOURCE", "DERIVATION_OPERANDS_IN_SOURCE", "RULE_QUOTED",
  "NONDISCLOSURE_CONFIRMED"]);

/** The record's single currency: reported actuals, then claims, then the consensus capture (all must agree). */
function v3ValidatedCurrency(ev: any, actuals: any[], claims: any[]): string | null {
  if (actuals.length > 0 && typeof actuals[0].currency === "string") return actuals[0].currency;
  if (claims.length > 0 && typeof claims[0].currency === "string") return claims[0].currency;
  if (isObject(ev.consensus) && typeof ev.consensus.currency === "string") return ev.consensus.currency;
  return null;
}

/** A claim's review instant (item 4/12): when sealed, a valid instant no earlier than the claim document's
 * retrieval and no later than the cutoff. */
function v3ClaimCheckedAt(c: any, doc: any, cutoffMs: number): void {
  if (c.checked_at === undefined || c.checked_at === null) return;
  const chk = instantMs(c.checked_at);
  need(chk !== null, "V3_CLAIM_CHECKED_AT_MALFORMED");
  need(chk! <= cutoffMs, "V3_CLAIM_CHECKED_AT_FUTURE");
  const retMs = doc ? instantMs(doc.retrieved_at) : null;
  if (retMs !== null) need(chk! >= retMs, "V3_CLAIM_REVIEW_BEFORE_RETRIEVAL");
}

function checkV3Evidence(value: any, ev: any, issuer: string, reportDay: string, cutoffMs: number,
  machine?: MachineAdmissionContext): V3EvidenceCheck {
  if (machine) need(machineContextIsValid(machine), "V3_MACHINE_CONTEXT");
  need(onlyKeys(value, V3_TOP_REQUIRED, V3_TOP_OPTIONAL), "V3_TOP_KEYS");
  need(onlyKeys(ev, V3_EV_REQUIRED, machine ? [...V3_EV_OPTIONAL, "auto_update"] : V3_EV_OPTIONAL), "V3_EV_KEYS");
  // Typed scoped channel-fault markers (item 9): a malformed/missing cache is a channel fault, never equated with a
  // genuine empty/nondisclosed success; the marker travels sealed so the scoped failure is re-derived here.
  for (const marker of [ev.consensus_fault, ev.release_check_fault]) {
    if (marker !== undefined && marker !== null) need(typeof marker === "string" && V3_FAULT_MARKERS.has(marker), "V3_FAULT_MARKER");
  }
  if (ev.release_channels !== undefined && ev.release_channels !== null) {
    const rc = ev.release_channels;
    need(isObject(rc) && (
      (rc.sec_cik === undefined || (Number.isInteger(rc.sec_cik) && rc.sec_cik > 0))
      && (rc.wire_symbol === undefined || (typeof rc.wire_symbol === "string" && rc.wire_symbol.length > 0 && rc.wire_symbol.length <= 40))
      && (rc.wire_names === undefined || (Array.isArray(rc.wire_names) && rc.wire_names.length <= 8
        && rc.wire_names.every((n: any) => typeof n === "string" && n.length <= 120)))
      // The official IR channel (Astra W1 ruling, astra-ir-coverage): a reviewed feed kind and its https base
      // (<=400 chars), with the reviewed guidance-release title (<=200) required alongside it.
      && (rc.ir === undefined || rc.ir === null || (isObject(rc.ir)
        && (rc.ir.kind === "Q4_PRESS_RELEASES" || rc.ir.kind === "RSS" || rc.ir.kind === "NEWSROOM_HTML")
        && typeof rc.ir.url === "string" && rc.ir.url.startsWith("https://") && rc.ir.url.length > 8 && rc.ir.url.length <= 400))
      && (rc.ir === undefined || rc.ir === null || typeof rc.ir_guidance_release_title === "string"
        && rc.ir_guidance_release_title.length > 0 && rc.ir_guidance_release_title.length <= 200)), "V3_RELEASE_CHANNELS");
  }

  // URL prefixes (both branches)
  const prefixes = Array.isArray(ev.url_prefixes) ? ev.url_prefixes : [];
  need(prefixes.length <= 8 && prefixes.every((p: any) => typeof p === "string" && PREFIX_RE.test(p)), "V3_PREFIXES");

  // Documents: bounded, allowlisted, complete provenance (item 4), end-of-day date-only rule (item 12).
  const docs = Array.isArray(ev.documents) ? ev.documents : [];
  if (docs.length > MAX_V3_DOCUMENTS) return { ...v3EvidenceLimitShape(), limit: true };
  const docMap = new Map<string, any>();
  for (const d of docs) {
    need(isObject(d) && onlyKeys(d, V3_DOC_REQUIRED, V3_DOC_OPTIONAL), "V3_DOC_KEYS");
    need(d.issuer === issuer, "V3_DOC_ISSUER");
    need(typeof d.publisher === "string" && d.publisher.trim().length > 0 && d.publisher.length <= 160, "V3_DOC_PUBLISHER");
    need(typeof d.title === "string" && d.title.trim().length > 0 && d.title.length <= 240, "V3_DOC_TITLE");
    need(V3_SOURCE_KINDS.has(d.source_kind), "V3_DOC_KIND");
    need(urlOk(d.url, prefixes), "V3_DOC_URL");
    if (d.source_kind === "SEC_PERIODIC" || d.source_kind === "SEC_8K_EXHIBIT" || d.source_kind === "SEC_6K_EXHIBIT") {
      need(typeof d.url === "string" && d.url.startsWith("https://www.sec.gov/Archives/edgar/data/"), "V3_SEC_URL");
    }
    need(claimDay(d.published_date) && instantMs(d.retrieved_at) !== null, "V3_DOC_DATES");
    need(d.published_date <= d.retrieved_at.slice(0, 10), "V3_DOC_TIME_COHERENCE");
    need(typeof d.sha256 === "string" && /^[0-9a-f]{64}$/.test(d.sha256), "V3_DOC_SHA");
    need(typeof d.byte_size === "number" && d.byte_size > 0 && d.byte_size <= MAX_V3_DOC_BYTES, "V3_DOC_SIZE");
    need(typeof d.lineage_id === "string" && d.lineage_id.length > 0 && d.lineage_id.length <= 80, "V3_DOC_LINEAGE");
    const retMs = instantMs(d.retrieved_at)!;
    need(retMs <= cutoffMs, "V3_DOC_RETRIEVED_CUTOFF");
    const pubMs = d.published_at ? instantMs(d.published_at) : null;
    if (pubMs !== null) {
      need(pubMs <= cutoffMs && pubMs <= retMs, "V3_DOC_PUBLISHED_CUTOFF");
      need(String(new Date(pubMs).toISOString()).slice(0, 10) === d.published_date, "V3_DOC_PUB_INSTANT_DATE");
    } else {
      // Date-only publication: only eligible after the end of that UTC day (item 12), never "<= reportDay".
      need(d.published_date < reportDay, "V3_DATE_ONLY_CUTOFF");
    }
    need(!docMap.has(d.id), "V3_DUP_DOC_ID");
    docMap.set(d.id, d);
  }

  // Claims: bounded, allowlisted, with the review instant and a full revision graph (items 4/11/12).
  const claims = Array.isArray(ev.claims) ? ev.claims : [];
  if (claims.length > MAX_V3_CLAIMS) return { ...v3EvidenceLimitShape(), limit: true };
  const claimIds = new Set<string>();
  for (const c of claims) {
    need(isObject(c) && onlyKeys(c, V3_CLAIM_REQUIRED, V3_CLAIM_OPTIONAL), "V3_CLAIM_KEYS");
    if (typeof c.id === "string") claimIds.add(c.id);
  }
  for (const c of claims) {
    need(docMap.has(c.document_id), "V3_CLAIM_DOC");
    need(c.metric === "REVENUE" && c.assertion_kind === "COMPANY_GUIDANCE", "V3_CLAIM_METRIC");
    if (c.accounting_basis !== undefined) need(ACCOUNTING_BASES_V3.has(c.accounting_basis), "V3_CLAIM_BASIS");
    if (typeof c.currency === "string") need(CURRENCIES.has(c.currency), "V3_CLAIM_CURRENCY");
    const quote = c.passage ?? c.quote;
    need(typeof quote === "string" && quote.trim().length > 0 && quote.length <= MAX_V3_PASSAGE, "V3_CLAIM_QUOTE");
    need(typeof c.locator === "string" && c.locator.trim().length > 0 && c.locator.length <= 160, "V3_CLAIM_LOCATOR");
    need(typeof c.original_representation === "string" && c.original_representation.trim().length > 0, "V3_CLAIM_ORIG_REP");
    // Representation parity (item 14): a PLUS_MINUS representation needs its sealed operand, like the Python reader.
    if (c.original_representation === "PLUS_MINUS_PERCENT" && c.plus_minus_percent === undefined) need(false, "V3_CLAIM_PM_PCT_OPERAND");
    if (c.original_representation === "PLUS_MINUS_AMOUNT" && c.plus_minus_amount === undefined) need(false, "V3_CLAIM_PM_AMT_OPERAND");
    need(typeof c.fiscal_label === "string" && c.fiscal_label.trim().length > 0, "V3_CLAIM_FISCAL_LABEL");
    v3ClaimCheckedAt(c, docMap.get(c.document_id), cutoffMs);
    // A present revision must be a valid object with a known kind and known targets (item 11): a non-object shape
    // is malformed evidence, not an ignored one; a withdrawn claim is history, not a record failure.
    if (c.revision !== undefined && c.revision !== null) {
      need(isObject(c.revision) && onlyKeys(c.revision, ["kind"], ["targets", "supersedes", "reason"]), "V3_REVISION_SHAPE");
      need(VALID_V3_REVISIONS.has(c.revision.kind), "V3_INVALID_REVISION_KIND");
      if (Array.isArray(c.revision.targets)) {
        for (const t of c.revision.targets) need(typeof t === "string" && claimIds.has(t), "V3_ORPHAN_REVISION_TARGET");
      }
      if (typeof c.revision.supersedes === "string") need(claimIds.has(c.revision.supersedes), "V3_ORPHAN_REVISION_SUPERSEDES");
    }
  }

  // Eligibility (scope, retrieval/publication, 200-day age) and the superseded/withdrawn split.
  let eligibleActive: any[] = [];
  for (const c of claims) {
    if (c.scope !== "COMPANY" && c.scope !== "CONSOLIDATED") continue;
    const doc = docMap.get(c.document_id);
    if (!doc) continue;
    const retMs = instantMs(doc.retrieved_at)!;
    if (retMs > cutoffMs) continue;
    const pubMs = doc.published_at ? instantMs(doc.published_at) : null;
    if (pubMs !== null) {
      if (pubMs > cutoffMs || pubMs > retMs) continue;
    } else if (doc.published_date >= reportDay) continue; // end-of-day rule
    const ageDays = days(doc.published_date, reportDay);
    if (ageDays < 0 || ageDays > 200) continue;
    eligibleActive.push(c);
  }
  const hasWithdrawn = eligibleActive.some(c => isObject(c.revision) && (c.revision.kind === "WITHDRAWN" || c.revision.kind === "WITHDRAWAL"));
  const supersededIds = new Set<string>();
  for (const c of eligibleActive) {
    const rev = c.revision;
    if (rev && isObject(rev)) {
      if (rev.kind === "SUPERSEDED" || rev.kind === "WITHDRAWN" || rev.kind === "WITHDRAWAL") supersededIds.add(String(c.id));
      if (Array.isArray(rev.targets)) rev.targets.forEach((t: string) => supersededIds.add(t));
      if (typeof rev.supersedes === "string") supersededIds.add(rev.supersedes);
    }
  }
  const active = eligibleActive.filter(c => !supersededIds.has(String(c.id)));
  const activeQuarter = active.filter(c => c.period_kind === "QUARTER");
  const activeFy = active.filter(c => c.period_kind === "FISCAL_YEAR");
  // Canonical-period conflict (item 11): any two active quarter claims on the same period.
  const qPeriods = activeQuarter.map(c => `${c.period_start ?? c.start}|${c.period_end ?? c.end}`);
  const conflict = new Set(qPeriods).size < qPeriods.length;

  // Reported actuals: bounded, allowlisted, contiguous, basis/currency consistent, derivation-validated.
  const actuals = Array.isArray(ev.reported_quarters) ? ev.reported_quarters : [];
  if (actuals.length > MAX_V3_ACTUALS) return { ...v3EvidenceLimitShape(), limit: true };
  let primaryActualBasis: string | null = null;
  for (let i = 0; i < actuals.length; i++) {
    const q = actuals[i];
    need(isObject(q) && onlyKeys(q, V3_ACTUAL_REQUIRED, V3_ACTUAL_OPTIONAL), `V3_ACTUAL_KEYS_${i}`);
    need(claimDay(q.start) && claimDay(q.end) && q.start <= q.end, `V3_ACTUAL_DATES_${i}`);
    need(typeof q.revenue === "number" && Number.isFinite(q.revenue) && q.revenue >= 0, `V3_ACTUAL_REV_${i}`);
    need(ACCOUNTING_BASES_V3.has(q.accounting_basis), `V3_ACTUAL_BASIS_${i}`);
    if (primaryActualBasis === null) primaryActualBasis = q.accounting_basis;
    else need(q.accounting_basis === primaryActualBasis, `V3_ACTUAL_BASIS_INCONSISTENCY_${i}`);
    need(typeof q.currency === "string" && CURRENCIES.has(q.currency), `V3_ACTUAL_CURRENCY_${i}`);
    need(q.scope === "COMPANY" || q.scope === "CONSOLIDATED", `V3_ACTUAL_SCOPE_${i}`);
    need(typeof q.document_id === "string" && docMap.has(q.document_id), `V3_ACTUAL_DOC_UNKNOWN_${i}`);
    need(typeof q.locator === "string" && q.locator.trim().length > 0, `V3_ACTUAL_LOCATOR_${i}`);
    if (typeof q.fiscal_label === "string") need(q.fiscal_label.length <= 120, `V3_ACTUAL_FISCAL_LABEL_${i}`);
    // A sealed YTD derivation (e.g. Q4 = FY - 9M) must recompute, mirroring scripts/revenue_guidance.py exactly:
    // kind YTD_DIFFERENCE, both document ids known, finite values, and longer - shorter == revenue.
    if (q.derivation !== undefined && q.derivation !== null) {
      const dv = q.derivation;
      need(isObject(dv) && dv.kind === "YTD_DIFFERENCE", `V3_ACTUAL_DERIVATION_${i}`);
      need(docMap.has(dv.longer_document_id) && docMap.has(dv.shorter_document_id), `V3_ACTUAL_DERIVATION_DOCS_${i}`);
      need(typeof dv.longer_value === "number" && Number.isFinite(dv.longer_value)
        && typeof dv.shorter_value === "number" && Number.isFinite(dv.shorter_value), `V3_ACTUAL_DERIVATION_VALUES_${i}`);
      need(closeV3(dv.longer_value - dv.shorter_value, q.revenue), `V3_ACTUAL_DERIVATION_${i}`);
    }
    if (i > 0) need(q.start === dayAfter(actuals[i - 1].end), `V3_ACTUAL_CONTIGUOUS_${i}`);
  }
  // The top-level duplicate copy must be the validated actuals, not a second, divergent record (item 6).
  if (value.reported_quarters !== undefined && value.reported_quarters !== null) {
    need(Array.isArray(value.reported_quarters) && same(value.reported_quarters, actuals), "V3_TOP_ACTUALS_MISMATCH");
  }

  // Forward intervals: exactly 4, contiguous, anchored, and each bound to a calendar document and locator
  // (item 10: calendar links on every branch, not only guidance).
  const intervals = Array.isArray(ev.forward_intervals) ? ev.forward_intervals : value.forward_quarters;
  // A Top20 issuer without a reviewed registry record seals no revenue evidence at all (build_v3: INPUTS_MISSING):
  // only that exact empty shape may carry no intervals; any partial record still needs its four sealed intervals.
  const noRecord = Array.isArray(ev.documents) && ev.documents.length === 0 && Array.isArray(ev.claims) && ev.claims.length === 0
    && actuals.length === 0 && Array.isArray(intervals) && intervals.length === 0
    && (value.forward_quarters === undefined || (Array.isArray(value.forward_quarters) && value.forward_quarters.length === 0))
    && (ev.release_channels ?? null) === null && (ev.latest_release_check ?? null) === null && (ev.consensus ?? null) === null
    && (ev.fy_reconciliation ?? null) === null && (ev.revenue_registry_status === "OK" || machine?.kind === "BARRIER")
    && value.revenue_status === "UNAVAILABLE" && (value.revenue_reason === "INPUTS_MISSING" ||
      (machine?.kind === "BARRIER" && value.revenue_reason === machine.barrierReason));
  // A4 r7: the scoped evidence-limit envelope - the oversized revenue originals were cleared by the sealer, but the
  // bounded v2 order view stays sealed so the independently validated sibling recognition (e.g. NVDA m12 USD
  // 1,248,000,000) re-derives as exactly that scoped state, never INVALID and never a wiped entry.
  const scopedLimit = value.revenue_status === "UNAVAILABLE" && value.revenue_reason === "EVIDENCE_LIMIT"
    && docs.length === 0 && claims.length === 0 && actuals.length === 0
    && (value.forward_quarters === undefined || (Array.isArray(value.forward_quarters) && value.forward_quarters.length === 0))
    && (ev.latest_release_check ?? null) === null && (ev.consensus ?? null) === null
    && (ev.fy_reconciliation ?? null) === null && (ev.release_channels ?? null) === null
    && (ev.reviewed_later_documents ?? null) === null && isObject(ev.order_evidence);
  need(Array.isArray(intervals) && (intervals.length === 4 || noRecord || scopedLimit), "V3_FW_INTERVALS");
  for (let i = 0; i < intervals.length; i++) {
    const intv = intervals[i];
    need(isObject(intv) && claimDay(intv.start) && claimDay(intv.end) && intv.start <= intv.end, `V3_INTV_DATES_${i}`);
    if (i > 0) need(intv.start === dayAfter(intervals[i - 1].end), `V3_INTV_CONTIGUOUS_${i}`);
    need(typeof intv.calendar_document_id === "string" && docMap.has(intv.calendar_document_id), `V3_INTV_CALENDAR_DOC_${i}`);
    need(typeof intv.calendar_locator === "string" && intv.calendar_locator.trim().length > 0 && intv.calendar_locator.length <= MAX_V3_PASSAGE,
      `V3_INTV_CALENDAR_LOCATOR_${i}`);
  }

  // The record's single currency.
  const currency = v3ValidatedCurrency(ev, actuals, claims);

  // The release-check receipt (whenever sealed): digest, channels, later documents, recomputed status, and the
  // reviewed channel identity (item 2: the SEC feed must be the issuer's own CIK, the wire feed its own symbol;
  // Astra W1: the official IR feed must be the registry-reviewed IR host).
  let receipt: any = null;
  let recStatus: string | null = null;
  const rc = ev.release_channels;
  // The record's reviewed official IR channel: kind + https base (shape validated above). When present, the
  // receipt must bind it (an ISSUER_IR channel on that host) and carry the SEC_WIRE_IR coverage; without a
  // reviewed IR channel the company-guidance path is suspended with the distinct IR_COVERAGE_MISSING diagnostic
  // (never NOT_DISCLOSED, zero or consensus), while order recognition stays independent.
  const irSpec = rc && isObject(rc) && isObject(rc.ir)
    && (rc.ir.kind === "Q4_PRESS_RELEASES" || rc.ir.kind === "RSS" || rc.ir.kind === "NEWSROOM_HTML")
    && typeof rc.ir.url === "string" ? rc.ir : null;
  let irHost: string | null = null;
  if (irSpec) {
    try { irHost = new URL(irSpec.url).host; } catch { irHost = null; }
  }
  if (ev.latest_release_check !== undefined && ev.latest_release_check !== null) {
    receipt = ev.latest_release_check;
    need(isObject(receipt) && Array.isArray(receipt.channels) && receipt.channels.length > 0, "V3_RECEIPT_RUNTIME_ONLY");
    const chkMs = instantMs(receipt.checked_at);
    need(chkMs !== null && chkMs <= cutoffMs, "V3_RECEIPT_TIME");
    const ageHours = (cutoffMs - chkMs!) / (3600 * 1000);
    need(ageHours >= 0 && ageHours <= 24, "V3_RECEIPT_AGE_24H");
    need(receipt.issuer === issuer, "V3_RECEIPT_ISSUER");
    // A receipt without a reviewed IR channel must not claim the SEC_WIRE_IR label (its IR channel host is
    // unreviewed): that wiring is invalid evidence. The reverse (a reviewed IR channel with the label not yet
    // upgraded to SEC_WIRE_IR) is not invalid evidence - it is the distinct IR_COVERAGE_MISSING suspension,
    // derived below, exactly like the Python caller (coverage check before the recompute).
    need(!(irSpec === null && receipt.coverage !== "SEC_AND_WIRE"), "V3_RECEIPT_COVERAGE");
    need(typeof receipt.digest === "string" && receipt.digest === computeReceiptDigest(receipt), "V3_RECEIPT_DIGEST");
    recStatus = recomputeReceiptStatus(receipt, ev.reviewed_later_documents, reportDay, undefined, cutoffMs,
      rc && Number.isInteger(rc.sec_cik) ? rc.sec_cik : undefined,
      rc && typeof rc.wire_symbol === "string" ? rc.wire_symbol : undefined,
      irSpec ? irHost : undefined);
    recStatus = machineEffectiveReceipt(machine, receipt, recStatus); // same unchanged raw classifier, separate accounted freshness
  }
  if (machine?.kind === "BARRIER" && machine.barrierReason === "FRESHNESS_UNVERIFIED") recStatus = "FRESHNESS_UNVERIFIED";
  // Missing/uncovered official IR coverage suspends the company-guidance revenue path (Astra W1 ruling): it applies
  // only where a company-guidance path was actually attempted (an active guidance claim) - a NOT_DISCLOSED or
  // consensus record carries no such path and never the IR diagnostic. A record without any reviewed IR wiring
  // suspends outright; a record with the wiring suspends until the receipt upgrades to SEC_WIRE_IR.
  const irCoverageMissing = (activeQuarter.length > 0 || activeFy.length > 0)
    ? (irSpec === null
      ? true
      : (receipt === null || receipt.coverage !== "SEC_WIRE_IR"))
    : false;

  // The consensus capture (whenever sealed): full metadata validation (item 15).
  let consensus: any = null;
  let lowSample = false;
  let consensusStale = false;
  if (ev.consensus !== undefined && ev.consensus !== null) {
    consensus = ev.consensus;
    need(isObject(consensus) && consensus.symbol === issuer, "V3_CONSENSUS_SYMBOL");
    need(typeof consensus.currency === "string" && CURRENCIES.has(consensus.currency), "V3_CONSENSUS_CURRENCY");
    if (currency !== null) need(consensus.currency === currency, "V3_CONSENSUS_CURRENCY_MIX");
    need(consensus.scope === undefined || consensus.scope === null || consensus.scope === "CONSOLIDATED" || consensus.scope === "COMPANY",
      "V3_CONSENSUS_SCOPE");
    if (consensus.source_url !== undefined && consensus.source_url !== null) {
      need(typeof consensus.source_url === "string" && /^https:\/\//.test(consensus.source_url) && consensus.source_url.length <= 400, "V3_CONSENSUS_URL");
    }
    const capTime = consensus.captured_at ?? consensus.retrieved_at;
    const capMs = instantMs(capTime);
    need(capMs !== null && capMs <= cutoffMs, "V3_CONSENSUS_TIME");
    consensusStale = (cutoffMs - capMs!) / (3600 * 1000) > 24;
    need(Array.isArray(consensus.quarters) && consensus.quarters.length >= 1 && consensus.quarters.length <= 2, "V3_CONSENSUS_QUARTERS");
    const q1 = consensus.quarters[0];
    // An explicit null first quarter is malformed evidence, never an absence (item 15).
    need(isObject(q1), "V3_CONSENSUS_Q1_MALFORMED");
    need(q1.end === intervals[0].end, "V3_CONSENSUS_Q1_END");
    need(q1.period === "0q" || q1.period === "Q1" || q1.period === "QUARTER", "V3_CONSENSUS_Q1_PERIOD");
    need(q1.scope === undefined || q1.scope === "CONSOLIDATED" || q1.scope === "COMPANY", "V3_CONSENSUS_Q1_SCOPE");
    if (q1.currency !== undefined && q1.currency !== null) need(q1.currency === consensus.currency, "V3_CONSENSUS_Q1_CURRENCY");
    // An explicit resolved start must be the interval's start (a 2020 start beside a 2026 interval is a mismatch).
    if (q1.start !== undefined && q1.start !== null) need(q1.start === intervals[0].start, "V3_CONSENSUS_Q1_START");
    need(typeof q1.analysts === "number" && Number.isInteger(q1.analysts) && q1.analysts >= 3, "V3_CONSENSUS_Q1_ANALYSTS");
    const q1Rev = typeof q1.revenue === "number" ? q1.revenue : q1.avg;
    need(typeof q1Rev === "number" && Number.isFinite(q1Rev) && q1Rev >= 0, "V3_CONSENSUS_Q1_REV");
    if (consensus.quarters.length > 1) {
      const q2 = consensus.quarters[1];
      // An explicit null second quarter is malformed evidence, never an absence (item 15).
      need(q2 !== null, "V3_CONSENSUS_Q2_NULL");
      need(isObject(q2), "V3_CONSENSUS_Q2_MALFORMED");
      need(q2.end === intervals[1].end, "V3_CONSENSUS_Q2_END");
      need(q2.period === undefined || q2.period === "+1q" || q2.period === "Q2" || q2.period === "QUARTER", "V3_CONSENSUS_Q2_PERIOD");
      need(q2.scope === undefined || q2.scope === "CONSOLIDATED" || q2.scope === "COMPANY", "V3_CONSENSUS_Q2_SCOPE");
      if (q2.currency !== undefined && q2.currency !== null) need(q2.currency === consensus.currency, "V3_CONSENSUS_Q2_CURRENCY");
      if (q2.start !== undefined && q2.start !== null) need(q2.start === intervals[1].start, "V3_CONSENSUS_Q2_START");
      const q2Rev = typeof q2.revenue === "number" ? q2.revenue : q2.avg;
      need(typeof q2Rev === "number" && Number.isFinite(q2Rev) && q2Rev >= 0, "V3_CONSENSUS_Q2_REV");
      need(typeof q2.analysts === "number" && Number.isInteger(q2.analysts) && q2.analysts >= 0, "V3_CONSENSUS_Q2_ANALYSTS");
      lowSample = q2.analysts < 3;
    }
  }

  // FY reconciliation (whenever sealed): the zero current-FY year-to-date is the degenerate zero-day span with zero
  // revenue and no quarter ends (item 13); any non-empty end list keeps the original rules.
  const fyRec = ev.fy_reconciliation;
  if (fyRec !== undefined && fyRec !== null) {
    need(isObject(fyRec), "V3_FY_REC_OBJECT");
    need(claimDay(fyRec.ytd_start) && claimDay(fyRec.ytd_end) && fyRec.ytd_start <= fyRec.ytd_end, "V3_FY_YTD_DATES");
    need(typeof fyRec.ytd_revenue === "number" && Number.isFinite(fyRec.ytd_revenue) && fyRec.ytd_revenue >= 0, "V3_FY_YTD_REV");
    need(Array.isArray(fyRec.ytd_quarter_ends), "V3_FY_Q_ENDS");
    if (fyRec.ytd_quarter_ends.length === 0) {
      need(fyRec.ytd_start === fyRec.ytd_end && fyRec.ytd_revenue === 0, "V3_FY_ZERO_YTD_DEGENERATE");
    } else {
      for (const qe of fyRec.ytd_quarter_ends) need(claimDay(qe) && qe >= fyRec.ytd_start && qe <= fyRec.ytd_end, "V3_FY_Q_END_RANGE");
    }
  }

  // Reviewed later documents (receipt reviews): bounded, typed, at or before the cutoff.
  const reviewed = Array.isArray(ev.reviewed_later_documents) ? ev.reviewed_later_documents : [];
  need(reviewed.length <= 16, "V3_REVIEWED_BOUNDS");
  for (const rld of reviewed) {
    need(isObject(rld) && rld.disposition === "REVIEWED_IRRELEVANT" && typeof rld.id === "string", "V3_REVIEWED_SHAPE");
    const rAt = instantMs(rld.reviewed_at);
    need(rAt !== null && rAt <= cutoffMs, "V3_REVIEWED_TIME");
  }

  // Staleness signals the unavailable state machine re-derives (item 8): a results release / review-required
  // receipt, an expired consensus capture, or guidance older than the 200-day bound.
  const guidanceStale = eligibleActive.length === 0 && claims.some((c: any) => {
    const doc = docMap.get(c.document_id);
    if (!doc) return false;
    const age = days(doc.published_date, reportDay);
    return age > 200;
  });
  const staleEvidence = (recStatus === "RESULTS_PUBLISHED" || recStatus === "REVIEW_REQUIRED" || consensusStale || guidanceStale
    || (machine?.kind === "BARRIER" && machine.barrierReason === "STALE"));

  // A3/A6 (Astra acceptance r7): the registry's explicit consensus gate travels sealed. While it is false the
  // Korean consensus route is deferred for this rollout: a sealed CONSENSUS basis is invalid, and the deferred
  // diagnostic never appears beside a gate that is on.
  need(ev.consensus_enabled === undefined || typeof ev.consensus_enabled === "boolean", "V3_CONSENSUS_GATE_SHAPE");
  if (ev.consensus_enabled === false && value.revenue_basis === "CONSENSUS") need(false, "V3_CONSENSUS_BASIS_GATE_OFF");
  if (ev.consensus_enabled === true && value.revenue_diagnostic === "CONSENSUS_DEFERRED") need(false, "V3_DEFERRED_GATE_ON");

  // A1 (Astra acceptance r7): the enforced reviewed profile seals beside the record evidence - the approval file's
  // sha256, its approved_at and this record's bounded review decisions. Present exactly when the profile admitted
  // the record; null exactly when it did not (the UNREVIEWED_INPUTS failure), which the unavailable state machine
  // re-derives below. The empty (noRecord) and scoped-limit envelopes seal explicit nulls.
  const approvalSealed = typeof ev.approval_sha256 === "string" && ev.approval_approved_at != null && ev.approval_decisions != null;
  const hasRecordEvidence = !noRecord && !scopedLimit;
  const machineAdmitted = machine?.kind === "AUTO";
  if (machineAdmitted) {
    need(ev.approval_sha256 === null && ev.approval_approved_at === null && ev.approval_decisions === null,
      "V3_MACHINE_HUMAN_APPROVAL_NULL");
  } else if (hasRecordEvidence && approvalSealed) {
    need(typeof ev.approval_sha256 === "string" && /^[0-9a-f]{64}$/.test(ev.approval_sha256), "V3_APPROVAL_SHA");
    const approvedMs = instantMs(ev.approval_approved_at);
    need(approvedMs !== null && approvedMs <= cutoffMs, "V3_APPROVAL_TIME");
    const decisions = ev.approval_decisions;
    need(Array.isArray(decisions) && decisions.length > 0 && decisions.length <= 32, "V3_APPROVAL_DECISIONS_BOUNDS");
    for (const dec of decisions) {
      need(isObject(dec) && V3_DECISION_KINDS.has(dec.kind) && V3_DECISION_VALUES.has(dec.decision)
        && typeof dec.ref === "string" && dec.ref.length > 0 && dec.ref.length <= 120, "V3_APPROVAL_DECISION_SHAPE");
      const reviewedMs = instantMs(dec.reviewed_at);
      need(reviewedMs !== null && reviewedMs <= cutoffMs, "V3_APPROVAL_DECISION_TIME");
    }
  } else if (hasRecordEvidence) {
    // The record's inputs are sealed but the profile did not admit them: the only coherent sealed state is the
    // unreviewed failure with explicit null approval fields.
    need(ev.approval_sha256 == null && ev.approval_approved_at == null && ev.approval_decisions == null
      && value.revenue_diagnostic === "UNREVIEWED_INPUTS" && value.revenue_reason === "INVALID", "V3_APPROVAL_MISSING");
  } else {
    need(ev.approval_sha256 == null && ev.approval_approved_at == null && ev.approval_decisions == null, "V3_APPROVAL_NULLS");
  }

  return {
    limit: false, docMap, claims, eligibleActive, activeQuarter, activeFy, hasWithdrawn, conflict,
    actuals, intervals, receipt, recStatus, irCoverageMissing, consensus, currency, lowSample, staleEvidence, periodMismatch: false,
    scopedLimit, hasRecordEvidence, approvalSealed, machineAdmitted,
  };
}

/** The empty shape every scoped limit result spreads (kept separate so the limit object stays tiny). */
function v3EvidenceLimitShape(): Omit<V3EvidenceCheck, "limit"> {
  return { docMap: new Map(), claims: [], eligibleActive: [], activeQuarter: [], activeFy: [], hasWithdrawn: false,
    conflict: false, actuals: [], intervals: [], receipt: null, recStatus: null, irCoverageMissing: false, consensus: null, currency: null,
    lowSample: false, staleEvidence: false, periodMismatch: false, scopedLimit: false, hasRecordEvidence: true, approvalSealed: false, machineAdmitted: false };
}

function parseV3(value: any, reportDay: string, issuer: string, generatedAt: string | undefined, outerV2?: unknown,
  machine?: MachineAdmissionContext): OrderForecast {
  const invalid = normalized(3, unavailable("INVALID"), unavailable("INVALID"));
  try {
    need(isObject(value) && value.version === 3 && value.issuer === issuer, "V3_HEADER");
    need(value.formula === "ORDERS-V3-01" && value.horizon_convention === "FISCAL_2Q_4Q", "V3_CONVENTION");
    const ev = value.evidence;
    need(isObject(ev), "V3_EVIDENCE");
    need(typeof generatedAt === "string" && ev.cutoff === generatedAt && instantMs(ev.cutoff) !== null, "V3_CUTOFF");
    need(ev.cutoff.slice(0, 10) === reportDay, "V3_REPORT_DAY");
    const cutoffMs = instantMs(ev.cutoff)!;

    // Strict structural check on evidence arrays BEFORE checking unavailable/available status
    need(Array.isArray(ev.documents), "V3_EV_DOCUMENTS_ARRAY");
    need(Array.isArray(ev.claims), "V3_EV_CLAIMS_ARRAY");
    need(Array.isArray(ev.reported_quarters), "V3_EV_ACTUALS_ARRAY");
    need(Array.isArray(ev.url_prefixes), "V3_EV_PREFIXES_ARRAY");

    // 1. Validate the order linkage: when the sealed v2 subtree (order_evidence) is present it must be the
    //    same evidence as the sibling v2 and must recompute through parseV2; a v3 without an order linkage
    //    carries an unavailable order view and must not assert any contracted recognition.
    let validatedOrder: OrderForecast;
    const rec = value.contracted_recognition;
    if (outerV2 && isObject(outerV2)) {
      const v2Any = outerV2 as any;
      if (v2Any.evidence !== null && v2Any.evidence !== undefined) {
        need(isObject(ev.order_evidence), "V3_ORDER_EV_MISSING_DESPITE_SIBLING");
        need(same(ev.order_evidence, v2Any.evidence), "V3_ORDER_EV_MISMATCH");
      }
      need(same(value.stock_sensitivity ?? null, v2Any.stock_sensitivity ?? null), "V3_STOCK_SENSITIVITY_MISMATCH");
    }

    if (isObject(ev.order_evidence)) {
      const orderEnv = outerV2 && isObject(outerV2) ? outerV2 : {
        version: 2,
        issuer,
        status: value.order_view?.status ?? (value.contracted_recognition ? "AVAILABLE" : "UNAVAILABLE"),
        reason: value.order_view?.reason ?? null,
        m6: value.order_view?.m6 ?? unavailable("NOT_DISCLOSED_HORIZON"),
        m12: value.order_view?.m12 ?? unavailable("NOT_DISCLOSED_HORIZON"),
        stock_sensitivity: value.stock_sensitivity ?? null,
        references: value.references ?? [],
        evidence: ev.order_evidence,
      };
      validatedOrder = parseV2(orderEnv, reportDay, issuer, generatedAt);
      need(validatedOrder.m6.reason !== "INVALID" && validatedOrder.m12.reason !== "INVALID", "V3_ORDER_INVALID");

      if (value.order_view !== undefined && value.order_view !== null) {
        need(isObject(value.order_view), "V3_ORDER_VIEW_OBJECT");
        // The normalized v2 view carries no top-level status/reason; derive them the way the sealer does
        // (scripts/order_forecast.py: status from the horizons, reason from topReason).
        const expectedOrderStatus = validatedOrder.m6.status === "AVAILABLE" || validatedOrder.m12.status === "AVAILABLE" ? "AVAILABLE" : "UNAVAILABLE";
        const expectedOrderReason = topReason(validatedOrder.m6, validatedOrder.m12);
        need(value.order_view.status === expectedOrderStatus, "V3_ORDER_VIEW_STATUS");
        need(value.order_view.reason === expectedOrderReason, "V3_ORDER_VIEW_REASON");
        // The sealed order view must equal the validated v2 tiles field by field (Astra r5 item 7): every field the
        // expected tile carries - amounts, dates, currency, scenario, warning, recognition - with no extras.
        // When the sibling v2 is present the expected tile is the sibling's sealed tile, not the normalized one.
        const compareTile = (sealed: any, expected: any, which: "m6" | "m12") => {
          need(isObject(sealed), `V3_ORDER_VIEW_${which.toUpperCase()}_OBJECT`);
          for (const key of Object.keys(expected)) {
            const ev = (expected as any)[key];
            const sv = sealed[key];
            if (typeof ev === "number") {
              need(typeof sv === "number" && closeV3(sv, ev), `V3_ORDER_VIEW_${which.toUpperCase()}_${key.toUpperCase()}`);
            } else if (ev !== null && typeof ev === "object") {
              // Nested objects (scenario, warning, contracted_recognition, quarter_derivation, lineage) compare deeply.
              need(same(sv ?? null, ev), `V3_ORDER_VIEW_${which.toUpperCase()}_${key.toUpperCase()}`);
            } else if (ev === null) {
              need(sv === null || sv === undefined, `V3_ORDER_VIEW_${which.toUpperCase()}_${key.toUpperCase()}`);
            } else if (ev === undefined) {
              need(sv === undefined, `V3_ORDER_VIEW_${which.toUpperCase()}_${key.toUpperCase()}`);
            } else {
              need(sv === ev, `V3_ORDER_VIEW_${which.toUpperCase()}_${key.toUpperCase()}`);
            }
          }
          const allowed = new Set([...Object.keys(expected), "scenario", "warning", "contracted_recognition"]);
          need(Object.keys(sealed).every(k => allowed.has(k)), `V3_ORDER_VIEW_${which.toUpperCase()}_EXTRA_KEYS`);
        };
        const v2Source = outerV2 && isObject(outerV2) ? (outerV2 as any) : validatedOrder;
        compareTile(value.order_view.m6, v2Source.m6, "m6");
        compareTile(value.order_view.m12, v2Source.m12, "m12");
      } else if (isObject(ev.order_evidence) || (outerV2 && isObject(outerV2) && (outerV2 as any).evidence)) {
        // The sealer always seals the order view beside an order linkage (item 7); its absence is a contract break.
        need(false, "V3_ORDER_VIEW_MISSING");
      }
    } else {
      if (rec && isObject(rec)) need(false, "V3_REC_WITHOUT_ORDER_EVIDENCE");
      validatedOrder = { ...normalized(2, unavailable("NOT_DISCLOSED_HORIZON"), unavailable("NOT_DISCLOSED_HORIZON")), cutoff: ev.cutoff };
    }

    const hasOrderM6Rec = validatedOrder.m6.status === "AVAILABLE" && validatedOrder.m6.basis === "RECOGNITION";
    const hasOrderM12Rec = validatedOrder.m12.status === "AVAILABLE" && validatedOrder.m12.basis === "RECOGNITION";

    if (hasOrderM6Rec || hasOrderM12Rec) {
      need(rec !== null && rec !== undefined && isObject(rec), "V3_RECOGNITION_OMITTED_DESPITE_SIBLING");
    }
    if (rec !== null && rec !== undefined) {
      need(isObject(rec), "V3_REC_NOT_OBJECT");
      need(onlyKeys(rec, ["m6", "m12"], []), "V3_REC_KEYS");
      if (rec.m6 !== null && rec.m6 !== undefined) {
        need(isObject(rec.m6), "V3_REC_M6_NOT_OBJECT");
        // The sealer always seals all seven recognition fields; a partial tile (amount only) is a contract break.
        need(onlyKeys(rec.m6, ["amount", "currency", "start", "end", "as_of", "share_pct", "rpo"],
          ["amount", "currency", "start", "end", "as_of", "share_pct", "rpo"]), "V3_REC_M6_KEYS");
        need(hasOrderM6Rec, "V3_FORGED_M6_REC");
        need(closeV3(rec.m6.amount, validatedOrder.m6.amount), "V3_FORGED_M6_REC_AMT");
        need(rec.m6.start === validatedOrder.m6.start && rec.m6.end === validatedOrder.m6.end, "V3_FORGED_M6_REC_DATES");
        need(rec.m6.currency === validatedOrder.m6.currency, "V3_FORGED_M6_REC_CURRENCY");
        if (rec.m6.rpo !== undefined) need(closeV3(rec.m6.rpo, validatedOrder.m6.rpo), "V3_FORGED_M6_REC_RPO");
        if (rec.m6.share_pct !== undefined) need(closeV3(rec.m6.share_pct, validatedOrder.m6.share_pct), "V3_FORGED_M6_REC_SHARE");
        if (rec.m6.as_of !== undefined) need(rec.m6.as_of === validatedOrder.m6.as_of, "V3_FORGED_M6_REC_AS_OF");
      }
      if (rec.m12 !== null && rec.m12 !== undefined) {
        need(isObject(rec.m12), "V3_REC_M12_NOT_OBJECT");
        need(onlyKeys(rec.m12, ["amount", "currency", "start", "end", "as_of", "share_pct", "rpo"],
          ["amount", "currency", "start", "end", "as_of", "share_pct", "rpo"]), "V3_REC_M12_KEYS");
        need(hasOrderM12Rec, "V3_FORGED_M12_REC");
        need(closeV3(rec.m12.amount, validatedOrder.m12.amount), "V3_FORGED_M12_REC_AMT");
        need(rec.m12.start === validatedOrder.m12.start && rec.m12.end === validatedOrder.m12.end, "V3_FORGED_M12_REC_DATES");
        need(rec.m12.currency === validatedOrder.m12.currency, "V3_FORGED_M12_REC_CURRENCY");
        if (rec.m12.rpo !== undefined) need(closeV3(rec.m12.rpo, validatedOrder.m12.rpo), "V3_FORGED_M12_REC_RPO");
        if (rec.m12.share_pct !== undefined) need(closeV3(rec.m12.share_pct, validatedOrder.m12.share_pct), "V3_FORGED_M12_REC_SHARE");
        if (rec.m12.as_of !== undefined) need(rec.m12.as_of === validatedOrder.m12.as_of, "V3_FORGED_M12_REC_AS_OF");
      }
    }

    // The sealed recognition tiles carry only the fields that are present (undefined keys are omitted, exactly like
    // the sealer's JSON), so the normalized tiles must omit them too for the deep comparison to hold.
    const recTileOf = (h: any) => ({
      amount: h.amount,
      currency: h.currency,
      start: h.start,
      end: h.end,
      ...(h.rpo !== undefined ? { rpo: h.rpo } : {}),
      ...(h.share_pct !== undefined ? { share_pct: h.share_pct } : {}),
      ...(h.as_of !== undefined ? { as_of: h.as_of } : {}),
    });
    const normRec = (hasOrderM6Rec || hasOrderM12Rec) ? {
      m6: hasOrderM6Rec ? recTileOf(validatedOrder.m6) : null,
      m12: hasOrderM12Rec ? recTileOf(validatedOrder.m12) : null,
    } : null;

    // 2. Validate revenue status and reasons
    const revStatus = value.revenue_status;
    const revReason = value.revenue_reason ?? null;
    need(revStatus === "AVAILABLE" || revStatus === "UNAVAILABLE", "V3_REV_STATUS");
    if (revReason !== null) need(REASONS_V3.has(revReason), "V3_REV_REASON");

    // (Astra r5 items 8/9) the unavailable outcome is derived from the fully validated inputs, never trusted from a
    // sealed early return: every evidence field was validated above the sealed status, on every branch.
    const evc = checkV3Evidence(value, ev, issuer, reportDay, cutoffMs, machine);
    if (evc.limit && !evc.scopedLimit) return v3EvidenceLimitResult(issuer);

    // If overall status is UNAVAILABLE:
    if (value.status === "UNAVAILABLE") {
      need(revStatus === "UNAVAILABLE", "V3_CONTRADICTORY_AVAILABLE");
      need(value.m6.status === "UNAVAILABLE" && value.m12.status === "UNAVAILABLE", "V3_UNAVAILABLE_TILES_STATUS");
      // The single state machine: the sealed reason must be what the validated routing inputs derive.
      let expectedReason: ForecastReason = (revReason as ForecastReason) ?? "NOT_DISCLOSED";
      if (ev.revenue_registry_status === "INVALID") expectedReason = "INVALID";
      else if (ev.revenue_registry_status === "EMPTY" || ev.revenue_registry_status === "UNAVAILABLE") expectedReason = "INPUTS_MISSING";
      // A1 (Astra acceptance r7): the record's inputs seal without the reviewed profile's admission - the A1
      // admission boundary overrides the routing inputs, and the reason is INVALID, never the routed outcome.
      if (machine?.kind === "BARRIER") expectedReason = (machine.scoped ? "EVIDENCE_LIMIT" : machine.barrierReason!) as ForecastReason;
      if (evc.hasRecordEvidence && !evc.approvalSealed && !evc.machineAdmitted) expectedReason = "INVALID";
      // An enum is not proof of the reason (items 8/9): each sealed reason must be backed by the validated evidence.
      if (expectedReason === "NOT_DISCLOSED") {
        need(evc.activeQuarter.length === 0 && evc.activeFy.length === 0, "V3_NOT_DISCLOSED_DESPITE_CLAIMS");
      } else if (expectedReason === "WITHDRAWN") {
        need(evc.hasWithdrawn, "V3_WITHDRAWN_UNBACKED");
        need(evc.activeQuarter.length === 0 && evc.activeFy.length === 0, "V3_WITHDRAWN_DESPITE_ACTIVE");
      } else if (expectedReason === "STALE") {
        need(evc.staleEvidence, "V3_STALE_UNBACKED");
      } else if (expectedReason === "FRESHNESS_UNVERIFIED") {
        // The receipt recompute is unverified, or the company-guidance path is suspended for missing official-IR
        // coverage (Astra W1 ruling): the sealed reason must be backed by one of the two, and by the diagnostic.
        need(evc.recStatus === "FRESHNESS_UNVERIFIED" || evc.irCoverageMissing, "V3_FRESHNESS_UNVERIFIED_UNBACKED");
      } else if (expectedReason === "SAMPLE_INSUFFICIENT") {
        need(evc.lowSample, "V3_SAMPLE_INSUFFICIENT_UNBACKED");
      } else if (expectedReason === "CONFLICTING_DISCLOSURES") {
        need(evc.conflict, "V3_CONFLICT_UNBACKED");
      } else if (expectedReason === "PERIOD_MISMATCH") {
        const qc = evc.activeQuarter[0];
        need(qc !== undefined && ((qc.period_start ?? qc.start) !== evc.intervals[0]!.start
          || (qc.period_end ?? qc.end) !== evc.intervals[0]!.end), "V3_PERIOD_MISMATCH_UNBACKED");
      } else if (expectedReason === "EVIDENCE_LIMIT") {
        // A4 r7: the scoped limit state stands on its own (the cleared revenue envelope plus the kept order view).
        need(evc.scopedLimit, "V3_EVIDENCE_LIMIT_UNBACKED");
      } else if (expectedReason !== "INVALID" && expectedReason !== "INPUTS_MISSING" && expectedReason !== "NO_REVENUE_HISTORY"
        && expectedReason !== "NO_REVENUE_BASIS") {
        need(false, "V3_REASON_UNBACKED"); // the rest is not a revenue reason
      }
      // Recognition-only outcome (item 8): a valid contracted recognition is never suppressed by the revenue state.
      if (hasOrderM6Rec) need(value.m6.status === "AVAILABLE" && value.m6.basis === "RECOGNITION", "V3_REC_SUPPRESSED_M6");
      if (hasOrderM12Rec) need(value.m12.status === "AVAILABLE" && value.m12.basis === "RECOGNITION", "V3_REC_SUPPRESSED_M12");
      if (!hasOrderM6Rec) need(value.m6.reason === expectedReason, "V3_TILE_REASON_MISMATCH");
      if (!hasOrderM12Rec) need(value.m12.reason === expectedReason, "V3_TILE_REASON_MISMATCH");
      need(value.reason === expectedReason, "V3_UNAVAILABLE_REASON_MISMATCH");
      // The distinct diagnostics (Astra W1 ruling; acceptance r7 A1/A3): each seals exactly in its own state - the
      // IR-coverage suspension, the unreviewed-inputs suspension and the deferred consensus route.
      const revDiag = value.revenue_diagnostic ?? null;
      need(revDiag === null || revDiag === "IR_COVERAGE_MISSING" || revDiag === "UNREVIEWED_INPUTS" || revDiag === "CONSENSUS_DEFERRED",
        "V3_DIAGNOSTIC_ENUM");
      // Same precedence as the producer: the reviewed-profile gate runs before any routing (build_v3), so an
      // unreviewed record seals no receipt and its diagnostic wins over the IR-coverage one derived from it.
      let expectedDiag: string | null = null;
      if (evc.hasRecordEvidence && !evc.approvalSealed && !evc.machineAdmitted) expectedDiag = "UNREVIEWED_INPUTS";
      else if (evc.irCoverageMissing) expectedDiag = "IR_COVERAGE_MISSING";
      else if (evc.hasRecordEvidence && ev.consensus_enabled === false && evc.consensus === null && expectedReason === "NOT_DISCLOSED")
        expectedDiag = "CONSENSUS_DEFERRED";
      need(revDiag === expectedDiag, "V3_DIAGNOSTIC_MISMATCH");
      // A5: the sealed record's actual provenance stays visible in the unavailable states (each used actual's
      // document and locator, the YTD block, the fiscal calendar source) - the deferred and unreviewed states
      // explain the revenue path without hiding the reviewed inputs behind them.
      const unavailSources: NonNullable<OrderForecast["revenueSources"]> = [];
      if (evc.hasRecordEvidence) {
        for (const q of evc.actuals.slice(0, 8)) {
          const qDoc = evc.docMap.get(q.document_id);
          unavailSources.push({
            role: "ACTUAL",
            quarter_end: q.end,
            document_id: q.document_id,
            locator: q.locator ? String(q.locator).slice(0, 120) : undefined,
            publisher: qDoc ? String(qDoc.publisher).slice(0, 80) : undefined,
            source_kind: qDoc?.source_kind,
            url: qDoc ? String(qDoc.url).slice(0, 160) : undefined,
            derivation: isObject(q.derivation)
              ? { longer_value: q.derivation.longer_value, shorter_value: q.derivation.shorter_value }
              : undefined,
          });
        }
        if (isObject(ev.fy_reconciliation)) {
          unavailSources.push({ role: "YTD", quarter_end: ev.fy_reconciliation.ytd_end, ytd_revenue: ev.fy_reconciliation.ytd_revenue });
        }
        if (evc.intervals.length > 0) {
          const calDoc = evc.docMap.get(evc.intervals[0].calendar_document_id);
          if (calDoc) {
            unavailSources.push({
              role: "CALENDAR",
              publisher: String(calDoc.publisher).slice(0, 80),
              source_kind: calDoc.source_kind,
              published_date: calDoc.published_date,
              locator: String(evc.intervals[0].calendar_locator ?? "").slice(0, 120),
              url: String(calDoc.url).slice(0, 160),
            });
          }
        }
      }
      return {
        ...normalized(3, unavailable(expectedReason), unavailable(expectedReason)),
        revenueStatus: "UNAVAILABLE",
        revenueBasis: null,
        revenueReason: revReason ?? expectedReason,
        revenueDiagnostic: revDiag,
        cutoff: ev.cutoff,
        sensitivity: validatedOrder.sensitivity,
        references: validatedOrder.references,
        supplements: validatedOrder.supplements,
        superseded: validatedOrder.superseded,
        registry24: validatedOrder.registry24,
        claims: validatedOrder.claims,
        currentStock: validatedOrder.currentStock,
        schedule: validatedOrder.schedule,
        revenueSources: unavailSources,
      };
    }

    need(value.status === "AVAILABLE", "V3_STATUS");
    need(isObject(value.m6) && isObject(value.m12), "V3_TILES");

    // If revenue is UNAVAILABLE, overall status AVAILABLE requires valid contracted recognition on Tile 2!
    if (revStatus === "UNAVAILABLE") {
      need(isObject(ev.order_evidence), "V3_REC_NO_ORDER_EV");
      const hasOrderM6Rec = validatedOrder.m6.status === "AVAILABLE" && validatedOrder.m6.basis === "RECOGNITION";
      const hasOrderM12Rec = validatedOrder.m12.status === "AVAILABLE" && validatedOrder.m12.basis === "RECOGNITION";
      need(hasOrderM6Rec || hasOrderM12Rec, "V3_NO_ORDER_REC");

      if (hasOrderM6Rec) {
        need(value.m6.status === "AVAILABLE" && value.m6.basis === "RECOGNITION", "V3_M6_REC_STATUS");
        need(closeV3(value.m6.amount, validatedOrder.m6.amount), "V3_M6_REC_AMT");
        need(value.m6.start === validatedOrder.m6.start && value.m6.end === validatedOrder.m6.end, "V3_M6_REC_DATES");
        need(value.m6.currency === validatedOrder.m6.currency, "V3_M6_REC_CURRENCY");
      } else {
        need(value.m6.status === "UNAVAILABLE", "V3_M6_REC_UNAVAILABLE");
      }

      if (hasOrderM12Rec) {
        need(value.m12.status === "AVAILABLE" && value.m12.basis === "RECOGNITION", "V3_M12_REC_STATUS");
        need(closeV3(value.m12.amount, validatedOrder.m12.amount), "V3_M12_REC_AMT");
        need(value.m12.start === validatedOrder.m12.start && value.m12.end === validatedOrder.m12.end, "V3_M12_REC_DATES");
        need(value.m12.currency === validatedOrder.m12.currency, "V3_M12_REC_CURRENCY");
      } else {
        need(value.m12.status === "UNAVAILABLE", "V3_M12_REC_UNAVAILABLE");
      }

      const normRecM6: ForecastHorizon = hasOrderM6Rec ? {
        status: "AVAILABLE",
        reason: undefined,
        basis: "RECOGNITION",
        basis_label: "已簽約預計認列",
        amount: validatedOrder.m6.amount,
        currency: validatedOrder.m6.currency,
        start: validatedOrder.m6.start,
        end: validatedOrder.m6.end,
        horizon_label: "半年",
        qualifier: `自${validatedOrder.m6.start}起，非今日起`,
        rpo: validatedOrder.m6.rpo,
        share_pct: validatedOrder.m6.share_pct,
        scenario: { status: "NO_BASIS", reason: "NO_REVENUE_BASIS" },
      } : unavailable((value.m6.reason as ForecastReason) ?? "NOT_DISCLOSED_HORIZON");

      const normRecM12: ForecastHorizon = hasOrderM12Rec ? {
        status: "AVAILABLE",
        reason: undefined,
        basis: "RECOGNITION",
        basis_label: "已簽約預計認列",
        amount: validatedOrder.m12.amount,
        currency: validatedOrder.m12.currency,
        start: validatedOrder.m12.start,
        end: validatedOrder.m12.end,
        horizon_label: "1年",
        qualifier: `自${validatedOrder.m12.start}起，非今日起`,
        rpo: validatedOrder.m12.rpo,
        share_pct: validatedOrder.m12.share_pct,
        scenario: { status: "NO_BASIS", reason: "NO_REVENUE_BASIS" },
      } : unavailable((value.m12.reason as ForecastReason) ?? "NOT_DISCLOSED_HORIZON");

      // Without a revenue projection a recognition horizon IS the tile (compared with normRecM6/M12 below); it never
      // carries a nested contracted_recognition copy (scripts/order_forecast.py build_v3 seals none on this branch),
      // so a nested copy here is refused rather than compared with the recognition (Astra r5 item 7; writer fix on
      // real data 2026-09-28: SNDK/AVGO, official-IR suspension beside a 12-month RPO schedule).
      need((value.m6.contracted_recognition ?? null) === null, "V3_M6_REC_TILE_MISMATCH");
      need((value.m12.contracted_recognition ?? null) === null, "V3_M12_REC_TILE_MISMATCH");

      // The distinct IR-coverage diagnostic (Astra W1 ruling), beside the independent order recognition:
      // sealed exactly when the company-guidance path is suspended for missing official-IR coverage.
      // Derived exactly as on the fully unavailable branch (acceptance r7 A1): the IR-coverage suspension, the
      // unreviewed-inputs suspension and the deferred consensus route can each sit beside a valid recognition.
      const revDiag = value.revenue_diagnostic ?? null;
      need(revDiag === null || revDiag === "IR_COVERAGE_MISSING" || revDiag === "UNREVIEWED_INPUTS" || revDiag === "CONSENSUS_DEFERRED",
        "V3_DIAGNOSTIC_ENUM");
      let expectedRecDiag: string | null = null;
      if (evc.hasRecordEvidence && !evc.approvalSealed && !evc.machineAdmitted) expectedRecDiag = "UNREVIEWED_INPUTS";
      else if (evc.irCoverageMissing) expectedRecDiag = "IR_COVERAGE_MISSING";
      else if (evc.hasRecordEvidence && ev.consensus_enabled === false && evc.consensus === null && revReason === "NOT_DISCLOSED")
        expectedRecDiag = "CONSENSUS_DEFERRED";
      need(revDiag === expectedRecDiag, "V3_DIAGNOSTIC_MISMATCH");

      return {
        version: 3,
        issuer,
        m6: normRecM6,
        m12: normRecM12,
        sensitivity: validatedOrder.sensitivity,
        references: validatedOrder.references,
        supplements: validatedOrder.supplements,
        superseded: validatedOrder.superseded,
        registry24: validatedOrder.registry24,
        registry: ev.revenue_registry_status ?? null,
        cutoff: ev.cutoff,
        claims: validatedOrder.claims,
        currentStock: validatedOrder.currentStock,
        schedule: validatedOrder.schedule,
        formula: value.formula,
        horizonConvention: value.horizon_convention,
        revenueStatus: "UNAVAILABLE",
        revenueBasis: null,
        revenueReason: revReason,
        revenueDiagnostic: revDiag,
        contractedRecognition: rec ?? null,
        assumptions: value.assumptions ?? null,
      };
    }

    // 3. Revenue is AVAILABLE: validate evidence completely and recompute! (the evidence itself was validated in
    // checkV3Evidence above: allowlisted fields, complete provenance, calendar links, receipts, consensus metadata.)
    need(value.revenue_basis === "COMPANY_GUIDANCE" || value.revenue_basis === "CONSENSUS", "V3_REVENUE_BASIS");
    need(value.m6.status === "AVAILABLE", "V3_M6_NOT_AVAILABLE");
    need(value.m12.status === "AVAILABLE", "V3_M12_NOT_AVAILABLE");
    need(value.m6.basis === value.revenue_basis, "V3_M6_BASIS_MISMATCH");
    need(value.m12.basis === value.revenue_basis, "V3_M12_BASIS_MISMATCH");
    need(value.cutoff === ev.cutoff, "V3_TOP_CUTOFF_MISMATCH");
    need(ev.revenue_registry_status === "OK", "V3_REGISTRY_STATUS");
    need(typeof ev.revenue_registry_sha256 === "string" && /^[0-9a-f]{64}$/.test(ev.revenue_registry_sha256), "V3_REGISTRY_SHA");
    need(value.formula === "ORDERS-V3-01", "V3_TOP_FORMULA");
    need(ev.formula === "ORDERS-V3-01", "V3_EV_FORMULA");
    // A WITHDRAWN (or any) revenue_reason beside available revenue is contradictory (item 6).
    need(revReason === null, "V3_REASON_DESPITE_AVAILABLE");
    // A suspended company-guidance path (missing official-IR coverage, Astra W1 ruling) can never produce available
    // revenue, and its distinct diagnostic never travels beside an available outcome.
    need(!evc.irCoverageMissing, "V3_IR_COVERAGE_MISSING_DESPITE_AVAILABLE");
    need((value.revenue_diagnostic ?? null) === null, "V3_DIAGNOSTIC_DESPITE_AVAILABLE");
    // A receipt that no longer recomputes OK (failed/failed-host channels, tampered status) cannot back available
    // revenue: the sealed AVAILABLE would trust a recompute the evidence contradicts (the IR host binding is part
    // of that recompute).
    need(evc.recStatus !== "FRESHNESS_UNVERIFIED", "V3_RECEIPT_UNVERIFIED_DESPITE_AVAILABLE");

    // Forward intervals: the validated set (exactly 4, contiguous, anchored, calendar-linked on every branch).
    const intervalObjs = evc.intervals;
    const docMap = evc.docMap;
    const actualObjs = evc.actuals;
    const validatedCurrency = evc.currency ?? "USD";

    // The record's single currency: reported actuals, then claims, then the consensus capture (all must agree).
    const currencies = new Set<string>([validatedCurrency]);
    for (const q of actualObjs) if (typeof q.currency === "string") currencies.add(q.currency);
    for (const c of evc.claims) if (typeof c.currency === "string") currencies.add(c.currency);
    if (typeof value.m6.currency === "string") currencies.add(value.m6.currency);
    if (typeof value.m12.currency === "string") currencies.add(value.m12.currency);
    need(currencies.size <= 1, "V3_CURRENCY_MIX");

    // Check the anchor date: the latest reported quarter end A when actuals are present, else the sealed anchor_date.
    const anchorDate = actualObjs.length > 0 ? actualObjs[actualObjs.length - 1].end : value.anchor_date;
    need(claimDay(anchorDate), "V3_ANCHOR_DATE");
    need(value.anchor_date === anchorDate, "V3_TOP_ANCHOR_MISMATCH");
    if (ev.anchor_date !== undefined) need(ev.anchor_date === anchorDate, "V3_EV_ANCHOR_MISMATCH");

    // Strict A-to-f1 adjacency!
    need(intervalObjs[0]!.start === dayAfter(anchorDate), "V3_ANCHOR_ADJACENT");
    need(actualObjs.every((a: any) => a.end <= anchorDate && a.start <= a.end), "V3_ACTUAL_NO_OVERLAP");

    let fAmounts = [0, 0, 0, 0];
    let derivations = ["", "", "", ""];
    let warning: any = null;
    let isFy = false;
    let amountsRecomputed = false;

    if (value.revenue_basis === "COMPANY_GUIDANCE") {
      // Claims were fully validated by checkV3Evidence (allowlist, provenance, the checked_at review instant, the
      // revision graph, scope/age eligibility): here we select the active set and re-derive the model only.
      const claims = evc.claims;
      need(claims.length > 0, "V3_CLAIMS_BOUNDS");
      need(evc.activeQuarter.length <= 1 && evc.activeFy.length <= 1, "V3_CONFLICTING_CLAIMS");
      const quarterClaim = evc.activeQuarter[0] ?? null;
      const fyClaim = evc.activeFy[0] ?? null;
      need(quarterClaim || fyClaim, "V3_NO_ACTIVE_GUIDANCE");

      if (quarterClaim) {
        const qStart = quarterClaim.period_start ?? quarterClaim.start;
        const qEnd = quarterClaim.period_end ?? quarterClaim.end;
        need(qStart === intervalObjs[0]!.start && qEnd === intervalObjs[0]!.end, "V3_QUARTER_INTERVAL_MATCH");
      }

      // Release-check receipt (item 2): the digest, the channel identity (the issuer's own CIK / wire symbol) and
      // the recomputed status were verified in checkV3Evidence; here the check is bound to the reference document.
      const receipt = evc.receipt;
      need(isObject(receipt), "V3_RECEIPT_REQUIRED");
      need(receipt.anchor_end === anchorDate, "V3_RECEIPT_ANCHOR");
      const activeClaim = quarterClaim ?? fyClaim;
      // The check starts from the claim's document or its latest reaffirmation (scripts/revenue_guidance.py
      // guidance_reference_document_id): a later reaffirmation without a restated figure moves the start date.
      let referenceDocId: string = activeClaim.document_id;
      let referenceDay: string = String(docMap.get(referenceDocId)?.published_date ?? "");
      for (const item of Array.isArray(activeClaim.reaffirmed_by) ? activeClaim.reaffirmed_by : []) {
        const doc = isObject(item) ? docMap.get(item.document_id) : undefined;
        if (doc !== undefined && String(doc.published_date ?? "") > referenceDay) {
          referenceDocId = item.document_id;
          referenceDay = String(doc.published_date);
        }
      }
      const activeDoc = docMap.get(referenceDocId);
      need(activeDoc !== undefined, "V3_RECEIPT_DOC");
      need(receipt.guidance_document_id === referenceDocId, "V3_RECEIPT_GUIDANCE_DOC_ID");
      need(receipt.guidance_published_date === activeDoc.published_date, "V3_RECEIPT_PUB_DATE");
      const rc = isObject(ev.release_channels) ? ev.release_channels : null;
      // The official IR host (Astra W1 ruling): when the record carries the reviewed IR wiring, the recompute binds
      // the ISSUER_IR channel to that host and requires it in the channel set.
      const irUrl = rc && isObject(rc.ir) && (rc.ir.kind === "Q4_PRESS_RELEASES" || rc.ir.kind === "RSS" || rc.ir.kind === "NEWSROOM_HTML")
        && typeof rc.ir.url === "string" ? rc.ir.url : null;
      let irHostBind: string | undefined;
      if (irUrl) { try { irHostBind = new URL(irUrl).host; } catch { irHostBind = undefined; } }
      const recomputedStatus = recomputeReceiptStatus(receipt, ev.reviewed_later_documents, reportDay, activeDoc.published_date, cutoffMs,
        rc && Number.isInteger(rc.sec_cik) ? rc.sec_cik : undefined,
        rc && typeof rc.wire_symbol === "string" ? rc.wire_symbol : undefined,
        irHostBind);
      const effectiveStatus = machineEffectiveReceipt(machine, receipt, recomputedStatus);
      need(machine ? effectiveStatus === "OK" : receipt.status === recomputedStatus && receipt.status === "OK", "V3_RECEIPT_STATUS_OK");

      // Derive forward amounts
      if (quarterClaim && !fyClaim) {
        const mp = validateModelPoint(quarterClaim);
        fAmounts = [mp.point, mp.point, mp.point, mp.point];
        derivations = ["公司財測", "模型：之後各季持平於公司財測", "模型：之後各季持平於公司財測", "模型：之後各季持平於公司財測"];
        amountsRecomputed = true;
      } else if (fyClaim && !quarterClaim) {
        const mp = validateModelPoint(fyClaim);
        const recObj = ev.fy_reconciliation;
        need(isObject(recObj) && recObj.fy_claim_id === fyClaim.id, "V3_FY_CLAIM_ID");
        // SAME Python exact zero-reported-YTD rollover; the WeakSet-created
        // context, not a payload flag, owns machine admission. All fiscal,
        // receipt, interval, residual and sealed-model checks still run below.
        const zeroYtdRollover = machineContextIsValid(machine) && machine.kind === "AUTO" && !machine.scoped
          && Array.isArray(recObj.ytd_quarter_ends) && recObj.ytd_quarter_ends.length === 0
          && typeof recObj.ytd_revenue === "number" && Number.isFinite(recObj.ytd_revenue) && recObj.ytd_revenue === 0
          && claimDay(fyClaim.period_start) && recObj.ytd_start === fyClaim.period_start
          && recObj.ytd_end === recObj.ytd_start && recObj.ytd_start === dayAfter(anchorDate)
          && actualObjs.length >= 4 && actualObjs.every((q: any) => q.end < recObj.ytd_start)
          && intervalObjs.length === 4 && intervalObjs[0].start === recObj.ytd_start
          && intervalObjs[3].end === (fyClaim.period_end ?? fyClaim.end);
        need(recObj.ytd_end === anchorDate || zeroYtdRollover, "V3_FY_YTD_END_MATCH");
        need(claimDay(recObj.ytd_start) && recObj.ytd_start <= recObj.ytd_end, "V3_FY_YTD_DATES");
        need(fyClaim.period_start === recObj.ytd_start, "V3_FY_YTD_START_MISMATCH");
        const fyEnd = fyClaim.period_end ?? fyClaim.end;
        const fySpanDays = days(fyClaim.period_start, fyEnd);
        need(fySpanDays >= 350 && fySpanDays <= 380, "V3_FY_SPAN_BOUNDS");
        need(Array.isArray(recObj.ytd_quarter_ends), "V3_FY_Q_ENDS");
        const matchingActuals = actualObjs.filter((q: any) => recObj.ytd_quarter_ends.includes(q.end));
        need(matchingActuals.length === recObj.ytd_quarter_ends.length, "V3_FY_ACTUALS_MATCH");
        if (matchingActuals.length > 0) {
          need(recObj.ytd_start === matchingActuals[0].start, "V3_FY_ACTUAL_START_MISMATCH");
        }
        const actSum = matchingActuals.reduce((sum: number, q: any) => sum + q.revenue, 0);
        need(closeV3(actSum, recObj.ytd_revenue), "V3_FY_YTD_REV_SUM");
        const n = 4 - recObj.ytd_quarter_ends.length;
        need(n >= 1 && n <= 4, "V3_FY_N_DERIVE");
        need(intervalObjs[n - 1].end === fyEnd, "V3_FY_INTERVAL_MATCH");

        let R = mp.point - recObj.ytd_revenue;
        need(R >= -1e-9, "V3_NEGATIVE_R");
        if (R < 0) R = 0;
        const qShare = R / n;
        for (let i = 0; i < n; i++) {
          fAmounts[i] = qShare;
          derivations[i] = "模型：全年財測扣已報營收，剩餘各季均分";
        }
        for (let i = n; i < 4; i++) {
          fAmounts[i] = qShare;
          derivations[i] = "模型：後續各季持平於財測推算末季";
        }
        isFy = true;
        amountsRecomputed = true;
      } else if (quarterClaim && fyClaim) {
        const gMp = validateModelPoint(quarterClaim);
        const fyMp = validateModelPoint(fyClaim);
        const recObj = ev.fy_reconciliation;
        need(isObject(recObj) && recObj.fy_claim_id === fyClaim.id, "V3_FY_CLAIM_ID");
        need(recObj.ytd_end === anchorDate, "V3_FY_YTD_END_MATCH");
        need(claimDay(recObj.ytd_start) && recObj.ytd_start <= recObj.ytd_end, "V3_FY_YTD_DATES");
        need(fyClaim.period_start === recObj.ytd_start, "V3_FY_YTD_START_MISMATCH");
        const fyEnd = fyClaim.period_end ?? fyClaim.end;
        const fySpanDays = days(fyClaim.period_start, fyEnd);
        need(fySpanDays >= 350 && fySpanDays <= 380, "V3_FY_SPAN_BOUNDS");
        need(Array.isArray(recObj.ytd_quarter_ends), "V3_FY_Q_ENDS");
        const matchingActuals = actualObjs.filter((q: any) => recObj.ytd_quarter_ends.includes(q.end));
        need(matchingActuals.length === recObj.ytd_quarter_ends.length, "V3_FY_ACTUALS_MATCH");
        if (matchingActuals.length > 0) {
          need(recObj.ytd_start === matchingActuals[0].start, "V3_FY_ACTUAL_START_MISMATCH");
        }
        const actSum = matchingActuals.reduce((sum: number, q: any) => sum + q.revenue, 0);
        need(closeV3(actSum, recObj.ytd_revenue), "V3_FY_YTD_REV_SUM");
        const n = 4 - recObj.ytd_quarter_ends.length;
        need(n >= 1 && n <= 4, "V3_FY_N_DERIVE");
        need(intervalObjs[n - 1].end === fyEnd, "V3_FY_INTERVAL_MATCH");

        let R = fyMp.point - recObj.ytd_revenue;
        need(R >= -1e-9, "V3_NEGATIVE_R");
        if (n === 1) {
          need(closeV3(R, gMp.point), "V3_CONCURRENT_N1_MISMATCH");
          fAmounts = [gMp.point, gMp.point, gMp.point, gMp.point];
          derivations = ["公司財測", "模型：後續各季持平於財測推算末季", "模型：後續各季持平於財測推算末季", "模型：後續各季持平於財測推算末季"];
        } else {
          let rem = R - gMp.point;
          need(rem >= -1e-9, "V3_NEGATIVE_CONCURRENT_RESIDUAL");
          if (rem < 0) rem = 0;
          fAmounts[0] = gMp.point;
          derivations[0] = "公司財測";
          const remShare = rem / (n - 1);
          for (let i = 1; i < n; i++) {
            fAmounts[i] = remShare;
            derivations[i] = "模型：全年財測扣已報營收及下季財測，剩餘各季均分";
          }
          for (let i = n; i < 4; i++) {
            fAmounts[i] = remShare;
            derivations[i] = "模型：後續各季持平於財測推算末季";
          }
        }
        isFy = true;
        amountsRecomputed = true;
      }

      // Post-quarter-end bridge
      const endedQuarters: any[] = [];
      for (let idx = 0; idx < intervalObjs.length; idx++) {
        const intv = intervalObjs[idx];
        if (reportDay > intv.end) {
          const overdue = days(intv.end, reportDay);
          need(overdue <= 70, "V3_OVERDUE_70D");
          endedQuarters.push({ idx, intv });
        }
      }
      if (endedQuarters.length > 0) {
        const earliest = endedQuarters[0];
        const affectedEnds = endedQuarters.map(q => q.intv.end);
        const endsStr = affectedEnds.join("、");
        const chkStr = receipt.checked_at;
        const wtext = isFy
          ? `全年財測推算季度已於${endsStr}結束，實際營收尚未公布；截至${chkStr}查核；仍為財測／模型，非實績`
          : `財測季度已於${endsStr}結束，實際營收尚未公布；截至${chkStr}查核；仍為財測／模型，非實績`;
        warning = {
          quarter_index: earliest.idx,
          quarter_end: earliest.intv.end,
          checked_at: chkStr,
          text: wtext,
          is_fy: isFy,
          affected_ends: affectedEnds,
        };
      }
    } else if (value.revenue_basis === "CONSENSUS") {
      const cEv = ev.consensus;
      need(isObject(cEv), "V3_CONSENSUS_REQUIRED");
      need(cEv.symbol === issuer, "V3_CONSENSUS_SYMBOL");
      const capTime = cEv.captured_at ?? cEv.retrieved_at;
      const capMs = instantMs(capTime);
      need(capMs !== null && capMs <= cutoffMs, "V3_CONSENSUS_TIME");
      need((cutoffMs - capMs!) / (3600 * 1000) <= 24, "V3_CONSENSUS_AGE");
      need(Array.isArray(cEv.quarters) && cEv.quarters.length >= 1 && cEv.quarters.length <= 2, "V3_CONSENSUS_QUARTERS");
      const q1 = cEv.quarters[0];
      need(isObject(q1) && q1.end === intervalObjs[0].end, "V3_CONSENSUS_Q1_END");
      need(q1.period === "0q" || q1.period === "Q1" || q1.period === "QUARTER", "V3_CONSENSUS_Q1_PERIOD");
      need(q1.scope === undefined || q1.scope === "CONSOLIDATED" || q1.scope === "COMPANY", "V3_CONSENSUS_Q1_SCOPE");
      need(q1.currency === undefined || q1.currency === validatedCurrency, "V3_CONSENSUS_Q1_CURRENCY");
      need(typeof q1.analysts === "number" && Number.isInteger(q1.analysts) && q1.analysts >= 3, "V3_CONSENSUS_Q1_ANALYSTS");
      const q1Rev = typeof q1.revenue === "number" ? q1.revenue : q1.avg;
      need(typeof q1Rev === "number" && Number.isFinite(q1Rev) && q1Rev >= 0, "V3_CONSENSUS_Q1_REV");
      // Consensus has NO +70d bridge
      need(reportDay <= intervalObjs[0].end, "V3_CONSENSUS_EXPIRED");

      const c1 = q1Rev;
      let q2Valid = false;
      let c2 = 0;
      let q2LowSample = false;
      if (cEv.quarters.length > 1) {
        const q2 = cEv.quarters[1];
        need(isObject(q2), "V3_CONSENSUS_Q2_MALFORMED");
        need(q2.end === intervalObjs[1].end, "V3_CONSENSUS_Q2_END");
        need(q2.period === undefined || q2.period === "+1q" || q2.period === "Q2" || q2.period === "QUARTER", "V3_CONSENSUS_Q2_PERIOD");
        need(q2.scope === undefined || q2.scope === "CONSOLIDATED" || q2.scope === "COMPANY", "V3_CONSENSUS_Q2_SCOPE");
        need(q2.currency === undefined || q2.currency === validatedCurrency, "V3_CONSENSUS_Q2_CURRENCY");
        const q2Rev = typeof q2.revenue === "number" ? q2.revenue : q2.avg;
        need(typeof q2Rev === "number" && Number.isFinite(q2Rev) && q2Rev >= 0, "V3_CONSENSUS_Q2_REV");
        need(typeof q2.analysts === "number" && Number.isInteger(q2.analysts) && q2.analysts >= 0, "V3_CONSENSUS_Q2_ANALYSTS");
        if (q2.analysts >= 3 && reportDay <= intervalObjs[1].end) {
          q2Valid = true;
          c2 = q2Rev;
        } else if (q2.analysts < 3) {
          q2LowSample = true;
        }
      }

      if (typeof cEv.currency === "string") {
        for (const q of actualObjs) if (typeof q.currency === "string") need(cEv.currency === q.currency, "V3_CONSENSUS_CURRENCY_MIX");
      }
      if (q2Valid) {
        fAmounts = [c1, c2, c2, c2];
        derivations = ["分析師共識", "分析師共識", "模型：持平於次季分析師共識", "模型：持平於次季分析師共識"];
      } else {
        fAmounts = [c1, c1, c1, c1];
        const secondDeriv = q2LowSample ? "僅一季共識（次季分析師樣本不足），其後持平模型" : "僅一季共識，其後持平模型";
        derivations = ["分析師共識", secondDeriv, secondDeriv, secondDeriv];
      }
      amountsRecomputed = true;
    }

    // Forward amounts: recomputed from sealed claims/consensus must match the sealed forward amounts field by field
    // (Astra r5 item 7): quarter_index, fiscal_label, start, end, amount and derivation, not just the amounts.
    need(amountsRecomputed, "V3_AMOUNTS_MUST_BE_RECOMPUTED");
    const sealedFw = Array.isArray(ev.forward_quarters) ? ev.forward_quarters : value.forward_quarters;
    need(Array.isArray(sealedFw) && sealedFw.length === 4, "V3_FW_AMOUNTS_SEALED");
    for (let i = 0; i < 4; i++) {
      const sf = sealedFw[i];
      need(isObject(sf), `V3_FW_ROW_${i}`);
      need(sf.quarter_index === i + 1, `V3_FW_INDEX_${i}`);
      need(sf.start === intervalObjs[i]!.start && sf.end === intervalObjs[i]!.end, `V3_FW_DATES_${i}`);
      need(sf.fiscal_label === (intervalObjs[i]!.fiscal_label ?? null), `V3_FW_LABEL_${i}`);
      need(typeof sf.amount === "number" && Number.isFinite(sf.amount), `V3_FW_AMOUNT_SEALED_${i}`);
      need(closeV3(fAmounts[i]!, sf.amount), `V3_FW_AMOUNT_${i}`);
      need(sf.derivation === derivations[i], `V3_FW_DERIVATION_${i}`);
    }

    // The bridge warning must equal the recomputed object as a whole (Astra r5 item 18): quarter_index,
    // quarter_end, checked_at, text, is_fy and affected_ends, in the top level and both tiles.
    if (warning !== null) {
      need(same(value.warning, warning), "V3_WARNING_MISMATCH");
      need(same(value.m6?.warning, warning), "V3_M6_WARNING_MISMATCH");
      need(same(value.m12?.warning, warning), "V3_M12_WARNING_MISMATCH");
    } else {
      need(!value.warning && !value.m6?.warning && !value.m12?.warning, "V3_UNEXPECTED_WARNING");
    }

    // 4. Arithmetic recomputation & validation
    const amount6 = fAmounts[0]! + fAmounts[1]!;
    const amount12 = fAmounts[0]! + fAmounts[1]! + fAmounts[2]! + fAmounts[3]!;
    need(closeV3(value.m6.amount, amount6), "V3_AMOUNT6");
    need(closeV3(value.m12.amount, amount12), "V3_AMOUNT12");
    need(value.m6.start === intervalObjs[0]!.start && value.m6.end === intervalObjs[1]!.end, "V3_M6_DATES");
    need(value.m12.start === intervalObjs[0]!.start && value.m12.end === intervalObjs[3]!.end, "V3_M12_DATES");

    need(value.m6.currency === validatedCurrency && value.m12.currency === validatedCurrency, "V3_CURRENCY_MISMATCH");

    let baselineB: number | null = null;
    let ttm6: number | null = null;
    let ttm12: number | null = null;
    let change6: number | null = null;
    let change12: number | null = null;

    if (actualObjs.length >= 4) {
      need(value.m6.scenario?.status === "AVAILABLE", "V3_M6_SCENARIO_NOT_AVAILABLE");
      need(value.m12.scenario?.status === "AVAILABLE", "V3_M12_SCENARIO_NOT_AVAILABLE");
      const latestFour = actualObjs.slice(-4);
      const bVal = latestFour.reduce((sum: number, q: any) => sum + q.revenue, 0);
      baselineB = bVal;
      need(closeV3(value.baseline_b, bVal), "V3_BASELINE");
      const t6 = latestFour[2]!.revenue + latestFour[3]!.revenue + fAmounts[0]! + fAmounts[1]!;
      const t12 = fAmounts[0]! + fAmounts[1]! + fAmounts[2]! + fAmounts[3]!;
      ttm6 = t6;
      ttm12 = t12;
      need(closeV3(value.m6.ttm_revenue, t6), "V3_TTM6");
      need(closeV3(value.m12.ttm_revenue, t12), "V3_TTM12");
      const c6 = t6 / bVal - 1;
      const c12 = t12 / bVal - 1;
      change6 = c6;
      change12 = c12;
      need(closeV3(value.m6.scenario?.change, c6), "V3_CHANGE6");
      need(closeV3(value.m12.scenario?.change, c12), "V3_CHANGE12");
    } else {
      need(value.baseline_b === null, "V3_BASELINE_NULL_MISSING_HISTORY");
      need(value.m6.scenario?.status === "NO_BASIS" && value.m6.scenario?.reason === "NO_REVENUE_HISTORY", "V3_SCENARIO_NO_HISTORY");
      need(value.m12.scenario?.status === "NO_BASIS" && value.m12.scenario?.reason === "NO_REVENUE_HISTORY", "V3_SCENARIO_NO_HISTORY");
    }

    if (value.assumptions !== undefined && value.assumptions !== null) {
      need(typeof value.assumptions === "string", "V3_ASSUMPTIONS_STRING");
      need(value.assumptions === CONDITION_TEXT_V3, "V3_ASSUMPTIONS_VALUE");
    }

    const recomputedFw = intervalObjs.map((intv: any, i: number) => ({
      quarter_index: i + 1,
      fiscal_label: intv.fiscal_label ?? null,
      start: intv.start,
      end: intv.end,
      amount: fAmounts[i],
      derivation: derivations[i],
    }));

    // The tiles' contracted recognition must equal the validated recognition (Astra r5 item 7), and an available
    // revenue result carries no revenue reason (item 6).
    need(same(value.m6.contracted_recognition ?? null, normRec?.m6 ?? null), "V3_M6_REC_TILE_MISMATCH");
    need(same(value.m12.contracted_recognition ?? null, normRec?.m12 ?? null), "V3_M12_REC_TILE_MISMATCH");
    need(value.reason === undefined || value.reason === null, "V3_REASON_DESPITE_AVAILABLE");

    const normM6: ForecastHorizon = {
      status: "AVAILABLE",
      reason: undefined,
      basis: value.revenue_basis,
      basis_label: value.revenue_basis === "COMPANY_GUIDANCE" ? "公司營收財測＋模型（非訂單）" : "非公司揭露、非訂單：分析師季度營收共識＋模型",
      amount: amount6,
      currency: validatedCurrency,
      start: intervalObjs[0].start,
      end: intervalObjs[1].end,
      horizon_label: "約6個月（2財季）",
      qualifier: `自${intervalObjs[0].start}起，非今日起`,
      ttm_revenue: ttm6 ?? undefined,
      scenario: actualObjs.length >= 4 ? { status: "AVAILABLE", change: change6! } : { status: "NO_BASIS", reason: "NO_REVENUE_HISTORY" },
      warning: warning ?? undefined,
      contracted_recognition: normRec?.m6 ?? null,
    };

    const normM12: ForecastHorizon = {
      status: "AVAILABLE",
      reason: undefined,
      basis: value.revenue_basis,
      basis_label: value.revenue_basis === "COMPANY_GUIDANCE" ? "公司營收財測＋模型（非訂單）" : "非公司揭露、非訂單：分析師季度營收共識＋模型",
      amount: amount12,
      currency: validatedCurrency,
      start: intervalObjs[0].start,
      end: intervalObjs[3].end,
      horizon_label: "約1年（4財季）",
      qualifier: `自${intervalObjs[0].start}起，非今日起`,
      ttm_revenue: ttm12 ?? undefined,
      scenario: actualObjs.length >= 4 ? { status: "AVAILABLE", change: change12! } : { status: "NO_BASIS", reason: "NO_REVENUE_HISTORY" },
      warning: warning ?? undefined,
      contracted_recognition: normRec?.m12 ?? null,
    };

    // A5 (Astra acceptance r7): the bounded provenance list of every operative selected input, rendered only from
    // the validated evidence above - each selected operational claim (its representation, operative quote, locator
    // and URL), its reaffirmations, the used actuals' document/locator and derivation operands, the YTD block, the
    // fiscal calendar source and the selected consensus quarters (with their analyst counts).
    type V3RevenueSource = NonNullable<OrderForecast["revenueSources"]>[number];
    const revenueSources: V3RevenueSource[] = [];
    const pushSource = (s: V3RevenueSource) => { if (revenueSources.length < 32) revenueSources.push(s); };
    if (value.revenue_basis === "COMPANY_GUIDANCE") {
      for (const sel of [...evc.activeQuarter, ...evc.activeFy]) {
        const cDoc = docMap.get(sel.document_id);
        pushSource({
          role: "GUIDANCE",
          representation: String(sel.original_representation ?? "").slice(0, 80),
          passage: String(sel.passage ?? "").replace(/\s+/g, " ").slice(0, 180),
          publisher: cDoc ? String(cDoc.publisher).slice(0, 80) : undefined,
          source_kind: cDoc?.source_kind,
          published_date: cDoc?.published_date,
          locator: sel.locator ? String(sel.locator).slice(0, 120) : undefined,
          url: cDoc ? String(cDoc.url).slice(0, 160) : undefined,
        });
        for (const ra of Array.isArray(sel.reaffirmed_by) ? sel.reaffirmed_by : []) {
          if (!isObject(ra)) continue;
          const raDoc = docMap.get(ra.document_id);
          pushSource({
            role: "REAFFIRMATION",
            passage: String(ra.passage ?? "").replace(/\s+/g, " ").slice(0, 180),
            locator: ra.locator ? String(ra.locator).slice(0, 120) : undefined,
            document_id: ra.document_id,
            url: raDoc ? String(raDoc.url).slice(0, 160) : undefined,
          });
        }
      }
      const calDoc = docMap.get(intervalObjs[0]!.calendar_document_id);
      if (calDoc) {
        pushSource({
          role: "CALENDAR",
          publisher: String(calDoc.publisher).slice(0, 80),
          source_kind: calDoc.source_kind,
          published_date: calDoc.published_date,
          locator: String(intervalObjs[0]!.calendar_locator ?? "").slice(0, 120),
          url: String(calDoc.url).slice(0, 160),
        });
      }
    } else if (value.revenue_basis === "CONSENSUS" && evc.consensus) {
      for (const q of Array.isArray(evc.consensus.quarters) ? evc.consensus.quarters : []) {
        if (!isObject(q)) continue;
        pushSource({
          role: "CONSENSUS",
          period: q.period,
          quarter_end: q.end,
          analysts: q.analysts,
          captured_at: String(evc.consensus.captured_at ?? evc.consensus.retrieved_at ?? ""),
          url: evc.consensus.source_url ? String(evc.consensus.source_url).slice(0, 160) : undefined,
        });
      }
    }
    // Used actuals' provenance (both bases: the consensus model's baseline is the sealed actuals) and the YTD block.
    for (const q of evc.actuals) {
      const qDoc = docMap.get(q.document_id);
      pushSource({
        role: "ACTUAL",
        quarter_end: q.end,
        document_id: q.document_id,
        locator: q.locator ? String(q.locator).slice(0, 120) : undefined,
        publisher: qDoc ? String(qDoc.publisher).slice(0, 80) : undefined,
        source_kind: qDoc?.source_kind,
        url: qDoc ? String(qDoc.url).slice(0, 160) : undefined,
        derivation: isObject(q.derivation)
          ? { longer_value: q.derivation.longer_value, shorter_value: q.derivation.shorter_value }
          : undefined,
      });
    }
    if (isObject(ev.fy_reconciliation)) {
      pushSource({
        role: "YTD",
        quarter_end: ev.fy_reconciliation.ytd_end,
        ytd_revenue: ev.fy_reconciliation.ytd_revenue,
      });
    }

    return {
      version: 3,
      issuer,
      m6: normM6,
      m12: normM12,
      sensitivity: validatedOrder.sensitivity,
      references: validatedOrder.references,
      supplements: validatedOrder.supplements,
      superseded: validatedOrder.superseded,
      registry24: validatedOrder.registry24,
      registry: ev.revenue_registry_status ?? null,
      cutoff: ev.cutoff,
      claims: validatedOrder.claims,
      currentStock: validatedOrder.currentStock,
      schedule: validatedOrder.schedule,
      formula: value.formula,
      horizonConvention: value.horizon_convention,
      revenueStatus: "AVAILABLE",
      revenueBasis: value.revenue_basis,
      revenueReason: null,
      revenueDiagnostic: null,
      anchorDate,
      baselineB,
      reportedQuarters: actualObjs,
      forwardQuarters: recomputedFw,
      contractedRecognition: normRec,
      assumptions: CONDITION_TEXT_V3,
      latestReleaseCheck: ev.latest_release_check ?? null,
      warning: warning ?? null,
      revenueSources,
    };
  } catch (error) {
    if (error instanceof EvidenceError) return invalid;
    return invalid;
  }
}

export function parseOrderForecastV3(raw: unknown, reportDay: string, issuer: string, generatedAt?: string, outerV2?: unknown): OrderForecast {
  const invalidV3 = normalized(3, unavailable("INVALID"), unavailable("INVALID"));
  if (!raw || typeof raw !== "object") return invalidV3;
  const value = raw as any;
  if (value.version !== 3) return invalidV3;
  return parseV3(value, reportDay, issuer, generatedAt, outerV2);
}

function machineUnavailable(outerV2: unknown, reportDay: string, issuer: string, generatedAt?: string): OrderForecast {
  // Independent unchanged v2 recognition checks only; never old revenue/consensus.
  const sibling = parseOrderForecast(outerV2, reportDay, issuer, generatedAt);
  const tile = (h: ForecastHorizon): ForecastHorizon => h.status === "AVAILABLE" && h.basis === "RECOGNITION"
    ? {...h, scenario: {status: "NO_BASIS", reason: "NO_REVENUE_BASIS"}}
    : unavailable("FRESHNESS_UNVERIFIED");
  return {...normalized(3, tile(sibling.m6), tile(sibling.m12)), issuer, cutoff: generatedAt ?? null, // absence stays null
    revenueStatus: "UNAVAILABLE", revenueBasis: null, revenueReason: "FRESHNESS_UNVERIFIED",
    revenueDiagnostic: "MACHINE_INPUTS_UNAVAILABLE", machineAdmitted: false};
}

export function parseOrderForecastV3Machine(raw: unknown, reportDay: string, issuer: string, generatedAt?: string,
  outerV2?: unknown, expected?: MachineBindings): OrderForecast {
  const context = validateMachineEnvelope(raw, expected, issuer, generatedAt, {
    digest: sha256Hex, receiptDigest: computeReceiptDigest,
    receiptStatus(receipt, record, cutoff) {
      const rc = record.release_channels;
      if (!isObject(rc) || !isObject(rc.ir) || receipt.coverage !== "SEC_WIRE_IR") return "FRESHNESS_UNVERIFIED";
      let host: string; try { host = new URL(rc.ir.url).host; } catch { return "FRESHNESS_UNVERIFIED"; }
      if (!["Q4_PRESS_RELEASES", "RSS", "NEWSROOM_HTML"].includes(rc.ir.kind)) return "FRESHNESS_UNVERIFIED";
      const doc = record.documents.find((d: any) => d.id === receipt.guidance_document_id);
      if (!doc) return "FRESHNESS_UNVERIFIED";
      return recomputeReceiptStatus(receipt, [], cutoff.slice(0,10), doc.published_date, Date.parse(cutoff), rc.sec_cik, rc.wire_symbol, host);
    },
  });
  if (!context) return machineUnavailable(outerV2, reportDay, issuer, generatedAt);
  const result = parseV3((raw as any).payload, reportDay, issuer, generatedAt, outerV2, context);
  if (result.m6.reason === "INVALID" && result.m12.reason === "INVALID" && result.revenueStatus === undefined)
    return machineUnavailable(outerV2, reportDay, issuer, generatedAt);
  return {...result, machineAdmitted: context.kind === "AUTO"};
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
  INVALID: "資料未通過驗證", STALE: "資料逾期未更新", NO_GROWTH: "訂單無可比年增", GROWTH_OUT_OF_RANGE: "訂單年增超出可外推範圍",
  NOT_DISCLOSED: "公司未揭露", NO_ORDERS: "未取得訂單資料", EXPIRED: "期間已結束", SCHEDULE_CONTRADICTION: "認列時程前後矛盾",
  NO_GROWTH_LINEAGE: "年增缺少可比基期", INVALID_SHARE: "揭露的認列比例無效", LEGACY: "訂單預估尚未產生",
  NO_REALIZATION_SCHEDULE: "公司未揭露認列時程", CONFLICTING_DISCLOSURES: "公司揭露互相矛盾，暫不估算", EVIDENCE_LIMIT: "證據超出上限，暫不估算",
  UNQUANTIFIED_STOCK: "最新揭露無可計算的訂單金額", UNRESOLVED_REVISION: "公司更正無法對應到本次申報，暫不估算",
  NO_REVENUE_HISTORY: "缺完整四季營收基準，無法估算", NO_REVENUE_BASIS: "缺完整營收推估，無法估算股價情境",
  WITHDRAWN: "公司已撤回財測", FRESHNESS_UNVERIFIED: "最新發布查核未通過", QUARTER_END_EXCEEDED_70D: "財測季度結束逾70天，暫不估算",
  SAMPLE_INSUFFICIENT: "分析師樣本數不足（少於3家）",
};
const LABEL = { m6: "半年", m12: "1年" } as const;
const UNDISCLOSED = new Set<ForecastReason>(["NOT_DISCLOSED_HORIZON", "NO_REALIZATION_SCHEDULE", "NOT_DISCLOSED"]);
const SOURCE_KIND_TEXT: Record<string, string> = { SEC_PERIODIC: "SEC 定期報告", SEC_8K_EXHIBIT: "SEC 8-K 附件",
  ISSUER_EARNINGS_RELEASE: "公司財報新聞稿", ISSUER_PREPARED_REMARKS: "公司法說會講稿", ISSUER_CONTRACT_ANNOUNCEMENT: "公司合約公告" };
const METRIC_TEXT: Record<string, string> = { RPO_STOCK: "RPO", BACKLOG_STOCK: "在手訂單", SIGNED_CONTRACT_VALUE: "已簽合約",
  ORDER_INTAKE: "新接訂單", ORDER_GUIDANCE: "公司訂單指引", RECOGNITION_SCHEDULE: "認列時程" };
export const CONDITION_TEXT = "條件情境：營收達預計認列額，P/S與股數不變；非目標價、非今日起報酬";
export const CONDITION_TEXT_V3 = "條件情境：營收依上述推估實現，P/S與股數不變；以最新已報四季為基準，非目標價、非今日起報酬";
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

function orderStateV3(h: ForecastHorizon, diag: string | null): string {
  if (h.status === "AVAILABLE") return "有效";
  const r = h.reason;
  if (r === "NOT_DISCLOSED" || r === "NOT_DISCLOSED_HORIZON") return diag === "CONSENSUS_DEFERRED" ? "公司未提供營收財測；分析師共識路線本次未啟用" : "未揭露";
  if (r === "INPUTS_MISSING") return "未收錄經審核的營收財測（公司未提供或尚待審核）";
  if (r === "STALE") return "資料逾期未更新";
  if (r === "CONFLICTING_DISCLOSURES") return "公司揭露互相矛盾，暫不估算";
  if (r === "WITHDRAWN") return "公司已撤回財測";
  // The distinct IR-coverage diagnostic (Astra W1 ruling): the official-IR channel was not covered, so the
  // company-guidance revenue path is suspended (order recognition stays independent).
  if (r === "FRESHNESS_UNVERIFIED") return diag === "IR_COVERAGE_MISSING" ? "官方IR查核未完成，暫停營收推估" : "最新發布查核未通過";
  if (r === "EVIDENCE_LIMIT") return "證據超出上限，暫不估算";
  if (r === "SAMPLE_INSUFFICIENT") return "分析師樣本數不足（少於3家）";
  if (r === "PERIOD_MISMATCH") return "推估期間與會計季度不符";
  if (r === "NO_REVENUE_HISTORY") return "缺完整四季營收基準，無法估算";
  if (r === "NO_REVENUE_BASIS") return "缺完整營收推估，無法估算股價情境";
  if (r === "INVALID" && diag === "UNREVIEWED_INPUTS") return "營收輸入未經審核，暫停營收推估";
  return "資料未通過驗證";
}

function orderRowV3(forecast: OrderForecast, key: Key, money: Money): string {
  const h = forecast[key];
  const hLabel = h.horizon_label ?? (key === "m6" ? "約6個月（2財季）" : "約1年（4財季）");
  const diag = forecast.revenueDiagnostic ?? null;
  if (h.status !== "AVAILABLE") {
    return `${hLabel}：${orderStateV3(h, diag)}`;
  }
  if (h.basis === "RECOGNITION") {
    return `${hLabel}內預計認列：${money(h.amount!, h.currency!)}（已簽約預計認列；自${h.start}起，非今日起，至${h.end}）`;
  }
  return `${hLabel}：${money(h.amount!, h.currency!)}（${h.basis_label ?? "公司營收財測＋模型（非訂單）"}；自${h.start}起，非今日起，至${h.end}）`;
}

function priceRowV3(forecast: OrderForecast, key: Key): string {
  const h = forecast[key];
  const hLabel = h.horizon_label ?? (key === "m6" ? "約6個月（2財季）" : "約1年（4財季）");
  const diag = forecast.revenueDiagnostic ?? null;
  if (h.status !== "AVAILABLE") {
    return `若${hLabel}達成營收推估 → 無法估算（${orderStateV3(h, diag)}）`;
  }
  if (h.basis === "RECOGNITION") {
    return `若${hLabel}內實現訂單 → 無法估算（缺完整營收推估，無法估算股價情境）`;
  }
  const s = h.scenario;
  if (s.status === "AVAILABLE" && s.change !== undefined) {
    return `若${hLabel}達成營收推估 → 股價情境 ${signedPct(s.change)}`;
  }
  return `若${hLabel}達成營收推估 → 無法估算（缺完整四季營收基準，無法估算）`;
}

/** Bounded revenue-source lines (Astra r5 item 19; acceptance r7 A5), rendered only from the validated sources
 * parseV3 sealed into forecast.revenueSources. The compact card keeps its two bounded lines (the first guidance
 * claim, the consensus quarter); the detail renders the full bounded list - every selected operational claim with
 * its representation, operative quote, locator and URL, the reaffirmations, the used actuals' provenance and
 * derivation operands, the YTD block, the fiscal calendar and the selected consensus quarters. */
const fmtV3Amount = (v: number): string => Number.isFinite(v) ? (Math.abs(v) >= 1e9 ? `${(v / 1e9).toFixed(2)}B` : `${(v / 1e6).toFixed(1)}M`) : "N/A";
function revenueSourceLinesV3(forecast: OrderForecast, detail = false): string[] {
  const sources = forecast.revenueSources ?? [];
  if (!detail) {
    const lines: string[] = [];
    const g = sources.find(s => s.role === "GUIDANCE");
    if (g) {
      const stated = g.representation ? `公司財測 ${g.representation}` : "公司財測";
      lines.push(`營收財測來源：${g.publisher ?? ""}（${g.source_kind ?? ""}，發布${g.published_date ?? ""}）；${stated}${g.url ? `：${g.url}` : ""}`.slice(0, 240));
    }
    const c = sources.find(s => s.role === "CONSENSUS");
    if (c) lines.push(`分析師共識（${c.period ?? "0q"}，至${c.quarter_end ?? "?"}）：${c.analysts ?? 0}位分析師${c.url ? `：${c.url}` : ""}`.slice(0, 240));
    return lines;
  }
  const lines: string[] = [];
  for (const s of sources) {
    switch (s.role) {
      case "GUIDANCE": {
        const stated = s.representation ? `公司財測 ${s.representation}` : "公司財測";
        lines.push(`營收財測來源：${s.publisher ?? ""}（${s.source_kind ?? ""}，發布${s.published_date ?? ""}）；${stated}${s.locator ? `；${s.locator}` : ""}${s.url ? `：${s.url}` : ""}`.slice(0, 300));
        if (s.passage) lines.push(`　原文：「${s.passage}」`.slice(0, 300));
        break;
      }
      case "REAFFIRMATION":
        lines.push(`財測重申：「${(s.passage ?? "").slice(0, 160)}」${s.locator ? `；${s.locator}` : ""}${s.url ? `：${s.url}` : ""}`.slice(0, 300));
        break;
      case "ACTUAL":
        lines.push(`實際營收來源（至${s.quarter_end ?? "?"}）：${s.publisher ?? ""}${s.locator ? ` ${s.locator}` : ""}${s.derivation ? `；YTD差額 ${fmtV3Amount(s.derivation.longer_value)}−${fmtV3Amount(s.derivation.shorter_value)}` : ""}${s.url ? `：${s.url}` : ""}`.slice(0, 300));
        break;
      case "YTD":
        lines.push(`YTD營收（至${s.quarter_end ?? "?"}）：${s.ytd_revenue !== undefined ? fmtV3Amount(s.ytd_revenue) : "未揭露"}`.slice(0, 300));
        break;
      case "CALENDAR":
        lines.push(`財季日曆來源：${s.publisher ?? ""}（${s.source_kind ?? ""}，發布${s.published_date ?? ""}）${s.locator ? `；${s.locator}` : ""}${s.url ? ` ${s.url}` : ""}`.slice(0, 300));
        break;
      case "CONSENSUS":
        lines.push(`分析師共識（${s.period ?? "0q"}，至${s.quarter_end ?? "?"}）：${s.analysts ?? 0}位分析師${s.url ? `：${s.url}` : ""}`.slice(0, 300));
        break;
    }
  }
  return lines;
}

/** The revenue-path suspension stated on every surface (Astra W1; acceptance r7 A1/A3): the official-IR coverage
 * suspension, the unreviewed-inputs suspension and the deferred consensus route - each beside any independently
 * valid contracted recognition, which is never suppressed. */
function revenueSuspensionLineV3(forecast: OrderForecast): string | null {
  switch (forecast.revenueDiagnostic) {
    case "IR_COVERAGE_MISSING":
      return "營收推估：官方IR查核未完成，暫停營收推估（已簽約認列另列，不受影響）";
    case "UNREVIEWED_INPUTS":
      return "營收推估：營收輸入未經審核，暫停營收推估（已簽約認列另列，不受影響）";
    case "CONSENSUS_DEFERRED":
      return "營收推估：公司未提供營收財測；分析師共識路線本次未啟用（已簽約認列另列，不受影響）";
    default:
      return null;
  }
}

function getModelAssumptionText(forecast: OrderForecast): string | null {
  if (forecast.revenueBasis === "COMPANY_GUIDANCE") {
    const f1Deriv = forecast.forwardQuarters?.[0]?.derivation ?? "";
    const f2Deriv = forecast.forwardQuarters?.[1]?.derivation ?? "";
    if (f1Deriv.includes("全年財測扣已報營收") && !f1Deriv.includes("公司財測")) {
      return "模型假設：全年財測扣除已報營收後剩餘各季均分，其後持平模型。";
    }
    if (f2Deriv.includes("全年財測")) {
      return "模型假設：首季依季度財測；其後依全年財測扣除已報營收及首季財測均分，其餘持平模型。";
    }
    return "模型假設：首季依公司財測；之後各季持平於首季財測模型。";
  }
  if (forecast.revenueBasis === "CONSENSUS") {
    const f2Deriv = forecast.forwardQuarters?.[1]?.derivation ?? "";
    if (f2Deriv.includes("僅一季共識")) {
      // The single-quarter consensus model (Astra r5 item 19): state the one consensus quarter, not "the first two".
      return f2Deriv.includes("次季分析師樣本不足")
        ? "模型假設：首季依分析師共識（次季樣本不足）；其後各季持平首季模型。"
        : "模型假設：首季依分析師共識；其後各季持平首季模型。";
    }
    return "模型假設：前兩季依分析師共識；其後各季持平於次季共識模型。";
  }
  return null;
}

function forecastCardV3(forecast: OrderForecast, money: Money): [string, boolean][] {
  const lines: [string, boolean][] = [
    ["訂單認列／營收推估", true],
    [orderRowV3(forecast, "m6", money), false],
    [orderRowV3(forecast, "m12", money), false],
  ];

  const irLine = revenueSuspensionLineV3(forecast);
  if (irLine) lines.push([irLine, false]);
  const modelAssumption = getModelAssumptionText(forecast);
  if (modelAssumption) {
    lines.push([modelAssumption, false]);
  }
  for (const src of revenueSourceLinesV3(forecast)) {
    lines.push([src, false]);
  }

  lines.push(
    ["營收實現後股價情境", true],
    [priceRowV3(forecast, "m6"), false],
    [priceRowV3(forecast, "m12"), false],
    [CONDITION_TEXT_V3, false],
  );

  const warning = forecast.m6.warning ?? forecast.m12.warning;
  if (warning) {
    lines.push([`財測時效警示：${warning.text}`, false]);
  }

  const rec = forecast.contractedRecognition;
  if (rec && forecast.m6.basis !== "RECOGNITION") {
    if (rec.m6 && rec.m12) {
      lines.push([`另列已簽約預計認列：半年期 ${money(rec.m6.amount, rec.m6.currency)}（起訖日 ${rec.m6.start}–${rec.m6.end}；不相加）`, false]);
      lines.push([`另列已簽約預計認列：1年期 ${money(rec.m12.amount, rec.m12.currency)}（起訖日 ${rec.m12.start}–${rec.m12.end}；不相加）`, false]);
    } else if (rec.m6 && !rec.m12) {
      lines.push([`另列已簽約預計認列：半年期 ${money(rec.m6.amount, rec.m6.currency)}（起訖日 ${rec.m6.start}–${rec.m6.end}；不相加）`, false]);
      lines.push(["另列已簽約預計認列：1年期未揭露時程（非公司揭露）", false]);
    } else if (rec.m12 && !rec.m6) {
      lines.push(["另列已簽約預計認列：半年期未揭露時程（非公司揭露）", false]);
      lines.push([`另列已簽約預計認列：1年期 ${money(rec.m12.amount, rec.m12.currency)}（起訖日 ${rec.m12.start}–${rec.m12.end}；不相加）`, false]);
    }
  }

  return lines;
}

function forecastTextV3(forecast: OrderForecast, money: Money): string {
  const parts = [
    `訂單認列／營收推估：${orderRowV3(forecast, "m6", money)}／${orderRowV3(forecast, "m12", money)}`,
  ];
  const modelAssumption = getModelAssumptionText(forecast);
  if (modelAssumption) parts.push(modelAssumption);
  const irText = revenueSuspensionLineV3(forecast);
  if (irText) parts.push(irText);
  parts.push(...revenueSourceLinesV3(forecast));
  parts.push(`營收實現後股價情境：${priceRowV3(forecast, "m6")}／${priceRowV3(forecast, "m12")}（${CONDITION_TEXT_V3}）`);
  const warning = forecast.m6.warning ?? forecast.m12.warning;
  if (warning) parts.push(warning.text);
  const rec = forecast.contractedRecognition;
  if (rec && forecast.m6.basis !== "RECOGNITION") {
    if (rec.m6 && rec.m12) {
      parts.push(`另列已簽約預計認列：半年期 ${money(rec.m6.amount, rec.m6.currency)}（起訖日 ${rec.m6.start}–${rec.m6.end}；不相加）`);
      parts.push(`另列已簽約預計認列：1年期 ${money(rec.m12.amount, rec.m12.currency)}（起訖日 ${rec.m12.start}–${rec.m12.end}；不相加）`);
    } else if (rec.m6 && !rec.m12) {
      parts.push(`另列已簽約預計認列：半年期 ${money(rec.m6.amount, rec.m6.currency)}（起訖日 ${rec.m6.start}–${rec.m6.end}；不相加）`);
      parts.push("另列已簽約預計認列：1年期未揭露時程（非公司揭露）");
    } else if (rec.m12 && !rec.m6) {
      parts.push("另列已簽約預計認列：半年期未揭露時程（非公司揭露）");
      parts.push(`另列已簽約預計認列：1年期 ${money(rec.m12.amount, rec.m12.currency)}（起訖日 ${rec.m12.start}–${rec.m12.end}；不相加）`);
    }
  }
  return parts.join("｜");
}

function forecastLinesV3(forecast: OrderForecast, money: Money): string[] {
  const lines: string[] = ["訂單認列／營收推估"];
  lines.push(orderRowV3(forecast, "m6", money));
  lines.push(orderRowV3(forecast, "m12", money));
  const irDetail = revenueSuspensionLineV3(forecast);
  if (irDetail) lines.push(irDetail);

  const modelAssumption = getModelAssumptionText(forecast);
  if (modelAssumption) {
    lines.push(modelAssumption);
  }
  lines.push(...revenueSourceLinesV3(forecast, true));

  lines.push("營收實現後股價情境");
  lines.push(priceRowV3(forecast, "m6"));
  lines.push(priceRowV3(forecast, "m12"));
  lines.push(CONDITION_TEXT_V3);
  lines.push("條件假設：以最新已報四季營收（B）為基準，營收推估達成時P/S倍數與股數不變；非目標價、非投資建議。");
  lines.push("風險提示：訂單取消或延遲、季度營收淡旺季、毛利率與產品組合變化、估值倍數收縮及股數稀釋風險。");

  const warning = forecast.m6.warning ?? forecast.m12.warning;
  if (warning) {
    lines.push(`財測時效警示：${warning.text}`);
  }

  const curr = forecast.reportedQuarters?.[0]?.currency ?? forecast.m6.currency ?? "USD";
  if (forecast.reportedQuarters && forecast.reportedQuarters.length >= 4 && forecast.baselineB !== null && forecast.baselineB !== undefined) {
    const latestFour = forecast.reportedQuarters.slice(-4);
    const qStrs = latestFour.map(q => `${q.fiscal_label ?? q.end}: ${money(q.revenue, q.currency)}`);
    lines.push(`已報四季基準營收（B）：${money(forecast.baselineB, curr)}（${qStrs.join("，")}）`);
  } else {
    lines.push("已報四季基準營收（B）：無法取得（缺完整四季營收基準）");
  }

  if (forecast.m6.ttm_revenue !== null && forecast.m6.ttm_revenue !== undefined && forecast.m12.ttm_revenue !== null && forecast.m12.ttm_revenue !== undefined) {
    lines.push(`6個月TTM營收分子：${money(forecast.m6.ttm_revenue, curr)}；1年TTM營收分子：${money(forecast.m12.ttm_revenue, curr)}`);
  }

  if (forecast.forwardQuarters && forecast.forwardQuarters.length === 4) {
    if (warning) {
      lines.push("推算四個財季（含已結束財季）營收：");
    } else {
      lines.push("推估未來四季營收：");
    }
    for (const f of forecast.forwardQuarters) {
      lines.push(`　第${f.quarter_index}季（${f.start}至${f.end}）：${money(f.amount, curr)}（${f.derivation}）`);
    }
  }

  const rec = forecast.contractedRecognition;
  if (rec && forecast.m6.basis !== "RECOGNITION") {
    if (rec.m6 && rec.m12) {
      lines.push(`另列已簽約預計認列：半年期 ${money(rec.m6.amount, rec.m6.currency)}（起訖日 ${rec.m6.start}–${rec.m6.end}；不相加）`);
      lines.push(`另列已簽約預計認列：1年期 ${money(rec.m12.amount, rec.m12.currency)}（起訖日 ${rec.m12.start}–${rec.m12.end}；不相加）`);
    } else if (rec.m6 && !rec.m12) {
      lines.push(`另列已簽約預計認列：半年期 ${money(rec.m6.amount, rec.m6.currency)}（起訖日 ${rec.m6.start}–${rec.m6.end}；不相加）`);
      lines.push("另列已簽約預計認列：1年期未揭露時程（非公司揭露）");
    } else if (rec.m12 && !rec.m6) {
      lines.push("另列已簽約預計認列：半年期未揭露時程（非公司揭露）");
      lines.push(`另列已簽約預計認列：1年期 ${money(rec.m12.amount, rec.m12.currency)}（起訖日 ${rec.m12.start}–${rec.m12.end}；不相加）`);
    }
  } else if (forecast.m6.basis !== "RECOGNITION" && forecast.m12.basis !== "RECOGNITION") {
    lines.push("訂單認列：未揭露半年期／1年期認列時程（非公司揭露）");
  }

  // Sourced references, superseded disclosures, and the order-book extrapolation (a model input, never a price).
  if (Array.isArray(forecast.references) && forecast.references.length > 0) {
    lines.push("訂單來源參考資料：");
    for (const ref of forecast.references) {
      const when = ref.start ? `${ref.start}–${ref.end}` : (ref.year !== undefined ? `FY${ref.year}` : "");
      lines.push(`　${ref.kind}：${ref.currency ?? "USD"} ${ref.amount}${when ? `（${when}）` : ""}`);
    }
  }
  if (Array.isArray(forecast.superseded) && forecast.superseded.length > 0) {
    lines.push("已過期／被取代之揭露：");
    for (const sup of forecast.superseded) {
      lines.push(`　${sup.filed ?? sup.as_of}（${sup.form ?? "filed"}，已過期／被取代）`);
    }
  }
  if (forecast.sensitivity) {
    const s = forecast.sensitivity;
    const parts: string[] = [];
    if (s.m6.status === "AVAILABLE" && s.m6.amount !== undefined && s.m6.currency) parts.push(`半年 ${money(s.m6.amount, s.m6.currency)}`);
    if (s.m12.status === "AVAILABLE" && s.m12.amount !== undefined && s.m12.currency) parts.push(`1年 ${money(s.m12.amount, s.m12.currency)}`);
    if (parts.length > 0) lines.push(`在手訂單外推（僅參考、非股價）：${parts.join("、")}`);
  }

  const lrc = forecast.latestReleaseCheck;
  if (lrc) {
    // The channel text follows the receipt's coverage: the official IR channel is listed only when it was checked.
    const coverageText = lrc.coverage === "SEC_WIRE_IR" ? "SEC 申報、通訊社新聞稿與官方IR" : "SEC 申報與通訊社新聞稿";
    lines.push(`最新發布查核：${lrc.checked_at}；查核管道：${lrc.coverage}（${coverageText}）；狀態：${lrc.status}`);
  }

  return lines;
}

/** The card's order block, one entry per line: [text, heading]. Both horizons, their windows, the conditional price rows
 * and the dates of the data always appear together. */
export function forecastCard(forecast: OrderForecast, money: Money): [string, boolean][] {
  if (forecast.version === 3) return forecastCardV3(forecast, money);
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
  if (forecast.version === 3) return forecastTextV3(forecast, money);
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
  if (forecast.version === 3) return forecastLinesV3(forecast, money);
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
