"""Stage 6 — one event loop for the session, and so one connection pool.

The change from stage 5: pytest-asyncio runs every test on the same loop
(`asyncio_default_test_loop_scope = session`), which lets the engine keep its connections from
test to test. The lifespan's `engine.dispose()` is stood in for, the per-test disposal and the
pool-tagging that went with it are gone, and what a test leaves on the loop is cancelled after
it.
"""
from app.settings import settings

# Before anything imports `app.db`, which builds the engine at import from `settings.DB_URL`.
settings.DB_URL = settings.DB_URL_TEST

import bcrypt                                                                                   # noqa: E402

# Also before `app` is imported: a module of it hashes at import. At the cost the application
# hashes with, a hash is a quarter of a second by design; a test makes a user or two and signs in.
# At the lowest cost bcrypt takes a hash is as real — salted, checked by the same `checkpw`, which
# reads the cost out of the hash. What the cost buys is time against a guesser, and no test
# measures that. The application's own code is untouched.
_gensalt = bcrypt.gensalt
bcrypt.gensalt = lambda rounds=4, prefix=b'2b': _gensalt(rounds, prefix)

import asyncio                                                                                  # noqa: E402

from datetime import UTC, datetime                                                              # noqa: E402

import pytest                                                                                   # noqa: E402
import time_machine                                                                             # noqa: E402

from asgi_lifespan import LifespanManager                                                       # noqa: E402

from app.db import Base, async_session, engine                                                  # noqa: E402
from app.main import create_app                                                                 # noqa: E402
from tests.database import create_database, drop_database                                       # noqa: E402

LOOP_SCOPE = 'session'


def pytest_configure(config):
    config.addinivalue_line('markers', 'freeze_time(moment): the test runs with the clock stopped, at `moment` or at now')
    assert config.getini('asyncio_default_test_loop_scope') == LOOP_SCOPE, 'run this stage with `python speedrun.py`'
    asyncio.run(create_database())


def pytest_unconfigure(config):
    asyncio.run(drop_database())


# One event loop runs the whole session, so the pool outlives a test. What a kept connection saves
# is more than its opening: a fresh Postgres backend reads the catalogue of every table it touches
# anew, and the clean-up before each test touches all of them.
@pytest.fixture(scope='session', autouse=True)
async def _the_pool_lives_as_long_as_the_run():
    yield
    await engine.dispose()


@pytest.fixture(autouse=True)
async def _nothing_outlives_its_test():
    # On the shared loop a task a test forgot would run on under the next test's name — against
    # its rows and its clock.
    before = asyncio.all_tasks()
    yield
    left = [task for task in asyncio.all_tasks() - before if task is not asyncio.current_task() and not task.done()]
    for task in left:
        task.cancel()
    await asyncio.gather(*left, return_exceptions=True)


@pytest.fixture
async def db_session():
    async with async_session() as session:
        yield session


@pytest.fixture(autouse=True)
async def clear_db(db_session):
    # One string of a `DELETE` per table, children before parents, handed straight to the driver:
    # asyncpg runs a string of several statements in one round trip and one transaction, where
    # SQLAlchemy would prepare and send each `DELETE` by itself — a round trip per table before
    # every test, most of them over a table already empty.
    connection = await (await db_session.connection()).get_raw_connection()
    await connection.driver_connection.execute(
        ';'.join(f'DELETE FROM "{table.name}"' for table in reversed(Base.metadata.sorted_tables))
    )
    await db_session.commit()


_application = None


def built_app():
    """The application, built once. A fresh one is expensive twice: `create_app` registers every
    route, and the first request FastAPI routes builds what it needs to validate them. What a test
    may expect of an application of its own is kept: the lifespan runs around every test."""
    global _application
    if _application is None:
        _application = create_app()
    return _application


class _EngineThatStays:
    """What the lifespan has in place of the engine in a test: the same connections, and a
    `dispose` that does nothing. Disposal is right for a process about to exit; here the process
    goes on to the next test, and the pool with it."""
    connect = engine.connect

    async def dispose(self):
        pass


@pytest.fixture
async def app(monkeypatch):
    monkeypatch.setattr('app.main.engine', _EngineThatStays())
    app = built_app()
    async with LifespanManager(app):
        yield app


def _in_utc(moment) -> datetime:
    """A moment as a test names it — a string or a datetime, with a zone or without — as the UTC
    instant it means: what has no zone is UTC."""
    if isinstance(moment, str):
        moment = datetime.fromisoformat(moment)
    return moment.replace(tzinfo=UTC) if moment.tzinfo is None else moment.astimezone(UTC)


class _StoppedClock:
    """The clock a test holds: stopped, and moved by the test alone."""

    def __init__(self, traveller):
        self._traveller = traveller

    def tick(self, delta=1) -> None:
        """Forward by seconds or by a `timedelta`."""
        self._traveller.shift(delta)

    def move_to(self, moment) -> None:
        self._traveller.move_to(_in_utc(moment))


def pytest_collection_modifyitems(items):
    # Only a test that reads the clock carries the mark, and only such a test has the clock
    # stopped — before any other fixture of the test is set up: the rows they write are dated by it.
    for item in items:
        if item.get_closest_marker('freeze_time'):
            item.fixturenames.insert(0, 'freezer')


@pytest.fixture
def freezer(request):
    """The clock stopped — at the moment `@pytest.mark.freeze_time('…')` names, or at now. The
    test moves it with `freezer.tick(seconds)` and `freezer.move_to(moment)`.

    What stops is the calendar: `datetime.now`, `time.time`. The monotonic clock — the event
    loop's own — runs on, so a timeout still means what it says."""
    marker = request.node.get_closest_marker('freeze_time')
    moment = _in_utc(marker.args[0]) if marker and marker.args else datetime.now(UTC)
    with time_machine.travel(moment, tick=False) as traveller:
        yield _StoppedClock(traveller)
