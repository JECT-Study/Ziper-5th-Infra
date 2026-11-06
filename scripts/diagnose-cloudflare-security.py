#!/usr/bin/env python3
"""Read-only, bounded Cloudflare security metadata; never record API bodies or credentials."""
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import re
import urllib.error
import urllib.request

API = 'https://api.cloudflare.com/client/v4'
HOST = 'origin-ziper.joonamin.dev'
SOURCES = {'bic', 'botFight', 'botManagement', 'country', 'firewallCustom', 'firewallManaged',
           'firewallRules', 'ip', 'ipRange', 'l7ddos', 'rateLimit', 'securityLevel', 'uaBlock', 'waf', 'zoneLockdown'}
ACTIONS = {'allow', 'block', 'challenge', 'jschallenge', 'managedChallenge', 'managedChallengeBypassed',
           'managedChallengeInteractiveSolved', 'managedChallengeNonInteractiveSolved', 'skip', 'log'}
QUERY = '''query ListFirewallEvents($zoneTag: string, $filter: FirewallEventsAdaptiveFilter_InputObject) {
  viewer { zones(filter: {zoneTag: $zoneTag}) {
    firewallEventsAdaptive(filter: $filter, limit: 20, orderBy: [datetime_DESC]) {
      action source ruleId datetime rayName
    }
  } }
}'''


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args):
        return None


def api(token, path, data=None, *, opener=None):
    headers = {'Authorization': 'Bearer ' + token, 'Accept': 'application/json',
               'User-Agent': 'ziper-security-readback'}
    if data is not None:
        headers['Content-Type'] = 'application/json'
    request = urllib.request.Request(API + path, headers=headers,
                                     data=json.dumps(data).encode() if data is not None else None)
    try:
        with (opener or urllib.request.build_opener(NoRedirect())).open(request, timeout=10) as response:
            body = response.read(65537)
            if len(body) > 65536:
                return response.status, None
            return response.status, json.loads(body)
    except urllib.error.HTTPError as error:
        status = error.code
        error.close()
        return status, None
    except (OSError, ValueError, urllib.error.URLError):
        return None, None


def sanitize_events(raw):
    if not isinstance(raw, list) or len(raw) > 20:
        raise ValueError('invalid_events')
    events = []
    for event in raw:
        if not isinstance(event, dict):
            raise ValueError('invalid_event')
        def field(name, pattern):
            value = event.get(name)
            return value if isinstance(value, str) and re.fullmatch(pattern, value) else None
        source, action = event.get('source'), event.get('action')
        events.append({
            'source': source if isinstance(source, str) and source in SOURCES else 'unrecognized',
            'action': action if isinstance(action, str) and action in ACTIONS else 'unrecognized',
            'ruleId': field('ruleId', r'(?:[a-f0-9]{32}|[0-9]{1,10})'),
            'at': field('datetime', r'[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]+)?Z'),
            'ray': field('rayName', r'[a-f0-9]{16}(?:-[A-Z]{3})?')})
    return events


def rest_value(body):
    return body.get('result') if isinstance(body, dict) and body.get('success') is True else None


def graphql_error_kind(body):
    if not isinstance(body, dict) or not isinstance(body.get('errors'), list):
        return 'unavailable'
    messages = ' '.join(e['message'][:1024].lower() for e in body['errors'][:20]
                        if isinstance(e, dict) and isinstance(e.get('message'), str))
    if any(p in messages for p in ('not authorized', 'not authorised', 'does not have access',
                                   'insufficient permission', 'not allowed', 'not have permission', 'forbidden')):
        return 'authorization'
    if any(p in messages for p in ('unknown field', 'unknown argument', 'cannot query field', 'unknown type', 'syntax error')):
        return 'query_schema'
    return 'other'


def main():
    credential_source = os.environ.get('CF_SECURITY_TOKEN_SOURCE', 'worker')
    report = {'checkedAt': datetime.now(timezone.utc).isoformat(), 'host': HOST,
              'credentialSource': credential_source if credential_source in ('dedicated', 'worker') else 'unrecognized',
              'readOnly': True, 'eventsReadable': False, 'events': [],
              'scope': 'At most20 sampled historical events for protected readyz; settings alone do not establish the cause'}
    try:
        token = os.environ.get('CLOUDFLARE_API_TOKEN', '')
        account = os.environ.get('CLOUDFLARE_ACCOUNT_ID', '')
        if not token or not re.fullmatch('[a-f0-9]{32}', account):
            raise ValueError('configuration')
        status, body = api(token, '/zones?name=joonamin.dev')
        report['zoneLookupHttpStatus'] = status
        zones = rest_value(body)
        matches = [z for z in zones if isinstance(z, dict) and z.get('name') == 'joonamin.dev'
                   and z.get('account', {}).get('id') == account] if isinstance(zones, list) else []
        if len(matches) != 1 or not re.fullmatch('[a-f0-9]{32}', matches[0].get('id', '')):
            raise ValueError('zone_unavailable')
        zone = matches[0]['id']
        settings = {}
        for name, choices in [('security_level', {'off', 'essentially_off', 'low', 'medium', 'high', 'under_attack'}),
                              ('browser_check', {'on', 'off'})]:
            status, body = api(token, '/zones/' + zone + '/settings/' + name)
            value = rest_value(body)
            value = value.get('value') if isinstance(value, dict) else None
            settings[name] = {'httpStatus': status, 'value': value if isinstance(value, str) and value in choices else None}
        status, body = api(token, '/zones/' + zone + '/bot_management')
        bot = rest_value(body)
        fight = bot.get('fight_mode') if isinstance(bot, dict) else None
        report['settings'] = settings
        report['botFightMode'] = {'httpStatus': status, 'enabled': fight if type(fight) is bool else None}
        end = datetime.now(timezone.utc)
        filters = {'datetime_geq': (end - timedelta(hours=2)).strftime('%Y-%m-%dT%H:%M:%SZ'),
                   'datetime_leq': end.strftime('%Y-%m-%dT%H:%M:%SZ'),
                   'clientRequestHTTPHost': HOST, 'clientRequestPath': '/readyz'}
        status, body = api(token, '/graphql', {'query': QUERY, 'variables': {'zoneTag': zone, 'filter': filters}})
        report['eventsHttpStatus'] = status
        report['window'] = {k: filters[k] for k in ('datetime_geq', 'datetime_leq')}
        if not isinstance(body, dict) or body.get('errors'):
            report['eventsResult'] = 'graphql_rejected_or_unavailable'
            report['graphqlErrorKind'] = graphql_error_kind(body)
        else:
            report['events'] = sanitize_events(body['data']['viewer']['zones'][0]['firewallEventsAdaptive'])
            report['eventsReadable'] = True
            report['eventsResult'] = 'readable'
    except (OSError, ValueError, KeyError, IndexError, TypeError, AttributeError):
        report['eventsResult'] = 'configuration_or_response_unavailable'
    output = Path('dist/cloudflare-security.json')
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report))
    return 0 if report['eventsReadable'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
