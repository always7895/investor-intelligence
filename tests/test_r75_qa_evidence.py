import copy
import importlib.util
import json
from pathlib import Path
import sys
import unittest
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from verify_r75_qa_evidence import verify

class LiveQaQualificationTests(unittest.TestCase):
    def setUp(self):
        self.proof = json.loads((ROOT / 'state/r75-qa-live-qualification.json').read_text(encoding='utf-8-sig'))
        self.manifest = copy.deepcopy(self.proof['source_manifest'])

    def test_exact_runtime_source_and_complete_live_matrix(self):
        self.assertTrue(verify(self.proof)['release_ready'])

    def test_missing_partial_incomplete_or_synthetic_only_is_rejected(self):
        for field, value in [('status','PASS_SYNTHETIC'),('production_mutation',True),('real_line_sent',True),('preset_unchanged',False),('isolated_resources_deleted',False),('source_manifest',{}),('exact_model','qwen38'),('reference_job','PASS_SYNTHETIC'),('results',[])]:
            data=copy.deepcopy(self.proof);data[field]=value
            with self.subTest(field=field),self.assertRaises(ValueError):verify(data,self.manifest)

    def test_latency_truncation_tokens_or_model_errors_fail_closed(self):
        for field,value in [('total_ms',28001),('total_ms',True),('finish_reason','length'),('pass',False),('model','qwen38'),('usage',{}),('http_status',502)]:
            data=copy.deepcopy(self.proof);data['results'][0][field]=value
            with self.subTest(field=field),self.assertRaises(ValueError):verify(data,self.manifest)

    def test_old_schema_wrong_version_and_duplicate_cases_are_rejected(self):
        for field,value in [('parser_schema','old'),('worker_version','old'),('no_write',False),('publication_contract_sha256','bad')]:
            data=copy.deepcopy(self.proof);data['readiness'][0][field]=value
            with self.subTest(field=field),self.assertRaises(ValueError):verify(data,self.manifest)
        data=copy.deepcopy(self.proof);data['results'][0]=copy.deepcopy(data['results'][1])
        with self.assertRaises(ValueError):verify(data,self.manifest)

if __name__=='__main__':unittest.main()
