#!/usr/bin/env python3
"""Verify restricted SSH and binary transport with an invalid, undeployable archive."""

import datetime
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys


def main():
    connection = sys.argv[1:]
    if not connection or Path(connection[0]).name != 'ssh':
        raise SystemExit('Supply the SSH executable and connection arguments')
    report = {"checkedAt": datetime.datetime.now(datetime.timezone.utc).isoformat(),
              "scope": "Restricted SSH and invalid binary archive; no application deployment",
              "checks": {}}
    stage = 'check'
    try:
        result = subprocess.run(connection + ['check'], input=b'', capture_output=True, timeout=30)
        if result.returncode or b'ZIPER_CI_RECEIVER_READY' not in result.stdout:
            raise ValueError('Readiness marker missing')
        report['checks'][stage] = True
        stage = 'generalCommandDenied'
        result = subprocess.run(connection + ['whoami'], input=b'', capture_output=True, timeout=30)
        if result.returncode not in (1, 2) or result.stdout.strip():
            raise ValueError('General command was not denied')
        report['checks'][stage] = True
        stage = 'binaryStream'
        payload = bytes(range(256)) * 4096
        version = hashlib.sha256(b'ziper-invalid-probe' + os.urandom(32)).hexdigest()[:40]
        result = subprocess.run(connection + ['deploy ' + version], input=payload,
                                capture_output=True, timeout=45)
        expected_size = ('ZIPER_RELEASE_BYTES=' + str(len(payload))).encode()
        expected_hash = ('ZIPER_RELEASE_SHA256=' + hashlib.sha256(payload).hexdigest()).encode()
        if result.returncode not in (1, 2) or expected_size not in result.stdout \
                or expected_hash not in result.stdout or b'ReadError' not in result.stderr:
            raise ValueError('Binary delivery or archive rejection was not verified')
        report['checks'][stage] = True
        report['fixtureBytes'] = len(payload)
        report['fixtureSha256'] = hashlib.sha256(payload).hexdigest()
        report['result'] = 'passed'
    except (OSError, subprocess.TimeoutExpired, ValueError):
        report['result'] = 'failed'
        report['failedCheck'] = stage
    path = Path('dist/receiver-stream-proof.json')
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(report))
    if report['result'] != 'passed':
        raise SystemExit(1)


if __name__ == '__main__':
    main()
