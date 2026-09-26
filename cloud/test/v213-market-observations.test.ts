// Sealed delayed quotes and listed-option observations through the real LINE routes. Synthetic values only.
import { describe, expect, it } from "vitest";
import { parseQuery } from "../src/core";
import { handleGlobalEquityLookup } from "../src/v213/global-equity-lookup";
import { identityNameBucket, identitySymbolBucket } from "../src/v213/identity-shards";
import { observationSymbol, optionTickerKeys } from "../src/v213/market-observations";
import { v213PublicLineAnswer } from "../src/v213/rich-menu";
import { SNAPSHOT_SEAL_KEY } from "../src/v213/snapshot-seal";
import { asKv, MemoryKv } from "./fake-kv";
import { sealUnboundReport } from "./sealed-report-migration";

const RUN = "20260926T030000Z-abcdefabcde0";
const now = Date.now();
const stamp = new Date(now - 30 * 60_000).toISOString().replace(/\.\d{3}Z$/, "Z");
const expiry = new Date(now + 21 * 86400_000).toISOString().slice(0, 10);
const FEED = [{ id: "nasdaq-stockholm-main", url: "https://api.nasdaq.com/api/nordic/screener/shares?category=MAIN_MARKET&tableonly=false&market=STO",
  retrieved_at: stamp, sha256: "c".repeat(64), rows: 1 }];

async function sha(text: string): Promise<string> {
  const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(text));
  return Array.from(new Uint8Array(digest), byte => byte.toString(16).padStart(2, "0")).join("");
}

async function sealedEnv() {
  const kv = new MemoryKv();
  kv.values.set("v213:top20-report:latest", JSON.stringify({ synthetic: "report" }));
  kv.values.set("last_successful_pipeline_timestamp", new Date(now - 60_000).toISOString().replace(/\.\d{3}Z$/, "Z"));
  await sealUnboundReport(kv, RUN);
  const row = ["SIVE", "NASDAQ STOCKHOLM", "SWEDEN", "Sweden", "Sivers Semiconductors", null, "COMMON_STOCK", "SEK", 0];
  const lazy: Record<string, unknown> = {
    [`v213:identity:v2:sym:${identitySymbolBucket("SIVE")}`]: { schema: "v213-identity-shard-v2", kind: "symbol", bucket: "S", generated_at: stamp, feeds: FEED, rows: [row] },
    "v213:identity:v2:sym:A": { schema: "v213-identity-shard-v2", kind: "symbol", bucket: "A", generated_at: stamp, feeds: FEED, rows: [] },
    [`v213:identity:v2:name:${identityNameBucket("sivers semiconductors")}`]: { schema: "v213-identity-shard-v2", kind: "name",
      bucket: String(identityNameBucket("sivers semiconductors")), generated_at: stamp, rows: [["sivers semiconductors", "S", "SIVE", "NASDAQ STOCKHOLM"]] },
    "v213:quotes:v1": { schema: "v213-quotes-v1", generated_at: stamp, quotes: { "SIVE.ST": { symbol: "SIVE.ST", price: 32.78, previous_close: 31.5,
      change_pct: 0.0406, currency: "SEK", asof: stamp, source: "Yahoo Finance (unofficial, delayed)", source_url: "https://finance.yahoo.com/quote/SIVE.ST" } } },
    "v213:options:v2": { schema: "v213-options-v2", generated_at: stamp, options: {
      "VOLV-B.ST": { weekly: { unavailable: "合成：VOLV-B 週期權無雙邊報價" } },
      AZN: { weekly: { unavailable: "合成：美股 AZN 週期權" } },
      "AZN.ST": { weekly: { unavailable: "合成：斯德哥爾摩 AZN 週期權" } },
      SIVE: {  // the older unsuffixed Stockholm key still answers a bare SIVE
      weekly: { unavailable: "Nasdaq Stockholm 無 3-14 天到期的上市期權" },
      monthly: { ticker: "SIVE", strategy: "COVERED_CALL", expiry, dte: 21, spot: 32.78, currency: "SEK", multiplier: 100,
        quote_basis: "delayed", timestamp: stamp, source: "Nasdaq Nordic option chain (exchange public web API, delayed)",
        provenance: "https://api.nasdaq.com/api/nordic/instruments/TX2540138/option-chain", rights_status: "candidate_local_review",
        suggestions: [
          { role: "HIGH_STRIKE", strike: 62, bid: 0.2, ask: 0.35, mid: 0.275, limit_price: 0.23, premium_per_contract: 23,
            period_yield: 0.23 / 32.78, annualized_yield: 0.23 / 32.78 * 365 / 21, upside_to_strike: 62 / 32.78 - 1,
            delta: null, iv: null, oi: 12, volume: null, spread_pct: 0.5455 },
          { role: "BALANCED", strike: 34, bid: 1.5, ask: 4.5, mid: 3, limit_price: 2.25, premium_per_contract: 225,
            period_yield: 2.25 / 32.78, annualized_yield: 2.25 / 32.78 * 365 / 21, upside_to_strike: 34 / 32.78 - 1,
            delta: null, iv: null, oi: 16, volume: null, spread_pct: 1 },
        ] },
    } } },
  };
  const sealKey = `snapshot:${RUN}:${SNAPSHOT_SEAL_KEY}`;
  const seal = JSON.parse(kv.values.get(sealKey)!);
  for (const [key, value] of Object.entries(lazy)) {
    const body = JSON.stringify(value);
    const digest = await sha(body);
    seal.objects[key] = { sha256: digest, utf8_bytes: new TextEncoder().encode(body).byteLength };
    kv.values.set(`blob:v1:${digest}`, body);
  }
  const sealText = JSON.stringify(seal);
  kv.values.set(sealKey, sealText);
  const pointer = JSON.parse(kv.values.get("snapshot:current")!);
  pointer.seal_sha256 = await sha(sealText);
  kv.values.set("snapshot:current", JSON.stringify(pointer));
  return { PUBLIC_CACHE: asKv(kv), TENANT_PRIVATE_CACHE: asKv(new MemoryKv()), EPHEMERAL_SECURITY_CACHE: asKv(new MemoryKv()),
    V21_TOP20_MAX_AGE_SECONDS: "7200", V213_LINE_PRESENTATION: "text" };
}

describe("sealed market observations", () => {
  it("maps listings to observation symbols", () => {
    expect(observationSymbol({ symbol: "SIVE", market: "SWEDEN", venue: "NASDAQ STOCKHOLM" })).toBe("SIVE.ST");
    expect(observationSymbol({ symbol: "5351", market: "TAIWAN", venue: "TPEX" })).toBe("5351.TWO");
    expect(observationSymbol({ symbol: "2330", market: "TAIWAN", venue: "TWSE" })).toBe("2330.TW");
    expect(observationSymbol({ symbol: "NVDA", market: "US", venue: "NASDAQ" })).toBe("NVDA");
    expect(observationSymbol({ symbol: "4062", market: "JAPAN", venue: "TSE" })).toBe("4062.T");
    expect(observationSymbol({ symbol: "005930", market: "KOREA", venue: "KRX" })).toBe("005930.KS");
    expect(observationSymbol({ symbol: "SOI", market: "EUROPE", venue: "EURONEXT PARIS" })).toBe("SOI.PA");
  });

  it("answers SIVE monthly options with the SEK observation and weekly with the exchange reason", async () => {
    const env = await sealedEnv();
    const monthly = await v213PublicLineAnswer(env as never, parseQuery("SIVE 每月期權")) as { text: string }[];
    expect(monthly[0]!.text).toContain("SIVE");
    expect(monthly[0]!.text).toContain("備兌買權建議");
    expect(monthly[0]!.text).toContain("62.00 SEK");
    expect(monthly[0]!.text).toContain("建議賣出限價 0.23 SEK");
    expect(monthly[0]!.text).toContain("每口權利金 225.00 SEK");
    expect(monthly[0]!.text).toContain("Nasdaq Nordic");
    expect(monthly[0]!.text).not.toContain("UNAVAILABLE");
    const weekly = JSON.stringify(await v213PublicLineAnswer(env as never, parseQuery("SIVE 每週期權")));
    expect(weekly).toContain("無 3-14 天到期的上市期權");
  });

  it("maps typed and looked-up tickers to option keys", () => {
    expect(optionTickerKeys("SIVE.ST")).toEqual(["SIVE.ST"]);
    expect(optionTickerKeys("volv b")).toEqual(["VOLV-B", "VOLV-B.ST"]);
    expect(optionTickerKeys("BRK.B")).toEqual(["BRK-B", "BRK-B.ST"]);
    expect(optionTickerKeys("BRK/B")).toEqual(["BRK-B", "BRK-B.ST"]);
    expect(optionTickerKeys("AZN")).toEqual(["AZN", "AZN.ST"]);
  });

  it("answers share classes, keeps US and Stockholm listings apart and is not taken by the stock lookup", async () => {
    const env = await sealedEnv();
    const expected: [string, string][] = [
      ["VOLV B 每週期權", "VOLV-B 週期權無雙邊報價"], ["期權 VOLV B 每週", "VOLV-B 週期權無雙邊報價"],
      ["VOLV-B.ST 每週期權", "VOLV-B 週期權無雙邊報價"], ["AZN 每週期權", "美股 AZN 週期權"], ["AZN.ST 每週期權", "斯德哥爾摩 AZN 週期權"],
    ];
    for (const [text, reason] of expected) {
      expect(await handleGlobalEquityLookup(env as never, parseQuery(text))).toBeNull();  // the Worker asks the lookup first
      expect(JSON.stringify(await v213PublicLineAnswer(env as never, parseQuery(text)))).toContain(reason);
    }
    // An explicit Stockholm suffix never falls back to another key (here only the older unsuffixed SIVE exists).
    expect(JSON.stringify(await v213PublicLineAnswer(env as never, parseQuery("SIVE.ST 每月期權")))).not.toContain("0.23 SEK");
    const weekly = JSON.stringify(await v213PublicLineAnswer(env as never, parseQuery("NVDA weekly options")));
    expect(weekly).toContain("OPTION_DATA_NOT_ADMITTED");  // no observation for NVDA in this fixture
  });

  it("offers the Stockholm listing's own options from the stock lookup", async () => {
    const env = { ...(await sealedEnv()), V213_LINE_PRESENTATION: "flex" };
    const card = JSON.stringify(await handleGlobalEquityLookup(env as never, parseQuery("SIVE")));
    expect(card).toContain("SIVE.ST 每月期權");
    expect(card).toContain("SIVE.ST 每週期權");
  });

  it("shows the delayed quote on the stock lookup", async () => {
    const env = await sealedEnv();
    const answer = await handleGlobalEquityLookup(env as never, parseQuery("SIVE")) as { text: string }[];
    expect(answer[0]!.text).toContain("延遲報價");
    expect(answer[0]!.text).toContain("32.78");
    expect(answer[0]!.text).toContain("+4.06%");
  });
});
