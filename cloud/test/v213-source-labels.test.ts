// Display labels for recorded English source names (operator 2026-09-26: project information in Chinese).
import { describe, expect, it } from "vitest";
import { quoteBasisZh, rightsZh, sourceZh } from "../src/v213/source-labels";

describe("source labels", () => {
  it("translates known sources and patterns and keeps anything else as recorded", () => {
    expect(sourceZh("Yahoo Finance option chain (unofficial, delayed)")).toBe("Yahoo Finance 期權鏈（非官方，延遲）");
    expect(sourceZh("Nasdaq Nordic option chain (exchange public web API, delayed)")).toContain("Nasdaq Nordic 期權鏈");
    expect(sourceZh("SEC 10-Q RPO recognition timing")).toBe("SEC 10-Q 剩餘履約義務認列時程");
    expect(sourceZh("SEC 10-K business section")).toBe("SEC 10-K 業務章節");
    expect(sourceZh("BLS PPI WPU117")).toBe("美國勞工統計局生產者物價指數 WPU117");
    expect(sourceZh("臺灣證交所每日收盤")).toBe("臺灣證交所每日收盤");
    expect(sourceZh("Some New Feed")).toBe("Some New Feed");  // never guessed
    expect(sourceZh(null)).toBe("未載明");
    expect(sourceZh("constructor")).toBe("constructor");  // no prototype lookups
    expect(quoteBasisZh("delayed")).toBe("延遲");
    expect(rightsZh("candidate_local_review")).toBe("候選來源（本機審查）");
    expect(rightsZh("other")).toBe("other");
  });
});
