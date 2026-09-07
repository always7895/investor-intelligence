export interface FreeRelayEnv {
  V213_FREE_RELAY_ROUTE?: DurableObjectNamespace;
  V21_SYNC_HMAC_SECRET?: string;
  FREE_RELAY_ENABLED?: string;
  FREE_RELAY_MAX_TTL_SECONDS?: string;
  LOCAL_LLM_MODEL?: string;
}

export interface FreeRelayRouteRecord {
  schema_version: 1;
  tunnel_mode: "quick_free_relay";
  model: string;
  public_url: string;
  connected_at: string;
  expires_at: string;
  health_schema_version: 2;
  route_generation: string;
  consecutive_health_checks: 3;
}

interface StoredRoute extends FreeRelayRouteRecord {
  accepted_at: string;
}

const ENCODER = new TextEncoder();
const GENERATION_RE = /^[0-9a-f]{32}$/;
const MODEL_RE = /^[A-Za-z0-9][A-Za-z0-9._:/+\-]{0,199}$/;
const EXACT_KEYS = [
  "schema_version",
  "tunnel_mode",
  "model",
  "public_url",
  "connected_at",
  "expires_at",
  "health_schema_version",
  "route_generation",
  "consecutive_health_checks",
].sort();
const ROUTE_KEY = "route:current";
const SEEN_KEY = "route:seen-generations";

function enabled(value: string | undefined): boolean {
  return ["1", "true", "yes", "on"].includes((value ?? "").trim().toLowerCase());
}

export function freeRelayEnabled(env: FreeRelayEnv): boolean {
  return enabled(env.FREE_RELAY_ENABLED);
}

function maxTtlSeconds(env: FreeRelayEnv): number {
  const configured = Number(env.FREE_RELAY_MAX_TTL_SECONDS ?? "300");
  return Math.max(60, Math.min(600, Number.isFinite(configured) ? configured : 300));
}

function expectedModel(env: FreeRelayEnv): string | null {
  const configured = (env.LOCAL_LLM_MODEL ?? "").trim();
  if (!configured || configured.toLowerCase() === "auto") return null;
  return configured;
}

function routeUrl(value: string): URL | null {
  let url: URL;
  try {
    url = new URL(value);
  } catch {
    return null;
  }
  const hostname = url.hostname.toLowerCase();
  if (
    url.protocol !== "https:" || url.username || url.password ||
    (url.port && url.port !== "443") || url.pathname !== "/" ||
    url.search || url.hash ||
    !/^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.trycloudflare\.com$/.test(hostname)
  ) return null;
  return new URL(url.origin + "/");
}

function exactKeys(value: Record<string, unknown>): boolean {
  const keys = Object.keys(value).sort();
  return keys.length === EXACT_KEYS.length && keys.every((key, index) => key === EXACT_KEYS[index]);
}

export function parseFreeRelayRoute(
  raw: string,
  env: FreeRelayEnv,
  nowMs = Date.now(),
): FreeRelayRouteRecord {
  let value: unknown;
  try {
    value = JSON.parse(raw);
  } catch {
    throw new Error("FREE_RELAY_ROUTE_JSON_INVALID");
  }
  if (!value || typeof value !== "object" || Array.isArray(value) || !exactKeys(value as Record<string, unknown>)) {
    throw new Error("FREE_RELAY_ROUTE_KEYS_INVALID");
  }
  const route = value as Record<string, unknown>;
  const connected = typeof route.connected_at === "string" ? Date.parse(route.connected_at) : Number.NaN;
  const expires = typeof route.expires_at === "string" ? Date.parse(route.expires_at) : Number.NaN;
  const url = typeof route.public_url === "string" ? routeUrl(route.public_url) : null;
  if (
    route.schema_version !== 1 || route.tunnel_mode !== "quick_free_relay" ||
    route.health_schema_version !== 2 || route.consecutive_health_checks !== 3 ||
    typeof route.model !== "string" || !MODEL_RE.test(route.model) || (expectedModel(env) !== null && route.model !== expectedModel(env)) ||
    typeof route.route_generation !== "string" || !GENERATION_RE.test(route.route_generation) ||
    !url || !Number.isFinite(connected) || !Number.isFinite(expires) ||
    connected > nowMs + 30_000 || expires <= nowMs + 15_000 ||
    expires > nowMs + maxTtlSeconds(env) * 1000 || expires <= connected
  ) {
    throw new Error("FREE_RELAY_ROUTE_INVALID");
  }
  return {
    schema_version: 1,
    tunnel_mode: "quick_free_relay",
    model: route.model,
    public_url: url.origin,
    connected_at: new Date(connected).toISOString(),
    expires_at: new Date(expires).toISOString(),
    health_schema_version: 2,
    route_generation: route.route_generation,
    consecutive_health_checks: 3,
  };
}

function validHealth(value: unknown, model: string): boolean {
  if (!value || typeof value !== "object" || Array.isArray(value)) return false;
  const health = value as Record<string, unknown>;
  return health.ok === true && health.service === "v213-local-llm-gateway" &&
    health.health_schema_version === 2 && health.llama_reachable === true &&
    health.selected_model_available === true && health.selected_model === model;
}

export async function verifyFreeRelayPublicHealth(route: FreeRelayRouteRecord): Promise<void> {
  for (let attempt = 0; attempt < 3; attempt += 1) {
    let response: Response;
    try {
      response = await fetch(`${route.public_url}/health`, {
        method: "GET",
        headers: { "cache-control": "no-store", pragma: "no-cache" },
        // Cloudflare's production Workers runtime supports "follow" and
        // "manual", but intentionally rejects redirect: "error".  Keep the
        // request fail-closed by observing redirects and rejecting every
        // non-2xx response below instead of following it.
        redirect: "manual",
        signal: AbortSignal.timeout(8_000),
      });
    } catch {
      throw new Error("FREE_RELAY_PUBLIC_HEALTH_FAILED");
    }
    if (!response.ok || !validHealth(await response.json().catch(() => null), route.model)) {
      throw new Error("FREE_RELAY_PUBLIC_HEALTH_MISMATCH");
    }
  }
}

function compareIso(left: string, right: string): number {
  return Date.parse(left) - Date.parse(right);
}

export function applyFreeRelayUpdate(
  current: StoredRoute | null,
  candidate: FreeRelayRouteRecord,
  seen: string[],
  nowMs = Date.now(),
): { route: StoredRoute; seen: string[]; action: "replace" | "heartbeat" } {
  if (Date.parse(candidate.expires_at) <= nowMs) throw new Error("FREE_RELAY_ROUTE_EXPIRED");
  if (!current) {
    if (seen.includes(candidate.route_generation)) throw new Error("FREE_RELAY_ROUTE_REPLAY");
    return {
      route: { ...candidate, accepted_at: new Date(nowMs).toISOString() },
      seen: [...seen, candidate.route_generation].slice(-64),
      action: "replace",
    };
  }
  if (candidate.route_generation === current.route_generation) {
    if (
      candidate.model !== current.model || candidate.public_url !== current.public_url ||
      candidate.connected_at !== current.connected_at ||
      compareIso(candidate.expires_at, current.expires_at) <= 0
    ) throw new Error("FREE_RELAY_ROUTE_REPLAY");
    return {
      route: { ...candidate, accepted_at: new Date(nowMs).toISOString() },
      seen,
      action: "heartbeat",
    };
  }
  if (seen.includes(candidate.route_generation)) throw new Error("FREE_RELAY_ROUTE_REPLAY");
  if (compareIso(candidate.connected_at, current.connected_at) <= 0) {
    throw new Error("FREE_RELAY_ROUTE_STALE_GENERATION");
  }
  return {
    route: { ...candidate, accepted_at: new Date(nowMs).toISOString() },
    seen: [...seen, candidate.route_generation].slice(-64),
    action: "replace",
  };
}

export class V213FreeRelayRoute {
  constructor(private readonly state: DurableObjectState) {}

  async fetch(request: Request): Promise<Response> {
    const url = new URL(request.url);
    if (request.method === "GET" && url.pathname === "/current") {
      const route = await this.state.storage.get<StoredRoute>(ROUTE_KEY);
      if (!route || Date.parse(route.expires_at) <= Date.now()) {
        return new Response(JSON.stringify({ ok: false, code: "FREE_RELAY_UNAVAILABLE" }), { status: 404 });
      }
      return new Response(JSON.stringify(route), { headers: { "content-type": "application/json", "cache-control": "no-store" } });
    }
    if (request.method !== "POST" || url.pathname !== "/update") return new Response("Not found", { status: 404 });
    const candidate = await request.json<FreeRelayRouteRecord>();
    try {
      const result = await this.state.storage.transaction(async (txn) => {
        const current = (await txn.get<StoredRoute>(ROUTE_KEY)) ?? null;
        const seen = (await txn.get<string[]>(SEEN_KEY)) ?? [];
        const applied = applyFreeRelayUpdate(current, candidate, seen);
        await txn.put(ROUTE_KEY, applied.route);
        await txn.put(SEEN_KEY, applied.seen);
        return applied;
      });
      return new Response(JSON.stringify({ ok: true, action: result.action, route_generation: result.route.route_generation, expires_at: result.route.expires_at }), {
        headers: { "content-type": "application/json", "cache-control": "no-store" },
      });
    } catch (error) {
      const code = error instanceof Error ? error.message : "FREE_RELAY_UPDATE_FAILED";
      return new Response(JSON.stringify({ ok: false, code }), { status: 409, headers: { "content-type": "application/json", "cache-control": "no-store" } });
    }
  }
}

function routeStub(env: FreeRelayEnv): DurableObjectStub | null {
  if (!freeRelayEnabled(env) || !env.V213_FREE_RELAY_ROUTE) return null;
  return env.V213_FREE_RELAY_ROUTE.get(env.V213_FREE_RELAY_ROUTE.idFromName("current-local-route"));
}

export async function updateFreeRelayRoute(body: string, env: FreeRelayEnv): Promise<Record<string, unknown>> {
  const stub = routeStub(env);
  if (!stub) throw new Error("FREE_RELAY_NOT_CONFIGURED");
  const route = parseFreeRelayRoute(body, env);
  await verifyFreeRelayPublicHealth(route);
  const response = await stub.fetch("https://free-relay.internal/update", { method: "POST", body: JSON.stringify(route) });
  const result = await response.json<Record<string, unknown>>().catch(() => ({ ok: false, code: "FREE_RELAY_UPDATE_RESPONSE_INVALID" }));
  if (!response.ok || result.ok !== true) throw new Error(String(result.code ?? "FREE_RELAY_UPDATE_REJECTED"));
  return result;
}

export async function currentFreeRelayRoute(env: FreeRelayEnv): Promise<FreeRelayRouteRecord | null> {
  const stub = routeStub(env);
  if (!stub) return null;
  const response = await stub.fetch("https://free-relay.internal/current", { method: "GET" });
  if (!response.ok) return null;
  const route = await response.json<StoredRoute>().catch(() => null);
  const expected = expectedModel(env);
  if (!route || Date.parse(route.expires_at) <= Date.now() || (expected !== null && route.model !== expected) || !routeUrl(route.public_url)) return null;
  return route;
}

function toHex(value: ArrayBuffer): string {
  return Array.from(new Uint8Array(value), (byte) => byte.toString(16).padStart(2, "0")).join("");
}

export interface FreeRelayRuntimeOverrides {
  LOCAL_LLM_BASE_URL: string;
  LOCAL_LLM_ALLOWED_HOSTS: string;
  LOCAL_LLM_MODEL: string;
  LOCAL_LLM_SHARED_SECRET: string;
  LOCAL_LLM_API_KEY: string;
}

export async function freeRelayRuntimeOverrides(env: FreeRelayEnv): Promise<FreeRelayRuntimeOverrides | null> {
  const route = await currentFreeRelayRoute(env);
  if (!route) return null;
  const gatewayMaterial = await freeRelayGatewaySecret(env, route.route_generation);
  if (!gatewayMaterial) return null;
  return {
    LOCAL_LLM_BASE_URL: route.public_url,
    LOCAL_LLM_ALLOWED_HOSTS: new URL(route.public_url).hostname,
    LOCAL_LLM_MODEL: route.model,
    LOCAL_LLM_SHARED_SECRET: gatewayMaterial,
    LOCAL_LLM_API_KEY: "",
  };
}

export async function freeRelayGatewaySecret(env: FreeRelayEnv, generation: string): Promise<string | null> {
  const material = (env.V21_SYNC_HMAC_SECRET ?? "").trim();
  if (material.length < 32 || !GENERATION_RE.test(generation)) return null;
  const key = await crypto.subtle.importKey("raw", ENCODER.encode(material), { name: "HMAC", hash: "SHA-256" }, false, ["sign"]);
  return toHex(await crypto.subtle.sign("HMAC", key, ENCODER.encode(`v213-free-relay-gateway.${generation}`)));
}
