import { describe, expect, it } from "vitest";
import { pinPublicSnapshot, publicJson, publicText } from "../src/v213/public-snapshot";
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
