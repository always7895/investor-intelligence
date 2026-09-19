import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { parseV21Top20 } from "../src/v21/top20";

function makeSyntheticTop20(overlayOverride?: Record<string, unknown>) {
  const generated = "2026-09-02T00:00:00Z";
  return Array.from({ length: 20 }, (_, index) => ({
    ticker: `T${String(index).padStart(2, "0")}`,
    name: `Synthetic ${index}`,
    serenity_score: 60 - index,
    serenity_raw_score: 62 - index,
    risk_penalty: 2,
    data_quality: 0.8,
    rating: index < 10 ? "A" : "B",
    category: "Synthetic",
    serenity_factors: {
      demand_wave: 12,
      chokepoint: 0,
      pricing_power: 9,
      replacement_friction: 0,
      tam_capture: 6,
      valuation_expectations: 3.75,
      evidence_quality: 14,
    },
    risk_flags: ["single_market_provider_degraded"],
    aschenbrenner_overlay: overlayOverride
      ? { ...overlayOverride }
      : {
          domain: "C" as const,
          fit_score: 20,
          included_in_serenity_score: false as const,
          attribution: "system_operationalization_not_aschenbrenner_stock_score",
        },
    evidence: [
      {
        source_id: "sec_edgar",
        tier: "T0",
        claim_type: "xbrl_fact",
        title: `SEC fact ${index}`,
        url: `https://www.sec.gov/Archives/edgar/data/${1000000 + index}/synthetic.htm`,
        as_of: generated,
      },
      {
        source_id: "nasdaq_symbol_directory",
        tier: "T2",
        claim_type: "regulated_listing_identity",
        title: `Nasdaq identity ${index}`,
        url: "https://www.nasdaqtrader.com/dynamic/SymDir/nasdaqlisted.txt",
        as_of: generated,
      },
      {
        source_id: "yahoo_finance_public_unofficial",
        tier: "T3",
        claim_type: "public_market_observation",
        title: `Yahoo observation ${index}`,
        url: `https://finance.yahoo.com/quote/T${String(index).padStart(2, "0")}`,
        as_of: generated,
      },
    ],
    evidence_count: 3,
    source_count: 3,
    scoring_version: "system-operationalization-v2.1.3-diversified" as const,
    line_public_eligible: true as const,
    provider_scope: "public_only" as const,
    owner_watchlist_inherited: false as const,
    rank: index + 1,
    generated_at: generated,
    as_of: generated,
  }));
}

const OLD4_OVERLAY = {
  domain: "C",
  fit_score: 20,
  included_in_serenity_score: false,
  attribution: "system_operationalization_not_aschenbrenner_stock_score",
};

const SAFE9_OVERLAY = {
  domain: "C",
  fit_score: 20,
  included_in_serenity_score: false,
  attribution: "system_operationalization_not_aschenbrenner_stock_score",
  status: "DISCOVERY_ONLY",
  company_fact_authority: false,
  current_holdings_verified: false,
  thesis_published_at: null,
  scenario_adjustment: "UNAVAILABLE",
};

describe("v2.1 discovery overlay parser compatibility", () => {
  let fetchSpy: ReturnType<typeof vi.spyOn>;

  beforeEach(() => {
    fetchSpy = vi.spyOn(globalThis, "fetch").mockRejectedValue(new Error("NETWORK_DISALLOWED"));
  });

  afterEach(() => {
    try {
      expect(fetchSpy).not.toHaveBeenCalled();
    } finally {
      fetchSpy.mockRestore();
    }
  });

  it("accepts legacy old4 overlay unchanged", () => {
    try {
      const records = makeSyntheticTop20(OLD4_OVERLAY);
      const parsed = parseV21Top20(records);
      expect(parsed).not.toBeNull();
      expect(parsed).toHaveLength(20);
      expect(parsed![0]!.aschenbrenner_overlay).toEqual(OLD4_OVERLAY);
      expect(Object.keys(parsed![0]!.aschenbrenner_overlay)).toEqual([
        "domain",
        "fit_score",
        "included_in_serenity_score",
        "attribution",
      ]);
    } finally {
      expect(fetchSpy).not.toHaveBeenCalled();
    }
  });

  it("accepts safe9 discovery overlay with exact expected keys and values", () => {
    try {
      const records = makeSyntheticTop20(SAFE9_OVERLAY);
      const parsed = parseV21Top20(records);
      expect(parsed).not.toBeNull();
      expect(parsed).toHaveLength(20);
      expect(parsed![0]!.aschenbrenner_overlay).toEqual(SAFE9_OVERLAY);
      expect(Object.keys(parsed![0]!.aschenbrenner_overlay)).toEqual([
        "domain",
        "fit_score",
        "included_in_serenity_score",
        "attribution",
        "status",
        "company_fact_authority",
        "current_holdings_verified",
        "thesis_published_at",
        "scenario_adjustment",
      ]);
    } finally {
      expect(fetchSpy).not.toHaveBeenCalled();
    }
  });

  it("accepts safe9 across all valid domain values: A, B, C, and null", () => {
    try {
      for (const domain of ["A", "B", "C", null] as const) {
        const records = makeSyntheticTop20({ ...SAFE9_OVERLAY, domain });
        const parsed = parseV21Top20(records);
        expect(parsed).not.toBeNull();
        expect(parsed![0]!.aschenbrenner_overlay.domain).toBe(domain);
      }
    } finally {
      expect(fetchSpy).not.toHaveBeenCalled();
    }
  });

  it("preserves full original rows and does not mutate raw input", () => {
    try {
      const records = makeSyntheticTop20(SAFE9_OVERLAY);
      const snapshot = JSON.stringify(records);
      const parsed = parseV21Top20(records);
      expect(parsed).not.toBeNull();
      expect(JSON.stringify(records)).toBe(snapshot);
      expect(parsed![0]!.aschenbrenner_overlay).toEqual(SAFE9_OVERLAY);

      const oldRecords = makeSyntheticTop20(OLD4_OVERLAY);
      const oldSnapshot = JSON.stringify(oldRecords);
      const oldParsed = parseV21Top20(oldRecords);
      expect(oldParsed).not.toBeNull();
      expect(JSON.stringify(oldRecords)).toBe(oldSnapshot);
      expect(oldParsed![0]!.aschenbrenner_overlay).toEqual(OLD4_OVERLAY);
    } finally {
      expect(fetchSpy).not.toHaveBeenCalled();
    }
  });

  describe("rejects all 5 discovery field promotion and malformed variants", () => {
    it("rejects status promotions and type mismatches", () => {
      try {
        const invalidValues = ["ACTIVE", "PROMOTED", "discovery_only", "DISCOVERY", true, null, 123, []];
        for (const bad of invalidValues) {
          const records = makeSyntheticTop20({ ...SAFE9_OVERLAY, status: bad });
          expect(parseV21Top20(records)).toBeNull();
        }
      } finally {
        expect(fetchSpy).not.toHaveBeenCalled();
      }
    });

    it("rejects company_fact_authority promotions and type mismatches", () => {
      try {
        const invalidValues = [true, "false", null, 1, 0, undefined, {}];
        for (const bad of invalidValues) {
          const records = makeSyntheticTop20({ ...SAFE9_OVERLAY, company_fact_authority: bad });
          expect(parseV21Top20(records)).toBeNull();
        }
      } finally {
        expect(fetchSpy).not.toHaveBeenCalled();
      }
    });

    it("rejects current_holdings_verified promotions and type mismatches", () => {
      try {
        const invalidValues = [true, "false", null, 1, 0, undefined, {}];
        for (const bad of invalidValues) {
          const records = makeSyntheticTop20({ ...SAFE9_OVERLAY, current_holdings_verified: bad });
          expect(parseV21Top20(records)).toBeNull();
        }
      } finally {
        expect(fetchSpy).not.toHaveBeenCalled();
      }
    });

    it("rejects thesis_published_at promotions and type mismatches", () => {
      try {
        const invalidValues = [
          "2026-09-02T00:00:00Z",
          "2026-09-02",
          true,
          false,
          "",
          12345,
          {},
        ];
        for (const bad of invalidValues) {
          const records = makeSyntheticTop20({ ...SAFE9_OVERLAY, thesis_published_at: bad });
          expect(parseV21Top20(records)).toBeNull();
        }
      } finally {
        expect(fetchSpy).not.toHaveBeenCalled();
      }
    });

    it("rejects scenario_adjustment promotions and type mismatches", () => {
      try {
        const invalidValues = ["APPLIED", "AVAILABLE", "unavailable", true, false, null, 1, []];
        for (const bad of invalidValues) {
          const records = makeSyntheticTop20({ ...SAFE9_OVERLAY, scenario_adjustment: bad });
          expect(parseV21Top20(records)).toBeNull();
        }
      } finally {
        expect(fetchSpy).not.toHaveBeenCalled();
      }
    });
  });

  describe("rejects partial extensions and unknown/extra keys", () => {
    it("rejects partial extensions between 5 and 8 keys", () => {
      try {
        // 5 keys (old4 + 1 new key)
        const fiveKeys = {
          ...OLD4_OVERLAY,
          status: "DISCOVERY_ONLY",
        };
        expect(parseV21Top20(makeSyntheticTop20(fiveKeys))).toBeNull();

        // 6 keys
        const sixKeys = {
          ...OLD4_OVERLAY,
          status: "DISCOVERY_ONLY",
          company_fact_authority: false,
        };
        expect(parseV21Top20(makeSyntheticTop20(sixKeys))).toBeNull();

        // 7 keys
        const sevenKeys = {
          ...OLD4_OVERLAY,
          status: "DISCOVERY_ONLY",
          company_fact_authority: false,
          current_holdings_verified: false,
        };
        expect(parseV21Top20(makeSyntheticTop20(sevenKeys))).toBeNull();

        // 8 keys (missing scenario_adjustment)
        const eightKeysMissingAdjustment = {
          ...OLD4_OVERLAY,
          status: "DISCOVERY_ONLY",
          company_fact_authority: false,
          current_holdings_verified: false,
          thesis_published_at: null,
        };
        expect(parseV21Top20(makeSyntheticTop20(eightKeysMissingAdjustment))).toBeNull();

        // 8 keys (missing status)
        const eightKeysMissingStatus = {
          ...OLD4_OVERLAY,
          company_fact_authority: false,
          current_holdings_verified: false,
          thesis_published_at: null,
          scenario_adjustment: "UNAVAILABLE",
        };
        expect(parseV21Top20(makeSyntheticTop20(eightKeysMissingStatus))).toBeNull();
      } finally {
        expect(fetchSpy).not.toHaveBeenCalled();
      }
    });

    it("rejects unknown extra keys on both old4 and safe9", () => {
      try {
        const old4WithExtra = {
          ...OLD4_OVERLAY,
          extra_key: "unauthorized",
        };
        expect(parseV21Top20(makeSyntheticTop20(old4WithExtra))).toBeNull();

        const safe9WithExtra = {
          ...SAFE9_OVERLAY,
          extra_key: "unauthorized",
        };
        expect(parseV21Top20(makeSyntheticTop20(safe9WithExtra))).toBeNull();

        const safe9With10Keys = {
          ...SAFE9_OVERLAY,
          scenario_mode: "optimistic",
        };
        expect(parseV21Top20(makeSyntheticTop20(safe9With10Keys))).toBeNull();
      } finally {
        expect(fetchSpy).not.toHaveBeenCalled();
      }
    });
  });

  describe("rejects included_in_serenity_score = true and wrong attribution", () => {
    it("rejects included_in_serenity_score = true on old4 and safe9", () => {
      try {
        const old4Included = { ...OLD4_OVERLAY, included_in_serenity_score: true };
        expect(parseV21Top20(makeSyntheticTop20(old4Included))).toBeNull();

        const safe9Included = { ...SAFE9_OVERLAY, included_in_serenity_score: true };
        expect(parseV21Top20(makeSyntheticTop20(safe9Included))).toBeNull();
      } finally {
        expect(fetchSpy).not.toHaveBeenCalled();
      }
    });

    it("rejects wrong attribution on old4 and safe9", () => {
      try {
        const wrongAttributions = [
          "aschenbrenner_official_stock_score",
          "system_operationalization",
          "",
          null,
        ];
        for (const attr of wrongAttributions) {
          const old4BadAttr = { ...OLD4_OVERLAY, attribution: attr };
          expect(parseV21Top20(makeSyntheticTop20(old4BadAttr))).toBeNull();

          const safe9BadAttr = { ...SAFE9_OVERLAY, attribution: attr };
          expect(parseV21Top20(makeSyntheticTop20(safe9BadAttr))).toBeNull();
        }
      } finally {
        expect(fetchSpy).not.toHaveBeenCalled();
      }
    });
  });

  describe("rejects invalid domain and NaN/out-of-range fit_score", () => {
    it("rejects invalid domain values on old4 and safe9", () => {
      try {
        const invalidDomains = ["D", "E", "a", "b", "c", "", 42, true, {}];
        for (const dom of invalidDomains) {
          const old4BadDomain = { ...OLD4_OVERLAY, domain: dom };
          expect(parseV21Top20(makeSyntheticTop20(old4BadDomain))).toBeNull();

          const safe9BadDomain = { ...SAFE9_OVERLAY, domain: dom };
          expect(parseV21Top20(makeSyntheticTop20(safe9BadDomain))).toBeNull();
        }
      } finally {
        expect(fetchSpy).not.toHaveBeenCalled();
      }
    });

    it("rejects NaN, Infinity, negative, >100, and non-numeric fit_score", () => {
      try {
        const invalidScores = [NaN, Infinity, -Infinity, -1, 100.1, 150, "20", null, undefined];
        for (const score of invalidScores) {
          const old4BadScore = { ...OLD4_OVERLAY, fit_score: score };
          expect(parseV21Top20(makeSyntheticTop20(old4BadScore))).toBeNull();

          const safe9BadScore = { ...SAFE9_OVERLAY, fit_score: score };
          expect(parseV21Top20(makeSyntheticTop20(safe9BadScore))).toBeNull();
        }
      } finally {
        expect(fetchSpy).not.toHaveBeenCalled();
      }
    });
  });

  describe("still enforces existing evidence and scoring checks", () => {
    it("rejects invalid evidence URLs and count mismatches with safe9 overlay", () => {
      try {
        const recordsBadUrl = makeSyntheticTop20(SAFE9_OVERLAY);
        recordsBadUrl[0]!.evidence[0]!.url = "http://insecure.example.com/item";
        expect(parseV21Top20(recordsBadUrl)).toBeNull();

        const recordsCountMismatch = makeSyntheticTop20(SAFE9_OVERLAY);
        recordsCountMismatch[0]!.evidence_count = 99;
        expect(parseV21Top20(recordsCountMismatch)).toBeNull();

        const recordsSourceMismatch = makeSyntheticTop20(SAFE9_OVERLAY);
        recordsSourceMismatch[0]!.source_count = 99;
        expect(parseV21Top20(recordsSourceMismatch)).toBeNull();
      } finally {
        expect(fetchSpy).not.toHaveBeenCalled();
      }
    });

    it("rejects filing provenance violations with safe9 overlay", () => {
      try {
        const records = makeSyntheticTop20(SAFE9_OVERLAY);
        Object.assign(records[0]!.evidence[0]!, {
          source_id: "sec_edgar",
          tier: "T0",
          claim_type: "filing_publication_provenance",
          title: "SEC filing",
          url: "https://www.sec.gov/Archives/edgar/data/1000000/000100000026000001/",
          as_of: "2026-09-02",
          family: "regulator_filing",
          publication_date: "2026-09-02",
          period_end: "",
          accession_number: "BAD-ACCESSION-NUMBER",
          primary: true,
          claim_primary: true,
          provenance_only: true,
          can_prove_positive_serenity_factor: false,
          retrieval_timestamp_used_as_publication_date: false,
        });
        expect(parseV21Top20(records)).toBeNull();
      } finally {
        expect(fetchSpy).not.toHaveBeenCalled();
      }
    });
  });
});
