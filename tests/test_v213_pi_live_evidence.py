"""Synthetic v2 receipt mutations; these are NOT live qualification evidence."""
import copy
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from verify_r75_qa_evidence import verify
from v213_pi_transport import PROFILE


def fixture():
    data = json.loads((ROOT / 'state/r75-qa-live-qualification.json').read_text(encoding='utf-8'))
    data.update(schema_version=2, inference_backend='pi', thinking_level='xhigh', request_enable_thinking=True,
                exact_model=PROFILE['model_id'], canonical_model=PROFILE['model_id'],
                model_catalog=[{'id': PROFILE['model_id']}], source_manifest={'fixture': 'synthetic'})
    data['router_processes_unchanged'] = True
    data['router_processes'] = {'processes': [{'pid': 1001, 'parent_pid': 1, 'started_utc': '2026-09-06T00:00:00Z'},
                                              {'pid': 1002, 'parent_pid': 1001, 'started_utc': '2026-09-06T00:00:01Z'}],
                                'loaded_model': PROFILE['model_id'],
                                'model_file': {'path': 'D:/models/fixture.gguf', 'size': 1024,
                                               'head_sha256': '0' * 64, 'tail_sha256': '1' * 64}}
    for row in data['results']:
        row['model'] = PROFILE['model_id']
        row['inference'] = 'pi'
        row['pi_usage'] = {'input_tokens': 600, 'output_tokens': 400, 'cache_read_tokens': 0}
        row['pi_proof'] = {'provider': 'llama.cpp', 'thinking_level': 'xhigh', 'xhigh_payload_validated': True,
                           'tools_executed': 0, 'qualification_cache_prompt': row['phase'] == 'warm', 'thinking_chars': 100}
    return data

class PiLiveEvidenceTests(unittest.TestCase):
    def test_synthetic_complete_pi_contract_and_fail_closed_mutations(self):
        data = fixture()
        self.assertEqual(verify(data, manifest={'fixture': 'synthetic'}, require_pi=True)['status'], 'PASS')
        for change in [lambda d: d['results'][2].update(inference='deterministic'),
                       lambda d: d.update(router_processes_unchanged=False),
                       lambda d: d['router_processes'].update(loaded_model='other'),
                       lambda d: d['router_processes']['model_file'].update(head_sha256='0' * 63),
                       lambda d: d.update(schema_version=True), lambda d: d.update(exact_model='qwen38-q6'),
                       lambda d: d.update(inference_backend='llama'), lambda d: d.update(request_enable_thinking=False),
                       lambda d: d['results'][0]['pi_proof'].update(thinking_level='off'),
                       lambda d: d['results'][0]['pi_proof'].update(xhigh_payload_validated=1),
                       lambda d: d['results'][0]['pi_proof'].update(qualification_cache_prompt=True),
                       lambda d: d['results'][0]['pi_usage'].update(cache_read_tokens=1),
                       lambda d: d['results'][2]['pi_proof'].update(thinking_chars=0)]:
            failed = copy.deepcopy(data); change(failed)
            with self.assertRaises(ValueError): verify(failed, manifest={'fixture': 'synthetic'}, require_pi=True)

    def test_old_direct_receipt_cannot_satisfy_pi_requirement(self):
        data = json.loads((ROOT / 'state/r75-qa-live-qualification.json').read_text(encoding='utf-8'))
        with self.assertRaisesRegex(ValueError, 'PI_LIVE_QUALIFICATION_REQUIRED'):
            verify(data, require_pi=True)

if __name__ == '__main__': unittest.main()
