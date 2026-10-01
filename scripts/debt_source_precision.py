"""Bounded original-file attributes and CONDITIONAL debt interval checks.

Not an XBRL/IXT conformant processor, taxonomy validator, source collector,
issuer rounding policy, independent corroboration or financial admission.
The existing exact point comparison and every withholding state stay intact.
See docs/DETAILED_REPORT_CONTRACT.md for the reviewed specifications and limits.
"""
from __future__ import annotations

import base64
import binascii
import hashlib
import io
import re
import stat
import xml.etree.ElementTree as ET
from datetime import date, datetime
from fractions import Fraction
from pathlib import Path

from v21_serenity_top20 import _strict_public_json, PipelineError
from v213_v21_progress_runner import FINANCIAL_V5_LIMITATIONS, DEBT_TAGS

POLICY = 'debt-source-precision-conditional-v1'
LIMITATIONS = FINANCIAL_V5_LIMITATIONS + ['SOURCE_PRECISION_IS_NOT_DEBT_RECONCILIATION']
MAX_BUNDLE_BYTES = 4_194_304
X = '{http://www.xbrl.org/2003/instance}'
IX = '{http://www.xbrl.org/2013/inlineXBRL}'
IXT = '{http://www.xbrl.org/inlineXBRL/transformation/2020-02-12}'
GAAP = r'\{http://fasb.org/us-gaap/20[0-9]{2}\}'
DEI = r'\{http://xbrl.sec.gov/dei/20[0-9]{2}\}'


class DebtPrecisionError(ValueError):
    pass


def require(ok, code='DEBT_PRECISION_SOURCE_UNSUPPORTED'):
    if not ok:
        raise DebtPrecisionError(code)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _object(value, keys):
    require(isinstance(value, dict) and set(value) == set(keys), 'DEBT_PRECISION_BUNDLE_INVALID')
    return value


def _time(value):
    require(isinstance(value, str) and re.fullmatch(r'[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]{1,6})?Z', value), 'DEBT_PRECISION_TIME_INVALID')
    try:
        return datetime.fromisoformat(value.replace('Z', '+00:00'))
    except ValueError:
        raise DebtPrecisionError('DEBT_PRECISION_TIME_INVALID') from None


def read_bundle(path: Path, *, forbidden=()) -> bytes:
    """Read-only bounded input; not a filesystem transaction/TOCTOU guarantee."""
    try:
        require(not str(path).startswith(('\\\\', '//')), 'DEBT_PRECISION_PATH_INVALID')
        require(all(':' not in part for part in path.parts if part != path.anchor), 'DEBT_PRECISION_PATH_INVALID')
        for item in (path, *path.parents):
            info = item.lstat()
            require(not stat.S_ISLNK(info.st_mode) and not getattr(info, 'st_file_attributes', 0) & 0x400, 'DEBT_PRECISION_PATH_INVALID')
        info = path.stat()
        require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1, 'DEBT_PRECISION_PATH_INVALID')
        resolved = path.resolve()
        require(not str(resolved).startswith(('\\\\', '//')), 'DEBT_PRECISION_PATH_INVALID')
        require(resolved not in [p.resolve() for p in forbidden], 'DEBT_PRECISION_PATH_COLLISION')
        with path.open('rb') as handle:
            raw = handle.read(MAX_BUNDLE_BYTES + 1)
        prepare_bundle(raw)  # Fail malformed envelopes before caller collection/writes.
        return raw
    except OSError:
        raise DebtPrecisionError('DEBT_PRECISION_PATH_INVALID') from None


def _xml(raw, expected):
    require(not re.search(br'<!\s*(DOCTYPE|ENTITY)\b', raw, re.I))
    root = None; stack = []; pending = {}; scopes = {}; ids = {}; parents = {}
    try:
        for event, element in ET.iterparse(io.StringIO(raw.decode('utf-8-sig')), events=('start', 'end', 'start-ns')):
            if event == 'start-ns':
                pending[element[0]] = element[1]
            elif event == 'start':
                require(len(stack) < 128 and len(scopes) < 100000 and len(element.attrib) <= 64)
                current = dict(scopes[id(stack[-1])]) if stack else {}
                current.update(pending); pending = {}
                require(len(current) <= 64 and '{http://www.w3.org/XML/1998/namespace}base' not in element.attrib)
                scopes[id(element)] = current
                if stack:
                    parents[id(element)] = stack[-1]
                else:
                    root = element
                stack.append(element)
                identity = element.get('id')
                if identity is not None:
                    require(isinstance(identity, str) and re.fullmatch(r'[A-Za-z_][A-Za-z0-9_.-]{0,99}', identity) and identity not in ids)
                    ids[identity] = element
            else:
                stack.pop()
    except (ET.ParseError, UnicodeError, RecursionError, ValueError, LookupError):
        raise DebtPrecisionError('DEBT_PRECISION_SOURCE_UNSUPPORTED') from None
    require(root is not None and root.tag == expected)
    return root, ids, scopes, parents


def _qname(text, scopes, element):
    require(isinstance(text, str) and re.fullmatch(r'[A-Za-z_][A-Za-z0-9_.-]*:[A-Za-z_][A-Za-z0-9_.-]*', text))
    prefix, local = text.split(':')
    require(prefix in scopes[id(element)])
    return '{' + scopes[id(element)][prefix] + '}' + local


def _day(text):
    require(isinstance(text, str) and re.fullmatch(r'[0-9]{4}-[0-9]{2}-[0-9]{2}', text))
    try:
        return date.fromisoformat(text).isoformat()
    except ValueError:
        raise DebtPrecisionError('DEBT_PRECISION_SOURCE_UNSUPPORTED') from None


def _text(element):
    require(len(element) == 0 and isinstance(element.text, str) and len(element.text) <= 128)
    return element.text.strip()


def _resource_parent(tree, element):
    root, _, _, parents = tree
    parent = parents.get(id(element))
    if root.tag == X+'xbrl':
        require(parent is root)
    else:
        require(parent is not None and parent.tag == IX+'resources' and not parent.attrib)
        header = parents.get(id(parent))
        require(header is not None and header.tag == IX+'header')


def _context(tree, ref, cik, *, instant=False):
    root, ids, _, parents = tree
    require(ref in ids)
    element = ids[ref]
    require(element.tag == X+'context' and set(element.attrib) == {'id'})
    _resource_parent(tree, element)
    require([c.tag for c in element] == [X+'entity', X+'period'])
    entity, period = element
    require(not entity.attrib and len(entity) == 1 and entity[0].tag == X+'identifier')
    require(entity[0].attrib == {'scheme':'http://www.sec.gov/CIK'} and _text(entity[0]) == cik and entity[0].text == cik)
    require(not period.attrib and all(not e.attrib for e in period))
    if [c.tag for c in period] == [X+'instant']:
        return {'kind':'instant', 'start':None, 'end':_day(_text(period[0])), 'cik':cik, 'segment':None, 'scenario':None}
    require(not instant and [c.tag for c in period] == [X+'startDate', X+'endDate'])
    start, end = [_day(_text(e)) for e in period]
    require(start <= end)
    return {'kind':'duration', 'start':start, 'end':end, 'cik':cik, 'segment':None, 'scenario':None}


def _unit(tree, ref):
    root, ids, scopes, parents = tree
    require(ref in ids)
    element = ids[ref]
    require(element.tag == X+'unit' and set(element.attrib) == {'id'} and len(element) == 1)
    _resource_parent(tree, element)
    measure = element[0]
    require(measure.tag == X+'measure' and not measure.attrib)
    expanded = _qname(_text(measure), scopes, measure)
    require(expanded == '{http://www.xbrl.org/2003/iso4217}USD')
    return expanded


def _integer(text):
    require(isinstance(text, str) and re.fullmatch(r'-?(?:0|[1-9][0-9]?)', text))
    value = int(text)
    require(-18 <= value <= 18)
    return value


def _number(text):
    require(isinstance(text, str) and len(text) <= 128 and re.fullmatch(r'[0-9]+(?:\.[0-9]+)?', text))
    return Fraction(text)


def interval(value: Fraction, decimals: str, mode: str):
    """Exact, bounded conditional arithmetic; never selects an issuer mode."""
    require(type(value) is Fraction and abs(value) <= 9007199254740991)
    require(mode in ('round-to-nearest', 'truncation'))
    if decimals == 'INF':
        return value, value, True, True
    step = Fraction(10) ** (-_integer(decimals))
    require((value / step).denominator == 1, 'DEBT_PRECISION_DIGITS_EXCEED_DECIMALS')
    if mode == 'round-to-nearest':
        return value - step/2, value + step/2, True, True
    if value > 0:
        return value, value + step, True, False
    if value < 0:
        return value - step, value, False, True
    return -step, step, False, False


def _interval_json(value):
    a, b, left, right = value
    return {'lower':str(a), 'upper':str(b), 'lower_closed':left, 'upper_closed':right}


def _overlaps(a, b):
    low, high = max(a[0], b[0]), min(a[1], b[1])
    if low != high:
        return low < high
    def contains(i, p):
        return (i[0] < p or i[2]) and (p < i[1] or i[3])
    return contains(a, low) and contains(b, low)


class _Bundle:
    def __init__(self, raw):
        require(type(raw) is bytes and 0 < len(raw) <= MAX_BUNDLE_BYTES, 'DEBT_PRECISION_BUNDLE_INVALID')
        try:
            value = _object(_strict_public_json(raw), ('schema_version','cik','accession','documents'))
        except PipelineError:
            raise DebtPrecisionError('DEBT_PRECISION_BUNDLE_INVALID') from None
        require(type(value['schema_version']) is int and value['schema_version'] == 1, 'DEBT_PRECISION_BUNDLE_INVALID')
        self.cik = value['cik']; self.accession = value['accession']; self.sha256 = sha(raw)
        require(isinstance(self.cik, str) and re.fullmatch(r'[0-9]{10}', self.cik) and int(self.cik) > 0, 'DEBT_PRECISION_BUNDLE_INVALID')
        require(isinstance(self.accession, str) and re.fullmatch(r'[0-9]{10}-[0-9]{2}-[0-9]{6}', self.accession), 'DEBT_PRECISION_BUNDLE_INVALID')
        prefix = f'https://www.sec.gov/Archives/edgar/data/{int(self.cik)}/{self.accession.replace("-", "")}/'
        self.base_url = prefix; self.documents = {}; bodies = {}; names = {}
        for role, item in _object(value['documents'], ('index','inline','instance')).items():
            _object(item, ('url','retrieved_at','body_sha256','body_base64'))
            url = item['url']
            require(isinstance(url, str) and url.startswith(prefix), 'DEBT_PRECISION_BUNDLE_INVALID')
            name = url[len(prefix):]
            require(bool(re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,99}', name)) and '..' not in name, 'DEBT_PRECISION_BUNDLE_INVALID')
            require(isinstance(item['body_base64'], str) and len(item['body_base64']) <= 2_796_204, 'DEBT_PRECISION_BUNDLE_INVALID')
            try:
                body = base64.b64decode(item['body_base64'], validate=True)
            except (ValueError, binascii.Error):
                raise DebtPrecisionError('DEBT_PRECISION_BUNDLE_INVALID') from None
            require(0 < len(body) <= 2_097_152 and sha(body) == item['body_sha256']
                    and base64.b64encode(body).decode('ascii') == item['body_base64'], 'DEBT_PRECISION_BUNDLE_INVALID')
            _time(item['retrieved_at'])
            self.documents[role] = {k:item[k] for k in ('url','retrieved_at','body_sha256')}
            self.documents[role]['bytes'] = len(body); bodies[role] = body; names[role] = name
        require(names['index'] == 'index.json' and names['inline'].endswith('.htm')
                and names['instance'] == names['inline'][:-4] + '_htm.xml', 'DEBT_PRECISION_BUNDLE_INVALID')
        try:
            index = _strict_public_json(bodies['index'])
        except PipelineError:
            raise DebtPrecisionError('DEBT_PRECISION_BUNDLE_INVALID') from None
        require(isinstance(index, dict) and isinstance(index.get('directory'), dict), 'DEBT_PRECISION_BUNDLE_INVALID')
        directory = index['directory']; items = directory.get('item')
        require(directory.get('name') == prefix.removeprefix('https://www.sec.gov').rstrip('/')
                and isinstance(items, list) and 1 <= len(items) <= 1000, 'DEBT_PRECISION_BUNDLE_INVALID')
        listed = []
        for item in items:
            name = item.get('name') if isinstance(item, dict) else None
            require(isinstance(name, str) and re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,99}', name) and '..' not in name, 'DEBT_PRECISION_BUNDLE_INVALID')
            listed.append(name)
        require(len({n.casefold() for n in listed}) == len(listed) and all(names[r] in listed for r in ('inline','instance')), 'DEBT_PRECISION_BUNDLE_INVALID')
        self.xml_error = None
        try:
            self.instance = _xml(bodies['instance'], X+'xbrl')
            self.inline = _xml(bodies['inline'], '{http://www.w3.org/1999/xhtml}html')
        except DebtPrecisionError as exc:
            self.xml_error = str(exc)

    def _inline_facts(self, name, kind, namespace):
        result = []
        for element in self.inline[0].iter():
            if element.tag not in (IX+'nonFraction', IX+'nonNumeric', IX+'fraction'):
                continue
            if (element.get('name') or '').rsplit(':',1)[-1] != name:
                continue
            expanded = _qname(element.get('name'), self.inline[2], element)
            if re.fullmatch(namespace+name, expanded):
                require(element.tag == IX+kind)
                result.append(element)
        return result

    def _identity(self):
        root, _, _, _ = self.instance
        _, ids, scopes, _ = self.inline
        result = {}; namespaces = set(); contexts = set()
        for name in ('EntityCentralIndexKey','DocumentType','DocumentFiscalYearFocus','DocumentFiscalPeriodFocus','DocumentPeriodEndDate','AmendmentFlag'):
            found = [e for e in root if re.fullmatch(DEI+name, e.tag)]
            require(len(found) == 1)
            element = found[0]
            require(set(element.attrib) == {'id','contextRef'} and element.get('id') in ids)
            other = ids[element.get('id')]
            require(self._inline_facts(name, 'nonNumeric', DEI) == [other], 'DEBT_PRECISION_AMBIGUOUS_OR_MISSING_FACT')
            require(other.tag == IX+'nonNumeric' and set(other.attrib) <= {'id','contextRef','name','format'})
            require(_qname(other.get('name'), scopes, other) == element.tag and other.get('contextRef') == element.get('contextRef'))
            a = _context(self.instance, element.get('contextRef'), self.cik)
            require(a == _context(self.inline, other.get('contextRef'), self.cik))
            contexts.add((a['kind'], a['start'], a['end']))
            text, normalized = _text(other), _text(element)
            if other.get('format') is not None:
                require(name == 'DocumentPeriodEndDate' and _qname(other.get('format'), scopes, other) == IXT+'date-monthname-day-year-en')
                # Explicitly limited subset: full English month, 1–2 day digits,
                # comma and 4-digit year. Other valid IXT forms remain unsupported.
                months = 'January February March April May June July August September October November December'.split()
                match = re.fullmatch(r'([A-Za-z]+)[ \u00a0]([0-9]{1,2}), ([0-9]{4})', text)
                require(match is not None and match[1] in months)
                text = _day(f'{match[3]}-{months.index(match[1])+1:02d}-{int(match[2]):02d}')
            require(text == normalized)
            result[name] = normalized; namespaces.add(element.tag.rsplit('}',1)[0])
        require(len(namespaces) == 1 and len(contexts) == 1)
        require(result['EntityCentralIndexKey'] == self.cik and result['DocumentType'] in ('10-K','10-Q')
                and result['DocumentFiscalPeriodFocus'] in ('FY','Q1','Q2','Q3','Q4') and result['AmendmentFlag'] == 'false'
                and re.fullmatch(r'20[0-9]{2}', result['DocumentFiscalYearFocus']))
        require(next(iter(contexts))[2] == _day(result['DocumentPeriodEndDate']))
        return result

    def assess(self, debt, receipt, cutoff):
        base = {'schema_version':1, 'policy_id':POLICY, 'bundle_sha256':self.sha256,
                'cik':self.cik, 'accession':self.accession, 'as_of_cutoff':cutoff,
                'document_receipts':self.documents,
                'companyfacts_body_sha256':receipt['body_sha256'] if receipt else None,
                'source_lineage_count':1, 'issuer_rounding_mode_verified':False,
                'taxonomy_calculation_verified':False, 'financial_reconciliation_admitted':False,
                'source_refresh_verified':False, 'publication_eligible':False}
        try:
            require(self.xml_error is None)
            require(receipt is not None, 'DEBT_PRECISION_SOURCE_RECEIPT_REQUIRED')
            cutoff_time = _time(cutoff)
            require(all(_time(d['retrieved_at']) <= cutoff_time for d in self.documents.values()), 'DEBT_PRECISION_TIME_INVALID')
            require(all(item['status'] == 'AVAILABLE' for item in debt['observations'].values()), 'DEBT_PRECISION_OPERANDS_UNAVAILABLE')
            identity = self._identity(); facts = []; operands = []
            namespaces = set(); bases = set()
            for key, tag in DEBT_TAGS.items():
                # DEBT_TAGS remains the sole selector; no alias or older-fact rescue.
                operand = debt['observations'][key]['operand']; operands.append(operand)
                require(operand['tag'] == tag)
                require(all(operand['filed'] <= _time(d['retrieved_at']).date().isoformat() for d in self.documents.values()), 'DEBT_PRECISION_TIME_INVALID')
                require(operand['cik'] == self.cik and operand['accession_number'] == self.accession
                        and operand['record_url'] == self.base_url and operand['unit'] == 'USD'
                        and operand['form'] == identity['DocumentType'] and str(operand['fiscal_year']) == identity['DocumentFiscalYearFocus']
                        and operand['end'] <= identity['DocumentPeriodEndDate'] <= operand['filed'], 'DEBT_PRECISION_BASIS_MISMATCH')
                bases.add((operand['end'], operand['filed'], operand['form'], operand['fiscal_year']))
                candidates = []
                for element in self.instance[0].iter():
                    if not re.fullmatch(GAAP+operand['tag'], element.tag):
                        continue
                    require(self.instance[3].get(id(element)) is self.instance[0])
                    context = _context(self.instance, element.get('contextRef'), self.cik, instant=True)
                    if context['end'] == operand['end']:
                        candidates.append((element, context))
                require(len(candidates) == 1, 'DEBT_PRECISION_AMBIGUOUS_OR_MISSING_FACT')
                element, context = candidates[0]; attrs = element.attrib
                require(set(attrs) == {'id','contextRef','unitRef','decimals'} and attrs['id'] in self.inline[1])
                other = self.inline[1][attrs['id']]
                inline_candidates = [item for item in self._inline_facts(tag, 'nonFraction', GAAP)
                                     if _context(self.inline, item.get('contextRef'), self.cik, instant=True)['end'] == operand['end']]
                require(inline_candidates == [other], 'DEBT_PRECISION_AMBIGUOUS_OR_MISSING_FACT')
                require(other.tag == IX+'nonFraction' and set(other.attrib) <= {'id','contextRef','unitRef','decimals','name','format','scale'})
                require(all(other.get(k) == v for k,v in attrs.items()) and _qname(other.get('name'), self.inline[2], other) == element.tag)
                require(context == _context(self.inline, other.get('contextRef'), self.cik, instant=True))
                measure = _unit(self.instance, attrs['unitRef'])
                require(measure == _unit(self.inline, other.get('unitRef')))
                literal, displayed = _text(element), _text(other)
                transform = _qname(other.get('format'), self.inline[2], other) if other.get('format') is not None else None
                if transform is not None:
                    require(transform == IXT+'num-dot-decimal' and re.fullmatch(r'[0-9]{1,3}(?:,[0-9]{3})*(?:\.[0-9]+)?|[0-9]+(?:\.[0-9]+)?', displayed))
                scale = _integer(other.get('scale', '0'))
                value = _number(literal)
                require(_number(displayed.replace(',','') if transform else displayed) * Fraction(10)**scale == value
                        and value == Fraction(str(operand['value'])), 'DEBT_PRECISION_VALUE_MISMATCH')
                decimals = attrs['decimals']
                interval(value, decimals, 'round-to-nearest')  # Bounds + excess-digit refusal.
                namespaces.add(element.tag.rsplit('}',1)[0])
                facts.append({'operand_ref':key, 'qname':element.tag, 'fact_id':attrs['id'], 'context_ref':attrs['contextRef'],
                              'context':context, 'unit_ref':attrs['unitRef'], 'unit_qname':measure,
                              'instance_value_literal':literal, 'inline_value_literal':displayed,
                              'scale':other.get('scale','0'), 'decimals':decimals, 'format_qname':transform})
            require(len(namespaces) == 1 and len(bases) == 1, 'DEBT_PRECISION_BASIS_MISMATCH')
            values = [Fraction(str(o['value'])) for o in operands]; modes = {}
            for mode in ('round-to-nearest','truncation'):
                bounds = [interval(v, f['decimals'], mode) for v,f in zip(values,facts)]
                a, b, total = bounds
                summed = a[0]+b[0], a[1]+b[1], a[2] and b[2], a[3] and b[3]
                modes[mode] = {'status':'OVERLAP' if _overlaps(summed,total) else 'DISJOINT',
                               'component_sum':_interval_json(summed), 'reported_total':_interval_json(total)}
            return {**base, 'status':'SOURCE_BOUND_CONDITIONAL_CHECK', 'reason':None, 'facts':facts,
                    'point_difference':str(values[0]+values[1]-values[2]), 'modes':modes,
                    'assumptions':['LISTED_CURRENT_PLUS_NONCURRENT_EQUALS_LISTED_TOTAL', 'EACH_MODE_TESTED_SEPARATELY_NOT_SELECTED_FOR_ISSUER']}
        except DebtPrecisionError as exc:
            return {**base, 'status':'WITHHELD', 'reason':str(exc), 'facts':[], 'point_difference':None, 'modes':{}, 'assumptions':[]}


def prepare_bundle(raw: bytes):
    """Per-call object only. Replay callers always provide and reparse raw bytes."""
    return _Bundle(raw)
