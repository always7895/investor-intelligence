import { splitLineText } from "../core";
import { publicJson, publicText, type StorageEnv } from "../storage";
import { getOwnerPushTarget } from "../v21/owner-storage";
import { pushText, type V21LinePushEnv } from "../v21/line-push";
import { parseV21Top20 } from "../v21/top20";
import { formatV213Top20Report, parseV213Top20Report } from "./top20-report";
import type { FieldLocale } from "./field-labels";

export interface V213BroadcastEnv extends StorageEnv, V21LinePushEnv {
  V21_SCHEDULED_PUSH_ENABLED?: string;
  V21_TOP20_MAX_AGE_SECONDS?: string;
  V213_FIELD_LOCALE?: string;
}

export type V213BroadcastSlot = "morning" | "evening" | "test";

function enabled(value: string | undefined): boolean {
  return ["1", "true", "yes", "on"].includes((value ?? "").trim().toLowerCase());
}

function locale(value: string | undefined): FieldLocale {
  const normalized = (value ?? "zh-TW").trim().toLowerCase();
  if (normalized === "en" || normalized === "english") return "en";
  if (normalized === "bilingual" || normalized === "zh-en" || normalized === "zh+en") return "bilingual";
  return "zh-TW";
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

  const records = parseV21Top20(await publicJson<unknown>(env, ["v21:top20:latest"]));
  if (!records) return { status: "top20_unavailable" };
  const report = parseV213Top20Report(
    await publicJson<unknown>(env, ["v213:top20-report:latest"]),
  );
  if (!report) return { status: "top20_report_unavailable" };
  if (report.records.some((item, index) => item.ticker !== records[index]?.ticker)) {
    return { status: "top20_report_order_mismatch" };
  }

  const stamp = (await publicText(env, ["last_successful_pipeline_timestamp"])) ?? records[0]!.generated_at;
  const parsedPipeline = Date.parse(stamp);
  const parsedReport = Date.parse(report.generated_at);
  const maxAge = Math.max(
    300,
    Math.min(86_400, Number(env.V21_TOP20_MAX_AGE_SECONDS ?? "7200") || 7200),
  );
  const pipelineAgeSeconds = (now - parsedPipeline) / 1000;
  const reportAgeSeconds = (now - parsedReport) / 1000;
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

  const message = formatV213Top20Report(report, locale(env.V213_FIELD_LOCALE));
  const chunks = splitLineText(message, 4900, 5);
  if (chunks.length !== 1 || chunks[0] !== message) {
    return { status: "seven_field_message_not_single_chunk" };
  }

  const pointer = (await env.PUBLIC_CACHE.get("snapshot:current", "json")) as Record<string, unknown> | null;
  const runId = String(pointer?.run_id ?? "unknown");
  const date = taipeiDate(now);
  const dedupeKey = `v213:broadcast:${date}:${slot}:${runId}`;
  if (slot !== "test" && (await env.EPHEMERAL_SECURITY_CACHE.get(dedupeKey))) {
    return { status: "duplicate" };
  }

  await pushText(env, owner.lineUserId, message);
  if (slot !== "test") {
    await env.EPHEMERAL_SECURITY_CACHE.put(dedupeKey, "sent", { expirationTtl: 259200 });
  }
  return {
    status: "sent",
    slot,
    run_id: runId,
    count: 20,
    format: "v213_seven_fields",
    field_locale: locale(env.V213_FIELD_LOCALE),
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
