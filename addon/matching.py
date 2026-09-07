import unicodedata
from html.parser import HTMLParser


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


def normalize(value, case_sensitive=False, markup=False):
    if markup:
        parser = PlainText()
        parser.feed(value)
        value = ''.join(parser.parts)
    value = ' '.join(unicodedata.normalize('NFC', value).split())
    return value if case_sensitive else value.casefold()
