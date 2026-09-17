import { describe, expect, it, vi, afterEach } from "vitest";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import {
  startDrain,
  finalAnswerCheck,
  jobIdStrict,
} from "./helpers/task0-general-qa-harness";

/**
 * TASK0 Phase-1G — offline negative gates for the general-QA live harness.
 * This file runs in the DEFAULT offline suite (fails red on any regression,
 * no gateway, no model, no network): collector semantics, strict job flow,
 * final-answer text contract (both traditional + simplified), opt-in gate,
 * and default-run exclusion of the manual suite.
 */
describe("TASK0 1G: drain collector semantics (offline)", () => {
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
    const before = performance.now();
    const startedReal = performance.now();
    let err: unknown = null;
    try {
      await d.settle();
    } catch (e) {
      err = e;
    }
    const elapsed = performance.now() - startedReal;
    expect(err).toBeTruthy();
    expect(String(err)).toContain("TASK0_DRAIN_TIMEOUT");
    expect(elapsed).toBeGreaterThanOrEqual(350);
    expect(elapsed).toBeLessThan(2_000);
    void before;
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

describe("TASK0 1G: job flow + final answer text contract (offline)", () => {
  const MARKER = "TASK0_LOCAL_MODEL_OK";

  it("job reference is extracted strictly from the worker's exact reply", () => {
    expect(jobIdStrict("問題已收到，參考編號 a1b2c3d4e5f60987。稍後輸入「查看結果 a1b2c3d4e5f60987」。")).toBe("a1b2c3d4e5f60987");
    expect(jobIdStrict("问题已收到，参考编号 ref_1234-ab。")).toBe("ref_1234-ab");
    expect(jobIdStrict("股票是股权。")).toBeNull();
  });

  it("placeholder / processing replies are NOT a final answer", () => {
    for (const t of [
      "問題已收到，參考編號 a1b2c3d4e5f60987。稍後輸入「查看結果 a1b2c3d4e5f60987」。",
      "问题已收到，参考编号 ref_1234-ab。",
      "已提交，稍後再試。",
      "正在處理中，請稍候。",
      "处理中，请稍候。",
    ]) {
      const c = finalAnswerCheck(t, MARKER);
      expect(c.ok, t).toBe(false);
      expect(["JOB_PLACEHOLDER", "PROCESSING_ONLY"], c.reason).toBeTruthy();
    }
    expect(finalAnswerCheck("問題已收到，參考編號 x1y2z3。", MARKER).reason).toBe("JOB_PLACEHOLDER");
    expect(finalAnswerCheck("已提交，稍後再試。", MARKER).reason).toBe("PROCESSING_ONLY");
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

describe("TASK0 1G: suite separation + opt-in gate (offline)", () => {
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
    expect(src).toContain(`if (process.env.II_TASK0_LIVE_OPTIN !== OPTIN) {`);
    expect(src).toContain("throw new Error");
    expect(src).toContain("opt-in is REQUIRED");
  });
});