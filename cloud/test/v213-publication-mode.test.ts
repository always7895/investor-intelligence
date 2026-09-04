import { describe, expect, it } from "vitest";
import allLimited from "../../tests/fixtures/v213-r75-publication-mode/all-limited.json";
import mixed from "../../tests/fixtures/v213-r75-publication-mode/mixed.json";
import {
  R75_PUBLICATION_MODE_CONTRACT_ID,
  r75PublicationModeContractHash,
  validateR75PublicationModes,
} from "../src/v213/publication-mode";

type Fixture = {
  contract_id: string;
  contract_sha256: string;
  expected: { evidence_qualified: number; limited: number; high_eligible: number };
  bundle: { payloads: { top20_json: string; source_independence_json: string } };
};

function run(raw: unknown) {
  const fixture = raw as Fixture;
  const top20 = JSON.parse(fixture.bundle.payloads.top20_json) as Array<Record<string, unknown>>;
  const sourceAudit = JSON.parse(fixture.bundle.payloads.source_independence_json) as Record<string, unknown>;
  const result = validateR75PublicationModes(sourceAudit, top20);
  expect(result).toEqual({
    evidenceQualified: fixture.expected.evidence_qualified,
    limited: fixture.expected.limited,
    highEligible: fixture.expected.high_eligible,
  });
  return fixture;
}

describe("R75 shared publication-mode fixtures", () => {
  it("accepts all-LIMITED and mixed fixtures", async () => {
    const first = run(allLimited);
    const second = run(mixed);
    const hash = await r75PublicationModeContractHash();
    expect(first.contract_id).toBe(R75_PUBLICATION_MODE_CONTRACT_ID);
    expect(second.contract_id).toBe(R75_PUBLICATION_MODE_CONTRACT_ID);
    expect(first.contract_sha256).toBe(hash);
    expect(second.contract_sha256).toBe(hash);
  });
});
