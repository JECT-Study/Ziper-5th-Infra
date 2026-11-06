#!/usr/bin/env python3
"""Wait for Tunnel startup, then require consecutive public health samples."""
import argparse
from datetime import datetime, timezone
import importlib.util
import json
from pathlib import Path
import time
from urllib.error import URLError


def wait_for_health(check, *, budget=180, now=time.monotonic, sleep=time.sleep):
    deadline = now() + budget
    streak = 0
    attempts = 0
    samples = []
    while now() < deadline:
        attempts += 1
        try:
            sample = []
            for path in ('/livez', '/readyz'):
                remaining = deadline - now()
                if remaining <= 0:
                    raise TimeoutError()
                sample.append(check(path, min(10, remaining)))
            streak += 1
            samples.append(sample)
            if streak == 3:
                return {'ok': True, 'attempts': attempts, 'samples': samples[-3:]}
        except (ValueError, URLError, TimeoutError, OSError):
            streak = 0
            samples = []
        remaining = deadline - now()
        if remaining > 0:
            sleep(min(10 if streak else 5, remaining))
    return {'ok': False, 'attempts': attempts, 'samples': [],
            'error': 'Public health did not stabilize within the startup deadline'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--contract', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    spec = importlib.util.spec_from_file_location('server_health_contract', args.contract)
    contract = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(contract)
    origin = 'https://api-ziper.joonamin.dev'
    report = {'checkedAt': datetime.now(timezone.utc).isoformat(), 'origin': origin,
              **wait_for_health(lambda path, timeout: contract.check_once(origin, path, timeout))}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report))
    return 0 if report['ok'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
