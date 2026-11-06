#!/usr/bin/env python3
import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location('startup', Path(__file__).with_name('verify-home-public.py'))
startup = importlib.util.module_from_spec(spec)
spec.loader.exec_module(startup)


class StartupTest(unittest.TestCase):
    def run_sequence(self, failures, budget=180):
        clock = [0]
        calls = [0]

        def check(path, timeout):
            calls[0] += 1
            if calls[0] in failures:
                raise ValueError('HTTP 530')
            return {'path': path, 'status': 200}

        def sleep(seconds):
            clock[0] += seconds

        return startup.wait_for_health(check, budget=budget, now=lambda: clock[0], sleep=sleep), clock[0]

    def test_tunnel_can_connect_after_first_public_failure(self):
        result, elapsed = self.run_sequence({1, 2})
        self.assertTrue(result['ok'])
        self.assertEqual(result['attempts'], 5)
        self.assertEqual(len(result['samples']), 3)
        self.assertEqual(elapsed, 30)

    def test_failure_resets_success_streak(self):
        result, _ = self.run_sequence({5})
        self.assertTrue(result['ok'])
        self.assertEqual(result['attempts'], 6)

    def test_persistent_failure_is_bounded_and_fails(self):
        result, elapsed = self.run_sequence(set(range(1, 100)), budget=20)
        self.assertFalse(result['ok'])
        self.assertEqual(elapsed, 20)
        self.assertEqual(result['samples'], [])


if __name__ == '__main__':
    unittest.main()
