/** Human-facing, fail-closed Chinese labels for public LINE status enums.
 * Wire values are NEVER modified here; only the rendered label is translated.
 * Unknown/future codes must not escape into a user-visible text node.
 */
const STATUS_ZH: Readonly<Record<string, string>> = Object.freeze({
  OK: "正常", PASS: "正常", FAIL: "未通過", UNKNOWN: "資料暫不可用",
  AVAILABLE: "可提供", UNAVAILABLE: "資料暫不可用", WITHHELD: "資料暫不提供",
  // Public LINE presentation only. Raw data and audit enums are kept intact.
  SYNTHETIC_EDUCATIONAL: "教學模擬",
  HISTORY_YOY_V1: "歷史營收年增外推模型",
  OFFICIAL_FISCAL_CALENDAR: "官方財季曆",
  ISSUER_PRESENTATION: "發行人簡報",
  SEC_8K_EXHIBIT: "美國證交會 8-K 申報附件",
  SEC_6K_EXHIBIT: "美國證交會 6-K 申報附件",
  OFFICIAL_FINANCIAL_STATEMENT: "官方財務報表",
  ISSUER_EARNINGS_RELEASE: "公司財報新聞稿",
  SEC_WIRE_IR: "美國證交會／新聞稿／公司投資人關係",
  SUPPRESSED_BY_SEALED_PROMOTION: "封存發布時限制顯示",
  RECOGNITION_24M: "24 個月認列時程",
  SINGLE_SOURCE: "單一供應來源",
  SEMI_MONOPOLY: "實質半寡占",
  CURRENT_DATA_STALE: "公開資料已逾時",
  NOT_CONFIGURED: "尚未設定",
  NOT_CONNECTED: "未連線",
  PUBLIC_SNAPSHOT_ONLY: "僅使用公開封存資料",
  UNBOUNDED: "無固定上限",
  NO_UNDERLYING_PRICE: "暫無標的價格",
  NO_LISTED_OPTIONS: "無掛牌選擇權",
  NO_ELIGIBLE_LIQUID_QUOTE: "暫無流動性足夠的報價",
  CHAIN_PROVIDER_ERROR: "資料來源暫時無法取得",
  PROVIDER_ERROR: "資料來源暫時無法取得",
  DEAL_PENDING_TARGET: "併購進行中，暫停選擇權建議",
  DISTRIBUTION_IN_WINDOW: "分拆後尚無經驗證的調整價格，暫不計算（不視為零）",
  NO_EXPIRATION_IN_WINDOW: "指定期間內無到期合約",
  NO_CANDIDATES: "暫無符合條件的候選",
  NO_DATA: "暫無資料", NOT_FOUND: "查無資料",
  OPTION_RIGHTS_NOT_ADMITTED: "期權資料未通過公開驗收",
  OPTION_DATA_NOT_ADMITTED: "期權資料未通過公開驗收",
  OPTION_DATA_UNAVAILABLE: "期權報價不可用",
  IDENTIFIER_UNAVAILABLE: "識別代號暫不可用",
  COMPANY_NAME_UNAVAILABLE: "公司名稱暫不可用",
  MACRO_TOP5_SHORTFALL: "TOP5合格產業不足",
  MACRO_CARD_UNAVAILABLE: "產業卡片暫不可用",
  MACRO_DEEP_UNAVAILABLE: "產業深度分析暫不可用",
  MACRO_PRODUCT_NOT_SEALED: "宏觀資料尚未封存",
  UNKNOWN_STRATEGY: "未支援的策略",
  OPTION_DATA_NOT_FOUND: "查無公開期權報價",
  COVERAGE_SCHEMA_INVALID: "來源資料未通過驗證",
  COVERAGE_STALE: "來源資料已逾時",
  COVERAGE_ABSENT: "來源資料未封存",
  SNAPSHOT_UNAVAILABLE: "快照暫不可用",
  ADMITTED_TOP5: "已通過 TOP5 准入",
  SHORTFALL: "符合條件的資料不足",
  RESOLVED: "身分已核對", IDENTITY_RESOLVED: "身分已核對",
  QUOTE_UNAVAILABLE: "報價暫不可用",
  IDENTITY_FALLBACK_SEC_CACHE: "採用身分備援資料",
  IDENTITY_CATALOG_UNAVAILABLE: "身分資料目錄暫不可用",
  IDENTITY_CONFLICT: "身分資料存在衝突",
  IDENTITY_CONFLICT_UNRESOLVED: "身分資料衝突，暫不解析",
  NEEDS_MARKET_SELECTION: "請選擇掛牌市場",
  MARKET_AMBIGUOUS: "市場資訊不明確",
  INVALID_REQUEST: "查詢格式不合規",
  CATALOG_PRESENT: "目錄有資料", CATALOG_UNAVAILABLE: "目錄暫不可用",
  LIMITED_RESEARCH_CANDIDATE: "研究候選（未完成獨立核實）",
  TEST_ONLY: "僅供測試展示",
  ADMITTED: "已通過驗收", NOT_ADMITTED: "未通過驗收",
  QUALIFIED: "符合條件", LOW_VOLUME: "成交量不足",
  LOW_OI: "未平倉量不足", WIDE_SPREAD: "買賣價差過大",
  WITHIN_CYCLE_WINDOW: "符合週期天數", OUTSIDE_CYCLE_WINDOW: "超出週期天數",
  NO_REVENUE_HISTORY: "缺營收歷史", INSUFFICIENT_EVIDENCE: "證據不足",
  NO_MATCHING_REVENUE: "缺同期營收", INSUFFICIENT_COVERAGE: "訂單覆蓋不足",
  ESTIMATE: "估計值", CURRENT: "目前資料", STALE: "資料已逾時", INVALID: "資料無效",
  VERIFIED: "已核驗", UNVERIFIED: "尚未核驗", PENDING: "待處理",
  ACTIVE: "進行中", INACTIVE: "未啟用",
  SUPPORTED: "已獲證據支持", INFERENCE: "推論", CONTEXT_ONLY: "僅供背景參考",
  NOT_A_COMPANY_FINDING: "非個股已驗證結論",
  UNPROVEN: "尚未證實", UNRANKED: "尚未評定",
});

/** Unknown values deliberately do not echo the code or arbitrary live text. */
export function statusLabelZh(code: unknown): string {
  if (typeof code !== "string" || !Object.prototype.hasOwnProperty.call(STATUS_ZH, code)) return "資料暫不可用";
  return STATUS_ZH[code]!;
}

/** Strip machine-code prefixes from free-form diagnostic text, preserving the explanation. */
export function humanizeStatusText(input: string): string {
  return input
    .replace(/\b[A-Z][A-Z0-9]*(?:_[A-Z0-9]+){1,}\b/g, code => statusLabelZh(code))
    .replace(/(?<![A-Za-z0-9/_-])(?:UNAVAILABLE|WITHHELD|AVAILABLE|SUPPORTED|INFERENCE|UNPROVEN|UNRANKED|UNKNOWN|INVALID|UNBOUNDED)(?![A-Za-z0-9/_-])/g,
      code => statusLabelZh(code))
    .replace(/([\u3400-\u9fff]):[ \t]*/g, "$1：");
}

const LINE_DISPLAY_FIELDS: Readonly<Record<string, true>> = { text: true, altText: true, label: true, title: true, displayText: true };

/** Last-mile display localization. Keep postback data, URI destinations, machine evidence and all input objects unchanged.
 * Applies to text, Flex altText, and nested visible label/title/text/displayText nodes only. */
export function localizeLineMessages<T>(messages: readonly T[]): T[] {
  const walk = (node: unknown): unknown => {
    if (Array.isArray(node)) return node.map(walk);
    if (node === null || typeof node !== "object") return node;
    const out: Record<string, unknown> = {};
    for (const [key, value] of Object.entries(node)) {
      out[key] = key === "data" || key === "postback" ? value
        : typeof value === "string" && Object.hasOwn(LINE_DISPLAY_FIELDS, key) ? localizeObservedStatusText(value) : walk(value);
    }
    return out;
  };
  return messages.map(message => walk(message) as T);
}

/** Known status tokens observed in public product render audits. Unlike the broad
 * humanizer, this last-mile guard does not rewrite opaque application/test codes
 * whose semantics require their own product-specific error handling. */
const LINE_OBSERVED_CODES = new Set([
  "SYNTHETIC_EDUCATIONAL", "HISTORY_YOY_V1", "OFFICIAL_FISCAL_CALENDAR",
  "ISSUER_PRESENTATION", "SEC_8K_EXHIBIT", "SEC_6K_EXHIBIT",
  "OFFICIAL_FINANCIAL_STATEMENT", "ISSUER_EARNINGS_RELEASE", "SEC_WIRE_IR",
  "SUPPRESSED_BY_SEALED_PROMOTION", "RECOGNITION_24M", "CURRENT_DATA_STALE",
  "NOT_CONFIGURED", "NOT_CONNECTED", "PUBLIC_SNAPSHOT_ONLY",
  "SINGLE_SOURCE", "SEMI_MONOPOLY", "INSUFFICIENT_EVIDENCE",
]);
export function localizeObservedStatusText(value: string): string {
  return value.replace(/\b[A-Z][A-Z0-9]{2,}(?:_[A-Z0-9]+){1,}\b/g, code =>
    LINE_OBSERVED_CODES.has(code) ? statusLabelZh(code) : code);
}
