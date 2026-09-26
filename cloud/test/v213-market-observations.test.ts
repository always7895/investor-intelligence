// Sealed delayed quotes and listed-option observations through the real LINE routes. Synthetic values only.
import { describe, expect, it } from "vitest";
import { parseQuery } from "../src/core";
import { handleGlobalEquityLookup } from "../src/v213/global-equity-lookup";
import { identityNameBucket, identitySymbolBucket } from "../src/v213/identity-shards";
import { observationSymbol } from "../src/v213/market-observations";
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
    "v213:options:v1": { schema: "v213-options-v1", generated_at: stamp, options: { SIVE: {
      weekly: { unavailable: "Nasdaq Stockholm 無 3-14 天到期的上市期權" },
      monthly: { ticker: "SIVE", expiry, dte: 21, strike: 36, type: "call", bid: 0.8, mid: 2.3, ask: 3.8, spread: 3, delta: null, iv: null,
        oi: 16, volume: null, breakeven: null, maxprofit: null, maxloss: null, annualized_yield: null, assignment_risk: "美式期權可能提前指派",
        liquidity_warning: "價差大", timestamp: stamp, quote_basis: "delayed", source: "Nasdaq Nordic option chain (exchange public web API, delayed)",
        provenance: "https://api.nasdaq.com/api/nordic/instruments/TX2540138/option-chain", currency: "SEK", multiplier: 100, rights_status: "candidate_local_review" },
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
    expect(monthly[0]!.text).toContain("0.80 SEK");
    expect(monthly[0]!.text).toContain("Nasdaq Nordic");
    const weekly = JSON.stringify(await v213PublicLineAnswer(env as never, parseQuery("SIVE 每週期權")));
    expect(weekly).toContain("無 3-14 天到期的上市期權");
  });

  it("shows the delayed quote on the stock lookup", async () => {
    const env = await sealedEnv();
    const answer = await handleGlobalEquityLookup(env as never, parseQuery("SIVE")) as { text: string }[];
    expect(answer[0]!.text).toContain("延遲報價");
    expect(answer[0]!.text).toContain("32.78");
    expect(answer[0]!.text).toContain("+4.06%");
  });
});
