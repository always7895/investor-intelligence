"""SYNTHETIC_G9_NOT_GENUINE: B10C-F1 URL_SHAPE refusals never echo userinfo, query or fragment.

Fake connector and clocks only; ZQA is synthetic, never issuer admission. No subprocess, no network.
"""
from __future__ import annotations

from contextlib import ExitStack
import itertools
import json
from pathlib import Path
import socket
import unittest
from unittest import mock

from tests import g9a_synthetic_issuers as h
from tests import nbis_synthetic_sources as f

updater = f.updater
W = h.World
ROOT = Path(__file__).resolve().parents[1]
NV = next(p for p in json.loads((ROOT / 'config/revenue-guidance-extraction-profiles-v1.json').read_bytes())['profiles'] if p['symbol'] == 'NVDA')
PX = '/Archives/edgar/data/1045810/000104581026000073/a.htm'
DOC = 'https://www.sec.gov' + PX
SECRETS = ('zqauser', 'S3CRETPW', 'T0KEN', 'FR4G')
IR = 'https://ir.zqa.synthetic-g9.example/'
IR_SECRET = 'https://zqauser:S3CRETPW@ir.zqa.synthetic-g9.example/?t=T0KEN#FR4G'
# (url, exact refusal text): the shown part is scheme://host[:port]/path only.
CASES = (
    ('https://zqauser:S3CRETPW@www.sec.gov' + PX, 'URL_SHAPE https://www.sec.gov' + PX),
    ('https://zqauser@www.sec.gov' + PX, 'URL_SHAPE https://www.sec.gov' + PX),
    ('https://zqauser:S3C@RETPW@www.sec.gov' + PX, 'URL_SHAPE https://www.sec.gov' + PX),
    # B10C-F1-NB1: an empty userinfo (falsy username and password) is refused too.
    ('https://:@www.sec.gov' + PX, 'URL_SHAPE https://www.sec.gov' + PX),
    ('https://@www.sec.gov' + PX, 'URL_SHAPE https://www.sec.gov' + PX),
    ('https://:@www.sec.gov:443' + PX, 'URL_SHAPE https://www.sec.gov:443' + PX),
    (DOC + '?t=T0KEN', 'URL_SHAPE ' + DOC),
    (DOC + '#FR4G', 'URL_SHAPE ' + DOC),
    ('http://zqauser:S3CRETPW@www.sec.gov' + PX + '?t=T0KEN#FR4G', 'URL_SHAPE http://www.sec.gov' + PX),
    ('https://zqauser:S3CRETPW@www.sec.gov:8443' + PX, 'URL_SHAPE https://www.sec.gov:8443' + PX),
    ('https://www.sec.gov:8443' + PX, 'URL_SHAPE https://www.sec.gov:8443' + PX),
    (DOC.replace('https', 'http'), 'URL_SHAPE ' + DOC.replace('https', 'http')),
)


def secret_free(text):
    return not any(s in text for s in SECRETS)


def end_to_end(ir_id=IR_SECRET):
    serial = itertools.count(1)
    with mock.patch.object(updater.secrets, 'token_hex', side_effect=lambda n: f'{next(serial):0{2*n}x}'), W(1, 0) as world:
        raw = world.receipts.read_text(encoding='utf-8')
        assert raw.count(IR) >= 1
        world.receipts.write_text(raw.replace(IR, ir_id, 1), encoding='utf-8')
        first = world.run(1)
        issuer = first[1]['issuers']['ZQA']
        events = [world.last('ZQA')] if world.pointer() is not None and 'ZQA' in world.pg()['issuers'] else []  # no attempt: no entry
        generations = [p.read_text(encoding='utf-8') for p in world.files('generations')]
        return {
            'issuer': issuer,
            'attempts': len(events),
            'detail': events[-1]['detail'] if events else None,
            'detail_secret_free': all(secret_free(e['detail']) for e in events),
            'event_secret_free': all(secret_free(json.dumps(e['event'])) for e in events),
            'run_secret_free': secret_free(json.dumps(first)),
            'summary_secret_free': secret_free(json.dumps(world.summary())),
            'generations': len(generations),
            'generations_secret_free': all(secret_free(text) for text in generations),
        }


class UrlShapeRedaction(unittest.TestCase):
    def setUp(self):
        stack = self.enterContext(ExitStack())
        stack.enter_context(mock.patch.object(socket, 'create_connection', side_effect=AssertionError('NO_NETWORK')))
        stack.enter_context(mock.patch.object(socket, 'getaddrinfo', side_effect=AssertionError('NO_NETWORK')))

    def test_refusal_text_shows_only_scheme_host_port_path(self):
        for url, text in CASES:
            with self.subTest(url=url):
                self.assertEqual(f.outcome_of(lambda: updater.url_rule(url, NV)), ('RAISED', 'NetworkBlocked', text))
                self.assertTrue(secret_free(text))

    def test_accepted_urls_unchanged(self):
        for url in (DOC, 'https://www.sec.gov:443' + PX, 'https://www.sec.gov:' + PX):
            with self.subTest(url=url):
                self.assertEqual(f.outcome_of(lambda: updater.url_rule(url, NV)), ('RESULT', 'document'))

    def test_detail_cap_unchanged(self):
        long_path = '/' + 'a' * 300
        outcome = f.outcome_of(lambda: updater.url_rule('http://zqauser:S3CRETPW@www.sec.gov' + long_path, NV))
        self.assertEqual(outcome, ('RAISED', 'NetworkBlocked', 'URL_SHAPE ' + ('http://www.sec.gov' + long_path)[:120]))

    def test_end_to_end_control_plain_ir_id_is_still_planned(self):
        # The same world with the unmodified (plain) IR id plans and attempts the event as before the F8 barrier.
        actual = f.outcome_of(lambda: end_to_end(IR))
        self.assertEqual(actual[0], 'RESULT', actual)
        r = actual[1]
        self.assertEqual((r['issuer']['action'], r['attempts'] > 0, r['generations'] > 0), ('ATTEMPTED', True, True), r)
        for key in ('detail_secret_free', 'event_secret_free', 'run_secret_free', 'summary_secret_free', 'generations_secret_free'):
            self.assertTrue(r[key], key)

    def test_end_to_end_secret_bearing_receipt_id_is_refused_before_anything_is_planned_or_persisted(self):
        # BATCH10C F8 fixed: a receipt listing a raw id with userinfo, query or fragment (as written before F8-N1; the
        # persisted form is not one, F8-AMEND1) is a barrier; the updater plans, fetches and attempts nothing for the
        # issuer (no attempt event); its material documents are recorded in the persisted form only
        # (tests/test_revenue_guidance_receipt_id_safety.py), so every generation file is secret-free.
        actual = f.outcome_of(end_to_end)
        self.assertEqual(actual[0], 'RESULT', actual)
        r = actual[1]
        self.assertEqual(r['issuer'], {'action': 'WAITING', 'reason': 'RECEIPT_DOCUMENT_ID_UNSAFE'})
        self.assertEqual((r['attempts'], r['generations']), (0, 1))  # the detections, in their persisted form; no attempt event
        for key in ('detail_secret_free', 'event_secret_free', 'run_secret_free', 'summary_secret_free', 'generations_secret_free'):
            self.assertTrue(r[key], key)


if __name__ == '__main__':
    unittest.main()
