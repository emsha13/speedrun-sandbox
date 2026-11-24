"""The harness is put together from independent choices. Each has a slow value — the obvious one,
the way a harness is usually first written — and a fast one, and each lives in a module of its
own here, both ways side by side.

Which values a run uses is said by the HARNESS environment variable: `slow` or `fast`, then any
number of single changes — `slow,hash=cheap` is the slow harness with cheap hashing and nothing
else. Unset, it is `fast`. `python speedrun.py` sets it and times the run.
"""
import os

CHOICES = {
    # What a password hash costs: bcrypt as production runs it; the same, but a fixture's hash of
    # the same password computed once a run; bcrypt at its lowest cost.
    'hash': ('prod', 'cached', 'cheap'),
    # A new application for every test, or one for the run.
    'app': ('per_test', 'shared'),
    # How the database is emptied before a test: a statement per table through SQLAlchemy, one
    # string of DELETEs to the driver, or one TRUNCATE.
    'clean': ('per_table', 'one_string', 'truncate'),
    # Whether a commit waits for the disk, as production's must, or returns at once.
    'commit': ('sync', 'async'),
    # The library that stops the clock.
    'clock': ('freezegun', 'time_machine'),
    # Whose clock is stopped: every test's, or only that of the tests marked `freeze_time`.
    'freeze': ('all', 'marked'),
    # An event loop per test, and so a connection pool per test — or one of each for the session.
    'loop': ('function', 'session'),
    # How a process gets its schema: builds it, or copies a template database built once.
    'schema': ('create', 'template'),
    # One process, or one per core under pytest-xdist.
    'workers': ('1', 'auto'),
}

SLOW = {name: values[0] for name, values in CHOICES.items()}
FAST = SLOW | {
    'hash': 'cheap', 'app': 'shared', 'clean': 'one_string', 'commit': 'async', 'clock': 'time_machine',
    'freeze': 'marked', 'loop': 'session',
}


def parse(text: str) -> dict:
    base, *changes = text.split(',')
    chosen = dict({'slow': SLOW, 'fast': FAST}[base])
    for change in changes:
        name, value = change.split('=')
        assert value in CHOICES[name], f'{name} is one of {CHOICES[name]}, not {value!r}'
        chosen[name] = value
    return chosen


class Options:
    def __init__(self, chosen: dict):
        self.__dict__.update(chosen)

    def pytest_args(self) -> list[str]:
        """What pytest itself has to be told: the loop's scope is pytest-asyncio's setting, and
        the number of processes is pytest-xdist's."""
        return [
            '-o', f'asyncio_default_fixture_loop_scope={self.loop}',
            '-o', f'asyncio_default_test_loop_scope={self.loop}',
            *(['-n', 'auto'] if self.workers == 'auto' else []),
        ]


options = Options(parse(os.environ.get('HARNESS', 'fast')))
