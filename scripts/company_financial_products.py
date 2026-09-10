"""Distinct LOCAL financial-product components for the existing report CLI.

Not a collector, scorer, sealed manifest or complete company research report.
Only retained SEC operands are used; market returns and private data are not.
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime
from decimal import Decimal
from typing import Any

from v213_v21_progress_runner import profitability_evidence, validate_cashflow_evidence, FINANCIAL_V2_LIMITATIONS
from report_source_acquisition import (SourceAcquisitionError, validate_report_acquisition,
                                       validate_company_receipt, digest, utc_time)

KINDS = ('card_summary', 'data_report', 'narrative_analysis')
LABELS = {'revenue_growth': '年度營收成長', 'gross_margin': '毛利率',
          'operating_margin': '營益率', 'net_margin': '淨利率'}
FORMULAS = {key: 'numerator / denominator - 1' if key == 'revenue_growth' else 'numerator / denominator' for key in LABELS}
WITHHELD = {'MISSING_OPERAND', 'INVALID_OPERAND', 'CONFLICTING_OPERAND',
            'WITHHELD_NOT_COMPARABLE_OR_NONPOSITIVE_DENOMINATOR'}
FACT_KEYS = set('cik taxonomy tag unit value start end filed form fiscal_year accession_number record_url'.split())
ROW_KEYS = set('schema_version rank ticker long_term_return_pct short_term_return_pct industry profit_summary long_term_window short_term_window market_source profit_source retrieved_at provider_scope owner_watchlist_inherited'.split())
REPORT_KEYS = set('schema_version product_version generated_at display_columns long_term_definition short_term_definition records provider_scope owner_watchlist_inherited'.split())
BASIS_KEYS = set('schema_version status publication_eligible provider_scope owner_watchlist_inherited generated_at report_sha256 hash_scope records'.split())
COMPANY_KEYS = set('schema_version status cik as_of_cutoff provider_scope publication_eligible source_retrieved_at source_lineage source_refresh_verified metrics limitations'.split())
LIMITATIONS = ['COMPANYFACTS_CONTEXT_AND_RESTATEMENT_REVIEW_INCOMPLETE',
              'NOT_INDEPENDENT_COMPANY_CLAIM_CORROBORATION',
              'NO_CASHFLOW_CAPACITY_ORDERS_DILUTION_OR_VALUATION_BRIDGE']
NOTICE = '僅財務證據組件，非完整公司研究；未封存、未取得發布資格。'
GAPS = '尚缺：完整證券／ADR身分、附註與重編核對、完整現金流調節、產能、客戶／訂單、融資條款及估值。加權平均股數差不是完整稀釋分析。不得據此生成目標價、總訂單或投資論點評分。'
CASH_LABELS = {'operating_cashflow': '營業現金流', 'ppe_payments': 'PPE現金支出',
               'net_income': '所選淨利', 'sbc': '股份基礎給付披露',
               'basic_shares': '基本加權平均股數', 'diluted_shares': '稀釋加權平均股數'}
CASH_METRIC_LABELS = {'cash_after_ppe': '營業現金流減PPE現金支出',
                      'cash_conversion': '營業現金流／所選淨利',
                      'diluted_share_increment': '稀釋／基本加權平均股數差額比'}


class FinancialProductsError(ValueError):
    pass


def _require(ok: bool, code: str = 'FINANCIAL_PRODUCTS_INPUT_INVALID') -> None:
    if not ok:
        raise FinancialProductsError(code)


def sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode('utf-8')


def _object(value, keys):
    _require(isinstance(value, dict) and set(value) == keys)
    return value


def _json(raw: bytes):
    _require(type(raw) is bytes and 0 < len(raw) <= 2_097_152, 'FINANCIAL_PRODUCTS_INPUT_SIZE')
    def pairs(items):
        value = {}
        for key, item in items:
            _require(key not in value, 'FINANCIAL_PRODUCTS_DUPLICATE_KEY')
            value[key] = item
        return value
    def constant(_):
        raise FinancialProductsError('FINANCIAL_PRODUCTS_NONFINITE')
    try:
        return json.loads(raw.decode('utf-8'), object_pairs_hook=pairs, parse_constant=constant)
    except (UnicodeError, json.JSONDecodeError, RecursionError):
        raise FinancialProductsError('FINANCIAL_PRODUCTS_JSON_INVALID') from None


def _time(value):
    _require(isinstance(value, str) and len(value) <= 40 and value.endswith('Z'))
    try:
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
        _require(parsed.tzinfo is not None)
    except ValueError:
        raise FinancialProductsError('FINANCIAL_PRODUCTS_TIME_INVALID') from None


def _finite(value):
    return type(value) in (int, float) and -1.7976931348623157e308 <= value <= 1.7976931348623157e308


def _validated_company(raw, generated, completed):
    _require(isinstance(raw, dict))
    if raw.get('status') in ('NO_OFFICIAL_IDENTITY', 'SOURCE_FETCH_OR_VALIDATION_FAILED'):
        _object(raw, {'status', 'publication_eligible'})
        _require(raw['publication_eligible'] is False)
        return None, {}, raw['status'], None
    version = raw.get('schema_version')
    _require(type(version) is int and version in (1, 2, 3))
    _object(raw, COMPANY_KEYS | ({'cashflow_bridge'} if version >= 2 else set()) | ({'source_acquisition'} if version == 3 else set()))
    _require(type(raw['schema_version']) is int and raw['schema_version'] == version
             and raw['status'] == 'CANDIDATE_NOT_PUBLICATION_QUALIFIED'
             and raw['as_of_cutoff'] == generated and raw['provider_scope'] == 'public_only'
             and raw['publication_eligible'] is False and raw['source_refresh_verified'] is False
             and (version == 3 or raw['source_retrieved_at'] is None)
             and raw['source_lineage'] == 'issuer_filing_via_sec_companyfacts'
             and raw['limitations'] == (FINANCIAL_V2_LIMITATIONS if version >= 2 else LIMITATIONS))
    if version == 3:
        receipt = raw['source_acquisition']
        if receipt is None:
            _require(raw['source_retrieved_at'] is None)
        else:
            try:
                validate_company_receipt(receipt, cik=raw['cik'])
                _require(raw['source_retrieved_at'] == receipt['retrieved_at']
                         and utc_time(receipt['retrieved_at']) <= utc_time(completed))
            except SourceAcquisitionError:
                raise FinancialProductsError('FINANCIAL_PRODUCTS_ACQUISITION_INVALID') from None
    metrics = _object(raw['metrics'], set(LABELS))
    facts = []
    for key, metric in metrics.items():
        _object(metric, {'status', 'value', 'value_unit', 'formula', 'numerator', 'denominator'})
        _require(isinstance(metric['status'], str) and metric['status'] in WITHHELD | {'AVAILABLE'}
                 and metric['formula'] == FORMULAS[key] and metric['value_unit'] == 'ratio')
        _require(_finite(metric['value']) if metric['status'] == 'AVAILABLE' else metric['value'] is None)
        for role in ('numerator', 'denominator'):
            operand = metric[role]
            if operand is None:
                continue
            _object(operand, FACT_KEYS)
            _require(isinstance(operand['record_url'], str) and len(operand['record_url']) <= 1024)
            fact = {'record_type': 'company_fact', **operand}
            # Reuse the producer's identity/date/value/URL checks, even for
            # withheld metrics whose surviving operands still appear in a table.
            try:
                probe = profitability_evidence([fact], cik=raw['cik'], as_of=generated)
            except Exception:
                raise FinancialProductsError('FINANCIAL_PRODUCTS_OPERAND_INVALID') from None
            projected = [m[r] for m in probe['metrics'].values() for r in ('numerator', 'denominator') if m[r] is not None]
            _require(any(canonical(operand) == canonical(p) for p in projected), 'FINANCIAL_PRODUCTS_OPERAND_INVALID')
            facts.append(fact)
    try:
        recomputed = profitability_evidence(facts, cik=raw['cik'], as_of=generated)
    except Exception:
        raise FinancialProductsError('FINANCIAL_PRODUCTS_RECOMPUTE_FAILED') from None
    for key, metric in metrics.items():
        if metric['status'] == 'AVAILABLE':
            _require(canonical(metric) == canonical(recomputed['metrics'][key]), 'FINANCIAL_PRODUCTS_CALCULATION_MISMATCH')
        # Never promote a failed/conflicting status just because the sidecar
        # does not retain the rejected source's original (possibly unsafe) data.
    cash = raw.get('cashflow_bridge')
    if version >= 2:
        try:
            validate_cashflow_evidence(cash, cik=raw['cik'], as_of=generated)
        except Exception:
            raise FinancialProductsError('FINANCIAL_PRODUCTS_CASHFLOW_INVALID') from None
    return raw['cik'], metrics, None, cash


def _number(value):
    return json.dumps(value, allow_nan=False)


def _percent(value):
    return format(Decimal(str(value)) * 100, '.4f') + '%'


def _period(metric):
    value = metric['numerator']
    return f"{value['start']}～{value['end']} ({value['unit']})"


def _sources(metrics, refs, cash=None):
    sources = {}
    for key in refs:
        for role in ('numerator', 'denominator'):
            fact = metrics[key][role]
            if fact is not None:
                identity = (fact['record_url'], fact['accession_number'], fact['filed'])
                sources[identity] = fact
    if cash:
        for item in cash['observations'].values():
            fact = item['operand']
            if fact is not None:
                sources[(fact['record_url'], fact['accession_number'], fact['filed'])] = fact
    return ['來源與限制：SEC Companyfacts 與其 filing 屬同一揭露血緣；不是多個獨立佐證。資料取得時間未驗證，可能來自快取。'] + [
        f"Filed {fact['filed']}；accession {fact['accession_number']}\n{fact['record_url']}" for fact in sources.values()]


def _data_blocks(metrics):
    blocks = ['核查方法：以下保留原值；ratio × 100 才是百分比。百分比顯示至4位小數，不以顯示值重算。不同期間各自列示，不混成同一期。']
    for key, metric in metrics.items():
        block = [f"{LABELS[key]} [{key}]：{metric['status']}", '',
                 '| 角色 | XBRL tag | 原值 | 單位 | 期間 | Filed | accession |',
                 '|---|---|---:|---|---|---|---|']
        for role, label in (('numerator', '分子'), ('denominator', '分母')):
            fact = metric[role]
            if fact is None:
                block.append(f'| {label} | 缺少或已拒絕 | — | — | — | — | — |')
            else:
                block.append(f"| {label} | {fact['tag']} | {_number(fact['value'])} | {fact['unit'] or '未知'} | {fact['start']}～{fact['end']} | {fact['filed']} | {fact['accession_number']} |")
        block.extend(['', f"公式：{metric['formula']}"])
        if metric['status'] == 'AVAILABLE':
            block.append(f"ratio = {_number(metric['value'])}；百分比 ≈ {_percent(metric['value'])}")
        else:
            block.append('本項不輸出計算結果；未知／不相容／衝突並不等於零。')
        blocks.append('\n'.join(block))
    return blocks


def _cash_value(metric):
    return _percent(metric['value']) if metric['value_unit'] == 'ratio' and metric['formula'].endswith('- 1') else f"{_number(metric['value'])} {metric['value_unit']}"


def _cash_data(cash):
    if cash is None:
        return ['舊版財務依據未保留現金流組件；不從摘要反推。']
    blocks = ['現金流與股數核查：PPE現金支出不是全部資本投資；不把淨投資現金流冒充capex，不將負支出取絕對值，不以缺少當零。各期間分別列示，不用季度淨利配全年現金流。']
    for key, item in cash['observations'].items():
        fact = item['operand']
        if fact is None:
            blocks.append(f"{CASH_LABELS[key]} [{key}]：{item['status']}；未保留可用原值。")
        else:
            blocks.append(f"{CASH_LABELS[key]} [{key}]：{item['status']}\n\n"
                          '| XBRL tag | 原值 | 單位 | 期間 | Filed | accession |\n'
                          '|---|---:|---|---|---|---|\n'
                          f"| {fact['tag']} | {_number(fact['value'])} | {fact['unit']} | {fact['start']}～{fact['end']} | {fact['filed']} | {fact['accession_number']} |")
    for key, metric in cash['metrics'].items():
        blocks.append(f"{CASH_METRIC_LABELS[key]} [{key}]：{metric['status']}\n"
                      f"公式：{metric['formula']}；operands：{', '.join(metric['operand_refs'])}\n"
                      + (f"原計算值：{_number(metric['value'])} {metric['value_unit']}" if metric['status'] == 'AVAILABLE' else '不輸出結果；不得改選較舊文件補回。'))
    return blocks


def _cash_summary(cash):
    if cash is None:
        return []
    blocks = []
    for key in ('operating_cashflow', 'ppe_payments'):
        fact = cash['observations'][key]['operand']
        if fact:
            blocks.append(f"{CASH_LABELS[key]}：{_number(fact['value'])} {fact['unit']}；{fact['start']}～{fact['end']}")
    metric = cash['metrics']['cash_after_ppe']
    if metric['status'] == 'AVAILABLE':
        blocks.append(f"{CASH_METRIC_LABELS['cash_after_ppe']}：{_cash_value(metric)}；不是可分配股東現金。")
    return blocks


def _cash_analysis(cash):
    if cash is None or not any(m['status'] == 'AVAILABLE' for m in cash['metrics'].values()):
        return []
    blocks = ['問題：帳面獲利經投資現金支出後，是否已成為股東可留存的價值？以下僅檢查已取得的數值鏈，不等於完整利益／融資橋。']
    metrics, observations = cash['metrics'], cash['observations']
    cash_left = metrics['cash_after_ppe']
    if cash_left['status'] == 'AVAILABLE':
        cfo, ppe = (observations[key]['operand'] for key in ('operating_cashflow', 'ppe_payments'))
        blocks.append(f"計算觀察 [cashflow.cash_after_ppe]：{cfo['start']}～{cfo['end']}，同文件營業現金流 {_number(cfo['value'])} 減PPE現金支出 {_number(ppe['value'])} = {_cash_value(cash_left)}。不是標準化FCF、每股收益或自由分配現金。")
        if cash_left['value'] < 0:
            blocks.append('條件解讀（INFERENCE）：所列PPE現金支出高於營業現金流；單靠這兩項的本期淨額無法覆蓋該支出。但不能據此宣告資金斷裂：尚需核對期初現金、其他投資、借款／到期及股權融資。')
        elif cash_left['value'] > 0:
            blocks.append('條件解讀（INFERENCE）：扣除所列PPE支出後仍為正，不代表全部可以配息；其他投資、租賃、還債及受限現金等義務仍待核對。')
        else:
            blocks.append('條件解讀（INFERENCE）：這兩項的淨額為零，不表示總現金收支平衡，也不表示沒有其他資金需求。')
    conversion = metrics['cash_conversion']
    if conversion['status'] == 'AVAILABLE':
        cfo, net = (observations[key]['operand'] for key in ('operating_cashflow', 'net_income'))
        blocks.append(f"計算觀察 [cashflow.cash_conversion]：{cfo['start']}～{cfo['end']}，同文件 CFO {_number(cfo['value'])}／所選正淨利 {_number(net['value'])} = {_number(conversion['value'])} 倍。倍數高不自動表示品質佳；營運資金回收、預收款及非現金調整只是待查原因，不是已證實歸因。")
        if cfo['value'] < 0:
            blocks.append('條件解讀（INFERENCE）：正淨利伴隨營業現金淨流出；帳面獲利尚不能代表同期間現金流入。應核對營運資金和非現金項目，不猜測是哪個客戶延付。')
        elif conversion['value'] < 1:
            blocks.append('條件解讀（INFERENCE）：營業現金流小於所選正淨利；差距需要期間調節，不能直接外推為永久現金轉換率。')
    shares = metrics['diluted_share_increment']
    if shares['status'] == 'AVAILABLE':
        basic, diluted = (observations[key]['operand'] for key in ('basic_shares', 'diluted_shares'))
        blocks.append(f"計算觀察 [cashflow.diluted_share_increment]：{basic['start']}～{basic['end']}，同文件基本／稀釋加權平均股數 {_number(basic['value'])}／{_number(diluted['value'])} shares，差額比 {_percent(shares['value'])}。這不是本期新發股比例、未來完全稀釋股數或ADR比率；零差額也不證明沒有反稀釋而排除的工具。")
    sbc = observations['sbc']['operand']
    if sbc:
        blocks.append(f"股份基礎給付觀察 [cashflow.sbc]：{sbc['start']}～{sbc['end']}，ShareBasedCompensation {_number(sbc['value'])} {sbc['unit']}。原報表位置及是否已列入CFO調整須查附註；不是現金支付或完整授予價值。不機械從CFO再扣一次，也不以此單一金額推算股權稀釋。")
    blocks.extend(['反方與條件結論：PPE投資可能是擴張亦可能是維持需求；正現金流也可能含需履約的預收款。需查附註、投資用途及融資條款，不能把營運成功直接當股東價值提升，更不能只凭單期缺口否定營運論點。',
                   '推翻／更新條件：現金流、支出或加權股數重編，期間／合併／股別口徑改變，必須重算；融資、認股權或可轉債新條款須另行評估。未取得的工具與義務不等於零，不生成每股現金收益或目標價。'])
    return blocks


def _analysis(metrics):
    op, net = (metrics.get(key) for key in ('operating_margin', 'net_margin'))
    if not op or not net or op['status'] != 'AVAILABLE' or net['status'] != 'AVAILABLE':
        return [], 'COMPARABLE_OPERATING_AND_NET_REQUIRED'
    if canonical(op['denominator']) != canonical(net['denominator']):
        return [], 'CROSS_METRIC_BASIS_MISMATCH'
    o, n = op['value'], net['value']
    difference = (Decimal(str(n)) - Decimal(str(o))) * 100
    blocks = [
        '問題：所選財報期間的帳面獲利是否能直接代表本業表現？',
        f"計算觀察 [operating_margin, net_margin]：{_period(op)}，營益率 {_percent(o)}、淨利率 {_percent(n)}；淨利率減營益率為 {difference:.4f} 個百分點。兩者共用同一營收分母、期間與文件，不跨季拼接。",
    ]
    if o < 0 < n:
        blocks.append('條件解讀（INFERENCE）：營業利益為負而淨利為正，因此正淨利不能直接當作本業已獲利的證明。應先拆解營業線以下的項目，再判斷獲利可持續性。')
    elif o > 0 > n:
        blocks.append('條件解讀（INFERENCE）：本業營業利益為正，底線卻虧損；改善本業不等於股東已取得正淨收益。需要查明營業線以下的負擔是否持續，而非單看營益率。')
    elif n > o:
        blocks.append('條件解讀（INFERENCE）：淨利高於營業利益。不能把整個淨利率都歸因於產品定價、供給稀缺或營運效率；營業線以下的淨影響需要獨立核對。')
    elif n < o:
        blocks.append('條件解讀（INFERENCE）：淨利低於營業利益；本業到最終淨收益之間存在減項的淨影響，不能把營業利益直接當作可分配的股東現金。')
    else:
        blocks.append('條件解讀（INFERENCE）：所選期間兩個利潤率相等，只表示所選數值的淨差為零，不證明沒有利息、稅或其他互抵項目。')
    blocks.extend([
        '反方：差距可能涉及業外、利息、稅、非控制權益或財報口徑；這些是待查原因，不是已證實歸因。虧損亦可能與投入時序有關，不能僅憑單期數字宣告營運論點失效。',
        '條件結論：先查財報附註中的利益橋與重編，再查現金流及稀釋。只有該差距在相同口徑下成立，以上比較才成立；不能外推下一期成長或目標價。',
        '推翻／更新條件：任一原值重編、期間／單位／合併口徑改變，需重算本段；若附註顯示主要影響屬一次性，不能延用為常態獲利。',
    ])
    return blocks, None


def _product(kind, blocks, refs, identity, reason=None):
    base = {**identity, 'output_kind': kind, 'report_id': f"financial:{identity['subject']['ticker']}:{kind}",
            'domain': 'stock', 'scope': 'financial_evidence_only', 'complete': False,
            'publication_eligible': False, 'claim_refs': refs, 'reason': reason}
    if reason:
        return {**base, 'status': 'UNAVAILABLE', 'content_utf8': None, 'content_sha256': None,
                'content_bytes': 0, 'pages': []}
    content = '\n\n'.join(blocks)
    chunks = []
    chunk = ''
    for block in blocks:
        _require(len(block.encode('utf-16-le')) // 2 <= 4400, 'FINANCIAL_PRODUCT_SECTION_TOO_LARGE')
        if chunk and len((chunk + '\n\n' + block).encode('utf-16-le')) // 2 > 4400:
            chunks.append(chunk); chunk = ''
        chunk += ('\n\n' if chunk else '') + block
    if chunk:
        chunks.append(chunk)
    _require(0 < len(chunks) <= 5 and '\n\n'.join(chunks) == content, 'FINANCIAL_PRODUCT_CAPACITY_EXCEEDED')
    digest = sha256(content.encode('utf-8'))
    pages = [{**identity, 'report_id': base['report_id'], 'output_kind': kind,
              'content_sha256': digest, 'index': i + 1, 'count': len(chunks), 'text': text,
              'page_sha256': sha256(text.encode('utf-8'))} for i, text in enumerate(chunks)]
    return {**base, 'status': 'AVAILABLE_PARTIAL', 'content_utf8': content,
            'content_sha256': digest, 'content_bytes': len(content.encode('utf-8')), 'pages': pages}


def build_financial_products(report_bytes: bytes, basis_bytes: bytes) -> dict:
    report = _json(report_bytes)
    _require(isinstance(report, dict))
    version = report.get('schema_version')
    _object(report, REPORT_KEYS | ({'calculation_cutoff'} if version == 2 else set()))
    if version == 2:
        try:
            validate_report_acquisition(report)
        except SourceAcquisitionError:
            raise FinancialProductsError('FINANCIAL_PRODUCTS_ACQUISITION_INVALID') from None
    basis = _object(_json(basis_bytes), BASIS_KEYS)
    _require(type(version) is int and version in (1, 2)
             and report['product_version'] == '2.1.2' and report['provider_scope'] == 'public_only'
             and report['owner_watchlist_inherited'] is False)
    _require(type(basis['schema_version']) is int and basis['schema_version'] == 1
             and basis['status'] == 'CANDIDATE_NOT_PUBLICATION_QUALIFIED'
             and basis['publication_eligible'] is False and basis['provider_scope'] == 'public_only'
             and basis['owner_watchlist_inherited'] is False
             and basis['generated_at'] == report['generated_at']
             and basis['report_sha256'] == sha256(report_bytes)
             and basis['hash_scope'] == 'v212 report UTF-8 bytes, not source HTTP or sealed snapshot',
             'FINANCIAL_PRODUCTS_SOURCE_BINDING_INVALID')
    _time(report['generated_at'])
    rows = report['records']
    _require(isinstance(rows, list) and len(rows) == 20 and isinstance(basis['records'], dict))
    seen = set()
    for i, row in enumerate(rows):
        _object(row, ROW_KEYS | ({'source_acquisition'} if version == 2 else set()))
        _require(type(row['rank']) is int and row['rank'] == i + 1
                 and type(row['schema_version']) is int and row['schema_version'] == version
                 and isinstance(row['ticker'], str) and bool(re.fullmatch(r'[A-Z0-9][A-Z0-9.-]{0,14}', row['ticker'])))
        _require(row['ticker'] not in seen and row['provider_scope'] == 'public_only'
                 and row['owner_watchlist_inherited'] is False)
        if version == 1:
            _time(row['retrieved_at'])  # Legacy clocks are not reinterpreted as new receipts.
        seen.add(row['ticker'])
    _require(set(basis['records']) == seen, 'FINANCIAL_PRODUCTS_SUBJECT_SET_MISMATCH')
    source_report_sha = sha256(report_bytes)
    source_basis_sha = sha256(basis_bytes)
    snapshot = 'candidate:' + sha256(report_bytes + b'\x00' + basis_bytes)
    records = []
    for row in rows:
        ticker = row['ticker']
        company = basis['records'][ticker]
        cutoff = report.get('calculation_cutoff', report['generated_at'])
        cik, metrics, failure, cash = _validated_company(company, cutoff, report['generated_at'])
        receipt = company.get('source_acquisition')
        if version == 2:
            clock = row['source_acquisition']['profit_summary']
            if clock['status'] == 'KNOWN':
                _require(receipt is not None and clock['retrieved_at'] == receipt['retrieved_at']
                         and clock['evidence_sha256'] == digest(receipt), 'FINANCIAL_PRODUCTS_ACQUISITION_MISMATCH')
            elif clock['status'] == 'UNKNOWN':
                _require(receipt is None, 'FINANCIAL_PRODUCTS_ACQUISITION_MISMATCH')
        refs = [key for key in LABELS if metrics.get(key, {}).get('status') == 'AVAILABLE']
        cash_refs = ([f'cashflow.{key}' for group in ('observations', 'metrics')
                      for key, item in cash[group].items() if item['status'] == 'AVAILABLE'] if cash else [])
        identity = {'candidate_snapshot_id': snapshot, 'snapshot_run_id': None,
                    'source_report_sha256': source_report_sha, 'source_basis_sha256': source_basis_sha,
                    'subject': {'ticker': ticker, 'issuer_cik': cik, 'security_identity_qualified': False}}
        header = [f"{ticker}｜CIK {cik or '未知'}｜財務證據", NOTICE,
                  f"計算 cutoff：{cutoff}；不是當前報價或完整新鮮度認證。",
                  (f"SEC body 原取得時間：{receipt['retrieved_at']}；{receipt['retrieval_mode']}；body SHA256 {receipt['body_sha256']}。仍須最新披露／附註核對。"
                   if receipt else 'SEC body 原取得時間未知；不以本機組裝時間代替，不從舊版摘要反推。')]
        reason = failure or (None if refs or cash_refs else 'NO_AVAILABLE_FINANCIAL_METRICS')
        summary = [f"{LABELS[key]}：{_percent(metrics[key]['value'])}；{_period(metrics[key])}" for key in refs]
        analysis, analysis_reason = _analysis(metrics)
        analysis_refs = ['operating_margin', 'net_margin'] if not analysis_reason else []
        cash_analysis = _cash_analysis(cash)
        if cash_analysis:
            analysis_reason = None
        products = {
            'card_summary': _product('card_summary', header + ['財務摘要 / Financial summary', *summary] + _cash_summary(cash) + [GAPS] + _sources(metrics, refs, cash), refs + cash_refs, identity, reason),
            'data_report': _product('data_report', header + ['財務數據核查 / Financial data review'] + _data_blocks(metrics) + _cash_data(cash) + [GAPS] + _sources(metrics, list(metrics), cash), list(metrics) + cash_refs, identity, reason),
            'narrative_analysis': _product('narrative_analysis', header + ['獲利結構解讀 / Earnings interpretation'] + analysis + cash_analysis + [GAPS] + _sources(metrics, analysis_refs, cash), analysis_refs + (cash_refs if cash_analysis else []), identity, reason or analysis_reason),
        }
        records.append({'ticker': ticker, 'products': products})
    return {'schema_version': 1, 'status': 'LOCAL_FINANCIAL_COMPONENTS_NOT_RELEASE_QUALIFIED',
            'candidate_snapshot_id': snapshot, 'snapshot_run_id': None,
            'source_report_sha256': source_report_sha, 'source_basis_sha256': source_basis_sha,
            'generated_at': report['generated_at'], 'provider_scope': 'public_only',
            'owner_watchlist_inherited': False, 'publication_eligible': False, 'complete': False,
            'records': records}


def verify_financial_products(products_bytes: bytes, report_bytes: bytes, basis_bytes: bytes) -> None:
    """Replay validation/rendering against exact input bytes (shared algorithm).

    Local integrity only. Does not grant freshness, rights or sealed admission.
    """
    expected = build_financial_products(report_bytes, basis_bytes)
    _require(canonical(_json(products_bytes)) == canonical(expected), 'FINANCIAL_PRODUCTS_OUTPUT_MISMATCH')
