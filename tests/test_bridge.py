import importlib.util
import json
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import Mock, patch
import anki_recall as app


def card(cid=1, kind=0, queue=0, deck='English'):
    return dict(cardId=cid, note=100, type=kind, queue=queue, deckName=deck, due=42)


class BridgeTests(unittest.TestCase):
    def test_english_inflection_forms(self):
        from goldendict_anki.word_forms import lookup_forms
        expected = {'dogs': 'dog', 'children': 'child', 'running': 'run',
                    'ran': 'run', 'went': 'go', 'studies': 'study',
                    'studied': 'study', 'better': 'good'}
        for form, lemma in expected.items():
            self.assertEqual(lookup_forms(form), [form, lemma])
        self.assertEqual(lookup_forms('news'), ['news'])
        self.assertEqual(lookup_forms('two words'), ['two words'])
        self.assertEqual(lookup_forms('dogs', enabled=False), ['dogs'])

    def test_lookup_falls_back_to_lemma(self):
        api = Mock()
        api.call.side_effect = [[100], [
            {'noteId': 100, 'fields': {'Word': {'value': 'run'},
              'Definition': {'value': 'move quickly'}}}],
            [1], [card()]]
        cards = app.lookup(api, app.DEFAULTS, 'running')
        self.assertEqual(cards[0]['_matched_word'], 'run')
        self.assertIn('OR', api.call.call_args_list[0].kwargs['query'])
        output = app.render('running', cards)
        self.assertIn('running → run', output)
        self.assertEqual(json.loads(output.split('class="anki-config">', 1)[1].split('</script>', 1)[0])['word'], 'run')
        self.assertEqual(json.loads(app.render('running', cards, fmt='json'))['cards'][0]['headword'], 'run')

    def test_exact_headword_and_lemma_are_both_returned(self):
        api = Mock()
        api.call.side_effect = [[100, 101], [
            {'noteId': 100, 'fields': {'Word': {'value': 'dogs'}}},
            {'noteId': 101, 'fields': {'Word': {'value': 'dog'}}}],
            [1], [card()], [2], [card(2)]]
        cards = app.lookup(api, app.DEFAULTS, 'dogs')
        self.assertEqual([c['_matched_word'] for c in cards], ['dogs', 'dog'])
        self.assertIn('nid:100', api.call.call_args_list[2].kwargs['query'])
        self.assertIn('nid:101', api.call.call_args_list[4].kwargs['query'])

    def test_promote_validates_actual_lemma(self):
        api = Mock(); api.call.return_value = {'message': 'ok'}
        c = card() | {'_matched_word': 'run'}
        app.promote(api, app.DEFAULTS, 'running', [c])
        self.assertEqual(api.call.call_args.kwargs['word'], 'run')

    def test_normalization(self):
        self.assertEqual(app.normalize('<b>Tour</b>nament&nbsp;', markup=True), 'tournament')
        self.assertNotEqual(app.normalize('tournaments'), 'tournament')
        self.assertNotEqual(app.normalize('Word', True), 'word')
        self.assertEqual(app.normalize('e\u0301'), app.normalize('é'))

    def test_lookup_exact_and_scope(self):
        api = Mock()
        api.call.side_effect = [[100, 101], [
            {'noteId': 100, 'fields': {'Word': {'value': '<b>Tour</b>nament'}}},
            {'noteId': 101, 'fields': {'Word': {'value': 'tournaments'}}}],
            [1, 2], [card(), card(2, deck='Other')]]
        config = app.DEFAULTS | {'deck': 'English'}
        self.assertEqual([c['cardId'] for c in app.lookup(api, config, 'tournament')], [1])
        self.assertEqual([c.args[0] for c in api.call.call_args_list], ['findNotes', 'notesInfo', 'findCards', 'cardsInfo'])

    def test_missing_field(self):
        api = Mock()
        api.call.side_effect = [[100], [{'fields': {'Front': {'value': 'x'}}}]]
        with self.assertRaises(app.BridgeError):
            app.lookup(api, app.DEFAULTS, 'x')

    def test_no_match(self):
        api = Mock()
        api.call.return_value = []
        self.assertEqual(app.lookup(api, app.DEFAULTS, 'missing'), [])

    def test_review_learning_buried_unchanged(self):
        api = Mock()
        for c in [card(kind=2, queue=2), card(kind=1, queue=1), card(queue=-2), card(kind=2, queue=-1)]:
            app.promote(api, app.DEFAULTS, 'x', [c], unsuspend=True)
        api.call.assert_not_called()

    def test_suspended_requires_flag(self):
        api = Mock()
        app.promote(api, app.DEFAULTS, 'x', [card(queue=-1)])
        api.call.assert_not_called()
        api.call.return_value = {'message': 'ok'}
        app.promote(api, app.DEFAULTS, 'x', [card(queue=-1)], unsuspend=True)
        self.assertEqual(api.call.call_args.args[0], 'gdPromoteNew')
        self.assertTrue(api.call.call_args.kwargs['unsuspend'])

    def test_duplicate_requires_selection(self):
        api = Mock()
        with self.assertRaises(app.BridgeError):
            app.promote(api, app.DEFAULTS, 'x', [card(), card(2)])
        api.call.assert_not_called()
        api.call.return_value = {'message': 'ok'}
        app.promote(api, app.DEFAULTS, 'x', [card(), card(2)], card_id=2)
        self.assertEqual(api.call.call_args.kwargs['cardId'], 2)

    def test_wrong_card_id(self):
        with self.assertRaises(app.BridgeError):
            app.promote(Mock(), app.DEFAULTS, 'x', [card()], card_id=9)

    def test_html_escaping(self):
        output = app.render('<script>x</script>', [card(deck='<img>')])
        self.assertNotIn('<script>x</script>', output)
        self.assertIn('&lt;script&gt;x&lt;/script&gt;', output)
        self.assertEqual(output.count('</script>'), 2)
        self.assertNotIn('<img>', output)

    def test_senses_and_card_faces(self):
        first = card() | {'_fields': {'Definition': 'sports contest'},
                          'question': '<style>bad css</style><b>front</b><script>bad js</script>'}
        second = card(2) | {'_fields': {'DefinitionTR': '骑士竞赛'}}
        output = app.render('tournament', [first, second])
        self.assertIn('sports contest', output)
        self.assertIn('骑士竞赛', output)
        self.assertIn('正面：front', output)
        self.assertNotIn('bad css', output)
        self.assertNotIn('bad js', output)
        self.assertEqual(output.count('type="radio"'), 2)
        self.assertEqual(output.count(' checked'), 1)
        self.assertIn('class="anki-card is-selected"', output)

    def test_script_data_and_article_isolation(self):
        from html.parser import HTMLParser
        class ConfigParser(HTMLParser):
            def __init__(self):
                super().__init__(); self.capture = False; self.data = ''; self.ids = []
            def handle_starttag(self, tag, attrs):
                attrs = dict(attrs)
                if tag == 'div' and 'id' in attrs: self.ids.append(attrs['id'])
                self.capture = tag == 'script' and attrs.get('type') == 'application/json'
            def handle_data(self, data):
                if self.capture: self.data += data
        word = '</script><img onerror="alert(1)">'
        p = ConfigParser(); p.feed(app.render(word, [card()]))
        self.assertEqual(json.loads(p.data)['word'], word)
        q = ConfigParser(); q.feed(app.render('other', [card()]))
        self.assertNotEqual(p.ids, q.ids)

    def test_no_actions_on_empty_or_error(self):
        for cards, error in [([], False), ([card()], True)]:
            self.assertNotIn('<button', app.render('x', cards, error=error))
        empty = app.render('x', [])
        self.assertNotIn('type="radio"', empty)
        self.assertNotIn(' checked', empty)

    def test_loopback_only(self):
        with self.assertRaises(app.BridgeError):
            app.Client(app.DEFAULTS | {'url': 'http://example.com:8765'})

    def test_http_contract_and_errors(self):
        import io
        client = app.Client(app.DEFAULTS)
        client.opener = Mock()
        client.opener.open.return_value = io.BytesIO(b'{"result":6,"error":null}')
        self.assertEqual(client.call('version'), 6)
        request = client.opener.open.call_args.args[0]
        self.assertEqual(json.loads(request.data)['version'], 6)
        client.opener.open.return_value = io.BytesIO(b'{"result":null,"error":"unsupported action"}')
        with self.assertRaisesRegex(app.BridgeError, '尚未启用提队扩展'):
            client.call('gdPromoteNew')
        client.opener.open.side_effect = TimeoutError()
        with self.assertRaises(app.BridgeError):
            client.call('version')


class AddonTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        aqt = types.ModuleType('aqt')
        aqt.gui_hooks = types.SimpleNamespace(profile_did_open=[])
        with patch.dict(sys.modules, {'aqt': aqt}):
            spec = importlib.util.spec_from_file_location('test_addon', Path(__file__).resolve().parents[1] / 'addon/__init__.py', submodule_search_locations=[str(Path(__file__).resolve().parents[1] / 'addon')])
            cls.module = importlib.util.module_from_spec(spec)
            sys.modules['test_addon'] = cls.module
            spec.loader.exec_module(cls.module)

    def test_register(self):
        module = types.ModuleType('fake_anki_connect')
        class AnkiConnect:
            handler = cardsInfo = collection = lambda self: None
        module.AnkiConnect = AnkiConnect
        queue_module = types.ModuleType('test_addon.priority_queue')
        queue_module.install = Mock()
        with patch.dict(sys.modules, {'fake_anki_connect': module, 'test_addon.priority_queue': queue_module}):
            self.module.register()
        self.assertTrue(AnkiConnect.gdPromoteNew.api)

    def test_gd_cors_compat_is_scoped(self):
        class Server:
            def allowOrigin(self, req):
                return False, 'original'
        settings = {'webBindPort': 8765, 'webCorsOriginList': ['gdlookup://localhost']}
        web = types.SimpleNamespace(WebServer=Server, util=types.SimpleNamespace(setting=settings.get))
        self.module.install_cors_compat(web)
        self.module.install_cors_compat(web)
        body = {'action': 'requestPermission', 'gdBridgeOrigin': 'gdlookup://localhost'}
        req = types.SimpleNamespace(method=b'POST', headers={b'origin': b'http://127.0.0.1:8765'}, body=json.dumps(body).encode())
        self.assertEqual(Server().allowOrigin(req), (True, 'gdlookup://localhost'))
        for action in ('deleteDecks', 'version'):
            req.body = json.dumps(body | {'action': action}).encode()
            self.assertEqual(Server().allowOrigin(req), (False, 'original'))
        req.body = json.dumps(body | {'action': 'gdPromoteNew'}).encode()
        self.assertEqual(Server().allowOrigin(req), (True, 'gdlookup://localhost'))
        settings['webCorsOriginList'] = []
        self.assertEqual(Server().allowOrigin(req), (False, 'original'))
        settings['webCorsOriginList'] = ['gdlookup://localhost']
        req.headers[b'origin'] = b'https://example.com'
        self.assertEqual(Server().allowOrigin(req), (False, 'original'))
        req.body = b'not json'
        self.assertEqual(Server().allowOrigin(req), (False, 'original'))

    def test_matching_code_stays_consistent(self):
        for value in ['<b>Tour</b>nament', 'e\u0301', 'Word', ' a&nbsp;b ']:
            self.assertEqual(self.module.normalize(value, markup=True), app.normalize(value, markup=True))


if __name__ == '__main__':
    unittest.main()
