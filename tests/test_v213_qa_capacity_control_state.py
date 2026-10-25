from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from v213_qa_capacity_control_state import (  # noqa: E402
    ABORT,
    AuthorityPairFacts,
    LexicalNamespaceFacts,
    PHASES,
    RunStateBindingClaims,
    StateEventClaims,
    StateHistoryFacts,
    StateValidationError,
    append_event,
    check_authority_pair_claims,
    check_namespace_lexical,
    initial_history,
    remaining_budget,
    validate_history,
    validate_state_binding,
)
from v213_qa_capacity_control_identity import (  # noqa: E402
    ACCEPTED_CONTROLLER_IDENTITY,
)


class RemainingBudgetTests(unittest.TestCase):
    def test_success(self):
        self.assertEqual(remaining_budget(100, 40, 10), 60)

    def test_zero_at_deadline(self):
        self.assertEqual(remaining_budget(100, 100, 50), 0)

    def test_now_equals_previous(self):
        self.assertEqual(remaining_budget(100, 50, 50), 50)

    def test_float_coordinates(self):
        self.assertEqual(remaining_budget(10.5, 2.5, 1.0), 8.0)

    def test_signed_coordinates(self):
        self.assertEqual(remaining_budget(-5, -10, -20), 5)

    def test_mixed_int_float(self):
        self.assertEqual(remaining_budget(100, 40.0, 10), 60.0)

    def test_backward_now_before_previous(self):
        with self.assertRaises(StateValidationError):
            remaining_budget(100, 10, 20)

    def test_exceeded_now_after_deadline(self):
        with self.assertRaises(StateValidationError):
            remaining_budget(100, 150, 10)

    def test_nan_rejected(self):
        nan = float("nan")
        for args in ((nan, 10, 5), (100, nan, 5), (100, 10, nan)):
            with self.assertRaises(StateValidationError):
                remaining_budget(*args)

    def test_inf_rejected(self):
        for v in (float("inf"), float("-inf")):
            for args in ((v, 10, 5), (100, v, 5), (100, 10, v)):
                with self.assertRaises(StateValidationError):
                    remaining_budget(*args)

    def test_bool_rejected(self):
        for b in (True, False):
            for args in ((b, 10, 5), (100, b, 5), (100, 10, b)):
                with self.assertRaises(StateValidationError):
                    remaining_budget(*args)

    def test_wrong_types_rejected(self):
        for bad in ("100", None, [100], {"a": 1}, (100,)):
            for args in ((bad, 10, 5), (100, bad, 5), (100, 10, bad)):
                with self.assertRaises(StateValidationError):
                    remaining_budget(*args)

    def test_overflow_rejected(self):
        with self.assertRaises(StateValidationError):
            remaining_budget(1e308, -1e308, -1e308)

    def test_huge_integer_input_rejected(self):
        huge = 10 ** 400
        for args in ((huge, 0, 0), (100, huge, 0), (100, 0, huge)):
            with self.assertRaises(StateValidationError):
                remaining_budget(*args)

    def test_integer_result_overflow_rejected(self):
        with self.assertRaises(StateValidationError):
            remaining_budget(10 ** 308, -(10 ** 308), -(10 ** 308))

    def test_int_float_subclass_rejected(self):
        class IntSub(int):
            pass

        class FloatSub(float):
            pass

        for bad in (IntSub(100), FloatSub(100.0)):
            for args in ((bad, 10, 5), (100, bad, 5), (100, 10, bad)):
                with self.assertRaises(StateValidationError):
                    remaining_budget(*args)

    def test_no_implicit_clock_deterministic(self):
        a = remaining_budget(100, 40, 10)
        b = remaining_budget(100, 40, 10)
        self.assertEqual(a, b)
        self.assertEqual(a, 60)


TASK_ID = "QA_CAPACITY_OPERATOR_HANDOFF_NATIVE_ONE_SHOT_6922278_V5"
# Authoritative accepted S1 pins (pure identity module), not fabricated.
SRC_SHA = ACCEPTED_CONTROLLER_IDENTITY.source_head
RUN_PLAN = ACCEPTED_CONTROLLER_IDENTITY.run_plan_sha256
REQUEST = ACCEPTED_CONTROLLER_IDENTITY.request_sha256
HARNESS = ACCEPTED_CONTROLLER_IDENTITY.harness_sha256
# Shape-valid but WRONG values (correct length/lowercase, not the accepted pin).
WRONG_SRC = "0" * 40
WRONG_RUN = "0" * 64
WRONG_REQ = "1" * 64
WRONG_HAR = "2" * 64
WINDOW = "W-6922278-ONE"
NS = "C:\\qa_capacity\\runs\\6922278"
FROM = 1_700_000_000
UNTIL = 1_700_003_600
NOW = 1_700_001_800
OPERATOR = "op-label-6922278"


def _valid_auth(**over):
    d = {
        "task_id": TASK_ID,
        "fixup_sha": SRC_SHA,
        "authorized_source_sha": SRC_SHA,
        "run_plan_sha256": RUN_PLAN,
        "request_sha256": REQUEST,
        "harness_sha256": HARNESS,
        "window_id": WINDOW,
        "valid_from_epoch_s": FROM,
        "valid_until_epoch_s": UNTIL,
        "run_namespace": NS,
    }
    d.update(over)
    return d


def _valid_handoff(**over):
    d = {
        "task_id": TASK_ID,
        "authorized_source_sha": SRC_SHA,
        "run_plan_sha256": RUN_PLAN,
        "request_sha256": REQUEST,
        "harness_sha256": HARNESS,
        "window_id": WINDOW,
        "valid_from_epoch_s": FROM,
        "valid_until_epoch_s": UNTIL,
        "run_namespace": NS,
        "operator": OPERATOR,
    }
    d.update(over)
    return d


class AuthorityPairClaimsTests(unittest.TestCase):
    def _check(self, auth=None, handoff=None, ns=NS, now=NOW):
        return check_authority_pair_claims(
            auth if auth is not None else _valid_auth(),
            handoff if handoff is not None else _valid_handoff(),
            ns,
            now,
        )

    def test_valid_asymmetric_pair(self):
        r = self._check()
        self.assertIsInstance(r, AuthorityPairFacts)
        self.assertIs(r.authorizes_execution, False)
        self.assertIs(r.namespace_requires_attestation, True)
        self.assertEqual(r.task_id, TASK_ID)
        self.assertEqual(r.fixup_sha, SRC_SHA)
        self.assertEqual(r.authorized_source_sha, SRC_SHA)
        self.assertEqual(r.run_plan_sha256, RUN_PLAN)
        self.assertEqual(r.request_sha256, REQUEST)
        self.assertEqual(r.harness_sha256, HARNESS)
        self.assertEqual(r.window_id, WINDOW)
        self.assertEqual(r.valid_from_epoch_s, FROM)
        self.assertEqual(r.valid_until_epoch_s, UNTIL)
        self.assertEqual(r.run_namespace, NS)
        self.assertEqual(r.operator, OPERATOR)

    def test_handoff_fixup_ignored(self):
        self._check(handoff=_valid_handoff(fixup_sha="00" * 40))
        self._check(handoff=_valid_handoff(fixup_sha=SRC_SHA))

    def test_unknown_extras_inert(self):
        r = self._check(
            auth=_valid_auth(extra_gate=True, other=123),
            handoff=_valid_handoff(extra_gate=True, zzz="x"),
        )
        self.assertIs(r.authorizes_execution, False)
        self.assertIs(r.namespace_requires_attestation, True)

    def test_missing_required_fields(self):
        for field in (
            "task_id", "fixup_sha", "authorized_source_sha",
            "run_plan_sha256", "request_sha256", "harness_sha256",
            "window_id", "valid_from_epoch_s", "valid_until_epoch_s",
            "run_namespace",
        ):
            d = _valid_auth()
            del d[field]
            with self.assertRaises(StateValidationError):
                self._check(auth=d)
        for field in (
            "task_id", "authorized_source_sha", "run_plan_sha256",
            "request_sha256", "harness_sha256", "window_id",
            "valid_from_epoch_s", "valid_until_epoch_s", "run_namespace",
            "operator",
        ):
            d = _valid_handoff()
            del d[field]
            with self.assertRaises(StateValidationError):
                self._check(handoff=d)

    def test_task_id_mismatch(self):
        with self.assertRaises(StateValidationError):
            self._check(auth=_valid_auth(task_id="OTHER"))
        with self.assertRaises(StateValidationError):
            self._check(handoff=_valid_handoff(task_id="OTHER"))

    def test_source_fixup_mismatch(self):
        with self.assertRaises(StateValidationError):
            self._check(auth=_valid_auth(fixup_sha=WRONG_SRC))
        with self.assertRaises(StateValidationError):
            self._check(auth=_valid_auth(authorized_source_sha=WRONG_SRC))
        with self.assertRaises(StateValidationError):
            self._check(handoff=_valid_handoff(authorized_source_sha=WRONG_SRC))

    def test_source_fixup_changed_consistently(self):
        # both fixup and source changed to the same shape-valid wrong value
        with self.assertRaises(StateValidationError):
            self._check(
                auth=_valid_auth(fixup_sha=WRONG_SRC,
                                 authorized_source_sha=WRONG_SRC),
                handoff=_valid_handoff(authorized_source_sha=WRONG_SRC),
            )

    def test_pin_mismatch(self):
        wrong = {"run_plan_sha256": WRONG_RUN,
                 "request_sha256": WRONG_REQ,
                 "harness_sha256": WRONG_HAR}
        for field in ("run_plan_sha256", "request_sha256", "harness_sha256"):
            # synchronized shape-valid WRONG value across BOTH records
            with self.assertRaises(StateValidationError):
                self._check(
                    auth=_valid_auth(**{field: wrong[field]}),
                    handoff=_valid_handoff(**{field: wrong[field]}),
                )
            # single-record wrong value also rejected
            with self.assertRaises(StateValidationError):
                self._check(handoff=_valid_handoff(**{field: wrong[field]}))

    def test_uppercase_pins_rejected(self):
        # uppercase matching pairs: correct length but wrong case
        with self.assertRaises(StateValidationError):
            self._check(auth=_valid_auth(fixup_sha=SRC_SHA.upper()))
        for field in ("run_plan_sha256", "request_sha256", "harness_sha256"):
            up = getattr(ACCEPTED_CONTROLLER_IDENTITY, field).upper()
            with self.assertRaises(StateValidationError):
                self._check(
                    auth=_valid_auth(**{field: up}),
                    handoff=_valid_handoff(**{field: up}),
                )

    def test_pin_wrong_type(self):
        with self.assertRaises(StateValidationError):
            self._check(auth=_valid_auth(fixup_sha=12345))
        with self.assertRaises(StateValidationError):
            self._check(auth=_valid_auth(run_plan_sha256=0))

    def test_shared_mismatch(self):
        with self.assertRaises(StateValidationError):
            self._check(handoff=_valid_handoff(window_id="W-OTHER"))
        with self.assertRaises(StateValidationError):
            self._check(handoff=_valid_handoff(valid_from_epoch_s=FROM + 1))
        with self.assertRaises(StateValidationError):
            self._check(handoff=_valid_handoff(valid_until_epoch_s=UNTIL - 1))
        with self.assertRaises(StateValidationError):
            self._check(handoff=_valid_handoff(run_namespace="C:\\other"))

    def test_bad_sha_length(self):
        with self.assertRaises(StateValidationError):
            self._check(auth=_valid_auth(fixup_sha="abc"))
        with self.assertRaises(StateValidationError):
            self._check(auth=_valid_auth(run_plan_sha256="00" * 63))

    def test_bounds_types(self):
        for bad in (True, False, float("nan"), float("inf"),
                    float("-inf"), 10 ** 400, "1"):
            for kw in ("valid_from_epoch_s", "valid_until_epoch_s"):
                with self.assertRaises(StateValidationError):
                    self._check(auth=_valid_auth(**{kw: bad}))

    def test_now_window(self):
        self._check(now=FROM)
        for bad in (UNTIL, FROM - 1, UNTIL + 1):
            with self.assertRaises(StateValidationError):
                self._check(now=bad)
        for bad in (True, float("nan"), 10 ** 400, "1"):
            with self.assertRaises(StateValidationError):
                self._check(now=bad)

    def test_from_until_order(self):
        with self.assertRaises(StateValidationError):
            self._check(auth=_valid_auth(valid_from_epoch_s=UNTIL))
        with self.assertRaises(StateValidationError):
            self._check(
                auth=_valid_auth(valid_from_epoch_s=UNTIL,
                                 valid_until_epoch_s=UNTIL)
            )

    def test_operator_types(self):
        with self.assertRaises(StateValidationError):
            self._check(handoff=_valid_handoff(operator=123))
        with self.assertRaises(StateValidationError):
            self._check(handoff=_valid_handoff(operator=""))

    def test_window_id_types(self):
        with self.assertRaises(StateValidationError):
            self._check(auth=_valid_auth(window_id=7))
        with self.assertRaises(StateValidationError):
            self._check(auth=_valid_auth(window_id=""))

    def test_namespace_mismatch(self):
        with self.assertRaises(StateValidationError):
            self._check(ns="C:\\expected\\different")

    def test_namespace_relative(self):
        for rel in ("C:foo", "foo\\bar", "runs\\6922278", ""):
            with self.assertRaises(StateValidationError):
                self._check(ns=rel)

    def test_namespace_nonstr(self):
        with self.assertRaises(StateValidationError):
            self._check(ns=123)

    def test_hostile_keys_and_mappings(self):
        class StrSub(str):
            pass

        class DictSub(dict):
            pass

        with self.assertRaises(StateValidationError):
            self._check(auth={StrSub("task_id"): TASK_ID})
        with self.assertRaises(StateValidationError):
            self._check(auth={1: "x"})
        with self.assertRaises(StateValidationError):
            self._check(auth=DictSub(_valid_auth()))
        with self.assertRaises(StateValidationError):
            self._check(auth=[_valid_auth()])

    def test_frozen_no_mutable_mapping(self):
        r = self._check()
        self.assertIsInstance(r, AuthorityPairFacts)
        with self.assertRaises(AttributeError):
            r.task_id = "x"
        with self.assertRaises(AttributeError):
            del r.task_id

    def test_flags_not_replaceable(self):
        r = self._check()
        # no _replace method advertises a granted flag
        with self.assertRaises(AttributeError):
            r._replace(authorizes_execution=True)
        # public constructor does not accept the flags
        with self.assertRaises(TypeError):
            AuthorityPairFacts(authorizes_execution=True)
        self.assertIs(r.authorizes_execution, False)
        self.assertIs(r.namespace_requires_attestation, True)

    def test_input_mutation_isolation(self):
        auth = _valid_auth()
        handoff = _valid_handoff()
        r = check_authority_pair_claims(auth, handoff, NS, NOW)
        auth["task_id"] = "MUTATED"
        handoff["operator"] = "MUTATED"
        self.assertEqual(r.task_id, TASK_ID)
        self.assertEqual(r.operator, OPERATOR)


class NamespaceLexicalTests(unittest.TestCase):
    """Public check_namespace_lexical regression table (ticket03 step C)."""

    ROOT = r'C:\synthetic\audit'

    def _ok(self, root, cand):
        return check_namespace_lexical(root, cand)

    def _reject(self, root, cand, msg=None):
        with self.assertRaises(StateValidationError) as ctx:
            check_namespace_lexical(root, cand)
        if msg is not None:
            self.assertIn(msg, str(ctx.exception))
        return ctx.exception

    def test_accepted_strict_descendant_raw_retained(self):
        r = self._ok(self.ROOT, r'C:\synthetic\audit\child')
        self.assertEqual(r.raw_root, self.ROOT)
        self.assertEqual(r.raw_candidate, r'C:\synthetic\audit\child')
        self.assertEqual(r.normalized_root, self.ROOT)
        self.assertEqual(r.normalized_candidate, r'C:\synthetic\audit\child')
        self.assertEqual(r.root_components, ('synthetic', 'audit'))
        self.assertEqual(r.candidate_components,
                         ('synthetic', 'audit', 'child'))

    def test_accepted_slash_backslash_mixed_only_slash_normalized(self):
        r = self._ok(self.ROOT, 'C:/synthetic/audit/child')
        self.assertEqual(r.raw_candidate, 'C:/synthetic/audit/child')
        self.assertEqual(r.normalized_candidate, r'C:\synthetic\audit\child')
        r2 = self._ok('C:/synthetic/audit', r'C:\synthetic\audit\deep\x')
        self.assertEqual(r2.normalized_root, r'C:\synthetic\audit')
        r3 = self._ok(self.ROOT, 'C:/synthetic\\audit/mixed')
        self.assertEqual(r3.normalized_candidate, r'C:\synthetic\audit\mixed')

    def test_accepted_valid_com10_and_com1notes(self):
        self._ok(self.ROOT, r'C:\synthetic\audit\COM10')
        self._ok(self.ROOT, r'C:\synthetic\audit\COM1notes')

    def test_accepted_lowercase_bound_root_exact_case(self):
        r = self._ok(r'c:\synthetic\audit', r'c:\synthetic\audit\child')
        self.assertEqual(r.root_drive, 'c')
        self.assertEqual(r.candidate_drive, 'c')

    def test_reject_root_itself(self):
        self._reject(self.ROOT, self.ROOT, 'strict descendant')

    def test_reject_sibling_prefix(self):
        self._reject(self.ROOT, r'C:\synthetic\audit2', 'outside root')
        self._reject(self.ROOT, r'C:\synthetic\auditor', 'outside root')

    def test_reject_shorter_path(self):
        self._reject(r'C:\synthetic\audit\deep', self.ROOT, 'outside root')

    def test_reject_wrong_drive(self):
        self._reject(self.ROOT, r'D:\synthetic\audit\child', 'drive differs')

    def test_reject_bare_drive_configured_root(self):
        self._reject('C:\\', r'C:\synthetic\audit', 'named directory')

    def test_root_alias_ambiguous_drive_directions(self):
        self._reject(r'C:\synthetic\audit', r'c:\synthetic\audit\child',
                     'ROOT_ALIAS_AMBIGUOUS')
        self._reject(r'c:\synthetic\audit', r'C:\synthetic\audit\child',
                     'ROOT_ALIAS_AMBIGUOUS')

    def test_root_alias_ambiguous_component_directions(self):
        self._reject(r'C:\synthetic\audit', r'C:\SYNTHETIC\audit\child',
                     'ROOT_ALIAS_AMBIGUOUS')
        self._reject(r'C:\SYNTHETIC\audit', r'C:\synthetic\audit\child',
                     'ROOT_ALIAS_AMBIGUOUS')

    def test_reject_prefixes_root_and_candidate(self):
        for bad in (r'\\server\share', r'\\?\C:\x', r'\\.\C:\x',
                    r'\??\C:\x', r'\\NT\share'):
            self._reject(bad, r'C:\synthetic\audit\child')
            self._reject(self.ROOT, bad)
        for bad in (r'C:foo', r'foo\bar', r'runs\6922278'):
            self._reject(bad, r'C:\synthetic\audit\child')
            self._reject(self.ROOT, bad)

    def test_reject_ads_invalid_chars_separators(self):
        self._reject(self.ROOT, r'C:\synthetic\audit\a:stream')
        for bad in (r'C:\synthetic\audit\a<b', r'C:\synthetic\audit\c>d',
                    r'C:\synthetic\audit\p|q', r'C:\synthetic\audit\m?n',
                    r'C:\synthetic\audit\s*t', r'C:\synthetic\audit\w"x',
                    r'C:\synthetic\audit\d:z'):
            self._reject(self.ROOT, bad)
        self._reject(self.ROOT, r'C:\synthetic\audit\\child')
        self._reject(self.ROOT, r'C:\synthetic\audit\child' + '\\')

    def test_reject_dot_dot_before_purepath_collapse(self):
        from pathlib import PureWindowsPath
        self.assertEqual(
            str(PureWindowsPath(r'C:\synthetic\audit\.\child')),
            r'C:\synthetic\audit\child')
        self._reject(self.ROOT, r'C:\synthetic\audit\.\child')
        self._reject(self.ROOT, r'C:\synthetic\audit\..\other')

    def test_reject_trailing_space_dot_and_controls(self):
        self._reject(self.ROOT, r'C:\synthetic\audit\child ')
        self._reject(self.ROOT, r'C:\synthetic\audit\child.')
        base = r'C:\synthetic\audit\child'
        for cc in (chr(0), chr(9), chr(1), chr(127)):
            self._reject(self.ROOT, base + cc)

    def test_reject_non_builtin_string_and_subclass(self):
        class StrSub(str):
            pass
        self._reject(StrSub(self.ROOT), r'C:\synthetic\audit\child')
        self._reject(self.ROOT, StrSub(r'C:\synthetic\audit\child'))
        for bad in (None, 123, b'C:\\x'):
            self._reject(bad, r'C:\synthetic\audit\child')
            self._reject(self.ROOT, bad)

    def test_reject_reserved_device_names(self):
        for name in ('CON', 'PRN', 'AUX', 'NUL', 'CONIN$', 'CONOUT$',
                     'COM0', 'COM1', 'COM9', 'LPT0', 'LPT1', 'LPT9',
                     'con', 'Prn', 'aUx', 'nul.txt', 'COM\u00b9',
                     'LPT\u00b2', 'CON .txt'):
            self._reject(self.ROOT, r'C:\synthetic\audit' + '\\' + name)

    def test_reject_shortname_tilde_digit_anywhere(self):
        self._reject(self.ROOT, r'C:\synthetic\audit\PROGRA~1')
        self._reject(self.ROOT, r'C:\synthetic\audit\run~2x')
        self._reject(self.ROOT, r'C:\synthetic\audit\xPROGRA~1y')
        self._ok(self.ROOT, r'C:\synthetic\audit\plain~name')

    def test_fixed_flags_and_alias_policy(self):
        r = self._ok(self.ROOT, r'C:\synthetic\audit\child')
        self.assertIs(r.LEXICAL_ONLY, True)
        self.assertIs(r.FILESYSTEM_ATTESTATION_REQUIRED, True)
        self.assertIs(r.AUTHORIZES_EXECUTION, False)
        self.assertIs(r.ROOT_IDENTITY_UNATTESTED, True)
        self.assertEqual(r.root_alias_policy, 'EXACT_CASE_COMPONENT_PREFIX')
        with self.assertRaises(TypeError):
            LexicalNamespaceFacts(AUTHORIZES_EXECUTION=True)
        with self.assertRaises(AttributeError):
            r.raw_root = 'x'
        with self.assertRaises(AttributeError):
            del r.raw_root
        self.assertIsInstance(r.root_components, tuple)
        self.assertIsInstance(r.candidate_components, tuple)

    def test_public_api_no_side_effect_primitives(self):
        import unittest.mock as mock
        targets = (
            'os.stat', 'os.listdir', 'os.access', 'os.path.exists',
            'os.remove', 'os.mkdir', 'os.getcwd',
            'time.time', 'socket.socket', 'subprocess.run',
        )
        patches = [mock.patch(t) for t in targets]
        mocks = [p.start() for p in patches]
        try:
            self._ok(self.ROOT, r'C:\synthetic\audit\child')
            self._reject(self.ROOT, self.ROOT)
        finally:
            for p in patches:
                p.stop()
        for m in mocks:
            m.assert_not_called()


# --- T04 C2: focused public-API tests ---------------------------------------

CK = 'a' * 40
RB = 'b' * 64
DL = 100.0
B = validate_state_binding(CK, 'run1', RB, DL)


def _ev(seq, eid, phase, now, ck=CK, run_id='run1', rb=RB, dl=DL):
    return StateEventClaims(ck, run_id, rb, dl, seq, eid, phase, now)


class TestStateBindingSchema(unittest.TestCase):
    def test_valid_binding(self):
        b = validate_state_binding(CK, 'run1', RB, DL)
        self.assertEqual(b.checkpoint_key, CK)
        self.assertEqual(b.run_id, 'run1')
        self.assertEqual(b.run_binding_sha256, RB)
        self.assertEqual(b.deadline, DL)

    def test_40_vs_64_rejected(self):
        for bad in (RB, 'a' * 39, 'a' * 41):
            with self.assertRaises(StateValidationError):
                validate_state_binding(bad, 'r', RB, DL)
        for bad in (CK, 'b' * 63, 'b' * 65):
            with self.assertRaises(StateValidationError):
                validate_state_binding(CK, 'r', bad, DL)

    def test_lowercase_only(self):
        with self.assertRaises(StateValidationError):
            validate_state_binding('A' * 40, 'r', RB, DL)
        with self.assertRaises(StateValidationError):
            validate_state_binding(CK, 'r', 'B' * 64, DL)

    def test_runid_boundary(self):
        validate_state_binding(CK, 'a' * 128, RB, DL)
        with self.assertRaises(StateValidationError):
            validate_state_binding(CK, 'a' * 129, RB, DL)
        with self.assertRaises(StateValidationError):
            validate_state_binding(CK, '', RB, DL)

    def test_runid_chars(self):
        validate_state_binding(CK, 'aB_9-', RB, DL)
        for bad in ('has space', 'tab\tx', 'uni\u00e9', 'slash/'): 
            with self.assertRaises(StateValidationError):
                validate_state_binding(CK, bad, RB, DL)

    def test_deadline_types(self):
        validate_state_binding(CK, 'r', RB, 100)
        validate_state_binding(CK, 'r', RB, 100.5)
        for bad in (True, False, float('inf'), float('nan'), None, '100'):
            with self.assertRaises(StateValidationError):
                validate_state_binding(CK, 'r', RB, bad)

    def test_malformed_binding_rejected_by_initial(self):
        bad = StateEventClaims(CK, 'r', RB, DL, 0, 'c'*64, 'RESERVED', 10.0)
        bad_binding = RunStateBindingClaims('x'*40, 'r', RB, DL)
        with self.assertRaises(StateValidationError):
            initial_history(bad_binding, 'c'*64, 10.0)

    def test_immutability(self):
        b = validate_state_binding(CK, 'r', RB, DL)
        with self.assertRaises(AttributeError):
            b.checkpoint_key = 'c' * 40
        with self.assertRaises(AttributeError):
            del b.run_id

    def test_replace_creates_new(self):
        b = validate_state_binding(CK, 'r', RB, DL)
        b2 = b._replace(run_id='r2')
        self.assertEqual(b.run_id, 'r')
        self.assertEqual(b2.run_id, 'r2')

    def test_flags_not_constructor(self):
        with self.assertRaises(TypeError):
            RunStateBindingClaims(CK, 'r', RB, DL, False)
        with self.assertRaises(TypeError):
            StateEventClaims(CK, 'r', RB, DL, 0, 'c'*64, 'RESERVED', 10.0, False)


class TestInitialStateAndChain(unittest.TestCase):
    def test_full_forward_chain(self):
        h = initial_history(B, 'c'*64, 10.0)
        h = append_event(h, 'd'*64, 'VERIFIED', 20.0)
        h = append_event(h, 'e'*64, 'ACTIVATION_RESERVED', 30.0)
        h = append_event(h, 'f'*64, 'RUNNER_STARTED', 40.0)
        h = append_event(h, '0'*64, 'TERMINAL', 50.0)
        f = validate_history(h)
        self.assertEqual(f.invocation_count, 1)
        self.assertTrue(f.terminal)
        self.assertFalse(f.activation_history_ambiguous)

    def test_counts_exact(self):
        h = initial_history(B, 'c'*64, 10.0)
        f = validate_history(h)
        self.assertEqual(f.invocation_count, 0)
        h = append_event(h, 'd'*64, 'VERIFIED', 20.0)
        h = append_event(h, 'e'*64, 'ACTIVATION_RESERVED', 30.0)
        f = validate_history(h)
        self.assertIsNone(f.invocation_count)
        h = append_event(h, 'f'*64, 'RUNNER_STARTED', 40.0)
        f = validate_history(h)
        self.assertEqual(f.invocation_count, 1)

    def test_abort_from_each_origin(self):
        # ABORT after RESERVED (count 0)
        h = initial_history(B, 'c'*64, 10.0)
        h = append_event(h, 'd'*64, ABORT, 15.0)
        f = validate_history(h)
        self.assertEqual(f.invocation_count, 0)
        self.assertTrue(f.terminal)
        # ABORT after VERIFIED (count 0)
        h = initial_history(B, 'c'*64, 10.0)
        h = append_event(h, 'd'*64, 'VERIFIED', 20.0)
        h = append_event(h, 'e'*64, ABORT, 25.0)
        f = validate_history(h)
        self.assertEqual(f.invocation_count, 0)
        # ABORT after ACTIVATION_RESERVED (count None)
        h = initial_history(B, 'c'*64, 10.0)
        h = append_event(h, 'd'*64, 'VERIFIED', 20.0)
        h = append_event(h, 'e'*64, 'ACTIVATION_RESERVED', 30.0)
        h = append_event(h, 'f'*64, ABORT, 35.0)
        f = validate_history(h)
        self.assertIsNone(f.invocation_count)
        self.assertTrue(f.activation_history_ambiguous)
        # ABORT after RUNNER_STARTED (count 1)
        h = initial_history(B, 'c'*64, 10.0)
        h = append_event(h, 'd'*64, 'VERIFIED', 20.0)
        h = append_event(h, 'e'*64, 'ACTIVATION_RESERVED', 30.0)
        h = append_event(h, 'f'*64, 'RUNNER_STARTED', 40.0)
        h = append_event(h, '0'*64, ABORT, 45.0)
        f = validate_history(h)
        self.assertEqual(f.invocation_count, 1)

    def test_abort_at_equal_deadline(self):
        h = initial_history(B, 'c'*64, 10.0)
        h = append_event(h, 'd'*64, 'VERIFIED', 20.0)
        h = append_event(h, 'e'*64, ABORT, DL)
        f = validate_history(h)
        self.assertTrue(f.terminal)

    def test_no_event_after_terminal(self):
        h = initial_history(B, 'c'*64, 10.0)
        h = append_event(h, 'd'*64, 'VERIFIED', 20.0)
        h = append_event(h, 'e'*64, 'ACTIVATION_RESERVED', 30.0)
        h = append_event(h, 'f'*64, 'RUNNER_STARTED', 40.0)
        h = append_event(h, '0'*64, 'TERMINAL', 50.0)
        with self.assertRaises(StateValidationError):
            append_event(h, '1'*64, 'VERIFIED', 55.0)

    def test_no_event_after_abort(self):
        h = initial_history(B, 'c'*64, 10.0)
        h = append_event(h, 'd'*64, ABORT, 15.0)
        with self.assertRaises(StateValidationError):
            append_event(h, 'e'*64, 'VERIFIED', 20.0)


class TestHistoryRejections(unittest.TestCase):
    def test_skipped_phase(self):
        h = initial_history(B, 'c'*64, 10.0)
        with self.assertRaises(StateValidationError):
            append_event(h, 'd'*64, 'ACTIVATION_RESERVED', 20.0)

    def test_repeated_phase(self):
        h = initial_history(B, 'c'*64, 10.0)
        h = append_event(h, 'd'*64, 'VERIFIED', 20.0)
        with self.assertRaises(StateValidationError):
            append_event(h, 'e'*64, 'VERIFIED', 30.0)

    def test_duplicate_event_id(self):
        h = initial_history(B, 'c'*64, 10.0)
        with self.assertRaises(StateValidationError):
            append_event(h, 'c'*64, 'VERIFIED', 20.0)

    def test_wrong_first_phase(self):
        ev = _ev(0, 'c'*64, 'VERIFIED', 10.0)
        with self.assertRaises(StateValidationError):
            validate_history((ev,))

    def test_empty_history(self):
        with self.assertRaises(StateValidationError):
            validate_history(())

    def test_list_rejected(self):
        ev = _ev(0, 'c'*64, 'RESERVED', 10.0)
        with self.assertRaises(StateValidationError):
            validate_history([ev])

    def test_event_subclass_rejected(self):
        class Sub(StateEventClaims):
            pass
        ev = Sub(CK, 'r', RB, DL, 0, 'c'*64, 'RESERVED', 10.0)
        with self.assertRaises(StateValidationError):
            validate_history((ev,))

    def test_dict_rejected(self):
        with self.assertRaises(StateValidationError):
            validate_history(({'phase': 'RESERVED'},))

    def test_unknown_phase(self):
        h = initial_history(B, 'c'*64, 10.0)
        with self.assertRaises(StateValidationError):
            append_event(h, 'd'*64, 'UNKNOWN', 20.0)

    def test_nonstring_phase(self):
        ev = _ev(0, 'c'*64, 123, 10.0)
        with self.assertRaises(StateValidationError):
            validate_history((ev,))

    def test_wrong_event_id_shape(self):
        h = initial_history(B, 'c'*64, 10.0)
        with self.assertRaises(StateValidationError):
            append_event(h, 'x'*64, 'VERIFIED', 20.0)

    def test_bool_sequence(self):
        ev = _ev(True, 'c'*64, 'RESERVED', 10.0)
        with self.assertRaises(StateValidationError):
            validate_history((ev,))

    def test_gap_sequence(self):
        ev = _ev(2, 'c'*64, 'RESERVED', 10.0)
        with self.assertRaises(StateValidationError):
            validate_history((ev,))


class TestLaterBindingGuards(unittest.TestCase):
    def test_later_binding_field_changed(self):
        for field in ('checkpoint_key', 'run_id', 'run_binding_sha256', 'deadline'):
            ev0 = _ev(0, 'c'*64, 'RESERVED', 10.0)
            if field == 'checkpoint_key':
                ev1 = _ev(1, 'd'*64, 'VERIFIED', 20.0, ck='c'*40)
            elif field == 'run_id':
                ev1 = _ev(1, 'd'*64, 'VERIFIED', 20.0, run_id='other')
            elif field == 'run_binding_sha256':
                ev1 = _ev(1, 'd'*64, 'VERIFIED', 20.0, rb='c'*64)
            else:
                ev1 = _ev(1, 'd'*64, 'VERIFIED', 20.0, dl=200.0)
            with self.assertRaises(StateValidationError):
                validate_history((ev0, ev1))

    def test_deadline_type_mismatch(self):
        ev0 = _ev(0, 'c'*64, 'RESERVED', 10.0, dl=100)
        ev1 = _ev(1, 'd'*64, 'VERIFIED', 20.0, dl=100.0)
        with self.assertRaises(StateValidationError):
            validate_history((ev0, ev1))

    def test_later_str_subclass_rejected(self):
        class EvilStr(str):
            def __eq__(self, other):
                return True
        ev0 = _ev(0, 'c'*64, 'RESERVED', 10.0)
        ev1 = _ev(1, 'd'*64, 'VERIFIED', 20.0, ck=EvilStr(CK))
        with self.assertRaises(StateValidationError):
            validate_history((ev0, ev1))

    def test_poison_eq_never_called(self):
        class Poison:
            def __eq__(self, other):
                raise RuntimeError('must not be called')
            def __ne__(self, other):
                raise RuntimeError('must not be called')
        ev0 = _ev(0, 'c'*64, 'RESERVED', 10.0)
        ev1 = _ev(1, 'd'*64, 'VERIFIED', 20.0, dl=Poison())
        with self.assertRaises(StateValidationError):
            validate_history((ev0, ev1))


class TestTimeAndCoordinates(unittest.TestCase):
    def test_now_types(self):
        for bad in (True, False, float('inf'), float('nan'), None, '10', [1]):
            ev = _ev(0, 'c'*64, 'RESERVED', bad)
            with self.assertRaises(StateValidationError):
                validate_history((ev,))

    def test_backward_now(self):
        ev0 = _ev(0, 'c'*64, 'RESERVED', 20.0)
        ev1 = _ev(1, 'd'*64, 'VERIFIED', 10.0)
        with self.assertRaises(StateValidationError):
            validate_history((ev0, ev1))

    def test_expired_forward(self):
        h = initial_history(B, 'c'*64, 10.0)
        with self.assertRaises(StateValidationError):
            append_event(h, 'd'*64, 'VERIFIED', DL)

    def test_expired_forward_past(self):
        with self.assertRaises(StateValidationError):
            validate_history((_ev(0, 'c'*64, 'RESERVED', 10.0),
                              _ev(1, 'd'*64, 'VERIFIED', DL + 1)))

    def test_signed_coordinates(self):
        b_neg = validate_state_binding(CK, 'r', RB, -50.0)
        h = initial_history(b_neg, 'c'*64, -60.0)
        h = append_event(h, 'd'*64, 'VERIFIED', -55.0)
        f = validate_history(h)
        self.assertEqual(f.invocation_count, 0)

    def test_huge_integer_deadline(self):
        huge = 10**300
        b = validate_state_binding(CK, 'r', RB, huge)
        h = initial_history(b, 'c'*64, 1.0)
        h = append_event(h, 'd'*64, 'VERIFIED', 2.0)
        f = validate_history(h)
        self.assertEqual(f.invocation_count, 0)

    def test_original_unchanged_after_append(self):
        h_orig = initial_history(B, 'c'*64, 10.0)
        h_new = append_event(h_orig, 'd'*64, 'VERIFIED', 20.0)
        self.assertEqual(len(h_orig), 1)
        self.assertEqual(len(h_new), 2)

    def test_idempotent_validation(self):
        h = initial_history(B, 'c'*64, 10.0)
        h = append_event(h, 'd'*64, 'VERIFIED', 20.0)
        f1 = validate_history(h)
        f2 = validate_history(h)
        self.assertEqual(f1, f2)


class TestExhaustivePhaseGraph(unittest.TestCase):
    """Exhaustive pure phase graph: 6 labels, lengths 1..5.
    Independent hardcoded 9 valid paths as oracle."""
    LABELS = PHASES + (ABORT,)
    # 9 valid paths: 5 forward prefixes + 4 ABORT terminals
    VALID_PATHS = (
        ('RESERVED',),
        ('RESERVED', 'VERIFIED'),
        ('RESERVED', 'VERIFIED', 'ACTIVATION_RESERVED'),
        ('RESERVED', 'VERIFIED', 'ACTIVATION_RESERVED', 'RUNNER_STARTED'),
        ('RESERVED', 'VERIFIED', 'ACTIVATION_RESERVED', 'RUNNER_STARTED', 'TERMINAL'),
        ('RESERVED', ABORT),
        ('RESERVED', 'VERIFIED', ABORT),
        ('RESERVED', 'VERIFIED', 'ACTIVATION_RESERVED', ABORT),
        ('RESERVED', 'VERIFIED', 'ACTIVATION_RESERVED', 'RUNNER_STARTED', ABORT),
    )

    def _build_history(self, phases):
        events = []
        for i, phase in enumerate(phases):
            eid = chr(ord('a') + i) * 64
            events.append(_ev(i, eid, phase, 10.0 + i))
        return tuple(events)

    def test_valid_paths_accepted(self):
        for path in self.VALID_PATHS:
            h = self._build_history(path)
            f = validate_history(h)
            self.assertIsNotNone(f, 'valid path rejected: %s' % (path,))

    def test_invalid_paths_rejected(self):
        # Spot-check a set of known-invalid paths
        invalid = (
            ('VERIFIED',),
            ('RESERVED', 'RESERVED'),
            ('RESERVED', 'ACTIVATION_RESERVED'),
            ('RESERVED', 'RUNNER_STARTED'),
            ('RESERVED', 'TERMINAL'),
            ('RESERVED', 'VERIFIED', 'RESERVED'),
            ('RESERVED', 'VERIFIED', 'VERIFIED'),
            ('RESERVED', 'VERIFIED', 'RUNNER_STARTED'),
            ('RESERVED', 'VERIFIED', 'ACTIVATION_RESERVED', 'ACTIVATION_RESERVED'),
            ('RESERVED', 'VERIFIED', 'ACTIVATION_RESERVED', 'TERMINAL'),
            ('RESERVED', ABORT, 'VERIFIED'),
            ('RESERVED', 'VERIFIED', ABORT, 'ACTIVATION_RESERVED'),
        )
        for path in invalid:
            h = self._build_history(path)
            with self.assertRaises(StateValidationError, msg='should reject: %s' % (path,)):
                validate_history(h)

    def test_full_exhaustive_graph(self):
        """All 6^1 + 6^2 + 6^3 + 6^4 + 6^5 = 9330 histories.
        Stop at first unexpected result."""
        import itertools
        total = 0
        accepted = 0
        for length in range(1, 6):
            for combo in itertools.product(self.LABELS, repeat=length):
                total += 1
                h = self._build_history(combo)
                try:
                    validate_history(h)
                    accepted += 1
                    if combo not in self.VALID_PATHS:
                        self.fail('unexpectedly accepted: %s' % (combo,))
                except StateValidationError:
                    if combo in self.VALID_PATHS:
                        self.fail('unexpectedly rejected: %s' % (combo,))
        self.assertEqual(total, 9330)
        self.assertEqual(accepted, 9)


class TestNoSideEffects(unittest.TestCase):
    def test_no_fs_clock_rng_network(self):
        import unittest.mock as mock
        targets = (
            'os.stat', 'os.listdir', 'os.access', 'os.path.exists',
            'os.remove', 'os.mkdir', 'os.getcwd', 'builtins.open',
            'time.time', 'time.monotonic', 'random.random',
            'socket.socket', 'subprocess.run',
        )
        patches = [mock.patch(t, side_effect=AssertionError(t)) for t in targets]
        mocks = [p.start() for p in patches]
        try:
            h = initial_history(B, 'c'*64, 10.0)
            h = append_event(h, 'd'*64, 'VERIFIED', 20.0)
            validate_history(h)
            # invalid path
            try:
                append_event(h, 'd'*64, 'VERIFIED', 30.0)
            except StateValidationError:
                pass
        finally:
            for p in patches:
                p.stop()


if __name__ == "__main__":
    unittest.main()