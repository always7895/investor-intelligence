// Options queries for listings outside the sealed option markets (operator 2026-09-27: TSMC and IQE had no answer): a mapped
// US ADR answers with its own options and a note; another market states that no public listed-option source covers it.
// Sealed synthetic snapshot through the real public routes; synthetic values only.
import { describe, expect, it } from "vitest";
import { parseQuery } from "../src/core";
import { handleGlobalEquityLookup } from "../src/v213/global-equity-lookup";
import { normalizeCompanyName } from "../src/v213/global-identity";
import { identityNameBucket } from "../src/v213/identity-shards";
import { adrRoute } from "../src/v213/option-routes";
import { v213PublicLineAnswer } from "../src/v213/rich-menu";
import { SNAPSHOT_SEAL_KEY } from "../src/v213/snapshot-seal";
import { asKv, MemoryKv } from "./fake-kv";
import { sealUnboundReport } from "./sealed-report-migration";

const RUN = "20260927T040000Z-abcdefabcde2";
const now = Date.now();
const stamp = new Date(now - 30 * 60_000).toISOString().replace(/\.\d{3}Z$/, "Z");
const expiry = new Date(now + 21 * 86400_000).toISOString().slice(0, 10);
const FEEDS = [{ id: "twse-listed", url: "https://openapi.twse.com.tw/v1/opendata/t187ap03_L", retrieved_at: stamp, sha256: "c".repeat(64), rows: 1 },
  { id: "lse-aim", url: "https://api.londonstockexchange.com/api/v1/components/refresh", retrieved_at: stamp, sha256: "d".repeat(64), rows: 1 }];
const TSMC_NAME = normalizeCompanyName("台積電");
// Synthetic Chinese names for a US listing, a Stockholm listing and a dual listing (NEEDS_MARKET_SELECTION).
const NAMES: [string, string, string, string][] = [
  [TSMC_NAME, "2", "2330", "TWSE"],
  [normalizeCompanyName("輝達"), "N", "NVDA", "NASDAQ"],
  [normalizeCompanyName("合成瑞典"), "S", "SIVE", "Nasdaq Stockholm"],
  [normalizeCompanyName("阿斯特捷利康"), "A", "AZN", "NASDAQ"],
  [normalizeCompanyName("阿斯特捷利康"), "A", "AZN", "Nasdaq Stockholm"],
  [normalizeCompanyName("合成雙掛"), "D", "DUAL", "NASDAQ"],
  [normalizeCompanyName("合成雙掛"), "D", "DUAL", "Nasdaq Stockholm"],
];

async function sha(text: string): Promise<string> {
  const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(text));
  return Array.from(new Uint8Array(digest), byte => byte.toString(16).padStart(2, "0")).join("");
}

const TSM_MONTHLY = { ticker: "TSM", strategy: "COVERED_CALL", expiry, dte: 21, spot: 300, currency: "USD", multiplier: 100, quote_basis: "delayed",
  timestamp: stamp, source: "Yahoo Finance option chain (unofficial, delayed)", provenance: "https://finance.yahoo.com/quote/TSM/options",
  rights_status: "unadmitted_third_party", suggestions: [{ role: "HIGH_STRIKE", strike: 330, bid: 2.0, ask: 2.1, mid: 2.05, limit_price: 2.05,
    premium_per_contract: 205, period_yield: 2.05 / 300, annualized_yield: 2.05 / 300 * 365 / 21, upside_to_strike: 330 / 300 - 1,
    delta: 0.18, delta_basis: "QUOTED_IV", iv: 0.4, oi: 900, volume: 50, spread_pct: 0.0488 }] };

async function sealedEnv() {
  const kv = new MemoryKv();
  kv.values.set("v213:top20-report:latest", JSON.stringify({ synthetic: "report" }));
  kv.values.set("last_successful_pipeline_timestamp", new Date(now - 60_000).toISOString().replace(/\.\d{3}Z$/, "Z"));
  await sealUnboundReport(kv, RUN);
  const shard = (bucket: string, rows: unknown[]) => ({ schema: "v213-identity-shard-v2", kind: "symbol", bucket, generated_at: stamp, feeds: FEEDS, rows });
  const lazy: Record<string, unknown> = {
    "v213:identity:v2:sym:2": shard("2", [["2330", "TWSE", "TAIWAN", "Taiwan", "Taiwan Semiconductor Manufacturing", null, "COMMON_STOCK", "TWD", 0, ["台積電", "TWSE"]]]),
    "v213:identity:v2:sym:I": shard("I", [["IQE", "LSE AIM", "UK", "United Kingdom", "IQE PLC", null, "COMMON_STOCK", "GBX", 1]]),
    "v213:identity:v2:sym:A": shard("A", [["AZN", "NASDAQ", "US", "United States", "AstraZeneca PLC ADS", null, "ADR", "USD", 0, ["阿斯特捷利康", "ZHWIKI"]],
      ["AZN", "Nasdaq Stockholm", "SWEDEN", "Sweden", "AstraZeneca PLC", null, "COMMON_STOCK", "SEK", 0, ["阿斯特捷利康", "ZHWIKI"]]]),
    "v213:identity:v2:sym:D": shard("D", [["DUAL", "NASDAQ", "US", "United States", "Synthetic Dual Corp", null, "COMMON_STOCK", "USD", 0, ["合成雙掛", "ZHWIKI"]],
      ["DUAL", "Nasdaq Stockholm", "SWEDEN", "Sweden", "Synthetic Dual AB", null, "COMMON_STOCK", "SEK", 0, ["合成雙掛", "ZHWIKI"]]]),
    "v213:identity:v2:sym:N": shard("N", [["NVDA", "NASDAQ", "US", "United States", "NVIDIA Corp", null, "COMMON_STOCK", "USD", 0, ["輝達", "ZHWIKI"]]]),
    "v213:identity:v2:sym:S": shard("S", [["SIVE", "Nasdaq Stockholm", "SWEDEN", "Sweden", "Sivers Semiconductors AB", null, "COMMON_STOCK", "SEK", 0, ["合成瑞典", "ZHWIKI"]]]),
    "v213:quotes:v1": { schema: "v213-quotes-v1", generated_at: stamp, quotes: {
      "2330.TW": { symbol: "2330.TW", price: 1500, previous_close: 1490, change_pct: 0.0067, currency: "TWD", asof: stamp, source: "Yahoo Finance (unofficial, delayed)", source_url: "https://finance.yahoo.com/quote/2330.TW" },
      "IQE.L": { symbol: "IQE.L", price: 15, previous_close: 15, change_pct: 0, currency: "GBp", asof: stamp, source: "Yahoo Finance (unofficial, delayed)", source_url: "https://finance.yahoo.com/quote/IQE.L" } } },
    "v213:options:v2": { schema: "v213-options-v2", generated_at: stamp, options: {
      TSM: { weekly: { unavailable: "合成：TSM 本週無雙邊報價" }, monthly: TSM_MONTHLY },
      NVDA: { monthly: { unavailable: "合成：NVDA 本月鏈缺漏" } }, "NVDA.ST": { monthly: { unavailable: "錯誤市場：不應顯示" } },
      "SIVE.ST": { monthly: { unavailable: "合成：SIVE.ST 本月鏈缺漏" } } } },
  };
  for (const [name, bucket, symbol, venue] of NAMES) {
    const key = `v213:identity:v2:name:${identityNameBucket(name)}`;
    const doc = (lazy[key] ??= { schema: "v213-identity-shard-v2", kind: "name", bucket: String(identityNameBucket(name)), generated_at: stamp, rows: [] }) as { rows: unknown[] };
    doc.rows.push([name, bucket, symbol, venue]);
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

const answer = async (env: Awaited<ReturnType<typeof sealedEnv>>, text: string) => JSON.stringify(await v213PublicLineAnswer(env as never, parseQuery(text)));

describe("option routes outside the sealed option markets", () => {
  it("maps home listings and their aliases to the US ADR", () => {
    expect(adrRoute("TSMC")).toEqual({ listing: "2330.TW", adr: "TSM", ratio: 5, name_zh: "台積電" });
    expect(adrRoute("2330.tw")?.adr).toBe("TSM");
    expect(adrRoute("3711")?.ratio).toBe(2);
    expect(adrRoute("IQE")).toBeNull();
  });

  it("answers TSMC, 2330 and 台積電 with the TSM ADR's options and says so", async () => {
    const env = await sealedEnv();
    for (const text of ["TSMC 每月期權", "2330 每月期權", "台積電 每月期權", "2330.TW 每月選擇權"]) {
      const body = await answer(env, text);
      expect(body, text).toContain("台積電（2330.TW）以其美國 ADR TSM（1 ADR＝5 股普通股）的掛牌期權顯示");
      expect(body, text).toContain("330.00");
      expect(body, text).toContain("交付的是 ADR");
    }
    expect(await answer(env, "TSMC 每週期權")).toContain("TSM 本週無雙邊報價");
    const direct = await answer(env, "TSM 每月期權");  // the ADR itself: no note
    expect(direct).toContain("330.00");
    expect(direct).not.toContain("以其美國 ADR");
  });

  it("states that a listing on another market has no public listed-option source instead of a bare refusal", async () => {
    const env = await sealedEnv();
    const body = await answer(env, "IQE 每月期權");
    expect(body).toContain("IQE 在英國（倫敦）（LSE AIM）掛牌");
    expect(body).toContain("只涵蓋美股與Nasdaq Stockholm");
    expect(body).toContain("本服務尚未採用此市場的個股期權報價來源");  // the service's coverage, not a claim about the market
    expect(body).not.toContain("OPTION_DATA_NOT_ADMITTED");
    expect(await answer(env, "每月期權")).not.toContain("以其美國 ADR");  // a cycle word alone is not a company name
  });

  it("answers a Chinese name resolved to a US or Stockholm listing from that listing's own key", async () => {
    const env = await sealedEnv();
    const us = await answer(env, "輝達 每月期權");
    expect(us).toContain("合成：NVDA 本月鏈缺漏");
    expect(us).not.toContain("錯誤市場");
    expect(us).not.toContain("OPTION_DATA_NOT_ADMITTED");
    const se = await answer(env, "合成瑞典 每月期權");
    expect(se).toContain("合成：SIVE.ST 本月鏈缺漏");
    // A depositary receipt never takes the Chinese name, so AstraZeneca resolves to its Stockholm share, which has no observation here.
    const azn = await answer(env, "阿斯特捷利康 每月期權");
    expect(azn).toContain("AZN.ST（Nasdaq Stockholm）：本輪封存資料沒有此掛牌的期權觀察");
    expect(azn).not.toContain("OPTION_DATA_NOT_ADMITTED");
    const both = await answer(env, "合成雙掛 每月期權");  // two common-stock listings: ask for the exact ticker instead of guessing
    expect(both).toContain("此名稱對應多個掛牌");
    expect(both).toContain("DUAL（NASDAQ）");
    expect(both).toContain("DUAL（Nasdaq Stockholm）");
  });

  it("never reads cycle or teaching words as a company name", async () => {
    const env = await sealedEnv();
    for (const text of ["每月期權", "每週期權", "期權教學"]) {
      const body = await answer(env, text);
      expect(body, text).not.toContain("以其美國 ADR");
      expect(body, text).not.toContain("此名稱對應多個掛牌");
      expect(body, text).not.toContain("掛牌；本服務的公開掛牌期權報價");
    }
    expect(await answer(env, "期權教學")).toContain("教學");
  });

  it("offers option buttons on the stock card only where an options answer exists", async () => {
    const env = { ...(await sealedEnv()), V213_LINE_PRESENTATION: "flex" };
    const tsmc = JSON.stringify(await handleGlobalEquityLookup(env as never, parseQuery("2330")));
    expect(tsmc).toContain("2330 每月期權");
    const iqe = JSON.stringify(await handleGlobalEquityLookup(env as never, parseQuery("IQE")));
    expect(iqe).not.toContain("每月期權");
  });
});
