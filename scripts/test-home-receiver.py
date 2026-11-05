import importlib.util
from pathlib import Path
import tarfile
import unittest

path = Path(__file__).resolve().parents[1] / 'deployment/home/receive.py'
spec = importlib.util.spec_from_file_location('receiver', path)
receiver = importlib.util.module_from_spec(spec)
spec.loader.exec_module(receiver)


class ContractTests(unittest.TestCase):
    def valid(self):
        return [tarfile.TarInfo(name) for name in ('image.tar.gz', 'manifest.json', 'compose.yml', 'deploy.sh')]

    def test_valid_regular_files(self):
        receiver.validate_members(self.valid())

    def test_traversal_and_unknown_files(self):
        for name in ('../image.tar.gz', '/etc/passwd', 'runtime.env'):
            members = self.valid()
            members[0].name = name
            with self.assertRaises(SystemExit):
                receiver.validate_members(members)

    def test_links_and_duplicate_names(self):
        members = self.valid()
        members[0].type = tarfile.SYMTYPE
        with self.assertRaises(SystemExit):
            receiver.validate_members(members)
        members = self.valid()
        members[-1].name = members[0].name
        with self.assertRaises(SystemExit):
            receiver.validate_members(members)

    def test_metadata_and_total_size_bounds(self):
        members = self.valid()
        members[1].size = 65_537
        with self.assertRaises(SystemExit):
            receiver.validate_members(members)
        members = self.valid()
        members[0].size = 2_000_000_000
        members[1].size = 1
        with self.assertRaises(SystemExit):
            receiver.validate_members(members)


if __name__ == '__main__':
    unittest.main()
