import importlib.util
import os
from pathlib import Path
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('ensure_saas_bypass_routes', Path(__file__).with_name('ensure-saas-bypass-routes.py'))
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

BASE_ENV = {
    'CLOUDFLARE_API_TOKEN': 'fixture-token',
    'CLOUDFLARE_ACCOUNT_ID': 'a' * 32,
    'CLOUDFLARE_ZONE_NAME': 'joonamin.dev',
    'EXTRA_PUBLIC_ORIGINS': 'https://api.ziper.cc',
}


class EnsureSaasBypassRoutesTests(unittest.TestCase):
    def test_skips_when_no_external_custom_hostnames(self):
        calls = []
        for extra in ('', 'https://alt.joonamin.dev'):
            with patch.dict(os.environ, {**BASE_ENV, 'EXTRA_PUBLIC_ORIGINS': extra}, clear=True):
                module.main(lambda method, path, payload: calls.append((method, path, payload)))
        self.assertEqual(calls, [])

    def test_creates_missing_bypass_routes_and_verifies_readback(self):
        routes = [
            {'id': 'existing-api', 'pattern': 'api-ziper.joonamin.dev/*', 'script': 'ziper-edge'},
            {'id': 'existing-tock', 'pattern': 'tock.joonamin.dev/*', 'script': 'tock-worker'},
        ]
        posts = []

        def call(method, path, payload):
            if path.startswith('/zones?'):
                return [{'id': 'zone-1', 'name': 'joonamin.dev', 'account': {'id': 'a' * 32}}]
            if method == 'GET' and path == '/zones/zone-1/workers/routes':
                return list(routes)
            if method == 'POST' and path == '/zones/zone-1/workers/routes':
                posts.append(payload)
                routes.append({'id': f'bypass-{len(posts)}', 'pattern': payload['pattern']})
                return routes[-1]
            raise AssertionError(f'Unexpected call: {method} {path}')

        with patch.dict(os.environ, BASE_ENV, clear=True):
            module.main(call)
        self.assertEqual(posts, [{'pattern': '*.joonamin.dev/*'}, {'pattern': 'joonamin.dev/*'}])

    def test_idempotent_when_bypass_routes_already_exist(self):
        routes = [
            {'id': 'b1', 'pattern': '*.joonamin.dev/*'},
            {'id': 'b2', 'pattern': 'joonamin.dev/*', 'script': None},
        ]
        posts = []

        def call(method, path, payload):
            if path.startswith('/zones?'):
                return [{'id': 'zone-1', 'name': 'joonamin.dev', 'account': {'id': 'a' * 32}}]
            if method == 'GET':
                return routes
            posts.append((method, path, payload))
            return {}

        with patch.dict(os.environ, BASE_ENV, clear=True):
            module.main(call)
        self.assertEqual(posts, [])

    def test_refuses_when_conflicting_worker_owns_bypass_pattern(self):
        routes = [{'id': 'conflict', 'pattern': '*.joonamin.dev/*', 'script': 'other-worker'}]

        def call(method, path, payload):
            if path.startswith('/zones?'):
                return [{'id': 'zone-1', 'name': 'joonamin.dev', 'account': {'id': 'a' * 32}}]
            if method == 'GET':
                return routes
            raise AssertionError('Should not mutate when conflicting script exists')

        with patch.dict(os.environ, BASE_ENV, clear=True):
            with self.assertRaises(SystemExit):
                module.main(call)

    def test_rejects_apex_zone_extra_origin(self):
        with patch.dict(os.environ, {**BASE_ENV, 'EXTRA_PUBLIC_ORIGINS': 'https://joonamin.dev'}, clear=True):
            with self.assertRaises(SystemExit):
                module.main(lambda method, path, payload: [])


if __name__ == '__main__':
    unittest.main()
