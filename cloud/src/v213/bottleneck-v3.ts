/** Bottleneck-explosion Top20 v3 and the Leopold-led industry ranking (scripts/bottleneck_top20_v3.py).
 *
 * Sealed as the lazy object `v213:bottleneck-top20:v3`. Leads (Serenity posts, 13F positions) weight conviction
 * but are never shown as company facts; every figure carries its source and date. A malformed or stale document
 * (older than the report bound, report-age.ts) gives null and the caller keeps the seven-field Top20.
 */
import { assertLineMessages, type LineOutboundMessage } from "../line-messages";
import type { PublicSnapshotView } from "./public-snapshot";
import { v213ReportAgeFresh } from "./report-age";
import { sourceZh } from "./source-labels";
import { PRICE_SOURCE_LABEL } from "./market-observations";
import { buildCompanyDataReportFlex, buildCompanyDataReportMessages, validateCompanyDataReport } from "./deep-analysis";
import {
  LINE_THEME as T, chip, divider, footerStyle, footnote, menuAction, meter, packCarousels, productHeader, rankBadge,
  section, stackedBar, statTile, uiBox, uiText,
} from "./line-theme";

export const BOTTLENECK_V3_KEY = "v213:bottleneck-top20:v3";

interface Fundamentals {
  source: string; source_url: string; quarter_end: string; revenue_yoy: number | null; revenue_yoy_prev: number | null;
  gross_margin: number | null; gross_margin_change: number | null; rpo_yoy: number | null; shares_yoy: number | null;
  /** What shares_yoy measures: shares outstanding (SEC dei) or the diluted weighted average of the quarter (a fallback). */
  shares_basis?: "OUTSTANDING" | "DILUTED_WEIGHTED_AVERAGE" | null;
  /** Official revenue beside the Yahoo quarter, never replacing it: the exchange's monthly revenue for Taiwan listings
   * (TWSE/TPEx open data, period YYYY-MM) or the issuer's own interim report for Stockholm (Cision, period YYYY-Qn). */
  cross_check?: RevenueCheck | null;
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
  revenue_fy0: number | null; revenue_fy1: number | null; revenue_growth: number; revenue_analysts: number | null;
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
}
interface LeopoldLead { long_weight: number; status: string; }
export interface BottleneckEntry {
  rank: number; symbol: string; name: string; layer: string;
  /** Traditional Chinese name stated by the exchange, the company or Chinese Wikipedia; null when none exists. */
  name_zh?: string | null; name_zh_source?: string | null; archetype: "EXPLOSION" | "COMPOUNDER"; score: number;
  role: string; role_source: { url: string; date: string };
  /** Traditional Chinese rendering of our own role description (config/bottleneck-layers-v3.json); the English stays shown. */
  role_zh?: string | null; outlook?: Outlook | null;
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

function validRevenueCheck(raw: any): boolean {
  if (raw === undefined || raw === null) return true;
  const rule = typeof raw === "object" && typeof raw.source_id === "string" && Object.hasOwn(REVENUE_SOURCES, raw.source_id)
    ? REVENUE_SOURCES[raw.source_id]! : null;
  return rule !== null && https(raw.source_url) && typeof raw.period === "string" && rule.period.test(raw.period)
    && raw.currency === rule.currency && optNum(raw.revenue_yoy) && optNum(raw.cumulative_yoy) && (num(raw.revenue_yoy) || num(raw.cumulative_yoy));
}

function validOutlook(raw: any): boolean {
  if (raw === undefined || raw === null) return true;
  if (typeof raw !== "object" || !Array.isArray(raw.scenarios) || raw.scenarios.length > 3
    || !raw.scenarios.every((row: any) => row && SCENARIOS.has(row.kind) && num(row.change))) return false;
  const o = raw.orders;
  const ordersOk = o === null || o === undefined
    || (o.kind === "NOT_DISCLOSED" && optStr(o.reason, 200))
    || ((o.kind === "RPO" || o.kind === "BACKLOG") && num(o.amount) && o.amount > 0 && https(o.source_url) && optStr(o.currency, 8)
      && optStr(o.as_of, 12) && optNum(o.yoy) && optStr(o.scope, 40) && optStr(o.source, 120)
      && (o.intake_quarter === undefined || o.intake_quarter === null || (num(o.intake_quarter.amount) && optNum(o.intake_quarter.yoy)))
      && (o.guidance === undefined || o.guidance === null || (num(o.guidance.amount) && optNum(o.guidance.year) && optNum(o.guidance.previous))));
  const c = raw.consensus;
  const consensusOk = c === null || c === undefined || (typeof c === "object" && num(c.revenue_growth) && https(c.source_url)
    && ["revenue_fy0", "revenue_fy1", "revenue_analysts", "eps_fy0", "eps_fy1", "eps_growth", "eps_analysts", "target_mean",
      "target_analysts", "price", "target_upside"].every(key => optNum(c[key])) && optStr(c.source, 80) && optStr(c.asof, 12));
  const s = raw.consensus_second;
  const secondOk = s === null || s === undefined || (typeof s === "object" && https(s.source_url)
    && ["target_mean", "target_upside", "target_analysts", "eps_fy0", "eps_fy1", "eps_growth", "eps_analysts"].every(key => optNum(s[key]))
    && optStr(s.source, 80) && optStr(s.asof, 12) && optStr(s.eps_fiscal_end, 20));
  return ordersOk && consensusOk && secondOk;
}

function validEntry(raw: any): raw is BottleneckEntry {
  return raw && Number.isInteger(raw.rank) && str(raw.symbol, 16) && str(raw.name, 160) && str(raw.layer, 40)
    && (raw.name_zh === undefined || raw.name_zh === null || (str(raw.name_zh, 40) && ZH_SOURCES.has(String(raw.name_zh_source))))
    && (raw.archetype === "EXPLOSION" || raw.archetype === "COMPOUNDER") && num(raw.score) && str(raw.role, 200)
    && optStr(raw.role_zh, 200) && validOutlook(raw.outlook)
    && raw.role_source && https(raw.role_source.url) && str(raw.role_source.date, 20)
    && raw.parts && ["layer_heat", "capture", "lead", "confirmation", "size", "penalty"].every(key => num(raw.parts[key]))
    && (raw.fundamentals === null || (raw.fundamentals && str(raw.fundamentals.source, 80) && https(raw.fundamentals.source_url)
      && str(raw.fundamentals.quarter_end, 12) && ["revenue_yoy", "revenue_yoy_prev", "gross_margin", "gross_margin_change", "rpo_yoy", "shares_yoy"].every(key => optNum(raw.fundamentals[key]))
      && [undefined, null, "OUTSTANDING", "DILUTED_WEIGHTED_AVERAGE"].includes(raw.fundamentals.shares_basis)
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

export function parseBottleneckV3(raw: unknown, now = Date.now()): BottleneckV3 | null {
  if (!raw || typeof raw !== "object") return null;
  const doc = raw as any;
  if (doc.schema !== "v213-bottleneck-top20-v3-sealed" || !str(doc.generated_at, 30) || !v213ReportAgeFresh([doc.generated_at], now)) return null;
  if (!Array.isArray(doc.top) || doc.top.length < 10 || doc.top.length > 20 || !doc.top.every(validEntry)) return null;
  if (!doc.top.every((entry: BottleneckEntry, index: number) => entry.rank === index + 1)) return null;
  if (!Array.isArray(doc.industries) || doc.industries.length < 3 || doc.industries.length > 20 || !doc.industries.every(validIndustry)) return null;
  const serenity = doc.serenity_source && https(doc.serenity_source.url) ? { url: doc.serenity_source.url, latest_post_at: doc.serenity_source.latest_post_at ?? null } : null;
  const leopold = doc.leopold_filing && https(doc.leopold_filing.url) ? doc.leopold_filing : null;
  const deep = doc.deep_reports && typeof doc.deep_reports === "object" && !Array.isArray(doc.deep_reports) ? doc.deep_reports : {};
  const top = doc.top.map((entry: BottleneckEntry) => ({ ...entry, market: closeLongTerm(entry.market, doc.generated_at.slice(0, 10)) }));
  return { generated_at: doc.generated_at, serenity_source: serenity, leopold_filing: leopold, top, industries: doc.industries, deep_reports: deep };
}

export async function loadBottleneckV3(view: PublicSnapshotView): Promise<BottleneckV3 | null> {
  if (view.integrity !== "sealed") return null;
  return parseBottleneckV3(await view.json<unknown>([BOTTLENECK_V3_KEY]));
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
const SCENARIO_NOTE = "股價情境＝分析師本財年→下一財年共識成長，套用目前股價與估值倍數的算術推算；市場若已反映部分成長，實際漲幅較小。非預測、非投資建議。";

/** "目前訂單": SEC remaining performance obligations or the company's own order backlog, else why none is shown. */
function currentOrders(outlook: Outlook | null | undefined, filer: boolean): string {
  const o = outlook?.orders;
  if (!o) return filer ? "目前訂單：最新 10-Q／10-K 未申報剩餘履約義務（RPO）。" : "目前訂單：非 SEC 定期申報公司，未取得公司公布的在手訂單。";
  if (o.kind === "NOT_DISCLOSED") return `目前訂單：未揭露${o.reason ? `（${o.reason}）` : ""}。`;
  const label = o.kind === "RPO" ? "剩餘履約義務（RPO，已簽約未認列）" : `在手訂單${o.scope ? `（${o.scope}）` : ""}`;
  const yoy = o.yoy === null || o.yoy === undefined ? "" : `，年增 ${pct(o.yoy, 0)}`;
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
function futureOutlook(outlook: Outlook | null | undefined): string[] {
  const lines: string[] = [];
  const o = outlook?.orders;
  if (o && o.kind !== "NOT_DISCLOSED") {
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
  if (!c) lines.push("分析師營收共識：未取得。");
  else lines.push(`分析師營收共識（非訂單）：下一財年營收 ${pct(c.revenue_growth, 1)}${c.revenue_analysts ? `（${c.revenue_analysts} 位）` : ""}`
    + `${c.eps_growth === null || c.eps_growth === undefined ? "" : `；EPS ${pct(c.eps_growth, 1)}${c.eps_analysts ? `（${c.eps_analysts} 位）` : ""}`}。`);
  return lines;
}

/** Price change if the consensus is realized at unchanged valuation multiples, and the mean analyst target. */
function scenarioBlocks(outlook: Outlook | null | undefined, compact: boolean): unknown[] {
  const c = outlook?.consensus;
  const rows = outlook?.scenarios ?? [];
  if (!c || rows.length === 0) return [uiText("若實現的股價情境：無分析師共識可推算。", "xs", T.ink)];
  const analysts = c.revenue_analysts ?? 0;
  if (compact && analysts < MIN_ANALYSTS) return [uiText(`若實現的股價情境：分析師樣本不足（${analysts} 位），不列推算。`, "xs", T.ink)];
  const sub = (kind: ScenarioKind) => kind === "ANALYST_TARGET" ? (c.target_analysts ? `${c.target_analysts} 位` : undefined)
    : kind === "EPS_CONSTANT_PE" ? (c.eps_analysts ? `${c.eps_analysts} 位` : undefined) : (c.revenue_analysts ? `${c.revenue_analysts} 位` : undefined);
  return [
    uiText("若實現的股價情境", "xxs", T.ink, { weight: "bold" }),
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

/** Order data older than this is not extrapolated (a stale order book says nothing about the next year). */
const ORDER_EXTRAPOLATION_MAX_AGE_DAYS = 200;
/** Above this year-on-year growth an order book usually changed scope (a new contract class, a restatement): no extrapolation. */
const ORDER_EXTRAPOLATION_MAX_YOY = 1.0;
const DAY_MS = 86_400_000;

export interface HorizonForecast {
  /** Rolling horizons from the report date (null when no supported input). */
  m6: string | null; y1: string | null;
  /** End months of the two horizons ("2027-03"), shown in the detail. */
  ends: { m6: string; y1: string };
  /** A figure for a stated fixed period (annual guidance) instead of rolling horizons. */
  fixed?: { label: string; value: string };
  basis: string;
}

/** Operator 2026-09-27: explicit 6-month and 1-year horizons, and a future ORDER estimate that is not the price scenario.
 * Both horizons run from the report date (Astra review: never from an older disclosure date, never a fiscal year relabelled).
 * Orders: the disclosed order book (RPO or backlog, a stock) extrapolated from its disclosure date to the report date + 6
 * months and + 12 months at its disclosed year-on-year growth, only for recent data (<= 200 days old, not after the report)
 * and growth in (-100%, +100%]; the company's own new-order guidance is shown for its stated year, not as a rolling horizon;
 * otherwise nothing. Price: the analysts' 12-month mean target (at least MIN_ANALYSTS), with 6 months as the time-proportional
 * share of that return (a stated assumption). Arithmetic, never a prediction. */
export function horizonForecast(doc: BottleneckV3, entry: BottleneckEntry): { orders: HorizonForecast; price: HorizonForecast } {
  const report = Date.parse(doc.generated_at);
  const endM6 = report + 182.5 * DAY_MS;
  const endY1 = report + 365 * DAY_MS;
  const month = (ms: number) => new Date(ms).toISOString().slice(0, 7);
  const ends = { m6: month(endM6), y1: month(endY1) };
  const o = entry.outlook?.orders;
  const { filer } = ordersOf(doc, entry.symbol);
  const disclosed = o && o.kind !== "NOT_DISCLOSED" ? o : null;
  // A real calendar date only (a malformed or partial date is never read leniently).
  const asOf = disclosed && isoDay(disclosed.as_of) ? Date.parse(`${disclosed.as_of}T00:00:00Z`) : NaN;
  const ageDays = (report - asOf) / DAY_MS;
  const reportYear = new Date(report).getUTCFullYear();
  let orders: HorizonForecast;
  const guidance = newOrderGuidance(disclosed);  // annual new-order guidance only (the same rule as the detail line)
  const grow = (end: number) => disclosed && num(disclosed.yoy) ? disclosed.amount * Math.pow(1 + disclosed.yoy, (end - asOf) / (365 * DAY_MS)) : NaN;
  const extrapolated = [grow(endM6), grow(endY1)];
  if (disclosed && num(disclosed.yoy) && disclosed.yoy > -1 && disclosed.yoy <= ORDER_EXTRAPOLATION_MAX_YOY && num(disclosed.amount)
      && disclosed.amount > 0 && Number.isFinite(ageDays) && ageDays >= -1 && ageDays <= ORDER_EXTRAPOLATION_MAX_AGE_DAYS
      && extrapolated.every(value => Number.isFinite(value) && value > 0)) {
    orders = { m6: money(extrapolated[0]!, disclosed.currency), y1: money(extrapolated[1]!, disclosed.currency), ends,
      basis: `${disclosed.kind === "RPO" ? "RPO" : "在手訂單"}餘額依年增${pct(disclosed.yoy, 0)}自${day(disclosed.as_of)}外推` };
  } else if (guidance && guidance.year! >= reportYear && guidance.year! <= reportYear + 1) {
    orders = { m6: null, y1: null, ends, fixed: { label: `${guidance.year}年全年`, value: money(guidance.amount, disclosed!.currency) },
      basis: "公司新接訂單指引（全年，非滾動12個月）" };
  } else {
    const reason = !disclosed ? (filer ? "未申報 RPO" : "公司未公布訂單")
      : !Number.isFinite(ageDays) ? "訂單日期不明，不外推"
      : ageDays < -1 ? "訂單日期晚於報告日，不採用"
      : ageDays > ORDER_EXTRAPOLATION_MAX_AGE_DAYS ? "訂單資料過舊，不外推"
      : num(disclosed.yoy) && disclosed.yoy > ORDER_EXTRAPOLATION_MAX_YOY ? `年增${pct(disclosed.yoy, 0)}過高（多為口徑變動），不外推`
      : num(disclosed.yoy) && disclosed.yoy <= -1 ? "訂單大幅萎縮，不外推"
      : num(disclosed.yoy) ? "外推結果超出可表示範圍，不採用" : "無年增可外推";
    orders = { m6: null, y1: null, ends, basis: reason };
  }
  const c = entry.outlook?.consensus;
  const upside = c?.target_upside;
  const analysts = c?.target_analysts ?? 0;
  let price: HorizonForecast;
  const halfYear = num(upside) && upside > -1 ? Math.pow(1 + upside, 0.5) - 1 : NaN;
  const printable = (value: number) => Number.isFinite(value) && Number.isFinite(value * 100);
  if (c && num(upside) && upside > -1 && printable(upside) && printable(halfYear) && num(analysts) && analysts >= MIN_ANALYSTS) {
    price = { m6: pct(halfYear, 0), y1: pct(upside, 0), ends,
      basis: `分析師12個月平均目標價（${analysts}位）；6個月按時間比例（假設）` };
  } else {
    price = { m6: null, y1: null, ends, basis: !c || !num(upside) ? "無分析師目標價" : upside <= -1 || !printable(upside) ? "目標價資料異常，不採用"
      : `目標價樣本不足（${num(analysts) ? analysts : 0}位）` };
  }
  return { orders, price };
}

const horizonTile = (label: string, value: HorizonForecast): [string, string, string] =>
  value.fixed ? [label, `${value.fixed.label} ${value.fixed.value}`, value.basis]
    : [label, value.y1 === null ? "未揭露" : `1年 ${value.y1}`, value.m6 === null ? value.basis : `6個月 ${value.m6}・${value.basis}`];

/** The three card tiles, identical on every Top20 card (operator 2026-09-26: one layout; current orders, the future
 * estimate and the price if realized): [label, value, sub]. */
export function outlookTiles(doc: BottleneckV3, entry: BottleneckEntry): [string, string, string][] {
  const outlook = entry.outlook;
  const o = outlook?.orders;
  const secFiler = ordersOf(doc, entry.symbol).filer || entry.fundamentals?.source === "SEC EDGAR XBRL companyfacts";
  const orders: [string, string, string] = !o ? ["現有訂單", "未揭露", secFiler ? "未申報 RPO" : "公司未公布"]
    : o.kind === "NOT_DISCLOSED" ? ["現有訂單", "未揭露", "公司未公布"]
    : ["現有訂單", money(o.amount, o.currency), `${o.kind === "RPO" ? "RPO" : "在手"} ${day(o.as_of)}${o.yoy === null || o.yoy === undefined ? "" : ` 年增${pct(o.yoy, 0)}`}`];
  const forecast = horizonForecast(doc, entry);
  return [orders, horizonTile("未來訂單預估", forecast.orders), horizonTile("若實現股價", forecast.price)];
}

/** The two forecast lines of the detail card. */
function horizonLines(doc: BottleneckV3, entry: BottleneckEntry): string[] {
  const { orders, price } = horizonForecast(doc, entry);
  const line = (label: string, value: HorizonForecast) => value.fixed ? `${label}：${value.fixed.label} ${value.fixed.value}（${value.basis}）。`
    : value.y1 === null && value.m6 === null ? `${label}：未揭露（${value.basis}）。`
    : `${label}：6個月（至${value.ends.m6}）${value.m6 ?? "未揭露"}、1年（至${value.ends.y1}）${value.y1 ?? "未揭露"}（${value.basis}）。`;
  return [line("未來訂單預估", orders), line("若實現股價", price)];
}

/** Operator 2026-09-26: current orders, the future estimate and the price scenario if realized on every Top20 card
 * (the same three tiles) and in full on the detail card. */
function orderSection(doc: BottleneckV3, entry: BottleneckEntry, compact = true) {
  const { filer } = ordersOf(doc, entry.symbol);
  const outlook = entry.outlook;
  const c = outlook?.consensus;
  if (compact) {
    return section("訂單與成長情境", [
      uiBox(outlookTiles(doc, entry).map(([label, value, sub]) => statTile(label, value, undefined, sub)), { layout: "horizontal", spacing: "sm" }),
      footnote("未來訂單預估＝已揭露訂單餘額自揭露日依年增外推至今日起6個月／1年（或公司全年接單指引）；若實現股價＝分析師12個月平均目標價，6個月按時間比例；皆為算術推算，非預測、非投資建議；營收情境與已簽約訂單的營收覆蓋見「瓶頸詳情」。"),
    ], "key");
  }
  return section("訂單與成長情境", [
    uiText(currentOrders(outlook, filer || entry.fundamentals?.source === "SEC EDGAR XBRL companyfacts"), "xs", T.ink),
    ...orderFloor(doc, entry),
    ...horizonLines(doc, entry).map(line => uiText(line, "xs", T.ink, { weight: "bold" })),
    ...futureOutlook(outlook).map(line => uiText(line, "xs", T.ink)),
    ...scenarioBlocks(outlook, compact),
    footnote(c ? `${SCENARIO_NOTE}共識：${sourceZh(c.source)}，${day(c.asof)}` : SCENARIO_NOTE),
    ...(compact ? [] : [outlook?.orders && outlook.orders.kind !== "NOT_DISCLOSED" ? footnote(`訂單來源：${sourceZh(outlook.orders.source)}：${outlook.orders.source_url}`.slice(0, 220)) : null,
      c ? footnote(`預估來源：${c.source_url}`) : null].filter(Boolean)),
  ], "key");
}

/** lean: the fallback form when twenty full cards would not fit five carousels (one LINE reply); the outlook keeps its
 * first and last line (current orders, the scenario) and the order floors move to the detail card. */
function companyBubble(doc: BottleneckV3, entry: BottleneckEntry, lean = false) {
  const fund = entry.fundamentals;
  const lead = entry.rank === 1;
  const long = longTerm(entry.market);
  return {
    type: "bubble", size: "mega",
    header: productHeader(`瓶頸爆發 TOP20 · ${entry.archetype === "EXPLOSION" ? "爆發型" : "核心複利型"}`, `${entry.symbol}｜${chineseName(entry)}`.slice(0, 60), [
      uiText(entry.name.slice(0, 80), "xxs", T.headerMuted),
      uiBox([rankBadge(entry.rank, lead), chip(layerName(doc, entry.layer)), chip(`${entry.score.toFixed(1)} 分`)], { layout: "horizontal", spacing: "sm" }),
    ]),
    body: uiBox([
      section("瓶頸位置", [uiText(entry.role_zh ?? entry.role, "sm", T.ink),
        footnote(`角色來源 ${entry.role_source.date}：${entry.role_source.url}`.slice(0, 180))], "key"),
      section("分數組成（0–100）", [
        meter(entry.score),
        stackedBar([
          { label: "層級熱度", weight: Math.round(entry.parts.layer_heat) }, { label: "公司捕獲", weight: Math.round(entry.parts.capture) },
          { label: "市場確認", weight: Math.round(entry.parts.confirmation) }, { label: "爆發性", weight: Math.round(entry.parts.size) },
        ]),
        ...(entry.parts.penalty > 0 ? [uiText(`稀釋／融資扣分 -${entry.parts.penalty}`, "xxs", T.negative)] : []),
      ]),
      section("公司數據", [
        uiBox([statTile("最新季營收年增", pct(fund?.revenue_yoy ?? null, 0)), statTile("毛利率變化", fund?.gross_margin_change === null || fund?.gross_margin_change === undefined ? "未揭露" : `${fund.gross_margin_change >= 0 ? "+" : ""}${(fund.gross_margin_change * 100).toFixed(1)}pp`)], { layout: "horizontal", spacing: "sm" }),
        uiBox([statTile("6個月報酬", pct(entry.market.ret_6m, 0)), statTile("2年年化", long.value, undefined, long.sub)], { layout: "horizontal", spacing: "sm" }),
        ...(long.event ? [footnote(`上市沿革：${long.event}`)] : []),
        footnote(fund ? `財報：${sourceZh(fund.source)}，季末 ${fund.quarter_end}` : "財報：未取得可比季度"),
        ...(fund?.cross_check ? [footnote(revenueCheck(fund.cross_check))] : []),
        footnote(`股價：${sourceZh(entry.market.source)}，至 ${entry.market.asof}；市值 ${cap(entry.market_cap_usd)}`),
        ...(entry.market.cross_check ? [footnote(exchangeCheck(entry.market.cross_check))] : []),
      ]),
      lean ? section("訂單與成長情境", [uiText(outlookTiles(doc, entry).map(([label, value, sub]) => `${label} ${value}（${sub}）`).join("\n"), "xs", T.ink)], "key")
        : orderSection(doc, entry),
      ...(entry.name_zh ? [footnote(`中文名來源：${ZH_SOURCE_LABEL[entry.name_zh_source ?? ""] ?? "已核對"}`)] : []),
    ], { paddingAll: "lg", spacing: "md" }),
    footer: uiBox([menuAction("瓶頸詳情", `瓶頸詳情 ${entry.symbol}`), menuAction("產業爆發榜", "產業爆發榜")], footerStyle),
  };
}

/** The long-term figure in one line of text: value, its explanation and the verified event. */
function longTermText(market: Market): string {
  const long = longTerm(market);
  return `${long.value}${long.sub ? `（${long.sub}）` : ""}${long.event ? `；${long.event}` : ""}`;
}

export function buildBottleneckTop20Messages(doc: BottleneckV3, style: "flex" | "text"): LineOutboundMessage[] {
  if (style === "text") {
    const lines = doc.top.map(entry => `${entry.rank}. ${entry.symbol} ${chineseName(entry)}（${entry.name}）｜${layerName(doc, entry.layer)}｜${entry.score.toFixed(1)}分｜營收年增 ${pct(entry.fundamentals?.revenue_yoy ?? null, 0)}｜6個月 ${pct(entry.market.ret_6m, 0)}｜2年年化 ${longTermText(entry.market)}`);
    const messages: LineOutboundMessage[] = [{ type: "text", text: [
      `瓶頸爆發 TOP20（v3，產生 ${doc.generated_at}）`,
      "排序：層級熱度＋公司捕獲＋社群與機構線索＋市場確認＋爆發性；2年年化報酬為負者排除。分拆、恢復交易、IPO 或重整新股不足2年者，改用已核實正常交易首日以來年化（至少1年，非2年）；沿革未核實且價格不足2年者不列入。非投資建議。",
      ...lines, "輸入「瓶頸詳情 代號」看逐項數據與來源；「產業爆發榜」看 Leopold 邏輯產業排序。",
    ].join("\n").slice(0, 4900) }];
    assertLineMessages(messages);
    return messages;
  }
  const alt = (index: number, total: number) => `瓶頸爆發 TOP20（${index + 1}/${total}）`;
  try {
    return packCarousels(doc.top.map(entry => companyBubble(doc, entry)), alt);
  } catch (error) {
    // Twenty full cards past five carousels (longer sourced texts): the lean cards, never a failed TOP20 reply.
    if (!(error instanceof Error) || error.message !== "LINE_MESSAGE_COUNT_INVALID") throw error;
    return packCarousels(doc.top.map(entry => companyBubble(doc, entry, true)), alt);
  }
}

const gmText = (value: number | null | undefined) => value === null || value === undefined ? "未揭露" : `${(value * 100).toFixed(1)}%`;
/** The basis of a share-count change when it is not shares outstanding. */
const sharesBasis = (fund: Fundamentals) => fund.shares_yoy !== null && fund.shares_basis === "DILUTED_WEIGHTED_AVERAGE" ? "稀釋加權平均股數" : undefined;
const ppShort = (value: number | null | undefined) => value === null || value === undefined ? "未揭露" : `${value >= 0 ? "+" : ""}${(value * 100).toFixed(1)}pp`;
const row = (...tiles: unknown[]) => uiBox(tiles, { layout: "horizontal", spacing: "sm" });

/** Operator 2026-09-26: the detail of every Top20 entry as a card: all filing and market figures, current orders,
 * the future estimate, the price scenarios if realized, and every source. Leads (Serenity, 13F) stay out, as on the card. */
function detailBubble(doc: BottleneckV3, entry: BottleneckEntry) {
  const fund = entry.fundamentals;
  const long = longTerm(entry.market);
  const accel = fund ? ppShort(accelOf(fund)) : "未揭露";
  return {
    type: "bubble", size: "mega",
    header: productHeader(`瓶頸詳情 · #${entry.rank} · ${entry.archetype === "EXPLOSION" ? "爆發型（市值<US$10B）" : "核心複利型"}`, `${entry.symbol}｜${chineseName(entry)}`.slice(0, 60), [
      uiText(entry.name.slice(0, 80), "xxs", T.headerMuted),
      uiBox([chip(layerName(doc, entry.layer)), chip(`${entry.score.toFixed(1)} 分`)], { layout: "horizontal", spacing: "sm" }),
    ]),
    body: uiBox([
      section("瓶頸位置", [uiText(entry.role_zh ?? entry.role, "sm", T.ink), ...(entry.role_zh ? [footnote(`原文：${entry.role}`)] : []),
        footnote(`角色來源 ${entry.role_source.date}：${entry.role_source.url}`.slice(0, 180))], "key"),
      section("財報數據", fund ? [
        row(statTile("最新季營收年增", pct(fund.revenue_yoy, 0)), statTile("前一季年增", pct(fund.revenue_yoy_prev, 0)), statTile("加速度", accel)),
        row(statTile("毛利率", gmText(fund.gross_margin)), statTile("毛利率年變化", ppShort(fund.gross_margin_change)), statTile("股數年增", pct(fund.shares_yoy, 1), undefined, sharesBasis(fund))),
        row(statTile("RPO 年增", pct(fund.rpo_yoy, 0)), statTile("季末", fund.quarter_end)),
        footnote(`${sourceZh(fund.source)}：${fund.source_url}`.slice(0, 220)),
        ...(fund.cross_check ? [footnote(`${revenueCheck(fund.cross_check)}：${fund.cross_check.source_url}`.slice(0, 220))] : []),
      ] : [uiText("未取得可比季度（不以估計替代）。", "xs", T.ink)]),
      section("市場數據", [
        row(statTile("6個月報酬", pct(entry.market.ret_6m, 0)), statTile("2年年化", long.value, undefined, long.sub), statTile("市值", cap(entry.market_cap_usd))),
        ...(long.event ? [uiText(`上市沿革：${long.event}`, "xs", T.ink), ...long.sources.map(source => footnote(`沿革來源 ${source}`.slice(0, 220)))] : []),
        footnote(`${sourceZh(entry.market.source)}，至 ${entry.market.asof}：${entry.market.source_url}`.slice(0, 220)),
        ...(entry.market.cross_check ? [footnote(`${exchangeCheck(entry.market.cross_check)}：${entry.market.cross_check.source_url}`.slice(0, 220))] : []),
      ]),
      orderSection(doc, entry, false),
      ...(entry.name_zh ? [footnote(`中文名來源：${ZH_SOURCE_LABEL[entry.name_zh_source ?? ""] ?? "已核對"}`)] : []),
      footnote("非投資建議，不自動下單。"),
    ], { paddingAll: "lg", spacing: "md" }),
    footer: uiBox([menuAction("回瓶頸 TOP20", "TOP20"), menuAction("產業爆發榜", "產業爆發榜")], footerStyle),
  };
}

function detailText(doc: BottleneckV3, entry: BottleneckEntry): string {
  const fund = entry.fundamentals;
  const long = longTerm(entry.market);
  const outlook = entry.outlook;
  const scenarios = (outlook?.scenarios ?? []).map(row => `${SCENARIO_LABEL[row.kind]} ${pct(row.change, 0)}`).join("、");
  const analysts = outlook?.consensus?.revenue_analysts ?? 0;
  return [
    `【瓶頸詳情｜#${entry.rank} ${entry.symbol} ${chineseName(entry)}（${entry.name}）】`,
    `型態：${entry.archetype === "EXPLOSION" ? "瓶頸爆發型（市值<US$10B）" : "核心複利型"}；市值 ${cap(entry.market_cap_usd)}`,
    `瓶頸位置：${entry.role_zh ?? entry.role}${entry.role_zh ? `（原文：${entry.role}）` : ""}`,
    fund ? `財報（${sourceZh(fund.source)}，季末 ${fund.quarter_end}）：營收年增 ${pct(fund.revenue_yoy)}，前一季年增 ${pct(fund.revenue_yoy_prev)}（加速度 ${pp(accelOf(fund))}）；毛利率 ${gmText(fund.gross_margin)}（年變化 ${pp(fund.gross_margin_change)}）；剩餘履約義務年增 ${pct(fund.rpo_yoy)}；股數年增 ${pct(fund.shares_yoy)}${sharesBasis(fund) ? `（${sharesBasis(fund)}）` : ""}\n來源：${fund.source_url}` : "財報：未取得可比季度（不以估計替代）。",
    ...(fund?.cross_check ? [`${revenueCheck(fund.cross_check)}\n來源：${fund.cross_check.source_url}`] : []),
    `股價（${sourceZh(entry.market.source)}，至 ${entry.market.asof}）：6個月 ${pct(entry.market.ret_6m)}、2年年化 ${long.value}${long.sub ? `（${long.sub}）` : ""}\n來源：${entry.market.source_url}`,
    ...(long.event ? [`上市沿革：${long.event}\n沿革來源：${long.sources.join("；")}`] : []),
    ...(entry.market.cross_check ? [exchangeCheck(entry.market.cross_check)] : []),
    currentOrders(outlook, ordersOf(doc, entry.symbol).filer || fund?.source === "SEC EDGAR XBRL companyfacts")
      + (outlook?.orders && outlook.orders.kind !== "NOT_DISCLOSED" ? `\n來源：${outlook.orders.source_url}` : ""),
    ...horizonLines(doc, entry),
    ...futureOutlook(outlook),
    scenarios ? `若實現的股價情境：${scenarios}${analysts < MIN_ANALYSTS ? `（僅 ${analysts} 位分析師，參考性低）` : ""}${outlook?.consensus ? `\n來源：${outlook.consensus.source_url}` : ""}` : "若實現的股價情境：無分析師共識可推算。",
    `${SCENARIO_NOTE}不自動下單。`,
  ].join("\n");
}

/** Cut at the last whole line within the limit, so a source line is never broken off mid-URL. */
function atLineBoundary(text: string, limit: number): string {
  if (text.length <= limit) return text;
  const cut = text.lastIndexOf("\n", limit - 2);
  return `${text.slice(0, cut > 0 ? cut : limit - 1)}…`;
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
    ? packCarousels([detailBubble(doc, entry)], () => `瓶頸詳情｜${entry.symbol} ${chineseName(entry)}`.slice(0, 400))
    : [{ type: "text", text: atLineBoundary(detailText(doc, entry), 4900) }];
  const reportMessages = report ? (style === "flex" ? buildCompanyDataReportFlex(report, doc.generated_at, ["回瓶頸 TOP20", "TOP20"])
    : buildCompanyDataReportMessages(report, doc.generated_at)) : [];
  const messages = [...detail, ...reportMessages].slice(0, 5);
  assertLineMessages(messages);
  return messages;
}

function industryBubble(doc: BottleneckV3, industry: IndustryEntry) {
  const members = doc.top.filter(entry => entry.layer === industry.id).map(entry => entry.name_zh ? `${entry.symbol} ${entry.name_zh}` : entry.symbol);
  const news = industry.news;
  return {
    type: "bubble", size: "mega",
    header: productHeader(`產業爆發榜 · Leopold 因果鏈：${CHAIN_ZH[industry.chain] ?? industry.chain}`, industry.name_zh, [
      uiBox([rankBadge(industry.rank, industry.rank === 1), chip(`爆發力 ${industry.explosiveness.toFixed(1)}`)], { layout: "horizontal", spacing: "sm" }),
    ]),
    body: uiBox([
      section("Leopold 邏輯：綁定限制", [uiText(industry.leopold_constraint_zh ?? industry.leopold_constraint, "sm", T.ink),
        ...(industry.leopold_constraint_zh ? [footnote(`原文：${industry.leopold_constraint}`)] : [])], "key"),
      section("資料訊號", [
        meter(industry.explosiveness),
        uiBox([statTile("營收年增中位數", pct(industry.median_revenue_yoy, 0)), statTile("加速度中位數", industry.median_acceleration === null || industry.median_acceleration === undefined ? "未揭露" : `${industry.median_acceleration >= 0 ? "+" : ""}${(industry.median_acceleration * 100).toFixed(0)}pp`)], { layout: "horizontal", spacing: "sm" }),
        uiBox([statTile("SEC申報熱度", newsRatio(news), undefined, news ? `近30天 ${news.recent_30d}／前60天 ${news.prior_60d}` : undefined), statTile("6個月股價中位數", pct(industry.median_return_6m, 0))], { layout: "horizontal", spacing: "sm" }),
      ]),
      section("本輪 TOP20 成員", [uiText(members.length ? members.join("、") : "（無）", "sm", T.ink)], "context"),
      divider(),
      footnote("爆發力＝因果鏈位置35＋機構持倉權重25＋營收加速20＋SEC申報熱度10＋社群熱度10（線索分數不單獨列出）。非投資建議。"),
    ], { paddingAll: "lg", spacing: "md" }),
    footer: uiBox([menuAction("瓶頸爆發 TOP20", "TOP20"), menuAction("回功能選單", "選單")], footerStyle),
  };
}

export function buildIndustryExplosionMessages(doc: BottleneckV3, style: "flex" | "text"): LineOutboundMessage[] {
  if (style === "text") {
    const lines = doc.industries.map(industry => `${industry.rank}. ${industry.name_zh}｜爆發力 ${industry.explosiveness.toFixed(1)}｜營收年增中位數 ${pct(industry.median_revenue_yoy, 0)}｜SEC申報熱度 ${newsRatio(industry.news)}｜6個月股價中位數 ${pct(industry.median_return_6m, 0)}`);
    const messages: LineOutboundMessage[] = [{ type: "text", text: [`產業爆發榜（Leopold 因果鏈，產生 ${doc.generated_at}）`, ...lines, "非投資建議。"].join("\n").slice(0, 4900) }];
    assertLineMessages(messages);
    return messages;
  }
  return packCarousels(doc.industries.slice(0, 10).map(industry => industryBubble(doc, industry)), (index, total) => `產業爆發榜（${index + 1}/${total}）`);
}
