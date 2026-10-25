# System Bottleneck Explosion Ranking V1: Policy, Admission, Safety Review 2 & Root-Cause Specification

> REVIEW 2 RESEARCH POLICY & TRUST BOUNDARY SLICE / 研究政策審查第 2 輪修正：
> 本文件記錄 System Bottleneck Explosion Ranking v1 之研究政策、准入門檻、舊榜單根因診斷，以及第 2 輪安全審查（Review 2 Trust Boundary & Fail-Closed Gates）之完整修正規格。
> 此模組為明確之 Opt-in 離線研究架構（`OFFLINE_NON_PUBLICATION`），非正式生產發布。
> 線上發布資格明確標示 `DEFER`，公開 CLI/raw JSON 輸入一律維持 `UNRANKED_INSUFFICIENT_EVIDENCE`（`admitted_count=0`, `ranked_count=0`, `rank=null`, `score_qualified=null`）。
> 下一階段任務為獨立公開標的池與數據收集器研究（independent public universe/source collector research），嚴禁在缺乏真實收集器能力前部署虛假 ADMITTED。以 state/STATUS.md 與不可變測試 receipts 為準。
> 
> TAKEOVER V1 UPDATE（2026-09-15）：
> 實裝嚴格因子對主張權限綁定（Factor-to-claim authority / scripts/bottleneck_claim_admission.py）；通用營業收入申報事實不能授權結構性因子得分；核心依賴、稀缺、定價權與股權捕捉四要件未齊備者一律 fail-closed 維持 UNRANKED_INSUFFICIENT_EVIDENCE。詳情見 [TOP20_BOTTLENECK_TAKEOVER_V1](TOP20_BOTTLENECK_TAKEOVER_V1.md)。

---

## 1. Executive Summary & Attribution Boundary

- **Research Lane Selected**: `SYSTEM_RESEARCH_CANDIDATES` under `skills/serenity-public-research/SKILL.md`.
- **Methodology Lens**: Public-logic high-fidelity reconstruction (`skills/serenity-bottleneck.md`, `references/RESEARCH_METHOD.md`, `references/CROSS_VALIDATION.md`).
- **Attribution Boundary**: Neither Serenity (`@aleabitoreddit`) nor Leopold Aschenbrenner has authored, reviewed, or endorsed this scoring rubric. Public posts are attributed source views and hypothesis generators, not company facts or portfolio recommendations. Leopold Aschenbrenner infrastructure scenarios remain `CONTEXT_ONLY` and contribute exactly 0.0 points to scoring.
- **Slice Scope**: Bounded engineering research-policy slice (`BOTTLENECK_COMPLETE_FAIL_CLOSED_TRUST_REVISION_2`). Existing production weights, R75 contracts, and Worker deployment remain intact and untouched.

---

## 2. Production Ranking Collapse: Detailed Empirical Diagnosis

An empirical audit of the existing published bundle (`247a463640af14dc8f388f9abb5a66f434d09e7ba032734294ff35b4f6613ace`) and code paths explains why non-chokepoint companies (ACGL, AFRM, BBY, CDE, FIS, HIG, HST) occupied top ranking seats:

### A. Generic Screener Seed Selection (Pre-Evidence Selection)
- **Code Reference**: `config/v21-serenity-policy.json` (lines 12–25).
- **Mechanism**: The candidate universe was seeded from generic Yahoo Finance market screeners:
  - `undervalued_growth_stocks` (weight 5)
  - `most_actives` (weight 2)
  - `day_gainers` (weight 1)
- **Consequence**: Companies such as ACGL (property & casualty insurance), AFRM (fintech buy-now-pay-later), BBY (electronics brick-and-mortar retail), CDE (silver mining), FIS (bank core processing), and HIG (insurance) entered the candidate pool solely based on market capitalization, trading volume, or recent short-term price momentum, completely lacking supply-chain bottleneck dependency.

### B. Core Factor Collapse to Zero Across All Candidates
- **Code Reference**: `scripts/v213_apply_diversified_operationalization.py` (lines 314–329) and `scripts/v21_serenity_top20.py` (lines 955, 964).
- **Observation Evidence** (`bottleneck-ranking-v1-observation.json`):
  - Candidates evaluated: 20
  - Distinct score values: **2** (all 20 candidates scored either 3.75 or 4.75)
  - Positive score distribution across all 20 rows:
    - `demand_wave`: **0 / 20**
    - `chokepoint`: **0 / 20**
    - `pricing_power`: **0 / 20**
    - `replacement_friction`: **0 / 20**
    - `tam_capture`: **0 / 20**
    - `valuation_expectations`: 20 / 20 (default baseline)
    - `evidence_quality`: 20 / 20 (default baseline)
- **Identity Tie Dangers**: Because all 5 structural factors collapsed to 0, every candidate's raw score collapsed to identical baseline numbers. Final ranking order degraded into trivial rounding differences from minor penalty tags or arbitrary alphabetical tie-breaks.

### C. Layout Artifact vs. Actual Weight Proof
- In the LINE Flex UI (`cloud/src/v213/top20-report.ts`), historical returns (2-year annualized CAGR and 6-month price return) are prominently displayed.
- **Audit Finding**: Historical returns were **layout context only**. In `scripts/v21_serenity_top20.py`, historical returns contributed exactly 0.0 points to `serenity_score`.
- Historical returns did not mechanically cause the ranking; rather, screener mis-allocation combined with total factor collapse caused the ranking collapse. In this new v1 engine, historical returns continue to have **0.0 score influence** and **0.0 admission weight**.

---

## 3. Review 2 Trust Boundary & Fail-Closed Resolution

Astra Safety Review rejected the Review 1 implementation despite 23+18 test passes because Review 1 contained several critical trust boundary violations. Review 2 fully resolves all confirmed blockers:

1. **Removal of Test Fixtures & Auto-Fallback from Production Code**:
   - `scripts/bottleneck_ranking.py` completely eliminates `import test_research_v2_claims` and `FIXTURE_REGISTRY`. Product code contains zero test module imports and zero fixture globals.
   - Candidate-owned `candidate_data['registry']` is strictly ignored; registry can only be provided via explicit caller dependency parameter, `acquisition_run.registry`, or authoritative `load_registry()`.

2. **Caller-Owned Runtime Health States (No Health Fabrication)**:
   - Candidate-owned `candidate_data['health_states']` is strictly ignored.
   - When no runtime health states or acquisition run is provided, `health_states` remains `None`, causing `reconcile_research_claims` to treat all observations as `DEGRADED`.
   - No silent defaulting of sources to `HEALTHY`.

3. **No Silent Parser or Jurisdiction Metadata Defaulting**:
   - Removed all `setdefault` operations for `parser_id`, `parser_version`, `jurisdiction`, and `language`.
   - Raw observations missing canonical parser or jurisdiction metadata fail closed via `normalize_observation`.

4. **Fail-Closed Clock Validation (No Clock Laundering)**:
   - `parse_clock` requires a non-empty, timezone-aware ISO-8601 string.
   - Missing or malformed timestamps raise `BottleneckRankingError` and never default to `datetime.now(timezone.utc)`.
   - Candidates with missing or invalid clocks fail admission (`missing_or_invalid_clock` risk flag, `UNRANKED_INSUFFICIENT_EVIDENCE`).

5. **Macro-Only Capability Boundary**:
   - Process-local `AcquisitionRun` with macro indicators (e.g. current ECB macro) cannot qualify company claims (`issuer_financial_statement` or `issuer_guidance_or_contract`).
   - Company candidates without corroborated company-level claims fail closed.

6. **CLI Untrusted Payload Defense**:
   - Until an authorized company-level collector is integrated, public CLI execution on raw candidate JSON always fails closed:
     `admitted_count = 0`, `ranked_count = 0`, `ranked_candidates = []`, all candidates in `low_confidence_watchlist` marked `UNRANKED_INSUFFICIENT_EVIDENCE`, `rank = null`, `score_qualified = null`.
   - Typed internal unit boundary injection (`registry`, `health_states`, `acquisition_run`) is reserved exclusively for typed unit tests.

---

## 4. System Operationalization Rubric V1 (100 Points)

The rubric is a versioned engineering operationalization proposal, **never** an official Serenity score or explosion probability.

### Positive Scoring Dimensions (Max 100 Points)
| Dimension | Max Pts | Core Verification Requirement |
| :--- | :---: | :--- |
| **Dependency Criticality** | 12 | Removing the input halts the customer system; irreplaceable architecture layer. Customer relationship alone awards 0. |
| **Qualified Scarcity & Switching** | 14 | Single-source or semi-monopoly (<2 effective qualified suppliers); customer switching time >12-18 months. Shortage relieved decreases score to 0. |
| **Demand Acceleration** | 10 | Multi-year structural acceleration verified by customer capex and physical deployment commitments. |
| **Supply Constraint** | 12 | Physical tooling lead times (>52 weeks), cleanroom barriers, or proprietary process know-how. Capacity expansion announcement without bottleneck awards 0. |
| **Pricing Power** | 12 | Disclosed contractual pricing power, cost-plus pass-through, or scarcity pricing. High gross margin alone awards 0. |
| **Company Value Capture** | 12 | Dominant BOM share capture, non-dilutive equity structure, disciplined capex. |
| **Operating Leverage** | 10 | Fixed-cost absorption resulting in incremental operating margins >40%. |
| **Catalyst & Timing (6-36M)** | 10 | Verified dated operational milestones (6-18M = 10 pts, 18-36M = 7 pts). |
| **Orders & Commitments** | 8 | Firm non-cancellable backlog, take-or-pay agreements, or prepayments (8 pts); design wins (2-5 pts). Vague TAM awards 0. |

### Downside Penalties & Disqualifiers
- **Financing / Dilution**: `MATERIAL_OVERHANG` (-5.0), `STRUCTURAL_DISQUALIFIER` (-10.0), `DESTROYED` (-100.0 / Disqualification).
- **Unprotected Customer Concentration**: Moderate (-3.0), Severe (-6.0).
- **Unexplained Revenue Deterioration**: Organic decline during industry expansion (-6.0 to -10.0).
- **Export / Geopolitical Concentration**: Severe unmitigated export risk (-6.0).
- **Valuation Crowding**: Extreme valuation expectations (-2.0 to -5.0).
- **Missing Risk Disclosure Penalty**: **-5.0 pts**. Omitted risk disclosures are penalized to ensure missing disclosure is never treated as zero risk.
- **Unresolved Claim Conflicts**: **-15.0 pts** and admission disqualification.
- **Missing or Invalid Clock**: **-20.0 pts** and admission disqualification.

---

## 5. Critical Admission Gates & Output Provenance

To prevent unproven candidates from entering the ranked top 20, candidates must pass all mandatory gates:
1. Verified company claims supported by authoritative sources via `reconcile_research_claims`.
2. Role must be `SINGLE_SOURCE`, `SEMI_MONOPOLY`, `QUALIFICATION_CONSTRAINED`, or `CAPACITY_BOTTLENECK`.
3. Scarcity score > 0 (corroborated scarcity or switching latency >= 12M).
4. Demand acceleration score > 0.
5. Pricing power > 0 OR Company capture > 0.
6. Dated 6–36M catalyst present.
7. Non-empty thesis killers / falsifiers disclosed.
8. Financing state != `DESTROYED`.
9. Thesis lifecycle != `BROKEN`.
10. Zero unresolved claim conflicts.
11. Valid, non-laundered evaluation clock.

### Provenance Tracking
Every output record returns structured provenance for each dimension:
- `provenance`: `"SOURCE_DERIVED_FACT"` (when backed by admitted observation), `"MODEL_INFERENCE"`, or `"UNKNOWN"`.
- `contribution_breakdown`: exact points awarded out of max points.
- `rank_rationale`: transparent summary of role, raw score, penalties, final score, status, and lifecycle.
- `historical_returns_context`: clearly marked with `influence_on_score: 0.0` and `usage: "DISPLAY_AND_RISK_CONTEXT_ONLY"`.
- `score_qualified`: `True` for admitted candidates, `null` for unranked.
- `candidate_assessment_mode`: `"RANKING_QUALIFIED"` for admitted, `"CANDIDATE_ONLY"` for unranked.

### Cardinality Rules
- Ranked list contains **at most 20** admitted candidates.
- If fewer than 20 qualify (0, 1, 19), exactly that number is ranked.
- **No zero-score padding and no lexical alphabetical backfill.**
- Candidates failing admission are preserved in `low_confidence_watchlist` with `rank=null`.
- Admitted candidates beyond 20 are placed in `admitted_overflow` with `rank=null`.

---

## 6. Migration and Next Task Roadmap

This slice hardens the trust boundary, removes all auto-fallback mechanisms, and enforces fail-closed gates across all lanes.
1. **Current Status**: Standalone engine verified; live production qualification explicitly **DEFERRED**.
2. **Next Task**: Independent public universe / source collector research (`skills/serenity-public-research/SKILL.md`). Constructing an authoritative public company collector with SEC/official issuer adapter integration before any live ranking admission can be enabled.
