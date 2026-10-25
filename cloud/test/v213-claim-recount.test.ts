import { describe, expect, it } from "vitest";
import mixed from "../../tests/fixtures/v213-r75-publication-mode/mixed.json";
import vectorFile from "../../tests/fixtures/v213-r75-publication-mode/claim-recount-vectors.json";
import contract from "../../config/v213-r75-publication-mode-v2.json";
import {
  claimLineageStructurallyQualified,
  computeIndependentLineages,
  pyEquals,
  pyStrip,
  pyTruthy,
} from "../src/v213/claim-recount";
import { validateR75PublicationModes } from "../src/v213/publication-mode";

// The SAME vector file is executed by tests/test_v213_publication_mode_claim_recount.py
// against scripts/source_observation.py and scripts/claim_lineage_qualification.py.
type Vectors = {
  contract_id: string;
  lineage_cases: Array<{ name: string; observations: unknown[]; expected: number }>;
  lineage_error_cases: Array<{ name: string; observations: unknown[] }>;
  recount_cases: Array<{ name: string; rule: string; minimum_families: unknown; expected: boolean; row: Record<string, unknown> }>;
};
const vectors = vectorFile as unknown as Vectors;

type Fixture = { bundle: { payloads: { top20_json: string; source_independence_json: string } } };

function inject(row: Record<string, unknown>) {
  const fixture = mixed as unknown as Fixture;
  const top20 = JSON.parse(fixture.bundle.payloads.top20_json) as Array<Record<string, unknown>>;
  const source = JSON.parse(fixture.bundle.payloads.source_independence_json) as { records: Array<Record<string, unknown>> };
  const target = source.records[0]!;
  delete target.claim_evidence_audit;
  if ("claim_evidence_audit" in row) target.claim_evidence_audit = row.claim_evidence_audit;
  return () => validateR75PublicationModes(source as unknown as Record<string, unknown>, top20);
}

describe("publication-mode contract v2 claim recount (Worker port)", () => {
  it("reads the v2 contract and the shared vectors are for it", () => {
    expect(contract.contract_id).toBe("v213-r75-publication-mode-v2");
    expect(vectors.contract_id).toBe(contract.contract_id);
    expect(contract.claim_recount.method).toBe("STRUCTURAL_ONLY");
    expect(contract.thresholds.min_evidence_claim_families).toBe(2);
    expect(vectors.recount_cases.length).toBeGreaterThanOrEqual(60);
  });

  it("matches the Python lineage merge on every shared vector", () => {
    for (const item of vectors.lineage_cases) {
      expect(computeIndependentLineages(item.observations), item.name).toBe(item.expected);
    }
  });

  it("raises where Python raises on a truthy non-mapping payload", () => {
    for (const item of vectors.lineage_error_cases) {
      expect(() => computeIndependentLineages(item.observations), item.name).toThrow();
    }
  });

  it("matches the Python structural recount on every shared vector (rules 1-6)", () => {
    for (const item of vectors.recount_cases) {
      expect(claimLineageStructurallyQualified(item.row, item.minimum_families as number), item.name).toBe(item.expected);
    }
  });

  it("has a refusing vector for every rule and an accepting vector for the positive rules", () => {
    const byRule = new Map<string, Set<boolean>>();
    for (const item of vectors.recount_cases) byRule.set(item.rule, (byRule.get(item.rule) ?? new Set()).add(item.expected));
    for (const rule of ["1", "2", "3", "4", "5", "6"]) expect(byRule.get(rule)?.has(false), rule).toBe(true);
    for (const rule of ["2", "3", "4", "5", "6", "time", "positive"]) expect(byRule.get(rule)?.has(true), rule).toBe(true);
  });

  it("runs every vector through the real publication-mode validator on the mixed fixture", () => {
    expect(inject({})).toThrow("V213_ACTIVATION_EVIDENCE_QUALIFIED_INVALID");
    let ran = 0;
    for (const item of vectors.recount_cases) {
      if (item.minimum_families !== 2) continue; // the Worker takes the threshold from the contract
      ran += 1;
      const run = inject(item.row);
      if (item.expected) expect(run, item.name).not.toThrow();
      else expect(run, item.name).toThrow("V213_ACTIVATION_EVIDENCE_QUALIFIED_INVALID");
    }
    expect(ran).toBeGreaterThanOrEqual(55);
  });

  it("never recounts LIMITED rows", () => {
    const fixture = mixed as unknown as Fixture;
    const top20 = JSON.parse(fixture.bundle.payloads.top20_json) as Array<Record<string, unknown>>;
    const source = JSON.parse(fixture.bundle.payloads.source_independence_json) as { records: Array<Record<string, unknown>> };
    delete source.records[10]!.claim_evidence_audit;
    source.records[11]!.claim_evidence_audit = "not an audit";
    expect(validateR75PublicationModes(source as unknown as Record<string, unknown>, top20)).toEqual({ evidenceQualified: 10, limited: 10, highEligible: 1 });
  });

  it("keeps the metric refusal ahead of the recount", () => {
    const fixture = mixed as unknown as Fixture;
    const top20 = JSON.parse(fixture.bundle.payloads.top20_json) as Array<Record<string, unknown>>;
    const source = JSON.parse(fixture.bundle.payloads.source_independence_json) as { records: Array<Record<string, any>> };
    source.records[0]!.source_metrics.claim_relevant_independent_families = 1;
    expect(() => validateR75PublicationModes(source as unknown as Record<string, unknown>, top20)).toThrow("V213_ACTIVATION_EVIDENCE_QUALIFIED_INVALID");
  });

  it("implements Python strip, truthiness and equality semantics", () => {
    expect(pyStrip("\u001c p \u3000")).toBe("p");
    expect(pyStrip("\ufeffp")).toBe("\ufeffp");
    expect(pyStrip("\u{1F600} x")).toBe("\u{1F600} x");
    expect([0, "", null, false, [], {}].map(pyTruthy)).toEqual([false, false, false, false, false, false]);
    expect([1, "a", true, [0], { a: 0 }].map(pyTruthy)).toEqual([true, true, true, true, true]);
    expect(pyEquals(true, 1)).toBe(true);
    expect(pyEquals("1", 1)).toBe(false);
    expect(pyEquals(null, 0)).toBe(false);
    expect(pyEquals({ a: [1, 2] }, { a: [1, 2.0] })).toBe(true);
    expect(pyEquals({ a: 1 }, { a: 1, b: 2 })).toBe(false);
  });
});
