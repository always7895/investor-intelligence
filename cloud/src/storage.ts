import {
  decryptTenantJson,
  encryptTenantJson,
  tenantDataEncryptionKey,
  type SecurityEnv,
} from "./security";

/**
 * Storage is deliberately split across independent Cloudflare KV namespaces.
 * PUBLIC_CACHE never receives tenant identifiers. TENANT_PRIVATE_CACHE never
 * receives shared snapshots. Webhook dedupe, rate limiting and deletion epochs
 * live in EPHEMERAL_SECURITY_CACHE.
 */
export interface StorageEnv extends SecurityEnv {
  PUBLIC_CACHE: KVNamespace;
  TENANT_PRIVATE_CACHE: KVNamespace;
  EPHEMERAL_SECURITY_CACHE: KVNamespace;
  MEMORY_FEATURE_AVAILABLE?: string;
  PRIVATE_MEMORY_MAX_TTL_SECONDS?: string;
  JOB_RESULT_TTL_SECONDS?: string;
  TENANT_DELETION_EPOCH_TTL_SECONDS?: string;
}

export interface ConversationMessage {
  role: "user" | "assistant";
  content: string;
  timestamp: string;
}

export interface JobRecord {
  status: "pending" | "complete" | "error";
  createdAt: string;
  completedAt?: string;
  result?: string;
  errorCode?: string;
}

interface SnapshotPointer {
  run_id?: string;
  runId?: string;
}

const INITIAL_TENANT_EPOCH = "0";
const TENANT_EPOCH_RE = /^(?:0|[0-9a-f]{32})$/;

function envBool(value: string | undefined, defaultValue = false): boolean {
  if (value === undefined) return defaultValue;
  return ["1", "true", "yes", "on"].includes(value.trim().toLowerCase());
}

export function memoryFeatureAvailable(env: StorageEnv): boolean {
  return envBool(env.MEMORY_FEATURE_AVAILABLE, false);
}

function memoryTtl(env: StorageEnv): number {
  const configured = Number(env.PRIVATE_MEMORY_MAX_TTL_SECONDS ?? "86400");
  return Math.max(60, Math.min(86400, Number.isFinite(configured) ? configured : 86400));
}

function jobTtl(env: StorageEnv): number {
  const configured = Number(env.JOB_RESULT_TTL_SECONDS ?? "3600");
  return Math.max(300, Math.min(86400, Number.isFinite(configured) ? configured : 3600));
}

function deletionEpochTtl(env: StorageEnv): number {
  const configured = Number(env.TENANT_DELETION_EPOCH_TTL_SECONDS ?? "86400");
  // The marker must outlive every possible private job/memory record so a late
  // completion cannot become current again after the marker expires.
  return Math.max(86400, Math.min(172800, Number.isFinite(configured) ? configured : 86400));
}

async function currentSnapshotRunId(env: StorageEnv): Promise<string | null> {
  const text = await env.PUBLIC_CACHE.get("snapshot:current", "text");
  if (!text) return null;
  try {
    const value = JSON.parse(text) as SnapshotPointer;
    return value.run_id ?? value.runId ?? null;
  } catch {
    return text.trim() || null;
  }
}

async function candidateKeys(env: StorageEnv, logicalKeys: string[]): Promise<string[]> {
  const runId = await currentSnapshotRunId(env);
  if (runId) return logicalKeys.map((key) => `snapshot:${runId}:${key}`);
  // Direct public keys are used only before a snapshot pointer exists. Once a
  // pointer is promoted, missing run objects fail closed instead of silently
  // falling back to stale direct keys.
  return [...logicalKeys];
}

export async function publicJson<T>(env: StorageEnv, logicalKeys: string[]): Promise<T | null> {
  for (const key of await candidateKeys(env, logicalKeys)) {
    const value = await env.PUBLIC_CACHE.get<T>(key, "json");
    if (value !== null) return value;
  }
  return null;
}

export async function publicText(env: StorageEnv, logicalKeys: string[]): Promise<string | null> {
  for (const key of await candidateKeys(env, logicalKeys)) {
    const value = await env.PUBLIC_CACHE.get(key, "text");
    if (value !== null) return value;
  }
  return null;
}

function tenantEpochKey(tenantId: string): string {
  return `tenant-delete-epoch:${tenantId}`;
}

function tenantKey(tenantId: string, epoch: string, suffix: string): string {
  return `tenant:${tenantId}:${epoch}:${suffix}`;
}

function randomTenantEpoch(): string {
  const bytes = crypto.getRandomValues(new Uint8Array(16));
  return Array.from(bytes, (value) => value.toString(16).padStart(2, "0")).join("");
}

export async function tenantWriteEpoch(env: StorageEnv, tenantId: string): Promise<string> {
  const value =
    (await env.EPHEMERAL_SECURITY_CACHE.get(tenantEpochKey(tenantId)))?.trim() ||
    INITIAL_TENANT_EPOCH;
  if (!TENANT_EPOCH_RE.test(value)) throw new Error("TENANT_WRITE_EPOCH_INVALID");
  return value;
}

async function rotateTenantWriteEpoch(env: StorageEnv, tenantId: string): Promise<string> {
  const value = randomTenantEpoch();
  await env.EPHEMERAL_SECURITY_CACHE.put(tenantEpochKey(tenantId), value, {
    expirationTtl: deletionEpochTtl(env),
  });
  return value;
}

async function memoryEnabledAtEpoch(
  env: StorageEnv,
  tenantId: string,
  epoch: string,
): Promise<boolean> {
  if (!memoryFeatureAvailable(env)) return false;
  return (
    (await env.TENANT_PRIVATE_CACHE.get(tenantKey(tenantId, epoch, "memory:enabled"))) ===
    "1"
  );
}

export async function memoryEnabled(env: StorageEnv, tenantId: string): Promise<boolean> {
  return memoryEnabledAtEpoch(env, tenantId, await tenantWriteEpoch(env, tenantId));
}

export async function setMemoryEnabled(
  env: StorageEnv,
  tenantId: string,
  enabled: boolean,
): Promise<void> {
  const epoch = await tenantWriteEpoch(env, tenantId);
  const key = tenantKey(tenantId, epoch, "memory:enabled");
  if (!memoryFeatureAvailable(env) || !enabled) {
    await env.TENANT_PRIVATE_CACHE.delete(key);
    await env.TENANT_PRIVATE_CACHE.delete(tenantKey(tenantId, epoch, "conversation"));
    return;
  }
  await env.TENANT_PRIVATE_CACHE.put(key, "1", {
    expirationTtl: memoryTtl(env),
  });
}

export async function conversation(
  env: StorageEnv,
  tenantId: string,
): Promise<ConversationMessage[]> {
  const epoch = await tenantWriteEpoch(env, tenantId);
  if (!(await memoryEnabledAtEpoch(env, tenantId, epoch))) return [];
  const encrypted = await env.TENANT_PRIVATE_CACHE.get(
    tenantKey(tenantId, epoch, "conversation"),
  );
  if (!encrypted) return [];
  const value = await decryptTenantJson<ConversationMessage[]>(
    tenantId,
    encrypted,
    tenantDataEncryptionKey(env),
  );
  return Array.isArray(value) ? value.slice(-8) : [];
}

export async function saveConversation(
  env: StorageEnv,
  tenantId: string,
  messages: ConversationMessage[],
  expectedEpoch?: string,
): Promise<boolean> {
  const epoch = expectedEpoch ?? (await tenantWriteEpoch(env, tenantId));
  if ((await tenantWriteEpoch(env, tenantId)) !== epoch) return false;
  if (!(await memoryEnabledAtEpoch(env, tenantId, epoch))) return false;
  const encrypted = await encryptTenantJson(
    tenantId,
    messages.slice(-8),
    tenantDataEncryptionKey(env),
  );
  const key = tenantKey(tenantId, epoch, "conversation");
  await env.TENANT_PRIVATE_CACHE.put(key, encrypted, {
    expirationTtl: memoryTtl(env),
  });
  if ((await tenantWriteEpoch(env, tenantId)) !== epoch) {
    await env.TENANT_PRIVATE_CACHE.delete(key);
    return false;
  }
  return true;
}

export async function clearConversation(env: StorageEnv, tenantId: string): Promise<void> {
  const epoch = await tenantWriteEpoch(env, tenantId);
  await env.TENANT_PRIVATE_CACHE.delete(tenantKey(tenantId, epoch, "conversation"));
}

export async function putJob(
  env: StorageEnv,
  tenantId: string,
  referenceId: string,
  record: JobRecord,
  expectedEpoch?: string,
): Promise<boolean> {
  const epoch = expectedEpoch ?? (await tenantWriteEpoch(env, tenantId));
  if ((await tenantWriteEpoch(env, tenantId)) !== epoch) return false;
  const encrypted = await encryptTenantJson(
    tenantId,
    record,
    tenantDataEncryptionKey(env),
  );
  const key = tenantKey(tenantId, epoch, `job:${referenceId}`);
  await env.TENANT_PRIVATE_CACHE.put(key, encrypted, {
    expirationTtl: jobTtl(env),
  });
  // Re-check after the write. A deletion that raced the pre-check rotates the
  // epoch first; the late result is then removed and is never reachable through
  // the current epoch even if KV listing was eventually consistent.
  if ((await tenantWriteEpoch(env, tenantId)) !== epoch) {
    await env.TENANT_PRIVATE_CACHE.delete(key);
    return false;
  }
  return true;
}

export async function getJob(
  env: StorageEnv,
  tenantId: string,
  referenceId: string,
): Promise<JobRecord | null> {
  const epoch = await tenantWriteEpoch(env, tenantId);
  const encrypted = await env.TENANT_PRIVATE_CACHE.get(
    tenantKey(tenantId, epoch, `job:${referenceId}`),
  );
  if (!encrypted) return null;
  return decryptTenantJson<JobRecord>(tenantId, encrypted, tenantDataEncryptionKey(env));
}

export async function deleteTenantData(env: StorageEnv, tenantId: string): Promise<number> {
  // Rotate before listing. All subsequent reads use the new epoch immediately,
  // while late writes from an older in-flight operation remain unreachable and
  // are deleted by putJob/saveConversation's post-write epoch check.
  await rotateTenantWriteEpoch(env, tenantId);

  const prefix = `tenant:${tenantId}:`;
  const names: string[] = [];
  let cursor: string | undefined;

  // Enumerate first, delete second. Mutating while paginating can make a
  // privacy deletion incomplete on eventually consistent KV.
  do {
    const page = await env.TENANT_PRIVATE_CACHE.list({ prefix, cursor });
    names.push(...page.keys.map((key) => key.name));
    cursor = page.list_complete ? undefined : page.cursor;
  } while (cursor);

  for (const name of names) {
    await env.TENANT_PRIVATE_CACHE.delete(name);
  }
  return names.length;
}

export async function snapshotStatus(env: StorageEnv): Promise<Record<string, unknown>> {
  const runId = await currentSnapshotRunId(env);
  return {
    promoted_snapshot: runId,
    has_snapshot: Boolean(runId),
  };
}
