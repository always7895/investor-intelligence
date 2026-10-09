"""O9 template/fake caller checks. Never touches the Windows scheduler."""
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
import json
from pathlib import Path
import shlex
import sys
import tempfile
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET

from tests import test_batch06_taifex_callers as fixture

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / 'scripts/task-templates/taifex-options-eod.disabled.xml'
NS = {'t': 'http://schemas.microsoft.com/windows/2004/02/mit/task'}


def read_template():
    return ET.fromstring(TEMPLATE.read_bytes())


class TaifexTaskTests(unittest.TestCase):
    def test_template_is_disabled_closed_action_and_has_no_registration_caller(self):
        root = read_template()
        self.assertEqual(root.findtext('t:Settings/t:Enabled', namespaces=NS), 'false')
        triggers = root.findall('t:Triggers/t:CalendarTrigger', NS)
        self.assertEqual(len(triggers), 1)
        self.assertEqual(triggers[0].findtext('t:Enabled', namespaces=NS), 'false')
        self.assertEqual(triggers[0].findtext('t:StartBoundary', namespaces=NS), '__LOCAL_START_BOUNDARY__')
        self.assertEqual(root.findtext('t:Settings/t:StartWhenAvailable', namespaces=NS), 'false')
        self.assertEqual(root.findtext('t:Settings/t:WakeToRun', namespaces=NS), 'false')
        self.assertEqual(root.findtext('t:Settings/t:MultipleInstancesPolicy', namespaces=NS), 'IgnoreNew')
        self.assertEqual(root.findtext('t:Settings/t:ExecutionTimeLimit', namespaces=NS), 'PT5M')
        principal = root.find('t:Principals/t:Principal', NS)
        self.assertEqual(principal.findtext('t:LogonType', namespaces=NS), 'InteractiveToken')
        self.assertEqual(principal.findtext('t:RunLevel', namespaces=NS), 'LeastPrivilege')
        self.assertIsNone(principal.find('t:UserId', NS))
        self.assertEqual(len(root.findall('t:Actions/*', NS)), 1)
        action = root.find('t:Actions/t:Exec', NS)
        self.assertEqual(action.findtext('t:Command', namespaces=NS), '__PROJECT_PYTHON__')
        self.assertEqual(action.findtext('t:WorkingDirectory', namespaces=NS), '__SOURCE_ROOT__')
        self.assertEqual(shlex.split(action.findtext('t:Arguments', namespaces=NS)), [
            '-I', '-B', '-X', 'utf8', '__SOURCE_ROOT__/scripts/fetch_public_source_observations.py',
            '--fetch', '--source', 'taifex_options_eod', '--output', '__LOCAL_OUTPUT__'])
        # No product entrypoint refers to this template/directory. Existing XML
        # registration branches restore exported task preimages, not template files.
        paths = list(ROOT.glob('*.ps1'))
        for directory in (ROOT / 'scripts', ROOT / 'launcher'):
            for suffix in ('*.ps1', '*.py', '*.cs'):
                paths.extend(directory.rglob(suffix))
        for path in paths:
            text = path.read_text(encoding='utf-8-sig')
            self.assertNotIn('taifex-options-eod.disabled.xml', text, str(path))
            self.assertNotIn('task-templates', text, str(path))

    def test_fake_run_uses_parsed_action_real_collector_and_local_atomic_writer(self):
        root = read_template()
        action = root.find('t:Actions/t:Exec', NS)
        original = fixture.collector.collect
        calls = []
        source_bodies = fixture.bodies()
        def transport(url):
            calls.append(url)
            return source_bodies[url]
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / 'local observation.json'
            args = shlex.split(action.findtext('t:Arguments', namespaces=NS))
            self.assertEqual(args[:4], ['-I', '-B', '-X', 'utf8'])
            args = [arg.replace('__SOURCE_ROOT__', ROOT.as_posix()).replace('__LOCAL_OUTPUT__', dest.as_posix())
                    for arg in args[4:]]
            self.assertEqual(Path(args[0]), ROOT / 'scripts/fetch_public_source_observations.py')
            with patch.object(sys, 'argv', args), patch.object(fixture.collector, 'datetime', fixture.Clock), \
                 patch.object(fixture.collector, 'collect', side_effect=lambda selected: original(selected, transport=transport)), \
                 redirect_stdout(StringIO()) as output:
                self.assertEqual(fixture.collector.main(), 0)
            document = json.loads(dest.read_bytes())
            self.assertEqual(document['status'], 'OK')
            self.assertIs(document['publication_eligible'], False)
            self.assertEqual(calls, [fixture.contract.TAIFEX_DAILY_URL])
            self.assertEqual(document['items'][0]['trade_date'], '2026-10-06')
            self.assertEqual(document['items'][0]['source_id'], fixture.EOD)
            self.assertIsNone(document['items'][0]['quote_time'])
            self.assertIs(document['items'][0]['line_quote_eligible'], False)
            self.assertIs(document['items'][0]['executable_quote'], False)
            self.assertEqual(json.loads(output.getvalue())['item_count'], 1)
        self.assertNotIn(fixture.EOD, fixture.collector.DEFAULT_SOURCES)
        self.assertNotIn(fixture.DELTA, fixture.collector.DEFAULT_SOURCES)

    def test_without_fetch_flag_cli_stops_before_transport_or_write(self):
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / 'not-created.json'
            with patch.object(sys, 'argv', ['collector', '--source', fixture.EOD, '--output', str(dest)]), \
                 patch.object(fixture.collector, 'collect') as collect, \
                 patch.object(fixture.collector, 'atomic_write_json') as write, redirect_stderr(StringIO()):
                with self.assertRaises(SystemExit) as stopped:
                    fixture.collector.main()
            self.assertEqual(stopped.exception.code, 2)
            collect.assert_not_called()
            write.assert_not_called()
            self.assertFalse(dest.exists())


if __name__ == '__main__':
    unittest.main()
