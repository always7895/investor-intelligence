# 正式修正版與安裝 / Published hotfix and installation

**範圍提醒 / Scope:** 已發布版仍有五／七欄入口不一致；新修正尚未交付。 / The published ZIP still has five/seven-field routing inconsistency; its fix is not yet delivered. [中英狀態 / Bilingual status](CURRENT_STATUS_BILINGUAL.md).

Use the [current verified identity, checksum and measurements](../README.md) and [latest immutable GitHub release](https://github.com/always7895/investor-intelligence/releases/latest). Do not use an older dated release document as the current installer source.

Download the ZIP plus checksum, verify SHA256, extract, then execute `install-v213-source-diverse-runtime.ps1`. The stable runtime is `%LOCALAPPDATA%\InvestorIntelligence\V213Runtime`; launch `InvestorIntelligence.exe` there.

Installation is separate from data activation. This Q&A/readiness hotfix was installed and its Worker code/relay cut over under current-session authorization; it did not resubmit the sealed bundle or change the existing snapshot,08:00/21:00 jobs or LINE recipients. CI remains no-Production-mutation.

Evidence includes Windows, live-Q&A, deployment, delivery, independent download, historical exact-bundle and local-install receipts. See [final delivery report](../state/FINAL_DELIVERY_REPORT_R75_FREE_RELAY.md). Historical release documentation is retained in Git and the older immutable releases.
