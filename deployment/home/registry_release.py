"""Fixed GHCR release contract shared by publisher and restricted receiver."""
import hashlib
import json
import re

REPOSITORY = 'ghcr.io/ject-study/ziper-server'
DIGEST = r'sha256:[a-f0-9]{64}'


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


def read_payload(source, version):
    raw = source.read(8193)
    if len(raw) > 8192:
        raise SystemExit('Registry control payload exceeds size limit')
    try:
        payload = json.loads(raw)
    except (ValueError, UnicodeError):
        raise SystemExit('Invalid registry control payload') from None
    if not isinstance(payload, dict) or set(payload) != {'manifest', 'username', 'token'}:
        raise SystemExit('Invalid registry control fields')
    username, token = payload['username'], payload['token']
    if not isinstance(username, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9\[\]-]{0,63}', username):
        raise SystemExit('Invalid registry actor')
    if not isinstance(token, str) or not 1 <= len(token) <= 4096 or any(c.isspace() for c in token):
        raise SystemExit('Invalid registry credential')
    return validate_manifest(payload['manifest'], version), username, token
