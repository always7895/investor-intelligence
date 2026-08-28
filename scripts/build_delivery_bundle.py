#!/usr/bin/env python3
"""Build a deterministic outer final-delivery ZIP and SHA-256 file.

The application ZIP has its own checksum, manifest and SPDX SBOM. This helper
also binds the human-facing delivery bundle itself so the file downloaded by the
owner can be verified before any PowerShell script is executed.
"""
from __future__ import annotations

import argparse
import hashlib
import os
import re
import stat
import zipfile
from pathlib import Path

SAFE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,199}$")
ZIP_TIMESTAMP = (1980, 1, 1, 0, 0, 0)


class DeliveryBundleError(ValueError):
    """Raised when a delivery input violates the closed bundle policy."""


def _parse_input(value: str) -> tuple[str, Path]:
    if "=" not in value:
        raise DeliveryBundleError("Each --input must use ARCHIVE_NAME=LOCAL_PATH")
    archive_name, raw_path = value.split("=", 1)
    archive_name = archive_name.strip()
    raw = Path(raw_path).expanduser()
    if raw.is_symlink():
        raise DeliveryBundleError(f"Delivery input must not be a symlink: {raw}")
    path = raw.resolve()
    if not SAFE_NAME.fullmatch(archive_name):
        raise DeliveryBundleError(f"Unsafe delivery archive name: {archive_name!r}")
    if Path(archive_name).name != archive_name or "/" in archive_name or "\\" in archive_name:
        raise DeliveryBundleError(f"Delivery entries must be flat basenames: {archive_name!r}")
    if not path.is_file() or path.is_symlink():
        raise DeliveryBundleError(f"Delivery input must be a regular non-symlink file: {path}")
    return archive_name, path


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_delivery_bundle(
    *,
    output: Path,
    checksum_output: Path,
    inputs: list[tuple[str, Path]],
) -> str:
    output = output.resolve()
    checksum_output = checksum_output.resolve()
    if output == checksum_output:
        raise DeliveryBundleError("ZIP output and checksum output must be different files")
    if output.suffix.casefold() != ".zip":
        raise DeliveryBundleError("Delivery bundle output must end in .zip")
    if not inputs:
        raise DeliveryBundleError("At least one delivery input is required")

    normalized: dict[str, Path] = {}
    for archive_name, path in inputs:
        key = archive_name.casefold()
        if key in normalized:
            raise DeliveryBundleError(f"Duplicate delivery entry: {archive_name}")
        if path in {output, checksum_output}:
            raise DeliveryBundleError("Output files cannot be included as bundle inputs")
        normalized[key] = path

    output.parent.mkdir(parents=True, exist_ok=True)
    checksum_output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(output.name + ".tmp")
    temporary.unlink(missing_ok=True)

    try:
        with zipfile.ZipFile(
            temporary,
            mode="w",
            compression=zipfile.ZIP_DEFLATED,
            compresslevel=9,
            strict_timestamps=True,
        ) as archive:
            for archive_name, path in sorted(inputs, key=lambda item: item[0].casefold()):
                info = zipfile.ZipInfo(filename=archive_name, date_time=ZIP_TIMESTAMP)
                info.compress_type = zipfile.ZIP_DEFLATED
                info.create_system = 3
                info.external_attr = (stat.S_IFREG | 0o644) << 16
                info.flag_bits |= 0x800  # UTF-8 names
                archive.writestr(info, path.read_bytes(), compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)
        os.replace(temporary, output)
    finally:
        temporary.unlink(missing_ok=True)

    digest = _sha256(output)
    checksum_output.write_text(f"{digest}  {output.name}\n", encoding="ascii", newline="\n")
    return digest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--checksum-output", type=Path, required=True)
    parser.add_argument(
        "--input",
        action="append",
        default=[],
        metavar="ARCHIVE_NAME=LOCAL_PATH",
        help="Flat archive entry and source file; repeat for every delivery file.",
    )
    args = parser.parse_args()
    try:
        parsed = [_parse_input(value) for value in args.input]
        digest = build_delivery_bundle(
            output=args.output,
            checksum_output=args.checksum_output,
            inputs=parsed,
        )
    except (DeliveryBundleError, OSError, zipfile.BadZipFile) as exc:
        print(f"FINAL DELIVERY BUNDLE FAILED\n- {exc}")
        return 1
    print(
        f"FINAL DELIVERY BUNDLE PASS\n"
        f"- archive: {args.output.resolve()}\n"
        f"- checksum: {args.checksum_output.resolve()}\n"
        f"- sha256: {digest}\n"
        f"- entries: {len(parsed)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
