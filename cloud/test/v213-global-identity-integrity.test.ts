import { describe, expect, it, vi } from "vitest";
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
import { pinPublicSnapshot, scopePublicSnapshot, type PublicSnapshotView } from "../src/v213/public-snapshot";
import { SNAPSHOT_OBJECT_KEYS, SNAPSHOT_SEAL_KEY } from "../src/v213/snapshot-seal";
import { buildSyntheticSealedReplay, makeOfflineEnv, SYNTHETIC_RUN } from "./synthetic-sealed-replay-fixture";

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

  it("Case 9: real pinned sealed view excludes unsealed identity KV extras", async () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockRejectedValue(
      new Error("OFFLINE_IDENTITY_NEGATIVE_NETWORK_FORBIDDEN"),
    );
    try {
      const { kv, reportRaw, seal } = await buildSyntheticSealedReplay();
      const { env, privateKv, securityKv } = makeOfflineEnv(kv);
      const catalog = createValidCandidateCatalog();
      const candidate = validateCatalogIntegrity(catalog);
      expect(candidate).not.toBeNull(); // Structural test data only, never identity authority.
      const raw = JSON.stringify(catalog);
      const extraKeys = [
        GLOBAL_IDENTITY_CATALOG_KEY,
        `snapshot:${SYNTHETIC_RUN}:${GLOBAL_IDENTITY_CATALOG_KEY}`,
      ];
      const sealKey = `snapshot:${SYNTHETIC_RUN}:${SNAPSHOT_SEAL_KEY}`;
      const originalValues = new Map(kv.values);
      expect(originalValues.get("snapshot:current")).toBeDefined();
      expect(originalValues.get(sealKey)).toBe(seal.text);

      // Extras exist on the SAME KV before a fresh scope/pin, not behind an old cached view.
      for (const key of extraKeys) {
        expect(originalValues.has(key)).toBe(false);
        await kv.put(key, raw);
        expect(kv.values.get(key)).toBe(raw);
      }
      expect(kv.values.size).toBe(originalValues.size + extraKeys.length);
      for (const [key, value] of originalValues) {
        expect(kv.values.get(key)).toBe(value); // Pointer, seal and every core member unchanged.
      }

      const getSpy = vi.spyOn(kv, "get"); // Delegates to the real MemoryKv implementation.
      try {
        const view = await pinPublicSnapshot(scopePublicSnapshot(env));
        const readsAfterPin = getSpy.mock.calls.length;
        expect(view.kind).toBe("snapshot");
        expect(view.integrity).toBe("sealed");
        expect(view.runId).toBe(SYNTHETIC_RUN);
        expect(SNAPSHOT_OBJECT_KEYS).toHaveLength(13);
        expect(getSpy.mock.calls.map(([key]) => key)).toEqual([
          "snapshot:current",
          sealKey,
          ...SNAPSHOT_OBJECT_KEYS.map(key => `snapshot:${SYNTHETIC_RUN}:${key}`),
        ]);
        // Positive control traverses the actual verified map; invalid/legacy/null views fail.
        expect(await view.text(["v213:top20-report:latest"])).toBe(reportRaw);
        expect(await view.text([GLOBAL_IDENTITY_CATALOG_KEY])).toBeNull();
        expect(await view.json([GLOBAL_IDENTITY_CATALOG_KEY])).toBeNull();
        const loaded = await loadGlobalIdentityCatalog(view);
        expect(loaded).toBeNull();

        const rejected = evaluateCatalogAdmission(view, loaded);
        expect(rejected.scope).toBe("REJECTED");
        expect(rejected.reason).toContain("CANDIDATE_INVALID");
        expect(rejected.isAuthoritative).toBe(false);
        expect(rejected.catalog).toBeNull();
        // Separately supplied structural data is deferred, not injected into the sealed map.
        const deferred = evaluateCatalogAdmission(view, candidate);
        expect(deferred.scope).toBe("ADMISSION_DEFER");
        expect(deferred.reason).toContain("ADMISSION_DEFER");
        expect(deferred.isAuthoritative).toBe(false);
        expect(deferred.catalog).toBe(candidate);

        expect(getSpy.mock.calls).toHaveLength(readsAfterPin);
        for (const key of extraKeys) {
          expect(getSpy.mock.calls.map(([readKey]) => readKey)).not.toContain(key);
          expect(kv.values.get(key)).toBe(raw);
        }
        for (const [key, value] of originalValues) {
          expect(kv.values.get(key)).toBe(value);
        }
        expect(privateKv.reads).toBe(0);
        expect(securityKv.reads).toBe(0);
        expect(fetchSpy).not.toHaveBeenCalled();
      } finally {
        getSpy.mockRestore();
      }
    } finally {
      fetchSpy.mockRestore();
    }
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
