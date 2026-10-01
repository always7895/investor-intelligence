import { describe, expect, it } from "vitest";
import { pinPublicSnapshot, publicJson, publicText, scopePublicSnapshot } from "../src/v213/public-snapshot";
import { publicJson as storageJson, publicText as storageText, snapshotStatus } from "../src/storage";
import { asKv, MemoryKv } from "./fake-kv";

class TracedKv extends MemoryKv {
  reads: string[] = [];
  override async get<T = string>(key: string, type?: "text" | "json"): Promise<T | string | null> {
    this.reads.push(key);
    return super.get<T>(key, type);
  }
}
function runtime() {
  const kv = new TracedKv();
  return { kv, env: { PUBLIC_CACHE: asKv(kv), TENANT_PRIVATE_CACHE: asKv(new MemoryKv()), EPHEMERAL_SECURITY_CACHE: asKv(new MemoryKv()) } };
}

describe("public snapshot selection", () => {
  it("keeps every compatibility read public-only when non-public KV access would throw", async () => {
    class ForbiddenKv extends MemoryKv {
      override async get<T = string>(_key: string, _type?: "text" | "json"): Promise<T | string | null> {
        throw new Error("NON_PUBLIC_KV_MUST_NOT_BE_READ");
      }
    }
    const { kv, env } = runtime();
    const forbidden = new ForbiddenKv();
    env.TENANT_PRIVATE_CACHE = asKv(forbidden);
    env.EPHEMERAL_SECURITY_CACHE = asKv(forbidden);
    kv.values.set("snapshot:current", '{"run_id":"run-a"}');
    kv.values.set("snapshot:run-a:report", '{"public":true}');
    kv.values.set("snapshot:run-a:note", "PUBLIC_TEXT");
    const scoped = scopePublicSnapshot(env);
    expect(await storageJson(scoped, ["report"])).toEqual({ public: true });
    expect(await storageText(scoped, ["note"])).toBe("PUBLIC_TEXT");
    expect(await snapshotStatus(scoped)).toEqual({ promoted_snapshot: "run-a", has_snapshot: true });
    expect(forbidden.values.size).toBe(0);
    expect(kv.reads.filter(key => key === "snapshot:current")).toHaveLength(1);
  });

  it.each(["", " ", "{}", "[]", "null", "true", "42", '"run-a"', "{broken",
    '{"run_id":null}', '{"run_id":42}', '{"run_id":""}', '{"run_id":"run/a"}',
    '{"run_id":"a","runId":"b"}', '{"run_id":null,"runId":"b"}',
    JSON.stringify({ run_id: "a".repeat(129) }),
  ])("never falls back to direct keys for invalid existing pointer %s", async pointer => {
    const { kv, env } = runtime();
    kv.values.set("snapshot:current", pointer);
    kv.values.set("report", JSON.stringify({ legacy: true }));
    kv.values.set("alternate", "legacy-data");
    expect(await publicJson(env, ["report"])).toBeNull();
    expect(await publicText(env, ["alternate"])).toBeNull();
    expect(await storageJson(env, ["report"])).toBeNull();
    expect(await storageText(env, ["alternate"])).toBeNull();
    expect(await snapshotStatus(env)).toEqual({ promoted_snapshot: null, has_snapshot: false });
    expect(kv.reads.every(key => key === "snapshot:current")).toBe(true);
    expect((await pinPublicSnapshot(env)).kind).toBe("invalid");
  });

  it("retains bootstrap compatibility only when pointer is absent", async () => {
    const { kv, env } = runtime();
    kv.values.set("report", JSON.stringify({ legacy: true }));
    expect(await publicJson(env, ["report"])).toEqual({ legacy: true });
    expect((await pinPublicSnapshot(env)).kind).toBe("legacy");
  });

  it.each(["run-a", '{"run_id":"run-a"}', '{"runId":"run-a"}', '{"run_id":"run-a","runId":"run-a"}'])("retains valid pointer compatibility %s", async pointer => {
    const { kv, env } = runtime();
    kv.values.set("snapshot:current", pointer);
    kv.values.set("report", JSON.stringify({ legacy: true }));
    expect(await publicJson(env, ["report"])).toBeNull();
    kv.values.set("snapshot:run-a:report", JSON.stringify({ run: "a" }));
    expect(await publicJson(env, ["report"])).toEqual({ run: "a" });
  });

  it("lazily shares one in-flight selection across current and compatibility exports", async () => {
    const { kv, env } = runtime();
    kv.values.set("snapshot:current", '{"run_id":"run-a"}');
    kv.values.set("snapshot:run-a:report", JSON.stringify({ run: "a" }));
    const scoped = scopePublicSnapshot(env);
    expect(scoped).not.toBe(env); expect(scoped.PUBLIC_CACHE).toBe(env.PUBLIC_CACHE);
    expect(scoped.TENANT_PRIVATE_CACHE).toBe(env.TENANT_PRIVATE_CACHE);
    expect(kv.reads).toHaveLength(0);
    const [a, b, view] = await Promise.all([storageJson(scoped, ["report"]), publicJson(scoped, ["report"]), pinPublicSnapshot(scoped)]);
    expect(a).toEqual({ run: "a" }); expect(b).toEqual(a); expect(view.integrity).toBe("legacy");
    expect(kv.reads.filter(key => key === "snapshot:current")).toHaveLength(1);
    // Legacy scope pins only its pointer; it does NOT seal mutable legacy bodies.
    kv.values.set("snapshot:current", '{"run_id":"run-b"}');
    expect((await pinPublicSnapshot(scoped)).runId).toBe("run-a");
    expect((await pinPublicSnapshot(scopePublicSnapshot(scoped))).runId).toBe("run-b");
    expect(kv.reads.filter(key => key === "snapshot:current")).toHaveLength(2);
  });

  it("retains invalid selection for the question rather than repairing it after pointer changes", async () => {
    const { kv, env } = runtime(); kv.values.set("snapshot:current", "null");
    kv.values.set("report", "MUST_NOT_RESCUE_INVALID_POINTER"); const scoped = scopePublicSnapshot(env);
    expect(await storageText(scoped, ["report"])).toBeNull();
    kv.values.delete("snapshot:current");
    expect(await publicText(scoped, ["report"])).toBeNull();
    expect((await pinPublicSnapshot(scoped)).integrity).toBe("invalid");
    expect(kv.reads).toEqual(["snapshot:current"]);
    expect(await storageText(scopePublicSnapshot(env), ["report"])).toBe("MUST_NOT_RESCUE_INVALID_POINTER");
  });

  it("does not retry a failed pointer read in the same question", async () => {
    const { kv, env } = runtime(); const get = kv.get.bind(kv); let calls = 0; let fail = true;
    env.PUBLIC_CACHE = asKv({ ...kv, async get<T>(key: string, type?: "text" | "json") {
      calls += 1; if (fail) throw new Error("SYNTHETIC_POINTER_READ_FAILED"); return get<T>(key, type);
    } } as unknown as MemoryKv);
    const scoped = scopePublicSnapshot(env);
    await expect(storageText(scoped, ["report"])).rejects.toThrow("SYNTHETIC_POINTER_READ_FAILED");
    fail = false;
    await expect(publicJson(scoped, ["report"])).rejects.toThrow("SYNTHETIC_POINTER_READ_FAILED");
    expect(calls).toBe(1);
    expect((await pinPublicSnapshot(scopePublicSnapshot(env))).kind).toBe("legacy");
    expect(calls).toBe(2);
  });

  it("pins related reads and lets subsequent requests select a newer run", async () => {
    const { kv, env } = runtime();
    kv.values.set("snapshot:current", '{"run_id":"run-a"}');
    kv.values.set("snapshot:run-a:report", JSON.stringify({ run: "a" }));
    kv.values.set("snapshot:run-a:stamp", "a-stamp");
    kv.values.set("snapshot:run-b:stamp", "b-stamp");
    const view = await pinPublicSnapshot(env);
    expect(view.runId).toBe("run-a");
    expect(Object.isFrozen(view)).toBe(true);
    expect(await view.json(["report"])).toEqual({ run: "a" });
    kv.values.set("snapshot:current", '{"run_id":"run-b"}');
    expect(await view.text(["stamp"])).toBe("a-stamp");
    expect(kv.reads.filter(key => key === "snapshot:current")).toHaveLength(1);
    expect(await publicText(env, ["stamp"])).toBe("b-stamp");
  });
});
