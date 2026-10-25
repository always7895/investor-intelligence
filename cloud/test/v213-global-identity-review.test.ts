import { describe, expect, it } from "vitest";
import {
  type GlobalIdentityCatalog,
  type GlobalIdentityRecord,
  resolveGlobalIdentity,
  parseIdentityRequest,
} from "../src/v213/global-identity";
import {
  loadGlobalIdentityCatalog,
  GLOBAL_IDENTITY_CATALOG_KEY,
} from "../src/v213/global-identity-reader";
import type { PublicSnapshotView } from "../src/v213/public-snapshot";

function createReviewSyntheticCatalog(): GlobalIdentityCatalog {
  const records: GlobalIdentityRecord[] = [
    // US NASDAQ
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
      source_url: "https://example.test/nasdaq",
    },
    // Amsterdam (Euronext Amsterdam) - specifically .AS
    {
      venue: "Euronext Amsterdam",
      market: "EUROPE",
      country: "Netherlands",
      symbol: "ASML",
      native_symbol: "ASML",
      security_name: "ASML Holding N.V.",
      native_name: null,
      security_class: "COMMON_STOCK",
      currency: "EUR",
      source_feed: "synthetic-euronext",
      source_url: "https://example.test/euronext",
    },
    // Taiwan TWSE (specifically .TW, NOT .TWO / TPEx)
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
      source_url: "https://example.test/twse",
    },
    // Korea KOSPI / KRX (specifically .KS, NOT .KQ / KOSDAQ)
    {
      venue: "KOSPI",
      market: "KOREA",
      country: "Korea",
      symbol: "005930",
      native_symbol: "005930",
      security_name: "Samsung Electronics Co Ltd",
      native_name: "삼성전자",
      security_class: "COMMON_STOCK",
      currency: "KRW",
      source_feed: "synthetic-krx",
      source_url: "https://example.test/krx",
    },
    // Symbol & Name collision test cases:
    // 1) Ticker "BOX" (Box, Inc. on NYSE)
    {
      venue: "NYSE",
      market: "US",
      country: "United States",
      symbol: "BOX",
      native_symbol: "BOX",
      security_name: "Box, Inc.",
      native_name: null,
      security_class: "COMMON_STOCK",
      currency: "USD",
      source_feed: "other-us-listed",
      source_url: "https://example.test/other",
    },
    // 2) Company whose exact security name is "BOX" (synthetic company on NASDAQ)
    {
      venue: "NASDAQ",
      market: "US",
      country: "United States",
      symbol: "BXCO",
      native_symbol: "BXCO",
      security_name: "BOX",
      native_name: null,
      security_class: "COMMON_STOCK",
      currency: "USD",
      source_feed: "nasdaq-listed",
      source_url: "https://example.test/nasdaq",
    },
  ];

  const by_venue_and_symbol: Record<string, number> = {};
  const by_symbol: Record<string, number[]> = {};
  const by_name: Record<string, number[]> = {};

  for (let idx = 0; idx < records.length; idx++) {
    const r = records[idx]!;
    by_venue_and_symbol[`${r.venue}:${r.symbol}`] = idx;
    by_symbol[r.native_symbol] = by_symbol[r.native_symbol] || [];
    by_symbol[r.native_symbol]!.push(idx);

    const norm = r.security_name.toLowerCase().trim().replace(/\s+/g, " ");
    by_name[norm] = by_name[norm] || [];
    if (!by_name[norm]!.includes(idx)) {
      by_name[norm]!.push(idx);
    }
  }

  return {
    schema_version: 1,
    contract_id: "v213-global-identity-v1",
    generated_at: "2026-09-15T00:00:00.000Z",
    collection_receipts_sha256: "0000000000000000000000000000000000000000000000000000000000000000",
    records_count: records.length,
    records,
    indexes: {
      by_venue_and_symbol,
      by_symbol,
      by_name,
    },
  };
}

describe("Astra Defect A: Generic SIVE handling without invented issuer or attempted Sweden market", () => {
  const catalog = createReviewSyntheticCatalog();

  it("resolves bare SIVE with generic algorithm identical to any uncataloged symbol", () => {
    const resSive = resolveGlobalIdentity(catalog, "SIVE");
    const resGeneric = resolveGlobalIdentity(catalog, "UNKNOWNXYZ");

    expect(resSive.status).toBe("UNAVAILABLE");
    expect(resGeneric.status).toBe("UNAVAILABLE");

    // Defect A check: No isSive flag
    expect((resSive as any).isSive).toBeUndefined();

    // Defect A check: No attemptedMarket without explicit suffix
    expect((resSive as any).attemptedMarket).toBeUndefined();

    // Defect A check: Reason identifies requested ticker only, no invented issuer name or OTC mention
    if (resSive.status === "UNAVAILABLE") {
      expect(resSive.reason).not.toContain("Sivers");
      expect(resSive.reason).not.toContain("OTC");
      expect(resSive.reason).toContain("SIVE");
    }
  });

  it("handles case variants (sive, Sive, SIVE) identically to generic symbols", () => {
    for (const variant of ["sive", "Sive", "SIVE"]) {
      const res = resolveGlobalIdentity(catalog, variant);
      expect(res.status).toBe("UNAVAILABLE");
      expect((res as any).isSive).toBeUndefined();
      expect((res as any).attemptedMarket).toBeUndefined();
    }
  });
});

describe("Astra Defect B: Cross-venue isolation & exact canonical venue matching", () => {
  const catalog = createReviewSyntheticCatalog();

  it("does not match ASML.DE to Euronext Amsterdam simply because Europe region matches", () => {
    // Catalog has ASML on Euronext Amsterdam (.AS), NOT Frankfurt/XETRA (.DE)
    const res = resolveGlobalIdentity(catalog, "ASML.DE");
    expect(res.status).toBe("UNAVAILABLE");
    if (res.status === "UNAVAILABLE") {
      expect(res.attemptedMarket).toBe("EUROPE");
    }
  });

  it("does not match 2330.TWO (TPEx) to TWSE simply because Taiwan market matches", () => {
    // Catalog has 2330 on TWSE (.TW), NOT TPEx (.TWO)
    const res = resolveGlobalIdentity(catalog, "2330.TWO");
    expect(res.status).toBe("UNAVAILABLE");
  });

  it("does not match 005930.KQ (KOSDAQ) to KOSPI simply because Korea market matches", () => {
    // Catalog has 005930 on KOSPI (.KS), NOT KOSDAQ (.KQ)
    const res = resolveGlobalIdentity(catalog, "005930.KQ");
    expect(res.status).toBe("UNAVAILABLE");
  });
});

describe("Astra Defect C: Bare query matches ALL candidates across symbol & name without first-wins priority", () => {
  const catalog = createReviewSyntheticCatalog();

  it("returns NEEDS_MARKET_SELECTION when bare query matches both a symbol and a company name", () => {
    // "BOX" matches symbol for Box, Inc. (NYSE) AND exact name for BXCO (NASDAQ)
    const res = resolveGlobalIdentity(catalog, "BOX");
    expect(res.status).toBe("NEEDS_MARKET_SELECTION");
    if (res.status === "NEEDS_MARKET_SELECTION") {
      expect(res.candidates.length).toBe(2);
      const symbols = res.candidates.map(c => c.symbol);
      expect(symbols).toContain("BOX");
      expect(symbols).toContain("BXCO");
    }
  });

  it("restricts search space when explicit operator (股票 vs 公司) is provided", () => {
    const resStock = resolveGlobalIdentity(catalog, "股票 BOX");
    expect(resStock.status).toBe("RESOLVED");
    if (resStock.status === "RESOLVED") {
      expect(resStock.record.symbol).toBe("BOX");
    }

    const resCompany = resolveGlobalIdentity(catalog, "公司 BOX");
    expect(resCompany.status).toBe("RESOLVED");
    if (resCompany.status === "RESOLVED") {
      expect(resCompany.record.symbol).toBe("BXCO");
    }
  });
});

describe("Astra Defect D & E: Prototype safety, bounded parsing, and strict catalog integrity", () => {
  const catalog = createReviewSyntheticCatalog();

  it("guards against prototype pollution keys (__proto__, constructor, toString)", () => {
    for (const protoKey of ["__proto__", "constructor", "toString", "valueOf"]) {
      const res = resolveGlobalIdentity(catalog, protoKey);
      expect(res.status).toBe("UNAVAILABLE");
    }
  });

  it("rejects catalog with tampered records_count in validateCatalogIntegrity", async () => {
    const tampered = {
      ...catalog,
      records_count: 999999, // Mismatches catalog.records.length
    };
    const mockView: PublicSnapshotView = {
      runId: "run1",
      kind: "snapshot",
      integrity: "sealed",
      async json<T>(keys: string[]): Promise<T | null> {
        if (keys.includes(GLOBAL_IDENTITY_CATALOG_KEY)) return tampered as T;
        return null;
      },
      async text(keys: string[]) {
        if (keys.includes(GLOBAL_IDENTITY_CATALOG_KEY)) return JSON.stringify(tampered);
        return null;
      },
    };
    const loaded = await loadGlobalIdentityCatalog(mockView);
    expect(loaded).toBeNull();
  });
});
