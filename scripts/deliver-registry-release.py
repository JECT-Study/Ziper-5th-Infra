#!/usr/bin/env python3
"""Deliver only bounded release metadata, pinned configuration and a read-only job credential over SSH."""
import base64
import datetime
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'deployment/home'))
from registry_release import (CONFIG_SECRETS, PAYLOAD_LIMIT, secret_versions, validate_config,
                              validate_manifest)


def load_config(directory):
    """Read the pinned Secret Manager files the workflow fetched; values never enter the report."""
    versions = secret_versions(json.loads((ROOT / 'config/production.json').read_text()))
    files = {name: base64.b64encode((directory / name).read_bytes()).decode()
             for name in CONFIG_SECRETS.values()}
    value = {'versions': versions, 'files': files}
    config_id, _, _ = validate_config(value)
    return value, config_id, versions


def main():
    connection = sys.argv[1:]
    if not connection or Path(connection[0]).name != 'ssh':
        raise SystemExit('Supply the SSH executable and connection arguments')
    version = os.environ['GITHUB_SHA']
    manifest = validate_manifest(json.loads(Path('dist/registry-release.json').read_text()), version)
    config, config_id, versions = load_config(Path(os.environ['ZIPER_HOME_CONFIG_DIR']))
    report = {'checkedAt': datetime.datetime.now(datetime.timezone.utc).isoformat(),
              'scope': 'Restricted SSH control, pinned configuration and registry pull', 'checks': {},
              'configId': config_id, 'secretVersions': versions, 'result': 'failed'}
    try:
        result = subprocess.run(connection + ['check'], input=b'', capture_output=True, timeout=30)
        if result.returncode or b'ZIPER_CI_RECEIVER_READY' not in result.stdout:
            raise ValueError()
        report['checks']['check'] = True
        result = subprocess.run(connection + ['whoami'], input=b'', capture_output=True, timeout=30)
        if result.returncode not in (1, 2) or result.stdout.strip():
            raise ValueError()
        report['checks']['generalCommandDenied'] = True
        payload = json.dumps({'manifest': manifest, 'username': os.environ['GITHUB_ACTOR'],
                              'token': os.environ['GHCR_TOKEN'], 'config': config}).encode()
        if len(payload) > PAYLOAD_LIMIT:
            raise ValueError()
        report['payloadBytes'] = len(payload)
        result = subprocess.run(connection + ['deploy-registry ' + version], input=payload,
                                capture_output=True, timeout=900)
        if result.returncode == 75 and b'ZIPER_DEPLOY_DEFERRED' in result.stdout:
            report['result'] = 'deferred'
            report['checks']['runtimeDeferred'] = True
            return write_report(report)
        if result.returncode:
            report['receiverExitCode'] = result.returncode
            known_failures = {
                b'Registry authentication failed': 'registry_authentication',
                b'Registry image pull failed': 'registry_pull',
                b'Immutable release manifest mismatch': 'immutable_manifest_mismatch',
                b'Pulled image config differs from manifest': 'image_config_mismatch',
                b'Registry image identity metadata invalid': 'registry_identity_invalid',
                b'Pulled image metadata differs from registry': 'engine_identity_mismatch',
                b'Registry image identity inspection failed': 'registry_identity_read',
                b'Invalid image metadata member': 'image_export_metadata',
                b'Expected one image in export': 'image_export_multiple',
                b'Invalid registry control payload': 'control_payload',
                b'Invalid registry control fields': 'control_fields',
                b'Invalid registry actor': 'control_actor',
                b'Invalid registry credential': 'control_credentials',
                b'Invalid configuration bundle': 'control_configuration',
                b'Pinned secret versions are missing or invalid': 'control_secret_versions',
                b'Immutable configuration bundle mismatch': 'immutable_configuration_mismatch',
                b'configuration bundle': 'home_configuration',
                b'Pulled image JAR differs from tested artifact': 'tested_jar_mismatch',
                b'Unsupported receiver command': 'receiver_not_installed',
                b'Ziper deployment failed app readiness or tunnel startup': 'home_activation',
            }
            report['receiverFailure'] = next((code for text, code in known_failures.items()
                                               if text in result.stderr), 'ssh_or_receiver_failure')
            raise ValueError()
        expected = ('ZIPER_REGISTRY_MANIFEST_DIGEST=' + manifest['imageManifestDigest']).encode()
        if expected not in result.stdout:
            raise ValueError()
        if ('ZIPER_CONFIG_ID=' + config_id).encode() not in result.stdout:
            raise ValueError()
        report['checks']['configStored'] = True
        report['checks']['registryDeploy'] = True
        report['result'] = 'passed'
    except (OSError, subprocess.TimeoutExpired, ValueError):
        pass
    write_report(report)
    if report['result'] != 'passed':
        raise SystemExit('Restricted registry deployment failed; inspect host state before retrying')


def write_report(report):
    Path('dist').mkdir(exist_ok=True)
    Path('dist/receiver-control-proof.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report))
    if output := os.environ.get('GITHUB_OUTPUT'):
        with open(output, 'a') as stream:
            stream.write('deferred=' + str(report['result'] == 'deferred').lower() + '\n')


if __name__ == '__main__':
    main()
