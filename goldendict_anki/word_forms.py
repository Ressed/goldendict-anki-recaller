"""English inflection fallback for dictionary-headword lookup."""
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT.parent / 'vendor'))
import simplemma

ENGLISH_WORD = re.compile(r"[A-Za-z]+(?:[-'][A-Za-z]+)*\Z")


def lookup_forms(word, enabled=True):
    """Return exact input first, followed by one conservative dictionary lemma."""
    exact = ' '.join(word.split())
    forms = [exact]
    if not enabled or not ENGLISH_WORD.fullmatch(exact):
        return forms
    lemma = simplemma.lemmatize(exact.casefold(), lang='en', greedy=False)
    if exact.isupper():
        lemma = lemma.upper()
    elif exact[:1].isupper():
        lemma = lemma.capitalize()
    if lemma and lemma != exact:
        forms.append(lemma)
    return forms
