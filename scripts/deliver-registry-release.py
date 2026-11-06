#!/usr/bin/env python3
"""Deliver only bounded release metadata and a read-only job credential over SSH."""
import datetime
import json
import os
from pathlib import Path
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'deployment/home'))
from registry_release import validate_manifest


def main():
    connection = sys.argv[1:]
    if not connection or Path(connection[0]).name != 'ssh':
        raise SystemExit('Supply the SSH executable and connection arguments')
    version = os.environ['GITHUB_SHA']
    manifest = validate_manifest(json.loads(Path('dist/registry-release.json').read_text()), version)
    report = {'checkedAt': datetime.datetime.now(datetime.timezone.utc).isoformat(),
              'scope': 'Restricted SSH control and registry pull', 'checks': {}, 'result': 'failed'}
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
                              'token': os.environ['GHCR_TOKEN']}).encode()
        if len(payload) > 8192:
            raise ValueError()
        report['payloadBytes'] = len(payload)
        result = subprocess.run(connection + ['deploy-registry ' + version], input=payload,
                                capture_output=True, timeout=900)
        if result.returncode:
            report['receiverExitCode'] = result.returncode
            known_failures = {
                b'Registry authentication failed': 'registry_authentication',
                b'Registry image pull failed': 'registry_pull',
                b'Immutable release manifest mismatch': 'immutable_manifest_mismatch',
                b'Pulled image config differs from manifest': 'image_config_mismatch',
                b'Pulled image JAR differs from tested artifact': 'tested_jar_mismatch',
                b'Unsupported receiver command': 'receiver_not_installed',
                b'Ziper deployment failed readiness verification': 'home_readiness',
            }
            report['receiverFailure'] = next((code for text, code in known_failures.items()
                                               if text in result.stderr), 'ssh_or_receiver_failure')
            raise ValueError()
        expected = ('ZIPER_REGISTRY_MANIFEST_DIGEST=' + manifest['imageManifestDigest']).encode()
        if expected not in result.stdout:
            raise ValueError()
        report['checks']['registryDeploy'] = True
        report['result'] = 'passed'
    except (OSError, subprocess.TimeoutExpired, ValueError):
        pass
    Path('dist').mkdir(exist_ok=True)
    Path('dist/receiver-control-proof.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report))
    if report['result'] != 'passed':
        raise SystemExit('Restricted registry deployment failed; inspect host state before retrying')


if __name__ == '__main__':
    main()
