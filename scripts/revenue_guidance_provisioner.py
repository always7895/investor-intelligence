"""F02C controlled machine authority. SOURCE ONLY / IMPLEMENTED_UNVERIFIED.

No registration hook, caller verifier, anchor cache or self-authorizing manifest.
Approval is seeded independently by a privileged trusted operator in HKLM64 BEFORE
our installer is entered. Checks within this interpreter are not a sandbox against
replacement of that interpreter/entrypoint. The initial trusted entry is external.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import threading
from pathlib import Path

# Failure custody only, NEVER cached authority. Real synchronous origin owners
# are retained before cleanup; future authority acquisition is unavailable.
_unsettled_origin = None
_origin_hold_event = threading.Event()


def origin_custody_status():
    return "UNRESOLVED" if _unsettled_origin is not None else "SETTLED"


def hold_unresolved_origin_custody():
    if origin_custody_status() != "UNRESOLVED":
        return
    while True:
        try:
            _origin_hold_event.wait()  # never signalled; no IO retry/cleanup/ack
        except BaseException:
            continue

AUTHORITY_KEY = r"SOFTWARE\InvestorIntelligence\GuidanceProtected"
CODE_BASE = Path(r"C:\Program Files\InvestorIntelligence\GuidanceProtected\releases")
DATA_BASE = Path(r"C:\ProgramData\InvestorIntelligenceGuidance")
TRUSTED = {"S-1-5-18", "S-1-5-32-544"}
# TrustedInstaller is an OS servicing owner, not an application runtime principal.
OWNERS = TRUSTED | {"S-1-5-80-956008885-3418522649-1831038044-1853292631-2271478464"}
CONTROL_INPUTS = {"config.json", "profiles.json", "registry.json", "approval.json",
                  "revenue_guidance.py", "revenue_guidance_auto_verify.py", "revenue_guidance_overlay.py"}
REQUIRED_FILES = {"Python/python.exe", "Python/python312.dll", "scripts/revenue_guidance_bootstrap.py",
                  "scripts/revenue_guidance_provisioner.py", "scripts/revenue_guidance_enroll.py",
                  "scripts/revenue_guidance_storage.py", "scripts/revenue_guidance_windows.py",
                  "scripts/revenue_guidance_revision.py", "scripts/revenue_guidance_overlay.py",
                  "scripts/revenue_guidance.py", "scripts/revenue_guidance_auto_verify.py",
                  "scripts/revenue_guidance_release_check.py", "scripts/revenue_guidance_autoupdate.py",
                  "scripts/issuer_ir_feeds.py", "scripts/sec_contact_headers.py",
                  "scripts/install_revenue_guidance_protected.ps1", "config/revenue-guidance-v1.json",
                  "config/revenue-guidance-approval-v1.json", "config/revenue-guidance-extraction-profiles-v1.json",
                  "config/system-bottleneck-explosion-v1.json"}
# Full real ranking/publisher/model closure, not merely host.py beside writable imports.
HOST_REQUIRED_FILES = {
    "scripts/revenue_guidance_host.py", "scripts/revenue_guidance_backend.psm1",
    "scripts/revenue_guidance_machine.py",
    "scripts/revenue_guidance_provider.psm1", "scripts/revenue_guidance_orchestration.psm1",
    "scripts/bottleneck_top20_v3.py", "scripts/publish_sealed_snapshot.py",
    "scripts/bottleneck_ranking.py", "scripts/bottleneck_claim_admission.py",
    "scripts/company_claim_admission_bridge.py", "scripts/multilineage_claim_bundle.py",
    "scripts/source_registry.py", "scripts/adapters/__init__.py", "scripts/adapters/base.py",
    "scripts/adapters/sec_edgar.py", "scripts/adapters/world_bank.py", "scripts/adapters/ecb_fx_reference.py",
    "scripts/build_v213_macro_industry_research.py",
    "scripts/build_zh_names.py", "scripts/company_deep_report.py", "scripts/thesis_phase.py",
    "scripts/listing_lineage.py", "scripts/order_forecast.py", "scripts/order_claims.py",
    "scripts/revenue_consensus_quarterly.py", "scripts/revenue_guidance_wire.py",
    "scripts/top20_carry_forward.py", "scripts/v213_evidence_policy.py",
    "scripts/official_quarterly_revenue.py", "config/bottleneck-layers-v3.json",
    "config/listing-lineage-v1.json", "config/official-quarterly-revenue-v1.json",
    "config/company-zh-names-v1.json", "config/order-claims-v2.json",
    "config/korea-ir-orders-v1.json", "config/korea-ir-fundamentals-v1.json",
}
REQUIRED_FILES |= HOST_REQUIRED_FILES


class AuthorityUnavailable(RuntimeError):
    def __init__(self):
        super().__init__("TRUST_AUTHORITY_UNAVAILABLE")


def _json(raw):
    def pairs(items):
        result = {}
        for k, v in items:
            if k in result:
                raise AuthorityUnavailable()
            result[k] = v
        return result
    if type(raw) is not str or len(raw.encode("utf-8")) > 2 * 1024 * 1024:
        raise AuthorityUnavailable()
    return json.loads(raw, object_pairs_hook=pairs, parse_constant=lambda _: (_ for _ in ()).throw(AuthorityUnavailable()))


def _apis():
    if _unsettled_origin is not None:
        raise AuthorityUnavailable()  # failure veto, not a cached admission result
    # Authority domain is distinct from candidate-driven storage allocation.
    # This binding is never authorization, and is deliberately not cached.
    if sys.platform != "win32" or sys.implementation.name != "cpython" or sys.version_info[:3] != (3, 12, 10) or sys.maxsize < 2**32:
        raise AuthorityUnavailable()
    import ctypes as c
    from ctypes import wintypes as w
    k = c.WinDLL("kernel32.dll", winmode=0x800)
    a = c.WinDLL("advapi32.dll", winmode=0x800)
    k.CreateFileW.argtypes = [w.LPCWSTR, w.DWORD, w.DWORD, c.c_void_p, w.DWORD, w.DWORD, w.HANDLE]
    k.CreateFileW.restype = w.HANDLE
    k.CloseHandle.argtypes = [w.HANDLE]
    k.CloseHandle.restype = w.BOOL
    k.GetFileInformationByHandleEx.argtypes = [w.HANDLE, c.c_int, c.c_void_p, w.DWORD]
    k.GetFileInformationByHandleEx.restype = w.BOOL
    k.GetFileSizeEx.argtypes = [w.HANDLE, c.POINTER(c.c_int64)]
    k.GetFileSizeEx.restype = w.BOOL
    k.ReadFile.argtypes = [w.HANDLE, c.c_void_p, w.DWORD, c.POINTER(w.DWORD), c.c_void_p]
    k.ReadFile.restype = w.BOOL
    k.LocalFree.argtypes = [c.c_void_p]
    k.LocalFree.restype = c.c_void_p
    a.GetSecurityInfo.argtypes = [w.HANDLE, c.c_int, w.DWORD, c.POINTER(c.c_void_p), c.POINTER(c.c_void_p),
                                  c.POINTER(c.c_void_p), c.POINTER(c.c_void_p), c.POINTER(c.c_void_p)]
    a.GetSecurityInfo.restype = w.DWORD
    a.ConvertSidToStringSidW.argtypes = [c.c_void_p, c.POINTER(c.c_void_p)]
    a.ConvertSidToStringSidW.restype = w.BOOL
    a.GetAclInformation.argtypes = [c.c_void_p, c.c_void_p, w.DWORD, c.c_int]
    a.GetAclInformation.restype = w.BOOL
    a.GetAce.argtypes = [c.c_void_p, w.DWORD, c.POINTER(c.c_void_p)]
    a.GetAce.restype = w.BOOL
    a.OpenProcessToken.argtypes = [w.HANDLE, w.DWORD, c.POINTER(w.HANDLE)]
    a.OpenProcessToken.restype = w.BOOL
    a.GetTokenInformation.argtypes = [w.HANDLE, c.c_int, c.c_void_p, w.DWORD, c.POINTER(w.DWORD)]
    a.GetTokenInformation.restype = w.BOOL
    k.GetCurrentProcess.restype = w.HANDLE
    k.GetVolumeNameForVolumeMountPointW.argtypes = [w.LPCWSTR, w.LPWSTR, w.DWORD]
    k.GetVolumeNameForVolumeMountPointW.restype = w.BOOL
    return c, w, k, a


def _sid(apis, ptr):
    c, w, k, a = apis
    text = c.c_void_p()
    if not a.ConvertSidToStringSidW(ptr, c.byref(text)):
        raise AuthorityUnavailable()
    try:
        return c.wstring_at(text)
    finally:
        if k.LocalFree(text):
            raise AuthorityUnavailable()


def _security(apis, handle, kind=1, *, runtime=None, allowed=0, ancestor=False):
    c, w, k, a = apis
    owner, dacl, sd = c.c_void_p(), c.c_void_p(), c.c_void_p()
    if a.GetSecurityInfo(handle, kind, 5, c.byref(owner), None, c.byref(dacl), None, c.byref(sd)):
        raise AuthorityUnavailable()
    try:
        if not owner.value or _sid(apis, owner) not in (OWNERS if ancestor else TRUSTED) or not dacl.value:
            raise AuthorityUnavailable()
        info = (w.DWORD * 3)()
        if not a.GetAclInformation(dacl, info, c.sizeof(info), 2) or info[0] > 256:
            raise AuthorityUnavailable()
        # Registry writes incl CREATE_SUB_KEY; file ancestor create rights do not
        # themselves permit replacing a held protected child. DELETE_CHILD does.
        dangerous = 0xD0000 | (0x26 if kind == 4 else (0x150 if ancestor else 0x156))
        for i in range(info[0]):
            ace = c.c_void_p()
            if not a.GetAce(dacl, i, c.byref(ace)):
                raise AuthorityUnavailable()
            header = c.string_at(ace, 4)
            ace_type, flags = header[0], header[1]
            size = int.from_bytes(header[2:4], "little")
            if size < 12 or ace_type not in (0, 1):
                raise AuthorityUnavailable()  # unknown/object/callback ACE never assumed safe
            if ace_type == 1 or flags & 8:  # deny / INHERIT_ONLY
                continue
            mask = int.from_bytes(c.string_at(ace.value + 4, 4), "little")
            principal = _sid(apis, c.c_void_p(ace.value + 8))
            if principal not in (OWNERS if ancestor else TRUSTED):
                permitted = allowed if principal == runtime else 0
                if mask & (0x50000000 | dangerous) & ~permitted:  # generic ALL/WRITE too
                    raise AuthorityUnavailable()
    finally:
        if sd.value and k.LocalFree(sd):
            raise AuthorityUnavailable()


class _HeldOrigin:
    """Synchronous independent OS authority custody; not a NativeStorageLease."""
    def __init__(self):
        self.apis = _apis()
        self.handles = []
        self.registry = []
        self.closed = False
        self.close_failed = False
        self._custody_next_origin = None
        self.files = {}
        self.policy = None
        self.installation = None
        self.enrollment = None
        self.live_owner_handle = None
        self.live_owner_owned = False
        self._p2_admission_conflicts = []
        self._p2_admission_phase = "NOT_STARTED"

    def hold(self, path, *, directory=False, ancestor=False, runtime=None, allowed=0):
        c, w, k, a = self.apis
        if len(self.handles) >= 8192:
            raise AuthorityUnavailable()
        h = k.CreateFileW(str(path), 0x80000000 | 0x20000, 3 if directory else 1, None, 3, 0x02200000, None)
        if h in (None, 0, c.c_void_p(-1).value):
            raise AuthorityUnavailable()
        # Retain before any metadata/security validation.
        self.handles.append(h)
        attr = (w.DWORD * 2)()
        std = c.create_string_buffer(24)
        fid = c.create_string_buffer(24)
        if (not k.GetFileInformationByHandleEx(h, 9, attr, 8)
                or not k.GetFileInformationByHandleEx(h, 1, std, 24)
                or not k.GetFileInformationByHandleEx(h, 18, fid, 24)):
            raise AuthorityUnavailable()
        data = std.raw
        if attr[0] & 0x400 or attr[1] or bool(data[21]) != directory or data[20] or (not directory and int.from_bytes(data[16:20], "little") != 1):
            raise AuthorityUnavailable()
        _security(self.apis, h, runtime=runtime, allowed=allowed, ancestor=ancestor)
        return h, (int.from_bytes(fid.raw[:8], "little"), fid.raw[8:24])

    def ancestors(self, path):
        target = Path(path)
        for parent in reversed(target.parents):
            self.hold(parent, directory=True, ancestor=True)

    def read(self, handle, cap=256 * 1024 * 1024):
        c, w, k, a = self.apis
        size = c.c_int64()
        if not k.GetFileSizeEx(handle, c.byref(size)) or not 0 <= size.value <= cap:
            raise AuthorityUnavailable()
        parts = []
        remaining = size.value
        while remaining:
            count = min(1024 * 1024, remaining)
            buf, got = c.create_string_buffer(count), w.DWORD()
            if not k.ReadFile(handle, buf, count, c.byref(got), None) or got.value != count:
                raise AuthorityUnavailable()
            parts.append(buf.raw)
            remaining -= count
        return b"".join(parts)

    def close(self):
        global _unsettled_origin
        if self.closed:
            if self.close_failed:
                raise AuthorityUnavailable()
            return
        # Keep exact actual origin objects/keys/handles BEFORE any cleanup
        # submission or status handoff. A pre-existing uncertainty vetoes further origin close calls;
        # retain other already-open origins through existing object links, not an
        # authorization cache/registration hook or new allocation/resource limit.
        self._custody_next_origin = _unsettled_origin
        _unsettled_origin = self
        self.closed = True
        self.close_failed = True
        if self._custody_next_origin is not None:
            raise AuthorityUnavailable()
        for key in reversed(self.registry):
            key.Close()  # never pop/forget a key whose cleanup may be uncertain
        for h in reversed(self.handles):
            if not self.apis[2].CloseHandle(h):
                raise AuthorityUnavailable()  # no retry or further close workaround
        # Per-enrollment interlock is released LAST, only after every actual
        # authority owner closed. Any earlier uncertainty retains its live handle
        # through bootstrap's original outer origin-custody lifetime veto.
        if self.live_owner_handle is not None:
            if self.live_owner_owned and not self.apis[2].ReleaseMutex(self.live_owner_handle):
                raise AuthorityUnavailable()
            if not self.apis[2].CloseHandle(self.live_owner_handle):
                raise AuthorityUnavailable()  # no retry, including interrupted release/close
            self.live_owner_handle = None
            self.live_owner_owned = False
        self.registry.clear()
        self.handles.clear()
        self.close_failed = False
        _unsettled_origin = None  # ONLY complete confirmed disposal permits return

    def release_p2_admission_conflicts(self):
        """Retire ONLY original admission read handles; SAME mutex stays owned.

        Enrollment validation is not native P2 sharing permission. Its actual
        coordination/journal READ/shareREAD owners conflict with exclusive P2
        WRITE/share0. Retain before the one cleanup phase; no release/reacquire
        gap, permission/share relaxation, cloned authority or uncertain retry.
        """
        global _unsettled_origin
        self.check_live()
        if (self._p2_admission_phase != "NOT_STARTED" or not self.live_owner_owned or
                self.live_owner_handle is None or len(self._p2_admission_conflicts) != 2 or
                {row["role"] for row in self._p2_admission_conflicts} != {"coordination.lock", "journal.dat"} or
                len({row["handle"] for row in self._p2_admission_conflicts}) != 2 or
                any(row["attempted"] or row["closed"] or self.handles.count(row["handle"]) != 1
                    for row in self._p2_admission_conflicts)):
            raise AuthorityUnavailable()
        # Failure rooting BEFORE any close/status handoff. Other uncertainty
        # vetoes new cleanup, retaining this exact origin+continuous guard too.
        self._custody_next_origin = _unsettled_origin
        _unsettled_origin = self
        self._p2_admission_phase = "RELEASING"
        if self._custody_next_origin is not None:
            raise AuthorityUnavailable()
        for row in self._p2_admission_conflicts:
            row["attempted"] = True
            if not self.apis[2].CloseHandle(row["handle"]):
                raise AuthorityUnavailable()  # exact owner retained; no more close/P2/guard release
            row["closed"] = True
            self.handles.remove(row["handle"])  # only confirmed disposal; NEVER close again at final cleanup
        self._p2_admission_phase = "CONFIRMED"
        _unsettled_origin = None  # both confirmed; SAME actual mutex remains owned and rooted in self

    def capture_public_input(self, relative, budget, cap=8 * 1024 * 1024):
        """Held public DATA observation, NEVER authority/code/config admission.

        Selector comes from independently protected HKLM PublicInputs. Fixed host
        names only; no credentials/broker/IBKR discovery/enumeration or callbacks.
        Public data can be writable; captured exact bytes, not their path/hash,
        feed the unchanged financial admission. Distinct from protected hold().
        """
        self.check_live()
        data = _machine(self, "PublicInputs")
        if (type(data) is not dict or set(data) != {"schema", "root"} or
                data["schema"] != "guidance-public-inputs-v1" or type(data["root"]) is not str or
                not re.fullmatch(r"[A-Za-z]:\\[^\x00-\x1f]{1,230}", data["root"]) or
                type(relative) is not str or len(relative) > 240 or
                any(not re.fullmatch(r"[A-Za-z0-9_.-]+", p) or p in (".", "..") for p in relative.split("/"))):
            raise AuthorityUnavailable()
        root = Path(data["root"])
        target = root.joinpath(*relative.split("/"))
        if root not in target.parents:
            raise AuthorityUnavailable()
        c, w, k, a = self.apis
        actual = None
        for path in list(reversed(root.parents)) + [root] + list(target.parents)[::-1][len(root.parents) + 1:] + [target]:
            directory = path != target
            budget._check_time()
            if len(self.handles) >= 8192:
                raise AuthorityUnavailable()
            h = k.CreateFileW(str(path), 0x80000000, 3 if directory else 1, None, 3, 0x02200000, None)
            if h in (None, 0, c.c_void_p(-1).value):
                # Only actual missing leaf/directory is absence. No ACL/metadata/
                # capacity/UNKNOWN error masquerades as an empty financial input.
                if k.GetLastError() in (2, 3):
                    return None, {"status": "ABSENT", "selector_sha256": hashlib.sha256(
                        json.dumps(data, sort_keys=True).encode()).hexdigest()}
                raise AuthorityUnavailable()
            self.handles.append(h)
            tags, std, fid, basic = (w.DWORD * 2)(), c.create_string_buffer(24), c.create_string_buffer(24), c.create_string_buffer(40)
            if (not k.GetFileInformationByHandleEx(h, 9, tags, 8) or
                    not k.GetFileInformationByHandleEx(h, 1, std, 24) or
                    not k.GetFileInformationByHandleEx(h, 18, fid, 24) or
                    not k.GetFileInformationByHandleEx(h, 0, basic, 40) or tags[0] & 0x400 or tags[1] or
                    bool(std.raw[21]) != directory or std.raw[20] or
                    (not directory and int.from_bytes(std.raw[16:20], "little") != 1)):
                raise AuthorityUnavailable()
            if not directory:
                size = int.from_bytes(std.raw[8:16], "little", signed=True)
                if not 0 <= size <= cap:
                    raise AuthorityUnavailable()
                budget.consume_read(size)  # actual combined ceiling, no hidden extra allowance/refund
                raw = self.read(h, cap)
                budget.admit_capture(len(raw), raw_document=cap > 8 * 1024 * 1024, historical=True)
                actual = {"status": "CAPTURED", "sha256": hashlib.sha256(raw).hexdigest(),
                          "last_write_filetime": int.from_bytes(basic.raw[16:24], "little"),
                          "selector_sha256": hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()}
                return raw, actual
        raise AuthorityUnavailable()

    def check_live(self):
        if self.closed or not self.handles or not self.registry or self.policy is None:
            raise AuthorityUnavailable()


def _machine(origin, value, *, missing=False):
    import winreg
    for suffix in ("", r"\InvestorIntelligence", r"\InvestorIntelligence\GuidanceProtected"):
        path = "SOFTWARE" + suffix
        key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, path, 0, winreg.KEY_READ | winreg.KEY_WOW64_64KEY)
        origin.registry.append(key)
        _security(origin.apis, int(key), 4, ancestor=bool(suffix != r"\InvestorIntelligence\GuidanceProtected"))
    try:
        text, kind = winreg.QueryValueEx(origin.registry[-1], value)
    except FileNotFoundError:
        if missing:
            return None
        raise AuthorityUnavailable() from None
    if kind != winreg.REG_SZ:
        raise AuthorityUnavailable()
    return _json(text)


def _policy(data):
    if type(data) is not dict or set(data) != {"schema", "release_id", "files", "runtime_sid"} or data["schema"] != "guidance-protected-approval-v1":
        raise AuthorityUnavailable()
    if not re.fullmatch("[0-9a-f]{64}", str(data["release_id"])) or not re.fullmatch(r"S-1-5-21-(?:\d+-){3}\d+", str(data["runtime_sid"])):
        raise AuthorityUnavailable()
    files = data["files"]
    if type(files) is not dict or not REQUIRED_FILES <= files.keys() or len(files) > 4096:
        raise AuthorityUnavailable()
    for name, digest in files.items():
        if (type(name) is not str or len(name) > 240 or "\\" in name or ":" in name or name.startswith("/")
                or any(not re.fullmatch(r"[A-Za-z0-9_-][A-Za-z0-9._-]*", p) or p.endswith(".") for p in name.split("/"))
                or name.lower().endswith((".pth", ".pyc")) or not re.fullmatch("[0-9a-f]{64}", str(digest))):
            raise AuthorityUnavailable()
    if len({n.casefold() for n in files}) != len(files):
        raise AuthorityUnavailable()
    return data


def _token(origin, *, issuer):
    c, w, k, a = origin.apis
    token = w.HANDLE()
    if not a.OpenProcessToken(k.GetCurrentProcess(), 8, c.byref(token)):
        raise AuthorityUnavailable()
    origin.handles.append(token.value)
    got, user = w.DWORD(), c.create_string_buffer(512)
    if not a.GetTokenInformation(token, 1, user, 512, c.byref(got)):
        raise AuthorityUnavailable()
    principal = _sid(origin.apis, c.c_void_p.from_buffer(user))
    elevation = w.DWORD()
    if not a.GetTokenInformation(token, 20, c.byref(elevation), 4, c.byref(got)):
        raise AuthorityUnavailable()
    # Full elevated token plus actual Administrators membership, not admin=True.
    shell = c.WinDLL("shell32.dll", winmode=0x800)
    shell.IsUserAnAdmin.restype = w.BOOL
    if issuer:
        if elevation.value != 1 or not shell.IsUserAnAdmin():
            raise AuthorityUnavailable()
    elif principal != origin.policy["runtime_sid"] or elevation.value != 0 or shell.IsUserAnAdmin():
        raise AuthorityUnavailable()


def controlled_origin(*, issuer=False):
    origin = _HeldOrigin()
    try:
        origin.policy = _policy(_machine(origin, "Approval"))
        origin.installation = _machine(origin, "Installation")
        policy = origin.policy
        root = CODE_BASE / policy["release_id"]
        if origin.installation != {"schema": "guidance-protected-install-v1", "release_id": policy["release_id"]}:
            raise AuthorityUnavailable()
        _token(origin, issuer=issuer)
        if (not sys.flags.isolated or not sys.flags.no_site or not sys.flags.dont_write_bytecode
                or Path(sys.executable) != root / "Python" / "python.exe" or Path(__file__) != root / "scripts" / "revenue_guidance_provisioner.py"):
            raise AuthorityUnavailable()
        origin.ancestors(root)
        origin.hold(root, directory=True)
        found = set()
        total = 0
        for directory, dirs, leaves in os.walk(root, followlinks=False):
            for n in dirs:
                origin.hold(Path(directory) / n, directory=True)
            for n in leaves:
                path = Path(directory) / n
                name = path.relative_to(root).as_posix()
                if name not in policy["files"]:
                    raise AuthorityUnavailable()
                h, _ = origin.hold(path)
                raw = origin.read(h)
                total += len(raw)
                if total > 512 * 1024 * 1024 or hashlib.sha256(raw).hexdigest() != policy["files"][name]:
                    raise AuthorityUnavailable()
                found.add(name)
                if name.startswith(("scripts/", "config/")):
                    origin.files[name] = raw
        if found != set(policy["files"]):
            raise AuthorityUnavailable()
        for path in sys.path:
            p = Path(path)
            if not p.is_absolute() or (p != root and root not in p.parents):
                raise AuthorityUnavailable()
        for module in tuple(sys.modules.values()):
            path = getattr(module, "__file__", None)
            if path and str(path) not in ("<frozen>",):
                p = Path(path)
                if not p.is_absolute() or root not in p.parents:
                    raise AuthorityUnavailable()
        origin.enrollment = _machine(origin, "Enrollment", missing=True)
        origin.check_live()
        return origin
    except BaseException:
        origin.close()
        raise AuthorityUnavailable() from None


def anchor_to_data(anchor):
    def oid(value):
        return {"volume_serial": value.volume_serial, "file_id": value.file_id.hex()}
    return {"schema_version": anchor.schema_version, "bootstrap_id": anchor.bootstrap_id, "volume_guid": anchor.volume_guid,
            "volume_root_identity": oid(anchor.volume_root_identity),
            "root_components": [[n, oid(i)] for n, i in anchor.root_components],
            "coordination_identity": oid(anchor.coordination_identity), "journal_identity": oid(anchor.journal_identity),
            "journal_format_version": anchor.journal_format_version, "state_required": anchor.state_required,
            "control_identity": oid(anchor.control_identity), "b1_identity": oid(anchor.b1_identity),
            "input_digests": dict(anchor.input_digests)}


def anchor_from_data(data):
    import revenue_guidance_storage as storage
    if type(data) is not dict or set(data) != {"schema_version", "bootstrap_id", "volume_guid", "volume_root_identity",
            "root_components", "coordination_identity", "journal_identity", "journal_format_version", "state_required",
            "control_identity", "b1_identity", "input_digests"}:
        raise AuthorityUnavailable()
    def oid(value):
        if type(value) is not dict or set(value) != {"volume_serial", "file_id"} or not re.fullmatch("[0-9a-f]{32}", str(value["file_id"])):
            raise AuthorityUnavailable()
        return storage.ObjectIdentity(value["volume_serial"], bytes.fromhex(value["file_id"]))
    anchor = storage.RootAnchor(data["schema_version"], data["bootstrap_id"], data["volume_guid"], oid(data["volume_root_identity"]),
            tuple((n, oid(i)) for n, i in data["root_components"]), oid(data["coordination_identity"]), oid(data["journal_identity"]),
            data["journal_format_version"], data["state_required"], oid(data["control_identity"]), oid(data["b1_identity"]),
            tuple(sorted(data["input_digests"].items())))
    return storage._validate_anchor_data(anchor)


def _enrolled(origin):
    record = origin.enrollment
    if type(record) is not dict or set(record) != {"schema", "release_id", "anchor", "initial_revision"} or record["schema"] != "guidance-protected-enrollment-v1":
        raise AuthorityUnavailable()
    if record["release_id"] != origin.policy["release_id"] or not re.fullmatch("gir1:[0-9a-f]{64}", str(record["initial_revision"])):
        raise AuthorityUnavailable()
    anchor = anchor_from_data(record["anchor"])
    if tuple(n for n, _ in anchor.root_components) != ("ProgramData", "InvestorIntelligenceGuidance", anchor.bootstrap_id):
        raise AuthorityUnavailable()
    bindings = {"config.json": "config/system-bottleneck-explosion-v1.json", "profiles.json": "config/revenue-guidance-extraction-profiles-v1.json",
                "registry.json": "config/revenue-guidance-v1.json", "approval.json": "config/revenue-guidance-approval-v1.json"}
    bindings.update({n: "scripts/" + n for n in CONTROL_INPUTS if n.endswith(".py")})
    if dict(anchor.input_digests) != {n: origin.policy["files"][p] for n, p in bindings.items()}:
        raise AuthorityUnavailable()
    root = DATA_BASE / anchor.bootstrap_id
    origin.ancestors(root)
    c, _, k, _ = origin.apis
    volume = c.create_unicode_buffer(64)
    if not k.GetVolumeNameForVolumeMountPointW("C:\\", volume, 64) or volume.value != "\\\\?\\Volume" + anchor.volume_guid + "\\":
        raise AuthorityUnavailable()
    _, actual_volume = origin.hold(Path("C:\\"), directory=True, ancestor=True)
    if actual_volume != (anchor.volume_root_identity.volume_serial, anchor.volume_root_identity.file_id):
        raise AuthorityUnavailable()
    path = Path("C:\\")
    for name, identity in anchor.root_components:
        path = path / name
        _, actual_part = origin.hold(path, directory=True, ancestor=True)
        if actual_part != (identity.volume_serial, identity.file_id):
            raise AuthorityUnavailable()
    _, actual = origin.hold(root, directory=True)
    if actual != (anchor.root_components[-1][1].volume_serial, anchor.root_components[-1][1].file_id):
        raise AuthorityUnavailable()
    if set(os.listdir(root)) != {"control", "b1"} or set(os.listdir(root / "control")) != CONTROL_INPUTS | {"coordination.lock", "journal.dat"}:
        raise AuthorityUnavailable()
    _, control = origin.hold(root / "control", directory=True)
    # Only DELETE_CHILD is admitted on the enrolled B1 subroot; its own DELETE,
    # WRITE_DAC/WRITE_OWNER remain forbidden. Inherit-only leaf DELETE is not
    # an effective grant to this held protected directory.
    _, b1 = origin.hold(root / "b1", directory=True, runtime=origin.policy["runtime_sid"], allowed=0x1ff)
    for actual_id, expected in ((control, anchor.control_identity), (b1, anchor.b1_identity)):
        if actual_id != (expected.volume_serial, expected.file_id):
            raise AuthorityUnavailable()
    for name in CONTROL_INPUTS:
        handle, _ = origin.hold(root / "control" / name)
        if hashlib.sha256(origin.read(handle, 8 * 1024 * 1024)).hexdigest() != dict(anchor.input_digests)[name]:
            raise AuthorityUnavailable()
    for name, identity in (("coordination.lock", anchor.coordination_identity), ("journal.dat", anchor.journal_identity)):
        handle, actual = origin.hold(root / "control" / name, runtime=origin.policy["runtime_sid"], allowed=0x19f)
        origin._p2_admission_conflicts.append({"role": name, "handle": handle, "attempted": False, "closed": False})
        if actual != (identity.volume_serial, identity.file_id):
            raise AuthorityUnavailable()
    return anchor


def retain_live_owner_custody(origin):
    """Failure-only lifetime rooting; does not authorize acquisition or cleanup."""
    global _unsettled_origin
    if origin is None or origin is _unsettled_origin:
        return
    if type(origin) is not _HeldOrigin or origin.live_owner_handle is None:
        raise AuthorityUnavailable()
    origin._custody_next_origin = _unsettled_origin
    _unsettled_origin = origin


def acquire_live_owner():
    """Fresh protected enrollment FIRST; bounded cross-process exclusion BEFORE P2.

    The named kernel object is only a concurrency interlock, NEVER authority.
    Its name is derived from the actual independently admitted enrolled domain,
    stable across code upgrades/sessions. Existing objects (including abandoned
    ones) are refused without waiting, repair, replacement or PID/marker probes.
    The real origin owns the returned handle before any subsequent handoff.
    """
    global _unsettled_origin
    origin = controlled_origin()
    creation_pending = False
    try:
        anchor = _enrolled(origin)
        domain = {"volume": anchor.volume_guid, "bootstrap": anchor.bootstrap_id,
                  "root": anchor.root_components[-1][1].file_id.hex(),
                  "coordination": anchor.coordination_identity.file_id.hex()}
        name = "Global\\InvestorIntelligenceGuidanceLiveOwner-" + hashlib.sha256(
            json.dumps(domain, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        c, w, k, _ = origin.apis
        k.CreateMutexW.argtypes = [c.c_void_p, w.BOOL, w.LPCWSTR]
        k.CreateMutexW.restype = w.HANDLE
        k.ReleaseMutex.argtypes = [w.HANDLE]
        k.ReleaseMutex.restype = w.BOOL
        k.GetLastError.restype = w.DWORD
        # Submission/return interruption is also retained, even before a handle
        # can be observed. No undocumented creation retry/automatic repair.
        creation_pending = True
        _unsettled_origin = origin
        handle = k.CreateMutexW(None, True, name)
        error = k.GetLastError()  # capture the creation outcome before other calls
        origin.live_owner_handle = handle  # retain actual return BEFORE classification
        if handle in (None, 0, c.c_void_p(-1).value):
            origin.live_owner_handle = None  # documented failed creation: no handle
            creation_pending = False
            _unsettled_origin = None
            raise AuthorityUnavailable()
        origin.live_owner_owned = error != 183  # existing initial-owner flag was ignored
        creation_pending = False
        _unsettled_origin = None  # creation classified; original origin still holds the owner
        if error == 183:
            raise AuthorityUnavailable()  # includes foreign/precreated/abandoned objects
        origin.release_p2_admission_conflicts()  # confirmed retire READ/share1 before P2 WRITE/share0
        origin.check_live()  # protected root/code/registry custody remains live; no guard transfer/release
        return origin
    except BaseException:
        if creation_pending or origin._p2_admission_phase == "RELEASING":
            # Preserve any linked earlier uncertainty AND the SAME guard. No
            # second close attempt or guard disposal to manufacture P2 liveness.
            if _unsettled_origin is not origin:
                origin._custody_next_origin = _unsettled_origin
                _unsettled_origin = origin
        else:
            origin.close()  # only classified/confirmed admission; guard still releases LAST
        raise AuthorityUnavailable() from None


def require_anchor(candidate):
    # EACH acquisition reads its OWN protected record; no authorized-object set.
    origin = controlled_origin()
    try:
        approved = _enrolled(origin)
        if anchor_to_data(candidate) != anchor_to_data(approved):
            raise AuthorityUnavailable()
        return anchor_from_data(anchor_to_data(approved))
    finally:
        origin.close()


def enrolled_anchor():
    origin = controlled_origin()
    try:
        return _enrolled(origin)
    finally:
        origin.close()


def require_issuer():
    origin = controlled_origin(issuer=True)
    try:
        if origin.enrollment is not None:
            raise AuthorityUnavailable()  # no repair/re-enrollment of arbitrary existing storage
        origin.ancestors(DATA_BASE)
        origin.hold(DATA_BASE, directory=True)
        return origin
    except BaseException:
        origin.close()
        raise


def require_live_issuer(origin):
    """Guarded issuer IO still needs REAL elevated protected origin, not a class.

    A medium runtime cannot manufacture issuer custody through __new__/fields.
    No injected verifier or stored authorized-caller set; fresh HKLM/principal and
    held independently approved executable/bootstrap are consulted here.
    This is not a sandbox against a privileged malicious interpreter/admin.
    """
    if type(origin) is not _HeldOrigin:
        raise AuthorityUnavailable()
    _HeldOrigin.check_live(origin)
    current = _HeldOrigin()
    try:
        current.policy = _policy(_machine(current, "Approval"))
        _token(current, issuer=True)
        if current.policy != origin.policy:
            raise AuthorityUnavailable()
        root = CODE_BASE / current.policy["release_id"]
        if (not sys.flags.isolated or not sys.flags.no_site or not sys.flags.dont_write_bytecode
                or Path(sys.executable) != root / "Python" / "python.exe"
                or Path(__file__) != root / "scripts" / "revenue_guidance_provisioner.py"):
            raise AuthorityUnavailable()
        current.ancestors(root)
        for name in ("Python/python.exe", "scripts/revenue_guidance_bootstrap.py"):
            current.ancestors(root / name)
            handle, _ = current.hold(root / name)
            if hashlib.sha256(current.read(handle)).hexdigest() != current.policy["files"][name]:
                raise AuthorityUnavailable()
        for module in tuple(sys.modules.values()):
            name = getattr(module, "__file__", None)
            if name and str(name) != "<frozen>" and root not in Path(name).parents:
                raise AuthorityUnavailable()
    finally:
        current.close()


def publish_enrollment(origin, anchor, revision):
    import winreg
    origin.check_live()
    # Fresh independent consultation before the LAST protected publication.
    current = controlled_origin(issuer=True)
    try:
        if current.enrollment is not None or current.policy != origin.policy:
            raise AuthorityUnavailable()
        key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, AUTHORITY_KEY, 0,
                             winreg.KEY_READ | winreg.KEY_SET_VALUE | winreg.KEY_WOW64_64KEY)
        current.registry.append(key)
        _security(current.apis, int(key), 4)
        record = {"schema": "guidance-protected-enrollment-v1", "release_id": origin.policy["release_id"],
                  "anchor": anchor_to_data(anchor), "initial_revision": revision}
        # Independently measure protected identities/ACL/bytes again, after native
        # close and before last publication. A class/digest alone cannot enroll.
        current.enrollment = record
        _enrolled(current)
        journal = current.read(current.handles[-1], 131072)
        import revenue_guidance_storage as storage
        sequences = []
        for offset in (0, storage.JOURNAL_SLOT_SIZE):
            import struct
            block = journal[offset:offset + storage.JOURNAL_SLOT_SIZE]
            if len(block) != storage.JOURNAL_SLOT_SIZE:
                raise AuthorityUnavailable()
            magic, fmt, hs, seq, length, reserved, digest = struct.unpack("<8sIIQII32s", block[:64])
            payload = block[64:64 + length]
            if (magic != b"GJSLT001" or fmt != 1 or hs != 64 or reserved or length > 8192
                    or hashlib.sha256(payload).digest() != digest or any(block[64 + length:])):
                raise AuthorityUnavailable()
            envelope = storage._safe_json_loads(payload.decode("utf-8"))
            if set(envelope) != {"schema", "bootstrap_id", "sequence", "state"} or envelope["schema"] != "guidance-provider-storage-v1" or envelope["bootstrap_id"] != anchor.bootstrap_id or envelope["sequence"] != seq:
                raise AuthorityUnavailable()
            state = storage._validate_p1_state(envelope["state"])
            if state != {"Schema": "guidance-provider-journal-v1", "StateRequired": True,
                         "InputRevision": revision, "PendingRevision": revision, "Intent": None}:
                raise AuthorityUnavailable()
            sequences.append(seq)
        if sequences != [0, 1]:
            raise AuthorityUnavailable()
        text = json.dumps(record, sort_keys=True, separators=(",", ":"), allow_nan=False)
        winreg.SetValueEx(key, "Enrollment", 0, winreg.REG_SZ, text)
        winreg.FlushKey(key)
        observed, kind = winreg.QueryValueEx(key, "Enrollment")
        if kind != winreg.REG_SZ or observed != text:
            raise AuthorityUnavailable()
    finally:
        current.close()
