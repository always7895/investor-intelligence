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
  return `需求 ${f.demand_wave ?? 0}｜瓶頸 ${f.chokepoint ?? 0}｜定價 ${f.pricing_power ?? 0}｜替代摩擦 ${f.replacement_friction ?? 0}｜TAM ${f.tam_capture ?? 0}｜估值 ${f.valuation_expectations ?? 0}｜證據 ${f.evidence_quality ?? 0}`;
}

function formatResearchDetail(item: V21Top20Record, universeSize: number): string {
  const evidence = item.evidence.slice(0, 3).map((entry) => `• ${entry.title}｜${entry.url}`);
  return [
    `${item.ticker}｜Serenity-first universe #${item.rank}/${universeSize}｜${item.serenity_score}/100｜品質 ${Math.round(item.data_quality * 100)}%｜${item.rating}`,
    item.rank <= 20 ? "目前狀態：Top 20" : `目前狀態：未進 Top 20（本輪 cutoff 為 #20）`,
    `${item.name}｜${item.category}`,
    factorLine(item),
    `風險扣分 ${item.risk_penalty}｜風險 ${item.risk_flags.length ? item.risk_flags.join("、") : "無重大結構化旗標"}`,
    `Aschenbrenner：Domain ${item.aschenbrenner_overlay.domain ?? "N/A"}，fit ${item.aschenbrenner_overlay.fit_score}（不計入 Serenity 主分）`,
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
    ["需求", "demand_wave"], ["瓶頸", "chokepoint"], ["定價", "pricing_power"],
    ["替代摩擦", "replacement_friction"], ["TAM", "tam_capture"],
    ["估值", "valuation_expectations"], ["證據", "evidence_quality"],
  ];
  return [
    `${left.ticker} vs ${right.ticker}｜Serenity-first 公開研究比較`,
    `${left.ticker}: universe #${left.rank}｜${left.serenity_score}/100｜品質 ${Math.round(left.data_quality * 100)}%｜風險扣分 ${left.risk_penalty}`,
    `${right.ticker}: universe #${right.rank}｜${right.serenity_score}/100｜品質 ${Math.round(right.data_quality * 100)}%｜風險扣分 ${right.risk_penalty}`,
    ...fields.map(([label, key]) => `${label}: ${left.ticker} ${lf[key] ?? 0} vs ${right.ticker} ${rf[key] ?? 0}`),
    "Aschenbrenner overlay 為獨立 context，不計入上述 Serenity 主分。",
  ].join("\n");
}

export function v211HelpText(): string {
  return [
    "Investor Intelligence v2.1.1 已上線公開研究問答。",
    "你可以問：",
    "• Top 20",
    "• NVDA 評分 / NVDA 怎麼看 / 為什麼 NVDA",
    "• NVDA vs CRDO 比較",
    "• NVDA 這週 sell call / 每月期權",
    "• 最新報告 / 系統狀態 / 通知狀態",
    "研究問答只使用已同步的公開研究 universe 與公開期權快照；不讀取持倉、成本、損益或券商資料。",
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

export async function v211ResearchAnswer(
  env: StorageEnv,
  query: ParsedQuery,
): Promise<string | null> {
  if (isGreeting(query.normalized)) return v211HelpText();
  if (query.intent === "options") return null;

  const raw = await publicJson<unknown>(env, ["v211:universe:latest"]);
  const universe = parseV211ResearchUniverse(raw);
  if (!universe) {
    if (query.ticker || asksResearch(query.normalized)) {
      return "目前沒有通過 v2.1.1 驗證的公開研究 universe；請等待下一次本機刷新與簽名同步。";
    }
    return null;
  }

  const tickers = explicitTickers(query.normalized);
  if (query.ticker && !tickers.includes(query.ticker)) tickers.unshift(query.ticker);
  if (asksComparison(query.normalized) && tickers.length >= 2) {
    const left = universe.find((item) => item.ticker === tickers[0]);
    const right = universe.find((item) => item.ticker === tickers[1]);
    if (!left || !right) {
      const missing = [tickers[0], tickers[1]].filter((ticker) => !universe.some((item) => item.ticker === ticker));
      return `本輪公開研究 universe 尚未涵蓋：${missing.join("、")}。這代表未通過本輪候選/SEC/流動性流程，不等於負面評級。`;
    }
    return compareRecords(left, right);
  }

  if (query.ticker && (query.intent === "general_qa" || query.intent === "ranking" || query.intent === "source_views" || asksResearch(query.normalized))) {
    const item = universe.find((record) => record.ticker === query.ticker);
    return item
      ? formatResearchDetail(item, universe.length)
      : `本輪公開研究 universe 中沒有 ${query.ticker}。這表示它沒有進入本輪完整 Serenity 評分集合，不等於系統給予負面評級。`;
  }

  if (/^(?:研究範圍|研究范围|universe|research universe)$/i.test(query.normalized)) {
    const cutoff = universe[19];
    return `本輪公開研究 universe 共 ${universe.length} 檔；Top 20 cutoff 為 ${cutoff?.ticker ?? "N/A"} ${cutoff?.serenity_score ?? "N/A"}/100。候選發現包含 broad screeners + AI-infrastructure thematic discovery，主分公式未因 theme 加分。`;
  }
  return null;
}

export function humanizeFallback(answer: string, query: ParsedQuery): string {
  if (answer === "LOCAL_MODEL_NOT_CONFIGURED") {
    return [
      "目前沒有啟用安全的開放式本機模型通道，所以這個問題無法用自由生成模式回答。",
      "公開研究問答仍可直接使用：Top 20、指定股票評分/原因、兩檔比較、公開期權、最新報告與系統狀態。",
      "輸入「你好」可查看範例。",
    ].join("\n");
  }
  if (answer === "LOCAL_MODEL_OFFLINE") {
    return "安全的本機模型通道目前離線；公開研究 universe、Top 20、期權與報告型問答仍可使用。";
  }
  if (answer === "OPTION_DATA_UNAVAILABLE") {
    return query.ticker
      ? `目前沒有 ${query.ticker} 的可用公開期權快照；可能是本輪 universe 未涵蓋、標的無可用期權，或公開資料擷取失敗。`
      : "目前沒有可用的公開期權快照。";
  }
  if (answer === "OPTION_DATA_STALE") {
    return "公開期權快照已超過 freshness gate，系統拒絕用過期報價提供 sell call / sell put 觀察；請等待下一次刷新。";
  }
  if (answer === "CURRENT_DATA_UNAVAILABLE") {
    return "目前沒有通過 freshness / evidence gate 的即時公開資料，因此系統不會猜測最新數值。";
  }
  return answer;
}
