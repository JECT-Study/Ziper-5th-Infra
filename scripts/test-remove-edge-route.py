import importlib.util
import os
from pathlib import Path
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('remove_edge_route', Path(__file__).with_name('remove-edge-route.py'))
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
ENV = {'CLOUDFLARE_API_TOKEN': 'fixture-token', 'CLOUDFLARE_ZONE_NAME': 'joonamin.dev',
       'PUBLIC_ORIGIN': 'https://api-ziper.joonamin.dev'}
ROUTES = [{'id': 'a', 'pattern': 'api-ziper.joonamin.dev/*', 'script': 'ziper-edge'},
          {'id': 'b', 'pattern': 'tock.joonamin.dev/*', 'script': 'ziper-edge'},
          {'id': 'c', 'pattern': 'api-ziper.joonamin.dev/*', 'script': 'other'},
          {'id': 'd', 'pattern': '*/*', 'script': 'ziper-edge'},
          {'id': 'e', 'pattern': '*.joonamin.dev/*'},
          {'id': 'f', 'pattern': 'joonamin.dev/*', 'script': None}]


class RemoveEdgeRouteTests(unittest.TestCase):
    def run_with(self, argv, extra_env=None):
        calls = []

        def call(method, path):
            calls.append((method, path))
            return [{'id': 'zone'}] if path.startswith('/zones?') else ROUTES if method == 'GET' else None
        env = {**ENV, **(extra_env or {})}
        with patch.dict(os.environ, env, clear=True):
            module.main(argv, call)
        return calls

    def test_dry_run_never_deletes(self):
        self.assertFalse(any(method == 'DELETE' for method, _ in self.run_with([])))

    def test_apply_deletes_only_this_worker_route_for_the_public_host(self):
        deletes = [path for method, path in self.run_with(['--apply']) if method == 'DELETE']
        self.assertEqual(deletes, ['/zones/zone/workers/routes/a'])

    def test_apply_with_external_custom_hostname_also_detaches_wildcard_only_for_this_worker(self):
        deletes = [path for method, path in self.run_with(['--apply'], {'EXTRA_PUBLIC_ORIGINS': 'https://api.ziper.cc'}) if method == 'DELETE']
        self.assertEqual(deletes, ['/zones/zone/workers/routes/a', '/zones/zone/workers/routes/d'])

    def test_host_outside_zone_is_rejected(self):
        with patch.dict(os.environ, {**ENV, 'PUBLIC_ORIGIN': 'https://api.example.com'}, clear=True):
            with self.assertRaises(SystemExit):
                module.main([], lambda method, path: [])


if __name__ == '__main__':
    unittest.main()
