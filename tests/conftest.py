"""Puts the harness together out of `tests/harness/`, by the choices HARNESS names.

The order of the first lines matters: which database the engine is built for, what a password hash
costs and whether the workspace is wired in are all settled when `app` is imported, so all three
are decided before that.
"""
import asyncio

import pytest

from app.settings import settings
from tests.harness import options
from tests.harness.database import point_at_the_test_database
from tests.harness.hashing import set_the_cost

point_at_the_test_database()
set_the_cost()
settings.WORKSPACE = options.size == 'large'

from tests.harness import database                                                              # noqa: E402
from tests.harness.application import *                                                         # noqa: E402, F401, F403
from tests.harness.cleaning import *                                                            # noqa: E402, F401, F403
from tests.harness.clock import *                                                               # noqa: E402, F401, F403
from tests.harness.pool import *                                                                # noqa: E402, F401, F403
from tests.fixtures import *                                                                    # noqa: E402, F401, F403


def runs_no_test(config) -> bool:
    """Whether this process is pytest-xdist's controller: it runs no test, its workers do — each
    on a database of its own, which each creates and drops itself."""
    return bool(getattr(config.option, 'numprocesses', None)) and not hasattr(config, 'workerinput')


def is_a_worker(config) -> bool:
    return hasattr(config, 'workerinput')


def pytest_configure(config):
    config.addinivalue_line('markers', 'freeze_time(moment): the test runs with the clock stopped, at `moment` or at now')
    assert config.getini('asyncio_default_test_loop_scope') == options.loop, (
        f'HARNESS says loop={options.loop} and pytest was told otherwise: run it with `python speedrun.py`'
    )
    # The template is built by whoever starts the run — the controller, or the one process.
    if options.schema == 'template' and not is_a_worker(config):
        asyncio.run(database.create_template())
    if not runs_no_test(config):
        asyncio.run(database.create_database())


def pytest_unconfigure(config):
    if not runs_no_test(config):
        asyncio.run(database.drop_database())
    if options.schema == 'template' and not is_a_worker(config):
        asyncio.run(database.drop_template())


def pytest_collection_modifyitems(items):
    stop_the_clock_for(items)                                                                   # noqa: F405


# An experiment, to be taken out: where a run's time goes.
import time                                                                                     # noqa: E402

SPENT = {'setup': 0.0, 'call': 0.0, 'teardown': 0.0}


@pytest.hookimpl(wrapper=True)
def pytest_runtest_setup(item):
    started = time.perf_counter()
    try:
        return (yield)
    finally:
        SPENT['setup'] += time.perf_counter() - started


@pytest.hookimpl(wrapper=True)
def pytest_runtest_call(item):
    started = time.perf_counter()
    try:
        return (yield)
    finally:
        SPENT['call'] += time.perf_counter() - started


@pytest.hookimpl(wrapper=True)
def pytest_runtest_teardown(item, nextitem):
    started = time.perf_counter()
    try:
        return (yield)
    finally:
        SPENT['teardown'] += time.perf_counter() - started


def pytest_terminal_summary(terminalreporter):
    from tests.harness.cleaning import SPENT as cleaning
    spent = SPENT | cleaning
    terminalreporter.write_line('SPENT ' + '  '.join(f'{name} {seconds:.2f}' for name, seconds in spent.items()))
