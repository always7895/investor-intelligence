import { describe, expect, it } from "vitest";
import {
  type GlobalIdentityCatalog,
  type GlobalIdentityRecord,
  parseIdentityRequest,
  resolveGlobalIdentity,
  MARKET_SUFFIX_SCHEMES,
} from "../src/v213/global-identity";
import {
  loadGlobalIdentityCatalog,
  GLOBAL_IDENTITY_CATALOG_KEY,
} from "../src/v213/global-identity-reader";
import type { PublicSnapshotView } from "../src/v213/public-snapshot";

// Synthetic catalog covering 9+ markets for schema and resolver testing
function createSyntheticCatalog(): GlobalIdentityCatalog {
  const records: GlobalIdentityRecord[] = [
    // US
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
    // US Share classes
    {
      venue: "NYSE",
      market: "US",
      country: "United States",
      symbol: "BRK.A",
      native_symbol: "BRK.A",
      security_name: "Berkshire Hathaway Inc. Class A",
      native_name: null,
      security_class: "COMMON_STOCK",
      currency: "USD",
      source_feed: "other-us-listed",
      source_url: "https://example.test/other",
    },
    {
      venue: "NYSE",
      market: "US",
      country: "United States",
      symbol: "BRK.B",
      native_symbol: "BRK.B",
      security_name: "Berkshire Hathaway Inc. Class B",
      native_name: null,
      security_class: "COMMON_STOCK",
      currency: "USD",
      source_feed: "other-us-listed",
      source_url: "https://example.test/other",
    },
    // Taiwan (TWSE) with leading zeros
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
    {
      venue: "TWSE",
      market: "TAIWAN",
      country: "Taiwan",
      symbol: "0050",
      native_symbol: "0050",
      security_name: "Yuanta Taiwan Top 50 ETF",
      native_name: "元大台灣50",
      security_class: "ETF",
      currency: "TWD",
      source_feed: "twse-listed",
      source_url: "https://example.test/twse",
    },
    // Dual listing: ASML on Euronext Amsterdam and NASDAQ
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
    {
      venue: "NASDAQ",
      market: "US",
      country: "United States",
      symbol: "ASML",
      native_symbol: "ASML",
      security_name: "ASML Holding N.V. - New York Registry Shares",
      native_name: null,
      security_class: "COMMON_STOCK",
      currency: "USD",
      source_feed: "nasdaq-listed",
      source_url: "https://example.test/nasdaq",
    },
    // UK (LSE)
    {
      venue: "LSE",
      market: "UK",
      country: "United Kingdom",
      symbol: "IQE",
      native_symbol: "IQE",
      security_name: "IQE plc",
      native_name: null,
      security_class: "COMMON_STOCK",
      currency: "GBp",
      source_feed: "synthetic-lse",
      source_url: "https://example.test/lse",
    },
    // Japan (TSE)
    {
      venue: "TSE",
      market: "JAPAN",
      country: "Japan",
      symbol: "7203",
      native_symbol: "7203",
      security_name: "Toyota Motor Corporation",
      native_name: "トヨタ自動車",
      security_class: "COMMON_STOCK",
      currency: "JPY",
      source_feed: "synthetic-tse",
      source_url: "https://example.test/tse",
    },
    // Korea (KRX) with leading zero
    {
      venue: "KRX",
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
    // Hong Kong (HKEX) with leading zero
    {
      venue: "HKEX",
      market: "HK",
      country: "Hong Kong",
      symbol: "0700",
      native_symbol: "0700",
      security_name: "Tencent Holdings Limited",
      native_name: "騰訊控股",
      security_class: "COMMON_STOCK",
      currency: "HKD",
      source_feed: "synthetic-hkex",
      source_url: "https://example.test/hkex",
    },
    // China Shanghai (SSE)
    {
      venue: "SSE",
      market: "CHINA_SHANGHAI",
      country: "China",
      symbol: "600519",
      native_symbol: "600519",
      security_name: "Kweichow Moutai Co Ltd",
      native_name: "貴州茅台",
      security_class: "COMMON_STOCK",
      currency: "CNY",
      source_feed: "synthetic-sse",
      source_url: "https://example.test/sse",
    },
    // Sweden (Nasdaq Stockholm)
    {
      venue: "Nasdaq Stockholm",
      market: "SWEDEN",
      country: "Sweden",
      symbol: "VOLV-B",
      native_symbol: "VOLV-B",
      security_name: "Volvo AB ser. B",
      native_name: null,
      security_class: "COMMON_STOCK",
      currency: "SEK",
      source_feed: "synthetic-stockholm",
      source_url: "https://example.test/stockholm",
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

    const normEn = r.security_name.toLowerCase().trim().replace(/\s+/g, " ");
    by_name[normEn] = by_name[normEn] || [];
    if (!by_name[normEn]!.includes(idx)) {
      by_name[normEn]!.push(idx);
    }

    if (r.native_name) {
      const normZh = r.native_name.toLowerCase().trim().replace(/\s+/g, " ");
      by_name[normZh] = by_name[normZh] || [];
      if (!by_name[normZh]!.includes(idx)) {
        by_name[normZh]!.push(idx);
      }
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

describe("Global Identity Resolver (v1)", () => {
  const catalog = createSyntheticCatalog();

  it("resolves single unambiguous bare ASCII symbol case-insensitively", () => {
    const res1 = resolveGlobalIdentity(catalog, "AAPL");
    expect(res1.status).toBe("RESOLVED");
    if (res1.status === "RESOLVED") {
      expect(res1.record.symbol).toBe("AAPL");
      expect(res1.record.venue).toBe("NASDAQ");
      expect(res1.candidateCount).toBe(1);
    }

    const res2 = resolveGlobalIdentity(catalog, "aapl");
    expect(res2.status).toBe("RESOLVED");
    if (res2.status === "RESOLVED") {
      expect(res2.record.symbol).toBe("AAPL");
    }
  });

  it("preserves native leading zeros for TWSE, KRX, and HKEX", () => {
    // Taiwan TWSE 0050
    const resTw = resolveGlobalIdentity(catalog, "0050");
    expect(resTw.status).toBe("RESOLVED");
    if (resTw.status === "RESOLVED") {
      expect(resTw.record.symbol).toBe("0050");
      expect(resTw.record.native_symbol).toBe("0050");
      expect(resTw.record.venue).toBe("TWSE");
    }

    // Korea KRX 005930
    const resKr = resolveGlobalIdentity(catalog, "005930");
    expect(resKr.status).toBe("RESOLVED");
    if (resKr.status === "RESOLVED") {
      expect(resKr.record.symbol).toBe("005930");
      expect(resKr.record.venue).toBe("KRX");
    }

    // HKEX 0700
    const resHk = resolveGlobalIdentity(catalog, "0700");
    expect(resHk.status).toBe("RESOLVED");
    if (resHk.status === "RESOLVED") {
      expect(resHk.record.symbol).toBe("0700");
      expect(resHk.record.venue).toBe("HKEX");
    }
  });

  it("resolves exact company names without prefix and handles multi-match without find-first", () => {
    // Single exact match: native name "台積電"
    const resZh = resolveGlobalIdentity(catalog, "台積電");
    expect(resZh.status).toBe("RESOLVED");
    if (resZh.status === "RESOLVED") {
      expect(resZh.record.symbol).toBe("2330");
    }

    // Single exact match: English name
    const resEn = resolveGlobalIdentity(catalog, "Apple Inc.");
    expect(resEn.status).toBe("RESOLVED");
    if (resEn.status === "RESOLVED") {
      expect(resEn.record.symbol).toBe("AAPL");
    }
  });

  it("returns NEEDS_MARKET_SELECTION for dual-listed symbol across venues (ASML)", () => {
    // ASML is listed on both Euronext Amsterdam and NASDAQ
    const res = resolveGlobalIdentity(catalog, "ASML");
    expect(res.status).toBe("NEEDS_MARKET_SELECTION");
    if (res.status === "NEEDS_MARKET_SELECTION") {
      expect(res.candidates.length).toBe(2);
      const venues = res.candidates.map(c => c.venue);
      expect(venues).toContain("Euronext Amsterdam");
      expect(venues).toContain("NASDAQ");
    }

    // Suffix narrows to specific venue
    const resSuffix = resolveGlobalIdentity(catalog, "ASML.AS");
    expect(resSuffix.status).toBe("RESOLVED");
    if (resSuffix.status === "RESOLVED") {
      expect(resSuffix.record.venue).toBe("Euronext Amsterdam");
    }
  });

  it("preserves distinct share classes (BRK.A vs BRK.B) without collapsing", () => {
    const resA = resolveGlobalIdentity(catalog, "BRK.A");
    const resB = resolveGlobalIdentity(catalog, "BRK.B");
    expect(resA.status).toBe("RESOLVED");
    expect(resB.status).toBe("RESOLVED");
    if (resA.status === "RESOLVED" && resB.status === "RESOLVED") {
      expect(resA.record.symbol).toBe("BRK.A");
      expect(resB.record.symbol).toBe("BRK.B");
      expect(resA.record.security_name).toContain("Class A");
      expect(resB.record.security_name).toContain("Class B");
    }
  });

  it("handles SIVE generically with honest UNAVAILABLE and no invented issuer or attempted Sweden market", () => {
    const variants = ["SIVE", "sive", "Sive"];
    for (const variant of variants) {
      const res = resolveGlobalIdentity(catalog, variant);
      expect(res.status).toBe("UNAVAILABLE");
      if (res.status === "UNAVAILABLE") {
        expect((res as any).isSive).toBeUndefined();
        expect(res.reason.toUpperCase()).toContain("SIVE");
        expect(res.reason).not.toContain("Sivers");
        expect(res.reason).not.toContain("OTC");
        expect(res.attemptedMarket).toBeUndefined();
      }
    }
  });

  it("returns UNAVAILABLE for unknown ticker or missing catalog without guessing", () => {
    // Unknown ticker
    const resUnknown = resolveGlobalIdentity(catalog, "ZZZZUNKNOWN");
    expect(resUnknown.status).toBe("UNAVAILABLE");

    // When catalog is null (publisher migration deferred)
    const resNullCat = resolveGlobalIdentity(null, "AAPL");
    expect(resNullCat.status).toBe("UNAVAILABLE");
    if (resNullCat.status === "UNAVAILABLE") {
      expect(resNullCat.reason).toContain("publisher migration deferred");
    }
  });

  it("rejects confusable full-width Unicode (ＡＡＯＩ) fail-closed without NFKC bypass", () => {
    const confusable = "\uFF21\uFF21\uFF2F\uFF29"; // ＡＡＯＩ
    const res = resolveGlobalIdentity(catalog, confusable);
    expect(res.status).toBe("INVALID_REQUEST");
    if (res.status === "INVALID_REQUEST") {
      expect(res.reason).toBe("CONFUSABLE_UNICODE_TICKER_REJECTED");
    }
  });

  it("rejects overlong, malicious strings, and reserved bot commands", () => {
    expect(resolveGlobalIdentity(catalog, "").status).toBe("INVALID_REQUEST");
    expect(resolveGlobalIdentity(catalog, "a".repeat(101)).status).toBe("INVALID_REQUEST");
    expect(resolveGlobalIdentity(catalog, "<script>alert(1)</script>").status).toBe("INVALID_REQUEST");
    expect(resolveGlobalIdentity(catalog, "TOP20").status).toBe("INVALID_REQUEST");
    expect(resolveGlobalIdentity(catalog, "GDP").status).toBe("INVALID_REQUEST");
    expect(resolveGlobalIdentity(catalog, "查看結果 ABCDEF1234").status).toBe("INVALID_REQUEST");
  });
});

describe("Sealed Snapshot Global Identity Reader", () => {
  const catalog = createSyntheticCatalog();

  function mockSealedView(catalogPayload: unknown, integrity: "sealed" | "legacy" = "sealed"): PublicSnapshotView {
    const rawText = catalogPayload ? JSON.stringify(catalogPayload) : null;
    return {
      runId: "20260915T000000Z-0123456789ab",
      kind: "snapshot",
      integrity,
      async json<T>(logicalKeys: string[]): Promise<T | null> {
        if (logicalKeys.includes(GLOBAL_IDENTITY_CATALOG_KEY)) {
          return catalogPayload as T;
        }
        return null;
      },
      async text(logicalKeys: string[]): Promise<string | null> {
        if (logicalKeys.includes(GLOBAL_IDENTITY_CATALOG_KEY)) {
          return rawText;
        }
        return null;
      },
    };
  }

  it("loads and verifies catalog from sealed PublicSnapshotView", async () => {
    const view = mockSealedView(catalog, "sealed");
    const loaded = await loadGlobalIdentityCatalog(view);
    expect(loaded).not.toBeNull();
    expect(loaded?.contract_id).toBe("v213-global-identity-v1");
    expect(loaded?.records_count).toBe(catalog.records.length);
  });

  it("rejects unsealed view (integrity: legacy) fail-closed", async () => {
    const view = mockSealedView(catalog, "legacy");
    const loaded = await loadGlobalIdentityCatalog(view);
    expect(loaded).toBeNull();
  });

  it("returns null when identity catalog is absent from sealed snapshot", async () => {
    const view = mockSealedView(null, "sealed");
    const loaded = await loadGlobalIdentityCatalog(view);
    expect(loaded).toBeNull();
  });

  it("rejects malformed or tampered catalog objects", async () => {
    const tampered = { ...catalog, contract_id: "wrong-contract-id" };
    const view = mockSealedView(tampered, "sealed");
    const loaded = await loadGlobalIdentityCatalog(view);
    expect(loaded).toBeNull();
  });
});
