# Research execution and card-content audit / 研究接線與資訊保留

Checked against source `4ba2a606c9e459884e15354aa91798ec432df0ba` on 2026-09-12, then corrected locally. This is source/caller analysis, **not fresh Production verification, current investment recommendations or a completed 20-company deep-research run**. Latest tests/findings: [STATUS](../state/STATUS.md).

## Two screenshots: what actually changed

The operator supplied a 2026-09-08 card and a 2026-09-12 card. They contain different companies/runs; changed membership and historical returns are not by themselves evidence of regression.

| Observation | Source trace / correction |
| --- | --- |
| Chinese names and detailed product descriptions disappeared | Old presentation contained ticker-keyed static narratives. Current report carries `name` from the accepted public universe; evidence detail incorrectly said original names were absent. Corrected to display the actual row name. Curated, source-bound Chinese names/product descriptions still need an admitted data path; no guesses restored. |
| MU +80%～+125%, SMCI +150%～+220% and downside ranges disappeared | `git show 6444dcd:cloud/src/v213/top20-presentation.ts` contains literal strings in `TOP20_SENSITIVITY`; no per-order operands, EPS/share bridge, dated comparable multiples or reproducible calculation. These are not validated forecasts and must not be copied back. |
| Deep-analysis / full-text buttons disappeared | The old labels overstated the available data. Current full research products deliberately return `RESEARCH_PRODUCT_NOT_SEALED`. Corrected candidate cards retain two honest, same-snapshot actions: evidence detail and full **company seven-field text**, not fake deep analysis. |
| Order timing and requested horizons are hard to find | Preserve the exact existing outlook string, including any disclosed percentages/windows. Explain filing date vs fulfillment date. Surface 6/12/24-month missing valuation status on cards and expand premises/limitations in evidence details. |

The actual authorized Worker caller is tested with mocked LINE transport, including both card actions, same-date content/run replacement, field completeness and size limits. No real LINE message is sent by these tests.

## Does the SKILL execute?

| Lane | Actual mechanism | What it does **not** prove |
| --- | --- | --- |
| Pi interactive research | On-demand `skills/serenity-public-research/SKILL.md` instructs the agent to read both references; all three were read and installed/source hashes compared in this audit | Not a scheduled screen, production model invocation or proof all claims were independently verified |
| Deterministic Top20 | Python collection/scoring/order reconciliation → seven-field report → pinned Worker renderer | Does not invoke Pi SKILL or a full model-led research process; a `canonical_serenity_skill` path in H6B output is metadata |
| Legacy enriched gateway | `v213_local_llm_gateway.enrich_messages` injects a system directive and existing source-independence context | Does not load the full SKILL/reference files. New response evidence reports `LEGACY_SYSTEM_DIRECTIVE`, directive hash, `full_skill_executed=false` and unverified model adherence |
| Profiled compact Q&A | `compact_upstream` validates a bounded prebuilt policy/context; `do_POST` bypasses legacy enrichment | Not the full SKILL. Reports `COMPACT_POLICY_ONLY`; transport marker smoke is `TRANSPORT_SMOKE`, not research |

The compact policy currently requests two short sentences, at most 65 Chinese characters. It cannot serve as the missing full report; do not silently enlarge the certified route, change model/presets or loosen its latency gates to hide that gap. Adding metadata is observability, **not implementing full autonomous research**.

The source/installed SKILL and references matched before edits:

- SKILL SHA256 `0fea4749dfdcf6ab88fe4eff71aacef34e5088b77e14c4064a7470cdd69ebd70`
- RESEARCH_METHOD SHA256 `32e66a880665143641f35d75e30abd99a8fdd5244775bf921eaebd2745d5cb2c`
- CROSS_VALIDATION SHA256 `ffb3994f5b8863024c1a77342b7e3f0f81c3a756bfc20da65a6e72472b3e18d1`

No actual local-model inference was run for this audit; no provider/model or skill-execution receipt is fabricated. Source-reading and synthetic caller tests are the evidence scope.

## Serenity and Leopold logic

Serenity remains the primary **public reconstruction**: system change → constrained layer → effective substitutes → company operating capture → financing/dilution → falsifiers. Named customers, high margins, sector labels or a rising stock price do not alone prove scarcity. The original scoring and LIMITED gates are unchanged.

Leopold Aschenbrenner is **CONTEXT_ONLY**: dated compute, capital, energy and deployment scenarios generate hypotheses, never company-order evidence, a score bonus, a current holding claim or a permanent AI-universe filter. The legacy gateway lacked an explicit Leopold-only trigger/context boundary; the candidate now states this and tests it. `included_in_serenity_score=false` remains unchanged.

Recent public-source check:

- Retrieved [Leopold's original cluster essay](https://situational-awareness.ai/racing-to-the-trillion-dollar-cluster/): “These are just very rough numbers anyway”; infrastructure “lead times ... are much longer still.” This is the historical 2024 scenario, not a new 2026 forecast or proof of any supplier's orders.
- [Community methodology archive](https://github.com/yan-labs/serenity-aleabitoreddit/blob/main/serenity-aleabitoreddit/references/methodology.md) is a discovery lead, not independent company corroboration or verified current Serenity advice.
- Direct [discovered @aleabitoreddit post](https://x.com/aleabitoreddit/status/2088226398708338889) returned **HTTP403**. Content/current stance remains UNVERIFIED; no mirror count or search synthesis cures it. No authentication or paywall bypass.

## Bounded 2026-09-11/12 public-source review / 有界公開來源檢視

Recorded 2026-09-12 against working tree `b96167af` (then uncommitted code; that session was documentation-only); the recorded fixes are now committed at `9aeb3d4` and `a01358c` with their tests tracked. A bounded, dated, attributed-source review — not an exhaustive feed, a runtime cache update, a production refresh or a recommendation list.

| Finding | Record |
| --- | --- |
| Discovery | Yahoo-only three-screener discovery; 120/50/20 are configured caps/target, not observed throughput |
| Issuer facts | SEC-centric issuer facts only; macro/identity websites are not company-claim corroboration |
| Leopold | No direct Leopold score bonus. The 2024 situational-awareness.ai essays and the June 30 13F (Situational Awareness LP, CIK 0002045724, filed 2026-08-14, table contains put/call rows; separate Schedule 13D on SharonAI Holdings) are not current holdings, orders or company corroboration |
| Serenity skill | Full Serenity skill execution remains incomplete, with 4 deliberately zero structural factors; `company_research_skill_run_completed=false` |
| LINE20 | No same-cutoff live LINE Top20 comparison (run ID/list not established in this audit); do not imitate social lists |
| Sept 11/12 posts | Three dated @aleabitoreddit originals (one 09-12, two 09-11) are bounded attributed views with `ticker_recommendation=false`, `company_fact_authority=false`; not a complete recommendation feed. The KuCoin AAOI/ESMT item is MIRROR_ONLY_ORIGINAL_UNRESOLVED discovery lead only |
| Archive health | Observed 2026-09-12 archive HEAD `b3784cb` (yan-labs/serenity-aleabitoreddit) recorded failure/`stale_unverified` (checked 2026-09-12T01:03:31Z; last cursor 2026-09-09); a fresh commit is not a fresh post |
| Cache boundary | Public audit refresh is not a runtime cache update: `source_cache_used_for_market_claims=false`, `runtime_cache_updated=false`, `production_mutated=false`, `real_line_sent=false` |
| Defaults | Six tainted synthetic defaults remain excluded from scoring/research |
| Open work | Full per-claim lineage/identity/order/valuation/macro/options/device/release work remains open |
| Authority | Generic authorization is not production/LINE/credential/installation authority; SEC contact scope still unresolved |

Receipts (literal paths under the installed root, not repository links): `_workspace/audit-runtime/astra-qwen-20260912/public-view-refresh.json` (as-of 2026-09-12; skill/reference SHA256s match the list above), the erroneous `scoped-source-receipt.json` and its metadata-only `scoped-source-receipt-correction.json`. The correction's finding stands: the original receipt's creation time is UNKNOWN and was not converted to a measured clock.

## Follow-up: new-member order extraction

`reconcile_v213_order_evidence.py` previously called the mutable `h6b.generic_sec_outlook` symbol. In a fresh process it could be the retired first-amount/same-sentence extractor; historical imports could silently replace it. The caller now explicitly selects the existing R15 semantic chain, preserving its unit, context and same-accession rules. A year or “幾乎全部／很多” alone is not admitted as a quantitative forward amount. Unchanged membership no longer fetches a needless SEC ticker map.

The actual reconciliation CLI is tested with synthetic SEC transports: unrelated revenue is not an order, a filing year alone is not an outlook, and an explicit RPO amount plus a60% recognition window is retained. Existing baseline order text/as-of/URLs are retained; membership reconciliation is not a fresh order-source refresh. Inherited company-report retrieval stamps do not prove a new order-source retrieval. This correction does not validate old rows, refresh20 companies, create individual contracts or calculate share-price targets. Missing current/future values remain the canonical unavailable strings.

The rich-menu route is deterministic navigation/industry aggregation, not full SKILL execution. Its exact capabilities and unfinished data are described in [LINE UI](LINE_TOP20_UI.md).

### Order acquisition is not report assembly

A later whole-caller check found that reconciliation could fill an absent order acquisition timestamp from the fresh five-field company report. That defeated the strict seven-field builder's unknown-clock refusal. The corrected caller does not inherit market/company clocks. The default R15 resolver records conservative acquisition-start times only for successful cited source-text reads; unvisited or failed citations remain unknown. Repeated reads retain the oldest clock, with UTC parsing rather than string sorting.

Previously generated runtime baselines carrying either known clock-inheriting producer tag cannot recycle those unproven clocks. Original input artifacts remain untouched; missing clocks do not become current facts. A newly assembled seven-field artifact has its own completion timestamp, permitting order retrieval after the five-field report while retaining the oldest contributing acquisition time. Future timestamps still fail; missing clocks cannot be cured by a new generation date. The actual reconciliation→strict-builder CLI regression retains original output sentinels on refusal.

These are clock provenance repairs, not original-passage/hash/rights qualification, a fresh20-company refresh or a complete per-order ledger. Live publication still requires all existing source/claim and freshness gates.

## Required order ledger — still not implemented in the seal

Each item must carry company/security identity, contract/customer (or explicitly undisclosed), RPO/backlog/firm order/LOI/pipeline type, amount and/or quantity/unit/currency, original passage and URL, publication/financial-as-of/retrieval dates, hash, claim status and underlying disclosure lineage. Preserve cancellation terms, recognized vs remaining amounts and superseded revisions.

**Timing:** retain disclosed start/end, fiscal/calendar basis and precision (day/month/quarter/year/window/unknown). “Within 12 months” is a window anchored to the disclosure's applicable date, not an invented exact delivery day. Delivery, acceptance, revenue recognition, cash collection and stock repricing are separate events. An aggregate RPO disclosure is not a list of individual customer orders; do not invent the missing rows. Overlapping backlog/RPO/prepayment entries cannot be summed.

**Three horizons:** for 6 months, 1 year and 2 years, separately model on-time, delay/partial and failure/reversal:

1. Evidence-bound shipment/recognition schedule and unit economics → revenue.
2. Margin, operating expenses, taxes, capex and working capital → earnings/cash flow.
3. Debt, funding, SBC/warrants/convertibles → diluted shareholder capture.
4. Appropriate valuation with dated comparables or explicitly justified assumptions; EV-to-equity adjustments; do not apply positive P/E to loss-making cases.
5. `price_return_pct = (scenario_value_per_share / dated_reference_price - 1) × 100`. Distinguish price return from dividends/total return. No unjustified probabilities or fixed bull/bear percentages.

Missing inputs mean **UNAVAILABLE**, not 0%, “very large,” guaranteed growth or a fabricated date. A local financial candidate exists but lacks this complete order/valuation chain and is not sealed. See [full report contract](DETAILED_REPORT_CONTRACT.md).

## SEC contact-header code closeout and audit chain (2026-09-13)

Committed at `37b506a1060a326f0ebeebc052709d274783c1e5` (branch `fix/options-provenance-audit`), exactly 5 files: new `scripts/sec_contact_headers.py`, `scripts/v21_serenity_top20.py`, `scripts/v213_serenity_h6b_full_top20.py`, `scripts/v213_source_federation.py`, new `tests/test_sec_contact_headers.py`. Independent recheck **SCOPED PASS** with the original FAIL retained, not replaced. Tests: 68 post-F1 PASS recorded, not rerun (`header-encoding-green.log`, GUARD_EXIT=0, zero denials); the 6 `test_v21_serenity_engine.py` tests reran 2026-09-13 under the pinned deny-network-v2 guard, 6/6 OK, RC=0 (`header-docs-engine-tests.log`), justified because the helper changed since they last ran. 68/61/23 are overlapping views of one test population, never summed as new distinct tests; the prior closeout's 51 health, 14 author, 22 doc tests and eight gate results are historical, not rerun.

Semantics: constructed User-Agent/From admitted as printable ASCII 1..512 is policy aligned to the existing v21 public-header boundary, not a statement that the transport supports all Latin-1. `from None` suppresses displayed exception chaining only (`__suppress_context__`), not memory erasure: `__context__`, traceback locals and the fixture's retained exception can retain identity. H6B contact handling is host-only; non-SEC requests and federation use a generic User-Agent without SEC identity, with no automatic redirects and no ambient proxy/netrc. The mapping defines the loader; it does not prove a runtime contact file exists or is valid.

Truthful audit chain: the earlier anonymous SEC GET is REPORTED (1/404/proto UA); actual occurrence, count and time were not independently verified, the original time is UNKNOWN and the response unused. The later authorized anonymous Git fetch succeeded (preflight 2026-09-13T05:00:50Z); no push. The phase is not claimed network-free, model-free or mutation-free. Qwen authored the local source/docs changes; application/Production LLMs were not invoked. Driver v1's successful security scan (`header-local-gate-security.log`) remains recorded; v1's claimed universal fallback/path guarantees were overstated (gaps A/B), and the audit-only driver-v2 synthetic proof (23-check self-test, `local-gate-v2-summary.txt`) closes those claimed boundaries — a synthetic driver proof, not a security rerun or current PASS. No new source code, OS or preset changes came from driver v2.

Metadata: the mixed SHA-256/Git-blob receipt is superseded by the separate correction `header-evidence-correction.json` (algorithms in explicitly separate fields; helper base retained and matching preflight, so no lineage-loss or unrecoverable-base claim). The intermediate 67/1 GREEN log was overwritten; only its reported summary is retained, with no fabricated raw recovery. All other RED/error/abort evidence and old receipts are preserved. All of this is source/mocked caller proof, **not** live research, installed, LINE or release acceptance.

## Options-menu admission correction (2026-09-13, from source `55edb2d9`)

The 期權 rich-menu panel no longer derives its status from the presence of unsealed `options:latest`/`latest_options` keys (root or run-scoped old-run carryover). Status follows only the pinned sealed-snapshot validation: a byte-verified sealed round reports `OPTION_DATA_NOT_ADMITTED` (the `v213-stored-snapshot-v1` contract object set contains no options member), and legacy/invalid views report `OPTION_DATA_UNAVAILABLE`. No schema or TTL was invented, no quote is rendered, and the 最新期權 action still routes to the unchanged `qa.ts` per-ticker freshness gate. `test/v213-rich-menu.test.ts` adds 12 actual-caller fixtures — fresh/stale/future/malformed/non-array/missing-timestamp/eligible-true/eligible-false, old key name, run-scoped old-run carryover, and a fully sealed round with fresh unsealed decoy keys — asserting no 快照存在 claim, no quote leakage and zero options-key reads through the pinned reader. This is menu-status truthfulness, **not** a sealed options product or any change to the admitted latest-options path.

## Remaining release work

Acquire/review admissible per-order source data, implement the ledger and scenario validator, bind distinct data/narrative products to a versioned sealed manifest, test pinned readers and real button callers, and obtain fresh source-bound Windows/archive/install acceptance. Deployment and genuine LINE delivery require explicit current-session authorization. This audit fixes visibility and truthful execution reporting; it does not claim those missing products now exist.
