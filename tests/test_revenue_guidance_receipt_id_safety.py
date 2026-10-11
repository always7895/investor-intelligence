"""SYNTHETIC_G9_NOT_GENUINE: BATCH10C F8, a receipt listing a raw later-document id with userinfo, query or fragment is a
barrier; the persisted form <shown>#sha256:<hex> flows like a clean id (F8-AMEND1).

Fake connector and clocks only; ZQA is synthetic, never issuer admission. No subprocess, no network.
"""
from __future__ import annotations

from contextlib import ExitStack
import dataclasses
import itertools
import json
from pathlib import Path
import socket
import tempfile
import unittest
from unittest import mock

import hashlib

from tests import g9a_synthetic_issuers as h
from tests import nbis_synthetic_sources as f
from tests import test_revenue_guidance_autoupdate as replay
from tests import test_revenue_guidance_machine_auto_parity as auto_parity

updater, overlay, guidance = f.updater, f.overlay, f.guidance
W = h.World
SECRETS = ('zqauser', 'S3CRETPW', 'T0KEN', 'FR4G')
IR = 'https://ir.zqa.synthetic-g9.example/'
UNSAFE_IDS = (
    'https://zqauser:S3CRETPW@ir.zqa.synthetic-g9.example/',
    'https://ir.zqa.synthetic-g9.example/?t=T0KEN',
    'https://ir.zqa.synthetic-g9.example/#FR4G',
    'https://zqauser:S3CRETPW@ir.zqa.synthetic-g9.example/?t=T0KEN#FR4G',
    'zqauser@host',
)
CUTOFF = '2026-03-03T00:00:00Z'
# Near misses of the persisted form: each still carries a raw '@', '?' or '#', or a digest that is not 64 lowercase hex.
H = 'https://ir.zqa.synthetic-g9.example/news'
NEAR_MISSES = (H + '?x#sha256:' + 'a' * 64, 'u@' + H + '#sha256:' + 'a' * 64, H + '#sha256:' + 'A' * 64,
               H + '#sha256:' + 'a' * 63, H + '#sha256:' + 'a' * 65, H + '#sha256:' + 'a' * 64 + '#x', H + '#x#sha256:' + 'a' * 64)
QUERY = '?utm_source=feed'
ROOT = Path(__file__).resolve().parents[1]
NV = next(p for p in json.loads((ROOT / 'config/revenue-guidance-extraction-profiles-v1.json').read_bytes())['profiles'] if p['symbol'] == 'NVDA')


def state_bytes(world):
    return b''.join(p.read_bytes() for p in sorted(world.state.rglob('*')) if p.is_file()) if world.state.exists() else b''


def secret_free(raw):
    return not any(s.encode() in raw for s in SECRETS)


def classic_receipt(later, status):
    """A fully formed SEC_AND_WIRE receipt (digest and status included) for the unit checks."""
    rc = {'issuer': 'ZQA', 'checked_at': '2026-03-02T11:00:00Z', 'status': status, 'guidance_document_id': 'DOC-1',
          'guidance_published_date': '2026-02-01', 'anchor_end': '2025-12-31', 'coverage': 'SEC_AND_WIRE',
          'channels': [{'kind': 'SEC_SUBMISSIONS', 'url': 'https://data.sec.gov/submissions/CIK0000000001.json', 'status': 'OK',
                        'checked_through': '2026-03-02', 'complete': True},
                       {'kind': 'WIRE_PRESS_RELEASES', 'url': 'https://api.nasdaq.com/api/news/topic/press_release?q=symbol:ZQA',
                        'status': 'OK', 'checked_through': '2026-03-02', 'complete': True}],
          'later_documents': later}
    rc['digest'] = guidance.compute_receipt_digest(rc)
    return rc


def doc(i, disposition='IRRELEVANT', channel='WIRE_PRESS_RELEASES'):
    return {'channel': channel, 'date': '2026-02-15', 'id': i, 'label': 'x', 'disposition': disposition}


def run_world(raw_id, edit=None):
    serial = itertools.count(1)
    with mock.patch.object(updater.secrets, 'token_hex', side_effect=lambda n: f'{next(serial):0{2*n}x}'), W(1, 0) as world:
        if raw_id is not None:
            raw = world.receipts.read_text(encoding='utf-8')
            world.receipts.write_text(raw.replace(IR, raw_id, 1) if edit is None else edit(raw, raw_id), encoding='utf-8')
        listed = [d['id'] for row in json.loads(world.receipts.read_bytes())['issuers']['ZQA'] for d in row['later_documents']]
        first = world.run(1)[1]
        second = world.run(2)[1]
        gen = world.pg() if world.pointer() else {}
        return {
            'expected_ids': sorted(overlay.safe_document_id(i) for i in listed),
            'summary': first['issuers']['ZQA'], 'second': second['issuers']['ZQA'], 'calls': len(world.calls),
            'pointer': world.pointer(), 'files': (len(world.files('generations')), len(world.files('captures'))),
            'issuers': gen.get('issuers'), 'detections': gen.get('detections'),
            'state_secret_free': secret_free(state_bytes(world)), 'run_secret_free': secret_free(json.dumps([first, second]).encode()),
        }


class ReceiptStatus(unittest.TestCase):
    def status(self, rc, *args):
        return guidance.recompute_receipt_status(rc, *args, expected_wire_symbol='ZQA')

    def test_baseline_valid_receipt_unchanged(self):
        self.assertEqual(self.status(classic_receipt([], 'OK')), 'OK')
        self.assertEqual(self.status(classic_receipt([doc('https://www.nasdaq.com/press-release/a-b', 'POSSIBLY_RELEVANT')], 'REVIEW_REQUIRED')),
                         'REVIEW_REQUIRED')
        self.assertEqual(self.status(classic_receipt([doc('0001234567-26-000001', 'RESULTS_RELEASE', 'SEC_SUBMISSIONS')], 'RESULTS_PUBLISHED')),
                         'RESULTS_PUBLISHED')

    def test_unsafe_id_recomputes_to_unverified_for_every_disposition(self):
        for bad in UNSAFE_IDS:
            for disposition in ('IRRELEVANT', 'POSSIBLY_RELEVANT', 'RESULTS_RELEASE'):
                with self.subTest(id=bad, disposition=disposition):
                    self.assertEqual(self.status(classic_receipt([doc(bad, disposition)], 'FRESHNESS_UNVERIFIED')), 'FRESHNESS_UNVERIFIED')

    def test_reviewed_irrelevant_cannot_launder_an_unsafe_id(self):
        reviewed = [{'id': UNSAFE_IDS[0], 'disposition': 'REVIEWED_IRRELEVANT', 'reviewed_at': '2026-03-01T00:00:00Z'}]
        self.assertEqual(self.status(classic_receipt([doc(UNSAFE_IDS[0], 'REVIEWED_IRRELEVANT')], 'OK'), reviewed), 'FRESHNESS_UNVERIFIED')

    def test_validate_receipt_never_admits_an_unsafe_receipt(self):
        moment = guidance.parse_instant(CUTOFF)
        for bad in UNSAFE_IDS:
            for claimed in ('OK', 'REVIEW_REQUIRED', 'RESULTS_PUBLISHED', 'FRESHNESS_UNVERIFIED'):
                with self.subTest(id=bad, claimed=claimed):
                    rc = classic_receipt([doc(bad, 'POSSIBLY_RELEVANT')], claimed)
                    valid, status, error = guidance.validate_receipt(rc, 'ZQA', '2025-12-31', 'DOC-1', moment,
                                                                     guidance_published_date='2026-02-01', expected_wire_symbol='ZQA')
                    self.assertFalse(valid)
                    self.assertEqual(status, 'INVALID' if claimed != 'FRESHNESS_UNVERIFIED' else 'FRESHNESS_UNVERIFIED')
                    self.assertNotIn(error, ('RESULTS_PUBLISHED', 'REVIEW_REQUIRED'))  # the terminal statuses stay unreachable

    def test_predicate(self):
        for ok in (None, [], [doc('0001234567-26-000001')], [doc('https://www.nasdaq.com/press-release/a-b')],
                   [doc(overlay.safe_document_id(i)) for i in UNSAFE_IDS], [doc('x#sha256:' + 'f' * 64)]):
            self.assertFalse(guidance.receipt_has_unsafe_document_id({'later_documents': ok}), ok)
        for bad in ('x', {}, [1], [{'id': None}], [{'id': 7}], [{}], [doc('a#b')], [doc('a?b')], [doc('a@b')],
                    *([doc(n)] for n in NEAR_MISSES), [doc(overlay.safe_document_id(UNSAFE_IDS[0])), doc(UNSAFE_IDS[1])]):
            self.assertTrue(guidance.receipt_has_unsafe_document_id({'later_documents': bad}), bad)
        self.assertTrue(guidance.receipt_has_unsafe_document_id('not a mapping'))

    def test_persisted_form_recomputes_like_a_clean_id(self):
        # BATCH10C F8-AMEND1: the persisted form is a safe id for every disposition; every near miss stays unsafe.
        for bad in UNSAFE_IDS:
            safe = overlay.safe_document_id(bad)
            for disposition, status in (('IRRELEVANT', 'OK'), ('POSSIBLY_RELEVANT', 'REVIEW_REQUIRED'), ('RESULTS_RELEASE', 'RESULTS_PUBLISHED')):
                with self.subTest(id=safe, disposition=disposition):
                    self.assertEqual(self.status(classic_receipt([doc(safe, disposition)], status)), status)
        for near in NEAR_MISSES:
            with self.subTest(id=near):
                self.assertEqual(self.status(classic_receipt([doc(near)], 'OK')), 'FRESHNESS_UNVERIFIED')

    def test_a_review_of_the_raw_id_links_its_persisted_form(self):
        # The release checker writes and matches ids in the persisted form; the recompute links a raw review to it.
        reviewed = [{'id': UNSAFE_IDS[1], 'disposition': 'REVIEWED_IRRELEVANT', 'reviewed_at': '2026-03-01T00:00:00Z'}]
        safe = overlay.safe_document_id(UNSAFE_IDS[1])
        self.assertEqual(self.status(classic_receipt([doc(safe, 'REVIEWED_IRRELEVANT')], 'OK'), reviewed), 'OK')
        self.assertEqual(self.status(classic_receipt([doc(safe, 'POSSIBLY_RELEVANT')], 'OK'), reviewed), 'OK')
        self.assertEqual(self.status(classic_receipt([doc(safe, 'REVIEWED_IRRELEVANT')], 'OK')), 'FRESHNESS_UNVERIFIED')
        other = [dict(reviewed[0], id=UNSAFE_IDS[2])]
        self.assertEqual(self.status(classic_receipt([doc(safe, 'REVIEWED_IRRELEVANT')], 'OK'), other), 'FRESHNESS_UNVERIFIED')

    def test_validate_receipt_admits_a_persisted_form_receipt(self):
        moment = guidance.parse_instant(CUTOFF)
        for i in ('0001234567-26-000001',) + tuple(overlay.safe_document_id(u) for u in UNSAFE_IDS):
            with self.subTest(id=i):
                self.assertEqual(guidance.validate_receipt(classic_receipt([doc(i)], 'OK'), 'ZQA', '2025-12-31', 'DOC-1', moment,
                                                           guidance_published_date='2026-02-01', expected_wire_symbol='ZQA'),
                                 (True, 'OK', None))


class OverlayAdmission(unittest.TestCase):
    def admission(self, rows, reference=None):
        with W(1, 0) as world:
            record = world.records['ZQA']
            ref = guidance.guidance_reference(record)['document_id']
            for r in rows:
                r.setdefault('guidance_document_id', reference or ref)
            receipts = {'schema': guidance.RELEASE_CHECKS_SCHEMA, 'issuers': {'ZQA': rows}}
            return overlay.receipt_admission(receipts, 'ZQA', record, CUTOFF), overlay.receipt_gate(receipts, 'ZQA', record, CUTOFF)

    def test_unsafe_row_bars_the_record_whether_newest_or_older(self):
        for bad in UNSAFE_IDS:
            with self.subTest(id=bad):
                older = {'checked_at': '2026-03-01T11:00:00Z', 'later_documents': [doc(bad, 'RESULTS_RELEASE')]}
                newest = {'checked_at': '2026-03-02T11:00:00Z', 'later_documents': []}
                for rows in ([older, newest], [newest, older], [older]):
                    admission, gate = self.admission([dict(r) for r in rows])
                    self.assertEqual((admission['decision'], gate), ('RECEIPT_DOCUMENT_ID_UNSAFE',) * 2)
                    self.assertEqual(admission['unaccounted'], [])
                    self.assertFalse(admission['valid'])
                    self.assertTrue(secret_free(json.dumps(admission).encode()))

    def test_safe_rows_are_not_flagged(self):
        admission, gate = self.admission([{'checked_at': '2026-03-02T11:00:00Z', 'later_documents': [doc('0001234567-26-000001')]}])
        self.assertNotEqual(gate, 'RECEIPT_DOCUMENT_ID_UNSAFE')
        self.assertIsNotNone(gate)  # the synthetic row carries no digest: still not admitted, for its own reason

    def test_persisted_form_rows_are_not_barred_but_a_raw_row_beside_them_is(self):
        for bad in UNSAFE_IDS:
            with self.subTest(id=bad):
                rows = [{'checked_at': '2026-03-01T11:00:00Z', 'later_documents': [doc(overlay.safe_document_id(bad), 'RESULTS_RELEASE')]},
                        {'checked_at': '2026-03-02T11:00:00Z', 'later_documents': [doc(overlay.safe_document_id(bad))]}]
                admission, gate = self.admission([dict(r) for r in rows])
                self.assertNotEqual(gate, 'RECEIPT_DOCUMENT_ID_UNSAFE')
                self.assertIsNotNone(gate)  # the synthetic rows carry no digest
                self.assertTrue(secret_free(json.dumps(admission).encode()))
                legacy = {'checked_at': '2026-03-01T12:00:00Z', 'later_documents': [doc(bad)]}
                admission, gate = self.admission([dict(r) for r in rows + [legacy]])
                self.assertEqual((admission['decision'], gate), ('RECEIPT_DOCUMENT_ID_UNSAFE',) * 2)

    def test_unsafe_row_of_another_reference_is_not_this_records_row(self):
        admission, gate = self.admission([{'checked_at': '2026-03-02T11:00:00Z', 'later_documents': [doc(UNSAFE_IDS[0])]}], reference='OTHER')
        self.assertEqual(gate, 'RECEIPT_MISSING')


class MachineAttachment(unittest.TestCase):
    """A real AUTO_VERIFIED NVDA replay whose retained receipt history is then tainted: the public machine attachment
    (what the Worker receives) must carry no row of it, and the issuer must be SUSPENDED, never admitted."""

    def produce(self, taint=None):
        with tempfile.TemporaryDirectory() as tmp:
            return auto_parity.produce(Path(tmp), taint)

    def nvda(self, result):
        return next(r for r in json.loads(result['report'])['top'] if r['symbol'] == 'NVDA')['outlook']['order_forecast_v3']

    def test_control_clean_history_is_attached_and_admitted(self):
        env = self.nvda(self.produce())
        self.assertEqual(env['payload']['evidence']['auto_update']['disposition'], 'AUTO_VERIFIED')
        self.assertTrue(env['machine']['receipt_history'])

    def test_tainted_history_is_suspended_and_never_attached(self):
        def taint(chain):
            data = json.loads(chain.receipts.read_text(encoding='utf-8'))
            rows = data['issuers']['NVDA']
            newest = max(rows, key=lambda r: r['checked_at'])
            older = json.loads(json.dumps(newest))  # an OLDER retained row of the same reference carries the id; the newest stays clean
            older['checked_at'] = '2026-02-26T12:00:00Z'
            older['later_documents'].append(doc('https://zqauser:S3CRETPW@www.nasdaq.com/press-release/x?t=T0KEN#FR4G'))
            rows.append(older)
            chain.receipts.write_text(json.dumps(data), encoding='utf-8')
        result = self.produce(taint)
        env = self.nvda(result)
        auto = env['payload']['evidence']['auto_update']
        self.assertEqual((auto['disposition'], auto['reason']), ('SUSPENDED', 'RECEIPT_DOCUMENT_ID_UNSAFE'))
        self.assertNotEqual(env['payload']['revenue_status'], 'AVAILABLE')
        self.assertEqual(env['machine']['receipt_history'], [])
        self.assertEqual(auto['receipt']['rows'], [])
        self.assertIsNone(env['machine']['record_canonical_json'])
        self.assertTrue(secret_free((result['report'] + result['binding']).encode()))


class UpdaterNeverPersists(unittest.TestCase):
    def setUp(self):
        stack = self.enterContext(ExitStack())
        stack.enter_context(mock.patch.object(socket, 'create_connection', side_effect=AssertionError('NO_NETWORK')))
        stack.enter_context(mock.patch.object(socket, 'getaddrinfo', side_effect=AssertionError('NO_NETWORK')))

    def test_control_safe_receipt_still_plans_and_fetches(self):
        actual = f.outcome_of(lambda: run_world(None))
        self.assertEqual(actual[0], 'RESULT', actual)
        self.assertGreater(actual[1]['calls'], 0)
        self.assertIsNotNone(actual[1]['pointer'])

    def test_unsafe_ir_id_is_never_planned_fetched_or_persisted(self):
        for bad in UNSAFE_IDS:
            with self.subTest(id=bad):
                actual = f.outcome_of(lambda: run_world(bad))
                self.assertEqual(actual[0], 'RESULT', actual)
                r = actual[1]
                self.assertEqual(r['summary'], {'action': 'WAITING', 'reason': 'RECEIPT_DOCUMENT_ID_UNSAFE'})
                self.assertEqual(r['second'], r['summary'])
                # nothing fetched or attempted; one generation (the second run adds none) records the material documents
                self.assertEqual((r['calls'], r['files'], r['issuers']), (0, (1, 0), {}))
                ids = sorted(d['id'] for d in r['detections']['ZQA']['documents'])
                self.assertEqual(ids, r['expected_ids'])  # every listed document, the tainted one in its persisted form
                self.assertEqual([i for i in ids if '#sha256:' in i], [i for i in r['expected_ids'] if guidance.unsafe_document_id(i)])
                self.assertEqual((r['state_secret_free'], r['run_secret_free']), (True, True))

    def test_unsafe_id_in_another_channel_also_stops_the_issuer(self):
        def swap_sec(raw, bad):
            data = json.loads(raw)
            data['issuers']['ZQA'][0]['later_documents'][0]['id'] = bad
            return json.dumps(data)
        actual = f.outcome_of(lambda: run_world('https://zqauser:S3CRETPW@www.sec.gov/x', swap_sec))
        self.assertEqual(actual[0], 'RESULT', actual)
        self.assertEqual((actual[1]['summary']['reason'], actual[1]['calls'], actual[1]['issuers']), ('RECEIPT_DOCUMENT_ID_UNSAFE', 0, {}))
        self.assertEqual((actual[1]['state_secret_free'], actual[1]['run_secret_free']), (True, True))

    def test_persisted_form_receipt_id_is_not_a_barrier(self):
        # BATCH10C F8-AMEND1: the IR item listed in the persisted form (as the release checker writes it) is a safe id,
        # so the issuer is planned instead of stopped (its lead carries the persisted form, which url_rule refuses).
        def persist_ir(raw, _):
            data = json.loads(raw)
            for d in data['issuers']['ZQA'][0]['later_documents']:
                if d['channel'] == 'ISSUER_IR':
                    d['id'] = overlay.safe_document_id(d['id'] + '?t=T0KEN')
            return json.dumps(data)
        actual = f.outcome_of(lambda: run_world('', persist_ir))
        self.assertEqual(actual[0], 'RESULT', actual)
        r = actual[1]
        self.assertNotIn('RECEIPT_DOCUMENT_ID_UNSAFE', (r['summary'].get('reason'), r['second'].get('reason')), r)
        self.assertNotEqual(r['summary'].get('action'), 'WAITING', r)
        self.assertEqual((r['state_secret_free'], r['run_secret_free']), (True, True))


class PersistedForm(unittest.TestCase):
    """BATCH10C F8: the persisted form of an unsafe id keeps every document accounted and distinct, and carries no secret."""
    safe = staticmethod(overlay.safe_document_id)
    D = '2026-02-15'

    def test_clean_ids_and_non_strings_are_unchanged(self):
        for value in ('0001045810-26-000073', 'https://www.sec.gov/Archives/edgar/data/1045810/000104581026000073/a.htm',
                      'https://www.nasdaq.com/press-release/x', IR, '', 7, None):
            with self.subTest(value=value):
                self.assertIs(self.safe(value), value)

    def test_unsafe_ids_are_digested_distinct_idempotent_and_secret_free(self):
        values = UNSAFE_IDS + ('zqauser:S3CRETPW@ir.zqa.synthetic-g9.example/', 'https:zqauser:S3CRETPW@host', 'user:S3CRETPW@host?x#y',
                               'https://ir.x.example/a?t=T0KEN', 'https://ir.x.example/a?t=T0KEN2', 'https://h/a@b', 'https://h/p?',
                               'https://ir.x.example/' + 'a' * 600 + '?t=1')
        out = [self.safe(v) for v in values]
        self.assertEqual(len(set(out)), len(values))
        for value, safe in zip(values, out):
            with self.subTest(value=value):
                self.assertEqual(safe.rsplit('#sha256:', 1)[1], hashlib.sha256(value.encode()).hexdigest())
                self.assertTrue(secret_free(safe.encode()) and not any(c in safe.rpartition('#')[0] for c in '?@#'), safe)
                self.assertLessEqual(len(safe), 400)
                self.assertIs(self.safe(safe), safe)
                self.assertEqual(guidance.persisted_document_id(value), safe)
                self.assertTrue(guidance.raw_unsafe_document_id(value))
                # textually unsafe (it carries '#'), yet the persisted form: a safe id that never bars (F8-AMEND1)
                self.assertTrue(guidance.unsafe_document_id(safe))
                self.assertFalse(guidance.raw_unsafe_document_id(safe))
        self.assertEqual(f.outcome_of(lambda: updater.url_rule(out[0], NV))[:2], ('RAISED', 'NetworkBlocked'))

    def test_accounting_is_kept_and_compared_in_the_persisted_form(self):
        a, b = UNSAFE_IDS[3], UNSAFE_IDS[3].replace('T0KEN', 'T0KEN2')
        docs = [doc(a, 'RESULTS_RELEASE', 'ISSUER_IR'), doc(b, 'POSSIBLY_RELEVANT', 'ISSUER_IR'), doc(a, 'RESULTS_RELEASE', 'ISSUER_IR')]
        material = overlay._material_documents([{'later_documents': docs}])
        self.assertEqual([(m['disposition'], secret_free(m['id'].encode())) for m in material], [('RESULTS_RELEASE', True), ('POSSIBLY_RELEVANT', True)])
        self.assertEqual([m['disposition'] for m in overlay.unaccounted({}, [{'later_documents': docs}], None, [])], ['RESULTS_RELEASE', 'POSSIBLY_RELEVANT'])
        # a stored (persisted-form) detection and the raw receipt row are one document, not two
        self.assertEqual(len(overlay.unaccounted({}, [{'later_documents': docs[:1]}], None, material[:1])), 1)
        # a human review of the raw id accounts the document; a different raw id does not; a consumed raw id accounts it
        reviewed = {'reviewed_later_documents': [{'id': b, 'disposition': 'REVIEWED_IRRELEVANT'}]}
        self.assertEqual([m['disposition'] for m in overlay.unaccounted(reviewed, [{'later_documents': docs}], None, [])], ['RESULTS_RELEASE'])
        producer = {'decisions': [{'kind': 'ROUTING', 'operands': {'consumed': [{'channel': 'ISSUER_IR', 'date': self.D, 'id': a}]}}]}
        self.assertEqual([m['disposition'] for m in overlay.unaccounted({}, [{'later_documents': docs}], producer, [])], ['POSSIBLY_RELEVANT'])
        self.assertIn(('ISSUER_IR', self.safe(a), self.D), overlay.consumed_identities(producer))

    def test_leads_carry_the_persisted_form(self):
        title = 'NVIDIA Announces Financial Results for First Quarter Fiscal 2027'
        documents = [{'channel': 'SEC_SUBMISSIONS', 'date': self.D, 'id': '0001045810-26-000073', 'label': '8-K items 2.02,9.01', 'disposition': 'RESULTS_RELEASE'},
                     {'channel': 'ISSUER_IR', 'date': self.D, 'id': UNSAFE_IDS[3], 'label': title, 'disposition': 'IRRELEVANT'}]
        events = updater.candidate_events(documents, None, NV)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]['ir_item']['id'], self.safe(UNSAFE_IDS[3]))
        self.assertTrue(secret_free(json.dumps(events).encode()))


class RotationKeepsAccounting(unittest.TestCase):
    """The real NVDA replay chain: a tainted RESULTS_RELEASE listed only in an OLDER retained row is recorded in its
    persisted form, the issuer is barred, and when that row ages out of the history (release_check KEEP) the document
    still bars admission (base recorded it verbatim; a design that records nothing would admit the issuer here)."""

    def test_material_document_of_a_tainted_row_survives_rotation(self):
        bad = 'https://zqauser:S3CRETPW@www.nasdaq.com/press-release/x?t=T0KEN#FR4G'
        with tempfile.TemporaryDirectory() as tmp:
            chain = replay.Chain(Path(tmp))
            sequence = itertools.count(1)
            with mock.patch.object(updater.secrets, 'token_hex', side_effect=lambda n: f'{next(sequence):0{2 * n}x}'):
                for instant in ('2025-12-17T23:00:00Z', '2025-12-19T12:00:00Z', '2026-02-26T12:00:00Z'):
                    chain.check(instant)
                    updater.run(chain.state, Ordinary(instant[:10]), replay.at(instant), replay.PROFILES, chain.registry, chain.approval, chain.receipts)
                chain.check('2026-02-27T12:00:00Z')
                data = json.loads(chain.receipts.read_text(encoding='utf-8'))
                rows = data['issuers']['NVDA']
                older = json.loads(json.dumps(max(rows, key=lambda r: r['checked_at'])))
                older['checked_at'] = '2026-02-26T13:00:00Z'
                older['later_documents'].append({'channel': 'WIRE_PRESS_RELEASES', 'date': '2026-02-26', 'id': bad, 'label': 'Other release', 'disposition': 'RESULTS_RELEASE'})
                rows.append(older)
                chain.receipts.write_text(json.dumps(data), encoding='utf-8')
                result = updater.run(chain.state, Ordinary('2026-02-27'), replay.at('2026-02-27T12:30:00Z'), replay.PROFILES, chain.registry, chain.approval, chain.receipts)
                self.assertEqual(result['issuers']['NVDA'], {'action': 'WAITING', 'reason': 'RECEIPT_DOCUMENT_ID_UNSAFE'})
                self.assertTrue(secret_free(state_bytes_of(chain.state)))
                before = chain.snapshot('2026-02-27T13:00:00Z').issuer('NVDA')
                self.assertEqual((before.disposition, before.reason), ('SUSPENDED', 'RECEIPT_DOCUMENT_ID_UNSAFE'))
                self.assertEqual([d['id'] for d in before.detections], [overlay.safe_document_id(bad)])
                data['issuers']['NVDA'] = [r for r in rows if r['checked_at'] != '2026-02-26T13:00:00Z']  # the row ages out
                chain.receipts.write_text(json.dumps(data), encoding='utf-8')
                after = chain.snapshot('2026-02-27T13:00:00Z').issuer('NVDA')
                self.assertEqual((after.disposition, after.reason, after.usable_record), ('SUSPENDED', 'RECEIPT_RESULTS_PUBLISHED', None))
                self.assertEqual([d['id'] for d in after.receipt_admission['unaccounted']], [overlay.safe_document_id(bad)])


class PhaseOneRecordsBeforeTheBarrier(unittest.TestCase):
    """Mutant M2 (the phase-1 barrier moved before the detection write): a world in which phase 0 does not record the
    effective reference's rows. Phase 0 reads the loader's discovery view, phase 1 the record admitted after any
    re-verification, so their references need not agree; here the real entry view is used except that its discovery
    reference names a document no retained row lists. Only phase 1 sees the tainted row, and it must record every
    material document of it, in the persisted form, before it stops the issuer."""

    def test_phase_one_records_a_barred_receipts_documents_that_phase_zero_did_not(self):
        self.assertIs(updater.overlay, overlay)  # the patch below reaches the updater's only entry-view call
        real, substituted = overlay.load_effective_inputs, []

        class OtherDiscoveryReference:
            def __init__(self, view):
                self.view = view

            def __getattr__(self, name):
                return getattr(self.view, name)

            def issuer(self, symbol):
                item = self.view.issuer(symbol)
                if item is None or item.discovery_reference is None:
                    return item
                substituted.append(symbol)
                return dataclasses.replace(item, discovery_reference=dict(item.discovery_reference, document_id='ZQA-NO-RETAINED-ROW'))

        serial = itertools.count(1)
        with ExitStack() as stack:
            stack.enter_context(mock.patch.object(updater.secrets, 'token_hex', side_effect=lambda n: f'{next(serial):0{2*n}x}'))
            stack.enter_context(mock.patch.object(overlay, 'load_effective_inputs', lambda **kw: OtherDiscoveryReference(real(**kw))))
            world = stack.enter_context(W(1, 0))
            raw = world.receipts.read_text(encoding='utf-8')
            world.receipts.write_text(raw.replace(IR, UNSAFE_IDS[3], 1), encoding='utf-8')
            listed = [d['id'] for row in json.loads(world.receipts.read_bytes())['issuers']['ZQA'] for d in row['later_documents']]
            self.assertEqual(sum(guidance.unsafe_document_id(i) for i in listed), 1)
            first = world.run(1)
            calls = [len(world.calls)]
            second = world.run(2)
            calls.append(len(world.calls))
            self.assertEqual((first[0], second[0]), ('RESULT', 'RESULT'), (first, second))
            self.assertIn('ZQA', substituted)  # phase 0 read the substituted reference: it had no row to record
            for outcome in (first, second):
                self.assertEqual(outcome[1]['issuers']['ZQA'], {'action': 'WAITING', 'reason': 'RECEIPT_DOCUMENT_ID_UNSAFE'})
            self.assertEqual(calls, [0, 0])  # nothing fetched in either run
            # phase 1 alone recorded the documents: one generation (the second run adds none), no attempt, no capture
            self.assertIsNotNone(world.pointer())
            self.assertEqual((len(world.files('generations')), len(world.files('captures'))), (1, 0))
            gen = world.pg()
            self.assertEqual(gen['issuers'], {})
            self.assertEqual(sorted(d['id'] for d in gen['detections']['ZQA']['documents']),
                             sorted(overlay.safe_document_id(i) for i in listed))
            self.assertTrue(secret_free(state_bytes(world)))


BARRED = {'action': 'WAITING', 'reason': 'RECEIPT_DOCUMENT_ID_UNSAFE'}


def verified(accession):
    return {'action': 'ATTEMPTED', 'event': accession, 'outcome': 'VERIFIED', 'reason': None}


def listing_link_with(suffix, raws):
    """The replay wire feed as probe_f3 serves it: every read lists NVDA's 2026-02-25 results release with `suffix` on
    its link (the feed keeps listing it); `raws` collects the listed originals, as the checker forms them."""
    original = replay.wire_fetch_as_of

    def as_of(day):
        inner = original(day)

        def fetch(url):
            data = inner(url)
            for row in data['data']['rows']:
                if row.get('created') == 'Feb 25, 2026' and 'financial-results' in str(row.get('url', '')):
                    row['url'] = row['url'] + suffix
                    if 'https://www.nasdaq.com' + row['url'] not in raws:
                        raws.append('https://www.nasdaq.com' + row['url'])
            return data
        return fetch
    return mock.patch.object(replay, 'wire_fetch_as_of', as_of)


def nvda_rows(chain):
    return json.loads(chain.receipts.read_text(encoding='utf-8'))['issuers']['NVDA']


class SteadyStateFeed(unittest.TestCase):
    """BATCH10C F8-AMEND1 (end-phase run 1, probe_f3): the real NVDA replay chain while the wire feed keeps listing the
    2026-02-25 results release with a query (or a fragment) on its link. The canonicalising checker writes that link in
    the persisted form in every row, which never bars: the quarterly verifications 000019, 000051 and 000073 go on as
    with a clean link. (The wire copy of a lead in the persisted form is dropped, URL_SHAPE, so the runs between the
    releases may wait for EVENT_UNRESOLVED, as the clean-link base does; that wait settles at the next release.)"""
    INSTANTS = ('2026-02-26T12:00:00Z', '2026-02-26T13:00:00Z', '2026-05-21T12:00:00Z', '2026-05-21T13:00:00Z',
                '2026-08-27T12:00:00Z', '2026-08-27T13:00:00Z')
    EXPECTED = {'2026-02-26T12:00:00Z': verified('0001045810-26-000019'), '2026-05-21T12:00:00Z': verified('0001045810-26-000051'),
                '2026-08-27T12:00:00Z': verified('0001045810-26-000073')}

    def run_chain(self, suffix, instants):
        raws, summaries, listed = [], {}, set()
        with tempfile.TemporaryDirectory() as tmp, listing_link_with(suffix, raws):
            chain = replay.Chain(Path(tmp))
            sequence = itertools.count(1)
            with mock.patch.object(updater.secrets, 'token_hex', side_effect=lambda n: f'{next(sequence):0{2 * n}x}'):
                for instant in instants:
                    chain.check(instant)
                    rows = nvda_rows(chain)
                    self.assertFalse(any(guidance.receipt_has_unsafe_document_id(r) for r in rows), instant)
                    listed |= {d['id'] for r in rows for d in r['later_documents']}
                    text = chain.receipts.read_text(encoding='utf-8')
                    self.assertFalse(any(raw in text for raw in raws), instant)
                    summaries[instant] = chain.update(instant)['issuers']['NVDA']
                    gated = chain.resolve(instant, receipts=True)['NVDA']
                    self.assertNotEqual(gated['reason'], 'RECEIPT_DOCUMENT_ID_UNSAFE', instant)
        self.assertTrue(raws)
        self.assertTrue({overlay.safe_document_id(raw) for raw in raws} <= listed)  # every row lists the persisted form
        self.assertFalse(any(guidance.raw_unsafe_document_id(i) for i in listed))
        for instant, summary in summaries.items():
            self.assertNotEqual(summary, BARRED, instant)
            if instant in self.EXPECTED:
                self.assertEqual(summary, self.EXPECTED[instant], instant)
        return summaries

    def test_a_feed_that_keeps_listing_a_query_link_never_bars(self):
        self.run_chain(QUERY, self.INSTANTS)

    def test_a_feed_that_keeps_listing_a_fragment_link_never_bars(self):
        self.run_chain('#feed', self.INSTANTS[:1])


class LegacyRawRowBound(unittest.TestCase):
    """BATCH10C F8-AMEND1: a receipt the checker wrote before F8-N1 lists the same link raw. Retained as the newest row,
    it bars the issuer exactly until KEEP (8) newer checks of the canonicalising checker have pushed it out of the
    retained history: the eighth check drops it, and the run after that check is the first one not barred."""

    def test_a_legacy_raw_row_bars_for_at_most_keep_new_checks(self):
        self.assertEqual(replay.checker.KEEP, 8)
        raws, runs = [], []
        with tempfile.TemporaryDirectory() as tmp, listing_link_with(QUERY, raws):
            chain = replay.Chain(Path(tmp))
            sequence = itertools.count(1)
            with mock.patch.object(updater.secrets, 'token_hex', side_effect=lambda n: f'{next(sequence):0{2 * n}x}'):
                chain.check('2026-02-26T11:00:00Z')
                data = json.loads(chain.receipts.read_text(encoding='utf-8'))
                legacy = json.loads(json.dumps(data['issuers']['NVDA'][-1]))
                swapped = [d for d in legacy['later_documents'] if d['id'] == overlay.safe_document_id(raws[0])]
                self.assertEqual(len(swapped), 1)
                swapped[0]['id'] = raws[0]  # what the checker wrote before F8-N1
                legacy['checked_at'] = '2026-02-26T11:30:00Z'
                legacy['digest'] = guidance.compute_receipt_digest(legacy)
                self.assertTrue(guidance.receipt_has_unsafe_document_id(legacy))
                data['issuers']['NVDA'].append(legacy)
                chain.receipts.write_text(json.dumps(data), encoding='utf-8')
                for k in range(1, replay.checker.KEEP + 1):
                    instant = f'2026-02-26T{11 + k}:00:00Z'
                    chain.check(instant)
                    retained = '2026-02-26T11:30:00Z' in [r['checked_at'] for r in nvda_rows(chain)]
                    summary = chain.update(instant)['issuers']['NVDA']
                    runs.append((k, retained, summary, chain.resolve(instant, receipts=True)['NVDA']['reason']))
                self.assertNotIn(raws[0].encode('utf-8'), state_bytes_of(chain.state))  # recorded in the persisted form only
        self.assertEqual([(k, retained) for k, retained, _, _ in runs], [(k, k < 8) for k in range(1, 9)])
        self.assertEqual([summary for _, _, summary, _ in runs[:7]], [BARRED] * 7)
        self.assertEqual([reason for _, _, _, reason in runs[:7]], ['RECEIPT_DOCUMENT_ID_UNSAFE'] * 7)
        # the eighth canonical check dropped the legacy row: the barrier lifts in that very run
        self.assertEqual(runs[7][2], verified('0001045810-26-000019'))
        self.assertNotEqual(runs[7][3], 'RECEIPT_DOCUMENT_ID_UNSAFE')


class Ordinary:
    """A synthetic ordinary transport over the replay fixtures (as test_revenue_guidance_machine_auto_parity.produce)."""

    def __init__(self, day):
        self.day = day

    def get(self, url, profile, symbol):
        return replay.ReplayAsOf(self.day).get(url, profile, symbol)


def state_bytes_of(state):
    return b''.join(p.read_bytes() for p in sorted(state.rglob('*')) if p.is_file())


if __name__ == '__main__':
    unittest.main()
