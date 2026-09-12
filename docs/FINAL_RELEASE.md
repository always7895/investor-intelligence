# Release and installation / 正式交付與安裝

[Released identity](../README.md) · [Current acceptance](../state/STATUS.md) · [Release gates](FINAL_RELEASE_PLAN.md)

1. Obtain the immutable ZIP and its adjacent refs/receipts from the release identified in README. Verify the external SHA256 before extraction. Never overwrite a prior release or borrow another ZIP's qualification.
2. Use `install-v213-source-diverse-runtime.ps1` only for the qualified package and intended runtime root. The historical default was `%LOCALAPPDATA%\InvestorIntelligence\V213Runtime`; the consolidated workspace also has a distinct installed root. Inspect the actual caller/target rather than assume an old shortcut identifies it.
3. Read the [workspace boundary](WORKSPACE_MAINTENANCE.md). Do not install over the development checkout, include `_workspace` / `_archive` as payload, or replay an old activation.
4. Prepare locked Worker dependencies as required by that package's installer; [dependency instructions](DEPENDENCY_LOCKING.md). The current coordinator's isolated regression requires `cloud/node_modules` when supplied by the source toolchain. Root node_modules and mutable caches are different ownership classes; do not blindly remove every directory with the same name.
5. Verify the complete installed dependency chain, metadata, actual EXE and scheduled actions independently. Installation metadata is not model selection or live release qualification. Keep rollback originals and failure journals.

**安裝程式碼不等於授權部署、發布、註冊／啟動排程或傳送真實LINE。**
Code installation does not authorize Production operations. CI remains `production_mutation_by_ci=false`.

Operational schedules, actual delivery observations and outstanding acceptance belong in STATUS, not a duplicated PASS table here. Interactive-owner operation requires the owner logged in and PC/network available; locked desktop is not the same as logged-out acceptance.

The historical release's separate GitHub release-asset attestation is not SLSA workflow build provenance. Full prior record: `git show 4ba2a606c9e459884e15354aa91798ec432df0ba:docs/FINAL_RELEASE.md`.
