# Git History 隱私閘門｜Git-history privacy gates

[文件索引](README.md)｜[最新正式發布](FINAL_RELEASE.md)

本文件說明目前仍適用的 Git history、current-tree 與 release-evidence 隱私規則。舊 v2.0.0 的 Support purge 已完成；目前 R75 FREE_RELAY 的正式 release 與 main 文件更新仍必須遵守同一套「不輸出敏感內容、exact commit 綁定、不可把舊 PASS 套到新 HEAD」原則。

## 目前正式狀態

```text
Current release：v2.1.3 R75 FREE_RELAY
Release source：92c97f97694e6e39c7a16986630d248c9ee744fe
Windows CI：33896931576 / PASS
Immutable tag：v2.1.3-R75-free-relay-final-92c97f9-33896931576
Release ZIP SHA-256：8b29e6b7ad6237042824e4c6af3a9b9cc16ea8a9e716b51fdfa8aca2c7da56ec
Current repository visibility：private
Current-tree security scan：PASS
P0/P1/P2：0/0/0
```

## 非破壞性 inventory｜Non-destructive inventory

History/privacy inventory 可以掃描可見 refs 與 current tree，但報告只能記錄：

- stable finding code；
- object prefix；
- one-way locator hash；
- finding count；
- pass/fail 狀態。

不得輸出：

- matched secret/content；
- raw filesystem path；
- raw e-mail address；
- raw LINE ID/message/reply token；
- Cloudflare／GitHub／HMAC／Gateway credential；
- brokerage/account/holding data。

Inventory 本身不得 rewrite history、force-push、rotate credentials、deploy Worker、寫 Production state 或發 LINE。

## Exact-head 規則

- 每一個驗證結果都必須綁定 exact commit。
- 舊 commit 的 PASS 不可轉移到新的 HEAD。
- documentation-only commit 仍需 current-tree security scan。
- release artifact、receipt、MANIFEST、SHA256SUMS 與 SBOM 必須綁定相同 source commit 和 workflow run。
- 正式不可變 Release 的 assets 不可被替換；若程式有變更，必須建立新的唯一 tag/release。

## R75 release privacy evidence

R75 authoritative run 與 post-download verification 已證明：

- ZIP path safety、duplicate、symlink checks PASS；
- MANIFEST 與 SHA256SUMS PASS；
- SBOM 與 receipts 身份一致；
- current-tree credential scan PASS；
- release 不包含現用 secret；
- `production_mutation_by_ci=false`；
- `cloud/src/qa.ts` 與認證基準 byte-identical；
- FREE_RELAY transport integration 未改寫 Serenity/publication semantics。

## Current-tree 敏感資料規則

任何 branch、PR、Issue、README、release note、workflow summary 或 log 都不得包含：

- API token、OAuth token、HMAC secret、Gateway secret；
- Cloudflare tunnel credential 或 secret material；
- LINE channel secret/access token/reply token/raw user ID；
- GitHub personal token；
- IBKR account ID、持股、成本、損益、margin、buying power；
- owner private watchlist/preferences/report；
- ephemeral TryCloudflare hostname 作為公開固定入口；
- 本機使用者目錄中的私人檔案內容。

範例值必須使用明確 synthetic placeholder，不能看似真實 credential。

## 證據的隱私｜Privacy of evidence

所有自動化報告必須保持：

```text
matched_content_in_report = false
raw_paths_in_report = false
raw_email_addresses_in_report = false
secret_values_in_report = false
owner_financial_data_in_report = false
```

必要時可以記錄經遮罩的 PID、port、version ID、commit、workflow run、finding code 與 one-way hash，但不可記錄秘密值。

## 歷史清理與保留

- 已完成的歷史 privacy purge 保留其 PASS 結論與 audit metadata。
- 不再需要重做日常 force-push 或歷史改寫。
- Historical issues/PRs 可加上「已由 R75 取代」的文字，但不刪除歷史討論。
- 最新 verified rollback bundle、不可變 Release、正式 receipts 與至少一份可重驗 evidence 必須保留。
- GitHub-managed `refs/pull/*` 只能稽核，不可由普通 workflow 當作 branch 刪除。

## 觸發重新 remediation 的條件

只有在發現下列情況時，才進入新的 remediation transaction：

1. 可存取 ref 中出現真實 secret／私人資料；
2. 正式 release asset 含不應存在的 private content；
3. current tree security scan 出現有效 finding；
4. release identity、checksum 或 receipt 不一致；
5. 新 branch 將敏感內容推至 GitHub；
6. credential 已暴露，需要 rotate/revoke。

處理順序：先 revoke/rotate，再 preserve evidence、清理 current tree，最後在備份與明確授權下處理 history。不能以刪除報告或隱藏 finding 代替 remediation。

## English summary

The v2.0.0 history purge is complete, but exact-head and privacy gates remain active for R75 and future changes. Inventories may expose only stable finding metadata, never matched content, raw paths, e-mail addresses, secrets or financial data. A PASS is commit-specific and immutable release assets cannot be replaced.
