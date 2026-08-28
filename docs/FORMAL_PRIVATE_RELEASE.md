# Formal Private Final Release Delivery

Investor Intelligence v2.0.0 is delivered as a reproducible, no-Git-history final package while the development repository remains private.

## Distribution boundary

The final package:

- is built only from an exact `main` commit accepted by both final workflows;
- is released only after GitHub Support removed the affected pull-request internal references and unreferenced commits;
- contains tracked release files only and no inherited `.git` history;
- excludes owner watchlists, owner preferences, portfolios, tenant data, messages, logs, caches, reports, runner state and credentials;
- includes an application ZIP, application SHA-256, release manifest, SPDX SBOM and exact-head final acceptance receipt;
- is labelled `private_direct_delivery` and is a final application release, not a development RC;
- does not deploy Worker, LINE, KV, IBKR, models or scheduled tasks;
- does not enable billing, paid data, paid APIs or external users.

Repository visibility is independent from application-release readiness.

## Installer boundary

The direct-delivery bundle includes `install-final.cmd` and `install-final.ps1`. The CMD wrapper provides a double-click path; the PowerShell installer verifies the application ZIP against its SHA-256 before extraction and delegates to package-contained `bootstrap.ps1`.

The bootstrap refuses runner workspaces, installs under `%LOCALAPPDATA%`, uses verified portable CPython 3.12.10, installs only binary official-index hash-locked dependencies, runs `pip check` and distribution-safe tests, preserves generated local output during explicit reinstall, and keeps every external integration disabled.

## Option-data boundary

The shared LINE design remains public-research-only. Live shared BID/ASK lookup stays unavailable until a separately reviewed source satisfies lawful automated access, sustainable free availability and display/redistribution rights. The deterministic manual option calculator labels all supplied figures unverified.

## Exact evidence

The one-day GitHub Actions formal evidence artifact contains the exact application ZIP, application SHA-256, manifest, SPDX SBOM, final acceptance receipt and private-distribution notice. The separate history workflow proves the Support purge and all-object clean state on the same source SHA.

For direct delivery, the accepted application evidence is combined with `install-final.ps1`, `install-final.cmd` and a final notice by the tested deterministic outer-bundle builder. The outer bundle is built twice, byte-compared and bound to a separate SHA-256 before delivery. Actions dependency caches remain forbidden.

## Cleanup

A valid final receipt authorizes only allowlisted transient cleanup. The newest verified rollback bundle and at least one verified backup remain protected through the configured cooling-off period. Cleanup never removes delivered release files, checksum, manifest, SBOM or final receipt.
