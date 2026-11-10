// Synthetic offline metadata; not a market capture or admission override.
import { describe, expect, it } from "vitest";
import {
  historicalDeltaBasisZh, validHistoricalVolatility, type HistoricalVolatility,
} from "../src/v213/historical-volatility";

const CAPTURE = "2026-11-09";
const SOURCE = "https://query1.finance.yahoo.com/v8/finance/chart/NVDA";
function evidence(): HistoricalVolatility {
  return {
    ticker: "NVDA", currency: "USD", hv20: 0.42, hv60: 0.38, observations: 61,
    start_date_20: "2026-10-09", start_date_60: "2026-08-14", asof_date: "2026-11-06",
    source_url: `${SOURCE}?period1=1&period2=2&interval=1d&events=history&includeAdjustedClose=true`,
    source_sha256: "abcdef0123456789".repeat(4), price_basis: "PROVIDER_ADJUSTED_CLOSE",
  };
}
function accepts(value: unknown, capture = CAPTURE): boolean {
  return validHistoricalVolatility(value, "NVDA", "USD", capture);
}

describe("source-bound HV20/HV60 metadata", () => {
  it("accepts both windows from 61 closes and discloses the applied model", () => {
    const value = evidence();
    expect(accepts(value)).toBe(true);
    const label = historicalDeltaBasisZh(value, 0.4);
    expect(label).toContain("Delta 以標的歷史波動率估算");
    expect(label).toMatch(/20\s*(?:個)?交易日/);
    expect(label).toMatch(/60\s*(?:個)?交易日/);
    expect(label).toMatch(/HV20\s*42(?:\.0+)?%/);
    expect(label).toMatch(/HV60\s*38(?:\.0+)?%/);
    expect(label).toMatch(/最終套用波動率\s*40(?:\.0+)?%/);
    expect(label).toContain(value.asof_date);
    expect(label).toContain("最後收盤日");
    expect(label).toContain("模型估算");
    expect(label).toContain("非報價中價反推");
    expect(label).toContain("買賣報價隱含波動率區間約束");
  });

  it("retains true zero variance instead of treating it as missing history", () => {
    expect(accepts({ ...evidence(), hv20: 0, hv60: 0 })).toBe(true);
  });

  it("accepts exact Swedish identity and explicit HTTPS port", () => {
    const value = { ...evidence(), ticker: "SIVE.ST", currency: "SEK",
      source_url: "https://query1.finance.yahoo.com:443/v8/finance/chart/SIVE.ST?range=6mo&interval=1d" };
    expect(validHistoricalVolatility(value, "SIVE.ST", "SEK", CAPTURE)).toBe(true);
    expect(validHistoricalVolatility(value, "sive.st", "SEK", CAPTURE)).toBe(false);
    expect(validHistoricalVolatility(value, "SIVE.ST", "USD", CAPTURE)).toBe(false);
    expect(validHistoricalVolatility({ ...value, currency: "EUR" }, "SIVE.ST", "EUR", CAPTURE)).toBe(false);
  });

  it.each(["", " NVDA", "NVDA ", ".NVDA", "NV..DA", "NV/DA", "NVDA?", "A".repeat(33)])("rejects invalid identity %s even when it matches", ticker => {
    expect(validHistoricalVolatility({ ...evidence(), ticker, source_url: SOURCE.replace("NVDA", ticker) }, ticker, "USD", CAPTURE)).toBe(false);
  });

  it.each<[string, unknown]>([
    ["ticker", "AMD"], ["ticker", "nvda"], ["currency", "SEK"], ["currency", "usd"],
    ["hv20", NaN], ["hv20", Infinity], ["hv20", -Infinity], ["hv20", -0.2], ["hv20", true], ["hv20", "0.42"],
    ["hv60", NaN], ["hv60", Infinity], ["hv60", -0.2], ["hv60", true], ["hv60", "0.38"],
    ["observations", 21], ["observations", 60], ["observations", 61.5], ["observations", true],
    ["observations", "61"], ["observations", NaN], ["price_basis", "CLOSE"], ["price_basis", true],
    ["source_sha256", "A".repeat(64)], ["source_sha256", "g".repeat(64)],
    ["source_sha256", "a".repeat(63)], ["source_sha256", "a".repeat(65)], ["source_sha256", true],
    ["start_date_20", "2026-02-30"], ["start_date_20", "2026-10-9"], ["start_date_20", "0000-10-09"],
    ["start_date_20", "2026-10-09T00:00:00Z"], ["start_date_20", "2026-11-06"],
    ["start_date_20", "2026-11-09"], ["start_date_20", "2026-01-01"], ["start_date_20", true],
    ["start_date_20", "2026-10-10"], ["start_date_60", "2026-10-09"], ["start_date_60", "2026-06-01"],
    ["start_date_60", "2026-08-15"], ["start_date_60", true], ["asof_date", "2026-11-07"],
    ["asof_date", "2026-11-31"], ["asof_date", "2026-11-09"], ["asof_date", "2026-11-10"],
    ["asof_date", "2026-11-04"], ["asof_date", true], ["source_url", true],
  ])("rejects invalid %s value %s", (key, value) => {
    expect(accepts({ ...evidence(), [key]: value })).toBe(false);
  });

  it.each([null, undefined, true, 1, "metadata", [], {}])("rejects non-contract shape %s", value => {
    expect(accepts(value)).toBe(false);
  });

  it("requires both windows and exactly eleven own keys, not inherited or extra keys", () => {
    const value = evidence();
    for (const key of Object.keys(value)) {
      const missing = Object.fromEntries(Object.entries(value).filter(([name]) => name !== key));
      expect(accepts(missing)).toBe(false);
    }
    expect(accepts({ ...value, annualized_volatility: 0.42, window_sessions: 20 })).toBe(false);
    expect(accepts({ ...value, [Symbol("extra")]: 1 })).toBe(false);
    expect(accepts(Object.create(value))).toBe(false);
  });

  it.each(["2026-11-07", "2026-11-08", "2026-11-09", "2026-11-10"])("accepts completed history age 1..4 at %s", capture => {
    expect(accepts(evidence(), capture)).toBe(true);
  });
  it.each(["2026-11-06", "2026-11-05", "2026-11-11", "2026-02-30", "2026-11-9", "2026-11-09T00:00:00Z", "0000-11-09"])("rejects invalid capture/age %s", capture => {
    expect(accepts(evidence(), capture)).toBe(false);
  });

  it("accepts real leap dates but rejects normalized non-leap dates", () => {
    const value = { ...evidence(), start_date_60: "2024-01-04", start_date_20: "2024-02-29", asof_date: "2024-03-28" };
    expect(accepts(value, "2024-03-29")).toBe(true);
    expect(accepts({ ...value, start_date_60: "2023-01-04", start_date_20: "2023-02-29", asof_date: "2023-03-28" }, "2023-03-29")).toBe(false);
  });

  it.each([
    SOURCE.replace("https:", "http:"), SOURCE.replace("query1.", "query2."),
    SOURCE.replace("yahoo.com", "yahoo.com.evil.example"), SOURCE.replace("NVDA", "AMD"),
    SOURCE.replace("NVDA", "%4eVDA"), SOURCE.replace("/NVDA", "/other/../NVDA"),
    SOURCE.replace("https://", "https://user:secret@"), SOURCE.replace(".com/", ".com:444/"),
    `${SOURCE}#fragment`, `${SOURCE}#`, `${SOURCE}/`, ` ${SOURCE}`, `${SOURCE}\n`,
    SOURCE.replace("/v8/", "\\v8/"), `${SOURCE}?token=TEST_PLACEHOLDER`, `${SOURCE}?${["api", "key"].join("_")}=placeholder`,
    `${SOURCE}?interval=1d&credential=secret`, `${SOURCE}?constructor=x`, `${SOURCE}?__proto__=x`,
  ])("rejects untrusted chart URL %s", source_url => {
    expect(accepts({ ...evidence(), source_url })).toBe(false);
  });

  it("allows the public chart URL without query parameters", () => {
    expect(accepts({ ...evidence(), source_url: SOURCE })).toBe(true);
  });
});
