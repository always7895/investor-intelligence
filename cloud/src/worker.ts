import { helpText, parseQuery } from "./core";
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
} from "./line";
import { manualOptionQuoteAnswer } from "./manual-options";
import {
  deterministicAnswer,
  generalAnswer,
  type QaEnv,
  type RequestContext,
} from "./qa";
import {
  deriveTenantId,
  lineAccessAllowed,
  lineAccessMode,
  randomReference,
  tenantHashSecret,
  tenantSecretsConfigured,
  type LineSourceIdentity,
} from "./security";
import { putJob, tenantWriteEpoch } from "./storage";

export interface Env extends QaEnv, LineEnv {
  MAX_WEBHOOK_BODY_BYTES?: string;
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
    "無自動報價來源時，可輸入「期權試算說明」，使用本次訊息提供的 BID / ASK 做不保存、不連券商的算術試算。",
  ].join("\n");
}

function sourceFromEvent(event: LineEvent): LineSourceIdentity | null {
  const source = event.source;
  if (!source || !["user", "group", "room"].includes(source.type)) return null;
  return source;
}

async function processAuthorizedLineEvent(
  env: Env,
  ctx: ExecutionContext,
  event: LineEvent,
  tenantId: string,
): Promise<void> {
  const requestContext: RequestContext = {
    tenantId,
    chatType: "user",
  };

  if (event.type === "follow") {
    if (event.replyToken) await replyText(env, event.replyToken, lineHelpText());
    return;
  }

  let text: string | null = null;
  if (event.type === "message" && event.message?.type === "text") {
    text = String((event.message as LineTextMessage).text ?? "");
  } else if (event.type === "postback") {
    text = event.postback?.data ?? null;
  }
  if (!text || !event.replyToken) return;

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

  const deterministic = await deterministicAnswer(env, query, requestContext);
  if (deterministic !== null) {
    await replyText(
      env,
      event.replyToken,
      query.intent === "help" ? lineHelpText() : deterministic,
    );
    return;
  }

  // Capture the tenant write epoch before starting a potentially long model
  // operation. A concurrent "delete my data" rotates this epoch first, making
  // every late completion from this operation unreachable and non-persistable.
  const operationEpoch = await tenantWriteEpoch(env, tenantId);
  const answerPromise = generalAnswer(env, query, requestContext);
  const timeout = new Promise<null>((resolve) => setTimeout(() => resolve(null), 7000));
  const quick = await Promise.race([answerPromise, timeout]);
  if (quick !== null) {
    await replyText(env, event.replyToken, quick);
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
            result: answer,
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

async function processLineEvent(env: Env, ctx: ExecutionContext, event: LineEvent): Promise<void> {
  if (!eventIsFresh(event, env)) return;
  const source = sourceFromEvent(event);
  // Disabled, invalidly configured, group/room and non-allowlisted events are
  // silently ignored before any tenant/event/rate-limit KV write or LINE reply.
  // This preserves the free reply quota and prevents deployment configuration
  // from reopening a shared-chat surface.
  if (
    !source ||
    source.type !== "user" ||
    lineAccessMode(env) === "disabled" ||
    !tenantSecretsConfigured(env)
  ) {
    return;
  }

  const tenantId = await deriveTenantId(source, tenantHashSecret(env));
  if (!lineAccessAllowed(env, tenantId, source.type)) return;
  if (!(await claimEvent(env, event.webhookEventId))) return;

  try {
    await processAuthorizedLineEvent(env, ctx, event, tenantId);
    await completeEvent(env, event.webhookEventId);
  } catch (error) {
    await releaseEvent(env, event.webhookEventId);
    throw error;
  }
}

async function handleWebhook(request: Request, env: Env, ctx: ExecutionContext): Promise<Response> {
  const configured = Number(env.MAX_WEBHOOK_BODY_BYTES ?? "262144");
  const maxBytes = Number.isFinite(configured) ? Math.max(1024, configured) : 262144;
  const contentLength = Number(request.headers.get("content-length") ?? "0");
  if (Number.isFinite(contentLength) && contentLength > maxBytes) {
    return new Response("payload too large", { status: 413 });
  }

  const rawBody = await request.text();
  if (new TextEncoder().encode(rawBody).length > maxBytes) {
    return new Response("payload too large", { status: 413 });
  }
  const signature = request.headers.get("x-line-signature");
  if (!(await verifyLineSignature(rawBody, signature, env.LINE_CHANNEL_SECRET))) {
    return new Response("invalid signature", { status: 401 });
  }

  let payload: { events?: LineEvent[] };
  try {
    payload = JSON.parse(rawBody) as { events?: LineEvent[] };
  } catch {
    return new Response("invalid JSON", { status: 400 });
  }

  for (const event of Array.isArray(payload.events) ? payload.events : []) {
    ctx.waitUntil(
      processLineEvent(env, ctx, event).catch((error) => {
        // Log only error class/name; message text and event payload are forbidden.
        console.error("LINE_EVENT_FAILED", error instanceof Error ? error.name : "UNKNOWN");
      }),
    );
  }
  return new Response("OK");
}

async function health(env: Env): Promise<Response> {
  // This endpoint is unauthenticated and intentionally exposes only static
  // safety posture. Exact snapshot IDs, pipeline timestamps, model-route state
  // and tenant/admission membership are not public health metadata.
  return jsonResponse({
    ok: true,
    service: "investor-intelligence-line-bot",
    line_access_mode: lineAccessMode(env),
    direct_chat_only: true,
    options_scope: "public_snapshot_only",
    manual_option_calculator: "ephemeral_user_supplied_only",
    ibkr_bridge: false,
    brokerage_connection: false,
    portfolio_access: false,
    private_sync: false,
    cloud_generation: "disabled",
    scheduled_push: "disabled",
    automatic_trading: false,
    paid_fallback: false,
  });
}

export default {
  async fetch(request: Request, env: Env, ctx: ExecutionContext): Promise<Response> {
    const url = new URL(request.url);
    if (request.method === "GET" && url.pathname === "/health") return health(env);
    if (request.method === "POST" && url.pathname === "/webhook") {
      return handleWebhook(request, env, ctx);
    }
    return new Response("Not found", { status: 404 });
  },
} satisfies ExportedHandler<Env>;
