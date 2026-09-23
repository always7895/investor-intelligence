"""E2A adopted synthetic regression tests; not an additional independent run."""
import copy,importlib.util,unittest
from pathlib import Path
S=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('creation',S/'scripts/v213_qa_capacity_creation_contract.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
def fixture(stdio=False):
    io={'stdin':'input','stdout':'output','stderr':'output'} if stdio else {}
    e=[dict(type='RESERVATION',run_id='run',candidate_sha256='a'*64,deadline_ns=100,synthetic=True),dict(type='JOB_READY',job_token='job',inherit=False,kill_on_close=True,breakaway=False),dict(type='ATTRIBUTES_READY',executable='synthetic.exe',cwd='synthetic',flags=0x80004,inherit_handles=stdio,job_list=['job'],stdio=io),dict(type='CREATE_ADMITTED',permit_token='permit',executable='synthetic.exe',cwd='synthetic',flags=0x80004,inherit_handles=stdio,job_list=['job'],handle_list=['input','output'] if stdio else []),dict(type='CREATE_RETURNED',success=True,process_token='process',thread_token='thread',original_creation_handles=True,attributes_kept_alive_through_return=True),dict(type='MEMBERSHIP_OBSERVED',process_token='process',job_token='job',in_job=True,suspended=True),dict(type='ATTRIBUTE_STORAGE_RELEASED',after_create_return=True),dict(type='CUSTODY_RETAINED',process_token='process',thread_token='thread',job_token='job',job_inherited=False,resumed=False)]
    for i,event in enumerate(e):event['now_ns']=i
    return e
FLAGS=['authorizes_execution','platform_qualified','image_bytes_attested','workspace_attested','hard_io_timeout_proven','cleanup_confirmed','retry_authorized']
class CreationProbes(unittest.TestCase):
    def check_safe(self,result):
        for flag in FLAGS:self.assertIs(result[flag],False)
        self.assertIs(result['synthetic'],True)
    def test_positive_profiles_and_immutability(self):
        for stdio in [False,True]:
            e=fixture(stdio);before=copy.deepcopy(e);r=m.validate_creation_transcript(e);self.check_safe(r);self.assertEqual(r['status'],'SYNTHETIC_CREATION_CONTRACT_VALID');self.assertEqual(r['permit_state'],'SPENT_CLAIMED');self.assertEqual(e,before)
    def test_all_truncations_and_unknown_fields(self):
        for n in range(8):
            r=m.validate_creation_transcript(fixture()[:n]);self.check_safe(r);self.assertNotEqual(r['status'],'SYNTHETIC_CREATION_CONTRACT_VALID')
            if n>=4:self.assertEqual(r['permit_state'],'SPENT_CLAIMED');self.assertEqual(r['status'],'UNQUALIFIED_QUARANTINED')
        for i in range(8):
            e=fixture();e[i]['cleanup_confirmed']=True;r=m.validate_creation_transcript(e);self.check_safe(r);self.assertNotEqual(r['status'],'SYNTHETIC_CREATION_CONTRACT_VALID')
    def test_late_and_failed_creation_spends(self):
        for i in [3,4,5,6,7]:
            e=fixture();e[i]['now_ns']=100;r=m.validate_creation_transcript(e);self.check_safe(r);self.assertEqual(r['status'],'UNQUALIFIED_QUARANTINED');self.assertIn(r['permit_state'],['SPENT_CLAIMED','UNKNOWN'])
        e=fixture();e[4].update(success=False,process_token=None,thread_token=None,original_creation_handles=False);r=m.validate_creation_transcript(e);self.assertEqual(r['status'],'UNQUALIFIED_QUARANTINED');self.assertEqual(r['permit_state'],'SPENT_CLAIMED');self.check_safe(r)
    def test_each_role_and_call_binding(self):
        mutations=[(3,'executable','other.exe'),(3,'cwd','other'),(3,'flags',0x80000),(3,'inherit_handles',1),(3,'job_list',['foreign']),(3,'handle_list',['job']),(3,'permit_token','job'),(4,'thread_token','process'),(4,'process_token','job'),(4,'process_token','permit'),(4,'original_creation_handles',1),(4,'attributes_kept_alive_through_return',False),(5,'process_token','foreign'),(5,'suspended',False),(7,'resumed',True),(7,'job_inherited',True),(2,'flags',True)]
        for index,key,value in mutations:
            with self.subTest(index=index,key=key):
                e=fixture();e[index][key]=value;r=m.validate_creation_transcript(e);self.check_safe(r);self.assertNotEqual(r['status'],'SYNTHETIC_CREATION_CONTRACT_VALID')
    def test_stdio_leaks_and_list_exactness(self):
        for value in [{'stdin':'job','stdout':'output','stderr':'output'},{'stdin':'output','stdout':'output','stderr':'output'},{'stdout':'output'},[],{'stdin':[], 'stdout':'output','stderr':'output'}]:
            e=fixture(True);e[2]['stdio']=value;r=m.validate_creation_transcript(e);self.check_safe(r);self.assertNotEqual(r['status'],'SYNTHETIC_CREATION_CONTRACT_VALID')
        for value in [['input','output','extra'],['input','output','output'],('input','output'),[True]]:
            e=fixture(True);e[3]['handle_list']=value;r=m.validate_creation_transcript(e);self.check_safe(r);self.assertNotEqual(r['status'],'SYNTHETIC_CREATION_CONTRACT_VALID')
    def test_job_list_exact_token_type(self):
        class EqualToAnything:
            def __eq__(self, other): return True
        for index in (2,3):
            for value in (True, [], EqualToAnything()):
                with self.subTest(index=index,value=type(value).__name__):
                    e=fixture();e[index]['job_list']=[value]
                    result=m.validate_creation_transcript(e);self.check_safe(result)
                    self.assertNotEqual(result['status'],'SYNTHETIC_CREATION_CONTRACT_VALID')
    def test_types_caps_and_order(self):
        for e in [None,{},True,tuple(fixture()),fixture()+[{}]]:
            r=m.validate_creation_transcript(e);self.check_safe(r);self.assertEqual(r['status'],'INVALID_TRANSCRIPT');self.assertEqual(r['permit_state'],'UNKNOWN')
        for i in range(8):
            for value in [True,-1,2**63,0.5,float('nan')]:
                e=fixture();e[i]['now_ns']=value;r=m.validate_creation_transcript(e);self.check_safe(r);self.assertNotEqual(r['status'],'SYNTHETIC_CREATION_CONTRACT_VALID')
        for i in range(7):
            e=fixture();e[i],e[i+1]=e[i+1],e[i];r=m.validate_creation_transcript(e);self.check_safe(r);self.assertNotEqual(r['status'],'SYNTHETIC_CREATION_CONTRACT_VALID')
        for value in ['x'*65,'bad token',[],True]:
            e=fixture();e[1]['job_token']=value;r=m.validate_creation_transcript(e);self.check_safe(r);self.assertNotEqual(r['status'],'SYNTHETIC_CREATION_CONTRACT_VALID')
if __name__=='__main__':unittest.main(verbosity=2)
