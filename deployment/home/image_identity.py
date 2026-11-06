"""OCI config identity across classic and containerd image stores."""
import hashlib
import json
import re
import subprocess
import tarfile
import tempfile


def image_config_digest(stream, tag):
    with tarfile.open(fileobj=stream, mode='r:*') as archive:
        def read(name):
            matches = [item for item in archive.getmembers() if item.name == name]
            if len(matches) != 1 or not matches[0].isfile() or not 0 < matches[0].size <= 1_048_576:
                raise SystemExit('Invalid image metadata member')
            return archive.extractfile(matches[0]).read()

        manifest = json.loads(read('manifest.json'))
        if not isinstance(manifest, list) or len(manifest) != 1 or not isinstance(manifest[0], dict):
            raise SystemExit('Expected one image in export')
        entry = manifest[0]
        tags = entry.get('RepoTags', [])
        normalize = lambda value: value.removeprefix('docker.io/library/')
        if not isinstance(tags, list) or normalize(tag) not in [normalize(t) for t in tags if isinstance(t, str)]:
            raise SystemExit('Exported image tag differs')
        path = entry.get('Config', '')
        if not isinstance(path, str):
            raise SystemExit('Invalid image config reference')
        match = re.fullmatch(r'(?:blobs/sha256/([a-f0-9]{64})|([a-f0-9]{64})\.json)', path)
        if match is None:
            raise SystemExit('Invalid image config reference')
        data = read(path)
        digest = hashlib.sha256(data).hexdigest()
        if digest != (match[1] or match[2]):
            raise SystemExit('Image config content differs from its address')
        config = json.loads(data)
        if not isinstance(config, dict) or config.get('os') != 'linux' or config.get('architecture') != 'amd64':
            raise SystemExit('Unexpected image platform')
        rootfs = config.get('rootfs', {})
        if not isinstance(rootfs, dict):
            raise SystemExit('Invalid image root filesystem identity')
        ids = rootfs.get('diff_ids')
        if rootfs.get('type') != 'layers' or not isinstance(ids, list) \
                or any(not isinstance(item, str) or not re.fullmatch(r'sha256:[a-f0-9]{64}', item) for item in ids):
            raise SystemExit('Invalid image root filesystem identity')
        return 'sha256:' + digest


def loaded_image_config_digest(image, env, directory):
    with tempfile.TemporaryFile(dir=directory) as output:
        subprocess.run(['docker', 'save', image], stdout=output, env=env, check=True)
        output.seek(0)
        return image_config_digest(output, image)
