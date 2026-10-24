# 文件索引 / Documentation index

Current acceptance register: [STATUS](../state/STATUS.md). Release identity: [README](../README.md) and each archive's own immutable refs/receipts. Historical dates, counts, model choices and approvals are not current authority.

本索引涵蓋所有Git可見Markdown（含新文件），由離線structure gate檢查；連結通過不代表事實或外部來源已重驗。檔案不為分類而搬移。

## Start here / 入口

- [README](../README.md)
- [README.zh-TW](../README.zh-TW.md)
- [AGENTS](../AGENTS.md)
- [CLAUDE](../CLAUDE.md) — Claude Code entrypoint importing AGENTS.md
- [IMPLEMENTATION_STATUS](../IMPLEMENTATION_STATUS.md)
- [STATUS](../state/STATUS.md)
- [POST_LAUNCH_BACKLOG / 上線後待辦](../state/POST_LAUNCH_BACKLOG.md)
- [CURRENT_STATUS_BILINGUAL](CURRENT_STATUS_BILINGUAL.md)
- [RESEARCH_EXECUTION_AUDIT](RESEARCH_EXECUTION_AUDIT.md)
- [PERSONA_LOGIC_FULL](PERSONA_LOGIC_FULL.md)
- [BOTTLENECK_RANKING_V1 — 未驗收設計草案](BOTTLENECK_RANKING_V1.md)
- [BOTTLENECK_CASE_STUDY_HITACHI_ENERGY_V1](BOTTLENECK_CASE_STUDY_HITACHI_ENERGY_V1.md)
- [COMPANY_EVIDENCE_CANDIDATES_INVENTORY_V1](COMPANY_EVIDENCE_CANDIDATES_INVENTORY_V1.md) - admission candidates (GEV, Hitachi 6501, Meiden 6508, Siemens Energy ENR): distance to typed admission, blockers; runtime admitted 0
- [TOP20_BOTTLENECK_TAKEOVER_V1](TOP20_BOTTLENECK_TAKEOVER_V1.md) — 系統瓶頸接管 v1 規格與呼叫路徑

## How-to and maintenance / 操作與維護

- [FINAL_RELEASE](FINAL_RELEASE.md)
- [FINAL_RELEASE_PLAN](FINAL_RELEASE_PLAN.md)
- [DEPENDENCY_LOCKING](DEPENDENCY_LOCKING.md)
- [WORKSPACE_MAINTENANCE](WORKSPACE_MAINTENANCE.md)
- [V213_FREE_WORKERS_RELAY](V213_FREE_WORKERS_RELAY.md)
- [LINE_TOP20_UI](LINE_TOP20_UI.md)
- [ENGINEERING_MAINTENANCE](ENGINEERING_MAINTENANCE.md)

## Contracts and reference / 契約與技術參考

- [DETAILED_REPORT_CONTRACT](DETAILED_REPORT_CONTRACT.md)
- [MODEL_RUNTIME_MIGRATION](MODEL_RUNTIME_MIGRATION.md)
- [LOCAL_RUNTIME_INDEPENDENCE](LOCAL_RUNTIME_INDEPENDENCE.md) — local gateway contract only; no live model qualification; acceptance is STATUS-authoritative
- [DECLARED_CLAIM_CANDIDATES](DECLARED_CLAIM_CANDIDATES.md) — MACRO candidate-only profile; no qualification or publication
- [PUBLIC_SOURCE_COVERAGE](PUBLIC_SOURCE_COVERAGE.md)
- [PUBLIC_UNIVERSE_DISCOVERY](PUBLIC_UNIVERSE_DISCOVERY.md) — 公開市場掛牌識別線索發現與覆蓋邊界（零錄取）
- [COMPANY_EVIDENCE_CANDIDATES](COMPANY_EVIDENCE_CANDIDATES.md) — 候選文本與引文位置驗證；非來源權威或排名准入
- [COMPANY_CLAIM_ADMISSION_BRIDGE](COMPANY_CLAIM_ADMISSION_BRIDGE.md) — 類型化公司主張准入橋接規範
- [PHRASE_ZH_QUALIFIED_PRESENTATION_CONTRACT](PHRASE_ZH_QUALIFIED_PRESENTATION_CONTRACT.md) — design only; no model activation
- [CARB_TYPED_SECTION_PARSER](CARB_TYPED_SECTION_PARSER.md) — CARB SF6 法規段落類型化解析（非准入、零權利）
- [PROVIDER_RUNTIME_HOOK](PROVIDER_RUNTIME_HOOK.md) — 提供者執行時期掛鉤與信任邊界（零公司准入）
- [ECB_REFERENCE_SOURCE_ADMISSION](ECB_REFERENCE_SOURCE_ADMISSION.md)
- [OPTIONS_SOURCE_REVIEW](OPTIONS_SOURCE_REVIEW.md)
- [PUBLIC_EOD_OPTIONS_SCOPE_DECISION](PUBLIC_EOD_OPTIONS_SCOPE_DECISION.md) — O11/O12 design only; grants no rights or admission
- [PUBLIC_OPTIONS_PROVIDER_RIGHTS_REVIEW](PUBLIC_OPTIONS_PROVIDER_RIGHTS_REVIEW.md)
- [SECURITY](SECURITY.md)
- [PRIVACY_MULTI_TENANT_POLICY](PRIVACY_MULTI_TENANT_POLICY.md)
- [IBKR_READ_ONLY](IBKR_READ_ONLY.md)
- [ZERO_COST_POLICY](ZERO_COST_POLICY.md)
- [LINE_PUBLIC_OPTIONS_ONLY_ARCHITECTURE](LINE_PUBLIC_OPTIONS_ONLY_ARCHITECTURE.md)
- [OPTIONS_RECOMMENDATION_SPEC](OPTIONS_RECOMMENDATION_SPEC.md)
- [MANUAL_OPTION_CALCULATOR](MANUAL_OPTION_CALCULATOR.md)
- [MACRO_OPTIONS_PRODUCTS_V1](MACRO_OPTIONS_PRODUCTS_V1.md)
- [GLOBAL_IDENTITY_RESOLVER_V1](GLOBAL_IDENTITY_RESOLVER_V1.md) — 全球證券身分解析器 v1
- [GLOBAL_EQUITY_LOOKUP](GLOBAL_EQUITY_LOOKUP.md) — 全球個股快查與代號歧義處理
- [LINE_BOT_QA_SPEC](LINE_BOT_QA_SPEC.md)
- [LINE_BOT_QA_IMPLEMENTATION](LINE_BOT_QA_IMPLEMENTATION.md)
- [QA_CAPACITY_CONTRACT](QA_CAPACITY_CONTRACT.md) — development-only; not R75 release acceptance
- [FORWARD_COMPARISON_PREMISES_V1](FORWARD_COMPARISON_PREMISES_V1.md) — design only
- [TOP20_UPSIDE_BRIDGE_V1](TOP20_UPSIDE_BRIDGE_V1.md) — upside ranking and order-realization bridge plan
- [SOURCE_ACTIVATION_PLAN_V1](SOURCE_ACTIVATION_PLAN_V1.md) — source activation wave plan
- [INDUSTRY_ROTATION_V1](INDUSTRY_ROTATION_V1.md) — macro industry rotation from BLS PPI and SEC XBRL
- [BOTTLENECK_TOP20_V3](BOTTLENECK_TOP20_V3.md) — bottleneck Top20 and the Leopold-led industry ranking
- [REVENUE_GUIDANCE_AUTOUPDATE](REVENUE_GUIDANCE_AUTOUPDATE.md) — revenue guidance renewal from official filings (shadow only)
- [F05B_PDF_EXTRACTION_CONTRACT](F05B_PDF_EXTRACTION_CONTRACT.md) — design only; no dependency adoption
- [TOP20_CARRY_FORWARD_V1](TOP20_CARRY_FORWARD_V1.md) — hourly seal of the validated LKG Top20, report-age contract, rollback
- [SOURCE_DIVERSITY_AUDIT](SOURCE_DIVERSITY_AUDIT.md) — product-by-source matrix, rejected sources, remediation order
- [GLOBAL_SOURCE_FEDERATION](GLOBAL_SOURCE_FEDERATION.md)
- [PUBLICATION_MODE_CONTRACT_V2](PUBLICATION_MODE_CONTRACT_V2.md) — Worker/install preflight parity, contract hash, deploy order
- [SOURCE_COVERAGE_MATRIX](SOURCE_COVERAGE_MATRIX.md)
- [KV_DEPLOYMENT_PREFLIGHT](KV_DEPLOYMENT_PREFLIGHT.md)
- [METHODOLOGY_ATTRIBUTION](METHODOLOGY_ATTRIBUTION.md)
- [GIT_HISTORY_PRIVACY_GATES](GIT_HISTORY_PRIVACY_GATES.md)
- [FINAL_CLEANUP_POLICY](FINAL_CLEANUP_POLICY.md)

## On-demand methodology / 按需研究方法

- [aschenbrenner-infra](../skills/aschenbrenner-infra.md)
- [serenity-bottleneck](../skills/serenity-bottleneck.md)
- [SKILL](../skills/serenity-public-research/SKILL.md)
- [CROSS_VALIDATION](../skills/serenity-public-research/references/CROSS_VALIDATION.md)
- [RESEARCH_METHOD](../skills/serenity-public-research/references/RESEARCH_METHOD.md)
- [SERENITY_LOGIC](../skills/serenity-public-research/references/SERENITY_LOGIC.md) — Serenity reasoning model reconstruction
- [ASCHENBRENNER_CONTEXT](../skills/serenity-public-research/references/ASCHENBRENNER_CONTEXT.md) — CONTEXT_ONLY essays and public filing leads
- [user-long-term-overlay](../skills/user-long-term-overlay.md)

## Dated evidence and historical technical references / 歷史與有日期的技術證據

Dated histories remain in their source revisions and R receipts; they are not current authority. Use STATUS and the applicable contract for current state. Retired notes and reports: `git show 34417b9:<path>`; source documents merged on 2026-10-24 (AUTHORITATIVE_SOURCE_CATALOG, SOURCE_POLICY_INDEX, KV_NAMESPACE_ISOLATION): `git show 147d616:docs/<name>.md`.

Older deployment/PASS/coverage claims here are scoped to their recorded revision, not today; current contracts and STATUS win. 未改寫歷史證據為今日成功。

- [FORMAL_PRIVATE_RELEASE](FORMAL_PRIVATE_RELEASE.md)
- [PHASE5_VALIDATION](PHASE5_VALIDATION.md)
- [PUBLIC_SOURCE_RIGHTS_REVIEW_20260909](PUBLIC_SOURCE_RIGHTS_REVIEW_20260909.md)
- [R75_SEVEN_FIELD_MIGRATION](R75_SEVEN_FIELD_MIGRATION.md)
- [STATUTORY_AUTHORITY_RESOLUTION_V1](STATUTORY_AUTHORITY_RESOLUTION_V1.md) — statutory authority and external citation typing (GOV/CCR provenance)
- [LINE_ALL_FRIENDS_ACCESS](LINE_ALL_FRIENDS_ACCESS.md) — `V213_LINE_ACCESS_MODE` switch (default `owner_only`), friend-lane limits, privacy invariants, rollout steps
- [OPERATOR_RUNBOOK](OPERATOR_RUNBOOK.md) — fail-closed operator procedures: health, rollbacks, task recreation, incidents, secret rotation, rollouts
- [V213_BILINGUAL_FIELDS](V213_BILINGUAL_FIELDS.md)
- [V213_NAMED_TUNNEL_DEPLOYMENT_HOTFIX](V213_NAMED_TUNNEL_DEPLOYMENT_HOTFIX.md)
- [V213_SERENITY_PUBLIC_LOGIC_SOURCE_DIVERSITY.en](V213_SERENITY_PUBLIC_LOGIC_SOURCE_DIVERSITY.en.md)
- [V213_SERENITY_PUBLIC_LOGIC_SOURCE_DIVERSITY.zh-TW](V213_SERENITY_PUBLIC_LOGIC_SOURCE_DIVERSITY.zh-TW.md)
- [V213_SERENITY_RELATED_PROJECTS_REVIEW.zh-TW](V213_SERENITY_RELATED_PROJECTS_REVIEW.zh-TW.md)
- [V21_OWNER_LINE_DELIVERY.zh-TW](V21_OWNER_LINE_DELIVERY.zh-TW.md)
- [V2_1_0_FINAL.zh-TW](V2_1_0_FINAL.zh-TW.md)
- [TSEM-20260909](research/TSEM-20260909.md)
- [FINAL_DELIVERY_REPORT_R75_FREE_RELAY](../state/FINAL_DELIVERY_REPORT_R75_FREE_RELAY.md)
- [ROLLBACK_JARS_POINTER_BACKUP](../state/rollback-jars/README.md) — archive of retired snapshot pointer bytes (operational)
- [TASK0_PHASE1D_SEALED_SNAPSHOT_FIXTURE](../cloud/test/fixtures/task0-phase1d/README.md) — fixed sealed-snapshot test fixture
