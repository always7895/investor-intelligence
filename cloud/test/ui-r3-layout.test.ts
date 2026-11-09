/** UI-R3 real LINE presentation boundaries; synthetic, sealed-fixture data only. */
import { describe, expect, it, vi } from "vitest";
import type * as Admission from "../src/v213/public-options-admission";
vi.mock("../src/v213/public-options-admission", async importOriginal => {
  const real = await importOriginal<typeof Admission>();
  return { ...real, admitPublicOption: vi.fn(real.admitPublicOption) };
});
import { assertLineMessages } from "../src/line-messages";
import { v25FlexMessages, v25Surfaces, v3D1Surfaces, bubblesOf, REPORT, top20Report } from "./flex-density-fixtures";
import { localizeLineMessages } from "../src/v213/status-labels";
import { doc, HOUR } from "./bottleneck-v3-fixture";
import { buildBottleneckDetail, buildBottleneckTop20Messages, buildIndustryExplosionMessages, parseBottleneckV3 } from "../src/v213/bottleneck-v3";
import { buildV213Top20Messages } from "../src/v213/top20-presentation";
import { buildCompanyEvidenceMessages } from "../src/v213/company-evidence-report";
import { buildTop20DeepAnalysisMessages } from "../src/v213/deep-analysis";
import { parseV213Top20Report } from "../src/v213/top20-report";
import { formatOptionsAnswer } from "../src/core";
import { optionsUnavailableReport } from "../src/v213/options-product";

const nodes = (value: any): any[] => value == null || typeof value !== "object" ? []
  : Array.isArray(value) ? value.flatMap(nodes) : [value, ...Object.values(value).flatMap(nodes)];
const renderedText = (messages: readonly any[]): string => messages.filter(x => x.type === "text").map(x => x.text).join("\n");
const tokens = (bubble: any) => nodes(bubble).filter(n => n.type === "text")
  .map(n => typeof n.text === "string" ? n.text : (n.contents ?? []).map((s: any) => s.text ?? "").join("")).join("\n");
const bytes = (value: unknown) => new TextEncoder().encode(JSON.stringify(value)).length;

// Inspect rendered display fields, never opaque postback/raw payloads or source strings.
function displayCodeLeaks(value: unknown, path = "$"): string[] {
  if (Array.isArray(value)) return value.flatMap((item, index) => displayCodeLeaks(item, `${path}[${index}]`));
  if (value === null || typeof value !== "object") return [];
  return Object.entries(value).flatMap(([key, item]) => {
    if (key === "data" || key === "postback") return [];
    const field = `${path}.${key}`;
    if (["text", "altText", "label", "title", "displayText"].includes(key) && typeof item === "string") {
      return [...item.matchAll(/[A-Z][A-Z0-9]*(?:_[A-Z0-9]+)+/g)].map(match => `${field}: ${match[0]}`);
    }
    return displayCodeLeaks(item, field);
  });
}

describe("UI-R3 LINE mobile layout with synthetic largest fixtures", () => {
  it("keeps every Flex message within LINE limits, named/date alt text, six-character action labels and <=3 footer actions", async () => {
    const flex = await v25FlexMessages();
    expect(flex.length).toBeGreaterThan(8);
    for (const [index, message] of flex.entries()) {
      assertLineMessages([message]);
      expect(Array.from(message.altText).length, `alt #${index}`).toBeLessThanOrEqual(60);
      expect(message.altText, `date #${index}`).toMatch(/\d{4}-\d{2}-\d{2}/);
      expect(bytes(message.contents), `bytes #${index}`).toBeLessThanOrEqual(48000);
      const bubbles = bubblesOf([message]);
      for (const [j,bubble] of bubbles.entries()) {
        const buttons = nodes(bubble.footer).filter(n => n.type === "button");
        expect(buttons.length, `message #${index} bubble #${j}`).toBeLessThanOrEqual(3);
        for (const button of buttons) {
          expect(Array.from(button.action.label).length, `button ${button.action.label}`).toBeLessThanOrEqual(6);
          expect(button.action.text.length).toBeGreaterThan(0);
        }
      }
    }
  });
  it("keeps each key card to one visual hero, three or fewer accent KPI tiles per row, no mandatory text ellipsis", async () => {
    for (const name of ["bottleneck Top20 card", "bottleneck detail page 1", "options-product contract", "bottleneck industry"]) {
      const bubbles = await (v25Surfaces as Record<string, () => Promise<any[]> | any[]>)[name]!();
      for (const bubble of bubbles.slice(0, 4)) {
        const body = nodes(bubble.body);
        expect(body.filter(n => n.type === "text" && n.size === "3xl").length, name).toBe(1);
        const rows = body.filter(n => n.type === "box" && n.layout === "horizontal");
        for (const row of rows) {
          const tiles = (row.contents ?? []).filter((node: any) => node.type === "box" && node.backgroundColor === "#EEF3F8");
          expect(tiles.length, name).toBeLessThanOrEqual(3);
        }
      }
    }
  });
  it("Top20 text preserves whole ranked entries, one per paragraph, not pipe-joined; disclosures last", () => {
    const parsed = parseBottleneckV3(doc(REPORT-HOUR), REPORT)!;
    const messages = buildBottleneckTop20Messages(parsed, "text");
    assertLineMessages(messages);
    const text = renderedText(messages);
    expect(text).toContain("產業層級：");
    expect(text).toContain("6 個月");
    expect(text).toContain("2 年年化");
    expect(text).toMatch(/\n\n\d+\. [A-Z]/);
    expect(text).toContain("目前訂單：");
    expect(text.trimEnd()).toMatch(/非投資建議；不自動下單。$/);
    for (const entry of parsed.top) expect(text).toContain(`${entry.rank}. ${entry.symbol}`);
    for (const message of messages) expect(message.type).toBe("text");
  });
  it("a pending acquisition never yields target option candidates, but displays the terms when present", () => {
    const result = formatOptionsAnswer([{ticker:"LITE",status:"DEAL_PENDING_TARGET",quote_source:"public",
      acquirer_symbol:"MRVL", exchange_ratio:4.5,
      periods: {weekly: {status:"OK", call_observations:{status:"OK",recommended_candidates:[{strike:99,bid:1,ask:2}]}}}}] as any, "LITE", "weekly");
    expect(result).toContain("併購進行中，暫停選擇權建議");
    expect(result).toContain("每股換 4.500 股 MRVL");
    expect(result).not.toContain("99");
    expect(result).not.toContain("買權報價");
    expect(result).not.toContain("DEAL_PENDING_TARGET");
  });
  it("public text contains localized statuses without raw wire-code leakage in built examples", async () => {
    const flex = await v25FlexMessages();
    const text = flex.flatMap(message => bubblesOf([message]).map(tokens)).join("\n");
    const prohibited = [
      "OPTION_DATA_UNAVAILABLE", "NO_ELIGIBLE_LIQUID_QUOTE", "NO_LISTED_OPTIONS",
      "DEAL_PENDING_TARGET", "LIMITED_RESEARCH_CANDIDATE", "QUOTE_UNAVAILABLE",
      "IDENTITY_CONFLICT_UNRESOLVED", "TEST-ONLY", "UNAVAILABLE",
    ];
    for(const code of prohibited) expect(text, code).not.toContain(code);
    expect(text).not.toMatch(/(?<![A-Za-z0-9_./-])[a-z][a-z0-9]*(?:_[a-z0-9]+)+(?![A-Za-z0-9_./-])/);
    const noQuote = optionsUnavailableReport("SYN", "weekly", "CHAIN_PROVIDER_ERROR", true);
    expect(renderedText(noQuote)).not.toContain("CHAIN_PROVIDER_ERROR");
    expect(renderedText(noQuote)).toContain("資料來源暫時無法取得");
  });
  it("rejects any unmapped UPPER_SNAKE_CASE in every shared rendered product fixture", async () => {
    for (const [name, build] of Object.entries(v25Surfaces)) {
      const rendered = await build();
      expect(displayCodeLeaks(localizeLineMessages(rendered)), name).toEqual([]);
    }
    for (const [name, rendered] of Object.entries(v3D1Surfaces())) {
      expect(displayCodeLeaks(localizeLineMessages(rendered)), name).toEqual([]);
    }
    // Full messages retain altText and all pages/disclosures omitted by density slices.
    const messages = await v25FlexMessages();
    expect(displayCodeLeaks(localizeLineMessages(messages))).toEqual([]);
    const parsed = parseBottleneckV3(doc(REPORT-HOUR), REPORT)!;
    for (const mode of ["text", "flex"] as const) {
      const complete = [
        ...buildBottleneckTop20Messages(parsed, mode),
        ...buildIndustryExplosionMessages(parsed, mode),
      ];
      expect(displayCodeLeaks(localizeLineMessages(complete)), mode).toEqual([]);
      for (const entry of parsed.top) {
        const detail = buildBottleneckDetail(parsed, entry.symbol, mode);
        const rendered = typeof detail === "string" ? [{ type: "text", text: detail }] : detail;
        expect(displayCodeLeaks(localizeLineMessages<unknown>(rendered)), `${mode}/${entry.symbol}`).toEqual([]);
      }
    }
  });

  it("old seven-field summary preserves all seven fields in their original order", () => {
    const report = parseV213Top20Report(top20Report() as never)!;
    const flex = buildV213Top20Messages(report);
    assertLineMessages(flex);
    const body = tokens(bubblesOf(flex)[0]);
    const fields = ["股票", "長期投資報酬率", "短期投資報酬率", "行業別", "獲利簡述", "公司現在訂單", "未來訂單預估"];
    let previous = -1;
    for (const field of fields) {const at = body.indexOf(field);expect(at, field).toBeGreaterThan(previous);previous = at;}
  });

  it("formats snapshot and audit-builder instants for Taipei in every visible user text (postback tokens excluded)", () => {
    const bottleneck = parseBottleneckV3(doc(REPORT - HOUR), REPORT)!;
    const sealed = parseV213Top20Report(top20Report() as never)!;
    const entries = [
      ...buildBottleneckTop20Messages(bottleneck, "text"),
      ...buildIndustryExplosionMessages(bottleneck, "text"),
      { type: "text" as const, text: String(buildBottleneckDetail(bottleneck, "NO_MATCH", "text")) },
      ...buildV213Top20Messages(sealed, "bilingual", "text"),
      ...buildCompanyEvidenceMessages(sealed, sealed.records[0]!.ticker),
      ...buildTop20DeepAnalysisMessages(sealed, sealed.records[0]!.ticker),
    ];
    for (const entry of entries) assertLineMessages([entry]);
    const text = renderedText(entries);
    expect(text).toContain("（台北）");
    expect(text).not.toMatch(/\b\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z\b/);
  });
});
