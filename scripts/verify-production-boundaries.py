#!/usr/bin/env python3
"""Read-only live probes; credentials stay in memory and receipts contain no tokens."""
import argparse
import base64
from datetime import datetime, timezone
import hashlib
import hmac
import json
from pathlib import Path
import re
import shlex
import time
import urllib.error
import urllib.parse
import urllib.request

PUBLIC = 'https://api-ziper.joonamin.dev'
PRIVATE_HEADERS = ('CF-Access-Client-Id', 'CF-Access-Client-Secret',
                   'CF-Access-Jwt-Assertion', 'X-Serverless-Authorization')


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args):
        return None


def request(url, headers=None, *, method='GET', ops=False):
    values = {'Accept': 'application/json', 'User-Agent': 'ziper-production-e2e', 'Cache-Control': 'no-cache'}
    values.update(headers or {})
    try:
        try:
            response = urllib.request.build_opener(NoRedirect()).open(
                urllib.request.Request(url, headers=values, method=method), timeout=10)
        except urllib.error.HTTPError as error:
            response = error
        with response:
            receipt = {'status': response.status,
                       'privateCredentialHeaderPresent': any(response.headers.get(k) for k in PRIVATE_HEADERS)}
            if response.status == 200:
                limit = 65536 if ops else 4096
                body = response.read(limit + 1)
                if len(body) > limit:
                    raise ValueError('response_size')
                value = json.loads(body)
                if ops:
                    mode, reason = value['state']['mode']['kind'], value['reason']
                    if (not isinstance(mode, str) or mode not in ('CLOSED', 'OPEN', 'HALF_OPEN')
                            or not isinstance(reason, str) or reason not in ('home', 'circuit_backup', 'scheduled_backup')):
                        raise ValueError('ops_contract')
                    receipt.update(mode=mode, reason=reason)
                else:
                    release = response.headers.get('X-Ziper-Release', '')
                    upstream = response.headers.get('X-Ziper-Origin')
                    receipt.update(upOnly=value == {'status': 'UP'},
                                   release=release if re.fullmatch('[a-f0-9]{40}', release) else None,
                                   origin=upstream if upstream in ('home', 'cloudrun') else None,
                                   noStore='no-store' in {part.strip() for part in response.headers.get('Cache-Control', '').lower().split(',')},
                                   sessionCookie=response.headers.get('Set-Cookie') is not None,
                                   cached=response.headers.get('CF-Cache-Status', '').upper() in ('HIT', 'STALE', 'UPDATING'))
            return receipt
    except (urllib.error.URLError, TimeoutError, OSError, ValueError, KeyError, TypeError):
        return {'status': None, 'error': 'request_failed_or_invalid_contract'}


def jwt(private):
    config = {}
    for line in (private / 'runtime.env').read_text().splitlines():
        if line and not line.startswith('#') and '=' in line:
            key, value = line.split('=', 1)
            parsed = shlex.split(value)
            config[key] = parsed[0] if parsed else ''
    encode = lambda value: base64.urlsafe_b64encode(json.dumps(value, separators=(',', ':')).encode()).rstrip(b'=')
    now = int(time.time())
    unsigned = encode({'alg': 'HS256', 'typ': 'JWT'}) + b'.' + encode({
        'iss': config.get('JWT_ISSUER', 'ziper-server'), 'aud': config.get('JWT_AUDIENCE', 'ziper-api'),
        'sub': 'ziper-production-e2e', 'iat': now, 'exp': now + 120})
    signature = hmac.new(base64.b64decode(config['JWT_SECRET_BASE64'], validate=True), unsigned, hashlib.sha256).digest()
    return (unsigned + b'.' + base64.urlsafe_b64encode(signature).rstrip(b'=')).decode()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--release', required=True)
    parser.add_argument('--expected-origin', choices=('home', 'cloudrun'), required=True)
    parser.add_argument('--backup-origin', required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    parsed = urllib.parse.urlsplit(args.backup_origin)
    if (not re.fullmatch('[a-f0-9]{40}', args.release) or parsed.scheme != 'https'
            or not parsed.hostname or not parsed.hostname.startswith('ziper-backup-')
            or not parsed.hostname.endswith('.run.app') or parsed.port or parsed.username or parsed.password
            or parsed.path not in ('', '/') or parsed.query or parsed.fragment):
        parser.error('Supply verified production release and canonical private backup origin')
    private = Path.home() / '.config/ziper/deployment'
    token_file = private / 'ops-read-token'
    if token_file.is_symlink() or token_file.stat().st_mode & 0o077:
        parser.error('Use a private token file')
    token = token_file.read_text().strip()
    if len(token) < 32:
        parser.error('Missing private ops token')
    receipts = {
        'normal': request(PUBLIC + '/readyz'),
        'validUserJwt': request(PUBLIC + '/readyz', {'Authorization': 'Bearer ' + jwt(private)}),
        'invalidUserJwt': request(PUBLIC + '/readyz', {'Authorization': 'Bearer invalid-e2e-token'}),
        'spoofedUpstreamHeadersProbe': request(PUBLIC + '/readyz', {**{k: 'spoofed-e2e-value' for k in PRIVATE_HEADERS},
            'X-Forwarded-Host': 'spoofed.invalid', 'X-Forwarded-Proto': 'http'}),
        'opsUnauthenticated': request(PUBLIC + '/_ops/circuit', ops=True),
        'opsWrongToken': request(PUBLIC + '/_ops/circuit', {'Authorization': 'Bearer wrong-e2e-token'}, ops=True),
        'opsAuthenticated': request(PUBLIC + '/_ops/circuit', {'Authorization': 'Bearer ' + token}, ops=True),
        'opsPostRejected': request(PUBLIC + '/_ops/circuit', {'Authorization': 'Bearer ' + token}, method='POST', ops=True),
        'backupAnonymousDenied': request(args.backup_origin.rstrip('/') + '/readyz'),
        'protectedHomeAnonymousDenied': request('https://origin-ziper.joonamin.dev/readyz')}
    def healthy(item):
        return (item.get('status') == 200 and item.get('upOnly') is True and item.get('release') == args.release
                and item.get('origin') == args.expected_origin and item.get('noStore') is True
                and item.get('sessionCookie') is False and item.get('cached') is False)
    expected_status = {'invalidUserJwt': 401, 'opsUnauthenticated': 404, 'opsWrongToken': 404,
                       'opsAuthenticated': 200, 'opsPostRejected': 404, 'backupAnonymousDenied': 403,
                       'protectedHomeAnonymousDenied': 403}
    ok = (all(healthy(receipts[k]) for k in ('normal', 'validUserJwt', 'spoofedUpstreamHeadersProbe'))
          and all(receipts[k].get('status') == status for k, status in expected_status.items())
          and not any(item.get('privateCredentialHeaderPresent') for item in receipts.values()))
    report = {'checkedAt': datetime.now(timezone.utc).isoformat(), 'release': args.release,
              'expectedOrigin': args.expected_origin, 'ok': ok, 'checks': receipts,
              'scope': 'Read-only health/auth and no reflected credential headers; backend header receipt is not observed. No business writes, member account or load benchmark'}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report))
    return 0 if ok else 1


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (OSError, ValueError, KeyError, TypeError):
        print(json.dumps({'ok': False, 'error': 'private_configuration_unavailable_or_invalid'}))
        raise SystemExit(1)
