#!/usr/bin/env python3
"""Mirror a verified release, then separately deploy the private Cloud Run backup."""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time
from urllib.parse import unquote, urlsplit
from zoneinfo import ZoneInfo

HOME = Path(__file__).resolve().parents[1] / 'deployment/home'
sys.path.insert(0, str(HOME))
from image_identity import loaded_image_config_digest
from registry_release import DIGEST, validate_manifest

PROJECT = 'ziper-production'
REGION = 'asia-southeast1'
SERVICE = 'ziper-backup'
AR_HOST = REGION + '-docker.pkg.dev'
AR_IMAGE = AR_HOST + '/' + PROJECT + '/ziper-releases/ziper-server'
RUNTIME = 'ziper-runtime@' + PROJECT + '.iam.gserviceaccount.com'
SCHEDULE = Path(__file__).resolve().parents[1] / 'config/production.json'
ORIGINAL_FIELDS = {'sourceSha', 'registryImage', 'imageManifestDigest', 'imageConfigDigest', 'jarSha256'}
MIRROR_FIELDS = ORIGINAL_FIELDS | {'artifactImage', 'artifactManifestDigest', 'image'}
DEPLOYED_FIELDS = MIRROR_FIELDS | {'service', 'url', 'revision', 'imageDigest'}


class Refused(ValueError):
    pass


def cli(args, *, env=None, data=None, missing=False, timeout=900, run=subprocess.run):
    """Keep raw CLI output private, including errors from application startup."""
    try:
        result = run(args, input=data, env=env, capture_output=True, timeout=timeout)
    except (OSError, subprocess.SubprocessError):
        raise Refused('command_failed_or_outcome_unknown') from None
    if result.returncode:
        stderr = result.stderr.decode(errors='replace') if isinstance(result.stderr, bytes) else result.stderr
        if missing and re.search(r'\bNOT_FOUND\b', stderr or ''):
            return None
        raise Refused('command_failed_or_outcome_unknown')
    return result.stdout.decode() if isinstance(result.stdout, bytes) else result.stdout


def gcloud(*args, **kwargs):
    return cli(['gcloud', *args, '--project', PROJECT, '--quiet', '--format=json'], **kwargs)


def json_value(raw):
    try:
        return json.loads(raw)
    except (TypeError, ValueError):
        raise Refused('invalid_provider_metadata') from None


def resource_value(raw):
    value = json_value(raw)
    if not isinstance(value, dict) or any(not isinstance(value.get(key, {}), dict)
                                           for key in ('metadata', 'spec', 'status')):
        raise Refused('invalid_provider_resource_metadata')
    return value


def source_sha(value):
    if not isinstance(value, str) or not re.fullmatch('[a-f0-9]{40}', value):
        raise Refused('invalid_source_commit')
    return value


def read_manifest(path, source):
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 8192:
        raise Refused('invalid_release_manifest_file')
    value = json_value(path.read_text())
    try:
        return validate_manifest(value, source_sha(source))
    except SystemExit:
        raise Refused('invalid_registry_release_manifest') from None


def read_mirror(path, source):
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 16384:
        raise Refused('invalid_mirror_manifest_file')
    value = json_value(path.read_text())
    if not isinstance(value, dict) or set(value) not in (MIRROR_FIELDS, DEPLOYED_FIELDS):
        raise Refused('invalid_mirror_manifest_fields')
    try:
        validate_manifest({key: value[key] for key in ORIGINAL_FIELDS}, source_sha(source))
    except SystemExit:
        raise Refused('invalid_registry_release_manifest') from None
    digest = value['artifactManifestDigest']
    if (value['artifactImage'] != AR_IMAGE or not isinstance(digest, str)
            or not re.fullmatch(DIGEST, digest) or value['image'] != AR_IMAGE + '@' + digest):
        raise Refused('unapproved_artifact_image')
    return value


def write_metadata(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    pending = path.with_name(path.name + '.next')
    pending.write_text(json.dumps(value, indent=2) + '\n')
    pending.replace(path)


def output(**values):
    if path := os.environ.get('GITHUB_OUTPUT'):
        with open(path, 'a') as stream:
            for key, value in values.items():
                stream.write(key + '=' + value + '\n')


def ar_digest(source, *, env=None):
    # The image-describe command also queries Container Analysis; tags need only AR.
    raw = gcloud('artifacts', 'docker', 'tags', 'list', AR_IMAGE, env=env, missing=True)
    if raw is None:
        return None
    records = json_value(raw)
    if not isinstance(records, list):
        raise Refused('invalid_artifact_tag_metadata')
    matches = []
    for record in records:
        if not isinstance(record, dict) or not isinstance(record.get('tag'), str):
            raise Refused('invalid_artifact_tag_metadata')
        if record['tag'].rsplit('/', 1)[-1] != source:
            continue
        if record.get('image') != AR_IMAGE or not isinstance(record.get('version'), str):
            raise Refused('unapproved_artifact_tag')
        digest = unquote(record['version'].rsplit('/', 1)[-1])
        if not re.fullmatch(DIGEST, digest):
            raise Refused('invalid_artifact_digest')
        matches.append(digest)
    if len(matches) > 1:
        raise Refused('ambiguous_artifact_tag')
    return matches[0] if matches else None


def verify_config(image, expected, env, directory):
    try:
        actual = loaded_image_config_digest(image, env, directory)
    except (SystemExit, OSError, ValueError, subprocess.SubprocessError):
        raise Refused('image_config_verification_failed') from None
    if actual != expected:
        raise Refused('image_config_mismatch')


def prepare(manifest, output_path):
    username = os.environ.get('GITHUB_ACTOR', '')
    token = os.environ.get('GHCR_TOKEN', '')
    if (not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9\[\]-]{0,63}', username)
            or not 1 <= len(token) <= 4096 or any(c.isspace() for c in token)):
        raise Refused('registry_credentials_missing_or_invalid')
    with tempfile.TemporaryDirectory() as temporary:
        directory = Path(temporary)
        env = dict(os.environ, DOCKER_CONFIG=str(directory / 'docker'))
        env.pop('GHCR_TOKEN', None)
        env.pop('GITHUB_TOKEN', None)
        cli(['docker', 'login', 'ghcr.io', '--username', username, '--password-stdin'],
            env=env, data=(token + '\n').encode())
        access = cli(['gcloud', 'auth', 'print-access-token', '--quiet'], env=env).strip()
        if not access or any(c.isspace() for c in access):
            raise Refused('google_credentials_unavailable')
        cli(['docker', 'login', AR_HOST, '--username', 'oauth2accesstoken', '--password-stdin'],
            env=env, data=(access + '\n').encode())
        source = manifest['sourceSha']
        ghcr = manifest['registryImage'] + '@' + manifest['imageManifestDigest']
        local = 'ziper-cloud-run-verify:' + source
        cli(['docker', 'pull', '--platform', 'linux/amd64', ghcr], env=env)
        cli(['docker', 'tag', ghcr, local], env=env)
        verify_config(local, manifest['imageConfigDigest'], env, directory)
        digest = ar_digest(source, env=env)
        if digest is None:
            target = AR_IMAGE + ':' + source
            cli(['docker', 'tag', local, target], env=env)
            # Never repeat an ambiguous push; a later run reads the tag first.
            cli(['docker', 'push', target], env=env)
            digest = ar_digest(source, env=env)
            if digest is None:
                raise Refused('published_artifact_has_no_digest')
        target = AR_IMAGE + '@' + digest
        cli(['docker', 'pull', '--platform', 'linux/amd64', target], env=env)
        cli(['docker', 'tag', target, local], env=env)
        verify_config(local, manifest['imageConfigDigest'], env, directory)
    result = {**manifest, 'artifactImage': AR_IMAGE, 'artifactManifestDigest': digest, 'image': target}
    write_metadata(output_path, result)
    output(image=target)
    return result


def deployment_allowed(now=None):
    value = json_value(SCHEDULE.read_text())['homeSchedule']
    if value['timeZone'] != 'Asia/Seoul':
        raise Refused('invalid_deployment_schedule')
    if (any(not isinstance(value[key], str) or not re.fullmatch(r'([01]\d|2[0-3]):[0-5]\d', value[key])
            for key in ('start', 'end')) or value['start'] == value['end']
            or type(value['deploySafetyMinutes']) is not int):
        raise Refused('invalid_deployment_schedule')
    minute = lambda text: int(text.split(':')[0]) * 60 + int(text.split(':')[1])
    start = (minute(value['start']) - value['deploySafetyMinutes']) % 1440
    end = minute(value['end'])
    if not 0 <= value['deploySafetyMinutes'] <= 120 or start == end:
        raise Refused('invalid_deployment_schedule')
    local = (now or datetime.now(timezone.utc)).astimezone(ZoneInfo(value['timeZone']))
    current = local.hour * 60 + local.minute
    blocked = start <= current < end if start < end else current >= start or current < end
    return not blocked


def desired_env(source):
    return {'SPRING_PROFILES_ACTIVE': 'prod',
            'SPRING_CONFIG_IMPORT': 'file:/run/ziper/config/application.properties',
            'SPRING_FLYWAY_ENABLED': 'false', 'APP_RUNTIME_MODE': 'server',
            'APP_MONITORING_METRICS_ENABLED': 'false', 'APP_MONITORING_ORIGIN': 'cloudrun',
            'SENTRY_ENVIRONMENT': 'prod', 'SENTRY_RELEASE': source,
            'JAVA_TOOL_OPTIONS': '-XX:MaxRAMPercentage=70'}


def run_url(value):
    if not isinstance(value, str):
        raise Refused('invalid_cloud_run_url')
    parsed = urlsplit(value)
    if (parsed.scheme != 'https' or not parsed.hostname or not parsed.hostname.startswith(SERVICE + '-')
            or not parsed.hostname.endswith('.run.app') or parsed.port or parsed.username or parsed.password
            or parsed.path not in ('', '/') or parsed.query or parsed.fragment):
        raise Refused('invalid_cloud_run_url')
    return value.rstrip('/')


def is_ready(resource):
    if not isinstance(resource, dict) or not isinstance(resource.get('status'), dict):
        return False
    conditions = resource['status'].get('conditions', [])
    return isinstance(conditions, list) and any(isinstance(condition, dict)
        and condition.get('type') == 'Ready' and condition.get('status') == 'True' for condition in conditions)


def revision_matches(resource, release):
    try:
        spec = resource['spec']
        container = spec['containers'][0]
        env = {item['name']: item.get('value') for item in container.get('env', [])}
        annotations = resource['metadata'].get('annotations', {})
        limits = container['resources']['limits']
        probe = container['startupProbe']
        return (container['image'] == release['image']
                and all(env.get(k) == v for k, v in desired_env(release['sourceSha']).items())
                and annotations.get('autoscaling.knative.dev/minScale', '0') == '0'
                and annotations.get('run.googleapis.com/cpu-throttling') == 'true'
                and annotations.get('run.googleapis.com/startup-cpu-boost') == 'false'
                and annotations.get('run.googleapis.com/execution-environment') == 'gen2'
                and limits.get('cpu') in ('1', '1000m') and limits.get('memory') in ('1Gi', '1024Mi')
                and spec['containerConcurrency'] == 20 and spec['timeoutSeconds'] == 30
                and probe['httpGet']['path'] == '/readyz' and probe['httpGet']['port'] == 8080
                and probe['timeoutSeconds'] == 3 and probe['periodSeconds'] == 5
                and probe['failureThreshold'] == 30)
    except (KeyError, TypeError, IndexError, AttributeError):
        return False


def wait_for_revision(resource, revision, release, *, now=time.monotonic, sleep=time.sleep, budget=180):
    deadline = now() + budget
    while True:
        if not revision_matches(resource, release):
            raise Refused('immutable_revision_configuration_drift_requires_new_source')
        if is_ready(resource):
            digest = resource.get('status', {}).get('imageDigest', '')
            if not isinstance(digest, str) or digest.rsplit('@', 1)[-1] != release['artifactManifestDigest']:
                raise Refused('cloud_run_revision_image_mismatch')
            return resource
        condition = next((c for c in resource.get('status', {}).get('conditions', [])
                          if c.get('type') == 'Ready'), {})
        if condition.get('status') == 'False':
            reason = condition.get('reason', '')
            safe = reason if isinstance(reason, str) and re.fullmatch(r'[A-Za-z][A-Za-z0-9_]{0,63}', reason) else 'unspecified'
            raise Refused('cloud_run_revision_failed_' + safe)
        remaining = deadline - now()
        if remaining <= 0:
            raise Refused('revision_still_reconciling_no_deploy_reissued')
        sleep(min(5, remaining))
        remaining = deadline - now()
        if remaining <= 0:
            raise Refused('revision_still_reconciling_no_deploy_reissued')
        resource = resource_value(gcloud('run', 'revisions', 'describe', revision, '--region', REGION,
                                     timeout=min(30, remaining)))


def service_limits_match(resource):
    annotations = resource.get('metadata', {}).get('annotations', {})
    return (annotations.get('run.googleapis.com/maxScale') == '1'
            and annotations.get('run.googleapis.com/minScale', '0') == '0')


def serves_revision(resource, revision):
    traffic = resource.get('status', {}).get('traffic', [])
    if not isinstance(traffic, list) or any(not isinstance(item, dict) or type(item.get('percent', 0)) is not int
                                          for item in traffic):
        return False
    return (any(item.get('revisionName') == revision and item.get('percent') == 100
                                            for item in traffic)
            and not any(item.get('revisionName') != revision and item.get('percent', 0) > 0 for item in traffic))


def deploy(release, output_path):
    if not deployment_allowed():
        raise Refused('deployment_deferred_by_home_schedule')
    revision = SERVICE + '-s' + release['sourceSha']
    current_revision = gcloud('run', 'revisions', 'describe', revision, '--region', REGION, missing=True, timeout=30)
    if current_revision is not None:
        wait_for_revision(resource_value(current_revision), revision, release)
        resource = resource_value(gcloud('run', 'services', 'describe', SERVICE, '--region', REGION))
        if not is_ready(resource):
            raise Refused('service_still_reconciling_no_deploy_reissued')
        status = resource['status']
        if status.get('latestCreatedRevisionName') != status.get('latestReadyRevisionName'):
            raise Refused('preceding_deployment_not_ready_inspect_before_retry')
        if not service_limits_match(resource):
            raise Refused('service_scaling_drift_requires_new_source')
        if not serves_revision(resource, revision):
            if not deployment_allowed():
                raise Refused('deployment_deferred_by_home_schedule')
            gcloud('run', 'services', 'update-traffic', SERVICE, '--region', REGION,
                   '--to-revisions=' + revision + '=100')
            resource = resource_value(gcloud('run', 'services', 'describe', SERVICE, '--region', REGION))
    else:
        existing = gcloud('run', 'services', 'describe', SERVICE, '--region', REGION, missing=True)
        resource = resource_value(existing) if existing is not None else None
        status = resource.get('status', {}) if isinstance(resource, dict) else {}
        if resource is not None and (not is_ready(resource)
                or status.get('latestCreatedRevisionName') != status.get('latestReadyRevisionName')):
            raise Refused('preceding_deployment_not_ready_inspect_before_retry')
        # Recheck immediately before the mutation after all lookups.
        if not deployment_allowed():
            raise Refused('deployment_deferred_by_home_schedule')
        env = ','.join(k + '=' + v for k, v in desired_env(release['sourceSha']).items())
        gcloud('run', 'deploy', SERVICE, '--region', REGION, '--image', release['image'],
               '--service-account', RUNTIME, '--execution-environment=gen2', '--cpu=1', '--memory=1Gi',
               '--min=0', '--max=1', '--cpu-throttling', '--no-cpu-boost', '--concurrency=20', '--timeout=30',
               '--revision-suffix=s' + release['sourceSha'],
               '--startup-probe=httpGet.path=/readyz,httpGet.port=8080,timeoutSeconds=3,periodSeconds=5,failureThreshold=30',
               '--set-env-vars=' + env,
               '--set-secrets=/run/ziper/config/application.properties=ziper-runtime-properties:1,/run/ziper/db-ca.pem=ziper-db-ca:1',
               '--labels=service=ziper,source-sha=' + release['sourceSha'])
        resource = resource_value(gcloud('run', 'services', 'describe', SERVICE, '--region', REGION))
        revision_data = resource_value(gcloud('run', 'revisions', 'describe', revision, '--region', REGION))
        wait_for_revision(revision_data, revision, release)
    if not is_ready(resource) or not service_limits_match(resource) or not serves_revision(resource, revision):
        raise Refused('cloud_run_service_not_ready_or_configuration_mismatch')
    status = resource['status']
    result = {**release, 'service': SERVICE, 'url': run_url(status.get('url')), 'revision': revision,
              'imageDigest': release['artifactManifestDigest']}
    write_metadata(output_path, result)
    output(image=release['image'], url=result['url'], deferred='false')
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=('prepare', 'deploy'))
    parser.add_argument('--source', required=True)
    parser.add_argument('--manifest', type=Path, default=Path('dist/registry-release.json'))
    parser.add_argument('--release', type=Path, default=Path('dist/cloud-run-release.json'))
    args = parser.parse_args()
    try:
        source_sha(args.source)
        result = (prepare(read_manifest(args.manifest, args.source), args.release) if args.mode == 'prepare'
                  else deploy(read_mirror(args.release, args.source), args.release))
        print(json.dumps({'result': 'prepared' if args.mode == 'prepare' else 'provider_ready',
                          'sourceSha': result['sourceSha'], 'image': result['image']}))
        return 0
    except (Refused, OSError, ValueError, KeyError, TypeError):
        # No raw CLI exception, secret values, database strings or response body.
        reason = sys.exc_info()[1]
        if isinstance(reason, Refused) and str(reason) == 'deployment_deferred_by_home_schedule':
            output(deferred='true')
            print(json.dumps({'result': 'deferred', 'phase': args.mode, 'reason': str(reason)}))
            return 0
        print(json.dumps({'result': 'failed', 'phase': args.mode,
                          'reason': str(reason) if isinstance(reason, Refused) else 'deployment_configuration_or_io_failed'}))
        return 1


if __name__ == '__main__':
    sys.exit(main())
