"""Synthetic engine/CLI output stays in owned fixtures, never default market files."""
from contextlib import ExitStack
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import v21_serenity_top20 as base
import v211_serenity_top20 as universe

SENTINEL = b'SYNTHETIC_DEFAULT_SENTINEL_DO_NOT_REPLACE'

def defaults(root):
    return [(base, key, root / name) for key, name in (
        ('TOP20_PATH', 'top20_public_latest.json'), ('PLAN_PATH', 'source_plan_public_latest.json'),
        ('METADATA_PATH', 'public_snapshot_metadata.json'), ('REPORT_PATH', 'public_briefing_latest.md'))] + [
        (universe, 'UNIVERSE_PATH', root / 'research_universe_public_latest.json'),
        (universe, 'GENERATED_SYMBOLS_PATH', root / 'line_public_symbols_generated.json')]


class SyntheticOutputIsolationTests(unittest.TestCase):
    def test_engines_refuse_default_output_before_any_provider_or_write(self):
        with tempfile.TemporaryDirectory(prefix='ii-synthetic-sentinels-') as tmp, ExitStack() as stack:
            root = Path(tmp)
            paths = defaults(root)
            for module, key, path in paths:
                path.write_bytes(SENTINEL)
                stack.enter_context(patch.object(module, key, path))
            stack.enter_context(patch.object(base, 'session', side_effect=AssertionError('PROVIDER_CALLED')))
            for module in (base, universe):
                for kwargs, reason in (({}, 'SYNTHETIC_OUTPUT_ROOT_REQUIRED'),
                                       ({'output_root': root}, 'SYNTHETIC_DEFAULT_OUTPUT_FORBIDDEN')):
                    with self.assertRaisesRegex(base.PipelineError, reason):
                        module.run(synthetic=True, **kwargs)
                with self.assertRaisesRegex(base.PipelineError, 'OUTPUT_ROOT_ONLY_FOR_SYNTHETIC'):
                    module.run(synthetic=False, output_root=root / 'elsewhere')
            for _, _, path in paths: self.assertEqual(path.read_bytes(), SENTINEL)

    def test_selftests_are_temporary_and_do_not_mutate_module_paths(self):
        with tempfile.TemporaryDirectory(prefix='ii-selftest-sentinels-') as tmp, ExitStack() as stack:
            paths = defaults(Path(tmp))
            for module, key, path in paths:
                path.write_bytes(SENTINEL)
                stack.enter_context(patch.object(module, key, path))
            base.self_test(); universe.self_test()
            for module, key, path in paths:
                self.assertEqual(getattr(module, key), path)
                self.assertEqual(path.read_bytes(), SENTINEL)

    def test_live_default_path_resolution_is_unchanged(self):
        self.assertEqual(base.public_output_paths(synthetic=False), dict(top20=base.TOP20_PATH,
            plan=base.PLAN_PATH, metadata=base.METADATA_PATH, report=base.REPORT_PATH))

    def test_coverage_wrapper_refuses_mismatched_response_paths_before_plan_io(self):
        import v211_serenity_top20_coverage_gate as coverage
        with tempfile.TemporaryDirectory(prefix='ii-output-binding-') as tmp:
            root = Path(tmp)
            for supplied in (str(root / 'unrelated.json'), None, 123):
                with patch.object(coverage, '_ORIGINAL_RUN', return_value={'source_plan_path': supplied}), \
                     patch.object(base, 'load_object') as read, patch.object(base, 'atomic_json') as write:
                    with self.assertRaisesRegex(base.PipelineError, 'OUTPUT_PATH_MISMATCH'):
                        coverage.coverage_gated_run(synthetic=True, output_root=root / 'output')
                    read.assert_not_called(); write.assert_not_called()

    def test_actual_cli_parsers_and_progress_forwarding_preserve_default_sentinels(self):
        # Patch only destinations inside the child; even a regression cannot
        # overwrite the real checkout's ignored market cache. Execute main().
        child = r'''
from pathlib import Path
import importlib, sys
sys.path.insert(0, sys.argv[1])
import v21_serenity_top20 as base
import v211_serenity_top20 as universe
root=Path(sys.argv[2])
for key,name in [('TOP20_PATH','top20_public_latest.json'),('PLAN_PATH','source_plan_public_latest.json'),
                 ('METADATA_PATH','public_snapshot_metadata.json'),('REPORT_PATH','public_briefing_latest.md')]:
    setattr(base,key,root/name)
universe.UNIVERSE_PATH=root/'research_universe_public_latest.json'
universe.GENERATED_SYMBOLS_PATH=root/'line_public_symbols_generated.json'
name=sys.argv[3]; module=importlib.import_module(name)
sys.argv=[name,*sys.argv[4:]]
raise SystemExit(module.main())
'''
        with tempfile.TemporaryDirectory(prefix='ii-engine-cli-') as tmp:
            root = Path(tmp); default = root / 'defaults'; default.mkdir()
            for _, _, path in defaults(default): path.write_bytes(SENTINEL)
            for name in ('v21_serenity_top20', 'v211_serenity_top20', 'v213_v21_progress_runner', 'v211_serenity_top20_coverage_gate'):
                output = root / name
                cases = [(['--synthetic'], 1), (['--synthetic', '--output-root', str(default)], 1),
                         (['--output-root', str(output)], 1), (['--synthetic', '--output-root', str(output)], 0)]
                if name != 'v213_v21_progress_runner': cases.append((['--self-test'], 0))
                for args, expected in cases:
                    with self.subTest(module=name, args=args):
                        run = subprocess.run([sys.executable, '-B', '-c', child, str(ROOT / 'scripts'), str(default), name, *args],
                            cwd=root, capture_output=True, timeout=45)
                        self.assertEqual(run.returncode, expected, run.stdout + run.stderr)
                        self.assertNotIn(b'Traceback', run.stderr)
                        for _, _, path in defaults(default): self.assertEqual(path.read_bytes(), SENTINEL)
                self.assertEqual(len(json.loads((output / 'top20_public_latest.json').read_text(encoding='utf-8'))), 20)


if __name__ == '__main__': unittest.main()
