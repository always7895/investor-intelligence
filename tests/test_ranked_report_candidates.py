"""Actual report/progress and final-order callers; public synthetic fixtures only."""
import copy
import hashlib
import json
import subprocess
import sys
import tempfile
import types
import unittest
from contextlib import redirect_stdout
from datetime import datetime
from io import StringIO
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT/'scripts'), str(ROOT/'tests')]
import test_report_source_acquisition as fixture
import v213_finalize_rank_coupled_order as finalizer
import company_financial_products as products
builder = fixture.builder


def prepare(root, *, rich=False, prices=None):
    original_market = builder._market_observation
    class Prices:
        def items(self):
            return iter(prices if prices is not None else [(datetime(2024,9,9),100.0),(datetime(2026,3,9),120.0),(datetime(2026,9,9),144.0)])
    fake = types.SimpleNamespace(Ticker=lambda _:types.SimpleNamespace(
        history=lambda **kw:{'Close':Prices()}, info={'industry':'Semiconductors'}))
    cls = fixture.financial_fixture.V212Top20ReportTests
    wire = cls.wire_document
    with patch.dict(sys.modules, {'yfinance':fake}), patch.object(cls, 'wire_document',
            lambda self, records: wire(self, records + ([self.fact(tag='OperatingIncomeLoss',value=12)] if rich else []))):
        result = fixture.actual_cli(root, progress=True, market=original_market)
    assert result['http_calls'] == 0
    paths = {'top20':root/'top20.json','v212':root/'report.json','v213':root/'seven.json',
             'federation':root/'federation.json','source_audit':root/'source.json','ledger':root/'ledger.json',
             'returns':root/'report.return-evidence-candidate.json','basis':root/'report.financial-evidence-candidate.json',
             'products':root/'report.financial-products-candidate.json'}
    seven=fixture.scheduled.build(result['report'],fixture.no_orders(result['report']))
    paths['v213'].write_bytes(builder.json_bytes(seven))
    for name,key in [('federation','ticker_sources'),('source_audit','records'),('ledger','records')]:
        paths[name].write_bytes(builder.json_bytes({key:[{'rank':i+1,'ticker':f'T{i:02d}','scope':'SYNTHETIC'} for i in range(20)]}))
    before={key:path.read_bytes() for key,path in paths.items()}
    return paths,before


def ranked_top(paths):
    rows=json.loads(paths['top20'].read_bytes())
    rows.reverse()
    for rank,row in enumerate(rows,1):row['rank']=rank
    paths['top20'].write_bytes(builder.json_bytes(rows))


def arguments(paths):
    args = []
    for key in ('top20','v212','v213','federation','source_audit','ledger'):
        args.extend(['--'+key.replace('_','-'), str(paths[key])])
    for key, flag in [('returns','return-evidence'),('basis','financial-evidence'),('products','financial-products')]:
        args.extend(['--'+flag, str(paths[key])])
    return args


def run_finalizer(paths):
    with patch.object(sys,'argv',['finalize',*arguments(paths)]),redirect_stdout(StringIO()):
        return finalizer.main()


def current_bytes(paths):
    return {key:path.read_bytes() for key,path in paths.items()}


class RankedReportCandidateTests(unittest.TestCase):
    def test_actual_final_order_cli_keeps_financial_and_return_candidates_bound(self):
        with tempfile.TemporaryDirectory() as tmp:
            paths,before=prepare(Path(tmp));ranked_top(paths)
            self.assertEqual(run_finalizer(paths),0)
            raw=paths['v212'].read_bytes();digest=hashlib.sha256(raw).hexdigest()
            basis=json.loads(paths['basis'].read_bytes());returns=json.loads(paths['returns'].read_bytes())
            self.assertEqual(basis['report_sha256'],digest,'FINAL_ORDER_LEAVES_FINANCIAL_BASIS_BOUND_TO_OLD_REPORT')
            self.assertEqual(returns['report_sha256'],digest,'FINAL_ORDER_LEAVES_RETURN_BASIS_BOUND_TO_OLD_REPORT')
            products.verify_financial_products(paths['products'].read_bytes(),raw,paths['basis'].read_bytes())
            self.assertEqual(json.loads(raw)['records'][0]['ticker'],'T19')
            self.assertEqual(basis['records'],json.loads(before['basis'])['records'])
            self.assertEqual(returns['records'],json.loads(before['returns'])['records'])
            self.assertEqual(json.loads(raw)['generated_at'],json.loads(before['v212'])['generated_at'])
            self.assertIsNone(json.loads(raw)['records'][0]['retrieved_at'])  # Unknown market time stays unknown.

    def test_invalid_late_document_cannot_partially_rewrite_earlier_reports(self):
        with tempfile.TemporaryDirectory() as tmp:
            paths,_=prepare(Path(tmp));ranked_top(paths)
            ledger=json.loads(paths['ledger'].read_bytes());ledger['records'].pop()
            paths['ledger'].write_bytes(builder.json_bytes(ledger))
            before={key:path.read_bytes() for key,path in paths.items()}
            with self.assertRaises(finalizer.FinalOrderError):run_finalizer(paths)
            for key,path in paths.items():self.assertEqual(path.read_bytes(),before[key],f'EARLY_REPORT_REWRITTEN_BEFORE_LATE_VALIDATION:{key}')

    def test_actual_diversified_cli_then_standalone_finalizer_rebinds_already_reordered_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);paths,before=prepare(root,rich=True)
            top=json.loads(paths['top20'].read_bytes())
            for i,row in enumerate(top):row['serenity_factors']['valuation_expectations']=i/10
            paths['top20'].write_bytes(builder.json_bytes(top))
            fed={'generated_at':json.loads(before['v212'])['generated_at'],
                 'ticker_sources':[{'ticker':row['ticker'],'independent_families':['us_sec','nasdaq','yahoo_finance'],
                 'official_identity_or_filing_families':['us_sec','nasdaq'],'market_observation_families':['yahoo_finance'],
                 'issuer_financial_claim_family_count':1,'evidence_additions':[]} for row in top],
                 'gates':{'pass':True,'successful_families':['us_sec','nasdaq','yahoo_finance'],
                 'official_successful_families':['us_sec','nasdaq'],'ticker_coverage_ratio':1.0,
                 'largest_family_share':0.3333,'unresolved_material_conflict_count':0,'missing_required_families':[]}}
            paths['federation'].write_bytes(builder.json_bytes(fed));(root/'plan.json').write_text('{}',encoding='utf-8')
            args=[]
            for key in ('top20','v212','v213','federation'):args.extend(['--'+key,str(paths[key])])
            args+=['--plan',str(root/'plan.json'),'--report',str(root/'report.md')]
            proc=subprocess.run([sys.executable,'-B',str(ROOT/'scripts/v213_apply_diversified_operationalization.py'),*args],cwd=root,capture_output=True,text=True,encoding='utf-8',timeout=30)
            self.assertEqual(proc.returncode,0,proc.stderr);self.assertIn('V213_DIVERSIFIED_OPERATIONALIZATION = PASS',proc.stdout)
            self.assertEqual(json.loads(paths['v212'].read_bytes())['records'][0]['ticker'],'T19')
            self.assertNotEqual(paths['v212'].read_bytes(),before['v212'])
            with self.assertRaises(products.FinancialProductsError):
                products.verify_financial_products(paths['products'].read_bytes(),paths['v212'].read_bytes(),paths['basis'].read_bytes())
            current_report=paths['v212'].read_bytes()
            proc=subprocess.run([sys.executable,'-B',str(ROOT/'scripts/v213_finalize_rank_coupled_order.py'),*arguments(paths)],cwd=root,capture_output=True,text=True,encoding='utf-8',timeout=30)
            self.assertEqual(proc.returncode,0,proc.stderr);self.assertIn('candidates_bound=true',proc.stdout)
            self.assertIn('publication_qualified=false; transaction_atomic=false',proc.stdout)
            self.assertEqual(paths['v212'].read_bytes(),current_report)  # Finalizer cannot restamp/recompute this input.
            products.verify_financial_products(paths['products'].read_bytes(),current_report,paths['basis'].read_bytes())
            old={row['ticker']:row['products'] for row in json.loads(before['products'])['records']}
            new=json.loads(paths['products'].read_bytes())
            self.assertTrue(any(len(item['pages'])>1 for row in new['records'] for item in row['products'].values()),
                            'MULTIPAGE_REBINDING_CONTROL_REQUIRED')
            self.assertNotEqual(new['candidate_snapshot_id'],json.loads(before['products'])['candidate_snapshot_id'])
            for row in new['records']:
                for kind,item in row['products'].items():
                    previous=old[row['ticker']][kind]
                    self.assertEqual(item['status'],'AVAILABLE_PARTIAL')
                    for key in ('content_utf8','content_sha256','claim_refs','subject','output_kind'):
                        self.assertEqual(item[key],previous[key])
                    self.assertEqual(item['report_id'],previous['report_id'])  # Stable subject/kind ID; snapshot/hash binding changes.
                    self.assertNotEqual(item['candidate_snapshot_id'],previous['candidate_snapshot_id'])
                    self.assertNotEqual(item['source_report_sha256'],previous['source_report_sha256'])
                    self.assertEqual('\n\n'.join(page['text'] for page in item['pages']),item['content_utf8'])
            self.assertEqual(json.loads(paths['returns'].read_bytes())['records'],json.loads(before['returns'])['records'])
            self.assertEqual(json.loads(paths['basis'].read_bytes())['records'],json.loads(before['basis'])['records'])

    def test_repeat_and_second_rank_change_preserve_failed_products_and_original_clocks(self):
        with tempfile.TemporaryDirectory() as tmp:
            paths,before=prepare(Path(tmp));ranked_top(paths);run_finalizer(paths)
            once=current_bytes(paths)
            with patch.object(finalizer,'atomic_bytes',side_effect=AssertionError('IDEMPOTENT_RUN_MUST_NOT_WRITE')):
                self.assertEqual(run_finalizer(paths),0)
            self.assertEqual(current_bytes(paths),once)
            ranked_top(paths);run_finalizer(paths)
            self.assertEqual(paths['v212'].read_bytes(),before['v212'])
            self.assertEqual(paths['products'].read_bytes(),before['products'])
            narrative=json.loads(paths['products'].read_bytes())['records'][0]['products']['narrative_analysis']
            self.assertEqual(narrative['status'],'UNAVAILABLE');self.assertEqual(narrative['pages'],[])

    def test_non_rank_report_changes_cannot_borrow_old_basis_even_with_valid_new_clocks(self):
        with tempfile.TemporaryDirectory() as tmp:
            paths,before=prepare(Path(tmp));ranked_top(paths)
            source=json.loads(before['v212'])
            def profit(doc):
                row=doc['records'][19];row['profit_summary']='淨利率 99.0%'
                row['source_acquisition']['profit_summary']['value']=row['profit_summary']
            def renewal(doc):
                row=doc['records'][19];row['source_acquisition']['profit_summary']['retrieved_at']=doc['generated_at']
            for mutate in (profit,renewal,lambda d:d.update(calculation_cutoff='2026-09-09T00:00:00Z'),lambda d:d.update(schema_version=1)):
                with self.subTest(mutation=mutate.__name__):
                    doc=copy.deepcopy(source);mutate(doc);paths['v212'].write_bytes(builder.json_bytes(doc))
                    expected=current_bytes(paths)
                    with self.assertRaises(finalizer.FinalOrderError):run_finalizer(paths)
                    self.assertEqual(current_bytes(paths),expected)

    def test_invalid_source_report_ranks_cannot_be_repaired_before_validation(self):
        with tempfile.TemporaryDirectory() as tmp:
            paths,before=prepare(Path(tmp));ranked_top(paths)
            for change in (lambda r:r.update(rank=True),lambda r:r.pop('rank'),lambda r:r.update(rank=1)):
                doc=json.loads(before['v212']);change(doc['records'][19]);paths['v212'].write_bytes(builder.json_bytes(doc))
                expected=current_bytes(paths)
                with self.assertRaises(finalizer.FinalOrderError):run_finalizer(paths)
                self.assertEqual(current_bytes(paths),expected)

    def test_missing_mixed_or_tampered_companions_are_not_rebuilt_into_success(self):
        with tempfile.TemporaryDirectory() as tmp:
            paths,before=prepare(Path(tmp),rich=True);ranked_top(paths)
            mutations=[('basis',lambda d:d.update(report_sha256='0'*64)),
                ('basis',lambda d:d['records'].pop('T19')),
                ('basis',lambda d:d.update(owner_watchlist_inherited=True)),
                ('products',lambda d:d['records'][19]['products']['data_report']['pages'].pop()),
                ('products',lambda d:d['records'][0]['products']['card_summary'].update(output_kind='narrative_analysis')),
                ('products',lambda d:d['records'].reverse()),
                ('products',lambda d:d.update(publication_eligible=True)),
                ('returns',lambda d:d.update(report_sha256='0'*64)),
                ('returns',lambda d:d.update(owner_watchlist_inherited=True)),
                ('returns',lambda d:d['records'].update(FOREIGN={})),
                ('returns',lambda d:d['records']['T19'].update(private_extension='SYNTHETIC_NOT_PRIVATE_DATA'))]
            for key,mutate in mutations:
                with self.subTest(companion=key,mutation=mutate.__name__):
                    doc=json.loads(before[key]);mutate(doc);paths[key].write_bytes(builder.json_bytes(doc));expected=current_bytes(paths)
                    with self.assertRaises(finalizer.FinalOrderError):run_finalizer(paths)
                    self.assertEqual(current_bytes(paths),expected);paths[key].write_bytes(before[key])
            for key in ('returns','basis','products'):
                paths[key].unlink()
                with patch.object(finalizer,'atomic_bytes',side_effect=AssertionError('MISSING_INPUT_MUST_NOT_WRITE')):
                    with self.assertRaises(finalizer.FinalOrderError):run_finalizer(paths)
                paths[key].write_bytes(before[key])

    def test_return_observations_require_raw_math_schema_and_projection_not_just_report_hash(self):
        with tempfile.TemporaryDirectory() as tmp:
            paths,before=prepare(Path(tmp));ranked_top(paths)
            original=json.loads(before['returns'])
            changes=[lambda o:o['windows']['two_year'].update(start_adjusted_close=50),
                lambda o:o['windows']['six_month'].update(elapsed_days=True),
                lambda o:o['windows']['two_year'].update(cumulative_return_pct=99),
                lambda o:o['windows']['two_year'].update(actual_start='2024-02-30'),
                lambda o:o['windows']['six_month'].update(status='INSUFFICIENT_HISTORY'),
                lambda o:o.update(retrieved_at='2026-09-09T00:00:00Z'),
                lambda o:o.update(acquisition_status='KNOWN'),
                lambda o:o.update(observed_at='2999-01-01T00:00:00Z'),
                lambda o:o.update(observed_at=False),lambda o:o['request'].update(auto_adjust=1),
                lambda o:o.update(schema_version=True),lambda o:o.update(ticker='FOREIGN')]
            for change in changes:
                with self.subTest(mutation=change.__name__):
                    doc=copy.deepcopy(original);change(doc['records']['T19']);paths['returns'].write_bytes(builder.json_bytes(doc));expected=current_bytes(paths)
                    with self.assertRaises(finalizer.FinalOrderError):run_finalizer(paths)
                    self.assertEqual(current_bytes(paths),expected)

    def test_incomplete_history_is_retained_not_reconstructed(self):
        with tempfile.TemporaryDirectory() as tmp:
            paths,before=prepare(Path(tmp),prices=[(datetime(2026,9,9),100.0)])
            ranked_top(paths);run_finalizer(paths)
            observed=json.loads(paths['returns'].read_bytes())['records']
            self.assertEqual(observed,json.loads(before['returns'])['records'])
            self.assertEqual(observed['T19']['status'],'NO_COMPLETE_RETURN_WINDOW')
            self.assertEqual(observed['T19']['windows']['two_year'],{'status':'INSUFFICIENT_HISTORY'})

    def test_duplicate_keys_bom_and_noncanonical_prior_report_fail_before_writes(self):
        with tempfile.TemporaryDirectory() as tmp:
            paths,before=prepare(Path(tmp));ranked_top(paths)
            for key,body in [('returns',before['returns'].replace(b'{',b'{"schema_version":1,',1)),
                             ('products',b'\xef\xbb\xbf'+before['products']),('basis',b'{')]:
                with self.subTest(key=key):
                    paths[key].write_bytes(body);expected=current_bytes(paths)
                    with self.assertRaises(finalizer.FinalOrderError):run_finalizer(paths)
                    self.assertEqual(current_bytes(paths),expected);paths[key].write_bytes(before[key])
            # Prior arbitrary whitespace is readable, but cannot be guessed or silently normalized during recovery.
            raw=b' '+before['v212'];basis=json.loads(before['basis']);basis['report_sha256']=hashlib.sha256(raw).hexdigest()
            basis_raw=builder.json_bytes(basis)
            paths['basis'].write_bytes(basis_raw);paths['products'].write_bytes(builder.json_bytes(products.build_financial_products(raw,basis_raw)))
            expected=current_bytes(paths)
            with self.assertRaises(finalizer.FinalOrderError):run_finalizer(paths)
            self.assertEqual(current_bytes(paths),expected)

    def test_custom_companion_paths_and_path_aliases_are_checked(self):
        with tempfile.TemporaryDirectory() as tmp:
            paths,_=prepare(Path(tmp));ranked_top(paths)
            for key in ('returns','basis','products'):
                new=Path(tmp)/(key+'.custom.json');paths[key].rename(new);paths[key]=new
            self.assertEqual(run_finalizer(paths),0)
            expected=current_bytes(paths)
            for key in ('returns','basis','products','ledger'):
                wrong=dict(paths);wrong[key]=paths['v212']
                with self.assertRaisesRegex(finalizer.FinalOrderError,'PATH_COLLISION'):run_finalizer(wrong)
                self.assertEqual(current_bytes(paths),expected)
            occupied=Path(tmp)/'occupied';occupied.mkdir();wrong=dict(paths);wrong['basis']=occupied
            with self.assertRaisesRegex(finalizer.FinalOrderError,'PATH_UNADMITTED'):run_finalizer(wrong)
            import os
            alias=Path(tmp)/'alias.json';os.link(paths['basis'],alias)
            with self.assertRaisesRegex(finalizer.FinalOrderError,'PATH_UNADMITTED'):run_finalizer(paths)
            self.assertEqual(current_bytes(paths),expected)

    def test_input_change_after_preparation_is_not_overwritten(self):
        with tempfile.TemporaryDirectory() as tmp:
            paths,_=prepare(Path(tmp));ranked_top(paths);before=current_bytes(paths)
            original=finalizer.rebind_ranked_candidates
            def changed(*args):
                result=original(*args);paths['ledger'].write_bytes(b'{"changed":"SYNTHETIC"}');return result
            with patch.object(finalizer,'rebind_ranked_candidates',side_effect=changed):
                with self.assertRaisesRegex(finalizer.FinalOrderError,'INPUT_CHANGED'):run_finalizer(paths)
            for key in paths:
                if key!='ledger':self.assertEqual(paths[key].read_bytes(),before[key])

    def test_write_failures_have_no_success_and_do_not_pretend_cross_file_rollback(self):
        for failure in range(1,9):
            with self.subTest(write=failure),tempfile.TemporaryDirectory() as tmp:
                paths,_=prepare(Path(tmp));ranked_top(paths);before=current_bytes(paths)
                original=finalizer.atomic_bytes;writes=[]
                def fail(path,body):
                    writes.append(path)
                    if len(writes)==failure:raise OSError('SYNTHETIC_WRITE_FAILURE_NOT_A_SECRET')
                    return original(path,body)
                with patch.object(finalizer,'atomic_bytes',side_effect=fail):
                    with self.assertRaisesRegex(finalizer.FinalOrderError,'CANDIDATE_OR_IO_INVALID'):run_finalizer(paths)
                self.assertEqual(len(writes),failure)
                self.assertEqual(paths['v212'].read_bytes(),before['v212'])  # Report is last; no success/rollback claim.
                self.assertTrue(all(path!=paths['v212'] for path in writes[:-1]))

    def test_partial_candidate_write_cannot_authorize_retry_repair(self):
        with tempfile.TemporaryDirectory() as tmp:
            paths,_=prepare(Path(tmp));ranked_top(paths)
            original=finalizer.atomic_bytes
            def fail(path,body):
                if path==paths['products']:raise OSError('SYNTHETIC_PRODUCT_WRITE_FAILURE')
                return original(path,body)
            with patch.object(finalizer,'atomic_bytes',side_effect=fail):
                with self.assertRaises(finalizer.FinalOrderError):run_finalizer(paths)
            partial=current_bytes(paths)
            with patch.object(finalizer,'atomic_bytes',side_effect=AssertionError('PARTIAL_INPUT_MUST_NOT_BE_REPAIRED')):
                with self.assertRaises(finalizer.FinalOrderError):run_finalizer(paths)
            self.assertEqual(current_bytes(paths),partial)

    def test_real_readback_not_in_memory_order_controls_success(self):
        with tempfile.TemporaryDirectory() as tmp:
            paths,_=prepare(Path(tmp));ranked_top(paths);original=finalizer.atomic_bytes
            def corrupt(path,body):
                return original(path,b'SYNTHETIC_WRONG_BYTES' if path==paths['v212'] else body)
            with patch.object(finalizer,'atomic_bytes',side_effect=corrupt):
                with self.assertRaisesRegex(finalizer.FinalOrderError,'READBACK_FAILED'):run_finalizer(paths)

    def test_standalone_positive_controls_and_intended_missing_companion_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);paths,_=prepare(root);ranked_top(paths);paths['products'].unlink()
            command=[sys.executable,'-B',str(ROOT/'scripts/v213_finalize_rank_coupled_order.py')]
            for arg,marker in [('--help','--financial-products'),('--self-test','V213_FINAL_RANK_COUPLED_ORDER_SELF_TEST = PASS')]:
                proc=subprocess.run([*command,arg],cwd=root,capture_output=True,text=True,encoding='utf-8',timeout=30)
                self.assertEqual(proc.returncode,0,proc.stderr);self.assertIn(marker,proc.stdout);self.assertNotIn('Traceback',proc.stderr)
            before={key:path.read_bytes() for key,path in paths.items() if key!='products'}
            proc=subprocess.run([*command,*arguments(paths)],cwd=root,capture_output=True,text=True,encoding='utf-8',timeout=30)
            self.assertEqual(proc.returncode,1);self.assertEqual(proc.stderr.strip(),'V213_FINAL_RANK_COUPLED_ORDER = FAIL; FINAL_ORDER_CANDIDATE_OR_IO_INVALID')
            self.assertNotIn('Traceback',proc.stderr);self.assertNotIn(' = PASS',proc.stdout)
            self.assertEqual({key:paths[key].read_bytes() for key in before},before)


if __name__=='__main__':unittest.main()
