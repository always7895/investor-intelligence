import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { BOTTLENECK_V3_KEY, loadBottleneckV3, parseBottleneckV3 } from "../src/v213/bottleneck-v3";
import type { PublicSnapshotView } from "../src/v213/public-snapshot";
import { GUIDANCE_BINDING_KEY } from "../src/v213/revenue-guidance-machine";
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

describe("G4b-2 synthetic NBIS AUTO frozen producer parity", () => {
  it("T1 pins unmodified fixture bytes and the non-first NBIS row", () => {
    expect(createHash("sha256").update(rawFixture).digest("hex")).toBe("c73665dc0a201c82c7b766edb4e08c31500a706e36b5d6e1e3d066643021cd5d");
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
      const f = nbisForecast(await loadBottleneckV3(view, { guidanceMachineEnabled: true }));
      const payload = JSON.parse(nbisFixture.report).top[2].outlook.order_forecast_v3.payload;
      expect(requested).toEqual([[BOTTLENECK_V3_KEY], [GUIDANCE_BINDING_KEY]]);
      expect(f.revenueStatus).toBe("AVAILABLE");
      expect(f.revenueStatus).toBe(payload.revenue_status);
      expect(f.revenueReason).toBe(payload.revenue_reason);
      expect(f.revenueDiagnostic).toBeNull();
      expect(f.machineAdmitted).toBe(true);
      expect(payload.evidence.approval_sha256).toBeNull();
      expect(payload.evidence.approval_approved_at).toBeNull();
      expect(payload.evidence.approval_decisions).toBeNull();
      expect(f.cutoff).toBe(NBIS_CUTOFF);
      expect(f.m6).toMatchObject({ status: "AVAILABLE", amount: 3.7e9 });
      expect(f.m12).toMatchObject({ status: "AVAILABLE", amount: 7.4e9 });
      expect(nbisForecast(parseBottleneckV3(JSON.parse(nbisFixture.report), Date.parse(NBIS_CUTOFF))).machineAdmitted).not.toBe(true);
    } finally { Date.now = savedNow; }
  });
});
