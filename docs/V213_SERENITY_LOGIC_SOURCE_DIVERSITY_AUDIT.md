# Investor Intelligence v2.1.3 — Serenity Logic, Related-Project and Source-Diversity Audit

Audit date: 2026-09-03 (Asia/Taipei)

## 1. Attribution boundary

This project implements a **public-source, high-fidelity reconstruction of useful Serenity-style research logic**. It does not claim to reproduce a private process, an official formula, or an official Serenity score. The numeric result remains a system operationalization overlay and cannot override an evidence-bound broken thesis.

The release boundary is deliberately stricter than an ordinary ranking model:

1. a quantitative screen may nominate a candidate, but cannot prove a bottleneck, pricing power, replacement friction, TAM capture, company capture, or a thesis state;
2. every final candidate must have dated company/claim evidence from multiple independently operated source families and registrable domains;
3. market prices and macro observations are corroboration/context only;
4. conflicting sources are retained for review and never averaged into a synthetic truth;
5. stale data is downgraded or rejected before activation;
6. all seven public payloads must belong to the same fresh run and be committed atomically.

## 2. Reviewed Serenity public-logic layers

The reviewed decision sequence is:

- **Demand wave** — dated evidence that a real demand regime exists; price action alone is insufficient.
- **Architecture and dependency graph** — evidence-bound edges identifying who depends on whom, the relationship, provenance URL, and date.
- **Bottleneck versus expansion** — single-source status, qualification constraints, binding capacity, unique process/IP and credible substitutes must be distinguished from ordinary growth.
- **Company capture** — evaluates whether the public company can economically retain the opportunity after pricing, product mix, customer concentration, financing, dilution, execution, capex and bypass risk.
- **Valuation expectations** — market-path corroboration is required for high confidence; an uncorroborated factor remains capped at 3.75/15.
- **Thesis killers and counterfactuals** — architecture bypass, factual dependency contradiction and financing that destroys equity capture can override a positive overlay.
- **Lifecycle and timing** — discovery, early/commercial/institutional validation, consensus, weakening and broken states are evidence states, not score bands.
- **Information gap** — separates an undiscovered/early thesis from a consensus narrative.
- **Source delta** — new evidence must be dated and compared with the prior source view; unknown remains unknown.
- **System operationalization** — ranking aid only; it cannot manufacture missing evidence or rescue a broken thesis.

## 3. Defects found during the audit

### 3.1 Wrangler mixed-output parsing

The production activation path previously risked parsing Wrangler's human-readable banner as JSON. The hardened path invokes the pinned JavaScript entry point through `node.exe`, isolates stdout/stderr, extracts exactly one balanced deployment JSON document, rejects ambiguity, and verifies the exact active Worker version.

### 3.2 PowerShell native argument loss

A Windows PowerShell automatic-variable collision caused native arguments to disappear in the regression fixture. The parameter was renamed and the direct-Node fixture now verifies mixed stdout, ANSI output, stderr isolation, missing JSON rejection and duplicate JSON rejection.

### 3.3 Stale independent market data treated as LIVE

HF Market Data returned usable rows whose latest `as_of` date was 2026-08-07 during a 2026-09-03 run. Counting those rows as current generated false market conflicts. The release gate now rejects any `LIVE`/`CACHED` market observation older than seven days; stale observations cannot increment independent-provider counts or high-confidence eligibility.

### 3.4 Portfolio-level diversity was insufficient

A portfolio can show several families/domains while an individual ticker still depends on one source. The new bundle boundary therefore enforces, **for every final ticker**:

- at least two claim-relevant source families;
- at least two claim-relevant registrable domains;
- at least one qualifying primary claim source;
- at least 80% dated claim evidence;
- source-level provenance, not only aggregate counters.

### 3.5 Positive factors could outlive their evidence

The new freshness policy separates run freshness, market freshness and company-claim freshness. Positive factors require fresh multi-source and primary evidence. Undated or stale evidence can remain historical context but cannot carry a current positive advantage.

### 3.6 Code-policy drift was not independently checked

Two release audits were added:

- a static audit that verifies the policy, implementation markers, Worker validation, rollback semantics and non-claim boundary;
- a generated-snapshot audit that recomputes payload SHA-256 digests and validates the exact Top20, reports, federation, source audit and freshness sidecar produced by the Windows run.

## 4. Freshness policy

| Evidence class | Maximum age | Publication behavior |
|---|---:|---|
| Activation snapshot and generated sidecars | 2 hours | Reject the run |
| Independent market observation | 7 days | Downgrade/reject as corroboration |
| Official macro observation | 45 days | Mark context unavailable/stale; never substitute for company evidence |
| Current-state company claim | 210 days | Cannot support a current positive factor after expiry |
| Structural claim | 550 days | Historical context only after expiry; must be reconfirmed for current-state inference |

These are maximum safety windows, not permission to ignore a newer available source. Within the retrieved evidence set, the most recent dated evidence controls the current-state view. Older contradictory evidence remains visible as history and cannot be silently discarded.

## 5. Source independence rules

A source count is not an independence count. The effective evidence unit is normalized by source family, registrable domain and claim type. The following never multiply independence:

- two pages from the same registrable domain supporting the same claim;
- parent/sub-brand sources under the same corporate publisher family;
- syndicated copies of the same article or announcement;
- market providers used to support a company fact;
- official macro series used to support a company-specific claim;
- search snippets, social reposts or community summaries that merely repeat a primary source.

For a broader positive inference, the preferred composition is one primary source plus one independently operated corroborator. A narrow disclosed fact can be established by the primary source itself, but a broader claim such as bottleneck, pricing power, replacement friction or durable capture still requires independent corroboration.

## 6. Related projects reviewed and useful design patterns extracted

The audit reviewed public architecture and documentation from the following projects. Their code and branding are not copied; only generally useful engineering patterns are extracted.

### OpenBB Platform

Official project: https://github.com/OpenBB-finance/OpenBB

Useful pattern: provider extensions behind normalized data models. Adopted direction: every provider observation must retain provider ID, family, domain, URL, retrieval status, observed time, data `as_of`, cache age and error disclosure. Provider success cannot be inferred merely because an HTTP request returned data.

### FinRobot

Official project: https://github.com/AI4Finance-Foundation/FinRobot

Useful pattern: role-specialized financial agents and explicit workflow composition. Adopted direction: keep evidence collection, thesis construction, disconfirmation, risk review and publication qualification as separate responsibilities rather than allowing one agent/source to both propose and approve a thesis.

### TradingAgents

Official project: https://github.com/TauricResearch/TradingAgents

Useful pattern: bull/bear debate plus trader and risk-management roles. Adopted direction: positive advantage extraction must be paired with a thesis-killer/counterfactual pass; unresolved material conflict blocks high confidence instead of being averaged away.

### Microsoft Qlib

Official project: https://github.com/microsoft/qlib

Useful pattern: reproducible data/model/strategy/backtest pipelines. Adopted direction: immutable run IDs, payload digests, point-in-time snapshots, exact membership/order validation and explicit separation between research evidence and subsequent outcome evaluation.

### Microsoft RD-Agent

Official project: https://github.com/microsoft/RD-Agent

Useful pattern: iterative research-development loops driven by measurable experiment feedback. Adopted direction: each defect becomes a deterministic regression test and release receipt rather than an informal prompt instruction.

### FinMem

Paper: https://arxiv.org/abs/2311.13743

Useful pattern: layered financial memory with recency, relevancy and importance. Adopted direction: current-state claims use explicit freshness windows; older evidence is retained as historical memory, while fresh contradictory evidence can lower or break the thesis.

## 7. Controls now enforced before delivery

- public-source-only Top20 and reports;
- no private owner watchlist inheritance;
- final diversified scoring version only;
- 20 records in identical order across all seven payloads;
- exact SHA-256 digest verification for every payload;
- at least two per-ticker claim families and domains;
- at least one per-ticker primary claim source;
- dated-evidence coverage threshold;
- fresh multi-source precondition for positive advantages;
- stale market observation rejection;
- no high-confidence inference without fresh market corroboration;
- uncorroborated valuation factor cap;
- unresolved source conflicts block activation;
- market and macro data excluded from company-claim proof;
- one immutable transaction with pointer written last;
- idempotent replay, exact pointer rollback and exact Worker rollback;
- no Production mutation during packaging/qualification.

## 8. Residual limitations and next hardening boundary

The current freshness gate proves that a positive candidate is backed by fresh multi-source evidence, but the ideal next schema is an explicit **factor-to-evidence binding ledger**. Each non-zero factor should carry its own claim, supporting source units, contradicting sources, latest support date and expiry. That will eliminate the remaining possibility that two valid sources support the company generally but not the exact factor receiving a positive contribution.

A second residual limitation is point-in-time outcome evaluation. Research snapshots are immutable, but a complete historical evaluation suite should also freeze provider availability, publication timestamps and delisted/unselected securities to prevent look-ahead and survivorship bias.

Until those two additions are complete, the project should describe factor-level results as evidence-bound public-logic estimates, not verified causal truth.
