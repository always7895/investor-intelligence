import { reserveFreePush } from "../v21/line-push-policy";

type DedupeState = {
  schema_version: 1;
  status: "pending" | "sent";
  token: string;
  updated_at: string;
  expires_at: number;
  // Keep status=pending for old readers; uncertainty never authorizes replay.
  delivery_unknown?: boolean;
};

function json(value: unknown, status = 200): Response {
  return new Response(JSON.stringify(value), {
    status,
    headers: {
      "content-type": "application/json; charset=utf-8",
      "cache-control": "no-store",
      "x-content-type-options": "nosniff",
    },
  });
}

function object(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value)
    ? value as Record<string, unknown>
    : {};
}

function validState(value: unknown): value is DedupeState {
  const v = object(value);
  return Object.keys(v).every(key => ["schema_version", "status", "token", "updated_at", "expires_at", "delivery_unknown"].includes(key)) &&
    v.schema_version === 1 && (v.status === "pending" || v.status === "sent") &&
    typeof v.token === "string" && /^[A-Za-z0-9._:-]{1,128}$/.test(v.token) &&
    typeof v.updated_at === "string" && Number.isFinite(Date.parse(v.updated_at)) &&
    typeof v.expires_at === "number" && Number.isFinite(v.expires_at) && v.expires_at >= Date.parse(v.updated_at) &&
    (v.delivery_unknown === undefined || typeof v.delivery_unknown === "boolean");
}

/** One Durable Object instance is selected by date + slot + run_id. */
export class V213BroadcastDedupe {
  constructor(private readonly state: DurableObjectState) {}

  async fetch(request: Request): Promise<Response> {
    if (request.method !== "POST") return json({ error: "METHOD_NOT_ALLOWED" }, 405);
    let body: Record<string, unknown>;
    try { body = object(await request.json()); }
    catch { return json({ error: "JSON_INVALID" }, 400); }
    if (body.action === "reserve_push") return reserveFreePush(this.state, body);
    if (typeof body.action !== "string" || (body.action !== "status" && typeof body.token !== "string") ||
        Object.keys(body).some(key => key !== "action" && key !== "token")) return json({ error: "REQUEST_INVALID" }, 400);
    const action = body.action;
    const token = String(body.token ?? "");
    const now = Date.now();
    const current = await this.state.storage.get<unknown>("state");
    if (current !== undefined && !validState(current)) return json({ error: "DEDUPE_STATE_INVALID" }, 409);

    if (action === "claim") {
      if (typeof body.token !== "string" || !/^[A-Za-z0-9._:-]{1,128}$/.test(token)) return json({ error: "TOKEN_INVALID" }, 400);
      if (current?.status === "sent") return json({ claimed: false, status: "duplicate" });
      if (current?.status === "pending") {
        if (current.delivery_unknown || current.expires_at <= now) {
          if (!current.delivery_unknown) await this.state.storage.put("state", {
            ...current, delivery_unknown: true, updated_at: new Date(now).toISOString(), expires_at: now + 72 * 60 * 60_000,
          } satisfies DedupeState);
          return json({ claimed: false, status: "delivery_unknown" });
        }
        return json({ claimed: false, status: "in_progress" });
      }
      const value: DedupeState = {
        schema_version: 1,
        status: "pending",
        token,
        updated_at: new Date(now).toISOString(),
        expires_at: now + 10 * 60_000,
      };
      await this.state.storage.put("state", value);
      return json({ claimed: true, status: "pending", token });
    }

    if (action === "complete") {
      if (!current || current.status !== "pending" || current.token !== token) {
        return json({ error: "CLAIM_MISMATCH" }, 409);
      }
      const value: DedupeState = {
        ...current,
        status: "sent",
        delivery_unknown: false,
        updated_at: new Date(now).toISOString(),
        expires_at: now + 72 * 60 * 60_000,
      };
      await this.state.storage.put("state", value);
      return json({ completed: true, status: "sent" });
    }

    if (action === "uncertain") {
      if (!current || current.status !== "pending" || current.token !== token) return json({ error: "CLAIM_MISMATCH" }, 409);
      await this.state.storage.put("state", {
        ...current, delivery_unknown: true, updated_at: new Date(now).toISOString(), expires_at: now + 72 * 60 * 60_000,
      } satisfies DedupeState);
      return json({ marked: true, status: "delivery_unknown" });
    }

    // Legacy callers must not erase a possibly accepted LINE request.
    if (action === "release") return json({ error: "UNSAFE_RELEASE_NOT_SUPPORTED" }, 409);

    if (action === "status") {
      return json({ state: current ?? null });
    }
    return json({ error: "ACTION_INVALID" }, 400);
  }
}

async function call(
  namespace: DurableObjectNamespace,
  key: string,
  action: string,
  token: string,
): Promise<Record<string, unknown>> {
  const id = namespace.idFromName(key);
  const response = await namespace.get(id).fetch("https://dedupe.internal/action", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ action, token }),
  });
  const value = object(await response.json());
  if (!response.ok) throw new Error(String(value.error ?? "V213_BROADCAST_DEDUPE_FAILED"));
  return value;
}

/**
 * Run the LINE push under an atomic claim. Transport/ack failures may follow a
 * provider acceptance, so retain uncertainty and never automatically replay.
 * Lease expiry is not proof of non-delivery. No exactly-once receipt is claimed.
 */
export async function runV213BroadcastOnce<T>(
  namespace: DurableObjectNamespace,
  key: string,
  send: () => Promise<T>,
): Promise<{ status: "sent" | "duplicate" | "in_progress" | "delivery_unknown"; value?: T }> {
  const token = crypto.randomUUID();
  const claim = await call(namespace, key, "claim", token);
  if (claim.claimed !== true) {
    if (claim.claimed !== false || (claim.status !== "duplicate" && claim.status !== "in_progress" && claim.status !== "delivery_unknown")) throw new Error("V213_BROADCAST_DEDUPE_RESPONSE_INVALID");
    return { status: claim.status };
  }
  if (claim.token !== token || claim.status !== "pending") throw new Error("V213_BROADCAST_DEDUPE_RESPONSE_INVALID");
  try {
    const value = await send();
    const completed = await call(namespace, key, "complete", token);
    if (completed.completed !== true || completed.status !== "sent") throw new Error("V213_BROADCAST_DEDUPE_RESPONSE_INVALID");
    return { status: "sent", value };
  } catch (error) {
    try { await call(namespace, key, "uncertain", token); }
    catch { /* keep the original error; pending or sent state still fences replay */ }
    throw error;
  }
}
