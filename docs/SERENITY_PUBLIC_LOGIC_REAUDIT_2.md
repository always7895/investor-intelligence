# Serenity Public-Logic Fidelity — final pre-user-run re-audit

## Purpose

This is the final static/methodology re-audit before asking the repository owner to run the Windows H1 validation. It deliberately searches for ways the first v2.1.3 fidelity engine could still produce a confident thesis from weak, unrelated, undated, or self-asserted evidence.

The target label remains:

> `Public-logic high-fidelity reconstruction`

The project still does **not** claim access to Serenity's private research process, hidden sources, discretionary weights, portfolio, or trades.

## Additional gaps found after the first re-audit

### 1. Evidence rows without usable provenance could still raise confidence

A row labelled primary/corroborating but missing an HTTPS source URL should not increase lifecycle confidence.

**Closed:** provenance-less evidence is no longer counted as proof by the fidelity engine.

### 2. Signal evidence could be undated

Dependency, commercial-validation, or thesis-killer claims with a URL but no valid `as_of` date could previously influence state.

**Closed:** signal evidence now requires both a bound evidence URL and a parseable date.

### 3. Architecture context was not necessarily dated

A bottleneck is architecture- and generation-specific. A correct company relationship tied to an unspecified architecture date can still misclassify a current chokepoint.

**Closed:** architecture/supercycle context used for bottleneck classification must have a valid `as_of` date and primary/corroborating evidence binding.

### 4. Graph-edge dates were only non-empty strings

A malformed date could pass the original graph check.

**Closed:** graph-edge `as_of` values must be parseable dates.

### 5. `BENEFICIARY` could be asserted without evidence

Even a lower-strength beneficiary label is still a company-fact claim and should not come from theme membership or a Boolean supplied by an upstream model.

**Closed:** `beneficiary_signal` now requires primary/corroborating `beneficiary_evidence_urls`; otherwise the dependency role stays `UNPROVEN` unless another supported dependency signal exists.

### 6. An unproven thesis could jump to a validation state

A commercial event such as a qualification could previously yield `COMMERCIAL_VALIDATION` even if architecture/graph/dependency evidence was insufficient to establish the thesis class.

**Closed:** `UNPROVEN` cannot enter commercial/institutional/consensus validation states. It remains `INSUFFICIENT_EVIDENCE` until a thesis class is established.

### 7. `CONSENSUS` could be assigned too easily

Information-gap `CONSENSUS` plus a commercial signal previously sufficed.

**Closed:** consensus now requires information-gap consensus **and** commercial validation **and** institutional/industry validation context. This remains context, never proof by authority.

### 8. A qualitative company-capture label could itself break the thesis

A caller could set `company_capture.state=DESTROYED` and trigger `BROKEN` even without an evidence-bound severe financing/architecture signal.

**Closed:** company-capture state remains an evidence-bound analytical output but does not independently change lifecycle. `BROKEN` requires an evidence-bound severe thesis killer such as `equity_capture_destroyed_by_financing`, `architecture_bypass`, or `factual_dependency_contradiction`.

### 9. Retrieved Serenity source views could lack publication date/horizon

That undermines the rule that public views are time-sensitive and company-specific.

**Closed:** a source view marked `retrieved` now requires a valid `published_at`, non-empty source-view paraphrase, and horizon.

### 10. Retrieved source-delta entries could be semantically empty

Required keys alone were insufficient if the values were blank.

**Closed:** retrieved source-delta rows require valid publication date plus non-empty ticker/theme, source view, horizon, and change-vs-prior text. Current-snapshot chronology is validated.

### 11. Cross-run append-only history could still be misunderstood

A single pure function cannot prove that prior snapshots were never overwritten.

**Closed:** the engine explicitly reports `cross_run_source_delta_append_only_verified=false`. Persistent cross-run append-only verification remains an H2/H3 requirement and must not be claimed before a history store compares runs.

## Regression coverage added

The v2.1.3 unit matrix now explicitly covers:

- evidence-bound semi-monopoly/qualification bottleneck;
- unbound dependency signal rejection;
- customer-named dependency not proving a chokepoint;
- beneficiary classification requiring evidence;
- commercial signal not validating an unproven thesis;
- focal-company graph-edge requirement;
- architecture evidence/date requirement;
- bound severe architecture killer overriding a system score;
- unbound killer not breaking a thesis;
- company-capture `DESTROYED` label alone not breaking a thesis;
- evidence-bound financing destruction breaking equity capture;
- company-capture positive state without evidence downgrading to `UNPROVEN`;
- lead-only social evidence not proving company economics;
- foreign ticker eligibility at the methodology layer;
- source-delta chronology and no cross-run append-only overclaim;
- retrieved source-delta semantic completeness;
- source-view separation from company-fact evidence;
- provenance-less evidence not raising confidence;
- valid-date requirements for signals and architecture;
- retrieved source-view publication date requirement;
- consensus requiring institutional/industry validation context;
- mandatory disconfirmation conditions;
- unknown signal rejection;
- bounded system operationalization score.

## Public-source sanity check

Directly retrievable public posts continue to support the conservative parts of the skill: Serenity describes a preference for semi-monopoly-like supply positions and publicly frames Photonics/Memory as supercycles. Public financing commentary also shows that destructive ATM/dilution structure can be a thesis-level concern. These public examples support looking for concentration, architecture/cycle timing, and financing destruction; they do **not** establish a fixed numerical formula.

## Still intentionally not solved before H1

H1 validates the methodology foundation, not a complete live fidelity research stack. The following remain explicitly deferred to shadow-mode work:

1. real customer/supplier graph extraction from filings, roadmaps and customer disclosures;
2. design-win, qualification, LTA, prepayment and capacity-reservation extraction;
3. capacity/utilization/lead-time time series;
4. cross-jurisdiction dilution/share-count normalization;
5. non-U.S. exchange and issuer-announcement adapters;
6. dated architecture-roadmap adapters;
7. persistent append-only Serenity source-view history;
8. qualified competitor/substitute mapping;
9. explicit architecture-bypass detection;
10. institutional-validation timing without proof-by-authority;
11. live shadow comparison of legacy `System operationalization score` versus fidelity thesis state;
12. production LINE rendering of fidelity state after shadow acceptance.

Until those are implemented and shadow-tested, v2.1.3 must prefer `UNPROVEN`/`INSUFFICIENT_EVIDENCE` instead of fabricating certainty, and the working v2.1.2 production release remains untouched.
