# TOP20 Bottleneck Takeover V1: Architecture, Calibration & Production Integration

## 1. Executive Summary & Attribution Boundary

- **Module**: `TOP20_BOTTLENECK_TAKEOVER_V1`.
- **Methodology Reference**: `skills/serenity-public-research/SKILL.md`, `references/RESEARCH_METHOD.md`, `references/CROSS_VALIDATION.md`.
- **Attribution Boundary**: Independent public-logic reconstruction of supply-chain bottleneck methodology. Neither Serenity (`@aleabitoreddit`) nor Leopold Aschenbrenner has authored, reviewed, or endorsed this scoring rubric. Public posts are attributed source views and hypothesis generators, not company facts or investment advice. Leopold Aschenbrenner scenarios remain `CONTEXT_ONLY` and contribute exactly 0.0 points to scoring.
- **Current Runtime Qualification Status**: **DEFERRED** (`status = INSUFFICIENT_EVIDENCE`). Admitted count = 0, ranked count = 0. No legacy fallback and no zero-padding to 20 seats.

---

## 2. Factor-to-Claim Authority Architecture

Prior iterations permitted caller boolean flags (e.g. `corroborated_scarcity=True` or `irreplaceable_architecture_layer=True`) to award factor points whenever any generic company claim (such as a 10-Q revenue statement) was verified.

The Takeover V1 engine enforces strict factor-to-claim authority (`scripts/bottleneck_claim_admission.py`):
1. **Factor Binding**: Every scored factor (`dependency_criticality`, `qualified_scarcity_and_switching`, `pricing_power`, `company_capture`) must specify explicit `claim_ids` referencing reconciled claims in `material_claims`.
2. **Subject & Metric Integrity**: The bound claim must match the candidate's ticker subject and measure the relevant structural mechanism. Generic revenue claims cannot license dependency, scarcity, pricing power, or company capture. Reusing a single claim across all 4 factors is strictly rejected.
3. **Core Four Mandatory Pillars**:
   - **Dependency**: Architecture chokepoint or sole qualified specification. Customer relationship or design win alone is rejected.
   - **Scarcity**: Low effective supplier count (<= 2) or switching latency >= 12 months. Announced CaPex alone without current chokepoint is rejected. Shortage relieved reduces score to 0.
   - **Pricing Power**: Contractual price indexation or realized scarcity pricing. Valid cost passthrough alone is NOT pricing power. High gross margin alone is rejected.
   - **Company Capture**: Equity value capture without destructive financing. Diluted share count / BOM share alone is NOT shareholder capture.
4. **Financing State Enforcement**: Missing financing risk never defaults to `NONE` (defaults to `STRUCTURAL_DISQUALIFIER`). Both `STRUCTURAL_DISQUALIFIER` and `DESTROYED` cannot qualify for capture. `MATERIAL_OVERHANG` applies an evidence-based penalty (5.0 pts) without destroying the thesis.
5. **Fail-Closed Principle**: If any of the 4 core pillars lacks a corroborated, unconflicted `SUPPORTED` claim from at least 2 independent source families, the candidate's factor score is clamped to 0.0 and the candidate evaluates to `UNRANKED_INSUFFICIENT_EVIDENCE`.

---

## 3. Real Structural Archetype Case Studies

### A. Power Transformers Shortage (Hitachi Energy / TSE: 6501)
- **Layer**: Extra-High-Voltage (EHV) Power Transformers, Bushings, Tap-Changers, Electrical Steel.
- **Evidenced Observations**:
  - WoodMac (2025-08-14): US power transformer supply deficit of 30% in 2025; demand up 116% since 2019; imports represent 80% of US power transformer supply. Lead times persist into 2030s.
  - Hitachi Energy (2025-03-10): $250M USD component expansion by 2027 in Virginia, Missouri, and Mississippi.
  - Hitachi Energy (2025-09-29): CAD 270M ($195M USD) expansion in Varennes, Quebec to nearly triple production capacity.
- **Contrary Evidence & Falsifiers**:
  - OEM expansions ($1.8B in North America since 2023) will add capacity by 2027. Announced capacity is not current available capacity.
  - Hitachi Energy is an unlisted operating subsidiary of conglomerate Hitachi, Ltd. (TSE: 6501; FY2024 revenue 9,783.3B JPY, 618 subsidiaries).
  - Critical axis separation: 618 subsidiaries represents conglomerate business-mix exposure materiality, NOT shareholder share dilution. TSE 6501 has no toxic dilution or warrant overhang.
  - No contractual pricing power proof is admitted at the listed security level; cost passthrough is not pricing power.
- **Status**: `UNRANKED_INSUFFICIENT_EVIDENCE`.

### B. Nuclear Enrichment Services (Urenco Consortium / EIA)
- **Layer**: Uranium Enrichment (SWU / Gas Centrifuge Cascades).
- **Evidenced Observations**:
  - Urenco FY2025 Audited Results (2026-03-12): €21.3B order book (+13.9%), revenue €2,096.2M (+11.7%) driven by higher realized prices.
  - EIA 2025 Uranium Marketing: 13.0M SWU purchased across 4 sellers; average price paid $108.70 vs $97.66 (+11.3%).
- **Contrary Evidence & Falsifiers**:
  - Operating leverage failure: Urenco EBITDA margin **fell from 38.8% to 38.4%** despite higher prices.
  - Catalyst horizon: Commercial HALEU production begins in the early 2030s (construction 2028), missing the 6–24 month ramp window. Operational additions (3 US cascades) increase near-term supply.
  - Non-listed entity: Urenco is an unlisted private consortium. It cannot be purchased as a public equity, and enrichment cannot be conflated with mining/conversion (Cameco CCJ).
  - Consortium ownership (1/3 UK, 1/3 NL, 1/3 German utilities) is marked `UNVERIFIED_PUBLIC_LEAD` without statutory registry filing observation.
  - EIA survey average reflects aggregate utility procurement mix, NOT independent corroboration of Urenco contract terms.
- **Status**: `UNRANKED_INSUFFICIENT_EVIDENCE`.

### C. Advanced Packaging (TSMC CoWoS)
- Retrieval of TSMC Annual 2025 returned HTTP 403.
- Status is retained as `UNAVAILABLE` without manufacturing speculative narrative text.

---

## 4. Production & UI Delivery Contract

1. **LINE Delivery**:
   - When TOP20 is requested, if `status = INSUFFICIENT_EVIDENCE` or admitted count = 0, the system responds:
     `系統瓶頸爆發 Top20 核心證據不足（INSUFFICIENT_EVIDENCE）；候選標的尚未取得獨立一級瓶頸與股權捕捉佐證。依政策扣留排名，不退回舊榜單、不補零至20名。 / Top20 bottleneck evidence insufficient; no legacy fallback.`
   - No fallback to legacy 20 seeds (DG, NEM, PBR, etc.).
   - No fallback to generic QA or local model hallucination.
2. **Deep Analysis Flow**:
   - Accessible via pinned snapshot reference.
   - For unranked candidates, deep analysis details why the candidate remains UNRANKED and lists the exact missing core claims.
   - 2Y total return displays `UNAVAILABLE` without authoritative reviewed provenance; never inverts CAGR.
3. **Cardinality**:
   - The ranked list contains strictly between 0 and 20 candidates.
   - When 0 qualify, exactly 0 are ranked.
   - When 1 qualifies, exactly 1 is ranked.
   - Zero-padding and alphabetical backfilling are prohibited.
