# Canonical release candidate acceptance v2

This document defines the non-deploying integration checkpoint for the stacked development line.

A candidate is not release-ready merely because individual feature branches passed at different commits. The exact combined head must pass, in one immutable revision:

1. current-tree privacy and credential scanning;
2. shared LINE public-only and LINE-to-IBKR separation;
3. separate public, tenant-private and ephemeral-security KV bindings;
4. closed public artifact schemas and cross-tenant/deletion-race tests;
5. authoritative-source catalog and adapter admission gates;
6. isolated, binary-only, hash-locked Python installation plus `pip check`;
7. committed npm lock, lifecycle-script-free `npm ci`, TypeScript and Worker tests;
8. Phase 4 public-report, Phase 7 recovery/scheduling and Phase 8 fault/clean-install tests;
9. reproducible package, checksum, manifest and SBOM verification;
10. release status remaining fail-closed.

The canonical integration branch and Draft PR are validation surfaces only. They do not deploy a Worker, configure LINE, connect IBKR, expose the local model, install credentials, enable paid services, rewrite Git history or publish a final release.
