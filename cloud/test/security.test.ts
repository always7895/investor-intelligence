import { describe, expect, it } from "vitest";
import {
  decryptTenantJson,
  deriveTenantId,
  encryptTenantJson,
  lineAccessAllowed,
  lineAccessMode,
  tenantSecretsConfigured,
  verifyLineSignature,
} from "../src/security";

function standardBase64(buffer: ArrayBuffer): string {
  const bytes = new Uint8Array(buffer);
  let binary = "";
  for (const value of bytes) binary += String.fromCharCode(value);
  return btoa(binary);
}

describe("security primitives", () => {
  it("accepts a valid LINE HMAC and rejects a modified body", async () => {
    const body = JSON.stringify({ events: [{ type: "message" }] });
    const secret = "EXAMPLE_TEST_CHANNEL_SECRET_NOT_REAL";
    const key = await crypto.subtle.importKey(
      "raw",
      new TextEncoder().encode(secret),
      { name: "HMAC", hash: "SHA-256" },
      false,
      ["sign"],
    );
    const digest = await crypto.subtle.sign(
      "HMAC",
      key,
      new TextEncoder().encode(body),
    );
    const signature = standardBase64(digest);
    await expect(verifyLineSignature(body, signature, secret)).resolves.toBe(true);
    await expect(verifyLineSignature(`${body}x`, signature, secret)).resolves.toBe(false);
  });

  it("derives stable but distinct tenant identifiers", async () => {
    const secret = "EXAMPLE_TENANT_HASH_SECRET_NOT_REAL";
    const tenantA = await deriveTenantId({ type: "user", userId: "SYNTHETIC-A" }, secret);
    const tenantA2 = await deriveTenantId({ type: "user", userId: "SYNTHETIC-A" }, secret);
    const tenantB = await deriveTenantId({ type: "user", userId: "SYNTHETIC-B" }, secret);
    expect(tenantA).toBe(tenantA2);
    expect(tenantA).not.toBe(tenantB);
    expect(tenantA).not.toContain("SYNTHETIC-A");
  });

  it("encrypts tenant data and refuses cross-tenant decryption", async () => {
    const encryptionSecret = "EXAMPLE_TENANT_ENCRYPTION_KEY_NOT_REAL";
    const envelope = await encryptTenantJson(
      "tenant-A",
      { value: "synthetic-private-message" },
      encryptionSecret,
    );
    expect(envelope).not.toContain("synthetic-private-message");
    await expect(
      decryptTenantJson<{ value: string }>("tenant-A", envelope, encryptionSecret),
    ).resolves.toEqual({ value: "synthetic-private-message" });
    await expect(
      decryptTenantJson("tenant-B", envelope, encryptionSecret),
    ).resolves.toBeNull();
  });

  it("requires both tenant secrets before shared-bot admission is operational", () => {
    expect(tenantSecretsConfigured({})).toBe(false);
    expect(
      tenantSecretsConfigured({ TENANT_HASH_SECRET: "hash-only" }),
    ).toBe(false);
    expect(
      tenantSecretsConfigured({
        TENANT_HASH_SECRET: "hash-secret",
        TENANT_DATA_ENCRYPTION_KEY: "data-secret",
      }),
    ).toBe(true);
  });

  it("defaults invalid and former public modes to disabled", () => {
    expect(lineAccessMode({})).toBe("disabled");
    expect(lineAccessMode({ LINE_ACCESS_MODE: "disabled" })).toBe("disabled");
    expect(lineAccessMode({ LINE_ACCESS_MODE: "public" })).toBe("disabled");
    expect(lineAccessMode({ LINE_ACCESS_MODE: "unexpected" })).toBe("disabled");
    expect(lineAccessMode({ LINE_ACCESS_MODE: "allowlist" })).toBe("allowlist");
  });

  it("admits only an HMAC-allowlisted direct user and always denies groups", async () => {
    const tenant = await deriveTenantId(
      { type: "user", userId: "SYNTHETIC-FRIEND" },
      "EXAMPLE_TENANT_HASH_SECRET_NOT_REAL",
    );
    expect(lineAccessAllowed({}, tenant, "user")).toBe(false);
    expect(
      lineAccessAllowed(
        {
          LINE_ACCESS_MODE: "allowlist",
          LINE_ALLOWED_TENANT_HASHES: tenant,
        },
        tenant,
        "user",
      ),
    ).toBe(true);
    expect(
      lineAccessAllowed(
        {
          LINE_ACCESS_MODE: "allowlist",
          LINE_ALLOWED_TENANT_HASHES: tenant,
        },
        tenant,
        "group",
      ),
    ).toBe(false);
    expect(
      lineAccessAllowed(
        {
          LINE_ACCESS_MODE: "allowlist",
          LINE_ALLOWED_TENANT_HASHES: "some-other-valid-hash-value-1234567890",
        },
        tenant,
        "user",
      ),
    ).toBe(false);
    expect(
      lineAccessAllowed(
        { LINE_ACCESS_MODE: "public", LINE_ALLOWED_TENANT_HASHES: tenant },
        tenant,
        "user",
      ),
    ).toBe(false);
  });
});
