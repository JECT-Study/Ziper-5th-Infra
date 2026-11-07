"""OCI config identity across classic and containerd image stores."""
import base64
import hashlib
import json
import re
import subprocess
import tarfile
import tempfile

MANIFEST_TYPES = {'application/vnd.docker.distribution.manifest.v2+json',
                  'application/vnd.oci.image.manifest.v1+json'}


def registry_image_config_digest(registry, local, image):
    """Bind raw registry bytes to a pulled engine object without Docker save."""
    try:
        reference, digest = image.rsplit('@', 1)
        if not reference or not re.fullmatch(r'sha256:[a-f0-9]{64}', digest):
            raise ValueError()
        raw = base64.b64decode(registry['Raw'], validate=True)
        descriptor = registry['Descriptor']
        manifest = json.loads(raw)
        config = manifest['config']
        config_digest = config['digest']
        platform = descriptor['platform']
        layers = manifest['layers']
        if (len(raw) > 1_048_576 or 'sha256:' + hashlib.sha256(raw).hexdigest() != digest
                or registry['Ref'] != image or descriptor['digest'] != digest
                or descriptor['size'] != len(raw) or manifest['schemaVersion'] != 2
                or manifest['mediaType'] not in MANIFEST_TYPES
                or descriptor['mediaType'] != manifest['mediaType']
                or platform.get('os') != 'linux' or platform.get('architecture') != 'amd64'
                or platform.get('variant', '') not in ('', 'v1')
                or not re.fullmatch(r'sha256:[a-f0-9]{64}', config_digest)
                or config['mediaType'] not in ('application/vnd.docker.container.image.v1+json',
                                                'application/vnd.oci.image.config.v1+json')
                or type(config['size']) is not int or not 0 < config['size'] <= 1_048_576
                or not isinstance(layers, list) or len(layers) > 256
                or any(not re.fullmatch(r'sha256:[a-f0-9]{64}', item['digest']) for item in layers)):
            raise ValueError()
    except (KeyError, TypeError, ValueError, AttributeError):
        raise SystemExit('Registry image identity metadata invalid') from None
    try:
        rootfs = local['RootFS']
        engine_descriptor = local.get('Descriptor')
        descriptor_matches = (isinstance(engine_descriptor, dict)
            and engine_descriptor.get('digest') == digest
            and engine_descriptor.get('mediaType') == manifest['mediaType'])
        # Classic engines identify the config; containerd engines can identify the manifest.
        if (local['Id'] != config_digest and not (local['Id'] == digest and descriptor_matches)
                or local['Os'] != 'linux' or local['Architecture'] != 'amd64'
                or rootfs['Type'] != 'layers' or not isinstance(rootfs['Layers'], list)
                or len(rootfs['Layers']) != len(layers)
                or any(not re.fullmatch(r'sha256:[a-f0-9]{64}', item) for item in rootfs['Layers'])
                or engine_descriptor is not None and not descriptor_matches):
            raise ValueError()
    except (KeyError, TypeError, ValueError, AttributeError):
        raise SystemExit('Pulled image metadata differs from registry') from None
    return config_digest


def pulled_image_config_digest(image, tag, env):
    try:
        registry = subprocess.run(['docker', 'manifest', 'inspect', '--verbose', image],
                                  env=env, capture_output=True, check=True, timeout=60).stdout
        local = subprocess.run(['docker', 'image', 'inspect', tag],
                               env=env, capture_output=True, check=True, timeout=30).stdout
        if len(registry) > 2_097_152 or len(local) > 1_048_576:
            raise ValueError()
        inspected = json.loads(local)
        if not isinstance(inspected, list) or len(inspected) != 1:
            raise ValueError()
        return registry_image_config_digest(json.loads(registry), inspected[0], image)
    except (OSError, subprocess.SubprocessError, TypeError, ValueError):
        raise SystemExit('Registry image identity inspection failed') from None


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
