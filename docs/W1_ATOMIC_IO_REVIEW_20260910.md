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

## GitHub scope

The diagnostic test fixtures/helpers and this review can be committed independently. They do not require the untracked coordinator in their default regression modes. The unaccepted four-installer/coordinator draft and working-tree boundary-test changes remain explicitly outside that diagnostic-only commit. Updating GitHub does not mean build, install, publication or LINE delivery has passed.
