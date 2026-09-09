import { runV213BroadcastOnce } from "./broadcast-dedupe";
import type { StorageEnv } from "../storage";
import { pinPublicSnapshot } from "./public-snapshot";
import { getOwnerPushTarget } from "../v21/owner-storage";
import { pushMessages, type V21LinePushEnv } from "../v21/line-push";
import { parseV21Top20 } from "../v21/top20";
import { readV213Top20Report, v213FieldLocale } from "./top20-report";
import { buildV213Top20Messages } from "./top20-presentation";

export interface V213BroadcastEnv extends StorageEnv, V21LinePushEnv {
  V213_BROADCAST_DEDUPE?: DurableObjectNamespace;
  V21_SCHEDULED_PUSH_ENABLED?: string;
  V21_TOP20_MAX_AGE_SECONDS?: string;
  V213_FIELD_LOCALE?: string;
  V213_LINE_PRESENTATION?: string;
}

export type V213BroadcastSlot = "morning" | "evening" | "test";

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

export async function broadcastV213Top20(
  env: V213BroadcastEnv,
  slot: V213BroadcastSlot,
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
  const report = await readV213Top20Report(view);
  if (!report) return { status: "top20_report_unavailable" };
  if (report.records.some((item, index) => item.ticker !== records[index]?.ticker)) {
    return { status: "top20_report_order_mismatch" };
  }

  const stamp = (await view.text(["last_successful_pipeline_timestamp"])) ?? "";
  const parsedPipeline = Date.parse(stamp);
  const parsedReport = Date.parse(report.generated_at);
  const maxAge = Math.max(
    300,
    Math.min(86_400, Number(env.V21_TOP20_MAX_AGE_SECONDS ?? "7200") || 7200),
  );
  // A delayed cron's nominal scheduledTime is not the execution clock.
  const observedAt = Date.now();
  const pipelineAgeSeconds = (observedAt - parsedPipeline) / 1000;
  const reportAgeSeconds = (observedAt - parsedReport) / 1000;
  if (
    !Number.isFinite(parsedPipeline) ||
    !Number.isFinite(parsedReport) ||
    pipelineAgeSeconds < -300 ||
    reportAgeSeconds < -300 ||
    pipelineAgeSeconds > maxAge ||
    reportAgeSeconds > maxAge
  ) {
    return { status: "stale" };
  }

  const messages = buildV213Top20Messages(report, v213FieldLocale(env.V213_FIELD_LOCALE), env.V213_LINE_PRESENTATION === "text" ? "text" : "flex");

  const runId = view.runId ?? "unknown";
  const date = taipeiDate(now);
  const dedupeKey = `v213:broadcast:${date}:${slot}:${runId}`;
  if (slot === "test") {
    await pushMessages(env, owner.lineUserId, messages);
  } else {
    if (!env.V213_BROADCAST_DEDUPE) return { status: "dedupe_unavailable" };
    const delivery = await runV213BroadcastOnce(
      env.V213_BROADCAST_DEDUPE,
      dedupeKey,
      () => pushMessages(env, owner.lineUserId, messages),
    );
    if (delivery.status !== "sent") return { status: delivery.status };
  }
  return {
    status: "sent",
    slot,
    run_id: runId,
    count: 20,
    format: "v213_seven_fields",
    field_locale: v213FieldLocale(env.V213_FIELD_LOCALE),
  };
}

export async function scheduledV213Broadcast(
  env: V213BroadcastEnv,
  cron: string,
  now: number,
): Promise<Record<string, unknown>> {
  if (cron === "0 0 * * *") return broadcastV213Top20(env, "morning", now);
  if (cron === "0 13 * * *") return broadcastV213Top20(env, "evening", now);
  return { status: "unsupported_cron" };
}
