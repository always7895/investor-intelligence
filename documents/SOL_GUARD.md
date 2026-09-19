# SOL_GUARD — SoL-Pi small-session compaction guard (source-bound receipt)

Status: IMPLEMENTED in the active project-local runtime; verified; **ACCEPTED scoped** (Master ACCEPT 2026-09-19, Mapika ACCEPT .9228; pre-commit base `9cd22fe2c737a7088002941b10b8226128af8084`; pre-commit evidence below, no invented final SHA). No Production mutation, no upstream Pi patch, no reinstall, no global registration.

## Identity

- Upstream SoL-Pi base SHA (exact apply base): `bd005888b9b8a3fcdb511feb91fc27d3dfa8f2b1`
- Active PROJECT-LOCAL runtime path: `D:\Investor-Intelligence-LINE-Pi\.pi\git\github.com\NVlabs\SoL-Pi` (actual loaded stack `src/sol-pi/index.ts`; project-local `git:github.com/NVlabs/SoL-Pi` package)
- The global copy `%USERPROFILE%\.pi\agent\git\github.com\NVlabs\SoL-Pi` is a distinct physical directory and was never modified by this task.

## Hashes (SHA-256)

- Source-bound patch `patches/sol-pi-small-session-guard.patch`: `7E1F983184A88E75856194224672EDFBDBE7F1188A42EEA976024879DD45F59D` (exact copy of the audit-runtime `sol-guard.patch`; excludes the pre-existing dirty lock and scratch files)
- Runtime patched `src/sol-pi/extensions/online-context-compact/extension.ts`: `C4B9D2ABD933D4BC9A6F5B8275827FDFFCC404569E5CC81CD6E8F65F247FB06B`
- Runtime patched `src/sol-pi/extensions/online-context-compact/index.ts`: `E8C16110079986E1A306F25361E1D2AFF564158EA49CEF07B0E0C0E733D39BC3`
- Runtime root `src/sol-pi/index.ts` (unchanged): `A9CC7B4B05724A672428288381211838DAFA668BA6031D777D5FB4B912609758`
- Runtime `package-lock.json` (pre-existing dirty diff, preserved byte-identical): `9391E590BB91356ABD05DAF46355229235463241EA4942F4776AA3120703BAB4`

## Guard behavior

- Actual cause: native global Pi `compaction.keepRecentTokens=96000` vs extension economics default `20000`; Pi emits `compaction_end.errorMessage = "Compaction failed: Nothing to compact (session too small)"` BEFORE the `onError` callback, so a callback-only guard was insufficient.
- The guard reads effective native compaction settings through the public `SettingsManager` API, runs a current-branch compaction preflight (mirroring Pi's non-compactable condition) at the boundary and again at `agent_settled`, and prevents the known non-compactable `ctx.compact()` call entirely (zero `compaction_start`/`compaction_end` noise). An exact benign callback fallback remains for residual races; genuine compaction failures stay fatal; the aborted plan resumes once; no false compaction evidence or cache debt.

## Apply / verify recipe (project-local only, fail-closed)

Prerequisites: SoL-Pi checkout at the exact base `bd005888b9b8a3fcdb511feb91fc27d3dfa8f2b1`; a pre-existing dirty `package-lock.json` is allowed and must be preserved byte-identical (the patch does not touch it). `git apply --check` only proves the hunks match current worktree content; it does NOT assert base-commit identity — the exact HEAD assertion below is the base gate.

```powershell
# Apply recipe (automatic, fail-closed). Exits non-zero on any mismatch.
$Root = 'D:\Investor-Intelligence-LINE-Pi\.pi\git\github.com\NVlabs\SoL-Pi'
$Patch = 'D:\Investor-Intelligence-LINE-Pi\_workspace\source\patches\sol-pi-small-session-guard.patch'
$ExpectedHead = 'bd005888b9b8a3fcdb511feb91fc27d3dfa8f2b1'
$ExpectedPatchSha = '7E1F983184A88E75856194224672EDFBDBE7F1188A42EEA976024879DD45F59D'
Set-Location $Root
if ((git rev-parse HEAD) -ne $ExpectedHead) { throw "BASE_MISMATCH: HEAD is not $ExpectedHead" }
if ((Get-FileHash $Patch -Algorithm SHA256).Hash -ne $ExpectedPatchSha) { throw 'PATCH_HASH_MISMATCH' }
if (Select-String -Path $Patch -Pattern 'package-lock.json' -Quiet) { throw 'PATCH_TOUCHES_LOCK' }
$LockShaBefore = (Get-FileHash (Join-Path $Root 'package-lock.json') -Algorithm SHA256).Hash
if ((git apply --check --reverse $Patch) -eq 0) {
    Write-Host 'ALREADY_APPLIED: no-op (patch is exactly what is on disk)'
} else {
    if ((git apply --check $Patch) -ne 0) { throw 'APPLY_CHECK_FAILED: worktree content drift' }
    git apply $Patch
}
if ((git apply --check --reverse $Patch) -ne 0) { throw 'FINAL_REVERSE_CHECK_FAILED' }
if ((Get-FileHash (Join-Path $Root 'package-lock.json') -Algorithm SHA256).Hash -ne $LockShaBefore) { throw 'LOCK_MODIFIED' }
Write-Host 'APPLY_VERIFIED: guard on disk, dirty lock preserved'
```

After applying, reload the project Pi extensions (`/reload` in the running master; no `/new`, no reinstall, no global registration) and confirm no upstream Pi file was modified.

```powershell
# Optional manual rollback ONLY (separate command; never executed by the apply recipe above).
# Set-Location 'D:\Investor-Intelligence-LINE-Pi\.pi\git\github.com\NVlabs\SoL-Pi'
# git apply --reverse 'D:\Investor-Intelligence-LINE-Pi\_workspace\source\patches\sol-pi-small-session-guard.patch'
```

## Verification record (2026-09-19, pre-commit evidence; no final SHA claimed)

- 27/27 targeted vitest: `tests/online-context-compact.test.ts`, `online-context-compact-agent-session.test.ts`, `online-context-compact-economics.test.ts`, `online-context-compact-plan.test.ts`, `online-context-compact-state.test.ts` (Master-independently re-run 17:52 local).
- 4 checks: `tsc --noEmit` PASS; `git diff --check` PASS; post-reload runtime regression master 4/4 PASS (small-session boundary + live compaction/resume); runtime package identity unchanged (root `index.ts` SHA above).
- Independent full gates: Python full retry 1531 tests 354.932s OK skipped 3 (initial 300s tool timeout retained as a non-pass attempt), compile PASS, Worker 869 PASS / 1 skip, typecheck PASS, PS5.1/7 parse included. No deployment, no QA recertification, no release claim.
- Runtime reverse-check (`git apply --check --reverse`) PASS at the staged receipt: the patch is exactly what is on disk; patch SHA-256 `7E1F9831…` unchanged.
- Small-session evidence: 2 completed plan boundaries → 0 `compaction_start`/`compaction_end` events, 0 extension errors, 0 compaction entries, 0 reminders, `cacheDebtTokens`/`cacheDebtRepaymentTokens`/`nativeCompactionCount` = 0, bounded calls then idle. Genuine failure: exactly 1 `compaction_end` with `errorMessage` containing the real failure (not "Nothing to compact"), surfaced through the bound `onError`.
- Scratch `tests/_scratch-dbg2.test.ts` and ignored `_dbg2.log` are preserved diagnostic evidence in the runtime tree; not accepted, not committed, do not delete.
- Receipt storage: the patch is committed byte-exact with a per-path `.gitattributes` marker (`patches/sol-pi-small-session-guard.patch -text -whitespace`, same convention as the pinned-XML fixture) so no line-ending conversion occurs and unified-diff syntax is excluded from ordinary source whitespace rules; textual diff display is preserved.