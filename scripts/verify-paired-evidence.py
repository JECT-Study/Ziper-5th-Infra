#!/usr/bin/env python3
"""Check downloaded Actions artifacts; independent provider readback is separate."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import sys


class Refused(ValueError):
    pass


def require(condition, reason):
    if not condition:
        raise Refused(reason)


def load(root, name):
    path = root / name
    require(path.is_file() and not path.is_symlink() and path.stat().st_size <= 1_048_576,
            'missing_or_oversized_evidence')
    return json.loads(path.read_text())


def verify(root, source, infra, run_id, attempt):
    run = load(root, 'run.json')
    require(str(run['id']) == run_id and run['run_attempt'] == attempt
            and run['event'] == 'workflow_dispatch' and run['head_branch'] == 'main'
            and run['head_sha'] == source and run['conclusion'] == 'success'
            and run['status'] == 'completed'
            and run['path'] == '.github/workflows/deploy-production.yml', 'workflow_not_successful_target')
    expected = 'JECT-Study/Ziper-5th-Infra/.github/workflows/deploy-home.yml@' + infra
    require(any(item.get('path') == expected and item.get('sha') == infra
                for item in run.get('referenced_workflows', [])), 'infra_reference_mismatch')
    jobs = load(root, 'jobs.json')
    names = {'home / publish', 'home / backup', 'home / deploy', 'home / notify'}
    require(jobs['total_count'] == 4 and len(jobs['jobs']) == 4
            and {job['name'] for job in jobs['jobs']} == names
            and all(job['conclusion'] == 'success' and job['status'] == 'completed'
                    and str(job['run_id']) == run_id and job['run_attempt'] == attempt
                    and job['head_sha'] == source and job['head_branch'] == 'main'
                    for job in jobs['jobs']), 'jobs_failed_or_skipped')

    artifacts = load(root, 'artifacts.json')['artifacts']
    required = ('registry-release', 'cloud-run-release', 'cloud-run-health', 'home-origin-health',
                'receiver-control-proof', 'public-health', 'release-manifest', 'discord-deploy-receipt')
    artifact_ids = {}
    for name in required:
        matches = [item for item in artifacts if item['name'] == f'{name}-attempt-{attempt}']
        require(len(matches) == 1, 'missing_or_duplicate_artifact')
        item = matches[0]
        require(item['expired'] is False and str(item['workflow_run']['id']) == run_id
                and item['workflow_run']['head_sha'] == source
                and item['workflow_run']['head_branch'] == 'main', 'artifact_provenance_mismatch')
        artifact_ids[name] = item['id']

    def artifact(name, filename):
        return load(root, f'{name}-attempt-{attempt}/{filename}.json')

    registry = artifact('registry-release', 'registry-release')
    cloud = artifact('cloud-run-release', 'cloud-run-release')
    home = artifact('release-manifest', 'registry-release')
    receiver = artifact('receiver-control-proof', 'receiver-control-proof')
    require(home == registry and receiver['result'] == 'passed'
            and all(receiver['checks'].get(key) is True for key in
                    ('check', 'generalCommandDenied', 'registryDeploy'))
            and receiver['checks'].get('runtimeDeferred', False) is False
            and not receiver.get('receiverFailure') and receiver.get('receiverExitCode', 0) == 0
            and 0 < receiver['payloadBytes'] <= 8192, 'home_delivery_not_confirmed')
    protected = artifact('home-origin-health', 'home-origin-health')
    require(protected['ok'] is True and protected['status'] == 200
            and protected['cloudflareChallenge'] is False
            and protected['credentialsMatchExpected'] is True, 'protected_origin_not_healthy')
    require(registry['sourceSha'] == cloud['sourceSha'] == source, 'source_identity_mismatch')
    for field, pattern in [('imageConfigDigest', r'sha256:[a-f0-9]{64}'), ('jarSha256', r'[a-f0-9]{64}')]:
        require(registry[field] == cloud[field] and re.fullmatch(pattern, registry[field]) is not None,
                'image_content_mismatch')
    require(registry['registryImage'] == 'ghcr.io/ject-study/ziper-server'
            and cloud['registryImage'] == registry['registryImage']
            and cloud['imageManifestDigest'] == registry['imageManifestDigest']
            and re.fullmatch(r'sha256:[a-f0-9]{64}', registry['imageManifestDigest']) is not None
            and re.fullmatch(r'sha256:[a-f0-9]{64}', cloud['artifactManifestDigest']) is not None
            and cloud['artifactImage'] == 'asia-southeast1-docker.pkg.dev/ziper-production/ziper-releases/ziper-server'
            and cloud['image'] == cloud['artifactImage'] + '@' + cloud['artifactManifestDigest']
            and cloud['imageDigest'] == cloud['artifactManifestDigest']
            and cloud['revision'] == 'ziper-backup-s' + source and cloud['service'] == 'ziper-backup',
            'registry_or_revision_mismatch')
    public = artifact('public-health', 'public-health')
    private = artifact('cloud-run-health', 'cloud-run-health')
    require(public['ok'] is True and public['termination'] == 'healthy'
            and public['expectedRelease'] == source and public['expectedOrigin'] == 'home'
            and public['consecutiveSuccesses'] == 3 and private['ok'] is True
            and private['sourceSha'] == source, 'health_not_target_success')
    for report, is_public in [(public, True), (private, False)]:
        require(len(report['samples']) == 3, 'health_pair_count')
        for pair in report['samples']:
            require(len(pair) == 2 and [sample['path'] for sample in pair] == ['/livez', '/readyz'],
                    'health_paths_mismatch')
            for sample in pair:
                require(sample['status'] == 200, 'health_http_failure')
                if is_public:
                    require(sample['release'] == source and sample['upstreamOrigin'] == 'home'
                            and sample['noStore'] is True and sample['statusOnly'] is True,
                            'public_identity_or_contract_failure')
                else:
                    require(sample['ok'] is True, 'private_health_failure')
    discord = artifact('discord-deploy-receipt', 'discord-deploy-receipt')
    delivery = discord['delivery']
    require(discord['SOURCE_SHA'] == source and discord['GITHUB_RUN_ID'] == run_id
            and discord['GITHUB_RUN_ATTEMPT'] == str(attempt)
            and discord['DEPLOY_RESULT'] == 'success' and discord['DEPLOY_SCOPE'] == 'paired'
            and discord['phase'] == 'complete' and delivery['state'] == 'confirmed'
            and delivery['channelId'] == '1566809692779323402'
            and re.fullmatch(r'[1-9][0-9]{0,24}', delivery['messageId']) is not None
            and discord['readStatus'] == 200 and 1 <= discord['readAttempts'] <= 3,
            'success_discord_not_confirmed')
    return {'checkedAt': datetime.now(timezone.utc).isoformat(), 'ok': True,
            'runId': run_id, 'attempt': attempt, 'sourceSha': source, 'infraSha': infra,
            'imageConfigDigest': registry['imageConfigDigest'], 'jarSha256': registry['jarSha256'],
            'ghcrManifestDigest': registry['imageManifestDigest'],
            'artifactManifestDigest': cloud['artifactManifestDigest'], 'revision': cloud['revision'],
            'discordMessageId': delivery['messageId'], 'discordChannelId': delivery['channelId'],
            'artifactIds': artifact_ids,
            'scope': 'Successful Actions attempt and artifact consistency; provider readback and failover are separate.'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--directory', type=Path, required=True)
    parser.add_argument('--source', required=True)
    parser.add_argument('--infra', required=True)
    parser.add_argument('--run-id', required=True)
    parser.add_argument('--attempt', type=int, choices=range(1, 101), required=True)
    parser.add_argument('--compare', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    try:
        require(re.fullmatch(r'[a-f0-9]{40}', args.source) and re.fullmatch(r'[a-f0-9]{40}', args.infra)
                and re.fullmatch(r'[1-9][0-9]*', args.run_id), 'invalid_identifiers')
        report = verify(args.directory, args.source, args.infra, args.run_id, args.attempt)
        if args.compare:
            first = json.loads(args.compare.read_text())
            require(first['ok'] is True and first['attempt'] == 1 and args.attempt == 2
                    and all(first[key] == report[key] for key in
                            ('sourceSha', 'infraSha', 'runId', 'imageConfigDigest', 'jarSha256',
                             'ghcrManifestDigest', 'artifactManifestDigest', 'revision'))
                    and first['discordMessageId'] != report['discordMessageId'], 'repeat_evidence_mismatch')
            report['sameReleaseRepeated'] = True
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as error:
        report = {'ok': False, 'reason': str(error) if isinstance(error, Refused) else 'invalid_evidence'}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report))
    return 0 if report['ok'] else 1


if __name__ == '__main__':
    sys.exit(main())
