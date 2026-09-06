# R75 Serenity 來源基礎研究 / Source-backed Serenity research — 2026-09-06

As-of cutoff: **2026-09-06 (UTC)**. This document is a dated research record for the
P1 follow-up "actual Serenity source-backed research integration". It is **not** a Pi
sub-agent execution receipt, **not** deterministic pipeline output, and **not** a claim
of any official Serenity score, formula, private process, portfolio or performance.

## 0. Scope, lanes and identity boundary / 範圍與身分邊界

- Researcher: the Pi takeover session (assistant in the pi coding harness).
  Tools actually used: `web_search` (provider-backed web search), GitHub API (product
  refresh script), read-only corpus clone, direct URL fetches. The local Q5 model was
  **not** used for this research (held for isolated live qualification).
- Identity: public **Serenity / @aleabitoreddit** material only. Material whose corpus
  identity is `@stockgodserenity` is a different identity and is quarantined.
- Lanes, kept separate throughout:
  - **ATTRIBUTED_SOURCE_VIEWS** — dated, attributable statements from the public corpus.
  - **SYSTEM_RESEARCH_CANDIDATES** — companies independently verified against primary
    sources; explicitly **not** her endorsement or watchlist.
- Method: `skills/serenity-public-research/SKILL.md` plus `references/RESEARCH_METHOD.md`
  (read completely) and `references/CROSS_VALIDATION.md` were read before conclusions.
  Claim labels are SUPPORTED / INFERENCE only; UNSUPPORTED claims are excluded or
  disclosed as such.

## 1. Source provenance / 來源證據紀錄

- Canonical public corpus: `yan-labs/serenity-aleabitoreddit`
  - HEAD `da758108828f09807f5711eca2a0e9a20f7a81b3`, committed `2026-09-06T01:07:01Z`
  - sync state: last_tweet_id `2096149203278037407`, last_update_time `2026-09-05T08:11:29Z`
  - `data/aleabitoreddit_tweets.json` SHA256 `5f5a60186f126a546582e3ca06a6c59eb3d7e40754e8d22c0fbc77a8bab20fef`
  - Retrieved `2026-09-06T16:32:03Z` via `scripts/v213_refresh_serenity_public_sources.py`
    (receipt: `data/cache/v213_serenity_public_source_latest.json`; `latest_available_verified=true`,
    `company_fact_authority=false`, `raw_posts_redistributed=false`).
- **Direct X originals remain HTTP 403 / UNVERIFIED** (known since the 2026-09-05 external
  review of `https://x.com/aleabitoreddit/status/2055822766600016238`). Every view below is
  therefore labeled `ARCHIVE_ONLY` (corpus-verbatim with tweet id and date); archive
  retrieval does not cure the original-retrieval gap. None of these views is presented as
  independently original-retrieved.
- Skill/reference hashes recorded for attribution:
  - `SKILL.md` `90da9ba91d66f29baf086d568a4d55b63eb0166bca7a738b3db3c8a954f0e74e`
  - `references/RESEARCH_METHOD.md` `ad128461919d643a71a88bab5be080aba301c1e9b83a45c7d5790f381ce21bb7`
  - `references/CROSS_VALIDATION.md` `43e54b28d47f283fff7927d67c8c90a3e7efc1e77a253f9fbaad4c526d5d2f80`
- Corroborating non-corporate sources used below are independent of the corpus lineage
  (issuer press releases, SEC filings, trade press, research-firm notes). Multiple forks
  of the same tweet corpus are **not** used and would count as one lineage.

## 2. System change, not ticker-first / 系統變化優先

Two structural transitions dominate the 2026-09-01…09-05 corpus window:

1. **AI datacenter optical interconnect** — the binding constraint layer is CW/EML laser
   supply and its InP substrate base (bandwidth → laser → substrate), with a CPO ramp
   expected around 2028 that makes current laser allocation forward evidence.
2. **Memory** — legacy/niche DRAM (DDR2/DDR3) structural shortage on top of the general
   memory upcycle; a Japanese-distributor claim (via Nikkei) of a 40–60% memory demand
   deficit appears in the 09-05 view.

Ranking note per method §2: laser/substrate **layer** scarcity is treated as tighter than
individual ticker strength; the candidates below sit at that layer or are direct
counterparties of it.

## 3. ATTRIBUTED_SOURCE_VIEWS / 本人公開觀點（corpus-verbatim, ARCHIVE_ONLY）

All rows: lifecycle `ACTIVE` (1–5 days old at cutoff, not superseded in corpus);
verification `ARCHIVE_ONLY` (X original 403/UNVERIFIED); stance as written; none implies
a current holding.

| Tweet id (UTC date) | Ticker/theme | Stance (abridged, corpus-verbatim) |
| --- | --- | --- |
| `2096149203278037407` (2026-09-05 08:11) | $MU, $SNDK, memory, CW lasers | Memory bottleneck "hasn't changed"; short-term sentiment does; Japanese distributors (Nikkei) say memory demand deficit 40–60%; demand imbalances "get worse than people expect" |
| `2095453263613341938` (2026-09-03 10:06) | $SIVE | Sivers expanding InP manufacturing in Glasgow; target ~100M CW DFB lasers/yr; "implied revenue capacity might be ~$625M–$1.25B/year" at historical $50–$100 per 8-laser array (INFERENCE, not a company figure) |
| `2095546138510459218` (2026-09-03 16:15) | $SIVE, CW DFB | ">$100m CW DFB extraordinary capacity disclosure"; cites TrendForce July data: global CW/EML capacity ≈608.4M/yr (~50.7M monthly) with $AVGO/$LITE/Sumitomo named among suppliers |
| `2095580088620449880` (2026-09-03 18:30) | ESMT (6775.TW) | DDR2/DDR3 idea update: June revenue ~$153M, July ~$214M, August ~$249M vs $35.3M last year; "monthly revenue increased ~63% in two months" (USD conversions; see §4.2) |
| `2095279986701951461` (2026-09-02 22:37) | $AVGO | AVGO CEO (earnings call): "Demand for lasers, whether it is EML lasers, CW lasers. Is far surpassing supply out there in the industry"; "even while they 3x laser capacity" |
| `2095153855818547571` (2026-09-02 14:16) | $NVDA | NVDA told JPMorgan revenue could grow 100%+ Y/Y unconstrained; gave ~70% because of what it believes it can supply; "FY27 est: ~$401B; FY28: ~$682B at 70%" |
| `2094754861695070712` (2026-09-01 11:50) | $AAOI, $AXTI | "$AAOI outperforms in 2027 and the $AXTI InP substrates bottleneck/chokepoint got validated"; AXT "ASP hikes moving forward with their agreements like $LITE and $COHR" |
| `2094854529967862140` (2026-09-01 18:26) | $AA, Sojitz (2768), gallium | US "Department of War" $174M gallium supply-chain financing: $AA (Alcoa) refinery production, Sojitz as Japanese JV offtake partner |
| `2095460499769155944` (2026-09-03 10:34) | $IQE | IQE "quantum dot foundry leader"; announced purchase agreement with Quintessent; QD laser names ($ALMU, QD Laser 6613) may "finally start" — **UNVERIFIED lead in this pass** |

Position color present in the window (e.g. "I'm still holding my position" on $SIVE,
"1 single share of $IREN") is disclosure of her own book only; it is not aggregated into
a current-holdings list and does not upgrade any candidate.

## 4. SYSTEM_RESEARCH_CANDIDATES / 系統研究候選（獨立驗證，非其推薦）

### 4.1 InP / CW laser chain (constraint layer)

Demand side — counterparty official disclosure:
- **SUPPORTED** — Broadcom Q3 FY2026 earnings call (2026-09-02): CEO statement that
  EML and CW laser demand "is far surpassing supply out there in the industry"; EML
  capacity growing from >40M units (2025) to 50M (2026); CW capacity from mid-teens
  millions (2025) to ~30M (2026); FY27E revenue ~$115B and FY28E ~$230B framework.
  Sources: Benzinga transcript (2026-09), Chipstrat summary, SDxCentral (2026-09-03).
- **SUPPORTED** — TrendForce (2026-06-03): combined EML + CW-DFB monthly capacity of
  50.7M units in 2026 (≈608.4M/yr), matching the corpus-cited figure; NVIDIA/Google/Meta
  locking EML/CW-DFB supplier capacity. Independent of both Broadcom and the corpus.

Supply side — issuer official releases:
- **SUPPORTED** — Sivers Semiconductors (STO:SIVE) official press release (2026-09-03,
  Kista): USD 30M strategic investment to expand the Glasgow (Scotland) InP facility;
  output target **more than 100M CW DFB lasers annually**; work begins H2 2026,
  **operational Q4 2027**; driven by "anticipated customer production ramps" for AI
  datacenter/optical interconnect. Source: sivers-semiconductors.com press page (and
  PRNewswire mirror — one lineage).
- The corpus "implied revenue capacity ~$625M–$1.25B/year" is **INFERENCE**: official
  capacity figure × historical $50–$100 per 8-laser array pricing. Not a company
  disclosure; no order book is disclosed for SIVE.
- **SUPPORTED** — AXT, Inc. (NASDAQ:AXTI) SEC 8-K (filed 2026-07-29): Capacity
  Reservation Agreement with Lumentum Operations LLC (signed 2026-07-26) for InP wafer
  substrates, initial six-year period through 2031-12-31 (renewable one-year
  increments), with an initial deposit of **$43,500,000** due within thirty business
  days. SEC 8-K (filed 2026-06-30): Master Development and Supply Agreement with
  Coherent Corp (effective 2026-06-25), three-year term, **$22,288,500** prepayment
  against a defined 6-inch InP capacity commitment, Beijing capacity expansion 2026–2028.
  Signed commitments + customer prepayments are forward evidence per method §5; they are
  not yet recognized revenue.

Layer confidence (multi-axis, method §9):
- `factual_evidence_confidence`: **HIGH** (issuer filings/press + independent research firm)
- `dependency_confidence`: **MEDIUM-HIGH** (prepayment/reservation evidence of
  allocation; effective substitute InP capacity and yield remain unquantified)
- `company_capture_confidence`: **MEDIUM** (SIVE financing/dilution overlay — ATM
  history, use of proceeds — NOT assessed in this pass; AXTI China-fab export exposure
  noted, not quantified)
- `source_view_freshness`: **HIGH** (views 1–5 days old at cutoff)
- `timing_confidence`: **MEDIUM** (Q4 2027 operational date is company-stated; CPO mix
  shift to 2028 unverified)

Falsifiers: SIVE Glasgow ramp slips or under-runs; Broadcom/Sumitomo 3× laser capacity
plus other new InP fabs close the gap faster; CPO architecture changes laser mix/volumes;
InP substrate pricing normalizes (prepayments not converted to volume); export/geopolitical
constraints on AXTI's Beijing production; AI capex slowdown.

### 4.2 Legacy memory — ESMT (6775.TW)

- **SUPPORTED** — ESMT issuer monthly-revenue announcement (esmt.com.tw press room,
  2026-08-04 for July 2026). Digitimes (2026-08-06): July revenue +40% vs June, monthly
  record; Q2 2026 record profit on niche-memory contract price increases (2026-08-02).
  Digitimes (2026-09-04): record August consolidated revenue for ESMT (and Nanya) on
  higher contract prices. June 2026 monthly record NT$4.85B (Digitimes 2026-07-06).
- **SUPPORTED** — TrendForce (2026-06-22): structural tightening of mature-node DRAM
  supply pushing buyers to legacy DDR2/DDR3, with continued DDR2 contract-price momentum.
- **INFERENCE** — corpus USD figures (~$153M Jun / ~$214M Jul / ~$249M Aug; ~$35.3M
  year-ago) are FX conversions of NT$ disclosures; the direction and magnitude (records,
  ~+40% MoM in July, ~63% over two months) are corroborated, the exact USD levels depend
  on the conversion rate used.
- **UNSUPPORTED (disclosed as attributable view only)** — the "40–60% memory demand
  deficit" figure attributed to Japanese distributors via Nikkei (09-05 tweet). Secondary
  attribution, not independently verified in this pass; must not enter publication as a
  company/industry fact.

Layer confidence:
- `factual_evidence_confidence`: **HIGH** (issuer revenue announcements)
- `dependency_confidence`: **MEDIUM** (structural legacy-shortage thesis supported by
  TrendForce, but effective new legacy capacity and customer mix not quantified)
- `source_view_freshness`: **HIGH**; `timing_confidence`: **MEDIUM**

Falsifiers: new legacy-DRAM capacity entry or requalification wave; contract-price
normalization after the upcycle; ESMT customer concentration risk; demand shift away from
DDR2/DDR3 as mature-node supply tightens elsewhere.

### 4.3 Demand-side anchors (context only, not candidates)

- **SUPPORTED** — NVIDIA (2026-08-26, Q2 FY2027 earnings): preliminary fiscal-2028
  revenue growth ~70%; Q3 FY2027 revenue guidance $108B ±2%; management described
  demand as growing at ~100% with the gap attributed to supply (memory components
  explicitly cited as continuing to constrain ramp) — Reuters, CNBC, Fortune (all
  2026-08-26); JPMorgan investor meeting 2026-09-02 reiterated the ~70% FY28 framework.
  The corpus figures (~$401B FY27 / ~$682B FY28) differ slightly from press-consensus
  figures ($396B → ~$673B); the 70% framework is confirmed, exact totals are
  NOT_COMPARABLE until NVDA's 10-Q/10-K figures land.

## 5. What this does NOT prove / 未證明事項

- No official Serenity score/formula/private process is claimed or implied.
- No current-holdings list is asserted; disclosed position color is hers only.
- X originals are 403/UNVERIFIED — all views are `ARCHIVE_ONLY` and can be re-dated or
  withdrawn if direct retrieval later contradicts the corpus text.
- No performance/price-appreciation claim is made or used as evidence (method §11).
- The corpus and its forks are one evidence family; they never corroborate themselves.
- No trading, no private/broker data, no paywall bypass; missing fields fail closed.

## 6. Seven-field readiness (fail-closed) / 七欄就緒狀態

Using only disclosed commitments (method §10, CROSS_VALIDATION §4):

| Candidate | Current orders（現在訂單） | Future order outlook（未來訂單預估） |
| --- | --- | --- |
| AXTI (AXTI) | 已揭露之承諾：Lumentum $43.5M 初始預付 + 2031 年前產能預約；Coherent $22.29M 預付 + 三年產量承諾（具體產量未揭露） | 無可靠公開預估（合約期限內產量未公開；INFERENCE 仅限方向） |
| SIVE (SIVE) | 未揭露（無可靠公開訂單數字）— 僅揭露擴產計畫，無訂單簿 | 無可靠公開預估 — Q4 2027 產能目標是產能計畫，不是訂單預估 |
| ESMT (6775.TW) | 未揭露（無可靠公開訂單數字）— 月營收為已揭露財務事實，非訂單 | 無可靠公開預估 — 合約價趨勢有第三方證據，公司未給訂單預估 |

## 7. Gaps and next steps / 缺口與下一步

- UNVERIFIED leads queued (not asserted): IQE–Quintessent quantum-dot acquisition terms;
  Foci (NVDA FAU supplier, 3363.TW) price/capacity claims; $GPRO–Starman Optical 800G/1.6T
  merger details; $AA/Sojitz gallium award amounts beyond the $174M program.
- SIVE financing/dilution overlay (ATM history, use of proceeds, share count) — required
  before any `company_capture` upgrade (method §6).
- AXTI China-fab export-constraint exposure — quantify before dependency upgrade.
- Re-attempt direct X original retrieval when access is restored; on success, upgrade
  the affected views from `ARCHIVE_ONLY` to original-verified and re-date them.
- This document is a research record only; it does not change scoring, publication
  contract, LIMITED restrictions, freshness gates, or any deployment.
