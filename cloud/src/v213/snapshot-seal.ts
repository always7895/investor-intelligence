/** Exact stored-object integrity for the active publication path.
 * The trusted pointer anchors these hashes; this is not source authenticity,
 * rights, freshness, a signature against a compromised KV writer, or a KV lock.
 */
import contract from "../../../config/v213-r75-publication-mode-v1.json";

export const SNAPSHOT_SEAL_KEY = "v213:snapshot-seal:v1";
export const SNAPSHOT_RUN_RE = /^\d{8}T\d{6}Z-[0-9a-f]{12}$/;
export const SNAPSHOT_OBJECT_KEYS = [
  "v21:top20:latest", "scores:latest", "source_views:latest", "source_plan:latest",
  "reports:latest", "reports:morning:latest", "reports:evening:latest",
  "last_successful_pipeline_timestamp", "v212:top20-report:latest", "v213:top20-report:latest",
  "v213:source-federation:latest", "v213:source-independence:latest", "v213:activation-claim",
] as const;

/** Optional sealed payloads added after the 13-key core; manifests may carry
 *  the core alone (historical runs) or core + the macro industry artifact. */
export const SNAPSHOT_OPTIONAL_KEYS = ["v213:macro-industry:latest"] as const;
/** Lazy sealed payloads: listed in the manifest with their digest, stored once under the content-addressed key
 *  `blob:v1:<sha256>` and verified only when a reader asks for them (identity shards, quotes, options). They never
 *  count toward the eager read of every question and are re-written only when their bytes change. */
export const SNAPSHOT_LAZY_KEY_RE = /^v213:(?:identity:v2:(?:sym:[A-Z0-9_]|name:(?:1[0-5]|[0-9]))|quotes:v1|options:v1|bottleneck-top20:v3)$/;
export const SNAPSHOT_LAZY_BLOB_PREFIX = "blob:v1:";
const MAX_LAZY_KEYS = 64;
const MAX_LAZY_TOTAL = 33_554_432;
const MAX_MANIFEST = 32_768;
const ENCODER = new TextEncoder();
const HEX = /^[0-9a-f]{64}$/;
const TRANSACTION = /^[0-9a-f]{32}$/;
const MAX_OBJECT = 2_097_152;
const MAX_TOTAL = 8_388_608;
const CONTRACT = "v213-stored-snapshot-v1";
export interface LazyObjectDigest { readonly sha256: string; readonly utf8_bytes: number; }
export interface SnapshotSealMeta {
  run_id: string; transaction_id: string; generated_at: string; public_data_as_of: string;
}
interface ObjectDigest { sha256: string; utf8_bytes: number; }
interface SnapshotSeal extends SnapshotSealMeta {
  schema_version: 1; contract_id: typeof CONTRACT;
  provider_scope: "public_only"; owner_watchlist_inherited: false;
  objects: Record<string, ObjectDigest>;
}
export interface SealedPointer {
  schema_version: 2; run_id: string; transaction_id: string; seal_sha256: string;
  public_data_as_of: string; promoted_at: string;
  provider_scope: "public_only"; owner_watchlist_inherited: false;
}
function requireSeal(ok: unknown): asserts ok {
  if (!ok) throw new Error("V213_SNAPSHOT_SEAL_INVALID");
}
function object(value: unknown): Record<string, unknown> {
  requireSeal(value && typeof value === "object" && !Array.isArray(value));
  return value as Record<string, unknown>;
}
function keys(value: Record<string, unknown>, expected: readonly string[]): void {
  requireSeal(Object.keys(value).length === expected.length && expected.every(key => Object.hasOwn(value, key)));
}
function time(raw: unknown): raw is string {
  if (typeof raw !== "string" || !/^(?!0000)\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d{3})?Z$/.test(raw)) return false;
  const n = Date.parse(raw);
  return Number.isFinite(n) && new Date(n).toISOString() === (raw.includes(".") ? raw : raw.replace("Z", ".000Z"));
}
function bytes(raw: string, limit: number): Uint8Array<ArrayBuffer> {
  requireSeal(typeof raw === "string" && raw.length > 0 && raw.length <= limit);
  const value = ENCODER.encode(raw);
  requireSeal(value.byteLength <= limit && new TextDecoder("utf-8", { fatal: true }).decode(value) === raw);
  return value;
}
async function sha(raw: string, limit = MAX_OBJECT): Promise<string> {
  const digest = await crypto.subtle.digest("SHA-256", bytes(raw, limit));
  return Array.from(new Uint8Array(digest), b => b.toString(16).padStart(2, "0")).join("");
}
function control(raw: string, limit: number): Record<string, unknown> {
  bytes(raw, limit);
  let value: unknown;
  try { value = JSON.parse(raw); } catch { throw new Error("V213_SNAPSHOT_SEAL_INVALID"); }
  // Controls are emitted by JSON.stringify in this Worker. Trimmed exact
  // spelling tolerates transport-level leading/trailing whitespace (e.g.
  // CRLF from a local writer's put) while STILL rejecting duplicate/escaped
  // duplicate keys, BOM, numeric coercion, overflow, extra keys and any inner
  // reordering: whitespace may only exist OUTSIDE the serialized object.
  requireSeal(raw.trim() === JSON.stringify(value));
  return object(value);
}
function meta(value: Record<string, unknown>): void {
  requireSeal(typeof value.run_id === "string" && SNAPSHOT_RUN_RE.test(value.run_id)
    && typeof value.transaction_id === "string" && TRANSACTION.test(value.transaction_id)
    && time(value.generated_at) && time(value.public_data_as_of)
    && Date.parse(value.public_data_as_of) <= Date.parse(value.generated_at) + 300_000);
}
function claim(raw: string, expected: SnapshotSealMeta): void {
  const value = control(raw, 8192);
  keys(value, ["schema_version", "transaction_id", "run_id", "payload_digests", "claimed_at"]);
  requireSeal(value.schema_version === 1 && value.run_id === expected.run_id
    && value.transaction_id === expected.transaction_id && time(value.claimed_at));
  const digests = object(value.payload_digests); keys(digests, contract.payload_names);
  requireSeal(Object.values(digests).every(item => typeof item === "string" && HEX.test(item)));
}
export function parseSealedPointer(raw: string): SealedPointer {
  const value = control(raw, 2048);
  keys(value, ["schema_version", "run_id", "transaction_id", "seal_sha256", "public_data_as_of", "promoted_at", "provider_scope", "owner_watchlist_inherited"]);
  requireSeal(value.schema_version === 2 && typeof value.run_id === "string" && SNAPSHOT_RUN_RE.test(value.run_id)
    && typeof value.transaction_id === "string" && TRANSACTION.test(value.transaction_id)
    && typeof value.seal_sha256 === "string" && HEX.test(value.seal_sha256)
    && time(value.public_data_as_of) && time(value.promoted_at)
    && value.provider_scope === "public_only" && value.owner_watchlist_inherited === false);
  return Object.freeze(value) as unknown as SealedPointer;
}
export async function buildSnapshotSeal(metadata: SnapshotSealMeta, supplied: readonly [string, string][]): Promise<{ text: string; sha256: string }> {
  const expected = { ...metadata };
  keys(expected, ["run_id", "transaction_id", "generated_at", "public_data_as_of"]); meta(expected);
  const entries = supplied.map(([key, body]) => [key, body] as [string, string]);
  const allowed: string[] = [...SNAPSHOT_OBJECT_KEYS, ...SNAPSHOT_OPTIONAL_KEYS];
  requireSeal(entries.length === SNAPSHOT_OBJECT_KEYS.length || entries.length === allowed.length);
  requireSeal(entries.every(([key]) => allowed.includes(key)));
  const bodies = Object.fromEntries(entries); keys(bodies, SNAPSHOT_OBJECT_KEYS);
  claim(bodies["v213:activation-claim"]!, expected);
  requireSeal(bodies.last_successful_pipeline_timestamp === expected.public_data_as_of);
  const manifestKeys = SNAPSHOT_OPTIONAL_KEYS.filter((key) => key in bodies);
  requireSeal(manifestKeys.length === 0 || manifestKeys.length === SNAPSHOT_OPTIONAL_KEYS.length);
  let total = 0;
  const digests: Record<string, ObjectDigest> = {};
  for (const key of [...SNAPSHOT_OBJECT_KEYS, ...manifestKeys]) {
    const raw = bodies[key]!; const size = bytes(raw, MAX_OBJECT).byteLength;
    total += size; requireSeal(total <= MAX_TOTAL);
    digests[key] = { sha256: await sha(raw), utf8_bytes: size };
  }
  const manifest: SnapshotSeal = { schema_version: 1, contract_id: CONTRACT, ...expected,
    provider_scope: "public_only", owner_watchlist_inherited: false, objects: digests };
  const text = JSON.stringify(manifest);
  return { text, sha256: await sha(text, 8192) };
}
export async function readSealedSnapshot(rawPointer: string, get: (key: string) => Promise<string | null>): Promise<{
  pointer: SealedPointer; objects: ReadonlyMap<string, string>; lazy: ReadonlyMap<string, LazyObjectDigest>;
}> {
  const pointer = parseSealedPointer(rawPointer);
  const prefix = `snapshot:${pointer.run_id}:`;
  const raw = await get(prefix + SNAPSHOT_SEAL_KEY); requireSeal(raw !== null);
  requireSeal(await sha(raw, MAX_MANIFEST) === pointer.seal_sha256);
  const manifest = control(raw, MAX_MANIFEST);
  keys(manifest, ["schema_version", "contract_id", "run_id", "transaction_id", "generated_at", "public_data_as_of", "provider_scope", "owner_watchlist_inherited", "objects"]);
  meta(manifest);
  requireSeal(manifest.schema_version === 1 && manifest.contract_id === CONTRACT
    && manifest.run_id === pointer.run_id && manifest.transaction_id === pointer.transaction_id
    && manifest.public_data_as_of === pointer.public_data_as_of
    && manifest.provider_scope === "public_only" && manifest.owner_watchlist_inherited === false);
  const allDefinitions = object(manifest.objects);
  const lazy = new Map<string, LazyObjectDigest>();
  let lazyTotal = 0;
  const definitions: Record<string, unknown> = {};
  for (const [key, value] of Object.entries(allDefinitions)) {
    if (!SNAPSHOT_LAZY_KEY_RE.test(key)) { definitions[key] = value; continue; }
    const entry = object(value); keys(entry, ["sha256", "utf8_bytes"]);
    requireSeal(typeof entry.sha256 === "string" && HEX.test(entry.sha256)
      && typeof entry.utf8_bytes === "number" && Number.isSafeInteger(entry.utf8_bytes)
      && entry.utf8_bytes > 0 && entry.utf8_bytes <= MAX_OBJECT);
    lazyTotal += entry.utf8_bytes;
    requireSeal(lazyTotal <= MAX_LAZY_TOTAL);
    lazy.set(key, Object.freeze({ sha256: entry.sha256, utf8_bytes: entry.utf8_bytes }));
  }
  requireSeal(lazy.size <= MAX_LAZY_KEYS);
  const definedKeys = Object.keys(definitions);
  const allowedDef = SNAPSHOT_OPTIONAL_KEYS.every((k) => typeof k === "string");
  requireSeal(allowedDef);
  requireSeal(definedKeys.length === SNAPSHOT_OBJECT_KEYS.length || definedKeys.length === SNAPSHOT_OBJECT_KEYS.length + SNAPSHOT_OPTIONAL_KEYS.length);
  requireSeal(definedKeys.every((k) =>
    SNAPSHOT_OBJECT_KEYS.includes(k as (typeof SNAPSHOT_OBJECT_KEYS)[number])
      || SNAPSHOT_OPTIONAL_KEYS.includes(k as (typeof SNAPSHOT_OPTIONAL_KEYS)[number])));
  const presentKeys: string[] = [...SNAPSHOT_OBJECT_KEYS, ...SNAPSHOT_OPTIONAL_KEYS.filter((k) => k in definitions)];
  let total = 0;
  for (const key of presentKeys) {
    const entry = object(definitions[key]); keys(entry, ["sha256", "utf8_bytes"]);
    requireSeal(typeof entry.sha256 === "string" && HEX.test(entry.sha256)
      && typeof entry.utf8_bytes === "number" && Number.isSafeInteger(entry.utf8_bytes)
      && entry.utf8_bytes > 0 && entry.utf8_bytes <= MAX_OBJECT);
    total += entry.utf8_bytes; requireSeal(total <= MAX_TOTAL);
  }
  const objects = new Map<string, string>();
  // Read/verify the whole bounded set before exposing any member. Keep these
  // exact bytes for this view; do not fetch them again while constructing an answer.
  for (const key of presentKeys) {
    const body = await get(prefix + key); requireSeal(body !== null);
    const entry = definitions[key] as unknown as ObjectDigest;
    requireSeal(bytes(body, MAX_OBJECT).byteLength === entry.utf8_bytes && await sha(body) === entry.sha256);
    objects.set(key, body);
  }
  claim(objects.get("v213:activation-claim")!, manifest as unknown as SnapshotSealMeta);
  requireSeal(objects.get("last_successful_pipeline_timestamp") === pointer.public_data_as_of);
  return { pointer, objects, lazy };
}

/** Exact bytes of one lazy sealed object, or null when absent, oversized or not matching its sealed digest. */
export async function readLazySealedObject(digest: LazyObjectDigest, get: (key: string) => Promise<string | null>): Promise<string | null> {
  try {
    const body = await get(SNAPSHOT_LAZY_BLOB_PREFIX + digest.sha256);
    if (body === null || bytes(body, MAX_OBJECT).byteLength !== digest.utf8_bytes) return null;
    return (await sha(body)) === digest.sha256 ? body : null;
  } catch {
    return null;
  }
}
