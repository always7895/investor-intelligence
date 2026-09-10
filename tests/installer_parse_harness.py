"""Persistent, public-only native parser fixtures. Never run installer bodies."""
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
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
    case = root / (label + "-" + uuid.uuid4().hex)
    case.mkdir()
    assert_plain_path(case)
    return case


@contextmanager
def persistent_fixture(label):
    # Deliberately no cleanup: failure evidence and links remain in this case.
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
    env = {key: os.environ[key] for key in ("SystemRoot", "WINDIR", "SystemDrive", "COMSPEC") if key in os.environ}
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


def result_record(case, host, result, expected_stdout, expected_returncode=0):
    if host not in REQUIRED_NATIVE_HOSTS:
        raise ValueError("HOST_LABEL_INVALID")
    output = (result.stdout + result.stderr).encode("utf-8", errors="replace")
    passed = (type(result.returncode) is int and result.returncode == expected_returncode
              and result.stdout.strip() == expected_stdout and result.stderr == "")
    record = dict(schema_version=1, host=host, returncode=result.returncode,
                  status=("PURE_PARSE_PASS" if expected_returncode == 0 else "EXPECTED_REJECTION") if passed else "UNEXPECTED",
                  output_bytes=len(output), output_sha256=hashlib.sha256(output).hexdigest(),
                  main_execution_allowed=False, raw_output_retained=False, release_qualified=False)
    write_json(case / (host.replace(".", "_") + "-result.json"), record)
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


def run_parse_case(fault=None):
    hosts = required_hosts()  # Missing capability is a nonzero blocker, never suite OK(skipped).
    case, manifest, driver = prepare_parse_case(fault)
    expected = PASS_MARKER if fault is None else "PURE_PARSE_REJECT;CODE=" + fault + ";MAIN_EXECUTED=false"
    inventory = {path: hashlib.sha256(path.read_bytes()).hexdigest()
                 for path in (driver, manifest, *(case / "inputs").iterdir())}
    for name, executable in hosts:
        host_case = case / name.replace(".", "_")
        host_case.mkdir()
        env = isolated_environment(host_case, executable)
        try:
            result = subprocess.run([executable, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                                     "-File", str(driver), "-InputManifest", str(manifest)],
                                    cwd=str(host_case), env=env, capture_output=True, encoding="utf-8", errors="replace", timeout=30)
        except (OSError, subprocess.TimeoutExpired) as exc:
            write_json(host_case / "transport-failure.json", dict(status="UNEXPECTED", code="TIMEOUT" if isinstance(exc, subprocess.TimeoutExpired) else "HOST_START_FAILED", release_qualified=False))
            raise RuntimeError("UNEXPECTED_PARSE_TRANSPORT") from None
        passed, record = result_record(case, name, result, expected, 0 if fault is None else 1)
        for path, digest in inventory.items():
            assert_plain_path(path)
            if hashlib.sha256(path.read_bytes()).hexdigest() != digest:
                raise RuntimeError("PARSE_INPUT_CHANGED")
        if not passed:
            raise AssertionError("UNEXPECTED_PURE_PARSE_RESULT: " + json.dumps(record, sort_keys=True))
    return case
