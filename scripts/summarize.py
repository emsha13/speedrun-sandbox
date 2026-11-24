"""A Markdown table out of what `speedrun.py --json` wrote: the median of each stage's runs.

    python scripts/summarize.py results/times.jsonl
"""
import json
import statistics
import sys

from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tests.stages import STAGES                                                                 # noqa: E402

runs, failed = defaultdict(list), set()
for line in Path(sys.argv[1]).read_text().splitlines():
    run = json.loads(line)
    runs[run['stage']].append(run['seconds'])
    if not run['passed']:
        failed.add(run['stage'])

medians = {number: statistics.median(seconds) for number, seconds in sorted(runs.items())}
baseline = medians[min(medians)]

print('| # | Stage | Median, s | Runs (min – max) | vs. the stage before | vs. baseline |')
print('|---|---|---:|---:|---:|---:|')
before = None
for number, median in medians.items():
    seconds = runs[number]
    step = f'×{before / median:.2f}' if before else ''
    title = STAGES[number].title + (' — FAILED' if number in failed else '')
    print(
        f'| {number} | {title} | {median:.1f} | {len(seconds)} ({min(seconds):.1f} – {max(seconds):.1f}) '
        f'| {step} | ×{baseline / median:.1f} |'
    )
    before = median
