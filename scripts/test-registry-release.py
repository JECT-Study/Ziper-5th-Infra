import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from unittest.mock import patch
from urllib.error import HTTPError

HOME = Path(__file__).resolve().parents[1] / 'deployment/home'
sys.path.insert(0, str(HOME))
import registry_release


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


receiver = load('receiver_registry', HOME / 'receive.py')
publisher = load('publisher_registry', Path(__file__).with_name('publish-registry-release.py'))
VERSION, PREVIOUS = 'a' * 40, 'b' * 40
CONFIG = json.dumps({'os': 'linux', 'architecture': 'amd64', 'rootfs': {'type': 'layers', 'diff_ids': []}}).encode()
CONFIG_DIGEST = 'sha256:' + hashlib.sha256(CONFIG).hexdigest()
JAR = b'tested-jar-fixture'
NEW_ID, OLD_ID = 'sha256:' + 'd' * 64, 'sha256:' + 'e' * 64


def manifest():
    return {'sourceSha': VERSION, 'registryImage': registry_release.REPOSITORY,
            'imageManifestDigest': 'sha256:' + 'c' * 64, 'imageConfigDigest': CONFIG_DIGEST,
            'jarSha256': hashlib.sha256(JAR).hexdigest()}


def payload(metadata=None):
    return json.dumps({'manifest': metadata or manifest(), 'username': 'fixture-actor',
                       'token': 'fixture-private-token'}).encode()


class Fixture:
    def __init__(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.binary = self.root / 'bin'
        self.binary.mkdir()
        trusted = self.root / 'ci'
        trusted.mkdir()
        (self.root / 'releases').mkdir()
        (self.root / 'docker-client').mkdir()
        (self.root / 'docker-client/config.json').write_text('{}')
        private = self.root / 'private'
        private.mkdir()
        for name in ('runtime.env', 'db-ca.pem', 'cloudflared-token'):
            (private / name).write_text('fixture')
        (self.root / 'fixture.jar').write_bytes(JAR)
        (self.root / 'config.json').write_bytes(CONFIG)
        (self.root / 'tags.json').write_text(json.dumps({'ziper-server:' + VERSION: OLD_ID,
                                                        'ziper-server:' + PREVIOUS: OLD_ID}))
        (self.root / 'deploy.lock').touch()
        (trusted / 'compose.yml').write_text('services: {}\n')
        shutil.copyfile(HOME / 'deploy.sh', trusted / 'deploy.sh')
        shutil.copyfile(HOME / 'registry_release.py', trusted / 'registry_release.py')
        # Keep this integration fixture outside its guard for at least two hours.
        now = datetime.now(timezone.utc).astimezone(registry_release.ZoneInfo('Asia/Seoul'))
        current = now.hour * 60 + now.minute
        clock = lambda minute: f'{minute // 60:02}:{minute % 60:02}'
        schedule = {'timeZone': 'Asia/Seoul', 'start': clock((current + 180) % 1440),
                    'end': clock((current + 240) % 1440), 'deploySafetyMinutes': 0}
        (trusted / 'production.json').write_text(json.dumps({'homeSchedule': schedule}))
        docker = self.binary / 'docker'
        docker.write_text('''#!/usr/bin/env python3
import fcntl,hashlib,io,json,os,pathlib,sys,tarfile
+r=pathlib.Path(os.environ['FIXTURE_ROOT']);a=sys.argv[1:]
+with (r/'deploy.lock').open('a+b') as lock:
+ try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB);held=False
+ except BlockingIOError:held=True
+with (r/'commands').open('a') as f:f.write(json.dumps({'args':a,'lockHeld':held})+'\\n')
+tags=json.loads((r/'tags.json').read_text())
+if a[0]=='login':
+ token=sys.stdin.read();d=pathlib.Path(os.environ['DOCKER_CONFIG']);d.mkdir(exist_ok=True)
+ (d/'config.json').write_text(token);(r/'auth-directory').write_text(str(d))
+elif a[0]=='tag':tags[a[2]]=tags.get(a[1],'sha256:'+'d'*64);(r/'tags.json').write_text(json.dumps(tags))
+elif a[0]=='save':
+ c=(r/'config.json').read_bytes();h=hashlib.sha256(c).hexdigest()
+ m=json.dumps([{'Config':h+'.json','RepoTags':[a[1]],'Layers':[]}]).encode()
+ with tarfile.open(fileobj=sys.stdout.buffer,mode='w|') as t:
+  for n,b in [('manifest.json',m),(h+'.json',c)]:
+   x=tarfile.TarInfo(n);x.size=len(b);t.addfile(x,io.BytesIO(b))
+elif a[0]=='create':print('fixture-container')
+elif a[0]=='cp':pathlib.Path(a[-1]).write_bytes((r/'fixture.jar').read_bytes())
+elif a[:2]==['image','inspect']:print(tags.get(a[-1],'sha256:'+'d'*64))
+elif a[:2]==['image','rm']:tags.pop(a[-1],None);(r/'tags.json').write_text(json.dumps(tags))
+elif a[0]=='compose':
+ version=pathlib.Path(a[a.index('-f')+1]).parent.name;cmd=a[a.index('-f')+2:]
+ if cmd[0]=='up' and cmd[-1]=='app':(r/'current-runtime').write_text(version)
+ elif cmd[0]=='up' and cmd[-1]=='cloudflared' and version=='a'*40 and (r/'fail-cloudflared').exists():sys.exit(1)
+ elif cmd==['stop','app']:(r/'current-runtime').write_text('stopped')
+'''.replace('\n+', '\n'))
        docker.chmod(0o700)
        if shutil.which('flock') is None:
            shim = self.binary / 'flock'
            shim.write_text('#!/usr/bin/env python3\nimport fcntl,sys\ntry:fcntl.flock(int(sys.argv[-1]),fcntl.LOCK_EX|fcntl.LOCK_NB)\nexcept BlockingIOError:sys.exit(1)\n')
            shim.chmod(0o700)
        self.env = {**os.environ, 'PATH': str(self.binary) + os.pathsep + os.environ['PATH'],
                    'FIXTURE_ROOT': str(self.root), 'ZIPER_DEPLOY_ROOT': str(self.root)}
        self.env.pop('ZIPER_DEPLOY_LOCK_FD', None)

    def release(self, version, identity):
        target = self.root / 'releases' / version
        target.mkdir()
        (target / 'image-id').write_text(identity + '\n')
        (target / 'compose.yml').write_text('services: {}\n')
        return target

    def calls(self):
        path = self.root / 'commands'
        return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []

    def close(self):
        self.temporary.cleanup()


class RegistryTests(unittest.TestCase):
    def fixture(self):
        fixture = Fixture()
        self.addCleanup(fixture.close)
        return fixture

    def test_bounded_control_payload_rejects_arbitrary_repo_and_secret_fields(self):
        value = json.loads(payload())
        result = registry_release.read_payload(io.BytesIO(payload()), VERSION)
        self.assertEqual(result[0], manifest())
        for replacement in [
            {**value, 'extra': 'unexpected'}, {**value, 'token': 'with newline\n'},
            {**value, 'manifest': {**manifest(), 'registryImage': 'attacker.test/image'}},
            {**value, 'manifest': {**manifest(), 'imageManifestDigest': 'latest'}},
            {**value, 'manifest': {**manifest(), 'sourceSha': 'c' * 40}},
        ]:
            with self.subTest(replacement=replacement), self.assertRaises(SystemExit):
                registry_release.read_payload(io.BytesIO(json.dumps(replacement).encode()), VERSION)
        with self.assertRaises(SystemExit):
            registry_release.read_payload(io.BytesIO(b'x' * 8193), VERSION)

    def test_unsupported_and_legacy_commands_fail_before_reading_credentials(self):
        for command in ('whoami', 'deploy ' + VERSION, 'deploy-registry latest', 'deploy-registry ' + VERSION + ';whoami'):
            with patch.object(receiver.sys, 'argv', ['receive.py', command]), self.assertRaises(SystemExit):
                receiver.main()

    def test_only_registry_404_means_absent_not_authentication_failure(self):
        class Response(io.BytesIO):
            headers = {'Docker-Content-Digest': 'sha256:' + 'c' * 64}
        for status, absent in [(404, True), (401, False), (403, False), (500, False)]:
            with self.subTest(status=status), patch.object(publisher, 'build_opener') as opener:
                opener.return_value.open.side_effect = [Response(b'{"token":"fixture"}'),
                    HTTPError('https://ghcr.io/fixture', status, 'fixture', {}, io.BytesIO(b'private-response-marker'))]
                if absent:
                    self.assertIsNone(publisher.registry_digest(VERSION, 'actor', 'fixture-private-token'))
                else:
                    with self.assertRaises(SystemExit) as error:
                        publisher.registry_digest(VERSION, 'actor', 'fixture-private-token')
                    self.assertNotIn('fixture-private-token', str(error.exception))

    def test_real_cli_fixture_pulls_checks_jar_and_keeps_inherited_lock_through_deploy(self):
        f = self.fixture()
        with patch.dict(os.environ, f.env, clear=True):
            receiver.deploy_registry(VERSION, io.BytesIO(payload()), f.root)
        calls = f.calls()
        self.assertTrue(all(call['lockHeld'] for call in calls))
        raw = json.dumps(calls)
        self.assertIn(registry_release.REPOSITORY + '@' + manifest()['imageManifestDigest'], raw)
        self.assertNotIn('fixture-private-token', raw)
        self.assertEqual((f.root / 'current-version').read_text().strip(), VERSION)
        self.assertEqual((f.root / 'current-runtime').read_text(), VERSION)
        self.assertFalse(Path((f.root / 'auth-directory').read_text()).exists())
        saved = (f.root / 'releases' / VERSION / 'manifest.json').read_text()
        self.assertNotIn('fixture-private-token', saved)
        self.assertEqual(json.loads(saved), manifest())
        self.assertFalse(any(key.startswith('ziper-verification:') for key in json.loads((f.root / 'tags.json').read_text())))

    def test_bad_jar_or_config_never_changes_existing_release_tag(self):
        for change in ({'jarSha256': '0' * 64}, {'imageConfigDigest': 'sha256:' + '0' * 64}):
            with self.subTest(change=change):
                f = self.fixture()
                with patch.dict(os.environ, f.env, clear=True), self.assertRaises(SystemExit):
                    receiver.deploy_registry(VERSION, io.BytesIO(payload({**manifest(), **change})), f.root)
                self.assertEqual(json.loads((f.root / 'tags.json').read_text())['ziper-server:' + VERSION], OLD_ID)
                self.assertFalse((f.root / 'releases' / VERSION).exists())
                self.assertFalse((f.root / 'current-runtime').exists())
                self.assertFalse(Path((f.root / 'auth-directory').read_text()).exists())
                self.assertFalse(any(call['args'][0] == 'tag' and call['args'][-1] == 'ziper-server:' + VERSION for call in f.calls()))

    def test_existing_lock_prevents_every_docker_command(self):
        f = self.fixture()
        code = 'import sys,io;from pathlib import Path;sys.path.insert(0,sys.argv[1]);import receive;receive.deploy_registry(sys.argv[3],sys.stdin.buffer,Path(sys.argv[2]))'
        with receiver.deployment_lock(f.root):
            result = subprocess.run([sys.executable, '-c', code, str(HOME), str(f.root), VERSION],
                                    input=payload(), env=f.env, capture_output=True, timeout=5)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(b'Another Ziper deployment is active', result.stderr)
        self.assertEqual(f.calls(), [])

    def test_existing_manifest_is_never_deleted_or_replaced_on_mismatch(self):
        f = self.fixture()
        release = f.release(VERSION, OLD_ID)
        previous = b'{"previous":"immutable-record"}\n'
        (release / 'manifest.json').write_bytes(previous)
        with patch.dict(os.environ, f.env, clear=True), self.assertRaises(SystemExit) as error:
            receiver.deploy_registry(VERSION, io.BytesIO(payload()), f.root)
        self.assertEqual(str(error.exception), 'Immutable release manifest mismatch')
        self.assertEqual((release / 'manifest.json').read_bytes(), previous)
        self.assertEqual(f.calls(), [])

    def test_recovery_lease_prevents_registry_login_and_runtime_mutation(self):
        for symlink in (False, True):
            with self.subTest(symlink=symlink):
                f = self.fixture()
                (f.root / 'ops').mkdir()
                lease = f.root / 'ops/recovery-lease.json'
                if symlink:
                    lease.symlink_to('missing-lease')
                else:
                    lease.write_text('{"expiresAt":0}')
                with patch.dict(os.environ, f.env, clear=True), self.assertRaises(SystemExit) as error:
                    receiver.deploy_registry(VERSION, io.BytesIO(payload()), f.root)
                self.assertIn('recovery lease', str(error.exception))
                self.assertEqual(f.calls(), [])
                self.assertFalse((f.root / 'releases' / VERSION).exists())

    def test_trusted_deploy_also_refuses_an_unresolved_recovery_lease(self):
        f = self.fixture()
        f.release(VERSION, OLD_ID)
        (f.root / 'ops').mkdir()
        (f.root / 'ops/recovery-lease.json').write_text('{"expiresAt":0}')
        result = subprocess.run(['bash', str(HOME / 'deploy.sh'), VERSION], env=f.env,
                                capture_output=True, timeout=5)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(b'recovery lease', result.stderr)
        self.assertEqual(f.calls(), [])

    def test_cloudflared_failure_restores_previous_runtime_and_record(self):
        f = self.fixture()
        f.release(PREVIOUS, OLD_ID)
        (f.root / 'current-version').write_text(PREVIOUS + '\n')
        (f.root / 'current-runtime').write_text(PREVIOUS)
        (f.root / 'fail-cloudflared').touch()
        with patch.dict(os.environ, f.env, clear=True), self.assertRaises(SystemExit) as error:
            receiver.deploy_registry(VERSION, io.BytesIO(payload()), f.root)
        self.assertEqual(error.exception.code, 1)
        self.assertEqual((f.root / 'current-version').read_text().strip(), PREVIOUS)
        self.assertEqual((f.root / 'current-runtime').read_text(), PREVIOUS)

    def test_first_cloudflared_failure_stops_app_and_does_not_record_success(self):
        f = self.fixture()
        (f.root / 'fail-cloudflared').touch()
        with patch.dict(os.environ, f.env, clear=True), self.assertRaises(SystemExit):
            receiver.deploy_registry(VERSION, io.BytesIO(payload()), f.root)
        self.assertFalse((f.root / 'current-version').exists())
        self.assertEqual((f.root / 'current-runtime').read_text(), 'stopped')

    def test_release_record_write_failure_restores_previous_runtime_and_record(self):
        f = self.fixture()
        f.release(PREVIOUS, OLD_ID)
        (f.root / 'current-version').write_text(PREVIOUS + '\n')
        (f.root / 'current-runtime').write_text(PREVIOUS)
        # A directory reliably rejects redirection, including when the test runs as root.
        (f.root / 'current-version.next').mkdir()
        with patch.dict(os.environ, f.env, clear=True), self.assertRaises(SystemExit) as error:
            receiver.deploy_registry(VERSION, io.BytesIO(payload()), f.root)
        self.assertEqual(error.exception.code, 1)
        self.assertEqual((f.root / 'current-version').read_text(), PREVIOUS + '\n')
        self.assertEqual((f.root / 'current-runtime').read_text(), PREVIOUS)
        tunnel_starts = [Path(call['args'][call['args'].index('-f') + 1]).parent.name
                         for call in f.calls() if call['args'][0] == 'compose'
                         and 'up' in call['args'] and call['args'][-1] == 'cloudflared']
        self.assertEqual(tunnel_starts, [VERSION, PREVIOUS])

    def test_first_release_record_write_failure_stops_new_app_without_success_record(self):
        f = self.fixture()
        (f.root / 'current-version.next').mkdir()
        with patch.dict(os.environ, f.env, clear=True), self.assertRaises(SystemExit) as error:
            receiver.deploy_registry(VERSION, io.BytesIO(payload()), f.root)
        self.assertEqual(error.exception.code, 1)
        self.assertFalse((f.root / 'current-version').exists())
        self.assertEqual((f.root / 'current-runtime').read_text(), 'stopped')
        self.assertTrue(any(call['args'][0] == 'compose' and 'up' in call['args']
                            and call['args'][-1] == 'cloudflared' for call in f.calls()))

    def test_same_release_tunnel_failure_does_not_stop_existing_app(self):
        f = self.fixture()
        f.release(VERSION, OLD_ID)
        (f.root / 'current-version').write_text(VERSION + '\n')
        (f.root / 'fail-cloudflared').touch()
        with patch.dict(os.environ, f.env, clear=True), self.assertRaises(SystemExit):
            receiver.deploy_registry(VERSION, io.BytesIO(payload()), f.root)
        self.assertEqual((f.root / 'current-version').read_text().strip(), VERSION)
        self.assertEqual((f.root / 'current-runtime').read_text(), VERSION)
        self.assertFalse(any(call['args'][-2:] == ['stop', 'app'] for call in f.calls()))

    def test_guard_crossed_during_pull_never_retags_or_starts_app(self):
        f = self.fixture()
        with patch.dict(os.environ, f.env, clear=True), patch.object(receiver, 'ensure_runtime_window',
                side_effect=[None, None, SystemExit(75)]), self.assertRaises(SystemExit) as error:
            receiver.deploy_registry(VERSION, io.BytesIO(payload()), f.root)
        self.assertEqual(error.exception.code, 75)
        self.assertEqual(json.loads((f.root / 'tags.json').read_text())['ziper-server:' + VERSION], OLD_ID)
        self.assertFalse((f.root / 'current-runtime').exists())
        self.assertFalse((f.root / 'releases' / VERSION).exists())
        self.assertFalse(Path((f.root / 'auth-directory').read_text()).exists())

    def test_sender_records_deferred_without_leaking_credential(self):
        f = self.fixture()
        dist = f.root / 'dist'
        dist.mkdir()
        (dist / 'registry-release.json').write_text(json.dumps(manifest()))
        ssh = f.binary / 'ssh'
        ssh.write_text('''#!/usr/bin/env python3
import sys
if sys.argv[-1]=='check':print('ZIPER_CI_RECEIVER_READY')
elif sys.argv[-1]=='whoami':sys.exit(1)
else:sys.stdin.read();print('ZIPER_DEPLOY_DEFERRED');sys.exit(75)
''')
        ssh.chmod(0o700)
        env = {**f.env, 'GITHUB_SHA': VERSION, 'GITHUB_ACTOR': 'fixture-actor',
               'GHCR_TOKEN': 'fixture-private-token', 'GITHUB_OUTPUT': str(f.root / 'outputs')}
        result = subprocess.run([sys.executable, str(Path(__file__).with_name('deliver-registry-release.py')),
                                 str(ssh)], cwd=f.root, env=env, capture_output=True, timeout=5)
        self.assertEqual(result.returncode, 0)
        self.assertNotIn(b'fixture-private-token', result.stdout + result.stderr)
        report = json.loads((dist / 'receiver-control-proof.json').read_text())
        self.assertEqual(report['result'], 'deferred')
        self.assertIn('deferred=true', (f.root / 'outputs').read_text())

    def test_inherited_descriptor_for_wrong_inode_is_rejected(self):
        f = self.fixture()
        f.release(VERSION, OLD_ID)
        with (f.root / 'wrong.lock').open('a+b') as wrong:
            env = {**f.env, 'ZIPER_DEPLOY_LOCK_FD': str(wrong.fileno())}
            result = subprocess.run(['bash', str(HOME / 'deploy.sh'), VERSION], env=env,
                                    pass_fds=(wrong.fileno(),), capture_output=True, timeout=5)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(f.calls(), [])

    def test_runtime_guard_boundary_and_no_runtime_mutation_when_deferred(self):
        f = self.fixture()
        source = json.loads((HOME.parents[1] / 'config/production.json').read_text())
        (f.root / 'ci/production.json').write_text(json.dumps(source))
        for iso, deferred in [('2026-11-06T17:29:59+00:00', False), ('2026-11-06T17:30:00+00:00', True),
                              ('2026-11-06T18:00:00+00:00', True), ('2026-11-06T20:59:59+00:00', True),
                              ('2026-11-06T21:00:00+00:00', False)]:
            with self.subTest(iso=iso):
                if deferred:
                    with self.assertRaises(SystemExit) as error:
                        registry_release.ensure_runtime_window(f.root, datetime.fromisoformat(iso))
                    self.assertEqual(error.exception.code, 75)
                else:
                    registry_release.ensure_runtime_window(f.root, datetime.fromisoformat(iso))
        with patch.object(receiver, 'ensure_runtime_window', side_effect=SystemExit(75)), self.assertRaises(SystemExit):
            receiver.deploy_registry(VERSION, io.BytesIO(payload()), f.root)
        self.assertEqual(f.calls(), [])


if __name__ == '__main__':
    unittest.main()
