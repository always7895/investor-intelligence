import type { ParsedQuery } from "../core";
import { publicJson, type StorageEnv } from "../storage";
import type { V21Top20Record } from "../v21/top20";

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
const IGNORED_SYMBOLS = new Set([
  "AI", "TOP", "LINE", "BOT", "CALL", "PUT", "SELL", "BUY", "OPTION",
  "OPTIONS", "IV", "DTE", "BID", "ASK", "YES", "NO", "USD",
]);

function exactKeys(value: Record<string, unknown>, expected: Set<string>): boolean {
  const keys = Object.keys(value);
  return keys.length === expected.size && keys.every((key) => expected.has(key));
}

function finite(value: unknown): value is number {
  return typeof value === "number" && Number.isFinite(value);
}

export function parseV211ResearchUniverse(raw: unknown): V21Top20Record[] | null {
  if (!Array.isArray(raw) || raw.length < 20 || raw.length > 120) return null;
  const result: V21Top20Record[] = [];
  const seen = new Set<string>();
  for (let index = 0; index < raw.length; index += 1) {
    const value = raw[index];
    if (!value || typeof value !== "object" || Array.isArray(value)) return null;
    const item = value as Record<string, unknown>;
    if (!exactKeys(item, RECORD_KEYS)) return null;
    const ticker = String(item.ticker ?? "").toUpperCase();
    if (!/^[A-Z0-9][A-Z0-9.-]{0,14}$/.test(ticker) || seen.has(ticker)) return null;
    seen.add(ticker);
    if (
      item.rank !== index + 1 ||
      !finite(item.serenity_score) ||
      !finite(item.serenity_raw_score) ||
      !finite(item.risk_penalty) ||
      !finite(item.data_quality) ||
      item.serenity_score < 0 || item.serenity_score > 100 ||
      item.data_quality < 0 || item.data_quality > 1 ||
      typeof item.name !== "string" ||
      typeof item.category !== "string" ||
      typeof item.rating !== "string" ||
      item.scoring_version !== "serenity-first-v2.1.0" ||
      item.line_public_eligible !== true ||
      item.provider_scope !== "public_only" ||
      item.owner_watchlist_inherited !== false ||
      !Array.isArray(item.risk_flags) ||
      !Array.isArray(item.evidence) || item.evidence.length < 1 ||
      item.evidence_count !== item.evidence.length ||
      !Number.isInteger(item.source_count) || Number(item.source_count) < 1 ||
      !Number.isFinite(Date.parse(String(item.generated_at ?? ""))) ||
      !Number.isFinite(Date.parse(String(item.as_of ?? "")))
    ) return null;
    if (!item.serenity_factors || typeof item.serenity_factors !== "object" || Array.isArray(item.serenity_factors)) return null;
    const factors = item.serenity_factors as Record<string, unknown>;
    if (!exactKeys(factors, FACTOR_KEYS) || Object.values(factors).some((entry) => !finite(entry))) return null;
    if (!item.aschenbrenner_overlay || typeof item.aschenbrenner_overlay !== "object" || Array.isArray(item.aschenbrenner_overlay)) return null;
    const overlay = item.aschenbrenner_overlay as Record<string, unknown>;
    if (overlay.included_in_serenity_score !== false || !finite(overlay.fit_score)) return null;
    result.push({ ...(item as unknown as V21Top20Record), ticker });
  }
  const ordered = [...result].sort(
    (left, right) =>
      right.serenity_score - left.serenity_score ||
      right.data_quality - left.data_quality ||
      left.ticker.localeCompare(right.ticker),
  );
  return ordered.every((item, index) => item.ticker === result[index]?.ticker) ? result : null;
}

function factorLine(item: V21Top20Record): string {
  const f = item.serenity_factors;
  return `系統因子：需求 ${f.demand_wave ?? 0}｜瓶頸代理 ${f.chokepoint ?? 0}｜定價代理 ${f.pricing_power ?? 0}｜替代摩擦代理 ${f.replacement_friction ?? 0}｜TAM代理 ${f.tam_capture ?? 0}｜估值代理 ${f.valuation_expectations ?? 0}｜證據 ${f.evidence_quality ?? 0}`;
}

function formatResearchDetail(item: V21Top20Record, universeSize: number): string {
  const evidence = item.evidence.slice(0, 3).map((entry) => `• ${entry.title}｜${entry.url}`);
  return [
    `${item.ticker}｜系統量化 universe #${item.rank}/${universeSize}｜系統量化分 ${item.serenity_score}/100｜品質 ${Math.round(item.data_quality * 100)}%｜${item.rating}`,
    "注意：此分數是本專案的 System operationalization，不是 Serenity 本人公布的公式或官方分數。",
    item.rank <= 20 ? "目前狀態：系統量化 Top 20" : "目前狀態：未進系統量化 Top 20（本輪 cutoff 為 #20）",
    `${item.name}｜${item.category}`,
    factorLine(item),
    `系統風險扣分 ${item.risk_penalty}｜風險 ${item.risk_flags.length ? item.risk_flags.join("、") : "無重大結構化旗標"}`,
    `Aschenbrenner：Domain ${item.aschenbrenner_overlay.domain ?? "N/A"}，fit ${item.aschenbrenner_overlay.fit_score}（不計入系統量化分）`,
    "公開證據：",
    ...evidence,
  ].join("\n");
}

function explicitTickers(text: string): string[] {
  const result: string[] = [];
  for (const match of text.matchAll(/(?:^|[^A-Za-z0-9])([A-Z][A-Z0-9]{0,5}(?:[.-][A-Z0-9]{1,4})?)(?=$|[^A-Za-z0-9])/g)) {
    const value = String(match[1] ?? "").toUpperCase();
    if (!value || IGNORED_SYMBOLS.has(value) || result.includes(value)) continue;
    result.push(value);
  }
  return result;
}

function compareRecords(left: V21Top20Record, right: V21Top20Record): string {
  const lf = left.serenity_factors;
  const rf = right.serenity_factors;
  const fields: Array<[string, string]> = [
    ["需求", "demand_wave"], ["瓶頸代理", "chokepoint"], ["定價代理", "pricing_power"],
    ["替代摩擦代理", "replacement_friction"], ["TAM代理", "tam_capture"],
    ["估值代理", "valuation_expectations"], ["證據", "evidence_quality"],
  ];
  return [
    `${left.ticker} vs ${right.ticker}｜公開研究比較（Serenity public-logic 與系統量化分分離）`,
    `${left.ticker}: universe #${left.rank}｜系統量化分 ${left.serenity_score}/100｜品質 ${Math.round(left.data_quality * 100)}%｜系統風險扣分 ${left.risk_penalty}`,
    `${right.ticker}: universe #${right.rank}｜系統量化分 ${right.serenity_score}/100｜品質 ${Math.round(right.data_quality * 100)}%｜系統風險扣分 ${right.risk_penalty}`,
    ...fields.map(([label, key]) => `${label}: ${left.ticker} ${lf[key] ?? 0} vs ${right.ticker} ${rf[key] ?? 0}`),
    "上述數字是 System operationalization；不是 Serenity 本人公布的分數或權重。",
    "Aschenbrenner overlay 為獨立 context，不計入上述系統量化分。",
  ].join("\n");
}

export function v211HelpText(): string {
  return [
    "Investor Intelligence v2.1.3 公開研究問答。",
    "你可以問：",
    "• Top 20",
    "• NVDA 評分 / NVDA 怎麼看 / 為什麼 NVDA",
    "• NVDA vs CRDO 比較",
    "• NVDA 這週 sell call / 每月期權",
    "• 任何其他明確股票代號：若不在已同步系統量化 universe，會交給本機模型的多來源 on-demand 研究層，而不是直接回覆『沒有資料』。",
    "• 最新報告 / 系統狀態 / 通知狀態",
    "系統量化 universe 與公開期權是 deterministic；Serenity 公開方法只以 public-logic fidelity reconstruction 呈現，與專案量化分數分離。",
  ].join("\n");
}

function isGreeting(text: string): boolean {
  return /^(?:你好|您好|哈囉|哈啰|嗨|hello|hi|hey)[!！。. ]*$/i.test(text.trim());
}
function asksComparison(text: string): boolean {
  return /(?:比較|对比|對比|相比|vs\.?|versus|compare)/i.test(text);
}
function asksResearch(text: string): boolean {
  return /(?:怎麼看|怎么看|看法|分析|研究|評分|评分|排名|為什麼|为什么|原因|風險|风险|證據|证据|serenity|aschenbrenner|score|rank|why|research)/i.test(text);
}

export async function v211ResearchAnswer(env: StorageEnv, query: ParsedQuery): Promise<string | null> {
  if (isGreeting(query.normalized)) return v211HelpText();
  if (query.intent === "options") return null;
  const raw = await publicJson<unknown>(env, ["v211:universe:latest"]);
  const universe = parseV211ResearchUniverse(raw);
  if (!universe) {
    if (query.ticker || asksResearch(query.normalized)) {
      return "目前沒有通過驗證的公開系統量化 universe；請等待下一次本機刷新與簽名同步。";
    }
    return null;
  }

  const tickers = explicitTickers(query.normalized);
  if (query.ticker && !tickers.includes(query.ticker)) tickers.unshift(query.ticker);
  if (asksComparison(query.normalized) && tickers.length >= 2) {
    const left = universe.find((item) => item.ticker === tickers[0]);
    const right = universe.find((item) => item.ticker === tickers[1]);
    if (!left || !right) return null;
    return compareRecords(left, right);
  }

  if (query.ticker && (query.intent === "general_qa" || query.intent === "ranking" || query.intent === "source_views" || asksResearch(query.normalized))) {
    const item = universe.find((record) => record.ticker === query.ticker);
    return item ? formatResearchDetail(item, universe.length) : null;
  }

  if (/^(?:研究範圍|研究范围|universe|research universe)$/i.test(query.normalized)) {
    const cutoff = universe[19];
    return `本輪公開系統量化 universe 共 ${universe.length} 檔；Top 20 cutoff 為 ${cutoff?.ticker ?? "N/A"} 系統量化分 ${cutoff?.serenity_score ?? "N/A"}/100。候選發現包含 broad screeners + AI-infrastructure thematic + SEC official-name coverage；theme 本身不加分。此量化公式是專案 operationalization，不等於 Serenity 本人公式。`;
  }
  return null;
}

export function humanizeFallback(answer: string, query: ParsedQuery): string {
  if (answer === "LOCAL_MODEL_NOT_CONFIGURED") {
    return [
      "本機模型橋接尚未啟用，所以這個開放式問題目前無法自由生成回答。",
      "已同步系統量化 universe、Top 20、公開期權、最新報告與系統狀態仍可直接使用。",
      "本機模型橋接啟用後，universe 外的明確股票代號會走多來源 on-demand 研究。",
    ].join("\n");
  }
  if (answer === "LOCAL_MODEL_OFFLINE") {
    return "本機模型橋接目前離線；系統量化 universe、Top 20、期權與報告型問答仍可使用。";
  }
  if (answer === "OPTION_DATA_UNAVAILABLE") {
    return query.ticker
      ? `目前沒有 ${query.ticker} 的可用公開期權快照；可能是本輪 universe 未涵蓋、標的無可用期權，或公開資料擷取失敗。`
      : "目前沒有可用的公開期權快照。";
  }
  if (answer === "OPTION_DATA_STALE") return "公開期權快照已超過 freshness gate，系統拒絕用過期報價提供 sell call / sell put 觀察；請等待下一次刷新。";
  if (answer === "CURRENT_DATA_UNAVAILABLE") return "目前沒有通過 freshness / evidence gate 的即時公開資料，因此系統不會猜測最新數值。";
  return answer;
}
