# System Bottleneck Explosion Ranking V1: Research & Policy Specification

> UNACCEPTED DESIGN / 未驗收草案：相關程式仍在工作區審查，focused 測試存在失敗；此文件不代表正式排名、完整市場研究或發布准入。以 state/STATUS.md 與原始測試 receipts 為準。

## 1. Executive Summary & Research Lane

This document defines the research methodology, production root-cause analysis, and versioned policy implementation for **System Bottleneck Explosion Ranking (v1)** (`config/system-bottleneck-explosion-v1.json`, `scripts/bottleneck_ranking.py`).

- **Research Lane Selected**: `SYSTEM_RESEARCH_CANDIDATES` under `skills/serenity-public-research/SKILL.md`.
- **Methodology Boundary**: Public-logic high-fidelity reconstruction (`skills/serenity-bottleneck.md`, `references/RESEARCH_METHOD.md`, `references/CROSS_VALIDATION.md`).
- **Attribution Contract**: Neither Serenity nor Leopold Aschenbrenner has endorsed this project. Public posts are attributed source views and hypothesis generators, not company facts or portfolio recommendations. Leopold Aschenbrenner infrastructure scenarios remain `CONTEXT_ONLY` and contribute zero score bonus.
- **Slice Scope**: Explicit opt-in research-policy slice marked `NOT_PUBLICATION_QUALIFIED`. Existing production weights, R75 contracts, and Worker deploy state remain active and untouched.

---

## 2. Production Ranking Collapse: Root Cause Diagnosis

A critical defect in previous runs was the presence of non-chokepoint companies (such as ACGL, AFRM, BBY, CDE, FIS, HIG, HST) in the top ranking. Our empirical inspection of the published bundle reveals the precise chain of failure:

### A. Ticker Discovery Decoupled from Supply Chains
- **File & Line**: `config/v21-serenity-policy.json` (lines 12–25).
- **Mechanism**: Candidate discovery used Yahoo Finance pre-canned stock screeners:
  - `undervalued_growth_stocks` (weight 5)
  - `most_actives` (weight 2)
  - `day_gainers` (weight 1)
- **Impact**: Tickers like ACGL (insurance), AFRM (fintech BNPL), BBY (consumer retail), CDE (silver mining), FIS (fintech core processing), and HIG (insurance) were ingested purely because of screening market cap or price momentum, completely bypassing supply-chain dependency analysis.

### B. Scoring Factor Collapse to Zero
- **File & Line**: `scripts/v21_serenity_top20.py` (lines 955, 964) and `scripts/v213_apply_diversified_operationalization.py` (lines 314–329).
- **Mechanism**: In `score_candidate`, `chokepoint` and `replacement_friction` were hardcoded to 0 because no dependency graph had been admitted. In `v213_apply_diversified_operationalization.py`, factors were strictly zeroed:
  - `demand_wave = 0.0`
  - `chokepoint = 0.0`
  - `pricing_power = 0.0`
  - `replacement_friction = 0.0`
  - `tam_capture = 0.0` (for flat/unreported revenue growth)
- **Actual Observation Data** (from `bottleneck-ranking-v1-observation.json`, bundle hash `247a463640af14dc8f388f9abb5a66f434d09e7ba032734294ff35b4f6613ace`):
  - Total records: 20
  - Distinct score count: **2**
  - Score range: **[3.75, 4.75]**
  - Factor positive counts across all 20 rows:
    - `demand_wave`: **0 / 20**
    - `chokepoint`: **0 / 20**
    - `pricing_power`: **0 / 20**
    - `replacement_friction`: **0 / 20**
    - `tam_capture`: **0 / 20**
    - `valuation_expectations`: 20 / 20
    - `evidence_quality`: 20 / 20
- **Impact**: All 20 candidate rows collapsed into a score of 3.75 or 4.75 (derived solely from default valuation expectations and evidence quality minus small penalties). The final rank order was decided by negligible penalty differences or deterministic tie-breaks, not economic scarcity.

### C. Layout Artifact vs. Ranking Cause
Screenshots of LINE Flex messages display:
1. 股票
2. 長期投資報酬率（近2年年化）
3. 短期投資報酬率（近6個月）
4. 行業別
5. 獲利簡述
6. 公司現在訂單
7. 未來訂單預估

The prominent display of historical returns led observers to suspect returns drove the ranking. However, review of `cloud/src/v213/top20-report.ts` and `scripts/v21_serenity_top20.py` proves returns were **display context only**. Historical returns contributed zero points to `serenity_score`. The actual cause was factor collapse and screener misallocation.

---

## 3. System Operationalization Rubric V1 (100 Points)

The versioned rubric in `config/system-bottleneck-explosion-v1.json` computes transparent, claim-grounded scores across 9 positive dimensions, subject to strict downside adjustments.

### Positive Rubric Weights & Anchors
1. **Dependency Criticality (12 pts)**:
   - 12: Mission-critical architecture chokepoint; removing input halts operation.
   - 8: High-criticality core module input; redesign requires >18 months.
   - 4: Moderate criticality or secondary subsystem.
   - 0: Generic beneficiary, commodity input, or unproven.
2. **Qualified Scarcity & Switching (14 pts)**:
   - 14: Single source or semi-monopoly (<2 effective qualified suppliers); switching >18M.
   - 10: 2-3 qualified suppliers, severe ramp constraint; switching 12-18M.
   - 5: Multiple alternatives exist; switching 6-12M.
   - 0: Readily available effective substitutes; switching <6M; or unproven.
   *(Shortage relieved decreases this score to 0).*
3. **Demand Acceleration (10 pts)**:
   - 10: Multi-year secular acceleration confirmed by customer capex/commitments.
   - 7: Evidenced tier-1 customer demand wave.
   - 3: Moderate sector growth without architectural lock-in.
   - 0: Mature/cyclical demand or unproven.
4. **Supply Constraint (12 pts)**:
   - 12: Severe lead times (>52 weeks), proprietary process/IP, or cleanroom barrier.
   - 8: Substantial expansion lead time (24-52 weeks) with high capital intensity.
   - 4: Moderate constraint (12-24 weeks).
   - 0: Elastic supply response or unproven constraint.
5. **Pricing Power (12 pts)**:
   - 12: Documented contractual price increases, cost-plus indexation, or pricing premium.
   - 8: Contractual price stability, no discounting pressure.
   - 4: Indirect pricing power via product mix shift.
   - 0: Price taker, commodity pricing, high gross margin without pricing mechanism.
6. **Company Capture (12 pts)**:
   - 12: High BOM share capture, strong non-dilutive balance sheet, minimal leakage.
   - 8: Strong capture, disciplined financing, manageable capex.
   - 4: Partial capture; bargaining power held by customer/supplier.
   - 0: Value captured upstream/downstream; unproven capture.
7. **Operating Leverage (10 pts)**:
   - 10: Incremental operating margins >40%; high fixed-cost absorption.
   - 7: Demonstrated operating leverage with volume scaling.
   - 3: Moderate leverage; linear cost structure.
   - 0: Negative leverage, diseconomies of scale, or unproven.
8. **Catalyst & Timing (10 pts)**:
   - 10: Dated 6-18M verified milestone (platform ramp, qualification completion).
   - 7: Dated 18-36M verified milestone with corroborated customer timeline.
   - 3: General roadmap timing without verified operational milestones.
   - 0: Distant (>36M), stale/past, or unproven catalyst.
9. **Order & Commitment Support (8 pts)**:
   - 8: Disclosed firm non-cancellable backlog, take-or-pay, or prepayments.
   - 5: Disclosed order book or design win volume commitments.
   - 2: Disclosed non-binding LOI or qualified pipeline.
   - 0: Vague TAM, undisclosed orders, general issuer guidance, or unproven.

**Total Positive Rubric Maximum = 100 Points.**

### Downside Penalties
- **Financing / Dilution**: `MATERIAL_OVERHANG` (-5.0), `STRUCTURAL_DISQUALIFIER` (-10.0), `DESTROYED` (-100.0 / Disqualification).
- **Unprotected Customer Concentration**: Moderate (-3.0), Severe (>50% single customer unprotected, -6.0).
- **Unexplained Revenue Deterioration**: Organic decline amid demand wave (-6.0 to -10.0).
- **Export / Policy Concentration**: Severe unmitigated export ban risk (-6.0).
- **Valuation Crowding**: Extreme valuation pricing in perfection (-3.0 to -5.0).
- **Missing Risk Disclosure Penalty**: **-5.0 pts**. Missing risk disclosures are **never** treated as zero risk.

---

## 4. Critical Admission Gates & Fail-Closed Logic

Candidates must satisfy all six mandatory pillars to enter the ranked list:
1. **Evidenced Bottleneck Role**: Must be `SINGLE_SOURCE`, `SEMI_MONOPOLY`, `QUALIFICATION_CONSTRAINED`, or `CAPACITY_BOTTLENECK`. `BENEFICIARY` and `UNPROVEN` are unranked.
2. **Qualified Scarcity & Switching**: Scarcity score > 0. Sole-source labels without evidence are rejected.
3. **Structural Demand Acceleration**: Demand score > 0.
4. **Pricing Mechanism or Company Capture**: Pricing power > 0 or Company Capture > 0. High gross margin alone does not qualify.
5. **Dated 6-36M Catalyst**: Catalyst score > 0 with dated operational milestones.
6. **Non-empty Thesis Killers**: Must articulate specific contrary conditions that falsify the thesis.

### Absolute Disqualifiers
- `financing_risk == "DESTROYED"` or `equity_capture_status == "DESTROYED"`: Immediate disqualification (`BROKEN`).
- `lifecycle == "BROKEN"`: Immediate disqualification.
- Unresolved claim conflicts or forged timestamps/identities: Excluded by observation reconciliation.

### Cardinality & Padding Rules
- Admitted candidates: **0 to 20**.
- If fewer than 20 candidates qualify (e.g. 0, 1, or 19), **only** those admitted are ranked.
- **Zero-padding and lexical alphabetical backfill are strictly forbidden.**
- Non-admitted candidates are retained in `low_confidence_watchlist` with explicit disqualification or missing-evidence reasons.

---

## 5. Neutrality & Verification Contracts

- **No Sector Favoritism**: AI, robotics, power, and critical infrastructure are dynamic hypotheses, not permanent allowlists. Metallurgy, optics, chemicals, and industrial inputs are evaluated with identical logic.
- **Global Universe**: Foreign listings (European, Japanese, Taiwanese) are admitted on primary exchange and financial disclosure evidence; absence of US SEC EDGAR filings is not a disqualifier.
- **Mature Mega-Caps**: Neither automatically admitted nor banned; judged strictly on incremental capture, valuation downside, and bottleneck role.
- **Perturbation Invariance**: Historical returns and social/author mentions have exactly 0.0 weight on score and rank.

---

## 6. Next-Slice Integration Architecture

To integrate `bottleneck_ranking.py` into the production LINE service, the following steps are required in subsequent slices:
1. **Production Pipeline Caller**: Update `scripts/v213_build_v21_public_snapshot.py` and `scripts/v213_apply_diversified_operationalization.py` to invoke `bottleneck_ranking.rank_bottleneck_candidates` on qualified candidates.
2. **Sealed Bundle Cardinality**: Update bundle validators (`scripts/build_v213_activation_bundle_v2.py`) to permit dynamic cardinality (0–20 records) without failing an exact-20 assertion when insufficient candidates qualify.
3. **Worker Display**: Update `cloud/src/v213/top20-report.ts` and `top20-presentation.ts` to display bottleneck role, substitution friction, and dated catalysts alongside existing order fields.
4. **Certification**: Standalone module execution does **not** claim live production ranking correction until full bundle activation and edge convergence are verified.
