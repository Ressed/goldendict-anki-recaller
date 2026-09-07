"""Jinja templates and local assets, emitted as a self-contained dictionary article."""
from pathlib import Path
import sys
import uuid

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT.parent / 'vendor'))
from jinja2 import Environment, FileSystemLoader, StrictUndefined

ENV = Environment(loader=FileSystemLoader(ROOT / 'templates'),
                  autoescape=True, undefined=StrictUndefined,
                  trim_blocks=True, lstrip_blocks=True)


def render_article(**context):
    return ENV.get_template('lookup.html').render(
        root_id='anki-' + uuid.uuid4().hex,
        css=(ROOT / 'static/lookup.css').read_text(encoding='utf-8'),
        javascript=(ROOT / 'static/lookup.js').read_text(encoding='utf-8'),
        **context)
