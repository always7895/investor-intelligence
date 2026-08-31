import {
  decryptTenantJson,
  encryptTenantJson,
  tenantDataEncryptionKey,
} from "../security";
import { tenantWriteEpoch, type StorageEnv } from "../storage";

interface EncryptedOwnerTarget {
  lineUserId: string;
  pairedAt: string;
}

export interface OwnerPushTarget {
  tenantId: string;
  lineUserId: string;
  pairedAt: string;
}

const OWNER_POINTER_KEY = "v21:owner-line:tenant";
const OWNER_TARGET_SUFFIX = "v21:owner-line:push-target";
const TENANT_ID_RE = /^[A-Za-z0-9_-]{43}$/;
const LINE_USER_ID_RE = /^U[0-9a-f]{32}$/i;

function targetKey(tenantId: string, epoch: string): string {
  return `tenant:${tenantId}:${epoch}:${OWNER_TARGET_SUFFIX}`;
}

export async function storeOwnerPairing(
  env: StorageEnv,
  tenantId: string,
  lineUserId: string,
): Promise<void> {
  if (!TENANT_ID_RE.test(tenantId) || !LINE_USER_ID_RE.test(lineUserId)) {
    throw new Error("V21_OWNER_PAIRING_INPUT_INVALID");
  }
  const existing = await env.TENANT_PRIVATE_CACHE.get(OWNER_POINTER_KEY);
  if (existing && existing !== tenantId) throw new Error("V21_OWNER_ALREADY_PAIRED");

  const epoch = await tenantWriteEpoch(env, tenantId);
  const pairedAt = new Date().toISOString();
  const encrypted = await encryptTenantJson(
    tenantId,
    { lineUserId, pairedAt } satisfies EncryptedOwnerTarget,
    tenantDataEncryptionKey(env),
  );
  const key = targetKey(tenantId, epoch);
  await env.TENANT_PRIVATE_CACHE.put(key, encrypted);
  if ((await tenantWriteEpoch(env, tenantId)) !== epoch) {
    await env.TENANT_PRIVATE_CACHE.delete(key);
    throw new Error("V21_OWNER_PAIRING_EPOCH_CHANGED");
  }
  await env.TENANT_PRIVATE_CACHE.put(OWNER_POINTER_KEY, tenantId);
  if ((await tenantWriteEpoch(env, tenantId)) !== epoch) {
    await env.TENANT_PRIVATE_CACHE.delete(key);
    await env.TENANT_PRIVATE_CACHE.delete(OWNER_POINTER_KEY);
    throw new Error("V21_OWNER_PAIRING_EPOCH_CHANGED");
  }
}

export async function getOwnerPushTarget(env: StorageEnv): Promise<OwnerPushTarget | null> {
  const tenantId = (await env.TENANT_PRIVATE_CACHE.get(OWNER_POINTER_KEY))?.trim() ?? "";
  if (!TENANT_ID_RE.test(tenantId)) return null;
  const epoch = await tenantWriteEpoch(env, tenantId);
  const encrypted = await env.TENANT_PRIVATE_CACHE.get(targetKey(tenantId, epoch));
  if (!encrypted) {
    await env.TENANT_PRIVATE_CACHE.delete(OWNER_POINTER_KEY);
    return null;
  }
  const target = await decryptTenantJson<EncryptedOwnerTarget>(
    tenantId,
    encrypted,
    tenantDataEncryptionKey(env),
  );
  if (!target || !LINE_USER_ID_RE.test(target.lineUserId) || !Number.isFinite(Date.parse(target.pairedAt))) {
    await env.TENANT_PRIVATE_CACHE.delete(OWNER_POINTER_KEY);
    return null;
  }
  return { tenantId, lineUserId: target.lineUserId, pairedAt: target.pairedAt };
}

export async function isOwnerTenant(env: StorageEnv, tenantId: string): Promise<boolean> {
  if (!TENANT_ID_RE.test(tenantId)) return false;
  const target = await getOwnerPushTarget(env);
  return target?.tenantId === tenantId;
}

export async function removeOwnerPairing(env: StorageEnv, tenantId: string): Promise<boolean> {
  const pointer = (await env.TENANT_PRIVATE_CACHE.get(OWNER_POINTER_KEY))?.trim() ?? "";
  if (pointer !== tenantId) return false;
  const epoch = await tenantWriteEpoch(env, tenantId);
  await env.TENANT_PRIVATE_CACHE.delete(OWNER_POINTER_KEY);
  await env.TENANT_PRIVATE_CACHE.delete(targetKey(tenantId, epoch));
  return true;
}

export async function ownerPairingStatus(env: StorageEnv): Promise<boolean> {
  return (await getOwnerPushTarget(env)) !== null;
}
