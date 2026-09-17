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
  modelCalls: Array<{ method: string; status: number; model: string }>;
  lineReplies: Array<{ replyTokenPrefix: string; textCount: number; sawBearer: boolean; texts: string[] }>;
  violations: string[];
};

export function createStrictBoundary(evidenceHost: string, gate: { port: number; secret: string }, nativeFetch: typeof fetch): StrictBoundary {
  const modelUrl = `https://${evidenceHost}/v1/chat/completions`;
  const lineReplyUrl = "https://api.line.me/v2/bot/message/reply";
  const b = {
    modelCalls: [] as StrictBoundary["modelCalls"],
    lineReplies: [] as StrictBoundary["lineReplies"],
    violations: [] as string[],
    fetch: null as unknown as StrictBoundary["fetch"],
  };
  b.fetch = async (input, init) => {
    const url = String(input);
    const method = (init?.method ?? (input instanceof Request ? input.method : "GET")).toUpperCase();
    if (url === modelUrl && method === "POST") {
      const body = String(init?.body ?? "");
      let model = "";
      try { model = String((JSON.parse(body) as { model?: unknown }).model ?? ""); } catch { /* body kept */ }
      const fwd = await nativeFetch(`http://127.0.0.1:${gate.port}/v1/chat/completions`, {
        method: "POST",
        headers: { "content-type": "application/json", "x-investor-shared-secret": gate.secret },
        body,
        signal: AbortSignal.timeout(90_000),
      });
      const text = await fwd.text();
      b.modelCalls.push({ method: "POST", status: fwd.status, model });
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
  secret: string;
  child: GatewayChild;
  stop: () => Promise<void>;
};

export async function startLocalGateway(opts: {
  model: string;
  llamaBaseUrl: string;
  profileJson: string;
  timeoutMs?: number;
}): Promise<LocalGatewayHandle> {
  const exe = resolveApprovedPython();
  const port = await freeLoopbackPort();
  const script = fileURLToPath(new URL("../../../scripts/v213_local_llm_gateway.py", import.meta.url));
  const cwd = fileURLToPath(new URL("../../..", import.meta.url));
  const random = new Uint8Array(randomBytes(24));
  const secret = Array.from(random, (byte) => byte.toString(16).padStart(2, "0")).join("");
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
      II_LOCAL_LLM_SHARED_SECRET: secret,
      V213_MODEL_PROFILE_JSON: opts.profileJson,
    } as NodeJS.ProcessEnv,
  });
  const deadline = Date.now() + 120_000;
  for (;;) {
    if (child.exitCode !== null) throw new Error(`TASK0_GATEWAY_CHILD_EXITED:${child.exitCode}`);
    const r = await fetch(`http://127.0.0.1:${port}/health`, {
      headers: { "x-investor-shared-secret": secret },
    }).catch(() => null);
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
          secret,
          child,
          stop: () => new Promise<void>((resolve, reject) => {
            child.once("exit", async () => {
              for (let i = 0; i < 24; i++) {
                const up = await fetch(`http://127.0.0.1:${port}/health`, {
                  headers: { "x-investor-shared-secret": secret },
                }).then(() => true).catch(() => false);
                if (!up) { resolve(); return; }
                await new Promise((r) => setTimeout(r, 250));
              }
              reject(new Error("TASK0_GATEWAY_LISTENER_STILL_UP"));
            });
            if (child.exitCode === null) child.kill();
            const guard = setTimeout(() => { child.kill(); }, 8_000);
            guard.unref();
          }),
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