// G7 / F06 offline producer -> wire -> Worker replay (Worker half). The fixture is the exact staged layout (index.json
// KV key -> k<N>.txt, and the file texts) that scripts/stage_sealed_replay.py stage() wrote for a run the real
// scripts/publish_sealed_snapshot.py main() sealed with --guidance-machine over the genuine AUTO producer bytes
// (generator tests/fixtures/make_revenue_guidance_f06_replay.py, Python half tests/test_revenue_guidance_f06_replay.py).
// It is loaded into a memory KV the way live-kv-replay.test.ts loads a staged run, then read through the real
// pinPublicSnapshot seal verification, the lazy blob digests and the machine loader at the historical AUTO cutoff.
// Synthetic historical data only: no native, live, network or Production qualification.
import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import { parseQuery } from "../src/core";
import { BOTTLENECK_V3_KEY, buildBottleneckDetail, loadBottleneckV3, parseBottleneckV3, type BottleneckV3 } from "../src/v213/bottleneck-v3";
import { pinPublicSnapshot } from "../src/v213/public-snapshot";
import { GUIDANCE_BINDING_KEY, resolveSealedMachineBindings } from "../src/v213/revenue-guidance-machine";
import { v213PublicLineAnswer } from "../src/v213/rich-menu";
import { SNAPSHOT_LAZY_BLOB_PREFIX, SNAPSHOT_SEAL_KEY } from "../src/v213/snapshot-seal";
import { MemoryKv } from "./fake-kv";
import { makeOfflineEnv } from "./synthetic-sealed-replay-fixture";

interface StagedReplay {
  schema: string; scope: string; cutoff: string; run_id: string; top20_state: string;
  index: Record<string, string>; files: Record<string, string>;
}
const replay = JSON.parse(readFileSync(new URL("./fixtures/revenue-guidance-f06-sealed-replay.json", import.meta.url), "utf8")) as StagedReplay;
const auto = JSON.parse(readFileSync(new URL("../../tests/fixtures/revenue-guidance-machine-auto-functional.json", import.meta.url), "utf8")) as {
  report: string; binding: string;
};
const AUTO_CUTOFF = "2026-02-27T13:00:00Z";
const NOW = Date.parse(AUTO_CUTOFF);
const PREFIX = `snapshot:${replay.run_id}:`;
const DETAIL_NVDA = "\u74f6\u9838\u8a73\u60c5 NVDA"; // the LINE bottleneck-detail command for NVDA
const BOTTLENECK_LIST = "\u74f6\u9838\u699c"; // the LINE bottleneck Top20 command
const V3_UNAVAILABLE_PREFIX = "\u74f6\u9838\u7206\u767c TOP20 "; // rich-menu.ts V3_UNAVAILABLE and the detail refusal

function required<T>(value: T | undefined, label: string): T {
  if (value === undefined) throw new Error(`${label} is missing`);
  return value;
}
function stagedKv(edit?: (values: Map<string, string>) => void): MemoryKv {
  const kv = new MemoryKv();
  for (const [key, file] of Object.entries(replay.index)) kv.values.set(key, required(replay.files[file], `staged file ${file}`));
  edit?.(kv.values);
  return kv;
}

const sealText = required(stagedKv().values.get(PREFIX + SNAPSHOT_SEAL_KEY), "the staged seal");
const seal = JSON.parse(sealText) as { objects: Record<string, { sha256: string; utf8_bytes: number }> };
const sealedDigest = (logicalKey: string) => required(seal.objects[logicalKey], `sealed ${logicalKey}`).sha256;
const blobKey = (logicalKey: string) => SNAPSHOT_LAZY_BLOB_PREFIX + sealedDigest(logicalKey);
function nvdaForecast(doc: BottleneckV3 | null) {
  const forecast = doc?.top.find(row => row.symbol === "NVDA")?.forecast;
  if (!forecast) throw new Error("expected a full report with an NVDA forecast");
  return forecast;
}
async function atCutoff<T>(run: () => Promise<T>): Promise<T> {
  // The loader keeps its production Date.now default; pin the declared historical instant and restore it.
  const realNow = Date.now;
  Date.now = () => NOW;
  try { return await run(); } finally { Date.now = realNow; }
}
const sha256 = (text: string) => createHash("sha256").update(text, "utf8").digest("hex");
const utf8Bytes = (text: string) => new TextEncoder().encode(text).byteLength;
const producerBinding = JSON.parse(auto.binding) as { report_sha256: string; source_manifest_sha256: string };
/** auto.binding with the last hex digit of one field flipped: the same UTF-8 length and still a well-formed binding. */
function flipBindingDigit(field: "report_sha256" | "source_manifest_sha256"): string {
  const value = producerBinding[field], spelled = `"${field}":"${value}"`;
  if (auto.binding.split(spelled).length !== 2) throw new Error(`${field} must occur exactly once in the binding`);
  return auto.binding.replace(spelled, `"${field}":"${value.slice(0, -1)}${value.endsWith("0") ? "1" : "0"}"`);
}
// Equal length and still resolvable for the sealed report: only the sealed sha256 compare can refuse this blob.
const SAME_LENGTH_BINDING = flipBindingDigit("source_manifest_sha256");
// Bound to other report bytes: the machine selection cannot resolve it against the sealed report.
const REPLAYED_BINDING = flipBindingDigit("report_sha256");
/** Re-seal the staged run over another binding blob, so its blob digest, the seal and the pointer all hold. */
function resealBinding(values: Map<string, string>, binding: string): void {
  const manifest = JSON.parse(sealText) as typeof seal;
  manifest.objects[GUIDANCE_BINDING_KEY] = { sha256: sha256(binding), utf8_bytes: utf8Bytes(binding) };
  const resealed = JSON.stringify(manifest);
  const pointer = JSON.parse(required(values.get("snapshot:current"), "the staged pointer")) as { seal_sha256: string };
  pointer.seal_sha256 = sha256(resealed);
  values.delete(blobKey(GUIDANCE_BINDING_KEY));
  values.set(SNAPSHOT_LAZY_BLOB_PREFIX + sha256(binding), binding);
  values.set(PREFIX + SNAPSHOT_SEAL_KEY, resealed);
  values.set("snapshot:current", JSON.stringify(pointer));
}

describe("G7 F06 staged sealed run through the real Worker readers", () => {
  it("binds the run, the seal and both lazy guidance objects to the producer bytes", async () => {
    expect([replay.schema, replay.scope, replay.cutoff, replay.top20_state]).toEqual(
      ["revenue-guidance-f06-sealed-replay-v1", "SYNTHETIC_HISTORICAL_AUTO_OFFLINE_REPLAY_NOT_NATIVE_OR_LIVE", AUTO_CUTOFF, "INSUFFICIENT"]);
    expect(Object.entries(replay.index)[0]).toEqual(["snapshot:current", "k0.txt"]);
    const kv = stagedKv();
    expect(kv.values.get(blobKey(BOTTLENECK_V3_KEY))).toBe(auto.report);
    expect(kv.values.get(blobKey(GUIDANCE_BINDING_KEY))).toBe(auto.binding);
    expect(kv.values.has(PREFIX + BOTTLENECK_V3_KEY) || kv.values.has(PREFIX + GUIDANCE_BINDING_KEY)).toBe(false);
    const { env, privateKv, securityKv } = makeOfflineEnv(kv);
    const view = await pinPublicSnapshot(env);
    expect([view.integrity, view.kind, view.runId]).toEqual(["sealed", "snapshot", replay.run_id]);
    expect([view.hasSealedObject?.(BOTTLENECK_V3_KEY), view.hasSealedObject?.(GUIDANCE_BINDING_KEY)]).toEqual([true, true]);
    expect(await view.text([GUIDANCE_BINDING_KEY])).toBe(auto.binding);
    expect(await view.text([BOTTLENECK_V3_KEY])).toBe(auto.report);
    expect([privateKv.reads, securityKv.reads]).toEqual([0, 0]);
  });

  it("admits the sealed machine forecast through the normal loader only with the opt-in", async () => {
    const { env } = makeOfflineEnv(stagedKv());
    await atCutoff(async () => {
      const view = await pinPublicSnapshot(env);
      const loaded = await loadBottleneckV3(view, { guidanceMachineEnabled: true });
      const forecast = nvdaForecast(loaded);
      expect(forecast.machineAdmitted).toBe(true);
      expect(forecast.revenueDiagnostic).toBeNull();
      expect(forecast.cutoff).toBe(AUTO_CUTOFF);
      expect(forecast.m6).toMatchObject({ status: "AVAILABLE", amount: 156e9 });
      expect(forecast.m12).toMatchObject({ status: "AVAILABLE", amount: 312e9 });
      const selected = resolveSealedMachineBindings(auto.report, auto.binding);
      if (selected === null) throw new Error("the sealed binding did not resolve");
      expect(loaded).toEqual(parseBottleneckV3(JSON.parse(auto.report), NOW, { guidanceMachineEnabled: true, machineBindings: selected }));
      // The same sealed run read without the machine opt-in never admits the machine payload.
      expect(nvdaForecast(await loadBottleneckV3(view)).machineAdmitted).not.toBe(true);
    });
  });

  it("answers the LINE detail command from the sealed machine forecast only when the env opts in", async () => {
    const { env } = makeOfflineEnv(stagedKv());
    await atCutoff(async () => {
      const view = await pinPublicSnapshot(env);
      const enabledDoc = await loadBottleneckV3(view, { guidanceMachineEnabled: true });
      const disabledDoc = await loadBottleneckV3(view);
      if (!enabledDoc || !disabledDoc) throw new Error("the sealed report did not load");
      const enabled = await v213PublicLineAnswer({ ...env, V213_LINE_PRESENTATION: "text", V213_GUIDANCE_MACHINE_ENABLED: "1" } as never,
        parseQuery(DETAIL_NVDA));
      const disabled = await v213PublicLineAnswer({ ...env, V213_LINE_PRESENTATION: "text" } as never, parseQuery(DETAIL_NVDA));
      expect(Array.isArray(enabled)).toBe(true);
      expect(enabled).toEqual(buildBottleneckDetail(enabledDoc, "NVDA", "text"));
      expect(disabled).toEqual(buildBottleneckDetail(disabledDoc, "NVDA", "text"));
      expect(enabled).not.toEqual(disabled);
    });
  });

  it("refuses a same-length binding blob on its sealed digest alone", async () => {
    // The length check and the machine selection both pass this blob; only readLazySealedObject's sha256 compare refuses it.
    expect(SAME_LENGTH_BINDING).not.toBe(auto.binding);
    expect(utf8Bytes(SAME_LENGTH_BINDING)).toBe(required(seal.objects[GUIDANCE_BINDING_KEY], "sealed binding").utf8_bytes);
    expect(resolveSealedMachineBindings(auto.report, SAME_LENGTH_BINDING)).not.toBeNull();
    const { env } = makeOfflineEnv(stagedKv(values => { values.set(blobKey(GUIDANCE_BINDING_KEY), SAME_LENGTH_BINDING); }));
    const view = await pinPublicSnapshot(env);
    expect([view.integrity, view.hasSealedObject?.(GUIDANCE_BINDING_KEY)]).toEqual(["sealed", true]);
    expect(await view.text([GUIDANCE_BINDING_KEY])).toBeNull();
    expect(await view.text([BOTTLENECK_V3_KEY])).toBe(auto.report);
  });

  it("reaches the machine selection through a re-sealed run whose binding is bound to other report bytes", async () => {
    // Over the producer binding the re-seal reproduces the staged seal and pointer bytes exactly.
    const resealedProducer = stagedKv(values => { resealBinding(values, auto.binding); });
    expect(Object.fromEntries(resealedProducer.values)).toEqual(Object.fromEntries(stagedKv().values));
    expect(resolveSealedMachineBindings(auto.report, REPLAYED_BINDING)).toBeNull();
    const { env } = makeOfflineEnv(stagedKv(values => { resealBinding(values, REPLAYED_BINDING); }));
    await atCutoff(async () => {
      const view = await pinPublicSnapshot(env);
      expect([view.integrity, view.kind, view.runId]).toEqual(["sealed", "snapshot", replay.run_id]);
      expect(await view.text([GUIDANCE_BINDING_KEY])).toBe(REPLAYED_BINDING);
      expect(await view.text([BOTTLENECK_V3_KEY])).toBe(auto.report);
      // The report itself still loads without the opt-in, so the machine refusal below is the selection's alone.
      expect(nvdaForecast(await loadBottleneckV3(view)).machineAdmitted).not.toBe(true);
    });
  });

  it.each<[string, (values: Map<string, string>) => void]>([
    ["binding-blob-altered", values => { values.set(blobKey(GUIDANCE_BINDING_KEY), auto.binding + " "); }],
    ["binding-blob-missing", values => { values.delete(blobKey(GUIDANCE_BINDING_KEY)); }],
    ["binding-blob-same-length", values => { values.set(blobKey(GUIDANCE_BINDING_KEY), SAME_LENGTH_BINDING); }],
    ["report-blob-altered", values => { values.set(blobKey(BOTTLENECK_V3_KEY), auto.report + " "); }],
    ["seal-rebound", values => { values.set(PREFIX + SNAPSHOT_SEAL_KEY, sealText.replace(sealedDigest(GUIDANCE_BINDING_KEY), "0".repeat(64))); }],
    ["pointer-missing", values => { values.delete("snapshot:current"); }],
    ["binding-replayed-and-resealed", values => { resealBinding(values, REPLAYED_BINDING); }],
  ])("refuses the machine route when the staged run is %s", async (_name, edit) => {
    const { env } = makeOfflineEnv(stagedKv(edit));
    await atCutoff(async () => {
      expect(await loadBottleneckV3(await pinPublicSnapshot(env), { guidanceMachineEnabled: true })).toBeNull();
      const machineEnv = { ...env, V213_LINE_PRESENTATION: "text", V213_GUIDANCE_MACHINE_ENABLED: "1" } as never;
      for (const command of [BOTTLENECK_LIST, DETAIL_NVDA]) {
        const answer = await v213PublicLineAnswer(machineEnv, parseQuery(command));
        expect(typeof answer).toBe("string");
        expect(String(answer).startsWith(V3_UNAVAILABLE_PREFIX)).toBe(true);
      }
    });
  });
});
