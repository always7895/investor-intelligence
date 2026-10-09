import { describe, expect, it } from "vitest";
import { assertLineMessages } from "../src/line-messages";
import {
  buildEducationalStrategyFlex,
  buildEducationalStrategyText,
  EDUCATIONAL_DISCLAIMER,
  EDUCATIONAL_STATUS,
  EDUCATIONAL_STRATEGIES,
} from "../src/v213/educational-options";
import { validateEducationalStrategyCard } from "../src/v213/market-product-schema";

describe("Standalone Educational Options Strategies", () => {
  it("contains exactly the four mandatory educational strategies", () => {
    expect(EDUCATIONAL_STRATEGIES).toHaveLength(4);
    const ids = EDUCATIONAL_STRATEGIES.map(s => s.strategy_id);
    expect(ids).toEqual(["covered_call", "cash_secured_put", "bull_call_spread", "protective_put"]);
  });

  it("every strategy card includes mandatory disclaimers, synthetic markers and payoff references", () => {
    for (const card of EDUCATIONAL_STRATEGIES) {
      expect(card.disclaimer).toBe(EDUCATIONAL_DISCLAIMER);
      expect(card.status).toBe(EDUCATIONAL_STATUS);
      expect(card.simulated_as_of).toBe("2026-09-14T00:00:00Z");
      expect(card.illustrative_ticker).toBe("EXAMPLE");
      expect(card.payoff_reference).toBeDefined();
      expect(card.payoff_reference.contract_multiplier).toBe(100);
      validateEducationalStrategyCard(card);
    }
  });

  it("verifies genuine arithmetic for Covered Call", () => {
    const cc = EDUCATIONAL_STRATEGIES.find(s => s.strategy_id === "covered_call")!;
    expect(cc.breakeven).toContain("$97.00");
    expect(cc.maxprofit).toContain("$8.00");
    expect(cc.maxprofit).toContain("$800.00");
    expect(cc.maxloss).toContain("$97.00");
    expect(cc.maxloss).toContain("$9,700.00");
    expect(cc.payoff_reference.breakeven_price).toBe(97.0);
    expect(cc.payoff_reference.max_profit_amount).toBe(800.0);
    expect(cc.payoff_reference.max_loss_amount).toBe(9700.0);
    expect(cc.assumptions.collateral).toContain("100 股現股");
  });

  it("verifies genuine arithmetic for Cash-Secured Put", () => {
    const csp = EDUCATIONAL_STRATEGIES.find(s => s.strategy_id === "cash_secured_put")!;
    expect(csp.breakeven).toContain("$87.50");
    expect(csp.maxprofit).toContain("$2.50");
    expect(csp.maxprofit).toContain("$250.00");
    expect(csp.maxloss).toContain("$87.50");
    expect(csp.maxloss).toContain("$8,750.00");
    expect(csp.payoff_reference.breakeven_price).toBe(87.5);
    expect(csp.payoff_reference.max_profit_amount).toBe(250.0);
    expect(csp.payoff_reference.max_loss_amount).toBe(8750.0);
    expect(csp.assumptions.collateral).toContain("100% 全額現金擔保 $9,000.00");
  });

  it("verifies genuine arithmetic for Bull Call Spread", () => {
    const bcs = EDUCATIONAL_STRATEGIES.find(s => s.strategy_id === "bull_call_spread")!;
    expect(bcs.debit_credit).toContain("淨付出權利金 $2.50");
    expect(bcs.breakeven).toContain("$102.50");
    expect(bcs.maxprofit).toContain("$7.50");
    expect(bcs.maxprofit).toContain("$750.00");
    expect(bcs.maxloss).toContain("$2.50");
    expect(bcs.maxloss).toContain("$250.00");
    expect(bcs.payoff_reference.breakeven_price).toBe(102.5);
    expect(bcs.payoff_reference.max_profit_amount).toBe(750.0);
    expect(bcs.payoff_reference.max_loss_amount).toBe(250.0);
    expect(bcs.assumptions.specific_caveats).toContain("Legging Risk");
  });

  it("verifies genuine arithmetic and UNBOUNDED profit for Protective Put", () => {
    const pp = EDUCATIONAL_STRATEGIES.find(s => s.strategy_id === "protective_put")!;
    expect(pp.breakeven).toContain("$103.00");
    expect(pp.maxloss).toContain("$8.00");
    expect(pp.maxloss).toContain("$800.00");
    expect(pp.maxprofit).toContain("UNBOUNDED");
    expect(pp.maxprofit).toContain("理論無限");
    expect(pp.payoff_reference.breakeven_price).toBe(103.0);
    expect(pp.payoff_reference.max_profit_amount).toBe("UNBOUNDED");
    expect(pp.payoff_reference.max_loss_amount).toBe(800.0);
    expect(pp.assumptions.specific_caveats).toContain("Premium Drag");
  });

  it("renders compliant Flex carousel with all 4 strategies (<=5 bubbles)", () => {
    const flex = buildEducationalStrategyFlex();
    assertLineMessages(flex);
    expect(flex).toHaveLength(1);
    const contents = (flex[0] as any).contents.contents;
    expect(contents).toHaveLength(4);
    const flexStr = JSON.stringify(flex);
    expect(flexStr).toContain("教學範例，非推薦");
    expect(flexStr).toContain("Covered Call");
    expect(flexStr).toContain("Cash-Secured Put");
    expect(flexStr).toContain("Bull Call Spread");
    expect(flexStr).toContain("Protective Put");
  });

  it("renders single strategy in Flex when requested", () => {
    const flex = buildEducationalStrategyFlex("cash_secured_put");
    assertLineMessages(flex);
    expect(flex).toHaveLength(1);
    const contents = (flex[0] as any).contents.contents;
    expect(contents).toHaveLength(1);
    expect(JSON.stringify(contents)).toContain("Cash-Secured Put");
  });

  it("renders compliant Text presentation within LINE length limits", () => {
    const text = buildEducationalStrategyText();
    assertLineMessages(text);
    expect(text.length).toBeLessThanOrEqual(5);
    for (const msg of text) {
      expect(msg.type).toBe("text");
      if (msg.type === "text") {
        expect(msg.text.length).toBeLessThanOrEqual(4900);
      }
    }
    const textStr = JSON.stringify(text);
    expect(textStr).toContain("教學範例，非推薦");
    expect(textStr).toContain("UNBOUNDED（理論無限）");
  });
});
