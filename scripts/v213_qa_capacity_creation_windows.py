"""V12 Win32 creation helper — primitives, registry, clock bridge, begin, prepare, invoke (FAKE API).

ABI layout facts, injected-prototype configuration, pure binding/clock
validators, a private custody slot, fixed custody errors, a private one-slot
registry with _reserve_slot, a sampled clock bridge (_read_clock_ns /
_clock_seconds), a private CreationOwner, a fake-only begin_owned_creation
that invokes the unchanged E1 factory, a fake-only prepare_once (not
qualified yet), and a fake-only invoke_once (no real adapter, no
qualification). No WinDLL loading, no factory/API/clock invocation at
import. All authority/qualification/cleanup flags false. Layout and
validators are pure facts, NOT native qualification.
"""
import ctypes
import math
import threading
import unicodedata
from ctypes import (
    Structure, c_uint32, c_uint16, c_int32, c_void_p, c_size_t, c_wchar_p, c_wchar, c_uint8, POINTER,
)
from v213_qa_capacity_creation_contract import _is_token, _is_sha256, _is_clock, MAX_CLOCK
from v213_qa_capacity_control_windows import (
    create_containment_job, RetainedContainmentJob, JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE,
)
from v213_qa_capacity_control_state import _parse_namespace_lexical, StateValidationError

# Fixed SDK constants (evidence: v12-helper-sdk-constants-01.json)
CREATE_FLAGS = 0x80004
JOB_LIST = 0x2000D
HANDLE_LIST = 0x20002
STARTF_USESTDHANDLES = 0x100
ERROR_INSUFFICIENT_BUFFER = 122

# Fixed-width types
DWORD = c_uint32
WORD = c_uint16
BOOL = c_int32
HANDLE = c_void_p
PVOID = c_void_p
SIZE_T = c_size_t
DWORD_PTR = c_size_t
LPWSTR = c_wchar_p
LPCWSTR = c_wchar_p
LPBYTE = POINTER(c_uint8)
PSIZE_T = POINTER(SIZE_T)
PDWORD = POINTER(DWORD)
PBOOL = POINTER(BOOL)


class STARTUPINFOW(Structure):
    _fields_ = [
        ("cb", DWORD),
        ("lpReserved", LPWSTR),
        ("lpDesktop", LPWSTR),
        ("lpTitle", LPWSTR),
        ("dwX", DWORD),
        ("dwY", DWORD),
        ("dwXSize", DWORD),
        ("dwYSize", DWORD),
        ("dwXCountChars", DWORD),
        ("dwYCountChars", DWORD),
        ("dwFillAttribute", DWORD),
        ("dwFlags", DWORD),
        ("wShowWindow", WORD),
        ("cbReserved2", WORD),
        ("lpReserved2", LPBYTE),
        ("hStdInput", HANDLE),
        ("hStdOutput", HANDLE),
        ("hStdError", HANDLE),
    ]


class STARTUPINFOEXW(Structure):
    _fields_ = [
        ("StartupInfo", STARTUPINFOW),
        ("lpAttributeList", PVOID),
    ]


class PROCESS_INFORMATION(Structure):
    _fields_ = [
        ("hProcess", HANDLE),
        ("hThread", HANDLE),
        ("dwProcessId", DWORD),
        ("dwThreadId", DWORD),
    ]


LPSTARTUPINFOW = POINTER(STARTUPINFOW)
LPPROCESS_INFORMATION = POINTER(PROCESS_INFORMATION)

# All authority/qualification/cleanup flags false (FAKE API, not qualified)
AUTHORIZES_EXECUTION = False
PLATFORM_QUALIFIED = False
IMAGE_BYTES_ATTESTED = False
WORKSPACE_ATTESTED = False
HARD_IO_TIMEOUT_PROVEN = False
CLEANUP_CONFIRMED = False
RETRY_AUTHORIZED = False


def check_windows_abi():
    if ctypes.sizeof(c_void_p) != 8:
        raise ValueError("ABI requires 8-byte pointers")
    if ctypes.sizeof(c_wchar) != 2:
        raise ValueError("ABI requires 2-byte WCHAR")
    if ctypes.sizeof(STARTUPINFOW) != 104:
        raise ValueError("STARTUPINFOW must be 104 bytes")
    if ctypes.sizeof(STARTUPINFOEXW) != 112:
        raise ValueError("STARTUPINFOEXW must be 112 bytes")
    if STARTUPINFOEXW.lpAttributeList.offset != 104:
        raise ValueError("STARTUPINFOEXW attribute pointer must be at offset 104")
    if ctypes.sizeof(PROCESS_INFORMATION) != 24:
        raise ValueError("PROCESS_INFORMATION must be 24 bytes")
    return True


def configure_injected_prototypes(api):
    protos = {
        "InitializeProcThreadAttributeList": ([PVOID, DWORD, DWORD, PSIZE_T], BOOL),
        "UpdateProcThreadAttribute": ([PVOID, DWORD, DWORD_PTR, PVOID, SIZE_T, PVOID, PSIZE_T], BOOL),
        "DeleteProcThreadAttributeList": ([PVOID], None),
        "CreateProcessW": ([LPCWSTR, LPWSTR, PVOID, PVOID, BOOL, DWORD, PVOID, LPCWSTR, LPSTARTUPINFOW, LPPROCESS_INFORMATION], BOOL),
        "GetHandleInformation": ([HANDLE, PDWORD], BOOL),
        "IsProcessInJob": ([HANDLE, HANDLE, PBOOL], BOOL),
        "GetLastError": ([], DWORD),
    }
    resolved = {}
    for name in protos:
        fn = getattr(api, name, None)
        if fn is None or not callable(fn) or not hasattr(fn, "argtypes") or not hasattr(fn, "restype"):
            raise ValueError("missing injected prototype: " + name)
        resolved[name] = fn
    for name, (argtypes, restype) in protos.items():
        resolved[name].argtypes = list(argtypes)
        resolved[name].restype = restype
    return True


def _validate_binding(binding):
    if type(binding) is not dict or len(binding) != 2:
        raise ValueError("INVALID_BINDING")
    for key in binding:
        if type(key) is not str:
            raise ValueError("INVALID_BINDING")
    if set(binding.keys()) != {"run_id", "candidate_sha256"}:
        raise ValueError("INVALID_BINDING")
    run_id = binding["run_id"]
    candidate_sha256 = binding["candidate_sha256"]
    if not _is_token(run_id) or not _is_sha256(candidate_sha256):
        raise ValueError("INVALID_BINDING")
    return (run_id, candidate_sha256)


def _validate_clock_sample(now_ns, previous_ns, deadline_ns):
    if not _is_clock(now_ns):
        raise ValueError("INVALID_CLOCK")
    if previous_ns is not None and not _is_clock(previous_ns):
        raise ValueError("INVALID_CLOCK")
    if not _is_clock(deadline_ns):
        raise ValueError("INVALID_CLOCK")
    if previous_ns is not None and now_ns < previous_ns:
        raise ValueError("CLOCK_REGRESSION")
    if now_ns >= deadline_ns:
        raise ValueError("DEADLINE_EXPIRED")
    return now_ns


_CUSTODY_TOKEN = object()


class _CustodySlot:
    __slots__ = (
        "_api", "_binding", "_deadline_ns", "_clock", "_last_ns", "_phase",
        "_job", "_attribute_storage", "_attribute_values", "_environment",
        "_startup_info", "_process_info", "_original_process_handle",
        "_original_thread_handle", "_prepare_spent", "_invoke_spent", "_lock",
        "_executable", "_cwd", "_stdio", "_attribute_size",
        "_attributes_initialized", "_attribute_delete_attempted",
        "_attribute_delete_completed", "_attribute_delete_unknown",
        "_create_entered", "_create_returned_success",
        "_original_process_id", "_original_thread_id",
    )

    def __init__(self, _token):
        if _token is not _CUSTODY_TOKEN:
            raise ValueError("CUSTODY_SLOT_PRIVATE_CONSTRUCTOR")
        self._api = None
        self._binding = None
        self._deadline_ns = None
        self._clock = None
        self._last_ns = None
        self._phase = "RESERVED"
        self._job = None
        self._attribute_storage = None
        self._attribute_values = ()
        self._environment = None
        self._startup_info = None
        self._process_info = None
        self._original_process_handle = None
        self._original_thread_handle = None
        self._prepare_spent = False
        self._invoke_spent = False
        self._lock = threading.Lock()
        self._executable = None
        self._cwd = None
        self._stdio = ()
        self._attribute_size = 0
        self._attributes_initialized = False
        self._attribute_delete_attempted = False
        self._attribute_delete_completed = False
        self._attribute_delete_unknown = False
        self._create_entered = False
        self._create_returned_success = False
        self._original_process_id = None
        self._original_thread_id = None

    def __repr__(self):
        return "<_CustodySlot nonauthorizing>"


class CreationPreparationError(Exception):
    def __init__(self, message, custody=None):
        super().__init__(message)
        self.message = message
        self.custody = custody

    def __str__(self):
        return self.message

    def __repr__(self):
        return "CreationPreparationError(%r)" % (self.message,)


class CreationInvocationError(Exception):
    def __init__(self, message, custody=None):
        super().__init__(message)
        self.message = message
        self.custody = custody

    def __str__(self):
        return self.message

    def __repr__(self):
        return "CreationInvocationError(%r)" % (self.message,)


_registry_lock = threading.Lock()
_registry_slot = None


def _reserve_slot(api, binding, deadline_ns, clock):
    global _registry_slot
    if not _registry_lock.acquire(blocking=False):
        raise CreationPreparationError("REGISTRY_BUSY", None)
    try:
        if _registry_slot is not None:
            raise CreationPreparationError("HELPER_ALREADY_RESERVED", None)
        slot = _CustodySlot(_CUSTODY_TOKEN)
        _registry_slot = slot
    finally:
        _registry_lock.release()
    try:
        validated_binding = _validate_binding(binding)
        if not _is_clock(deadline_ns):
            raise ValueError("INVALID_DEADLINE")
        if not callable(clock):
            raise ValueError("INVALID_CLOCK_CALLBACK")
        if api is None or type(api) is dict:
            raise ValueError("INVALID_API")
        slot._api = api
        slot._binding = validated_binding
        slot._deadline_ns = deadline_ns
        slot._clock = clock
        return slot
    except Exception:
        slot._phase = "QUARANTINED"
        raise CreationPreparationError("INVALID_RESERVATION", slot) from None
    except BaseException:
        slot._phase = "QUARANTINED"
        raise


def _read_clock_ns(slot):
    now = slot._clock()
    validated = _validate_clock_sample(now, slot._last_ns, slot._deadline_ns)
    slot._last_ns = validated
    return validated


def _clock_seconds(slot):
    seconds = _read_clock_ns(slot) / 1_000_000_000.0
    if not math.isfinite(seconds):
        raise ValueError("CLOCK_SECONDS_NOT_FINITE")
    return seconds


_CREATION_OWNER_TOKEN = object()


class CreationOwner:
    __slots__ = ("_slot",)

    def __init__(self, _token):
        if _token is not _CREATION_OWNER_TOKEN:
            raise ValueError("CREATION_OWNER_PRIVATE_CONSTRUCTOR")
        self._slot = None

    def __repr__(self):
        return "<CreationOwner nonauthorizing>"

    def prepare_once(self, executable, cwd, stdio=None):
        slot = self._slot
        _claim_preparation(slot)
        try:
            _read_clock_ns(slot)
            executable = _validate_creation_path(executable, True)
            cwd = _validate_creation_path(cwd, False)
            job = slot._job
            if type(job) is not RetainedContainmentJob:
                raise ValueError("INVALID_JOB_TYPE")
            if job._api is not slot._api:
                raise ValueError("INVALID_JOB_API")
            if job._closed is not False:
                raise ValueError("INVALID_JOB_CLOSED")
            if job._cleanup_failed is not False:
                raise ValueError("INVALID_JOB_CLEANUP")
            if job._observed_limit_flags != JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE:
                raise ValueError("INVALID_JOB_LIMIT_FLAGS")
            stdio = _validate_stdio(stdio, job._handle)
            _allocate_creation_backing(slot, executable, cwd, stdio)
            _observe_handle_flags(slot, job._handle, 0)
            seen = set()
            for h in stdio:
                if h not in seen:
                    seen.add(h)
                    _observe_handle_flags(slot, h, 1)
            _prepare_attribute_list(slot)
            prepared = PreparedCreation(_PREPARED_CREATION_TOKEN)
            prepared._slot = slot
            _read_clock_ns(slot)
            slot._phase = "PREPARED_UNQUALIFIED"
            return prepared
        except Exception:
            slot._phase = "QUARANTINED"
            _delete_attributes_once(slot)
            raise CreationPreparationError("PREPARATION_UNQUALIFIED", slot) from None
        except BaseException:
            slot._phase = "QUARANTINED"
            _delete_attributes_once(slot)
            raise


def begin_owned_creation(api, binding, deadline_ns, clock):
    slot = _reserve_slot(api, binding, deadline_ns, clock)
    factory_entered = False
    factory_returned = False
    try:
        check_windows_abi()
        _read_clock_ns(slot)
        configure_injected_prototypes(api)
        deadline_seconds = deadline_ns / 1_000_000_000.0
        if not math.isfinite(deadline_seconds):
            raise ValueError("DEADLINE_SECONDS_NOT_FINITE")
        factory_entered = True
        job = create_containment_job(api, deadline=deadline_seconds, clock=lambda: _clock_seconds(slot))
        slot._job = job
        factory_returned = True
        if type(job) is not RetainedContainmentJob:
            raise ValueError("INVALID_JOB_TYPE")
        if job._api is not api:
            raise ValueError("INVALID_JOB_API")
        if job._closed is not False:
            raise ValueError("INVALID_JOB_CLOSED")
        if job._cleanup_failed is not False:
            raise ValueError("INVALID_JOB_CLEANUP")
        if job._observed_limit_flags != JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE:
            raise ValueError("INVALID_JOB_LIMIT_FLAGS")
        _read_clock_ns(slot)
        owner = CreationOwner(_CREATION_OWNER_TOKEN)
        owner._slot = slot
        slot._phase = "JOB_READY_UNQUALIFIED"
        return owner
    except Exception:
        slot._phase = "QUARANTINED"
        if factory_entered and not factory_returned:
            raise CreationPreparationError("JOB_ACQUISITION_OR_RELEASE_UNCONFIRMED", slot) from None
        raise CreationPreparationError("JOB_SETUP_UNQUALIFIED", slot) from None
    except BaseException:
        slot._phase = "QUARANTINED"
        raise


def _validate_creation_path(value, executable):
    if type(value) is not str or not value:
        raise ValueError("INVALID_CREATION_PATH")
    if len(value) > 1024:
        raise ValueError("INVALID_CREATION_PATH")
    for ch in value:
        if unicodedata.category(ch) in ("Cc", "Cf", "Cs"):
            raise ValueError("INVALID_CREATION_PATH")
    if len(value.encode("utf-16-le")) // 2 > 1024:
        raise ValueError("INVALID_CREATION_PATH")
    try:
        normalized, _drive, comps = _parse_namespace_lexical(value)
    except StateValidationError:
        raise ValueError("INVALID_CREATION_PATH")
    if executable:
        if not comps:
            raise ValueError("INVALID_CREATION_PATH")
        final = comps[-1]
        if len(final) <= 4 or not final.lower().endswith(".exe"):
            raise ValueError("INVALID_CREATION_PATH")
    return normalized


def _validate_stdio(stdio, job_handle):
    if type(job_handle) is not int or not (0 < job_handle < 2**31) or (job_handle & 3) != 0:
        raise ValueError("INVALID_STDIO")
    if stdio is None:
        return ()
    if type(stdio) is not dict:
        raise ValueError("INVALID_STDIO")
    if not stdio:
        return ()
    for key in stdio:
        if type(key) is not str:
            raise ValueError("INVALID_STDIO")
    if set(stdio.keys()) != {"stdin", "stdout", "stderr"}:
        raise ValueError("INVALID_STDIO")
    handles = []
    for role in ("stdin", "stdout", "stderr"):
        h = stdio[role]
        if type(h) is not int or not (0 < h < 2**31) or (h & 3) != 0:
            raise ValueError("INVALID_STDIO")
        handles.append(h)
    stdin, stdout, stderr = handles
    if stdin == job_handle or stdout == job_handle or stderr == job_handle:
        raise ValueError("INVALID_STDIO")
    if stdin == stdout or stdin == stderr:
        raise ValueError("INVALID_STDIO")
    return (stdin, stdout, stderr)


def _claim_preparation(slot):
    if not slot._lock.acquire(False):
        raise CreationPreparationError("PREPARATION_BUSY")
    try:
        if slot._prepare_spent or slot._phase != "JOB_READY_UNQUALIFIED":
            raise CreationPreparationError("PREPARATION_UNAVAILABLE")
        slot._prepare_spent = True
        slot._phase = "PREPARING"
    finally:
        slot._lock.release()


_PREPARED_CREATION_TOKEN = object()


class PreparedCreation:
    __slots__ = ("_slot",)

    def __init__(self, _token):
        if _token is not _PREPARED_CREATION_TOKEN:
            raise ValueError("PREPARED_CREATION_PRIVATE_CONSTRUCTOR")
        self._slot = None

    def __repr__(self):
        return "<PreparedCreation nonauthorizing>"

    def invoke_once(self):
        slot = self._slot
        _claim_invocation(slot)
        try:
            _read_clock_ns(slot)
            _validate_invocation_ready(slot)
            _observe_handle_flags(slot, slot._job._handle, 0)
            seen = set()
            for h in slot._stdio:
                if h not in seen:
                    seen.add(h)
                    _observe_handle_flags(slot, h, 1)
            _validate_invocation_ready(slot)
            _read_clock_ns(slot)
            _call_create_capture(slot)
            _validate_created_outputs(slot)
            _observe_created_membership(slot)
            if not _delete_attributes_once(slot):
                raise ValueError("ATTRIBUTE_DELETE_UNCONFIRMED")
            _read_clock_ns(slot)
            outcome = CreationOutcome(_CREATION_OUTCOME_TOKEN)
            outcome._slot = slot
            slot._phase = "CREATED_SUSPENDED_CUSTODY_RETAINED"
            return outcome
        except Exception:
            slot._phase = "QUARANTINED"
            _delete_attributes_once(slot)
            raise CreationInvocationError("QUARANTINED_UNQUALIFIED", slot) from None
        except BaseException:
            slot._phase = "QUARANTINED"
            _delete_attributes_once(slot)
            raise


def _allocate_creation_backing(slot, executable, cwd, stdio):
    slot._executable = executable
    slot._cwd = cwd
    slot._stdio = stdio
    slot._environment = (ctypes.c_char * 2)()
    slot._startup_info = STARTUPINFOEXW()
    slot._startup_info.StartupInfo.cb = 112
    if stdio:
        slot._startup_info.StartupInfo.dwFlags = 0x100
        slot._startup_info.StartupInfo.hStdInput = stdio[0]
        slot._startup_info.StartupInfo.hStdOutput = stdio[1]
        slot._startup_info.StartupInfo.hStdError = stdio[2]
    else:
        slot._startup_info.StartupInfo.dwFlags = 0
        slot._startup_info.StartupInfo.hStdInput = 0
        slot._startup_info.StartupInfo.hStdOutput = 0
        slot._startup_info.StartupInfo.hStdError = 0
    slot._process_info = PROCESS_INFORMATION()
    job_array = (HANDLE * 1)(slot._job._handle)
    if stdio:
        dedup = []
        for h in stdio:
            if h not in dedup:
                dedup.append(h)
        stdio_array = (HANDLE * len(dedup))(*dedup)
        slot._attribute_values = (job_array, stdio_array)
    else:
        slot._attribute_values = (job_array,)
    slot._attribute_size = SIZE_T(0)


def _delete_attributes_once(slot):
    if not slot._attributes_initialized:
        return False
    if slot._attribute_delete_attempted:
        return slot._attribute_delete_completed
    slot._attribute_delete_attempted = True
    try:
        slot._api.DeleteProcThreadAttributeList(ctypes.cast(slot._attribute_storage, ctypes.c_void_p))
        slot._attribute_delete_completed = True
    except BaseException:
        slot._attribute_delete_unknown = True
        slot._attribute_delete_completed = False
    return slot._attribute_delete_completed


def _initialize_attribute_list(slot):
    count = len(slot._attribute_values)
    _read_clock_ns(slot)
    size_ptr = ctypes.byref(slot._attribute_size)
    ok = slot._api.InitializeProcThreadAttributeList(None, count, 0, size_ptr)
    if ok:
        raise ValueError("ATTRIBUTE_INIT_UNEXPECTED_SUCCESS")
    err = slot._api.GetLastError()
    if type(err) is not int or err != 122:
        raise ValueError("ATTRIBUTE_INIT_BAD_ERROR")
    if not (1 <= slot._attribute_size.value <= 65536):
        raise ValueError("ATTRIBUTE_INIT_BAD_SIZE")
    _read_clock_ns(slot)
    allocated = slot._attribute_size.value
    buffer = (ctypes.c_byte * allocated)()
    slot._attribute_storage = buffer
    _read_clock_ns(slot)
    ok = slot._api.InitializeProcThreadAttributeList(buffer, count, 0, size_ptr)
    if not ok:
        raise ValueError("ATTRIBUTE_INIT_FAILED")
    slot._attributes_initialized = True
    if not (0 < slot._attribute_size.value <= allocated):
        raise ValueError("ATTRIBUTE_INIT_BAD_SIZE")
    _read_clock_ns(slot)


def _observe_handle_flags(slot, handle, expected):
    _read_clock_ns(slot)
    flags = DWORD()
    ok = slot._api.GetHandleInformation(handle, ctypes.byref(flags))
    _read_clock_ns(slot)
    if not ok:
        raise ValueError("HANDLE_OBSERVE_FAILED")
    if flags.value != expected:
        raise ValueError("HANDLE_OBSERVE_BAD_FLAGS")


def _prepare_attribute_list(slot):
    _initialize_attribute_list(slot)
    for key, array in zip((JOB_LIST, HANDLE_LIST), slot._attribute_values):
        _read_clock_ns(slot)
        ok = slot._api.UpdateProcThreadAttribute(
            ctypes.cast(slot._attribute_storage, PVOID), 0, key,
            ctypes.cast(array, PVOID), ctypes.sizeof(array), None, None)
        if not ok:
            raise ValueError("ATTRIBUTE_UPDATE_FAILED")
        _read_clock_ns(slot)
    slot._startup_info.lpAttributeList = ctypes.cast(slot._attribute_storage, PVOID)


def _claim_invocation(slot):
    if not slot._lock.acquire(False):
        raise CreationInvocationError("INVOCATION_BUSY")
    try:
        if slot._invoke_spent or slot._phase != "PREPARED_UNQUALIFIED":
            raise CreationInvocationError("INVOCATION_UNAVAILABLE")
        slot._invoke_spent = True
        slot._phase = "INVOKING"
    finally:
        slot._lock.release()


_CREATION_OUTCOME_TOKEN = object()


class CreationOutcome:
    __slots__ = ("_slot",)

    def __init__(self, _token):
        if _token is not _CREATION_OUTCOME_TOKEN:
            raise ValueError("CREATION_OUTCOME_PRIVATE_CONSTRUCTOR")
        self._slot = None

    @property
    def status(self):
        return "CREATED_SUSPENDED_CUSTODY_RETAINED"

    def __repr__(self):
        return "<CreationOutcome nonauthorizing>"

    def __bool__(self):
        raise TypeError("NONAUTHORIZING_OUTCOME")


def _validate_invocation_ready(slot):
    job = slot._job
    if type(job) is not RetainedContainmentJob:
        raise ValueError("INVALID_INVOCATION_STATE")
    if job._api is not slot._api:
        raise ValueError("INVALID_INVOCATION_STATE")
    if job._closed is not False:
        raise ValueError("INVALID_INVOCATION_STATE")
    if job._cleanup_failed is not False:
        raise ValueError("INVALID_INVOCATION_STATE")
    if job._observed_limit_flags != JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE:
        raise ValueError("INVALID_INVOCATION_STATE")
    if type(slot._stdio) is not tuple:
        raise ValueError("INVALID_INVOCATION_STATE")
    if len(slot._stdio) not in (0, 3):
        raise ValueError("INVALID_INVOCATION_STATE")
    if type(slot._attribute_values) is not tuple:
        raise ValueError("INVALID_INVOCATION_STATE")
    if len(slot._attribute_values) != (2 if slot._stdio else 1):
        raise ValueError("INVALID_INVOCATION_STATE")
    stdio = _validate_stdio({"stdin": slot._stdio[0], "stdout": slot._stdio[1], "stderr": slot._stdio[2]} if slot._stdio else None, job._handle)
    job_array = slot._attribute_values[0]
    if len(job_array) != 1 or job_array[0] != job._handle:
        raise ValueError("INVALID_INVOCATION_STATE")
    if slot._stdio:
        stdio_array = slot._attribute_values[1]
        dedup = []
        for h in stdio:
            if h not in dedup:
                dedup.append(h)
        if len(stdio_array) != len(dedup) or list(stdio_array) != dedup:
            raise ValueError("INVALID_INVOCATION_STATE")
    if not slot._attributes_initialized:
        raise ValueError("INVALID_INVOCATION_STATE")
    if slot._attribute_delete_attempted or slot._attribute_delete_completed or slot._attribute_delete_unknown:
        raise ValueError("INVALID_INVOCATION_STATE")
    if slot._attribute_storage is None or slot._environment is None or slot._startup_info is None or slot._process_info is None:
        raise ValueError("INVALID_INVOCATION_STATE")
    if slot._process_info.hProcess is not None or slot._process_info.hThread is not None:
        raise ValueError("INVALID_INVOCATION_STATE")
    if slot._process_info.dwProcessId != 0 or slot._process_info.dwThreadId != 0:
        raise ValueError("INVALID_INVOCATION_STATE")


def _validate_created_outputs(slot):
    process = slot._original_process_handle
    thread = slot._original_thread_handle
    process_id = slot._original_process_id
    thread_id = slot._original_thread_id
    if type(process) is not int or not (0 < process < 2**31) or (process & 3) != 0:
        raise ValueError("INVALID_CREATION_OUTPUT")
    if type(thread) is not int or not (0 < thread < 2**31) or (thread & 3) != 0:
        raise ValueError("INVALID_CREATION_OUTPUT")
    if process == thread:
        raise ValueError("INVALID_CREATION_OUTPUT")
    for h in (process, thread):
        if h == slot._job._handle or h in slot._stdio:
            raise ValueError("INVALID_CREATION_OUTPUT")
    if type(process_id) is not int or not (1 <= process_id <= 0xFFFFFFFF):
        raise ValueError("INVALID_CREATION_OUTPUT")
    if type(thread_id) is not int or not (1 <= thread_id <= 0xFFFFFFFF):
        raise ValueError("INVALID_CREATION_OUTPUT")
    if process_id == thread_id:
        raise ValueError("INVALID_CREATION_OUTPUT")


def _call_create_capture(slot):
    pi = slot._process_info
    slot._create_entered = True
    result = slot._api.CreateProcessW(
        slot._executable, None, None, None, bool(slot._stdio), CREATE_FLAGS,
        ctypes.cast(slot._environment, PVOID), slot._cwd,
        ctypes.cast(ctypes.pointer(slot._startup_info), LPSTARTUPINFOW),
        ctypes.pointer(pi))
    if type(result) is not int or result == 0:
        raise ValueError("CREATE_UNCONFIRMED")
    slot._create_returned_success = True
    slot._original_process_handle = pi.hProcess
    slot._original_thread_handle = pi.hThread
    slot._original_process_id = pi.dwProcessId
    slot._original_thread_id = pi.dwThreadId


def _observe_created_membership(slot):
    _read_clock_ns(slot)
    out = c_int32(0)
    result = slot._api.IsProcessInJob(slot._original_process_handle, slot._job._handle, ctypes.pointer(out))
    _read_clock_ns(slot)
    if type(result) is not int or result == 0 or out.value != 1:
        raise ValueError("MEMBERSHIP_UNCONFIRMED")