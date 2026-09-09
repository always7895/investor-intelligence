export { V213BroadcastDedupe } from "./broadcast-dedupe";
export { V213FreeRelayRoute } from "./free-relay";
import v211Worker, { V211_GENERAL_QA, V211_TOP20_REPORT, type V211Env } from "../v211/worker";
import { compactGeneralAnswer, compactCompletionBody, minimalModelSmoke } from "./compact-qa";
import { v213FieldLocale } from "./top20-report";
import { v213Top20LineAnswer } from "./top20-presentation";
import { authenticateV21AdminRequest } from "../v21/admin";
import {
  finalizeV213Activation,
  ingestV213ActivationBundle,
  rollbackV213Activation,
} from "./activation-v3";
import { broadcastV213Top20, scheduledV213Broadcast } from "./broadcast";
import {
  currentFreeRelayRoute,
  freeRelayEnabled,
  freeRelayRuntimeOverrides,
  updateFreeRelayRoute,
  type FreeRelayEnv,
} from "./free-relay";

import { edgeReadiness, servingVersion, type VersionEnv } from "./readiness";

type V213ProductionEnv = V211Env & FreeRelayEnv & VersionEnv & { V213_COMPACT_QA_ENABLED?: string; V213_FIELD_LOCALE?: string };

type RuntimeFetch = typeof fetch;

function requestUrl(input: RequestInfo | URL): URL | null {
  try {
    if (input instanceof Request) return new URL(input.url);
    return new URL(String(input));
  } catch {
    return null;
  }
}

/**
 * Cloudflare's production runtime rejects redirect: "error" before issuing a
 * request.  The certified Q&A module intentionally remains byte-for-byte
 * unchanged, so emulate that standard Fetch behavior only for its HTTPS local
 * model completion call: observe redirects with "manual", then reject 3xx.
 */
export async function v213RuntimeCompatibleFetch(
  nativeFetch: RuntimeFetch,
  input: RequestInfo | URL,
  init?: RequestInit,
): Promise<Response> {
  const url = requestUrl(input);
  const method = String(init?.method ?? (input instanceof Request ? input.method : "GET")).toUpperCase();
  const adapt = init?.redirect === "error" && method === "POST" && url?.protocol === "https:" &&
    url.pathname === "/v1/chat/completions";
  if (!adapt) return nativeFetch(input, init);
  let body = init?.body;
  if (typeof body === "string") {
    let parsed: unknown;
    try { parsed = JSON.parse(body); } catch { parsed = null; }
    const compact = compactCompletionBody(parsed);
    if (compact) body = JSON.stringify(compact);
  }
  const response = await nativeFetch(input, { ...init, body, redirect: "manual" });
  if (response.status >= 300 && response.status < 400) {
    throw new TypeError("V213_LOCAL_MODEL_REDIRECT_REJECTED");
  }
  return response;
}

const nativeRuntimeFetch = globalThis.fetch.bind(globalThis) as RuntimeFetch;
globalThis.fetch = ((input: RequestInfo | URL, init?: RequestInit) =>
  v213RuntimeCompatibleFetch(nativeRuntimeFetch, input, init)) as RuntimeFetch;

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

function errorCode(error: unknown, fallback: string): string {
  return error instanceof Error ? error.message : fallback;
}

function validationStatus(code: string): number {
  if (/STATE|POINTER|CONCURRENT|COLLISION|ALREADY|MISMATCH|REPLAY|STALE|EXPIRED/.test(code)) return 409;
  return 400;
}

export async function freeRelayRequestEnv(env: V213ProductionEnv): Promise<V213ProductionEnv> {
  // v213 uses one compact path. Explicit false is an operational rollback,
  // not a second model or paid fallback. Legacy qa.ts safety checks still run.
  const handler = env.V213_COMPACT_QA_ENABLED !== "false" ? compactGeneralAnswer : undefined;
  if (!freeRelayEnabled(env)) return { ...env, [V211_GENERAL_QA]: handler, [V211_TOP20_REPORT]: v213Top20LineAnswer };
  const overrides = await freeRelayRuntimeOverrides(env);
  return {
    ...env,
    [V211_GENERAL_QA]: handler,
    [V211_TOP20_REPORT]: v213Top20LineAnswer,
    LOCAL_LLM_BASE_URL: overrides?.LOCAL_LLM_BASE_URL ?? "",
    LOCAL_LLM_ALLOWED_HOSTS: overrides?.LOCAL_LLM_ALLOWED_HOSTS ?? "",
    LOCAL_LLM_MODEL: overrides?.LOCAL_LLM_MODEL ?? "qwen38-q6",
    LOCAL_LLM_SHARED_SECRET: overrides?.LOCAL_LLM_SHARED_SECRET ?? "",
    LOCAL_LLM_API_KEY: "",
  };
}

async function authenticatedBody(request: Request, env: V211Env): Promise<string | Response> {
  try {
    return await authenticateV21AdminRequest(request, env);
  } catch (error) {
    return jsonResponse({ ok: false, code: errorCode(error, "V213_AUTH_FAILED") }, 401);
  }
}

async function handleFreeRelaySmoke(request: Request, env: V213ProductionEnv): Promise<Response> {
  const authenticated = await authenticatedBody(request, env);
  if (authenticated instanceof Response) return authenticated;
  try {
    const value = JSON.parse(authenticated) as Record<string, unknown>;
    if (!value || Array.isArray(value) || Object.keys(value).length !== 1 || value.schema_version !== 1) {
      throw new Error("FREE_RELAY_SMOKE_REQUEST_INVALID");
    }
    const route = await currentFreeRelayRoute(env);
    if (!route) throw new Error("FREE_RELAY_UNAVAILABLE");
    if (!(await minimalModelSmoke(await freeRelayRequestEnv(env)))) throw new Error("FREE_RELAY_SMOKE_MODEL_RESPONSE_INVALID");
    return jsonResponse({
      ok: true,
      status: "PASS",
      model: route.model,
      route_generation: route.route_generation,
      health_schema_version: route.health_schema_version,
      stable_entrypoint: "workers_dev",
      expected_token_observed: true,
    });
  } catch (error) {
    const code = errorCode(error, "FREE_RELAY_SMOKE_FAILED");
    return jsonResponse({ ok: false, code }, validationStatus(code));
  }
}

async function handleActivationTransaction(
  request: Request,
  env: V211Env & VersionEnv,
  action: "commit" | "rollback" | "finalize",
): Promise<Response> {
  const authenticated = await authenticatedBody(request, env);
  if (authenticated instanceof Response) return authenticated;
  try {
    const result = action === "commit"
      ? await ingestV213ActivationBundle(authenticated, env)
      : action === "rollback"
        ? await rollbackV213Activation(authenticated, env)
        : await finalizeV213Activation(authenticated, env);
    return jsonResponse({ ...result, worker_version: servingVersion(env) });
  } catch (error) {
    const code = errorCode(error, "V213_ACTIVATION_TRANSACTION_FAILED");
    return jsonResponse({ ok: false, code, action }, validationStatus(code));
  }
}

/**
 * v2.1.3 production entrypoint.
 *
 * Ordinary request behavior remains delegated to the accepted v2.1.2 owner
 * Worker, including local-model QA. The v2.1.3 activation bundle is committed
 * transactionally: all immutable run objects are validated and written before
 * the public pointer. A short-lived exact-pointer rollback handle is retained
 * until the caller finalizes the Worker/runtime deployment.
 */
export default {
  async fetch(request: Request, env: V213ProductionEnv, ctx: ExecutionContext): Promise<Response> {
    const url = new URL(request.url);
    // Legacy single-object writes can replace sealed pointers or mutate hashed
    // run objects. Retire them before authentication/nonce or storage access.
    if (["/v21/admin/public-snapshot", "/v212/admin/top20-report", "/v213/admin/top20-report"].includes(url.pathname)) {
      return jsonResponse({ ok: false, code: "V213_SEALED_PUBLICATION_REQUIRED" }, 410);
    }
    if (url.pathname === "/v213/readiness") return edgeReadiness(request, env);
    if (url.pathname === "/health" && request.method === "GET") {
      const base = await v211Worker.fetch(request, env, ctx);
      return jsonResponse({ ...await base.json<Record<string, unknown>>(), service: "investor-intelligence-v213-owner-line", product_version: "2.1.3", top20_presentation: "seven_fields", top20_field_locale: v213FieldLocale(env.V213_FIELD_LOCALE) });
    }
    if (request.method === "POST" && url.pathname === "/v213/admin/activation-bundle") {
      // Before authentication's nonce write: stale serving code cannot commit.
      const version = servingVersion(env);
      if (!version || request.headers.get("x-ii-expected-worker-version") !== version) {
        return jsonResponse({ ok: false, code: "V213_ACTIVATION_SERVING_VERSION_MISMATCH", worker_version: version }, 409);
      }
      return handleActivationTransaction(request, env, "commit");
    }
    if (request.method === "POST" && url.pathname === "/v213/admin/activation-rollback") {
      return handleActivationTransaction(request, env, "rollback");
    }
    if (request.method === "POST" && url.pathname === "/v213/admin/activation-finalize") {
      return handleActivationTransaction(request, env, "finalize");
    }
    if (request.method === "POST" && url.pathname === "/v213/admin/free-relay-smoke") {
      return handleFreeRelaySmoke(request, env);
    }
    if (request.method === "POST" && url.pathname === "/v213/admin/free-relay-route") {
      const authenticated = await authenticatedBody(request, env);
      if (authenticated instanceof Response) return authenticated;
      try {
        return jsonResponse({ status: "accepted", ...(await updateFreeRelayRoute(authenticated, env)) });
      } catch (error) {
        const code = errorCode(error, "FREE_RELAY_UPDATE_FAILED");
        return jsonResponse({ ok: false, code }, validationStatus(code));
      }
    }
    if (request.method === "POST" && ["/v213/admin/test-push", "/v21/admin/test-push"].includes(url.pathname)) {
      const authenticated = await authenticatedBody(request, env);
      if (authenticated instanceof Response) return authenticated;
      try {
        return jsonResponse(await broadcastV213Top20(env, "test"));
      } catch (error) {
        const code = errorCode(error, "V213_TEST_PUSH_FAILED");
        return jsonResponse({ ok: false, code }, validationStatus(code));
      }
    }
    return v211Worker.fetch(request, await freeRelayRequestEnv(env), ctx);
  },

  async scheduled(
    controller: ScheduledController,
    env: V213ProductionEnv,
    ctx: ExecutionContext,
  ): Promise<void> {
    ctx.waitUntil(
      scheduledV213Broadcast(env, controller.cron, controller.scheduledTime).then((result) => {
        if (!["sent", "duplicate", "disabled"].includes(String(result.status ?? ""))) {
          console.error("V213_SCHEDULED_BROADCAST_SKIPPED", String(result.status ?? "unknown"));
        }
      }),
    );
  },
} satisfies ExportedHandler<V213ProductionEnv>;
