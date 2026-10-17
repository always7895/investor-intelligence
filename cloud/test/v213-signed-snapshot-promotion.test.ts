import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { pinPublicSnapshot } from "../src/v213/public-snapshot";
import { loadV213FreshTop20Report, getV213ReportReference } from "../src/v213/top20-report";
import {
  INSUFFICIENT_EVIDENCE_MESSAGE,
  readV213BottleneckReport,
} from "../src/v213/bottleneck-report";
import { SNAPSHOT_OBJECT_KEYS, SNAPSHOT_SEAL_KEY } from "../src/v213/snapshot-seal";
import { asKv, MemoryKv } from "./fake-kv";
import type { V213Top20Env } from "../src/v213/top20-report";
import type { ParsedQuery } from "../src/core";

// Legacy filename only: synthetic sealed bytes are NOT signatures, historical
// admissions, source authentication or fresh Production/release proof.
import { buildSyntheticSealedReplay, makeOfflineEnv, SYNTHETIC_RUN, SYNTHETIC_NOW, SYNTHETIC_STAMP } from "./synthetic-sealed-replay-fixture";
const RUN = SYNTHETIC_RUN;
const fetchGuard = vi.fn(() => { throw new Error("OFFLINE_REPLAY_NETWORK_FORBIDDEN"); });
let guards: ReturnType<typeof makeOfflineEnv>[] = [];
beforeEach(() => { guards = []; fetchGuard.mockClear(); vi.stubGlobal("fetch", fetchGuard); });
async function store(): Promise<MemoryKv> { return (await buildSyntheticSealedReplay()).kv; }
function envWith(kv: MemoryKv): V213Top20Env {
  const guard = makeOfflineEnv(kv); guards.push(guard); return guard.env;
}

const rankingQuery: ParsedQuery = {
  intent: "ranking", ticker: null, period: "weekly",
  referenceId: null, normalized: "Top 20 bottleneck ranking",
};

function freezeSyntheticClock(): void {
  vi.useFakeTimers();
  vi.setSystemTime(new Date(SYNTHETIC_NOW));
}

afterEach(() => {
  try {
    expect(fetchGuard).not.toHaveBeenCalled();
    for (const guard of guards) { expect(guard.privateKv.reads).toBe(0); expect(guard.securityKv.reads).toBe(0); }
  } finally { vi.useRealTimers(); vi.unstubAllGlobals(); }
});

describe("Synthetic sealed replay through actual loaders; no promotion authority", () => {
  it("serves a sealed synthetic qualified-shape report through loadV213FreshTop20Report", async () => {
    freezeSyntheticClock();
    const env = envWith(await store());
    const report = await loadV213FreshTop20Report(env, rankingQuery);
    expect(typeof report).not.toBe("string");
    const top = report as NonNullable<typeof report> & object;
    expect(top).toBeTruthy();
    const t = top as {
      schema_version: number;
      records: { rank: number; ticker: string; system_bottleneck_explosion_score?: number }[];
      display_columns: readonly string[];
      provider_scope: string;
    };
    expect(t.schema_version).toBe(2);
    expect(t.provider_scope).toBe("public_only");
    expect(t.display_columns).toHaveLength(7);
    expect(t.records).toHaveLength(2);
    expect(t.records.map(r => r.ticker)).toEqual(["SYNTHA", "SYNTHB"]);
    expect(t.records.map(r => r.rank)).toEqual([1, 2]);
    const ref = getV213ReportReference(top as Parameters<typeof getV213ReportReference>[0]);
    expect(ref?.snapshot).toBe(`s:${RUN}`);
    expect(typeof ref?.reportSha256).toBe("string");
    expect(new RegExp("^[0-9a-f]{64}$").test(ref?.reportSha256 ?? "")).toBe(true);
  });

  it("readV213BottleneckReport returns the synthetic qualified-shape two-row report", async () => {
    freezeSyntheticClock();
    const view = await pinPublicSnapshot(envWith(await store()));
    expect(view.integrity).toBe("sealed");
    expect(view.runId).toBe(RUN);
    const report = await readV213BottleneckReport(view);
    expect(report).not.toBeNull();
    expect(report?.status).toBe("QUALIFIED");
    expect(report?.admitted_count).toBe(2);
    expect(report?.ranked_count).toBe(2);
    expect(report?.total_evaluated).toBe(2);
    expect(report?.provider_scope).toBe("public_only");
    expect(report?.live_qualification).toBe("DEFERRED");
    for (const row of report?.records ?? []) {
      expect(row.admission_status).toBe("ADMITTED");
      expect(row.score_qualified).toBe(true);
      expect(row.candidate_assessment_mode).toBe("RANKING_QUALIFIED");
      expect(row.claims_audit.conflicted_claim_count).toBe(0);
      expect(row.claims_audit.supported_claim_count).toBeGreaterThanOrEqual(2);
    }
    const scores = (report?.records ?? []).map(r => r.system_bottleneck_explosion_score);
    expect(scores[0]).toBeGreaterThanOrEqual(scores[1] ?? 0);
    expect(scores[0]).toBeGreaterThan(0);
  });

  it("all 13 sealed objects plus the seal verify at pin time", async () => {
    freezeSyntheticClock();
    const kv = await store();
    for (const key of SNAPSHOT_OBJECT_KEYS) {
      expect(kv.values.has(`snapshot:${RUN}:${key}`)).toBe(true);
    }
    expect(kv.values.has(`snapshot:${RUN}:${SNAPSHOT_SEAL_KEY}`)).toBe(true);
    const rawSeal = kv.values.get(`snapshot:${RUN}:${SNAPSHOT_SEAL_KEY}`)!;
    const bytes = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(rawSeal));
    const digest = Array.from(new Uint8Array(bytes), byte => byte.toString(16).padStart(2, "0")).join("");
    expect(JSON.parse(kv.values.get("snapshot:current")!).seal_sha256).toBe(digest);
    expect((await pinPublicSnapshot(envWith(kv))).integrity).toBe("sealed");
  });

  it("tampered pointer seal sha-256 fails closed to INSUFFICIENT_EVIDENCE", async () => {
    freezeSyntheticClock();
    const kv = await store();
    const pointer = JSON.parse(kv.values.get("snapshot:current")!);
    pointer.seal_sha256 = "0011223344556677889900112233445566778899001122334455667788990011";
    kv.values.set("snapshot:current", JSON.stringify(pointer));
    const view = await pinPublicSnapshot(envWith(kv));
    expect(view.kind).toBe("invalid");
    const viewAgain = await pinPublicSnapshot(envWith(kv));
    expect(viewAgain.integrity).toBe("invalid");
    expect(await loadV213FreshTop20Report(envWith(kv), rankingQuery)).toBe(INSUFFICIENT_EVIDENCE_MESSAGE);
  });

  it("tampered seal manifest (size drift) fails closed even with recomputed pointer hash", async () => {
    freezeSyntheticClock();
    const kv = await store();
    const prefix = `snapshot:${RUN}:`;
    const manifest = JSON.parse(kv.values.get(prefix + SNAPSHOT_SEAL_KEY)!);
    manifest.objects["reports:latest"].utf8_bytes -= 1;
    const raw = JSON.stringify(manifest);
    const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(raw));
    const digestHex = Array.from(new Uint8Array(digest), b => b.toString(16).padStart(2, "0")).join("");
    kv.values.set(prefix + SNAPSHOT_SEAL_KEY, raw);
    const pointer = JSON.parse(kv.values.get("snapshot:current")!);
    pointer.seal_sha256 = digestHex;
    kv.values.set("snapshot:current", JSON.stringify(pointer));
    const view = await pinPublicSnapshot(envWith(kv));
    expect(view.kind).toBe("invalid");
    expect(await loadV213FreshTop20Report(envWith(kv), rankingQuery)).toBe(INSUFFICIENT_EVIDENCE_MESSAGE);
  });

  it("pointerless unsealed single-report writes carry no publication authority", async () => {
    freezeSyntheticClock();
    const { reportRaw } = await buildSyntheticSealedReplay();
    const top20 = reportRaw;
    const bottleneck = reportRaw;
    // Shape A: flat legacy pointer present, raw unsealed reports written
    // directly into the namespace, no seal, no run bound.
    const kvLegacy = new MemoryKv();
    kvLegacy.values.set("snapshot:current", "{\"run_id\":\"legacy-run\"}");
    kvLegacy.values.set("v213:top20-report:latest", top20);
    kvLegacy.values.set("v213:bottleneck-report:latest", bottleneck);
    const viewA = await pinPublicSnapshot(envWith(kvLegacy));
    expect(viewA.integrity).toBe("legacy");
    expect(await readV213BottleneckReport(viewA)).toBeNull();
    const outA = await loadV213FreshTop20Report(envWith(kvLegacy), rankingQuery);
    expect(typeof outA !== "object" || outA === null).toBe(true);
    // Shape B: no pointer at all; raw writes alone authorize nothing.
    const kvNone = new MemoryKv();
    kvNone.values.set("v213:top20-report:latest", top20);
    kvNone.values.set("last_successful_pipeline_timestamp", SYNTHETIC_STAMP);
    const viewB = await pinPublicSnapshot(envWith(kvNone));
    expect(await readV213BottleneckReport(viewB)).toBeNull();
    const outB = await loadV213FreshTop20Report(envWith(kvNone), rankingQuery);
    expect(typeof outB !== "object" || outB === null).toBe(true);
  });

  it("absent store (no snapshot at all) fails closed without legacy borrow", async () => {
    freezeSyntheticClock();
    const out = await loadV213FreshTop20Report(envWith(new MemoryKv()), rankingQuery);
    expect(out !== INSUFFICIENT_EVIDENCE_MESSAGE).toBe(true);
    expect(typeof out !== "object" || out === null).toBe(true);
  });
});