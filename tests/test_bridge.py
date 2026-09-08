import json
import unittest
from unittest.mock import Mock, patch, call
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
            {'noteId': 100, 'cards': [1], 'fields': {'Word': {'value': 'run'},
              'Definition': {'value': 'move quickly'}}}],
            [card()]]
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
            {'noteId': 100, 'cards': [1], 'fields': {'Word': {'value': 'dogs'}}},
            {'noteId': 101, 'cards': [2], 'fields': {'Word': {'value': 'dog'}}}],
            [card(2), card()]]
        cards = app.lookup(api, app.DEFAULTS, 'dogs')
        self.assertEqual([c['_matched_word'] for c in cards], ['dogs', 'dog'])
        self.assertEqual(api.call.call_args_list[2], call('cardsInfo', cards=[1, 2]))
        self.assertEqual(api.call.call_count, 3)

    def promotion_api(self, c=None, word='x'):
        api = Mock()
        current = (c or card()) | {'fields': {'Word': {'value': word}}}
        def respond(action, **params):
            if action == 'cardsInfo':
                return [current]
            if action == 'findCards':
                return []
            if action == 'unsuspend':
                current['queue'] = 0
                return None
            return True
        api.call.side_effect = respond
        return api

    def test_promote_validates_actual_lemma(self):
        api = self.promotion_api(word='<b>run</b>')
        c = card() | {'_matched_word': 'run'}
        app.promote(api, app.DEFAULTS, 'running', [c])
        self.assertEqual(api.call.call_args, call('setDueDate', cards=[1], days='0'))
        self.assertEqual([c.args[0] for c in api.call.call_args_list], ['cardsInfo', 'findCards', 'setDueDate'])

    def test_stale_or_filtered_cards_rejected(self):
        for current in (card(kind=2, queue=2), card(queue=-2), card(deck='Other')):
            api = self.promotion_api(current)
            with self.assertRaises(app.BridgeError):
                app.promote(api, app.DEFAULTS, 'x', [card()])
            self.assertNotIn('setDueDate', [c.args[0] for c in api.call.call_args_list])
        api = self.promotion_api(word='changed')
        with self.assertRaises(app.BridgeError):
            app.promote(api, app.DEFAULTS, 'x', [card()])
        api = Mock(); api.call.side_effect = [[card() | {'fields': {'Word': {'value': 'x'}}}], [1]]
        with self.assertRaises(app.BridgeError):
            app.promote(api, app.DEFAULTS, 'x', [card()])
        self.assertEqual(api.call.call_count, 2)

    def test_unsuspend_failure_does_not_set_due_date(self):
        api = Mock()
        current = card(queue=-1) | {'fields': {'Word': {'value': 'x'}}}
        api.call.side_effect = [[current], [], None, [current], []]
        with self.assertRaises(app.BridgeError):
            app.promote(api, app.DEFAULTS, 'x', [card(queue=-1)], unsuspend=True)
        self.assertNotIn('setDueDate', [c.args[0] for c in api.call.call_args_list])

    def test_unsuspend_return_values_use_actual_state(self):
        for value in (None, True, False):
            with self.subTest(value=value):
                current = card(queue=-1) | {'fields': {'Word': {'value': 'x'}}}
                api = Mock()
                api.call.side_effect = [[current], [], value, [current | {'queue': 0}], [], True]
                app.promote(api, app.DEFAULTS, 'x', [card(queue=-1)], unsuspend=True)
                self.assertEqual(api.call.call_args, call('setDueDate', cards=[1], days='0'))

    def test_state_change_during_unsuspend_stops_promotion(self):
        current = card(queue=-1) | {'fields': {'Word': {'value': 'x'}}}
        for changed in (current | {'queue': 2, 'type': 2}, current | {'deckName': 'Other'},
                        current | {'fields': {'Word': {'value': 'changed'}}}):
            api = Mock(); api.call.side_effect = [[current], [], None, [changed]]
            with self.assertRaises(app.BridgeError):
                app.promote(api, app.DEFAULTS, 'x', [card(queue=-1)], unsuspend=True)
            self.assertNotIn('setDueDate', [c.args[0] for c in api.call.call_args_list])

    def test_set_due_failure_is_not_retried(self):
        api = Mock()
        api.call.side_effect = [[card() | {'fields': {'Word': {'value': 'x'}}}], [], False]
        with self.assertRaises(app.BridgeError):
            app.promote(api, app.DEFAULTS, 'x', [card()])
        self.assertEqual(api.call.call_count, 3)

    def test_normalization(self):
        self.assertEqual(app.normalize('<b>Tour</b>nament&nbsp;', markup=True), 'tournament')
        self.assertNotEqual(app.normalize('tournaments'), 'tournament')
        self.assertNotEqual(app.normalize('Word', True), 'word')
        self.assertEqual(app.normalize('e\u0301'), app.normalize('é'))

    def test_lookup_exact_and_scope(self):
        api = Mock()
        api.call.side_effect = [[100, 101], [
            {'noteId': 100, 'cards': [1, 2], 'fields': {'Word': {'value': '<b>Tour</b>nament'}}},
            {'noteId': 101, 'cards': [3], 'fields': {'Word': {'value': 'tournaments'}}}],
            [card(), card(2, deck='Other')]]
        config = app.DEFAULTS | {'deck': 'English'}
        self.assertEqual([c['cardId'] for c in app.lookup(api, config, 'tournament')], [1])
        self.assertEqual([c.args[0] for c in api.call.call_args_list], ['findNotes', 'notesInfo', 'cardsInfo'])
        self.assertEqual(api.call.call_args, call('cardsInfo', cards=[1, 2]))

    def test_missing_field(self):
        api = Mock()
        api.call.side_effect = [[100], [{'fields': {'Front': {'value': 'x'}}}]]
        with self.assertRaises(app.BridgeError):
            app.lookup(api, app.DEFAULTS, 'x')

    def test_no_match(self):
        api = Mock()
        api.call.return_value = []
        self.assertEqual(app.lookup(api, app.DEFAULTS, 'missing'), [])

    def test_lookup_batches_cards_and_preserves_order_and_scope(self):
        api = Mock()
        notes = [{'noteId': i, 'cards': [i], 'fields': {'Word': {'value': 'x'}}}
                 for i in range(501)]
        def respond(action, **params):
            if action == 'findNotes':
                return list(range(501))
            if action == 'notesInfo':
                return [notes[i] for i in params['notes']]
            if action == 'cardsInfo':
                return [None if i == 1 else card(i, deck='Other' if i == 2 else 'English::Child')
                        for i in reversed(params['cards'])]
            self.fail(f'unexpected call: {action}')
        api.call.side_effect = respond
        cards = app.lookup(api, app.DEFAULTS | {'deck': 'English', 'lemmatize': False}, 'x')
        self.assertEqual([c['cardId'] for c in cards], [0] + list(range(3, 501)))
        self.assertEqual([len(c.kwargs['cards']) for c in api.call.call_args_list
                          if c.args[0] == 'cardsInfo'], [250, 250, 1])

    def test_review_learning_buried_unchanged(self):
        api = Mock()
        for c in [card(kind=2, queue=2), card(kind=1, queue=1), card(queue=-2), card(kind=2, queue=-1)]:
            app.promote(api, app.DEFAULTS, 'x', [c], unsuspend=True)
        api.call.assert_not_called()

    def test_suspended_requires_flag(self):
        api = Mock()
        app.promote(api, app.DEFAULTS, 'x', [card(queue=-1)])
        api.call.assert_not_called()
        api = self.promotion_api(card(queue=-1))
        app.promote(api, app.DEFAULTS, 'x', [card(queue=-1)], unsuspend=True)
        self.assertEqual([c.args[0] for c in api.call.call_args_list], ['cardsInfo', 'findCards', 'unsuspend', 'cardsInfo', 'findCards', 'setDueDate'])

    def test_duplicate_requires_selection(self):
        api = Mock()
        with self.assertRaises(app.BridgeError):
            app.promote(api, app.DEFAULTS, 'x', [card(), card(2)])
        api.call.assert_not_called()
        api = self.promotion_api(card(2))
        app.promote(api, app.DEFAULTS, 'x', [card(), card(2)], card_id=2)
        self.assertEqual(api.call.call_args, call('setDueDate', cards=[2], days='0'))

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
        with self.assertRaisesRegex(app.BridgeError, 'unsupported action'):
            client.call('setDueDate', cards=[1], days='0')
        client.opener.open.side_effect = TimeoutError()
        with self.assertRaises(app.BridgeError):
            client.call('version')


if __name__ == '__main__':
    unittest.main()
