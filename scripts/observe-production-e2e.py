#!/usr/bin/env python3
"""Read-only external observer; records evidence, never changes circuit or origins."""
import argparse
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import re
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import build_opener, HTTPRedirectHandler, Request

MODES = ('CLOSED', 'OPEN', 'HALF_OPEN')
REASONS = ('home', 'circuit_backup', 'scheduled_backup')


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, response, code, message, headers, new_url):
        response.close()
        raise ValueError('redirect_rejected')


def origin(value):
    parsed = urlsplit(value)
    if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password or parsed.path not in ('', '/') or parsed.query or parsed.fragment:
        raise ValueError('invalid_origin')
    return value.rstrip('/')


def finite_number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def ops_snapshot(raw):
    state = raw['state']
    mode = state['mode']['kind']
    generation = state['generation']
    if mode not in MODES or not isinstance(generation, int) or generation < 0 or raw['reason'] not in REASONS:
        raise ValueError('invalid_ops_contract')
    samples = state['samples']
    if not isinstance(samples, list) or len(samples) > 10:
        raise ValueError('invalid_ops_samples')
    clean_samples = []
    for sample in samples:
        if not isinstance(sample['slot'], int) or type(sample['healthy']) is not bool:
            raise ValueError('invalid_ops_sample')
        clean_samples.append({'slot': sample['slot'], 'healthy': sample['healthy']})
    transitions = []
    for transition in raw.get('transitions', [])[:100]:
        if transition['previous'] not in MODES or transition['next'] not in MODES or not all(finite_number(transition[k]) for k in ('at', 'generation')):
            raise ValueError('invalid_ops_transition')
        transitions.append({k: transition[k] for k in ('at', 'previous', 'next', 'generation')})
    next_alarm = raw.get('nextAlarmAt')
    if next_alarm is not None and not finite_number(next_alarm):
        raise ValueError('invalid_ops_alarm')
    result = {'mode': mode, 'generation': generation, 'reason': raw['reason'], 'samples': clean_samples,
              'nextAlarmAt': next_alarm, 'transitions': transitions}
    for name in ('successes', 'retryAt'):
        value = state['mode'].get(name)
        if value is not None and finite_number(value):
            result[name] = value
    return result


def read_url(url, *, token=None, ops=False, timeout=10):
    headers = {'User-Agent': 'ziper-production-e2e', 'Accept': 'application/json', 'Cache-Control': 'no-cache'}
    if token:
        headers['Authorization'] = 'Bearer ' + token
    try:
        try:
            response = build_opener(NoRedirect()).open(Request(url, headers=headers), timeout=timeout)
        except HTTPError as error:
            response = error
        with response:
            result = {'status': response.status}
            if response.status != 200:
                return result
            limit = 65536 if ops else 4096
            body = response.read(limit + 1)
            if len(body) > limit:
                raise ValueError('response_too_large')
            raw = json.loads(body)
            if response.headers.get_content_type() != 'application/json':
                raise ValueError('unexpected_content_type')
            if ops:
                return {**result, **ops_snapshot(raw)}
            release = response.headers.get('X-Ziper-Release')
            upstream = response.headers.get('X-Ziper-Origin')
            result.update(origin=upstream if upstream in ('home', 'cloudrun', 'local') else None,
                          release=release if isinstance(release, str) and re.fullmatch('[a-f0-9]{40}', release) else None,
                          upOnly=raw == {'status': 'UP'}, noStore='no-store' in [item.strip() for item in response.headers.get('Cache-Control', '').lower().split(',')],
                          cached=response.headers.get('CF-Cache-Status', '').upper() in ('HIT', 'STALE', 'UPDATING'),
                          sessionCookie=response.headers.get('Set-Cookie') is not None)
            return result
    except (ValueError, KeyError, TypeError, UnicodeError):
        return {'status': None, 'error': 'response_contract_invalid'}
    except (URLError, TimeoutError, OSError):
        return {'status': None, 'error': 'request_failed'}


def load_marker(path):
    if path is None or not path.exists():
        return None
    if path.stat().st_size > 1024:
        raise ValueError('invalid_fault_marker')
    marker = json.loads(path.read_text())
    if set(marker) != {'faultAt', 'faultMonotonic'} or not all(finite_number(marker[k]) for k in marker):
        raise ValueError('invalid_fault_marker')
    return marker


def healthy(public, release, upstream):
    return (public.get('status') == 200 and public.get('upOnly') is True and public.get('noStore') is True
            and public.get('cached') is False and public.get('sessionCookie') is False
            and public.get('release') == release and public.get('origin') == upstream)


def summarize(rows, *, release, marker):
    summary = {'observations': len(rows), 'expectedRelease': release, 'homeHealthy': False,
               'firstBackupSeconds': None, 'failoverWithin600Seconds': False, 'halfOpenSeen': False,
               'halfOpenFailureSeen': False, 'recoveredClosedAndHome': False, 'releaseMismatch': False,
               'duplicateSampleSlots': False, 'faultMarkerPresent': marker is not None}
    fault_at = marker['faultAt'] if marker else None
    for row in rows:
        public, ops = row['public'], row['ops']
        summary['homeHealthy'] |= healthy(public, release, 'home')
        if public.get('status') == 200 and public.get('release') is not None and public['release'] != release:
            summary['releaseMismatch'] = True
        slots = [sample['slot'] for sample in ops.get('samples', [])]
        summary['duplicateSampleSlots'] |= len(slots) != len(set(slots))
        if marker is None or row['monotonic'] < marker['faultMonotonic']:
            continue
        elapsed = row['monotonic'] - marker['faultMonotonic']
        if healthy(public, release, 'cloudrun') and ops.get('mode') in ('OPEN', 'HALF_OPEN') and ops.get('reason') == 'circuit_backup':
            if summary['firstBackupSeconds'] is None:
                summary['firstBackupSeconds'] = round(elapsed, 3)
                summary['failoverWithin600Seconds'] = 0 <= elapsed <= 600
        transitions = [t for t in ops.get('transitions', []) if t['at'] >= fault_at * 1000]
        summary['halfOpenSeen'] |= ops.get('mode') == 'HALF_OPEN' or any(t['next'] == 'HALF_OPEN' for t in transitions)
        summary['halfOpenFailureSeen'] |= any(t['previous'] == 'HALF_OPEN' and t['next'] == 'OPEN' for t in transitions)
        closed_after_half_open = any(t['previous'] == 'HALF_OPEN' and t['next'] == 'CLOSED' for t in transitions)
        if closed_after_half_open and ops.get('mode') == 'CLOSED' and ops.get('reason') == 'home' and healthy(public, release, 'home'):
            summary['recoveredClosedAndHome'] = True
    return summary


def observe(public_origin, token, release, output, *, seconds, interval, marker_path=None,
            require_failover=False, require_recovery=False, stop_on='none', now=time.monotonic,
            sleep=time.sleep, fetch=read_url):
    started = now()
    rows = []
    output.parent.mkdir(parents=True, exist_ok=True)
    marker = None
    with output.open('x') as stream:
        while now() - started < seconds:
            marker = load_marker(marker_path) or marker
            remaining = seconds - (now() - started)
            public = fetch(public_origin + '/readyz', timeout=min(10, max(0.1, remaining)))
            ops = fetch(public_origin + '/_ops/circuit', token=token, ops=True, timeout=min(10, max(0.1, remaining)))
            row = {'at': datetime.now(timezone.utc).isoformat(), 'monotonic': now(),
                   'elapsedSeconds': round(now() - started, 3), 'public': public, 'ops': ops}
            stream.write(json.dumps(row) + '\n')
            stream.flush()
            rows.append(row)
            summary = summarize(rows, release=release, marker=marker)
            if stop_on == 'failover' and summary['failoverWithin600Seconds'] or stop_on == 'recovery' and summary['recoveredClosedAndHome']:
                break
            remaining = seconds - (now() - started)
            if remaining > 0:
                sleep(min(interval, remaining))
    summary = summarize(rows, release=release, marker=marker)
    summary['ok'] = ((not require_failover or summary['failoverWithin600Seconds'])
                     and (not require_recovery or summary['recoveredClosedAndHome'])
                     and not summary['releaseMismatch'] and not summary['duplicateSampleSlots'])
    summary['verdict'] = 'VERIFIED' if summary['ok'] and (require_failover or require_recovery) else 'OBSERVED' if summary['ok'] else 'NOT_VERIFIED'
    output.with_suffix('.summary.json').write_text(json.dumps(summary, indent=2) + '\n')
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--public-origin', required=True)
    parser.add_argument('--token-file', type=Path)
    parser.add_argument('--release', required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--seconds', type=int, default=1200)
    parser.add_argument('--interval', type=int, default=5)
    parser.add_argument('--fault-marker', type=Path)
    parser.add_argument('--require-failover', action='store_true')
    parser.add_argument('--require-recovery', action='store_true')
    parser.add_argument('--stop-on', choices=('none', 'failover', 'recovery'), default='none')
    args = parser.parse_args()
    try:
        public_origin = origin(args.public_origin)
        if args.token_file and (args.token_file.is_symlink() or args.token_file.stat().st_mode & 0o077):
            raise ValueError('token_file_must_be_private')
        token = args.token_file.read_text().strip() if args.token_file else os.environ.get('OPS_READ_TOKEN', '')
        if len(token) < 32 or not re.fullmatch('[a-f0-9]{40}', args.release) or not 1 <= args.seconds <= 14400 or not 1 <= args.interval <= 60:
            raise ValueError('invalid_observer_configuration')
        summary = observe(public_origin, token, args.release, args.output, seconds=args.seconds, interval=args.interval,
                          marker_path=args.fault_marker, require_failover=args.require_failover,
                          require_recovery=args.require_recovery, stop_on=args.stop_on)
        print(json.dumps(summary))
        return 0 if summary['ok'] else 1
    except (ValueError, OSError, KeyError, TypeError):
        print(json.dumps({'ok': False, 'verdict': 'NOT_VERIFIED', 'error': 'observer_configuration_or_evidence_failed'}))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
