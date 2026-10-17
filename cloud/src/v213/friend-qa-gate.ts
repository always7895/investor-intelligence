/**
 * Friend admission gate for the LINE all-friends mode (V213_LINE_ACCESS_MODE=all_friends).
 *
 * One named Durable Object instance holds every counter that must be atomic and must not cost a KV write:
 * webhook-event dedupe, per-friend public-read caps, the local-model lane (global in-flight cap, per-friend
 * 1 in-flight + 1 waiting, per-minute and per-day caps, a bounded in-request wait) and the daily cap on
 * slow-job KV writes. It uses the same storage API style as V213BroadcastDedupe (get/put/delete/list/transaction).
 *
 * Stored rows hold only a further hash of the HMAC tenant id, integer counters, expiry times, lease records and
 * hashes of webhook event ids. Never message text, replyTokens, raw LINE ids or the owner id.
 */
import policy from "../../../config/v213-compact-qa-v1.json";
import { hashOpaqueId } from "../security";

export interface FriendQaGateEnv {
  V213_FRIEND_QA_GATE?: DurableObjectNamespace;
  /** Friend model calls in flight at once, 1..4. Coupled to the gateway's II_GATEWAY_MAX_CONCURRENT_GENERATIONS. */
  V213_FRIEND_QA_GLOBAL_INFLIGHT?: string;
  /** Friends allowed to wait for the model lane at once, 0..8. */
  V213_FRIEND_QA_QUEUE_MAX?: string;
  /** In-request wait for the model lane in ms, clamped by MAX_ACQUIRE_WAIT_MS. */
  V213_FRIEND_QA_ACQUIRE_WAIT_MS?: string;
  /** Friend slow-job KV writes per Taipei day (each parked job costs two). */
  V213_FRIEND_JOB_WRITES_PER_DAY?: string;
}

export const FRIEND_PUBLIC_PER_MINUTE = 20;
export const FRIEND_PUBLIC_PER_DAY = 400;
export const FRIEND_MODEL_PER_MINUTE = 3;
export const FRIEND_MODEL_PER_DAY = 30;
export const FRIEND_KV_WRITE_ACTIONS_PER_DAY = 5;
export const FRIEND_JOB_WRITES_PER_JOB = 2;

const MINUTE_MS = 60_000;
const DAY_MS = 86_400_000;
const TAIPEI_OFFSET_MS = 8 * 3_600_000;
const EVENT_TTL_MS = DAY_MS;
const GATE_NAME = "friend-qa-gate-v1";

/** The compact-QA policy bounds the whole model call: acquire wait + timeout_ms + margin <= absolute_budget_ms. */
export const COMPACT_TIMEOUT_MS: number = policy.timeout_ms;
export const COMPACT_ABSOLUTE_BUDGET_MS: number = policy.absolute_budget_ms;
export const ACQUIRE_MARGIN_MS = 2000;
export const MAX_ACQUIRE_WAIT_MS = COMPACT_ABSOLUTE_BUDGET_MS - COMPACT_TIMEOUT_MS - ACQUIRE_MARGIN_MS;
export const DEFAULT_ACQUIRE_WAIT_MS = 5000;
/** A lease outlives the absolute budget, so a crashed Worker cannot hold a slot for long. */
export const DEFAULT_LEASE_MS = COMPACT_ABSOLUTE_BUDGET_MS + 12_000;
export const DEFAULT_JOB_WRITES_PER_DAY = 150;

export interface FriendQaLimits {
  globalInFlight: number;
  queueMax: number;
  acquireWaitMs: number;
  leaseMs: number;
  jobWritesPerDay: number;
}

function intIn(value: unknown, fallback: number, min: number, max: number): number {
  const parsed = typeof value === "string" || typeof value === "number" ? Number(value) : Number.NaN;
  if (!Number.isFinite(parsed)) return fallback;
  return Math.min(max, Math.max(min, Math.trunc(parsed)));
}

/** Pure; also used by the Durable Object to re-clamp whatever a caller sends. */
export function clampFriendQaLimits(raw: Partial<Record<keyof FriendQaLimits, unknown>>): FriendQaLimits {
  return {
    globalInFlight: intIn(raw.globalInFlight, 1, 1, 4),
    queueMax: intIn(raw.queueMax, 2, 0, 8),
    acquireWaitMs: intIn(raw.acquireWaitMs, DEFAULT_ACQUIRE_WAIT_MS, 0, MAX_ACQUIRE_WAIT_MS),
    leaseMs: intIn(raw.leaseMs, DEFAULT_LEASE_MS, COMPACT_ABSOLUTE_BUDGET_MS + 2000, 120_000),
    jobWritesPerDay: intIn(raw.jobWritesPerDay, DEFAULT_JOB_WRITES_PER_DAY, 0, 1000),
  };
}

export function friendQaLimits(env: FriendQaGateEnv): FriendQaLimits {
  return clampFriendQaLimits({
    globalInFlight: env.V213_FRIEND_QA_GLOBAL_INFLIGHT,
    queueMax: env.V213_FRIEND_QA_QUEUE_MAX,
    acquireWaitMs: env.V213_FRIEND_QA_ACQUIRE_WAIT_MS,
    jobWritesPerDay: env.V213_FRIEND_JOB_WRITES_PER_DAY,
  });
}

/** Day bucket on a fixed +08:00 boundary (Taiwan has no DST), so "try again tomorrow" is literally true. */
export function taipeiDayBucket(ms: number): number {
  return Math.floor((ms + TAIPEI_OFFSET_MS) / DAY_MS);
}

function dayExpiry(day: number): number {
  return (day + 3) * DAY_MS - TAIPEI_OFFSET_MS;
}

export type FriendRequestKind = "follow" | "public" | "kv_write";
export type AdmitResult =
  | { ok: true }
  | { ok: false; reason: "duplicate" | "rate" | "rate_kv" | "unavailable" };
export type AcquireBusyReason =
  | "tenant_rate_minute"
  | "tenant_rate_day"
  | "tenant_busy"
  | "queue_full"
  | "wait_timeout"
  | "unavailable";
export type AcquireResult = { status: "granted" } | { status: "busy"; reason: AcquireBusyReason };

// ---------------------------------------------------------------- client (Worker side)

function gateStub(env: FriendQaGateEnv): DurableObjectStub | null {
  const namespace = env.V213_FRIEND_QA_GATE;
  if (!namespace || typeof namespace.idFromName !== "function") return null;
  return namespace.get(namespace.idFromName(GATE_NAME));
}

export function friendGateConfigured(env: FriendQaGateEnv): boolean {
  return Boolean(env.V213_FRIEND_QA_GATE) && typeof env.V213_FRIEND_QA_GATE?.idFromName === "function";
}

/** A further hash of the HMAC tenant id: the Durable Object never sees the id used for KV keys. */
export async function gateTenantKey(tenantId: string): Promise<string> {
  return hashOpaqueId(`friend-qa-gate:v1:${tenantId}`);
}

/** A bound Durable Object that does not answer is as unavailable as an unbound one. */
export const GATE_CALL_TIMEOUT_MS = 2000;
/** Slack above the bounded acquire wait for the Durable Object round trip. */
export const GATE_ACQUIRE_SLACK_MS = 1500;

async function callGateOnce(env: FriendQaGateEnv, body: Record<string, unknown>): Promise<Record<string, unknown> | null> {
  try {
    const stub = gateStub(env);
    if (!stub) return null;
    const response = await stub.fetch("https://friend-qa-gate.internal/action", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(body),
    });
    if (!response.ok) return null;
    const value = (await response.json()) as unknown;
    return value && typeof value === "object" && !Array.isArray(value) ? (value as Record<string, unknown>) : null;
  } catch {
    return null;
  }
}

async function callGate(
  env: FriendQaGateEnv,
  body: Record<string, unknown>,
  timeoutMs: number = GATE_CALL_TIMEOUT_MS,
): Promise<Record<string, unknown> | null> {
  let timer: ReturnType<typeof setTimeout> | undefined;
  const timeout = new Promise<null>((resolve) => {
    timer = setTimeout(() => resolve(null), timeoutMs);
  });
  try {
    return await Promise.race([callGateOnce(env, body), timeout]);
  } finally {
    if (timer !== undefined) clearTimeout(timer);
  }
}

/** Unbound, throwing or malformed => unavailable. The caller answers with the honest busy text; never fails open. */
export async function gateAdmit(
  env: FriendQaGateEnv,
  tenantId: string,
  eventId: string | undefined,
  kind: FriendRequestKind,
): Promise<AdmitResult> {
  const body: Record<string, unknown> = { action: "admit", th: await gateTenantKey(tenantId), kind };
  if (eventId) body.ev = await hashOpaqueId(`friend-event:v1:${eventId}`);
  const result = await callGate(env, body);
  if (result?.ok === true) return { ok: true };
  if (result?.ok === false && ["duplicate", "rate", "rate_kv"].includes(String(result.reason))) {
    return { ok: false, reason: result.reason as "duplicate" | "rate" | "rate_kv" };
  }
  return { ok: false, reason: "unavailable" };
}

export function newAttemptId(): string {
  return crypto.randomUUID().replace(/-/g, "");
}

export async function gateAcquire(
  env: FriendQaGateEnv,
  tenantId: string,
  attemptId: string,
  owner: boolean,
): Promise<AcquireResult> {
  const limits = friendQaLimits(env);
  // A slot granted to a call that timed out is not leaked: the lease expires by itself (DEFAULT_LEASE_MS).
  const result = await callGate(
    env,
    { action: "acquire", th: await gateTenantKey(tenantId), att: attemptId, owner, limits },
    owner ? GATE_CALL_TIMEOUT_MS : limits.acquireWaitMs + GATE_ACQUIRE_SLACK_MS,
  );
  if (result?.status === "granted") return { status: "granted" };
  const reasons = ["tenant_rate_minute", "tenant_rate_day", "tenant_busy", "queue_full", "wait_timeout"];
  if (result?.status === "busy" && reasons.includes(String(result.reason))) {
    return { status: "busy", reason: result.reason as AcquireBusyReason };
  }
  return { status: "busy", reason: "unavailable" };
}

/** Idempotent; never throws. */
export async function gateRelease(env: FriendQaGateEnv, attemptId: string): Promise<void> {
  await callGate(env, { action: "release", att: attemptId, limits: friendQaLimits(env) });
}

/** Reserve the KV writes of one parked slow job. false => no parked job (answer busy). */
export async function gateReserveJobWrites(env: FriendQaGateEnv): Promise<boolean> {
  const result = await callGate(env, {
    action: "job_writes",
    n: FRIEND_JOB_WRITES_PER_JOB,
    cap: friendQaLimits(env).jobWritesPerDay,
  });
  return result?.ok === true;
}

// ---------------------------------------------------------------- Durable Object

type Counter = { n: number; exp: number };
type Lease = { t: string; o: boolean; exp: number };
type Lane = { leases: Record<string, Lease> };
type Waiter = {
  t: string;
  att: string;
  limits: FriendQaLimits;
  done: boolean;
  timer?: ReturnType<typeof setTimeout>;
  resolve: (result: AcquireResult) => void;
};

const OPAQUE_ID = /^[A-Za-z0-9_-]{8,64}$/;

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
  return value && typeof value === "object" && !Array.isArray(value) ? (value as Record<string, unknown>) : {};
}

function token(value: unknown): string | null {
  return typeof value === "string" && OPAQUE_ID.test(value) ? value : null;
}

export class V213FriendQaGate {
  private waiters: Waiter[] = [];
  private waking = false;
  private wakeAgain = false;
  private lastPrune = 0;

  constructor(private readonly state: DurableObjectState) {}

  async fetch(request: Request): Promise<Response> {
    if (request.method !== "POST") return json({ error: "METHOD_NOT_ALLOWED" }, 405);
    let body: Record<string, unknown>;
    try {
      body = object(await request.json());
    } catch {
      return json({ error: "JSON_INVALID" }, 400);
    }
    try {
      if (body.action === "admit") return await this.admit(body);
      if (body.action === "acquire") return await this.acquire(body);
      if (body.action === "release") return await this.release(body);
      if (body.action === "job_writes") return await this.jobWrites(body);
    } catch {
      return json({ error: "FRIEND_GATE_FAILED" }, 500);
    }
    return json({ error: "ACTION_INVALID" }, 400);
  }

  private async admit(body: Record<string, unknown>): Promise<Response> {
    const th = token(body.th);
    const ev = body.ev === undefined ? undefined : token(body.ev);
    const kind = body.kind;
    if (!th || ev === null || !["follow", "public", "kv_write"].includes(String(kind))) {
      return json({ error: "REQUEST_INVALID" }, 400);
    }
    const now = Date.now();
    const minute = Math.floor(now / MINUTE_MS);
    const day = taipeiDayBucket(now);
    const result = await this.state.storage.transaction(async (txn) => {
      if (ev) {
        const seen = await txn.get<number>(`ev:${ev}`);
        if (typeof seen === "number" && seen > now) return { ok: false, reason: "duplicate" };
        await txn.put(`ev:${ev}`, now + EVENT_TTL_MS);
      }
      if (kind === "follow") return { ok: true };
      const perMinute = await txn.get<Counter>(`rm:${th}:${minute}`);
      const perDay = await txn.get<Counter>(`rd:${th}:${day}`);
      if ((perMinute?.n ?? 0) >= FRIEND_PUBLIC_PER_MINUTE || (perDay?.n ?? 0) >= FRIEND_PUBLIC_PER_DAY) {
        return { ok: false, reason: "rate" };
      }
      if (kind === "kv_write") {
        const writes = await txn.get<Counter>(`kd:${th}:${day}`);
        if ((writes?.n ?? 0) >= FRIEND_KV_WRITE_ACTIONS_PER_DAY) return { ok: false, reason: "rate_kv" };
        await txn.put(`kd:${th}:${day}`, { n: (writes?.n ?? 0) + 1, exp: dayExpiry(day) } satisfies Counter);
      }
      await txn.put(`rm:${th}:${minute}`, { n: (perMinute?.n ?? 0) + 1, exp: (minute + 3) * MINUTE_MS } satisfies Counter);
      await txn.put(`rd:${th}:${day}`, { n: (perDay?.n ?? 0) + 1, exp: dayExpiry(day) } satisfies Counter);
      return { ok: true };
    });
    await this.maybePrune(now);
    return json(result);
  }

  private async acquire(body: Record<string, unknown>): Promise<Response> {
    const th = token(body.th);
    const att = token(body.att);
    if (!th || !att || typeof body.owner !== "boolean") return json({ error: "REQUEST_INVALID" }, 400);
    const owner = body.owner;
    const limits = clampFriendQaLimits(object(body.limits));
    const now = Date.now();
    const minute = Math.floor(now / MINUTE_MS);
    const day = taipeiDayBucket(now);

    // The waiter exists before the transaction and is registered inside it (synchronously after the reads that
    // decide), so two requests can never both see an empty waiting room. A retried callback re-registers the same
    // attempt id, never a second place.
    let settle: (result: AcquireResult) => void = () => undefined;
    const outcome = new Promise<AcquireResult>((resolve) => {
      settle = resolve;
    });
    const waiter: Waiter = {
      t: th,
      att,
      limits,
      done: false,
      resolve: (value) => {
        if (waiter.done) return;
        waiter.done = true;
        if (waiter.timer !== undefined) clearTimeout(waiter.timer);
        settle(value);
      },
    };

    let decision: "granted" | "wait" | AcquireResult;
    try {
      decision = await this.state.storage.transaction(
        async (txn): Promise<"granted" | "wait" | AcquireResult> => {
          const lane = this.liveLane(await txn.get<Lane>("lane"), now);
          if (owner) {
            // The owner is never blocked by friend saturation. It still occupies (and so counts toward) the global cap.
            lane.leases[att] = { t: th, o: true, exp: now + limits.leaseMs };
            await txn.put("lane", lane);
            return "granted";
          }
          const perMinute = await txn.get<Counter>(`qm:${th}:${minute}`);
          const perDay = await txn.get<Counter>(`qd:${th}:${day}`);
          if ((perMinute?.n ?? 0) >= FRIEND_MODEL_PER_MINUTE) return { status: "busy", reason: "tenant_rate_minute" };
          if ((perDay?.n ?? 0) >= FRIEND_MODEL_PER_DAY) return { status: "busy", reason: "tenant_rate_day" };
          const others = this.waiters.filter((entry) => entry.att !== att);
          if (others.some((entry) => entry.t === th)) return { status: "busy", reason: "tenant_busy" };
          const leases = Object.values(lane.leases);
          const free = leases.length < limits.globalInFlight;
          const tenantLeased = leases.some((lease) => lease.t === th);
          let verdict: "granted" | "wait";
          if (free && !tenantLeased && others.length === 0) {
            lane.leases[att] = { t: th, o: false, exp: now + limits.leaseMs };
            verdict = "granted";
          } else {
            if (others.length >= limits.queueMax || limits.acquireWaitMs <= 0) {
              return { status: "busy", reason: "queue_full" };
            }
            this.waiters = [...others, waiter];
            verdict = "wait";
          }
          // Counters are charged only when the model slot is actually granted (here or in wake()), so a wait that
          // times out ("this question was not processed") never costs the friend one of the 3/min or 30/day.
          if (verdict === "granted") {
            await txn.put("lane", lane);
            await txn.put(`qm:${th}:${minute}`, { n: (perMinute?.n ?? 0) + 1, exp: (minute + 3) * MINUTE_MS } satisfies Counter);
            await txn.put(`qd:${th}:${day}`, { n: (perDay?.n ?? 0) + 1, exp: dayExpiry(day) } satisfies Counter);
          }
          return verdict;
        },
      );
    } catch (error) {
      this.dropWaiter(att);
      throw error;
    }
    if (decision !== "wait") this.dropWaiter(att);
    if (decision === "granted") {
      await this.maybePrune(now);
      return json({ status: "granted" });
    }
    if (decision !== "wait") return json(decision);

    // Bounded in-request wait. Never a durable parked queue: an eviction drops it and the caller sees busy.
    waiter.timer = setTimeout(() => {
      this.dropWaiter(att);
      waiter.resolve({ status: "busy", reason: "wait_timeout" });
    }, limits.acquireWaitMs);
    if (waiter.done) clearTimeout(waiter.timer);
    void this.wake();
    const result = await outcome;
    await this.maybePrune(now);
    return json(result);
  }

  private async release(body: Record<string, unknown>): Promise<Response> {
    const att = token(body.att);
    if (!att) return json({ error: "REQUEST_INVALID" }, 400);
    await this.releaseLease(att);
    await this.wake();
    return json({ released: true });
  }

  private async jobWrites(body: Record<string, unknown>): Promise<Response> {
    const n = Number(body.n);
    const cap = Number(body.cap);
    if (!Number.isInteger(n) || n < 1 || n > 4 || !Number.isInteger(cap) || cap < 0 || cap > 1000) {
      return json({ error: "REQUEST_INVALID" }, 400);
    }
    const day = taipeiDayBucket(Date.now());
    const ok = await this.state.storage.transaction(async (txn) => {
      const current = await txn.get<Counter>(`jw:${day}`);
      const used = current?.n ?? 0;
      if (used + n > cap) return false;
      await txn.put(`jw:${day}`, { n: used + n, exp: dayExpiry(day) } satisfies Counter);
      return true;
    });
    return json({ ok });
  }

  private dropWaiter(attemptId: string): void {
    this.waiters = this.waiters.filter((entry) => entry.att !== attemptId);
  }

  private liveLane(stored: Lane | undefined, now: number): Lane {
    const lane: Lane = { leases: {} };
    for (const [attempt, lease] of Object.entries(stored?.leases ?? {})) {
      if (lease.exp > now) lane.leases[attempt] = lease;
    }
    return lane;
  }

  /** Grant freed capacity to waiting friends in arrival order; skips a friend whose own lease is still held. */
  private async wake(): Promise<void> {
    if (this.waking) {
      this.wakeAgain = true;
      return;
    }
    this.waking = true;
    try {
      do {
        this.wakeAgain = false;
        for (;;) {
          if (this.waiters.length === 0) break;
          let candidate: Waiter | null = null;
          try {
            // The callback only chooses and writes the lease (idempotent by attempt id), so a retried transaction is safe.
            candidate = await this.state.storage.transaction(async (txn) => {
              const now = Date.now();
              const lane = this.liveLane(await txn.get<Lane>("lane"), now);
              const leases = Object.values(lane.leases);
              const chosen = this.waiters.find(
                (entry) =>
                  !entry.done &&
                  leases.length < entry.limits.globalInFlight &&
                  !leases.some((lease) => lease.t === entry.t),
              );
              if (!chosen) return null;
              lane.leases[chosen.att] = { t: chosen.t, o: false, exp: now + chosen.limits.leaseMs };
              await txn.put("lane", lane);
              const minute = Math.floor(now / MINUTE_MS);
              const day = taipeiDayBucket(now);
              const perMinute = await txn.get<Counter>(`qm:${chosen.t}:${minute}`);
              const perDay = await txn.get<Counter>(`qd:${chosen.t}:${day}`);
              await txn.put(`qm:${chosen.t}:${minute}`, { n: (perMinute?.n ?? 0) + 1, exp: (minute + 3) * MINUTE_MS } satisfies Counter);
              await txn.put(`qd:${chosen.t}:${day}`, { n: (perDay?.n ?? 0) + 1, exp: dayExpiry(day) } satisfies Counter);
              return chosen;
            });
          } catch {
            candidate = null;
          }
          if (!candidate) break;
          this.dropWaiter(candidate.att);
          if (candidate.done) {
            // It gave up while its lease was being written: hand the slot straight back.
            await this.releaseLease(candidate.att);
            continue;
          }
          candidate.resolve({ status: "granted" });
        }
      } while (this.wakeAgain);
    } finally {
      this.waking = false;
    }
  }

  private async releaseLease(attemptId: string): Promise<void> {
    const now = Date.now();
    await this.state.storage.transaction(async (txn) => {
      const lane = this.liveLane(await txn.get<Lane>("lane"), now);
      delete lane.leases[attemptId];
      await txn.put("lane", lane);
    });
  }

  private async maybePrune(now: number): Promise<void> {
    if (now - this.lastPrune < 5 * MINUTE_MS) return;
    this.lastPrune = now;
    try {
      for (const prefix of ["ev:", "rm:", "rd:", "qm:", "qd:", "kd:", "jw:"]) {
        const rows = await this.state.storage.list<unknown>({ prefix, limit: 1000 });
        for (const [key, value] of rows) {
          const expiry = typeof value === "number" ? value : Number(object(value).exp);
          if (Number.isFinite(expiry) && expiry <= now) await this.state.storage.delete(key);
        }
      }
    } catch {
      // Pruning is housekeeping; every read re-checks expiry.
    }
  }
}
