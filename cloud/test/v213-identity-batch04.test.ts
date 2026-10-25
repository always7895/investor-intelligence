// BATCH04: genuine Python builder/seal fixture, fake KV only. No public option admission or sends.
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import fixture from "../../tests/fixtures/identity-batch04-functional.json";
import { parseQuery } from "../src/core";
import { assertLineMessages, type LineOutboundMessage } from "../src/line-messages";
import { handleGlobalEquityLookup } from "../src/v213/global-equity-lookup";
import { identityNameBucket, loadIdentityCatalogForQuery } from "../src/v213/identity-shards";
import { resolveGlobalIdentity } from "../src/v213/global-identity";
import { pinPublicSnapshot } from "../src/v213/public-snapshot";
import { asKv, MemoryKv } from "./fake-kv";

const trace = vi.hoisted(() => ({ queries: [] as string[], failures: {} as Record<string, string>, legacy: 0 }));
vi.mock("../src/v213/identity-shards", async importOriginal => {
  const real = await importOriginal<typeof import("../src/v213/identity-shards")>();
  return { ...real, loadIdentityCatalogForQuery: vi.fn(async (view, query) => {
    trace.queries.push(query);
    // U1-03: an injected read outcome for one exact query; every other query reads the real sealed shards.
    const failure = trace.failures[query];
    if (failure === "throw") throw new Error("U1_SYNTHETIC_READ_FAILURE");
    if (failure === "null") return null;
    const catalog = await real.loadIdentityCatalogForQuery(view, query);
    return failure === "mismatch" && catalog
      ? { ...catalog, records: catalog.records.map(r => ({ ...r, security_name: `${r.security_name} (other)` })) } : catalog;
  }) };
});
vi.mock("../src/v213/global-identity-reader", async importOriginal => {
  const real = await importOriginal<typeof import("../src/v213/global-identity-reader")>();
  return { ...real, loadGlobalIdentityCatalog: vi.fn(async view => {
    trace.legacy += 1;
    return real.loadGlobalIdentityCatalog(view);
  }) };
});
const SEAL = `snapshot:${fixture.run}:v213:snapshot-seal:v1`;
const SYM = "v213:identity:v2:sym:";
const NAME = "v213:identity:v2:name:";
const sha = async (body: string) => Array.from(new Uint8Array(await crypto.subtle.digest("SHA-256", new TextEncoder().encode(body))),
  n => n.toString(16).padStart(2, "0")).join("");

async function environment(style: "text" | "flex", replacements: Record<string, unknown> = {}) {
  const kv = new MemoryKv();
  for (const [key, body] of Object.entries(fixture.values)) kv.values.set(key, body);
  const seal = JSON.parse(kv.values.get(SEAL)!);
  for (const [logical, value] of Object.entries(replacements)) {
    const body = JSON.stringify(value), digest = await sha(body);
    seal.objects[logical] = { sha256: digest, utf8_bytes: new TextEncoder().encode(body).length };
    kv.values.set("blob:v1:" + digest, body);
  }
  if (Object.keys(replacements).length) {
    const body = JSON.stringify(seal);
    kv.values.set(SEAL, body);
    const pointer = JSON.parse(kv.values.get("snapshot:current")!);
    pointer.seal_sha256 = await sha(body);
    kv.values.set("snapshot:current", JSON.stringify(pointer));
  }
  return { kv, env: { PUBLIC_CACHE: asKv(kv), TENANT_PRIVATE_CACHE: asKv(new MemoryKv()),
    EPHEMERAL_SECURITY_CACHE: asKv(new MemoryKv()), V213_LINE_PRESENTATION: style, V21_TOP20_MAX_AGE_SECONDS: "7200" } };
}
function strings(value: unknown): string[] {
  if (!value || typeof value !== "object") return [];
  if (Array.isArray(value)) return value.flatMap(strings);
  const obj = value as Record<string, unknown>;
  return [...(obj.type === "text" && typeof obj.text === "string" ? [obj.text] : []), ...Object.values(obj).flatMap(strings)];
}
async function answer(f: Awaited<ReturnType<typeof environment>>, query: string) {
  const messages = await handleGlobalEquityLookup(f.env as never, parseQuery(query)) as LineOutboundMessage[];
  expect(Array.isArray(messages)).toBe(true);
  assertLineMessages(messages);
  return { messages, text: strings(messages).join("\n"), raw: JSON.stringify(messages) };
}
function ambiguityObjects() {
  const source = fixture.document.symbol_shards.A;
  const rows = Array.from({ length: 12 }, (_, i) => ["A" + String(i).padStart(2, "0"), "NASDAQ STOCKHOLM", "SWEDEN", "Sweden",
    "\u{1f6f0}".repeat(120) + String(i), null, "COMMON_STOCK", "SEK", 4, ["軌道", "WIKIDATA_LABEL"]]);
  const bucket = identityNameBucket("軌道");
  return { [SYM + "A"]: { ...source, rows },
    [NAME + bucket]: { schema: source.schema, kind: "name", bucket: String(bucket), generated_at: fixture.stamp,
      rows: rows.map(r => ["軌道", "A", r[0], r[1]]) } };
}
beforeEach(() => {
  vi.useFakeTimers({ toFake: ["Date"] });
  vi.setSystemTime(new Date("2026-09-15T12:01:00Z"));
  trace.queries = [];
  trace.failures = {};
  trace.legacy = 0;
  vi.stubGlobal("fetch", vi.fn(() => { throw new Error("BATCH04_NETWORK_FORBIDDEN"); }));
});
afterEach(() => { vi.useRealTimers(); vi.unstubAllGlobals(); });

describe("BATCH04 identity real caller", () => {
  it("B04-01 Python conflict variants survive seal, loader and name-only seed", async () => {
    for (const style of ["text", "flex"] as const) {
      const f = await environment(style);
      const view = await pinPublicSnapshot(f.env as never);
      expect(view.integrity).toBe("sealed");
      const catalog = await loadIdentityCatalogForQuery(view, "公司 Acme Orbit");
      expect(catalog?.records.filter(r => r.symbol === "ACME")).toHaveLength(2);
      for (const query of ["公司 Acme Orbit", "ACME"]) {
        const reply = await answer(f, query);
        expect(reply.text).toContain("IDENTITY_CONFLICT:");
        expect(reply.text).toContain("NASDAQ:ACME");
        expect(reply.text).not.toContain("原因不明");
        expect(reply.raw).not.toContain('"label":"每月期權"');
      }
      expect((await answer(f, "SIVE.ST")).text).toContain("Synthetic Orbit");
      expect((await answer(f, "GOOD")).text).toContain("Healthy Orbit");
    }
  });

  it("B04-02 altered Python lazy bytes refuse only that identity", async () => {
    const f = await environment("text");
    const blob = fixture.blobs["v213:identity:v2:sym:A"];
    f.kv.values.set(blob, f.kv.values.get(blob)!.replace("Acme Orbit", "Acme Forged"));
    const reply = await answer(f, "ACME");
    expect(reply.text).toContain("原因不明");
    expect(reply.text).not.toContain("Acme Forged");
    expect(reply.text).not.toContain("IDENTITY_CONFLICT:");
    expect((await answer(f, "GOOD")).text).toContain("Healthy Orbit");
  });

  it("B04-03 missing and admitted-empty catalogs never prove security absence", async () => {
    for (const style of ["text", "flex"] as const) for (const mode of ["missing", "empty"] as const) {
      const f = await environment(style, mode === "empty" ? { [SYM + "A"]: { ...fixture.document.symbol_shards.A, rows: [] } } : {});
      if (mode === "missing") f.kv.values.delete(fixture.blobs["v213:identity:v2:sym:A"]);
      const reply = await answer(f, "股票 ABSENT");
      expect(reply.text).toContain("原因不明");
      expect(reply.text).toContain("這不代表該證券不存在、已下市、沒有期權或不具交易權利");
      expect(reply.text).not.toContain("publisher migration deferred");
      expect(reply.text).not.toContain("SEC 本機快取");
      if (style === "flex") {
        expect(reply.raw).toContain("TOP20");
        expect(reply.raw).not.toContain('"label":"每月期權"');
      }
    }
  });

  it("B04-04 Unicode candidate prefix is complete, bounded and equal in text and Flex", async () => {
    const visible: string[][] = [];
    for (const style of ["text", "flex"] as const) {
      trace.queries = [];
      const reply = await answer(await environment(style, ambiguityObjects()), "公司 軌道");
      expect(trace.queries).toEqual(["公司 軌道", "A00.ST", "A01.ST", "A02.ST"]);
      const lines = reply.text.split("\n").filter(line => /A\d\d \(NASDAQ STOCKHOLM/.test(line)).map(line => line.replace(/^• /, ""));
      expect(lines.length).toBeGreaterThanOrEqual(3);
      expect(lines.length).toBeLessThanOrEqual(10);
      expect(lines.map(line => "• " + line).join("\n").length).toBeLessThanOrEqual(3000);
      lines.forEach((line, i) => expect(line).toContain("\u{1f6f0}".repeat(120) + i));
      expect(reply.text).toContain(`已顯示 ${lines.length}/12 筆候選`);
      expect(reply.text).toContain("不代表不存在、不支援或已驗證");
      expect(reply.text).toContain("本次未驗證");
      if (style === "flex") {
        const raw = reply.raw;
        expect(raw).toContain('"text":"A00.ST"');
        expect(raw).toContain('"text":"A02.ST"');
        expect(raw).not.toContain('"text":"A03.ST"');
      }
      visible.push(lines);
    }
    expect(visible[0]).toEqual(visible[1]);
  });

  it("B04-05 name seed cannot lose an observed variant to an incomplete canonical index", async () => {
    const f = await environment("text");
    const catalog = await loadIdentityCatalogForQuery(await pinPublicSnapshot(f.env as never), "公司 Acme Orbit");
    expect(catalog).not.toBeNull();
    // Explicit catalog-boundary seam: a corrupted index, not a normally generated shard catalog.
    catalog!.indexes.by_symbol.ACME = [1];
    const result = resolveGlobalIdentity(catalog!, "公司 Acme Orbit");
    expect(result.status).toBe("UNAVAILABLE");
    expect("reason" in result && result.reason).toContain("IDENTITY_CONFLICT:");
  });

  it("U1-03 a failed, missing or different certification read reuses neither the name catalog nor a legacy catalog", async () => {
    const query = "\u516c\u53f8 \u8ecc\u9053";
    // Non-vacuous: the name-query catalog DOES hold A01, so reusing it would certify A01.ST.
    const seed = await loadIdentityCatalogForQuery(await pinPublicSnapshot((await environment("text", ambiguityObjects())).env as never), query);
    expect(resolveGlobalIdentity(seed, "A01.ST").status).toBe("RESOLVED");
    for (const style of ["text", "flex"] as const) for (const failure of ["throw", "null", "mismatch"]) {
      trace.queries = [];
      trace.failures = { "A01.ST": failure };
      trace.legacy = 0;
      const reply = await answer(await environment(style, ambiguityObjects()), query);
      // A failure still spends its validation call (sequential, no retry); the fourth candidate stays unchecked.
      expect(trace.queries, failure).toEqual([query, "A00.ST", "A01.ST", "A02.ST"]);
      expect(trace.legacy, failure).toBe(0);
      expect(reply.text, failure).toContain("A00.ST");
      expect(reply.text, failure).toContain("A02.ST");
      expect(reply.text, failure).not.toContain("A01.ST");
      if (style === "flex") {
        expect(reply.raw, failure).toContain('"text":"A00.ST"');
        expect(reply.raw, failure).toContain('"text":"A02.ST"');
        expect(reply.raw, failure).not.toContain('"text":"A01.ST"');
      }
    }
  });

  it("U1-03 no certified route leaves only the safe navigation", async () => {
    const query = "\u516c\u53f8 \u8ecc\u9053";
    for (const style of ["text", "flex"] as const) {
      trace.queries = [];
      trace.failures = { "A00.ST": "throw", "A01.ST": "null", "A02.ST": "mismatch" };
      const reply = await answer(await environment(style, ambiguityObjects()), query);
      expect(trace.queries).toEqual([query, "A00.ST", "A01.ST", "A02.ST"]);
      expect(trace.legacy).toBe(0);
      expect(reply.text).not.toMatch(/A\d\d\.ST/);
      if (style === "flex") {
        expect(reply.raw).toContain('"text":"TOP20"');
        expect(reply.raw).toContain('"text":"\u9078\u55ae"');
        expect(reply.raw).not.toMatch(/"text":"A\d\d\.ST"/);
      }
    }
  });
});
