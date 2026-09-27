"""Behavioral tests for the local (non-CI) branch of scripts/resolve_python.ps1.

Each case copies the resolver into a disposable fixture checkout and runs it under
Windows PowerShell 5.1 and PowerShell 7. The base interpreter is a fake that
reports a configured version and creates a pip-less virtual environment from the
running test interpreter; pip inside that environment is a recording fake, so no
package is downloaded. The activation scripts are never run end to end: only
their Resolve-R75Python/Test-PythonRuntime function bodies are loaded.
"""
from __future__ import annotations

import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RESOLVER = ROOT / "scripts" / "resolve_python.ps1"
ACTIVATION_SCRIPTS = ("activate-v213-seven-field-schedule.ps1", "activate-v213-diversified-schedule.ps1")
NATIVE_HOSTS = ("powershell.exe", "pwsh.exe")
RUNNER_VERSION = ".".join(str(part) for part in sys.version_info[:3])
LOCKED_PIP_INSTALL = ["install", "--isolated", "--disable-pip-version-check", "--only-binary=:all:",
                      "--index-url", "https://pypi.org/simple", "--require-hashes", "-r"]

FAKE_BASE = r"""@echo off
setlocal
if not "%FAKE_BASE_LOG%"=="" echo %*>>"%FAKE_BASE_LOG%"
if "%~1"=="-c" goto probe
if "%~1"=="-m" if "%~2"=="venv" goto venv
exit /b 9
:probe
set "p=%~f0"
set "p=%p:\=\\%"
echo {"version": [@VERSION@], "bits": "@BITS@", "executable": "%p%", "prefix": "", "venv": false, "implementation": "@IMPL@"}
exit /b 0
:venv
"@PYTHON@" "@HELPER@" "%~4"
exit /b %ERRORLEVEL%
"""

FAKE_VENV = r"""import os
import sys
import venv
from pathlib import Path

rc = int(os.environ.get("FAKE_VENV_RC", "0"))
if rc:
    sys.exit(rc)
dest = Path(sys.argv[1])
if os.environ.get("FAKE_VENV_BROKEN") == "1":
    dest.mkdir(parents=True)
    (dest / "pyvenv.cfg").write_text("home = nowhere\n", encoding="utf-8")
    sys.exit(0)
venv.EnvBuilder(with_pip=False, symlinks=False).create(dest)
pip = dest / "Lib" / "site-packages" / "pip"
pip.mkdir(parents=True, exist_ok=True)
(pip / "__init__.py").write_text("", encoding="utf-8")
(pip / "__main__.py").write_text(
    "import json, os, sys\n"
    "log = os.environ.get('FAKE_PIP_LOG')\n"
    "if log:\n"
    "    with open(log, 'a', encoding='utf-8') as handle:\n"
    "        handle.write(json.dumps(sys.argv[1:]) + '\\n')\n"
    "command = sys.argv[1] if len(sys.argv) > 1 else ''\n"
    "sys.exit(int(os.environ.get('FAKE_PIP_' + command.upper() + '_RC', '0')))\n",
    encoding="utf-8",
)
"""


def _ps_quote(value: object) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def _remove_tree_no_follow(path: Path) -> None:
    """Delete a fixture tree; junctions and links are removed as links, never traversed."""
    if not path.exists():
        return
    with os.scandir(path) as entries:
        for entry in entries:
            if entry.is_junction() or entry.is_symlink():
                try:
                    os.unlink(entry.path)
                except OSError:
                    os.rmdir(entry.path)
            elif entry.is_dir(follow_symlinks=False):
                _remove_tree_no_follow(Path(entry.path))
            else:
                os.chmod(entry.path, stat.S_IWRITE)
                os.unlink(entry.path)
    os.rmdir(path)


@unittest.skipUnless(os.name == "nt", "the resolver is a Windows PowerShell script")
class LocalPythonResolverTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.hosts = [(name, shutil.which(name)) for name in NATIVE_HOSTS]
        missing = [name for name, path in cls.hosts if path is None]
        if missing:
            raise RuntimeError("BLOCKED_NATIVE_HOST_UNAVAILABLE: " + ", ".join(missing))

    def setUp(self):
        self.base = Path(tempfile.mkdtemp(prefix="ii-resolver-"))
        self.addCleanup(_remove_tree_no_follow, self.base)

    # Fixture helpers -------------------------------------------------------

    def fixture(self, name: str, *, requirements: bool = True) -> Path:
        case = self.base / name
        project = case / "project"
        (project / "scripts").mkdir(parents=True)
        shutil.copyfile(RESOLVER, project / "scripts" / "resolve_python.ps1")
        if requirements:
            (project / "requirements-ci.txt").write_text("fixture-package==1.0 --hash=sha256:" + "0" * 64 + "\n",
                                                         encoding="ascii")
        (project / "keep.txt").write_text("checkout sentinel\n", encoding="ascii")
        helper = case / "fake_venv.py"
        helper.write_text(FAKE_VENV, encoding="utf-8")
        return project

    def fake_base(self, project: Path, version: str = RUNNER_VERSION, bits: str = "64bit",
                  implementation: str = "cpython") -> Path:
        path = project.parent / f"fake-{implementation}-{version}-{bits}.cmd"
        text = (FAKE_BASE.replace("@VERSION@", ", ".join(version.split(".")))
                .replace("@BITS@", bits)
                .replace("@IMPL@", implementation)
                .replace("@PYTHON@", sys.executable)
                .replace("@HELPER@", str(project.parent / "fake_venv.py")))
        path.write_text(text.replace("\n", "\r\n"), encoding="ascii")
        return path

    def run_host(self, host: str, project: Path, body: str, env: dict[str, str] | None = None) -> dict[str, str]:
        script = project.parent / "harness.ps1"
        script.write_text(
            "$ErrorActionPreference = 'Stop'\n"
            f"Set-Location -LiteralPath {_ps_quote(project)}\n"
            "$outcome = 'OK'\n"
            "$out = $null\n"
            f"try {{\n{body}\n}} catch {{ $outcome = 'THREW: ' + $_.Exception.Message }}\n"
            "$count = if ($null -eq $out) { 0 } else { @($out).Count }\n"
            "[Console]::Out.WriteLine('II_OUTCOME=' + ($outcome -replace '\\r?\\n', ' '))\n"
            "[Console]::Out.WriteLine('II_PROJECT_PYTHON=' + $env:PROJECT_PYTHON)\n"
            "[Console]::Out.WriteLine('II_OUT_COUNT=' + $count)\n"
            "if ($count -gt 0) { [Console]::Out.WriteLine('II_OUT_FIRST=' + @($out)[0]) }\n",
            encoding="utf-8-sig",
        )
        environment = {key: value for key, value in os.environ.items()
                       if key.upper() not in {"GITHUB_ACTIONS", "GITHUB_ENV", "GITHUB_OUTPUT", "PROJECT_PYTHON",
                                              "PYTHON_FOR_RUNNER", "PSMODULEPATH"}
                       and not key.upper().startswith("FAKE_")}
        environment["FAKE_BASE_LOG"] = str(project.parent / "base.log")
        environment["FAKE_PIP_LOG"] = str(project.parent / "pip.log")
        environment.update(env or {})
        completed = subprocess.run(
            [host, "-NoLogo", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", str(script)],
            capture_output=True, text=True, encoding="utf-8", errors="replace", env=environment, timeout=300,
        )
        result = {}
        for line in completed.stdout.splitlines():
            if line.startswith("II_") and "=" in line:
                key, value = line.split("=", 1)
                result[key] = value
        self.assertIn("II_OUTCOME", result, f"{host} harness did not finish:\n{completed.stdout}\n{completed.stderr}")
        return result

    def resolve(self, host: str, project: Path, arguments: str, env: dict[str, str] | None = None,
                before: str = "") -> dict[str, str]:
        return self.run_host(host, project, f"{before}\n$out = & .\\scripts\\resolve_python.ps1 {arguments}", env)

    @staticmethod
    def pip_calls(project: Path) -> list[list[str]]:
        log = project.parent / "pip.log"
        if not log.exists():
            return []
        return [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines() if line.strip()]

    @staticmethod
    def venv_creations(project: Path) -> int:
        log = project.parent / "base.log"
        if not log.exists():
            return 0
        return sum("-m venv --copies" in line for line in log.read_text(encoding="utf-8", errors="replace").splitlines())

    def assert_failed(self, result: dict[str, str], message: str):
        self.assertTrue(result["II_OUTCOME"].startswith("THREW: "), result)
        self.assertIn(message, result["II_OUTCOME"])
        self.assertEqual(result["II_PROJECT_PYTHON"], "", "a failed resolution must not leave PROJECT_PYTHON")

    # Generic mode ----------------------------------------------------------

    def test_fresh_generic_setup_exports_verified_venv_without_installing(self):
        for host_name, host in self.hosts:
            with self.subTest(host=host_name):
                project = self.fixture(f"fresh-{host_name}")
                base = self.fake_base(project)
                result = self.resolve(host, project, f"-VenvPath .venv-t -BasePython {_ps_quote(base)}")
                expected = project / ".venv-t" / "Scripts" / "python.exe"
                self.assertEqual(result["II_OUTCOME"], "OK", result)
                self.assertEqual(result["II_PROJECT_PYTHON"], str(expected))
                self.assertTrue(expected.is_file())
                self.assertTrue((project / ".venv-t" / "pyvenv.cfg").is_file())
                self.assertEqual(result["II_OUT_COUNT"], "0", "the resolver must not write to the success stream")
                self.assertEqual(self.venv_creations(project), 1)
                self.assertEqual(self.pip_calls(project), [], "generic mode must not install packages")
                # Generic mode keeps its version/bitness-only semantics.
                other = self.fake_base(project, implementation="pypy")
                generic = self.resolve(host, project, f"-VenvPath .venv-u -BasePython {_ps_quote(other)}")
                self.assertEqual(generic["II_OUTCOME"], "OK", generic)

    def test_repeat_setup_reuses_environment_for_relative_and_absolute_paths(self):
        for host_name, host in self.hosts:
            with self.subTest(host=host_name):
                project = self.fixture(f"repeat-{host_name}")
                base = self.fake_base(project)
                first = self.resolve(host, project, f"-VenvPath .venv-t -BasePython {_ps_quote(base)}")
                self.assertEqual(first["II_OUTCOME"], "OK", first)
                venv = project / ".venv-t"
                (venv / "sentinel.txt").write_text("keep\n", encoding="ascii")
                dependency = venv / "Lib" / "site-packages" / "ii_sentinel_dep"
                dependency.mkdir()
                (dependency / "__init__.py").write_text("VALUE = 7\n", encoding="ascii")
                for arguments in (f"-VenvPath .venv-t -BasePython {_ps_quote(base)}",
                                  f"-VenvPath {_ps_quote(venv)} -BasePython {_ps_quote(base)}"):
                    again = self.resolve(host, project, arguments)
                    self.assertEqual(again["II_OUTCOME"], "OK", again)
                    self.assertEqual(again["II_PROJECT_PYTHON"], first["II_PROJECT_PYTHON"])
                self.assertEqual(self.venv_creations(project), 1, "an existing valid environment must be reused")
                self.assertTrue((venv / "sentinel.txt").is_file())
                probe = subprocess.run([first["II_PROJECT_PYTHON"], "-c", "import ii_sentinel_dep; print(ii_sentinel_dep.VALUE)"],
                                       capture_output=True, text=True, timeout=60)
                self.assertEqual(probe.stdout.strip(), "7")

    def test_wrong_version_or_architecture_base_is_rejected(self):
        for host_name, host in self.hosts:
            for version, bits in (("3.9.18", "64bit"), (RUNNER_VERSION, "32bit")):
                with self.subTest(host=host_name, version=version, bits=bits):
                    project = self.fixture(f"reject-{host_name}-{version}-{bits}")
                    base = self.fake_base(project, version, bits)
                    result = self.resolve(host, project, f"-VenvPath .venv-t -BasePython {_ps_quote(base)}",
                                          before="$env:PROJECT_PYTHON = 'C:\\stale\\python.exe'")
                    self.assert_failed(result, "No service-accessible 64-bit Python 3.10+")
                    self.assertFalse((project / ".venv-t").exists())

    def test_incompatible_existing_environment_is_left_untouched(self):
        for host_name, host in self.hosts:
            with self.subTest(host=host_name):
                project = self.fixture(f"incompatible-{host_name}")
                base = self.fake_base(project)
                self.assertEqual(self.resolve(host, project, f"-VenvPath .venv-t -BasePython {_ps_quote(base)}")["II_OUTCOME"], "OK")
                (project / ".venv-t" / "sentinel.txt").write_text("keep\n", encoding="ascii")
                result = self.resolve(host, project, f"-VenvPath .venv-t -MinimumVersion 3.99 -BasePython {_ps_quote(base)}",
                                      before="$env:PROJECT_PYTHON = 'C:\\stale\\python.exe'")
                self.assert_failed(result, "is not a compatible virtual environment")
                self.assertTrue((project / ".venv-t" / "sentinel.txt").is_file())
                self.assertTrue((project / ".venv-t" / "Scripts" / "python.exe").is_file())
                self.assertEqual(self.venv_creations(project), 1)

    def test_non_venv_broken_or_file_destination_is_left_untouched(self):
        for host_name, host in self.hosts:
            with self.subTest(host=host_name):
                project = self.fixture(f"nonvenv-{host_name}")
                base = self.fake_base(project)
                plain = project / "plain"
                plain.mkdir()
                (plain / "sentinel.txt").write_text("keep\n", encoding="ascii")
                broken = project / "broken"
                (broken / "Scripts").mkdir(parents=True)
                (broken / "pyvenv.cfg").write_text("home = nowhere\n", encoding="ascii")
                (broken / "Scripts" / "python.exe").write_text("not a program\n", encoding="ascii")
                (project / "afile").write_text("keep\n", encoding="ascii")
                (project / "empty").mkdir()
                for name, message in (("empty", "is not a compatible virtual environment"),
                                      ("plain", "is not a compatible virtual environment"),
                                      ("broken", "is not a compatible virtual environment"),
                                      ("afile", "exists and is not a directory")):
                    result = self.resolve(host, project, f"-VenvPath {name} -BasePython {_ps_quote(base)}")
                    self.assert_failed(result, message)
                self.assertEqual((plain / "sentinel.txt").read_text(encoding="ascii"), "keep\n")
                self.assertEqual(sorted(p.name for p in plain.iterdir()), ["sentinel.txt"])
                self.assertEqual((broken / "Scripts" / "python.exe").read_text(encoding="ascii"), "not a program\n")
                self.assertEqual((project / "afile").read_text(encoding="ascii"), "keep\n")
                self.assertEqual(list((project / "empty").iterdir()), [])
                self.assertEqual(self.venv_creations(project), 0)

    def test_unsafe_destinations_are_refused(self):
        # A resolver that failed to refuse would delete or write to the destination, so the
        # drive-root case uses a drive letter that does not exist rather than a real root.
        unused = [f"{letter}:\\" for letter in "ZYXWVUTSRQPONMLKJ" if not os.path.exists(f"{letter}:\\")]
        self.assertTrue(unused, "no unused drive letter for the drive-root case")
        for host_name, host in self.hosts:
            with self.subTest(host=host_name):
                project = self.fixture(f"unsafe-{host_name}")
                base = self.fake_base(project)
                for destination in (".", "..", str(project), unused[0]):
                    result = self.resolve(host, project, f"-VenvPath {_ps_quote(destination)} -BasePython {_ps_quote(base)}")
                    self.assert_failed(result, "Refusing unsafe virtual-environment destination")
                self.assertTrue((project / "keep.txt").is_file())
                self.assertEqual(self.venv_creations(project), 0)

    def test_reparse_point_destination_is_refused(self):
        for host_name, host in self.hosts:
            with self.subTest(host=host_name):
                project = self.fixture(f"reparse-{host_name}")
                base = self.fake_base(project)
                target = project.parent / "junction-target"
                target.mkdir()
                (target / "sentinel.txt").write_text("keep\n", encoding="ascii")
                link = project / "linked"
                # mklink prints in the console code page, so keep its output as bytes.
                made = subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(target)],
                                      capture_output=True, timeout=60)
                self.assertEqual(made.returncode, 0, (made.stdout + made.stderr).decode("mbcs", "replace"))
                for destination in ("linked\\env", "linked"):
                    result = self.resolve(host, project, f"-VenvPath {_ps_quote(destination)} -BasePython {_ps_quote(base)}")
                    self.assert_failed(result, "is a reparse point")
                self.assertEqual(sorted(p.name for p in target.iterdir()), ["sentinel.txt"])
                self.assertEqual(self.venv_creations(project), 0)

    def test_github_exports_only_after_success(self):
        for host_name, host in self.hosts:
            with self.subTest(host=host_name):
                project = self.fixture(f"github-{host_name}")
                github_env = project.parent / "github.env"
                github_output = project.parent / "github.output"
                env = {"GITHUB_ENV": str(github_env), "GITHUB_OUTPUT": str(github_output)}
                bad = self.fake_base(project, "3.9.18")
                failed = self.resolve(host, project, f"-VenvPath .venv-t -BasePython {_ps_quote(bad)}", env)
                self.assert_failed(failed, "No service-accessible")
                self.assertFalse(github_env.exists() or github_output.exists())
                good = self.fake_base(project)
                result = self.resolve(host, project, f"-VenvPath .venv-t -BasePython {_ps_quote(good)}", env)
                self.assertEqual(result["II_OUTCOME"], "OK", result)
                expected = str(project / ".venv-t" / "Scripts" / "python.exe")
                self.assertIn("PROJECT_PYTHON=" + expected, github_env.read_text(encoding="utf-8-sig"))
                self.assertIn("python=" + expected, github_output.read_text(encoding="utf-8-sig"))

    def test_unwritable_github_export_leaves_project_python_unset(self):
        for host_name, host in self.hosts:
            for variable in ("GITHUB_ENV", "GITHUB_OUTPUT"):
                with self.subTest(host=host_name, variable=variable):
                    project = self.fixture(f"github-fail-{host_name}-{variable}")
                    base = self.fake_base(project)
                    blocked = project.parent / "export-is-a-directory"
                    blocked.mkdir()
                    env = {"GITHUB_ENV": str(project.parent / "github.env"),
                           "GITHUB_OUTPUT": str(project.parent / "github.output")}
                    env[variable] = str(blocked)
                    result = self.resolve(host, project, f"-VenvPath .venv-t -BasePython {_ps_quote(base)}", env,
                                          before="$env:PROJECT_PYTHON = 'C:\\stale\\python.exe'")
                    self.assertTrue(result["II_OUTCOME"].startswith("THREW: "), result)
                    self.assertEqual(result["II_PROJECT_PYTHON"], "")
                    self.assertEqual(list(blocked.iterdir()), [])

    # Locked mode -----------------------------------------------------------

    def locked_case(self, name: str, host: str, *, env: dict[str, str] | None = None, version: str = "3.12.10",
                    requirements: bool = True, implementation: str = "cpython",
                    project: Path | None = None) -> tuple[Path, dict[str, str], Path, Path]:
        project = project or self.fixture(name, requirements=requirements)
        base = self.fake_base(project, version, implementation=implementation)
        github_env = project.parent / "github.env"
        github_output = project.parent / "github.output"
        environment = {"GITHUB_ENV": str(github_env), "GITHUB_OUTPUT": str(github_output)}
        environment.update(env or {})
        result = self.resolve(host, project, f"-VenvPath .venv-t -InstallLockedDependencies -BasePython {_ps_quote(base)}",
                              environment, before="$env:PROJECT_PYTHON = 'C:\\stale\\python.exe'")
        return project, result, github_env, github_output

    def assert_locked_failure(self, project: Path, result: dict[str, str], github_env: Path, github_output: Path,
                              message: str):
        self.assert_failed(result, message)
        self.assertFalse(github_env.exists() or github_output.exists(), "no success export after a failure")
        self.assertEqual(list(project.parent.rglob("*.ok")), [], "no success marker after a failure")

    @unittest.skipUnless(sys.version_info[:3] == (3, 12, 10), "locked mode needs the approved CPython 3.12.10 runner")
    def test_locked_mode_installs_the_hash_lock_and_checks_before_export(self):
        for host_name, host in self.hosts:
            with self.subTest(host=host_name):
                project, result, github_env, github_output = self.locked_case(f"locked-{host_name}", host)
                self.assertEqual(result["II_OUTCOME"], "OK", result)
                expected = str(project / ".venv-t" / "Scripts" / "python.exe")
                self.assertEqual(result["II_PROJECT_PYTHON"], expected)
                self.assertEqual(result["II_OUT_COUNT"], "0")
                self.assertEqual(self.pip_calls(project),
                                 [LOCKED_PIP_INSTALL + [str(project / "requirements-ci.txt")], ["check"]])
                self.assertIn("PROJECT_PYTHON=" + expected, github_env.read_text(encoding="utf-8-sig"))
                self.assertIn("python=" + expected, github_output.read_text(encoding="utf-8-sig"))

    @unittest.skipUnless(sys.version_info[:3] == (3, 12, 10), "locked mode needs the approved CPython 3.12.10 runner")
    def test_locked_mode_failures_export_nothing(self):
        cases = (
            ("pip-install", {"FAKE_PIP_INSTALL_RC": "1"}, "3.12.10", True, "Hash-locked dependency installation failed", 1),
            ("pip-check", {"FAKE_PIP_CHECK_RC": "1"}, "3.12.10", True, "pip check failed", 2),
            ("venv-create", {"FAKE_VENV_RC": "1"}, "3.12.10", True, "Failed to create virtual environment", 0),
            ("venv-probe", {"FAKE_VENV_BROKEN": "1"}, "3.12.10", True, "preflight failed", 0),
            ("interpreter", {}, "3.13.0", True, "approved 64-bit CPython 3.12.10", 0),
            ("implementation", {}, "3.12.10", True, "approved 64-bit CPython 3.12.10", 0),
            ("requirements", {}, "3.12.10", False, "Hash-locked requirements are missing", 0),
        )
        for host_name, host in self.hosts:
            for name, env, version, requirements, message, pip_calls in cases:
                with self.subTest(host=host_name, case=name):
                    project, result, github_env, github_output = self.locked_case(
                        f"lockfail-{host_name}-{name}", host, env=env, version=version, requirements=requirements,
                        implementation="pypy" if name == "implementation" else "cpython")
                    self.assert_locked_failure(project, result, github_env, github_output, message)
                    self.assertEqual(len(self.pip_calls(project)), pip_calls)
                    if name in ("interpreter", "implementation", "requirements", "venv-create"):
                        self.assertFalse((project / ".venv-t").exists())

    @unittest.skipUnless(sys.version_info[:3] == (3, 12, 10), "locked mode needs the approved CPython 3.12.10 runner")
    def test_locked_mode_rejects_an_existing_non_cpython_environment(self):
        for host_name, host in self.hosts:
            with self.subTest(host=host_name):
                project, first, _, _ = self.locked_case(f"lockimpl-{host_name}", host)
                self.assertEqual(first["II_OUTCOME"], "OK", first)
                venv = project / ".venv-t"
                # The venv's own interpreter now reports another implementation.
                (venv / "Lib" / "site-packages" / "sitecustomize.py").write_text(
                    "import sys, types\n"
                    "sys.implementation = types.SimpleNamespace(**{**vars(sys.implementation), 'name': 'pypy'})\n",
                    encoding="ascii")
                (venv / "sentinel.txt").write_text("keep\n", encoding="ascii")
                (project.parent / "github.env").unlink()
                (project.parent / "github.output").unlink()
                _, result, github_env, github_output = self.locked_case(f"lockimpl-{host_name}", host, project=project)
                self.assert_locked_failure(project, result, github_env, github_output,
                                           "is not a compatible virtual environment")
                self.assertTrue((venv / "sentinel.txt").is_file())
                self.assertEqual(len(self.pip_calls(project)), 2, "no install after the refusal")
                generic = self.resolve(host, project, "-VenvPath .venv-t")
                self.assertEqual(generic["II_OUTCOME"], "OK", generic)

    # Real callers ----------------------------------------------------------

    def test_activation_fallbacks_receive_the_resolver_executable(self):
        for script in ACTIVATION_SCRIPTS:
            for host_name, host in self.hosts:
                with self.subTest(script=script, host=host_name):
                    project = self.fixture(f"activation-{host_name}-{Path(script).stem}")
                    base = self.fake_base(project)
                    local_app_data = project.parent / "localappdata"
                    local_app_data.mkdir()
                    body = (
                        "$ast = [System.Management.Automation.Language.Parser]::ParseFile("
                        f"{_ps_quote(ROOT / script)}, [ref]$null, [ref]$null)\n"
                        "foreach ($name in 'Test-PythonRuntime', 'Resolve-R75Python') {\n"
                        "  $fn = $ast.Find({ param($n) $n -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -eq $name }, $true)\n"
                        "  if ($null -eq $fn) { throw \"missing function $name\" }\n"
                        "  . ([scriptblock]::Create($fn.Extent.Text))\n"
                        "}\n"
                        "function Get-Command { }\n"
                        "function Register-ScheduledTask { throw 'forbidden task API' }\n"
                        "function Invoke-WebRequest { throw 'forbidden network API' }\n"
                        "function Invoke-RestMethod { throw 'forbidden network API' }\n"
                        f"$env:LOCALAPPDATA = {_ps_quote(local_app_data)}\n"
                        f"$env:PYTHON_FOR_RUNNER = {_ps_quote(base)}\n"
                        "Remove-Item -LiteralPath Env:PROJECT_PYTHON -ErrorAction SilentlyContinue\n"
                        f"$out = Resolve-R75Python {_ps_quote(project)}\n"
                    )
                    result = self.run_host(host, project, body)
                    expected = local_app_data / "InvestorIntelligence" / "Runtime" / ".venv-v213-r75-activation" / "Scripts" / "python.exe"
                    self.assertEqual(result["II_OUTCOME"], "OK", result)
                    self.assertEqual(result["II_OUT_COUNT"], "1", "Resolve-R75Python must return one executable")
                    self.assertEqual(result["II_OUT_FIRST"], str(expected))
                    self.assertEqual(result["II_PROJECT_PYTHON"], str(expected))
                    self.assertEqual(self.pip_calls(project), [])

    def test_r70_call_pattern_uses_the_exported_interpreter(self):
        for host_name, host in self.hosts:
            with self.subTest(host=host_name):
                project = self.fixture(f"r70-{host_name}")
                base = self.fake_base(project)
                body = (
                    "function Get-Command { }\n"
                    f"$env:PYTHON_FOR_RUNNER = {_ps_quote(base)}\n"
                    "& .\\scripts\\resolve_python.ps1 -VenvPath .venv-v213-r70-validation\n"
                    "if (-not $env:PROJECT_PYTHON -or -not (Test-Path -LiteralPath $env:PROJECT_PYTHON -PathType Leaf)) { throw 'Verified Python was not configured.' }\n"
                    "& $env:PROJECT_PYTHON -m pip install --isolated --disable-pip-version-check --only-binary=:all: --index-url https://pypi.org/simple --require-hashes -r requirements-ci.txt\n"
                    "if ($LASTEXITCODE -ne 0) { throw 'Hash-locked Python dependency installation failed.' }\n"
                    "& $env:PROJECT_PYTHON -m pip check\n"
                    "if ($LASTEXITCODE -ne 0) { throw 'Python dependency check failed.' }\n"
                )
                result = self.run_host(host, project, body)
                self.assertEqual(result["II_OUTCOME"], "OK", result)
                self.assertEqual(result["II_PROJECT_PYTHON"],
                                 str(project / ".venv-v213-r70-validation" / "Scripts" / "python.exe"))
                self.assertEqual(self.pip_calls(project), [LOCKED_PIP_INSTALL + ["requirements-ci.txt"], ["check"]])


if __name__ == "__main__":
    unittest.main()
