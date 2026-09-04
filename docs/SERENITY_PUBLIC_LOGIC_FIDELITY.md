# Serenity Public-Logic Fidelity — v2.1.3 gap audit

## Goal

Build the highest-fidelity reconstruction that can be justified from Serenity's identifiable public posts without claiming access to private process, hidden data, or discretionary weights.

The target label is:

> `Public-logic high-fidelity reconstruction`

The system must never claim `100% identical to Serenity` or `official Serenity formula`.

## Audit of v2.1.0/v2.1.1 engine

| Existing behavior | Fidelity problem | v2.1.3 correction |
|---|---|---|
| AI/photonics/chokepoint keywords can create large chokepoint/replacement-friction proxy scores | Category/keyword exposure is not proof of a bottleneck | Require explicit dependency signals and evidenced supply-chain graph |
| Gross margin increases chokepoint/replacement-friction proxies | Margin can reflect many things and does not prove qualification/substitution difficulty | Margin becomes supporting company-economics evidence only |
| Revenue growth directly drives TAM-capture proxy | A pre-revenue or early-ramp chokepoint can be important before reported revenue captures the architecture | Separate architecture/ramp, company capture, and commercial validation |
| Fixed P/S and P/E bands drive valuation score | Public Serenity posts distinguish bottleneck/game-theory theses from ordinary expansion theses | Separate `BOTTLENECK_THESIS` vs `EXPANSION_THESIS`; retain valuation only as system operationalization/context |
| Beta and short interest are automatic penalties | These are project-authored risk heuristics, not known Serenity rules | Keep only as optional system overlay; never attribute to Serenity |
| U.S. SEC/Nasdaq/NYSE bounds determine the scored universe | Public research includes European/Nordic and other non-U.S. suppliers | Public-logic layer is exchange-agnostic; SEC limitation is only a data-pipeline limitation |
| One deterministic `serenity_score` appears in LINE output | Falsely suggests an official quantitative Serenity formula | UI relabels as `System operationalization score` |
| No formal source-delta timeline | Public views are time-sensitive and can reverse | Append-only source view history with `what_changed_vs_prior_source_view` |
| No explicit thesis lifecycle | A score can stay high even after financing/architecture contradiction | Add lifecycle: DISCOVERY -> VALIDATION -> CONSENSUS / WEAKENING / BROKEN |
| Financing risk is generic numerical penalty | Public financing criticism can directly invalidate equity capture | Material dilution/ATM can force `THESIS_WEAKENING`; destructive equity-capture failure can force `BROKEN` |
| Missing evidence can still leave useful keyword/market proxy points | Encourages false precision | Missing dependency evidence yields `UNPROVEN` / `INSUFFICIENT_EVIDENCE` |

## Public-source behaviors incorporated in v2.1.3

Primary URLs are maintained in `skills/serenity-bottleneck.md`. The current public record supports these broad patterns:

- supply-chain/chokepoint-first research;
- semi-monopoly and qualified-supplier concentration as important patterns;
- information synthesis rather than simple sector screening;
- distinction between bottleneck theses and ordinary expansion theses;
- photonics/memory supercycle and architecture timing;
- global/European undiscovered small-cap search;
- material financing/dilution as a thesis risk;
- company-specific entry/timing and revisable discretionary views.

Each underlying company fact must still be corroborated independently. A Serenity post is primary evidence of Serenity's view, not necessarily primary evidence that the company claim is correct.

## New v2.1.3 architecture

### 1. Source view

A dated, URL-backed paraphrase of the public post. No inferred universal rules.

### 2. Public-logic fidelity state

Structured fields:

- architecture / supercycle;
- supply-chain graph;
- dependency role;
- information gap;
- bottleneck vs expansion thesis;
- company capture/optionality;
- thesis killers;
- thesis lifecycle;
- timing;
- source delta.

### 3. System operationalization score

The legacy quantitative 100-point output. It remains useful for reproducibility but is not allowed to override a `BROKEN` public-logic state and must not be called an official Serenity score.

### 4. Model inference

The local model can synthesize evidence but must mark uncertainty and cannot fill missing dependency edges by assumption.

### 5. User overlay

Long-term holding preferences stay separate and cannot alter the source view or fidelity state.

## High-priority regression cases

These are methodology test archetypes, not permanent endorsements or expected rankings:

- **AXTI-like substrate case:** should require explicit substrate dependency, concentration, qualification and customer/architecture linkage; keyword `InP` alone is insufficient.
- **SIVE-like foreign light-source case:** must not disappear solely because SEC companyfacts is unavailable.
- **AAOI-like vertical-integration case:** operating growth may coexist with financing/dilution risk; a material financing event can weaken the thesis without waiting for revenue decline.
- **COHR/LITE-like established beneficiary case:** broad photonics exposure does not automatically equal an undiscovered chokepoint.
- **TSEM/SOI-like foundry/substrate case:** test whether the company is actually difficult to replace and where it sits in the architecture graph.
- **generic high-margin software stock:** must not become a semiconductor/AI chokepoint from margin or AI wording.

No ticker is hard-coded into production scoring logic.

## Remaining gaps after v2.1.3 foundation

The following require later evidence adapters before a production fidelity engine can be considered complete:

1. structured customer-supplier relationship extraction;
2. qualification/design-win/LTA/prepayment event extraction;
3. capacity and lead-time time series;
4. ATM/dilution/share-count event normalization across jurisdictions;
5. non-U.S. exchange filings and company announcements;
6. architecture roadmap ingestion with dated generation/ramp windows;
7. source-view delta ingestion from publicly retrievable Serenity posts;
8. qualified-competitor/substitute mapping;
9. evidence of institutional validation separated from proof-by-authority;
10. explicit architecture-bypass/disconfirmation detection.

Until those adapters exist, the engine must prefer `UNPROVEN` over a confident bottleneck label.
