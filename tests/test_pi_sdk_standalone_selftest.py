"""Hermetic tests for scripts/v213_pi_sdk_standalone_selftest.py.

The node load proof runs a real `node -e` against the synthetic unit's own
files (no network, no model); tests requiring node skip where it is absent.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))

import pi_sdk_standalone_selftest as st  # noqa: E402

MODEL = 'Qwen3.8-27B-UD-Q5_K_XL-7a1459e88548'
SDK_DIRNAME = 'pi-coding-agent'
SDK_VERSION = '0.85.1'
ENTRY_EXPORTS = 12


def sha256_of(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def build_unit(tmp: Path, export_count: int = ENTRY_EXPORTS) -> Path:
    unit = tmp / 'Sdk-Standalone-test'
    sdk = (unit / 'pi' / 'npm' / 'node_modules' / '@earendil-works' / SDK_DIRNAME)
    (sdk / 'dist').mkdir(parents=True)
    exports = ','.join(f'k{i}:{i}' for i in range(export_count))
    (sdk / 'dist' / 'index.js').write_text(f'module.exports = {{{exports}}};\n',
                                           encoding='utf-8')
    (sdk / 'package.json').write_text(
        json.dumps({'name': '@earendil-works/pi-coding-agent', 'version': SDK_VERSION}),
        encoding='utf-8')
    lock = {
        'name': 'pi-sdk',
        'lockfileVersion': 3,
        'packages': {
            '': {'dependencies': {'@earendil-works/pi-coding-agent': SDK_VERSION}},
            'node_modules/@earendil-works/pi-coding-agent': {
                'version': SDK_VERSION,
                'resolved': 'https://registry.npmjs.org/@earendil-works/pi-coding-agent'
                            f'/-/pi-coding-agent-{SDK_VERSION}.tgz',
                'integrity': 'sha512-' + 'a' * 86,
            },
        },
    }
    (unit / 'pi').mkdir(parents=True, exist_ok=True)
    (unit / 'pi' / 'package-lock.json').write_text(json.dumps(lock), encoding='utf-8')
    (unit / 'pi' / 'settings.json').write_text(json.dumps({
        'packages': ['npm:@earendil-works/pi-coding-agent@0.85.1'],
        'llamaServerUrl': 'http://127.0.0.1:8080',
        'defaultProvider': 'llama.cpp',
        'defaultModel': MODEL,
        'skills': [str(unit / 'skills' / 'demo-skill')],
        'enableSkillCommands': True,
        'defaultThinkingLevel': 'xhigh',
        'modelThinkingLevels': {f'llama.cpp/{MODEL}': 'xhigh'},
        'defaultTools': ['read', 'bash'],
    }), encoding='utf-8')
    (unit / 'pi' / 'settings.template.json').write_text(
        '{"defaultThinkingLevel": "high"}\n', encoding='utf-8')
    skill = unit / 'skills' / 'demo-skill'
    skill.mkdir(parents=True)
    (skill / 'SKILL.md').write_text(
        '---\nname: demo-skill\ndescription: A demo skill for tests.\n---\nBody\n',
        encoding='utf-8')
    files = []
    for dirpath, dirnames, filenames in os.walk(unit):
        for fn in filenames:
            p = Path(dirpath) / fn
            rel = p.relative_to(unit).as_posix()
            if rel in ('MANIFEST.json', 'SHA256SUMS.txt'):
                continue
            files.append((rel, p))
    lock_path = unit / 'pi' / 'package-lock.json'
    manifest = {
        'schema_version': 1,
        'unit': 'PI_SDK_STANDALONE',
        'sdk_version': SDK_VERSION,
        'lockfile': 'pi/package-lock.json',
        'lockfile_sha256': sha256_of(lock_path),
        'lockfile_package_count': 1,
        'node_modules_file_count': 2,
        'unit_file_count': len(files),
        'secrets_included': False,
    }
    (unit / 'MANIFEST.json').write_text(json.dumps(manifest), encoding='utf-8')
    with open(unit / 'SHA256SUMS.txt', 'w', encoding='utf-8') as f:
        for rel, p in files:
            f.write(f'{sha256_of(p)}  {rel}\n')
    return unit


class StandaloneSelfTestToolTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix='ii-sdk-selftest-')
        self.tmp = Path(self._tmp.name)
        self.unit = build_unit(self.tmp)
        self.lock = json.loads(
            (self.unit / 'pi' / 'package-lock.json').read_text(encoding='utf-8'))

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _require_node(self) -> None:
        if shutil.which('node') is None:
            self.skipTest('node runtime not available')

    def _run_checks(self, unit) -> dict:
        node = shutil.which('node')
        checks = {
            'unit_layout': st.check_unit_layout(unit),
            'settings_audit': st.check_settings_audit(unit),
            'sha256sums': st.check_sha256sums(unit),
            'manifest': st.check_manifest(unit, self.lock),
            'node_load_proof': st.check_node_load_proof(unit, self.lock, node),
        }
        return checks

    def test_valid_unit_passes_all_checks(self) -> None:
        self._require_node()
        checks = self._run_checks(self.unit)
        for name, r in checks.items():
            self.assertEqual(r.get('errors', []), [], name)
        self.assertEqual(checks['settings_audit']['model'], MODEL)
        self.assertEqual(checks['node_load_proof']['version'], SDK_VERSION)
        self.assertEqual(checks['node_load_proof']['export_count'], ENTRY_EXPORTS)

    def test_secret_like_key_fails_closed(self) -> None:
        s = json.loads((self.unit / 'pi' / 'settings.json').read_text(encoding='utf-8'))
        s['lineChannelAccessToken'] = 'fixed-marker-not-a-real-secret'
        (self.unit / 'pi' / 'settings.json').write_text(json.dumps(s), encoding='utf-8')
        r = st.check_settings_audit(self.unit)
        self.assertTrue(any('secret-like key' in e for e in r['errors']))

    def test_secret_like_value_fails_closed(self) -> None:
        s = json.loads((self.unit / 'pi' / 'settings.json').read_text(encoding='utf-8'))
        s['note'] = 'ghp_' + 'A1' * 20
        (self.unit / 'pi' / 'settings.json').write_text(json.dumps(s), encoding='utf-8')
        r = st.check_settings_audit(self.unit)
        self.assertTrue(any('secret-like value' in e for e in r['errors']))

    def test_non_canonical_model_fails_closed(self) -> None:
        s = json.loads((self.unit / 'pi' / 'settings.json').read_text(encoding='utf-8'))
        s['defaultModel'] = 'qwen38-q5'
        (self.unit / 'pi' / 'settings.json').write_text(json.dumps(s), encoding='utf-8')
        r = st.check_settings_audit(self.unit)
        self.assertTrue(any('exact canonical model ID' in e for e in r['errors']))

    def test_non_localhost_router_fails_closed(self) -> None:
        s = json.loads((self.unit / 'pi' / 'settings.json').read_text(encoding='utf-8'))
        s['llamaServerUrl'] = 'http://10.0.0.5:8080'
        (self.unit / 'pi' / 'settings.json').write_text(json.dumps(s), encoding='utf-8')
        r = st.check_settings_audit(self.unit)
        self.assertTrue(any('localhost' in e for e in r['errors']))

    def test_skill_without_frontmatter_fails_closed(self) -> None:
        (self.unit / 'skills' / 'demo-skill' / 'SKILL.md').write_text(
            'no frontmatter here\n', encoding='utf-8')
        r = st.check_settings_audit(self.unit)
        self.assertTrue(any('frontmatter invalid' in e for e in r['errors']))

    def test_corrupted_file_fails_sha256sums(self) -> None:
        target = self.unit / 'pi' / 'settings.template.json'
        target.write_text(target.read_text(encoding='utf-8') + 'tampered\n',
                          encoding='utf-8')
        r = st.check_sha256sums(self.unit)
        self.assertTrue(any('sha256 mismatch' in e for e in r['errors']))

    def test_missing_listed_file_fails_sha256sums(self) -> None:
        (self.unit / 'pi' / 'settings.template.json').unlink()
        r = st.check_sha256sums(self.unit)
        self.assertTrue(any('listed file missing' in e for e in r['errors']))

    def test_manifest_lock_hash_mismatch_fails(self) -> None:
        p = self.unit / 'pi' / 'package-lock.json'
        p.write_text(p.read_text(encoding='utf-8') + ' ', encoding='utf-8')
        r = st.check_manifest(self.unit, self.lock)
        self.assertTrue(any('lockfile_sha256' in e for e in r['errors']))

    def test_symlink_in_node_modules_fails_inventory(self) -> None:
        link = self.unit / 'pi' / 'npm' / 'node_modules' / 'evil-link'
        try:
            link.symlink_to(self.unit / 'pi' / 'npm' / 'node_modules' / '@earendil-works')
        except OSError:
            self.skipTest('symlink creation requires privileges on this host')
        try:
            with self.assertRaises(ValueError):
                st.inventory(self.unit / 'pi' / 'npm' / 'node_modules')
        finally:
            link.unlink()

    def test_node_proof_version_mismatch_fails(self) -> None:
        self._require_node()
        p = self.unit / 'pi' / 'npm' / 'node_modules' / '@earendil-works' / SDK_DIRNAME \
            / 'package.json'
        data = json.loads(p.read_text(encoding='utf-8'))
        data['version'] = '9.9.9'
        p.write_text(json.dumps(data), encoding='utf-8')
        r = st.check_node_load_proof(self.unit, self.lock, shutil.which('node'))
        self.assertTrue(any('version' in e for e in r['errors']))

    def test_node_proof_suspicious_exports_fails(self) -> None:
        self._require_node()
        small = build_unit(self.tmp / 'small', export_count=2)
        small_lock = json.loads(
            (small / 'pi' / 'package-lock.json').read_text(encoding='utf-8'))
        r = st.check_node_load_proof(small, small_lock, shutil.which('node'))
        self.assertTrue(any('export' in e for e in r['errors']))

    def test_node_absent_fails(self) -> None:
        r = st.check_node_load_proof(self.unit, self.lock, None)
        self.assertTrue(any('node runtime not found' in e for e in r['errors']))

    def test_copy_fidelity_detects_missing_and_extra(self) -> None:
        src_root = self.tmp / 'src-install'
        (src_root / 'node_modules' / 'pkg-x').mkdir(parents=True)
        (src_root / 'node_modules' / 'pkg-x' / 'a.js').write_text('same\n',
                                                                  encoding='utf-8')
        (self.unit / 'pi' / 'npm' / 'node_modules' / 'pkg-x').mkdir(parents=True)
        (self.unit / 'pi' / 'npm' / 'node_modules' / 'pkg-x' / 'a.js').write_text(
            'same\n', encoding='utf-8')
        (self.unit / 'pi' / 'npm' / 'node_modules' / 'pkg-x' / 'extra.js').write_text(
            'extra\n', encoding='utf-8')
        r = st.check_copy_fidelity(self.unit, src_root)
        self.assertTrue(any('extra files' in e for e in r['errors']))
        (src_root / 'node_modules' / 'pkg-x' / 'only-src.js').write_text('s\n',
                                                                         encoding='utf-8')
        r = st.check_copy_fidelity(self.unit, src_root)
        self.assertTrue(any('missing from unit' in e for e in r['errors']))


if __name__ == '__main__':
    unittest.main()
