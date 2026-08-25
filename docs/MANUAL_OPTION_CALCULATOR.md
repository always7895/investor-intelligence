# Ephemeral manual option quote calculator

The shared LINE Bot has no production live option BID/ASK provider until a source passes free-access, automation, redistribution and adapter review. It must not fill that gap with scraping, brokerage data, paid feeds or invented quotes.

As a deterministic fallback, an allowlisted direct-chat user may supply a complete quote in one message:

```text
期權試算 ticker=ALPHA type=call spot=100 strike=110 bid=2.50 ask=2.80 dte=7 currency=USD
```

Traditional-Chinese field aliases are also accepted:

```text
期權試算 代號=BETA 類型=賣權 現價=100 履約價=90 買價=1.00 賣價=1.20 天數=30 幣別=USD
```

## Output scope

The calculator performs arithmetic only:

- midpoint and bid/ask spread;
- spread as a percentage of midpoint;
- a non-binding sell-limit observation from one quarter of the spread above bid through midpoint;
- annualized premium observations using spot for calls and strike for puts;
- call effective-sale-price observations;
- put break-even and one-standard-contract cash-requirement observations;
- weekly, monthly or custom DTE classification.

It does not fetch or verify a quote, infer Delta, use open interest or volume, recommend a trade, guarantee execution or place an order. Every response is marked `USER_SUPPLIED_NOT_VERIFIED`.

## Privacy boundary

The parser accepts only a closed `key=value` schema. Account, portfolio, position, holdings, shares, quantity, contracts, cost basis, P&L, margin and buying-power fields are rejected. First-person holdings or account disclosures are rejected before calculation.

The calculation runs only after LINE signature validation, direct-chat allowlisting, tenant derivation, event deduplication and rate limiting. The input is not written to public KV, not included in the public snapshot and not sent to the local model. No broker or IBKR path exists.

## Fail-closed behavior

Unknown fields, duplicates, missing fields, scientific notation, non-finite values, inverted bid/ask, invalid tickers, invalid currency or DTE outside 1–730 days return a bounded usage error. Ordinary option questions are not intercepted and continue through the public-snapshot gate, which remains disabled without a reviewed provider.
