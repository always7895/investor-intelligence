import { describe, expect, it } from "vitest";
import worker, { type Env } from "../src/worker";
import { MemoryKv, asKv } from "./fake-kv";

function context(): ExecutionContext {
  return {
    waitUntil() {},
    passThroughOnException() {},
  } as unknown as ExecutionContext;
}

function env(): Env {
  return {
    PUBLIC_CACHE: asKv(new MemoryKv()),
    TENANT_PRIVATE_CACHE: asKv(new MemoryKv()),
    EPHEMERAL_SECURITY_CACHE: asKv(new MemoryKv()),
    LINE_CHANNEL_SECRET: "EXAMPLE_LINE_CHANNEL_SECRET_NOT_REAL",
    LINE_CHANNEL_ACCESS_TOKEN: "EXAMPLE_LINE_ACCESS_TOKEN_NOT_REAL",
    LINE_ACCESS_MODE: "allowlist",
    TENANT_HASH_SECRET: "EXAMPLE_TENANT_HASH_SECRET_NOT_REAL",
    TENANT_DATA_ENCRYPTION_KEY: "EXAMPLE_TENANT_DATA_KEY_NOT_REAL",
    MEMORY_FEATURE_AVAILABLE: "false",
    LOCAL_LLM_BASE_URL: "https://private-model.example",
    LOCAL_LLM_ALLOWED_HOSTS: "private-model.example",
    LOCAL_LLM_SHARED_SECRET: "EXAMPLE_LOCAL_MODEL_SECRET_NOT_REAL",
  };
}

describe("public health metadata", () => {
  it("exposes static safety posture but no operational, model-route or namespace metadata", async () => {
    const response = await worker.fetch(
      new Request("https://example.test/health"),
      env(),
      context(),
    );
    expect(response.status).toBe(200);
    expect(response.headers.get("cache-control")).toBe("no-store");
    const payload = (await response.json()) as Record<string, unknown>;

    expect(payload.ok).toBe(true);
    expect(payload.line_access_mode).toBe("allowlist");
    expect(payload.direct_chat_only).toBe(true);
    expect(payload.options_scope).toBe("public_snapshot_only");
    expect(payload.ibkr_bridge).toBe(false);
    expect(payload.portfolio_access).toBe(false);
    expect(payload.private_sync).toBe(false);

    expect(payload).not.toHaveProperty("last_successful_pipeline_timestamp");
    expect(payload).not.toHaveProperty("snapshot");
    expect(payload).not.toHaveProperty("local_model_configured");
    expect(payload).not.toHaveProperty("timestamp");
    expect(payload).not.toHaveProperty("kv_namespaces");
    expect(JSON.stringify(payload)).not.toContain("private-model.example");
    expect(JSON.stringify(payload)).not.toContain("TENANT_PRIVATE_CACHE");
  });
});
