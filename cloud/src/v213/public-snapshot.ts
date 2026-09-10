import type { StorageEnv } from "../storage";
import { readSealedSnapshot, SNAPSHOT_RUN_RE, SNAPSHOT_SEAL_KEY } from "./snapshot-seal";

interface SnapshotPointer { run_id?: unknown; runId?: unknown; }
export interface PublicSnapshotView {
  readonly runId: string | null;
  readonly kind: "snapshot" | "legacy" | "invalid";
  readonly integrity: "sealed" | "legacy" | "invalid";
  json<T>(logicalKeys: string[]): Promise<T | null>;
  text(logicalKeys: string[]): Promise<string | null>;
}

function invalidView(): PublicSnapshotView {
  return Object.freeze({ runId: null, kind: "invalid", integrity: "invalid",
    async json<T>() { return null as T | null; }, async text() { return null; } });
}

// Opt-in per-question cache, never keyed by the reusable Worker env/KV binding.
// The state is module-private; configuration or request text cannot supply a view.
const questionViews = new WeakMap<StorageEnv, { pending?: Promise<PublicSnapshotView> }>();
export function scopePublicSnapshot<T extends StorageEnv>(env: T): T {
  const scoped = { ...env };
  questionViews.set(scoped, {});
  return scoped;
}

export function pinPublicSnapshot(env: StorageEnv): Promise<PublicSnapshotView> {
  const state = questionViews.get(env);
  if (!state) return readPublicSnapshot(env);
  // Cache in-flight, invalid and rejected results too. No retry or scope repair
  // inside an answer; a subsequent question gets a new scope and a new read.
  return state.pending ??= readPublicSnapshot(env);
}

/** Pin related public reads. Current transaction snapshots verify all stored
 * objects first and retain exact bytes. No writes/private fallback; integrity
 * does not grant source truth, current freshness, rights or release acceptance.
 * Absent-pointer/non-transaction bootstrap compatibility remains unsealed.
 */
async function readPublicSnapshot(env: StorageEnv): Promise<PublicSnapshotView> {
  const text = await env.PUBLIC_CACHE.get("snapshot:current", "text");
  if (text !== null && (typeof text !== "string" || text.length > 2048)) return invalidView();
  let runId: string | null = null;
  if (text !== null) {
    let raw: unknown;
    try { raw = JSON.parse(text); } catch { raw = undefined; }
    if (raw && typeof raw === "object" && !Array.isArray(raw) && Object.hasOwn(raw, "schema_version")) {
      try {
        const verified = await readSealedSnapshot(text, key => env.PUBLIC_CACHE.get(key, "text"));
        return Object.freeze<PublicSnapshotView>({
          runId: verified.pointer.run_id, kind: "snapshot", integrity: "sealed",
          async text(logicalKeys) {
            for (const key of logicalKeys) {
              const body = verified.objects.get(key);
              if (body !== undefined) return body;
            }
            return null;
          },
          async json<T>(logicalKeys: string[]): Promise<T | null> {
            for (const key of logicalKeys) {
              const body = verified.objects.get(key);
              if (body !== undefined) {
                try { return JSON.parse(body) as T; } catch { return null; }
              }
            }
            return null;
          },
        });
      } catch { return invalidView(); }
    }
    const valid = (value: unknown): value is string => typeof value === "string" && /^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$/.test(value);
    if (raw === undefined) {
      if (!valid(text.trim())) return invalidView();
      runId = text.trim();
    } else {
      if (!raw || typeof raw !== "object" || Array.isArray(raw)) return invalidView();
      // Legacy pointers are flat identity controls. Keep whitespace compatibility
      // but do not let last-key-wins erase contradictory/escaped identities.
      const lexicalKeys = text.match(/"(?:[^"\\]|\\.)*"\s*:/g) ?? [];
      if (lexicalKeys.length !== Object.keys(raw).length) return invalidView();
      if (Object.keys(raw).some(key => key !== "run_id" && key !== "runId")) return invalidView();
      const value = raw as SnapshotPointer;
      const primary = Object.hasOwn(value, "run_id"); const legacy = Object.hasOwn(value, "runId");
      if (primary && legacy && value.run_id !== value.runId) return invalidView();
      const selected = primary ? value.run_id : legacy ? value.runId : undefined;
      if (!valid(selected)) return invalidView();
      runId = selected;
    }
    // Transaction-format run IDs cannot downgrade into the bootstrap path.
    // Retained old activation claims are history, not authority to synthesize a
    // missing seal. They require a fresh new transaction, not an in-place repair.
    if (SNAPSHOT_RUN_RE.test(runId)) return invalidView();
    for (const key of [SNAPSHOT_SEAL_KEY, "v213:activation-claim"]) {
      if (await env.PUBLIC_CACHE.get(`snapshot:${runId}:${key}`, "text") !== null) return invalidView();
    }
  }
  const keys = (logicalKeys: string[]) => runId === null ? [...logicalKeys] : logicalKeys.map(key => `snapshot:${runId}:${key}`);
  return Object.freeze<PublicSnapshotView>({
    runId, kind: runId === null ? "legacy" : "snapshot", integrity: "legacy",
    async json<T>(logicalKeys: string[]): Promise<T | null> {
      for (const key of keys(logicalKeys)) {
        const value = await env.PUBLIC_CACHE.get<T>(key, "json");
        if (value !== null) return value;
      }
      return null;
    },
    async text(logicalKeys: string[]): Promise<string | null> {
      for (const key of keys(logicalKeys)) {
        const value = await env.PUBLIC_CACHE.get(key, "text");
        if (value !== null) return value;
      }
      return null;
    },
  });
}

export async function publicJson<T>(env: StorageEnv, logicalKeys: string[]): Promise<T | null> {
  return (await pinPublicSnapshot(env)).json<T>(logicalKeys);
}
export async function publicText(env: StorageEnv, logicalKeys: string[]): Promise<string | null> {
  return (await pinPublicSnapshot(env)).text(logicalKeys);
}
