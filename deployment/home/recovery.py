#!/usr/bin/env python3
"""Root-only, leased recovery for one Ziper app container; never a general shell."""
import argparse
from contextlib import contextmanager
import fcntl
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time

ROOT = Path('/opt/ziper')
PROJECT = 'ziper-production'
SERVICE = 'app'
MAX_LEASE_SECONDS = 540


class Refused(ValueError):
    pass


class Recovery:
    def __init__(self, root=ROOT, run=subprocess.run, now=time.time):
        self.root, self.run, self.now = root, run, now
        self.directory = root / 'ops'
        self.lease_path = self.directory / 'recovery-lease.json'
        self.result_path = self.directory / 'recovery-result.json'

    def docker(self, *args):
        result = self.run(['docker', *args], capture_output=True, text=True, timeout=20)
        if result.returncode:
            raise Refused('docker_operation_failed')
        return result.stdout

    def version(self):
        version = (self.root / 'current-version').read_text().strip()
        if not re.fullmatch('[a-f0-9]{40}', version):
            raise Refused('invalid_recorded_release')
        return version

    def inspect(self, container_id):
        if not re.fullmatch('[a-f0-9]{64}', container_id):
            raise Refused('invalid_container_id')
        try:
            records = json.loads(self.docker('inspect', '--type', 'container', container_id))
            if len(records) != 1:
                raise Refused('ambiguous_container')
            record = records[0]
            labels = record['Config']['Labels']
            if record['Id'] != container_id or labels.get('com.docker.compose.project') != PROJECT or labels.get('com.docker.compose.service') != SERVICE:
                raise Refused('container_scope_mismatch')
            releases = [value.removeprefix('SENTRY_RELEASE=') for value in record['Config'].get('Env', [])
                        if value.startswith('SENTRY_RELEASE=')]
            if releases != [self.version()]:
                raise Refused('container_release_mismatch')
            return {'containerId': container_id, 'running': record['State']['Running'] is True}
        except (KeyError, TypeError, json.JSONDecodeError):
            raise Refused('invalid_container_metadata') from None

    def current(self):
        ids = self.docker('ps', '-aq', '--no-trunc', '--filter', 'label=com.docker.compose.project=' + PROJECT,
                          '--filter', 'label=com.docker.compose.service=' + SERVICE).split()
        if len(ids) != 1:
            raise Refused('expected_exactly_one_ziper_app')
        return {**self.inspect(ids[0]), 'version': self.version(), 'project': PROJECT, 'service': SERVICE}

    def write(self, path, value):
        if path.is_symlink():
            raise Refused('state_symlink_rejected')
        pending = path.with_name(path.name + '.next')
        descriptor = os.open(pending, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
        with os.fdopen(descriptor, 'w') as output:
            json.dump(value, output)
            output.write('\n')
            output.flush()
            os.fsync(output.fileno())
        os.replace(pending, path)

    def read(self, path):
        if not path.exists():
            return None
        if path.is_symlink() or path.stat().st_size > 8192:
            raise Refused('invalid_state_file')
        return json.loads(path.read_text())

    @contextmanager
    def locked(self):
        self.directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        if self.directory.is_symlink() or self.directory.stat().st_mode & 0o077:
            raise Refused('ops_directory_must_be_private')
        with (self.directory / 'recovery.lock').open('a') as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise Refused('another_recovery_operation_is_active') from None
            with (self.root / 'deploy.lock').open('a') as deploy_lock:
                try:
                    fcntl.flock(deploy_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError:
                    raise Refused('ziper_deployment_is_active') from None
                yield

    def lease(self, test_id=None):
        lease = self.read(self.lease_path)
        if not isinstance(lease, dict) or set(lease) != {'testId', 'containerId', 'version', 'createdAt', 'expiresAt'}:
            raise Refused('no_valid_recovery_lease')
        if not isinstance(lease['testId'], str) or not re.fullmatch('[A-Za-z0-9_-]{8,80}', lease['testId']):
            raise Refused('invalid_lease_test_id')
        if test_id is not None and lease['testId'] != test_id:
            raise Refused('lease_test_id_mismatch')
        if not all(isinstance(lease[k], (int, float)) and not isinstance(lease[k], bool) for k in ('createdAt', 'expiresAt')):
            raise Refused('invalid_lease_time')
        if not 0 <= lease['expiresAt'] - lease['createdAt'] <= MAX_LEASE_SECONDS:
            raise Refused('invalid_lease_duration')
        if lease['version'] != self.version():
            raise Refused('release_changed_since_arm')
        target = self.current()
        if target['containerId'] != lease['containerId']:
            raise Refused('container_changed_since_arm')
        return lease, target

    def execute(self, command, *, test_id=None, seconds=MAX_LEASE_SECONDS):
        with self.locked():
            if command == 'check':
                return {'result': 'checked', **self.current()}
            if command == 'status':
                return {'lease': self.read(self.lease_path), 'lastResult': self.read(self.result_path), **self.current()}
            if command == 'arm':
                if not isinstance(test_id, str) or not re.fullmatch('[A-Za-z0-9_-]{8,80}', test_id):
                    raise Refused('invalid_test_id')
                if not 0 <= seconds <= MAX_LEASE_SECONDS:
                    raise Refused('invalid_lease_duration')
                existing = self.read(self.lease_path)
                if existing is not None:
                    raise Refused('recover_existing_lease_before_rearming')
                target = self.current()
                if not target['running']:
                    raise Refused('app_must_be_running_before_arm')
                now = self.now()
                lease = {'testId': test_id, 'containerId': target['containerId'], 'version': target['version'],
                         'createdAt': now, 'expiresAt': now + seconds}
                self.write(self.lease_path, lease)
                return {'result': 'armed', **lease}
            if command == 'tick' and not self.lease_path.exists():
                return {'result': 'no_lease'}
            lease, target = self.lease(test_id)
            if command == 'stop':
                if lease['expiresAt'] <= self.now():
                    raise Refused('lease_expired_before_fault')
                self.docker('stop', '--time', '5', target['containerId'])
                result = {'result': 'stopped', 'testId': lease['testId'], 'containerId': target['containerId'],
                          'version': target['version'], 'at': self.now()}
                self.write(self.result_path, result)
                return result
            if command == 'tick' and self.now() < lease['expiresAt']:
                return {'result': 'waiting', 'testId': lease['testId'], 'expiresAt': lease['expiresAt']}
            if command not in ('tick', 'recover'):
                raise Refused('unsupported_command')
            if not target['running']:
                self.docker('start', target['containerId'])
                if not self.inspect(target['containerId'])['running']:
                    raise Refused('app_did_not_start')
            result = {'result': 'already_running' if target['running'] else 'restarted', 'testId': lease['testId'],
                      'containerId': target['containerId'], 'version': target['version'], 'at': self.now()}
            self.write(self.result_path, result)
            self.lease_path.unlink()
            return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('check', 'arm', 'status', 'stop', 'recover', 'tick'))
    parser.add_argument('--test-id')
    parser.add_argument('--seconds', type=int, default=MAX_LEASE_SECONDS)
    args = parser.parse_args()
    if os.geteuid() != 0:
        parser.error('Run through the dedicated root operator or scheduler')
    if args.command in ('arm', 'stop', 'recover') and not args.test_id:
        parser.error('--test-id is required')
    try:
        print(json.dumps(Recovery().execute(args.command, test_id=args.test_id, seconds=args.seconds)))
        return 0
    except (Refused, OSError, ValueError, subprocess.SubprocessError) as error:
        reason = str(error) if isinstance(error, Refused) else 'recovery_operation_failed'
        print(json.dumps({'result': 'refused', 'reason': reason}))
        return 1


if __name__ == '__main__':
    sys.exit(main())
