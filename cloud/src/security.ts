export interface SecurityEnv {
  TENANT_HASH_SECRET?: string;
  TENANT_DATA_ENCRYPTION_KEY?: string;
  // Legacy key aliases are accepted only for migration of tenant-scoped memory.
  TENANT_HMAC_SECRET?: string;
  TENANT_ENCRYPTION_KEY?: string;
  LINE_ACCESS_MODE?: string;
  LINE_ALLOWED_TENANT_HASHES?: string;
}

export type LineAccessMode = "disabled" | "allowlist";

export interface LineSourceIdentity {
  type: "user" | "group" | "room";
  userId?: string;
  groupId?: string;
  roomId?: string;
}

const encoder = new TextEncoder();
const decoder = new TextDecoder();

function bytesToBase64Url(value: ArrayBuffer | Uint8Array): string {
  const bytes = value instanceof Uint8Array ? value : new Uint8Array(value);
  let binary = "";
  const chunk = 0x8000;
  for (let index = 0; index < bytes.length; index += chunk) {
    binary += String.fromCharCode(...bytes.subarray(index, index + chunk));
  }
  return btoa(binary).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/g, "");
}

function base64UrlToBytes(value: string): Uint8Array<ArrayBuffer> {
  const normalized = value.replace(/-/g, "+").replace(/_/g, "/");
  const padded = normalized + "=".repeat((4 - (normalized.length % 4)) % 4);
  const binary = atob(padded);
  const bytes = new Uint8Array(binary.length);
  for (let index = 0; index < binary.length; index += 1) {
    bytes[index] = binary.charCodeAt(index);
  }
  return bytes;
}

function parseHashSet(value: string | undefined): Set<string> {
  return new Set(
    (value ?? "")
      .split(",")
      .map((item) => item.trim())
      .filter((item) => /^[A-Za-z0-9_-]{20,64}$/.test(item)),
  );
}

export function timingSafeEqual(left: string, right: string): boolean {
  const a = encoder.encode(left);
  const b = encoder.encode(right);
  if (a.length !== b.length) return false;
  let difference = 0;
  for (let index = 0; index < a.length; index += 1) {
    difference |= a[index]! ^ b[index]!;
  }
  return difference === 0;
}

export function tenantHashSecret(env: SecurityEnv): string {
  const value = env.TENANT_HASH_SECRET ?? env.TENANT_HMAC_SECRET ?? "";
  if (!value) throw new Error("TENANT_HASH_SECRET is not configured");
  return value;
}

export function tenantDataEncryptionKey(env: SecurityEnv): string {
  const value = env.TENANT_DATA_ENCRYPTION_KEY ?? env.TENANT_ENCRYPTION_KEY ?? "";
  if (!value) throw new Error("TENANT_DATA_ENCRYPTION_KEY is not configured");
  return value;
}

export function tenantSecretsConfigured(env: SecurityEnv): boolean {
  return Boolean(
    (env.TENANT_HASH_SECRET ?? env.TENANT_HMAC_SECRET ?? "").trim() &&
      (env.TENANT_DATA_ENCRYPTION_KEY ?? env.TENANT_ENCRYPTION_KEY ?? "").trim(),
  );
}

export function lineAccessMode(env: SecurityEnv): LineAccessMode {
  return (env.LINE_ACCESS_MODE ?? "disabled").trim().toLowerCase() === "allowlist"
    ? "allowlist"
    : "disabled";
}

export function lineAccessAllowed(
  env: SecurityEnv,
  tenantId: string,
  chatType: LineSourceIdentity["type"],
): boolean {
  if (lineAccessMode(env) !== "allowlist") return false;
  // Shared operation is permanently one-to-one. This is intentionally not an
  // environment switch: deployment configuration cannot reopen group/room data
  // or quota surfaces.
  if (chatType !== "user") return false;
  return parseHashSet(env.LINE_ALLOWED_TENANT_HASHES).has(tenantId);
}

export async function verifyLineSignature(
  rawBody: string,
  signature: string | null,
  channelSecret: string,
): Promise<boolean> {
  if (!signature || !channelSecret) return false;
  const key = await crypto.subtle.importKey(
    "raw",
    encoder.encode(channelSecret),
    { name: "HMAC", hash: "SHA-256" },
    false,
    ["sign"],
  );
  const digest = await crypto.subtle.sign("HMAC", key, encoder.encode(rawBody));
  const standardBase64 = bytesToBase64Url(digest)
    .replace(/-/g, "+")
    .replace(/_/g, "/");
  const padding = "=".repeat((4 - (standardBase64.length % 4)) % 4);
  return timingSafeEqual(`${standardBase64}${padding}`, signature);
}

export async function hashOpaqueId(value: string): Promise<string> {
  const digest = await crypto.subtle.digest("SHA-256", encoder.encode(value));
  return bytesToBase64Url(digest).slice(0, 43);
}

function identityMaterial(source: LineSourceIdentity): string {
  return [
    source.type,
    source.userId ?? "",
    source.groupId ?? "",
    source.roomId ?? "",
  ].join("|");
}

export async function deriveTenantId(
  source: LineSourceIdentity,
  secret: string,
): Promise<string> {
  if (!secret) throw new Error("TENANT_HASH_SECRET is not configured");
  const key = await crypto.subtle.importKey(
    "raw",
    encoder.encode(secret),
    { name: "HMAC", hash: "SHA-256" },
    false,
    ["sign"],
  );
  const digest = await crypto.subtle.sign("HMAC", key, encoder.encode(identityMaterial(source)));
  return bytesToBase64Url(digest).slice(0, 43);
}

async function encryptionKey(secret: string, tenantId: string): Promise<CryptoKey> {
  if (!secret) throw new Error("TENANT_DATA_ENCRYPTION_KEY is not configured");
  const hmacKey = await crypto.subtle.importKey(
    "raw",
    encoder.encode(secret),
    { name: "HMAC", hash: "SHA-256" },
    false,
    ["sign"],
  );
  const derived = await crypto.subtle.sign(
    "HMAC",
    hmacKey,
    encoder.encode(`tenant-data-key|${tenantId}`),
  );
  return crypto.subtle.importKey(
    "raw",
    derived,
    { name: "AES-GCM" },
    false,
    ["encrypt", "decrypt"],
  );
}

export async function encryptTenantJson(
  tenantId: string,
  value: unknown,
  secret: string,
): Promise<string> {
  const key = await encryptionKey(secret, tenantId);
  const iv = crypto.getRandomValues(new Uint8Array(12));
  const ciphertext = await crypto.subtle.encrypt(
    { name: "AES-GCM", iv, additionalData: encoder.encode(tenantId) },
    key,
    encoder.encode(JSON.stringify(value)),
  );
  return JSON.stringify({
    v: 1,
    iv: bytesToBase64Url(iv),
    ciphertext: bytesToBase64Url(ciphertext),
  });
}

export async function decryptTenantJson<T>(
  tenantId: string,
  envelope: string,
  secret: string,
): Promise<T | null> {
  let parsed: { v?: number; iv?: string; ciphertext?: string };
  try {
    parsed = JSON.parse(envelope) as { v?: number; iv?: string; ciphertext?: string };
  } catch {
    return null;
  }
  if (parsed.v !== 1 || !parsed.iv || !parsed.ciphertext) return null;
  try {
    const key = await encryptionKey(secret, tenantId);
    const plaintext = await crypto.subtle.decrypt(
      {
        name: "AES-GCM",
        iv: base64UrlToBytes(parsed.iv),
        additionalData: encoder.encode(tenantId),
      },
      key,
      base64UrlToBytes(parsed.ciphertext),
    );
    return JSON.parse(decoder.decode(plaintext)) as T;
  } catch {
    return null;
  }
}

export function randomReference(length = 8): string {
  const alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789";
  const bytes = crypto.getRandomValues(new Uint8Array(length));
  return Array.from(bytes, (value) => alphabet[value % alphabet.length]).join("");
}
