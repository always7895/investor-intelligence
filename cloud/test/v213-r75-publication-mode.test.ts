import { describe, expect, it } from "vitest";
import { validateR75PublicationModes } from "../src/v213/publication-mode";

const LIMITED = "LIMITED_RESEARCH_CANDIDATE";

function fixture() {
  const top20 = Array.from({ length: 20 }, (_, index) => ({
    rank: index + 1,
    ticker: `T${String(index).padStart(2, "0")}`,
    serenity_factors: {
      demand_wave: 0,
      chokepoint: 0,
      pricing_power: 0,
      replacement_friction: 0,
      tam_capture: 0,
      valuation_expectations: 3.75,
    },
  }));
  const records = top20.map((row) => ({
    rank: row.rank,
    ticker: row.ticker,
    publication_evidence_mode: LIMITED,
    source_metrics: {
      claim_relevant_independent_families: 1,
      claim_relevant_independent_domains: 1,
      claim_relevant_primary_sources: 1,
      claim_dated_evidence_ratio: 1,
    },
    freshness_state: {
      status: "PASS",
      publication_evidence_mode: LIMITED,
      claim_primary_units: 1,
      publication_provenance_origin_count: 2,
      publication_provenance_domain_count: 2,
    },
    public_logic_state: {
      publication_evidence_mode: LIMITED,
      model_inference_confidence: "LIMITED",
      validated_company_thesis: false,
    },
    missing_or_review: [
      "LIMITED_RESEARCH_CANDIDATE",
      "INDEPENDENT_CLAIM_CORROBORATION",
      "NON_YAHOO_MARKET_CORROBORATION",
    ],
    eligible_for_high_confidence_model_inference: false,
  }));
  return {
    top20,
    source: {
      portfolio: {
        evidence_qualified_candidate_count: 0,
        limited_research_candidate_count: 20,
        all_rows_publication_provenance_multi_source: true,
        limited_rows_high_confidence_eligible_count: 0,
        high_confidence_model_inference_eligible_count: 0,
      },
      freshness_audit: {
        status: "PASS",
        ticker_count: 20,
        evidence_qualified_candidate_count: 0,
        limited_research_candidate_count: 20,
        all_tickers_publication_provenance_multi_source: true,
        all_positive_advantages_fresh_multi_source: true,
      },
      records,
    },
  };
}

describe("R75 publication-mode validation", () => {
  it("accepts a fail-closed all-LIMITED bundle", () => {
    const value = fixture();
    expect(validateR75PublicationModes(value.source, value.top20)).toEqual({
      evidenceQualified: 0,
      limited: 20,
      highEligible: 0,
    });
  });

  it("rejects a positive sensitive factor on LIMITED", () => {
    const value = fixture();
    value.top20[0].serenity_factors.demand_wave = 1;
    expect(() => validateR75PublicationModes(value.source, value.top20)).toThrow(
      "V213_ACTIVATION_LIMITED_PUBLICATION_INVALID",
    );
  });

  it("rejects HIGH eligibility on LIMITED", () => {
    const value = fixture();
    value.source.records[0].eligible_for_high_confidence_model_inference = true;
    value.source.portfolio.high_confidence_model_inference_eligible_count = 1;
    value.source.portfolio.limited_rows_high_confidence_eligible_count = 1;
    expect(() => validateR75PublicationModes(value.source, value.top20)).toThrow(
      "V213_ACTIVATION_PUBLICATION_FRESHNESS_INVALID",
    );
  });

  it("rejects single-origin LIMITED publication provenance", () => {
    const value = fixture();
    value.source.records[0].freshness_state.publication_provenance_origin_count = 1;
    expect(() => validateR75PublicationModes(value.source, value.top20)).toThrow(
      "V213_ACTIVATION_LIMITED_PUBLICATION_INVALID",
    );
  });
});
