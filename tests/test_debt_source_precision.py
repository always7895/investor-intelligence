"""Synthetic source files through actual report/progress/finalizer callers; no live I/O."""
import base64
import copy
import hashlib
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout, redirect_stderr
from datetime import datetime, timezone
from io import StringIO
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT/'scripts'), str(ROOT/'tests')]
import test_report_source_acquisition as fixture
import test_v212_top20_report as financial
import company_financial_products as products
builder = fixture.builder
ACTUAL_CLI = fixture.actual_cli
NOW = datetime(2026, 9, 11, 8, tzinfo=timezone.utc)


class Clock(datetime):
    @classmethod
    def now(cls, tz=None):
        return NOW if tz else NOW.replace(tzinfo=None)


def facts(profit=True):
    h = financial.V212Top20ReportTests()
    values = [h.fact(tag=tag, value=value, start=None) for tag, value in
              [('LongTermDebtCurrent', 11007000000), ('LongTermDebtNoncurrent', 71340000000),
               ('LongTermDebt', 82300000000)]]
    return values + ([h.fact(), h.fact(tag='OperatingIncomeLoss', value=12), h.fact(tag='NetIncomeLoss', value=20)] if profit else [])


def bundle():
    prefix = 'https://www.sec.gov/Archives/edgar/data/1/000000000126000001/'
    namespaces = ('xmlns:x="http://www.xbrl.org/2003/instance" xmlns:us="http://fasb.org/us-gaap/2025" '
                  'xmlns:dei="http://xbrl.sec.gov/dei/2025" xmlns:iso="http://www.xbrl.org/2003/iso4217" '
                  'xmlns:ix="http://www.xbrl.org/2013/inlineXBRL" '
                  'xmlns:ixt="http://www.xbrl.org/inlineXBRL/transformation/2020-02-12"')
    context = ('<x:context id="c"><x:entity><x:identifier scheme="http://www.sec.gov/CIK">0000000001</x:identifier>'
               '</x:entity><x:period><x:instant>2026-06-30</x:instant></x:period></x:context>'
               '<x:unit id="usd"><x:measure>iso:USD</x:measure></x:unit>')
    identity = {'EntityCentralIndexKey':'0000000001', 'DocumentType':'10-K', 'DocumentFiscalYearFocus':'2026',
                'DocumentFiscalPeriodFocus':'FY', 'DocumentPeriodEndDate':'2026-06-30', 'AmendmentFlag':'false'}
    xml, inline = [], []
    for index, (tag, value) in enumerate(identity.items()):
        xml.append(f'<dei:{tag} id="d{index}" contextRef="c">{value}</dei:{tag}>')
        inline.append(f'<ix:nonNumeric id="d{index}" contextRef="c" name="dei:{tag}">{value}</ix:nonNumeric>')
    for index, (tag, value, text, scale, decimals) in enumerate([
        ('LongTermDebtCurrent',11007000000,'11,007','6','-6'),
        ('LongTermDebtNoncurrent',71340000000,'71,340','6','-6'),
        ('LongTermDebt',82300000000,'82.3','9','-8')]):
        attrs = f'id="f{index}" contextRef="c" unitRef="usd" decimals="{decimals}"'
        xml.append(f'<us:{tag} {attrs}>{value}</us:{tag}>')
        fmt = ' format="ixt:num-dot-decimal"' if index < 2 else ''
        inline.append(f'<ix:nonFraction {attrs} name="us:{tag}" scale="{scale}"{fmt}>{text}</ix:nonFraction>')
    index_body = builder.json_bytes({'directory':{'name':'/Archives/edgar/data/1/000000000126000001',
                                    'item':[{'name':n} for n in ('synthetic.htm','synthetic_htm.xml')]}})
    bodies = {'index':('index.json',index_body),
              'inline':('synthetic.htm',f'<html xmlns="http://www.w3.org/1999/xhtml" {namespaces}><body><ix:header><ix:resources>{context}</ix:resources></ix:header>{"".join(inline)}</body></html>'.encode()),
              'instance':('synthetic_htm.xml',f'<x:xbrl {namespaces}>{context}{"".join(xml)}</x:xbrl>'.encode())}
    return {'schema_version':1, 'cik':'0000000001', 'accession':'0000000001-26-000001', 'documents':{
        role:{'url':prefix+name,'retrieved_at':'2026-09-10T12:00:00Z',
              'body_sha256':hashlib.sha256(raw).hexdigest(),'body_base64':base64.b64encode(raw).decode('ascii')}
        for role,(name,raw) in bodies.items()}}


def change_document(value, role, before, after):
    item = value['documents'][role]
    raw = base64.b64decode(item['body_base64'])
    assert before.encode() in raw
    raw = raw.replace(before.encode(), after.encode())
    item.update(body_sha256=hashlib.sha256(raw).hexdigest(), body_base64=base64.b64encode(raw).decode('ascii'))


def cli(root, packet=None, *, progress=False, profit=True):
    root.mkdir(parents=True, exist_ok=True)
    original_main = builder.main
    wire = financial.V212Top20ReportTests.wire_document
    def main():
        if packet is not None:
            path = root/'precision-input.json'
            path.write_bytes(builder.json_bytes(packet))
            sys.argv += ['--debt-precision-bundle',str(path)]
        return original_main()
    with patch.object(builder,'main',side_effect=main), patch.object(builder,'datetime',Clock), \
            patch.object(fixture,'datetime',Clock), patch.object(builder.base,'utc_now',return_value=NOW), \
            patch.object(financial.V212Top20ReportTests,'wire_document',lambda self,rows:wire(self,facts(profit))):
        return ACTUAL_CLI(root,progress=progress)


class DebtSourcePrecisionTests(unittest.TestCase):
    def test_actual_report_and_progress_bind_original_precision_without_reconciling_points(self):
        for progress in (False, True):
            with self.subTest(progress=progress), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                prior = cli(root/'legacy',progress=progress)
                value = cli(root/'bound',bundle(),progress=progress)
                self.assertEqual(value['http_calls'],0)
                self.assertEqual(value['report'],prior['report'])
                company = value['basis']['records']['T00']
                self.assertEqual(company['schema_version'],6,'ACTUAL_CLI_HAS_NO_SOURCE_BOUND_PRECISION_INPUT')
                review = company['debt_precision']
                self.assertEqual(review['status'],'SOURCE_BOUND_CONDITIONAL_CHECK')
                self.assertEqual([f['decimals'] for f in review['facts']],['-6','-6','-8'])
                self.assertEqual(review['point_difference'],'47000000')
                self.assertEqual(review['modes']['round-to-nearest']['status'],'OVERLAP')
                self.assertEqual(review['modes']['truncation']['status'],'OVERLAP')
                self.assertEqual(company['debt_bridge'],prior['basis']['records']['T00']['debt_bridge'])
                self.assertEqual(company['debt_bridge']['reported_total_check']['status'],'CONFLICT')
                self.assertEqual(company['source_acquisition'],prior['basis']['records']['T00']['source_acquisition'])
                for product in value['products']['records'][0]['products'].values():
                    self.assertIn('原始精度屬性已核對',product['content_utf8'])
                    self.assertNotIn('原始披露精度尚未核驗',product['content_utf8'])
                    self.assertNotIn('資料取得時間未驗證',product['content_utf8'])
                    self.assertIn('不以猜測容差放行',product['content_utf8'])
                    self.assertIn('CONFLICT',product['content_utf8'])
                    self.assertFalse(product['publication_eligible']);self.assertFalse(product['complete'])
                    self.assertIsNone(product['snapshot_run_id'])
                    self.assertEqual('\n\n'.join(p['text'] for p in product['pages']),product['content_utf8'])
                products.verify_financial_products(builder.json_bytes(value['products']),builder.json_bytes(value['report']),
                    builder.json_bytes(value['basis']),precision_bundle=builder.json_bytes(bundle()))

    def test_extra_inline_fact_cannot_hide_behind_a_matching_instance_id(self):
        for kind in ('nonFraction','nonNumeric','fraction'):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as tmp:
                packet = bundle()
                change_document(packet,'inline','</body>',
                    f'<ix:{kind} id="extra" contextRef="c" unitRef="usd" decimals="-6" name="us:LongTermDebtCurrent" scale="6" format="ixt:num-dot-decimal">99,999</ix:{kind}></body>')
                value = cli(Path(tmp),packet)
                review = value['basis']['records']['T00']['debt_precision']
                self.assertEqual(review['status'],'WITHHELD','UNMATCHED_INLINE_DUPLICATE_FALSE_PRECISION_BINDING')
                self.assertIn('operating_margin',value['products']['records'][0]['products']['narrative_analysis']['claim_refs'])

    def test_source_clocks_before_filing_or_after_cutoff_cannot_be_bound(self):
        for instant in ('2026-01-01T00:00:00Z','2026-09-11T08:00:01Z'):
            with self.subTest(instant=instant), tempfile.TemporaryDirectory() as tmp:
                packet=bundle();packet['documents']['inline']['retrieved_at']=instant
                value=cli(Path(tmp),packet)
                self.assertEqual(value['basis']['records']['T00']['debt_precision']['status'],'WITHHELD',
                                 'SOURCE_FILE_CLOCK_NOT_POSSIBLE_FOR_SELECTED_FILING')
                self.assertEqual(value['basis']['records']['T00']['source_retrieved_at'],'2026-09-11T05:00:00Z')

    def test_unsupported_source_shapes_fail_only_precision_preserving_profit_and_debt_conflict(self):
        mutations = [
            ('instance','decimals="-6"','decimals="-18" precision="2"'),
            ('instance','decimals="-6"','decimals="-99"'),
            ('instance','decimals="-6"','decimals="-8"'),
            ('inline','scale="6"','scale="7"'),
            ('inline','ixt:num-dot-decimal','ixt:fixed-zero'),
            ('inline','transformation/2020-02-12','transformation/2015-02-26'),
            ('inline','>11,007<','>11,008<'),
            ('inline','>11,007<','><span>11,007</span><'),
            ('inline','id="f0"','id="f0" sign="-"'),
            ('inline','id="f0"','id="f0" continuedAt="other"'),
            ('inline','<ix:resources>','<ix:resources target="other">'),
            ('instance','>0000000001<','>0000000002<'),
            ('instance','iso:USD','iso:EUR'),
            ('instance','<x:instant>2026-06-30</x:instant>','<x:startDate>2025-07-01</x:startDate><x:endDate>2026-06-30</x:endDate>'),
            ('instance','</x:entity>','<x:segment/></x:entity>'),
            ('instance','<us:LongTermDebtCurrent','<us:LongTermDebtCurrent xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xsi:nil="true"'),
            ('instance','id="f0"','id="f1"'),
            ('instance','<x:xbrl','<!DOCTYPE x [<!ENTITY e SYSTEM "https://example.invalid/NEVER_FETCH">]><x:xbrl'),
        ]
        for role, before, after in mutations:
            with self.subTest(role=role, after=after), tempfile.TemporaryDirectory() as tmp:
                packet=bundle();change_document(packet,role,before,after)
                value=cli(Path(tmp),packet)
                company=value['basis']['records']['T00']
                self.assertEqual(company['debt_precision']['status'],'WITHHELD')
                self.assertEqual(company['debt_bridge']['reported_total_check']['status'],'CONFLICT')
                self.assertEqual(value['report']['records'][0]['profit_summary'],'獲利；營益率 12.0%；淨利率 20.0%')
                self.assertEqual(value['products']['records'][0]['products']['narrative_analysis']['status'],'AVAILABLE_PARTIAL')
                self.assertEqual(value['http_calls'],0)
                products.verify_financial_products(builder.json_bytes(value['products']),builder.json_bytes(value['report']),
                    builder.json_bytes(value['basis']),precision_bundle=builder.json_bytes(packet))

    def test_full_replay_requires_original_bundle_and_rejects_tampered_flags_facts_and_modes(self):
        with tempfile.TemporaryDirectory() as tmp:
            value=cli(Path(tmp),bundle())
        report,basis,rendered=(builder.json_bytes(value[k]) for k in ('report','basis','products'))
        with self.assertRaisesRegex(products.FinancialProductsError,'PRECISION_SOURCE_REQUIRED'):
            products.verify_financial_products(rendered,report,basis)
        changes=[('bundle_sha256','0'*64),('financial_reconciliation_admitted',True),('issuer_rounding_mode_verified',True),
                 ('point_difference','0'),('facts',[]),('modes',{}),('as_of_cutoff','2026-09-10T00:00:00Z')]
        for key, changed in changes:
            with self.subTest(key=key):
                altered=copy.deepcopy(value['basis']);altered['records']['T00']['debt_precision'][key]=changed
                with self.assertRaisesRegex(products.FinancialProductsError,'PRECISION_MISMATCH'):
                    products.build_financial_products(report,builder.json_bytes(altered),precision_bundle=builder.json_bytes(bundle()))
        modified=bundle();change_document(modified,'inline','>11,007<','>11,008<')
        with self.assertRaisesRegex(products.FinancialProductsError,'PRECISION_MISMATCH'):
            products.verify_financial_products(rendered,report,basis,precision_bundle=builder.json_bytes(modified))
        altered=copy.deepcopy(value['products']);altered['records'][0]['products']['data_report']['pages'][0]['text']='SYNTHETIC_CHANGED_PAGE'
        with self.assertRaisesRegex(products.FinancialProductsError,'OUTPUT_MISMATCH'):
            products.verify_financial_products(builder.json_bytes(altered),report,basis,precision_bundle=builder.json_bytes(bundle()))

    def test_bundle_envelope_and_output_collision_refuse_before_collection_or_writes(self):
        invalid=[]
        for key, changed in [('schema_version',True),('cik','bad'),('accession','wrong')]:
            packet=bundle();packet[key]=changed;invalid.append(builder.json_bytes(packet))
        for key, changed in [('url','https://example.invalid/NEVER_FETCH'),('body_sha256','0'*64),('body_base64','not-base64')]:
            packet=bundle();packet['documents']['inline'][key]=changed;invalid.append(builder.json_bytes(packet))
        packet=bundle();change_document(packet,'index','/Archives/edgar/data/1/','/Archives/edgar/data/2/');invalid.append(builder.json_bytes(packet))
        invalid += [b'{"schema_version":1,"schema_version":1}',b'[]',b' ' * 4_194_305]
        for index, raw in enumerate(invalid):
            with self.subTest(index=index), tempfile.TemporaryDirectory() as tmp:
                root=Path(tmp);source=root/'source.json';source.write_bytes(raw);output=root/'report.json';output.write_bytes(b'SYNTHETIC_ORIGINAL')
                with patch.object(sys,'argv',['build','--output',str(output),'--debt-precision-bundle',str(source)]), \
                        patch.object(builder,'build',side_effect=AssertionError('INVALID_BUNDLE_MUST_NOT_COLLECT')) as build, redirect_stdout(StringIO()):
                    self.assertEqual(builder.main(),1)
                build.assert_not_called();self.assertEqual(output.read_bytes(),b'SYNTHETIC_ORIGINAL');self.assertEqual(source.read_bytes(),raw)
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'same.json';raw=builder.json_bytes(bundle());path.write_bytes(raw)
            with patch.object(sys,'argv',['build','--output',str(path),'--debt-precision-bundle',str(path)]), \
                    patch.object(builder,'build',side_effect=AssertionError('INPUT_MUST_NOT_BE_OUTPUT')) as build,redirect_stdout(StringIO()):
                self.assertEqual(builder.main(),1)
            build.assert_not_called();self.assertEqual(path.read_bytes(),raw)

    def test_conditional_interval_endpoints_grid_and_decimal_context_are_exact(self):
        from fractions import Fraction as F
        from decimal import localcontext, Inexact, Rounded
        import debt_source_precision as precision
        for digits in (2,28):
            with localcontext() as ctx:
                ctx.prec=digits;ctx.traps[Inexact]=True;ctx.traps[Rounded]=True;ctx.clear_flags()
                self.assertEqual(precision.interval(F(5000),'-3','round-to-nearest'),(F(4500),F(5500),True,True))
                self.assertEqual(precision.interval(F(5000),'-3','truncation'),(F(5000),F(6000),True,False))
                self.assertEqual(precision.interval(F(-5000),'-3','truncation'),(F(-6000),F(-5000),False,True))
                self.assertEqual(precision.interval(F(0),'-3','truncation'),(F(-1000),F(1000),False,False))
                self.assertEqual(precision.interval(F('0.1'),'INF','truncation'),(F('0.1'),F('0.1'),True,True))
                for mode in ('round-to-nearest','truncation'):
                    with self.assertRaisesRegex(precision.DebtPrecisionError,'DIGITS_EXCEED_DECIMALS'):
                        precision.interval(F(5100),'-3',mode)
                a=precision.interval(F(5000),'-3','round-to-nearest');b=precision.interval(F(6000),'-3','round-to-nearest')
                self.assertTrue(precision._overlaps(a,b))  # closed endpoint contact counts
                self.assertFalse(precision._overlaps(precision.interval(F(5000),'-3','truncation'),precision.interval(F(6000),'-3','truncation')))
                self.assertFalse(any(ctx.flags.values()))

    def test_precision_diagnostic_alone_does_not_qualify_narrative_or_legacy_inputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            value=cli(Path(tmp)/'bound',bundle(),profit=False)
            legacy=cli(Path(tmp)/'legacy',profit=False)
        self.assertEqual(value['products']['records'][0]['products']['narrative_analysis']['status'],'UNAVAILABLE')
        self.assertEqual(legacy['basis']['records']['T00']['schema_version'],5)
        report=builder.json_bytes(legacy['report']);basis=builder.json_bytes(legacy['basis'])
        products.verify_financial_products(builder.json_bytes(legacy['products']),report,basis)
        with self.assertRaisesRegex(products.FinancialProductsError,'PRECISION_DOWNGRADE'):
            products.build_financial_products(report,basis,precision_bundle=builder.json_bytes(bundle()))
        planted=copy.deepcopy(legacy['basis']);planted['records']['T00']['debt_precision']=value['basis']['records']['T00']['debt_precision']
        with self.assertRaises(products.FinancialProductsError):products.build_financial_products(report,builder.json_bytes(planted))

    def test_actual_standalone_finalizer_requires_pinned_bundle_preserves_it_and_all_clocks(self):
        import subprocess
        import test_ranked_report_candidates as ranked
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);value=cli(root,bundle(),progress=True)
            paths={'top20':root/'top20.json','v212':root/'report.json','v213':root/'seven.json','federation':root/'federation.json',
                   'source_audit':root/'source.json','ledger':root/'ledger.json','returns':root/'report.return-evidence-candidate.json',
                   'basis':root/'report.financial-evidence-candidate.json','products':root/'report.financial-products-candidate.json'}
            paths['v213'].write_bytes(builder.json_bytes(fixture.scheduled.build(value['report'],fixture.no_orders(value['report']),fixture.names_for(value['report']),return_evidence=fixture.market_anchors(value['report']))))
            for name,key in [('federation','ticker_sources'),('source_audit','records'),('ledger','records')]:
                paths[name].write_bytes(builder.json_bytes({key:[{'rank':i+1,'ticker':f'T{i:02d}'} for i in range(20)]}))
            ranked.ranked_top(paths);before=ranked.current_bytes(paths);source=root/'precision-input.json';source_before=source.read_bytes()
            command=[sys.executable,'-B',str(ROOT/'scripts/v213_finalize_rank_coupled_order.py'),*ranked.arguments(paths)]
            rejected=subprocess.run(command,cwd=root,capture_output=True,timeout=30)
            self.assertEqual(rejected.returncode,1);self.assertNotIn(b'Traceback',rejected.stderr)
            self.assertEqual(ranked.current_bytes(paths),before)
            accepted=subprocess.run(command+['--debt-precision-bundle',str(source)],cwd=root,capture_output=True,timeout=30)
            self.assertEqual(accepted.returncode,0,accepted.stderr);self.assertEqual(source.read_bytes(),source_before)
            self.assertEqual(json.loads(paths['basis'].read_bytes())['records'],json.loads(before['basis'])['records'])
            self.assertEqual(json.loads(paths['v212'].read_bytes())['records'][0]['ticker'],'T19')
            old={v['ticker']:v['products'] for v in value['products']['records']}
            for row in json.loads(paths['products'].read_bytes())['records']:
                for kind,item in row['products'].items():
                    self.assertEqual(item['content_utf8'],old[row['ticker']][kind]['content_utf8'])
            products.verify_financial_products(paths['products'].read_bytes(),paths['v212'].read_bytes(),paths['basis'].read_bytes(),precision_bundle=source_before)

    def test_supported_prefix_date_subset_and_inf_are_not_guessed_issuer_modes(self):
        packet=bundle()
        change_document(packet,'inline','ixt:','renamed:')
        change_document(packet,'inline','xmlns:ixt=','xmlns:renamed=')
        change_document(packet,'inline','id="d4" contextRef="c" name="dei:DocumentPeriodEndDate"',
                        'id="d4" contextRef="c" name="dei:DocumentPeriodEndDate" format="renamed:date-monthname-day-year-en"')
        change_document(packet,'inline','>2026-06-30</ix:nonNumeric>','>June\u00a030, 2026</ix:nonNumeric>')
        for role in ('inline','instance'):
            change_document(packet,role,'decimals="-6"','decimals="INF"')
            change_document(packet,role,'decimals="-8"','decimals="INF"')
        with tempfile.TemporaryDirectory() as tmp:value=cli(Path(tmp),packet)
        review=value['basis']['records']['T00']['debt_precision']
        self.assertEqual(review['status'],'SOURCE_BOUND_CONDITIONAL_CHECK')
        self.assertTrue(all(m['status']=='DISJOINT' for m in review['modes'].values()))
        self.assertFalse(review['issuer_rounding_mode_verified']);self.assertFalse(review['taxonomy_calculation_verified'])
        self.assertFalse(review['financial_reconciliation_admitted'])

    def test_source_input_change_before_writes_cannot_replace_existing_outputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);paths=[root/('report'+suffix) for suffix in ('.json','.financial-evidence-candidate.json',
                                 '.financial-products-candidate.json','.return-evidence-candidate.json')]
            for path in paths:path.write_bytes(b'SYNTHETIC_EXISTING_OUTPUT')
            original=builder.build_financial_products
            def change_after_render(*args,**kwargs):
                value=original(*args,**kwargs)
                path=root/'precision-input.json';path.write_bytes(path.read_bytes()+b'\n')
                return value
            with patch.object(builder,'build_financial_products',side_effect=change_after_render):
                with self.assertRaisesRegex(AssertionError,'ACTUAL_CLI_FAILED'):cli(root,bundle())
            self.assertTrue(all(p.read_bytes()==b'SYNTHETIC_EXISTING_OUTPUT' for p in paths))

    def test_native_caller_refuses_missing_module_before_any_child_or_contact_read(self):
        import subprocess
        for host in ('C:/Windows/System32/WindowsPowerShell/v1.0/powershell.exe','C:/Program Files/PowerShell/7/pwsh.exe'):
            with self.subTest(host=host), tempfile.TemporaryDirectory() as tmp:
                self.assertTrue(Path(host).is_file(),'REQUIRED_NATIVE_HOST_MISSING')
                root=Path(tmp);app=root/'synthetic-app';app.mkdir()
                for relative in ('run-v211-evidence-gated.ps1','scripts/build_v212_top20_report.py','scripts/historical_return_evidence.py',
                                 'scripts/v213_v21_progress_runner.py','scripts/company_financial_products.py',
                                 'scripts/report_source_acquisition.py','sync-v21-public-snapshot.ps1','sync-v212-top20-report.ps1'):
                    path=app/relative;path.parent.mkdir(parents=True,exist_ok=True)
                    path.write_text('throw "SYNTHETIC_CHILD_MUST_NOT_EXECUTE"',encoding='utf-8')
                (root/'install-state.json').write_bytes(builder.json_bytes({'application_root':str(app),'python_executable':sys.executable,
                    'user_config_root':str(root/'NONEXISTENT_SYNTHETIC_CONFIG')}))
                result=subprocess.run([host,'-NoLogo','-NoProfile','-NonInteractive','-File',str(ROOT/'run-v212-local.ps1'),
                                       '-BaseInstallRoot',str(root),'-NoSync','-NonInteractive'],cwd=root,capture_output=True,timeout=30)
                self.assertNotEqual(result.returncode,0)
                combined=result.stdout+result.stderr
                self.assertIn(b'debt_source_precision.py',combined)
                self.assertNotIn(b'SYNTHETIC_CHILD_MUST_NOT_EXECUTE',combined)
                self.assertFalse((root/'NONEXISTENT_SYNTHETIC_CONFIG').exists())


if __name__ == '__main__':
    unittest.main()
