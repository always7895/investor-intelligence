# 目前狀態／Current status

本次操作者改要求可替換的 Q5／thinking xhigh；已完成單次開發請求及受控 Windows validation-only run34303303119（SUCCESS），目前共享 profile 已接上開發 EXE、bridge、gateway 與 Worker；依降級授權採用 thinking=false／effort=none，完整隔離 Q5 live 矩陣10次已通過（最長1890ms），另含負向、非同步與LINE格式模擬驗證。正式資料／發布驗收尚未完成，早晚更新排程仍維修暫停。登記 runner 不等於驗收，舊 Q6 證據仍屬歷史。See [Q5/model and runner migration scope](MODEL_RUNTIME_MIGRATION.md): the newly requested profile is not yet release-qualified; no new EXE or Production switch is claimed.

## 開發中全來源稽核／Public-source audit candidate

新增官方公告與股票日行情的選用本機抓取器；五個端點皆已在核准 CPython3.12.10＋鎖定 certifi 下直接 CLI 真實讀取。舊 TLS 失敗保留；未關閉憑證／hostname 驗證或降低 verify flags。GitHub Windows 回歸已通過只驗證模式；未產生發布檔案。TPEx 無成交資料保留空報價，不把紀錄數當有效價格數。完整範圍、限制與證據見[來源覆蓋](PUBLIC_SOURCE_COVERAGE.md)。

New opt-in local collection covers official announcements and equity EOD data. All five live reads succeeded using supported pinned CPython3.12.10 plus locked certifi roots. Historical TLS failures remain failures; certificate/hostname verification and default flags are intact. GitHub Windows regression passed validation-only; release artifacts and full qualification remain pending. Missing closes stay null; record counts do not equal usable quote counts. See [coverage and evidence](PUBLIC_SOURCE_COVERAGE.md).

### 正式發布 gate／Current release gates

一般候選版改走既有 receipt 綁定 FREE_RELAY 打包器，保留最終 ZIP 解壓測試與隔離安裝驗證；不再自動呼叫會刪除測試依賴並填入固定舊計數的 legacy 一般打包器。歷史腳本保留，已認證 QA 不變。Live Q&A 證據現在要求含時區的開始／完成時間、順序有效、最早開始距今不超過 24 小時；未替舊證據補上新時間。尚無合格新發布：runner 缺席、fresh exact-Q6 證據待補，本機端點觀察到 Q5，未換模型或改 preset。

Current candidates use the existing receipt-bound FREE_RELAY packager with final-ZIP tests and isolated installation, not the legacy generic packager that strips test dependencies and records fixed old counts. Historical scripts and certified QA remain unchanged. Live evidence needs ordered timezone-aware start/completion timestamps, with the start no older than 24 hours. Old receipts were not restamped. No new release is qualified: Windows runner acceptance and fresh exact-Q6 evidence remain missing; the observed endpoint advertises Q5, without any model/preset changes.

### 期權／Options

新增 TAIFEX 日行情、Alpaca indicative 本機匯入 adapters；未啟用 live feed、公共 LINE 發布或 brokerage 連線。修正來源失敗隔離、持倉容量與兩種推薦視圖不一致、日期及布林驗證。完整專案驗收仍未完成，歷史缺陷數不代表目前全面安全。

Local-export adapters now normalize TAIFEX EOD and Alpaca indicative observations. No live feed/public LINE/brokerage activation. Candidate fixes cover provider failures, capacity/recommendation-view consistency and strict review fields. Whole-project acceptance is incomplete.

See [source review / 使用說明](OPTIONS_SOURCE_REVIEW.md), [PR #37](https://github.com/always7895/investor-intelligence/pull/37), [quote-provenance blocker #38](https://github.com/always7895/investor-intelligence/issues/38), and [current audit evidence](../state/STATUS.md). The following release evidence is historical and does not qualify these changes.

## 已發布基線／Released baseline — 2026-09-06 Asia/Taipei

## 已驗證範圍／Verified scope

七欄、Q6別名、封存更新與正式切換已完成實測；不是所有未測功能／真機送達皆已驗證。最新下載與自身 source/run 身分請見 [Release](https://github.com/always7895/investor-intelligence/releases/latest)、ZIP 的 HOTFIX-REFS 與相鄰 receipts。本文記錄已完成的功能基線；後續封裝須以自身 receipts 為準。

Seven-field routing, exact Q6 identity, sealed refresh and authorized cutover are qualified. This does not certify every untested scenario or LINE-device delivery. A ZIP's own refs/receipts identify its build; the latest release is authoritative for current downloadable identity.

## 七欄／Seven fields

| 繁體中文 | English |
|---|---|
| 股票 | Ticker |
| 近2年歷史年化報酬 | Historical 2Y annualized return |
| 近6個月歷史報酬 | Historical 6M return |
| 行業別 | Industry |
| 獲利簡述 | Profit summary |
| 公司現在訂單 | Current orders |
| 未來訂單展望 | Future order outlook |

互動與排程共用20檔完整資料：四組五卡 Flex；`Top20 文字` 完整公司分組備援。缺乏證據不填造訂單數字、不提升 LIMITED；雙語欄名不代表每份來源原文已重新翻譯／驗證。

Interactive and scheduled handlers share20 complete records, four five-card carousels and a complete text fallback. Missing evidence stays unavailable. Labels do not upgrade eligibility or certify every source narrative.

## 實證／Evidence

最新正式 source／CI／SHA 見 [README](../README.md)；已發布並安裝 b5baae9 /33992169731，發布後再次下載驗證與 `gh release verify-asset` PASS。Later documentation-only commits do not change that executable identity.

- 功能切換基線／Functional baseline: `bfb4e3db75f7bb00f8dd693aca2ba178ba6f5879`, Windows CI33989794415 PASS. PS5.1/7、Python、typecheck、Worker22 files/142 tests、下載獨立驗證與安裝 PASS；後續 Windows-only／封裝修正以其新 CI 為準。
- 既有 Router／Existing Router: `127.0.0.1:8080`, max_instances=1; selected `qwen38-q6`, canonical `Qwen3.8-27B-UD-Q6_K_XL-844843d973bf`. Preset unchanged; no second model/server. 十個完整隔離 Q6 cases 最大1425.23ms；Production固定smoke2231/2097ms。
- Worker `54442104-0e1f-419c-84a9-b7c4ca63ee3f` at100%; subsequent Windows-only corrections leave Worker bytes identical. 三個舊未封存入口已無認證唯讀式空請求確認 HTTP410。
- 已安裝實際完整更新／Actual installed end-to-end refresh: `20260905T205013Z-749cc4fbd2cd`, transaction `124ed6f6603d68ea05f81e82517ae320`; FINALIZED,20 LIMITED/0 qualified. Bundle SHA256 `e870c27ab21273900aaf1c2588a2d48823dc7d95f60ca4703c174f747b467610`.
- 獨立遠端讀回／Independent remote readback:13 required objects present; actual stored report locally renders four Flex messages/20 cards/two text messages. LINE transport was not invoked by this check.
- 排程／Tasks:07:20/20:20 Taipei, canonical wrapper + explicit sealed publication, Interactive owner, IgnoreNew,100-minute limit/retries. Worker cron remains08:00/21:00. 需主機／網路可用且使用者登入；鎖定桌面可執行，登出後不保證。

## 剩餘界線／Remaining boundaries

- 已追蹤／Tracked P0/P1/P2 = **0/0/1**. Separate `InvestorDailyBriefing` has a missing target/unproven ownership and was not modified. Its historical error is not relabelled fixed.
- 正常切換後08:00/21:00送達、LINE真機排版仍待自然觀察。No extra real LINE test; mocked transport or local rendering is not device certification.
- SLSA workflow build attestation remains unavailable (HTTP404). The separate cryptographic GitHub immutable-release asset attestation passed after publication; independent published-ZIP checks also PASS. These are distinct evidence types. 廣泛 Q6文字審查仍 INCOMPLETE；窄範圍 ACK型別審查完成，不替代整體測試。
- 直接 X 原始候選仍403／UNVERIFIED；公開 Serenity 重建不是官方／私人公式，不宣稱最新本人立場。Mirrors are not independent evidence; macro/identity facts do not prove company operations.
- Freshness, provenance, digest, ordering, negative factors, optional BLS, privacy/IBKR boundaries remain enforced. Missing/stale data fails closed; no five-field fallback or fabricated data.

## 變更權限／Mutation accounting

`production_mutation_by_ci=false`. CI did not mutate Production. Separately authorized operator work installed the runtime and changed relay, Worker, fresh snapshots and refresh task definitions;08:00/21:00 cron remained unchanged. No paid activation, provider-secret rotation/upload or extra real LINE test.

以上是本次當前授權操作的事實記錄，不能作為未來 session 的授權。This record is evidence, not transferable authorization.
