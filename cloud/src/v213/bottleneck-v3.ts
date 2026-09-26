/** Bottleneck-explosion Top20 v3 and the Leopold-led industry ranking (scripts/bottleneck_top20_v3.py).
 *
 * Sealed as the lazy object `v213:bottleneck-top20:v3`. Leads (Serenity posts, 13F positions) weight conviction
 * but are never shown as company facts; every figure carries its source and date. A malformed or stale document
 * (older than the report bound, report-age.ts) gives null and the caller keeps the seven-field Top20.
 */
import { assertLineMessages, type LineOutboundMessage } from "../line-messages";
import type { PublicSnapshotView } from "./public-snapshot";
import { v213ReportAgeFresh } from "./report-age";
import { buildCompanyDataReportFlex, buildCompanyDataReportMessages, validateCompanyDataReport } from "./deep-analysis";
import {
  LINE_THEME as T, chip, divider, footerStyle, footnote, menuAction, meter, packCarousels, productHeader, rankBadge,
  section, stackedBar, statTile, uiBox, uiText,
} from "./line-theme";

export const BOTTLENECK_V3_KEY = "v213:bottleneck-top20:v3";

interface Fundamentals {
  source: string; source_url: string; quarter_end: string; revenue_yoy: number | null; revenue_yoy_prev: number | null;
  gross_margin: number | null; gross_margin_change: number | null; rpo_yoy: number | null; shares_yoy: number | null;
}
interface Market {
  source: string; source_url: string; asof: string; ret_6m: number | null; ret_1y: number | null; cagr_2y: number | null; currency: string | null;
  /** Annualized since the first trading day, only for listings younger than two years (null otherwise). */
  cagr_listed?: number | null; history_start?: string | null;
}
interface SerenityLead { mentions: number; bullish: number; bearish: number; stance: string; latest_at: string | null; latest_url: string | null; }
interface LeopoldLead { long_weight: number; status: string; }
export interface BottleneckEntry {
  rank: number; symbol: string; name: string; layer: string;
  /** Traditional Chinese name stated by the exchange, the company or Chinese Wikipedia; null when none exists. */
  name_zh?: string | null; name_zh_source?: string | null; archetype: "EXPLOSION" | "COMPOUNDER"; score: number;
  role: string; role_source: { url: string; date: string };
  parts: { layer_heat: number; capture: number; lead: number; confirmation: number; size: number; penalty: number };
  fundamentals: Fundamentals | null; market: Market; market_cap_usd: number | null;
  serenity: SerenityLead | null; leopold: LeopoldLead | null;
}
export interface IndustryEntry {
  rank: number; id: string; name_zh: string; chain: string; leopold_constraint: string; explosiveness: number;
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

function validEntry(raw: any): raw is BottleneckEntry {
  return raw && Number.isInteger(raw.rank) && str(raw.symbol, 16) && str(raw.name, 160) && str(raw.layer, 40)
    && (raw.name_zh === undefined || raw.name_zh === null || (str(raw.name_zh, 40) && ZH_SOURCES.has(String(raw.name_zh_source))))
    && (raw.archetype === "EXPLOSION" || raw.archetype === "COMPOUNDER") && num(raw.score) && str(raw.role, 200)
    && raw.role_source && https(raw.role_source.url) && str(raw.role_source.date, 20)
    && raw.parts && ["layer_heat", "capture", "lead", "confirmation", "size", "penalty"].every(key => num(raw.parts[key]))
    && (raw.fundamentals === null || (raw.fundamentals && str(raw.fundamentals.source, 80) && https(raw.fundamentals.source_url)
      && str(raw.fundamentals.quarter_end, 12) && ["revenue_yoy", "revenue_yoy_prev", "gross_margin", "gross_margin_change", "rpo_yoy", "shares_yoy"].every(key => optNum(raw.fundamentals[key]))))
    && raw.market && str(raw.market.source, 80) && https(raw.market.source_url) && str(raw.market.asof, 12)
    && ["ret_6m", "ret_1y", "cagr_2y", "cagr_listed"].every(key => optNum(raw.market[key])) && optNum(raw.market_cap_usd)
    && (raw.market.history_start === undefined || raw.market.history_start === null || str(raw.market.history_start, 12))
    && (raw.serenity === null || (raw.serenity && Number.isInteger(raw.serenity.mentions) && str(raw.serenity.stance, 12)
      && (raw.serenity.latest_url === null || https(raw.serenity.latest_url))))
    && (raw.leopold === null || (raw.leopold && num(raw.leopold.long_weight) && str(raw.leopold.status, 12)));
}

function validIndustry(raw: any): raw is IndustryEntry {
  return raw && Number.isInteger(raw.rank) && str(raw.id, 40) && str(raw.name_zh, 40) && str(raw.chain, 30)
    && str(raw.leopold_constraint, 300) && num(raw.explosiveness)
    && ["median_revenue_yoy", "median_acceleration", "median_return_6m"].every(key => optNum(raw[key]))
    && num(raw.fund_13f_weight) && num(raw.serenity_heat)
    && (raw.news === null || (raw.news && Number.isInteger(raw.news.recent_30d) && Number.isInteger(raw.news.prior_60d) && optNum(raw.news.ratio)));
}

/** The sealed v3 document when valid and inside the report-age bound; otherwise null. */
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
  return { generated_at: doc.generated_at, serenity_source: serenity, leopold_filing: leopold, top: doc.top, industries: doc.industries, deep_reports: deep };
}

export async function loadBottleneckV3(view: PublicSnapshotView): Promise<BottleneckV3 | null> {
  if (view.integrity !== "sealed") return null;
  return parseBottleneckV3(await view.json<unknown>([BOTTLENECK_V3_KEY]));
}

const pct = (value: number | null | undefined, digits = 1) => value === null || value === undefined ? "未揭露" : `${value >= 0 ? "+" : ""}${(value * 100).toFixed(digits)}%`;
const pp = (value: number | null | undefined) => value === null || value === undefined ? "未揭露" : `${value >= 0 ? "+" : ""}${(value * 100).toFixed(1)}個百分點`;
const cap = (value: number | null) => value === null ? "未揭露" : value >= 1e12 ? `US$${(value / 1e12).toFixed(2)}T` : value >= 1e9 ? `US$${(value / 1e9).toFixed(1)}B` : `US$${(value / 1e6).toFixed(0)}M`;
const day = (value: string | null | undefined) => (value ?? "").slice(0, 10) || "未揭露";

function layerName(doc: BottleneckV3, id: string): string {
  return doc.industries.find(industry => industry.id === id)?.name_zh ?? id;
}

/** "中文名（來源）" or the explicit statement that no stated Chinese name exists (never a translation). */
export function chineseName(entry: Pick<BottleneckEntry, "name_zh" | "name_zh_source">): string {
  return entry.name_zh ? entry.name_zh : "無公認中文名";
}

/** The one long-term figure on every card: 2-year CAGR; a listing younger than two years says so and shows the
 * annualized return since its first trading day. */
function longTerm(market: Market): { value: string; sub: string | undefined } {
  if (market.cagr_2y !== null) return { value: pct(market.cagr_2y, 0), sub: undefined };
  return { value: "上市未滿2年", sub: `${day(market.history_start)}起年化 ${pct(market.cagr_listed ?? null, 0)}` };
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

function orderSection(doc: BottleneckV3, entry: BottleneckEntry) {
  const { orders, rpoYoy, rpoPeriod, filer } = ordersOf(doc, entry.symbol);
  if (orders) {
    const tile = (label: string, key: string) => {
      const coverage = orders.coverage[key];
      const floor = orders.floor[key];
      return statTile(label, floor !== null && floor !== undefined ? `≥${floor >= 0 ? "+" : ""}${floor.toFixed(0)}%` : "需新訂單", undefined,
        coverage === null || coverage === undefined ? "未揭露" : `已簽約覆蓋 ${coverage.toFixed(0)}%`);
    };
    return section("訂單實現下限（已簽約 RPO）", [
      uiBox([tile("6個月", "m6"), tile("1年", "m12"), tile("2年", "m24")], { layout: "horizontal", spacing: "sm" }),
      footnote(`${orders.form}（${orders.filed}）揭露的認列時程，RPO 基準日 ${orders.as_of}；營收成長下限＝已簽約金額÷目前營收水準−1，未計新訂單。`),
    ], "key");
  }
  const lines = !filer ? "非 SEC 定期申報公司：無剩餘履約義務（RPO）揭露，不推估訂單。"
    : rpoYoy !== null ? `剩餘履約義務（RPO）年增 ${pct(rpoYoy, 0)}（${rpoPeriod ?? "最新季"}）；最新財報未揭露認列時程，不推估6個月／1年／2年實現金額。`
      : "最新 10-Q／10-K 未申報剩餘履約義務（RPO），訂單能見度無法量化。";
  return section("訂單能見度（SEC 申報）", [uiText(lines, "xs", T.ink)], "context");
}

function companyBubble(doc: BottleneckV3, entry: BottleneckEntry) {
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
      section("瓶頸位置", [uiText(entry.role, "sm", T.ink), footnote(`角色來源 ${entry.role_source.date}：${entry.role_source.url}`.slice(0, 180))], "key"),
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
        footnote(fund ? `財報：${fund.source}，季末 ${fund.quarter_end}` : "財報：未取得可比季度"),
        footnote(`股價：${entry.market.source}，至 ${entry.market.asof}；市值 ${cap(entry.market_cap_usd)}`),
      ]),
      orderSection(doc, entry),
      ...(entry.name_zh ? [footnote(`中文名來源：${ZH_SOURCE_LABEL[entry.name_zh_source ?? ""] ?? "已核對"}`)] : []),
    ], { paddingAll: "lg", spacing: "md" }),
    footer: uiBox([menuAction("瓶頸詳情", `瓶頸詳情 ${entry.symbol}`), menuAction("產業爆發榜", "產業爆發榜")], footerStyle),
  };
}

export function buildBottleneckTop20Messages(doc: BottleneckV3, style: "flex" | "text"): LineOutboundMessage[] {
  if (style === "text") {
    const lines = doc.top.map(entry => `${entry.rank}. ${entry.symbol} ${chineseName(entry)}（${entry.name}）｜${layerName(doc, entry.layer)}｜${entry.score.toFixed(1)}分｜營收年增 ${pct(entry.fundamentals?.revenue_yoy ?? null, 0)}｜6個月 ${pct(entry.market.ret_6m, 0)}｜2年年化 ${longTerm(entry.market).value}`);
    const messages: LineOutboundMessage[] = [{ type: "text", text: [
      `瓶頸爆發 TOP20（v3，產生 ${doc.generated_at}）`,
      "排序：層級熱度＋公司捕獲＋社群與機構線索＋市場確認＋爆發性；2年年化報酬（未滿2年者為上市以來年化）為負者排除。非投資建議。",
      ...lines, "輸入「瓶頸詳情 代號」看逐項數據與來源；「產業爆發榜」看 Leopold 邏輯產業排序。",
    ].join("\n").slice(0, 4900) }];
    assertLineMessages(messages);
    return messages;
  }
  return packCarousels(doc.top.map(entry => companyBubble(doc, entry)), (index, total) => `瓶頸爆發 TOP20（${index + 1}/${total}）`);
}

export function buildBottleneckDetail(doc: BottleneckV3, symbol: string, style: "flex" | "text" = "text"): LineOutboundMessage[] | string {
  const entry = doc.top.find(item => item.symbol.toUpperCase() === symbol.toUpperCase());
  if (!entry) return `「${symbol}」不在本輪瓶頸爆發 TOP20（產生 ${doc.generated_at}）。`;
  // The company data report (SEC filings, business profile, thesis phase, order realization) when one is sealed.
  const raw = Object.hasOwn(doc.deep_reports, entry.symbol) ? doc.deep_reports[entry.symbol] : undefined;
  const report = raw ? validateCompanyDataReport(raw, entry.symbol) : null;
  if (report) {
    const messages = (style === "flex" ? buildCompanyDataReportFlex(report, doc.generated_at, ["回瓶頸 TOP20", "TOP20"])
      : buildCompanyDataReportMessages(report, doc.generated_at)).slice(0, 5);
    assertLineMessages(messages);
    return messages;
  }
  // No sealed report (non-SEC filers): the filing and price figures behind the card, each with its source.
  const fund = entry.fundamentals;
  const long = longTerm(entry.market);
  const text = [
    `【瓶頸詳情｜#${entry.rank} ${entry.symbol} ${chineseName(entry)}（${entry.name}）】`,
    `型態：${entry.archetype === "EXPLOSION" ? "瓶頸爆發型（市值<US$10B）" : "核心複利型"}；市值 ${cap(entry.market_cap_usd)}`,
    fund ? `財報（${fund.source}，季末 ${fund.quarter_end}）：營收年增 ${pct(fund.revenue_yoy)}，前一季年增 ${pct(fund.revenue_yoy_prev)}（加速度 ${fund.revenue_yoy !== null && fund.revenue_yoy_prev !== null ? pp(fund.revenue_yoy - fund.revenue_yoy_prev) : "未揭露"}）；毛利率 ${fund.gross_margin === null ? "未揭露" : (fund.gross_margin * 100).toFixed(1) + "%"}（年變化 ${pp(fund.gross_margin_change)}）；剩餘履約義務年增 ${pct(fund.rpo_yoy)}；股數年增 ${pct(fund.shares_yoy)}\n來源：${fund.source_url}` : "財報：未取得可比季度（不以估計替代）。",
    `股價（${entry.market.source}，至 ${entry.market.asof}）：6個月 ${pct(entry.market.ret_6m)}、2年年化 ${long.value}${long.sub ? `（${long.sub}）` : ""}\n來源：${entry.market.source_url}`,
    `非 SEC 定期申報公司：無 10-Q／10-K 深度報告與 RPO 認列時程，不推估訂單實現。非投資建議，不自動下單。`,
  ].join("\n");
  const messages: LineOutboundMessage[] = [{ type: "text", text: text.slice(0, 4900) }];
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
      section("Leopold 邏輯：綁定限制", [uiText(industry.leopold_constraint, "sm", T.ink)], "key"),
      section("資料訊號", [
        meter(industry.explosiveness),
        uiBox([statTile("營收年增中位數", pct(industry.median_revenue_yoy, 0)), statTile("加速度中位數", industry.median_acceleration === null ? "未揭露" : `${industry.median_acceleration >= 0 ? "+" : ""}${(industry.median_acceleration * 100).toFixed(0)}pp`)], { layout: "horizontal", spacing: "sm" }),
        uiBox([statTile("SEC申報熱度", news?.ratio === null || news === null ? "未取得" : `${news.ratio.toFixed(2)}x`, undefined, news ? `近30天 ${news.recent_30d}／前60天 ${news.prior_60d}` : undefined), statTile("6個月股價中位數", pct(industry.median_return_6m, 0))], { layout: "horizontal", spacing: "sm" }),
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
    const lines = doc.industries.map(industry => `${industry.rank}. ${industry.name_zh}｜爆發力 ${industry.explosiveness.toFixed(1)}｜營收年增中位數 ${pct(industry.median_revenue_yoy, 0)}｜SEC申報熱度 ${industry.news?.ratio ?? "未取得"}x｜6個月股價中位數 ${pct(industry.median_return_6m, 0)}`);
    const messages: LineOutboundMessage[] = [{ type: "text", text: [`產業爆發榜（Leopold 因果鏈，產生 ${doc.generated_at}）`, ...lines, "非投資建議。"].join("\n").slice(0, 4900) }];
    assertLineMessages(messages);
    return messages;
  }
  return packCarousels(doc.industries.slice(0, 10).map(industry => industryBubble(doc, industry)), (index, total) => `產業爆發榜（${index + 1}/${total}）`);
}
