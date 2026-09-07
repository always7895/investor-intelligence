import { runV213BroadcastOnce } from "./broadcast-dedupe";
import { publicJson, publicText, type StorageEnv } from "../storage";
import { getOwnerPushTarget } from "../v21/owner-storage";
import { pushMessages, type V21LinePushEnv } from "../v21/line-push";
import { parseV21Top20 } from "../v21/top20";
import { parseV213Top20Report, v213FieldLocale } from "./top20-report";
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

function dailyHumorousReminderText(report: V213Top20Report): string {
  const topNames = report.records.slice(0, 3).map((r) => r.ticker).join("、");
  return [
    "🔔【韭菜守護者・每日早報巡邏】🌱🛡️",
    "報告各位道友！大盤已開，華爾街大鐮刀又在磨刀霍霍了！",
    "",
    "今日最新【TOP 20 物理瓶頸榜單】已新鮮出爐！",
    `當前焦點瓶頸領跑：${topNames} 等 20 檔核心標的～`,
    "誰在手握實體訂單真放量、誰在裸泳炒作割韭菜，後台數據全幫你照妖完畢。",
    "",
    "👇 趕緊點擊下方圖文選單【每日 TOP 20】免費開箱查看完整 20 檔七欄卡片，別讓主力又把你割了！👇",
  ].join("\n");
}

export async function broadcastV213Top20(
  env: V213BroadcastEnv & { V213_TEST_PUSH_FULL_CARDS?: string; V213_EVENING_PUSH_ENABLED?: string },
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

  const reminderMessage: LineOutboundMessage = {
    type: "text",
    text: dailyHumorousReminderText(report),
  };
  const messages = (slot === "test" && env.V213_TEST_PUSH_FULL_CARDS === "true")
    ? buildV213Top20Messages(report, v213FieldLocale(env.V213_FIELD_LOCALE), env.V213_LINE_PRESENTATION === "text" ? "text" : "flex")
    : [reminderMessage];

  const pointer = (await env.PUBLIC_CACHE.get("snapshot:current", "json")) as Record<string, unknown> | null;
  const runId = String(pointer?.run_id ?? "unknown");
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
  env: V213BroadcastEnv & { V213_EVENING_PUSH_ENABLED?: string },
  cron: string,
  now: number,
): Promise<Record<string, unknown>> {
  if (cron === "0 0 * * *") return broadcastV213Top20(env, "morning", now);
  if (cron === "0 13 * * *") {
    if (env.V213_EVENING_PUSH_ENABLED === "true") return broadcastV213Top20(env, "evening", now);
    return { status: "evening_push_disabled_to_save_quota" };
  }
  return { status: "unsupported_cron" };
}
