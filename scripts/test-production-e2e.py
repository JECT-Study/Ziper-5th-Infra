#!/usr/bin/env python3
import importlib.util
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


ROOT = Path(__file__).resolve().parents[1]
recovery = load('recovery', ROOT / 'deployment/home/recovery.py')
observer = load('observer', ROOT / 'scripts/observe-production-e2e.py')
VERSION = 'a' * 40
CONTAINER = 'b' * 64


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
                               'com.docker.compose.service': 'app'}, 'Env': ['TOKEN=private-marker']},
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
