/**
 * B2 caller regression: REAL sealed route/loader/identity/renderers. Synthetic-only, no network.
 * D1-D5: timed admission proves expiry ORDER, not catalog review_valid_through; fault cases are
 * defensive boundaries, NOT sealed-reachable states. Direct-query dot rewriting (before FOUND) is pinned by B2-18.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import catalog from "../../config/public-options-provider-candidates.json";
import { parseQuery } from "../src/core";
import { assertLineMessages, type LineOutboundMessage } from "../src/line-messages";
import { type GlobalIdentityCatalog, normalizeCompanyName } from "../src/v213/global-identity";
import { identityNameBucket } from "../src/v213/identity-shards";
import { loadDetailedOptionObservation } from "../src/v213/market-observations";
import * as admission from "../src/v213/public-options-admission";
import { pinPublicSnapshot } from "../src/v213/public-snapshot";
import { v213PublicLineAnswer } from "../src/v213/rich-menu";
import { SNAPSHOT_SEAL_KEY } from "../src/v213/snapshot-seal";
import { asKv, MemoryKv } from "./fake-kv";
import { sealUnboundReport } from "./sealed-report-migration";
import { admitSyntheticTickers, resetAdmissionToReal, SYNTHETIC_PROVIDER_ID } from "./synthetic-option-admission";

const trace = vi.hoisted(() => ({
  logical: [] as string[][],
  queries: [] as string[],
  events: [] as string[],
  views: new WeakMap<object, object>(),
  hook: null as null | { key: string; mode: "advance" | "reject"; cutoff?: number },
  legacy: false,
  metadata: [] as { recordsSame: boolean; indexesSame: boolean }[],
  fault: null as null | "missing" | "empty" | "whitespace" | "space-body",
  afterFoundClock: null as number | null,
  faultEvidence: [] as { before: string | undefined; after: string | undefined; quoteSame: boolean }[],
}));

// TEST SEAM: preserve the real error class/constants; each test resets to REAL admission.
vi.mock("../src/v213/public-options-admission", async importOriginal => {
  const real = await importOriginal<typeof import("../src/v213/public-options-admission")>();
  return { ...real, admitPublicOption: vi.fn(real.admitPublicOption) };
});

// TEST SEAM: transparent facade over the REAL frozen pinned view; labelled json rejection only.
vi.mock("../src/v213/public-snapshot", async importOriginal => {
  const real = await importOriginal<typeof import("../src/v213/public-snapshot")>();
  return { ...real, pinPublicSnapshot: vi.fn(async (...args: Parameters<typeof real.pinPublicSnapshot>) => {
    const view = await real.pinPublicSnapshot(...args);
    const existing = trace.views.get(view) as typeof view | undefined;
    if (existing) return existing;
    const facade: typeof view = {
      ...view,
      text: view.text.bind(view),
      hasSealedObject: view.hasSealedObject?.bind(view),
      async json<T>(keys: string[]): Promise<T | null> {
        trace.logical.push([...keys]);
        keys.forEach(key => trace.events.push("read:" + key));
        const hook = trace.hook && keys.includes(trace.hook.key) ? trace.hook : null;
        if (hook?.mode === "reject") {
          if (hook.cutoff !== undefined) {
            vi.setSystemTime(hook.cutoff);
            trace.events.push("clock:" + hook.cutoff);
          }
          trace.events.push("reject:" + hook.key);
          throw new Error("SYNTHETIC_VIEW_READ_REJECTION");
        }
        const result = await view.json<T>(keys);
        if (hook?.mode === "advance") {
          if (hook.cutoff === undefined) throw new Error("CUTOFF_REQUIRED");
          vi.setSystemTime(hook.cutoff);
          trace.events.push("clock:" + hook.cutoff);
        }
        return result;
      },
    };
    trace.views.set(view, facade);
    return facade;
  }) };
});

// TEST SEAM: log real identity queries; the legacy case adds ONLY metadata, never records/indexes.
vi.mock("../src/v213/identity-shards", async importOriginal => {
  const real = await importOriginal<typeof import("../src/v213/identity-shards")>();
  return { ...real, loadIdentityCatalogForQuery: vi.fn(async (...args: Parameters<typeof real.loadIdentityCatalogForQuery>) => {
    trace.queries.push(args[1]);
    trace.events.push("identity:" + args[1]);
    const found = await real.loadIdentityCatalogForQuery(...args);
    if (!trace.legacy || !found) return found;
    const decorated: GlobalIdentityCatalog = {
      ...found, conflicts: { "XNAS:ACME": [{ reason: "SYNTHETIC_LEGACY_METADATA" }] }, conflicts_count: 1,
    };
    trace.metadata.push({ recordsSame: decorated.records === found.records, indexesSame: decorated.indexes === found.indexes });
    return decorated;
  }) };
});

// TEST SEAM: REAL loader first. Approved boundary faults change only ticker; expiry hook returns SAME result.
vi.mock("../src/v213/market-observations", async importOriginal => {
  const real = await importOriginal<typeof import("../src/v213/market-observations")>();
  return { ...real, loadDetailedOptionObservation: vi.fn(async (...args: Parameters<typeof real.loadDetailedOptionObservation>) => {
    const found = await real.loadDetailedOptionObservation(...args);
    if (found.status !== "FOUND") return found;
    trace.events.push("found:" + found.ticker);
    if (trace.afterFoundClock !== null) {
      vi.setSystemTime(trace.afterFoundClock);
      trace.events.push("clock:" + trace.afterFoundClock);
    }
    if (trace.fault === null) return found;
    const altered = { ...found };
    if (trace.fault === "missing") delete altered.ticker;
    else altered.ticker = { empty: "", whitespace: "   ", "space-body": "AB CD.ST" }[trace.fault];
    trace.faultEvidence.push({ before: found.ticker, after: altered.ticker, quoteSame: altered.quote === found.quote });
    return altered;
  }) };
});

const realAdmission = await vi.importActual<typeof import("../src/v213/public-options-admission")>("../src/v213/public-options-admission");
const NOW = Date.parse("2026-09-30T12:00:00Z");
const WINDOW_START = Date.parse("2026-09-30T23:59:59Z");
const CUTOFF = Date.parse("2026-10-01T00:00:00Z");
const RUN = "20260930T120000Z-abcdefabcde4";
const OPTIONS = "v213:options:v2";
const SYM = "v213:identity:v2:sym:";
const NAME = "v213:identity:v2:name:";
const styles = ["text", "flex"] as const;
type Style = typeof styles[number];
type Row = [string, string, string, string, string, string | null, string, string, number, ...unknown[]];

function us(symbol: string, venue = "XNAS"): Row {
  return [symbol, venue, "US", "United States", "Synthetic Issuer", null, "COMMON_STOCK", "USD", 0];
}
function stockholm(symbol: string): Row {
  const r = us(symbol, "XSTO");
  r[2] = "SWEDEN"; r[3] = "Sweden"; r[7] = "SEK";
  return r;
}
function pair(row: Row): Row[] {
  const second = structuredClone(row);
  second[6] = "PREFERRED_STOCK";
  return [structuredClone(row), second];
}
function iso(ms: number): string { return new Date(ms).toISOString().replace(/\.000Z$/, "Z"); }
function cycle(ticker: string, currency = "USD", now = NOW) {
  return {
    ticker, currency, strategy: "COVERED_CALL", expiry: iso(now + 21 * 86400_000).slice(0, 10),
    dte: 21, spot: 300, multiplier: 100, quote_basis: "delayed", timestamp: iso(now - 30 * 60_000),
    source: "Synthetic delayed observation", provenance: "https://synthetic.invalid/options",
    rights_status: "unadmitted_third_party", suggestions: [{
      role: "HIGH_STRIKE", strike: 330, bid: 2, ask: 2.1, mid: 2.05, limit_price: 2.05,
      premium_per_contract: 205, period_yield: 2.05 / 300, annualized_yield: 2.05 / 300 * 365 / 21,
      upside_to_strike: 330 / 300 - 1, delta: 0.18, delta_basis: "QUOTED_IV", iv: 0.4,
      oi: 900, volume: 50, spread_pct: 0.0488,
    }],
  };
}
class TracedKv extends MemoryKv {
  reads: string[] = [];
  rejectKey: string | null = null;
  override async get<T = string>(key: string, type?: "text" | "json"): Promise<T | string | null> {
    this.reads.push(key);
    if (key === this.rejectKey) throw new Error("SYNTHETIC_KV_READ_REJECTION");
    return super.get<T>(key, type);
  }
}
interface Setup {
  key?: string;
  currency?: string;
  rows?: Row[];
  emptyBuckets?: string[];
  style?: Style;
  now?: number;
  names?: [string, string, string, string][];
  mutate?: (lazy: Record<string, any>) => void;
}
async function sha(text: string): Promise<string> {
  return Array.from(new Uint8Array(await crypto.subtle.digest("SHA-256", new TextEncoder().encode(text))),
    b => b.toString(16).padStart(2, "0")).join("");
}
async function sealed(setup: Setup = {}) {
  const now = setup.now ?? NOW;
  const key = setup.key ?? "ACME";
  const kv = new TracedKv();
  kv.values.set("v213:top20-report:latest", JSON.stringify({ synthetic: "B2" }));
  kv.values.set("last_successful_pipeline_timestamp", iso(now - 60_000));
  await sealUnboundReport(kv, RUN);
  const feeds = ["a", "b"].map(id => ({
    id: "synthetic-" + id, url: "https://synthetic.invalid/" + id, retrieved_at: iso(now - 30 * 60_000),
    sha256: id.repeat(64),
  }));
  const lazy: Record<string, any> = {
    [OPTIONS]: { schema: "v213-options-v2", generated_at: iso(now - 30 * 60_000),
      options: { [key]: { monthly: cycle(key, setup.currency, now) } } },
  };
  const bucketRows = new Map<string, Row[]>((setup.emptyBuckets ?? []).map(bucket => [bucket, []]));
  for (const row of setup.rows ?? []) {
    const bucket = row[0].charAt(0);
    if (!bucketRows.has(bucket)) bucketRows.set(bucket, []);
    bucketRows.get(bucket)!.push(row);
  }
  for (const [bucket, rows] of bucketRows) {
    lazy[SYM + bucket] = { schema: "v213-identity-shard-v2", kind: "symbol", bucket,
      generated_at: iso(now - 30 * 60_000), feeds, rows };
  }
  for (const [name, bucket, symbol, venue] of setup.names ?? []) {
    const normalized = normalizeCompanyName(name);
    const b = identityNameBucket(normalized);
    const logical = NAME + b;
    lazy[logical] ??= { schema: "v213-identity-shard-v2", kind: "name", bucket: String(b),
      generated_at: iso(now - 30 * 60_000), rows: [] };
    lazy[logical].rows.push([normalized, bucket, symbol, venue]);
  }
  setup.mutate?.(lazy);
  const sealKey = "snapshot:" + RUN + ":" + SNAPSHOT_SEAL_KEY;
  const seal = JSON.parse(kv.values.get(sealKey)!);
  const blobs = new Map<string, string>();
  for (const [logical, value] of Object.entries(lazy)) {
    const body = JSON.stringify(value);
    const digest = await sha(body);
    seal.objects[logical] = { sha256: digest, utf8_bytes: new TextEncoder().encode(body).length };
    const blob = "blob:v1:" + digest;
    blobs.set(logical, blob);
    kv.values.set(blob, body);
  }
  const sealText = JSON.stringify(seal);
  kv.values.set(sealKey, sealText);
  const pointer = JSON.parse(kv.values.get("snapshot:current")!);
  pointer.seal_sha256 = await sha(sealText);
  kv.values.set("snapshot:current", JSON.stringify(pointer));
  const env = {
    PUBLIC_CACHE: asKv(kv), TENANT_PRIVATE_CACHE: asKv(new MemoryKv()),
    EPHEMERAL_SECURITY_CACHE: asKv(new MemoryKv()), V21_TOP20_MAX_AGE_SECONDS: "7200",
    V213_LINE_PRESENTATION: setup.style ?? "text",
  };
  return { env, kv, blobs };
}
type Fixture = Awaited<ReturnType<typeof sealed>>;

function clearTrace(): void {
  trace.logical = []; trace.queries = []; trace.events = []; trace.metadata = []; trace.faultEvidence = [];
  vi.mocked(admission.admitPublicOption).mockClear();
}
function logAdmission(impl: typeof admission.admitPublicOption): void {
  vi.mocked(admission.admitPublicOption).mockImplementation((subject, nowMs) => {
    const time = nowMs ?? Date.now();
    const result = impl(subject, nowMs);
    const ticker = (subject as { ticker?: unknown } | null)?.ticker;
    trace.events.push("admit:" + String(ticker) + ":" + time + ":" + result.ok);
    return result;
  });
}
function optIn(...tickers: string[]): void {
  // TEST SEAM: each positive test names ONLY its synthetic sealed tickers; others stay REAL.
  admitSyntheticTickers(...tickers);
  const impl = vi.mocked(admission.admitPublicOption).getMockImplementation();
  if (!impl) throw new Error("ADMISSION_IMPLEMENTATION_MISSING");
  logAdmission(impl);
}
function timed(ticker: string): void {
  // TEST SEAM D1: synthetic expiry-ORDER only, NOT a catalog review_valid_through test.
  logAdmission((subject, nowMs = Date.now()) => {
    const key = (subject as { ticker?: unknown } | null)?.ticker;
    return key === ticker && nowMs < CUTOFF
      ? { ok: true, provider_id: SYNTHETIC_PROVIDER_ID }
      : realAdmission.admitPublicOption(subject, nowMs);
  });
}
beforeEach(() => {
  vi.useFakeTimers({ toFake: ["Date"] });
  vi.setSystemTime(NOW);
  vi.clearAllMocks();
  trace.views = new WeakMap();
  trace.hook = null; trace.legacy = false; trace.fault = null; trace.afterFoundClock = null;
  clearTrace();
  resetAdmissionToReal();
  logAdmission(realAdmission.admitPublicOption);
  vi.stubGlobal("fetch", vi.fn(async () => { throw new Error("NETWORK_FORBIDDEN"); }));
});
afterEach(() => {
  resetAdmissionToReal();
  trace.hook = null; trace.legacy = false; trace.fault = null; trace.afterFoundClock = null;
  vi.useRealTimers(); vi.unstubAllGlobals();
});

const utf8 = (value: unknown) => new TextEncoder().encode(JSON.stringify(value)).length;
function bounds(messages: LineOutboundMessage[]): void {
  expect(() => assertLineMessages(messages)).not.toThrow();
  expect(messages.length).toBeGreaterThanOrEqual(1);
  expect(messages.length).toBeLessThanOrEqual(5);
  for (const message of messages) {
    if (message.type === "text") expect(message.text.length).toBeLessThanOrEqual(4900);
    else {
      expect(message.altText.length).toBeLessThanOrEqual(400);
      const bubbles = message.contents.contents as Record<string, unknown>[];
      expect(bubbles.length).toBeGreaterThanOrEqual(1);
      expect(bubbles.length).toBeLessThanOrEqual(5);
      expect(utf8(message.contents)).toBeLessThanOrEqual(48000);
      for (const bubble of bubbles) expect(utf8(bubble)).toBeLessThanOrEqual(28000);
    }
  }
}
async function answer(fixture: Fixture, command = "ACME 每月期權") {
  const result = await v213PublicLineAnswer(fixture.env as never, parseQuery(command));
  if (!Array.isArray(result)) throw new Error("EXPECTED_REAL_CALLER_MESSAGES");
  bounds(result);
  return JSON.stringify(result);
}
function noQuote(reply: string): void {
  for (const marker of ["330.00", "$2.05", "2.05 SEK", "OI 900", "成交量 50"]) expect(reply).not.toContain(marker);
}
function positive(reply: string, currency = "USD"): void {
  expect(reply).toContain(currency === "USD" ? "$330.00" : "330.00 SEK");
  for (const marker of ["IDENTITY_CONFLICT", "SOURCE_UNAVAILABLE", "IDENTIFIER_UNAVAILABLE", "IDENTITY_CATALOG_UNAVAILABLE",
    "身分已驗證", "已驗證身分", "不存在", "多來源交叉驗證"]) expect(reply).not.toContain(marker);
}
function conflict(reply: string, keys: string[], names = ["Synthetic Issuer"]): void {
  expect(reply).toContain("IDENTITY_CONFLICT");
  const sorted = [...keys].sort();
  expect(reply).toContain("顯示 " + Math.min(5, sorted.length) + "/" + sorted.length);
  expect(reply).toContain(sorted.slice(0, 5).join("、"));
  for (const key of sorted.slice(5)) expect(reply).not.toContain(key);
  expect(reply).toContain("不選擇");
  expect(reply).not.toContain("請以精確代號");
  for (const name of names) expect(reply).not.toContain(name);
  noQuote(reply);
}
function logicalIdentity(): string[] {
  return trace.logical.flat().filter(k => k.startsWith("v213:identity:"));
}
function physicalIdentity(fixture: Fixture): string[] {
  const reverse = new Map([...fixture.blobs].map(([logical, blob]) => [blob, logical]));
  return fixture.kv.reads.map(key => reverse.get(key)).filter((key): key is string => !!key?.startsWith("v213:identity:"));
}
function reads(fixture: Fixture, logical: string[], physical = logical): void {
  expect(logicalIdentity()).toEqual(logical);
  expect(physicalIdentity(fixture)).toEqual(physical);
}
function expiry(reply: string, ticker: string, query: string | null, readKey: string | null, rejects = false): void {
  expect(reply).toContain(admission.OPTION_RIGHTS_NOT_ADMITTED);
  expect(reply).not.toContain("IDENTITY_CONFLICT");
  noQuote(reply);
  expect(vi.mocked(admission.admitPublicOption)).toHaveBeenCalledTimes(2);
  const expected = [
    "admit:" + ticker + ":" + WINDOW_START + ":true",
    "found:" + ticker,
    ...(query === null ? [] : ["identity:" + query]),
    ...(readKey === null ? [] : ["read:" + readKey]),
    "clock:" + CUTOFF,
    ...(rejects ? ["reject:" + readKey] : []),
    "admit:" + ticker + ":" + CUTOFF + ":false",
  ];
  expect(trace.events.filter(e => !e.startsWith("read:") || e.startsWith("read:v213:identity:"))).toEqual(expected);
}
const sevenVenues = ["XNAS", "XNYS", "ARCX", "BATS", "IEX", "MEMX", "PSX"];
const sevenRows = () => sevenVenues.flatMap(venue => pair(us("ACME", venue)));

describe("B2 integrated caller (D1-D5 synthetic seam scope)", () => {
  for (const style of styles) {
    it("B2-01: " + style + " US same-key conflict ignores agreeing Stockholm sibling", async () => {
      optIn("ACME");
      const f = await sealed({ style, rows: [...pair(us("ACME")), stockholm("ACME")] });
      const reply = await answer(f);
      conflict(reply, ["XNAS:ACME"]);
      expect(reply).not.toContain("XSTO:ACME");
      expect(trace.queries).toEqual(["ticker ACME"]);
      reads(f, [SYM + "A"]);
    });
  }

  for (const key of ["SIVE.ST", "SIVE"]) {
    it("B2-02: exact matched " + key + " with SEK uses SIVE.ST", async () => {
      optIn(key);
      const f = await sealed({ key, currency: "SEK", rows: [...pair(stockholm("SIVE")), us("SIVE")] });
      const reply = await answer(f, key + " 每月期權");
      conflict(reply, ["XSTO:SIVE"]);
      expect(reply).not.toContain("XNAS:SIVE");
      expect(trace.queries).toEqual(["SIVE.ST"]);
      reads(f, [SYM + "S"]);
    });
  }

  for (const target of ["US", "SWEDEN"]) {
    it("B2-03: contradictory sibling cannot poison " + target, async () => {
      const key = target === "US" ? "ACME" : "ACME.ST";
      const currency = target === "US" ? "USD" : "SEK";
      const rows = target === "US" ? [us("ACME"), ...pair(stockholm("ACME"))] : [stockholm("ACME"), ...pair(us("ACME"))];
      optIn(key);
      const f = await sealed({ key, currency, rows });
      positive(await answer(f, key + " 每月期權"), currency);
      expect(trace.queries).toEqual([target === "US" ? "ticker ACME" : "ACME.ST"]);
      reads(f, [SYM + "A"]);
    });
  }

  for (const style of styles) {
    it("B2-04: " + style + " counts all seven keys, displays five sorted complete keys", async () => {
      optIn("ACME");
      const f = await sealed({ style, rows: sevenRows() });
      conflict(await answer(f), sevenVenues.map(v => v + ":ACME"));
      expect(trace.queries).toEqual(["ticker ACME"]);
      reads(f, [SYM + "A"]);
    });
  }

  for (const alias of ["TSMC", "台積電"]) {
    for (const home of ["absent", "conflicting"]) {
      it("B2-05: ADR " + alias + " requires no " + home + " home identity", async () => {
        optIn("TSM");
        const homeRow: Row = ["2330", "TWSE", "TAIWAN", "Taiwan", "Home Synthetic", null, "COMMON_STOCK", "TWD", 0];
        const f = await sealed({ key: "TSM", rows: [us("TSM"), ...(home === "conflicting" ? pair(homeRow) : [])] });
        const reply = await answer(f, alias + " 每月期權");
        positive(reply);
        expect(reply).toContain("ADR TSM");
        expect(reply).toContain("2330.TW");
        expect(reply).toContain("1 ADR＝5");
        expect(trace.queries).toEqual(["ticker TSM"]);
        reads(f, [SYM + "T"]);
      });
    }
    it("B2-05: ADR " + alias + " refuses quoted TSM conflict despite agreeing home", async () => {
      optIn("TSM");
      const f = await sealed({ key: "TSM", rows: [...pair(us("TSM")),
        ["2330", "TWSE", "TAIWAN", "Taiwan", "Home Synthetic", null, "COMMON_STOCK", "TWD", 0]] });
      const reply = await answer(f, alias + " 每月期權");
      conflict(reply, ["XNAS:TSM"]);
      expect(reply).not.toContain("TWSE:2330");
      expect(trace.queries).toEqual(["ticker TSM"]);
      reads(f, [SYM + "T"]);
    });
  }

  it("B2-06: provenance-only row differences are not identity evidence", async () => {
    optIn("ACME");
    const other = us("ACME"); other[8] = 1;
    const f = await sealed({ rows: [us("ACME"), other] });
    positive(await answer(f));
    expect(trace.queries).toEqual(["ticker ACME"]);
    reads(f, [SYM + "A"]);
  });
  it("B2-06: TEST SEAM legacy metadata-only decorator remains no-evidence", async () => {
    optIn("ACME");
    trace.legacy = true;
    const f = await sealed({ rows: [us("ACME")] });
    positive(await answer(f));
    expect(trace.metadata).toEqual([{ recordsSame: true, indexesSame: true }]);
    expect(trace.queries).toEqual(["ticker ACME"]);
    reads(f, [SYM + "A"]);
  });

  for (const mode of ["missing", "malformed", "kv-error", "facade-error"]) {
    it("B2-07: " + mode + " has no identity/absence claim", async () => {
      optIn("BRK-B");
      const f = await sealed({ key: "BRK-B", rows: mode === "missing" ? [] : pair(us("BRK-B")),
        mutate: mode === "malformed" ? lazy => { lazy[SYM + "B"].schema = "INVALID_SYNTHETIC_SCHEMA"; } : undefined });
      if (mode === "kv-error") {
        // TEST SEAM: throw in KV; the REAL snapshot-seal catches and returns null (not R631).
        f.kv.rejectKey = f.blobs.get(SYM + "B")!;
      }
      if (mode === "facade-error") {
        // TEST SEAM D2: escaping view rejection explicitly exercises R631; not a KV claim.
        trace.hook = { key: SYM + "B", mode: "reject" };
      }
      positive(await answer(f, "BRK-B 每月期權"));
      expect(trace.queries).toEqual(["ticker BRK-B"]);
      reads(f, [SYM + "B"], mode === "missing" || mode === "facade-error" ? [] : [SYM + "B"]);
      expect(trace.events.includes("reject:" + SYM + "B")).toBe(mode === "facade-error");
    });
  }
  it("B2-07: spelling mismatch does not invent BRK.B for matched BRK-B", async () => {
    optIn("BRK-B");
    const f = await sealed({ key: "BRK-B", rows: pair(us("BRK.B")), emptyBuckets: ["A"] });
    positive(await answer(f, "BRK-B 每月期權"));
    expect(trace.queries).toEqual(["ticker BRK-B"]);
    // I120 assigns generatedAt even when take() selects no rows: no A probe is needed.
    reads(f, [SYM + "B"]);
  });

  for (const style of styles) {
    it("B2-08: " + style + " synthetic expiry-ORDER during identity await precedes conflict", async () => {
      vi.setSystemTime(WINDOW_START);
      timed("ACME");
      const f = await sealed({ now: WINDOW_START, style, rows: pair(us("ACME")) });
      // TEST SEAM D1: clock advances AFTER real identity object read, before B2 rights recheck.
      trace.hook = { key: SYM + "A", mode: "advance", cutoff: CUTOFF };
      const reply = await answer(f);
      expiry(reply, "ACME", "ticker ACME", SYM + "A");
      reads(f, [SYM + "A"]);
    });
  }

  const refusals = ["invalid-row", "stale-row", "stale-doc", "invalid-schema", "invalid-date", "absent-doc", "foreign-ticker", "rights"] as const;
  for (const mode of refusals) {
    it("B2-09: " + mode + " pre-FOUND refusal adds zero identity reads", async () => {
      if (mode !== "rights") optIn("ACME");
      const f = await sealed({ rows: pair(us("ACME")), mutate: lazy => {
        const doc = lazy[OPTIONS];
        if (mode === "invalid-row") doc.options.ACME.monthly.suggestions[0].bid = 3;
        if (mode === "stale-row") doc.options.ACME.monthly.timestamp = iso(NOW - 7 * 3600_000);
        if (mode === "stale-doc") doc.generated_at = iso(NOW - 7 * 3600_000);
        if (mode === "invalid-schema") doc.schema = "INVALID_SYNTHETIC_SCHEMA";
        if (mode === "invalid-date") doc.generated_at = "not-a-time";
        if (mode === "absent-doc") delete lazy[OPTIONS];
        if (mode === "foreign-ticker") doc.options.ACME.monthly.ticker = "OTHER";
        // A sibling quote must never replace a refusal on the first matched key.
        doc.options["ACME.ST"] = { monthly: cycle("ACME.ST", "SEK") };
      } });
      const reply = await answer(f);
      const reason = mode === "rights" ? admission.OPTION_RIGHTS_NOT_ADMITTED
        : mode === "absent-doc" ? "OPTION_DATA_NOT_ADMITTED"
        : mode === "stale-doc" ? "期權快照已逾時"
        : mode === "invalid-schema" || mode === "invalid-date" ? "封存期權物件無法驗證或讀取"
        : "封存之期權觀察未通過驗證";
      expect(reply).toContain(reason); noQuote(reply);
      expect(reply).not.toContain("IDENTITY_CONFLICT");
      expect(trace.queries).toEqual([]);
      reads(f, []);
      expect(trace.events.some(e => e.startsWith("found:"))).toBe(false);
    });
  }

  async function compareBaseline(setup: Setup, key: string, expected: string[], command = key + " 每月期權") {
    optIn(key);
    const baseline = await sealed(setup);
    const loaded = await loadDetailedOptionObservation(await pinPublicSnapshot(baseline.env as never), [key], "monthly", NOW);
    expect(loaded.status).toBe("FOUND");
    reads(baseline, []);
    clearTrace();
    const f = await sealed(setup);
    positive(await answer(f, command));
    expect(trace.queries).toEqual(["ticker " + key]);
    reads(f, expected);
    expect(logicalIdentity().length).toBeLessThanOrEqual(2);
    expect(physicalIdentity(f).length).toBeLessThanOrEqual(2);
  }
  // Correct the plan's fixture premise, not the bound: take() sets generatedAt BEFORE matching rows.
  // Empty/mismatched valid symbol shards need one read; I155's actual A-probe needs no initial take().
  it("B2-10: empty B adds exactly one symbol object without an unnecessary A probe", async () => {
    await compareBaseline({ key: "BRK-B", emptyBuckets: ["B", "A"] }, "BRK-B", [SYM + "B"]);
  });
  it("B2-10: empty A symbol object is fetched once", async () => {
    await compareBaseline({ emptyBuckets: ["A"] }, "ACME", [SYM + "A"]);
  });
  it("B2-10: populated B adds one symbol object and no name channel", async () => {
    await compareBaseline({ key: "BRK-B", rows: [us("BRK-B")] }, "BRK-B", [SYM + "B"]);
  });
  it("B2-10: authentic sixteen-character matched key reaches the A-probe, not name channel", async () => {
    // Real quote alphabet allows 16 chars; I's symbol alphabet allows 15. A share-class query
    // normalizes to this exact sealed key through real optionTickerKeys; no boundary fault.
    const key = "ABCDEFGHIJKLM-AB";
    expect(key.length).toBe(16);
    await compareBaseline({ key, emptyBuckets: ["A"] }, key, [SYM + "A"], "ABCDEFGHIJKLM AB 每月期權");
    expect(trace.events).toContain("found:" + key);
  });

  for (const style of styles) {
    it("B2-11: " + style + " bounded conflict never leaks partial candidate or quote", async () => {
      optIn("ACME");
      const rows = sevenRows();
      const longName = "SYNTHETIC_LONG_CANDIDATE_" + "Q".repeat(270);
      rows.forEach(row => { row[4] = longName; });
      const f = await sealed({ style, rows });
      conflict(await answer(f), sevenVenues.map(v => v + ":ACME"), [longName]);
      reads(f, [SYM + "A"]);
    });
  }

  for (const style of styles) {
    for (const key of ["ACME", "TSM"]) {
      it("B2-12: " + style + " real catalog NONE denies " + key + " without opt-in", async () => {
        const f = await sealed({ key, style, rows: pair(us(key)) });
        const reply = await answer(f, key === "TSM" ? "TSMC 每月期權" : "ACME 每月期權");
        expect(catalog.production_quote_provider_selected).toBe(false);
        expect(reply).toContain(admission.OPTION_RIGHTS_NOT_ADMITTED);
        noQuote(reply);
        expect(reply).not.toContain("IDENTITY_CONFLICT");
        expect(trace.queries).toEqual([]);
        reads(f, []);
        expect(vi.mocked(admission.admitPublicOption)).toHaveBeenCalledTimes(1);
      });
    }
  }

  it("B2-13: name route preserves matched BRK.B.ST and never checks BRK-B.ST", async () => {
    optIn("BRK.B.ST");
    const exact = stockholm("BRK.B");
    exact.push(["合成瑞典", "OFFICIAL"]);
    const f = await sealed({ key: "BRK.B.ST", currency: "SEK",
      rows: [exact, ...pair(stockholm("BRK-B"))], names: [["合成瑞典", "B", "BRK.B", "XSTO"]] });
    positive(await answer(f, "合成瑞典 每月期權"), "SEK");
    expect(trace.queries).toEqual(["合成瑞典", "BRK.B.ST"]);
    const nameKey = NAME + identityNameBucket(normalizeCompanyName("合成瑞典"));
    reads(f, [nameKey, SYM + "B", SYM + "B"], [nameKey, SYM + "B"]);
    const found = trace.events.indexOf("found:BRK.B.ST");
    expect(found).toBeGreaterThanOrEqual(0);
    expect(trace.events.slice(found + 1).filter(e => e.startsWith("read:"))).toEqual(["read:" + SYM + "B"]);
    expect(trace.queries).not.toContain("BRK-B.ST");
  });
  it("B2-18: direct BRK.B.ST query reaches the sealed dash key BRK-B.ST before FOUND", async () => {
    // Real optionTickerKeys: a class-share dot becomes the sealed "-" key (BRK.B.ST -> ["BRK-B.ST"]); the identity target is
    // that matched key, and the dot-spelled rows in the same shard are not its evidence.
    optIn("BRK-B.ST");
    const f = await sealed({ key: "BRK-B.ST", currency: "SEK", rows: [stockholm("BRK-B"), ...pair(stockholm("BRK.B"))] });
    positive(await answer(f, "BRK.B.ST \u6bcf\u6708\u671f\u6b0a"), "SEK");  // the same monthly-options command as above
    expect(trace.events).toContain("found:BRK-B.ST");
    expect(trace.queries).toEqual(["BRK-B.ST"]);
    reads(f, [SYM + "B"]);
  });

  it("B2-14: authentic eleven-character Stockholm body is no-evidence with zero reads", async () => {
    const key = "ABCDEFGHIJK.ST";
    optIn(key);
    const f = await sealed({ key, currency: "SEK", rows: pair(stockholm("ABCDEFGHIJK")) });
    positive(await answer(f, key + " 每月期權"), "SEK");
    expect(trace.events).toContain("found:" + key);
    expect(trace.queries).toEqual([]);
    reads(f, []);
  });
  it("B2-14: TEST SEAM defensive boundary space body is not a sealed-reachable claim", async () => {
    optIn("ACME");
    trace.fault = "space-body";
    const f = await sealed({ currency: "SEK", rows: [...pair(stockholm("AB CD")), ...pair(stockholm("AB-CD"))] });
    positive(await answer(f), "SEK");
    expect(trace.faultEvidence).toEqual([{ before: "ACME", after: "AB CD.ST", quoteSame: true }]);
    expect(trace.queries).toEqual([]);
    reads(f, []);
  });

  for (const fault of ["missing", "empty", "whitespace"] as const) {
    it("B2-15: TEST SEAM defensive boundary " + fault + " matched key, not sealed-reachable", async () => {
      optIn("ACME");
      trace.fault = fault;
      const f = await sealed({ rows: pair(us("ACME")) });
      positive(await answer(f));
      expect(trace.faultEvidence).toEqual([{ before: "ACME",
        after: fault === "missing" ? undefined : fault === "empty" ? "" : "   ", quoteSame: true }]);
      expect(trace.queries).toEqual([]);
      reads(f, []);
    });
  }

  for (const key of ["BRK-B", "SIVE.ST"]) {
    it("B2-16: supported " + key + " cannot enter adversarial name channel", async () => {
      const swedish = key.endsWith(".ST");
      const symbol = swedish ? "SIVE" : "BRK-B";
      const currency = swedish ? "SEK" : "USD";
      const row = swedish ? stockholm(symbol) : us(symbol);
      optIn(key);
      const f = await sealed({ key, currency, rows: [row, ...pair(us("NOISE"))],
        names: [[key, "N", "NOISE", "XNAS"], ["ticker " + key, "N", "NOISE", "XNAS"]] });
      positive(await answer(f, key + " 每月期權"), currency);
      expect(trace.queries).toEqual([swedish ? key : "ticker " + key]);
      reads(f, [SYM + (swedish ? "S" : "B")]);
    });
  }

  for (const style of styles) {
    it("B2-17: " + style + " synthetic expiry-ORDER still wins with no identity lookup", async () => {
      const key = "ABCDEFGHIJK.ST";
      vi.setSystemTime(WINDOW_START);
      timed(key);
      const f = await sealed({ key, currency: "SEK", now: WINDOW_START, style, rows: pair(stockholm("ABCDEFGHIJK")) });
      // TEST SEAM D1: real FOUND completes, then clock closes before caller continues; result untouched.
      trace.afterFoundClock = CUTOFF;
      const reply = await answer(f, key + " 每月期權");
      expiry(reply, key, null, null);
      expect(trace.queries).toEqual([]);
      reads(f, []);
    });
    it("B2-17: " + style + " synthetic expiry-ORDER still wins after escaping identity read error", async () => {
      vi.setSystemTime(WINDOW_START);
      timed("ACME");
      const f = await sealed({ now: WINDOW_START, style, rows: pair(us("ACME")) });
      // TEST SEAM D2: advance then reject facade json; actual KV errors alone are swallowed below B2.
      trace.hook = { key: SYM + "A", mode: "reject", cutoff: CUTOFF };
      const reply = await answer(f);
      expiry(reply, "ACME", "ticker ACME", SYM + "A", true);
      expect(trace.queries).toEqual(["ticker ACME"]);
      reads(f, [SYM + "A"], []);
    });
  }
});
