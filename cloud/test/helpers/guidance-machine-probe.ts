// Pre-KV replay probe for the sealed revenue-guidance machine binding (reader contract v213-reader-replay-v4).
// Shared by cloud/test/live-kv-replay.test.ts (the operator gate) and the offline F06 fixture test, so both run the
// same code. It reads only the pinned sealed view; no KV namespace, network or private store is touched.
import { BOTTLENECK_V3_KEY, loadBottleneckV3 } from "../../src/v213/bottleneck-v3";
import type { PublicSnapshotView } from "../../src/v213/public-snapshot";
import { GUIDANCE_BINDING_KEY } from "../../src/v213/revenue-guidance-machine";

/** ABSENT: the sealed index carries no machine binding (every non-machine tier). ADMITTED: the machine loader resolved
 * the binding against the sealed report. REFUSED: the run names a binding and the machine loader cannot read it. */
export type GuidanceMachineProbe = "ADMITTED" | "REFUSED" | "ABSENT";

export async function probeGuidanceMachine(view: PublicSnapshotView): Promise<GuidanceMachineProbe> {
  if (view.integrity !== "sealed" || view.kind !== "snapshot" || !view.hasSealedObject?.(GUIDANCE_BINDING_KEY)) return "ABSENT";
  if (!view.hasSealedObject?.(BOTTLENECK_V3_KEY)) return "REFUSED";
  return (await loadBottleneckV3(view, { guidanceMachineEnabled: true })) === null ? "REFUSED" : "ADMITTED";
}
