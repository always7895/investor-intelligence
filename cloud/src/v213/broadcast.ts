import { runV213BroadcastOnce } from "./broadcast-dedupe";
import { publicJson, publicText, type StorageEnv } from "../storage";
import { getOwnerPushTarget } from "../v21/owner-storage";
import { pushMessages, type V21LinePushEnv } from "../v21/line-push";
import { parseV21Top20 } from "../v21/top20";
import { parseV213Top20Report, v213FieldLocale } from "./top20-report";
import { buildV213Top20Messages, STOCK_RESEARCH_KNOWLEDGE_BASE } from "./top20-presentation";

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

const CURRENT_EVENT_TOPICS: Array<{ theme: string; commentary: string }> = [
  {
    theme: "⚡ 雲端巨頭 CapEx 爆表與電力荒",
    commentary: "四大雲端巨頭 2026 資本開支預期突破 3,500 億美元！然而華爾街只看概念，真正懂行的人都在盯變壓器交期與現場發電。沒有電，十萬卡集群就是昂貴的散熱鐵盒，抱緊現場能源與物理瓶頸！",
  },
  {
    theme: "🚀 1.6T 光模組換代加速與 InP 荒",
    commentary: "微軟與 AWS 加速向 800G/1.6T 光互聯狂奔！銅退光進成為物理宿命，上游 InP 磷化銦基板與 CW 雷射短缺已成定局。別被短線主力洗盤甩轎，手握第一手產能契約才能笑到最後！",
  },
  {
    theme: "📦 台積電 CoWoS-L 擴產與先進封裝搶單",
    commentary: "Blackwell 伺服器全面標配 CoWoS-L 封裝，矽中介層達到光罩極限 3.3 倍！晶圓代工總閥門供不應求，一線大廠加價搶產能。認清誰在靠故事裸泳、誰在手握真訂單放量！",
  },
  {
    theme: "💾 美光 HBM3e 售罄與成熟記憶體大缺貨",
    commentary: "三大原廠產能轉往 HBM 引發傳統 DDR3 出現結構性產能真空！經銷通路調查記憶體缺口達 40%-60%，量價齊揚的超級週期正在上演，切忌在黎明前被主力震盪洗出場！",
  },
  {
    theme: "🦾 人形機器人工廠試產與精密絲槓瓶頸",
    commentary: "特斯拉 Optimus 與主流車廠啟動工廠搬運實測！全身 30 餘個致動關節的核心卡在行星滾柱絲槓的 Ra 0.05μm 極限磨削良率。炒作概念不如深挖不可替代的精密機械護城河！",
  },
  {
    theme: "🎯 聯準會利率路徑與半導體週期定海神針",
    commentary: "宏觀降息預期反覆拉扯，科技權值劇烈波動！但在高波動市場中，唯有具備第一方法定待履行訂單（RPO）與多年排他協議的標的，才是穿越多空牛熊的真正定海神針！",
  },
  {
    theme: "🛡️ 華爾街季報季與合約真金白銀檢驗",
    commentary: "財報季來臨，華爾街大鐮刀又在磨刀霍霍！故事吹得再大，終究要面臨法定 SEC 申報與客戶定金的照妖鏡檢驗。守護者每日幫你過濾雜訊，不賣股、高 Strike 穩健收租！",
  },
  {
    theme: "🔋 現場自備微電網避開 5 年電網排隊",
    commentary: "美國電網接入排隊期長達 5-7 年，誰能提供 Behind-the-Meter 現場電源，誰就掌握超大規模算力落地的鑰匙。15-20 年超長 PPA 協議帶來極度確定性的現金流！",
  },
  {
    theme: "🔬 矽光子晶圓代工與片上雷射耦合商業化",
    commentary: "CPO 進入試產衝刺期，光引擎被動封裝技術突飛猛進。市場情緒隨短期消息起伏，唯有鎖定專利壁壘與長約預付款的底層代工廠，才能穩穩享受產業成長紅利！",
  },
  {
    theme: "💡 不賣股為第一優先・高履約價防守收租",
    commentary: "物理約束標的長線倍數潛力極大，『絕不賣股』是第一原則！善用每週價外 +15%～+25% 高 Strike 限價收租，時間價值每週末無損落袋，正股張數一股不少！",
  },
];

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

  const dayOfYear = Math.floor(now / 86_400_000);
  const topic = CURRENT_EVENT_TOPICS[(dayOfYear * 7 + dayIndex) % CURRENT_EVENT_TOPICS.length]!;

  const formatTicker = (ticker: string) => {
    const info = STOCK_RESEARCH_KNOWLEDGE_BASE[ticker];
    return info ? `${ticker} (${info.chineseName})` : ticker;
  };
  const top3 = report.records.slice(0, 3).map((r) => formatTicker(r.ticker)).join("、");
  const sortedByReturn = [...report.records].sort((a, b) => (Number(b.short_term_return_pct) || 0) - (Number(a.short_term_return_pct) || 0));
  const gainer = sortedByReturn[0];

  const featuredIndex = (dayOfYear + dayIndex) % Math.max(1, report.records.length);
  const featured = report.records[featuredIndex];

  const lines = [
    `🛡️【韭菜守護者・每日早報巡邏】📢🕵️（${dateStr}）`,
    weekdayGreetings[dayIndex] || weekdayGreetings[1]!,
    "",
    `🔥 今日焦點時事點評【${topic.theme}】：`,
    topic.commentary,
    "",
    "📊 今日最新【TOP 20 物理瓶頸榜】已完成校準！",
    `當前焦點領跑：${top3} 等 20 檔核心標的～`,
  ];

  if (gainer && Number(gainer.short_term_return_pct) > 0) {
    lines.push(`⚡ 近期動能指標：【${formatTicker(gainer.ticker)}】近6月累積回報 +${Number(gainer.short_term_return_pct).toFixed(1)}%`);
  }

  if (featured && featured.current_orders && !featured.current_orders.includes("未揭露")) {
    lines.push("", `🔍 今日亮點照妖鏡【${formatTicker(featured.ticker)}】：`, `• 訂單合約：${featured.current_orders.slice(0, 75)}`);
  }

  lines.push(
    "",
    "💡 點擊下方圖文選單【宏觀產業分析】查看五大賽道深度評析，或點擊【每日 TOP 20】查看完整雙語卡片！🛡️",
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
