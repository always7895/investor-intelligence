from __future__ import annotations

import hashlib
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import build_delivery_bundle as builder  # noqa: E402


class DeliveryBundleTests(unittest.TestCase):
    def test_two_builds_are_byte_identical_and_checksum_bound(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            first = root / "first.txt"
            second = root / "second.txt"
            first.write_text("alpha\n", encoding="utf-8")
            second.write_bytes(b"beta\x00\xff")
            inputs = [("B.txt", second), ("a.txt", first)]

            out_one = root / "one.zip"
            sum_one = root / "one.sha256"
            out_two = root / "two.zip"
            sum_two = root / "two.sha256"
            digest_one = builder.build_delivery_bundle(
                output=out_one,
                checksum_output=sum_one,
                inputs=inputs,
            )
            digest_two = builder.build_delivery_bundle(
                output=out_two,
                checksum_output=sum_two,
                inputs=inputs,
            )
            self.assertEqual(out_one.read_bytes(), out_two.read_bytes())
            self.assertEqual(digest_one, digest_two)
            self.assertEqual(digest_one, hashlib.sha256(out_one.read_bytes()).hexdigest())
            self.assertEqual(sum_one.read_text(encoding="ascii"), f"{digest_one}  one.zip\n")
            with zipfile.ZipFile(out_one) as archive:
                self.assertEqual(archive.namelist(), ["a.txt", "B.txt"])
                self.assertEqual(archive.read("a.txt"), b"alpha\n")
                self.assertEqual(archive.getinfo("a.txt").date_time, builder.ZIP_TIMESTAMP)

    def test_rejects_traversal_duplicates_symlinks_and_output_recursion(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source.txt"
            source.write_text("value", encoding="utf-8")
            with self.assertRaises(builder.DeliveryBundleError):
                builder._parse_input(f"../escape={source}")
            with self.assertRaises(builder.DeliveryBundleError):
                builder.build_delivery_bundle(
                    output=root / "bundle.zip",
                    checksum_output=root / "bundle.sha256",
                    inputs=[("A.txt", source), ("a.TXT", source)],
                )
            with self.assertRaises(builder.DeliveryBundleError):
                builder.build_delivery_bundle(
                    output=source,
                    checksum_output=root / "bundle.sha256",
                    inputs=[("source.txt", source)],
                )
            link = root / "link.txt"
            try:
                link.symlink_to(source)
            except OSError:
                self.skipTest("Symlink creation is unavailable")
            with self.assertRaises(builder.DeliveryBundleError):
                builder._parse_input(f"link.txt={link}")


if __name__ == "__main__":
    unittest.main()
