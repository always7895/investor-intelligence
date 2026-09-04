import contract from "../../../config/v213-r75-publication-mode-v1.json";

const EVIDENCE_QUALIFIED = contract.modes.evidence_qualified;
const LIMITED = contract.modes.limited;
const LIMITED_CODES = contract.limited_missing_codes;
const SENSITIVE_FACTORS = contract.sensitive_factors;
const THRESHOLDS = contract.thresholds;

export const R75_PUBLICATION_MODE_CONTRACT_ID = contract.contract_id;

function canonicalJson(value: unknown): string {
  if (Array.isArray(value)) return `[${value.map(canonicalJson).join(",")}]`;
  if (value && typeof value === "object") {
    const item = value as Record<string, unknown>;
    return `{${Object.keys(item).sort().map((key) => `${JSON.stringify(key)}:${canonicalJson(item[key])}`).join(",")}}`;
  }
  return JSON.stringify(value);
}

export async function r75PublicationModeContractHash(): Promise<string> {
  const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(canonicalJson(contract)));
  return [...new Uint8Array(digest)].map((byte) => byte.toString(16).padStart(2, "0")).join("");
}

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
  if (sourceRows.length !== THRESHOLDS.ticker_count || top20.length !== THRESHOLDS.ticker_count) {
    throw new Error("V213_ACTIVATION_PUBLICATION_MODE_COUNT_INVALID");
  }

  const declaredStrict = finiteNumber(portfolio.evidence_qualified_candidate_count);
  const declaredLimited = finiteNumber(portfolio.limited_research_candidate_count);
  if (!Number.isInteger(declaredStrict) || !Number.isInteger(declaredLimited) || declaredStrict < 0 || declaredLimited < 0 || declaredStrict + declaredLimited !== THRESHOLDS.ticker_count) {
    throw new Error("V213_ACTIVATION_PUBLICATION_MODE_COUNT_INVALID");
  }
  if (
    freshnessAudit.status !== "PASS" ||
    finiteNumber(freshnessAudit.ticker_count) !== THRESHOLDS.ticker_count ||
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
        finiteNumber(metrics.claim_relevant_independent_families) < THRESHOLDS.min_evidence_claim_families ||
        finiteNumber(metrics.claim_relevant_independent_domains) < THRESHOLDS.min_evidence_claim_domains ||
        finiteNumber(metrics.claim_relevant_primary_sources) < THRESHOLDS.min_evidence_primary_sources ||
        finiteNumber(metrics.claim_dated_evidence_ratio) < THRESHOLDS.min_claim_dated_evidence_ratio
      ) {
        throw new Error("V213_ACTIVATION_EVIDENCE_QUALIFIED_INVALID");
      }
      return;
    }

    if (mode !== LIMITED) throw new Error("V213_ACTIVATION_PUBLICATION_MODE_INVALID");
    limited += 1;
    if (
      finiteNumber(state.claim_primary_units) < THRESHOLDS.min_limited_claim_primary_units ||
      finiteNumber(state.publication_provenance_origin_count) < THRESHOLDS.min_publication_provenance_origins ||
      finiteNumber(state.publication_provenance_domain_count) < THRESHOLDS.min_publication_provenance_domains ||
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
