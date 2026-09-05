"""Exercise forwarding only, against synthetic canonical scripts, never Production."""
import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PAIRS = (
    ('run-v213-local-source-diverse.ps1', 'run-v213-local.ps1',
     ['-ProjectRoot', 'synthetic root (1)', '-Model', 'qwen38-q6', '-NoSync', '-NoAutoActivation'],
     '@{root=$ProjectRoot; model=$Model; no_sync=[bool]$NoSync; no_activation=[bool]$NoAutoActivation}',
     {'root':'synthetic root (1)', 'model':'qwen38-q6', 'no_sync':True, 'no_activation':True}),
    ('activate-v213-seven-field-schedule-serenity-latest.ps1', 'activate-v213-diversified-schedule.ps1',
     ['-FieldLocale','bilingual','-PreflightOnly'],
     '@{locale=$FieldLocale; preflight=[bool]$PreflightOnly; confirm=[bool]$ConfirmActivation}',
     {'locale':'bilingual', 'preflight':True, 'confirm':False}),
)

def parameters(path):
    text = path.read_text(encoding='utf-8-sig')
    return text[:text.index('\n)\n')+3]

class CompatibilityEntrypointTests(unittest.TestCase):
    def test_installers_never_overlay_a_forwarder_onto_its_canonical_target(self):
        for name in ('install-v213-runtime.ps1', 'install-v213-source-diverse-runtime-v2.ps1'):
            text = (ROOT / name).read_text(encoding='utf-8-sig')
            self.assertNotRegex(text, r"'run-v213-local-source-diverse\.ps1'\s*=\s*'run-v213-local\.ps1'")
        installer = (ROOT / 'install-v213-runtime.ps1').read_text(encoding='utf-8-sig')
        self.assertIn('The canonical stable refresh pipeline order is invalid', installer)
        self.assertIn('source-independence gate', installer)

    def test_parameter_contracts_are_identical(self):
        for alias, canonical, *_ in PAIRS:
            self.assertEqual(parameters(ROOT/alias), parameters(ROOT/canonical))
            self.assertLess(len((ROOT/alias).read_text(encoding='utf-8').splitlines()), 30)

    def test_ps51_and_ps7_forward_switches_paths_and_exit_codes_without_running_product(self):
        shells = [shutil.which(s) for s in ('powershell.exe','pwsh')]
        if not all(shells): self.skipTest('Both Windows PowerShell5.1 and PowerShell7 required')
        for shell in shells:
            for alias, canonical, args, expression, expected in PAIRS:
                with self.subTest(shell=shell, alias=alias), tempfile.TemporaryDirectory() as temp:
                    folder = Path(temp)/'版本 (1) space'
                    folder.mkdir()
                    shutil.copyfile(ROOT/alias, folder/alias)
                    stub = parameters(ROOT/canonical) + '\n[Console]::OutputEncoding = [Text.UTF8Encoding]::new($false)\n' + expression + ' | ConvertTo-Json -Compress\nexit 37\n'
                    (folder/canonical).write_text(stub, encoding='utf-8')
                    result = subprocess.run([shell,'-NoProfile','-NonInteractive','-File',str(folder/alias),*args], capture_output=True, encoding='utf-8', errors='strict', timeout=20)
                    self.assertEqual(result.returncode, 37, result.stderr)
                    self.assertEqual(json.loads(result.stdout), expected)

if __name__ == '__main__':
    unittest.main()
