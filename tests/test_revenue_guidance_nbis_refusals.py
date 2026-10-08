"""G4a synthetic-only hygiene/refusal pins; no genuine NBIS qualification."""
import copy
from decimal import Decimal
import html
import json
import re
import unittest
from urllib.parse import urlsplit

from tests import nbis_synthetic_sources as f


def leaves(value, path=()):
    if isinstance(value, dict):
        for key, child in value.items():
            yield from leaves(child, path + (key,))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from leaves(child, path + (index,))
    else:
        yield path, value


def curated_denylist():
    curated = next(row for row in json.loads((f.ROOT / 'config/revenue-guidance-v1.json').read_bytes())['issuers']
                   if row['symbol'] == 'NBIS')
    deny = {key: set() for key in ('accessions', 'urls', 'hashes', 'names', 'numbers')}
    for path, value in leaves(curated):
        if type(value) in (int, float):
            deny['numbers'].add(Decimal(str(value)))
        elif isinstance(value, str):
            deny['accessions'].update(re.findall(r'\b[0-9]{10}-[0-9]{2}-[0-9]{6}\b|\b[0-9]{18}\b', value))
            if path[-1] == 'sha256':
                deny['hashes'].add(value)
            if value.startswith('https://'):
                deny['urls'].add(value)
                if path[-1] == 'url' and path[0] == 'documents':
                    deny['names'].add(urlsplit(value).path.rsplit('/', 1)[-1])
    return curated, deny


class SyntheticHygiene(unittest.TestCase):
    def check_text(self, text, deny):
        for kind in ('accessions', 'hashes', 'names'):
            for value in deny[kind]:
                self.assertNotIn(value, text, (kind, value))
        # Financial text is inspected independently of the product parser. Cover
        # both currency prose and displayed decimal table values, including the
        # million/billion representation of each amount (not only JSON numbers).
        visible = html.unescape(re.sub(r'<[^>]*>', ' ', text))
        number = r'([0-9]+(?:,[0-9]{3})*(?:\.[0-9]+)?)'
        for match in re.finditer(r'(?:\$|\bUSD\s+)' + number + r'\s*(B|billion|million)?', visible):
            value = Decimal(match[1].replace(',', ''))
            scale = {'B': 1000000000, 'billion': 1000000000, 'million': 1000000}.get(match[2], 1)
            self.assertNotIn(value, deny['numbers'])
            self.assertNotIn(value * scale, deny['numbers'])
        for cell in re.findall(r'<t[dh](?:\s[^>]*)?>(.*?)</t[dh]>', text, re.S):
            cell = html.unescape(re.sub(r'<[^>]*>', '', cell)).strip()
            if re.fullmatch(r'[0-9]+(?:,[0-9]{3})*\.[0-9]+', cell):
                value = Decimal(cell.replace(',', ''))
                self.assertNotIn(value, deny['numbers'])
                self.assertNotIn(value * 1000000, deny['numbers'])

    def check_url(self, value, path, deny):
        # CLOSED path/value exceptions. Product pins at the frozen ab0fb67d:
        # auto_verify.py:38,2273; revenue_guidance.py:992-997 (policy, not fetch).
        policy_paths = {('baseline', 'url_prefixes', 0): f.ARCHIVES,
                        ('record', 'url_prefixes', 0): 'https://www.sec.gov/Archives/edgar/data/',
                        ('attempt', 'record', 'url_prefixes', 0): 'https://www.sec.gov/Archives/edgar/data/'}
        if path in policy_paths:
            self.assertEqual(value, policy_paths[path])
            return
        # Closed channel list: release_check.py:283-300 passes ir.url to
        # issuer_ir_feeds.read_channel; tracked NBIS config:3227-3229.
        endpoints = {'https://group.nebius.com/newsroom'}
        if value in endpoints:
            return
        self.assertNotIn(value, deny['urls'])
        if value == 'https://data.sec.gov/submissions/CIK0001513845.json':
            # autoupdate.py:546 and auto_verify.py:2013 exact issuer endpoint.
            return
        if urlsplit(value).hostname == 'www.sec.gov':
            self.assertRegex(value, r'^https://www\.sec\.gov/Archives/edgar/data/1513845/0000000000[0-9]{8}/[A-Za-z0-9._-]+$')
        else:
            self.assertRegex(value, r'^https://(?:group\.nebius\.com/newsroom|www\.nasdaq\.com/press-release)/synthetic-g4-[a-z0-9-]+$')

    def test_complete_positive_corpus_is_non_curated(self):
        curated, deny = curated_denylist()
        self.assertTrue(all(deny.values()))
        self.assertEqual(curated['url_prefixes'], ['https://www.sec.gov/Archives/edgar/data/'])
        for mode in ('Z', 'R'):
            with self.subTest(mode=mode), f.Scenario(mode) as s:
                f.guidance.validate_issuer_record(s.baseline, 'NBIS')
                s.plan()
                result = s.build()
                self.assertEqual(result['outcome'], 'VERIFIED', result['detail'])
                self.assertIsNotNone(result['record'])
                attempt = f.updater._attempt(s.lead['accession'], s.now, s.baseline, s.event, s.captures, result)
                corpus = {'baseline': s.baseline, 'record': result['record'], 'attempt': attempt}
                for root in (s.baseline, result['record'], attempt['record']):
                    self.assertEqual(root['url_prefixes'], [f.ARCHIVES] if root is s.baseline else curated['url_prefixes'])
                    # CIK identity auto_verify.py:1181,2013; emitted claim unit :2179.
                    self.assertEqual(root['release_channels']['sec_cik'], 1513845)
                    self.assertTrue(root['claims'])
                    for claim in root['claims']:
                        self.assertEqual(claim['unit_multiplier'], 1)
                for url, raw in s.bodies.items():
                    text = raw.decode('utf-8')
                    self.assertIn(f.MARKER, text)
                    self.check_url(url, ('body_url',), deny)
                    self.check_text(text, deny)
                    if url.endswith('.json'):
                        corpus['body:' + url] = json.loads(raw)
                    for link in re.findall(r'https://[^\s<>"\']+', text):
                        self.check_url(link, ('html_link',), deny)
                for url in s.transport.requests:
                    self.check_url(url, ('request',), deny)
                for path, value in leaves(corpus):
                    if type(value) in (int, float):
                        numeric = Decimal(str(value))
                        if numeric not in deny['numbers']:
                            continue
                        record_path = path[1:] if path[0] in ('baseline', 'record') else path[2:] if path[:2] == ('attempt', 'record') else None
                        if record_path == ('release_channels', 'sec_cik'):
                            self.assertEqual(value, 1513845)
                        elif (record_path is not None and len(record_path) == 3 and record_path[0] == 'claims'
                              and type(record_path[1]) is int and record_path[2] == 'unit_multiplier'):
                            self.assertEqual(value, 1)
                        elif path == ('body:' + f.SUBMISSIONS, 'cik'):
                            self.assertEqual(value, 1513845)
                        else:
                            self.fail('Non-exempt numeric collision: ' + repr((path, value)))
                    elif isinstance(value, str):
                        self.check_text(value, deny)
                        if value.startswith('https://'):
                            self.check_url(value, path, deny)
                forbidden_fetches = {f.ARCHIVES, 'https://www.sec.gov/Archives/edgar/data/'}
                self.assertTrue(forbidden_fetches.isdisjoint(s.transport.requests))
                self.assertTrue(forbidden_fetches.isdisjoint(s.bodies))
                for root in (s.baseline, result['record'], attempt['record']):
                    self.assertTrue(forbidden_fetches.isdisjoint(d['url'] for d in root['documents']))


def observe(label, value):
    """Audit runner records this raw value before the caller's assertions."""
    return value


def replace_capture(s, key, raw):
    previous = f.overlay.load_capture(s.root, s.captures[key])
    s.captures[key] = f.overlay.store_capture(s.root, raw, previous)


def append_paragraph(raw, text):
    return raw.replace(b'</body>', ('<p>' + text + '</p></body>').encode('utf-8'))


class SyntheticRefusals(unittest.TestCase):
    def refused(self, result, reason, detail, outcome='BLOCKED'):
        observe('builder-refusal', result)
        self.assertEqual(result['outcome'], outcome, result)
        self.assertEqual(result['reason'], reason, result)
        self.assertIn(detail, result['detail'])
        self.assertIsNone(result['record'])
        self.assertEqual(result['decisions'], [])

    def test_captured_body_refusals(self):
        rows = [
            ('fy-heading', 'Z', 'letter', 'INPUT_MALFORMED', 'NBIS full positive heading'),
            ('fy-closed', 'Z', 'letter', 'PERIOD_MISMATCH', 'NBIS closed guidance block heading/FY'),
            ('fy-word-glued', 'Z', 'letter', 'PERIOD_MISMATCH', 'NBIS guidance versus first forward FY'),
            ('original-missing', 'Z', 'letter', 'INPUT_MISSING', 'NBIS unique original numeric FY source'),
            ('unaccounted-href', 'Z', 'letter', 'INCOMPLETE_EVENT_COVERAGE', 'NBIS unaccounted operative link'),
            ('missing-ir-link', 'Z', 'ir_copy', 'INCOMPLETE_EVENT_COVERAGE', 'NBIS required original package links missing'),
            ('opaque-img', 'Z', 'letter', 'UNSUPPORTED_TEMPLATE', 'NBIS opaque operative content'),
            ('txt-member', 'Z', 'index', 'UNSUPPORTED_TEMPLATE', 'NBIS unknown/uninspectable index member'),
            ('statement-coupling', 'Z', 'statement', 'AMBIGUOUS', 'NBIS unique consolidated statement'),
            ('corroboration-coupling', 'Z', 'statement', 'AMBIGUOUS', 'NBIS unique current highlights corroboration'),
            ('highlights-disagree', 'Z', 'statement', 'SOURCE_DISAGREEMENT', 'NBIS highlights/current statement'),
            ('difference-disagree', 'Z', 'statement', 'SOURCE_DISAGREEMENT', 'NBIS exact direct/difference reconciliation'),
            ('competing-revenue', 'Z', 'letter', 'AMBIGUOUS', 'NBIS additional competing revenue-guidance clause'),
            ('two-headings', 'Z', 'letter', 'AMBIGUOUS', 'NBIS unique full FY revenue/ARR clause'),
            ('r-numeric', 'R', 'letter', 'UNSUPPORTED_TEMPLATE', 'NBIS competing numeric outlook'),
            ('r-negated', 'R', 'letter', 'SOURCE_DISAGREEMENT', 'NBIS negated/excepted reaffirmation'),
        ]
        for name, mode, slot, reason, detail in rows:
            with self.subTest(row=name), f.Scenario(mode) as s:
                s.plan()
                key = slot if slot == 'ir_copy' else s.event['packages'][0][slot]
                raw = s.loaded()[key]['raw']
                if name == 'fy-heading':
                    raw = raw.replace(b'revenue in 2032', b'revenue in 2033')
                elif name == 'fy-closed':
                    raw = raw.replace(b'2032 Guidance update</p><p>', b'2032 Guidance update ').replace(b'revenue in 2032', b'revenue in 2033')
                elif name == 'fy-word-glued':
                    raw = append_paragraph(raw.replace(b'2032', b'2033'), 'x2032 Guidance update')
                elif name == 'original-missing':
                    raw = raw.replace(b'2032 Guidance update', b'Synthetic guidance heading')
                elif name == 'unaccounted-href':
                    raw = append_paragraph(raw, '<a href="https://group.nebius.com/newsroom/synthetic-g4-unaccounted">Other</a>')
                elif name == 'missing-ir-link':
                    target = s.packages[0].base + s.packages[0].names[2]
                    raw = raw.replace(('<a href="' + target + '">Exhibit 2</a>').encode(), b'')
                elif name == 'opaque-img':
                    raw = append_paragraph(raw, '<img/>')
                elif name == 'txt-member':
                    data = json.loads(raw)
                    data['directory']['item'].append({'name': 'synthetic-g4-extra.txt'})
                    raw = f.encoded(data)
                elif name == 'statement-coupling':
                    basis = f'<p>{f.GAAP}</p><p>{f.CONTINUING}</p>'.encode()
                    raw = raw.replace(basis, b'').replace(b'<p>Financial Highlights', basis + b'<p>Financial Highlights')
                elif name == 'corroboration-coupling':
                    raw = raw.replace(('<p>' + f.HEADING).encode(), ('<p>Financial Highlights Consolidated results</p><p>' + f.HEADING).encode())
                elif name == 'highlights-disagree':
                    raw = raw.replace(b'1,444.4', b'1,444.5', 1)
                elif name == 'difference-disagree':
                    raw = raw.replace(b'5,111.0', b'5,111.1')
                elif name == 'competing-revenue':
                    raw = append_paragraph(raw, '$8B revenue.')
                elif name == 'two-headings':
                    raw = append_paragraph(raw, '2032 Guidance update')
                elif name == 'r-numeric':
                    raw = append_paragraph(raw, '$8B revenue outlook.')
                elif name == 'r-negated':
                    raw = append_paragraph(raw, 'We are not reaffirming revenue.')
                replace_capture(s, key, raw)
                self.refused(s.build(), reason, detail)

    def test_event_order_and_coverage_refusals(self):
        rows = [('ir-missing', 'Z'), ('same-day-material', 'Z'), ('later-material', 'Z'),
                ('regression', 'Z'), ('same-anchor', 'Z'), ('two-letters', 'Z'),
                ('same-day-original', 'R'), ('intervening-material', 'R'), ('wrong-role', 'Z')]
        for name, mode in rows:
            with self.subTest(row=name), f.Scenario(mode) as s:
                s.plan()
                outcome = 'BLOCKED'
                if name == 'ir-missing':
                    s.event['ir_item'] = None
                    reason, detail, outcome = 'INCOMPLETE_EVENT_COVERAGE', 'NBIS official IR member/channel publication', 'WAITING'
                elif name in ('same-day-material', 'later-material', 'intervening-material'):
                    day = {'same-day-material': '2032-02-19', 'later-material': '2032-02-20',
                           'intervening-material': '2034-07-01'}[name]
                    s.event['later_documents'].append({'channel': 'ISSUER_IR', 'id': 'https://group.nebius.com/newsroom/synthetic-g4-material',
                        'date': day, 'label': 'Synthetic material', 'disposition': 'POSSIBLY_RELEVANT'})
                    reason, detail = 'EVENT_UNRESOLVED', 'NBIS unaccounted intervening/same-day/later material'
                elif name in ('regression', 'same-anchor'):
                    s.baseline['reported_quarters'][0]['end'] = '2032-03-31' if name == 'regression' else '2031-12-31'
                    reason = 'OUT_OF_ORDER'
                    detail = 'NBIS actual anchor regression' if name == 'regression' else 'NBIS same-anchor without later reaffirmation'
                elif name == 'two-letters':
                    key = s.event['packages'][1]['letter']
                    raw = append_paragraph(s.loaded()[key]['raw'], '2032 Guidance update')
                    replace_capture(s, key, append_paragraph(raw, f.fy_block(2032)))
                    reason, detail = 'AMBIGUOUS', 'NBIS unique original numeric FY source'
                elif name == 'same-day-original':
                    s.event['packages'][1]['filed'] = s.event['filed']
                    for entry in s.event['channel_history']:
                        if entry['accession'] == s.event['packages'][1]['accession']:
                            entry['item']['date'] = s.event['filed']
                    data = json.loads(s.loaded()['submissions']['raw'])
                    data['filings']['recent']['filingDate'][1] = s.event['filed']
                    replace_capture(s, 'submissions', f.encoded(data))
                    reason, detail = 'AMBIGUOUS', 'NBIS same-day unproven separate original-guidance event'
                else:
                    loaded = s.loaded()
                    loaded[s.event['packages'][0]['letter']]['role'] = 'SEC_INDEX'
                    result = f.verify.build_successor(s.profile, f.overlay.predecessor_view(s.baseline, s.baseline), s.event, loaded, s.now)
                    self.refused(result, 'APPROVAL_BINDING', 'NBIS source role')
                    continue
                self.refused(s.build(), reason, detail, outcome)

    def test_replay_role_admission(self):
        with f.Scenario() as s:
            s.transport.replay = True
            s.plan()
            result = s.build()
            self.assertEqual(result['outcome'], 'VERIFIED', result)
            attempt = f.updater._attempt(s.lead['accession'], s.now, s.baseline, s.event, s.captures, result)
            self.assertIsNone(f.overlay.validate_attempt(attempt))
            with self.assertRaises(f.overlay.StateError) as caught:
                f.overlay.rederive(s.root, s.profile, s.baseline, attempt, allow_replay=False, baseline=s.baseline)
            observe('replay-denial', str(caught.exception))
            self.assertEqual(str(caught.exception), 'REPLAY_CAPTURE')
            replayed = f.overlay.rederive(s.root, s.profile, s.baseline, attempt, allow_replay=True, baseline=s.baseline)
            observe('replay-allowed', replayed)
            self.assertEqual(f.verify.canonical_json(replayed), f.verify.canonical_json(result))

    def test_alias_32_boundary_before_request(self):
        with f.Scenario() as s:
            s.plan(captures={f'synthetic-padding-{i}': '0' * 64 for i in range(12)})
            observe('alias-at-limit', {'aliases': len(s.captures), 'requests': s.transport.requests})
            self.assertEqual(len(s.captures), 32)
            self.assertEqual(s.transport.requests, s.expected_requests())
        with f.Scenario() as s:
            aliases = {f'synthetic-padding-{i}': '0' * 64 for i in range(32)}
            with self.assertRaises(f.verify.Blocked) as caught:
                s.plan(captures=aliases)
            error = caught.exception
            observe('alias-over-limit', {'outcome': error.outcome, 'reason': error.reason, 'detail': error.detail,
                                       'requests': s.transport.requests, 'aliases': len(aliases)})
            self.assertEqual((error.outcome, error.reason, error.detail), ('WAITING', 'CAPTURE_LIMIT', 'NBIS capture domain'))
            self.assertEqual(s.transport.requests, [])
            self.assertEqual(len(aliases), 32)
            self.assertFalse(s.root.exists())

    def test_historical_package_8_bound_is_reachable(self):
        with f.Scenario() as s:
            packages = [f.Package(f'0000000000-32-{105-i:06d}', f'2032-02-{19-i:02d}', 2031, 4,
                                  '1,444.4', '5,111.0', original=2032 if i == 0 else None) for i in range(9)]
            recent = {key: [] for key in ('accessionNumber', 'form', 'filingDate', 'reportDate', 'primaryDocument')}
            bodies = {}
            for p in packages:
                docs = p.documents()
                statement = p.base + p.names[1]
                bodies[statement] = append_paragraph(docs[statement], f'{f.COMPANY} FORM 6-K financial results for the fourth quarter of 2031')
                bodies[p.base + p.names[2]] = docs[p.base + p.names[2]]
                bodies[p.base + 'index.json'] = f.encoded({'_synthetic': f.MARKER, 'directory': {'item': [{'name': n} for n in p.names[1:]]}})
                for key, value in zip(recent, (p.accession, '6-K', p.filed, '2031-12-31', p.names[1])):
                    recent[key].append(value)
            bodies[f.SUBMISSIONS] = f.encoded({'_synthetic': f.MARKER, 'cik': 1513845, 'filings': {'recent': recent}})
            s.transport = f.FixtureTransport(bodies)
            aliases = {}
            with self.assertRaises(f.verify.Blocked) as caught:
                s.plan(captures=aliases)
            error = caught.exception
            observe('packages-over-limit', {'outcome': error.outcome, 'reason': error.reason, 'detail': error.detail,
                                           'requests': s.transport.requests, 'aliases': len(aliases)})
            self.assertEqual((error.outcome, error.reason, error.detail), ('WAITING', 'CAPTURE_LIMIT', 'NBIS bounded historical package domain'))
            expected = [f.SUBMISSIONS]
            for p in packages[:8]:
                expected += [p.base + 'index.json'] + [p.base + n for n in p.names[1:]]
            self.assertEqual(s.transport.requests, expected)
            self.assertEqual(len(aliases), 25)
            self.assertNotIn(packages[8].base + 'index.json', s.transport.requests)

    def test_grid_exact_limits(self):
        table = '<table><tr><td rowspan="32" colspan="32">synthetic</td></tr>' + '<tr></tr>' * 31 + '</table>'
        controls = [('span', table, 1), ('nesting', '<table>' * 8 + '<tr><td>synthetic</td></tr>' + '</table>' * 8, 8),
                    ('slots', table * 32, 32)]
        for name, body, count in controls:
            with self.subTest(control=name):
                try:
                    _, tables = f.verify.nbis_document(f.html('grid-' + name, body))
                except f.verify.Blocked as error:
                    observe('grid-control-refused-' + name, {'outcome': error.outcome, 'reason': error.reason, 'detail': error.detail})
                    self.fail('At-limit grid control refused: ' + error.reason + ': ' + error.detail)
                observe('grid-' + name, {'tables': len(tables), 'slots': sum(len(t['grid']) for t in tables)})
                self.assertEqual(len(tables), count)
                if name == 'slots':
                    self.assertEqual(sum(len(t['grid']) for t in tables), 32768)
        refusals = [('span', table.replace('rowspan="32"', 'rowspan="33"'), 'UNSUPPORTED_TEMPLATE', 'unsupported NBIS span'),
                    ('nesting', '<table>' * 9, 'CAPTURE_LIMIT', 'NBIS table nesting/count'),
                    ('slots', table * 32 + '<table><tr><td>x</td></tr></table>', 'CAPTURE_LIMIT', 'NBIS total expanded grid')]
        for name, body, reason, detail in refusals:
            with self.subTest(refusal=name):
                with self.assertRaises(f.verify.Blocked) as caught:
                    f.verify.nbis_document(f.html('grid-over-' + name, body))
                error = caught.exception
                observe('grid-over-' + name, {'outcome': error.outcome, 'reason': error.reason, 'detail': error.detail})
                self.assertEqual((error.outcome, error.reason, error.detail), ('BLOCKED', reason, detail))


class MalformedCharacterization(unittest.TestCase):
    """Typed parser refusals; marked-section preconditions require CPython 3.12.10."""
    refused = SyntheticRefusals.refused

    def row(self, label, fn, expected):
        actual = f.outcome_of(fn)
        f.observe_boundary(label, actual)
        with self.subTest(row=label):
            self.assertEqual(actual, expected)

    @staticmethod
    def blocked(reason, detail):
        return ("RESULT", {"outcome": "BLOCKED", "reason": reason, "detail": detail, "record": None, "decisions": []})

    def test_malformed_raw_builder_and_planner(self):
        rows = [('xml', 'UNSUPPORTED_TEMPLATE', 'not well-formed XML'),
                ('unclosed-table', 'UNSUPPORTED_TEMPLATE', 'unclosed NBIS document')]
        for name, reason, detail in rows:
            with self.subTest(row=name), f.Scenario() as s:
                s.plan()
                key = s.event['packages'][0]['statement']
                raw = s.loaded()[key]['raw']
                raw = raw.replace(b'</body>', b'<br></body>') if name == 'xml' else raw.replace(b'</table>', b'', 1)
                replace_capture(s, key, raw)
                self.refused(s.build(), reason, detail)

    def test_non_utf8_is_typed_builder_and_planner(self):
        with f.Scenario() as s:
            s.plan()
            key = s.event["packages"][0]["statement"]
            original = s.loaded()[key]["raw"]
            replace_capture(s, key, original + b"\xff")
            self.row("nbis.builder.non-utf8", s.build,
                     self.blocked("CANONICALIZATION_FAILED", f"not UTF-8 at byte {len(original)}"))
        with f.Scenario() as s:
            p = s.packages[0]
            url = p.base + p.names[1]
            original = s.bodies[url]
            s.bodies[url] += b"\xff"
            captures = {}
            self.row("nbis.planner.non-utf8", lambda: s.plan(captures=captures),
                     ("BLOCKED", "BLOCKED", "CANONICALIZATION_FAILED", f"not UTF-8 at byte {len(original)}"))
            self.assertEqual(s.transport.requests, [f.SUBMISSIONS, p.base + "index.json", p.base + p.names[0], url])
            self.assertIn("nbis:" + p.accession + ":statement", captures)

    def test_marked_section_is_typed_builder_and_planner(self):
        from html.parser import HTMLParser
        for name, marker in (("bogus", b"<![bogus["), ("endif", b"<![ endif]>")):
            with self.assertRaises(AssertionError):
                HTMLParser().feed(marker.decode("ascii"))
            for slot in ("letter", "statement", "ir_copy", "nbis:0000000000-31-000305:wire_copy"):
                with self.subTest(marker=name, slot=slot), f.Scenario() as s:
                    s.plan()
                    key = slot if slot in s.captures else s.event["packages"][0][slot]
                    raw = f.insert_before_body(self, s.loaded()[key]["raw"], marker)
                    replace_capture(s, key, raw)
                    self.row("nbis.builder.marked." + slot + "." + name, s.build,
                             self.blocked("UNSUPPORTED_TEMPLATE", f.HTML_UNREADABLE))
            with f.Scenario() as s:
                p = s.packages[0]
                url = p.base + p.names[2]
                s.bodies[url] = f.insert_before_body(self, s.bodies[url], marker)
                self.row("nbis.planner.marked." + name, s.plan,
                         ("BLOCKED", "BLOCKED", "UNSUPPORTED_TEMPLATE", f.HTML_UNREADABLE))
                self.assertEqual(s.transport.requests, [f.SUBMISSIONS, p.base + "index.json"] + [p.base + n for n in p.names])

    def test_unknown_xml_encoding_is_typed(self):
        prefix = b'<?xml version="1.0" encoding="x-synthetic-unknown"?>'
        with f.Scenario() as s:
            s.plan()
            key = s.event["packages"][0]["statement"]
            replace_capture(s, key, prefix + s.loaded()[key]["raw"])
            self.row("nbis.builder.xml-unknown", s.build, self.blocked("INPUT_MALFORMED", "LookupError"))
        with f.Scenario() as s:
            p = s.packages[0]
            url = p.base + p.names[1]
            s.bodies[url] = prefix + s.bodies[url]
            self.row("nbis.planner.xml-unknown", s.plan, ("BLOCKED", "BLOCKED", "INPUT_MALFORMED", "LookupError"))
            self.assertEqual(s.transport.requests, [f.SUBMISSIONS, p.base + "index.json"] + [p.base + n for n in p.names])

    def test_accepted_sections_reach_planner_and_builder(self):
        with f.Scenario() as s:
            p = s.packages[0]
            url = p.base + p.names[2]
            s.bodies[url] = f.insert_before_body(self, s.bodies[url], b"<![if !supportLists]><![endif]>")
            def invoke():
                s.plan()
                result = s.build()
                return {"outcome": result["outcome"], "reason": result["reason"], "detail": result["detail"],
                        "requests": s.transport.requests}
            self.row("nbis.accepted-letter", invoke, ("RESULT", {"outcome": "VERIFIED", "reason": None,
                     "detail": "", "requests": s.expected_requests()}))

    def test_transport_assertion_propagates(self):
        with f.Scenario() as s:
            p = s.packages[0]
            url = p.base + p.names[2]
            del s.bodies[url]
            self.row("nbis.transport-assertion", s.plan,
                     ("RAISED", "AssertionError", "UNEXPECTED_SYNTHETIC_REQUEST " + url))
            self.assertEqual(s.transport.requests, [f.SUBMISSIONS, p.base + "index.json"] + [p.base + n for n in p.names])

    def test_enabled_sec_8k_parser_refusals_are_typed(self):
        # Only synthetic bytes, never modified retained replay corpus outside TEMP.
        p = f.verify.validate_profiles(f.tracked())["NVDA"]
        acc, filed, name = "0000000000-32-000105", "2032-02-19", "q4fy32pr.htm"
        base = f'https://www.sec.gov/Archives/edgar/data/{p["cik"]}/{acc.replace("-", "")}/'
        submissions = f'https://data.sec.gov/submissions/CIK{p["cik"]:010d}.json'
        plain = f.html("enabled-8k-parser", "Synthetic only")
        xhtml = f.html("enabled-8k-parser", "Synthetic only", xhtml=True)
        rows = [
            ("bogus", plain + b"<![bogus[", "UNSUPPORTED_TEMPLATE", f.HTML_UNREADABLE),
            ("endif", plain + b"<![ endif]>", "UNSUPPORTED_TEMPLATE", f.HTML_UNREADABLE),
            ("charref", b"<p>&#" + b"1" * 4301 + b";</p>", "INPUT_MALFORMED", "ValueError"),
            ("table", b"<table><tr><td>x</table><table>", "INPUT_MALFORMED", "IndexError"),
            ("xml-unknown", b'<?xml version="1.0" encoding="x-synthetic-unknown"?>' + xhtml, "INPUT_MALFORMED", "LookupError"),
            ("xml-multibyte", b'<?xml version="1.0" encoding="Shift_JIS"?>' + xhtml, "INPUT_MALFORMED", "ValueError"),
            ("non-utf8", plain + b"\xff", "CANONICALIZATION_FAILED", f"not UTF-8 at byte {len(plain)}"),
        ]
        for row_name, raw, reason, detail in rows:
            with self.subTest(payload=row_name), f.Scenario() as s:
                if row_name in ("bogus", "endif"):
                    from html.parser import HTMLParser
                    with self.assertRaises(AssertionError):
                        HTMLParser().feed("<![bogus[" if row_name == "bogus" else "<![ endif]>")
                bodies = {submissions: f.encoded({"_synthetic": f.MARKER, "cik": p["cik"], "filings": {"recent": {
                    "accessionNumber": [acc], "form": ["8-K"], "filingDate": [filed], "reportDate": ["2031-12-31"],
                    "primaryDocument": [name], "items": ["2.02"]}}}),
                    base + "index.json": f.encoded({"_synthetic": f.MARKER, "directory": {"item": [{"name": name}]}}),
                    base + name: raw}
                requests, captures = [], {}
                case = self
                class Transport:
                    replay = False
                    def get(self, url, profile, symbol):
                        requests.append(url)
                        case.assertEqual(symbol, "NVDA")
                        kind = f.updater.url_rule(url, profile)
                        return bodies[url], f.updater.CONTENT_TYPES[kind][0]
                lead = {"accession": acc, "filed": filed, "ir_item": None, "wire_item": None, "later_documents": []}
                planned = [lead]
                def plan():
                    event, _ = f.updater.plan_event(Transport(), s.root, p, lead, filed, s.clock,
                                                    {"bytes": 0, "store": 0}, captures=captures)
                    planned[0] = event
                    return {"periodic": event["periodic"], "calendar": event["calendar"],
                            "allocation_sources": event["allocation_sources"],
                            "captures": sorted(captures), "requests": requests}
                self.row("a1.planner." + row_name, plan, ("RESULT", {"periodic": {}, "calendar": None,
                    "allocation_sources": [], "captures": ["exhibit", "index", "submissions"],
                    "requests": [submissions, base + "index.json", base + name]}))
                loaded = {key: f.overlay.load_capture(s.root, digest) for key, digest in captures.items()}
                self.row("a1.builder." + row_name,
                         lambda: f.verify.build_successor(p, {}, planned[0], loaded, s.now), self.blocked(reason, detail))


class NbisParserBoundary(unittest.TestCase):
    """Raw unfinished-table rows are stability pins (BATCH10B AMEND1)."""
    def row(self, label, fn, expected):
        actual = f.outcome_of(fn)
        f.observe_boundary(label, actual)
        self.assertEqual(actual, expected)

    def test_direct_rows(self):
        from html.parser import HTMLParser
        import sys
        self.assertEqual(sys.version_info[:3], (3, 12, 10))
        self.assertEqual(sys.get_int_max_str_digits(), 4300)
        base = f.html("pb", "<p>x</p>")
        rows = [
            ("bogus", b"<![bogus[", "UNSUPPORTED_TEMPLATE", f.HTML_UNREADABLE),
            ("endif", b"<![ endif]>", "UNSUPPORTED_TEMPLATE", f.HTML_UNREADABLE),
            ("non-utf8", b"\xff", "CANONICALIZATION_FAILED", f"not UTF-8 at byte {len(base)}"),
            ("charref", b"<p>&#" + b"1" * 4301 + b";</p>", "INPUT_MALFORMED", "ValueError"),
            ("table", b"<table><tr><td>x</table><table>", "UNSUPPORTED_TEMPLATE", "unfinished NBIS table/span"),
        ]
        sites = [("nbis_document", f.verify.nbis_document),
                 ("_nbis_package_links", lambda raw: f.verify._nbis_package_links(raw, f.ARCHIVES + "synthetic-g4-x/"))]
        for site, parse in sites:
            for name, suffix, reason, detail in rows:
                with self.subTest(site=site, row=name):
                    if name in ("bogus", "endif"):
                        with self.assertRaises(AssertionError):
                            HTMLParser().feed(suffix.decode("ascii"))
                    self.row("nbis." + site + "." + name, lambda: parse(base + suffix),
                             ("BLOCKED", "BLOCKED", reason, detail))

    def test_dg41_must_still_refuse(self):
        namespace = b"http://www.xbrl.org/2013/inlineXBRL"
        encoded = "".join("&#" + str(c) + ";" for c in namespace).encode("ascii")
        rows = [
            ("ix-text-unclosed", "UNSUPPORTED_TEMPLATE", "not well-formed XML"),
            ("rebound", "UNSUPPORTED_TEMPLATE", "namespace prefix 'ix' bound more than once"),
            ("entity", "UNSUPPORTED_TEMPLATE", "unexpected markup before the inline XBRL document"),
            ("duplicate-context", "SOURCE_DISAGREEMENT", "duplicate XBRL context/unit ids ['synthetic-duplicate']"),
            ("charref-namespace-token", "UNSUPPORTED_TEMPLATE", f.PLAIN_HTML),
            ("charref-namespace-element", "UNSUPPORTED_TEMPLATE", f.PLAIN_HTML),
            ("charref-namespace-default", "UNSUPPORTED_TEMPLATE", f.PLAIN_HTML),
        ]
        for name, reason, detail in rows:
            with self.subTest(row=name), f.Scenario() as s:
                s.plan()
                key = s.event["packages"][0]["statement"]
                old = s.loaded()[key]["raw"]  # XHTML base for rebound/entity/duplicate.
                self.assertEqual(old.count(namespace), 1)
                raw = old
                if name == "ix-text-unclosed":
                    raw = old.replace(b' xmlns:ix="' + namespace + b'"', b"")
                    raw = f.insert_before_body(self, raw, b"<p>" + namespace + b"</p><br>")
                elif name == "rebound":
                    raw = f.insert_before_body(self, raw, b'<span xmlns:ix="urn:synthetic:other"></span>')
                elif name == "entity":
                    raw = f.insert_before_body(self, raw, b'<!ENTITY synthetic "x">')
                elif name == "duplicate-context":
                    context = b'<xbrli:context xmlns:xbrli="http://www.xbrl.org/2003/instance" id="synthetic-duplicate"/>'
                    raw = f.insert_before_body(self, raw, b"<ix:header>" + context * 2 + b"</ix:header>")
                elif name == "charref-namespace-token":
                    raw = old.replace(namespace, b"http&#58;//www.xbrl.org/2013/inlineXBRL")
                else:
                    raw = old.replace(namespace, encoded)
                    fact = (b'<ix:nonFraction name="us-gaap:Revenues">1</ix:nonFraction>'
                            if name == "charref-namespace-element" else
                            b'<nonFraction xmlns="http://www.xbrl.org/2013/inline&#88;BRL" name="us-gaap:Revenues">1</nonFraction>')
                    raw = f.insert_before_body(self, raw, b"<ix:header>" + fact + b"</ix:header>")
                self.assertNotEqual(raw, old)
                replace_capture(s, key, raw)
                def invoke():
                    result = s.build()
                    if name == "ix-text-unclosed" and isinstance(result.get("detail"), str):
                        result = dict(result, detail=result["detail"].partition(":")[0])
                    return result
                self.row("dg41.refuse." + name, invoke, ("RESULT", {"outcome": "BLOCKED",
                    "reason": reason, "detail": detail, "record": None, "decisions": []}))

    def test_feed_close_stubs(self):
        from unittest import mock
        sites = [("grid", f.verify._NbisGrid, f.verify.nbis_document),
                 ("links", f.verify._NbisLinks, lambda raw: f.verify._nbis_package_links(raw, f.ARCHIVES + "synthetic-g4-x/"))]
        for site, cls, parse in sites:
            for method in ("feed", "close"):
                for error, expected in f.parser_stubs():
                    with self.subTest(site=site, method=method, error=type(error).__name__):
                        seen = []
                        def invoke():
                            try:
                                return parse(f.html("pb-stub", "<p>x</p>"))
                            except f.verify.Blocked as caught:
                                seen.append(caught)
                                raise
                        with mock.patch.object(cls, method, side_effect=error):
                            self.row("nbis." + site + ".stub." + method + "." + type(error).__name__, invoke, expected)
                        if isinstance(error, f.verify.Blocked):
                            self.assertIs(seen[0], error)


if __name__ == '__main__':
    unittest.main()
