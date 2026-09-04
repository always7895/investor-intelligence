# v2.1.3 Serenity Public-Logic Reconstruction and Source Diversity

Investor Intelligence does not claim access to, or reproduction of, Serenity's private process, official formula or official score. Historical machine keys such as `serenity_score` remain only for compatibility and are displayed as **System operationalization** fields.

The analysis model separates a dated identifiable Serenity public-source view from architecture/demand, evidence-bound dependency graph, bottleneck-versus-expansion state, company capture, valuation expectations, thesis killers, lifecycle/timing, the legacy system overlay, model inference and the user's long-term preference overlay.

Claims advance only through the evidence state machine: `UNPROVEN`, `EVIDENCE_FORMING`, `COMMERCIAL_VALIDATION`, `INSTITUTIONAL_VALIDATION`, `THESIS_IMPAIRED`, `THESIS_BROKEN`. A keyword, sector label, revenue growth, gross margin, beta, short interest, named customer or popular theme cannot establish a chokepoint by itself.

Source count is not source independence. Syndicated copies, the same registrable domain, the same corporate source family, and rewrites of one press release count once. Social posts prove the author's statement, not the underlying company fact. A direct regulator or issuer disclosure can establish its narrow disclosed fact; broader dependency, scarcity, capture or future-order inference requires an independent corroborating family.

The existing yfinance adjusted-close pipeline remains the deterministic return calculation source for historical compatibility. Yahoo/yfinance is therefore a **calculation provider**, not sufficient thesis evidence. Each refresh independently checks the market path through Stooq, Nasdaq historical data, optional Alpha Vantage adjusted data, and official FRED macro context. Conflicting values are retained as `CONFLICT_REVIEW`; they are never averaged away to manufacture apparent precision.

Before report promotion, the portfolio must have at least three independent source families and domains, at least 75% non-Yahoo market corroboration, and no source family above 70% of counted independent units. High-confidence model inference additionally requires a primary/official source, two independent families, non-Yahoo corroboration and no unresolved conflict. Public observations may be cached for at most 72 hours; the system does not silently fall back to Yahoo-only after the cache expires.

Implementation:

- `config/v213-serenity-public-logic-policy.json`
- `scripts/v213_source_independence_gate.py`
- `data/cache/v213_source_independence_latest.json`
- `data/cache/v213_source_observation_cache.json`
- `scripts/v213_local_llm_gateway.py`

The local model receives the sidecar's source families, domains, primary/official coverage, market corroboration, conflicts, missing evidence and public-logic states. When the gate does not support high confidence, the model is required to answer with `LIMITED`, `UNPROVEN` or `INSUFFICIENT_EVIDENCE` rather than fill missing evidence with plausible prose.
