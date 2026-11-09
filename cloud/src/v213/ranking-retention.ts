import { hasVerifiedSnapshotCustody, type PublicSnapshotView } from "./public-snapshot";
import { v213ReportAgeFresh } from "./report-age";

// Deliberately independent of bottleneck-v3.ts so its loader can import this contract.
const RANKING_KEY = "v213:bottleneck-top20:v3";
export interface RetainedRanking {
  readonly raw: unknown;
  readonly originalAsOf: string;
  /** Historical structural-validation clock only; NEVER the admission/approval clock. */
  readonly parseAt: number;
  readonly observedAt: number;
  readonly notice: string;
}

/** Cadence/quota stops leave snapshot:current pointing to the same immutable seal.
 * Read that actual verified object, never a raw latest key or a caller-supplied body.
 * This is permission to attempt the ordinary structural parser at the ORIGINAL
 * report time, not permission to skip its identity/rights/evidence validation.
 * The caller must label every returned ranking/forecast historical and must keep
 * observedAt (not parseAt) for time-limited machine approval/admission decisions.
 * Invalid/missing custody is a real bootstrap prerequisite, not a fallback ranking.
 */
export async function readRetainedRanking(view: PublicSnapshotView, observedAt = Date.now()): Promise<RetainedRanking | null> {
  if (!Number.isFinite(observedAt) || Math.abs(observedAt) > 8_640_000_000_000_000
    || !hasVerifiedSnapshotCustody(view, RANKING_KEY)) return null;
  // text() performs the lazy blob digest verification; manifest membership alone
  // is NOT verification of that blob. Never take a separate direct KV read.
  const body = await view.text([RANKING_KEY]);
  if (body === null) return null;
  let raw: unknown;
  try { raw = JSON.parse(body); } catch { return null; }
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) return null;
  const doc = raw as Record<string, unknown>;
  if (doc.schema !== "v213-bottleneck-top20-v3-sealed" || typeof doc.generated_at !== "string"
    || !/^(?!0000)\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d{3})?Z$/.test(doc.generated_at)) return null;
  const parseAt = Date.parse(doc.generated_at);
  if (!Number.isFinite(parseAt) || parseAt > observedAt
    || new Date(parseAt).toISOString() !== (doc.generated_at.includes(".") ? doc.generated_at : doc.generated_at.replace("Z", ".000Z"))) return null;
  // Only the ranking age gate can be relaxed. Fresh reports keep the normal path.
  if (v213ReportAgeFresh([doc.generated_at], observedAt)) return null;
  if (!Array.isArray(doc.top) || doc.top.length < 10 || doc.top.length > 20) return null;
  const symbols = new Set<string>();
  for (const row of doc.top) {
    if (!row || typeof row !== "object" || typeof row.symbol !== "string" || !row.symbol.trim() || symbols.has(row.symbol)) return null;
    symbols.add(row.symbol);
  }
  const notice = `歷史保留排名（原始資料時間 ${doc.generated_at}）：目前未取得新的有效封存排行，保留最後驗證的排名。非即時資料；訂單、預估與情境僅代表該時間，不代表目前核准、權利或投資建議。`;
  return { raw, originalAsOf: doc.generated_at, parseAt, observedAt, notice };
}
