"""M5 owned Strata controller (scripts/v213_owned_strata.py): M4 protocol tests with IN-MEMORY fake launcher, process handle,
observer, OS-lock and HTTP objects only.

No network connection, child process, GPU or real Strata (:8080/:8081) is used and every file lives in a TemporaryDirectory.
These fakes prove the protocol sequencing, never Windows handles, job containment, OS locks or GPU release (native proof and the
Q2 trial stay open)."""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import sys
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import v213_model_profile as profile_lib  # noqa: E402
import v213_owned_strata as owned  # noqa: E402
from v213_compact_qa_gateway import POLICY  # noqa: E402

PORT = 18555
OWNER = 'investor-intelligence'
PEER = 'peer-project'
REQUESTERS = ('gateway', 'watchdog')
DIGEST = {name: hashlib.sha256(('m5-synthetic-' + name).encode('ascii')).hexdigest()
          for name in ('design', 'go', 'source', 'harness', 'observer')}
MARKER = POLICY['smoke_prompt'].removeprefix('Reply exactly ')
IDLE = {'queued': 0, 'in_flight': 0, 'background': 0}
BUSY = {'queued': 1, 'in_flight': 1, 'background': 0}
INTENT_KEYS = ('V213_RUNTIME_BINDING_JSON', 'V213_MODEL_PROFILE_JSON', 'II_LLAMA_BASE_URL', 'II_LOCAL_LLM_MODEL',
               'II_CAPABILITY_METADATA_URL')
BASE = 'http://127.0.0.1:' + str(PORT)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def pins(**changes):
    value = {'schema_version': 1, 'design_sha256': DIGEST['design'], 'go_sha256': DIGEST['go'],
             'source_sha256': DIGEST['source'], 'harness_sha256': DIGEST['harness'], 'observer_sha256': DIGEST['observer'],
             'owner': OWNER, 'holder': OWNER, 'port': PORT, 'requesters': list(REQUESTERS), 'min_context': 32768,
             'limits': {'ack_seconds': 30, 'drain_seconds': 60, 'stop_seconds': 30, 'startup_seconds': 120,
                        'answer_seconds': 30, 'lease_seconds': 600, 'observation_max_age_seconds': 5,
                        'log_quiet_seconds': 300, 'idle_gpu_memory_mib': 1024, 'model_gpu_memory_mib': 20000,
                        'poll_seconds': 1}}
    value.update(changes)
    return value


@contextmanager
def isolated_intent():
    with tempfile.TemporaryDirectory(prefix='m5-intent-') as directory, patch.dict(os.environ):
        for key in INTENT_KEYS:
            os.environ.pop(key, None)
        os.environ['LOCALAPPDATA'] = directory
        yield Path(directory)


class Clock:
    def __init__(self):
        self.now = 5000.0
        self.hooks = []

    def monotonic(self):
        return self.now

    def time(self):
        return 1800000000.0 + self.now

    def sleep(self, seconds):
        self.now += seconds
        for hook in list(self.hooks):
            hook()


class Lock:
    def __init__(self, table, path):
        self.table, self.path, self.lost = table, path, False

    def held(self):
        return not self.lost and self.table.get(self.path) is self

    def release(self):
        if self.table.get(self.path) is self:
            del self.table[self.path]


class Locks:
    """Fake non-blocking OS lock provider: one holder per path, never stolen."""

    def __init__(self):
        self.table = {}

    def acquire(self, path):
        if path in self.table:
            return None
        lock = self.table[path] = Lock(self.table, path)
        return lock


class Process:
    """Fake retained handle of one owned job; it records every terminate() it receives."""

    def __init__(self, world, pid, argv):
        self.world, self.pid, self.creation_time, self.argv = world, pid, 130000000 + pid, argv
        self.model_file = argv[argv.index('--model') + 1]
        self.code = None
        self.terminations = 0
        self.children = []
        self.stubborn = False

    def poll(self):
        return self.code

    def terminate(self):
        self.terminations += 1
        if not self.stubborn:
            self.exit(0)

    def wait(self, timeout):
        return self.code is not None

    def job_members(self):
        if self.code is not None:
            return []
        return [[self.pid, self.creation_time]] + [list(child) for child in self.children]

    def exit(self, code):
        self.code = code
        for hook in list(self.world.exit_hooks):
            hook(self)


class World:
    """Synthetic host: processes, GPU, ports and per-model fault switches."""

    def __init__(self, clock):
        self.clock = clock
        self.procs = []
        self.next_pid = 4100
        self.max_alive = 0
        self.serves = {}
        self.shared = {'8080': 'ABSENT', '8081': 'ABSENT'}
        self.foreign = []
        self.foreign_tasks = 0
        self.pending = lambda: IDLE
        self.direct = 0
        self.log_age = 86400
        self.stale = 0.0
        self.extra_memory = 0
        self.listener = None
        self.observer_sha = DIGEST['observer']
        self.never_ready = set()
        self.bad_answer = set()
        self.auth = set()
        self.aliases = set()
        self.second_row = set()
        self.launch_hooks = []
        self.exit_hooks = []
        self.snapshot_hooks = []

    def alive(self):
        return [proc for proc in self.procs if proc.code is None]


class Launcher:
    harness_sha256 = DIGEST['harness']

    def __init__(self, world):
        self.world = world
        self.argvs = []
        self.fail_on = set()

    def launch(self, argv, *, run_nonce):
        self.argvs.append(tuple(argv))
        if len(self.argvs) in self.fail_on or len(run_nonce) != 32:
            raise OSError('synthetic launch failure')
        world = self.world
        proc = Process(world, world.next_pid, list(argv))
        world.next_pid += 1
        world.procs.append(proc)
        world.max_alive = max(world.max_alive, len(world.alive()))
        for hook in list(world.launch_hooks):
            hook(proc)
        return proc


class Observer:
    def __init__(self, world):
        self.world = world

    def snapshot(self):
        world = self.world
        for hook in list(world.snapshot_hooks):
            hook()
        alive = world.alive()
        listener = world.listener or ([alive[-1].pid, alive[-1].creation_time] if alive else 'ABSENT')
        return {'schema_version': 1, 'observer_sha256': world.observer_sha, 'monotonic': world.clock.now - world.stale,
                'gpu': {'processes': [[proc.pid, proc.creation_time] for proc in alive] + [list(item) for item in world.foreign],
                        'memory_used_mib': 12000 * len(alive) + world.extra_memory, 'utilization_pct': 7},
                'herdr': {'foreign_gpu_tasks': world.foreign_tasks},
                'ports': {'8080': world.shared['8080'], '8081': world.shared['8081'], str(PORT): listener},
                'pending': dict(world.pending()), 'direct_clients': world.direct, 'log': {'age_seconds': world.log_age}}


class Http:
    """Fake selected-only transport; the synthetic auth flag is schema data, not a credential."""

    def __init__(self, world):
        self.world = world
        self.calls = []

    def request(self, method, url, *, payload=None, timeout=None, max_bytes=None):
        self.calls.append((method, url))
        world = self.world
        alive = world.alive()
        if not url.startswith(BASE + '/') or not alive:
            raise ConnectionRefusedError('synthetic: nothing listens')
        proc = alive[-1]
        model = world.serves[proc.model_file]
        path = url[len(BASE):]
        if path == '/health':
            return {'service': 'strata', 'status': 'ok', 'loaded': proc.model_file not in world.never_ready, 'model': model,
                    'api_key': model in world.auth, 'max_context': 262144}
        if path == '/v1/models':
            row = {'id': model, 'status': {'value': 'loaded'}, 'meta': {'n_ctx': 262144}}
            if model in world.aliases:
                row['aliases'] = ['alias-of-' + model]
            rows = [row] + ([{'id': 'second-model', 'status': {'value': 'loaded'}, 'meta': {'n_ctx': 262144}}]
                            if model in world.second_row else [])
            return {'data': rows}
        if path == '/v1/chat/completions':
            world.clock.now += 0.25
            bad = model in world.bad_answer or payload.get('model') != model
            return {'model': model, 'choices': [{'finish_reason': 'length' if bad else 'stop',
                                                 'message': {'content': 'partial' if bad else MARKER}}]}
        raise ConnectionRefusedError('synthetic: unknown route')


class Intent:
    """Fake request-intent store with failure switches."""

    def __init__(self):
        self.state = {'mode': 'LEGACY_ABSENT', 'binding_sha256': None, 'profile_sha256': None}
        self.commits = []
        self.unavailable = False
        self.fail_commit = False
        self.wrong_readback = False

    def snapshot(self):
        if self.unavailable:
            raise profile_lib.BindingUnavailable('BINDING_JSON_INVALID')
        return dict(self.state)

    def commit(self, binding, profile):
        self.commits.append(binding['model'])
        if self.fail_commit:
            self.unavailable = True
            raise OSError('synthetic torn intent write')
        digest = 'e' * 64 if self.wrong_readback else profile_lib.binding_sha256(binding, profile)
        self.state = {'mode': 'EXPLICIT_STRATA', 'binding_sha256': digest, 'profile_sha256': profile_lib.profile_sha256(profile)}

    def make_unavailable(self):
        self.unavailable = True


class Rig:
    def __init__(self, directory, *, intent=None, **pin_changes):
        self.dir = Path(directory)
        for name in ('gpu', 'gate', 'state', 'bin'):
            (self.dir / name).mkdir()
        roster = {'schema_version': 1, 'participants': [OWNER, PEER]}
        (self.dir / 'gpu' / 'participants.json').write_bytes(json.dumps(roster).encode('ascii'))
        self.clock = Clock()
        self.world = World(self.clock)
        self.locks = Locks()
        self.launcher = Launcher(self.world)
        self.http = Http(self.world)
        self.observer = Observer(self.world)
        self.intent = intent if intent is not None else Intent()
        self.reservation = owned.GpuReservation(self.dir / 'gpu', holder=OWNER, locks=self.locks, clock=self.clock)
        self.gate = owned.AdmissionGate(self.dir / 'gate', owner=OWNER, requesters=list(REQUESTERS))
        self.peer_acks = True
        self.requester_acks = set(REQUESTERS)
        self.acked = {}
        self.clock.hooks.append(self.cooperate)
        self.engine = self.dir / 'bin' / 'strata-synthetic.exe'
        self.engine.write_bytes(b'synthetic engine bytes')
        self.old = self.spec('old', 'synthetic-old')
        self.new = self.spec('new', 'synthetic-new')
        self.ctl = owned.OwnedStrataController(pins=pins(**pin_changes), state_dir=self.dir / 'state', launcher=self.launcher,
                                               http=self.http, observer=self.observer, locks=self.locks,
                                               reservation=self.reservation, gate=self.gate, intent=self.intent,
                                               clock=self.clock)

    def cooperate(self):
        """Synthetic cooperating peer and requesters: each acknowledges only what is currently recorded."""
        record = owned.read_reservation(self.dir / 'gpu')
        if record is not None and self.peer_acks and self.acked.get(PEER) != record['reservation_id']:
            owned.acknowledge_reservation(self.dir / 'gpu', PEER, record['reservation_id'])
            self.acked[PEER] = record['reservation_id']
        gate = self.gate.read()
        if gate['state'] == 'CLOSED':
            for requester in sorted(self.requester_acks):
                if self.acked.get(requester) != gate['generation']:
                    owned.requester_acknowledge(self.dir / 'gate', OWNER, requester, gate['generation'])
                    self.acked[requester] = gate['generation']

    def spec(self, name, model_id, config=b'{"n_ctx": 262144}\n'):
        model = self.dir / 'bin' / (name + '.gguf')
        model.write_bytes(('synthetic weights ' + name).encode('ascii'))
        settings = self.dir / 'bin' / (name + '.json')
        settings.write_bytes(config)
        self.world.serves[str(model)] = model_id
        profile = dict(schema_version=1, model=model_id, enable_thinking=False, reasoning_effort='none',
                       max_output_tokens=1024, smoke_output_tokens=128, timeout_ms=5000)
        return {'schema_version': 1, 'executable': str(self.engine), 'executable_sha256': sha(self.engine.read_bytes()),
                'model_file': str(model), 'model_sha256': sha(model.read_bytes()), 'config_file': str(settings),
                'config_sha256': sha(config), 'argv': ['--model', str(model), '--config', str(settings), '--port', str(PORT)],
                'model_id': model_id, 'profile': profile}

    def started(self):
        if self.ctl.open()['outcome'] != 'RESERVED' or self.ctl.start(self.old)['outcome'] != 'ADMISSION_OPEN':
            raise AssertionError('synthetic owned start failed')
        return self

    def session(self):
        return self.dir / 'state' / self.ctl._session

    def states(self):
        return [entry['state'] for entry in owned.read_journal(self.session())]

    def process(self, model_id):
        return [proc for proc in self.world.procs if self.world.serves[proc.model_file] == model_id]


class OwnedStrataControllerTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix='m5-owned-')
        self.addCleanup(self._tmp.cleanup)

    def make(self, **changes):
        return Rig(tempfile.mkdtemp(dir=self._tmp.name), **changes)

    def assertOutcome(self, result, outcome, reason):
        self.assertEqual((result['outcome'], result['reason']), (outcome, reason))

    def test_m4_state_order_single_model_owned_routes_and_clean_release(self):
        rig = self.make()
        opened = rig.ctl.open()
        self.assertOutcome(opened, 'RESERVED', 'OK')
        self.assertEqual(opened['participants'], [PEER])
        self.assertOutcome(rig.ctl.start(rig.old), 'ADMISSION_OPEN', 'OK')
        old = rig.process('synthetic-old')[0]
        admitted = owned.requester_admitted(rig.dir / 'gate', OWNER)
        self.assertEqual(admitted['binding_sha256'], rig.ctl._current['inst']['hashes']['binding'])
        before = len(rig.states())
        result = rig.ctl.replace(rig.new)
        self.assertOutcome(result, 'ADMISSION_OPEN', 'OK')
        self.assertEqual(rig.states()[before:], list(owned.STATES))
        new = rig.process('synthetic-new')[0]
        self.assertEqual((old.terminations, old.code, new.code), (1, 0, None))
        self.assertEqual(rig.world.max_alive, 1)
        self.assertEqual(rig.intent.state['binding_sha256'], result['binding_sha256'])
        self.assertEqual(rig.intent.commits, ['synthetic-old', 'synthetic-new'])
        gate = rig.gate.read()
        self.assertEqual((gate['state'], gate['binding_sha256']), ('OPEN', result['binding_sha256']))
        allowed = {('GET', BASE + '/health'), ('GET', BASE + '/v1/models'), ('POST', BASE + '/v1/chat/completions')}
        self.assertTrue(set(rig.http.calls) <= allowed)
        self.assertOutcome(rig.ctl.shutdown(), 'RELEASED', 'OK')
        self.assertEqual((new.terminations, rig.world.alive(), rig.ctl.status), (1, [], 'CLOSED'))
        self.assertIsNone(owned.read_reservation(rig.dir / 'gpu'))
        self.assertEqual(rig.locks.table, {})
        self.assertIsNone(owned.requester_admitted(rig.dir / 'gate', OWNER))
        entries = owned.read_journal(rig.session())
        for entry in entries:
            self.assertEqual((entry['design_sha256'], entry['go_sha256'], entry['source_sha256'], entry['qualification']),
                             (DIGEST['design'], DIGEST['go'], DIGEST['source'], 'UNQUALIFIED'))
        raw = b''.join(path.read_bytes() for path in sorted(rig.session().iterdir()))
        for leaked in (MARKER, POLICY['smoke_prompt'], json.dumps(str(rig.dir))[1:-1], 'strata-synthetic.exe', '.gguf', '--model'):
            self.assertNotIn(leaked.encode('ascii'), raw)
        self.assertEqual(owned.recover(rig.session(), rig.gate)['outcome'], 'CLEAN')

    def test_commit_goes_through_the_existing_pending_barrier_with_readback(self):
        with isolated_intent():
            rig = self.make(intent=owned.ProfileIntent(ROOT)).started()
            self.assertOutcome(rig.ctl.replace(rig.new), 'ADMISSION_OPEN', 'OK')
            resolved = profile_lib.resolve_binding(str(ROOT))
            self.assertEqual((resolved['mode'], resolved['binding']['base_url'], resolved['binding']['model']),
                             ('EXPLICIT_STRATA', BASE, 'synthetic-new'))
            self.assertEqual(resolved['binding_sha256'], rig.ctl._current['inst']['hashes']['binding'])
            rig.intent.make_unavailable()
            with self.assertRaises(profile_lib.BindingUnavailable):
                profile_lib.resolve_binding(str(ROOT))

    def test_protected_ports_pins_specs_and_unadmitted_harness_fail_closed(self):
        for port in sorted(owned.PROTECTED_PORTS):
            with self.subTest(port=port), self.assertRaisesRegex(owned.OwnedInstanceUnavailable, '^PINS_PORT_PROTECTED$'):
                owned.validate_pins(pins(port=port))
        with self.assertRaisesRegex(owned.OwnedInstanceUnavailable, '^PINS_DIGEST_INVALID$'):
            owned.validate_pins(pins(design_sha256='0' * 63))
        with self.assertRaisesRegex(owned.OwnedInstanceUnavailable, '^PINS_SCHEMA_INVALID$'):
            owned.validate_pins({key: value for key, value in pins().items() if key != 'go_sha256'})
        limits = pins()['limits']  # longest pinned un-renewed wait here: poll 1 + startup 120 + answer 30 = 151
        for changes in ({'lease_seconds': 60, 'startup_seconds': 120}, {'lease_seconds': 140},
                        {'lease_seconds': 100, 'stop_seconds': 50, 'startup_seconds': 10},
                        {'lease_seconds': 100, 'ack_seconds': 80, 'startup_seconds': 10}):
            with self.subTest(limits=changes), self.assertRaisesRegex(owned.OwnedInstanceUnavailable, '^PINS_LIMITS_INVALID$'):
                owned.validate_pins(pins(limits=dict(limits, **changes)))
        self.assertEqual(owned.validate_pins(pins(limits=dict(limits, lease_seconds=152)))['limits']['lease_seconds'], 152)
        with self.assertRaisesRegex(owned.OwnedInstanceUnavailable, '^PINS_REQUESTERS_INVALID$'):
            owned.validate_pins(pins(requesters=[]))
        rig = self.make()
        with self.assertRaisesRegex(owned.OwnedInstanceUnavailable, '^GATE_REQUESTERS_INVALID$'):
            owned.AdmissionGate(rig.dir / 'gate', owner=OWNER, requesters=[])
        model = rig.new['model_file']
        for argv, code in ((['--model', model, '--port', '8080'], 'SPEC_ARGV_PROTECTED_PORT'),
                           (['--model', model, '--host=127.0.0.1:8081', '--port', str(PORT)], 'SPEC_ARGV_PROTECTED_PORT'),
                           (['--model', model], 'SPEC_ARGV_PORT_UNPINNED'),
                           (['--model', model, '--port', str(PORT), '--fetch', 'https://example.invalid/w'], 'SPEC_ARGV_FORBIDDEN'),
                           (['--model', model, '--port', str(PORT), '--before_load', 'x'], 'SPEC_ARGV_FORBIDDEN')):
            with self.subTest(argv=argv[2:]), self.assertRaisesRegex(owned.OwnedInstanceUnavailable, '^' + code + '$'):
                owned.prepare_instance(dict(rig.new, argv=argv), PORT)
        for spec, port, code in ((dict(rig.new, model_sha256='0' * 64), PORT, 'SPEC_HASH_MISMATCH'),
                                 (dict(rig.new, model_id='synthetic-old'), PORT, 'SPEC_MODEL_PROFILE_MISMATCH'),
                                 (rig.new, 8080, 'PINS_PORT_PROTECTED')):
            with self.subTest(code=code), self.assertRaisesRegex(owned.OwnedInstanceUnavailable, '^' + code + '$'):
                owned.prepare_instance(spec, port)
        launcher = Launcher(rig.world)
        launcher.harness_sha256 = 'f' * 64
        with self.assertRaisesRegex(owned.OwnedInstanceUnavailable, '^HARNESS_NOT_ADMITTED$'):
            owned.OwnedStrataController(pins=pins(), state_dir=rig.dir / 'state', launcher=launcher, http=rig.http,
                                        observer=rig.observer, locks=rig.locks, reservation=rig.reservation, gate=rig.gate,
                                        intent=rig.intent, clock=rig.clock)
        self.assertEqual((rig.launcher.argvs, launcher.argvs, rig.http.calls), ([], [], []))

    def test_busy_unknown_or_shared_gpu_refuses_open_before_any_reservation(self):
        def under_reservation(rig):  # only the recheck under the held reservation sees it: record and both locks released
            seen = []

            def hook():
                seen.append(True)
                if len(seen) == 2:
                    rig.world.foreign.append([9001, 5])
            rig.world.snapshot_hooks.append(hook)

        cases = (('GPU_FOREIGN_PROCESS', lambda rig: rig.world.foreign.append([9001, 5])),
                 ('GPU_BUSY', lambda rig: setattr(rig.world, 'extra_memory', 4096)),
                 ('SHARED_STRATA_PRESENT', lambda rig: rig.world.shared.update({'8080': [9002, 6]})),
                 ('SHARED_STRATA_PRESENT', lambda rig: rig.world.shared.update({'8081': [9003, 7]})),
                 ('OBSERVATION_AMBIGUOUS', lambda rig: rig.world.shared.update({'8081': 'UNKNOWN'})),
                 ('OBSERVATION_STALE', lambda rig: setattr(rig.world, 'stale', 6.0)),
                 ('OBSERVER_NOT_ADMITTED', lambda rig: setattr(rig.world, 'observer_sha', 'f' * 64)),
                 ('GPU_FOREIGN_TASK', lambda rig: setattr(rig.world, 'foreign_tasks', 1)),
                 ('SHARED_LOG_ACTIVE', lambda rig: setattr(rig.world, 'log_age', 10)),
                 ('PORT_FOREIGN_LISTENER', lambda rig: setattr(rig.world, 'listener', [9004, 8])),
                 ('RESERVATION_ACK_MISSING', lambda rig: setattr(rig, 'peer_acks', False)),
                 ('GPU_FOREIGN_PROCESS', under_reservation))
        for code, fault in cases:
            with self.subTest(code=code):
                rig = self.make()
                fault(rig)
                self.assertOutcome(rig.ctl.open(), 'REFUSED', code)
                self.assertEqual(rig.ctl.status, 'CLOSED')
                self.assertEqual((rig.launcher.argvs, rig.http.calls, rig.locks.table), ([], [], {}))
                self.assertIsNone(owned.read_reservation(rig.dir / 'gpu'))
                self.assertEqual(owned.recover(rig.session(), rig.gate)['outcome'], 'CLEAN')
                with self.assertRaisesRegex(owned.OwnedInstanceUnavailable, '^CONTROLLER_NOT_RESERVED$'):
                    rig.ctl.start(rig.old)

    def test_cooperative_reservation_is_exclusive_acknowledged_and_never_reclaimed(self):
        rig = self.make()
        gpu = rig.dir / 'gpu'
        lease = rig.reservation.acquire(lease_seconds=600, ack_seconds=5, poll_seconds=1)
        self.assertEqual(lease['participants'], [PEER])
        self.assertEqual(owned.read_reservation(gpu)['reservation_id'], lease['reservation_id'])
        rival = owned.GpuReservation(gpu, holder=PEER, locks=rig.locks, clock=rig.clock)
        with self.assertRaisesRegex(owned.OwnedInstanceUnavailable, '^RESERVATION_BUSY$'):
            rival.acquire(lease_seconds=600, ack_seconds=5, poll_seconds=1)
        with self.assertRaisesRegex(owned.OwnedInstanceUnavailable, '^RESERVATION_ID_MISMATCH$'):
            owned.acknowledge_reservation(gpu, PEER, '0' * 32)
        rig.reservation.release()
        self.assertIsNone(owned.read_reservation(gpu))
        self.assertEqual(rig.locks.table, {})
        with self.assertRaisesRegex(owned.OwnedInstanceUnavailable, '^RESERVATION_MISSING$'):
            rig.reservation.release()
        rig.peer_acks = False  # the left-over acknowledgment names the previous id and never counts for a new one
        with self.assertRaisesRegex(owned.OwnedInstanceUnavailable, '^RESERVATION_ACK_MISSING$'):
            rig.reservation.acquire(lease_seconds=600, ack_seconds=3, poll_seconds=1)
        self.assertIsNone(owned.read_reservation(gpu))
        self.assertEqual(rig.locks.table, {})
        stale = owned._canonical({'schema_version': 1, 'reservation_id': 'a' * 32, 'holder': PEER, 'roster_sha256': 'b' * 64,
                                  'expires_epoch': 1})
        (gpu / 'reservation.json').write_bytes(stale)
        rig.clock.now += 10 ** 6
        with self.assertRaisesRegex(owned.OwnedInstanceUnavailable, '^RESERVATION_PRESENT_RECOVERY_REQUIRED$'):
            rig.reservation.acquire(lease_seconds=600, ack_seconds=3, poll_seconds=1)
        self.assertEqual((gpu / 'reservation.json').read_bytes(), stale)
        self.assertEqual(rig.locks.table, {})
        (gpu / 'reservation.json').unlink()
        (gpu / 'participants.json').write_bytes(b'{"schema_version":1,"participants":["peer-project"]}')
        with self.assertRaisesRegex(owned.OwnedInstanceUnavailable, '^RESERVATION_ROSTER_INVALID$'):
            rig.reservation.acquire(lease_seconds=600, ack_seconds=3, poll_seconds=1)

    def test_lost_lock_expired_lease_or_withdrawn_ack_is_recovery_without_any_stop(self):
        def lose_lifecycle(rig):
            rig.ctl._lifecycle.lost = True

        def lose_reservation_lock(rig):
            rig.reservation._lock.lost = True

        def expire(rig):
            rig.clock.now += 10 ** 5

        def withdraw(rig):
            rig.peer_acks = False
            (rig.dir / 'gpu' / ('ack-' + PEER + '.json')).unlink()

        for fault, code in ((lose_lifecycle, 'LIFECYCLE_LOCK_LOST'), (lose_reservation_lock, 'RESERVATION_LOCK_LOST'),
                            (expire, 'RESERVATION_EXPIRED'), (withdraw, 'RESERVATION_ACK_WITHDRAWN')):
            with self.subTest(code=code):
                rig = self.make().started()
                old = rig.process('synthetic-old')[0]
                fired = []

                def hook(rig=rig, fault=fault, fired=fired):
                    if rig.ctl._last_state == 'DRAINED' and not fired:
                        fired.append(True)
                        fault(rig)

                rig.world.snapshot_hooks.append(hook)
                self.assertOutcome(rig.ctl.replace(rig.new), 'RECOVERY_REQUIRED', code)
                self.assertEqual((old.terminations, old.code, len(rig.launcher.argvs)), (0, None, 1))
                self.assertEqual(rig.gate.read()['state'], 'CLOSED')
                self.assertIsNone(owned.requester_admitted(rig.dir / 'gate', OWNER))
                self.assertIsNotNone(owned.read_reservation(rig.dir / 'gpu'))
                self.assertTrue(rig.intent.unavailable)
                for call in (lambda: rig.ctl.replace(rig.new), rig.ctl.shutdown):
                    with self.assertRaisesRegex(owned.OwnedInstanceUnavailable, '^CONTROLLER_RECOVERY_REQUIRED$'):
                        call()
                self.assertEqual(owned.recover(rig.session(), rig.gate)['phase'], 'RECOVERY_REQUIRED_RECORDED')

    def test_pid_reuse_identity_drift_and_foreign_handles_are_never_stopped(self):
        rig = self.make().started()
        old = rig.process('synthetic-old')[0]
        rig.world.listener = [old.pid, old.creation_time + 1]  # same PID, other creation time: a reused PID
        self.assertOutcome(rig.ctl.replace(rig.new), 'REFUSED', 'LISTENER_IDENTITY_MISMATCH')
        self.assertEqual((old.terminations, rig.gate.read()['state'], len(rig.launcher.argvs)), (0, 'OPEN', 1))
        rig.world.listener = None
        stranger = Process(rig.world, 777, ['--model', rig.old['model_file']])
        copied = dict(rig.ctl._current)  # the same handle object, but not the record the launcher returned
        for record in (dict(copied, handle=stranger, identity=(777, stranger.creation_time)), copied):
            with self.assertRaisesRegex(owned.OwnedInstanceUnavailable, '^OWNERSHIP_NOT_PROVEN$'):
                rig.ctl._stop(record)
        self.assertEqual((stranger.terminations, old.terminations), (0, 0))
        old.creation_time += 1  # the retained handle no longer matches its recorded creation identity
        self.assertOutcome(rig.ctl.replace(rig.new), 'RECOVERY_REQUIRED', 'OWNERSHIP_IDENTITY_DRIFT')
        self.assertEqual((old.terminations, len(rig.launcher.argvs)), (0, 1))

    def test_candidate_faults_roll_back_to_the_restarted_former_instance(self):
        def served_other(rig):
            rig.world.serves[rig.new['model_file']] = 'synthetic-other'

        def child(rig):
            rig.world.launch_hooks.append(
                lambda proc: proc.children.append([9100, 1]) if proc.model_file == rig.new['model_file'] else None)

        def crash(rig):
            rig.world.launch_hooks.append(lambda proc: proc.exit(3) if proc.model_file == rig.new['model_file'] else None)

        def foreign_listener(rig):
            def on_launch(proc):
                if proc.model_file == rig.new['model_file']:
                    rig.world.listener = [proc.pid, proc.creation_time + 5]
            rig.world.launch_hooks.append(on_launch)
            rig.world.exit_hooks.append(lambda proc: setattr(rig.world, 'listener', None))

        def memory(rig):
            def on_launch(proc):
                if proc.model_file == rig.new['model_file']:
                    rig.world.extra_memory = 9000
            rig.world.launch_hooks.append(on_launch)
            rig.world.exit_hooks.append(lambda proc: setattr(rig.world, 'extra_memory', 0))

        def config_changed(rig):
            def on_exit(proc):
                if proc.model_file == rig.old['model_file']:
                    Path(rig.new['config_file']).write_bytes(b'{"n_ctx": 1}\n')
            rig.world.exit_hooks.append(on_exit)

        def direct_client(rig):
            def on_launch(proc):
                if proc.model_file == rig.new['model_file']:
                    rig.world.direct = 1
            rig.world.launch_hooks.append(on_launch)
            rig.world.exit_hooks.append(lambda proc: setattr(rig.world, 'direct', 0))

        cases = (('STRATA_HEALTH_IDENTITY_UNAVAILABLE', served_other),
                 ('STRATA_SELECTED_CONTEXT_UNAVAILABLE', lambda rig: rig.world.aliases.add('synthetic-new')),
                 ('STRATA_CATALOG_NOT_SINGLE_MODEL', lambda rig: rig.world.second_row.add('synthetic-new')),
                 ('ENDPOINT_AUTH_REQUIRED', lambda rig: rig.world.auth.add('synthetic-new')),
                 ('ANSWER_INCOMPLETE', lambda rig: rig.world.bad_answer.add('synthetic-new')),
                 ('CANDIDATE_STARTUP_TIMEOUT', lambda rig: rig.world.never_ready.add(rig.new['model_file'])),
                 ('UNEXPECTED_CHILD_PROCESS', child), ('INSTANCE_EXITED', crash),
                 ('LISTENER_IDENTITY_MISMATCH', foreign_listener), ('RESOURCE_LIMIT_EXCEEDED', memory),
                 ('SPEC_HASH_MISMATCH', config_changed), ('TRIAL_INELIGIBLE_DIRECT_CLIENT', direct_client))
        for code, fault in cases:
            with self.subTest(code=code):
                rig = self.make().started()
                old = rig.process('synthetic-old')[0]
                fault(rig)
                result = rig.ctl.replace(rig.new)
                self.assertOutcome(result, 'ROLLED_BACK', code)
                restored = rig.process('synthetic-old')[-1]
                self.assertIsNot(restored, old)
                self.assertEqual((old.terminations, restored.code, rig.world.max_alive), (1, None, 1))
                self.assertEqual([proc for proc in rig.world.alive()], [restored])
                self.assertEqual(rig.ctl._current['handle'], restored)
                self.assertEqual(rig.intent.commits, ['synthetic-old'])
                gate = rig.gate.read()
                self.assertEqual((gate['state'], gate['binding_sha256']), ('OPEN', result['binding_sha256']))
                self.assertEqual(result['binding_sha256'], rig.ctl._current['inst']['hashes']['binding'])
                self.assertEqual(rig.states()[-3:], ['TRANSITION_FAILED', 'ROLLBACK_STARTED', 'ROLLED_BACK'])
                self.assertEqual(rig.ctl.status, 'RESERVED')

    def test_unaccounted_client_at_every_candidate_observation_is_never_admitted(self):
        # Exactly one observation sees the client, so each candidate-side check (both VERIFIED snapshots, the pre-commit one and
        # the agreement) must refuse it by itself; after the commit the refusal is RECOVERY_REQUIRED, never a rollback.
        for stage, nth, outcome in (('CANDIDATE_READY', 1, 'ROLLED_BACK'), ('CANDIDATE_READY', 2, 'ROLLED_BACK'),
                                    ('VERIFIED', 1, 'ROLLED_BACK'), ('COMMITTED', 1, 'RECOVERY_REQUIRED')):
            with self.subTest(stage=stage, nth=nth):
                rig = self.make().started()
                old = rig.process('synthetic-old')[0]
                seen = []

                def hook(rig=rig, stage=stage, nth=nth, seen=seen):
                    if rig.ctl._last_state == stage:
                        seen.append(True)
                    rig.world.direct = 1 if rig.ctl._last_state == stage and len(seen) == nth else 0

                rig.world.snapshot_hooks.append(hook)
                self.assertOutcome(rig.ctl.replace(rig.new), outcome, 'TRIAL_INELIGIBLE_DIRECT_CLIENT')
                candidate = rig.process('synthetic-new')[0]
                admitted = owned.requester_admitted(rig.dir / 'gate', OWNER)
                self.assertEqual((old.terminations, rig.world.max_alive), (1, 1))
                if outcome == 'ROLLED_BACK':
                    self.assertEqual((candidate.terminations, candidate.code, len(rig.launcher.argvs)), (1, 0, 3))
                    self.assertEqual(admitted['binding_sha256'], rig.ctl._current['inst']['hashes']['binding'])
                    self.assertEqual((rig.intent.commits, rig.ctl.status), (['synthetic-old'], 'RESERVED'))
                else:
                    self.assertEqual((candidate.terminations, candidate.code, len(rig.launcher.argvs)), (0, None, 2))
                    self.assertEqual((admitted, rig.gate.read()['state'], rig.intent.unavailable), (None, 'CLOSED', True))
                    self.assertEqual(rig.intent.commits, ['synthetic-old', 'synthetic-new'])
                    self.assertEqual(owned.recover(rig.session(), rig.gate)['phase'], 'RECOVERY_REQUIRED_RECORDED')

    def test_drain_refusals_restore_the_unchanged_old_generation(self):
        cases = (('DRAIN_TIMEOUT', lambda rig: setattr(rig.world, 'pending', lambda: BUSY)),
                 ('DRAIN_RACE', lambda rig: setattr(rig.world, 'pending',
                                                     lambda: BUSY if rig.ctl._last_state == 'DRAINED' else IDLE)),
                 ('TRIAL_INELIGIBLE_UNACKED', lambda rig: setattr(rig, 'requester_acks', {'gateway'})),
                 ('TRIAL_INELIGIBLE_DIRECT_CLIENT', lambda rig: setattr(rig.world, 'direct', 1)))
        for code, fault in cases:
            with self.subTest(code=code):
                rig = self.make().started()
                old = rig.process('synthetic-old')[0]
                before = rig.gate.read()
                fault(rig)
                self.assertOutcome(rig.ctl.replace(rig.new), 'REFUSED_RESTORED', code)
                self.assertEqual((old.terminations, old.code, len(rig.launcher.argvs)), (0, None, 1))
                after = rig.gate.read()
                self.assertEqual((after['state'], after['binding_sha256'], after['generation']),
                                 ('OPEN', before['binding_sha256'], before['generation'] + 2))
                self.assertEqual(owned.requester_admitted(rig.dir / 'gate', OWNER)['generation'], after['generation'])
                self.assertEqual(rig.states()[-2:], ['TRANSITION_FAILED', 'ABORTED_RESTORED'])
                self.assertEqual((rig.ctl.status, rig.intent.commits), ('RESERVED', ['synthetic-old']))

    def test_failure_at_every_journal_write_is_recovery_and_never_a_second_model(self):
        original = owned.Journal.append
        for failing in range(1, len(owned.STATES) + 1):
            with self.subTest(write=owned.STATES[failing - 1]):
                rig = self.make().started()
                old = rig.process('synthetic-old')[0]
                count = [0]

                def append(journal, record, count=count, failing=failing):
                    count[0] += 1
                    if count[0] == failing:
                        raise owned.OwnedInstanceUnavailable('JOURNAL_WRITE_FAILED')
                    return original(journal, record)

                with patch.object(owned.Journal, 'append', append):
                    result = rig.ctl.replace(rig.new)
                self.assertOutcome(result, 'RECOVERY_REQUIRED', 'JOURNAL_WRITE_FAILED')
                self.assertEqual(rig.world.max_alive, 1)
                self.assertEqual(rig.gate.read()['state'], 'CLOSED')
                self.assertTrue(rig.intent.unavailable)
                self.assertEqual(old.terminations, 1 if failing >= 5 else 0)
                self.assertEqual(len(rig.launcher.argvs), 2 if failing >= 6 else 1)
                self.assertEqual(rig.intent.commits, ['synthetic-old'] + (['synthetic-new'] if failing >= 8 else []))
                self.assertEqual(owned.recover(rig.session(), rig.gate)['phase'], 'RECOVERY_REQUIRED_RECORDED')

    def test_uncertain_intent_commit_keeps_admission_closed_and_intent_unavailable(self):
        for flag, code in (('fail_commit', 'INTENT_COMMIT_UNCERTAIN'), ('wrong_readback', 'INTENT_READBACK_MISMATCH')):
            with self.subTest(code=code):
                rig = self.make().started()
                setattr(rig.intent, flag, True)
                self.assertOutcome(rig.ctl.replace(rig.new), 'RECOVERY_REQUIRED', code)
                candidate = rig.process('synthetic-new')[0]
                self.assertEqual((candidate.code, candidate.terminations, len(rig.launcher.argvs)), (None, 0, 2))
                self.assertEqual((rig.gate.read()['state'], rig.intent.unavailable, rig.world.max_alive), ('CLOSED', True, 1))
                self.assertEqual(owned.recover(rig.session())['phase'], 'RECOVERY_REQUIRED_RECORDED')

    def test_failed_rollback_is_recovery_and_never_starts_a_second_model(self):
        def stubborn(rig):
            rig.world.bad_answer.add('synthetic-new')
            rig.world.launch_hooks.append(
                lambda proc: setattr(proc, 'stubborn', True) if proc.model_file == rig.new['model_file'] else None)

        def former_fails(rig):
            rig.world.bad_answer.update({'synthetic-new', 'synthetic-old'})

        def relaunch_fails(rig):
            rig.world.bad_answer.add('synthetic-new')
            rig.launcher.fail_on.add(3)

        def predecessor_changed(rig):
            rig.world.bad_answer.add('synthetic-new')
            Path(rig.old['model_file']).write_bytes(b'tampered synthetic weights')

        for fault, code, launches in ((stubborn, 'STOP_UNPROVEN', 2), (former_fails, 'ROLLBACK_FAILED', 3),
                                      (relaunch_fails, 'LAUNCH_OUTCOME_UNKNOWN', 3),
                                      (predecessor_changed, 'PREDECESSOR_BYTES_CHANGED', 2)):
            with self.subTest(code=code):
                rig = self.make().started()
                fault(rig)
                self.assertOutcome(rig.ctl.replace(rig.new), 'RECOVERY_REQUIRED', code)
                self.assertEqual((len(rig.launcher.argvs), rig.world.max_alive), (launches, 1))
                self.assertEqual(rig.gate.read()['state'], 'CLOSED')
                self.assertIn('ROLLBACK_STARTED', rig.states())
                self.assertEqual(owned.recover(rig.session(), rig.gate)['phase'], 'RECOVERY_REQUIRED_RECORDED')

    def test_gpu_not_released_after_the_old_exit_blocks_the_candidate(self):
        def foreign_gpu(rig, proc):
            rig.world.foreign.append([9200, 9])

        def shared_strata(rig, proc):
            rig.world.shared['8080'] = [9300, 10]

        for fault in (foreign_gpu, shared_strata):
            with self.subTest(fault=fault.__name__):
                rig = self.make().started()
                rig.world.exit_hooks.append(
                    lambda proc, rig=rig, fault=fault: fault(rig, proc) if proc.model_file == rig.old['model_file'] else None)
                self.assertOutcome(rig.ctl.replace(rig.new), 'RECOVERY_REQUIRED', 'GPU_RELEASE_UNPROVEN')
                self.assertEqual((len(rig.launcher.argvs), rig.gate.read()['state']), (1, 'CLOSED'))
                self.assertEqual(rig.states()[-2:], ['DRAINED', 'RECOVERY_REQUIRED'])  # no OWNED_OLD_EXITED, no rollback

    def test_first_start_failure_rolls_back_to_no_instance_with_admission_closed(self):
        rig = self.make()
        rig.world.bad_answer.add('synthetic-old')
        self.assertOutcome(rig.ctl.open(), 'RESERVED', 'OK')
        self.assertOutcome(rig.ctl.start(rig.old), 'ROLLED_BACK', 'ANSWER_INCOMPLETE')
        self.assertEqual((rig.world.alive(), rig.gate.read()['state'], rig.intent.commits), ([], 'CLOSED', []))
        self.assertIsNone(owned.requester_admitted(rig.dir / 'gate', OWNER))
        self.assertOutcome(rig.ctl.shutdown(), 'RELEASED', 'OK')
        self.assertEqual(owned.recover(rig.session(), rig.gate)['outcome'], 'CLEAN')

    def test_hooked_config_is_refused_in_precheck_without_side_effects(self):
        rig = self.make().started()
        hooked = rig.spec('hooked', 'synthetic-hooked', config=b'{"before_load": "x"}\n')
        before = rig.gate.read()
        self.assertOutcome(rig.ctl.replace(hooked), 'REFUSED', 'SPEC_CONFIG_FORBIDDEN')
        self.assertEqual((rig.gate.read(), len(rig.launcher.argvs), rig.states()[-1]), (before, 1, 'REFUSED'))

    def test_recover_is_read_only_idempotent_and_names_every_interrupted_phase(self):
        rig = self.make().started()
        self.assertOutcome(rig.ctl.replace(rig.new), 'ADMISSION_OPEN', 'OK')
        self.assertOutcome(rig.ctl.shutdown(), 'RELEASED', 'OK')
        crashed = self.make().started()
        crashed.world.launch_hooks.append(
            lambda proc: proc.exit(3) if proc.model_file == crashed.new['model_file'] else None)
        self.assertOutcome(crashed.ctl.replace(crashed.new), 'ROLLED_BACK', 'INSTANCE_EXITED')
        expected = {'PRECHECK': 'SESSION_INTERRUPTED', 'RESERVED': 'SESSION_INTERRUPTED', 'ADMISSION_OPEN': 'SESSION_INTERRUPTED',
                    'ROLLED_BACK': 'SESSION_INTERRUPTED', 'ADMISSION_CLOSED': 'ADMISSION_CLOSED_OLD_RUNNING',
                    'DRAINED': 'ADMISSION_CLOSED_OLD_RUNNING', 'OWNED_OLD_EXITED': 'OLD_EXITED_NO_CANDIDATE',
                    'CANDIDATE_READY': 'CANDIDATE_READY_POINTER_NOT_COMMITTED',
                    'VERIFIED': 'CANDIDATE_READY_POINTER_NOT_COMMITTED', 'COMMITTED': 'COMMITTED_ADMISSION_NOT_OPEN',
                    'TRANSITION_FAILED': 'ROLLBACK_INCOMPLETE', 'ROLLBACK_STARTED': 'ROLLBACK_INCOMPLETE'}
        seen = set()
        for source, complete in ((rig.session(), True), (crashed.session(), False)):
            names = sorted(path.name for path in source.iterdir())
            entries = owned.read_journal(source)
            for index in range(1, len(names) + (0 if complete else 1)):
                prefix = Path(tempfile.mkdtemp(dir=self._tmp.name)) / 'session'
                prefix.mkdir()
                for name in names[:index]:
                    shutil.copyfile(source / name, prefix / name)
                before = {path.name: path.read_bytes() for path in prefix.iterdir()}
                first, second = owned.recover(prefix), owned.recover(prefix)
                self.assertEqual(first, second)
                self.assertEqual({path.name: path.read_bytes() for path in prefix.iterdir()}, before)
                self.assertEqual((first['outcome'], first['phase']), ('RECOVERY_REQUIRED', expected[entries[index - 1]['state']]))
                self.assertEqual(first['actions'], [])
                seen.add(first['phase'])
        self.assertEqual(seen, set(expected.values()))
        self.assertEqual(owned.recover(rig.session(), rig.gate)['outcome'], 'CLEAN')
        rig.gate.close('txn-synthetic')
        self.assertEqual(owned.recover(rig.session(), rig.gate)['phase'], 'GENERATION_DISAGREEMENT')
        for damage in ('flip', 'gap'):
            with self.subTest(damage=damage):
                copy = Path(tempfile.mkdtemp(dir=self._tmp.name)) / 'session'
                shutil.copytree(rig.session(), copy)
                if damage == 'flip':
                    data = bytearray((copy / '0003.json').read_bytes())
                    data[10] ^= 0x01
                    (copy / '0003.json').write_bytes(bytes(data))
                else:
                    (copy / '0002.json').unlink()
                self.assertEqual(owned.recover(copy)['phase'], 'JOURNAL_INTEGRITY_LOST')

    def test_library_is_unwired_and_cannot_reach_shared_servers_by_itself(self):
        source = (ROOT / 'scripts' / 'v213_owned_strata.py').read_text(encoding='utf-8')
        for token in ('import subprocess', 'import socket', 'urllib', 'http.client', '__main__', 'v1/unload', 'v1/load',
                      'taskkill', 'os.kill', 'Stop-Process'):
            self.assertNotIn(token, source)
        callers = []
        for pattern in ('*.ps1', '*.cmd', 'scripts/*.ps1', 'scripts/*.psm1', 'scripts/*.py', 'scripts/task-templates/*',
                        'launcher/*.cs', 'config/*.json'):
            for path in ROOT.glob(pattern):
                if (path.is_file() and path.name != 'v213_owned_strata.py'
                        and 'v213_owned_strata' in path.read_text(encoding='utf-8', errors='replace')):
                    callers.append(path.name)
        self.assertEqual(callers, [])


if __name__ == '__main__':
    unittest.main()
