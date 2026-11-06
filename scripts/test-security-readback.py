#!/usr/bin/env python3
import importlib.util
import io
import json
from pathlib import Path
from types import SimpleNamespace
import unittest
import urllib.error

spec = importlib.util.spec_from_file_location('security', Path(__file__).with_name('diagnose-cloudflare-security.py'))
security = importlib.util.module_from_spec(spec)
spec.loader.exec_module(security)


class SecurityReadbackTests(unittest.TestCase):
    def test_event_report_only_keeps_typed_metadata_not_private_fields(self):
        marker = 'fixture-private-marker'
        raw = {'source': 'botFight', 'action': 'managedChallenge', 'ruleId': 'a' * 32,
               'datetime': '2026-11-06T21:52:35Z', 'rayName': 'b' * 16,
               'clientIP': marker, 'clientRequestQuery': marker, 'description': marker, 'userAgent': marker}
        clean = security.sanitize_events([raw])[0]
        self.assertEqual(clean['source'], 'botFight')
        self.assertEqual(clean['action'], 'managedChallenge')
        self.assertEqual(clean['ruleId'], 'a' * 32)
        self.assertNotIn(marker, json.dumps(clean))
        unknown = security.sanitize_events([{k: marker for k in raw}])[0]
        self.assertEqual(unknown['source'], 'unrecognized')
        self.assertEqual(unknown['action'], 'unrecognized')
        self.assertIsNone(unknown['ruleId'])
        self.assertNotIn(marker, json.dumps(unknown))
        with self.assertRaises(ValueError):
            security.sanitize_events([raw] * 21)
        for message, expected in [('not authorized ' + marker, 'authorization'),
                                  ('Cannot query field ' + marker, 'query_schema'), (marker, 'other')]:
            self.assertEqual(security.graphql_error_kind({'errors': [{'message': message}]}), expected)

    def test_api_rejects_oversized_body_and_does_not_return_error_bodies(self):
        class Response(io.BytesIO):
            status = 200
        requests = []
        def oversized(request, timeout):
            requests.append(request)
            self.assertEqual(timeout, 10)
            return Response(b'x' * 65537)
        status, data = security.api('fixture-private-token', '/graphql', {'query': security.QUERY},
                                    opener=SimpleNamespace(open=oversized))
        self.assertEqual((status, data), (200, None))
        self.assertEqual(requests[0].get_method(), 'POST')
        self.assertTrue(json.loads(requests[0].data)['query'].startswith('query '))
        private = io.BytesIO(b'fixture-private-error-body')
        def denied(*args, **kwargs):
            raise urllib.error.HTTPError('https://api.cloudflare.com/client/v4/graphql', 403, 'Denied', {}, private)
        self.assertEqual(security.api('fixture-private-token', '/graphql', opener=SimpleNamespace(open=denied)), (403, None))
        self.assertTrue(private.closed)
        self.assertIsNone(security.NoRedirect().redirect_request(None, None, None, None, None, None))


if __name__ == '__main__':
    unittest.main()
