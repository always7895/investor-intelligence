import { mkdirSync, writeFileSync } from "node:fs";
import { isAbsolute, join, resolve, sep } from "node:path";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { resetAdmissionToReal } from "./synthetic-option-admission";
import { measure, v25FlexMessages, v25Surfaces, v3D1Surfaces, type Node } from "./flex-density-fixtures";
import { LINE_THEME as T, disclosureGroups, verdictLine } from "../src/v213/line-theme";

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
  "V21 three strategies": { texts: 25, chars: 626 },
  "options-guidance cycle comparison": { texts: 23, chars: 490 },
  "bottleneck detail (all pages)": { texts: 23, chars: 963 },
};
const V25_AFTER_CEILINGS: Record<string, { texts: number; chars: number }> = {
  "top20-presentation": { texts: 24, chars: 698 },
  "bottleneck Top20 card": { texts: 16, chars: 600 },
  "bottleneck detail page 1": { texts: 10, chars: 409 },
  "bottleneck industry": { texts: 8, chars: 97 },
  "covered-call (3 tiers)": { texts: 22, chars: 606 },
  "options-guidance order": { texts: 12, chars: 339 },
  "options-guidance sizing": { texts: 7, chars: 172 },
  "educational-options": { texts: 9, chars: 344 },
  "options-product contract": { texts: 8, chars: 296 },
  "options-product unavailable": { texts: 5, chars: 184 },
  // V25 integration: the stock-lookup hint, the past-returns caveat and the 七欄Top20 / 選單 文字 pointers stay on the panel.
  "rich-menu navigation": { texts: 6, chars: 132 },
  "V21 three strategies": { texts: 21, chars: 656 },
  "options-guidance cycle comparison": { texts: 12, chars: 336 },
  "bottleneck detail (all pages)": { texts: 22, chars: 413 },
};
const V25_FLOORS: Record<string, { texts: number | null; chars: number | null; reason: string }> = {
  "bottleneck Top20 card": {
    texts: 16,
    chars: null,
    reason: "The 600-character same-card floor is removed because the dated sources, forecast bases and risks now live in the issuer-scoped final disclosure in the same reply; the text-node floor and unchanged ceilings still apply.",
  },
  "bottleneck detail page 1": {
    texts: 10,
    chars: null,
    reason: "The page-specific 409-character floor is removed because baseline data remains reachable on the full-data path; the page text floor and unchanged V20 ceiling still apply.",
  },
  "options-guidance order": {
    texts: 12,
    chars: 338,
    reason: "The inherited 35% target is 318 characters. The 338-character floor (the monthly window now reads 0-60, one character shorter than 21-45) preserves LIMIT/Mid and Bid/Mid/Ask, underlying/strike/expiry/DTE, Delta target, annualized yield and its out-of-range warning, wide-spread status, avoid-market rule, annualization formula, and the non-broker/non-execution/non-advice/self-order/full-premium-loss boundary.",
  },
  "educational-options": {
    texts: 9,
    chars: 344,
    reason: "FIX-R2C: the displayed synthetic status is now localized as 教學模擬 (17 fewer characters than the old machine code). The compact bubble retains the exact contract legs and assignment clause, unit/collateral, fees, the simulated date and all non-recommendation and non-execution qualifiers.",
  },
  "options-product contract": {
    texts: 8,
    chars: 296,
    reason: "The V25 pre-FIX3 capture was 6/295; target35 is 214 characters. The 8/296 bubble keeps timestamp/source, rights/provenance, assignment, liquidity and execution/advice caveats in three labelled groups. Splitting the former run-on disclosure adds two text nodes and one label character; no quote qualifier or provenance value is moved off the bubble.",
  },
  "options-product unavailable": {
    texts: 5,
    chars: 184,
    reason: "The caller-supplied reason must remain verbatim beside the unavailable/no-guess/no-stale-fallback status, unavailable-field and non-advice/no-order disclosures.",
  },
  "V21 three strategies": {
    texts: null,
    chars: null,
    reason: "The overview is compacted to meet the ten-row cap; complete strategy quotes and qualifications remain in the final same-reply disclosure and are asserted through the public caller. Upper ceilings remain unchanged.",
  },
  "options-guidance cycle comparison": {
    texts: 12,
    chars: 336,
    reason: "The inherited 35% target is 318 characters. The 336-character floor keeps the weekly/monthly comparison parameters, quote bands, DTE and freshness basis, annualization formula, source context, and non-broker/non-execution/non-advice/no-order qualifiers together on the same bubble.",
  },
  "bottleneck detail (all pages)": {
    texts: 22,
    chars: null,
    reason: "The 22-node maximum includes the appended research report, not the largest detail page. The old exact character count included a duplicate SEC form, filing date and recognition date; those remain together in the recognition disclosure. The unchanged 413-character ceiling still applies. Consumer tests assert same-card source, date, shares and scenario qualifiers.",
  },
};

interface SurfaceSample {
  name: string;
  bubbles: Node[];
  bubbleCount: number;
  worstBubbleIndex: number;
  worstBubble: Node;
  metricMaxBubbleIndices: Record<"texts" | "chars" | "bullets" | "sections" | "xxs" | "footerButtons" | "distinctSizes" | "distinctWeights" | "longestPlainLine" | "disclosureLines", number>;
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
      const matches = [
        ...Array.from(text.matchAll(pattern), match => ({ index: match.index ?? 0, token: match[0] })),
        ...Array.from(text.matchAll(/(?:\bLIMIT\s+|限價\s*)(-?\d+(?:\.\d+)?)(?=\s*(?:\(|（|\||$))/gi),
          match => ({ index: (match.index ?? 0) + match[0].lastIndexOf(match[1]!), token: match[1]! })),
      ];
      for (const { index, token } of matches) {
        const field = (text.slice(0, index).split(/[｜\n]/).at(-1) ?? "").trim().replace(/\s+/g, " ");
        const key = `${context.join("/")}|${field}|${token}`;
        const current = figures.get(key) ?? { token, count: 0 };
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
  // A rich-text line is the concatenation of its spans (disclosureGroups renders a bold label span plus a body span).
  if (node.type === "text") return typeof node.text === "string" ? node.text
    : (node.contents ?? []).map(span => typeof span.text === "string" ? span.text : "").join("");
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
const LABELLED_DISCLOSURE_SURFACES: Record<string, true> = {
  "bottleneck Top20 card": true,
  "bottleneck detail page 1": true,
  "bottleneck detail (all pages)": true,
  "covered-call (3 tiers)": true,
  "educational-options": true,
  "options-product contract": true,
  "V21 three strategies": true,
};
function disclosureLines(bubble: Node): { text: string; labelledBold: boolean }[] {
  const lines: { text: string; labelledBold: boolean }[] = [];
  const visit = (value: unknown): void => {
    if (Array.isArray(value)) { value.forEach(visit); return; }
    if (typeof value !== "object" || value === null) return;
    const node = value as Node;
    if (node.type === "text" && node.size === "xxs" && node.color === T.subtle) {
      const labelledBold = Array.isArray(node.contents) && node.contents.length >= 2
        && node.contents[0]?.weight === "bold";
      // V25-FIX3 counts each visible line separately; wrapped body notes are not one run-on disclosure.
      for (const text of visibleText(node).split(/\r?\n/)) lines.push({ text, labelledBold });
      return;
    }
    Object.values(value as Record<string, unknown>).forEach(visit);
  };
  visit(bubble);
  return lines;
}
function footerDisclosureLines(bubble: Node): { text: string; labelledBold: boolean }[] {
  return disclosureLines((bubble as any).footer);
}
function assertLabelledFooterDisclosures(name: string, bubble: Node): void {
  const lines = footerDisclosureLines(bubble);
  expect(lines.length, `${name} footer disclosures`).toBeGreaterThan(0);
  for (const line of lines) expect(line.labelledBold, `${name} bold disclosure label`).toBe(true);
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
  expect(metrics.footerDisclosureLines, `${name} footer disclosure groups`).toBeLessThanOrEqual(3);
  for (const line of disclosureLines(bubble)) {
    expect(Array.from(line.text).length, `${name} disclosure line`).toBeLessThanOrEqual(110);
  }
  expect(metrics.distinctSizes, `${name} text sizes`).toBeLessThanOrEqual(4);
  expect(metrics.distinctWeights, `${name} text weights`).toBeLessThanOrEqual(2);
  // The all-pages sample also appends an unchanged research-report bubble; its first four product pages are checked below.
  if (LABELLED_DISCLOSURE_SURFACES[name] && name !== "bottleneck detail (all pages)") assertLabelledFooterDisclosures(name, bubble);
  expect(metrics.maxLinesUsed, `${name} maxLines`).toBe(0);
  expect(metrics.footerDisclosureLines, `${name} footer disclosure groups`).toBeLessThanOrEqual(3);
  expect(metrics.longestPlainLine, `${name} body line`).toBeLessThanOrEqual(40);
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
    const maxIndex = (key: keyof SurfaceSample["metrics"]) =>
      measurements.reduce((worst, candidate, index) => candidate[key] > measurements[worst]![key] ? index : worst, 0);
    const maxValue = (key: keyof SurfaceSample["metrics"]) => measurements[maxIndex(key)]![key];
    const worstBubbleIndex = maxIndex("chars");
    const metrics = {
      texts: maxValue("texts"),
      chars: maxValue("chars"),
      bullets: maxValue("bullets"),
      sections: maxValue("sections"),
      xxs: maxValue("xxs"),
      footerButtons: maxValue("footerButtons"),
      distinctSizes: maxValue("distinctSizes"),
      distinctWeights: maxValue("distinctWeights"),
      longestPlainLine: maxValue("longestPlainLine"),
      disclosureLines: maxValue("disclosureLines"),
    };
    const metricMaxBubbleIndices = {
      texts: maxIndex("texts"),
      chars: maxIndex("chars"),
      bullets: maxIndex("bullets"),
      sections: maxIndex("sections"),
      xxs: maxIndex("xxs"),
      footerButtons: maxIndex("footerButtons"),
      distinctSizes: maxIndex("distinctSizes"),
      distinctWeights: maxIndex("distinctWeights"),
      longestPlainLine: maxIndex("longestPlainLine"),
      disclosureLines: maxIndex("disclosureLines"),
    };
    const ceiling = V20_CEILINGS[name] ?? null;
    samples.push({
      name,
      bubbles,
      bubbleCount: bubbles.length,
      worstBubbleIndex,
      worstBubble: bubbles[worstBubbleIndex]!,
      metricMaxBubbleIndices,
      metrics,
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
  // Captures are evidence, never repository content: refuse any directory inside this checkout.
  const repositoryRoot = resolve(__dirname, "..", "..").toLowerCase();
  if (outputDirectory.toLowerCase() === repositoryRoot || outputDirectory.toLowerCase().startsWith(`${repositoryRoot}${sep}`)) {
    throw new Error("V25_ARTIFACT_DIR must be outside the repository");
  }
  const phaseDirectory = join(outputDirectory, `flex-${phase}`);
  mkdirSync(phaseDirectory, { recursive: true });
  for (const sample of samples) {
    const fileName = `${sample.name.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "")}.json`;
    writeFileSync(join(phaseDirectory, fileName), `${JSON.stringify(sample.worstBubble, null, 2)}\n`, "utf8");
    const metricMaxIndices = [...new Set(Object.values(sample.metricMaxBubbleIndices))];
    for (const index of metricMaxIndices) {
      if (index === sample.worstBubbleIndex) continue;
      const metrics = Object.entries(sample.metricMaxBubbleIndices).filter(([, maxIndex]) => maxIndex === index)
        .map(([metric]) => metric).join("-");
      writeFileSync(join(phaseDirectory, `${fileName.slice(0, -5)}-max-${metrics}.json`),
        `${JSON.stringify(sample.bubbles[index]!, null, 2)}\n`, "utf8");
    }
  }
  const artifact = {
    source: phase === "before" ? "Pinned base 873be8c before Fix3" : "Fix3 builder outputs after remediation",
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
        if (floor.chars !== null) expect(sample.metrics.chars, `${sample.name} documented floor`).toBe(floor.chars);
        if (floor.texts !== null) expect(sample.metrics.texts, `${sample.name} documented floor text nodes`).toBe(floor.texts);
        continue;
      }
      expect(sample.target35, sample.name).not.toBeNull();
      expect(sample.metrics.chars, `${sample.name} characters`).toBeLessThanOrEqual(sample.target35!.chars);
      expect(sample.metrics.texts, `${sample.name} text count`).toBeLessThanOrEqual(sample.target35!.texts);
    }
  });
  it("detects duplicate bare LIMIT values", () => {
    const repeatedLimit = "LIMIT 2.25（Mid）";
    const bubble = { type: "box", contents: [
      { type: "text", text: repeatedLimit },
      { type: "text", text: repeatedLimit },
    ] };
    expect(duplicateNumericFigures(bubble as Node)).toEqual(["2.25"]);
  });
  it("keeps D1 caveats single-use per bubble and the Top20 disclosure within 260 code points", async () => {
    const samples = await collectSamples();
    for (const sample of samples) {
      sample.bubbles.forEach((bubble, index) =>
        expect(repeatedD1Caveats(bubble), `${sample.name} bubble ${index + 1}`).toEqual([]));
    }
    const top20 = samples.find(sample => sample.name === "bottleneck Top20 card")!;
    const disclosure = top20DisclosureText(top20.worstBubble);
    const detail = samples.find(sample => sample.name === "bottleneck detail (all pages)")!;
    expect(detail.bubbles.length).toBeGreaterThanOrEqual(4);
    detail.bubbles.slice(0, 4).forEach((bubble, index) =>
      assertLabelledFooterDisclosures(`bottleneck detail page ${index + 1}`, bubble));
    expect(disclosure).not.toBe("");
    const body = visibleText((top20.worstBubble as any).body);
    const footer = visibleText((top20.worstBubble as any).footer);
    expect(body).toMatch(/市值\s*US\$/);
    // V25-D2 leaves score composition in the existing detail command when it cannot fit the card budget.
    expect(body).not.toContain("分數構成：");
    expect(footer).not.toContain("市值 ");
    expect(footer).not.toContain("角色 ");
    expect(footer).not.toContain("分數構成：");
    for (const [name, bubbles] of Object.entries(v3D1Surfaces())) {
      expect(bubbles.length, `${name} must have a bubble`).toBeGreaterThan(0);
      bubbles.forEach((bubble, index) => {
        expect(repeatedD1Caveats(bubble), `${name} bubble ${index + 1}`).toEqual([]);
        for (const line of disclosureLines(bubble)) {
          expect(Array.from(line.text).length, `${name} disclosure line`).toBeLessThanOrEqual(110);
        }
        // V25-FIX3 includes actual V3 footer groups while excluding unrelated xxs header/body text.
        assertLabelledFooterDisclosures(name, bubble);
      });
    }
  });


  it("limits visible recommendation verdicts by Unicode code points", () => {
    const exactLimit = verdictLine("🙂".repeat(24)) as Node;
    expect(Array.from(exactLimit.text ?? "").length).toBe(24);
    expect(verdictLine("🙂".repeat(25))).toBeUndefined();
    expect(verdictLine("   ")).toBeUndefined();
  });

  it("never drops or throws on a long live disclosure; skips empty groups", () => {
    const long = "流動性：" + "價差偏寬".repeat(40);
    const nodes = disclosureGroups([{ label: "來源", text: "A\nB" }, { label: "風險", text: long }, { label: "基準", text: " " }]) as Node[];
    expect(nodes).toHaveLength(2);
    const spans = (node: Node) => (node.contents as Node[]).map(span => span.text ?? "");
    expect(spans(nodes[0]!)).toEqual(["來源｜", "A B"]);
    expect(spans(nodes[1]!).join("")).toBe(`風險｜${long}`);
    expect(() => disclosureGroups([1, 2, 3, 4].map(n => ({ label: `L${n}`, text: "x" })))).toThrow("LINE_DISCLOSURE_GROUP_LIMIT");
  });

  it("reads rich-text disclosure spans, so an overlong line or a repeated caveat is detected", () => {
    const groups = disclosureGroups([{ label: "風險", text: `${"x".repeat(200)}；非保證；非保證` }]) as Node[];
    const bubble = { type: "bubble", body: { type: "box", contents: [] }, footer: { type: "box", contents: groups } } as unknown as Node;
    const lines = footerDisclosureLines(bubble);
    expect(lines).toHaveLength(1);
    expect(lines[0]!.labelledBold).toBe(true);
    expect(Array.from(lines[0]!.text).length).toBeGreaterThan(110);
    expect(lines[0]!.text.startsWith("風險｜xxx")).toBe(true);
    expect(repeatedD1Caveats(bubble)).toEqual(["非保證"]);
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
