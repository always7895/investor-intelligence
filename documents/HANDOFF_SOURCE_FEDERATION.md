# HANDOFF: INVESTOR_INTELLIGENCE_SOURCE_FEDERATION_FULL_AUTOPILOT

## META
- PROJECT: INVESTOR_INTELLIGENCE_SOURCE_FEDERATION_FULL_AUTOPILOT
- MODE: AUTONOMOUS=true, CONTINUOUS_EXECUTION=true, HUMAN_CONFIRMATION_REQUIRED=false, FAIL_CLOSED=true, SINGLE_WRITER=true
- MASTER: Astra (Master)
- DECIDER: Mapika-decider-2b-v9 (ALIAS_ONLY identity resolved 2026-09-19)
- EXECUTOR_WRITER: Qwen3.8-27B-EXL3-5.5bpw-v2 (exact, tabby-local localhost:5000)
- ORCHESTRATOR: Pi + official Herdr Skill
- WORKSPACE: D:\Investor-Intelligence-LINE-Pi\_workspace\source
- BRANCH: fix/options-provenance-audit
- HANDOFF_DATE: 2026-09-19
- CURRENT_TASK: TASK0-3L_SOURCE_FEDERATION_FOUNDATION (IN PROGRESS)

## GOAL
Upgrade Investor Intelligence from a single/few-source evidence system to a multi-institution Source Federation. Yahoo Finance is only one source; no single provider (Yahoo/Stooq/Nasdaq) is the global evidence backbone. The system must auto-integrate official regulators, issuer IR/filings, exchanges, options/futures institutions, government statistics, central banks, international organizations, global markets, public institutional research, reputable financial news, and public market-data aggregators — while preserving provenance, lineage, freshness, claim-specific evidence, fail-closed, publication gates, privacy, and ranking/scoring integrity.

## GOVERNANCE (3-LAYER)
- Astra (Master): sole Master Controller (architecture, task contracts, final acceptance). Astra-class models only for the `astra-master` role; no non-master Astra dispatch. Production authorization is OPERATOR-only (explicit current-session operator authorization); Master technical approval alone is insufficient.
- Mapika-decider-2b-v9: bounded decision, evidence sufficiency, source routing, diff review, risk classification, escalation routing. Does NOT write source code or modify Production. Identity item resolved ALIAS_ONLY (actual v9 weights/paths verified; older logical model ID reported as alias).
- Qwen3.8-27B-EXL3-5.5bpw-v2 (exact): sole Writer (discovery, adapter implementation, fixtures, tests, refactor within approved scope, gates, git commit/push, deploy only after Master gate).
- Pi + official Herdr Skill: orchestration, tool execution, evidence collection, calls Mapika, calls the Master, state machine progression; one master, one writer; cloud scouts default zero, max two cheap only for unresolved work.
- ANTI_LOOP: same hypothesis without new evidence max 2 restatements. 3 consecutive read-only ops without decision-grade evidence → STOP → Mapika DECIDE. Mapika LOW/UNKNOWN → auto-send Master ruling → continue (no human wait).
- Master ops: decider first → Astra master ruling. On timeout → check status first (no duplicate resend).

## GLOBAL AUTONOMY LAW
No provider failure (timeout/403/404/429/JS challenge/schema change/API key/premium/region block/robots-ToS/auth/temp outage) may stop the project. Classify each provider: AVAILABLE_PUBLIC, AVAILABLE_PUBLIC_LIMITED, AVAILABLE_KEYLESS, OPTIONAL_FREE_KEY, AUTH_REQUIRED, PREMIUM_ONLY, JS_ONLY, RATE_LIMITED, REGION_BLOCKED, LEGAL_RESTRICTED, TEMP_UNAVAILABLE, SCHEMA_BROKEN, UNSUPPORTED. AVAILABLE_* → build/use adapter. OPTIONAL_FREE_KEY → no auto account/key entry → OPTIONAL_DEFERRED → continue. AUTH_REQUIRED/PREMIUM_ONLY → no purchase/login/bypass → record capability → continue. JS_ONLY → bounded adapter only if repo has legal public browser/web adapter, else DEFER. RATE_LIMITED → backoff/cache → no evidence gate reduction. REGION_BLOCKED/TEMP_UNAVAILABLE → quarantine → pipeline continues. Single source failure NEVER = PROJECT_STOP. Only repository integrity/security/secret leak/corrupt provenance contract = HARD STOP.

## PROGRESS: TASK0-3L_SOURCE_FEDERATION_FOUNDATION

### Deliverables (13)
1. repository/source inventory — DONE
2. Mapika-v9 actual pin verification — RESOLVED ALIAS_ONLY (2026-09-19: startup loads D:/Models/Mapika-decider-2b-v9, load_ms2124 matches live health2124.2; API id decider-v8 is ALIAS_ONLY, Mapika .9693; no migration/schema-debug needed)
3. authoritative Source Registry — EXISTS (158 sources in config/sources/; see below)
4. mandatory institution coverage matrix — IMPLEMENTED as derived nine-lane projection: `coverage_lanes(registry, policy)` over `lane_semantics` (current registry metadata only; presence is NOT proof of availability/publication). The previously advertised `config/source-federation/source-coverage-matrix.json` path remains NOT_PRESENT (origin UNKNOWN); reproducible inventory: `python scripts/source_registry.py coverage --lanes` (ledger + lanes) and `coverage` (legacy ledger-only output preserved).
5. claim taxonomy — EXISTING 10 live `claim_families` (unchanged); the 22-class list remains an unimplemented requirement. Semantic core adds per-family `claim_family_semantics` descriptors (evidence-role/authority-class mappings derived from current registry metadata; no manual source-id lists; all numeric minima/required_fields unchanged).
6. origin/transport lineage schema — IMPLEMENTED (named contract): explicit `data_origin_lineage` (publisher identity resolving to a registered identity/group, original disclosure/event id, content hash) separate from `transport_lineage` (fetch source/path only, never counted). Mirrors/copies of one origin or identical content cannot increase the independent lineage count; same publisher multiple URLs = one origin; unknown/contradictory origins rejected (no source_id fallback fabricating independence).
7. source capability probe framework — IMPLEMENTED (exact 8 states): `classify_capability(source, *, declared_access, observed_health)` → PUBLIC, PUBLIC_LIMITED, OPTIONAL_KEY, AUTH_REQUIRED, PREMIUM_ONLY, RATE_LIMITED, TEMP_UNAVAILABLE, UNSUPPORTED. Declared access and observed health are separate strict inputs; `free_access_required` is not auth evidence; trust tier is not availability; budgets are not 429s; actual 429 → RATE_LIMITED; transport failure → TEMP_UNAVAILABLE; forbidden/payment never downgrade to PUBLIC; malformed states fail closed; OPTIONAL_KEY metadata never reads keys.
8. source router skeleton — REUSED + EXTENDED in place: `route_claim(registry, claim_kind, policy, *, runtime_only=True, federation_policy)` reuses `select_sources` + `TRUST_RANK` with deterministic source-id tiebreak; all 10 claim kinds yield candidate_sources/authority_order/freshness_requirement (stricter applicable retrieval TTL bound; retrieval freshness vs source observation clock distinguished)/minimum_lineages/fallback_chain (existing required_live_sources family ids). Unknown claim fails closed. Catalog inspection (`runtime_only=False`) lists disabled providers but does not qualify them. Candidate count is never a score/rank boost.
9. deterministic tests — EXTENDED: `tests/test_source_registry_semantics.py` (34 tests: exact 8 states + malformed, all-10 route envelopes, nine lanes with explicit missing clearing, mirrors=1 origin, official+exchange=2, unavailable sources do not block healthy lane, unsupported/stale/future/wrong-subject/missing-lineage/bad-shape/unknown-origin fail closed, registration alone never qualifies, material conflict not rescued by counts, ranking/admission stability, round-1 + round-2 counterexample regressions, centralized minima validation table, actual CLI caller fixtures) + qualification `qualify_claim_evidence` (validated `ParsedBatch` reused unchanged; only fully valid origins counted; `publication_eligible` always False) + `tests/test_source_claim_coverage_gate.py` descriptor regressions.
10. Mapika review — ACCEPT_SCOPED .8613 (2026-09-19; bounded self-review recorded as NOT independent certification)
11. full gates — PASS (full Python 1569 tests 357.336s OK skip 3; Worker 869 PASS 1 skip; typecheck/compile/PS5.1/7; 4 gates + cached diffcheck)
12. atomic commit + push — DONE (this change; SHA in git log)
13. auto-continue into TASK0-3M — PENDING (next Mapika contract; next lane: policy-descriptor referential consistency)

### SEC adapter binding contract V1 — ACCEPTED scoped (2026-09-19)
- Acceptance: Mapika .8658 under LOAD_GUARD_STRICT=true (resident writer reuse LOAD .9694; activation receipt `audit-runtime/sec-binding-contract-v1/load-guard-activation.json`). Full Python 1594/359.927s OK skip 3; Worker 869/1 skip; typecheck/compile/PS5.1/7/4 gates; focused 92/92. Limitations: process-local receipt integrity (not cryptographic durable proof); USD monetary only; real SEC planned/disabled with no endpoint admission; not a full product release.
Read-only mapping (base `37a76b6`) followed by the bounded implementation below.
- `adapters/base.py`: frozen `FetchReceipt(source_id, canonical_url, retrieved_at, http_status, content_sha256, transport_metadata)` + mint/validate helpers. Minted ONLY by the existing fetch owner from the actual response status + raw body bytes at the response-capture seam; no public from-dict auto-attestation, no default 200; direct construction, string/bool status and deep mutation are invalid (in-process integrity marker; not cryptographic proof; no secrets).
- `fetch_public_source_observations.py`: additive `ReceiptMintingTransport` (wraps any transport, mints per successful response) + `receipt_for_observation` (binds row to receipt by source pair + exact body hash; missing receipt fails closed). `fetch_bytes` bytes API, `collect` outputs, ENDPOINTS/DEFAULT_SOURCES/ACQUISITION_ONLY_ENDPOINTS and all network admission unchanged; NO SEC admission added — the contract is exercised offline through the injected-response seam.
- `sec_edgar.py`: `bind_sec_claim(raw_content, fetch_receipt, registry, claim_kind, expected_cik, expected_period?, resolved_symbol_alias?)` — receipt-gated strict binding: strict 10-digit CIK (no permissive digit stripping), receipt URL CIK match, canonical entity/identifier = CIK (name descriptive only), USD-only monetary projection (raw unit/taxonomy/tag always retained; shares/other units stay valid raw parses but fail monetary qualification — documented limit, no taxonomy expansion), optional symbol only from an explicit resolved {cik, symbol} alias (absent omitted, mismatched rejected), jurisdiction from the registered US metadata only, four separate clocks (source_event_time/filing_time, fact_period, receipt retrieved_at, evidence_as_of) with explicit date-precision earliest/latest bounds (UTC day start / min(day end, verified retrieval)) and `evidence_as_of` labelled as the verified earliest bound — never a pretended midnight instant, never retrieval substitution; event day after retrieval day rejected.
- `source_registry.py`: qualifier SEC guard — SEC-bound observations require a valid typed `SecClaimBinding` (minted receipt + binding integrity proof: raw content hash, CIK/period vs expected subject, projected-record digest re-verified by deterministic re-projection from the raw batch) even if the caller supplies http_status=200; generic providers unchanged; the real registry's SEC planned/disabled entry remains non-qualifying (positive fixtures clone it enabled in-test only). Global TTLs/minima unchanged.
- Catalog: single existing entry `us_sec_edgar` `adapter.id` → `sec_edgar` (status `planned`, runtime flags and all other fields byte/value unchanged); unknown adapter fails, no fallback; no new source IDs.
- Tests: `tests/test_sec_adapter_binding.py` (20: receipt direct-construction/deep-mutation/string-bool fakes, byte-hash/URL tamper, happy projection, mandatory period + quarter mismatch, explicit alias, USD-only/shares fail-closed, four clocks + date-precision bounds, future/stale clocks, strict CIK, real-registry-disabled non-qualifying, enabled test clone qualifies, caller-200-without-receipt cannot bypass, projected-record tamper digest, generic scope enforcement, no ENDPOINTS expansion, offline minting seam). Generic semantics fixtures moved from canonical `us_sec_edgar` to existing non-SEC `jp_fsa_edinet` (Mapika-gated root cause: the guard now correctly rejects the old fixture — no guard bypass). All outputs `publication_eligible: False`; no admission/scoring changes.

### SOURCE INVENTORY (DONE)
- Registry files: 7 (config/sources/*.json)
- Total registered sources: 158
- Adapter files: 14 (scripts/adapters/*.py)
- Authority class distribution:
  - securities_regulator: 27
  - central_bank: 26
  - national_statistics_office: 24
  - regulated_exchange: 23
  - international_organization: 16
  - government_open_data: 10
  - public_sector_industry_body: 8
  - reputable_financial_media: 7
  - academic_repository: 4
  - patent_or_ip_office: 3
  - public_service_media: 3
  - standards_body: 3
  - reputable_newswire: 2
  - finance_ministry_or_treasury: 1
  - court_or_legal_registry: 1
- Trust tier: T1_PRIMARY_OFFICIAL: 132, T2_INSTITUTIONAL_CORROBORATION: 13, T3_REPUTABLE_SECONDARY_LEAD: 13
- Existing adapters (14): base, company_public_document, ecb_fx_reference, ecb_sdmx, gleif, issuer_directory, nasdaq_symbol_directory, official_rss, sdmx_csv, sec_edgar, staged_public, taifex_options_eod, taiwan_equities, world_bank
- Source entry schema: source_id, display_name, authority_class, trust_tier, evidence_roles, jurisdictions, languages, canonical_urls, independence_group, admission_status, adapter{id,status}, access{free_access_required,payment_required,terms_review_status}, runtime{enabled,per_host_concurrency,minimum_request_interval_seconds,maximum_retries,freshness_seconds}, provenance{required,correction_tracking}, priority, notes
- Catalog policy (config/authoritative-source-catalog.json): no_fixed_source_count_limit, automatic_activation, free_only, public_data_only, paywall_bypass_forbidden, runtime_enable_requires_all_gates, unknown_fields_fail_closed
- Registry policy (config/sources/registry-policy.json): unbounded source count, trust tiers T1-T4, authority classes list

### COVERAGE MATRIX (NOT_PRESENT at advertised path; plan retained below; origin of earlier DONE claim UNKNOWN)
File: config/source-federation/source-coverage-matrix.json
- 17 mandatory lanes; 12 COVERED, 4 PARTIAL, 1 MISSING
- COVERED (12): B_US_REGULATORY, E_US_MACRO, F_INTL_MACRO, G_JAPAN, H_TAIWAN, I_HK_CHINA, J_SOUTH_KOREA, K_EUROPE_UK, L_CANADA, M_AUSTRALIA, N_SINGAPORE, P_MEDIA
- PARTIAL (4):
  - A_ISSUER_PRIMARY: general issuer IR resolver for ranked universe (JP/TW/US); filings lane covered by sec_edgar/jp_fsa_edinet/tw_mops
  - C_US_EXCHANGES: NYSE, Cboe, OCC, CME, ICE public datasets (BATCH B)
  - D_OPTIONS_DERIVATIVES: Cboe/OCC/CME official (BATCH B)
  - O_MARKET_AGGREGATOR: Yahoo/Stooq as secondary lane (BATCH B)
- MISSING (1): Q_CREDIT_RESEARCH (S&P/Moody's/Fitch/MSCI/Morningstar/LSEG/FactSet/bank research) — capability catalog only (PREMIUM_ONLY/AUTH_REQUIRED), BATCH E, no purchase

### EXISTING INFRASTRUCTURE (key files)
- scripts/adapters/ (14 adapters)
- scripts/providers/ (ibkr_client_portal.py)
- scripts/v213_source_federation.py, v213_source_federation_gate.py
- scripts/source_registry.py, authoritative_source_catalog.py
- scripts/source_acquisition.py, source_observation.py, source_health.py
- scripts/source_claim_coverage_gate.py, source_diversity_gate.py
- scripts/v213_source_independence_gate*.py (v1-v4)
- config/sources/ (7 region/sector registry files, 158 sources)
- config/authoritative-sources/ (6 region files + public-research-candidates + v213-runtime-extensions)
- config/authoritative-source-catalog.json (template, 0 sources)
- config/v213-source-federation-policy.json
- config/source-family-templates.json
- schemas/authoritative-source-catalog.schema.json

## MANDATORY SOURCE UNIVERSE (from directive)
- A. ISSUER PRIMARY: company IR, earnings, annual/quarterly reports, guidance, press releases, regulatory filings. PRIMARY_ISSUER_LINEAGE. Mirrors (Reuters/Yahoo/Nasdaq) of same press release = NOT new issuer lineage.
- B. US REGULATORY: SEC, EDGAR, FINRA, CFTC, Federal Reserve, FDIC. SEC filing/XBRL = highest authority class.
- C. US EXCHANGES: Nasdaq, NYSE, Cboe, OCC, CME, ICE, MIAX, BOX, MEMX. Premium feeds = CAPABILITY_DISCOVERED but PREMIUM_ONLY.
- D. OPTIONS/DERIVATIVES: Cboe, OCC, exchange, CME, TAIFEX, aggregator cross-check, Yahoo secondary.
- E. US MACRO: Fed, FRED, ALFRED, BLS, BEA, Census, Treasury, FiscalData, EIA, CFTC.
- F. INTL MACRO: IMF, World Bank, OECD, BIS, ECB, Eurostat, BoE, BoJ, PBOC.
- G. JAPAN: JPX, TSE, EDINET, TDnet, BoJ, Statistics Bureau, issuer IR, Nikkei (media/context only).
- H. TAIWAN: TWSE, TPEx, MOPS, TAIFEX, CB ROC, DGBAS, issuer IR.
- I. HK/CHINA: HKEX, HKEXnews, SSE, SZSE, CSRC, PBOC.
- J. SOUTH KOREA: KRX, DART, FSS, BoK, issuer IR.
- K. EUROPE/UK: LSE, RNS, Euronext, ESMA, ECB, Eurostat, FCA.
- L. CANADA: SEDAR+, TSX/TMX, BoC, Statistics Canada.
- M. AUSTRALIA: ASX, ASIC, RBA, ABS.
- N. SINGAPORE: SGX, MAS, SINGSTAT.
- O. MARKET AGGREGATOR: Yahoo, Stooq, Nasdaq public, exchange public. Optional: Alpha Vantage, Twelve Data, Tiingo, Marketstack, FMP, Polygon.
- P. MEDIA: Reuters, Bloomberg, FT, WSJ, CNBC, AP, Nikkei, Barron's, MarketWatch.
- Q. CREDIT/INDEX/RESEARCH: S&P, Moody's, Fitch, MSCI, Morningstar, LSEG, FactSet, bank research (Goldman, JPM, MS, BofA, Citi, UBS, Barclays, DB, Nomura, Mizuho).

## YAHOO RULES
Yahoo must NOT prove: audited revenue, company guidance, regulatory filing facts, replace SEC/EDINET/MOPS primary filings.
Yahoo CAN: OHLC, volume, chart timestamps, basic market-series observations, secondary price cross-check, symbol metadata (when independently validated).

## CLAIM TAXONOMY (22 classes, PENDING)
FILING_FACT, ACCOUNTING_FACT, GUIDANCE, MANAGEMENT_STATEMENT, CORPORATE_ACTION, PRICE, VOLUME, OPTIONS_REFERENCE, OPTIONS_MARKET_ACTIVITY, SHORT_INTEREST, INSIDER_ACTIVITY, INSTITUTIONAL_HOLDING, MACRO, RATES, FX, ENERGY, COMMODITY, ECONOMIC_ACTIVITY, REGULATORY_EVENT, CREDIT_RATING, NEWS_EVENT, ANALYST_COMMENTARY, INDUSTRY_DATA.
Each claim type needs: allowed_authority_classes, preferred_sources, minimum_independent_lineages, freshness_limit, staleness_behavior, publication_behavior.

## AUTHORITY PRIORITY (LEVEL 0-5)
- LEVEL 0: official regulator/government/exchange/issuer primary filing
- LEVEL 1: central bank/official statistical institution/official international organization
- LEVEL 2: licensed/recognized market infrastructure/clearing institution
- LEVEL 3: reputable market-data provider
- LEVEL 4: major financial media
- LEVEL 5: secondary aggregator/community source
Per-claim-type order possible (e.g. ACCOUNTING_FACT: SEC filing > issuer IR > exchange mirror > media > aggregator).

## TWO-DIMENSION LINEAGE (PENDING)
- data_origin_lineage: underlying claim origin (e.g. SEC filing)
- transport_lineage: how it was delivered (e.g. issuer IR mirror, Yahoo article linking SEC filing)
Different transport, same origin = NOT 3 independent sources. Source count ≠ confidence.

## SOURCE ROUTER (PENDING)
route_claim(claim_type, symbol, jurisdiction) → candidate_sources, authority_order, freshness_requirement, minimum_lineages, fallback_chain.
Examples:
- FILING_FACT + US: SEC → issuer IR → exchange mirror → media context
- FILING_FACT + Japan: EDINET → issuer IR → JPX/TDnet → media context
- FILING_FACT + Taiwan: MOPS → issuer IR → TWSE/TPEx → media context
- OPTIONS_REFERENCE + US: Cboe/OCC/exchange → secondary market-data
- MACRO_US_CPI: BLS → FRED → OECD/IMF context

## EVIDENCE QUALIFICATION
A source record is evidence_qualified only if: source identity valid AND claim class supported AND freshness valid AND schema valid AND lineage valid AND symbol/entity mapping valid AND required fields present. Provider success alone != qualified evidence.

## FAIL-CLOSED RULES
HTTP failure, invalid JSON, HTML-as-API, CAPTCHA, JS challenge, empty result, missing timestamp, stale data, schema mismatch, wrong symbol/exchange/currency/unit/date, duplicate lineage, unsupported claim, auth failure, premium block → source record NOT QUALIFIED. Never zero-pad. Never infer from unrelated sources.

## DETERMINISTIC FIXTURES (per adapter)
VALID, HTTP_ERROR, TIMEOUT, RATE_LIMIT, INVALID_JSON, EMPTY, STALE, SCHEMA_CHANGED, SYMBOL_MISMATCH, UNIT_MISMATCH, DUPLICATE_LINEAGE, UNSUPPORTED_CLAIM. Network live probe = informational. Unit test PASS does not depend on external network.

## FEDERATION TESTS (F1-F10)
F1: single provider available → valid but cannot fake required independent lineage
F2: two mirrors of same filing → lineage count = 1
F3: SEC + independent exchange market source → correct separate lineages
F4: official conflicts with aggregator → official retained, conflict recorded, no silent overwrite
F5: two official sources conflict → conflict state, fail closed for claim, Master review only if publication impact
F6: Yahoo down → federation continues
F7: SEC down → fallback only where claim rules permit, no fake primary evidence
F8: premium provider unavailable → no project failure
F9: all providers for one claim fail → claim FAIL-CLOSED, rest continues
F10: provider recovers → health returns automatically

## CONFLICT ENGINE
CONSISTENT, TOLERANCE_MATCH, CONFLICT, STALE_CONFLICT, UNIT_CONFLICT, ENTITY_CONFLICT. No simple majority vote. Authority-weighted resolution: higher-authority fresh source may supersede lower authority. Two high-authority conflicts → unresolved → fail closed for claim.

## FRESHNESS (per source family)
Market price: minutes/hours. Options reference: trading-day/current-contract. Filing: until superseded. Guidance: until withdrawn/replaced. Macro monthly: until next release. GDP quarterly: release/vintage. News: event timestamp. No single 7200-second rule for all data. Use existing policy structure; extend only with claim-aware freshness; do not weaken existing freshness gate.

## CACHE + RATE LIMIT
Bounded source cache. Cache key: institution, endpoint, entity, claim, as_of. Respect ETag, Last-Modified, Retry-After, Cache-Control, provider rate limits. No brute-force.

## SOURCE HEALTH DAEMON
Within existing scheduler architecture. Only: availability, parse health, age, schema fingerprint. NOT: restart credentials, purchase service, bypass rate limit. Health failure → quarantine lane → fallback → retry later.

## DECIDER CHECKPOINTS (per batch)
Mapika PRE/POST review. Schema (known working type): questions = {"verdict": {"type": "choice", "instructions": "...", "criteria": {"ACCEPT": "meaning", "REWORK": "meaning", "ESCALATE_MASTER": "meaning", "STOP": "meaning"}}}. ACCEPT >=0.70 → continue. REWORK → Qwen auto minimal rework → review again. ESCALATE_MASTER → auto call Master ruling → ingest → continue. LOW confidence → Master ruling → continue. No user ask.

## ADAPTER IMPLEMENTATION ORDER
- BATCH A — Primary corporate evidence: SEC, issuer IR, current JPX/EDINET/TWSE/MOPS needed by ranked universe
- BATCH B — Exchange/market: Cboe, OCC, Nasdaq public, NYSE public, JPX/TWSE/TAIFEX, Yahoo, Stooq
- BATCH C — Macro: Fed/FRED, BLS, BEA, Treasury/FiscalData, Census, World Bank, IMF, OECD, ECB/Eurostat, BOJ/other
- BATCH D — Media/event: Reuters/Bloomberg/FT/WSJ/CNBC/AP/Nikkei (permitted claim classes only)
- BATCH E — Optional/restricted capability catalog: FINRA auth lanes, premium Nasdaq/CME, S&P/Moody's/FactSet/LSEG/etc. (no purchase)

## RANKING SAFETY
New source != ticker bonus. Source federation only improves: evidence coverage, confidence provenance, freshness, claim verification. FORBIDDEN: SOURCE_COUNT_BONUS, FAMOUS_INSTITUTION_BONUS, MEDIA_MENTION_BONUS (unless existing scoring contract explicitly defines + recertified).

## CURRENT APPROVED TICKERS
Do not auto-change historical admission. Any originally FAIL-CLOSED ticker stays FAIL-CLOSED until new qualified evidence truly satisfies existing admission policy. FORBIDDEN: zero padding, synthetic evidence, source-count inflation, same-lineage duplication.

## PRODUCTION POLICY
Local implementation/test/commit/push: auto. Production source-federation deploy: requires explicit current-session OPERATOR authorization; Master technical approval (DEPLOY_APPROVED) alone is insufficient, and no deploy is authorized by this document. Operator-authorized deploy → Qwen deploy normal pipeline → readback → smoke test → auto rollback if gate fails. No operator authorization → no production deploy → continue next local task. FORBIDDEN: create paid account, rotate credentials, purchase data, expose secrets, alter brokerage integration, enable trading, weaken LINE privacy, bypass existing production seal/pointer-last.

## PRODUCTION CANARY (deployment order)
1. source adapters → 2. registry → 3. router → 4. evidence engine → 5. local replay → 6. sealed fixture replay → 7. production canary → 8. readback → 9. live product smoke test → 10. final promotion. Any step fail: auto rollback → evidence receipt → Mapika → Master → next repair cycle. No user wait.

## CANONICAL GATES
Python targeted tests, Python full suite, cloud npm test, cloud npm run typecheck, security_check, documentation_structure_gate, agent_skill_structure, JSON validation, supply-chain gate, git diff --check. Any gate fail: Qwen repair → Mapika → rerun. Max 2 repair cycles. 3rd fail → Master ruling → ingest → continue.

## PROJECT LOOP
REPO_PREFLIGHT → DECIDER_PIN_CHECK → SOURCE_REGISTRY_DISCOVERY → CAPABILITY_PROBES → CLAIM_TAXONOMY → SOURCE_ROUTER → BATCH_IMPLEMENT → TARGETED_TESTS → MAPIKA_REVIEW → FULL_GATES → COMMIT_PUSH → MASTER_REVIEW → IF DEPLOY_APPROVED: PRODUCTION_CANARY/READBACK/LIVE_TESTS/FINALIZE_OR_ROLLBACK ELSE: CONTINUE_LOCAL_NEXT_BATCH → NEXT_BATCH → LOOP. Until SOURCE_FEDERATION_COMPLETE=true AND PROJECT_RELEASE_COMPLETE=true.

## TASK SEQUENCE
- TASK0-3L_SOURCE_FEDERATION_FOUNDATION (CURRENT, IN PROGRESS)
- TASK0-3M_PRIMARY_OFFICIAL_SOURCES
- TASK0-3N_MARKET_OPTIONS_FEDERATION
- TASK0-3O_MACRO_GLOBAL_FEDERATION
- TASK0-3P_MEDIA_EVENT_FEDERATION
- TASK0-3Q_FEDERATION_REPLAY_AND_CONFLICT_ENGINE
- TASK0-3R_MASTER_PRODUCTION_REVIEW

## HARD STOP ONLY
1. repository corruption
2. secret leak detected
3. destructive operation impossible to rollback
4. conflicting Master governance rules
5. evidence/provenance integrity cannot be preserved
6. requested action requires payment/account creation and no free fallback exists
7. security boundary violation
8. Git state cannot be reconciled safely
Normal source/API failure is NOT HARD STOP. On HARD STOP: save evidence → Mapika → Master → if Master provides safe repair, auto continue → only Master explicit STOP_PROJECT truly stops.

## NEXT ACTIONS (for new session)
1. Mapika-v9 pin — RESOLVED ALIAS_ONLY (2026-09-19): actual v9 weights/paths verified (D:/Models/Mapika-decider-2b-v9, load_ms2124 = live health); reported API id decider-v8 is an alias only; no migration needed.
2. Complete TASK0-3L pending deliverables:
   - claim taxonomy (config/source-federation/claim-taxonomy.json)
   - origin/transport lineage schema (config/source-federation/lineage-schema.json)
   - source capability probe framework (scripts/source_capability_probe.py)
   - source router skeleton (scripts/source_router.py)
   - deterministic tests (tests/test_source_federation_*.py)
3. Mapika PRE/POST review of TASK0-3L.
4. Full canonical gates.
5. Atomic commit + push.
6. Auto-continue into TASK0-3M_PRIMARY_OFFICIAL_SOURCES.

## CONSTRAINTS
- Single writer (Qwen only). No two writers editing same repo simultaneously.
- No secret/credential/token/cookie/LINE ID output or persistence.
- No paid account creation, credential rotation, data purchase.
- No paywall bypass, credential sharing, copied subscriber content.
- No zero-padding, synthetic evidence, source-count inflation, same-lineage duplication.
- No weakening existing freshness gate, publication gate, or production seal/pointer-last.
- Do not re-open TASK0-3K (12:56/13:56 historical observability gap = NON_BLOCKING_HISTORICAL_OBSERVABILITY_GAP).
- Do not change historical ticker admission.
- Read-only discovery may be parallelized (Herdr read-only workers, Pi tools, Mapika routing). Never two writers.

## EVIDENCE RECEIPTS
- config/source-federation/source-coverage-matrix.json (coverage matrix)
- .tmp/task0-3j-repair/ (prior 3J/3K evidence)
- data/cache/sealed-refresh.log (production refresh log)
- state/STATUS.md (current task state)

## FINAL REPORTING FORMAT
PROJECT: INVESTOR_INTELLIGENCE_SOURCE_FEDERATION_FULL_AUTOPILOT
RESULT: PASS | PARTIAL | BLOCKED
SOURCE_COVERAGE: official_regulators, issuer_primary, exchanges, options_derivatives, us_macro, global_macro, regional_sources, media, aggregators, restricted_catalogued
FEDERATION: registered_sources, working_public_sources, deferred_auth, deferred_premium, temporarily_unavailable, failed_closed
CLAIMS: claim_classes, qualified, conflicted, fail_closed
LINEAGE: origin_dedupe, transport_dedupe, fake_independence_detected
TESTS: targeted, python, vitest, tsc, security, docs, supply_chain
DECIDER: model_pin, reviews
MASTER: model_tier, latest_ruling
GIT: commits, push, worktree
PRODUCTION: deployment, canary, readback, rollback
NEXT: <automatically continued task or PROJECT_COMPLETE>
AUTONOMY: human_intervention_required=false