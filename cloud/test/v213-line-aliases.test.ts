// Natural LINE phrasings reach the current products: bottleneck Top20 v3, its detail, the industry ranking and the
// covered-call observations. Sealed synthetic snapshot through the real public routes; synthetic values only.
import { describe, expect, it } from "vitest";
import { parseQuery } from "../src/core";
import { handleGlobalEquityLookup } from "../src/v213/global-equity-lookup";
import { BOTTLENECK_V3_KEY } from "../src/v213/bottleneck-v3";
import { v213PublicLineAnswer } from "../src/v213/rich-menu";
import { SNAPSHOT_SEAL_KEY } from "../src/v213/snapshot-seal";
import { doc, HOUR } from "./bottleneck-v3-fixture";
import { asKv, MemoryKv } from "./fake-kv";
import { sealUnboundReport } from "./sealed-report-migration";

const RUN = "20260926T040000Z-abcdefabcde1";
const now = Date.now();
const stamp = new Date(now - 30 * 60_000).toISOString().replace(/\.\d{3}Z$/, "Z");
const expiry = new Date(now + 21 * 86400_000).toISOString().slice(0, 10);

async function sha(text: string): Promise<string> {
  const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(text));
  return Array.from(new Uint8Array(digest), byte => byte.toString(16).padStart(2, "0")).join("");
}

const SIVE_MONTHLY = { ticker: "SIVE.ST", strategy: "COVERED_CALL", expiry, dte: 21, spot: 32.78, currency: "SEK", multiplier: 100,
  quote_basis: "delayed", timestamp: stamp, source: "Nasdaq Nordic option chain (exchange public web API, delayed)",
  provenance: "https://api.nasdaq.com/api/nordic/instruments/TX2540138/option-chain", rights_status: "candidate_local_review",
  suggestions: [{ role: "HIGH_STRIKE", strike: 62, bid: 0.2, ask: 0.35, mid: 0.275, limit_price: 0.23, premium_per_contract: 23,
    period_yield: 0.23 / 32.78, annualized_yield: 0.23 / 32.78 * 365 / 21, upside_to_strike: 62 / 32.78 - 1,
    delta: 0.061, delta_basis: "QUOTE_IMPLIED", iv: 1.5658, oi: 12, volume: null, spread_pct: 0.5455 }] };

async function sealedEnv() {
  const kv = new MemoryKv();
  kv.values.set("v213:top20-report:latest", JSON.stringify({ synthetic: "report" }));
  kv.values.set("last_successful_pipeline_timestamp", new Date(now - 60_000).toISOString().replace(/\.\d{3}Z$/, "Z"));
  await sealUnboundReport(kv, RUN);
  const lazy: Record<string, unknown> = {
    [BOTTLENECK_V3_KEY]: doc(now - HOUR),
    "v213:options:v2": { schema: "v213-options-v2", generated_at: stamp, options: {
      "SIVE.ST": { weekly: { unavailable: "Nasdaq Stockholm 無 3-14 天到期的上市期權" }, monthly: SIVE_MONTHLY } } },
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

async function answer(env: Awaited<ReturnType<typeof sealedEnv>>, text: string): Promise<string> {
  expect(await handleGlobalEquityLookup(env as never, parseQuery(text))).toBeNull();  // the Worker asks the lookup first
  return JSON.stringify(await v213PublicLineAnswer(env as never, parseQuery(text)));
}

describe("LINE aliases for the current products", () => {
  it("sends the plain ranking words and punctuated or full-width TOP20 to the bottleneck Top20 v3", async () => {
    const env = await sealedEnv();
    for (const text of ["TOP20。", "ＴＯＰ２０！", "top 20?", "排名", "排行榜", "前20", "前 20 名", "前二十", "瓶頸排名", "瓶頸榜", "TOP20 文字"]) {
      expect(await answer(env, text), text).toContain("瓶頸爆發 TOP20（v3");
    }
  });

  it("sends industry ranking phrasings to the Leopold industry ranking, not the company Top20", async () => {
    const env = await sealedEnv();
    for (const text of ["產業排名", "產業榜", "產業排行榜", "产业排名", "產業爆發榜。"]) {
      const body = await answer(env, text);
      expect(body, text).toContain("產業爆發榜（Leopold 因果鏈");
      expect(body, text).not.toContain("瓶頸爆發 TOP20（v3");
    }
  });

  it("opens a company detail with or without a space, ticker first, or by the symbol before the venue suffix", async () => {
    const env = await sealedEnv();
    for (const [text, symbol] of [["瓶頸詳情S1", "S1"], ["瓶頸 s1", "S1"], ["S1 詳情", "S1"], ["瓶頸詳情 S1。", "S1"],
      ["SIVE 詳情", "SIVE.ST"], ["瓶頸詳情 SIVE", "SIVE.ST"], ["瓶頸詳情 S2 文字", "S2"]] as const) {
      expect(await answer(env, text), text).toContain(`【瓶頸詳情｜#`);
      expect(await answer(env, text), text).toContain(` ${symbol} `);
    }
    expect(await answer(env, "瓶頸詳情 NVDA")).toContain("「NVDA」不在本輪瓶頸爆發 TOP20");
    expect(await answer(env, "NVDA 詳情")).toBe("null");  // not a Top20 company: the research lane keeps it
  });

  it("answers option phrasings without a cycle word, with 選擇權, trailing punctuation or no space", async () => {
    const env = await sealedEnv();
    for (const text of ["SIVE.ST 每月選擇權", "SIVE.ST 每月期權！", "期權SIVE.ST 每月", "選擇權 SIVE.ST 每月"]) {
      const body = await answer(env, text);
      expect(body, text).toContain("62.00 SEK");
      expect(body, text).toContain("Delta 0.06（由報價反推）");
    }
    for (const text of ["SIVE.ST 期權", "SIVE.ST期權", "SIVE.ST 選擇權"]) {
      expect(await answer(env, text), text).toContain("無 3-14 天到期的上市期權");  // no cycle word: weekly, as before
    }
    for (const text of ["call options", "sell options"]) {
      expect(await answer(env, text), text).not.toContain("備兌買權");  // English words are never read as tickers
    }
  });

  it("points help and navigation at commands that work", async () => {
    const env = await sealedEnv();
    const menu = await answer(env, "選單");
    for (const phrase of ["瓶頸詳情 代號", "產業爆發榜", "代號 每月期權", "七欄Top20"]) expect(menu).toContain(phrase);
    const options = await answer(env, "期權");
    expect(options).toContain("NVDA 每月期權");
    expect(options).not.toContain("「最新期權」");
  });
});
