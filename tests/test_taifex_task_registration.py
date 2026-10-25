"""O10 TAIFEX task activation: registration transaction over a fake task scheduler.

Every ScheduledTasks cmdlet is a PowerShell function over an in-memory XML store (functions shadow cmdlets), so no real
task is read or changed. The fake parses the registered XML the way the scheduler would (action, trigger, enabled flags),
so a placeholder, a disabled trigger or a wrong path in the rendered definition fails the real readback code. Like the
real scheduler it refuses a definition string whose XML declaration names an encoding other than UTF-16."""
import json
import shlex
import shutil
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch
import xml.etree.ElementTree as ET

from tests import test_batch06_taifex_callers as fixture

ROOT = Path(__file__).resolve().parents[1]
LIB = ROOT / "scripts" / "taifex_options_eod_task.ps1"
ENTRY = ROOT / "scripts" / "register_taifex_options_eod_task.ps1"
TEMPLATE = ROOT / "scripts" / "task-templates" / "taifex-options-eod.disabled.xml"
NAME = "InvestorIntelligence-TaifexOptionsEod"
NS = {"t": "http://schemas.microsoft.com/windows/2004/02/mit/task"}

HARNESS = r"""
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$case = Get-Content -LiteralPath $args[0] -Raw -Encoding UTF8 | ConvertFrom-Json
$global:Store = @{}
foreach ($p in $case.existing.PSObject.Properties) { $global:Store[$p.Name] = [string]$p.Value }
$global:Calls = New-Object System.Collections.Generic.List[string]
function Read-Task([string]$xml) {
    $d = New-Object System.Xml.XmlDocument; $d.LoadXml($xml)
    $n = New-Object System.Xml.XmlNamespaceManager $d.NameTable; $n.AddNamespace('t', 'http://schemas.microsoft.com/windows/2004/02/mit/task')
    $x = $d.SelectSingleNode('//t:Exec', $n)
    [pscustomobject]@{
        Actions = @([pscustomobject]@{ Execute = $x.SelectSingleNode('t:Command', $n).InnerText; Arguments = $x.SelectSingleNode('t:Arguments', $n).InnerText
                                       WorkingDirectory = $x.SelectSingleNode('t:WorkingDirectory', $n).InnerText })
        Triggers = @([pscustomobject]@{ Enabled = ($d.SelectSingleNode('//t:CalendarTrigger/t:Enabled', $n).InnerText -eq 'true')
                                        StartBoundary = $d.SelectSingleNode('//t:CalendarTrigger/t:StartBoundary', $n).InnerText })
        Settings = [pscustomobject]@{ Enabled = ($d.SelectSingleNode('//t:Settings/t:Enabled', $n).InnerText -eq 'true') }
        Principal = [pscustomobject]@{ LogonType = $(if ($d.SelectSingleNode('//t:Principal/t:LogonType', $n).InnerText -eq 'InteractiveToken') { 'Interactive' } else { 'Other' }) }
    }
}
function Get-ScheduledTask {
    [CmdletBinding()] param([string]$TaskName)
    $global:Calls.Add("GET $TaskName")
    if (@($case.lookup_fail) -contains $TaskName) { throw "SYNTHETIC_LOOKUP_FAILURE" }
    if ($global:Store.ContainsKey($TaskName)) { return (Read-Task $global:Store[$TaskName]) }
    $record = New-Object Management.Automation.ErrorRecord ([Exception]"No task $TaskName"), 'NotFound', 'ObjectNotFound', $TaskName
    $PSCmdlet.WriteError($record)
}
function Export-ScheduledTask {
    [CmdletBinding()] param([string]$TaskName)
    $global:Calls.Add("EXPORT $TaskName")
    return $global:Store[$TaskName]
}
function Register-ScheduledTask {
    [CmdletBinding()] param([string]$TaskName, [string]$Xml, [switch]$Force)
    $existingNames = @($case.existing.PSObject.Properties | ForEach-Object { $_.Name })
    $isRestore = ($existingNames -contains $TaskName) -and ($Xml -eq [string]$case.existing.$TaskName)
    $kind = if ($isRestore) { 'RESTORE' } else { 'REGISTER' }
    $global:Calls.Add("$kind $TaskName")
    # the real scheduler takes the string as UTF-16 and refuses a declaration naming another encoding
    if ($Xml -match '^\s*<\?xml[^>]*encoding\s*=\s*"(?!utf-16")[^"]*"') { throw '(1,40)::ERROR: unable to switch the encoding' }
    if ($kind -eq 'REGISTER' -and $case.register_fail) { throw 'SYNTHETIC_REGISTER_FAILURE' }
    $stored = $Xml
    if ($kind -eq 'REGISTER' -and $case.readback_tamper -eq 'disable_trigger') { $stored = $Xml.Replace('<Enabled>true</Enabled>', '<Enabled>false</Enabled>') }
    if ($kind -eq 'REGISTER' -and $case.readback_tamper -eq 'other_arguments') { $stored = $Xml.Replace('taifex_options_eod', 'taifex_options_delta') }
    if ($kind -eq 'REGISTER' -and $case.readback_tamper -eq 'other_logon') { $stored = $Xml.Replace('InteractiveToken', 'S4U') }
    $global:Store[$TaskName] = $stored
}
function Unregister-ScheduledTask {
    [CmdletBinding()] param([string]$TaskName, [switch]$Confirm)
    $global:Calls.Add("UNREGISTER $TaskName")
    [void]$global:Store.Remove($TaskName)
}
. $args[1]
$errorText = $null; $result = $null
try {
    if ($case.mode -eq 'unregister') { $result = Invoke-TaifexTaskUnregistration }
    else {
        for ($i = 0; $i -lt [int]$case.repeat; $i++) {
            $result = Invoke-TaifexTaskRegistration -TemplatePath $case.template -PythonPath $case.python -SourceRoot $case.source `
                -DataRoot $case.data -RuntimeRoot $case.runtime -DailyTime $case.time -OutputFile $case.output
        }
    }
} catch { $errorText = $_.Exception.Message }
[pscustomobject]@{ calls = @($global:Calls); store = $global:Store; error = $errorText } | ConvertTo-Json -Depth 5 -Compress
"""


@unittest.skipUnless(shutil.which("powershell.exe"), "Windows PowerShell not available")
class TaifexTaskRegistrationTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        tmp = Path(self._tmp.name).resolve()
        self.source = tmp / "InstalledRuntime"
        (self.source / "scripts").mkdir(parents=True)
        (self.source / "scripts" / "fetch_public_source_observations.py").write_text("# collector stub\n", encoding="utf-8")
        self.data = tmp / "LocalData" / "taifex"
        self.python = Path(sys.executable).resolve()
        self.tmp = tmp

    def run_case(self, existing=None, **overrides):
        case = {"existing": existing or {}, "mode": "register", "repeat": 1, "template": str(TEMPLATE),
                "python": str(self.python), "source": str(self.source), "data": str(self.data), "runtime": str(self.source),
                "time": "17:30", "output": "", "lookup_fail": [], "register_fail": False, "readback_tamper": ""}
        case.update(overrides)
        harness, data = self.tmp / "harness.ps1", self.tmp / "case.json"
        harness.write_text(HARNESS, encoding="utf-8")
        data.write_text(json.dumps(case), encoding="utf-8")
        done = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", str(harness),
                               str(data), str(LIB)], capture_output=True, encoding="utf-8", errors="replace", timeout=120)
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        return json.loads(done.stdout.strip().splitlines()[-1])

    def count(self, result, kind):
        return sum(1 for call in result["calls"] if call.startswith(kind + " "))

    def rendered(self, result):
        return ET.fromstring(result["store"][NAME])

    # --- positive -------------------------------------------------------------------------------------------------------
    def test_registers_enabled_daily_task_with_every_placeholder_resolved(self):
        result = self.run_case()
        self.assertIsNone(result["error"])
        self.assertEqual(self.count(result, "REGISTER"), 1)
        text = result["store"][NAME]
        self.assertNotRegex(text, r"__[A-Z][A-Z0-9_]*__")
        root = self.rendered(result)
        self.assertEqual(root.findtext("t:Settings/t:Enabled", namespaces=NS), "true")
        trigger = root.find("t:Triggers/t:CalendarTrigger", NS)
        self.assertEqual(trigger.findtext("t:Enabled", namespaces=NS), "true")
        self.assertEqual(trigger.findtext("t:StartBoundary", namespaces=NS)[11:16], "17:30")
        self.assertEqual(trigger.findtext("t:ScheduleByDay/t:DaysInterval", namespaces=NS), "1")
        self.assertEqual(len(root.findall("t:Triggers/*", NS)), 1)
        principal = root.find("t:Principals/t:Principal", NS)
        self.assertEqual(principal.findtext("t:RunLevel", namespaces=NS), "LeastPrivilege")
        self.assertEqual(root.findtext("t:Settings/t:WakeToRun", namespaces=NS), "false")
        self.assertEqual(root.findtext("t:Settings/t:StartWhenAvailable", namespaces=NS), "false")
        self.assertEqual(principal.findtext("t:LogonType", namespaces=NS), "InteractiveToken")
        self.assertNotIn("<!--", text)
        self.assertFalse(text.lstrip().startswith("<?xml"), "the scheduler takes the string as UTF-16: no utf-8 declaration")
        action = root.find("t:Actions/t:Exec", NS)
        self.assertEqual(Path(action.findtext("t:Command", namespaces=NS)), self.python)
        self.assertEqual(Path(action.findtext("t:WorkingDirectory", namespaces=NS)), self.source)
        args = shlex.split(action.findtext("t:Arguments", namespaces=NS))
        self.assertEqual(args[:4], ["-I", "-B", "-X", "utf8"])
        self.assertEqual(Path(args[4]), self.source / "scripts" / "fetch_public_source_observations.py")
        self.assertEqual(args[5:9], ["--fetch", "--source", "taifex_options_eod", "--output"])
        self.assertEqual(len(args), 10)
        output = Path(args[9])
        self.assertEqual(output, self.data / "taifex-options-eod-latest.json")
        self.assertNotIn(self.source, output.parents)
        self.assertNotIn("taifex_options_delta", text)
        self.assertTrue(self.data.is_dir(), "local output directory is created by the registration")
        self.assertFalse(output.exists(), "registration itself never collects")

    def test_reregistration_is_idempotent_and_leaves_one_identical_definition(self):
        first = self.run_case()
        second = self.run_case(existing={NAME: first["store"][NAME]}, repeat=2)
        self.assertIsNone(second["error"])
        self.assertEqual(second["store"][NAME], first["store"][NAME])
        self.assertEqual(len(second["store"]), 1)

    def test_rendered_action_fake_runs_the_real_collector_into_the_local_file(self):
        result = self.run_case()
        action = self.rendered(result).find("t:Actions/t:Exec", NS)
        args = shlex.split(action.findtext("t:Arguments", namespaces=NS))[4:]
        self.assertEqual(Path(args[0]), self.source / "scripts" / "fetch_public_source_observations.py")
        original, bodies = fixture.collector.collect, fixture.bodies()
        calls = []
        def transport(url):
            calls.append(url)
            return bodies[url]
        args[0] = str(ROOT / "scripts" / "fetch_public_source_observations.py")
        with patch.object(sys, "argv", args), patch.object(fixture.collector, "datetime", fixture.Clock), \
             patch.object(fixture.collector, "collect", side_effect=lambda selected: original(selected, transport=transport)), \
             redirect_stdout(StringIO()):
            self.assertEqual(fixture.collector.main(), 0)
        document = json.loads((self.data / "taifex-options-eod-latest.json").read_bytes())
        self.assertEqual(calls, [fixture.contract.TAIFEX_DAILY_URL])
        self.assertIs(document["publication_eligible"], False)
        self.assertEqual(document["items"][0]["source_id"], fixture.EOD)

    # --- negatives ------------------------------------------------------------------------------------------------------
    def refused(self, code, **overrides):
        result = self.run_case(**overrides)
        self.assertIn(code, result["error"] or "", result)
        self.assertEqual(self.count(result, "REGISTER"), 0)
        self.assertEqual(self.count(result, "UNREGISTER"), 0)

    def test_template_with_unresolved_placeholder_is_refused(self):
        bad = self.tmp / "bad.xml"
        bad.write_text(TEMPLATE.read_text(encoding="utf-8").replace("--fetch", "--fetch __EXTRA_PLACEHOLDER__"), encoding="utf-8")
        self.refused("TAIFEX_TASK_PLACEHOLDER_UNRESOLVED", template=str(bad))

    def test_output_inside_installed_payload_is_refused(self):
        self.refused("TAIFEX_TASK_OUTPUT_INSIDE_PAYLOAD", data=str(self.source / "data"), output=str(self.source / "data" / "x.json"))

    def test_data_root_that_contains_the_payload_is_refused(self):
        self.refused("TAIFEX_TASK_OUTPUT_INSIDE_PAYLOAD", data=str(self.tmp), output=str(self.tmp / "x.json"))

    def test_output_outside_data_root_is_refused(self):
        self.refused("TAIFEX_TASK_OUTPUT_OUTSIDE_DATA_ROOT", output=str(self.tmp / "elsewhere" / "x.json"))

    def test_traversal_in_output_is_refused(self):
        self.refused("TAIFEX_TASK_PATH_INVALID", output=str(self.data / ".." / "x.json"))

    def test_production_named_storage_is_refused(self):
        for name in ("production", "kv", "public", "sealed", "cloud"):
            with self.subTest(name=name):
                data = self.tmp / "L" / name / "taifex"
                self.refused("TAIFEX_TASK_OUTPUT_IN_PRODUCTION_STORAGE", data=str(data), output=str(data / "x.json"))

    def test_relative_and_placeholder_paths_are_refused(self):
        self.refused("TAIFEX_TASK_PATH_NOT_ABSOLUTE", python="python.exe")
        self.refused("TAIFEX_TASK_PATH_INVALID", python="C:/__PROJECT_PYTHON__/python.exe")

    def test_missing_python_or_collector_is_refused(self):
        self.refused("TAIFEX_TASK_PYTHON_MISSING", python=str(self.tmp / "nope" / "python.exe"))
        self.refused("TAIFEX_TASK_COLLECTOR_MISSING", source=str(self.tmp / "empty"), runtime=str(self.tmp / "empty"))

    def test_times_in_the_0800_window_and_malformed_times_are_refused(self):
        for value in ("07:45", "08:00", "08:30"):
            with self.subTest(value=value):
                self.refused("TAIFEX_TASK_TIME_IN_0800_WINDOW", time=value)
        self.refused("TAIFEX_TASK_TIME_INVALID", time="25:00")
        self.assertIsNone(self.run_case(time="08:31")["error"])

    def test_development_checkout_as_source_root_is_refused(self):
        checkout = self.tmp / "Checkout"
        (checkout / "scripts").mkdir(parents=True)
        (checkout / "scripts" / "fetch_public_source_observations.py").write_text("#\n", encoding="utf-8")
        (checkout / ".git").mkdir()
        self.refused("TAIFEX_TASK_SOURCE_IS_CHECKOUT", source=str(checkout), runtime=str(checkout))
        workspace = self.tmp / "_workspace" / "source"
        (workspace / "scripts").mkdir(parents=True)
        (workspace / "scripts" / "fetch_public_source_observations.py").write_text("#\n", encoding="utf-8")
        self.refused("TAIFEX_TASK_SOURCE_IS_CHECKOUT", source=str(workspace), runtime=str(workspace))

    def test_non_json_output_is_refused(self):
        self.refused("TAIFEX_TASK_OUTPUT_EXTENSION", output=str(self.data / "x.exe"))

    # --- rollback -------------------------------------------------------------------------------------------------------
    def test_readback_failure_on_fresh_install_unregisters(self):
        for tamper in ("disable_trigger", "other_arguments", "other_logon"):
            with self.subTest(tamper=tamper):
                result = self.run_case(readback_tamper=tamper)
                self.assertIn("TAIFEX_TASK_REGISTER_FAILED; rollback completed", result["error"] or "")
                self.assertEqual(self.count(result, "UNREGISTER"), 1)
                self.assertEqual(result["store"], {})

    def test_readback_failure_restores_the_previous_definition(self):
        old = self.run_case()["store"][NAME].replace("17:30", "18:10")
        result = self.run_case(existing={NAME: old}, readback_tamper="disable_trigger")
        self.assertIn("rollback completed", result["error"] or "")
        self.assertEqual(self.count(result, "RESTORE"), 1)
        self.assertEqual(result["store"][NAME], old)

    def test_ambiguous_lookup_changes_nothing(self):
        result = self.run_case(lookup_fail=[NAME])
        self.assertIn("TAIFEX_TASK_UNCHANGED", result["error"] or "")
        self.assertEqual(self.count(result, "REGISTER"), 0)

    def test_failed_register_call_is_rolled_back(self):
        result = self.run_case(register_fail=True)
        self.assertIn("TAIFEX_TASK_REGISTER_FAILED", result["error"] or "")
        self.assertEqual(result["store"], {})

    # --- unregister -----------------------------------------------------------------------------------------------------
    def test_unregister_removes_only_this_task_and_is_repeatable(self):
        installed = self.run_case()["store"][NAME]
        result = self.run_case(mode="unregister", existing={NAME: installed, "Other": "<x/>"})
        self.assertIsNone(result["error"])
        self.assertEqual(self.count(result, "UNREGISTER"), 1)
        self.assertEqual(list(result["store"]), ["Other"])
        again = self.run_case(mode="unregister", existing={"Other": "<x/>"})
        self.assertEqual(self.count(again, "UNREGISTER"), 0)
        self.assertEqual(list(again["store"]), ["Other"])


class TaifexEntryScriptTests(unittest.TestCase):
    def test_registrar_exists_and_is_the_only_consumer_of_the_template(self):
        self.assertTrue(ENTRY.is_file() and LIB.is_file())
        text = ENTRY.read_text(encoding="utf-8")
        self.assertIn("taifex-options-eod.disabled.xml", text)
        self.assertIn("[switch]$Unregister", text)
        self.assertNotIn("Start-ScheduledTask", text + LIB.read_text(encoding="utf-8"))
        consumers = set()
        for directory in (ROOT / "scripts", ROOT / "launcher"):
            for path in directory.rglob("*.ps1"):
                if "taifex-options-eod.disabled.xml" in path.read_text(encoding="utf-8-sig"):
                    consumers.add(path.name)
        for path in ROOT.glob("*.ps1"):
            self.assertNotIn("taifex-options-eod.disabled.xml", path.read_text(encoding="utf-8-sig"), path.name)
        self.assertEqual(consumers, {"register_taifex_options_eod_task.ps1"})

    def test_collector_action_never_selects_delta_or_default_sources(self):
        text = (TEMPLATE).read_text(encoding="utf-8")
        self.assertIn("--source taifex_options_eod", text)
        self.assertNotIn("taifex_options_delta", text)
        self.assertEqual(text.count("--source"), 1)

    @unittest.skipUnless(shutil.which("powershell.exe"), "Windows PowerShell not available")
    def test_validate_only_prints_resolved_action_without_touching_the_scheduler(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "Runtime"
            (source / "scripts").mkdir(parents=True)
            (source / "scripts" / "fetch_public_source_observations.py").write_text("#\n", encoding="utf-8")
            done = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", str(ENTRY),
                                   "-ValidateOnly", "-SourceRoot", str(source), "-PythonPath", sys.executable,
                                   "-DataRoot", str(Path(tmp) / "Data" / "taifex")], capture_output=True, encoding="utf-8",
                                  errors="replace", timeout=60)
            self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
            self.assertIn("TAIFEX_OPTIONS_EOD_TASK_VALIDATE = PASS", done.stdout)
            self.assertIn("schedule_mutation=false", done.stdout)
            self.assertIn("--source taifex_options_eod", done.stdout)
            self.assertNotRegex(done.stdout, r"__[A-Z][A-Z0-9_]*__")
            refused = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", str(ENTRY),
                                      "-ValidateOnly", "-SourceRoot", str(source), "-PythonPath", sys.executable,
                                      "-DataRoot", str(source / "data")], capture_output=True, encoding="utf-8", errors="replace", timeout=60)
            self.assertNotEqual(refused.returncode, 0)
            self.assertIn("TAIFEX_TASK_OUTPUT_INSIDE_PAYLOAD", refused.stdout + refused.stderr)


if __name__ == "__main__":
    unittest.main()
