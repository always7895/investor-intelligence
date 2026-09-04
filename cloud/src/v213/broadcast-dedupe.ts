type DedupeState = {
  schema_version: 1;
  status: "pending" | "sent";
  token: string;
  updated_at: string;
  expires_at: number;
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

/** One Durable Object instance is selected by date + slot + run_id. */
export class V213BroadcastDedupe {
  constructor(private readonly state: DurableObjectState) {}

  async fetch(request: Request): Promise<Response> {
    if (request.method !== "POST") return json({ error: "METHOD_NOT_ALLOWED" }, 405);
    let body: Record<string, unknown>;
    try { body = object(await request.json()); }
    catch { return json({ error: "JSON_INVALID" }, 400); }
    const action = String(body.action ?? "");
    const token = String(body.token ?? "");
    const now = Date.now();
    const current = await this.state.storage.get<DedupeState>("state");

    if (action === "claim") {
      if (!token || token.length > 128) return json({ error: "TOKEN_INVALID" }, 400);
      if (current && current.expires_at > now && current.status === "sent") {
        return json({ claimed: false, status: "duplicate" });
      }
      if (current && current.expires_at > now && current.status === "pending") {
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
        updated_at: new Date(now).toISOString(),
        expires_at: now + 72 * 60 * 60_000,
      };
      await this.state.storage.put("state", value);
      return json({ completed: true, status: "sent" });
    }

    if (action === "release") {
      if (current && current.status === "pending" && current.token === token) {
        await this.state.storage.delete("state");
      }
      return json({ released: true });
    }

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
 * Run the LINE push under an atomic claim.  A failed push releases the claim so
 * a later retry remains possible; a successful push is retained for 72 hours.
 */
export async function runV213BroadcastOnce<T>(
  namespace: DurableObjectNamespace,
  key: string,
  send: () => Promise<T>,
): Promise<{ status: "sent" | "duplicate" | "in_progress"; value?: T }> {
  const token = crypto.randomUUID();
  const claim = await call(namespace, key, "claim", token);
  if (claim.claimed !== true) {
    const status = String(claim.status ?? "duplicate");
    return { status: status === "in_progress" ? "in_progress" : "duplicate" };
  }
  try {
    const value = await send();
    await call(namespace, key, "complete", token);
    return { status: "sent", value };
  } catch (error) {
    try { await call(namespace, key, "release", token); }
    catch { /* preserve the original send error */ }
    throw error;
  }
}
