import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";
import { BOTTLENECK_V3_KEY, loadBottleneckV3, parseBottleneckV3, type BottleneckReadOptions } from "../src/v213/bottleneck-v3";
import type { PublicSnapshotView } from "../src/v213/public-snapshot";
import { GUIDANCE_BINDING_KEY, resolveSealedMachineBindings } from "../src/v213/revenue-guidance-machine";
import { TRANSPORT_V1_ADMISSION_MODE, TRANSPORT_V1_SCHEMA } from "../src/v213/revenue-guidance-wire";

// G1 caller rows over the genuine Python AUTO and BARRIER producer fixtures read by the real sealed
// loader. Every corruption re-binds the outer report digest, so only inner semantics decide; each
// negative has a re-bound unmodified control. Synthetic historical data only: no network, KV or runtime.
type Texts = { report: string; binding: string };
const sha = (text: string) => createHash("sha256").update(text).digest("hex");
const bytes = (text: string) => new TextEncoder().encode(text).byteLength;
const fixture = (name: string) =>
  JSON.parse(readFileSync(resolve(__dirname, `../../tests/fixtures/${name}`), "utf8")) as Texts & { scope: string };
const AUTO = fixture("revenue-guidance-machine-auto-functional.json");
const BARRIER = fixture("revenue-guidance-machine-barrier-functional.json");
const AUTO_CUTOFF = "2026-02-27T13:00:00Z";
const BARRIER_CUTOFF = "2026-09-28T15:00:00Z";

function view(texts: Texts): PublicSnapshotView {
  return {
    runId: "synthetic-g1-callers", kind: "snapshot", integrity: "sealed",
    hasSealedObject: key => key === BOTTLENECK_V3_KEY || key === GUIDANCE_BINDING_KEY,
    json: async () => { throw new Error("machine loader must select exact texts, not fallback JSON"); },
    text: async keys => {
      if (keys.length !== 1) throw new Error("unexpected key selection");
      if (keys[0] === BOTTLENECK_V3_KEY) return texts.report;
      if (keys[0] === GUIDANCE_BINDING_KEY) return texts.binding;
      throw new Error("unexpected key");
    },
  };
}
function rebound(source: Texts, corrupt: (report: any) => void): Texts {
  const report = JSON.parse(source.report);
  corrupt(report);
  const reportText = JSON.stringify(report);
  const binding = JSON.parse(source.binding);
  binding.report_sha256 = sha(reportText);
  return { report: reportText, binding: JSON.stringify(binding) };
}
async function forecast(texts: Texts, cutoff: string, options: BottleneckReadOptions = { guidanceMachineEnabled: true }) {
  const savedNow = Date.now;
  Date.now = () => Date.parse(cutoff);
  try {
    const f = (await loadBottleneckV3(view(texts), options))?.top.find(row => row.symbol === "NVDA")?.forecast;
    if (!f) throw new Error("expected full report and NVDA forecast");
    return f;
  } finally { Date.now = savedNow; }
}
function parsedNvda(report: any, cutoff: string, options: BottleneckReadOptions) {
  const f = parseBottleneckV3(report, Date.parse(cutoff), options)?.top.find(row => row.symbol === "NVDA")?.forecast;
  if (!f) throw new Error("expected parsed NVDA forecast");
  return f;
}
const envelopeOf = (report: any) => report.top[0].outlook.order_forecast_v3;
const transport = (payload: unknown) => ({ schema: TRANSPORT_V1_SCHEMA, admission_mode: TRANSPORT_V1_ADMISSION_MODE, payload });

describe("G1-11 forged, scoped and double-wrapped AUTO payloads cannot improve admission", () => {
  it("control: a re-bound unmodified AUTO report is still admitted", async () => {
    expect(AUTO.scope).toBe("SYNTHETIC_HISTORICAL_AUTO_NOT_NATIVE_OR_LIVE");
    const f = await forecast(rebound(AUTO, () => {}), AUTO_CUTOFF);
    expect(f.machineAdmitted).toBe(true);
    expect(f.revenueDiagnostic).toBeNull();
    expect(f.m6).toMatchObject({ status: "AVAILABLE", amount: 156e9 });
  });

  it.each<[string, (v: any) => void]>([
    ["extra-envelope-key", v => { v.extra = null; }],
    ["extra-machine-key", v => { v.machine.extra = null; }],
    ["extra-auto-update-key", v => { v.payload.evidence.auto_update.extra = null; }],
    ["payload-version-4", v => { v.payload.version = 4; }],
    ["inner-transport-double-wrap", v => { v.payload = transport(v.payload); }],
    ["forged-m6-amount", v => { v.payload.m6.amount += 1e9; }],
    ["forged-scoped-flags", v => { v.payload.revenue_status = "UNAVAILABLE"; v.payload.revenue_reason = "EVIDENCE_LIMIT"; }],
    ["forged-human-approval", v => { v.payload.evidence.approval_sha256 = "a".repeat(64); }],
    ["forged-disposition", v => { v.payload.evidence.auto_update.disposition = "CURATED"; }],
    ["consumed-triple-added", v => {
      v.payload.evidence.auto_update.consumed.push(["ISSUER_IR", "https://example.invalid/synthetic-g1", "2026-02-26"]);
    }],
    ["consumed-triple-removed", v => { v.payload.evidence.auto_update.consumed.pop(); }],
  ])("rejects %s after re-binding the outer report", async (name, corrupt) => {
    const f = await forecast(rebound(AUTO, report => corrupt(envelopeOf(report))), AUTO_CUTOFF);
    expect(f.revenueDiagnostic, name).toBe("MACHINE_INPUTS_UNAVAILABLE");
    expect(f.revenueStatus, name).toBe("UNAVAILABLE");
    expect(f.machineAdmitted, name).toBe(false);
  });

  it("rejects an outward transport wrapper around the machine envelope with both flags on", async () => {
    const texts = rebound(AUTO, report => { report.top[0].outlook.order_forecast_v3 = transport(envelopeOf(report)); });
    const f = await forecast(texts, AUTO_CUTOFF, { guidanceMachineEnabled: true, guidanceWireEnabled: true });
    expect(f.revenueDiagnostic).toBe("MACHINE_INPUTS_UNAVAILABLE");
    expect(f.machineAdmitted).toBe(false);
  });

  it("a machine-disabled reader never admits the machine envelope, with or without the wire flag", () => {
    for (const options of [{}, { guidanceWireEnabled: true }] as BottleneckReadOptions[]) {
      const direct = parsedNvda(JSON.parse(AUTO.report), AUTO_CUTOFF, options);
      expect(direct.m6.reason).toBe("INVALID");
      expect(direct.machineAdmitted).not.toBe(true);
      const wrapped = JSON.parse(AUTO.report);
      wrapped.top[0].outlook.order_forecast_v3 = transport(envelopeOf(wrapped));
      const unwrapped = parsedNvda(wrapped, AUTO_CUTOFF, options);
      expect(unwrapped.m6.reason).toBe("INVALID");
      expect(unwrapped.machineAdmitted).not.toBe(true);
    }
  });
});

describe("G1-15 sealed selection byte caps are exact", () => {
  it("admits a binding of exactly 64000 bytes and refuses 64001", () => {
    const padded = AUTO.binding + " ".repeat(64000 - bytes(AUTO.binding));
    expect(bytes(padded)).toBe(64000);
    expect(resolveSealedMachineBindings(AUTO.report, padded)).not.toBeNull();
    expect(resolveSealedMachineBindings(AUTO.report, padded + " ")).toBeNull();
  });

  it("admits a report of exactly 1900000 bytes and refuses 1900001 under a re-bound digest", () => {
    const withReport = (report: string) => {
      const binding = JSON.parse(AUTO.binding);
      binding.report_sha256 = sha(report);
      return JSON.stringify(binding);
    };
    const padded = AUTO.report + " ".repeat(1900000 - bytes(AUTO.report));
    expect(bytes(padded)).toBe(1900000);
    expect(resolveSealedMachineBindings(padded, withReport(padded))).not.toBeNull();
    expect(resolveSealedMachineBindings(padded + " ", withReport(padded + " "))).toBeNull();
    expect(resolveSealedMachineBindings(padded, AUTO.binding)).toBeNull();
  });
});

describe("G1-16 the machine loader reads only one sealed snapshot view", () => {
  it.each(["legacy-kind", "legacy-integrity", "invalid-integrity"])("returns no document for a %s view", async name => {
    const base = view(rebound(AUTO, () => {}));
    const input: PublicSnapshotView = name === "legacy-kind" ? { ...base, kind: "legacy" }
      : { ...base, integrity: name === "legacy-integrity" ? "legacy" : "invalid" };
    const savedNow = Date.now;
    Date.now = () => Date.parse(AUTO_CUTOFF);
    try {
      expect(await loadBottleneckV3(base, { guidanceMachineEnabled: true })).not.toBeNull();
      expect(await loadBottleneckV3(input, { guidanceMachineEnabled: true })).toBeNull();
    } finally { Date.now = savedNow; }
  });
});

describe("G1-19 a barrier envelope never resurrects revenue", () => {
  it("control: the re-bound unmodified BARRIER keeps its producer unavailability", async () => {
    expect(BARRIER.scope).toBe("SYNTHETIC_BARRIER_ONLY_NOT_AUTO_OR_NATIVE");
    const f = await forecast(rebound(BARRIER, () => {}), BARRIER_CUTOFF);
    expect(f.revenueDiagnostic).toBeNull();
    expect(f.revenueStatus).toBe("UNAVAILABLE");
    expect(f.machineAdmitted).toBe(false);
  });

  it.each<[string, (v: any) => void]>([
    ["forged-available-status", v => { v.payload.revenue_status = "AVAILABLE"; v.payload.revenue_reason = null; }],
    ["forged-reason", v => { v.payload.revenue_reason = "STALE"; }],
    ["forged-producer-pin", v => { v.payload.evidence.auto_update.producer = { attempt_sha256: "a".repeat(64) }; }],
    ["forged-record", v => { v.machine.record_canonical_json = "{}"; }],
  ])("refuses barrier %s without any revenue", async (name, corrupt) => {
    const f = await forecast(rebound(BARRIER, report => corrupt(envelopeOf(report))), BARRIER_CUTOFF);
    expect(f.revenueDiagnostic, name).toBe("MACHINE_INPUTS_UNAVAILABLE");
    expect(f.revenueStatus, name).toBe("UNAVAILABLE");
    expect(f.m6.status, name).not.toBe("AVAILABLE");
    expect(f.m12.status, name).not.toBe("AVAILABLE");
    expect(f.machineAdmitted, name).toBe(false);
  });
});
