// V20 (LINE Flex UI/UX polish): density budgets over the main flex builders with realistic-length fixtures.
// The design budgets (docs/LINE_TOP20_UI.md) are asserted where the data allows them; every surface also has a measured ceiling
// so a regression to the pre-V20 wall of text fails. Figures and disclosures are asserted elsewhere (per-surface suites);
// this file only measures structure. Synthetic data only.
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { LineOutboundMessage } from "../src/line-messages";
import { parseQuery } from "../src/core";
import { buildV213Top20Messages } from "../src/v213/top20-presentation";
import { parseV213Top20Report } from "../src/v213/top20-report";
import { buildBottleneckDetail, parseBottleneckV3 } from "../src/v213/bottleneck-v3";
import { buildCoveredCallMessages, validateCoveredCallCycle } from "../src/v213/covered-call";
import { buildEducationalStrategyFlex } from "../src/v213/educational-options";
import { optionsUnavailableReport } from "../src/v213/options-product";
import { v213PublicLineAnswer } from "../src/v213/rich-menu";
import { BUTTON_LABEL_MAX, bulletList, bulletRow, clampText, detailsButton, altSummary, disclosureLine, kvRow } from "../src/v213/line-theme";
import { doc as bottleneckDoc } from "./bottleneck-v3-fixture";
import { admitSyntheticTickers, resetAdmissionToReal } from "./synthetic-option-admission";
import { bubblesOf, coveredCycle, isBulletRow, measure, REPORT, top20Report, v20Surfaces, worst, type Node } from "./flex-density-fixtures";

vi.mock("../src/v213/public-options-admission", async importOriginal => {
  const real = await importOriginal<typeof import("../src/v213/public-options-admission")>();
  return { ...real, admitPublicOption: vi.fn(real.admitPublicOption) };
});
beforeEach(() => { resetAdmissionToReal(); });


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
// V25 tightens supported surfaces to measured post-redesign ceilings. The legacy seven-field Top20 cap stays unchanged;
// the V21 strategy card and extended bottleneck details are governed by the separate V25 budget.
const CEILING: Record<string, { texts: number; chars: number; bullets: number; sections: number; footerButtons: number }> = {
  "top20-presentation": { texts: 24, chars: 710, bullets: 0, sections: 0, footerButtons: 1 },
  "bottleneck Top20 card": { texts: 13, chars: 560, bullets: 0, sections: 0, footerButtons: 2 },
  "bottleneck detail page 1": { texts: 8, chars: 203, bullets: 0, sections: 0, footerButtons: 2 },
  "bottleneck industry": { texts: 8, chars: 97, bullets: 0, sections: 0, footerButtons: 2 },
  "covered-call (3 tiers)": { texts: 20, chars: 636, bullets: 0, sections: 1, footerButtons: 2 },
  "options-guidance order": { texts: 12, chars: 339, bullets: 0, sections: 0, footerButtons: 1 },
  "options-guidance sizing": { texts: 7, chars: 172, bullets: 0, sections: 0, footerButtons: 1 },
  "educational-options": { texts: 7, chars: 411, bullets: 0, sections: 0, footerButtons: 2 },
  "options-product contract": { texts: 6, chars: 295, bullets: 0, sections: 0, footerButtons: 2 },
  "options-product unavailable": { texts: 5, chars: 184, bullets: 0, sections: 0, footerButtons: 2 },
  "rich-menu navigation": { texts: 6, chars: 132, bullets: 3, sections: 0, footerButtons: 2 },
};

describe("V20 density budgets (realistic fixtures)", () => {
  const surfaces = v20Surfaces;

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

  it("figure-bearing pages never use maxLines on a card that carries figures or disclosures", async () => {
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
    expect(row.contents![1]).toMatchObject({ type: "text", wrap: true, flex: 1 });
    expect(row.contents![1]!.maxLines).toBeUndefined();
    expect((bulletRow("說明", { maxLines: 2 }) as Node).contents![1]!.maxLines).toBe(2);
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
    const label = (detailsButton("查看 NVDA 完整數據與來源網址與更多說明", "x") as Node).action!.label as string;
    expect(Array.from(label).length).toBeLessThanOrEqual(BUTTON_LABEL_MAX);
  });

  it("clampText is code-point safe; disclosureLine joins with a fullwidth bar; altSummary stays within 120", () => {
    expect(clampText("𠮷𠮷𠮷𠮷", 3)).toBe("𠮷𠮷…");
    expect(clampText("短", 3)).toBe("短");
    expect((disclosureLine(["來源：A", "", "非投資建議"]) as Node).text).toBe("來源：A｜非投資建議");
    expect(Array.from(altSummary({ topic: "題".repeat(100), status: "狀態".repeat(30), next: "下一步" })).length).toBeLessThanOrEqual(120);
  });
});
