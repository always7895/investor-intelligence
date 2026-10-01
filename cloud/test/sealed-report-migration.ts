import { SNAPSHOT_OBJECT_KEYS, SNAPSHOT_SEAL_KEY, buildSnapshotSeal } from "../src/v213/snapshot-seal";
import sealContract from "../../config/v213-r75-publication-mode-v1.json";

const txId = (n: string) => n.repeat(32);

/**
 * Contract migration helper (TOP20_BOTTLENECK_TAKEOVER_V1 arbitration):
 * legacy top-level single-report writes (v213:top20-report:latest +
 * last_successful_pipeline_timestamp) no longer authorize publication. The
 * helper re-packages the SAME bytes into a sealed run-bound snapshot with a
 * pointer-last activation so legitimate reports stay testable, while
 * genuinely pointerless raw writes fail closed to INSUFFICIENT_EVIDENCE.
 */
export async function sealUnboundReport(kv: { values: Map<string, string> }, runId = "20260910T100000Z-9f8e7d6c5b4a"): Promise<void> {
  const reportRaw = kv.values.get("v213:top20-report:latest") ?? null;
  const stampRaw = kv.values.get("last_successful_pipeline_timestamp") ?? null;
  if (reportRaw === null || stampRaw === null) return;
  kv.values.delete("v213:top20-report:latest");
  kv.values.delete("last_successful_pipeline_timestamp");
  const tx = txId("2");
  const bodies: [string, string][] = SNAPSHOT_OBJECT_KEYS.map(key => [key, JSON.stringify({ synthetic: key })]);
  bodies.find(([key]) => key === "last_successful_pipeline_timestamp")![1] = stampRaw;
  bodies.find(([key]) => key === "v213:top20-report:latest")![1] = reportRaw;
  bodies.find(([key]) => key === "v213:activation-claim")![1] = JSON.stringify({
    schema_version: 1,
    transaction_id: tx,
    run_id: runId,
    payload_digests: Object.fromEntries(sealContract.payload_names.map((name) => [name, "a".repeat(64)])),
    claimed_at: stampRaw,
  });
  const seal = await buildSnapshotSeal({ run_id: runId, transaction_id: tx, generated_at: stampRaw, public_data_as_of: stampRaw }, bodies);
  for (const [key, body] of bodies) kv.values.set(`snapshot:${runId}:${key}`, body);
  kv.values.set(`snapshot:${runId}:${SNAPSHOT_SEAL_KEY}`, seal.text);
  kv.values.set("snapshot:current", JSON.stringify({
    schema_version: 2, run_id: runId, transaction_id: tx, seal_sha256: seal.sha256,
    public_data_as_of: stampRaw, promoted_at: stampRaw, provider_scope: "public_only", owner_watchlist_inherited: false,
  }));
}