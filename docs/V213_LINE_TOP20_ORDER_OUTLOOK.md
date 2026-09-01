# v2.1.3 LINE Top 20 — order-outlook extension

## User-visible target

The final LINE Top 20 presentation is extended from five to seven fields, with the
new fields appended after the existing profit summary:

1. 股票
2. 長期投資報酬率（近2年年化）
3. 短期投資報酬率（近6個月）
4. 行業別
5. 獲利簡述
6. 公司現在訂單
7. 未來訂單預估

The v2.1.2 Production Worker remains unchanged while this v2.1.3 contract is
validated.

## Meaning of 公司現在訂單

This is not a generic revenue estimate.  It may use only evidence such as:

- disclosed backlog / order book / bookings;
- signed purchase commitments;
- minimum order quantities or annual purchase commitments;
- fixed-quantity supply agreements;
- capacity-reservation agreements with customer deposits/prepayments;
- other explicit company/customer order commitments from official filings or
  official issuer/counterparty releases.

If a comparable order number is not disclosed, the field must say:
`未揭露（無可靠公開訂單數字）`.

## Meaning of 未來訂單預估

This is an evidence-bound outlook, not a model-invented dollar forecast.  It may
summarize signed future commitments, disclosed ramp schedules, order-book guidance,
customer production ramps, or explicit company guidance.  It can state a direction
or visibility horizon (for example `能見度偏高`, `偏增`, or `無可靠公開預估`).

A precise total order/revenue number is prohibited unless the amount is directly
supported by public evidence or can be arithmetically derived from explicit public
contract terms.

## Provenance

Source URLs and as-of metadata remain in the machine payload but are not added as
extra LINE display columns.  The LINE message stays exactly seven columns.

## AXTI example from filed agreements

Current public commitments include:

- Casela: binding 2027 fixed aggregate InP quantity, total RMB 173m (about US$25.4m),
  with at least an 80% purchase requirement;
- Coherent: initial three-year 6-inch InP supply/capacity commitment, US$22.2885m
  prepayment, minimum-order mechanics, and AXT manufacturing-capacity expansion
  during 2026-2028;
- Lumentum: six-year minimum annual InP capacity reservation with two US$43.5m
  deposits and annual purchase-commitment mechanics.

These agreements support high order visibility but do **not** establish the total
future revenue from all customers, and they do not prove a Serenity-style hard
bottleneck by themselves.

## Release gate

The seven-field format will not replace the live v2.1.2 five-field LINE report
until:

- order/outlook extraction is evidence-bound across the full current Top 20;
- missing disclosure renders fail-closed placeholders rather than fabricated data;
- the 20-row rank order still matches the signed Top 20 snapshot;
- Worker parse/render tests pass;
- a real LINE test push confirms the seven-field output.
