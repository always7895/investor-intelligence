import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { BOTTLENECK_V3_KEY, loadBottleneckV3 } from "../src/v213/bottleneck-v3";
import type { PublicSnapshotView } from "../src/v213/public-snapshot";
import { GUIDANCE_BINDING_KEY } from "../src/v213/revenue-guidance-machine";
import { describe, expect, it } from "vitest";

// G4c Scenario R (REAFFIRMATION): synthetic, frozen, test-only; never genuine/native/live qualification or
// enablement. The fixture is produced by tests/test_revenue_guidance_machine_nbis_reaffirm_parity.py (its
// frozen-bytes row is the pin). Rows pin DECLARED, designed expectations only; M13/M13s are characterizations
// (TS_ADMITS_TODAY: the REAFFIRMATION offsets are checked by shape only, an open product finding).
const rawFixture = readFileSync(resolve(__dirname, "../../tests/fixtures/revenue-guidance-machine-nbis-reaffirm-functional.json"));
const fixture = JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(rawFixture)) as {
  scope: string; report: string; binding: string;
};
const NBIS_CUTOFF = "2034-08-14T13:00:00Z";
const H = (text: string) => createHash("sha256").update(text).digest("hex");
const clone = (value: any): any => JSON.parse(JSON.stringify(value));
function canon(value: any): string {
  if (value === null || typeof value !== "object") return JSON.stringify(value);
  if (Array.isArray(value)) return "[" + value.map(canon).join(",") + "]";
  return "{" + Object.keys(value).sort().map(k => JSON.stringify(k) + ":" + canon(value[k])).join(",") + "}";
}
function fixtureView(report: string, binding: string): PublicSnapshotView {
  return {
    runId: "synthetic-machine-reaffirmation", kind: "snapshot", integrity: "sealed",
    hasSealedObject: key => key === BOTTLENECK_V3_KEY || key === GUIDANCE_BINDING_KEY,
    json: async () => { throw new Error("exact texts required"); },
    text: async keys => {
      if (keys.length !== 1) throw new Error("unexpected key selection");
      if (keys[0] === BOTTLENECK_V3_KEY) return report;
      if (keys[0] === GUIDANCE_BINDING_KEY) return binding;
      throw new Error("unexpected key");
    },
  };
}
const shift = (offsets: number[]) => [(offsets[0] ?? 0) + 1, (offsets[1] ?? 0) + 1];

// The G4b-3 full repin chain (decision rows only: the record is never edited here); canonical equality is
// checked BEFORE mutation. canon is a test-side reimplementation of the private MS:28 helper, not a bypass.
function repin(id: string): {report: string; binding: string} {
  const report = clone(JSON.parse(fixture.report)), binding = clone(JSON.parse(fixture.binding));
  const envelope = report.top[2].outlook.order_forecast_v3, m = envelope.machine;
  for (const key of ["decisions_canonical_json", "producer_canonical_json", "record_canonical_json"]) {
    if (canon(JSON.parse(m[key])) !== m[key]) throw new Error("CANONICAL_LOAD_MISMATCH " + key);
  }
  let decisions = JSON.parse(m.decisions_canonical_json);
  const record = JSON.parse(m.record_canonical_json);
  const attempt = JSON.parse(m.producer_canonical_json), event = attempt.event;
  const auto = envelope.payload.evidence.auto_update, producerPin = auto.producer;
  const pkg = event.packages.find((p: any) => p.accession === event.accession);
  const currentState = decisions.find((d: any) => d.kind === "MEMBERSHIP" && d.ref === pkg.accession).operands.guidance_state;
  const reaffirmation = decisions.find((d: any) => d.kind === "REAFFIRMATION");
  const current = reaffirmation.operands.current;
  if (id === "M13") current.offsets = shift(current.offsets);
  else if (id === "M13s") currentState.offsets = shift(currentState.offsets);
  else if (id === "R01") current.passage = current.passage.replace(String(current.year), String(current.year + 1));
  else if (id === "R02") decisions = decisions.filter((d: any) => d !== reaffirmation);
  else if (id === "R03") currentState.kind = "ORIGINAL_RANGE";
  else if (id !== "C0") throw new Error("UNKNOWN_ROW");

  attempt.decisions = decisions; attempt.event = event;
  // Required emit order: decisions, producer, record.
  m.decisions_canonical_json = canon(decisions);
  m.producer_canonical_json = canon(attempt);
  m.record_canonical_json = canon(record);
  producerPin.decisions_sha256 = H(m.decisions_canonical_json);
  producerPin.attempt_sha256 = H(m.producer_canonical_json);
  producerPin.event_sha256 = H(canon(event));
  binding.issuers.NBIS.attempt_sha256 = producerPin.attempt_sha256;
  auto.decisions = decisions.map((d: any) => ({kind: d.kind, ref: d.ref, decision: d.decision, capture: d.capture, operands: d.operands}));
  const routing = decisions.find((d: any) => d.kind === "ROUTING").operands;
  auto.consumed = routing.consumed.map((v: any) => [v.channel, v.id, v.date]).sort((a: any, b: any) => canon(a) < canon(b) ? -1 : canon(a) > canon(b) ? 1 : 0);
  const reportText = JSON.stringify(report);
  binding.report_sha256 = H(reportText);
  return {report: reportText, binding: JSON.stringify(binding)};
}
async function tuple(texts: {report: string; binding: string}): Promise<[boolean | null, string | null]> {
  const result = await loadBottleneckV3(fixtureView(texts.report, texts.binding), {guidanceMachineEnabled: true});
  const forecast = result?.top.find(row => row.symbol === "NBIS")?.forecast;
  if (!forecast || forecast.machineAdmitted === undefined) return [null, null];
  return [forecast.machineAdmitted, forecast.revenueStatus ?? null];
}

// ROWTABLE-BEGIN
const ROW_TABLE = [
  {"id": "C0", "kind": "CTRL", "py_a": ["RESULT", null], "py_b": ["RESULT", ["AUTO_VERIFIED", null]], "ts": [true, "AVAILABLE"]},
  {"id": "M13", "kind": "CHAR", "py_a": ["RESULT", null], "py_b": ["RESULT", ["BLOCKED", "APPROVAL_BINDING"]], "ts": [true, "AVAILABLE"]},
  {"id": "M13s", "kind": "CHAR", "py_a": ["RESULT", null], "py_b": ["RESULT", ["BLOCKED", "APPROVAL_BINDING"]], "ts": [true, "AVAILABLE"]},
  {"id": "R01", "kind": "NEG", "py_a": ["RESULT", null], "py_b": ["RESULT", ["BLOCKED", "APPROVAL_BINDING"]], "ts": [false, "UNAVAILABLE"]},
  {"id": "R02", "kind": "NEG", "py_a": ["RESULT", null], "py_b": ["RESULT", ["BLOCKED", "APPROVAL_BINDING"]], "ts": [false, "UNAVAILABLE"]},
  {"id": "R03", "kind": "NEG", "py_a": ["RAISED", "StateError", "ATTEMPT_NBIS_SCHEMA"], "py_b": ["RESULT", ["BLOCKED", "STATE_CORRUPT"]], "ts": [false, "UNAVAILABLE"]}
];
// ROWTABLE-END

describe("G4c synthetic NBIS Scenario R (REAFFIRMATION) frozen fixture", () => {
  it("T0R scope, the non-first NBIS row and exactly one REAFFIRMATION decision", () => {
    expect(fixture.scope).toBe("SYNTHETIC_NBIS_REAFFIRM_NOT_GENUINE_NATIVE_OR_LIVE");
    const top = JSON.parse(fixture.report).top;
    expect([top.length, top[2].symbol]).toEqual([10, "NBIS"]);
    const decisions = JSON.parse(top[2].outlook.order_forecast_v3.machine.decisions_canonical_json);
    expect(decisions.filter((d: any) => d.kind === "REAFFIRMATION")).toHaveLength(1);
  });

  it("T2R admits the reaffirmed NBIS AUTO record through the normal loader without human approval", async () => {
    const savedNow = Date.now;
    Date.now = () => Date.parse(NBIS_CUTOFF);
    try {
      const result = await loadBottleneckV3(fixtureView(fixture.report, fixture.binding), {guidanceMachineEnabled: true});
      const f = result?.top.find(row => row.symbol === "NBIS")?.forecast;
      const payload = JSON.parse(fixture.report).top[2].outlook.order_forecast_v3.payload;
      expect([f?.machineAdmitted, f?.revenueStatus, f?.revenueDiagnostic]).toEqual([true, "AVAILABLE", null]);
      expect([payload.evidence.approval_sha256, payload.evidence.approval_approved_at, payload.evidence.approval_decisions])
        .toEqual([null, null, null]);
      // Designed: FY2034 midpoint 7.4e9 minus the reported YTD 3.5333e9, over the two remaining quarters.
      expect(f?.m6).toMatchObject({ status: "AVAILABLE", amount: 3.8667e9 });
      expect(f?.m12).toMatchObject({ status: "AVAILABLE", amount: 7.7334e9 });
    } finally { Date.now = savedNow; }
  });

  for (const row of ROW_TABLE) it(row.id + " " + row.kind, async () => {
    const savedNow = Date.now;
    Date.now = () => Date.parse(NBIS_CUTOFF);
    try {
      // Every row requires its own no-op C0 in the same test.
      expect(await tuple(repin("C0"))).toEqual([true, "AVAILABLE"]);
      expect(await tuple(repin(row.id))).toEqual(row.ts);
    } finally { Date.now = savedNow; }
  });
});
