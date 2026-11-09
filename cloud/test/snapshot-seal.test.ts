import { describe, expect, it, vi } from "vitest";
import { buildSnapshotSeal, parseSealedPointer, readSealedSnapshot, SNAPSHOT_OBJECT_KEYS, SNAPSHOT_OPTIONAL_KEYS, SNAPSHOT_SEAL_KEY, type SnapshotSealMeta } from "../src/v213/snapshot-seal";
import { clearVerifiedLazyBodies, hasVerifiedSnapshotCustody, pinPublicSnapshot, scopePublicSnapshot } from "../src/v213/public-snapshot";
import { withAlphaVantageOwnerOnly } from "../src/v213/alpha-vantage-viewer";
import { finalizeV213Activation } from "../src/v213/activation-v3";
import { v213ReportTimesAreFresh } from "../src/v213/top20-report";
import contract from "../../config/v213-r75-publication-mode-v2.json";
import { asKv, MemoryKv } from "./fake-kv";

// Storage-integrity fixtures only. Actual admission/read caller is tested in
// v213-activation.test.ts; these arbitrary objects are NOT publication evidence.
const RUN = "20260910T100000Z-123456789abc";
const TX = "1".repeat(32);
const TIME = "2026-09-10T10:00:00Z";
const MARKET_RUN = "20260910T120000Z-abcdef123456";
const MARKET_TIME = "2026-09-10T12:00:00Z";
const RANKING_KEY = "v213:bottleneck-top20:v3";
async function digest(raw: string) {
  return Array.from(new Uint8Array(await crypto.subtle.digest("SHA-256", new TextEncoder().encode(raw))), b => b.toString(16).padStart(2, "0")).join("");
}
async function fixture() {
  const meta = { run_id: RUN, transaction_id: TX, generated_at: TIME, public_data_as_of: TIME };
  const bodies: [string, string][] = SNAPSHOT_OBJECT_KEYS.map(key => [key, JSON.stringify({ synthetic: key, marker: "📊" })]);
  bodies.find(([key]) => key === "last_successful_pipeline_timestamp")![1] = TIME;
  bodies.find(([key]) => key === "v213:activation-claim")![1] = JSON.stringify({
    schema_version: 1, run_id: RUN, transaction_id: TX,
    payload_digests: Object.fromEntries(contract.payload_names.map(key => [key, "a".repeat(64)])), claimed_at: TIME,
  });
  const seal = await buildSnapshotSeal(meta, bodies);
  const pointer = { schema_version: 2, run_id: RUN, transaction_id: TX, seal_sha256: seal.sha256,
    public_data_as_of: TIME, promoted_at: TIME, provider_scope: "public_only", owner_watchlist_inherited: false };
  const kv = new MemoryKv(); const prefix = `snapshot:${RUN}:`;
  for (const [key, body] of bodies) kv.values.set(prefix + key, body);
  kv.values.set(prefix + SNAPSHOT_SEAL_KEY, seal.text); kv.values.set("snapshot:current", JSON.stringify(pointer));
  const privateKv = new MemoryKv(); const securityKv = new MemoryKv();
  vi.spyOn(privateKv, "get").mockRejectedValue(new Error("PRIVATE_READ_FORBIDDEN"));
  vi.spyOn(securityKv, "get").mockRejectedValue(new Error("SECURITY_READ_FORBIDDEN"));
  const env = { PUBLIC_CACHE: asKv(kv), TENANT_PRIVATE_CACHE: asKv(privateKv), EPHEMERAL_SECURITY_CACHE: asKv(securityKv) };
  const rewrite = async (manifest: any) => {
    const raw = JSON.stringify(manifest); kv.values.set(prefix + SNAPSHOT_SEAL_KEY, raw);
    pointer.seal_sha256 = await digest(raw); kv.values.set("snapshot:current", JSON.stringify(pointer));
  };
  return { meta, bodies, seal, pointer, kv, env, prefix, rewrite };
}

async function reusedCoreFixture() {
  clearVerifiedLazyBodies();
  const f = await fixture();
  const ranking = JSON.stringify({ generated_at: TIME, evidence_capture_at: TIME, approval_approved_at: TIME, marker: "UNCHANGED_RANKING" });
  const oldQuotes = JSON.stringify({ generated_at: TIME, marker: "OLD_QUOTES" });
  const quotes = JSON.stringify({ generated_at: MARKET_TIME, marker: "FRESH_QUOTES" });
  const options = JSON.stringify({ generated_at: MARKET_TIME, marker: "FRESH_OPTIONS" });
  const entry = async (body: string) => ({ sha256: await digest(body), utf8_bytes: new TextEncoder().encode(body).byteLength });
  const rankingDigest = await entry(ranking);
  const oldManifest = JSON.parse(f.seal.text);
  oldManifest.objects[RANKING_KEY] = rankingDigest;
  oldManifest.objects["v213:quotes:v1"] = await entry(oldQuotes);
  f.kv.values.set(`blob:v1:${rankingDigest.sha256}`, ranking);
  f.kv.values.set(`blob:v1:${await digest(oldQuotes)}`, oldQuotes);
  await f.rewrite(oldManifest);
  const original = await pinPublicSnapshot(f.env);
  const originalRoot = f.kv.values.get(f.prefix + SNAPSHOT_SEAL_KEY);
  const meta = { ...f.meta, run_id: MARKET_RUN, generated_at: MARKET_TIME, core_run_id: RUN, ranking_persisted_at: TIME,
    product_persisted_at: { market: MARKET_TIME, prices: TIME, identity: TIME } };
  const assemblyBodies: [string, string][] = f.bodies.map(([key, body]) => [key, key === "last_successful_pipeline_timestamp" ? MARKET_TIME : body]);
  const built = await buildSnapshotSeal(meta, assemblyBodies);
  f.kv.values.set(`snapshot:${MARKET_RUN}:last_successful_pipeline_timestamp`, MARKET_TIME);
  const manifest = JSON.parse(built.text);
  manifest.objects[RANKING_KEY] = rankingDigest;
  for (const [key, body] of [["v213:quotes:v1", quotes], ["v213:options:v2", options]]) {
    manifest.objects[key!] = await entry(body!);
    f.kv.values.set(`blob:v1:${await digest(body!)}`, body!);
  }
  const pointer = { ...f.pointer, run_id: MARKET_RUN, promoted_at: MARKET_TIME };
  const rewrite = async (value: typeof manifest) => {
    const raw = JSON.stringify(value);
    f.kv.values.set(`snapshot:${MARKET_RUN}:${SNAPSHOT_SEAL_KEY}`, raw);
    pointer.seal_sha256 = await digest(raw);
    f.kv.values.set("snapshot:current", JSON.stringify(pointer));
  };
  await rewrite(manifest);
  return { ...f, meta, manifest, pointer, rewrite, original, originalRoot, ranking, rankingDigest, oldQuotes, quotes, options, assemblyBodies };
}

describe("versioned stored-object seal (not source qualification)", () => {
  it("verifies the whole set, uses immutable captured bytes, and never reads direct/private fallback", async () => {
    const { kv, env, prefix } = await fixture(); const read = vi.spyOn(kv, "get");
    const view = await pinPublicSnapshot(env);
    expect(view.integrity).toBe("sealed"); expect(view.kind).toBe("snapshot"); expect(Object.isFrozen(view)).toBe(true);
    expect(view.runId).toBe(RUN); expect(view.sealRunId).toBe(RUN);
    expect(view.sealSha256).toBe(JSON.parse(kv.values.get("snapshot:current")!).seal_sha256);
    expect(read).toHaveBeenCalledTimes(15); // pointer + manifest + 13 members
    const raw = await view.text(["reports:latest"]);
    kv.values.set(prefix + "reports:latest", "SYNTHETIC_CHANGED_AFTER_PIN");
    kv.values.set("reports:latest", "DIRECT_MUST_NOT_BE_READ");
    kv.values.set(prefix + "options:latest", "UNSEALED_MUST_NOT_BE_READ");
    kv.values.set("snapshot:current", "new-run");
    expect(await view.text(["reports:latest"])).toBe(raw);
    const parsed = await view.json<any>(["reports:latest"]); parsed.marker = "MUTATED_PARSED_OBJECT";
    expect((await view.json<any>(["reports:latest"])).marker).toBe("📊");
    expect(await view.text(["options:latest", "financial-products-candidate"])).toBeNull();
    expect(read).toHaveBeenCalledTimes(15);
  });
  it.each(SNAPSHOT_OBJECT_KEYS)("refuses altered %s before exposing any member", async key => {
    const { kv, env, prefix } = await fixture();
    kv.values.set(prefix + key, kv.values.get(prefix + key)! + " ");
    const view = await pinPublicSnapshot(env); expect(view.kind).toBe("invalid");
    expect(await view.text(["reports:latest"])).toBeNull(); expect(await view.json(["scores:latest"])).toBeNull();
  });
  it.each([...SNAPSHOT_OBJECT_KEYS, SNAPSHOT_SEAL_KEY])("refuses missing %s without repair or alternate lookup", async key => {
    const { kv, env, prefix } = await fixture(); kv.values.delete(prefix + key);
    const before = new Map(kv.values); expect((await pinPublicSnapshot(env)).kind).toBe("invalid");
    expect(kv.values).toEqual(before);
  });
  it.each(["identity", "transaction", "date", "extra", "subset", "private", "byte_length", "oversized", "bool", "swap"])("refuses %s even when the pointer hash is recomputed", async mode => {
    const { seal, env, rewrite } = await fixture(); const manifest = JSON.parse(seal.text);
    if (mode === "identity") manifest.run_id = RUN.replace("123456", "abcdef");
    if (mode === "transaction") manifest.transaction_id = "2".repeat(32);
    if (mode === "date") manifest.generated_at = "2026-02-30T10:00:00Z";
    if (mode === "extra") manifest.unreviewed_extension = true;
    if (mode === "subset") delete manifest.objects["reports:evening:latest"];
    if (mode === "private") manifest.owner_watchlist_inherited = true;
    if (mode === "byte_length") manifest.objects["reports:latest"].utf8_bytes--;
    if (mode === "oversized") manifest.objects["reports:latest"].utf8_bytes = 2097153;
    if (mode === "bool") manifest.objects["reports:latest"].utf8_bytes = true;
    if (mode === "swap") [manifest.objects["reports:latest"],manifest.objects["scores:latest"]] = [manifest.objects["scores:latest"],manifest.objects["reports:latest"]];
    await rewrite(manifest); expect((await pinPublicSnapshot(env)).kind).toBe("invalid");
  });
  it.each(["duplicate", "escaped_duplicate", "bom", "numeric_lexeme", "unknown_schema"])("refuses noncanonical or unsupported pointer %s", async mode => {
    const { kv, env } = await fixture(); let raw = kv.values.get("snapshot:current")!;
    if (mode === "duplicate") raw = raw.replace('{', '{"schema_version":2,');
    if (mode === "escaped_duplicate") raw = raw.replace('{', '{"schema_\\u0076ersion":2,');
    if (mode === "bom") raw = '\uFEFF' + raw;
    if (mode === "numeric_lexeme") raw = raw.replace('"schema_version":2', '"schema_version":2.0');
    if (mode === "unknown_schema") raw = raw.replace('"schema_version":2', '"schema_version":3');
    kv.values.set("snapshot:current", raw); expect((await pinPublicSnapshot(env)).kind).toBe("invalid");
  });
  it.each([RUN, JSON.stringify({ run_id: RUN }), JSON.stringify({ schema_version: 1, run_id: RUN })])("will not downgrade a transaction pointer into unsealed compatibility: %s", async raw => {
    const { kv, env } = await fixture(); kv.values.set("snapshot:current", raw);
    expect((await pinPublicSnapshot(env)).kind).toBe("invalid");
  });
  it("rejects a substituted claim even after recomputing both object and manifest digests", async () => {
    const { kv, env, prefix, seal, rewrite } = await fixture();
    const manifest = JSON.parse(seal.text); const value = JSON.parse(kv.values.get(prefix + "v213:activation-claim")!);
    value.transaction_id = "2".repeat(32); const raw = JSON.stringify(value);
    kv.values.set(prefix + "v213:activation-claim", raw);
    manifest.objects["v213:activation-claim"] = { sha256: await digest(raw), utf8_bytes: new TextEncoder().encode(raw).byteLength };
    await rewrite(manifest); expect((await pinPublicSnapshot(env)).kind).toBe("invalid");
  });
  it("bounds UTF-8, total size and malformed strings before storage effects", async () => {
    const { meta, bodies } = await fixture();
    const invalid = bodies.map(([k,v]) => [k,v] as [string,string]);
    invalid[0]![1] = "x".repeat(2097153); await expect(buildSnapshotSeal(meta, invalid)).rejects.toThrow("V213_SNAPSHOT_SEAL_INVALID");
    invalid[0]![1] = "\ud800"; await expect(buildSnapshotSeal(meta, invalid)).rejects.toThrow("V213_SNAPSHOT_SEAL_INVALID");
    for (let i=0; i<5; i++) invalid[i]![1] = "x".repeat(2097152);
    await expect(buildSnapshotSeal(meta, invalid)).rejects.toThrow("V213_SNAPSHOT_SEAL_INVALID");
    await expect(buildSnapshotSeal({ ...meta, private_extension: true } as any, bodies)).rejects.toThrow("V213_SNAPSHOT_SEAL_INVALID");
  });
  it("captures caller inputs before async hashing", async () => {
    const { meta, bodies, seal } = await fixture(); const pending = buildSnapshotSeal(meta, bodies);
    bodies[1]![1] = "MUTATED_AFTER_CALL"; meta.run_id = "OTHER";
    expect(await pending).toEqual(seal);
  });
  it("rejects transport failures without exposing a partial verified view", async () => {
    const { kv, env } = await fixture(); vi.spyOn(kv, "get").mockRejectedValueOnce(new Error("SYNTHETIC_TRANSPORT"));
    await expect(pinPublicSnapshot(env)).rejects.toThrow("SYNTHETIC_TRANSPORT"); // pointer fetch itself still propagates to caller boundary
    vi.mocked(kv.get).mockRestore();
    const get = kv.get.bind(kv);
    vi.spyOn(kv, "get").mockImplementation(async (key: string, type?: "text"|"json") => {
      if (key.endsWith("source_views:latest")) throw new Error("SYNTHETIC_TRANSPORT");
      return get(key,type);
    });
    expect((await pinPublicSnapshot(env)).kind).toBe("invalid");
  });
  it("keeps pointer fields immutable", async () => {
    const { kv } = await fixture(); expect(Object.isFrozen(parseSealedPointer(kv.values.get("snapshot:current")!))).toBe(true);
  });

  it("reads a market-only root from the unchanged core and ranking digest, with independently fresh lazy markets", async () => {
    const f = await reusedCoreFixture();
    const before = new Map(f.kv.values);
    const get = vi.spyOn(f.kv, "get"); const put = vi.spyOn(f.kv, "put");
    const view = await pinPublicSnapshot(f.env);
    expect(view.integrity).toBe("sealed"); expect(view.runId).toBe(RUN);
    expect(view.sealRunId).toBe(MARKET_RUN); expect(f.original.sealRunId).toBe(RUN);
    expect(view.sealSha256).toBe(f.pointer.seal_sha256);
    expect(view.sealedDigest!(RANKING_KEY)).toEqual(f.original.sealedDigest!(RANKING_KEY));
    expect(await view.text([RANKING_KEY])).toBe(f.ranking);
    expect(await view.text(["v213:quotes:v1"])).toBe(f.quotes);
    expect(await view.text(["v213:options:v2"])).toBe(f.options);
    expect(await view.text(["v213:activation-claim"])).toBe(f.bodies.find(([key]) => key === "v213:activation-claim")![1]);
    expect(await view.text(["last_successful_pipeline_timestamp"])).toBe(MARKET_TIME);
    expect(f.pointer.public_data_as_of).toBe(TIME);
    expect(f.kv.values.get(f.prefix + "last_successful_pipeline_timestamp")).toBe(TIME);
    expect(JSON.parse((await view.text([RANKING_KEY]))!)).toMatchObject({
      generated_at: TIME, evidence_capture_at: TIME, approval_approved_at: TIME,
    });
    expect(f.kv.values.get(f.prefix + SNAPSHOT_SEAL_KEY)).toBe(f.originalRoot);
    expect(get.mock.calls.map(([key]) => key)).toContain(`snapshot:${MARKET_RUN}:${SNAPSHOT_SEAL_KEY}`);
    expect(get.mock.calls.map(([key]) => key)).not.toContain(f.prefix + "last_successful_pipeline_timestamp");
    expect(get.mock.calls.map(([key]) => key)).not.toContain(`blob:v1:${await digest(f.oldQuotes)}`);
    expect(get.mock.calls.map(([key]) => key).filter(key => key.startsWith(`snapshot:${MARKET_RUN}:`)))
      .toEqual([`snapshot:${MARKET_RUN}:${SNAPSHOT_SEAL_KEY}`, `snapshot:${MARKET_RUN}:last_successful_pipeline_timestamp`]);
    expect(put).not.toHaveBeenCalled(); expect(f.kv.values).toEqual(before);
    const verified = await readSealedSnapshot(f.kv.values.get("snapshot:current")!, key => f.kv.get(key, "text"));
    expect(verified.pointer.run_id).toBe(MARKET_RUN); expect(verified.coreRunId).toBe(RUN);
  });

  it("keeps actual pipeline liveness independent from unchanged data, report, claim and approval dates", async () => {
    const f = await reusedCoreFixture();
    const view = await pinPublicSnapshot(f.env);
    const liveness = await view.text(["last_successful_pipeline_timestamp"]);
    const observedAt = Date.parse(MARKET_TIME) + 3600_000;
    const env = { V21_TOP20_MAX_AGE_SECONDS: "7200" };
    expect(liveness).toBe(MARKET_TIME);
    expect(f.pointer.public_data_as_of).toBe(TIME);
    expect(JSON.parse((await view.text([RANKING_KEY]))!)).toMatchObject({
      generated_at: TIME, evidence_capture_at: TIME, approval_approved_at: TIME,
    });
    expect(JSON.parse((await view.text(["v213:activation-claim"]))!).claimed_at).toBe(TIME);
    expect(v213ReportTimesAreFresh(env, liveness, [TIME], observedAt)).toBe(true);
    expect(v213ReportTimesAreFresh(env, TIME, [TIME], observedAt)).toBe(false);
    const expiredReportAt = Date.parse(TIME) + 86401_000;
    expect(v213ReportTimesAreFresh(env, new Date(expiredReportAt).toISOString(), [TIME], expiredReportAt)).toBe(false);
    await expect(buildSnapshotSeal(f.meta, f.bodies)).rejects.toThrow("V213_SNAPSHOT_SEAL_INVALID");
  });

  it.each(["missing", "length", "sha256", "old_clock"])("rejects %s global liveness without borrowing the old core marker", async mode => {
    const f = await reusedCoreFixture();
    const key = `snapshot:${MARKET_RUN}:last_successful_pipeline_timestamp`;
    if (mode === "missing") f.kv.values.delete(key);
    else if (mode === "length") f.kv.values.set(key, MARKET_TIME + " ");
    else if (mode === "sha256") f.kv.values.set(key, MARKET_TIME.replace("12:00", "11:00"));
    else {
      f.kv.values.set(key, TIME);
      f.manifest.objects.last_successful_pipeline_timestamp = { sha256: await digest(TIME), utf8_bytes: new TextEncoder().encode(TIME).byteLength };
      await f.rewrite(f.manifest);
    }
    const before = new Map(f.kv.values);
    expect(f.kv.values.get(f.prefix + "last_successful_pipeline_timestamp")).toBe(TIME);
    expect((await pinPublicSnapshot(f.env)).kind).toBe("invalid");
    expect(f.kv.values).toEqual(before);
  });

  it("advances a genuinely new lazy ranking/binding without relabeling retained core authority or product clocks", async () => {
    const f = await reusedCoreFixture();
    const productClocks = { market: TIME, prices: TIME, identity: TIME };
    const built = await buildSnapshotSeal({ ...f.meta, ranking_persisted_at: MARKET_TIME, product_persisted_at: productClocks }, f.assemblyBodies);
    const manifest = JSON.parse(built.text);
    const original = JSON.parse(f.originalRoot!);
    manifest.objects["v213:quotes:v1"] = original.objects["v213:quotes:v1"];
    const ranking = JSON.stringify({ generated_at: MARKET_TIME, evidence_capture_at: TIME, approval_approved_at: TIME, marker: "NEW_RANKING" });
    const binding = JSON.stringify({ generated_at: MARKET_TIME, marker: "NEW_BINDING_NOT_ADMISSION_EVIDENCE" });
    for (const [logical, body] of [[RANKING_KEY, ranking], ["v213:revenue-guidance-binding:v1", binding]]) {
      const hash = await digest(body!);
      manifest.objects[logical!] = { sha256: hash, utf8_bytes: new TextEncoder().encode(body!).byteLength };
      f.kv.values.set(`blob:v1:${hash}`, body!);
    }
    await f.rewrite(manifest);
    const view = await pinPublicSnapshot(f.env);
    expect(view.integrity).toBe("sealed"); expect(view.runId).toBe(RUN); expect(view.sealRunId).toBe(MARKET_RUN);
    expect(view.sealedDigest!(RANKING_KEY)?.sha256).not.toBe(f.rankingDigest.sha256);
    expect(await view.text([RANKING_KEY])).toBe(ranking);
    expect(await view.text(["v213:revenue-guidance-binding:v1"])).toBe(binding);
    expect(await view.text(["v213:quotes:v1"])).toBe(f.oldQuotes);
    expect(manifest.ranking_persisted_at).toBe(MARKET_TIME);
    expect(manifest.product_persisted_at).toEqual(productClocks);
    for (const [logical, body] of f.bodies) {
      expect(await view.text([logical])).toBe(logical === "last_successful_pipeline_timestamp" ? MARKET_TIME : body);
      expect(f.kv.values.get(f.prefix + logical)).toBe(body);
    }
    expect(f.kv.values.get(f.prefix + SNAPSHOT_SEAL_KEY)).toBe(f.originalRoot);
  });

  it("distinguishes two verified seals with the same global/core IDs by exact hash, and keeps the pinned audit identity immutable", async () => {
    const f = await reusedCoreFixture();
    const first = await pinPublicSnapshot(f.env);
    const firstHash = f.pointer.seal_sha256;
    f.manifest.product_persisted_at.identity = MARKET_TIME;
    await f.rewrite(f.manifest);
    const second = await pinPublicSnapshot(f.env);
    expect(second.integrity).toBe("sealed");
    expect(second.runId).toBe(first.runId); expect(second.sealRunId).toBe(first.sealRunId);
    expect(first.sealSha256).toBe(firstHash);
    expect(second.sealSha256).toBe(f.pointer.seal_sha256);
    expect(second.sealSha256).not.toBe(first.sealSha256);
    expect(hasVerifiedSnapshotCustody({ ...second }, RANKING_KEY)).toBe(false);
  });

  it("retains only real-reader custody through the friend wrapper, without allowing wrappers or spreads to repair it", async () => {
    const f = await reusedCoreFixture();
    const owner = await pinPublicSnapshot(f.env);
    const friend = await pinPublicSnapshot(scopePublicSnapshot(f.env, "friend"));
    expect(friend.runId).toBe(RUN);
    expect(friend.sealRunId).toBe(MARKET_RUN);
    expect(friend.sealSha256).toBe(f.pointer.seal_sha256); expect(owner.sealSha256).toBe(friend.sealSha256);
    expect(hasVerifiedSnapshotCustody(owner, RANKING_KEY)).toBe(true);
    expect(hasVerifiedSnapshotCustody(friend, RANKING_KEY)).toBe(true);
    expect(hasVerifiedSnapshotCustody({ ...owner }, RANKING_KEY)).toBe(false);
    expect(hasVerifiedSnapshotCustody(withAlphaVantageOwnerOnly(owner), RANKING_KEY)).toBe(false);
    f.kv.values.delete(f.prefix + "scores:latest");
    const before = new Map(f.kv.values);
    const invalid = await pinPublicSnapshot(scopePublicSnapshot(f.env, "friend"));
    expect(invalid.kind).toBe("invalid"); expect(hasVerifiedSnapshotCustody(invalid, RANKING_KEY)).toBe(false);
    expect(invalid.sealRunId).toBeUndefined();
    expect(invalid.sealSha256).toBeUndefined();
    expect(f.kv.values).toEqual(before);
  });

  it.each(["core_only", "clock_only", "bad_core", "newline_core", "null_core", "bad_clock", "future_clock", "wrong_root", "wrong_core", "no_pair",
    "wrong_transaction", "renewed_claim", "renewed_claim_time", "renewed_data", "bad_product", "array_product", "extra_product", "future_product",
    "bad_product_time", "boolean_product"])("refuses reused-core metadata/identity corruption: %s", async mode => {
    const f = await reusedCoreFixture(); const manifest = f.manifest;
    if (mode === "core_only") delete manifest.ranking_persisted_at;
    if (mode === "clock_only") delete manifest.core_run_id;
    if (mode === "bad_core") manifest.core_run_id = "not-a-run";
    if (mode === "newline_core") manifest.core_run_id = RUN + "\n";
    if (mode === "null_core") manifest.core_run_id = null;
    if (mode === "bad_clock") manifest.ranking_persisted_at = "2026-02-30T10:00:00Z";
    if (mode === "future_clock") manifest.ranking_persisted_at = "2026-09-10T13:00:00Z";
    if (mode === "wrong_root") manifest.run_id = RUN;
    if (mode === "wrong_core") {
      manifest.core_run_id = MARKET_RUN;
      for (const [key, body] of f.bodies) if (key !== "last_successful_pipeline_timestamp") f.kv.values.set(`snapshot:${MARKET_RUN}:${key}`, body);
    }
    if (mode === "no_pair") { delete manifest.core_run_id; delete manifest.ranking_persisted_at; }
    if (mode === "wrong_transaction") { manifest.transaction_id = "2".repeat(32); f.pointer.transaction_id = manifest.transaction_id; }
    if (mode === "renewed_claim" || mode === "renewed_claim_time") {
      const claim = JSON.parse(f.kv.values.get(f.prefix + "v213:activation-claim")!);
      if (mode === "renewed_claim") claim.run_id = MARKET_RUN; else claim.claimed_at = MARKET_TIME;
      const body = JSON.stringify(claim); f.kv.values.set(f.prefix + "v213:activation-claim", body);
      manifest.objects["v213:activation-claim"] = { sha256: await digest(body), utf8_bytes: new TextEncoder().encode(body).byteLength };
    }
    if (mode === "renewed_data") { manifest.public_data_as_of = MARKET_TIME; f.pointer.public_data_as_of = MARKET_TIME; }
    if (mode === "bad_product") manifest.product_persisted_at = null;
    if (mode === "array_product") manifest.product_persisted_at = [];
    if (mode === "extra_product") manifest.product_persisted_at.extra = TIME;
    if (mode === "future_product") manifest.product_persisted_at.market = "2026-09-10T13:00:00Z";
    if (mode === "bad_product_time") manifest.product_persisted_at.market = "2026-09-10";
    if (mode === "boolean_product") manifest.product_persisted_at.market = true;
    await f.rewrite(manifest);
    const before = new Map(f.kv.values);
    expect((await pinPublicSnapshot(f.env)).kind).toBe("invalid");
    expect(f.kv.values).toEqual(before);
  });

  it.each(["reports:latest", "v213:activation-claim"])("never falls back to a global-run clone when core %s is missing", async key => {
    const f = await reusedCoreFixture(); const body = f.kv.values.get(f.prefix + key)!;
    f.kv.values.delete(f.prefix + key); f.kv.values.set(`snapshot:${MARKET_RUN}:${key}`, body);
    expect((await pinPublicSnapshot(f.env)).kind).toBe("invalid");
  });

  it.each(["length", "sha256"])("still verifies the complete reused eager core's %s before returning any member", async mode => {
    const f = await reusedCoreFixture();
    const body = f.kv.values.get(f.prefix + "reports:evening:latest")!;
    f.kv.values.set(f.prefix + "reports:evening:latest", mode === "length" ? body + " " : body.replace("📊", "📈"));
    const view = await pinPublicSnapshot(f.env);
    expect(view.kind).toBe("invalid"); expect(await view.text(["scores:latest"])).toBeNull();
  });

  it.each(["missing", "length", "sha256"])("refuses a %s fresh lazy body without borrowing an old market blob", async mode => {
    const f = await reusedCoreFixture();
    const key = `blob:v1:${await digest(f.quotes)}`;
    if (mode === "missing") f.kv.values.delete(key);
    else f.kv.values.set(key, mode === "length" ? f.quotes + " " : f.quotes.replace("FRESH", "WRONG"));
    const view = await pinPublicSnapshot(f.env);
    expect(view.integrity).toBe("sealed"); expect(await view.text(["v213:quotes:v1"])).toBeNull();
    expect(await view.text([RANKING_KEY])).toBe(f.ranking);
  });

  it("builds exact optional metadata and optional eager core, snapshots nested clocks, and preserves ordinary seal bytes", async () => {
    const f = await fixture();
    expect(await buildSnapshotSeal(f.meta, f.bodies)).toEqual(f.seal);
    const meta = { ...f.meta, core_run_id: RUN, ranking_persisted_at: TIME, product_persisted_at: { market: TIME } };
    const expected = await buildSnapshotSeal(meta, f.bodies);
    const pending = buildSnapshotSeal(meta, f.bodies); meta.product_persisted_at.market = MARKET_TIME;
    expect(await pending).toEqual(expected);
    expect(JSON.parse(expected.text)).toMatchObject({ core_run_id: RUN, ranking_persisted_at: TIME, product_persisted_at: { market: TIME } });
    const optional: [string, string][] = [...f.bodies, [SNAPSHOT_OPTIONAL_KEYS[0], '{"synthetic":"macro"}']];
    expect(Object.keys(JSON.parse((await buildSnapshotSeal(f.meta, optional)).text).objects)).toHaveLength(14);
    for (const invalid of [{ core_run_id: RUN }, { ranking_persisted_at: TIME },
      { core_run_id: "wrong", ranking_persisted_at: TIME },
      { core_run_id: RUN, ranking_persisted_at: MARKET_TIME }, { product_persisted_at: null },
      { product_persisted_at: { extra: TIME } }, { product_persisted_at: { market: MARKET_TIME } }]) {
      // Intentionally invalid runtime metadata exercises the builder's boundary.
      const invalidMeta = { ...f.meta, ...invalid } as unknown as SnapshotSealMeta;
      await expect(buildSnapshotSeal(invalidMeta, f.bodies)).rejects.toThrow("V213_SNAPSHOT_SEAL_INVALID");
    }
    expect(JSON.parse((await buildSnapshotSeal({ ...f.meta, product_persisted_at: {} }, f.bodies)).text).product_persisted_at).toEqual({});
  });

  it("does not turn a market-only seal into a newly finalized activation or renew the original recovery journal", async () => {
    const f = await reusedCoreFixture(); const privateKv = new MemoryKv();
    const key = `v213:activation-rollback:${TX}`;
    privateKv.values.set(key, JSON.stringify({ schema_version: 2, transaction_id: TX, run_id: RUN,
      previous_pointer: null, previous_run_id: null, created_at: TIME }));
    const env = { ...f.env, TENANT_PRIVATE_CACHE: asKv(privateKv) };
    const before = new Map(privateKv.values); const pub = new Map(f.kv.values);
    await expect(finalizeV213Activation(JSON.stringify({ schema_version: 1, transaction_id: TX, run_id: RUN }), env))
      .rejects.toThrow("V213_ACTIVATION_FINALIZE_POINTER_MISMATCH");
    await expect(finalizeV213Activation(JSON.stringify({ schema_version: 1, transaction_id: TX, run_id: MARKET_RUN }), env))
      .rejects.toThrow("V213_ACTIVATION_ROLLBACK_STATE_INVALID");
    expect(privateKv.values).toEqual(before); expect(f.kv.values).toEqual(pub);
  });
});
