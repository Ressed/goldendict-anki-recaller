"""English inflection fallback for dictionary-headword lookup."""
import re

ENGLISH_WORD = re.compile(r"[A-Za-z]+(?:[-'][A-Za-z]+)*\Z")


def lookup_forms(word, enabled=True):
    """Return exact input first, followed by one conservative dictionary lemma."""
    exact = ' '.join(word.split())
    forms = [exact]
    if not enabled or not ENGLISH_WORD.fullmatch(exact):
        return forms
    import simplemma
    lemma = simplemma.lemmatize(exact.casefold(), lang='en', greedy=False)
    if exact.isupper():
        lemma = lemma.upper()
    elif exact[:1].isupper():
        lemma = lemma.capitalize()
    if lemma and lemma != exact:
        forms.append(lemma)
    return forms
