import type { ParsedQuery } from "../core";
import { publicJson, type StorageEnv } from "../storage";

export type V21ScoringVersion =
  | "serenity-first-v2.1.0"
  | "system-operationalization-v2.1.3-diversified";

export interface V21Evidence {
  source_id: string;
  tier: string;
  claim_type: string;
  title: string;
  url: string;
  as_of: string;
}

export interface V21Top20Record {
  ticker: string;
  name: string;
  serenity_score: number;
  serenity_raw_score: number;
  risk_penalty: number;
  data_quality: number;
  rating: string;
  category: string;
  serenity_factors: Record<string, number>;
  risk_flags: string[];
  aschenbrenner_overlay: {
    domain: "A" | "B" | "C" | null;
    fit_score: number;
    included_in_serenity_score: false;
    attribution: string;
  };
  evidence: V21Evidence[];
  evidence_count: number;
  source_count: number;
  scoring_version: V21ScoringVersion;
  line_public_eligible: true;
  provider_scope: "public_only";
  owner_watchlist_inherited: false;
  rank: number;
  generated_at: string;
  as_of: string;
}

const RECORD_KEYS = new Set([
  "ticker", "name", "serenity_score", "serenity_raw_score", "risk_penalty",
  "data_quality", "rating", "category", "serenity_factors", "risk_flags",
  "aschenbrenner_overlay", "evidence", "evidence_count", "source_count",
  "scoring_version", "line_public_eligible", "provider_scope",
  "owner_watchlist_inherited", "rank", "generated_at", "as_of",
]);

const FACTOR_KEYS = new Set([
  "demand_wave", "chokepoint", "pricing_power", "replacement_friction",
  "tam_capture", "valuation_expectations", "evidence_quality",
]);

const EVIDENCE_KEYS = new Set([
  "source_id", "tier", "claim_type", "title", "url", "as_of",
]);

const OVERLAY_KEYS = new Set([
  "domain", "fit_score", "included_in_serenity_score", "attribution",
]);

const SCORING_VERSIONS = new Set<V21ScoringVersion>([
  "serenity-first-v2.1.0",
  "system-operationalization-v2.1.3-diversified",
]);

function exactKeys(value: Record<string, unknown>, expected: Set<string>): boolean {
  const keys = Object.keys(value);
  return keys.length === expected.size && keys.every((key) => expected.has(key));
}

function finite(value: unknown): value is number {
  return typeof value === "number" && Number.isFinite(value);
}

function validTimestamp(value: unknown): value is string {
  return typeof value === "string" && value.length <= 40 && Number.isFinite(Date.parse(value));
}

function validEvidence(value: unknown): value is V21Evidence {
  if (!value || typeof value !== "object" || Array.isArray(value)) return false;
  const item = value as Record<string, unknown>;
  if (!exactKeys(item, EVIDENCE_KEYS)) return false;
  if (
    typeof item.source_id !== "string" || !item.source_id ||
    typeof item.tier !== "string" ||
    typeof item.claim_type !== "string" ||
    typeof item.title !== "string" ||
    typeof item.url !== "string" ||
    !validTimestamp(item.as_of)
  ) return false;
  try {
    const url = new URL(item.url);
    return url.protocol === "https:" && !url.username && !url.password;
  } catch {
    return false;
  }
}

export function parseV21Top20(raw: unknown): V21Top20Record[] | null {
  if (!Array.isArray(raw) || raw.length !== 20) return null;
  const result: V21Top20Record[] = [];
  const seen = new Set<string>();

  for (let index = 0; index < raw.length; index += 1) {
    const value = raw[index];
    if (!value || typeof value !== "object" || Array.isArray(value)) return null;
    const item = value as Record<string, unknown>;
    if (!exactKeys(item, RECORD_KEYS)) return null;
    const ticker = String(item.ticker ?? "").toUpperCase();
    if (!/^[A-Z0-9][A-Z0-9.-]{0,14}$/.test(ticker) || ticker.includes("..") || seen.has(ticker)) return null;
    seen.add(ticker);
    const scoringVersion = item.scoring_version as V21ScoringVersion;
    const diversified = scoringVersion === "system-operationalization-v2.1.3-diversified";

    if (
      item.rank !== index + 1 ||
      !finite(item.serenity_score) || !finite(item.serenity_raw_score) ||
      !finite(item.risk_penalty) || !finite(item.data_quality) ||
      item.serenity_score < 0 || item.serenity_score > 100 ||
      item.serenity_raw_score < 0 || item.serenity_raw_score > 100 ||
      item.risk_penalty < 0 || item.data_quality < 0 || item.data_quality > 1 ||
      typeof item.name !== "string" || typeof item.rating !== "string" ||
      typeof item.category !== "string" || !SCORING_VERSIONS.has(scoringVersion) ||
      item.line_public_eligible !== true || item.provider_scope !== "public_only" ||
      item.owner_watchlist_inherited !== false || !validTimestamp(item.generated_at) ||
      !validTimestamp(item.as_of) || !Array.isArray(item.risk_flags) ||
      item.risk_flags.some((entry) => typeof entry !== "string") ||
      !Array.isArray(item.evidence) || item.evidence.length < (diversified ? 2 : 1) ||
      item.evidence.some((entry) => !validEvidence(entry)) ||
      item.evidence_count !== item.evidence.length ||
      !Number.isInteger(item.source_count) || Number(item.source_count) < (diversified ? 2 : 1)
    ) return null;

    const uniqueSources = new Set((item.evidence as V21Evidence[]).map((entry) => entry.source_id));
    if (diversified && uniqueSources.size !== item.source_count) return null;

    if (!item.serenity_factors || typeof item.serenity_factors !== "object" || Array.isArray(item.serenity_factors)) return null;
    const factors = item.serenity_factors as Record<string, unknown>;
    if (!exactKeys(factors, FACTOR_KEYS) || Object.values(factors).some((entry) => !finite(entry))) return null;
    if (diversified && (factors.chokepoint !== 0 || factors.replacement_friction !== 0)) return null;

    if (!item.aschenbrenner_overlay || typeof item.aschenbrenner_overlay !== "object" || Array.isArray(item.aschenbrenner_overlay)) return null;
    const overlay = item.aschenbrenner_overlay as Record<string, unknown>;
    if (
      !exactKeys(overlay, OVERLAY_KEYS) ||
      !["A", "B", "C", null].includes(overlay.domain as string | null) ||
      !finite(overlay.fit_score) || overlay.fit_score < 0 || overlay.fit_score > 100 ||
      overlay.included_in_serenity_score !== false ||
      overlay.attribution !== "system_operationalization_not_aschenbrenner_stock_score"
    ) return null;

    result.push({ ...(item as unknown as V21Top20Record), ticker });
  }

  const ordered = [...result].sort(
    (left, right) =>
      right.serenity_score - left.serenity_score ||
      right.data_quality - left.data_quality ||
      left.ticker.localeCompare(right.ticker),
  );
  if (ordered.some((item, index) => item.ticker !== result[index]?.ticker)) return null;
  return result;
}

function scoreLabel(item: V21Top20Record): string {
  return item.scoring_version === "system-operationalization-v2.1.3-diversified"
    ? "系統量化分"
    : "舊版系統量化分";
}

export function formatV21Top20(records: V21Top20Record[], title: string): string {
  const diversified = records.every((item) => item.scoring_version === "system-operationalization-v2.1.3-diversified");
  return [
    title,
    diversified
      ? "Serenity 公開邏輯高擬真重建 + 多來源系統量化（非 Serenity 官方公式、排名或背書；非個人化投資建議）"
      : "舊版專案系統量化（非 Serenity 官方公式或背書；非個人化投資建議）",
    ...records.map(
      (item) =>
        `${item.rank}. ${item.ticker}｜${scoreLabel(item)} ${item.serenity_score}/100｜品質 ${Math.round(item.data_quality * 100)}%｜${item.rating}`,
    ),
    "Aschenbrenner A/B/C 是獨立 infrastructure overlay，不計入系統量化分。",
    diversified
      ? "101 個來源是受審查目錄；本輪 live source federation 另外驗證實際使用家族，Yahoo/yfinance 僅為 T3 觀測。"
      : "來源目錄不等於本輪實際取用；未啟用來源不會冒充已取用。",
  ].join("\n");
}

export function formatV21Top20Detail(item: V21Top20Record): string {
  const factors = item.serenity_factors;
  const evidence = item.evidence.slice(0, 5).map((entry) => `• ${entry.title}｜${entry.url}`);
  return [
    `#${item.rank} ${item.ticker}｜${scoreLabel(item)} ${item.serenity_score}/100｜資料品質 ${Math.round(item.data_quality * 100)}%`,
    `${item.name}｜${item.category}`,
    `需求 ${factors.demand_wave ?? 0}｜瓶頸 ${factors.chokepoint ?? 0}｜定價 ${factors.pricing_power ?? 0}｜替代摩擦 ${factors.replacement_friction ?? 0}`,
    `TAM ${factors.tam_capture ?? 0}｜估值 ${factors.valuation_expectations ?? 0}｜證據 ${factors.evidence_quality ?? 0}｜風險扣分 ${item.risk_penalty}`,
    `風險：${item.risk_flags.length ? item.risk_flags.join("、") : "無重大結構化旗標"}`,
    `Aschenbrenner：Domain ${item.aschenbrenner_overlay.domain ?? "N/A"}，fit ${item.aschenbrenner_overlay.fit_score}（不計入系統量化分）`,
    "公開證據：",
    ...evidence,
  ].join("\n");
}

function asksV21Detail(query: ParsedQuery): boolean {
  if (!query.ticker) return false;
  return /(?:為什麼|为什么|原因|證據|证据|評分|评分|score|ranking|rank|why)/i.test(query.normalized);
}

export async function v21Top20Answer(env: StorageEnv, query: ParsedQuery): Promise<string | null> {
  if (query.intent !== "ranking" && !asksV21Detail(query)) return null;
  const records = parseV21Top20(await publicJson<unknown>(env, ["v21:top20:latest"]));
  if (!records) return "目前沒有通過嚴格驗證的 v2.1 公開 Top 20。";
  if (query.ticker) {
    const item = records.find((record) => record.ticker === query.ticker);
    return item ? formatV21Top20Detail(item) : `目前 Top 20 中沒有 ${query.ticker}。`;
  }
  return formatV21Top20(records, "Investor Intelligence v2.1 公開 Top 20");
}
