/** Bottleneck-explosion Top20 v3 and the Leopold-led industry ranking (scripts/bottleneck_top20_v3.py).
 *
 * Sealed as the lazy object `v213:bottleneck-top20:v3`. Leads (Serenity posts, 13F positions) weight conviction
 * but are never shown as company facts; every figure carries its source and date. A malformed or stale document
 * (older than the report bound, report-age.ts) gives null and the caller keeps the seven-field Top20.
 */
import { forecastCard, forecastLines, forecastText, parseOrderForecast, parseOrderForecastV3, parseOrderForecastV3Machine, RPO_MEANING, type OrderForecast } from "./order-forecast";
import { historyBlockLines, historyViewOf, type HistoryView } from "./revenue-history-model";
import { TREND_CHIP, TREND_LABEL, trendBasisText, trendBlockLines, trendHorizonFor, validTrend, type TrendEstimate } from "./revenue-trend";
import { assertLineMessages, type LineOutboundMessage } from "../line-messages";
import type { PublicSnapshotView } from "./public-snapshot";
import { v213ReportAgeFresh } from "./report-age";
import { readRetainedRanking } from "./ranking-retention";
import { unwrapTransportV1 } from "./revenue-guidance-wire";
import { GUIDANCE_BINDING_KEY, MACHINE_SCHEMA, resolveSealedMachineBindings, type MachineBindings } from "./revenue-guidance-machine";
import { sourceZh } from "./source-labels";
import { statusLabelZh } from "./status-labels";
import { formatQuotePrice, formatTaipeiTimestamp, formatVisibleMoment } from "./line-formatters";
import { PRICE_SOURCE_LABEL } from "./market-observations";
import { buildCompanyDataReportFlex, buildCompanyDataReportMessages, validateCompanyDataReport } from "./deep-analysis";
import {
  LINE_THEME as T, accentHeading, accentKpiTile, altSummary, barRow, chip, detailsButton, disclosureLine, footerStyle, footnote, headerStyle, kpiTile, kvRow, menuAction, meter, packCarousels,
  productHeader, rankBadge, signColor, statTile, noticeBanner, noticeText, uiBox, uiText,
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
  /** Additive positive latest filed quarter; never an invented order or an analyst forecast. */
  revenue?: number | null; revenue_unit?: string | null;
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
  /** Underlying adjustment for a completed shareholder distribution is not independently proved. */
  return_reasons?: Partial<Record<"ret_6m" | "ret_1y" | "cagr_2y" | "cagr_listed", "DISTRIBUTION_IN_WINDOW">>;
  distribution_adjustment?: {
    status: "REVIEWED_PRIMARY_INPUTS"; source_url: string; distribution_date: string;
    related_symbol: string; shares_per_share: number; evidence_sha256: string;
    values: Partial<Record<"ret_6m" | "ret_1y" | "cagr_2y", number>>;
    method: "SHAREHOLDER_ENTITLEMENT_TOTAL_RETURN";
  };
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
interface MergerActionNote {
  target_symbol: string; acquirer_symbol: string; kind: "ALL_STOCK" | "CASH" | "MIXED"; status: "PENDING";
  exchange_ratio: number | null; cash_per_share: number | null; currency: string | null;
  expected_close: string; source_url: string;
}
interface DistributionActionNote {
  kind: "DISTRIBUTION"; status: "CLOSED"; target_market: "US"; target_symbol: string;
  distribution_date: string; related_market: "US"; related_symbol: string;
  shares_per_share: number; source_url: string; source_date: string; review_by: string | null;
}
type CorporateActionNote = MergerActionNote | DistributionActionNote;
interface CorporateActionDisplay {
  symbol: string; corporate_action?: CorporateActionNote;
  market?: Pick<Market, "distribution_adjustment">;
}
interface ExcludedCorporateAction {
  symbol: string; reason_zh: string; corporate_action: CorporateActionNote;
}
const EXCLUDED_ACTION_REASONS: Record<"PENDING" | "DISTRIBUTION", string> = {
  PENDING: "併購待完成，暫不納入排行",
  DISTRIBUTION: "尚缺可核對的一手歷史收盤價、完整配息與拆股紀錄及衍生報酬公開使用權；零股另須實際淨現金證明，跨配發權益日報酬暫不顯示。",
};
const ROTATION_NOTICE_ZH = "本輪輪動來源鏈未驗證；排行仍依既有資料更新，請人工覆核。";
interface RotationProvenanceNotice { status: "UNVERIFIED"; notice_zh: string; }
export interface BottleneckEntry {
  rank: number; symbol: string; name: string; layer: string;
  /** Traditional Chinese name stated by the exchange, the company or Chinese Wikipedia; null when none exists. */
  name_zh?: string | null; name_zh_source?: string | null; archetype: "EXPLOSION" | "COMPOUNDER"; score: number;
  role: string; role_source: { url: string; date: string };
  /** Traditional Chinese rendering of our own role description (config/bottleneck-layers-v3.json); the English stays shown. */
  role_zh?: string | null; outlook?: Outlook | null;
  /** The validated order forecast (set by parseBottleneckV3; unavailable when missing or invalid). */
  forecast?: OrderForecast;
  /** V33b: the validated TREND_YOY_V1 estimate (sealed optional field `revenue_trend`, scripts/revenue_trend.py), set by
   * parseBottleneckV3 only when it recomputes from its own quarters; absent for older documents. It applies only where
   * no existing revenue basis does (revenue-trend.ts). */
  trend?: TrendEstimate;
  parts: { layer_heat: number; capture: number; lead: number; confirmation: number; size: number; penalty: number };
  fundamentals: Fundamentals | null; market: Market; market_cap_usd: number | null;
  serenity: SerenityLead | null; leopold: LeopoldLead | null;
  /** Controlled public terms for either party. Display only; no admission or entitlement transfer. */
  corporate_action?: CorporateActionNote;
  /** Research-only hypotheses. All conditions remain unvalidated and score-neutral. */
  screen_conditions?: { state: "UNVERIFIED"; rules: {rule_id: string; label_zh: string; status: "PASS" | "FAIL" | "UNKNOWN"}[] };
  latest_event?: { published_on: string; source_url: string; headline_zh: string; status: "PRIMARY_REVIEWED" | "PRIMARY_METADATA_ONLY" };
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
  excluded_actions?: ExcludedCorporateAction[];
  rotation_provenance?: RotationProvenanceNotice;
  /** Runtime-only: derived by the verified sealed reader, never copied from wire metadata. */
  historical_retention_notice?: string;
  historical_forecasts_unavailable?: boolean;
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

function validCorporateAction(raw: unknown, symbol: string, generatedAt: string): boolean {
  if (raw === undefined) return true; // compatible with pre-merger seals
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) return false;
  const x = raw as Record<string, unknown>;
  if (x.kind === "DISTRIBUTION") {
    const fields = ["target_market", "target_symbol", "kind", "status", "distribution_date",
      "related_market", "related_symbol", "shares_per_share", "source_url", "source_date", "review_by"];
    return keysExactly(x, fields) && x.target_market === "US"
      && (x.target_symbol === symbol || x.related_symbol === symbol)
      && str(x.target_symbol, 15) && /^[A-Z0-9][A-Z0-9.-]{0,14}$/.test(x.target_symbol as string)
      && x.related_market === "US" && x.status === "CLOSED"
      && str(x.related_symbol, 15) && /^[A-Z0-9][A-Z0-9.-]{0,14}$/.test(x.related_symbol as string)
      && x.related_symbol !== x.target_symbol && num(x.shares_per_share)
      && (x.shares_per_share as number) > 0 && (x.shares_per_share as number) <= 10000
      && calendarDay(x.distribution_date) && calendarDay(x.source_date)
      && (x.source_date as string) >= (x.distribution_date as string)
      && (x.source_date as string) <= generatedAt.slice(0, 10)
      && (x.distribution_date as string) <= generatedAt.slice(0, 10)
      && (x.review_by === null || (calendarDay(x.review_by) && (x.review_by as string) >= (x.distribution_date as string)))
      && sourceText(x.source_url, 400)
      && /^https:\/\/www\.sec\.gov\/Archives\/[a-zA-Z0-9/_-]+\.[a-zA-Z0-9]+$/.test(x.source_url as string);
  }
  const keys = ["target_symbol", "acquirer_symbol", "kind", "status", "exchange_ratio", "cash_per_share", "currency", "expected_close", "source_url"];
  if (!keysExactly(x, keys) || !str(x.target_symbol, 15) || !/^[A-Z0-9][A-Z0-9.-]{0,14}$/.test(x.target_symbol as string)
    || !str(x.acquirer_symbol, 15) || !/^[A-Z0-9][A-Z0-9.-]{0,14}$/.test(x.acquirer_symbol as string)
    || x.target_symbol === x.acquirer_symbol || (x.target_symbol !== symbol && x.acquirer_symbol !== symbol)
    || x.status !== "PENDING" || !["ALL_STOCK", "CASH", "MIXED"].includes(String(x.kind))
    || !str(x.expected_close, 70) || !/^(?:20\d{2}-(?:H[12]|Q[1-4])|(?:first|second) half of calendar year 20\d{2}|20\d{2}-\d{2}-\d{2})$/.test(x.expected_close as string)
    || !https(x.source_url) || !(x.source_url as string).startsWith("https://www.sec.gov/Archives/")) return false;
  const share = num(x.exchange_ratio) && (x.exchange_ratio as number) > 0 && (x.exchange_ratio as number) <= 10000;
  const cash = num(x.cash_per_share) && (x.cash_per_share as number) > 0;
  if (x.kind === "ALL_STOCK") return share && x.cash_per_share === null && x.currency === null;
  if (x.kind === "CASH") return x.exchange_ratio === null && cash && typeof x.currency === "string" && /^[A-Z]{3}$/.test(x.currency);
  return share && cash && typeof x.currency === "string" && /^[A-Z]{3}$/.test(x.currency);
}

function corporateActionText(entry: CorporateActionDisplay): string | null {
  const deal = entry.corporate_action;
  if (!deal) return null;
  if (deal.kind === "DISTRIBUTION") {
    const terms = `${deal.distribution_date} 完成分拆：${deal.target_symbol} 每股配發 ${deal.shares_per_share.toFixed(5)} 股 ${deal.related_symbol}`;
    if (entry.symbol !== deal.target_symbol) {
      return `${terms}；${deal.related_symbol} 為配發標的，未套用 ${deal.target_symbol} 股東權益報酬`;
    }
    return `${terms}；${entry.market?.distribution_adjustment
      ? "跨事件報酬依已覆核一手權益資料計算（非交易報酬）" : "未取得完整權益調整價格，跨事件報酬不顯示"}`;
  }
  const firstHalf = /^first half of calendar year (20\d{2})$/.exec(deal.expected_close);
  const secondHalf = /^second half of calendar year (20\d{2})$/.exec(deal.expected_close);
  const expected = firstHalf ? `${firstHalf[1]} 年上半年` : secondHalf ? `${secondHalf[1]} 年下半年` : deal.expected_close;
  const terms = deal.kind === "ALL_STOCK" ? `每股換 ${deal.exchange_ratio!.toFixed(3)} 股 ${deal.acquirer_symbol}`
    : deal.kind === "CASH" ? `每股現金 ${deal.cash_per_share} ${deal.currency}`
    : `每股換 ${deal.exchange_ratio!.toFixed(3)} 股 ${deal.acquirer_symbol} 加現金 ${deal.cash_per_share} ${deal.currency}`;
  return `併購進行中：${deal.target_symbol} ${terms}，預計 ${expected}完成；收購方維持獨立評分，完成仍待審核`;
}

function corporateActionNotice(entry: CorporateActionDisplay): string | null {
  const text = corporateActionText(entry);
  if (!text) return null;
  return noticeText(entry.corporate_action?.kind === "DISTRIBUTION" ? "分拆已完成" : "併購進行中", text);
}
function corporateActionBanner(entry: BottleneckEntry): unknown[] {
  const text = corporateActionText(entry);
  if (!text) return [];
  const distribution = entry.corporate_action?.kind === "DISTRIBUTION";
  return [noticeBanner(distribution ? "info" : "caution", distribution ? "分拆已完成" : "併購進行中", text)];
}
function corporateActionSourceLabel(entry: BottleneckEntry): string {
  return entry.corporate_action?.kind === "DISTRIBUTION" ? "分拆公告來源" : "併購公告來源";
}

function validReturnReasons(market: any, action: CorporateActionNote | undefined): boolean {
  const reasons = market.return_reasons;
  if (reasons !== undefined) {
    if (!action || action.kind !== "DISTRIBUTION" || !reasons || typeof reasons !== "object" || Array.isArray(reasons)) return false;
    const keys = Object.keys(reasons);
    if (keys.length === 0 || keys.length > 4 || !keys.every(key =>
      ["ret_6m", "ret_1y", "cagr_2y", "cagr_listed"].includes(key)
        && reasons[key] === "DISTRIBUTION_IN_WINDOW" && market[key] === null)) return false;
  }
  if (!action || action.kind !== "DISTRIBUTION") return market.distribution_adjustment === undefined;
  if (!calendarDay(market.asof)) return false;
  const knownExDate = action.target_symbol === "MOD" && action.related_symbol === "THRM"
    && action.distribution_date === "2026-10-01" && action.source_date === "2026-10-01"
    && action.shares_per_share === 0.44619
    && action.source_url === "https://www.sec.gov/Archives/edgar/data/67347/000110465926112870/tm2626618d1_8k.htm";
  const elapsed = daysBetween(knownExDate ? "2026-10-02" : action.distribution_date, market.asof);
  const boundaryOffset = knownExDate ? 1 : 0; // pre-ex holders only; unknown ex-dates stay conservative
  if (market.distribution_adjustment !== undefined) {
    const proof = market.distribution_adjustment;
    if (!proof || !keysExactly(proof, ["status", "source_url", "distribution_date",
      "related_symbol", "shares_per_share", "evidence_sha256", "values", "method"])
      || proof.status !== "REVIEWED_PRIMARY_INPUTS" || proof.method !== "SHAREHOLDER_ENTITLEMENT_TOTAL_RETURN"
      || proof.source_url !== action.source_url || proof.distribution_date !== action.distribution_date
      || proof.related_symbol !== action.related_symbol || proof.shares_per_share !== action.shares_per_share
      || typeof proof.evidence_sha256 !== "string" || !/^[0-9a-f]{64}$/.test(proof.evidence_sha256)
      || !proof.values || typeof proof.values !== "object" || Array.isArray(proof.values)) return false;
    const values = proof.values;
    const allowed = ["ret_6m", "ret_1y", "cagr_2y"];
    if (!Object.keys(values).length || Object.keys(values).some(key => !allowed.includes(key))) return false;
    for (const [key, window] of [["ret_6m", 182], ["ret_1y", 365], ["cagr_2y", 730]] as const) {
      const hasProof = Object.hasOwn(values, key);
      const crossed = elapsed >= 0 && elapsed <= window - boundaryOffset;
      if (hasProof && (!crossed || !num(values[key]) || values[key]! <= -1
        || values[key]! > 1000 || market[key] !== values[key])) return false;
      if (!hasProof && crossed && market[key] !== null) return false;
    }
    return true;
  }
  if (elapsed < 0) return reasons === undefined;
  if (elapsed <= 182 - boundaryOffset && market.ret_6m !== null) return false;
  if (elapsed <= 365 - boundaryOffset && market.ret_1y !== null) return false;
  if (elapsed <= 730 - boundaryOffset && market.cagr_2y !== null) return false;
  if (reasons !== undefined) {
    for (const key of Object.keys(reasons)) {
      const maxDays = key === "ret_6m" ? 182 : key === "ret_1y" ? 365 : key === "cagr_2y" ? 730 : null;
      if (maxDays !== null && elapsed > maxDays - boundaryOffset) return false;
    }
  }
  return true;
}

const SCREEN_RULES: Record<string, string> = {
  R01_REV_GROWTH_20: "營收年增至少20%",
  R02_REV_ACCEL_10PP: "營收年增加速至少10個百分點",
  R03_GM_EXPAND_2PP: "毛利率年增至少2個百分點",
  R04_RPO_GROWTH_20: "剩餘履約義務年增至少20%",
  R05_DILUTION_BELOW_5: "同季可比股數年增不超過5%",
  R06_REL_MOMENTUM_6M: "近6個月報酬高於QQQ",
  R07_PRICE_2Y_POSITIVE: "近2年調整後價格報酬為正",
  R08_REL_MOMENTUM_SOXX_6M: "近6個月報酬高於SOXX",
  R09_MAX_DRAWDOWN_12M: "近1年最大回撤不超過35%",
  R10_ATM_MATERIAL_DILUTION: "已查證有效ATM及重大稀釋條款",
  R13_INDEPENDENT_13F_POSITION_CHANGE: "已查證獨立機構13F持股變化",
};
function validScreenConditions(raw: any): boolean {
  if (raw === undefined) return true;
  if (!raw || !keysExactly(raw, ["state", "rules"]) || raw.state !== "UNVERIFIED"
    || !Array.isArray(raw.rules) || raw.rules.length !== 11) return false;
  const seen = new Set<string>();
  return raw.rules.every((r: any) => {
    if (!r || !keysExactly(r, ["rule_id", "label_zh", "status"])
      || !Object.hasOwn(SCREEN_RULES, r.rule_id) || SCREEN_RULES[r.rule_id] !== r.label_zh
      || seen.has(r.rule_id) || !["PASS", "FAIL", "UNKNOWN"].includes(r.status)
      || ((r.rule_id.startsWith("R10_") || r.rule_id.startsWith("R13_")) && r.status !== "UNKNOWN")) return false;
    seen.add(r.rule_id); return true;
  });
}
function screenConditionsText(entry: BottleneckEntry): string {
  const passed = (entry.screen_conditions?.rules ?? []).filter(r => r.status === "PASS");
  return "符合的篩選條件（未驗證）：" + (passed.length
    ? passed.slice(0, 3).map(r => r.label_zh).join("、") + (passed.length > 3 ? "等" : "")
    : entry.screen_conditions?.rules.some(r => r.status === "FAIL") ? "已評估條件未符合；未揭露者仍為未知" : "資料不足，暫不判斷");
}
const EVENT_EXCHANGE_HOSTS: Readonly<Record<string, true>> = {
  "mops.twse.com.tw": true, "mopsov.twse.com.tw": true, "www.twse.com.tw": true, "openapi.twse.com.tw": true,
  "www.tpex.org.tw": true, "dart.fss.or.kr": true, "englishdart.fss.or.kr": true, "kind.krx.co.kr": true,
};
function validLatestEvent(raw: any, generatedAt: string): boolean {
  if (raw === undefined) return true;
  if (!raw || !keysExactly(raw, ["published_on", "source_url", "headline_zh", "status"])
    || !calendarDay(raw.published_on) || raw.published_on > generatedAt.slice(0, 10)
    || !str(raw.headline_zh, 70) || /[\r\n]/.test(raw.headline_zh)
    || !str(raw.source_url, 500) || /[\r\n]/.test(raw.source_url)) return false;
  let source: URL;
  try { source = new URL(raw.source_url); } catch { return false; }
  if (source.protocol !== "https:" || source.username || source.password || source.hash
    || (source.port && source.port !== "443")) return false;
  const sec = source.hostname === "www.sec.gov" && source.pathname.startsWith("/Archives/")
    || source.hostname === "data.sec.gov" && source.pathname.startsWith("/submissions/");
  if (!sec && EVENT_EXCHANGE_HOSTS[source.hostname] !== true) return false;
  return raw.status === "PRIMARY_REVIEWED" || raw.status === "PRIMARY_METADATA_ONLY"
    && raw.headline_zh === (sec ? "SEC 公告（內容待查）" : "交易所公告（內容待查）");
}
function validActionExclusions(raw: unknown, generatedAt: string, top: BottleneckEntry[]): boolean {
  if (raw === undefined) return true;
  if (!Array.isArray(raw) || raw.length > 30) return false;
  const seen = new Set<string>();
  for (const value of raw) {
    if (!value || typeof value !== "object" || Array.isArray(value)) return false;
    const row = value as Record<string, unknown>;
    if (!keysExactly(row, ["symbol", "reason_zh", "corporate_action"])
      || typeof row.symbol !== "string" || !/^[A-Z0-9][A-Z0-9.-]{0,14}$/.test(row.symbol)
      || !row.corporate_action || !validCorporateAction(row.corporate_action, row.symbol, generatedAt)
      || top.some(entry => entry.symbol === row.symbol) || seen.has(row.symbol)) return false;
    const note = row.corporate_action as CorporateActionNote;
    if (note.target_symbol !== row.symbol
      || row.reason_zh !== EXCLUDED_ACTION_REASONS[note.kind === "DISTRIBUTION" ? "DISTRIBUTION" : "PENDING"]) return false;
    seen.add(row.symbol);
  }
  return true;
}
function excludedActionText(row: ExcludedCorporateAction): string {
  return `${row.symbol}：${row.reason_zh}\n${corporateActionNotice(row)}\n官方來源：${row.corporate_action.source_url}`;
}
function validRotationProvenance(raw: unknown): boolean {
  if (raw === undefined) return true;
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) return false;
  const value = raw as Record<string, unknown>;
  return keysExactly(value, ["status", "notice_zh"]) && value.status === "UNVERIFIED"
    && value.notice_zh === ROTATION_NOTICE_ZH;
}
function latestEventText(entry: BottleneckEntry): string {
  const e = entry.latest_event;
  return e ? `最新事件（${e.status === "PRIMARY_METADATA_ONLY" ? "申報紀錄，內容未核" : "官方公告"}）：${e.published_on} ${e.headline_zh}`
    : "最新事件：未取得已核對之官方更新";
}
function validEntry(raw: any, generatedAt: string): raw is BottleneckEntry {
  return raw && Number.isInteger(raw.rank) && str(raw.symbol, 16) && str(raw.name, 160) && str(raw.layer, 40)
    && (raw.name_zh === undefined || raw.name_zh === null || (str(raw.name_zh, 40) && ZH_SOURCES.has(String(raw.name_zh_source))))
    && (raw.archetype === "EXPLOSION" || raw.archetype === "COMPOUNDER") && num(raw.score) && str(raw.role, 200)
    && optStr(raw.role_zh, 200) && validOutlook(raw.outlook, generatedAt)
    && validCorporateAction(raw.corporate_action, raw.symbol, generatedAt)
    && (raw.corporate_action?.kind === "DISTRIBUTION" || raw.corporate_action?.target_symbol !== raw.symbol)
    && validScreenConditions(raw.screen_conditions)
    && validLatestEvent(raw.latest_event, generatedAt)
    && raw.role_source && https(raw.role_source.url) && str(raw.role_source.date, 20)
    && raw.parts && ["layer_heat", "capture", "lead", "confirmation", "size", "penalty"].every(key => num(raw.parts[key]))
    && (raw.fundamentals === null || (raw.fundamentals && str(raw.fundamentals.source, 80) && https(raw.fundamentals.source_url)
      && str(raw.fundamentals.quarter_end, 12)
      && (raw.fundamentals.revenue == null || (num(raw.fundamentals.revenue) && raw.fundamentals.revenue > 0))
      && (raw.fundamentals.revenue_unit == null || (typeof raw.fundamentals.revenue_unit === "string" && /^[A-Z]{3}$/.test(raw.fundamentals.revenue_unit)))
      && ["revenue_yoy", "revenue_yoy_prev", "gross_margin", "gross_margin_change", "rpo_yoy", "shares_yoy"].every(key => optNum(raw.fundamentals[key]))
      && [undefined, null, "OUTSTANDING", "DILUTED_WEIGHTED_AVERAGE"].includes(raw.fundamentals.shares_basis)
      && validCuratedRevenue(raw.fundamentals, raw.symbol, generatedAt)
      && validRevenueCheck(raw.fundamentals.cross_check)))
    && raw.market && str(raw.market.source, 80) && https(raw.market.source_url) && str(raw.market.asof, 12)
    && ["ret_6m", "ret_1y", "cagr_2y", "cagr_listed"].every(key => optNum(raw.market[key])) && optNum(raw.market_cap_usd)
    && validReturnReasons(raw.market,
      raw.corporate_action?.kind === "DISTRIBUTION" && raw.corporate_action.target_symbol !== raw.symbol
        ? undefined : raw.corporate_action)
    && (raw.market.cross_check === undefined || (raw.market.cross_check && str(raw.market.cross_check.source_id, 40)
      && https(raw.market.cross_check.source_url) && num(raw.market.cross_check.price) && raw.market.cross_check.price > 0
      && optStr(raw.market.cross_check.asof, 30) && str(raw.market.cross_check.currency, 8) && optNum(raw.market.cross_check.diff)))
    && (raw.market.history_start === undefined || raw.market.history_start === null || str(raw.market.history_start, 12))
    && (raw.serenity === null || (raw.serenity && Number.isInteger(raw.serenity.mentions) && str(raw.serenity.stance, 12)
      && (raw.serenity.latest_url === null || https(raw.serenity.latest_url))))
    && (raw.leopold === null || (raw.leopold && num(raw.leopold.long_weight) && str(raw.leopold.status, 13)));
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
  if ("excluded_pending" in doc || !validActionExclusions(doc.excluded_actions, doc.generated_at, doc.top)) return null;
  if (!validRotationProvenance(doc.rotation_provenance)) return null;
  if (!Array.isArray(doc.industries) || doc.industries.length < 3 || doc.industries.length > 20 || !doc.industries.every(validIndustry)) return null;
  const serenity = doc.serenity_source && https(doc.serenity_source.url) ? { url: doc.serenity_source.url, latest_post_at: doc.serenity_source.latest_post_at ?? null } : null;
  const leopold = doc.leopold_filing && https(doc.leopold_filing.url) ? doc.leopold_filing : null;
  const deep = doc.deep_reports && typeof doc.deep_reports === "object" && !Array.isArray(doc.deep_reports) ? doc.deep_reports : {};
  const reportDay = doc.generated_at.slice(0, 10);
  const top = doc.top.map((entry: BottleneckEntry) => {
    const trend = validTrend((entry as any).revenue_trend, entry.fundamentals, reportDay);
    return { ...entry, market: closeLongTerm(entry.market, reportDay),
      forecast: parseOutlookForecast(entry.outlook, reportDay, entry.symbol, doc.generated_at, options), ...(trend ? { trend } : {}) };
  });
  return { generated_at: doc.generated_at, serenity_source: serenity, leopold_filing: leopold,
    top, industries: doc.industries, deep_reports: deep, excluded_actions: doc.excluded_actions,
    rotation_provenance: doc.rotation_provenance };
}

export async function loadBottleneckV3(view: PublicSnapshotView, options: BottleneckReadOptions = {}): Promise<BottleneckV3 | null> {
  if (view.integrity !== "sealed") return null;
  const observedAt = Date.now();
  let raw: unknown;
  let effectiveOptions = options;
  let machineUnavailable = false;
  if (options.guidanceMachineEnabled === true) {
    if (view.kind !== "snapshot" || !view.hasSealedObject?.(BOTTLENECK_V3_KEY)) return null;
    const [report, binding] = await Promise.all([view.text([BOTTLENECK_V3_KEY]), view.text([GUIDANCE_BINDING_KEY])]);
    if (report === null) return null;
    const selected = binding === null ? null : resolveSealedMachineBindings(report, binding);
    // A declared but missing/corrupt/replayed binding is broken custody, not
    // permission to downgrade that machine snapshot to historical facts.
    if (view.hasSealedObject?.(GUIDANCE_BINDING_KEY) && (binding === null || selected === null)) return null;
    machineUnavailable = selected === null;
    // A caller's bindings cannot repair missing custody or authorize an old forecast.
    effectiveOptions = { ...options, machineBindings: selected ?? undefined };
    try { raw = JSON.parse(report); } catch { return null; }
  } else raw = await view.json<unknown>([BOTTLENECK_V3_KEY]);
  const current = machineUnavailable ? null : parseBottleneckV3(raw, observedAt, effectiveOptions);
  if (current) return current;
  const retained = await readRetainedRanking(view, observedAt, options.guidanceMachineEnabled === true);
  if (!retained) return null;
  const historical = parseBottleneckV3(retained.raw, retained.parseAt, effectiveOptions);
  if (!historical) return null;
  historical.historical_retention_notice = retained.notice;
  if (options.guidanceMachineEnabled === true) {
    // Keep ranking facts, not expired machine authority or a silent legacy forecast.
    historical.historical_forecasts_unavailable = true;
    historical.historical_retention_notice += " 機器預估未延展核准；僅保留當時排行事實，不列新的訂單預估或股價情境。";
    historical.deep_reports = {};
    for (const entry of historical.top) {
      delete entry.outlook;
      delete entry.forecast;
      delete entry.trend;
    }
  }
  return historical;
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
  return `交易所收盤交叉比對：${PRICE_SOURCE_LABEL[check.source_id] ?? check.source_id} ${formatQuotePrice(check.price, check.currency)} ${check.currency}（${check.asof ?? "日期未載明"}）${diff}`;
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
  const sources = lineage ? lineage.sources.map(source => `${formatVisibleMoment(source.published_at)} ${source.url}`) : [];
  if (market.long_term_basis === "TWO_YEAR" && market.cagr_2y !== null) return { value: pct(market.cagr_2y, 0), sub: undefined, event, sources };
  if (lineage && market.long_term_basis === "SINCE_REGULAR_WAY") {
    return { value: "獨立交易價格未滿2年", event, sources,
      sub: `${market.cagr_listed_start}–${market.asof} ${lineage.kind === "RESUMPTION" ? "恢復交易" : "正常交易"}以來年化 ${pct(market.cagr_listed ?? null, 0)}（非2年）` };
  }
  if (lineage) return { value: "獨立交易價格未滿2年", sub: "正常交易未滿1年或缺首日價格，不年化", event, sources };
  if (market.return_reasons?.cagr_2y === "DISTRIBUTION_IN_WINDOW") {
    return { value: "分拆期間報酬不可比", sub: statusLabelZh("DISTRIBUTION_IN_WINDOW"), event, sources };
  }
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
  const forecast = forecastOf(doc, entry);
  const trend = trendBlockLines(entry.trend, money, forecast);
  return [...forecastCard(forecast, money, historyOf(doc, entry)), ...trend.map((text, index): [string, boolean] => [text, index === 0])];
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
  if (doc.historical_forecasts_unavailable) return null;
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

const scoreIndicator = (score: number, prefix = "") => uiBox([
  uiText(`${prefix}${score.toFixed(1)} 分`, "xxs", T.headerText, { weight: "bold" }),
  score <= 0 ? uiBox([], { backgroundColor: T.border, height: "6px", cornerRadius: "3px" }) : meter(score, 100, T.accent),
], { width: prefix ? "150px" : "70px", spacing: "xs", flex: 0 });
const signedHero = (label: string, value: string, context?: string, compactLabel = false) => {
  const glyph = /^[-−]\d/.test(value) ? "▼ " : /^\+\d/.test(value) ? "▲ " : "";
  return uiBox([
    context ? chip(`${label}${compactLabel ? "· " : " · "}${context}`, T.accentTint, T.muted) : uiText(label, "xs", T.subtle),
    { type: "text", size: value.length > 10 ? "xl" : "3xl", weight: "bold", wrap: true, contents: [
      ...(glyph ? [{ type: "span", text: glyph, size: "xs", color: signColor(value) }] : []),
      { type: "span", text: value, color: signColor(value), weight: "bold" },
    ] },
  ], { layout: "horizontal", spacing: "sm", alignItems: "center" });
};
const compactDisclosures = (notes: { label: string; text: string }[]) => ({
  type: "text", size: "xxs", color: T.subtle, wrap: true,
  contents: notes.filter(note => note.label.trim() && note.text.trim()).flatMap(({ label, text }, index) => [
    { type: "span", text: `${index ? "\n" : ""}${label}｜`, color: T.subtle, weight: "bold" },
    { type: "span", text: text.replace(/[\r\n]+/g, " "), color: T.subtle },
  ]),
});

type ReplyDisclosure = { scope: string; label: string; text: string };

/** Keep positive and negative verification status attached to the issuer, including the prior-quarter basis. */
function qualificationNotes(entry: BottleneckEntry): ReplyDisclosure[] {
  const fund = entry.fundamentals;
  const official = officialPrevious(fund);
  return [
    { scope: entry.symbol, label: "營收交叉", text: fund?.cross_check ? revenueCheck(fund.cross_check) : "未取得官方營收交叉比對" },
    { scope: entry.symbol, label: "行情交叉", text: entry.market.cross_check ? exchangeCheck(entry.market.cross_check) : "未取得交易所收盤交叉比對" },
    ...(fund?.revenue_yoy_prev != null ? [{ scope: entry.symbol, label: "前季", text: official?.label ?? "沿用可比來源" }] : []),
  ];
}

/** One final same-reply card groups identical disclosures without dropping their subjects. */
function replyDisclosureBubble(notes: ReplyDisclosure[]) {
  const grouped = new Map<string, { label: string; text: string; scopes: string[] }>();
  for (const { scope, label, text } of notes) {
    if (!label.trim() || !text.trim()) continue;
    const normalized = text.replace(/[\r\n]+/g, " ");
    const key = `${label}\u0000${normalized}`;
    const existing = grouped.get(key);
    if (existing) {
      if (!existing.scopes.includes(scope)) existing.scopes.push(scope);
    } else grouped.set(key, { label, text: normalized, scopes: [scope] });
  }
  return {
    type: "bubble", size: "mega",
    header: productHeader("本回覆共用", "資料來源與說明"),
    body: uiBox(Array.from(grouped.values(), ({ label, text, scopes }) =>
      uiText(`${scopes.join("、")}｜${label}：${text}`, "xxs", T.ink)), { paddingAll: "lg", spacing: "sm" }),
    footer: uiBox([compactDisclosures([{ label: "用途", text: "非投資建議；不自動下單" }])], footerStyle),
  };
}



/** Numeric fallback estimates, explicitly separate from filed facts, RPO and target-price claims.
 * Revenue amounts are expressed in the currency of the issuer's latest reported quarter.
 * Growth is a damped median of the latest filed YoY observations; if absent, use layer median.
 * Never cross currency units or silently call a peer revenue number the issuer's filed result. */
export interface Top20Fallback {
  amount: number; change: number; currency: string;
  basis: "歷史推估" | "產業中位數推估" | "產業成長截尾推估" | "同業營收代理推估";
  asof: string; explanation: string;
}
function cleanGrowth(v: unknown): v is number {
  return typeof v === "number" && Number.isFinite(v) && v > -0.95 && v <= 3;
}
const capGrowth = (v: number) => Math.max(-0.35, Math.min(0.50, v));
function median(values: number[]): number | null {
  if (!values.length) return null;
  const data=values.slice().sort((a,b)=>a-b);
  const mid=data.length>>1;
  return data.length%2 ? data[mid]! : (data[mid-1]!+data[mid]!)/2;
}
export function estimateTop20Fallback(doc: BottleneckV3, entry: BottleneckEntry): {m6:Top20Fallback; m12:Top20Fallback} | null {
  if (doc.historical_forecasts_unavailable) return null;
  const f=entry.fundamentals;
  const unit=f?.revenue_unit ?? entry.market.currency;
  const currency=typeof unit==="string" && /^[A-Z]{3}$/.test(unit) ? unit : null;
  if (!currency) return null;
  let filed=f?.revenue;
  let proxy=false;
  if (typeof filed!=="number" || !Number.isFinite(filed) || filed<=0) {
    const peers=doc.top.filter(r=>r.symbol!==entry.symbol && r.layer===entry.layer
      && r.fundamentals?.revenue_unit===currency
      && typeof r.fundamentals.revenue==="number" && Number.isFinite(r.fundamentals.revenue)
      && r.fundamentals.revenue>0).map(r=>r.fundamentals!.revenue!);
    filed=median(peers);
    proxy=true;
  }
  if (typeof filed!=="number" || !Number.isFinite(filed) || filed<=0) return null;
  const rates=[f?.revenue_yoy,f?.revenue_yoy_prev].filter(cleanGrowth);
  const ownGrowth=median(rates);
  const layer=doc.industries.find(ind=>ind.id===entry.layer);
  const rawIndustryGrowth=layer?.median_revenue_yoy;
  const clippedIndustry=typeof rawIndustryGrowth==="number" && Number.isFinite(rawIndustryGrowth) && rawIndustryGrowth>3;
  const industryGrowth=cleanGrowth(rawIndustryGrowth) ? rawIndustryGrowth : clippedIndustry ? 3 : null;
  const sourceGrowth=ownGrowth ?? industryGrowth;
  if (sourceGrowth===null) return null;
  const growth=capGrowth(sourceGrowth*0.5);
  const basis:Top20Fallback["basis"]=proxy ? "同業營收代理推估" : ownGrowth!==null ? "歷史推估"
    : clippedIndustry ? "產業成長截尾推估" : "產業中位數推估";
  const asof=f?.quarter_end ?? doc.generated_at.slice(0,10);
  const growthExplanation=ownGrowth!==null ? "已報年增中位數折半，限制−35%至+50%"
    : clippedIndustry ? `產業年增觀察${pct(rawIndustryGrowth,0)}超過+300%，輸入截尾至+300%後折半，最終限制−35%至+50%`
    : "同層級產業年增中位數折半，限制−35%至+50%";
  const explanation=(proxy ? "同產業同幣別最近季營收中位數代理；不是該公司的已報營收"
    : "公司最近季營收×期間季數")+"；"+growthExplanation;
  const make=(months:6|12):Top20Fallback=>{
    const change=growth*(months/12);
    return {amount:filed!*(months/3)*(1+change),change,currency,basis,asof,explanation};
  };
  return {m6:make(6),m12:make(12)};
}
interface Top20Horizon {
  amount:string; change:number|null; basis:string; asof:string; reason:string; estimate:boolean;
}
function top20Horizon(doc:BottleneckV3,entry:BottleneckEntry,index:0|1):Top20Horizon|null {
  const forecast=forecastOf(doc,entry);
  const h=index===0?forecast.m6:forecast.m12;
  const ownEstimate=estimateTop20Fallback(doc,entry)?.[index===0?"m6":"m12"];
  const scenario=h.scenario.status==="AVAILABLE" && typeof h.scenario.change==="number" &&
    Number.isFinite(h.scenario.change) ? h.scenario.change : null;
  if (h.status==="AVAILABLE" && typeof h.amount==="number" && Number.isFinite(h.amount) && h.amount>=0) {
    const label=h.basis==="RECOGNITION"?"訂單認列":h.basis==="COMPANY_GUIDANCE"?"公司指引":
      h.basis==="CONSENSUS"?"分析師共識":"營收依據";
    return {amount:money(h.amount,h.currency),change:scenario??ownEstimate?.change??null,
      basis:label,asof:h.end??entry.fundamentals?.quarter_end??doc.generated_at.slice(0,10),
      reason:scenario!==null?"封存資料的條件情境；非實績":ownEstimate?"無股價情境，採財報增幅並假定P/S與股數不變；非目標價":"缺可核對成長依據，股價情境未驗證",
      estimate:true};
  }
  const trend=trendHorizonFor(entry.trend,forecast,index===0?"m6":"m12");
  if (trend) return {amount:money(trend.amount,entry.trend!.currency),change:scenario??trend.change,
    basis:"趨勢推估",asof:entry.trend!.anchor,reason:"既有已驗證營收趨勢；固定P/S與股數",estimate:true};
  const historical=historyOf(doc,entry);
  if (historical?.status==="ESTIMATE") return {amount:money(index===0?historical.m6:historical.m12,historical.currency),
    change:scenario??(index===0?historical.change6:historical.change12),
    basis:"歷史推估",asof:historical.anchor,reason:"已報四季歷史模型；固定P/S與股數",estimate:true};
  if (ownEstimate) return {amount:money(ownEstimate.amount,ownEstimate.currency),change:scenario??ownEstimate.change,
    basis:ownEstimate.basis,asof:ownEstimate.asof,reason:ownEstimate.explanation+"；固定P/S與股數；非目標價",estimate:true};
  return null;
}
function visibleHorizon(row:Top20Horizon|null,label:string):string {
  return row ? label+"："+row.amount+"（"+row.basis+"；截至"+row.asof+"；推估、非實績）" :
    label+"：未驗證（缺可核對營收金額、幣別或成長依據）";
}
function visibleScenario(row:Top20Horizon|null,label:string):string {
  return row?.change!==null && row?.change!==undefined ? label+"："+pct(row.change,0)+"（"+row.basis+"；P/S與股數不變；推估、非實績、非目標價）" :
    label+"：未驗證（缺可核對的成長或估價基準）";
}

/** Only replace missing numeric horizons that can be projected from a genuine company quarter.
 * Existing reviewed order/revenue-trend paths keep their exact established presentation. */
function needsTop20Fallback(doc:BottleneckV3,entry:BottleneckEntry):boolean {
  const quarter=entry.fundamentals?.revenue;
  if(typeof quarter!=="number" || !Number.isFinite(quarter) || quarter<=0 || entry.trend) return false;
  const forecast=forecastOf(doc,entry);
  return forecast.m6.status!=="AVAILABLE" || forecast.m12.status!=="AVAILABLE";
}

/** One-glance summary; complete sealed detail remains behind the text button. */
function companyBubble(doc: BottleneckV3, entry: BottleneckEntry, notes: ReplyDisclosure[], lean = false) {
  const fund = entry.fundamentals;
  const long = longTerm(entry.market);
  const official = officialPrevious(fund);
  const [ordersTile, ...proxyTiles] = outlookTiles(doc, entry);
  const proxyNotes = proxyTiles.map(([label, value, sub]) => {
    const detail = sub.replace(/^非訂單(?:｜)?/, "").replace(/｜季末 \d{4}-\d{2}-\d{2}$/, "");
    return `${label.replace("營收動能（代理）", "營收代理")}：${value}${detail ? `｜${detail}` : ""}｜非訂單`;
  });
  const forecast = forecastOf(doc, entry);
  const visible = [top20Horizon(doc,entry,0),top20Horizon(doc,entry,1)];
  const needsFallback = needsTop20Fallback(doc,entry);
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
  const orderWindows: string[] = [];
  const compactOrderRows = orderRows.map((row, index) => row.replace(/（(起算日 [^）]+)）/u, (_, window: string) => {
    orderWindows[index] = `${index === 0 ? "半年" : index === 1 ? "1年" : "期間"}${window}`;
    return "";
  }));
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
  const revenueCard = forecast.version === 3;
  const unavailableRevenue = revenueCard && forecast.revenueBasis == null;
  const unavailableRevenueNote = unavailableRevenue
    ? forecastLines.find(([text]) => text.startsWith("營收推估："))?.[0] ?? forecast.consensusNote ?? "營收推估未取得"
    : "";
  // V33b: the lowest-priority trend estimate fills only a horizon that has no existing figure (revenue-trend.ts).
  const trend = unavailableRevenue ? entry.trend : undefined;
  const trendOf = (index: number) => trendHorizonFor(trend, forecast, index === 0 ? "m6" : "m12");
  const trendShown = trendOf(0) !== null || trendOf(1) !== null;
  const revenueRows = compactOrderRows.map(row => {
    const colon = row.indexOf("：");
    const basis = colon < 0 ? -1 : row.indexOf("（", colon);
    return basis < 0 ? row : row.slice(0, basis);
  });
  const revenueScenarioRows = [forecast.m6, forecast.m12].map((horizon, index) => {
    const label = index === 0 ? "半年" : "1年";
    if (horizon.scenario.status === "AVAILABLE" && horizon.scenario.change !== undefined) return `${label}：${pct(horizon.scenario.change, 0)}`;
    const reason = scenarioRows[index]?.match(/無法估價（([^）]+)）/u)?.[1];
    return `${label}：無法估價${reason ? `（${reason}）` : ""}`;
  });
  const revenueBasis = unavailableRevenue
    ? `${unavailableRevenueNote}${trendShown ? `；${TREND_LABEL}，截至已申報季末 ${trend!.anchor}，${trendBasisText(trend!)}` : ""}`
    : [forecast.m6.basis_label, forecast.m12.basis_label].find(Boolean) ?? "來源未揭露";
  const revenueWindows = [forecast.m6, forecast.m12].flatMap((horizon, index) =>
    horizon.start && horizon.end ? [`${index === 0 ? "約半年" : "約1年"}：${horizon.start}–${horizon.end}${horizon.basis_label && horizon.basis_label !== revenueBasis ? `；${horizon.basis_label}` : ""}`] : []);
  const scenarioClaim = scenarioRows[0]?.includes("→ 股價情境")
    ? `${scenarioRows[0].split("→ 股價情境")[0]}→ 股價情境` : "";
  const analystNote = consensusV3
    ? (!entry.outlook?.consensus || !entry.outlook.scenarios?.length
      ? "分析師共識情境（非訂單）：無分析師共識可推算。" : "其他分析師情境見詳情")
    : "";
  // An RPO figure keeps its meaning and coverage qualifier on this card, once: from the forecast basis when it states it,
  // otherwise from the displayed orders figure itself, with or without a future forecast and whatever its version.
  const forecastCaveat = forecast.version === 3 ? "營收推估非保證" : "預計認列非保證";
  const recognitionCaveat = forecastLines.find(([text]) => text.startsWith(RPO_MEANING))?.[0]
    ?? (entry.outlook?.orders?.kind === "RPO" ? `${RPO_MEANING}；${forecastCaveat}` : forecastCaveat);
  const closingDisclosure = [
    condition,
    ...(forecast.version === 2 ? ["認列依公司披露時程"] : []),
    recognitionCaveat,
    "非今日起",
    "非目標價、非投資建議、不自動下單",
  ].join("；");
  const sourceNotes = revenueCard ? [
    { label: "來源", text: `${revenueBasis}${revenueWindows.length ? `；${revenueWindows.join("；")}` : ""}${entry.outlook?.orders?.kind === "RPO" ? `；訂單：${ordersTile![2]}` : ""}` },
    { label: "價", text: `${sourceZh(entry.market.source)}${scenarioClaim ? `；${scenarioClaim}` : ""}；${condition}${analystNote ? `；${analystNote}` : ""}` },
    { label: "情境", text: `${condition ? closingDisclosure.replace(`${condition}；`, "") : closingDisclosure}${warning?.text ? `；${warning.text}` : ""}${!revenueBasis.includes("非訂單") && !analystNote.includes("非訂單") ? "；非訂單" : ""}` },
    ...(historyRows.length ? [{ label: "歷史", text: historyRows[0]! }] : []),
    ...proxyNotes.map(text => ({ label: "代理", text })),
  ] : [
    { label: "來源", text: `${fund ? `財報：${sourceZh(fund.source)}${official ? `（前一季採官方合併季報），季末 ${fund.quarter_end}；${official.label}` : ""}` : "財報：未取得可比季度"}${fund?.cross_check ? `；${revenueCheck(fund.cross_check)}` : ""}；股價來源 ${sourceZh(entry.market.source)}；訂單：${ordersTile![2]}${orderWindows.filter((_, index) => index % 2 === 0).map(window => `；${window}`).join("")}` },
    { label: "行情", text: `${entry.market.cross_check ? exchangeCheck(entry.market.cross_check) : ""}${long.event ? `；上市沿革 ${long.event}` : ""}${orderWindows.filter((_, index) => index % 2 === 1).map(window => `；${window}`).join("")}` },
    { label: "情境", text: `${closingDisclosure}${long.sub ? `；${long.sub}` : ""}` },
    ...(historyRows.length ? [{ label: "歷史", text: historyRows[0]! }] : []),
    ...proxyNotes.map(text => ({ label: "代理", text })),
  ];
  if(needsFallback) notes.push(...visible.flatMap(row=>row?[{scope:entry.symbol,label:"半年／1年推估",
    text:row.basis+"｜"+row.asof+"｜"+row.reason+"｜推估非實績，非公司揭露之訂單"}]:[]));
  notes.push(...sourceNotes.map(note => ({ scope: entry.symbol, ...note })));
  notes.push(...qualificationNotes(entry));
  return {
    type: "bubble", size: "mega",
    header: uiBox([
      uiBox([chip(`#${entry.rank}`), chip(layerName(doc, entry.layer)), chip(`分數 ${entry.score.toFixed(1)}`)],
        { layout: "horizontal", spacing: "xs" }),
      uiBox([
        { type: "text", size: "lg", wrap: true, contents: [
          { type: "span", text: `${entry.symbol}｜${chineseName(entry)}`.slice(0, 60), size: "lg", color: T.headerText, weight: "bold" },
          { type: "span", text: `\n${!lean ? `${entry.name}｜` : ""}${entry.archetype === "EXPLOSION" ? "爆發型" : "核心複利型"}｜${entry.role_zh ?? entry.role}｜截至 ${entry.market.asof}${entry.name_zh ? `｜中文名來源：${ZH_SOURCE_LABEL[entry.name_zh_source ?? ""] ?? "來源已核對"}` : ""}`.slice(0, 155),
            size: "xs", color: T.headerMuted },
        ] },
        entry.score <= 0 ? uiBox([], { backgroundColor: T.border, height: "6px", cornerRadius: "3px" }) : meter(entry.score, 100, T.accent),
      ], { layout: "horizontal", spacing: "sm" }),
    ], { ...headerStyle, spacing: "sm" }),
    body: uiBox([
      ...corporateActionBanner(entry),
      uiBox([
      signedHero("營收年增", pct(fund?.revenue_yoy ?? null, 0), fund ? `季末 ${fund.quarter_end}` : undefined, true),
      uiBox([
        accentKpiTile("毛利變化", ppShort(fund?.gross_margin_change)),
        accentKpiTile("6個月",entry.market.ret_6m!==null || !needsFallback ? pct(entry.market.ret_6m,0)
          : pct(doc.industries.find(x=>x.id===entry.layer)?.median_return_6m ?? visible[0]?.change ?? null,0)
             +"（"+(entry.market.return_reasons?.ret_6m?"未調整配發；":"")+"產業推估・非實績）"),
        accentKpiTile("2年年化", long.value),
      ], { layout: "horizontal", spacing: "sm" }),
      uiText(`市值 ${cap(entry.market_cap_usd)}｜${fund && sharesBasis(fund) ? "稀釋加權股數" : "股數"} ${fund ? pct(fund.shares_yoy, 1) : "未揭露"}`, "xs", T.subtle),
      ], { spacing: "sm" }),
      uiBox([
      uiBox([
        uiBox([uiBox([], { width: "3px", height: "16px", flex: 0, backgroundColor: T.accent }), chip(`${ordersTile![0]}：${ordersTile![1]}`, T.soft, T.ink),
          ...(revenueCard && warning ? [chip("財季已結束，仍為推估非實績", T.paleCaution, T.caution)]
            : unavailableRevenue ? [chip(trendShown ? TREND_CHIP : needsFallback ? "營收與情境推估・非實績" : "營收推估暫不可用", T.paleCaution, T.caution)] : [])], { layout: "horizontal", spacing: "xs" }),
      ]),
      uiBox([
        ...(needsFallback ? [
          uiBox(visible.map((row,index)=>{
            const label=index===0?"半年":"1年";
            return uiText(visibleHorizon(row,label+"營收推估")+"｜"+visibleScenario(row,label+"股價情境"),
              "xxs",T.ink);
          }),{spacing:"xs"})
        ] : [
        ...(revenueCard ? [
          uiBox((unavailableRevenue ? [forecast.m6, forecast.m12] : revenueRows).map((row, index) => {
            const horizon = [forecast.m6, forecast.m12][index]!;
            const recognition = unavailableRevenue && horizon.status === "AVAILABLE" && horizon.basis === "RECOGNITION" && horizon.amount !== undefined;
            const estimate = !recognition ? trendOf(index) : null;
            const label = `${index === 0 ? "約半年" : "約1年"}${recognition ? "訂單認列" : estimate ? "趨勢推估" : "營收推估"}`;
            const source = typeof row === "string" ? row : "";
            const colon = source.indexOf("：");
            const value = recognition ? money(horizon.amount!, horizon.currency) : estimate ? money(estimate.amount, trend!.currency)
              : unavailableRevenue ? "未揭露" : colon < 0 ? source : source.slice(colon + 1);
            return kvRow(label, value, { color: value === "未揭露" ? T.subtle : T.ink });
          }), { spacing: "xs" }),
          uiBox([forecast.m6, forecast.m12].map((horizon, index) => {
            const label = index === 0 ? "約半年" : "約1年";
            const estimate = horizon.scenario.status === "AVAILABLE" ? null : trendOf(index);
            if (estimate) return barRow(`${label}趨勢`, Math.abs(estimate.change * 100), pct(estimate.change, 0), 150);
            return horizon.scenario.status === "AVAILABLE" && horizon.scenario.change !== undefined
              ? barRow(label, Math.abs(horizon.scenario.change * 100), pct(horizon.scenario.change, 0), 150)
              : uiBox([uiText(label, "xs", T.subtle), chip(revenueScenarioRows[index]!.split("：").slice(1).join("："), T.soft, T.subtle)],
                { layout: "horizontal", spacing: "sm" });
          }), { spacing: "xs" }),
        ] : [
          uiBox([forecast.m6, forecast.m12].map((horizon, index) => {
            const row = `${index === 0 ? "未來訂單｜" : ""}${compactOrderRows[index] ?? "未揭露"}`;
            return horizon.status === "AVAILABLE" ? uiText(row, "xs", T.ink, { weight: "bold" }) : chip(row, T.soft, T.subtle);
          }), { spacing: "xs" }),
          uiBox([forecast.m6, forecast.m12].map((horizon, index) => {
            const row = `${index === 0 ? "股價情境｜" : ""}${(scenarioRows[index] ?? "無法估價").replace(/訂單僅覆蓋同期營收 ([^)）]+)/u, "覆蓋$1")}`;
            const change = horizon.scenario.status === "AVAILABLE" ? horizon.scenario.change : undefined;
            return change === undefined ? chip(row, T.soft, T.subtle)
              : uiBox([uiText(row, "xs", change < 0 ? T.negative : T.ink, { weight: "bold" }),
                ...(change === 0 ? [] : [uiBox([meter(Math.abs(change) * 100, 150, T.accent)], { width: "30px", flex: 0 })])],
                { layout: "horizontal", spacing: "xs", alignItems: "center" });
          }), { spacing: "xs" }),
        ]),
        ]),
        ...(!revenueCard ? forecastWarningRows.map(row => uiText(wrapForecastRow(row), "xxs", T.ink)) : []),
        // Full historical model inputs and estimates remain on the complete-data route.
      ], { spacing: "xs" }),
      ], { spacing: "sm" }),
    ], { paddingAll: "lg", spacing: "md" }),
    footer: uiBox([
      compactDisclosures([{ label: "提醒", text: `${trendShown ? `${TREND_LABEL}，截至 ${trend!.anchor} 季末；` : ""}${forecastCaveat}；${screenConditionsText(entry)}；${latestEventText(entry)}；非目標價；非投資建議；不自動下單` }]),
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
    const lines = doc.top.map(entry => [
      `${entry.rank}. ${entry.symbol} ${chineseName(entry)}（${entry.name}）`,
      `產業層級：${layerName(doc, entry.layer)}`,
      `分數：${entry.score.toFixed(1)}`,
      `營收年增 ${pct(entry.fundamentals?.revenue_yoy ?? null, 0)}`,
      `6 個月 ${pct(entry.market.ret_6m, 0)}`,
      `2 年年化 ${longTermText(entry.market)}`,
      currentOrders(entry.outlook, ordersOf(doc, entry.symbol).filer || entry.fundamentals?.source === "SEC EDGAR XBRL companyfacts", doc.generated_at.slice(0, 10)),
      ...(corporateActionNotice(entry) ? [corporateActionNotice(entry)!] : []),
      screenConditionsText(entry),
      latestEventText(entry),
      ...(needsTop20Fallback(doc,entry) ? ([0,1] as const).flatMap(index=>{
        const estimate=top20Horizon(doc,entry,index), label=index===0?"半年":"1年";
        return [visibleHorizon(estimate,label+"營收推估"),visibleScenario(estimate,label+"股價情境")];
      }) : forecastText(forecastOf(doc,entry),money).split("｜")),
      ...(entry.outlook?.consensus?.revenue_growth == null && entry.outlook?.consensus ? [compactScenarioText(entry.outlook)] : []),
    ].join("\n"));
    // Paginated into at most five messages of whole entries (never an entry cut away by a length limit).
    const blocks = [`瓶頸爆發 TOP20（v3，產生 ${formatTaipeiTimestamp(doc.generated_at)}）`,
      "排序：層級熱度＋公司捕獲＋社群與機構線索＋市場確認＋爆發性；2年年化報酬為負者排除。分拆、恢復交易、IPO 或重整新股不足2年者，改用已核實正常交易首日以來年化（至少1年，非2年）；沿革未核實且價格不足2年者不列入。非投資建議。",
      ...(doc.historical_retention_notice ? [doc.historical_retention_notice] : []),
      ...lines, ...(doc.excluded_actions ?? []).map(excludedActionText),
      ...(doc.rotation_provenance ? [doc.rotation_provenance.notice_zh] : []),
      "輸入「瓶頸詳情 代號」看逐項數據與來源；「產業爆發榜」看 Leopold 邏輯產業排序。", "公開研究，非投資建議；不自動下單。"];
    const pages: string[] = [];
    for (const block of blocks) {
      const last = pages[pages.length - 1];
      if (last !== undefined && last.length + 2 + block.length <= 4900) pages[pages.length - 1] = `${last}\n\n${block}`;
      else pages.push(block);
    }
    const messages: LineOutboundMessage[] = pages.map(text => ({ type: "text", text }));
    assertLineMessages(messages);
    return messages;
  }
  const alt = (index: number, total: number) => `瓶頸爆發 TOP20（${index + 1}/${total}）`;
  const build = (lean: boolean) => {
    const notes: ReplyDisclosure[] = [];
    if (doc.historical_retention_notice) notes.push({
      scope: "本頁排行與情境", label: "歷史保留資料", text: doc.historical_retention_notice,
    });
    const cards = doc.top.map(entry => companyBubble(doc, entry, notes, lean));
    notes.push(...(doc.excluded_actions ?? []).map(row => ({
      scope: row.symbol, label: "未納入排行",
      text: `${row.reason_zh}；${corporateActionNotice(row)}；官方來源：${row.corporate_action.source_url}`,
    })));
    if (doc.rotation_provenance) notes.push({
      scope: "本輪排行", label: "輪動來源", text: doc.rotation_provenance.notice_zh,
    });
    return packCarousels([...cards, replyDisclosureBubble(notes)], alt, doc.generated_at);
  };
  try {
    return build(false);
  } catch (error) {
    if (!(error instanceof Error) || !["LINE_MESSAGE_COUNT_INVALID", "LINE_FLEX_CAROUSEL_TOO_LARGE", "LINE_FLEX_BUBBLE_INVALID"].includes(error.message)) throw error;
    // Retry only LINE packing limits; keep every F1/F2 field, dropping optional English names and the industry button.
    return build(true);
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
  const official = officialPrevious(fund);
  const { orders, rpoYoy, filer } = ordersOf(doc, entry.symbol);
  const outlook = entry.outlook;
  const forecast = forecastOf(doc, entry);
  const warning = forecast.m6.warning ?? forecast.m12.warning;
  const kind = entry.archetype === "EXPLOSION" ? "爆發型（市值<US$10B）" : "核心複利型";
  const buttons = [detailsButton(`${entry.symbol} 完整數據與網址`, `瓶頸詳情 ${entry.symbol} 文字`), menuAction("回瓶頸 TOP20", "TOP20")];
  const sharedNotes: ReplyDisclosure[] = qualificationNotes(entry);
  if (doc.historical_retention_notice) sharedNotes.push({
    scope: entry.symbol, label: "歷史保留資料", text: doc.historical_retention_notice,
  });
  const page = (eyebrow: string, body: unknown[], notes: { label: string; text: string }[], compact = false) => {
    sharedNotes.push(...notes.map(note => ({ scope: eyebrow, ...note })));
    return {
    type: "bubble", size: "mega",
    header: compact ? uiBox([
      { type: "text", size: "xxs", wrap: true, contents: [
        { type: "span", text: `瓶頸詳情 · #${entry.rank} · ${eyebrow}\n`, size: "xxs", color: T.headerMuted, weight: "bold" },
        { type: "span", text: `${entry.symbol}｜${chineseName(entry)}`.slice(0, 60), size: "xl", color: T.headerText, weight: "bold" },
        { type: "span", text: `\n${entry.name.slice(0, 80)}｜${layerName(doc, entry.layer)}｜${entry.score.toFixed(1)} 分｜股價至 ${entry.market.asof}${fund ? `｜股數 ${pct(fund.shares_yoy, 1)}${sharesBasis(fund) ? `（${sharesBasis(fund)}）` : ""}` : ""}`, size: "xxs", color: T.headerMuted },
      ] },
      uiBox([entry.score <= 0 ? uiBox([], { backgroundColor: T.border, height: "6px", cornerRadius: "3px" }) : meter(entry.score, 100, T.accent)],
        { width: "70px" }),
    ], { ...headerStyle, spacing: "sm" }) : productHeader(`瓶頸詳情 · #${entry.rank} · ${eyebrow}`, `${entry.symbol}｜${chineseName(entry)}`.slice(0, 60), [
      uiText(`${entry.name.slice(0, 80)}｜${entry.archetype === "EXPLOSION" ? "爆發型" : "核心複利型"}`, "xxs", T.headerMuted),
      uiBox([chip(layerName(doc, entry.layer)), scoreIndicator(entry.score)], { layout: "horizontal", spacing: "sm" }),
    ]),
    body: uiBox([...(eyebrow.startsWith("財報") ? corporateActionBanner(entry) : []), ...body], { paddingAll: "lg", spacing: "md" }),
    footer: uiBox([compactDisclosures([{ label: "提醒", text: `${eyebrow === "訂單與情境" ? "投資有風險" : forecast.version === 2 ? "預計認列非保證" : "營收推估非保證"}；非投資建議；不自動下單` }]), ...buttons], footerStyle),
    };
  };

  const page1 = page(`財報與市場 · ${kind}`, [
    signedHero("營收年增", pct(fund?.revenue_yoy ?? null, 0), fund ? `季末 ${fund.quarter_end}` : undefined),
    uiBox([accentKpiTile("毛利率", gmText(fund?.gross_margin)),
      accentKpiTile("6個月", pct(entry.market.ret_6m, 0)),
      accentKpiTile("2年年化", long.value)], { layout: "horizontal", spacing: "sm" }),
    uiBox([
      uiText(`毛利率變化 ${ppShort(fund?.gross_margin_change)}`, "xs", T.muted),
      uiText(`前季營收年增 ${pct(fund?.revenue_yoy_prev ?? null, 0)}`, "xs", T.muted),
      uiText(`營收加速度 ${ppShort(fund ? accelOf(fund) : null)}`, "xs", T.muted),
    ], { spacing: "xs" }),
  ], [
    { label: "財報", text: `${fund ? `${sourceZh(fund.source)}；季末 ${fund.quarter_end}` : "未取得可比季度"}${official ? `；${official.label}` : ""}${fund?.cross_check ? `；${revenueCheck(fund.cross_check)}` : ""}` },
    { label: "行情", text: `${sourceZh(entry.market.source)}${long.sub ? `；${long.sub}` : ""}` },
    ...(entry.market.cross_check ? [{ label: "交叉", text: exchangeCheck(entry.market.cross_check) }] : []),
    ...(long.event ? [{ label: "沿革", text: `上市沿革：${long.event}` }] : []),
    { label: "用途", text: "非投資建議；不自動下單" },
  ], true);

  const [ordersTile] = outlookTiles(doc, entry);
  const floorValue = (value: number | null | undefined) => value === null || value === undefined ? "需新訂單" : `≥${value >= 0 ? "+" : ""}${value.toFixed(0)}%`;
  const scenario = outlook?.scenarios?.[0];
  const annualRecognition = forecast.m12.contracted_recognition ?? (forecast.m12.status === "AVAILABLE"
    && forecast.m12.basis === "RECOGNITION" && forecast.m12.amount !== undefined
    ? { amount: forecast.m12.amount, currency: forecast.m12.currency, rpo: forecast.m12.rpo,
      start: forecast.m12.start, end: forecast.m12.end } : null);
  const disclosedRpoYoy = outlook?.orders?.kind === "RPO" ? outlook.orders.yoy : rpoYoy;
  const orderValueRow = (label: string, value: string | null) => uiBox([
    uiText(label, "xs", T.subtle),
    value === null ? chip("未揭露", T.soft, T.subtle) : uiText(value, "sm", T.ink, { align: "end", weight: "bold" }),
  ], { layout: "horizontal", spacing: "sm", alignItems: "center" });
  const forecastConsensusLabel = [forecast.m6.basis_label, forecast.m12.basis_label]
    .find((label): label is string => typeof label === "string" && label.startsWith("分析師共識（非公司財測、非官方）"));
  const consensusSourceLine = forecastConsensusLabel ?? (scenario && outlook?.consensus
    ? `分析師共識（非公司財測、非官方）｜${outlook.consensus.source ?? "來源未揭露"}，${outlook.consensus.revenue_analysts == null ? "數量未揭露" : `${outlook.consensus.revenue_analysts} 位`}分析師，截至 ${(outlook.consensus.asof ?? "").slice(0, 10) || "日期未揭露"}`
    : "");
  const floorNote = orders ? `RPO ${orders.form}（申報 ${orders.filed}），認列基準 ${orders.as_of}；營收下限非股價下限，未計新訂單、取消或遞延`
    : !filer ? "非 SEC 定期申報公司，無 RPO 認列時程" : "最新財報未揭露認列時程，不推估實現金額";
  const history = historyOf(doc, entry);
  const trendRows = (["m6", "m12"] as const).map(key => trendHorizonFor(entry.trend, forecast, key));
  const h6=top20Horizon(doc,entry,0), h12=top20Horizon(doc,entry,1);
  const page2 = page("訂單與情境", [
    ...(needsTop20Fallback(doc,entry)?[
    uiText(visibleHorizon(h6,"半年營收推估"),"xs",T.ink),
    uiText(visibleHorizon(h12,"1年營收推估"),"xs",T.ink),
    uiText(visibleScenario(h6,"半年股價情境"),"xs",T.ink),
    uiText(visibleScenario(h12,"1年股價情境"),"xs",T.ink),    ]:[]),
    uiBox([
      signedHero(ordersTile![0], ordersTile![1], annualRecognition ? "預計認列非保證" : orders ? `認列基準 ${orders.as_of}` : undefined),
      uiBox([accentKpiTile("半年認列支撐", floorValue(orders?.floor.m6)), accentKpiTile("1年認列支撐", floorValue(orders?.floor.m12))], { layout: "horizontal", spacing: "sm" }),
    ]),
    uiBox([
      orderValueRow("RPO 年增", disclosedRpoYoy == null ? null : pct(disclosedRpoYoy, 0)),
      orderValueRow("預計1年內認列", annualRecognition ? money(annualRecognition.amount, annualRecognition.currency) : null),
      ...(annualRecognition?.rpo && annualRecognition.amount <= annualRecognition.rpo
        ? [annualRecognition.amount === 0 ? orderValueRow("認列進度", "0%")
          : barRow("認列進度", annualRecognition.amount, `${(annualRecognition.amount / annualRecognition.rpo * 100).toFixed(0)}%`, annualRecognition.rpo)] : []),
    ], { spacing: "xs" }),
    uiBox(history?.status === "ESTIMATE" ? [
      accentHeading("歷史模型股價情境"),
      barRow("6M", Math.abs(history.change6 * 100), pct(history.change6, 0)),
      barRow("1Y", Math.abs(history.change12 * 100), pct(history.change12, 0)),
    ] : trendRows.some(row => row !== null) ? [
      accentHeading("趨勢推估股價情境"),
      ...trendRows.flatMap((row, index) => row ? [barRow(index === 0 ? "6M" : "1Y", Math.abs(row.change * 100), pct(row.change, 0))] : []),
    ] : [forecast.m6, forecast.m12].map((horizon, index) => {
      const label = index === 0 ? "半年股價" : "1年";
      const change = horizon.scenario.status === "AVAILABLE" ? horizon.scenario.change : undefined;
      if (change !== undefined) return change === 0 ? orderValueRow(label, "0%") : barRow(label, Math.abs(change * 100), pct(change, 0), 150);
      const reason = horizon.scenario.status === "INSUFFICIENT_COVERAGE" ? "覆蓋不足"
        : horizon.scenario.reason === "NO_MATCHING_REVENUE" ? "缺同期營收"
        : horizon.scenario.reason === "SCOPE_PARTIAL" ? "範圍不符"
        : horizon.scenario.reason === "NO_REVENUE_HISTORY" ? "缺營收歷史"
        : horizon.scenario.reason === "NO_REVENUE_BASIS" ? "缺營收依據"
        : horizon.scenario.reason === "INVALID_BASELINE" ? "基準無效" : "缺認列時程";
      return uiBox([uiText(`${label}${reason}`, "xs", T.subtle), chip("無法估價", T.soft, T.subtle)], { layout: "horizontal", spacing: "sm" });
    }), { spacing: "xs" }),
  ], [
    { label: "來源", text: `${ordersTile![2]}；股價 ${entry.market.asof}；${orders ? "分期已簽約認列金額÷目前營收−1" : annualRecognition ? "認列資料見文字版" : floorNote}${annualRecognition ? `；期間${outlook?.orders && outlook.orders.kind !== "NOT_DISCLOSED" && annualRecognition.start === outlook.orders.as_of ? "訂單日" : annualRecognition.start ?? "起日未揭露"}–${annualRecognition.end ?? "迄日未揭露"}（非今日起）` : ""}` },
    { label: "認列", text: orders ? `已簽約營收成長支撐；半年/1年覆蓋${orders.coverage.m6 == null ? "未揭露" : `${orders.coverage.m6.toFixed(0)}%`}/${orders.coverage.m12 == null ? "未揭露" : `${orders.coverage.m12.toFixed(0)}%`}；${floorNote}` : annualRecognition ? "已簽約認列非保證；未計新訂單、取消或遞延" : "無可用 RPO 認列時程；不推估實現金額" },
    { label: "用途", text: `${consensusSourceLine ? `${consensusSourceLine}；` : ""}${trendRows.some(row => row !== null) ? `${TREND_LABEL}，截至 ${entry.trend!.anchor} 季末；` : ""}${history?.status === "ESTIMATE" || trendRows.some(row => row !== null) || [forecast.m6, forecast.m12].some(h => h.scenario.status === "AVAILABLE") ? "P/S與股數不變；非目標價；" : ""}非投資建議；不自動下單` },
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
  return { cards: [page1, page2, page3, page4], disclosure: replyDisclosureBubble(sharedNotes) };
}

function detailText(doc: BottleneckV3, entry: BottleneckEntry): string {
  const fund = entry.fundamentals;
  const long = longTerm(entry.market);
  const outlook = entry.outlook;
  const scenarios = (outlook?.scenarios ?? []).map(row => `${SCENARIO_LABEL[row.kind]} ${pct(row.change, 0)}（${scenarioSample(outlook, row.kind)}）`).join("、");
  const official = officialPrevious(fund);
  const { orders } = ordersOf(doc, entry.symbol);
  const floorValue = (value: number | null | undefined) => value === null || value === undefined ? "需新訂單" : `≥${value >= 0 ? "+" : ""}${value.toFixed(0)}%`;
  const coverageValue = (value: number | null | undefined) => value === null || value === undefined ? "未揭露" : `${value.toFixed(0)}%`;
  return [
    `【瓶頸詳情｜#${entry.rank} ${entry.symbol} ${chineseName(entry)}（${entry.name}）】`,
    ...(doc.historical_retention_notice ? [doc.historical_retention_notice] : []),
    `型態：${entry.archetype === "EXPLOSION" ? "瓶頸爆發型（市值<US$10B）" : "核心複利型"}；市值 ${cap(entry.market_cap_usd)}`,
    `瓶頸位置：${entry.role_zh ?? entry.role}${entry.role_zh ? `（原文：${entry.role}）` : ""}`,
    ...(needsTop20Fallback(doc,entry) ? ([0,1] as const).flatMap(index=>{
      const row=top20Horizon(doc,entry,index), label=index===0?"半年":"1年";
      return [visibleHorizon(row,label+"營收推估"),visibleScenario(row,label+"股價情境")];
    }) : []),
    ...(corporateActionNotice(entry) ? [corporateActionNotice(entry)!, `${corporateActionSourceLabel(entry)}：${entry.corporate_action!.source_url}`] : []),
    screenConditionsText(entry),
    latestEventText(entry),
    ...(entry.latest_event ? [`最新事件來源：${entry.latest_event.source_url}`] : []),
    `分數構成：層級熱度 ${entry.parts.layer_heat}｜公司捕獲 ${entry.parts.capture}｜市場確認 ${entry.parts.confirmation}｜爆發性 ${entry.parts.size}${entry.parts.penalty !== 0 ? `｜條件式稀釋／融資扣分 -${entry.parts.penalty}` : ""}`,
    fund ? `財報（${sourceZh(fund.source)}${official ? "；前一季年增採官方合併季報" : ""}，季末 ${fund.quarter_end}）：營收年增 ${pct(fund.revenue_yoy)}，前一季年增 ${pct(fund.revenue_yoy_prev)}（加速度 ${pp(accelOf(fund))}）；毛利率 ${gmText(fund.gross_margin)}（年變化 ${pp(fund.gross_margin_change)}）；剩餘履約義務年增 ${pct(fund.rpo_yoy)}；股數年增 ${pct(fund.shares_yoy)}${sharesBasis(fund) ? `（${sharesBasis(fund)}）` : ""}\n來源：${fund.source_url}${official ? `\n${official.label}\n前一季來源：${official.url}` : ""}` : "財報：未取得可比季度（不以估計替代）。",
    fund?.cross_check ? `${revenueCheck(fund.cross_check)}\n來源：${fund.cross_check.source_url}` : "官方營收未交叉比對",
    `股價（${sourceZh(entry.market.source)}，至 ${entry.market.asof}）：6個月 ${pct(entry.market.ret_6m)}、2年年化 ${long.value}${long.sub ? `（${long.sub}）` : ""}\n來源：${entry.market.source_url}`,
    ...(long.event ? [`上市沿革：${long.event}\n沿革來源：${long.sources.join("；")}`] : []),
    entry.market.cross_check ? exchangeCheck(entry.market.cross_check) : "交易所收盤未交叉比對",
    currentOrders(outlook, ordersOf(doc, entry.symbol).filer || fund?.source === "SEC EDGAR XBRL companyfacts", doc.generated_at.slice(0, 10))
      + (outlook?.orders && outlook.orders.kind !== "NOT_DISCLOSED" ? `\n來源：${outlook.orders.source_url}` : ""),
    ...(orders ? [`已簽約營收成長支撐（RPO認列時程）：6個月 ${floorValue(orders.floor.m6)}（覆蓋 ${coverageValue(orders.coverage.m6)}）；1年 ${floorValue(orders.floor.m12)}（覆蓋 ${coverageValue(orders.coverage.m12)}）；2年 ${floorValue(orders.floor.m24)}（覆蓋 ${coverageValue(orders.coverage.m24)}）。計算：分期已簽約認列金額÷目前營收−1；RPO ${orders.form}（申報 ${orders.filed}），認列基準 ${orders.as_of}；營收下限非股價下限，未計新訂單、取消或遞延。`] : ["RPO 認列時程未披露"]),
    ...proxyDetailLines(doc, entry),
    ...forecastLines(forecastOf(doc, entry), money, historyOf(doc, entry)),
    ...trendBlockLines(entry.trend, money, forecastOf(doc, entry), true),
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
  if (!entry) {
    const excluded = doc.excluded_actions?.find(row => row.symbol.toUpperCase() === symbol.toUpperCase());
    const text = excluded ? excludedActionText(excluded)
      : `「${symbol}」不在本輪瓶頸爆發 TOP20（產生 ${formatTaipeiTimestamp(doc.generated_at)}）。`;
    return doc.historical_retention_notice ? `${doc.historical_retention_notice}\n${text}` : text;
  }
  // The detail card first; then the company data report (SEC filings, business profile, thesis phase, order
  // realization) when one is sealed.
  const raw = Object.hasOwn(doc.deep_reports, entry.symbol) ? doc.deep_reports[entry.symbol] : undefined;
  const report = raw ? validateCompanyDataReport(raw, entry.symbol) : null;
  const reportMessages = report ? (style === "flex" ? buildCompanyDataReportFlex(report, doc.generated_at, ["回瓶頸 TOP20", "TOP20"])
    : buildCompanyDataReportMessages(report, doc.generated_at)) : [];
  let messages: LineOutboundMessage[];
  if (style === "flex") {
    const { cards, disclosure } = detailBubbles(doc, entry);
    const alt = () => altSummary({ topic: `${entry.symbol} ${chineseName(entry)} 瓶頸詳情`,
      status: `第 ${entry.rank} 名，財報、訂單、依據與來源`, next: "左右滑動；完整網址按文字版" });
    const detail = packCarousels(reportMessages.length ? cards : [...cards, disclosure], alt, doc.generated_at);
    messages = reportMessages.length ? [...detail, ...reportMessages, ...packCarousels([disclosure], alt, doc.generated_at)] : detail;
  } else {
    const detail = pagesAtLineBoundary(detailText(doc, entry), 4900).map(text => ({ type: "text" as const, text }));
    messages = [...detail, ...reportMessages].slice(0, 5);
  }
  assertLineMessages(messages);
  return messages;
}

function industryBubble(doc: BottleneckV3, industry: IndustryEntry) {
  const acceleration = industry.median_acceleration === null || industry.median_acceleration === undefined ? "未揭露"
    : `${industry.median_acceleration >= 0 ? "+" : ""}${(industry.median_acceleration * 100).toFixed(0)}pp`;
  const secHeat = industry.news?.ratio === null || industry.news?.ratio === undefined ? "SEC申報未取得" : "SEC申報熱度已納入";
  return {
    type: "bubble", size: "mega",
    header: uiBox([
      { type: "text", size: "lg", wrap: true, contents: [
        { type: "span", text: `產業爆發榜 · Leopold 因果鏈：${CHAIN_ZH[industry.chain] ?? industry.chain}\n`, size: "xs", color: T.headerMuted },
        { type: "span", text: industry.name_zh, size: "lg", color: T.headerText, weight: "bold" },
      ] },
      chip(`#${industry.rank}`),
    ], { ...headerStyle, spacing: "sm" }),
    body: uiBox([
      { type: "text", size: "3xl", weight: "bold", wrap: true, contents: [
        { type: "span", text: "產業爆發力\n", size: "xs", color: T.subtle, weight: "regular" },
        { type: "span", text: industry.explosiveness.toFixed(1), size: "3xl", color: T.ink, weight: "bold" },
      ] },
      uiBox([accentKpiTile("營收中位", pct(industry.median_revenue_yoy, 0)),
        accentKpiTile("加速", acceleration),
        accentKpiTile("6個月", pct(industry.median_return_6m, 0))], { layout: "horizontal", spacing: "sm" }),
      uiText(`${secHeat}；詳情：產業爆發榜 文字`, "xs", T.subtle),
    ], { paddingAll: "lg", spacing: "md" }),
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
    const messages = pagesAtLineBoundary([`產業爆發榜（Leopold 因果鏈，產生 ${formatTaipeiTimestamp(doc.generated_at)}）`,
      "爆發力構成：因果鏈位置35＋機構持倉權重25＋營收加速20＋SEC申報熱度10＋社群熱度10",
      ...lines, "非投資建議。"].join("\n"), 4900)
      .map(text => ({ type: "text" as const, text }));
    assertLineMessages(messages);
    return messages;
  }
  return packCarousels(doc.industries.slice(0, 10).map(industry => industryBubble(doc, industry)), (index, total) => `產業爆發榜（${index + 1}/${total}）`, doc.generated_at);
}
