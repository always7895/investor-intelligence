/**
 * OPTIONICON R2 regression tests (integrated by INTEG1 with the B2 caller; NOT_RUN: Vitest is blocked at the native boundary).
 *
 * Imports only vitest and the real global-identity module (the proposal copy is not retained). Every fixture is
 * synthetic: no caller, no fixture file, no network, no model, no rights mock. Caller behaviour (B2) is covered
 * by the bounded HARN1C harness, not here.
 * R1 corrections: F1 the union is narrowed by a checked helper, never by an unchecked cast; F2 one exact key
 * is shown 1/1; F3 a same-key contradiction keeps venue+symbol identical in both row orders while a
 * different venue stays a separate negative; F4 the fixture default native_symbol equals the final symbol
 * unless an alias is under test; F5 rejected inputs are proved against populated exact keys, never an empty
 * fixture; F6 an already observed alias seed survives an incomplete canonical index. NOT RUN.
 */
import { describe, expect, it } from "vitest";

import {
  findUsIdentityConflict,
  type GlobalIdentityCatalog,
  type GlobalIdentityRecord,
  type GlobalIdentityResolution,
} from "../src/v213/global-identity";

/* Mirrors the module's own index-spelling expansion so a fixture index behaves like a real catalog index
 * (the shard loader's space/hyphen/dot variants plus the legacy upper-case symbol and native symbol). */
const spellingsOf = (record: GlobalIdentityRecord): string[] =>
  [record.symbol, record.native_symbol].map(value => value.toUpperCase())
    .flatMap(value => value.includes(" ") ? [value, value.replace(/ /g, "-"), value.replace(/ /g, ".")] : [value]);

/** R1 F4: native_symbol defaults to the final symbol, so an unrelated symbol is never indexed as ACME. */
const row = (over: Partial<GlobalIdentityRecord>): GlobalIdentityRecord => {
  const merged: GlobalIdentityRecord = {
    venue: "XNAS", market: "US", country: "United States", symbol: "ACME", native_symbol: "ACME",
    security_name: "Acme Synthetic Corp", native_name: null, name_zh: null, name_zh_source: null,
    security_class: "COMMON_STOCK", currency: "USD", source_feed: "synthetic-feed-a",
    source_url: "https://synthetic.invalid/a", ...over,
  };
  return over.native_symbol === undefined ? { ...merged, native_symbol: merged.symbol } : merged;
};

const catalogOf = (records: GlobalIdentityRecord[], extra: Partial<GlobalIdentityCatalog> = {}): GlobalIdentityCatalog => {
  const bySymbol: Record<string, number[]> = {};
  records.forEach((record, index) => {
    for (const spelling of spellingsOf(record)) (bySymbol[spelling] ??= []).push(index);
  });
  return {
    schema_version: 1, contract_id: "v213-global-identity-v1", generated_at: "2026-01-01T00:00:00Z",
    collection_receipts_sha256: "0".repeat(64), records_count: records.length, records,
    indexes: { by_venue_and_symbol: {}, by_symbol: bySymbol, by_name: {} }, ...extra,
  };
};

/** R1 F1: the returned union is narrowed by a runtime check; no unchecked assertion hides a type error. */
const unavailable = (found: GlobalIdentityResolution | null) => {
  if (found === null) throw new Error("expected an UNAVAILABLE resolution, got null");
  if (found.status !== "UNAVAILABLE") throw new Error(`expected an UNAVAILABLE resolution, got ${found.status}`);
  return found;
};

/** Standard admitted class values; the class differs only where a conflict is the point of the test. */
const pair = (spelling: string, over: Partial<GlobalIdentityRecord> = {}): GlobalIdentityRecord[] => [
  row({ symbol: spelling, ...over }),
  row({ symbol: spelling, security_class: "PREFERRED_STOCK", ...over }),
];

describe("findUsIdentityConflict - null means NO_EVIDENCE_OF_CONFLICT only", () => {
  it("null catalog and empty catalog are no-evidence, never an absence claim", () => {
    expect(findUsIdentityConflict(null, "ACME")).toBeNull();
    expect(findUsIdentityConflict(catalogOf([]), "ACME")).toBeNull();
  });

  it("a spelling the index does not list is no-evidence", () => {
    expect(findUsIdentityConflict(catalogOf(pair("OTHER")), "ACME")).toBeNull();
  });

  it("the name channel is never read, even when it holds a contradiction", () => {
    const catalog: GlobalIdentityCatalog = {
      ...catalogOf(pair("ACME")),
      indexes: { by_venue_and_symbol: {}, by_symbol: {}, by_name: { acme: [0, 1] } },
    };
    expect(findUsIdentityConflict(catalog, "ACME")).toBeNull();
  });

  it("legacy catalog.conflicts metadata is not evidence", () => {
    const provenanceOnly = [row({}), row({ source_feed: "synthetic-feed-b" })];
    const catalog: GlobalIdentityCatalog = {
      ...catalogOf(provenanceOnly),
      conflicts: { "XNAS:ACME": [{ reason: "synthetic legacy metadata" }] }, conflicts_count: 1,
    };
    expect(findUsIdentityConflict(catalog, "ACME")).toBeNull();
  });
});

describe("non-conflicting and provenance-only rows", () => {
  it("one US row and duplicate identical rows are no-evidence", () => {
    expect(findUsIdentityConflict(catalogOf([row({})]), "ACME")).toBeNull();
    expect(findUsIdentityConflict(catalogOf([row({}), row({})]), "ACME")).toBeNull();
  });

  it("source_feed and source_url alone are neither a conflict nor corroboration", () => {
    const catalog = catalogOf([
      row({ source_feed: "synthetic-feed-a", source_url: "https://synthetic.invalid/a" }),
      row({ source_feed: "synthetic-feed-b", source_url: "https://synthetic.invalid/b" }),
    ]);
    expect(findUsIdentityConflict(catalog, "ACME")).toBeNull();
  });
});

describe("one exact key with contradictory rows (R1 F2, F3)", () => {
  const usA = row({ symbol: "BRK-B" });
  const usB = row({ symbol: "BRK-B", market: "UK", country: "United Kingdom", currency: "GBP" });

  it("two contradictory rows of one venue:symbol key are ONE key: shown 1/1, never 2/2", () => {
    const found = unavailable(findUsIdentityConflict(catalogOf([usA, usB]), "BRK-B"));
    expect(found.query).toBe("ticker BRK-B");
    expect(found.attemptedMarket).toBe("US");
    expect(found.reason).toContain("IDENTITY_CONFLICT");
    expect(found.reason).toContain("本快照對 1 個掛牌");
    expect(found.reason).toContain("顯示 1/1");
    expect(found.reason).not.toContain("2/2");
    expect(found.reason).toContain("XNAS:BRK-B");
  });

  it("both row orders decide identically", () => {
    const forward = unavailable(findUsIdentityConflict(catalogOf([usA, usB]), "BRK-B"));
    const reverse = unavailable(findUsIdentityConflict(catalogOf([usB, usA]), "BRK-B"));
    expect(forward.reason).toBe(reverse.reason);
  });

  it("a second venue with the same symbol is a different key and stays no-evidence", () => {
    const rows = [
      row({ symbol: "BRK-B" }), row({ symbol: "BRK-B", source_feed: "synthetic-feed-b" }),
      row({ venue: "XSTO", market: "SWEDEN", country: "Sweden", symbol: "BRK-B", currency: "SEK" }),
      row({ venue: "XSTO", market: "SWEDEN", country: "Sweden", symbol: "BRK-B", currency: "SEK", source_feed: "synthetic-feed-b" }),
    ];
    expect(findUsIdentityConflict(catalogOf(rows), "BRK-B")).toBeNull();
  });

  it("a contradiction inside a foreign venue only is not US evidence", () => {
    const rows = [row({ symbol: "BRK-B" }), ...pair("BRK-B", { venue: "XSTO", market: "SWEDEN", country: "Sweden", currency: "SEK" })];
    expect(findUsIdentityConflict(catalogOf(rows), "BRK-B")).toBeNull();
  });
});

describe("market relevance is decided after the whole key is completed", () => {
  const st = pair("SIVE", { venue: "XSTO", market: "SWEDEN", country: "Sweden", currency: "SEK" });
  const us = pair("SIVE");

  it("a Stockholm-only contradiction for the same spelling does not poison US", () => {
    expect(findUsIdentityConflict(catalogOf(st), "SIVE")).toBeNull();
  });

  it("when US and Stockholm both contradict, only the relevant US key is counted", () => {
    const found = unavailable(findUsIdentityConflict(catalogOf([...st, ...us]), "SIVE"));
    expect(found.reason).toContain("本快照對 1 個掛牌");
    expect(found.reason).toContain("XNAS:SIVE");
    expect(found.reason).not.toContain("XSTO:SIVE");
    expect(found.attemptedMarket).toBe("US");
  });

  it("irrelevant symbols and venues never poison the result", () => {
    const noise = [
      row({ venue: "XSTO", market: "SWEDEN", country: "Sweden", symbol: "OTHER", currency: "SEK" }),
      row({ venue: "XTAI", market: "TAIWAN", country: "Taiwan", symbol: "2330", currency: "TWD" }),
      ...pair("IRRELEVANT"),
    ];
    expect(findUsIdentityConflict(catalogOf(noise), "ACME")).toBeNull();
  });

  it("rows the index does not list under the queried spelling are never invented", () => {
    const rows = [row({ symbol: "ACME" }), row({ symbol: "ACME-B", security_class: "PREFERRED_STOCK" })];
    expect(findUsIdentityConflict(catalogOf(rows), "ACME")).toBeNull();
  });
});

describe("the complete relevant set decides, only the display is capped", () => {
  it("seven distinct conflicting US keys refuse and show exactly 5/7 sorted keys", () => {
    const venues = ["XNAS", "XNYS", "ARCX", "BATS", "IEX", "MEMX", "PSX"];
    const records = venues.flatMap(venue => pair("ACME", { venue }));
    const found = unavailable(findUsIdentityConflict(catalogOf(records), "ACME"));
    expect(found.reason).toContain("本快照對 7 個掛牌");
    expect(found.reason).toContain("顯示 5/7");
    expect(found.reason).toContain("ARCX:ACME、BATS:ACME、IEX:ACME、MEMX:ACME、PSX:ACME");
    expect(found.reason).not.toContain("XNAS:ACME");
    expect(found.reason).not.toContain("XNYS:ACME");
  });
});

describe("index completion and spelling semantics (R1 F6)", () => {
  const incompleteIndex = (): GlobalIdentityCatalog => ({
    ...catalogOf([]), records: [row({ symbol: "ACME B" }), row({ symbol: "ACME B", security_class: "PREFERRED_STOCK" })],
    records_count: 2,
    indexes: { by_venue_and_symbol: {}, by_name: {}, by_symbol: { "ACME B": [0], "ACME-B": [1] } },
  });

  it("an observed alias seed absent from the canonical index is retained and completed", () => {
    const found = unavailable(findUsIdentityConflict(incompleteIndex(), "ACME-B"));
    expect(found.reason).toContain("XNAS:ACME B");
    expect(found.reason).toContain("本快照對 1 個掛牌");
    expect(found.reason).toContain("顯示 1/1");
  });

  it("a row the canonical index omits under the queried spelling is not invented", () => {
    expect(findUsIdentityConflict(incompleteIndex(), "ACME B")).toBeNull();
  });

  it("space-derived spellings behave exactly as the existing index lists them", () => {
    const catalog = catalogOf(pair("BRK B"));
    for (const spelling of ["BRK B", "BRK-B", "BRK.B"]) {
      const found = unavailable(findUsIdentityConflict(catalog, spelling));
      expect(found.query).toBe(`ticker ${spelling}`);
      expect(found.reason).toContain("顯示 1/1");
    }
  });

  it("BRK-B and BRK.B are not equivalent when the index lists only one of them", () => {
    const catalog = catalogOf(pair("BRK.B"));
    expect(findUsIdentityConflict(catalog, "BRK.B")).not.toBeNull();
    expect(findUsIdentityConflict(catalog, "BRK-B")).toBeNull();
  });

  it("a genuine lowercase spelling resolves the same key as its uppercase form", () => {
    const catalog = catalogOf(pair("BRK.B"));
    const upper = unavailable(findUsIdentityConflict(catalog, "BRK.B"));
    const lower = unavailable(findUsIdentityConflict(catalog, "brk.b"));
    expect(lower.query).toBe("ticker brk.b");
    expect(lower.reason).toBe(upper.reason);
  });
});

describe("explicit spelling and reserved rejection against populated exact keys (R1 F5)", () => {
  const rejected = ["", "   ", "TOP20", "期權", "AAPL.TW", "ACME.TW", "ACME Inc", "公司 ACME", "個股 ACME", "ticker ACME",
    "股票 ACME", "台積電", "GDP", "ACME?", "ACME/B", "查看結果 abc123", "完整文字分析", "data_report", "ＡＣＭＥ",
    "__proto__", "constructor", "1".repeat(120)];

  it("each rejected input is indexed with a real contradiction, so null proves the policy, not an empty fixture", () => {
    const populated = catalogOf(rejected.flatMap(query => [...pair(query), ...pair("ACME")]));
    for (const query of rejected) expect(findUsIdentityConflict(populated, query)).toBeNull();
  });
});

describe("malformed typed input stays honest", () => {
  it("a malformed index shape is no-evidence and a missing index object is not swallowed", () => {
    const broken: GlobalIdentityCatalog = {
      ...catalogOf([]), records: [row({})], records_count: 1,
      indexes: { by_venue_and_symbol: {}, by_name: {}, by_symbol: { ACME: "not-an-array" as unknown as number[] } },
    };
    expect(findUsIdentityConflict(broken, "ACME")).toBeNull();
    const missing = { ...catalogOf([]), indexes: undefined as unknown as GlobalIdentityCatalog["indexes"] };
    expect(() => findUsIdentityConflict(missing, "ACME")).toThrow(TypeError);
  });
});
