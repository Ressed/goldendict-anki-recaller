"""Integration tests against installed Anki 26.8.1; only disposable collections."""
import importlib.util
from pathlib import Path
import sys
import os
import tempfile
import unittest
import types
from unittest.mock import Mock, patch

if os.environ.get('ANKI_APP_PACKAGES'):
    sys.path.insert(0, os.environ['ANKI_APP_PACKAGES'])
from anki.collection import Collection
spec = importlib.util.spec_from_file_location('priority_queue', Path(__file__).resolve().parents[1] / 'addon/priority_queue.py')
pq = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pq)
pq.install()


class QueueTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=Path(__file__).parent)
        self.col = Collection(str(Path(self.temp.name) / 'test.anki2'))
        self.root = self.col.decks.id('eggrolls')
        self.high = self.col.decks.id('eggrolls::01k')
        self.low = self.col.decks.id('eggrolls::60k')
        for did, limit in [(self.root, 2), (self.high, 10), (self.low, 0)]:
            deck = self.col.decks.get(did); deck['newLimit'] = limit; self.col.decks.save(deck)
        self.high_ids = [self.add(self.high, 'high' + str(i)) for i in range(5)]
        self.low_ids = [self.add(self.low, 'low' + str(i)) for i in range(3)]
        self.col.decks.select(self.root)
        self.plan = pq.Plan(self.col, self.temp.name)
        setattr(self.col.sched, pq.KEY, self.plan)

    def add(self, did, word):
        note = self.col.new_note(self.col.models.by_name('Basic'))
        note['Front'] = word; self.col.add_note(note, did)
        return note.cards()[0].id

    def tearDown(self):
        self.col.close(); self.temp.cleanup()

    def queue(self):
        return self.col.sched.get_queued_cards(fetch_limit=100)

    def answer(self, rating=3):
        q = self.queue().cards[0]
        card = self.col.get_card(q.card.id); card.start_timer()
        self.col.sched.answer_card(self.col.sched.build_answer(card=card, states=q.states, rating=rating))

    def test_replace_tail_zero_child_and_answer(self):
        before = [x.card.id for x in self.queue().cards]
        result = self.plan.promote(self.low_ids[0], 'eggrolls')
        self.assertEqual(result['displaced'], [before[-1]])
        self.assertEqual([x.card.id for x in self.queue().cards], [self.low_ids[0], before[0]])
        self.assertEqual(self.queue().new_count, 2)
        self.answer()
        self.assertEqual(self.col.get_card(self.low_ids[0]).type, 2)
        self.assertEqual(self.queue().new_count, 1)
        self.assertEqual(self.queue().cards[0].card.id, before[0])
        self.assertEqual(self.col.get_card(before[-1]).queue, 0)
        self.assertEqual(self.col.decks.get(self.low)['newLimit'], 0)
        self.assertEqual(self.col.db.scalar('select count(*) from revlog'), 1)

    def test_existing_and_repeat_do_not_evict(self):
        before = [x.card.id for x in self.queue().cards]
        for _ in range(2):
            result = self.plan.promote(before[-1], 'eggrolls')
            self.assertEqual(result['displaced'], [])
            self.assertEqual(self.queue().new_count, 2)
            self.assertEqual(self.queue().cards[0].card.id, before[-1])

    def test_exhausted_adds_extra(self):
        self.answer(); self.answer()
        self.assertEqual(self.queue().new_count, 0)
        self.plan.promote(self.low_ids[0], 'eggrolls')
        self.assertEqual(self.queue().new_count, 1)
        self.answer()
        self.assertEqual(self.col.decks.get(self.root)['newToday'][1], 3)

    def test_again_undo_and_restart(self):
        self.plan.promote(self.low_ids[0], 'eggrolls')
        self.answer(rating=0)
        self.assertEqual(self.col.get_card(self.low_ids[0]).type, 1)
        self.assertEqual(self.queue().new_count, 1)
        self.col.undo()
        self.assertEqual(self.col.get_card(self.low_ids[0]).type, 0)
        self.assertEqual(self.queue().cards[0].card.id, self.low_ids[0])
        plan = pq.Plan(self.col, self.temp.name)
        setattr(self.col.sched, pq.KEY, plan)
        self.assertEqual(self.queue().cards[0].card.id, self.low_ids[0])

    def test_multiple_priorities_and_day_scope(self):
        for cid in self.low_ids:
            self.plan.promote(cid, 'eggrolls')
            self.assertEqual(self.queue().cards[0].card.id, cid)
            self.assertEqual(self.queue().new_count, 2)
        self.plan.data['day'] -= 1
        self.assertFalse(self.plan.active())
        self.assertTrue(all(q.card.id in self.high_ids for q in self.queue().cards))

    def test_different_selected_deck_rejected(self):
        self.col.decks.select(self.high)
        with self.assertRaises(ValueError):
            self.plan.promote(self.low_ids[0], 'eggrolls')

    def test_random_collection_preserves_remaining_selection(self):
        config = self.col.decks.config_dict_for_deck_id(self.root)
        config['newGatherPriority'] = 4
        config['newSortOrder'] = 4
        self.col.decks.update_config(config)
        before = [q.card.id for q in self.queue().cards]
        self.plan.promote(self.low_ids[0], 'eggrolls')
        self.assertEqual([q.card.id for q in self.queue().cards], [self.low_ids[0], before[0]])
        self.answer()
        self.assertEqual(self.queue().cards[0].card.id, before[0])
        self.answer()
        self.assertEqual(self.queue().new_count, 0)
        self.assertEqual(self.col.decks.config_dict_for_deck_id(self.root)['newSortOrder'], 4)

    def test_native_review_after_new_plan_exhausted(self):
        review = self.col.get_card(self.high_ids[-1])
        review.type = 2; review.queue = 2; review.due = self.col.sched.today
        review.ivl = 1; self.col.update_card(review)
        config = self.col.decks.config_dict_for_deck_id(self.root)
        config['newMix'] = 2; self.col.decks.update_config(config)
        self.plan.promote(self.low_ids[0], 'eggrolls')
        self.answer(); self.answer()
        self.assertEqual(self.queue().cards[0].card.id, review.id)
        self.answer()
        self.assertEqual(self.col.db.scalar('select count(*) from revlog'), 3)

    def test_public_action_displays_card_and_validates(self):
        aqt = types.ModuleType('aqt')
        aqt.gui_hooks = types.SimpleNamespace(profile_did_open=[])
        spec = importlib.util.spec_from_file_location('integration_addon', Path(__file__).resolve().parents[1] / 'addon/__init__.py',
                    submodule_search_locations=[str(Path(__file__).resolve().parents[1] / 'addon')])
        module = importlib.util.module_from_spec(spec)
        sys.modules['integration_addon'] = module
        with patch.dict(sys.modules, {'aqt': aqt}):
            spec.loader.exec_module(module)
        window = Mock(state='review'); window.reviewer.state = 'question'
        api = Mock(); api.collection.return_value = self.col; api.window.return_value = window
        cid = self.low_ids[0]
        params = dict(cardId=cid, word='low0', field='Front', deck='eggrolls::60k', studyDeck='eggrolls')
        with self.assertRaises(ValueError):
            module.gdPromoteNew(api, **(params | {'word': 'wrong'}))
        result = module.gdPromoteNew(api, **params)
        self.assertEqual(result['mode'], 'queue-first')
        self.assertEqual(self.queue().cards[0].card.id, cid)
        window.reviewer.nextCard.assert_called_once()

    def test_parent_limit_edit_and_today_override(self):
        self.plan.promote(self.low_ids[0], 'eggrolls')
        deck = self.col.decks.get(self.root)
        deck['newLimit'] = 3; self.col.decks.save(deck)
        self.assertEqual(self.queue().new_count, 3)
        self.assertEqual(self.queue().cards[0].card.id, self.low_ids[0])
        deck['newLimitToday'] = {'today': self.col.sched.today, 'limit': 1}
        self.col.decks.save(deck)
        self.assertEqual(self.queue().new_count, 1)
        self.assertEqual(self.queue().cards[0].card.id, self.low_ids[0])


if __name__ == '__main__':
    unittest.main()
