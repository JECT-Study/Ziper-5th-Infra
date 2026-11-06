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

def validate_members(members):
    expected = {'image.tar.gz', 'manifest.json', 'compose.yml', 'deploy.sh'}
    if len(members) != len(expected) or {m.name for m in members} != expected:
        raise SystemExit('Unexpected release files')
    if sum(m.size for m in members) > 2_000_000_000:
        raise SystemExit('Release exceeds size limit')
    for member in members:
        limit = 2_000_000_000 if member.name == 'image.tar.gz' else 65_536
        if not member.isfile() or member.size < 0 or member.size > limit:
            raise SystemExit('Invalid release file type or size')


def copy_release(source, destination, limit=2_000_000_000):
    total = 0
    while chunk := source.read(65_536):
        total += len(chunk)
        if total > limit:
            raise SystemExit('Release exceeds size limit')
        destination.write(chunk)
    return total


def deploy(version, archive):
    if not re.fullmatch('[0-9a-f]{40}', version):
        raise SystemExit('Invalid release identifier')
    root = Path('/opt/ziper')
    with tempfile.TemporaryDirectory(dir=root) as temporary:
        stage = Path(temporary)
        with tarfile.open(archive, 'r:gz') as bundle:
            members = bundle.getmembers()
            validate_members(members)
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
        container = subprocess.check_output(['docker', 'create', 'ziper-server:' + version], env=env, text=True).strip()
        try:
            extracted = stage / 'app.jar'
            subprocess.run(['docker', 'cp', container + ':/app/app.jar', str(extracted)], env=env, check=True, stdout=subprocess.DEVNULL)
            if hashlib.file_digest(extracted.open('rb'), 'sha256').hexdigest() != manifest.get('jarSha256'):
                raise SystemExit('Remote image JAR differs from tested artifact')
        finally:
            subprocess.run(['docker', 'rm', container], env=env, check=True, stdout=subprocess.DEVNULL)
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


def main():
    command = ' '.join(sys.argv[1:])
    if command == 'check':
        print('ZIPER_CI_RECEIVER_READY', flush=True)
        return
    match = re.fullmatch(r'deploy ([0-9a-f]{40})', command)
    if match is None:
        raise SystemExit('Unsupported receiver command')
    os.umask(0o077)
    version = match[1]
    incoming = Path('/opt/ziper/incoming')
    incoming.mkdir(mode=0o700, exist_ok=True)
    archive = incoming / (version + '.tgz')
    created = False
    try:
        with archive.open('xb') as destination:
            created = True
            size = copy_release(sys.stdin.buffer, destination)
        print(f'ZIPER_RELEASE_BYTES={size}', flush=True)
        with archive.open('rb') as content:
            print('ZIPER_RELEASE_SHA256=' + hashlib.file_digest(content, 'sha256').hexdigest(), flush=True)
        deploy(version, archive)
    finally:
        if created:
            archive.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
