// Bottleneck-explosion Top20 v3 and the industry ranking: strict parsing, report-age bound, LINE rendering.
import { describe, expect, it } from "vitest";
import {
  buildBottleneckDetail, buildBottleneckTop20Messages, buildIndustryExplosionMessages, outlookForecast, outlookTiles, parseBottleneckV3,
} from "../src/v213/bottleneck-v3";
import { doc, forecastCase, HOUR, OUTLOOKS } from "./bottleneck-v3-fixture";
import lineageContract from "../../tests/fixtures/v213-lineage-sealed-markets.json";
import urlTable from "../../tests/fixtures/v213-order-forecast-urls.json";
import officialRevenueFixture from "../../tests/fixtures/v213-official-quarterly-revenue.json";

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
    // The fixed report clock: the sealed order forecasts (tests/fixtures/v213-order-forecast-sealed.json) date from 2026-09.
    const parsed = parseBottleneckV3(doc(REPORT), REPORT + HOUR)!;
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
    // Operator 2026-09-27: a spin-off is not a new company; its figure starts at the first regular-way session, never at
    // when-issued trading, and says it is not a 2-year figure; the verified event shows even when two years exist.
    expect(serialized).not.toContain("上市未滿2年");
    expect(serialized).not.toContain("2025-02-13起年化");
    expect(serialized).toContain("獨立交易價格未滿2年");
    expect(serialized).toContain("2025-02-24–2026-09-25 正常交易以來年化 +64%（非2年）");
    expect(serialized).toContain("上市沿革：2025-02-21 自 Synthetic Parent（SPAR）分拆；2025-02-24 起正常交易");
    expect(serialized).toContain("上市沿革：2024-03-19 IPO；2024-03-20 起交易");
    // An unverified since-listing figure from an older document is never shown; the card says the data are insufficient.
    expect(serialized).toContain("2年價格資料不足");
    expect(serialized).toContain("可得價格自 2025-01-06；上市沿革未核實");
    expect(serialized).not.toContain("+777%");
    // Lead scores are not shown; signed-order floors from the sealed SEC report are.
    expect(serialized).not.toMatch(/Serenity|Leopold 基金|"線索"/);
    expect(serialized).not.toContain("已簽約訂單可支撐的營收成長");  // revenue coverage are on the detail card only
    // Operator 2026-09-26: current orders, the future estimate and the price scenario if realized, on every card.
    expect(serialized.match(/"訂單與成長情境"/g)).toHaveLength(20);
    // One layout on every card (Astra ORDERS-V2-01): the current-orders tile, both realization rows and both price rows.
    for (const label of ["現有訂單", "未來訂單預估", "訂單實現後股價情境"]) expect(serialized.match(new RegExp(`"${label}"`, "g"))).toHaveLength(20);
    for (const row of ["半年內預計認列：", "1年內預計認列：", "若半年內實現訂單 → ", "若1年內實現訂單 → "]) expect(serialized.match(new RegExp(`"${row}`, "g"))).toHaveLength(20);
    expect(serialized).toContain("RPO 2026-07-26 年增+68%");
    expect(serialized).toContain("17.51兆 KRW");
    expect(serialized).toContain("在手 2026-06-30 年增+63%");
    expect(serialized).toContain("半年內預計認列：US$12.0B（起算日 2026-06-30（非今日起），至 2026-12-30）");  // S2: the filing's own 6-month schedule
    expect(serialized).toContain("半年後訂單餘額外推：25.13兆 KRW（至 2027-03-27）");  // S8: a book extrapolation is a labelled sensitivity
    expect(serialized).toContain("模型推估，非公司揭露、非期間認列");
    expect(serialized).toContain("公司未公布");
    expect(serialized).not.toContain("分析師12個月平均目標價");  // analyst targets never fill an order tile
    expect(serialized).not.toContain("1年 +46%");  // the analyst target (+46%) never appears as the order-linked price
    expect(serialized).not.toContain("+2860%");
    expect(serialized).not.toContain("目標價樣本不足");
    expect(serialized).toContain("非目標價、非投資建議");
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
    expect(s1).toContain("已簽約訂單可支撐的營收成長（RPO 認列時程）");
    expect(s1).toContain("僅指營收，不是股價下限");
    expect(s1).not.toContain("訂單實現下限");
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
    expect(textWithReport[0]!.text).toContain("分析師共識情境（非訂單）：營收實現·市銷率不變 +70%");  // the analyst scenario is labelled as such
    expect(textWithReport.every(message => message.type === "text" && message.text.length <= 4900)).toBe(true);
    const industries = JSON.stringify(buildIndustryExplosionMessages(parsed, "flex"));
    expect(industries).toContain("Leopold 邏輯");
    expect(industries).toContain("HBM 與 CoWoS 是近期限制。");
    expect(industries).toContain("原文：HBM and CoWoS are near-term constraints.");
    expect(industries).toContain("3.00x");
    expect(industries).not.toMatch(/Serenity 熱度|基金13F占比/);
  });

  it("shows the verified listing event and its sources in every form and closes malformed lineage metadata", () => {
    const parsed = parseBottleneckV3(doc(Date.now() - HOUR))!;
    const text = JSON.stringify(buildBottleneckTop20Messages(parsed, "text"));
    expect(text).toContain("2年年化 獨立交易價格未滿2年（2025-02-24–2026-09-25 正常交易以來年化 +64%（非2年））；2025-02-21 自 Synthetic Parent（SPAR）分拆");
    expect(text).toContain("2年年化 2年價格資料不足（可得價格自 2025-01-06；上市沿革未核實）");
    expect(text).toContain("沿革未核實且價格不足2年者不列入");
    expect(text).not.toContain("上市以來年化");
    for (const style of ["flex", "text"] as const) {
      const detail = JSON.stringify(buildBottleneckDetail(parsed, "S2", style));
      expect(detail, style).toContain("上市沿革：2025-02-21 自 Synthetic Parent（SPAR）分拆；2025-02-24 起正常交易");
      expect(detail, style).toContain("2025-02-24 https://www.sec.gov/Archives/edgar/data/1/000000000000000001/synthetic8k.htm");
      expect(detail, style).toContain("正常交易以來年化 +64%（非2年）");
    }
    const resumed = doc(Date.now() - HOUR);
    Object.assign((resumed.top as any[])[2].market.lineage, { kind: "RESUMPTION", event_date: "2025-02-24",
      related_entity: { name: "Synthetic Predecessor N.V.", symbol: "SPRE" } });
    const resumedText = JSON.stringify(buildBottleneckDetail(parseBottleneckV3(resumed)!, "S2", "text"));
    expect(resumedText).toContain("2025-02-24 恢復交易（前身 Synthetic Predecessor N.V.（SPRE））");
    expect(resumedText).toContain("恢復交易以來年化 +64%（非2年）");
    // Malformed or contradictory metadata closes: no since-listing figure, no event, the neutral statement instead.
    const breaks: [string, (market: any) => void][] = [
      ["when-issued base", market => { market.cagr_listed_start = "2025-02-13"; }],
      ["too short", market => { market.cagr_listed_span_days = 300; }],
      ["basis contradicts values", market => { market.long_term_basis = "TWO_YEAR"; }],
      ["impossible date", market => { market.lineage.regular_way_start = "2025-02-30"; }],
      ["no source", market => { market.lineage.sources = []; }],
      ["uncovered parent", market => { market.lineage.sources = [{ ...market.lineage.sources[0], claims: ["kind", "event_date", "regular_way_start"] }]; }],
      ["invented IPO parent", market => { market.lineage.kind = "IPO"; }],
      ["http source", market => { market.lineage.sources[0].url = "http://example.com/x"; }],
      ["bad request start", market => { market.history_request_start = "2023-13-01"; }],
      ["span is not asof minus start", market => { market.cagr_listed_span_days = 579; }],
      ["five days of history", market => { market.asof = "2025-03-01"; }],
      ["two years claimed for a 2025 segment", market => { Object.assign(market, { long_term_basis: "TWO_YEAR", cagr_2y: 0.9,
        cagr_listed: null, cagr_listed_start: null, cagr_listed_span_days: null }); }],
      ["after the report date", market => { market.asof = "2099-01-01"; market.cagr_listed_span_days = 27340; }],
      ["event gap over 60 days", market => { market.lineage.regular_way_start = "2025-06-24"; market.cagr_listed_start = "2025-06-24"; }],
      ["malformed UNKNOWN with a two-year value", market => { Object.assign(market, { lineage: { kind: "UNKNOWN", note: "x" },
        long_term_basis: "TWO_YEAR", cagr_2y: 0.9, cagr_listed: null, cagr_listed_start: null, cagr_listed_span_days: null }); }],
    ];
    for (const [label, mutate] of breaks) {
      const broken = doc(Date.now() - HOUR);
      mutate((broken.top as any[])[2].market);
      const detail = JSON.stringify(buildBottleneckDetail(parseBottleneckV3(broken)!, "S2", "text"));
      expect(detail, label).not.toContain("+64%");
      expect(detail, label).not.toContain("+90%");  // present but broken metadata suppresses the two-year value too
      expect(detail, label).not.toContain("上市沿革：");
      expect(detail, label).toContain("2年價格資料不足");
    }
  });

  it("labels a share-count change measured on the diluted weighted average and refuses an unknown basis", () => {
    const raw = doc(Date.now() - HOUR);
    Object.assign((raw.top as any[])[3].fundamentals, { shares_yoy: 1.003, shares_basis: "DILUTED_WEIGHTED_AVERAGE" });
    const parsed = parseBottleneckV3(raw)!;
    for (const style of ["text", "flex"] as const) {
      const detail = JSON.stringify(buildBottleneckDetail(parsed, "S3", style));
      expect(detail, style).toContain("+100.3%");
      expect(detail, style).toContain("稀釋加權平均股數");
    }
    expect(JSON.stringify(buildBottleneckDetail(parsed, "S1", "text"))).not.toContain("稀釋加權平均股數");  // shares outstanding: no label
    const invalid = doc(Date.now() - HOUR);
    (invalid.top as any[])[3].fundamentals.shares_basis = "GUESSED";
    expect(parseBottleneckV3(invalid)).toBeNull();
  });

  it("renders the sealer's own output (wire contract fixture shared with the Python sealer tests)", () => {
    // tests/fixtures/v213-lineage-sealed-markets.json: each `sealed` object is what scripts/publish_sealed_snapshot.py emits
    // for its `input` (asserted in tests/test_bottleneck_top20_v3.py); here it goes through the Worker parser to the public forms.
    for (const contract of lineageContract.cases) {
      const sealed = doc(Date.now() - HOUR);
      (sealed.top as any[])[2].market = structuredClone(contract.sealed);
      const parsed = parseBottleneckV3(sealed)!;
      expect(parsed, contract.name).not.toBeNull();
      const forms = [JSON.stringify(buildBottleneckDetail(parsed, "S2", "text")), JSON.stringify(buildBottleneckDetail(parsed, "S2", "flex")),
        JSON.stringify(buildBottleneckTop20Messages(parsed, "text"))];
      for (const body of forms) {
        expect(body, contract.name).toContain(contract.expect);
        for (const absent of contract.absent) expect(body, contract.name).not.toContain(absent);
      }
    }
  });

  it("shows a Taiwan listing's official monthly revenue beside the Yahoo quarter and refuses a malformed one", () => {
    const monthly = { source_id: "TPEX", source_url: "https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap05_O", period: "2026-08",
      revenue_yoy: 5.253153, cumulative_yoy: 4.889214, currency: "TWD" };
    const withCheck = doc(Date.now() - HOUR);
    (withCheck.top[1] as any).fundamentals.cross_check = monthly;
    const parsed = parseBottleneckV3(withCheck)!;
    expect(parsed).not.toBeNull();
    const expected = "官方月營收：櫃買中心 2026-08 單月年增 +525%，1–8 月累計年增 +489%";
    expect(JSON.stringify(buildBottleneckDetail(parsed, "S1", "text"))).toContain(expected);
    expect(JSON.stringify(buildBottleneckDetail(parsed, "S1", "flex"))).toContain(expected);
    expect(JSON.stringify(buildBottleneckTop20Messages(parsed, "flex"))).toContain(expected);
    for (const bad of [{ ...monthly, period: "2026-13" }, { ...monthly, source_url: "http://x" },
      { ...monthly, revenue_yoy: null, cumulative_yoy: null }, { ...monthly, revenue_yoy: "525%" },
      // ChatGPT review: the Worker enforces the seal's source -> period -> currency contract
      { ...monthly, period: "2026-Q2" }, { ...monthly, source_id: "CISION" }, { ...monthly, source_id: "YAHOO" },
      { ...monthly, currency: "USD" }, { ...monthly, period: "2026-０８" }]) {
      const rejected = doc(Date.now() - HOUR);
      (rejected.top[1] as any).fundamentals.cross_check = bad;
      expect(parseBottleneckV3(rejected)).toBeNull();
    }
  });

  it("shows a Stockholm listing's own interim report (Cision) with its quarter", () => {
    const report = { source_id: "CISION", source_url: "https://news.cision.com/sivers-semiconductors/r/q2,c4388331", period: "2026-Q2",
      revenue_yoy: -0.123779, cumulative_yoy: null, currency: "SEK" };
    const withReport = doc(Date.now() - HOUR);
    (withReport.top[0] as any).fundamentals.cross_check = report;
    const parsed = parseBottleneckV3(withReport)!;
    expect(parsed).not.toBeNull();
    const text = JSON.stringify(buildBottleneckDetail(parsed, "SIVE.ST", "text"));
    expect(text).toContain("公司財報公告：Cision（發行公司法規公告） 2026-Q2 營收年增 -12%");
    expect(text).not.toContain("官方月營收");
    const bad = doc(Date.now() - HOUR);
    (bad.top[0] as any).fundamentals.cross_check = { ...report, period: "2026-Q5" };
    expect(parseBottleneckV3(bad)).toBeNull();
    const korea = doc(Date.now() - HOUR);
    (korea.top[0] as any).fundamentals.cross_check = { ...report, source_id: "COMPANY_IR_KR", revenue_yoy: 2.567748, currency: "KRW",
      source_url: "https://news.skhynix.com/en/q2-2026-business-results/" };
    expect(JSON.stringify(buildBottleneckDetail(parseBottleneckV3(korea)!, "SIVE.ST", "text"))).toContain("公司財報公告：公司 IR 財報 2026-Q2 營收年增 +257%");
  });

  it("renders optional numbers the validator lets through as missing, never as NaN or a crash", () => {
    const sparse = doc(Date.now() - HOUR);
    delete (sparse.industries[0] as any).news.ratio;
    delete (sparse.industries[1] as any).median_acceleration;
    delete (sparse.top[0] as any).market.cross_check.diff;
    delete (sparse.top[1] as any).fundamentals.revenue_yoy;  // ChatGPT review: acceleration was NaN
    delete (sparse.top[1] as any).market_cap_usd;  // and the market cap US$NaNM
    (sparse.top[2] as any).fundamentals.cross_check = { source_id: "TPEX", source_url: "https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap05_O",
      period: "2026-08", cumulative_yoy: 0.2, currency: "TWD" };
    const parsed = parseBottleneckV3(sparse)!;
    expect(parsed).not.toBeNull();
    const flex = JSON.stringify(buildIndustryExplosionMessages(parsed, "flex"));
    const text = JSON.stringify(buildIndustryExplosionMessages(parsed, "text"));
    const detail = JSON.stringify(buildBottleneckDetail(parsed, "SIVE.ST", "text"));
    const second = [JSON.stringify(buildBottleneckDetail(parsed, "S1", "text")), JSON.stringify(buildBottleneckDetail(parsed, "S1", "flex")),
      JSON.stringify(buildBottleneckTop20Messages(parsed, "flex"))];
    for (const body of [flex, text, detail, ...second]) expect(body).not.toMatch(/NaN|undefined/);
    expect(second[0]).toContain("加速度 未揭露");
    expect(JSON.stringify(buildBottleneckDetail(parsed, "S2", "text"))).toContain("官方月營收：櫃買中心 2026-08 1–8 月累計年增 +20%");
    expect(flex).toContain("未取得");
    expect(text).toContain("SEC申報熱度 未取得｜");
    expect(text).toContain("SEC申報熱度 3.00x");
    expect(detail).toContain("未取得可比較差異");  // a missing diff is not a currency mismatch
  });

  it("falls back to lean cards instead of a failed reply when twenty full cards exceed five carousels", () => {
    const heavy = doc(REPORT);
    for (const entry of heavy.top as any[]) {
      entry.role_source.url = `https://example.com/${"r".repeat(170)}`;
      entry.outlook = { ...(structuredClone(OUTLOOKS[1]) as object), order_forecast: { ...forecastCase("S1"), issuer: entry.symbol } };
      entry.name = "N".repeat(80);
      entry.role = "r".repeat(200);
      entry.role_zh = "角".repeat(200);
    }
    const parsed = parseBottleneckV3(heavy, REPORT + HOUR)!;
    const bubbles = buildBottleneckTop20Messages(parsed, "flex") as unknown as { contents: { contents: unknown[] } }[];
    expect(bubbles.length).toBeLessThanOrEqual(5);
    expect(bubbles.reduce((total, message) => total + message.contents.contents.length, 0)).toBe(20);
    const serialized = JSON.stringify(bubbles);
    expect(serialized.match(/"訂單與成長情境"/g)).toHaveLength(20);
    expect(serialized).toContain("上市沿革：2025-02-21 自 Synthetic Parent（SPAR）分拆；2025-02-24 起正常交易");  // lean cards keep the event
    const s1 = parsed.top.find(entry => entry.symbol === "S1")!;
    // Operator 2026-09-27: the future ORDER estimate and the price scenario are different figures, each with 6-month and 1-year horizons.
    const [orders] = outlookTiles(parsed, s1);  // full and lean cards are both built from the tile and the order block
    expect(orders).toEqual(["現有訂單", "US$3.2B", "RPO 2026-07-26 年增+68%"]);
    expect(outlookForecast(parsed, s1).map(([text]) => text)).toEqual(["未來訂單預估", "半年內預計認列：未揭露", "1年內預計認列：US$1.2B（起算日 2026-07-26（非今日起），至 2027-07-26）", "訂單實現後股價情境",
      "若半年內實現訂單 → 無法估價（缺認列時程）", "若1年內實現訂單 → 無法估價（訂單僅覆蓋同期營收 0.3%）", "RPO 為剩餘履約義務，非全部訂單；預計認列非保證",
      "訂單資料截至 2026-07-26｜來源公布 2026-08-26"]);
    expect(serialized).toContain("若1年內實現訂單 → 無法估價（訂單僅覆蓋同期營收 0.3%）");  // the lean card keeps both horizons
  });

  // The report time is fixed so the horizon arithmetic is exact.
  const REPORT = Date.UTC(2026, 8, 27, 1, 0, 0);
  const fixed = () => parseBottleneckV3(doc(REPORT), REPORT + HOUR)!;
  const pick = (parsed: ReturnType<typeof fixed>, symbol: string) => parsed.top.find(item => item.symbol === symbol)!;
  const usd = (value: number) => `US$${(value / 1e9).toFixed(1)}B`;

  const card = (parsed: ReturnType<typeof fixed>, symbol: string) => outlookForecast(parsed, pick(parsed, symbol)).map(([text]) => text);
  const REFUSED = "1年內預計認列：資料未通過驗證";

  it("renders the sealed 6-month / 1-year order forecast from the Python contract fixture on the card and the detail", () => {
    const parsed = fixed();
    const detail = (symbol: string) => JSON.stringify(buildBottleneckDetail(parsed, symbol, "text"));
    // S1 NVDA: 12 months from the filing's schedule; 6 months not disclosed; no price (orders cover 0.3%); each reason on its row.
    expect(card(parsed, "S1")).toEqual(["未來訂單預估", "半年內預計認列：未揭露", "1年內預計認列：US$1.2B（起算日 2026-07-26（非今日起），至 2027-07-26）", "訂單實現後股價情境",
      "若半年內實現訂單 → 無法估價（缺認列時程）", "若1年內實現訂單 → 無法估價（訂單僅覆蓋同期營收 0.3%）", "RPO 為剩餘履約義務，非全部訂單；預計認列非保證",
      "訂單資料截至 2026-07-26｜來源公布 2026-08-26"]);
    expect(detail("S1")).toContain("1年內預計認列：US$1.2B（起算日 2026-07-26（非今日起），至 2027-07-26）＝RPO US$3.2B（截至 2026-07-26）× 公司揭露1年內認列 39%；全公司");
    expect(detail("S1")).toContain("同期營收水準＝2026-07-26 當季 ");
    expect(detail("S1")).toContain("覆蓋率 0.3%；其餘營收來源未由本訂單資料涵蓋");
    expect(detail("S1")).toContain("訂單來源：10-Q 2026-08-26（0000000000-26-000001） https://www.sec.gov/Archives/edgar/data/1045810/000104581026000075/nvda-20260726.htm");
    expect(detail("S1")).not.toContain("揭露日");  // the as-of date is the measurement date, never called the disclosure date
    // S2: explicit 6 and 12 months covering the revenue level: two order amounts, two price changes, never the same figure.
    expect(card(parsed, "S2")).toEqual(["未來訂單預估", "半年內預計認列：US$12.0B（起算日 2026-06-30（非今日起），至 2026-12-30）",
      "1年內預計認列：US$22.0B（起算日 2026-06-30（非今日起），至 2027-06-30）", "訂單實現後股價情境", "若半年內實現訂單 → 股價預估 +50%",
      "若1年內實現訂單 → 股價預估 +38%", "條件情境：營收達預計認列額，P/S與股數不變；非目標價、非今日起報酬", "RPO 為剩餘履約義務，非全部訂單；預計認列非保證",
      "訂單資料截至 2026-06-30｜來源公布 2026-08-10"]);
    expect(detail("S2")).toContain("條件情境：營收達預計認列額，P/S與股數不變；非目標價、非今日起報酬；未計新訂單、取消或遞延");
    expect(card(parsed, "S3")[1]).toBe("半年內預計認列：未揭露");  // an interpolated 6 months is not shown
    expect(card(parsed, "S5").slice(1, 3)).toEqual(["半年內預計認列：未取得訂單資料", "1年內預計認列：未取得訂單資料"]);  // not acquired, never 0 or 無
    expect(card(parsed, "S7")[2]).toBe("1年內預計認列：未揭露");  // CRWV: 24 months is a labelled reference only
    expect(detail("S7")).toContain("參考（固定期間，非半年／1年）：24個月內認列 US$42.5B（RPO × 41%，2026-06-30–2028-06-30）。");
    // S8: a segment's book is a model sensitivity, never a realization or a price.
    expect(card(parsed, "S8")).toEqual(["未來訂單預估", "半年內預計認列：未揭露", "1年內預計認列：未揭露", "訂單實現後股價情境",
      "若半年內實現訂單 → 無法估價（缺認列時程）", "若1年內實現訂單 → 無法估價（缺認列時程）", "訂單餘額外推敏感度（非訂單實現情境）",
      "半年後訂單餘額外推：25.13兆 KRW（至 2027-03-27）", "1年後訂單餘額外推：32.15兆 KRW（至 2027-09-27）", "模型推估，非公司揭露、非期間認列"]);
    expect(detail("S8")).toContain("依年增+63%（公司自述：「수주잔고 전년 동기 +63%」）自今日起外推；期末餘額，非期間認列");
    expect(detail("S8")).toContain("參考（固定期間，公司指引，非已簽約訂單）：2026年全年新接訂單指引 12.00兆 KRW。");
    expect(card(parsed, "S9")[2]).toBe("1年內預計認列：資料未通過驗證");  // period mismatch: the detail names it
    expect(detail("S9")).toContain("訂單與營收期間不一致");
    // S10: a company-wide book is a sensitivity too: no "若…實現訂單" price from an extrapolation (contract ORDERS-V2-01).
    expect(card(parsed, "S10").slice(4, 6)).toEqual(["若半年內實現訂單 → 無法估價（缺認列時程）", "若1年內實現訂單 → 無法估價（缺認列時程）"]);
    expect(card(parsed, "S10")).toContain("1年後訂單餘額外推：US$2.6B（至 2027-09-27）");
    expect(detail("S10")).toContain("（對比 2025-06-30 的 US$1.6B）自今日起外推");
    // S11: the 6-month window ended before the report: not a future estimate; the 12-month one still stands.
    expect(card(parsed, "S11").slice(1, 6)).toEqual(["半年內預計認列：期間已結束", "1年內預計認列：US$22.0B（起算日 2026-03-11（非今日起），至 2027-03-11）",
      "訂單實現後股價情境", "若半年內實現訂單 → 無法估價（期間已結束）", "若1年內實現訂單 → 股價預估 +38%"]);
    // S12: Sandisk's fourth quarter derived from the 10-K is named in the revenue level.
    expect(card(parsed, "S12")[2]).toBe("1年內預計認列：US$11.4B（起算日 2026-07-03（非今日起），至 2027-07-03）");
    expect(detail("S12")).toContain("同期營收水準＝2026-07-03 當季（第四季＝全年 US$20.2B − 前九個月 US$11.3B）");
    // The text form of the Top20 carries both rows of both blocks for every entry.
    const text = JSON.stringify(buildBottleneckTop20Messages(parsed, "text"));
    expect(text).toContain("未來訂單預估：半年內預計認列：未揭露／1年內預計認列：US$1.2B（起算日 2026-07-26（非今日起），至 2027-07-26）｜訂單實現後股價情境：若半年內實現訂單 → 無法估價（缺認列時程）／若1年內實現訂單 → 無法估價（訂單僅覆蓋同期營收 0.3%）｜RPO 為剩餘履約義務，非全部訂單；預計認列非保證｜訂單資料截至 2026-07-26｜來源公布 2026-08-26");
    expect(text).toContain("訂單實現後股價情境：若半年內實現訂單 → 股價預估 +50%／若1年內實現訂單 → 股價預估 +38%（條件情境：營收達預計認列額，P/S與股數不變；非目標價、非今日起報酬）");
    expect(text).toContain("訂單餘額外推敏感度（非訂單實現情境）：半年後訂單餘額外推：25.13兆 KRW（至 2027-03-27）／1年後訂單餘額外推：32.15兆 KRW（至 2027-09-27）（模型推估，非公司揭露、非期間認列）");
    expect(text.match(/未來訂單預估：半年內預計認列：/g)).toHaveLength(20);
  });

  it("shows a tampered, foreign or inconsistent sealed forecast as unavailable, never another figure", () => {
    const orderTileOf = (mutate: (forecast: any) => void, issuer = "S1", index = 1) => {
      const raw = doc(REPORT);
      const forecast = forecastCase(issuer);
      mutate(forecast);
      (raw.top as any[])[index].outlook.order_forecast = forecast;
      const parsed = parseBottleneckV3(raw, REPORT + HOUR)!;
      return card(parsed, `S${index}`);
    };
    const tamper: [string, (forecast: any) => void][] = [
      ["amount", f => { f.m12.amount *= 2; }], ["share", f => { f.m12.share_pct = 120; }], ["coverage", f => { f.m12.scenario.coverage = 2; }],
      ["price from nothing", f => { f.m12.scenario = { status: "AVAILABLE", coverage: 1.2, change: 0.2 }; }],
      ["window", f => { f.m12.end = "2027-09-27"; }], ["stale", f => { f.m12.as_of = "2026-01-01"; f.m12.start = "2026-01-01"; f.m12.end = "2027-01-01"; }],
      ["future filing", f => { f.m12.filed = "2026-12-01"; }], ["http source", f => { f.m12.source_url = "http://www.sec.gov/x"; }],
      ["hostless source", f => { f.m12.source_url = "https://"; }], ["overflow", f => { f.m12.rpo = 1.7e308; f.m12.amount = Infinity; }],
      ["unknown basis", f => { f.m12.basis = "ANALYST"; }], ["unknown version", f => { f.version = 2; }],
      ["another issuer", f => { f.issuer = "NVDA"; }], ["segment recognition", f => { f.m12.scope = "SEGMENT"; }],
      ["status says unavailable", f => { f.status = "UNAVAILABLE"; f.reason = "NO_ORDERS"; }],
      ["unknown currency", f => { f.m12.currency = "BANANAS"; }],
    ];
    for (const [label, mutate] of tamper) expect(orderTileOf(mutate)[2], label).toBe(label === "stale" ? "1年內預計認列：資料逾200天" : REFUSED);
    // Mixed evidence across the horizons, a shrinking schedule, an ended window.
    expect(orderTileOf(f => { f.m6.as_of = "2026-06-29"; f.m6.start = "2026-06-29"; f.m6.end = "2026-12-29"; }, "S2", 2)[2]).toBe(REFUSED);
    expect(orderTileOf(f => { f.m6.share_pct = 60; f.m6.amount = 24e9; f.m6.scenario = { status: "AVAILABLE", coverage: 3, change: 2 }; }, "S2", 2)[2]).toBe(REFUSED);
    expect(orderTileOf(f => { f.m6.status = "AVAILABLE"; f.m6.reason = undefined; Object.assign(f.m6, { ...f.m12, share_pct: 30, amount: 12e9,
      end: "2026-09-11", scenario: { status: "AVAILABLE", coverage: 1.5, change: 0.5 } }); f.status = "AVAILABLE"; }, "S11", 11)[1]).toBe("半年內預計認列：期間已結束");
    // A segment book priced as the company, or a book whose growth has no comparison on record.
    // A tampered book horizon is invalid in the sensitivity too; a book is never priced.
    expect(orderTileOf(f => { f.m12.scenario = { status: "AVAILABLE", change: 0.63 }; }, "S8", 8)).toContain("1年後訂單餘額外推：資料未通過驗證");
    expect(orderTileOf(f => { f.m12.yoy_prior_amount = 1e9; }, "S10", 10)).toContain("1年後訂單餘額外推：資料未通過驗證");
    expect(orderTileOf(f => { f.m12.scenario.change = 0.9; }, "S10", 10)).toContain("1年後訂單餘額外推：資料未通過驗證");
    expect(orderTileOf(() => {}, "S10", 10).some(line => line.includes("股價預估"))).toBe(false);
    const legacy = doc(REPORT);  // a document sealed before the forecast existed: unavailable, never the old analyst tiles
    delete (legacy.top as any[])[1].outlook.order_forecast;
    const parsedLegacy = parseBottleneckV3(legacy, REPORT + HOUR)!;
    expect(card(parsedLegacy, "S1")).toEqual(["未來訂單預估", "半年內預計認列：尚未產生", "1年內預計認列：尚未產生", "訂單實現後股價情境",
      "若半年內實現訂單 → 無法估價（缺認列時程）", "若1年內實現訂單 → 無法估價（缺認列時程）"]);
  });

  it("requires the filing evidence, one filing for every horizon and reference, and a fully derived fourth quarter (Astra batch 33)", () => {
    const view = (issuer: string, index: number, mutate: (forecast: any) => void) => {
      const raw = doc(REPORT);
      const forecast = forecastCase(issuer);
      mutate(forecast);
      (raw.top as any[])[index].outlook.order_forecast = forecast;
      const parsed = parseBottleneckV3(raw, REPORT + HOUR)!;
      return { rows: card(parsed, `S${index}`), detail: JSON.stringify(buildBottleneckDetail(parsed, `S${index}`, "text")) };
    };
    for (const field of ["accession", "passage", "report_period", "quarter_start", "explicit", "form"]) {
      expect(view("S1", 1, f => { delete f.m12[field]; }).rows[2], field).toBe(REFUSED);
    }
    for (const [label, change] of [["old report period", { report_period: "2025-01-01" }], ["not explicit", { explicit: false }],
      ["bad accession", { accession: "123" }], ["8-K", { form: "8-K" }], ["userinfo URL", { source_url: "https://:password@example.com/x" }],
      ["bad port", { source_url: "https://example.com:99999/x" }], ["quarter too long", { quarter_start: "2026-01-01" }]] as const) {
      expect(view("S1", 1, f => Object.assign(f.m12, change)).rows[2], label).toBe(REFUSED);
    }
    // One filing for both horizons: a 6-month record from another accession or another quarter invalidates both.
    expect(view("S2", 2, f => { f.m6.accession = "0000000000-26-000002"; }).rows[2]).toBe(REFUSED);
    expect(view("S2", 2, f => { f.m6.quarter_start = "2026-04-02"; }).rows[2]).toBe(REFUSED);
    // The top-level reason follows the horizons.
    expect(view("S7", 7, f => { f.reason = "NO_ORDERS"; }).detail).not.toContain("24個月內認列");
    // The fourth-quarter derivation is checked as a whole.
    for (const [label, change] of [["ancient nine months", { nine_months_end: "1900-01-01" }], ["no accession", { annual_accession: null }],
      ["negative inputs", { annual: -20.248e9, nine_months: -29.213e9 }], ["other fiscal year", { annual_start: "2025-01-01" }]] as const) {
      expect(view("S12", 12, f => Object.assign(f.m12.quarter_derivation, change)).rows[2], label).toBe(REFUSED);
    }
    expect(view("S12", 12, f => { f.m12.quarter_start = "2026-04-05"; }).rows[2]).toBe(REFUSED);
    // The 24-month reference is recomputed, fresh and from the same filing, even for a 24-month-only company.
    const crwv = (mutate: (reference: any) => void) => view("S7", 7, f => mutate(f.references[0])).detail;
    expect(crwv(() => {})).toContain("24個月內認列 US$42.5B");
    expect(crwv(r => { r.amount = 1e99; })).not.toMatch(/24個月內認列|e\+/);
    expect(crwv(r => { r.as_of = "2025-01-01"; r.start = "2025-01-01"; r.end = "2027-01-01"; })).not.toContain("24個月內認列");
    expect(crwv(r => { r.accession = "bad"; })).not.toContain("24個月內認列");
    expect(view("S2", 2, f => { f.references.push({ ...forecastCase("S7").references[0] }); }).rows[2]).toBe(REFUSED);  // another filing
    expect(view("S7", 7, f => { f.references.push(f.references[0]); }).detail).not.toContain("24個月內認列");  // duplicated
  });

  it("binds a book's comparison and segment across horizons, requires a references array and shares the URL rule (Astra batch 34)", () => {
    const tilesOf = (issuer: string, index: number, mutate: (forecast: any) => void) => {
      const raw = doc(REPORT);
      const forecast = forecastCase(issuer);
      mutate(forecast);
      (raw.top as any[])[index].outlook.order_forecast = forecast;
      const parsed = parseBottleneckV3(raw, REPORT + HOUR)!;
      return { rows: card(parsed, `S${index}`), detail: JSON.stringify(buildBottleneckDetail(parsed, `S${index}`, "text")) };
    };
    expect(tilesOf("S10", 10, f => { f.m6.yoy_prior_as_of = "2025-06-01"; }).rows[2]).toBe(REFUSED);  // SERIES comparison differs
    expect(tilesOf("S8", 8, f => { f.m6.scope_label = "造船部門"; }).rows[2]).toBe(REFUSED);  // another segment
    expect(tilesOf("S8", 8, f => { f.m6.yoy_evidence = "another statement"; }).rows[2]).toBe(REFUSED);  // another company statement
    for (const container of [{ kind: "RECOGNITION_24M", amount: 1e99 }, "broken", null]) {
      expect(tilesOf("S1", 1, f => { f.references = container; }).rows[2], JSON.stringify(container)).toBe(REFUSED);
      expect(tilesOf("S7", 7, f => { f.references = container; }).detail, JSON.stringify(container)).toContain("1年內預計認列：資料未通過驗證");
    }
    for (const row of urlTable.cases) {  // the same table the Python tests use
      expect(tilesOf("S1", 1, f => { f.m12.source_url = row.url; }).rows[2], row.url)
        .toBe(row.accepted ? "1年內預計認列：US$1.2B（起算日 2026-07-26（非今日起），至 2027-07-26）" : REFUSED);
      expect(tilesOf("S10", 10, f => { f.m6.source_url = row.url; f.m12.source_url = row.url; }).rows.includes("1年後訂單餘額外推：US$2.6B（至 2027-09-27）"), row.url)
        .toBe(row.accepted);
      expect(tilesOf("S7", 7, f => { f.references[0].source_url = row.url; }).detail.includes("24個月內認列 US$42.5B"), row.url).toBe(row.accepted);
    }
  });

  it("paginates the Top20 text form instead of cutting entries away, with long valid inputs", () => {
    const long = doc(REPORT);
    for (const entry of long.top as any[]) {
      entry.name = "N".repeat(160);
      entry.role = "r".repeat(200);
    }
    const messages = buildBottleneckTop20Messages(parseBottleneckV3(long, REPORT + HOUR)!, "text") as { type: string; text: string }[];
    expect(messages.length).toBeLessThanOrEqual(5);
    const all = messages.map(message => message.text).join("\n");
    for (let rank = 1; rank <= 20; rank += 1) expect(all, `rank ${rank}`).toMatch(new RegExp(`(^|\n)${rank}\. `));
    expect(all.match(/未來訂單預估：半年內預計認列：/g)).toHaveLength(20);
    for (const message of messages) expect(message.text.length).toBeLessThanOrEqual(4900);
  });

  it("never prints an overflowing or malformed figure on the public card or detail", () => {
    for (const [label, mutate] of [
      ["order overflow", (parsed: any) => Object.assign(pick(parsed, "S1").outlook!.orders as object, { amount: Number.MAX_VALUE, yoy: 1 })],
      ["huge target", (parsed: any) => Object.assign(pick(parsed, "S1").outlook!.consensus as object, { target_upside: 1e307 })],
      ["partial order date", (parsed: any) => Object.assign(pick(parsed, "S1").outlook!.orders as object, { as_of: "2026-7-26" })],
    ] as const) {
      const parsed = fixed();
      mutate(parsed);
      const card = JSON.stringify(buildBottleneckTop20Messages(parsed, "flex"));
      const detail = JSON.stringify(buildBottleneckDetail(parsed, "S1", "text")) + JSON.stringify(buildBottleneckDetail(parsed, "S1", "flex"));
      for (const body of [card, detail]) expect(body, label).not.toMatch(/Infinity|NaN|undefined/);
    }
  });

  it("never shows revenue or malformed guidance as new-order guidance in any form", () => {
    for (const [label, change] of [["revenue guidance", { kind: "REVENUE" }], ["fractional year", { year: 2026.5 }],
      ["no kind", { kind: null }]] as const) {
      const raw = doc(REPORT);  // the raw document is changed before parsing, as a sealed object would arrive
      Object.assign((raw.top as any[])[4].outlook.orders.guidance, change);
      const parsed = parseBottleneckV3(raw, REPORT + HOUR)!;
      expect(parsed, label).not.toBeNull();
      for (const style of ["text", "flex"] as const) {
        const detail = JSON.stringify(buildBottleneckDetail(parsed, "S4", style));
        expect(detail, `${label} ${style}`).not.toContain("12.00兆 KRW");  // the guided amount is withheld
        expect(detail, `${label} ${style}`).not.toContain("年新接訂單");
        expect(detail, `${label} ${style}`).not.toContain("公司新接訂單指引");
      }
      expect(JSON.stringify(buildBottleneckTop20Messages(parsed, "flex")), label).not.toContain("12.00兆 KRW");
    }
    const supported = JSON.stringify(buildBottleneckDetail(fixed(), "S4", "text"));  // the supported kind still shows
    expect(supported).toContain("公司指引：2026 年新接訂單 12.00兆 KRW（原 8.40兆 KRW）");
  });

  it("attributes an official previous-quarter YoY separately and refuses contradictory evidence (L18-5351-CURATED-01)", () => {
    // The fundamentals the Python sealer emitted (tests/test_bottleneck_top20_v3.py OfficialPreviousQuarterTests).
    const sealed = (officialRevenueFixture as any).fundamentals;
    const BUILT = Date.parse((officialRevenueFixture as any).generated_at);  // the sealer's build instant, after retrieval
    const withOfficial = (mutate: (fund: any, entry: any) => void = () => {}, built = BUILT) => {
      const d = doc(built);
      const entry = (d.top as any[])[1];
      Object.assign(entry, { symbol: "5351.TWO", name: "Etron Technology", fundamentals: structuredClone(sealed) });
      mutate(entry.fundamentals, entry);
      return parseBottleneckV3(d, built + HOUR);
    };
    const parsed = withOfficial()!;
    expect(parsed).not.toBeNull();
    const label = "前一季年增來源：鈺創官方合併季報（2026Q1／2025Q1，附註六(二十四) p.39），已核對同基準";
    const q1 = "https://etron.com/wp-content/uploads/2026/05/115Q1%E5%90%88%E4%BD%B5%E8%B2%A1%E5%A0%B1.pdf";
    const text = buildBottleneckDetail(parsed, "5351.TWO", "text") as { type: string; text: string }[];
    const body = text.map(message => message.text).join("\n");
    expect(body).toContain("財報（Yahoo Finance 季度損益表（非官方）；前一季年增採官方合併季報，季末 2026-06-30）：營收年增 +557.8%，前一季年增 +336.2%（加速度 +221.6個百分點）");
    expect(body).toContain(`來源：https://finance.yahoo.com/quote/5351.TWO/financials\n${label}\n前一季來源：${q1}`);
    expect(text.every(message => message.type === "text" && message.text.length <= 4900)).toBe(true);
    const flex = JSON.stringify(buildBottleneckDetail(parsed, "5351.TWO", "flex"));
    expect(flex).toContain(label);
    expect(flex).toContain(`前一季來源：${q1}`);
    expect(flex).toContain("https://finance.yahoo.com/quote/5351.TWO/financials");  // the current quarter stays Yahoo's
    const cards = buildBottleneckTop20Messages(parsed, "flex") as unknown[];
    expect(cards.length).toBeLessThanOrEqual(5);
    expect(JSON.stringify(cards)).toContain("財報：Yahoo Finance 季度損益表（非官方）（前一季採官方合併季報），季末 2026-06-30");
    // Every other entry keeps its unchanged attribution.
    expect(JSON.stringify(buildBottleneckDetail(parsed, "S1", "flex"))).not.toContain("官方合併季報");

    const refused: [string, (fund: any, entry: any) => void][] = [
      ["no evidence", fund => { fund.revenue_yoy_prev_source = null; }],
      ["evidence under a Yahoo basis", fund => { fund.revenue_yoy_prev_basis = "YAHOO"; }],
      ["unknown basis", fund => { fund.revenue_yoy_prev_basis = "OFFICIAL"; }],
      ["another symbol", (_fund, entry) => { entry.symbol = "5351.TW"; }],
      ["out of period", fund => { fund.quarter_end = "2026-09-30"; }],
      ["previous YoY", fund => { fund.revenue_yoy_prev += 1e-9; }],
      ["current YoY", fund => { fund.revenue_yoy += 0.001; }],
      ["digest format", fund => { fund.revenue_yoy_prev_source.config_sha256 = "A".repeat(64); }],
      ["unknown field", fund => { fund.revenue_yoy_prev_source.extra = 1; }],
      ["claim amount", fund => { fund.revenue_yoy_prev_source.previous_pair.current.amount = 2735413; }],
      ["claim float", fund => { fund.revenue_yoy_prev_source.previous_pair.prior_year.amount = 627130.5; }],
      ["claim period", fund => { fund.revenue_yoy_prev_source.current_pair.prior_year.end = "2025-06-29"; }],
      ["claim document", fund => { fund.revenue_yoy_prev_source.current_pair.current.document_id = "X"; }],
      ["http document", fund => { fund.revenue_yoy_prev_source.documents[0].url = "http://etron.com/a.pdf"; }],
      ["foreign host", fund => { fund.revenue_yoy_prev_source.documents[0].url = "https://etron.com.example/a.pdf"; }],
      ["document hash", fund => { fund.revenue_yoy_prev_source.documents[1].sha256 = "z".repeat(64); }],
      ["restatement", fund => { fund.revenue_yoy_prev_source.restatement_check.half_year_claims.current.amount = 7634099; }],
      ["reconciliation", fund => { fund.revenue_yoy_prev_source.restatement_check.reconciliations[0].difference = 1; }],
      ["overlap delta", fund => { fund.revenue_yoy_prev_source.cross_check.current_current.delta_twd = 1001; }],
      ["overlap observation", fund => { fund.revenue_yoy_prev_source.cross_check.previous_current.yahoo_twd = 2735412000 + 1001; }],
      ["overlap official", fund => { fund.revenue_yoy_prev_source.cross_check.current_prior_year.official_twd = 744722; }],
      ["looser threshold", fund => { fund.revenue_yoy_prev_source.cross_check.max_overlap_delta_twd = 2000; }],
      ["ratio observation", fund => { fund.revenue_yoy_prev_source.cross_check.current_yoy.yahoo_ratio += 1e-9; }],
      ["currency", fund => { fund.revenue_yoy_prev_source.cross_check.financial_currency = "USD"; }],
      // Chronology and text as strict as the sealer (Astra review r1, fix 2).
      ["impossible published date", fund => { fund.revenue_yoy_prev_source.documents[0].published_date = "2026-02-31"; }],
      ["impossible retrieval", fund => { fund.revenue_yoy_prev_source.documents[0].retrieved_at = "2026-99-99T99:99:99Z"; }],
      ["retrieval after the report", fund => { fund.revenue_yoy_prev_source.documents[0].retrieved_at = "2099-01-01T00:00:00Z"; }],
      ["published after retrieval", fund => { fund.revenue_yoy_prev_source.documents[0].published_date = "2026-09-28"; }],
      ["published before 1990", fund => { fund.revenue_yoy_prev_source.documents[0].published_date = "1989-12-31"; }],
      ["multi-line note", fund => { fund.revenue_yoy_prev_source.previous_pair.current.note = "six\nFAKE"; }],
      ["blank row", fund => { fund.revenue_yoy_prev_source.current_pair.current.row = "   "; }],
      ["control character in a title", fund => { fund.revenue_yoy_prev_source.documents[1].title += "\u0007"; }],
      ["lone surrogate", fund => { fund.revenue_yoy_prev_source.issuer_short_name_zh = "\ud800"; }],
      ["space in the URL", fund => { fund.revenue_yoy_prev_source.documents[0].url += " x"; }],
    ];
    for (const [name, mutate] of refused) expect(withOfficial(mutate), name).toBeNull();
    // A report generated before the documents were retrieved cannot carry them (fresh at its own read clock).
    expect(withOfficial(() => {}, Date.parse("2026-09-27T10:00:00Z"))).toBeNull();
    expect(withOfficial(() => {}, Date.parse("2026-09-27T10:14:53Z"))).not.toBeNull();
    // Legacy documents (neither field) and Yahoo-basis ones parse as before.
    expect(withOfficial(fund => { delete fund.revenue_yoy_prev_basis; delete fund.revenue_yoy_prev_source; fund.revenue_yoy_prev = null; })).not.toBeNull();
    const yahoo = withOfficial(fund => { fund.revenue_yoy_prev_basis = "YAHOO"; fund.revenue_yoy_prev_source = null; })!;
    expect(JSON.stringify(buildBottleneckDetail(yahoo, "5351.TWO", "flex"))).not.toContain("官方合併季報");
  });
});
