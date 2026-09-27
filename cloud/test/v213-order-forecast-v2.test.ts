// Version-2 order forecasts (Astra contract ORDERS-V2-01 and its revision-1 review): the Worker validates the sealed claim
// evidence, recomputes the selection at the exact sealed build instant and every figure from the sealed periodic input,
// order book and claims, and renders both horizons with their windows. The Python producer's output is
// tests/fixtures/v213-order-forecast-v2.json (tests/test_order_claims.py) and the real sealer's output
// tests/fixtures/v213-order-forecast-v2-sealed.json (tests/test_bottleneck_top20_v3.py).
import { describe, expect, it } from "vitest";
import { buildBottleneckDetail, buildBottleneckTop20Messages, outlookForecast, parseBottleneckV3 } from "../src/v213/bottleneck-v3";
import { parseOrderForecast, selectClaims } from "../src/v213/order-forecast";
import { doc, HOUR } from "./bottleneck-v3-fixture";
import v2 from "../../tests/fixtures/v213-order-forecast-v2.json";
import sealedCase from "../../tests/fixtures/v213-order-forecast-v2-sealed.json";

const REPORT = Date.UTC(2026, 8, 27, 1, 0, 0);
const GENERATED = "2026-09-27T01:00:00Z";
const cases = (v2 as any).cases as Record<string, { forecast: any }>;
const REFUSED = "1年內預計認列：資料未通過驗證";

function parsedWith(mutate: (forecasts: Record<string, any>) => void = () => {}, generated = REPORT) {
  const raw = doc(generated);
  const forecasts = Object.fromEntries(Object.entries(cases).map(([symbol, c]) => [symbol, structuredClone(c.forecast)]));
  mutate(forecasts);
  for (const [symbol, forecast] of Object.entries(forecasts)) {
    const entry = (raw.top as any[])[Number(symbol.slice(1))];
    entry.outlook = { ...(entry.outlook ?? { orders: null, consensus: null, scenarios: [], consensus_second: null }), order_forecast: forecast };
  }
  return parseBottleneckV3(raw, generated + HOUR)!;
}
const card = (parsed: ReturnType<typeof parsedWith>, symbol: string) =>
  outlookForecast(parsed, parsed.top.find(entry => entry.symbol === symbol)!).map(([text]) => text);
const direct = (forecast: any, symbol = "S1") => parseOrderForecast(forecast, "2026-09-27", symbol, GENERATED);

describe("version-2 order forecast", () => {
  it("renders every shared Python case through the real Top20 caller", () => {
    expect((doc(REPORT) as any).generated_at).toBe(GENERATED);
    const parsed = parsedWith();
    // S1: a later 8-K states a new RPO and its own schedule: it replaces the filing's; the mirrored release counts once;
    // the filing's quarter ends 62 days earlier, so no price; the new contract is a dated reference, never added.
    expect(card(parsed, "S1")).toEqual(["未來訂單預估", "半年內預計認列：US$15.4B（起算日 2026-08-31（非今日起），至 2027-02-28）",
      "1年內預計認列：US$27.8B（起算日 2026-08-31（非今日起），至 2027-08-31）", "訂單實現後股價情境", "若半年內實現訂單 → 無法估價（缺同期營收）",
      "若1年內實現訂單 → 無法估價（缺同期營收）", "RPO 為剩餘履約義務，非全部訂單；預計認列非保證",
      "訂單資料截至 2026-08-31｜來源公布 2026-09-10｜本次查核 2026-09-21", "期後訂單消息（不併入 RPO）：新簽5年供貨合約約 US$5.0B（2026-09-11）",
      "已由 2026-09-10 公司揭露更新；前值保留供查核"]);
    const detail = JSON.stringify(buildBottleneckDetail(parsed, "S1", "text"));
    expect(detail).toContain("前值：10-Q 2026-08-10（0000000000-26-000001）RPO US$40.0B（截至 2026-06-30）× 55% 於 2026-06-30–2027-06-30 認列");
    expect(detail).toContain("訂單來源：SEC 8-K 附件 2026-09-10（p.1）https://www.sec.gov/Archives/edgar/data/1/S1-8K.htm；原文：「RPO_STOCK statement S1-RPO」；本次查核 2026-09-21");
    expect(detail).toContain("參考（固定期間，非半年／1年）：24個月內認列 US$38.4B（RPO × 80%，2026-08-31–2028-08-31）。");
    expect(card(parsed, "S2").slice(1, 6)).toEqual(["半年內預計認列：公司揭露互相矛盾，暫不估算", "1年內預計認列：公司揭露互相矛盾，暫不估算",
      "訂單實現後股價情境", "若半年內實現訂單 → 公司揭露互相矛盾，暫不估算", "若1年內實現訂單 → 公司揭露互相矛盾，暫不估算"]);
    // S3: an issuer correction replaces the RPO (shown first, with why there is no figure); a cancellation with its reason.
    expect(card(parsed, "S3").slice(1, 8)).toEqual(["半年內預計認列：未揭露", "1年內預計認列：未揭露", "訂單實現後股價情境",
      "若半年內實現訂單 → 無法估價（缺認列時程）", "若1年內實現訂單 → 無法估價（缺認列時程）",
      "最新揭露 RPO：US$10.5B（截至 2026-08-31，公布 2026-09-08）；公司未揭露其認列時程", "另有 1 則期後訂單消息（詳見瓶頸詳情）"]);
    const s3 = JSON.stringify(buildBottleneckDetail(parsed, "S3", "text"));
    expect(s3).toContain("期後訂單更正（不併入 RPO）：合約取消（2026-09-08；customer terminated the agreement）");
    expect(s3).toContain("已更正：RPO US$10.0B（2026-09-01）→ 依 2026-09-08 揭露（issuer correction of the RPO）");
    expect(s3).toContain("已取消：已簽合約 US$2.0B（2026-09-02）→ 依 2026-09-08 揭露（customer terminated the agreement）");
    // S4: a release published on the cutoff day (date only) does not count yet; a filing carries no review time.
    expect(card(parsed, "S4").slice(-2)).toEqual(["訂單資料截至 2026-06-30｜來源公布 2026-08-10", "尚無已驗證的期後訂單補充"]);
    expect(card(parsed, "S5").at(-1)).toBe("期後訂單補充：無法讀取");
    // S6: the issuer restated the filing's RPO: the correction replaces it, the filing's schedule is history.
    expect(card(parsed, "S6").slice(-2)).toEqual(["最新揭露 RPO：US$40.4B（截至 2026-06-30，公布 2026-08-20）；公司未揭露其認列時程",
      "已由 2026-08-20 公司揭露更正；前值保留供查核"]);
    // S7: a disclosed zero RPO is current: no old schedule revives, nothing is priced.
    expect(card(parsed, "S7").slice(1, 6)).toEqual(["半年內預計認列：無可計算金額", "1年內預計認列：無可計算金額", "訂單實現後股價情境",
      "若半年內實現訂單 → 無法估價（最新揭露無可計算金額）", "若1年內實現訂單 → 無法估價（最新揭露無可計算金額）"]);
  });

  it("renders ranges with their unit and explains a current stock from its actual schedule state", () => {
    const parsed = parsedWith();
    expect(card(parsed, "S10").slice(1, 3)).toEqual(["半年內預計認列：無可計算金額", "1年內預計認列：無可計算金額"]);
    expect(card(parsed, "S10")).toContain("最新揭露 RPO：≥US$40.0B（區間）（截至 2026-08-31，公布 2026-09-05）；最新揭露無可計算的訂單金額");
    // A 6-month-only schedule that has ended, no filing: the rows say so; the stock line points to them.
    expect(card(parsed, "S11").slice(1, 3)).toEqual(["半年內預計認列：期間已結束", "1年內預計認列：未揭露"]);
    expect(card(parsed, "S11")).toContain("最新揭露 RPO：US$20.0B（截至 2026-03-15，公布 2026-03-20）；認列時程見上");
    expect(card(parsed, "S11").join("\n")).not.toContain("照常適用");
  });

  it("keeps equal stocks' schedules, and explains older or identical stocks truthfully (Astra review of revision 3)", () => {
    const parsed = parsedWith();
    expect(card(parsed, "S12").slice(1, 3)).toEqual(["半年內預計認列：公司揭露互相矛盾，暫不估算", "1年內預計認列：公司揭露互相矛盾，暫不估算"]);
    expect(card(parsed, "S13")).toContain("最新揭露 RPO：US$30.0B（截至 2026-05-31，公布 2026-09-12）；早於申報量測（2026-06-30），僅供參考");
    expect(card(parsed, "S13")[2]).toBe("1年內預計認列：US$22.0B（起算日 2026-06-30（非今日起），至 2027-06-30）");
    expect(card(parsed, "S14")).toContain("最新揭露 RPO：US$40.0B（截至 2026-06-30，公布 2026-08-12）；與申報同日同額，沿用申報之認列時程");
  });

  it("keeps a supplementary-plane issuer at the budget complete in every detail form, paginating instead of cutting", () => {
    const raw = doc(REPORT);
    for (const entry of raw.top as any[]) {
      entry.outlook = { ...(entry.outlook ?? { orders: null, consensus: null, scenarios: [], consensus_second: null }),
        order_forecast: JSON.parse(JSON.stringify(cases.S16!.forecast).replaceAll("S16", entry.symbol)) };
      entry.name = "名".repeat(160);
      entry.role = "r".repeat(200);
      entry.role_zh = "角".repeat(200);
    }
    const parsed = parseBottleneckV3(raw, REPORT + HOUR)!;
    expect(card(parsed, parsed.top[5]!.symbol)[2]).toBe("1年內預計認列：US$21.0B（起算日 2026-08-31（非今日起），至 2027-08-31）");
    for (const entry of [parsed.top[0]!, parsed.top[19]!]) {
      for (const style of ["text", "flex"] as const) {
        const detail = JSON.stringify(buildBottleneckDetail(parsed, entry.symbol, style));
        expect(detail.match(/本次查核 2026-09-21/g)?.length ?? 0, `${entry.symbol} ${style}`).toBeGreaterThanOrEqual(6);
        for (let i = 1; i <= 4; i += 1) expect(detail, `${entry.symbol} ${style}`).toContain(`期後訂單消息（不併入 RPO）：合約${i}`);
        expect(detail, style).not.toContain("…\"");  // nothing cut at a line boundary
      }
    }
  });

  it("compares numbers by value whatever their JSON spelling (Astra review of revision 4)", () => {
    const parsed = parsedWith();
    expect(card(parsed, "S17")[2]).toBe("1年內預計認列：US$22.0B（起算日 2026-06-30（非今日起），至 2027-06-30）");
    expect(card(parsed, "S18").slice(1, 3)).toEqual(["半年內預計認列：無可計算金額", "1年內預計認列：無可計算金額"]);
    // Signed zero is one value (Astra review of revision 5): equal ranges and zero stocks are not conflicts.
    for (const symbol of ["S19", "S15"]) expect(card(parsed, symbol).slice(1, 3), symbol).toEqual(["半年內預計認列：無可計算金額", "1年內預計認列：無可計算金額"]);
  });

  it("accepts the real sealer's fixed-cutoff output through parseBottleneckV3", () => {
    const raw = doc(Date.parse((sealedCase as any).generated_at));
    (raw.top as any[])[1].symbol = "SNDK";
    (raw.top as any[])[1].outlook = { orders: null, consensus: null, scenarios: [], consensus_second: null, order_forecast: (sealedCase as any).forecast };
    const parsed = parseBottleneckV3(raw, Date.parse((sealedCase as any).generated_at) + HOUR)!;
    expect(card(parsed, "SNDK").slice(1, 6)).toEqual(["半年內預計認列：US$15.4B（起算日 2026-07-31（非今日起），至 2027-01-31）",
      "1年內預計認列：US$26.4B（起算日 2026-07-31（非今日起），至 2027-07-31）", "訂單實現後股價情境",
      "若半年內實現訂單 → 無法估價（訂單僅覆蓋同期營收 96%）", "若1年內實現訂單 → 無法估價（訂單僅覆蓋同期營收 83%）"]);
  });

  it("recomputes the selection exactly as the Python producer did", () => {
    for (const [symbol, c] of Object.entries(cases)) {
      const ev = c.forecast.evidence;
      if (!ev.selection || ev.selection.status === "EVIDENCE_LIMIT") continue;
      const filing = ev.periodic?.status === "DISCLOSED" ? { accession: ev.periodic.accession, filed: ev.periodic.filed } : null;
      expect(selectClaims(ev.documents, ev.claims, Date.parse(ev.cutoff), filing), symbol).toEqual(ev.selection);
    }
  });

  it("refuses tampered, foreign or inconsistent records as a whole (Astra review probes included)", () => {
    const tamper: [string, (f: any) => void][] = [
      ["amount", f => { f.m12.amount *= 1.1; }],
      ["share", f => { f.m12.share_pct = 70; }],
      ["claim value", f => { f.evidence.claims.find((c: any) => c.id === "S1-RPO").amount = 50; }],
      ["schedule shares", f => { f.evidence.claims.find((c: any) => c.id === "S1-SCHED").shares.m12 = 60; }],
      ["selection says nothing excluded", f => { f.evidence.selection.excluded = []; }],
      ["selection picks the mirror", f => { f.evidence.selection.current_stock = "S1-RPO-MIRROR"; }],
      ["filing state", f => { f.evidence.selection.filing = "SUPERSEDED"; }],
      ["cutoff later the same day", f => { f.evidence.cutoff = "2026-09-27T23:00:00Z"; f.evidence.claims[0].checked_at = "2026-09-27T22:00:00Z"; }],
      ["rollover instant", f => { f.evidence.claims[0].checked_at = "2026-09-26T24:00:00Z"; }],
      ["malformed digest", f => { f.evidence.registry_sha256 = "abc"; }],
      ["prefix not reviewed", f => { f.evidence.url_prefixes = ["https://other.example/"]; }],
      ["empty passage", f => { f.evidence.claims[0].passage = ""; }],
      ["control character", f => { f.evidence.claims[0].passage = "a\u0001b"; }],
      ["short document hash", f => { f.evidence.documents[0].sha256 = "a".repeat(63); }],
      ["unknown claim field", f => { f.evidence.claims[0].verified = true; }],
      ["period on a stock", f => { Object.assign(f.evidence.claims[0], { period_start: "not-a-date" }); }],
      ["nonsense bounds", f => { f.evidence.claims[3].bounds = { lower: 3, upper: 2 }; }],
      ["exhibit object", f => { f.evidence.documents[0].sec.exhibit = { n: 1 }; }],
      ["8-K without exhibit", f => { delete f.evidence.documents[0].sec.exhibit; }],
      ["unknown top field", f => { f.note = "x"; }],
      ["schedule of another stock", f => { f.m12.stock_claim_id = "S1-RPO-MIRROR"; }],
      ["window from today", f => { f.m12.start = "2026-09-27"; }],
      ["price without the filing's quarter", f => { Object.assign(f.m12, { quarter_revenue: 1e9, quarter_start: "2026-06-01", quarter_end: "2026-08-31",
        quarter_basis: "FRAME", scenario: { status: "AVAILABLE", coverage: 6.96, change: 5.96 } }); }],
      ["failed filing with a quarter", f => { Object.assign(f.evidence.periodic, { status: "INVALID", quarter_revenue: 1e9, quarter_end: "2026-08-31" }); }],
      ["source omitted, old schedule shown", f => { f.m6 = structuredClone(cases.S4!.forecast.m6); f.m12 = structuredClone(cases.S4!.forecast.m12);
        delete f.m6.source; delete f.m12.source; }],
      ["mixed baselines", f => { f.m6.amount = 1; }],
      ["another issuer", f => { f.issuer = "S2"; }],
      ["unknown version", f => { f.version = 3; }],
      ["supplement dropped", f => { f.references = f.references.filter((r: any) => r.kind !== "CLAIM"); }],
      ["supplement not active", f => { f.references.push({ kind: "CLAIM", claim_id: "S1-RPO-MIRROR" }); }],
      ["superseded newer than the stock", f => { f.references.find((r: any) => r.kind === "SUPERSEDED_SCHEDULE").as_of = "2026-09-01"; }],
      ["24-month reference inflated", f => { f.references.find((r: any) => r.kind === "REGISTRY_RECOGNITION_24M").amount *= 2; }],
      ["caller-supplied failure label", f => { f.m6 = { status: "UNAVAILABLE", reason: "EXPIRED", scenario: { status: "NO_BASIS", reason: "NO_ORDER_BASIS" } }; }],
      ["registry evidence without a registry", f => { f.evidence.registry_status = "UNAVAILABLE"; f.evidence.registry_sha256 = null; }],
      // Astra review of revision 2
      ["dot segment escaping the prefix", f => { f.evidence.documents[2].url = "https://investors.synthetic.example/ir/../unreviewed/file.pdf"; }],
      ["encoded dot segment", f => { f.evidence.documents[2].url = "https://investors.synthetic.example/ir/%2e%2e/unreviewed/file.pdf"; }],
      ["null summary", f => { f.evidence.claims.find((c: any) => c.id === "S1-CONTRACT").summary = null; }],
      ["far-future publication", f => { f.evidence.documents[0].published_date = "9999-12-31"; }],
      ["schedule on another basis", f => { f.evidence.claims.find((c: any) => c.id === "S1-SCHED").basis = "another basis"; }],
      ["filing correction on another basis", f => { const c = f.evidence.claims.find((x: any) => x.id === "S1-RPO");
        c.basis = "NON_GAAP other cohort"; c.revision = { kind: "REPLACES", targets: ["FILING:0000000000-26-000001"], reason: "restated" }; }],
      ["schedule null_reason object", f => { f.evidence.claims.find((c: any) => c.id === "S1-SCHED").null_reason = { bad: 1 }; }],
      ["schedule null_reason byte-order mark", f => { f.evidence.claims.find((c: any) => c.id === "S1-SCHED").null_reason = "\ufeff"; }],
      ["unpaired surrogate", f => { f.evidence.claims[0].locator = "x\ud800"; }],
      ["zero-width character", f => { f.evidence.claims[0].passage = "a\u200bb"; }],
      ["evidence beyond the presentation budget", f => {  // about 2,900 code points against the shared budget of 2,400
        f.evidence.documents[0].url = `https://www.sec.gov/Archives/edgar/data/1/${"z".repeat(340)}.htm`;
        for (const d of f.evidence.documents.slice(1)) d.url = `https://investors.synthetic.example/ir/${d.id}${"z".repeat(340)}.pdf`;
        for (const c of f.evidence.claims) { c.locator = "頁".repeat(160); c.passage = "證".repeat(1000); } }],
    ];
    for (const [label, mutate] of tamper) {
      const parsed = parsedWith(forecasts => mutate(forecasts.S1));
      expect(card(parsed, "S1")[2], label).toBe(REFUSED);
      expect(card(parsed, "S1").some(line => line.startsWith("期後訂單") || line.startsWith("已由")), label).toBe(false);
    }
    // A mixed-baseline price on the filing's own horizons, and a conflict claimed without evidence for it.
    expect(card(parsedWith(f => { f.S4.m6.quarter_revenue = 1e9; f.S4.m6.scenario = { status: "AVAILABLE", coverage: 6, change: 5 }; }), "S4")[2]).toBe(REFUSED);
    expect(card(parsedWith(f => { for (const k of ["m6", "m12"]) f.S4[k] = { status: "UNAVAILABLE", reason: "CONFLICTING_DISCLOSURES",
      scenario: { status: "NO_BASIS", reason: "NO_ORDER_BASIS" } }; f.S4.status = "UNAVAILABLE"; f.S4.reason = "CONFLICTING_DISCLOSURES"; }), "S4")[2]).toBe(REFUSED);
    // A document published after the build instant (sub-day), even with its selection recomputed to include it.
    const late = structuredClone(cases.S1!.forecast);
    late.evidence.documents[2].published_at = "2026-09-27T01:00:01Z";
    late.evidence.documents[2].published_date = "2026-09-27";
    expect(direct(late).m12.reason).toBe("INVALID");
  });

  it("keeps twenty cards and both detail forms with the most evidence an issuer may seal within the LINE limits", () => {
    const raw = doc(REPORT);
    for (const entry of raw.top as any[]) {
      entry.outlook = { ...(entry.outlook ?? { orders: null, consensus: null, scenarios: [], consensus_second: null }),
        order_forecast: JSON.parse(JSON.stringify(cases.S8!.forecast).replaceAll("S8", entry.symbol)) };
      entry.name = "N".repeat(160);
      entry.role = "r".repeat(200);
    }
    const parsed = parseBottleneckV3(raw, REPORT + HOUR)!;
    const flex = buildBottleneckTop20Messages(parsed, "flex") as unknown[];
    expect(flex.length).toBeLessThanOrEqual(5);
    const cards = JSON.stringify(flex);
    expect(cards.match(/半年內預計認列：US\$12\.0B/g)?.length ?? 0).toBe(20);
    expect(cards.match(/另有 5 則期後訂單消息/g)?.length ?? 0).toBe(20);
    const text = buildBottleneckTop20Messages(parsed, "text") as { text: string }[];
    expect(text.length).toBeLessThanOrEqual(5);
    for (const message of text) expect(message.text.length).toBeLessThanOrEqual(4900);
    const all = text.map(message => message.text).join("\n");
    expect(all.match(/1年內預計認列：US\$21\.0B（起算日 2026-08-31（非今日起），至 2027-08-31）/g)?.length ?? 0).toBe(20);
    expect(all.match(/若1年內實現訂單 → /g)?.length ?? 0).toBe(20);
    for (const style of ["text", "flex"] as const) {
      const detail = JSON.stringify(buildBottleneckDetail(parsed, parsed.top[3]!.symbol, style));
      expect(detail.match(/期後訂單消息（不併入 RPO）/g)?.length ?? 0, style).toBe(6);  // every disclosure in the detail
      expect(detail, style).toContain("若1年內實現訂單 → ");
    }
  });

  it("keeps the largest presentation within the budget complete in every form (Astra review of revision 2, fix 7)", () => {
    const raw = doc(REPORT);
    for (const entry of raw.top as any[]) {
      entry.outlook = { ...(entry.outlook ?? { orders: null, consensus: null, scenarios: [], consensus_second: null }),
        order_forecast: JSON.parse(JSON.stringify(cases.S9!.forecast).replaceAll("S9", entry.symbol)) };
      entry.name = "N".repeat(160);
      entry.role = "r".repeat(200);
      entry.role_zh = "角".repeat(200);
    }
    const parsed = parseBottleneckV3(raw, REPORT + HOUR)!;
    for (const entry of parsed.top) expect(card(parsed, entry.symbol)[2], entry.symbol).toBe("1年內預計認列：US$21.0B（起算日 2026-08-31（非今日起），至 2027-08-31）");
    expect((buildBottleneckTop20Messages(parsed, "flex") as unknown[]).length).toBeLessThanOrEqual(5);
    const text = buildBottleneckTop20Messages(parsed, "text") as { text: string }[];
    expect(text.map(m => m.text).join("\n").match(/若1年內實現訂單 → /g)?.length ?? 0).toBe(20);
    for (const entry of parsed.top) {
      for (const style of ["text", "flex"] as const) {
        const detail = JSON.stringify(buildBottleneckDetail(parsed, entry.symbol, style));
        // Every disclosure with its source line, both horizons and the price rows, never cut.
        for (let i = 1; i <= 4; i += 1) expect(detail, `${entry.symbol} ${style} 合${i}`).toContain(`期後訂單消息（不併入 RPO）：合${i}`);
        expect(detail.match(/本次查核 2026-09-21/g)?.length ?? 0, `${entry.symbol} ${style}`).toBeGreaterThanOrEqual(6);
        expect(detail, style).toContain("若1年內實現訂單 → ");
      }
    }
  });

  it("binds a version-2 record to its own build instant and never reads it as version 1", () => {
    const forecast = structuredClone(cases.S1!.forecast);
    expect(direct(forecast).m12.status).toBe("AVAILABLE");
    expect(parseOrderForecast(forecast, "2026-09-27", "S1", "2026-09-27T02:00:00Z").m12.reason).toBe("INVALID");
    expect(parseOrderForecast(forecast, "2026-09-27", "S1").m12.reason).toBe("INVALID");  // no build instant supplied
    expect(direct({ ...forecast, version: 1 }).m12.reason).toBe("INVALID");
    expect(parseOrderForecast(undefined, "2026-09-27", "S1", GENERATED).m12.reason).toBe("LEGACY");
  });
});
