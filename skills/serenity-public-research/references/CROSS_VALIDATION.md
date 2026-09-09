# 深化研究與來源交叉驗證 / Deeper research and source cross-validation

## Scope / 範圍

This extends the preserved RESEARCH_METHOD.md; it is our public-research design, not Serenity's official process. Existing scoring weights, publication contract, LIMITED restrictions and private-data boundaries remain unchanged. Documentation or a source catalog is not proof of a working adapter or live coverage.

## 深度要求 / Required depth

1. **Constraint graph:** bind every demand → component → process → material edge to dated evidence. Identify the minimum constrained layer, qualification time, yield, effective capacity and architectural bypass. Named customer relationships alone are insufficient.
2. **Economic bridge:** distinguish available capacity, achievable yield, utilization, units shipped, disclosed pricing, recognized revenue, GAAP profit and cash flow. Carry currency, units and period. Do not multiply total industry capex by an invented supplier share to manufacture orders.
3. **Shareholder capture:** reconcile growth with capex, working capital, cash burn, debt maturities, SBC, warrants and diluted shares. Separate operating success from per-share value capture. A strong product can coexist with destructive financing.
4. **Counterparty and conversion:** distinguish evaluation, qualification, LOI, design win, signed commitment, cancellable backlog, RPO, shipment and recognized revenue. RPO and backlog are not interchangeable; avoid double-counting them. Record cancellation terms and customer concentration where disclosed.
5. **Scenarios and falsifiers:** separate disclosed commitments from explicit research assumptions. Test slower ramp, substitute capacity, lower pricing/yield and financing delay. State evidence that would overturn the thesis. Scenarios never become numeric total-order estimates in the seven-field report.
6. **Valuation and timing:** separate enterprise value from equity value, GAAP from adjusted earnings, and consolidated from segment figures. Market attention and past price gains are not bottleneck evidence.
7. **Public-view evaluation:** retain losing, neutral, revised and delisted cases, not only winners. If evaluating 1/5/20/60/120 trading-day forward returns, use point-in-time inputs, declared event cutoffs, corporate-action handling, benchmark comparison and drawdown. Label simulated results as hypothetical; do not validate private performance or auto-trade.

## 世界級來源按能力分工 / Source capability matrix

These are source-selection targets, not claims that all feeds are enabled, free or licensed for redistribution.

| Source family / 來源 | Admissible role / 用途 | Boundary / 不可推論 |
| --- | --- | --- |
| SEC EDGAR and issuer IR | Filed financial facts, official commitments, financial notes | Companyfacts and the underlying filing are the same disclosure lineage, not independent witnesses |
| Customer/supplier official IR (e.g. Microsoft, Alphabet, NVIDIA, TSMC, ASML) | Independent counterparty disclosure about its own commitments, capacity or architecture | Logo walls, partnerships and third-party customer guesses do not prove orders or scarcity |
| Nasdaq, NYSE, TWSE/MOPS, HKEX, JPX | Listing identity and relevant official announcements; market data only with verified access rights | An exchange's symbol directory does not validate prices; issuer announcements mirrored by exchanges remain issuer-origin claims |
| Reuters, Bloomberg, Financial Times, WSJ, CNBC | Attributable reporting, corroboration and discovery when publicly accessible and permitted | No paywall bypass, paid activation, bulk scraping assumption or article redistribution; syndicated copies count once |
| Yahoo Finance and separately qualified market providers | Historical market observations with known adjustment basis and permitted usage | Unofficial access is not an authoritative exchange feed; an accessible endpoint is not a redistribution license |
| World Bank, IMF, OECD, FRED/ALFRED, BLS, ECB | Macro, FX, policy and historical revisions within source authority | Macro coverage cannot satisfy company-order evidence; republished original series count as one lineage |
| Public X originals and unaffiliated GitHub research projects | Dated source views and research hypotheses | Not company-fact evidence, not private performance proof; forks and shared tweet archives are one lineage |

## 每項主張的驗證 / Claim-level reconciliation

Retain `claim_id`, security/issuer identity, original publisher and underlying lineage, original URL, publication time, retrieval time, factual as-of period, exact supporting passage, metric definition, unit/currency, adjustment basis, support status and conflicts. Keep source-derived facts separate from model-generated inference.

For comparisons, align ticker/exchange/CIK or equivalent identity, share class/ADR ratio, fiscal period versus calendar period, instant versus duration, GAAP versus adjusted basis, consolidated versus segment values, currency/scale, trading date/timezone, and split/dividend adjustment. Unknown comparability must not be counted as agreement.

Use explicit research reconciliation states:

- `CORROBORATED`: compatible independent evidence supports the same material claim.
- `PRIMARY_ONLY`: attributable primary fact, but no independent corroboration; do not invent a second witness.
- `CONFLICT`: unresolved material disagreement; exclude the disputed conclusion from publication until resolved.
- `NOT_COMPARABLE`: definitions/periods/adjustments differ or are unknown.
- `UNAVAILABLE`: evidence cannot be obtained; retain the existing missing-data text and LIMITED restrictions.

These are research labels, not a new publication-mode schema. Preserve the existing federation thresholds and validator. Report actual per-ticker/per-claim coverage and concentration, not merely successful global endpoints. Multiple sources must add independent relevant evidence, not pad a website count. Retrieving an old filing today does not make the underlying facts current.

## Dynamic discovery and retirement / 動態發現與汰換

These are acceptance requirements, not claims that the live pipeline implements them.

1. **Open discovery:** combine permitted exchange-wide issuer directories with dated regulatory, procurement, company, counterparty, industry and news events. X, forums, podcasts and media can propose hypotheses; popularity, repost count or a famous investor's list adds no evidence score. Do not reserve permanent capacity for AI or any other named sector. Record coverage gaps by exchange/security class and the discovery exclusion stage.
2. **Constraint before ticker:** describe the system change, required function, binding capacity/qualification constraint, effective substitutes and dated expansion response. A large TAM, partnership or rising share price alone is not a bottleneck. Distinguish structural scarcity from temporary allocation and ordinary cyclicality.
3. **Company capture:** connect the scarce layer to accessible capacity, achievable yield, contracted demand, realizable margin/cash flow and diluted per-share capture. Keep each inference's premises explicit. Do not turn announced capacity into available capacity or multiply market capex by a guessed supplier share.
4. **Adversarial validation:** actively seek qualified alternatives, shorter lead times, cancellations, inventory accumulation, price cuts, customer concentration, architecture bypass, funding gaps and dilution. Compare like-for-like units, specification, period, currency and customer platform; conflicting or non-comparable observations do not corroborate one another.
5. **State transitions:** DISCOVERED → EVIDENCE_PENDING → qualified or LIMITED; allow STALE / CONFLICT / THESIS_BROKEN / SUPERSEDED transitions. A removed candidate retains dated reasons; reconsideration needs new evidence, not a fresh retrieval stamp. Trigger review on material events and source-policy expiry, not arbitrary sector rotation.
6. **No guaranteed explosion:** prioritize testable asymmetric opportunities and explicit downside/scenario assumptions. Evaluate out of sample with point-in-time universes, delisted/failed cases, benchmark-relative returns and drawdowns. Backtests or good examples do not establish predictive accuracy.

### Source roles, freshness and concentration

- For material investment conclusions, require relevant independent company-level support under the existing publication policy, including primary evidence. A single attributable filing can remain a PRIMARY_ONLY factual observation; it cannot masquerade as cross-validated thesis support. Listing directories and macro data do not satisfy company-order corroboration.
- Track original publisher, underlying disclosure lineage, role, security identity, source event/period time, retrieval time, exact passage, content hash, rights scope, currency/units and revision/supersession. Financial period end, filing date, retrieval date and market quote time are different clocks.
- Enforce source-specific refresh/freshness policy and exchange/session calendars. An EOD feed must say EOD, not real-time; delayed or unknown quote timing cannot become an executable live limit reference. No unbounded scraping or paid fallback to simulate coverage.
- Reuse unchanged admitted content by hash; deduplicate syndicated stories; use permitted conditional requests, bounded queues, rate limits and backoff. Re-evaluate when evidence changes, not by resending the entire archive to the model. Failed refresh keeps its failed state and must not advance last-success time.
- Report per-claim lineage counts and per-candidate coverage, stale/conflicting/missing fields, provider failure rates and provider/domain concentration at discovery, evidence and publication stages. Multiple APIs of the same publisher are not independent. Global website counts never substitute for these metrics.

### Leopold Aschenbrenner: auxiliary only

Label this layer CONTEXT_ONLY and keep it out of Serenity scoring. Use public, dated deployment/capital/energy scenarios as hypotheses to test against current regulated statistics, actual customer budgets and supplier capacity. His AI-focused examples must not restrict the discovery universe to AI. A historical prediction is not a realized statistic; a delayed13F is not proof of a current position or endorsement. We study transferable reasoning, not copy a portfolio.

## Direct refresh check — 2026-09-09

- Direct X page `https://x.com/aleabitoreddit/status/2083274448845906083` returned HTTP403; this failure remains recorded. A subsequent request to X's official public `https://publish.twitter.com/oembed` endpoint returned an author-matched excerpt dated2026-07-31. It distinguishes2027 ramps from a2028 horizon. The excerpt is truncated: only the returned passage is verified, not the full thread, underlying company facts, current holdings or latest stance. Do not treat an old public addition as a current recommendation.
- Another search lead, `https://x.com/aleabitoreddit/status/2013947011490615486`, returned HTTP404 through official oEmbed. Keep it UNVERIFIED; do not repeat its allegations from the search summary. Additional searches did not establish a latest September source view; absence from results is not proof of absence.
- Retrieved Leopold's original `https://situational-awareness.ai/racing-to-the-trillion-dollar-cluster/`. This is a historical2024 scenario, NOT a new2026 statement. Exact wording includes “These are just very rough numbers anyway” and “the lead times for these are much longer still” when discussing infrastructure. Preserve this uncertainty and test today's constraints independently.
- Search proposed a new fund-portfolio story at `https://www.axios.com/2026/07/30/ai-hedge-fund-situational-awareness-citadel`; direct retrieval returned HTTP403. Do not repeat the search synthesis as a verified transaction or current holding change. No authentication/paywall bypass attempted.
- Public-source rights and actual adapter coverage are separately documented in the repository source review. This research refresh neither enables a provider nor proves live scheduling, global coverage or a functioning screen.

## External review evidence / 外部查閱紀錄

Reviewed on 2026-09-05 UTC:

- [SEC EDGAR APIs](https://www.sec.gov/search-filings/edgar-application-programming-interfaces): public JSON APIs require no API key; filings and XBRL are not price feeds. Custom taxonomies/segment facts are not comprehensively represented by Companyfacts; consult underlying filings. SEC also cautions about differing reporting periods and automated-access policies.
- [quantskills public-research model](https://github.com/quantskills/skill-serenity-research-model/blob/main/SKILL.md): reviewed extraction/review/evaluation concepts, including failed and revised samples. Unaffiliated reconstruction; not proof of Serenity authorship or investment performance. No third-party executable code installed or copied.
- [W-Y-P reconstructed framework](https://github.com/W-Y-P/Serenity-aleabitoreddit-skill/blob/main/references/serenity_framework.md): reviewed architecture, unit economics, financing and failure-mode concepts. Its own snapshot date is 2026-06-12; its supplemental WOOK98 material is not an independent witness. No third-party executable code installed or copied.
- Direct retrieval of [one discovered X candidate](https://x.com/aleabitoreddit/status/2055822766600016238) returned HTTP 403. Its content and current-view relevance are **UNVERIFIED**. Search summaries and archive mirrors do not cure this gap; do not assert a current Serenity ticker stance from this check.

Broader source activation still requires adapter tests, terms/access review, rate limits, redaction, provenance and actual live evidence. Never bypass authentication or paywalls to fill a field.
