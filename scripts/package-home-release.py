#!/usr/bin/env python3
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tarfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'deployment/home'))
from image_identity import image_config_digest

version = sys.argv[1]
if not re.fullmatch('[a-f0-9]{40}', version):
    raise SystemExit('Invalid source SHA')
release = Path('dist/home-release')
release.mkdir(parents=True, exist_ok=True)
image = 'ziper-server:' + version
subprocess.run(['docker', 'build', '--platform', 'linux/amd64', '--target', 'release', '--tag', image, 'server'], check=True)
subprocess.run(['python3', 'scripts/verify-release-artifact.py', '--image', image], cwd='server', check=True)
with (release / 'image.tar.gz').open('wb') as output:
    save = subprocess.Popen(['docker', 'save', image], stdout=subprocess.PIPE)
    try:
        subprocess.run(['gzip'], stdin=save.stdout, stdout=output, check=True)
    finally:
        if save.stdout: save.stdout.close()
    if save.wait() != 0: raise SystemExit('Image export failed')
with (release / 'image.tar.gz').open('rb') as archive:
    identity = image_config_digest(archive, image)
jar = Path('server/build/libs/ziper-server.jar')
manifest = {'sourceSha': version, 'imageConfigDigest': identity, 'jarSha256': hashlib.file_digest(jar.open('rb'), 'sha256').hexdigest(), 'archiveSha256': hashlib.file_digest((release / 'image.tar.gz').open('rb'), 'sha256').hexdigest()}
(release / 'manifest.json').write_text(json.dumps(manifest))
for filename in ('compose.yml', 'deploy.sh'):
    shutil.copyfile(Path('deployment/home') / filename, release / filename)
with tarfile.open('dist/home-release.tgz', 'w:gz') as bundle:
    for filename in ('image.tar.gz', 'manifest.json', 'compose.yml', 'deploy.sh'):
        bundle.add(release / filename, arcname=filename)
