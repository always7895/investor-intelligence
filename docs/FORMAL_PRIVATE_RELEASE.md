# 歷史文件：Formal Private Release v2.0.0

> **此文件只保留 v2.0.0 私人交付的歷史稽核內容，已由 v2.1.3 R75 FREE_RELAY 不可變正式版取代。**
>
> 目前正式文件：[主 README](../README.md)｜[繁體中文完整說明](../README.zh-TW.md)｜[R75 最終正式發布](FINAL_RELEASE.md)

## 目前正式權威

```text
Current version：v2.1.3 R75 FREE_RELAY
Immutable tag：v2.1.3-R75-free-relay-final-92c97f9-33896931576
Release source：92c97f97694e6e39c7a16986630d248c9ee744fe
Windows CI：33896931576 / PASS
ZIP SHA-256：8b29e6b7ad6237042824e4c6af3a9b9cc16ea8a9e716b51fdfa8aca2c7da56ec
Production Worker：27121388-1e6e-445a-b45e-104a867ca70d / 100%
Stable entrypoint：https://investor-intelligence-v21-owner-line.moon951753.workers.dev
Exact model：qwen38-q6
Custom domain required：false
P0/P1/P2：0/0/0
```

## v2.0.0 歷史交付邊界

v2.0.0 當時採 reproducible、無 Git history 的私人直接交付，並強調：

- exact `main` commit 與正式 workflow 綁定；
- package 不包含 `.git` history；
- 排除 owner watchlist、portfolio、tenant data、messages、logs、cache、reports、runner state 與 credentials；
- 包含 application ZIP、SHA-256、manifest、SPDX SBOM 與 acceptance receipt；
- 當時不部署 Worker、LINE、KV、IBKR、模型或排程；
- 不啟用 billing、paid data、paid API 或 external users。

這些內容只描述 v2.0.0 的交付狀態。R75 FREE_RELAY 現在已完成 separate operator-authorized Production Worker deploy、真實 route、heartbeat、Task Scheduler 與端到端 smoke，但仍保留 public-only、secret exclusion、free-only 與 no-broker-write 邊界。

## 目前與歷史版本的主要差異

| 項目 | v2.0.0 歷史狀態 | v2.1.3 R75 目前狀態 |
|---|---|---|
| Production Worker | 未部署 | `27121388-1e6e-445a-b45e-104a867ca70d` 100% active |
| Local model route | 無正式 route | FREE_RELAY + exact `qwen38-q6` |
| Stable entrypoint | 無正式 Production authority | 既有 `workers.dev` |
| Custom domain | 不適用 | 不需要 |
| Reconnect | 無 | at-logon task + heartbeat |
| CI tests | v2.0 gates | Python 550/2、Worker 19/113、PS 5.1/7 |
| Release protection | 私人直接交付 | GitHub Immutable Release + attested assets |
| Defects | 當時狀態 | P0/P1/P2 = 0/0/0 |

## 歷史 installer 注意事項

本文件過去提到的 `install-final.cmd`、`install-final.ps1`、`App\2.0.0` 與 v2.0.0 SHA 不得再用於 R75。最新版請從目前不可變 Release 下載 R75 FREE_RELAY ZIP，核對：

```text
8b29e6b7ad6237042824e4c6af3a9b9cc16ea8a9e716b51fdfa8aca2c7da56ec
```

並依 [繁體中文完整說明](../README.zh-TW.md) 操作。

## Current English notice

This document is retained only as a historical record of the v2.0.0 private-delivery boundary. It is not the current installation, deployment or release authority. The current immutable production release is v2.1.3 R75 FREE_RELAY.
