/** Free-only admission. Configuration is an operator-reviewed attestation, not
 * a billing API proof or permission to deploy/send. Never synthesize a review. */
export interface FreePushPolicy {
  schema_version: 1;
  channel_sha256: string;
  billing_month: string;
  billing_timezone: string;
  free_message_limit: number;
  reviewed_at: string;
  free_plan_verified: true;
  paid_expansion_disabled: true;
}
export interface PushSlot { date: string; slot: "morning" | "evening" }
export class LinePushGateError extends Error {}
export const PUSH_DEADLINE_MS = 10_000;
const HEX = /^[a-f0-9]{64}$/;
const UUID = /^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/;

function object(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : {};
}
/** These LINE/control contracts are flat. Reject duplicate (including escaped)
 * keys before a last-key-wins parse can turn contradictory evidence green. */
export function parseFlatPushObject(text: string): Record<string, unknown> {
  const parsed: unknown = JSON.parse(text);
  if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) throw new Error("FLAT_OBJECT_REQUIRED");
  const value = parsed as Record<string, unknown>;
  if (Object.values(value).some(item => item !== null && typeof item === "object")) throw new Error("FLAT_OBJECT_REQUIRED");
  const seen = new Set<string>();
  for (const token of text.matchAll(/"(?:\\.|[^"\\])*"/g)) {
    if (!/^\s*:/.test(text.slice(token.index! + token[0].length))) continue;
    const key = JSON.parse(token[0]) as string;
    if (seen.has(key)) throw new Error("DUPLICATE_KEY");
    seen.add(key);
  }
  return value;
}
function validDay(value: unknown): value is string {
  if (typeof value !== "string" || !/^\d{4}-\d{2}-\d{2}$/.test(value)) return false;
  const stamp = Date.parse(`${value}T00:00:00.000Z`);
  return Number.isFinite(stamp) && new Date(stamp).toISOString().slice(0, 10) === value;
}
function keys(value: Record<string, unknown>, names: string[]): boolean {
  return Object.keys(value).length === names.length && names.every(name => Object.hasOwn(value, name));
}
function integer(value: unknown, max = Number.MAX_SAFE_INTEGER): value is number {
  return typeof value === "number" && Number.isSafeInteger(value) && value >= 0 && value <= max;
}
export function localDate(now: number, timeZone = "Asia/Taipei"): string {
  const parts = new Intl.DateTimeFormat("en-US", { timeZone, year: "numeric", month: "2-digit", day: "2-digit" }).formatToParts(new Date(now));
  return ["year", "month", "day"].map(type => parts.find(part => part.type === type)!.value).join("-");
}
export function parseFreePushPolicy(raw: unknown, now = Date.now()): FreePushPolicy {
  if (typeof raw !== "string" || !raw || raw.length > 4096) throw new LinePushGateError("LINE_FREE_PLAN_REVIEW_REQUIRED");
  try {
    const v = parseFlatPushObject(raw);
    if (!keys(v, ["schema_version", "channel_sha256", "billing_month", "billing_timezone", "free_message_limit", "reviewed_at", "free_plan_verified", "paid_expansion_disabled"]) ||
        v.schema_version !== 1 || v.free_plan_verified !== true || v.paid_expansion_disabled !== true ||
        typeof v.channel_sha256 !== "string" || !HEX.test(v.channel_sha256) ||
        typeof v.billing_month !== "string" || !/^\d{4}-\d{2}$/.test(v.billing_month) ||
        typeof v.billing_timezone !== "string" || v.billing_timezone.length > 80 ||
        !integer(v.free_message_limit, 1_000_000) || v.free_message_limit < 1 ||
        typeof v.reviewed_at !== "string") throw new Error();
    const reviewed = Date.parse(v.reviewed_at);
    if (!Number.isFinite(reviewed) || new Date(reviewed).toISOString() !== v.reviewed_at || reviewed > now || now - reviewed > 31 * 86400_000 ||
        localDate(reviewed, v.billing_timezone).slice(0, 7) !== v.billing_month || localDate(now, v.billing_timezone).slice(0, 7) !== v.billing_month) throw new Error();
    return v as unknown as FreePushPolicy;
  } catch { throw new LinePushGateError("LINE_FREE_PLAN_REVIEW_INVALID_OR_EXPIRED"); }
}
export async function pushDigest(text: string): Promise<string> {
  const bytes = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(text));
  return Array.from(new Uint8Array(bytes), byte => byte.toString(16).padStart(2, "0")).join("");
}
export function validateQuota(quota: unknown, consumption: unknown, policy: FreePushPolicy): number {
  const q = object(quota); const c = object(consumption);
  // A target limit is not proof of a free plan. It must exactly match the
  // separately reviewed free allowance; none/unlimited/expanded quotas fail.
  if (!keys(q, ["type", "value"]) || q.type !== "limited" || !integer(q.value) || q.value !== policy.free_message_limit ||
      !keys(c, ["totalUsage"]) || !integer(c.totalUsage)) throw new LinePushGateError("LINE_FREE_QUOTA_UNVERIFIED");
  if (c.totalUsage >= q.value) throw new LinePushGateError("LINE_FREE_QUOTA_EXHAUSTED");
  return c.totalUsage;
}

function response(value: unknown, status = 200): Response {
  return Response.json(value, { status, headers: { "cache-control": "no-store" } });
}

/** Called ONLY through the existing R75 Durable Object namespace. No LINE IDs,
 * payloads, credentials or response bodies are stored. All counters and the
 * immutable attempt are reserved in ONE storage transaction, before POST.
 * No refunds, lease expiry, automatic retry or claim deletion is supported. */
export async function reserveFreePush(state: DurableObjectState, body: Record<string, unknown>): Promise<Response> {
  try {
    if (!keys(body, ["action", "policy", "usage", "operation_sha256", "body_sha256", "day"]) || body.action !== "reserve_push" ||
        typeof body.operation_sha256 !== "string" || !HEX.test(body.operation_sha256) ||
        typeof body.body_sha256 !== "string" || !HEX.test(body.body_sha256) ||
        body.day !== localDate(Date.now()) || !integer(body.usage)) throw new LinePushGateError("LINE_PUSH_RESERVATION_INVALID");
    const policy = parseFreePushPolicy(body.policy);
    const usage = body.usage; const operation = body.operation_sha256; const digest = body.body_sha256; const day = String(body.day);
    return await state.storage.transaction(async txn => {
      const ledger = await txn.get<Record<string, unknown>>("push:ledger");
      if (ledger === undefined && (await txn.list({ prefix: "push:", limit: 1 })).size) throw new LinePushGateError("LINE_PUSH_LEDGER_INVALID");
      if (ledger !== undefined) {
        if (!keys(object(ledger), ["schema_version", "channel_sha256", "billing_timezone", "month", "limit", "usage_high_water", "reserved_month", "day", "reserved_day"]) ||
            ledger.schema_version !== 1 || typeof ledger.month !== "string" || !validDay(`${ledger.month}-01`) || ledger.month > policy.billing_month ||
            !validDay(ledger.day) || ledger.day > day ||
            !integer(ledger.limit) || !integer(ledger.usage_high_water) || !integer(ledger.reserved_month) || !integer(ledger.reserved_day, 2)) throw new LinePushGateError("LINE_PUSH_LEDGER_INVALID");
        if (ledger.channel_sha256 !== policy.channel_sha256 || ledger.billing_timezone !== policy.billing_timezone ||
            (ledger.month === policy.billing_month && ledger.limit !== policy.free_message_limit)) throw new LinePushGateError("LINE_PUSH_LEDGER_IDENTITY_INVALID");
      }
      const attemptKey = `push:attempt:${operation}`;
      const prior = await txn.get<Record<string, unknown>>(attemptKey);
      if (prior !== undefined) {
        if (!keys(object(prior), ["schema_version", "body_sha256", "retry_key", "reserved_at"]) || prior.schema_version !== 1 ||
            typeof prior.body_sha256 !== "string" || !HEX.test(prior.body_sha256) || typeof prior.retry_key !== "string" || !UUID.test(prior.retry_key) ||
            typeof prior.reserved_at !== "string" || !Number.isFinite(Date.parse(prior.reserved_at)) || new Date(prior.reserved_at).toISOString() !== prior.reserved_at) throw new LinePushGateError("LINE_PUSH_LEDGER_INVALID");
        throw new LinePushGateError(prior.body_sha256 === digest ? "LINE_PUSH_ALREADY_ATTEMPTED" : "LINE_PUSH_PAYLOAD_CONFLICT");
      }
      const sameMonth = ledger?.month === policy.billing_month;
      const reserved = sameMonth ? Number(ledger!.reserved_month) : 0;
      const used = Math.max(sameMonth ? Number(ledger!.usage_high_water) : 0, usage);
      const today = ledger?.day === day ? Number(ledger.reserved_day) : 0;
      // Conservatively double-count our attempts when already visible in the API;
      // the API total is not a transactionally current account-wide counter.
      if (used + reserved + 1 > policy.free_message_limit) throw new LinePushGateError("LINE_FREE_QUOTA_EXHAUSTED");
      if (today >= 2) throw new LinePushGateError("LINE_PUSH_DAILY_LIMIT");
      parseFreePushPolicy(body.policy);
      if (day !== localDate(Date.now())) throw new LinePushGateError("LINE_PUSH_SLOT_INVALID");
      const retryKey = crypto.randomUUID();
      await txn.put({
        "push:ledger": { schema_version: 1, channel_sha256: policy.channel_sha256, billing_timezone: policy.billing_timezone,
          month: policy.billing_month, limit: policy.free_message_limit, usage_high_water: used, reserved_month: reserved + 1,
          day, reserved_day: today + 1 },
        [attemptKey]: { schema_version: 1, body_sha256: digest, retry_key: retryKey, reserved_at: new Date().toISOString() },
      });
      return response({ reserved: true, retry_key: retryKey, operation_sha256: operation, body_sha256: digest });
    });
  } catch (error) {
    return response({ error: error instanceof LinePushGateError ? error.message : "LINE_PUSH_BUDGET_UNAVAILABLE" }, 409);
  }
}

export async function reservePush(
  namespace: DurableObjectNamespace, policy: FreePushPolicy, usage: number, bodySha: string, slot: PushSlot | undefined, signal: AbortSignal,
): Promise<string> {
  const day = localDate(Date.now());
  if (slot && (slot.date !== day || (slot.slot !== "morning" && slot.slot !== "evening"))) throw new LinePushGateError("LINE_PUSH_SLOT_INVALID");
  const scope = slot ? `scheduled:${day}:${slot.slot}` : `manual:${bodySha}`;
  const operation = await pushDigest(scope);
  if (signal.aborted) throw new LinePushGateError("LINE_PUSH_DEADLINE_EXCEEDED");
  const result = await namespace.get(namespace.idFromName(`v213:free-push:${policy.channel_sha256}`)).fetch("https://dedupe.internal/action", {
    method: "POST", signal, headers: { "content-type": "application/json" },
    body: JSON.stringify({ action: "reserve_push", policy: JSON.stringify(policy), usage, operation_sha256: operation, body_sha256: bodySha, day }),
  });
  const value = object(await result.json());
  const errors = ["LINE_PUSH_ALREADY_ATTEMPTED", "LINE_PUSH_PAYLOAD_CONFLICT", "LINE_FREE_QUOTA_EXHAUSTED", "LINE_PUSH_DAILY_LIMIT", "LINE_PUSH_LEDGER_INVALID", "LINE_PUSH_LEDGER_IDENTITY_INVALID"];
  if (!result.ok) throw new LinePushGateError(typeof value.error === "string" && errors.includes(value.error) ? value.error : "LINE_PUSH_BUDGET_UNAVAILABLE");
  if (!keys(value, ["reserved", "retry_key", "operation_sha256", "body_sha256"]) || value.reserved !== true ||
      value.operation_sha256 !== operation || value.body_sha256 !== bodySha || typeof value.retry_key !== "string" || !UUID.test(value.retry_key)) throw new LinePushGateError("LINE_PUSH_RESERVATION_UNVERIFIED");
  return value.retry_key;
}
