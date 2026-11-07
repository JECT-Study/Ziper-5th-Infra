import base64
import copy
import hashlib
import io
import json
from pathlib import Path
import sys
import tarfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'deployment/home'))
from image_identity import image_config_digest, registry_image_config_digest

TAG = 'ziper-server:' + 'a' * 40
CONFIG = json.dumps({'os': 'linux', 'architecture': 'amd64',
                     'rootfs': {'type': 'layers', 'diff_ids': ['sha256:' + 'b' * 64]}}).encode()


def fixture(layout, data=CONFIG, manifest=None, name=None, duplicate=False):
    digest = hashlib.sha256(data).hexdigest()
    path = name or (digest + '.json' if layout == 'classic' else 'blobs/sha256/' + digest)
    result = io.BytesIO()
    with tarfile.open(fileobj=result, mode='w') as archive:
        entries = manifest if manifest is not None else [{'Config': path, 'RepoTags': [TAG]}]
        for member_name, content in [('manifest.json', json.dumps(entries).encode()), (path, data)]:
            member = tarfile.TarInfo(member_name)
            member.size = len(content)
            archive.addfile(member, io.BytesIO(content))
            if duplicate and member_name == path:
                archive.addfile(member, io.BytesIO(content))
    result.seek(0)
    return result


class ImageIdentityTests(unittest.TestCase):
    def test_classic_and_oci_layout_have_the_same_config_identity(self):
        expected = 'sha256:' + hashlib.sha256(CONFIG).hexdigest()
        self.assertEqual(expected, image_config_digest(fixture('classic'), TAG))
        self.assertEqual(expected, image_config_digest(fixture('oci'), TAG))

    def test_configuration_change_changes_the_identity(self):
        changed = json.loads(CONFIG)
        changed['config'] = {'User': '10001'}
        self.assertNotEqual(image_config_digest(fixture('oci'), TAG),
                            image_config_digest(fixture('oci', json.dumps(changed).encode()), TAG))

    def test_wrong_content_address_is_rejected(self):
        with self.assertRaises(SystemExit):
            image_config_digest(fixture('oci', name='blobs/sha256/' + '0' * 64), TAG)

    def test_path_traversal_duplicates_and_wrong_tag_are_rejected(self):
        for source in (fixture('oci', name='../config.json'), fixture('oci', duplicate=True),
                       fixture('oci', manifest=[{'Config': 'x', 'RepoTags': ['another:tag']}])):
            with self.assertRaises(SystemExit):
                image_config_digest(source, TAG)

    def test_multiple_images_and_wrong_platform_are_rejected(self):
        with self.assertRaises(SystemExit):
            image_config_digest(fixture('oci', manifest=[{}, {}]), TAG)
        changed = json.loads(CONFIG)
        changed['architecture'] = 'arm64'
        with self.assertRaises(SystemExit):
            image_config_digest(fixture('oci', json.dumps(changed).encode()), TAG)


class RegistryIdentityTests(unittest.TestCase):
    def data(self, media='application/vnd.docker.distribution.manifest.v2+json'):
        config = 'sha256:' + hashlib.sha256(CONFIG).hexdigest()
        body = {'schemaVersion': 2, 'mediaType': media,
                'config': {'mediaType': 'application/vnd.oci.image.config.v1+json', 'size': len(CONFIG), 'digest': config},
                'layers': [{'digest': 'sha256:' + 'c' * 64}]}
        raw = json.dumps(body).encode()
        digest = 'sha256:' + hashlib.sha256(raw).hexdigest()
        image = 'ghcr.io/ject-study/ziper-server@' + digest
        descriptor = {'digest': digest, 'size': len(raw), 'mediaType': media,
                      'platform': {'os': 'linux', 'architecture': 'amd64'}}
        registry = {'Ref': image, 'Descriptor': descriptor, 'Raw': base64.b64encode(raw).decode()}
        local = {'Id': digest, 'Descriptor': copy.deepcopy(descriptor), 'Os': 'linux', 'Architecture': 'amd64',
                 'RootFS': {'Type': 'layers', 'Layers': ['sha256:' + 'b' * 64]}}
        return registry, local, image, config

    def test_raw_manifest_binds_config_to_classic_and_containerd_engines(self):
        for media in ('application/vnd.docker.distribution.manifest.v2+json', 'application/vnd.oci.image.manifest.v1+json'):
            registry, local, image, expected = self.data(media)
            self.assertEqual(registry_image_config_digest(registry, local, image), expected)
            local['Id'] = expected
            local.pop('Descriptor')
            self.assertEqual(registry_image_config_digest(registry, local, image), expected)

    def test_altered_raw_reference_descriptor_and_platform_are_rejected(self):
        for mutation in ('raw', 'reference', 'descriptor', 'platform', 'size'):
            registry, local, image, _ = self.data()
            if mutation == 'raw': registry['Raw'] = base64.b64encode(b'{}').decode()
            if mutation == 'reference': registry['Ref'] = 'another@' + image.split('@')[1]
            if mutation == 'descriptor': registry['Descriptor']['digest'] = 'sha256:' + '0' * 64
            if mutation == 'platform': registry['Descriptor']['platform']['architecture'] = 'arm64'
            if mutation == 'size': registry['Descriptor']['size'] += 1
            with self.subTest(mutation=mutation), self.assertRaises(SystemExit):
                registry_image_config_digest(registry, local, image)

    def test_wrong_engine_object_platform_layer_count_and_descriptor_are_rejected(self):
        for mutation in ('id', 'architecture', 'layers', 'descriptor'):
            registry, local, image, _ = self.data()
            if mutation == 'id': local['Id'] = 'sha256:' + '0' * 64
            if mutation == 'architecture': local['Architecture'] = 'arm64'
            if mutation == 'layers': local['RootFS']['Layers'] = []
            if mutation == 'descriptor': local['Descriptor']['digest'] = 'sha256:' + '0' * 64
            with self.subTest(mutation=mutation), self.assertRaises(SystemExit):
                registry_image_config_digest(registry, local, image)

    def test_invalid_base64_and_manifest_lists_are_rejected(self):
        registry, local, image, _ = self.data()
        registry['Raw'] = 'private-marker-invalid-base64'
        with self.assertRaises(SystemExit) as error:
            registry_image_config_digest(registry, local, image)
        self.assertNotIn('private-marker', str(error.exception))
        registry, local, image, _ = self.data('application/vnd.oci.image.index.v1+json')
        with self.assertRaises(SystemExit):
            registry_image_config_digest(registry, local, image)


if __name__ == '__main__':
    unittest.main()
