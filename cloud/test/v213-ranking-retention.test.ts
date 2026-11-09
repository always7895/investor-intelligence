import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
import { afterEach, describe, expect, it, vi } from "vitest";
import { BOTTLENECK_V3_KEY, buildBottleneckDetail, buildBottleneckTop20Messages, estimateTop20Fallback,
  loadBottleneckV3, parseBottleneckV3 } from "../src/v213/bottleneck-v3";
import { clearVerifiedLazyBodies, pinPublicSnapshot, scopePublicSnapshot, type PublicSnapshotView } from "../src/v213/public-snapshot";
import { readRetainedRanking } from "../src/v213/ranking-retention";
import { SNAPSHOT_LAZY_BLOB_PREFIX, SNAPSHOT_SEAL_KEY } from "../src/v213/snapshot-seal";
import { GUIDANCE_BINDING_KEY } from "../src/v213/revenue-guidance-machine";
import { asKv, MemoryKv } from "./fake-kv";

// Existing synthetic offline sealed replay, never network or installed KV.
const replay = JSON.parse(readFileSync(new URL("./fixtures/revenue-guidance-f06-sealed-replay.json", import.meta.url), "utf8")) as {
  run_id: string; index: Record<string, string>; files: Record<string, string>;
};
const sha = (body: string) => createHash("sha256").update(body, "utf8").digest("hex");
const prefix = `snapshot:${replay.run_id}:`;
const HOUR = 3600_000;
interface FixtureRanking { generated_at: string; top: { symbol: string; rank: number }[]; }
function fixture(change?: (raw: FixtureRanking) => void, omitMachineBinding = false) {
  const kv = new MemoryKv();
  for (const [key, file] of Object.entries(replay.index)) kv.values.set(key, replay.files[file]!);
  const manifest = JSON.parse(kv.values.get(prefix + SNAPSHOT_SEAL_KEY)!);
  const blob = SNAPSHOT_LAZY_BLOB_PREFIX + manifest.objects[BOTTLENECK_V3_KEY].sha256;
  const raw: FixtureRanking = JSON.parse(kv.values.get(blob)!);
  if (omitMachineBinding) delete manifest.objects[GUIDANCE_BINDING_KEY];
  if (change || omitMachineBinding) {
    change?.(raw);
    const body = JSON.stringify(raw);
    manifest.objects[BOTTLENECK_V3_KEY] = { sha256: sha(body), utf8_bytes: new TextEncoder().encode(body).byteLength };
    kv.values.delete(blob);
    kv.values.set(SNAPSHOT_LAZY_BLOB_PREFIX + sha(body), body);
    const seal = JSON.stringify(manifest);
    kv.values.set(prefix + SNAPSHOT_SEAL_KEY, seal);
    const pointer = JSON.parse(kv.values.get("snapshot:current")!);
    pointer.seal_sha256 = sha(seal);
    kv.values.set("snapshot:current", JSON.stringify(pointer));
  }
  const env = { PUBLIC_CACHE: asKv(kv), TENANT_PRIVATE_CACHE: asKv(new MemoryKv()), EPHEMERAL_SECURITY_CACHE: asKv(new MemoryKv()) };
  return { kv, env, raw, blob };
}

afterEach(() => vi.restoreAllMocks());

describe("historical ranking retention custody", () => {
  it("retains exact original time and requires normal structural parsing", async () => {
    const { env, raw } = fixture();
    const now = Date.parse(raw.generated_at) + 48 * HOUR;
    expect(parseBottleneckV3(raw, now)).toBeNull();
    const retained = await readRetainedRanking(await pinPublicSnapshot(env), now);
    expect(retained).not.toBeNull();
    expect(retained!.originalAsOf).toBe(raw.generated_at);
    expect(retained!.observedAt).toBe(now);
    expect(retained!.parseAt).toBe(Date.parse(raw.generated_at));
    expect(retained!.raw).toEqual(raw);
    expect(retained!.notice).toContain(raw.generated_at);
    expect(parseBottleneckV3(retained!.raw, retained!.parseAt)?.top).toHaveLength(raw.top.length);
  });

  it("keeps every hourly read populated across 30 UTC resets without pointer writes", async () => {
    const { kv, env, raw } = fixture();
    const before = new Map(kv.values);
    const start = Date.parse(raw.generated_at) + 48 * HOUR;
    const clock = vi.spyOn(Date, "now");
    for (let hour = 0; hour < 30 * 24; hour++) {
      clock.mockReturnValue(start + hour * HOUR);
      const historical = await loadBottleneckV3(await pinPublicSnapshot(scopePublicSnapshot(env)));
      expect(historical?.generated_at).toBe(raw.generated_at);
      expect(historical?.top).toHaveLength(raw.top.length);
      expect(historical?.historical_retention_notice).toContain(raw.generated_at);
    }
    expect(kv.values).toEqual(before);
  }, 60_000);

  it("shows dated retained facts on both ranking/detail surfaces without reviving machine approval", async () => {
    const { env, raw } = fixture();
    vi.spyOn(Date, "now").mockReturnValue(Date.parse(raw.generated_at) + 48 * HOUR);
    const historical = await loadBottleneckV3(await pinPublicSnapshot(env), { guidanceMachineEnabled: true });
    expect(historical?.top).toHaveLength(raw.top.length);
    if (!historical) throw new Error("RETAINED_FACTS_UNAVAILABLE");
    expect(historical.historical_forecasts_unavailable).toBe(true);
    expect(estimateTop20Fallback(historical, historical.top[0]!)).toBeNull();
    expect(historical.top.every(entry => !entry.forecast && !entry.trend && !entry.outlook)).toBe(true);
    for (const style of ["text", "flex"] as const) {
      expect(JSON.stringify(buildBottleneckTop20Messages(historical, style))).toContain(raw.generated_at);
      expect(JSON.stringify(buildBottleneckDetail(historical, historical.top[0]!.symbol, style))).toContain(raw.generated_at);
    }
  });

  it("keeps fresh sealed facts available when machine authority is absent, without any forecast fallback", async () => {
    const { env, raw } = fixture(undefined, true);
    vi.spyOn(Date, "now").mockReturnValue(Date.parse(raw.generated_at) + HOUR);
    const facts = await loadBottleneckV3(await pinPublicSnapshot(env), { guidanceMachineEnabled: true });
    expect(facts?.top).toHaveLength(raw.top.length);
    if (!facts) throw new Error("SEALED_FACTS_UNAVAILABLE");
    expect(facts.generated_at).toBe(raw.generated_at);
    expect(facts.historical_forecasts_unavailable).toBe(true);
    expect(facts.top.every(entry => !entry.forecast && !entry.outlook && !entry.trend)).toBe(true);
    expect(estimateTop20Fallback(facts, facts.top[0]!)).toBeNull();
  });

  it("does not let wire metadata create historical custody or suppress ordinary forecast validation", () => {
    const { raw } = fixture();
    Object.assign(raw, { historical_retention_notice: "自行核准", historical_forecasts_unavailable: true });
    const current = parseBottleneckV3(raw, Date.parse(raw.generated_at));
    expect(current).not.toBeNull();
    expect(current?.historical_retention_notice).toBeUndefined();
    expect(current?.historical_forecasts_unavailable).toBeUndefined();
  });

  it("preserves real reader custody through its non-owner rights wrapper, but not a copied view", async () => {
    const { env, raw } = fixture();
    const now = Date.parse(raw.generated_at) + 48 * HOUR;
    const view = await pinPublicSnapshot(scopePublicSnapshot(env, "friend"));
    expect(await readRetainedRanking(view, now)).not.toBeNull();
    expect(await readRetainedRanking({ ...view }, now)).toBeNull();
  });

  it("does not grant custody to a structural sealed lookalike", async () => {
    const { raw } = fixture();
    let reads = 0;
    const view: PublicSnapshotView = { kind: "snapshot", integrity: "sealed", runId: replay.run_id,
      hasSealedObject: () => true, json: async <T>() => raw as T,
      text: async () => { reads++; return JSON.stringify(raw); } };
    expect(await readRetainedRanking(view, Date.parse(raw.generated_at) + 48 * HOUR)).toBeNull();
    expect(reads).toBe(0);
  });

  it("rejects raw bootstrap and a missing or corrupted lazy body", async () => {
    clearVerifiedLazyBodies();
    const { kv, env, raw, blob } = fixture();
    const now = Date.parse(raw.generated_at) + 48 * HOUR;
    // Unsealed raw bootstrap must never become a fabricated last-good ranking.
    const pointer = kv.values.get("snapshot:current")!;
    kv.values.delete("snapshot:current");
    kv.values.set(BOTTLENECK_V3_KEY, JSON.stringify(raw));
    expect(await readRetainedRanking(await pinPublicSnapshot(env), now)).toBeNull();
    kv.values.set("snapshot:current", pointer);
    const original = kv.values.get(blob)!;
    kv.values.set(blob, original + " ");
    expect(await readRetainedRanking(await pinPublicSnapshot(env), now)).toBeNull();
    kv.values.delete(blob);
    expect(await readRetainedRanking(await pinPublicSnapshot(env), now)).toBeNull();
  });

  it.each(["2026-02-30T13:00:00Z", "not-a-time", "2027-01-01T00:00:00Z", "2026-02-27", "0000-01-01T00:00:00Z"])("rejects invalid/future report time %s", async generated => {
    const { env } = fixture(raw => { raw.generated_at = generated; });
    expect(await readRetainedRanking(await pinPublicSnapshot(env), Date.parse("2026-11-09T00:00:00Z"))).toBeNull();
  });

  it("leaves fresh ranking and invalid observation clocks to the normal path", async () => {
    const { env, raw } = fixture();
    const view = await pinPublicSnapshot(env);
    expect(await readRetainedRanking(view, Date.parse(raw.generated_at))).toBeNull();
    expect(await readRetainedRanking(view, NaN)).toBeNull();
    expect(await readRetainedRanking(view, Infinity)).toBeNull();
  });

  it("does not turn an empty, duplicated or structurally invalid ranking into approval", async () => {
    for (const change of [
      (raw: FixtureRanking) => { raw.top = []; },
      (raw: FixtureRanking) => { raw.top[1]!.symbol = raw.top[0]!.symbol; },
    ]) {
      const { env, raw } = fixture(change);
      expect(await readRetainedRanking(await pinPublicSnapshot(env), Date.parse(raw.generated_at) + 48 * HOUR)).toBeNull();
    }
    const { env, raw } = fixture(raw => { raw.top[0]!.rank = 99; });
    const retained = await readRetainedRanking(await pinPublicSnapshot(env), Date.parse(raw.generated_at) + 48 * HOUR);
    expect(retained).not.toBeNull();
    expect(parseBottleneckV3(retained!.raw, retained!.parseAt)).toBeNull();
  });
});
