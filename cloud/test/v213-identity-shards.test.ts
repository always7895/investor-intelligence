// Sealed identity shards (lazy content-addressed objects) through the real LINE stock lookup. Synthetic values only.
import { describe, expect, it } from "vitest";
import { parseQuery } from "../src/core";
import { handleGlobalEquityLookup } from "../src/v213/global-equity-lookup";
import { resolveGlobalIdentity } from "../src/v213/global-identity";
import { identityNameBucket, identitySymbolBucket, loadIdentityCatalogForQuery } from "../src/v213/identity-shards";
import { pinPublicSnapshot } from "../src/v213/public-snapshot";
import { SNAPSHOT_SEAL_KEY } from "../src/v213/snapshot-seal";
import { asKv, MemoryKv } from "./fake-kv";
import { sealUnboundReport } from "./sealed-report-migration";

const RUN = "20260926T020000Z-abcdefabcdef";
const FEEDS = [
  { id: "nasdaq-listed", url: "https://www.nasdaqtrader.com/dynamic/SymDir/nasdaqlisted.txt", retrieved_at: "2026-09-26T01:00:00Z", sha256: "a".repeat(64), rows: 1 },
  { id: "twse-listed", url: "https://openapi.twse.com.tw/v1/opendata/t187ap03_L", retrieved_at: "2026-09-26T01:00:00Z", sha256: "b".repeat(64), rows: 1 },
  { id: "nasdaq-stockholm-main", url: "https://api.nasdaq.com/api/nordic/screener/shares?category=MAIN_MARKET&tableonly=false&market=STO", retrieved_at: "2026-09-26T01:00:00Z", sha256: "c".repeat(64), rows: 1 },
];
const ROWS = [
  ["NVDA", "NASDAQ", "US", "United States", "NVIDIA Corporation - Common Stock", null, "COMMON_STOCK", "USD", 0, ["輝達", "ZHWIKI"]],
  ["2330", "TWSE", "TAIWAN", "Taiwan", "台灣積體電路製造股份有限公司", "台積電", "COMMON_STOCK", "TWD", 1, ["台積電", "TWSE"]],
  ["SIVE", "NASDAQ STOCKHOLM", "SWEDEN", "Sweden", "Sivers Semiconductors", null, "COMMON_STOCK", "SEK", 2],
  ["VOLV B", "NASDAQ STOCKHOLM", "SWEDEN", "Sweden", "Volvo B", null, "COMMON_STOCK", "SEK", 2],
  ["2330", "TSE", "JAPAN", "Japan", "Forside Co.,Ltd.", null, "COMMON_STOCK", "JPY", 0],
] as const;

async function sha(text: string): Promise<string> {
  const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(text));
  return Array.from(new Uint8Array(digest), byte => byte.toString(16).padStart(2, "0")).join("");
}

function shards(): Record<string, unknown> {
  const out: Record<string, unknown> = {};
  for (const row of ROWS) {
    const bucket = identitySymbolBucket(row[0]);
    const key = `v213:identity:v2:sym:${bucket}`;
    const shard = (out[key] ??= { schema: "v213-identity-shard-v2", kind: "symbol", bucket, generated_at: "2026-09-26T01:00:00Z", feeds: FEEDS, rows: [] }) as { rows: unknown[] };
    shard.rows.push([...row]);
    const zh = row.length > 9 ? (row as readonly unknown[])[9] as readonly string[] : null;
    for (const name of new Set([row[4], row[5], zh?.[0]].filter(Boolean).map(value => String(value).trim().toLowerCase()))) {
      const nameBucket = identityNameBucket(name);
      const nameKey = `v213:identity:v2:name:${nameBucket}`;
      const nameShard = (out[nameKey] ??= { schema: "v213-identity-shard-v2", kind: "name", bucket: String(nameBucket), generated_at: "2026-09-26T01:00:00Z", rows: [] }) as { rows: unknown[] };
      nameShard.rows.push([name, bucket, row[0], row[1]]);
    }
  }
  // Market price shards (scripts/build_price_shards.py): Taiwan has a stated trade date, Sweden none.
  const stamp = new Date(Date.now() - 3600_000).toISOString().replace(/\.\d{3}Z$/, "Z");
  out["v213:prices:v1:TAIWAN"] = { schema: "v213-price-shard-v1", market: "TAIWAN", generated_at: stamp,
    sources: [{ id: "twse-day-all", url: "https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL", retrieved_at: stamp, sha256: "d".repeat(64), rows: 1 }],
    rows: { "2330": [1000, -0.5, "2026-09-24", "TWD", 0] } };
  out["v213:prices:v1:SWEDEN"] = { schema: "v213-price-shard-v1", market: "SWEDEN", generated_at: stamp,
    sources: [{ id: "nasdaq-stockholm-main", url: "https://api.nasdaq.com/api/nordic/screener/shares", retrieved_at: stamp, sha256: "e".repeat(64), rows: 1 }],
    rows: { SIVE: [32.78, 1.2, null, "SEK", 0] } };
  if (!out["v213:identity:v2:sym:A"]) {
    out["v213:identity:v2:sym:A"] = { schema: "v213-identity-shard-v2", kind: "symbol", bucket: "A", generated_at: "2026-09-26T01:00:00Z", feeds: FEEDS, rows: [] };
  }
  return out;
}

/** A sealed run whose manifest lists the shards as lazy objects stored under blob:v1:<sha256>. */
async function sealedWithShards(tamper?: string) {
  const kv = new MemoryKv();
  const stamp = new Date(Date.now() - 60_000).toISOString().replace(/\.\d{3}Z$/, "Z");
  kv.values.set("v213:top20-report:latest", JSON.stringify({ synthetic: "report" }));
  kv.values.set("last_successful_pipeline_timestamp", stamp);
  await sealUnboundReport(kv, RUN);
  const sealKey = `snapshot:${RUN}:${SNAPSHOT_SEAL_KEY}`;
  const seal = JSON.parse(kv.values.get(sealKey)!);
  for (const [key, value] of Object.entries(shards())) {
    const body = JSON.stringify(value);
    const digest = await sha(body);
    seal.objects[key] = { sha256: digest, utf8_bytes: new TextEncoder().encode(body).byteLength };
    kv.values.set(`blob:v1:${digest}`, key === tamper ? body.replace("Sivers", "Sivars") : body);
  }
  const sealText = JSON.stringify(seal);
  kv.values.set(sealKey, sealText);
  const pointer = JSON.parse(kv.values.get("snapshot:current")!);
  pointer.seal_sha256 = await sha(sealText);
  kv.values.set("snapshot:current", JSON.stringify(pointer));
  return { PUBLIC_CACHE: asKv(kv), TENANT_PRIVATE_CACHE: asKv(new MemoryKv()), EPHEMERAL_SECURITY_CACHE: asKv(new MemoryKv()),
    V21_TOP20_MAX_AGE_SECONDS: "7200", V213_LINE_PRESENTATION: "text" };
}

describe("sealed identity shards", () => {
  it("hashes names like the Python builder (FNV-1a over UTF-16 code units)", () => {
    expect(identityNameBucket("台積電")).toBe(1342269639 % 16);
    expect(identityNameBucket("abc")).toBe(440920331 % 16);
  });

  it("resolves Swedish, US and Taiwan listings, share-class spellings and native names", async () => {
    const view = await pinPublicSnapshot(await sealedWithShards() as never);
    const status = async (query: string) => {
      const resolution = resolveGlobalIdentity(await loadIdentityCatalogForQuery(view, query), query);
      return resolution.status === "RESOLVED" ? `${resolution.record.venue}:${resolution.record.symbol}` : resolution.status;
    };
    expect(await status("SIVE")).toBe("NASDAQ STOCKHOLM:SIVE");
    expect(await status("SIVE.ST")).toBe("NASDAQ STOCKHOLM:SIVE");
    expect(await status("NVDA")).toBe("NASDAQ:NVDA");
    expect(await status("2330")).toBe("TWSE:2330");
    expect(await status("2330.TW")).toBe("TWSE:2330");
    expect(await status("2330.T")).toBe("TSE:2330");  // bare numeric codes stay Taiwan-first
    expect(await status("台積電")).toBe("TWSE:2330");
    expect(await status("VOLV.B")).toBe("NASDAQ STOCKHOLM:VOLV B");
    expect(await status("股票 VOLV-B")).toBe("NASDAQ STOCKHOLM:VOLV B");
    expect(await status("ZZZZ")).toBe("UNAVAILABLE");
    expect(await status("輝達")).toBe("NASDAQ:NVDA");  // sourced Chinese names are searchable
  });

  it("shows the sourced Chinese name next to the original, or says that none exists", async () => {
    const env = await sealedWithShards();
    const nvda = await handleGlobalEquityLookup(env as never, parseQuery("NVDA")) as { text: string }[];
    expect(nvda[0]!.text).toContain("中文名稱：輝達（中文維基百科）");
    expect(nvda[0]!.text).toContain("公司名稱（原文）：NVIDIA Corporation");
    const tw = await handleGlobalEquityLookup(env as never, parseQuery("2330")) as { text: string }[];
    expect(tw[0]!.text).toContain("中文名稱：台積電（臺灣證交所）");
    const sive = await handleGlobalEquityLookup(env as never, parseQuery("SIVE")) as { text: string }[];
    expect(sive[0]!.text).toContain("中文名稱：無公認中文名");
  });

  it("answers the LINE stock lookup with the admitted identity instead of 身分資料未封存", async () => {
    const env = await sealedWithShards();
    const answer = await handleGlobalEquityLookup(env as never, parseQuery("SIVE")) as { text: string }[];
    expect(answer[0]!.text).toContain("已准入證券身分");
    expect(answer[0]!.text).toContain("Sivers Semiconductors");
    expect(answer[0]!.text).not.toContain("身分資料未封存");
  });

  it("shows the market price shard for listings outside the watch universe", async () => {
    const env = await sealedWithShards();
    const tw = await handleGlobalEquityLookup(env as never, parseQuery("2330")) as { text: string }[];
    expect(tw[0]!.text).toContain("已准入證券身分 · 延遲報價");
    expect(tw[0]!.text).toContain("價格 1000 TWD（-0.50%），觀察時間 2026-09-24");
    expect(tw[0]!.text).toContain("臺灣證交所每日收盤 https://openapi.twse.com.tw/");
    const se = await handleGlobalEquityLookup(env as never, parseQuery("SIVE")) as { text: string }[];
    expect(se[0]!.text).toContain("擷取時間；來源未載明成交日");
    const us = await handleGlobalEquityLookup(env as never, parseQuery("NVDA")) as { text: string }[];
    expect(us[0]!.text).toContain("報價未開放");  // no US shard sealed: stays honest
  });

  it("refuses a lazy blob whose bytes do not match the sealed digest", async () => {
    const view = await pinPublicSnapshot(await sealedWithShards("v213:identity:v2:sym:S") as never);
    expect(view.integrity).toBe("sealed");
    expect(resolveGlobalIdentity(await loadIdentityCatalogForQuery(view, "SIVE"), "SIVE").status).toBe("UNAVAILABLE");
    expect(resolveGlobalIdentity(await loadIdentityCatalogForQuery(view, "NVDA"), "NVDA").status).toBe("RESOLVED");
  });
});
