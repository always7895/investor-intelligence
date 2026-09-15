import { describe, expect, it } from "vitest";
import {
  parseGlobalEquityQuery,
  buildGlobalEquityLookupMessages,
  type EquityLookupResult,
} from "../src/v213/global-equity-lookup";
import { assertLineMessages } from "../src/line-messages";

describe("Global Equity Lookup Parser & Presentation", () => {
  describe("Matrix of market symbols with explicit suffix scheme hints", () => {
    const matrix = [
      { input: "7203.T", expectedMarket: "JAPAN", canonical: "7203.T", leadingZero: false },
      { input: "005930.KS", expectedMarket: "KOREA", canonical: "005930.KS", leadingZero: true },
      { input: "0700.HK", expectedMarket: "HK", canonical: "0700.HK", leadingZero: true },
      { input: "600519.SS", expectedMarket: "CHINA_SHANGHAI", canonical: "600519.SS", leadingZero: false },
      { input: "000001.SZ", expectedMarket: "CHINA_SHENZHEN", canonical: "000001.SZ", leadingZero: true },
      { input: "2330.TW", expectedMarket: "TAIWAN", canonical: "2330.TW", leadingZero: false },
      { input: "IQE.L", expectedMarket: "UK", canonical: "IQE.L", leadingZero: false },
      { input: "SIVE.ST", expectedMarket: "SWEDEN", canonical: "SIVE.ST", leadingZero: false },
      { input: "ASML.AS", expectedMarket: "EUROPE", canonical: "ASML.AS", leadingZero: false },
    ];

    it.each(matrix)("resolves $input correctly with suffix scheme hint", ({ input, expectedMarket, canonical, leadingZero }) => {
      const res = parseGlobalEquityQuery(input);
      expect(res).not.toBeNull();
      expect(res!.market).toBe(expectedMarket);
      expect(res!.canonicalSymbol).toBe(canonical);
      expect(res!.leadingZeroPreserved).toBe(leadingZero);
      expect(res!.suffixHint).toBe(true);
      expect(res!.currency).toBe("UNAVAILABLE"); // Not assumed without admitted quote feed
    });
  });

  describe("Bare symbols and numeric tickers without market suffix", () => {
    it("preserves exact bare 4-digit and 6-digit numeric tickers as UNKNOWN market (no guessed TW/SZ/KS)", () => {
      // 2330 without suffix stays UNKNOWN; does NOT default to 2330.TW
      const res2330 = parseGlobalEquityQuery("2330");
      expect(res2330).not.toBeNull();
      expect(res2330!.market).toBe("UNKNOWN");
      expect(res2330!.canonicalSymbol).toBe("2330");

      // 7203 without suffix stays UNKNOWN; does NOT default to 7203.T
      const res7203 = parseGlobalEquityQuery("7203");
      expect(res7203).not.toBeNull();
      expect(res7203!.market).toBe("UNKNOWN");
      expect(res7203!.canonicalSymbol).toBe("7203");

      // 005930 preserves leading zeros and stays UNKNOWN; does NOT default to .KS or .SZ
      const resSamsung = parseGlobalEquityQuery("005930");
      expect(resSamsung).not.toBeNull();
      expect(resSamsung!.market).toBe("UNKNOWN");
      expect(resSamsung!.canonicalSymbol).toBe("005930");
      expect(resSamsung!.leadingZeroPreserved).toBe(true);

      // 000001 preserves leading zeros and stays UNKNOWN
      const resPingAn = parseGlobalEquityQuery("000001");
      expect(resPingAn).not.toBeNull();
      expect(resPingAn!.market).toBe("UNKNOWN");
      expect(resPingAn!.canonicalSymbol).toBe("000001");
      expect(resPingAn!.leadingZeroPreserved).toBe(true);
    });

    it("treats bare alphabetic tickers (AAPL, ASML, SIVE) as UNKNOWN market without unverified US assumption", () => {
      const resAAPL = parseGlobalEquityQuery("AAPL");
      expect(resAAPL).not.toBeNull();
      expect(resAAPL!.canonicalSymbol).toBe("AAPL");
      expect(resAAPL!.market).toBe("UNKNOWN");

      // Bare ASML is NOT forced to Euronext ASML.AS
      const resASML = parseGlobalEquityQuery("asml");
      expect(resASML).not.toBeNull();
      expect(resASML!.canonicalSymbol).toBe("ASML");
      expect(resASML!.market).toBe("UNKNOWN");
    });
  });

  describe("SIVE verification and absence of invented US OTC", () => {
    it.each(["sive", "Sive", "SIVE"])("identifies %s without invented US OTC candidates", (input) => {
      const res = parseGlobalEquityQuery(input);
      expect(res).not.toBeNull();
      expect(res!.canonicalSymbol).toBe("SIVE");
      expect(res!.market).toBe("UNKNOWN");
      expect(res!.exchange).not.toContain("US OTC");
      expect(res!.country).not.toContain("US OTC");
    });

    it("distinguishes bare SIVE from explicit Swedish scheme SIVE.ST", () => {
      const resBare = parseGlobalEquityQuery("sive");
      const resSweden = parseGlobalEquityQuery("SIVE.ST");

      expect(resBare!.canonicalSymbol).toBe("SIVE");
      expect(resBare!.market).toBe("UNKNOWN");

      expect(resSweden!.canonicalSymbol).toBe("SIVE.ST");
      expect(resSweden!.market).toBe("SWEDEN");
      expect(resSweden!.suffixHint).toBe(true);
    });
  });

  describe("Leading zero and share class preservation", () => {
    it("preserves leading zeros for HK, Korea, and China symbols", () => {
      expect(parseGlobalEquityQuery("0700.HK")?.canonicalSymbol).toBe("0700.HK");
      expect(parseGlobalEquityQuery("005930.KS")?.canonicalSymbol).toBe("005930.KS");
      expect(parseGlobalEquityQuery("000001.SZ")?.canonicalSymbol).toBe("000001.SZ");
    });

    it("preserves share classes such as BRK.A and BRK.B", () => {
      const resA = parseGlobalEquityQuery("BRK.A");
      expect(resA).not.toBeNull();
      expect(resA!.canonicalSymbol).toBe("BRK.A");
      expect(resA!.shareClass).toBe("A");

      const resB = parseGlobalEquityQuery("BRK.B");
      expect(resB).not.toBeNull();
      expect(resB!.canonicalSymbol).toBe("BRK.B");
      expect(resB!.shareClass).toBe("B");
    });
  });

  describe("Explicit lookup grammar vs genuine prose", () => {
    it("handles explicit lookup grammar", () => {
      expect(parseGlobalEquityQuery("股票 AAPL")?.canonicalSymbol).toBe("AAPL");
      expect(parseGlobalEquityQuery("個股 2330.TW")?.canonicalSymbol).toBe("2330.TW");
      expect(parseGlobalEquityQuery("查股價 0700.HK")?.canonicalSymbol).toBe("0700.HK");
      expect(parseGlobalEquityQuery("股票 台積電")?.canonicalSymbol).toBe("台積電");
      expect(parseGlobalEquityQuery("股票 台積電")?.isCompanyQuery).toBe(true);
    });

    it("rejects unprefixed Chinese company names from hardcoded whitelist (no static dictionary)", () => {
      // Without explicit grammar, bare Chinese text is NOT turned into equity lookup
      expect(parseGlobalEquityQuery("台積電")).toBeNull();
      expect(parseGlobalEquityQuery("蘋果")).toBeNull();
      expect(parseGlobalEquityQuery("微軟")).toBeNull();
      expect(parseGlobalEquityQuery("艾司摩爾")).toBeNull();
    });
  });

  describe("Negative tests (must NOT be treated as equity lookup)", () => {
    it.each([
      "TOP20",
      "TOP10",
      "宏觀產業分析",
      "TOP5產業總覽",
      "當輪產業分布",
      "期權",
      "最新期權",
      "期權教學",
      "選單",
      "幫助",
      "健康",
      "早報",
      "晚報",
    ])("preserves menu command '%s'", (cmd) => {
      expect(parseGlobalEquityQuery(cmd)).toBeNull();
    });

    it.each([
      "GDP",
      "CPI",
      "USD",
      "FOMC",
      "FED",
    ])("preserves ambiguous macro abbreviation '%s'", (macro) => {
      expect(parseGlobalEquityQuery(macro)).toBeNull();
    });

    it.each([
      "什麼是量化投資？",
      "今天天氣如何",
      "台積電的營收如何？",
      "請問台股明天會漲嗎",
    ])("does not turn arbitrary prose into equity lookup: '%s'", (prose) => {
      expect(parseGlobalEquityQuery(prose)).toBeNull();
    });

    it.each([
      "<script>alert(1)</script>",
      "http://evil.com/sive",
      "https://phishing.site/quote",
      "A".repeat(200),
      "123",
      "999999999",
    ])("rejects malicious or invalid inputs", (badInput) => {
      expect(parseGlobalEquityQuery(badInput)).toBeNull();
    });
  });

  describe("Presentation & Flex formatting", () => {
    it("builds compliant LINE Flex card for unavailable quote without fake data", () => {
      const identity = parseGlobalEquityQuery("sive")!;
      const result: EquityLookupResult = {
        identity,
        admittedInSealedSnapshot: false,
        nameUnverified: true,
        quoteStatus: "UNAVAILABLE",
        source: "unsealed_or_missing",
        disclaimer: "公開研究資訊，非投資建議。",
      };

      const messages = buildGlobalEquityLookupMessages(result, "flex");
      expect(messages).toHaveLength(1);
      expect(messages[0]!.type).toBe("flex");
      assertLineMessages(messages);

      const json = JSON.stringify(messages[0]);
      expect(json).toContain("SIVE");
      expect(json).toContain("QUOTE_UNAVAILABLE");
      expect(json).toContain("未完成來源核對");
      expect(json).not.toContain("AAPL");
      expect(json).not.toContain("US OTC");
    });

    it("builds compliant LINE Text messages for presentation=text", () => {
      const identity = parseGlobalEquityQuery("AAPL")!;
      const result: EquityLookupResult = {
        identity,
        admittedInSealedSnapshot: false,
        nameUnverified: true,
        quoteStatus: "UNAVAILABLE",
        source: "unsealed_or_missing",
        disclaimer: "公開研究資訊，非投資建議。",
      };

      const messages = buildGlobalEquityLookupMessages(result, "text");
      expect(messages).toHaveLength(1);
      expect(messages[0]!.type).toBe("text");
      assertLineMessages(messages);

      const text = (messages[0] as any).text;
      expect(text).toContain("個股快查 · AAPL");
      expect(text).toContain("QUOTE_UNAVAILABLE");
      expect(text).toContain("未完成來源核對");
    });

    it("enforces nameUnverified display over unverified Chinese names", () => {
      const identity = parseGlobalEquityQuery("AAPL")!;
      identity.canonicalNameZh = "蘋果公司（假定）";
      const result: EquityLookupResult = {
        identity,
        admittedInSealedSnapshot: false,
        nameUnverified: true,
        quoteStatus: "UNAVAILABLE",
        source: "unsealed_or_missing",
        disclaimer: "公開研究資訊，非投資建議。",
      };

      const messages = buildGlobalEquityLookupMessages(result, "text");
      const text = (messages[0] as any).text;
      expect(text).toContain("未完成來源核對（不猜譯）");
      expect(text).not.toContain("蘋果公司（假定）");
    });
  });
});
