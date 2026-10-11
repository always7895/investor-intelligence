import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { BOTTLENECK_V3_KEY, loadBottleneckV3, parseBottleneckV3 } from "../src/v213/bottleneck-v3";
import { computeReceiptDigest } from "../src/v213/order-forecast";
import type { PublicSnapshotView } from "../src/v213/public-snapshot";
import { GUIDANCE_BINDING_KEY, resolveSealedMachineBindings, validateMachineEnvelope, type MachineCallbacks } from "../src/v213/revenue-guidance-machine";
import { describe, expect, it } from "vitest";

// Frozen synthetic bytes only: never genuine/native/live NBIS qualification.
const rawFixture = readFileSync(resolve(__dirname, "../../tests/fixtures/revenue-guidance-machine-nbis-auto-functional.json"));
const nbisFixture = JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(rawFixture)) as {
  scope: string; report: string; binding: string;
};
const NBIS_CUTOFF = "2032-02-20T13:00:00Z";

function fixtureView(report = nbisFixture.report, binding: string | null = nbisFixture.binding) {
  const requested: string[][] = [];
  const view: PublicSnapshotView = {
    runId: "synthetic-machine-barrier", kind: "snapshot", integrity: "sealed",
    hasSealedObject: key => key === BOTTLENECK_V3_KEY || (key === GUIDANCE_BINDING_KEY && binding !== null),
    json: async () => { throw new Error("machine loader must select exact texts, not fallback JSON"); },
    text: async keys => {
      requested.push([...keys]);
      if (keys.length !== 1) throw new Error("unexpected key selection");
      if (keys[0] === BOTTLENECK_V3_KEY) return report;
      if (keys[0] === GUIDANCE_BINDING_KEY) return binding;
      throw new Error("unexpected key");
    },
  };
  return { view, requested };
}
function nbisForecast(doc: Awaited<ReturnType<typeof loadBottleneckV3>>) {
  const forecast = doc?.top.find(row => row.symbol === "NBIS")?.forecast;
  if (!forecast) throw new Error("expected full report and NBIS forecast");
  return forecast;
}
const H = (text: string) => createHash("sha256").update(text).digest("hex");
const utf8 = (text: string) => new TextEncoder().encode(text).byteLength;
// Test-side copy of the private canonical helper (as in v213-revenue-guidance-machine-nbis-pairs.test.ts), not a bypass.
function canon(value: any): string {
  if (value === null || typeof value !== "object") return JSON.stringify(value);
  if (Array.isArray(value)) return "[" + value.map(canon).join(",") + "]";
  return "{" + Object.keys(value).sort().map(k => JSON.stringify(k) + ":" + canon(value[k])).join(",") + "}";
}
/** The fixture texts after `edit`, re-pinned as the G4b-3 repin chain does: decisions, producer, binding pin and report digest. */
function repin(edit: (envelope: any, decisions: any[]) => void = () => undefined): { report: string; binding: string } {
  const report = JSON.parse(nbisFixture.report), binding = JSON.parse(nbisFixture.binding);
  const envelope = report.top[2].outlook.order_forecast_v3, m = envelope.machine, auto = envelope.payload.evidence.auto_update;
  for (const key of ["decisions_canonical_json", "producer_canonical_json"]) {
    if (canon(JSON.parse(m[key])) !== m[key]) throw new Error("CANONICAL_LOAD_MISMATCH " + key);
  }
  const decisions = JSON.parse(m.decisions_canonical_json), attempt = JSON.parse(m.producer_canonical_json);
  edit(envelope, decisions);
  attempt.decisions = decisions;
  m.decisions_canonical_json = canon(decisions);
  m.producer_canonical_json = canon(attempt);
  auto.producer.decisions_sha256 = H(m.decisions_canonical_json);
  auto.producer.attempt_sha256 = H(m.producer_canonical_json);
  binding.issuers.NBIS.attempt_sha256 = auto.producer.attempt_sha256;
  auto.decisions = decisions.map((d: any) => ({ kind: d.kind, ref: d.ref, decision: d.decision, capture: d.capture, operands: d.operands }));
  const text = JSON.stringify(report);
  binding.report_sha256 = H(text);
  return { report: text, binding: JSON.stringify(binding) };
}
// TEST SEAM: the receipt classifier echoes each stored status. validateMachineEnvelope requires the real classifier to return
// exactly that status for every history row and the newest one, so on an admitted input the echo changes no outcome.
const callbacks: MachineCallbacks = { digest: H, receiptDigest: computeReceiptDigest, receiptStatus: (receipt: any) => receipt.status };
function validatorContext(texts: { report: string; binding: string }) {
  const bindings = resolveSealedMachineBindings(texts.report, texts.binding);
  expect(bindings).not.toBeNull();
  return validateMachineEnvelope(JSON.parse(texts.report).top[2].outlook.order_forecast_v3, bindings ?? undefined, "NBIS", NBIS_CUTOFF, callbacks);
}

describe("G4b-2 synthetic NBIS AUTO frozen producer parity", () => {
  it("T1 pins unmodified fixture bytes and the non-first NBIS row", () => {
    expect(createHash("sha256").update(rawFixture).digest("hex")).toBe("0d10abfd3f8de37c1e4cbf7c01128b5f3be2f93a5c0968b6b8df5a7982db51de");
    expect(nbisFixture.scope).toBe("SYNTHETIC_NBIS_AUTO_NOT_GENUINE_NATIVE_OR_LIVE");
    const top = JSON.parse(nbisFixture.report).top;
    expect(top).toHaveLength(10);
    expect(top[2].symbol).toBe("NBIS");
  });

  it("T2 admits NBIS AUTO through the normal loader without human approval", async () => {
    const savedNow = Date.now;
    Date.now = () => Date.parse(NBIS_CUTOFF);
    try {
      const { view, requested } = fixtureView(nbisFixture.report, nbisFixture.binding);
      const doc = await loadBottleneckV3(view, { guidanceMachineEnabled: true });
      const f = nbisForecast(doc);
      const payload = JSON.parse(nbisFixture.report).top[2].outlook.order_forecast_v3.payload;
      // The loader's own parse of the sealed text, the NBIS entry its forecast f was validated from (T5 is the negative).
      const loaded = (doc?.top.find(row => row.symbol === "NBIS")?.outlook as any)?.order_forecast_v3?.payload;
      expect(requested).toEqual([[BOTTLENECK_V3_KEY], [GUIDANCE_BINDING_KEY]]);
      expect(f.revenueStatus).toBe("AVAILABLE");
      expect(f.revenueStatus).toBe(payload.revenue_status);
      expect(f.revenueReason).toBe(payload.revenue_reason);
      expect(f.revenueDiagnostic).toBeNull();
      expect(f.machineAdmitted).toBe(true);
      expect(loaded.evidence.approval_sha256).toBeNull();
      expect(loaded.evidence.approval_approved_at).toBeNull();
      expect(loaded.evidence.approval_decisions).toBeNull();
      expect(f.cutoff).toBe(NBIS_CUTOFF);
      expect(f.m6).toMatchObject({ status: "AVAILABLE", amount: 3.7e9 });
      expect(f.m12).toMatchObject({ status: "AVAILABLE", amount: 7.4e9 });
      expect(nbisForecast(parseBottleneckV3(JSON.parse(nbisFixture.report), Date.parse(NBIS_CUTOFF))).machineAdmitted).not.toBe(true);
    } finally { Date.now = savedNow; }
  });

  // G4b-2 LOW split: MT4 (zero-YTD operand gate) and MT8L (envelope cap) sit in validateMachineEnvelope, MT2 (V3_FY_YTD_END_MATCH
  // rollover) in parseV3 after it. T3 passes under MT2 and fails under MT4/MT8L; T4 fails only under MT4.
  it("T3 the envelope validator admits the sealed NBIS envelope and its no-op repin as AUTO", () => {
    for (const texts of [{ report: nbisFixture.report, binding: nbisFixture.binding }, repin()]) {
      const bytes = utf8(JSON.stringify(JSON.parse(texts.report).top[2].outlook.order_forecast_v3));
      expect(bytes).toBeGreaterThan(100000);
      expect(bytes).toBeLessThanOrEqual(256000);
      const context = validatorContext(texts);
      expect([context?.kind, context?.scoped]).toEqual(["AUTO", false]);
    }
  });

  it("T4 the zero-YTD FY reconciliation needs a null operand: an existing calendar proof as operand is refused", () => {
    const decisions = JSON.parse(JSON.parse(nbisFixture.report).top[2].outlook.order_forecast_v3.machine.decisions_canonical_json);
    expect(decisions.find((d: any) => d.kind === "FY_RECONCILIATION").operands).toMatchObject({ operand: null, quarters: [] });
    const texts = repin((_, rows) => {
      const op = (kind: string) => rows.find((d: any) => d.kind === kind).operands;
      op("FY_RECONCILIATION").operand = JSON.parse(JSON.stringify(op("CALENDAR").proofs[0]));
    });
    expect(validatorContext(texts)).toBeNull();
  });

  it("T5 a human approval on the sealed NBIS payload denies machine admission through the normal loader", async () => {
    const savedNow = Date.now;
    Date.now = () => Date.parse(NBIS_CUTOFF);
    try {
      const control = repin();
      const admitted = nbisForecast(await loadBottleneckV3(fixtureView(control.report, control.binding).view, { guidanceMachineEnabled: true }));
      expect([admitted.machineAdmitted, admitted.revenueStatus, admitted.revenueDiagnostic]).toEqual([true, "AVAILABLE", null]);
      const approvals: [string, unknown][] = [["approval_sha256", "a".repeat(64)], ["approval_approved_at", NBIS_CUTOFF], ["approval_decisions", []]];
      for (const [field, value] of approvals) {
        const texts = repin(envelope => { envelope.payload.evidence[field] = value; });
        const f = nbisForecast(await loadBottleneckV3(fixtureView(texts.report, texts.binding).view, { guidanceMachineEnabled: true }));
        expect([field, f.machineAdmitted, f.revenueStatus, f.revenueDiagnostic]).toEqual([field, false, "UNAVAILABLE", "MACHINE_INPUTS_UNAVAILABLE"]);
      }
    } finally { Date.now = savedNow; }
  });
});
