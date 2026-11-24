"""Run the suite under a harness and say how long it took.

    python speedrun.py                         the fast harness
    python speedrun.py slow                    the slow one
    python speedrun.py slow,hash=cheap fast    any harnesses, one after another
    python speedrun.py --series minus-one      every harness of a series
    python speedrun.py fast -- -x -k login     what follows `--` goes to pytest

A harness is `slow` or `fast` followed by single changes; `tests/harness/__init__.py` lists them.

    --runs N      run each harness N times
    --json FILE   append one line per run: {"harness": "slow", "seconds": 12.3, "passed": true}
    --matrix      print every harness of every series as a JSON list, and run nothing
"""
import json
import os
import subprocess
import sys
import time

from tests.harness import Options, parse

# Each series is a list of (harness, what the row is called).
SERIES = {
    # One change after another, each on top of the ones before.
    'cumulative': [
        ('slow', 'the slow harness'),
        ('slow,hash=cheap', '+ bcrypt at its lowest cost'),
        ('slow,hash=cheap,app=shared', '+ one application for the run'),
        ('slow,hash=cheap,app=shared,clean=one_string', '+ the database emptied in one round trip'),
        ('slow,hash=cheap,app=shared,clean=one_string,clock=time_machine', '+ time-machine instead of freezegun'),
        ('fast,loop=function', '+ the clock stopped only where a test reads it'),
        ('fast', '+ one event loop, one connection pool'),
        ('fast,workers=auto', '+ a process per core'),
        ('fast,workers=auto,schema=template', '+ the schema copied from a template'),
    ],
    # The slow harness with one brake taken off: what each change gives by itself.
    'minus-one': [
        ('slow', 'the slow harness'),
        ('slow,hash=cheap', 'bcrypt at its lowest cost'),
        ('slow,hash=cached', "the fixtures' hash computed once"),
        ('slow,app=shared', 'one application for the run'),
        ('slow,clean=one_string', 'the database emptied in one round trip'),
        ('slow,clean=truncate', 'the database emptied by TRUNCATE'),
        ('slow,clock=time_machine', 'time-machine instead of freezegun'),
        ('slow,freeze=marked', 'the clock stopped only where a test reads it'),
        ('slow,clock=time_machine,loop=session', 'time-machine and one event loop'),
        ('slow,workers=auto', 'a process per core'),
    ],
    # The fast harness with one brake put back: what each change is worth once the rest is done.
    'plus-one': [
        ('fast', 'the fast harness'),
        ('fast,hash=prod', 'bcrypt as in production'),
        ('fast,hash=cached', "bcrypt as in production, the fixtures' hash computed once"),
        ('fast,app=per_test', 'an application per test'),
        ('fast,clean=per_table', 'the database emptied table by table'),
        ('fast,clean=truncate', 'the database emptied by TRUNCATE'),
        ('fast,clock=freezegun', 'freezegun'),
        ('fast,freeze=all', 'the clock stopped for every test'),
        ('fast,loop=function', 'an event loop per test'),
        ('fast,workers=auto', 'a process per core'),
    ],
}


def every_harness() -> list[str]:
    return list(dict.fromkeys(harness for rows in SERIES.values() for harness, _ in rows))


def run(harness: str, extra: list[str]) -> tuple[float, bool]:
    command = [sys.executable, '-m', 'pytest', '-q', *Options(parse(harness)).pytest_args(), *extra]
    started = time.perf_counter()
    finished = subprocess.run(command, env=os.environ | {'HARNESS': harness})
    return time.perf_counter() - started, finished.returncode == 0


def taken(argv: list[str], flag: str) -> str | None:
    if flag not in argv:
        return None
    at = argv.index(flag)
    value = argv[at + 1]
    del argv[at:at + 2]
    return value


def main(argv: list[str]) -> int:
    argv, extra = (argv[:argv.index('--')], argv[argv.index('--') + 1:]) if '--' in argv else (argv, [])
    if '--matrix' in argv:
        print(json.dumps(every_harness()))
        return 0
    log, runs, series = taken(argv, '--json'), int(taken(argv, '--runs') or 1), taken(argv, '--series')
    harnesses = [harness for harness, _ in SERIES[series]] if series else argv or ['fast']

    results = []
    for harness in harnesses:
        for _ in range(runs):
            print(f'\n=== {harness}', flush=True)
            seconds, passed = run(harness, extra)
            results.append((harness, seconds, passed))
            if log:
                with open(log, 'a') as file:
                    file.write(json.dumps({'harness': harness, 'seconds': round(seconds, 2), 'passed': passed}) + '\n')

    print()
    for harness, seconds, passed in results:
        print(f'{seconds:8.1f} s  {harness}  {"" if passed else "FAILED"}')
    return 0 if all(passed for _, _, passed in results) else 1


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
