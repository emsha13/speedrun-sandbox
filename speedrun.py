"""Run the suite under one stage's harness, or several, and say how long each took.

    python speedrun.py              every stage, in order
    python speedrun.py 0 6          stages 0 and 6
    python speedrun.py 3 -- -x -k login     what follows `--` goes to pytest

`--json FILE` appends one line per run: {"stage": 3, "seconds": 12.3, "passed": true}.
"""
import json
import os
import subprocess
import sys
import time

from tests.stages import STAGES


def run(number: int, extra: list[str]) -> tuple[float, bool]:
    stage = STAGES[number]
    command = [
        sys.executable, '-m', 'pytest', '-q',
        '-o', f'asyncio_default_fixture_loop_scope={stage.loop_scope}',
        '-o', f'asyncio_default_test_loop_scope={stage.loop_scope}',
        *stage.args, *extra,
    ]
    started = time.perf_counter()
    finished = subprocess.run(command, env=os.environ | {'STAGE': str(number)})
    return time.perf_counter() - started, finished.returncode == 0


def main(argv: list[str]) -> int:
    argv, extra = (argv[:argv.index('--')], argv[argv.index('--') + 1:]) if '--' in argv else (argv, [])
    log = None
    if '--json' in argv:
        at = argv.index('--json')
        log = argv[at + 1]
        del argv[at:at + 2]
    numbers = [int(arg) for arg in argv] or list(range(len(STAGES)))

    results = []
    for number in numbers:
        print(f'\n=== stage {number}: {STAGES[number].title}', flush=True)
        seconds, passed = run(number, extra)
        results.append((number, seconds, passed))
        if log:
            with open(log, 'a') as file:
                file.write(json.dumps({'stage': number, 'seconds': round(seconds, 2), 'passed': passed}) + '\n')

    print()
    first = results[0][1]
    for number, seconds, passed in results:
        print(f'{number}  {STAGES[number].title:<46} {seconds:8.1f} s  x{first / seconds:5.1f}  {"" if passed else "FAILED"}')
    return 0 if all(passed for _, _, passed in results) else 1


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
