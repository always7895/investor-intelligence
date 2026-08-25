from __future__ import annotations

import base64
import hashlib
import hmac
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from derive_tenant_hash import derive_tenant_hash, identity_material  # noqa: E402


class TenantHashTests(unittest.TestCase):
    def test_user_identity_material_matches_worker_contract(self) -> None:
        self.assertEqual(
            identity_material("user", user_id="U-SYNTHETIC"),
            "user|U-SYNTHETIC||",
        )

    def test_group_and_room_require_their_chat_identifier(self) -> None:
        with self.assertRaises(ValueError):
            identity_material("group", user_id="U-SYNTHETIC")
        with self.assertRaises(ValueError):
            identity_material("room", user_id="U-SYNTHETIC")

    def test_hash_is_url_safe_and_matches_sha256_hmac(self) -> None:
        material = "user|U-SYNTHETIC||"
        secret = "SYNTHETIC_TENANT_SECRET"
        expected = (
            base64.urlsafe_b64encode(
                hmac.new(secret.encode(), material.encode(), hashlib.sha256).digest()
            )
            .decode()
            .rstrip("=")[:43]
        )
        value = derive_tenant_hash(material, secret)
        self.assertEqual(value, expected)
        self.assertNotIn("U-SYNTHETIC", value)
        self.assertRegex(value, r"^[A-Za-z0-9_-]{43}$")


if __name__ == "__main__":
    unittest.main()
