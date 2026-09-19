"""Actual caller provenance propagation; synthetic public fixtures, never live."""
import copy
import hashlib
import json
import sys
import tempfile
import subprocess
import types
import unittest
from contextlib import ExitStack, redirect_stdout
from datetime import datetime, timedelta, timezone
from io import StringIO
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import build_v212_top20_report as builder
import build_v213_scheduled_top20_report as scheduled
import v21_serenity_top20 as engine
import report_source_acquisition as acquisition
import company_financial_products as products
import test_public_json_refresh as transport
import test_v212_top20_report as financial_fixture
import test_v213_v212_progress_runner as progress_fixture


def actual_cli(root, *, progress=False, age_hours=3, market=None, http_status=200):
    root.mkdir(parents=True, exist_ok=True)
    top=root/'top20.json';top.write_bytes(builder.json_bytes(progress_fixture.provisional_rows()))
    output=root/'report.json';cache=root/'cache';original=builder.build
    helper=financial_fixture.V212Top20ReportTests()
    body=builder.json_bytes(helper.wire_document([helper.fact(), helper.fact(tag='NetIncomeLoss',value=20)]))
    source_time=(datetime.now(timezone.utc)-timedelta(hours=age_hours)).replace(microsecond=0)
    with ExitStack() as stack:
        http=stack.enter_context(engine.session())
        get=stack.enter_context(patch.object(http,'get',return_value=transport.Response(http_status,body)))
        stack.enter_context(patch.object(engine,'CACHE_ROOT',cache))
        if http_status==200:
            with patch.object(engine,'utc_now',return_value=source_time):
                engine.get_json(http,transport.SEC_URL,headers=transport.headers(),cache_path=cache/'companyfacts/CIK0000000001.json',cache_hours=24)
        before=get.call_count
        stack.enter_context(patch.object(builder,'build',side_effect=lambda **kw:original(top20_path=top,**kw)))
        stack.enter_context(patch.object(engine,'session',return_value=http))
        stack.enter_context(patch.object(engine,'sec_headers',side_effect=transport.headers))
        policy={'sec_companyfacts_url':transport.SEC_URL.replace('0000000001','{cik}'),'sec_minimum_interval_seconds':0,'sec_cache_hours':24}
        stack.enter_context(patch.object(engine,'validate_policy',return_value=(policy,{})))
        stack.enter_context(patch.object(progress_fixture.MODULE.preselection,'validate_v213_policy',return_value=(policy,{})))
        stack.enter_context(patch.object(engine,'sec_reference',return_value={f'T{i:02}':{'cik':'0000000001'} for i in range(20)}))
        stack.enter_context(patch.object(builder.snapshot,'validate_top20',side_effect=progress_fixture.MODULE.validate_provisional_top20))
        stack.enter_context(patch.object(builder,'_market_observation',side_effect=market or (lambda *a,**kw:(None,None,'未分類'))))
        stack.enter_context(patch.object(sys,'argv',['build','--output',str(output)]))
        with redirect_stdout(StringIO()):
            code=(progress_fixture.MODULE.main if progress else builder.main)()
        if code!=0:raise AssertionError('ACTUAL_CLI_FAILED')
        return {'report':json.loads(output.read_bytes()),'basis':json.loads((root/'report.financial-evidence-candidate.json').read_bytes()),
                'products':json.loads((root/'report.financial-products-candidate.json').read_bytes()),
                'source_time':source_time.isoformat().replace('+00:00','Z'),'http_calls':get.call_count-before}


def no_orders(report):
    return {'product_version':'2.1.3','records':[{'rank':r['rank'],'ticker':r['ticker'],
            'current_orders':'未揭露（無可靠公開訂單數字）','future_orders_estimate':'無可靠公開預估',
            'orders_as_of':'','orders_confidence':'UNAVAILABLE','current_order_source_urls':[],
            'future_order_source_urls':[]} for r in report['records']]}

def names_for(report):
    return {row['ticker']: f"Synthetic Company {i}" for i, row in enumerate(report['records'])}


class ReportSourceAcquisitionTests(unittest.TestCase):
    def test_actual_cli_retains_three_hour_cache_time_not_assembly_time(self):
        with tempfile.TemporaryDirectory() as tmp:
            result=actual_cli(Path(tmp))
            self.assertEqual(result['http_calls'],0)
            self.assertEqual(result['report']['records'][0]['retrieved_at'],result['source_time'])

    def test_actual_progress_entrypoint_forwards_evidence_sink_and_restores_hooks(self):
        before=builder._market_observation
        with tempfile.TemporaryDirectory() as tmp:
            result=actual_cli(Path(tmp),progress=True)
            self.assertEqual(result['report']['records'][0]['retrieved_at'],result['source_time'])
        self.assertIs(builder._market_observation,before)

    def test_seven_field_producer_refuses_missing_clock_instead_of_generation_fallback(self):
        with tempfile.TemporaryDirectory() as tmp:
            report=actual_cli(Path(tmp))['report'];report['records'][19]['retrieved_at']=None
            with self.assertRaises(scheduled.V213ScheduledReportError):
                scheduled.build(report,no_orders(report),names_for(report))


    def test_default_two_hour_sec_cache_refetches_stale_cache_with_fresh_receipt(self):
        # Production default (no sec_cache_hours in policy) is 2 hours: a 3h-old
        # cache must be re-fetched so scheduled runs bind a fresh SEC receipt.
        root=tempfile.mkdtemp()
        try:
            top=Path(root)/'top20.json';top.write_bytes(builder.json_bytes(progress_fixture.provisional_rows()))
            output=Path(root)/'report.json';cache=Path(root)/'cache'
            original=builder.build
            helper=financial_fixture.V212Top20ReportTests()
            body=builder.json_bytes(helper.wire_document([helper.fact(), helper.fact(tag='NetIncomeLoss',value=20)]))
            source_time=(datetime.now(timezone.utc)-timedelta(hours=3)).replace(microsecond=0)
            with ExitStack() as stack:
                http=stack.enter_context(engine.session())
                get=stack.enter_context(patch.object(http,'get',return_value=transport.Response(200,body)))
                stack.enter_context(patch.object(engine,'CACHE_ROOT',cache))
                with patch.object(engine,'utc_now',return_value=source_time):
                    engine.get_json(http,transport.SEC_URL,headers=transport.headers(),cache_path=cache/'companyfacts/CIK0000000001.json',cache_hours=24)
                before=get.call_count
                stack.enter_context(patch.object(builder,'build',side_effect=lambda **kw:original(top20_path=top,**kw)))
                stack.enter_context(patch.object(engine,'session',return_value=http))
                stack.enter_context(patch.object(engine,'sec_headers',side_effect=transport.headers))
                policy={'sec_companyfacts_url':transport.SEC_URL.replace('0000000001','{cik}'),'sec_minimum_interval_seconds':0}
                stack.enter_context(patch.object(engine,'validate_policy',return_value=(policy,{})))
                stack.enter_context(patch.object(progress_fixture.MODULE.preselection,'validate_v213_policy',return_value=(policy,{})))
                stack.enter_context(patch.object(engine,'sec_reference',return_value={f'T{i:02d}':{'cik':'0000000001'} for i in range(20)}))
                stack.enter_context(patch.object(builder.snapshot,'validate_top20',side_effect=progress_fixture.MODULE.validate_provisional_top20))
                stack.enter_context(patch.object(builder,'_market_observation',side_effect=lambda *a,**kw:(None,None,'未分類')))
                stack.enter_context(patch.object(sys,'argv',['build','--output',str(output)]))
                with redirect_stdout(StringIO()):
                    code=builder.main()
            self.assertEqual(code,0)
            self.assertGreaterEqual(get.call_count-before,1)
            report=json.loads(output.read_bytes())
            fetched=acquisition.utc_time(report['records'][0]['source_acquisition']['profit_summary']['retrieved_at'])
            self.assertGreater(fetched,source_time)
            self.assertLessEqual((datetime.now(timezone.utc)-fetched).total_seconds(),300)
        finally:
            import shutil;shutil.rmtree(root,ignore_errors=True)

    def test_actual_cli_old_cache_cannot_qualify_local_sealed_bundle(self):
        import build_v213_activation_bundle_v2 as seal
        with tempfile.TemporaryDirectory() as tmp:
            result=actual_cli(Path(tmp));seven=scheduled.build(result['report'],no_orders(result['report']),names_for(result['report']))
            envelope,_,_,federation,source=seal._synthetic_documents()
            with self.assertRaisesRegex(seal.SerenityEvidenceError,'stale'):
                seal.build_bundle(envelope,result['report'],seven,federation,source)

    def test_local_sealed_admission_preserves_fresh_clocks_and_rejects_downgrade_unknown_or_mixed_reports(self):
        import build_v213_activation_bundle_v2 as seal
        with tempfile.TemporaryDirectory() as tmp:
            result=actual_cli(Path(tmp),age_hours=.05);five=result['report'];seven=scheduled.build(five,no_orders(five),names_for(five))
            envelope,_,_,federation,source=seal._synthetic_documents()
            value=seal.build_bundle(envelope,five,seven,federation,source)
            stored=json.loads(value['payloads']['v212_top20_report_json'])
            self.assertEqual(stored['records'][19]['retrieved_at'],result['source_time'])
            for mode in ('legacy','unknown','mixed'):
                first=copy.deepcopy(five);second=copy.deepcopy(seven)
                if mode=='legacy':first['schema_version']=1
                if mode=='unknown':
                    row=first['records'][19];row['retrieved_at']=None
                    row['source_acquisition']['profit_summary']=acquisition.field_clock('profit_summary',row['profit_summary'])
                    second['records'][19]['retrieved_at']=None
                if mode=='mixed':second['records'][19]['profit_summary']='獲利；淨利率 99.0%'
                error = seal.SerenityEvidenceError if mode == 'unknown' else seal.core.ActivationBundleError
                with self.assertRaises(error):seal.build_bundle(envelope,first,second,federation,source)

    def test_financial_receipt_and_products_keep_original_time_with_new_completion_cutoff(self):
        with tempfile.TemporaryDirectory() as tmp:
            value=actual_cli(Path(tmp),progress=True)
            report=value['report'];company=value['basis']['records']['T00'];receipt=company['source_acquisition']
            self.assertEqual(company['schema_version'],5)
            self.assertIsNone(company['debt_bridge']['source_retrieved_at'])
            self.assertFalse(company['debt_bridge']['source_refresh_verified'])
            self.assertIsNone(company['liquidity_bridge']['source_retrieved_at'])
            self.assertFalse(company['liquidity_bridge']['source_refresh_verified'])
            self.assertEqual(company['source_retrieved_at'],value['source_time'])
            self.assertEqual(receipt['retrieval_mode'],'BOUND_CACHE')
            self.assertEqual(company['as_of_cutoff'],report['calculation_cutoff'])
            self.assertFalse(company['source_refresh_verified']);self.assertFalse(company['publication_eligible'])
            self.assertLess(acquisition.utc_time(company['source_retrieved_at']),acquisition.utc_time(report['generated_at']))
            self.assertEqual(report['records'][0]['source_acquisition']['profit_summary']['evidence_sha256'],acquisition.digest(receipt))
            for kind in ('card_summary','data_report'):
                text=value['products']['records'][0]['products'][kind]['content_utf8']
                self.assertIn(value['source_time'],text);self.assertIn('BOUND_CACHE',text)
                self.assertIn(receipt['body_sha256'],text)

    def test_known_components_use_oldest_not_newest_clock(self):
        now=(datetime.now(timezone.utc)-timedelta(minutes=10)).replace(microsecond=0).isoformat().replace('+00:00','Z')
        def market(ticker,fallback,*,evidence_sink):
            evidence_sink['source_acquisition']={key:acquisition.field_clock(key,value,retrieved_at=now,evidence_sha256='a'*64)
                for key,value in [('long_term_return_pct',12.0),('short_term_return_pct',4.0),('industry','工業設備')]}
            return .12,.04,'工業設備'
        with tempfile.TemporaryDirectory() as tmp:
            value=actual_cli(Path(tmp),progress=True,market=market)
            self.assertEqual(value['report']['records'][19]['retrieved_at'],value['source_time'])
            seven=scheduled.build(value['report'],no_orders(value['report']),names_for(value['report']),require_known_acquisition=True)
            self.assertEqual(seven['records'][19]['retrieved_at'],value['source_time'])

    def test_unknown_market_keeps_local_values_but_no_freshness_or_publication_fallback(self):
        with tempfile.TemporaryDirectory() as tmp:
            result=actual_cli(Path(tmp),market=lambda *a,**kw:(.12,.04,'工業設備'))
            row=result['report']['records'][0]
            self.assertEqual(row['long_term_return_pct'],12.0)
            self.assertEqual(row['source_acquisition']['industry']['status'],'UNKNOWN')
            self.assertIsNone(row['retrieved_at'])
            baseline=no_orders(result['report']);seven=scheduled.build(result['report'],baseline,names_for(result['report']))
            self.assertIsNone(seven['records'][0]['retrieved_at'])
            with self.assertRaises(scheduled.V213ScheduledReportError):
                scheduled.build(result['report'],baseline,names_for(result['report']),require_known_acquisition=True)
            report=Path(tmp)/'five.json';base=Path(tmp)/'orders.json';out=Path(tmp)/'seven.json';text=Path(tmp)/'seven.txt'
            report.write_bytes(builder.json_bytes(result['report']));base.write_bytes(builder.json_bytes(baseline))
            out.write_text('SYNTHETIC_ORIGINAL');text.write_text('SYNTHETIC_PREVIEW')
            run=subprocess.run([sys.executable,'-B',str(ROOT/'scripts/build_v213_scheduled_top20_report.py'),
                '--v212-report',str(report),'--baseline',str(base),'--output',str(out),'--preview',str(text),'--require-known-acquisition'],capture_output=True,timeout=30)
            self.assertEqual(run.returncode,1)
            self.assertIn(b'SOURCE_ACQUISITION_UNKNOWN',run.stderr)
            self.assertNotIn(b'Traceback',run.stderr)
            self.assertEqual(out.read_text(),'SYNTHETIC_ORIGINAL');self.assertEqual(text.read_text(),'SYNTHETIC_PREVIEW')

    def test_standalone_cli_imports_and_selftests_from_unrelated_working_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            for name,marker in [('build_v212_top20_report.py','V212_TOP20_REPORT_SELF_TEST = PASS'),
                                ('build_v213_scheduled_top20_report.py','V213_SCHEDULED_REPORT_SELF_TEST = PASS'),
                                ('build_v213_activation_bundle_v2.py','V213_ACTIVATION_BUNDLE_V2_SELF_TEST')]:
                for flag in ('--help','--self-test'):
                    run=subprocess.run([sys.executable,'-B',str(ROOT/'scripts'/name),flag],cwd=tmp,capture_output=True,timeout=60)
                    self.assertEqual(run.returncode,0,f'STANDALONE_CLI_FAILED:{name}:{flag}')
                    self.assertNotIn(b'Traceback',run.stderr)
                    if flag=='--self-test':self.assertIn(marker.encode(),run.stdout)

    def test_market_library_return_time_is_not_source_acquisition_time(self):
        fake=types.SimpleNamespace(Ticker=lambda _:types.SimpleNamespace(history=lambda **kw:None,info={'industry':'Semiconductors'}))
        sink={}
        with patch.dict(sys.modules,{'yfinance':fake}):
            result=builder._market_observation('T00','',evidence_sink=sink)
        self.assertEqual(result,(None,None,'半導體'))
        self.assertIsNone(sink['retrieved_at']);self.assertIn('observed_at',sink)
        self.assertEqual(sink['acquisition_status'],'UNKNOWN_PROVIDER_ACQUISITION_TIME')

    def test_retained_orders_keep_old_time_and_missing_time_stays_unknown(self):
        with tempfile.TemporaryDirectory() as tmp:
            result=actual_cli(Path(tmp),age_hours=.05);report=result['report'];baseline=no_orders(report)
            row=baseline['records'][19];old=(datetime.now(timezone.utc)-timedelta(days=1)).replace(microsecond=0).isoformat().replace('+00:00','Z')
            row.update(current_orders='合約證據待核對',orders_confidence='EVIDENCE_BOUND',orders_as_of='2026-07-01',
                       current_order_source_urls=['https://www.sec.gov/example/current'],retrieved_at=old)
            self.assertEqual(scheduled.build(report,baseline,names_for(report))['records'][19]['retrieved_at'],old)
            del row['retrieved_at']
            self.assertIsNone(scheduled.build(report,baseline,names_for(report))['records'][19]['retrieved_at'])
            with self.assertRaises(scheduled.V213ScheduledReportError):scheduled.build(report,baseline,names_for(report),require_known_acquisition=True)
            row['retrieved_at']=report['generated_at']+'suffix'
            with self.assertRaises(scheduled.V213ScheduledReportError):scheduled.build(report,baseline,names_for(report))

    def test_seven_field_completion_can_follow_order_acquisition_without_renewing_operands(self):
        with tempfile.TemporaryDirectory() as tmp:
            report = actual_cli(Path(tmp), age_hours=.05)['report']
        baseline = no_orders(report)
        financial_done = acquisition.utc_time(report['generated_at'])
        order_time = (financial_done + timedelta(seconds=2)).isoformat(timespec='milliseconds').replace('+00:00', 'Z')
        done = (financial_done + timedelta(seconds=4)).isoformat(timespec='milliseconds').replace('+00:00', 'Z')
        row = baseline['records'][19]
        row.update(current_orders='合約證據待核對', orders_confidence='EVIDENCE_BOUND', orders_as_of='2026-07-01',
                   current_order_source_urls=['https://www.sec.gov/example/current'], retrieved_at=order_time)
        with patch.object(scheduled, '_completion_time', return_value=done):
            seven = scheduled.build(report, baseline, names_for(report), require_known_acquisition=True)
            self.assertEqual(seven['generated_at'], done)
            self.assertEqual(seven['records'][19]['retrieved_at'], report['records'][19]['retrieved_at'])
            self.assertNotEqual(seven['records'][19]['retrieved_at'], done)
            row['retrieved_at'] = (financial_done + timedelta(seconds=5)).isoformat(timespec='milliseconds').replace('+00:00', 'Z')
            with self.assertRaises(scheduled.V213ScheduledReportError):
                scheduled.build(report, baseline, names_for(report), require_known_acquisition=True)
        with patch.object(scheduled, '_completion_time', return_value='2000-01-01T00:00:00Z'):
            with self.assertRaises(scheduled.V213ScheduledReportError):
                scheduled.build(report, baseline, names_for(report))

    def test_reconciliation_cli_cannot_launder_unknown_order_clock_into_strict_builder(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            report = actual_cli(root / 'financial', age_hours=.05)['report']
            baseline = no_orders(report)
            baseline['records'][19].update(current_orders='合約證據待核對', orders_confidence='EVIDENCE_BOUND',
                orders_as_of='2026-07-01', current_order_source_urls=['https://www.sec.gov/example/current'])
            five = root / 'five.json'; old = root / 'old.json'; orders = root / 'orders.json'
            top = root / 'top.json'; output = root / 'seven.json'; preview = root / 'seven.txt'
            five.write_bytes(builder.json_bytes(report)); old.write_bytes(builder.json_bytes(baseline))
            top.write_bytes(builder.json_bytes([{'ticker': ticker, 'name': name} for ticker, name in names_for(report).items()]))
            output.write_text('SYNTHETIC_ORIGINAL'); preview.write_text('SYNTHETIC_PREVIEW')
            # Run both real CLIs, not just the final formatter. Same membership
            # must require no provider calls or live/default cache paths.
            first = subprocess.run([sys.executable, '-B', str(ROOT / 'scripts/reconcile_v213_order_evidence.py'),
                '--v212-report', str(five), '--baseline', str(old), '--output', str(orders),
                '--receipt', str(root / 'receipt.json')], cwd=tmp, capture_output=True, timeout=30)
            self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
            second = subprocess.run([sys.executable, '-B', str(ROOT / 'scripts/build_v213_scheduled_top20_report.py'),
                '--v212-report', str(five), '--baseline', str(orders), '--top20', str(top), '--output', str(output),
                '--preview', str(preview), '--require-known-acquisition'], cwd=tmp, capture_output=True, timeout=30)
            # The launch reconciler now withholds the unbound retained claim.
            # A strict candidate with explicit UNAVAILABLE orders is legitimate;
            # it must not publish the old value or invent an acquisition clock.
            self.assertEqual(second.returncode, 0, second.stdout + second.stderr)
            produced = json.loads(output.read_bytes())
            row = produced['records'][19]
            self.assertEqual(row['current_orders'], '未揭露（無可靠公開訂單數字）')
            self.assertEqual(row['future_orders_estimate'], '無可靠公開預估')
            self.assertEqual(row['orders_confidence'], 'UNAVAILABLE')
            self.assertEqual(row['current_order_source_urls'], [])
            self.assertEqual(row['future_order_source_urls'], [])
            self.assertIsNone(json.loads(orders.read_bytes())['records'][19]['retrieved_at'])
            self.assertEqual(row['retrieved_at'], report['records'][19]['retrieved_at'])
            self.assertNotIn('合約證據待核對', preview.read_text(encoding='utf-8'))
            self.assertIn(b'publication_qualified=false', second.stdout)
            self.assertIn(row['ticker'], json.loads((root / 'receipt.json').read_bytes())['withheld_retained'])
            self.assertEqual(json.loads(old.read_bytes()), baseline)

    def test_clock_value_binding_omissions_and_future_or_coerced_times_refuse(self):
        with tempfile.TemporaryDirectory() as tmp:
            valid=actual_cli(Path(tmp))['report']
        mutations=[lambda d:d['records'][19].update(retrieved_at=d['generated_at']),
                   lambda d:d['records'][19]['source_acquisition']['profit_summary'].update(value='不同摘要'),
                   lambda d:d['records'][19]['source_acquisition'].pop('industry'),
                   lambda d:d['records'][19]['source_acquisition']['profit_summary'].update(evidence_sha256='bad'),
                   lambda d:d.update(schema_version=True),lambda d:d['records'][0].update(rank=True)]
        for mutate in mutations:
            doc=copy.deepcopy(valid);mutate(doc)
            with self.assertRaises(acquisition.SourceAcquisitionError):acquisition.validate_report_acquisition(doc)
        for stamp in [None,True,[],{},'2026-02-31T00:00:00Z','2026-09-10T13:00:00+00:00','9999-01-01T00:00:00Z']:
            doc=copy.deepcopy(valid);doc['records'][0]['source_acquisition']['profit_summary']['retrieved_at']=stamp
            with self.assertRaises(acquisition.SourceAcquisitionError):acquisition.validate_report_acquisition(doc)

    def test_receipt_sink_is_cleared_on_denial_or_preflight_failure(self):
        helper=financial_fixture.V212Top20ReportTests();body=builder.json_bytes(helper.wire_document([helper.fact()]))
        with tempfile.TemporaryDirectory() as tmp,engine.session() as http:
            path=Path(tmp)/'raw.json';sink={'previous':'SYNTHETIC_SUCCESS'}
            with patch.object(http,'get',return_value=transport.Response(body=body)):
                engine.get_json(http,transport.SEC_URL,headers=transport.headers(),cache_path=path,cache_hours=0,receipt_sink=sink)
            self.assertEqual(sink['retrieval_mode'],'DIRECT_HTTP')
            self.assertEqual(sink['body_sha256'],hashlib.sha256(body).hexdigest())
            with patch.object(http,'get',return_value=transport.Response(403)):
                with self.assertRaises(engine.PipelineError):engine.get_json(http,transport.SEC_URL,headers=transport.headers(),cache_path=path,cache_hours=0,receipt_sink=sink)
            self.assertEqual(sink,{})
            sink.update(previous='SYNTHETIC_SUCCESS')
            with self.assertRaises(engine.PipelineError):engine.get_json(http,'https://example.invalid/',headers=transport.headers(),cache_path=path,cache_hours=24,receipt_sink=sink)
            self.assertEqual(sink,{})

    def test_changed_records_or_company_identity_cannot_borrow_a_receipt(self):
        helper=financial_fixture.V212Top20ReportTests();body=builder.json_bytes(helper.wire_document([helper.fact()]))
        with tempfile.TemporaryDirectory() as tmp,engine.session() as http,patch.object(engine,'CACHE_ROOT',Path(tmp)):
            sink={};policy={'sec_companyfacts_url':transport.SEC_URL,'sec_minimum_interval_seconds':0}
            with patch.object(http,'get',return_value=transport.Response(body=body)):
                rows=engine.sec_companyfacts({'ticker':'T00','official':{'cik':'0000000001'}},policy,http,transport.headers(),receipt_sink=sink)
            acquisition.validate_company_receipt(sink,cik='0000000001',records=rows)
            changed=copy.deepcopy(rows);changed[0]['value']+=1
            with self.assertRaises(acquisition.SourceAcquisitionError):acquisition.validate_company_receipt(sink,cik='0000000001',records=changed)
            with self.assertRaises(acquisition.SourceAcquisitionError):acquisition.validate_company_receipt(sink,cik='0000000002',records=rows)
            bad={**sink,'private_extension':'SYNTHETIC_PRIVATE_MARKER'}
            with self.assertRaises(acquisition.SourceAcquisitionError):acquisition.validate_company_receipt(bad,cik='0000000001')

    def test_financial_product_reader_rejects_changed_acquisition_reference(self):
        with tempfile.TemporaryDirectory() as tmp:
            value=actual_cli(Path(tmp));report=builder.json_bytes(value['report']);basis=value['basis']
            basis['records']['T00']['source_acquisition']['body_sha256']='0'*64
            with self.assertRaises(products.FinancialProductsError):products.build_financial_products(report,builder.json_bytes(basis))


if __name__=='__main__':unittest.main()
