// Bottleneck-explosion Top20 v3 and the industry ranking: strict parsing, report-age bound, LINE rendering.
import { describe, expect, it } from "vitest";
import {
  buildBottleneckDetail, buildBottleneckTop20Messages, buildIndustryExplosionMessages, horizonForecast, outlookTiles, parseBottleneckV3,
} from "../src/v213/bottleneck-v3";
import { doc, HOUR, OUTLOOKS } from "./bottleneck-v3-fixture";
import lineageContract from "../../tests/fixtures/v213-lineage-sealed-markets.json";

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
    // One layout on every card: the same three tiles in the same order.
    for (const label of ["現有訂單", "未來訂單預估", "若實現股價"]) expect(serialized.match(new RegExp(`"${label}"`, "g"))).toHaveLength(20);
    expect(serialized).toContain("RPO 2026-07-26 年增+68%");
    expect(serialized).toContain("17.51兆 KRW");
    expect(serialized).toContain("在手 2026-06-30 年增+63%");
    expect(serialized).toContain("在手訂單餘額依年增+63%自2026-06-30外推");
    expect(serialized).toContain("公司未公布");
    expect(serialized).toContain("分析師12個月平均目標價（59位）");
    expect(serialized).toContain("1年 +46%");
    expect(serialized).toContain("樣本不足");  // one analyst: no scenario on the card
    expect(serialized).not.toContain("+2860%");
    expect(serialized).toContain("目標價樣本不足（1位）");
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
    expect(textWithReport[0]!.text).toContain("若實現的股價情境：營收實現·市銷率不變 +70%");
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
    expect(serialized).toContain("上市沿革：2025-02-21 自 Synthetic Parent（SPAR）分拆；2025-02-24 起正常交易");  // lean cards keep the event
    const s1 = parsed.top.find(entry => entry.symbol === "S1")!;
    // Operator 2026-09-27: the future ORDER estimate and the price scenario are different figures, each with 6-month and 1-year horizons.
    // (the extrapolated amounts depend on the clock; the fixed-clock tests below check them exactly)
    const [orders, future, price] = outlookTiles(parsed, s1);  // full and lean cards are both built from these three items
    expect(orders).toEqual(["現有訂單", "US$3.2B", "RPO 2026-07-26 年增+68%"]);
    expect(future![0]).toBe("未來訂單預估");
    expect(future![1]).toMatch(/^1年 US\$\d+\.\dB$/);
    expect(future![2]).toMatch(/^6個月 US\$\d+\.\dB・RPO餘額依年增\+68%自2026-07-26外推$/);
    expect(price).toEqual(["若實現股價", "1年 +46%", "6個月 +21%・分析師12個月平均目標價（59位）；6個月按時間比例（假設）"]);
  });

  // The report time is fixed so the horizon arithmetic is exact.
  const REPORT = Date.UTC(2026, 8, 27, 1, 0, 0);
  const fixed = () => parseBottleneckV3(doc(REPORT), REPORT + HOUR)!;
  const pick = (parsed: ReturnType<typeof fixed>, symbol: string) => parsed.top.find(item => item.symbol === symbol)!;
  const usd = (value: number) => `US$${(value / 1e9).toFixed(1)}B`;

  it("extrapolates the order book from its disclosure date to the report date plus 6 and 12 months", () => {
    const parsed = fixed();
    const age = (REPORT - Date.parse("2026-07-26")) / 86_400_000;
    const at = (days: number) => usd(3.2e9 * Math.pow(1.68, (age + days) / 365));
    expect(horizonForecast(parsed, pick(parsed, "S1")).orders).toEqual({ m6: at(182.5), y1: at(365), ends: { m6: "2027-03", y1: "2027-09" },
      basis: "RPO餘額依年增+68%自2026-07-26外推" });
    const detail = JSON.stringify(buildBottleneckDetail(parsed, "S1", "text"));
    expect(detail).toContain(`未來訂單預估：6個月（至2027-03）${at(182.5)}、1年（至2027-09）${at(365)}`);
    expect(detail).toContain("若實現股價：6個月（至2027-03）+21%、1年（至2027-09）+46%");
    const card = JSON.stringify(buildBottleneckTop20Messages(parsed, "flex"));
    expect(card).toContain(`1年 ${at(365)}`);
    expect(card).not.toMatch(/NaN|undefined/);
  });

  it("refuses stale, future-dated, extreme or collapsing order data and keeps guidance to its own year", () => {
    const cases: [Record<string, unknown>, string | null][] = [
      [{ as_of: "2021-04-03" }, "訂單資料過舊，不外推"], [{ as_of: "2026-12-01" }, "訂單日期晚於報告日，不採用"],
      [{ yoy: 5.52 }, "年增+552%過高（多為口徑變動），不外推"], [{ yoy: -1.5 }, "訂單大幅萎縮，不外推"], [{ yoy: null }, "無年增可外推"],
      [{ yoy: -0.3 }, null]];
    for (const [change, basis] of cases) {
      const parsed = fixed();
      Object.assign(pick(parsed, "S1").outlook!.orders as object, change);
      const orders = horizonForecast(parsed, pick(parsed, "S1")).orders;
      if (basis) expect(orders, JSON.stringify(change)).toMatchObject({ m6: null, y1: null, basis });
      else expect(orders.y1).toBe(usd(3.2e9 * Math.pow(0.7, ((REPORT - Date.parse("2026-07-26")) / 86_400_000 + 365) / 365)));  // declining
    }
    const korea = fixed();
    expect(horizonForecast(korea, pick(korea, "S4")).orders.basis).toBe("在手訂單餘額依年增+63%自2026-06-30外推");
    (pick(korea, "S4").outlook!.orders as any).yoy = null;  // guidance only: its own year, never relabelled as 1 year
    expect(horizonForecast(korea, pick(korea, "S4")).orders).toMatchObject({ fixed: { label: "2026年全年", value: "12.00兆 KRW" },
      basis: "公司新接訂單指引（全年，非滾動12個月）" });
    expect(outlookTiles(korea, pick(korea, "S4"))[1]).toEqual(["未來訂單預估", "2026年全年 12.00兆 KRW", "公司新接訂單指引（全年，非滾動12個月）"]);
    (pick(korea, "S4").outlook!.orders as any).guidance.year = 2020;
    expect(horizonForecast(korea, pick(korea, "S4")).orders.fixed).toBeUndefined();
    expect(outlookTiles(korea, pick(korea, "S5"))[1]).toEqual(["未來訂單預估", "未揭露", "公司未公布訂單"]);
  });

  it("never prints an overflowing or malformed horizon on the public card or detail", () => {
    const cases: [string, string, (parsed: ReturnType<typeof fixed>) => void, RegExp | string][] = [
      ["order overflow", "S1", parsed => Object.assign(pick(parsed, "S1").outlook!.orders as object, { amount: Number.MAX_VALUE, yoy: 1 }),
        "外推結果超出可表示範圍，不採用"],
      ["huge target", "S1", parsed => Object.assign(pick(parsed, "S1").outlook!.consensus as object, { target_upside: 1e307 }), "目標價資料異常，不採用"],
      ["partial order date", "S1", parsed => Object.assign(pick(parsed, "S1").outlook!.orders as object, { as_of: "2026-7-26" }), "訂單日期不明，不外推"],
      ["fractional guidance year", "S4", parsed => {
        Object.assign(pick(parsed, "S4").outlook!.orders as object, { yoy: null });
        (pick(parsed, "S4").outlook!.orders as any).guidance.year = 2026.5;
      }, "無年增可外推"],
      ["unsupported guidance kind", "S4", parsed => {
        Object.assign(pick(parsed, "S4").outlook!.orders as object, { yoy: null });
        (pick(parsed, "S4").outlook!.orders as any).guidance.kind = "REVENUE";
      }, "無年增可外推"],
    ];
    for (const [label, symbol, mutate, expected] of cases) {
      const parsed = fixed();
      mutate(parsed);
      const card = JSON.stringify(buildBottleneckTop20Messages(parsed, "flex"));
      const detail = JSON.stringify(buildBottleneckDetail(parsed, symbol, "text")) + JSON.stringify(buildBottleneckDetail(parsed, symbol, "flex"));
      for (const body of [card, detail]) expect(body, label).not.toMatch(/Infinity|NaN|undefined/);
      expect(detail, label).toContain(expected);
      expect(detail, label).not.toContain("2026.5");
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

  it("takes the price horizon only from a 12-month target with enough analysts and a valid return", () => {
    for (const [change, basis] of [[{ target_analysts: 1 }, "目標價樣本不足（1位）"], [{ target_upside: null }, "無分析師目標價"],
      [{ target_upside: -1.5 }, "目標價資料異常，不採用"]] as const) {
      const parsed = fixed();
      Object.assign(pick(parsed, "S1").outlook!.consensus as object, change);
      expect(horizonForecast(parsed, pick(parsed, "S1")).price, JSON.stringify(change)).toMatchObject({ m6: null, y1: null, basis });
    }
  });

});
