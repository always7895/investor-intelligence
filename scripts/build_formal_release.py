#!/usr/bin/env python3
"""Build the non-synthetic formal package from an ephemeral accepted status.

This wrapper never deploys, installs credentials, enables LINE/IBKR or writes to
GitHub. The status path must be generated only after the exact checked-out head
passes the retained final gates.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from release_package import ReleasePackageError, build_release_package


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--release-status", type=Path, required=True)
    args = parser.parse_args()
    try:
        outputs = build_release_package(
            output_dir=args.output_dir,
            version=args.version,
            synthetic=False,
            release_status_path=args.release_status,
        )
    except (FileNotFoundError, ReleasePackageError, OSError, ValueError) as exc:
        print(f"FORMAL RELEASE PACKAGE BUILD FAILED\n- {exc}")
        return 1
    print(
        json.dumps(
            {
                "archive": str(outputs.archive),
                "checksum": str(outputs.checksum),
                "manifest": str(outputs.manifest),
                "sbom": str(outputs.sbom),
                "source_commit": outputs.source_commit,
                "version": outputs.version,
                "file_count": outputs.file_count,
                "archive_sha256": outputs.archive_sha256,
                "synthetic": False,
                "distribution_scope": "private_direct_delivery",
                "public_repository_publication_ready": False,
                "deployment_performed": False,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
