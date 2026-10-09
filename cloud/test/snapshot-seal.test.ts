import { describe, expect, it, vi } from "vitest";
import { buildSnapshotSeal, parseSealedPointer, SNAPSHOT_OBJECT_KEYS, SNAPSHOT_SEAL_KEY } from "../src/v213/snapshot-seal";
import { pinPublicSnapshot } from "../src/v213/public-snapshot";
import contract from "../../config/v213-r75-publication-mode-v1.json";
import { asKv, MemoryKv } from "./fake-kv";

// Storage-integrity fixtures only. Actual admission/read caller is tested in
// v213-activation.test.ts; these arbitrary objects are NOT publication evidence.
const RUN = "20260910T100000Z-123456789abc";
const TX = "1".repeat(32);
const TIME = "2026-09-10T10:00:00Z";
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

describe("versioned stored-object seal (not source qualification)", () => {
  it("verifies the whole set, uses immutable captured bytes, and never reads direct/private fallback", async () => {
    const { kv, env, prefix } = await fixture(); const read = vi.spyOn(kv, "get");
    const view = await pinPublicSnapshot(env);
    expect(view.integrity).toBe("sealed"); expect(view.kind).toBe("snapshot"); expect(Object.isFrozen(view)).toBe(true);
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
});
