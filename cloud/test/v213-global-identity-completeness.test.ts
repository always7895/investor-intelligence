// I2-03 (BATCH04 matrix): structural identity-catalog validity is never promoted to complete market coverage. A valid catalog
// can lack listings and unobserved contradictory rows, so these rows pin the documented limit; nothing here is a completeness
// proof. Synthetic records and the BATCH04 builder fixture in a fake KV only: no network and no LINE send.
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import fixture from "../../tests/fixtures/identity-batch04-functional.json";
import { parseQuery } from "../src/core";
import type { LineOutboundMessage } from "../src/line-messages";
import { handleGlobalEquityLookup } from "../src/v213/global-equity-lookup";
import { resolveGlobalIdentity, type GlobalIdentityCatalog, type GlobalIdentityRecord } from "../src/v213/global-identity";
import { evaluateCatalogAdmission, validateCatalogIntegrity } from "../src/v213/global-identity-reader";
import { loadIdentityCatalogForQuery } from "../src/v213/identity-shards";
import { pinPublicSnapshot, type PublicSnapshotView } from "../src/v213/public-snapshot";
import { asKv, MemoryKv } from "./fake-kv";

const NOT_PROOF = "\u9019\u4e0d\u4ee3\u8868\u8a72\u8b49\u5238\u4e0d\u5b58\u5728";  // the ABS1 scope notice: "not proof of absence"

function listing(venue: string, symbol: string, name: string): GlobalIdentityRecord {
  return {
    venue, market: "US", country: "United States", symbol, native_symbol: symbol, security_name: name, native_name: null,
    security_class: "COMMON_STOCK", currency: "USD", source_feed: "nasdaq-listed",
    source_url: "https://www.nasdaqtrader.com/dynamic/SymDir/nasdaqlisted.txt",
  };
}
/** A structurally valid candidate: indexes rebuilt exactly as the reader's canonical rebuild (last row of a key wins). */
function catalogOf(records: GlobalIdentityRecord[]): GlobalIdentityCatalog {
  const byVenue: Record<string, number> = {};
  const bySymbol: Record<string, number[]> = {};
  const byName: Record<string, number[]> = {};
  records.forEach((record, index) => {
    byVenue[`${record.venue}:${record.symbol}`] = index;
    (bySymbol[record.symbol.toUpperCase()] ??= []).push(index);
    const names = (byName[record.security_name.trim().toLowerCase().replace(/\s+/g, " ")] ??= []);
    if (!names.includes(index)) names.push(index);
  });
  return {
    schema_version: 1, contract_id: "v213-global-identity-v1", generated_at: "2026-09-15T00:00:00.000Z",
    collection_receipts_sha256: "0".repeat(64), records_count: records.length, records,
    indexes: { by_venue_and_symbol: byVenue, by_symbol: bySymbol, by_name: byName },
  };
}
const sealedView: PublicSnapshotView = {
  runId: "i2-synthetic", kind: "snapshot", integrity: "sealed",
  async text() { return null; },
  async json<T>() { return null as T | null; },
};
function environment() {
  const kv = new MemoryKv();
  for (const [key, body] of Object.entries(fixture.values)) kv.values.set(key, body);
  return { PUBLIC_CACHE: asKv(kv), TENANT_PRIVATE_CACHE: asKv(new MemoryKv()), EPHEMERAL_SECURITY_CACHE: asKv(new MemoryKv()),
    V213_LINE_PRESENTATION: "text", V21_TOP20_MAX_AGE_SECONDS: "7200" };
}
const textOf = (messages: LineOutboundMessage[]) => messages.map(m => (m.type === "text" ? m.text : "")).join("\n");

beforeEach(() => {
  vi.useFakeTimers({ toFake: ["Date"] });
  vi.setSystemTime(new Date("2026-09-15T12:01:00Z"));
  vi.stubGlobal("fetch", vi.fn(() => { throw new Error("I2_NETWORK_FORBIDDEN"); }));
});
afterEach(() => { vi.useRealTimers(); vi.unstubAllGlobals(); });

describe("I2-03 structural validity is not market completeness", () => {
  it("a valid catalog with a listing removed is still valid: validity is not coverage, and never authority", () => {
    const full = catalogOf([listing("NASDAQ", "ORBA", "Orbit Alpha"), listing("NYSE", "ORBB", "Orbit Beta")]);
    const partial = catalogOf([listing("NASDAQ", "ORBA", "Orbit Alpha")]);
    for (const catalog of [full, partial]) {
      const candidate = validateCatalogIntegrity(catalog);
      expect(candidate).not.toBeNull();
      const assessment = evaluateCatalogAdmission(sealedView, candidate);
      expect([assessment.scope, assessment.isAuthoritative]).toEqual(["ADMISSION_DEFER", false]);
    }
    expect(resolveGlobalIdentity(full, "ORBB").status).toBe("RESOLVED");
    const missing = resolveGlobalIdentity(partial, "ORBB");
    expect(missing.status).toBe("UNAVAILABLE");
    // Snapshot-scoped absence wording only, never a statement about the listing itself.
    expect("reason" in missing && missing.reason.startsWith("IDENTIFIER_UNAVAILABLE:")).toBe(true);
  });

  it("a completeness claim cannot ride on a valid catalog (closed root keys)", () => {
    const base = catalogOf([listing("NASDAQ", "ORBA", "Orbit Alpha")]);
    expect(validateCatalogIntegrity({ ...base })).not.toBeNull();
    for (const claim of [{ complete: true }, { coverage: "COMPLETE_MARKET" }, { markets_complete: ["US"] }, { completeness: 1 }]) {
      expect(validateCatalogIntegrity({ ...base, ...claim }), JSON.stringify(claim)).toBeNull();
    }
  });

  it("declared conflict metadata is not evidence: an unobserved contradictory row is decided only once observed", () => {
    const declared = { ...catalogOf([listing("NASDAQ", "ACMX", "Acme Orbit")]), conflicts_count: 0, conflicts: {} };
    expect(validateCatalogIntegrity(declared)).not.toBeNull();
    expect(resolveGlobalIdentity(declared, "ACMX").status).toBe("RESOLVED");
    // The same valid shape with the contradictory variant observed: still structurally valid, still declaring 0 conflicts.
    const observed = {
      ...catalogOf([listing("NASDAQ", "ACMX", "Acme Orbit"), listing("NASDAQ", "ACMX", "Acme Variant")]),
      conflicts_count: 0, conflicts: {},
    };
    expect(validateCatalogIntegrity(observed)).not.toBeNull();
    const conflict = resolveGlobalIdentity(observed, "ACMX");
    expect(conflict.status).toBe("UNAVAILABLE");
    expect("reason" in conflict && conflict.reason.startsWith("IDENTITY_CONFLICT:")).toBe(true);
  });

  it("the runtime shard catalog is query-scoped: its count is the selected rows, never a directory or market total", async () => {
    const view = await pinPublicSnapshot(environment() as never);
    expect(view.integrity).toBe("sealed");
    const acme = await loadIdentityCatalogForQuery(view, "ACME");
    expect([acme?.records_count, acme?.records.length, fixture.document.records]).toEqual([2, 2, 12]);
    // No coverage or conflict-count field exists for a consumer to read completeness from.
    expect(Object.keys(acme ?? {}).sort()).toEqual(
      ["collection_receipts_sha256", "contract_id", "generated_at", "indexes", "records", "records_count", "schema_version"]);
    const absent = await loadIdentityCatalogForQuery(view, "\u80a1\u7968 ABSENT");
    expect(absent?.records_count).toBe(0);
  });

  it("an absence in a present, valid, non-empty shard catalog is shown with the not-proof-of-absence notice", async () => {
    const messages = await handleGlobalEquityLookup(environment() as never, parseQuery("\u80a1\u7968 ABSENT")) as LineOutboundMessage[];
    expect(Array.isArray(messages)).toBe(true);
    const text = textOf(messages);
    expect(text).toContain("IDENTIFIER_UNAVAILABLE:");
    expect(text).toContain(NOT_PROOF);
    // The same present catalog still resolves its own listing: the absence is about this snapshot's rows only.
    const good = textOf(await handleGlobalEquityLookup(environment() as never, parseQuery("GOOD")) as LineOutboundMessage[]);
    expect(good).toContain("Healthy Orbit");
  });
});
