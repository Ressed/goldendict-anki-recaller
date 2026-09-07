"""Stable entry point for existing GoldenDict Program commands."""
import sys
from goldendict_anki.cli import *  # compatibility for existing imports

if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    raise SystemExit(main())
