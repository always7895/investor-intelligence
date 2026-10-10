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
    (DOC + '?t=T0KEN', 'URL_SHAPE ' + DOC),
    (DOC + '#FR4G', 'URL_SHAPE ' + DOC),
    ('http://zqauser:S3CRETPW@www.sec.gov' + PX + '?t=T0KEN#FR4G', 'URL_SHAPE http://www.sec.gov' + PX),
    ('https://zqauser:S3CRETPW@www.sec.gov:8443' + PX, 'URL_SHAPE https://www.sec.gov:8443' + PX),
    ('https://www.sec.gov:8443' + PX, 'URL_SHAPE https://www.sec.gov:8443' + PX),
    (DOC.replace('https', 'http'), 'URL_SHAPE ' + DOC.replace('https', 'http')),
)


def secret_free(text):
    return not any(s in text for s in SECRETS)


def end_to_end():
    serial = itertools.count(1)
    with mock.patch.object(updater.secrets, 'token_hex', side_effect=lambda n: f'{next(serial):0{2*n}x}'), W(1, 0) as world:
        raw = world.receipts.read_text(encoding='utf-8')
        assert raw.count(IR) >= 1
        world.receipts.write_text(raw.replace(IR, IR_SECRET, 1), encoding='utf-8')
        first = world.run(1)
        last = world.last('ZQA')
        generations = [p.read_text(encoding='utf-8') for p in world.files('generations')]
        return {
            'outcome': (last['outcome'], last['reason']),
            'detail': last['detail'],
            'detail_secret_free': secret_free(last['detail']),
            'event_secret_free': secret_free(json.dumps(last['event'])),
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

    def test_end_to_end_waiting_detail_never_carries_userinfo_query_or_fragment(self):
        actual = f.outcome_of(end_to_end)
        self.assertEqual(actual[0], 'RESULT', actual)
        r = actual[1]
        self.assertEqual(r['outcome'], ('WAITING', 'NETWORK_UNAVAILABLE'))
        self.assertTrue(r['detail'].startswith('URL_SHAPE https://ir.zqa.synthetic-g9.example/'), r['detail'])
        for key in ('detail_secret_free', 'run_secret_free', 'summary_secret_free'):
            self.assertTrue(r[key], key)
        # Traced, NOT fixed (BATCH10C F8, a separate lane): the receipts-provided IR item id is persisted verbatim in the
        # attempt event and the generation files, so an id that itself carries userinfo stays there.
        self.assertEqual((r['event_secret_free'], r['generations_secret_free'], r['generations'] > 0), (False, False, True))


if __name__ == '__main__':
    unittest.main()
