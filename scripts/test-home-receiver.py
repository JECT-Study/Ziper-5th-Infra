import importlib.util
import io
from pathlib import Path
import tarfile
import unittest

path = Path(__file__).resolve().parents[1] / 'deployment/home/receive.py'
spec = importlib.util.spec_from_file_location('receiver', path)
receiver = importlib.util.module_from_spec(spec)
spec.loader.exec_module(receiver)


class ContractTests(unittest.TestCase):
    def test_binary_stream_over_ssh_window_preserves_every_byte(self):
        payload = bytes(range(256)) * 4096
        output = io.BytesIO()
        size = receiver.copy_release(io.BytesIO(payload), output)
        self.assertEqual(len(payload), size)
        self.assertEqual(payload, output.getvalue())

    def test_stream_rejects_excess_size_before_writing_excess_chunk(self):
        output = io.BytesIO()
        with self.assertRaises(SystemExit):
            receiver.copy_release(io.BytesIO(b'bad'), output, limit=2)
        self.assertEqual(b'', output.getvalue())

    def test_general_commands_rejected_before_receiving_payload(self):
        from unittest.mock import patch
        for command in ('whoami', 'deploy invalid', 'deploy ' + 'a' * 40 + '; whoami'):
            with patch.object(receiver.sys, 'argv', ['receive.py', command]):
                with self.assertRaises(SystemExit):
                    receiver.main()

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
