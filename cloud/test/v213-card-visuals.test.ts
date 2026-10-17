// Card body visuals (operator 2026-09-25: card bodies read as flat text). Synthetic values only.
import { describe, expect, it } from "vitest";
import { assertLineMessages } from "../src/line-messages";
import { richText } from "../src/v213/line-theme";
import { buildMacroDeepAnalysisFlex, buildMacroIndustryCardFlex, buildMacroTop5OverviewFlex } from "../src/v213/macro-industry-product";
import type { MacroDeepAnalysis, MacroIndustryCard } from "../src/v213/market-product-schema";
import { buildCompanyDataReportFlex, validateCompanyDataReport } from "../src/v213/deep-analysis";

const bytes = (value: unknown) => new TextEncoder().encode(JSON.stringify(value)).length;
const nodes = (value: unknown, type: string): any[] => !value || typeof value !== "object" ? []
  : Array.isArray(value) ? value.flatMap(item => nodes(item, type))
    : [...((value as any).type === type ? [value] : []), ...Object.values(value).flatMap(item => nodes(item, type))];

const card = (rank: number, filler = ""): MacroIndustryCard => ({
  rank, industry_id: `ind_${rank}`, industry_name: `合成產業 ${rank} (Synthetic industry ${rank})`,
  current_state: `成員營收年增 +26.1%（US$135.00B → US$170.22B，2026-06-30）${filler}`, outlook_12_36m: `價格年增 -3.2%${filler}`,
  growth: { rate_pct: 26.1, units: "% YoY", period: "2026 Q2", type: "actual", publisher: "SEC", date: "2026-06-30", source_id: "syn",
    url: "https://example.com/growth", raw_passage: "Synthetic passage of the growth figure" },
  demand_drivers: [`需求 +10.0%${filler}`], supply_constraint_chokepoint: `RPO 年增 +86.3%${filler}`, pricing: "PPI 年增 +45.0%",
  value_chain_position: "SIC 3571", beneficiaries_key_suppliers: ["Synthetic A", "Synthetic B"],
  catalysts: { m6: "下次檢查 2026-11-12", y1: "每季更新", y2: "無已公告事件" }, risks_lifecycle: "存貨年增超過營收 10 個百分點",
  opportunity_score: 90 - rank * 7, confidence: { data_completeness: 80, source_independence: 67, verification_status: "VERIFIED" },
});

describe("card body visuals", () => {
  it("highlights figures in running text; dates and plain words stay plain", () => {
    const node: any = richText("營收年增 +26.1%，價格 -3.2%，US$1.20B，毛利率 75.0%，2026-06-30");
    const figures = node.contents.filter((s: any) => s.weight === "bold").map((s: any) => [s.text, s.color]);
    expect(figures).toEqual([["+26.1%", "#111418"], ["-3.2%", "#B42318"], ["US$1.20B", "#111418"], ["75.0%", "#111418"]]);
    expect(node.contents.map((s: any) => s.text).join("")).toBe("營收年增 +26.1%，價格 -3.2%，US$1.20B，毛利率 75.0%，2026-06-30");
    expect(node.text).toBeUndefined();
    expect((richText("沒有任何數字") as any).contents).toBeUndefined();
  });

  it("TOP5 overview ranks with badges and score meters, cards with tiles and a catalyst timeline", () => {
    const messages = buildMacroTop5OverviewFlex({ title: "TOP5產業總覽", generated_at: "2026-09-25T12:00:00Z", horizon: "12-36M",
      qualified_count: 5, shortfall: 0, status: "ADMITTED_TOP5", industries: [1, 2, 3, 4, 5].map(rank => card(rank)) });
    assertLineMessages(messages);
    const overview = (messages[0] as any).contents.contents[0];
    const widths = nodes(overview.body, "box").map(box => box.width).filter((w: unknown) => typeof w === "string" && /%$/.test(w as string));
    expect(widths.slice(0, 5)).toEqual(["83%", "76%", "69%", "62%", "55%"]);
    expect(JSON.stringify(overview.body)).toContain("Synthetic industry 1");
    expect(JSON.stringify(overview.body)).toContain("機會分數構成");
    const first = (messages[0] as any).contents.contents[1];
    const texts = nodes(first.body, "text").map(t => t.text);
    expect(texts).toEqual(expect.arrayContaining(["市場成長率", "+26.1%", "資料完整度", "80%", "6M", "1Y", "2Y"]));
  });

  it("oversized content drops highlighting to stay inside LINE limits, and carousels are packed by size", () => {
    const long = "，".concat("長".repeat(1300));
    const flex = buildMacroIndustryCardFlex(card(1, long));
    assertLineMessages(flex);
    expect(nodes(flex, "span")).toHaveLength(0);
    const messages = buildMacroTop5OverviewFlex({ title: "TOP5產業總覽", generated_at: "2026-09-25T12:00:00Z", horizon: "12-36M",
      qualified_count: 5, shortfall: 0, status: "ADMITTED_TOP5", industries: [1, 2, 3, 4, 5].map(rank => card(rank, "，".concat("長".repeat(500)))) });
    assertLineMessages(messages);
    expect(messages.length).toBeGreaterThan(2);
    expect(messages.every(m => bytes((m as any).contents) <= 46_000)).toBe(true);
    expect((messages[0] as any).contents.contents[0].header.contents[1].text).toBe("TOP5產業總覽");
  });

  it("deep analysis unfolds as a ten-step timeline with the bottleneck step filled", () => {
    const deep: MacroDeepAnalysis = { industry_id: "syn", industry_name: "合成產業 (Synthetic)", demand: "需求 +26.1%", supply: "存貨 +103.8%",
      bottleneck: "RPO +86.3%", pricing: "PPI +45.0%", capex: "未量測", competition: "前五大 96.0%", beneficiaries: ["A", "B"],
      catalysts: { m6: "2026-11-12", y1: "每季", y2: "無" }, risks: ["PPI 轉負"], killers: ["RPO 年增 -10% 以下"],
      source_references: [{ source: "SEC XBRL", url: "https://data.sec.gov/api/xbrl/frames/us-gaap/Revenues/USD/CY2026Q2.json" }] };
    const flex = buildMacroDeepAnalysisFlex(deep);
    assertLineMessages(flex);
    const markers = nodes((flex[0] as any).contents.contents[0].body, "text").map(t => t.text).filter((t: string) => /^\d+$/.test(t));
    expect(markers).toEqual(["1", "2", "3", "4", "5", "6", "7", "8", "9", "10"]);
    expect(JSON.stringify(flex)).toContain("邏輯證偽點 (Thesis Killers)");
  });

  it("company report renders a phase ladder, validated KPI tiles, numbered sections and sources", () => {
    const raw = { ticker: "SYN", name: "Synthetic Devices Inc.", as_of: "2026-09-25", boundary: "官方資料的計算與整理；不是投資建議、價格預測或機率",
      phase: { phase: "COMMERCIAL_VALIDATION", next_review_at: "2026-11-12" },
      sections: ["公司業務", "營運動能", "訂單能見度", "產能與資本支出", "證偽條件"].map(title => ({ title, text: `${title} 年增 +25.0%` })),
      source_references: [{ source: "SEC XBRL company facts", url: "https://data.sec.gov/api/xbrl/companyfacts/CIK0000000001.json", period: "CY2026Q2" }],
      kpis: [{ label: "營收年增", value: 25, unit: "%", signed: true, period: "CY2026Q2" }, { label: "毛利率", value: 61.5, unit: "%", signed: false },
        { label: "RPO 年增", value: null, unit: "%", signed: true }] };
    const data = validateCompanyDataReport(raw, "SYN")!;
    expect(data.kpis).toHaveLength(3);
    for (const bad of [[{ label: "x", value: "1", unit: "%", signed: true }], [{ label: "x", value: 1, unit: "USD", signed: true }],
      [{ label: "很長的標籤超過十二個字元的限制", value: 1, unit: "%", signed: true }]]) {
      expect(validateCompanyDataReport({ ...raw, kpis: bad }, "SYN")).toBeNull();
    }
    expect(validateCompanyDataReport({ ...raw, kpis: undefined }, "SYN")!.kpis).toEqual([]);
    const flex = buildCompanyDataReportFlex(data, "2026-09-25T12:00:00Z", ["回潛力榜", "潛力榜"]);
    assertLineMessages(flex);
    const bubbles = (flex[0] as any).contents.contents;
    expect(bubbles).toHaveLength(4);
    const overviewTexts = nodes(bubbles[0], "text").map(t => t.text);
    expect(overviewTexts).toEqual(expect.arrayContaining(["SYN", "+25.0%", "61.5%", "未申報", "商業驗證（公司開始獲利）"]));
    expect(nodes(bubbles[0], "text").find(t => t.text === "商業")?.weight).toBe("bold");
    expect(nodes(bubbles[1], "text").map(t => t.text)).toEqual(expect.arrayContaining(["一", "公司業務", "四", "產能與資本支出"]));
    expect(JSON.stringify(bubbles[2])).toContain("#FEF3F2"); // falsifiers sit on the pale warning panel
    expect(JSON.stringify(bubbles[3])).toContain("https://data.sec.gov/api/xbrl/companyfacts/CIK0000000001.json");
    expect(JSON.stringify(bubbles[3].footer)).toContain("潛力榜");
  });
});
