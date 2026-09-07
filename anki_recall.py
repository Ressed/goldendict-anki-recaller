"""Entry point for GoldenDict Program commands."""
import sys
from goldendict_anki.cli import *  # re-export the command API

if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    raise SystemExit(main())
