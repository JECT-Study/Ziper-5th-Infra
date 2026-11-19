#!/usr/bin/env python3
"""Ensure zone-level Workers bypass (None) routes exist before attaching a */* custom-hostname route.

Never logs token values or raw API bodies, and never overwrites routes bound to a Worker script.
"""
import json
import os
import re
import urllib.parse
import urllib.request

API = 'https://api.cloudflare.com/client/v4'


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def external_hosts(extra_origins, zone_name):
    hosts = []
    for raw in extra_origins.split(','):
        item = raw.strip()
        if not item:
            continue
        parsed = urllib.parse.urlsplit(item)
        host = parsed.hostname or ''
        if parsed.scheme != 'https' or not host or parsed.username or parsed.password or parsed.port or parsed.path not in ('', '/') or parsed.query or parsed.fragment or host.endswith('.invalid'):
            raise SystemExit('Invalid extra public origin configuration')
        if host == zone_name:
            raise SystemExit('Apex zone cannot be an extra public origin')
        if not host.endswith('.' + zone_name):
            hosts.append(host)
    return hosts


def required_bypass_patterns(zone_name):
    return [f'*.{zone_name}/*', f'{zone_name}/*']


def main(call=None):
    zone_name = os.environ.get('CLOUDFLARE_ZONE_NAME', '')
    if not re.fullmatch(r'[a-z0-9.-]+', zone_name):
        raise SystemExit('Invalid zone configuration')
    external = external_hosts(os.environ.get('EXTRA_PUBLIC_ORIGINS', ''), zone_name)
    if not external:
        print(json.dumps({'required': False, 'created': 0, 'verified': 0}))
        return

    token = os.environ.get('CLOUDFLARE_API_TOKEN', '')
    account_id = os.environ.get('CLOUDFLARE_ACCOUNT_ID', '')
    if not token:
        raise SystemExit('Missing Cloudflare API token')
    if account_id and not re.fullmatch(r'[a-f0-9]{32}', account_id):
        raise SystemExit('Invalid account configuration')
    opener = urllib.request.build_opener(NoRedirect())

    def request(method, path, payload=None):
        data = json.dumps(payload).encode('utf-8') if payload is not None else None
        headers = {'Authorization': 'Bearer ' + token, 'Accept': 'application/json'}
        if data is not None:
            headers['Content-Type'] = 'application/json'
        req = urllib.request.Request(API + path, data=data, method=method, headers=headers)
        with opener.open(req, timeout=10) as response:
            body = json.loads(response.read(65536))
        if body.get('success') is not True:
            raise SystemExit('Cloudflare API request failed')
        return body['result']

    call = call or request
    zones = call('GET', '/zones?' + urllib.parse.urlencode({'name': zone_name}), None)
    zones = [z for z in zones if z.get('name') == zone_name and (not account_id or z.get('account', {}).get('id') == account_id)]
    if len(zones) != 1:
        raise SystemExit('Zone not found')
    zone_id = zones[0]['id']

    patterns = required_bypass_patterns(zone_name)
    routes = call('GET', f'/zones/{zone_id}/workers/routes', None)
    created = 0
    for pattern in patterns:
        matching = [r for r in routes if r.get('pattern') == pattern]
        if any(r.get('script') for r in matching):
            raise SystemExit('Conflicting worker route exists for zone bypass pattern')
        if not matching:
            call('POST', f'/zones/{zone_id}/workers/routes', {'pattern': pattern})
            created += 1

    verified_routes = call('GET', f'/zones/{zone_id}/workers/routes', None) if created else routes
    verified = 0
    for pattern in patterns:
        matching = [r for r in verified_routes if r.get('pattern') == pattern]
        if not matching or any(r.get('script') for r in matching):
            raise SystemExit('Zone bypass route readback verification failed')
        verified += 1

    print(json.dumps({'required': True, 'created': created, 'verified': verified}))


if __name__ == '__main__':
    main()
