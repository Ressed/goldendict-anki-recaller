"""Expose guarded insertion into the current study queue through AnkiConnect."""
import sys
import json
from urllib.parse import urlsplit
from aqt import gui_hooks
from .matching import normalize


def gdPromoteNew(self, cardId, word, field, deck, caseSensitive=False, unsuspend=False, studyDeck=None):
    if type(cardId) is not int or type(unsuspend) is not bool or type(caseSensitive) is not bool:
        raise ValueError('Invalid action parameters')
    col = self.collection()
    card = col.get_card(cardId)
    if card.type != 0 or card.odid or card.queue not in (0, -1):
        raise ValueError('仅可插入普通牌组中的新卡；卡片状态可能已变化。')
    if col.decks.name(card.did) != deck:
        raise ValueError('牌组已变化，请重新查词。')
    note = card.note()
    if field not in note or normalize(note[field], caseSensitive, markup=True) != normalize(word, caseSensitive):
        raise ValueError('词头已变化，请重新查词。')
    scope = studyDeck or deck.split('::')[0]
    if deck != scope and not deck.startswith(scope + '::'):
        raise ValueError('卡片不属于指定的父牌组。')
    if col.decks.current()['name'] != scope or col.decks.current()['dyn']:
        raise ValueError('请先在 Anki 选择父牌组 ' + scope + '，再点击插队。')
    window = self.window()
    if window.state == 'review' and window.reviewer.state == 'transition':
        raise ValueError('Anki 正在提交作答，请稍后重新查询。')
    if card.queue == -1 and not unsuspend:
        raise ValueError('暂停卡需明确勾选解除暂停。')
    from .priority_queue import install, get_plan
    install()
    plan = get_plan(col.sched)
    # Capture the existing random selection before unsuspension resets queues.
    if not plan.active():
        native = col.sched._gd_native_get(fetch_limit=10000)
        order = [q.card.id for q in native.cards if q.queue == 0]
        if len(order) != native.new_count:
            raise ValueError('无法完整读取当前新卡队列，未插队。')
        plan.data = dict(day=col.sched.today, deck=col.decks.current()['id'], order=order, pinned=[])
    if card.queue == -1:
        col.sched.unsuspend_cards([cardId])
    result = plan.promote(cardId, scope)
    if window.state == 'review':
        window.reviewer.nextCard()
    else:
        window.moveToState('review')
    return result


gdPromoteNew.api = True
gdPromoteNew.versions = []


def install_cors_compat(web):
    """Repair GD's rewritten Origin only for marked bridge actions and an opted-in origin."""
    cls = web.WebServer
    original = cls.allowOrigin
    if getattr(original, '_gd_compat', False):
        return

    def allow_origin(self, req):
        try:
            body = json.loads(req.body)
            origin = urlsplit(req.headers.get(b'origin', b'').decode())
            if (req.method == b'POST' and isinstance(body, dict)
                    and body.get('gdBridgeOrigin') == 'gdlookup://localhost'
                    and body.get('action') in ('requestPermission', 'gdPromoteNew')
                    and origin.scheme == 'http'
                    and origin.hostname in ('127.0.0.1', 'localhost', '::1')
                    and origin.port == web.util.setting('webBindPort')
                    and not origin.username and not origin.password
                    and not origin.path and not origin.query and not origin.fragment
                    and 'gdlookup://localhost' in web.util.setting('webCorsOriginList')):
                return True, 'gdlookup://localhost'
        except (ValueError, TypeError, UnicodeError):
            pass
        return original(self, req)

    allow_origin._gd_compat = True
    cls.allowOrigin = allow_origin


def register():
    from .priority_queue import install
    install()
    # Anki add-on folder names vary; patch only the actual AnkiConnect class.
    for module in list(sys.modules.values()):
        cls = getattr(module, '__dict__', {}).get('AnkiConnect')
        if isinstance(cls, type) and all(hasattr(cls, name) for name in ('handler', 'cardsInfo', 'collection')):
            cls.gdPromoteNew = gdPromoteNew
            web = getattr(module, 'web', None)
            if web is not None and hasattr(web, 'WebServer'):
                install_cors_compat(web)


gui_hooks.profile_did_open.append(register)
