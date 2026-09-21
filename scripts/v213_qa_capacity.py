"""Development-only cooperative QA capacity evidence; no machine-wide GPU isolation claim."""
import hashlib
import json
import math
import os
import re
import secrets
import stat
import subprocess
import sys
import time
import ctypes
import ctypes.wintypes
from datetime import datetime, timezone
from pathlib import Path


class CapacityError(RuntimeError):
    pass


def canonical_hash(value):
    try:
        raw = json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise CapacityError(str(exc)) from exc
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def process_identity(pid):
    if isinstance(pid, bool) or not isinstance(pid, int) or pid <= 0:
        raise CapacityError("pid must be a positive int, not bool")
    if sys.platform == "win32":
        k = ctypes.WinDLL("kernel32", use_last_error=True)
        k.OpenProcess.argtypes = [ctypes.wintypes.DWORD, ctypes.wintypes.BOOL, ctypes.wintypes.DWORD]
        k.OpenProcess.restype = ctypes.wintypes.HANDLE
        k.GetExitCodeProcess.argtypes = [ctypes.wintypes.HANDLE, ctypes.POINTER(ctypes.wintypes.DWORD)]
        k.GetExitCodeProcess.restype = ctypes.wintypes.BOOL
        k.GetProcessTimes.argtypes = [ctypes.wintypes.HANDLE] + [ctypes.POINTER(ctypes.wintypes.FILETIME)] * 4
        k.GetProcessTimes.restype = ctypes.wintypes.BOOL
        k.CloseHandle.argtypes = [ctypes.wintypes.HANDLE]
        k.CloseHandle.restype = ctypes.wintypes.BOOL
        h = k.OpenProcess(0x1000, False, pid)
        if not h:
            e = ctypes.get_last_error()
            if e == 87:
                return None
            raise CapacityError(f"OpenProcess failed: error {e}")
        try:
            exit_code = ctypes.wintypes.DWORD()
            ok = k.GetExitCodeProcess(h, ctypes.byref(exit_code))
            if not ok:
                raise CapacityError(f"GetExitCodeProcess failed: error {ctypes.get_last_error()}")
            if exit_code.value != 259:  # STILL_ACTIVE
                return None  # conclusively dead
            fts = [ctypes.wintypes.FILETIME() for _ in range(4)]
            ok = k.GetProcessTimes(h, ctypes.byref(fts[0]), ctypes.byref(fts[1]), ctypes.byref(fts[2]), ctypes.byref(fts[3]))
            if not ok:
                raise CapacityError(f"GetProcessTimes failed: error {ctypes.get_last_error()}")
            return f"{fts[0].dwHighDateTime:08x}{fts[0].dwLowDateTime:08x}"
        finally:
            k.CloseHandle(h)
    try:
        with open(f"/proc/{pid}/stat", "r") as f:
            content = f.read()
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise CapacityError(str(exc)) from exc
    try:
        lp = content.rfind(")")
        if lp == -1:
            raise ValueError("malformed stat: no closing paren")
        fields = content[lp + 1:].split()
        if len(fields) < 20:
            raise ValueError("malformed stat: insufficient fields")
        return f"starttime={fields[19]}"
    except ValueError as exc:
        raise CapacityError(str(exc)) from exc


# ---------------------------------------------------------------------------
# _Guard and secure path validation (Slice C)
# ---------------------------------------------------------------------------

def _is_reparse(st):
    """True if lstat reports a Windows reparse point."""
    if sys.platform == "win32":
        try:
            return bool(st.st_file_attributes & 0x200)  # FILE_ATTRIBUTE_REPARSE_POINT
        except AttributeError:
            return False
    return False


def _assert_dir(st, path):
    if stat.S_ISLNK(st.st_mode):
        raise CapacityError(f"ancestor is symlink: {path}")
    if _is_reparse(st):
        raise CapacityError(f"ancestor is reparse point: {path}")
    if not stat.S_ISDIR(st.st_mode):
        raise CapacityError(f"ancestor is not a directory: {path}")


def _assert_guard(st, path):
    if stat.S_ISLNK(st.st_mode):
        raise CapacityError(f"guard is symlink: {path}")
    if _is_reparse(st):
        raise CapacityError(f"guard is reparse point: {path}")
    if not stat.S_ISREG(st.st_mode):
        raise CapacityError(f"guard is not a regular file: {path}")
    if st.st_nlink != 1:
        raise CapacityError(f"guard has nlink != 1: {path}")


def _validate_ancestors(path):
    """lstat each existing ancestor of path; reject symlink/reparse/nondir."""
    for parent in path.parents:
        try:
            st = os.lstat(os.fspath(parent))
        except FileNotFoundError:
            continue
        _assert_dir(st, parent)


def _secure_path(path):
    """Canonicalize path to absolute form, rejecting any '..' traversal.

    Accepts str or Path. Returns an absolute Path. Reusable for future
    metadata checks; callers still validate existing bytes separately
    via _validate_ancestors.
    """
    if isinstance(path, str):
        path = Path(path)
    if ".." in path.parts:
        raise CapacityError("path must not contain '..' traversal")
    return Path(os.path.abspath(os.fspath(path)))


class _Guard:
    """Persistent byte-range/flock guard for a canonical root."""

    def __init__(self, root):
        self.root = _secure_path(root)
        self.guardpath = self.root / "guard"
        self.fd = None
        self._identity = None  # immutable (dev, ino) captured on acquire

    def acquire(self):
        if self.fd is not None:
            raise CapacityError("guard already held (reentrant acquire)")
        _validate_ancestors(self.root)
        try:
            os.makedirs(os.fspath(self.root), exist_ok=True)
        except OSError as exc:
            raise CapacityError(f"mkdir root failed: {exc}") from exc
        _validate_ancestors(self.guardpath)
        fd = None
        try:
            try:
                gstat = os.lstat(os.fspath(self.guardpath))
            except FileNotFoundError:
                gstat = None
            if gstat is not None:
                _assert_guard(gstat, self.guardpath)
                fd = os.open(os.fspath(self.guardpath), os.O_RDWR)
                fstat = os.fstat(fd)
                if (fstat.st_dev, fstat.st_ino) != (gstat.st_dev, gstat.st_ino):
                    raise CapacityError("guard fstat/lstat identity mismatch")
            else:
                # Fresh root: exclusive creation
                try:
                    fd = os.open(
                        os.fspath(self.guardpath),
                        os.O_RDWR | os.O_CREAT | os.O_EXCL,
                        0o644,
                    )
                except FileExistsError:
                    # Race: another holder created it between lstat and open
                    gstat = os.lstat(os.fspath(self.guardpath))
                    _assert_guard(gstat, self.guardpath)
                    fd = os.open(os.fspath(self.guardpath), os.O_RDWR)
                    fstat = os.fstat(fd)
                    if (fstat.st_dev, fstat.st_ino) != (gstat.st_dev, gstat.st_ino):
                        raise CapacityError("guard fstat/lstat identity mismatch")
                else:
                    fstat = os.fstat(fd)
                _assert_guard(fstat, self.guardpath)
            # Lock before any byte write that could alter another holder
            os.lseek(fd, 0, os.SEEK_SET)
            if sys.platform == "win32":
                import msvcrt
                msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            # Ensure at least 1 byte for range lock
            if os.fstat(fd).st_size == 0:
                os.write(fd, b"\x00")
            self._identity = (fstat.st_dev, fstat.st_ino)
            self.fd = fd
        except CapacityError:
            if fd is not None:
                try:
                    os.close(fd)
                except OSError:
                    pass
            raise
        except Exception as exc:
            if fd is not None:
                try:
                    os.close(fd)
                except OSError:
                    pass
            raise CapacityError(f"guard acquire failed: {exc}") from exc

    def check(self):
        if self.fd is None:
            raise CapacityError("guard not held")
        _validate_ancestors(self.guardpath)
        gstat = os.lstat(os.fspath(self.guardpath))
        if self._identity is not None:
            if (gstat.st_dev, gstat.st_ino) != self._identity:
                raise CapacityError("guard identity changed")
        _assert_guard(gstat, self.guardpath)

    def close(self):
        if self.fd is None:
            return
        fd = self.fd
        try:
            if sys.platform == "win32":
                import msvcrt
                os.lseek(fd, 0, os.SEEK_SET)
                msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(fd, fcntl.LOCK_UN)
        finally:
            os.close(fd)
            self.fd = None


# ---------------------------------------------------------------------------
# Lease lifecycle (Slice D): CapacityLease + recover_dead
# ---------------------------------------------------------------------------

APPROVED_MODEL = "Qwen3.8-27B-EXL3-5.5bpw-v2"
APPROVED_CONTEXT = 262144
_SOURCE_HEAD_RE = re.compile(r"^[0-9a-f]{40}$")


def _validate_ttl(ttl_s):
    if isinstance(ttl_s, bool) or not isinstance(ttl_s, (int, float)):
        raise CapacityError("ttl_s must be a finite positive number, not bool")
    if not math.isfinite(ttl_s) or ttl_s <= 0:
        raise CapacityError("ttl_s must be a finite positive number")
    return ttl_s


def _validate_binding(binding):
    def _pos_int(v):
        return not isinstance(v, bool) and isinstance(v, int) and v > 0
    def _nstr(v):
        return isinstance(v, str) and v != ""
    def _h64(v):
        return isinstance(v, str) and len(v) == 64 and all(c in "0123456789abcdef" for c in v)
    if not isinstance(binding, dict):
        raise CapacityError("binding must be a dict")
    sh = binding.get("source_head")
    if not isinstance(sh, str) or not _SOURCE_HEAD_RE.match(sh):
        raise CapacityError("binding source_head must be 40 lowercase hex")
    if binding.get("model_id") != APPROVED_MODEL:
        raise CapacityError("binding model_id must be the approved model")
    ctx = binding.get("context")
    if isinstance(ctx, bool) or not isinstance(ctx, int) or ctx != APPROVED_CONTEXT:
        raise CapacityError("binding context must be int 262144, not bool")
    svc = binding.get("service")
    if not isinstance(svc, dict):
        raise CapacityError("binding service must be a dict")
    if not _pos_int(svc.get("pid")):
        raise CapacityError("binding service pid must be a positive int")
    if not _pos_int(svc.get("parent_pid")):
        raise CapacityError("binding service parent_pid must be a positive int")
    if not _nstr(svc.get("created")):
        raise CapacityError("binding service created (birth) must be a non-empty str")
    if not _nstr(svc.get("parent_created")):
        raise CapacityError("binding service parent_created (birth) must be a non-empty str")
    for key in ("image_sha256", "parent_image_sha256", "main_sha256"):
        if not _h64(svc.get(key)):
            raise CapacityError(f"binding service {key} must be a 64-char lowercase hex hash")
    if not _nstr(binding.get("gpu_uuid")):
        raise CapacityError("binding gpu_uuid must be a non-empty str")
    clients = binding.get("allowed_clients")
    if not isinstance(clients, list):
        raise CapacityError("binding allowed_clients must be a list")
    for i, c in enumerate(clients):
        if not isinstance(c, dict):
            raise CapacityError(f"binding allowed_clients[{i}] must be a dict")
        if not _pos_int(c.get("pid")):
            raise CapacityError(f"binding allowed_clients[{i}].pid must be a positive int")
        if not _nstr(c.get("created")):
            raise CapacityError(f"binding allowed_clients[{i}].created must be a non-empty str")
    names = binding.get("qwen_worker_names")
    if not isinstance(names, list):
        raise CapacityError("binding qwen_worker_names must be a list")
    for i, n in enumerate(names):
        if not _nstr(n):
            raise CapacityError(f"binding qwen_worker_names[{i}] must be a non-empty str")
    ma = binding.get("model_artifacts")
    if not isinstance(ma, dict):
        raise CapacityError("binding model_artifacts must be a dict")
    for key in ("config_sha256", "weights_sha256"):
        v = ma.get(key)
        if v is not None and not _h64(v):
            raise CapacityError(f"binding model_artifacts.{key} must be None or 64-char hex")
    if not _nstr(ma.get("availability")):
        raise CapacityError("binding model_artifacts.availability must be a non-empty str")
    return binding


def _fsync_dir(path):
    if sys.platform == "win32":
        return
    fd = os.open(os.fspath(path), os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _read_owner_bytes(path):
    """Read owner metadata bytes; reject symlink/reparse/hardlink/alias."""
    try:
        st = os.lstat(os.fspath(path))
    except FileNotFoundError:
        raise CapacityError("owner.json disappeared")
    if stat.S_ISLNK(st.st_mode) or _is_reparse(st):
        raise CapacityError("owner.json is a symlink/reparse point")
    if not stat.S_ISREG(st.st_mode):
        raise CapacityError("owner.json is not a regular file")
    if st.st_nlink != 1:
        raise CapacityError("owner.json is a hardlink")
    fd = os.open(os.fspath(path), os.O_RDONLY)
    try:
        fstat = os.fstat(fd)
        if (fstat.st_dev, fstat.st_ino) != (st.st_dev, st.st_ino):
            raise CapacityError("owner.json fstat/lstat identity mismatch")
        data = b""
        while True:
            chunk = os.read(fd, 65536)
            if not chunk:
                break
            data += chunk
    finally:
        os.close(fd)
    return data, fstat


def _unique_archive(adir, name_hint, payload):
    """Write payload to a unique path under adir; never overwrite a receipt."""
    os.makedirs(os.fspath(adir), exist_ok=True)
    base = f"{name_hint}-{secrets.token_hex(8)}"
    for _ in range(8):
        target = adir / f"{base}.json"
        try:
            fd = os.open(os.fspath(target), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
        except FileExistsError:
            base = f"{name_hint}-{secrets.token_hex(8)}"
            continue
        try:
            os.write(fd, payload)
            os.fsync(fd)
        finally:
            os.close(fd)
        _fsync_dir(adir)
        return target
    raise CapacityError("could not allocate a unique archive path")


def _probe_state(process_probe, pid, owner_created):
    """Classify a probe result as 'dead' or 'live'; raise on unknown."""
    try:
        result = process_probe(pid)
    except CapacityError:
        raise
    except Exception as exc:
        raise CapacityError(f"process probe unknown: {exc}") from exc
    if result is None:
        return "dead"
    if isinstance(result, str):
        if not result:
            raise CapacityError("process probe returned empty string; unknown")
        if result == owner_created:
            return "live"
        return "dead"
    raise CapacityError("process probe returned unexpected type; unknown")


class CapacityLease:
    def __init__(self, root, binding, ttl_s=60, process_probe=process_identity):
        self.root = _secure_path(root)
        self.ttl_s = _validate_ttl(ttl_s)
        self.binding = json.loads(json.dumps(binding))
        _validate_binding(self.binding)
        self.process_probe = process_probe
        self.guard = _Guard(self.root)
        self.metadata_path = self.root / "owner.json"
        self._nonce = None
        self._meta_sha = None
        self._meta_ino = None
        self._pid = None
        self._deadline = None
        self._held = False

    def _build_metadata(self):
        pid = os.getpid()
        try:
            birth = self.process_probe(pid)
        except CapacityError:
            raise CapacityError("cannot determine owner process birth")
        if birth is None:
            raise CapacityError("process_probe returned None; cannot verify owner birth")
        if not isinstance(birth, (str, dict)):
            raise CapacityError("process_probe returned invalid creation marker")
        return {
            "nonce": secrets.token_hex(16),
            "run_id": secrets.token_hex(16),
            "pid": pid,
            "created": birth,
            "created_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "ttl_s": self.ttl_s,
            "source_head": self.binding["source_head"],
            "model_id": self.binding["model_id"],
            "context": self.binding["context"],
            "service": self.binding["service"],
            "binding": self.binding,
        }

    def _dumps(self, meta):
        return json.dumps(meta, sort_keys=True, separators=(",", ":"),
                          ensure_ascii=False, allow_nan=False).encode("utf-8")

    def _publish(self, raw):
        tmp = self.root / (".owner-tmp-" + secrets.token_hex(8))
        fd = os.open(os.fspath(tmp), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
        try:
            try:
                os.write(fd, raw)
                os.fsync(fd)
            finally:
                os.close(fd)
            _validate_ancestors(self.metadata_path)
            # Refuse to overwrite an existing owner.json (foreign owner)
            try:
                os.lstat(os.fspath(self.metadata_path))
                raise CapacityError("owner.json already exists; refusing to overwrite foreign owner")
            except FileNotFoundError:
                pass
            os.replace(os.fspath(tmp), os.fspath(self.metadata_path))
            _fsync_dir(self.root)
        except BaseException:
            try:
                os.unlink(os.fspath(tmp))
            except OSError:
                pass
            raise

    def acquire(self):
        self.guard.acquire()
        try:
            try:
                ost = os.lstat(os.fspath(self.metadata_path))
            except FileNotFoundError:
                ost = None
            if ost is not None:
                raise CapacityError("existing owner.json residual; acquire refused")
            meta = self._build_metadata()
            raw = self._dumps(meta)
            self._publish(raw)
            st = os.lstat(os.fspath(self.metadata_path))
            self._nonce = meta["nonce"]
            self._meta_sha = hashlib.sha256(raw).hexdigest()
            self._meta_ino = st.st_ino
            self._pid = meta["pid"]
            self._deadline = time.monotonic() + self.ttl_s
            self._held = True
            return meta
        except BaseException:
            self.guard.close()
            self._held = False
            raise

    def check(self, nonce):
        if not self._held:
            raise CapacityError("lease not held")
        if nonce != self._nonce:
            raise CapacityError("nonce mismatch")
        self.guard.check()
        data, fstat = _read_owner_bytes(self.metadata_path)
        if fstat.st_ino != self._meta_ino:
            raise CapacityError("owner.json inode changed")
        if hashlib.sha256(data).hexdigest() != self._meta_sha:
            raise CapacityError("owner.json byte digest changed")
        try:
            meta = json.loads(data.decode("utf-8"))
        except (ValueError, UnicodeDecodeError) as exc:
            raise CapacityError(f"owner.json corrupt: {exc}") from exc
        if meta.get("nonce") != self._nonce:
            raise CapacityError("owner.json nonce mismatch")
        if meta.get("pid") != self._pid:
            raise CapacityError("owner.json owner pid mismatch")
        if meta.get("binding") != self.binding:
            raise CapacityError("owner.json binding mismatch")
        if time.monotonic() >= self._deadline:
            raise CapacityError("lease TTL expired")
        # Verify current PID and process creation marker still match owner
        cur_pid = os.getpid()
        if cur_pid != self._pid:
            raise CapacityError("current PID differs from owner PID")
        try:
            cur_birth = self.process_probe(cur_pid)
        except CapacityError:
            raise CapacityError("cannot verify owner process birth during check")
        if cur_birth is None:
            raise CapacityError("process_probe returned None during check")
        stored_birth = meta.get("created")
        # Normalize both to comparable values
        if isinstance(cur_birth, dict):
            cur_birth_val = cur_birth.get("created")
        else:
            cur_birth_val = cur_birth
        if isinstance(stored_birth, dict):
            stored_birth_val = stored_birth.get("created")
        else:
            stored_birth_val = stored_birth
        if cur_birth_val != stored_birth_val:
            raise CapacityError("process creation marker changed since acquire")
        return meta

    def release(self, nonce):
        self.check(nonce)
        data, fstat = _read_owner_bytes(self.metadata_path)
        digest = hashlib.sha256(data).hexdigest()
        try:
            meta = json.loads(data.decode("utf-8"))
        except (ValueError, UnicodeDecodeError) as exc:
            raise CapacityError(f"owner.json corrupt: {exc}") from exc
        event = {
            "event": "release",
            "owner": meta.get("pid"),
            "nonce": nonce,
            "hash": digest,
            "released_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        }
        payload = json.dumps({"metadata": meta, "release": event},
                             sort_keys=True, separators=(",", ":"),
                             ensure_ascii=False, allow_nan=False).encode("utf-8")
        archive = _unique_archive(self.root / "archive", f"release-{nonce}", payload)
        event["archive"] = str(archive)
        try:
            os.unlink(os.fspath(self.metadata_path))
        except FileNotFoundError:
            pass
        _fsync_dir(self.root)
        self.guard.close()
        self._held = False
        return event

    def close(self):
        self.guard.close()
        self._held = False


def recover_dead(root, expected_nonce, expected_metadata_sha256,
                 process_probe=process_identity):
    root = _secure_path(root)
    guard = _Guard(root)
    metadata_path = root / "owner.json"
    guard.acquire()
    try:
        data, fstat = _read_owner_bytes(metadata_path)
        if hashlib.sha256(data).hexdigest() != expected_metadata_sha256:
            raise CapacityError("owner.json digest does not match expected")
        try:
            meta = json.loads(data.decode("utf-8"))
        except (ValueError, UnicodeDecodeError) as exc:
            raise CapacityError(f"owner.json corrupt: {exc}") from exc
        if meta.get("nonce") != expected_nonce:
            raise CapacityError("owner.json nonce does not match expected")
        pid = meta.get("pid")
        if isinstance(pid, bool) or not isinstance(pid, int) or pid <= 0:
            raise CapacityError("owner.json pid invalid")
        state = _probe_state(process_probe, pid, meta.get("created"))
        if state == "live":
            raise CapacityError("owner process is live (same birth); recovery refused")
        event = {
            "event": "recover_dead",
            "owner": pid,
            "nonce": expected_nonce,
            "hash": expected_metadata_sha256,
            "reason": "conclusively_dead" if state == "dead" else "birth_differs",
            "recovered_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        }
        payload = json.dumps({"metadata": meta, "recovery": event},
                             sort_keys=True, separators=(",", ":"),
                             ensure_ascii=False, allow_nan=False).encode("utf-8")
        archive = _unique_archive(root / "archive", f"recover-{expected_nonce}", payload)
        event["archived"] = str(archive)
        try:
            os.unlink(os.fspath(metadata_path))
        except FileNotFoundError:
            pass
        _fsync_dir(root)
        return event
    finally:
        guard.close()


# ---------------------------------------------------------------------------
# NVIDIA XML parser + snapshot evaluation
# ---------------------------------------------------------------------------
import xml.etree.ElementTree as ET

_GPU_PROC_TYPES = frozenset(("C", "C+G", "G"))


def parse_nvidia_xml(text):
    """Parse one-GPU nvidia-smi XML; return flat dict or raise CapacityError."""
    if not isinstance(text, str) or not text:
        raise CapacityError("gpu_xml must be a non-empty string")
    try:
        root = ET.fromstring(text)
    except ET.ParseError as exc:
        raise CapacityError(f"GPU XML parse error: {exc}") from exc
    gpu = root.find(".//gpu")
    if gpu is None:
        raise CapacityError("GPU XML missing <gpu> element")
    uuid_el = gpu.find("uuid")
    if uuid_el is None or not (uuid_el.text or "").strip():
        raise CapacityError("GPU XML missing non-empty <uuid>")
    dm_el = gpu.find("driver_model/current_dm")
    if dm_el is None or not (dm_el.text or "").strip():
        raise CapacityError("GPU XML missing non-empty <driver_model><current_dm>")
    procs_el = gpu.find("processes")
    if procs_el is None:
        raise CapacityError("GPU XML missing mandatory <processes> element")
    processes = []
    seen_pids = set()
    for pi in procs_el.findall("process_info"):
        pid_el = pi.find("pid")
        type_el = pi.find("type")
        if pid_el is None or type_el is None:
            raise CapacityError("GPU process_info missing <pid> or <type>")
        pid_s = (pid_el.text or "").strip()
        if not pid_s or not pid_s.isdigit() or int(pid_s) <= 0:
            raise CapacityError(f"GPU process pid must be positive strict decimal, got {pid_s!r}")
        pid = int(pid_s)
        ptype = (type_el.text or "").strip()
        if ptype not in _GPU_PROC_TYPES:
            raise CapacityError(f"GPU process type must be in C/C+G/G, got {ptype!r}")
        if pid in seen_pids:
            raise CapacityError(f"GPU duplicate process pid {pid}")
        seen_pids.add(pid)
        processes.append({"pid": pid, "type": ptype})
    return {
        "uuid": (uuid_el.text or "").strip(),
        "driver_model": (dm_el.text or "").strip(),
        "processes": processes,
    }


def evaluate_snapshot(raw, binding):
    """Evaluate a raw snapshot against a binding; return computed facts."""
    reasons = []
    model_ok = False
    service_ok = False
    gpu_conflict = False
    client_conflict = False
    qwen_conflict = False

    # Validate binding first
    try:
        _validate_binding(binding)
    except CapacityError as exc:
        reasons.append(f"binding invalid: {exc}")
        return {
            "model_identity_verified": False,
            "service_identity_verified": False,
            "gpu_conflict_observed": False,
            "client_conflict_observed": False,
            "qwen_conflict_observed": False,
            "reasons": reasons,
        }

    # Model identity
    model = raw.get("model")
    if not isinstance(model, dict):
        reasons.append("model telemetry missing")
    else:
        if model.get("id") != binding["model_id"]:
            reasons.append("model id mismatch")
        else:
            params = model.get("parameters")
            if not isinstance(params, dict):
                reasons.append("model parameters missing")
            else:
                msl = params.get("max_seq_len")
                if isinstance(msl, bool) or not isinstance(msl, int) or msl != APPROVED_CONTEXT:
                    reasons.append("model max_seq_len must be strict int 262144")
                else:
                    model_ok = True

    # Service identity
    svc = raw.get("service")
    if not isinstance(svc, dict):
        reasons.append("service telemetry missing")
    else:
        bsvc = binding["service"]
        svc_tuple = (svc.get("pid"), svc.get("created"), svc.get("image_sha256"),
                     svc.get("parent_pid"), svc.get("parent_created"),
                     svc.get("parent_image_sha256"), svc.get("main_sha256"))
        bsvc_tuple = (bsvc["pid"], bsvc["created"], bsvc["image_sha256"],
                      bsvc["parent_pid"], bsvc["parent_created"],
                      bsvc["parent_image_sha256"], bsvc["main_sha256"])
        if svc_tuple != bsvc_tuple:
            reasons.append("service identity tuple mismatch")
        lp = svc.get("listener_port")
        if isinstance(lp, bool) or not isinstance(lp, int) or lp != 5000:
            reasons.append("listener_port must be strict int 5000")
        elif svc_tuple == bsvc_tuple:
            service_ok = True

    # GPU evaluation
    gpu_xml = raw.get("gpu_xml")
    gpu_uuid_matched = None  # None=unknown, True/False
    if gpu_xml is None:
        reasons.append("gpu_xml telemetry missing")
    elif not isinstance(gpu_xml, str) or not gpu_xml:
        reasons.append("gpu_xml must be non-empty string")
    else:
        try:
            parsed = parse_nvidia_xml(gpu_xml)
        except CapacityError as exc:
            reasons.append(f"gpu_xml parse error: {exc}")
        else:
            if parsed["uuid"] != binding["gpu_uuid"]:
                reasons.append("gpu uuid mismatch")
                gpu_uuid_matched = False
            else:
                gpu_uuid_matched = True
                svc_pid = binding["service"]["pid"]
                svc_proc = None
                extra_conflicts = []
                for p in parsed["processes"]:
                    if p["pid"] == svc_pid:
                        svc_proc = p
                    elif p["type"] in ("C", "C+G"):
                        extra_conflicts.append(p)
                if svc_proc is None:
                    reasons.append("gpu service process not found")
                elif svc_proc["type"] not in ("C", "C+G"):
                    reasons.append("gpu service process type must be C or C+G")
                else:
                    if extra_conflicts:
                        gpu_conflict = True
                        for p in extra_conflicts:
                            reasons.append(f"additional C/C+G gpu process pid={p['pid']} type={p['type']}")

    # Clients
    clients = raw.get("clients")
    if clients is None:
        reasons.append("clients telemetry missing")
        service_ok = False
    elif not isinstance(clients, list):
        reasons.append("clients must be a list")
        service_ok = False
    else:
        allowed = binding["allowed_clients"]
        allowed_set = {(c["pid"], c["created"]) for c in allowed}
        seen_client_pids = set()
        for c in clients:
            if not isinstance(c, dict):
                reasons.append("client entry must be a dict")
                client_conflict = True
                continue
            cp = c.get("pid")
            cc = c.get("created")
            if isinstance(cp, bool) or not isinstance(cp, int) or not isinstance(cc, str):
                reasons.append("client pid/created malformed")
                client_conflict = True
                continue
            if cp in seen_client_pids:
                reasons.append(f"duplicate client pid {cp}")
                client_conflict = True
                continue
            seen_client_pids.add(cp)
            if (cp, cc) not in allowed_set:
                reasons.append(f"foreign client pid={cp}")
                client_conflict = True

    # Herdr agents
    herdr = raw.get("herdr")
    if herdr is None:
        reasons.append("herdr telemetry missing")
    elif not isinstance(herdr, dict):
        reasons.append("herdr must be a dict")
    else:
        agents = herdr.get("agents")
        if not isinstance(agents, list):
            reasons.append("herdr agents must be a list")
        else:
            qwen_names = set(binding["qwen_worker_names"])
            for a in agents:
                if not isinstance(a, dict):
                    continue
                name = a.get("name", "")
                status = a.get("agent_status", "")
                if name in qwen_names and status in ("working", "blocked", "unknown"):
                    reasons.append(f"qwen worker {name} status={status}")
                    qwen_conflict = True

    # Service identity also requires GPU UUID match when known
    if service_ok and gpu_uuid_matched is False:
        service_ok = False

    return {
        "model_identity_verified": model_ok,
        "service_identity_verified": service_ok,
        "gpu_conflict_observed": gpu_conflict,
        "client_conflict_observed": client_conflict,
        "qwen_conflict_observed": qwen_conflict,
        "reasons": reasons,
    }


# ---------------------------------------------------------------------------
# Windows collector: raw IO seams (runner + http_get), no final booleans
# ---------------------------------------------------------------------------
_GPU_CMD = ("nvidia-smi", "-q", "-x")
_HERDR_CMD = ("herdr", "agent", "list")
_CARD_URL = "http://127.0.0.1:5000/v1/model"
_SVC_KEYS = ("pid", "created", "image_sha256", "parent_pid", "parent_created",
             "parent_image_sha256", "main_sha256", "listener_port")

_PS_SCRIPT = (
    "$ErrorActionPreference='Stop';"
    "function _Sha256File { param([string]$Path) $fs=$null; $sha=$null; try { $fs=[IO.FileStream]::new($Path,'Open','Read'); $sha=[Security.Cryptography.SHA256]::Create(); $h=$sha.ComputeHash($fs); $hex=''; foreach($b in $h){$hex+=$b.ToString('x2')}; return [pscustomobject]@{Hash=$hex} } finally { if($fs){$fs.Dispose()}; if($sha){$sha.Dispose()} } };"
    "$tcp=@(Get-NetTCPConnection -ErrorAction Stop);"
    "$l=@($tcp|Where-Object{$_.LocalPort -eq 5000 -and $_.State -eq 'Listen'});"
    "if($l.Count -ne 1){throw 'listener 5000 ambiguous'};"
    "$lp=$l[0].OwningProcess;"
    "$cli=@($tcp|Where-Object{$_.RemotePort -eq 5000 -and $_.State -eq 'Established'}|ForEach-Object{$_.OwningProcess}|Sort-Object -Unique|Where-Object{$_ -ne $lp});"
    "$ps=Get-CimInstance Win32_Process -Filter \"ProcessId=$lp\";"
    "if(-not $ps){throw 'listener process vanished'};"
    "$ppid=$ps.ParentProcessId;"
    "$pproc=Get-CimInstance Win32_Process -Filter \"ProcessId=$ppid\";"
    "if(-not $pproc){throw 'parent process vanished'};"
    "$img=_Sha256File -Path $ps.ExecutablePath;"
    "$pimg=_Sha256File -Path $pproc.ExecutablePath;"
    "$sp=Get-Process -Id $lp; $scp=Get-Process -Id $ppid;"
    "$screated=$sp.StartTime.ToFileTimeUtc().ToString('x16');"
    "$pcreated=$scp.StartTime.ToFileTimeUtc().ToString('x16');"
    "$tabby=Split-Path -Parent (Split-Path -Parent (Split-Path -Parent $pproc.ExecutablePath));"
    "$main=Join-Path $tabby 'main.py';"
    "if(-not (Test-Path -LiteralPath $main)){throw 'main.py missing'};"
    "$mainhash=_Sha256File -Path $main;"
    "$tok=[IO.Path]::GetFileName($main);"
    "$tokRegex='(?<![a-zA-Z0-9_.])' + [regex]::Escape($tok) + '(?![a-zA-Z0-9_.])';"
    "if(-not (($ps.CommandLine -match $tokRegex) -or ($pproc.CommandLine -match $tokRegex))){throw 'main.py token not matched'};"
    "$clients=@($cli|ForEach-Object{$p=Get-Process -Id $_;[pscustomobject]@{pid=$_;created=$p.StartTime.ToFileTimeUtc().ToString('x16')}});"
    "$svc=[pscustomobject]@{pid=$lp;created=$screated;image_sha256=$img.Hash;parent_pid=$ppid;parent_created=$pcreated;parent_image_sha256=$pimg.Hash;main_sha256=$mainhash.Hash;listener_port=5000};"
    "[pscustomobject]@{service=$svc;clients=$clients}|ConvertTo-Json -Depth 5 -Compress"
)


def _default_runner(argv, timeout=10, **kwargs):
    if sys.platform != "win32":
        raise CapacityError("default runner requires Windows")
    if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or timeout <= 0:
        raise CapacityError(f"runner timeout must be a positive number, got {timeout!r}")
    try:
        proc = subprocess.run(
            list(argv), shell=False, check=True, capture_output=True,
            text=True, encoding="utf-8", timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        raise CapacityError("runner timed out") from None
    except subprocess.CalledProcessError as exc:
        raise CapacityError(f"runner exit code {exc.returncode}") from None
    return proc.stdout


def _default_http_get(url, timeout=5, allow_redirects=False, **kwargs):
    import requests
    if sys.platform != "win32":
        raise CapacityError("default http_get requires Windows")
    if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or timeout <= 0:
        raise CapacityError(f"http_get timeout must be a positive number, got {timeout!r}")
    if allow_redirects is not False:
        raise CapacityError("http_get must keep allow_redirects disabled (False)")
    session = requests.Session()
    session.trust_env = False
    try:
        resp = session.get(url, timeout=timeout, allow_redirects=False)
    finally:
        session.close()
    if resp.status_code != 200:
        raise CapacityError(f"model card status {resp.status_code} != 200")
    return resp.text


def _parse_ps_attestation(text):
    if not isinstance(text, str) or not text:
        raise CapacityError("PS attestation stdout must be a non-empty string")
    try:
        data = json.loads(text)
    except (ValueError, TypeError) as exc:
        raise CapacityError(f"PS attestation JSON parse error: {exc}") from exc
    if not isinstance(data, dict):
        raise CapacityError("PS attestation must be a JSON object")
    svc = data.get("service")
    if not isinstance(svc, dict):
        raise CapacityError("PS attestation missing 'service' object")
    for key in _SVC_KEYS:
        if key not in svc:
            raise CapacityError(f"PS service missing required key {key!r}")
    clients = data.get("clients")
    if not isinstance(clients, list):
        raise CapacityError("PS attestation missing 'clients' list")
    for c in clients:
        if not isinstance(c, dict):
            raise CapacityError("PS client entry must be an object")
        if "pid" not in c or "created" not in c:
            raise CapacityError("PS client entry missing pid/created")
    return data


def _parse_herdr_stdout(text, qwen_worker_names=()):
    if not isinstance(text, str) or not text:
        raise CapacityError("herdr stdout must be a non-empty string")
    try:
        data = json.loads(text)
    except (ValueError, TypeError) as exc:
        raise CapacityError(f"herdr JSON parse error: {exc}") from exc
    if not isinstance(data, dict):
        raise CapacityError("herdr stdout must be a JSON object")
    result = data.get("result")
    if not isinstance(result, dict):
        raise CapacityError("herdr stdout missing 'result' object")
    agents = result.get("agents")
    if not isinstance(agents, list):
        raise CapacityError("herdr 'result.agents' must be a list")
    known = set(qwen_worker_names)
    sanitized = []
    for a in agents:
        if not isinstance(a, dict):
            raise CapacityError("herdr agent entry must be an object")
        name = a.get("name")
        status = a.get("agent_status")
        name_s = name if isinstance(name, str) else ""
        status_s = status if isinstance(status, str) else ""
        if name_s in known and not status_s:
            status_s = "unknown"
        sanitized.append({
            "name": name_s,
            "agent_status": status_s,
        })
    return {"agents": sanitized}


def _parse_model_card(text):
    if not isinstance(text, str) or not text:
        raise CapacityError("model card must be a non-empty string")
    try:
        data = json.loads(text)
    except (ValueError, TypeError) as exc:
        raise CapacityError(f"model card JSON parse error: {exc}") from exc
    if not isinstance(data, dict):
        raise CapacityError("model card must be a JSON object")
    mid = data.get("id")
    if not isinstance(mid, str) or not mid:
        raise CapacityError("model card missing 'id' string")
    params = data.get("parameters")
    if not isinstance(params, dict):
        raise CapacityError("model card missing 'parameters' object")
    msl = params.get("max_seq_len")
    if isinstance(msl, bool) or not isinstance(msl, int):
        raise CapacityError("model card max_seq_len must be a strict int")
    return {"id": mid, "parameters": {"max_seq_len": msl}}


def _sanitize_gpu_xml(text):
    """Re-serialize one-GPU nvidia-smi XML to observed facts only.

    Keeps exactly uuid / driver_model / process pid+type, using the parsed
    values re-emitted through ElementTree.  Unrelated raw metadata (serials,
    filenames, other tags) is discarded, while the observed pid/type facts are
    preserved verbatim.
    """
    parsed = parse_nvidia_xml(text)
    root = ET.Element("nvidia_smi_log")
    gpu = ET.SubElement(root, "gpu", {"id": "0"})
    ET.SubElement(gpu, "uuid").text = parsed["uuid"]
    ET.SubElement(ET.SubElement(gpu, "driver_model"), "current_dm").text = (
        parsed["driver_model"])
    procs = ET.SubElement(gpu, "processes")
    for p in parsed["processes"]:
        pi = ET.SubElement(procs, "process_info")
        ET.SubElement(pi, "pid").text = str(p["pid"])
        ET.SubElement(pi, "type").text = p["type"]
    return ET.tostring(root, encoding="unicode")


def collect_windows_snapshot(binding, *, runner=None, http_get=None):
    """Collect a raw Windows snapshot through injectable IO seams.

    Dispatches the three exact command kinds plus the one canonical loopback
    model card and returns the raw sanitized observations.  The collector ONLY
    observes: it does not render a healthy/unhealthy verdict and does not raise
    on unverified identity or observed conflict — the evaluator (and monitor)
    judge those raw facts and flag UNQUALIFIED.  Parse/transport that is
    missing or malformed still raises.  Fully injected works on any OS.
    """
    if runner is None:
        runner = _default_runner
    if http_get is None:
        http_get = _default_http_get
    gpu_xml = runner(list(_GPU_CMD), timeout=10)
    herdr_raw = runner(list(_HERDR_CMD), timeout=10)
    ps_raw = runner(["powershell.exe", "-NoProfile", "-Command", _PS_SCRIPT],
                    timeout=10)
    card_raw = http_get(_CARD_URL, timeout=5, allow_redirects=False)
    try:
        sanitized_gpu = _sanitize_gpu_xml(gpu_xml)
    except CapacityError as exc:
        raise CapacityError(f"gpu_xml invalid: {exc}") from exc
    herdr = _parse_herdr_stdout(herdr_raw, binding.get("qwen_worker_names", ()))
    attestation = _parse_ps_attestation(ps_raw)
    model = _parse_model_card(card_raw)
    raw = {
        "model": model,
        "gpu_xml": sanitized_gpu,
        "service": attestation["service"],
        "clients": attestation["clients"],
        "herdr": herdr,
    }
    return raw


# ---------------------------------------------------------------------------
# run_window + verify_receipt (cooperative monitor, Slice E)
# ---------------------------------------------------------------------------
import copy
import threading


def _validate_run_config(interval_s, max_gap_s, timeout_s):
    for nm, v in (("interval_s", interval_s), ("max_gap_s", max_gap_s), ("timeout_s", timeout_s)):
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            raise CapacityError(f"{nm} must be finite number, not bool")
        if not math.isfinite(v):
            raise CapacityError(f"{nm} must be finite")
    if interval_s <= 0:
        raise CapacityError("interval_s must be > 0")
    if max_gap_s < interval_s:
        raise CapacityError("max_gap_s must be >= interval_s")
    if timeout_s <= 0 or timeout_s > 900:
        raise CapacityError("timeout_s must be in (0, 900]")
    if max_gap_s > 15:
        raise CapacityError("max_gap_s must be <= 15")


def _probe_bounded(probe, deadline, t0):
    """Run probe in daemon thread; return (raw, p_start, p_end) or raise."""
    res = [None, None, None, None]
    done = threading.Event()

    def _w():
        res[1] = time.monotonic() - t0
        try:
            res[0] = probe()
        except Exception as exc:
            res[3] = exc
        finally:
            res[2] = time.monotonic() - t0
            done.set()

    th = threading.Thread(target=_w, daemon=True)
    th.start()
    remaining = deadline - time.monotonic()
    th.join(timeout=max(0.0, remaining))
    if not done.is_set():
        raise CapacityError("probe timeout")
    if res[3] is not None:
        raise res[3]
    return res[0], res[1], res[2]


def _sample(lease, nonce, raw, phase, seq, prev_hash, t0, p_start, p_end):
    lease.check(nonce)
    data_before, _ = _read_owner_bytes(lease.metadata_path)
    lease_hash_before = hashlib.sha256(data_before).hexdigest()
    s = {"seq": seq, "phase": phase, "time_s": p_end,
         "started_s": p_start, "ended_s": p_end,
         "raw": copy.deepcopy(raw),
         "lease_hash_before": lease_hash_before,
         "lease_hash_after": lease_hash_before,
         "prev_hash": prev_hash}
    # Re-check lease after to capture any corruption during probe
    try:
        lease.check(nonce)
        data_after, _ = _read_owner_bytes(lease.metadata_path)
        s["lease_hash_after"] = hashlib.sha256(data_after).hexdigest()
    except CapacityError:
        s["lease_hash_after"] = "CORRUPTED"
    s["hash"] = canonical_hash(s)
    return s


def _validate_coverage(samples, ws, we, config):
    """Validate chronology/coverage of samples.

    Returns (errors: list[str], interior_during: int).
    errors is empty if coverage is valid.
    Uses actual probe started_s/ended_s/time_s emitted by run_window.
    """
    errors = []
    if not samples:
        return errors, 0

    # 1. Strict sequence/chain
    for i, s in enumerate(samples):
        if s.get("seq") != i:
            errors.append(f"sample seq mismatch at {i}")
        if i == 0:
            if s.get("prev_hash") is not None:
                errors.append("first sample prev_hash must be None")
        else:
            if s.get("prev_hash") != samples[i - 1].get("hash"):
                errors.append(f"sample prev_hash mismatch at {i}")

    # 2. Phase order: PRE then DURING* then POST
    phases = [s["phase"] for s in samples]
    for ph in phases:
        if ph not in ("PRE", "DURING", "POST"):
            errors.append(f"unknown phase {ph!r}")
    pre_count = phases.count("PRE")
    post_count = phases.count("POST")
    if pre_count != 1:
        errors.append(f"expected exactly 1 PRE, got {pre_count}")
    if post_count != 1:
        errors.append(f"expected exactly 1 POST, got {post_count}")
    if phases[0] != "PRE":
        errors.append("first sample must be PRE")
    if phases[-1] != "POST":
        errors.append("last sample must be POST")
    for i, ph in enumerate(phases):
        if ph == "PRE" and i > 0:
            errors.append(f"PRE at position {i} must be first")
            break
    for i, ph in enumerate(phases):
        if ph == "POST" and i < len(phases) - 1:
            errors.append(f"POST at position {i} must be last")
            break

    # 3. Finite nonnegative time values, start<=end, time_s==ended_s
    for i, s in enumerate(samples):
        for key in ("time_s", "started_s", "ended_s"):
            v = s.get(key)
            if v is None:
                errors.append(f"sample {i} missing {key}")
            elif isinstance(v, bool) or not isinstance(v, (int, float)):
                errors.append(f"sample {i} {key} not numeric")
            elif not math.isfinite(v) or v < 0:
                errors.append(f"sample {i} {key} not finite nonnegative")
        st = s.get("started_s")
        en = s.get("ended_s")
        if isinstance(st, (int, float)) and isinstance(en, (int, float)):
            if st > en:
                errors.append(f"sample {i} started_s > ended_s")
        ts = s.get("time_s")
        if isinstance(ts, (int, float)) and isinstance(en, (int, float)):
            if ts != en:
                errors.append(f"sample {i} time_s != ended_s")

    # 4. Sample order: no backwards/overlap
    for i in range(1, len(samples)):
        prev_end = samples[i - 1].get("ended_s")
        cur_start = samples[i].get("started_s")
        if isinstance(prev_end, (int, float)) and isinstance(cur_start, (int, float)):
            if cur_start < prev_end:
                errors.append(
                    f"sample {i} starts before sample {i-1} ends (overlap)")

    # 5. Work interval checks
    interior_during = 0
    if ws is None or we is None:
        errors.append("work times missing; cannot validate coverage")
    else:
        for s in samples:
            if s["phase"] == "PRE":
                en = s.get("ended_s")
                if isinstance(en, (int, float)) and en > ws:
                    errors.append("PRE ended after work starts")
        for s in samples:
            if s["phase"] == "POST":
                st = s.get("started_s")
                if isinstance(st, (int, float)) and st < we:
                    errors.append("POST began before work ends")
        for s in samples:
            if s["phase"] == "DURING":
                ts = s.get("time_s")
                if isinstance(ts, (int, float)):
                    if ts < ws or ts > we:
                        errors.append(
                            f"DURING sample time_s={ts} outside "
                            f"work interval [{ws}, {we}]")
                    elif ws < ts < we:
                        interior_during += 1
        if not errors and interior_during == 0:
            errors.append("no genuinely interior DURING sample")

    # 6. Probe duration and gap checks
    max_gap = config.get("max_gap_s")
    if max_gap is not None:
        for i, s in enumerate(samples):
            st = s.get("started_s")
            en = s.get("ended_s")
            if isinstance(st, (int, float)) and isinstance(en, (int, float)):
                if (en - st) > max_gap:
                    errors.append(
                        f"sample {i} probe duration {en - st} "
                        f"exceeds max_gap {max_gap}")
        for i in range(1, len(samples)):
            prev_end = samples[i - 1].get("ended_s")
            cur_start = samples[i].get("started_s")
            if isinstance(prev_end, (int, float)) and isinstance(cur_start, (int, float)):
                gap = cur_start - prev_end
                if gap > max_gap:
                    errors.append(
                        f"gap between sample {i-1} and {i} is {gap} "
                        f"> max_gap {max_gap}")

    return errors, interior_during


def _lease_hash_linkage_errors(receipt_data):
    """Return reasons if the lease metadata hash linkage is broken.

    The expected lease metadata hash is canonical_hash(receipt['lease']['metadata']),
    using the same canonical serialization as CapacityLease._dumps.  The acquire
    event hash, each successful sample's BEFORE/AFTER lease hashes, and the
    release event hash must ALL equal that metadata hash, with matching
    nonce/owner lifecycle.  Matching arbitrary hashes to each other is
    insufficient: they must equal the canonical metadata hash.
    """
    errors = []
    lease_info = receipt_data.get("lease")
    if not isinstance(lease_info, dict):
        return ["lease section missing"]
    meta = lease_info.get("metadata")
    if not isinstance(meta, dict):
        return ["lease metadata missing"]
    nonce = lease_info.get("nonce")
    if not isinstance(nonce, str) or not nonce:
        errors.append("lease nonce missing")
    if meta.get("nonce") != nonce:
        errors.append("metadata nonce mismatch with lease header")
    try:
        expected = canonical_hash(meta)
    except CapacityError as exc:
        return errors + [f"lease metadata hash uncomputable: {exc}"]

    def _is_hash(v):
        return (isinstance(v, str) and len(v) == 64
                and all(c in "0123456789abcdef" for c in v))

    events = receipt_data.get("events")
    if not isinstance(events, list):
        events = []
    samples = receipt_data.get("samples")
    if not isinstance(samples, list):
        samples = []

    # acquire event: exactly one, matching nonce, hash == metadata hash
    acq = [e for e in events if isinstance(e, dict) and e.get("kind") == "acquire"]
    if not acq:
        errors.append("no acquire event for lease linkage")
    else:
        if len(acq) > 1:
            errors.append("duplicate acquire events")
        a = acq[0]
        if a.get("nonce") != nonce:
            errors.append("acquire nonce mismatch with lease header")
        if not _is_hash(a.get("hash")):
            errors.append("acquire hash malformed")
        elif a.get("hash") != expected:
            errors.append("acquire hash does not match lease metadata hash")

    # samples: each BEFORE/AFTER lease hash (when a real hash) == metadata hash
    for i, s in enumerate(samples):
        if not isinstance(s, dict):
            continue
        for key in ("lease_hash_before", "lease_hash_after"):
            v = s.get(key)
            if v == "CORRUPTED":
                continue  # honest corruption; handled by integrity check
            if not _is_hash(v):
                errors.append(f"sample {i} {key} malformed")
            elif v != expected:
                errors.append(f"sample {i} {key} does not match lease metadata hash")

    # release event: at most one, matching nonce, hash == metadata hash
    rel = [e for e in events if isinstance(e, dict) and e.get("kind") == "release"]
    if rel:
        if len(rel) > 1:
            errors.append("duplicate release events")
        r = rel[0]
        if r.get("nonce") != nonce:
            errors.append("release nonce mismatch with lease header")
        if not _is_hash(r.get("hash")):
            errors.append("release hash malformed")
        elif r.get("hash") != expected:
            errors.append("release hash does not match lease metadata hash")

    return errors


def _derive_summary(receipt_data, binding):
    """Derive the complete summary from receipt records.

    Both builder and verifier call this to ensure identical computation.
    Gathers ALL evaluator reasons unconditionally, plus recorded error events,
    with deterministic deduplication (first-occurrence order preserved).
    """
    samples = receipt_data.get("samples", [])
    events = receipt_data.get("events", [])
    ws = receipt_data.get("work_start_s")
    we = receipt_data.get("work_end_s")
    config = receipt_data.get("config", {})

    model_ok = True
    service_ok = True
    gpu_c = False
    client_c = False
    qwen_c = False
    lease_held = True

    all_reasons = []

    if not samples:
        all_reasons.append("no samples")
        model_ok = False
        service_ok = False

    for s in samples:
        ev = evaluate_snapshot(s.get("raw", {}), binding)
        if not ev["model_identity_verified"]:
            model_ok = False
        if not ev["service_identity_verified"]:
            service_ok = False
        if ev["gpu_conflict_observed"]:
            gpu_c = True
        if ev["client_conflict_observed"]:
            client_c = True
        if ev["qwen_conflict_observed"]:
            qwen_c = True
        # Gather ALL evaluator reasons unconditionally
        all_reasons.extend(ev["reasons"])
        # Lease integrity: check before/after hashes match
        lh_before = s.get("lease_hash_before")
        lh_after = s.get("lease_hash_after")
        if lh_before is not None and lh_after is not None and lh_before != lh_after:
            lease_held = False
            all_reasons.append(f"sample {s.get('seq')} lease hash changed")

    # Recorded error events
    for e in events:
        if e.get("kind") == "error":
            code = e.get("code", "unknown_error")
            all_reasons.append(code)
            if code in ("lease_corrupt", "lease_check_failed", "owner_corrupted",
                        "release_failed"):
                lease_held = False

    # Lease metadata hash linkage (shared between builder and verifier):
    # acquire event hash, each sample BEFORE/AFTER lease hash, and release
    # event hash must all equal the canonical lease metadata hash.
    linkage_errors = _lease_hash_linkage_errors(receipt_data)
    if linkage_errors:
        lease_held = False
        all_reasons.extend(linkage_errors)

    # MONITOR_COMPLETE: validated via shared coverage checker
    if samples:
        coverage_errors, _ = _validate_coverage(samples, ws, we, config)
        if coverage_errors:
            all_reasons.extend(coverage_errors)
        monitor_ok = (not coverage_errors)
    else:
        monitor_ok = False

    # Deterministic deduplication: preserve first-occurrence order
    seen = set()
    reasons = []
    for r in all_reasons:
        if r not in seen:
            seen.add(r)
            reasons.append(r)

    # lease_released derived from events
    lease_released = bool([e for e in events if e.get("kind") == "release"])

    # Qualified: zero reasons and all existing gates
    qualified = (model_ok and service_ok
                 and not gpu_c and not client_c and not qwen_c
                 and monitor_ok and lease_held and lease_released
                 and not reasons)

    return {
        "LEASE_HELD": lease_held,
        "MODEL_IDENTITY_VERIFIED": model_ok,
        "SERVICE_IDENTITY_VERIFIED": service_ok,
        "GPU_CONFLICT_OBSERVED": gpu_c,
        "TABBY_CONFLICT_OBSERVED": client_c,
        "MONITOR_COMPLETE": monitor_ok,
        "QWEN_CONFLICT_OBSERVED": qwen_c,
        "lease_released": lease_released,
        "CAPACITY_EVIDENCE": "QUALIFIED" if qualified else "UNQUALIFIED",
        "reasons": reasons,
    }


def _recompute(receipt, binding):
    """Backward-compatible wrapper; return (flags_dict, reasons)."""
    summary = _derive_summary(receipt, binding)
    flags = {k: v for k, v in summary.items()
             if k not in ("lease_released", "CAPACITY_EVIDENCE", "reasons")}
    return flags, summary["reasons"]


def run_window(lease, probe, work, *, interval_s=1, max_gap_s=2, timeout_s=60):
    _validate_run_config(interval_s, max_gap_s, timeout_s)
    t0 = time.monotonic()
    deadline = t0 + timeout_s
    binding = lease.binding
    # Acquire
    meta = lease.acquire()
    nonce = meta["nonce"]
    events = [{"kind": "acquire", "nonce": nonce, "hash": lease._meta_sha,
               "time_s": time.monotonic() - t0}]
    samples = []
    seq = 0
    prev_hash = None
    failure = [False]
    failure_reasons = []
    work_start_s = work_end_s = None
    lease_released = False
    lease_integrity_error = [False]

    def _record_error(code, exc=None):
        failure[0] = True
        failure_reasons.append(code)
        events.append({"kind": "error", "code": code, "time_s": time.monotonic() - t0})

    def _do_probe(phase):
        nonlocal seq, prev_hash
        try:
            raw, ps, pe = _probe_bounded(probe, deadline, t0)
            if (pe - ps) > max_gap_s:
                _record_error("probe_gap")
                return None
            s = _sample(lease, nonce, raw, phase, seq, prev_hash, t0, ps, pe)
            if seq > 0 and (s["time_s"] - samples[-1]["time_s"]) > max_gap_s:
                _record_error("sample_gap")
                return None
            samples.append(s)
            prev_hash = s["hash"]
            seq += 1
            return s
        except CapacityError as exc:
            if "lease" in str(exc).lower() or "owner" in str(exc).lower() or "guard" in str(exc).lower():
                lease_integrity_error[0] = True
                _record_error("lease_check_failed")
            else:
                _record_error("probe_failed" if not failure[0] else "probe_error")
            return None
        except Exception:
            _record_error("probe_failed" if not failure[0] else "probe_error")
            return None

    # PRE
    pre_sample = _do_probe("PRE")
    # Evaluate PRE before starting work: any reasons/conflicts prevent callback
    pre_ok = False
    if pre_sample is not None and not failure[0]:
        pre_ev = evaluate_snapshot(pre_sample["raw"], binding)
        if (pre_ev["model_identity_verified"] and pre_ev["service_identity_verified"]
                and not pre_ev["gpu_conflict_observed"]
                and not pre_ev["client_conflict_observed"]
                and not pre_ev["qwen_conflict_observed"]
                and not pre_ev["reasons"]):
            pre_ok = True
        else:
            _record_error("pre_evaluation_failed")
            for r in pre_ev["reasons"]:
                failure_reasons.append(r)
    # DURING (only if PRE succeeded and evaluation passed)
    if pre_ok:
        cancel_event = threading.Event()
        work_exc = [None]
        work_actual_start = [None]
        work_actual_end = [None]

        def _work_fn():
            work_actual_start[0] = time.monotonic() - t0
            try:
                work(cancel_event)
            except Exception as exc:
                work_exc[0] = exc
            finally:
                work_actual_end[0] = time.monotonic() - t0

        wth = threading.Thread(target=_work_fn, daemon=True)
        wth.start()
        work_start_s = time.monotonic() - t0
        # Monitor loop with absolute deadline
        while wth.is_alive() and time.monotonic() < deadline:
            _do_probe("DURING")
            if failure[0]:
                cancel_event.set()
            elif samples and samples[-1]["phase"] == "DURING":
                ev = evaluate_snapshot(samples[-1]["raw"], binding)
                if (not ev["model_identity_verified"] or not ev["service_identity_verified"]
                        or ev["gpu_conflict_observed"] or ev["client_conflict_observed"]
                        or ev["qwen_conflict_observed"]
                        or ev["reasons"]):
                    failure[0] = True
                    for r in ev["reasons"]:
                        failure_reasons.append(r)
                    cancel_event.set()
            remaining = deadline - time.monotonic()
            wth.join(timeout=min(interval_s, max(0.0, remaining)))
        # Deadline passed or work done: cancel immediately
        cancel_event.set()
        # Join work with remaining bound
        remaining = deadline - time.monotonic()
        wth.join(timeout=max(0.0, remaining))
        # Record actual work times
        if work_actual_start[0] is not None:
            work_start_s = work_actual_start[0]
        if work_actual_end[0] is not None:
            work_end_s = work_actual_end[0]
        elif work_start_s is not None:
            work_end_s = time.monotonic() - t0
        if wth.is_alive():
            _record_error("work_stuck")
        elif work_exc[0] is not None:
            _record_error("work_raised")
    # POST
    _do_probe("POST")
    # Release: only if lease is intact and no work_stuck
    work_stuck = any(e.get("code") == "work_stuck" for e in events)
    if not lease_integrity_error[0] and not work_stuck:
        try:
            lease.check(nonce)
            rel_event = lease.release(nonce)
            lease_released = True
            events.append({"kind": "release", "nonce": nonce, "hash": rel_event["hash"],
                           "time_s": time.monotonic() - t0})
        except CapacityError:
            lease.close()
            lease_integrity_error[0] = True
            _record_error("release_failed")
    else:
        lease.close()
    # Build summary via shared helper (identical to verifier computation)
    recompute_input = {"samples": samples, "events": events,
                       "work_start_s": work_start_s, "work_end_s": work_end_s,
                       "config": {"interval_s": interval_s,
                                  "max_gap_s": max_gap_s,
                                  "timeout_s": timeout_s},
                       "lease": {"nonce": nonce,
                                 "metadata": json.loads(json.dumps(meta))}}
    summary = _derive_summary(recompute_input, binding)
    receipt = {"kind": "qa-capacity-cooperative-v1", "binding": json.loads(json.dumps(binding)),
               "lease": {"nonce": nonce, "metadata": json.loads(json.dumps(meta))},
               "config": {"interval_s": interval_s, "max_gap_s": max_gap_s, "timeout_s": timeout_s},
               "work_start_s": work_start_s, "work_end_s": work_end_s,
               "samples": samples, "events": events, "summary": summary}
    receipt["digest"] = canonical_hash(receipt)
    return receipt


def verify_receipt(receipt, binding):
    if receipt.get("kind") != "qa-capacity-cooperative-v1":
        raise CapacityError("bad kind")
    if receipt.get("binding") != binding:
        raise CapacityError("binding mismatch")
    # Check outer digest
    stored_digest = receipt.get("digest")
    r = {k: v for k, v in receipt.items() if k != "digest"}
    if canonical_hash(r) != stored_digest:
        raise CapacityError("outer digest mismatch")
    # Validate metadata copies match binding
    lease_info = receipt.get("lease", {})
    stored_meta = lease_info.get("metadata", {})
    if stored_meta.get("source_head") != binding["source_head"]:
        raise CapacityError("metadata source_head mismatch")
    if stored_meta.get("model_id") != binding["model_id"]:
        raise CapacityError("metadata model_id mismatch")
    if stored_meta.get("context") != binding["context"]:
        raise CapacityError("metadata context mismatch")
    if stored_meta.get("service") != binding["service"]:
        raise CapacityError("metadata service mismatch")
    if stored_meta.get("binding") != binding:
        raise CapacityError("metadata binding mismatch")
    # Validate config
    config = receipt.get("config", {})
    for key in ("interval_s", "max_gap_s", "timeout_s"):
        val = config.get(key)
        if val is None or isinstance(val, bool) or not isinstance(val, (int, float)):
            raise CapacityError(f"config {key} invalid")
        if not math.isfinite(val) or val <= 0:
            raise CapacityError(f"config {key} must be finite positive")
    # Validate work times are finite and within config bounds
    ws = receipt.get("work_start_s")
    we = receipt.get("work_end_s")
    timeout_s = config["timeout_s"]
    if ws is not None:
        if isinstance(ws, bool) or not isinstance(ws, (int, float)) or not math.isfinite(ws):
            raise CapacityError("work_start_s invalid")
        if ws < 0 or ws > timeout_s:
            raise CapacityError("work_start_s outside config bounds")
    if we is not None:
        if isinstance(we, bool) or not isinstance(we, (int, float)) or not math.isfinite(we):
            raise CapacityError("work_end_s invalid")
        if we < 0 or we > timeout_s:
            raise CapacityError("work_end_s outside config bounds")
    if ws is not None and we is not None and we < ws:
        raise CapacityError("work_end_s before work_start_s")
    # Check sample chain
    samples = receipt.get("samples", [])
    for i, s in enumerate(samples):
        if s.get("seq") != i:
            raise CapacityError(f"sample seq mismatch at {i}")
        check = {k: v for k, v in s.items() if k != "hash"}
        if canonical_hash(check) != s.get("hash"):
            raise CapacityError(f"sample hash mismatch at {i}")
        if i > 0 and s.get("prev_hash") != samples[i - 1].get("hash"):
            raise CapacityError(f"sample prev_hash mismatch at {i}")
    # Validate chronology/coverage via shared validator
    if samples:
        cov_errors, _ = _validate_coverage(samples, ws, we, config)
        if cov_errors:
            raise CapacityError(f"coverage invalid: {cov_errors[0]}")
    # Check lease events
    events = receipt.get("events", [])
    acq = [e for e in events if e.get("kind") == "acquire"]
    if not acq:
        raise CapacityError("no acquire event")
    acquire_nonce = acq[0].get("nonce")
    if acquire_nonce != lease_info.get("nonce"):
        raise CapacityError("acquire nonce mismatch with lease info")
    rel = [e for e in events if e.get("kind") == "release"]
    if rel:
        if rel[0].get("nonce") != acquire_nonce:
            raise CapacityError("release nonce does not match acquire nonce")
    # Derive the entire summary via shared helper (identical to builder)
    computed_summary = _derive_summary(receipt, binding)
    # Compare the ENTIRE computed summary to stored summary exactly
    stored_summary = receipt.get("summary", {})
    if computed_summary != stored_summary:
        raise CapacityError("summary contradiction: computed != stored")
    return computed_summary


# ---------------------------------------------------------------------------
# Windows-native DEVELOPMENT entry point (not a workflow, not R75)
# ---------------------------------------------------------------------------

def canonical_lease_root():
    """Return the canonical LOCALAPPDATA lease root; Windows only."""
    if sys.platform != "win32":
        raise CapacityError("canonical_lease_root requires Windows")
    localappdata = os.environ.get("LOCALAPPDATA", "")
    if not localappdata:
        raise CapacityError("LOCALAPPDATA is empty or unset")
    if localappdata.startswith(("//", "\\\\")):
        raise CapacityError("LOCALAPPDATA must not be a UNC path")
    p = Path(localappdata)
    if not p.is_absolute():
        raise CapacityError("LOCALAPPDATA must be an absolute path")
    if ".." in p.parts:
        raise CapacityError("LOCALAPPDATA must not contain traversal")
    return p / "InvestorIntelligence" / "qa-capacity-v1"


def _native_source_evidence(binding):
    """Verify source integrity via bounded local git; return (head, sha256)."""
    repo = Path(__file__).resolve().parent.parent
    _MODULE_REL = "scripts/v213_qa_capacity.py"

    def _git(args, timeout=10):
        try:
            return subprocess.run(
                ["git"] + list(args), cwd=str(repo), shell=False,
                capture_output=True, text=True, timeout=timeout,
            )
        except subprocess.TimeoutExpired:
            raise CapacityError("git timed out") from None

    head_proc = _git(["rev-parse", "HEAD"])
    if head_proc.returncode != 0:
        raise CapacityError("git rev-parse HEAD failed")
    head = head_proc.stdout.strip()
    if head != binding["source_head"]:
        raise CapacityError("source HEAD mismatch")

    diff_proc = _git(["diff", "--quiet", "HEAD", "--"])
    if diff_proc.returncode != 0:
        raise CapacityError("tracked tree is dirty")

    cat_proc = _git(["cat-file", "-e", f"HEAD:{_MODULE_REL}"])
    if cat_proc.returncode != 0:
        raise CapacityError("module absent in HEAD")

    module_bytes = Path(__file__).resolve().read_bytes()
    return head, hashlib.sha256(module_bytes).hexdigest()


def run_native_window(binding, work, *, interval_s=2, max_gap_s=5,
                      timeout_s=60, ttl_s=60):
    """Windows-native DEVELOPMENT window; NOT R75 release qualification."""
    head, sha256 = _native_source_evidence(binding)
    root = canonical_lease_root()
    lease = CapacityLease(root, binding, ttl_s)
    receipt = run_window(
        lease, lambda: collect_windows_snapshot(binding), work,
        interval_s=interval_s, max_gap_s=max_gap_s, timeout_s=timeout_s,
    )
    receipt["origin"] = "WINDOWS_NATIVE_DEVELOPMENT"
    receipt["source_module_sha256"] = sha256
    receipt["digest"] = canonical_hash({k: v for k, v in receipt.items() if k != "digest"})
    return receipt