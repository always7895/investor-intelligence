// F06-REPLAY-GATE-BINDING (Worker half): the pre-KV replay gate's guidance_machine_probe (reader contract v4) over the
// committed F06 staged run, loaded into a memory KV exactly as live-kv-replay.test.ts loads a staged run. The probe is
// the shared helper the gate runs; the clock is pinned to the declared historical AUTO cutoff and restored. Good run:
// ADMITTED. Tampered or missing binding or report: REFUSED. Run no longer sealed: ABSENT (the gate then fails on
// INTEGRITY_SEALED and on the missing admission). A sealed non-machine run (no binding in the seal): ABSENT with
// integrity "sealed", so the helper never runs the machine loader on a non-machine tier. Synthetic historical data only; no network, native or live proof.
import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import { BOTTLENECK_V3_KEY } from "../src/v213/bottleneck-v3";
import { pinPublicSnapshot } from "../src/v213/public-snapshot";
import { GUIDANCE_BINDING_KEY } from "../src/v213/revenue-guidance-machine";
import { SNAPSHOT_LAZY_BLOB_PREFIX, SNAPSHOT_SEAL_KEY } from "../src/v213/snapshot-seal";
import { MemoryKv } from "./fake-kv";
import { probeGuidanceMachine, type GuidanceMachineProbe } from "./helpers/guidance-machine-probe";
import { buildSyntheticSealedReplay, makeOfflineEnv, SYNTHETIC_NOW } from "./synthetic-sealed-replay-fixture";

interface StagedReplay { run_id: string; index: Record<string, string>; files: Record<string, string>; }
const replay = JSON.parse(readFileSync(new URL("./fixtures/revenue-guidance-f06-sealed-replay.json", import.meta.url), "utf8")) as StagedReplay;
const auto = JSON.parse(readFileSync(new URL("../../tests/fixtures/revenue-guidance-machine-auto-functional.json", import.meta.url), "utf8")) as {
  report: string; binding: string;
};
const NOW = Date.parse("2026-02-27T13:00:00Z");
const PREFIX = `snapshot:${replay.run_id}:`;
const sha256 = (text: string) => createHash("sha256").update(text, "utf8").digest("hex");
const utf8Bytes = (text: string) => new TextEncoder().encode(text).byteLength;

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
const blobKey = (logicalKey: string) => SNAPSHOT_LAZY_BLOB_PREFIX + required(seal.objects[logicalKey], `sealed ${logicalKey}`).sha256;
/** Re-seal the staged run over another binding blob so its digest, the seal and the pointer all hold. */
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
// Bound to other report bytes: the machine selection cannot resolve it against the sealed report.
const producerBinding = JSON.parse(auto.binding) as { report_sha256: string };
const REPLAYED_BINDING = auto.binding.replace(`"report_sha256":"${producerBinding.report_sha256}"`,
  `"report_sha256":"${producerBinding.report_sha256.slice(0, -1)}${producerBinding.report_sha256.endsWith("0") ? "1" : "0"}"`);

async function probeAt(edit?: (values: Map<string, string>) => void): Promise<{ probe: GuidanceMachineProbe; privateReads: number }> {
  const { env, privateKv, securityKv } = makeOfflineEnv(stagedKv(edit));
  const realNow = Date.now;
  Date.now = () => NOW;
  try {
    const probe = await probeGuidanceMachine(await pinPublicSnapshot(env));
    return { probe, privateReads: privateKv.reads + securityKv.reads };
  } finally { Date.now = realNow; }
}

describe("F06 pre-KV replay: guidance_machine_probe over the staged F06 run", () => {
  it("reports the sealed machine binding ADMITTED at the cutoff without touching private or security KV", async () => {
    expect(REPLAYED_BINDING).not.toBe(auto.binding);
    expect(await probeAt()).toEqual({ probe: "ADMITTED", privateReads: 0 });
  });

  it.each<[string, (values: Map<string, string>) => void, GuidanceMachineProbe]>([
    ["binding-blob-altered", values => { values.set(blobKey(GUIDANCE_BINDING_KEY), auto.binding + " "); }, "REFUSED"],
    ["binding-blob-missing", values => { values.delete(blobKey(GUIDANCE_BINDING_KEY)); }, "REFUSED"],
    ["report-blob-altered", values => { values.set(blobKey(BOTTLENECK_V3_KEY), auto.report + " "); }, "REFUSED"],
    ["binding-replayed-and-resealed", values => { resealBinding(values, REPLAYED_BINDING); }, "REFUSED"],
    ["pointer-missing", values => { values.delete("snapshot:current"); }, "ABSENT"],
  ])("reports %s as the expected non-admitted state", async (_name, edit, expected) => {
    expect((await probeAt(edit)).probe).toBe(expected);
  });

  it("reports a sealed run without the machine binding as ABSENT (non-machine tiers unchanged)", async () => {
    const { kv, seal } = await buildSyntheticSealedReplay();
    expect(Object.keys(JSON.parse(seal.text).objects)).not.toContain(GUIDANCE_BINDING_KEY);
    const { env, privateKv, securityKv } = makeOfflineEnv(kv);
    const realNow = Date.now;
    Date.now = () => Date.parse(SYNTHETIC_NOW);
    try {
      const view = await pinPublicSnapshot(env);
      expect(view.integrity).toBe("sealed");
      expect(await probeGuidanceMachine(view)).toBe("ABSENT");
    } finally { Date.now = realNow; }
    expect(privateKv.reads + securityKv.reads).toBe(0);
  });
});
