# Serenity Public-Logic Fidelity — second-pass re-audit

## Scope

This document records the second-pass audit performed before the first user-side H1 validation run. It exists to prevent the v2.1.3 foundation from passing only superficial tests while still allowing unsupported methodology claims.

The target remains:

> `Public-logic high-fidelity reconstruction`

It is not a claim to reproduce Serenity's private process, hidden sources, discretionary weights, portfolio, or trades.

## Concrete defects found in the first v2.1.3 foundation

### 1. Severe financing break signal was impossible to use

`equity_capture_destroyed_by_financing` existed in the severe-break list but not in the allowed thesis-killer list. A strict parser would therefore reject it before it could ever produce `BROKEN`.

**Correction:** every severe-break signal is now required to be a subset of the allowed thesis-killer set, and the policy self-validation fails otherwise.

### 2. Dependency signals were not bound to the evidence that supposedly proved them

The first implementation counted evidence globally. A record could therefore claim `semi_monopoly`, `qualification_constraint`, `architecture_bypass`, or a commercial event without identifying which filing/customer/roadmap source supported that specific signal.

**Correction:** dependency, commercial-validation, institutional-context, and thesis-killer signals must have `signal_evidence` bindings to primary/corroborating evidence URLs before they affect the fidelity state. Lead-only or unbound signals remain visible as warnings but cannot prove or break a thesis.

### 3. Supply-chain graph edges were not validated strongly enough

The first implementation accepted arbitrary graph dictionaries. It did not require a relationship, date, bound evidence, or even an edge touching the focal company.

**Correction:** only evidence-bound structured edges are retained. A dependency role cannot be promoted unless the validated graph contains an edge that touches the focal company node.

### 4. Architecture/supercycle state could be asserted without bound evidence

A hard dependency plus unrelated primary evidence could still create a bottleneck classification even when the architecture map itself was unsupported.

**Correction:** bottleneck classification now requires an evidence-bound architecture/supercycle identity plus an evidence-bound graph touching the company.

### 5. Customer-named dependency was too easy to overinterpret

A customer mentioning a supplier/component proves linkage, but does not by itself prove single-source supply, scarcity, qualification friction, or a chokepoint.

**Correction:** `customer_named_dependency` remains useful evidence but is explicitly excluded from the `bottleneck_proving_signals` set. It cannot alone create `BOTTLENECK_THESIS`.

### 6. Company capture/optionality was specified in the skill but missing from the engine result

The skill required analysis of qualified capacity/share, financing durability, pricing/contract structure, BOM/product mix, vertical integration, concentration, execution/capex and bypass risk, but the first engine did not expose a company-capture state.

**Correction:** the engine now includes an evidence-bound `company_capture` object with `STRONG / POSITIVE / MIXED / WEAK / DESTROYED / UNPROVEN`. Unsupported positive states are downgraded to `UNPROVEN`; evidence-backed `DESTROYED` can break the equity-capture thesis.

### 7. Information-gap state could be asserted without evidence

The first implementation allowed a caller to directly set `UNDISCOVERED`, `BECOMING_KNOWN`, or `CONSENSUS` without binding that judgment to evidence.

**Correction:** nontrivial information-gap states require primary/corroborating evidence URLs; otherwise the state falls back to `UNKNOWN`.

### 8. Source-delta "append-only" was overclaimed

A pure single-run function can validate ordering inside one snapshot, but cannot prove that older source views were never overwritten across separate runs unless persistent history is compared.

**Correction:** the engine validates chronology/duplicates within the current snapshot and explicitly emits `cross_run_source_delta_append_only_verified = false`. True append-only verification is deferred to a persistent history store in H2/H3.

### 9. Serenity source view was a label, not an explicit output object

The first engine had `source_view_label` but no validated `serenity_source_views` list.

**Correction:** source views are now explicit structured objects, separate from company-fact evidence. A missing source view triggers a warning and must never be interpreted as proof that Serenity discussed the ticker.

### 10. Fidelity confidence was implicit

The methodology policy requires uncertainty to remain visible, but the first engine did not emit a structured confidence state.

**Correction:** the engine now returns `HIGH / MEDIUM / LOW` fidelity confidence with reasons derived from evidence, architecture binding, graph completeness and warnings.

## Fail-closed behavior after re-audit

The engine must prefer `UNPROVEN` or `INSUFFICIENT_EVIDENCE` when any of the following are missing:

- evidence-bound architecture/supercycle context;
- evidence-bound graph edges;
- an edge touching the focal company;
- evidence binding for dependency/commercial/killer signals;
- evidence-backed company-capture claims;
- explicit disconfirmation conditions.

A high legacy quantitative score cannot override `BROKEN`.

## Remaining gaps intentionally deferred to H2/H3

These are not silently considered solved:

1. automated customer-supplier graph extraction from real filings/roadmaps;
2. design-win / LTA / prepayment / qualification event extraction;
3. capacity and lead-time time series;
4. cross-jurisdiction ATM/dilution/share-count normalization;
5. non-U.S. exchange announcement adapters;
6. dated architecture-roadmap ingestion;
7. persistent append-only Serenity source-view history;
8. qualified competitor/substitute mapping;
9. explicit architecture-bypass detection;
10. institutional validation timing without proof-by-authority;
11. real shadow comparisons between the legacy system score and the fidelity state;
12. end-to-end LINE rendering of the new fidelity state without disrupting v2.1.2 production.

Until these exist and pass shadow-run tests, v2.1.2 production remains the stable release and v2.1.3 stays development-only.
