# Final cleanup and rollback-retention policy

This repository treats cleanup as a **post-release transaction**, not as a development convenience. The user has authorized removal of unnecessary backups and generated files after the final version is complete, but that authorization does not waive release gates or rollback safety.

## Locked during development

`config/final-cleanup-policy.json` is intentionally locked. The retained `scripts/final_cleanup_gate.py` validates policy and receipt documents only; it contains no deletion implementation. Development workflows must not remove the verified history backup, rewrite Git refs, delete GitHub-managed pull refs, clear release evidence or touch local private configuration.

## Required final receipt

A later one-time cleanup transaction must present an exact, closed-schema receipt bound to the final candidate commit and tree. The receipt must prove all of the following:

- final release state is ready while deployment, billing and external-user admission remain false;
- rewritten history passes `--scope all --require-clean`;
- a fresh clone from GitHub passes canonical acceptance;
- clean-install, reproducible package, manifest, checksum and SPDX SBOM gates pass;
- cleanup is explicitly authorized for that exact candidate.

A receipt from another branch, an earlier commit or a partial workflow is invalid.

## Repository-generated files eligible for cleanup

After receipt validation, a separate reviewed maintenance transaction may remove only the closed repository-relative allowlist: transient virtual environments, npm cache, `cloud/node_modules`, generated public cache/history and reports. It must refuse absolute paths, parent traversal, symlink escapes and any path outside the reviewed repository root.

Source, tests, documentation, configuration, schemas, Git metadata and final release evidence are protected.

## Offline history backups

History backups remain preserved until the final candidate has passed post-rewrite fresh-clone acceptance and the minimum cooling-off period. Cleanup must use an explicit backup root, a content-free inventory and verified backup markers. It must retain the newest verified rollback bundle and at least one verified backup. Unverified or ambiguous directories are never deleted automatically.

The final ZIP, SHA-256 checksum, release manifest, SPDX SBOM, final acceptance receipt and newest verified rollback bundle remain protected evidence.

## Git and GitHub cleanup

Obsolete branches may be removed only from an explicit inventory after the final receipt is accepted. `main`, the finalization branch and release-prefixed refs are protected. GitHub-managed `refs/pull/*` are platform-owned and read-only to repository workflows; they must be audited separately and never treated as ordinary deletable branches.

## Current state

Cleanup is locked. No backup or repository file is deleted merely because this policy exists. The later destructive transaction must first pass the read-only gate with `--require-unlocked`, perform a dry-run inventory, and then operate only on the approved allowlist.
