# Serenity public-logic fidelity skill

> Primary public source: Serenity (`@aleabitoreddit`) on X.
>
> Fidelity boundary: this file models only reasoning patterns that can be supported by identifiable public posts. It is **not** a claim to reproduce Serenity's private research process, portfolio, hidden data sources, or discretionary judgment. Serenity has not endorsed this project.

## 1. What the public record supports

The public record supports a research style with these recurring characteristics:

1. **Supply-chain-first reasoning.** Start from an architecture, capacity constraint, material, process, qualification path, or infrastructure bottleneck and work toward listed companies rather than starting from a stock screener.
2. **Bottleneck vs. beneficiary distinction.** A company can benefit from an AI or semiconductor cycle without controlling a hard-to-replace link. The thesis becomes stronger when there is evidence of single-source, semi-monopoly, scarce qualified capacity, difficult qualification, proprietary process knowledge, or an otherwise constrained path.
3. **Information synthesis.** The edge can come from connecting public supply-chain facts that are individually known but not yet synthesized by the market.
4. **Expansion thesis vs. bottleneck thesis.** A normal growth/expansion company should not automatically be analyzed with the same logic as a chokepoint company. A bottleneck thesis requires explicit supply-chain dependency evidence.
5. **Supercycle/architecture timing.** Photonics, memory and other infrastructure cycles are treated as evolving architectures. The relevant question is not only current revenue, but where the architecture is moving, when qualification/volume ramps occur, and which component becomes binding as the cycle advances.
6. **Undiscovered/global search.** Public posts repeatedly discuss smaller suppliers outside the largest U.S. listings, including European photonics/semiconductor names. A U.S.-only universe is therefore not a faithful representation of the public method.
7. **Semi-monopoly preference.** Serenity has publicly stated a preference for semi-monopoly-like positions in parts of the photonics supply chain. This is evidence for looking at supplier concentration and qualified alternatives, not for awarding automatic points from a category label.
8. **Financing can invalidate a good operating thesis.** Repeated ATM issuance, toxic dilution, or other financing behavior can materially weaken or break support for a company even when the underlying market grows.
9. **Entry/timing matters.** A long-term operating thesis and a short-term entry decision are separate. A company-specific long-term thesis does not imply a universal holding-period rule.
10. **Discretionary and revisable.** New evidence, customer changes, architecture changes, financing, valuation/expectations, and timing can change a view. The public method is not a static 100-point formula.

### Primary-source registry used by this skill

- short-term entry points / recap context: https://x.com/aleabitoreddit/status/2045965735386820934
- discretionary AXTI/InP thesis: https://x.com/aleabitoreddit/status/2063465386960736396
- company-specific long-term revenue/operating-income thesis: https://x.com/aleabitoreddit/status/2075496116481884524
- financing/ATM weakening support: https://x.com/aleabitoreddit/status/2090903631793127644
- semi-monopoly preference, AXTI/SOI/TSEM/COHR/SIVE/AAOI context: https://x.com/aleabitoreddit/status/2033889361801175094
- photonics and memory supercycle framing: https://x.com/aleabitoreddit/status/2034752613246542215
- information-synthesis / SOI monopoly framing: https://x.com/aleabitoreddit/status/2044491122161160517
- bottleneck-game-theory vs expansion-thesis framing: https://x.com/aleabitoreddit/status/2038101004252753959
- infrastructure bottleneck example (transformers/switchgear): https://x.com/aleabitoreddit/status/2041168871168545115
- European/strategic chokepoint context: https://x.com/aleabitoreddit/status/2047110496999137730
- financing-structure warning example: https://x.com/aleabitoreddit/status/2013947011490615486

The system must preserve each post's date, company-specific scope, and uncertainty. If a post cannot be retrieved or independently verified during a run, the system may retain the URL as a lead but must not invent its contents.

## 2. What must NOT be attributed to Serenity

No reviewed primary source establishes that Serenity published or endorsed:

- this repository's exact seven-factor 100-point score;
- equal or fixed weights for demand, chokepoint, pricing power, replacement friction, TAM, valuation, or evidence quality;
- automatic market-cap, price, volume, P/S, P/E, margin, beta, or short-interest cutoffs;
- automatic entry at 60 or exit below 40;
- a blanket two-year holding rule;
- an automatic penalty schedule such as `high_beta = -3`;
- the Power/Compute/Components taxonomy as an official Serenity framework;
- fixed position sizes or options prescriptions;
- an endorsement of every ticker discovered by this project.

Any such numerical rule is a **System operationalization**, not a `Serenity score`.

---

# 3. Public-logic fidelity engine

The fidelity engine must not output a single number labelled as Serenity's score. It must produce a structured, auditable thesis state.

## Stage A — Architecture / supercycle map

Before scoring a company, identify the relevant architecture or cycle:

- compute / accelerators;
- HBM / NAND / memory hierarchy;
- networking / Ethernet / interconnect;
- pluggable optics / 800G / 1.6T;
- silicon photonics / CPO / external light sources;
- substrates / epi / wafers / foundry / packaging / test;
- datacenter power / transformers / switchgear / cooling;
- neocloud / physical AI infrastructure;
- another explicitly evidenced cycle.

Record:

- current architecture generation;
- next architecture generation;
- qualification stage;
- expected volume-ramp window if publicly evidenced;
- evidence URLs and dates;
- what would invalidate the timing assumption.

Do not infer a fixed 8–12 month lead universally. Preserve the timing stated by each source.

## Stage B — Supply-chain dependency graph

Build a graph, not a keyword list:

`end customer -> platform/architecture -> module/system -> component -> process -> wafer/substrate/material -> equipment/capacity`

Every claimed edge must have evidence. Unknown links stay `unknown`.

For the focal company, classify its dependency role:

- `SINGLE_SOURCE` — evidence supports effectively one qualified source for the relevant link;
- `SEMI_MONOPOLY` — very concentrated qualified supply with few credible alternatives;
- `QUALIFICATION_CONSTRAINED` — alternatives exist but switching/qualification is materially difficult or slow;
- `CAPACITY_BOTTLENECK` — the relevant qualified capacity is binding;
- `BENEFICIARY` — demand helps, but the architecture can function without this supplier;
- `UNPROVEN` — insufficient evidence.

A company name, sector, margin, or keyword can never by itself set a bottleneck class.

## Stage C — Information-gap test

Assess whether the thesis depends on public facts that appear under-synthesized rather than merely unknown.

Evidence can include:

- small or foreign listing with limited coverage;
- supplier/customer disclosures not joined together by consensus research;
- recent architecture roadmap change not yet visible in reported revenue;
- contracts, LTAs, prepayments, design wins, qualification or capacity announcements that precede reported revenue;
- institutional validation appearing after the original public thesis.

Output one of:

- `UNDISCOVERED`
- `EARLY_DISCOVERY`
- `BECOMING_KNOWN`
- `CONSENSUS`
- `UNKNOWN`

This is a qualitative state, not a valuation bonus.

## Stage D — Bottleneck vs expansion thesis

Classify:

- `BOTTLENECK_THESIS`
- `EXPANSION_THESIS`
- `HYBRID`
- `UNPROVEN`

A bottleneck thesis requires at least one hard dependency signal from Stage B plus corroborating evidence. Revenue growth alone is not sufficient.

An expansion thesis may be attractive, but it should be evaluated with ordinary company economics rather than being granted chokepoint status.

## Stage E — Company capture and optionality

Test whether the company can economically capture the architecture change:

- qualified share/capacity;
- ability to expand without destructive financing;
- pricing/contract structure;
- BOM share and product mix;
- vertical integration or adjacent-product optionality;
- customer concentration;
- execution/capex requirements;
- whether a substitute architecture can bypass the company.

Gross margin and revenue growth are evidence inputs, not substitutes for these questions.

## Stage F — Thesis-killer / disconfirmation engine

Explicitly search for contrary evidence. Minimum categories:

- repeated ATM or other material dilution;
- toxic warrants / financing transfer to insiders or arbitrage;
- customer loss or concentration deterioration;
- architecture shift that bypasses the component;
- new qualified competitor;
- qualification or volume-ramp delay;
- capacity expansion that removes scarcity faster than demand grows;
- pricing collapse;
- export-control / jurisdictional disruption;
- balance-sheet inability to fund the ramp;
- factual contradiction of a claimed supply-chain edge.

A severe financing or architecture event can move a thesis directly to `THESIS_WEAKENING` or `BROKEN` even if reported revenue is still growing.

## Stage G — Thesis lifecycle

Output exactly one state:

- `DISCOVERY`
- `EARLY_VALIDATION`
- `COMMERCIAL_VALIDATION`
- `INSTITUTIONAL_VALIDATION`
- `CONSENSUS`
- `THESIS_WEAKENING`
- `BROKEN`
- `INSUFFICIENT_EVIDENCE`

State transitions must cite the event/evidence that caused them.

Examples of transition logic:

- `DISCOVERY -> EARLY_VALIDATION`: supplier/customer/roadmap linkage gains primary corroboration.
- `EARLY_VALIDATION -> COMMERCIAL_VALIDATION`: design win, contract, prepayment, qualification, capacity reservation, or realized revenue supports the path.
- `COMMERCIAL_VALIDATION -> INSTITUTIONAL_VALIDATION`: credible institutional/industry validation appears after the thesis; this is context, not proof by authority.
- any state -> `THESIS_WEAKENING`: material contradiction, dilution, delay, substitute, or financing risk worsens.
- any state -> `BROKEN`: core dependency/architecture thesis is falsified or financing/governance destroys the equity capture mechanism.

## Stage H — Timing / entry context

Keep these separate:

- `operating_thesis_horizon`
- `architecture_ramp_window`
- `entry_context`
- `valuation_expectation_context`

Never convert a company-specific long-term thesis into a universal two-year hold rule.

## Stage I — Global universe

The fidelity research layer must be exchange-agnostic. It may examine U.S., Canadian, European, Nordic, UK/AIM, Taiwanese, Japanese, Korean, Hong Kong, or other listed suppliers when lawful public evidence is available.

The deterministic U.S.-SEC scoring universe may remain U.S.-only for data-quality reasons, but that limitation must not be presented as a Serenity-method limitation.

## Stage J — Source delta

For each Serenity public-source item tracked by the system, store:

- `url`
- `published_at` when known
- `ticker_or_theme`
- `source_view`
- `stance` (`positive`, `negative`, `mixed`, `neutral`, `unknown`)
- `horizon`
- `what_changed_vs_prior_source_view`
- `retrieval_status`

Never overwrite an older source view; append a new dated view so thesis reversals remain visible.

---

# 4. Relationship to the existing 100-point engine

The existing seven-factor score is retained only as:

`System operationalization score`

It is a reproducible quantitative overlay and may be useful for ranking, but it must not be called a `Serenity score` or treated as a faithful copy of Serenity's discretionary method.

The public-logic fidelity engine is authoritative for labels such as:

- bottleneck vs beneficiary;
- thesis lifecycle;
- source-derived Serenity view;
- disconfirmation state;
- architecture timing;
- information gap.

The quantitative score may not override a `BROKEN` fidelity state.

# 5. Evidence hierarchy

1. **Primary/strong** — regulatory filings, exchange announcements, named contracts, customer/supplier disclosures, audited statements, official roadmaps, official capacity/qualification statements.
2. **Corroborating** — adjacent-company calls, government documents, credible technical/industry publications, reputable institutional research where redistributable.
3. **Lead only** — social posts, search snippets, price action, unnamed rumors, community summaries.

Serenity posts are primary evidence for **what Serenity publicly said**, but not primary evidence that the underlying company fact is true. Company facts should be independently corroborated whenever possible.

# 6. Required output labels

Every research answer using this skill must distinguish:

- `Serenity source view` — faithful, dated paraphrase with URL;
- `Public-logic fidelity state` — the structured stages above;
- `System operationalization score` — repository-authored quantitative ranking;
- `Model inference` — conclusion inferred from evidence;
- `User long-term overlay` — repository-owner preference, separate from Serenity;
- `Contrary evidence / thesis killers` — explicit disconfirmation section.

# 7. Fail-closed rules

- Missing evidence does not become positive evidence.
- A sector keyword cannot establish a chokepoint.
- High gross margin cannot establish replacement friction.
- Revenue growth cannot establish TAM capture by itself.
- High beta or short interest cannot be described as a Serenity-authored penalty.
- Foreign listings cannot be excluded merely because SEC companyfacts is unavailable.
- A social-media post cannot independently prove company economics.
- A thesis with no explicit disconfirmation conditions is incomplete.
- The system must never claim `100% identical to Serenity`. The highest defensible label is `public-logic high-fidelity reconstruction`.