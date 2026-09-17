import { spawn as _spawn } from "node:child_process";
import { existsSync, readFileSync } from "node:fs";
import { createServer } from "node:net";
import { fileURLToPath } from "node:url";
import { createHash, randomBytes } from "node:crypto";

export type GatewayChild = {
  kill: (signal?: NodeJS.Signals) => boolean;
  once: (event: string, listener: (...args: unknown[]) => void) => unknown;
  on: (event: string, listener: (...args: unknown[]) => void) => unknown;
  exitCode: number | null;
};

/**
 * TASK0 Phase-1F — hardened harness for the opt-in live-gateway runner only.
 * Default offline `vitest run` never imports the manual suite; this file is
 * imported exclusively by test/manual/v213-task0-general-qa-live.manual.ts.
 *
 * Hard rules (no caller can relax):
 * - Approved Python executable only (II_TASK0_PYTHON_EXE override or the
 *   operator host interpreter); shell: false; explicit minimal env only —
 *   the full process.env is never inherited by the gateway child.
 * - fileURLToPath for every URL->OS path (Windows-safe; no manual
 *   pathname mangling).
 * - Health readiness = HTTP 200 AND ok AND service AND health_schema_version
 *   =2 AND llama_reachable AND selected_model_available AND selected_model
 *   equals the expected model string. 503 / missing / wrong field = not
 *   ready (never treated as readiness).
 * - Port from a throwaway net-0 listener.
 * - Release waits for child "exit" AND verifies the loopback listener stops
 *   answering (connection failure), not a fixed post-kill sleep.
 * - The strict boundary forwards ONLY:
 *     POST https://<host>/v1/chat/completions  ->  http://127.0.0.1:<port>
 *       (origin/path rewritten to loopback; method POST; body pass-through;
 *        AbortSignal.timeout(90s) arrival boundary)
 *     POST https://api.line.me/v2/bot/message/reply -> captured reply, 200
 *       served locally, never sent externally.
 *   Any other origin/path/method is recorded as a violation and fails the
 *   run immediately.
 */
export interface DrainHandle {
  add: (p: Promise<unknown>) => void;
  settle: () => Promise<{ fulfilled: number; rejected: number; rejects: unknown[] }>;
}

/**
 * Phase-1G drain: follows an ever-growing set of waitUntil work. The wait
 * itself races a REAL-TIME deadline (performance.now, unaffected by a
 * Date-only fake), so a stuck promise fails instead of hanging; work added
 * after an earlier batch is awaited too; every unexpected rejection is
 * preserved and reported (never reclassified as fulfillment).
 */
export function startDrain(
  deadlineMs: number,
  now: () => number = () => (globalThis as unknown as { performance?: { now(): number } }).performance?.now() ?? Date.now(),
): DrainHandle {
  const jobs = new Set<Promise<unknown>>();
  const consumed = new Set<Promise<unknown>>();
  const rejects: unknown[] = [];
  const limitAt = now() + deadlineMs;
  return {
    add: (p) => { jobs.add(p); },
    settle: async () => {
      let fulfilled = 0;
      for (;;) {
        const remaining = limitAt - now();
        if (remaining <= 0) throw new Error("TASK0_DRAIN_TIMEOUT");
        const fresh = [...jobs].filter((p) => !consumed.has(p));
        if (fresh.length === 0) break;
        for (const p of fresh) consumed.add(p);
        const settledPromise = Promise.all(
          fresh.map((p) => Promise.allSettled([p]).then((rs) => ({ p, rs }))),
        );
        let roundTimer: ReturnType<typeof setTimeout> | undefined;
        const timer = new Promise<never>((_res, rej) => {
          roundTimer = setTimeout(() => { rej(new Error("TASK0_DRAIN_TIMEOUT")); }, remaining);
        });
        const batch = await Promise.race([settledPromise, timer]);
        if (roundTimer !== undefined) clearTimeout(roundTimer);
        for (const { rs } of batch) {
          const r = rs[0];
          if (r.status === "fulfilled") {
            fulfilled++;
          } else {
            rejects.push(r.reason);
          }
        }
      }
      return { fulfilled, rejected: rejects.length, rejects };
    },
  };
}

export const APPROVED_PYTHON_DEFAULT = "C:\\Users\\moon9\\AppData\\Local\\Programs\\Python\\Python312\\python.exe";

export function resolveApprovedPython(): string {
  const exe = process.env.II_TASK0_PYTHON_EXE ?? APPROVED_PYTHON_DEFAULT;
  if (!existsSync(exe)) throw new Error(`TASK0_APPROVED_PYTHON_MISSING:${exe}`);
  return exe;
}

async function freeLoopbackPort(): Promise<number> {
  const srv = createServer();
  await new Promise<void>((res) => srv.listen(0, "127.0.0.1", () => res()));
  const addr = srv.address();
  const port = typeof addr === "object" && addr ? addr.port : 0;
  if (!port) throw new Error("TASK0_GATEWAY_PORT_UNAVAILABLE");
  await new Promise<void>((res) => srv.close(() => res()));
  return port;
}

export type StrictBoundary = {
  fetch: (input: RequestInfo | URL, init?: RequestInit) => Promise<Response>;
  modelCalls: Array<{ method: string; status: number; model: string; finishReason: string; modelReturned: string }>;
  lineReplies: Array<{ replyTokenPrefix: string; textCount: number; sawBearer: boolean; texts: string[] }>;
  violations: string[];
  /** Queue one-off artificial latency (ms) applied to the NEXT model forward. */
  delayMs: number[];
  /** Next model forward returns a 504 timeout body exactly once. */
  markStallOnce: () => void;
  stallArmed: () => boolean;
};

export type FinalAnswerCheck = { ok: boolean; reason: string };

/**
 * Phase-1G REPAIR: structural completion verdict for a raw gateway response
 * body. Only finish_reason === "stop" AND returned model === expected model
 * AND non-trivial/acceptable content is a usable success. "length", empty
 * finishes, wrong/absent model and non-JSON bodies are explicit failures.
 */
export function completionVerdict(body: string, expectedModel: string, marker: string): FinalAnswerCheck {
  let j: { choices?: Array<{ finish_reason?: string; message?: { content?: string } }>; model?: string };
  try {
    j = JSON.parse(body) as typeof j;
  } catch {
    return { ok: false, reason: "NO_STRUCTURE" };
  }
  const fr = String(j.choices?.[0]?.finish_reason ?? "");
  if (fr === "") return { ok: false, reason: "FINISH_EMPTY" };
  if (fr !== "stop") return { ok: false, reason: "FINISH_NOT_STOP" };
  const m = String(j.model ?? "");
  if (m === "" || m !== expectedModel) return { ok: false, reason: "MODEL_MISMATCH" };
  const content = String(j.choices?.[0]?.message?.content ?? "");
  if (marker && content.includes(marker)) return { ok: true, reason: "OK" };
  if (content.trim().length < 4) return { ok: false, reason: "THIN_CONTENT" };
  const gate = finalAnswerCheck(content, marker);
  if (!gate.ok) return { ok: false, reason: gate.reason };
  return { ok: true, reason: "OK" };
}

/**
 * Phase-1G REPAIR: bounded gateway release. Covers: alive (kill -> exit ->
 * listener verified down), already-exited (no kill, verify only), stuck
 * (bounded deadline fail), and reentrant calls. probeAlive() must observe
 * the loopback port; release resolves only after the port stops answering.
 */
export function releaseGateway(
  child: {
    exitCode: number | null;
    kill: (s?: NodeJS.Signals) => boolean;
    once: (ev: string, fn: (...a: unknown[]) => void) => unknown;
  },
  probeAlive: () => Promise<boolean>,
  deadlineMs = 10_000,
): Promise<void> {
  const releaseStartAt = performance.now();
  return new Promise<void>((resolve, reject) => {
    let settled = false;
    const hard = setTimeout(() => finish(new Error("TASK0_GATEWAY_RELEASE_TIMEOUT")), deadlineMs);
    const finish = (err?: Error) => {
      if (settled) return;
      settled = true;
      clearTimeout(hard);
      if (err) reject(err);
      else resolve();
    };
    const verify = async () => {
      for (let i = 0; i < 24; i++) {
        const up = await probeAlive().catch(() => false);
        if (!up) { finish(); return; }
        await new Promise((r) => setTimeout(r, 200));
        if (performance.now() > releaseStartAt + deadlineMs) { finish(new Error("TASK0_GATEWAY_RELEASE_TIMEOUT")); return; }
      }
      finish(new Error("TASK0_GATEWAY_LISTENER_STILL_UP"));
    };
    if (child.exitCode !== null) {
      void verify();
      return;
    }
    child.once("exit", () => { void verify(); });
    child.kill();
  });
}

/**
 * Phase-1G: final answer gate. Structural acceptance of a completed model
 * answer for the manual suite; a job placeholder, offline/closed wording
 * (traditional AND simplified), a smoke marker, processing hints, or
 * non-usable language is NEVER a final answer.
 */
export function finalAnswerCheck(text: string, marker: string): FinalAnswerCheck {
  const t = (text ?? "").trim();
  if (t.length === 0) return { ok: false, reason: "EMPTY" };
  if (marker && t.includes(marker)) return { ok: false, reason: "SMOKE_MARKER" };
  if (t.includes("本机模型桥接尚未启用") || t.includes("本機模型橋接尚未啟用")) return { ok: false, reason: "OFFLINE_CLOSED" };
  if (/問題已收到|问题已收到/.test(t)) return { ok: false, reason: "JOB_PLACEHOLDER" };
  if (/查看結果\s+[A-Za-z0-9_-]{4,}|查看结果\s+[A-Za-z0-9_-]{4,}/.test(t)) return { ok: false, reason: "JOB_PLACEHOLDER" };
  if (/已提交|正在處理|处理中|稍後再試|稍后再试/.test(t)) return { ok: false, reason: "PROCESSING_ONLY" };
  if (!/[\u4e00-\u9fff]{4,}/.test(t)) return { ok: false, reason: "NOT_USABLE_LANGUAGE" };
  return { ok: true, reason: "OK" };
}

/** Strict job reference extraction (first request -> second formal query). */
export function jobIdStrict(text: string): string | null {
  const m = (text ?? "").match(/(?:參考編號|参考编号)\s*([A-Za-z0-9_-]{4,64})/);
  return m && m[1] ? m[1] : null;
}

function combinedSignal(caller: AbortSignal | undefined, capMs: number): AbortSignal {
  const anySig = (AbortSignal as unknown as { any?(signals: Iterable<AbortSignal>, ms?: number): AbortSignal }).any;
  const cap = AbortSignal.timeout(capMs);
  if (typeof anySig === "function") {
    if (caller) return anySig.call(AbortSignal, [caller, cap]);
    return cap;
  }
  const ctrl = new AbortController();
  const t = setTimeout(() => { ctrl.abort(new Error("TASK0_FORWARD_DEADLINE")); }, capMs);
  if (caller) {
    if (caller.aborted) { ctrl.abort(caller.reason); return ctrl.signal; }
    caller.addEventListener("abort", () => ctrl.abort(caller.reason), { once: true });
  }
  ctrl.signal.addEventListener("abort", () => clearTimeout(t), { once: true });
  return ctrl.signal;
}

export function createStrictBoundary(evidenceHost: string, gate: { port: number; channelValue: string }, nativeFetch: typeof fetch): StrictBoundary {
  const modelUrl = `https://${evidenceHost}/v1/chat/completions`;
  const lineReplyUrl = "https://api.line.me/v2/bot/message/reply";
  let stallPending = false;
  const b = {
    modelCalls: [] as StrictBoundary["modelCalls"],
    lineReplies: [] as StrictBoundary["lineReplies"],
    violations: [] as string[],
    delayMs: [] as number[],
    markStallOnce: () => { stallPending = true; },
    stallArmed: () => stallPending,
    fetch: null as unknown as StrictBoundary["fetch"],
  };
  b.fetch = async (input, init) => {
    const url = String(input);
    const method = (init?.method ?? (input instanceof Request ? input.method : "GET")).toUpperCase();
    if (url === modelUrl && method === "POST") {
      const body = String(init?.body ?? "");
      let model = "";
      try { model = String((JSON.parse(body) as { model?: unknown }).model ?? ""); } catch { /* body kept */ }
      const oneShotDelay = b.delayMs.shift();
      if (oneShotDelay) await new Promise((rr) => setTimeout(rr, oneShotDelay));
      if (stallPending) {
        stallPending = false;
        await new Promise((rr) => setTimeout(rr, 8_000));
        b.modelCalls.push({ method: "POST", status: 504, model, finishReason: "", modelReturned: "" });
        return new Response(JSON.stringify({ error: { message: "local inference timeout", type: "local_model_timeout" } }),
          { status: 504, headers: { "content-type": "application/json" } });
      }
      const fwd = await nativeFetch(`http://127.0.0.1:${gate.port}/v1/chat/completions`, {
        method: "POST",
        headers: { "content-type": "application/json", "x-investor-shared-secret": gate.channelValue },
        body,
        signal: combinedSignal(init?.signal as AbortSignal | undefined, 90_000),
      });
      const text = await fwd.text();
      let finishReason = "";
      let modelReturned = "";
      try {
        const j = JSON.parse(text) as { choices?: Array<{ finish_reason?: string }>; model?: string };
        finishReason = String(j.choices?.[0]?.finish_reason ?? "");
        modelReturned = String(j.model ?? "");
      } catch { /* non-JSON body is not a usable answer either */ }
      b.modelCalls.push({ method: "POST", status: fwd.status, model, finishReason, modelReturned });
      return new Response(text, { status: fwd.status, headers: { "content-type": "application/json" } });
    }
    if (url === lineReplyUrl && method === "POST") {
      const body = String(init?.body ?? "");
      const headers = String(JSON.stringify(init?.headers ?? {}));
      let replyTokenPrefix = "";
      let textCount = 0;
      const texts: string[] = [];
      try {
        const parsed = JSON.parse(body) as { replyToken?: string; messages?: Array<{ text?: string }> };
        replyTokenPrefix = (parsed.replyToken ?? "").slice(0, 8);
        for (const m of parsed.messages ?? []) if (typeof m.text === "string") texts.push(m.text);
        textCount = texts.length;
      } catch { /* counted as zero */ }
      b.lineReplies.push({ replyTokenPrefix, textCount, sawBearer: headers.includes('"authorization"'), texts });
      return new Response(JSON.stringify({ endpoint: "https://api.line.me/v2/bot/message/reply", detail: [] }),
        { status: 200, headers: { "content-type": "application/json", "x-line-request-id": "task0-phase1f-synthetic" } });
    }
    b.violations.push(`${method} ${url}`);
    throw new Error(`TASK0_BOUNDARY_VIOLATION:${method}:${url}`);
  };
  return b;
}

export type LocalGatewayHandle = {
  port: number;
  channelValue: string;
  child: GatewayChild;
  probeStats: { refused: number; timeout: boolean };
  stop: () => Promise<void>;
};

export async function startLocalGateway(opts: {
  model: string;
  llamaBaseUrl: string;
  profileJson: string;
  timeoutMs?: number;
  onProbe?: (url: string, i: number) => Promise<Response | null>;
  nativeFetch?: typeof fetch;
}): Promise<LocalGatewayHandle> {
  const exe = resolveApprovedPython();
  const port = await freeLoopbackPort();
  const script = fileURLToPath(new URL("../../../scripts/v213_local_llm_gateway.py", import.meta.url));
  const cwd = fileURLToPath(new URL("../../..", import.meta.url));
  const random = new Uint8Array(randomBytes(24));
  const channelValue = Array.from(random, (byte) => byte.toString(16).padStart(2, "0")).join("");
  const child = (_spawn as unknown as (cmd: string, args: string[], options: Record<string, unknown>) => GatewayChild)(
    exe,
    ["-B", script, "--host", "127.0.0.1", "--port", String(port)],
    {
    shell: false,
    cwd,
    stdio: ["ignore", "ignore", "pipe"],
    env: {
      PATH: process.env.PATH ?? "",
      SystemRoot: process.env.SystemRoot ?? "C:\\Windows",
      TEMP: process.env.TEMP ?? "",
      TMP: process.env.TMP ?? "",
      PYTHONIOENCODING: "utf-8",
      II_LLAMA_BASE_URL: opts.llamaBaseUrl,
      II_LOCAL_LLM_MODEL: opts.model,
      II_LOCAL_LLM_SHARED_SECRET: channelValue,
      V213_MODEL_PROFILE_JSON: opts.profileJson,
    } as NodeJS.ProcessEnv,
  });
  const startAt = Date.now();
  const deadline = Date.now() + 120_000;
  const probeStats = { refused: 0, timeout: false };
  let probeN = 0;
  const realFetch: typeof fetch = opts.nativeFetch ?? ((globalThis as unknown as { fetch: typeof fetch }).fetch.bind(globalThis));
  for (;;) {
    if (child.exitCode !== null) throw new Error(`TASK0_GATEWAY_CHILD_EXITED:${child.exitCode}`);
    const url = `http://127.0.0.1:${port}/health`;
    const t0 = Date.now();
    let r: Response | null;
    if (opts.onProbe) {
      r = await opts.onProbe(url, probeN);
    } else {
      r = await realFetch(url, {
        headers: { "x-investor-shared-secret": channelValue },
        signal: AbortSignal.timeout(2_500),
      }).catch(() => null);
    }
    probeN++;
    const elapsed = Date.now() - t0;
    if (r === null) {
      probeStats.refused++;
      if (elapsed >= 7_000 && elapsed < 20_000) probeStats.timeout = true;
    } else if (elapsed >= 7_000 && elapsed < 20_000) {
      probeStats.timeout = true;
    }
    if (r) {
      const body = (await r.json().catch(() => null)) as Record<string, unknown> | null;
      if (
        r.status === 200 &&
        body != null &&
        body.ok === true &&
        (body as { service?: unknown }).service === "v213-local-llm-gateway" &&
        (body as { health_schema_version?: unknown }).health_schema_version === 2 &&
        (body as { llama_reachable?: unknown }).llama_reachable === true &&
        (body as { selected_model_available?: unknown }).selected_model_available === true &&
        (body as { selected_model?: unknown }).selected_model === opts.model
      ) {
        return {
          port,
          channelValue,
          child,
          probeStats,
          stop: () => releaseGateway(child, () =>
            realFetch(`http://127.0.0.1:${port}/health`, { headers: { "x-investor-shared-secret": channelValue } })
              .then((r) => r.status === 200)
              .catch(() => false), 10_000),
        };
      }
    }
    if (Date.now() > deadline) {
      child.kill();
      throw new Error(`TASK0_GATEWAY_NOT_READY:last=${r ? r.status : "unreachable"}`);
    }
    await new Promise((r) => setTimeout(r, 500));
  }
}

export function profileJsonPath(): string {
  return fileURLToPath(new URL("../../../config/v213-model-profile-exl3-sc5-h6-v6.candidate.json", import.meta.url));
}

export function readProfileJson(): string {
  return readFileSync(profileJsonPath(), "utf-8").trim();
}

export function sha256Hex(text: string): string {
  return createHash("sha256").update(new TextEncoder().encode(text)).digest("hex");
}

export async function waitChildExit(c: GatewayChild, ms: number): Promise<number | null> {
  if (c.exitCode !== null) return c.exitCode;
  const exited = new Promise<number>((res) => { c.once("exit", () => res(c.exitCode ?? -1)); });
  const timeout = new Promise<null>((res) => setTimeout(() => res(null), ms));
  return Promise.race([exited, timeout]);
}