#!/usr/bin/env python3
"""Verify reboot policy in a disposable nested daemon, never restart the host daemon."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import time
import uuid


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    parent = 'ziper-restart-proof-' + uuid.uuid4().hex[:12]
    phase = 'create_disposable_daemon'
    report = {'checkedAt': datetime.now(timezone.utc).isoformat(), 'ok': False,
              'scope': 'Disposable nested Docker daemon; no production daemon or host reboot',
              'wholeHomeBootVerified': False}

    def command(*parts, timeout=120):
        return subprocess.check_output(['docker', *parts], stderr=subprocess.PIPE, timeout=timeout, text=True).strip()

    def nested(*parts, timeout=30):
        return command('exec', parent, 'docker', '-H', 'unix:///var/run/docker.sock', *parts, timeout=timeout)

    def wait_ready():
        until = time.monotonic() + 60
        while time.monotonic() < until:
            try:
                return nested('info', '--format', '{{.ServerVersion}}', timeout=5)
            except (subprocess.SubprocessError, OSError):
                time.sleep(1)
        raise RuntimeError('disposable_daemon_not_ready')

    def states():
        return {name: json.loads(nested('inspect', name))[0]['State']['Running']
                for name in ('always-policy-probe', 'unless-stopped-policy-probe')}

    try:
        command('run', '--detach', '--privileged', '--name', parent, '--memory=512m', '--cpus=1',
                '--entrypoint', 'dockerd', 'docker:29.6.2-dind',
                '--host=unix:///var/run/docker.sock', '--storage-driver=vfs')
        report['nestedDaemonVersion'] = wait_ready()
        phase = 'start_policy_probes'
        for name, policy in [('always-policy-probe', 'always'), ('unless-stopped-policy-probe', 'unless-stopped')]:
            nested('run', '--detach', '--name', name, '--restart', policy, 'alpine:3.22', 'sleep', '3600', timeout=120)
        time.sleep(11)
        phase = 'verify_manual_stop_is_respected'
        nested('stop', '--time', '1', 'always-policy-probe', 'unless-stopped-policy-probe')
        time.sleep(2)
        report['afterManualStop'] = states()
        assert report['afterManualStop'] == {'always-policy-probe': False, 'unless-stopped-policy-probe': False}
        phase = 'restart_only_disposable_daemon'
        command('stop', '--time', '20', parent, timeout=40)
        command('start', parent)
        wait_ready()
        until = time.monotonic() + 30
        while time.monotonic() < until:
            report['afterNestedDaemonRestart'] = states()
            if report['afterNestedDaemonRestart']['always-policy-probe']:
                break
            time.sleep(1)
        report['ok'] = report['afterNestedDaemonRestart'] == {'always-policy-probe': True, 'unless-stopped-policy-probe': False}
        if not report['ok']:
            raise RuntimeError('restart_policy_result_mismatch')
    except (subprocess.SubprocessError, OSError, ValueError, KeyError, IndexError, AssertionError, RuntimeError):
        report['failedPhase'] = phase
    finally:
        cleanup = subprocess.run(['docker', 'rm', '--force', '--volumes', parent], capture_output=True, timeout=40)
        report['disposableDaemonRemoved'] = cleanup.returncode == 0
        report['ok'] &= report['disposableDaemonRemoved']
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2) + '\n')
        print(json.dumps(report))
    return 0 if report['ok'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
