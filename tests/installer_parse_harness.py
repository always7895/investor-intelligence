"""Persistent, public-only native parser fixtures. Never run installer bodies."""
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import time
import uuid

ROOT = Path(__file__).resolve().parents[1]
# CI must explicitly supply its owned runner-temp scope; never use ambient TEMP.
if os.environ.get("V213_INSTALLER_TEST_AUDIT_ROOT"):
    AUDIT_CASE_ROOT = Path(os.environ["V213_INSTALLER_TEST_AUDIT_ROOT"])
elif os.environ.get("GITHUB_ACTIONS") == "true" and os.environ.get("RUNNER_TEMP"):
    AUDIT_CASE_ROOT = Path(os.environ["RUNNER_TEMP"]) / "v213-installer-test-cases"
else:
    AUDIT_CASE_ROOT = ROOT.parent / "audit-runtime" / "w1-review-b-cases"
REQUIRED_NATIVE_HOSTS = ("powershell.exe", "pwsh.exe")
PARSE_INPUTS = (
    ("caller:BASE", "install-v213-runtime.ps1"),
    ("caller:SOURCE_DIVERSE", "install-v213-source-diverse-runtime.ps1"),
    ("caller:SOURCE_DIVERSE_V2", "install-v213-source-diverse-runtime-v2.ps1"),
    ("caller:SERENITY_LATEST", "install-v213-serenity-latest-runtime.ps1"),
    ("coordinator", "scripts/v213_runtime_install_coordinator.ps1"),
)
PASS_MARKER = "PURE_PARSE_PASS;MAIN_EXECUTED=false;ROLES=6"


def required_hosts():
    hosts = [(name, shutil.which(name)) for name in REQUIRED_NATIVE_HOSTS]
    if any(path is None for _, path in hosts):
        raise RuntimeError("BLOCKED_NATIVE_HOST_UNAVAILABLE")
    return [(name, str(Path(path).absolute())) for name, path in hosts]


def assert_plain_path(path):
    """lstat detects junctions as well as symlinks; never traverse a link."""
    path = Path(path)
    for entry in (*reversed(path.parents), path):
        info = entry.lstat()
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT:
            raise RuntimeError("FIXTURE_REPARSE_REJECTED")
        if entry != path and not stat.S_ISDIR(info.st_mode):
            raise RuntimeError("FIXTURE_PARENT_NOT_DIRECTORY")
    if path.is_file() and path.stat().st_nlink != 1:
        raise RuntimeError("FIXTURE_HARDLINK_REJECTED")


# Cases stay for a day as failure evidence; older ones are pruned once per process
# so repeated full runs cannot grow the audit area without bound.
CASE_RETENTION_SECONDS = 24 * 60 * 60
CASE_NAME = re.compile(r"^[a-z0-9-]+-[0-9a-f]{32}$")
_pruned_roots = set()


def _remove_tree_no_follow(path):
    """Delete a case tree; links and junctions are removed as links, never traversed."""
    with os.scandir(path) as entries:
        for entry in entries:
            try:
                if entry.is_junction() or entry.is_symlink():
                    try:
                        os.unlink(entry.path)
                    except OSError:
                        os.rmdir(entry.path)
                elif entry.is_dir(follow_symlinks=False):
                    _remove_tree_no_follow(entry.path)
                else:
                    os.chmod(entry.path, stat.S_IWRITE)
                    os.unlink(entry.path)
            except OSError:
                continue  # e.g. an ACL test case denying deletion; leave it
    try:
        os.rmdir(path)
    except OSError:
        pass


def prune_stale_cases(root, retention_seconds=CASE_RETENTION_SECONDS, now=None):
    """Remove case directories older than the retention; returns the pruned names."""
    cutoff = (time.time() if now is None else now) - retention_seconds
    pruned = []
    with os.scandir(root) as entries:
        for entry in entries:
            try:
                if not CASE_NAME.fullmatch(entry.name) or entry.is_junction() or entry.is_symlink():
                    continue
                if not entry.is_dir(follow_symlinks=False) or entry.stat(follow_symlinks=False).st_mtime >= cutoff:
                    continue
                _remove_tree_no_follow(entry.path)
            except OSError:
                continue  # removed concurrently or not accessible; never fail a test run on pruning
            pruned.append(entry.name)
    return pruned


def new_case(label):
    if not label or any(c not in "abcdefghijklmnopqrstuvwxyz0123456789-" for c in label):
        raise ValueError("FIXTURE_LABEL_INVALID")
    root = AUDIT_CASE_ROOT
    if not root.is_absolute() or ".." in root.parts or str(root).startswith("\\\\"):
        raise RuntimeError("FIXTURE_ABSOLUTE_LOCAL_ROOT_REQUIRED")
    if root == ROOT or root.is_relative_to(ROOT) or ROOT.is_relative_to(root):
        raise RuntimeError("FIXTURE_SOURCE_OVERLAP")
    assert_plain_path(root.parent)
    root.mkdir(exist_ok=True)
    assert_plain_path(root)
    if root not in _pruned_roots:
        _pruned_roots.add(root)
        prune_stale_cases(root)
    case = root / (label + "-" + uuid.uuid4().hex)
    case.mkdir()
    assert_plain_path(case)
    return case


@contextmanager
def persistent_fixture(label):
    # No cleanup on exit: failure evidence and links stay; new_case prunes cases after CASE_RETENTION_SECONDS.
    yield str(new_case(label.rstrip(" -")))


def write_new(path, raw):
    assert_plain_path(path.parent)
    with path.open("xb") as handle:
        handle.write(raw)
        handle.flush()
        os.fsync(handle.fileno())
    if path.read_bytes() != raw:
        raise RuntimeError("FIXTURE_WRITE_READBACK_FAILED")


def write_json(path, value):
    write_new(path, (json.dumps(value, ensure_ascii=False, allow_nan=False, sort_keys=True, indent=2) + "\n").encode("utf-8"))


def isolated_environment(case, host_path):
    assert_plain_path(case)
    home = Path(host_path).parent
    # Never inherit tokens, LINE IDs, broker config or caller PSModulePath.
    env = {key: os.environ[key] for key in ("SystemRoot", "WINDIR", "SystemDrive", "COMSPEC", "PATHEXT") if key in os.environ}
    env.setdefault("PATHEXT", ".COM;.EXE;.BAT;.CMD")
    for key, directory in (("LOCALAPPDATA", "local"), ("APPDATA", "roaming"),
                           ("TEMP", "temp"), ("TMP", "temp"), ("USERPROFILE", "profile"), ("HOME", "profile")):
        target = case / directory
        target.mkdir(exist_ok=True)
        assert_plain_path(target)
        env[key] = str(target)
    windows = Path(os.environ["SystemRoot"])
    env["PATH"] = os.pathsep.join((str(home), str(windows / "System32")))
    env["PSModulePath"] = os.pathsep.join((str(home / "Modules"), str(windows / "System32/WindowsPowerShell/v1.0/Modules")))
    env["PSModuleAnalysisCachePath"] = str(case / "local" / "module-analysis-cache")
    env.update(PYTHONUTF8="1", PYTHONDONTWRITEBYTECODE="1", POWERSHELL_TELEMETRY_OPTOUT="1",
               POWERSHELL_UPDATECHECK="Off", LINE_ENABLED="false", DELIVERY_ENABLED="false",
               PUBLIC_KV_SYNC_ENABLED="false", IBKR_READONLY_ENABLED="false", FREE_ONLY_MODE="true",
               PAID_FALLBACK_ENABLED="false", PRODUCTION_MUTATION_BY_CI="false")
    return env


def _write_parse_evidence(path, record):
    try:
        write_json(path, record)
    except (OSError, RuntimeError):
        # Do not overwrite an existing receipt or leak an OS message/path. Keep
        # the primary result distinct from failure to persist that result.
        status = record.get("status")
        if status not in ("PURE_PARSE_PASS", "EXPECTED_REJECTION", "UNEXPECTED"):
            status = "UNEXPECTED"
        code = record.get("code", "NONE")
        if code not in ("NONE", "TIMEOUT", "HOST_START_FAILED", "INPUT_CHANGED", "INPUT_UNAVAILABLE"):
            code = "UNKNOWN"
        rc = record.get("returncode")
        if type(rc) is not int:
            rc = "NOT_STARTED"
        raise RuntimeError(f"UNEXPECTED_PARSE_EVIDENCE_WRITE;primary_status={status};primary_code={code};returncode={rc}") from None


def result_record(case, host, result, expected_stdout, expected_returncode=0, *,
                  input_binding_sha256=None, input_integrity="NOT_BOUND"):
    if host not in REQUIRED_NATIVE_HOSTS:
        raise ValueError("HOST_LABEL_INVALID")
    if input_binding_sha256 is not None:
        if (not isinstance(input_binding_sha256, str) or len(input_binding_sha256) != 64
                or any(c not in "0123456789abcdef" for c in input_binding_sha256)
                or input_integrity not in ("UNCHANGED", "CHANGED", "UNAVAILABLE")):
            raise ValueError("PARSE_BINDING_INVALID")
    elif input_integrity != "NOT_BOUND":
        raise ValueError("PARSE_BINDING_REQUIRED")
    output = (result.stdout + result.stderr).encode("utf-8", errors="replace")
    matched = (type(result.returncode) is int and result.returncode == expected_returncode
               and result.stdout.strip() == expected_stdout and result.stderr == "")
    passed = matched and input_integrity in ("NOT_BOUND", "UNCHANGED")
    record = dict(schema_version=2, host=host, returncode=result.returncode,
                  status=("PURE_PARSE_PASS" if expected_returncode == 0 else "EXPECTED_REJECTION") if passed else "UNEXPECTED",
                  process_oracle_matched=matched, input_integrity=input_integrity, input_binding_sha256=input_binding_sha256,
                  output_bytes=len(output), output_sha256=hashlib.sha256(output).hexdigest(),
                  main_execution_allowed=False, raw_output_retained=False, release_qualified=False)
    _write_parse_evidence(case / (host.replace(".", "_") + "-result.json"), record)
    return passed, record


def prepare_parse_case(fault=None):
    if fault not in (None, "ROLE_SET_INVALID", "INPUT_DIGEST_MISMATCH", "PARSE_ERROR"):
        raise ValueError("FAULT_NOT_DECLARED")
    case = new_case("b1-pure-parse")
    inputs = case / "inputs"
    inputs.mkdir()
    control = b"param(\n" if fault == "PARSE_ERROR" else b"param()\nthrow 'CONTROL_BODY_MUST_NOT_EXECUTE'\n"
    payloads = [("control", "control.ps1", control)]
    for role, relative in PARSE_INPUTS:
        source = ROOT / relative
        assert_plain_path(source)
        if source.stat().st_size > 524288:
            raise RuntimeError("PARSE_INPUT_LIMIT")
        payloads.append((role, Path(relative).name, source.read_bytes()))
    entries = []
    for role, name, raw in payloads:
        path = inputs / name
        write_new(path, raw)
        entries.append(dict(role=role, path=str(path), bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest()))
    if fault == "ROLE_SET_INVALID":
        entries[1]["role"] = "coordinator"
    if fault == "INPUT_DIGEST_MISMATCH":
        entries[0]["sha256"] = "0" * 64
    manifest = case / "pure-parse-input.json"
    write_json(manifest, dict(schema_version=1, main_execution_allowed=False, files=entries))
    driver_source = ROOT / "tests/fixtures/v213_parse_only.ps1"
    assert_plain_path(driver_source)
    driver = case / "parse-only.ps1"
    write_new(driver, driver_source.read_bytes())
    return case, manifest, driver


def _parse_input_integrity(inventory):
    try:
        for path, digest in inventory.items():
            assert_plain_path(path)
            if hashlib.sha256(path.read_bytes()).hexdigest() != digest:
                return "CHANGED"
    except (OSError, RuntimeError):
        return "UNAVAILABLE"  # Includes rejected links; never follow them to rescue a hash.
    return "UNCHANGED"


def run_parse_case(fault=None):
    hosts = required_hosts()  # Missing capability is a nonzero blocker, never suite OK(skipped).
    case, manifest, driver = prepare_parse_case(fault)
    expected = PASS_MARKER if fault is None else "PURE_PARSE_REJECT;CODE=" + fault + ";MAIN_EXECUTED=false"
    inventory, entries = {}, []
    for path in (driver, manifest, *sorted((case / "inputs").iterdir())):
        assert_plain_path(path)
        data = path.read_bytes()
        inventory[path] = hashlib.sha256(data).hexdigest()
        entries.append(dict(path=str(path.relative_to(case)), bytes=len(data), sha256=inventory[path]))
    harness_path = Path(__file__)
    assert_plain_path(harness_path)
    inventory[harness_path] = hashlib.sha256(harness_path.read_bytes()).hexdigest()
    binding = case / "parse-run-inputs.json"
    _write_parse_evidence(binding, dict(schema_version=1, kind="PURE_PARSE_INPUT_BINDING", fault=fault,
                         inputs=entries, harness_sha256=inventory[harness_path], hosts=[name for name, _ in hosts],
                         main_execution_allowed=False, release_qualified=False))
    binding_sha256 = hashlib.sha256(binding.read_bytes()).hexdigest()
    inventory[binding] = binding_sha256
    for name, executable in hosts:
        host_case = case / name.replace(".", "_")
        host_case.mkdir()
        env = isolated_environment(host_case, executable)
        integrity = _parse_input_integrity(inventory)
        if integrity != "UNCHANGED":
            _write_parse_evidence(host_case / "transport-failure.json", dict(status="UNEXPECTED", host=name,
                                 code="INPUT_" + integrity, input_integrity=integrity, input_binding_sha256=binding_sha256,
                                 returncode=None, main_execution_allowed=False, release_qualified=False))
            raise RuntimeError("PARSE_INPUT_" + integrity)
        try:
            result = subprocess.run([executable, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                                     "-File", str(driver), "-InputManifest", str(manifest)],
                                    cwd=str(host_case), env=env, capture_output=True, encoding="utf-8", errors="replace", timeout=30)
        except (OSError, subprocess.TimeoutExpired) as exc:
            partial = b""
            if isinstance(exc, subprocess.TimeoutExpired):
                for value in (exc.output, exc.stderr):
                    if isinstance(value, str):
                        partial += value.encode("utf-8", errors="replace")
                    elif isinstance(value, bytes):
                        partial += value
            _write_parse_evidence(host_case / "transport-failure.json", dict(status="UNEXPECTED", host=name,
                                 code="TIMEOUT" if isinstance(exc, subprocess.TimeoutExpired) else "HOST_START_FAILED",
                                 input_integrity=_parse_input_integrity(inventory), input_binding_sha256=binding_sha256,
                                 returncode=None, output_bytes=len(partial), output_sha256=hashlib.sha256(partial).hexdigest(),
                                 raw_output_retained=False, main_execution_allowed=False, release_qualified=False))
            raise RuntimeError("UNEXPECTED_PARSE_TRANSPORT") from None
        # Classify input integrity BEFORE writing any success receipt. A process
        # marker alone is not a source-bound PASS. These checks are not a TOCTOU proof.
        integrity = _parse_input_integrity(inventory)
        passed, record = result_record(case, name, result, expected, 0 if fault is None else 1,
                                       input_binding_sha256=binding_sha256, input_integrity=integrity)
        if integrity != "UNCHANGED":
            raise RuntimeError("PARSE_INPUT_" + integrity)
        if not passed:
            raise AssertionError("UNEXPECTED_PURE_PARSE_RESULT: " + json.dumps(record, sort_keys=True))
    return case
