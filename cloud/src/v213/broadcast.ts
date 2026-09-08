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

function taipeiDetails(now = Date.now()): { dayIndex: number; dateStr: string } {
  const d = new Date(now);
  const weekdayStr = new Intl.DateTimeFormat("en-US", { timeZone: "Asia/Taipei", weekday: "short" }).format(d);
  const dayIndex = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"].indexOf(weekdayStr);
  const dateStr = new Intl.DateTimeFormat("zh-TW", { timeZone: "Asia/Taipei", month: "numeric", day: "numeric" }).format(d);
  return { dayIndex: dayIndex >= 0 ? dayIndex : 1, dateStr };
}

function dailyHumorousReminderText(report: V213Top20Report, now = Date.now()): string {
  const { dayIndex, dateStr } = taipeiDetails(now);

  const weekdayGreetings = [
    "【週末沉澱日】不用盯盤的假日時光，最適合靜下心來盤點物理瓶頸，別讓主力的假新聞擾亂節奏！",
    "【週一開工開局】華爾街大鐮刀週末充完電又在磨刀霍霍了！新的一週多空交戰，先看清底層實體訂單！",
    "【週二盤中觀察】主力洗盤甩轎是常態，浮躁追高最容易被收割，數據幫你穩住心態！",
    "【週三週中巡邏】行情走到一週中場，誰在靠故事裸泳、誰在手握真訂單放量，數據全幫你照妖完畢！",
    "【週四夜戰前瞻】重要數據與美股夜戰前夕，市場情緒緊繃，唯有不可替代的物理瓶頸才是定海神針！",
    "【週五結算警戒】每週選擇權今天大結算！主力劇烈洗盤容易引發震盪，抱緊核心護城河！",
    "【週六復盤巡航】週末美股收盤，回顧一週籌碼與訂單變化，為下一波趨勢提前做好準備！",
  ];

  const top3 = report.records.slice(0, 3).map((r) => r.ticker).join("、");
  const sortedByReturn = [...report.records].sort((a, b) => (Number(b.short_term_return_pct) || 0) - (Number(a.short_term_return_pct) || 0));
  const gainer = sortedByReturn[0];

  const dayOfYear = Math.floor(now / 86_400_000);
  const featuredIndex = (dayOfYear + dayIndex) % Math.max(1, report.records.length);
  const featured = report.records[featuredIndex];

  const lines = [
    `🔔【韭菜守護者・每日早報巡邏】🌱🛡️（${dateStr}）`,
    weekdayGreetings[dayIndex] || weekdayGreetings[1],
    "",
    "📊 今日最新【TOP 20 物理瓶頸榜】已完成校準！",
    `當前焦點領跑：${top3} 等 20 檔核心標的～`,
  ];

  if (gainer && Number(gainer.short_term_return_pct) > 0) {
    lines.push(`🔥 近期動能指標：【${gainer.ticker}】近6月累積回報 +${Number(gainer.short_term_return_pct).toFixed(1)}%`);
  }

  if (featured && featured.current_orders && !featured.current_orders.includes("未揭露")) {
    lines.push("", `🔍 今日亮點照妖鏡【${featured.ticker}】：`, `• 訂單合約：${featured.current_orders.slice(0, 75)}`);
  }

  lines.push(
    "",
    "👇 點擊下方圖文選單【每日 TOP 20】免費查看完整 20 檔雙語卡片，別讓主力又把你割了！👇",
  );
  return lines.join("\n");
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
    text: dailyHumorousReminderText(report, now),
  };
  const useReminder = env.V213_BROADCAST_MODE === "reminder";
  const messages = useReminder
    ? [reminderMessage]
    : buildV213Top20Messages(
        report,
        v213FieldLocale(env.V213_FIELD_LOCALE),
        env.V213_LINE_PRESENTATION === "text" ? "text" : "flex",
      );

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
  env: V213BroadcastEnv & { V213_EVENING_PUSH_ENABLED?: string; V213_BROADCAST_MODE?: string },
  cron: string,
  now: number,
): Promise<Record<string, unknown>> {
  if (cron === "0 0 * * *") return broadcastV213Top20(env, "morning", now);
  if (cron === "0 13 * * *") {
    if (env.V213_BROADCAST_MODE === "reminder" && env.V213_EVENING_PUSH_ENABLED !== "true") {
      console.error("V213_SCHEDULED_BROADCAST_SKIPPED evening_push_disabled_to_save_quota");
      return { status: "evening_push_disabled_to_save_quota" };
    }
    return broadcastV213Top20(env, "evening", now);
  }
  return { status: "unsupported_cron" };
}
