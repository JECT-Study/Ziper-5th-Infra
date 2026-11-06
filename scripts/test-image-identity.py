import hashlib
import io
import json
from pathlib import Path
import sys
import tarfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'deployment/home'))
from image_identity import image_config_digest

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


if __name__ == '__main__':
    unittest.main()
