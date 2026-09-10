# Workspace maintenance / 工作區精簡

## Authoritative layout

- Single project home: `D:\Investor-Intelligence-LINE-Pi`.
- Source: `_workspace/source` under that home; reviewable Git commits, shared validators, one R75 release pipeline.
- Installed application: `D:\Investor-Intelligence-LINE-Pi`; changes here are not automatically source changes or qualified releases.
- Isolated review worktrees: `_workspace/review-baseline` and `_workspace/review-source-views`; preserve unmerged work and baseline provenance until integration acceptance.
- Audit runtime: `_workspace/audit-runtime`; pinned tools, live proofs and failed receipts, not a generic disposable temp directory.
- Historical backups: `_archive/history-backups`; do not rewrite old receipts to replace their historical paths.
- The former five top-level investor directories were physically relocated and Git worktree links repaired. No old-path aliases or junctions were created. Treat `_workspace` and `_archive` as non-runtime material: never recursively include them in publication or installed-runtime packaging.
- Runner folders: inspect registration, service state, executable paths and junction targets before deciding anything is obsolete.
- Router/models and unrelated projects are outside routine repository cleanup.

Prefer fewer responsibilities and reuse, not a blind reduction in file count. A compatibility wrapper, fixture, lock or historical negative test may still be an active dependency.

## Safe deletion protocol

1. Fetch Git and record HEAD, dirty state, worktree inventory and exact proposed paths. Do not absorb another writer's work.
2. Check tracked files, untracked data, package/build/test/installer references, running processes, scheduled actions and services. Inspect command lines only in memory; never log arguments or credential-bearing contents. Exclude the inspection process itself from process-reference counts.
3. Refuse junctions/symlinks and ancestor escapes. An unknown/unreadable inventory is not evidence of absence.
4. Delete only reproducible artifacts under explicit roots: e.g. untracked Python bytecode caches beneath project scripts/tests when no tests are running. Never recursively clean the drive, all temp directories, the installed application or runner workspaces while a service/job may use them.
5. Preserve signed receipts, sealed bundles, transaction journals, rollback originals, recovery material and unmerged work. Historical Markdown can be shortened at HEAD with an immutable Git-history reference; evidence JSON must not be rewritten as a success.
6. Record deleted file/byte counts and retained blockers. Run tests after code or dependency changes. Deletion itself is not a performance benchmark.

## Instruction/document architecture

- `AGENTS.md`: short engineering authority and boundaries.
- `state/STATUS.md`: bounded current acceptance, blockers and next action; history stays in Git.
- `skills/*/SKILL.md`: task routing and essential boundaries; detailed methodology in referenced files, loaded only for matching tasks.
- `README.md`: release identity. Do not duplicate mutable version tables in other documents.
- Contracts/code: authoritative schemas, field order and validation. Documentation links to them rather than maintaining divergent copies.
- Dated source observations: separate receipts/reviews, never permanent ticker recommendations in an always-loaded instruction file.

Source edits do not update the installed Pi skill or application automatically. Diff/verify installation separately; do not overwrite divergent installed instructions or activate a release merely to make the directory tree look tidy.
