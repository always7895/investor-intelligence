/** Traditional Chinese display labels for the source names the pipeline records in English (operator 2026-09-26:
 * project information in Chinese wherever possible). Display only: sealed data, validators and provenance keep the
 * recorded name, and a name without a rule is shown as recorded rather than guessed. */

const EXACT: Record<string, string> = {
  "SEC EDGAR XBRL companyfacts": "SEC EDGAR XBRL 財報資料",
  "SEC XBRL company facts": "SEC XBRL 財報資料",
  "SEC EDGAR submissions": "SEC EDGAR 申報清單",
  "SEC EDGAR full-text search": "SEC EDGAR 全文檢索",
  "SEC EDGAR latest annual report, Item 1 / Item 4": "SEC EDGAR 最新年報（Item 1／Item 4）",
  "Yahoo Finance quarterly income statement (unofficial)": "Yahoo Finance 季度損益表（非官方）",
  "Yahoo Finance adjusted daily close (unofficial)": "Yahoo Finance 還原收盤價（非官方）",
  "Yahoo Finance analyst estimates (unofficial)": "Yahoo Finance 分析師預估（非官方）",
  "Yahoo Finance (unofficial, delayed)": "Yahoo Finance（非官方，延遲）",
  "Yahoo Finance option chain (unofficial, delayed)": "Yahoo Finance 期權鏈（非官方，延遲）",
  "Nasdaq Nordic option chain (exchange public web API, delayed)": "Nasdaq Nordic 期權鏈（交易所公開網頁 API，延遲）",
  "Nasdaq US option chain (public quote page API, delayed; Yahoo fallback)": "Nasdaq 美股期權鏈（公開報價頁 API，延遲；Yahoo 備援）",
};

const PATTERNS: [RegExp, (match: RegExpExecArray) => string][] = [
  [/^SEC (10-[KQ]|20-F|40-F|6-K) RPO recognition timing$/, m => `SEC ${m[1]} 剩餘履約義務認列時程`],
  [/^SEC (10-[KQ]|20-F|40-F) business section$/, m => `SEC ${m[1]} 業務章節`],
  [/^SEC XBRL frames (.+)$/, m => `SEC XBRL 橫斷面資料 ${m[1]}`],
  [/^BLS PPI (.+)$/, m => `美國勞工統計局生產者物價指數 ${m[1]}`],
];

export function sourceZh(source: string | null | undefined): string {
  if (!source) return "未載明";
  if (Object.hasOwn(EXACT, source)) return EXACT[source]!;
  for (const [pattern, label] of PATTERNS) {
    const match = pattern.exec(source);
    if (match) return label(match);
  }
  return source;
}

const QUOTE_BASIS: Record<string, string> = { realtime: "即時", delayed: "延遲", asof_close: "收盤" };
const RIGHTS: Record<string, string> = {
  reviewed_public_access: "已審查的公開取用", candidate_local_review: "候選來源（本機審查）", unadmitted_third_party: "未納入的第三方來源",
  review_before_enable: "啟用前待審查", automated_access_prohibited: "禁止自動擷取",
};
export const quoteBasisZh = (value: string) => QUOTE_BASIS[value] ?? value;
export const rightsZh = (value: string) => RIGHTS[value] ?? value;
