"""Regression for the release ZIP that removed activation's npm test inputs."""
import importlib.util
import json
import copy
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "relay_verifier", ROOT / "scripts/verify_v213_r75_free_relay_hotfix.py"
)
VERIFIER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(VERIFIER)


class PackagedWorkerPayloadTests(unittest.TestCase):
    def payload(self):
        paths = sorted((ROOT / "cloud/test").glob("*.ts")) + sorted(
            (ROOT / "tests/fixtures/v213-r75-publication-mode").glob("*.json")
        )
        files = {p.relative_to(ROOT).as_posix().lower():
                 (p.relative_to(ROOT).as_posix(), p.read_bytes()) for p in paths}
        refs = {"worker_test_payload": [v[0] for v in files.values()],
                "packaged_worker_test_count": 113}
        return files, refs

    def test_only_reviewed_public_skill_and_all_its_references_are_packaged(self):
        paths = ['skills/serenity-public-research/SKILL.md',
                 'skills/serenity-public-research/references/RESEARCH_METHOD.md',
                 'skills/serenity-public-research/references/CROSS_VALIDATION.md',
                 'cloud/src/v213/top20-report.ts', 'docs/CURRENT_STATUS_BILINGUAL.md']
        files = {p.casefold(): (p, (ROOT / p).read_bytes()) for p in paths}
        VERIFIER.verify_public_research_payload(files)
        for path in files:
            with self.subTest(missing=path), self.assertRaises(VERIFIER.VerificationError):
                VERIFIER.verify_public_research_payload({k:v for k,v in files.items() if k != path})
        with self.assertRaises(VERIFIER.VerificationError):
            VERIFIER.verify_public_research_payload({**files, 'skills/unreviewed.md': ('skills/unreviewed.md', b'synthetic')})

    def test_complete_runtime_payload_passes(self):
        files, refs = self.payload()
        VERIFIER.verify_worker_test_payload(files, refs)

    def test_old_zip_without_tests_fails_closed(self):
        _, refs = self.payload()
        with self.assertRaises(VERIFIER.VerificationError):
            VERIFIER.verify_worker_test_payload({}, refs)

    def test_each_runtime_dependency_is_required(self):
        files, refs = self.payload()
        for path in files:
            with self.subTest(path=path), self.assertRaises(VERIFIER.VerificationError):
                VERIFIER.verify_worker_test_payload(
                    {k: v for k, v in files.items() if k != path}, refs
                )

    def test_missing_fixture_cannot_be_removed_from_inventory(self):
        files, refs = self.payload()
        missing = "tests/fixtures/v213-r75-publication-mode/mixed.json"
        del files[missing]
        refs["worker_test_payload"].remove(missing)
        with self.assertRaises(VERIFIER.VerificationError):
            VERIFIER.verify_worker_test_payload(files, refs)

    def test_zero_or_boolean_test_count_rejected(self):
        files, refs = self.payload()
        for count in (0, -1, True, "113", None):
            with self.subTest(count=count), self.assertRaises(VERIFIER.VerificationError):
                VERIFIER.verify_worker_test_payload(files, dict(refs, packaged_worker_test_count=count))

    def test_non_runtime_tests_rejected(self):
        files, refs = self.payload()
        extra = "tests/internal.py"
        files[extra] = (extra, b"# synthetic")
        refs["worker_test_payload"].append(extra)
        with self.assertRaises(VERIFIER.VerificationError):
            VERIFIER.verify_worker_test_payload(files, refs)


class ArchiveModelBindingTests(unittest.TestCase):
    """Synthetic ZIPs/receipts test admission, not real PE/install qualification."""
    def fixture(self, directory, modern=True, mutate=None):
        commit, run = 'a' * 40, '12345'
        files, refs = PackagedWorkerPayloadTests().payload()
        files = {k: v[1] for k, v in files.items()}
        paths = '''scripts/v213_free_relay.ps1 scripts/v213_free_relay_heartbeat.ps1
scripts/v213_windows_security.ps1 scripts/run_v213_local_llm_bridge_core.ps1
register-v213-free-relay-task.ps1 scripts/v213_sealed_refresh.ps1
run-v213-scheduled-refresh.ps1 register-v213-refresh-tasks.ps1
cloud/src/v213/free-relay.ts cloud/src/v213/production-worker.ts
cloud/wrangler.v213.production.template.toml run-v213-local.ps1
config/v213-r75-publication-mode-v1.json scripts/v213_r75_activation_preflight.py
cloud/src/v213/publication-mode.ts cloud/src/v213/activation-v2.ts
skills/serenity-public-research/SKILL.md
skills/serenity-public-research/references/RESEARCH_METHOD.md
skills/serenity-public-research/references/CROSS_VALIDATION.md
cloud/src/v213/top20-report.ts docs/CURRENT_STATUS_BILINGUAL.md'''.split()
        for p in paths:
            files[p.casefold()] = (ROOT / p).read_bytes()
        files['investorintelligence.exe'] = b'MZ_SYNTHETIC_NOT_AN_INSTALLABLE_EXECUTABLE'
        common = dict(artifact_kind='R75_FREE_WORKERS_RELAY_HOTFIX', source_commit=commit,
                      workflow_run_id=run, base_named_tunnel_commit=VERIFIER.BASE,
                      production_mutation_by_ci=False)
        refs.update(common, protected_release_semantics_unchanged=True,
                    consecutive_public_health_required=3, health_schema_version=2,
                    exact_model='qwen38-q6', normal_production_tunnel_mode='quick_free_relay',
                    workers_dev_stable_entrypoint=True, custom_domain_required=False,
                    publication_contract_sha256=VERIFIER.sha(files['config/v213-r75-publication-mode-v1.json']))
        receipts = [dict(common, status='PASS', release_ready=True, live_qa='PASS', live_free_relay_smoke='PASS'),
                    dict(common, status='PASS', extracted_zip_worker_gate='PASS', packaged_worker_typecheck='PASS',
                         packaged_worker_tests=refs['packaged_worker_test_count'], extracted_zip_runtime_install='PASS'),
                    dict(common, status='PASS')]
        if modern:
            profile = dict(schema_version=1, model='synthetic-profile-model', enable_thinking=False,
                           reasoning_effort='none', max_output_tokens=1024, smoke_output_tokens=128, timeout_ms=18000)
            files['config/v213-model-profile-v1.json'] = json.dumps(profile).encode()
            for p in ('scripts/v213_model_profile.py', 'scripts/v213_compact_qa_gateway.py',
                      'scripts/v213_local_llm_gateway.py', 'cloud/src/v213/model-profile.ts'):
                files[p] = (ROOT / p).read_bytes()
            for record in (refs, receipts[0], receipts[1]):
                record.update(exact_model=profile['model'], model_profile_sha256=VERIFIER.profile_sha256(profile))
        if mutate:
            mutate(files, refs, receipts)
        files['hotfix-refs.json'] = json.dumps(refs).encode()
        manifest = dict(common, files=[dict(path=k, bytes=len(v), sha256=VERIFIER.sha(v)) for k, v in files.items()])
        files['manifest.json'] = json.dumps(manifest).encode()
        files['sha256sums.txt'] = ''.join(f'{VERIFIER.sha(v)}  {k}\n' for k, v in files.items()).encode()
        archive = directory / f'Investor-Intelligence-v2.1.3-R75-Free-Relay-Hotfix-{commit}-{run}.zip'
        with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED) as z:
            for name, data in files.items():
                z.writestr(name, data)
        digest = VERIFIER.sha(archive.read_bytes())
        checksum = directory / 'checksum.txt'
        checksum.write_text(f'{digest}  {archive.name}\n', encoding='ascii')
        # These are fresh synthetic delivery receipts, not restamped real evidence.
        receipts[2].setdefault('zip_sha256', digest)
        receipt_paths = []
        for i, record in enumerate(receipts):
            path = directory / f'synthetic-receipt-{i}.json'
            path.write_text(json.dumps(record), encoding='utf-8')
            receipt_paths.append(path)
        return archive, checksum, commit, run, receipt_paths

    def test_actual_archive_cli_accepts_bound_profile_and_legacy(self):
        for modern in (False, True):
            with self.subTest(modern=modern), tempfile.TemporaryDirectory() as d:
                directory = Path(d)
                archive, checksum, commit, run, receipts = self.fixture(directory, modern)
                output = directory / 'result.json'
                command = [sys.executable, str(ROOT / 'scripts/verify_v213_r75_free_relay_hotfix.py'),
                           '--archive', str(archive), '--checksum', str(checksum), '--source-commit', commit,
                           '--workflow-run-id', run, '--output', str(output)]
                for receipt in receipts:
                    command += ['--receipt', str(receipt)]
                result = subprocess.run(command, capture_output=True, timeout=30)
                self.assertEqual(result.returncode, 0, result.stdout)
                self.assertEqual(json.loads(output.read_text())['exact_model'],
                                 'synthetic-profile-model' if modern else 'qwen38-q6')

    def test_rehashed_archives_cannot_hide_profile_drift_or_missing_receipts(self):
        cases = [
            lambda f, r, e: r.update(exact_model='wrong'),
            lambda f, r, e: r.update(model_profile_sha256='0' * 64),
            lambda f, r, e: e[0].update(model_profile_sha256='0' * 64),
            lambda f, r, e: e[1].update(exact_model='wrong'),
            lambda f, r, e: e[0].update(release_ready=False),
            lambda f, r, e: e[0].update(artifact_kind='wrong'),
            lambda f, r, e: e[2].update(zip_sha256='0' * 64),
            lambda f, r, e: e.__setitem__(0, copy.deepcopy(e[1])),
            lambda f, r, e: f.pop('config/v213-model-profile-v1.json'),
            lambda f, r, e: f.pop('scripts/v213_model_profile.py'),
            lambda f, r, e: f.update({'config/v213-model-profile-v1.json': b'{"model":"invalid"}'}),
        ]
        for i, change in enumerate(cases):
            with self.subTest(case=i), tempfile.TemporaryDirectory() as d:
                args = self.fixture(Path(d), mutate=change)
                with self.assertRaises(VERIFIER.VerificationError):
                    VERIFIER.verify(*args)

    def test_profile_markers_cannot_silently_downgrade_to_legacy(self):
        def change(files, refs, receipts):
            files.pop('config/v213-model-profile-v1.json')
            for record in (refs, receipts[0], receipts[1]):
                record.pop('model_profile_sha256')
                record['exact_model'] = 'qwen38-q6'
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaisesRegex(VERIFIER.VerificationError, 'profile runtime payload missing'):
                VERIFIER.verify(*self.fixture(Path(d), mutate=change))

    def test_coherent_but_unqualified_thinking_is_rejected(self):
        def change(files, refs, receipts):
            key = 'config/v213-model-profile-v1.json'
            profile = json.loads(files[key])
            profile.update(enable_thinking=True, reasoning_effort='low')
            files[key] = json.dumps(profile).encode()
            for record in (refs, receipts[0], receipts[1]):
                record['model_profile_sha256'] = VERIFIER.profile_sha256(profile)
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaisesRegex(VERIFIER.VerificationError, 'thinking capability unqualified'):
                VERIFIER.verify(*self.fixture(Path(d), mutate=change))

    def test_duplicate_receipt_keys_are_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            args = self.fixture(Path(d))
            receipt = args[-1][0]
            receipt.write_bytes(receipt.read_bytes()[:-1] + b',"status":"PASS"}')
            with self.assertRaises(VERIFIER.VerificationError):
                VERIFIER.verify(*args)

    def test_legacy_cannot_admit_other_model(self):
        with tempfile.TemporaryDirectory() as d:
            args = self.fixture(Path(d), modern=False, mutate=lambda f, r, e: r.update(exact_model='other'))
            with self.assertRaises(VERIFIER.VerificationError):
                VERIFIER.verify(*args)


if __name__ == "__main__":
    unittest.main()
