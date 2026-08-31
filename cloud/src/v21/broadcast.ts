import { publicJson, publicText, type StorageEnv } from "../storage";
import { getOwnerPushTarget } from "./owner-storage";
import { pushText, type V21LinePushEnv } from "./line-push";
import { formatV21Top20, parseV21Top20 } from "./top20";

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

  const records = parseV21Top20(await publicJson<unknown>(env, ["v21:top20:latest"]));
  if (!records) return { status: "top20_unavailable" };
  const stamp = (await publicText(env, ["last_successful_pipeline_timestamp"])) ?? records[0]!.generated_at;
  const parsed = Date.parse(stamp);
  const maxAge = Math.max(300, Math.min(86_400, Number(env.V21_TOP20_MAX_AGE_SECONDS ?? "7200") || 7200));
  const ageSeconds = (now - parsed) / 1000;
  if (!Number.isFinite(parsed) || ageSeconds < -300 || ageSeconds > maxAge) {
    return { status: "stale" };
  }

  const pointer = (await env.PUBLIC_CACHE.get("snapshot:current", "json")) as Record<string, unknown> | null;
  const runId = String(pointer?.run_id ?? "unknown");
  const date = taipeiDate(now);
  const dedupeKey = `v21:broadcast:${date}:${slot}:${runId}`;
  if (slot !== "test" && (await env.EPHEMERAL_SECURITY_CACHE.get(dedupeKey))) {
    return { status: "duplicate" };
  }

  const title =
    slot === "morning"
      ? `Investor Intelligence 08:00 Top 20｜${date}`
      : slot === "evening"
        ? `Investor Intelligence 21:00 Top 20｜${date}`
        : `Investor Intelligence 測試推送｜${date}`;
  await pushText(env, owner.lineUserId, formatV21Top20(records, title));
  if (slot !== "test") {
    await env.EPHEMERAL_SECURITY_CACHE.put(dedupeKey, "sent", { expirationTtl: 259200 });
  }
  return { status: "sent", slot, run_id: runId, count: 20 };
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
