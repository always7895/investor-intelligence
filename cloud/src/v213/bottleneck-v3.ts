/** Bottleneck-explosion Top20 v3 and the Leopold-led industry ranking (scripts/bottleneck_top20_v3.py).
 *
 * Sealed as the lazy object `v213:bottleneck-top20:v3`. Leads (Serenity posts, 13F positions) weight conviction
 * but are never shown as company facts; every figure carries its source and date. A malformed or stale document
 * (older than the report bound, report-age.ts) gives null and the caller keeps the seven-field Top20.
 */
import { forecastCard, forecastLines, forecastText, parseOrderForecast, parseOrderForecastV3, parseOrderForecastV3Machine, type OrderForecast } from "./order-forecast";
import { historyBlockLines, historyViewOf, type HistoryView } from "./revenue-history-model";
import { assertLineMessages, type LineOutboundMessage } from "../line-messages";
import type { PublicSnapshotView } from "./public-snapshot";
import { v213ReportAgeFresh } from "./report-age";
import { unwrapTransportV1 } from "./revenue-guidance-wire";
import { GUIDANCE_BINDING_KEY, MACHINE_SCHEMA, resolveSealedMachineBindings, type MachineBindings } from "./revenue-guidance-machine";
import { sourceZh } from "./source-labels";
import { PRICE_SOURCE_LABEL } from "./market-observations";
import { buildCompanyDataReportFlex, buildCompanyDataReportMessages, validateCompanyDataReport } from "./deep-analysis";
import {
  LINE_THEME as T, altSummary, chip, detailsButton, disclosureGroups, disclosureLine, footerStyle, footnote, menuAction, packCarousels,
  productHeader, rankBadge, statTile, uiBox, uiText,
} from "./line-theme";

export const BOTTLENECK_V3_KEY = "v213:bottleneck-top20:v3";

/** B3-WIRE-01 reader options. `guidanceWireEnabled` (default off) is the only explicit opt-in to the
 * transport-v1 envelope decode at the existing present-v3 branch; it authorizes no forecast admission
 * by itself - the final forecast is always produced by the unchanged strict `parseOrderForecastV3`. */
export interface BottleneckReadOptions {
  guidanceWireEnabled?: boolean;
  guidanceMachineEnabled?: boolean;
  /** Pure parser operand ONLY. Actual ordinary loader always resolves from SAME sealed view; no override. */
  machineBindings?: MachineBindings;
}

interface Fundamentals {
  source: string; source_url: string; quarter_end: string; revenue_yoy: number | null; revenue_yoy_prev: number | null;
  /** Where revenue_yoy_prev comes from: Yahoo's own columns, or a reviewed official pair (config/official-quarterly-revenue-v1.json)
   * with its evidence in revenue_yoy_prev_source. Older documents carry neither field. */
  revenue_yoy_prev_basis?: "YAHOO" | "OFFICIAL_CURATED" | null;
  revenue_yoy_prev_source?: OfficialRevenueEvidence | null;
  gross_margin: number | null; gross_margin_change: number | null; rpo_yoy: number | null; shares_yoy: number | null;
  /** What shares_yoy measures: shares outstanding (SEC dei) or the diluted weighted average of the quarter (a fallback). */
  shares_basis?: "OUTSTANDING" | "DILUTED_WEIGHTED_AVERAGE" | null;
  /** Official revenue beside the Yahoo quarter, never replacing it: the exchange's monthly revenue for Taiwan listings
   * (TWSE/TPEx open data, period YYYY-MM) or the issuer's own interim report for Stockholm (Cision, period YYYY-Qn). */
  cross_check?: RevenueCheck | null;
}

/** A claim of an official interim report (amount in the record's unit), located by printed page, note and row. */
interface OfficialClaim {
  amount: number; start: string; end: string; period_kind: "QUARTER" | "HALF_YEAR";
  document_id: string; page_label: string; note: string; row: string;
}
interface OfficialOverlap { period_end: string; official_twd: number; yahoo_twd: number; delta_twd: number }
/** Evidence of a previous-quarter YoY from a reviewed official pair (scripts/official_quarterly_revenue.py evidence()). */
export interface OfficialRevenueEvidence {
  version: "official-quarterly-revenue-evidence-v1"; config_sha256: string; record_id: string; symbol: string;
  issuer_short_name_zh: string; applies_to_quarter_end: string; previous_quarter_end: string;
  currency: "TWD"; unit: "THOUSANDS"; unit_multiplier: 1000; scope: "CONSOLIDATED"; accounting_standard: "IAS34_TW_FSC";
  metric: "TOTAL_REVENUE";
  documents: { id: string; title: string; url: string; publisher: string; published_date: string; retrieved_at: string;
    byte_size: number; sha256: string; assurance: "CPA_REVIEWED" }[];
  previous_pair: { current: OfficialClaim; prior_year: OfficialClaim };
  current_pair: { current: OfficialClaim; prior_year: OfficialClaim };
  restatement_check: { status: string; document_id: string; half_year_claims: { current: OfficialClaim; prior_year: OfficialClaim };
    reconciliations: { period: string; half_year_amount: number; current_quarter_amount: number; derived_q1_amount: number;
      q1_claim_amount: number; difference: 0 }[] };
  cross_check: { financial_currency: "TWD"; max_overlap_delta_twd: number; max_current_yoy_ratio_delta: number;
    current_current: OfficialOverlap; current_prior_year: OfficialOverlap; previous_current: OfficialOverlap;
    current_yoy: { official_ratio: number; yahoo_ratio: number; delta_ratio: number } };
}
interface RevenueCheck {
  source_id: string; source_url: string; period: string; revenue_yoy: number | null; cumulative_yoy: number | null; currency?: string | null;
}
/** A verified corporate event behind a standalone price history shorter than the request (config/listing-lineage-v1.json,
 * scripts/listing_lineage.py): the company is not new, the security's regular-way trading is. */
interface Lineage {
  kind: "SPINOFF" | "RESUMPTION" | "IPO" | "NEW_EQUITY"; event_date: string; regular_way_start: string;
  related_entity: { name: string; symbol: string | null } | null;
  sources: { url: string; published_at: string; claims: string[]; evidence: string }[];
}
type LongTermBasis = "TWO_YEAR" | "SINCE_REGULAR_WAY" | "UNAVAILABLE";
interface Market {
  source: string; source_url: string; asof: string; ret_6m: number | null; ret_1y: number | null; cagr_2y: number | null; currency: string | null;
  /** Annualized since the verified first regular-way session, only without a two-year figure (null otherwise). */
  cagr_listed?: number | null; history_start?: string | null;
  lineage?: Lineage | { kind: "UNKNOWN" }; history_request_start?: string | null; cagr_listed_start?: string | null;
  cagr_listed_span_days?: number | null; long_term_basis?: LongTermBasis;
  /** The exchange's own close for the listing (price shards), beside the Yahoo close the returns use. */
  cross_check?: { source_id: string; source_url: string; price: number; asof: string | null; currency: string; diff: number | null };
}
interface SerenityLead { mentions: number; bullish: number; bearish: number; stance: string; latest_at: string | null; latest_url: string | null; }
/** Current orders, the consensus outlook and the price scenarios if it is realized (scripts/bottleneck_top20_v3.py). */
interface OrdersFigure {
  kind: "RPO" | "BACKLOG"; amount: number; currency: string | null; as_of: string | null; yoy: number | null; scope?: string | null;
  source: string | null; source_url: string; intake_quarter?: { amount: number; yoy?: number | null } | null;
  guidance?: { kind?: string | null; year?: number | null; amount: number; previous?: number | null } | null;
}
interface Consensus {
  revenue_fy0: number | null; revenue_fy1: number | null; revenue_growth: number | null; revenue_analysts: number | null;
  eps_fy0: number | null; eps_fy1: number | null; eps_growth: number | null; eps_analysts: number | null;
  target_mean: number | null; target_analysts: number | null; price: number | null; target_upside: number | null;
  source: string | null; source_url: string; asof: string | null;
}
type ScenarioKind = "REVENUE_CONSTANT_PS" | "EPS_CONSTANT_PE" | "ANALYST_TARGET";
/** A second, independent consensus (Nasdaq.com analyst estimates, US listings), shown beside Yahoo, never merged. */
interface SecondConsensus {
  target_mean: number | null; target_upside: number | null; target_analysts: number | null; eps_fy0: number | null;
  eps_fy1: number | null; eps_growth: number | null; eps_analysts: number | null; eps_fiscal_end: string | null;
  source: string | null; source_url: string; asof: string | null;
}
export interface Outlook {
  orders: OrdersFigure | { kind: "NOT_DISCLOSED"; reason: string | null } | null;
  consensus: Consensus | null; scenarios: { kind: ScenarioKind; change: number }[];
  consensus_second?: SecondConsensus | null;
  /** The sealed 6-month / 1-year order forecast (scripts/order_forecast.py), validated into `forecast` at parse time. */
  order_forecast?: unknown;
  /** Additive dual field v3 (Astra contract ORDERS-V3-01 section 6): revenue + order view. */
  order_forecast_v3?: unknown;
}
interface LeopoldLead { long_weight: number; status: string; }
export interface BottleneckEntry {
  rank: number; symbol: string; name: string; layer: string;
  /** Traditional Chinese name stated by the exchange, the company or Chinese Wikipedia; null when none exists. */
  name_zh?: string | null; name_zh_source?: string | null; archetype: "EXPLOSION" | "COMPOUNDER"; score: number;
  role: string; role_source: { url: string; date: string };
  /** Traditional Chinese rendering of our own role description (config/bottleneck-layers-v3.json); the English stays shown. */
  role_zh?: string | null; outlook?: Outlook | null;
  /** The validated order forecast (set by parseBottleneckV3; unavailable when missing or invalid). */
  forecast?: OrderForecast;
  parts: { layer_heat: number; capture: number; lead: number; confirmation: number; size: number; penalty: number };
  fundamentals: Fundamentals | null; market: Market; market_cap_usd: number | null;
  serenity: SerenityLead | null; leopold: LeopoldLead | null;
}
export interface IndustryEntry {
  rank: number; id: string; name_zh: string; chain: string; leopold_constraint: string; leopold_constraint_zh?: string | null; explosiveness: number;
  median_revenue_yoy: number | null; median_acceleration: number | null; median_return_6m: number | null;
  fund_13f_weight: number; serenity_heat: number;
  news: { source: string; source_url: string | null; recent_30d: number; prior_60d: number; ratio: number | null } | null;
}
export interface BottleneckV3 {
  generated_at: string; serenity_source: { url: string; latest_post_at: string | null } | null;
  leopold_filing: { period: string; filed: string; url: string } | null;
  top: BottleneckEntry[]; industries: IndustryEntry[];
  /** Sealed company data reports (SEC filers), validated per ticker when a detail is opened. */
  deep_reports: Record<string, unknown>;
}

const CHAIN_ZH: Record<string, string> = { compute: "算力", power: "電力", datacenter: "資料中心", chips_memory: "晶片與記憶體",
  network_optics: "網路與光通訊", materials: "材料與元件" };
const ZH_SOURCES = new Set(["TWSE", "TPEX", "OFFICIAL", "ZHWIKI", "WIKIDATA_LABEL"]);
const ZH_SOURCE_LABEL: Record<string, string> = { TWSE: "臺灣證交所", TPEX: "櫃買中心", OFFICIAL: "公司官方", ZHWIKI: "中文維基百科", WIKIDATA_LABEL: "維基數據" };
const str = (value: unknown, max: number): value is string => typeof value === "string" && value.length > 0 && value.length <= max;
const num = (value: unknown): value is number => typeof value === "number" && Number.isFinite(value);
const optNum = (value: unknown) => value === null || value === undefined || num(value);
const https = (value: unknown) => str(value, 400) && value.startsWith("https://");
const optStr = (value: unknown, max: number) => value === undefined || value === null || str(value, max);
const SCENARIOS = new Set(["REVENUE_CONSTANT_PS", "EPS_CONSTANT_PE", "ANALYST_TARGET"]);

/** Source -> period shape and currency, as sealed by publish_sealed_snapshot._sealed_revenue_check. */
const REVENUE_SOURCES: Record<string, { period: RegExp; currency: string }> = {
  TWSE: { period: /^[0-9]{4}-(?:0[1-9]|1[0-2])$/, currency: "TWD" },
  TPEX: { period: /^[0-9]{4}-(?:0[1-9]|1[0-2])$/, currency: "TWD" },
  CISION: { period: /^[0-9]{4}-Q[1-4]$/, currency: "SEK" },
  COMPANY_IR_KR: { period: /^[0-9]{4}-Q[1-4]$/, currency: "KRW" },
};

/** Official comparative-quarter evidence (scripts/official_quarterly_revenue.py, Astra L18-5351-CURATED-01): the
 * previous-quarter YoY computed from a reviewed official pair. Mirrors the sealer: exact shapes, admitted issuer hosts,
 * claim periods, restatement arithmetic, recomputed overlaps and both YoYs; anything else refuses the document. */
const OFFICIAL_REVENUE_HOSTS = ["etron.com"];
const OFFICIAL_EVIDENCE_VERSION = "official-quarterly-revenue-evidence-v1";
const ISO_DAY = /^[0-9]{4}-[0-9]{2}-[0-9]{2}$/;
const ISO_UTC = /^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$/;
const LONE_SURROGATE = /[\ud800-\udbff](?![\udc00-\udfff])|(?<![\ud800-\udbff])[\udc00-\udfff]/;

/** A real calendar day 1990-2100 (the sealer's bounds), canonical YYYY-MM-DD. */
function calendarDay(value: unknown): value is string {
  if (typeof value !== "string" || !ISO_DAY.test(value)) return false;
  const year = Number(value.slice(0, 4));
  const day = Date.parse(`${value}T00:00:00Z`);
  return year >= 1990 && year <= 2100 && !Number.isNaN(day) && new Date(day).toISOString().slice(0, 10) === value;
}

/** A real UTC instant YYYY-MM-DDTHH:MM:SSZ on such a day. */
function utcInstant(value: unknown): value is string {
  return typeof value === "string" && ISO_UTC.test(value) && calendarDay(value.slice(0, 10))
    && !Number.isNaN(Date.parse(value)) && new Date(value).toISOString() === `${value.slice(0, 19)}.000Z`;
}

/** Nonblank single-line text of at most max code points, as the sealer's _text. */
function sourceText(value: unknown, max: number): value is string {
  return typeof value === "string" && value.trim().length > 0 && [...value].length <= max
    && !/[\u0000-\u001f\u007f-\u009f]/.test(value) && !LONE_SURROGATE.test(value);
}

function keysExactly(value: any, keys: string[]): boolean {
  return !!value && typeof value === "object" && !Array.isArray(value)
    && Object.keys(value).length === keys.length && keys.every(key => Object.hasOwn(value, key));
}

const positiveInt = (value: unknown): value is number => Number.isSafeInteger(value) && (value as number) > 0;

function quarterStart(end: string): string {
  return `${end.slice(0, 4)}-${String(Number(end.slice(5, 7)) - 2).padStart(2, "0")}-01`;
}

function yearEarlier(end: string): string {
  return `${Number(end.slice(0, 4)) - 1}${end.slice(4)}`;
}

function previousQuarterEnd(end: string): string | null {
  const year = end.slice(0, 4);
  return ({ "03-31": `${Number(year) - 1}-12-31`, "06-30": `${year}-03-31`, "09-30": `${year}-06-30`,
    "12-31": `${year}-09-30` } as Record<string, string>)[end.slice(5)] ?? null;
}

export function quarterLabel(end: string): string {
  return `${end.slice(0, 4)}Q${Math.floor((Number(end.slice(5, 7)) - 1) / 3) + 1}`;
}

function validCuratedRevenue(fund: any, symbol: string, generatedAt: string): boolean {
  const basis = fund.revenue_yoy_prev_basis;
  if (![undefined, null, "YAHOO", "OFFICIAL_CURATED"].includes(basis)) return false;
  const s = fund.revenue_yoy_prev_source;
  if (basis !== "OFFICIAL_CURATED") return s === undefined || s === null;
  if (!keysExactly(s, ["version", "config_sha256", "record_id", "symbol", "issuer_short_name_zh", "applies_to_quarter_end",
    "previous_quarter_end", "currency", "unit", "unit_multiplier", "scope", "accounting_standard", "metric", "documents",
    "previous_pair", "current_pair", "restatement_check", "cross_check"])) return false;
  const current = s.applies_to_quarter_end, previous = s.previous_quarter_end;
  if (s.version !== OFFICIAL_EVIDENCE_VERSION || s.symbol !== symbol || current !== fund.quarter_end
    || typeof s.config_sha256 !== "string" || !/^[0-9a-f]{64}$/.test(s.config_sha256)
    || !sourceText(s.record_id, 80) || !sourceText(s.issuer_short_name_zh, 120) || !calendarDay(current) || !utcInstant(generatedAt)
    || previousQuarterEnd(current) !== previous || s.currency !== "TWD" || s.unit !== "THOUSANDS"
    || s.unit_multiplier !== 1000 || s.scope !== "CONSOLIDATED" || s.accounting_standard !== "IAS34_TW_FSC"
    || s.metric !== "TOTAL_REVENUE") return false;
  if (!Array.isArray(s.documents) || s.documents.length < 1 || s.documents.length > 4) return false;
  const docIds = new Set<string>();
  for (const d of s.documents) {
    if (!keysExactly(d, ["id", "title", "url", "publisher", "published_date", "retrieved_at", "byte_size", "sha256", "assurance"])
      || !sourceText(d.id, 60) || docIds.has(d.id) || !sourceText(d.title, 160) || !sourceText(d.publisher, 120)
      || !sourceText(d.url, 400) || !OFFICIAL_REVENUE_HOSTS.some(host => d.url.startsWith(`https://${host}/`)) || /[?#@\s\\]/.test(d.url)
      // Published on or before the retrieval day; retrieved no later than the report that carries it.
      || !calendarDay(d.published_date) || !utcInstant(d.retrieved_at) || d.published_date > d.retrieved_at.slice(0, 10)
      || Date.parse(d.retrieved_at) > Date.parse(generatedAt)
      || !positiveInt(d.byte_size) || d.byte_size >= 1e15 || typeof d.sha256 !== "string" || !/^[0-9a-f]{64}$/.test(d.sha256)
      || d.assurance !== "CPA_REVIEWED") return false;
    docIds.add(d.id);
  }
  const claim = (c: any, kind: string, start: string, end: string) => keysExactly(c, ["amount", "start", "end", "period_kind",
    "document_id", "page_label", "note", "row"]) && positiveInt(c.amount) && c.amount < 1e15 && c.start === start && c.end === end
    && c.period_kind === kind && docIds.has(c.document_id) && sourceText(c.page_label, 60) && sourceText(c.note, 60)
    && sourceText(c.row, 60);
  const pair = (p: any, end: string) => keysExactly(p, ["current", "prior_year"])
    && claim(p.current, "QUARTER", quarterStart(end), end)
    && claim(p.prior_year, "QUARTER", quarterStart(yearEarlier(end)), yearEarlier(end));
  if (!pair(s.previous_pair, previous) || !pair(s.current_pair, current)) return false;
  const rest = s.restatement_check;
  if (!keysExactly(rest, ["status", "document_id", "half_year_claims", "reconciliations"])
    || !["06-30", "12-31"].includes(current.slice(5)) || rest.status !== `MATCHED_THROUGH_${quarterLabel(current)}`
    || !docIds.has(rest.document_id) || !keysExactly(rest.half_year_claims, ["current", "prior_year"])
    || !Array.isArray(rest.reconciliations) || rest.reconciliations.length !== 2) return false;
  const roles = [["current", current], ["prior_year", yearEarlier(current)]] as const;
  for (const [index, [role, end]] of roles.entries()) {
    const half = rest.half_year_claims[role];
    const first = s.previous_pair[role].amount, second = s.current_pair[role].amount;
    const row = rest.reconciliations[index];
    const earlier = previousQuarterEnd(end)!;
    if (!claim(half, "HALF_YEAR", quarterStart(earlier), end) || half.document_id !== rest.document_id
      || half.amount - second !== first || !keysExactly(row, ["period", "half_year_amount", "current_quarter_amount",
        "derived_q1_amount", "q1_claim_amount", "difference"]) || row.period !== quarterLabel(earlier)
      || row.half_year_amount !== half.amount || row.current_quarter_amount !== second || row.derived_q1_amount !== first
      || row.q1_claim_amount !== first || row.difference !== 0) return false;
  }
  // Both YoYs: the previous one is the official pair's; the current (Yahoo) one agrees with the official current pair.
  const officialCurrent = s.current_pair.current.amount / s.current_pair.prior_year.amount - 1;
  if (!num(fund.revenue_yoy_prev) || !num(fund.revenue_yoy)
    || Math.abs(fund.revenue_yoy_prev - (s.previous_pair.current.amount / s.previous_pair.prior_year.amount - 1)) > 1e-12
    || Math.abs(fund.revenue_yoy - officialCurrent) > 0.00001) return false;
  const cross = s.cross_check;
  if (!keysExactly(cross, ["financial_currency", "max_overlap_delta_twd", "max_current_yoy_ratio_delta", "current_current",
    "current_prior_year", "previous_current", "current_yoy"]) || cross.financial_currency !== "TWD"
    || cross.max_overlap_delta_twd !== 1000 || cross.max_current_yoy_ratio_delta !== 0.00001) return false;
  const overlaps = [["current_current", s.current_pair.current], ["current_prior_year", s.current_pair.prior_year],
    ["previous_current", s.previous_pair.current]] as const;
  for (const [name, official] of overlaps) {
    const row = cross[name];
    if (!keysExactly(row, ["period_end", "official_twd", "yahoo_twd", "delta_twd"]) || row.period_end !== official.end
      || row.official_twd !== official.amount * 1000 || !num(row.yahoo_twd) || row.yahoo_twd <= 0 || !num(row.delta_twd)
      || Math.abs(row.delta_twd - Math.abs(row.yahoo_twd - row.official_twd)) > 1e-6 || row.delta_twd > 1000) return false;
  }
  const yoy = cross.current_yoy;
  return keysExactly(yoy, ["official_ratio", "yahoo_ratio", "delta_ratio"]) && num(yoy.official_ratio)
    && Math.abs(yoy.official_ratio - officialCurrent) <= 1e-12 && yoy.yahoo_ratio === fund.revenue_yoy
    && num(yoy.delta_ratio) && Math.abs(yoy.delta_ratio - Math.abs(yoy.yahoo_ratio - yoy.official_ratio)) <= 1e-12
    && yoy.delta_ratio <= 0.00001;
}

function validRevenueCheck(raw: any): boolean {
  if (raw === undefined || raw === null) return true;
  const rule = typeof raw === "object" && typeof raw.source_id === "string" && Object.hasOwn(REVENUE_SOURCES, raw.source_id)
    ? REVENUE_SOURCES[raw.source_id]! : null;
  return rule !== null && https(raw.source_url) && typeof raw.period === "string" && rule.period.test(raw.period)
    && raw.currency === rule.currency && optNum(raw.revenue_yoy) && optNum(raw.cumulative_yoy) && (num(raw.revenue_yoy) || num(raw.cumulative_yoy));
}

function validPartialAnalyst(c: any, generatedAt: string): boolean {
  const count = (n: unknown) => typeof n === "number" && Number.isInteger(n) && n > 0;
  const finiteOrNull = (n: number) => Number.isFinite(n) ? n : null;
  const same = (actual: unknown, expected: number | null) => expected === null ? actual == null : num(actual) && Math.abs(actual - expected) <= 1e-10;
  if (!calendarDay(c.asof) || c.asof !== generatedAt.slice(0, 10)
    || !/^https:\/\/finance\.yahoo\.com\/quote\/[A-Za-z0-9.\-]+\/analysis$/.test(c.source_url)) return false;
  const target = num(c.target_mean) && c.target_mean > 0 && count(c.target_analysts);
  const eps = num(c.eps_fy1) && count(c.eps_analysts);
  if ((!target && (c.target_mean != null || c.target_upside != null || c.target_analysts != null))
    || (!eps && (c.eps_fy1 != null || c.eps_growth != null || c.eps_analysts != null))) return false;
  return (target || eps)
    && same(c.target_upside, target && num(c.price) && c.price > 0 ? finiteOrNull(c.target_mean / c.price - 1) : null)
    && same(c.eps_growth, eps && num(c.eps_fy0) && c.eps_fy0 > 0 && c.eps_fy1 > 0 ? finiteOrNull(c.eps_fy1 / c.eps_fy0 - 1) : null);
}

function validOutlook(raw: any, generatedAt: string): boolean {
  if (raw === undefined || raw === null) return true;
  if (typeof raw !== "object" || !Array.isArray(raw.scenarios) || raw.scenarios.length > 3
    || !raw.scenarios.every((row: any) => row && SCENARIOS.has(row.kind) && num(row.change))) return false;
  const o = raw.orders;
  const ordersOk = o === null || o === undefined
    || (o.kind === "NOT_DISCLOSED" && optStr(o.reason, 200))
    || ((o.kind === "RPO" || o.kind === "BACKLOG") && num(o.amount) && o.amount > 0 && https(o.source_url) && optStr(o.currency, 8)
      && calendarDay(o.as_of) && o.as_of <= generatedAt.slice(0, 10) && optNum(o.yoy) && optStr(o.scope, 40) && optStr(o.source, 120)
      && (o.intake_quarter === undefined || o.intake_quarter === null || (num(o.intake_quarter.amount) && optNum(o.intake_quarter.yoy)))
      && (o.guidance === undefined || o.guidance === null || (num(o.guidance.amount) && optNum(o.guidance.year) && optNum(o.guidance.previous))));
  const c = raw.consensus;
  const consensusOk = c === null || c === undefined || (typeof c === "object" && optNum(c.revenue_growth) && https(c.source_url)
    && (num(c.revenue_growth) || validPartialAnalyst(c, generatedAt))
    && ["revenue_fy0", "revenue_fy1", "revenue_analysts", "eps_fy0", "eps_fy1", "eps_growth", "eps_analysts", "target_mean",
      "target_analysts", "price", "target_upside"].every(key => optNum(c[key])) && optStr(c.source, 80) && optStr(c.asof, 12));
  if (c && c.revenue_growth == null && raw.scenarios.some((row: any) =>
    row.change !== c[({ REVENUE_CONSTANT_PS: "revenue_growth", EPS_CONSTANT_PE: "eps_growth", ANALYST_TARGET: "target_upside" } as Record<string, string>)[row.kind]!])) return false;
  const s = raw.consensus_second;
  const secondOk = s === null || s === undefined || (typeof s === "object" && https(s.source_url)
    && ["target_mean", "target_upside", "target_analysts", "eps_fy0", "eps_fy1", "eps_growth", "eps_analysts"].every(key => optNum(s[key]))
    && optStr(s.source, 80) && optStr(s.asof, 12) && optStr(s.eps_fiscal_end, 20));
  return ordersOk && consensusOk && secondOk;
}

function validEntry(raw: any, generatedAt: string): raw is BottleneckEntry {
  return raw && Number.isInteger(raw.rank) && str(raw.symbol, 16) && str(raw.name, 160) && str(raw.layer, 40)
    && (raw.name_zh === undefined || raw.name_zh === null || (str(raw.name_zh, 40) && ZH_SOURCES.has(String(raw.name_zh_source))))
    && (raw.archetype === "EXPLOSION" || raw.archetype === "COMPOUNDER") && num(raw.score) && str(raw.role, 200)
    && optStr(raw.role_zh, 200) && validOutlook(raw.outlook, generatedAt)
    && raw.role_source && https(raw.role_source.url) && str(raw.role_source.date, 20)
    && raw.parts && ["layer_heat", "capture", "lead", "confirmation", "size", "penalty"].every(key => num(raw.parts[key]))
    && (raw.fundamentals === null || (raw.fundamentals && str(raw.fundamentals.source, 80) && https(raw.fundamentals.source_url)
      && str(raw.fundamentals.quarter_end, 12) && ["revenue_yoy", "revenue_yoy_prev", "gross_margin", "gross_margin_change", "rpo_yoy", "shares_yoy"].every(key => optNum(raw.fundamentals[key]))
      && [undefined, null, "OUTSTANDING", "DILUTED_WEIGHTED_AVERAGE"].includes(raw.fundamentals.shares_basis)
      && validCuratedRevenue(raw.fundamentals, raw.symbol, generatedAt)
      && validRevenueCheck(raw.fundamentals.cross_check)))
    && raw.market && str(raw.market.source, 80) && https(raw.market.source_url) && str(raw.market.asof, 12)
    && ["ret_6m", "ret_1y", "cagr_2y", "cagr_listed"].every(key => optNum(raw.market[key])) && optNum(raw.market_cap_usd)
    && (raw.market.cross_check === undefined || (raw.market.cross_check && str(raw.market.cross_check.source_id, 40)
      && https(raw.market.cross_check.source_url) && num(raw.market.cross_check.price) && raw.market.cross_check.price > 0
      && optStr(raw.market.cross_check.asof, 30) && str(raw.market.cross_check.currency, 8) && optNum(raw.market.cross_check.diff)))
    && (raw.market.history_start === undefined || raw.market.history_start === null || str(raw.market.history_start, 12))
    && (raw.serenity === null || (raw.serenity && Number.isInteger(raw.serenity.mentions) && str(raw.serenity.stance, 12)
      && (raw.serenity.latest_url === null || https(raw.serenity.latest_url))))
    && (raw.leopold === null || (raw.leopold && num(raw.leopold.long_weight) && str(raw.leopold.status, 12)));
}

function validIndustry(raw: any): raw is IndustryEntry {
  return raw && Number.isInteger(raw.rank) && str(raw.id, 40) && str(raw.name_zh, 40) && str(raw.chain, 30)
    && str(raw.leopold_constraint, 300) && optStr(raw.leopold_constraint_zh, 300) && num(raw.explosiveness)
    && ["median_revenue_yoy", "median_acceleration", "median_return_6m"].every(key => optNum(raw[key]))
    && num(raw.fund_13f_weight) && num(raw.serenity_heat)
    && (raw.news === null || (raw.news && Number.isInteger(raw.news.recent_30d) && Number.isInteger(raw.news.prior_60d) && optNum(raw.news.ratio)));
}

/** The sealed v3 document when valid and inside the report-age bound; otherwise null. */
const LINEAGE_KINDS = new Set(["SPINOFF", "RESUMPTION", "IPO", "NEW_EQUITY"]);
const LINEAGE_CLAIMS = new Set(["kind", "event_date", "regular_way_start", "related_entity"]);
const MIN_ANNUALIZE_DAYS = 365;
const MAX_EVENT_TO_TRADING_DAYS = 60;
const TWO_YEAR_MIN_DAYS = 725;  // eligible history the two-year return needs (scripts/listing_lineage.py)
const FUTURE_TOLERANCE_DAYS = 1;
const daysBetween = (from: string, to: string) => Math.round((Date.parse(`${to}T00:00:00Z`) - Date.parse(`${from}T00:00:00Z`)) / 86_400_000);

/** A real ASCII YYYY-MM-DD date. */
function isoDay(value: unknown): value is string {
  if (typeof value !== "string" || !/^[0-9]{4}-[0-9]{2}-[0-9]{2}$/.test(value)) return false;
  const time = Date.parse(`${value}T00:00:00Z`);
  return Number.isFinite(time) && new Date(time).toISOString().slice(0, 10) === value;
}

/** An allowlisted copy of the lineage record under the sealer's rules (scripts/listing_lineage.py clean_record), or null. */
function validLineage(raw: any): Lineage | null {
  if (!raw || typeof raw !== "object" || !LINEAGE_KINDS.has(raw.kind) || !isoDay(raw.event_date) || !isoDay(raw.regular_way_start)) return null;
  const gap = daysBetween(raw.event_date, raw.regular_way_start);
  if (gap < 0 || gap > MAX_EVENT_TO_TRADING_DAYS) return null;
  const entity = raw.related_entity;
  if (raw.kind === "IPO" ? entity !== null
    : !(entity && typeof entity === "object" && str(entity.name, 80) && (entity.symbol === null || (str(entity.symbol, 12) && /^[A-Z0-9][A-Z0-9.-]{0,11}$/.test(entity.symbol))))) return null;
  if (!Array.isArray(raw.sources) || raw.sources.length < 1 || raw.sources.length > 4) return null;
  const covered = new Set<string>();
  const sources: Lineage["sources"] = [];
  for (const source of raw.sources) {
    if (!source || typeof source !== "object" || !https(source.url) || source.url.length > 400 || !isoDay(source.published_at)
      || !str(source.evidence, 400) || !Array.isArray(source.claims) || source.claims.length === 0
      || !source.claims.every((claim: unknown) => typeof claim === "string" && LINEAGE_CLAIMS.has(claim))) return null;
    source.claims.forEach((claim: string) => covered.add(claim));
    sources.push({ url: source.url, published_at: source.published_at, claims: [...source.claims], evidence: source.evidence });
  }
  if (!["kind", "event_date", "regular_way_start"].every(claim => covered.has(claim)) || (entity && !covered.has("related_entity"))) return null;
  return { kind: raw.kind, event_date: raw.event_date, regular_way_start: raw.regular_way_start,
    related_entity: entity ? { name: entity.name, symbol: entity.symbol } : null, sources };
}

/** The long-term fields of one sealed market object under the sealer's rules (scripts/listing_lineage.py
 * clean_market_lineage): an older document WITHOUT the fields keeps only its two-year value; PRESENT but malformed or
 * contradictory metadata (dates out of order or after the report, a span that is not asof minus the start, two years
 * claimed for a younger segment) suppresses every long-term figure, the two-year one included. */
function closeLongTerm(market: Market, reportDay: string): Market {
  const two = num(market.cagr_2y) ? market.cagr_2y : null;
  const empty = { cagr_listed: null, cagr_listed_start: null, cagr_listed_span_days: null, history_request_start: null };
  if (!Object.hasOwn(market, "lineage") && !Object.hasOwn(market, "long_term_basis")) {
    return { ...market, ...empty, lineage: { kind: "UNKNOWN" }, cagr_2y: two, long_term_basis: two !== null ? "TWO_YEAR" : "UNAVAILABLE" };
  }
  const invalid: Market = { ...market, ...empty, lineage: { kind: "UNKNOWN" }, cagr_2y: null, long_term_basis: "UNAVAILABLE" };
  const raw = market.lineage as any;
  const unknown = !!raw && typeof raw === "object" && raw.kind === "UNKNOWN" && Object.keys(raw).length === 1;
  const lineage = unknown ? null : validLineage(raw);
  const asof = market.asof, requested = market.history_request_start;
  if ((!unknown && lineage === null) || !isoDay(asof) || !isoDay(requested) || daysBetween(requested, asof) < 0
    || !isoDay(reportDay) || daysBetween(reportDay, asof) > FUTURE_TOLERANCE_DAYS) return invalid;
  if (lineage && daysBetween(lineage.regular_way_start, asof) < 0) return invalid;
  const segmentStart = lineage ? lineage.regular_way_start : market.history_start;
  const listed = market.cagr_listed ?? null, since = market.cagr_listed_start ?? null, span = market.cagr_listed_span_days ?? null;
  const nothingListed = listed === null && since === null && span === null;
  const basis = market.long_term_basis;
  const consistent = basis === "TWO_YEAR" ? two !== null && nothingListed && isoDay(segmentStart) && daysBetween(segmentStart, asof) >= TWO_YEAR_MIN_DAYS
    : basis === "UNAVAILABLE" ? two === null && nothingListed
    : basis === "SINCE_REGULAR_WAY" ? two === null && lineage !== null && num(listed) && listed > -1 && since === lineage.regular_way_start
      && Number.isInteger(span) && (span as number) >= MIN_ANNUALIZE_DAYS && span === daysBetween(lineage.regular_way_start, asof)
    : false;
  if (!consistent) return invalid;
  return { ...market, lineage: lineage ?? { kind: "UNKNOWN" }, cagr_2y: two, cagr_listed: listed, cagr_listed_start: since,
    cagr_listed_span_days: span, history_request_start: requested };
}

export function parseBottleneckV3(raw: unknown, now = Date.now(), options: BottleneckReadOptions = {}): BottleneckV3 | null {
  if (!raw || typeof raw !== "object") return null;
  const doc = raw as any;
  if (doc.schema !== "v213-bottleneck-top20-v3-sealed" || !str(doc.generated_at, 30) || !v213ReportAgeFresh([doc.generated_at], now)) return null;
  if (!Array.isArray(doc.top) || doc.top.length < 10 || doc.top.length > 20 || !doc.top.every((entry: any) => validEntry(entry, doc.generated_at))) return null;
  if (!doc.top.every((entry: BottleneckEntry, index: number) => entry.rank === index + 1)) return null;
  if (!Array.isArray(doc.industries) || doc.industries.length < 3 || doc.industries.length > 20 || !doc.industries.every(validIndustry)) return null;
  const serenity = doc.serenity_source && https(doc.serenity_source.url) ? { url: doc.serenity_source.url, latest_post_at: doc.serenity_source.latest_post_at ?? null } : null;
  const leopold = doc.leopold_filing && https(doc.leopold_filing.url) ? doc.leopold_filing : null;
  const deep = doc.deep_reports && typeof doc.deep_reports === "object" && !Array.isArray(doc.deep_reports) ? doc.deep_reports : {};
  const reportDay = doc.generated_at.slice(0, 10);
  const top = doc.top.map((entry: BottleneckEntry) => ({ ...entry, market: closeLongTerm(entry.market, reportDay),
    forecast: parseOutlookForecast(entry.outlook, reportDay, entry.symbol, doc.generated_at, options) }));
  return { generated_at: doc.generated_at, serenity_source: serenity, leopold_filing: leopold, top, industries: doc.industries, deep_reports: deep };
}

export async function loadBottleneckV3(view: PublicSnapshotView, options: BottleneckReadOptions = {}): Promise<BottleneckV3 | null> {
  if (view.integrity !== "sealed") return null;
  if (options.guidanceMachineEnabled === true) {
    if (view.kind !== "snapshot" || !view.hasSealedObject?.(BOTTLENECK_V3_KEY) || !view.hasSealedObject?.(GUIDANCE_BINDING_KEY)) return null;
    const [report, binding] = await Promise.all([view.text([BOTTLENECK_V3_KEY]), view.text([GUIDANCE_BINDING_KEY])]);
    if (report === null || binding === null) return null;
    const selected = resolveSealedMachineBindings(report, binding);
    if (selected === null) return null; // no second latest/KV read/legacy single object or packet-chosen expected data
    try { return parseBottleneckV3(JSON.parse(report), Date.now(), {...options, machineBindings: selected}); }
    catch { return null; }
  }
  return parseBottleneckV3(await view.json<unknown>([BOTTLENECK_V3_KEY]), Date.now(), options);
}

const pct = (value: number | null | undefined, digits = 1) => value === null || value === undefined ? "未揭露" : `${value >= 0 ? "+" : ""}${(value * 100).toFixed(digits)}%`;
const pp = (value: number | null | undefined) => value === null || value === undefined ? "未揭露" : `${value >= 0 ? "+" : ""}${(value * 100).toFixed(1)}個百分點`;
const cap = (value: number | null | undefined) => value === null || value === undefined ? "未揭露" : value >= 1e12 ? `US$${(value / 1e12).toFixed(2)}T` : value >= 1e9 ? `US$${(value / 1e9).toFixed(1)}B` : `US$${(value / 1e6).toFixed(0)}M`;
/** Revenue acceleration only when both growth figures are present. */
const accelOf = (fund: Fundamentals) => num(fund.revenue_yoy) && num(fund.revenue_yoy_prev) ? fund.revenue_yoy - fund.revenue_yoy_prev : null;
const day = (value: string | null | undefined) => (value ?? "").slice(0, 10) || "未揭露";
/** SEC filing heat (last 30 days against the prior 60-day pace); the sealed ratio is optional. */
const newsRatio = (news: IndustryEntry["news"] | undefined) => {
  const ratio = news?.ratio;
  return ratio === null || ratio === undefined ? "未取得" : `${ratio.toFixed(2)}x`;
};

function money(amount: number, currency: string | null | undefined): string {
  const unit = (currency ?? "").toUpperCase();
  if (unit === "USD") return amount >= 1e12 ? `US$${(amount / 1e12).toFixed(2)}T` : amount >= 1e9 ? `US$${(amount / 1e9).toFixed(1)}B` : `US$${(amount / 1e6).toFixed(0)}M`;
  const label = unit || "（幣別未載明）";
  return amount >= 1e12 ? `${(amount / 1e12).toFixed(2)}兆 ${label}` : amount >= 1e8 ? `${(amount / 1e8).toFixed(1)}億 ${label}` : `${Math.round(amount).toLocaleString("en-US")} ${label}`;
}

const SCENARIO_LABEL: Record<ScenarioKind, string> = { REVENUE_CONSTANT_PS: "營收實現·市銷率不變", EPS_CONSTANT_PE: "EPS實現·本益比不變", ANALYST_TARGET: "分析師目標價" };
/** Fewer analysts than this: the Top20 card lists no price scenario and the detail marks it as thin. */
const MIN_ANALYSTS = 3;
const SCENARIO_NOTE = "分析師共識情境＝本財年→下一財年共識成長，套用目前股價與估值倍數的算術推算；市場若已反映部分成長，實際漲幅較小。非預測、非投資建議。";

/** "目前訂單": SEC remaining performance obligations or the company's own order backlog, else why none is shown. */
const ORDER_STOCK_MAX_AGE_DAYS = 200; // same source-state ceiling as order_forecast.py
function ordersAreCurrent(o: Outlook["orders"], reportDay: string): boolean {
  return !!o && o.kind !== "NOT_DISCLOSED" && calendarDay(o.as_of)
    && daysBetween(o.as_of, reportDay) >= 0 && daysBetween(o.as_of, reportDay) <= ORDER_STOCK_MAX_AGE_DAYS;
}
function currentOrders(outlook: Outlook | null | undefined, filer: boolean, reportDay: string): string {
  const o = outlook?.orders;
  if (!o) return filer ? "目前訂單：最新 10-Q／10-K 未申報剩餘履約義務（RPO）。" : "目前訂單：非 SEC 定期申報公司，未取得公司公布的在手訂單。";
  if (o.kind === "NOT_DISCLOSED") return `目前訂單：未揭露${o.reason ? `（${o.reason}）` : ""}。`;
  const label = o.kind === "RPO" ? "剩餘履約義務（RPO，已簽約未認列）" : `在手訂單${o.scope ? `（${o.scope}）` : ""}`;
  const yoy = o.yoy === null || o.yoy === undefined ? "" : `，年增 ${pct(o.yoy, 0)}`;
  if (!ordersAreCurrent(o, reportDay)) return `歷史披露（${day(o.as_of)}；已過期，不作目前訂單／預測）：${label} ${money(o.amount, o.currency)}。`;
  return `目前訂單：${label} ${money(o.amount, o.currency)}（${day(o.as_of)}${yoy}）。`;
}

/** The company's annual new-order guidance when it is exactly that (kind ANNUAL_NEW_ORDERS, an integer year, a finite
 * positive amount); any other guidance is withheld everywhere, never relabelled as new orders. */
function newOrderGuidance(orders: OrdersFigure | null | undefined): NonNullable<OrdersFigure["guidance"]> | null {
  const guidance = orders && orders.kind === "BACKLOG" ? orders.guidance : null;
  return guidance && guidance.kind === "ANNUAL_NEW_ORDERS" && Number.isInteger(guidance.year) && num(guidance.amount) && guidance.amount > 0
    && Number.isFinite(guidance.amount * 1e3) ? guidance : null;
}

/** "未來預估": the company's own order guidance and new orders where published, and the analyst consensus revenue
 * (an estimate of revenue, not of orders). */
function futureOutlook(outlook: Outlook | null | undefined, reportDay: string): string[] {
  const lines: string[] = [];
  const o = outlook?.orders;
  if (o && o.kind !== "NOT_DISCLOSED" && ordersAreCurrent(o, reportDay)) {
    if (o.intake_quarter) lines.push(`最新一季新接訂單 ${money(o.intake_quarter.amount, o.currency)}${o.intake_quarter.yoy === null || o.intake_quarter.yoy === undefined ? "" : `（年增 ${pct(o.intake_quarter.yoy, 0)}）`}。`);
    const guidance = newOrderGuidance(o);
    if (guidance) lines.push(`公司指引：${guidance.year} 年新接訂單 ${money(guidance.amount, o.currency)}${num(guidance.previous) && guidance.previous > 0 ? `（原 ${money(guidance.previous, o.currency)}）` : ""}。`);
  }
  const c = outlook?.consensus;
  const s = outlook?.consensus_second;
  if (s) {
    const parts = [s.target_mean != null ? `平均目標價 ${s.target_mean}${s.target_upside != null ? `（${pct(s.target_upside, 0)}` : "（"}${s.target_analysts ? `，${s.target_analysts} 位）` : "）"}` : "",
      s.eps_fy1 != null ? `${s.eps_fiscal_end || "下一財年"} EPS ${s.eps_fy1}${s.eps_growth != null ? `（${pct(s.eps_growth, 1)}` : "（"}${s.eps_analysts ? `，${s.eps_analysts} 位）` : "）"}` : ""].filter(Boolean);
    lines.push(`第二來源（${sourceZh(s.source)}）：${parts.join("；")}。`);
    const yahooTarget = (outlook?.scenarios ?? []).find(row => row.kind === "ANALYST_TARGET")?.change;
    if (yahooTarget != null && s.target_upside != null && Math.abs(yahooTarget - s.target_upside) > 0.15) {
      lines.push(`兩家來源目標價差距大（Yahoo ${pct(yahooTarget, 0)}／Nasdaq ${pct(s.target_upside, 0)}），請審慎參考。`);
    }
  }
  if (!c || c.revenue_growth == null) {
    lines.push("分析師營收共識：未取得。");
    if (c?.eps_fy1 != null) lines.push(`分析師 EPS 共識（非訂單）：下一財年 ${c.eps_fy1}（${c.eps_analysts} 位）${c.eps_growth != null ? `，成長 ${pct(c.eps_growth, 1)}` : "；未具備可比正值，未推算成長"}。`);
    if (c?.target_mean != null) lines.push(`分析師平均目標價（非訂單）：${c.target_mean}（${c.target_analysts} 位）。`);
  }
  else lines.push(`分析師營收共識（非訂單）：下一財年營收 ${pct(c.revenue_growth, 1)}${c.revenue_analysts ? `（${c.revenue_analysts} 位）` : ""}`
    + `${c.eps_growth === null || c.eps_growth === undefined ? "" : `；EPS ${pct(c.eps_growth, 1)}${c.eps_analysts ? `（${c.eps_analysts} 位）` : ""}`}。`);
  return lines;
}

function scenarioCount(outlook: Outlook | null | undefined, kind: ScenarioKind): number {
  const c = outlook?.consensus;
  return (kind === "ANALYST_TARGET" ? c?.target_analysts : kind === "EPS_CONSTANT_PE" ? c?.eps_analysts : c?.revenue_analysts) ?? 0;
}
function scenarioSample(outlook: Outlook | null | undefined, kind: ScenarioKind): string {
  const count = scenarioCount(outlook, kind);
  return count < MIN_ANALYSTS ? `僅 ${count} 位分析師，參考性低（樣本不足）` : `${count} 位分析師`;
}
function compactScenarioText(outlook: Outlook | null | undefined): string {
  const all = outlook?.scenarios ?? [];
  const rows = all.filter(row => scenarioCount(outlook, row.kind) >= MIN_ANALYSTS);
  return "分析師共識情境（非訂單）：" + (rows.length ? rows.map(row => `${SCENARIO_LABEL[row.kind]} ${pct(row.change, 0)}`).join("、")
    : all.length ? "分析師樣本不足，不列推算。" : "無可計算的正值基礎或分析師共識，不列推算。");
}

/** Price change if the consensus is realized at unchanged valuation multiples, and the mean analyst target. */
function scenarioBlocks(outlook: Outlook | null | undefined, compact: boolean): unknown[] {
  const c = outlook?.consensus;
  const allRows = outlook?.scenarios ?? [];
  const countFor = (kind: ScenarioKind) => (kind === "ANALYST_TARGET" ? c?.target_analysts : kind === "EPS_CONSTANT_PE" ? c?.eps_analysts : c?.revenue_analysts) ?? 0;
  const rows = compact ? allRows.filter(row => countFor(row.kind) >= MIN_ANALYSTS) : allRows;
  if (!c || allRows.length === 0) return [uiText("分析師共識情境（非訂單）：無分析師共識可推算。", "xs", T.ink)];
  const analystsFor = (kind: ScenarioKind) => (kind === "ANALYST_TARGET" ? c.target_analysts : kind === "EPS_CONSTANT_PE" ? c.eps_analysts : c.revenue_analysts) ?? 0;
  const analysts = Math.min(...allRows.map(row => analystsFor(row.kind)));
  if (compact && rows.length === 0) return [uiText(`分析師共識情境（非訂單）：分析師樣本不足（${analysts} 位），不列推算。`, "xs", T.ink)];
  const sub = (kind: ScenarioKind) => kind === "ANALYST_TARGET" ? (c.target_analysts ? `${c.target_analysts} 位` : undefined)
    : kind === "EPS_CONSTANT_PE" ? (c.eps_analysts ? `${c.eps_analysts} 位` : undefined) : (c.revenue_analysts ? `${c.revenue_analysts} 位` : undefined);
  return [
    uiText("分析師共識情境（非訂單）", "xxs", T.ink, { weight: "bold" }),
    uiBox(rows.map(row => statTile(SCENARIO_LABEL[row.kind], pct(row.change, 0), undefined, compact ? undefined : sub(row.kind))), { layout: "horizontal", spacing: "sm" }),
    ...(analysts < MIN_ANALYSTS ? [uiText(`僅 ${analysts} 位分析師，參考性低。`, "xxs", T.negative)] : []),
  ];
}

/** "交易所收盤交叉比對：<exchange> <price> <currency>（<date>），與 Yahoo 差 <diff>" beside the card's Yahoo price line. */
function exchangeCheck(check: NonNullable<Market["cross_check"]>): string {
  const diff = check.diff === undefined ? "（未取得可比較差異）" : check.diff === null ? "（幣別單位不同，不比較）" : `，與 Yahoo 差 ${check.diff >= 0 ? "+" : ""}${(check.diff * 100).toFixed(2)}%`;
  return `交易所收盤交叉比對：${PRICE_SOURCE_LABEL[check.source_id] ?? check.source_id} ${check.price} ${check.currency}（${check.asof ?? "日期未載明"}）${diff}`;
}

const OFFICIAL_SOURCE_LABEL: Record<string, string> = { ...ZH_SOURCE_LABEL, CISION: "Cision（發行公司法規公告）", COMPANY_IR_KR: "公司 IR 財報" };
/** Beside the Yahoo quarter, never differenced: "官方月營收：櫃買中心 2026-08 單月年增 +525%，1–8 月累計年增 +489%"
 * (a different period) or "公司財報公告：Cision（發行公司法規公告） 2026-Q2 營收年增 -12%". */
function revenueCheck(check: RevenueCheck): string {
  if (/Q[1-4]$/.test(check.period)) {
    const yoy = check.revenue_yoy === null || check.revenue_yoy === undefined ? "未揭露" : pct(check.revenue_yoy, 0);
    return `公司財報公告：${OFFICIAL_SOURCE_LABEL[check.source_id.toUpperCase()] ?? check.source_id} ${check.period} 營收年增 ${yoy}`;
  }
  const month = Number(check.period.slice(5, 7));
  const parts = [
    ...(check.revenue_yoy === null || check.revenue_yoy === undefined ? [] : [`單月年增 ${pct(check.revenue_yoy, 0)}`]),
    ...(check.cumulative_yoy === null || check.cumulative_yoy === undefined ? [] : [`${month === 1 ? "1 月" : `1–${month} 月`}累計年增 ${pct(check.cumulative_yoy, 0)}`]),
  ];
  return `官方月營收：${OFFICIAL_SOURCE_LABEL[check.source_id.toUpperCase()] ?? check.source_id} ${check.period} ${parts.join("，")}`;
}

function layerName(doc: BottleneckV3, id: string): string {
  return doc.industries.find(industry => industry.id === id)?.name_zh ?? id;
}

/** "中文名（來源）" or the explicit statement that no stated Chinese name exists (never a translation). */
export function chineseName(entry: Pick<BottleneckEntry, "name_zh" | "name_zh_source">): string {
  return entry.name_zh ? entry.name_zh : "無公認中文名";
}

/** The verified corporate event, in one line (never "new company"): a spin-off, a trading resumption, an IPO or new equity. */
function lineageEvent(lineage: Lineage): string {
  const entity = lineage.related_entity;
  const named = entity ? `${entity.name}${entity.symbol ? `（${entity.symbol}）` : ""}` : "";
  switch (lineage.kind) {
    case "SPINOFF": return `${lineage.event_date} 自 ${named}分拆；${lineage.regular_way_start} 起正常交易`;
    case "RESUMPTION": return `${lineage.regular_way_start} 恢復交易（前身 ${named}）`;
    case "IPO": return `${lineage.event_date} IPO；${lineage.regular_way_start} 起交易`;
    case "NEW_EQUITY": return `${lineage.event_date} 重整完成，${lineage.regular_way_start} 起新股交易（舊股 ${entity?.symbol ?? entity?.name ?? ""} 已註銷）`;
  }
}

/** The one long-term figure on every card and in every form (operator 2026-09-27: Sandisk is not a new company): the
 * 2-year CAGR; a verified spin-off, resumption, IPO or new equity without two years of its own prices says so and shows
 * the annualized return since its first regular-way session (at least one year); an unverified short history says only
 * that the price data are insufficient. The event line appears whenever the lineage is verified, with its sources. */
function longTerm(market: Market): { value: string; sub: string | undefined; event: string | null; sources: string[] } {
  const lineage = market.lineage && market.lineage.kind !== "UNKNOWN" ? market.lineage as Lineage : null;
  const event = lineage ? lineageEvent(lineage) : null;
  const sources = lineage ? lineage.sources.map(source => `${source.published_at} ${source.url}`) : [];
  if (market.long_term_basis === "TWO_YEAR" && market.cagr_2y !== null) return { value: pct(market.cagr_2y, 0), sub: undefined, event, sources };
  if (lineage && market.long_term_basis === "SINCE_REGULAR_WAY") {
    return { value: "獨立交易價格未滿2年", event, sources,
      sub: `${market.cagr_listed_start}–${market.asof} ${lineage.kind === "RESUMPTION" ? "恢復交易" : "正常交易"}以來年化 ${pct(market.cagr_listed ?? null, 0)}（非2年）` };
  }
  if (lineage) return { value: "獨立交易價格未滿2年", sub: "正常交易未滿1年或缺首日價格，不年化", event, sources };
  return { value: "2年價格資料不足", sub: market.history_start ? `可得價格自 ${day(market.history_start)}；上市沿革未核實` : "上市沿革未核實", event, sources };
}

interface OrderView { as_of: string; form: string; filed: string; coverage: Record<string, number | null>; floor: Record<string, number | null> }

/** Signed-order coverage from the sealed SEC company report (RPO on the disclosed recognition schedule). */
function ordersOf(doc: BottleneckV3, symbol: string): { orders: OrderView | null; rpoYoy: number | null; rpoPeriod: string | null; filer: boolean } {
  const raw = Object.hasOwn(doc.deep_reports, symbol) ? doc.deep_reports[symbol] as any : undefined;
  if (!raw || typeof raw !== "object") return { orders: null, rpoYoy: null, rpoPeriod: null, filer: false };
  const kpi = Array.isArray(raw.kpis) ? raw.kpis.find((k: any) => k && k.label === "RPO 年增") : undefined;
  const rpoYoy = kpi && num(kpi.value) ? kpi.value / 100 : null;
  const o = raw.orders;
  const horizons = ["m6", "m12", "m24"];
  const orders = o && str(o.as_of, 12) && str(o.form, 12) && str(o.filed, 12) && o.coverage_pct && o.floor_growth_pct
    && horizons.every(key => optNum(o.coverage_pct[key]) && optNum(o.floor_growth_pct[key]))
    ? { as_of: o.as_of, form: o.form, filed: o.filed, coverage: o.coverage_pct, floor: o.floor_growth_pct } : null;
  return { orders, rpoYoy, rpoPeriod: kpi && str(kpi.period, 20) ? kpi.period : null, filer: true };
}

/** Signed-order revenue floors on the disclosed recognition schedule (sealed SEC report), when there is one. */
function orderFloor(doc: BottleneckV3, entry: BottleneckEntry): unknown[] {
  const { orders, rpoYoy, rpoPeriod, filer } = ordersOf(doc, entry.symbol);
  if (orders) {
    const tile = (label: string, key: string) => {
      const coverage = orders.coverage[key];
      const floor = orders.floor[key];
      return statTile(label, floor !== null && floor !== undefined ? `≥${floor >= 0 ? "+" : ""}${floor.toFixed(0)}%` : "需新訂單", undefined,
        coverage === null || coverage === undefined ? "未揭露" : `已簽約覆蓋 ${coverage.toFixed(0)}%`);
    };
    return [
      uiText("已簽約訂單可支撐的營收成長（RPO 認列時程）", "xxs", T.ink, { weight: "bold" }),
      uiBox([tile("6個月", "m6"), tile("1年", "m12"), tile("2年", "m24")], { layout: "horizontal", spacing: "sm" }),
      footnote(`${orders.form}（${orders.filed}）揭露的認列時程，RPO 基準日 ${orders.as_of}；＝該期間將認列之已簽約金額÷目前營收水準−1。僅指營收，不是股價下限；未計新訂單、取消或遞延。`),
    ];
  }
  if (!filer) return entry.outlook?.orders ? [] : [uiText("非 SEC 定期申報公司：無剩餘履約義務（RPO）認列時程，不推估訂單實現金額。", "xxs", T.muted)];
  return [uiText(rpoYoy !== null ? `RPO 年增 ${pct(rpoYoy, 0)}（${rpoPeriod ?? "最新季"}）；最新財報未揭露認列時程，不推估6個月／1年／2年實現金額。`
    : "最新 10-Q／10-K 未申報 RPO 認列時程。", "xxs", T.muted)];
}

/** The current-orders tile of every Top20 card: [label, value, sub]. The future order block follows it (outlookForecast). */
export function outlookTiles(doc: BottleneckV3, entry: BottleneckEntry): [string, string, string][] {
  const outlook = entry.outlook;
  const o = outlook?.orders;
  const secFiler = ordersOf(doc, entry.symbol).filer || entry.fundamentals?.source === "SEC EDGAR XBRL companyfacts";
  const orders: [string, string, string] = !o ? ["現有訂單", "未揭露", secFiler ? "未申報 RPO" : "公司未公布"]
    : o.kind === "NOT_DISCLOSED" ? ["現有訂單", "未揭露", "公司未公布"]
    : !ordersAreCurrent(o, doc.generated_at.slice(0, 10)) ? ["歷史披露（已過期）", money(o.amount, o.currency), `${day(o.as_of)}；不作目前訂單／預測`]
    : ["現有訂單", money(o.amount, o.currency), `${o.kind === "RPO" ? "RPO" : "在手"} ${day(o.as_of)}${o.yoy === null || o.yoy === undefined ? "" : ` 年增${pct(o.yoy, 0)}`}`];
  return [orders, ...proxyTile(doc, entry)];
}

/** V13 Phase A: while the current-orders tile says 未揭露 (no orders at all, or the company has not published any), a second tile
 * shows the reported revenue momentum - the sealed latest-quarter YoY and its acceleration - labelled as a proxy and never as
 * orders. It never replaces or edits the 現有訂單 tile; it fails closed to 未揭露 on a missing or faulty YoY or an old quarter. */
const PROXY_LABEL = "營收動能（代理）";
export const PROXY_FOOTNOTE = "營收動能是已報營收的年增與加速度，只是需求的間接參考；不是訂單、不是在手訂單、不是預測。";
const PROXY_MAX_AGE_DAYS = 200;
const PROXY_YOY_FAULT = 3;
export function proxyTile(doc: BottleneckV3, entry: BottleneckEntry): [string, string, string][] {
  const o = entry.outlook?.orders;
  if (o && o.kind !== "NOT_DISCLOSED" && ordersAreCurrent(o, doc.generated_at.slice(0, 10))) return [];
  const fund = entry.fundamentals;
  const reportDay = doc.generated_at.slice(0, 10);
  const age = fund && /^[0-9]{4}-[0-9]{2}-[0-9]{2}$/.test(fund.quarter_end ?? "")
    ? Math.round((Date.parse(`${reportDay}T00:00:00Z`) - Date.parse(`${fund.quarter_end}T00:00:00Z`)) / 86_400_000) : null;
  if (!fund || !num(fund.revenue_yoy) || age === null || age < 0 || age > PROXY_MAX_AGE_DAYS || Math.abs(fund.revenue_yoy) > PROXY_YOY_FAULT) {
    return [[PROXY_LABEL, "未揭露", "非訂單"]];
  }
  const accel = accelOf(fund);
  const accelText = accel === null ? "" : `｜加速 ${accel >= 0 ? "+" : "-"}${Math.abs(accel * 100).toFixed(0)}pp`;
  return [[PROXY_LABEL, `年增 ${pct(fund.revenue_yoy, 0)}`, `非訂單${accelText}｜季末 ${fund.quarter_end}`]];
}

/** The detail text contains the proxy tile and full footnote. Top20 keeps the proxy value and its 非訂單 sub-line together;
 * the lean fallback preserves both, while the detail retains complete values and source. */
function proxyDetailLines(doc: BottleneckV3, entry: BottleneckEntry): string[] {
  const tiles = proxyTile(doc, entry);
  return tiles.length === 0 ? [] : [...tiles.map(([label, value, sub]) => `${label}：${value}（${sub}）`), PROXY_FOOTNOTE];
}

/** The future order block of every Top20 card, line by line ([text, heading]): 半年 and 1年 realization rows with their
 * windows, the conditional price rows, the data dates and later disclosures (Astra contract ORDERS-V2-01). */
export function outlookForecast(doc: BottleneckV3, entry: BottleneckEntry): [string, boolean][] {
  return forecastCard(forecastOf(doc, entry), money, historyOf(doc, entry));
}

/** Reader order (Astra contract ORDERS-V3-01 section 6):
 * If order_forecast_v3 is present, validate v3 (including null, wrong version, stale/unavailable and malformed cases).
 * Never use v3 || v2. Only genuine absence permits the existing v2/v1 parser. */
function parseOutlookForecast(outlook: Outlook | null | undefined, reportDay: string, symbol: string, generatedAt?: string, options: BottleneckReadOptions = {}): OrderForecast {
  if (outlook && Object.prototype.hasOwnProperty.call(outlook, "order_forecast_v3")) {
    let rawV3 = (outlook as any).order_forecast_v3;
    if (rawV3 && typeof rawV3 === "object" && rawV3.schema === MACHINE_SCHEMA) {
      if (options.guidanceMachineEnabled === true)
        return parseOrderForecastV3Machine(rawV3, reportDay, symbol, generatedAt, (outlook as any).order_forecast, options.machineBindings);
      return parseOrderForecastV3(rawV3, reportDay, symbol, generatedAt, (outlook as any).order_forecast); // false stays strict, no v2 fallback
    }
    if (options.guidanceMachineEnabled === true && options.machineBindings?.issuers[symbol]?.disposition !== "CURATED")
      return parseOrderForecastV3Machine(rawV3, reportDay, symbol, generatedAt, (outlook as any).order_forecast, options.machineBindings);
    if (options.guidanceWireEnabled === true) rawV3 = unwrapTransportV1(rawV3);
    return parseOrderForecastV3(rawV3, reportDay, symbol, generatedAt, (outlook as any).order_forecast);
  }
  if (options.guidanceMachineEnabled === true && options.machineBindings?.issuers[symbol]?.disposition !== "CURATED")
    return parseOrderForecastV3Machine(null, reportDay, symbol, generatedAt, outlook?.order_forecast, options.machineBindings);
  return parseOrderForecast(outlook?.order_forecast, reportDay, symbol, generatedAt);
}

/** V13: the history-model view of an entry (null unless its revenue state passed the fail-closed eligibility list). */
function historyOf(doc: BottleneckV3, entry: BottleneckEntry): HistoryView | null {
  return historyViewOf(forecastOf(doc, entry), entry.fundamentals, doc.generated_at.slice(0, 10));
}

/** An entry's validated forecast (a parsed document always has one; a hand-built entry reads as unavailable). */
function forecastOf(doc: BottleneckV3, entry: BottleneckEntry): OrderForecast {
  return entry.forecast ?? parseOutlookForecast(entry.outlook, doc.generated_at.slice(0, 10), entry.symbol, doc.generated_at);
}

/** Where a previous-quarter YoY from an official pair comes from (the current quarter stays Yahoo's). */
function officialPrevious(fund: Fundamentals | null | undefined): { label: string; url: string } | null {
  const s = fund?.revenue_yoy_prev_basis === "OFFICIAL_CURATED" ? fund.revenue_yoy_prev_source : null;
  if (!s) return null;
  const claim = s.previous_pair.current;
  const url = s.documents.find(d => d.id === claim.document_id)?.url ?? "";
  return { url, label: `前一季年增來源：${s.issuer_short_name_zh}官方合併季報（${quarterLabel(claim.end)}／${quarterLabel(s.previous_pair.prior_year.end)}，`
    + `附註${claim.note} p.${claim.page_label}），已核對同基準` };
}

/** V20: forecast-card rows ([text, heading]) as short card bullets under their bold headings. Rows that carry a figure or a
 * price scenario come first, then freshness warnings and later-disclosure notices (kept verbatim), then the rest; `max`
 * rows at most. URL lines and long derivations stay in the text edition. A long figure row keeps its "label：figure（source
 * class" head: the inline attribution (consensus, non-official) is a source label and is never cut. */
const COMPACT_ROW_MAX = 44;
function compactForecastRow(text: string): string {
  if (Array.from(text).length <= COMPACT_ROW_MAX) return text;
  if (/警示|期後|更新/.test(text)) return text;
  const colon = text.indexOf("：");
  if (colon < 0) return text.split(/[；。]/)[0]!;
  const open = text.indexOf("（", colon);
  if (open < 0) return text.split(/[；。]/)[0]!;
  let depth = 0;
  for (let index = open; index < text.length; index += 1) {
    const ch = text[index]!;
    if (ch === "（") depth += 1;
    else if (ch === "）") depth -= 1;
    else if (ch === "；" && depth === 1) return `${text.slice(0, index)}）`;
  }
  return text;
}
export function forecastBullets(lines: readonly [string, boolean][], max = 10): { text: string; heading: boolean }[] {
  const indexed = lines.map(([text, heading], index) => ({ text, heading, index })).filter(row => row.heading || !/https?:\/\//.test(row.text));
  const rank = (text: string) => Array.from(text).length <= COMPACT_ROW_MAX || /警示|期後|更新|模型推估|US\$|→|\d%/.test(text) ? 0 : 1;
  const keep = new Set(indexed.filter(row => !row.heading).sort((x, y) => rank(x.text) - rank(y.text) || x.index - y.index).slice(0, max).map(row => row.index));
  const out: { text: string; heading: boolean }[] = [];
  indexed.forEach((row, at) => {
    if (row.heading) {
      const next = indexed.slice(at + 1).find(item => item.heading || keep.has(item.index));
      if (next && !next.heading) out.push({ text: row.text, heading: true });
    } else if (keep.has(row.index)) out.push({ text: compactForecastRow(row.text), heading: false });
  });
  return out;
}
/** The two sealed horizon rows immediately under an existing forecast heading. */
function forecastRowsAfter(lines: readonly [string, boolean][], heading: string): string[] {
  const start = lines.findIndex(([text, isHeading]) => isHeading && text === heading);
  if (start < 0) return [];
  const rows: string[] = [];
  for (const [text, isHeading] of lines.slice(start + 1)) {
    if (isHeading) break;
    rows.push(text);
    if (rows.length === 2) break;
  }
  return rows;
}
/** Wraps required forecast content without clipping it; Flex body lines stay within the V25 40-code-point limit. */
function wrapForecastRow(text: string, splitQualifier = false): string {
  const characters = Array.from(text);
  if (characters.length <= 40) return text;
  const lines: string[] = [];
  let start = 0;
  while (start < characters.length) {
    let end = Math.min(start + 40, characters.length);
    if (end < characters.length) {
      const colon = characters.indexOf("：");
      const open = start === 0 && colon >= 0 ? characters.indexOf("（", colon + 1) : -1;
      if (splitQualifier && open > colon && open > start && open < end) end = open;
      else {
        for (let at = end; at > start + 20; at -= 1) {
          if ("｜；，、。： ".includes(characters[at - 1]!)) { end = at; break; }
        }
      }
    }
    lines.push(characters.slice(start, end).join(""));
    start = end;
  }
  return lines.join("\n");
}
function forecastDisplayRows(prefix: string, rows: readonly string[], splitQualifier = false): string {
  const shown = rows.length ? rows : ["未揭露"];
  return shown.map((row, index) => wrapForecastRow(`${index === 0 ? `${prefix}｜` : ""}${row.replaceAll("（非今日起）", "")}`, splitQualifier)).join("\n");
}


/** One-glance summary; complete sealed detail remains behind the text button. */
function companyBubble(doc: BottleneckV3, entry: BottleneckEntry, lean = false) {
  const fund = entry.fundamentals;
  const long = longTerm(entry.market);
  const official = officialPrevious(fund);
  const [ordersTile, ...proxyTiles] = outlookTiles(doc, entry);
  const forecast = forecastOf(doc, entry);
  const warning = forecast.m6.warning ?? forecast.m12.warning;
  const consensusV3 = forecast.version === 3 && forecast.revenueBasis === "CONSENSUS";
  const history = historyOf(doc, entry);
  // Keep the independent historical revenue estimate and its inputs beside its figures on the Top20 bubble.
  // Closing disclosure carries shared "非今日起"/"非目標價" once; avoid repeating them per history horizon.
  const historyRows = historyBlockLines(history, money).map(row => row.replaceAll("非今日起", "").replaceAll("非目標價", ""));
  const forecastLines = forecastCard(forecast, money, history);
  const orderHeading = forecast.version === 3 ? "訂單認列／營收推估" : "未來訂單預估";
  const scenarioHeading = forecast.version === 3 ? "營收實現後股價情境" : "訂單實現後股價情境";
  const consensusAttribution = "分析師共識為第三方分析師估計平均，非公司財測、非官方";
  const forecastWarningRows = [...new Set([
    ...(forecast.revenueBasis === "CONSENSUS" && forecast.consensusNote ? [forecast.consensusNote] : []),
    ...(warning?.text ? [warning.text] : []),
  ])];
  if (forecast.revenueBasis === "CONSENSUS" && entry.outlook?.consensus
    && !forecastWarningRows.some(row => row.includes(consensusAttribution))) forecastWarningRows.unshift(consensusAttribution);
  const cleanForecastRow = (row: string) => {
    let clean = row;
    for (const warningText of forecastWarningRows) clean = clean.replaceAll(warningText, "");
    return clean.replace(/（非今日起）|非今日起報酬|非今日起|非目標價|非投資建議|非保證|不自動下單/g, "")
      .replace(/(?:[，、；]\s*){2,}/g, "；")
      .replace(/^[，、；]+\s*|\s*[，、；]+$/g, "")
      .trim();
  };
  const orderRows = forecastRowsAfter(forecastLines, orderHeading).map(cleanForecastRow).filter(Boolean);
  const rawCondition = forecastLines.find(([text]) => text.startsWith("條件情境："))?.[0]
    ?? (forecast.version === 3 ? "條件情境：營收依上述推估實現，P/S與股數不變；以最新已報四季為基準，非目標價、非今日起報酬"
      : "條件情境：營收達預計認列額，P/S與股數不變；非目標價、非今日起報酬");
  const condition = cleanForecastRow(rawCondition.replace("條件情境：", "")
    .replace(/[，、；]\s*非目標價[，、；]\s*非今日起報酬.*$/u, "")
    .replace("營收依上述推估實現", "營收推估達成")
    .replace("營收達預計認列額", "營收達認列額")
    .replace("以最新已報四季為基準", "基準：最新已報四季"));
  const scenarioRows = forecastRowsAfter(forecastLines, scenarioHeading)
    .filter(row => !row.startsWith("條件情境："))
    .map(cleanForecastRow).filter(Boolean);
  const closingDisclosure = [
    condition,
    ...(forecast.version === 2 ? ["認列依公司披露時程"] : []),
    forecast.version === 3 ? "營收推估非保證" : "預計認列非保證",
    "非今日起",
    "非目標價、非投資建議、不自動下單",
  ].join("；");
  return {
    type: "bubble", size: "mega",
    header: productHeader(`瓶頸 TOP20 · ${entry.archetype === "EXPLOSION" ? "爆發型" : "核心複利型"}`, `${entry.symbol}｜${chineseName(entry)}`.slice(0, 60), [
      ...(!lean ? [uiText(entry.name.slice(0, 80), "xxs", T.headerMuted)] : []),
      ...(entry.name_zh ? [uiText(`中文名來源：${ZH_SOURCE_LABEL[entry.name_zh_source ?? ""] ?? "來源已核對"}`, "xxs", T.headerMuted)] : []),
      uiBox([rankBadge(entry.rank, entry.rank === 1), chip(layerName(doc, entry.layer)), chip(`${entry.score.toFixed(1)} 分`)], { layout: "horizontal", spacing: "sm" }),
    ]),
    body: uiBox([
      uiBox([
        uiText(`${pct(fund?.revenue_yoy ?? null, 0)}營收年增｜毛利變化 ${ppShort(fund?.gross_margin_change)}`, "xs", T.ink),
        uiText(wrapForecastRow(fund
          ? `財報：${sourceZh(fund.source)}${official ? "（前一季採官方合併季報）" : ""}，季末 ${fund.quarter_end}`
          : "財報：未取得可比季度"), "xs", T.ink),
        ...(official ? [uiText(wrapForecastRow(official.label), "xs", T.ink)] : []),
      ], { spacing: "xs" }),
      uiBox([
        uiText(wrapForecastRow(`半年 ${pct(entry.market.ret_6m, 0)}｜2年年化 ${long.value}｜市值${cap(entry.market_cap_usd)}${long.sub ? `｜${long.sub}` : ""}${long.event ? `｜上市沿革 ${long.event}` : ""}｜股價來源 ${sourceZh(entry.market.source)}，至 ${entry.market.asof}`), "xs", T.ink),
        uiText(wrapForecastRow(`${ordersTile![0]}：${ordersTile![1]}｜${entry.role_zh ?? entry.role}｜訂單：${ordersTile![2]}`), "xs", T.ink),
        ...proxyTiles.map(([label, value, sub]) => {
          const detail = sub.replace(/^非訂單(?:｜)?/, "").replace(/｜季末 \d{4}-\d{2}-\d{2}$/, "");
          const displayLabel = label.replace("營收動能（代理）", "營收代理");
          return uiText(wrapForecastRow(`${displayLabel}：${value}${detail ? `｜${detail}` : ""}｜非訂單`), "xs", T.ink);
        }),
      ], { spacing: "xs" }),
      uiBox([
        uiText([
          forecastDisplayRows("未來訂單", orderRows, true),
          ...forecastWarningRows.map(row => wrapForecastRow(row)),
          ...historyRows.map(row => wrapForecastRow(row)),
        ].filter(Boolean).join("\n"), "xs", T.ink),
        uiText(forecastDisplayRows("股價情境", scenarioRows), "xs", T.ink),
        ...(consensusV3 ? [uiBox(scenarioBlocks(entry.outlook, true), { spacing: "xs" })] : []),
      ], { spacing: "xs" }),
    ], { paddingAll: "lg", spacing: "sm" }),
    footer: uiBox([
      ...disclosureGroups([
        { label: "營收交叉", text: fund?.cross_check ? revenueCheck(fund.cross_check) : "未取得官方營收交叉比對" },
        { label: "行情交叉", text: entry.market.cross_check ? exchangeCheck(entry.market.cross_check) : "未取得交易所收盤交叉比對" },
        { label: "情境", text: closingDisclosure },
      ]),
      detailsButton(`${entry.symbol} 瓶頸詳情`, `瓶頸詳情 ${entry.symbol}`),
      ...(!lean ? [menuAction("產業爆發榜", "產業爆發榜")] : []),
    ], footerStyle),
  };
}



/** The long-term figure in one line of text: value, its explanation and the verified event. */
function longTermText(market: Market): string {
  const long = longTerm(market);
  return `${long.value}${long.sub ? `（${long.sub}）` : ""}${long.event ? `；${long.event}` : ""}`;
}

export function buildBottleneckTop20Messages(doc: BottleneckV3, style: "flex" | "text"): LineOutboundMessage[] {
  if (style === "text") {
    const lines = doc.top.map(entry => `${entry.rank}. ${entry.symbol} ${chineseName(entry)}（${entry.name}）｜${layerName(doc, entry.layer)}｜${entry.score.toFixed(1)}分｜營收年增 ${pct(entry.fundamentals?.revenue_yoy ?? null, 0)}｜6個月 ${pct(entry.market.ret_6m, 0)}｜2年年化 ${longTermText(entry.market)}｜${currentOrders(entry.outlook, ordersOf(doc, entry.symbol).filer || entry.fundamentals?.source === "SEC EDGAR XBRL companyfacts", doc.generated_at.slice(0, 10))}｜${forecastText(forecastOf(doc, entry), money)}${entry.outlook?.consensus?.revenue_growth == null && entry.outlook?.consensus ? `｜${compactScenarioText(entry.outlook)}` : ""}`);
    // Paginated into at most five messages of whole entries (never an entry cut away by a length limit).
    const blocks = [`瓶頸爆發 TOP20（v3，產生 ${doc.generated_at}）`,
      "排序：層級熱度＋公司捕獲＋社群與機構線索＋市場確認＋爆發性；2年年化報酬為負者排除。分拆、恢復交易、IPO 或重整新股不足2年者，改用已核實正常交易首日以來年化（至少1年，非2年）；沿革未核實且價格不足2年者不列入。非投資建議。",
      ...lines, "輸入「瓶頸詳情 代號」看逐項數據與來源；「產業爆發榜」看 Leopold 邏輯產業排序。"];
    const pages: string[] = [];
    for (const block of blocks.map(text => text.slice(0, 1200))) {
      const last = pages[pages.length - 1];
      if (last !== undefined && last.length + 1 + block.length <= 4900) pages[pages.length - 1] = `${last}\n${block}`;
      else pages.push(block);
    }
    const messages: LineOutboundMessage[] = pages.slice(0, 5).map(text => ({ type: "text", text }));
    assertLineMessages(messages);
    return messages;
  }
  const alt = (index: number, total: number) => `瓶頸爆發 TOP20（${index + 1}/${total}）`;
  try {
    return packCarousels(doc.top.map(entry => companyBubble(doc, entry)), alt);
  } catch (error) {
    if (!(error instanceof Error) || !["LINE_MESSAGE_COUNT_INVALID", "LINE_FLEX_CAROUSEL_TOO_LARGE", "LINE_FLEX_BUBBLE_INVALID"].includes(error.message)) throw error;
    // Retry only LINE packing limits; keep every F1/F2 field, dropping optional English names and the industry button.
    return packCarousels(doc.top.map(entry => companyBubble(doc, entry, true)), alt);
  }
}

const gmText = (value: number | null | undefined) => value === null || value === undefined ? "未揭露" : `${(value * 100).toFixed(1)}%`;
/** The basis of a share-count change when it is not shares outstanding. */
const sharesBasis = (fund: Fundamentals) => fund.shares_yoy !== null && fund.shares_basis === "DILUTED_WEIGHTED_AVERAGE" ? "稀釋加權平均股數" : undefined;
const ppShort = (value: number | null | undefined) => value === null || value === undefined ? "未揭露" : `${value >= 0 ? "+" : ""}${(value * 100).toFixed(1)}pp`;
/** V20: the detail of a Top20 entry as four compact pages (financials and market, orders and scenarios, order basis, sources)
 * instead of one 70-text card. Full source URLs and narrative remain in the text edition one tap away
 * (`瓶頸詳情 <代號> 文字`). */
function detailBubbles(doc: BottleneckV3, entry: BottleneckEntry) {
  const fund = entry.fundamentals;
  const long = longTerm(entry.market);
  const accel = fund ? ppShort(accelOf(fund)) : "未揭露";
  const official = officialPrevious(fund);
  const { orders, filer } = ordersOf(doc, entry.symbol);
  const outlook = entry.outlook;
  const forecast = forecastOf(doc, entry);
  const warning = forecast.m6.warning ?? forecast.m12.warning;
  const kind = entry.archetype === "EXPLOSION" ? "爆發型（市值<US$10B）" : "核心複利型";
  const buttons = [detailsButton(`${entry.symbol} 完整數據與網址`, `瓶頸詳情 ${entry.symbol} 文字`), menuAction("回瓶頸 TOP20", "TOP20")];
  const page = (eyebrow: string, body: unknown[], notes: { label: string; text: string }[]) => ({
    type: "bubble", size: "mega",
    header: productHeader(`瓶頸詳情 · #${entry.rank} · ${eyebrow}`, `${entry.symbol}｜${chineseName(entry)}`.slice(0, 60), [
      uiText(entry.name.slice(0, 80), "xxs", T.headerMuted),
      uiBox([chip(layerName(doc, entry.layer)), chip(`${entry.score.toFixed(1)} 分`), chip(entry.archetype === "EXPLOSION" ? "爆發型" : "核心複利型")], { layout: "horizontal", spacing: "sm" }),
    ]),
    body: uiBox(body, { paddingAll: "lg", spacing: "sm" }),
    footer: uiBox([...disclosureGroups(notes), ...buttons], footerStyle),
  });

  const financeRows = fund ? [
    `營收 ${pct(fund.revenue_yoy, 0)}｜前季 ${pct(fund.revenue_yoy_prev, 0)}｜加速 ${accel}`,
    `毛利 ${gmText(fund.gross_margin)}（${ppShort(fund.gross_margin_change)}）｜RPO ${pct(fund.rpo_yoy, 0)}｜股數 ${pct(fund.shares_yoy, 1)}${sharesBasis(fund) ? `（${sharesBasis(fund)}）` : ""}`,
    `6個月 ${pct(entry.market.ret_6m, 0)}｜2年年化 ${long.value}｜市值 ${cap(entry.market_cap_usd)}`,
    `財報來源：${sourceZh(fund.source)}；季末 ${fund.quarter_end}`,
    ...(official ? [official.label] : []),
    `股價來源：${sourceZh(entry.market.source)}；至 ${entry.market.asof}`,
    ...(long.sub ? [`長期口徑：${long.sub}`] : []),
    ...(long.event ? [`上市沿革：${long.event}`] : []),
    "非投資建議；不自動下單",
  ] : [
    `財報未取得可比季度；6個月 ${pct(entry.market.ret_6m, 0)}｜2年年化 ${long.value}｜市值 ${cap(entry.market_cap_usd)}`,
    `股價來源：${sourceZh(entry.market.source)}；至 ${entry.market.asof}`,
    ...(long.sub ? [`長期口徑：${long.sub}`] : []),
    ...(long.event ? [`上市沿革：${long.event}`] : []),
    "非投資建議；不自動下單",
  ];
  const financeSummary = financeRows.map(row => wrapForecastRow(row)).join("\n");
  const page1 = page(`財報與市場 · ${kind}`, [
    uiText(financeSummary, "xs", T.ink),
  ], [
    { label: "營收交叉", text: fund?.cross_check ? revenueCheck(fund.cross_check) : "未取得官方營收交叉比對" },
    { label: "行情交叉", text: entry.market.cross_check ? exchangeCheck(entry.market.cross_check) : "未取得交易所收盤交叉比對" },
    ...(!official ? [{ label: "前季", text: "沿用可比來源" }] : []),
  ]);

  const [ordersTile] = outlookTiles(doc, entry);
  const floorValue = (value: number | null | undefined) => value === null || value === undefined ? "需新訂單" : `≥${value >= 0 ? "+" : ""}${value.toFixed(0)}%`;
  const coverageValue = (value: number | null | undefined) => value === null || value === undefined ? "未揭露" : `${value.toFixed(0)}%`;
  const floorSummary = orders ? [
    "已簽約營收成長支撐（RPO認列時程）",
    `6個月 ${floorValue(orders.floor.m6)}（覆蓋 ${coverageValue(orders.coverage.m6)}）｜1年 ${floorValue(orders.floor.m12)}（覆蓋 ${coverageValue(orders.coverage.m12)}）`,
    `2年 ${floorValue(orders.floor.m24)}（覆蓋 ${coverageValue(orders.coverage.m24)}）`,
    "計算：分期已簽約認列金額÷目前營收−1",
  ].map(row => wrapForecastRow(row)).join("\n") : "RPO 認列時程未披露";
  const scenario = outlook?.scenarios?.[0];
  const scenarioSummary = scenario && outlook?.consensus
    ? "分析師共識情境：詳見文字版"
    : "分析師共識情境：無資料可推算";
  const forecastConsensusLabel = [forecast.m6.basis_label, forecast.m12.basis_label]
    .find((label): label is string => typeof label === "string" && label.startsWith("分析師共識（非公司財測、非官方）"));
  const consensusAnalysts = outlook?.consensus?.revenue_analysts;
  const consensusSourceLine = forecastConsensusLabel ?? (scenario && outlook?.consensus
    ? `分析師共識（非公司財測、非官方）｜${outlook.consensus.source ?? "來源未揭露"}，${consensusAnalysts == null ? "數量未揭露" : `${consensusAnalysts} 位`}分析師，截至 ${(outlook.consensus.asof ?? "").slice(0, 10) || "日期未揭露"}`
    : "");
  const floorNote = orders ? `RPO ${orders.form}（申報 ${orders.filed}），認列基準 ${orders.as_of}；營收下限非股價下限，未計新訂單、取消或遞延`
    : !filer ? "非 SEC 定期申報公司，無 RPO 認列時程" : "最新財報未揭露認列時程，不推估實現金額";
  const stockRecognitionDates = orders
    ? `股價 ${entry.market.asof}；認列基準 ${orders.as_of}；申報 ${orders.filed}`
    : `股價 ${entry.market.asof}；RPO 認列基準未揭露`;
  const page2 = page("訂單與情境", [
    uiText(wrapForecastRow(`${ordersTile![0]}：${ordersTile![1]}｜${ordersTile![2]}`), "xs", T.ink),
    uiText(floorSummary, "xs", T.ink),
    uiText([stockRecognitionDates, scenarioSummary, consensusSourceLine].filter(Boolean).map(row => wrapForecastRow(row)).join("\n"), "xs", T.ink),
  ], [
    { label: "來源", text: orders ? `${orders.form}，申報 ${orders.filed}` : floorNote },
    { label: "認列", text: orders ? floorNote : "無可用 RPO 認列時程；不推估實現金額" },
    { label: "用途", text: "非投資建議；不自動下單" },
  ]);
  const evidenceLabel = orders ? `RPO ${orders.form}｜申報 ${orders.filed}｜認列基準 ${orders.as_of}`
    : !filer ? "非 SEC 定期申報公司；無 RPO 認列時程" : "最新申報未揭露 RPO 認列時程";
  const orderSource = outlook?.orders && outlook.orders.kind !== "NOT_DISCLOSED"
    ? `${sourceZh(outlook.orders.source)}；${outlook.orders.as_of ?? "日期未揭露"}`
    : "未披露訂單來源";
  const forecastWarnings = [
    forecast.consensusNote,
    forecast.version === 3 && (forecast.revenueReason === "INVALID" || forecast.m6.reason === "INVALID" || forecast.m12.reason === "INVALID") ? "資料未通過驗證" : "",
    warning ? `${forecast.revenueBasis === "CONSENSUS" ? "共識時效警示" : "時效警示"}：${warning.text}` : "",
  ].filter(Boolean).join("；");
  const page3 = page("訂單依據", [
    uiText(wrapForecastRow(evidenceLabel), "xs", T.ink),
    uiText(wrapForecastRow(`訂單來源：${orderSource}`), "xs", T.ink),
    uiText(forecastWarnings ? wrapForecastRow(forecastWarnings) : "逐項條件、期後披露與預估見文字版", "xs", T.ink),
  ], [
    { label: "預計", text: orders || forecast.version === 2 ? "認列非保證；未計新訂單、取消或遞延" : "沒有可驗證的認列預估" },
    { label: "情境", text: "分析師共識為算術推算；非預測" },
    { label: "用途", text: "非投資建議；不自動下單" },
  ]);

  const page4 = page("來源", [
    uiText(wrapForecastRow(`財報：${fund ? `${sourceZh(fund.source)}；季末 ${fund.quarter_end}` : "未取得可比季度"}`), "xs", T.ink),
    ...(official ? [uiText(wrapForecastRow(official.label), "xs", T.ink)] : []),
    uiText(wrapForecastRow(`股價：${sourceZh(entry.market.source)}；至 ${entry.market.asof}`), "xs", T.ink),
    uiText(`交叉比對、沿革與完整網址見文字版${entry.name_zh ? `；中文名來源：${ZH_SOURCE_LABEL[entry.name_zh_source ?? ""] ?? "來源已核對"}` : ""}`, "xs", T.ink),
  ], [
    { label: "財報", text: fund ? sourceZh(fund.source) : "未取得可比季度；不以估計替代" },
    { label: "行情", text: `${sourceZh(entry.market.source)}；${entry.market.asof}` },
    { label: "連結", text: "完整來源網址及逐項交叉比對見文字版" },
  ]);
  return [page1, page2, page3, page4];
}

function detailText(doc: BottleneckV3, entry: BottleneckEntry): string {
  const fund = entry.fundamentals;
  const long = longTerm(entry.market);
  const outlook = entry.outlook;
  const scenarios = (outlook?.scenarios ?? []).map(row => `${SCENARIO_LABEL[row.kind]} ${pct(row.change, 0)}（${scenarioSample(outlook, row.kind)}）`).join("、");
  const official = officialPrevious(fund);
  return [
    `【瓶頸詳情｜#${entry.rank} ${entry.symbol} ${chineseName(entry)}（${entry.name}）】`,
    `型態：${entry.archetype === "EXPLOSION" ? "瓶頸爆發型（市值<US$10B）" : "核心複利型"}；市值 ${cap(entry.market_cap_usd)}`,
    `瓶頸位置：${entry.role_zh ?? entry.role}${entry.role_zh ? `（原文：${entry.role}）` : ""}`,
    `分數構成：層級熱度 ${entry.parts.layer_heat}｜公司捕獲 ${entry.parts.capture}｜市場確認 ${entry.parts.confirmation}｜爆發性 ${entry.parts.size}${entry.parts.penalty !== 0 ? `｜條件式稀釋／融資扣分 -${entry.parts.penalty}` : ""}`,
    fund ? `財報（${sourceZh(fund.source)}${official ? "；前一季年增採官方合併季報" : ""}，季末 ${fund.quarter_end}）：營收年增 ${pct(fund.revenue_yoy)}，前一季年增 ${pct(fund.revenue_yoy_prev)}（加速度 ${pp(accelOf(fund))}）；毛利率 ${gmText(fund.gross_margin)}（年變化 ${pp(fund.gross_margin_change)}）；剩餘履約義務年增 ${pct(fund.rpo_yoy)}；股數年增 ${pct(fund.shares_yoy)}${sharesBasis(fund) ? `（${sharesBasis(fund)}）` : ""}\n來源：${fund.source_url}${official ? `\n${official.label}\n前一季來源：${official.url}` : ""}` : "財報：未取得可比季度（不以估計替代）。",
    ...(fund?.cross_check ? [`${revenueCheck(fund.cross_check)}\n來源：${fund.cross_check.source_url}`] : []),
    `股價（${sourceZh(entry.market.source)}，至 ${entry.market.asof}）：6個月 ${pct(entry.market.ret_6m)}、2年年化 ${long.value}${long.sub ? `（${long.sub}）` : ""}\n來源：${entry.market.source_url}`,
    ...(long.event ? [`上市沿革：${long.event}\n沿革來源：${long.sources.join("；")}`] : []),
    ...(entry.market.cross_check ? [exchangeCheck(entry.market.cross_check)] : []),
    currentOrders(outlook, ordersOf(doc, entry.symbol).filer || fund?.source === "SEC EDGAR XBRL companyfacts", doc.generated_at.slice(0, 10))
      + (outlook?.orders && outlook.orders.kind !== "NOT_DISCLOSED" ? `\n來源：${outlook.orders.source_url}` : ""),
    ...proxyDetailLines(doc, entry),
    ...forecastLines(forecastOf(doc, entry), money, historyOf(doc, entry)),
    ...futureOutlook(outlook, doc.generated_at.slice(0, 10)),
    scenarios ? `分析師共識情境（非訂單）：${scenarios}${outlook?.consensus ? `\n來源：${outlook.consensus.source_url}` : ""}` : "分析師共識情境（非訂單）：無分析師共識可推算。",
    `${SCENARIO_NOTE}不自動下單。`,
  ].join("\n");
}

/** Whole lines into pages of at most `limit` UTF-16 units (a continuation page says so); nothing is cut away. */
function pagesAtLineBoundary(text: string, limit: number): string[] {
  const pages: string[] = [];
  let page = "";
  for (const line of text.split("\n")) {
    const next = page ? `${page}\n${line}` : line;
    if (next.length <= limit) { page = next; continue; }
    if (page) pages.push(page);
    page = `（續）${line}`;
    while (page.length > limit) { pages.push(page.slice(0, limit)); page = `（續）${page.slice(limit)}`; }
  }
  if (page) pages.push(page);
  return pages;
}

/** The Top20 entry for a typed symbol: exact, else the one listing whose symbol before the venue suffix matches
 * ("SIVE" -> SIVE.ST, "5351" -> 5351.TWO); two listings sharing a base stay unresolved. */
export function findBottleneckEntry(doc: BottleneckV3, symbol: string): BottleneckEntry | undefined {
  const wanted = symbol.toUpperCase();
  const exact = doc.top.find(item => item.symbol.toUpperCase() === wanted);
  if (exact) return exact;
  const byBase = doc.top.filter(item => item.symbol.toUpperCase().split(".")[0] === wanted);
  return byBase.length === 1 ? byBase[0] : undefined;
}

export function buildBottleneckDetail(doc: BottleneckV3, symbol: string, style: "flex" | "text" = "text"): LineOutboundMessage[] | string {
  const entry = findBottleneckEntry(doc, symbol);
  if (!entry) return `「${symbol}」不在本輪瓶頸爆發 TOP20（產生 ${doc.generated_at}）。`;
  // The detail card first; then the company data report (SEC filings, business profile, thesis phase, order
  // realization) when one is sealed.
  const raw = Object.hasOwn(doc.deep_reports, entry.symbol) ? doc.deep_reports[entry.symbol] : undefined;
  const report = raw ? validateCompanyDataReport(raw, entry.symbol) : null;
  const detail: LineOutboundMessage[] = style === "flex"
    ? packCarousels(detailBubbles(doc, entry), () => altSummary({ topic: `${entry.symbol} ${chineseName(entry)} 瓶頸詳情`,
      status: `第 ${entry.rank} 名，財報、訂單、依據與來源 4 頁`, next: "左右滑動；完整網址按文字版" }))
    : pagesAtLineBoundary(detailText(doc, entry), 4900).map(text => ({ type: "text" as const, text }));
  const reportMessages = report ? (style === "flex" ? buildCompanyDataReportFlex(report, doc.generated_at, ["回瓶頸 TOP20", "TOP20"])
    : buildCompanyDataReportMessages(report, doc.generated_at)) : [];
  const messages = [...detail, ...reportMessages].slice(0, 5);
  assertLineMessages(messages);
  return messages;
}

function industryBubble(doc: BottleneckV3, industry: IndustryEntry) {
  const acceleration = industry.median_acceleration === null || industry.median_acceleration === undefined ? "未揭露"
    : `${industry.median_acceleration >= 0 ? "+" : ""}${(industry.median_acceleration * 100).toFixed(0)}pp`;
  const secHeat = industry.news?.ratio === null || industry.news?.ratio === undefined ? "SEC申報未取得" : "SEC申報熱度已納入";
  return {
    type: "bubble", size: "mega",
    header: productHeader(`產業爆發榜 · Leopold 因果鏈：${CHAIN_ZH[industry.chain] ?? industry.chain}`, industry.name_zh, [
      uiBox([rankBadge(industry.rank, industry.rank === 1), chip(`爆發力 ${industry.explosiveness.toFixed(1)}`)], { layout: "horizontal", spacing: "sm" }),
    ]),
    body: uiBox([
      uiText("綁定限制與成員：產業爆發榜 文字", "xs", T.ink),
      uiText(`營收中位 ${pct(industry.median_revenue_yoy, 0)}｜加速 ${acceleration}`, "xs", T.ink),
      uiText(`6個月 ${pct(industry.median_return_6m, 0)}｜${secHeat}`, "xs", T.ink),
    ], { paddingAll: "lg", spacing: "sm" }),
    footer: uiBox([disclosureLine(["非投資建議"]),
      menuAction("瓶頸爆發 TOP20", "TOP20"), menuAction("回功能選單", "選單")], footerStyle),
  };
}

export function buildIndustryExplosionMessages(doc: BottleneckV3, style: "flex" | "text"): LineOutboundMessage[] {
  if (style === "text") {
    const lines = doc.industries.map(industry => {
      const members = doc.top.filter(entry => entry.layer === industry.id).map(entry => entry.name_zh ? `${entry.symbol} ${entry.name_zh}` : entry.symbol);
      return [
        `${industry.rank}. ${industry.name_zh}｜爆發力 ${industry.explosiveness.toFixed(1)}｜營收年增中位數 ${pct(industry.median_revenue_yoy, 0)}｜加速度中位數 ${industry.median_acceleration === null || industry.median_acceleration === undefined ? "未揭露" : `${industry.median_acceleration >= 0 ? "+" : ""}${(industry.median_acceleration * 100).toFixed(0)}pp`}｜SEC申報熱度 ${newsRatio(industry.news)}｜6個月股價中位數 ${pct(industry.median_return_6m, 0)}`,
        `Leopold 綁定限制：${industry.leopold_constraint_zh ?? industry.leopold_constraint}\n原文引句：「${industry.leopold_constraint}」`,
        `SEC申報統計：近30天 ${industry.news?.recent_30d ?? "未取得"} 件｜前60天 ${industry.news?.prior_60d ?? "未取得"} 件｜近30天／前60天比率 ${industry.news?.ratio === null || industry.news?.ratio === undefined ? "未取得" : `${industry.news.ratio.toFixed(2)}x`}`,
        `本輪 TOP20 成員：${members.length ? members.join("、") : "（無）"}`,
      ].join("\n");
    });
    const messages = pagesAtLineBoundary([`產業爆發榜（Leopold 因果鏈，產生 ${doc.generated_at}）`,
      "爆發力構成：因果鏈位置35＋機構持倉權重25＋營收加速20＋SEC申報熱度10＋社群熱度10",
      ...lines, "非投資建議。"].join("\n"), 4900)
      .map(text => ({ type: "text" as const, text }));
    assertLineMessages(messages);
    return messages;
  }
  return packCarousels(doc.industries.slice(0, 10).map(industry => industryBubble(doc, industry)), (index, total) => `產業爆發榜（${index + 1}/${total}）`);
}
