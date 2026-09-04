const EVIDENCE_QUALIFIED = "EVIDENCE_QUALIFIED";
const LIMITED = "LIMITED_RESEARCH_CANDIDATE";
const LIMITED_CODES = [
  "LIMITED_RESEARCH_CANDIDATE",
  "INDEPENDENT_CLAIM_CORROBORATION",
] as const;
const SENSITIVE_FACTORS = [
  "demand_wave",
  "chokepoint",
  "pricing_power",
  "replacement_friction",
  "tam_capture",
] as const;

function record(value: unknown, code: string): Record<string, unknown> {
  if (!value || typeof value !== "object" || Array.isArray(value)) throw new Error(code);
  return value as Record<string, unknown>;
}

function rows(value: unknown, code: string): unknown[] {
  if (!Array.isArray(value)) throw new Error(code);
  return value;
}

function finiteNumber(value: unknown): number {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : 0;
}

function modeOf(item: Record<string, unknown>): string {
  const direct = String(item.publication_evidence_mode ?? "");
  if (direct) return direct;
  const freshness = item.freshness_state;
  if (freshness && typeof freshness === "object" && !Array.isArray(freshness)) {
    const nested = String((freshness as Record<string, unknown>).publication_evidence_mode ?? "");
    if (nested) return nested;
  }
  const logic = item.public_logic_state;
  if (logic && typeof logic === "object" && !Array.isArray(logic)) {
    return String((logic as Record<string, unknown>).publication_evidence_mode ?? "");
  }
  return "";
}

function positiveSensitiveFactors(top20Row: Record<string, unknown>): string[] {
  const factors = record(top20Row.serenity_factors, "V213_ACTIVATION_TOP20_FACTORS_INVALID");
  return SENSITIVE_FACTORS.filter((name) => finiteNumber(factors[name]) > 0);
}

export type R75PublicationModeSummary = {
  evidenceQualified: number;
  limited: number;
  highEligible: number;
};

/**
 * Validate the final publication modes after the Python bundle builder has
 * normalized source-level evidence.  This is deliberately independent of the
 * portfolio's pre-normalization global claim-family count: a safe LIMITED row
 * may have one company-claim family only when it also has current primary
 * company evidence, two independent publication-provenance origins/domains,
 * no positive sensitive factor, no validated thesis and no HIGH eligibility.
 */
export function validateR75PublicationModes(
  sourceAudit: Record<string, unknown>,
  top20: Array<Record<string, unknown>>,
): R75PublicationModeSummary {
  const portfolio = record(sourceAudit.portfolio, "V213_ACTIVATION_PUBLICATION_MODE_INVALID");
  const freshnessAudit = record(sourceAudit.freshness_audit, "V213_ACTIVATION_PUBLICATION_MODE_INVALID");
  const sourceRows = rows(sourceAudit.records, "V213_ACTIVATION_PUBLICATION_MODE_INVALID");
  if (sourceRows.length !== 20 || top20.length !== 20) {
    throw new Error("V213_ACTIVATION_PUBLICATION_MODE_COUNT_INVALID");
  }

  const declaredStrict = finiteNumber(portfolio.evidence_qualified_candidate_count);
  const declaredLimited = finiteNumber(portfolio.limited_research_candidate_count);
  if (!Number.isInteger(declaredStrict) || !Number.isInteger(declaredLimited) || declaredStrict < 0 || declaredLimited < 0 || declaredStrict + declaredLimited !== 20) {
    throw new Error("V213_ACTIVATION_PUBLICATION_MODE_COUNT_INVALID");
  }
  if (
    freshnessAudit.status !== "PASS" ||
    finiteNumber(freshnessAudit.ticker_count) !== 20 ||
    finiteNumber(freshnessAudit.evidence_qualified_candidate_count) !== declaredStrict ||
    finiteNumber(freshnessAudit.limited_research_candidate_count) !== declaredLimited ||
    freshnessAudit.all_tickers_publication_provenance_multi_source !== true ||
    freshnessAudit.all_positive_advantages_fresh_multi_source !== true ||
    portfolio.all_rows_publication_provenance_multi_source !== true ||
    finiteNumber(portfolio.limited_rows_high_confidence_eligible_count) !== 0
  ) {
    throw new Error("V213_ACTIVATION_PUBLICATION_FRESHNESS_INVALID");
  }

  let evidenceQualified = 0;
  let limited = 0;
  let highEligible = 0;
  sourceRows.forEach((raw, index) => {
    const item = record(raw, "V213_ACTIVATION_PUBLICATION_ROW_INVALID");
    const top20Row = record(top20[index], "V213_ACTIVATION_PUBLICATION_ROW_INVALID");
    if (String(item.ticker ?? "") !== String(top20Row.ticker ?? "")) {
      throw new Error("V213_ACTIVATION_PUBLICATION_ORDER_INVALID");
    }
    const metrics = record(item.source_metrics, "V213_ACTIVATION_PUBLICATION_ROW_INVALID");
    const state = record(item.freshness_state, "V213_ACTIVATION_PUBLICATION_ROW_INVALID");
    const logic = record(item.public_logic_state, "V213_ACTIVATION_PUBLICATION_ROW_INVALID");
    const missing = rows(item.missing_or_review, "V213_ACTIVATION_PUBLICATION_ROW_INVALID").map(String);
    const mode = modeOf(item);
    const eligible = item.eligible_for_high_confidence_model_inference === true;
    if (eligible) highEligible += 1;
    if (state.status !== "PASS") throw new Error("V213_ACTIVATION_PUBLICATION_FRESHNESS_INVALID");

    if (mode === EVIDENCE_QUALIFIED) {
      evidenceQualified += 1;
      if (
        finiteNumber(metrics.claim_relevant_independent_families) < 2 ||
        finiteNumber(metrics.claim_relevant_independent_domains) < 2 ||
        finiteNumber(metrics.claim_relevant_primary_sources) < 1 ||
        finiteNumber(metrics.claim_dated_evidence_ratio) < 0.8
      ) {
        throw new Error("V213_ACTIVATION_EVIDENCE_QUALIFIED_INVALID");
      }
      return;
    }

    if (mode !== LIMITED) throw new Error("V213_ACTIVATION_PUBLICATION_MODE_INVALID");
    limited += 1;
    if (
      finiteNumber(state.claim_primary_units) < 1 ||
      finiteNumber(state.publication_provenance_origin_count) < 2 ||
      finiteNumber(state.publication_provenance_domain_count) < 2 ||
      eligible ||
      logic.model_inference_confidence !== "LIMITED" ||
      logic.validated_company_thesis !== false ||
      LIMITED_CODES.some((code) => !missing.includes(code)) ||
      positiveSensitiveFactors(top20Row).length !== 0
    ) {
      throw new Error("V213_ACTIVATION_LIMITED_PUBLICATION_INVALID");
    }
  });

  if (evidenceQualified !== declaredStrict || limited !== declaredLimited) {
    throw new Error("V213_ACTIVATION_PUBLICATION_MODE_COUNT_INVALID");
  }
  if (highEligible !== finiteNumber(portfolio.high_confidence_model_inference_eligible_count)) {
    throw new Error("V213_ACTIVATION_HIGH_CONFIDENCE_COUNT_INVALID");
  }
  return { evidenceQualified, limited, highEligible };
}
