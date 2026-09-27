/** The Top20 card's 6-month and 1-year ORDER figures and the price change if those orders are realized (operator
 * 2026-09-27; Astra contract "order horizons and order-linked price scenarios"). The sealer computes them with
 * scripts/order_forecast.py; this module re-validates every sealed record against the same rules (issuer, scope, currency,
 * evidence, windows, the cumulative schedule, and every derived value recomputed from its sealed inputs) and renders them.
 * A record that fails is shown as unavailable, never replaced by another figure; no analyst estimate enters either tile. */

export type ForecastReason = "NOT_DISCLOSED_HORIZON" | "PERIOD_MISMATCH" | "INPUTS_MISSING" | "INVALID" | "STALE" | "NO_GROWTH"
  | "GROWTH_OUT_OF_RANGE" | "NOT_DISCLOSED" | "NO_ORDERS" | "EXPIRED" | "SCHEDULE_CONTRADICTION" | "NO_GROWTH_LINEAGE" | "INVALID_SHARE" | "LEGACY";
export interface ForecastScenario { status: "AVAILABLE" | "INSUFFICIENT_COVERAGE" | "NO_BASIS"; coverage?: number; change?: number;
  reason?: "NO_ORDER_BASIS" | "SCOPE_PARTIAL" }
export interface ForecastHorizon {
  status: "AVAILABLE" | "UNAVAILABLE"; reason?: ForecastReason; basis?: "RECOGNITION" | "STOCK_EXTRAPOLATION";
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
export interface OrderForecast { version: 1; m6: ForecastHorizon; m12: ForecastHorizon; references: ForecastReference[] }

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
export function parseOrderForecast(raw: unknown, reportDay: string, issuer: string): OrderForecast {
  const legacy: OrderForecast = { version: 1, m6: unavailable("LEGACY"), m12: unavailable("LEGACY"), references: [] };
  const invalid: OrderForecast = { version: 1, m6: unavailable("INVALID"), m12: unavailable("INVALID"), references: [] };
  if (!raw || typeof raw !== "object") return legacy;
  const value = raw as any;
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
  return { version: 1, m6, m12, references };
}

// ---------------------------------------------------------------- rendering

const REASON_TEXT: Record<ForecastReason, string> = {
  NOT_DISCLOSED_HORIZON: "公司未揭露此期間認列時程", PERIOD_MISMATCH: "訂單與營收期間不一致", INPUTS_MISSING: "缺少 RPO 或同期營收",
  INVALID: "訂單資料未通過驗證", STALE: "訂單資料逾200天", NO_GROWTH: "訂單無可比年增", GROWTH_OUT_OF_RANGE: "訂單年增超出可外推範圍",
  NOT_DISCLOSED: "公司未揭露訂單", NO_ORDERS: "無訂單資料", EXPIRED: "此期間已結束", SCHEDULE_CONTRADICTION: "認列時程前後矛盾",
  NO_GROWTH_LINEAGE: "年增缺少可比基期", INVALID_SHARE: "揭露的認列比例無效", LEGACY: "訂單預估尚未產生",
};
const SHORT_REASON: Partial<Record<ForecastReason, string>> = { NOT_DISCLOSED_HORIZON: "未揭露", NO_ORDERS: "無資料", NOT_DISCLOSED: "未揭露", EXPIRED: "已過期" };

const pct = (value: number, digits = 0) => `${value >= 0 ? "+" : ""}${(value * 100).toFixed(digits)}%`;
const coveragePct = (value: number) => `${(value * 100) < 10 ? (value * 100).toFixed(1) : (value * 100).toFixed(0)}%`;
type Money = (amount: number, currency: string | null) => string;

const orderValue = (h: ForecastHorizon, money: Money) => h.status === "AVAILABLE" ? money(h.amount!, h.currency!) : (SHORT_REASON[h.reason!] ?? "無法取得");
const orderBasis = (h: ForecastHorizon) => h.basis === "RECOGNITION" ? `已簽約預計認列，自揭露日${h.start}起（非今日起）`
  : `${h.scope === "SEGMENT" ? `${h.scope_label ?? "部門"}訂單（非全公司）` : "訂單餘額"}自今日起外推至${h.end}（非期間認列）`;
const priceValue = (h: ForecastHorizon) => h.scenario.status === "AVAILABLE" ? pct(h.scenario.change!) : "無法估價";
const priceWhy = (h: ForecastHorizon) => h.scenario.status === "INSUFFICIENT_COVERAGE" ? `訂單僅覆蓋同期營收${coveragePct(h.scenario.coverage!)}`
  : h.scenario.status === "AVAILABLE" ? (h.basis === "RECOGNITION" ? "假設營收達已簽約額、P/S與股數不變" : "假設營收隨訂單、P/S與股數不變")
  : h.scenario.reason === "SCOPE_PARTIAL" ? "部門訂單不代表全公司" : "缺訂單依據";

/** The two card tiles: [label, value, sub]; both always name 6個月 and 1年, and every reason belongs to its own horizon. */
export function forecastTiles(forecast: OrderForecast, money: Money): [[string, string, string], [string, string, string]] {
  const { m6, m12 } = forecast;
  const basis = [m12, m6].find(h => h.status === "AVAILABLE");
  const orderSub = `6個月 ${orderValue(m6, money)}・${basis ? orderBasis(basis) : REASON_TEXT[m12.reason!]}`;
  const priceSub = m6.scenario.status === m12.scenario.status && priceWhy(m6) === priceWhy(m12) && m6.status === m12.status
    ? `6個月 ${priceValue(m6)}・${priceWhy(m12)}` : `6個月 ${priceValue(m6)}（${priceWhy(m6)}）・1年：${priceWhy(m12)}`;
  return [["未來訂單預估", `1年 ${orderValue(m12, money)}`, orderSub], ["若實現股價（變動）", `1年 ${priceValue(m12)}`, priceSub]];
}

/** The two tiles in one line for the text form of the Top20, with the same basis, window, scope and conditions as the card. */
export function forecastText(forecast: OrderForecast, money: Money): string {
  const { m6, m12 } = forecast;
  const basis = [m12, m6].find(h => h.status === "AVAILABLE");
  const orders = `未來訂單 1年 ${orderValue(m12, money)}／6個月 ${orderValue(m6, money)}（${basis ? orderBasis(basis) : REASON_TEXT[m12.reason!]}）`;
  const price = `若實現股價 1年 ${priceValue(m12)}（${priceWhy(m12)}）／6個月 ${priceValue(m6)}（${priceWhy(m6)}）`;
  return `${orders}｜${price}`;
}

/** The detail lines: each horizon with its window, basis, inputs, assumptions and source, then the fixed-period references. */
export function forecastLines(forecast: OrderForecast, money: Money): string[] {
  const lines: string[] = [];
  const sources = new Set<string>();
  for (const [key, label] of [["m6", "6個月"], ["m12", "1年"]] as const) {
    const h = forecast[key];
    if (h.status !== "AVAILABLE") {
      lines.push(`未來訂單預估・${label}：無（${REASON_TEXT[h.reason!]}）；若實現股價：無法估價（缺訂單依據）。`);
      continue;
    }
    if (h.basis === "RECOGNITION") {
      const quarter = h.quarter_basis === "DERIVED_Q4" && h.quarter_derivation
        ? `${h.quarter_end} 當季（第四季＝全年 ${money(h.quarter_derivation.annual, "USD")} − 前九個月 ${money(h.quarter_derivation.nine_months, "USD")}）`
        : `${h.quarter_end} 當季`;
      lines.push(`未來訂單預估・${label}（${h.start}–${h.end}，自揭露日起算，非今日起）：${money(h.amount!, h.currency!)}，已簽約預計認列（RPO ${money(h.rpo!, h.currency!)} × ${h.share_pct}%）。`);
      lines.push(h.scenario.status === "AVAILABLE"
        ? `若實現股價・${label}：${pct(h.scenario.change!)}（條件情境：同期營收達已簽約金額，同期營收水準＝${quarter}×${label === "1年" ? 4 : 2}；P/S與股數不變；非目標價，非今日起的報酬；未計新訂單、取消或遞延）。`
        : `若實現股價・${label}：無法估價，已簽約訂單僅覆蓋同期營收水準的 ${coveragePct(h.scenario.coverage!)}（同期營收水準＝${quarter}×${label === "1年" ? 4 : 2}；其餘營收來自尚未簽約的訂單）。`);
      sources.add(`訂單來源：${h.form ?? "申報"} ${h.filed}${h.accession ? `（${h.accession}）` : ""} ${h.source_url}${h.passage ? `；原文：「${h.passage.slice(0, 160)}」` : ""}`);
    } else {
      const growth = h.lineage === "SERIES" ? `對比 ${h.yoy_prior_as_of} 的 ${money(h.yoy_prior_amount!, h.currency!)}` : `公司自述：「${(h.yoy_evidence ?? "").slice(0, 80)}」`;
      lines.push(`未來訂單預估・${label}（${h.start}–${h.end}）：${money(h.amount!, h.currency!)}，${h.scope === "SEGMENT" ? `${h.scope_label ?? "部門"}（非全公司）` : ""}${h.kind === "RPO" ? "RPO" : "在手訂單"}餘額 ${money(h.stock!, h.currency!)}（${h.as_of}）依年增${pct(h.yoy!)}（${growth}）外推；期末餘額，非期間認列。`);
      lines.push(h.scenario.status === "AVAILABLE"
        ? `若實現股價・${label}：${pct(h.scenario.change!)}（假設營收同比例跟隨訂單餘額、P/S與股數不變；以今日餘額為基準；訂單可能取消、延遲或組合改變；非目標價）。`
        : `若實現股價・${label}：無法估價（部門訂單不代表全公司營收）。`);
      sources.add(`訂單來源：${h.source_url}`);
    }
  }
  lines.push(...sources);
  for (const ref of forecast.references) {
    lines.push(ref.kind === "RECOGNITION_24M"
      ? `參考（固定期間，非6個月／1年）：24個月內認列 ${money(ref.amount, ref.currency)}（RPO × ${ref.share_pct}%，${ref.start}–${ref.end}）。`
      : `參考（固定期間）：公司${ref.year}年全年新接訂單指引 ${money(ref.amount, ref.currency)}。`);
  }
  return lines;
}
