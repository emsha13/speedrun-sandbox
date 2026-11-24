"""Run the suite under a harness and say how long it took.

    python speedrun.py                         the fast harness
    python speedrun.py slow                    the slow one
    python speedrun.py slow fast --rounds 3    both, turn and turn about, three times
    python speedrun.py fast -- -x -k login     what follows `--` goes to pytest

A harness is `slow` or `fast` followed by single changes; `tests/harness/__init__.py` lists them.

    --rounds N    run the harnesses N times over, in turns
    --json FILE   append one line per run
    --matrix      print the pairs of harnesses the three series compare, as JSON, and run nothing

Two harnesses are only ever compared on one machine, run in turns: the same harness on two
machines differs by more than most of the changes here are worth.
"""
import json
import os
import subprocess
import sys
import time

from tests.harness import Options, parse

# Each series is a list of (harness, what the row is called).
SERIES = {
    # One change after another, each on top of the ones before; each row is compared with the
    # row above it.
    'cumulative': [
        ('slow', 'the slow harness'),
        ('slow,hash=cheap', '+ bcrypt at its lowest cost'),
        ('slow,hash=cheap,app=shared', '+ one application for the run'),
        ('slow,hash=cheap,app=shared,clean=one_string', '+ the database emptied in one round trip'),
        ('slow,hash=cheap,app=shared,clean=one_string,commit=async', '+ commits that do not wait for the disk'),
        ('fast,freeze=all,loop=function', '+ time-machine instead of freezegun'),
        ('fast,loop=function', '+ the clock stopped only where a test reads it'),
        ('fast', '+ one event loop, one connection pool'),
        ('fast,workers=auto', '+ a process per core'),
        ('fast,workers=auto,schema=template', '+ the schema copied from a template'),
    ],
    # The slow harness with one brake taken off: what each change gives by itself. Each row is
    # compared with the first.
    'minus-one': [
        ('slow', 'the slow harness'),
        ('slow,hash=cheap', 'bcrypt at its lowest cost'),
        ('slow,hash=cached', "the fixtures' hash computed once"),
        ('slow,app=shared', 'one application for the run'),
        ('slow,clean=one_string', 'the database emptied in one round trip'),
        ('slow,clean=truncate', 'the database emptied by TRUNCATE'),
        ('slow,commit=async', 'commits that do not wait for the disk'),
        ('slow,clock=time_machine', 'time-machine instead of freezegun'),
        ('slow,freeze=marked', 'the clock stopped only where a test reads it'),
        ('slow,clock=time_machine,loop=session', 'time-machine and one event loop'),
        ('slow,workers=auto', 'a process per core'),
    ],
    # The fast harness with one brake put back: what each change is worth once the rest is done.
    # Each row is compared with the first.
    'plus-one': [
        ('fast', 'the fast harness'),
        ('fast,hash=prod', 'bcrypt as in production'),
        ('fast,hash=cached', "bcrypt as in production, the fixtures' hash computed once"),
        ('fast,app=per_test', 'an application per test'),
        ('fast,clean=per_table', 'the database emptied table by table'),
        ('fast,clean=truncate', 'the database emptied by TRUNCATE'),
        ('fast,commit=sync', 'commits that wait for the disk'),
        ('fast,clock=freezegun', 'freezegun'),
        ('fast,freeze=all', 'the clock stopped for every test'),
        ('fast,loop=function', 'an event loop per test'),
    ],
}


def pairs_of(series: str) -> list[tuple[str, str]]:
    """Which two harnesses each row of the series is a comparison of: (the reference, the row)."""
    harnesses = [harness for harness, _ in SERIES[series]]
    if series == 'cumulative':
        return list(zip(harnesses, harnesses[1:]))
    return [(harnesses[0], harness) for harness in harnesses[1:]]


def matrix() -> list[dict]:
    """Every pair once, whichever series ask for it and in whichever order."""
    seen, jobs = set(), []
    for series in SERIES:
        for pair in pairs_of(series):
            if frozenset(pair) in seen:
                continue
            seen.add(frozenset(pair))
            # A run at production's hashing cost takes minutes; the rest take seconds and can
            # afford more turns.
            slow = any(parse(harness)['hash'] != 'cheap' for harness in pair)
            jobs.append({'a': pair[0], 'b': pair[1], 'rounds': 2 if slow else 5})
    return jobs


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
        print(json.dumps(matrix()))
        return 0
    log, rounds = taken(argv, '--json'), int(taken(argv, '--rounds') or 1)
    harnesses = argv or ['fast']
    machine = os.environ.get('SPEEDRUN_MACHINE', 'here')

    results = []
    for _ in range(rounds):
        for harness in harnesses:
            print(f'\n=== {harness}', flush=True)
            seconds, passed = run(harness, extra)
            results.append((harness, seconds, passed))
            if log:
                line = {'machine': machine, 'harness': harness, 'seconds': round(seconds, 2), 'passed': passed}
                with open(log, 'a') as file:
                    file.write(json.dumps(line) + '\n')

    print()
    for harness, seconds, passed in results:
        print(f'{seconds:8.1f} s  {harness}  {"" if passed else "FAILED"}')
    return 0 if all(passed for _, _, passed in results) else 1


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
