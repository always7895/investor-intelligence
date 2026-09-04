import type { V21AdminEnv } from "../v21/admin";
import { parseV21Top20 } from "../v21/top20";
import { parseV213Top20Report } from "./top20-report";

export async function ingestV213Top20Report(
  body: string,
  env: V21AdminEnv,
): Promise<{ run_id: string; report_count: number; format: "v213_seven_fields" }> {
  let raw: unknown;
  try {
    raw = JSON.parse(body);
  } catch {
    throw new Error("V213_TOP20_REPORT_JSON_INVALID");
  }
  const report = parseV213Top20Report(raw);
  if (!report) throw new Error("V213_TOP20_REPORT_SCHEMA_INVALID");

  const pointerRaw = await env.PUBLIC_CACHE.get("snapshot:current", "json");
  if (!pointerRaw || typeof pointerRaw !== "object" || Array.isArray(pointerRaw)) {
    throw new Error("V213_CURRENT_SNAPSHOT_MISSING");
  }
  const runId = String((pointerRaw as Record<string, unknown>).run_id ?? "");
  if (!/^\d{8}T\d{6}Z-[0-9a-f]{12}$/.test(runId)) {
    throw new Error("V213_CURRENT_RUN_ID_INVALID");
  }

  const topRaw = await env.PUBLIC_CACHE.get(`snapshot:${runId}:v21:top20:latest`, "json");
  const top20 = parseV21Top20(topRaw);
  if (!top20) throw new Error("V213_CURRENT_TOP20_INVALID");
  const expected = top20.map((item) => item.ticker);
  const actual = report.records.map((item) => item.ticker);
  if (expected.some((ticker, index) => ticker !== actual[index])) {
    throw new Error("V213_TOP20_REPORT_ORDER_MISMATCH");
  }

  await env.PUBLIC_CACHE.put(
    `snapshot:${runId}:v213:top20-report:latest`,
    JSON.stringify(report),
    { expirationTtl: 259200 },
  );
  return { run_id: runId, report_count: report.records.length, format: "v213_seven_fields" };
}
