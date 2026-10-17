import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import { parseOrderForecastV3 } from "../src/v213/order-forecast";

// Lane V11 (revenue-guidance registry coverage): the v2/v3 order-forecast objects the PRODUCER (order_forecast.build_v3) writes for the issuers whose
// registry record was added or renewed, with the edited registry, its approval and the replayed 2026-10-13 receipts (tests/fixtures/
// v11-guidance-v3-outlooks.json, made by the producer, not by hand). The rollout order is Worker first: the unchanged reader must accept every
// state the new producer seals, and an old/new mismatch must still fail closed.
const proof = JSON.parse(readFileSync("../tests/fixtures/v11-guidance-v3-outlooks.json", "utf-8"));
const day: string = proof.generated_at.slice(0, 10);
const entry = (sym: string) => proof.entries[sym];
const parse = (sym: string, v3: any = entry(sym).order_forecast_v3) => parseOrderForecastV3(v3, day, sym, proof.generated_at, entry(sym).order_forecast);
const copy = (sym: string) => JSON.parse(JSON.stringify(entry(sym).order_forecast_v3));

const RENEWED: Record<string, number> = { MU: 61.5e9, SNDK: 10.55e9, LITE: 1.25e9, AVGO: 34.8e9, MTSI: 0.42e9, AAOI: 0.2725e9, ALAB: 0.55e9 };
const NOT_DISCLOSED = ["AXTI", "CORZ", "3006.TW", "SIVE.ST"];

describe("the Worker reads the revenue states of the lane V11 registry records", () => {
  it("accepts every renewed company-guidance path as AVAILABLE with its first projected quarter", () => {
    for (const [sym, first] of Object.entries(RENEWED)) {
      const f = parse(sym);
      expect(f.m6.status, sym).toBe("AVAILABLE");
      expect(f.revenueBasis, sym).toBe("COMPANY_GUIDANCE");
      expect(entry(sym).order_forecast_v3.forward_quarters[0].amount, sym).toBeCloseTo(first, 0);
    }
  });

  it("accepts NBIS now that its official-IR channel reads complete (full-year guidance allocation)", () => {
    const f = parse("NBIS");
    expect([f.m6.status, f.revenueBasis]).toEqual(["AVAILABLE", "COMPANY_GUIDANCE"]);
  });

  it("accepts the ended-quarter bridge warning of the renewed issuers whose guided quarter has ended", () => {
    const bridged: [string, string][] = [["LITE", "2026-09-26"], ["SNDK", "2026-10-02"], ["MTSI", "2026-10-02"], ["AAOI", "2026-09-30"], ["ALAB", "2026-09-30"]];
    for (const [sym, ended] of bridged) {
      expect(parse(sym).warning?.text, sym).toContain(`財測季度已於${ended}結束，實際營收尚未公布`);
    }
  });

  it("accepts the new nondisclosure records as the sealed NOT_DISCLOSED state", () => {
    for (const sym of NOT_DISCLOSED) {
      const f = parse(sym);
      expect([f.m6.status, f.m6.reason, f.m12.reason], sym).toEqual(["UNAVAILABLE", "NOT_DISCLOSED", "NOT_DISCLOSED"]);
      // The integrated registry enables the consensus route (operator 2026-10-13) and the fixture holds no consensus capture,
      // so the genuine nondisclosure stands without the CONSENSUS_DEFERRED diagnostic of the disabled gate.
      expect(f.revenueDiagnostic, sym).toBeNull();
    }
  });
});

describe("the Worker still fails closed on the lane V11 records", () => {
  it("refuses a renewed path once its official-IR channel is stripped from the sealed evidence", () => {
    for (const sym of ["AVGO", "MU"]) {
      const stripped = copy(sym);
      delete stripped.evidence.release_channels.ir;
      delete stripped.evidence.release_channels.ir_guidance_release_title;
      expect(parse(sym, stripped).m6.reason, sym).toBe("INVALID");
    }
  });

  it("refuses a renewed path whose receipt does not read the official-IR channel completely", () => {
    const f = copy("SNDK");
    const ir = f.evidence.latest_release_check.channels.find((c: any) => c.kind === "ISSUER_IR");
    ir.complete = false;
    expect(parse("SNDK", f).m6.reason).toBe("INVALID");
  });

  it("refuses a record whose approval binding is removed", () => {
    for (const sym of ["MU", "AXTI"]) {
      const unbound = copy(sym);
      unbound.evidence.approval_sha256 = null;
      expect(parse(sym, unbound).m6.reason, sym).toBe("INVALID");
    }
  });

  it("refuses a nondisclosure record that invents a guidance claim", () => {
    const forged = copy("CORZ");
    forged.evidence.claims = [copy("MU").evidence.claims[0]];
    expect(parse("CORZ", forged).m6.reason).toBe("INVALID");
  });

  it("refuses MU numbers that no longer match the sealed claim (a guided amount edited after sealing)", () => {
    const forged = copy("MU");
    forged.evidence.claims[0].stated_point = 70e9;
    forged.evidence.claims[0].high = 71.5e9;
    forged.evidence.claims[0].low = 68.5e9;
    expect(parse("MU", forged).m6.reason).toBe("INVALID");
  });
});
