import type { ParsedQuery } from "../core";
import { assertLineMessages, type LineOutboundMessage } from "../line-messages";
import type { FieldLocale } from "./field-labels";
import { buildCompanyEvidenceMessages } from "./company-evidence-report";
import { buildTop20DeepAnalysisMessages } from "./deep-analysis";
import { LINE_THEME as T, menuAction } from "./line-theme";
import { parseResearchProductRequest, unavailableResearchProduct } from "./research-product-request";
import { getTwoYearTotalReturnDisplay } from "./top20-return-evidence";
import {
  getV213ReportReference, loadV213FreshTop20Report, parseV213BoundedTop20Report, parseV213Top20Report, v213FieldLocale,
  v213TimesAreFresh, V213_STALE_RECORDS_MESSAGE,
  v213Top20DisplayHeader, v213Top20DisplayValues,
  type V213Top20Env, type V213Top20Report, type V213Top20ReportRecord,
} from "./top20-report";

type PresentationEnv = V213Top20Env & { V213_LINE_PRESENTATION?: string };
const NOTICE = "歷史報酬，非預測；公開研究，非投資建議。 / Historical returns, not forecasts. Public research, not investment advice.";
const SCENARIO_STATUS = "6個月／1年／2年：實現、延遲及未實現訂單的目標價／漲跌幅，尚缺逐筆訂單與估值依據；不是零成長或零風險。時程見深度化分析。";
const companyText = (record: V213Top20ReportRecord, labels: readonly string[]) =>
  `── ${record.rank}/20 · ${record.ticker}｜原文：${record.name} ──\n中文名稱：未完成來源核對（不猜譯）\n` + v213Top20DisplayValues(record).map((value, i) => `${labels[i]}：${value}`).join("\n");
const text = (value: string, size = "sm", color: string = T.ink) => ({ type: "text", text: value, size, color, wrap: true });
const box = (contents: unknown[], extra: Record<string, unknown> = {}) => ({ type: "box", layout: "vertical", contents, spacing: "sm", ...extra });

/** Pure presentation only. Callers retain freshness, sealed-publication and dedupe gates. */
export function buildV213Top20Messages(report: V213Top20Report, locale: FieldLocale = "bilingual", style: "flex" | "text" = "flex"): LineOutboundMessage[] {
  // Strict twenty-record contract first; sealed bottleneck-policy projections
  // (report reference bound) additionally accept 1..20 record payloads.
  const parsed = parseV213Top20Report(report) ??
    (getV213ReportReference(report) !== null ? parseV213BoundedTop20Report(report) : null);
  if (!parsed) throw new Error("V213_PRESENTATION_REPORT_INVALID");
  const reference = getV213ReportReference(report);
  const labels = v213Top20DisplayHeader(locale);
  const localTime = new Intl.DateTimeFormat("zh-TW", { timeZone: "Asia/Taipei", year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", hourCycle: "h23" }).format(new Date(report.generated_at));
  const generated = `報告產生 / Generated (台北 / Taipei): ${localTime}`;
  if (style === "text") {
    // Keep complete company blocks. Never truncate a row, drop a field or emit
    // only the first five messages as a seemingly complete Top20.
    const prefix = `Top20 · 七欄摘要 / Seven-field summary\n${generated}\n${NOTICE}`;
    const chunks: string[] = [];
    let chunk = prefix;
    for (const record of report.records) {
      const block = `\n\n${companyText(record, labels)}`;
      if (chunk.length + block.length > 4900) { chunks.push(chunk); chunk = prefix; }
      if (chunk.length + block.length > 4900) throw new Error("V213_PRESENTATION_ROW_TOO_LARGE");
      chunk += block;
    }
    chunks.push(chunk);
    const messages: LineOutboundMessage[] = chunks.map(value => ({ type: "text", text: value }));
    assertLineMessages(messages);
    return messages;
  }
  const bubbles = report.records.map(record => {
    const values = v213Top20DisplayValues(record);
    const field = (i: number, emphasis = false) => box([
      text(labels[i]!, i <= 2 ? "xxs" : "xs", T.muted),
      { ...text(values[i]!, emphasis ? "xl" : "sm"), ...(emphasis ? { weight: "bold" } : {}) },
    ], { flex: 1 });

    const totalReturnDisplay = getTwoYearTotalReturnDisplay(record);
    const returnBox = (label: string, value: string) => box([
      text(label, "xxs", T.muted),
      { ...text(value, value.length > 8 ? "sm" : "xl", T.ink), weight: "bold" },
    ], { flex: 1 });

    return {
      type: "bubble", size: "mega",
      header: box([
        text(`TOP20 · ${record.rank}/20 · 研究候選 / Candidate`, "xs", "#D4D4D4"),
        text(labels[0]!, "xs", "#D4D4D4"),
        { ...text(values[0]!, "xxl", T.paper), weight: "bold" },
        text("歷史報酬，非預測 / Not forecasts", "xs", "#D4D4D4"),
        text(`原文：${record.name}`, "sm", T.paper),
        text("中文名稱：未完成來源核對", "xs", "#D4D4D4"),
      ], { backgroundColor: T.ink, paddingAll: "lg" }),
      body: box([
        box([
          returnBox("2Y 總報酬", totalReturnDisplay),
          field(1, true),
          field(2, true),
        ], { layout: "horizontal", backgroundColor: T.soft, paddingAll: "md", cornerRadius: "md", spacing: "sm" }),
        field(3), { type: "separator", color: T.border }, field(4),
        box([field(5), field(6)], { backgroundColor: T.paleGreen, paddingAll: "md", cornerRadius: "md", spacing: "sm" }),
      ], { paddingAll: "lg", spacing: "lg", backgroundColor: T.paper }),
      footer: box([
        text(SCENARIO_STATUS, "xs", T.muted),
        text(generated, "xs", T.muted), text(NOTICE, "xs", T.muted),
        ...(reference ? [menuAction("深度化分析 / Deep analysis",
          `Top20 深度化分析 ${record.ticker} ${new Date(report.generated_at).toISOString()} ${reference.snapshot} ${reference.reportSha256}`
        )] : [text("詳情入口未綁定 / Unbound detail reference", "xs", T.muted)]),
      ], { paddingAll: "md", backgroundColor: T.soft }),
    };
  });
  const messages: LineOutboundMessage[] = [];
  for (let start = 0; start < bubbles.length; start += 5) {
    messages.push({ type: "flex", altText: `Top20 ${start + 1}–${start + 5}/20 · 七欄公開研究 / Public research. 歷史報酬非預測 / Not forecasts.`,
      contents: { type: "carousel", contents: bubbles.slice(start, start + 5) } });
  }
  assertLineMessages(messages);
  return messages;
}

export async function v213Top20LineAnswer(env: PresentationEnv, query: ParsedQuery): Promise<LineOutboundMessage[] | string | null> {
  const requested = parseResearchProductRequest(query.normalized);
  if (requested) return unavailableResearchProduct(requested);
  const detailPrefix = /^top\s*20\s+(?:深度化分析|證據詳情|公司文字)(?:\s|$)/i.test(query.normalized);
  const companyOnly = /^top\s*20\s+公司文字(?:\s|$)/i.test(query.normalized);
  const detail = /^top\s*20\s+(?:深度化分析|證據詳情|公司文字)\s+([A-Z0-9][A-Z0-9.-]{0,14})\s+(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z)\s+(legacy|s:[A-Z0-9][A-Z0-9._-]{0,127})\s+([a-f0-9]{64})$/i.exec(query.normalized);
  if (detailPrefix && !detail) return "請從卡片選擇有效的公司深度化分析。";
  const result = await loadV213FreshTop20Report(env, detail ? { ...query, ticker: null, intent: "ranking", normalized: "Top20" } : query);
  if (!result || typeof result === "string") return result;
  if (detail) {
    const reference = getV213ReportReference(result);
    if (!reference || detail[2] !== new Date(result.generated_at).toISOString() || detail[3] !== reference.snapshot || detail[4]!.toLowerCase() !== reference.reportSha256) return "Top20 已更新或內容不符，請重新取得卡片；不把另一份報告冒充舊卡片的詳情。";
    const row = result.records.find(record => record.ticker === detail[1]!.toUpperCase());
    if (!row) return "該公司不在本輪 Top20 快照，沒有改用舊資料或其他公司的報告。";
    if (!v213TimesAreFresh(env, [row.retrieved_at])) return V213_STALE_RECORDS_MESSAGE;
    try {
      if (companyOnly) {
        const messages: LineOutboundMessage[] = [{ type: "text", text:
          `本公司七欄摘要（不是完整深度分析）\n快照產生：${result.generated_at}\n${NOTICE}\n\n${companyText(row, v213Top20DisplayHeader(v213FieldLocale(env.V213_FIELD_LOCALE)))}\n\n${SCENARIO_STATUS}` }];
        assertLineMessages(messages);
        return messages;
      }
      return buildTop20DeepAnalysisMessages(result, row.ticker);
    } catch { return "公司深度化分析未通過來源或訊息完整性檢查，已拒絕顯示。"; }
  }
  if (!v213TimesAreFresh(env, result.records.map(row => row.retrieved_at))) return V213_STALE_RECORDS_MESSAGE;
  const style = /文字|text/i.test(query.normalized) || env.V213_LINE_PRESENTATION === "text" ? "text" : "flex";
  return buildV213Top20Messages(result, v213FieldLocale(env.V213_FIELD_LOCALE), style);
}
