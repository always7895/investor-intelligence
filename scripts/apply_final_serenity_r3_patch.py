#!/usr/bin/env python3
# One-time exact patch for the final limited-evidence Worker contract.
from __future__ import annotations

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def replace_once(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8-sig")
    count = text.count(old)
    if count != 1:
        raise RuntimeError(
            f"{path}: expected exactly one replacement target, found {count}"
        )
    path.write_text(text.replace(old, new), encoding="utf-8", newline="\\n")


def run(*args: str) -> None:
    subprocess.run(args, cwd=ROOT, check=True)


def main() -> int:
    activation = ROOT / "cloud" / "src" / "v213" / "activation-v2.ts"
    replace_once(
        activation,
        'const MARKET_MISSING = "NON_YAHOO_MARKET_CORROBORATION";\\n',
        'const MARKET_MISSING = "NON_YAHOO_MARKET_CORROBORATION";\\n'
        'const EVIDENCE_QUALIFIED = "EVIDENCE_QUALIFIED";\\n'
        'const LIMITED_RESEARCH_CANDIDATE = "LIMITED_RESEARCH_CANDIDATE";\\n'
        'const LIMITED_CLAIM_MISSING = "INDEPENDENT_CLAIM_CORROBORATION";\\n',
    )
    replace_once(
        activation,
        '''    !finite(portfolio.claim_source_families) || portfolio.claim_source_families < 2 ||
    !finite(portfolio.claim_source_domains) || portfolio.claim_source_domains < 2 ||
    !finite(portfolio.maximum_single_family_share) || portfolio.maximum_single_family_share > 0.70 ||
''',
        '''    !finite(portfolio.claim_source_families) || portfolio.claim_source_families < 1 ||
    !finite(portfolio.claim_source_domains) || portfolio.claim_source_domains < 1 ||
    portfolio.all_rows_publication_provenance_multi_source !== true ||
    Number(portfolio.limited_rows_high_confidence_eligible_count ?? -1) !== 0 ||
    !finite(portfolio.maximum_single_family_share) || portfolio.maximum_single_family_share > 0.70 ||
''',
    )
    replace_once(
        activation,
        '''    const eligible = record.eligible_for_high_confidence_model_inference === true;
    if (eligible) eligibleCount += 1;
    if (providerCount < 1) {
''',
        '''    const eligible = record.eligible_for_high_confidence_model_inference === true;
    if (eligible) eligibleCount += 1;
    const freshness = object(record.freshness_state, "V213_ACTIVATION_SOURCE_AUDIT_RECORD_INVALID");
    const publicationMode = String(
      record.publication_evidence_mode ?? freshness.publication_evidence_mode ?? "",
    );
    const sensitivePositive = [
      "demand_wave", "chokepoint", "pricing_power", "replacement_friction", "tam_capture",
    ].some((name) => Number(top20[index]?.serenity_factors[name] ?? 0) > 0);
    if (publicationMode === EVIDENCE_QUALIFIED) {
      if (
        Number(freshness.claim_source_families ?? 0) < 2 ||
        Number(freshness.claim_source_domains ?? 0) < 2 ||
        Number(freshness.claim_primary_units ?? 0) < 1
      ) throw new Error("V213_ACTIVATION_EVIDENCE_QUALIFIED_INVALID");
      if (sensitivePositive && (
        Number(freshness.fresh_claim_primary_units ?? 0) < 1 ||
        Number(freshness.fresh_claim_non_primary_units ?? 0) < 1
      )) throw new Error("V213_ACTIVATION_POSITIVE_ADVANTAGE_EVIDENCE_INVALID");
    } else if (publicationMode === LIMITED_RESEARCH_CANDIDATE) {
      if (
        sensitivePositive || eligible ||
        logic.model_inference_confidence !== "LIMITED" ||
        logic.validated_company_thesis !== false ||
        logic.identity_provenance_is_company_claim_evidence !== false ||
        logic.identity_provenance_can_support_positive_advantage !== false ||
        !missing.includes(LIMITED_CLAIM_MISSING) ||
        !missing.includes(LIMITED_RESEARCH_CANDIDATE) ||
        Number(freshness.claim_primary_units ?? 0) < 1 ||
        Number(freshness.publication_provenance_origin_count ?? 0) < 2 ||
        Number(freshness.publication_provenance_domain_count ?? 0) < 2
      ) throw new Error("V213_ACTIVATION_LIMITED_EVIDENCE_INVALID");
    } else {
      throw new Error("V213_ACTIVATION_PUBLICATION_EVIDENCE_MODE_INVALID");
    }
    if (providerCount < 1) {
''',
    )

    test = ROOT / "cloud" / "test" / "v213-activation.test.ts"
    replace_once(
        test,
        'const MARKET_MISSING = "NON_YAHOO_MARKET_CORROBORATION";\\n',
        'const MARKET_MISSING = "NON_YAHOO_MARKET_CORROBORATION";\\n'
        'const LIMITED_CLAIM_MISSING = "INDEPENDENT_CLAIM_CORROBORATION";\\n'
        'const LIMITED_RESEARCH_CANDIDATE = "LIMITED_RESEARCH_CANDIDATE";\\n',
    )
    replace_once(test, "      tam_capture: 6,\\n", "      tam_capture: 0,\\n")
    replace_once(
        test,
        '''      claim_source_families: 2,
      claim_source_domains: 3,
      maximum_single_family_share: 0.5,
''',
        '''      claim_source_families: 1,
      claim_source_domains: 1,
      all_rows_publication_provenance_multi_source: true,
      evidence_qualified_candidate_count: 0,
      limited_research_candidate_count: 20,
      limited_rows_high_confidence_eligible_count: 0,
      maximum_single_family_share: 0.5,
''',
    )
    replace_once(
        test,
        '''      source_metrics: {
        claim_relevant_independent_families: 2,
        claim_relevant_independent_domains: 3,
        claim_relevant_primary_sources: 1,
        claim_dated_evidence_ratio: 1,
      },
      market_corroboration: { status: "UNAVAILABLE", independent_provider_count: 0 },
      public_logic_state: { model_inference_confidence: "LIMITED" },
      missing_or_review: [MARKET_MISSING],
      eligible_for_high_confidence_model_inference: false,
''',
        '''      source_metrics: {
        claim_relevant_independent_families: 1,
        claim_relevant_independent_domains: 1,
        claim_relevant_primary_sources: 1,
        claim_dated_evidence_ratio: 1,
        publication_provenance_origin_count: 2,
        publication_provenance_domain_count: 2,
      },
      market_corroboration: { status: "UNAVAILABLE", independent_provider_count: 0 },
      public_logic_state: {
        model_inference_confidence: "LIMITED",
        validated_company_thesis: false,
        identity_provenance_is_company_claim_evidence: false,
        identity_provenance_can_support_positive_advantage: false,
      },
      publication_evidence_mode: LIMITED_RESEARCH_CANDIDATE,
      freshness_state: {
        status: "PASS",
        publication_evidence_mode: LIMITED_RESEARCH_CANDIDATE,
        claim_source_families: 1,
        claim_source_domains: 1,
        claim_primary_units: 1,
        fresh_claim_primary_units: 1,
        fresh_claim_non_primary_units: 0,
        publication_provenance_origin_count: 2,
        publication_provenance_domain_count: 2,
        positive_advantage_factors: [],
      },
      missing_or_review: [MARKET_MISSING, LIMITED_CLAIM_MISSING, LIMITED_RESEARCH_CANDIDATE],
      eligible_for_high_confidence_model_inference: false,
''',
    )
    replace_once(
        test,
        '''  it("rejects a public source sidecar that attempts to smuggle a private holding", async () => {
''',
        '''  it("rejects a limited research candidate that carries a positive advantage", async () => {
    const { env } = runtime();
    const value = await bundle();
    const rows = JSON.parse(value.payloads.top20_json);
    rows[0].serenity_factors.tam_capture = 1;
    value.payloads.top20_json = JSON.stringify(rows);
    value.sha256.top20_json = await digest(value.payloads.top20_json);
    await expect(ingestV213ActivationBundle(JSON.stringify(value), env)).rejects.toThrow(
      "V213_ACTIVATION_LIMITED_EVIDENCE_INVALID",
    );
  });

  it("rejects a public source sidecar that attempts to smuggle a private holding", async () => {
''',
    )

    package = ROOT / "scripts" / "ci_v213_hotfix6_package.ps1"
    text = package.read_text(encoding="utf-8-sig")
    text = text.replace(
        "Investor-Intelligence-v2.1.3-SourceDiverse-R60-Hotfix6-WranglerJSON.zip",
        "Investor-Intelligence-v2.1.3-Final-Serenity-R3.zip",
    )
    text = text.replace(
        "SourceDiverse-R60-Hotfix6-WranglerJSON",
        "SourceDiverse-R60-Final-Serenity-R3",
    )
    package.write_text(text, encoding="utf-8", newline="\\n")

    runtime = ROOT / "install-v213-runtime.ps1"
    replace_once(
        runtime,
        "    'scripts\\build_v213_activation_bundle_v2.py',\\n",
        "    'scripts\\build_v213_activation_bundle_v2.py',\\n"
        "    'config\\v213-limited-research-candidate-policy.json',\\n"
        "    'config\\v213-serenity-methodology-reference-pins.json',\\n"
        "    'docs\\V213_SERENITY_RELATED_PROJECTS_REVIEW.zh-TW.md',\\n"
        "    'scripts\\audit_v213_serenity_release_v7.ps1',\\n"
        "    'scripts\\audit_v213_generated_snapshot_v5.ps1',\\n"
        "    'scripts\\audit_v213_serenity_scoring_logic_v2.ps1',\\n",
    )

    helper_workflow = ROOT / ".github" / "workflows" / "apply-final-serenity-r3.yml"
    helper_script = ROOT / "scripts" / "apply_final_serenity_r3_patch.py"
    if helper_workflow.exists():
        helper_workflow.unlink()
    if helper_script.exists():
        helper_script.unlink()

    run("git", "config", "user.name", "Investor Intelligence Release Bot")
    run("git", "config", "user.email", "actions@users.noreply.github.com")
    run("git", "add", "-A")
    run(
        "git",
        "commit",
        "-m",
        "fix: enforce evidence-qualified or explicit limited candidate publication",
    )
    run(
        "git",
        "push",
        "origin",
        "HEAD:development/v2.1.3-serenity-public-logic-fidelity",
    )
    print("FINAL_SERENITY_R3_PATCH_COMMIT=PASS", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
