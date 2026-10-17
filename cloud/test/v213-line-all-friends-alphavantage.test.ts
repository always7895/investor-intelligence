// Alpha Vantage values are for the owner only (operator 2026-10-11, Q2 of OPERATOR-DECISION-S1-AND-ALPHAVANTAGE-FRIENDS-20261011.txt).
// Real caller: the signed webhook through the production Worker (processLineEvent / the friend lane), a sealed snapshot with an
// Alpha Vantage sourced spot row and Yahoo sourced rows. Synthetic values only, no network.
/// <reference types="node" />
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { QUOTES_KEY, OPTIONS_KEY } from "../src/v213/market-observations";
import { ALPHA_VANTAGE_SOURCE_LABEL, isAlphaVantageProvenance, withAlphaVantageOwnerOnly } from "../src/v213/alpha-vantage-viewer";
import type { PublicSnapshotView } from "../src/v213/public-snapshot";
import { SNAPSHOT_SEAL_KEY } from "../src/v213/snapshot-seal";
import { FRIEND_A, OWNER_USER, lineFixture, type FixtureOptions } from "./line-all-friends-fixture";
import { sealUnboundReport } from "./sealed-report-migration";
import { admitSyntheticTickers, resetAdmissionToReal } from "./synthetic-option-admission";

// Rights NONE is the real default (every option row is denied); these tests opt in per test for exactly the sealed tickers they render.
vi.mock("../src/v213/public-options-admission", async importOriginal => {
  const real = await importOriginal<typeof import("../src/v213/public-options-admission")>();
  return { ...real, admitPublicOption: vi.fn(real.admitPublicOption) };
});

type Fixture = Awaited<ReturnType<typeof lineFixture>>;
const open: Fixture[] = [];
const TEXT = { V213_LINE_PRESENTATION: "text" };
async function fixture(options: FixtureOptions = {}): Promise<Fixture> {
  for (const previous of open.splice(0)) previous.restore();
  const f = await lineFixture({ ...options, env: { ...TEXT, ...(options.env ?? {}) } });
  open.push(f);
  await seal(f);
  return f;
}
beforeEach(() => {
  resetAdmissionToReal();
});
afterEach(() => {
  for (const f of open.splice(0)) f.restore();
  vi.restoreAllMocks();
});

const RUN = "20261011T040000Z-abcdefabcde2";
const now = Date.now();
const stamp = new Date(now - 30 * 60_000).toISOString().replace(/\.\d{3}Z$/, "Z");
const expiry = new Date(now + 21 * 86400_000).toISOString().slice(0, 10);
const FEEDS = [
  { id: "twse-listed", url: "https://openapi.twse.com.tw/v1/opendata/t187ap03_L", retrieved_at: stamp, sha256: "c".repeat(64), rows: 1 },
  { id: "lse-aim", url: "https://api.londonstockexchange.com/api/v1/components/refresh", retrieved_at: stamp, sha256: "d".repeat(64), rows: 1 },
];
const YAHOO = "Yahoo Finance (unofficial, delayed)";
const AV_URL = "https://www.alphavantage.co/query?function=GLOBAL_QUOTE&symbol=AVQ";
// AVQ: the Alpha Vantage fallback row. YHQ: Yahoo. PTH: Yahoo whose URL only mentions the AV host in its query string.
// HST: another provider on a host that merely starts with the AV host name. All four are US common stocks.
const ROWS: Record<string, { price: number; source: string; source_url: string }> = {
  AVQ: { price: 123.45, source: ALPHA_VANTAGE_SOURCE_LABEL, source_url: AV_URL },
  YHQ: { price: 67.89, source: YAHOO, source_url: "https://finance.yahoo.com/quote/YHQ" },
  PTH: { price: 45.67, source: YAHOO, source_url: "https://finance.yahoo.com/quote/PTH?ref=www.alphavantage.co" },
  HST: { price: 89.01, source: "Synthetic Vendor", source_url: "https://www.alphavantage.co.example.test/quote/HST" },
};

async function sha(text: string): Promise<string> {
  const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(text));
  return Array.from(new Uint8Array(digest), byte => byte.toString(16).padStart(2, "0")).join("");
}

function cycle(ticker: string) {
  return {
    ticker, strategy: "COVERED_CALL", expiry, dte: 21, spot: 300, currency: "USD", multiplier: 100, quote_basis: "delayed",
    timestamp: stamp, source: "Yahoo Finance option chain (unofficial, delayed)", provenance: `https://finance.yahoo.com/quote/${ticker}/options`,
    rights_status: "unadmitted_third_party",
    suggestions: [{ role: "HIGH_STRIKE", strike: 330, bid: 2.0, ask: 2.1, mid: 2.05, limit_price: 2.05, premium_per_contract: 205,
      period_yield: 2.05 / 300, annualized_yield: 2.05 / 300 * 365 / 21, upside_to_strike: 330 / 300 - 1, delta: 0.18, delta_basis: "QUOTED_IV",
      iv: 0.4, oi: 900, volume: 50, spread_pct: 0.0488 }],
  };
}

/** Seals the fixture's public KV: report objects through the migration helper, then quotes, options and identity shards as lazy objects. */
async function seal(f: Fixture): Promise<void> {
  const kv = f.publicKv;
  kv.values.set("v213:top20-report:latest", JSON.stringify({ synthetic: "report" }));
  kv.values.set("last_successful_pipeline_timestamp", new Date(now - 60_000).toISOString().replace(/\.\d{3}Z$/, "Z"));
  await sealUnboundReport(kv, RUN);
  const lazy: Record<string, unknown> = {};
  for (const symbol of Object.keys(ROWS)) {
    const bucket = symbol.slice(0, 1);
    const key = `v213:identity:v2:sym:${bucket}`;
    const doc = (lazy[key] ??= { schema: "v213-identity-shard-v2", kind: "symbol", bucket, generated_at: stamp, feeds: FEEDS, rows: [] }) as { rows: unknown[] };
    doc.rows.push([symbol, "NASDAQ", "US", "United States", `Synthetic ${symbol} Corp`, null, "COMMON_STOCK", "USD", 0]);
  }
  lazy[QUOTES_KEY] = {
    schema: "v213-quotes-v1", generated_at: stamp,
    quotes: Object.fromEntries(Object.entries(ROWS).map(([symbol, row]) => [symbol,
      { symbol, price: row.price, previous_close: row.price - 1, change_pct: 1 / (row.price - 1), currency: "USD", asof: stamp, source: row.source, source_url: row.source_url }])),
  };
  lazy[OPTIONS_KEY] = {
    schema: "v213-options-v2", generated_at: stamp,
    options: { AVQ: { weekly: { unavailable: "合成：AVQ 本週無雙邊報價" }, monthly: cycle("AVQ") }, YHQ: { monthly: cycle("YHQ") } },
  };
  const sealKey = `snapshot:${RUN}:${SNAPSHOT_SEAL_KEY}`;
  const sealDocument = JSON.parse(kv.values.get(sealKey)!);
  for (const [key, value] of Object.entries(lazy)) {
    const body = JSON.stringify(value);
    const digest = await sha(body);
    sealDocument.objects[key] = { sha256: digest, utf8_bytes: new TextEncoder().encode(body).byteLength };
    kv.values.set(`blob:v1:${digest}`, body);
  }
  const sealText = JSON.stringify(sealDocument);
  kv.values.set(sealKey, sealText);
  const pointer = JSON.parse(kv.values.get("snapshot:current")!);
  pointer.seal_sha256 = await sha(sealText);
  kv.values.set("snapshot:current", JSON.stringify(pointer));
}

async function ask(f: Fixture, user: string, text: string): Promise<string> {
  const sent = await f.deliver(user, text);
  const reply = f.replyTo(sent.token);
  expect(reply, text).toBeTypeOf("string");
  return reply as string;
}

const ALL = { mode: "all_friends" } satisfies FixtureOptions;

describe("Alpha Vantage derived values are owner-only in all_friends mode", () => {
  it("a friend gets no Alpha Vantage price, source or URL in the stock lookup; Yahoo and look-alike rows are unchanged", async () => {
    const f = await fixture(ALL);
    const av = await ask(f, FRIEND_A, "ticker AVQ");
    expect(av).not.toContain("123.45");
    expect(av).not.toMatch(/alpha\s*vantage|alphavantage/i);
    expect(await ask(f, FRIEND_A, "ticker YHQ")).toContain("67.89");
    // The closed rule: a path or query that mentions the host, or a host that only starts with it, is not Alpha Vantage.
    expect(await ask(f, FRIEND_A, "ticker PTH")).toContain("45.67");
    expect(await ask(f, FRIEND_A, "ticker HST")).toContain("89.01");
  });

  it("the owner sees the Alpha Vantage row unchanged in all_friends mode", async () => {
    const f = await fixture(ALL);
    const reply = await ask(f, OWNER_USER, "ticker AVQ");
    expect(reply).toContain("123.45");
    expect(reply).toContain("Alpha Vantage");
  });

  it("owner_only mode (missing, explicit, garbage) answers the owner byte-identically to all_friends", async () => {
    const f = await fixture(ALL);
    const reference = await ask(f, OWNER_USER, "ticker AVQ");
    for (const mode of [undefined, "owner_only", "ALL_FRIENDS"]) {
      const g = await fixture({ mode });
      expect(await ask(g, OWNER_USER, "ticker AVQ"), String(mode)).toBe(reference);
    }
  });

  it("treats a failed owner lookup as a friend", async () => {
    const f = await fixture(ALL);
    const original = f.privateKv.get.bind(f.privateKv);
    const reads = vi.spyOn(f.privateKv, "get").mockImplementation((async (key: string, type?: "text" | "json") => {
      if (key === "v21:owner-line:tenant") throw new Error("SYNTHETIC_KV_READ_FAILURE");
      return original(key, type);
    }) as never);
    const reply = await ask(f, OWNER_USER, "ticker AVQ");
    reads.mockRestore();
    expect(reply).not.toContain("123.45");
    expect(reply).not.toMatch(/alpha\s*vantage|alphavantage/i);
  });

  it("the covered-call card: the friend gets the unavailable state for the Alpha Vantage underlying only", async () => {
    admitSyntheticTickers("AVQ", "YHQ");
    const f = await fixture(ALL);
    const friendAv = await ask(f, FRIEND_A, "AVQ 每月期權");
    expect(friendAv).toContain("現價暫不可用");
    expect(friendAv).not.toContain("330.00");
    expect(friendAv).not.toMatch(/alpha\s*vantage|alphavantage/i);
    expect(await ask(f, FRIEND_A, "YHQ 每月期權")).toContain("330.00");
    expect(await ask(f, OWNER_USER, "AVQ 每月期權")).toContain("330.00");
  });

  it("the sealed bytes are never altered: the friend view only changes the parsed copy", async () => {
    const bodies = new Map<string, string>([
      [QUOTES_KEY, JSON.stringify({ schema: "v213-quotes-v1", generated_at: stamp, quotes: { AVQ: { source: ALPHA_VANTAGE_SOURCE_LABEL, source_url: AV_URL, price: 1 } } })],
      [OPTIONS_KEY, JSON.stringify({ schema: "v213-options-v2", generated_at: stamp, options: { AVQ: { monthly: { spot: 1 } } } })],
    ]);
    const inner: PublicSnapshotView = {
      runId: RUN, kind: "snapshot", integrity: "sealed", hasSealedObject: key => bodies.has(key),
      json: async <T,>(keys: string[]) => { const body = bodies.get(keys[0]!); return body === undefined ? null : JSON.parse(body) as T; },
      text: async keys => bodies.get(keys[0]!) ?? null,
    };
    const view = withAlphaVantageOwnerOnly(inner);
    expect(await view.text([QUOTES_KEY])).toBe(bodies.get(QUOTES_KEY));
    expect(await view.text([OPTIONS_KEY])).toBe(bodies.get(OPTIONS_KEY));
    expect(view.integrity).toBe("sealed");
    expect(view.hasSealedObject?.(QUOTES_KEY)).toBe(true);
    expect(JSON.stringify(await view.json([QUOTES_KEY]))).not.toContain("alphavantage");
    expect(JSON.stringify(await view.json([OPTIONS_KEY]))).not.toContain("\"spot\"");
    // Other sealed objects pass through untouched.
    bodies.set("other", JSON.stringify({ schema: "x", value: AV_URL }));
    expect(await view.json(["other"])).toEqual({ schema: "x", value: AV_URL });
  });
});

describe("closed Alpha Vantage provenance rule", () => {
  const row = (source: unknown, source_url: unknown, extra: Record<string, unknown> = {}) => ({ source, source_url, ...extra });
  it("matches the exact host, the exact producer label and the exact family names", () => {
    expect(isAlphaVantageProvenance(row(YAHOO, AV_URL))).toBe(true);
    expect(isAlphaVantageProvenance(row(YAHOO, "https://WWW.AlphaVantage.co/query"))).toBe(true);
    expect(isAlphaVantageProvenance(row(ALPHA_VANTAGE_SOURCE_LABEL, "https://finance.yahoo.com/quote/X"))).toBe(true);
    expect(isAlphaVantageProvenance(row(YAHOO, "https://finance.yahoo.com/quote/X", { source_family: "alpha_vantage_market" }))).toBe(true);
    expect(isAlphaVantageProvenance(row(YAHOO, "https://finance.yahoo.com/quote/X", { source_id: "alpha_vantage_adjusted" }))).toBe(true);
  });
  it("never matches a substring of free text, a path, a query, another host or an unknown shape", () => {
    expect(isAlphaVantageProvenance(row(YAHOO, "https://finance.yahoo.com/www.alphavantage.co/query"))).toBe(false);
    expect(isAlphaVantageProvenance(row(YAHOO, "https://finance.yahoo.com/quote/X?ref=www.alphavantage.co"))).toBe(false);
    expect(isAlphaVantageProvenance(row(YAHOO, "https://www.alphavantage.co.example.test/query"))).toBe(false);
    expect(isAlphaVantageProvenance(row(YAHOO, "https://alphavantage.co/query"))).toBe(false);
    expect(isAlphaVantageProvenance(row(YAHOO, "https://notwww.alphavantage.co/query"))).toBe(false);
    expect(isAlphaVantageProvenance(row("Alpha Vantage free text", "https://finance.yahoo.com/quote/X"))).toBe(false);
    expect(isAlphaVantageProvenance(row(YAHOO, "https://finance.yahoo.com/quote/X", { source_family: "alpha_vantage" }))).toBe(false);
    expect(isAlphaVantageProvenance(row(YAHOO, 42))).toBe(false);
    expect(isAlphaVantageProvenance(row(YAHOO, "not a url"))).toBe(false);
    for (const value of [null, undefined, "https://www.alphavantage.co/query", 7, ["x"]]) expect(isAlphaVantageProvenance(value)).toBe(false);
  });
});
