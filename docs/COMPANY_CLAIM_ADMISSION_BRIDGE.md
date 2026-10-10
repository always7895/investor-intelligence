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
   - Identity values (`independence_group`, `origin_group`, `content_sha256`) must be strings. They are stripped, and a non-string value is ignored instead of being coerced with `str()`. A truthy top-level `origin_group` is used first (even if it is not a string, in which case it is ignored); only otherwise does the legacy `payload.origin_group` fallback apply, and a truthy malformed `payload` still raises instead of being skipped silently.
   - A well-formed observation with no usable key is skipped and no longer counts as its own anonymous family. A non-mapping observation was already skipped.
   - The family count is a metadata-overlap count, not proof of authenticity or independence. For invalid or mixed metadata it can be higher or lower than the earlier coercing behavior: for example, two observations with a numeric `independence_group` of 7 and origins A and B formerly shared an invented `publisher:7` key and counted as 1, and now count as 2. Fixture threshold outcomes can therefore change. The upstream acquisition binding, the source registry (a non-empty string `independence_group`) and the context checks stay mandatory and unchanged.

6. **Domain-Specific Economic Rules:**
   - **Generic OEM Count != Effective Alternatives:** Merely listing nominal competitors does not establish qualified substitutes or relief of switching friction.
   - **Conditional Forecast != Realized Scarcity:** Forward guidance or multi-year capacity targets cannot license realized scarcity.
   - **Group ROIC / Dividend Payout != Pricing Power:** Corporate capital allocation policies (e.g., 30% dividend payout or consolidated ROIC) do not constitute contractual price indexation or scarcity premium.
   - **Business Mix != Share Dilution:** Holding multiple operating subsidiaries or diversified segments is distinct from equity dilution.
   - **Unknown Financing Defaults to STRUCTURAL_DISQUALIFIER:** Unspecified or missing financing risk never defaults to `NONE`.
   - **Cross-Factor Uniqueness:** Each of the four core factors (`dependency`, `scarcity`, `pricing`, `capture`) must be licensed by a **distinct** claim ID. Reusing a single claim across factors is prohibited.

7. **Old Entrypoint Integration & Trust Bypass Elimination:**
   `bottleneck_claim_admission.reconcile_factor_authority` wraps `bridge_reconcile_factors` directly once without shadowing or fallback.
   - When `fixture_mode` is `None`, the wrapper enables fixture mode only if `source_observations` is non-empty, every observation's `canonical_url` host ends in `.example`, and every claim with status exactly `SUPPORTED` has `independent_evidence_families >= 2`; other claim statuses are ignored by this detection check. Otherwise, and for explicit `False`, the bridge requires an owned acquisition context and returns `ADMISSION_DEFER` without one. The bridge itself defaults to `False` and independently validates observation lineages. Auto-detected synthetic results carry the tier `TEST_ONLY`; the tier is descriptive and consumers gate on `core_admitted`, which stays true for a `TEST_ONLY` result when all four factors license (`scripts/company_claim_admission_bridge.py`, tier block before the return), so the tier name is not itself the barrier; the barrier is the wrapper fixture detection (`.example` hosts only, `scripts/bottleneck_claim_admission.py` lines 44-61) and the requirement that a non-fixture call carry an owned acquisition context; a direct bridge call with `fixture_mode=True` is not covered by the wrapper detection.
   - Runtime callers do not forward `acquisition_context`. A non-synthetic owned run remains `UNADMITTED` and `core_admitted=False`; canonical bindings alone confer no live admission. Synthetic owned-run wiring may return `TEST_ONLY_NONRUNTIME`.

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
