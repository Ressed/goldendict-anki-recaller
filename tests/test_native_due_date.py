"""Optional native set_due_date checks, using disposable Anki collections only."""
import os
from pathlib import Path
import sys
import tempfile
import unittest


@unittest.skipUnless(os.environ.get('ANKI_APP_PACKAGES'), 'Optional installed Anki runtime')
class NativeDueDateTests(unittest.TestCase):
    def test_promotion_search_and_write_against_native_anki(self):
        sys.path.insert(0, os.environ['ANKI_APP_PACKAGES'])
        from anki.collection import Collection
        from goldendict_anki.cli import BridgeError, DEFAULTS, promote_card
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as directory:
            col = Collection(str(Path(directory) / 'test.anki2'))
            try:
                did = col.decks.id('test')
                ids = []
                for word in ('ordinary', 'filtered'):
                    note = col.new_note(col.models.by_name('Basic'))
                    note['Front'] = word; col.add_note(note, did)
                    ids.append(note.cards()[0].id)
                filtered_did = col.decks.new_filtered('Filtered')
                filtered = col.get_card(ids[1])
                filtered.odid = did; filtered.did = filtered_did
                col.update_card(filtered)

                class NativeClient:
                    def call(self, action, **params):
                        if action == 'cardsInfo':
                            c = col.get_card(params['cards'][0])
                            # Match AnkiConnect versions that omit odid, so the
                            # production search actually reaches Anki's parser.
                            return [dict(cardId=c.id, type=c.type, queue=c.queue,
                                         deckName=col.decks.name(c.did),
                                         fields={'Front': {'value': c.note()['Front']}})]
                        if action == 'findCards':
                            return col.find_cards(params['query'])
                        if action == 'unsuspend':
                            col.sched.unsuspend_cards(params['cards'])
                            # Installed AnkiConnect.unsuspend has no return statement.
                            return None
                        if action == 'setDueDate':
                            col.sched.set_due_date(params['cards'], params['days'], config_key=None)
                            return True
                        raise AssertionError(action)

                config = DEFAULTS | {'field': 'Front'}
                col.sched.suspend_cards([ids[0]])
                self.assertEqual(col.get_card(ids[0]).queue, -1)
                promote_card(NativeClient(), config, ids[0], 'ordinary', 'test', unsuspend=True)
                result = col.get_card(ids[0])
                self.assertEqual((result.type, result.queue, result.due), (2, 2, col.sched.today))
                before = col.get_card(ids[1])._to_backend_card()
                with self.assertRaisesRegex(BridgeError, '筛选牌组'):
                    promote_card(NativeClient(), config, ids[1], 'filtered', 'Filtered')
                self.assertEqual(col.get_card(ids[1])._to_backend_card(), before)
            finally:
                col.close()

    def test_new_card_becomes_today_review_without_touching_other_cards(self):
        sys.path.insert(0, os.environ['ANKI_APP_PACKAGES'])
        from anki.collection import Collection
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as directory:
            col = Collection(str(Path(directory) / 'test.anki2'))
            try:
                did = col.decks.id('test')
                ids = []
                for word in ('selected', 'untouched'):
                    note = col.new_note(col.models.by_name('Basic'))
                    note['Front'] = word; col.add_note(note, did)
                    ids.append(note.cards()[0].id)
                other_before = col.get_card(ids[1])._to_backend_card()
                # Exactly the scheduler call used by AnkiConnect.setDueDate.
                col.sched.set_due_date([ids[0]], '0', config_key=None)
                selected = col.get_card(ids[0])
                self.assertEqual((selected.type, selected.queue), (2, 2))
                self.assertEqual(selected.due, col.sched.today)
                self.assertEqual(selected.reps, 0)
                self.assertEqual(selected.did, did)
                self.assertEqual(col.get_card(ids[1])._to_backend_card(), other_before)
            finally:
                col.close()


if __name__ == '__main__':
    unittest.main()
