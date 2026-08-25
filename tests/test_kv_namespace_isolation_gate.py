from __future__ import annotations

import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from kv_namespace_isolation_gate import audit_kv_isolation  # noqa: E402


class KvNamespaceIsolationGateTests(unittest.TestCase):
    def test_repository_passes_three_namespace_gate(self) -> None:
        self.assertEqual(audit_kv_isolation(), [])

    def fixture_root(self) -> tuple[tempfile.TemporaryDirectory[str], Path]:
        temporary = tempfile.TemporaryDirectory()
        root = Path(temporary.name)
        for relative in (
            "config/kv-namespace-policy.json",
            "cloud/wrangler.toml",
            "cloud/src/storage.ts",
            "cloud/src/line.ts",
            "cloud/src/worker.ts",
            "cloud/test/storage.test.ts",
            "cloud/test/line.test.ts",
            "cloud/test/qa.test.ts",
        ):
            target = root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(ROOT / relative, target)
        return temporary, root

    def test_rejects_same_namespace_ids_and_legacy_binding(self) -> None:
        temporary, root = self.fixture_root()
        try:
            wrangler = (root / "cloud/wrangler.toml").read_text(encoding="utf-8")
            wrangler = wrangler.replace(
                "REPLACE_WITH_TENANT_PRIVATE_PRODUCTION_KV_NAMESPACE_ID",
                "REPLACE_WITH_PUBLIC_PRODUCTION_KV_NAMESPACE_ID",
            ).replace(
                'binding = "EPHEMERAL_SECURITY_CACHE"',
                'binding = "CACHE"',
            )
            (root / "cloud/wrangler.toml").write_text(wrangler, encoding="utf-8")
            findings = audit_kv_isolation(root)
        finally:
            temporary.cleanup()
        self.assertTrue(any("production namespace IDs must be distinct" in item for item in findings))
        self.assertTrue(any("KV bindings must be exactly" in item for item in findings))

    def test_rejects_public_reads_from_private_namespace(self) -> None:
        temporary, root = self.fixture_root()
        try:
            path = root / "cloud/src/storage.ts"
            text = path.read_text(encoding="utf-8")
            text = text.replace(
                "const value = await env.PUBLIC_CACHE.get<T>(key, \"json\");",
                "const value = await env.TENANT_PRIVATE_CACHE.get<T>(key, \"json\");",
            )
            path.write_text(text, encoding="utf-8")
            findings = audit_kv_isolation(root)
        finally:
            temporary.cleanup()
        self.assertTrue(any("public read path touches tenant-private KV" in item for item in findings))

    def test_rejects_memory_enabled_by_default_and_generic_private_api(self) -> None:
        temporary, root = self.fixture_root()
        try:
            wrangler_path = root / "cloud/wrangler.toml"
            wrangler_path.write_text(
                wrangler_path.read_text(encoding="utf-8").replace(
                    'MEMORY_FEATURE_AVAILABLE = "false"',
                    'MEMORY_FEATURE_AVAILABLE = "true"',
                ),
                encoding="utf-8",
            )
            storage_path = root / "cloud/src/storage.ts"
            storage_path.write_text(
                storage_path.read_text(encoding="utf-8")
                + "\nexport async function putPrivateJson() {}\n",
                encoding="utf-8",
            )
            findings = audit_kv_isolation(root)
        finally:
            temporary.cleanup()
        self.assertTrue(any("MEMORY_FEATURE_AVAILABLE" in item for item in findings))
        self.assertTrue(any("generic private JSON APIs" in item for item in findings))

    def test_policy_must_remain_fail_closed(self) -> None:
        temporary, root = self.fixture_root()
        try:
            policy_path = root / "config/kv-namespace-policy.json"
            policy = json.loads(policy_path.read_text(encoding="utf-8"))
            policy["same_namespace_id_forbidden"] = False
            policy_path.write_text(json.dumps(policy), encoding="utf-8")
            findings = audit_kv_isolation(root)
        finally:
            temporary.cleanup()
        self.assertTrue(any("same_namespace_id_forbidden" in item for item in findings))


if __name__ == "__main__":
    unittest.main()
