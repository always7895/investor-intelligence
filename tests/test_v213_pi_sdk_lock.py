import base64
import copy
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import v213_pi_sdk_lock as lock

SRI = 'sha512-' + base64.b64encode(b'x' * 64).decode()

def entry(name, version='1.0.0'):
    return {'version': version, 'resolved': 'https://registry.npmjs.org/' + name + '/-/fixture.tgz', 'integrity': SRI}

def fixture():
    sdk = entry(lock.PROFILE['sdk_package'], lock.PROFILE['sdk_version'])
    sdk['dependencies'] = {'public-dependency': '^1.0.0'}
    return {'lockfileVersion': 3, 'packages': {'node_modules/' + lock.PROFILE['sdk_package']: sdk,
            'node_modules/public-dependency': entry('public-dependency'),
            'node_modules/unrelated-developer-plugin': entry('unrelated-developer-plugin')}}

class PiSdkLockTests(unittest.TestCase):
    def test_minimal_reachable_graph_preserves_pins(self):
        original = fixture(); before = copy.deepcopy(original)
        manifest, result = lock.extract(original)
        self.assertEqual(original, before)
        self.assertEqual(manifest['dependencies'], {lock.PROFILE['sdk_package']: lock.PROFILE['sdk_version']})
        self.assertEqual(len(result['packages']), 3)
        self.assertNotIn('node_modules/unrelated-developer-plugin', result['packages'])

    def test_missing_integrity_never_silently_passes(self):
        value = fixture(); del value['packages']['node_modules/public-dependency']['integrity']
        with self.assertRaises(ValueError): lock.extract(value)
        observed = []
        def lookup(*args): observed.append(args); return SRI
        _, result = lock.extract(value, lookup)
        self.assertEqual(observed[0][0], 'public-dependency')
        self.assertEqual(result['packages']['node_modules/public-dependency']['integrity'], SRI)
        self.assertNotIn('integrity', value['packages']['node_modules/public-dependency'])

    def test_reject_private_registry_link_and_wrong_sdk(self):
        for change in ({'resolved': 'https://example.invalid/private.tgz'}, {'link': True}, {'version': 'other'}):
            value = fixture(); value['packages']['node_modules/' + lock.PROFILE['sdk_package']].update(change)
            with self.assertRaises(ValueError): lock.extract(value)

    def test_committed_runtime_lock_has_only_qualified_registry_and_integrity(self):
        data = json.loads((ROOT / 'runtime/pi/package-lock.json').read_text(encoding='utf-8'))
        _, result = lock.extract(data)
        self.assertEqual(data, result)

    def test_live_manifest_binds_node_runner_skill_and_runtime_lock(self):
        import v213_qa_live_gate
        manifest = v213_qa_live_gate.source_manifest()
        for name in ['scripts/v213_pi_inference.mjs', 'runtime/pi/package-lock.json', 'skills/serenity-public-research/SKILL.md']:
            self.assertIn(name, manifest)

if __name__ == '__main__': unittest.main()
