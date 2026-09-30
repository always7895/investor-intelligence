// Sealed delayed quotes and listed-option observations through the real LINE routes. Synthetic values only.
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { parseQuery } from "../src/core";
import { handleGlobalEquityLookup } from "../src/v213/global-equity-lookup";
import { identityNameBucket, identitySymbolBucket } from "../src/v213/identity-shards";
import { observationSymbol, optionTickerKeys, loadOptionObservation, loadDelayedQuote } from "../src/v213/market-observations";
import { pinPublicSnapshot } from "../src/v213/public-snapshot";
import { v213PublicLineAnswer } from "../src/v213/rich-menu";
import { SNAPSHOT_SEAL_KEY } from "../src/v213/snapshot-seal";
import { asKv, MemoryKv } from "./fake-kv";
import { sealUnboundReport } from "./sealed-report-migration";

const RUN = "20260926T030000Z-abcdefabcde0";
const FIXED_NOW = new Date("2026-09-28T12:00:00.000Z").getTime();

class TrackingMemoryKv extends MemoryKv {
  readKeys: string[] = [];

  override async get<T = string>(key: string, type?: "text" | "json"): Promise<T | string | null> {
    this.readKeys.push(key);
    return super.get<T>(key, type);
  }
}

async function sha(text: string): Promise<string> {
  const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(text));
  return Array.from(new Uint8Array(digest), byte => byte.toString(16).padStart(2, "0")).join("");
}

async function sealedEnv(options: {
  nowMs?: number;
  observationGeneratedAt?: string;
  omitObservations?: boolean;
  withPriceShard?: boolean;
  legacyKvKeys?: Record<string, string>;
  kv?: MemoryKv;
} = {}) {
  const currentNow = options.nowMs ?? FIXED_NOW;
  const stamp = new Date(currentNow - 30 * 60_000).toISOString().replace(/\.\d{3}Z$/, "Z");
  const expiry = new Date(currentNow + 21 * 86400_000).toISOString().slice(0, 10);
  const feed = [{ id: "nasdaq-stockholm-main", url: "https://api.nasdaq.com/api/nordic/screener/shares?category=MAIN_MARKET&tableonly=false&market=STO",
    retrieved_at: stamp, sha256: "c".repeat(64), rows: 1 }];
  const kv = options.kv ?? new MemoryKv();
  kv.values.set("v213:top20-report:latest", JSON.stringify({ synthetic: "report" }));
  kv.values.set("last_successful_pipeline_timestamp", new Date(currentNow - 60_000).toISOString().replace(/\.\d{3}Z$/, "Z"));
  if (options.legacyKvKeys) {
    for (const [k, v] of Object.entries(options.legacyKvKeys)) {
      kv.values.set(k, v);
    }
  }
  await sealUnboundReport(kv, RUN);
  const row = ["SIVE", "NASDAQ STOCKHOLM", "SWEDEN", "Sweden", "Sivers Semiconductors", null, "COMMON_STOCK", "SEK", 0];
  const obsStamp = options.observationGeneratedAt ?? stamp;
  const lazy: Record<string, unknown> = {
    [`v213:identity:v2:sym:${identitySymbolBucket("SIVE")}`]: { schema: "v213-identity-shard-v2", kind: "symbol", bucket: "S", generated_at: stamp, feeds: feed, rows: [row] },
    "v213:identity:v2:sym:A": { schema: "v213-identity-shard-v2", kind: "symbol", bucket: "A", generated_at: stamp, feeds: feed, rows: [] },
    [`v213:identity:v2:name:${identityNameBucket("sivers semiconductors")}`]: { schema: "v213-identity-shard-v2", kind: "name",
      bucket: String(identityNameBucket("sivers semiconductors")), generated_at: stamp, rows: [["sivers semiconductors", "S", "SIVE", "NASDAQ STOCKHOLM"]] },
  };
  if (!options.omitObservations) {
    lazy["v213:quotes:v1"] = { schema: "v213-quotes-v1", generated_at: obsStamp, quotes: { "SIVE.ST": { symbol: "SIVE.ST", price: 32.78, previous_close: 31.5,
      change_pct: 0.0406, currency: "SEK", asof: obsStamp, source: "Yahoo Finance (unofficial, delayed)", source_url: "https://finance.yahoo.com/quote/SIVE.ST" } } };
    lazy["v213:options:v2"] = { schema: "v213-options-v2", generated_at: obsStamp, options: {
      "VOLV-B.ST": { weekly: { unavailable: "合成：VOLV-B 週期權無雙邊報價" } },
      AZN: { weekly: { unavailable: "合成：美股 AZN 週期權" } },
      "AZN.ST": { weekly: { unavailable: "合成：斯德哥爾摩 AZN 週期權" } },
      SIVE: {  // the older unsuffixed Stockholm key still answers a bare SIVE
      weekly: { unavailable: "Nasdaq Stockholm 無 3-14 天到期的上市期權" },
      monthly: { ticker: "SIVE", strategy: "COVERED_CALL", expiry, dte: 21, spot: 32.78, currency: "SEK", multiplier: 100,
        quote_basis: "delayed", timestamp: obsStamp, source: "Nasdaq Nordic option chain (exchange public web API, delayed)",
        provenance: "https://api.nasdaq.com/api/nordic/instruments/TX2540138/option-chain", rights_status: "candidate_local_review",
        suggestions: [
          { role: "HIGH_STRIKE", strike: 62, bid: 0.2, ask: 0.35, mid: 0.275, limit_price: 0.23, premium_per_contract: 23,
            period_yield: 0.23 / 32.78, annualized_yield: 0.23 / 32.78 * 365 / 21, upside_to_strike: 62 / 32.78 - 1,
            delta: 0.061, delta_basis: "QUOTE_IMPLIED", iv: 1.5658, oi: 12, volume: null, spread_pct: 0.5455 },
          { role: "BALANCED", strike: 34, bid: 1.5, ask: 4.5, mid: 3, limit_price: 2.25, premium_per_contract: 225,
            period_yield: 2.25 / 32.78, annualized_yield: 2.25 / 32.78 * 365 / 21, upside_to_strike: 34 / 32.78 - 1,
            delta: null, iv: null, oi: 16, volume: null, spread_pct: 1 },
        ] },
    } } };
  }
  if (options.withPriceShard) {
    lazy["v213:prices:v1:SWEDEN"] = {
      schema: "v213-price-shard-v1",
      market: "SWEDEN",
      generated_at: stamp,
      sources: [{ id: "nasdaq-stockholm-main", url: "https://api.nasdaq.com/api/nordic/screener/shares" }],
      rows: { "SIVE": [35.50, 2.5, stamp.slice(0, 10), "SEK", 0] },
    };
  }
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
  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(FIXED_NOW);
  });

  afterEach(() => {
    vi.useRealTimers();
  });
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
    expect(weekly).toContain("本輪封存快照未包含 NVDA 之期權觀察");  // no observation for NVDA in this fixture
    expect(weekly).not.toContain("OPTION_DATA_NOT_ADMITTED");
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

  it("renders original source, timestamp and prices when observation is within 6h", async () => {
    const fixedStamp = new Date(FIXED_NOW - 5.5 * 3600_000).toISOString().replace(/\.\d{3}Z$/, "Z");
    const env = await sealedEnv({ observationGeneratedAt: fixedStamp });
    const monthly = await v213PublicLineAnswer(env as never, parseQuery("SIVE 每月期權")) as { text: string }[];
    expect(monthly[0]!.text).toContain("62.00 SEK");
    expect(monthly[0]!.text).toContain("建議賣出限價 0.23 SEK");
    expect(monthly[0]!.text).toContain("每口權利金 225.00 SEK");
    expect(monthly[0]!.text).toContain("Nasdaq Nordic");
    expect(monthly[0]!.text).toContain(fixedStamp);
    expect(monthly[0]!.text).toContain("https://api.nasdaq.com/api/nordic/instruments/TX2540138/option-chain");
    expect(monthly[0]!.text).not.toContain("UNAVAILABLE");
  });

  it("exercises actual option route at exactly 6h boundary and 6h + 1s", async () => {
    const boundaryStamp = new Date(FIXED_NOW - 6 * 3600_000).toISOString().replace(/\.\d{3}Z$/, "Z");
    const env = await sealedEnv({ observationGeneratedAt: boundaryStamp });
    const view = await pinPublicSnapshot(env as never);

    // Exactly 6h: allowed on actual option route and helper
    const at6hAnswer = await v213PublicLineAnswer(env as never, parseQuery("SIVE 每月期權")) as { text: string }[];
    expect(at6hAnswer[0]!.text).toContain("62.00 SEK");
    expect(at6hAnswer[0]!.text).toContain("建議賣出限價 0.23 SEK");
    expect(at6hAnswer[0]!.text).not.toContain("OPTION_DATA_UNAVAILABLE");

    const at6hHelper = await loadOptionObservation(view, "SIVE", "monthly", FIXED_NOW);
    expect(at6hHelper).not.toBeNull();
    expect((at6hHelper as { quote: { suggestions: unknown[] } }).quote.suggestions).toHaveLength(2);

    // 6h + 1s (FIXED_NOW + 1000): rejected on actual option route and helper
    vi.setSystemTime(FIXED_NOW + 1000);

    const past6hAnswer = JSON.stringify(await v213PublicLineAnswer(env as never, parseQuery("SIVE 每月期權")));
    expect(past6hAnswer).toContain("OPTION_DATA_UNAVAILABLE");
    expect(past6hAnswer).not.toContain("62.00 SEK");

    const past6hHelper = await loadOptionObservation(view, "SIVE", "monthly", FIXED_NOW + 1000);
    expect(past6hHelper).toBeNull();
  });

  it("yields no suggestion and unavailable delayed quote when observation is older than 6h", async () => {
    const expiredStamp = new Date(FIXED_NOW - (6 * 3600_000 + 10_000)).toISOString().replace(/\.\d{3}Z$/, "Z");
    const env = await sealedEnv({ observationGeneratedAt: expiredStamp });
    const view = await pinPublicSnapshot(env as never);

    // Real option route returns unavailability
    const optionAns = JSON.stringify(await v213PublicLineAnswer(env as never, parseQuery("SIVE 每月期權")));
    expect(optionAns).toContain("OPTION_DATA_UNAVAILABLE");
    expect(optionAns).not.toContain("62.00 SEK");

    // Expired loadDelayedQuote is explicitly null
    const expiredDelayedQuote = await loadDelayedQuote(view, "SIVE.ST", FIXED_NOW);
    expect(expiredDelayedQuote).toBeNull();

    // Old delayed stock quote is unavailable through stock lookup
    const lookupAns = await handleGlobalEquityLookup(env as never, parseQuery("SIVE")) as { text: string }[];
    expect(lookupAns[0]!.text).not.toContain("32.78");
    expect(lookupAns[0]!.text).toContain("報價未開放");
    expect(lookupAns[0]!.text).not.toContain("已准入證券身分 · 延遲報價");
  });

  it("falls back to fresh price shard when combined observations are expired", async () => {
    const expiredStamp = new Date(FIXED_NOW - (6 * 3600_000 + 10_000)).toISOString().replace(/\.\d{3}Z$/, "Z");
    const env = await sealedEnv({ observationGeneratedAt: expiredStamp, withPriceShard: true });
    // Even though combined observation is expired, fresh price shard supplies the quote
    const lookupAns = await handleGlobalEquityLookup(env as never, parseQuery("SIVE")) as { text: string }[];
    expect(lookupAns[0]!.text).toContain("35.5 SEK");
    expect(lookupAns[0]!.text).not.toContain("32.78");
  });

  it("does not revive direct legacy keys or illicit fallback when option object is omitted after sealer expiry", async () => {
    const usableSyntheticPayload = JSON.stringify({
      schema: "v213-options-v2",
      generated_at: new Date(FIXED_NOW - 60_000).toISOString().replace(/\.\d{3}Z$/, "Z"),
      options: {
        SIVE: {
          monthly: {
            ticker: "SIVE", strategy: "COVERED_CALL", expiry: "2026-10-19", dte: 21, spot: 32.78, currency: "SEK",
            multiplier: 100, quote_basis: "delayed", timestamp: "2026-09-28T11:59:00Z",
            source: "Illicit Direct Key Fallback", provenance: "https://example.com/illicit",
            rights_status: "candidate_local_review",
            suggestions: [
              { role: "HIGH_STRIKE", strike: 99, bid: 9.0, ask: 9.5, mid: 9.25, limit_price: 9.0,
                premium_per_contract: 900, period_yield: 9.0 / 32.78, annualized_yield: 9.0 / 32.78 * 365 / 21,
                upside_to_strike: 99 / 32.78 - 1, delta: 0.1, delta_basis: "QUOTE_IMPLIED", iv: 1.0,
                oi: 10, volume: 10, spread_pct: 0.05 },
            ],
          },
        },
      },
    });

    const kv = new TrackingMemoryKv();
    const env = await sealedEnv({
      kv,
      omitObservations: true,
      legacyKvKeys: {
        "v213:options:v2": usableSyntheticPayload,
        "options:latest": usableSyntheticPayload,
        "latest_options": usableSyntheticPayload,
      },
    });

    // Clear recorded keys from initial sealedEnv setup
    kv.readKeys = [];

    const optionAns = JSON.stringify(await v213PublicLineAnswer(env as never, parseQuery("SIVE 每月期權")));
    expect(optionAns).toContain("OPTION_DATA_UNAVAILABLE");
    expect(optionAns).not.toContain("Illicit Direct Key Fallback");
    expect(optionAns).not.toContain("99.00 SEK");

    // Direct unsealed KV keys and legacy aliases must never be read by the option route
    expect(kv.readKeys).not.toContain("v213:options:v2");
    expect(kv.readKeys).not.toContain("options:latest");
    expect(kv.readKeys).not.toContain("latest_options");
  });
});
