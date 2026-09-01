# Investor Intelligence v2.1.3 — H6B1 Full Top20 Order/Outlook Shadow

## Purpose

H6A passed the public-methodology/source-fidelity audit. H6B1 now applies the
accepted rules to the *current installed v2.1.2 Top 20* without changing its
rank, returns, industry or profit fields.

H6B1 appends the two requested LINE fields in shadow only:

1. 股票
2. 長期投資報酬率（近2年年化）
3. 短期投資報酬率（近6個月）
4. 行業別
5. 獲利簡述
6. 公司現在訂單
7. 未來訂單預估

No LINE message is sent in H6B1. H6B2 is the real LINE seven-field test-push and
user-acceptance stage.

## Findings carried forward from H6A

### Multi-axis confidence is authoritative

The legacy one-dimensional `fidelity_confidence.state` is retained only for
compatibility and is deprecated for downstream decisions. High factual confidence
does not prove a hard dependency.

### Operating thesis is separate from bottleneck/dependency

H6A exposed one remaining semantic inconsistency in SIVE:

- official customer-ramp evidence exists;
- company capture is positive;
- GlobalFoundries independently corroborates the relationship;
- financing pressure is material;
- hard dependency is not proven.

H6B therefore reconciles the **operating axis** to `COMMERCIAL_VALIDATION` while
preserving `BENEFICIARY` and refusing a bottleneck promotion.

### Source-view history is now checkpointable across runs

H6A provides a prior checkpoint of 4 entries with latest record hash:

`3b1e34fdd385ec3816a4f60a9f803cd1a3f64d2899cdc81c49e4cf5f36ed8102`

H6B can verify that later source history preserves that checkpoint. H6B1 does
not append unverified archive leads.

### Canonical Skill

The canonical v2.1.3 methodology is:

`skills/serenity-public-research/SKILL.md`

`skills/serenity-bottleneck.md` remains a compatibility reference. If the two
ever conflict, the canonical Skill wins.

## Order evidence contract

`公司現在訂單` accepts only evidence such as disclosed backlog, remaining
performance obligations, order book, named production orders, signed customer
purchase commitments, fixed/minimum-take quantities, capacity reservations and
customer prepayments. Supplier purchase obligations are not customer orders.

`未來訂單預估` is either a signed future commitment/window or a clearly labelled
inference from official order/ramp guidance. A pipeline is not a booked order.
Guidance is not backlog. No model-generated total order/revenue figure is allowed.

When evidence is absent the output is explicit:

- `未揭露（無可靠公開訂單數字）`
- `無可靠公開預估`

## Strong public examples used as validation adapters

### AXTI

The accepted H5/H6 evidence object already binds Casela, Coherent and Lumentum
multi-year/fixed/minimum/capacity commitments. It supports contracted visibility
but not a total revenue estimate and not a hard dependency.

### TSEM

Tower's May 13, 2026 official release disclosed $1.3B of 2027 SiPho customer
contracts and $290M of customer prepayments, with a larger 2028 contractual wafer
commitment. The July 14 expansion provides the capacity/ramp window.

### COHR

The March 2, 2026 NVIDIA/Coherent agreement is multiyear, nonexclusive and
contains a multibillion-dollar NVIDIA purchase commitment plus future access and
capacity rights. Coherent's August 12 results report exceptional customer demand,
capacity expansion and multiple new platforms beginning to ramp.

### SIVE

Sivers' August 27 Q2 release reports an $8.2M ALL.SPACE production order and a
$1.2B opportunity pipeline. The September 1 CEO letter additionally describes
initial $3M Tachyon and $3.4M SemiNex orders and expected future LiDAR/Jabil order
windows. H6B keeps pipeline separate from booked orders.

## Generic SEC fallback

For other U.S. Top20 issuers, H6B scans a bounded set of recent official SEC
filings for explicit numeric backlog/RPO/order-book/bookings/production-order
language. It fails closed if the context is missing, hypothetical or looks like
the issuer's own supplier purchase obligation.

Generic extraction is intentionally conservative; it is better to show
`未揭露` than manufacture precision.

## Dependency boundary

Order visibility is commercial evidence, not scarcity evidence. H6B1 is
forbidden to create `SINGLE_SOURCE`, `SEMI_MONOPOLY`,
`QUALIFICATION_CONSTRAINED` or `CAPACITY_BOTTLENECK` from order data alone.

AXTI specifically remains fail-closed because qualified suppliers and competitors
are disclosed while effective available current-ramp substitute capacity has not
yet been independently proven.

## Production boundary

H6B1 reads the current installed v2.1.2 Top20 and generates a 20-row seven-field
shadow JSON and text preview. It does not deploy Worker, write KV, change
schedules, or send LINE.

H6B2 will perform a real LINE seven-field test push only after H6B1 passes and
the generated 20-row preview is audited.
