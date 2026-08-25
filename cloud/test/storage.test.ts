import { describe, expect, it } from "vitest";
import {
  conversation,
  deleteTenantData,
  getJob,
  memoryEnabled,
  publicJson,
  putJob,
  saveConversation,
  setMemoryEnabled,
  tenantWriteEpoch,
  type StorageEnv,
} from "../src/storage";
import { MemoryKv, asKv } from "./fake-kv";

function env(
  publicKv: MemoryKv,
  privateKv: MemoryKv,
  overrides: Partial<StorageEnv> = {},
  securityKv = new MemoryKv(),
): StorageEnv {
  return {
    PUBLIC_CACHE: asKv(publicKv),
    TENANT_PRIVATE_CACHE: asKv(privateKv),
    EPHEMERAL_SECURITY_CACHE: asKv(securityKv),
    TENANT_HASH_SECRET: "EXAMPLE_TENANT_HASH_SECRET_NOT_REAL",
    TENANT_DATA_ENCRYPTION_KEY: "EXAMPLE_TENANT_DATA_KEY_NOT_REAL",
    MEMORY_FEATURE_AVAILABLE: "false",
    PRIVATE_MEMORY_MAX_TTL_SECONDS: "86400",
    JOB_RESULT_TTL_SECONDS: "3600",
    ...overrides,
  };
}

describe("physically separated public and tenant storage", () => {
  it("reads public snapshots only from PUBLIC_CACHE", async () => {
    const publicKv = new MemoryKv();
    const privateKv = new MemoryKv();
    publicKv.values.set("snapshot:current", JSON.stringify({ run_id: "RUN1" }));
    publicKv.values.set(
      "snapshot:RUN1:scores:latest",
      JSON.stringify([{ ticker: "PUBLIC" }]),
    );
    publicKv.values.set("scores:latest", JSON.stringify([{ ticker: "LEGACY_PUBLIC" }]));
    privateKv.values.set("scores:latest", JSON.stringify([{ ticker: "PRIVATE_SENTINEL" }]));

    await expect(publicJson(env(publicKv, privateKv), ["scores:latest"])).resolves.toEqual([
      { ticker: "PUBLIC" },
    ]);
    expect(JSON.stringify(await publicJson(env(publicKv, privateKv), ["scores:latest"]))).not.toContain(
      "PRIVATE_SENTINEL",
    );
  });

  it("keeps memory unavailable and leaves no private state by default", async () => {
    const publicKv = new MemoryKv();
    const privateKv = new MemoryKv();
    const runtime = env(publicKv, privateKv);
    expect(await memoryEnabled(runtime, "tenant-A")).toBe(false);
    await setMemoryEnabled(runtime, "tenant-A", true);
    await saveConversation(runtime, "tenant-A", [
      { role: "user", content: "private text", timestamp: "now" },
    ]);
    expect(privateKv.values.size).toBe(0);
    expect(publicKv.values.size).toBe(0);
  });

  it("encrypts explicitly available memory only in TENANT_PRIVATE_CACHE", async () => {
    const publicKv = new MemoryKv();
    const privateKv = new MemoryKv();
    const runtime = env(publicKv, privateKv, { MEMORY_FEATURE_AVAILABLE: "true" });
    await setMemoryEnabled(runtime, "tenant-A", true);
    await saveConversation(runtime, "tenant-A", [
      { role: "user", content: "private text", timestamp: "now" },
    ]);
    const raw = privateKv.values.get("tenant:tenant-A:0:conversation") ?? "";
    expect(raw).not.toContain("private text");
    expect([...publicKv.values.values()].join("\n")).not.toContain("private text");
    await expect(conversation(runtime, "tenant-A")).resolves.toEqual([
      { role: "user", content: "private text", timestamp: "now" },
    ]);
    await expect(conversation(runtime, "tenant-B")).resolves.toEqual([]);
  });

  it("encrypts long-job results only in TENANT_PRIVATE_CACHE", async () => {
    const publicKv = new MemoryKv();
    const privateKv = new MemoryKv();
    const runtime = env(publicKv, privateKv);
    await putJob(runtime, "tenant-A", "REF123", {
      status: "complete",
      createdAt: "2026-08-24T00:00:00Z",
      result: "tenant-only result",
    });
    expect([...privateKv.values.values()].join("\n")).not.toContain("tenant-only result");
    expect(publicKv.values.size).toBe(0);
    await expect(getJob(runtime, "tenant-A", "REF123")).resolves.toMatchObject({
      status: "complete",
      result: "tenant-only result",
    });
    await expect(getJob(runtime, "tenant-B", "REF123")).resolves.toBeNull();
  });

  it("deletes one tenant namespace without touching public or other-tenant data", async () => {
    const publicKv = new MemoryKv();
    const privateKv = new MemoryKv();
    const securityKv = new MemoryKv();
    publicKv.values.set("reports:latest", "PUBLIC");
    privateKv.values.set("tenant:tenant-A:memory:enabled", "1");
    privateKv.values.set("tenant:tenant-A:job:ABC", "encrypted");
    privateKv.values.set("tenant:tenant-B:memory:enabled", "1");
    const runtime = env(publicKv, privateKv, {}, securityKv);
    const deleted = await deleteTenantData(runtime, "tenant-A");
    expect(deleted).toBe(2);
    expect(privateKv.values.has("tenant:tenant-A:memory:enabled")).toBe(false);
    expect(privateKv.values.has("tenant:tenant-B:memory:enabled")).toBe(true);
    expect(publicKv.values.get("reports:latest")).toBe("PUBLIC");
    expect(await tenantWriteEpoch(runtime, "tenant-A")).not.toBe("0");
  });

  it("prevents an in-flight retry from resurrecting data after tenant deletion", async () => {
    const publicKv = new MemoryKv();
    const privateKv = new MemoryKv();
    const securityKv = new MemoryKv();
    const runtime = env(publicKv, privateKv, {}, securityKv);
    const oldEpoch = await tenantWriteEpoch(runtime, "tenant-A");
    const createdAt = new Date(Date.now() - 1000).toISOString();

    expect(
      await putJob(
        runtime,
        "tenant-A",
        "OLDREF",
        { status: "pending", createdAt },
        oldEpoch,
      ),
    ).toBe(true);
    await deleteTenantData(runtime, "tenant-A");

    expect(
      await putJob(
        runtime,
        "tenant-A",
        "OLDREF",
        {
          status: "complete",
          createdAt,
          completedAt: new Date().toISOString(),
          result: "MUST_NOT_RESURRECT",
        },
        oldEpoch,
      ),
    ).toBe(false);
    await expect(getJob(runtime, "tenant-A", "OLDREF")).resolves.toBeNull();
    expect([...privateKv.values.values()].join("\n")).not.toContain("MUST_NOT_RESURRECT");

    const newEpoch = await tenantWriteEpoch(runtime, "tenant-A");
    expect(newEpoch).not.toBe(oldEpoch);
    expect(
      await putJob(
        runtime,
        "tenant-A",
        "NEWREF",
        {
          status: "complete",
          createdAt: new Date().toISOString(),
          result: "new-generation result",
        },
        newEpoch,
      ),
    ).toBe(true);
    await expect(getJob(runtime, "tenant-A", "NEWREF")).resolves.toMatchObject({
      result: "new-generation result",
    });
    expect([...securityKv.values.values()].join("\n")).not.toContain("new-generation result");
  });
});
