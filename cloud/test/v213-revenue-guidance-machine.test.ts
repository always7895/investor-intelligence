import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { BOTTLENECK_V3_KEY, loadBottleneckV3, parseBottleneckV3 } from "../src/v213/bottleneck-v3";
import type { PublicSnapshotView } from "../src/v213/public-snapshot";
import { describe, expect, it } from "vitest";
import { parseOrderForecastV3Machine } from "../src/v213/order-forecast";
import {
  MACHINE_SCHEMA,
  GUIDANCE_BINDING_KEY,
  machineContextIsValid,
  resolveSealedMachineBindings,
  validateMachineEnvelope,
  type MachineBindings,
  type MachineCallbacks,
} from "../src/v213/revenue-guidance-machine";

// TYPEFIX1 regression: the typed fail-closed checks must keep a valid sealed selection and a valid
// barrier envelope unchanged, and must deny a missing issuer pin, a missing binding or a mismatched
// cutoff. Synthetic in-memory inputs only; no network, credentials or runtime.
const CUTOFF = "2026-09-28T15:00:00Z";
const SYMBOLS = ["NVDA", "SNDK", "SYM3", "SYM4", "SYM5", "SYM6", "SYM7", "SYM8", "SYM9", "SYM10"];
const IDENTITY = {
  verifier_version: null, normalizer_version: null, implementation_sha256: null, profiles_sha256: null,
  baseline_registry_sha256: null, baseline_approval_sha256: null,
};
const sha = (text: string) => createHash("sha256").update(text).digest("hex");
const reportText = JSON.stringify({
  schema: "v213-bottleneck-top20-v3-sealed", generated_at: CUTOFF, top: SYMBOLS.map(symbol => ({ symbol })),
});
const waitingPin = (symbol: string) => ({
  symbol, disposition: "WAITING", reason: null, admission_kind: null, identity: { ...IDENTITY },
  attempt_sha256: null, record_sha256: null, receipt_digest: null,
});
const bindingValue = (symbols: readonly string[]) => ({
  schema: "revenue-guidance-public-binding-v1", report_sha256: sha(reportText), cutoff: CUTOFF,
  revision: `gir1:${"a".repeat(64)}`, input_digest: "b".repeat(64), generation_id: null, generation_sha256: null,
  source_manifest_sha256: "c".repeat(64), issuers: Object.fromEntries(symbols.map(s => [s, waitingPin(s)])),
});
const callbacks: MachineCallbacks = {
  digest: sha,
  receiptDigest: () => { throw new Error("not reached for a barrier envelope"); },
  receiptStatus: () => { throw new Error("not reached for a barrier envelope"); },
};
const barrierEnvelope = (issuer: string) => ({
  schema: MACHINE_SCHEMA,
  admission_mode: "B1_MACHINE_V1",
  machine: {
    schema: "revenue-guidance-machine-evidence-v1", issuer, cutoff: CUTOFF, input_digest: "b".repeat(64),
    generation_id: null, generation_sha256: null, identity: { ...IDENTITY },
    record_canonical_json: null, producer_canonical_json: null, decisions_canonical_json: null, receipt_history: [],
  },
  payload: {
    issuer, version: 3, cutoff: CUTOFF, revenue_status: "UNAVAILABLE", revenue_reason: "STALE",
    evidence: {
      cutoff: CUTOFF, approval_sha256: null, approval_approved_at: null, approval_decisions: null,
      auto_update: {
        version: "auto-admission-evidence-v1", issuer, disposition: "WAITING", reason: null, admission_kind: null,
        generation_id: null, identity: { ...IDENTITY }, producer: null, decisions: [], consumed: [], detections: [],
        overflow: false, receipt: null, cutoff: CUTOFF, input_digest: "b".repeat(64), generation_sha256: null,
      },
    },
  },
});
const requiredBindings = (): MachineBindings => {
  const bindings = resolveSealedMachineBindings(reportText, JSON.stringify(bindingValue(SYMBOLS)));
  if (bindings === null) throw new Error("valid synthetic binding did not resolve");
  return bindings;
};

describe("TYPEFIX1 revenue-guidance machine fail-closed typing", () => {
  it("a valid sealed selection still resolves and is frozen", () => {
    const bindings = requiredBindings();
    expect(Object.keys(bindings.issuers).sort()).toEqual([...SYMBOLS].sort());
    expect(bindings.issuers.NVDA?.disposition).toBe("WAITING");
    expect(Object.isFrozen(bindings)).toBe(true);
  });

  it("a selection missing an issuer or with a different report hash is denied", () => {
    expect(resolveSealedMachineBindings(reportText, JSON.stringify(bindingValue(SYMBOLS.slice(1))))).toBeNull();
    expect(resolveSealedMachineBindings(reportText + " ", JSON.stringify(bindingValue(SYMBOLS)))).toBeNull();
    expect(resolveSealedMachineBindings(reportText, "{not json")).toBeNull();
  });

  it("a valid barrier envelope keeps its unchanged barrier context", () => {
    const ctx = validateMachineEnvelope(barrierEnvelope("NVDA"), requiredBindings(), "NVDA", CUTOFF, callbacks);
    expect(ctx).not.toBeNull();
    expect(machineContextIsValid(ctx)).toBe(true);
    expect(ctx?.kind).toBe("BARRIER");
    expect(ctx?.barrierReason).toBe("STALE");
    expect(ctx?.receiptDigest).toBeNull();
    expect(ctx?.rawReceiptStatus).toBeNull();
  });

  it("a missing sealed issuer pin stays denied without a default pin", () => {
    const { NVDA: _removed, ...rest } = requiredBindings().issuers;
    const withoutPin: MachineBindings = { ...requiredBindings(), issuers: rest };
    expect(validateMachineEnvelope(barrierEnvelope("NVDA"), withoutPin, "NVDA", CUTOFF, callbacks)).toBeNull();
    expect(validateMachineEnvelope(barrierEnvelope("ZZZZ"), requiredBindings(), "ZZZZ", CUTOFF, callbacks)).toBeNull();
  });

  it("an absent binding or a mismatched cutoff is denied", () => {
    expect(validateMachineEnvelope(barrierEnvelope("NVDA"), undefined, "NVDA", CUTOFF, callbacks)).toBeNull();
    expect(validateMachineEnvelope(barrierEnvelope("NVDA"), requiredBindings(), "NVDA", undefined, callbacks)).toBeNull();
    expect(validateMachineEnvelope(barrierEnvelope("NVDA"), requiredBindings(), "NVDA", "2026-09-28T15:00:01Z", callbacks)).toBeNull();
  });

  it("the machine fallback keeps an absent cutoff null and names its diagnostic", () => {
    const absent = parseOrderForecastV3Machine(null, "2026-09-28", "NVDA");
    expect(absent.cutoff).toBeNull();
    expect(absent.revenueStatus).toBe("UNAVAILABLE");
    expect(absent.revenueReason).toBe("FRESHNESS_UNVERIFIED");
    expect(absent.revenueDiagnostic).toBe("MACHINE_INPUTS_UNAVAILABLE");
    expect(absent.machineAdmitted).toBe(false);
    const dated = parseOrderForecastV3Machine(null, "2026-09-28", "NVDA", CUTOFF);
    expect(dated.cutoff).toBe(CUTOFF);
    expect(dated.revenueDiagnostic).toBe("MACHINE_INPUTS_UNAVAILABLE");
  });

  it.each<[string, (v: any) => void]>([
    ["forged-input", v => { v.machine.input_digest = "d".repeat(64); v.payload.evidence.auto_update.input_digest = "d".repeat(64); }],
    ["replayed-cutoff", v => { v.machine.cutoff = "2026-09-27T15:00:00Z"; }],
    ["forged-record", v => { v.machine.record_canonical_json = "{}"; }],
    ["malformed-history", v => { v.machine.receipt_history = {}; }],
    ["wrong-mode", v => { v.admission_mode = "EXISTING_V3_ONLY"; }],
  ])("rejects attachment %s despite a matching report digest", async (name, corrupt) => {
    const savedNow = Date.now;
    Date.now = () => Date.parse(CUTOFF);
    try {
      const report = JSON.parse(pythonFixture.report);
      corrupt(report.top[0].outlook.order_forecast_v3);
      const reportText = JSON.stringify(report);
      const binding = JSON.parse(pythonFixture.binding);
      binding.report_sha256 = sha(reportText); // exercise inner semantics, not just outer mismatch
      const f = nvdaForecast(await loadBottleneckV3(fixtureView(reportText, JSON.stringify(binding)).view,
        { guidanceMachineEnabled: true }));
      expect(f.revenueDiagnostic, name).toBe("MACHINE_INPUTS_UNAVAILABLE");
      expect(f.revenueStatus, name).toBe("UNAVAILABLE");
      expect(f.machineAdmitted, name).toBe(false);
    } finally { Date.now = savedNow; }
  });

  it.each(["missing-binding", "mixed-report", "replayed-binding", "malformed-binding", "unsealed", "missing-object"])(
    "rejects selection %s despite caller-supplied bindings", async name => {
      const selected = resolveSealedMachineBindings(pythonFixture.report, pythonFixture.binding);
      if (!selected) throw new Error("fixture binding missing");
      const savedNow = Date.now;
      Date.now = () => Date.parse(CUTOFF);
      try {
        const replay = JSON.parse(pythonFixture.binding);
        replay.cutoff = "2026-09-27T15:00:00Z";
        const input = fixtureView(
          name === "mixed-report" ? pythonFixture.report + " " : pythonFixture.report,
          name === "missing-binding" ? null : name === "replayed-binding" ? JSON.stringify(replay) :
            name === "malformed-binding" ? "{bad-json" : pythonFixture.binding);
        if (name === "unsealed") input.view = { ...input.view, integrity: "legacy" };
        if (name === "missing-object") input.view.hasSealedObject = () => false;
        expect(await loadBottleneckV3(input.view, { guidanceMachineEnabled: true, machineBindings: selected })).toBeNull();
        if (name === "unsealed" || name === "missing-object") expect(input.requested).toEqual([]);
      } finally { Date.now = savedNow; }
    });
});

/** Actual Python producer + serializer output, from a genuine EffectiveInputs
 * loaded with missing required state and synthetic invalid baselines. This is
 * BARRIER parity only, never AUTO revenue, native admission or live freshness. */
const pythonFixture = JSON.parse(readFileSync(resolve(__dirname, "../../tests/fixtures/revenue-guidance-machine-barrier-functional.json"), "utf8")) as {
  scope: string; report: string; binding: string;
};
const autoFixture = JSON.parse(readFileSync(resolve(__dirname, "../../tests/fixtures/revenue-guidance-machine-auto-functional.json"), "utf8")) as {
  scope: string; report: string; binding: string;
};
const AUTO_CUTOFF = "2026-02-27T13:00:00Z";

describe("BATCH03F genuine historical AUTO through the normal loader", () => {
  it("admits the real producer financial payload without human approval", async () => {
    const savedNow = Date.now;
    Date.now = () => Date.parse(AUTO_CUTOFF);
    try {
      expect(autoFixture.scope).toBe("SYNTHETIC_HISTORICAL_AUTO_NOT_NATIVE_OR_LIVE");
      const { view, requested } = fixtureView(autoFixture.report, autoFixture.binding);
      const f = nvdaForecast(await loadBottleneckV3(view, { guidanceMachineEnabled: true }));
      const payload = JSON.parse(autoFixture.report).top[0].outlook.order_forecast_v3.payload;
      expect(requested).toEqual([[BOTTLENECK_V3_KEY], [GUIDANCE_BINDING_KEY]]);
      expect(f.revenueStatus).toBe(payload.revenue_status);
      expect(f.revenueReason).toBe(payload.revenue_reason);
      expect(f.revenueDiagnostic).toBeNull();
      expect(f.machineAdmitted).toBe(true);
      expect(payload.evidence.approval_sha256).toBeNull();
      expect(payload.evidence.approval_approved_at).toBeNull();
      expect(payload.evidence.approval_decisions).toBeNull();
      expect(f.cutoff).toBe(AUTO_CUTOFF);
      expect(f.m6).toMatchObject({ status: "AVAILABLE", amount: 156e9 });
      expect(f.m12).toMatchObject({ status: "AVAILABLE", amount: 312e9 });
      expect(nvdaForecast(parseBottleneckV3(JSON.parse(autoFixture.report), Date.parse(AUTO_CUTOFF))).machineAdmitted).not.toBe(true);
    } finally { Date.now = savedNow; }
  });

  it.each<[string, (v: any) => void]>([
    ["producer-hash", v => { v.machine.producer_canonical_json += " "; }],
    ["replayed-auto-cutoff", v => { v.machine.cutoff = "2026-02-26T13:00:00Z"; }],
  ])("rejects AUTO %s after re-binding the outer report", async (_name, corrupt) => {
    const savedNow = Date.now;
    Date.now = () => Date.parse(AUTO_CUTOFF);
    try {
      const report = JSON.parse(autoFixture.report);
      corrupt(report.top[0].outlook.order_forecast_v3);
      const reportText = JSON.stringify(report);
      const binding = JSON.parse(autoFixture.binding);
      binding.report_sha256 = sha(reportText);
      const f = nvdaForecast(await loadBottleneckV3(fixtureView(reportText, JSON.stringify(binding)).view,
        { guidanceMachineEnabled: true }));
      expect(f.revenueDiagnostic).toBe("MACHINE_INPUTS_UNAVAILABLE");
      expect(f.revenueStatus).toBe("UNAVAILABLE");
      expect(f.machineAdmitted).toBe(false);
    } finally { Date.now = savedNow; }
  });
});

function fixtureView(report = pythonFixture.report, binding: string | null = pythonFixture.binding) {
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
function nvdaForecast(doc: Awaited<ReturnType<typeof loadBottleneckV3>>) {
  const forecast = doc?.top.find(row => row.symbol === "NVDA")?.forecast;
  if (!forecast) throw new Error("expected full report and NVDA forecast");
  return forecast;
}

describe("BATCH03B genuine Python BARRIER through the real machine loader", () => {
  it("preserves producer unavailability without downgrading to the machine-input fallback", async () => {
    const savedNow = Date.now;
    Date.now = () => Date.parse(CUTOFF);
    try {
      expect(pythonFixture.scope).toBe("SYNTHETIC_BARRIER_ONLY_NOT_AUTO_OR_NATIVE");
      const { view, requested } = fixtureView();
      const loaded = await loadBottleneckV3(view, { guidanceMachineEnabled: true });
      expect(requested).toEqual([[BOTTLENECK_V3_KEY], [GUIDANCE_BINDING_KEY]]);
      const f = nvdaForecast(loaded);
      const envelope = JSON.parse(pythonFixture.report).top[0].outlook.order_forecast_v3;
      expect(f.revenueStatus).toBe(envelope.payload.revenue_status);
      expect(f.revenueReason).toBe(envelope.payload.revenue_reason);
      expect(f.revenueDiagnostic).toBeNull();
      expect(f.machineAdmitted).toBe(false);
      expect(f.cutoff).toBe(CUTOFF);
      expect(f.m6).toMatchObject({ status: "UNAVAILABLE", reason: "INVALID" });
      expect(f.m12).toMatchObject({ status: "UNAVAILABLE", reason: "INVALID" });
      const selected = resolveSealedMachineBindings(pythonFixture.report, pythonFixture.binding);
      expect(selected).not.toBeNull();
      if (!selected) throw new Error("binding missing");
      expect(loaded).toEqual(parseBottleneckV3(JSON.parse(pythonFixture.report), Date.parse(CUTOFF),
        { guidanceMachineEnabled: true, machineBindings: selected }));
      const disabled = nvdaForecast(parseBottleneckV3(JSON.parse(pythonFixture.report), Date.parse(CUTOFF)));
      expect(disabled.m6).toMatchObject({ status: "UNAVAILABLE", reason: "INVALID" });
      expect(disabled.machineAdmitted).not.toBe(true);
    } finally { Date.now = savedNow; }
  });

});
