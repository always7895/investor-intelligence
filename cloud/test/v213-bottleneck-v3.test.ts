// Bottleneck-explosion Top20 v3 and the industry ranking: strict parsing, report-age bound, LINE rendering.
import { describe, expect, it } from "vitest";
import {
  buildBottleneckDetail, buildBottleneckTop20Messages, buildIndustryExplosionMessages, outlookTiles, parseBottleneckV3,
} from "../src/v213/bottleneck-v3";
import { doc, HOUR, OUTLOOKS } from "./bottleneck-v3-fixture";

describe("bottleneck-explosion Top20 v3", () => {
  it("parses a fresh document and refuses stale, malformed or mis-ranked ones", () => {
    const now = Date.now();
    expect(parseBottleneckV3(doc(now - HOUR))?.top).toHaveLength(20);
    expect(parseBottleneckV3(doc(now - 15 * HOUR))).toBeNull();
    const bad = doc(now - HOUR); (bad.top[4] as any).fundamentals.source_url = "http://insecure.example"; expect(parseBottleneckV3(bad)).toBeNull();
    const translated = doc(now - HOUR); (translated.top[3] as any).name_zh = "機翻名"; (translated.top[3] as any).name_zh_source = "MACHINE";
    expect(parseBottleneckV3(translated)).toBeNull();
    const shuffled = doc(now - HOUR); (shuffled.top[0] as any).rank = 2; expect(parseBottleneckV3(shuffled)).toBeNull();
    const insecure = doc(now - HOUR); (insecure.top[1] as any).outlook.orders.source_url = "http://x"; expect(parseBottleneckV3(insecure)).toBeNull();
    const invented = doc(now - HOUR); (invented.top[1] as any).outlook.scenarios.push({ kind: "MOON", change: 9 }); expect(parseBottleneckV3(invented)).toBeNull();
    const older = doc(now - HOUR); for (const entry of older.top as any[]) { delete entry.outlook; delete entry.role_zh; }
    expect(parseBottleneckV3(older)?.top).toHaveLength(20);  // documents sealed before outlooks still render
    expect(parseBottleneckV3(doc(now - HOUR, { schema: "other" }))).toBeNull();
  });

  it("renders LINE carousels within limits, a sourced detail and the industry ranking", () => {
    const parsed = parseBottleneckV3(doc(Date.now() - HOUR))!;
    const flex = buildBottleneckTop20Messages(parsed, "flex");
    expect(flex.length).toBeGreaterThanOrEqual(4);
    const serialized = JSON.stringify(flex);
    expect(serialized).toContain("SIVE.ST");
    expect(serialized).toContain("瓶頸詳情 SIVE.ST");
    expect(serialized).toContain("+109%");
    // Chinese name next to the original, or the explicit statement that none exists (never a translation).
    expect(serialized).toContain("S1｜合成一號");
    expect(serialized).toContain("中文名來源：中文維基百科");
    expect(serialized).toContain("SIVE.ST｜無公認中文名");
    // One long-term standard on every card: 6-month return and 2-year CAGR; younger listings say so.
    expect(serialized.match(/"2年年化"/g)).toHaveLength(20);
    expect(serialized).not.toContain("1年報酬");
    expect(serialized).toContain("上市未滿2年");
    expect(serialized).toContain("2025-02-13起年化 +64%");
    // Lead scores are not shown; signed-order floors from the sealed SEC report are.
    expect(serialized).not.toMatch(/Serenity|Leopold 基金|"線索"/);
    expect(serialized).not.toContain("訂單實現下限（已簽約 RPO）");  // horizon floors are on the detail card only
    // Operator 2026-09-26: current orders, the future estimate and the price scenario if realized, on every card.
    expect(serialized.match(/"訂單與成長情境"/g)).toHaveLength(20);
    // One layout on every card: the same three tiles in the same order.
    for (const label of ["現有訂單", "未來預估", "若實現股價"]) expect(serialized.match(new RegExp(`"${label}"`, "g"))).toHaveLength(20);
    expect(serialized).toContain("RPO 2026-07-26 年增+68%");
    expect(serialized).toContain("17.51兆 KRW");
    expect(serialized).toContain("在手 2026-06-30 年增+63%");
    expect(serialized).toContain("2026年接單指引");
    expect(serialized).toContain("公司未公布");
    expect(serialized).toContain("營收共識 58位");
    expect(serialized).toContain("目標價 +46%");
    expect(serialized).toContain("樣本不足");  // one analyst: no scenario on the card
    expect(serialized).not.toContain("+2860%");
    expect(serialized).toContain("1位分析師");
    expect(serialized).toContain("非預測、非投資建議");
    // Chinese first, the original kept; source labels in Chinese.
    expect(serialized).toContain("合成稀缺層角色");
    expect(serialized).not.toContain("原文：");  // the English original is on the detail card
    expect(serialized).toContain("財報：SEC EDGAR XBRL 財報資料");
    expect(serialized).toContain("股價：Yahoo Finance 還原收盤價（非官方）");
    expect(serialized).toContain("交易所收盤交叉比對：Nasdaq Nordic 斯德哥爾摩（延遲） 32.78 SEK（2026-09-25），與 Yahoo 差 +0.12%");
    expect(flex.length).toBeLessThanOrEqual(5);  // one LINE reply
    const text = buildBottleneckTop20Messages(parsed, "text") as { text: string }[];
    expect(text[0]!.text).toContain("為負者排除");
    expect(text[0]!.text).toContain("S1 合成一號（Synthetic 1）");
    const detail = buildBottleneckDetail(parsed, "sive.st") as { text: string }[];
    expect(detail[0]!.text).toContain("https://data.sec.gov/api/xbrl/companyfacts/");
    expect(detail[0]!.text).not.toMatch(/Serenity|Leopold/);
    expect(detail[0]!.text).toContain("瓶頸位置：合成稀缺層角色（原文：synthetic scarce layer role）");
    expect(detail[0]!.text).toContain("僅 1 位分析師，參考性低");
    expect(buildBottleneckDetail(parsed, "ZZZ")).toContain("不在本輪");
    // Operator 2026-09-26: every detail is a card with the full figures, orders, estimate, scenarios and sources;
    // an SEC filer's sealed company report follows it.
    const withReport = buildBottleneckDetail(parsed, "S1", "flex") as { type: string; altText: string }[];
    expect(withReport.length).toBeGreaterThanOrEqual(2);
    expect(withReport.length).toBeLessThanOrEqual(5);
    expect(withReport[0]!.altText).toBe("瓶頸詳情｜S1 合成一號");  // the detail card first, then the company report
    const s1 = JSON.stringify(withReport);
    expect(s1).toContain("Synthetic One");
    expect(s1).toContain("訂單實現下限（已簽約 RPO）");
    expect(s1).toContain("≥+33%");
    for (const label of ["財報數據", "前一季年增", "加速度", "股數年增", "市場數據", "訂單與成長情境", "EPS實現·本益比不變",
      "50 位", "預估來源：https://finance.yahoo.com/quote/S1/analysis", "訂單來源：SEC EDGAR XBRL 財報資料"]) expect(s1).toContain(label);
    expect(s1).toContain("目前訂單：剩餘履約義務（RPO，已簽約未認列） US$3.2B（2026-07-26，年增 +68%）");
    expect(s1).toContain("下一財年營收 +70.0%（58 位）");
    expect(s1).toContain("第二來源（Nasdaq.com 分析師預估）：平均目標價 250（+11%，33 位）；Jan 2028 EPS 13.5（+45.9%，15 位）");
    expect(s1).toContain("兩家來源目標價差距大（Yahoo +46%／Nasdaq +11%）");
    const korea = JSON.stringify(buildBottleneckDetail(parsed, "S4", "flex"));
    expect(korea).toContain("目前訂單：在手訂單（重工業部門（連結）） 17.51兆 KRW（2026-06-30，年增 +63%）");
    expect(korea).toContain("最新一季新接訂單 3.32兆 KRW（年增 +51%）");
    expect(korea).toContain("公司指引：2026 年新接訂單 12.00兆 KRW（原 8.40兆 KRW）");
    expect(JSON.stringify(buildBottleneckDetail(parsed, "S5", "flex"))).toContain("目前訂單：未揭露（SK海力士未揭露在手訂單）");
    const sive = buildBottleneckDetail(parsed, "SIVE.ST", "flex") as { contents: unknown }[];
    expect(sive).toHaveLength(1);  // no sealed report: the detail card only
    const sivePayload = JSON.stringify(sive);
    expect(sivePayload).toContain("+2860%");  // the detail shows the thin estimate, marked as such
    expect(sivePayload).toContain("僅 1 位分析師，參考性低");
    expect(sivePayload).toContain("原文：synthetic scarce layer role");
    expect(sivePayload).not.toMatch(/Serenity|Leopold/);
    expect(sivePayload).toContain("回瓶頸 TOP20");
    expect(sivePayload).toContain("市場若已反映部分成長，實際漲幅較小");  // the scenario states its basis
    const textWithReport = buildBottleneckDetail(parsed, "S1", "text") as { type: string; text: string }[];
    expect(textWithReport.length).toBeLessThanOrEqual(5);
    expect(textWithReport[0]!.text).toContain("若實現的股價情境：營收實現·市銷率不變 +70%");
    expect(textWithReport.every(message => message.type === "text" && message.text.length <= 4900)).toBe(true);
    const industries = JSON.stringify(buildIndustryExplosionMessages(parsed, "flex"));
    expect(industries).toContain("Leopold 邏輯");
    expect(industries).toContain("HBM 與 CoWoS 是近期限制。");
    expect(industries).toContain("原文：HBM and CoWoS are near-term constraints.");
    expect(industries).toContain("3.00x");
    expect(industries).not.toMatch(/Serenity 熱度|基金13F占比/);
  });

  it("renders optional numbers the validator lets through as missing, never as NaN or a crash", () => {
    const sparse = doc(Date.now() - HOUR);
    delete (sparse.industries[0] as any).news.ratio;
    delete (sparse.industries[1] as any).median_acceleration;
    delete (sparse.top[0] as any).market.cross_check.diff;
    const parsed = parseBottleneckV3(sparse)!;
    expect(parsed).not.toBeNull();
    const flex = JSON.stringify(buildIndustryExplosionMessages(parsed, "flex"));
    const text = JSON.stringify(buildIndustryExplosionMessages(parsed, "text"));
    const detail = JSON.stringify(buildBottleneckDetail(parsed, "SIVE.ST", "text"));
    for (const body of [flex, text, detail]) expect(body).not.toMatch(/NaN|undefined/);
    expect(flex).toContain("未取得");
    expect(text).toContain("SEC申報熱度 未取得｜");
    expect(text).toContain("SEC申報熱度 3.00x");
    expect(detail).toContain("幣別單位不同，不比較");
  });

  it("falls back to lean cards instead of a failed reply when twenty full cards exceed five carousels", () => {
    const heavy = doc(Date.now() - HOUR);
    for (const entry of heavy.top as any[]) {
      entry.role_source.url = `https://example.com/${"r".repeat(170)}`;
      entry.outlook = structuredClone(OUTLOOKS[1]);
      entry.name = "N".repeat(80);
      entry.role = "r".repeat(200);
      entry.role_zh = "角".repeat(200);
    }
    const parsed = parseBottleneckV3(heavy)!;
    const bubbles = buildBottleneckTop20Messages(parsed, "flex") as unknown as { contents: { contents: unknown[] } }[];
    expect(bubbles.length).toBeLessThanOrEqual(5);
    expect(bubbles.reduce((total, message) => total + message.contents.contents.length, 0)).toBe(20);
    const serialized = JSON.stringify(bubbles);
    expect(serialized.match(/"訂單與成長情境"/g)).toHaveLength(20);
    const s1 = parsed.top.find(entry => entry.symbol === "S1")!;
    expect(outlookTiles(parsed, s1)).toEqual([["現有訂單", "US$3.2B", "RPO 2026-07-26 年增+68%"], ["未來預估", "+70%", "營收共識 58位"],
      ["若實現股價", "+70%", "目標價 +46%／Nasdaq +11%"]]);  // full and lean cards are both built from these three items
  });
});
