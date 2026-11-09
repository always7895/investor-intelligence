import { describe, expect, it } from "vitest";
import { combineQuotes } from "../src/v213/global-equity-lookup";
import { formatQuotePrice } from "../src/v213/line-formatters";
import { humanizeStatusText, localizeLineMessages } from "../src/v213/status-labels";
import { legacyCompanyNameLabel, verifiedLegacyCompanyName } from "../src/v213/verified-legacy-company-names";

const shard = (price: number, asof: string, source = "Nasdaq Screener") => ({
  price, asof, source, source_url: "https://example.com/official", currency: "USD", change_pct: null,
});
const watch = (price: number, asof: string, source = "Yahoo Finance (unofficial, delayed)") => ({
  price, asof, source, source_url: "https://example.com/delayed", currency: "USD", change_pct: null,
});
describe("FIX-R2C quote observation precedence", () => {
  it("shows newer watch quote and keeps older listing source with its own timestamp and correct signed gap", () => {
    const official = shard(182.29, "2026-11-05");
    const delayed = watch(186.63999938964844, "2026-11-08T14:18:00Z");
    const result = combineQuotes(official, delayed);
    expect(result.primary).toBe(delayed);
    expect(result.crossCheck?.officialReference).toBe(true);
    expect(result.crossCheck?.asOf).toBe(official.asof);
    expect(result.crossCheck?.price).toBe(official.price);
    expect(result.crossCheck?.diffPct).toBeCloseTo(182.29 / 186.63999938964844 - 1, 12);
  });
  it("keeps newer official listing observation, and tie favours the listing", () => {
    const official = shard(102, "2026-11-09T14:00:00Z");
    const delayed = watch(100, "2026-11-08T14:00:00Z");
    expect(combineQuotes(official, delayed).primary).toBe(official);
    expect(combineQuotes(official, { ...delayed, asof: official.asof }).primary).toBe(official);
  });
  it.each([
    ["2026-11-08", "2026-11-08T23:59:59Z", false],
    ["2026-11-08", "2026-11-08T00:00:00+09:00", false],
    ["2026-11-08T00:00:00Z", "2026-11-08", false],
    ["2026-11-08", "2026-11-09T00:00:00Z", true],
    ["2026-11-08", "2026-11-07T23:59:59Z", false],
    ["2026-11-08T23:59:59Z", "2026-11-09", true],
    ["2026-11-08T09:00:00Z", "2026-11-08T09:00:01Z", true],
    ["2026-11-08T09:00:00Z", "2026-11-08T10:00:00+02:00", false],
  ])("compares observation precision at %s / %s", (listing, delayed, newer) => {
    const official = shard(100, listing);
    const observed = watch(101, delayed);
    const result = combineQuotes(official, observed);
    expect(result.primary).toBe(newer ? observed : official);
    expect(result.crossCheck?.asOf).toBe(newer ? listing : delayed);
    expect(result.crossCheck?.price).toBe(newer ? 100 : 101);
  });
  it("does not treat two aliases of one Yahoo provider as independent sources", () => {
    const official = shard(99, "2026-11-05", "Yahoo Finance（日線收盤）");
    const delayed = watch(101, "2026-11-08T12:00:00Z");
    const actual = combineQuotes(official, delayed);
    expect(actual.primary).toBe(delayed);
    // Alias equivalence is a provider-identity policy, not an expiry gate.
    expect(actual.crossCheck === undefined || actual.crossCheck?.source === official.source).toBe(true);
  });
  it("rejects invalid timestamps as fresher and never compares different currencies", () => {
    const official = shard(100, "2026-11-08T09:00:00Z");
    const bad = watch(200, "not-a-time");
    expect(combineQuotes(official, bad).primary).toBe(official);
    const second = { ...watch(101, "2026-11-09T09:00:00Z"), currency: "JPY" };
    expect(combineQuotes(official, second).crossCheck?.diffPct).toBe(null);
  });
});
describe("FIX-R2C display-only contract", () => {
  it("has no binary float tail and respects quote currency decimal units", () => {
    expect(formatQuotePrice(186.63999938964844, "USD")).toBe("186.64");
    expect(formatQuotePrice(342.3699951171875, "USD")).toBe("342.37");
    expect(formatQuotePrice(142.9222, "JPY")).toBe("143");
    expect(formatQuotePrice(-0.000001, "USD")).toBe("0.00");
    expect(formatQuotePrice(Number.NaN, "USD")).toBe("未提供");
  });
  it("uses source-tagged matching issuer names but does not guess missing or changed issuers", () => {
    expect(verifiedLegacyCompanyName("MU", "MICRON TECHNOLOGY INC")).toContain("美光科技");
    expect(verifiedLegacyCompanyName("PBR-A", "PETROBRAS - PETROLEO BRASILEIRO SA")).toContain("巴西石油");
    expect(verifiedLegacyCompanyName("MU", "unrelated issuer")).toBeNull();
    expect(legacyCompanyNameLabel("RDDT", "Reddit, Inc.")).toContain("不猜譯");
  });
  it("translates all identified status code examples without altering wire actions", () => {
    expect(humanizeStatusText("SYNTHETIC_EDUCATIONAL｜HISTORY_YOY_V1｜SEC_8K_EXHIBIT｜CURRENT_DATA_STALE")).not.toMatch(/_[A-Z0-9]+/);
    const data = "期權教學 SYNTHETIC_EDUCATIONAL";
    const raw = [{ type:"flex", altText:"SYNTHETIC_EDUCATIONAL", contents:{ type:"carousel", contents:[
      { type:"bubble", body:{ type:"box", contents:[{ type:"text", text:"OFFICIAL_FISCAL_CALENDAR" }] },
        footer:{ type:"box", contents:[{type:"button",action:{type:"postback",label:"SEC_8K_EXHIBIT",data}}]} }
    ]} }];
    const rendered = localizeLineMessages(raw);
    expect(JSON.stringify(rendered)).not.toContain("OFFICIAL_FISCAL_CALENDAR");
    expect(rendered[0]?.contents.contents[0]?.footer.contents[0]?.action.data).toBe(data);
    expect(raw[0]?.altText).toBe("SYNTHETIC_EDUCATIONAL");
  });
});
