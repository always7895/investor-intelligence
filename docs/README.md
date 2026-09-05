# Investor Intelligence 文件索引｜Documentation index

## 目前正式文件｜Current authoritative documents

1. [主 README／Main README](../README.md)
2. [繁體中文完整使用說明](../README.zh-TW.md)
3. [R75 FREE_RELAY 最終正式發布](FINAL_RELEASE.md)
4. [R75 FREE_RELAY 架構與路由租約](V213_FREE_WORKERS_RELAY.md)
5. [目前實作狀態](../IMPLEMENTATION_STATUS.md)
6. [正式上線與交付證據](../state/FINAL_DELIVERY_REPORT_R75_FREE_RELAY.md)
7. [詳細專案狀態](../state/STATUS.md)
8. [營運、維護與下一版 release gate](FINAL_RELEASE_PLAN.md)

## 目前正式版本｜Current release

```text
Version：v2.1.3 R75 FREE_RELAY
Tag：v2.1.3-R75-free-relay-final-92c97f9-33896931576
Release source：92c97f97694e6e39c7a16986630d248c9ee744fe
Windows CI：33896931576 / PASS
ZIP SHA-256：8b29e6b7ad6237042824e4c6af3a9b9cc16ea8a9e716b51fdfa8aca2c7da56ec
Production Worker：27121388-1e6e-445a-b45e-104a867ca70d / 100%
Stable entrypoint：https://investor-intelligence-v21-owner-line.moon951753.workers.dev
Exact model：qwen38-q6
Custom domain：not required
P0/P1/P2：0/0/0
```

## 歷史文件｜Historical documents

下列文件保留作為 v2.0.0／v2.1.0 開發、隱私清理、release candidate 與供應鏈稽核的歷史證據。它們不是目前的安裝、部署或 Production authority：

- `CANONICAL_RELEASE_CANDIDATE_V2.md`
- `FORMAL_PRIVATE_RELEASE.md`
- `FINAL_CLEANUP_POLICY.md`
- `GIT_HISTORY_PRIVACY_GATES.md`
- 舊 Phase、v2.0.0、v2.1.0 與 R70 規劃文件

歷史文件中的 commit、SHA、workflow、安裝路徑和「尚未部署」狀態只描述當時版本，不能套用到 R75 FREE_RELAY。

## 技術參考｜Technical references

仍可作為目前架構背景參考，但遇到版本衝突時，以 R75 current documents 為準：

- [Authoritative source catalog](AUTHORITATIVE_SOURCE_CATALOG.md)
- [Global source federation](GLOBAL_SOURCE_FEDERATION.md)
- [Dependency locking](DEPENDENCY_LOCKING.md)
- [KV deployment preflight](KV_DEPLOYMENT_PREFLIGHT.md)
- [KV namespace isolation](KV_NAMESPACE_ISOLATION.md)
- [LINE Bot Q&A implementation](LINE_BOT_QA_IMPLEMENTATION.md)
- [IBKR read-only boundary](IBKR_READ_ONLY.md)

## 文件維護規則｜Documentation maintenance

每次新的正式版都必須同步更新：

- Repository description 與 homepage；
- latest Release title/body；
- `README.md` 與 `README.zh-TW.md`；
- `IMPLEMENTATION_STATUS.md`；
- `docs/FINAL_RELEASE.md`；
- current architecture 文件；
- 所有 open Issue／PR tracker；
- 歷史文件的 superseded 標示。

不可變 release 的歷史內容不得覆寫；新版本應建立新的唯一 tag／release，並在 current docs 中明確指出最新 authority。
