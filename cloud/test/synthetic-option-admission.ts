// TESTFIX1: shared test-only seam for public-option admission, the same policy as v213-options-global.test.ts
// (OPTIONS_TEST_POLICY1). The real public-options rights catalog admits no provider (rights NONE). A test that checks
// routing, identity, freshness, validation or formatting opts in PER TEST for exactly the sealed tickers it renders;
// every other row keeps the real catalog decision. No catalog or provider is changed. The real policy at the actual
// callers, with no mock at all, is tested in v213-public-options-admission-regression.test.ts.
// vi.mock is hoisted per file, so a test file using this helper must itself partially mock the module:
//   vi.mock("../src/v213/public-options-admission", async importOriginal => {
//     const real = await importOriginal<typeof import("../src/v213/public-options-admission")>();
//     return { ...real, admitPublicOption: vi.fn(real.admitPublicOption) };
//   });
// and call resetAdmissionToReal() before every test. Without that mock both functions throw instead of admitting.
import { vi } from "vitest";
import * as admission from "../src/v213/public-options-admission";

const realAdmission = await vi.importActual<typeof import("../src/v213/public-options-admission")>("../src/v213/public-options-admission");
export const SYNTHETIC_PROVIDER_ID = "synthetic-test-only-not-in-catalog";

function admissionSeam() {
  if (!vi.isMockFunction(admission.admitPublicOption)) throw new Error("public-options-admission is not mocked in this test file");
  return vi.mocked(admission.admitPublicOption);
}

/** Restore the REAL catalog predicate; call before every test so positive admission is a per-test opt-in only. */
export function resetAdmissionToReal(): void {
  admissionSeam().mockImplementation(realAdmission.admitPublicOption);
}

/** Per-test opt-in: admit only these sealed tickers (synthetic provider id); all other rows keep the real catalog decision. */
export function admitSyntheticTickers(...tickers: string[]): void {
  const allowed = new Set(tickers);
  admissionSeam().mockImplementation((subject: unknown, nowMs?: number) => {
    const ticker = typeof subject === "object" && subject !== null ? (subject as { ticker?: unknown }).ticker : undefined;
    return typeof ticker === "string" && allowed.has(ticker)
      ? { ok: true, provider_id: SYNTHETIC_PROVIDER_ID }
      : realAdmission.admitPublicOption(subject, nowMs);
  });
}
