"""GB-S3A focused tests — retained origin observation foundation.

Fake DLL/handle table only. NO actual DLL loading, native calls, TCP, job,
launch, or real namespaces. Records exact call trace. No caller booleans grant
authority. S3 remains PARTIAL (this is step A only).
"""

from __future__ import annotations

import ctypes
import gc
import hashlib
import ipaddress
import math
import struct
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from v213_qa_capacity_control_state import (  # noqa: E402
    StateValidationError,
)
from v213_qa_capacity_control_windows import (  # noqa: E402
    AF_INET,
    AF_INET6,
    AUTHORIZES_EXECUTION,
    ERROR_INSUFFICIENT_BUFFER,
    FileAttributeTagInfoStruct,
    FileIdInfoStruct,
    FileStandardInfoStruct,
    IMAGE_BYTES_ATTESTED,
    JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE,
    JobBasicLimitInformationStruct,
    JobExtendedLimitInformationStruct,
    JobIoCountersStruct,
    MAX_TABLE_BYTES,
    MibTcp6RowOwnerPid,
    MibTcp6TableOwnerPid,
    MibTcpRowOwnerPid,
    MibTcpTableOwnerPid,
    RetainedContainmentJob,
    RetainedFileObservation,
    RetainedListenerBinding,
    RetainedOrigin,
    TCP_TABLE_OWNER_PID_ALL,
    TcpRowFact,
    TcpSnapshot,
    WORKSPACE_ATTESTED,
    WindowsObservationError,
    _FILETIME,
    _decode_tcp_table,
    _issued_tcp_snapshots,
    _issue_tcp_snapshot,
    bind_file_bytes,
    bind_listener_process,
    bind_origin,
    classify_tcp_conflicts,
    collect_tcp_owner_tables,
    create_containment_job,
    is_factory_issued_tcp_snapshot,
)

WAIT_OBJECT_0 = 0
WAIT_TIMEOUT = 258
WAIT_FAILED = 0xFFFFFFFF
WAIT_ABANDONED = 0x00000080


class FakeAPI:
    """Fake Windows API with a handle table and exact call trace.

    The callables are plain functions (closures) stored as instance attributes
    so they support .argtypes/.restype (as required by the ABI contract).
    """

    def __init__(self, creation_filetime=None, image_path=None,
                 open_result=None, open_null=False, times_ok=True,
                 image_ok=True, wait_result=0, close_ok=True,
                 image_size_override=None):
        self.creation_filetime = creation_filetime  # (low, high) or None
        self.image_path = image_path
        self.open_result = open_result  # None -> assign handle; else use it
        self.open_null = open_null  # True -> OpenProcess returns NULL
        self.times_ok = times_ok
        self.image_ok = image_ok
        self.wait_result = wait_result
        self.close_ok = close_ok
        self.image_size_override = image_size_override
        self.call_trace = []
        self.handle_table = {}
        self._next_handle = 0x1000

        self.OpenProcess = self._make_open_process()
        self.GetProcessTimes = self._make_get_process_times()
        self.QueryFullProcessImageNameW = self._make_query_image()
        self.WaitForSingleObject = self._make_wait()
        self.CloseHandle = self._make_close()

    def _make_open_process(self):
        self_ = self

        def open_process(access, inherit, pid):
            self_.call_trace.append(("OpenProcess", access, inherit, pid))
            if self_.open_null:
                return None
            if self_.open_result is not None:
                return self_.open_result
            self_._next_handle += 1
            handle = self_._next_handle
            self_.handle_table[handle] = {"pid": pid, "access": access}
            return handle

        return open_process

    def _make_get_process_times(self):
        self_ = self

        def get_process_times(handle, creation, exit_, kernel, user):
            self_.call_trace.append(("GetProcessTimes", handle))
            if not self_.times_ok:
                return 0
            if self_.creation_filetime is not None:
                low, high = self_.creation_filetime
                creation.contents.dwLowDateTime = low
                creation.contents.dwHighDateTime = high
            return 1

        return get_process_times

    def _make_query_image(self):
        self_ = self

        def query_image(handle, flags, buf, size_ptr):
            self_.call_trace.append(
                ("QueryFullProcessImageNameW", handle, flags))
            if not self_.image_ok:
                return 0
            if self_.image_path is not None:
                for i, ch in enumerate(self_.image_path):
                    buf[i] = ch
                if self_.image_size_override is not None:
                    size_ptr.contents.value = self_.image_size_override
                else:
                    size_ptr.contents.value = len(self_.image_path)
            return 1

        return query_image

    def _make_wait(self):
        self_ = self

        def wait(handle, ms):
            self_.call_trace.append(("WaitForSingleObject", handle, ms))
            return self_.wait_result

        return wait

    def _make_close(self):
        self_ = self

        def close(handle):
            self_.call_trace.append(("CloseHandle", handle))
            if not self_.close_ok:
                return 0
            self_.handle_table.pop(handle, None)
            return 1

        return close


def _birth(low, high):
    return (high << 32) | low


class WindowsABITests(unittest.TestCase):
    def _valid_api(self):
        return FakeAPI(creation_filetime=(0x1111, 0x2222),
                       image_path="C:\\a.exe")

    def test_abi_widths_sizes_prototypes(self):
        api = self._valid_api()
        bind_origin(api, 1234, _birth(0x1111, 0x2222), "C:\\a.exe")
        self.assertEqual(
            api.OpenProcess.argtypes,
            [ctypes.c_uint32, ctypes.c_int32, ctypes.c_uint32])
        self.assertIs(api.OpenProcess.restype, ctypes.c_void_p)
        self.assertEqual(
            api.GetProcessTimes.argtypes,
            [ctypes.c_void_p, ctypes.POINTER(_FILETIME),
             ctypes.POINTER(_FILETIME), ctypes.POINTER(_FILETIME),
             ctypes.POINTER(_FILETIME)])
        self.assertIs(api.GetProcessTimes.restype, ctypes.c_int32)
        self.assertEqual(
            api.QueryFullProcessImageNameW.argtypes,
            [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_wchar_p,
             ctypes.POINTER(ctypes.c_uint32)])
        self.assertIs(api.QueryFullProcessImageNameW.restype, ctypes.c_int32)
        self.assertEqual(
            api.WaitForSingleObject.argtypes,
            [ctypes.c_void_p, ctypes.c_uint32])
        self.assertIs(api.WaitForSingleObject.restype, ctypes.c_uint32)
        self.assertEqual(api.CloseHandle.argtypes, [ctypes.c_void_p])
        self.assertIs(api.CloseHandle.restype, ctypes.c_int32)
        # FILETIME size 8, word offsets 0/4
        self.assertEqual(ctypes.sizeof(_FILETIME), 8)
        self.assertEqual(_FILETIME.dwLowDateTime.offset, 0)
        self.assertEqual(_FILETIME.dwHighDateTime.offset, 4)

    def test_no_native_library_import_side_effects(self):
        from unittest import mock
        api = self._valid_api()
        with mock.patch.object(ctypes, "WinDLL",
                               side_effect=AssertionError("WinDLL called")) \
                as m1, \
             mock.patch.object(ctypes, "CDLL",
                               side_effect=AssertionError("CDLL called")) \
                as m2:
            origin = bind_origin(api, 1234, _birth(0x1111, 0x2222),
                                 "C:\\a.exe")
            origin.wait_for_exit(1000, 0, 0)
            origin.close()
        self.assertFalse(m1.called)
        self.assertFalse(m2.called)

    def test_result_flags_fixed_false(self):
        self.assertIs(AUTHORIZES_EXECUTION, False)
        self.assertIs(WORKSPACE_ATTESTED, False)
        self.assertIs(IMAGE_BYTES_ATTESTED, False)
        self.assertIs(RetainedOrigin.AUTHORIZES_EXECUTION, False)
        self.assertIs(RetainedOrigin.WORKSPACE_ATTESTED, False)
        self.assertIs(RetainedOrigin.IMAGE_BYTES_ATTESTED, False)


class WindowsBindTests(unittest.TestCase):
    def _valid_api(self, low=0x1111, high=0x2222, image="C:\\a.exe",
                   **kwargs):
        return FakeAPI(creation_filetime=(low, high), image_path=image,
                       **kwargs)

    def test_valid_bind(self):
        api = self._valid_api()
        origin = bind_origin(api, 1234, _birth(0x1111, 0x2222), "C:\\a.exe")
        self.assertEqual(origin.pid, 1234)
        self.assertEqual(origin.creation_filetime, _birth(0x1111, 0x2222))
        self.assertEqual(origin.image_path, "C:\\a.exe")
        # immutable observed facts read-only
        with self.assertRaises(WindowsObservationError):
            origin.pid = 9999
        with self.assertRaises(WindowsObservationError):
            origin.image_path = "C:\\b.exe"

    def test_pid_malformed_no_calls(self):
        for bad_pid in (True, 0, -1, 0x100000000, 1.5, "1234"):
            api = self._valid_api()
            with self.assertRaises(WindowsObservationError):
                bind_origin(api, bad_pid, _birth(0x1111, 0x2222),
                            "C:\\a.exe")
            self.assertEqual(api.call_trace, [])

    def test_pid_subclass_no_calls(self):
        class _IntSub(int):
            pass
        api = self._valid_api()
        with self.assertRaises(WindowsObservationError):
            bind_origin(api, _IntSub(1234), _birth(0x1111, 0x2222),
                        "C:\\a.exe")
        self.assertEqual(api.call_trace, [])

    def test_birth_malformed_no_calls(self):
        for bad_birth in (True, -1, 0x10000000000000000, 1.5, "x"):
            api = self._valid_api()
            with self.assertRaises(WindowsObservationError):
                bind_origin(api, 1234, bad_birth, "C:\\a.exe")
            self.assertEqual(api.call_trace, [])

    def test_image_malformed_no_calls(self):
        for bad_image in ("", "a.exe", "sub\\a.exe", "C:", "C:a.exe",
                          "C:\\bad\x00char.exe", "C:\\del\x7f.exe",
                          1234, None):
            api = self._valid_api()
            with self.assertRaises(WindowsObservationError):
                bind_origin(api, 1234, _birth(0x1111, 0x2222), bad_image)
            self.assertEqual(api.call_trace, [])

    def test_access_denied_no_close(self):
        api = FakeAPI(open_null=True)
        with self.assertRaises(WindowsObservationError):
            bind_origin(api, 1234, _birth(0x1111, 0x2222), "C:\\a.exe")
        close_calls = [c for c in api.call_trace if c[0] == "CloseHandle"]
        self.assertEqual(close_calls, [])

    def test_failed_times_closes_owned(self):
        api = self._valid_api(times_ok=False)
        with self.assertRaises(WindowsObservationError):
            bind_origin(api, 1234, _birth(0x1111, 0x2222), "C:\\a.exe")
        close_calls = [c for c in api.call_trace if c[0] == "CloseHandle"]
        self.assertEqual(len(close_calls), 1)

    def test_failed_image_closes_owned(self):
        api = self._valid_api(image_ok=False)
        with self.assertRaises(WindowsObservationError):
            bind_origin(api, 1234, _birth(0x1111, 0x2222), "C:\\a.exe")
        close_calls = [c for c in api.call_trace if c[0] == "CloseHandle"]
        self.assertEqual(len(close_calls), 1)

    def test_wrong_birth_closes_owned(self):
        api = self._valid_api(low=0x1111, high=0x2222)
        with self.assertRaises(WindowsObservationError):
            bind_origin(api, 1234, _birth(0x1111, 0x9999), "C:\\a.exe")
        close_calls = [c for c in api.call_trace if c[0] == "CloseHandle"]
        self.assertEqual(len(close_calls), 1)

    def test_filetime_same_low_different_high_mismatch(self):
        low = 0x1111
        api = self._valid_api(low=low, high=0x3333)  # actual high 0x3333
        with self.assertRaises(WindowsObservationError):
            bind_origin(api, 1234, _birth(low, 0x2222), "C:\\a.exe")
        close_calls = [c for c in api.call_trace if c[0] == "CloseHandle"]
        self.assertEqual(len(close_calls), 1)

    def test_wrong_image_closes_owned(self):
        api = self._valid_api(image="C:\\actual.exe")
        with self.assertRaises(WindowsObservationError):
            bind_origin(api, 1234, _birth(0x1111, 0x2222), "C:\\expected.exe")
        close_calls = [c for c in api.call_trace if c[0] == "CloseHandle"]
        self.assertEqual(len(close_calls), 1)

    def test_missing_image_closes_owned(self):
        api = FakeAPI(creation_filetime=(0x1111, 0x2222), image_path=None)
        with self.assertRaises(WindowsObservationError):
            bind_origin(api, 1234, _birth(0x1111, 0x2222), "C:\\a.exe")
        close_calls = [c for c in api.call_trace if c[0] == "CloseHandle"]
        self.assertEqual(len(close_calls), 1)

    def test_single_open_same_handle_for_queries(self):
        api = self._valid_api()
        origin = bind_origin(api, 1234, _birth(0x1111, 0x2222), "C:\\a.exe")
        open_calls = [c for c in api.call_trace if c[0] == "OpenProcess"]
        self.assertEqual(len(open_calls), 1)
        # queries use the SAME handle (the one OpenProcess returned)
        get_handle = [c for c in api.call_trace
                      if c[0] == "GetProcessTimes"][0][1]
        img_handle = [c for c in api.call_trace
                      if c[0] == "QueryFullProcessImageNameW"][0][1]
        self.assertEqual(get_handle, img_handle)
        self.assertEqual(get_handle, origin._handle)

    def test_retained_handle_vs_reused_pid(self):
        api = self._valid_api(low=0x1111, high=0x2222, image="C:\\a.exe")
        origin = bind_origin(api, 1234, _birth(0x1111, 0x2222), "C:\\a.exe")
        handle1 = origin._handle
        # PID reuse: new process with same PID, different birth/image
        api.creation_filetime = (0x3333, 0x4444)
        api.image_path = "C:\\b.exe"
        origin2 = bind_origin(api, 1234, _birth(0x3333, 0x4444), "C:\\b.exe")
        handle2 = origin2._handle
        self.assertNotEqual(handle1, handle2)
        # wait on the retained origin -> uses handle1, not handle2
        api.wait_result = WAIT_OBJECT_0
        api.call_trace.clear()
        origin.wait_for_exit(1000, 0, 0)
        wait_calls = [c for c in api.call_trace
                      if c[0] == "WaitForSingleObject"]
        self.assertEqual(wait_calls[0][1], handle1)


class WindowsWaitTests(unittest.TestCase):
    def _bound(self, wait_result=0):
        api = FakeAPI(creation_filetime=(0x1111, 0x2222),
                      image_path="C:\\a.exe", wait_result=wait_result)
        origin = bind_origin(api, 1234, _birth(0x1111, 0x2222), "C:\\a.exe")
        return api, origin

    def test_wait_signaled(self):
        api, origin = self._bound(wait_result=WAIT_OBJECT_0)
        self.assertTrue(origin.wait_for_exit(1000, 0, 0))

    def test_wait_timeout(self):
        api, origin = self._bound(wait_result=WAIT_TIMEOUT)
        self.assertFalse(origin.wait_for_exit(1000, 0, 0))

    def test_wait_failed(self):
        api, origin = self._bound(wait_result=WAIT_FAILED)
        with self.assertRaises(WindowsObservationError):
            origin.wait_for_exit(1000, 0, 0)

    def test_wait_abandoned(self):
        api, origin = self._bound(wait_result=WAIT_ABANDONED)
        with self.assertRaises(WindowsObservationError):
            origin.wait_for_exit(1000, 0, 0)

    def test_wait_zero_budget(self):
        api, origin = self._bound(wait_result=WAIT_TIMEOUT)
        api.call_trace.clear()
        self.assertFalse(origin.wait_for_exit(1000, 1000, 0))
        wait_calls = [c for c in api.call_trace
                      if c[0] == "WaitForSingleObject"]
        self.assertEqual(wait_calls[0][2], 0)  # ms == 0

    def test_wait_bounded_ms_cap(self):
        api, origin = self._bound(wait_result=WAIT_TIMEOUT)
        api.call_trace.clear()
        origin.wait_for_exit(1000000, 0, 0)  # remaining 1000000s
        wait_calls = [c for c in api.call_trace
                      if c[0] == "WaitForSingleObject"]
        self.assertEqual(wait_calls[0][2], 300000)  # ms capped

    def test_wait_expired_budget(self):
        api, origin = self._bound()
        with self.assertRaises(StateValidationError):
            origin.wait_for_exit(1000, 1001, 0)  # now > deadline

    def test_wait_backward_budget(self):
        api, origin = self._bound()
        with self.assertRaises(StateValidationError):
            origin.wait_for_exit(1000, 500, 600)  # now < previous_now

    def test_wait_bool_budget(self):
        api, origin = self._bound()
        with self.assertRaises(StateValidationError):
            origin.wait_for_exit(True, 0, 0)  # bool deadline


class WindowsLifecycleTests(unittest.TestCase):
    def _bound(self, close_ok=True):
        api = FakeAPI(creation_filetime=(0x1111, 0x2222),
                      image_path="C:\\a.exe", close_ok=close_ok)
        origin = bind_origin(api, 1234, _birth(0x1111, 0x2222), "C:\\a.exe")
        return api, origin

    def test_reject_public_construction(self):
        with self.assertRaises(WindowsObservationError):
            RetainedOrigin()
        with self.assertRaises(WindowsObservationError):
            RetainedOrigin(1234)

    def test_single_close(self):
        api, origin = self._bound()
        origin.close()
        close_calls = [c for c in api.call_trace if c[0] == "CloseHandle"]
        self.assertEqual(len(close_calls), 1)

    def test_double_close(self):
        api, origin = self._bound()
        origin.close()
        with self.assertRaises(WindowsObservationError):
            origin.close()
        close_calls = [c for c in api.call_trace if c[0] == "CloseHandle"]
        self.assertEqual(len(close_calls), 1)  # only one actual close

    def test_wait_after_close(self):
        api, origin = self._bound()
        origin.close()
        with self.assertRaises(WindowsObservationError):
            origin.wait_for_exit(1000, 0, 0)

    def test_context_manager_closes(self):
        api = FakeAPI(creation_filetime=(0x1111, 0x2222),
                      image_path="C:\\a.exe")
        with bind_origin(api, 1234, _birth(0x1111, 0x2222), "C:\\a.exe") \
                as origin:
            origin.wait_for_exit(1000, 0, 0)
        close_calls = [c for c in api.call_trace if c[0] == "CloseHandle"]
        self.assertEqual(len(close_calls), 1)

    def test_failed_close_not_silent(self):
        api, origin = self._bound(close_ok=False)
        with self.assertRaises(WindowsObservationError):
            origin.close()
        # failed close is still one close; no silent success
        close_calls = [c for c in api.call_trace if c[0] == "CloseHandle"]
        self.assertEqual(len(close_calls), 1)

    def test_no_process_termination(self):
        api, origin = self._bound()
        origin.wait_for_exit(1000, 0, 0)
        origin.close()
        # only observation calls; no TerminateProcess/kill in trace
        ops = {c[0] for c in api.call_trace}
        self.assertTrue(ops <= {"OpenProcess", "GetProcessTimes",
                                "QueryFullProcessImageNameW",
                                "WaitForSingleObject", "CloseHandle"})


class WindowsDefectRepairTests(unittest.TestCase):
    """Focused tests for the four reproduced source defects + helper fix."""

    def _api(self, **kwargs):
        base = dict(creation_filetime=(0x1111, 0x2222),
                    image_path="C:\\a.exe")
        base.update(kwargs)
        return FakeAPI(**base)

    # --- defect 1: returned image length validation -----------------------
    def test_image_length_zero_rejected(self):
        api = self._api(image_size_override=0)
        with self.assertRaises(WindowsObservationError):
            bind_origin(api, 1234, _birth(0x1111, 0x2222), "C:\\a.exe")

    def test_image_length_capacity_rejected(self):
        import v213_qa_capacity_control_windows as m
        api = self._api(image_size_override=m._MAX_IMAGE_PATH_CHARS)
        with self.assertRaises(WindowsObservationError):
            bind_origin(api, 1234, _birth(0x1111, 0x2222), "C:\\a.exe")

    def test_image_length_mismatch_rejected(self):
        api = self._api(image_size_override=99)  # != len("C:\\a.exe")
        with self.assertRaises(WindowsObservationError):
            bind_origin(api, 1234, _birth(0x1111, 0x2222), "C:\\a.exe")

    # --- defect 2: immutable flags/facts/ownership ------------------------
    def test_flag_fact_mutation_rejected(self):
        api = self._api()
        origin = bind_origin(api, 1234, _birth(0x1111, 0x2222), "C:\\a.exe")
        with self.assertRaises(WindowsObservationError):
            origin.pid = 9999
        with self.assertRaises(WindowsObservationError):
            origin.image_path = "C:\\b.exe"
        with self.assertRaises(WindowsObservationError):
            origin.creation_filetime = 0
        with self.assertRaises(WindowsObservationError):
            origin.AUTHORIZES_EXECUTION = True
        with self.assertRaises(WindowsObservationError):
            origin._handle = 0xDEAD
        with self.assertRaises(WindowsObservationError):
            origin._closed = True

    def test_flag_fact_deletion_rejected(self):
        api = self._api()
        origin = bind_origin(api, 1234, _birth(0x1111, 0x2222), "C:\\a.exe")
        with self.assertRaises(WindowsObservationError):
            del origin.pid
        with self.assertRaises(WindowsObservationError):
            del origin.image_path
        with self.assertRaises(WindowsObservationError):
            del origin._handle

    # --- defect 3: huge finite budget bounded -----------------------------
    def test_huge_finite_budget_bounded(self):
        api = self._api(wait_result=WAIT_TIMEOUT)
        origin = bind_origin(api, 1234, _birth(0x1111, 0x2222), "C:\\a.exe")
        api.call_trace.clear()
        # huge finite remaining (1e308 s) must not overflow; capped at 300000
        origin.wait_for_exit(1e308, 0, 0)
        wait_calls = [c for c in api.call_trace
                      if c[0] == "WaitForSingleObject"]
        self.assertEqual(wait_calls[0][2], 300000)

    # --- defect 4: NULL handle never queried ------------------------------
    def test_null_zero_handle_rejected(self):
        api = FakeAPI(open_result=0)  # zero handle
        with self.assertRaises(WindowsObservationError):
            bind_origin(api, 1234, _birth(0x1111, 0x2222), "C:\\a.exe")
        ops = {c[0] for c in api.call_trace}
        self.assertEqual(ops, {"OpenProcess"})  # NULL never queried

    def test_bool_handle_rejected(self):
        api = FakeAPI(open_result=True)  # bool handle
        with self.assertRaises(WindowsObservationError):
            bind_origin(api, 1234, _birth(0x1111, 0x2222), "C:\\a.exe")
        ops = {c[0] for c in api.call_trace}
        self.assertEqual(ops, {"OpenProcess"})  # no bool handle success

    # --- defect 5: close-failure reporting --------------------------------
    def test_close_failure_not_silent(self):
        api = self._api(close_ok=False)
        origin = bind_origin(api, 1234, _birth(0x1111, 0x2222), "C:\\a.exe")
        with self.assertRaises(WindowsObservationError):
            origin.close()
        self.assertTrue(origin.cleanup_failed)
        # wait cannot continue after ambiguous cleanup
        with self.assertRaises(WindowsObservationError):
            origin.wait_for_exit(1000, 0, 0)

    def test_bind_cleanup_failure_surfaced(self):
        # query fails AND cleanup close fails -> cleanup failure surfaced
        api = FakeAPI(creation_filetime=(0x1111, 0x2222),
                      image_path="C:\\a.exe", times_ok=False, close_ok=False)
        with self.assertRaises(WindowsObservationError) as ctx:
            bind_origin(api, 1234, _birth(0x1111, 0x2222), "C:\\a.exe")
        self.assertIn("cleanup CloseHandle failed", str(ctx.exception))


class FakeTcpTableAPI:
    """Fake GetExtendedTcpTable modeling Windows input capacity faithfully.

    sizing_size/fill_size None (default) means actual per-family data length;
    explicit 0 is the malformed input case. Fill checks incoming capacity and
    allocation size before memmove; short capacity returns 122 + required size
    (never an unsafe overflow). Per-family error injection for the second
    family sizing/fill; inputs (including incoming capacity) are tracked.
    """

    def __init__(self, tables=None, sizing_size=None, fill_size=None,
                 second_family_sizing_rc=None, second_family_fill_rc=None):
        self.tables = tables or {}
        self.sizing_size = sizing_size
        self.fill_size = fill_size
        self.second_family_sizing_rc = second_family_sizing_rc
        self.second_family_fill_rc = second_family_fill_rc
        self.calls = []

        def get_extended_tcp_table(buf, size_ptr, order, family, table_class,
                                   reserved):
            data = self.tables.get(family)
            data_len = len(data) if data is not None else 0
            self.calls.append({"sizing": buf is None, "order": order,
                               "family": family, "table_class": table_class,
                               "reserved": reserved,
                               "in_size": size_ptr.contents.value,
                               "buf_size": (ctypes.sizeof(buf)
                                            if buf is not None else 0)})
            if buf is None:
                if self.second_family_sizing_rc is not None \
                        and family == AF_INET6:
                    return self.second_family_sizing_rc
                size_ptr.contents.value = (self.sizing_size
                                           if self.sizing_size is not None
                                           else data_len)
                return 122
            if self.second_family_fill_rc is not None and family == AF_INET6:
                return self.second_family_fill_rc
            in_cap = size_ptr.contents.value
            alloc = ctypes.sizeof(buf)
            if in_cap < data_len or alloc < data_len:
                size_ptr.contents.value = data_len
                return 122
            ctypes.memmove(buf, data, data_len)
            size_ptr.contents.value = (self.fill_size
                                       if self.fill_size is not None
                                       else data_len)
            return 0

        self.GetExtendedTcpTable = get_extended_tcp_table


def _port16(port, upper=0):
    return port.to_bytes(2, "big") + upper.to_bytes(2, "big")


def _v4_row(state, laddr, lport, raddr, rport, pid, upper=0):
    return (state.to_bytes(4, "little") + laddr + _port16(lport, upper)
            + raddr + _port16(rport, upper) + pid.to_bytes(4, "little"))


def _v6_row(state, laddr, lscope, lport, raddr, rscope, rport, pid,
            upper=0):
    return (laddr + lscope.to_bytes(4, "little") + _port16(lport, upper)
            + raddr + rscope.to_bytes(4, "little") + _port16(rport, upper)
            + state.to_bytes(4, "little") + pid.to_bytes(4, "little"))


def _table_image(rows):
    return len(rows).to_bytes(4, "little") + b"".join(rows)


def _ip6(text):
    packed = ipaddress.IPv6Address(text).packed
    assert len(packed) == 16
    return packed


V4_LISTEN = _v4_row(2, b"\x7f\x00\x00\x01", 80, b"\x7f\x00\x00\x01", 0, 4242)
V4_EST_LOCAL = _v4_row(5, b"\x7f\x00\x00\x01", 8080, b"\x0a\x00\x00\x01",
                       80, 777)
V4_EST_REMOTE = _v4_row(5, b"\x7f\x00\x00\x01", 50000, b"\x0a\x00\x00\x02",
                        80, 999)
V6_LISTEN = _v6_row(2, b"\x00" * 15 + b"\x01", 1, 443, b"\x00" * 16, 2, 0,
                    31337)
V6_EST = _v6_row(5, b"\xfe\x80" + b"\x00" * 14, 5, 9000,
                 _ip6("2001:db8::1"), 7, 443, 555)


class S3BLayoutTests(unittest.TestCase):
    def test_constants(self):
        self.assertEqual(AF_INET, 2)
        self.assertEqual(AF_INET6, 23)
        self.assertEqual(TCP_TABLE_OWNER_PID_ALL, 5)
        self.assertEqual(ERROR_INSUFFICIENT_BUFFER, 122)
        self.assertEqual(MAX_TABLE_BYTES, 4 * 1024 * 1024)

    def test_row_layouts(self):
        self.assertEqual(ctypes.sizeof(MibTcpRowOwnerPid), 24)
        self.assertEqual(ctypes.sizeof(MibTcp6RowOwnerPid), 56)
        self.assertEqual([n for n, _ in MibTcpRowOwnerPid._fields_],
                         ["state", "localAddr", "localPort", "remoteAddr",
                          "remotePort", "pid"])
        self.assertEqual([n for n, _ in MibTcp6RowOwnerPid._fields_],
                         ["localAddr", "localScope", "localPort",
                          "remoteAddr", "remoteScope", "remotePort",
                          "state", "pid"])
        self.assertEqual(MibTcpRowOwnerPid.state.size, 4)
        self.assertEqual(MibTcpRowOwnerPid.state.offset, 0)
        self.assertEqual(MibTcp6RowOwnerPid.localAddr.size, 16)
        self.assertEqual(MibTcp6RowOwnerPid.localAddr.offset, 0)

    def test_table_layouts(self):
        self.assertEqual(MibTcpTableOwnerPid.table.offset, 4)
        self.assertEqual(MibTcp6TableOwnerPid.table.offset, 4)
        self.assertEqual(ctypes.sizeof(MibTcpTableOwnerPid), 28)
        self.assertEqual(ctypes.sizeof(MibTcp6TableOwnerPid), 60)


class S3BDecoderTests(unittest.TestCase):
    def test_ipv4_decode(self):
        rows = _decode_tcp_table(
            _table_image([V4_EST_LOCAL]), AF_INET)
        self.assertEqual(len(rows), 1)
        r = rows[0]
        self.assertEqual(r.family, AF_INET)
        self.assertEqual(r.local_address, "127.0.0.1")
        self.assertEqual(r.local_port, 8080)
        self.assertEqual(r.local_scope_id, 0)
        self.assertEqual(r.remote_address, "10.0.0.1")
        self.assertEqual(r.remote_port, 80)
        self.assertEqual(r.state, 5)
        self.assertEqual(r.pid, 777)

    def test_ipv4_unused_upper_port_bits(self):
        row = _v4_row(5, b"\x7f\x00\x00\x01", 80, b"\x7f\x00\x00\x01", 80,
                      1, upper=0xFFFF)
        r = _decode_tcp_table(_table_image([row]), AF_INET)[0]
        self.assertEqual(r.local_port, 80)
        self.assertEqual(r.remote_port, 80)

    def test_ipv6_decode(self):
        r = _decode_tcp_table(_table_image([V6_EST]), AF_INET6)[0]
        self.assertEqual(r.family, AF_INET6)
        self.assertEqual(r.local_address, "fe80::")
        self.assertEqual(r.local_scope_id, 5)
        self.assertEqual(r.local_port, 9000)
        self.assertEqual(r.remote_address, "2001:db8::1")
        self.assertEqual(r.remote_scope_id, 7)
        self.assertEqual(r.remote_port, 443)
        self.assertEqual(r.state, 5)
        self.assertEqual(r.pid, 555)

    def test_exact_type_rejects(self):
        good = _table_image([V4_LISTEN])
        for bad in (b"", "bytes", bytearray(good), memoryview(good), None,
                    123):
            with self.subTest(data=type(bad).__name__):
                with self.assertRaises(WindowsObservationError):
                    _decode_tcp_table(bad, AF_INET)
        for fam in (True, False, 0, 22, 24, "2", 2.0):
            with self.subTest(family=fam):
                with self.assertRaises(WindowsObservationError):
                    _decode_tcp_table(good, fam)

    def test_size_branches(self):
        with self.assertRaises(WindowsObservationError):
            _decode_tcp_table(b"\x01\x02\x03", AF_INET)  # header < 4
        huge = (4 + (4 * 1024 * 1024)).to_bytes(4, "little")
        with self.assertRaises(WindowsObservationError):
            _decode_tcp_table(huge, AF_INET)  # count overflows budget
        with self.assertRaises(WindowsObservationError):
            _decode_tcp_table(
                (2).to_bytes(4, "little") + V4_LISTEN, AF_INET)  # truncated
        with self.assertRaises(WindowsObservationError):
            _decode_tcp_table(
                _table_image([V4_LISTEN]) + b"\x00", AF_INET)  # trailing

    def test_state_branches(self):
        for state in (0, 13, 4294967295):
            row = _v4_row(state, b"\x7f\x00\x00\x01", 1, b"\x7f\x00\x00\x01",
                          1, 2)
            with self.subTest(state=state):
                with self.assertRaises(WindowsObservationError):
                    _decode_tcp_table(_table_image([row]), AF_INET)
        for state in (2, 5):
            row = _v4_row(state, b"\x7f\x00\x00\x01", 1, b"\x7f\x00\x00\x01",
                          1, 0)
            with self.subTest(pid0=state):
                with self.assertRaises(WindowsObservationError):
                    _decode_tcp_table(_table_image([row]), AF_INET)

    def test_duplicate_rows(self):
        for rows in ([V4_LISTEN, V4_LISTEN], [V6_EST, V6_EST]):
            with self.subTest(family=rows[0] is V4_LISTEN):
                fam = AF_INET if rows[0] is V4_LISTEN else AF_INET6
                with self.assertRaises(WindowsObservationError):
                    _decode_tcp_table(_table_image(rows), fam)

    def test_row_fact_frozen(self):
        r = _decode_tcp_table(_table_image([V4_LISTEN]), AF_INET)[0]
        self.assertIs(type(r), TcpRowFact)
        with self.assertRaises(Exception):
            r.state = 9


class S3BCollectorTests(unittest.TestCase):
    def _tables(self):
        return {AF_INET: _table_image([V4_LISTEN, V4_EST_LOCAL]),
                AF_INET6: _table_image([V6_LISTEN, V6_EST])}

    def test_both_family_order_and_args(self):
        api = FakeTcpTableAPI(tables=self._tables(),
                              sizing_size=4 + 2 * 24 + 8 * 1024)
        snap = collect_tcp_owner_tables(api, 1234)
        self.assertEqual(api.calls, [
            {"sizing": True, "order": 0, "family": AF_INET,
             "table_class": 5, "reserved": 0, "in_size": 0, "buf_size": 0},
            {"sizing": False, "order": 0, "family": AF_INET,
             "table_class": 5, "reserved": 0, "in_size": 8244,
             "buf_size": 8244},
            {"sizing": True, "order": 0, "family": AF_INET6,
             "table_class": 5, "reserved": 0, "in_size": 0, "buf_size": 0},
            {"sizing": False, "order": 0, "family": AF_INET6,
             "table_class": 5, "reserved": 0, "in_size": 8244,
             "buf_size": 8244}])
        self.assertEqual(len(snap.rows), 4)
        self.assertEqual(snap.sampled_at, 1234)
        self.assertFalse(snap.AUTHORIZES_EXECUTION)
        self.assertFalse(snap.ATOMIC_SNAPSHOT)
        self.assertFalse(snap.PROCESS_BIRTHS_ATTESTED)
        self.assertFalse(snap.LISTENER_IDENTITY_ATTESTED)

    def test_error_first_family_stops(self):
        # malformed input: explicit sizing size 0 (<4) on the FIRST family
        api = FakeTcpTableAPI(tables=self._tables(), sizing_size=0)
        with self.assertRaises(WindowsObservationError):
            collect_tcp_owner_tables(api, 1)
        self.assertEqual(len(api.calls), 1)
        self.assertEqual(api.calls[0]["family"], AF_INET)
        self.assertEqual(api.calls[0]["in_size"], 0)

    def test_error_second_family(self):
        # injected IPv6 FILL failure: complete preceding trace + 4th call
        api = FakeTcpTableAPI(tables=self._tables(),
                              second_family_fill_rc=5)
        with self.assertRaises(WindowsObservationError):
            collect_tcp_owner_tables(api, 1)
        self.assertEqual(len(api.calls), 4)
        self.assertEqual(api.calls[0], {"sizing": True, "order": 0,
                                        "family": AF_INET, "table_class": 5,
                                        "reserved": 0, "in_size": 0,
                                        "buf_size": 0})
        self.assertEqual(api.calls[1], {"sizing": False, "order": 0,
                                        "family": AF_INET, "table_class": 5,
                                        "reserved": 0, "in_size": 4 + 2 * 24,
                                        "buf_size": 4 + 2 * 24})
        self.assertEqual(api.calls[2], {"sizing": True, "order": 0,
                                        "family": AF_INET6, "table_class": 5,
                                        "reserved": 0, "in_size": 0,
                                        "buf_size": 0})
        self.assertEqual(api.calls[3], {"sizing": False, "order": 0,
                                        "family": AF_INET6, "table_class": 5,
                                        "reserved": 0, "in_size": 4 + 2 * 56,
                                        "buf_size": 4 + 2 * 56})
        api = FakeTcpTableAPI(tables=self._tables(),
                              second_family_sizing_rc=42)
        with self.assertRaises(WindowsObservationError):
            collect_tcp_owner_tables(api, 1)
        self.assertEqual(len(api.calls), 3)
        self.assertEqual(api.calls[0]["family"], AF_INET)
        self.assertEqual(api.calls[2]["family"], AF_INET6)

    def test_resize_bounds(self):
        for sizing_size in (0, 3, 4 * 1024 * 1024 + 1):
            api = FakeTcpTableAPI(tables=self._tables(),
                                  sizing_size=sizing_size)
            with self.subTest(sizing_size=sizing_size):
                with self.assertRaises(WindowsObservationError):
                    collect_tcp_owner_tables(api, 1)
        api = FakeTcpTableAPI(tables=self._tables(),
                              sizing_size=4 + 2 * 24, fill_size=3)
        with self.assertRaises(WindowsObservationError):
            collect_tcp_owner_tables(api, 1)
        api = FakeTcpTableAPI(tables=self._tables(),
                              sizing_size=4 + 2 * 24, fill_size=4 + 3 * 24)
        with self.assertRaises(WindowsObservationError):
            collect_tcp_owner_tables(api, 1)

    def test_missing_or_noncallable(self):
        class NoAttr:
            pass

        with self.assertRaises(WindowsObservationError):
            collect_tcp_owner_tables(NoAttr(), 1)

        class NotCallable:
            GetExtendedTcpTable = 5

        with self.assertRaises(WindowsObservationError):
            collect_tcp_owner_tables(NotCallable(), 1)

    def test_sampled_at_rejected_before_calls(self):
        for bad in (True, "1", float("nan"), float("inf"), 10 ** 400):
            api = FakeTcpTableAPI(tables=self._tables())
            with self.subTest(bad=bad):
                with self.assertRaises(WindowsObservationError):
                    collect_tcp_owner_tables(api, bad)
            self.assertEqual(api.calls, [])

    def test_sampled_at_float_15_accepted(self):
        api = FakeTcpTableAPI(tables=self._tables())
        snap = collect_tcp_owner_tables(api, 1.5)
        self.assertEqual(snap.sampled_at, 1.5)
        self.assertEqual(len(snap.rows), 4)
        self.assertEqual(len(api.calls), 4)

    def test_empty_tables_false_flags(self):
        api = FakeTcpTableAPI(tables={AF_INET: b"\x00" * 4,
                                      AF_INET6: b"\x00" * 4},
                              sizing_size=4)
        snap = collect_tcp_owner_tables(api, 9)
        self.assertEqual(snap.rows, ())
        self.assertFalse(snap.AUTHORIZES_EXECUTION)
        self.assertFalse(snap.ATOMIC_SNAPSHOT)


class S3BClassifyTests(unittest.TestCase):
    def _snap(self):
        return collect_tcp_owner_tables(
            FakeTcpTableAPI(tables={AF_INET: _table_image(
                [V4_LISTEN, V4_EST_LOCAL, V4_EST_REMOTE]),
                AF_INET6: _table_image([V6_LISTEN, V6_EST])}),
            1234)

    def test_established_local_and_remote(self):
        est, listeners = classify_tcp_conflicts(self._snap(), 80)
        self.assertEqual(len(est), 2)
        self.assertEqual(est[0].family, AF_INET)
        self.assertEqual(est[0].local_port, 8080)
        self.assertEqual(est[1].family, AF_INET)
        self.assertEqual(est[1].remote_port, 80)
        self.assertIsInstance(est, tuple)
        self.assertIsInstance(listeners, tuple)

    def test_no_pid_exemption(self):
        row = _v4_row(5, b"\x7f\x00\x00\x01", 80, b"\x7f\x00\x00\x01", 80,
                      1)
        snap = collect_tcp_owner_tables(
            FakeTcpTableAPI(tables={AF_INET: _table_image([row]),
                                    AF_INET6: b"\x00" * 4}),
            1)
        est, _ = classify_tcp_conflicts(snap, 80)
        self.assertEqual(len(est), 1)
        self.assertEqual(est[0].pid, 1)

    def test_ipv6_conflicts(self):
        est, listeners = classify_tcp_conflicts(self._snap(), 443)
        self.assertEqual(len(est), 1)
        self.assertEqual(est[0].family, AF_INET6)
        self.assertEqual(est[0].remote_port, 443)
        self.assertEqual(len(listeners), 1)
        self.assertEqual(listeners[0].family, AF_INET6)

    def test_listeners_separated(self):
        est, listeners = classify_tcp_conflicts(self._snap(), 80)
        self.assertEqual(len(listeners), 1)
        self.assertEqual(listeners[0].local_port, 80)
        self.assertEqual(listeners[0].state, 2)
        est, _ = classify_tcp_conflicts(self._snap(), 443)
        self.assertEqual(len(est), 1)  # V6_LISTEN local 443 not established

    def test_port_type_rejects(self):
        snap = self._snap()
        for bad in (True, False, 0, 65536, "80", 80.0, float("nan"), None):
            with self.subTest(port=bad):
                with self.assertRaises(WindowsObservationError):
                    classify_tcp_conflicts(snap, bad)

    def test_fabricated_snapshots_refused(self):
        with self.assertRaises(WindowsObservationError):
            TcpSnapshot()
        raw = object.__new__(TcpSnapshot)
        with self.assertRaises(WindowsObservationError):
            classify_tcp_conflicts(raw, 80)

        class Sub(TcpSnapshot):
            pass

        with self.assertRaises(WindowsObservationError):
            classify_tcp_conflicts(object.__new__(Sub), 80)

    def test_snapshot_immutable(self):
        snap = self._snap()
        with self.assertRaises(WindowsObservationError):
            snap.rows = ()
        with self.assertRaises(WindowsObservationError):
            del snap.sampled_at

    def test_weak_registry_lifecycle(self):
        snap = self._snap()
        self.assertTrue(is_factory_issued_tcp_snapshot(snap))
        del snap
        gc.collect()
        self.assertEqual(len(_issued_tcp_snapshots), 0)
        snap2 = self._snap()
        self.assertTrue(is_factory_issued_tcp_snapshot(snap2))


class FakeAPISequence(FakeAPI):
    """FakeAPI with a per-call WaitForSingleObject result sequence."""

    def __init__(self, wait_sequence=None, **kwargs):
        super().__init__(**kwargs)
        self.wait_sequence = list(wait_sequence or [])

        def wait(handle, ms):
            self.call_trace.append(("WaitForSingleObject", handle, ms))
            if self.wait_sequence:
                value = self.wait_sequence.pop(0)
                if isinstance(value, Exception):
                    raise value  # exact instance at the wait call site
                return value
            return 258  # live process: zero-wait not signaled

        self.WaitForSingleObject = wait


class FakeSequencedTcpAPI:
    """True delegate: first/second dual-family collections go to two real
    FakeTcpTableAPI instances; records each call (incl. input size) before
    delegating; capacity/error behavior stays in the real fakes."""

    def __init__(self, first, second):
        self.first = first
        self.second = second
        self.calls = []

        def get_extended_tcp_table(buf, size_ptr, order, family, table_class,
                                   reserved):
            sizing = buf is None
            api = self.first if len(self.calls) < 4 else self.second
            self.calls.append({"sizing": sizing, "order": order,
                               "family": family, "table_class": table_class,
                               "reserved": reserved,
                               "in_size": size_ptr.contents.value,
                               "buf_size": (ctypes.sizeof(buf)
                                            if buf is not None else 0)})
            return api.GetExtendedTcpTable(buf, size_ptr, order, family,
                                           table_class, reserved)

        self.GetExtendedTcpTable = get_extended_tcp_table


C2_PID = 4242
C2_IMAGE = "C:\\listener.exe"
C2_BIRTH = _birth(0x1111, 0x2222)
C2_V4_LISTEN = _v4_row(2, b"\x7f\x00\x00\x01", 80, b"\x7f\x00\x00\x01", 0,
                       C2_PID)
C2_V6_LISTEN = _v6_row(2, b"\x00" * 15 + b"\x01", 1, 80, b"\x00" * 16, 2, 0,
                       C2_PID)
C2_V4_OTHER_EST = _v4_row(5, b"\x7f\x00\x00\x01", 8080, b"\x0a\x00\x00\x01",
                          443, 888)
C2_V4_EST_LOCAL = _v4_row(5, b"\x7f\x00\x00\x01", 80, b"\x0a\x00\x00\x01",
                          80, 666)
C2_V4_EST_REMOTE = _v4_row(5, b"\x7f\x00\x00\x01", 50000, b"\x0a\x00\x00\x02",
                           80, 777)
C2_V6_EST_LOCAL = _v6_row(5, b"\x00" * 15 + b"\x01", 1, 80, b"\x00" * 16, 2,
                          80, 888)
C2_V6_EST_REMOTE = _v6_row(5, b"\x00" * 15 + b"\x01", 1, 50000, b"\x20\x01"
                           + b"\x0d\xb8" + b"\x00" * 10, 2, 80, 999)


class S3CListenerBindingTests(unittest.TestCase):
    def _valid(self):
        first = FakeTcpTableAPI(tables={AF_INET: _table_image(
            [C2_V4_LISTEN, C2_V4_OTHER_EST]),
            AF_INET6: _table_image([C2_V6_LISTEN])})
        second = FakeTcpTableAPI(tables={AF_INET: _table_image(
            [C2_V4_LISTEN, C2_V4_OTHER_EST]),
            AF_INET6: _table_image([C2_V6_LISTEN])})
        tcp = FakeSequencedTcpAPI(first, second)
        proc = FakeAPI(creation_filetime=(0x1111, 0x2222),
                       image_path=C2_IMAGE, wait_result=258)
        return tcp, proc

    def _bind(self, tcp, proc, pid=C2_PID, birth=C2_BIRTH, image=C2_IMAGE,
              port=80, before=1000.0, after=1001.0, deadline=2000.0):
        return bind_listener_process(proc, tcp, pid, birth, image, port,
                                     observed_before=before,
                                     observed_after=after, deadline=deadline)

    def test_valid_same_pid_dual_family(self):
        tcp, proc = self._valid()
        b = self._bind(tcp, proc)
        self.assertIs(type(b), RetainedListenerBinding)
        self.assertEqual(b.pid, C2_PID)
        self.assertEqual(b.creation_filetime, C2_BIRTH)
        self.assertEqual(b.image_path, C2_IMAGE)
        self.assertEqual(b.sampled_before, 1000.0)
        self.assertEqual(b.sampled_after, 1001.0)
        self.assertTrue(is_factory_issued_tcp_snapshot(b.before_snapshot))
        self.assertTrue(is_factory_issued_tcp_snapshot(b.after_snapshot))
        self.assertEqual(len(b.before_snapshot.rows), 3)
        self.assertFalse(b.AUTHORIZES_EXECUTION)
        self.assertFalse(b.ATOMIC_SNAPSHOT)
        self.assertFalse(b.IMAGE_BYTES_ATTESTED)
        self.assertFalse(b.WORKSPACE_ATTESTED)
        self.assertTrue(b.EXPECTED_PROCESS_CLAIMS_MATCHED)
        self.assertEqual(
            [e for e in proc.call_trace if e[0] == "OpenProcess"],
            [("OpenProcess", 0x00101000, 0, C2_PID)])
        waits = [e for e in proc.call_trace if e[0] == "WaitForSingleObject"]
        self.assertEqual(len(waits), 2)
        self.assertEqual(waits[0][1], waits[1][1])  # SAME HANDLE
        self.assertEqual(waits[0][2], 0)  # zero-wait probes
        self.assertEqual([e for e in proc.call_trace
                          if e[0] == "CloseHandle"], [])
        with self.assertRaises(WindowsObservationError):
            b.pid = 1
        b.close()
        self.assertEqual(len([e for e in proc.call_trace
                              if e[0] == "CloseHandle"]), 1)
        with self.assertRaises(WindowsObservationError):
            b.close()

    def test_established_before_open_process(self):
        for v4 in (C2_V4_EST_LOCAL,   # local endpoint, foreign pid
                   _v4_row(5, b"\x7f\x00\x00\x01", 80, b"\x0a\x00\x00\x01",
                           80, C2_PID),  # same pid as expected listener
                   C2_V4_EST_REMOTE):  # remote endpoint
            tcp, proc = self._valid()
            tcp.first.tables[AF_INET] = _table_image(
                [C2_V4_LISTEN, v4])
            with self.assertRaises(WindowsObservationError):
                self._bind(tcp, proc)
            self.assertEqual(
                [e for e in proc.call_trace if e[0] == "OpenProcess"], [])
        for v6 in (C2_V6_EST_LOCAL,   # v6 local endpoint
                   C2_V6_EST_REMOTE,  # v6 remote endpoint
                   _v6_row(5, b"\x00" * 15 + b"\x01", 1, 80, b"\x00" * 16,
                           2, 80, C2_PID)):  # v6 self pid
            tcp, proc = self._valid()
            tcp.first.tables[AF_INET6] = _table_image(
                [C2_V6_LISTEN, v6])
            with self.assertRaises(WindowsObservationError):
                self._bind(tcp, proc)
            self.assertEqual(
                [e for e in proc.call_trace if e[0] == "OpenProcess"], [])

    def test_listener_ownership_variants(self):
        empty4 = {AF_INET: b"\x00" * 4, AF_INET6: b"\x00" * 4}
        cases = [
            ({AF_INET: _table_image([C2_V4_LISTEN]),
              AF_INET6: b"\x00" * 4}, True),  # valid samePID v4-only
            (empty4, False),  # missing ALL listeners, both families
            ({AF_INET: _table_image(
                [_v4_row(2, b"\x7f\x00\x00\x01", 80, b"\x7f\x00\x00\x01", 0,
                         777)]),
              AF_INET6: _table_image([C2_V6_LISTEN])}, False),  # foreign PID
        ]
        for tables, expect_success in cases:
            tcp, proc = self._valid()
            tcp.first.tables = dict(tables)
            tcp.second.tables = dict(tables)
            if expect_success:
                b = self._bind(tcp, proc)
                self.assertEqual(b.pid, C2_PID)
                b.close()
            else:
                with self.assertRaises(WindowsObservationError):
                    self._bind(tcp, proc)
                self.assertEqual(
                    [e for e in proc.call_trace
                     if e[0] == "OpenProcess"], [])

    def test_second_sample_mutations_close_once(self):
        def run(second_v4_rows, second_v6_rows=None):
            tcp, proc = self._valid()
            tcp.second.tables[AF_INET] = _table_image(second_v4_rows)
            if second_v6_rows is not None:
                tcp.second.tables[AF_INET6] = _table_image(second_v6_rows)
            with self.assertRaises(WindowsObservationError):
                self._bind(tcp, proc)
            self.assertEqual(len([e for e in proc.call_trace
                                  if e[0] == "CloseHandle"]), 1)

        # listener disappearance
        run([C2_V4_OTHER_EST])
        # address mutation
        run([_v4_row(2, b"\x7f\x00\x00\x02", 80, b"\x7f\x00\x00\x01", 0,
                     C2_PID), C2_V4_OTHER_EST])
        # scope mutation (v6)
        run([C2_V4_LISTEN, C2_V4_OTHER_EST],
            [_v6_row(2, b"\x00" * 15 + b"\x01", 9, 80, b"\x00" * 16, 2, 0,
                     C2_PID)])
        # pid change
        run([_v4_row(2, b"\x7f\x00\x00\x01", 80, b"\x7f\x00\x00\x01", 0, 999),
             C2_V4_OTHER_EST])
        # new established on target port
        run([C2_V4_LISTEN, C2_V4_EST_LOCAL])
        # mere enumeration order with same SET is okay (2 rows reordered)
        tcp, proc = self._valid()
        extra_listen = _v4_row(2, b"\xac\x10\x00\x01", 80,
                               b"\xac\x10\x00\x01", 0, C2_PID)
        tcp.first.tables[AF_INET] = _table_image(
            [C2_V4_LISTEN, extra_listen, C2_V4_OTHER_EST])
        tcp.second.tables[AF_INET] = _table_image(
            [extra_listen, C2_V4_LISTEN, C2_V4_OTHER_EST])
        b = self._bind(tcp, proc)
        self.assertEqual(len(b.before_snapshot.rows), 4)
        b.close()

    def test_wrong_birth_image_denied(self):
        # valid-shape field mismatches: one OpenProcess / one CloseHandle
        for birth, image in ((_birth(0x3333, 0x2222), C2_IMAGE),  # low word
                             (C2_BIRTH + 1, C2_IMAGE),  # same low, high word
                             (C2_BIRTH, "C:\\other.exe")):  # different path
            tcp, proc = self._valid()
            with self.assertRaises(WindowsObservationError):
                self._bind(tcp, proc, birth=birth, image=image)
            self.assertEqual(len([e for e in proc.call_trace
                                  if e[0] == "OpenProcess"]), 1)
            self.assertEqual(len([e for e in proc.call_trace
                                  if e[0] == "CloseHandle"]), 1)
        # malformed birth str: argument validation, NO calls anywhere
        tcp, proc = self._valid()
        with self.assertRaises(WindowsObservationError):
            self._bind(tcp, proc, birth="0x1111")
        self.assertEqual(tcp.calls, [])
        self.assertEqual(proc.call_trace, [])
        # access denied: OpenProcess NULL -> one open, no close
        tcp, proc = self._valid()
        proc.open_null = True
        with self.assertRaises(WindowsObservationError):
            self._bind(tcp, proc)
        self.assertEqual(len([e for e in proc.call_trace
                              if e[0] == "OpenProcess"]), 1)
        self.assertEqual([e for e in proc.call_trace
                          if e[0] == "CloseHandle"], [])

    def test_pid_reuse_signaled_old_handle(self):
        tcp, proc = self._valid()
        proc.wait_result = 0  # retained OLD handle signaled
        with self.assertRaises(WindowsObservationError):
            self._bind(tcp, proc)
        self.assertEqual(len([e for e in proc.call_trace
                              if e[0] == "CloseHandle"]), 1)
        self.assertEqual(
            [e for e in proc.call_trace if e[0] == "OpenProcess"],
            [("OpenProcess", 0x00101000, 0, C2_PID)])  # never a new OpenProcess
        self.assertEqual(len(tcp.calls), 4)  # no second TCP sample

    def test_wait_failed_and_signaled_after(self):
        tcp, proc = self._valid()
        proc.wait_result = 0xFFFFFFFF  # WAIT_FAILED on probe
        with self.assertRaises(WindowsObservationError):
            self._bind(tcp, proc)
        self.assertEqual(len([e for e in proc.call_trace
                              if e[0] == "CloseHandle"]), 1)
        tcp, proc = self._valid()
        proc2 = FakeAPISequence(creation_filetime=(0x1111, 0x2222),
                                image_path=C2_IMAGE,
                                wait_sequence=[258, 0])  # timeout then signaled
        with self.assertRaises(WindowsObservationError):
            self._bind(tcp, proc2)
        self.assertEqual(len([e for e in proc2.call_trace
                              if e[0] == "CloseHandle"]), 1)
        self.assertEqual(len(tcp.calls), 8)  # both complete samples then re-probe
        handle = 0x1001  # FakeAPI handle_table assigns 0x1000+1 first
        waits = [e for e in proc2.call_trace
                 if e[0] == "WaitForSingleObject"]
        self.assertEqual(len(waits), 2)
        self.assertEqual(waits[0][1], waits[1][1])  # SAME retained handle
        self.assertEqual(waits[0][2], 0)  # zero-wait probes
        self.assertEqual(len([e for e in proc2.call_trace
                              if e[0] == "OpenProcess"]), 1)
        self.assertEqual(len([e for e in proc2.call_trace
                              if e[0] == "CloseHandle" and e[1] == handle]), 1)

    def test_post_acquisition_observer_exception_cleanup(self):
        # ANY post-acquisition observation exception -> failclosed + one close
        for exc in (OSError("boom"), RuntimeError("bad")):
            tcp, proc = self._valid()
            real_get = tcp.GetExtendedTcpTable

            def get_extended_tcp_table(buf, size_ptr, order, family,
                                       table_class, reserved):
                if len(tcp.calls) >= 4:
                    raise exc
                return real_get(buf, size_ptr, order, family, table_class,
                                reserved)

            tcp.GetExtendedTcpTable = get_extended_tcp_table
            with self.assertRaises(WindowsObservationError):
                self._bind(tcp, proc)
            self.assertEqual(len([e for e in proc.call_trace
                                  if e[0] == "CloseHandle"]), 1)
        # raw WaitForSingleObject exception after origin acquisition
        for seq in ((OSError("wait boom"),), (258, RuntimeError("wait bad"))):
            tcp, proc = self._valid()
            proc2 = FakeAPISequence(creation_filetime=(0x1111, 0x2222),
                                    image_path=C2_IMAGE,
                                    wait_sequence=list(seq))
            with self.assertRaises(WindowsObservationError) as ctx:
                self._bind(tcp, proc2)
            self.assertIs(ctx.exception.__cause__, seq[-1])
            self.assertEqual(len([e for e in proc2.call_trace
                                  if e[0] == "CloseHandle"]), 1)
            self.assertEqual(len(tcp.calls), 4 if len(seq) == 1 else 8)
            handle = 0x1001
            waits = [e for e in proc2.call_trace
                     if e[0] == "WaitForSingleObject"]
            self.assertEqual(len(waits), len(seq))
            self.assertTrue(all(e[1] == handle and e[2] == 0 for e in waits))
            self.assertEqual(len([e for e in proc2.call_trace
                                  if e[0] == "OpenProcess"]), 1)
            self.assertEqual(len([e for e in proc2.call_trace
                                  if e[0] == "CloseHandle" and e[1] == handle]),
                             1)

    def test_second_family_missing_closes_once(self):
        tcp, proc = self._valid()
        tcp.second.tables[AF_INET6] = None  # precise 7-call refusal path
        with self.assertRaises(WindowsObservationError):
            self._bind(tcp, proc)
        self.assertEqual(len(tcp.calls), 7)
        self.assertEqual(len([e for e in proc.call_trace
                              if e[0] == "CloseHandle"]), 1)

    def test_cleanup_failure_surfaces(self):
        tcp, proc = self._valid()
        proc.wait_result = 0  # actual post-acquisition observation failure
        proc.close_ok = False
        with self.assertRaises(WindowsObservationError):
            self._bind(tcp, proc)
        self.assertEqual(len([e for e in proc.call_trace
                              if e[0] == "CloseHandle"]), 1)  # no retry

    def test_coordinate_and_arg_rejects_before_calls(self):
        for before, after, deadline in ((True, 1001.0, 2000.0),
                                        (1000.0, "x", 2000.0),
                                        (1000.0, 1001.0, float("nan")),
                                        (1000.0, 1001.0, float("inf")),
                                        (10 ** 400, 1001.0, 2000.0),
                                        (1001.0, 1000.0, 2000.0),  # backward
                                        (1000.0, 2000.0, 2000.0),  # expired
                                        (1000.0, 2001.0, 2000.0)):  # after>=dl
            tcp, proc = self._valid()
            with self.assertRaises(WindowsObservationError):
                self._bind(tcp, proc, before=before, after=after,
                           deadline=deadline)
            self.assertEqual(tcp.calls, [])
            self.assertEqual(proc.call_trace, [])
        for port, pid, birth, image in ((0, C2_PID, C2_BIRTH, C2_IMAGE),
                                        (65536, C2_PID, C2_BIRTH, C2_IMAGE),
                                        (True, C2_PID, C2_BIRTH, C2_IMAGE),
                                        (80, 0, C2_BIRTH, C2_IMAGE),
                                        (80, C2_PID, True, C2_IMAGE),
                                        (80, C2_PID, C2_BIRTH, "C:x")):
            tcp, proc = self._valid()
            with self.assertRaises(WindowsObservationError):
                self._bind(tcp, proc, port=port, pid=pid, birth=birth,
                           image=image)
            self.assertEqual(tcp.calls, [])
            self.assertEqual(proc.call_trace, [])

    def test_signed_and_equal_coordinates_allowed(self):
        tcp, proc = self._valid()
        b = self._bind(tcp, proc, before=-5.0, after=-5.0, deadline=10.0)
        self.assertEqual(b.sampled_before, -5.0)
        self.assertEqual(b.sampled_after, -5.0)
        b.close()


D1_DATA = b"Q" * 200000
D1_SHA = hashlib.sha256(D1_DATA).hexdigest()
D1_ID = bytes(range(1, 17))
D1_EXPECTED_FACTS = (0x20, 0, 262144, 200000, 1, 0, 0, 0x1234, D1_ID,
                     "\\\\?\\C:\\dir\\file.bin")

_D1_UNSET = object()


class FakeD1API:
    """Fake injected D1 file APIs: closures supporting ctypes argtypes,
    actual output pointers/DWORD values, real ReadFile byte data, exact
    trace. ABI readiness is recorded inside CreateFileW (before acquisition).
    Distinct sentinels: create_result unset -> valid handle, explicit None ->
    NULL; final_path_count unset -> actual path length, explicit 0 -> failed
    API. facts_after applies only after the before triplet completes."""

    def __init__(self, data=D1_DATA, sha=D1_SHA, volume=0x1234, file_id=D1_ID,
                 size=200000, final_path=D1_EXPECTED_FACTS[9],
                 handle=0x123456789, create_result=_D1_UNSET, file_type=1,
                 fail_info_std=False, fail_info_id=False, fail_info_tag=False,
                 facts_after=None, final_path_count=None, short_read=0,
                 read_fail=False, read_exc=None, create_exc=None,
                 close_ok=True, close_exc=None, clock_values=None,
                 file_attributes=0x20, reparse_tag=0, eof_extra=False):
        self.data = data
        self.sha = sha
        self.volume = volume
        self.file_id = file_id
        self.size = size
        self.final_path = final_path
        self.handle_value = handle
        self.create_result = create_result
        self.file_type = file_type
        self.fail_info_std = fail_info_std
        self.fail_info_id = fail_info_id
        self.fail_info_tag = fail_info_tag
        self.facts_after = facts_after
        self.final_path_count = final_path_count
        self.short_read = short_read
        self.read_fail = read_fail
        self.read_exc = read_exc
        self.create_exc = create_exc
        self.close_ok = close_ok
        self.close_exc = close_exc
        self.file_attributes = file_attributes
        self.reparse_tag = reparse_tag
        self.eof_extra = eof_extra
        self.info_calls = 0
        self._offset = 0
        self.abi_ready = False
        self.trace = []
        self.clock_values = list(clock_values or [float(v)
                                                  for v in range(100, 180)])

        def create_file_w(path, access, share, sa, disp, flags, template):
            self.abi_ready = (
                self.CreateFileW.restype is ctypes.c_void_p
                and self.CreateFileW.argtypes == [ctypes.c_wchar_p,
                                                  ctypes.c_uint32,
                                                  ctypes.c_uint32,
                                                  ctypes.c_void_p,
                                                  ctypes.c_uint32,
                                                  ctypes.c_uint32,
                                                  ctypes.c_void_p])
            self.trace.append(("CreateFileW", access, share, disp, flags))
            if self.create_exc is not None:
                raise self.create_exc
            if self.create_result is _D1_UNSET:
                return self.handle_value
            return self.create_result

        def get_file_type(handle):
            self.trace.append(("GetFileType", handle))
            return self.file_type

        def get_file_info_ex(handle, info_class, buf, size):
            self.info_calls += 1
            self.trace.append(("GetFileInformationByHandleEx", handle,
                               info_class))
            after = (self.facts_after is not None and self.info_calls > 3)
            if info_class == 18:
                if self.fail_info_id:
                    return 0
                if size.value != ctypes.sizeof(FileIdInfoStruct):
                    return 0
                out = ctypes.cast(buf,
                                  ctypes.POINTER(FileIdInfoStruct)).contents
                out.VolumeSerialNumber = (self.facts_after[7] if after
                                          else self.volume)
                fid = self.facts_after[8] if after else self.file_id
                for i in range(16):
                    out.FileId[i] = fid[i]
                return 1
            if info_class == 1:
                if self.fail_info_std:
                    return 0
                if size.value != ctypes.sizeof(FileStandardInfoStruct):
                    return 0
                out = ctypes.cast(buf,
                                  ctypes.POINTER(FileStandardInfoStruct)\
                                  ).contents
                out.AllocationSize = (self.facts_after[2] if after
                                      else self.size + 62144)
                out.EndOfFile = self.facts_after[3] if after else self.size
                out.NumberOfLinks = self.facts_after[4] if after else 1
                out.DeletePending = self.facts_after[5] if after else 0
                out.Directory = self.facts_after[6] if after else 0
                return 1
            if self.fail_info_tag:
                return 0
            if size.value != ctypes.sizeof(FileAttributeTagInfoStruct):
                return 0
            out = ctypes.cast(buf,
                              ctypes.POINTER(FileAttributeTagInfoStruct)\
                              ).contents
            out.FileAttributes = (self.facts_after[0] if after
                                  else self.file_attributes)
            out.ReparseTag = (self.facts_after[1] if after
                              else self.reparse_tag)
            return 1

        def get_final_path(handle, buf, cap, flags):
            self.trace.append(("GetFinalPathNameByHandleW", handle, flags))
            if self.final_path_count == 0:
                return 0
            if self.final_path_count is not None and \
                    self.final_path_count > cap:
                return self.final_path_count
            after = (self.facts_after is not None and self.info_calls > 3)
            path = self.facts_after[9] if after else self.final_path
            buf[:len(path)] = path
            return self.final_path_count if self.final_path_count is not None \
                else len(path)

        def read_file(handle, buf, count, got, ov):
            self.trace.append(("ReadFile", handle, count))
            if self.read_exc is not None:
                raise self.read_exc
            if self.read_fail:
                return 0
            if self._offset >= len(self.data):
                if self.eof_extra:
                    data = self.data[:1]
                else:
                    data = b""
            else:
                remaining = len(self.data) - self._offset
                n = min(count, remaining)
                if self.short_read:
                    n = min(n, self.short_read)
                data = self.data[self._offset:self._offset + n]
                self._offset += n
            ctypes.memmove(buf, data, len(data))
            got.contents.value = len(data)
            return 1

        def close_handle(handle):
            self.trace.append(("CloseHandle", handle))
            if self.close_exc is not None:
                raise self.close_exc
            return 1 if self.close_ok else 0

        self.CreateFileW = create_file_w
        self.GetFileType = get_file_type
        self.GetFileInformationByHandleEx = get_file_info_ex
        self.GetFinalPathNameByHandleW = get_final_path
        self.ReadFile = read_file
        self.CloseHandle = close_handle

    def clock(self):
        if self.clock_values:
            return self.clock_values.pop(0)
        return 100.0


class D1FileBindingTests(unittest.TestCase):
    D1_PATH = "C:\\dir\\file.bin"

    def _fake(self, **kw):
        return FakeD1API(**kw)

    def _bind(self, api, path=D1_PATH, sha=D1_SHA, volume=0x1234,
              file_id=D1_ID, size=200000, deadline=200.0):
        return bind_file_bytes(api, path, sha, volume, file_id, size,
                               deadline=deadline, clock=api.clock)

    def test_success_chunk_eof_hash(self):
        api = self._fake()
        b = self._bind(api)
        self.assertIs(type(b), RetainedFileObservation)
        self.assertEqual(b.path, self.D1_PATH)
        self.assertEqual(b.observed_sha256, D1_SHA)
        self.assertEqual(b.expected_size, 200000)
        self.assertEqual(b.volume_serial, 0x1234)
        self.assertEqual(b.file_id, D1_ID)
        h = 0x123456789
        self.assertEqual([e for e in api.trace if e[0] == "ReadFile"],
                         [("ReadFile", h, 65536), ("ReadFile", h, 65536),
                          ("ReadFile", h, 65536), ("ReadFile", h, 3392),
                          ("ReadFile", h, 1)])
        self.assertEqual(api.trace[0], ("CreateFileW", 0x80000000, 1, 3,
                                        0x00200000))
        self.assertEqual([e for e in api.trace
                          if e[0] == "CloseHandle"], [])
        b.close()
        self.assertEqual([e for e in api.trace
                          if e[0] == "CloseHandle"], [("CloseHandle", h)])

    def test_struct_sizes_offsets_abi(self):
        self.assertEqual(ctypes.sizeof(FileIdInfoStruct), 24)
        self.assertEqual(FileIdInfoStruct.VolumeSerialNumber.offset, 0)
        self.assertEqual(FileIdInfoStruct.FileId.offset, 8)
        self.assertEqual(ctypes.sizeof(FileStandardInfoStruct), 24)
        self.assertEqual(FileStandardInfoStruct.EndOfFile.offset, 8)
        self.assertEqual(FileStandardInfoStruct.NumberOfLinks.offset, 16)
        self.assertEqual(ctypes.sizeof(FileAttributeTagInfoStruct), 8)
        api = self._fake()
        b = self._bind(api)
        self.assertTrue(api.abi_ready)  # ABI assigned BEFORE CreateFileW
        self.assertEqual(api.CreateFileW.argtypes, [ctypes.c_wchar_p,
                                                    ctypes.c_uint32,
                                                    ctypes.c_uint32,
                                                    ctypes.c_void_p,
                                                    ctypes.c_uint32,
                                                    ctypes.c_uint32,
                                                    ctypes.c_void_p])
        self.assertIs(api.CreateFileW.restype, ctypes.c_void_p)
        self.assertEqual(api.GetFileInformationByHandleEx.argtypes,
                         [ctypes.c_void_p, ctypes.c_int32, ctypes.c_void_p,
                          ctypes.c_uint32])
        self.assertIs(api.GetFileInformationByHandleEx.restype,
                      ctypes.c_int32)
        self.assertEqual(api.ReadFile.argtypes, [ctypes.c_void_p,
                                                 ctypes.c_void_p,
                                                 ctypes.c_uint32,
                                                 ctypes.POINTER(
                                                     ctypes.c_uint32),
                                                 ctypes.c_void_p])
        self.assertIs(api.CloseHandle.restype, ctypes.c_int32)
        b.close()
        self.assertEqual([e for e in api.trace
                          if e[0] == "CloseHandle"],
                         [("CloseHandle", 0x123456789)])

    def test_malformed_inputs_no_api_calls(self):
        bad_sha = D1_SHA.upper()
        cases = [(self.D1_PATH, bad_sha, 0x1234, D1_ID, 200000),
                 (self.D1_PATH, D1_SHA, 0x1234, D1_ID + b"\x00", 200000),
                 (self.D1_PATH, D1_SHA, 0x1234, D1_ID[:15], 200000),
                 (self.D1_PATH, D1_SHA, True, D1_ID, 200000),
                 (self.D1_PATH, D1_SHA, 0x1234, D1_ID, 0),
                 (self.D1_PATH, D1_SHA, 0x1234, D1_ID, 536870913),
                 (self.D1_PATH, D1_SHA, 0x1234, D1_ID, 1.5),
                 ("\\\\srv\\share\\f.bin", D1_SHA, 0x1234, D1_ID, 200000),
                 ("C:\\dir\\..\\file.bin", D1_SHA, 0x1234, D1_ID, 200000),
                 ("C:\\dir\\f:stream.bin", D1_SHA, 0x1234, D1_ID, 200000),
                 ("C:", D1_SHA, 0x1234, D1_ID, 200000),
                 ("C:\\" + "a" * 32767, D1_SHA, 0x1234, D1_ID, 200000),
                 (self.D1_PATH, "x" * 64, 0x1234, D1_ID, 200000)]
        for path, sha, volume, file_id, size in cases:
            api = self._fake()
            with self.assertRaises(WindowsObservationError):
                self._bind(api, path=path, sha=sha, volume=volume,
                           file_id=file_id, size=size)
            self.assertEqual(api.trace, [])
            self.assertEqual(api.info_calls, 0)

    def test_zero_octet_valid_id(self):
        fid = bytes([1, 0, 3] + list(range(4, 17)))
        api = self._fake(file_id=fid)
        b = self._bind(api, file_id=fid)
        self.assertEqual(b.file_id, fid)
        b.close()

    def test_digest_mismatch(self):
        api = self._fake()
        with self.assertRaises(WindowsObservationError) as ctx:
            self._bind(api, sha=D1_SHA[:-1] + ("0" if D1_SHA[-1] != "0"
                                               else "1"))
        self.assertIn("sha256 digest mismatch", str(ctx.exception))
        self.assertEqual(len([e for e in api.trace
                              if e[0] == "CloseHandle"]), 1)

    def test_after_metadata_mutation_refused(self):
        expected_msgs = {2: "file facts changed between observations",
                         3: "EndOfFile size mismatch",
                         4: "hardlink count not 1",
                         5: "standard info delete/directory",
                         7: "volume serial mismatch",
                         8: "file id mismatch",
                         9: "final path prefix mismatch"}
        for changed in (2, 3, 4, 5, 7, 8, 9):
            facts = list(D1_EXPECTED_FACTS)
            if changed == 8:
                facts[8] = D1_ID[:-1] + b"\x11"
            elif changed == 9:
                facts[9] = "\\\\?\\C:\\dir\\other.bin"
            else:
                facts[changed] = facts[changed] + 1
            api = self._fake(facts_after=tuple(facts))
            with self.assertRaises(WindowsObservationError) as ctx:
                self._bind(api)
            self.assertEqual(str(ctx.exception), expected_msgs[changed])
            self.assertEqual(len([e for e in api.trace
                                  if e[0] == "CloseHandle"]), 1)

    def test_final_path_count_errors(self):
        for count, msg in ((0, "GetFinalPathNameByHandleW count invalid"),
                           (32768, "GetFinalPathNameByHandleW count invalid"),
                           (32769, "GetFinalPathNameByHandleW count invalid"),
                           (10, "GetFinalPathNameByHandleW length inconsistent")):
            api = self._fake(final_path_count=count)
            with self.assertRaises(WindowsObservationError) as ctx:
                self._bind(api)
            self.assertEqual(str(ctx.exception), msg)
            self.assertEqual(len([e for e in api.trace
                                  if e[0] == "CloseHandle"]), 1)

    def test_invalid_handles(self):
        for h in (0, -1, True, (1 << 64) - 1, 1 << 64):
            api = self._fake(create_result=h)
            with self.assertRaises(WindowsObservationError):
                self._bind(api)
            self.assertEqual([e for e in api.trace
                              if e[0] == "CloseHandle"], [])
        api = self._fake(create_result=128)
        b = self._bind(api)
        b.close()
        self.assertEqual([e for e in api.trace
                          if e[0] == "CloseHandle"], [("CloseHandle", 128)])

    def test_syscall_failures(self):
        api = self._fake(create_result=None)  # explicit NULL open
        with self.assertRaises(WindowsObservationError):
            self._bind(api)
        self.assertEqual([e for e in api.trace
                          if e[0] == "CloseHandle"], [])
        for kw in ({"file_type": 2}, {"fail_info_tag": True},
                   {"fail_info_std": True}, {"fail_info_id": True},
                   {"read_fail": True}, {"short_read": 3},
                   {"final_path_count": 0}):
            api = self._fake(**kw)
            with self.assertRaises(WindowsObservationError):
                self._bind(api)
            self.assertEqual(len([e for e in api.trace
                                  if e[0] == "CloseHandle"]), 1)

    def test_true_raised_exceptions(self):
        api = self._fake(create_exc=OSError("denied"))
        with self.assertRaises(WindowsObservationError):
            self._bind(api)
        self.assertEqual([e for e in api.trace
                          if e[0] == "CloseHandle"], [])
        for exc in (OSError("io"), RuntimeError("bad")):
            api = self._fake(read_exc=exc)
            with self.assertRaises(WindowsObservationError) as ctx:
                self._bind(api)
            self.assertIs(ctx.exception.__cause__, exc)
            self.assertEqual(len([e for e in api.trace
                                  if e[0] == "CloseHandle"]), 1)

    def test_clock_failures(self):
        cases = [([200.0, 201.0], 0, 0), ([float("nan")], 0, 0),
                 ([float("inf")], 0, 0), ([10 ** 400], 0, 0),
                 ([100.0, 50.0], 1, 1), ([100.0, 200.0], 1, 1)]
        for values, open_n, close_n in cases:
            api = self._fake(clock_values=list(values))
            with self.assertRaises(WindowsObservationError):
                self._bind(api)
            self.assertEqual(len([e for e in api.trace
                                  if e[0] == "OpenProcess"
                                  or e[0] == "CreateFileW"]), open_n)
            self.assertEqual(len([e for e in api.trace
                                  if e[0] == "CloseHandle"]), close_n)

    def test_close_fail_marks_unusable(self):
        api = self._fake(close_ok=False)
        b = self._bind(api)
        with self.assertRaises(WindowsObservationError):
            b.close()
        self.assertTrue(b.cleanup_failed)
        self.assertEqual(len([e for e in api.trace
                              if e[0] == "CloseHandle"]), 1)
        with self.assertRaises(WindowsObservationError):
            b.close()
        self.assertEqual(len([e for e in api.trace
                              if e[0] == "CloseHandle"]), 1)
        api = self._fake(close_exc=OSError("boom"))
        b = self._bind(api)
        with self.assertRaises(WindowsObservationError):
            b.close()
        self.assertTrue(b.cleanup_failed)
        self.assertEqual(len([e for e in api.trace
                              if e[0] == "CloseHandle"]), 1)

    def test_content_mismatches(self):
        for kw, msg in (({"file_attributes": 0x420}, "reparse/directory"),
                        ({"reparse_tag": 0x1172000}, "reparse tag"),
                        ({"facts_after": (0x20, 0, 262144, 200000, 2, 0,
                                          0, 0x1234, D1_ID,
                                          "\\\\?\\C:\\dir\\file.bin")},
                         "hardlink"),
                        ({"facts_after": (0x20, 0, 262144, 200000, 1, 1,
                                          0, 0x1234, D1_ID,
                                          "\\\\?\\C:\\dir\\file.bin")},
                         "delete/directory"),
                        ({"eof_extra": True}, "extra bytes")):
            api = self._fake(**kw)
            with self.assertRaises(WindowsObservationError) as ctx:
                self._bind(api)
            self.assertIn(msg, str(ctx.exception))
            self.assertEqual(len([e for e in api.trace
                                  if e[0] == "CloseHandle"]), 1)

    def test_factory_and_flags(self):
        with self.assertRaises(WindowsObservationError):
            RetainedFileObservation()
        api = self._fake()
        b = self._bind(api)
        self.assertFalse(b.AUTHORIZES_EXECUTION)
        self.assertFalse(b.WORKSPACE_ATTESTED)
        self.assertFalse(b.IMAGE_BYTES_ATTESTED)
        self.assertFalse(b.FILESYSTEM_ATTESTED)
        self.assertFalse(b.PLATFORM_QUALIFIED)
        self.assertFalse(b.HARD_IO_TIMEOUT_PROVEN)
        self.assertTrue(b.FILE_BYTES_MATCHED)
        with self.assertRaises(WindowsObservationError):
            b.path = "C:\\x"
        with self.assertRaises(WindowsObservationError):
            del b.file_id
        b.close()


_E1_UNSET = object()


class FakeJobAPI:
    """Fake injected E1 job APIs: closures supporting ctypes argtypes,
    actual output pointers/DWORD values, exact trace. ABI readiness recorded
    inside CreateJobObjectW. create_result unset -> valid handle, explicit
    None -> NULL; query_returned unset -> sizeof, explicit value honored."""

    def __init__(self, handle=0x10000001, create_result=_E1_UNSET,
                 set_handle_info=True, get_handle_info=True, handle_flags=0,
                 set_info=True, query_info=True, query_flags=0x2000,
                 query_returned=None, create_exc=None, set_handle_exc=None,
                 get_handle_exc=None, set_info_exc=None, query_info_exc=None,
                 close_ok=True, close_exc=None, clock_values=None):
        self.handle_value = handle
        self.create_result = create_result
        self.set_handle_info = set_handle_info
        self.get_handle_info = get_handle_info
        self.handle_flags = handle_flags
        self.set_info = set_info
        self.query_info = query_info
        self.query_flags = query_flags
        self.query_returned = query_returned
        self.create_exc = create_exc
        self.set_handle_exc = set_handle_exc
        self.get_handle_exc = get_handle_exc
        self.set_info_exc = set_info_exc
        self.query_info_exc = query_info_exc
        self.close_ok = close_ok
        self.close_exc = close_exc
        self.abi_ready = False
        self.trace = []
        self.clock_values = list(clock_values or [float(v)
                                                  for v in range(100, 180)])

        def create_job(sa, name):
            self.abi_ready = (
                self.CreateJobObjectW.restype is ctypes.c_void_p
                and self.CreateJobObjectW.argtypes == [ctypes.c_void_p,
                                                       ctypes.c_wchar_p])
            self.trace.append(("CreateJobObjectW", sa, name))
            if self.create_exc is not None:
                raise self.create_exc
            if self.create_result is _E1_UNSET:
                return self.handle_value
            return self.create_result

        def set_handle(h, mask, flags):
            self.trace.append(("SetHandleInformation", h, mask, flags))
            if self.set_handle_exc is not None:
                raise self.set_handle_exc
            return 1 if self.set_handle_info else 0

        def get_handle(h, flags_ptr):
            self.trace.append(("GetHandleInformation", h))
            if self.get_handle_exc is not None:
                raise self.get_handle_exc
            if not self.get_handle_info:
                return 0
            flags_ptr.contents.value = self.handle_flags
            return 1

        def set_info(h, info_class, buf, size):
            self.trace.append(("SetInformationJobObject", h, info_class))
            if self.set_info_exc is not None:
                raise self.set_info_exc
            if not self.set_info:
                return 0
            out = ctypes.cast(buf, ctypes.POINTER(
                JobExtendedLimitInformationStruct)).contents
            out.BasicLimitInformation.LimitFlags = \
                out.BasicLimitInformation.LimitFlags  # no-op keep width
            return 1

        def query_info(h, info_class, buf, size, returned):
            self.trace.append(("QueryInformationJobObject", h, info_class))
            if self.query_info_exc is not None:
                raise self.query_info_exc
            if not self.query_info:
                return 0
            out = ctypes.cast(buf, ctypes.POINTER(
                JobExtendedLimitInformationStruct)).contents
            out.BasicLimitInformation.LimitFlags = self.query_flags
            returned.contents.value = (self.query_returned
                                       if self.query_returned is not None
                                       else ctypes.sizeof(
                                           JobExtendedLimitInformationStruct))
            return 1

        def close_handle(h):
            self.trace.append(("CloseHandle", h))
            if self.close_exc is not None:
                raise self.close_exc
            return 1 if self.close_ok else 0

        self.CreateJobObjectW = create_job
        self.SetHandleInformation = set_handle
        self.GetHandleInformation = get_handle
        self.SetInformationJobObject = set_info
        self.QueryInformationJobObject = query_info
        self.CloseHandle = close_handle

    def clock(self):
        if self.clock_values:
            return self.clock_values.pop(0)
        return 100.0


class E1ContainmentJobTests(unittest.TestCase):
    def _fake(self, **kw):
        return FakeJobAPI(**kw)

    def _create(self, api, deadline=200.0):
        return create_containment_job(api, deadline=deadline, clock=api.clock)

    def test_success_exact_order_flags(self):
        api = self._fake()
        j = self._create(api)
        self.assertIs(type(j), RetainedContainmentJob)
        self.assertEqual(j.observed_limit_flags, 0x2000)
        self.assertEqual(api.trace[0], ("CreateJobObjectW", None, None))
        self.assertEqual([e[0] for e in api.trace],
                         ["CreateJobObjectW", "SetHandleInformation",
                          "GetHandleInformation", "SetInformationJobObject",
                          "QueryInformationJobObject"])
        self.assertEqual(api.trace[1], ("SetHandleInformation", 0x10000001,
                                        1, 0))
        self.assertEqual(api.trace[3][2], 9)
        self.assertEqual(api.trace[4][2], 9)
        self.assertEqual([e for e in api.trace
                          if e[0] == "CloseHandle"], [])
        j.close()
        self.assertEqual([e for e in api.trace
                          if e[0] == "CloseHandle"],
                         [("CloseHandle", 0x10000001)])

    def test_struct_sizes_offsets_abi(self):
        self.assertEqual(ctypes.sizeof(JobBasicLimitInformationStruct), 64)
        self.assertEqual(JobBasicLimitInformationStruct.LimitFlags.offset,
                         16)
        self.assertEqual(JobBasicLimitInformationStruct.
                         MinimumWorkingSetSize.offset, 24)
        self.assertEqual(JobBasicLimitInformationStruct.Affinity.offset, 48)
        self.assertEqual(ctypes.sizeof(JobIoCountersStruct), 48)
        self.assertEqual(ctypes.sizeof(JobExtendedLimitInformationStruct),
                         144)
        self.assertEqual(JobExtendedLimitInformationStruct.IoInfo.offset, 64)
        self.assertEqual(JobExtendedLimitInformationStruct.
                         ProcessMemoryLimit.offset, 112)
        api = self._fake()
        j = self._create(api)
        self.assertTrue(api.abi_ready)  # ABI BEFORE first CreateJobObjectW
        self.assertEqual(api.SetInformationJobObject.argtypes,
                         [ctypes.c_void_p, ctypes.c_int32, ctypes.c_void_p,
                          ctypes.c_uint32])
        self.assertEqual(api.QueryInformationJobObject.argtypes,
                         [ctypes.c_void_p, ctypes.c_int32, ctypes.c_void_p,
                          ctypes.c_uint32,
                          ctypes.POINTER(ctypes.c_uint32)])
        self.assertIs(api.CloseHandle.restype, ctypes.c_int32)
        j.close()

    def test_invalid_deadline_no_api_calls(self):
        # includes a post-acquisition backwards case ([100,50]): valid first
        # clock -> CreateJobObjectW -> cleanup registered -> backward second
        # clock -> exactly one close, not a no-acquisition error
        for values, expected_trace in (
                ([200.0, 201.0], []), ([float("nan")], []),
                ([float("inf")], []), ([10 ** 400], []),
                ([100.0, 50.0], [("CreateJobObjectW", None, None),
                                 ("CloseHandle", 0x10000001)])):
            api = self._fake(clock_values=list(values))
            with self.assertRaises(WindowsObservationError):
                self._create(api)
            self.assertEqual(api.trace, expected_trace)

    def test_invalid_handles_no_close(self):
        for h in (0, -1, True, None, (1 << 64) - 1, 1 << 64):
            api = self._fake(create_result=h)
            with self.assertRaises(WindowsObservationError):
                self._create(api)
            self.assertEqual([e for e in api.trace
                              if e[0] == "CloseHandle"], [])
        api = self._fake(create_result=128)
        j = self._create(api)
        j.close()
        self.assertEqual([e for e in api.trace
                          if e[0] == "CloseHandle"], [("CloseHandle", 128)])

    def test_syscall_failures_one_close(self):
        for kw in ({"set_handle_info": False}, {"get_handle_info": False},
                   {"set_info": False}, {"query_info": False},
                   {"query_returned": 8}, {"query_flags": 0x1000},
                   {"query_flags": 0x2001}, {"handle_flags": 1},
                   {"handle_flags": 0x10000000}):
            api = self._fake(**kw)
            with self.assertRaises(WindowsObservationError):
                self._create(api)
            self.assertEqual(len([e for e in api.trace
                                  if e[0] == "CloseHandle"]), 1)

    def test_raised_exceptions_one_close(self):
        api = self._fake(create_exc=OSError("denied"))
        with self.assertRaises(WindowsObservationError):
            self._create(api)
        self.assertEqual([e for e in api.trace
                          if e[0] == "CloseHandle"], [])
        for kw in ({"set_handle_exc": OSError("a")},
                   {"get_handle_exc": RuntimeError("b")},
                   {"set_info_exc": OSError("c")},
                   {"query_info_exc": RuntimeError("d")}):
            api = self._fake(**kw)
            with self.assertRaises(WindowsObservationError):
                self._create(api)
            self.assertEqual(len([e for e in api.trace
                                  if e[0] == "CloseHandle"]), 1)

    def test_clock_acquisition_stages(self):
        for values, close_n, expected_trace in (
                ([200.0, 201.0], 0, []),
                ([100.0, 50.0], 1, [("CreateJobObjectW", None, None),
                                    ("CloseHandle", 0x10000001)]),
                ([100.0, 200.0], 1, [("CreateJobObjectW", None, None),
                                     ("CloseHandle", 0x10000001)])):
            api = self._fake(clock_values=list(values))
            with self.assertRaises(WindowsObservationError):
                self._create(api)
            self.assertEqual(len([e for e in api.trace
                                  if e[0] == "CloseHandle"]), close_n)
            self.assertEqual(api.trace, expected_trace)

    def test_close_fail_marks_unusable(self):
        api = self._fake(close_ok=False)
        j = self._create(api)
        with self.assertRaises(WindowsObservationError):
            j.close()
        self.assertTrue(j.cleanup_failed)
        self.assertEqual(len([e for e in api.trace
                              if e[0] == "CloseHandle"]), 1)
        with self.assertRaises(WindowsObservationError):
            j.close()
        self.assertEqual(len([e for e in api.trace
                              if e[0] == "CloseHandle"]), 1)
        api = self._fake(close_exc=OSError("boom"))
        j = self._create(api)
        with self.assertRaises(WindowsObservationError):
            j.close()
        self.assertTrue(j.cleanup_failed)
        self.assertEqual(len([e for e in api.trace
                              if e[0] == "CloseHandle"]), 1)

    def test_factory_and_flags(self):
        with self.assertRaises(WindowsObservationError):
            RetainedContainmentJob()
        api = self._fake()
        j = self._create(api)
        self.assertFalse(j.AUTHORIZES_EXECUTION)
        self.assertFalse(j.PLATFORM_QUALIFIED)
        self.assertFalse(j.CHILD_ASSIGNED)
        self.assertFalse(j.HARD_IO_TIMEOUT_PROVEN)
        with self.assertRaises(WindowsObservationError):
            j.observed_limit_flags = 0
        with self.assertRaises(WindowsObservationError):
            del j.cleanup_failed
        j.close()


if __name__ == "__main__":
    unittest.main()