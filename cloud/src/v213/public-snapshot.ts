import type { StorageEnv } from "../storage";

interface SnapshotPointer { run_id?: unknown; runId?: unknown; }
export interface PublicSnapshotView {
  readonly runId: string | null;
  readonly kind: "snapshot" | "legacy" | "invalid";
  json<T>(logicalKeys: string[]): Promise<T | null>;
  text(logicalKeys: string[]): Promise<string | null>;
}

// null means truly absent; undefined means present but invalid.
async function currentSnapshotRunId(env: StorageEnv): Promise<string | null | undefined> {
  const text = await env.PUBLIC_CACHE.get("snapshot:current", "text");
  if (text === null) return null;
  const valid = (value: unknown): value is string => typeof value === "string" && /^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$/.test(value);
  let raw: unknown;
  try { raw = JSON.parse(text); }
  catch { return valid(text.trim()) ? text.trim() : undefined; } // legacy bare run ID
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) return undefined;
  const value = raw as SnapshotPointer;
  const primary = Object.prototype.hasOwnProperty.call(value, "run_id");
  const legacy = Object.prototype.hasOwnProperty.call(value, "runId");
  if (primary && legacy && value.run_id !== value.runId) return undefined;
  const runId = primary ? value.run_id : legacy ? value.runId : undefined;
  return valid(runId) ? runId : undefined;
}

/** Pin related public reads. No writes, content-hash verification or private fallback. */
export async function pinPublicSnapshot(env: StorageEnv): Promise<PublicSnapshotView> {
  const runId = await currentSnapshotRunId(env);
  const keys = (logicalKeys: string[]) => runId === undefined ? [] : runId === null
    ? [...logicalKeys] : logicalKeys.map(key => `snapshot:${runId}:${key}`);
  return Object.freeze<PublicSnapshotView>({
    runId: runId ?? null,
    kind: runId === undefined ? "invalid" : runId === null ? "legacy" : "snapshot",
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
