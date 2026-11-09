// M1: synthetic offline regression values, not a live market collection or an admission override.
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { parseQuery } from "../src/core";
import { combineQuotes, handleGlobalEquityLookup } from "../src/v213/global-equity-lookup";
import { identitySymbolBucket } from "../src/v213/identity-shards";
import { formatVisibleMoment } from "../src/v213/line-formatters";
import { loadDelayedQuote, loadListingPrice } from "../src/v213/market-observations";
import { clearVerifiedLazyBodies, pinPublicSnapshot } from "../src/v213/public-snapshot";
import { SNAPSHOT_SEAL_KEY } from "../src/v213/snapshot-seal";
import { asKv, MemoryKv } from "./fake-kv";
import { sealUnboundReport } from "./sealed-report-migration";

const RUN = "20261108T151812Z-abcdefabcde1";
const GENERATED = "2026-11-08T15:18:12Z";
const NOW = Date.parse(GENERATED) + 60_000;
const RECORD = { symbol: "NVDA", market: "US" as const, venue: "NASDAQ" };
const QUOTE = { symbol: "NVDA", price: 186.64, previous_close: 182.29, change_pct: 186.64 / 182.29 - 1,
  currency: "USD", asof: "2026-11-06", fetched_at: GENERATED, source: "Yahoo Finance (unofficial, delayed)",
  source_url: "https://finance.yahoo.com/quote/NVDA" };

async function sha(text: string): Promise<string> {
  const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(text));
  return Array.from(new Uint8Array(digest), byte => byte.toString(16).padStart(2, "0")).join("");
}

async function sealedQuotes(options: {
  quote?: Record<string, unknown>;
  listingAsOf?: string | null;
  listingFetchedAt?: string;
  tamper?: boolean;
} = {}) {
  const kv = new MemoryKv();
  kv.values.set("v213:top20-report:latest", JSON.stringify({ synthetic: "report" }));
  kv.values.set("last_successful_pipeline_timestamp", GENERATED);
  await sealUnboundReport(kv, RUN);
  const bucket = identitySymbolBucket("NVDA");
  const feeds = [{ id: "nasdaq-listed", url: "https://www.nasdaqtrader.com/dynamic/SymDir/nasdaqlisted.txt",
    retrieved_at: GENERATED, sha256: "a".repeat(64), rows: 1 }];
  const document = { schema: "v213-quotes-v1", generated_at: GENERATED, quotes: { NVDA: options.quote ?? QUOTE } };
  const lazy: Record<string, unknown> = {
    [`v213:identity:v2:sym:${bucket}`]: { schema: "v213-identity-shard-v2", kind: "symbol", bucket,
      generated_at: GENERATED, feeds, rows: [["NVDA", "NASDAQ", "US", "United States", "NVIDIA Corporation",
        null, "COMMON_STOCK", "USD", 0]] },
    "v213:identity:v2:sym:A": { schema: "v213-identity-shard-v2", kind: "symbol", bucket: "A",
      generated_at: GENERATED, feeds, rows: [] },
    "v213:quotes:v1": document,
  };
  if (options.listingAsOf !== undefined) {
    lazy["v213:prices:v1:US"] = { schema: "v213-price-shard-v1", market: "US", generated_at: GENERATED,
      sources: [{ id: "nasdaq-us-screener", url: "https://api.nasdaq.com/api/screener/stocks",
        retrieved_at: options.listingFetchedAt ?? "2026-11-08T15:00:00Z" }],
      rows: { NVDA: [182.29, null, options.listingAsOf, "USD", 0] } };
  }
  const sealKey = `snapshot:${RUN}:${SNAPSHOT_SEAL_KEY}`;
  const seal = JSON.parse(kv.values.get(sealKey)!);
  for (const [key, value] of Object.entries(lazy)) {
    const body = JSON.stringify(value);
    const digest = await sha(body);
    seal.objects[key] = { sha256: digest, utf8_bytes: new TextEncoder().encode(body).byteLength };
    kv.values.set(`blob:v1:${digest}`, options.tamper && key === "v213:quotes:v1" ? body.replace("186.64", "999.99") : body);
  }
  const sealText = JSON.stringify(seal);
  kv.values.set(sealKey, sealText);
  const pointer = JSON.parse(kv.values.get("snapshot:current")!);
  pointer.seal_sha256 = await sha(sealText);
  kv.values.set("snapshot:current", JSON.stringify(pointer));
  const env = { PUBLIC_CACHE: asKv(kv), TENANT_PRIVATE_CACHE: asKv(new MemoryKv()),
    EPHEMERAL_SECURITY_CACHE: asKv(new MemoryKv()), V21_TOP20_MAX_AGE_SECONDS: "7200", V213_LINE_PRESENTATION: "text" };
  return { env, document, view: await pinPublicSnapshot(env) };
}

describe("M1 observation and acquisition clocks", () => {
  beforeEach(() => { clearVerifiedLazyBodies(); vi.useFakeTimers(); vi.setSystemTime(NOW); });
  afterEach(() => { clearVerifiedLazyBodies(); vi.useRealTimers(); });

  it.each(["2026-11-06", "2026-11-06T21:00:00Z"])("keeps NVDA 186.64 at provider AS OF %s despite a Sunday fetch", async asof => {
    const { env, view, document } = await sealedQuotes({ quote: { ...QUOTE, asof }, listingAsOf: "2026-11-05" });
    const before = JSON.stringify(await view.json(["v213:quotes:v1"]));
    const quote = await loadDelayedQuote(view, "NVDA", NOW);
    const listing = await loadListingPrice(view, RECORD, NOW);
    expect(quote).toMatchObject({ price: 186.64, asof, fetched_at: GENERATED });
    expect(listing).toMatchObject({ asof: "2026-11-05", fetched_at: "2026-11-08T15:00:00Z" });
    const combined = combineQuotes(listing, quote);
    expect(combined.primary).toBe(quote);
    expect(combined.crossCheck).toMatchObject({ asOf: "2026-11-05", fetchedAt: "2026-11-08T15:00:00Z" });
    for (const style of ["text", "flex"]) {
      const output = JSON.stringify(await handleGlobalEquityLookup({ ...env, V213_LINE_PRESENTATION: style }, parseQuery("NVDA")));
      expect(output).toContain("最新觀察價 186.64 USD");
      expect(output).toContain(`觀察時間 ${formatVisibleMoment(asof)}`);
      expect(output).toContain(`擷取時間 ${formatVisibleMoment(GENERATED)}`);
      expect(output).not.toContain(`觀察時間 ${formatVisibleMoment(GENERATED)}`);
    }
    expect(JSON.stringify(await view.json(["v213:quotes:v1"]))).toBe(before);
    expect(JSON.parse(before!)).toEqual(document); // Reader normalization never rewrites sealed input bytes.
  });

  it.each([GENERATED, "2026-11-08T15:18:12.000Z", "2026-11-08T23:18:12+08:00"])(
    "treats legacy generated_at collision %s as ingestion, never a fresher observation", async asof => {
      const { fetched_at: _fetch, ...legacy } = QUOTE;
      const { env, view } = await sealedQuotes({ quote: { ...legacy, asof }, listingAsOf: "2026-11-05" });
      const quote = await loadDelayedQuote(view, "NVDA", NOW);
      const listing = await loadListingPrice(view, RECORD, NOW);
      expect(quote).toMatchObject({ asof: null, fetched_at: asof });
      const combined = combineQuotes(listing, quote);
      expect(combined.primary).toBe(listing);
      expect(combined.crossCheck).toMatchObject({ asOf: null, fetchedAt: asof });
      for (const style of ["text", "flex"]) {
        const output = JSON.stringify(await handleGlobalEquityLookup({ ...env, V213_LINE_PRESENTATION: style }, parseQuery("NVDA")));
        expect(output).toContain("最新觀察價 182.29 USD");
        expect(output).toContain(`觀察時間未揭露；擷取時間 ${formatVisibleMoment(asof)}`);
        expect(output).not.toContain(`觀察時間 ${formatVisibleMoment(asof)}`);
      }
    });

  it("labels a lone legacy quote as fetch-only in both text and Flex", async () => {
    const { fetched_at: _fetch, ...legacy } = QUOTE;
    const { env } = await sealedQuotes({ quote: { ...legacy, asof: GENERATED } });
    for (const style of ["text", "flex"]) {
      const output = JSON.stringify(await handleGlobalEquityLookup({ ...env, V213_LINE_PRESENTATION: style }, parseQuery("NVDA")));
      expect(output).toContain("封存報價（觀察時間未揭露）");
      expect(output).toContain(`擷取時間 ${formatVisibleMoment(GENERATED)}`);
      expect(output).not.toContain("最新觀察價");
      expect(output).not.toContain(`觀察時間 ${formatVisibleMoment(GENERATED)}`);
    }
  });

  it.each([undefined, null, "invalid-clock"])("keeps missing/unknown provider clock %s explicit", async asof => {
    const { env, view } = await sealedQuotes({ quote: { ...QUOTE, asof }, listingAsOf: "2026-11-05" });
    const quote = await loadDelayedQuote(view, "NVDA", NOW);
    const listing = await loadListingPrice(view, RECORD, NOW);
    expect(quote).toMatchObject({ asof: null, fetched_at: GENERATED });
    expect(combineQuotes(listing, quote).primary).toBe(listing);
    const output = JSON.stringify(await handleGlobalEquityLookup(env, parseQuery("NVDA")));
    expect(output).toContain("觀察時間未揭露；擷取時間 ");
    expect(output).not.toContain("invalid-clock");
  });

  it("does not manufacture an acquisition clock when neither source field records one", async () => {
    const { asof: _asof, fetched_at: _fetch, ...unclocked } = QUOTE;
    const { env, view } = await sealedQuotes({ quote: unclocked });
    expect(await loadDelayedQuote(view, "NVDA", NOW)).toMatchObject({ asof: null, fetched_at: null });
    const output = JSON.stringify(await handleGlobalEquityLookup(env, parseQuery("NVDA")));
    expect(output).toContain("觀察時間未揭露");
    expect(output).not.toContain("擷取時間");
    expect(output).not.toContain("最新觀察價");
  });

  it("does not promote fetch-only listing rows over known observations", async () => {
    const { env, view } = await sealedQuotes({ listingAsOf: null, listingFetchedAt: "2026-11-08T15:19:00Z" });
    const listing = await loadListingPrice(view, RECORD, NOW);
    const quote = await loadDelayedQuote(view, "NVDA", NOW);
    expect(listing).toMatchObject({ asof: null, fetched_at: "2026-11-08T15:19:00Z" });
    const combined = combineQuotes(listing, quote);
    expect(combined.primary).toBe(quote);
    expect(combined.crossCheck).toMatchObject({ asOf: null, fetchedAt: "2026-11-08T15:19:00Z" });
    const output = JSON.stringify(await handleGlobalEquityLookup(env, parseQuery("NVDA")));
    expect(output).toContain("最新觀察價 186.64 USD");
    expect(output).toContain("觀察時間未揭露；擷取時間 ");
  });

  it("ranks precise observations independently of acquisition order and retains unknown ties", () => {
    const official = { ...QUOTE, source: "Nasdaq Screener", asof: "2026-11-06T21:00:00Z", fetched_at: "2026-11-08T16:00:00Z" };
    const observed = { ...QUOTE, asof: "2026-11-06T16:00:01-05:00", fetched_at: "2026-11-08T14:00:00Z" };
    expect(combineQuotes(official, observed).primary).toBe(observed);
    const older = { ...observed, asof: "2026-11-06T22:00:00+02:00", fetched_at: "2026-11-08T17:00:00Z" };
    expect(combineQuotes(official, older).primary).toBe(official);
    const unknown = { ...official, asof: null };
    expect(combineQuotes(unknown, { ...older, asof: null }).primary).toBe(unknown);
  });

  it("keeps document freshness, future-clock and sealed-byte gates unchanged", async () => {
    const { view } = await sealedQuotes({ listingAsOf: "2026-11-06" });
    expect(await loadDelayedQuote(view, "NVDA", Date.parse(GENERATED) + 6 * 3600_000 + 1)).toBeNull();
    expect(await loadDelayedQuote(view, "NVDA", Date.parse(GENERATED) - 300_001)).toBeNull();
    expect(await loadListingPrice(view, RECORD, Date.parse(GENERATED) + 4 * 86400_000 + 1)).toBeNull();
    expect(await loadListingPrice(view, RECORD, Date.parse(GENERATED) - 300_001)).toBeNull();
    clearVerifiedLazyBodies(); // Exercise a cold read, not the already verified content-addressed body.
    const tampered = await sealedQuotes({ tamper: true });
    expect(await loadDelayedQuote(tampered.view, "NVDA", NOW)).toBeNull();
  });
});
