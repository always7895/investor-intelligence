// Pre-KV replay probe for the sealed revenue-guidance machine binding (reader contract v213-reader-replay-v5).
// Shared by cloud/test/live-kv-replay.test.ts (the operator gate) and the offline F06 fixture test, so both run the
// same code. It reads only the pinned sealed view; no KV namespace, network or private store is touched.
import { BOTTLENECK_V3_KEY, loadBottleneckV3 } from "../../src/v213/bottleneck-v3";
import type { PublicSnapshotView } from "../../src/v213/public-snapshot";
import { GUIDANCE_BINDING_KEY } from "../../src/v213/revenue-guidance-machine";

/** ABSENT: no declared machine binding. ADMITTED: the real loader resolved current machine data.
 * REFUSED: current machine admission unavailable; datedFactsOnly distinguishes valid retained facts from broken custody. */
export type GuidanceMachineProbe = "ADMITTED" | "REFUSED" | "ABSENT";
export interface GuidanceMachineProbeResult {
  readonly status: GuidanceMachineProbe;
  /** Valid retained facts with forecasts explicitly withheld; never current machine admission. */
  readonly datedFactsOnly: boolean;
}

export async function probeGuidanceMachine(view: PublicSnapshotView): Promise<GuidanceMachineProbeResult> {
  if (view.integrity !== "sealed" || view.kind !== "snapshot" || !view.hasSealedObject?.(GUIDANCE_BINDING_KEY)) return { status: "ABSENT", datedFactsOnly: false };
  if (!view.hasSealedObject?.(BOTTLENECK_V3_KEY)) return { status: "REFUSED", datedFactsOnly: false };
  const doc = await loadBottleneckV3(view, { guidanceMachineEnabled: true });
  const datedFactsOnly = doc?.historical_forecasts_unavailable === true && typeof doc.historical_retention_notice === "string"
    && doc.historical_retention_notice.length > 0;
  return { status: doc === null || doc.historical_forecasts_unavailable === true ? "REFUSED" : "ADMITTED", datedFactsOnly };
}
