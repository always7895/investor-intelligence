// V20 (LINE Flex UI/UX polish): density budgets over the main flex builders with realistic-length fixtures.
// The design budgets (docs/LINE_TOP20_UI.md) are asserted where the data allows them; every surface also has a measured ceiling
// so a regression to the pre-V20 wall of text fails. Figures and disclosures are asserted elsewhere (per-surface suites);
// this file only measures structure. Synthetic data only.
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { LineOutboundMessage } from "../src/line-messages";
import { parseQuery } from "../src/core";
import { buildV213Top20Messages } from "../src/v213/top20-presentation";
import { parseV213Top20Report } from "../src/v213/top20-report";
import { buildBottleneckDetail, buildBottleneckTop20Messages, buildIndustryExplosionMessages, parseBottleneckV3 } from "../src/v213/bottleneck-v3";
import { buildCoveredCallMessages, validateCoveredCallCycle } from "../src/v213/covered-call";
import { buildOptionsGuidanceFlexBubble, buildPositionSizingFlexBubble, generateOptionsOrderGuidance, generatePositionSizingFramework } from "../src/v213/options-guidance";
import { buildEducationalStrategyFlex } from "../src/v213/educational-options";
import { buildOptionContractFlex, optionsUnavailableReport } from "../src/v213/options-product";
import { validateOptionContractQuote } from "../src/v213/market-product-schema";
import { v213PublicLineAnswer } from "../src/v213/rich-menu";
import { BULLET_DOT_SIZE, BUTTON_LABEL_MAX, bulletList, bulletRow, clampText, detailsButton, altSummary, disclosureLine, kvRow } from "../src/v213/line-theme";
import { doc as bottleneckDoc } from "./bottleneck-v3-fixture";
import { admitSyntheticTickers, resetAdmissionToReal } from "./synthetic-option-admission";

vi.mock("../src/v213/public-options-admission", async importOriginal => {
  const real = await importOriginal<typeof import("../src/v213/public-options-admission")>();
  return { ...real, admitPublicOption: vi.fn(real.admitPublicOption) };
});
beforeEach(() => { resetAdmissionToReal(); });

type Node = Record<string, any>;
interface Metrics { texts: number; chars: number; bullets: number; sections: number; xxs: number; buttons: number; footerButtons: number;
  longPlain: string[]; maxLinesUsed: number; labels: string[]; footerDisclosureLines: number }

const visible = (node: Node) => typeof node.text === "string" ? node.text : (node.contents ?? []).map((span: Node) => span.text ?? "").join("");
const isDot = (node: Node) => node?.type === "box" && node.width === BULLET_DOT_SIZE && node.height === BULLET_DOT_SIZE;
const isBulletRow = (node: Node) => node?.type === "box" && node.layout === "horizontal" && Array.isArray(node.contents) && node.contents.length === 2 && isDot(node.contents[0]);

/** Structure metrics of one bubble. A "section" is a framed box with a titled strip (borderWidth set). */
function measure(bubble: Node): Metrics {
  const m: Metrics = { texts: 0, chars: 0, bullets: 0, sections: 0, xxs: 0, buttons: 0, footerButtons: 0, longPlain: [], maxLinesUsed: 0, labels: [], footerDisclosureLines: 0 };
  const walk = (node: any, inBullet: boolean, inFooter: boolean) => {
    if (Array.isArray(node)) { node.forEach(child => walk(child, inBullet, inFooter)); return; }
    if (!node || typeof node !== "object") return;
    if (node.type === "button") { m.buttons += 1; if (inFooter) m.footerButtons += 1; m.labels.push(node.action?.label ?? ""); return; }
    if (node.type === "box" && node.borderWidth && node.cornerRadius === "md" && node.spacing === "none") m.sections += 1;
    const bullet = isBulletRow(node);
    if (bullet) m.bullets += 1;
    if (node.type === "text") {
      const text = visible(node);
      m.texts += 1; m.chars += Array.from(text).length;
      if (node.size === "xxs") m.xxs += 1;
      if (node.maxLines) m.maxLinesUsed += 1;
      if (inFooter && node.size === "xxs" && Array.from(text).length > 60) m.footerDisclosureLines += 1;
      if (!inBullet && node.size !== "xxs" && Array.from(text).length > 60) m.longPlain.push(text);
      return;
    }
    Object.entries(node).forEach(([key, value]) => { if (key !== "type") walk(value, inBullet || bullet, inFooter || key === "footer"); });
  };
  walk(bubble, false, false);
  return m;
}

const bubblesOf = (messages: readonly LineOutboundMessage[]): Node[] =>
  messages.flatMap(message => message.type === "flex" ? (message.contents as Node).contents as Node[] : []);
const worst = (list: Metrics[], key: "texts" | "chars" | "bullets" | "sections" | "footerButtons" | "xxs") => Math.max(...list.map(item => item[key]));

// --- realistic-length fixtures -----------------------------------------------------------------------------------------
function top20Report() {
  return {
    schema_version: 2, product_version: "2.1.3", generated_at: "2026-09-01T00:00:00Z",
    freshness_policy: { policy_id: "v213-serenity-fresh-independent-evidence-v2", policy_sha256: "27ce461fae50218bb14e4d50ff283f6ed75b201e4a38d656643a5ed65d59c8d8" },
    evidence_capture_at: "2026-09-15T11:00:00Z",
    display_columns: ["股票", "長期投資報酬率（近2年年化）", "短期投資報酬率（近6個月）", "行業別", "獲利簡述", "公司現在訂單", "未來訂單預估"],
    long_term_definition: "trailing_2y_adjusted_close_cagr", short_term_definition: "trailing_6m_adjusted_close_price_return",
    records: Array.from({ length: 20 }, (_, index) => ({
      schema_version: 2, rank: index + 1, ticker: `T${String(index).padStart(2, "0")}`, name: `Synthetic Semiconductor Holdings ${index}`,
      long_term_return_pct: 50 - index, short_term_return_pct: 15 - index / 2, industry: "半導體設備與先進封裝材料",
      profit_summary: "最新季營收年增 +20.0%，毛利率 52.1%，營業利益率 31.4%；自由現金流為正，稀釋股數年增 1.2%。",
      current_orders: "2027 年前已簽約固定量約 RMB1.73 億，另有三年期供貨協議；公司於 2026-08 季報揭露在手訂單年增 +35%。",
      future_orders_estimate: "能見度偏高但不估總額；管理層指引下一財年新接訂單年增 20%–30%，但未提供金額，系統不推估訂單總額。",
      long_term_window: "2y_cagr", short_term_window: "6m_price_return", market_source: "yfinance", profit_source: "sec_edgar",
      orders_as_of: "2026-09-01T00:00:00Z", orders_confidence: "EVIDENCE_BOUND",
      current_order_source_urls: ["https://www.sec.gov/example/current"], future_order_source_urls: ["https://www.sec.gov/example/future"],
      numeric_total_order_estimate_prohibited: true, retrieved_at: "2026-09-01T00:00:00Z", orders_state_as_of: "2026-09-01T00:00:00Z",
      evidence_class: "structural_claim", freshness_policy_key: "structural_claim_max_age_days", test_only_admission: true,
      provider_scope: "public_only", owner_watchlist_inherited: false,
    })),
    provider_scope: "public_only", owner_watchlist_inherited: false,
  };
}

const REPORT = Date.parse("2026-09-27T01:00:00Z");
const tierItem = (role: string, strike: number, bid: number, ask: number, delta: number, spot: number, dte: number) => {
  const mid = Number(((bid + ask) / 2).toFixed(4));
  const limit = Number((Math.floor(mid / 0.01 + 1e-9) * 0.01).toFixed(2));
  return { role, strike, bid, ask, mid, limit_price: limit, premium_per_contract: limit * 100, period_yield: limit / spot,
    annualized_yield: limit / spot * 365 / Math.max(dte, 1), upside_to_strike: strike / spot - 1, delta, delta_basis: "QUOTED", iv: 0.4,
    oi: 1200, volume: 350, spread_pct: (ask - bid) / mid };
};
const coveredCycle = () => ({ ticker: "NVDA", strategy: "COVERED_CALL", expiry: "2026-10-09", dte: 2, spot: 100, currency: "USD", multiplier: 100,
  quote_basis: "delayed", timestamp: "2026-10-07T14:00:00Z", source: "Yahoo Finance option chain (unofficial, delayed)",
  provenance: "https://finance.yahoo.com/quote/NVDA/options", rights_status: "unadmitted_third_party", asof_date: "2026-10-07", weekly_week: "CURRENT",
  suggestions: [tierItem("HIGH_STRIKE", 112, 0.10, 0.12, 0.08, 100, 2), tierItem("BALANCED", 106, 0.60, 0.66, 0.28, 100, 2)],
  middle_suggestion: tierItem("MIDDLE", 108, 0.35, 0.40, 0.20, 100, 2) });

// Pre-V20 worst-bubble figures on these same fixtures (measured at 74f3e99 with this file's `measure`): texts / chars / xxs texts.
const BEFORE: Record<string, { texts: number; chars: number; xxs: number }> = {
  "top20-presentation": { texts: 29, chars: 1081, xxs: 17 },
  "bottleneck Top20 card": { texts: 44, chars: 818, xxs: 22 },
  "bottleneck detail page 1": { texts: 75, chars: 1587, xxs: 38 },
  "bottleneck industry": { texts: 20, chars: 294, xxs: 9 },
  "covered-call (3 tiers)": { texts: 59, chars: 955, xxs: 40 },
  "options-guidance order": { texts: 26, chars: 684, xxs: 12 },
  "options-guidance sizing": { texts: 14, chars: 566, xxs: 6 },
  "educational-options": { texts: 21, chars: 763, xxs: 5 },
  "options-product contract": { texts: 14, chars: 347, xxs: 4 },
  "options-product unavailable": { texts: 8, chars: 304, xxs: 0 },
  "rich-menu navigation": { texts: 8, chars: 396, xxs: 1 },
};
// Ceilings (worst bubble per surface). Design budgets per page: <= 14 texts, <= 480 chars, <= 5 bullets per section, <= 2 sections.
// Surfaces whose content is dominated by sealed data (the seven-field values, the order-evidence rows of a Top20 card, three covered-call
// tiers) cannot meet the 14-text / 480-char budget; their ceiling is the measured V20 value plus a small margin and is strictly below
// BEFORE. The headline surfaces below do meet the design budget (second test).
const CEILING: Record<string, { texts: number; chars: number; bullets: number; sections: number; footerButtons: number }> = {
  "top20-presentation": { texts: 24, chars: 710, bullets: 0, sections: 0, footerButtons: 1 },
  "bottleneck Top20 card": { texts: 36, chars: 730, bullets: 10, sections: 0, footerButtons: 2 },
  "bottleneck detail page 1": { texts: 34, chars: 410, bullets: 2, sections: 0, footerButtons: 2 },
  "bottleneck industry": { texts: 18, chars: 290, bullets: 2, sections: 0, footerButtons: 2 },
  "covered-call (3 tiers)": { texts: 56, chars: 910, bullets: 6, sections: 3, footerButtons: 2 },
  "options-guidance order": { texts: 23, chars: 490, bullets: 3, sections: 0, footerButtons: 1 },
  "options-guidance sizing": { texts: 10, chars: 400, bullets: 2, sections: 0, footerButtons: 1 },
  "educational-options": { texts: 10, chars: 560, bullets: 6, sections: 0, footerButtons: 2 },
  "options-product contract": { texts: 10, chars: 330, bullets: 6, sections: 0, footerButtons: 2 },
  "options-product unavailable": { texts: 7, chars: 230, bullets: 4, sections: 0, footerButtons: 3 },
  "rich-menu navigation": { texts: 9, chars: 210, bullets: 5, sections: 1, footerButtons: 3 },
};

describe("V20 density budgets (realistic fixtures)", () => {
  const surfaces: Record<string, () => Promise<Node[]> | Node[]> = {
    "top20-presentation": () => bubblesOf(buildV213Top20Messages(parseV213Top20Report(top20Report() as never)!)),
    "bottleneck Top20 card": () => bubblesOf(buildBottleneckTop20Messages(parseBottleneckV3(bottleneckDoc(REPORT - 3600_000), REPORT)!, "flex")),
    "bottleneck detail page 1": () => {
      const parsed = parseBottleneckV3(bottleneckDoc(REPORT - 3600_000), REPORT)!;
      return parsed.top.flatMap(entry => {
        const detail = buildBottleneckDetail(parsed, entry.symbol, "flex");
        return typeof detail === "string" ? [] : [bubblesOf(detail)[0]!];
      });
    },
    "bottleneck industry": () => bubblesOf(buildIndustryExplosionMessages(parseBottleneckV3(bottleneckDoc(REPORT - 3600_000), REPORT)!, "flex")),
    "covered-call (3 tiers)": () => {
      admitSyntheticTickers("NVDA");
      return bubblesOf(buildCoveredCallMessages(validateCoveredCallCycle(coveredCycle())!, "每週期權", "flex"));
    },
    "options-guidance order": () => {
      const guidance = generateOptionsOrderGuidance({ ticker: "nvda", strategy: "covered_call", underlyingPrice: 128.4, strike: 135, expiry: "2026-12-18",
        dte: 94, delta: 0.25, bid: 2.1, mid: 2.25, ask: 2.4, openInterest: 1200, volume: 350 });
      return bubblesOf([buildOptionsGuidanceFlexBubble(guidance)]);
    },
    "options-guidance sizing": () => bubblesOf([buildPositionSizingFlexBubble(generatePositionSizingFramework("BOTTLENECK_CHOKEPOINT"), "NVDA")]),
    "educational-options": () => bubblesOf(buildEducationalStrategyFlex()),
    "options-product contract": () => {
      admitSyntheticTickers("NVDA");
      const quote = validateOptionContractQuote({ ticker: "NVDA", expiry: "2026-09-25", dte: 11, strike: 125, type: "call", bid: 4.2, mid: 4.35, ask: 4.5, spread: 0.3,
        delta: 0.52, iv: 0.45, oi: 2500, volume: 480, breakeven: null, maxprofit: null, maxloss: null, annualized_yield: null,
        assignment_risk: "買方持有權利，無被動指派風險", liquidity_warning: "雙邊價差合理，流動性良好", timestamp: "2026-09-14T12:00:00Z",
        quote_basis: "delayed", source: "yfinance_public", provenance: "OP_TEST_SUITE", currency: "USD", multiplier: 100, rights_status: "unadmitted_third_party" } as never,
      { evaluatedAt: "2026-09-14T12:00:00Z" });
      return bubblesOf(buildOptionContractFlex(quote, { evaluatedAt: "2026-09-14T12:00:00Z" }));
    },
    "options-product unavailable": () => bubblesOf(optionsUnavailableReport("NVDA", "weekly",
      "本輪封存資料沒有 NVDA 的每週期權觀察。（已封存之公開觀察）本輪封存資料沒有 NVDA 的每週期權觀察。", false)),
    "rich-menu navigation": async () => bubblesOf(await v213PublicLineAnswer({} as never, parseQuery("選單")) as LineOutboundMessage[]),
  };

  for (const [name, build] of Object.entries(surfaces)) {
    it(`${name}: within its density ceiling, no vague button, no clipped figure`, async () => {
      const bubbles = await build();
      expect(bubbles.length).toBeGreaterThan(0);
      const metrics = bubbles.map(measure);
      const ceiling = CEILING[name]!;
      if (process.env.V20_LOG) process.stderr.write(`@@ ${name} bubbles=${metrics.length} texts=${worst(metrics, "texts")} chars=${worst(metrics, "chars")} bullets=${worst(metrics, "bullets")} sections=${worst(metrics, "sections")} xxs=${worst(metrics, "xxs")} footerButtons=${worst(metrics, "footerButtons")} long=${Math.max(...metrics.map(m => m.longPlain.length))}
`);
      expect(worst(metrics, "texts"), `${name} texts`).toBeLessThanOrEqual(ceiling.texts);
      expect(worst(metrics, "chars"), `${name} chars`).toBeLessThanOrEqual(ceiling.chars);
      expect(worst(metrics, "bullets"), `${name} bullets`).toBeLessThanOrEqual(ceiling.bullets);
      expect(worst(metrics, "sections"), `${name} sections`).toBeLessThanOrEqual(ceiling.sections);
      expect(worst(metrics, "footerButtons"), `${name} footer buttons`).toBeLessThanOrEqual(ceiling.footerButtons);
      // V20 never makes a surface denser than before: fewer characters everywhere, no more texts (the navigation panel gains
      // one dot-less disclosure line while halving its characters).
      expect(worst(metrics, "chars"), `${name} chars vs before`).toBeLessThan(BEFORE[name]!.chars);
      expect(worst(metrics, "texts"), `${name} texts vs before`).toBeLessThanOrEqual(BEFORE[name]!.texts + (name === "rich-menu navigation" ? 1 : 0));
      for (const item of metrics) {
        for (const label of item.labels) {
          expect(Array.from(label).length, label).toBeLessThanOrEqual(BUTTON_LABEL_MAX);
          expect(label.trim()).not.toMatch(/^(?:詳情|更多|詳細|查看|Details|More)$/i);
        }
      }
    });
  }

  it("the headline surfaces meet the design page budget of 14 texts and 480 characters where the data allows it", async () => {
    // Surfaces whose content is dominated by sealed data (seven-field values, evidence pages) are excluded on purpose.
    for (const name of ["options-guidance sizing", "options-product unavailable", "options-product contract", "rich-menu navigation"]) {
      const metrics = (await surfaces[name]!()).map(measure);
      expect(worst(metrics, "texts"), name).toBeLessThanOrEqual(14);
      expect(worst(metrics, "chars"), name).toBeLessThanOrEqual(480);
    }
  });

  it("bullet-based pages never use maxLines on a card that carries figures or disclosures", async () => {
    for (const name of ["top20-presentation", "covered-call (3 tiers)", "options-guidance order", "options-product contract", "educational-options"]) {
      const metrics = (await surfaces[name]!()).map(measure);
      expect(metrics.every(item => item.maxLinesUsed === 0), name).toBe(true);
    }
  });

  it("every flex message keeps a specific altText within 120 characters on the migrated surfaces", async () => {
    admitSyntheticTickers("NVDA");
    const parsed = parseBottleneckV3(bottleneckDoc(REPORT - 3600_000), REPORT)!;
    const messages: LineOutboundMessage[] = [
      ...buildV213Top20Messages(parseV213Top20Report(top20Report() as never)!),
      ...buildBottleneckDetail(parsed, "S1", "flex") as LineOutboundMessage[],
      ...buildCoveredCallMessages(validateCoveredCallCycle(coveredCycle())!, "每週期權", "flex"),
      ...buildEducationalStrategyFlex("covered_call"),
      ...optionsUnavailableReport("NVDA", "weekly", "本輪封存資料沒有 NVDA 的每週期權觀察。", false),
    ];
    for (const message of messages) {
      if (message.type !== "flex") continue;
      expect(Array.from(message.altText).length, message.altText).toBeLessThanOrEqual(120);
      expect(message.altText.split("｜").length, message.altText).toBeGreaterThanOrEqual(2);
    }
  });
});

describe("V20 detail commands behind the shortened disclosures", () => {
  it("`選單 文字` and `期權教學 <策略> 文字` return the full text edition", async () => {
    for (const command of ["選單 文字", "期權教學 cash_secured_put 文字"]) {
      const messages = await v213PublicLineAnswer({} as never, parseQuery(command)) as LineOutboundMessage[];
      expect(Array.isArray(messages), command).toBe(true);
      expect(messages.every(message => message.type === "text"), command).toBe(true);
    }
    const menu = await v213PublicLineAnswer({} as never, parseQuery("選單 文字")) as { type: "text"; text: string }[];
    expect(menu.map(message => message.text).join(" ")).toContain("不連券商、不下單，內容非投資建議");
  });

  it("the covered-call and educational cards point at commands that exist", () => {
    admitSyntheticTickers("NVDA");
    const buttons = (messages: LineOutboundMessage[]) => bubblesOf(messages).flatMap(bubble => JSON.stringify(bubble).match(/"text":"([^"]+)"\}\}/g) ?? []);
    expect(buttons(buildCoveredCallMessages(validateCoveredCallCycle(coveredCycle())!, "每週期權", "flex")).join(" ")).toContain("NVDA 每週期權 文字");
    expect(buttons(buildEducationalStrategyFlex("covered_call")).join(" ")).toContain("期權教學 covered_call 文字");
  });
});

describe("V20 primitives", () => {
  it("bulletRow is a dot plus one wrapping text; maxLines only when asked", () => {
    const row = bulletRow("營收年增 +109%") as Node;
    expect(isBulletRow(row)).toBe(true);
    expect(row.contents[1]).toMatchObject({ type: "text", wrap: true, flex: 1 });
    expect(row.contents[1].maxLines).toBeUndefined();
    expect((bulletRow("說明", { maxLines: 2 }) as Node).contents[1].maxLines).toBe(2);
  });

  it("bulletList caps at max and says how many were left", () => {
    const rows = bulletList(["一", "二", "三", "四", "五", "六", "七"], { max: 5 }) as Node[];
    expect(rows.filter(isBulletRow)).toHaveLength(5);
    expect(JSON.stringify(rows.at(-1))).toContain("另有 2 項");
  });

  it("kvRow keeps a figure whole (no maxLines by default) and puts the sub line under the row", () => {
    const row = kvRow("年化收益", "13.3%", { sub: "期間 0.15%" }) as Node;
    expect(JSON.stringify(row)).not.toContain("maxLines");
    expect(JSON.stringify(row)).toContain("期間 0.15%");
  });

  it("detailsButton rejects vague labels and clamps to LINE's 20-character label limit", () => {
    expect(() => detailsButton("詳情", "x")).toThrow("V20_BUTTON_LABEL_VAGUE");
    expect(() => detailsButton("Details", "x")).toThrow("V20_BUTTON_LABEL_VAGUE");
    const label = (detailsButton("查看 NVDA 完整數據與來源網址與更多說明", "x") as Node).action.label as string;
    expect(Array.from(label).length).toBeLessThanOrEqual(BUTTON_LABEL_MAX);
  });

  it("clampText is code-point safe; disclosureLine joins with a fullwidth bar; altSummary stays within 120", () => {
    expect(clampText("𠮷𠮷𠮷𠮷", 3)).toBe("𠮷𠮷…");
    expect(clampText("短", 3)).toBe("短");
    expect((disclosureLine(["來源：A", "", "非投資建議"]) as Node).text).toBe("來源：A｜非投資建議");
    expect(Array.from(altSummary({ topic: "題".repeat(100), status: "狀態".repeat(30), next: "下一步" })).length).toBeLessThanOrEqual(120);
  });
});
