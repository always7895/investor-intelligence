# Investor Intelligence R75 權威來源目錄｜Authoritative Source Catalog

_Last reconciled / 最後核對：2026-09-05 Asia/Taipei_

[文件索引](README.md)｜[最新正式發布](FINAL_RELEASE.md)｜[Global source federation](GLOBAL_SOURCE_FEDERATION.md)

## 目的｜Purpose

本目錄是 R75 public-only 研究與來源治理的規劃基礎。它可以持續擴充，沒有固定來源數量上限，但每次執行仍受到權限、零成本、隱私、schema、健康、request、response-byte、wall-time、retry 與 per-host concurrency 預算限制。

> **Catalog membership 不等於 runtime activation。** 來源出現在目錄中，只代表它可被規劃、審查或作為候選；未通過全部 admission gate 前，不得影響正式分數或報告。

## 目前 inventory snapshot

R75 目前正式 source-planning inventory 為：

```text
catalog_count = 101
```

101 是目前快照，不是上限。新增來源的目的必須是補足真實 evidence gap 或提高韌性，不能只為增加數字。

最新已驗證的實機來源聯邦結果：

```text
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

當免費 non-Yahoo market corroboration 不可用時，系統將該缺口明確披露、限制信心並把不受支持的正向敏感因子歸零；不會把來源中斷轉成零值，也不會把 LIMITED 靜默升級成 HIGH。

## 來源類型｜Source families

目錄可包含：

- 證券監管機關與法定申報系統；
- 受監管交易所與官方公告系統；
- 中央銀行、財政部、國庫與政府統計機構；
- 國際組織、多邊機構與官方開放資料；
- 公司 investor-relations、正式 filing 與官方 press release；
- 法院、專利、採購、貿易、制裁與產業監管資料；
- 合法且免費的 regulated-market／market-infrastructure observations；
- 具透明出處的 secondary corroboration／discovery leads；
- 經相同 admission process 審查的新來源。

不因網域看似官方、搜尋排名高、社群引用多或內容熱門而自動信任。

## Trust tiers

### T0／T1 — Primary direct authority

Regulator filing、exchange announcement、central-bank release、government statistic、court/patent record、issuer filing 或 official company release，可支持其權限範圍內的直接事實。

Primary source 並不自動支持因果推論、投資結論或高信心 thesis。

### T2 — Regulated／institutional corroboration

受監管 market infrastructure、國際組織、標準機構、學術 repository 或透明 attribution 的 institutional source，可作為獨立 corroboration。

### T3 — Public market observation／secondary lead

公開 market convenience、reputable publication 或 aggregator 可作 discovery/secondary context，但不能取代 material company claim 的 primary evidence。

Yahoo/yfinance 只能作 T3 seed／public market observation，不是 authoritative evidence，也不得成為唯一 methodology。

### Quarantined／disabled

Forum、匿名內容、SEO farm、copied/unsourced content、schema 不穩、權利不明、付費限制或健康失敗的來源不得影響 scoring、recommendation 或 factual report。

## Runtime admission lifecycle

```text
DISCOVERED
  -> IDENTITY_VERIFIED
  -> AUTHORITY_SCOPE_REVIEWED
  -> LEGAL_AND_FREE_ACCESS_APPROVED
  -> SCHEMA_AND_ADAPTER_VALIDATED
  -> PRIVACY_AND_PROVENANCE_VALIDATED
  -> PARSER_CANARY_PASS
  -> HEALTH_SOAK_PASS
  -> RUNTIME_ENABLED
```

任一 gate 失敗時，來源必須進入 `QUARANTINED` 或對應的 `DISABLED_*` 狀態。

必要條件至少包括：

1. authority scope reviewed；
2. exact endpoint access/rights reviewed；
3. free access 或明確 optional free credential；
4. response schema reviewed；
5. privacy boundary reviewed；
6. statically reviewed adapter 與 fixture tests；
7. runtime health/probation；
8. provenance 完整；
9. redistribution/display boundary 清楚；
10. paid fallback 不可到達。

Automatic discovery 可以新增 disabled candidate metadata，但不得：

- 自動 enable endpoint；
- 執行 remote code；
- 安裝未審查 plugin；
- bypass paywall／CAPTCHA／robots/access control；
- 購買方案；
- 使用 owner private entitlement 作為 public feed。

## Finite runtime planning

每次 run 以 operational budget 限制，而不是以目錄總數硬切：

- total request budget；
- total response-byte budget；
- wall-clock budget；
- per-host request/concurrency ceiling；
- bounded retry/backoff；
- circuit breaker；
- source-specific quota；
- cache TTL/freshness；
- required free credential availability。

超出預算時 defer，不增加無限制 traffic，也不自動升級付費方案。

## Provenance record

正式 observation 至少應保留：

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

Model-generated summary 永遠不能當作 source evidence。

## Claim verification

### 直接官方事實

有效的 primary record 可在其法定/官方權限內支持 filing value、policy rate、employment figure、exchange announcement 等直接事實。

### Material interpretation

Material interpretation 至少需要：

- 一個 claim-relevant primary source 加獨立 corroboration；或
- 兩個可追溯到 original material 的獨立 institutional sources。

### Conflicting evidence

系統不平均矛盾事實，依序優先：

1. corrected/restated primary source；
2. current primary source；
3. official exchange/regulator mirror；
4. independent institutional corroboration；
5. reputable secondary coverage。

仍無法解決時，必須披露 conflict，且 disputed field 不得驅動自動 score change。

## R75 publication-mode integration

來源目錄與 scoring 之間有 publication contract：

```text
EVIDENCE_QUALIFIED
LIMITED_RESEARCH_CANDIDATE
```

- `EVIDENCE_QUALIFIED` 需要 strict claim-level evidence／independence／freshness。
- `LIMITED_RESEARCH_CANDIDATE` 必須有 primary evidence 與獨立 publication provenance，但 confidence 限制為 LIMITED。
- LIMITED 不得 validated thesis、不得 HIGH eligible、不得保留 unsupported positive sensitive factors。
- BLS 是 optional macro context；必要來源家族、domain 與 claim independence 門檻仍 fail closed。

## Zero-cost 與隱私邊界

Required source 不得要求：

- paid API key；
- premium subscription；
- 可自動轉付費的信用卡流程；
- paywall/login/CAPTCHA bypass；
- prohibited scraping；
- paid market-data package。

目錄只含 public-source metadata，不得包含：

- raw LINE ID/message；
- user query history/watchlist；
- owner holding/cost/P&L/margin/account ID；
- IBKR session/account response；
- tenant memory/private report；
- Cloudflare、LINE、GitHub、HMAC 或 Gateway secrets。

## 相關檔案｜Files

- `config/authoritative-source-catalog.json`
- `config/authoritative-sources/*.json`
- `schemas/authoritative-source-catalog.schema.json`
- `scripts/authoritative_source_catalog.py`
- `tests/test_authoritative_source_catalog.py`

## English summary

The current R75 source-planning inventory contains 101 records and has no fixed ceiling. Catalog membership never implies runtime activation. Every source must pass authority, legal/free-access, schema, privacy, provenance, adapter and health gates. The latest verified run used seven source families and six official families with 100% ticker coverage; unavailable free non-Yahoo market corroboration was disclosed and confidence-capped rather than fabricated.
