import { describe, expect, it } from "vitest";
import {
  formatManualOptionQuote,
  manualOptionQuoteAnswer,
  parseManualOptionInput,
  type ManualOptionInput,
} from "../src/manual-options";

const callInput: ManualOptionInput = {
  ticker: "ALPHA",
  optionType: "call",
  spot: 100,
  strike: 110,
  bid: 2.5,
  ask: 2.8,
  dte: 7,
  currency: "USD",
};

describe("ephemeral user-supplied option calculator", () => {
  it("does not intercept an ordinary public option query", () => {
    expect(manualOptionQuoteAnswer("ALPHA 每週期權 BID ASK")).toBeNull();
  });

  it("returns closed usage help without a provider request", () => {
    const answer = manualOptionQuoteAnswer("期權試算說明");
    expect(answer).toContain("ticker=ALPHA");
    expect(answer).toContain("不會查詢券商、持倉或帳戶");
  });

  it("parses an exact call input and labels every value user-supplied", () => {
    const answer = manualOptionQuoteAnswer(
      "期權試算 ticker=ALPHA type=call spot=100 strike=110 bid=2.50 ask=2.80 dte=7 currency=USD",
    );
    expect(answer).toContain("USER_SUPPLIED_NOT_VERIFIED");
    expect(answer).toContain("ALPHA");
    expect(answer).toContain("CALL");
    expect(answer).toContain("Mid USD 2.65");
    expect(answer).toContain("每週觀察區間");
    expect(answer).toContain("有效出售價觀察");
    expect(answer).toContain("沒有抓取或驗證行情");
    expect(answer).toContain("不是推薦");
  });

  it("supports traditional-Chinese aliases for a put calculation", () => {
    const answer = manualOptionQuoteAnswer(
      "期權試算 代號=BETA 類型=賣權 現價=100 履約價=90 買價=1.00 賣價=1.20 天數=30 幣別=USD",
    );
    expect(answer).toContain("BETA");
    expect(answer).toContain("PUT");
    expect(answer).toContain("每月觀察區間");
    expect(answer).toContain("損益平衡觀察");
    expect(answer).toContain("標準一口現金履約額 USD 9000.00");
  });

  it("rejects personal holdings and account fields", () => {
    for (const text of [
      "期權試算 ticker=ALPHA type=call spot=100 strike=110 bid=2 ask=3 dte=7 shares=100",
      "期權試算 ticker=ALPHA type=call spot=100 strike=110 bid=2 ask=3 dte=7 account=TEST",
      "期權試算 我持有 ALPHA ticker=ALPHA type=call spot=100 strike=110 bid=2 ask=3 dte=7",
    ]) {
      expect(manualOptionQuoteAnswer(text)).toContain("不接受");
    }
  });

  it("fails closed on unknown duplicate or missing fields", () => {
    expect(
      manualOptionQuoteAnswer(
        "期權試算 ticker=ALPHA type=call spot=100 strike=110 bid=2 ask=3 dte=7 delta=0.2",
      ),
    ).toContain("未知欄位");
    expect(
      manualOptionQuoteAnswer(
        "期權試算 ticker=ALPHA ticker=BETA type=call spot=100 strike=110 bid=2 ask=3 dte=7",
      ),
    ).toContain("重複");
    expect(
      manualOptionQuoteAnswer(
        "期權試算 ticker=ALPHA type=call spot=100 strike=110 bid=2 dte=7",
      ),
    ).toContain("缺少必要欄位");
  });

  it("rejects inverted, non-decimal and unbounded values", () => {
    expect(
      manualOptionQuoteAnswer(
        "期權試算 ticker=ALPHA type=call spot=100 strike=110 bid=3 ask=2 dte=7",
      ),
    ).toContain("ask 不得小於 bid");
    expect(
      manualOptionQuoteAnswer(
        "期權試算 ticker=ALPHA type=call spot=1e2 strike=110 bid=2 ask=3 dte=7",
      ),
    ).toContain("十進位數字");
    expect(
      manualOptionQuoteAnswer(
        "期權試算 ticker=ALPHA type=call spot=100 strike=110 bid=2 ask=3 dte=0",
      ),
    ).toContain("1 到 730");
  });

  it("formatter is deterministic and contains no account or execution claims", () => {
    const first = formatManualOptionQuote(callInput);
    const second = formatManualOptionQuote(callInput);
    expect(first).toBe(second);
    expect(first).not.toContain("已下單");
    expect(first).not.toContain("帳戶資料");
    expect(first).toContain("不下單");
  });

  it("parser returns a normalized closed input object", () => {
    const value = parseManualOptionInput(
      "options calculator symbol=alpha option_type=CALL price=100 k=110 bid=2.5 ask=2.8 days=7 ccy=usd",
    );
    expect(value).toEqual(callInput);
  });
});
