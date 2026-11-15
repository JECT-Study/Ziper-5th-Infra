#!/usr/bin/env python3
"""Detach only the ziper-edge Worker route of the public host. Never logs token values or API bodies."""
import json
import os
import re
import sys
import urllib.parse
import urllib.request

API = 'https://api.cloudflare.com/client/v4'
SCRIPT = 'ziper-edge'


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def targets(routes, host):
    """Routes bound to this Worker for exactly the public host; other scripts and hosts are untouched."""
    return [r for r in routes if r.get('script') == SCRIPT and r.get('pattern') == host + '/*']


def main(argv, call=None):
    apply = '--apply' in argv
    token = os.environ.get('CLOUDFLARE_API_TOKEN', '')
    zone_name = os.environ.get('CLOUDFLARE_ZONE_NAME', '')
    host = urllib.parse.urlsplit(os.environ.get('PUBLIC_ORIGIN', '')).hostname or ''
    if not token or not re.fullmatch(r'[a-z0-9.-]+', zone_name) or not host.endswith('.' + zone_name):
        raise SystemExit('Invalid edge route configuration')
    opener = urllib.request.build_opener(NoRedirect())

    def request(method, path):
        req = urllib.request.Request(API + path, method=method, headers={'Authorization': 'Bearer ' + token})
        with opener.open(req, timeout=10) as response:
            body = json.loads(response.read(65536))
        if not body.get('success'):
            raise SystemExit('Cloudflare API request failed')
        return body['result']

    call = call or request
    zones = call('GET', '/zones?' + urllib.parse.urlencode({'name': zone_name}))
    if len(zones) != 1:
        raise SystemExit('Zone not found')
    zone = zones[0]['id']
    matched = targets(call('GET', f'/zones/{zone}/workers/routes'), host)
    if apply:
        for route in matched:
            call('DELETE', f"/zones/{zone}/workers/routes/{route['id']}")
    print(json.dumps({'host': host, 'script': SCRIPT, 'matched': len(matched), 'removed': len(matched) if apply else 0}))


if __name__ == '__main__':
    main(sys.argv[1:])
