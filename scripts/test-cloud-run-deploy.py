#!/usr/bin/env python3
"""Offline CLI and HTTP fixtures; these tests do not deploy to Google Cloud."""
from contextlib import contextmanager
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch


def load(name, filename):
    spec = importlib.util.spec_from_file_location(name, Path(__file__).with_name(filename))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


deploy = load('cloud_run_deployer', 'deploy-cloud-run.py')
health = load('cloud_run_verifier', 'verify-cloud-run.py')
bootstrap = load('cloud_run_bootstrap', 'bootstrap-gcp-production.py')
SOURCE = 'a' * 40
REVISION = 'ziper-backup-s' + SOURCE
GHCR_DIGEST = 'sha256:' + 'b' * 64
AR_DIGEST = 'sha256:' + 'c' * 64
CONFIG = json.dumps({'os': 'linux', 'architecture': 'amd64',
                     'rootfs': {'type': 'layers', 'diff_ids': []}}).encode()
CONFIG_DIGEST = 'sha256:' + hashlib.sha256(CONFIG).hexdigest()


def manifest():
    return {'sourceSha': SOURCE, 'registryImage': 'ghcr.io/ject-study/ziper-server',
            'imageManifestDigest': GHCR_DIGEST, 'imageConfigDigest': CONFIG_DIGEST, 'jarSha256': 'd' * 64}


def mirror():
    return {**manifest(), 'artifactImage': deploy.AR_IMAGE, 'artifactManifestDigest': AR_DIGEST,
            'image': deploy.AR_IMAGE + '@' + AR_DIGEST}


def provider():
    return {'metadata': {'annotations': {'run.googleapis.com/maxScale': '1', 'run.googleapis.com/minScale': '0'}},
            'spec': {'template': {'metadata': {'annotations': {
                'run.googleapis.com/cpu-throttling': 'true',
                'run.googleapis.com/startup-cpu-boost': 'false',
                'run.googleapis.com/execution-environment': 'gen2'}},
                'spec': {'containerConcurrency': 20, 'timeoutSeconds': 30, 'serviceAccountName': deploy.RUNTIME,
                         'volumes': [
                             {'name': 'config-volume-uniquename', 'secret': {'secretName': 'ziper-runtime-properties',
                              'items': [{'key': '1', 'path': 'application.properties'}]}},
                             {'name': 'ca-volume-uniquename', 'secret': {'secretName': 'ziper-db-ca',
                              'items': [{'key': '1', 'path': 'db-ca.pem'}]}}],
                         'containers': [
                    {'image': mirror()['image'], 'resources': {'limits': {'cpu': '1', 'memory': '1Gi'}},
                     'volumeMounts': [{'name': 'config-volume-uniquename', 'mountPath': '/run/ziper-config'},
                                      {'name': 'ca-volume-uniquename', 'mountPath': '/run/ziper'}],
                     'startupProbe': {'httpGet': {'path': '/readyz', 'port': 8080},
                                      'timeoutSeconds': 3, 'periodSeconds': 5, 'failureThreshold': 30},
                     'env': [{'name': k, 'value': v} for k, v in deploy.desired_env(SOURCE).items()]}]}}},
            'status': {'url': 'https://ziper-backup-45190721178.asia-southeast1.run.app',
                       'latestCreatedRevisionName': REVISION,
                       'latestReadyRevisionName': REVISION,
                       'traffic': [{'revisionName': REVISION, 'percent': 100}],
                       'conditions': [{'type': 'Ready', 'status': 'True'}]}}


def revision(digest=AR_DIGEST):
    template = provider()['spec']['template']
    return {**template, 'status': {'conditions': [{'type': 'Ready', 'status': 'True'}],
                       'imageDigest': deploy.AR_IMAGE + '@' + digest}}


@contextmanager
def fake_cli(*, existing=False, deny=False, mismatch=False):
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        binary = root / 'bin'
        binary.mkdir()
        (root / 'config.json').write_bytes(CONFIG)
        if existing:
            (root / 'ar-present').write_text('yes')
        if deny:
            (root / 'deny').write_text('yes')
        if mismatch:
            (root / 'mismatch').write_text('yes')
        program = '''#!/usr/bin/env python3
import hashlib,io,json,os,pathlib,sys,tarfile
r=pathlib.Path(os.environ['FIXTURE_ROOT']);a=sys.argv[1:];name=pathlib.Path(sys.argv[0]).name
with (r/'commands').open('a') as f:f.write(json.dumps([name,*a])+'\\n')
if name=='gcloud':
 if a[:2]==['auth','print-access-token']:print('private-google-access-marker')
 elif a[:4]==['artifacts','docker','tags','list']:
  if (r/'deny').exists():sys.stderr.write('PERMISSION_DENIED private-response-marker');sys.exit(1)
  if not (r/'ar-present').exists():sys.stderr.write('NOT_FOUND missing package');sys.exit(1)
  image='asia-southeast1-docker.pkg.dev/ziper-production/ziper-releases/ziper-server'
  print(json.dumps([{'tag':'projects/p/locations/l/repositories/r/packages/i/tags/'+'a'*40,
                    'image':image,'version':'projects/p/locations/l/repositories/r/packages/i/versions/sha256:'+'c'*64}]))
else:
 if a[0]=='login':
  token=sys.stdin.read();d=pathlib.Path(os.environ['DOCKER_CONFIG']);d.mkdir(parents=True,exist_ok=True)
  (d/'config.json').write_text(token);(r/'auth-directory').write_text(str(d))
 elif a[0]=='push':
  (r/'ar-present').write_text('yes')
  with (r/'pushes').open('a') as f:f.write('push\\n')
 elif a[0]=='pull' and 'pkg.dev/' in a[-1]:(r/'active-ar').write_text('yes')
 elif a[0]=='save':
  c=(r/'config.json').read_bytes()
  if (r/'mismatch').exists() and (r/'active-ar').exists():c=c.replace(b'"amd64"',b'"arm64"')
  h=hashlib.sha256(c).hexdigest();m=json.dumps([{'Config':h+'.json','RepoTags':[a[1]],'Layers':[]}]).encode()
  with tarfile.open(fileobj=sys.stdout.buffer,mode='w|') as t:
   for n,b in [('manifest.json',m),(h+'.json',c)]:
    x=tarfile.TarInfo(n);x.size=len(b);t.addfile(x,io.BytesIO(b))
'''
        for name in ('docker', 'gcloud'):
            path = binary / name
            path.write_text(program)
            path.chmod(0o700)
        with patch.dict(os.environ, {'PATH': str(binary) + os.pathsep + os.environ['PATH'],
                                     'FIXTURE_ROOT': str(root), 'GITHUB_ACTOR': 'fixture-actor',
                                     'GHCR_TOKEN': 'private-ghcr-marker'}):
            yield root


class CloudRunDeployTests(unittest.TestCase):
    def test_private_verifier_cli_starts_and_rejects_missing_token_without_disclosure(self):
        script = str(Path(__file__).with_name('verify-cloud-run.py'))
        help_result = subprocess.run([sys.executable, script, '--help'], capture_output=True, text=True)
        self.assertEqual(help_result.returncode, 0, help_result.stderr)
        self.assertIn('--source', help_result.stdout)
        env = {key: value for key, value in os.environ.items() if key != 'CLOUD_RUN_ID_TOKEN'}
        result = subprocess.run([sys.executable, script, '--url', 'https://ziper-backup-fixture.run.app',
                                 '--source', SOURCE], env=env, capture_output=True, text=True)
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertNotIn('Traceback', result.stderr)
        self.assertIn('private ID token environment', result.stderr)

    def test_actual_cli_mirror_pins_both_digests_and_cleans_credentials(self):
        with fake_cli() as root:
            result = deploy.prepare(manifest(), root / 'release.json')
            self.assertEqual(result, mirror())
            calls = (root / 'commands').read_text()
            self.assertIn(manifest()['registryImage'] + '@' + GHCR_DIGEST, calls)
            self.assertIn(deploy.AR_IMAGE + '@' + AR_DIGEST, calls)
            self.assertNotIn('private-ghcr-marker', calls)
            self.assertNotIn('private-google-access-marker', calls)
            self.assertNotIn('private-', (root / 'release.json').read_text())
            self.assertFalse(Path((root / 'auth-directory').read_text()).exists())
            self.assertEqual((root / 'pushes').read_text().splitlines(), ['push'])
            deploy.prepare(manifest(), root / 'release.json')
            self.assertEqual((root / 'pushes').read_text().splitlines(), ['push'])

    def test_auth_failure_is_not_absence_and_never_pushes(self):
        with fake_cli(deny=True) as root:
            with self.assertRaises(deploy.Refused) as error:
                deploy.prepare(manifest(), root / 'release.json')
            self.assertNotIn('private-response-marker', str(error.exception))
            self.assertFalse((root / 'pushes').exists())
            self.assertFalse((root / 'release.json').exists())
            self.assertFalse(Path((root / 'auth-directory').read_text()).exists())

    def test_existing_mirror_with_wrong_config_is_refused_without_push(self):
        with fake_cli(existing=True, mismatch=True) as root:
            with self.assertRaises(deploy.Refused):
                deploy.prepare(manifest(), root / 'release.json')
            self.assertFalse((root / 'pushes').exists())
            self.assertFalse((root / 'release.json').exists())
            self.assertFalse(Path((root / 'auth-directory').read_text()).exists())

    def test_manifest_rejects_repository_digest_and_source_substitution(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'mirror.json'
            for replacement in ({'artifactImage': 'attacker.test/image'},
                                {'artifactManifestDigest': 'latest'}, {'sourceSha': 'f' * 40},
                                {'image': deploy.AR_IMAGE + ':latest'}):
                path.write_text(json.dumps({**mirror(), **replacement}))
                with self.subTest(replacement=replacement), self.assertRaises(deploy.Refused):
                    deploy.read_mirror(path, SOURCE)

    def test_schedule_boundary_is_end_exclusive_and_has_no_override(self):
        for utc, allowed in [('2026-11-06T17:29:59+00:00', True),
                             ('2026-11-06T17:30:00+00:00', False),
                             ('2026-11-06T20:59:59+00:00', False),
                             ('2026-11-06T21:00:00+00:00', True)]:
            with self.subTest(utc=utc):
                self.assertEqual(deploy.deployment_allowed(datetime.fromisoformat(utc)), allowed)

    def test_schedule_blocks_before_provider_calls_and_rechecks_before_mutation(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / 'release.json'
            with patch.object(deploy, 'deployment_allowed', return_value=False), patch.object(deploy, 'gcloud') as api:
                with self.assertRaises(deploy.Refused): deploy.deploy(mirror(), output)
                api.assert_not_called()
            with patch.object(deploy, 'deployment_allowed', side_effect=[True, False]), patch.object(deploy, 'gcloud', return_value=None) as api:
                with self.assertRaises(deploy.Refused): deploy.deploy(mirror(), output)
                self.assertEqual(api.call_count, 2)

    def test_not_ready_previous_deployment_is_not_automatically_reissued(self):
        service = provider()
        service['status']['latestCreatedRevisionName'] = 'ziper-backup-00002-pending'
        with tempfile.TemporaryDirectory() as directory, patch.object(deploy, 'deployment_allowed', return_value=True), \
                patch.object(deploy, 'gcloud', side_effect=[None, json.dumps(service)]) as api:
            with self.assertRaises(deploy.Refused) as error:
                deploy.deploy(mirror(), Path(directory) / 'release.json')
            self.assertEqual(str(error.exception), 'preceding_deployment_not_ready_inspect_before_retry')
            self.assertEqual(api.call_count, 2)

    def test_ready_same_release_is_read_and_verified_without_redeployment(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(deploy, 'deployment_allowed', return_value=True), \
                patch.object(deploy, 'gcloud', side_effect=[json.dumps(revision()), json.dumps(provider())]) as api:
            result = deploy.deploy(mirror(), Path(directory) / 'release.json')
            self.assertEqual(result['imageDigest'], AR_DIGEST)
            self.assertEqual(result['revision'], REVISION)
            self.assertFalse(any(call.args[:2] == ('run', 'deploy') for call in api.call_args_list))

    def test_one_deploy_uses_secret_files_and_no_public_invocation_flag(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(deploy, 'deployment_allowed', return_value=True), \
                patch.object(deploy, 'gcloud', side_effect=[None, None, '{}', json.dumps(provider()), json.dumps(revision())]) as api:
            result = deploy.deploy(mirror(), Path(directory) / 'release.json')
            self.assertEqual(result['service'], 'ziper-backup')
            mutations = [call.args for call in api.call_args_list if call.args[:2] == ('run', 'deploy')]
            self.assertEqual(len(mutations), 1)
            args = mutations[0]
            self.assertIn('--cpu-throttling', args)
            self.assertIn('--no-cpu-boost', args)
            self.assertIn('--max=1', args)
            self.assertIn('--min=0', args)
            self.assertIn('--revision-suffix=s' + SOURCE, args)
            self.assertFalse(any('allow-unauthenticated' in arg for arg in args))
            self.assertTrue(any('ziper-runtime-properties:1' in arg for arg in args))
            self.assertTrue(any('SPRING_FLYWAY_ENABLED=false' in arg for arg in args))

    def test_ready_revision_must_match_pinned_artifact_digest(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(deploy, 'deployment_allowed', return_value=True), \
                patch.object(deploy, 'gcloud', side_effect=[json.dumps(revision(GHCR_DIGEST))]):
            with self.assertRaises(deploy.Refused) as error:
                deploy.deploy(mirror(), Path(directory) / 'release.json')
            self.assertEqual(str(error.exception), 'cloud_run_revision_image_mismatch')

    def test_existing_revision_drift_fails_without_deploying(self):
        changed = revision()
        changed['spec']['containers'][0]['env'][0]['value'] = 'wrong'
        with tempfile.TemporaryDirectory() as directory, patch.object(deploy, 'deployment_allowed', return_value=True), \
                patch.object(deploy, 'gcloud', return_value=json.dumps(changed)) as api:
            with self.assertRaises(deploy.Refused) as error:
                deploy.deploy(mirror(), Path(directory) / 'release.json')
            self.assertEqual(str(error.exception), 'immutable_revision_configuration_drift_requires_new_source')
            self.assertEqual(api.call_count, 1)

    def test_revision_requires_exact_runtime_identity(self):
        for identity in (None, 'default', 'attacker@ziper-production.iam.gserviceaccount.com'):
            changed = revision()
            changed['spec']['serviceAccountName'] = identity
            with self.subTest(identity=identity):
                self.assertFalse(deploy.revision_matches(changed, mirror()))

    def test_secret_volume_drift_and_overlapping_mounts_are_rejected(self):
        def wrong_name(resource): resource['spec']['volumes'][0]['secret']['secretName'] = 'another-secret'
        def wrong_version(resource): resource['spec']['volumes'][0]['secret']['items'][0]['key'] = 'latest'
        def wrong_file(resource): resource['spec']['volumes'][0]['secret']['items'][0]['path'] = '../application.properties'
        def nested_mount(resource): resource['spec']['containers'][0]['volumeMounts'][0]['mountPath'] = '/run/ziper/config'
        def extra_mount(resource): resource['spec']['containers'][0]['volumeMounts'].append({'name': 'config-volume-uniquename', 'mountPath': '/etc'})
        def duplicate_volume(resource): resource['spec']['volumes'][1]['name'] = resource['spec']['volumes'][0]['name']
        def missing_item(resource): resource['spec']['volumes'][0]['secret']['items'] = []
        def optional(resource): resource['spec']['volumes'][0]['secret']['optional'] = True
        for mutation in (wrong_name, wrong_version, wrong_file, nested_mount, extra_mount, duplicate_volume, missing_item, optional):
            changed = revision()
            mutation(changed)
            with self.subTest(mutation=mutation.__name__):
                self.assertFalse(deploy.revision_matches(changed, mirror()))

    def test_same_project_secret_aliases_resolve_without_assuming_volume_names(self):
        changed = revision()
        changed['metadata']['annotations']['run.googleapis.com/secrets'] = (
            'properties-uuid:projects/45190721178/secrets/ziper-runtime-properties,'
            'ca-uuid:projects/ziper-production/secrets/ziper-db-ca')
        changed['spec']['volumes'][0]['secret']['secretName'] = 'properties-uuid'
        changed['spec']['volumes'][1]['secret']['secretName'] = 'ca-uuid'
        self.assertTrue(deploy.revision_matches(changed, mirror()))
        changed['metadata']['annotations']['run.googleapis.com/secrets'] = (
            'properties-uuid:projects/999999999/secrets/ziper-runtime-properties,'
            'ca-uuid:projects/ziper-production/secrets/ziper-db-ca')
        self.assertFalse(deploy.revision_matches(changed, mirror()))

    def test_unknown_or_unused_secret_alias_is_not_ignored(self):
        for aliases in ('unused:projects/45190721178/secrets/ziper-db-ca',
                        'bad:projects/45190721178/secrets/unknown',
                        'dup:projects/45190721178/secrets/ziper-db-ca,dup:projects/45190721178/secrets/ziper-db-ca'):
            changed = revision()
            changed['metadata']['annotations']['run.googleapis.com/secrets'] = aliases
            with self.subTest(aliases=aliases):
                self.assertFalse(deploy.revision_matches(changed, mirror()))

    def test_reconciling_revision_is_polled_read_only_then_reused(self):
        pending = revision()
        pending['status']['conditions'][0]['status'] = 'Unknown'
        elapsed = [0]
        with patch.object(deploy, 'gcloud', return_value=json.dumps(revision())) as api:
            result = deploy.wait_for_revision(pending, REVISION, mirror(), now=lambda: elapsed[0],
                                              sleep=lambda value: elapsed.__setitem__(0, elapsed[0] + value))
            self.assertTrue(deploy.is_ready(result))
            self.assertEqual(elapsed[0], 5)
            self.assertEqual(api.call_args.args[:3], ('run', 'revisions', 'describe'))

    def test_failed_revision_returns_only_reason_code_without_raw_message(self):
        failed = revision()
        failed['status']['conditions'][0] = {'type': 'Ready', 'status': 'False',
                                            'reason': 'HealthCheckFailed', 'message': 'private-db-url-marker'}
        with self.assertRaises(deploy.Refused) as error:
            deploy.wait_for_revision(failed, REVISION, mirror())
        self.assertEqual(str(error.exception), 'cloud_run_revision_failed_HealthCheckFailed')

    def test_reconciling_revision_deadline_never_issues_deploy(self):
        pending = revision()
        pending['status']['conditions'][0]['status'] = 'Unknown'
        clock = [0]
        with patch.object(deploy, 'gcloud', return_value=json.dumps(pending)) as api:
            with self.assertRaises(deploy.Refused) as error:
                deploy.wait_for_revision(pending, REVISION, mirror(), now=lambda: clock[0],
                    sleep=lambda value: clock.__setitem__(0, clock[0] + value), budget=12)
            self.assertEqual(str(error.exception), 'revision_still_reconciling_no_deploy_reissued')
            self.assertEqual(clock[0], 12)
            self.assertTrue(all(call.args[:3] == ('run', 'revisions', 'describe') for call in api.call_args_list))

    def test_deferred_cli_emits_output_without_claiming_provider_ready(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / 'release.json'
            path.write_text(json.dumps(mirror()))
            output = root / 'outputs'
            stdout = io.StringIO()
            with patch.dict(os.environ, {'GITHUB_OUTPUT': str(output)}), \
                    patch.object(deploy, 'deployment_allowed', return_value=False), \
                    patch.object(sys, 'argv', ['deploy-cloud-run.py', 'deploy', '--source', SOURCE, '--release', str(path)]), \
                    patch.object(sys, 'stdout', stdout), patch.object(deploy, 'gcloud') as api:
                self.assertEqual(deploy.main(), 0)
                api.assert_not_called()
            self.assertEqual(output.read_text(), 'deferred=true\n')
            self.assertEqual(json.loads(stdout.getvalue())['result'], 'deferred')

    def test_health_real_http_fixture_checks_auth_negotiation_and_both_paths(self):
        requests = []

        class Handler(BaseHTTPRequestHandler):
            code = 200
            extra = False
            wrong_release = False

            def do_GET(self):
                requests.append({'path': self.path, 'accept': self.headers.get('Accept'),
                                 'authorization': self.headers.get('Authorization'),
                                 'serverlessAuthorization': self.headers.get('X-Serverless-Authorization')})
                self.send_response(self.code)
                self.send_header('Content-Type', 'application/json' if self.headers.get('Accept') == 'application/json'
                                 else 'application/vnd.spring-boot.actuator.v3+json')
                self.send_header('Cache-Control', 'no-store')
                self.send_header('X-Ziper-Origin', 'cloudrun')
                self.send_header('X-Ziper-Release', 'b' * 40 if self.wrong_release else SOURCE)
                self.end_headers()
                self.wfile.write(json.dumps({'status': 'UP', **({'private': 'private-body-marker'} if self.extra else {})}).encode())

            def log_message(self, *args):
                pass

        with ThreadingHTTPServer(('127.0.0.1', 0), Handler) as server:
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                url = 'http://127.0.0.1:' + str(server.server_port)
                elapsed = []
                result = health.verify(url, SOURCE, 'private-id-token-marker' * 3, sleep=elapsed.append)
                self.assertTrue(result['ok'])
                self.assertEqual(len(requests), 6)
                self.assertEqual(elapsed, [10, 10])
                self.assertTrue(all(r['accept'] == 'application/json' for r in requests))
                self.assertTrue(all(r['serverlessAuthorization'].startswith('Bearer ') for r in requests))
                self.assertTrue(all(r['authorization'] is None for r in requests))
                self.assertNotIn('private-id-token-marker', json.dumps(result))
                for option, value in [('code', 403), ('extra', True), ('wrong_release', True)]:
                    setattr(Handler, option, value)
                    before = len(requests)
                    result = health.verify(url, SOURCE, 'private-id-token-marker' * 3, sleep=elapsed.append)
                    self.assertFalse(result['ok'])
                    self.assertEqual(len(requests), before + 1)
                    self.assertNotIn('private-body-marker', json.dumps(result))
                    setattr(Handler, option, 200 if option == 'code' else False)
            finally:
                server.shutdown()
                thread.join()


class OidcTrustTests(unittest.TestCase):
    def trust(self, subject=None):
        return {'oidc': {'issuerUri': 'https://token.actions.githubusercontent.com'},
                'attributeMapping': bootstrap.OIDC_MAPPING,
                'attributeCondition': bootstrap.oidc_condition(subject or bootstrap.OIDC_SUBJECT)}

    def test_legacy_subject_is_migrated_without_removing_main_or_environment(self):
        with patch.object(bootstrap, 'run', side_effect=[self.trust(bootstrap.OIDC_LEGACY_SUBJECT), {}, self.trust()]) as command:
            bootstrap.ensure_wif_provider('ziper-github', 'ziper-server')
        update = command.call_args_list[1].args[0]
        self.assertIn('update-oidc', update)
        self.assertIn('--attribute-condition=' + self.trust()['attributeCondition'], update)
        self.assertIn("assertion.ref == 'refs/heads/main'", update[-1])
        self.assertIn('@1440603337:environment:production', update[-1])

    def test_matching_trust_is_only_read(self):
        with patch.object(bootstrap, 'run', side_effect=[self.trust(), self.trust()]) as command:
            bootstrap.ensure_wif_provider('ziper-github', 'ziper-server')
        self.assertTrue(all('describe' in call.args[0] for call in command.call_args_list))

    def test_unknown_condition_or_issuer_is_not_overwritten(self):
        for field in ('condition', 'issuer'):
            with self.subTest(field=field):
                trust = self.trust()
                if field == 'condition':
                    trust['attributeCondition'] += " && assertion.environment == 'production'"
                else:
                    trust['oidc']['issuerUri'] = 'https://unexpected.invalid'
                with patch.object(bootstrap, 'run', return_value=trust) as command:
                    with self.assertRaises(SystemExit):
                        bootstrap.ensure_wif_provider('ziper-github', 'ziper-server')
                self.assertEqual(command.call_count, 1)

    def test_update_requires_matching_provider_readback(self):
        with patch.object(bootstrap, 'run', side_effect=[self.trust(bootstrap.OIDC_LEGACY_SUBJECT), {}, self.trust(bootstrap.OIDC_LEGACY_SUBJECT)]):
            with self.assertRaises(SystemExit):
                bootstrap.ensure_wif_provider('ziper-github', 'ziper-server')


if __name__ == '__main__':
    unittest.main()
