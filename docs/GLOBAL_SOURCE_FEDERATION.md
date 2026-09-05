# Investor Intelligence R75 全球權威來源聯邦｜Global Source Federation

_Last reconciled / 最後核對：2026-09-05 Asia/Taipei_

[文件索引](README.md)｜[權威來源目錄](AUTHORITATIVE_SOURCE_CATALOG.md)｜[最新正式發布](FINAL_RELEASE.md)

## 設計目標｜Design objective

Investor Intelligence 不設定八個、二十個、九十九個或一百個來源的固定上限。R75 source-planning inventory 目前為 101，但 runtime activation 仍以 authority、identity、合法免費存取、provenance、freshness、schema、adapter 與 health gate 為準。

```text
NO_ARTIFICIAL_SOURCE_COUNT_LIMIT
+ STRICT_SOURCE_ADMISSION
+ BOUNDED_PER-HOST_CONCURRENCY
+ PRIMARY-EVIDENCE-FIRST
+ CLAIM-LEVEL-INDEPENDENCE
+ FAIL-CLOSED_CORRECTNESS
```

沒有數量上限不等於無限制 scraping。每次 run 受到 request、response-byte、wall-time、retry、per-host concurrency、quota 與 cache freshness 預算約束。

## 最新已驗證實機狀態｜Latest verified runtime state

```text
catalog_count = 101
global source families = 7
official source families = 6
ticker coverage = 100.0%
missing required families = none
conflicts = 0
claim families = 2
claim domains = 3
claim primary coverage = 100.0%
non-Yahoo market corroboration = 0.0%
```

免費 non-Yahoo market data 在該 run 中不可用，因此全部 20 個候選維持 `LIMITED_RESEARCH_CANDIDATE`。這不是 source-federation failure：公司／claim diversity 與 primary coverage 通過，而缺少 market corroboration 被披露並限制信心；unsupported positive factors 在 snapshot 前歸零。

## Eligible source families

可納入規劃與審查的來源包括：

- securities regulators、statutory filing systems；
- regulated exchanges、official announcement systems；
- central banks、finance ministries、treasuries；
- national statistics offices、government open-data portals；
- international organizations、multilateral institutions；
- court、patent、procurement、customs、trade、sanctions databases；
- official company IR sites、filings、press releases；
- regulated market infrastructure 與合法免費 market observations；
- academic、standards、scientific repositories；
- reputable newswire/publication 作獨立 corroboration 或 discovery lead；
- sector regulators、energy/grid/telecom/environmental authorities；
- 經相同 admission lifecycle 通過的新來源。

Popular、政府風格網域、搜尋排名或他站轉述本身都不構成 admission。

## Trust tiers

### Primary official authority

法定 publisher／資料所有者，如 regulator filing、exchange announcement、central-bank release、government statistic、court/patent record、issuer filing、official company release。

Primary source 可以支持其權限範圍內的直接事實，但不自動支持 investment conclusion 或 causal inference。

### Institutional corroboration

受監管 market infrastructure、intergovernmental institution、standards body、academic repository 或透明 attribution 的 institutional source，可支持獨立 corroboration。

### Secondary lead／public observation

Reputable publication、aggregator 或 public market convenience 可作 discovery／context；不能取代 material company claim 的 primary evidence。

Yahoo/yfinance 是 T3 seed／public observation，不能被當成 official、broker-grade 或唯一 methodology。

### Quarantined

Forums、anonymous posts、copied/unsourced content、SEO farms、schema unstable、payment required、terms incompatible 或 identity unverified 的來源不得影響 scoring、recommendation 或 factual report。

## Source admission lifecycle

```text
DISCOVERED
  -> IDENTITY_VERIFIED
  -> AUTHORITY_SCOPE_REVIEWED
  -> LEGAL_AND_FREE_ACCESS_APPROVED
  -> ADAPTER_CONTRACT_VALIDATED
  -> PROVENANCE_VALIDATED
  -> PARSER_CANARY_PASS
  -> HEALTH_SOAK_PASS
  -> RUNTIME_ENABLED
```

失敗狀態包括：

```text
QUARANTINED
DISABLED_PAYMENT_REQUIRED
DISABLED_TERMS_INCOMPATIBLE
DISABLED_IDENTITY_UNVERIFIED
DISABLED_SCHEMA_UNSTABLE
DISABLED_HEALTH_FAILURE
DISABLED_FREE_ONLY_POLICY
```

Discovery 永遠不會 auto-enable source。

## Registry architecture

來源由目錄式 registry 與 strict schema 管理，總數可成長；runtime 以 operational controls 限制：

- per-host concurrency；
- request rate；
- bounded retry/backoff；
- circuit breaker；
- free-quota budget；
- priority queue；
- cache TTL／freshness；
- source-specific terms/access controls。

超出預算時 defer，不增加 request storm，也不自動進入付費方案。

## Provenance contract

每筆 accepted observation 至少應具有：

```text
source_id
source_family
authority_class
trust_tier
canonical_url
jurisdiction
language
published_at
retrieved_at
content_hash
parser_id
parser_version
claim_type
evidence_role
freshness_status
source_health
correction_status
```

Model-generated text 不能成為 source evidence。

## Claim verification policy

### Direct official facts

Current primary record 可支持 publisher 權限內的 filed revenue、policy rate、employment figure 或 exchange announcement。

### Secondary／interpretive claims

Material interpretation 需要：

- 一個 claim-relevant primary source加獨立 corroboration；或
- 至少兩個可追溯 original material 的獨立 institutional sources。

### Conflicts

系統不平均矛盾 facts，優先順序：

1. corrected/restated primary source；
2. current primary source within legal authority；
3. official exchange/regulator mirror；
4. independent institutional corroboration；
5. reputable secondary coverage。

仍無法解決時，必須披露 conflict，且 disputed field 不得驅動自動 score change。

## Publication-mode integration

```text
EVIDENCE_QUALIFIED
LIMITED_RESEARCH_CANDIDATE
```

- Evidence-qualified row 需要 strict claim evidence、independence、freshness 與 primary support。
- LIMITED row 需要 primary evidence 與 independent publication provenance，但 inference confidence 必須限制為 LIMITED。
- LIMITED 不得 HIGH eligible、不得 validated thesis、不得保留 unsupported positive sensitive factors。
- BLS 為 optional macro context；required family/count 與 claim independence gate 仍 fail closed。

## Stability and correctness

- last-known-good normalized record 與 raw attempt 分離；
- content hash 與 retrieval timestamp 不可混用；
- reject impossible future publication time／malformed chronology；
- parser/schema drift 使用 canary fixture；
- sudden outlier 先 quarantine；
- correction/restatement/superseded version 不靜默覆寫；
- delayed/stale/preliminary/revised/final 明確標示；
- source outage 不轉成零值；
- lower-trust substitute 必須改變 evidence label；
- public source cache 與 tenant-private state 分離；
- retrieved content 視為 untrusted data，防 prompt injection。

## Zero-cost boundary

Required source 不得要求：

- paid API key；
- premium subscription；
- credit card auto-rollover；
- paywall/login/CAPTCHA/access-control bypass；
- prohibited scraping；
- paid market-data package。

Licensed broker source 若使用者本來合法擁有且無新費用，也只能是 tenant/private path，不能成為 global public feed。

## Release gates

Production enable 前至少要求：

1. registry schema validation；
2. authority/domain identity；
3. legal/free-access review；
4. deterministic normalized adapter；
5. complete provenance；
6. stale/revision/correction tests；
7. rate-limit/circuit-breaker tests；
8. hostile/malformed-content tests；
9. outage preserves last-known-good；
10. no tenant-private transmission；
11. no paid fallback；
12. coverage-ledger entry；
13. exact-head CI；
14. publication contract and negative fail-closed tests。

## Non-goal

系統不承諾持續抓取全世界每個公開網站。它承諾沒有人工 source-count ceiling，且每個 admitted source 都可追溯、合法、免費、獨立治理、受預算限制並 fail closed。

## English summary

R75 currently plans from a 101-record catalog without a fixed ceiling. The latest verified run used seven source families and six official families with 100% ticker coverage. Free non-Yahoo market corroboration was unavailable, so confidence remained LIMITED and unsupported positive factors were withheld. Every source remains subject to strict admission, provenance, bounded-runtime and publication-mode gates.
