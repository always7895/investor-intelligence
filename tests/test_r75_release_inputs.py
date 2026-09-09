import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from r75_release_inputs import REFERENCE, select_receipt


class ReleaseInputsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='r75 inputs ')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / 'repo'
        self.root.mkdir()
        self.git('init', '-q')
        (self.root / 'state').mkdir()
        (self.root / 'scripts').mkdir()
        shutil.copy2(ROOT / 'scripts/r75_release_inputs.py', self.root / 'scripts/r75_release_inputs.py')
        self.payload = b'{"synthetic_fixture":true}\n'
        self.digest = hashlib.sha256(self.payload).hexdigest()
        self.ref = {'schema_version': 1, 'receipt_path': 'state/fresh.json', 'receipt_sha256': self.digest}
        (self.root / 'state/fresh.json').write_bytes(self.payload)
        (self.root / 'state/r75-qa-live-qualification.json').write_bytes(self.payload)
        self.write_ref(self.ref)
        self.commit()

    def git(self, *args):
        return subprocess.check_output(['git', '-C', str(self.root), *args], stderr=subprocess.DEVNULL)

    def commit(self):
        self.git('add', '-A')
        self.git('-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.invalid', 'commit', '-qm', 'synthetic fixture', '--allow-empty')

    def write_ref(self, value):
        (self.root / REFERENCE).write_text(json.dumps(value), encoding='utf-8')

    def test_actual_cli_selects_committed_reference_not_newest_file(self):
        (self.root / 'state/newer.json').write_text('{}')
        result = subprocess.run([sys.executable, str(ROOT / 'scripts/r75_release_inputs.py'), '--project-root', str(self.root)], capture_output=True, check=True)
        selected = json.loads(result.stdout)
        self.assertEqual(selected['receipt_path'], 'state/fresh.json')
        self.assertEqual(selected['receipt_sha256'], self.digest)
        self.assertEqual(selected['source_commit'], self.git('rev-parse', 'HEAD').decode().strip())
        from verify_r75_qa_evidence import verify
        with self.assertRaisesRegex(ValueError, 'LIVE_GATE_NOT_PASS'):
            verify(json.loads(self.payload))  # Selection is not qualification.

    def test_legacy_default_only_when_reference_absent(self):
        (self.root / REFERENCE).unlink(); self.commit()
        self.assertEqual(select_receipt(self.root)['receipt_path'], 'state/r75-qa-live-qualification.json')
        self.write_ref(self.ref)  # untracked pointer cannot activate a fallback
        with self.assertRaises(ValueError): select_receipt(self.root)
        self.commit(); (self.root / REFERENCE).unlink()
        with self.assertRaises((ValueError, OSError)): select_receipt(self.root)

    def test_bad_reference_types_paths_hashes_and_duplicate_keys_fail(self):
        variants = [[], {**self.ref, 'schema_version': True}, {**self.ref, 'extra': 'PRIVATE_SENTINEL'},
                    {**self.ref, 'receipt_sha256': '0'*64}]
        for path in ('../private.json', 'state/../private.json', 'C:/private.json', 'state/fresh.json\n', 'state/a/b.json', None):
            variants.append({**self.ref, 'receipt_path': path})
        for value in variants:
            with self.subTest(value=value):
                self.write_ref(value); self.commit()
                with self.assertRaises(ValueError): select_receipt(self.root)
        (self.root / REFERENCE).write_text('{"schema_version":1,"schema_version":1}')
        self.commit()
        with self.assertRaisesRegex(ValueError, 'DUPLICATE'): select_receipt(self.root)

    def test_same_size_worktree_drift_untracked_and_oversized_receipts_fail(self):
        path = self.root / 'state/fresh.json'
        path.write_bytes(self.payload.replace(b'true', b'null'))
        with self.assertRaisesRegex(ValueError, 'DRIFT'): select_receipt(self.root)
        path.write_bytes(self.payload); self.git('rm', '--cached', 'state/fresh.json'); self.git('-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.invalid', 'commit', '-qm', 'remove fixture')
        with self.assertRaises(ValueError): select_receipt(self.root)
        path.write_bytes(b' '*1048577); self.ref['receipt_sha256'] = hashlib.sha256(path.read_bytes()).hexdigest()
        self.write_ref(self.ref); self.commit()
        with self.assertRaisesRegex(ValueError, 'SIZE'): select_receipt(self.root)

    def test_fresh_checkout_preserves_receipt_bytes_with_autocrlf(self):
        self.git('config', 'core.autocrlf', 'true')
        shutil.copy2(ROOT / '.gitattributes', self.root / '.gitattributes')
        payload = b'{"synthetic_fixture":true}\r\n'
        relative = 'state/r75-qa-live-synthetic.json'
        (self.root / relative).write_bytes(payload)
        self.write_ref({**self.ref, 'receipt_path': relative, 'receipt_sha256': hashlib.sha256(payload).hexdigest()})
        self.commit()
        clone = Path(self.temp.name) / 'clone'
        subprocess.run(['git', '-c', 'core.autocrlf=true', 'clone', '-q', str(self.root), str(clone)], check=True, capture_output=True)
        self.assertEqual((clone / relative).read_bytes(), payload)
        self.assertEqual(select_receipt(clone)['receipt_sha256'], hashlib.sha256(payload).hexdigest())

    def test_git_symlink_mode_is_rejected_before_reading_target(self):
        blob = self.git('rev-parse', 'HEAD:state/fresh.json')
        self.git('update-index', '--cacheinfo', '120000,' + blob.decode().strip() + ',state/fresh.json')
        self.git('-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.invalid', 'commit', '-qm', 'synthetic link mode')
        with self.assertRaisesRegex(ValueError, 'REGULAR'): select_receipt(self.root)

    @unittest.skipUnless(sys.platform == 'win32', 'native PS caller blocks')
    def test_actual_validation_and_packaging_selection_blocks(self):
        for shell in ('powershell.exe', 'pwsh.exe'):
            if not shutil.which(shell): continue
            for name in ('ci_v213_r75_free_relay_validate.ps1', 'ci_v213_r75_free_relay_package.ps1'):
                text = (ROOT / 'scripts' / name).read_text(encoding='utf-8')
                begin = text.index('    $qaInputRaw =')
                block = text[begin:text.index('    $profileArgs=@()', begin)]
                for expected in ('state/fresh.json', 'state/wrong.json'):
                    command = "$ErrorActionPreference='Stop';Set-StrictMode -Version Latest;$ProjectRoot=(Get-Location).Path;$sha=(git rev-parse HEAD).Trim();"
                    command += "$windows=[pscustomobject]@{qa_live_receipt_path='"+expected+"';qa_live_receipt_sha256='"+self.digest+"'};" + block
                    result = subprocess.run([shell, '-NoProfile', '-Command', command], cwd=self.root,
                        env={**os.environ, 'PROJECT_PYTHON': sys.executable}, capture_output=True, timeout=25)
                    should_pass = 'validate' in name or expected == 'state/fresh.json'
                    self.assertEqual(result.returncode == 0, should_pass, result.stdout + result.stderr)

    @unittest.skipUnless(sys.platform == 'win32', 'native PS output guard')
    def test_actual_packager_preserves_existing_output_and_rejects_source_child(self):
        text = (ROOT / 'scripts/ci_v213_r75_free_relay_package.ps1').read_text(encoding='utf-8')
        begin = text.index('    $OutputRoot = [IO.Path]::GetFullPath($OutputRoot)')
        block = text[begin:text.index('    $stage =', begin)]
        existing = Path(self.temp.name) / 'existing'; existing.mkdir()
        sentinel = existing / 'keep.txt'; sentinel.write_text('KEEP')
        for shell in ('powershell.exe', 'pwsh.exe'):
            if not shutil.which(shell): continue
            for target in (existing, self.root / 'new-output'):
                command = "$ErrorActionPreference='Stop';$ProjectRoot=(Get-Location).Path;$OutputRoot=$env:TEST_OUTPUT_ROOT;" + block
                result = subprocess.run([shell, '-NoProfile', '-Command', command], cwd=self.root,
                    env={**os.environ, 'TEST_OUTPUT_ROOT': str(target)}, capture_output=True, timeout=15)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(sentinel.read_text(), 'KEEP')
                self.assertFalse((self.root / 'new-output').exists())


if __name__ == '__main__': unittest.main()
