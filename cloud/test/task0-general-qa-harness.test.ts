import { describe, expect, it, vi, afterEach } from "vitest";
import { readFileSync } from "node:fs";
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import {
  startDrain,
  finalAnswerCheck,
  jobIdStrict,
  completionVerdict,
  createStrictBoundary,
  releaseGateway,
} from "./helpers/task0-general-qa-harness";

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

  it("structural completion verdict: only finish=stop + correct model + real content pass", () => {
    const ok = JSON.stringify({
      id: "chatcmpl-t1",
      model: EXL3,
      choices: [{ index: 0, message: { role: "assistant", content: MARKER }, finish_reason: "stop" }],
    });
    expect(completionVerdict(ok, EXL3, MARKER)).toEqual({ ok: true, reason: "OK" });
    const length = ok.replace('"stop"', '"length"');
    expect(completionVerdict(length, EXL3, MARKER).reason).toBe("FINISH_NOT_STOP");
    const wrong = ok.replace(EXL3, "some-other-model");
    expect(completionVerdict(wrong, EXL3, MARKER).reason).toBe("MODEL_MISMATCH");
    const emptyFinish = JSON.stringify({ model: EXL3, choices: [{ message: { role: "assistant", content: MARKER }, finish_reason: "" }] });
    expect(completionVerdict(emptyFinish, EXL3, MARKER).reason).toBe("FINISH_EMPTY");
    expect(completionVerdict("not json at all", EXL3, MARKER).reason).toBe("NO_STRUCTURE");
    const thin = JSON.stringify({ model: EXL3, choices: [{ message: { role: "assistant", content: "ok" }, finish_reason: "stop" }] });
    expect(completionVerdict(thin, EXL3, MARKER).ok).toBe(false);
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

  it("gateway release: alive->kill->exit->listener-down resolves (verified, bounded)", async () => {
    let alive = true;
    const listeners: Record<string, Array<(...a: unknown[]) => void>> = {};
    const child = {
      exitCode: null as number | null,
      once(ev: string, fn: (...a: unknown[]) => void) { (listeners[ev] ??= []).push(fn); return child; },
      on(ev: string, fn: (...a: unknown[]) => void) { (listeners[ev] ??= []).push(fn); return child; },
      kill(signal?: NodeJS.Signals) { void signal; alive = false; queueMicrotask(() => { child.exitCode = 0; (listeners["exit"] ?? []).forEach((f) => f()); }); return true; },
    };
    let up = true;
    const probe = async () => up;
    const t = setTimeout(() => { up = false; }, 120);
    const r = releaseGateway(child as never, probe, 8_000);
    await r.then(
      () => expect(alive).toBe(false),
      (e) => { throw e; },
    );
    clearTimeout(t);
  });

  it("gateway release: child ALREADY exited before stop() resolves without kill (no dangling wait)", async () => {
    let killed = false;
    const child = {
      exitCode: -2 as number | null,
      once() { return child; },
      on() { return child; },
      kill() { killed = true; return true; },
    };
    await expect(releaseGateway(child as never, async () => false, 4_000)).resolves.toBeUndefined();
    expect(killed).toBe(false);
  });

  it("gateway release: kill that never emits exit must NOT wait 1h (bounded failure)", async () => {
    const child = {
      exitCode: null as number | null,
      once() { return child; },
      on() { return child; },
      kill() { return true; },
    };
    const t0 = performance.now();
    await expect(releaseGateway(child as never, async () => true, 900)).rejects.toThrow(/TIMEOUT|RELEASE/);
    expect(performance.now() - t0).toBeLessThan(5_000);
  });

  it("release is reentrant-safe: calling stop twice does not hang or double-emit violations", async () => {
    let exited = false;
    const listeners: Array<(...a: unknown[]) => void> = [];
    const child = {
      exitCode: null as number | null,
      once(_ev: string, fn: (...a: unknown[]) => void) { listeners.push(fn); return child; },
      on(_ev: string, fn: (...a: unknown[]) => void) { listeners.push(fn); return child; },
      kill() { if (!exited) { exited = true; queueMicrotask(() => { child.exitCode = 0; listeners.forEach((f) => f()); }); } return true; },
    };
    const p1 = releaseGateway(child as never, async () => false, 4_000);
    const p2 = releaseGateway(child as never, async () => false, 4_000);
    await expect(Promise.allSettled([p1, p2]).then((rs) => rs.every((x) => x.status === "fulfilled"))).resolves.toBe(true);
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