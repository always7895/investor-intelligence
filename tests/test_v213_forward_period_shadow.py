"""Synthetic API tests; master-designed/Q-adopted, not independent authorship."""
from __future__ import annotations
import dataclasses
from datetime import datetime, timedelta
import builtins
import io
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
import traceback
import types
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts')) if str(ROOT / 'scripts') not in sys.path else None
import v213_forward_period_shadow as mod

KINDS = ('CALLER_CLAIMED_COMMITMENT', 'CALLER_CLAIMED_MANAGEMENT_GUIDANCE', 'CALLER_ANALYTICAL_INFERENCE')
FLAGS = ('independently_verified', 'comparability_qualified', 'scoring_eligible', 'publication_eligible', 'consumer_admission')
INPUTS = ('information_cutoff', 'period_start', 'period_end', 'declared_evidence_kind')
TIMES = INPUTS[:3]
COMMON = ('CALLER_DECLARATION_NOT_ADMITTED', 'NO_QUANTITY_OR_GROWTH_COMPUTED')
INVALID = 'FORWARD_PERIOD_DECLARATION_INVALID'
NOT_FORWARD = 'FORWARD_PERIOD_NOT_FORWARD'


def declaration(**changes):
    raw = dict(information_cutoff='2026-06-01T00:00:00Z', period_start='2026-06-01T00:00:00Z',
               period_end='2026-12-31T00:00:00Z', declared_evidence_kind=KINDS[0])
    raw.update(changes)
    return raw


class ForwardPeriodTests(unittest.TestCase):
    def invalid(self, raw, message=INVALID):
        with self.assertRaises(mod.ForwardPeriodError) as caught:
            mod.parse_forward_period_declaration(raw)
        self.assertEqual(str(caught.exception), message)
        return caught.exception

    def output(self, raw, role):
        before = dict(raw)
        result = mod.parse_forward_period_declaration(raw)
        value = result.to_dict()
        self.assertIs(type(value), dict)
        self.assertEqual(set(value), set(INPUTS) | {'time_role', 'period_scope', 'limitations'} | set(FLAGS))
        self.assertEqual({key: value[key] for key in INPUTS}, raw)
        self.assertEqual(value['time_role'], role)
        self.assertEqual(value['period_scope'], 'DECLARED_TOTAL_PERIOD')
        first = 'STRADDLING_TOTAL_NOT_FUTURE_REMAINDER' if role == 'STRADDLING_TOTAL' else 'FUTURE_PERIOD_NOT_REALIZATION_PROOF'
        self.assertEqual(result.limitations, (first, *COMMON))
        self.assertEqual(value['limitations'], [first, *COMMON])
        for flag in FLAGS:
            self.assertIs(getattr(result, flag), False)
            self.assertIs(value[flag], False)
        self.assertEqual(raw, before)
        return result

    def test_future_start_each_kind(self):
        for kind in KINDS:
            with self.subTest(kind=kind):
                self.output(declaration(declared_evidence_kind=kind, period_start='2026-07-01T00:00:00Z'), 'FUTURE_START_TOTAL')

    def test_straddling_each_kind(self):
        for kind in KINDS:
            with self.subTest(kind=kind):
                self.output(declaration(declared_evidence_kind=kind, period_start='2026-01-01T00:00:00Z'), 'STRADDLING_TOTAL')

    def test_cutoff_equalities_and_past(self):
        self.output(declaration(), 'FUTURE_START_TOTAL')
        self.invalid(declaration(period_start='2026-01-01T00:00:00Z', period_end='2026-06-01T00:00:00Z'), NOT_FORWARD)
        self.invalid(declaration(period_start='2026-01-01T00:00:00Z', period_end='2026-05-31T23:59:59Z'), NOT_FORWARD)

    def test_invalid_interval_order(self):
        self.invalid(declaration(period_end='2026-06-01T00:00:00Z'))
        self.invalid(declaration(period_end='2026-05-01T00:00:00Z'))

    def test_calendar_edges(self):
        cases = [
            ('0001-01-01T00:00:00Z', '0001-01-01T00:00:00Z', '0001-01-02T00:00:00Z', 'FUTURE_START_TOTAL'),
            ('9999-12-30T00:00:00Z', '9999-12-30T00:00:00Z', '9999-12-31T23:59:59Z', 'FUTURE_START_TOTAL'),
            ('2024-02-29T00:00:00Z', '2024-02-28T00:00:00Z', '2024-03-01T00:00:00Z', 'STRADDLING_TOTAL'),
            ('2024-02-28T00:00:00Z', '2024-02-29T00:00:00Z', '2024-03-01T00:00:00Z', 'FUTURE_START_TOTAL'),
            ('2025-12-31T23:59:59Z', '2025-12-31T23:59:59Z', '2026-01-01T00:00:00Z', 'FUTURE_START_TOTAL'),
        ]
        for cutoff, start, end, role in cases:
            self.output(declaration(information_cutoff=cutoff, period_start=start, period_end=end), role)

    def test_bad_timestamp_matrix_all_fields(self):
        invalid = ['0000-01-01T00:00:00Z', '10000-01-01T00:00:00Z', '2025-02-29T00:00:00Z',
                   '2026-02-30T00:00:00Z', '2026-00-01T00:00:00Z', '2026-13-01T00:00:00Z',
                   '2026-01-00T00:00:00Z', '2026-04-31T00:00:00Z', '2026-06-01T24:00:00Z',
                   '2026-06-01T00:60:00Z', '2026-06-01T00:00:60Z', '２０２６-06-01T00:00:00Z',
                   '٢٠٢٦-06-01T00:00:00Z', '2026-06-01T00:00:00+00:00', '2026-06-01T00:00:00.0Z',
                   '2026-06-01 00:00:00Z', '2026-06-01T00:00:00z', ' 2026-06-01T00:00:00Z',
                   '2026-06-01T00:00:00Z\n', '', 'SYNTHETIC_NO_ECHO_' * 1000]
        for field in TIMES:
            for index, value in enumerate(invalid):
                with self.subTest(field=field, index=index):
                    self.invalid(declaration(**{field: value}))

    def test_missing_and_injected_fields(self):
        for key in INPUTS:
            raw = declaration(); del raw[key]
            self.invalid(raw)
        for key in (*FLAGS, 'quantity', 'growth', 'score', 'rank', 'currency', 'unknown'):
            self.invalid(declaration(**{key: True}))
        self.invalid({str(i): 'x' for i in range(1000)})

    def test_wrong_top_level_types(self):
        for raw in (None, True, False, 0, 1.0, '', [], (), set(), types.MappingProxyType(declaration())):
            self.invalid(raw)
        calls = []
        class PoisonDict(dict):
            def __len__(self): calls.append('len'); raise AssertionError('hook')
            def keys(self): calls.append('keys'); raise AssertionError('hook')
            def __iter__(self): calls.append('iter'); raise AssertionError('hook')
            def __getitem__(self, key): calls.append('get'); raise AssertionError('hook')
        raw = PoisonDict(declaration()); calls.clear()
        self.invalid(raw)
        self.assertEqual(calls, [])

    def test_key_types_preserve_cardinality(self):
        class StringSubclass(str):
            pass
        for key in (True, 1, None, ('x',), StringSubclass('information_cutoff')):
            raw = declaration(); value = raw.pop('information_cutoff'); raw[key] = value
            self.assertEqual(len(raw), 4)
            self.invalid(raw)

    def test_wrong_value_types_no_conversion_hooks(self):
        calls = []
        class Poison:
            def __str__(self): calls.append('str'); raise AssertionError('hook')
            def __repr__(self): calls.append('repr'); raise AssertionError('hook')
            def __eq__(self, other): calls.append('eq'); raise AssertionError('hook')
            def __hash__(self): calls.append('hash'); raise AssertionError('hook')
            def __bool__(self): calls.append('bool'); raise AssertionError('hook')
            def __len__(self): calls.append('len'); raise AssertionError('hook')
        class StringSubclass(str):
            def __str__(self): calls.append('subclass-str'); raise AssertionError('hook')
        for field in INPUTS:
            for index, value in enumerate((None, True, 1, 1.5, [], {}, (), Poison(), StringSubclass(declaration()[field]))):
                raw = declaration(**{field: value}); calls.clear()
                with self.subTest(field=field, index=index):
                    self.invalid(raw)
                    self.assertEqual(calls, [])

    def test_evidence_kind_domain(self):
        for value in ('', 'FACT', 'VERIFIED', 'ADMITTED', KINDS[0].lower(), KINDS[0] + ' ', ' ' + KINDS[0], 'X' * 10000):
            self.invalid(declaration(declared_evidence_kind=value))

    def test_fixed_suppressed_calendar_diagnostics(self):
        raw = declaration(period_start='2026-02-30T00:00:00Z')
        try:
            mod.parse_forward_period_declaration(raw)
        except mod.ForwardPeriodError as exc:
            self.assertEqual(str(exc), INVALID)
            self.assertTrue(exc.__suppress_context__)
            rendered = ''.join(traceback.format_exception(type(exc), exc, exc.__traceback__))
            self.assertNotIn(raw['period_start'], rendered)
            self.assertNotIn('ValueError:', rendered)
        else:
            self.fail('invalid calendar accepted')

    def test_frozen_slots_and_constructor_flags(self):
        result = self.output(declaration(), 'FUTURE_START_TOTAL')
        self.assertFalse(hasattr(result, '__dict__'))
        fields = {field.name: field for field in dataclasses.fields(result)}
        args = {name: getattr(result, name) for name, field in fields.items() if field.init}
        for flag in FLAGS:
            self.assertFalse(fields[flag].init)
            with self.assertRaises(TypeError):
                mod.ForwardPeriodDeclaration(**args, **{flag: True})
            with self.assertRaises(dataclasses.FrozenInstanceError):
                setattr(result, flag, True)
        with self.assertRaises(dataclasses.FrozenInstanceError):
            result.time_role = 'MUTATED'

    def test_detached_serialization_and_input_preservation(self):
        raw = declaration(period_start='2026-01-01T00:00:00Z'); before = dict(raw)
        result = self.output(raw, 'STRADDLING_TOTAL'); expected = result.to_dict()
        first, second = result.to_dict(), result.to_dict()
        self.assertIsNot(first, second); self.assertIsNot(first['limitations'], second['limitations'])
        first['limitations'].append('MUTATED')
        for key in INPUTS + ('time_role', 'period_scope') + FLAGS: first[key] = 'MUTATED'
        self.assertEqual(result.to_dict(), expected)
        self.assertEqual(second, expected); self.assertEqual(raw, before)
        self.assertEqual(mod.parse_forward_period_declaration(raw), result)
        bad = declaration(period_end='2026-06-01T00:00:00Z'); copy = dict(bad)
        self.invalid(bad); self.assertEqual(bad, copy)

    def test_generated_interval_vectors(self):
        anchors = (datetime(2024, 2, 28), datetime(2025, 12, 31), datetime(2026, 6, 1))
        templates = ((0, 1, 'FUTURE_START_TOTAL'), (1, 2, 'FUTURE_START_TOTAL'), (-1, 1, 'STRADDLING_TOTAL'))
        count = 0
        for anchor in anchors:
            for scale in (1, 2, 7, 30):
                for start, end, role in templates:
                    encode = lambda value: value.isoformat(timespec='seconds') + 'Z'
                    raw = declaration(information_cutoff=encode(anchor), period_start=encode(anchor + timedelta(days=start * scale)),
                                      period_end=encode(anchor + timedelta(days=end * scale)))
                    self.output(raw, role); count += 1
        self.assertEqual(count, 36)

    def test_bounded_owned_import_and_parser_guards(self):
        # Read/compile before guards. This is bounded observed behavior, NOT a sandbox proof.
        path = Path(mod.__file__)
        code = compile(path.read_text(encoding='utf-8'), str(path), 'exec')
        name = '_t2_owned_import_probe'
        self.assertNotIn(name, sys.modules)
        owned = types.ModuleType(name)
        owned.__file__ = str(path)
        targets = [(builtins, 'open'), (io, 'open'), (socket, 'socket'), (subprocess, 'Popen'),
                   (os, 'getenv'), (os, 'putenv'), (time, 'time'), (time, 'monotonic')]
        from contextlib import ExitStack
        with patch.dict(sys.modules, {name: owned}):
            with ExitStack() as stack:
                probes = [stack.enter_context(patch.object(obj, attr, side_effect=AssertionError('DENIED_' + attr))) for obj, attr in targets]
                exec(code, owned.__dict__)
                future = owned.parse_forward_period_declaration(declaration()).to_dict()
                mixed = owned.parse_forward_period_declaration(declaration(period_start='2026-01-01T00:00:00Z')).to_dict()
                for probe in probes: probe.assert_not_called()
        self.assertNotIn(name, sys.modules)
        self.assertEqual(future['time_role'], 'FUTURE_START_TOTAL')
        self.assertEqual(mixed['time_role'], 'STRADDLING_TOTAL')
        for flag in FLAGS:
            self.assertIs(future[flag], False); self.assertIs(mixed[flag], False)


if __name__ == '__main__':
    unittest.main()
