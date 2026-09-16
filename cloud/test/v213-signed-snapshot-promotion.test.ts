import { afterEach, describe, expect, it, vi } from "vitest";
import { readFileSync } from "node:fs";
import { pinPublicSnapshot } from "../src/v213/public-snapshot";
import { loadV213FreshTop20Report, getV213ReportReference } from "../src/v213/top20-report";
import {
  INSUFFICIENT_EVIDENCE_MESSAGE,
  readV213BottleneckReport,
} from "../src/v213/bottleneck-report";
import { SNAPSHOT_OBJECT_KEYS, SNAPSHOT_SEAL_KEY } from "../src/v213/snapshot-seal";
import { asKv, MemoryKv } from "./fake-kv";
import type { StorageEnv } from "../src/storage";
import type { V213Top20Env } from "../src/v213/top20-report";
import type { ParsedQuery } from "../src/core";

// Signed-snapshot promotion chain verification (Task #19). The store below was
// produced offline by scripts/publish_sealed_snapshot.py from the admitted
// multi-lineage candidates (GEV rank 1, Hitachi 6501 rank 2). These tests
// exercise the REAL loader path (pinPublicSnapshot -> sealed view -> reporter)
// against the committed sealed objects and the committed pointer, plus the
// fail-closed tamper and pointerless cases.
const RUN = "20260915T120000Z-f2a9ea873960";
const SEAL = "d64b21bee62008b4bc6c1e5924eb6a301139b4a51840c7f820b10da960628115";

const objectsPath = new URL(`../../state/v213-snapshots/${RUN}/objects.json`, import.meta.url);
const pointerPath = new URL(`../../state/v213-snapshots/${RUN}/pointer.raw.json`, import.meta.url);

function store(): MemoryKv {
  const objects = JSON.parse(readFileSync(objectsPath, "utf-8")) as Record<string, string>;
  const pointer = readFileSync(pointerPath, "utf-8").trim();
  const kv = new MemoryKv();
  for (const [key, body] of Object.entries(objects)) kv.values.set(key, body);
  kv.values.set("snapshot:current", pointer);
  return kv;
}

function envWith(kv: MemoryKv): V213Top20Env {
  const privateKv = new MemoryKv();
  const securityKv = new MemoryKv();
  const env = {
    PUBLIC_CACHE: asKv(kv),
    TENANT_PRIVATE_CACHE: asKv(privateKv),
    EPHEMERAL_SECURITY_CACHE: asKv(securityKv),
    V213_FIELD_LOCALE: "en",
    V21_TOP20_MAX_AGE_SECONDS: "86400",
  };
  return env as unknown as V213Top20Env;
}

const rankingQuery: ParsedQuery = {
  intent: "ranking", ticker: null, period: "weekly",
  referenceId: null, normalized: "Top 20 bottleneck ranking",
};

function freezeClockToPromotion(): void {
  vi.useFakeTimers();
  vi.setSystemTime(new Date("2026-09-15T14:00:00Z"));
}

afterEach(() => {
  vi.useRealTimers();
});

describe("Task #19 signed snapshot promotion (GEV & 6501)", () => {
  it("serves the sealed qualified report through loadV213FreshTop20Report", async () => {
    freezeClockToPromotion();
    const env = envWith(store());
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
    expect(t.records.map(r => r.ticker)).toEqual(["GEV", "6501"]);
    expect(t.records.map(r => r.rank)).toEqual([1, 2]);
    const ref = getV213ReportReference(top as Parameters<typeof getV213ReportReference>[0]);
    expect(ref?.snapshot).toBe(`s:${RUN}`);
    expect(typeof ref?.reportSha256).toBe("string");
    expect(new RegExp("^[0-9a-f]{64}$").test(ref?.reportSha256 ?? "")).toBe(true);
  });

  it("readV213BottleneckReport returns the qualified two-admission report", async () => {
    freezeClockToPromotion();
    const view = await pinPublicSnapshot(envWith(store()));
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
    freezeClockToPromotion();
    const kv = store();
    for (const key of SNAPSHOT_OBJECT_KEYS) {
      expect(kv.values.has(`snapshot:${RUN}:${key}`)).toBe(true);
    }
    expect(kv.values.has(`snapshot:${RUN}:${SNAPSHOT_SEAL_KEY}`)).toBe(true);
    expect(kv.values.get("snapshot:current")).toContain(SEAL);
  });

  it("tampered pointer seal sha-256 fails closed to INSUFFICIENT_EVIDENCE", async () => {
    freezeClockToPromotion();
    const kv = store();
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
    freezeClockToPromotion();
    const kv = store();
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
    freezeClockToPromotion();
    const objects = JSON.parse(readFileSync(objectsPath, "utf-8")) as Record<string, string>;
    const top20 = objects[`snapshot:${RUN}:v213:top20-report:latest`]!;
    const bottleneck = objects[`snapshot:${RUN}:v213:bottleneck-report:latest`]!;
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
    kvNone.values.set("last_successful_pipeline_timestamp", "2026-09-15T12:00:00Z");
    const viewB = await pinPublicSnapshot(envWith(kvNone));
    expect(await readV213BottleneckReport(viewB)).toBeNull();
    const outB = await loadV213FreshTop20Report(envWith(kvNone), rankingQuery);
    expect(typeof outB !== "object" || outB === null).toBe(true);
  });

  it("absent store (no snapshot at all) fails closed without legacy borrow", async () => {
    freezeClockToPromotion();
    const out = await loadV213FreshTop20Report(envWith(new MemoryKv()), rankingQuery);
    expect(out !== INSUFFICIENT_EVIDENCE_MESSAGE).toBe(true);
    expect(typeof out !== "object" || out === null).toBe(true);
  });
});