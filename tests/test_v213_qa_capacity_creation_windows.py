import sys
import threading
import unittest
from pathlib import Path
from unittest import mock

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
import v213_qa_capacity_creation_windows as m  # noqa: E402

GOOD_BINDING = {"run_id": "run-1", "candidate_sha256": "a" * 64}


class HelperPureTest(unittest.TestCase):
    def setUp(self):
        self._slot_patcher = mock.patch.object(m, "_registry_slot", None)
        self._lock_patcher = mock.patch.object(m, "_registry_lock", threading.Lock())
        self._slot_patcher.start()
        self._lock_patcher.start()
        self.addCleanup(self._slot_patcher.stop)
        self.addCleanup(self._lock_patcher.stop)

    def test_binding_exact_and_copy(self):
        result = m._validate_binding(dict(GOOD_BINDING))
        self.assertEqual(result, ("run-1", "a" * 64))
        self.assertIsInstance(result, tuple)
        b = dict(GOOD_BINDING)
        r = m._validate_binding(b)
        b["run_id"] = "changed"
        self.assertEqual(r[0], "run-1")

    def test_binding_rejects(self):
        class MyDict(dict):
            pass

        class MyStr(str):
            pass

        bad = [
            {"run_id": "x", "other": "a" * 64},
            {"run_id": "x", "candidate_sha256": "a" * 64, "extra": "y"},
            ["run_id", "candidate_sha256"],
            {"run_id": "", "candidate_sha256": "a" * 64},
            {"run_id": "x", "candidate_sha256": "A" * 64},
            {1: "x", "candidate_sha256": "a" * 64},
            MyDict({"run_id": "x", "candidate_sha256": "a" * 64}),
            {MyStr("run_id"): "x", "candidate_sha256": "a" * 64},
        ]
        for b in bad:
            with self.assertRaises(ValueError):
                m._validate_binding(b)

    def test_binding_custom_key_hash_eq_not_called_after_construction(self):
        calls = {"hash": 0, "eq": 0}

        class Evil:
            def __hash__(self):
                calls["hash"] += 1
                return 42

            def __eq__(self, other):
                calls["eq"] += 1
                return False

        d = {Evil(): "x", "candidate_sha256": "a" * 64}
        constructed = calls["hash"]
        with self.assertRaises(ValueError):
            m._validate_binding(d)
        self.assertEqual(calls["hash"], constructed)
        self.assertEqual(calls["eq"], 0)

    def test_clock_valid(self):
        self.assertEqual(m._validate_clock_sample(100, None, 1000), 100)
        self.assertEqual(m._validate_clock_sample(100, 100, 1000), 100)
        self.assertEqual(m._validate_clock_sample(200, 100, 1000), 200)

    def test_clock_rejects(self):
        class MyInt(int):
            pass

        bad = [
            (True, None, 1000),
            (1.0, None, 1000),
            (-1, None, 1000),
            (2 ** 63, None, 2 ** 63),
            (MyInt(100), None, 1000),
            (100, True, 1000),
            (50, 100, 1000),
            (1000, None, 1000),
            (2000, None, 1000),
        ]
        for args in bad:
            with self.assertRaises(ValueError):
                m._validate_clock_sample(*args)

    def test_slot_private_ctor_and_repr(self):
        with self.assertRaises(ValueError):
            m._CustodySlot(object())
        self.assertEqual(repr(m._CustodySlot(m._CUSTODY_TOKEN)), "<_CustodySlot nonauthorizing>")

    def test_api_identity_and_clock_never_called(self):
        calls = {"n": 0}

        def clock():
            calls["n"] += 1
            return 0

        api = object()
        slot = m._reserve_slot(api, dict(GOOD_BINDING), 1000, clock)
        self.assertIs(slot._api, api)
        self.assertEqual(calls["n"], 0)

    def test_deadline_zero_accepted(self):
        api = object()
        clock = lambda: 0
        slot = m._reserve_slot(api, dict(GOOD_BINDING), 0, clock)
        self.assertEqual(slot._deadline_ns, 0)
        self.assertEqual(slot._phase, "RESERVED")

    def test_invalid_api_and_retry_refused(self):
        api = object()
        clock = lambda: 0
        try:
            m._reserve_slot({}, dict(GOOD_BINDING), 1000, clock)
            self.fail("expected error")
        except m.CreationPreparationError as e:
            self.assertEqual(e.message, "INVALID_RESERVATION")
            self.assertIs(e.custody, m._registry_slot)
            self.assertEqual(m._registry_slot._phase, "QUARANTINED")
        try:
            m._reserve_slot(api, dict(GOOD_BINDING), 1000, clock)
            self.fail("expected error")
        except m.CreationPreparationError as e:
            self.assertEqual(e.message, "HELPER_ALREADY_RESERVED")
            self.assertIsNone(e.custody)
            self.assertEqual(m._registry_slot._phase, "QUARANTINED")

    def test_reservation_binding_copy_isolation(self):
        api = object()
        clock = lambda: 0
        b = dict(GOOD_BINDING)
        slot = m._reserve_slot(api, b, 1000, clock)
        b["run_id"] = "changed"
        self.assertEqual(slot._binding, ("run-1", "a" * 64))

    def test_error_repr_excludes_custody_api_binding(self):
        api = object()
        clock = lambda: 0
        try:
            m._reserve_slot(api, {"run_id": "x"}, 1000, clock)
            self.fail("expected error")
        except m.CreationPreparationError as e:
            r = repr(e)
            self.assertIn("INVALID_RESERVATION", r)
            self.assertNotIn("run-1", r)
            self.assertNotIn("a" * 64, r)
            self.assertNotIn(repr(api), r)
            self.assertNotIn(repr(e.custody), r)

    def test_invalid_consumes_slot_quarantined(self):
        api = object()
        clock = lambda: 0
        cases = [
            lambda: m._reserve_slot(api, {"run_id": "x"}, 1000, clock),
            lambda: m._reserve_slot(api, dict(GOOD_BINDING), "x", clock),
            lambda: m._reserve_slot(api, dict(GOOD_BINDING), True, clock),
            lambda: m._reserve_slot(api, dict(GOOD_BINDING), 2 ** 63, clock),
            lambda: m._reserve_slot(api, dict(GOOD_BINDING), 1000, "nope"),
            lambda: m._reserve_slot(None, dict(GOOD_BINDING), 1000, clock),
        ]
        for fn in cases:
            with self.subTest(), mock.patch.object(m, "_registry_slot", None):
                try:
                    fn()
                    self.fail("expected error")
                except m.CreationPreparationError as e:
                    self.assertEqual(e.message, "INVALID_RESERVATION")
                    self.assertIs(e.custody, m._registry_slot)
                    self.assertEqual(m._registry_slot._phase, "QUARANTINED")

    def test_duplicate_and_busy_custody_none(self):
        api = object()
        clock = lambda: 0
        incumbent = m._reserve_slot(api, dict(GOOD_BINDING), 1000, clock)
        try:
            m._reserve_slot(api, dict(GOOD_BINDING), 1000, clock)
            self.fail("expected error")
        except m.CreationPreparationError as e:
            self.assertEqual(e.message, "HELPER_ALREADY_RESERVED")
            self.assertIsNone(e.custody)
            self.assertIs(m._registry_slot, incumbent)
        m._registry_lock.acquire()
        try:
            try:
                m._reserve_slot(api, dict(GOOD_BINDING), 1000, clock)
                self.fail("expected error")
            except m.CreationPreparationError as e:
                self.assertEqual(e.message, "REGISTRY_BUSY")
                self.assertIsNone(e.custody)
        finally:
            m._registry_lock.release()

    def test_constructor_memoryerror_releases_lock(self):
        with mock.patch.object(m, "_CustodySlot", side_effect=MemoryError):
            with self.assertRaises(MemoryError):
                m._reserve_slot(object(), dict(GOOD_BINDING), 1000, lambda: 0)
        self.assertIsNone(m._registry_slot)
        self.assertFalse(m._registry_lock.locked())

    def test_keyboardinterrupt_keeps_quarantined_slot(self):
        with mock.patch.object(m, "_validate_binding", side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):
                m._reserve_slot(object(), dict(GOOD_BINDING), 1000, lambda: 0)
        self.assertIsNotNone(m._registry_slot)
        self.assertEqual(m._registry_slot._phase, "QUARANTINED")

    def test_concurrent_at_most_one_slot(self):
        api = object()
        clock = lambda: 0
        results = []
        errors = []
        barrier = threading.Barrier(4)

        def worker():
            try:
                barrier.wait(timeout=5)
                results.append(("ok", m._reserve_slot(api, dict(GOOD_BINDING), 1000, clock)))
            except m.CreationPreparationError as e:
                results.append(("err", e.custody))
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=worker, daemon=True) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)
        self.assertFalse(any(t.is_alive() for t in threads))
        self.assertEqual(errors, [])
        ok = [r for r in results if r[0] == "ok"]
        err = [r for r in results if r[0] == "err"]
        self.assertEqual(len(ok), 1)
        self.assertEqual(len(err), 3)
        for r in err:
            self.assertIsNone(r[1])
        self.assertIs(m._registry_slot, ok[0][1])

    def test_flags_false(self):
        for flag in ("AUTHORIZES_EXECUTION", "PLATFORM_QUALIFIED", "IMAGE_BYTES_ATTESTED",
                     "WORKSPACE_ATTESTED", "HARD_IO_TIMEOUT_PROVEN", "CLEANUP_CONFIRMED", "RETRY_AUTHORIZED"):
            self.assertIs(getattr(m, flag), False)

    def test_abi_and_config_fake_only(self):
        self.assertTrue(m.check_windows_abi())
        names = ("InitializeProcThreadAttributeList", "UpdateProcThreadAttribute",
                 "DeleteProcThreadAttributeList", "CreateProcessW",
                 "GetHandleInformation", "IsProcessInJob", "GetLastError")
        api = type("Api", (), {name: mock.Mock() for name in names})()
        self.assertTrue(m.configure_injected_prototypes(api))
        for name in names:
            self.assertIsNotNone(getattr(api, name).argtypes)
            getattr(api, name).assert_not_called()


TESTS_DIR = Path(__file__).resolve().parent
if str(TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(TESTS_DIR))
from test_v213_qa_capacity_control_windows import FakeJobAPI  # noqa: E402


class HelperJobAPI(FakeJobAPI):
    def __init__(self, **kw):
        kw.setdefault("clock_values", [10**9 * i for i in range(1, 100)])
        super().__init__(**kw)
        for name in ("InitializeProcThreadAttributeList", "UpdateProcThreadAttribute",
                     "DeleteProcThreadAttributeList", "CreateProcessW",
                     "IsProcessInJob", "GetLastError"):
            def raise_if_called(*args, _name=name, **kwargs):
                raise AssertionError("helper method called: " + _name)
            raise_if_called.argtypes = []
            raise_if_called.restype = None
            setattr(self, name, raise_if_called)
        self.GetHandleInformation.argtypes = []
        self.GetHandleInformation.restype = None


class HelperBeginTest(unittest.TestCase):
    def setUp(self):
        self._slot_patcher = mock.patch.object(m, "_registry_slot", None)
        self._lock_patcher = mock.patch.object(m, "_registry_lock", threading.Lock())
        self._slot_patcher.start()
        self._lock_patcher.start()
        self.addCleanup(self._slot_patcher.stop)
        self.addCleanup(self._lock_patcher.stop)

    def _binding(self):
        return {"run_id": "run-1", "candidate_sha256": "a" * 64}

    def test_success_private_owner_retained(self):
        api = HelperJobAPI()
        owner = m.begin_owned_creation(api, self._binding(), 10**18, api.clock)
        self.assertIs(type(owner), m.CreationOwner)
        self.assertIs(owner._slot._api, api)
        self.assertIs(type(owner._slot._job), m.RetainedContainmentJob)
        self.assertEqual(owner._slot._phase, "JOB_READY_UNQUALIFIED")
        names = [e[0] for e in api.trace]
        self.assertEqual(names.count("CreateJobObjectW"), 1)
        self.assertEqual(names.count("CloseHandle"), 0)
        self.assertFalse(hasattr(owner, "close"))
        self.assertFalse(hasattr(owner, "job"))

    def test_expired_clock_before_injected_calls(self):
        api = HelperJobAPI(clock_values=[10**18])
        try:
            m.begin_owned_creation(api, self._binding(), 10**18, api.clock)
            self.fail("expected error")
        except m.CreationPreparationError as e:
            self.assertEqual(e.message, "JOB_SETUP_UNQUALIFIED")
        self.assertEqual(api.trace, [])

    def test_pre_return_factory_failure_unknown(self):
        api = HelperJobAPI(create_exc=RuntimeError("create failed"))
        try:
            m.begin_owned_creation(api, self._binding(), 10**18, api.clock)
            self.fail("expected error")
        except m.CreationPreparationError as e:
            self.assertEqual(e.message, "JOB_ACQUISITION_OR_RELEASE_UNCONFIRMED")
            self.assertIs(e.custody, m._registry_slot)
        self.assertEqual(m._registry_slot._phase, "QUARANTINED")
        self.assertIsNone(m._registry_slot._job)

    def test_rounding_near_max_clock_conservative_refusal(self):
        api = HelperJobAPI(clock_values=[2**63 - 2, 2**63 - 2])
        try:
            m.begin_owned_creation(api, self._binding(), 2**63 - 1, api.clock)
            self.fail("expected error")
        except m.CreationPreparationError as e:
            self.assertEqual(e.message, "JOB_ACQUISITION_OR_RELEASE_UNCONFIRMED")
        self.assertEqual(api.trace, [])

    def test_duplicate_begin_custody_none(self):
        api = HelperJobAPI()
        first = m.begin_owned_creation(api, self._binding(), 10**18, api.clock)
        try:
            m.begin_owned_creation(api, self._binding(), 10**18, api.clock)
            self.fail("expected error")
        except m.CreationPreparationError as e:
            self.assertEqual(e.message, "HELPER_ALREADY_RESERVED")
            self.assertIsNone(e.custody)
        self.assertIs(m._registry_slot, first._slot)
        self.assertEqual([e[0] for e in api.trace].count("CreateJobObjectW"), 1)


class HelperBeginFaultTest(unittest.TestCase):
    setUp = HelperBeginTest.setUp

    def _fresh(self):
        return mock.patch.object(m, "_registry_slot", None)

    def _assert_unqualified(self):
        self.assertEqual(m._registry_slot._phase, "QUARANTINED")
        for key in ("AUTHORIZES_EXECUTION", "PLATFORM_QUALIFIED", "IMAGE_BYTES_ATTESTED",
                    "WORKSPACE_ATTESTED", "HARD_IO_TIMEOUT_PROVEN", "CLEANUP_CONFIRMED", "RETRY_AUTHORIZED"):
            self.assertIs(getattr(m, key), False)

    def test_post_return_late_and_interrupt_keep_original_job(self):
        original = m.create_containment_job
        for mode in ("late", "interrupt"):
            with self.subTest(mode=mode), self._fresh():
                api = HelperJobAPI()
                returned = []
                def clock():
                    if returned:
                        if mode == "interrupt":
                            raise KeyboardInterrupt()
                        return 1000
                    return 100
                def factory(*args, **kwargs):
                    job = original(*args, **kwargs)
                    returned.append(job)
                    return job
                error_type = KeyboardInterrupt if mode == "interrupt" else m.CreationPreparationError
                with mock.patch.object(m, "create_containment_job", side_effect=factory):
                    with self.assertRaises(error_type) as caught:
                        m.begin_owned_creation(api, dict(GOOD_BINDING), 1000, clock)
                self.assertIs(m._registry_slot._job, returned[0])
                if mode == "late":
                    self.assertIs(caught.exception.custody, m._registry_slot)
                    self.assertEqual(str(caught.exception), "JOB_SETUP_UNQUALIFIED")
                self._assert_unqualified()
                self.assertNotIn("CloseHandle", [e[0] for e in api.trace])

    def test_fault_injected_returned_object_never_ready(self):
        original = m.create_containment_job
        faults = [("type", None), ("_api", object()), ("_closed", True),
                  ("_cleanup_failed", True), ("_observed_limit_flags", 0)]
        for field, value in faults:
            with self.subTest(field=field), self._fresh():
                api = HelperJobAPI()
                returned = []
                def factory(*args, **kwargs):
                    if field == "type":
                        job = object()  # Boundary injection, not an E1 success proof.
                    else:
                        job = original(*args, **kwargs)
                        object.__setattr__(job, field, value)
                    returned.append(job)
                    return job
                with mock.patch.object(m, "create_containment_job", side_effect=factory):
                    with self.assertRaises(m.CreationPreparationError) as caught:
                        m.begin_owned_creation(api, dict(GOOD_BINDING), 1000, lambda: 100)
                self.assertIs(m._registry_slot._job, returned[0])
                self.assertIs(caught.exception.custody, m._registry_slot)
                self.assertEqual(str(caught.exception), "JOB_SETUP_UNQUALIFIED")
                self._assert_unqualified()
                self.assertNotIn("CloseHandle", [e[0] for e in api.trace])

    def test_actual_e1_cleanup_failure_stays_unknown_and_spent(self):
        api = HelperJobAPI(get_handle_info=False, close_ok=False)
        with self.assertRaises(m.CreationPreparationError) as caught:
            m.begin_owned_creation(api, dict(GOOD_BINDING), 1000, lambda: 100)
        slot = m._registry_slot
        self.assertEqual(str(caught.exception), "JOB_ACQUISITION_OR_RELEASE_UNCONFIRMED")
        self.assertIs(caught.exception.custody, slot)
        self.assertIsNone(slot._job)
        self.assertEqual([e[0] for e in api.trace].count("CloseHandle"), 1)
        self._assert_unqualified()
        with self.assertRaises(m.CreationPreparationError) as duplicate:
            m.begin_owned_creation(api, dict(GOOD_BINDING), 1000, lambda: 100)
        self.assertIsNone(duplicate.exception.custody)
        self.assertIs(m._registry_slot, slot)
        self.assertEqual([e[0] for e in api.trace].count("CreateJobObjectW"), 1)

    def test_strict_clock_failures_before_job_calls(self):
        for values in ([True], [1.0], [-1], [2**63], [100, 99]):
            with self.subTest(values=values), self._fresh():
                api = HelperJobAPI()
                samples = iter(values)
                with self.assertRaises(m.CreationPreparationError):
                    m.begin_owned_creation(api, dict(GOOD_BINDING), 1000, lambda: next(samples))
                self._assert_unqualified()
                self.assertEqual(api.trace, [])
                self.assertEqual(m._registry_slot._last_ns, 100 if len(values) == 2 else None)
        with self._fresh():
            api = HelperJobAPI()
            def broken_clock():
                raise RuntimeError("DO_NOT_ECHO_CLOCK_DETAIL")
            with self.assertRaises(m.CreationPreparationError) as caught:
                m.begin_owned_creation(api, dict(GOOD_BINDING), 1000, broken_clock)
            self.assertEqual(str(caught.exception), "JOB_SETUP_UNQUALIFIED")
            self._assert_unqualified()
            self.assertEqual(api.trace, [])

    def test_reentrant_begin_cannot_get_custody_or_second_job(self):
        api = HelperJobAPI()
        attempted = []
        def clock():
            if not attempted:
                attempted.append(True)
                with self.assertRaises(m.CreationPreparationError) as rejected:
                    m.begin_owned_creation(api, dict(GOOD_BINDING), 1000, clock)
                self.assertIsNone(rejected.exception.custody)
                self.assertEqual(str(rejected.exception), "HELPER_ALREADY_RESERVED")
            return 100
        owner = m.begin_owned_creation(api, dict(GOOD_BINDING), 1000, clock)
        self.assertIs(owner._slot, m._registry_slot)
        self.assertEqual([e[0] for e in api.trace].count("CreateJobObjectW"), 1)
        self.assertNotIn("CloseHandle", [e[0] for e in api.trace])


class HelperValidatorTest(unittest.TestCase):
    def test_creation_path_normalized(self):
        self.assertEqual(m._validate_creation_path("C:/dir/app.EXE", True), "C:\\dir\\app.EXE")
        self.assertEqual(m._validate_creation_path("C:/", False), "C:\\")

    def test_creation_path_rejected(self):
        class MyStr(str):
            __hash__ = str.__hash__
        bad = [
            ("", False),
            (MyStr("C:\\dir\\app.exe"), True),
            ("C:\\dir\\\x00app.exe", True),
            ("C:\\dir\\\u00adapp.exe", True),
            ("C:\\dir\\" + chr(0xD800) + "app.exe", True),
            ("dir\\app.exe", True),
            ("\\\\server\\share\\x.exe", True),
            ("\\.\\pipe\\x.exe", True),
            ("C:\\dir\\app.exe:ads", True),
            ("C:\\dir\\..\\app.exe", True),
            ("C:\\dir\\CON.exe", True),
            ("C:\\dir\\.exe", True),
            ("C:\\", True),
            ("C:\\dir\\app.cmd", True),
        ]
        for value, exe in bad:
            with self.subTest(value=repr(value)):
                with self.assertRaises(ValueError) as ctx:
                    m._validate_creation_path(value, exe)
                self.assertEqual(str(ctx.exception), "INVALID_CREATION_PATH")

    def test_creation_path_utf16_boundary(self):
        base = "C:\\" + chr(0x10400) * 508 + "a.exe"
        self.assertEqual(len(base.encode("utf-16-le")) // 2, 1024)
        self.assertEqual(m._validate_creation_path(base, True), base)
        with self.assertRaises(ValueError):
            m._validate_creation_path("C:\\" + chr(0x10400) * 508 + "ab.exe", True)
        with self.assertRaises(ValueError):
            m._validate_creation_path("C:\\" + chr(0x10400) * 509 + "a.exe", True)

    def test_stdio_none_empty(self):
        self.assertEqual(m._validate_stdio(None, 0x1000), ())
        self.assertEqual(m._validate_stdio({}, 0x1000), ())

    def test_stdio_role_order_copy_isolation(self):
        d = {"stdin": 4, "stdout": 8, "stderr": 12}
        result = m._validate_stdio(d, 0x1000)
        self.assertEqual(result, (4, 8, 12))
        d["stdin"] = 999
        self.assertEqual(result, (4, 8, 12))

    def test_stdio_stdout_eq_stderr_allowed(self):
        self.assertEqual(m._validate_stdio({"stdin": 4, "stdout": 8, "stderr": 8}, 0x1000), (4, 8, 8))

    def test_stdio_rejected(self):
        class MyStr(str):
            __hash__ = str.__hash__
        class MyInt(int):
            pass
        class MyDict(dict):
            pass
        bad = [
            {"stdin": 4, "stdout": 4, "stderr": 12},
            {"stdin": 4, "stdout": 0x1000, "stderr": 12},
            {"stdin": True, "stdout": 8, "stderr": 12},
            {"stdin": MyInt(4), "stdout": 8, "stderr": 12},
            {"stdin": 0, "stdout": 8, "stderr": 12},
            {"stdin": -4, "stdout": 8, "stderr": 12},
            {"stdin": 1, "stdout": 8, "stderr": 12},
            {"stdin": 2, "stdout": 8, "stderr": 12},
            {"stdin": 3, "stdout": 8, "stderr": 12},
            {"stdin": 0x1001, "stdout": 8, "stderr": 12},
            {"stdin": 0x1002, "stdout": 8, "stderr": 12},
            {"stdin": 0x1003, "stdout": 8, "stderr": 12},
            {"stdin": 0xFFFFFFFF, "stdout": 8, "stderr": 12},
            {"stdin": 0xFFFFFFFE, "stdout": 8, "stderr": 12},
            {"stdin": 2**31, "stdout": 8, "stderr": 12},
            {"stdin": 2**63, "stdout": 8, "stderr": 12},
            {"stdin": 2**64 - 1, "stdout": 8, "stderr": 12},
            {"stdin": 0x100000004, "stdout": 8, "stderr": 12},
            MyDict({"stdin": 4, "stdout": 8, "stderr": 12}),
            {"stdin": 4, "stdout": 8, "stderr": 12, "extra": 16},
            {"stdin": 4, "stdout": 8},
            {MyStr("stdin"): 4, "stdout": 8, "stderr": 12},
        ]
        for value in bad:
            with self.subTest(value=repr(value)):
                with self.assertRaises(ValueError) as ctx:
                    m._validate_stdio(value, 0x1000)
                self.assertEqual(str(ctx.exception), "INVALID_STDIO")

    def test_stdio_nonbuiltin_str_key_before_eq(self):
        class MyStr(str):
            __hash__ = str.__hash__
            eq_calls = 0
            def __eq__(self, other):
                MyStr.eq_calls += 1
                return super().__eq__(other)
        try:
            m._validate_stdio({MyStr("stdin"): 4, "stdout": 8, "stderr": 12}, 0x1000)
            self.fail("expected error")
        except ValueError:
            pass
        self.assertEqual(MyStr.eq_calls, 0)

    def test_stdio_max_aligned(self):
        self.assertEqual(m._validate_stdio({"stdin": 2**31 - 4, "stdout": 8, "stderr": 12}, 0x1000),
                         (2**31 - 4, 8, 12))

    def test_stdio_invalid_job_before_eq(self):
        class MyInt(int):
            eq_calls = 0
            def __eq__(self, other):
                MyInt.eq_calls += 1
                return super().__eq__(other)
        for job in (MyInt(0x1001), MyInt(0), MyInt(2**31), "not_int"):
            with self.subTest(job=repr(job)):
                try:
                    m._validate_stdio({"stdin": 4, "stdout": 8, "stderr": 12}, job)
                    self.fail("expected error")
                except ValueError:
                    pass
        self.assertEqual(MyInt.eq_calls, 0)

    def test_flags_false(self):
        for flag in ("AUTHORIZES_EXECUTION", "PLATFORM_QUALIFIED", "IMAGE_BYTES_ATTESTED",
                     "WORKSPACE_ATTESTED", "HARD_IO_TIMEOUT_PROVEN", "CLEANUP_CONFIRMED", "RETRY_AUTHORIZED"):
            self.assertIs(getattr(m, flag), False)


class HelperPreparationAPI(HelperJobAPI):
    """Injected kernel-handle model only; no live adapter or lease proof."""
    def __init__(self, faults=(), stdio_flags=1):
        super().__init__(handle=0x1000)
        self.events, self.faults = [], set(faults)
        self.stdio_flags, self.initialized = stdio_flags, False
        original_get = self.GetHandleInformation
        def unlocked():
            assert not m._registry_lock.locked()
            assert not m._registry_slot._lock.locked()
        def init(buf, count, flags, size_ptr):
            unlocked()
            assert count in (1, 2) and flags == 0
            self.events.append(("init", buf is None, count))
            size = m.ctypes.cast(size_ptr, m.ctypes.POINTER(m.SIZE_T))
            if buf is None:
                size.contents.value = 0 if "zero_size" in self.faults else (65537 if "oversize" in self.faults else 128)
                return 1 if "size_success" in self.faults else 0
            assert m.ctypes.cast(buf, m.PVOID).value == m.ctypes.addressof(m._registry_slot._attribute_storage)
            if "init_false" in self.faults:
                return 0
            self.initialized = True
            if "resized" in self.faults:
                size.contents.value = 129
            return 1
        def error():
            self.events.append(("error",))
            return 123 if "bad_error" in self.faults else 122
        def update(ptr, flags, key, values, size, previous, returned):
            unlocked()
            assert flags == 0 and previous is None and returned is None
            assert m.ctypes.cast(ptr, m.PVOID).value == m.ctypes.addressof(m._registry_slot._attribute_storage)
            assert key in (m.JOB_LIST, m.HANDLE_LIST) and size % m.ctypes.sizeof(m.HANDLE) == 0
            array = m.ctypes.cast(values, m.ctypes.POINTER(m.HANDLE))
            actual = tuple(array[i] for i in range(size // m.ctypes.sizeof(m.HANDLE)))
            self.events.append(("update", key, actual, size))
            return 0 if (key == m.JOB_LIST and "update_job" in self.faults) or (key == m.HANDLE_LIST and "update_stdio" in self.faults) else 1
        def delete(ptr):
            unlocked()
            assert m.ctypes.cast(ptr, m.PVOID).value == m.ctypes.addressof(m._registry_slot._attribute_storage)
            self.events.append(("delete",))
            if "delete_raise" in self.faults:
                raise RuntimeError("FAKE_DELETE_FAILURE")
            return False  # A completed void call, NOT a BOOL failure.
        def get_flags(handle, flags_ptr):
            unlocked()
            self.events.append(("flags", handle))
            if handle == self.handle_value:
                return original_get(handle, m.ctypes.cast(flags_ptr, m.PDWORD))
            assert handle in (4, 8, 12)
            m.ctypes.cast(flags_ptr, m.PDWORD).contents.value = self.stdio_flags
            return 1
        for name, fn in (("InitializeProcThreadAttributeList", init), ("GetLastError", error),
                         ("UpdateProcThreadAttribute", update), ("DeleteProcThreadAttributeList", delete),
                         ("GetHandleInformation", get_flags)):
            fn.argtypes, fn.restype = [], None
            setattr(self, name, fn)
    def clock(self):
        assert not m._registry_lock.locked() and not m._registry_slot._lock.locked()
        self.events.append(("clock",))
        if self.initialized:
            assert m._registry_slot._attributes_initialized  # Set BEFORE post-Init observation.
            if "interrupt_after_init" in self.faults:
                raise KeyboardInterrupt()
            if "late_after_init" in self.faults:
                return 1000
        return 100


class HelperPreparationTest(unittest.TestCase):
    setUp = HelperPureTest.setUp
    def _owner(self, api):
        return m.begin_owned_creation(api, dict(GOOD_BINDING), 1000, api.clock)
    def _flags_false(self):
        for name in ("AUTHORIZES_EXECUTION", "PLATFORM_QUALIFIED", "IMAGE_BYTES_ATTESTED",
                     "WORKSPACE_ATTESTED", "HARD_IO_TIMEOUT_PROVEN", "CLEANUP_CONFIRMED", "RETRY_AUTHORIZED"):
            self.assertIs(getattr(m, name), False)
    def test_public_prepare_pointed_layout_and_order(self):
        for stdio in (None, {"stdin": 4, "stdout": 8, "stderr": 12}, {"stdin": 4, "stdout": 8, "stderr": 8}):
            with self.subTest(stdio=stdio), mock.patch.object(m, "_registry_slot", None):
                api = HelperPreparationAPI(); owner = self._owner(api)
                prepared = owner.prepare_once("C:/fake/app.EXE", "C:/", stdio)
                slot = owner._slot
                self.assertIs(prepared._slot, slot); self.assertIs(m._registry_slot, slot)
                self.assertEqual(slot._phase, "PREPARED_UNQUALIFIED")
                self.assertEqual((slot._executable, slot._cwd), ("C:\\fake\\app.EXE", "C:\\"))
                self.assertEqual(bytes(slot._environment), b"\0\0"); self.assertEqual(m.ctypes.sizeof(slot._environment), 2)
                info = slot._startup_info.StartupInfo
                self.assertEqual(info.cb, 112)
                self.assertEqual(info.dwFlags, m.STARTF_USESTDHANDLES if stdio else 0)
                self.assertEqual((info.hStdInput, info.hStdOutput, info.hStdError), tuple(stdio[k] for k in ("stdin", "stdout", "stderr")) if stdio else (None, None, None))
                self.assertEqual(slot._startup_info.lpAttributeList, m.ctypes.addressof(slot._attribute_storage))
                self.assertEqual((slot._process_info.hProcess, slot._process_info.hThread, slot._process_info.dwProcessId, slot._process_info.dwThreadId), (None, None, 0, 0))
                calls = [e for e in api.events if e[0] == "update"]
                expected = [("update", m.JOB_LIST, (0x1000,), 8)]
                if stdio:
                    values = tuple(dict.fromkeys(stdio[k] for k in ("stdin", "stdout", "stderr")))
                    expected.append(("update", m.HANDLE_LIST, values, 8 * len(values)))
                self.assertEqual(calls, expected)
                self.assertEqual([e[2] for e in api.events if e[0] == "init"], [len(expected)] * 2)
                index = api.events.index(("init", True, len(expected)))
                self.assertEqual(api.events[index + 1], ("error",))
                self.assertFalse(slot._attribute_delete_attempted)
                self.assertTrue(callable(prepared.invoke_once)); self.assertFalse(hasattr(prepared, "close"))
                before = list(api.events)
                with self.assertRaises(m.CreationPreparationError) as duplicate:
                    owner.prepare_once("C:/fake/app.exe", "C:/", stdio)
                self.assertIsNone(duplicate.exception.custody); self.assertEqual(api.events, before)
                self.assertNotIn("CloseHandle", [e[0] for e in api.trace]); self._flags_false()

    def test_initialization_update_and_delete_failure_matrix(self):
        cases = [("size_success",), ("bad_error",), ("zero_size",), ("oversize",), ("init_false",),
                 ("resized",), ("update_job",), ("update_stdio",), ("late_after_init",),
                 ("interrupt_after_init",), ("update_job", "delete_raise")]
        for faults in cases:
            with self.subTest(faults=faults), mock.patch.object(m, "_registry_slot", None):
                api = HelperPreparationAPI(faults); owner = self._owner(api); job = owner._slot._job
                error = KeyboardInterrupt if "interrupt_after_init" in faults else m.CreationPreparationError
                with self.assertRaises(error) as caught:
                    owner.prepare_once("C:/fake/app.exe", "C:/", {"stdin": 4, "stdout": 8, "stderr": 8})
                first = ("init", True, 2)
                self.assertIn(first, api.events)
                if faults[0] != "size_success":
                    self.assertEqual(api.events[api.events.index(first) + 1], ("error",))
                if faults[0] not in ("size_success", "bad_error", "zero_size", "oversize"):
                    self.assertIn(("init", False, 2), api.events)
                if faults[0] in ("update_job", "update_stdio"):
                    key = m.JOB_LIST if faults[0] == "update_job" else m.HANDLE_LIST
                    self.assertTrue(any(e[0] == "update" and e[1] == key for e in api.events))
                slot = m._registry_slot
                self.assertIs(slot._job, job); self.assertTrue(slot._prepare_spent)
                self.assertEqual(slot._phase, "QUARANTINED")
                if error is m.CreationPreparationError:
                    self.assertIs(caught.exception.custody, slot)
                    self.assertEqual(str(caught.exception), "PREPARATION_UNQUALIFIED")
                initialized = faults[0] in ("resized", "update_job", "update_stdio", "late_after_init", "interrupt_after_init")
                self.assertEqual(slot._attributes_initialized, initialized)
                self.assertEqual(api.events.count(("delete",)), 1 if initialized else 0)
                self.assertEqual(slot._attribute_delete_unknown, "delete_raise" in faults)
                self.assertEqual(slot._attribute_delete_completed, initialized and "delete_raise" not in faults)
                if faults[0] not in ("size_success", "bad_error", "zero_size", "oversize"):
                    self.assertIsNotNone(slot._attribute_storage)
                self.assertEqual(bytes(slot._environment), b"\0\0")
                self.assertEqual(list(slot._attribute_values[0]), [0x1000])
                before = list(api.events)
                with self.assertRaises(m.CreationPreparationError) as retry:
                    owner.prepare_once("C:/fake/app.exe", "C:/")
                self.assertIsNone(retry.exception.custody); self.assertEqual(api.events, before)
                del caught
                self.assertIs(m._registry_slot, slot)
                self.assertNotIn("CloseHandle", [e[0] for e in api.trace]); self._flags_false()

    def test_pre_attribute_refusals_remain_spent(self):
        for fault in ("path", "stdio_flags", "job_flags", "closed", "unsupported_job"):
            with self.subTest(fault=fault), mock.patch.object(m, "_registry_slot", None):
                api = HelperPreparationAPI(stdio_flags=3 if fault == "stdio_flags" else 1)
                owner = self._owner(api); job = owner._slot._job
                if fault == "job_flags": api.handle_flags = 1
                if fault == "closed": object.__setattr__(job, "_closed", True)
                if fault == "unsupported_job": object.__setattr__(job, "_handle", 0x1001)
                with self.assertRaises(m.CreationPreparationError):
                    owner.prepare_once("C:/fake/app.cmd" if fault == "path" else "C:/fake/app.exe", "C:/", {"stdin": 4, "stdout": 8, "stderr": 8})
                self.assertTrue(owner._slot._prepare_spent); self.assertEqual(owner._slot._phase, "QUARANTINED")
                self.assertIs(owner._slot._job, job)
                self.assertFalse(any(e[0] in ("init", "update", "delete") for e in api.events))
                self.assertNotIn("CloseHandle", [e[0] for e in api.trace]); self._flags_false()

    def test_concurrent_and_reentrant_prepare_make_one_list(self):
        api = HelperPreparationAPI(); owner = self._owner(api)
        entered, release = threading.Event(), threading.Event()
        original = api.InitializeProcThreadAttributeList
        results = []
        def sizing(buf, *args):
            if buf is None:
                with self.assertRaises(m.CreationPreparationError) as reentrant:
                    owner.prepare_once("C:/fake/app.exe", "C:/")
                self.assertIsNone(reentrant.exception.custody)
                entered.set()
                if not release.wait(3): raise RuntimeError("FAKE_WAIT_TIMEOUT")
            return original(buf, *args)
        def worker():
            try: results.append(owner.prepare_once("C:/fake/app.exe", "C:/"))
            except BaseException as error: results.append(error)
        with mock.patch.object(api, "InitializeProcThreadAttributeList", side_effect=sizing):
            thread = threading.Thread(target=worker, daemon=True); thread.start()
            try:
                self.assertTrue(entered.wait(3))
                with self.assertRaises(m.CreationPreparationError) as concurrent:
                    owner.prepare_once("C:/fake/app.exe", "C:/")
                self.assertIsNone(concurrent.exception.custody)
            finally:
                release.set(); thread.join(3)
            self.assertFalse(thread.is_alive())
        self.assertEqual(len(results), 1); self.assertIs(type(results[0]), m.PreparedCreation)
        self.assertEqual([e for e in api.events if e[0] == "init"], [("init", True, 1), ("init", False, 1)])
        self.assertNotIn("CloseHandle", [e[0] for e in api.trace]); self._flags_false()


class HelperInvocationAPI(HelperPreparationAPI):
    """Fake injected invocation only; no native process or suspension proof."""
    def __init__(self, outputs=(0x2000, 0x2004, 101, 103), result=1, faults=()):
        super().__init__(faults)
        self.outputs, self.result = outputs, result
        self.created, self.deleted = False, False
        self.written, self.on_create = None, None
        self.capture_checks = 0
        original_delete = self.DeleteProcThreadAttributeList
        def create(app, command, process_sa, thread_sa, inherit, flags, env, cwd, startup, pi_ptr):
            slot = m._registry_slot
            assert not slot._lock.locked() and not m._registry_lock.locked()
            assert slot._invoke_spent and slot._create_entered
            assert app == slot._executable and cwd == slot._cwd
            assert command is None and process_sa is None and thread_sa is None
            assert inherit is bool(slot._stdio) and flags == 0x80004
            assert m.ctypes.cast(env, m.PVOID).value == m.ctypes.addressof(slot._environment)
            assert m.ctypes.string_at(env, 2) == b"\0\0" and m.ctypes.sizeof(slot._environment) == 2
            assert type(startup) is m.LPSTARTUPINFOW
            assert m.ctypes.cast(startup, m.PVOID).value == m.ctypes.addressof(slot._startup_info)
            ex = m.ctypes.cast(startup, m.ctypes.POINTER(m.STARTUPINFOEXW)).contents
            assert ex.StartupInfo.cb == 112 and ex.lpAttributeList == m.ctypes.addressof(slot._attribute_storage)
            assert m.ctypes.cast(pi_ptr, m.PVOID).value == m.ctypes.addressof(slot._process_info)
            info = ex.StartupInfo
            assert info.dwFlags == (m.STARTF_USESTDHANDLES if self.expected_stdio else 0)
            assert (info.hStdInput, info.hStdOutput, info.hStdError) == (self.expected_stdio or (None, None, None))
            assert info.lpReserved is None and info.lpDesktop is None and info.lpTitle is None
            assert not info.lpReserved2
            for name in ("dwX", "dwY", "dwXSize", "dwYSize", "dwXCountChars", "dwYCountChars", "dwFillAttribute", "wShowWindow", "cbReserved2"):
                assert getattr(info, name) == 0
            assert len(slot._attribute_values) == (2 if self.expected_stdio else 1)
            assert tuple(slot._attribute_values[0]) == (self.handle_value,)
            if self.expected_stdio:
                assert tuple(slot._attribute_values[1]) == tuple(dict.fromkeys(self.expected_stdio))
            pi = m.ctypes.cast(pi_ptr, m.LPPROCESS_INFORMATION).contents
            assert (pi.hProcess, pi.hThread, pi.dwProcessId, pi.dwThreadId) == (None, None, 0, 0)
            self.events.append(("create",))
            if self.on_create is not None: self.on_create()
            pi.hProcess, pi.hThread, pi.dwProcessId, pi.dwThreadId = self.outputs
            self.written = (pi.hProcess, pi.hThread, pi.dwProcessId, pi.dwThreadId)
            self.created = True
            if "create_raise" in self.faults: raise RuntimeError("FAKE_CREATE_FAILURE")
            if "create_interrupt" in self.faults: raise KeyboardInterrupt()
            return self.result
        def membership(process, job, result_ptr):
            self._capture_observed()
            assert process == m._registry_slot._original_process_handle and job == self.handle_value
            assert not m._registry_slot._lock.locked()
            self.events.append(("membership",))
            if "membership_raise" in self.faults: raise RuntimeError("FAKE_MEMBERSHIP_FAILURE")
            if "membership_interrupt" in self.faults: raise KeyboardInterrupt()
            m.ctypes.cast(result_ptr, m.PBOOL).contents.value = 0 if "membership_false" in self.faults else (2 if "membership_bad_output" in self.faults else 1)
            if "membership_api_false" in self.faults: return 0
            return True if "membership_bad_return" in self.faults else 1
        def delete(ptr):
            self._capture_observed()
            self.events.append(("delete_enter",))
            if "delete_interrupt" in self.faults: raise KeyboardInterrupt()
            result = original_delete(ptr)
            self.deleted = True
            return result
        for name, fn in (("CreateProcessW", create), ("IsProcessInJob", membership), ("DeleteProcThreadAttributeList", delete)):
            fn.argtypes, fn.restype = [], None
            setattr(self, name, fn)
    def _capture_observed(self):
        slot = m._registry_slot
        success = self.created and type(self.result) is int and self.result != 0 and not ({"create_raise", "create_interrupt"} & self.faults)
        assert slot._create_returned_success is success
        originals = (slot._original_process_handle, slot._original_thread_handle, slot._original_process_id, slot._original_thread_id)
        assert originals == (self.written if success else (None, None, None, None))
        if self.created: self.capture_checks += 1
    def clock(self):
        value = super().clock()
        slot = m._registry_slot
        if "pre_expired" in self.faults and slot._phase == "INVOKING" and not self.created: return 1000
        if self.created:
            self._capture_observed()
            if "post_interrupt" in self.faults: raise KeyboardInterrupt()
            if "post_expired" in self.faults: return 1000
            if "post_regression" in self.faults: return 99
            if "post_bool" in self.faults: return True
            if "post_overflow" in self.faults: return 2**63
            if self.deleted and "delete_late" in self.faults: return 1000
        return value


class HelperInvocationTest(unittest.TestCase):
    setUp = HelperPureTest.setUp
    _flags_false = HelperPreparationTest._flags_false
    def _prepared(self, api, stdio=None):
        api.expected_stdio = tuple(stdio[k] for k in ("stdin", "stdout", "stderr")) if stdio else ()
        owner = m.begin_owned_creation(api, dict(GOOD_BINDING), 1000, api.clock)
        return owner.prepare_once("C:/fake/app.exe", "C:/", stdio)
    def _retained(self, api, slot):
        self.assertIs(m._registry_slot, slot)
        self.assertIsNotNone(slot._job); self.assertIsNotNone(slot._attribute_storage)
        self.assertEqual(bytes(slot._environment), b"\0\0")
        self.assertEqual(api.events.count(("delete_enter",)), 1)
        self.assertNotIn("CloseHandle", [e[0] for e in api.trace])
        self._flags_false()
    def test_success_wire_capture_outcome_and_duplicate(self):
        for stdio in (None, {"stdin": 4, "stdout": 8, "stderr": 12}, {"stdin": 4, "stdout": 8, "stderr": 8}):
            with self.subTest(stdio=stdio), mock.patch.object(m, "_registry_slot", None):
                api = HelperInvocationAPI(); prepared = self._prepared(api, stdio); slot = prepared._slot
                outcome = prepared.invoke_once()
                self.assertIs(type(outcome), m.CreationOutcome); self.assertIs(outcome._slot, slot)
                self.assertEqual(outcome.status, "CREATED_SUSPENDED_CUSTODY_RETAINED")
                self.assertEqual(slot._phase, outcome.status); self.assertTrue(slot._create_returned_success)
                self.assertGreater(api.capture_checks, 0); self.assertEqual(api.events.count(("create",)), 1)
                self.assertEqual(api.events.count(("membership",)), 1); self.assertTrue(slot._attribute_delete_completed)
                with self.assertRaises(TypeError): bool(outcome)
                with self.assertRaises(AttributeError): outcome.status = "PERMIT"
                with self.assertRaises(ValueError): m.CreationOutcome(object())
                self.assertFalse(hasattr(outcome, "close")); self.assertFalse(hasattr(outcome, "handle"))
                before = list(api.events)
                with self.assertRaises(m.CreationInvocationError) as duplicate: prepared.invoke_once()
                self.assertIsNone(duplicate.exception.custody); self.assertEqual(api.events, before)
                self._retained(api, slot)
    def test_false_malformed_and_exception_outputs_not_owned(self):
        for result, fault in ((0, None), (True, None), (None, None), (1, "create_raise"), (1, "create_interrupt")):
            with self.subTest(result=result, fault=fault), mock.patch.object(m, "_registry_slot", None):
                api = HelperInvocationAPI(result=result, faults=() if fault is None else (fault,))
                prepared = self._prepared(api); slot = prepared._slot
                error = KeyboardInterrupt if fault == "create_interrupt" else m.CreationInvocationError
                with self.assertRaises(error): prepared.invoke_once()
                self.assertEqual(api.events.count(("create",)), 1); self.assertNotIn(("membership",), api.events)
                self.assertFalse(slot._create_returned_success)
                self.assertEqual((slot._original_process_handle, slot._original_thread_handle, slot._original_process_id, slot._original_thread_id), (None, None, None, None))
                self.assertEqual((slot._process_info.hProcess, slot._process_info.hThread, slot._process_info.dwProcessId, slot._process_info.dwThreadId), api.written)
                self.assertEqual(slot._phase, "QUARANTINED"); self._retained(api, slot)
    def test_invalid_success_outputs_retained_before_delete(self):
        cases = [(0, 0x2004, 101, 103), (0x2000, 0, 101, 103), (0x2000, 0x2000, 101, 103),
                 (0x1000, 0x2004, 101, 103), (4, 0x2004, 101, 103), (0x2001, 0x2004, 101, 103),
                 (0x100002000, 0x2004, 101, 103), (2**64-1, 0x2004, 101, 103),
                 (0x2000, 0x2004, 0, 103), (0x2000, 0x2004, 101, 0), (0x2000, 0x2004, 101, 101)]
        for outputs in cases:
            with self.subTest(outputs=outputs), mock.patch.object(m, "_registry_slot", None):
                api = HelperInvocationAPI(outputs); prepared = self._prepared(api, {"stdin": 4, "stdout": 8, "stderr": 8}); slot = prepared._slot
                with self.assertRaises(m.CreationInvocationError): prepared.invoke_once()
                self.assertTrue(slot._create_returned_success); self.assertEqual(api.events.count(("create",)), 1)
                self.assertNotIn(("membership",), api.events); self.assertGreater(api.capture_checks, 0)
                self.assertEqual(slot._phase, "QUARANTINED"); self._retained(api, slot)
    def test_post_return_observation_and_delete_failures_keep_originals(self):
        faults = ("post_expired", "post_regression", "post_bool", "post_overflow", "post_interrupt",
                  "membership_false", "membership_api_false", "membership_bad_output", "membership_bad_return",
                  "membership_raise", "membership_interrupt", "delete_raise", "delete_interrupt", "delete_late")
        for fault in faults:
            with self.subTest(fault=fault), mock.patch.object(m, "_registry_slot", None):
                api = HelperInvocationAPI(faults=(fault,)); prepared = self._prepared(api); slot = prepared._slot
                error = KeyboardInterrupt if fault in ("post_interrupt", "membership_interrupt") else m.CreationInvocationError
                with self.assertRaises(error) as caught: prepared.invoke_once()
                if error is m.CreationInvocationError:
                    self.assertIs(caught.exception.custody, slot); self.assertEqual(str(caught.exception), "QUARANTINED_UNQUALIFIED")
                self.assertTrue(slot._create_returned_success); self.assertEqual(api.events.count(("create",)), 1)
                if fault.startswith("membership") or fault.startswith("delete"):
                    self.assertIn(("membership",), api.events)
                self.assertEqual((slot._original_process_handle, slot._original_thread_handle, slot._original_process_id, slot._original_thread_id), api.written)
                self.assertEqual(slot._attribute_delete_unknown, fault in ("delete_raise", "delete_interrupt"))
                self.assertEqual(slot._phase, "QUARANTINED"); self._retained(api, slot)
                before = list(api.events)
                with self.assertRaises(m.CreationInvocationError) as retry: prepared.invoke_once()
                self.assertIsNone(retry.exception.custody); self.assertEqual(api.events, before)
                del caught
                self.assertIs(m._registry_slot, slot)
    def test_precall_state_and_deadline_refuse_before_create(self):
        for fault in ("pre_expired", "closed", "api_identity", "job_flags", "partial_pi", "wrong_array", "non_tuple"):
            with self.subTest(fault=fault), mock.patch.object(m, "_registry_slot", None):
                api = HelperInvocationAPI(faults=(fault,)); prepared = self._prepared(api); slot = prepared._slot
                if fault == "closed": object.__setattr__(slot._job, "_closed", True)
                if fault == "api_identity": object.__setattr__(slot._job, "_api", object())
                if fault == "job_flags": api.handle_flags = 1
                if fault == "partial_pi": slot._process_info.hProcess = 0x5000
                if fault == "wrong_array": slot._attribute_values[0][0] = 0x2000
                if fault == "non_tuple": slot._stdio = []
                with self.assertRaises(m.CreationInvocationError): prepared.invoke_once()
                self.assertNotIn(("create",), api.events); self.assertFalse(slot._create_entered)
                self.assertFalse(slot._create_returned_success); self.assertTrue(slot._invoke_spent)
                self.assertEqual(slot._phase, "QUARANTINED"); self._retained(api, slot)
    def test_busy_concurrent_reentrant_make_one_create(self):
        api = HelperInvocationAPI(); prepared = self._prepared(api); slot = prepared._slot
        before = list(api.events)
        slot._lock.acquire()
        try:
            with self.assertRaises(m.CreationInvocationError) as busy: prepared.invoke_once()
            self.assertIsNone(busy.exception.custody); self.assertFalse(slot._invoke_spent)
            self.assertEqual(api.events, before)
        finally: slot._lock.release()
        entered, release = threading.Event(), threading.Event(); results = []
        def on_create():
            with self.assertRaises(m.CreationInvocationError) as reentrant: prepared.invoke_once()
            self.assertIsNone(reentrant.exception.custody)
            entered.set()
            if not release.wait(3): raise RuntimeError("FAKE_WAIT_TIMEOUT")
        api.on_create = on_create
        def worker():
            try: results.append(prepared.invoke_once())
            except BaseException as error: results.append(error)
        thread = threading.Thread(target=worker, daemon=True); thread.start()
        try:
            self.assertTrue(entered.wait(3))
            with self.assertRaises(m.CreationInvocationError) as concurrent: prepared.invoke_once()
            self.assertIsNone(concurrent.exception.custody)
        finally: release.set(); thread.join(3)
        self.assertFalse(thread.is_alive()); self.assertEqual(len(results), 1)
        self.assertIs(type(results[0]), m.CreationOutcome)
        self.assertEqual(api.events.count(("create",)), 1); self._retained(api, slot)


if __name__ == "__main__":
    unittest.main()
