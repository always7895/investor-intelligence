// Stock lookup price sources (operator 2026-09-26: a lookup showed Yahoo only): the exchange feed leads and a second,
// independent observation is shown beside it.
import { describe, expect, it } from "vitest";
import { buildGlobalEquityLookupMessages, combineQuotes, type EquityLookupResult } from "../src/v213/global-equity-lookup";

const exchange = { price: 32.78, change_pct: 0.012, currency: "SEK", asof: "2026-09-25", source: "Nasdaq Nordic 斯德哥爾摩（延遲）", source_url: "https://api.nasdaq.com/api/nordic/" };
const yahoo = { price: 32.9, change_pct: 0.015, currency: "SEK", asof: "2026-09-26T10:39:05Z", source: "Yahoo Finance (unofficial, delayed)", source_url: "https://finance.yahoo.com/quote/SIVE.ST" };

describe("quote cross-check", () => {
  it("leads with the exchange feed and compares a different source in the same currency", () => {
    const { primary, crossCheck } = combineQuotes(exchange, yahoo);
    expect(primary).toBe(exchange);
    expect(crossCheck!.diffPct).toBeCloseTo(32.9 / 32.78 - 1, 6);
    expect(combineQuotes(null, yahoo)).toEqual({ primary: yahoo });  // one source: shown as the only one
    expect(combineQuotes(exchange, { ...yahoo, source: exchange.source }).crossCheck).toBeUndefined();  // not independent
    expect(combineQuotes(exchange, { ...yahoo, currency: "GBp" }).crossCheck!.diffPct).toBeNull();  // no unit mixing
  });

  it("shows both sources in the lookup answer", () => {
    const { primary, crossCheck } = combineQuotes(exchange, yahoo);
    const result: EquityLookupResult = {
      identity: { rawInput: "SIVE", normalizedSymbol: "SIVE", canonicalSymbol: "SIVE", market: "SWEDEN", country: "瑞典", exchange: "NASDAQ STOCKHOLM（瑞典）",
        currency: "SEK", isAmbiguous: false, leadingZeroPreserved: false },
      admittedInSealedSnapshot: true, nameUnverified: true, quoteStatus: "AVAILABLE", price: primary!.price, changePct: primary!.change_pct ?? undefined,
      asOf: primary!.asof, priceSource: primary!.source, crossCheck, source: "sealed_snapshot:x", disclaimer: "公開研究資訊",
      resolution: { status: "RESOLVED" } as any,
    };
    const text = (buildGlobalEquityLookupMessages(result, "text") as { text: string }[])[0]!.text;
    expect(text).toContain("價格 32.78 SEK（+1.20%），來源 Nasdaq Nordic 斯德哥爾摩（延遲）");
    expect(text).toContain("交叉比對：Yahoo Finance（非官方，延遲） 32.9（差 +0.37%");
    expect(text).not.toContain("差異超過 5%");
    const far = combineQuotes(exchange, { ...yahoo, price: 36.0 });
    const farText = (buildGlobalEquityLookupMessages({ ...result, crossCheck: far.crossCheck }, "text") as { text: string }[])[0]!.text;
    expect(farText).toContain("差異超過 5%，請以交易所價格為準");
  });
});
