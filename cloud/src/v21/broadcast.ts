import type { StorageEnv } from "../storage";
import { pinPublicSnapshot } from "../v213/public-snapshot";
import { v213TimesAreFresh, v213EvidenceWithinWindow } from "../v213/top20-report";
import { formatV212Top20Report, parseV212Top20Report } from "../v212/top20-report";
import { getOwnerPushTarget } from "./owner-storage";
import { pushText, type V21LinePushEnv } from "./line-push";
import { parseV21Top20 } from "./top20";

export interface V21BroadcastEnv extends StorageEnv, V21LinePushEnv {
  V21_SCHEDULED_PUSH_ENABLED?: string;
  V21_TOP20_MAX_AGE_SECONDS?: string;
}

export type BroadcastSlot = "morning" | "evening" | "test";

function enabled(value: string | undefined): boolean {
  return ["1", "true", "yes", "on"].includes((value ?? "").trim().toLowerCase());
}

function taipeiDate(now: number): string {
  return new Intl.DateTimeFormat("en-CA", {
    timeZone: "Asia/Taipei",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).format(new Date(now));
}

export async function broadcastV21Top20(
  env: V21BroadcastEnv,
  slot: BroadcastSlot,
  now = Date.now(),
): Promise<Record<string, unknown>> {
  if (slot !== "test" && !enabled(env.V21_SCHEDULED_PUSH_ENABLED)) {
    return { status: "disabled" };
  }
  const owner = await getOwnerPushTarget(env);
  if (!owner) return { status: "owner_not_paired" };

  const view = await pinPublicSnapshot(env);
  const records = parseV21Top20(await view.json<unknown>(["v21:top20:latest"]));
  if (!records) return { status: "top20_unavailable" };
  const report = parseV212Top20Report(
    await view.json<unknown>(["v212:top20-report:latest"]),
  );
  if (!report) return { status: "top20_report_unavailable" };
  if (report.records.some((item, index) => item.ticker !== records[index]?.ticker)) {
    return { status: "top20_report_order_mismatch" };
  }

  const stamp = await view.text(["last_successful_pipeline_timestamp"]);
  // Row source-state freshness: rows carrying orders_state_as_of are judged on
  // that source-state stamp; V212 rows fall back to retrieved_at, which must then
  // satisfy the product max-age cap (not a 550d evidence window).
  if (!v213TimesAreFresh(env, [
    stamp,
    report.generated_at,
    ...records.map(row => row.generated_at),
    ...report.records.map(row => (row as { orders_state_as_of?: string }).orders_state_as_of ?? row.retrieved_at),
  ])) {
    return { status: "stale" };
  }
  if (!(await v213EvidenceWithinWindow(report.records.map(row => {
    const withClass = row as { orders_state_as_of?: string; evidence_class?: string };
    // V212 schema has no evidence_class: fall back to the structural (550d) class so
    // v213EvidenceWithinWindow can resolve a policy key instead of failing on undefined.
    return { freshAsOf: withClass.orders_state_as_of ?? row.retrieved_at, retrievedAt: row.retrieved_at, evidenceClass: withClass.evidence_class ?? "structural_claim", sealTime: report.generated_at };
  })))) {
    return { status: "stale" };
  }

  const runId = view.runId ?? "unknown";
  const date = taipeiDate(now);
  const dedupeKey = `v21:broadcast:${date}:${slot}:${runId}`;
  if (slot !== "test" && (await env.EPHEMERAL_SECURITY_CACHE.get(dedupeKey))) {
    return { status: "duplicate" };
  }

  // v2.1.2 requirement: no title/narrative/score fields in the Top 20 push.
  // Only the exact five requested columns are emitted by the formatter.
  await pushText(env, owner.lineUserId, formatV212Top20Report(report), slot === "test" ? undefined : { date, slot });
  if (slot !== "test") {
    await env.EPHEMERAL_SECURITY_CACHE.put(dedupeKey, "sent", { expirationTtl: 259200 });
  }
  return { status: "sent", slot, run_id: runId, count: 20, format: "v212_five_fields" };
}

export async function scheduledV21Broadcast(
  env: V21BroadcastEnv,
  cron: string,
  now: number,
): Promise<Record<string, unknown>> {
  if (cron === "0 0 * * *") return broadcastV21Top20(env, "morning", now);
  if (cron === "0 13 * * *") return broadcastV21Top20(env, "evening", now);
  return { status: "unsupported_cron" };
}
