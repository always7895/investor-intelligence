// Legacy filename retained; offline synthetic replay, NOT live or release proof.
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { pinPublicSnapshot } from "../src/v213/public-snapshot";
import { loadV213FreshTop20Report, getV213ReportReference } from "../src/v213/top20-report";
import { readV213BottleneckReport } from "../src/v213/bottleneck-report";
import type { ParsedQuery } from "../src/core";
import { buildSyntheticSealedReplay, makeOfflineEnv, SYNTHETIC_NOW, SYNTHETIC_RUN, SYNTHETIC_STAMP } from "./synthetic-sealed-replay-fixture";

const query: ParsedQuery = { intent: "ranking", ticker: null, period: "weekly", referenceId: null, normalized: "Top 20" };
const fetchGuard = vi.fn(() => { throw new Error("OFFLINE_REPLAY_NETWORK_FORBIDDEN"); });
let guards: ReturnType<typeof makeOfflineEnv>[] = [];
beforeEach(() => {
  guards = []; fetchGuard.mockClear(); vi.stubGlobal("fetch", fetchGuard);
  vi.useFakeTimers(); vi.setSystemTime(new Date(SYNTHETIC_NOW));
});
afterEach(() => {
  try {
    expect(fetchGuard).not.toHaveBeenCalled();
    for (const guard of guards) { expect(guard.privateKv.reads).toBe(0); expect(guard.securityKv.reads).toBe(0); }
  } finally { vi.useRealTimers(); vi.unstubAllGlobals(); }
});

it("replays synthetic sealed bytes through the actual public report caller offline", async () => {
  const fixture = await buildSyntheticSealedReplay();
  const guard = makeOfflineEnv(fixture.kv); guards.push(guard);
  const view = await pinPublicSnapshot(guard.env);
  expect(view.integrity).toBe("sealed");
  const report = await loadV213FreshTop20Report(guard.env, query);
  expect(report).not.toBeNull(); expect(typeof report).toBe("object");
  if (!report || typeof report === "string") throw new Error("SYNTHETIC_REPORT_MISSING");
  const reference = getV213ReportReference(report);
  expect(reference?.snapshot).toBe(`s:${SYNTHETIC_RUN}`);
  expect(reference?.reportSha256).toMatch(/^[0-9a-f]{64}$/);
});

it("refuses a still-valid sealed report at a stale synthetic clock via the unchanged freshness gate", async () => {
  const fixture = await buildSyntheticSealedReplay();
  const guard = makeOfflineEnv(fixture.kv); guards.push(guard);
  expect(typeof await loadV213FreshTop20Report(guard.env, query)).toBe("object");
  vi.setSystemTime(new Date(Date.parse(SYNTHETIC_STAMP) + 86401 * 1000));
  const view = await pinPublicSnapshot(guard.env);
  expect(view.integrity).toBe("sealed");
  expect((await readV213BottleneckReport(view))?.status).toBe("QUALIFIED");
  const stale = await loadV213FreshTop20Report(guard.env, query);
  expect(typeof stale).toBe("string");
  expect(stale).toContain("Seven-field Top20 is stale or invalid");
});
