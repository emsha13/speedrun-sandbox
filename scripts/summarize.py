"""Markdown tables out of what `speedrun.py --json` wrote: one per series, the median of each
harness's runs.

    python scripts/summarize.py results/*.jsonl
"""
import json
import statistics
import sys

from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from speedrun import SERIES                                                                     # noqa: E402

TITLES = {
    'cumulative': 'One change after another',
    'minus-one': 'The slow harness with one brake taken off',
    'plus-one': 'The fast harness with one brake put back',
}

runs, failed = defaultdict(list), set()
for path in sys.argv[1:]:
    for line in Path(path).read_text().splitlines():
        run = json.loads(line)
        runs[run['harness']].append(run['seconds'])
        if not run['passed']:
            failed.add(run['harness'])

for series, rows in SERIES.items():
    rows = [(harness, label) for harness, label in rows if harness in runs]
    if not rows:
        continue
    first = statistics.median(runs[rows[0][0]])
    print(f'\n### {TITLES[series]}\n')
    print('| Harness | Median, s | Runs (min – max) | vs. the row above | vs. the first row |')
    print('|---|---:|---:|---:|---:|')
    above = None
    for harness, label in rows:
        seconds = runs[harness]
        median = statistics.median(seconds)
        step = f'×{above / median:.2f}' if above and series == 'cumulative' else ''
        print(
            f'| {label}{" — FAILED" if harness in failed else ""}<br>`{harness}` | {median:.1f} '
            f'| {len(seconds)} ({min(seconds):.1f} – {max(seconds):.1f}) | {step} | ×{first / median:.2f} |'
        )
        above = median
