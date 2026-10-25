import { mkdirSync, writeFileSync } from "node:fs";
import { isAbsolute, join, resolve, sep } from "node:path";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { resetAdmissionToReal } from "./synthetic-option-admission";
import { measure, v25FlexMessages, v25Surfaces, type Node } from "./flex-density-fixtures";
import { LINE_THEME as T, verdictLine } from "../src/v213/line-theme";

vi.mock("../src/v213/public-options-admission", async importOriginal => {
  const real = await importOriginal<typeof import("../src/v213/public-options-admission")>();
  return { ...real, admitPublicOption: vi.fn(real.admitPublicOption) };
});
beforeEach(() => { resetAdmissionToReal(); });

const V20_CEILINGS: Record<string, { texts: number; chars: number }> = {
  "top20-presentation": { texts: 24, chars: 710 },
  "bottleneck Top20 card": { texts: 36, chars: 730 },
  "bottleneck detail page 1": { texts: 34, chars: 410 },
  "bottleneck industry": { texts: 18, chars: 290 },
  "covered-call (3 tiers)": { texts: 56, chars: 910 },
  "options-guidance order": { texts: 23, chars: 490 },
  "options-guidance sizing": { texts: 10, chars: 400 },
  "educational-options": { texts: 10, chars: 560 },
  "options-product contract": { texts: 10, chars: 330 },
  "options-product unavailable": { texts: 7, chars: 230 },
  "rich-menu navigation": { texts: 9, chars: 210 },
  "V21 three strategies": { texts: 56, chars: 910 },
  "options-guidance cycle comparison": { texts: 23, chars: 490 },
  "bottleneck detail (all pages)": { texts: 23, chars: 963 },
};
const V25_AFTER_CEILINGS: Record<string, { texts: number; chars: number }> = {
  "top20-presentation": { texts: 24, chars: 698 },
  "bottleneck Top20 card": { texts: 13, chars: 560 },
  "bottleneck detail page 1": { texts: 8, chars: 203 },
  "bottleneck industry": { texts: 8, chars: 97 },
  "covered-call (3 tiers)": { texts: 20, chars: 636 },
  "options-guidance order": { texts: 12, chars: 339 },
  "options-guidance sizing": { texts: 7, chars: 172 },
  "educational-options": { texts: 7, chars: 411 },
  "options-product contract": { texts: 6, chars: 295 },
  "options-product unavailable": { texts: 5, chars: 184 },
  // V25 integration: the stock-lookup hint, the past-returns caveat and the 七欄Top20 / 選單 文字 pointers stay on the panel.
  "rich-menu navigation": { texts: 6, chars: 132 },
  "V21 three strategies": { texts: 18, chars: 590 },
  "options-guidance cycle comparison": { texts: 12, chars: 336 },
  "bottleneck detail (all pages)": { texts: 9, chars: 463 },
};
const V25_FLOORS: Record<string, { texts: number; chars: number; reason: string }> = {
  "bottleneck Top20 card": {
    texts: 13,
    chars: 560,
    reason: "The inherited 35% target is 474 characters. The measured 560-character floor keeps together six- and twelve-month order horizons and recognition dates; conditional price scenarios with P/S/share-count invariance; the RPO definition and non-guaranteed/non-target/non-advice/no-auto-order caveats; current-order and unreported-RPO status; the non-order proxy; six-month and short-history/two-year price basis; market cap; long-horizon normal-trading return and listing/spin-off history; and SEC/Yahoo source names and dates. Score composition is accessible in the detail route, not required as a card qualifier.",
  },
  "covered-call (3 tiers)": {
    texts: 20,
    chars: 636,
    reason: "The inherited 35% target is 591 characters. The 636-character floor preserves all three strikes/limits and Bid/Mid/Ask bands, contract premium and period/annualized yields, the source name/capture time and unavailable quote time, 100-share cover and assignment/upside-cap risk, the high-strike threshold and return formulas, each Delta with its source and assignment-probability-only qualifier, the full-liquidity text-route pointer, short-term annualization caveat, delayed/non-executable public-data status, non-advice/non-guaranteed/no-order wording, and underlying downside risk.",
  },
  "options-guidance order": {
    texts: 12,
    chars: 339,
    reason: "The inherited 35% target is 318 characters. The 339-character floor preserves LIMIT/Mid and Bid/Mid/Ask, underlying/strike/expiry/DTE, Delta target, annualized yield and its out-of-range warning, wide-spread status, avoid-market rule, annualization formula, and the non-broker/non-execution/non-advice/self-order/full-premium-loss boundary.",
  },
  "educational-options": {
    texts: 7,
    chars: 411,
    reason: "The inherited 35% target is 364 characters. The 411-character floor preserves the explicit non-recommendation label, synthetic status and as-of date, strategy and contract multiplier, assumed cost and full-share collateral, premium/cost assumptions, fees/slippage, early assignment and tax caveats, capped upside and substantial underlying downside, plus non-quote/non-advice/no-order disclosures.",
  },
  "options-product contract": {
    texts: 6,
    chars: 295,
    reason: "The fixed contract identity, all sealed bid/mark/ask, spread, delta, IV, open-interest and volume fields, timestamp, source/provenance, rights, assignment, liquidity, and execution/advice caveats cannot be removed or clipped.",
  },
  "options-product unavailable": {
    texts: 5,
    chars: 184,
    reason: "The caller-supplied reason must remain verbatim beside the unavailable/no-guess/no-stale-fallback status, unavailable-field and non-advice/no-order disclosures.",
  },
  "options-guidance cycle comparison": {
    texts: 12,
    chars: 336,
    reason: "The inherited 35% target is 318 characters. The 336-character floor keeps the weekly/monthly comparison parameters, quote bands, DTE and freshness basis, annualization formula, source context, and non-broker/non-execution/non-advice/no-order qualifiers together on the same bubble.",
  },
};

interface SurfaceSample {
  name: string;
  bubbles: Node[];
  bubbleCount: number;
  worstBubbleIndex: number;
  worstBubble: Node;
  metrics: {
    texts: number;
    chars: number;
    bullets: number;
    sections: number;
    xxs: number;
    footerButtons: number;
    distinctSizes: number;
    distinctWeights: number;
    longestPlainLine: number;
    disclosureLines: number;
  };
  v20Ceiling: { texts: number; chars: number } | null;
  target35: { chars: number; texts: number } | null;
}
const PROTECTED_SURFACES: Record<string, true> = { "top20-presentation": true };

function duplicateNumericFigures(bubble: Node): string[] {
  const figures = new Map<string, { token: string; count: number }>();
  const textOf = (value: unknown): string => {
    if (Array.isArray(value)) return value.map(textOf).join(" ");
    if (typeof value !== "object" || value === null) return "";
    const node = value as Node;
    if (node.type === "text") return typeof node.text === "string" ? node.text : "";
    return textOf(node.contents);
  };
  const visit = (value: unknown, context: readonly string[] = [], inFooter = false): void => {
    if (Array.isArray(value)) { value.forEach(child => visit(child, context, inFooter)); return; }
    if (typeof value !== "object" || value === null) return;
    const node = value as Node;
    if (node.type === "text") {
      if (inFooter && node.size === "xxs" && node.color === T.subtle) return;
      const text = typeof node.text === "string" ? node.text : "";
      const pattern = /(?:US)?\$\s?-?\d[\d,]*(?:\.\d+)?|[+-]?\d+(?:\.\d+)?(?:%|pp)/g;
      for (const match of text.matchAll(pattern)) {
        const field = (text.slice(0, match.index).split(/[｜\n]/).at(-1) ?? "").trim().replace(/\s+/g, " ");
        const key = `${context.join("/")}|${field}|${match[0]}`;
        const current = figures.get(key) ?? { token: match[0], count: 0 };
        current.count += 1;
        figures.set(key, current);
      }
      return;
    }
    if (node.type === "box" && node.layout === "horizontal" && node.contents?.length === 2) {
      const label = textOf(node.contents[0]).trim();
      visit(node.contents[0], context, inFooter);
      visit(node.contents[1], label ? [...context, label] : context, inFooter);
      return;
    }
    Object.entries(node).forEach(([key, child]) => { if (key !== "action") visit(child, context, inFooter || key === "footer"); });
  };
  visit(bubble);
  return [...figures.values()].filter(({ count }) => count > 1).map(({ token }) => token);
}
const D1_CAVEAT_TOKENS = ["非目標價", "非投資建議", "非今日起", "非保證", "不自動下單"] as const;

function visibleText(value: unknown): string {
  if (Array.isArray(value)) return value.map(visibleText).join(" ");
  if (typeof value !== "object" || value === null) return "";
  const node = value as Node;
  if (node.type === "text") return typeof node.text === "string" ? node.text : visibleText(node.contents);
  if (node.type === "button") return typeof (node as any).action?.label === "string" ? (node as any).action.label : "";
  return Object.entries(value as Record<string, unknown>)
    .filter(([key]) => key !== "action")
    .map(([, child]) => visibleText(child))
    .join(" ");
}

function repeatedD1Caveats(bubble: Node): string[] {
  const content = visibleText(bubble);
  return D1_CAVEAT_TOKENS.filter(token => {
    const first = content.indexOf(token);
    return first >= 0 && content.indexOf(token, first + token.length) >= 0;
  });
}

function top20DisclosureText(bubble: Node): string {
  const lines: string[] = [];
  const visit = (value: unknown): void => {
    if (Array.isArray(value)) { value.forEach(visit); return; }
    if (typeof value !== "object" || value === null) return;
    const node = value as Node;
    if (node.type === "text" && node.size === "xxs" && node.color === T.subtle) {
      lines.push(visibleText(node));
      return;
    }
    Object.values(value as Record<string, unknown>).forEach(visit);
  };
  visit((bubble as any).footer);
  return lines.join("");
}


function assertBodyRows(name: string, bubble: Node): void {
  const visit = (value: unknown): void => {
    if (Array.isArray(value)) { value.forEach(visit); return; }
    if (typeof value !== "object" || value === null) return;
    const node = value as Node;
    if (node.type === "box" && node.layout !== "horizontal" && Array.isArray(node.contents)) {
      const rows = node.contents.filter(child => child.type !== "separator");
      expect(rows.length, `${name} vertical row group`).toBeLessThanOrEqual(3);
    }
    node.contents?.forEach(visit);
  };
  visit(bubble.body);
}

function assertBubbleDesign(name: string, bubble: Node): void {
  const metrics = measure(bubble);
  expect(new TextEncoder().encode(JSON.stringify(bubble)).length, `${name} bubble bytes`).toBeLessThanOrEqual(46_000);
  if (PROTECTED_SURFACES[name]) return;
  assertBodyRows(name, bubble);
  expect(metrics.sections, `${name} framed sections`).toBeLessThanOrEqual(1);
  expect(metrics.bullets, `${name} bullets`).toBeLessThanOrEqual(3);
  expect(metrics.longestPlainLine, `${name} plain body line: ${metrics.longPlain.join(" / ")}`).toBeLessThanOrEqual(40);
  expect(metrics.distinctSizes, `${name} text sizes`).toBeLessThanOrEqual(4);
  expect(metrics.distinctWeights, `${name} text weights`).toBeLessThanOrEqual(2);
  expect(metrics.maxLinesUsed, `${name} maxLines`).toBe(0);
  expect(metrics.footerDisclosureLines, `${name} footer disclosureLine`).toBe(1);
  expect(metrics.buttons, `${name} buttons`).toBeLessThanOrEqual(2);
  expect(metrics.footerButtons, `${name} footer buttons`).toBeLessThanOrEqual(2);
  expect(duplicateNumericFigures(bubble), `${name} repeated figures`).toEqual([]);
  for (const label of metrics.labels) {
    expect(Array.from(label).length, label).toBeLessThanOrEqual(20);
    expect(label.trim(), label).not.toMatch(/^(?:詳情|更多|詳細|查看|Details|More|返回|選單|View|Back|Menu)$/i);
  }
}


async function collectSamples(): Promise<SurfaceSample[]> {
  const samples: SurfaceSample[] = [];
  for (const [name, build] of Object.entries(v25Surfaces)) {
    const bubbles = await build();
    expect(bubbles.length, `${name} must have a bubble`).toBeGreaterThan(0);
    const measurements = bubbles.map(measure);
    const worstBubbleIndex = measurements.reduce((worst, candidate, index) =>
      candidate.chars > measurements[worst]!.chars ? index : worst, 0);
    const metrics = measurements[worstBubbleIndex]!;
    const ceiling = V20_CEILINGS[name] ?? null;
    samples.push({
      name,
      bubbles,
      bubbleCount: bubbles.length,
      worstBubbleIndex,
      worstBubble: bubbles[worstBubbleIndex]!,
      metrics: {
        texts: metrics.texts,
        chars: metrics.chars,
        bullets: metrics.bullets,
        sections: metrics.sections,
        xxs: metrics.xxs,
        footerButtons: metrics.footerButtons,
        distinctSizes: metrics.distinctSizes,
        distinctWeights: metrics.distinctWeights,
        longestPlainLine: metrics.longestPlainLine,
        disclosureLines: metrics.disclosureLines,
      },
      v20Ceiling: ceiling,
      target35: ceiling ? { chars: Math.floor(ceiling.chars * 0.65), texts: Math.floor(ceiling.texts * 0.75) } : null,
    });
  }
  return samples;
}

function writeCapture(samples: SurfaceSample[], phase: "before" | "after"): void {
  const rawDirectory = process.env.V25_ARTIFACT_DIR;
  if (!rawDirectory || !isAbsolute(rawDirectory)) throw new Error("V25_ARTIFACT_DIR must be an absolute report path");
  const outputDirectory = resolve(rawDirectory);
  const allowedSuffix = ["scratchpad", "v25", "luna", "out"].join(sep);
  if (!outputDirectory.toLowerCase().endsWith(`${sep}${allowedSuffix}`.toLowerCase())) {
    throw new Error("V25_ARTIFACT_DIR must end in scratchpad/v25/luna/out");
  }
  const phaseDirectory = join(outputDirectory, `flex-${phase}`);
  mkdirSync(phaseDirectory, { recursive: true });
  for (const sample of samples) {
    const fileName = `${sample.name.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "")}.json`;
    writeFileSync(join(phaseDirectory, fileName), `${JSON.stringify(sample.worstBubble, null, 2)}\n`, "utf8");
  }
  const artifact = {
    source: phase === "before" ? "V20 builder outputs before V25 code changes" : "V25 builder outputs after UI changes",
    surfaces: samples.map(({ worstBubble, bubbles, ...sample }) => sample),
  };
  writeFileSync(join(outputDirectory, `${phase === "before" ? "BEFORE" : "AFTER"}.json`), `${JSON.stringify(artifact, null, 2)}\n`, "utf8");
}

describe("V25 Flex density baseline and budgets", () => {
  it("captures every worst bubble and meets the measured reductions", async () => {
    const samples = await collectSamples();
    const phase = process.env.V25_CAPTURE;
    if (phase === "before" || phase === "after") writeCapture(samples, phase);
    samples.forEach(sample => sample.bubbles.forEach(bubble => assertBubbleDesign(sample.name, bubble)));
    expect(samples.map(sample => sample.name)).toEqual(Object.keys(v25Surfaces));
    for (const sample of samples) {
      const afterCeiling = V25_AFTER_CEILINGS[sample.name];
      expect(afterCeiling, `${sample.name} V25 ceiling`).toBeDefined();
      expect(sample.metrics.chars, `${sample.name} new character ceiling`).toBeLessThanOrEqual(afterCeiling!.chars);
      expect(sample.metrics.texts, `${sample.name} new text-node ceiling`).toBeLessThanOrEqual(afterCeiling!.texts);
      if (PROTECTED_SURFACES[sample.name]) continue;
      const floor = V25_FLOORS[sample.name];
      if (floor) {
        expect(sample.metrics.chars, `${sample.name} documented floor`).toBe(floor.chars);
        expect(sample.metrics.texts, `${sample.name} documented floor text nodes`).toBe(floor.texts);
        continue;
      }
      expect(sample.target35, sample.name).not.toBeNull();
      expect(sample.metrics.chars, `${sample.name} characters`).toBeLessThanOrEqual(sample.target35!.chars);
      expect(sample.metrics.texts, `${sample.name} text count`).toBeLessThanOrEqual(sample.target35!.texts);
    }
  });
  it("keeps D1 caveats single-use per bubble and the Top20 disclosure within 260 code points", async () => {
    const samples = await collectSamples();
    for (const sample of samples) {
      sample.bubbles.forEach((bubble, index) =>
        expect(repeatedD1Caveats(bubble), `${sample.name} bubble ${index + 1}`).toEqual([]));
    }
    const top20 = samples.find(sample => sample.name === "bottleneck Top20 card")!;
    const disclosure = top20DisclosureText(top20.worstBubble);
    expect(disclosure).not.toBe("");
    const body = visibleText((top20.worstBubble as any).body);
    const footer = visibleText((top20.worstBubble as any).footer);
    expect(body).toContain("市值US$");
    // V25-D2 leaves score composition in the existing detail command when it cannot fit the card budget.
    expect(body).not.toContain("分數構成：");
    expect(footer).not.toContain("市值 ");
    expect(footer).not.toContain("角色 ");
    expect(footer).not.toContain("分數構成：");
    expect(Array.from(disclosure).length, "Top20 disclosure code points").toBeLessThanOrEqual(260);
  });


  it("limits visible recommendation verdicts by Unicode code points", () => {
    const exactLimit = verdictLine("🙂".repeat(24)) as Node;
    expect(Array.from(exactLimit.text ?? "").length).toBe(24);
    expect(verdictLine("🙂".repeat(25))).toBeUndefined();
    expect(verdictLine("   ")).toBeUndefined();
  });

  it("keeps every Flex message within V25 carousel and alt-text limits", async () => {
    const messages = await v25FlexMessages();
    expect(messages.length).toBeGreaterThan(0);
    for (const message of messages) {
      expect(Array.from(message.altText).length, message.altText).toBeLessThanOrEqual(120);
      const contents = message.contents;
      const carousel = contents && typeof contents === "object" && "contents" in contents ? contents.contents : undefined;
      expect(Array.isArray(carousel), message.altText).toBe(true);
      const bubbleCount = Array.isArray(carousel) ? carousel.length : 0;
      expect(bubbleCount, message.altText).toBeGreaterThanOrEqual(1);
      expect(bubbleCount, message.altText).toBeLessThanOrEqual(5);
      expect(new TextEncoder().encode(JSON.stringify(message.contents)).length, message.altText).toBeLessThanOrEqual(46_000);
    }
  });
});
