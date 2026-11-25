"""An experiment, to be taken out: where the tests' own calls spend their time on the large app."""
import gc
import time

import pytest
from sqlalchemy import event

from app.db import engine
from tests.harness import options


def now() -> float:
    return time.clock_gettime(time.CLOCK_MONOTONIC)


SPENT = {'setup': 0.0, 'call': 0.0, 'call sql': 0.0, 'call gc': 0.0}
COUNT = {'call sql': 0, 'gc 0': 0, 'gc 1': 0, 'gc 2': 0, 'call gc 2': 0}
STATE = {'in call': False, 'gc started': 0.0, 'sql started': 0.0, 'gc all': 0.0, 'objects': 0}


def on_gc(phase, info):
    if phase == 'start':
        STATE['gc started'] = now()
        return
    took = now() - STATE['gc started']
    STATE['gc all'] += took
    COUNT[f'gc {info["generation"]}'] += 1
    if STATE['in call']:
        SPENT['call gc'] += took
        if info['generation'] == 2:
            COUNT['call gc 2'] += 1


@event.listens_for(engine.sync_engine, 'before_cursor_execute')
def before(*args):
    STATE['sql started'] = now()


@event.listens_for(engine.sync_engine, 'after_cursor_execute')
def after(*args):
    if STATE['in call']:
        SPENT['call sql'] += now() - STATE['sql started']
        COUNT['call sql'] += 1


def pytest_sessionstart(session):
    if options.gc == 'frozen':
        gc.collect()
        gc.freeze()
    STATE['objects'] = len(gc.get_objects())
    gc.callbacks.append(on_gc)


@pytest.hookimpl(wrapper=True)
def pytest_runtest_setup(item):
    started = now()
    try:
        return (yield)
    finally:
        SPENT['setup'] += now() - started


@pytest.hookimpl(wrapper=True)
def pytest_runtest_call(item):
    started = now()
    STATE['in call'] = True
    try:
        return (yield)
    finally:
        STATE['in call'] = False
        SPENT['call'] += now() - started


def pytest_terminal_summary(terminalreporter):
    line = '  '.join(f'{name} {seconds:.2f}' for name, seconds in SPENT.items())
    line += f'  gc all {STATE["gc all"]:.2f}  objects {STATE["objects"]}  '
    line += '  '.join(f'{name} {count}' for name, count in COUNT.items())
    terminalreporter.write_line('SPENT ' + line)
