import { describe, expect, it } from "vitest";
import { buildBottleneckDetail, buildBottleneckTop20Messages, parseBottleneckV3 } from "../src/v213/bottleneck-v3";
import { doc, HOUR } from "./bottleneck-v3-fixture";

const DAY = "2026-11-02";
const SEC = "https://www.sec.gov/Archives/edgar/data/1/000000000000000001/synthetic8k.htm";
const rulePairs = [
  ["R01_REV_GROWTH_20", "營收年增至少20%"],
  ["R02_REV_ACCEL_10PP", "營收年增加速至少10個百分點"],
  ["R03_GM_EXPAND_2PP", "毛利率年增至少2個百分點"],
  ["R04_RPO_GROWTH_20", "剩餘履約義務年增至少20%"],
  ["R05_DILUTION_BELOW_5", "同季可比股數年增不超過5%"],
  ["R06_REL_MOMENTUM_6M", "近6個月報酬高於QQQ"],
  ["R07_PRICE_2Y_POSITIVE", "近2年調整後價格報酬為正"],
  ["R08_REL_MOMENTUM_SOXX_6M", "近6個月報酬高於SOXX"],
  ["R09_MAX_DRAWDOWN_12M", "近1年最大回撤不超過35%"],
  ["R10_ATM_MATERIAL_DILUTION", "已查證有效ATM及重大稀釋條款"],
  ["R13_INDEPENDENT_13F_POSITION_CHANGE", "已查證獨立機構13F持股變化"],
] as const;

function fixture() {
  const value = doc(Date.now() - HOUR);
  const first = { ...value.top[0]!,
    screen_conditions: {
      state: "UNVERIFIED",
      rules: rulePairs.map<{ rule_id: string; label_zh: string; status: string }>(([rule_id, label_zh], index) =>
        ({ rule_id, label_zh, status: index >= 9 ? "UNKNOWN" : index % 3 === 0 ? "PASS" : index % 3 === 1 ? "FAIL" : "UNKNOWN" })),
    },
    latest_event: { status: "PRIMARY_REVIEWED", source_url: SEC,
      published_on: DAY, headline_zh: "公開公司公告待驗證後續里程碑" },
  };
  const top: [typeof first, ...typeof value.top] = [first, ...value.top.slice(1)];
  return { ...value, top, excluded_actions: [{
    symbol: "LITE", reason_zh: "併購待完成，暫不納入排行",
    corporate_action: { target_symbol: "LITE", acquirer_symbol: "MRVL", kind: "ALL_STOCK", status: "PENDING",
      exchange_ratio: 4.5, cash_per_share: null, currency: null,
      expected_close: "first half of calendar year 2028", source_url: SEC },
  }, {
    symbol: "MOD", reason_zh: "尚缺可核對的一手歷史收盤價、完整配息與拆股紀錄及衍生報酬公開使用權；零股另須實際淨現金證明，跨配發權益日報酬暫不顯示。",
    corporate_action: { target_market: "US", target_symbol: "MOD", kind: "DISTRIBUTION", status: "CLOSED",
      distribution_date: "2026-10-01", related_market: "US", related_symbol: "THRM", shares_per_share: 0.44619,
      source_url: SEC, source_date: "2026-10-01", review_by: null },
  }] };
}

describe("R2B score-neutral research overlays and pending-deal disclosures", () => {
  it("renders unvalidated conditions and latest reviewed event without assigning scores or admitting a merger target", () => {
    const parsed = parseBottleneckV3(fixture());
    expect(parsed).not.toBeNull();
    expect(parsed!.top[0]!.score).toBe(80);
    const flex = buildBottleneckTop20Messages(parsed!, "flex");
    expect(flex.length).toBeLessThanOrEqual(5);
    const raw = JSON.stringify(flex);
    expect(raw).toContain("符合的篩選條件（未驗證）");
    expect(raw).toContain("最新事件（官方公告）");
    expect(raw).toContain("營收年增至少20%");
    const text = buildBottleneckTop20Messages(parsed!, "text");
    expect(JSON.stringify(text)).toContain("LITE：併購待完成，暫不納入排行");
    const excluded = buildBottleneckDetail(parsed!, "LITE");
    expect(typeof excluded).toBe("string");
    expect(excluded).toContain("4.500 股 MRVL");
    expect(excluded).toContain("2028 年上半年");
    for (const payload of [raw, JSON.stringify(text)]) {
      expect(payload).toContain("LITE");
      expect(payload).toContain("4.500 股 MRVL");
      expect(payload).toContain("2028 年上半年");
      expect(payload).toContain("MOD");
      expect(payload).toContain("零股另須實際淨現金證明");
      expect(payload).not.toMatch(/\b(?:PENDING|CLOSED)\b/);
    }
    expect(buildBottleneckDetail(parsed!, "MOD")).toContain("0.44619 股 THRM");
    expect(buildBottleneckDetail(parsed!, "MOD")).toContain("跨配發權益日報酬暫不顯示");
    expect(parsed!.top.some(row => row.symbol === "LITE" || row.symbol === "MOD")).toBe(false);
    expect(JSON.stringify(text)).not.toContain("未驗證條件已確認");
  });

  it("keeps a complete report when the first 13F period has no comparison quarter", () => {
    const value = fixture();
    value.top[0].leopold = { long_weight: 0.2, status: "UNKNOWN_PRIOR" };
    const parsed = parseBottleneckV3(value);
    expect(parsed?.top.map(row => row.symbol)).toEqual(value.top.map(row => row.symbol));
    expect(parsed?.top[0]?.leopold?.status).toBe("UNKNOWN_PRIOR");
    expect(parsed?.top[0]?.score).toBe(value.top[0].score);
  });

  it("rejects forged validation, unknown or duplicate rule, future event and fabricated exclusion", () => {
    const a = fixture();
    a.top[0].screen_conditions.state = "VERIFIED";
    expect(parseBottleneckV3(a)).toBeNull();
    const b = fixture();
    b.top[0].screen_conditions.rules[0]!.rule_id = "INVEST_NOW";
    expect(parseBottleneckV3(b)).toBeNull();
    const c = fixture();
    c.top[0].screen_conditions.rules[1]!.rule_id = c.top[0].screen_conditions.rules[0]!.rule_id;
    expect(parseBottleneckV3(c)).toBeNull();
    const d = fixture();
    d.top[0].latest_event.published_on = "2099-11-02";
    expect(parseBottleneckV3(d)).toBeNull();
    const e = fixture();
    e.excluded_actions[0]!.symbol = e.top[0].symbol;
    expect(parseBottleneckV3(e)).toBeNull();
  });

  it("rejects missing, conflicting and forged excluded-action disclosures", () => {
    const missing = fixture();
    Object.assign(missing.excluded_actions[0]!, { corporate_action: undefined });
    expect(parseBottleneckV3(missing)).toBeNull();
    const duplicate = fixture();
    duplicate.excluded_actions.push(structuredClone(duplicate.excluded_actions[0]!));
    expect(parseBottleneckV3(duplicate)).toBeNull();
    const reason = fixture();
    reason.excluded_actions[1]!.reason_zh = "已完成核准，可顯示零報酬";
    expect(parseBottleneckV3(reason)).toBeNull();
    const wrongParty = fixture();
    wrongParty.excluded_actions[1]!.symbol = "THRM";
    expect(parseBottleneckV3(wrongParty)).toBeNull();
  });

  it("keeps official TW/KR notices metadata-only and rejects forged claim text or source authority", () => {
    for (const source_url of [
      "https://openapi.twse.com.tw/v1/opendata/t187ap04_L",
      "https://dart.fss.or.kr/api/link.jsp?rcpNo=20261102000001",
    ]) {
      const value = fixture();
      value.top[0].latest_event = { status: "PRIMARY_METADATA_ONLY", source_url,
        published_on: DAY, headline_zh: "交易所公告（內容待查）" };
      const parsed = parseBottleneckV3(value);
      expect(parsed).not.toBeNull();
      expect(JSON.stringify(buildBottleneckDetail(parsed!, parsed!.top[0]!.symbol))).toContain("內容待查");
      value.top[0].latest_event.headline_zh = "已簽新訂單";
      expect(parseBottleneckV3(value)).toBeNull();
      value.top[0].latest_event = { status: "PRIMARY_REVIEWED", source_url: "https://unrelated.invalid/notice",
        published_on: DAY, headline_zh: "聲稱的官方公告" };
      expect(parseBottleneckV3(value)).toBeNull();
    }
    const forged = fixture();
    forged.top[0].screen_conditions.rules[9]!.status = "PASS";
    expect(parseBottleneckV3(forged)).toBeNull();
  });
});


describe("R2B distribution entitlement admission", () => {
  it("accepts a sealed, reviewed primary-return proof without trusting unadjusted Yahoo return", () => {
    const base = doc(Date.now() - HOUR);
    const sec = "https://www.sec.gov/Archives/edgar/data/67347/000110465926112870/tm2626618d1_8k.htm";
    const row = { ...base.top[0]!, symbol: "MOD",
      market: { ...base.top[0]!.market, asof: "2026-11-06", ret_6m: 0.03, ret_1y: 0.08, cagr_2y: 0.11,
        distribution_adjustment: {
          status: "REVIEWED_PRIMARY_INPUTS", source_url: sec,
          distribution_date: "2026-10-01", related_symbol: "THRM", shares_per_share: 0.44619,
          evidence_sha256: "a".repeat(64), method: "SHAREHOLDER_ENTITLEMENT_TOTAL_RETURN",
          values: { ret_6m: 0.03, ret_1y: 0.08, cagr_2y: 0.11 },
        } },
      corporate_action: {
        target_market: "US", target_symbol: "MOD", kind: "DISTRIBUTION", status: "CLOSED",
        distribution_date: "2026-10-01", related_market: "US", related_symbol: "THRM",
        shares_per_share: 0.44619, source_url: sec, source_date: "2026-10-01", review_by: null,
      },
    };
    const value = { ...base, top: [row, ...base.top.slice(1)] };
    const parsed = parseBottleneckV3(value);
    expect(parsed).not.toBeNull();
    expect(JSON.stringify(buildBottleneckTop20Messages(parsed!, "text"))).toContain("跨事件報酬依已覆核一手權益資料計算");
    const forged = structuredClone(row);
    forged.market.ret_6m = 0.99;
    expect(parseBottleneckV3({ ...value, top: [forged, ...base.top.slice(1)] })).toBeNull();
    const mismatched = structuredClone(row);
    mismatched.market.distribution_adjustment.evidence_sha256 = "invalid";
    expect(parseBottleneckV3({ ...value, top: [mismatched, ...base.top.slice(1)] })).toBeNull();
  });

  it("uses the Oct2 ex-spin boundary, not the Oct1 distribution day", () => {
    const now = Date.parse("2026-10-02T12:00:00Z");
    const base = doc(now - HOUR);
    const returns: { ret_6m: number | null; ret_1y: number | null; cagr_2y: number | null;
      return_reasons?: Record<string, string> } = { ret_6m: 0.8, ret_1y: 2.1, cagr_2y: 1.1 };
    const row = { ...base.top[0]!, symbol: "MOD", market: { ...base.top[0]!.market, ...returns, asof: "2026-10-01" },
      corporate_action: {
        target_market: "US", target_symbol: "MOD", kind: "DISTRIBUTION", status: "CLOSED",
        distribution_date: "2026-10-01", related_market: "US", related_symbol: "THRM",
        shares_per_share: 0.44619,
        source_url: "https://www.sec.gov/Archives/edgar/data/67347/000110465926112870/tm2626618d1_8k.htm",
        source_date: "2026-10-01", review_by: null,
      } };
    const value = { ...base, top: [row, ...base.top.slice(1)] };
    expect(parseBottleneckV3(value, now)).not.toBeNull();
    row.market.asof = "2026-10-02";
    expect(parseBottleneckV3(value, now)).toBeNull();
    row.market.ret_6m = row.market.ret_1y = row.market.cagr_2y = null;
    row.market.return_reasons = { ret_6m: "DISTRIBUTION_IN_WINDOW", ret_1y: "DISTRIBUTION_IN_WINDOW",
      cagr_2y: "DISTRIBUTION_IN_WINDOW" };
    expect(parseBottleneckV3(value, now)).not.toBeNull();
  });
});
