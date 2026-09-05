import type { ParsedQuery } from "../core";
import { assertLineMessages, type LineOutboundMessage } from "../line-messages";
import type { FieldLocale } from "./field-labels";
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
    const prefix = `Top20 · 七欄公開研究 / Seven-field public research\n${generated}\n${NOTICE}`;
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
        { type: "button", style: "link", height: "sm", action: { type: "message", label: "完整文字版 / Full text", text: "Top20 文字" } },
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
  const result = await loadV213FreshTop20Report(env, query);
  if (!result || typeof result === "string") return result;
  const style = /文字|text/i.test(query.normalized) || env.V213_LINE_PRESENTATION === "text" ? "text" : "flex";
  return buildV213Top20Messages(result, v213FieldLocale(env.V213_FIELD_LOCALE), style);
}
