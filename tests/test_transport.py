"""Local HTTP transport tests; never contact the user's Anki collection."""
import json
import threading
import unittest
import urllib.error
import urllib.request
from unittest.mock import Mock

from goldendict_anki.bridge import Server, alive
from goldendict_anki.cli import DEFAULTS


class TransportTests(unittest.TestCase):
    def setUp(self):
        self.server = Server(DEFAULTS, 'test-token')
        self.server.client = Mock()
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.url = f'http://127.0.0.1:{self.server.server_port}'

    def tearDown(self):
        self.server.shutdown(); self.server.server_close(); self.thread.join()

    def post(self, path='/promote', token='test-token', **body):
        request = urllib.request.Request(self.url + path,
            json.dumps(dict(token=token, **body)).encode(),
            {'Content-Type': 'text/plain', 'Origin': self.url})
        return urllib.request.build_opener(urllib.request.ProxyHandler({})).open(request, timeout=3)

    def test_health_and_invalid_token_do_not_touch_anki(self):
        self.assertTrue(alive({'url': self.url, 'token': 'test-token'}))
        with self.assertRaises(urllib.error.HTTPError) as error:
            self.post(token='wrong')
        self.assertEqual(error.exception.code, 403)
        self.server.client.call.assert_not_called()

    def test_promote_uses_only_standard_api_and_gd_cors(self):
        c = {'cardId': 42, 'type': 0, 'queue': -1, 'deckName': 'English',
             'fields': {'Word': {'value': 'run'}}}
        self.server.client.call.side_effect = [[c], [], None, [c | {'queue': 0}], [], True]
        with self.post(params=dict(card_id=42, word='run', deck='English', unsuspend=True)) as response:
            self.assertEqual(response.headers['Access-Control-Allow-Origin'], 'gdlookup://localhost')
            result = json.load(response)
        self.assertIsNone(result['error'])
        self.assertIn('绿卡', result['result']['message'])
        calls = self.server.client.call.call_args_list
        self.assertEqual([c.args[0] for c in calls], ['cardsInfo', 'findCards', 'unsuspend', 'cardsInfo', 'findCards', 'setDueDate'])
        self.assertEqual(calls[-1].kwargs, {'cards': [42], 'days': '0'})

    def test_arbitrary_actions_and_bad_params_rejected(self):
        with self.assertRaises(urllib.error.HTTPError) as error:
            self.post('/deleteDecks')
        self.assertEqual(error.exception.code, 404)
        self.server.client.call.assert_not_called()

    def test_invalid_params_rejected(self):
        with self.post(params={'action': 'deleteDecks'}) as response:
            self.assertIsNotNone(json.load(response)['error'])
        self.server.client.call.assert_not_called()

    def test_lookup_reads_fresh_data_and_keeps_token_required(self):
        c = {'cardId': 42, 'note': 1, 'type': 0, 'queue': 0, 'due': 1,
             'deckName': 'English'}
        self.server.client.call.side_effect = [[1],
            [{'noteId': 1, 'cards': [42], 'fields': {'Word': {'value': 'two words'}}}],
            [c], []]
        params = dict(word='two words', full_scan=False)
        with self.post('/lookup', params=params) as response:
            first = json.load(response)
        self.assertIsNone(first['error'])
        self.assertIn('找到 1 张卡', first['result'])
        with self.post('/lookup', params=params) as response:
            self.assertIn('没有找到已有卡片', json.load(response)['result'])
        self.assertEqual([c.args[0] for c in self.server.client.call.call_args_list],
                         ['findNotes', 'notesInfo', 'cardsInfo', 'findNotes'])
        with self.assertRaises(urllib.error.HTTPError):
            self.post('/lookup', token='wrong', params=params)
        self.assertEqual(self.server.client.call.call_count, 4)

    def test_lookup_rejects_invalid_parameters(self):
        for params in ({}, {'word': 'x', 'full_scan': 'false'},
                       {'word': 'x', 'full_scan': False, 'action': 'deleteDecks'},
                       {'word': 'x' * 501, 'full_scan': False}):
            with self.post('/lookup', params=params) as response:
                self.assertIsNotNone(json.load(response)['error'])
        self.server.client.call.assert_not_called()

    def test_api_failure_reported_without_retry(self):
        from goldendict_anki.cli import BridgeError
        self.server.client.call.side_effect = BridgeError('connection lost')
        with self.post(params=dict(card_id=42, word='run', deck='English', unsuspend=False)) as response:
            self.assertIn('connection lost', json.load(response)['error'])
        self.assertEqual(self.server.client.call.call_count, 1)


if __name__ == '__main__':
    unittest.main()
