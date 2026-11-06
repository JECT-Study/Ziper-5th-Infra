#!/usr/bin/env python3
"""Plan by default; align two recorded Ziper containers without replacing their release."""
import argparse
import base64
import fcntl
import hashlib
import importlib.util
import inspect
import json
from pathlib import Path
import re
import subprocess
from datetime import datetime
from zoneinfo import ZoneInfo
import zlib


def reconcile(app, tunnel, release, schedule_sha, apply, root=Path('/opt/ziper')):
    def docker(*args):
        result = subprocess.run(['docker', *args], capture_output=True, text=True, timeout=30)
        if result.returncode:
            raise RuntimeError('docker_operation_failed_read_state_before_retry')
        return result.stdout
    with (root / 'deploy.lock').open('a+b') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        lease = root / 'ops/recovery-lease.json'
        if lease.exists() or lease.is_symlink() or (root / 'current-version').read_text().strip() != release:
            raise RuntimeError('release_or_lease_mismatch')
        policy_bytes = (root / 'ci/production.json').read_bytes()
        if hashlib.sha256(policy_bytes).hexdigest() != schedule_sha:
            raise RuntimeError('schedule_mismatch')
        schedule = json.loads(policy_bytes)['homeSchedule']
        parse = lambda value: int(value[:2]) * 60 + int(value[3:])
        start = (parse(schedule['start']) - schedule['deploySafetyMinutes']) % 1440
        end = parse(schedule['end'])
        def window_open():
            local = datetime.now(ZoneInfo(schedule['timeZone']))
            minute = local.hour * 60 + local.minute
            return not (start <= minute < end if start < end else minute >= start or minute < end)
        if apply and not window_open():
            raise RuntimeError('deferred_by_home_schedule')
        files = {root / 'current-version'}
        def snapshot():
            raw = json.loads(docker('inspect', app, tunnel))
            if len(raw) != 2:
                raise RuntimeError('container_count')
            values = []
            for item, identity, service in zip(raw, (app, tunnel), ('app', 'cloudflared')):
                labels = item['Config'].get('Labels', {})
                env = dict(value.split('=', 1) for value in item['Config'].get('Env', []) if '=' in value)
                if (item['Id'] != identity or labels.get('com.docker.compose.project') != 'ziper-production'
                        or labels.get('com.docker.compose.service') != service or item['State']['Running'] is not True
                        or service == 'app' and env.get('SENTRY_RELEASE') != release):
                    raise RuntimeError('container_scope')
                for name in labels.get('com.docker.compose.project.config_files', '').split(','):
                    path = Path(name)
                    if not name or path.is_symlink() or not path.resolve().is_relative_to(root.resolve()) or not path.is_file():
                        raise RuntimeError('compose_reference')
                    files.add(path)
                restart = item['HostConfig']['RestartPolicy']['Name']
                started = item['State']['StartedAt']
                if (restart not in ('unless-stopped', 'always') or not isinstance(started, str)
                        or not re.fullmatch(r'[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9:.]+Z', started)):
                    raise RuntimeError('unexpected_restart_policy')
                values.append({'service': service, 'containerId': identity, 'restartPolicy': restart,
                               'running': True, 'startedAt': started})
            return values
        before = snapshot()
        hashes = {path: hashlib.sha256(path.read_bytes()).digest() for path in files}
        targets = [item['containerId'] for item in before if item['restartPolicy'] != 'always']
        if apply and targets:
            if not window_open():
                raise RuntimeError('deferred_by_home_schedule')
            docker('update', '--restart=always', *targets)
        after = snapshot()
        if (files != set(hashes) or any(hashlib.sha256(path.read_bytes()).digest() != digest for path, digest in hashes.items())
                or any(a['startedAt'] != b['startedAt'] or a['containerId'] != b['containerId'] for a, b in zip(before, after))
                or apply and any(item['restartPolicy'] != 'always' for item in after)):
            raise RuntimeError('state_changed_read_before_retry')
        return {'release': release, 'applied': apply, 'updatedContainerCount': len(targets) if apply else 0,
                'before': before, 'after': after, 'sameContainerStartTimes': True, 'referencedFilesUnchanged': True,
                'newImageDeployment': False, 'wholeHomeBootVerified': False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('infra-sha', 'release', 'app-container', 'tunnel-container', 'output'):
        parser.add_argument('--' + name, required=True)
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    if (not re.fullmatch('[a-f0-9]{40}', args.infra_sha) or not re.fullmatch('[a-f0-9]{40}', args.release)
            or not re.fullmatch('[a-f0-9]{64}', args.app_container) or not re.fullmatch('[a-f0-9]{64}', args.tunnel_container)
            or args.app_container == args.tunnel_container):
        parser.error('Supply full reviewed SHA and distinct recorded container IDs')
    root = Path(__file__).resolve().parents[1]
    def git(*values):
        return subprocess.check_output(['git', *values], cwd=root, stderr=subprocess.PIPE)
    report = {'ok': False, 'infraSha': args.infra_sha, 'applicationRequested': args.apply, 'stage': 'prepare'}
    try:
        subprocess.run(['git', 'merge-base', '--is-ancestor', args.infra_sha, 'origin/main'], cwd=root, check=True, capture_output=True)
        if args.apply:
            for name in ('scripts/reconcile-home-restart-policy.py', 'scripts/install-home-control.py'):
                if git('show', args.infra_sha + ':' + name) != (root / name).read_bytes():
                    raise RuntimeError('script_must_match_reviewed_main')
            count = subprocess.check_output(['gh', 'api', '--method', 'GET',
                'repos/JECT-Study/Ziper-5th-Infra/actions/workflows/ci.yml/runs', '-f', 'head_sha=' + args.infra_sha,
                '-f', 'branch=main', '-f', 'event=push', '-f', 'status=success', '--jq', '.workflow_runs | length'], text=True, stderr=subprocess.PIPE)
            if int(count) < 1:
                raise RuntimeError('successful_main_ci_required')
        schedule_sha = hashlib.sha256(git('show', args.infra_sha + ':config/production.json')).hexdigest()
        call = 'reconcile(' + ','.join(map(repr, (args.app_container, args.tunnel_container, args.release, schedule_sha, args.apply))) + ')'
        code = ('import fcntl,hashlib,json,re,subprocess\nfrom pathlib import Path\nfrom datetime import datetime\nfrom zoneinfo import ZoneInfo\n'
                + inspect.getsource(reconcile) + '\ntry:\n result=' + call + '\n result["remoteOk"]=True\n'
                + 'except Exception as error:\n result={"remoteOk":False,"failure":str(error) if isinstance(error,RuntimeError) else "remote_refused"}\n'
                + 'print(json.dumps(result))')
        payload = base64.b64encode(zlib.compress(code.encode(), 9))
        loader = 'import base64,zlib,sys;exec(zlib.decompress(base64.b64decode(sys.stdin.buffer.read())))'
        report['controlPayloadBytes'] = len(payload)
        if len(loader.encode()) > 2000 or len(payload) > 65536:
            raise RuntimeError('control_payload_exceeds_native_ssh_budget')
        spec = importlib.util.spec_from_file_location('installer', root / 'scripts/install-home-control.py')
        installer = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(installer)
        report['stage'] = 'ssh'
        receipt = installer.remote(loader, payload)
        allowed = {'release_or_lease_mismatch', 'schedule_mismatch', 'deferred_by_home_schedule', 'container_count',
                   'container_scope', 'compose_reference', 'unexpected_restart_policy',
                   'docker_operation_failed_read_state_before_retry', 'state_changed_read_before_retry', 'remote_refused'}
        if receipt.get('remoteOk') is not True:
            report['failure'] = receipt.get('failure') if receipt.get('failure') in allowed else 'remote_refused'
            raise RuntimeError('remote_refused')
        report.update(receipt)
        report['stage'] = 'receipt'
        report['ok'] = True
    except Exception:
        report['result'] = 'failed_or_unknown_read_actual_state_before_retry'
    report['checkedAt'] = datetime.now().astimezone().isoformat()
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report))
    return 0 if report['ok'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
