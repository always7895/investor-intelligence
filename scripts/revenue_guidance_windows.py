"""
UNEXECUTED/UNVALIDATED CODE-ONLY IMPLEMENTATION.
revenue_guidance_windows.py - P2 Lazy Windows storage and trusted-bootstrap source.
Implements bounded handle-rooted Win32/NT I/O. Does NOT provide arbitrary raw handle access.
"""

import sys
import re
import threading
import struct

class StorageError(Exception): pass
class StorageUnavailableError(StorageError): pass
class StorageBusyError(StorageError): pass
class StorageObjectMissingError(StorageError): pass
class StorageObjectExistsError(StorageError): pass
class StorageValidationFault(StorageError): pass

STATUS_SUCCESS = 0x00000000
STATUS_PENDING = 0x00000103
FILE_OPEN = 0x00000001
FILE_CREATE = 0x00000002
FILE_DIRECTORY_FILE = 0x00000001
FILE_LIST_DIRECTORY = 0x0001
FILE_ADD_FILE = 0x0002
FILE_ADD_SUBDIRECTORY = 0x0004
FILE_WRITE_DATA = 0x0002
DELETE = 0x00010000
# SDK FILE_INFORMATION_CLASS, distinct from Win32 information classes below:
# https://learn.microsoft.com/en-us/windows-hardware/drivers/ddi/wdm/ne-wdm-_file_information_class
NATIVE_RENAME_INFORMATION = 10
NATIVE_NAMES_INFORMATION = 12
NATIVE_DISPOSITION_INFORMATION = 13
NATIVE_END_OF_FILE_INFORMATION = 20
IO_CHUNK_BYTES = 1024 * 1024
DIRECTORY_PAGE_BYTES = 65536
STATUS_NO_MORE_FILES = 0x80000006
STATUS_BUFFER_OVERFLOW = 0x80000005
STATUS_OBJECT_NAME_COLLISION = 0xC0000035
FILE_OPEN_REPARSE_POINT = 0x00200000
FILE_SYNCHRONOUS_IO_NONALERT = 0x00000020
FILE_NON_DIRECTORY_FILE = 0x00000040
FILE_WRITE_THROUGH = 0x00000002
FILE_READ_ATTRIBUTES = 0x0080
FILE_TRAVERSE = 0x0020
SYNCHRONIZE = 0x00100000
FILE_GENERIC_READ = 0x00120089
FILE_GENERIC_WRITE = 0x00120116

FILE_STANDARD_INFO_CLASS = 1
FILE_ATTRIBUTE_TAG_INFO_CLASS = 9
FILE_ID_INFO_CLASS = 18
WAIT_OBJECT_0 = 0x00000000

_cache = None
_poisoned = False
_quarantine_record = None
# Real owner retained BEFORE a synchronous close can become unconfirmed. This is
# a failure/lifetime veto, never authority, a handle-adoption API or caller cache.
_unsettled_close_owner = None
_custody_hold_event = threading.Event()  # prepared before ANY native submission
_bind_lock = threading.Lock()


def _origin_custody_unresolved():
    origin_domain = sys.modules.get("revenue_guidance_provisioner")
    return origin_domain is not None and origin_domain.origin_custody_status() == "UNRESOLVED"


def native_custody_status():
    """Read-only existing Python evidence; no binding/native/clock/cleanup call.

    Shared outer-lifetime seam for bootstrap and the future F02D same-owner host.
    A poisoned domain, pending request or unconfirmed close forbids normal exit.
    """
    record = _quarantine_record
    if (_poisoned or _unsettled_close_owner is not None or
            (record is not None and record.submitted and record.final_status == STATUS_PENDING)):
        return "UNRESOLVED"
    if _origin_custody_unresolved():
        return "UNRESOLVED"  # actual synchronous origin cleanup is also a lifetime veto
    return "SETTLED"


def _retain_uncertain_cleanup(context):
    """Internal failure veto on aborted cleanup of ACTUAL registered owners.

    Never adopts a handle, authorizes a caller or registers an authority object.
    Reuses the existing owner/request/context graph; no extra custody counter/cap.
    """
    global _unsettled_close_owner, _poisoned
    if _unsettled_close_owner is not None or _retains_context(context):
        return  # original uncertainty already owns the real graph
    for owner in context._owned_handles:
        if owner is None or owner._closed or owner._active_released:
            continue
        record = owner._request
        if (owner.lease_context is not context or owner._slot is None or
                context._owned_handles[owner._slot] is not owner or record is None or
                record.owned_handle is not owner or record.lease_context is not context or not record.submitted):
            continue
        try:
            value = record.out_handle.value
            has_custody = value not in (None, 0, -1, 0xFFFFFFFF, 0xFFFFFFFFFFFFFFFF)
        except BaseException:
            has_custody = True
        if has_custody:
            _unsettled_close_owner = owner
            _poisoned = True
            return


def context_custody_unresolved(context):
    """Narrow read-only veto before issuer-origin disposal; no native call."""
    owner = _unsettled_close_owner
    return (getattr(context, "_quarantined", False) or _retains_context(context) or
            (owner is not None and owner.lease_context is context))


def hold_unresolved_native_custody():
    """Never return/unload while real unresolved custody remains.

    No syscall retry, polling, cleanup, acknowledgement or cancellation fiction.
    Event is private and NEVER signalled by product code. External operator/OS
    termination is outside this lifetime guarantee, not successful cleanup.
    """
    if native_custody_status() != "UNRESOLVED":
        return
    while True:
        try:
            _custody_hold_event.wait()  # unsignalled, no deadline or busy polling
        except BaseException:
            # A Python interrupt/SystemExit cannot convert UNKNOWN into settlement.
            continue

def _retains_context(context):
    record = _quarantine_record
    return (record is not None and record.submitted and
            record.final_status == STATUS_PENDING and record.lease_context is context)


def _check_poison():
    global _poisoned
    record = _quarantine_record
    if record is not None and record.submitted and record.final_status == STATUS_PENDING:
        _poisoned = True
    if _origin_custody_unresolved():
        _poisoned = True
    if _poisoned:
        if _unsettled_close_owner is not None or _origin_custody_unresolved():
            raise StorageUnavailableError("NATIVE_CUSTODY_UNRESOLVED: Native domain permanently poisoned")
        raise StorageUnavailableError("PENDING_IO_UNRESOLVED: Native domain permanently poisoned")

def _lazy_bind():
    global _cache
    if _cache is not None:
        return _cache
    _bind_lock.acquire()
    try:
        if _cache is not None:
            return _cache
        import platform
        if sys.implementation.name != "cpython" or sys.version_info[:2] != (3, 12) or sys.platform != "win32" or platform.machine().lower() not in ("amd64", "x86_64") or sys.maxsize <= 2**32:
            raise StorageUnavailableError("Unsupported platform: requires CPython 3.12 x64 on Windows")

        import ctypes
        from ctypes import wintypes

        USHORT = ctypes.c_uint16
        ULONG = ctypes.c_uint32
        DWORD = ctypes.c_uint32
        LONG = ctypes.c_int32
        NTSTATUS = ctypes.c_int32
        BOOL = ctypes.c_int32
        BOOLEAN = ctypes.c_uint8
        ULONGLONG = ctypes.c_uint64
        LARGE_INTEGER = ctypes.c_int64
        HANDLE = wintypes.HANDLE
        PVOID = wintypes.LPVOID
        ULONG_PTR = ctypes.c_uint64
        PWSTR = wintypes.LPWSTR

        class UNICODE_STRING(ctypes.Structure):
            _fields_ = [("Length", USHORT), ("MaximumLength", USHORT), ("Buffer", PWSTR)]

        class OBJECT_ATTRIBUTES(ctypes.Structure):
            _fields_ = [("Length", ULONG), ("RootDirectory", HANDLE), ("ObjectName", ctypes.POINTER(UNICODE_STRING)),
                        ("Attributes", ULONG), ("SecurityDescriptor", PVOID), ("SecurityQualityOfService", PVOID)]

        class _IO_STATUS_BLOCK_UNION(ctypes.Union):
            _fields_ = [("Status", NTSTATUS), ("Pointer", PVOID)]

        class IO_STATUS_BLOCK(ctypes.Structure):
            _fields_ = [("u", _IO_STATUS_BLOCK_UNION), ("Information", ULONG_PTR)]

        class FILE_ID_INFO(ctypes.Structure):
            _fields_ = [("VolumeSerialNumber", ULONGLONG), ("FileId", ctypes.c_uint8 * 16)]

        class FILE_STANDARD_INFO(ctypes.Structure):
            _fields_ = [("AllocationSize", LARGE_INTEGER), ("EndOfFile", LARGE_INTEGER),
                        ("NumberOfLinks", DWORD), ("DeletePending", BOOLEAN), ("Directory", BOOLEAN)]

        class FILE_ATTRIBUTE_TAG_INFO(ctypes.Structure):
            _fields_ = [("FileAttributes", DWORD), ("ReparseTag", DWORD)]

        # Native x64 natural alignment, not packed wire layouts. FileName starts
        # at its ctypes field offset (20), NOT sizeof(FILE_RENAME_INFORMATION).
        class _RENAME_UNION(ctypes.Union):
            _fields_ = [("ReplaceIfExists", BOOLEAN), ("Flags", ULONG)]

        class FILE_RENAME_INFORMATION(ctypes.Structure):
            _fields_ = [("u", _RENAME_UNION), ("RootDirectory", HANDLE),
                        ("FileNameLength", ULONG), ("FileName", USHORT * 1)]

        class FILE_END_OF_FILE_INFORMATION(ctypes.Structure):
            _fields_ = [("EndOfFile", LARGE_INTEGER)]

        class FILE_DISPOSITION_INFORMATION(ctypes.Structure):
            _fields_ = [("DeleteFile", BOOLEAN)]

        LOAD_LIBRARY_SEARCH_SYSTEM32 = 0x00000800
        ntdll = ctypes.WinDLL("ntdll.dll", winmode=LOAD_LIBRARY_SEARCH_SYSTEM32)
        kernel32 = ctypes.WinDLL("kernel32.dll", winmode=LOAD_LIBRARY_SEARCH_SYSTEM32)

        ntdll.NtCreateFile.argtypes = [
            ctypes.POINTER(HANDLE), ULONG, ctypes.POINTER(OBJECT_ATTRIBUTES),
            ctypes.POINTER(IO_STATUS_BLOCK), ctypes.POINTER(LARGE_INTEGER),
            ULONG, ULONG, ULONG, ULONG, PVOID, ULONG
        ]
        ntdll.NtCreateFile.restype = NTSTATUS
        for api in (ntdll.NtReadFile, ntdll.NtWriteFile):
            api.argtypes = [HANDLE, HANDLE, PVOID, PVOID,
                            ctypes.POINTER(IO_STATUS_BLOCK), PVOID, ULONG,
                            ctypes.POINTER(LARGE_INTEGER), ctypes.POINTER(ULONG)]
            api.restype = NTSTATUS
        ntdll.NtSetInformationFile.argtypes = [HANDLE, ctypes.POINTER(IO_STATUS_BLOCK),
                                             PVOID, ULONG, ctypes.c_int]
        ntdll.NtSetInformationFile.restype = NTSTATUS
        ntdll.NtQueryDirectoryFile.argtypes = [HANDLE, HANDLE, PVOID, PVOID,
                                             ctypes.POINTER(IO_STATUS_BLOCK), PVOID,
                                             ULONG, ctypes.c_int, BOOLEAN,
                                             ctypes.POINTER(UNICODE_STRING), BOOLEAN]
        ntdll.NtQueryDirectoryFile.restype = NTSTATUS
        ntdll.NtFlushBuffersFile.argtypes = [HANDLE, ctypes.POINTER(IO_STATUS_BLOCK)]
        ntdll.NtFlushBuffersFile.restype = NTSTATUS

        kernel32.GetFileInformationByHandleEx.argtypes = [HANDLE, ctypes.c_int, PVOID, DWORD]
        kernel32.GetFileInformationByHandleEx.restype = BOOL

        kernel32.GetVolumeInformationByHandleW.argtypes = [
            HANDLE, PWSTR, DWORD, ctypes.POINTER(DWORD), ctypes.POINTER(DWORD),
            ctypes.POINTER(DWORD), PWSTR, DWORD
        ]
        kernel32.GetVolumeInformationByHandleW.restype = BOOL

        kernel32.CloseHandle.argtypes = [HANDLE]
        kernel32.CloseHandle.restype = BOOL

        kernel32.WaitForSingleObject.argtypes = [HANDLE, DWORD]
        kernel32.WaitForSingleObject.restype = DWORD

        class BindingCache:
            def __init__(self):
                self.ctypes = ctypes
                self.HANDLE = HANDLE
                self.DWORD = DWORD
                self.LARGE_INTEGER = LARGE_INTEGER
                self.UNICODE_STRING = UNICODE_STRING
                self.OBJECT_ATTRIBUTES = OBJECT_ATTRIBUTES
                self.IO_STATUS_BLOCK = IO_STATUS_BLOCK
                self.FILE_ID_INFO = FILE_ID_INFO
                self.FILE_STANDARD_INFO = FILE_STANDARD_INFO
                self.FILE_ATTRIBUTE_TAG_INFO = FILE_ATTRIBUTE_TAG_INFO
                self.FILE_RENAME_INFORMATION = FILE_RENAME_INFORMATION
                self.FILE_END_OF_FILE_INFORMATION = FILE_END_OF_FILE_INFORMATION
                self.FILE_DISPOSITION_INFORMATION = FILE_DISPOSITION_INFORMATION
                self.ntdll = ntdll
                self.kernel32 = kernel32
                self.PWSTR = PWSTR
                import threading
                self.native_lock = threading.Lock()

        new_cache = BindingCache()
        if _cache is None:
            _cache = new_cache
        return _cache
    except Exception:
        raise StorageUnavailableError("Failed to bind native DLLs") from None
    finally:
        _bind_lock.release()

def _require_context(context, parent=None, *, cleanup=False):
    # Private custody plumbing; genuine authorization remains require_anchor.
    from revenue_guidance_storage import NativeStorageLease, NativeIssuerContext
    if type(context) not in (NativeStorageLease, NativeIssuerContext):
        raise StorageValidationFault("Owning storage custody required")
    if type(context) is NativeIssuerContext and not cleanup:
        # Actual independent protected-origin handles/principal were acquired
        # before native budget/bind; a caller class/seal/Boolean is not admission.
        import revenue_guidance_provisioner as provisioner
        provisioner.require_live_issuer(context._issuer_origin)
    if context._guard_thread != threading.get_ident() or not context._lock.locked():
        raise StorageValidationFault("Held lease serialization required")
    if not cleanup and (context._closed or context._quarantined or context._state not in ("ACQUIRING", "READY")):
        raise StorageValidationFault("Lease is not active")
    if not cleanup:
        context.budget._check_time()
    current = parent
    while current is not None:
        if type(current) is not OwnedHandle or current.lease_context is not context:
            raise StorageValidationFault("Cross-lease owner or parent")
        slot = current._slot
        if slot is None or context._owned_handles[slot] is not current:
            # Only confirmed, evidence-free closed slots can be reused. A stale
            # closed owner may acknowledge close, never submit I/O or refund.
            if cleanup and current._closed and current._active_released and current.close_error is None:
                return context
            raise StorageValidationFault("Unregistered ownership chain")
        if not cleanup and (current._closed or current._close_attempted or current._quarantined or current._dispose_only):
            raise StorageValidationFault("Inactive ownership chain")
        record = current._request
        if record is None or record.lease_context is not context or record.owned_handle is not current:
            raise StorageValidationFault("Incomplete ownership record")
        if not cleanup and (not record.submitted or record.final_status != STATUS_SUCCESS):
            raise StorageValidationFault("Unsettled ownership chain")
        ancestor = record.parent
        if ancestor is not None and (type(ancestor) is not OwnedHandle or ancestor._slot is None or ancestor._serial >= current._serial):
            raise StorageValidationFault("Invalid ancestor chain")
        if current._rename_parent is not None:
            # Only files are renamed; target directories are never renamed by
            # this substrate, so this secondary ancestry cannot form a cycle.
            _require_context(context, current._rename_parent, cleanup=cleanup)
        current = ancestor
    return context


def _require_handle(handle):
    if type(handle) is not OwnedHandle:
        raise StorageValidationFault("Owned handle required")
    return _require_context(handle.lease_context, handle)


class _OpenEvidence:
    """Compact bounded history, not a handle/authority or pending-buffer owner."""
    def __init__(self):
        self.serial = -1
        self.submitted = False
        self.final_status = STATUS_PENDING
        self.created = False
        self.close_attempted = False
        self.close_confirmed = False
        self.released = False


def _record_open_state(record):
    evidence = record.owned_handle._evidence
    evidence.submitted = record.submitted
    evidence.final_status = record.final_status
    evidence.created = record.owned_handle._created


class OwnedHandle:
    def __init__(self, lease_context: object, _secret: object = None):
        if _secret is not OwnedHandle:
            raise StorageValidationFault("Arbitrary handle adoption is prohibited")
        self._request = None
        self._slot = None
        self._charged = False
        self._active_released = False
        self._closed = False
        self._close_attempted = False
        self._quarantined = False
        self.lease_context = lease_context
        self.close_error = None
        self._serial = -1
        self._dispose_only = False
        self._namespace = False
        self._is_directory = False
        self._directory_scope = None
        self._writable = False
        self._delete_access = False
        self._created = False
        self._temporary_operation = None
        self._published = False
        self._identity = None
        self._rename_parent = None
        self._last_io = None
        self._cleanup_mark = -1
        self._object_cap = 8 * 1024 * 1024
        self._planned_size = None
        self._staging_reservation = None
        self._readback_reservation = None
        self._evidence = _OpenEvidence()

    def _register(self):
        context = _require_context(self.lease_context)
        if context._next_serial >= len(context._open_evidence):
            raise StorageValidationFault("Lifetime preparation/evidence capacity exhausted")
        for slot in range(len(context._owned_handles)):
            previous = context._owned_handles[slot]
            if previous is None or (previous._closed and previous._active_released and previous.close_error is None and previous._last_io is None):
                self._slot = slot
                self._serial = context._next_serial
                self._evidence.serial = self._serial
                context._open_evidence[self._serial] = self._evidence
                context._next_serial += 1
                context._owned_handles[slot] = self
                # Complete owner/request rooted BEFORE debit; no append/handoff.
                context.budget.precharge_open(self)
                return
        raise StorageValidationFault("Ownership record capacity exhausted")

    @property
    def handle(self) -> int:
        if self._closed or self._close_attempted or self._active_released:
            raise StorageError("Handle closed or invalid")
        record = self._request
        if record is None or not record.submitted or record.final_status != STATUS_SUCCESS:
            raise StorageError("Handle not settled successfully")
        value = record.out_handle.value
        if value in (None, 0, -1, 0xFFFFFFFF, 0xFFFFFFFFFFFFFFFF):
            raise StorageError("Handle output invalid")
        return value

    def _close_internal(self, c):
        global _unsettled_close_owner, _poisoned
        if _unsettled_close_owner is not None or _origin_custody_unresolved():
            # Entire actual owner/context/origin remains rooted. No later close
            # (including another ancestor/owner) is a workaround for uncertainty.
            raise self.lease_context._cleanup_failure
        if (self._quarantined or self.lease_context._quarantined or
            _retains_context(self.lease_context)):
            # Domain/context check also covers interruption during marking.
            raise self.lease_context._pending_failure
        if self.close_error is not None:
            raise self.close_error
        if self._closed or self._active_released:
            self._closed = True
            return
        if self._close_attempted:
            if getattr(self, 'close_error', None) is not None:
                raise self.close_error
            raise StorageError("Close already attempted and unconfirmed")

        for child in self.lease_context._owned_handles:
            if child is not None and not child._closed and child is not self:
                if child._request.parent is self or child._rename_parent is self:
                    raise StorageValidationFault("Live descendant must close before ancestor")
        record = self._request
        if record is not None and record.submitted and record.final_status == STATUS_PENDING:
            raise StorageUnavailableError("PENDING_IO_UNRESOLVED")
        try:
            value = record.out_handle.value if record is not None and record.submitted else None
        except BaseException as e:
            self._close_attempted = True
            self.close_error = e
            _unsettled_close_owner = self
            _poisoned = True
            raise
        if value in (None, 0, -1, 0xFFFFFFFF, 0xFFFFFFFFFFFFFFFF):
            self.lease_context.budget.release_active_handle(self)
            self._closed = True
            return

        # Retain BEFORE submission, including an interrupt during status handoff.
        _unsettled_close_owner = self
        self._close_attempted = True
        self._evidence.close_attempted = True
        try:
            res = c.kernel32.CloseHandle(c.HANDLE(value))
            if not res:
                raise StorageUnavailableError("CloseHandle natively failed")
            self._evidence.close_confirmed = True
            self.lease_context.budget.release_active_handle(self)
            self._closed = True
            _unsettled_close_owner = None  # ONLY confirmed close + ownership release
        except BaseException as e:
            self.close_error = e
            _poisoned = True
            raise

    def close(self):
        try:
            _require_context(self.lease_context, self, cleanup=True)
            c = _lazy_bind()
            with c.native_lock:
                self._close_internal(c)
        except BaseException:
            # Also cover guard/bind/lock interruption BEFORE _close_internal:
            # a real registered live native owner cannot be lost at outer exit.
            _retain_uncertain_cleanup(self.lease_context)
            raise

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

class _PendingRequestRecord:
    def __init__(self, c, utf16_name, name_buf, uni_str, p_uni_str, obj_attrs, p_obj_attrs, io_status, p_io_status, out_handle, p_out_handle, parent, lease_context, owned_handle):
        self.c = c
        self.utf16_name = utf16_name
        self.name_buf = name_buf
        self.uni_str = uni_str
        self.p_uni_str = p_uni_str
        self.obj_attrs = obj_attrs
        self.p_obj_attrs = p_obj_attrs
        self.io_status = io_status
        self.p_io_status = p_io_status
        self.out_handle = out_handle
        self.p_out_handle = p_out_handle
        self.parent = parent
        self.lease_context = lease_context
        self.owned_handle = owned_handle
        self.submitted = False
        self.final_status = STATUS_PENDING
        self.primary_error = None

def get_file_metadata(handle: OwnedHandle) -> tuple[int, bytes, int, bool, bool, int, int, int]:
    """Returns (VolumeSerial, FileId, Size, IsDir, DeletePending, Attributes, ReparseTag, NumberOfLinks)."""
    _require_handle(handle)
    c = _lazy_bind()
    with c.native_lock:
        _check_poison()
        handle.lease_context.budget.charge_work(buffer_bytes=c.ctypes.sizeof(c.FILE_ID_INFO))
        id_info = c.FILE_ID_INFO()
        if not c.kernel32.GetFileInformationByHandleEx(c.HANDLE(handle.handle), FILE_ID_INFO_CLASS, c.ctypes.byref(id_info), c.ctypes.sizeof(id_info)):
            raise StorageUnavailableError("Failed to get FILE_ID_INFO")
        handle.lease_context.budget.charge_work(buffer_bytes=c.ctypes.sizeof(c.FILE_STANDARD_INFO))
        std_info = c.FILE_STANDARD_INFO()
        if not c.kernel32.GetFileInformationByHandleEx(c.HANDLE(handle.handle), FILE_STANDARD_INFO_CLASS, c.ctypes.byref(std_info), c.ctypes.sizeof(std_info)):
            raise StorageUnavailableError("Failed to get FILE_STANDARD_INFO")
        handle.lease_context.budget.charge_work(buffer_bytes=c.ctypes.sizeof(c.FILE_ATTRIBUTE_TAG_INFO))
        tag_info = c.FILE_ATTRIBUTE_TAG_INFO()
        if not c.kernel32.GetFileInformationByHandleEx(c.HANDLE(handle.handle), FILE_ATTRIBUTE_TAG_INFO_CLASS, c.ctypes.byref(tag_info), c.ctypes.sizeof(tag_info)):
            raise StorageUnavailableError("Failed to get FILE_ATTRIBUTE_TAG_INFO")
    return (
        id_info.VolumeSerialNumber, bytes(id_info.FileId),
        std_info.EndOfFile, bool(std_info.Directory),
        bool(std_info.DeletePending), tag_info.FileAttributes, tag_info.ReparseTag,
        std_info.NumberOfLinks
    )

def check_volume_ntfs(handle: OwnedHandle):
    _require_handle(handle)
    c = _lazy_bind()
    with c.native_lock:
        _check_poison()
        handle.lease_context.budget.charge_work(buffer_bytes=516)
        fs_name = c.ctypes.create_unicode_buffer(256)
        flags = c.DWORD()
        if not c.kernel32.GetVolumeInformationByHandleW(c.HANDLE(handle.handle), None, 0, None, None, c.ctypes.byref(flags), fs_name, 256):
            raise StorageUnavailableError("Failed to read volume info")
    if fs_name.value != "NTFS":
        raise StorageUnavailableError("Storage must be NTFS")
    if flags.value & 0x00080000:
        raise StorageUnavailableError("Volume is read-only")

def _validate_component(name: str):
    if type(name) is not str:
        raise StorageValidationFault("Name must be exactly string")
    if not name or len(name) > 255:
        raise StorageValidationFault("Name bounds exceeded")
    try:
        utf16_name = name.encode('utf-16-le')
    except UnicodeEncodeError:
        raise StorageValidationFault("Component is not valid UTF-16") from None
    if len(utf16_name) == 0 or len(utf16_name) > 510:
        raise StorageValidationFault("Name UTF-16 length out of bounds")
    if name in (".", "..") or name.endswith(".") or name.endswith(" "):
        raise StorageValidationFault("Invalid name dots/spaces")
    if any(c in name for c in '\\/:*?"<>|\0'):
        raise StorageValidationFault("Invalid component characters")
    if any(ord(c) < 32 or 127 <= ord(c) <= 159 for c in name):
        raise StorageValidationFault("Control characters not allowed")
    upper_name = name.upper()
    name_base = upper_name.split('.')[0]
    if name_base in ("CON", "PRN", "AUX", "NUL"):
        raise StorageValidationFault("DOS alias reserved name")
    if len(name_base) == 4 and name_base.startswith(("COM", "LPT")):
        if name_base[3] in "123456789\u00B9\u00B2\u00B3\u2074\u2075\u2076\u2077\u2078\u2079":
            raise StorageValidationFault("DOS alias reserved name")

def _nt_open(root_dir: 'OwnedHandle | None', name: str, is_dir: bool, write_access: bool, lease_context: object, *, create=False, namespace_access=False, operation=None, object_cap=None, staging_reservation=None) -> OwnedHandle:
    _require_context(lease_context, root_dir)
    if any(type(flag) is not bool for flag in (is_dir, write_access, create, namespace_access)):
        raise StorageValidationFault("Flags must be exactly bool")
    if create and (root_dir is None or operation is not lease_context._live_operation):
        raise StorageValidationFault("Live create custody required")
    if namespace_access and (root_dir is None or not is_dir):
        raise StorageValidationFault("Namespace rights only on held descendant directories")
    if root_dir is not None:
        _validate_component(name)
    elif (lease_context._state != "ACQUIRING" or
          any(h is not None for h in lease_context._owned_handles) or
          name != f"\\??\\Volume{lease_context.anchor.volume_guid}\\" or
          not is_dir or write_access):
        raise StorageValidationFault("Root acquisition context mismatch")
    utf16_name = name.encode('utf-16-le')
    if len(utf16_name) > 65535 - 2:
        raise StorageValidationFault("Name too long")

    c = _lazy_bind()
    with c.native_lock:
        _check_poison()
        global _quarantine_record, _poisoned
        if _quarantine_record is not None:
            raise StorageUnavailableError("Quarantine slot occupied")
        h = None
        record = None
        try:
            # Every allocation precedes registration/debit/submission. An owner
            # directly retains output storage; no postreturn scalar adoption.
            name_buf = c.ctypes.create_string_buffer(utf16_name + b'\x00\x00')
            uni_str = c.UNICODE_STRING(
                Length=len(utf16_name), MaximumLength=len(utf16_name) + 2,
                Buffer=c.ctypes.cast(name_buf, c.PWSTR)
            )
            p_uni_str = c.ctypes.pointer(uni_str)
            security_buf = None
            if create and _is_issuer(lease_context):
                # Owner/DACL are set AT CREATION: no same-user creator-owner
                # WRITE_DAC window before post-create protection/readback.
                security_bytes = _issuer_creation_security(lease_context, root_dir, name, is_dir)
                security_buf = c.ctypes.create_string_buffer(security_bytes)
            obj_attrs = c.OBJECT_ATTRIBUTES(
                Length=c.ctypes.sizeof(c.OBJECT_ATTRIBUTES),
                RootDirectory=c.HANDLE(root_dir.handle) if root_dir else None,
                ObjectName=p_uni_str, Attributes=0,
                SecurityDescriptor=c.ctypes.cast(security_buf, c.ctypes.c_void_p) if security_buf is not None else None,
                SecurityQualityOfService=None
            )
            p_obj_attrs = c.ctypes.pointer(obj_attrs)
            access = (FILE_READ_ATTRIBUTES | FILE_TRAVERSE | SYNCHRONIZE) if is_dir else (FILE_GENERIC_READ | (FILE_GENERIC_WRITE if write_access else 0))
            if namespace_access:
                access |= FILE_LIST_DIRECTORY | FILE_ADD_FILE | FILE_ADD_SUBDIRECTORY
            if create and not is_dir:
                access |= DELETE
            if create and _is_issuer(lease_context):
                # Only positively NEW issuer objects may get security-setting rights.
                access |= 0x000E0000  # READ_CONTROL | WRITE_DAC | WRITE_OWNER
            flags = FILE_SYNCHRONOUS_IO_NONALERT | FILE_OPEN_REPARSE_POINT
            flags |= FILE_DIRECTORY_FILE if is_dir else FILE_NON_DIRECTORY_FILE
            if write_access and not is_dir:
                flags |= FILE_WRITE_THROUGH
            share = 3 if is_dir else (0 if write_access else 1)
            io_status = c.IO_STATUS_BLOCK()
            p_io_status = c.ctypes.pointer(io_status)
            out_handle = c.HANDLE()
            p_out_handle = c.ctypes.pointer(out_handle)
            h = OwnedHandle(lease_context, _secret=OwnedHandle)
            record = _PendingRequestRecord(
                c, utf16_name, name_buf, uni_str, p_uni_str,
                obj_attrs, p_obj_attrs, io_status, p_io_status,
                out_handle, p_out_handle, root_dir, lease_context, h
            )
            record._issuer_security_buffer = security_buf  # retained through UNKNOWN with all NT arguments
            h._request = record
            h._namespace = namespace_access
            h._is_directory = is_dir
            h._writable = write_access
            h._delete_access = create and not is_dir
            h._temporary_operation = operation if create and not is_dir else None
            if object_cap is not None:
                if type(object_cap) is not int or object_cap < 0 or object_cap > lease_context.limits.max_object_bytes:
                    raise StorageValidationFault("Invalid object ceiling")
                h._object_cap = object_cap
            h._register()
            if staging_reservation is not None:
                if not create or is_dir:
                    raise StorageValidationFault("Staging reservation only for new files")
                lease_context.budget._bind_staging(staging_reservation, h)
            lease_context.budget.charge_work(buffer_bytes=len(utf16_name) + 2 + (len(security_bytes) if security_buf is not None else 0),
                                             mutation=create, owner=h)
            _quarantine_record = record
            # From this point an exceptional submission is conservatively UNKNOWN.
            record.submitted = True
            record.final_status = c.ntdll.NtCreateFile(
                p_out_handle, access, p_obj_attrs,
                p_io_status, None, 0, share, FILE_CREATE if create else FILE_OPEN, flags, None, 0
            )
            if record.final_status == STATUS_PENDING:
                if out_handle.value not in (None, 0, -1, 0xFFFFFFFF, 0xFFFFFFFFFFFFFFFF):
                    wait_res = c.kernel32.WaitForSingleObject(out_handle, 0xFFFFFFFF)
                    if wait_res == WAIT_OBJECT_0:
                        # Only a confirmed wait permits adopting final IOSB status.
                        record.final_status = io_status.u.Status
            if record.final_status == STATUS_PENDING:
                raise lease_context._pending_failure

            if record.final_status != STATUS_SUCCESS:
                if (record.final_status & 0xFFFFFFFF) == STATUS_OBJECT_NAME_COLLISION:
                    raise StorageObjectExistsError("Object already exists")
                if (record.final_status & 0xFFFFFFFF) in (0xC0000034, 0xC000003A):
                    raise StorageObjectMissingError("Object not found")
                raise StorageUnavailableError("NtCreateFile failed")
            # This validation may fail, but cannot undo established completion.
            h.handle
            if create:
                # FILE_CREATE never adopts an existing object; Information=2 is
                # FILE_CREATED. Any other successful result is not creation proof.
                if io_status.Information != 2:
                    lease_context._closed = True
                    raise StorageValidationFault("Create result is not FILE_CREATED")
                h._created = True
            _record_open_state(record)
            _quarantine_record = None
            return h
        except BaseException as primary:
            if record is not None:
                record.primary_error = primary
                _record_open_state(record)
            if record is not None and record.submitted and record.final_status == STATUS_PENDING:
                # No new allocation/append is needed to retain the whole domain.
                _poisoned = True
                lease_context._mark_quarantined()
                if primary is not lease_context._pending_failure:
                    lease_context._pending_failure.primary_error = primary
                    raise lease_context._pending_failure from primary
                raise
            # Settled and pre-submission failures are NEVER pretend UNKNOWN.
            if _quarantine_record is record:
                _quarantine_record = None
            if h is not None and h._slot is not None and lease_context._owned_handles[h._slot] is h:
                try:
                    h._close_internal(c)  # Already admitted; no lock recursion.
                except BaseException as cleanup:
                    if h.close_error is None:
                        h.close_error = cleanup
                    lease_context._cleanup_failure.primary_error = primary
                    raise lease_context._cleanup_failure from primary
            raise

def open_volume_root(guid: str, lease_context: object) -> OwnedHandle:
    _require_context(lease_context)
    if guid != lease_context.anchor.volume_guid:
        raise StorageValidationFault("Root descriptor mismatch")
    if type(guid) is not str:
        raise StorageValidationFault("GUID must be string")
    if len(guid) != 38:
        raise StorageValidationFault("GUID bounded length mismatch")
    if not re.fullmatch(r"\{[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\}", guid):
        raise StorageValidationFault("GUID must be strictly formed")
    h = _nt_open(None, f"\\??\\Volume{guid}\\", is_dir=True, write_access=False, lease_context=lease_context)
    check_volume_ntfs(h)
    vol, fid, size, act_dir, del_pend, attrs, rep_tag, links = get_file_metadata(h)
    if not act_dir:
        raise StorageValidationFault("Root must be directory")
    if del_pend:
        raise StorageValidationFault("Root is pending deletion")
    if rep_tag != 0 or (attrs & 0x00000400):
        raise StorageValidationFault("Root is reparse point")
    return h

def open_relative(parent: OwnedHandle, name: str, is_dir: bool, write_access: bool, lease_context: object) -> OwnedHandle:
    if parent is None:
        raise StorageValidationFault("Parent required")
    _require_context(lease_context, parent)
    if type(is_dir) is not bool or type(write_access) is not bool:
        raise StorageValidationFault("Flags must be exactly bool")
    _validate_component(name)
    p_vol, p_fid, p_size, p_dir, p_del, p_attrs, p_rep, p_links = get_file_metadata(parent)
    if not p_dir or p_del or p_rep or (p_attrs & 0x00000400):
        raise StorageValidationFault("Parent is not a safe directory")
    h = _nt_open(parent, name, is_dir, write_access, lease_context=lease_context)
    vol, fid, size, act_dir, del_pend, attrs, rep_tag, links = get_file_metadata(h)
    if vol != p_vol:
        raise StorageValidationFault("Volume identity mismatch")
    if act_dir != is_dir:
        raise StorageValidationFault("Type mismatch")
    if del_pend:
        raise StorageValidationFault("Object is pending deletion")
    if rep_tag != 0 or (attrs & 0x00000400):
        raise StorageValidationFault("Reparse point encountered")
    if not is_dir and links != 1:
        raise StorageValidationFault(f"NumberOfLinks must be 1 for leaves, got {links}")
    return h

class _IoRequestRecord(_PendingRequestRecord):
    """Same single pending slot, with all NT arguments retained before submission."""
    def __init__(self, c, handle, api, *, target=None, buffers=()):
        io = c.IO_STATUS_BLOCK()
        p_io = c.ctypes.pointer(io)
        super().__init__(c, None, None, None, None, None, None, io, p_io,
                         handle._request.out_handle, None, handle,
                         handle.lease_context, handle)
        self.target = target
        self.buffers = buffers
        self.api = api
        self.arguments = ()
        self.wait_handle = c.HANDLE(handle.handle)
        self.completion_action = "ordinary"


def _submit_io(record, *, mutation=False, buffer_bytes=0, allowed=(STATUS_SUCCESS,)):
    # Caller holds the genuine lease guard; no second I/O/ownership domain.
    global _quarantine_record, _poisoned
    context = _require_handle(record.owned_handle)
    if record.target is not None:
        _require_context(context, record.target)
    c = record.c
    with c.native_lock:
        _check_poison()
        if _quarantine_record is not None:
            raise StorageUnavailableError("Quarantine slot occupied")
        context.budget.charge_work(buffer_bytes=buffer_bytes, mutation=mutation, owner=record.owned_handle)
        context._io_record = record
        _quarantine_record = record
        try:
            if record.completion_action == "dispose":
                # Close-only even if interrupted during final-success handoff.
                record.owned_handle._dispose_only = True
            record.submitted = True
            record.final_status = record.api(*record.arguments) & 0xFFFFFFFF
            if record.final_status == STATUS_PENDING:
                wait_res = c.kernel32.WaitForSingleObject(record.wait_handle, 0xFFFFFFFF)
                if wait_res == WAIT_OBJECT_0:
                    record.final_status = record.io_status.u.Status & 0xFFFFFFFF
            if record.final_status == STATUS_PENDING:
                raise context._pending_failure
            if record.final_status not in allowed:
                if record.final_status == STATUS_OBJECT_NAME_COLLISION:
                    raise StorageObjectExistsError("Rename target already exists")
                raise StorageUnavailableError("Native I/O failed")
            if record.completion_action == "rename":
                record.owned_handle._published = True
                record.owned_handle._rename_parent = record.target
                record.owned_handle._temporary_operation = None
            _quarantine_record = None
            return int(record.io_status.Information)
        except BaseException as primary:
            record.primary_error = primary
            record.owned_handle._last_io = record
            if record.submitted and record.final_status == STATUS_PENDING:
                _poisoned = True
                context._mark_quarantined()
                if primary is not context._pending_failure:
                    context._pending_failure.primary_error = primary
                    raise context._pending_failure from primary
                raise
            if _quarantine_record is record:
                _quarantine_record = None
            if mutation and not isinstance(primary, StorageObjectExistsError):
                context._closed = True
                context._failure_primary = primary
            raise


def _safe_metadata(handle, *, directory=None):
    _require_handle(handle)
    m = get_file_metadata(handle)
    vol, fid, size, is_dir, pending, attrs, tag, links = m
    if size < 0 or pending or tag or attrs & 0x400:
        raise StorageValidationFault("Unsafe native object")
    if directory is not None and is_dir != directory:
        raise StorageValidationFault("Native object type mismatch")
    if not is_dir and links != 1:
        raise StorageValidationFault("Native leaf is hardlinked")
    identity = (vol, fid)
    if handle._identity is not None and handle._identity != identity:
        raise StorageValidationFault("Held object identity changed")
    handle._identity = identity
    return m


def _namespace_parent(parent):
    context = _require_handle(parent)
    if not parent._namespace:
        raise StorageValidationFault("Held namespace-directory rights required")
    _safe_metadata(parent, directory=True)
    if _is_issuer(context) and parent is context._bootstrap_parent:
        return context  # create_relative further restricts this to the exact NEW root
    if getattr(context.anchor, "schema_version", None) == "guidance-provider-storage-v2" and not _is_issuer(context):
        current = parent
        while current is not None and current is not context.b1_handle:
            current = current._request.parent
        if current is None:
            raise StorageValidationFault("Normal namespace is strictly B1-only")
        return context
    # Legacy strict descendants / newly issuer-owned root only.
    current = parent
    while current is not context.root_handle and current is not None:
        current = current._request.parent
    if current is None or (parent is context.root_handle and not _is_issuer(context)):
        raise StorageValidationFault("Namespace must be below enrolled root")
    return context


def _namespace_name(name):
    _validate_component(name)
    # These names are never admitted to the new namespace mutation surface.
    if name.casefold() in ("coordination.lock", "journal.dat"):
        raise StorageValidationFault("Control filename is not a namespace operand")


def open_namespace_directory(parent, name):
    context = _require_handle(parent)
    _namespace_name(name)
    # Parent may be the pinned enrolled root, or one of its held descendants.
    current = parent
    while current is not context.root_handle and current is not None:
        current = current._request.parent
    if current is None:
        raise StorageValidationFault("Parent is outside enrolled root")
    if getattr(context.anchor, "schema_version", None) == "guidance-provider-storage-v2" and not _is_issuer(context):
        # Only the exact enrolled B1 subroot, or descendants of its real identity.
        if parent is context.root_handle:
            if name != "b1":
                raise StorageValidationFault("Controlled root is not a namespace")
        else:
            _namespace_parent(parent)
    pm = _safe_metadata(parent, directory=True)
    h = _nt_open(parent, name, True, False, context, namespace_access=True)
    m = _safe_metadata(h, directory=True)
    if m[0] != pm[0]:
        raise StorageValidationFault("Namespace volume mismatch")
    return h


def create_relative(parent, name, *, directory, operation, object_cap, _reservation=None):
    context = _namespace_parent(parent)
    if _is_issuer(context) and parent is context._bootstrap_parent:
        if name != context._new_root_name or directory is not True or context.root_handle is not None:
            raise StorageValidationFault("Only exact NEW issuer root create admitted")
        _validate_component(name)
    elif _is_issuer(context) and parent is context.root_handle:
        if name not in ("control", "b1") or directory is not True:
            raise StorageValidationFault("Exact NEW issuer root schema required")
        _validate_component(name)
    elif _is_issuer(context) and parent is context.control_handle:
        from revenue_guidance_provisioner import CONTROL_INPUTS
        if name not in CONTROL_INPUTS | {"coordination.lock", "journal.dat"} or directory is not False:
            raise StorageValidationFault("Exact issuer control schema required")
        _validate_component(name)
    else:
        _namespace_name(name)
    if type(directory) is not bool or operation is None or operation is not context._live_operation:
        raise StorageValidationFault("Live operation required")
    pm = _safe_metadata(parent, directory=True)
    h = _nt_open(parent, name, directory, not directory, context, create=True,
                 namespace_access=directory, operation=operation, object_cap=object_cap,
                 staging_reservation=_reservation)
    try:
        m = _safe_metadata(h, directory=directory)
        if m[0] != pm[0] or (not directory and m[2] != 0):
            raise StorageValidationFault("Created object invalid")
        return h
    except BaseException as primary:
        context._closed = True
        context._failure_primary = primary
        raise


def _is_issuer(context):
    from revenue_guidance_storage import NativeIssuerContext
    return type(context) is NativeIssuerContext


def _issuer_security_text(context, role, directory):
    context._issuer_origin.check_live()
    runtime = context._issuer_origin.policy["runtime_sid"]
    if role in ("root", "control", "input"):
        grant = "(A;OICI;GRGX;;;" + runtime + ")" if directory else "(A;;GR;;;" + runtime + ")"
    elif role == "b1":
        if directory:
            # Enrolled B1 subroot itself: DELETE_CHILD, NOT DELETE/DAC/OWNER.
            # Inherit-only ACE gives descendant leaves staging/rename DELETE,
            # without granting deletion of this enrolled directory/ancestry.
            grant = ("(A;;0x1201ff;;;" + runtime + ")" +
                     "(A;OICIIO;0x1301bf;;;" + runtime + ")")
        else:
            grant = "(A;;0x1301bf;;;" + runtime + ")"  # leaf DELETE for native rename
    elif role == "journal":
        grant = "(A;;0x12019f;;;" + runtime + ")"
    else:
        raise StorageValidationFault("Issuer security role")
    return "O:BAG:BAD:P(A;OICI;FA;;;SY)(A;OICI;FA;;;BA)" + grant


def _issuer_creation_security(context, parent, name, directory):
    if parent is context._bootstrap_parent:
        if name != context._new_root_name or not directory:
            raise StorageValidationFault("Exact NEW issuer root required")
        role = "root"
    elif parent is context.root_handle:
        if name not in ("b1", "control") or not directory:
            raise StorageValidationFault("Exact root children required")
        role = name
    elif parent is context.control_handle:
        from revenue_guidance_provisioner import CONTROL_INPUTS
        if name not in CONTROL_INPUTS | {"coordination.lock", "journal.dat"} or directory:
            raise StorageValidationFault("Exact control creation required")
        role = "journal" if name in ("coordination.lock", "journal.dat") else "input"
    else:
        current = parent
        while current is not None and current is not context.b1_handle:
            current = current._request.parent
        if current is None:
            raise StorageValidationFault("Creation outside NEW B1")
        role = "b1"
    text = _issuer_security_text(context, role, directory)
    c, w, k, a = context._issuer_origin.apis
    a.ConvertStringSecurityDescriptorToSecurityDescriptorW.argtypes = [w.LPCWSTR, w.DWORD, c.POINTER(c.c_void_p), c.POINTER(w.DWORD)]
    a.ConvertStringSecurityDescriptorToSecurityDescriptorW.restype = w.BOOL
    a.GetSecurityDescriptorLength.argtypes = [c.c_void_p]
    a.GetSecurityDescriptorLength.restype = w.DWORD
    sd = c.c_void_p()
    if not a.ConvertStringSecurityDescriptorToSecurityDescriptorW(text, 1, c.byref(sd), None):
        raise StorageUnavailableError("Issuer creation protection unavailable")
    try:
        length = a.GetSecurityDescriptorLength(sd)
        if not 20 <= length <= 65536:
            raise StorageValidationFault("Issuer security descriptor size")
        return c.string_at(sd, length)
    finally:
        if k.LocalFree(sd):
            raise StorageUnavailableError("Issuer security allocation cleanup unconfirmed")


def protect_issuer_object(handle, role):
    """Only NEW issuer-owned handles; exact protected DACL/owner + readback.

    No normal runtime ACL mutation, recursive repair or path-based authority.
    This synchronous OS security operation is separate from NT pending I/O.
    """
    context = _require_handle(handle)
    if not _is_issuer(context) or not handle._created or context._live_operation is None:
        raise StorageValidationFault("Genuine NEW issuer custody required")
    import revenue_guidance_provisioner as provisioner
    c, w, k, a = context._issuer_origin.apis
    runtime = context._issuer_origin.policy["runtime_sid"]
    sddl = _issuer_security_text(context, role, handle._is_directory)
    a.ConvertStringSecurityDescriptorToSecurityDescriptorW.argtypes = [w.LPCWSTR, w.DWORD, c.POINTER(c.c_void_p), c.POINTER(w.DWORD)]
    a.ConvertStringSecurityDescriptorToSecurityDescriptorW.restype = w.BOOL
    a.GetSecurityDescriptorOwner.argtypes = [c.c_void_p, c.POINTER(c.c_void_p), c.POINTER(w.BOOL)]
    a.GetSecurityDescriptorOwner.restype = w.BOOL
    a.GetSecurityDescriptorDacl.argtypes = [c.c_void_p, c.POINTER(w.BOOL), c.POINTER(c.c_void_p), c.POINTER(w.BOOL)]
    a.GetSecurityDescriptorDacl.restype = w.BOOL
    a.SetSecurityInfo.argtypes = [w.HANDLE, c.c_int, w.DWORD, c.c_void_p, c.c_void_p, c.c_void_p, c.c_void_p]
    a.SetSecurityInfo.restype = w.DWORD
    sd, owner, acl = c.c_void_p(), c.c_void_p(), c.c_void_p()
    defaulted, present = w.BOOL(), w.BOOL()
    context.budget.charge_work(mutation=True, buffer_bytes=len(sddl) * 2)
    if not a.ConvertStringSecurityDescriptorToSecurityDescriptorW(sddl, 1, c.byref(sd), None):
        raise StorageUnavailableError("Issuer security descriptor unavailable")
    try:
        if (not a.GetSecurityDescriptorOwner(sd, c.byref(owner), c.byref(defaulted))
                or not a.GetSecurityDescriptorDacl(sd, c.byref(present), c.byref(acl), c.byref(defaulted))
                or not present.value or not acl.value
                or a.SetSecurityInfo(handle.handle, 1, 0x80000005, owner, None, acl, None)):
            raise StorageUnavailableError("Issuer object protection failed")
        permitted = (0x1ff if handle._is_directory else 0x101bf) if role == "b1" else (0x19f if role == "journal" else 0)
        provisioner._security(context._issuer_origin.apis, handle.handle, runtime=runtime, allowed=permitted)
    except BaseException as error:
        context._closed = True
        context._failure_primary = error
        raise
    finally:
        if k.LocalFree(sd):
            context._closed = True
            raise StorageUnavailableError("Issuer security buffer cleanup unconfirmed")


def _validate_range(handle, offset, count):
    context = _require_handle(handle)
    if type(offset) is not int or type(count) is not int or offset < 0 or count < 0:
        raise StorageValidationFault("Range must be bounded exact integers")
    if offset + count > handle._object_cap:
        raise StorageValidationFault("Range exceeds admitted object ceiling")
    if _safe_metadata(handle, directory=False)[2] > handle._object_cap:
        raise StorageValidationFault("Existing EOF exceeds admitted object ceiling")
    context.budget._check_time()
    return context


def read_chunk(handle, offset, count, *, _reservation=None):
    context = _validate_range(handle, offset, count)
    if count > IO_CHUNK_BYTES:
        raise StorageValidationFault("Read chunk exceeds 1 MiB")
    if count == 0:
        _check_poison()
        return b""
    context.budget.consume_read(count, owner=handle, reservation=_reservation)
    c = _lazy_bind()
    buf = c.ctypes.create_string_buffer(count)
    pos = c.LARGE_INTEGER(offset)
    p_pos = c.ctypes.pointer(pos)
    rec = _IoRequestRecord(c, handle, c.ntdll.NtReadFile, buffers=(buf, pos, p_pos, _reservation))
    rec.arguments = (rec.wait_handle, None, None, None, rec.p_io_status,
                     buf, count, p_pos, None)
    actual = _submit_io(rec, buffer_bytes=count)
    if actual != count:
        error = StorageValidationFault("Short or zero-progress native read")
        rec.primary_error = error
        handle._last_io = rec
        raise error
    return buf.raw


def read_at(handle: OwnedHandle, offset: int, count: int) -> bytes:
    _validate_range(handle, offset, count)
    # Bounded whole-object compatibility wrapper; kernel buffers stay <=1 MiB.
    data = bytearray()
    for pos in range(offset, offset + count, IO_CHUNK_BYTES):
        data.extend(read_chunk(handle, pos, min(IO_CHUNK_BYTES, offset + count - pos)))
    _check_poison()
    return bytes(data)


def write_chunk(handle, offset, data):
    if type(data) is not bytes or len(data) > IO_CHUNK_BYTES:
        raise StorageValidationFault("Write chunk must be bytes <=1 MiB")
    context = _validate_range(handle, offset, len(data))
    if not handle._writable:
        raise StorageValidationFault("Write permission not held")
    if not data:
        _check_poison()
        return
    context.budget.consume_write(len(data), owner=handle)
    c = _lazy_bind()
    buf = c.ctypes.create_string_buffer(data, len(data))
    pos = c.LARGE_INTEGER(offset)
    p_pos = c.ctypes.pointer(pos)
    rec = _IoRequestRecord(c, handle, c.ntdll.NtWriteFile, buffers=(buf, pos, p_pos, data))
    rec.arguments = (rec.wait_handle, None, None, None, rec.p_io_status,
                     buf, len(data), p_pos, None)
    actual = _submit_io(rec, mutation=True, buffer_bytes=len(data))
    if actual != len(data):
        context._closed = True
        raise StorageValidationFault("Short or zero-progress native write")


def write_at(handle: OwnedHandle, offset: int, data: bytes):
    if type(data) is not bytes:
        raise StorageValidationFault("Data must be bytes")
    _validate_range(handle, offset, len(data))
    for start in range(0, len(data), IO_CHUNK_BYTES):
        write_chunk(handle, offset + start, data[start:start + IO_CHUNK_BYTES])
    _check_poison()


def _set_information(handle, info, info_class, *, target=None, buffers=(), allowed=(STATUS_SUCCESS,)):
    _require_handle(handle)
    c = _lazy_bind()
    p_info = c.ctypes.pointer(info)
    rec = _IoRequestRecord(c, handle, c.ntdll.NtSetInformationFile,
                           target=target, buffers=(info, p_info) + buffers)
    length = c.ctypes.sizeof(info)
    rec.arguments = (rec.wait_handle, rec.p_io_status, p_info, length, info_class)
    return _submit_io(rec, mutation=True, buffer_bytes=length, allowed=allowed)


def truncate(handle, length):
    context = _validate_range(handle, length, 0)
    if not handle._writable:
        raise StorageValidationFault("FILE_WRITE_DATA required for EOF")
    c = _lazy_bind()
    _set_information(handle, c.FILE_END_OF_FILE_INFORMATION(length), NATIVE_END_OF_FILE_INFORMATION)
    try:
        if _safe_metadata(handle, directory=False)[2] != length:
            raise StorageValidationFault("EOF readback failed")
    except BaseException as primary:
        context._closed = True
        context._failure_primary = primary
        raise


def flush(handle: OwnedHandle):
    _require_handle(handle)
    c = _lazy_bind()
    rec = _IoRequestRecord(c, handle, c.ntdll.NtFlushBuffersFile)
    rec.arguments = (rec.wait_handle, rec.p_io_status)
    _submit_io(rec, mutation=True)


def rename_relative(source, target_parent, name, *, replace):
    context = _require_handle(source)
    if _namespace_parent(target_parent) is not context or type(replace) is not bool:
        raise StorageValidationFault("Same-lease rename target required")
    _namespace_name(name)
    sm = _safe_metadata(source, directory=False)
    pm = _safe_metadata(target_parent, directory=True)
    if sm[0] != pm[0] or not source._delete_access or not source._created or source._published:
        raise StorageValidationFault("Rename requires live created file with DELETE")
    if source._temporary_operation is None or source._temporary_operation is not context._live_operation:
        raise StorageValidationFault("Rename outside live creation operation")
    c = _lazy_bind()
    encoded = name.encode("utf-16-le")
    name_offset = c.FILE_RENAME_INFORMATION.FileName.offset
    # Keep the typed aligned allocation and name bytes alive through completion.
    units = (name_offset + len(encoded) + 7) // 8
    backing = (c.ctypes.c_uint64 * units)()
    info = c.FILE_RENAME_INFORMATION.from_buffer(backing)
    info.u.ReplaceIfExists = int(replace)
    info.RootDirectory = c.HANDLE(target_parent.handle)
    info.FileNameLength = len(encoded)
    c.ctypes.memmove(c.ctypes.addressof(backing) + name_offset, encoded, len(encoded))
    p_info = c.ctypes.pointer(info)
    rec = _IoRequestRecord(c, source, c.ntdll.NtSetInformationFile,
                           target=target_parent, buffers=(encoded, backing, info, p_info))
    rec.completion_action = "rename"
    rec.arguments = (rec.wait_handle, rec.p_io_status, p_info,
                     max(c.ctypes.sizeof(info), name_offset + len(encoded)), NATIVE_RENAME_INFORMATION)
    _submit_io(rec, mutation=True, buffer_bytes=c.ctypes.sizeof(backing))
    try:
        if _safe_metadata(source, directory=False)[:2] != sm[:2]:
            raise StorageValidationFault("Renamed source identity changed")
    except BaseException as primary:
        context._closed = True
        context._failure_primary = primary
        raise


def dispose_temporary(handle, operation):
    context = _require_handle(handle)
    _safe_metadata(handle, directory=False)
    if (not handle._created or handle._published or not handle._delete_access or
        operation is None or operation is not context._live_operation or
        operation is not handle._temporary_operation):
        raise StorageValidationFault("Disposition requires this operation's created temporary")
    c = _lazy_bind()
    info = c.FILE_DISPOSITION_INFORMATION(1)
    p_info = c.ctypes.pointer(info)
    rec = _IoRequestRecord(c, handle, c.ntdll.NtSetInformationFile, buffers=(info, p_info))
    rec.arguments = (rec.wait_handle, rec.p_io_status, p_info, c.ctypes.sizeof(info), NATIVE_DISPOSITION_INFORMATION)
    rec.completion_action = "dispose"
    # _submit_io performs admission, then irrevocably marks close-only before
    # submission; after successful FileDispositionInformation, ONLY close.
    _submit_io(rec, mutation=True, buffer_bytes=c.ctypes.sizeof(info))
    try:
        handle.close()
    except BaseException as primary:
        context._closed = True
        context._failure_primary = primary
        raise


def enumerate_names(parent):
    context = _namespace_parent(parent)
    c = _lazy_bind()
    names = []
    seen = set()
    restart = True
    # Lease-lifetime caps include pages/entries from prior enumerations.
    for _ in range(context.budget.max_directory_pages):
        context.budget.charge_directory_page()
        context.budget.consume_read(DIRECTORY_PAGE_BYTES)
        buf = c.ctypes.create_string_buffer(DIRECTORY_PAGE_BYTES)
        rec = _IoRequestRecord(c, parent, c.ntdll.NtQueryDirectoryFile, buffers=(buf,))
        rec.arguments = (rec.wait_handle, None, None, None, rec.p_io_status,
                         buf, DIRECTORY_PAGE_BYTES, NATIVE_NAMES_INFORMATION, 0, None, int(restart))
        actual = _submit_io(rec, buffer_bytes=DIRECTORY_PAGE_BYTES,
                            allowed=(STATUS_SUCCESS, STATUS_NO_MORE_FILES, STATUS_BUFFER_OVERFLOW))
        restart = False
        if rec.final_status == STATUS_NO_MORE_FILES:
            if actual != 0:
                raise StorageValidationFault("Enumeration end carries unexpected bytes")
            return tuple(names)
        if rec.final_status == STATUS_BUFFER_OVERFLOW:
            raise StorageValidationFault("Partial directory record refused")
        if actual < 12 or actual > DIRECTORY_PAGE_BYTES:
            # STATUS_SUCCESS + Information=0 is NOT documented end-of-directory.
            raise StorageValidationFault("Invalid or zero-progress directory page")
        # Complete page was pre-reserved; unused/UNKNOWN work is never refunded.
        raw = buf.raw[:actual]
        offset = 0
        while True:
            if offset % 4 or actual - offset < 12:
                raise StorageValidationFault("Malformed directory header")
            nxt, _, length = struct.unpack_from("<III", raw, offset)
            if length == 0 or length % 2 or length > 510 or offset + 12 + length > actual:
                raise StorageValidationFault("Truncated or oversized directory name")
            end = offset + 12 + length
            if nxt and (nxt % 4 or nxt < 12 + length or offset + nxt > actual - 12):
                raise StorageValidationFault("Malformed directory offset")
            # SDK guarantees aligned, forward nonoverlapping offsets, NOT a
            # minimal-packed stride. For nxt==0, any remaining IOSB-bounded tail
            # is padding, never another name or an invented end-of-directory.
            try:
                name = raw[offset + 12:end].decode("utf-16-le", errors="strict")
            except UnicodeDecodeError:
                raise StorageValidationFault("Invalid directory UTF-16") from None
            context.budget.charge_directory_entry()
            if name not in (".", ".."):
                _validate_component(name)
                if name in seen:
                    raise StorageValidationFault("Duplicate or unstable directory enumeration")
                seen.add(name)
                names.append(name)
            if not nxt:
                break
            offset += nxt
    raise StorageValidationFault("Directory page limit exceeded without documented end")
