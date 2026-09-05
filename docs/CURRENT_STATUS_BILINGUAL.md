# 目前狀態／Current status — 2026-09-06 Asia/Taipei

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

- 功能切換基線／Functional baseline: `bfb4e3db75f7bb00f8dd693aca2ba178ba6f5879`, Windows CI33989794415 PASS. PS5.1/7、Python、typecheck、Worker22 files/142 tests、下載獨立驗證與安裝 PASS；後續 Windows-only／封裝修正以其新 CI 為準。
- 既有 Router／Existing Router: `127.0.0.1:8080`, max_instances=1; selected `qwen38-q6`, canonical `Qwen3.8-27B-UD-Q6_K_XL-844843d973bf`. Preset unchanged; no second model/server. 十個完整隔離 Q6 cases 最大1425.23ms；Production固定smoke2231/2097ms。
- Worker `54442104-0e1f-419c-84a9-b7c4ca63ee3f` at100%; subsequent Windows-only corrections leave Worker bytes identical. 三個舊未封存入口已無認證唯讀式空請求確認 HTTP410。
- 已安裝實際完整更新／Actual installed end-to-end refresh: `20260905T205013Z-749cc4fbd2cd`, transaction `124ed6f6603d68ea05f81e82517ae320`; FINALIZED,20 LIMITED/0 qualified. Bundle SHA256 `e870c27ab21273900aaf1c2588a2d48823dc7d95f60ca4703c174f747b467610`.
- 獨立遠端讀回／Independent remote readback:13 required objects present; actual stored report locally renders four Flex messages/20 cards/two text messages. LINE transport was not invoked by this check.
- 排程／Tasks:07:20/20:20 Taipei, canonical wrapper + explicit sealed publication, Interactive owner, IgnoreNew,100-minute limit/retries. Worker cron remains08:00/21:00. 需主機／網路可用且使用者登入；鎖定桌面可執行，登出後不保證。

## 剩餘界線／Remaining boundaries

- 已追蹤／Tracked P0/P1/P2 = **0/0/1**. Separate `InvestorDailyBriefing` has a missing target/unproven ownership and was not modified. Its historical error is not relabelled fixed.
- 正常切換後08:00/21:00送達、LINE真機排版仍待自然觀察。No extra real LINE test; mocked transport or local rendering is not device certification.
- GitHub artifact attestation is not produced by this workflow. Independent ZIP checks PASS, but no attested claim. 廣泛 Q6文字審查仍 INCOMPLETE；窄範圍 ACK型別審查完成，不替代整體測試。
- 直接 X 原始候選仍403／UNVERIFIED；公開 Serenity 重建不是官方／私人公式，不宣稱最新本人立場。Mirrors are not independent evidence; macro/identity facts do not prove company operations.
- Freshness, provenance, digest, ordering, negative factors, optional BLS, privacy/IBKR boundaries remain enforced. Missing/stale data fails closed; no five-field fallback or fabricated data.

## 變更權限／Mutation accounting

`production_mutation_by_ci=false`. CI did not mutate Production. Separately authorized operator work installed the runtime and changed relay, Worker, fresh snapshots and refresh task definitions;08:00/21:00 cron remained unchanged. No paid activation, provider-secret rotation/upload or extra real LINE test.

以上是本次當前授權操作的事實記錄，不能作為未來 session 的授權。This record is evidence, not transferable authorization.
