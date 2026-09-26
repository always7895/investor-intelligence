import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class SecureCredentialStoreTests(unittest.TestCase):

    @unittest.skipUnless(os.name == 'nt', 'Windows native Credential Manager required')
    def test_compiled_exe_credential_store_self_test(self):
        compiler = Path(os.environ['WINDIR']) / 'Microsoft.NET/Framework64/v4.0.30319/csc.exe'
        self.assertTrue(compiler.is_file(), f'csc.exe not found at {compiler}')
        source = ROOT / 'launcher/InvestorIntelligenceLauncher.cs'
        self.assertTrue(source.is_file(), f'Launcher source not found at {source}')
        store = ROOT / 'launcher/SecureCredentialStore.cs'
        self.assertTrue(store.is_file(), f'Credential store module not found at {store}')

        with tempfile.TemporaryDirectory(prefix='SecureCredTest_') as directory:
            stage = Path(directory)
            exe = stage / 'InvestorIntelligence.exe'
            compile_args = [
                str(compiler),
                '/nologo',
                '/target:winexe',
                '/platform:anycpu',
                '/reference:System.dll',
                '/reference:System.Core.dll',
                '/reference:System.Drawing.dll',
                '/reference:System.Windows.Forms.dll',
                '/reference:System.Web.Extensions.dll',
                f'/out:{exe}',
                str(source),
                str(store),
            ]
            result = subprocess.run(compile_args, capture_output=True, text=True, timeout=45)
            self.assertEqual(result.returncode, 0, f'csc compilation failed:\n{result.stderr}\n{result.stdout}')

            # Compilation diagnostics must not include credentials
            self.assertNotIn('secret', result.stdout.lower())
            self.assertNotIn('secret', result.stderr.lower())

            # Run only new self-test with timeout, asserts exit 0 and no payload in stdout/stderr
            test_run = subprocess.run(
                [str(exe), '--credential-store-self-test'],
                capture_output=True,
                text=True,
                timeout=30,
            )
            self.assertEqual(
                test_run.returncode,
                0,
                f'Credential store self-test failed with code {test_run.returncode}.\nSTDOUT: {test_run.stdout}\nSTDERR: {test_run.stderr}',
            )
            self.assertIn('INVESTOR_INTELLIGENCE_SECURE_STORE_SELF_TEST=PASS', test_run.stdout)

            # Assert no sensitive/payload leakage in stdout/stderr
            combined_output = test_run.stdout + test_run.stderr
            self.assertNotIn('LINE_CHANNEL_SECRET=', combined_output)
            self.assertNotIn('LINE_CHANNEL_ACCESS_TOKEN=', combined_output)
            self.assertNotIn('CLOUDFLARE_API_TOKEN=', combined_output)
            self.assertNotIn('GITHUB_TOKEN=', combined_output)
            self.assertNotIn('ALPHAVANTAGE_API_KEY=', combined_output)

            # Exact sole argument check: extra arguments must not trigger self-test
            extra_arg_run = subprocess.run(
                [str(exe), '--credential-store-self-test', 'unexpected-extra'],
                capture_output=True,
                text=True,
                timeout=15,
            )
            self.assertNotEqual(extra_arg_run.returncode, 0)
            self.assertNotIn('INVESTOR_INTELLIGENCE_SECURE_STORE_SELF_TEST=PASS', extra_arg_run.stdout)

    def test_source_contract_security_boundaries(self):
        launcher_path = ROOT / 'launcher/InvestorIntelligenceLauncher.cs'
        store_path = ROOT / 'launcher/SecureCredentialStore.cs'
        self.assertTrue(store_path.is_file(), f'Credential store module not found at {store_path}')
        # The credential manager now lives in its own module so the distributed
        # launcher stays a local PowerShell bridge; assertions apply to both.
        source = launcher_path.read_text(encoding='utf-8') + '\n' + store_path.read_text(encoding='utf-8')

        # No vault enumeration allowed
        self.assertNotIn('CredEnumerate', source)
        self.assertNotIn('CredEnumerateW', source)
        self.assertNotIn('CredEnumerateA', source)

        # advapi32 P/Invoke APIs
        self.assertIn('CredWriteW', source)
        self.assertIn('CredReadW', source)
        self.assertIn('CredDeleteW', source)
        self.assertIn('CredFree', source)

        # Struct layout and constants
        self.assertIn('CRED_TYPE_GENERIC', source)
        self.assertIn('CRED_PERSIST_LOCAL_MACHINE', source)
        self.assertIn('CharSet.Unicode', source)

        # Exact service allowlist
        for service in [
            'LINE_CHANNEL_ACCESS_TOKEN',
            'LINE_CHANNEL_SECRET',
            'CLOUDFLARE_API_TOKEN',
            'GITHUB_TOKEN',
            'ALPHAVANTAGE_API_KEY',
        ]:
            self.assertIn(service, source)

        # Production and synthetic prefixes
        self.assertIn('InvestorIntelligence/V1/', source)
        self.assertIn('InvestorIntelligence/Synthetic/', source)

        # Memory zeroing and unmanaged free boundaries
        self.assertIn('Array.Clear', source)
        self.assertIn('ZeroNativeMemory', source)
        self.assertIn('Marshal.FreeHGlobal', source)

        # Callback exposure and documented limits (not a false zero-copy claim)
        self.assertIn('Managed memory / OS limits', source)

        # Nonempty and length validation <= 2560 bytes
        self.assertIn('2560', source)

        # Flag routing
        self.assertIn('--credential-store-self-test', source)


if __name__ == '__main__':
    unittest.main()
