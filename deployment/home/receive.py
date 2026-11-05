#!/usr/bin/env python3
"""Receive one immutable image, never a shell command or a secret configuration."""
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tarfile
import tempfile

version = sys.argv[1]
if not re.fullmatch('[0-9a-f]{40}', version):
    raise SystemExit('Invalid release identifier')
root = Path('/opt/ziper')
archive = Path('/mnt/c/ProgramData/Ziper/incoming') / (version + '.tgz')
allowed = {'image.tar.gz', 'manifest.json', 'compose.yml', 'deploy.sh'}
with tempfile.TemporaryDirectory(dir=root) as temporary:
    stage = Path(temporary)
    with tarfile.open(archive, 'r:gz') as bundle:
        members = bundle.getmembers()
        if len(members) != len(allowed) or {m.name for m in members} != allowed:
            raise SystemExit('Unexpected release files')
        if any(not m.isfile() or m.size > 2_000_000_000 for m in members):
            raise SystemExit('Invalid release file type or size')
        bundle.extractall(stage, filter='data')
    manifest = json.loads((stage / 'manifest.json').read_text())
    if manifest.get('sourceSha') != version:
        raise SystemExit('Release source mismatch')
    if not re.fullmatch('sha256:[0-9a-f]{64}', manifest.get('imageId', '')):
        raise SystemExit('Invalid image identity')
    digest = hashlib.file_digest((stage / 'image.tar.gz').open('rb'), 'sha256').hexdigest()
    if digest != manifest.get('archiveSha256'):
        raise SystemExit('Release archive mismatch')
    # Deployment scripts are installed by the administrator, not executed from the SSH payload.
    trusted = root / 'ci'
    for filename in ('compose.yml', 'deploy.sh'):
        if (stage / filename).read_bytes() != (trusted / filename).read_bytes():
            raise SystemExit('Unapproved deployment contract')
    existing = root / 'releases' / version / 'manifest.json'
    if existing.exists() and existing.read_bytes() != (stage / 'manifest.json').read_bytes():
        raise SystemExit('Immutable release manifest mismatch')
    env = dict(os.environ, DOCKER_CONFIG=str(root / 'docker-client'))
    subprocess.run(['docker', 'load', '-i', str(stage / 'image.tar.gz')], env=env, check=True, stdout=subprocess.DEVNULL)
    actual = subprocess.check_output(['docker', 'image', 'inspect', '--format', '{{.Id}}', 'ziper-server:' + version], env=env, text=True).strip()
    if actual != manifest['imageId']:
        raise SystemExit('Loaded image differs from manifest')
    release = root / 'releases' / version
    release.mkdir(parents=True, exist_ok=True, mode=0o700)
    for filename in ('compose.yml', 'deploy.sh', 'manifest.json'):
        data = (stage / filename).read_bytes()
        target = release / filename
        if target.exists() and target.read_bytes() != data:
            raise SystemExit('Immutable release already exists with different content')
        target.write_bytes(data)
        target.chmod(0o600)
    (release / 'image-id').write_text(actual + '\n')
    subprocess.run(['bash', str(trusted / 'deploy.sh'), version], env=env, check=True)
