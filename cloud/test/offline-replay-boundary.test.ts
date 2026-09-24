// Known escape-pattern regression guard, NOT a universal execution sandbox.
import { expect, it } from "vitest";
import { readFileSync } from "node:fs";
import { buildSyntheticSealedReplay, SYNTHETIC_RUN } from "./synthetic-sealed-replay-fixture";
import { SNAPSHOT_OBJECT_KEYS, SNAPSHOT_SEAL_KEY } from "../src/v213/snapshot-seal";

it("keeps the two replay suites and fixture free of automatic external access and artifact writes", () => {
  for (const name of ["live-production-replay.test.ts", "v213-signed-snapshot-promotion.test.ts", "synthetic-sealed-replay-fixture.ts"]) {
    const source = readFileSync(new URL(`./${name}`, import.meta.url), "utf8");
    for (const prohibited of [
      /child_process|\bexec(?:Sync|File|FileSync)?\s*\(|\bspawn(?:Sync)?\s*\(/i,
      /\bnpx\b|\bwrangler\b/i,
      /node:(?:fs|fs\/promises|net|http|https|tls|dgram)|from\s+["'](?:fs|net|https?|tls|dgram)["']/,
      /readFile|writeFile|appendFile|mkdir|state[\\/]v213-snapshots|test-live-replay-result/,
      /\bfetch\s*\(|new\s+(?:WebSocket|XMLHttpRequest)\s*\(/,
      /process\.env|\b(?:require|import)\s*\(/,
    ]) expect(source, `${name}: forbidden escape pattern`).not.toMatch(prohibited);
  }
});

it("constructs deterministic independent memory stores with the pointer inserted last", async () => {
  const first = await buildSyntheticSealedReplay();
  const second = await buildSyntheticSealedReplay();
  expect(first.kv).not.toBe(second.kv);
  expect([...first.kv.values]).toEqual([...second.kv.values]);
  expect(first.kv.values.size).toBe(SNAPSHOT_OBJECT_KEYS.length + 2);
  expect([...first.kv.values.keys()].at(-1)).toBe("snapshot:current");
  for (const key of SNAPSHOT_OBJECT_KEYS) expect(first.kv.values.has(`snapshot:${SYNTHETIC_RUN}:${key}`)).toBe(true);
  expect(first.kv.values.has(`snapshot:${SYNTHETIC_RUN}:${SNAPSHOT_SEAL_KEY}`)).toBe(true);
  first.kv.values.set("snapshot:current", "synthetic mutation");
  expect(second.kv.values.get("snapshot:current")).not.toBe("synthetic mutation");
});
