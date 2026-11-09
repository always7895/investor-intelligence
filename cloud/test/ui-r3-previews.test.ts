/** UI-R3 offline preview exporter. Run with UI_R3_WRITE_PREVIEWS=1 to write ui-r3/previews/.
 * Synthetic fixtures only. No Worker, KV, LINE API, network, Production or broker access.
 */
import { describe, expect, it } from "vitest";
import { mkdirSync, writeFileSync } from "node:fs";
import { resolve, join } from "node:path";
import { createHash } from "node:crypto";
import { assertLineMessages, type LineOutboundMessage } from "../src/line-messages";
import { parseQuery } from "../src/core";
import { doc, HOUR } from "./bottleneck-v3-fixture";
import modDistributionFact from "../../tests/fixtures/gap-c-mod-sec-8k.json";
import { parseBottleneckV3, buildBottleneckTop20Messages, buildBottleneckDetail } from "../src/v213/bottleneck-v3";
import { buildOptionsGuidanceFlexBubble, buildOptionsGuidanceText, generateOptionsOrderGuidance } from "../src/v213/options-guidance";
import { optionsUnavailableReport } from "../src/v213/options-product";
import { buildGlobalEquityLookupMessages, type EquityLookupResult } from "../src/v213/global-equity-lookup";
import { v213PublicLineAnswer } from "../src/v213/rich-menu";

const asMessages = (value: LineOutboundMessage[] | string | null): LineOutboundMessage[] =>
  typeof value === "string" ? [{ type: "text", text: value }] : value ?? [];

const clone = <T,>(input: T): T => structuredClone(input);

/** GAP-C: actual SEC terms in an otherwise synthetic, forced-inclusion MOD card.
 * The real ranker excludes MOD while its distribution-crossing CAGR is unknown.
 * This fixture deliberately forces an entry to exercise the LINE renderer, not ranking.
 */
function makeGapCModOutputs(now: number): Record<string, LineOutboundMessage[]> {
  const raw = clone(doc(now - HOUR)) as any;
  raw.top[0].symbol = modDistributionFact.target_symbol;
  raw.top[0].name = "Synthetic MOD Distribution UI Case";
  raw.top[0].layer = "cooling_power_train";
  raw.industries.push({ ...raw.industries[0], rank: 4, id: "cooling_power_train", name_zh: "散熱與機房電力鏈" });
  raw.top[0].market = {
    ...raw.top[0].market, asof: "2026-11-06", currency: "USD",
    history_start: "2023-11-06", history_request_start: "2023-11-06",
    lineage: { kind: "UNKNOWN" }, long_term_basis: "UNAVAILABLE",
    cagr_listed: null, cagr_listed_start: null, cagr_listed_span_days: null,
    ret_6m: null, ret_1y: null, cagr_2y: null,
    return_reasons: {
      ret_6m: "DISTRIBUTION_IN_WINDOW",
      ret_1y: "DISTRIBUTION_IN_WINDOW",
      cagr_2y: "DISTRIBUTION_IN_WINDOW",
    },
  };
  raw.top[0].corporate_action = {
    target_market: "US", target_symbol: modDistributionFact.target_symbol,
    kind: "DISTRIBUTION", status: "CLOSED",
    distribution_date: modDistributionFact.distribution_date,
    related_market: "US", related_symbol: modDistributionFact.related_symbol,
    shares_per_share: modDistributionFact.shares_per_mod_share,
    source_url: modDistributionFact.source_url,
    source_date: modDistributionFact.published_on, review_by: null,
  };
  const parsed = parseBottleneckV3(raw, now);
  if (!parsed) throw new Error("UI_R3_GAP_C_MOD_FIXTURE_INVALID");
  return {
    "gap-c-mod-top20-flex.json": buildBottleneckTop20Messages(parsed, "flex"),
    "gap-c-mod-top20-text.json": buildBottleneckTop20Messages(parsed, "text"),
    "gap-c-mod-detail-flex.json": asMessages(buildBottleneckDetail(parsed, "MOD", "flex")),
    "gap-c-mod-detail-text.json": asMessages(buildBottleneckDetail(parsed, "MOD", "text")),
  };
}

async function makePreviews(): Promise<Record<string, LineOutboundMessage[]>> {
  const now = Date.now();
  const standard = parseBottleneckV3(doc(now - HOUR), now);
  if (!standard) throw new Error("UI_R3_PREVIEW_TOP20_FIXTURE_INVALID");
  const topFlex = buildBottleneckTop20Messages(standard, "flex");
  const first = topFlex[0]!;
  if (first.type !== "flex" || !Array.isArray(first.contents.contents)) throw new Error("UI_R3_PREVIEW_TOP20_FLEX_SHAPE");
  const firstThree: LineOutboundMessage[] = [{
    type: "flex", altText: `瓶頸 TOP20｜${standard.generated_at.slice(0, 10)}`,
    contents: { type: "carousel", contents: first.contents.contents.slice(0, 3) },
  }];

  // The deal is a synthetic rendering case: MRVL acquires LITE at 4.500 shares.
  // All terms belong to this offline fixture and are not asserted as live corporate facts.
  const dealRaw = clone(doc(now - HOUR)) as any;
  dealRaw.top[0].symbol = "MRVL";
  dealRaw.top[0].name = "Synthetic MRVL Acquirer";
  dealRaw.top[0].corporate_action = {
    target_symbol: "LITE", acquirer_symbol: "MRVL", kind: "ALL_STOCK", status: "PENDING",
    exchange_ratio: 4.5, cash_per_share: null, currency: null,
    expected_close: "first half of calendar year 2028",
    source_url: "https://www.sec.gov/Archives/edgar/data/0001633978/000119312526442758/d163169dex991.htm",
  };
  const dealDoc = parseBottleneckV3(dealRaw, now);
  if (!dealDoc) throw new Error("UI_R3_PREVIEW_DEAL_FIXTURE_INVALID");
  const dealCarousels = buildBottleneckTop20Messages(dealDoc, "flex");
  const dealBubble = dealCarousels.flatMap(message => message.type === "flex"
    ? (message.contents.contents as unknown[]) : []).find(bubble =>
      typeof bubble === "object" && bubble !== null && JSON.stringify((bubble as any).header).includes("MRVL"));
  if (!dealBubble) throw new Error("UI_R3_PREVIEW_DEAL_BUBBLE_MISSING");
  const dealFlex: LineOutboundMessage[] = [{
    type: "flex", altText: `LITE／MRVL 併購提醒｜${dealDoc.generated_at.slice(0, 10)}`,
    contents: { type: "carousel", contents: [dealBubble] },
  }];
  const dealText = asMessages(buildBottleneckDetail(dealDoc, "MRVL", "text"));
  if (!JSON.stringify(dealText).includes("4.500")) throw new Error("UI_R3_PREVIEW_DEAL_TERMS_MISSING");

  const guidance = generateOptionsOrderGuidance({
    ticker: "SYN", strategy: "covered_call", underlyingPrice: 128.4, strike: 135,
    expiry: "2026-12-18", dte: 40, delta: 0.25,
    bid: 2.1, mid: 2.25, ask: 2.4, openInterest: 1200, volume: 350,
  });
  const identity: EquityLookupResult = {
    identity: {
      rawInput: "SYN", normalizedSymbol: "SYN", canonicalSymbol: "SYN",
      canonicalNameEn: "Synthetic Preview Corporation",
      market: "US", country: "United States", exchange: "NASDAQ",
      currency: "USD", isAmbiguous: false, leadingZeroPreserved: false,
    },
    quoteStatus: "UNAVAILABLE", admittedInSealedSnapshot: false,
    nameUnverified: true, source: "unsealed_or_missing",
    disclaimer: "合成示範資料；不代表已准入的真實上市標的或報價；非投資建議。",
  };
  const menuFlex = asMessages(await v213PublicLineAnswer({} as never, parseQuery("選單")));
  const menuText = asMessages(await v213PublicLineAnswer({ V213_LINE_PRESENTATION: "text" } as never, parseQuery("選單")));
  return {
    "top20-flex.json": firstThree,
    "top20-text.json": buildBottleneckTop20Messages(standard, "text"),
    "lite-mrvl-deal-flex.json": dealFlex,
    "lite-mrvl-deal-text.json": dealText,
    "options-flex.json": [buildOptionsGuidanceFlexBubble(guidance)],
    "options-text.json": [{ type: "text", text: buildOptionsGuidanceText(guidance) }],
    "options-unavailable-flex.json": optionsUnavailableReport("SYN", "monthly", "NO_LISTED_OPTIONS", false),
    "options-unavailable-text.json": optionsUnavailableReport("SYN", "monthly", "NO_LISTED_OPTIONS", true),
    "name-lookup-flex.json": buildGlobalEquityLookupMessages(identity, "flex"),
    "name-lookup-text.json": buildGlobalEquityLookupMessages(identity, "text"),
    "main-menu-flex.json": menuFlex,
    "main-menu-text.json": menuText,
  };
}

describe("UI-R3 offline preview artifacts", () => {
  it("validates all requested synthetic Flex and text surfaces and optionally exports review JSON", async () => {
    const surfaces = await makePreviews();
    expect(Object.keys(surfaces)).toHaveLength(12);
    for (const [name, messages] of Object.entries(surfaces)) {
      expect(messages.length, name).toBeGreaterThan(0);
      assertLineMessages(messages);
      expect(messages.every(message => message.type === (name.includes("-flex") ? "flex" : "text")), name).toBe(true);
    }
    expect((surfaces["top20-flex.json"]![0] as Extract<LineOutboundMessage, {type:"flex"}>).contents.contents).toHaveLength(3);
    if (process.env.UI_R3_WRITE_PREVIEWS !== "1") return;
    const output = resolve(__dirname, "../../../previews");
    if (!/[/\\]ui-r3[/\\]previews$/.test(output)) throw new Error("UI_R3_PREVIEW_BAD_OUTPUT");
    mkdirSync(output, { recursive: true });
    const manifest: Record<string, string> = {};
    for (const [name, messages] of Object.entries(surfaces)) {
      const data = JSON.stringify({
        kind: "UI-R3_OFFLINE_SYNTHETIC_PREVIEW",
        real_market_or_quote: false, may_send_to_LINE: false,
        generated_at: new Date().toISOString(),
        messages,
      }, null, 2) + "\n";
      writeFileSync(join(output, name), data, "utf8");
      manifest[name] = createHash("sha256").update(data).digest("hex");
    }
    writeFileSync(join(output, "MANIFEST.sha256.json"), JSON.stringify(manifest, null, 2) + "\n", "utf8");
    writeFileSync(join(output, "README.txt"),
      "UI-R3 offline review previews. All companies, numbers, deal terms and sources are synthetic/test fixture values.\n" +
      "The LITE/MRVL case uses synthetic deal metadata for a renderer regression example, not a fact claim.\n" +
      "No network, Worker, brokerage or LINE send was performed. JSON files hold raw LINE Flex/text payloads.\n", "utf8");
  });

  it("guards 12 UI-R3 previews plus 4 GAP-C MOD outputs against raw status tokens and snake_case codes", async () => {
    const surfaces = { ...await makePreviews(), ...makeGapCModOutputs(Date.now()) };
    const visibleText = (messages: readonly LineOutboundMessage[]): string => {
      const lines: string[] = [];
      const visit = (value: unknown): void => {
        if (!value || typeof value !== "object") return;
        if (Array.isArray(value)) { for (const child of value) visit(child); return; }
        const node = value as Record<string, unknown>;
        if (node.type === "text") {
          if (typeof node.text === "string") lines.push(node.text);
          else if (Array.isArray(node.contents)) lines.push(node.contents
            .map(span => typeof span === "object" && span !== null && typeof (span as any).text === "string"
              ? (span as any).text : "").join(""));
          return;
        }
        for (const [key, child] of Object.entries(node)) if (key !== "action") visit(child);
      };
      for (const message of messages) {
        if (message.type === "text") lines.push(message.text);
        else { lines.push(message.altText); visit(message.contents); }
      }
      return lines.join("\n");
    };
    for (const [name, messages] of Object.entries(surfaces)) {
      const text = visibleText(messages);
      expect(text, name).not.toMatch(/([^：\n]{2,28})：\1：/gu);
      expect(text, name).not.toMatch(/\b\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z\b/);
      expect(text, name).not.toMatch(/(?<![A-Za-z0-9_./-])(?:[A-Z][A-Z0-9]*(?:_[A-Z0-9]+)+|[a-z][a-z0-9]*(?:_[a-z0-9]+)+)(?![A-Za-z0-9_./-])/);
    }
    const modOutputs = Object.entries(surfaces).filter(([name]) => name.startsWith("gap-c-mod-"));
    expect(modOutputs).toHaveLength(4);
    for (const [name, messages] of modOutputs) {
      const rendered = visibleText(messages);
      expect(rendered, name).toContain("分拆後尚無經驗證的調整價格，暫不計算（不視為零）");
      expect(rendered, name).toContain("0.44619");
      expect(rendered, name).not.toContain("DISTRIBUTION_IN_WINDOW");
    }
    // The actual ranker withholds MOD's 2-year CAGR. The sealed v3 reader has
    // no 'excluded' rows; direct detail lookup therefore reports non-membership,
    // and must not manufacture an in-list MOD company card.
    const normal = parseBottleneckV3(doc(Date.now() - HOUR));
    expect(normal).not.toBeNull();
    expect(buildBottleneckDetail(normal!, "MOD", "text")).toContain("不在本輪瓶頸爆發 TOP20");
    expect(visibleText(surfaces["top20-text.json"]!)).toContain("（台北）");
    const deal = visibleText(surfaces["lite-mrvl-deal-text.json"]!);
    expect(deal).toContain("預計 2028 年上半年完成");
    expect(deal).not.toContain("併購進行中：併購進行中：");
    const options = surfaces["options-flex.json"]![0] as Extract<LineOutboundMessage, {type:"flex"}>;
    expect(options.altText).toMatch(/^期權掛單參數｜SYN 月期權｜\d{4}-\d{2}-\d{2}$/);
    expect(options.altText).not.toContain("LIMIT");
    expect(options.altText).not.toContain("Monthly");
  });
});
