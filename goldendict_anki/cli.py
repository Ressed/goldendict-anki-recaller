"""Look up existing Anki cards from GoldenDict. Python 3.10+, Jinja2 templates."""
import argparse
from html.parser import HTMLParser
import json
import os
from pathlib import Path
import sys
import unicodedata
import urllib.error
import urllib.parse
import urllib.request


class BridgeError(Exception):
    pass


class PlainText(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []

    def handle_data(self, data):
        self.parts.append(data)

    def handle_starttag(self, tag, attrs):
        if tag in ('br', 'div', 'p'):
            self.parts.append(' ')

    def handle_endtag(self, tag):
        if tag in ('div', 'p'):
            self.parts.append(' ')


def plain(value):
    parser = PlainText()
    parser.feed(value or '')
    return ' '.join(''.join(parser.parts).split())


def normalize(value, case_sensitive=False, markup=False):
    if markup:
        value = plain(value)
    value = ' '.join(unicodedata.normalize('NFC', value).split())
    return value if case_sensitive else value.casefold()


def quote(value):
    for char in ('\\', '"', '*', '_'):
        value = value.replace(char, '\\' + char)
    return '"' + value + '"'


class Client:
    def __init__(self, config):
        self.config = config
        url = urllib.parse.urlsplit(config['url'])
        if url.scheme != 'http' or url.hostname not in ('localhost', '127.0.0.1', '::1') or url.username or url.password:
            raise BridgeError('AnkiConnect 地址必须是本机 HTTP 地址。')
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def call(self, action, **params):
        body = {'action': action, 'version': 6, 'params': params}
        key = os.environ.get('ANKICONNECT_API_KEY') or self.config.get('api_key')
        if key:
            body['key'] = key
        request = urllib.request.Request(self.config['url'], json.dumps(body).encode('utf-8'), {'Content-Type': 'application/json'})
        try:
            with self.opener.open(request, timeout=self.config['timeout']) as response:
                reply = json.load(response)
        except (OSError, urllib.error.URLError, ValueError) as exc:
            raise BridgeError('连接失败或响应无效。请打开 Anki 并检查 AnkiConnect。若刚执行提队，结果可能已生效，请先重新查询，勿自动重试。') from exc
        if not isinstance(reply, dict) or 'error' not in reply or 'result' not in reply:
            raise BridgeError('AnkiConnect 响应格式不正确。')
        if reply['error']:
            raise BridgeError(f"{action}: {reply['error']}")
        return reply['result']


DEFAULTS = dict(url='http://127.0.0.1:8765', deck=None, field='Word',
                sense_fields=['DefinitionTR', 'Definition'], label_fields=['PoS', 'Label'],
                lemmatize=True, case_sensitive=False, timeout=10, api_key=None)


def load_config(path):
    config = DEFAULTS.copy()
    config['sense_fields'] = list(DEFAULTS['sense_fields'])
    config['label_fields'] = list(DEFAULTS['label_fields'])
    if path.exists():
        data = json.loads(path.read_text(encoding='utf-8-sig'))
        if not isinstance(data, dict) or set(data) - set(DEFAULTS):
            raise BridgeError('配置必须是 JSON 对象，且不能包含未知配置项。')
        config.update(data)
    for key in ('url', 'field'):
        if not isinstance(config[key], str) or not config[key].strip():
            raise BridgeError(f'配置 {key} 必须为非空字符串。')
    if config['deck'] is not None and (not isinstance(config['deck'], str) or not config['deck'].strip()):
        raise BridgeError('deck 必须为非空字符串或 null。')
    for key in ('sense_fields', 'label_fields'):
        if (not isinstance(config[key], list) or not config[key]
                or any(not isinstance(item, str) or not item.strip() for item in config[key])):
            raise BridgeError(f'配置 {key} 必须是非空字段名数组。')
    if (type(config['case_sensitive']) is not bool or type(config['lemmatize']) is not bool
            or type(config['timeout']) not in (int, float) or not 0 < config['timeout'] <= 120):
        raise BridgeError('case_sensitive 和 lemmatize 必须为布尔值；timeout 必须在 0～120 秒之间。')
    return config


def lookup(client, config, word, full_scan=False):
    from .word_forms import lookup_forms
    forms = lookup_forms(word, config['lemmatize'])
    scope = 'deck:' + quote(config['deck']) if config['deck'] else ''
    field_name = quote(config['field'])[1:-1]
    clauses = [f'"{field_name}:*{quote(form)[1:-1]}*"' for form in forms]
    form_query = clauses[0] if len(clauses) == 1 else '(' + ' OR '.join(clauses) + ')'
    query = scope if full_scan else f'{scope} {form_query}'.strip()
    ids = client.call('findNotes', query=query)
    matched_by_form = {normalize(form, config['case_sensitive']): [] for form in forms}
    field_seen = False
    for offset in range(0, len(ids), 250):
        for note in client.call('notesInfo', notes=ids[offset:offset + 250]):
            field = note.get('fields', {}).get(config['field'])
            if field is not None:
                field_seen = True
                actual = normalize(field['value'], config['case_sensitive'], markup=True)
                if actual in matched_by_form:
                    matched_by_form[actual].append(note)
    if ids and not field_seen:
        raise BridgeError(f"目标笔记没有字段 {config['field']}，请检查字段名（区分大小写）。")
    matched = [(form, note) for form in forms
               for note in matched_by_form[normalize(form, config['case_sensitive'])]]
    cards = []
    for matched_form, note in matched:
        nid = note['noteId']
        note_fields = {name: data.get('value', '') for name, data in note.get('fields', {}).items()}
        cids = client.call('findCards', query=f'{scope} nid:{int(nid)}'.strip())
        if cids:
            for card in client.call('cardsInfo', cards=cids):
                if card:
                    item = dict(card)
                    item['_fields'] = note_fields
                    item['_matched_word'] = matched_form
                    cards.append(item)
    deck = config['deck']
    return [c for c in cards if not deck or c['deckName'] == deck or c['deckName'].startswith(deck + '::')]


def state(card):
    base = {0: '新卡', 1: '学习中', 2: '复习', 3: '重新学习'}.get(card['type'], '未知')
    overlay = {-1: '已暂停', -2: '已手动埋藏', -3: '已自动埋藏', 4: '预览'}.get(card['queue'])
    return f'{overlay} / {base}' if overlay else base


def card_summary(card, config):
    fields = card.get('_fields') or {name: data.get('value', '')
                                   for name, data in card.get('fields', {}).items()}
    senses = [plain(fields.get(name, '')) for name in config['sense_fields']]
    labels = [plain(fields.get(name, '')) for name in config['label_fields']]
    return {'senses': [v for v in senses if v], 'labels': [v for v in labels if v],
            'front': face_text(card.get('question', '')),
            'back': face_text(card.get('answer', ''))}


class FaceText(PlainText):
    """Text preview only: never embed executable Anki card markup."""
    def __init__(self):
        super().__init__()
        self.ignored = []

    def handle_starttag(self, tag, attrs):
        if tag in ('style', 'script', 'svg'):
            self.ignored.append(tag)
        if not self.ignored:
            super().handle_starttag(tag, attrs)

    def handle_endtag(self, tag):
        if self.ignored:
            if tag == self.ignored[-1]:
                self.ignored.pop()
            return
        super().handle_endtag(tag)

    def handle_data(self, data):
        if not self.ignored:
            super().handle_data(data)


def face_text(markup):
    parser = FaceText()
    parser.feed(markup or '')
    value = ' '.join(''.join(parser.parts).split())
    return value[:1800] + ('…' if len(value) > 1800 else '')


def promote(client, config, word, cards, card_id=None, unsuspend=False):
    selected = [c for c in cards if c['cardId'] == card_id] if card_id is not None else cards
    if card_id is not None and not selected:
        raise BridgeError('--card-id 不属于本次精确匹配结果。')
    eligible = [c for c in selected if c['type'] == 0 and (c['queue'] == 0 or (unsuspend and c['queue'] == -1))]
    if not eligible:
        return '没有可提队的新卡；已学卡、埋藏卡和未授权解除暂停的卡保持原状。'
    if len(eligible) > 1:
        raise BridgeError('匹配到多张可提队卡；请用 --card-id 指定一张。')
    card = eligible[0]
    return promote_card(client, config, card['cardId'], card.get('_matched_word', word),
                        card['deckName'], unsuspend)


def promote_card(client, config, card_id, word, deck, unsuspend=False):
    """Revalidate a stale lookup, then use only standard AnkiConnect actions."""
    if type(card_id) is not int or type(unsuspend) is not bool or not isinstance(word, str) or not isinstance(deck, str):
        raise BridgeError('无效的提队参数。')
    scope = config['deck']
    if scope and deck != scope and not deck.startswith(scope + '::'):
        raise BridgeError('卡片不属于配置的牌组。')
    def checked_card():
        current = client.call('cardsInfo', cards=[card_id])
        if not current or not current[0] or current[0].get('cardId') != card_id:
            raise BridgeError('卡片已不存在，请重新查词。')
        card = current[0]
        if card['deckName'] != deck:
            raise BridgeError('牌组已变化，请重新查词。')
        field = card.get('fields', {}).get(config['field'])
        if field is None or normalize(field['value'], config['case_sensitive'], markup=True) != normalize(word, config['case_sensitive']):
            raise BridgeError('词头已变化，请重新查词。')
        if card['type'] != 0 or card['queue'] not in (0, -1) or card.get('odid', 0):
            raise BridgeError('仅可处理普通牌组中的未学新卡；卡片状态可能已变化。')
        # cardsInfo does not expose odid on all AnkiConnect versions.
        if client.call('findCards', query=f'cid:{card_id} deck:filtered'):
            raise BridgeError('筛选牌组中的卡片不可提队。')
        return card

    card = checked_card()
    if card['queue'] == -1:
        if not unsuspend:
            raise BridgeError('暂停卡需明确勾选解除暂停。')
        # Some AnkiConnect versions perform the change but return null.
        client.call('unsuspend', cards=[card_id])
        card = checked_card()
        if card['queue'] != 0:
            raise BridgeError('卡片仍处于暂停状态，未设置到期日，请重新查词后核对。')
    if client.call('setDueDate', cards=[card_id], days='0') is not True:
        raise BridgeError('设置到期日未确认，请重新查词后核对。')
    return f'已设为今天到期的复习卡（绿卡）；仍受复习限额影响（card {card_id}）'


def render(word, cards, message='', error=False, fmt='html', config=None, bridge=None):
    config = config or DEFAULTS
    if fmt == 'json':
        rendered_cards = []
        for card in cards:
            item = {k: card[k] for k in ('cardId', 'note', 'deckName', 'type', 'queue', 'due')}
            item.update(headword=card.get('_matched_word', word), state=state(card),
                        **card_summary(card, config))
            rendered_cards.append(item)
        return json.dumps(dict(word=word, cards=rendered_cards, message=message, error=error), ensure_ascii=False)

    matched_words = list(dict.fromkeys(c.get('_matched_word', word) for c in cards))
    lemmas = [value for value in matched_words
              if normalize(value, config['case_sensitive']) != normalize(word, config['case_sensitive'])]
    exact_found = any(normalize(value, config['case_sensitive']) == normalize(word, config['case_sensitive'])
                      for value in matched_words)
    matched_word = matched_words[0] if matched_words else word
    heading = f'Anki · {word}' + (f'（同时查询原形 {" / ".join(lemmas)}）' if lemmas and exact_found
                                  else f' → {matched_word}' if lemmas else '')
    status = message or (f'同时匹配输入词头和原形，共找到 {len(cards)} 张卡，请按词头和义项选择。'
                         if lemmas and exact_found else
                         f'已将 {word} 还原为 {matched_word}；找到 {len(cards)} 张卡，请按义项选择。'
                         if lemmas else f'找到 {len(cards)} 张卡，请按义项选择。'
                         if cards else '没有找到已有卡片。')
    if fmt == 'text':
        lines = [heading, status]
        for card in cards:
            summary = card_summary(card, config)
            sense = ' / '.join(summary['senses']) or '（没有可显示的义项）'
            labels = ' · '.join(summary['labels'])
            lines.append(f"词头 {card.get('_matched_word', word)} | {labels + ' | ' if labels else ''}{sense} | {card['deckName']} | {state(card)} | card {card['cardId']}")
        return '\n'.join(lines)

    from .html_view import render_article
    views = []
    for card in cards:
        views.append(dict(card, **card_summary(card, config), state=state(card),
                          template=str(card.get('ord', 0) + 1),
                          headword=card.get('_matched_word', word)))
    interaction = dict(bridge=bridge,
        timeout=config['timeout'], word=matched_word, field=config['field'],
        caseSensitive=config['case_sensitive'],
        studyDeck=config['deck'],
        cards=[{**{k: c[k] for k in ('cardId', 'deckName', 'type', 'queue')},
                'word': c.get('_matched_word', word)} for c in cards])
    return render_article(heading=heading, status=status, cards=views,
                          error=error, interaction=interaction)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('word', nargs='?')
    parser.add_argument('--stdin', action='store_true', help='Read the query as UTF-8 from stdin')
    parser.add_argument('--config', type=Path)
    parser.add_argument('--promote', action='store_true')
    parser.add_argument('--unsuspend', action='store_true')
    parser.add_argument('--card-id', type=int)
    parser.add_argument('--full-scan', action='store_true', help='Scan every scoped note (slower)')
    parser.add_argument('--format', choices=('html', 'text', 'json'), default='html')
    parser.add_argument('--inspect', action='store_true', help='List decks and model fields, read only')
    args = parser.parse_args(argv)
    word = args.word or ''
    cards = []
    config = DEFAULTS
    try:
        path = args.config or Path(__file__).resolve().parent.parent / 'config.json'
        if args.config and not path.exists():
            raise BridgeError('指定的配置文件不存在。')
        config = load_config(path)
        client = Client(config)
        if args.inspect:
            if args.promote or args.unsuspend:
                raise BridgeError('--inspect 不能和修改参数一起使用。')
            data = {'decks': client.call('deckNames'), 'models': {name: client.call('modelFieldNames', modelName=name) for name in client.call('modelNames')}}
            print(render('配置检查', [], json.dumps(data, ensure_ascii=False, indent=2), fmt=args.format, config=config))
            return 0
        if args.stdin:
            if args.word is not None:
                raise BridgeError('word 与 --stdin 只能选择一个。')
            word = sys.stdin.buffer.read(4097).decode('utf-8').strip()
        if not word.strip() or len(word) > 500:
            raise BridgeError('请输入 1～500 个字符的查询词。')
        if args.unsuspend and not args.promote:
            raise BridgeError('--unsuspend 必须和 --promote 同时使用。')
        cards = lookup(client, config, word, args.full_scan)
        message = ''
        if args.promote:
            message = promote(client, config, word, cards, args.card_id, args.unsuspend)
            if cards:
                refreshed = {c['cardId']: c for c in client.call('cardsInfo', cards=[c['cardId'] for c in cards]) if c}
                cards = [refreshed.get(c['cardId'], c) | {'_fields': c.get('_fields', {}),
                         '_matched_word': c.get('_matched_word', word)} for c in cards]
        bridge = None
        if args.format == 'html' and any(c['type'] == 0 and c['queue'] in (0, -1) for c in cards):
            from .bridge import ensure_bridge
            bridge = ensure_bridge(config)
        print(render(word, cards, message, fmt=args.format, config=config, bridge=bridge))
        return 0
    except (BridgeError, OSError, ValueError, KeyError, TypeError) as exc:
        print(render(word, cards, '错误：' + str(exc), error=True, fmt=args.format, config=config))
        return 1


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    raise SystemExit(main())
