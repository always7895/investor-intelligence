"""Synthetic tests for the SDK installed-byte verifier. No network: fetch_tarball
is patched and tarballs are constructed in memory. Covers the byte-comparison
logic, layout/path-safety rules, exclusion accounting, and the Windows long-path
helper."""
import base64
import hashlib
import io
import os
import sys
import tarfile
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import v213_pi_sdk_byte_verify as bv


def make_tarball(files, prefix='package'):
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode='w:gz') as tar:
        for rel, content in files.items():
            data = content.encode('utf-8') if isinstance(content, str) else content
            info = tarfile.TarInfo(name=f'{prefix}/{rel}')
            info.size = len(data)
            info.mtime = 0
            tar.addfile(info, io.BytesIO(data))
    return buf.getvalue()


def sri(blob):
    return 'sha512-' + base64.b64encode(hashlib.sha512(blob).digest()).decode()


def make_entry(blob, url='https://registry.npmjs.org/pkg/-/pkg-1.0.0.tgz'):
    return {'name': 'pkg', 'version': '1.0.0', 'resolved': url, 'integrity': sri(blob)}


def _install(tmp, key, files):
    d = tmp / key
    for rel, content in files.items():
        p = d / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(content.encode('utf-8') if isinstance(content, str) else content)
    return d


class ByteVerifyPackageTests(unittest.TestCase):
    def _run(self, key, blob, installed, lock_keys=None, url=None, entry=None):
        with tempfile.TemporaryDirectory() as t:
            tmp = Path(t)
            _install(tmp, key, installed)
            if entry is None:
                entry = make_entry(blob, url or 'https://registry.npmjs.org/pkg/-/pkg-1.0.0.tgz')
            lock_keys = lock_keys or {key}
            with patch.object(bv, 'fetch_tarball', return_value=blob):
                return bv.verify_package(key, entry, tmp, tmp, lock_keys)

    def test_pass_when_bytes_match(self):
        files = {'package.json': '{"name":"pkg"}', 'dist/index.js': 'console.log(1)'}
        r = self._run('node_modules/pkg', make_tarball(files), files)
        self.assertEqual(r['status'], 'PASS')
        self.assertEqual(r['files'], 2)

    def test_fail_missing_file(self):
        files = {'package.json': '{}', 'dist/index.js': 'x'}
        with self.assertRaisesRegex(ValueError, 'PI_INSTALLED_BYTES_MISMATCH'):
            self._run('node_modules/pkg', make_tarball(files), {'package.json': '{}'})

    def test_fail_extra_file(self):
        files = {'package.json': '{}'}
        with self.assertRaisesRegex(ValueError, 'PI_INSTALLED_BYTES_MISMATCH'):
            self._run('node_modules/pkg', make_tarball(files),
                      {'package.json': '{}', 'sneaky.js': 'x'})

    def test_fail_differing_bytes(self):
        files = {'package.json': '{}'}
        with self.assertRaisesRegex(ValueError, 'PI_INSTALLED_BYTES_MISMATCH'):
            self._run('node_modules/pkg', make_tarball(files), {'package.json': '{"t":1}'})

    def test_fail_sha_mismatch(self):
        files = {'package.json': '{}'}
        bad = make_entry(make_tarball(files))
        bad['integrity'] = 'sha512-' + base64.b64encode(b'\x00' * 64).decode()
        with tempfile.TemporaryDirectory() as t:
            tmp = Path(t)
            _install(tmp, 'node_modules/pkg', files)
            with patch.object(bv, 'fetch_tarball', return_value=make_tarball(files)):
                with self.assertRaisesRegex(ValueError, 'PI_TARBALL_SHA512_MISMATCH'):
                    bv.verify_package('node_modules/pkg', bad, tmp, tmp, {'node_modules/pkg'})

    def test_fail_non_registry_host(self):
        files = {'package.json': '{}'}
        with self.assertRaisesRegex(ValueError, 'PI_RESOLVED_HOST_INVALID'):
            self._run('node_modules/pkg', make_tarball(files), files,
                      url='https://evil.example.com/pkg.tgz')

    def test_fail_symlink_in_tarball(self):
        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode='w:gz') as tar:
            info = tarfile.TarInfo(name='package/link.js')
            info.type = tarfile.SYMTYPE
            info.linkname = 'index.js'
            tar.addfile(info)
        files = {'package.json': '{}'}
        with self.assertRaisesRegex(ValueError, 'PI_TARBALL_LINK_FORBIDDEN'):
            self._run('node_modules/pkg', buf.getvalue(), files)

    def test_fail_symlink_in_installed(self):
        files = {'package.json': '{}'}
        blob = make_tarball(files)
        with tempfile.TemporaryDirectory() as t:
            tmp = Path(t)
            d = _install(tmp, 'node_modules/pkg', files)
            try:
                os.symlink('package.json', str(d / 'link.js'))
            except OSError:
                self.skipTest('OS denies symlink creation (no elevated privilege); '
                              'tarball-side symlink rejection is covered separately')
            with patch.object(bv, 'fetch_tarball', return_value=blob):
                with self.assertRaisesRegex(ValueError, 'PI_INSTALLED_LINK_FORBIDDEN'):
                    bv.verify_package('node_modules/pkg', make_entry(blob), tmp, tmp, {'node_modules/pkg'})

    def test_atypes_style_prefix_accepted(self):
        files = {'package.json': '{}', 'index.d.ts': 'declare const x: 1'}
        r = self._run('node_modules/@types/node', make_tarball(files, prefix='node v22.19'), files)
        self.assertEqual(r['status'], 'PASS')
        self.assertEqual(r['files'], 2)

    def test_dot_slash_member_prefix_normalized(self):
        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode='w:gz') as tar:
            data = b'x'
            info = tarfile.TarInfo(name='package/./dist/index.js')
            info.size = len(data)
            info.mtime = 0
            tar.addfile(info, io.BytesIO(data))
        r = self._run('node_modules/pkg', buf.getvalue(), {'dist/index.js': 'x'})
        self.assertEqual(r['status'], 'PASS')

    def test_multi_prefix_layout_rejected(self):
        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode='w:gz') as tar:
            for name in ('package/a.js', 'other/b.js'):
                data = b'x'
                info = tarfile.TarInfo(name=name)
                info.size = len(data)
                info.mtime = 0
                tar.addfile(info, io.BytesIO(data))
        with self.assertRaisesRegex(ValueError, 'PI_TARBALL_LAYOUT_UNEXPECTED'):
            bv.tarball_files(buf.getvalue())

    def test_nested_package_and_bin_shims_excluded(self):
        key = 'node_modules/parent'
        nested_key = key + '/node_modules/child'
        files = {'package.json': '{}'}
        blob = make_tarball(files)
        with tempfile.TemporaryDirectory() as t:
            tmp = Path(t)
            parent = _install(tmp, key, files)
            _install(tmp, nested_key, {'package.json': '{}'})
            (parent / 'node_modules' / '.bin').mkdir(parents=True, exist_ok=True)
            (parent / 'node_modules' / '.bin' / 'child').write_text('shim')
            with patch.object(bv, 'fetch_tarball', return_value=blob):
                r = bv.verify_package(key, make_entry(blob), tmp, tmp, {key, nested_key})
        self.assertEqual(r['status'], 'PASS')
        self.assertEqual(r['files'], 1)
        self.assertGreaterEqual(r['npm_generated_files_excluded'], 2)

    def test_long_path_helper_windows(self):
        if os.name != 'nt':
            self.skipTest('Windows only')
        short = 'C:\\temp\\x'
        self.assertEqual(bv._long_path(short), short)
        long = 'C:\\temp\\' + 'a' * 300
        self.assertTrue(bv._long_path(long).startswith(chr(92) + chr(92) + '?' + chr(92)))


if __name__ == '__main__':
    unittest.main()
