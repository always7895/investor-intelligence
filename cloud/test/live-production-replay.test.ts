import { it, expect } from "vitest";
import { writeFileSync, existsSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { pinPublicSnapshot } from "../src/v213/public-snapshot";
import { loadV213FreshTop20Report, getV213ReportReference } from "../src/v213/top20-report";
import { asKv, MemoryKv } from "./fake-kv";
import type { ParsedQuery } from "../src/core";
import { execSync } from "node:child_process";

it("live replay against live public bytes or latest sealed snapshot", async () => {
  const kv = new MemoryKv();
  const namespaceId = "96142af40b5d4213862d5483fe3a66da";

  // Fetch live pointer from KV
  let pointerRaw: string | null = null;
  try {
    pointerRaw = execSync(`npx wrangler kv key get "snapshot:current" --namespace-id ${namespaceId}`, {
      cwd: join(__dirname, ".."),
      encoding: "utf8",
      stdio: ["pipe", "pipe", "pipe"],
    }).trim();
  } catch {
    pointerRaw = null;
  }

  let runId = "";
  if (pointerRaw && pointerRaw.startsWith("{")) {
    const pointer = JSON.parse(pointerRaw);
    runId = pointer.run_id;
    kv.values.set("snapshot:current", pointerRaw);

    // Read necessary keys from local snapshot or KV
    const localDir = join(__dirname, `../../state/v213-snapshots/${runId}`);
    const objPath = join(localDir, "objects.json");
    if (existsSync(objPath)) {
      const objects = JSON.parse(readFileSync(objPath, "utf8"));
      for (const [k, v] of Object.entries(objects)) kv.values.set(k, String(v));
    }
  }

  const env = {
    PUBLIC_CACHE: asKv(kv),
    TENANT_PRIVATE_CACHE: asKv(new MemoryKv()),
    EPHEMERAL_SECURITY_CACHE: asKv(new MemoryKv()),
    V213_FIELD_LOCALE: "bilingual",
    V21_TOP20_MAX_AGE_SECONDS: "7200",
  } as never;

  const view = await pinPublicSnapshot(env);
  const q: ParsedQuery = { intent: "ranking", ticker: null, period: "weekly", referenceId: null, normalized: "Top 20" };
  const report = await loadV213FreshTop20Report(env, q);

  const isFresh = report !== null && typeof report === "object";
  const artifactPath = join(__dirname, "../test-live-replay-result.json");
  writeFileSync(
    artifactPath,
    JSON.stringify({
      fresh: isFresh,
      run_id: runId,
      reference: isFresh ? getV213ReportReference(report as never) : null,
      evaluated_at: new Date().toISOString(),
    }, null, 2),
    "utf8"
  );

  expect(isFresh).toBe(true);
});
