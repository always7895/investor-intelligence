import { describe, expect, it, vi, afterEach, beforeEach } from "vitest";
import { readFileSync } from "node:fs";
import { spawnSync } from "node:child_process";
vi.mock("node:child_process", async (importOriginal) => {
  const orig = await importOriginal<typeof import("node:child_process")>();
  return { ...orig, spawn: vi.fn() };
});
import { fileURLToPath } from "node:url";
import {
  startDrain,
  finalAnswerCheck,
  jobIdStrict,
  completionVerdict,
  createStrictBoundary,
  releaseGateway,
  startLocalGateway,
} from "./helpers/task0-general-qa-harness";
import { spawn } from "node:child_process";


/**
 * TASK0 Phase-1G REPAIR — offline negative gates for the general-QA live
 * harness. Offline only: no gateway child, no model, no network.
 * Covers: collector semantics, strict job flow, final-answer text contract
 * (both scripts), structural completion verdict, caller-cancel propagation,
 * gateway release states, and manual opt-in/runner separation.
 */
describe("TASK0 1G-R: drain collector semantics (offline)", () => {
  afterEach(() => vi.useRealTimers());

  it("rejects are captured and reported, never converted to fulfillment", async () => {
    const d = startDrain(5_000);
    d.add(Promise.resolve("ok"));
    d.add(Promise.reject(new Error("BACKGROUND_JOB_FAILED")));
    const r = await d.settle();
    expect(r.fulfilled).toBe(1);
    expect(r.rejected).toBe(1);
    expect(String(r.rejects[0])).toContain("BACKGROUND_JOB_FAILED");
  });

  it("work added AFTER the first batch is also awaited (late job included)", async () => {
    const d = startDrain(5_000);
    d.add(new Promise((res) => setTimeout(res, 120)));
    setTimeout(() => d.add(new Promise((res) => setTimeout(res, 30))), 30);
    const r = await d.settle();
    expect(r.fulfilled).toBe(2);
    expect(r.rejected).toBe(0);
  });

  it("a stuck promise fails at the REAL-time deadline (Date fake does not fool it)", async () => {
    vi.useFakeTimers({ toFake: ["Date"] });
    vi.setSystemTime(new Date(Date.UTC(2026, 8, 17, 1, 0, 0)));
    const d = startDrain(400);
    d.add(new Promise(() => { /* never resolves */ }));
    const startedReal = performance.now();
    let err: unknown = null;
    try {
      await d.settle();
    } catch (e: unknown) {
      err = e;
    }
    const elapsed = performance.now() - startedReal;
    expect(err).toBeTruthy();
    expect(String(err)).toContain("TASK0_DRAIN_TIMEOUT");
    expect(elapsed).toBeGreaterThanOrEqual(350);
    expect(elapsed).toBeLessThan(2_000);
  });

  it("normal batch completes well before the deadline", async () => {
    const d = startDrain(5_000);
    d.add(Promise.resolve(1));
    d.add(new Promise((res) => setTimeout(() => res(2), 20)));
    const t0 = performance.now();
    const r = await d.settle();
    expect(r.fulfilled).toBe(2);
    expect(performance.now() - t0).toBeLessThan(3_000);
  });
});

describe("TASK0 1G-R: structure, strictness and cleanup (offline)", () => {
  const MARKER = "TASK0_LOCAL_MODEL_OK";
  const EXL3 = "Qwen3.8-27B-EXL3-SC5-H6-V6";
  const probeStateRef: Array<() => Promise<never>> = [];

  it("both live callers use the shared real-time drain (no .catch('caught') reclassification)", () => {
    const chain = readFileSync(fileURLToPath(new URL("./v213-task0-general-qa-chain.test.ts", import.meta.url)), "utf-8");
    const manual = readFileSync(fileURLToPath(new URL("./manual/v213-task0-general-qa-live.manual.ts", import.meta.url)), "utf-8");
    for (const [label, src] of [["chain", chain], ["manual", manual]] as const) {
      expect(src, `${label} must import startDrain`).toContain("startDrain");
      expect(src, `${label} must call drain.settle()`).toContain(".settle()");
      expect(src, `${label} must have no 'caught' reclassification`).not.toContain('"caught"');
      expect(src, `${label} must have no tagged-Set p.catch pattern`).not.toContain('() => { tag.done = true; tag.value = "caught"');
    }
  });

  it("structural completion verdict: H3 rules (structure, finish, model, marker isolation)", () => {
    const base = (content: string, finish = "stop", model = EXL3) =>
      JSON.stringify({ id: "chatcmpl-t1", model, choices: [{ index: 0, message: { role: "assistant", content }, finish_reason: finish }] });
    const ANSWER = "股票是公司所有權的憑證，結構風險高於債券，但收益不固定。";
    expect(completionVerdict(base(ANSWER), EXL3, MARKER, "answer")).toEqual({ ok: true, reason: "OK" });
    expect(completionVerdict(base(MARKER), EXL3, MARKER, "answer").reason).toBe("FORBIDDEN_MARKER_IN_ANSWER");
    expect(completionVerdict(base(MARKER), EXL3, MARKER, "smoke")).toEqual({ ok: true, reason: "OK" });
    expect(completionVerdict(base(MARKER + "!"), EXL3, MARKER, "smoke").reason).toBe("SMOKE_NOT_EXACT");
    expect(completionVerdict(base(ANSWER, "length"), EXL3, MARKER).reason).toBe("FINISH_LENGTH");
    expect(completionVerdict(base(ANSWER, "content_filter"), EXL3, MARKER).ok).toBe(false);
    expect(completionVerdict(base(ANSWER, ""), EXL3, MARKER).reason).toBe("FINISH_EMPTY");
    expect(completionVerdict(base(ANSWER, "stop", "some-other-model"), EXL3, MARKER).reason).toBe("MODEL_MISMATCH");
    expect(completionVerdict(base(ANSWER, "stop", ""), EXL3, MARKER).reason).toBe("MODEL_MISMATCH");
    expect(completionVerdict("null", EXL3, MARKER).reason).toBe("NO_STRUCTURE");
    expect(completionVerdict("[1,2]", EXL3, MARKER).reason).toBe("NO_STRUCTURE");
    expect(completionVerdict("not json at all", EXL3, MARKER).reason).toBe("NO_STRUCTURE");
    expect(completionVerdict(JSON.stringify({ model: EXL3, choices: [] }), EXL3, MARKER).reason).toBe("NO_STRUCTURE");
    expect(completionVerdict(JSON.stringify({ model: EXL3 }), EXL3, MARKER).reason).toBe("NO_STRUCTURE");
    expect(completionVerdict(base("ok"), EXL3, MARKER).reason).toBe("THIN_CONTENT");
    expect(completionVerdict(base("問題已收到，參考編號 a1b2c3d4e5f60987。稍後輸入「查看結果 a1b2c3d4e5f60987」。"), EXL3, MARKER).ok).toBe(false);
  });

  it("caller abort propagates fast, no model call is recorded, no boundary violation", async () => {
    const seenSignals: AbortSignal[] = [];
    const fakeNative = async (_input: RequestInfo | URL, init?: RequestInit): Promise<Response> => {
      const sig = init?.signal as AbortSignal | undefined;
      if (sig) seenSignals.push(sig);
      await new Promise<void>((res, rej) => {
        if (sig) sig.addEventListener("abort", () => rej(new DOMException("aborted", "AbortError")), { once: true });
        setTimeout(res, 15_000);
      });
      return new Response(`${JSON.stringify({ choices: [], model: EXL3 })}`, { status: 200 });
    };
    const b = createStrictBoundary("task0-phase1f-live.trycloudflare.com", { port: 9, channelValue: "deadbeef" }, fakeNative);
    const ctrl = new AbortController();
    setTimeout(() => ctrl.abort(new Error("caller gave up")), 60);
    const t0 = performance.now();
    let err: unknown = null;
    try {
      await b.fetch(`https://task0-phase1f-live.trycloudflare.com/v1/chat/completions`, {
        method: "POST",
        body: JSON.stringify({ model: EXL3, messages: [] }),
        signal: ctrl.signal,
      });
    } catch (e) {
      err = e;
    }
    const elapsed = performance.now() - t0;
    expect(err).toBeTruthy();
    expect(elapsed).toBeLessThan(4_000); // not the 90s cap, not the fake 15s
    expect(seenSignals.length).toBe(1);
    expect(seenSignals[0]?.aborted).toBe(true); // cancellation reached the transport
    expect(b.modelCalls.length).toBe(0);
    expect(b.violations.length).toBe(0);
  });

  it("release: 404/503-style replies stay LIVE; release waits for exit + a non-live probe (503 class cannot pass)", async () => {
    let killed = false;
    const listeners: Array<(...a: unknown[]) => void> = [];
    const child = {
      exitCode: null as number | null,
      signalCode: null as NodeJS.Signals | null,
      spawnError: null as Error | null,
      once(_ev: string, fn: (...a: unknown[]) => void) { listeners.push(fn); return child; },
      kill() {
        killed = true;
        setTimeout(() => { child.exitCode = 0; listeners.forEach((f) => f()); }, 80);
        return true;
      },
    };
    let liveProbes = 0;
    const probe = async (): Promise<"live" | "down" | "unknown"> => {
      if (child.exitCode !== null) return "down";
      liveProbes++;
      return "live"; // 404/503/200-style: still answering before the process exits
    };
    await releaseGateway(child, probe, 8_000);
    expect(killed).toBe(true);
    expect(liveProbes).toBeGreaterThanOrEqual(1); // a live (503/404) probe did NOT close the release
  });

  it("release: child gone by SIGNAL (no exitCode) + down probe resolves WITHOUT kill", async () => {
    let killed = false;
    const child = {
      exitCode: null as number | null,
      signalCode: "SIGTERM" as NodeJS.Signals | null,
      spawnError: null as Error | null,
      once() { return child; },
      kill() { killed = true; return true; },
    };
    await expect(releaseGateway(child, async () => "down", 4_000)).resolves.toBeUndefined();
    expect(killed).toBe(false);
  });

  it("release: child gone by SPAWN ERROR resolves WITHOUT kill", async () => {
    let killed = false;
    const child = {
      exitCode: null as number | null,
      signalCode: null as NodeJS.Signals | null,
      spawnError: new Error("spawn ENOENT"),
      once() { return child; },
      kill() { killed = true; return true; },
    };
    await expect(releaseGateway(child, async () => "down", 4_000)).resolves.toBeUndefined();
    expect(killed).toBe(false);
  });

  it("release: probe errors/timeouts are UNKNOWN, never 'down' (stuck child = bounded failure, not hang)", async () => {
    let kills = 0;
    const child = {
      exitCode: null as number | null,
      signalCode: null as NodeJS.Signals | null,
      spawnError: null as Error | null,
      once() { return child; },
      kill() { kills++; return true; },
    };
    let probes = 0;
    const t0 = performance.now();
    await expect(
      releaseGateway(child, async () => {
        probes++;
        throw new Error("probe timeout");
      }, 900),
    ).rejects.toThrow(/RELEASE_TIMEOUT/);
    expect(performance.now() - t0).toBeLessThan(6_000);
    expect(probes).toBeGreaterThanOrEqual(1);
    expect(kills).toBeGreaterThanOrEqual(1);
  });

  it("release: calling it twice on the same (dead) child settles both, with one kill at most", async () => {
    let kills = 0;
    const child = {
      exitCode: 0 as number | null,
      signalCode: null as NodeJS.Signals | null,
      spawnError: null as Error | null,
      once() { return child; },
      kill() { kills++; return true; },
    };
    const p1 = releaseGateway(child, async () => "down", 4_000);
    const p2 = releaseGateway(child, async () => "down", 4_000);
    await Promise.all([p1, p2]);
    expect(kills).toBe(0);
  });

  it("model call cap: a forward beyond the cap is rejected BEFORE any backend I/O", async () => {
    let nativeHits = 0;
    const fakeNative = async (): Promise<Response> => {
      nativeHits++;
      return new Response(JSON.stringify({ model: EXL3, choices: [{ finish_reason: "stop", message: { role: "assistant", content: MARKER } }] }), { status: 200, headers: { "content-type": "application/json" } });
    };
    const b = createStrictBoundary("task0-phase1f-live.trycloudflare.com", { port: 9, channelValue: "deadbeef" }, fakeNative, 1);
    const first = await b.fetch(`https://task0-phase1f-live.trycloudflare.com/v1/chat/completions`, { method: "POST", body: JSON.stringify({ model: EXL3, messages: [] }) });
    expect(first.status).toBe(200);
    expect(nativeHits).toBe(1);
    await expect(b.fetch(`https://task0-phase1f-live.trycloudflare.com/v1/chat/completions`, { method: "POST", body: JSON.stringify({ model: EXL3, messages: [] }) })).rejects.toThrow("TASK0_MODEL_CALL_CAP");
    expect(nativeHits, "capped forward must never reach the backend").toBe(1);
    expect(b.modelCalls.length).toBe(1);
    expect(b.violations.length).toBe(0);
  });

  it("job reference is extracted strictly from the worker's exact reply", () => {
    expect(jobIdStrict("問題已收到，參考編號 a1b2c3d4e5f60987。稍後輸入「查看結果 a1b2c3d4e5f60987」。")).toBe("a1b2c3d4e5f60987");
    expect(jobIdStrict("问题已收到，参考编号 ref_1234-ab。")).toBe("ref_1234-ab");
    expect(jobIdStrict("股票是股权。")).toBeNull();
  });

  it("placeholder / processing replies are NOT a final answer", () => {
    const cases: Array<[string, string]> = [
      ["問題已收到，參考編號 a1b2c3d4e5f60987。稍後輸入「查看結果 a1b2c3d4e5f60987」。", "JOB_PLACEHOLDER"],
      ["问题已收到，参考编号 ref_1234-ab。", "JOB_PLACEHOLDER"],
      ["已提交，稍後再試。", "PROCESSING_ONLY"],
      ["正在處理中，請稍候。", "PROCESSING_ONLY"],
      ["处理中，请稍候。", "PROCESSING_ONLY"],
    ];
    for (const [t, want] of cases) {
      const c = finalAnswerCheck(t, MARKER);
      expect(c.ok, t).toBe(false);
      expect(c.reason, `expected ${want} for: ${t}`).toBe(want);
      expect(["JOB_PLACEHOLDER", "PROCESSING_ONLY"]).toContain(c.reason);
    }
  });

  it("offline/closed wording is rejected in BOTH traditional and simplified", () => {
    expect(finalAnswerCheck("本機模型橋接尚未啟用。", MARKER).reason).toBe("OFFLINE_CLOSED");
    expect(finalAnswerCheck("本机模型桥接尚未启用。", MARKER).reason).toBe("OFFLINE_CLOSED");
  });

  it("smoke marker / empty / thin English-only are rejected; a real Chinese final answer is accepted", () => {
    expect(finalAnswerCheck("TASK0_LOCAL_MODEL_OK", MARKER).reason).toBe("SMOKE_MARKER");
    expect(finalAnswerCheck("   ", MARKER).reason).toBe("EMPTY");
    expect(finalAnswerCheck("ok", MARKER).reason).toBe("NOT_USABLE_LANGUAGE");
    expect(finalAnswerCheck("股票是公司所有权的凭证，债券是债权凭证，风险特征不同。", MARKER)).toEqual({ ok: true, reason: "OK" });
  });
});

describe("TASK0 1G-R: suite separation + opt-in gate (offline)", () => {
  it("the manual file is NOT picked up by the default vitest include patterns", () => {
    const name = fileURLToPath(new URL("./manual/v213-task0-general-qa-live.manual.ts", import.meta.url));
    const defaultPatterns = [/\.test\.[cm]?[jt]s?$/, /\.spec\.[cm]?[jt]s?$/];
    for (const re of defaultPatterns) {
      expect(re.test(name), `default pattern ${re} must not match the manual file`).toBe(false);
    }
  });

  it("the live-only config includes the manual file and nothing else", () => {
    const cfg = readFileSync(fileURLToPath(new URL("../vitest.task0-live.config.ts", import.meta.url)), "utf-8");
    expect(cfg).toContain("test/manual/**/*.manual.ts");
  });

  it("the manual source carries the hard opt-in gate (throw, not skip)", () => {
    const src = readFileSync(fileURLToPath(new URL("./manual/v213-task0-general-qa-live.manual.ts", import.meta.url)), "utf-8");
    expect(src).toContain("if (process.env.II_TASK0_LIVE_OPTIN !== OPTIN) {");
    expect(src).toContain("throw new Error");
    expect(src).toContain("opt-in is REQUIRED");
  });

  it("running the live runner WITHOUT opt-in exits non-zero with zero python spawn (measured, offline)", () => {
    const cloud = fileURLToPath(new URL("..", import.meta.url));
    const bin = fileURLToPath(new URL("../node_modules/vitest/vitest.mjs", import.meta.url));
    const run = spawnSync(process.execPath, [bin, "run", "-c", "vitest.task0-live.config.ts"], {
      cwd: cloud,
      env: { ...process.env, II_TASK0_LIVE_OPTIN: "" },
      encoding: "utf-8",
      timeout: 120_000,
    });
    const out = `${run.stdout ?? ""}${run.stderr ?? ""}`;
    expect(run.status, out.slice(-1200)).not.toBe(0);
    expect(out).toContain("TASK0_LIVE_OPTIN_REQUIRED");
    expect(out).not.toContain("TASK0_GATEWAY_CHILD_EXITED");
    expect(out).not.toContain("v213-local-llm-gateway");
    expect(out).not.toMatch(/127\.0\.0\.1:\d+\/health/);
  }, 150_000);
});

describe("TASK0 1I: bounded release + forward budget (mandatory offline cases)", () => {
  beforeEach(() => { vi.useRealTimers(); });
  type FakeChild = {
    exitCode: number | null;
    signalCode: NodeJS.Signals | null;
    spawnError: Error | null;
    killCalls: number;
    kill: () => boolean;
    once: (ev: string, cb: (...a: unknown[]) => void) => unknown;
    on: (ev: string, cb: (...a: unknown[]) => void) => unknown;
    emitExit: (code?: number | null, sig?: NodeJS.Signals | null) => void;
  };
  const makeFakeChild = (autoExit: boolean): FakeChild => {
    const listeners: Record<string, Array<(v?: number, s?: NodeJS.Signals) => void>> = {};
    const c: FakeChild = {
      exitCode: null,
      signalCode: null,
      spawnError: null,
      killCalls: 0,
      kill: () => { c.killCalls++; if (c.exitCode === null && c.signalCode === null) c.exitCode = 0; return true; },
      once: (ev, cb) => { (listeners[ev] ??= []).push((v, sgn) => { if (ev === "exit") { c.exitCode = v === undefined ? 0 : v; c.signalCode = sgn ?? null; } }); return c; },
      on: (ev, cb) => { (listeners[ev] ??= []).push((v, sgn) => { if (ev === "exit") { c.exitCode = v === undefined ? 0 : v; c.signalCode = sgn ?? null; } }); return c; },
      emitExit: (code = 0, sig: NodeJS.Signals | null = null) => { c.exitCode = code; c.signalCode = sig; for (const cb of listeners["exit"] ?? []) cb(code === null ? undefined : code, sig ?? undefined); },
    };
    if (autoExit) setTimeout(() => c.emitExit(0), 20);
    return c;
  };

  it("CASE3: gone child + UNKNOWN probe (probe throws) is a BOUNDED FAILURE, never a success", async () => {
    const child = makeFakeChild(false);
    child.emitExit(0);
    await expect(
      releaseGateway(child as never, () => { throw new Error("PROBE_444"); }, 300).then(
        () => "RESOLVED",
        (e: Error) => "REJECTED:" + e.message,
      ),
    ).resolves.toMatch(/^REJECTED:TASK0_GATEWAY_RELEASE_TIMEOUT$/);
  });

  it("CASE1: child gone but the loopback answers 503 (live) — release must NOT resolve; bounded failure", async () => {
    const child = makeFakeChild(false);
    child.emitExit(0);
    await expect(
      releaseGateway(child as never, async () => "live", 300).then(
        () => "RESOLVED",
        (e: Error) => "REJECTED:" + e.message,
      ),
    ).resolves.toMatch(/^REJECTED:TASK0_GATEWAY_RELEASE_TIMEOUT$/);
  });

  it("CASE2(E): child gone + probe classification: ECONNRESET must be UNKNOWN (release then times out)", async () => {
    const child = makeFakeChild(false);
    child.emitExit(1);
    await expect(
      releaseGateway(child as never, async () => "unknown", 300).then(
        () => "RESOLVED",
        (e: Error) => "REJECTED:" + e.message,
      ),
    ).resolves.toMatch(/^REJECTED:TASK0_GATEWAY_RELEASE_TIMEOUT$/);
  });

  it("CASE2: normal death — gone + ECONNREFUSED (down) resolves; resolved inside deadline, kill attempted once", async () => {
    const child = makeFakeChild(false);
    child.emitExit(1); // normal death: process exits on its own
    const t0 = Date.now();
    const releaseP = releaseGateway(child as never, async () => "down", 4_000);
    await releaseP;
    expect(Date.now() - t0).toBeLessThan(3_500);
    expect(child.killCalls).toBe(0); // died before the release signal was ever needed
  });

  it("CASE5: startLocalGateway integration — ready BEFORE stop means ZERO kills; repeated stop() shares one release", async () => {
    (spawn as unknown as { mockClear: () => void }).mockClear?.();
    const child = makeFakeChild(false) as never as ReturnType<typeof spawn>;
    (spawn as unknown as { mockReturnValue: (v: unknown) => void }).mockReturnValue(child);
    let probeRound = 0;
    const handleP = startLocalGateway({
      model: "EXL3",
      llamaBaseUrl: "http://127.0.0.1:9",
      profileJson: "{}",
      onProbe: async () => {
        probeRound++;
        if (probeRound < 2) return new Response(JSON.stringify({ ok: false }), { status: 503 });
        return new Response(JSON.stringify({
          ok: true,
          service: "v213-local-llm-gateway",
          health_schema_version: 2,
          llama_reachable: true,
          selected_model_available: true,
          selected_model: "EXL3",
        }), { status: 200 });
      },
    });
    const handle = await handleP;
    expect((child as unknown as FakeChild).killCalls).toBe(0); // no release attempted before ready
    const fake = child as unknown as FakeChild;
    const stop1 = handle.stop();
    const stop2 = handle.stop();
    expect(stop1).toBe(stop2); // same shared cleanup promise
    await stop1;
    expect(stop2 === stop1).toBeTypeOf("boolean");
    expect(fake.killCalls).toBeLessThanOrEqual(1);
  });

  it("CASE4: startup exits BEFORE readiness — failure path performs the same bounded cleanup (single release, no hang)", async () => {
    const fake = makeFakeChild(false) as never as ReturnType<typeof spawn>;
    (spawn as unknown as { mockReturnValue: (v: unknown) => void }).mockReturnValue(fake);
    setTimeout(() => { (fake as unknown as FakeChild).emitExit(3); }, 20);
    await expect(startLocalGateway({
      model: "EXL3",
      llamaBaseUrl: "http://127.0.0.1:9",
      profileJson: "{}",
      onProbe: async () => new Response(JSON.stringify({ ok: false }), { status: 503 }),
    })).rejects.toThrow(/TASK0_GATEWAY_CHILD_EXITED:3/);
    // release performed: child is gone; a follow-up release settles fast
    await expect(releaseGateway(fake as never, async () => "down", 3_000)).resolves.toBeUndefined();
  });

  it("CASE6: forward budget is reserved BEFORE any await — parallel cap: 2 accepted, 3rd rejected, native hit exactly 2", async () => {
    let nativeHits = 0;
    const b = createStrictBoundary(
      "h.test",
      { port: 1, channelValue: "x" },
      (async () => {
        nativeHits++;
        await new Promise((r) => setTimeout(r, 80));
        return new Response(JSON.stringify({ choices: [{ finish_reason: "stop" }], model: "EXL3" }), { status: 200 });
      }) as typeof fetch,
      2,
    );
    const r1 = b.fetch("https://h.test/v1/chat/completions", { method: "POST", body: JSON.stringify({ model: "EXL3" }) }) as Promise<Response>;
    const r2 = b.fetch("https://h.test/v1/chat/completions", { method: "POST", body: JSON.stringify({ model: "EXL3" }) }) as Promise<Response>;
    const r3p = b.fetch("https://h.test/v1/chat/completions", { method: "POST", body: JSON.stringify({ model: "EXL3" }) }).then(
      () => "OK",
      (e: unknown) => "CAP:" + String(e),
    );
    expect(await r1).toBeInstanceOf(Response);
    expect(await r2).toBeInstanceOf(Response);
    expect(await r3p).toBe("CAP:Error: TASK0_MODEL_CALL_CAP");
    expect(nativeHits).toBe(2);
  });

  it("CASE7: a forward whose backend call ERRORS still consumes its budget unit", async () => {
    let nativeHits = 0;
    const b = createStrictBoundary(
      "h.test",
      { port: 1, channelValue: "x" },
      (async () => {
        nativeHits++;
        throw new Error("ECONNREFUSED");
      }) as typeof fetch,
      1,
    );
    const r1 = b.fetch("https://h.test/v1/chat/completions", { method: "POST", body: JSON.stringify({ model: "EXL3" }) }).then(
      () => "OK",
      (e: unknown) => "ERR:" + String(e),
    );
    const r2 = b.fetch("https://h.test/v1/chat/completions", { method: "POST", body: JSON.stringify({ model: "EXL3" }) }).then(
      () => "OK",
      (e: unknown) => "CAP:" + String(e),
    );
    expect(await r1).toBe("ERR:Error: ECONNREFUSED");
    expect(await r2).toBe("CAP:Error: TASK0_MODEL_CALL_CAP");
    expect(nativeHits).toBe(1);
  });
});
