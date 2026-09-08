"""Measure fresh CLI processes against local Anki (read-only; no card writes)."""
import argparse
from pathlib import Path
import statistics
import subprocess
import sys
import time


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('words', nargs='+')
    parser.add_argument('--runs', type=int, default=5)
    parser.add_argument('--config', type=Path)
    parser.add_argument('--format', choices=('html', 'json', 'text'), default='html')
    args = parser.parse_args()
    if args.runs < 2:
        parser.error('--runs must be at least 2')
    root = Path(__file__).resolve().parents[1]
    command = [sys.executable, str(root / 'anki_recall.py'), '--format', args.format]
    if args.config:
        command += ['--config', str(args.config.resolve())]
    for word in args.words:
        samples = []
        for _ in range(args.runs):
            start = time.perf_counter()
            result = subprocess.run(command + ['--', word], cwd=root, capture_output=True)
            samples.append(time.perf_counter() - start)
            if result.returncode:
                print(f'{word}: lookup failed (exit {result.returncode}); run the CLI to inspect the error.',
                      file=sys.stderr)
                return 1
        print(f'{word}: first={samples[0]:.3f}s, subsequent median={statistics.median(samples[1:]):.3f}s, '
              f'max={max(samples):.3f}s, below 1s={sum(s < 1 for s in samples)}/{len(samples)}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
