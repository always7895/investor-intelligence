/** UI-R3 display-only contracts. No network, no real markets, no snapshot writes. */
import { describe, expect, it } from "vitest";
import { formatCount, formatCurrency, formatDate, formatPercent, formatTaipeiTimestamp } from "../src/v213/line-formatters";
import { statusLabelZh, humanizeStatusText } from "../src/v213/status-labels";
import { LINE_THEME as T, altSummary, menuAction, noticeBanner, noticeText, shortActionLabel, shortAltText } from "../src/v213/line-theme";

const nodes = (value: any): any[] => value == null || typeof value !== "object" ? []
  : Array.isArray(value) ? value.flatMap(nodes) : [value, ...Object.values(value).flatMap(nodes)];

function luminance(color: string): number {
  const values = [1, 3, 5].map(i => parseInt(color.slice(i, i + 2), 16) / 255)
    .map(x => x <= 0.04045 ? x / 12.92 : ((x + 0.055) / 1.055) ** 2.4);
  return values[0]! * 0.2126 + values[1]! * 0.7152 + values[2]! * 0.0722;
}
function contrast(a: string, b: string): number {
  const x = luminance(a), y = luminance(b);
  return (Math.max(x, y) + 0.05) / (Math.min(x, y) + 0.05);
}
describe("UI-R3 status presentation (wire values remain unchanged)", () => {
  it.each([
    ["OK", "正常"], ["PASS", "正常"],
    ["NO_UNDERLYING_PRICE", "暫無標的價格"],
    ["NO_LISTED_OPTIONS", "無掛牌選擇權"],
    ["NO_ELIGIBLE_LIQUID_QUOTE", "暫無流動性足夠的報價"],
    ["CHAIN_PROVIDER_ERROR", "資料來源暫時無法取得"],
    ["PROVIDER_ERROR", "資料來源暫時無法取得"],
    ["DEAL_PENDING_TARGET", "併購進行中，暫停選擇權建議"],
    ["UNAVAILABLE", "資料暫不可用"],
    ["QUOTE_UNAVAILABLE", "報價暫不可用"],
  ])("%s displays %s", (code, wanted) => expect(statusLabelZh(code)).toBe(wanted));
  it("uses neutral fallback without echoing unknown or malicious input", () => {
    for (const value of [null, undefined, {}, 123, "", "NEW_FUTURE_STATUS", "<script>alert(1)</script>"])
      expect(statusLabelZh(value)).toBe("資料暫不可用");
    expect(humanizeStatusText("狀態 NO_LISTED_OPTIONS｜RPO 123")).toBe("狀態 無掛牌選擇權｜RPO 123");
    expect(humanizeStatusText("QUOTE_UNAVAILABLE（NO_UNDERLYING_PRICE）")).toBe("報價暫不可用（暫無標的價格）");
  });
  it("notice banners have a 4px rail, WCAG AA text, and matching text-mode warning", () => {
    const tones = {
      caution: [T.paleCaution, T.caution],
      negative: [T.paleNegative, T.negative],
      info: [T.accentTint, T.accent],
    } as const;
    for (const [kind, [bg, fg]] of Object.entries(tones)) {
      const banner: any = noticeBanner(kind as keyof typeof tones, "併購進行中", "請核對封存來源");
      expect(banner.backgroundColor).toBe(bg);
      expect(banner.contents[0].width).toBe("4px");
      expect(banner.contents[0].backgroundColor).toBe(fg);
      const labels = nodes(banner).filter(n => n.type === "text");
      expect(labels.some(n => n.text === "併購進行中" && n.size === "sm" && n.weight === "bold" && n.color === fg)).toBe(true);
      expect(labels.some(n => n.text === "請核對封存來源" && n.size === "xs" && n.color === T.ink)).toBe(true);
      expect(contrast(bg, fg)).toBeGreaterThanOrEqual(4.5);
      expect(contrast(bg, T.ink)).toBeGreaterThanOrEqual(4.5);
    }
    expect(noticeText("交易資訊未核實", "資料可能延遲")).toBe("【注意】交易資訊未核實：資料可能延遲");
  });
});
describe("UI-R3 financial numbers and mobile navigation", () => {
  it("separates only large integer counts and never invents missing numbers", () => {
    expect(formatCount(9999)).toBe("9999");
    expect(formatCount(10000)).toBe("10,000");
    expect(formatCount(123456789)).toBe("123,456,789");
    expect(formatCount(Infinity)).toBe("未提供");
  });
  it("renders signed percentages with the specified precision and accurate ratio semantics", () => {
    expect(formatPercent(0.091, true)).toBe("+9.1%");
    expect(formatPercent(0.1, true)).toBe("+10%");
    expect(formatPercent(-0.099, true)).toBe("-9.9%");
    expect(formatPercent(22.3)).toBe("+22%");
    expect(formatPercent(-0)).toBe("+0.0%");
    expect(formatPercent(NaN)).toBe("未提供");
  });
  it("renders localized money with explicit currencies and ten-thousands/100M groups", () => {
    expect(formatCurrency(15.2, "USD")).toBe("US$15.20");
    expect(formatCurrency(15000, "TWD")).toBe("NT$1.5萬");
    expect(formatCurrency(230000000, "USD")).toBe("US$2.3億");
    expect(formatCurrency(500, "JPY")).toBe("¥500.00");
    expect(formatCurrency(500, "HKD")).toBe("HK$500.00");
    expect(formatCurrency(500, "KRW")).toBe("₩500.00");
    expect(formatCurrency(NaN)).toBe("未提供");
  });
  it("keeps dates as calendar dates and formats timestamps using Taipei locale", () => {
    expect(formatDate("2026-11-07T23:30:00Z")).toBe("2026-11-07");
    expect(formatDate("2026-02-30")).toBe("日期未揭露");
    expect(formatDate(new Date(NaN))).toBe("日期未揭露");
    expect(formatTaipeiTimestamp("2026-11-07T08:30:00Z")).toBe("11-07 16:30（台北）");
    expect(formatTaipeiTimestamp("invalid")).toBe("時間未知");
  });
  it("truncates visible button labels to six while preserving the full command", () => {
    for (const value of ["查看期權策略教學", "返回 TOP20 榜單", "完整產業分布文字", "查 NVDA 每月期權", "深度化分析（10維因果）"]) {
      const label = shortActionLabel(value);
      expect(Array.from(label).length).toBeLessThanOrEqual(6);
      const action: any = menuAction(value, `原始指令:${value}`);
      expect(action.action.label).toBe(label);
      expect(action.action.text).toBe(`原始指令:${value}`);
    }
  });
  it("includes surface and date in accessible alt text, capped at 60 characters", () => {
    const alt = altSummary({ topic: "瓶頸爆發榜單中文完整名稱".repeat(10), status: "完成", next: "滑動查看", date: "2026-11-07T06:00:00Z" });
    expect(Array.from(alt).length).toBeLessThanOrEqual(60);
    expect(alt).toContain("2026-11-07");
    expect(shortAltText("個股快查", "2026-11-07")).toBe("個股快查｜2026-11-07");
  });
});
