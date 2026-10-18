"""Caller-level tests of the reviewed release scope generator/checker (scripts/r75_release_scope.py).

Every row drives the real command line against a synthetic Git repository (no network, no Production). The legacy lane
fails closed on any path outside a hard-coded allowlist; the successor lane must keep that property with an explicit,
generated inventory: an unlisted path, an UNREVIEWED entry, a non-ancestor baseline and a wide tail all refuse.
"""
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / 'scripts/r75_release_scope.py'
GIT = ['git', '-c', 'user.name=Synthetic', '-c', 'user.email=synthetic@example.invalid', '-c', 'commit.gpgsign=false',
       '-c', 'core.hooksPath=nonexistent-synthetic-hooks', '-c', 'core.autocrlf=false']
INVENTORY = 'state/r75-release-reviewed-scope-t1.json'
RANGES = 'state/r75-release-acceptance-ranges-t1.json'
POINTER = 'state/r75-qa-live-current.ref.json'


def isolated_git_env(**extra):
    """The environment for every Git child of a synthetic repository: no user or system Git configuration (core.autocrlf, safe.*, hooks, aliases)."""
    return {**os.environ, 'GIT_CONFIG_GLOBAL': os.devnull, 'GIT_CONFIG_NOSYSTEM': '1', **extra}


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    sys.path.insert(0, str(path.parent))
    try:
        spec.loader.exec_module(module)
    finally:
        sys.path.pop(0)
    return module


class ScopeCase(unittest.TestCase):
    def setUp(self):
        if not shutil.which('git'):
            self.skipTest('git is required')
        self.temp = tempfile.TemporaryDirectory(prefix='r75-scope-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / 'repo'
        self.root.mkdir()
        self.git('init', '-q')

    def git(self, *args):
        result = subprocess.run([*GIT, '-C', str(self.root), *args], capture_output=True, text=True, timeout=60,
                                env=isolated_git_env())
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout.strip()

    def write(self, relative, text):
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(text.encode('utf-8'))

    def commit(self, message):
        self.git('add', '-A')
        self.git('commit', '-q', '-m', message)
        return self.git('rev-parse', 'HEAD')

    def scope(self, *args):
        return subprocess.run([sys.executable, '-I', str(SCRIPT), *args], capture_output=True, text=True, timeout=120, env=isolated_git_env())

    def rng(self, rid, to, status='ACCEPTED'):
        accepted = status == 'ACCEPTED'
        return {'id': rid, 'to': to, 'status': status, 'kind': 'FABLE_INDEPENDENT_ACCEPT' if accepted else 'NONE',
                'receipt': f'R/FABLE-{rid}-INDEPENDENT-ACCEPT-CLAUDECODE-00000000.txt' if accepted else '', 'note': 'synthetic'}

    def write_ranges(self, baseline, rows):
        self.write(RANGES, json.dumps({'schema_version': 1, 'lane': 't1', 'baseline': baseline, 'ranges': rows}, indent=1) + '\n')

    def history(self, first_status='ACCEPTED'):
        """baseline, c1 (runtime change), c2 (docs + STATUS), c3 (old QA receipt + pointer); returns the shas."""
        self.write('README.md', 'base\n')
        self.write('scripts/a.py', 'print(1)\n')
        self.write('state/STATUS.md', 'status 0\n')
        base = self.commit('baseline')
        self.write('scripts/a.py', 'print(2)\n')
        self.write('cloud/src/x.ts', 'export const x = 1;\n')
        c1 = self.commit('runtime change')
        self.write('docs/D.md', 'doc\n')
        self.write('state/STATUS.md', 'status 1\n')
        c2 = self.commit('docs and status')
        self.write('state/r75-qa-live-old.json', '{"old": true}\n')
        self.write(POINTER, json.dumps({'schema_version': 1, 'receipt_path': 'state/r75-qa-live-old.json', 'receipt_sha256': '0' * 64}) + '\n')
        c3 = self.commit('old live receipt')
        self.shas = {'base': base, 'c1': c1, 'c2': c2, 'c3': c3}
        self.write_ranges(base, [self.rng('A1', c1, first_status), self.rng('A2', c3)])
        return self.shas

    def build(self, expect=0, head=None):
        result = self.scope('build', '--project-root', str(self.root), '--ranges', RANGES, '--output', INVENTORY,
                            *(['--head', head] if head else []))
        self.assertEqual(result.returncode, expect, result.stdout + result.stderr)
        return result

    def check(self, *extra):
        return self.scope('check', '--project-root', str(self.root), '--inventory', INVENTORY, '--ranges', RANGES, *extra)

    def reviewed(self):
        self.history()
        self.build()
        self.commit('reviewed scope inventory')

    def assertRefused(self, result, code):
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn('R75_RELEASE_SCOPE_REFUSED reason=' + code, result.stderr)


class ReviewedScopeTests(ScopeCase):
    def test_reviewed_scope_passes_and_reports_the_binding(self):
        self.reviewed()
        result = self.check()
        self.assertEqual(result.returncode, 0, result.stderr)
        data = json.loads(result.stdout)
        self.assertEqual((data['status'], data['baseline'], data['covered_head'], data['tail_commits']),
                         ('PASS', self.shas['base'], self.shas['c3'], 1))
        inventory = json.loads((self.root / INVENTORY).read_text())
        by_path = {p['path']: p for p in inventory['paths']}
        self.assertEqual(sorted(by_path), ['cloud/src/x.ts', 'docs/D.md', 'scripts/a.py', 'state/STATUS.md',
                                           'state/r75-qa-live-current.ref.json', 'state/r75-qa-live-old.json'])
        self.assertEqual((by_path['cloud/src/x.ts']['change'], by_path['cloud/src/x.ts']['range']), ('A', 'A1'))
        self.assertEqual(by_path['docs/D.md']['evidence'], 'R/FABLE-A2-INDEPENDENT-ACCEPT-CLAUDECODE-00000000.txt')
        # Byte-stable generator: rebuilding changes nothing.
        before = (self.root / INVENTORY).read_bytes()
        # The covered head is the last reviewed commit, not the HEAD that already carries the inventory (that commit is the tail).
        self.build(head=self.shas['c3'])
        self.assertEqual((self.root / INVENTORY).read_bytes(), before)

    def test_unlisted_changed_path_refuses(self):
        self.history()
        self.build()
        inventory = json.loads((self.root / INVENTORY).read_text())
        inventory['paths'] = [p for p in inventory['paths'] if p['path'] != 'cloud/src/x.ts']
        self.write(INVENTORY, json.dumps(inventory, indent=1) + '\n')
        self.commit('inventory missing a path')
        result = self.check()
        self.assertRefused(result, 'CHANGED_PATH_NOT_IN_INVENTORY')
        self.assertIn('cloud/src/x.ts', result.stderr)

    def test_path_changed_after_the_covered_head_refuses_outside_the_tail_rule(self):
        self.reviewed()
        for relative, text in (('cloud/src/x.ts', 'export const x = 2;\n'), ('scripts/new.py', 'print(3)\n'),
                               ('state/other.json', '{}\n'), ('state/r75-release-extra.json', '{}\n'),
                               ('docs/Another.md', 'doc\n')):
            with self.subTest(path=relative):
                self.write(relative, text)
                self.commit('late change ' + relative)
                result = self.check()
                self.assertRefused(result, 'TAIL_PATH_NOT_ALLOWED')
                self.assertIn(relative, result.stderr)
                self.git('reset', '-q', '--hard', 'HEAD~1')

    def test_unreviewed_entry_refuses_even_when_everything_else_matches(self):
        self.history(first_status='UNREVIEWED')
        self.build(expect=3)  # build still writes the inventory, but flags it
        summary = json.loads(self.build(expect=3).stdout)
        self.assertGreater(summary['unreviewed'], 0)
        self.assertEqual(summary['unreviewed_ranges'], ['A1'])
        self.commit('inventory with UNREVIEWED entries')
        self.assertRefused(self.check(), 'UNREVIEWED_PATH')

    def test_flipping_a_status_to_accepted_in_the_inventory_is_detected(self):
        self.history(first_status='UNREVIEWED')
        self.build(expect=3)
        inventory = json.loads((self.root / INVENTORY).read_text())
        for entry in inventory['paths']:
            entry['status'] = 'ACCEPTED'
        self.write(INVENTORY, json.dumps(inventory, indent=1) + '\n')
        self.commit('forged statuses')
        result = self.check()
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertRegex(result.stderr, r'reason=(INVENTORY_ENTRY_DIFFERS|INVENTORY_DIFFERS_FROM_GIT)')

    def test_last_change_decides_the_evidence_not_an_earlier_touch(self):
        self.write('scripts/a.py', 'print(1)\n')
        base = self.commit('baseline')
        self.write('scripts/a.py', 'print(2)\n')
        self.write('scripts/b.py', 'print(2)\n')
        c1 = self.commit('unreviewed era')
        self.write('scripts/a.py', 'print(3)\n')
        c2 = self.commit('reviewed rewrite of a.py only')
        self.write_ranges(base, [self.rng('OLD', c1, 'UNREVIEWED'), self.rng('NEW', c2)])
        self.build(expect=3)
        inventory = json.loads((self.root / INVENTORY).read_text())
        by_path = {p['path']: p for p in inventory['paths']}
        self.assertEqual((by_path['scripts/a.py']['status'], by_path['scripts/a.py']['touched_by']), ('ACCEPTED', ['OLD', 'NEW']))
        self.assertEqual(by_path['scripts/b.py']['status'], 'UNREVIEWED')

    def test_baseline_that_is_not_an_ancestor_refuses(self):
        self.history()
        branch = self.git('rev-parse', '--abbrev-ref', 'HEAD')
        self.git('checkout', '-q', '-b', 'side', self.shas['base'])
        self.write('side.txt', 'side\n')
        side = self.commit('side branch commit')
        self.git('checkout', '-q', branch)
        self.write_ranges(side, [self.rng('A1', self.shas['c3'])])
        result = self.scope('build', '--project-root', str(self.root), '--ranges', RANGES, '--output', INVENTORY)
        self.assertRefused(result, 'BASELINE_NOT_ANCESTOR')
        # The committed inventory cannot be re-pointed at a non-ancestor either.
        self.write_ranges(self.shas['base'], [self.rng('A1', self.shas['c1']), self.rng('A2', self.shas['c3'])])
        self.build()
        inventory = json.loads((self.root / INVENTORY).read_text())
        inventory['baseline'] = side
        self.write(INVENTORY, json.dumps(inventory, indent=1) + '\n')
        self.commit('inventory with a side-branch baseline')
        self.assertRefused(self.check(), 'BASELINE_NOT_ANCESTOR')

    def test_commit_after_the_last_range_is_unassigned_and_refuses(self):
        self.history()
        self.write_ranges(self.shas['base'], [self.rng('A1', self.shas['c1'])])
        self.build(expect=3)
        self.commit('inventory leaving c2 and c3 without a range')
        self.assertRefused(self.check(), 'INVENTORY_HAS_UNASSIGNED_COMMITS')

    def test_merge_commit_inside_the_scope_refuses(self):
        self.write('a.txt', 'a\n')
        base = self.commit('baseline')
        branch = self.git('rev-parse', '--abbrev-ref', 'HEAD')
        self.git('checkout', '-q', '-b', 'topic')
        self.write('t.txt', 't\n')
        self.commit('topic')
        self.git('checkout', '-q', branch)
        self.write('m.txt', 'm\n')
        self.commit('main side')
        self.git('merge', '-q', '--no-ff', '-m', 'merge topic', 'topic')
        head = self.git('rev-parse', 'HEAD')
        self.write_ranges(base, [self.rng('A1', head)])
        self.assertRefused(self.scope('build', '--project-root', str(self.root), '--ranges', RANGES, '--output', INVENTORY),
                           'MERGE_COMMIT_IN_SCOPE')

    def test_ranges_input_must_match_the_inventory_and_digest_pin_must_match(self):
        self.reviewed()
        digest = json.loads(self.check().stdout)['inventory_sha256']
        self.assertEqual(self.check('--expect-sha256', digest).returncode, 0)
        self.assertRefused(self.check('--expect-sha256', '1' * 64), 'INVENTORY_DIGEST_MISMATCH')
        doc = json.loads((self.root / RANGES).read_text())
        doc['ranges'][1]['receipt'] = 'R/FABLE-FORGED-INDEPENDENT-ACCEPT-CLAUDECODE-00000000.txt'
        self.write(RANGES, json.dumps(doc, indent=1) + '\n')
        self.commit('ranges input edited after the inventory')
        self.assertRefused(self.check(), 'RANGES_INPUT_DIFFERS_FROM_INVENTORY')

    def test_accepted_range_needs_a_receipt_name(self):
        self.history()
        doc = json.loads((self.root / RANGES).read_text())
        doc['ranges'][0]['receipt'] = ''
        self.write(RANGES, json.dumps(doc, indent=1) + '\n')
        self.assertRefused(self.scope('build', '--project-root', str(self.root), '--ranges', RANGES, '--output', INVENTORY),
                           'RANGE_ACCEPTED_WITHOUT_RECEIPT')

    def test_blob_pin_catches_a_listed_path_that_drifted(self):
        self.reviewed()
        inventory = json.loads((self.root / INVENTORY).read_text())
        for entry in inventory['paths']:
            if entry['path'] == 'scripts/a.py':
                entry['blob'] = 'f' * 40
        self.write(INVENTORY, json.dumps(inventory, indent=1) + '\n')
        self.commit('inventory with a wrong blob')
        self.assertRefused(self.check(), 'INVENTORY_ENTRY_DIFFERS')


class NarrowTailRuleTests(ScopeCase):
    def receipt_commit(self, receipt='state/r75-qa-live-new.json', pointer_to=None):
        self.write(receipt, '{"fresh": true}\n')
        self.write(POINTER, json.dumps({'schema_version': 1, 'receipt_path': pointer_to or receipt, 'receipt_sha256': '1' * 64}) + '\n')
        self.write('state/STATUS.md', 'status after live receipt\n')
        return self.commit('record the live Q&A receipt')

    def test_state_only_receipt_commit_passes_within_the_narrow_rule(self):
        self.reviewed()
        self.receipt_commit()
        result = self.check()
        self.assertEqual(result.returncode, 0, result.stderr)
        data = json.loads(result.stdout)
        self.assertEqual((data['tail_commits'], data['tail_new_receipts']), (2, ['state/r75-qa-live-new.json']))
        # STATUS-only commits keep passing too.
        self.write('state/STATUS.md', 'status again\n')
        self.commit('status')
        self.assertEqual(self.check().returncode, 0)

    def test_receipt_the_pointer_does_not_name_refuses(self):
        self.reviewed()
        self.receipt_commit(pointer_to='state/r75-qa-live-old.json')
        self.assertRefused(self.check(), 'TAIL_RECEIPT_NOT_POINTED_AT')

    def test_second_new_receipt_refuses(self):
        self.reviewed()
        self.receipt_commit()
        self.write('state/r75-qa-live-second.json', '{}\n')
        self.commit('second receipt')
        self.assertRefused(self.check(), 'TAIL_TOO_MANY_RECEIPTS')

    def test_rewriting_an_existing_receipt_or_deleting_status_refuses(self):
        self.reviewed()
        self.write('state/r75-qa-live-old.json', '{"old": false}\n')
        self.commit('rewrite the old receipt')
        self.assertRefused(self.check(), 'TAIL_PATH_NOT_ALLOWED')
        self.git('reset', '-q', '--hard', 'HEAD~1')
        (self.root / 'state/STATUS.md').unlink()
        self.commit('delete status')
        self.assertRefused(self.check(), 'TAIL_DELETE_FORBIDDEN')

    def test_wide_tail_refuses(self):
        self.reviewed()
        for number in range(8):
            self.write('state/STATUS.md', f'status {number + 10}\n')
            self.commit(f'status {number}')
        self.assertRefused(self.check(), 'TAIL_TOO_LONG')

    def test_inventory_with_a_foreign_covered_head_refuses(self):
        self.reviewed()
        inventory = json.loads((self.root / INVENTORY).read_text())
        branch = self.git('rev-parse', '--abbrev-ref', 'HEAD')
        self.git('checkout', '-q', '-b', 'other', self.shas['c1'])
        self.write('other.txt', 'o\n')
        other = self.commit('other')
        self.git('checkout', '-q', branch)
        inventory['covered_head'] = other
        self.write(INVENTORY, json.dumps(inventory, indent=1) + '\n')
        self.commit('inventory with a foreign covered head')
        result = self.check()
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn('R75_RELEASE_SCOPE_REFUSED reason=', result.stderr)


class VerifierScopeBindingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.verifier = load_module('relay_verifier_scope', ROOT / 'scripts/verify_v213_r75_free_relay_hotfix.py')

    def records(self):
        name = 'Investor-Intelligence-v2.1.3-R75-next1'
        digest = 'a' * 64
        refs = {'scope_mode': 'reviewed_inventory', 'artifact_name': name, 'scope_inventory_sha256': digest,
                'scope_baseline_commit': 'b' * 40, 'scope_covered_head': 'c' * 40}
        manifest = {'artifact_name': name, 'scope_inventory_sha256': digest}
        windows = {'release_ready': True, 'scope_mode': 'reviewed_inventory', 'artifact_name': name, 'scope_inventory_sha256': digest,
                   'scope_baseline_commit': 'b' * 40, 'scope_covered_head': 'c' * 40}
        return refs, manifest, [windows, {'extracted_zip_worker_gate': 'PASS'}, {'zip_sha256': 'x'}], name

    def test_legacy_archive_without_scope_fields_still_verifies(self):
        self.verifier.verify_scope_binding({}, {}, [{'release_ready': True}], self.verifier.DEFAULT_ARTIFACT_NAME)

    def test_successor_archive_binds_name_digest_baseline_and_covered_head(self):
        refs, manifest, verified, name = self.records()
        self.verifier.verify_scope_binding(refs, manifest, verified, name)
        mutants = [
            lambda r, m, v: r.update(scope_inventory_sha256='d' * 64),
            lambda r, m, v: m.update(scope_inventory_sha256='d' * 64),
            lambda r, m, v: v[0].update(scope_inventory_sha256='d' * 64),
            lambda r, m, v: v[0].update(scope_baseline_commit='e' * 40),
            lambda r, m, v: v[0].update(scope_covered_head='e' * 40),
            lambda r, m, v: r.update(scope_mode='legacy_allowlist'),
            lambda r, m, v: r.pop('scope_inventory_sha256'),
            lambda r, m, v: m.update(artifact_name='Investor-Intelligence-v2.1.3-R75-other'),
        ]
        for index, mutate in enumerate(mutants):
            refs, manifest, verified, name = self.records()
            mutate(refs, manifest, verified)
            with self.subTest(mutant=index), self.assertRaises(self.verifier.VerificationError):
                self.verifier.verify_scope_binding(refs, manifest, verified, name)

    def test_successor_scope_cannot_reuse_the_legacy_artifact_name(self):
        refs, manifest, verified, _ = self.records()
        default = self.verifier.DEFAULT_ARTIFACT_NAME
        refs['artifact_name'] = manifest['artifact_name'] = verified[0]['artifact_name'] = default
        with self.assertRaises(self.verifier.VerificationError):
            self.verifier.verify_scope_binding(refs, manifest, verified, default)

    def test_invalid_artifact_name_is_refused_before_any_archive_is_read(self):
        for bad in ('x', 'Investor-Intelligence-v2.1.3-R75-', '../Investor-Intelligence-v2.1.3-R75-x', 'Investor-Intelligence-v9.9.9-R75-x'):
            with self.subTest(name=bad), self.assertRaises(self.verifier.VerificationError):
                self.verifier.verify(Path('missing.zip'), Path('missing.sha256'), 'a' * 40, '1', [Path('a'), Path('b'), Path('c')], None, bad)


if __name__ == '__main__':
    unittest.main()
