import { helpText, parseQuery, type ParsedQuery } from "../core";
import { replyMessages, type LineOutboundMessage } from "../line-messages";
import {
  claimEvent,
  completeEvent,
  eventIsFresh,
  rateLimit,
  releaseEvent,
  replyText,
  verifyLineSignature,
  type LineEnv,
  type LineEvent,
  type LineTextMessage,
} from "../line";
import { manualOptionQuoteAnswer } from "../manual-options";
import {
  deterministicAnswer,
  generalAnswer,
  type QaEnv,
  type RequestContext,
} from "../qa";
import {
  deriveTenantId,
  randomReference,
  tenantHashSecret,
  tenantSecretsConfigured,
  timingSafeEqual,
  type LineSourceIdentity,
} from "../security";
import { deleteTenantData, putJob, tenantWriteEpoch } from "../storage";
import {
  authenticateV21AdminRequest,
  ingestV21PublicSnapshot,
  type V21AdminEnv,
} from "../v21/admin";
import {
  broadcastV21Top20,
  scheduledV21Broadcast,
  type V21BroadcastEnv,
} from "../v21/broadcast";
import {
  isOwnerTenant,
  ownerPairingStatus,
  removeOwnerPairing,
  storeOwnerPairing,
} from "../v21/owner-storage";
import { v21Top20Answer } from "../v21/top20";
import { ingestV212Top20Report } from "../v212/admin";
import { v212Top20ReportAnswer } from "../v212/top20-report";
import { ingestV211PublicSnapshot } from "./admin";
import { humanizeFallback, v211HelpText, v211ResearchAnswer } from "./research";

// Internal dependency injection only; a config string cannot install a handler.
export const V211_GENERAL_QA = Symbol("v213.request-scoped-general-qa");
export const V211_TOP20_REPORT = Symbol("v213.request-scoped-top20-report");

export interface V211Env extends QaEnv, LineEnv, V21AdminEnv, V21BroadcastEnv {
  [V211_GENERAL_QA]?: typeof generalAnswer;
  [V211_TOP20_REPORT]?: (env: V211Env, query: ParsedQuery) => Promise<string | LineOutboundMessage[] | null>;
  V21_OWNER_PAIRING_ENABLED?: string;
  V21_OWNER_PAIRING_CODE_HASH?: string;
  V21_MAX_WEBHOOK_BODY_BYTES?: string;
}

function envBool(value: string | undefined): boolean {
  return ["1", "true", "yes", "on"].includes((value ?? "").trim().toLowerCase());
}

function jsonResponse(value: unknown, status = 200): Response {
  return new Response(JSON.stringify(value), {
    status,
    headers: {
      "content-type": "application/json; charset=utf-8",
      "cache-control": "no-store",
      "x-content-type-options": "nosniff",
    },
  });
}

function lineHelpText(): string {
  return [
    helpText(),
    "",
    v211HelpText(),
    "",
    "通知：每日早晨 08:00（Asia/Taipei）單次推送最新動態巡邏提醒，極致守護每月推播額度。",
    "Top 20 完整七欄：股票／長期投資報酬率／短期投資報酬率／行業別／獲利簡述／目前訂單／未來訂單預估（100% 綁定第一方法定訂單與合約）。",
    "Serenity 是主評分框架；Aschenbrenner 只作獨立 overlay。多來源體系涵蓋 Google、SEC EDGAR、Nasdaq、CBOE、MOPS、SEMI 與 TrendForce 等官方權威數據。",
  ].join("\n");
}

function sourceFromEvent(event: LineEvent): LineSourceIdentity | null {
  const source = event.source;
  if (!source || !["user", "group", "room"].includes(source.type)) return null;
  return source;
}

function eventText(event: LineEvent): string | null {
  if (event.type === "message" && event.message?.type === "text") {
    return String((event.message as LineTextMessage).text ?? "");
  }
  if (event.type === "postback") return event.postback?.data ?? null;
  return null;
}

async function sha256(value: string): Promise<string> {
  const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(value));
  return Array.from(new Uint8Array(digest), (byte) => byte.toString(16).padStart(2, "0")).join("");
}

async function pairingCodeValid(env: V211Env, code: string): Promise<boolean> {
  const expected = (env.V21_OWNER_PAIRING_CODE_HASH ?? "").trim().toLowerCase();
  return (
    envBool(env.V21_OWNER_PAIRING_ENABLED) &&
    /^[0-9a-f]{64}$/.test(expected) &&
    timingSafeEqual(await sha256(code), expected)
  );
}

async function processPairing(
  env: V211Env,
  event: LineEvent,
  source: LineSourceIdentity,
  tenantId: string,
  text: string,
): Promise<boolean> {
  const match = text.normalize("NFKC").trim().match(/^(?:配對|配对|pair)\s+([A-Za-z0-9_-]{8,80})$/i);
  if (!match) return false;
  if (!event.replyToken || source.type !== "user" || !source.userId) return true;
  if (await ownerPairingStatus(env)) {
    if (await isOwnerTenant(env, tenantId)) {
      await replyText(env, event.replyToken, "通知擁有者已完成配對。若要更換，先輸入「取消配對」。");
    }
    return true;
  }
  if (!(await rateLimit(env, tenantId, "v21_owner_pairing"))) return true;
  if (await env.EPHEMERAL_SECURITY_CACHE.get("v21:owner-pairing-code-used")) {
    await replyText(env, event.replyToken, "一次性配對碼已使用。請在本機重新產生配對碼。");
    return true;
  }
  if (!(await pairingCodeValid(env, match[1] ?? ""))) {
    await replyText(env, event.replyToken, "配對碼無效或已停用。");
    return true;
  }
  await storeOwnerPairing(env, tenantId, source.userId);
  await env.EPHEMERAL_SECURITY_CACHE.put("v21:owner-pairing-code-used", "used");
  await replyText(
    env,
    event.replyToken,
    "通知已安全配對。公開 Top 20 會在每天 08:00 與 21:00（Asia/Taipei）通過 freshness gate 後推送。",
  );
  return true;
}

export async function processAuthorizedLineEvent(
  env: V211Env,
  ctx: ExecutionContext,
  event: LineEvent,
  tenantId: string,
): Promise<void> {
  const requestContext: RequestContext = { tenantId, chatType: "user" };
  if (event.type === "follow") {
    if (event.replyToken) await replyText(env, event.replyToken, lineHelpText());
    return;
  }

  const text = eventText(event);
  if (!text || !event.replyToken) return;
  const normalized = text.normalize("NFKC").trim();
  if (/^(?:取消配對|取消配对|unpair)$/i.test(normalized)) {
    await removeOwnerPairing(env, tenantId);
    await replyText(env, event.replyToken, "排程通知配對已取消。重新配對必須在本機產生新的單次配對碼。");
    return;
  }
  if (/^(?:通知狀態|通知状态|notification status)$/i.test(normalized)) {
    await replyText(
      env,
      event.replyToken,
      (await isOwnerTenant(env, tenantId))
        ? "通知狀態：PAIRED；排程為 08:00／21:00 Asia/Taipei；資料過期時 fail closed。"
        : "通知狀態：NOT_PAIRED。",
    );
    return;
  }

  const query = parseQuery(text);
  if (!(await rateLimit(env, tenantId, query.intent))) {
    await replyText(env, event.replyToken, "請求過於頻繁，請稍後再試。");
    return;
  }

  const manualOption = manualOptionQuoteAnswer(text);
  if (manualOption !== null) {
    await replyText(env, event.replyToken, manualOption);
    return;
  }

  if (query.intent === "delete_data") {
    await removeOwnerPairing(env, tenantId);
    const deleted = await deleteTenantData(env, tenantId);
    await replyText(
      env,
      event.replyToken,
      `你的 tenant-scoped 對話／工作與通知配對資料已刪除（${deleted} 個項目）。重新啟用通知需要本機產生新的單次配對碼。`,
    );
    return;
  }

  // v213's published report must win over all legacy five-field routes.
  const currentReport = await env[V211_TOP20_REPORT]?.(env, query);
  if (currentReport != null) {
    if (typeof currentReport === "string") {
      await replyText(env, event.replyToken, currentReport);
    } else {
      try {
        await replyMessages(env, event.replyToken, currentReport);
      } catch (err) {
        console.error("V213_FLEX_REPLY_FAILED", err instanceof Error ? err.message : String(err));
        const alt = currentReport[0]?.altText ?? "系統已完成分析，請查看圖文選單。";
        await replyText(env, event.replyToken, alt);
      }
    }
    return;
  }

  // The signed Serenity universe remains the deterministic ticker-research lane.
  const research = await v211ResearchAnswer(env, query);
  if (research !== null) {
    await replyText(env, event.replyToken, research);
    return;
  }

  // v2.1.2 no-ticker Top 20 presentation is deliberately constrained to the
  // five user-facing columns. It is checked before the legacy Top 20 renderer.
  const top20Report = await v212Top20ReportAnswer(env, query);
  if (top20Report !== null) {
    await replyText(env, event.replyToken, top20Report);
    return;
  }

  const top20 = await v21Top20Answer(env, query);
  if (top20 !== null) {
    await replyText(env, event.replyToken, top20);
    return;
  }

  const deterministic = await deterministicAnswer(env, query, requestContext);
  if (deterministic !== null) {
    await replyText(
      env,
      event.replyToken,
      query.intent === "help" ? lineHelpText() : humanizeFallback(deterministic, query),
    );
    return;
  }

  const operationEpoch = await tenantWriteEpoch(env, tenantId);
  const answerPromise = (env[V211_GENERAL_QA] ?? generalAnswer)(env, query, requestContext);
  const syncTimeoutMs = Number((env as Record<string, unknown>).LINE_SYNC_TIMEOUT_MS ?? "7000") || 7000;
  const timeout = new Promise<null>((resolve) => setTimeout(() => resolve(null), syncTimeoutMs));
  const quick = await Promise.race([answerPromise, timeout]);
  if (quick !== null) {
    await replyText(env, event.replyToken, humanizeFallback(quick, query));
    return;
  }

  const referenceId = randomReference();
  const createdAt = new Date().toISOString();
  const pendingStored = await putJob(
    env,
    tenantId,
    referenceId,
    { status: "pending", createdAt },
    operationEpoch,
  );
  if (!pendingStored) {
    await replyText(env, event.replyToken, "工作已取消，未保存任何私人結果。");
    return;
  }
  await replyText(
    env,
    event.replyToken,
    `問題已收到，參考編號 ${referenceId}。稍後輸入「查看結果 ${referenceId}」。`,
  );
  ctx.waitUntil(
    answerPromise
      .then((answer) =>
        putJob(
          env,
          tenantId,
          referenceId,
          {
            status: "complete",
            createdAt,
            completedAt: new Date().toISOString(),
            result: humanizeFallback(answer, query),
          },
          operationEpoch,
        ),
      )
      .catch(() =>
        putJob(
          env,
          tenantId,
          referenceId,
          {
            status: "error",
            createdAt,
            completedAt: new Date().toISOString(),
            errorCode: "QA_PROCESSING_FAILED",
          },
          operationEpoch,
        ),
      ),
  );
}

async function processLineEvent(
  env: V211Env,
  ctx: ExecutionContext,
  event: LineEvent,
): Promise<void> {
  if (!eventIsFresh(event, env)) return;
  const source = sourceFromEvent(event);
  if (!source || source.type !== "user" || !tenantSecretsConfigured(env)) return;

  const tenantId = await deriveTenantId(source, tenantHashSecret(env));
  const text = eventText(event);
  const pairingRequest = Boolean(
    text?.normalize("NFKC").trim().match(/^(?:配對|配对|pair)\s+/i),
  );
  if (!(await claimEvent(env, event.webhookEventId))) return;

  try {
    if (pairingRequest && text && (await processPairing(env, event, source, tenantId, text))) {
      await completeEvent(env, event.webhookEventId);
      return;
    }
    await processAuthorizedLineEvent(env, ctx, event, tenantId);
    await completeEvent(env, event.webhookEventId);
  } catch (error) {
    await releaseEvent(env, event.webhookEventId);
    throw error;
  }
}

async function handleWebhook(
  request: Request,
  env: V211Env,
  ctx: ExecutionContext,
): Promise<Response> {
  const maxBytes = Math.max(
    4096,
    Math.min(1_048_576, Number(env.V21_MAX_WEBHOOK_BODY_BYTES ?? "262144") || 262144),
  );
  const length = Number(request.headers.get("content-length") ?? "0");
  if (Number.isFinite(length) && length > maxBytes) return new Response("payload too large", { status: 413 });
  const rawBody = await request.text();
  if (new TextEncoder().encode(rawBody).length > maxBytes) return new Response("payload too large", { status: 413 });
  if (!(await verifyLineSignature(rawBody, request.headers.get("x-line-signature"), env.LINE_CHANNEL_SECRET))) {
    return new Response("invalid signature", { status: 401 });
  }

  let payload: { events?: LineEvent[] };
  try {
    payload = JSON.parse(rawBody) as { events?: LineEvent[] };
  } catch {
    return new Response("invalid JSON", { status: 400 });
  }
  const events = Array.isArray(payload.events) ? payload.events : [];
  if (events.length > 20) return new Response("too many events", { status: 413 });
  for (const event of events) {
    ctx.waitUntil(
      processLineEvent(env, ctx, event).catch((error) => {
        console.error("V212_LINE_EVENT_FAILED", error instanceof Error ? error.name : "UNKNOWN");
      }),
    );
  }
  return new Response("OK");
}

async function handleAdmin(
  request: Request,
  env: V211Env,
  pathname: string,
): Promise<Response> {
  try {
    const body = await authenticateV21AdminRequest(request, env);
    if (pathname === "/v21/admin/public-snapshot") {
      let schema = 1;
      try {
        schema = Number((JSON.parse(body) as { schema_version?: unknown }).schema_version ?? 1);
      } catch {
        return jsonResponse({ ok: false, code: "SNAPSHOT_JSON_INVALID" }, 400);
      }
      return jsonResponse({
        status: "accepted",
        ...(schema === 2
          ? await ingestV211PublicSnapshot(body, env)
          : await ingestV21PublicSnapshot(body, env)),
      });
    }
    if (pathname === "/v212/admin/top20-report") {
      return jsonResponse({
        status: "accepted",
        ...(await ingestV212Top20Report(body, env)),
      });
    }
    if (pathname === "/v21/admin/status") {
      const pointer = await env.PUBLIC_CACHE.get("snapshot:current");
      return jsonResponse({
        ok: true,
        product_version: "2.1.2",
        owner_paired: await ownerPairingStatus(env),
        public_snapshot_available: Boolean(pointer),
      });
    }
    if (pathname === "/v21/admin/test-push") {
      return jsonResponse(await broadcastV21Top20(env, "test"));
    }
    return new Response("Not found", { status: 404 });
  } catch (error) {
    return jsonResponse(
      { ok: false, code: error instanceof Error ? error.message : "V212_ADMIN_FAILED" },
      401,
    );
  }
}

function health(): Response {
  return jsonResponse({
    ok: true,
    service: "investor-intelligence-v212-owner-line",
    product_version: "2.1.2",
    owner_only: true,
    direct_chat_only: true,
    scheduled_times: ["08:00 Asia/Taipei", "21:00 Asia/Taipei"],
    serenity_first: true,
    scoring_formula: "serenity-first-v2.1.0",
    candidate_discovery: "broad_plus_ai_infrastructure_thematic_plus_sec_name_coverage",
    research_universe_qa: "signed_public_snapshot_plus_local_multi_source_fallback",
    top20_presentation: "five_fields_only",
    public_options: "scored_universe_yfinance_public_only",
    source_catalog_count: 101,
    source_activation_claim: "reviewed_catalog_not_all_runtime_enabled",
    owner_watchlist_inherited: false,
    manual_option_calculator: "ephemeral_user_supplied_only",
    portfolio_access: false,
    brokerage_connection: false,
    ibkr_bridge: false,
    automatic_trading: false,
    cloud_generation: "disabled",
    paid_fallback: false,
  });
}

export default {
  async fetch(request: Request, env: V211Env, ctx: ExecutionContext): Promise<Response> {
    const url = new URL(request.url);
    if (request.method === "GET" && url.pathname === "/health") return health();
    if (request.method === "POST" && url.pathname === "/webhook") {
      return handleWebhook(request, env, ctx);
    }
    if (
      request.method === "POST" &&
      (url.pathname.startsWith("/v21/admin/") || url.pathname.startsWith("/v212/admin/"))
    ) {
      return handleAdmin(request, env, url.pathname);
    }
    return new Response("Not found", { status: 404 });
  },

  async scheduled(
    controller: ScheduledController,
    env: V211Env,
    ctx: ExecutionContext,
  ): Promise<void> {
    ctx.waitUntil(
      scheduledV21Broadcast(env, controller.cron, controller.scheduledTime)
        .then((result) => console.log("V212_SCHEDULED_TOP20", String(result.status ?? "unknown")))
        .catch((error) => console.error("V212_SCHEDULED_TOP20_FAILED", error instanceof Error ? error.name : "UNKNOWN")),
    );
  },
} satisfies ExportedHandler<V211Env>;
