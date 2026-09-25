/** Data-driven potential ranking (operator rules 2026-09-25: rank by potential, every number sourced,
 * nothing hand-written, updates with the data). Built daily from BLS PPI, SEC XBRL and TWSE/TPEx
 * monthly revenue (scripts/industry_rotation.py) and sealed inside the TOP5 overview object.
 * The phase is an eligibility gate and the published strength formula orders companies; this is a
 * computation over official data, not a forecast, target price or recommendation. */
import { assertLineMessages, type LineOutboundMessage } from "../line-messages";
import { buildCompanyDataReportFlex, buildCompanyDataReportMessages, validateCompanyDataReport, type CompanyDataReport } from "./deep-analysis";
import { LINE_THEME as T, chip, footnote, headerStyle, labelValue, menuAction, phaseLadder, section, signColor, statTile, uiBox, uiText } from "./line-theme";

export interface PotentialRecord {
  readonly rank: number; readonly ticker: string; readonly name: string; readonly industry_name: string;
  readonly phase: string; readonly strength: number; readonly revenue_yoy_pct: number | null; readonly rpo_yoy_pct: number | null;
  readonly gross_margin_change_pp: number | null; readonly operating_margin_change_pp: number | null;
  readonly dilution_yoy_pct: number | null; readonly next_review_at: string | null;
}
export interface PotentialRanking {
  readonly as_of: string; readonly quarter: string; readonly records: readonly PotentialRecord[];
  readonly reports: Readonly<Record<string, unknown>>;
}

const PHASE_ZH: Record<string, string> = {
  DISCOVERY: "初現（單一來源）", EARLY_VALIDATION: "驗證中（雙來源確認）", COMMERCIAL_VALIDATION: "商業驗證（公司開始獲利）",
  INSTITUTIONAL_VALIDATION: "法人進場",
};
const TICKER = /^[A-Z]{1,5}$/;
const DAY = /^\d{4}-\d{2}-\d{2}$/;
const num = (v: unknown) => v === null || (typeof v === "number" && Number.isFinite(v));
const text = (v: unknown, max: number) => typeof v === "string" && v.trim().length > 0 && v.length <= max && !/[\r\n]/.test(v);

/** Strict reader of the ranking embedded in the sealed overview; null on any malformed row. */
export function validatePotentialRanking(raw: unknown): PotentialRanking | null {
  const value = raw as any;
  if (!value || typeof value !== "object" || !DAY.test(String(value.as_of)) || !text(value.quarter, 20)) return null;
  if (!Array.isArray(value.records) || value.records.length < 1 || value.records.length > 20) return null;
  const seen = new Set<string>();
  for (const [index, row] of value.records.entries()) {
    if (!row || row.rank !== index + 1 || !TICKER.test(String(row.ticker)) || seen.has(row.ticker)) return null;
    if (!text(row.name, 200) || !text(row.industry_name, 80) || !(row.phase in PHASE_ZH)) return null;
    if (!Number.isInteger(row.strength) || row.strength < 0 || row.strength > 100) return null;
    for (const key of ["revenue_yoy_pct", "rpo_yoy_pct", "gross_margin_change_pp", "operating_margin_change_pp", "dilution_yoy_pct"]) {
      if (!num(row[key])) return null;
    }
    if (row.next_review_at !== null && !DAY.test(String(row.next_review_at))) return null;
    seen.add(row.ticker);
  }
  const reports = value.reports && typeof value.reports === "object" && !Array.isArray(value.reports) ? value.reports : {};
  return { as_of: value.as_of, quarter: value.quarter, records: value.records, reports };
}

const pct = (v: number | null, unit = "%") => (v === null ? "未申報" : `${v >= 0 ? "+" : ""}${v.toFixed(1)}${unit}`);

function bubble(ranking: PotentialRanking, row: PotentialRecord) {
  return {
    type: "bubble", size: "mega",
    header: uiBox([
      uiBox([chip(`#${row.rank}`), uiText(`資料驅動潛力榜 · ${row.rank}/${ranking.records.length}`, "xxs", T.headerMuted, { gravity: "center", flex: 1 })],
        { layout: "horizontal", spacing: "md" }),
      uiText(row.ticker, "3xl", T.headerText, { weight: "bold" }),
      uiText(row.name, "md", T.headerText, { weight: "bold" }),
      uiText(row.industry_name, "xxs", T.headerSubtle),
      uiText(`階段：${PHASE_ZH[row.phase]}`, "xxs", T.headerMuted, { weight: "bold" }),
    ], { ...headerStyle, spacing: "md" }),
    body: uiBox([
      section("關鍵數據 / Key data", [
        uiBox([
          statTile("營收年增", pct(row.revenue_yoy_pct)),
          statTile("RPO年增", pct(row.rpo_yoy_pct)),
          statTile("資料強度", `${row.strength}`, row.strength),
        ], { layout: "horizontal", spacing: "sm" }),
      ], "key"),
      section("獲利與股本 / Margins & dilution", [
        labelValue("毛利率年變化", pct(row.gross_margin_change_pp, " 個百分點"), { weight: "bold", color: signColor(pct(row.gross_margin_change_pp)) }),
        labelValue("營業利益率年變化", pct(row.operating_margin_change_pp, " 個百分點"), { weight: "bold", color: signColor(pct(row.operating_margin_change_pp)) }),
        labelValue("稀釋後股數年變化", pct(row.dilution_yoy_pct)),
      ], "detail"),
      section("資料階段 / Phase", [
        phaseLadder(row.phase),
        uiBox([labelValue("資料季度", ranking.quarter), labelValue("下次檢查", row.next_review_at ?? "下一份財報")], { layout: "horizontal", spacing: "md" }),
      ], "context"),
    ], { paddingAll: "lg", spacing: "md", backgroundColor: T.paper }),
    footer: uiBox([
      menuAction("詳細報告 / Report", `潛力報告 ${row.ticker}`),
      footnote(`資料計算日 ${ranking.as_of}｜BLS、SEC XBRL、證交所與櫃買中心官方資料計算；不是預測或投資建議`),
    ], { paddingAll: "lg", spacing: "sm", backgroundColor: T.paper }),
  };
}

export function buildPotentialRankingFlex(ranking: PotentialRanking): LineOutboundMessage[] {
  const bubbles = ranking.records.map(row => bubble(ranking, row));
  const messages: LineOutboundMessage[] = [];
  // Same shape as Top20: at most 4 carousels of 5 bubbles (LINE reply limit and project carousel rule).
  for (let start = 0; start < bubbles.length; start += 5) {
    messages.push({ type: "flex", altText: `資料驅動潛力榜 ${start + 1}–${Math.min(start + 5, bubbles.length)}/${bubbles.length}（官方資料計算，非預測）`,
      contents: { type: "carousel", contents: bubbles.slice(start, start + 5) } });
  }
  assertLineMessages(messages);
  return messages;
}

export function buildPotentialRankingText(ranking: PotentialRanking): LineOutboundMessage[] {
  const lines = [`【資料驅動潛力榜】資料季度 ${ranking.quarter}｜計算日 ${ranking.as_of}`,
    "排序：階段准入（排除擁擠、緩解、失效）→ 雙來源確認優先 → 公開的資料強度公式；每產業最多 5 家。非預測、非投資建議。",
    ...ranking.records.map(r => `#${r.rank} ${r.ticker} ${r.name}｜${r.industry_name}｜${PHASE_ZH[r.phase]}｜強度 ${r.strength}｜營收 ${pct(r.revenue_yoy_pct)}｜RPO ${pct(r.rpo_yoy_pct)}`),
    "詳細報告：輸入「潛力報告 代號」，例如：潛力報告 " + ranking.records[0]!.ticker];
  const messages: LineOutboundMessage[] = [{ type: "text", text: lines.join("\n").slice(0, 4900) }];
  assertLineMessages(messages);
  return messages;
}

export function buildPotentialReport(ranking: PotentialRanking, ticker: string, generatedAt: string, isText = false): LineOutboundMessage[] | string {
  const symbol = ticker.toUpperCase();
  if (!ranking.records.some(row => row.ticker === symbol)) return `「${symbol}」不在本輪資料驅動潛力榜中；不以其他公司或舊資料代替。`;
  const data: CompanyDataReport | null = validateCompanyDataReport(ranking.reports[symbol], symbol);
  if (!data) return `「${symbol}」的詳細報告尚未產生或未通過驗證；不以樣板文字冒充。`;
  return isText ? buildCompanyDataReportMessages(data, generatedAt) : buildCompanyDataReportFlex(data, generatedAt, ["回潛力榜", "潛力榜"]);
}
