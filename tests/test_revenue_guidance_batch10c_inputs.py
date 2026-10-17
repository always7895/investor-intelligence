"""SYNTHETIC_G9_NOT_GENUINE: BATCH10C typed URL and Retry-After boundaries.

Fake connector and clocks only; ZQA is synthetic, never issuer admission.
"""
from __future__ import annotations

from contextlib import ExitStack, redirect_stdout
from datetime import datetime
import io
import itertools
import json
from pathlib import Path
import socket
import sys
import tempfile
import types
import unittest
from unittest import mock

from tests import g9a_synthetic_issuers as h
from tests import nbis_synthetic_sources as f

updater, overlay = f.updater, f.overlay
W, At = h.World, h.at
ROOT = Path(__file__).resolve().parents[1]
NV = next(p for p in json.loads((ROOT / 'config/revenue-guidance-extraction-profiles-v1.json').read_bytes())['profiles'] if p['symbol'] == 'NVDA')
PX = '/Archives/edgar/data/1045810/000104581026000073/a.htm'
DOC = 'https://www.sec.gov' + PX
BODY = b'<html><body>SYNTHETIC_G9_NOT_GENUINE ZQA</body></html>'
OK_OUT = ('RESULT', (BODY, 'text/html'))
BL = ('RAISED', 'NetworkBlocked', 'URL_SHAPE')
TRANSIENT = ('RAISED', 'NetworkBlocked', 'TRANSIENT')
BAD = ('https://www.sec.gov:99999' + PX, 'https://www.sec.gov:abc' + PX,
       'https://www.sec.gov:-1' + PX, 'https://www.sec.gov:65536' + PX,
       'https://www.sec.gov:\uff14\uff14\uff13' + PX, 'https://[::1' + PX,
       'https://www.sec.gov]' + PX, 'https://user:pw@www.sec.gov:99999' + PX)
# Characterized at BASE; pinned at P1 after the hard class gate (BASE_DELTA).
A5_PIN = (('RESULT', {'status': 'OK', 'at': '2026-03-02T12:01:00Z', 'issuers': {'ZQA': {'action': 'ATTEMPTED', 'event': '0009100001-26-000001', 'outcome': 'WAITING', 'reason': 'NETWORK_UNAVAILABLE'}}, 'reverified': False, 'generation_id': '20260302T120100Z-000000000003'}), ('RESULT', ('ATTEMPTED', 'WAITING', 'NETWORK_UNAVAILABLE')), ('RESULT', ('WAITING', 'NETWORK_UNAVAILABLE', 'URL_SHAPE')), ('RESULT', ('SUB', 'INDEX', 'DOC')), ('RESULT', 3), ('RESULT', 3), ('RESULT', (('RESULT', 0), 3, True)))


class Response:
    def __init__(self, status=200, retry=None):
        self.status = status
        self.headers = {'content-type': 'text/html'}
        if retry is not None:
            self.headers['retry-after'] = retry
        self.body = BODY if status == 200 else b''

    def read(self, n):
        raw, self.body = self.body, b''
        return raw

    def close(self):
        pass


class Script:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls, self.resolutions, self.sleeps = [], [], []
        self.clock = [0.0]
        self.transport = updater.Transport({'User-Agent': 'B10C-SYNTHETIC'}, connector=self.connect,
                                           resolver=self.resolve, sleep=self.sleep, monotonic=lambda: self.clock[0])

    def connect(self, host, address, path, headers, timeout):
        self.calls.append((host, address, path, dict(headers), timeout))
        return self.responses.pop(0)

    def resolve(self, host):
        self.resolutions.append(host)
        return ['162.159.140.1']

    def sleep(self, value):
        self.sleeps.append(value)
        self.clock[0] += value


def retry_case(value, status=503, twice=False):
    with mock.patch.object(updater, 'PACING_SECONDS', 0):
        scripted = Script([Response(status, value)] * (2 if twice else 1) + [Response()])
        outcome = f.outcome_of(lambda: scripted.transport.get(DOC, NV, 'ZQA'))
        return outcome, len(scripted.calls), scripted.sleeps


def probe(url):
    try:
        value = updater.url_rule(url, NV)
    except BaseException as error:
        return (type(error).__name__, str(error), url not in str(error), 'pw' not in str(error),
                error.__cause__ is None, error.__suppress_context__ is True)
    return 'RESULT', value


def a3():
    scripted = Script([Response() for _ in range(len(BAD) + 1)])
    outcomes = tuple(f.outcome_of(lambda url=url: scripted.transport.get(url, NV, 'ZQA')) for url in BAD)
    before = (outcomes, len(scripted.calls), len(scripted.resolutions), list(scripted.sleeps), scripted.transport.requests)
    return before + (f.outcome_of(lambda: scripted.transport.get(DOC, NV, 'ZQA')),)


def a4():
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        (root / 'inventory.json').write_text('[]', encoding='utf-8')
        replay = updater.ReplayTransport(root)
        return (tuple(f.outcome_of(lambda url=url: replay.get(url, NV, 'ZQA')) for url in BAD),
                f.outcome_of(lambda: replay.get(DOC, NV, 'ZQA')))


def rewrite_receipts(world):
    raw = world.receipts.read_text(encoding='utf-8')
    world.receipts.write_text(raw.replace('https://ir.zqa.synthetic-g9.example/',
                                          'https://ir.zqa.synthetic-g9.example:99999/', 1), encoding='utf-8')


def main_transport(world):
    """Private copy of World.run's connector for the real main() entrypoint."""
    world.calls = []
    world.clock = h.FakeClock()

    def connector(host, address, path, headers, timeout):
        if host == 'data.sec.gov':
            i, kind = int(path.rsplit('CIK', 1)[1].split('.')[0]) - 9100001, 'SUB'
        elif host == 'www.sec.gov':
            i = int(path.split('/')[4]) - 9100001
            kind = 'INDEX' if path.endswith('/index.json') else 'DOC'
        else:
            i, kind = [h.host(sym) for sym in world.syms].index(host), 'IR'
        sym = world.syms[i]
        world.calls.append((world.clock(), sym, kind))
        raw, ctype = world.payload(i, kind, path.rsplit('/', 1)[-1])
        return h.Response(404 if kind == 'IR' else 200, raw, ctype)

    return updater.Transport({'User-Agent': 'B10C-SYNTHETIC'}, connector=connector,
                             resolver=lambda host: ['162.159.140.1'], sleep=world.clock.sleep, monotonic=world.clock)


class FixedDatetime(datetime):
    @classmethod
    def now(cls, tz=None):
        return At(1).astimezone(tz) if tz is not None else At(1).replace(tzinfo=None)


def a5():
    # Stable synthetic entropy makes the returned product generation IDs pinnable.
    serial = itertools.count(1)
    with mock.patch.object(updater.secrets, 'token_hex', side_effect=lambda n: f'{next(serial):0{2*n}x}'), W(1, 0) as world:
        rewrite_receipts(world)
        first = world.run(1)
        summary = f.outcome_of(lambda: tuple(world.summary()['issuers']['ZQA'].get(k) for k in ('action', 'outcome', 'reason')))
        last = f.outcome_of(lambda: tuple(world.last('ZQA')[k] for k in ('outcome', 'reason', 'detail')))
        kinds = f.outcome_of(lambda: tuple(kind for _, _, kind in world.calls))
        count1 = f.outcome_of(lambda: len(world.files('generations')))
        second = world.run(2)
        count2 = f.outcome_of(lambda: len(world.files('generations')))
        findings = f.outcome_of(lambda: {
            'bad_id_in_attempt_event': ':99999' in json.dumps(world.last('ZQA')['event']),
            'bad_id_generation_files': sum(':99999' in p.read_text(encoding='utf-8') for p in world.files('generations')),
            'run2': second,
        })
        f.observe_boundary('A5-F8', findings)
        with W(1, 0) as fresh:
            rewrite_receipts(fresh)
            transport = main_transport(fresh)
            fake_module = types.ModuleType('sec_contact_headers')
            fake_module.sec_identity_headers = lambda: {'User-Agent': 'B10C-SYNTHETIC'}
            output = io.StringIO()
            with mock.patch.object(overlay, 'SUPPORTED_AUTO', ('ZQA',)), \
                    mock.patch.object(updater, 'Transport', return_value=transport), \
                    mock.patch.object(updater, 'datetime', FixedDatetime), \
                    mock.patch.dict(sys.modules, {'sec_contact_headers': fake_module}), redirect_stdout(output):
                main_result = f.outcome_of(lambda: updater.main([
                    '--state-root', str(fresh.state), '--profiles', str(fresh.profiles),
                    '--registry', str(fresh.registry), '--approval', str(fresh.approval), '--receipts', str(fresh.receipts)]))
            main_tuple = f.outcome_of(lambda: (main_result, len(fresh.calls), ':99999' not in output.getvalue()))
            f.observe_boundary('A5-class-evidence', {
                'run1': first, 'run2': second, 'last': last, 'main': main_result,
                'main_calls': len(fresh.calls), 'stdout': output.getvalue(),
                'summary_no_bad_id': ':99999' not in json.dumps(first),
            })
        return first, summary, last, kinds, count1, count2, main_tuple


class Batch10CInputs(unittest.TestCase):
    def setUp(self):
        stack = self.enterContext(ExitStack())
        stack.enter_context(mock.patch.object(socket, 'create_connection', side_effect=AssertionError('NO_NETWORK')))
        stack.enter_context(mock.patch.object(socket, 'getaddrinfo', side_effect=AssertionError('NO_NETWORK')))

    def test_a1(self):
        actual = f.outcome_of(lambda: tuple(probe(url) for url in BAD))
        self.assertEqual(f.observe_boundary('A1', actual), ('RESULT', (('NetworkBlocked', 'URL_SHAPE', True, True, True, True),) * len(BAD)))

    def test_a2(self):
        actual = f.outcome_of(lambda: (
            f.outcome_of(lambda: updater.url_rule('https://www.sec.gov:8443' + PX, NV)),
            f.outcome_of(lambda: updater.url_rule('https://www.sec.gov:443' + PX, NV)),
            f.outcome_of(lambda: updater.url_rule(DOC.replace('https', 'http'), NV)),
            str(updater.NetworkBlocked('URL_SHAPE')).startswith(updater.RETRYABLE)))
        self.assertEqual(f.observe_boundary('A2', actual), ('RESULT', (
            ('RAISED', 'NetworkBlocked', 'URL_SHAPE https://www.sec.gov:8443' + PX),
            ('RESULT', 'document'), ('RAISED', 'NetworkBlocked', 'URL_SHAPE ' + DOC.replace('https', 'http')), False)))

    def test_a2b(self):
        # BATCH10C F4, accepted by design: an empty port ('https://host:/path') parses as port None, i.e. an omitted port (RFC 3986 section 3.2.3), so the https default 443.
        actual = f.outcome_of(lambda: f.outcome_of(lambda: updater.url_rule('https://www.sec.gov:' + PX, NV)))
        self.assertEqual(f.observe_boundary('A2b', actual), ('RESULT', ('RESULT', 'document')))

    def test_a3(self):
        actual = f.outcome_of(a3)
        self.assertEqual(f.observe_boundary('A3', actual), ('RESULT', ((BL,) * len(BAD), 0, 0, [], 0, OK_OUT)))

    def test_a4(self):
        actual = f.outcome_of(a4)
        self.assertEqual(f.observe_boundary('A4', actual), ('RESULT', ((BL,) * len(BAD), ('RAISED', 'NetworkBlocked', 'REPLAY_MISSING'))))

    def test_a5(self):
        actual = f.outcome_of(a5)
        self.assertEqual(f.observe_boundary('A5', actual), ('RESULT', A5_PIN))

    def test_b1(self):
        actual = f.outcome_of(lambda: tuple(retry_case(value) for value in ('\u00b2', '\u0663', '\uff11', '1' * 4301, '00005', '12345')))
        self.assertEqual(f.observe_boundary('B1', actual), ('RESULT', ((OK_OUT, 2, [2]),) * 3 + ((TRANSIENT, 1, []), (OK_OUT, 2, [5]), (TRANSIENT, 1, []))))

    def test_b2(self):
        values = ('0', '1', '5', '0005', '030', '30', '0030', '31', '600', '999', '1000', '9999', '1' * 4300,
                  '', '-1', '1e3', ' 5', '5 ', '5x', '5\n', '\n5', '+5', '5.0', '12345x', 'x12345', '123456\n', None)
        actual = f.outcome_of(lambda: tuple(retry_case(value) for value in values) + (retry_case('5', 429),))
        self.assertEqual(f.observe_boundary('B2', actual), ('RESULT',
            tuple((OK_OUT, 2, [delay]) for delay in (0, 1, 5, 5, 30, 30, 30)) +
            ((TRANSIENT, 1, []),) * 6 + ((OK_OUT, 2, [2]),) * 14 + ((OK_OUT, 2, [5]),)))

    def test_b3(self):
        actual = f.outcome_of(lambda: (retry_case('\u00b2', twice=True), retry_case(None, twice=True)))
        self.assertEqual(f.observe_boundary('B3', actual), ('RESULT', ((TRANSIENT, 2, [2]),) * 2))

    def test_b4(self):
        # BATCH10C F2: leading zeros do not count toward the four digits (RFC 9110 delay-seconds = 1*DIGIT), so a zero-padded value is its own delay, as before BATCH10C; int() never sees more than four digits.
        values = ('00005', '0' * 8 + '5', '00030', '00000', '0' * 4301, '0' * 4300 + '31', '000031', '0' * 4301 + '12345')
        actual = f.outcome_of(lambda: tuple(retry_case(value) for value in values))
        self.assertEqual(f.observe_boundary('B4', actual), ('RESULT', (
            (OK_OUT, 2, [5]), (OK_OUT, 2, [5]), (OK_OUT, 2, [30]), (OK_OUT, 2, [0]), (OK_OUT, 2, [0]),
            (TRANSIENT, 1, []), (TRANSIENT, 1, []), (TRANSIENT, 1, []))))


if __name__ == '__main__':
    unittest.main()
