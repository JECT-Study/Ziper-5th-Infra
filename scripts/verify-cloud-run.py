#!/usr/bin/env python3
"""Verify private Cloud Run probes without logging the ID token or body."""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener


class Refused(ValueError):
    pass


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, response, code, message, headers, new_url):
        response.close()
        raise Refused('redirect_rejected')


def origin(value):
    parsed = urlsplit(value)
    if (parsed.scheme != 'https' or not parsed.hostname or not parsed.hostname.startswith('ziper-backup-')
            or not parsed.hostname.endswith('.run.app') or parsed.port or parsed.username or parsed.password
            or parsed.path not in ('', '/') or parsed.query or parsed.fragment):
        raise Refused('invalid_cloud_run_origin')
    return value.rstrip('/')


def probe(url, path, source, token, *, timeout=30, opener=None):
    request = Request(url + path, headers={'X-Serverless-Authorization': 'Bearer ' + token,
                                         'Accept': 'application/json', 'User-Agent': 'ziper-private-backup-verification',
                                         'Cache-Control': 'no-cache'})
    try:
        response = (opener or build_opener(NoRedirect())).open(request, timeout=timeout)
    except HTTPError as error:
        error.close()
        return {'path': path, 'ok': False, 'status': error.code, 'reason': 'http_error'}
    with response:
        status = response.status
        if status != 200:
            return {'path': path, 'ok': False, 'status': status, 'reason': 'http_error'}
        directives = [item.strip().lower() for item in response.headers.get('Cache-Control', '').split(',')]
        if ('no-store' not in directives or response.headers.get('Set-Cookie') is not None
                or response.headers.get('CF-Cache-Status', '').upper() in ('HIT', 'STALE', 'UPDATING')
                or response.headers.get_content_type() != 'application/json'
                or response.headers.get('X-Ziper-Origin') != 'cloudrun'
                or response.headers.get('X-Ziper-Release') != source):
            return {'path': path, 'ok': False, 'status': status, 'reason': 'response_contract_invalid'}
        body = response.read(4097)
        if len(body) > 4096:
            return {'path': path, 'ok': False, 'status': status, 'reason': 'response_too_large'}
        try:
            valid = json.loads(body) == {'status': 'UP'}
        except (ValueError, UnicodeError):
            valid = False
        return {'path': path, 'ok': valid, 'status': status,
                **({} if valid else {'reason': 'response_contract_invalid'})}


def verify(url, source, token, *, checks=3, interval=10, check=probe, sleep=time.sleep):
    report = {'checkedAt': datetime.now(timezone.utc).isoformat(), 'sourceSha': source,
              'ok': False, 'samples': []}
    for index in range(checks):
        sample = []
        for path in ('/livez', '/readyz'):
            try:
                result = check(url, path, source, token)
            except (Refused, URLError, TimeoutError, OSError, ValueError):
                result = {'path': path, 'ok': False, 'status': None, 'reason': 'private_health_request_failed'}
            sample.append(result)
            if not result['ok']:
                report['samples'].append(sample)
                return report
        report['samples'].append(sample)
        if index + 1 < checks:
            sleep(interval)
    report['ok'] = True
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url', required=True)
    parser.add_argument('--source', required=True)
    parser.add_argument('--checks', type=int, choices=range(1, 11), default=3)
    parser.add_argument('--interval', type=int, choices=range(1, 61), default=10)
    parser.add_argument('--output', type=Path, default=Path('dist/cloud-run-health.json'))
    args = parser.parse_args()
    token = os.environ.get('CLOUD_RUN_ID_TOKEN', '')
    try:
        args.url = origin(args.url)
        if not re.fullmatch('[a-f0-9]{40}', args.source) or len(token) < 32 or any(c.isspace() for c in token):
            raise Refused('invalid_health_configuration')
    except (ValueError, Refused):
        parser.error('Supply a valid backup origin, source SHA and private ID token environment')
    report = verify(args.url, args.source, token, checks=args.checks, interval=args.interval)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report))
    return 0 if report['ok'] else 1


if __name__ == '__main__':
    sys.exit(main())
