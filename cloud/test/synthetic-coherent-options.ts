import type { CoveredCallCycle, CoveredCallSuggestion, StrategyLeg } from "../src/v213/covered-call";
import type { DeltaModel } from "../src/v213/option-delta-model";

// Explicitly synthetic test data, never a replay/source repair. Independent analytic BS
// prices use 4% and calendar days. Simpson integration avoids calling production math.
function normalCdf(x: number): number {
  if (x <= -8) return 0;
  if (x >= 8) return 1;
  const steps = 512, width = Math.abs(x) / steps;
  let sum = 1 + Math.exp(-x * x / 2);
  for (let i = 1; i < steps; i++) sum += (i % 2 === 0 ? 2 : 4) * Math.exp(-((i * width) ** 2) / 2);
  return 0.5 + Math.sign(x) * width * sum / (3 * Math.sqrt(2 * Math.PI));
}

function syntheticGreeks(spot: number, strike: number, dte: number, sigma: number, put = false) {
  const years = Math.max(dte, 1) / 365, vol = sigma * Math.sqrt(years);
  const d1 = (Math.log(spot / strike) + (0.04 + sigma * sigma / 2) * years) / vol;
  const d2 = d1 - vol, discounted = strike * Math.exp(-0.04 * years);
  return put
    ? { delta: normalCdf(-d1), price: discounted * normalCdf(-d2) - spot * normalCdf(-d1) }
    : { delta: normalCdf(d1), price: spot * normalCdf(d1) - discounted * normalCdf(d2) };
}

interface QuoteSpec { strike: number; put: boolean; bid: number; ask: number }
function syntheticIv(price: number, spot: number, strike: number, dte: number, put: boolean): number {
  let low = 0, high = 1;
  while (syntheticGreeks(spot, strike, dte, high, put).price < price) high *= 2;
  for (let i = 0; i < 64; i++) {
    const mid = low / 2 + high / 2;
    if (syntheticGreeks(spot, strike, dte, mid, put).price < price) low = mid;
    else high = mid;
  }
  return low / 2 + high / 2;
}
function book(spot: number, dte: number, sigma: number, legs: { strike: number; put: boolean }[]) {
  const quotes: QuoteSpec[] = legs.map(leg => {
    const price = syntheticGreeks(spot, leg.strike, dte, sigma, leg.put).price;
    // Four-decimal synthetic source quotes with a tight relative spread. Rounding
    // happens before IV intersection; no invented model is attached to raw prices.
    const bid = Math.floor(price * 0.98 * 10_000) / 10_000;
    const ask = Math.ceil(price * 1.02 * 10_000) / 10_000;
    if (bid <= 0 || (ask - bid) / (bid / 2 + ask / 2) > 0.25) throw new Error("Synthetic option price too small for a tight four-decimal book");
    return { ...leg, bid, ask };
  });
  const iv_bid = Math.max(...quotes.map(leg => syntheticIv(leg.bid, spot, leg.strike, dte, leg.put)));
  const iv_ask = Math.min(...quotes.map(leg => syntheticIv(leg.ask, spot, leg.strike, dte, leg.put)));
  if (iv_bid > iv_ask) throw new Error("Synthetic option cohort has no common IV interval");
  const delta_model: DeltaModel = { basis: "QUOTE_IMPLIED", iv_bid, iv_ask, sigma: iv_bid / 2 + iv_ask / 2 };
  return { quotes, delta_model };
}
function quoteLimit(bid: number, ask: number, buy = false): number {
  const mid = bid / 2 + ask / 2;
  return buy ? Math.min(ask, Math.max(mid, Math.round((mid / 2 + ask / 2) * 100) / 100))
    : Math.max(bid, Math.min(mid, Math.round((bid / 2 + mid / 2) * 100) / 100));
}
function callItem(role: CoveredCallSuggestion["role"], quote: QuoteSpec, spot: number, dte: number, model: DeltaModel): CoveredCallSuggestion {
  const { strike, bid, ask } = quote, limit = quoteLimit(bid, ask);
  return { role, strike, bid, ask, mid: bid / 2 + ask / 2, limit_price: limit,
    premium_per_contract: Math.round(limit * 10_000) / 100, period_yield: limit / spot,
    annualized_yield: limit / spot * 365 / Math.max(dte, 1), upside_to_strike: strike / spot - 1,
    delta: syntheticGreeks(spot, strike, dte, model.sigma).delta,
    delta_basis: model.basis, iv: Number(model.sigma.toFixed(4)), oi: 1200, volume: 300,
    spread_pct: (ask - bid) / (bid / 2 + ask / 2) };
}

export function syntheticCalls(spot: number, dte: number, highStrike: number, balancedStrike?: number, middleStrike?: number) {
  const years = Math.max(dte, 1) / 365;
  // d1=-1.1 keeps the high-strike delta around .136 for every synthetic clock.
  const sigma = (Math.sqrt(1.21 + 2 * (Math.log(highStrike / spot) - 0.04 * years)) - 1.1) / Math.sqrt(years);
  const strikes = [highStrike, ...(balancedStrike === undefined ? [] : [balancedStrike]), ...(middleStrike === undefined ? [] : [middleStrike])];
  const { quotes, delta_model } = book(spot, dte, sigma, strikes.map(strike => ({ strike, put: false })));
  const suggestions = [callItem("HIGH_STRIKE", quotes[0]!, spot, dte, delta_model)];
  if (balancedStrike !== undefined) suggestions.push(callItem("BALANCED", quotes[1]!, spot, dte, delta_model));
  const middle_suggestion = middleStrike === undefined ? undefined : callItem("MIDDLE", quotes.at(-1)!, spot, dte, delta_model);
  return { delta_model, suggestions, ...(middle_suggestion ? { middle_suggestion } : {}) };
}

/** Only retime explicitly synthetic fixtures. Rebuild every leg and quote-derived
 * economic field together, preserving strikes, roles, labels and normalized vol. */
export function repriceSyntheticCycle(cycle: CoveredCallCycle, dte: number): void {
  if (!cycle.delta_model || cycle.delta_model.basis !== "QUOTE_IMPLIED") throw new Error("Expected a synthetic tight-book model");
  const sigma = cycle.delta_model.sigma * Math.sqrt(Math.max(cycle.dte, 1) / Math.max(dte, 1));
  const cc = [...cycle.suggestions, ...(cycle.middle_suggestion ? [cycle.middle_suggestion] : [])];
  const csp = cycle.strategies?.csp;
  const collar = cycle.strategies?.collar;
  const legs: { leg: StrategyLeg | CoveredCallSuggestion; put: boolean; buy: boolean }[] = cc.map(leg => ({ leg, put: false, buy: false }));
  if (csp && "suggestions" in csp) for (const leg of csp.suggestions) legs.push({ leg, put: true, buy: false });
  if (collar && "items" in collar) {
    legs.push({ leg: collar.put, put: true, buy: true });
    for (const item of collar.items) legs.push({ leg: item.call, put: false, buy: false });
  }
  const { quotes, delta_model } = book(cycle.spot, dte, sigma, legs.map(({ leg, put }) => ({ strike: leg.strike, put })));
  cycle.dte = dte;
  cycle.delta_model = delta_model;
  legs.forEach(({ leg, put, buy }, i) => {
    const quote = quotes[i]!;
    Object.assign(leg, { bid: quote.bid, ask: quote.ask, limit_price: quoteLimit(quote.bid, quote.ask, buy),
      delta: syntheticGreeks(cycle.spot, leg.strike, dte, delta_model.sigma, put).delta, delta_basis: delta_model.basis });
    if ("iv" in leg) Object.assign(leg, callItem(leg.role, quote, cycle.spot, dte, delta_model));
  });
  if (csp && "suggestions" in csp) for (const item of csp.suggestions) Object.assign(item, {
    premium_per_contract: Math.round(item.limit_price * 10_000) / 100, cash_required: item.strike * 100,
    annualized_yield: item.limit_price / item.strike * 365 / Math.max(dte, 1),
    breakeven: item.strike - item.limit_price, downside_buffer: 1 - item.strike / cycle.spot,
  });
  if (collar && "items" in collar) for (const item of collar.items) {
    const net = item.call.limit_price - collar.put.limit_price;
    Object.assign(item, { net_premium_per_share: net, max_loss_per_share: cycle.spot - collar.put.strike - net,
      max_gain_per_share: item.call.strike - cycle.spot + net, break_even: cycle.spot - net,
      worst_case_net_per_share: item.call.bid - collar.put.ask });
  }
}
