"""Protected authority admission through the real provisioner/enroll callers over a fake OS.

03f rows G2-04, G2-05, G2-06, G2-08, G2-09, G2-13 and G2-14. ctypes.WinDLL, the winreg
calls and the provisioner's sys/os/__file__ view are replaced per test by an in-memory
machine: HKLM64 values and key security, file security descriptors, the process token,
synthetic protected release/data trees and handles. The real _apis, _machine, _policy,
_security, _token, _HeldOrigin, controlled_origin, _enrolled, require_anchor,
require_issuer, require_live_issuer, acquire_live_owner, publish_enrollment, the
NativeStorageLease/NativeIssuerContext authority admission, validate_initial_inputs and
enroll run against it. No registry key, ACL, token, DLL, file, process or scheduled task
of this host is touched; real Windows trust roots, ACL/token semantics, ABI and durability
stay G3. The bootstrap is never imported: its fixed protected-path and -I -S -B guards are
pinned as refusals only, and its source shape is characterized statically.

Two lifetime-hold cases leave one parked daemon thread each by design: the product hold
has no exit path, so the fake lifetime event parks forever after the pinned interrupts.
"""
from __future__ import annotations

import argparse  # noqa: F401  (loaded before any guarded bootstrap probe runs under patched sys.flags)
import ast
import builtins
from contextlib import ExitStack, contextmanager
import copy
import ctypes
import dataclasses
import hashlib
import importlib.util
import json
from pathlib import Path
import struct
import sys
import threading
import time
from types import SimpleNamespace
import unittest
from unittest import mock

try:
    import ctypes.wintypes
except (ImportError, ValueError):  # pragma: no cover - only the Windows authority domain needs it
    pass
try:
    import winreg
except ImportError:  # pragma: no cover - the protected authority domain is Windows-only
    winreg = None

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))
sys.path.insert(0, str(REPO))
import revenue_guidance as guidance
import revenue_guidance_enroll as enrollment
import revenue_guidance_overlay as overlay
import revenue_guidance_provisioner as provisioner
import revenue_guidance_revision as revision
import revenue_guidance_storage as storage
import revenue_guidance_windows as windows
from tests import test_revenue_guidance_storage_contract as p2

UA = provisioner.AuthorityUnavailable
SYSTEM, ADMINS, USERS, CREATOR_OWNER = "S-1-5-18", "S-1-5-32-544", "S-1-5-32-545", "S-1-3-0"
TRUSTED_INSTALLER = "S-1-5-80-956008885-3418522649-1831038044-1853292631-2271478464"
RUNTIME = "S-1-5-21-1111111111-2222222222-3333333333-1001"
OTHER_USER = "S-1-5-21-1111111111-2222222222-3333333333-1002"
OPERATOR = "S-1-5-21-1111111111-2222222222-3333333333-500"
FULL_CONTROL, READ_EXECUTE, KEY_ALL_ACCESS, KEY_READ_MASK = 0x1F01FF, 0x1200A9, 0xF003F, 0x20019
RUNTIME_B1_DIRECTORY, RUNTIME_B1_INHERITED, RUNTIME_CONTROL = 0x1201FF, 0x1301BF, 0x12019F
READ_ACCESS, OPEN_FLAGS, PROCESS, SERIAL = 0x80000000 | 0x00020000, 0x02200000, 0x7FFF0001, 0x51E70001
INVALID_HANDLE = ctypes.c_void_p(-1).value
RELEASE = "a1" * 32
GUID = "{01234567-89ab-cdef-0123-456789abcdef}"
OTHER_GUID = "{fedcba98-7654-3210-fedc-ba9876543210}"
BOOT = "enroll-" + "5" * 32
REV = "gir1:" + "c" * 64
OTHER_REV = "gir1:" + "d" * 64
CODE_ROOT = provisioner.CODE_BASE / RELEASE
DATA_ROOT = provisioner.DATA_BASE / BOOT
CONTROL = DATA_ROOT / "control"
LEAF_KEY = provisioner.AUTHORITY_KEY
KEY_CHAIN = ("SOFTWARE", "SOFTWARE\\InvestorIntelligence", LEAF_KEY)
MAGIC, INVALID_MAGIC = b"GJSLT001", b"INVALID!"
SLOT = storage.JOURNAL_SLOT_SIZE
LIMIT = 2 * 1024 * 1024
CFG, PROF = "config/system-bottleneck-explosion-v1.json", "config/revenue-guidance-extraction-profiles-v1.json"
REG, APP = "config/revenue-guidance-v1.json", "config/revenue-guidance-approval-v1.json"
BINDINGS = {"config.json": CFG, "profiles.json": PROF, "registry.json": REG, "approval.json": APP}
BINDINGS.update({name: "scripts/" + name for name in overlay.IMPLEMENTATION_FILES})
GENUINE = {path: (REPO / path).read_bytes() for path in sorted(set(BINDINGS.values()))}
RELEASE_FILES = {name: GENUINE.get(name, b"synthetic approved release bytes for " + name.encode("ascii"))
                 for name in sorted(provisioner.REQUIRED_FILES)}
INSTALLATION = {"schema": "guidance-protected-install-v1", "release_id": RELEASE}
FORBIDDEN_WINREG = ("CreateKey", "CreateKeyEx", "DeleteKey", "DeleteKeyEx", "DeleteValue", "SetValue", "OpenKeyEx",
                    "ConnectRegistry", "LoadKey", "SaveKey", "EnumKey", "EnumValue", "QueryValue", "QueryInfoKey")
BOOTSTRAP = REPO / "scripts" / "revenue_guidance_bootstrap.py"
BOOTSTRAP_SOURCE = BOOTSTRAP.read_text(encoding="utf-8")
FORGED_BOOTSTRAP = provisioner.CODE_BASE / RELEASE / "scripts" / "revenue_guidance_bootstrap.py"
_PARKED_FOREVER = threading.Event()  # never set: a lifetime hold under test parks here by design


def sha(data):
    return hashlib.sha256(data).hexdigest()


def journal_state(revision=REV, pending=REV, intent=None):
    return p2.state(revision, pending, intent)


def journal_bytes(first=0, second=1, *, state=None, bootstrap=BOOT, magic=MAGIC):
    value = journal_state() if state is None else state
    return (p2.slot(first, value, bootstrap=bootstrap, magic=magic) +
            p2.slot(second, value, bootstrap=bootstrap, magic=magic))


def approval_record(**extra_files):
    files = {name: sha(data) for name, data in RELEASE_FILES.items()}
    files.update(extra_files)
    return {"schema": "guidance-protected-approval-v1", "release_id": RELEASE, "files": files, "runtime_sid": RUNTIME}


def _value(item):
    return getattr(item, "value", item)


def _out(reference):
    return getattr(reference, "_obj", reference)  # the object behind ctypes.byref


@contextmanager
def sys_module(name, value):
    """Replace exactly one sys.modules entry and restore it."""
    missing = object()
    previous = sys.modules.get(name, missing)
    sys.modules[name] = value
    try:
        yield
    finally:
        if previous is missing:
            sys.modules.pop(name, None)
        else:
            sys.modules[name] = previous


@dataclasses.dataclass
class Ace:
    sid: str
    mask: int
    kind: int = 0
    flags: int = 0
    size: int = 20


@dataclasses.dataclass
class Security:
    owner: str | None
    aces: list
    dacl: bool = True
    error: int = 0
    acl_info: bool = True
    count: int | None = None
    bad_ace: int | None = None


def file_security(*extra, owner=ADMINS):
    return Security(owner, [Ace(SYSTEM, FULL_CONTROL), Ace(ADMINS, FULL_CONTROL), Ace(USERS, READ_EXECUTE),
                            Ace(CREATOR_OWNER, 0x10000000, flags=0x0B), *extra])


def key_security(*extra, owner=SYSTEM):
    return Security(owner, [Ace(SYSTEM, KEY_ALL_ACCESS), Ace(ADMINS, KEY_ALL_ACCESS), Ace(USERS, KEY_READ_MASK), *extra])


@dataclasses.dataclass(eq=False)
class Node:
    path: object
    directory: bool
    data: bytes = b""
    identity: tuple = (SERIAL, bytes(16))
    security: Security | None = None
    kind: int = 1
    attributes: int = 0
    reparse_tag: int = 0
    links: int = 1
    delete_pending: bool = False
    size: int | None = None
    short_read: bool = False
    info_fail: bool = False
    later_identity: tuple | None = None  # reported from the second open on: a replaced object
    opens: int = 0

    @property
    def label(self):
        return self.path if type(self.path) is str else str(self.path)


class _Export:
    """Native-shaped export: callable, with assignable argtypes/restype like a ctypes function."""
    def __init__(self, implementation):
        self.implementation = implementation

    def __call__(self, *args):
        return self.implementation(*args)


class FakeDll:
    def __init__(self, machine, name, **exports):
        self._machine, self._name = machine, name
        for export, implementation in exports.items():
            setattr(self, export, _Export(implementation))

    def __getattr__(self, name):
        if not name.startswith("__"):
            self._machine.unexpected.append((self._name, name))  # e.g. an elevation or write export
        raise AttributeError(name)


class FakeKey:
    def __init__(self, machine, handle, path, access):
        self.machine, self.handle, self.path, self.access = machine, handle, path, access

    def __int__(self):
        return self.handle

    __index__ = __int__

    def Close(self):
        self.machine.events.append(("RegCloseKey", self.path))
        raised = self.machine.key_close_raise.pop(self.path, None)
        if raised is not None:
            raise raised
        if self.handle in self.machine.closed:
            self.machine.unexpected.append(("second key close", self.path))
        self.machine.closed.add(self.handle)


class FakeMachine:
    """In-memory Windows authority surface; every export records what the product asked for."""

    def __init__(self):
        self.sys = SimpleNamespace()
        self.os = SimpleNamespace(walk=self.walk, listdir=self.listdir)
        self.kernel32 = FakeDll(
            self, "kernel32.dll", CreateFileW=self.create_file, CloseHandle=self.close_handle,
            GetFileInformationByHandleEx=self.file_information, GetFileSizeEx=self.file_size,
            ReadFile=self.read_file, LocalFree=self.local_free, GetCurrentProcess=lambda: PROCESS,
            GetVolumeNameForVolumeMountPointW=self.volume_name, CreateMutexW=self.create_mutex,
            ReleaseMutex=self.release_mutex, GetLastError=lambda: self.last_error)
        self.advapi32 = FakeDll(
            self, "advapi32.dll", GetSecurityInfo=self.security_info, ConvertSidToStringSidW=self.sid_text,
            GetAclInformation=self.acl_information, GetAce=self.ace, OpenProcessToken=self.open_token,
            GetTokenInformation=self.token_information)
        self.shell32 = FakeDll(self, "shell32.dll", IsUserAnAdmin=lambda: int(self.proc_token.admin))
        self.reset()

    def reset(self):
        self.events, self.unexpected, self.loads, self.frees, self.written = [], [], [], [], []
        self._keep, self._sid_pointer, self._sids, self._texts, self._acls, self._descriptors = [], {}, {}, {}, {}, {}
        self.handles, self.closed, self.positions, self.identities = {}, set(), {}, {}
        self.next_handle, self.next_file = 0x1000, 1
        self.close_fail, self.close_raise, self.key_close_raise, self.read_raise = set(), {}, {}, {}
        self.localfree_fail, self.convert_fail = set(), set()
        self.proc_token = SimpleNamespace(user=RUNTIME, elevation=0, admin=False, open_ok=True, user_ok=True,
                                     elevation_ok=True)
        self.token_node = Node("<token>", False, kind=0)
        self.mutex_node = Node("<mutex>", False, kind=0)
        self.mutex = SimpleNamespace(outcome="created", raised=None, release_ok=True, rooted=[])
        self.volume, self.volume_ok, self.last_error, self.readback = "\\\\?\\Volume" + GUID + "\\", True, 0, None
        self.sys.__dict__.clear()
        self.sys.__dict__.update(
            platform="win32", implementation=SimpleNamespace(name="cpython"), version_info=(3, 12, 10, "final", 0),
            maxsize=2 ** 63 - 1, flags=SimpleNamespace(isolated=1, no_site=1, dont_write_bytecode=1),
            executable=str(CODE_ROOT / "Python" / "python.exe"),
            path=[str(CODE_ROOT / "scripts"), str(CODE_ROOT / "Python" / "python312.zip"), str(CODE_ROOT / "Python")],
            modules={"builtins": SimpleNamespace(), "zipimport": SimpleNamespace(__file__="<frozen>"),
                     "revenue_guidance_bootstrap": SimpleNamespace(
                         __file__=str(CODE_ROOT / "scripts" / "revenue_guidance_bootstrap.py")),
                     "revenue_guidance_provisioner": SimpleNamespace(
                         __file__=str(CODE_ROOT / "scripts" / "revenue_guidance_provisioner.py"))})
        self.nodes = {}
        self.ensure_directories(CODE_ROOT)
        self.add(CODE_ROOT, True)
        for name, data in RELEASE_FILES.items():
            path = CODE_ROOT.joinpath(*name.split("/"))
            self.ensure_directories(path)
            self.add(path, False, data)
        self.ensure_directories(DATA_ROOT)
        self.add(DATA_ROOT, True)
        self.add(CONTROL, True)
        self.add(DATA_ROOT / "b1", True, security=file_security(
            Ace(RUNTIME, RUNTIME_B1_DIRECTORY), Ace(RUNTIME, RUNTIME_B1_INHERITED, flags=0x0B)))
        for name in sorted(provisioner.CONTROL_INPUTS):
            self.add(CONTROL / name, False, RELEASE_FILES[BINDINGS[name]])
        self.add(CONTROL / "coordination.lock", False, b"\x00", security=file_security(Ace(RUNTIME, RUNTIME_CONTROL)))
        self.add(CONTROL / "journal.dat", False, journal_bytes(), security=file_security(Ace(RUNTIME, RUNTIME_CONTROL)))
        self.keys = {KEY_CHAIN[0]: Node(KEY_CHAIN[0], False, kind=4, security=key_security(owner=TRUSTED_INSTALLER)),
                     KEY_CHAIN[1]: Node(KEY_CHAIN[1], False, kind=4, security=key_security()),
                     KEY_CHAIN[2]: Node(KEY_CHAIN[2], False, kind=4, security=key_security())}
        self.values = {}
        self.set_value("Approval", approval_record())
        self.set_value("Installation", INSTALLATION)
        self.set_value("Enrollment", self.enrollment_record())

    # synthetic trees ---------------------------------------------------------------------------
    def add(self, path, directory, data=b"", **fields):
        fields.setdefault("security", file_security())
        node = Node(Path(path), directory, data, (SERIAL, self.next_file.to_bytes(16, "little")), **fields)
        self.next_file += 1
        self.nodes[Path(path)] = node
        return node

    def ensure_directories(self, path):
        for parent in reversed(Path(path).parents):
            if parent not in self.nodes:
                self.add(parent, True)

    def node(self, path):
        return self.nodes[Path(path)]

    def release(self, name):
        return self.node(CODE_ROOT.joinpath(*name.split("/")))

    def replace_identity(self, path):
        self.node(path).identity = (SERIAL, (0xF000 + self.next_file).to_bytes(16, "little"))
        self.next_file += 1

    def identity(self, path):
        return storage.ObjectIdentity(*self.node(path).identity)

    def anchor(self):
        return storage._validate_anchor_data(storage.RootAnchor(
            "guidance-provider-storage-v2", BOOT, GUID, self.identity("C:\\"),
            (("ProgramData", self.identity("C:\\ProgramData")),
             ("InvestorIntelligenceGuidance", self.identity(provisioner.DATA_BASE)), (BOOT, self.identity(DATA_ROOT))),
            self.identity(CONTROL / "coordination.lock"), self.identity(CONTROL / "journal.dat"), 1, True,
            self.identity(CONTROL), self.identity(DATA_ROOT / "b1"),
            tuple(sorted((name, sha(self.node(CONTROL / name).data)) for name in provisioner.CONTROL_INPUTS))))

    def enrollment_record(self, **changes):
        record = {"schema": "guidance-protected-enrollment-v1", "release_id": RELEASE,
                  "anchor": provisioner.anchor_to_data(self.anchor()), "initial_revision": REV}
        record.update(changes)
        return record

    def set_value(self, name, value, kind=None):
        self.values[name] = (value if type(value) is str else json.dumps(value),
                             winreg.REG_SZ if kind is None else kind)

    def children(self, path):
        path = Path(path)
        return sorted((node for key, node in self.nodes.items() if key != path and key.parent == path),
                      key=lambda node: node.path.name.lower())

    def walk(self, top, topdown=True, onerror=None, followlinks=False):
        self.events.append(("walk", str(top), followlinks))
        pending = [Path(top)]
        while pending:
            current = pending.pop()
            nodes = self.children(current)
            directories = [node.path.name for node in nodes if node.directory]
            yield str(current), directories, [node.path.name for node in nodes if not node.directory]
            pending.extend(current / name for name in reversed(directories))

    def listdir(self, path):
        self.events.append(("listdir", str(path)))
        return [node.path.name for node in self.children(path)]

    # handles and memory --------------------------------------------------------------------------
    def load_library(self, name, mode=0, handle=None, use_errno=False, use_last_error=False, winmode=None):
        self.loads.append((name, winmode))
        library = {"kernel32.dll": self.kernel32, "advapi32.dll": self.advapi32, "shell32.dll": self.shell32}.get(name)
        if library is None:
            self.unexpected.append(("library", name))
            raise OSError("synthetic loader refuses " + str(name))
        return library

    def _open(self, node):
        handle = self.next_handle
        self.next_handle += 4
        node.opens += 1
        self.handles[handle] = node
        self.identities[handle] = node.later_identity if node.opens > 1 and node.later_identity else node.identity
        return handle

    def _held(self, handle):
        node = self.handles.get(handle)
        return None if node is None or handle in self.closed else node

    def live(self):
        return sorted(self.handles[handle].label for handle in self.handles if handle not in self.closed)

    def _allocate(self):
        buffer = ctypes.create_string_buffer(16)
        self._keep.append(buffer)
        return ctypes.addressof(buffer)

    def sid_pointer(self, sid):
        if sid not in self._sid_pointer:
            pointer = self._allocate()
            self._sid_pointer[sid] = pointer
            self._sids[pointer] = sid
        return self._sid_pointer[sid]

    def _acl(self, security):
        entries = []
        for ace in security.aces:
            buffer = ctypes.create_string_buffer(32)
            self._keep.append(buffer)
            header = bytes((ace.kind, ace.flags)) + ace.size.to_bytes(2, "little") + ace.mask.to_bytes(4, "little")
            ctypes.memmove(buffer, header, 8)
            address = ctypes.addressof(buffer)
            self._sids[address + 8] = ace.sid
            entries.append(address)
        pointer = self._allocate()
        self._acls[pointer] = SimpleNamespace(entries=entries, info=security.acl_info, bad=security.bad_ace,
                                              count=len(entries) if security.count is None else security.count)
        return pointer

    # kernel32 ----------------------------------------------------------------------------------------
    def create_file(self, path, access, share, attributes, disposition, flags, template):
        self.events.append(("CreateFileW", path, access, share, disposition, flags))
        node = self.nodes.get(Path(path))
        if node is None or attributes is not None or template is not None:
            self.last_error = 2
            return INVALID_HANDLE
        return self._open(node)

    def close_handle(self, handle):
        handle = _value(handle)
        node = self.handles.get(handle)
        if node is None:
            self.unexpected.append(("CloseHandle", handle))
            return 0
        self.events.append(("CloseHandle", node.label))
        raised = self.close_raise.pop(node.label, None)
        if raised is not None:
            raise raised
        if node.label in self.close_fail:
            return 0
        if handle in self.closed:
            self.unexpected.append(("second close", node.label))
        self.closed.add(handle)
        return 1

    def file_information(self, handle, cls, buffer, size):
        node = self._held(handle)
        if node is None or node.info_fail:
            return 0
        attributes = (0x10 if node.directory else 0x80) | node.attributes
        if cls == 9 and size == 8:
            buffer[0], buffer[1] = attributes, node.reparse_tag
            return 1
        if cls == 1 and size == 24:
            end = len(node.data) if node.size is None else node.size
            raw = struct.pack("<qqIBB2x", 0, end, node.links, int(node.delete_pending), int(node.directory))
        elif cls == 18 and size == 24:
            serial, file_id = self.identities[handle]
            raw = struct.pack("<Q", serial) + file_id
        elif cls == 0 and size == 40:
            raw = struct.pack("<qqqqI4x", 1, 2, 3, 4, attributes)
        else:
            self.unexpected.append(("information class", cls, size))
            return 0
        ctypes.memmove(buffer, raw, len(raw))
        return 1

    def file_size(self, handle, reference):
        node = self._held(handle)
        if node is None:
            return 0
        _out(reference).value = len(node.data) if node.size is None else node.size
        return 1

    def read_file(self, handle, buffer, count, got, overlapped):
        node = self._held(handle)
        if node is None or overlapped is not None:
            return 0
        self.events.append(("ReadFile", node.label, count))
        raised = self.read_raise.get(node.label)
        if raised is not None:
            raise raised
        position = self.positions.get(handle, 0)
        chunk = node.data[position:position + count]
        if node.short_read:
            chunk = chunk[:-1]
        ctypes.memmove(buffer, chunk, len(chunk))
        _out(got).value = len(chunk)
        self.positions[handle] = position + len(chunk)
        return 1

    def local_free(self, pointer):
        address = _value(pointer)
        if address in self._texts:
            sid = self._texts.pop(address)
            self.frees.append(("sid", sid))
            return address if sid in self.localfree_fail else None
        if address in self._descriptors:
            label = self._descriptors.pop(address)
            self.frees.append(("descriptor", label))
            return address if "descriptor" in self.localfree_fail else None
        self.unexpected.append(("LocalFree", address))
        return address

    def volume_name(self, mount, buffer, size):
        self.events.append(("GetVolumeNameForVolumeMountPointW", mount))
        if mount != "C:\\" or size != 64 or not self.volume_ok:
            return 0
        buffer.value = self.volume
        return 1

    def create_mutex(self, attributes, initial, name):
        self.events.append(("CreateMutexW", attributes, initial, name))
        self.mutex.rooted.append(provisioner._unsettled_origin)  # origin custody while the creation call is in flight
        if self.mutex.raised is not None:
            raise self.mutex.raised
        if self.mutex.outcome == "failed":
            self.last_error = 5
            return None
        handle = self._open(self.mutex_node)
        self.last_error = 183 if self.mutex.outcome == "existing" else 0
        return handle

    def release_mutex(self, handle):
        node = self._held(_value(handle))
        self.events.append(("ReleaseMutex", node.label if node else handle))
        return int(node is self.mutex_node and self.mutex.release_ok)

    # advapi32 ----------------------------------------------------------------------------------------
    def security_info(self, handle, kind, information, owner, group, dacl, sacl, descriptor):
        node = self._held(_value(handle))
        self.events.append(("GetSecurityInfo", node.label if node else handle, kind))
        if (node is None or node.security is None or node.kind != kind or information != 5
                or group is not None or sacl is not None):
            return 87
        security = node.security
        if security.error:
            return security.error
        _out(owner).value = self.sid_pointer(security.owner) if security.owner else None
        _out(dacl).value = self._acl(security) if security.dacl else None
        pointer = self._allocate()
        self._descriptors[pointer] = node.label
        _out(descriptor).value = pointer
        return 0

    def acl_information(self, dacl, information, size, cls):
        acl = self._acls.get(_value(dacl))
        if acl is None or cls != 2 or size != 12 or not acl.info:
            return 0
        information[0], information[1], information[2] = acl.count, 0, 0
        return 1

    def ace(self, dacl, index, reference):
        acl = self._acls.get(_value(dacl))
        if acl is None or index == acl.bad or not 0 <= index < len(acl.entries):
            return 0
        _out(reference).value = acl.entries[index]
        return 1

    def sid_text(self, pointer, reference):
        sid = self._sids.get(_value(pointer))
        if sid is None or sid in self.convert_fail:
            return 0
        text = ctypes.create_unicode_buffer(sid)
        self._keep.append(text)
        address = ctypes.addressof(text)
        self._texts[address] = sid
        _out(reference).value = address
        return 1

    def open_token(self, process, access, reference):
        self.events.append(("OpenProcessToken", access))
        if _value(process) != PROCESS or not self.proc_token.open_ok:
            return 0
        _out(reference).value = self._open(self.token_node)
        return 1

    def token_information(self, token, cls, buffer, size, got):
        node = self._held(_value(token))
        self.events.append(("GetTokenInformation", cls))
        if node is not self.token_node:
            return 0
        if cls == 1 and size == 512 and self.proc_token.user_ok:
            ctypes.c_void_p.from_buffer(buffer).value = self.sid_pointer(self.proc_token.user)  # TOKEN_USER.User.Sid
            return 1
        if cls == 20 and size == 4 and self.proc_token.elevation_ok:
            _out(buffer).value = self.proc_token.elevation
            return 1
        return 0

    # winreg ----------------------------------------------------------------------------------------------
    def open_key(self, root, path, reserved=0, access=0):
        self.events.append(("OpenKey", root, path, reserved, access))
        node = self.keys.get(path)
        if root != winreg.HKEY_LOCAL_MACHINE or node is None:
            raise FileNotFoundError(2, "synthetic registry key absent")
        return FakeKey(self, self._open(node), path, access)

    def query_value(self, key, name):
        self.events.append(("QueryValueEx", key.path, name))
        if key.path != LEAF_KEY or key.handle in self.closed:
            self.unexpected.append(("QueryValueEx", key.path, name))
            raise OSError(6, "synthetic invalid key")
        if name not in self.values:
            raise FileNotFoundError(2, "synthetic registry value absent")
        value, kind = self.values[name]
        if name == "Enrollment" and self.written and self.readback is not None:
            value = self.readback
        return value, kind

    def set_value_ex(self, key, name, reserved, kind, value):
        self.events.append(("SetValueEx", key.path, name, reserved, kind))
        if not key.access & winreg.KEY_SET_VALUE or key.handle in self.closed:
            raise PermissionError(5, "synthetic access denied")
        self.values[name] = (value, kind)
        self.written.append((name, value))

    def flush_key(self, key):
        self.events.append(("FlushKey", key.path))

    def forbidden(self, name):
        def refuse(*args, **kwargs):
            self.unexpected.append(("winreg", name))
            raise AssertionError("winreg." + name + " must not be used")
        return refuse


class InterruptingEvent:
    """A lifetime event that raises the given interrupts, then parks forever."""
    def __init__(self, interrupts):
        self.interrupts = list(interrupts)
        self.calls = 0
        self.parked = threading.Event()

    def wait(self, timeout=None):
        self.calls += 1
        if self.interrupts:
            raise self.interrupts.pop(0)
        self.parked.set()
        _PARKED_FOREVER.wait()

    def set(self):
        raise AssertionError("product code signalled the lifetime event")


@unittest.skipUnless(sys.platform == "win32" and winreg is not None, "the protected authority domain is Windows-only")
class _AuthorityDomain(unittest.TestCase):
    def setUp(self):
        self.m = FakeMachine()
        enter = self.enterContext
        enter(mock.patch.object(ctypes, "WinDLL", self.m.load_library))
        enter(mock.patch.object(winreg, "OpenKey", self.m.open_key))
        enter(mock.patch.object(winreg, "QueryValueEx", self.m.query_value))
        enter(mock.patch.object(winreg, "SetValueEx", self.m.set_value_ex))
        enter(mock.patch.object(winreg, "FlushKey", self.m.flush_key))
        for name in FORBIDDEN_WINREG:
            if hasattr(winreg, name):
                enter(mock.patch.object(winreg, name, self.m.forbidden(name)))
        enter(mock.patch.object(provisioner, "sys", self.m.sys))
        enter(mock.patch.object(provisioner, "os", self.m.os))
        enter(mock.patch.object(provisioner, "__file__", str(CODE_ROOT / "scripts" / "revenue_guidance_provisioner.py")))
        enter(mock.patch.object(provisioner, "_unsettled_origin", None))
        enter(mock.patch.object(windows, "_poisoned", False))
        enter(mock.patch.object(windows, "_unsettled_close_owner", None))
        enter(mock.patch.object(windows, "_quarantine_record", None))
        self.bind = enter(mock.patch.object(windows, "_lazy_bind", side_effect=AssertionError("native binding reached")))

    def tearDown(self):
        self.assertEqual(self.m.unexpected, [])
        self.assertTrue({name for name, _ in self.m.loads} <= {"kernel32.dll", "advapi32.dll", "shell32.dll"})
        self.assertTrue(all(mode == 0x800 for _, mode in self.m.loads))  # LOAD_LIBRARY_SEARCH_SYSTEM32 only
        self.bind.assert_not_called()

    def mark(self):
        return len(self.m.events)

    def calls(self, name, since=0):
        return [event for event in self.m.events[since:] if event[0] == name]

    def refused(self, function, *args, **kwargs):
        with self.assertRaises(UA) as caught:
            function(*args, **kwargs)
        self.assertEqual(str(caught.exception), "TRUST_AUTHORITY_UNAVAILABLE")
        return caught.exception

    def assertSettled(self):
        self.assertIsNone(provisioner._unsettled_origin)
        self.assertEqual(provisioner.origin_custody_status(), "SETTLED")
        self.assertEqual(self.m.live(), [])

    def assertNoAuthorityWrite(self):
        self.assertEqual(self.calls("SetValueEx") + self.calls("FlushKey"), [])
        self.assertEqual(self.m.written, [])

    def as_issuer(self):
        self.m.proc_token.user, self.m.proc_token.elevation, self.m.proc_token.admin = OPERATOR, 1, True

    def unenrolled(self):
        self.m.values.pop("Enrollment", None)


class InterpreterBindingTests(_AuthorityDomain):
    """G2-05/G2-14: binding is never authority, never cached, and vetoed by unresolved custody."""

    def test_binding_needs_the_exact_interpreter_and_loads_system32_libraries_each_time(self):
        first, second = provisioner._apis(), provisioner._apis()
        self.assertIs(first[0], ctypes)
        self.assertIs(first[1], ctypes.wintypes)
        self.assertIs(first[2], self.m.kernel32)
        self.assertIs(first[3], self.m.advapi32)
        self.assertEqual(first, second)
        self.assertEqual(self.m.loads, [("kernel32.dll", 0x800), ("advapi32.dll", 0x800)] * 2)
        self.assertEqual(self.m.events, [])

    def test_interpreter_mismatch_refuses_before_any_library_load(self):
        rows = [("platform", "linux"), ("platform", "cygwin"), ("implementation", SimpleNamespace(name="pypy")),
                ("version_info", (3, 12, 9, "final", 0)), ("version_info", (3, 12, 11, "final", 0)),
                ("version_info", (3, 13, 0, "final", 0)), ("maxsize", 2 ** 31 - 1)]
        for attribute, value in rows:
            with self.subTest(attribute=attribute, value=value), mock.patch.object(self.m.sys, attribute, value):
                self.refused(provisioner._apis)
                self.refused(provisioner.controlled_origin)
        self.assertEqual(self.m.loads, [])
        self.assertEqual(self.m.events, [])

    def test_unresolved_origin_custody_vetoes_binding_and_every_acquisition(self):
        anchor = self.m.anchor()
        with mock.patch.object(provisioner, "_unsettled_origin", object()):
            for call in (provisioner._apis, provisioner.controlled_origin, provisioner.enrolled_anchor,
                         provisioner.require_issuer, provisioner.acquire_live_owner,
                         lambda: provisioner.require_anchor(anchor)):
                self.refused(call)
            self.assertEqual(provisioner.origin_custody_status(), "UNRESOLVED")
        self.assertEqual(self.m.loads, [])
        self.assertEqual(self.m.events, [])

    def test_the_refusal_category_is_fixed(self):
        self.assertEqual(str(UA()), "TRUST_AUTHORITY_UNAVAILABLE")
        self.assertEqual(UA().args, ("TRUST_AUTHORITY_UNAVAILABLE",))


class MachineRecordTests(_AuthorityDomain):
    """G2-04: every read opens the fixed HKLM64 chain, checks key security and parses strictly."""

    def test_every_read_opens_the_fixed_hklm64_chain_and_retains_each_key_before_its_security_check(self):
        origin = provisioner._HeldOrigin()
        self.assertEqual(provisioner._machine(origin, "Installation"), INSTALLATION)
        self.assertEqual(provisioner._machine(origin, "Installation"), INSTALLATION)
        one = [("OpenKey", KEY_CHAIN[0]), ("GetSecurityInfo", KEY_CHAIN[0]), ("OpenKey", KEY_CHAIN[1]),
               ("GetSecurityInfo", KEY_CHAIN[1]), ("OpenKey", KEY_CHAIN[2]), ("GetSecurityInfo", KEY_CHAIN[2]),
               ("QueryValueEx", LEAF_KEY)]
        sequence = [(event[0], event[2] if event[0] == "OpenKey" else event[1]) for event in self.m.events
                    if event[0] in ("OpenKey", "GetSecurityInfo", "QueryValueEx")]
        self.assertEqual(sequence, one * 2)  # no cached key, value or verdict
        access = winreg.KEY_READ | winreg.KEY_WOW64_64KEY
        self.assertEqual({event[1:] for event in self.calls("OpenKey")},
                         {(winreg.HKEY_LOCAL_MACHINE, path, 0, access) for path in KEY_CHAIN})
        self.assertEqual({event[2] for event in self.calls("GetSecurityInfo")}, {4})
        self.assertEqual(len(origin.registry), 6)
        origin.close()
        self.assertSettled()
        self.assertEqual(len(self.calls("RegCloseKey")), 6)
        self.assertNoAuthorityWrite()

    def test_missing_type_and_json_shape_refusals_keep_the_opened_keys_for_cleanup(self):
        rows = [("absent", None), ("expand string", ('{"schema": 1}', winreg.REG_EXPAND_SZ)),
                ("binary", (b"{}", winreg.REG_BINARY)), ("multi string", (["{}"], winreg.REG_MULTI_SZ)),
                ("non-text REG_SZ", (b"{}", winreg.REG_SZ)), ("duplicate member", ('{"a": 1, "a": 2}', winreg.REG_SZ)),
                ("NaN", ('{"a": NaN}', winreg.REG_SZ)), ("negative Infinity", ('{"a": -Infinity}', winreg.REG_SZ)),
                ("over 2 MiB", ('"' + "x" * (LIMIT - 1) + '"', winreg.REG_SZ))]
        for label, stored in rows:
            with self.subTest(label):
                self.m.reset()
                if stored is None:
                    del self.m.values["Approval"]
                else:
                    self.m.values["Approval"] = stored
                origin = provisioner._HeldOrigin()
                self.refused(provisioner._machine, origin, "Approval")
                self.assertEqual(len(origin.registry), 3)
                origin.close()
                self.assertSettled()

    def test_exact_size_limit_is_admitted_and_only_enrollment_may_be_absent(self):
        self.m.values["Approval"] = ('"' + "x" * (LIMIT - 2) + '"', winreg.REG_SZ)
        origin = provisioner._HeldOrigin()
        self.assertEqual(len(provisioner._machine(origin, "Approval")), LIMIT - 2)
        self.unenrolled()
        self.assertIsNone(provisioner._machine(origin, "Enrollment", missing=True))
        self.refused(provisioner._machine, origin, "Enrollment")
        origin.close()
        self.assertSettled()

    def test_writable_or_foreign_owned_authority_keys_are_refused(self):
        refused = [
            ("leaf KEY_SET_VALUE", 2, key_security(Ace(USERS, 0x0002))),
            ("leaf KEY_CREATE_SUB_KEY", 2, key_security(Ace(USERS, 0x0004))),
            ("leaf KEY_CREATE_LINK", 2, key_security(Ace(USERS, 0x0020))),
            ("leaf DELETE", 2, key_security(Ace(USERS, 0x10000))),
            ("leaf WRITE_DAC", 2, key_security(Ace(USERS, 0x40000))),
            ("leaf WRITE_OWNER", 2, key_security(Ace(USERS, 0x80000))),
            ("leaf GENERIC_WRITE", 2, key_security(Ace(USERS, 0x40000000))),
            ("leaf GENERIC_ALL", 2, key_security(Ace(USERS, 0x10000000))),
            ("leaf runtime KEY_SET_VALUE", 2, key_security(Ace(RUNTIME, 0x0002))),
            ("leaf TrustedInstaller full control", 2, key_security(Ace(TRUSTED_INSTALLER, KEY_ALL_ACCESS))),
            ("leaf owned by TrustedInstaller", 2, key_security(owner=TRUSTED_INSTALLER)),
            ("leaf owned by runtime", 2, key_security(owner=RUNTIME)),
            ("leaf NULL DACL", 2, Security(SYSTEM, [], dacl=False)),
            ("ancestor KEY_SET_VALUE", 1, key_security(Ace(USERS, 0x0002))),
            ("ancestor owned by Users", 0, key_security(owner=USERS)),
        ]
        for label, index, security in refused:
            with self.subTest(label):
                self.m.reset()
                self.m.keys[KEY_CHAIN[index]].security = security
                origin = provisioner._HeldOrigin()
                self.refused(provisioner._machine, origin, "Approval")
                self.assertEqual(len(origin.registry), index + 1)
                self.assertEqual(self.calls("QueryValueEx"), [])
                origin.close()
                self.assertSettled()
        admitted = [
            ("ancestor owned by TrustedInstaller", 0, key_security(owner=TRUSTED_INSTALLER)),
            ("ancestor TrustedInstaller full control", 1, key_security(Ace(TRUSTED_INSTALLER, KEY_ALL_ACCESS))),
            ("leaf Users query/enumerate/notify", 2, key_security(Ace(USERS, 0x0019))),
            ("leaf deny ACE", 2, key_security(Ace(USERS, KEY_ALL_ACCESS, kind=1))),
            ("leaf inherit-only ACE", 2, key_security(Ace(USERS, KEY_ALL_ACCESS, flags=0x0B))),
        ]
        for label, index, security in admitted:
            with self.subTest(label):
                self.m.reset()
                self.m.keys[KEY_CHAIN[index]].security = security
                origin = provisioner._HeldOrigin()
                self.assertEqual(provisioner._machine(origin, "Approval"), approval_record())
                origin.close()
                self.assertSettled()


class PolicyShapeTests(unittest.TestCase):
    """G2-04: the externally seeded Approval must name the complete package closure exactly."""

    def test_complete_external_approval_is_admitted_up_to_the_file_bound(self):
        base = approval_record()
        self.assertIs(provisioner._policy(base), base)
        files = dict(base["files"])
        files.update({f"config/extra-{index:04d}.json": "0" * 64 for index in range(4096 - len(files))})
        self.assertEqual(len(provisioner._policy(dict(base, files=files))["files"]), 4096)

    def test_shape_identity_and_name_refusals(self):
        base = approval_record()
        def without(*names):
            return {name: digest for name, digest in base["files"].items() if name not in names}
        def plus(name, digest="0" * 64):
            return dict(base["files"], **{name: digest})
        too_many = dict(base["files"])
        too_many.update({f"config/extra-{index:04d}.json": "0" * 64 for index in range(4097 - len(too_many))})
        rows = [
            ("not an object", [base]),
            ("self-signature member", dict(base, signature="00")),
            ("runtime_sid absent", {key: value for key, value in base.items() if key != "runtime_sid"}),
            ("schema v2", dict(base, schema="guidance-protected-approval-v2")),
            ("release id upper case", dict(base, release_id=RELEASE.upper())),
            ("release id short", dict(base, release_id=RELEASE[:-1])),
            ("runtime is SYSTEM", dict(base, runtime_sid=SYSTEM)),
            ("runtime is Administrators", dict(base, runtime_sid=ADMINS)),
            ("runtime short domain SID", dict(base, runtime_sid="S-1-5-21-1-2-1001")),
            ("files as list", dict(base, files=sorted(base["files"]))),
            ("host closure file missing", dict(base, files=without("scripts/revenue_guidance_host.py"))),
            ("interpreter missing", dict(base, files=without("Python/python.exe"))),
            ("4097 files", dict(base, files=too_many)),
            ("backslash name", dict(base, files=plus("scripts\\evil.py"))),
            ("drive name", dict(base, files=plus("C:/evil.py"))),
            ("absolute name", dict(base, files=plus("/scripts/evil.py"))),
            ("parent segment", dict(base, files=plus("scripts/../evil.py"))),
            ("current segment", dict(base, files=plus("scripts/./evil.py"))),
            ("empty segment", dict(base, files=plus("scripts//evil.py"))),
            ("trailing dot", dict(base, files=plus("scripts/evil."))),
            ("hidden segment", dict(base, files=plus(".hidden/evil.py"))),
            ("space in name", dict(base, files=plus("scripts/ev il.py"))),
            ("path configuration file", dict(base, files=plus("Python/Lib/evil.pth"))),
            ("bytecode file", dict(base, files=plus("scripts/__pycache__/evil.PYC"))),
            ("name over 240", dict(base, files=plus("config/" + "a" * 240))),
            ("digest upper case", dict(base, files=plus("config/extra.json", "A" * 64))),
            ("digest short", dict(base, files=plus("config/extra.json", "0" * 63))),
            ("digest not text", dict(base, files=plus("config/extra.json", 0))),
            ("case-folded duplicate", dict(base, files=plus("CONFIG/revenue-guidance-v1.json"))),
        ]
        for label, policy in rows:
            with self.subTest(label):
                with self.assertRaises(UA):
                    provisioner._policy(policy)


class SecurityDescriptorTests(_AuthorityDomain):
    """G2-05: owner/DACL admission of protected objects, platform ancestors and the runtime carve-out."""

    def setUp(self):
        super().setUp()
        self.apis = provisioner._apis()
        self.file = self.m.add(r"C:\SecurityProbe\probe.bin", False, b"probe")
        self.key = self.m.keys[LEAF_KEY]

    def check(self, node, security, kind=1, **options):
        node.security = security
        handle = self.m._open(node)
        try:
            return provisioner._security(self.apis, handle, kind, **options)
        finally:
            self.m.closed.add(handle)

    def test_descriptor_matrix(self):
        def users(mask, **fields):
            return file_security(Ace(USERS, mask, **fields))
        runtime_b1 = {"runtime": RUNTIME, "allowed": 0x1ff}
        runtime_journal = {"runtime": RUNTIME, "allowed": 0x19f}
        rows = [
            ("baseline protected file", file_security(), 1, {}, True),
            ("query failure", dataclasses.replace(file_security(), error=5), 1, {}, False),
            ("no owner", file_security(owner=None), 1, {}, False),
            ("Users owner", file_security(owner=USERS), 1, {}, False),
            ("runtime owner", file_security(owner=RUNTIME), 1, {}, False),
            ("TrustedInstaller owner on a protected object", file_security(owner=TRUSTED_INSTALLER), 1, {}, False),
            ("TrustedInstaller owner on a platform ancestor", file_security(owner=TRUSTED_INSTALLER), 1,
             {"ancestor": True}, True),
            ("NULL DACL", dataclasses.replace(file_security(), dacl=False), 1, {}, False),
            ("ACL information failure", dataclasses.replace(file_security(), acl_info=False), 1, {}, False),
            ("257 ACEs", dataclasses.replace(file_security(), count=257), 1, {}, False),
            ("256 trusted ACEs", Security(ADMINS, [Ace(ADMINS, FULL_CONTROL)] * 256), 1, {}, True),
            ("unreadable ACE", dataclasses.replace(file_security(), bad_ace=1), 1, {}, False),
            ("short ACE", file_security(Ace(ADMINS, FULL_CONTROL, size=11)), 1, {}, False),
            ("audit ACE type", file_security(Ace(ADMINS, 0, kind=2)), 1, {}, False),
            ("object ACE type", file_security(Ace(ADMINS, 0, kind=5)), 1, {}, False),
            ("callback ACE type", file_security(Ace(ADMINS, 0, kind=9)), 1, {}, False),
            ("deny ACE ignored", users(FULL_CONTROL, kind=1), 1, {}, True),
            ("inherit-only grant ignored", users(FULL_CONTROL, flags=0x0B), 1, {}, True),
            ("TrustedInstaller full control on a platform ancestor", file_security(Ace(TRUSTED_INSTALLER, FULL_CONTROL)),
             1, {"ancestor": True}, True),
            ("TrustedInstaller full control on a protected object", file_security(Ace(TRUSTED_INSTALLER, FULL_CONTROL)),
             1, {}, False),
            ("runtime B1 directory grant", file_security(Ace(RUNTIME, RUNTIME_B1_DIRECTORY)), 1, runtime_b1, True),
            ("runtime B1 grant plus DELETE", file_security(Ace(RUNTIME, RUNTIME_B1_DIRECTORY | 0x10000)), 1,
             runtime_b1, False),
            ("runtime B1 grant plus WRITE_DAC", file_security(Ace(RUNTIME, RUNTIME_B1_DIRECTORY | 0x40000)), 1,
             runtime_b1, False),
            ("another user holding the runtime grant", file_security(Ace(OTHER_USER, RUNTIME_B1_DIRECTORY)), 1,
             runtime_b1, False),
            ("runtime grant without the carve-out", file_security(Ace(RUNTIME, RUNTIME_B1_DIRECTORY)), 1, {}, False),
            ("runtime journal grant", file_security(Ace(RUNTIME, RUNTIME_CONTROL)), 1, runtime_journal, True),
            ("runtime journal grant plus DELETE_CHILD", file_security(Ace(RUNTIME, RUNTIME_CONTROL | 0x40)), 1,
             runtime_journal, False),
        ]
        for bit in (0x2, 0x4, 0x10, 0x40, 0x100, 0x10000, 0x40000, 0x80000, 0x10000000, 0x40000000):
            rows.append((f"Users write bit {bit:#x}", users(bit), 1, {}, False))
        for bit in (0x1, 0x8, 0x20, 0x80, 0x20000, 0x100000, 0x20000000, 0x80000000, READ_EXECUTE):
            rows.append((f"Users read bit {bit:#x}", users(bit), 1, {}, True))
        for bit, admitted in ((0x2, True), (0x4, True), (0x10, False), (0x40, False), (0x100, False),
                              (0x10000, False), (0x40000, False), (0x40000000, False)):
            rows.append((f"ancestor Users bit {bit:#x}", users(bit), 1, {"ancestor": True}, admitted))
        for label, node, security, kind, options, admitted in (
                [(row[0], self.file) + row[1:] for row in rows] +
                [(f"registry Users bit {bit:#x}", self.key, key_security(Ace(USERS, bit)), 4, {}, admitted)
                 for bit, admitted in ((0x2, False), (0x4, False), (0x20, False), (0x40000, False),
                                       (KEY_READ_MASK, True), (0x10, True), (0x8, True))] +
                [("file object queried as a registry key", self.file, file_security(), 4, {}, False)]):
            with self.subTest(label):
                if admitted:
                    self.assertIsNone(self.check(node, security, kind, **options))
                else:
                    self.refused(self.check, node, security, kind, **options)

    def test_sid_text_and_descriptor_buffers_are_released_on_every_path(self):
        self.assertIsNone(self.check(self.file, file_security()))
        self.assertEqual(self.m.frees, [("sid", ADMINS), ("sid", SYSTEM), ("sid", ADMINS), ("sid", USERS),
                                        ("descriptor", self.file.label)])
        for label, failure in (("SID text conversion fails", ("convert", USERS)),
                               ("SID text release fails", ("free", USERS)),
                               ("descriptor release fails", ("free", "descriptor"))):
            with self.subTest(label):
                self.m.frees.clear()
                self.m.convert_fail.clear()
                self.m.localfree_fail.clear()
                (self.m.convert_fail if failure[0] == "convert" else self.m.localfree_fail).add(failure[1])
                self.refused(self.check, self.file, file_security())
                self.assertEqual(self.m.frees[-1], ("descriptor", self.file.label))
        self.m.frees.clear()
        self.m.convert_fail.clear()
        self.m.localfree_fail.clear()
        self.refused(self.check, self.file, file_security(owner=USERS))
        self.assertEqual(self.m.frees, [("sid", USERS), ("descriptor", self.file.label)])


class TokenTests(_AuthorityDomain):
    """G2-05/G2-06: runtime is the approved medium principal; the issuer is a full elevated administrator."""

    def run_token(self, issuer):
        origin = provisioner._HeldOrigin()
        origin.policy = {"runtime_sid": RUNTIME}
        try:
            provisioner._token(origin, issuer=issuer)
            return True, origin
        except UA as error:
            self.assertEqual(str(error), "TRUST_AUTHORITY_UNAVAILABLE")
            return False, origin

    def test_token_matrix(self):
        rows = [
            (False, "approved medium runtime", {}, True),
            (False, "another user", {"user": OTHER_USER}, False),
            (False, "operator principal", {"user": OPERATOR}, False),
            (False, "elevated runtime", {"elevation": 1}, False),
            (False, "runtime in Administrators", {"admin": True}, False),
            (False, "token cannot be opened", {"open_ok": False}, False),
            (False, "user query fails", {"user_ok": False}, False),
            (False, "elevation query fails", {"elevation_ok": False}, False),
            (True, "full elevated administrator", {"user": OPERATOR, "elevation": 1, "admin": True}, True),
            (True, "filtered administrator token", {"user": OPERATOR, "elevation": 0, "admin": True}, False),
            (True, "elevated non-member", {"user": OPERATOR, "elevation": 1, "admin": False}, False),
            (True, "unknown elevation value", {"user": OPERATOR, "elevation": 2, "admin": True}, False),
            (True, "medium runtime asking for issuer", {}, False),
        ]
        for issuer, label, token, admitted in rows:
            with self.subTest(label):
                self.m.reset()
                vars(self.m.proc_token).update(token)
                ok, origin = self.run_token(issuer)
                self.assertEqual(ok, admitted)
                self.assertEqual(self.calls("OpenProcessToken"), [("OpenProcessToken", 8)])  # TOKEN_QUERY only
                self.assertEqual(len(origin.handles), 0 if token.get("open_ok", True) is False else 1)
                if admitted:
                    self.assertIn(("shell32.dll", 0x800), self.m.loads)
                origin.close()
                self.assertSettled()


class HeldObjectTests(_AuthorityDomain):
    """G2-05: held protected objects are read-only, never followed through reparse points, bounded."""

    def test_hold_opens_read_only_without_following_reparse_points(self):
        file = self.m.release("Python/python.exe")
        folder = self.m.node(CODE_ROOT / "scripts")
        origin = provisioner._HeldOrigin()
        first, identity = origin.hold(file.path)
        second, _ = origin.hold(folder.path, directory=True)
        self.assertEqual(identity, file.identity)
        self.assertEqual(origin.handles, [first, second])
        self.assertEqual(self.calls("CreateFileW"), [
            ("CreateFileW", str(file.path), READ_ACCESS, 1, 3, OPEN_FLAGS),
            ("CreateFileW", str(folder.path), READ_ACCESS, 3, 3, OPEN_FLAGS)])
        origin.close()
        self.assertSettled()

    def test_unsafe_objects_are_refused_after_their_handle_is_retained(self):
        rows = [("reparse attribute", "Python/python.exe", False, {"attributes": 0x400}),
                ("reparse tag", "Python/python.exe", False, {"reparse_tag": 0xA000000C}),
                ("directory opened as a file", "scripts", False, {}),
                ("file opened as a directory", "Python/python.exe", True, {}),
                ("delete pending", "Python/python.exe", False, {"delete_pending": True}),
                ("hard link", "Python/python.exe", False, {"links": 2}),
                ("metadata query fails", "Python/python.exe", False, {"info_fail": True}),
                ("protected file writable by Users", "Python/python.exe", False,
                 {"security": file_security(Ace(USERS, 0x2))})]
        for label, name, directory, fields in rows:
            with self.subTest(label):
                self.m.reset()
                node = self.m.node(CODE_ROOT.joinpath(*name.split("/")))
                vars(node).update(fields)
                origin = provisioner._HeldOrigin()
                self.refused(origin.hold, node.path, directory=directory)
                self.assertEqual(len(origin.handles), 1)  # retained before validation, closed by origin cleanup
                origin.close()
                self.assertSettled()
        self.m.reset()
        self.m.node(CODE_ROOT / "scripts").links = 3  # a directory link count is not a leaf hard link
        origin = provisioner._HeldOrigin()
        origin.hold(CODE_ROOT / "scripts", directory=True)
        self.refused(origin.hold, CODE_ROOT / "absent.py")
        self.assertEqual(len(origin.handles), 1)  # absence leaves nothing to retain
        origin.close()
        self.assertSettled()

    def test_held_owner_count_is_bounded_before_any_open(self):
        origin = provisioner._HeldOrigin()
        origin.handles = [0] * 8192
        self.refused(origin.hold, CODE_ROOT / "Python" / "python.exe")
        self.assertEqual(self.calls("CreateFileW"), [])
        origin.handles = []
        origin.close()
        self.assertSettled()

    def test_reads_are_exact_chunked_and_bounded(self):
        large = self.m.add(r"C:\ReadProbe\large.bin", False, bytes(range(256)) * 4096 + b"tail!")
        small = self.m.add(r"C:\ReadProbe\small.bin", False, b"x" * 11)
        short = self.m.add(r"C:\ReadProbe\short.bin", False, b"y" * 9, short_read=True)
        huge = self.m.add(r"C:\ReadProbe\huge.bin", False, b"", size=256 * 1024 * 1024 + 1)
        origin = provisioner._HeldOrigin()
        handle, _ = origin.hold(large.path)
        self.assertEqual(origin.read(handle), large.data)
        self.assertEqual([event[2] for event in self.calls("ReadFile")], [1024 * 1024, 5])
        for node, cap in ((small, 10), (huge, 256 * 1024 * 1024)):
            with self.subTest(node.label):
                handle, _ = origin.hold(node.path)
                mark = self.mark()
                self.refused(origin.read, handle, cap)
                self.assertEqual(self.calls("ReadFile", mark), [])
        handle, _ = origin.hold(short.path)
        self.refused(origin.read, handle)
        origin.close()
        self.assertSettled()


class ControlledOriginTests(_AuthorityDomain):
    """G2-04/G2-05: each acquisition independently admits policy, principal, interpreter, closure and imports."""

    def test_runtime_acquisition_reads_every_record_fresh_and_measures_the_whole_approved_closure(self):
        origin = provisioner.controlled_origin()
        self.assertEqual(origin.policy, approval_record())
        self.assertEqual(origin.installation, INSTALLATION)
        self.assertEqual(origin.enrollment, self.m.enrollment_record())
        self.assertEqual(origin.files, {name: data for name, data in RELEASE_FILES.items()
                                        if name.startswith(("scripts/", "config/"))})
        self.assertEqual([event[2] for event in self.calls("QueryValueEx")], ["Approval", "Installation", "Enrollment"])
        held = {event[1] for event in self.calls("CreateFileW")}
        self.assertTrue({str(CODE_ROOT.joinpath(*name.split("/"))) for name in RELEASE_FILES} <= held)
        self.assertTrue({str(path) for path in CODE_ROOT.parents} <= held)
        self.assertEqual({event[2] for event in self.calls("CreateFileW")}, {READ_ACCESS})
        self.assertEqual({event[1] for event in self.calls("ReadFile")},
                         {str(CODE_ROOT.joinpath(*name.split("/"))) for name in RELEASE_FILES})
        self.assertEqual(self.calls("walk"), [("walk", str(CODE_ROOT), False)])
        order = [event[2] if event[0] == "QueryValueEx" else event[0] for event in self.m.events
                 if event[0] in ("QueryValueEx", "OpenProcessToken", "walk")]
        self.assertEqual(order, ["Approval", "Installation", "OpenProcessToken", "walk", "Enrollment"])
        self.assertNoAuthorityWrite()
        origin.close()
        self.assertSettled()
        provisioner.controlled_origin().close()
        self.assertEqual([event[2] for event in self.calls("QueryValueEx")],
                         ["Approval", "Installation", "Enrollment"] * 2)
        self.assertEqual(len(self.calls("OpenKey")), 18)
        self.assertSettled()

    def test_absent_enrollment_is_reported_as_none_and_never_synthesized(self):
        self.unenrolled()
        origin = provisioner.controlled_origin()
        self.assertIsNone(origin.enrollment)
        origin.close()
        self.refused(provisioner.enrolled_anchor)
        self.assertSettled()
        self.assertNoAuthorityWrite()

    def test_admission_refusals_close_every_owner_and_report_one_fixed_category(self):
        machine = self.m
        def value(name, data):
            return lambda stack: machine.set_value(name, data)
        def secure(path, security):
            return lambda stack: setattr(machine.node(path), "security", security)
        def release(name, **fields):
            return lambda stack: vars(machine.release(name)).update(fields)
        rows = [
            ("approval absent", lambda stack: machine.values.pop("Approval")),
            ("approval not JSON", value("Approval", "{")),
            ("approval self-signature member", value("Approval", dict(approval_record(), signature="00"))),
            ("approval runtime is SYSTEM", value("Approval", dict(approval_record(), runtime_sid=SYSTEM))),
            ("approval admits a .pth file", value("Approval", approval_record(**{"Python/Lib/evil.pth": "0" * 64}))),
            ("installation absent", lambda stack: machine.values.pop("Installation")),
            ("installation selects another release", value("Installation", dict(INSTALLATION, release_id="b2" * 32))),
            ("installation extra member", value("Installation", dict(INSTALLATION, approved=True))),
            ("authority key writable by Users",
             lambda stack: setattr(machine.keys[LEAF_KEY], "security", key_security(Ace(USERS, 0x2)))),
            ("runtime principal is another user", lambda stack: setattr(machine.proc_token, "user", OTHER_USER)),
            ("runtime token is elevated", lambda stack: setattr(machine.proc_token, "elevation", 1)),
            ("interpreter not isolated", lambda stack: setattr(machine.sys.flags, "isolated", 0)),
            ("site imports enabled", lambda stack: setattr(machine.sys.flags, "no_site", 0)),
            ("bytecode writes enabled", lambda stack: setattr(machine.sys.flags, "dont_write_bytecode", 0)),
            ("interpreter outside the release", lambda stack: setattr(machine.sys, "executable", r"C:\Python312\python.exe")),
            ("provisioner outside the release", lambda stack: stack.enter_context(mock.patch.object(
                provisioner, "__file__", str(REPO / "scripts" / "revenue_guidance_provisioner.py")))),
            ("platform ancestor allows DELETE_CHILD", secure(CODE_ROOT.parents[3], file_security(Ace(USERS, 0x40)))),
            ("releases ancestor owned by runtime", secure(CODE_ROOT.parent, file_security(owner=RUNTIME))),
            ("release root owned by TrustedInstaller", secure(CODE_ROOT, file_security(owner=TRUSTED_INSTALLER))),
            ("approved file writable by Users", release("scripts/revenue_guidance_storage.py",
                                                        security=file_security(Ace(USERS, 0x2)))),
            ("approved file owned by runtime", release(REG, security=file_security(owner=RUNTIME))),
            ("unapproved sitecustomize beside the code",
             lambda stack: machine.add(CODE_ROOT / "scripts" / "sitecustomize.py", False, b"import os")),
            ("approved host module missing",
             lambda stack: machine.nodes.pop(CODE_ROOT / "scripts" / "revenue_guidance_host.py")),
            ("approved bytes replaced", release("scripts/revenue_guidance_windows.py", data=b"replaced")),
            ("hard-linked interpreter DLL", release("Python/python312.dll", links=2)),
            ("reparse-point package directory",
             lambda stack: setattr(machine.node(CODE_ROOT / "scripts" / "adapters"), "attributes", 0x400)),
            ("interpreter larger than 256 MiB", release("Python/python.exe", size=256 * 1024 * 1024 + 1)),
            ("relative import path", lambda stack: machine.sys.path.append("")),
            ("import path outside the release", lambda stack: machine.sys.path.append(r"C:\ProgramData\runtime\site-packages")),
            ("module loaded from outside the release", lambda stack: machine.sys.modules.__setitem__(
                "sitecustomize", SimpleNamespace(__file__=r"C:\ProgramData\runtime\sitecustomize.py"))),
            ("module with a relative origin",
             lambda stack: machine.sys.modules.__setitem__("relative", SimpleNamespace(__file__="relative.py"))),
            ("enrollment not REG_SZ", lambda stack: machine.set_value(
                "Enrollment", machine.enrollment_record(), winreg.REG_EXPAND_SZ)),
            ("enrollment duplicate member", value("Enrollment", '{"schema": 1, "schema": 2}')),
        ]
        for label, mutate in rows:
            with self.subTest(label), ExitStack() as stack:
                machine.reset()
                mutate(stack)
                error = self.refused(provisioner.controlled_origin)
                self.assertIsNone(error.__cause__)
                self.assertTrue(error.__suppress_context__)  # no raw OS/parser detail escapes
                self.assertSettled()
                self.assertNoAuthorityWrite()

    def test_interrupt_during_measurement_is_cleaned_up_and_refused(self):
        for raised in (SystemExit(3), KeyboardInterrupt()):
            with self.subTest(type(raised).__name__):
                self.m.reset()
                self.m.read_raise[str(CODE_ROOT / "scripts" / "revenue_guidance_storage.py")] = raised
                error = self.refused(provisioner.controlled_origin)
                self.assertTrue(error.__suppress_context__)
                self.assertSettled()


class UnresolvedOriginCustodyTests(_AuthorityDomain):
    """G2-14: unconfirmed origin cleanup keeps the exact owner graph and vetoes authority without retry."""

    def test_failed_handle_close_roots_the_exact_origin_graph_and_vetoes_new_authority(self):
        self.m.release("scripts/revenue_guidance_windows.py").data = b"replaced"
        self.m.close_fail.add(str(CODE_ROOT))
        self.refused(provisioner.controlled_origin)
        retained = provisioner._unsettled_origin
        self.assertIs(type(retained), provisioner._HeldOrigin)
        self.assertTrue(retained.closed and retained.close_failed)
        self.assertIsNone(retained._custody_next_origin)
        self.assertEqual(provisioner.origin_custody_status(), "UNRESOLVED")
        self.assertEqual(windows.native_custody_status(), "UNRESOLVED")  # joined lifetime seam
        retained_labels = sorted([str(CODE_ROOT), "<token>"] + [str(path) for path in CODE_ROOT.parents])
        self.assertEqual(self.m.live(), retained_labels)
        closes = [event[1] for event in self.calls("CloseHandle")]
        self.assertEqual(closes.count(str(CODE_ROOT)), 1)  # attempted once, never retried
        self.assertEqual(set(closes) & (set(retained_labels) - {str(CODE_ROOT)}), set())
        self.assertEqual(len(self.calls("RegCloseKey")), 6)  # keys closed before any handle
        mark = self.mark()
        anchor = self.m.anchor()
        for call in (provisioner.controlled_origin, provisioner.enrolled_anchor, provisioner.require_issuer,
                     provisioner.acquire_live_owner, lambda: provisioner.require_anchor(anchor), retained.close):
            self.refused(call)
        self.assertEqual(self.m.events[mark:], [])
        self.assertIs(provisioner._unsettled_origin, retained)

    def test_interrupted_registry_close_roots_the_origin_before_any_handle_close(self):
        self.m.release("scripts/revenue_guidance_windows.py").data = b"replaced"
        self.m.key_close_raise[LEAF_KEY] = KeyboardInterrupt()
        with self.assertRaises(KeyboardInterrupt):
            provisioner.controlled_origin()
        self.assertEqual(provisioner.origin_custody_status(), "UNRESOLVED")
        self.assertEqual(self.calls("CloseHandle"), [])
        self.assertEqual(len(self.calls("RegCloseKey")), 1)
        self.assertIn("<token>", self.m.live())
        self.assertEqual(windows.native_custody_status(), "UNRESOLVED")

    def test_existing_uncertainty_vetoes_cleanup_of_a_settled_origin_and_links_it(self):
        origin = provisioner.controlled_origin()
        earlier = object()
        provisioner._unsettled_origin = earlier  # restored by the base patch
        mark = self.mark()
        self.refused(origin.close)
        self.assertIs(provisioner._unsettled_origin, origin)
        self.assertIs(origin._custody_next_origin, earlier)
        self.assertEqual(self.m.events[mark:], [])
        self.refused(origin.close)
        self.assertEqual(self.m.events[mark:], [])

    def test_settled_origin_hold_returns_without_waiting(self):
        wait = mock.Mock(side_effect=AssertionError("waited while settled"))
        with mock.patch.object(provisioner, "_origin_hold_event", SimpleNamespace(wait=wait)):
            self.assertIsNone(provisioner.hold_unresolved_origin_custody())
        wait.assert_not_called()

    def test_unresolved_origin_hold_survives_interrupts_without_retry_or_exit(self):
        event = InterruptingEvent([SystemExit(0), KeyboardInterrupt(), GeneratorExit()])
        provisioner._unsettled_origin = object()  # restored by the base patch
        with mock.patch.object(provisioner, "_origin_hold_event", event):
            thread = threading.Thread(target=provisioner.hold_unresolved_origin_custody, daemon=True,
                                      name="g2-14-parked-origin-hold")
            thread.start()
            self.assertTrue(event.parked.wait(10))
        self.assertTrue(thread.is_alive())
        self.assertEqual(event.calls, 4)
        self.assertEqual(self.m.events, [])

    def test_native_lifetime_hold_joins_unresolved_origin_custody(self):
        provisioner._unsettled_origin = object()  # restored by the base patch
        self.assertEqual(windows.native_custody_status(), "UNRESOLVED")
        event = InterruptingEvent([KeyboardInterrupt(), SystemExit(2)])
        with mock.patch.object(windows, "_custody_hold_event", event):
            thread = threading.Thread(target=windows.hold_unresolved_native_custody, daemon=True,
                                      name="g2-14-parked-native-hold")
            thread.start()
            self.assertTrue(event.parked.wait(10))
        self.assertTrue(thread.is_alive())
        self.assertEqual(event.calls, 3)
        self.assertEqual(self.m.events, [])


class AnchorAdmissionTests(_AuthorityDomain):
    """G2-04/G2-06: require_anchor compares the whole candidate with a freshly measured enrollment."""

    def test_require_anchor_returns_a_fresh_copy_of_only_the_exact_enrolled_anchor(self):
        anchor = self.m.anchor()
        first = provisioner.require_anchor(anchor)
        self.assertEqual(first, anchor)
        self.assertIsNot(first, anchor)
        self.assertSettled()
        self.assertEqual(provisioner.require_anchor(anchor), anchor)
        self.assertEqual([event[2] for event in self.calls("QueryValueEx")],
                         ["Approval", "Installation", "Enrollment"] * 2)
        self.assertEqual(provisioner.enrolled_anchor(), anchor)
        self.assertSettled()
        self.assertNoAuthorityWrite()

    def test_any_candidate_field_difference_is_refused(self):
        anchor = self.m.anchor()
        other = storage.ObjectIdentity(SERIAL, b"\x77" * 16)
        rows = {
            "schema_version": "guidance-provider-storage-v1", "bootstrap_id": "enroll-" + "6" * 32,
            "volume_guid": OTHER_GUID, "volume_root_identity": other,
            "root_components": anchor.root_components[:-1] + ((BOOT, other),),
            "coordination_identity": other, "journal_identity": other, "journal_format_version": 2,
            "state_required": False, "control_identity": other, "b1_identity": other,
            "input_digests": tuple((name, "0" * 64 if name == "config.json" else digest)
                                   for name, digest in anchor.input_digests),
        }
        for field, value in rows.items():
            with self.subTest(field):
                self.m.reset()
                self.refused(provisioner.require_anchor, dataclasses.replace(anchor, **{field: value}))
                self.assertSettled()

    def test_each_acquisition_reads_its_own_record(self):
        anchor = self.m.anchor()
        provisioner.require_anchor(anchor)
        stored = self.m.values.pop("Enrollment")
        self.refused(provisioner.require_anchor, anchor)
        self.m.values["Enrollment"] = stored
        self.assertEqual(provisioner.require_anchor(anchor), anchor)
        self.assertSettled()

    def test_enrolled_layout_refusals(self):
        machine = self.m
        def record(mutator):
            def apply():
                value = machine.enrollment_record()
                mutator(value)
                machine.set_value("Enrollment", value)
            return apply
        def secure(path, security):
            return lambda: setattr(machine.node(path), "security", security)
        rows = [
            ("record extra member", record(lambda r: r.update(approved=True)), UA),
            ("record schema v2", record(lambda r: r.update(schema="guidance-protected-enrollment-v2")), UA),
            ("record for another release", record(lambda r: r.update(release_id="b2" * 32)), UA),
            ("initial revision malformed", record(lambda r: r.update(initial_revision="gir1:" + "C" * 64)), UA),
            ("anchor file id not hex", record(lambda r: r["anchor"]["journal_identity"].update(file_id="zz" * 16)), UA),
            ("anchor volume guid malformed", record(lambda r: r["anchor"].update(volume_guid="C:")),
             storage.MissingTrustedAnchorError),
            ("anchor outside the fixed data base",
             record(lambda r: r["anchor"]["root_components"][1].__setitem__(0, "OtherGuidance")), UA),
            # Paths resolve case-insensitively, so only the exact-name check refuses another spelling of a held directory.
            ("ProgramData component in another case",
             record(lambda r: r["anchor"]["root_components"][0].__setitem__(0, "PROGRAMDATA")), UA),
            ("data base component in another case",
             record(lambda r: r["anchor"]["root_components"][1].__setitem__(0, "investorintelligenceguidance")), UA),
            ("bootstrap component in another case",
             record(lambda r: r["anchor"]["root_components"][2].__setitem__(0, BOOT.upper())), UA),
            ("anchor input digest not bound to the approval",
             record(lambda r: r["anchor"]["input_digests"].update({"config.json": "0" * 64})), UA),
            ("mounted volume differs", lambda: setattr(machine, "volume", "\\\\?\\Volume" + OTHER_GUID + "\\"), UA),
            ("volume root replaced", lambda: machine.replace_identity("C:\\"), UA),
            ("ProgramData replaced", lambda: machine.replace_identity("C:\\ProgramData"), UA),
            ("enrolled root replaced between holds",
             lambda: setattr(machine.node(DATA_ROOT), "later_identity", (SERIAL, b"\x55" * 16)), UA),
            ("extra entry in the enrolled root", lambda: machine.add(DATA_ROOT / "b1-old", True), UA),
            ("journal missing from control", lambda: machine.nodes.pop(CONTROL / "journal.dat"), UA),
            ("extra control file", lambda: machine.add(CONTROL / "debug.log", False, b"x"), UA),
            ("control directory replaced", lambda: machine.replace_identity(CONTROL), UA),
            ("b1 directory replaced", lambda: machine.replace_identity(DATA_ROOT / "b1"), UA),
            ("b1 grants runtime DELETE", secure(DATA_ROOT / "b1", file_security(Ace(RUNTIME, RUNTIME_B1_DIRECTORY | 0x10000))), UA),
            ("b1 grants Users file creation", secure(DATA_ROOT / "b1", file_security(
                Ace(RUNTIME, RUNTIME_B1_DIRECTORY), Ace(USERS, 0x2))), UA),
            ("control input bytes changed", lambda: setattr(machine.node(CONTROL / "registry.json"), "data", b"{}"), UA),
            ("control input writable by runtime", secure(CONTROL / "approval.json", file_security(Ace(RUNTIME, 0x2))), UA),
            ("coordination lock replaced", lambda: machine.replace_identity(CONTROL / "coordination.lock"), UA),
            ("journal grants runtime WRITE_DAC", secure(CONTROL / "journal.dat", file_security(
                Ace(RUNTIME, RUNTIME_CONTROL | 0x40000))), UA),
            ("hard-linked journal", lambda: setattr(machine.node(CONTROL / "journal.dat"), "links", 2), UA),
            ("data base ancestor allows DELETE_CHILD", secure(provisioner.DATA_BASE, file_security(Ace(USERS, 0x40))), UA),
        ]
        for label, mutate, error in rows:
            with self.subTest(label):
                machine.reset()
                mutate()
                with self.assertRaises(error):
                    provisioner.enrolled_anchor()
                self.assertSettled()

    def test_enrolled_admission_records_exactly_the_two_p2_conflict_owners(self):
        origin = provisioner.controlled_origin()
        self.assertEqual(provisioner._enrolled(origin), self.m.anchor())
        rows = origin._p2_admission_conflicts
        self.assertEqual([row["role"] for row in rows], ["coordination.lock", "journal.dat"])
        self.assertTrue(all(not row["attempted"] and not row["closed"] and origin.handles.count(row["handle"]) == 1
                            for row in rows))
        self.assertEqual(origin.handles[-1], rows[1]["handle"])
        self.assertEqual(self.m.handles[rows[1]["handle"]].label, str(CONTROL / "journal.dat"))
        origin.close()
        self.assertSettled()


class LeaseAdmissionTests(_AuthorityDomain):
    """G2-06: normal leases and the issuer context admit real authority before custody, clock and budget."""

    def record_custody(self):
        machine = self.m
        real = storage.NativeStorageLease._initialize_custody
        def initialize(lease, limits):
            machine.events.append(("custody", limits.profile, tuple(machine.live())))
            return real(lease, limits)
        def start(lease):
            machine.events.append(("start", type(lease).__name__))
        self.enterContext(mock.patch.object(storage.NativeStorageLease, "_initialize_custody", initialize))
        self.enterContext(mock.patch.object(storage.NativeStorageLease, "_start_acquisition", start))

    def test_normal_lease_admits_the_candidate_through_require_anchor_before_custody(self):
        self.record_custody()
        anchor = self.m.anchor()
        lease = storage.NativeStorageLease(anchor, storage.NativeLimits())
        self.assertEqual(lease.anchor, anchor)
        self.assertEqual(self.calls("custody"), [("custody", "legacy", ())])  # origin already disposed
        names = [event[0] for event in self.m.events]
        self.assertLess(names.index("QueryValueEx"), names.index("custody"))
        self.assertEqual(names[-1], "start")
        self.assertSettled()

    def test_normal_lease_refusal_precedes_custody_clock_and_budget(self):
        self.record_custody()
        budget = self.enterContext(mock.patch.object(
            storage, "_remaining_b1_limits", side_effect=AssertionError("budget consulted before authority")))
        machine = self.m
        rows = [("not enrolled", lambda: machine.values.pop("Enrollment")),
                ("enrolled journal replaced", lambda: machine.replace_identity(CONTROL / "journal.dat")),
                ("elevated runtime token", lambda: setattr(machine.proc_token, "elevation", 1)),
                ("unresolved origin custody", lambda: setattr(provisioner, "_unsettled_origin", object()))]
        for label, mutate in rows:
            with self.subTest(label):
                machine.reset()
                provisioner._unsettled_origin = None
                mutate()
                with self.assertRaises(storage.MissingTrustedAnchorError) as caught:
                    storage.NativeStorageLease(machine.anchor(), storage.NativeLimits.b1(1000), parent_deadline=None)
                self.assertEqual(str(caught.exception), "TRUST_AUTHORITY_UNAVAILABLE")
                self.assertIsNone(caught.exception.__cause__)
                self.assertEqual(self.calls("custody") + self.calls("start"), [])
        provisioner._unsettled_origin = None
        budget.assert_not_called()

    def test_b1_budget_is_consulted_only_after_authority_admits(self):
        self.record_custody()
        with self.assertRaises(storage.BudgetExceededError):
            storage.NativeStorageLease(self.m.anchor(), storage.NativeLimits.b1(1000), parent_deadline=None)
        self.assertEqual(self.calls("custody"), [])
        self.assertEqual([event[2] for event in self.calls("QueryValueEx")], ["Approval", "Installation", "Enrollment"])
        self.assertSettled()
        lease = storage.NativeStorageLease(self.m.anchor(), storage.NativeLimits.b1(1000),
                                           parent_deadline=time.monotonic() + 30)
        self.assertEqual(lease.limits.profile, "b1")
        self.assertLessEqual(lease.limits.max_elapsed_ms, 1000)

    def test_candidate_type_and_limits_are_checked_before_authority(self):
        anchor = self.m.anchor()
        with self.assertRaises(storage.MissingTrustedAnchorError):
            storage.NativeStorageLease(SimpleNamespace(**vars(anchor)), storage.NativeLimits())
        with self.assertRaises(storage.MissingTrustedAnchorError):
            storage.NativeStorageLease(dataclasses.replace(anchor, volume_guid="C:"), storage.NativeLimits())
        with self.assertRaises(TypeError):
            storage.NativeStorageLease(anchor, {"profile": "legacy"})
        self.assertEqual(self.m.events, [])

    def test_missing_authority_function_is_unavailable_not_a_registration_hook(self):
        anchor = self.m.anchor()
        with sys_module("revenue_guidance_provisioner", SimpleNamespace(CONTROL_INPUTS=provisioner.CONTROL_INPUTS)):
            with self.assertRaises(storage.MissingTrustedAnchorError):
                storage.NativeStorageLease(anchor, storage.NativeLimits())
        self.assertIs(sys.modules["revenue_guidance_provisioner"], provisioner)
        self.assertEqual(self.m.events, [])

    def issuer_inputs(self, error=None):
        machine, seen = self.m, []
        def inputs(origin):
            machine.events.append(("inputs",))
            seen.append(origin)
            if error is not None:
                raise error
            return {"probe": b"captured"}
        self.enterContext(mock.patch.object(enrollment, "validate_initial_inputs", inputs))
        return seen

    def test_issuer_context_admits_privileged_origin_before_inputs_volume_and_custody(self):
        self.as_issuer()
        self.unenrolled()
        self.record_custody()
        seen = self.issuer_inputs()
        context = storage.NativeIssuerContext(5000, parent_deadline=time.monotonic() + 30)
        origin = context._issuer_origin
        self.assertEqual(seen, [origin])
        self.assertIs(type(origin), provisioner._HeldOrigin)
        self.assertFalse(origin.closed)
        self.assertIsNone(origin.enrollment)
        self.assertEqual(context._initial_inputs, {"probe": b"captured"})
        self.assertEqual(context.anchor.volume_guid, GUID)
        self.assertRegex(context._new_root_name, r"\Aenroll-[0-9a-f]{32}\Z")
        self.assertEqual(context.anchor.bootstrap_id, context._new_root_name)
        self.assertEqual(context.limits.profile, "b1")
        self.assertLessEqual(context.limits.max_elapsed_ms, 5000)
        names = [event[0] for event in self.m.events]
        data_base = next(index for index, event in enumerate(self.m.events)
                         if event[0] == "CreateFileW" and event[1] == str(provisioner.DATA_BASE))
        self.assertLess(names.index("OpenProcessToken"), data_base)
        self.assertLess(data_base, names.index("inputs"))
        self.assertLess(names.index("inputs"), names.index("GetVolumeNameForVolumeMountPointW"))
        self.assertLess(names.index("GetVolumeNameForVolumeMountPointW"), names.index("custody"))
        self.assertEqual(names[-1], "start")
        self.assertIn(str(provisioner.DATA_BASE), self.m.live())
        origin.close()
        self.assertSettled()

    def test_issuer_context_refusals(self):
        self.record_custody()
        machine = self.m
        def issuer(**token):
            def apply():
                self.as_issuer()
                vars(machine.proc_token).update(token)
            return apply
        before_inputs = [
            ("medium runtime token", lambda: None, True),
            ("elevated without Administrators membership", issuer(admin=False), True),
            ("filtered administrator token", issuer(elevation=0), True),
            ("existing enrollment is never repaired", issuer(), False),
            ("data base absent", lambda: (self.as_issuer(), machine.nodes.pop(provisioner.DATA_BASE)), True),
            ("data base writable by Users", lambda: (self.as_issuer(), setattr(
                machine.node(provisioner.DATA_BASE), "security", file_security(Ace(USERS, 0x2)))), True),
        ]
        seen = self.issuer_inputs()
        for label, mutate, unenrolled in before_inputs:
            with self.subTest(label):
                machine.reset()
                if unenrolled:
                    self.unenrolled()
                mutate()
                self.refused(storage.NativeIssuerContext, 5000, parent_deadline=time.monotonic() + 30)
                self.assertEqual(seen, [])
                self.assertEqual(self.calls("inputs") + self.calls("custody"), [])
                self.assertSettled()
                self.assertNoAuthorityWrite()

    def test_issuer_context_failures_after_admission_dispose_the_settled_origin(self):
        self.record_custody()
        machine = self.m
        rows = [("baseline invalid", ValueError("ENROLLMENT_BASELINE_INVALID"), lambda: None, ValueError),
                ("volume name unavailable", None, lambda: setattr(machine, "volume_ok", False),
                 storage.MissingTrustedAnchorError),
                ("volume path is not a GUID", None, lambda: setattr(machine, "volume", "\\\\?\\Volume{not-a-guid}\\"),
                 storage.MissingTrustedAnchorError)]
        for label, inputs_error, mutate, error in rows:
            with self.subTest(label), ExitStack() as stack:
                machine.reset()
                self.as_issuer()
                self.unenrolled()
                mutate()
                stack.enter_context(mock.patch.object(enrollment, "validate_initial_inputs",
                                                      mock.Mock(side_effect=inputs_error, return_value={})))
                with self.assertRaises(error):
                    storage.NativeIssuerContext(5000, parent_deadline=time.monotonic() + 30)
                self.assertEqual(self.calls("custody"), [])
                self.assertSettled()

    def test_issuer_failure_with_unresolved_native_custody_keeps_the_origin(self):
        self.as_issuer()
        self.unenrolled()
        self.enterContext(mock.patch.object(enrollment, "validate_initial_inputs",
                                            side_effect=ValueError("ENROLLMENT_BASELINE_INVALID")))
        self.enterContext(mock.patch.object(windows, "context_custody_unresolved", return_value=True))
        with self.assertRaises(ValueError):
            storage.NativeIssuerContext(5000, parent_deadline=time.monotonic() + 30)
        self.assertEqual(self.calls("CloseHandle") + self.calls("RegCloseKey"), [])
        self.assertIn(str(provisioner.DATA_BASE), self.m.live())
        self.assertIn("<token>", self.m.live())

    def issuer_origin(self):
        self.as_issuer()
        self.unenrolled()
        return provisioner.require_issuer()

    def test_guarded_issuer_io_reconsults_policy_principal_and_protected_entry_bytes(self):
        origin = self.issuer_origin()
        held = self.m.live()
        mark = self.mark()
        provisioner.require_live_issuer(origin)
        self.assertEqual([event[2] for event in self.calls("QueryValueEx", mark)], ["Approval"])
        self.assertEqual(len(self.calls("OpenProcessToken", mark)), 1)
        self.assertEqual({event[1] for event in self.calls("ReadFile", mark)},
                         {str(CODE_ROOT / "Python" / "python.exe"),
                          str(CODE_ROOT / "scripts" / "revenue_guidance_bootstrap.py")})
        self.assertEqual(self.m.live(), held)  # the fresh consultation origin is disposed
        self.assertFalse(origin.closed)
        origin.close()
        self.assertSettled()

    def test_live_issuer_refusals(self):
        machine = self.m
        class Subclass(provisioner._HeldOrigin):
            pass
        def copy_into(cls):
            def build(origin):
                forged = cls.__new__(cls)
                forged.__dict__.update(vars(origin))
                return forged
            return build
        def medium_token():
            machine.proc_token.user, machine.proc_token.elevation, machine.proc_token.admin = RUNTIME, 0, False
        rows = [
            ("duck-typed origin", lambda origin: SimpleNamespace(**vars(origin)), None, False),
            ("subclass instance", copy_into(Subclass), None, False),
            ("closed origin", lambda origin: (origin.close(), origin)[1], None, False),
            ("manufactured fields under a medium token", copy_into(provisioner._HeldOrigin), medium_token, True),
            ("approval changed since acquisition", lambda origin: origin, lambda: machine.set_value(
                "Approval", approval_record(**{"config/added.json": "0" * 64})), True),
            ("bootstrap bytes replaced", lambda origin: origin,
             lambda: setattr(machine.release("scripts/revenue_guidance_bootstrap.py"), "data", b"replaced"), True),
            ("hard-linked interpreter", lambda origin: origin,
             lambda: setattr(machine.release("Python/python.exe"), "links", 2), True),
            ("interpreter not isolated", lambda origin: origin, lambda: setattr(machine.sys.flags, "isolated", 0), True),
            ("foreign module loaded", lambda origin: origin, lambda: machine.sys.modules.__setitem__(
                "foreign", SimpleNamespace(__file__=r"C:\ProgramData\runtime\foreign.py")), True),
        ]
        for label, choose, mutate, consults in rows:
            with self.subTest(label):
                machine.reset()
                candidate = choose(self.issuer_origin())
                if mutate is not None:
                    mutate()
                live = machine.live()
                mark = self.mark()
                self.refused(provisioner.require_live_issuer, candidate)
                if consults:
                    self.assertTrue(self.calls("OpenKey", mark))
                else:
                    self.assertEqual(machine.events[mark:], [])
                self.assertEqual(machine.live(), live)
                self.assertIsNone(provisioner._unsettled_origin)


class LiveOwnerTests(_AuthorityDomain):
    """G2-14: the enrolled-domain interlock is retained exactly; uncertain creation/release roots the origin."""

    def live_owner_name(self):
        anchor = self.m.anchor()
        domain = {"volume": GUID, "bootstrap": BOOT, "root": anchor.root_components[-1][1].file_id.hex(),
                  "coordination": anchor.coordination_identity.file_id.hex()}
        return "Global\\InvestorIntelligenceGuidanceLiveOwner-" + hashlib.sha256(
            json.dumps(domain, sort_keys=True, separators=(",", ":")).encode()).hexdigest()

    def after_mutex(self):
        index = next(position for position, event in enumerate(self.m.events) if event[0] == "CreateMutexW")
        return self.m.events[index + 1:]

    def test_live_owner_is_named_from_the_enrolled_domain_and_retires_only_admission_reads(self):
        origin = provisioner.acquire_live_owner()
        self.assertEqual(self.calls("CreateMutexW"), [("CreateMutexW", None, True, self.live_owner_name())])
        self.assertEqual(self.m.mutex.rooted, [origin])  # rooted before submission, unrooted once classified
        self.assertEqual(self.after_mutex(), [("CloseHandle", str(CONTROL / "coordination.lock")),
                                              ("CloseHandle", str(CONTROL / "journal.dat"))])
        self.assertTrue(origin.live_owner_owned)
        self.assertEqual(origin._p2_admission_phase, "CONFIRMED")
        self.assertEqual([(row["attempted"], row["closed"]) for row in origin._p2_admission_conflicts],
                         [(True, True), (True, True)])
        self.assertIsNone(provisioner._unsettled_origin)
        self.assertIn("<mutex>", self.m.live())
        mark = self.mark()
        origin.close()
        tail = self.m.events[mark:]
        self.assertEqual([event[0] for event in tail[:9]], ["RegCloseKey"] * 9)
        self.assertEqual(tail[-2:], [("ReleaseMutex", "<mutex>"), ("CloseHandle", "<mutex>")])  # released LAST
        self.assertNotIn(("CloseHandle", str(CONTROL / "journal.dat")), tail)  # never closed twice
        self.assertSettled()

    def test_existing_or_failed_interlock_is_refused_and_settled(self):
        for outcome, mutex_closed in (("existing", True), ("failed", False)):
            with self.subTest(outcome):
                self.m.reset()
                self.m.mutex.outcome = outcome
                self.refused(provisioner.acquire_live_owner)
                tail = self.after_mutex()
                self.assertNotIn("ReleaseMutex", [event[0] for event in tail])
                self.assertEqual(tail[-1] == ("CloseHandle", "<mutex>"), mutex_closed)
                self.assertSettled()

    def test_interrupted_creation_retains_the_origin_without_cleanup(self):
        self.m.mutex.raised = KeyboardInterrupt()
        self.refused(provisioner.acquire_live_owner)
        self.assertIs(type(provisioner._unsettled_origin), provisioner._HeldOrigin)
        self.assertEqual(self.m.mutex.rooted, [provisioner._unsettled_origin])  # already rooted when submitted
        self.assertEqual(provisioner.origin_custody_status(), "UNRESOLVED")
        self.assertEqual(self.after_mutex(), [])
        self.assertIn("<token>", self.m.live())

    def test_failed_admission_read_release_retains_the_same_owned_interlock(self):
        self.m.close_fail.add(str(CONTROL / "coordination.lock"))
        self.refused(provisioner.acquire_live_owner)
        retained = provisioner._unsettled_origin
        self.assertEqual(retained._p2_admission_phase, "RELEASING")
        self.assertEqual([(row["attempted"], row["closed"]) for row in retained._p2_admission_conflicts],
                         [(True, False), (False, False)])
        self.assertEqual(self.after_mutex(), [("CloseHandle", str(CONTROL / "coordination.lock"))])
        self.assertTrue(retained.live_owner_owned)
        self.assertIn("<mutex>", self.m.live())
        self.assertEqual(provisioner.origin_custody_status(), "UNRESOLVED")

    def admitted_origin(self):
        origin = provisioner.controlled_origin()
        provisioner._enrolled(origin)
        origin.live_owner_handle = self.m._open(self.m.mutex_node)
        origin.live_owner_owned = True
        return origin

    def test_release_preconditions_refuse_without_closing(self):
        def conflict(index, **fields):
            return lambda origin: origin._p2_admission_conflicts[index].update(fields)
        rows = [
            ("already released", lambda origin: setattr(origin, "_p2_admission_phase", "CONFIRMED")),
            ("interlock not owned", lambda origin: setattr(origin, "live_owner_owned", False)),
            ("no interlock", lambda origin: setattr(origin, "live_owner_handle", None)),
            ("one conflict", lambda origin: origin._p2_admission_conflicts.pop()),
            ("three conflicts", lambda origin: origin._p2_admission_conflicts.append(
                dict(origin._p2_admission_conflicts[0]))),
            ("role renamed", conflict(0, role="queue.json")),
            ("same handle twice", lambda origin: origin._p2_admission_conflicts[1].update(
                handle=origin._p2_admission_conflicts[0]["handle"])),
            ("already attempted", conflict(0, attempted=True)),
            ("already closed", conflict(1, closed=True)),
            ("handle not held", lambda origin: origin.handles.remove(origin._p2_admission_conflicts[0]["handle"])),
            ("handle held twice", lambda origin: origin.handles.append(origin._p2_admission_conflicts[1]["handle"])),
            ("origin closed", lambda origin: setattr(origin, "closed", True)),
        ]
        for label, mutate in rows:
            with self.subTest(label):
                self.m.reset()
                origin = self.admitted_origin()
                mutate(origin)
                phase = origin._p2_admission_phase
                mark = self.mark()
                self.refused(origin.release_p2_admission_conflicts)
                self.assertEqual(self.m.events[mark:], [])
                self.assertIsNone(provisioner._unsettled_origin)
                self.assertEqual(origin._p2_admission_phase, phase)

    def test_retain_live_owner_custody_is_failure_only_rooting(self):
        provisioner.retain_live_owner_custody(None)
        plain = provisioner.controlled_origin()
        self.refused(provisioner.retain_live_owner_custody, plain)
        self.refused(provisioner.retain_live_owner_custody, SimpleNamespace(live_owner_handle=1))
        self.assertIsNone(provisioner._unsettled_origin)
        plain.close()
        owner = provisioner.acquire_live_owner()
        mark = self.mark()
        provisioner.retain_live_owner_custody(owner)
        self.assertIs(provisioner._unsettled_origin, owner)
        self.assertIsNone(owner._custody_next_origin)
        provisioner.retain_live_owner_custody(owner)
        self.assertIsNone(owner._custody_next_origin)
        self.assertEqual(provisioner.origin_custody_status(), "UNRESOLVED")
        later = provisioner._HeldOrigin.__new__(provisioner._HeldOrigin)
        later.live_owner_handle = 1
        provisioner.retain_live_owner_custody(later)
        self.assertIs(provisioner._unsettled_origin, later)
        self.assertIs(later._custody_next_origin, owner)
        self.assertEqual(self.m.events[mark:], [])
        self.assertIn("<mutex>", self.m.live())


class PublishEnrollmentTests(_AuthorityDomain):
    """G2-09: Enrollment is published LAST, after a fresh issuer re-measurement and journal check, then read back."""

    def setUp(self):
        super().setUp()
        self.as_issuer()
        self.unenrolled()

    def test_enrollment_is_published_last_after_fresh_remeasurement_and_reads_back(self):
        origin = provisioner.require_issuer()
        held = self.m.live()
        anchor = self.m.anchor()
        mark = self.mark()
        provisioner.publish_enrollment(origin, anchor, REV)
        tail = self.m.events[mark:]
        record = {"schema": "guidance-protected-enrollment-v1", "release_id": RELEASE,
                  "anchor": provisioner.anchor_to_data(anchor), "initial_revision": REV}
        text = json.dumps(record, sort_keys=True, separators=(",", ":"), allow_nan=False)
        self.assertEqual(self.m.written, [("Enrollment", text)])
        self.assertEqual(self.m.values["Enrollment"], (text, winreg.REG_SZ))
        writable = [event for event in tail if event[0] == "OpenKey" and event[4] & winreg.KEY_SET_VALUE]
        self.assertEqual(writable, [("OpenKey", winreg.HKEY_LOCAL_MACHINE, LEAF_KEY, 0,
                                     winreg.KEY_READ | winreg.KEY_SET_VALUE | winreg.KEY_WOW64_64KEY)])
        names = [event[0] for event in tail]
        written = names.index("SetValueEx")
        self.assertEqual(tail[written:written + 3], [("SetValueEx", LEAF_KEY, "Enrollment", 0, winreg.REG_SZ),
                                                     ("FlushKey", LEAF_KEY), ("QueryValueEx", LEAF_KEY, "Enrollment")])
        journal_read = max(index for index, event in enumerate(tail)
                           if event[0] == "ReadFile" and event[1] == str(CONTROL / "journal.dat"))
        self.assertLess(tail.index(writable[0]), journal_read)
        self.assertLess(journal_read, written)
        remeasured = {event[1] for event in tail[:written] if event[0] == "CreateFileW"}
        self.assertTrue({str(CONTROL / name) for name in provisioner.CONTROL_INPUTS | {"coordination.lock", "journal.dat"}}
                        <= remeasured)
        self.assertTrue(all(event[0] in ("RegCloseKey", "CloseHandle") for event in tail[written + 3:]))
        self.assertEqual(self.m.live(), held)
        self.assertFalse(origin.closed)
        origin.close()
        self.assertSettled()
        machine = self.m
        machine.proc_token.user, machine.proc_token.elevation, machine.proc_token.admin = RUNTIME, 0, False
        self.assertEqual(provisioner.require_anchor(anchor), anchor)  # the published record is the admitted authority

    def test_refusals_publish_nothing_and_dispose_the_fresh_origin(self):
        machine = self.m
        def journal(data):
            return lambda origin: setattr(machine.node(CONTROL / "journal.dat"), "data", data)
        state = journal_state()
        intent = {"Id": "a" * 32, "BaseInputRevision": REV, "ObservedAtBeginRevision": REV, "PriorPendingRevision": None}
        rows = [
            ("issuer origin already closed", lambda origin: origin.close(), REV, False),
            ("enrollment already published", lambda origin: machine.set_value("Enrollment", machine.enrollment_record()),
             REV, True),
            ("policy changed since the issuer origin",
             lambda origin: setattr(origin, "policy", dict(origin.policy, runtime_sid=OTHER_USER)), REV, True),
            ("medium token at publication", lambda origin: setattr(machine.proc_token, "elevation", 0), REV, True),
            ("authority key writable by Users",
             lambda origin: setattr(machine.keys[LEAF_KEY], "security", key_security(Ace(USERS, 0x2))), REV, True),
            ("slot magic not yet written", journal(journal_bytes(magic=INVALID_MAGIC)), REV, True),
            ("only the first slot written", journal(p2.slot(0, state, bootstrap=BOOT) +
                                                    p2.slot(1, state, bootstrap=BOOT, magic=INVALID_MAGIC)), REV, True),
            ("pending rebuild cleared", journal(journal_bytes(state=journal_state(pending=None))), REV, True),
            ("intent present", journal(journal_bytes(state=journal_state(intent=intent))), REV, True),
            ("sequences not 0 and 1", journal(journal_bytes(1, 2)), REV, True),
            ("slots in swapped order", journal(journal_bytes(1, 0)), REV, True),
            ("foreign bootstrap", journal(journal_bytes(bootstrap="enroll-" + "7" * 32)), REV, True),
            ("nonzero slot tail", journal(p2.slot(0, state, bootstrap=BOOT, tail=b"\x01") +
                                          p2.slot(1, state, bootstrap=BOOT)), REV, True),
            ("anchor differs from the measured tree",
             lambda origin: machine.replace_identity(CONTROL / "journal.dat"), REV, True),
            ("control input replaced", lambda origin: setattr(machine.node(CONTROL / "profiles.json"), "data", b"{}"),
             REV, True),
            ("revision differs from the journal", lambda origin: None, OTHER_REV, True),
            ("revision malformed", lambda origin: None, "gir1:" + "Z" * 64, True),
        ]
        for label, mutate, revision_value, consults in rows:
            with self.subTest(label):
                machine.reset()
                self.as_issuer()
                self.unenrolled()
                origin = provisioner.require_issuer()
                anchor = machine.anchor()
                mutate(origin)
                live = machine.live()
                mark = self.mark()
                self.refused(provisioner.publish_enrollment, origin, anchor, revision_value)
                self.assertNoAuthorityWrite()
                if consults:
                    self.assertTrue(self.calls("OpenKey", mark))
                else:
                    self.assertEqual(machine.events[mark:], [])
                self.assertEqual(machine.live(), live)
                self.assertIsNone(provisioner._unsettled_origin)

    def test_readback_mismatch_is_detected_after_the_write(self):
        origin = provisioner.require_issuer()
        held = self.m.live()
        self.m.readback = "{}"
        self.refused(provisioner.publish_enrollment, origin, self.m.anchor(), REV)
        self.assertEqual(len(self.m.written), 1)  # detection after publication, not prevention
        self.assertEqual(self.calls("FlushKey"), [("FlushKey", LEAF_KEY)])
        self.assertEqual(self.m.live(), held)
        origin.close()
        self.assertSettled()


class GenuineOrigin:
    """The admitted origin surface validate_initial_inputs reads: liveness, captured bytes, approved digests."""
    def __init__(self):
        self.files = {name: data for name, data in RELEASE_FILES.items() if name.startswith(("scripts/", "config/"))}
        self.policy = {"files": {name: sha(data) for name, data in RELEASE_FILES.items()}}
        self.live_checks = 0

    def check_live(self):
        self.live_checks += 1

    def bind(self, path, data):
        self.files[path] = data
        self.policy["files"][path] = sha(data)


class _Untouchable(dict):
    def __getitem__(self, key):
        raise AssertionError("capture read before the live-origin check")


class EnrollmentInputTests(unittest.TestCase):
    """G2-08: enrollment admits only genuine, nonempty, approval-bound protected baselines."""

    def spy(self):
        calls, real = [], guidance.check_reviewed_profile
        def check(symbol, record, approval, registry_sha256, cutoff):
            result = real(symbol, record, approval, registry_sha256, cutoff)
            calls.append((symbol, result))
            return result
        self.enterContext(mock.patch.object(guidance, "check_reviewed_profile", check))
        return calls

    def test_genuine_protected_release_bytes_pass_the_shared_validators(self):
        calls = self.spy()
        origin = GenuineOrigin()
        inputs = enrollment.validate_initial_inputs(origin)
        self.assertEqual(set(inputs), set(BINDINGS))
        self.assertEqual(set(BINDINGS), provisioner.CONTROL_INPUTS)  # enroll and provisioner bind the same set
        for name, path in BINDINGS.items():
            self.assertIs(inputs[name], origin.files[path])
        guided = [record["symbol"] for record in json.loads(GENUINE[REG])["issuers"] if record["status"] == "GUIDANCE"]
        self.assertTrue(guided)
        self.assertEqual(calls, [(symbol, None) for symbol in guided])
        self.assertEqual(origin.live_checks, 1)

    def test_live_origin_is_required_before_any_capture(self):
        origin = GenuineOrigin()
        origin.check_live = mock.Mock(side_effect=UA())
        origin.files = _Untouchable(origin.files)
        with self.assertRaises(UA):
            enrollment.validate_initial_inputs(origin)

    def test_capture_must_equal_the_independently_approved_digest(self):
        origin = GenuineOrigin()
        origin.files[REG] = GENUINE[REG] + b" "
        with self.assertRaises(UA):
            enrollment.validate_initial_inputs(origin)
        origin = GenuineOrigin()
        origin.policy["files"][APP] = "0" * 64
        with self.assertRaises(UA):
            enrollment.validate_initial_inputs(origin)

    def test_refusals_of_approved_but_inadequate_baselines(self):
        registry, approval = json.loads(GENUINE[REG]), json.loads(GENUINE[APP])
        profiles = json.loads(GENUINE[PROF])
        def dumps(value):
            return json.dumps(value).encode("utf-8")
        def rebound(registry_bytes):
            value = copy.deepcopy(approval)
            value["registry_sha256"] = sha(registry_bytes)
            return dumps(value)
        def edit_registry(symbol, **fields):
            value = copy.deepcopy(registry)
            next(record for record in value["issuers"] if record["symbol"] == symbol).update(fields)
            return dumps(value)
        def edit_approval(edit):
            value = copy.deepcopy(approval)
            edit(value)
            return dumps(value)
        nvda = next(record for record in registry["issuers"] if record["symbol"] == "NVDA")
        edited, nameless = edit_registry("NVDA", company_name=nvda["company_name"] + " Edited"), edit_registry("NVDA", company_name="")
        empty = dumps(dict(registry, issuers=[]))
        without_mu = dumps(dict(registry, issuers=[record for record in registry["issuers"] if record["symbol"] != "MU"]))
        undisclosed = dumps(dict(registry, issuers=[record for record in registry["issuers"]
                                                    if record["status"] != "GUIDANCE"]))
        skeleton = dumps({"schema": approval["schema"], "registry_sha256": None, "approved_at": None,
                          "reviewer": None, "records": {}})
        rows = [
            ("empty config object", {CFG: b"{}"}, ValueError, "ENROLLMENT_CONFIG_INVALID", None),
            ("config list", {CFG: b"[]"}, ValueError, "ENROLLMENT_CONFIG_INVALID", None),
            ("profiles schema", {PROF: dumps(dict(profiles, schema="other"))}, ValueError, "PROFILES_SCHEMA", None),
            ("registry not JSON", {REG: b"{", APP: rebound(b"{")}, ValueError, "ENROLLMENT_BASELINE_INVALID", None),
            ("empty registry baseline", {REG: empty, APP: rebound(empty)}, ValueError, "ENROLLMENT_BASELINE_INVALID", None),
            ("approval malformed", {APP: dumps(dict(approval, extra=1))}, ValueError, "ENROLLMENT_BASELINE_INVALID", None),
            ("approval pending skeleton", {APP: skeleton}, ValueError, "ENROLLMENT_APPROVAL_BINDING", []),
            ("approval bound to another registry", {APP: dumps(dict(approval, registry_sha256="0" * 64))},
             ValueError, "ENROLLMENT_APPROVAL_BINDING", []),
            ("approval not bound to a registry without guidance records", {REG: undisclosed},
             ValueError, "ENROLLMENT_APPROVAL_BINDING", []),
            ("record digest not approved", {APP: edit_approval(
                lambda value: value["records"]["NVDA"].update(record_sha256="0" * 64))},
             ValueError, "ENROLLMENT_APPROVAL_BINDING", ("NVDA", "RECORD_CHANGED")),
            ("decision after the enrollment time", {APP: edit_approval(
                lambda value: value["records"]["NVDA"]["decisions"][0].update(reviewed_at="2099-01-01T00:00:00Z"))},
             ValueError, "ENROLLMENT_APPROVAL_BINDING", ("NVDA", "DECISION_TIME_INCOHERENT")),
            ("registry record edited after approval", {REG: edited, APP: rebound(edited)},
             ValueError, "ENROLLMENT_APPROVAL_BINDING", ("NVDA", "RECORD_CHANGED")),
            ("registry record invalid", {REG: nameless, APP: rebound(nameless)}, guidance.GuidanceError, None, None),
            ("enabled profile without a baseline", {REG: without_mu, APP: rebound(without_mu)},
             ValueError, "ENROLLMENT_PROFILE_BASELINE_MISSING", None),
            ("no supported AUTO profile enabled", {PROF: dumps(dict(profiles, enabled_symbols=[]))},
             ValueError, "ENROLLMENT_PROFILES_EMPTY", None),
        ]
        calls = self.spy()
        for label, changes, error, message, last in rows:
            with self.subTest(label):
                calls.clear()
                origin = GenuineOrigin()
                for path, data in changes.items():
                    origin.bind(path, data)  # approved bytes: the digest check passes, the content must still fail
                with self.assertRaises(error) as caught:
                    enrollment.validate_initial_inputs(origin)
                if message is not None:
                    self.assertEqual(str(caught.exception), message)
                if last == []:
                    self.assertEqual(calls, [])  # refused by the registry binding itself, before any record check
                elif last is not None:
                    self.assertEqual(calls[-1], last)


INPUTS = {name: (b"\xa5" * (windows.IO_CHUNK_BYTES + 3) if name == "revenue_guidance.py" else
                 ("synthetic captured " + name).encode("ascii")) for name in sorted(provisioner.CONTROL_INPUTS)}
GENERATION_DIGEST = "e" * 64
DEADLINE = 4321.5


def synthetic_anchor(inputs):
    def identity(number):
        return storage.ObjectIdentity(SERIAL, number.to_bytes(16, "little"))
    return storage._validate_anchor_data(storage.RootAnchor(
        "guidance-provider-storage-v2", BOOT, GUID, identity(1),
        (("ProgramData", identity(2)), ("InvestorIntelligenceGuidance", identity(3)), (BOOT, identity(4))),
        identity(5), identity(6), 1, True, identity(7), identity(8),
        tuple(sorted((name, sha(data)) for name, data in inputs.items()))))


def snapshot(condition="PINNED", digest=GENERATION_DIGEST):
    return SimpleNamespace(condition=condition, generation_sha256=digest)


class EnrollIssuer:
    """Recording issuer context: the enroll caller's view of NativeIssuerContext (no native custody)."""
    def __init__(self, events, journal, inputs, anchor):
        self.events, self.journal, self._initial_inputs, self._anchor = events, journal, inputs, anchor
        self._issuer_origin = SimpleNamespace(role="issuer-origin")
        self.root_handle = SimpleNamespace(name="<root>")
        self.control_handle = SimpleNamespace(name="<control>")
        self.b1_handle = SimpleNamespace(name="<b1>")
        self.coordination_handle = self.journal_handle = None
        self.budget = SimpleNamespace(reserve_transition=lambda **amounts: events.append(("reserve", amounts)))
        self.identity_failure = None
        reader = storage.NativeStorageLease.__new__(storage.NativeStorageLease)
        reader.anchor = SimpleNamespace(bootstrap_id=anchor.bootstrap_id, state_required=True)
        reader._initialize_custody(storage.NativeLimits())
        reader._state = "READY"
        reader.journal_handle = journal.handle
        self._reader = reader  # the real two-slot parser over the in-memory journal

    def __enter__(self):
        self.events.append(("enter",))
        return self

    def __exit__(self, kind, error, trace):
        self.events.append(("exit", kind))
        return False

    @contextmanager
    def namespace_operation(self):
        self.events.append(("namespace", "begin"))
        try:
            yield
        finally:
            self.events.append(("namespace", "end"))

    def create_staging_file(self, parent, name, size):
        if parent is not self.control_handle:
            raise AssertionError("control objects are created only below control")
        handle = self.journal.handle if name == "journal.dat" else SimpleNamespace(name=name)
        handle._staging_reservation = ("reservation", name, size)
        self.events.append(("create", name, size))
        return handle

    def write_owned_chunk(self, handle, offset, data):
        self.events.append(("chunk", handle.name, offset, len(data)))
        if handle is self.journal.handle:
            self.journal.data[offset:offset + len(data)] = data

    def truncate_owned(self, handle, length):
        self.events.append(("truncate", handle.name, length))

    def flush_owned(self, handle):
        self.events.append(("flush-owned", handle.name))

    def _verify_bytes(self, handle, data, *, reservation=None):
        self.events.append(("verify", handle.name, len(data), reservation))

    def close_owned(self, handle):
        self.events.append(("close-owned", handle.name))

    def create_directory(self, parent, name):
        if parent is not self.b1_handle:
            raise AssertionError("B1 directories are created only below b1")
        self.events.append(("mkdir", name))
        return SimpleNamespace(name=name)

    def bind_anchor(self, input_digests):
        self.events.append(("bind", dict(input_digests)))
        return self._anchor

    def _get_both_slots(self, precharged=False):
        self.events.append(("slots", precharged))
        return self._reader._get_both_slots(precharged=precharged)

    def _verify_identity(self, handle, expected):
        self.events.append(("identity-check", handle.name, expected))
        if handle.name == self.identity_failure:
            raise storage.IdentityMismatchError("Identity mismatch")


class FakeStore:
    def __init__(self, events, index, controls):
        self.events, self.index, self.controls = events, index, controls

    def write(self, path, data):
        self.events.append(("store-write", self.index, path, data))

    def _control(self, name):
        self.events.append(("control-readback", self.index, name))
        return self.controls[name]


class EnrollmentOrderTests(unittest.TestCase):
    """G2-09: enroll's caller-level order over a recording issuer, the real slot builder and two-slot parser."""

    def setUp(self):
        events = self.events = []
        self.journal = p2.FakeJournal(bytes(SLOT), bytes(SLOT))
        self.journal.handle = SimpleNamespace(name="journal.dat")
        self.inputs = dict(INPUTS)
        self.anchor = synthetic_anchor(self.inputs)
        self.issuer = EnrollIssuer(events, self.journal, self.inputs, self.anchor)
        self.snapshots, self.revisions, self.controls = [snapshot(), snapshot()], [REV, REV], dict(self.inputs)
        self.generations, self.stores = [], []
        self.close_error = self.publish_error = None
        journal = self.journal

        def issuer_context(parent_remaining_ms, *, parent_deadline):
            events.append(("issuer-context", parent_remaining_ms, parent_deadline))
            return self.issuer

        def native_close(lease):
            events.append(("native-close", lease is self.issuer))
            if self.close_error is not None:
                raise self.close_error

        def publish(origin, anchor, revision_value):
            events.append(("publish", origin, anchor, revision_value))
            if self.publish_error is not None:
                raise self.publish_error

        def b1_store(issuer):
            if issuer is not self.issuer:
                raise AssertionError("B1Store over a foreign context")
            store = FakeStore(events, len(self.stores), self.controls)
            self.stores.append(store)
            events.append(("store", store.index))
            return store

        def publish_generation(store, generation, parent):
            events.append(("publish-generation", store.index, parent))
            self.generations.append(generation)
            return GENERATION_DIGEST

        def load(*, cutoff, state_root, state_required):
            events.append(("load", state_root.index, state_required))
            return ("effective", state_root.index)

        def require(effective, *rest):
            events.append(("require-snapshot", effective[1], len(rest)))
            return self.snapshots.pop(0)

        def compute(value):
            events.append(("revision",))
            return self.revisions.pop(0)

        def write_at(handle, offset, data):
            events.append(("write", offset, bytes(data)))
            journal.write_at(handle, offset, data)

        def flush(handle):
            events.append(("flush",))
            journal.flush(handle)

        def read_at(handle, offset, count):
            events.append(("read", offset, count))
            return journal.read_at(handle, offset, count)

        enter = self.enterContext
        enter(mock.patch.object(storage, "NativeIssuerContext", issuer_context))
        enter(mock.patch.object(storage.NativeStorageLease, "close", native_close))
        enter(mock.patch.object(provisioner, "publish_enrollment", publish))
        enter(mock.patch.object(windows, "write_at", write_at))
        enter(mock.patch.object(windows, "flush", flush))
        enter(mock.patch.object(windows, "read_at", read_at))
        enter(mock.patch.object(windows, "protect_issuer_object",
                                lambda handle, role: events.append(("protect", handle.name, role))))
        self.bind = enter(mock.patch.object(windows, "_lazy_bind", side_effect=AssertionError("native binding reached")))
        enter(mock.patch.object(overlay, "B1Store", b1_store))
        enter(mock.patch.object(overlay, "identity", lambda profiles, registry, approval, store:
                                (events.append(("identity", store.index)), {"inputs": "identity"})[1]))
        enter(mock.patch.object(overlay, "publish_generation", publish_generation))
        enter(mock.patch.object(overlay, "load_effective_inputs", load))
        enter(mock.patch.object(overlay, "require_snapshot", require))
        enter(mock.patch.object(revision, "compute_input_revision", compute))

    def tearDown(self):
        self.bind.assert_not_called()

    def run_enroll(self):
        return enrollment.enroll(5000, parent_deadline=DEADLINE)

    def expected_success(self):
        chunk = windows.IO_CHUNK_BYTES
        def control(name, data, role):
            rows = [("create", name, len(data))]
            rows += [("chunk", name, offset, len(data[offset:offset + chunk])) for offset in range(0, len(data), chunk)]
            return rows + [("truncate", name, len(data)), ("flush-owned", name),
                           ("verify", name, len(data), ("reservation", name, len(data))), ("protect", name, role)]
        state = journal_state()
        invalid = journal_bytes(state=state, magic=INVALID_MAGIC)
        rows = [("issuer-context", 5000, DEADLINE), ("enter",), ("namespace", "begin")]
        for name, data in self.inputs.items():
            rows += control(name, data, "input") + [("close-owned", name)]
        rows += control("coordination.lock", b"\x00", "journal")
        rows += control("journal.dat", bytes(storage.JOURNAL_FILE_SIZE), "journal")
        rows += [("bind", {name: sha(data) for name, data in self.inputs.items()})]
        for directory in ("captures", "segments", "generations"):
            rows += [("mkdir", directory), ("close-owned", directory)]
        rows += [("store", 0),
                 ("store-write", 0, ("store_usage.json",), b'{"bytes": 0, "files": 0, "pending": {}}'),
                 ("store-write", 0, ("queue.json",), b'{"last_served":null}'),
                 ("store-write", 0, ("receipts.json",),
                  json.dumps({"schema": guidance.RELEASE_CHECKS_SCHEMA, "issuers": {}}).encode("utf-8")),
                 ("identity", 0), ("publish-generation", 0, None), ("load", 0, True), ("require-snapshot", 0, 1),
                 ("revision",),
                 ("reserve", {"write_bytes": storage.JOURNAL_FILE_SIZE + 16,
                              "read_bytes": 2 * storage.JOURNAL_FILE_SIZE, "mutations": 6}),
                 ("write", 0, invalid), ("flush",), ("read", 0, storage.JOURNAL_FILE_SIZE),
                 ("write", 0, MAGIC), ("flush",), ("write", SLOT, MAGIC), ("flush",),
                 ("slots", True), ("read", 0, storage.JOURNAL_FILE_SIZE),
                 ("store", 1), ("load", 1, True), ("require-snapshot", 1, 1), ("revision",)]
        rows += [("control-readback", 1, name) for name in self.inputs]
        rows += [("identity-check", "<root>", self.anchor.root_components[-1][1]),
                 ("identity-check", "<control>", self.anchor.control_identity),
                 ("identity-check", "<b1>", self.anchor.b1_identity),
                 ("namespace", "end"), ("native-close", True),
                 ("publish", self.issuer._issuer_origin, self.anchor, REV), ("exit", None)]
        return rows

    def test_enrollment_flushes_reads_back_and_publishes_authority_last(self):
        result = self.run_enroll()
        self.assertEqual(result, {"status": "ENROLLED_PENDING_REBUILD", "state_required": True, "model_complete": False})
        self.assertEqual(self.events, self.expected_success())
        state = journal_state()
        self.assertEqual(bytes(self.journal.data), journal_bytes(state=state))  # both adjacent slots, magic last
        self.assertEqual([slot.state for slot in self.issuer._reader._get_both_slots(precharged=True)], [state, state])
        generation = self.generations[0]
        self.assertEqual(set(generation), {"inputs", "schema", "generation_id", "parent", "created_at", "issuers",
                                           "detections"})
        self.assertEqual((generation["schema"], generation["parent"], generation["issuers"], generation["detections"]),
                         (overlay.STATE_SCHEMA, None, {}, {}))  # no fabricated financial history
        self.assertRegex(generation["generation_id"], r"\A\d{8}T\d{6}Z-[0-9a-f]{12}\Z")
        self.assertRegex(generation["created_at"], r"\A\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z\Z")
        for handle in (self.issuer.coordination_handle, self.issuer.journal_handle):
            self.assertIsNone(handle._staging_reservation)
            self.assertTrue(handle._published)
        self.assertIs(self.issuer.journal_handle, self.journal.handle)

    def test_refusals_never_publish_authority(self):
        journal = self.journal
        def first(event):
            return event[0]
        rows = [
            ("snapshot not pinned", lambda: self.snapshots.__setitem__(0, snapshot(condition="STATE_FAILURE")),
             storage.StorageLeaseError, "ENROLLMENT_SNAPSHOT_UNAVAILABLE", lambda event: first(event) in ("reserve", "write")),
            ("snapshot of another generation", lambda: self.snapshots.__setitem__(0, snapshot(digest="f" * 64)),
             storage.StorageLeaseError, "ENROLLMENT_SNAPSHOT_UNAVAILABLE", lambda event: first(event) in ("reserve", "write")),
            ("journal readback differs", lambda: setattr(journal, "override", lambda o, c, n: bytes(c) if n == 1 else None),
             storage.StorageLeaseError, "ENROLLMENT_JOURNAL_READBACK", lambda event: event == ("write", 0, MAGIC)),
            ("slots read back another state", lambda: setattr(journal, "override", lambda o, c, n: journal_bytes(
                state=journal_state(pending=None)) if n == 2 else None),
             storage.StorageLeaseError, "ENROLLMENT_JOURNAL_READBACK", lambda event: event == ("store", 1)),
            ("torn slots", lambda: setattr(journal, "override", lambda o, c, n: bytes(c) if n == 2 else None),
             storage.JournalRecoveryRequired, None, lambda event: event == ("store", 1)),
            ("revision differs on readback", lambda: self.revisions.__setitem__(1, OTHER_REV),
             storage.StorageLeaseError, "ENROLLMENT_REVISION_READBACK", lambda event: first(event) == "control-readback"),
            ("control input differs on readback", lambda: self.controls.__setitem__("approval.json", b"{}"),
             storage.StorageLeaseError, "ENROLLMENT_INPUT_READBACK", lambda event: first(event) == "identity-check"),
            ("identity changed", lambda: setattr(self.issuer, "identity_failure", "<b1>"),
             storage.IdentityMismatchError, None, lambda event: first(event) == "native-close"),
            ("native cleanup unconfirmed", lambda: setattr(self, "close_error", storage.StorageLeaseError("PENDING")),
             storage.StorageLeaseError, "PENDING", lambda event: False),
            ("publication refused", lambda: setattr(self, "publish_error", UA()), UA, "TRUST_AUTHORITY_UNAVAILABLE",
             lambda event: False),
        ]
        for label, mutate, error, message, absent in rows:
            with self.subTest(label):
                self.events.clear()
                journal.data[:] = bytes(storage.JOURNAL_FILE_SIZE)
                journal.override, journal.full_reads = None, 0
                self.snapshots[:], self.revisions[:] = [snapshot(), snapshot()], [REV, REV]
                self.controls.clear()
                self.controls.update(self.inputs)
                self.issuer.identity_failure = self.close_error = self.publish_error = None
                mutate()
                with self.assertRaises(error) as caught:
                    self.run_enroll()
                if message is not None:
                    self.assertEqual(str(caught.exception), message)
                published = [event for event in self.events if event[0] == "publish"]
                self.assertEqual(len(published), 1 if label == "publication refused" else 0)
                self.assertFalse(any(absent(event) for event in self.events))
                self.assertEqual(self.events[-1], ("exit", type(caught.exception)))


class BootstrapGuardTests(unittest.TestCase):
    """G2-13: the fixed protected entry refuses every load outside the protected release and -I -S -B.

    Refusal only: no test passes the guard, and nothing behind it is executed here.
    """

    def setUp(self):
        self.path = list(sys.path)
        self.entry = sys.modules.get("revenue_guidance_bootstrap", None)
        self.addCleanup(self.restore_path)

    def restore_path(self):
        sys.path[:] = self.path

    @staticmethod
    def flags(**overrides):
        # Every real interpreter flag, with only the three guarded ones overridden.
        values = {name: getattr(sys.flags, name) for name in dir(sys.flags)
                  if not name.startswith(("_", "n_")) and name not in ("count", "index")}
        values.update(overrides)
        return SimpleNamespace(**values)

    def execute(self, filename, flags):
        code = compile(BOOTSTRAP_SOURCE, str(filename), "exec")
        namespace = {"__name__": "revenue_guidance_bootstrap_guard_probe", "__file__": str(filename),
                     "__builtins__": builtins}
        with mock.patch.object(sys, "flags", flags), self.assertRaises(SystemExit) as caught:
            exec(code, namespace)
        return caught.exception, namespace

    def assertNothingLoaded(self, names):
        for name in ("main", "provisioner", "acquire", "run_with_native_lifetime", "_pending", "_hold_native_lifetime"):
            self.assertNotIn(name, names)
        self.assertEqual(sys.path, self.path)
        self.assertNotIn("revenue_guidance_bootstrap_guard_probe", sys.modules)
        self.assertIs(sys.modules.get("revenue_guidance_bootstrap", None), self.entry)

    def test_import_from_the_development_tree_is_refused(self):
        spec = importlib.util.spec_from_file_location("revenue_guidance_bootstrap_guard_probe", BOOTSTRAP)
        module = importlib.util.module_from_spec(spec)
        with mock.patch.object(sys, "dont_write_bytecode", True), self.assertRaises(SystemExit) as caught:
            spec.loader.exec_module(module)
        self.assertEqual(caught.exception.code, "TRUST_AUTHORITY_UNAVAILABLE")
        self.assertNothingLoaded(vars(module))

    def test_forged_protected_location_still_requires_isolated_no_site_no_bytecode(self):
        for isolated, no_site, no_bytecode in ((0, 1, 1), (1, 0, 1), (1, 1, 0), (0, 0, 0)):
            with self.subTest(isolated=isolated, no_site=no_site, dont_write_bytecode=no_bytecode):
                error, namespace = self.execute(FORGED_BOOTSTRAP, self.flags(
                    isolated=isolated, no_site=no_site, dont_write_bytecode=no_bytecode))
                self.assertEqual(error.code, "TRUST_AUTHORITY_UNAVAILABLE")
                self.assertNothingLoaded(namespace)

    def test_locations_outside_the_fixed_release_layout_are_refused_even_with_protected_flags(self):
        base = provisioner.CODE_BASE
        for filename in (base / RELEASE / "scripts" / "revenue_guidance_bootstrap_copy.py",
                         base / RELEASE / "tools" / "revenue_guidance_bootstrap.py",
                         base / RELEASE / "nested" / "scripts" / "revenue_guidance_bootstrap.py",
                         base.parent / "staging" / RELEASE / "scripts" / "revenue_guidance_bootstrap.py",
                         BOOTSTRAP):
            with self.subTest(str(filename)):
                error, namespace = self.execute(filename, self.flags(isolated=1, no_site=1, dont_write_bytecode=1))
                self.assertEqual(error.code, "TRUST_AUTHORITY_UNAVAILABLE")
                self.assertNothingLoaded(namespace)

    def test_static_shape_of_the_entry(self):
        """Characterization of source shape only; not caller-level qualification."""
        tree = ast.parse(BOOTSTRAP_SOURCE)
        body = tree.body
        guards = [index for index, node in enumerate(body)
                  if isinstance(node, ast.If) and any(isinstance(statement, ast.Raise) for statement in node.body)
                  and ast.unparse(node.test) != "__name__ == '__main__'"]
        insert = next(index for index, node in enumerate(body)
                      if isinstance(node, ast.Expr) and ast.unparse(node).startswith("sys.path.insert"))
        imported = next(index for index, node in enumerate(body) if isinstance(node, ast.Import)
                        and any(alias.name == "revenue_guidance_provisioner" for alias in node.names))
        self.assertEqual(len(guards), 2)
        self.assertLess(max(guards), insert)
        self.assertLess(insert, imported)
        functions = {node.name: node for node in body if isinstance(node, ast.FunctionDef)}
        choices = [keyword.value for call in ast.walk(functions["main"]) if isinstance(call, ast.Call)
                   and getattr(call.func, "attr", None) == "add_argument" and call.args
                   and isinstance(call.args[0], ast.Constant) and call.args[0].value == "command"
                   for keyword in call.keywords if keyword.arg == "choices"]
        self.assertEqual([ast.literal_eval(choice) for choice in choices],
                         [("enroll", "snapshot", "check", "update", "maintain", "recount", "host")])
        issuer = [ast.unparse(keyword.value) for call in ast.walk(functions["main"]) if isinstance(call, ast.Call)
                  and getattr(call.func, "attr", None) == "controlled_origin" for keyword in call.keywords
                  if keyword.arg == "issuer"]
        self.assertEqual(issuer, ["args.command == 'enroll'"])
        enroll_guards = [ast.unparse(node.test) for node in ast.walk(functions["main"]) if isinstance(node, ast.If)
                         and any(isinstance(statement, ast.Import) and statement.names[0].name == "revenue_guidance_enroll"
                                 for statement in node.body)]
        self.assertEqual(enroll_guards, ["args.command == 'enroll'"])
        tries = [node for node in functions["run_with_native_lifetime"].body if isinstance(node, ast.Try)]
        self.assertEqual([[ast.unparse(statement) for statement in node.finalbody] for node in tries],
                         [["_hold_native_lifetime()"]])
        constants = {node.value for node in ast.walk(functions["_hold_native_lifetime"]) if isinstance(node, ast.Constant)}
        self.assertIn('{"status":"NATIVE_CUSTODY_UNRESOLVED","model_complete":false}', constants)
        pending = [node for node in ast.walk(functions["_pending"]) if isinstance(node, ast.Return)]
        self.assertEqual(len(pending), 1)
        returned = dict(zip((ast.literal_eval(key) for key in pending[0].value.keys), pending[0].value.values))
        self.assertIs(ast.literal_eval(returned["model_complete"]), False)
        self.assertEqual(ast.unparse(returned["state_required"]), "True")
        assigned = {ast.unparse(node) for node in ast.walk(functions["_pending"]) if isinstance(node, ast.Assign)}
        self.assertIn("state['PendingRevision'] = current_revision", assigned)
        modules = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                modules |= {alias.name for alias in node.names}
            elif isinstance(node, ast.ImportFrom):
                modules.add(node.module)
        self.assertLessEqual(modules, {
            "__future__", "argparse", "json", "sys", "pathlib", "time", "datetime", "sec_contact_headers",
            "revenue_guidance_provisioner", "revenue_guidance_storage", "revenue_guidance_revision",
            "revenue_guidance_host", "revenue_guidance_overlay", "revenue_guidance_enroll",
            "revenue_guidance_release_check", "revenue_guidance_autoupdate"})
        names = ({node.id for node in ast.walk(tree) if isinstance(node, ast.Name)} |
                 {node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)})
        self.assertEqual(names & {"ShellExecuteW", "ShellExecuteExW", "CreateProcessW", "Popen", "system", "startfile",
                                  "execv", "runas", "subprocess", "ctypes", "winreg"}, set())


if __name__ == "__main__":
    unittest.main()
