#!/usr/bin/env python3
import importlib.util
from datetime import datetime
import hashlib
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


ROOT = Path(__file__).resolve().parents[1]
recovery = load('recovery', ROOT / 'deployment/home/recovery.py')
observer = load('observer', ROOT / 'scripts/observe-production-e2e.py')
boundaries = load('boundaries', ROOT / 'scripts/verify-production-boundaries.py')
installer = load('installer', ROOT / 'scripts/install-home-control.py')
restart_policy = load('restart_policy', ROOT / 'scripts/reconcile-home-restart-policy.py')
VERSION = 'a' * 40
CONTAINER = 'b' * 64


class RemoteControlTests(unittest.TestCase):
    def test_existing_code_only_and_small_ascii_stdin_modes_preserve_inputs(self):
        for payload in (None, b'fixture-small-ascii-control'):
            with self.subTest(payload=payload), patch.object(installer.subprocess, 'run') as run:
                run.return_value = SimpleNamespace(returncode=0, stdout=b'{"ok":true}\n')
                self.assertEqual(installer.remote('print("fixture")', payload), {'ok': True})
                self.assertEqual(run.call_args.kwargs['input'], payload)


class RestartPolicyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        (self.root / 'ops').mkdir()
        (self.root / 'ci').mkdir()
        (self.root / 'current-version').write_text(VERSION)
        self.compose = self.root / 'compose.yml'
        self.compose.write_text('restart: unless-stopped\n')
        self.policy = self.root / 'ci/production.json'
        self.policy.write_text(json.dumps({'homeSchedule': {'timeZone': 'Asia/Seoul', 'start': '03:00', 'end': '06:00', 'deploySafetyMinutes': 30}}))
        self.policy_hash = hashlib.sha256(self.policy.read_bytes()).hexdigest()
        self.ids = ('b' * 64, 'c' * 64)
        self.items = [{'Id': cid, 'Config': {'Env': ['SENTRY_RELEASE=' + VERSION, 'TOKEN=fixture-private-marker'],
                      'Labels': {'com.docker.compose.project': 'ziper-production', 'com.docker.compose.service': service,
                                 'com.docker.compose.project.config_files': str(self.compose)}},
                      'State': {'Running': True, 'StartedAt': '2026-11-06T21:09:54Z'},
                      'HostConfig': {'RestartPolicy': {'Name': 'unless-stopped'}}}
                      for cid, service in zip(self.ids, ('app', 'cloudflared'))]
        self.updates = []

    def tearDown(self):
        self.temp.cleanup()

    def docker(self, command, **kwargs):
        if command[1] == 'inspect':
            value = json.dumps(self.items)
        elif command[1:3] == ['update', '--restart=always']:
            self.updates.append(command[3:])
            for item in self.items:
                if item['Id'] in command[3:]:
                    item['HostConfig']['RestartPolicy']['Name'] = 'always'
            value = ''
        else:
            raise AssertionError('Only inspect and policy update are allowed')
        return SimpleNamespace(returncode=0, stdout=value)

    def execute(self, apply):
        with patch.object(restart_policy.subprocess, 'run', self.docker), patch.object(restart_policy, 'datetime') as clock:
            clock.now.return_value = datetime(2026, 11, 7, 12)
            return restart_policy.reconcile(*self.ids, VERSION, self.policy_hash, apply, self.root)

    def test_plan_is_read_only_then_apply_and_repeat_change_only_policy(self):
        plan = self.execute(False)
        self.assertFalse(plan['applied'])
        self.assertEqual(self.updates, [])
        first = self.execute(True)
        self.assertEqual(first['updatedContainerCount'], 2)
        self.assertTrue(first['sameContainerStartTimes'])
        self.assertTrue(first['referencedFilesUnchanged'])
        self.assertEqual(self.updates, [list(self.ids)])
        self.assertEqual(self.execute(True)['updatedContainerCount'], 0)
        self.assertEqual(self.updates, [list(self.ids)])
        self.assertEqual(self.compose.read_text(), 'restart: unless-stopped\n')
        self.assertNotIn('fixture-private-marker', json.dumps(first))

    def test_lease_and_other_project_never_receive_policy_update(self):
        lease = self.root / 'ops/recovery-lease.json'
        lease.write_text('{}')
        with self.assertRaises(RuntimeError):
            self.execute(True)
        lease.unlink()
        self.items[0]['Config']['Labels']['com.docker.compose.project'] = 'tocktock'
        with self.assertRaises(RuntimeError):
            self.execute(True)
        self.items[0]['Config']['Labels']['com.docker.compose.project'] = 'ziper-production'
        with patch.object(restart_policy.subprocess, 'run', self.docker), patch.object(restart_policy, 'datetime') as clock:
            clock.now.side_effect = [datetime(2026, 11, 7, 12), datetime(2026, 11, 8, 2, 30)]
            with self.assertRaisesRegex(RuntimeError, 'deferred_by_home_schedule'):
                restart_policy.reconcile(*self.ids, VERSION, self.policy_hash, True, self.root)
        self.assertEqual(self.updates, [])


class BoundaryReceiptTests(unittest.TestCase):
    def request(self, body, *, ops=True, headers=None):
        class Response:
            status = 200

            def __init__(self):
                self.headers = headers or {}

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def read(self, limit):
                return json.dumps(body).encode()[:limit]

        with patch.object(boundaries.urllib.request, 'build_opener', return_value=SimpleNamespace(open=lambda *a, **kw: Response())):
            return boundaries.request('https://api.example.test/readyz', ops=ops)

    def test_ops_receipt_accepts_only_fixed_modes_and_reasons(self):
        for mode, reason in [('CLOSED', 'home'), ('OPEN', 'circuit_backup'), ('HALF_OPEN', 'scheduled_backup')]:
            receipt = self.request({'state': {'mode': {'kind': mode}}, 'reason': reason})
            self.assertEqual(receipt['mode'], mode)
            self.assertEqual(receipt['reason'], reason)
        for mode, reason in [('CLOSED', 'fixture-private-marker'), ('fixture-private-marker', 'home'),
                             (None, 'home'), ('OPEN', {'value': 'fixture-private-marker'})]:
            with self.subTest(mode=mode, reason=reason):
                receipt = self.request({'state': {'mode': {'kind': mode}}, 'reason': reason})
                self.assertIsNone(receipt['status'])
                self.assertNotIn('fixture-private-marker', json.dumps(receipt))

    def test_health_receipt_does_not_copy_unexpected_body_or_header_values(self):
        marker = 'fixture-private-marker'
        receipt = self.request({'status': 'UP', 'unexpected': marker}, ops=False, headers={
            'X-Ziper-Release': marker, 'X-Ziper-Origin': marker, 'CF-Access-Client-Secret': marker,
            'Cache-Control': 'no-cache, no-store, max-age=0'})
        self.assertFalse(receipt['upOnly'])
        self.assertTrue(receipt['noStore'])
        self.assertTrue(receipt['privateCredentialHeaderPresent'])
        self.assertIsNone(receipt['release'])
        self.assertIsNone(receipt['origin'])
        self.assertNotIn(marker, json.dumps(receipt))


class Docker:
    def __init__(self):
        self.running = True
        self.container = CONTAINER
        self.project = 'ziper-production'
        self.commands = []

    def __call__(self, command, **kwargs):
        self.commands.append(command)
        args = command[1:]
        if args[0] == 'ps':
            value = self.container + '\n'
        elif args[0] == 'inspect':
            value = json.dumps([{'Id': self.container, 'Config': {'Labels': {'com.docker.compose.project': self.project,
                               'com.docker.compose.service': 'app'}, 'Env': ['TOKEN=private-marker', 'SENTRY_RELEASE=' + VERSION]},
                                'State': {'Running': self.running}}])
        elif args[0] == 'stop':
            self.running = False
            value = self.container
        elif args[0] == 'start':
            self.running = True
            value = self.container
        else:
            raise AssertionError(command)
        return SimpleNamespace(returncode=0, stdout=value)


class RecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        (self.root / 'current-version').write_text(VERSION)
        self.clock = [1000]
        self.docker = Docker()
        self.subject = recovery.Recovery(self.root, self.docker, lambda: self.clock[0])

    def tearDown(self):
        self.temp.cleanup()

    def test_expired_scheduler_probe_is_harmless_and_records_proof(self):
        self.subject.execute('arm', test_id='scheduler_probe', seconds=0)
        result = self.subject.execute('tick')
        self.assertEqual(result['result'], 'already_running')
        self.assertNotIn('start', [c[1] for c in self.docker.commands])
        self.assertFalse(self.subject.lease_path.exists())
        self.assertEqual(self.subject.execute('status')['lastResult']['testId'], 'scheduler_probe')

    def test_controller_loss_is_recovered_by_a_fresh_watchdog_instance(self):
        self.subject.execute('arm', test_id='actual_fault', seconds=540)
        self.subject.execute('stop', test_id='actual_fault')
        self.assertFalse(self.docker.running)
        self.clock[0] += 539
        fresh = recovery.Recovery(self.root, self.docker, lambda: self.clock[0])
        self.assertEqual(fresh.execute('tick')['result'], 'waiting')
        self.clock[0] += 1
        self.assertEqual(fresh.execute('tick')['result'], 'restarted')
        self.assertTrue(self.docker.running)
        self.assertEqual([c for c in self.docker.commands if c[1] == 'start'], [['docker', 'start', CONTAINER]])
        self.assertEqual(fresh.execute('tick')['result'], 'no_lease')

    def test_scope_release_and_test_id_mismatches_never_stop_or_start(self):
        for change in ('project', 'container', 'version', 'test_id'):
            with self.subTest(change=change):
                self.subject.execute('arm', test_id='guarded_test', seconds=60)
                if change == 'project': self.docker.project = 'tocktock'
                elif change == 'container': self.docker.container = 'c' * 64
                elif change == 'version': (self.root / 'current-version').write_text('d' * 40)
                with self.assertRaises(recovery.Refused):
                    self.subject.execute('stop', test_id='wrong_test' if change == 'test_id' else 'guarded_test')
                self.assertNotIn('stop', [c[1] for c in self.docker.commands])
                self.subject.lease_path.unlink()
                self.docker.project, self.docker.container = 'ziper-production', CONTAINER
                (self.root / 'current-version').write_text(VERSION)

    def test_expired_or_overlong_lease_cannot_inject_fault(self):
        with self.assertRaises(recovery.Refused):
            self.subject.execute('arm', test_id='guarded_test', seconds=541)
        self.subject.execute('arm', test_id='guarded_test', seconds=0)
        with self.assertRaises(recovery.Refused):
            self.subject.execute('stop', test_id='guarded_test')
        self.assertTrue(self.docker.running)

    def test_immediate_recover_is_scoped_and_output_contains_no_environment(self):
        self.subject.execute('arm', test_id='actual_fault', seconds=540)
        self.subject.execute('stop', test_id='actual_fault')
        result = self.subject.execute('recover', test_id='actual_fault')
        self.assertEqual(result['result'], 'restarted')
        self.assertNotIn('private-marker', json.dumps(self.subject.execute('status')))
        self.assertEqual(self.subject.result_path.stat().st_mode & 0o777, 0o600)


def public(upstream='cloudrun', version=VERSION):
    return {'status': 200, 'upOnly': True, 'noStore': True, 'cached': False, 'sessionCookie': False,
            'origin': upstream, 'release': version}


def ops(mode='OPEN', transitions=None):
    return {'status': 200, 'mode': mode, 'generation': 1, 'reason': 'home' if mode == 'CLOSED' else 'circuit_backup',
            'samples': [{'slot': 1, 'healthy': False}], 'transitions': transitions or []}


class ObserverTests(unittest.TestCase):
    def test_actual_monotonic_limit_and_same_release_are_required(self):
        marker = {'faultAt': 1000, 'faultMonotonic': 10}
        for elapsed, version, expected in ((600, VERSION, True), (600.01, VERSION, False), (300, 'c' * 40, False)):
            with self.subTest(elapsed=elapsed, version=version):
                summary = observer.summarize([{'monotonic': 10 + elapsed, 'public': public(version=version), 'ops': ops()}],
                                             release=VERSION, marker=marker)
                self.assertEqual(summary['failoverWithin600Seconds'], expected)

    def test_scheduled_routing_does_not_claim_circuit_failover(self):
        snapshot = ops()
        snapshot['reason'] = 'scheduled_backup'
        summary = observer.summarize([{'monotonic': 20, 'public': public(), 'ops': snapshot}], release=VERSION,
                                     marker={'faultAt': 1000, 'faultMonotonic': 10})
        self.assertFalse(summary['failoverWithin600Seconds'])

    def test_recovery_requires_transition_history_closed_and_home(self):
        transitions = [{'at': 1001000, 'previous': 'OPEN', 'next': 'HALF_OPEN', 'generation': 1},
                       {'at': 1002000, 'previous': 'HALF_OPEN', 'next': 'OPEN', 'generation': 2},
                       {'at': 1003000, 'previous': 'OPEN', 'next': 'HALF_OPEN', 'generation': 2},
                       {'at': 1004000, 'previous': 'HALF_OPEN', 'next': 'CLOSED', 'generation': 3}]
        snapshot = ops('CLOSED', transitions)
        summary = observer.summarize([{'monotonic': 20, 'public': public('home'), 'ops': snapshot}], release=VERSION,
                                     marker={'faultAt': 1000, 'faultMonotonic': 10})
        self.assertTrue(summary['halfOpenSeen'])
        self.assertTrue(summary['halfOpenFailureSeen'])
        self.assertTrue(summary['recoveredClosedAndHome'])
        summary = observer.summarize([{'monotonic': 20, 'public': public('home'), 'ops': ops('CLOSED')}], release=VERSION,
                                     marker={'faultAt': 1000, 'faultMonotonic': 10})
        self.assertFalse(summary['recoveredClosedAndHome'])

    def test_ops_parser_whitelists_metadata_and_rejects_invalid_samples(self):
        raw = {'state': {'mode': {'kind': 'OPEN', 'retryAt': 1000}, 'generation': 1,
                         'samples': [{'slot': 1, 'healthy': False}], 'private': 'private-marker'},
               'reason': 'circuit_backup', 'nextAlarmAt': 1000, 'token': 'private-marker'}
        self.assertNotIn('private-marker', json.dumps(observer.ops_snapshot(raw)))
        raw['state']['samples'][0]['healthy'] = 'false'
        with self.assertRaises(ValueError): observer.ops_snapshot(raw)

    def test_observer_collects_without_real_sleeps_and_requires_real_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            marker = Path(directory) / 'fault.json'
            marker.write_text(json.dumps({'faultAt': 1000, 'faultMonotonic': 0}))
            clock = [0]

            def fetch(url, **kwargs):
                return ops() if kwargs.get('ops') else public()

            def sleep(seconds): clock[0] += seconds

            result = observer.observe('https://fixture.test', 'private-marker' * 4, VERSION, Path(directory) / 'evidence.jsonl',
                                      seconds=20, interval=5, marker_path=marker, require_failover=True, stop_on='failover',
                                      now=lambda: clock[0], sleep=sleep, fetch=fetch)
            self.assertTrue(result['ok'])
            self.assertEqual(result['verdict'], 'VERIFIED')
            self.assertNotIn('private-marker', Path(directory, 'evidence.jsonl').read_text())


if __name__ == '__main__':
    unittest.main()
