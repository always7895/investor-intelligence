import { V213_TOP20_DISPLAY_COLUMNS_BILINGUAL, v213Top20DisplayValues, type V213Top20Report } from "../src/v213/top20-report";

/** Inspect the actual captured LINE payload, not a freshly rendered substitute. */
export function flexTextNodes(value: unknown): string[] {
  if (!value || typeof value !== "object") return [];
  if (Array.isArray(value)) return value.flatMap(flexTextNodes);
  const node = value as Record<string, unknown>;
  const own = node.type === "text" && typeof node.text === "string" ? [node.text] : [];
  return [...own, ...Object.values(node).flatMap(flexTextNodes)];
}

export function inspectSevenFieldFlex(messages: any[], expected: V213Top20Report) {
  const validShape = messages.length === 4 && messages.every(m => m.type === "flex" && m.contents?.type === "carousel" && m.contents.contents?.length === 5);
  const bubbles = messages.flatMap(m => m.type === "flex" && Array.isArray(m.contents?.contents) ? m.contents.contents : []);
  const nodes = bubbles.map(flexTextNodes);
  const labels = V213_TOP20_DISPLAY_COLUMNS_BILINGUAL;
  const fields = nodes.map(texts => labels.filter(label => texts.filter(t => t === label).length === 1).length);
  const values = nodes.map(texts => labels.map(label => {
    const index = texts.indexOf(label);
    return index < 0 ? null : texts[index + 1];
  }));
  return { rows: bubbles.length, fields: [fields[0] ?? 0, ...fields],
    header: labels.filter(label => nodes[0]?.includes(label)).join("｜"),
    presentation: validShape ? "flex_carousel" : "invalid", message_count: messages.length,
    values_match: values.length === expected.records.length && values.every((row, i) => JSON.stringify(row) === JSON.stringify(v213Top20DisplayValues(expected.records[i]!))) };
}
