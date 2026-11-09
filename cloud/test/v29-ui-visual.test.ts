import { describe, expect, it, vi } from "vitest";
import { bubblesOf, REPORT, v20Surfaces, v3D1Surfaces, type Node } from "./flex-density-fixtures";
import type * as Admission from "../src/v213/public-options-admission";
import { doc } from "./bottleneck-v3-fixture";
import { buildBottleneckDetail, buildBottleneckTop20Messages, parseBottleneckV3 } from "../src/v213/bottleneck-v3";
import { optionsUnavailableReport } from "../src/v213/options-product";
import consensusFixture from "../../tests/fixtures/v11-consensus-sealed.json";

vi.mock("../src/v213/public-options-admission", async importOriginal => {
  const real = await importOriginal<typeof Admission>();
  return { ...real, admitPublicOption: vi.fn(real.admitPublicOption) };
});

function all(value: unknown): Node[] {
  if (!value || typeof value !== "object") return [];
  if (Array.isArray(value)) return value.flatMap(all);
  return [value as Node, ...Object.values(value).flatMap(all)];
}
const bytes = (value: unknown) => new TextEncoder().encode(JSON.stringify(value)).length;
function explicitRows(node: Node): number {
  if (node.type === "text") return (node.text ?? (node.contents ?? []).map(span => span.text ?? "").join("")).split("\n").length;
  const rows = (node.contents ?? []).map(explicitRows);
  return node.layout === "horizontal" ? Math.max(0, ...rows) : rows.reduce((a, b) => a + b, 0);
}

describe("V29 card visual hierarchy", () => {
  for (const name of ["bottleneck Top20 card", "bottleneck detail page 1", "options-product contract"]) {
    it(`${name} has a hero, KPI grid, bounded disclosures and size`, async () => {
      const bubbles = await v20Surfaces[name]!();
      expect(bubbles.length).toBeGreaterThan(0);
      for (const bubble of bubbles) {
        const body = all(bubble.body);
        expect(body.some(n => n.type === "text" && n.size === "3xl" && n.weight === "bold")).toBe(true);
        expect(body.some(n => n.type === "box" && n.layout === "horizontal" && (n.contents ?? []).filter(c => c.type === "box" && c.backgroundColor).length >= 2)).toBe(true);
        expect(bytes(bubble)).toBeLessThanOrEqual(28000);
        const footer = bubble.footer as Node;
        const contents = footer.contents ?? [];
        const firstButton = contents.findIndex(n => n.type === "button");
        expect(firstButton).toBeGreaterThan(0);
        expect(contents.slice(firstButton).every(n => n.type === "button")).toBe(true);
        expect(contents.slice(0, firstButton).length).toBeLessThanOrEqual(3);
      }
    });
  }
  it("stacks KPI labels, keeps missing values unbroken, and shows the accent meter", async () => {
    const parsed = parseBottleneckV3(doc(REPORT - 3600_000), REPORT)!;
    const detail = buildBottleneckDetail(parsed, "S1", "flex");
    expect(Array.isArray(detail)).toBe(true);
    if (!Array.isArray(detail)) return;
    const [finance, orders] = bubblesOf(detail);
    const tiles = all(finance!.body).filter(n => n.backgroundColor === "#EEF3F8" && n.type === "box");
    const stacked = tiles.flatMap(all).filter(n => n.type === "text" && (n.contents?.[0]?.text ?? "").endsWith("\n"));
    expect(stacked.length).toBeGreaterThanOrEqual(3);
    for (const text of stacked) {
      expect(text.contents?.[0]?.size).toBe("xs");
      expect(text.contents?.[1]?.weight).toBe("bold");
    }
    expect(all(orders!.body).some(n => n.text === "需新訂單" && n.wrap === false)).toBe(true);
    expect(all(finance!.header).some(n => n.backgroundColor === "#344F70")).toBe(true);
    const top = (await v20Surfaces["bottleneck Top20 card"]!())[1]!;
    const forecasts = all(top.body).filter(n => n.type === "text" && /未來訂單｜|股價情境｜/.test(n.text ?? ""));
    expect(forecasts).toHaveLength(2);
    expect(forecasts.every(n => !(n.text ?? "").includes("\n"))).toBe(true);
  });
  it("keeps unavailable option reasons usable even when long", () => {
    const bubble = v20Surfaces["options-product unavailable"]!() as Node[];
    expect(all(bubble[0]!.body).some(n => n.type === "box" && n.width === "4px")).toBe(true);
    expect(all(bubble[0]!.body).some(n => n.text?.startsWith("暫無"))).toBe(true);
  });
  it("shows the order-page hero, KPI grid, and honest missing values", () => {
    const parsed = parseBottleneckV3(doc(REPORT - 3600_000), REPORT)!;
    const result = buildBottleneckDetail(parsed, "S1", "flex");
    expect(Array.isArray(result)).toBe(true);
    if (!Array.isArray(result)) return;
    const body = all(bubblesOf(result)[1]!.body);
    expect(body.some(n => n.type === "text" && n.size === "3xl" && n.weight === "bold")).toBe(true);
    expect(body.some(n => n.type === "box" && n.layout === "horizontal" && (n.contents ?? []).filter(c => c.type === "box" && c.backgroundColor).length >= 2)).toBe(true);
    expect(body.some(n => n.text === "需新訂單")).toBe(true);
    const rendered = JSON.stringify(bubblesOf(result)[1]);
    for (const value of ["RPO 年增", "+68%", "1年內認列", "US$1.2B", "認列進度", "39%", "缺認列時程", "覆蓋不足"])
      expect(rendered).toContain(value);
  });
  it("keeps every baseline financial field and source on the complete-data route", () => {
    const parsed = parseBottleneckV3(doc(REPORT - 3600_000), REPORT)!;
    const result = buildBottleneckDetail(parsed, "S1", "text");
    expect(Array.isArray(result)).toBe(true);
    if (!Array.isArray(result)) return;
    const text = result.map(message => message.type === "text" ? message.text : "").join("\n");
    for (const field of ["市值 US$2.1B", "SEC EDGAR XBRL 財報資料", "季末 2026-06-30",
      "營收年增 +109.0%", "前一季年增 +90.0%", "加速度 +19.0個百分點",
      "毛利率 42.0%", "年變化 +14.0個百分點", "剩餘履約義務年增 未揭露", "股數年增 +2.0%",
      "https://data.sec.gov/api/xbrl/companyfacts/CIK0000000001.json",
      "Yahoo Finance 還原收盤價（非官方）", "2026-09-25", "6個月 +80.0%", "2年年化 +110%",
      "https://finance.yahoo.com/quote/X", "官方營收未交叉比對", "交易所收盤未交叉比對"]) {
      expect(text, field).toContain(field);
    }
  });
  it("renders long source prose and unavailable diagnostics without throwing", () => {
    const parsed = parseBottleneckV3(doc(REPORT - 3600_000), REPORT)!;
    parsed.top[0]!.role = parsed.top[0]!.role.repeat(5);
    const cards = buildBottleneckTop20Messages(parsed, "flex");
    const reason = "暫無可驗證期權資料；😀".repeat(500);
    const unavailable = optionsUnavailableReport("NVDA", "weekly", reason, false);
    const text = optionsUnavailableReport("NVDA", "weekly", reason, true);
    expect(text.map(message => message.type === "text" ? message.text : "").join("")).toContain(reason);
    expect(all(bubblesOf(cards)[0]!.body).some(n => n.type === "text" && n.size === "3xl")).toBe(true);
    expect(all(bubblesOf(unavailable)[0]!.body).some(n => n.type === "box" && n.width === "4px")).toBe(true);
  });
  it("renders listed expiry pairs without inventing a quote", () => {
    const result = optionsUnavailableReport("NVDA", "monthly", "本次回應有上市買權；所列到期不在策略範圍（最近到期 2026-12-18（46天））", false);
    const text = JSON.stringify(result);
    expect(text).toContain("2026-12-18 · DTE 46");
    expect(text).toContain("期權報價不可用");
    const ageOnly = JSON.stringify(optionsUnavailableReport("NVDA", "monthly", "資料產生於 2026-12-18（46天）前，已逾時", false));
    expect(ageOnly).not.toContain("DTE 46");
  });
  it("keeps the explicit body-row budget within ten", async () => {
    for (const name of ["bottleneck Top20 card", "bottleneck detail page 1", "options-product contract", "options-product unavailable"]) {
      for (const bubble of await v20Surfaces[name]!()) expect(explicitRows(bubble.body as Node), name).toBeLessThanOrEqual(10);
    }
    const variants = v3D1Surfaces();
    for (const name of ["bottleneck consensus V3", "bottleneck company-guidance V3"]) {
      for (const bubble of variants[name]!) expect(explicitRows(bubble.body as Node), name).toBeLessThanOrEqual(10);
    }
    for (const [caseName, sample] of Object.entries(consensusFixture.cases)) {
      const candidate = sample as { cutoff: string; outlooks: Record<string, unknown> };
      const generated = Date.parse(candidate.cutoff);
      for (const [symbol, outlook] of Object.entries(candidate.outlooks)) {
        const raw = doc(generated);
        raw.top[1]!.symbol = symbol;
        raw.top[1]!.outlook = structuredClone(outlook) as never;
        const variant = parseBottleneckV3(raw, generated + 3600_000)!;
        const reply = bubblesOf(buildBottleneckTop20Messages(variant, "flex"));
        const card = reply[1]!;
        expect(explicitRows(card.body as Node), `${caseName} ${symbol}`).toBeLessThanOrEqual(10);
        const rendered = JSON.stringify(card);
        const shared = JSON.stringify(reply.at(-1));
        expect(shared).toContain("資料來源與說明");
        expect(shared).toContain(symbol);
        if (caseName === "stale_age") {
          expect(rendered).toContain("營收推估暫不可用");
          expect(shared).toContain("分析師共識資料已逾24小時");
        }
        if (caseName === "recognition_stale") {
          expect(rendered).toContain("約1年訂單認列");
          expect(rendered).toContain("US$125M");
          expect(shared).toContain("分析師共識所估財季已結束");
        }
      }
    }
    const parsed = parseBottleneckV3(doc(REPORT - 3600_000), REPORT)!;
    for (const entry of parsed.top) {
      const detail = buildBottleneckDetail(parsed, entry.symbol, "flex");
      if (Array.isArray(detail)) expect(explicitRows(bubblesOf(detail)[1]!.body as Node), `orders ${entry.symbol}`).toBeLessThanOrEqual(10);
    }
  });
  it("uses no more than two KPI tiles per row", async () => {
    for (const name of ["bottleneck Top20 card", "bottleneck detail page 1", "options-product contract"]) {
      for (const bubble of await v20Surfaces[name]!()) {
        for (const node of all(bubble.body)) {
          if (node.type === "box" && node.layout === "horizontal") {
            const tiles = (node.contents ?? []).filter(child => child.type === "box" && child.backgroundColor === "#EEF3F8");
            expect(tiles.length, name).toBeLessThanOrEqual(3);
          }
        }
      }
    }
  });
  it("reports largest real fixture bubble", async () => {
    const groups = await Promise.all(["bottleneck Top20 card", "bottleneck detail page 1", "options-product contract", "options-product unavailable"].map(name => v20Surfaces[name]!()));
    const large = [...groups.flat(), ...Object.values(v3D1Surfaces()).flat()].map(bytes);
    console.log(`V29_MAX_FIXTURE_BUBBLE_BYTES=${Math.max(...large)}`);
    expect(Math.max(...large)).toBeLessThan(46000);
    expect(groups[0]!.every(b => all(b.body).some(n => n.type === "text" && n.size === "3xl"))).toBe(true);
  });
});
