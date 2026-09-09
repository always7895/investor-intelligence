import type { ParsedQuery } from "../core";
import { assertLineMessages, type LineOutboundMessage } from "../line-messages";
import type { FieldLocale } from "./field-labels";
import { buildCompanyEvidenceMessages } from "./company-evidence-report";
import {
  loadV213FreshTop20Report, parseV213Top20Report, v213FieldLocale,
  v213Top20DisplayHeader, v213Top20DisplayValues,
  type V213Top20Env, type V213Top20Report,
} from "./top20-report";

type PresentationEnv = V213Top20Env & { V213_LINE_PRESENTATION?: string };
const NOTICE = "歷史報酬，非預測；公開研究，非投資建議。 / Historical returns, not forecasts. Public research, not investment advice.";
const text = (value: string, size = "sm", color = "#172B4D") => ({ type: "text", text: value, size, color, wrap: true });
const box = (contents: unknown[], extra: Record<string, unknown> = {}) => ({ type: "box", layout: "vertical", contents, spacing: "sm", ...extra });

/** Pure presentation only. Callers retain freshness, sealed-publication and dedupe gates. */
export function buildV213Top20Messages(report: V213Top20Report, locale: FieldLocale = "bilingual", style: "flex" | "text" = "flex"): LineOutboundMessage[] {
  if (!parseV213Top20Report(report)) throw new Error("V213_PRESENTATION_REPORT_INVALID");
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
      const block = `\n\n── ${record.rank}/20 ──\n` + v213Top20DisplayValues(record).map((value, i) => `${labels[i]}：${value}`).join("\n");
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
      text(labels[i]!, "xs", "#475569"),
      { ...text(values[i]!, emphasis ? "xl" : "sm"), ...(emphasis ? { weight: "bold" } : {}) },
    ], { flex: 1 });
    return {
      type: "bubble", size: "mega",
      header: box([
        text(`TOP20 · ${record.rank}/20 · 研究候選 / Candidate`, "xs", "#CBD5E1"),
        text(labels[0]!, "xs", "#CBD5E1"),
        { ...text(values[0]!, "xxl", "#FFFFFF"), weight: "bold" },
      ], { backgroundColor: "#142C47", paddingAll: "lg" }),
      body: box([
        box([field(1, true), field(2, true)], { layout: "horizontal", backgroundColor: "#F1F5F9", paddingAll: "md", cornerRadius: "md", spacing: "md" }),
        field(3), { type: "separator", color: "#E2E8F0" }, field(4),
        box([field(5), field(6)], { backgroundColor: "#EFF6FF", paddingAll: "md", cornerRadius: "md", spacing: "lg" }),
      ], { paddingAll: "lg", spacing: "lg", backgroundColor: "#FFFFFF" }),
      footer: box([
        text(generated, "xs", "#475569"), text(NOTICE, "xs", "#475569"),
        { type: "button", style: "link", height: "sm", action: { type: "message", label: "證據詳情 / Evidence", text: `Top20 證據詳情 ${record.ticker} ${new Date(report.generated_at).toISOString()}` } },
      ], { paddingAll: "md", backgroundColor: "#F8FAFC" }),
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
  const detailPrefix = /^top\s*20\s+證據詳情(?:\s|$)/i.test(query.normalized);
  const detail = /^top\s*20\s+證據詳情\s+([A-Z0-9][A-Z0-9.-]{0,14})\s+(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z)$/i.exec(query.normalized);
  if (detailPrefix && !detail) return "請從卡片選擇有效的公司證據詳情。";
  const result = await loadV213FreshTop20Report(env, detail ? { ...query, ticker: null, intent: "ranking", normalized: "Top20" } : query);
  if (!result || typeof result === "string") return result;
  if (detail) {
    if (detail[2] !== new Date(result.generated_at).toISOString()) return "Top20 已更新，請重新取得卡片；不把新報告冒充舊卡片的詳情。";
    const row = result.records.find(record => record.ticker === detail[1]!.toUpperCase());
    if (!row) return "該公司不在本輪 Top20 快照，沒有改用舊資料或其他公司的報告。";
    const limit = Math.max(300, Math.min(86400, Number(env.V21_TOP20_MAX_AGE_SECONDS ?? "7200") || 7200));
    const age = (Date.now() - Date.parse(row.retrieved_at)) / 1000;
    if (!Number.isFinite(age) || age < -300 || age > limit) return "公司資料取得時間已過期或無效，不能以新的報告日期掩蓋舊資料。";
    try { return buildCompanyEvidenceMessages(result, row.ticker); }
    catch { return "公司證據詳情未通過來源或訊息完整性檢查，已拒絕顯示。"; }
  }
  const style = /文字|text/i.test(query.normalized) || env.V213_LINE_PRESENTATION === "text" ? "text" : "flex";
  return buildV213Top20Messages(result, v213FieldLocale(env.V213_FIELD_LOCALE), style);
}
