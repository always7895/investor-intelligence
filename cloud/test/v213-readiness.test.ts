/// <reference types="node" />
import { writeFileSync } from "node:fs";
import { afterEach, describe, expect, it, vi } from "vitest";
import * as top20 from "../src/v21/top20";
import worker from "../src/v213/production-worker";
import { edgeReadiness, PARSER_SCHEMA, compactPolicyHash } from "../src/v213/readiness";

const VERSION = "12345678-1234-1234-1234-123456789abc";
const OLD = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa";
const CHALLENGE = "1".repeat(32);
function request(version = VERSION, challenge = CHALLENGE) {
  return new Request(`https://synthetic.workers.dev/v213/readiness?challenge=${challenge}&expected_version=${version}`);
}
function noStorage() {
  const trap = new Proxy({}, { get() { throw new Error("READINESS_MUST_NOT_TOUCH_STORAGE"); } });
  return { CF_VERSION_METADATA: { id: VERSION }, PUBLIC_CACHE: trap, TENANT_PRIVATE_CACHE: trap, EPHEMERAL_SECURITY_CACHE: trap, V213_FREE_RELAY_ROUTE: trap } as any;
}
const ctx = { waitUntil: vi.fn(), passThroughOnException() {} } as unknown as ExecutionContext;

afterEach(() => vi.restoreAllMocks());
describe("no-write exact-version edge readiness", () => {
  it("rejects the pre-provenance parser even when the version metadata matches", async () => {
    vi.spyOn(top20, "parseV21Top20").mockReturnValue(null);
    const response = await edgeReadiness(request(), noStorage());
    expect(response.status).toBe(409);
    expect(await response.json()).toMatchObject({ ready: false, code: "V213_READINESS_PARSER_FAILED", no_write: true });
  });
  it("proves the deployed parser's positive and negative closed-schema invariants without KV/DO/model calls", async () => {
    const network = vi.spyOn(globalThis, "fetch").mockRejectedValue(new Error("READINESS_NETWORK_FORBIDDEN"));
    const response = await worker.fetch(request(), noStorage(), ctx);
    expect(network).not.toHaveBeenCalled();
    expect(response.status).toBe(200);
    const data = await response.json() as any;
    expect(data).toMatchObject({ ready: true, worker_version: VERSION, parser_schema: PARSER_SCHEMA, challenge: CHALLENGE, no_write: true, compatibility: "PASS" });
    expect(data.compact_policy_sha256).toBe(await compactPolicyHash());
    expect(response.headers.get("cache-control")).toContain("no-store");
    expect(response.headers.get("x-ii-serving-version")).toBe(VERSION);
    if (process.env.V213_READINESS_FIXTURE_OUT) writeFileSync(process.env.V213_READINESS_FIXTURE_OUT, JSON.stringify(data));
  });
  it("fails closed on old version, missing metadata and malformed challenges", async () => {
    for (const [req, env] of [[request(OLD), noStorage()], [request(), {}], [request(VERSION, "bad"), noStorage()]] as const) {
      const response = await edgeReadiness(req, env);
      expect(response.status).toBe(409);
      expect((await response.json() as any).ready).toBe(false);
    }
  });
  it("echoes a fresh challenge; a cached proof cannot satisfy a new readiness request", async () => {
    const a = await (await edgeReadiness(request(), noStorage())).json() as any;
    const b = await (await edgeReadiness(request(VERSION, "2".repeat(32)), noStorage())).json() as any;
    expect(a.challenge).not.toBe(b.challenge);
    expect(a.worker_version).toBe(b.worker_version);
  });
  it("rejects missing/old commit serving-version BEFORE HMAC nonce or snapshot writes", async () => {
    for (const id of [undefined, OLD]) {
      const headers: Record<string, string> = {};
      if (id) headers["x-ii-expected-worker-version"] = id;
      const response = await worker.fetch(new Request("https://synthetic.workers.dev/v213/admin/activation-bundle", { method: "POST", headers, body: "{}" }), noStorage(), ctx);
      expect(response.status).toBe(409);
      expect((await response.json() as any).code).toBe("V213_ACTIVATION_SERVING_VERSION_MISMATCH");
    }
  });
});
