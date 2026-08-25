# Formal Private Release Delivery

Investor Intelligence may produce a formal, reproducible source package for direct private delivery while the private development repository remains private.

## Distribution boundary

The formal package:

- is built only from an exact accepted `main` commit;
- contains tracked release files only and no inherited `.git` history;
- excludes owner watchlists, owner preferences, portfolios, tenant data, messages, logs, caches, reports, runner state and credentials;
- includes a ZIP, SHA-256 checksum, release manifest, SPDX SBOM and exact-head acceptance receipt;
- is labelled `private_direct_delivery`;
- does not claim that the private GitHub repository is ready to be made public;
- does not deploy Worker, LINE, KV, IBKR, models or scheduled tasks;
- does not enable billing, paid data, paid APIs or external users.

GitHub-managed pull refs may remain an external platform-retention issue even after all official branches and tags are privacy-clean. That condition blocks publication of the private development repository itself, but it does not add Git history to the clean release ZIP.

## Option-data boundary

The shared LINE design remains public-research-only. Live shared BID/ASK lookup stays unavailable until a separately reviewed source satisfies lawful automated access, sustainable free availability and display/redistribution rights. The formal package includes the deterministic manual option calculator; all user-supplied figures are labelled unverified.

## Delivery artifact

The one-day GitHub Actions artifact contains:

1. `investor-intelligence-<version>.zip`;
2. `investor-intelligence-<version>.sha256`;
3. `investor-intelligence-<version>.manifest.json`;
4. `investor-intelligence-<version>.sbom.spdx.json`;
5. `final-acceptance-receipt.json`;
6. `PRIVATE-DISTRIBUTION-NOTICE.md`.

The artifact is downloaded for delivery before expiry. Actions dependency caches are forbidden and no formal release artifact may be retained for more than one day.

## Cleanup

A valid final receipt may authorize a separate cleanup transaction, but the newest verified rollback bundle and at least one verified backup remain protected through the configured cooling-off period. Cleanup never removes the delivered release files, their checksum, manifest, SBOM or final receipt.
