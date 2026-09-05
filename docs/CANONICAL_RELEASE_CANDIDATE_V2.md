# 歷史文件：Canonical Release Candidate v2

> **已由 Investor Intelligence v2.1.3 R75 FREE_RELAY 不可變正式版取代。**
>
> 目前正式文件：[主 README](../README.md)｜[繁體中文說明](../README.zh-TW.md)｜[最終正式發布](FINAL_RELEASE.md)

## 目前正式權威

```text
Version：v2.1.3 R75 FREE_RELAY
Release tag：v2.1.3-R75-free-relay-final-92c97f9-33896931576
Release source：92c97f97694e6e39c7a16986630d248c9ee744fe
Windows CI：33896931576 / PASS
ZIP SHA-256：8b29e6b7ad6237042824e4c6af3a9b9cc16ea8a9e716b51fdfa8aca2c7da56ec
Production Worker：27121388-1e6e-445a-b45e-104a867ca70d / 100%
Stable entrypoint：workers.dev
Custom domain required：false
P0/P1/P2：0/0/0
```

本文件原本描述 stacked development line 的「非部署 release candidate checkpoint」。該階段已完成並被後續 R75 hardening、FREE_RELAY、權威 Windows CI、不可變 GitHub Release、真實 Worker deploy、route/heartbeat、Task Scheduler 與端到端 smoke 證據取代。

## 歷史驗收原則

當時的候選版本要求同一個 exact combined head 通過：

1. current-tree privacy 與 credential scan；
2. LINE public-only 與 LINE-to-IBKR separation；
3. public／tenant-private／ephemeral-security state isolation；
4. closed public schemas 與 cross-tenant/deletion-race tests；
5. source catalog／adapter admission gates；
6. hash-locked Python 與 `pip check`；
7. npm lock、TypeScript 與 Worker tests；
8. public report、recovery、scheduling、fault/clean-install tests；
9. reproducible package、checksum、manifest、SBOM；
10. release status fail-closed。

這些原則已納入後續正式 release gate，但本文件中的 branch、workflow、版本與「尚未部署」敘述只代表當時歷史狀態，不得再當作目前 Production 指令。

## Current English notice

This is an archived release-candidate document. It is not the current installation or production authority. The current verified release is **Investor Intelligence v2.1.3 R75 FREE_RELAY**, with immutable tag `v2.1.3-R75-free-relay-final-92c97f9-33896931576`.
