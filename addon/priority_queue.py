"""Daily, profile-local new-card plan over Anki's native reviewer scheduler."""
import hashlib
import json
from pathlib import Path
from anki.scheduler.v3 import Scheduler, QueuedCards

KEY = '_gd_priority_plan'
MAX_FETCH = 10000


class Plan:
    def __init__(self, col, directory=None):
        self.col = col
        directory = Path(directory or Path(__file__).with_name('user_files'))
        directory.mkdir(parents=True, exist_ok=True)
        self.path = directory / (hashlib.sha256(str(col.path).encode()).hexdigest() + '.json')
        self.data = None
        if self.path.exists():
            try:
                data = json.loads(self.path.read_text(encoding='utf-8'))
                if isinstance(data, dict) and all(k in data for k in ('day', 'deck', 'order', 'pinned')):
                    self.data = data
            except (OSError, ValueError):
                # A damaged local plan must not prevent normal Anki review.
                pass

    def save(self):
        temp = self.path.with_suffix('.tmp')
        temp.write_text(json.dumps(self.data), encoding='utf-8')
        temp.replace(self.path)

    def active(self):
        return (self.data and self.data['day'] == self.col.sched.today
                and self.data['deck'] == self.col.decks.current()['id'])

    def live(self):
        result = []
        if not self.active():
            return result
        scope = self.col.decks.name(self.data['deck'])
        for cid in self.data['order']:
            try:
                card = self.col.get_card(cid)
            except Exception:
                continue
            name = self.col.decks.name(card.did)
            if card.type == 0 and card.queue == 0 and not card.odid and (name == scope or name.startswith(scope + '::')):
                result.append(cid)
        return result

    def budget(self):
        deck = self.col.decks.current()
        config = self.col.decks.config_dict_for_deck_id(deck['id'])
        limit = deck.get('newLimit')
        if limit is None:
            limit = config['new']['perDay']
        override = deck.get('newLimitToday')
        if override and override['today'] == self.col.sched.today:
            limit = override['limit']
        day, count = deck['newToday']
        return limit, count if day == self.col.sched.today else 0

    def promote(self, cid, scope):
        col = self.col
        deck = col.decks.current()
        if deck['dyn'] or deck['name'] != scope:
            raise ValueError('请先在 Anki 选择并进入父牌组 ' + scope + '，再点击插队。')
        if not self.active():
            native = col.sched._gd_native_get(fetch_limit=MAX_FETCH)
            order = [q.card.id for q in native.cards if q.queue == QueuedCards.NEW]
            if len(order) != native.new_count:
                raise ValueError('当前待学队列过大，无法完整读取；未插队。')
            self.data = dict(day=col.sched.today, deck=deck['id'], order=order, pinned=[])
        order = self.live()
        already = cid in order
        order = [cid] + [x for x in order if x != cid]
        limit, studied = self.budget()
        removed = []
        if not already and studied < limit:
            while studied + len(order) > limit and len(order) > 1:
                removed.append(order.pop())
        self.data['order'] = order
        self.data['limit'] = limit
        self.data['pinned'] = [cid] + [x for x in self.data['pinned'] if x != cid and x in order]
        self.save()
        return dict(message='已插入当前学习队列首位' +
                    ('；今日额度已用完，本卡额外加入' if studied >= limit and not already else '') +
                    (f'；已移出末尾 {len(removed)} 张未学新卡' if removed else ''),
                    cardId=cid, displaced=removed, newCount=len(order), mode='queue-first')

    def queued(self, native, fetch_limit):
        order = self.live()
        limit, studied = self.budget()
        if self.data.get('limit', limit) != limit:
            # A mid-day edit of the parent's total limit should remain useful.
            capacity = max(0, limit - studied)
            pinned = [x for x in self.data['pinned'] if x in order]
            if studied >= limit:
                capacity = max(capacity, len(pinned))
            order = order[:capacity]
            for item in native.cards:
                if len(order) >= capacity:
                    break
                if item.queue == QueuedCards.NEW and item.card.id not in order:
                    order.append(item.card.id)
            self.data.update(order=order, pinned=[x for x in pinned if x in order], limit=limit)
            self.save()
        pinned = [cid for cid in self.data['pinned'] if cid in order]
        rest = [cid for cid in order if cid not in pinned]
        queued = {}
        for cid in order:
            card = self.col.get_card(cid)
            states = self.col._backend.get_scheduling_states(cid)
            queued[cid] = QueuedCards.QueuedCard(
                card=card._to_backend_card(), queue=QueuedCards.NEW, states=states)
            queued[cid].context.deck_name = self.col.decks.name(card.did)
            queued[cid].context.seed = card.nid
        output = [queued[cid] for cid in pinned]
        for item in native.cards:
            if item.queue == QueuedCards.NEW:
                if rest:
                    output.append(queued[rest.pop(0)])
            else:
                output.append(item)
        output.extend(queued[cid] for cid in rest)
        result = QueuedCards(new_count=len(order), learning_count=native.learning_count,
                             review_count=native.review_count)
        result.cards.extend(output[:fetch_limit])
        return result


def get_plan(scheduler):
    if not hasattr(scheduler, KEY):
        setattr(scheduler, KEY, Plan(scheduler.col))
    return getattr(scheduler, KEY)


def install():
    if hasattr(Scheduler, '_gd_native_get'):
        return
    Scheduler._gd_native_get = Scheduler.get_queued_cards
    original_answer = Scheduler.answer_card

    def get(self, *, fetch_limit=1, intraday_learning_only=False):
        plan = get_plan(self)
        if not plan.active() or intraday_learning_only:
            return self._gd_native_get(fetch_limit=fetch_limit, intraday_learning_only=intraday_learning_only)
        native = self._gd_native_get(fetch_limit=MAX_FETCH)
        return plan.queued(native, fetch_limit)

    def answer(self, input):
        plan = get_plan(self)
        if not plan.active():
            return original_answer(self, input)
        # Native answers require the actual backend queue head. An ordinary card
        # update invalidates that queue; answering then uses native scheduling,
        # stats, siblings and revlog, without claiming a different card was first.
        undo = self.col.add_custom_undo_entry('回答插队学习计划中的新卡')
        self.col.update_card(self.col.get_card(input.card_id))
        try:
            return original_answer(self, input)
        finally:
            self.col.merge_undo_entries(undo)

    Scheduler.get_queued_cards = get
    Scheduler.answer_card = answer
