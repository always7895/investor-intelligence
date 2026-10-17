# BOTTLENECK_CASE_STUDY_HITACHI_ENERGY_V1

Canonical archetype case study for the **Power Transformer Supply-Chain
Chokepoint** (public observables mapped to the TSE-listed vehicle
Hitachi, and not TSE: 6501, through its Hitachi Energy division). This is a
**QUALITATIVE TYPE reference** (a pattern to be evidenced by improved
primary documents), a ranking rationale and not an investment rationale.
Runtime preserved companies remain strictly 0; nothing in this document
publishes a ranked candidate.

## 1. Structural Mechanism

- **EHV (Extra-High-Voltage) power transformers** for grid transmission
  interconnects, together with their upstream components **bushings** (HV
  insulators/current leads) and grain-oriented **core steel**, constitute a
  physical chokepoint whose output determines grid buildout speed.
- **Import dependence**: US import dependence in EHV large power transformers
  is frequently cited as about 80% (recent report attribution; see D5):
  domestic qualified production capacity is thin relative to replacement
  demand (aging fleet) + new interconnection demand (data centers,
  renewables, EV charging infrastructure).
- **Lead times**: the disclosed lead time is in excess of 30 months for
  large power transformers - 128 to 144 weeks - an order of several times
  the historical 8-12 month range. This is the latency of replacement
  (demand cannot be satisfied by opening new lain capacity within the
  relevant planning horizon, because core steel + bushings + capital and
  qualified labor all constrain simultaneously).

## 2. Primary Sources (Type/Enumeration, Not Citation of Specific Content)

| # | Source Class | Status at time of investigation |
|---|--------------|--------------------------------|
| D1 | Circuit-event announcement of Party A's September 2025 **$1 billion US-denominated North American manufacturing expansion** | Enumerated (Party A's official reporting surfaces; document digests out of scope of this lineage) |
| D2 | **Nikkei** report on 30+ month lead times for EHV power transformers | Enumerated (commercial print; quotations require rights review) |
| D3 | **US DOE grid/reliability reports** (Grid Resilience / system reliability observation) | Enumerated (official observation; warn on OAL/DOI publication lineage) |
| D4 | USITC / Census import-share observation (about 80% EHV import-dependence anchor) | Enumerated (official statistics; digest-specific values require separate verification) |
| D5 | Party A's **investor materials** (segment disclosure: Energy is a portion of a broader group) | Enumerated (investor observation; group composition in Section 4) |

None of these sources instantiate claim records within this lineage; the
typed pipeline (source-preservation -> mechanical evidence enumeration ->
entrusted qualification) consumes them only under its own identity gates.

## 3. The Four-Pillar Core Analysis (Type)

### 3.1 Dependency - Physical Transmission Interconnect Chokepoint
EHV transformers + bushings + core steel sit on the only path by which
generated power reaches load centers. The item is not substitutable by a
familiar component: the voltage class, short-circuit rating, and qualification
cycles (utility testing, NEMA/IEC credentials) make it an irreplaceable
structural layer (engine `dependency_evidence.irreplaceable_architecture_layer`).

### 3.2 Scarcity - Switching Latency >= 12 Months
>30-month lead times (128-144 weeks) satisfy the engine's switching-latency
floor (>= 12 months) many times over: a new qualified supplier facing greenfield
capacity, tooling, and utility requalification cannot enter the market within
the demand horizon. This is the latency of a "scarce asset," not a
convenience (engine `scarcity_evidence.switching_time_months`).

### 3.3 Pricing Power - Indexation and Multi-Year Margin Expansion
Long-term supply agreements with **price indexation** and documented multi-year
realized margin expansion (Party A's announced pricing environment in the
North American market) indicate that the bottleneck monetizes scarcity rather
than passing it through. Engine: `pricing_evidence.contractual_price_
increases_documented` + mechanism=indexation.

### 3.4 Company Capture - Business-Mix Dilution vs. Shareholder Dilution
The decisive differentiation for this archetype:
- **Business-mix dilution (a non-adjacent negative).** Hitachi, Limited (TSE:
  6501) is a **conglomerate of more than 600 companies** across DT
  (Digital Technology), Energy, Connect, and Automotive groups. The Energy
  segment is only a portion of the group equity value: investors bear the
  "mix" dilution. This factor is an immovable adjustment to capture,
  but it is not a disqualifier under the engine rules, and the
  bridge explicitly encodes **"Business mix / company count ≠ share dilution"**.
- **Shareholder dilution (the fatal negative).** It is star-deduction
  when a company's shareholder value is being consumed by **death-spiral
  convertible debt, warrants overlay, or predatory capital formation**. TSE: 6501
  has none of these mechanisms within the scope of this observed window
  (engine `financing_risk` defaults to "NONE" only when the documentation
  is genuine; unknown is never "NONE").

In other words, the archetype tests whether the pipeline can correctly
preserve a capture thesis against an index/dilution family while correctly
and prominently failing on shareholder dilution. The tests
(`tests/test_bottleneck_case_study_hitachi.py`) pin down both directions.

## 4. Invariants

1. This document is a **qualitative type**; it proves nothing about any firm's
   corner-specific current state.
2. **Runtime preserved companies remain strictly 0** - the case study is
   documentation and test fixtures only; the ranking engine remains the sole
   (admission) writer, and it currently preserves nothing.
3. Facts disclosed in Primary D1-D5 are enumerations: until digested and
   passported-source into claim records, they are not evidence of claims.
4. Not investment advice. No brokerage execution exists in this system;
   order/reference parameters elsewhere in the repository remain data
   observations.

## 5. Engine Mapping (Quick Reference)

| Pillar | Engine Field | Type Value |
|--------|--------------|------------|
| Dependency | `dependency_evidence.irreplaceable_architecture_layer` | True (EHV interconnect) |
| Scarcity | `scarcity_evidence.switching_time_months` / `effective_suppliers_count` | 128-144 weeks (= about 30-33 months) / few qualified |
| Pricing | `pricing_evidence.contractual_price_increases_documented` | True, indexation mechanism |
| Capture | `company_capture_evidence.dominant_bom_share` + `financing_risk` | Capture in layer; dilution NONE documented |

(TSE: 6501 is listed on the Tokyo Stock Exchange; Exchange code canonical
format within the engine: "TSE".)