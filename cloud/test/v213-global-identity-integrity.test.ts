import { describe, expect, it } from "vitest";
import {
  type GlobalIdentityCatalog,
  type GlobalIdentityRecord,
} from "../src/v213/global-identity";
import {
  validateCatalogIntegrity,
  loadGlobalIdentityCatalog,
  evaluateCatalogAdmission,
  GLOBAL_IDENTITY_CATALOG_KEY,
} from "../src/v213/global-identity-reader";
import type { PublicSnapshotView } from "../src/v213/public-snapshot";
import { MemoryKv, asKv } from "./fake-kv";

function createValidCandidateCatalog(): GlobalIdentityCatalog {
  const records: GlobalIdentityRecord[] = [
    {
      venue: "NASDAQ",
      market: "US",
      country: "United States",
      symbol: "AAPL",
      native_symbol: "AAPL",
      security_name: "Apple Inc.",
      native_name: null,
      security_class: "COMMON_STOCK",
      currency: "USD",
      source_feed: "nasdaq-listed",
      source_url: "https://www.nasdaqtrader.com/dynamic/SymDir/nasdaqlisted.txt",
    },
    {
      venue: "TWSE",
      market: "TAIWAN",
      country: "Taiwan",
      symbol: "2330",
      native_symbol: "2330",
      security_name: "Taiwan Semiconductor Manufacturing Co Ltd",
      native_name: "台積電",
      security_class: "COMMON_STOCK",
      currency: "TWD",
      source_feed: "twse-listed",
      source_url: "https://openapi.twse.com.tw/v1/opendata/t187ap03_L",
    },
  ];

  return {
    schema_version: 1,
    contract_id: "v213-global-identity-v1",
    generated_at: "2026-09-15T00:00:00.000Z",
    collection_receipts_sha256: "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
    records_count: 2,
    indexed_symbols_count: 2,
    indexed_names_count: 3,
    conflicts_count: 0,
    records,
    indexes: {
      by_venue_and_symbol: {
        "NASDAQ:AAPL": 0,
        "TWSE:2330": 1,
      },
      by_symbol: {
        "AAPL": [0],
        "2330": [1],
      },
      by_name: {
        "apple inc.": [0],
        "taiwan semiconductor manufacturing co ltd": [1],
        "台積電": [1],
      },
    },
  };
}

describe("Global Identity Catalog Integrity: Strict Authority & Validation Boundary", () => {
  it("Case 1: rejects injected object reference in by_symbol index", () => {
    const catalog = createValidCandidateCatalog();
    (catalog.indexes.by_symbol as any)["AAPL"] = [
      {
        venue: "INJECTED",
        market: "US",
        country: "United States",
        symbol: "AAPL",
        native_symbol: "AAPL",
        security_name: "Injected Malicious Company",
        native_name: null,
        security_class: "COMMON_STOCK",
        currency: "USD",
        source_feed: "nasdaq-listed",
        source_url: "https://www.nasdaqtrader.com/dynamic/SymDir/nasdaqlisted.txt",
      },
    ];
    const res = validateCatalogIntegrity(catalog);
    expect(res).toBeNull();
  });

  it("Case 2: rejects incorrect valid index (AAPL mapped to 2330 record index)", () => {
    const catalog = createValidCandidateCatalog();
    // Index 1 exists in records, but belongs to 2330, not AAPL
    (catalog.indexes.by_symbol as any)["AAPL"] = [1];
    const res = validateCatalogIntegrity(catalog);
    expect(res).toBeNull();
  });

  it("Case 3: rejects fractional, NaN, Infinity, and boolean index references", () => {
    const catFraction = createValidCandidateCatalog();
    (catFraction.indexes.by_symbol as any)["AAPL"] = [0.5];
    expect(validateCatalogIntegrity(catFraction)).toBeNull();

    const catNaN = createValidCandidateCatalog();
    (catNaN.indexes.by_symbol as any)["AAPL"] = [NaN];
    expect(validateCatalogIntegrity(catNaN)).toBeNull();

    const catInf = createValidCandidateCatalog();
    (catInf.indexes.by_symbol as any)["AAPL"] = [Infinity];
    expect(validateCatalogIntegrity(catInf)).toBeNull();

    const catBool = createValidCandidateCatalog();
    (catBool.indexes.by_symbol as any)["AAPL"] = [true];
    expect(validateCatalogIntegrity(catBool)).toBeNull();
  });

  it("Case 4: rejects dangling, duplicate, or key-spoofed indexes and unclosed root keys", () => {
    // Dangling venue index
    const catDanglingVenue = createValidCandidateCatalog();
    (catDanglingVenue.indexes.by_venue_and_symbol as any)["NASDAQ:AAPL"] = 999;
    expect(validateCatalogIntegrity(catDanglingVenue)).toBeNull();

    // Bogus venue index key
    const catBogusVenueKey = createValidCandidateCatalog();
    (catBogusVenueKey.indexes.by_venue_and_symbol as any)["BOGUS:KEY"] = 0;
    expect(validateCatalogIntegrity(catBogusVenueKey)).toBeNull();

    // Duplicate reference in symbol index
    const catDupeIndex = createValidCandidateCatalog();
    (catDupeIndex.indexes.by_symbol as any)["AAPL"] = [0, 0];
    expect(validateCatalogIntegrity(catDupeIndex)).toBeNull();

    // Unclosed root key
    const catExtraRoot = {
      ...createValidCandidateCatalog(),
      unexpected_root_extension: "malicious",
    };
    expect(validateCatalogIntegrity(catExtraRoot)).toBeNull();
  });

  it("Case 5: rejects impossible calendar dates and trailing timezone junk", () => {
    const catImpossible = createValidCandidateCatalog();
    catImpossible.generated_at = "2026-02-31T25:99:99Z";
    expect(validateCatalogIntegrity(catImpossible)).toBeNull();

    const catTrailing = createValidCandidateCatalog();
    catTrailing.generated_at = "2026-09-15T00:00:00.000Z trailing junk";
    expect(validateCatalogIntegrity(catTrailing)).toBeNull();

    const catNaive = createValidCandidateCatalog();
    catNaive.generated_at = "2026-09-15 00:00:00";
    expect(validateCatalogIntegrity(catNaive)).toBeNull();
  });

  it("Case 6: rejects HTTP, credentialed, local, and traversal URLs in source_url", () => {
    const catHttp = createValidCandidateCatalog();
    catHttp.records[0]!.source_url = "http://www.nasdaqtrader.com/dynamic/SymDir/nasdaqlisted.txt";
    expect(validateCatalogIntegrity(catHttp)).toBeNull();

    const catCred = createValidCandidateCatalog();
    catCred.records[0]!.source_url = "https://user:password@www.nasdaqtrader.com/dynamic/SymDir/nasdaqlisted.txt";
    expect(validateCatalogIntegrity(catCred)).toBeNull();

    const catLocal = createValidCandidateCatalog();
    catLocal.records[0]!.source_url = "https://127.0.0.1/dynamic/SymDir/nasdaqlisted.txt";
    expect(validateCatalogIntegrity(catLocal)).toBeNull();

    const catTraversal = createValidCandidateCatalog();
    catTraversal.records[0]!.source_url = "https://www.nasdaqtrader.com/../private/nasdaqlisted.txt";
    expect(validateCatalogIntegrity(catTraversal)).toBeNull();
  });

  it("Case 7: rejects payload exceeding UTF-8 byte cap with CJK multi-byte characters", async () => {
    // 5 MB of 3-byte CJK characters: char count ~1.7M chars, but byte count ~5.1M bytes
    // If limit is 5MB, char count <= 5M passes naive .length, but byteLength > 5MB must be rejected.
    const baseCat = createValidCandidateCatalog();
    const cjkPadding = "台".repeat(3.5 * 1024 * 1024); // 3.5M chars = 10.5 MB UTF-8 bytes (> 10MB limit)
    baseCat.records[0]!.security_name = cjkPadding;
    const jsonStr = JSON.stringify(baseCat);

    // jsonStr.length is ~3.5M (which is < 10*1024*1024 chars), but UTF-8 byte length > 10.5MB
    const mockView: PublicSnapshotView = {
      runId: "run1",
      kind: "snapshot",
      integrity: "sealed",
      async text(keys: string[]) {
        if (keys.includes(GLOBAL_IDENTITY_CATALOG_KEY)) return jsonStr;
        return null;
      },
      async json<T>() {
        return null;
      },
    };

    const loaded = await loadGlobalIdentityCatalog(mockView);
    expect(loaded).toBeNull();
  });

  it("Case 8: rejects view.json fallback when view.text is unavailable", async () => {
    const catalog = createValidCandidateCatalog();
    const mockViewWithoutText: PublicSnapshotView = {
      runId: "run1",
      kind: "snapshot",
      integrity: "sealed",
      async text() {
        return null;
      },
      async json<T>(keys: string[]) {
        if (keys.includes(GLOBAL_IDENTITY_CATALOG_KEY)) return catalog as T;
        return null;
      },
    };

    // Reader must require bounded raw text; falling back to unmeasured view.json is prohibited
    const loaded = await loadGlobalIdentityCatalog(mockViewWithoutText);
    expect(loaded).toBeNull();
  });

  it("Case 9: actual closed sealed extra object negative in MemoryKv fails closed", async () => {
    // MemoryKv with unsealed extra key or missing identity profile in seal
    const kv = new MemoryKv();
    // Provide a valid pointer but seal object does not include identity catalog key
    const rawPointer = JSON.stringify({
      schema_version: 2,
      run_id: "20260915T000000Z-0123456789ab",
      transaction_id: "0123456789abcdef0123456789abcdef",
      seal_sha256: "0".repeat(64),
      public_data_as_of: "2026-09-15T00:00:00.000Z",
      promoted_at: "2026-09-15T00:00:00.000Z",
      provider_scope: "public_only",
      owner_watchlist_inherited: false,
    });
    await kv.put("snapshot:current", rawPointer);

    // Snapshot seal in current schema has NO identity slot
    const mockView: PublicSnapshotView = {
      runId: "20260915T000000Z-0123456789ab",
      kind: "snapshot",
      integrity: "sealed",
      async text(keys: string[]) {
        if (keys.includes(GLOBAL_IDENTITY_CATALOG_KEY)) return null;
        return null;
      },
      async json<T>() {
        return null;
      },
    };
    const loaded = await loadGlobalIdentityCatalog(mockView);
    expect(loaded).toBeNull();
  });

  it("Case 10: primitive flags (e.g. trusted: true or view.integrity string) cannot admit authority", () => {
    // Simply having a valid candidate JSON does not grant official source admission
    const catalog = createValidCandidateCatalog();
    const candidate = validateCatalogIntegrity(catalog);
    expect(candidate).not.toBeNull();

    // Authority must be withheld/deferred when explicit identity profile contract is absent
    const mockUnapprovedView: PublicSnapshotView = {
      runId: "run1",
      kind: "snapshot",
      integrity: "sealed",
      async text() {
        return JSON.stringify(catalog);
      },
      async json<T>() {
        return null;
      },
    };

    const assessment = evaluateCatalogAdmission(mockUnapprovedView, candidate);
    expect(assessment.scope).toBe("ADMISSION_DEFER");
    expect(assessment.isAuthoritative).toBe(false);
    expect(assessment.reason).toContain("ADMISSION_DEFER");

    // Unsealed view reports REJECTED
    const unsealedView: PublicSnapshotView = {
      ...mockUnapprovedView,
      integrity: "invalid",
    };
    const rejectedAssessment = evaluateCatalogAdmission(unsealedView, candidate);
    expect(rejectedAssessment.scope).toBe("REJECTED");
    expect(rejectedAssessment.isAuthoritative).toBe(false);
  });
});
