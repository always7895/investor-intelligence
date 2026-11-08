/** Source-tagged legacy seven-column Top20 display names.
 * Reviewed from the local 2026-11-08 public identity-shard cache (ZHWIKI/WIKIDATA_LABEL)
 * and the repository's config/company-zh-names-v1.json. This is a presentation
 * allowlist, NOT a new admission source or a translation algorithm.
 * Bind each label to the exact historical issuer spelling and listing to avoid
 * carrying a ticker-only label across issuer changes; never guess missing names. */
const SOURCES = {
  ZHWIKI: "中文維基百科",
  WIKIDATA_LABEL: "維基數據中文名稱",
} as const;

type Source = keyof typeof SOURCES;
interface ReviewedName { readonly issuer: string; readonly nameZh: string; readonly source: Source }
const REVIEWED: Readonly<Record<string, ReviewedName>> = Object.freeze({
  BBY: { issuer: "BEST BUY CO INC", nameZh: "百思買", source: "ZHWIKI" },
  CLS: { issuer: "CELESTICA INC", nameZh: "天弘科技", source: "ZHWIKI" },
  MU: { issuer: "MICRON TECHNOLOGY INC", nameZh: "美光科技", source: "ZHWIKI" },
  SMCI: { issuer: "Super Micro Computer, Inc.", nameZh: "美超微電腦", source: "ZHWIKI" },
  ADM: { issuer: "Archer-Daniels-Midland Co", nameZh: "阿徹丹尼爾斯米德蘭", source: "ZHWIKI" },
  ALL: { issuer: "ALLSTATE CORP", nameZh: "好事達", source: "WIKIDATA_LABEL" },
  COF: { issuer: "CAPITAL ONE FINANCIAL CORP", nameZh: "第一資本", source: "ZHWIKI" },
  CVS: { issuer: "CVS HEALTH Corp", nameZh: "CVS健康", source: "ZHWIKI" },
  NEM: { issuer: "NEWMONT Corp /DE/", nameZh: "紐蒙特黃金", source: "ZHWIKI" },
  PBR: { issuer: "PETROBRAS - PETROLEO BRASILEIRO SA", nameZh: "巴西石油", source: "ZHWIKI" },
  // PBR-A is the preferred ADR class of the SAME named issuer, not another company.
  "PBR-A": { issuer: "PETROBRAS - PETROLEO BRASILEIRO SA", nameZh: "巴西石油", source: "ZHWIKI" },
  WDC: { issuer: "WESTERN DIGITAL CORP", nameZh: "威騰電子", source: "ZHWIKI" },
  FSLR: { issuer: "FIRST SOLAR, INC.", nameZh: "第一太陽能", source: "WIKIDATA_LABEL" },
});
const canonicalIssuer = (value: string) => value.normalize("NFKC").toUpperCase().replace(/[^A-Z0-9]/g, "");

export function verifiedLegacyCompanyName(ticker: string, originalIssuerName: string): string | null {
  const reviewed = Object.hasOwn(REVIEWED, ticker) ? REVIEWED[ticker] : undefined;
  if (!reviewed || canonicalIssuer(reviewed.issuer) !== canonicalIssuer(originalIssuerName)) return null;
  return reviewed.nameZh + "（" + SOURCES[reviewed.source] + "）";
}

export function legacyCompanyNameLabel(ticker: string, originalIssuerName: string): string {
  return verifiedLegacyCompanyName(ticker, originalIssuerName)
    ?? "未完成來源核對（保留原文，不猜譯）";
}
