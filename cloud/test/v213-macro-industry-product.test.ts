import { describe, expect, it } from "vitest";
import { assertLineMessages } from "../src/line-messages";
import {
  buildMacroDeepAnalysisFlex,
  buildMacroDeepAnalysisText,
  buildMacroIndustryCardFlex,
  buildMacroIndustryCardText,
  buildMacroTop5OverviewFlex,
  buildMacroTop5OverviewText,
  macroShortfallReport,
} from "../src/v213/macro-industry-product";
import type {
  MacroDeepAnalysis,
  MacroIndustryCard,
  MacroTop5Overview,
} from "../src/v213/market-product-schema";
import { validateMacroGrowthRate } from "../src/v213/market-product-schema";

function mockCard(rank: number, id: string, withGrowth = true): MacroIndustryCard {
  return {
    rank,
    industry_id: id,
    industry_name: `產業 ${id}`,
    current_state: `現況說明 ${id}`,
    outlook_12_36m: `展望說明 ${id}`,
    growth: withGrowth ? {
      rate_pct: 25.5,
      units: "% YoY",
      period: "2026",
      type: "forecast",
      publisher: "WSTS / SEMI",
      date: "2026-06",
      source_id: "wsts-outlook",
      url: "https://example.com/growth",
      raw_passage: "Market expected to grow 25.5% YoY in 2026",
    } : null,
    demand_drivers: ["算力擴張", "基礎設施升級"],
    supply_constraint_chokepoint: "關鍵零件交期與產能受限",
    pricing: "具備長約定價溢價能力",
    value_chain_position: "上游核心材料與模組封裝",
    beneficiaries_key_suppliers: ["供應商A", "供應商B"],
    catalysts: {
      m6: "6個月催化：樣品認證",
      y1: "1年催化：產線放量",
      y2: "2年催化：商業規模普及",
    },
    risks_lifecycle: "處於成長高速期，主要風險為同業資本過度支出。",
    opportunity_score: 88,
    confidence: {
      data_completeness: 90,
      source_independence: 85,
      verification_status: "VERIFIED_PUBLIC_PROSE",
    },
  };
}

function mockOverview(count = 5): MacroTop5Overview {
  const industries = Array.from({ length: count }, (_, i) => mockCard(i + 1, `ind_${i + 1}`));
  const shortfall = Math.max(0, 5 - count);
  return {
    title: "TOP5產業總覽",
    generated_at: "2026-09-14T12:00:00Z",
    horizon: "12-36M",
    qualified_count: count,
    shortfall,
    status: shortfall === 0 ? "ADMITTED_TOP5" : "SHORTFALL_NOT_QUALIFIED",
    shortfall_report: shortfall > 0 ? `短缺通報：合格候選僅 ${count} 個` : undefined,
    industries,
  };
}

const mockDeep: MacroDeepAnalysis = {
  industry_id: "hbm_packaging",
  industry_name: "先進封裝與高頻寬記憶體",
  demand: "AI 加速器對高頻寬與低延遲記憶體需求持續翻倍",
  supply: "TSV 矽穿孔產能與 CoWoS 機台供給緊繃",
  bottleneck: "高精度對位機台與熱壓合鍵合設備交期長達 18 個月",
  pricing: "記憶體原廠具備年度議價強勢地位",
  capex: "主要晶圓廠與封測廠年度資本支出維持雙位數增長",
  competition: "技術壁壘極高，由少數兩至三家大廠主導",
  beneficiaries: ["TSMC", "SK Hynix", "Micron", "Advantest"],
  catalysts: {
    m6: "HBM3e 12-Hi 通過主要客戶認證",
    y1: "HBM4 混合鍵合樣品出貨",
    y2: "晶圓級 3D 整合進入雲端資料中心",
  },
  risks: ["雲端業者自研晶片架構轉向", "整體景氣衰退導致資本支出下修"],
  killers: ["低成本封裝技術完全替代 3D 鍵合", "新記憶體架構繞過 HBM 需求"],
  source_references: [
    { source: "WSTS Spring 2026", url: "https://www.wsts.org/76/Recent-News-Release", passage: "Memory segment forecast to surge 250%" },
  ],
};

describe("Macro Industry Product presentation and schemas", () => {
  it("builds valid Flex overview respecting carousel limit <= 5 per message (total 2 messages)", () => {
    const overview = mockOverview(5);
    const messages = buildMacroTop5OverviewFlex(overview);
    assertLineMessages(messages);
    expect(messages).toHaveLength(2);
    const carousel1 = (messages[0] as any).contents;
    expect(carousel1.type).toBe("carousel");
    expect(carousel1.contents.length).toBeLessThanOrEqual(5);
    const carousel2 = (messages[1] as any).contents;
    expect(carousel2.type).toBe("carousel");
    expect(carousel2.contents.length).toBeLessThanOrEqual(5);
    const bodyStr = JSON.stringify(messages);
    expect(bodyStr).toContain("TOP5產業總覽");
    expect(bodyStr).toContain("正式准入 TOP5");
    expect(bodyStr).toContain("宏觀產業 卡片 ind_1");
  });

  it("builds valid Text overview retaining complete data and actions", () => {
    const overview = mockOverview(5);
    const messages = buildMacroTop5OverviewText(overview);
    assertLineMessages(messages);
    expect(messages.every(m => m.type === "text")).toBe(true);
    const textStr = JSON.stringify(messages);
    expect(textStr).toContain("TOP5產業總覽");
    expect(textStr).toContain("第 1 名：產業 ind_1");
    expect(textStr).toContain("第 5 名：產業 ind_5");
    expect(textStr).toContain("快捷指令：");
  });

  it("reports shortfall deterministically when <5 industries qualify", () => {
    const overview = mockOverview(2);
    const flexMessages = buildMacroTop5OverviewFlex(overview);
    assertLineMessages(flexMessages);
    const flexStr = JSON.stringify(flexMessages);
    expect(flexStr).toContain("短缺通報");
    expect(flexStr).toContain("未達准入門檻");

    const textMessages = buildMacroTop5OverviewText(overview);
    assertLineMessages(textMessages);
    const textStr = JSON.stringify(textMessages);
    expect(textStr).toContain("短缺通報");
    expect(textStr).toContain("合格候選數：2/5");

    const standaloneShortfall = macroShortfallReport(2);
    assertLineMessages(standaloneShortfall);
    expect(JSON.stringify(standaloneShortfall)).toContain("MACRO_TOP5_SHORTFALL");
  });

  it("renders independent industry card in Flex and text with missing growth handling", () => {
    const cardWithGrowth = mockCard(1, "hbm", true);
    const flex1 = buildMacroIndustryCardFlex(cardWithGrowth);
    assertLineMessages(flex1);
    expect(JSON.stringify(flex1)).toContain("+25.5% YoY");
    expect(JSON.stringify(flex1)).toContain("WSTS / SEMI");

    const cardNoGrowth = mockCard(2, "robotics", false);
    const flex2 = buildMacroIndustryCardFlex(cardNoGrowth);
    assertLineMessages(flex2);
    expect(JSON.stringify(flex2)).toContain("UNAVAILABLE（無已驗收來源之獨立市場成長率）");

    const text2 = buildMacroIndustryCardText(cardNoGrowth);
    assertLineMessages(text2);
    expect(JSON.stringify(text2)).toContain("UNAVAILABLE（無已驗收來源之獨立市場成長率）");
    expect(JSON.stringify(text2)).toContain("System Operationalization 量化評分，非機率");
  });

  it("strictly rejects company count percentage as market growth", () => {
    expect(() => {
      validateMacroGrowthRate({
        rate_pct: 50.0,
        units: "% of companies",
        period: "2026",
        type: "forecast",
        publisher: "Test",
        date: "2026-06",
        source_id: "wsts-outlook",
        url: "https://example.com",
      });
    }).toThrow("COMPANY_COUNT_PERCENTAGE_CANNOT_BE_MARKET_GROWTH");

    expect(() => {
      validateMacroGrowthRate({
        rate_pct: 50.0,
        units: "%",
        period: "2026",
        type: "forecast",
        publisher: "Test",
        date: "2026-06",
        source_id: "wsts-outlook",
        raw_passage: "候選家數占比為 50%",
      });
    }).toThrow("COMPANY_COUNT_PERCENTAGE_CANNOT_BE_MARKET_GROWTH");
  });

  it("rejects invalid date and period formats in growth rate", () => {
    expect(() => {
      validateMacroGrowthRate({
        rate_pct: 20.0,
        units: "% YoY",
        period: "invalid-period",
        type: "forecast",
        publisher: "Test",
        date: "2026-06",
        source_id: "wsts-outlook",
        url: "https://example.com",
      });
    }).toThrow("INVALID_GROWTH_PERIOD");

    expect(() => {
      validateMacroGrowthRate({
        rate_pct: 20.0,
        units: "% YoY",
        period: "2026",
        type: "forecast",
        publisher: "Test",
        date: "invalid-date",
        source_id: "wsts-outlook",
        url: "https://example.com",
      });
    }).toThrow("INVALID_GROWTH_DATE");
  });

  it("requires source URL or raw passage binding in growth rate", () => {
    expect(() => {
      validateMacroGrowthRate({
        rate_pct: 20.0,
        units: "% YoY",
        period: "2026",
        type: "forecast",
        publisher: "Test",
        date: "2026-06",
        source_id: "wsts-outlook",
      });
    }).toThrow("SOURCE_BINDING_REQUIRED");
  });

  it("requires source_id lineage binding in growth rate", () => {
    expect(() => {
      validateMacroGrowthRate({
        rate_pct: 20.0,
        units: "% YoY",
        period: "2026",
        type: "forecast",
        publisher: "Test",
        date: "2026-06",
        url: "https://example.com",
      });
    }).toThrow("UNADMITTED_GROWTH_SOURCE");
  });

  it("renders 10-dimension deep route with catalysts and thesis killers", () => {
    const flex = buildMacroDeepAnalysisFlex(mockDeep);
    assertLineMessages(flex);
    const flexStr = JSON.stringify(flex);
    expect(flexStr).toContain("10維因果鏈展開");
    expect(flexStr).toContain("需求傳導");
    expect(flexStr).toContain("核心瓶頸");
    expect(flexStr).toContain("邏輯證偽點 (Thesis Killers)");
    expect(flexStr).toContain("WSTS Spring 2026");

    const text = buildMacroDeepAnalysisText(mockDeep);
    assertLineMessages(text);
    const textStr = JSON.stringify(text);
    expect(textStr).toContain("1. 需求傳導");
    expect(textStr).toContain("10. 證偽指標");
    expect(textStr).toContain("⚠️ 低成本封裝技術完全替代 3D 鍵合");
  });
});
