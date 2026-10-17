import { extractTicker, normalizeText, type OptionPeriod } from "../core";

export type ResearchProductKind = "card_summary" | "data_report" | "narrative_analysis";
export interface ResearchProductRequest {
  readonly domain: "stock" | "options" | "macro" | null;
  readonly outputKind: ResearchProductKind;
  readonly ticker: string | null;
  readonly top20: boolean;
  readonly period: OptionPeriod;
}
const LABELS: ReadonlyArray<readonly [ResearchProductKind, readonly string[]]> = [
  ["card_summary", ["卡片摘要", "card_summary"]],
  ["data_report", ["完整詳細資料報告", "完整详细资料报告", "詳細資料報告", "详细资料报告", "數據詳報", "数据详报", "data_report"]],
  ["narrative_analysis", ["完整文字分析", "完整文字分析報告", "完整文字分析报告", "深入分析", "narrative_analysis"]],
];
const DOMAIN_LABELS = { stock: "股票", options: "期權", macro: "宏觀" } as const;
const KIND_LABELS = { card_summary: "卡片摘要", data_report: "數據詳報", narrative_analysis: "完整文字分析" } as const;
const SYMBOL = "\\$?[A-Za-z0-9][A-Za-z0-9.-]{0,14}";
const OPTION = "(?:期權|期权|選擇權|选择权|options?)";
const PERIOD = "(?:每週|每周|每月|weekly|monthly)";

type Target = Omit<ResearchProductRequest, "outputKind">;
function explicitSymbol(value: string): string | null {
  // Use the existing symbol/ignored-token rules; a product label does not
  // create a legal company name, issuer identity or private watchlist lookup.
  const candidate = value.replace(/^\$/, "").toUpperCase();
  const extracted = extractTicker(`ticker: ${value}`);
  return extracted === candidate ? extracted : null;
}
function target(raw: string): Target | null {
  const value = raw.trim().replace(/^[:：]\s*|\s*[:：]$/g, "");
  if (!value) return { domain: null, ticker: null, top20: false, period: null };
  if (/^top\s*20$/i.test(value)) return { domain: "stock", ticker: null, top20: true, period: null };
  if (/^(?:宏觀|宏观|macro)$/i.test(value)) return { domain: "macro", ticker: null, top20: false, period: null };
  const stock = new RegExp(`^(?:個股|个股|股票|stock)(?:\\s+(${SYMBOL}))?$`, "i").exec(value);
  if (stock) {
    const ticker = stock[1] ? explicitSymbol(stock[1]) : null;
    return stock[1] && !ticker ? null : { domain: "stock", ticker, top20: false, period: null };
  }
  const prefix = new RegExp(`^(?:(${PERIOD})\\s*)?${OPTION}(?:\\s+(${SYMBOL}))?$`, "i").exec(value);
  const suffix = new RegExp(`^(${SYMBOL})\\s+(?:(${PERIOD})\\s*)?${OPTION}$`, "i").exec(value);
  if (prefix || suffix) {
    const symbol = prefix ? prefix[2] : suffix![1];
    const ticker = symbol ? explicitSymbol(symbol) : null;
    if (symbol && !ticker) return null;
    const periodText = prefix ? prefix[1] : suffix![2];
    const period = periodText ? /每月|monthly/i.test(periodText) ? "monthly" : "weekly" : null;
    return { domain: "options", ticker, top20: false, period };
  }
  // Bare symbols retain the core parser's deliberate uppercase/$ requirement;
  // ordinary prose such as "explain data_report" is not a stock selection.
  if (!/^(?:[A-Z][A-Z0-9.-]{0,14}|\$[A-Za-z0-9][A-Za-z0-9.-]{0,14})$/.test(value)) return null;
  const ticker = extractTicker(value);
  return ticker && ticker === value.replace(/^\$/, "").toUpperCase()
    ? { domain: "stock", ticker, top20: false, period: null } : null;
}

/** Narrow product-command grammar, not a natural-language research classifier.
 * Ordinary analysis, Top20/text/evidence, and conceptual questions stay intact.
 * This request identity is NOT a stored-product manifest or publication grant.
 */
export function parseResearchProductRequest(raw: string): ResearchProductRequest | null {
  if (typeof raw !== "string" || raw.length > 200) return null;
  const text = normalizeText(raw).replace(/^(?:請(?:提供|給我|顯示|查看|開啟)|请(?:提供|给我|显示|查看|开启)|please (?:show|open))\s*/i, "");
  const lower = text.toLowerCase();
  for (const [outputKind, names] of LABELS) {
    for (const name of names) {
      const foldedName = name.toLowerCase();
      const remainders = [];
      if (lower.endsWith(foldedName)) remainders.push(text.slice(0, -name.length));
      if (lower.startsWith(foldedName)) remainders.push(text.slice(name.length));
      for (const remainder of remainders) {
        const selected = target(remainder);
        if (selected) return Object.freeze({ ...selected, outputKind });
      }
    }
  }
  return null;
}

/** The current seal contract has no admitted three-product object set. Refuse
 * explicitly rather than borrowing seven-field text, candidates or model prose.
 * Adding real products requires reviewed/versioned admission and pinned readers;
 * changing this message or adding a direct-key fallback is not that migration.
 */
export function unavailableResearchProduct(request: ResearchProductRequest): string {
  const domain = request.domain ? DOMAIN_LABELS[request.domain] : "尚未指定領域";
  const subject = request.top20 ? "Top20" : request.ticker ? `查詢代號 ${request.ticker}（未核驗證券身分）` : "未指定標的／宏觀整體";
  const period = request.period === "weekly" ? "；每週期權" : request.period === "monthly" ? "；每月期權" : "";
  return [
    "RESEARCH_PRODUCT_NOT_SEALED",
    `要求：${domain}／${KIND_LABELS[request.outputKind]} (${request.outputKind})；${subject}${period}。`,
    "目前封存契約尚未包含這類獨立產物，不能提供已驗證、同輪綁定的該類報告。",
    "七欄卡片、證據詳情與本機財務候選不是完整詳報；不改送摘要或即席模型回答冒充。",
    "既有七欄摘要可另輸入「Top20」或「Top20 文字」。",
  ].join("\n");
}
