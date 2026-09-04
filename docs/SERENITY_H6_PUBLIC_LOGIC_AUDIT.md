# v2.1.3 H6 — Serenity Public-Logic Audit and Refinement

## Scope

This audit compares the accepted H5 v5 R3 shadow output against:

- direct public @aleabitoreddit posts already verified by the project;
- later public-post archives used only as discovery/stance-history leads;
- public Serenity methodology Skills and GitHub distillations;
- Investor Intelligence source-governance docs and fidelity engine rules;
- real H5 output for AAOI, AXTI, SIVE, LITE, COHR, TSEM and SOI.

It does **not** claim to reproduce a private process or official Serenity formula.

## What H5 already gets right

1. Social/Serenity views do not prove company facts or dependency.
2. A named relationship does not automatically prove a bottleneck.
3. AXTI remains `UNPROVEN` despite strong public semi-monopoly language because issuer filings disclose qualified alternatives and current effective substitute capacity is not independently proven.
4. SIVE's GlobalFoundries relationship is an evidence-bound graph edge but does not automatically become a hard dependency.
5. AAOI ATM lineage is separated into two programs plus amendment/completion and is not based on mention counting.
6. SIVE material dilution is fact-separated from the stronger `toxic_financing` judgment.
7. SOI identity was corrected to Soitec and the wrong Yahoo `ZQM.SI` mapping is quarantined.
8. Source-history chaining and DATE_ONLY precision are fail-closed.
9. The v2.1.3 seven-field LINE renderer remains inactive until full Top20 coverage and real LINE acceptance.

## Remaining logic gaps found after H5 PASS

### 1. Source-view freshness is materially incomplete

The persistent verified source history currently contains only four direct public views ending 2026-03-19. Later public archive indexes expose newer original X ids for AAOI, SIVE, AXTI, TSEM and the wider photonics supply-gap thesis.

The project must not silently call the March views "current". Archive-discovered later items enter as `ARCHIVE_ONLY` until direct post text is retrievable/verified. Ticker stance lifecycle must distinguish `ACTIVE`, `AGING`, `STALE`, `SUPERSEDED`, `REVERSED`, and `ARCHIVE_ONLY`.

### 2. Additive enrichment leaves stale warnings

H5 adds official architecture/source views after the base fidelity object was already computed. This leaves contradictions such as:

- a ticker containing Serenity source views while warning that no validated source view is attached;
- SOI containing evidence-bound official architecture while retaining older architecture-missing warnings;
- top-level source-history chain verified while per-ticker `cross_run_source_delta_append_only_verified=false` remains unchanged.

H6 must use a canonical post-enrichment reconciliation pass, not additive patches only.

### 3. One confidence label conflates different questions

All seven H5 names end up `fidelity_confidence=LOW`, even when primary factual evidence is extensive. This is too coarse.

H6 separates:

- factual evidence confidence;
- dependency confidence;
- company-capture confidence;
- identity confidence;
- source-view freshness;
- timing confidence.

Example: AXTI can have HIGH factual evidence confidence, LOW hard-dependency confidence, HIGH company-capture confidence and STALE public-view freshness simultaneously.

### 4. Operating thesis and equity capture need separate state machines

The public methodology treats financing structure as first-class, but public behavior also shows that a company can retain a strong operating thesis while an ATM is a material equity overhang.

H6 therefore separates:

- `operating_thesis_state`;
- `equity_capture_pressure` / `financing_severity`;
- final investability/research state.

`repeated_atm_or_material_dilution` is not automatically equivalent to an operating-thesis failure. Evidence-bound `equity_capture_destroyed_by_financing` remains a severe break signal.

### 5. Qualified substitute != effective substitute at the current ramp

The AXTI case is the central H6 bottleneck test. Public filings disclose multiple qualified substrate suppliers and competitors, while 2026 fixed-quantity, prepayment and multi-year capacity reservations indicate capacity tightness.

The correct state is currently:

- qualified substitutes: proven to exist;
- capacity tightness candidate: supported;
- effective current-ramp substitute capacity: unproven;
- hard dependency: unproven.

H6 must obtain independent current-ramp evidence before allowing `SEMI_MONOPOLY`, `QUALIFICATION_CONSTRAINED`, or `CAPACITY_BOTTLENECK`.

### 6. GitHub/Skill corpus lineage can create false consensus

Several public Skills are forks or distillations of overlapping @aleabitoreddit archives. Counting three Skills that repeat the same original post as three corroborating sources is invalid.

H6 records corpus lineage and sets all methodology/archive Skills to zero factual-corroboration weight. They are useful for:

- discovering original post ids;
- workflow comparison;
- source-view semantic review;
- identifying missing research axes.

They are not company evidence.

### 7. Identity ambiguity must fail closed

A public `serenity-skill` based on `@stockgodserenity` is a different identity/corpus from `@aleabitoreddit`. It must never enter this project's Serenity source history or methodology evidence.

### 8. Source federation breadth is better than active claim coverage

The project catalog has broad global inventory and good admission controls, but the actual H5 records are still dominated by SEC plus lead-only Yahoo/context sources. Many names have zero independent corroborating company evidence.

H6 prioritizes sources by **claim gap**, not source count:

- counterparty filings/releases;
- customer procurement / production schedules;
- qualified competitor/capacity evidence;
- non-US exchange/issuer filings;
- patents, standards and conference technical material when relevant;
- lead-time/allocation/capacity-start evidence.

### 9. SEC parsing should become accession/attachment-aware

Repeated H5 fixes showed the risk of page-length and wording-sensitive regex extraction. The durable pattern is:

`accession -> raw filing/attachments -> deterministic normalized text/sections/XBRL -> content hash -> bounded claim evidence`

Future implementation should borrow this engineering pattern instead of growing one-off regexes indefinitely.

### 10. Final natural-language claims need a grounding audit

Every material output claim should be classified as:

- `SUPPORTED`;
- `INFERENCE`;
- `UNSUPPORTED`.

`UNSUPPORTED` claims are blocked. `INFERENCE` must expose the premises. This is especially important for forward orders, total future revenue, customer-path mapping, semi-monopoly labels and valuation scenarios.

## Public-methodology synthesis

Across direct public posts and independent public distillations, the most durable observable workflow is:

1. start from structural demand/system change;
2. trace the BOM/value chain upstream;
3. rank scarce layers before companies;
4. look for low effective supplier count, qualification friction, hard-to-expand capacity, specialized process/IP, lead times and reservations;
5. map customer/counterparty quality and signed commercial evidence;
6. distinguish pre-ramp qualification from trailing financials;
7. examine financing/equity-capture quality;
8. compare expectations/valuation and timing separately;
9. explicitly state substitution, capacity, architecture, customer, financing and execution falsifiers.

This is a public-methodology reconstruction, not an official Serenity formula.

## H6 release gates before Production

H6 must remain fail-closed until all of the following are true:

1. project-owned `SKILL.md` passes static review;
2. wrong-identity corpus guard passes;
3. source-lineage deduplication passes;
4. source-view lifecycle/freshness passes;
5. stale-warning reconciliation passes;
6. multi-axis confidence passes;
7. financing/operating-thesis separation passes;
8. effective-capacity dependency gate passes;
9. full Top20 seven-field order/outlook population passes;
10. each material generated claim passes claim-level grounding;
11. complete Worker regression passes;
12. real LINE seven-field test push passes;
13. user confirms the LINE output;
14. only then may a separate Production activation stage be prepared.

No H6 audit/refinement work itself changes Production.
