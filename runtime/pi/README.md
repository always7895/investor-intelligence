# Project-local Pi SDK lock / 專案本地 SDK 鎖定

Development input, **not a qualified standalone runtime**. SDK: `@earendil-works/pi-coding-agent@0.85.1`.

The only executed package installation was logged first and run at the outer project root with lifecycle scripts disabled:

```text
pi install -l npm:@earendil-works/pi-coding-agent@0.85.1
```

`package-lock.json` is the reachable SDK-only graph extracted from that project-local installation. It excludes unrelated coding plugins. Five upstream shrinkwrapped nested packages omitted integrity fields. Extraction initially failed closed; exact-version public npm metadata was then checked against each pinned tarball URL to supply SHA512 integrity. Source lock bytes were not rewritten. This metadata repair does **not** verify already-installed package files.

Reproduction tool: `scripts/v213_pi_sdk_lock.py`. Network enrichment is explicit (`--resolve-missing-integrity`), bounded, registry-only and never executes downloaded package code. Default extraction rejects missing integrity. SDK/registry/pin/graph tests live in `tests/test_v213_pi_sdk_lock.py`.

Before formal delivery, verify tarball integrity and installed bytes, preserve this exact dependency graph, run isolated startup without global SDK/owner configuration, and independently verify the Windows package. Those gates remain pending. Any further Pi package/plugin install must log and use `pi install -l ...`, never a global install.

繁中：這是待驗收的 SDK 鎖檔，不是正式安裝完成證明。缺失的完整性欄位由精確版本的公開 npm metadata 補齊，尚未證明安裝後檔案與 tarball 相同。正式交付前仍須完成檔案驗證、獨立啟動與 Windows 封裝驗收；不得複製全域 SDK 或私人設定充作交付。
