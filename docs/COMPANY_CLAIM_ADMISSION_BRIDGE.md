# Typed Company Claim Admission Bridge

**Lane:** `TYPED_COMPANY_CLAIM_ADMISSION_V1` / `CANONICAL_COMPANY_ACQUISITION_BINDING_V1`

**Scripts:**
- `scripts/company_claim_admission_bridge.py`
- `scripts/bottleneck_claim_admission.py`
- `scripts/source_acquisition.py`
- `scripts/source_observation.py`

**Test Suites:**
- `tests/test_company_claim_admission_bridge.py`
- `tests/test_company_claim_admission_bridge_security.py`
- `tests/test_company_acquisition_bindings.py`
- `tests/test_top20_bottleneck_takeover.py`

---

## 1. Overview & Purpose

The `company_claim_admission_bridge.py` module establishes a minimal typed bridge connecting trusted source acquisition and canonical research claims to factor-specific bottleneck company admission.

It enforces that candidate text matches (e.g. from `company_evidence_candidates.py`) and generic source observations are **not** confused with authoritative source acquisition or factor-specific economic licensing. Corroborated `SUPPORTED` status from observation reconciliation alone cannot license all four core factors without exact fact bindings, authentic acquisition context, and economic validation.

---

## 2. Core Architectural Principles & Trust Boundaries

1. **Candidate Text Verification != Company Admission:**
   Matching a verbatim passage in a PDF/HTML text proves only the existence of the anchor. It does **not** authenticate the publisher, verify source rights, establish semantic entailment, or license any factor. Output admission tier for unreviewed candidate corpora is strictly `UNADMITTED` (admitted count = 0).

2. **Acquisition Authority Gates & Forgery Rejection:**
   Trust is anchored exclusively in validated `AcquisitionRun` instances or authoritative `Registry` + verified runtime `health_states`.
   - Caller-injected registries, forged health dictionaries (`health_states: {"official": "HEALTHY"}`), or caller-asserted `status: "ADMITTED"` flags are rejected fail-closed.
   - Public Python callers passing generic Mappings or caller-owned typed claims without authentic acquisition-context ownership cannot receive factor licensing or core admission. Missing trusted acquisition remains strictly `ADMISSION_DEFER`.
   - Fabricating an acquisition context dictionary or mock object is strictly rejected.

3. **HTTPS ONLY and URL Security Invariants:**
   All canonical source URLs must use `https://` strictly.
   - Rejects `http://` scheme fail-closed.
   - Rejects URLs containing credentials/userinfo (`user:pass@host`), never sanitizing and promoting.
   - Rejects query parameters bearing authentication tokens or secrets (`token`, `apiKey`, `secret`, `auth`, `password`).
   - Rejects RFC 1918 private IPs, cloud metadata endpoints (`169.254.169.254`), loopback addresses (`127.0.0.1`, `::1`), IPv6-mapped IPv4 addresses (`::ffff:127.0.0.1`), trailing dot hostnames, and internal TLDs (`.local`, `.internal`, `.lan`).
   - Error messages are strictly static codes (`INVALID_SOURCE_URL`, `PRIVATE_PAYLOAD_DETECTED`); input paths, raw URLs, and sensitive payloads are never echoed in exceptions.

4. **Exact Fact Binding to Canonical Admitted Observations:**
   Factor licensing requires that every claimed factor is backed by verified canonical observations in `source_observations` matching:
   - `subject`: must match candidate ticker / legal entity.
   - `product_or_spec`: must be specific to the bottleneck layer; generic or unqualified commodities are rejected.
   - `period` and `period_type`: conditional forecasts, long-term targets, and forward guidance cannot license realized historical factors.
   - `metric` and `claim_type`: must strictly comply with `CLAIM_AUTHORITY_RULES` for the respective factor.
   - `evidence_role`: must be authoritative for the factor (e.g. `financial_statements` for capture/pricing; macro reporting cannot license company equity capture).
   - `unit` and `value`: values must be finite scalars (`int`, `float`, bounded `str`). Boolean numeric coercion (`True`/`False` as numbers) and non-finite values (`NaN`, `Infinity`) are rejected.

5. **Lineage Deduplication & Connected Components Invariants:**
   Multiple chapters, sections, or filings from the same issuer annual report family (such as 4 chapters of an annual report) share origin/lineage/hash keys and transitively collapse into **one** evidence family.
   - Each factor claim requires at least **two** independent evidence families computed via connected components.
   - Caller-invented duplicate lineages from the same underlying issuer document fail closed.

6. **Domain-Specific Economic Rules:**
   - **Generic OEM Count != Effective Alternatives:** Merely listing nominal competitors does not establish qualified substitutes or relief of switching friction.
   - **Conditional Forecast != Realized Scarcity:** Forward guidance or multi-year capacity targets cannot license realized scarcity.
   - **Group ROIC / Dividend Payout != Pricing Power:** Corporate capital allocation policies (e.g., 30% dividend payout or consolidated ROIC) do not constitute contractual price indexation or scarcity premium.
   - **Business Mix != Share Dilution:** Holding multiple operating subsidiaries or diversified segments is distinct from equity dilution.
   - **Unknown Financing Defaults to STRUCTURAL_DISQUALIFIER:** Unspecified or missing financing risk never defaults to `NONE`.
   - **Cross-Factor Uniqueness:** Each of the four core factors (`dependency`, `scarcity`, `pricing`, `capture`) must be licensed by a **distinct** claim ID. Reusing a single claim across factors is prohibited.

7. **Old Entrypoint Integration & Trust Bypass Elimination:**
   `bottleneck_claim_admission.reconcile_factor_authority` wraps `bridge_reconcile_factors` directly once without shadowing or fallback.
   - `fixture_mode` defaults to `False`; auto-trust bypass is strictly eliminated.
   - Synthetic fixture evaluation is only enabled for authoritative test fixture suites using reserved `.example` domains and corroborated research claims.

8. **Canonical Company Acquisition Factor Bindings (`CANONICAL_COMPANY_ACQUISITION_BINDING_V1`):**
   The architecture blocker is resolved by extending `AcquisitionRun` with process-local, factory-created `CompanyFactorBinding` tuples.
   - Real factory origin: Bindings are generated exclusively inside `source_acquisition.acquire_runtime_sources` from parsed, normalized observation records with reviewed source capability.
   - Typed binding fields: `claim_id`, `subject`, `entity`, `security`, `factor`, `metric`, `product_or_spec`, `region`, `unit`, `period`, `period_type`, `evidence_role`, clocks (`source_clock`, `event_clock`, `retrieval_clock`), `canonical_observation_ids`, `lineage_ids`, `independent_lineage_count`, and `is_test_binding`.
   - Lineage deduplication: `independent_lineage_count` is derived directly from observation connected components (>= 2 required for factor licensing).
   - All referenced observation IDs must exist in the SAME owned `AcquisitionRun`. Cross-run replay, dangling IDs, cross-company subject mismatch, and unreviewed source capabilities fail closed.
   - Unrelated macro/ECB observation runs remain fully compatible and produce empty company bindings without overreach.
   - TEST_ONLY canonical transport paths evaluate to `TEST_ONLY_NONRUNTIME` to prove factory-to-admission-caller wiring.
   - Live production admission remains strictly 0; fixture evaluation confers zero production qualification.

---

## 3. Interfaces & Integration

```python
from company_claim_admission_bridge import (
    validate_typed_claim,
    compute_independent_lineages,
    bridge_reconcile_factors,
    BridgeValidationError,
)

# Fact validation
validated_claim = validate_typed_claim(raw_claim, now=clock, allowed_subject="TICKER")

# Lineage deduplication
family_count = compute_independent_lineages(observations)

# Factor authority reconciliation
result = bridge_reconcile_factors(
    candidate,
    reconciled_claims,
    ticker="TICKER",
    now=clock,
    fixture_mode=False,
    acquisition_context=acquisition_run,
)
```
