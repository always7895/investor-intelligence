import copy
import importlib.util
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch, Mock
from types import SimpleNamespace
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from verify_r75_qa_evidence import verify
from v213_qa_live_gate import router_limits, validate_router_proof, wait_isolated_origin

class LiveQaQualificationTests(unittest.TestCase):
    def setUp(self):
        self.proof = json.loads((ROOT / 'state/r75-qa-live-qualification.json').read_text(encoding='utf-8-sig'))
        self.manifest = copy.deepcopy(self.proof['source_manifest'])

    def test_only_new_test_host_empty_cloudflare_page_can_wait(self):
        pending=SimpleNamespace(status_code=404, headers={'server':'cloudflare'}, text='There is nothing here yet')
        ready=SimpleNamespace(status_code=200, json=lambda:{'ok':True,'product_version':'2.1.3','top20_presentation':'seven_fields'})
        session=SimpleNamespace(get=Mock(side_effect=[pending,ready]))
        now=[0.0]
        result=wait_isolated_origin(session,'https://ii-r75-qa-bench-012345abcd.synthetic.workers.dev',lambda:now[0],lambda n:now.__setitem__(0,now[0]+n))
        self.assertEqual(result['initial_empty_worker_404_count'],1)
        with self.assertRaisesRegex(RuntimeError,'SCOPE_INVALID'):
            wait_isolated_origin(session,'https://production.synthetic.workers.dev')
        for status in (301,401,403,404,429,500):
            bad=SimpleNamespace(status_code=status,headers={'server':'cloudflare'},text='arbitrary failure')
            session=SimpleNamespace(get=Mock(return_value=bad))
            with self.subTest(status=status),self.assertRaisesRegex(RuntimeError,'UNEXPECTED_HTTP'):
                wait_isolated_origin(session,'https://ii-r75-qa-bench-012345abcd.synthetic.workers.dev')
            self.assertEqual(session.get.call_count,1)
        now=[0.0];session=SimpleNamespace(get=Mock(return_value=pending))
        with self.assertRaisesRegex(RuntimeError,'PROVISIONING_TIMEOUT'):
            wait_isolated_origin(session,'https://ii-r75-qa-bench-012345abcd.synthetic.workers.dev',lambda:now[0],lambda n:now.__setitem__(0,now[0]+n))
        self.assertEqual(now[0],20)

    def test_router_proof_rejects_empty_multiple_or_non_integer_limits(self):
        listener = {'pid': 17, 'name': 'llama-server'}
        props = {'role': 'router', 'max_instances': 1}
        for invalid in (None, {}, [], [listener], {**listener, 'pid': True}, {**listener, 'name': 'unrelated'}):
            with self.subTest(listener=invalid), self.assertRaises(RuntimeError):
                validate_router_proof(invalid, props)
        for invalid in (None, {}, {**props, 'role': 'model'}, {**props, 'max_instances': True}, {**props, 'max_instances': 2}, {**props, 'max_instances': '1'}):
            with self.subTest(props=invalid), self.assertRaises(RuntimeError):
                validate_router_proof(listener, invalid)
        with patch('v213_qa_live_gate.subprocess.run', return_value=SimpleNamespace(stdout=json.dumps(listener))), patch('v213_qa_live_gate.requests.get', return_value=SimpleNamespace(status_code=200,json=lambda:props)) as get:
            self.assertEqual(router_limits()['models_max'],1)
            self.assertFalse(get.call_args.kwargs['allow_redirects'])

    def test_canonical_model_receipt_requires_unique_catalog(self):
        data = copy.deepcopy(self.proof)
        canonical = 'Qwen3.8-27B-UD-Q5_K_XL-7a1459e88548'
        # In-memory synthetic verifier fixture only; never rewrite the live receipt.
        data['canonical_model'] = canonical
        data['model_catalog'] = [{'id': canonical, 'aliases': ['qwen38-q5']}]
        for row in data['results']: row['model'] = canonical
        self.assertTrue(verify(data, self.manifest)['release_ready'])
        for catalog in (None, [], [{'id': 'other-model'}], data['model_catalog'] + [{'id': 'other', 'aliases': ['qwen38-q5']}]):
            with self.subTest(catalog=catalog), self.assertRaisesRegex(ValueError, 'CATALOG_PROOF_INVALID'):
                verify({**data, 'model_catalog': catalog}, self.manifest)

    def test_readiness_only_cannot_be_relabelled_as_release_pass(self):
        data=copy.deepcopy(self.proof)
        data.update(status='PASS',scope='READINESS_ONLY')
        with self.assertRaisesRegex(ValueError,'READINESS_ONLY_NOT_RELEASE_QUALIFICATION'):
            verify(data,self.manifest)

    def test_exact_runtime_source_and_complete_live_matrix(self):
        self.assertTrue(verify(self.proof)['release_ready'])

    def test_missing_partial_incomplete_or_synthetic_only_is_rejected(self):
        for field, value in [('status','PASS_SYNTHETIC'),('production_mutation',True),('real_line_sent',True),('preset_unchanged',False),('isolated_resources_deleted',False),('source_manifest',{}),('exact_model','qwen38'),('reference_job','PASS_SYNTHETIC'),('results',[]),('line_values_match',False),('text_fallback_values_match',False),('line_message_count',6),('text_message_count',6)]:
            data=copy.deepcopy(self.proof);data[field]=value
            with self.subTest(field=field),self.assertRaises(ValueError):verify(data,self.manifest)

    def test_latency_truncation_tokens_or_model_errors_fail_closed(self):
        for field,value in [('total_ms',28001),('total_ms',True),('finish_reason','length'),('pass',False),('model','qwen38'),('pi_usage',{}),('http_status',502)]:
            data=copy.deepcopy(self.proof);data['results'][0][field]=value
            with self.subTest(field=field),self.assertRaises(ValueError):verify(data,self.manifest)

    def test_old_schema_wrong_version_and_duplicate_cases_are_rejected(self):
        for field,value in [('parser_schema','old'),('worker_version','old'),('no_write',False),('publication_contract_sha256','bad')]:
            data=copy.deepcopy(self.proof);data['readiness'][0][field]=value
            with self.subTest(field=field),self.assertRaises(ValueError):verify(data,self.manifest)
        data=copy.deepcopy(self.proof);data['results'][0]=copy.deepcopy(data['results'][1])
        with self.assertRaises(ValueError):verify(data,self.manifest)

if __name__=='__main__':unittest.main()
