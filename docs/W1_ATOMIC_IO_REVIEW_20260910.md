# W1 atomic IO / ACL review — diagnostic scope only

## Finding

The original helper's existing-file branch passed an ordinary PowerShell `$null` to the string backup-name parameter of `File.Replace`. The source-bound B3 probe failed on PS5.1 and PS7 with inner `ArgumentException`, HResult `-2147024809`. New-file writes were not the same failing branch.

The first typed-null comparison wrote the requested bytes but failed its exact-SDDL check. That original failure remains valid evidence. It did not prove a permissions expansion, nor was it acceptable to ignore an unexplained descriptor change.

## New isolated evidence

`audit-runtime/w1-acl-followup-20260910-a/acl-decomposition.json` records both native hosts. Each uses new non-secret fixtures; neither full coordinator nor installed runtime is invoked.

| Case | Owner / group / ordered DACL bytes | Control flags | Original backup |
|---|---|---|---|
| Inherited, ignore-metadata-errors=true | Unchanged | 32772 → 33796, XOR1024 | None |
| Inherited, strict metadata errors | Unchanged | Same addition | None |
| Protected DACL, strict | Unchanged | Exactly unchanged | None |
| Explicit backup path, strict | Unchanged | Same addition on new target | Original descriptor exactly unchanged |

The differing bit is `SE_DACL_AUTO_INHERITED` (0x0400). DACL bytes and ACE order, not merely formatted account names, were compared. Raw security descriptors, principal identifiers and ACE bytes are not logged. SACL was not requested: this evidence does NOT certify audit/integrity policy, alternate streams, file identity, recovery after interruption or arbitrary filesystems.

Microsoft documents that ReplaceFile preserves DACLs and that the resulting target has the replacement file's identity; backup/replaced/replacement files must share a volume. Its security-descriptor documentation defines the auto-inherited flag. These references explain the measured marker transition, not blanket permission to ignore flags:

- https://learn.microsoft.com/en-us/windows/win32/api/winbase/nf-winbase-replacefilew
- https://learn.microsoft.com/en-us/windows/win32/secauthz/security-descriptor-control

## Narrow comparison rule and negative coverage

The test-only comparator requires non-null owner/group/DACL, exact owner/group, exact ordered DACL binary data and unchanged resource-manager control. All control bits must match, except addition (never removal) of 0x0400. It does not sort ACEs or treat arbitrary SDDL differences as equivalent.

Twelve synthetic comparator cases run on both hosts: exact match, documented marker addition, marker removal, owner/group changes, rights expansion, added deny ACE, ACE reordering, protection change, ACE inheritance change, null-vs-empty DACL and null-DACL admission. Only the first two are accepted. The native regression also checks strict metadata-error handling, protected ACLs and exact original-backup descriptor preservation.

The old exact-SDDL observation is still false for inherited targets. The new result is a separately scoped access-metadata comparison, not a restamped old PASS. This is a proposed diagnostic classification, NOT an approved production ACL-normalization rule. Future inheritance behavior remains untested; current DACL equality alone does not prove all permission semantics equivalent. Do not use it to admit unknown ACL types, unsupported storage, untrusted ownership or unobserved SACL semantics.

## Implementation boundary

No production coordinator fix is certified here. A reviewed transaction should use explicit transaction-bound originals/backup references and strict metadata-error handling, then verify actual target/backup identity and bytes. It must not select the newest backup, discard original metadata, or use live copy/restore fallback. A file replacement primitive is not full crash recovery or a consumer barrier.

W1 still needs trusted archive/ownership admission, shared participant locks, durable journal/originals, reader isolation, all four real callers and restart/finalize negatives. The mixed installed root must not be swapped or automatically adopted. Full Python/native/Windows acceptance and fresh source-bound release proof remain prerequisites to shipping.

## Follow-up: recovery, inheritance, identity and streams

Evidence: `audit-runtime/w1-metadata-followup-a/`. The diagnostic baseline contains seven AST-selected definitions from the unchanged coordinator (original SHA above). It is a frozen UNACCEPTED fixture, not replacement production code. Its normalized-LF SHA is `68956b7d64467be25acdcc26c7a4780b9b45e50a0f7228accd4e21e61a63d275`; default tests do not depend on an untracked coordinator.

Both hosts reproduce two additional recovery defects:

- `Restore-V213Metadata` returns false when the original file (including an empty original) is already unchanged. This is not a verified recovery failure requiring an overwrite.
- With an originally absent file, a third-party directory at that pathname returns true. A non-leaf object is not equivalent to absence. The synthetic directory/sentinel survives, but the reported recovery success is wrong.

The journal sequence independently reproduces LOCKED creation succeeding, then both PREPARED and ROLLED_BACK updates failing with inner ArgumentException. This supports a double-failure mechanism; missing historical full-install journals still prevent claiming the sole historical cause.

Native replacement/parent-ACL tests on both hosts show:

- The new target uses the replacement file identity; backup retains the original identity and OLD bytes.
- Original/replacement named streams are present in the resulting target; the original stream remains in backup. This does not admit arbitrary streams or hardlinks into a runtime manifest.
- After a deliberate parent ACL update, inherited target DACLs match the unreplaced control and change together; protected controls/targets remain unchanged.
- **An inherited backup's descriptor changes with that parent update.** Therefore a backup alone is not an immutable ACL-original record. The protected fixture's backup descriptor remains equal. This does not authorize protecting an operator's existing ACL or dropping inheritance.

A passive `GetNamedSecurityInfoW` SACL query on a new PS5.1 fixture returns Win32 **1314**. Receipt is BLOCKED, SACL presence is null/unknown, CLI exits2; PS7 capability retry was not attempted. No privilege was enabled, no elevation/policy change was made, and no real runtime metadata was read. SACL qualification remains blocked pending explicit narrowly scoped authorization and B3/Astra review; no production ACL-normalization or IO patch is approved by these tests.

The first auxiliary PS5.1 parse driver failed (no product body); a new assigned-array driver parsed both hosts. First two inheritance attempts failed; the second's bounded receipt identifies `CREATE_STREAMS` / NotSupportedException (`-2146233067`). Replacing only the fixture's legacy .NET ADS path operations with Win32 handles, on the same verified local NTFS scope, preserves the stream oracle. Final three diagnostic methods pass across both hosts; frozen baseline failures remain failures, not installer acceptance. Original helper temporary-file cleanup still exists in that frozen baseline.

## GitHub scope

The diagnostic test fixtures/helpers and this review can be committed independently. They do not require the untracked coordinator in their default regression modes. The unaccepted four-installer/coordinator draft and working-tree boundary-test changes remain explicitly outside that diagnostic-only commit. Updating GitHub does not mean build, install, publication or LINE delivery has passed.
