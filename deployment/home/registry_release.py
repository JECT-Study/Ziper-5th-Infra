"""Fixed GHCR release contract shared by publisher and restricted receiver."""
import base64
import binascii
import hashlib
import json
import re
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

REPOSITORY = 'ghcr.io/ject-study/ziper-server'
DIGEST = r'sha256:[a-f0-9]{64}'
PAYLOAD_LIMIT = 65536
CONFIG_FILE_LIMIT = 16384
# Secret Manager secret -> file name inside the home configuration bundle.
CONFIG_SECRETS = {'ziper-runtime-properties': 'application.properties',
                  'ziper-home-migration-properties': 'migration.properties',
                  'ziper-db-ca': 'db-ca.pem'}


def ensure_runtime_window(root, now=None):
    try:
        policy = json.loads((root / 'ci' / 'production.json').read_text())['homeSchedule']
        start, end, safety = policy['start'], policy['end'], policy['deploySafetyMinutes']
        if policy['timeZone'] != 'Asia/Seoul' or not isinstance(safety, int) or isinstance(safety, bool) or not 0 <= safety <= 120:
            raise ValueError()
        if any(not isinstance(value, str) or not re.fullmatch(r'(?:[01][0-9]|2[0-3]):[0-5][0-9]', value) for value in (start, end)) or start == end:
            raise ValueError()
        minute = lambda value: int(value[:2]) * 60 + int(value[3:])
        beginning, ending = (minute(start) - safety) % 1440, minute(end)
        current = (now or datetime.now(timezone.utc)).astimezone(ZoneInfo('Asia/Seoul'))
        at = current.hour * 60 + current.minute
        deferred = beginning <= at < ending if beginning < ending else at >= beginning or at < ending
    except (KeyError, TypeError, ValueError, OSError):
        raise SystemExit('Trusted deployment schedule is missing or invalid') from None
    if deferred:
        print('ZIPER_DEPLOY_DEFERRED', flush=True)
        raise SystemExit(75)


def file_sha256(path):
    digest = hashlib.sha256()
    with path.open('rb') as content:
        for chunk in iter(lambda: content.read(65536), b''):
            digest.update(chunk)
    return digest.hexdigest()


def validate_manifest(value, version):
    fields = {'sourceSha', 'registryImage', 'imageManifestDigest', 'imageConfigDigest', 'jarSha256'}
    if not isinstance(value, dict) or set(value) != fields:
        raise SystemExit('Invalid registry release fields')
    if not re.fullmatch(r'[a-f0-9]{40}', version) or value['sourceSha'] != version:
        raise SystemExit('Release source mismatch')
    if value['registryImage'] != REPOSITORY:
        raise SystemExit('Unapproved image repository')
    for name in ('imageManifestDigest', 'imageConfigDigest'):
        if not isinstance(value[name], str) or not re.fullmatch(DIGEST, value[name]):
            raise SystemExit('Invalid registry image digest')
    if not isinstance(value['jarSha256'], str) or not re.fullmatch(r'[a-f0-9]{64}', value['jarSha256']):
        raise SystemExit('Invalid JAR identity')
    return value


def secret_versions(policy):
    """Pinned Secret Manager versions; both origins read exactly these, never latest."""
    versions = policy.get('secretVersions') if isinstance(policy, dict) else None
    if (not isinstance(versions, dict) or set(versions) != set(CONFIG_SECRETS)
            or any(not isinstance(value, str) or not re.fullmatch(r'[1-9][0-9]{0,5}', value)
                   for value in versions.values())):
        raise SystemExit('Pinned secret versions are missing or invalid')
    return dict(versions)


def config_identity(versions, files):
    """Bundle ID from pinned versions and file hashes; independent of file order."""
    digests = {name: hashlib.sha256(data).hexdigest() for name, data in sorted(files.items())}
    canonical = json.dumps({'versions': versions, 'files': digests}, sort_keys=True, separators=(',', ':'))
    return hashlib.sha256(canonical.encode()).hexdigest()


def validate_config(value):
    if not isinstance(value, dict) or set(value) != {'versions', 'files'}:
        raise SystemExit('Invalid configuration bundle fields')
    versions = secret_versions({'secretVersions': value['versions']})
    encoded = value['files']
    if not isinstance(encoded, dict) or set(encoded) != set(CONFIG_SECRETS.values()):
        raise SystemExit('Invalid configuration bundle files')
    files = {}
    for name, text in encoded.items():
        try:
            data = base64.b64decode(text, validate=True) if isinstance(text, str) else None
        except (binascii.Error, ValueError):
            data = None
        if not data or len(data) > CONFIG_FILE_LIMIT or b'\0' in data:
            raise SystemExit('Invalid configuration bundle content')
        files[name] = data
    return config_identity(versions, files), versions, files


def read_payload(source, version):
    raw = source.read(PAYLOAD_LIMIT + 1)
    if len(raw) > PAYLOAD_LIMIT:
        raise SystemExit('Registry control payload exceeds size limit')
    try:
        payload = json.loads(raw)
    except (ValueError, UnicodeError):
        raise SystemExit('Invalid registry control payload') from None
    if not isinstance(payload, dict) or set(payload) != {'manifest', 'username', 'token', 'config'}:
        raise SystemExit('Invalid registry control fields')
    username, token = payload['username'], payload['token']
    if not isinstance(username, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9\[\]-]{0,63}', username):
        raise SystemExit('Invalid registry actor')
    if not isinstance(token, str) or not 1 <= len(token) <= 4096 or any(c.isspace() for c in token):
        raise SystemExit('Invalid registry credential')
    return validate_manifest(payload['manifest'], version), username, token, validate_config(payload['config'])
