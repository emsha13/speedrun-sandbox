"""Markdown tables out of what `speedrun.py --json` wrote, one per series.

    python scripts/summarize.py results/*.jsonl

A row compares two harnesses that ran in turns on one machine: the medians of each there, and
their ratio. Seconds from two different rows come from two different machines and are not to be
compared; the ratios are.
"""
import json
import statistics
import sys

from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from speedrun import SERIES, pairs_of                                                           # noqa: E402

TITLES = {
    'cumulative': 'One change after another',
    'minus-one': 'The slow harness with one brake taken off',
    'plus-one': 'The fast harness with one brake put back',
}

# machine -> harness -> seconds of each run
runs, failed = defaultdict(lambda: defaultdict(list)), set()
for path in sys.argv[1:]:
    for line in Path(path).read_text().splitlines():
        run = json.loads(line)
        runs[run['machine']][run['harness']].append(run['seconds'])
        if not run['passed']:
            failed.add(run['harness'])


def compared(reference: str, harness: str) -> tuple[float, float, int] | None:
    """The medians of the two on the machine that ran both, and how many times it ran each."""
    for machine in runs.values():
        if reference in machine and harness in machine:
            return statistics.median(machine[reference]), statistics.median(machine[harness]), len(machine[harness])
    return None


for series, rows in SERIES.items():
    labels = dict(rows)
    print(f'\n### {TITLES[series]}\n')
    if series == 'cumulative':
        print('| Change | Before, s | After, s | Runs of each | This change | All so far |')
        print('|---|---:|---:|---:|---:|---:|')
        total = 1.0
        for reference, harness in pairs_of(series):
            found = compared(reference, harness)
            if found is None:
                continue
            before, after, times = found
            total *= before / after
            flag = ' — FAILED' if {reference, harness} & failed else ''
            print(
                f'| {labels[harness]}{flag}<br>`{harness}` | {before:.1f} | {after:.1f} | {times} '
                f'| ×{before / after:.2f} | ×{total:.1f} |'
            )
        continue
    slower = series == 'plus-one'
    print(f'| Change | {rows[0][1]}, s | With the change, s | Runs of each | {"Slower" if slower else "Faster"} by |')
    print('|---|---:|---:|---:|---:|')
    for reference, harness in pairs_of(series):
        found = compared(reference, harness)
        if found is None:
            continue
        before, after, times = found
        ratio = after / before if slower else before / after
        flag = ' — FAILED' if {reference, harness} & failed else ''
        print(f'| {labels[harness]}{flag}<br>`{harness}` | {before:.1f} | {after:.1f} | {times} | ×{ratio:.2f} |')
