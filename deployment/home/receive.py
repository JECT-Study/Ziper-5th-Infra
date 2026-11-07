#!/usr/bin/env python3
"""Receive bounded registry metadata, never an archive or an arbitrary shell command."""
from contextlib import contextmanager
import fcntl
import json
import os
from pathlib import Path
import re
import secrets
import subprocess
import sys
import tempfile
from image_identity import pulled_image_config_digest
from registry_release import REPOSITORY, ensure_runtime_window, file_sha256, read_payload


@contextmanager
def deployment_lock(root):
    with (root / 'deploy.lock').open('a+b') as lock:
        try:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise SystemExit('Another Ziper deployment is active') from None
        yield lock.fileno()


def deploy_registry(version, source, root=Path('/opt/ziper')):
    manifest, username, token = read_payload(source, version)
    ensure_runtime_window(root)
    with deployment_lock(root) as lock_fd:
        ensure_runtime_window(root)
        lease = root / 'ops' / 'recovery-lease.json'
        if lease.exists() or lease.is_symlink():
            raise SystemExit('A Ziper recovery lease must be resolved before deployment')
        deploy_registry_locked(version, manifest, username, token, root, lock_fd)


def deploy_registry_locked(version, manifest, username, token, root, lock_fd):
    trusted = root / 'ci'
    release = root / 'releases' / version
    metadata = (json.dumps(manifest, sort_keys=True) + '\n').encode()
    existing = release / 'manifest.json'
    if existing.exists() and existing.read_bytes() != metadata:
        raise SystemExit('Immutable release manifest mismatch')
    contracts = {filename: (trusted / filename).read_bytes() for filename in ('compose.yml', 'deploy.sh')}
    for filename, data in contracts.items():
        target = release / filename
        if target.exists() and target.read_bytes() != data:
            raise SystemExit('Immutable release already exists with different content')
    with tempfile.TemporaryDirectory(dir=root) as temporary:
        stage = Path(temporary)
        os.chmod(stage, 0o700)
        env = dict(os.environ, DOCKER_CONFIG=str(stage / 'docker'))
        env.pop('GITHUB_TOKEN', None)
        env.pop('GHCR_TOKEN', None)
        image = REPOSITORY + '@' + manifest['imageManifestDigest']
        # A unique verification tag never replaces the currently runnable release tag.
        verification_tag = 'ziper-verification:' + version + '-' + secrets.token_hex(8)
        login = subprocess.run(['docker', 'login', 'ghcr.io', '--username', username, '--password-stdin'],
                               input=(token + '\n').encode(), env=env, capture_output=True)
        token = None
        if login.returncode:
            raise SystemExit('Registry authentication failed')
        pull = subprocess.run(['docker', 'pull', '--platform', 'linux/amd64', image],
                              env=env, capture_output=True)
        if pull.returncode:
            raise SystemExit('Registry image pull failed')
        try:
            subprocess.run(['docker', 'tag', image, verification_tag], env=env, check=True, capture_output=True)
            if pulled_image_config_digest(image, verification_tag, env) != manifest['imageConfigDigest']:
                raise SystemExit('Pulled image config differs from manifest')
            container = subprocess.check_output(['docker', 'create', verification_tag], env=env, text=True).strip()
            try:
                extracted = stage / 'app.jar'
                subprocess.run(['docker', 'cp', container + ':/app/app.jar', str(extracted)],
                               env=env, check=True, capture_output=True)
                if file_sha256(extracted) != manifest['jarSha256']:
                    raise SystemExit('Pulled image JAR differs from tested artifact')
            finally:
                subprocess.run(['docker', 'rm', container], env=env, check=True, capture_output=True)
            actual = subprocess.check_output(['docker', 'image', 'inspect', '--format', '{{.Id}}', verification_tag],
                                             env=env, text=True).strip()
            if not re.fullmatch(r'sha256:[a-f0-9]{64}', actual):
                raise SystemExit('Invalid local engine identity')
            # All metadata/image/JAR checks precede this shared tag mutation, under deploy.lock.
            ensure_runtime_window(root)
            local = 'ziper-server:' + version
            subprocess.run(['docker', 'tag', verification_tag, local], env=env, check=True, capture_output=True)
            release.mkdir(parents=True, exist_ok=True, mode=0o700)
            for filename, data in [('manifest.json', metadata), *contracts.items()]:
                target = release / filename
                target.write_bytes(data)
                target.chmod(0o600)
            (release / 'image-id').write_text(actual + '\n')
            print('ZIPER_REGISTRY_MANIFEST_DIGEST=' + manifest['imageManifestDigest'], flush=True)
            print('ZIPER_IMAGE_CONFIG_DIGEST=' + manifest['imageConfigDigest'], flush=True)
        finally:
            subprocess.run(['docker', 'image', 'rm', verification_tag], env=env, capture_output=True)
    # Credentials are gone. Share the same open lock description with trusted deploy.sh.
    env = dict(os.environ, DOCKER_CONFIG=str(root / 'docker-client'), ZIPER_DEPLOY_ROOT=str(root),
               ZIPER_DEPLOY_LOCK_FD=str(lock_fd))
    env.pop('GITHUB_TOKEN', None)
    env.pop('GHCR_TOKEN', None)
    result = subprocess.run(['bash', str(trusted / 'deploy.sh'), version], env=env, pass_fds=(lock_fd,))
    if result.returncode:
        raise SystemExit(result.returncode)


def main():
    command = ' '.join(sys.argv[1:])
    if command == 'check':
        print('ZIPER_CI_RECEIVER_READY', flush=True)
        return
    registry_match = re.fullmatch(r'deploy-registry ([0-9a-f]{40})', command)
    if registry_match is not None:
        os.umask(0o077)
        deploy_registry(registry_match[1], sys.stdin.buffer)
        return
    if re.fullmatch(r'deploy [0-9a-f]{40}', command):
        raise SystemExit('Legacy archive deployment is disabled; use deploy-registry')
    raise SystemExit('Unsupported receiver command')


if __name__ == '__main__':
    main()
