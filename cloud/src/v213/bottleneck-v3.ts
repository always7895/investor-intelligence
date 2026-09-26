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
interface Market { source: string; source_url: string; asof: string; ret_6m: number | null; ret_1y: number | null; cagr_2y: number | null; currency: string | null; }
interface SerenityLead { mentions: number; bullish: number; bearish: number; stance: string; latest_at: string | null; latest_url: string | null; }
interface LeopoldLead { long_weight: number; status: string; }
export interface BottleneckEntry {
  rank: number; symbol: string; name: string; layer: string; archetype: "EXPLOSION" | "COMPOUNDER"; score: number;
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
const str = (value: unknown, max: number): value is string => typeof value === "string" && value.length > 0 && value.length <= max;
const num = (value: unknown): value is number => typeof value === "number" && Number.isFinite(value);
const optNum = (value: unknown) => value === null || value === undefined || num(value);
const https = (value: unknown) => str(value, 400) && value.startsWith("https://");

function validEntry(raw: any): raw is BottleneckEntry {
  return raw && Number.isInteger(raw.rank) && str(raw.symbol, 16) && str(raw.name, 160) && str(raw.layer, 40)
    && (raw.archetype === "EXPLOSION" || raw.archetype === "COMPOUNDER") && num(raw.score) && str(raw.role, 200)
    && raw.role_source && https(raw.role_source.url) && str(raw.role_source.date, 20)
    && raw.parts && ["layer_heat", "capture", "lead", "confirmation", "size", "penalty"].every(key => num(raw.parts[key]))
    && (raw.fundamentals === null || (raw.fundamentals && str(raw.fundamentals.source, 80) && https(raw.fundamentals.source_url)
      && str(raw.fundamentals.quarter_end, 12) && ["revenue_yoy", "revenue_yoy_prev", "gross_margin", "gross_margin_change", "rpo_yoy", "shares_yoy"].every(key => optNum(raw.fundamentals[key]))))
    && raw.market && str(raw.market.source, 80) && https(raw.market.source_url) && str(raw.market.asof, 12)
    && ["ret_6m", "ret_1y", "cagr_2y"].every(key => optNum(raw.market[key])) && optNum(raw.market_cap_usd)
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

function companyBubble(doc: BottleneckV3, entry: BottleneckEntry) {
  const fund = entry.fundamentals;
  const lead = entry.rank === 1;
  const serenity = entry.serenity
    ? `Serenity 近120天提及 ${entry.serenity.mentions} 則（看多 ${entry.serenity.bullish}／看空 ${entry.serenity.bearish}），最近 ${day(entry.serenity.latest_at)}`
    : "Serenity 近120天未提及";
  const leopold = entry.leopold
    ? `Leopold 基金 13F 持倉 ${(entry.leopold.long_weight * 100).toFixed(1)}%（${entry.leopold.status === "NEW" ? "新建倉" : "持有"}，期末 ${doc.leopold_filing?.period ?? "未揭露"}）`
    : "Leopold 基金最新 13F 未持有";
  return {
    type: "bubble", size: "mega",
    header: productHeader(`瓶頸爆發 TOP20 · ${entry.archetype === "EXPLOSION" ? "爆發型" : "核心複利型"}`, `${entry.symbol}｜${entry.name}`.slice(0, 60), [
      uiBox([rankBadge(entry.rank, lead), chip(layerName(doc, entry.layer)), chip(`${entry.score.toFixed(1)} 分`)], { layout: "horizontal", spacing: "sm" }),
    ]),
    body: uiBox([
      section("瓶頸位置", [uiText(entry.role, "sm", T.ink), footnote(`角色來源 ${entry.role_source.date}：${entry.role_source.url}`.slice(0, 180))], "key"),
      section("分數組成（0–100）", [
        meter(entry.score),
        stackedBar([
          { label: "層級熱度", weight: Math.round(entry.parts.layer_heat) }, { label: "公司捕獲", weight: Math.round(entry.parts.capture) },
          { label: "線索", weight: Math.round(entry.parts.lead) }, { label: "市場確認", weight: Math.round(entry.parts.confirmation) },
          { label: "爆發性", weight: Math.round(entry.parts.size) },
        ]),
        ...(entry.parts.penalty > 0 ? [uiText(`稀釋／融資扣分 -${entry.parts.penalty}`, "xxs", T.negative)] : []),
      ]),
      section("公司數據", [
        uiBox([statTile("最新季營收年增", pct(fund?.revenue_yoy ?? null, 0)), statTile("毛利率變化", fund?.gross_margin_change === null || fund?.gross_margin_change === undefined ? "未揭露" : `${fund.gross_margin_change >= 0 ? "+" : ""}${(fund.gross_margin_change * 100).toFixed(1)}pp`)], { layout: "horizontal", spacing: "sm" }),
        uiBox([statTile("6個月報酬", pct(entry.market.ret_6m, 0)), statTile(entry.market.cagr_2y !== null ? "2年年化" : "1年報酬", pct(entry.market.cagr_2y ?? entry.market.ret_1y, 0))], { layout: "horizontal", spacing: "sm" }),
        footnote(fund ? `財報：${fund.source}，季末 ${fund.quarter_end}` : "財報：未取得可比季度"),
        footnote(`股價：${entry.market.source}，至 ${entry.market.asof}；市值 ${cap(entry.market_cap_usd)}`),
      ]),
      section("線索（非公司事實）", [uiText(serenity, "xs", T.ink), uiText(leopold, "xs", T.ink)], "context"),
    ], { paddingAll: "lg", spacing: "md" }),
    footer: uiBox([menuAction("瓶頸詳情", `瓶頸詳情 ${entry.symbol}`), menuAction("產業爆發榜", "產業爆發榜")], footerStyle),
  };
}

export function buildBottleneckTop20Messages(doc: BottleneckV3, style: "flex" | "text"): LineOutboundMessage[] {
  if (style === "text") {
    const lines = doc.top.map(entry => `${entry.rank}. ${entry.symbol} ${entry.name}｜${layerName(doc, entry.layer)}｜${entry.score.toFixed(1)}分｜營收年增 ${pct(entry.fundamentals?.revenue_yoy ?? null, 0)}｜6M ${pct(entry.market.ret_6m, 0)}`);
    const messages: LineOutboundMessage[] = [{ type: "text", text: [
      `瓶頸爆發 TOP20（v3，產生 ${doc.generated_at}）`,
      "排序：層級熱度＋公司捕獲＋Serenity/Leopold 線索＋市場確認＋爆發性；長期報酬為負者排除。非投資建議。",
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
  const fund = entry.fundamentals;
  const text = [
    `【瓶頸詳情｜#${entry.rank} ${entry.symbol} ${entry.name}】`,
    `層級：${layerName(doc, entry.layer)}｜型態：${entry.archetype === "EXPLOSION" ? "瓶頸爆發型（市值<US$10B）" : "核心複利型"}｜總分 ${entry.score.toFixed(1)}`,
    `分數：層級熱度 ${entry.parts.layer_heat}、公司捕獲 ${entry.parts.capture}、線索 ${entry.parts.lead}、市場確認 ${entry.parts.confirmation}、爆發性 ${entry.parts.size}、扣分 ${entry.parts.penalty}`,
    `瓶頸角色：${entry.role}（${entry.role_source.date}，${entry.role_source.url}）`,
    fund ? `財報（${fund.source}，季末 ${fund.quarter_end}）：營收年增 ${pct(fund.revenue_yoy)}；前一季年增 ${pct(fund.revenue_yoy_prev)}；毛利率 ${fund.gross_margin === null ? "未揭露" : (fund.gross_margin * 100).toFixed(1) + "%"}（年變化 ${pp(fund.gross_margin_change)}）；剩餘履約義務年增 ${pct(fund.rpo_yoy)}；股數年增 ${pct(fund.shares_yoy)}\n來源：${fund.source_url}` : "財報：未取得可比季度（不以估計替代）。",
    `股價（${entry.market.source}，至 ${entry.market.asof}）：6個月 ${pct(entry.market.ret_6m)}、1年 ${pct(entry.market.ret_1y)}、2年年化 ${pct(entry.market.cagr_2y)}；市值 ${cap(entry.market_cap_usd)}\n來源：${entry.market.source_url}`,
    entry.serenity ? `Serenity 線索：近120天 ${entry.serenity.mentions} 則（看多 ${entry.serenity.bullish}／看空 ${entry.serenity.bearish}，判定 ${entry.serenity.stance}），最近 ${day(entry.serenity.latest_at)}：${entry.serenity.latest_url ?? ""}` : "Serenity 線索：近120天未提及。",
    entry.leopold ? `Leopold 線索：Situational Awareness LP 13F 多頭部位 ${(entry.leopold.long_weight * 100).toFixed(1)}%（${entry.leopold.status}；期末 ${doc.leopold_filing?.period}，申報 ${doc.leopold_filing?.filed}）${doc.leopold_filing?.url ?? ""}` : "Leopold 線索：最新 13F 未持有。",
    "線索只影響排序權重，不是公司事實；13F 為季末持倉、申報可晚 45 天。非投資建議，不自動下單。",
  ].join("\n");
  const summary: LineOutboundMessage = { type: "text", text: text.slice(0, 4900) };
  // The company data report (SEC filings, business profile, thesis phase, order realization) when one is sealed.
  const raw = Object.hasOwn(doc.deep_reports, entry.symbol) ? doc.deep_reports[entry.symbol] : undefined;
  const report = raw ? validateCompanyDataReport(raw, entry.symbol) : null;
  if (report) {
    const extra = style === "flex" ? buildCompanyDataReportFlex(report, doc.generated_at, ["回瓶頸 TOP20", "TOP20"])
      : buildCompanyDataReportMessages(report, doc.generated_at);
    const messages = [summary, ...extra].slice(0, 5);
    assertLineMessages(messages);
    return messages;
  }
  const messages: LineOutboundMessage[] = [summary];
  assertLineMessages(messages);
  return messages;
}

function industryBubble(doc: BottleneckV3, industry: IndustryEntry) {
  const members = doc.top.filter(entry => entry.layer === industry.id).map(entry => entry.symbol);
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
        uiBox([statTile("SEC申報熱度", news?.ratio === null || news === null ? "未取得" : `${news.ratio.toFixed(2)}x`, undefined, news ? `近30天 ${news.recent_30d}／前60天 ${news.prior_60d}` : undefined), statTile("基金13F占比", `${(industry.fund_13f_weight * 100).toFixed(1)}%`)], { layout: "horizontal", spacing: "sm" }),
        footnote(`6個月股價中位數 ${pct(industry.median_return_6m, 0)}；Serenity 熱度 ${industry.serenity_heat.toFixed(1)}`),
      ]),
      section("本輪 TOP20 成員", [uiText(members.length ? members.join("、") : "（無）", "sm", T.ink)], "context"),
      divider(),
      footnote("爆發力＝因果鏈位置35＋基金13F權重25＋營收加速20＋SEC申報熱度10＋Serenity熱度10。非投資建議。"),
    ], { paddingAll: "lg", spacing: "md" }),
    footer: uiBox([menuAction("瓶頸爆發 TOP20", "TOP20"), menuAction("回功能選單", "選單")], footerStyle),
  };
}

export function buildIndustryExplosionMessages(doc: BottleneckV3, style: "flex" | "text"): LineOutboundMessage[] {
  if (style === "text") {
    const lines = doc.industries.map(industry => `${industry.rank}. ${industry.name_zh}｜爆發力 ${industry.explosiveness.toFixed(1)}｜營收年增中位數 ${pct(industry.median_revenue_yoy, 0)}｜SEC申報熱度 ${industry.news?.ratio ?? "未取得"}x｜13F ${(industry.fund_13f_weight * 100).toFixed(1)}%`);
    const messages: LineOutboundMessage[] = [{ type: "text", text: [`產業爆發榜（Leopold 因果鏈，產生 ${doc.generated_at}）`, ...lines, "非投資建議。"].join("\n").slice(0, 4900) }];
    assertLineMessages(messages);
    return messages;
  }
  return packCarousels(doc.industries.slice(0, 10).map(industry => industryBubble(doc, industry)), (index, total) => `產業爆發榜（${index + 1}/${total}）`);
}
