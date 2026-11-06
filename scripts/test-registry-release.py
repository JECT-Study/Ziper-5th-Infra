import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
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
VERSION = 'a' * 40
CONFIG = json.dumps({'os': 'linux', 'architecture': 'amd64', 'rootfs': {'type': 'layers', 'diff_ids': []}}).encode()
CONFIG_DIGEST = 'sha256:' + hashlib.sha256(CONFIG).hexdigest()
JAR = b'tested-jar-fixture'


def manifest():
    return {'sourceSha': VERSION, 'registryImage': registry_release.REPOSITORY,
            'imageManifestDigest': 'sha256:' + 'b' * 64, 'imageConfigDigest': CONFIG_DIGEST,
            'jarSha256': hashlib.sha256(JAR).hexdigest()}


class RegistryTests(unittest.TestCase):
    def test_bounded_control_payload_rejects_arbitrary_repo_and_secret_fields(self):
        value = {'manifest': manifest(), 'username': 'fixture-actor', 'token': 'fixture-private-token'}
        result = registry_release.read_payload(io.BytesIO(json.dumps(value).encode()), VERSION)
        self.assertEqual(result[0], manifest())
        for replacement in [
            {**value, 'extra': 'unexpected'},
            {**value, 'token': 'with newline\n'},
            {**value, 'manifest': {**manifest(), 'registryImage': 'attacker.test/image'}},
            {**value, 'manifest': {**manifest(), 'imageManifestDigest': 'latest'}},
            {**value, 'manifest': {**manifest(), 'sourceSha': 'c' * 40}},
        ]:
            with self.subTest(replacement=replacement), self.assertRaises(SystemExit):
                registry_release.read_payload(io.BytesIO(json.dumps(replacement).encode()), VERSION)
        with self.assertRaises(SystemExit):
            registry_release.read_payload(io.BytesIO(b'x' * 8193), VERSION)

    def test_unsupported_registry_commands_fail_before_reading_credentials(self):
        for command in ('deploy-registry latest', 'deploy-registry ' + VERSION + ';whoami'):
            with patch.object(receiver.sys, 'argv', ['receive.py', command]), self.assertRaises(SystemExit):
                receiver.main()

    def test_only_registry_404_means_absent_not_authentication_failure(self):
        class Response(io.BytesIO):
            headers = {'Docker-Content-Digest': 'sha256:' + 'b' * 64}

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

    def test_real_cli_fixture_pulls_exact_digest_checks_jar_and_cleans_auth(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            binary = root / 'bin'
            binary.mkdir()
            trusted = root / 'ci'
            trusted.mkdir()
            (root / 'releases').mkdir()
            (root / 'docker-client').mkdir()
            (root / 'fixture.jar').write_bytes(JAR)
            (root / 'config.json').write_bytes(CONFIG)
            (trusted / 'compose.yml').write_text('services: {}\n')
            (trusted / 'deploy.sh').write_text('#!/bin/sh\nprintf "%s" "$1" > "$FIXTURE_ROOT/deployed"\n')
            docker = binary / 'docker'
            docker.write_text('''#!/usr/bin/env python3
import hashlib,io,json,os,pathlib,sys,tarfile
r=pathlib.Path(os.environ['FIXTURE_ROOT']);a=sys.argv[1:]
with (r/'commands').open('a') as f:f.write(json.dumps(a)+'\\n')
if a[0]=='login':
 token=sys.stdin.read();d=pathlib.Path(os.environ['DOCKER_CONFIG']);d.mkdir(exist_ok=True)
 (d/'config.json').write_text(token);(r/'auth-directory').write_text(str(d))
elif a[0]=='save':
 c=(r/'config.json').read_bytes();h=hashlib.sha256(c).hexdigest()
 m=json.dumps([{'Config':h+'.json','RepoTags':[a[1]],'Layers':[]}]).encode()
 with tarfile.open(fileobj=sys.stdout.buffer,mode='w|') as t:
  for n,b in [('manifest.json',m),(h+'.json',c)]:
   x=tarfile.TarInfo(n);x.size=len(b);t.addfile(x,io.BytesIO(b))
elif a[0]=='create':print('fixture-container')
elif a[0]=='cp':pathlib.Path(a[-1]).write_bytes((r/'fixture.jar').read_bytes())
elif a[:2]==['image','inspect']:print('sha256:'+'d'*64)
''')
            docker.chmod(0o700)
            payload = {'manifest': manifest(), 'username': 'fixture-actor', 'token': 'fixture-private-token'}
            with patch.dict(os.environ, {'PATH': str(binary) + os.pathsep + os.environ['PATH'], 'FIXTURE_ROOT': str(root)}):
                receiver.deploy_registry(VERSION, io.BytesIO(json.dumps(payload).encode()), root)
            calls = (root / 'commands').read_text()
            self.assertIn(registry_release.REPOSITORY + '@' + manifest()['imageManifestDigest'], calls)
            self.assertNotIn('fixture-private-token', calls)
            self.assertEqual((root / 'deployed').read_text(), VERSION)
            self.assertFalse(Path((root / 'auth-directory').read_text()).exists())
            saved = (root / 'releases' / VERSION / 'manifest.json').read_text()
            self.assertNotIn('fixture-private-token', saved)
            self.assertEqual(json.loads(saved), manifest())
            other = 'c' * 40
            payload['manifest'] = {**manifest(), 'sourceSha': other, 'jarSha256': '0' * 64}
            with patch.dict(os.environ, {'PATH': str(binary) + os.pathsep + os.environ['PATH'], 'FIXTURE_ROOT': str(root)}):
                with self.assertRaises(SystemExit) as error:
                    receiver.deploy_registry(other, io.BytesIO(json.dumps(payload).encode()), root)
            self.assertEqual(str(error.exception), 'Pulled image JAR differs from tested artifact')
            self.assertEqual((root / 'deployed').read_text(), VERSION)
            self.assertFalse((root / 'releases' / other).exists())
            self.assertFalse(Path((root / 'auth-directory').read_text()).exists())


if __name__ == '__main__':
    unittest.main()
