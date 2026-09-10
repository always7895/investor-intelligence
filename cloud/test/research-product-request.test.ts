import { describe, expect, it } from "vitest";
import { parseResearchProductRequest as parse, unavailableResearchProduct } from "../src/v213/research-product-request";
import { parseQuery } from "../src/core";
import { v213Top20LineAnswer } from "../src/v213/top20-presentation";
import { asKv, MemoryKv } from "./fake-kv";

describe("explicit research-product requests (all currently unavailable, not product acceptance)", () => {
  for (const [label, outputKind] of [["卡片摘要", "card_summary"], ["數據詳報", "data_report"], ["深入分析", "narrative_analysis"]] as const) {
    it.each([["股票 T00", "stock"], ["期權 T00", "options"], ["宏觀", "macro"]] as const)(`preserves %s domain and ${outputKind} rather than selecting a summary`, (prefix, domain) => {
      const request = parse(`${prefix} ${label}`)!;
      expect(request).toEqual({ domain, outputKind, ticker: domain === "macro" ? null : "T00", top20: false, period: null });
      expect(Object.isFrozen(request)).toBe(true);
      const message = unavailableResearchProduct(request);
      expect(message).toContain("RESEARCH_PRODUCT_NOT_SEALED"); expect(message).toContain(outputKind);
      expect(message.length).toBeLessThan(4900);
    });
    it(`does not guess a ticker/domain for standalone ${outputKind}`, () => {
      expect(parse(outputKind)).toEqual({ domain: null, outputKind, ticker: null, top20: false, period: null });
    });
  }

  it.each([
    ["Top20數據詳報", "data_report", "stock", null, true, null],
    ["Top 20:深入分析", "narrative_analysis", "stock", null, true, null],
    ["請提供 Ｔ００ 數據詳報", "data_report", "stock", "T00", false, null],
    ["data_report: T00", "data_report", "stock", "T00", false, null],
    ["股票 aapl 完整詳細資料報告", "data_report", "stock", "AAPL", false, null],
    ["$aapl narrative_analysis", "narrative_analysis", "stock", "AAPL", false, null],
    ["$2330.TW data_report", "data_report", "stock", "2330.TW", false, null],
    ["$CPI 數據詳報", "data_report", "stock", "CPI", false, null],
    ["T00 每週期權 數據詳報", "data_report", "options", "T00", false, "weekly"],
    ["每月期權 T00 完整文字分析", "narrative_analysis", "options", "T00", false, "monthly"],
    ["weekly options T00 data_report", "data_report", "options", "T00", false, "weekly"],
    ["T00 monthly options card_summary", "card_summary", "options", "T00", false, "monthly"],
    ["宏观 完整文字分析报告", "narrative_analysis", "macro", null, false, null],
  ] as const)("recognizes the bounded explicit command %s", (text, outputKind, domain, ticker, top20, period) => {
    expect(parse(text)).toEqual({ outputKind, domain, ticker, top20, period });
  });

  it.each([
    "Top20", "Top20 文字", "Top20 text", "Top20 證據詳情 T00", "分析 CPI 與 FOMC 對航運的影響",
    "深入分析 CPI 如何影響需求", "Serenity 的瓶頸與公司价值捕捉", "什麼是數據詳報", "如何閱讀完整文字分析",
    "explain data_report", "what is narrative_analysis", "我持有 T00 20股，成本100，請深入分析", "我的投資組合 data_report",
    "T00 每週期權", "比較 T00 與 T01", "最新報告", "刪除我的資料", "宏觀 景氣如何？",
    "CPI 數據詳報", "ABCDEFGH9 data_report", "股票 ABCDEFGH9 data_report", "AAPL..X data_report", "AAPL- data_report",
    "T00/X 數據詳報", "T00\u0000 數據詳報", "T00 ".repeat(100) + "數據詳報",
  ])("leaves ordinary/ambiguous/malformed text untouched: %s", text => {
    expect(parse(text)).toBeNull();
  });

  it("refuses explicit unavailable kinds before any public/private lookup or candidate fallback", async () => {
    const forbidden = { async get() { throw new Error("PRODUCT_FENCE_MUST_NOT_READ_DATA"); } } as unknown as KVNamespace;
    const env = { PUBLIC_CACHE: forbidden, TENANT_PRIVATE_CACHE: forbidden, EPHEMERAL_SECURITY_CACHE: asKv(new MemoryKv()) };
    for (const command of ["Top20 data_report", "T00 narrative_analysis", "macro card_summary"]) {
      const result = await v213Top20LineAnswer(env, parseQuery(command));
      expect(typeof result).toBe("string"); expect(result).toContain("RESEARCH_PRODUCT_NOT_SEALED");
    }
  });
});
