#!/usr/bin/env python3
"""Read the pinned Secret Manager versions for home into a private runner directory; never print values."""
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'deployment/home'))
from registry_release import CONFIG_FILE_LIMIT, CONFIG_SECRETS, secret_versions

PROJECT = 'ziper-production'


def fetch(directory, gcloud='gcloud'):
    versions = secret_versions(json.loads((ROOT / 'config/production.json').read_text()))
    os.umask(0o077)
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    for secret, name in CONFIG_SECRETS.items():
        target = directory / name
        result = subprocess.run([gcloud, 'secrets', 'versions', 'access', versions[secret], '--secret', secret,
                                 '--project', PROJECT, '--out-file', str(target)], capture_output=True)
        if result.returncode or not target.is_file():
            raise SystemExit('Pinned secret read failed: ' + secret)
        size = target.stat().st_size
        if not 0 < size <= CONFIG_FILE_LIMIT:
            raise SystemExit('Pinned secret size is outside the bundle limit: ' + secret)
        target.chmod(0o600)
    print(json.dumps({'secretVersions': versions, 'fetched': True}), flush=True)


def main():
    if len(sys.argv) != 2:
        raise SystemExit('Supply the private output directory')
    fetch(Path(sys.argv[1]), os.environ.get('ZIPER_GCLOUD', 'gcloud'))


if __name__ == '__main__':
    main()
