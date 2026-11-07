#!/usr/bin/env python3
"""Reject mixed/failed receipts using a preserved successful production attempt."""
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / 'docs/evidence/2026-11-07/resumed-paired'
SPEC = importlib.util.spec_from_file_location('paired', ROOT / 'scripts/verify-paired-evidence.py')
paired = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(paired)


class PairedEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name) / 'attempt'
        shutil.copytree(EVIDENCE / 'attempt-1', self.directory)
        self.execution = json.loads((EVIDENCE / 'execution.json').read_text())

    def verify(self):
        return paired.verify(self.directory, self.execution['sourceSha'], self.execution['infraSha'],
                             str(self.execution['runId']), 1)

    def change(self, path, edit):
        target = self.directory / path
        value = json.loads(target.read_text())
        edit(value)
        target.write_text(json.dumps(value))

    def test_preserved_successful_attempt_is_accepted(self):
        result = self.verify()
        self.assertTrue(result['ok'])
        self.assertEqual(result['sourceSha'], self.execution['sourceSha'])
        self.assertEqual(result['attempt'], 1)

    def test_successful_jobs_from_a_different_attempt_are_rejected(self):
        self.change('jobs.json', lambda value: value['jobs'][0].update(run_attempt=2))
        with self.assertRaisesRegex(paired.Refused, 'jobs_failed_or_skipped'):
            self.verify()

    def test_artifact_from_a_different_run_is_rejected(self):
        self.change('artifacts.json', lambda value: value['artifacts'][0]['workflow_run'].update(id=1))
        with self.assertRaisesRegex(paired.Refused, 'artifact_provenance_mismatch'):
            self.verify()

    def test_missing_home_delivery_confirmation_is_rejected(self):
        self.change('receiver-control-proof-attempt-1/receiver-control-proof.json',
                    lambda value: value['checks'].update(registryDeploy=False))
        with self.assertRaisesRegex(paired.Refused, 'home_delivery_not_confirmed'):
            self.verify()

    def test_stale_home_manifest_is_rejected(self):
        self.change('release-manifest-attempt-1/registry-release.json',
                    lambda value: value.update(jarSha256='0' * 64))
        with self.assertRaisesRegex(paired.Refused, 'home_delivery_not_confirmed'):
            self.verify()

    def test_different_registry_reference_is_rejected(self):
        self.change('cloud-run-release-attempt-1/cloud-run-release.json',
                    lambda value: value.update(registryImage='ghcr.io/another/image'))
        with self.assertRaisesRegex(paired.Refused, 'registry_or_revision_mismatch'):
            self.verify()

    def test_stale_public_health_release_is_rejected(self):
        self.change('public-health-attempt-1/public-health.json',
                    lambda value: value['samples'][0][0].update(release='0' * 40))
        with self.assertRaisesRegex(paired.Refused, 'public_identity_or_contract_failure'):
            self.verify()

    def test_discord_post_without_confirmed_read_is_rejected(self):
        self.change('discord-deploy-receipt-attempt-1/discord-deploy-receipt.json',
                    lambda value: value.update(readStatus=404))
        with self.assertRaisesRegex(paired.Refused, 'success_discord_not_confirmed'):
            self.verify()

    def test_different_infra_reference_is_rejected(self):
        self.change('run.json', lambda value: value.update(referenced_workflows=[]))
        with self.assertRaisesRegex(paired.Refused, 'infra_reference_mismatch'):
            self.verify()

    def repeat_cli(self, reuse_message=False):
        directory = Path(self.temporary.name) / 'repeat'
        shutil.copytree(EVIDENCE / 'attempt-2', directory)
        if reuse_message:
            path = directory / 'discord-deploy-receipt-attempt-2/discord-deploy-receipt.json'
            value = json.loads(path.read_text())
            first = json.loads((EVIDENCE / 'first-verified.json').read_text())
            value['delivery']['messageId'] = first['discordMessageId']
            path.write_text(json.dumps(value))
        output = directory / 'verified.json'
        result = subprocess.run([sys.executable, str(ROOT / 'scripts/verify-paired-evidence.py'),
            '--directory', str(directory), '--source', self.execution['sourceSha'],
            '--infra', self.execution['infraSha'], '--run-id', str(self.execution['runId']),
            '--attempt', '2', '--compare', str(EVIDENCE / 'first-verified.json'),
            '--output', str(output)], capture_output=True, text=True, timeout=10)
        return result.returncode, json.loads(output.read_text())

    def test_real_repeated_release_is_accepted_by_cli(self):
        code, result = self.repeat_cli()
        self.assertEqual(code, 0)
        self.assertTrue(result['sameReleaseRepeated'])

    def test_reusing_first_discord_message_does_not_prove_a_second_notification(self):
        code, result = self.repeat_cli(reuse_message=True)
        self.assertEqual(code, 1)
        self.assertEqual(result, {'ok': False, 'reason': 'repeat_evidence_mismatch'})


if __name__ == '__main__':
    unittest.main()
