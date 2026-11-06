#!/usr/bin/env python3
"""Publish once per source SHA; reuse and reverify an existing GHCR release."""
import base64
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, Request, build_opener

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'deployment/home'))
from image_identity import loaded_image_config_digest
from registry_release import REPOSITORY, DIGEST, file_sha256, validate_manifest


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args):
        return None


def registry_digest(version, username, credential):
    basic = base64.b64encode((username + ':' + credential).encode()).decode()
    opener = build_opener(NoRedirect())
    request = Request('https://ghcr.io/token?service=ghcr.io&scope=repository:ject-study/ziper-server:pull,push',
                      headers={'Authorization': 'Basic ' + basic})
    try:
        with opener.open(request, timeout=20) as response:
            value = json.loads(response.read(65537))
        if not isinstance(value, dict):
            raise ValueError()
        bearer = value.get('token', value.get('access_token'))
        if not isinstance(bearer, str) or not bearer:
            raise ValueError()
        request = Request('https://ghcr.io/v2/ject-study/ziper-server/manifests/' + version,
                          method='HEAD', headers={'Authorization': 'Bearer ' + bearer,
                          'Accept': 'application/vnd.oci.image.manifest.v1+json, application/vnd.docker.distribution.manifest.v2+json'})
        try:
            with opener.open(request, timeout=20) as response:
                digest = response.headers.get('Docker-Content-Digest', '')
        except HTTPError as error:
            error.close()
            if error.code == 404:
                return None
            raise
        if not re.fullmatch(DIGEST, digest):
            raise ValueError()
        return digest
    except HTTPError as error:
        error.close()
        raise SystemExit('GHCR lookup HTTP ' + str(error.code) + '; authentication errors are not treated as an absent image') from None
    except (URLError, ValueError, OSError):
        raise SystemExit('GHCR lookup failed; authentication/network errors are not treated as an absent image') from None


def main():
    version = sys.argv[1]
    if not re.fullmatch(r'[a-f0-9]{40}', version):
        raise SystemExit('Invalid source SHA')
    username, token = os.environ['GITHUB_ACTOR'], os.environ['GHCR_TOKEN']
    digest = registry_digest(version, username, token)
    local = 'ziper-server:' + version
    tag = REPOSITORY + ':' + version
    with tempfile.TemporaryDirectory() as temporary:
        env = dict(os.environ, DOCKER_CONFIG=temporary)
        env.pop('GHCR_TOKEN', None)
        env.pop('GITHUB_TOKEN', None)
        login = subprocess.run(['docker', 'login', 'ghcr.io', '--username', username, '--password-stdin'],
                               input=(token + '\n').encode(), env=env, capture_output=True)
        if login.returncode:
            raise SystemExit('GHCR login failed')
        if digest is None:
            subprocess.run(['docker', 'build', '--platform', 'linux/amd64', '--target', 'release',
                            '--label', 'org.opencontainers.image.source=https://github.com/JECT-Study/Ziper-5th-Server',
                            '--label', 'org.opencontainers.image.revision=' + version,
                            '--tag', local, 'server'], env=env, check=True)
            subprocess.run(['python3', 'scripts/verify-release-artifact.py', '--image', local],
                           cwd='server', env=env, check=True)
            subprocess.run(['docker', 'tag', local, tag], env=env, check=True)
            # An uncertain push is not retried; a later run reads the registry first.
            subprocess.run(['docker', 'push', tag], env=env, check=True)
            digest = registry_digest(version, username, token)
            if digest is None:
                raise SystemExit('Published image has no verifiable manifest')
        else:
            subprocess.run(['docker', 'pull', '--platform', 'linux/amd64', REPOSITORY + '@' + digest], env=env, check=True)
            subprocess.run(['docker', 'tag', REPOSITORY + '@' + digest, local], env=env, check=True)
            subprocess.run(['python3', 'scripts/verify-release-artifact.py', '--image', local],
                           cwd='server', env=env, check=True)
        config = loaded_image_config_digest(local, env, Path(temporary))
    jar = Path('server/build/libs/ziper-server.jar')
    jar_digest = file_sha256(jar)
    manifest = validate_manifest({'sourceSha': version, 'registryImage': REPOSITORY,
                                 'imageManifestDigest': digest, 'imageConfigDigest': config,
                                 'jarSha256': jar_digest}, version)
    destination = Path('dist/registry-release.json')
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(manifest, indent=2) + '\n')
    if output := os.environ.get('GITHUB_OUTPUT'):
        with open(output, 'a') as stream:
            stream.write('image=' + REPOSITORY + '@' + digest + '\n')
            stream.write('digest=' + digest + '\n')
    print('Registry release manifest prepared; credentials omitted.')


if __name__ == '__main__':
    main()
