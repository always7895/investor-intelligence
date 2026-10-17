"""v213 QA capacity control — retained origin observation foundation (GB-S3A).

Dependency-injected ABI/retained PROCESS HANDLE observation wrapper. NO actual
DLL loading, native calls, TCP, job, launch, or real namespaces. The injected
API object is from trusted future composition, never parsed user config. All
result flags AUTHORIZES_EXECUTION=false, WORKSPACE_ATTESTED=false,
IMAGE_BYTES_ATTESTED=false. This is bounded source step A only; S3 remains
PARTIAL (TCP/secure-path/job pending). No Windows/runtime qualification or
image-byte/workspace verification is claimed from the image path.
"""

import contextlib
import ctypes
import ipaddress
import math
import weakref
from dataclasses import dataclass

from v213_qa_capacity_control_state import remaining_budget, StateValidationError

# --- fixed non-negotiable flags (immutable; never constructor fields) ------
AUTHORIZES_EXECUTION = False
WORKSPACE_ATTESTED = False
IMAGE_BYTES_ATTESTED = False

# --- Windows access rights (Microsoft docs) --------------------------------
# Request PROCESS_QUERY_LIMITED_INFORMATION | SYNCHRONIZE, inherit FALSE.
# No all-access or debug privilege.
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
SYNCHRONIZE = 0x00100000
_ORIGIN_ACCESS = PROCESS_QUERY_LIMITED_INFORMATION | SYNCHRONIZE

# --- WaitForSingleObject results (Microsoft docs) --------------------------
WAIT_OBJECT_0 = 0
WAIT_TIMEOUT = 258
WAIT_FAILED = 0xFFFFFFFF

# --- bounded wait: never INFINITE; floor to bounded finite DWORD ms --------
_MAX_WAIT_MS = 300000

# --- bounded image path buffer (characters, excluding nul) -----------------
_MAX_IMAGE_PATH_CHARS = 32767


class WindowsObservationError(Exception):
    """Raised for failclosed observation errors (access denied, bad response,
    wait errors, close failures, lifecycle violations, malformed arguments)."""


class _FILETIME(ctypes.Structure):
    """FILETIME: two uint32 words; creation = high<<32 | low exactly.

    No seconds conversion/truncation. Size 8, word offsets 0/4.
    """
    _fields_ = [
        ("dwLowDateTime", ctypes.c_uint32),
        ("dwHighDateTime", ctypes.c_uint32),
    ]


# --- exact ctypes ABI prototypes (Microsoft docs) --------------------------
# HANDLE=c_void_p; DWORD=c_uint32; BOOL=c_int32; FILETIME size8, word offsets
# 0/4. Configure exact argtypes/restype on injected API callables (fake
# functions support these attributes).
_ABI = {
    "OpenProcess": {
        "argtypes": [ctypes.c_uint32, ctypes.c_int32, ctypes.c_uint32],
        "restype": ctypes.c_void_p,
    },
    "GetProcessTimes": {
        "argtypes": [ctypes.c_void_p,
                     ctypes.POINTER(_FILETIME),
                     ctypes.POINTER(_FILETIME),
                     ctypes.POINTER(_FILETIME),
                     ctypes.POINTER(_FILETIME)],
        "restype": ctypes.c_int32,
    },
    "QueryFullProcessImageNameW": {
        "argtypes": [ctypes.c_void_p, ctypes.c_uint32,
                     ctypes.c_wchar_p, ctypes.POINTER(ctypes.c_uint32)],
        "restype": ctypes.c_int32,
    },
    "WaitForSingleObject": {
        "argtypes": [ctypes.c_void_p, ctypes.c_uint32],
        "restype": ctypes.c_uint32,
    },
    "CloseHandle": {
        "argtypes": [ctypes.c_void_p],
        "restype": ctypes.c_int32,
    },
}

_REQUIRED_API_NAMES = tuple(_ABI.keys())


def _apply_abi(api):
    """Set exact argtypes/restype on the injected API callables (declarative).

    The fake functions support these attributes. Returns the api unchanged.
    Raises WindowsObservationError if a required callable is missing.
    """
    for name in _REQUIRED_API_NAMES:
        fn = getattr(api, name, None)
        if not callable(fn):
            raise WindowsObservationError("api missing callable: %s" % name)
        spec = _ABI[name]
        fn.argtypes = spec["argtypes"]
        fn.restype = spec["restype"]
    return api


# --- argument validation (BEFORE any calls/custom comparisons) -------------
def _validate_pid(pid):
    """Validate exact pid uint32 nonzero."""
    if type(pid) is not int:
        raise WindowsObservationError("pid must be exact builtin int")
    if pid <= 0 or pid > 0xFFFFFFFF:
        raise WindowsObservationError("pid must be nonzero uint32")


def _validate_birth(birth):
    """Validate birth uint64 nonbool."""
    if type(birth) is not int:
        raise WindowsObservationError("birth must be exact builtin int")
    if birth < 0 or birth > 0xFFFFFFFFFFFFFFFF:
        raise WindowsObservationError("birth must be uint64")


def _is_absolute_windows_path(image):
    """True if image is an absolute Windows file path (drive-letter or UNC)."""
    if len(image) >= 3 and image[1] == ":" and image[2] in ("\\", "/"):
        if image[0].isalpha():
            return True
    if image.startswith("\\\\") or image.startswith("//"):
        return True
    return False


def _validate_image_path(image):
    """Validate builtin image str nonempty/absolute Windows file path/no
    control chars."""
    if type(image) is not str:
        raise WindowsObservationError("image must be exact builtin str")
    if not image:
        raise WindowsObservationError("image must be nonempty")
    for ch in image:
        if ord(ch) < 0x20 or ord(ch) == 0x7F:
            raise WindowsObservationError("image contains control char")
    if not _is_absolute_windows_path(image):
        raise WindowsObservationError(
            "image must be absolute Windows file path")


def _to_bounded_ms(remaining_seconds):
    """Convert remaining seconds to bounded finite DWORD ms <=300000 with floor.

    Clamp remaining seconds to 300 BEFORE multiplication/floor to avoid float
    overflow. Never INFINITE. remaining_seconds is finite non-negative (from
    remaining_budget). Preserves zero and floor fractional waits.
    """
    if remaining_seconds >= 300:
        return _MAX_WAIT_MS  # 300000 (clamped before multiplication)
    ms = math.floor(remaining_seconds * 1000)
    if ms < 0:
        ms = 0
    return ms


def _query_origin(api, handle):
    """Query creation FILETIME and image path through the SAME HANDLE.

    Returns (actual_birth_uint64, actual_image_str). Raises
    WindowsObservationError on failed/missing/invalid response.
    """
    creation = _FILETIME()
    exit_ = _FILETIME()
    kernel = _FILETIME()
    user = _FILETIME()
    ok = api.GetProcessTimes(handle,
                             ctypes.pointer(creation),
                             ctypes.pointer(exit_),
                             ctypes.pointer(kernel),
                             ctypes.pointer(user))
    if not ok:
        raise WindowsObservationError("GetProcessTimes failed")
    actual_birth = (creation.dwHighDateTime << 32) | creation.dwLowDateTime
    buf = ctypes.create_unicode_buffer(_MAX_IMAGE_PATH_CHARS)
    size = ctypes.c_uint32(_MAX_IMAGE_PATH_CHARS)
    ok = api.QueryFullProcessImageNameW(handle, 0, buf, ctypes.pointer(size))
    if not ok:
        raise WindowsObservationError("QueryFullProcessImageNameW failed")
    # validate returned size: nonzero and strictly less than buffer capacity,
    # consistent with a bounded nul-terminated path (including actual length)
    returned_size = size.value
    if returned_size <= 0 or returned_size >= _MAX_IMAGE_PATH_CHARS:
        raise WindowsObservationError(
            "image path length invalid (truncated/invalid response)")
    actual_image = buf.value
    if len(actual_image) != returned_size:
        raise WindowsObservationError(
            "image path length inconsistent with buffer")
    # validate returned path with same exact builtin-string/path checks
    _validate_image_path(actual_image)
    return actual_birth, actual_image


class RetainedOrigin:
    """Opaque owned retained PROCESS HANDLE observation (factory-issued only).

    Rejects public normal arbitrary handle construction. Immutable observed
    facts exposed read-only. Lifecycle owns exactly one close; no
    double-close/wait-after-close. No process termination.
    """
    AUTHORIZES_EXECUTION = False
    WORKSPACE_ATTESTED = False
    IMAGE_BYTES_ATTESTED = False
    __slots__ = ("_api", "_handle", "_pid", "_creation_filetime",
                 "_image_path", "_closed", "_cleanup_failed")

    def __new__(cls, *args, **kwargs):
        raise WindowsObservationError(
            "RetainedOrigin is factory-issued only (bind_origin)")

    def __setattr__(self, name, value):
        raise WindowsObservationError(
            "RetainedOrigin observed facts/flags/ownership are immutable")

    def __delattr__(self, name):
        raise WindowsObservationError(
            "RetainedOrigin observed facts/flags/ownership are immutable")

    @property
    def pid(self):
        return self._pid

    @property
    def creation_filetime(self):
        return self._creation_filetime

    @property
    def image_path(self):
        return self._image_path

    @property
    def cleanup_failed(self):
        return self._cleanup_failed

    def wait_for_exit(self, deadline, now, previous_now):
        """Wait for the retained process to exit.

        Returns True only if WAIT_OBJECT_0 (observed signaled). Timeout ->
        False. Errors -> WindowsObservationError. Reuse remaining_budget;
        convert supplied remaining seconds to bounded finite DWORD ms
        <=300000 with floor (never INFINITE); no implicit clock/read or reset.
        No process termination. Cannot continue after close/ambiguous cleanup.
        """
        if self._closed:
            raise WindowsObservationError("wait after close")
        remaining = remaining_budget(deadline, now, previous_now)
        ms = _to_bounded_ms(remaining)
        result = self._api.WaitForSingleObject(self._handle, ms)
        if result == WAIT_OBJECT_0:
            return True
        if result == WAIT_TIMEOUT:
            return False
        # WAIT_FAILED or any other (including WAIT_ABANDONED) -> error
        raise WindowsObservationError(
            "WaitForSingleObject error: 0x%x" % result)

    def close(self):
        """Close the owned HANDLE exactly once. Failed close not reported as
        successful (retains explicit cleanup-failed state). No double-close."""
        if self._closed:
            raise WindowsObservationError("double close")
        ok = self._api.CloseHandle(self._handle)
        object.__setattr__(self, "_closed", True)
        if not ok:
            object.__setattr__(self, "_cleanup_failed", True)
            raise WindowsObservationError("CloseHandle failed")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()
        return False


def bind_origin(api, pid, expected_creation_filetime, expected_image_path):
    """Bind a retained origin observation to a process.

    Validates exact pid uint32 nonzero, birth uint64 nonbool, builtin image str
    nonempty/absolute Windows file path/no control chars BEFORE any calls/custom
    comparisons. Single OpenProcess, query creation and path through SAME
    HANDLE, compare all64 birth and exact image; mismatch/access-denied/missing/
    invalid response failclosed and close only owned HANDLE. Never reopen by PID
    for waits or substitute new PID state. Returns opaque owned RetainedOrigin.
    """
    # 1) validate args BEFORE any calls/custom comparisons
    _validate_pid(pid)
    _validate_birth(expected_creation_filetime)
    _validate_image_path(expected_image_path)
    # 2) apply ABI to injected callables
    _apply_abi(api)
    # 3) single OpenProcess (inherit FALSE, bounded access); NULL includes
    # None/zero; no bool handle success; keep full pointer-width handles
    handle = api.OpenProcess(_ORIGIN_ACCESS, 0, pid)
    if handle is None or type(handle) is bool or handle == 0:
        raise WindowsObservationError("OpenProcess NULL (access denied)")
    # 4) query creation and path through SAME HANDLE; failclosed performs a
    # single owned cleanup attempt and surfaces cleanup failure
    try:
        actual_birth, actual_image = _query_origin(api, handle)
        if actual_birth != expected_creation_filetime:
            raise WindowsObservationError("creation FILETIME mismatch")
        if actual_image != expected_image_path:
            raise WindowsObservationError("image path mismatch")
    except WindowsObservationError as query_err:
        closed = api.CloseHandle(handle)  # single owned cleanup attempt
        if not closed:
            raise WindowsObservationError(
                "cleanup CloseHandle failed after query failure")
        raise query_err
    # 5) return opaque owned RetainedOrigin (factory internal object.__setattr__)
    origin = object.__new__(RetainedOrigin)
    object.__setattr__(origin, "_api", api)
    object.__setattr__(origin, "_handle", handle)
    object.__setattr__(origin, "_pid", pid)
    object.__setattr__(origin, "_creation_filetime", actual_birth)
    object.__setattr__(origin, "_image_path", actual_image)
    object.__setattr__(origin, "_closed", False)
    object.__setattr__(origin, "_cleanup_failed", False)
    return origin


# --- S3B step1: TCP ctypes layouts and immutable facts ---------------------
# Source-only step: no DLL loading, no GetExtendedTcpTable, no Windows calls.

AF_INET = 2
AF_INET6 = 23
TCP_TABLE_OWNER_PID_ALL = 5
ERROR_INSUFFICIENT_BUFFER = 122
MAX_TABLE_BYTES = 4 * 1024 * 1024  # 4 MiB bounded table budget


class MibTcpRowOwnerPid(ctypes.Structure):
    _fields_ = [("state", ctypes.c_uint32),
                ("localAddr", ctypes.c_uint32),
                ("localPort", ctypes.c_uint32),
                ("remoteAddr", ctypes.c_uint32),
                ("remotePort", ctypes.c_uint32),
                ("pid", ctypes.c_uint32)]


class MibTcp6RowOwnerPid(ctypes.Structure):
    _fields_ = [("localAddr", ctypes.c_uint8 * 16),
                ("localScope", ctypes.c_uint32),
                ("localPort", ctypes.c_uint32),
                ("remoteAddr", ctypes.c_uint8 * 16),
                ("remoteScope", ctypes.c_uint32),
                ("remotePort", ctypes.c_uint32),
                ("state", ctypes.c_uint32),
                ("pid", ctypes.c_uint32)]


class MibTcpTableOwnerPid(ctypes.Structure):
    _fields_ = [("dwNumEntries", ctypes.c_uint32),
                ("table", MibTcpRowOwnerPid * 1)]


class MibTcp6TableOwnerPid(ctypes.Structure):
    _fields_ = [("dwNumEntries", ctypes.c_uint32),
                ("table", MibTcp6RowOwnerPid * 1)]


assert ctypes.sizeof(MibTcpRowOwnerPid) == 24
assert ctypes.sizeof(MibTcp6RowOwnerPid) == 56
assert MibTcpTableOwnerPid.table.offset == 4
assert MibTcp6TableOwnerPid.table.offset == 4
assert ctypes.sizeof(MibTcpTableOwnerPid) == 28
assert ctypes.sizeof(MibTcp6TableOwnerPid) == 60


@dataclass(frozen=True, slots=True)
class TcpRowFact:
    family: int
    local_address: str
    local_port: int
    local_scope_id: int
    remote_address: str
    remote_port: int
    remote_scope_id: int
    state: int
    pid: int


class TcpSnapshot:
    """Opaque factory-issued TCP snapshot; immutable; no authorization."""
    AUTHORIZES_EXECUTION = False
    ATOMIC_SNAPSHOT = False
    PROCESS_BIRTHS_ATTESTED = False
    LISTENER_IDENTITY_ATTESTED = False
    __slots__ = ("_rows", "_sampled_at", "__weakref__")

    def __new__(cls, *args, **kwargs):
        raise WindowsObservationError(
            "TcpSnapshot is factory-issued only (_issue_tcp_snapshot)")

    def __setattr__(self, name, value):
        raise WindowsObservationError("TcpSnapshot is immutable")

    def __delattr__(self, name):
        raise WindowsObservationError("TcpSnapshot is immutable")

    @property
    def rows(self):
        return self._rows

    @property
    def sampled_at(self):
        return self._sampled_at


_issued_tcp_snapshots = weakref.WeakValueDictionary()


def _validate_sampled_at(sampled_at):
    """Exact builtin int/float nonbool finite; huge-int OverflowError refused."""
    if isinstance(sampled_at, bool) or type(sampled_at) not in (int, float):
        raise WindowsObservationError(
            "sampled_at must be exact builtin int/float")
    try:
        finite = math.isfinite(sampled_at)
    except OverflowError:
        finite = False  # huge int cannot represent a finite timestamp
    if not finite:
        raise WindowsObservationError("sampled_at must be finite")


def _issue_tcp_snapshot(rows, sampled_at):
    """Private factory-issue; only the later collector uses it (source-only)."""
    if type(rows) is not tuple:
        raise WindowsObservationError("rows must be exact builtin tuple")
    for row in rows:
        if type(row) is not TcpRowFact:
            raise WindowsObservationError("row must be exact TcpRowFact")
    _validate_sampled_at(sampled_at)
    snap = object.__new__(TcpSnapshot)
    object.__setattr__(snap, "_rows", rows)
    object.__setattr__(snap, "_sampled_at", sampled_at)
    _issued_tcp_snapshots[id(snap)] = snap
    return snap


def is_factory_issued_tcp_snapshot(snap):
    """Exact-type then identity-preserving registry membership check."""
    if type(snap) is not TcpSnapshot:
        return False
    return _issued_tcp_snapshots.get(id(snap)) is snap


def _decode_tcp_table(data, family):
    """Pure bounded decode of a raw TCP table bytes image; no native calls."""
    if type(data) is not bytes:
        raise WindowsObservationError("data must be exact builtin bytes")
    if isinstance(family, bool) or type(family) is not int:
        raise WindowsObservationError("family must be exact builtin int")
    if family not in (AF_INET, AF_INET6):
        raise WindowsObservationError("family must be AF_INET(2)/AF_INET6(23)")
    if len(data) > MAX_TABLE_BYTES:
        raise WindowsObservationError("data exceeds MAX_TABLE_BYTES")
    if len(data) < 4:
        raise WindowsObservationError("data shorter than uint32 count header")
    rowsize = (ctypes.sizeof(MibTcpRowOwnerPid) if family == AF_INET
               else ctypes.sizeof(MibTcp6RowOwnerPid))
    count = int.from_bytes(data[0:4], "little")
    if count > (MAX_TABLE_BYTES - 4) // rowsize:
        raise WindowsObservationError("row count overflows bounded budget")
    if len(data) != 4 + count * rowsize:
        raise WindowsObservationError("data size not exact 4+count*rowsize")
    rows = []
    seen = set()
    for i in range(count):
        row = data[4 + i * rowsize:4 + (i + 1) * rowsize]  # bounded slice
        if family == AF_INET:
            state = int.from_bytes(row[0:4], "little")
            local_addr = str(ipaddress.IPv4Address(row[4:8]))
            local_port = int.from_bytes(row[8:10], "big")
            remote_addr = str(ipaddress.IPv4Address(row[12:16]))
            remote_port = int.from_bytes(row[16:18], "big")
            pid = int.from_bytes(row[20:24], "little")
            local_scope = 0
            remote_scope = 0
        else:
            local_addr = str(ipaddress.IPv6Address(row[0:16]))
            local_scope = int.from_bytes(row[16:20], "little")
            local_port = int.from_bytes(row[20:22], "big")
            remote_addr = str(ipaddress.IPv6Address(row[24:40]))
            remote_scope = int.from_bytes(row[40:44], "little")
            remote_port = int.from_bytes(row[44:46], "big")
            state = int.from_bytes(row[48:52], "little")
            pid = int.from_bytes(row[52:56], "little")
        if not 1 <= state <= 12:
            raise WindowsObservationError("state outside 1..12")
        if state in (2, 5) and pid == 0:
            raise WindowsObservationError(
                "LISTEN/ESTABLISHED requires nonzero pid")
        key = (family, local_addr, local_port, local_scope,
               remote_addr, remote_port, remote_scope, state, pid)
        if key in seen:
            raise WindowsObservationError("duplicate exact row")
        seen.add(key)
        rows.append(TcpRowFact(*key))
    return tuple(rows)


def _collect_one_family(api, family):
    """Exactly two GetExtendedTcpTable calls (sizing + fill); failclosed."""
    fn = api.GetExtendedTcpTable
    fn.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_uint32),
                   ctypes.c_int32, ctypes.c_uint32, ctypes.c_int32,
                   ctypes.c_uint32]
    fn.restype = ctypes.c_uint32
    size = ctypes.c_uint32(0)
    rc = fn(None, ctypes.pointer(size), 0, family, TCP_TABLE_OWNER_PID_ALL, 0)
    if rc != ERROR_INSUFFICIENT_BUFFER:
        raise WindowsObservationError(
            "GetExtendedTcpTable sizing rc != ERROR_INSUFFICIENT_BUFFER")
    required = size.value
    if required < 4 or required > MAX_TABLE_BYTES:
        raise WindowsObservationError("GetExtendedTcpTable size out of bounds")
    buf = ctypes.create_string_buffer(required)  # allocated only after bounds
    size = ctypes.c_uint32(required)  # fill inputs allocated capacity
    rc = fn(buf, ctypes.pointer(size), 0, family, TCP_TABLE_OWNER_PID_ALL, 0)
    if rc != 0:
        raise WindowsObservationError("GetExtendedTcpTable fill rc != 0")
    returned = size.value
    if returned < 4 or returned > required:
        raise WindowsObservationError(
            "GetExtendedTcpTable returned size invalid")
    return _decode_tcp_table(buf.raw[:returned], family)


def collect_tcp_owner_tables(api, sampled_at):
    """Injected dual-family TCP collector; snapshot only after both succeed."""
    _validate_sampled_at(sampled_at)  # validated BEFORE any API calls
    try:
        fn = api.GetExtendedTcpTable
    except AttributeError:
        raise WindowsObservationError("GetExtendedTcpTable missing on api")
    if not callable(fn):
        raise WindowsObservationError("GetExtendedTcpTable must be callable")
    v4 = _collect_one_family(api, AF_INET)
    v6 = _collect_one_family(api, AF_INET6)
    return _issue_tcp_snapshot(tuple(v4) + tuple(v6), sampled_at)


def classify_tcp_conflicts(snapshot, port):
    """Immutable (established, listeners) conflict view; no exemptions."""
    if isinstance(port, bool) or type(port) is not int:
        raise WindowsObservationError("port must be exact builtin int")
    if not 1 <= port <= 65535:
        raise WindowsObservationError("port outside 1..65535")
    if not is_factory_issued_tcp_snapshot(snapshot):
        raise WindowsObservationError(
            "snapshot must be factory-issued (registry identity)")
    established = []
    listeners = []
    for row in snapshot.rows:
        if row.state == 5 and (row.local_port == port
                               or row.remote_port == port):
            established.append(row)
        elif row.state == 2 and row.local_port == port:
            listeners.append(row)
    return tuple(established), tuple(listeners)


# --- S3C: retained listener/process binding (injected source sub-slice) ---
# Expected-process CLAIM matching and retained HANDLE evidence, NOT trusted
# operator authority or final filesystem/workspace/image-byte attestation.
# Real platform and atomic snapshot remain unproven; false flags preserved.
# Input observations are explicit test coordinates, NOT certified fresh OS
# timestamps. No DLL/Windows/socket/native calls anywhere in this sub-slice.


class RetainedListenerBinding:
    """Opaque immutable binding owning exactly one RetainedOrigin.

    Factory-issued only (bind_listener_process). Normal construction and
    ordinary assignment/deletion are forbidden. Expected-claim matching may
    expose EXPECTED_PROCESS_CLAIMS_MATCHED=True; no LISTENER_IDENTITY or
    full-authority promotion from fake data. No PID polling/reopen, no
    process termination. Not a sandbox against malicious Python memory/API
    injection.
    """
    AUTHORIZES_EXECUTION = False
    ATOMIC_SNAPSHOT = False
    IMAGE_BYTES_ATTESTED = False
    WORKSPACE_ATTESTED = False
    EXPECTED_PROCESS_CLAIMS_MATCHED = True
    __slots__ = ("_origin", "_pid", "_creation_filetime", "_image_path",
                 "_sampled_before", "_sampled_after",
                 "_before_snapshot", "_after_snapshot")

    def __new__(cls, *args, **kwargs):
        raise WindowsObservationError(
            "RetainedListenerBinding is factory-issued only")

    def __setattr__(self, name, value):
        raise WindowsObservationError("RetainedListenerBinding is immutable")

    def __delattr__(self, name):
        raise WindowsObservationError("RetainedListenerBinding is immutable")

    @property
    def pid(self):
        return self._pid

    @property
    def creation_filetime(self):
        return self._creation_filetime

    @property
    def image_path(self):
        return self._image_path

    @property
    def sampled_before(self):
        return self._sampled_before

    @property
    def sampled_after(self):
        return self._sampled_after

    @property
    def before_snapshot(self):
        return self._before_snapshot

    @property
    def after_snapshot(self):
        return self._after_snapshot

    def close(self):
        self._origin.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()
        return False


def _validate_sample_coordinates(observed_before, observed_after, deadline):
    """Exact finite nonbool signed coordinates; positive deadline budgets."""
    for name, value in (("observed_before", observed_before),
                        ("observed_after", observed_after),
                        ("deadline", deadline)):
        if isinstance(value, bool) or type(value) not in (int, float):
            raise WindowsObservationError(
                "%s must be exact builtin int/float" % name)
        try:
            finite = math.isfinite(value)
        except OverflowError:
            finite = False
        if not finite:
            raise WindowsObservationError("%s must be finite" % name)
    if observed_before > observed_after or observed_after >= deadline:
        raise WindowsObservationError(
            "coordinates must satisfy before<=after<deadline")
    # accepted remaining_budget (signed coordinates permitted); no clock resets
    try:
        if remaining_budget(deadline, observed_before, observed_before) <= 0:
            raise WindowsObservationError(
                "deadline budget not positive at observed_before")
        if remaining_budget(deadline, observed_after, observed_before) <= 0:
            raise WindowsObservationError(
                "deadline budget not positive at observed_after")
    except StateValidationError as err:
        raise WindowsObservationError(
            "coordinate budget validation failed") from err


def _classify_port_conflicts(snapshot, port):
    """(established, listeners) for one explicit port coordinate."""
    established, listeners = classify_tcp_conflicts(snapshot, port)
    return established, listeners


def bind_listener_process(process_api, tcp_api, pid,
                          expected_creation_filetime, expected_image_path,
                          port, *, observed_before, observed_after, deadline):
    """Bind a retained listener/process observation (injected APIs only).

    0) validate ALL explicit arguments before any API calls; 1) collect both
    families at observed_before and classify port (any matching ESTABLISHED
    local OR remote refuses, no PID/Pi/self exemption; >=1 matching LISTEN
    local-port row and ALL such listeners owned by exactly expected pid);
    2) single bind_origin; 3) zero-wait probe of the retained HANDLE (signaled
    refuses, WAIT_FAILED propagates); 4) second both-family snapshot at
    observed_after with same conflict/owner requirements and EXACT same
    listener row set, then re-probe the SAME retained HANDLE; 5) return owned
    immutable binding. Any post-origin failure closes that origin exactly
    once; cleanup failure surfaces, never success. No retry/reopen, no new
    HANDLE/PID substitution, no process termination.
    """
    # 0) validate everything BEFORE any API calls
    _validate_pid(pid)
    _validate_birth(expected_creation_filetime)
    _validate_image_path(expected_image_path)
    if isinstance(port, bool) or type(port) is not int:
        raise WindowsObservationError("port must be exact builtin int")
    if not 1 <= port <= 65535:
        raise WindowsObservationError("port outside 1..65535")
    _validate_sample_coordinates(observed_before, observed_after, deadline)
    # 1) before snapshot: conflict + listener ownership claims
    before = collect_tcp_owner_tables(tcp_api, observed_before)
    established, listeners = _classify_port_conflicts(before, port)
    if established:
        raise WindowsObservationError(
            "matching ESTABLISHED row on target port")
    if not listeners:
        raise WindowsObservationError("no matching LISTEN row on target port")
    for row in listeners:
        if row.pid != pid:
            raise WindowsObservationError(
                "listener not owned by exactly expected pid")
    # 2) single owned retained handle; structural ExitStack ownership guard
    origin = bind_origin(process_api, pid, expected_creation_filetime,
                         expected_image_path)
    try:
        with contextlib.ExitStack() as stack:
            stack.callback(origin.close)  # exactly once on any unwind
            # 3) zero-wait probe of the retained HANDLE
            if origin.wait_for_exit(observed_before, observed_before,
                                    observed_before):
                raise WindowsObservationError(
                    "retained process already signaled")
            # 4) after snapshot: same requirements + exact listener row set
            after = collect_tcp_owner_tables(tcp_api, observed_after)
            established2, listeners2 = _classify_port_conflicts(after, port)
            if established2:
                raise WindowsObservationError(
                    "matching ESTABLISHED row on target port (after)")
            if not listeners2:
                raise WindowsObservationError(
                    "no matching LISTEN row on target port (after)")
            for row in listeners2:
                if row.pid != pid:
                    raise WindowsObservationError(
                        "listener not owned by exactly expected pid (after)")
            key = lambda r: (r.family, r.local_address, r.local_port,
                             r.local_scope_id, r.remote_address,
                             r.remote_port, r.remote_scope_id, r.state,
                             r.pid)
            if sorted(map(key, listeners)) != sorted(map(key, listeners2)):
                raise WindowsObservationError(
                    "listener row set changed between snapshots")
            if origin.wait_for_exit(observed_after, observed_after,
                                    observed_after):
                raise WindowsObservationError(
                    "retained process signaled before/after")
            # 5) owned immutable binding inside the guarded block
            binding = object.__new__(RetainedListenerBinding)
            object.__setattr__(binding, "_origin", origin)
            object.__setattr__(binding, "_pid", pid)
            object.__setattr__(binding, "_creation_filetime",
                               expected_creation_filetime)
            object.__setattr__(binding, "_image_path", expected_image_path)
            object.__setattr__(binding, "_sampled_before", observed_before)
            object.__setattr__(binding, "_sampled_after", observed_after)
            object.__setattr__(binding, "_before_snapshot", before)
            object.__setattr__(binding, "_after_snapshot", after)
            # only after full construction: transfer cleanup obligation
            stack.pop_all()
            return binding
    except WindowsObservationError:
        raise
    except Exception as err:
        raise WindowsObservationError(
            "listener binding observation failed") from err


# --- S3D1: retained file HANDLE / exact byte observation (injected only) ---
# Caller pins are CLAIMS, not authority. Exact image bytes MATCHED through
# the retained handle, NOT process loaded-image attestation. No DLL loading,
# no launch/HTTP/host native operations. Synchronous Win32 I/O can block:
# hard IO timeout is NOT proven (real deadline cancellation is D2/platform).
import hashlib  # D1 only: exact byte digest through the retained handle

from v213_qa_capacity_control_state import _parse_namespace_lexical

GENERIC_READ = 0x80000000
FILE_SHARE_READ = 0x00000001
OPEN_EXISTING = 3
FILE_FLAG_OPEN_REPARSE_POINT = 0x00200000
FILE_TYPE_DISK = 1
FILE_ATTRIBUTE_REPARSE_POINT = 0x000000400
FILE_ATTRIBUTE_DIRECTORY = 0x00000010
FileStandardInfo = 1
FileAttributeTagInfo = 9
FileIdInfo = 18
_D1_MAX_CHUNK = 65536
_D1_MAX_PATH_CHARS = 32768
_D1_MAX_COMPONENTS = 128
_D1_MAX_SIZE = 536870912


class FileIdInfoStruct(ctypes.Structure):
    _fields_ = [("VolumeSerialNumber", ctypes.c_uint64),
                ("FileId", ctypes.c_uint8 * 16)]


class FileStandardInfoStruct(ctypes.Structure):
    _fields_ = [("AllocationSize", ctypes.c_int64),
                ("EndOfFile", ctypes.c_int64),
                ("NumberOfLinks", ctypes.c_uint32),
                ("DeletePending", ctypes.c_uint8),
                ("Directory", ctypes.c_uint8)]


class FileAttributeTagInfoStruct(ctypes.Structure):
    _fields_ = [("FileAttributes", ctypes.c_uint32),
                ("ReparseTag", ctypes.c_uint32)]


class RetainedFileObservation:
    """Opaque immutable retained file HANDLE observation (factory only)."""
    AUTHORIZES_EXECUTION = False
    WORKSPACE_ATTESTED = False
    IMAGE_BYTES_ATTESTED = False
    FILESYSTEM_ATTESTED = False
    PLATFORM_QUALIFIED = False
    HARD_IO_TIMEOUT_PROVEN = False
    FILE_BYTES_MATCHED = True
    __slots__ = ("_api", "_handle", "_path", "_expected_size",
                 "_volume_serial", "_file_id", "_observed_sha256",
                 "_closed", "_cleanup_failed")

    def __new__(cls, *args, **kwargs):
        raise WindowsObservationError(
            "RetainedFileObservation is factory-issued only")

    def __setattr__(self, name, value):
        raise WindowsObservationError("RetainedFileObservation is immutable")

    def __delattr__(self, name):
        raise WindowsObservationError("RetainedFileObservation is immutable")

    @property
    def path(self):
        return self._path

    @property
    def expected_size(self):
        return self._expected_size

    @property
    def volume_serial(self):
        return self._volume_serial

    @property
    def file_id(self):
        return self._file_id

    @property
    def observed_sha256(self):
        return self._observed_sha256

    @property
    def cleanup_failed(self):
        return self._cleanup_failed

    def close(self):
        """Close the owned file HANDLE exactly once; failure surfaces."""
        if self._closed:
            raise WindowsObservationError("double close")
        object.__setattr__(self, "_closed", True)  # unusable before attempt
        try:
            ok = self._api.CloseHandle(self._handle)
        except Exception as err:
            object.__setattr__(self, "_cleanup_failed", True)
            raise WindowsObservationError("CloseHandle failed") from err
        if not ok:
            object.__setattr__(self, "_cleanup_failed", True)
            raise WindowsObservationError("CloseHandle failed")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()
        return False


def _d1_configure_abi(api):
    """Validate required injected callables, then exact fixed-width Win32
    prototypes. MUST precede CreateFileW (no native default int truncation)."""
    for name in ("CreateFileW", "GetFileType",
                 "GetFileInformationByHandleEx", "GetFinalPathNameByHandleW",
                 "ReadFile", "CloseHandle"):
        if not callable(getattr(api, name, None)):
            raise WindowsObservationError("required injected API missing")
    api.CreateFileW.argtypes = [ctypes.c_wchar_p, ctypes.c_uint32,
                                ctypes.c_uint32, ctypes.c_void_p,
                                ctypes.c_uint32, ctypes.c_uint32,
                                ctypes.c_void_p]
    api.CreateFileW.restype = ctypes.c_void_p
    api.GetFileType.argtypes = [ctypes.c_void_p]
    api.GetFileType.restype = ctypes.c_uint32
    api.GetFileInformationByHandleEx.argtypes = [ctypes.c_void_p,
                                                 ctypes.c_int32,
                                                 ctypes.c_void_p,
                                                 ctypes.c_uint32]
    api.GetFileInformationByHandleEx.restype = ctypes.c_int32
    api.GetFinalPathNameByHandleW.argtypes = [ctypes.c_void_p,
                                              ctypes.c_wchar_p,
                                              ctypes.c_uint32,
                                              ctypes.c_uint32]
    api.GetFinalPathNameByHandleW.restype = ctypes.c_uint32
    api.ReadFile.argtypes = [ctypes.c_void_p, ctypes.c_void_p,
                             ctypes.c_uint32, ctypes.POINTER(ctypes.c_uint32),
                             ctypes.c_void_p]
    api.ReadFile.restype = ctypes.c_int32
    api.CloseHandle.argtypes = [ctypes.c_void_p]
    api.CloseHandle.restype = ctypes.c_int32


class _D1BudgetChecker:
    """Monotonic budget tracker: one clock() sample per check, cause kept."""

    def __init__(self, deadline):
        if isinstance(deadline, bool) or type(deadline) not in (int, float):
            raise WindowsObservationError(
                "deadline must be exact builtin int/float")
        try:
            finite = math.isfinite(deadline)
        except OverflowError:
            finite = False
        if not finite:
            raise WindowsObservationError("deadline must be finite")
        self._deadline = deadline
        self._previous = None

    def check(self, clock):
        now = clock()
        if isinstance(now, bool) or type(now) not in (int, float):
            raise WindowsObservationError(
                "clock must return exact builtin int/float")
        try:
            finite = math.isfinite(now)
        except OverflowError:
            finite = False
        if not finite:
            raise WindowsObservationError("clock must return finite")
        if self._previous is None:
            self._previous = now
        if remaining_budget(self._deadline, now, self._previous) <= 0:
            raise WindowsObservationError("deadline budget not positive")
        self._previous = now


def _d1_validate_file_path(path):
    """Accepted S2 lexical parser: strict local drive-rooted named file."""
    if type(path) is not str:
        raise WindowsObservationError("path must be exact builtin str")
    if len(path) >= _D1_MAX_PATH_CHARS:
        raise WindowsObservationError("path exceeds bounded length")
    try:
        normalized, _drive, components = _parse_namespace_lexical(path)
    except StateValidationError as err:
        raise WindowsObservationError(
            "path rejected by lexical parser") from err
    if len(components) < 1:
        raise WindowsObservationError("path must be a named file")
    if len(components) > _D1_MAX_COMPONENTS:
        raise WindowsObservationError("too many path components")
    return normalized


def _d1_read_file_sha256(api, handle, expected_size, budget, clock):
    """Bounded <=65536 reads on the SAME handle; exact EOF semantics."""
    digest = hashlib.sha256()
    consumed = 0
    while consumed < expected_size:
        chunk = min(_D1_MAX_CHUNK, expected_size - consumed)
        buf = ctypes.create_string_buffer(chunk)
        got = ctypes.c_uint32(0)
        budget.check(clock)
        if not api.ReadFile(handle, buf, chunk, ctypes.pointer(got), None):
            raise WindowsObservationError("ReadFile failed")
        budget.check(clock)
        if got.value != chunk:
            raise WindowsObservationError("ReadFile short read")
        digest.update(buf.raw[:chunk])
        consumed += chunk
    probe = ctypes.create_string_buffer(1)
    got = ctypes.c_uint32(0)
    budget.check(clock)
    if not api.ReadFile(handle, probe, 1, ctypes.pointer(got), None):
        raise WindowsObservationError("ReadFile EOF probe failed")
    budget.check(clock)
    if got.value != 0:
        raise WindowsObservationError("ReadFile returned extra bytes")
    return digest.hexdigest()


def _d1_observe_file_info(api, handle, budget, clock):
    """Attribute tag + standard + identity + final path on SAME handle.

    Budget checked before AND after every observation syscall; final path
    count must satisfy 0<count<capacity and match the returned string length.
    """
    tag = FileAttributeTagInfoStruct()
    size = ctypes.c_uint32(ctypes.sizeof(tag))
    budget.check(clock)
    if not api.GetFileInformationByHandleEx(handle, FileAttributeTagInfo,
                                            ctypes.byref(tag), size):
        raise WindowsObservationError("GetFileInformationByHandleEx tag failed")
    budget.check(clock)
    std = FileStandardInfoStruct()
    size = ctypes.c_uint32(ctypes.sizeof(std))
    budget.check(clock)
    if not api.GetFileInformationByHandleEx(handle, FileStandardInfo,
                                            ctypes.byref(std), size):
        raise WindowsObservationError("GetFileInformationByHandleEx std failed")
    budget.check(clock)
    fid = FileIdInfoStruct()
    size = ctypes.c_uint32(ctypes.sizeof(fid))
    budget.check(clock)
    if not api.GetFileInformationByHandleEx(handle, FileIdInfo,
                                            ctypes.byref(fid), size):
        raise WindowsObservationError("GetFileInformationByHandleEx id failed")
    budget.check(clock)
    pathbuf = ctypes.create_unicode_buffer(_D1_MAX_PATH_CHARS)
    budget.check(clock)
    count = api.GetFinalPathNameByHandleW(handle, pathbuf,
                                          _D1_MAX_PATH_CHARS, 0)
    budget.check(clock)
    if not 0 < count < _D1_MAX_PATH_CHARS:
        raise WindowsObservationError("GetFinalPathNameByHandleW count invalid")
    if len(pathbuf.value) != count:
        raise WindowsObservationError(
            "GetFinalPathNameByHandleW length inconsistent")
    final_path = pathbuf.value[:count]
    return (tag.FileAttributes, tag.ReparseTag, std.AllocationSize,
            std.EndOfFile, std.NumberOfLinks, std.DeletePending,
            std.Directory, fid.VolumeSerialNumber,
            bytes(fid.FileId), final_path)


def _d1_check_file_facts(facts, expected_size, expected_volume_serial,
                         expected_file_id, normalized_path):
    """Failclosed checks over one observation tuple."""
    (attrs, reparse_tag, allocation, eof, links, delete_pending,
     directory, volume_serial, file_id, final_path) = facts
    if attrs & FILE_ATTRIBUTE_REPARSE_POINT or attrs & FILE_ATTRIBUTE_DIRECTORY:
        raise WindowsObservationError("file attributes reparse/directory")
    if reparse_tag != 0:
        raise WindowsObservationError("reparse tag nonzero")
    if delete_pending or directory:
        raise WindowsObservationError("standard info delete/directory")
    if links != 1:
        raise WindowsObservationError("hardlink count not 1")
    if eof != expected_size:
        raise WindowsObservationError("EndOfFile size mismatch")
    if allocation < eof:
        raise WindowsObservationError("AllocationSize below EndOfFile")
    if volume_serial != expected_volume_serial:
        raise WindowsObservationError("volume serial mismatch")
    if file_id != expected_file_id:
        raise WindowsObservationError("file id mismatch")
    if final_path != "\\\\?\\" + normalized_path:
        raise WindowsObservationError("final path prefix mismatch")


def _d1_close_file(api, handle):
    if not api.CloseHandle(handle):
        raise WindowsObservationError("CloseHandle failed")


def bind_file_bytes(api, path, expected_sha256, expected_volume_serial,
                    expected_file_id, expected_size, *, deadline, clock):
    """Bind a retained final-file observation (injected APIs only).

    Validates all shapes before any API call; CreateFileW GENERIC_READ only
    (never write/create/delete, no write/delete sharing, no inheritance);
    close registered via ExitStack immediately after valid acquisition and
    released only after full fact construction; metadata, final path, byte
    hash and re-observation all through the SAME retained handle; budget
    checked before/after each observation with the injected clock (no reset);
    exact once close on all failures incl. BaseException; failed cleanup
    surfaces, never success. No reacquire by path, no retry.
    """
    # 0) validate all shapes BEFORE any API call
    normalized_path = _d1_validate_file_path(path)
    if (type(expected_sha256) is not str or len(expected_sha256) != 64
            or any(ch not in "0123456789abcdef" for ch in expected_sha256)):
        raise WindowsObservationError(
            "expected_sha256 must be lowercase 64hex")
    if (isinstance(expected_volume_serial, bool)
            or type(expected_volume_serial) is not int
            or not 0 <= expected_volume_serial <= 0xFFFFFFFFFFFFFFFF):
        raise WindowsObservationError(
            "expected_volume_serial must be builtin uint64 nonbool")
    if (type(expected_file_id) is not bytes or len(expected_file_id) != 16
            or not any(expected_file_id)):
        raise WindowsObservationError(
            "expected_file_id must be exact 16 nonzero bytes")
    if (isinstance(expected_size, bool) or type(expected_size) is not int
            or not 1 <= expected_size <= _D1_MAX_SIZE):
        raise WindowsObservationError(
            "expected_size must be exact int 1..536870912")
    if not callable(clock):
        raise WindowsObservationError("clock must be callable")
    budget = _D1BudgetChecker(deadline)
    try:
        with contextlib.ExitStack() as stack:
            # 1) ABI configured/validated BEFORE acquisition; close registered
            # immediately after valid handle, before any later sample/API
            _d1_configure_abi(api)
            budget.check(clock)
            handle = api.CreateFileW(path, GENERIC_READ, FILE_SHARE_READ,
                                     None, OPEN_EXISTING,
                                     FILE_FLAG_OPEN_REPARSE_POINT, None)
            if (type(handle) is not int or handle <= 0
                    or handle >= (1 << 64) - 1):
                raise WindowsObservationError("CreateFileW invalid handle")
            stack.callback(_d1_close_file, api, handle)
            budget.check(clock)
            # 2) type + metadata + identity + final path on SAME handle
            budget.check(clock)
            if api.GetFileType(handle) != FILE_TYPE_DISK:
                raise WindowsObservationError("file type not DISK")
            budget.check(clock)
            before_facts = _d1_observe_file_info(api, handle, budget, clock)
            _d1_check_file_facts(before_facts, expected_size,
                                 expected_volume_serial, expected_file_id,
                                 normalized_path)
            # 3) bounded byte hash on SAME retained handle
            observed_sha256 = _d1_read_file_sha256(api, handle, expected_size,
                                                   budget, clock)
            if observed_sha256 != expected_sha256:
                raise WindowsObservationError("sha256 digest mismatch")
            # 4) re-observe SAME handle; validate AND require exact equality
            after_facts = _d1_observe_file_info(api, handle, budget, clock)
            _d1_check_file_facts(after_facts, expected_size,
                                 expected_volume_serial, expected_file_id,
                                 normalized_path)
            if before_facts != after_facts:
                raise WindowsObservationError(
                    "file facts changed between observations")
            # 5) full construction succeeds: transfer cleanup obligation
            binding = object.__new__(RetainedFileObservation)
            object.__setattr__(binding, "_api", api)
            object.__setattr__(binding, "_handle", handle)
            object.__setattr__(binding, "_path", normalized_path)
            object.__setattr__(binding, "_expected_size", expected_size)
            object.__setattr__(binding, "_volume_serial",
                               expected_volume_serial)
            object.__setattr__(binding, "_file_id", expected_file_id)
            object.__setattr__(binding, "_observed_sha256", observed_sha256)
            object.__setattr__(binding, "_closed", False)
            object.__setattr__(binding, "_cleanup_failed", False)
            stack.pop_all()
            return binding
    except WindowsObservationError:
        raise
    except Exception as err:
        raise WindowsObservationError(
            "file byte observation failed") from err


# --- S3E1: unnamed non-inherited kill-on-close job HANDLE (injected only) ---
# E1 creates an EMPTY JOB ONLY: never arbitrary process HANDLE acceptance,
# no child/process creation, no assigning/resume/kill. This component alone
# never proves contained runner or no unprotected execution (E2 separate).

JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x2000
JobObjectExtendedLimitInformation = 9


class JobBasicLimitInformationStruct(ctypes.Structure):
    _fields_ = [("PerProcessUserTimeLimit", ctypes.c_int64),
                ("PerJobUserTimeLimit", ctypes.c_int64),
                ("LimitFlags", ctypes.c_uint32),
                ("MinimumWorkingSetSize", ctypes.c_size_t),
                ("MaximumWorkingSetSize", ctypes.c_size_t),
                ("ActiveProcessLimit", ctypes.c_uint32),
                ("Affinity", ctypes.c_size_t),
                ("PriorityClass", ctypes.c_uint32),
                ("SchedulingClass", ctypes.c_uint32)]


class JobIoCountersStruct(ctypes.Structure):
    _fields_ = [("ReadOperationCount", ctypes.c_uint64),
                ("WriteOperationCount", ctypes.c_uint64),
                ("OtherOperationCount", ctypes.c_uint64),
                ("ReadTransferCount", ctypes.c_uint64),
                ("WriteTransferCount", ctypes.c_uint64),
                ("OtherTransferCount", ctypes.c_uint64)]


class JobExtendedLimitInformationStruct(ctypes.Structure):
    _fields_ = [("BasicLimitInformation", JobBasicLimitInformationStruct),
                ("IoInfo", JobIoCountersStruct),
                ("ProcessMemoryLimit", ctypes.c_size_t),
                ("JobMemoryLimit", ctypes.c_size_t),
                ("PeakProcessMemoryUsed", ctypes.c_size_t),
                ("PeakJobMemoryUsed", ctypes.c_size_t)]


class RetainedContainmentJob:
    """Opaque immutable retained EMPTY job HANDLE (factory-issued only)."""
    AUTHORIZES_EXECUTION = False
    PLATFORM_QUALIFIED = False
    CHILD_ASSIGNED = False
    HARD_IO_TIMEOUT_PROVEN = False
    __slots__ = ("_api", "_handle", "_observed_limit_flags",
                 "_closed", "_cleanup_failed")

    def __new__(cls, *args, **kwargs):
        raise WindowsObservationError(
            "RetainedContainmentJob is factory-issued only")

    def __setattr__(self, name, value):
        raise WindowsObservationError("RetainedContainmentJob is immutable")

    def __delattr__(self, name):
        raise WindowsObservationError("RetainedContainmentJob is immutable")

    @property
    def observed_limit_flags(self):
        return self._observed_limit_flags

    @property
    def cleanup_failed(self):
        return self._cleanup_failed

    def close(self):
        """Close the owned job HANDLE exactly once; failure surfaces."""
        if self._closed:
            raise WindowsObservationError("double close")
        object.__setattr__(self, "_closed", True)  # unusable before attempt
        try:
            ok = self._api.CloseHandle(self._handle)
        except Exception as err:
            object.__setattr__(self, "_cleanup_failed", True)
            raise WindowsObservationError("CloseHandle failed") from err
        if not ok:
            object.__setattr__(self, "_cleanup_failed", True)
            raise WindowsObservationError("CloseHandle failed")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()
        return False


def _e1_configure_abi(api):
    """Validate required injected callables, then exact fixed-width Win32
    prototypes. MUST precede the first job syscall."""
    for name in ("CreateJobObjectW", "SetInformationJobObject",
                 "QueryInformationJobObject", "SetHandleInformation",
                 "GetHandleInformation", "CloseHandle"):
        if not callable(getattr(api, name, None)):
            raise WindowsObservationError("required injected API missing")
    api.CreateJobObjectW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p]
    api.CreateJobObjectW.restype = ctypes.c_void_p
    api.SetInformationJobObject.argtypes = [ctypes.c_void_p, ctypes.c_int32,
                                            ctypes.c_void_p, ctypes.c_uint32]
    api.SetInformationJobObject.restype = ctypes.c_int32
    api.QueryInformationJobObject.argtypes = [ctypes.c_void_p, ctypes.c_int32,
                                              ctypes.c_void_p, ctypes.c_uint32,
                                              ctypes.POINTER(ctypes.c_uint32)]
    api.QueryInformationJobObject.restype = ctypes.c_int32
    api.SetHandleInformation.argtypes = [ctypes.c_void_p, ctypes.c_uint32,
                                         ctypes.c_uint32]
    api.SetHandleInformation.restype = ctypes.c_int32
    api.GetHandleInformation.argtypes = [ctypes.c_void_p,
                                         ctypes.POINTER(ctypes.c_uint32)]
    api.GetHandleInformation.restype = ctypes.c_int32
    api.CloseHandle.argtypes = [ctypes.c_void_p]
    api.CloseHandle.restype = ctypes.c_int32


def _e1_close_job(api, handle):
    if not api.CloseHandle(handle):
        raise WindowsObservationError("CloseHandle failed")


def create_containment_job(api, *, deadline, clock):
    """Create an unnamed, non-inherited, kill-on-close EMPTY job (injected).

    Validates exact x64 ABI (sizeof(void_p)==8), clock and budget BEFORE any
    syscall; all prototypes set before the first syscall; single cleanup
    registered immediately after valid acquisition and released only after
    full fact construction; handle must be non-inherited and unprotected;
    zero-initialized extended limits with ONLY the kill-on-close flag, then
    exact query-back verification. Failures incl. raw exceptions/close the
    owned handle exactly once; failed cleanup surfaces, never success.
    No process assignment, resume or kill here (E2 is separate).
    """
    # 1) validate architecture, clock and budget BEFORE any API call
    if ctypes.sizeof(ctypes.c_void_p) != 8:
        raise WindowsObservationError(
            "explicit Windows x64 ABI required (void_p == 8)")
    if not callable(clock):
        raise WindowsObservationError("clock must be callable")
    budget = _D1BudgetChecker(deadline)
    try:
        with contextlib.ExitStack() as stack:
            _e1_configure_abi(api)
            budget.check(clock)
            handle = api.CreateJobObjectW(None, None)
            if (type(handle) is not int or handle <= 0
                    or handle >= (1 << 64) - 1):
                raise WindowsObservationError("CreateJobObjectW invalid handle")
            stack.callback(_e1_close_job, api, handle)
            budget.check(clock)
            # 2) non-inherited, unprotected handle; budget around each syscall
            budget.check(clock)
            if not api.SetHandleInformation(handle, 1, 0):
                raise WindowsObservationError("SetHandleInformation failed")
            budget.check(clock)
            flags = ctypes.c_uint32(0)
            if not api.GetHandleInformation(handle, ctypes.pointer(flags)):
                raise WindowsObservationError("GetHandleInformation failed")
            budget.check(clock)
            if flags.value != 0:
                raise WindowsObservationError(
                    "handle must be non-inherited and unprotected")
            # 3) zero-initialized limits; ONLY kill-on-close flag
            info = JobExtendedLimitInformationStruct()
            info.BasicLimitInformation.LimitFlags = \
                JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
            budget.check(clock)
            if not api.SetInformationJobObject(handle,
                                               JobObjectExtendedLimitInformation,
                                               ctypes.byref(info),
                                               ctypes.sizeof(info)):
                raise WindowsObservationError("SetInformationJobObject failed")
            budget.check(clock)
            # 4) exact query-back verification
            observed = JobExtendedLimitInformationStruct()
            returned = ctypes.c_uint32(0)
            budget.check(clock)
            if not api.QueryInformationJobObject(
                    handle, JobObjectExtendedLimitInformation,
                    ctypes.byref(observed), ctypes.sizeof(observed),
                    ctypes.pointer(returned)):
                raise WindowsObservationError(
                    "QueryInformationJobObject failed")
            budget.check(clock)
            if returned.value != ctypes.sizeof(observed):
                raise WindowsObservationError(
                    "query returned size mismatch")
            observed_flags = observed.BasicLimitInformation.LimitFlags
            if observed_flags != JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE:
                raise WindowsObservationError(
                    "observed limit flags mismatch")
            # 5) full construction succeeds: transfer cleanup obligation
            job = object.__new__(RetainedContainmentJob)
            object.__setattr__(job, "_api", api)
            object.__setattr__(job, "_handle", handle)
            object.__setattr__(job, "_observed_limit_flags", observed_flags)
            object.__setattr__(job, "_closed", False)
            object.__setattr__(job, "_cleanup_failed", False)
            stack.pop_all()
            return job
    except WindowsObservationError:
        raise
    except Exception as err:
        raise WindowsObservationError(
            "containment job observation failed") from err