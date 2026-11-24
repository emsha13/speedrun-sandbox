"""Stage 5 — the clock stopped only where a test reads it.

The one change from stage 4: a test without the `freeze_time` mark runs on the real clock.
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
from sqlalchemy import event                                                                    # noqa: E402

from app.db import Base, async_session, engine                                                  # noqa: E402
from app.main import create_app                                                                 # noqa: E402
from tests.database import create_database, drop_database                                       # noqa: E402

LOOP_SCOPE = 'function'


def pytest_configure(config):
    config.addinivalue_line('markers', 'freeze_time(moment): the test runs with the clock stopped, at `moment` or at now')
    assert config.getini('asyncio_default_test_loop_scope') == LOOP_SCOPE, 'run this stage with `python speedrun.py`'
    asyncio.run(create_database())


def pytest_unconfigure(config):
    asyncio.run(drop_database())


@pytest.fixture(autouse=True)
async def _fresh_connection_pool_per_test():
    yield
    # asyncpg ties a pooled connection to the event loop that opened it, and every test runs on a
    # fresh loop: a connection carried over from the previous test fails with "attached to a
    # different loop". Dropping the pool at teardown makes the next test open its own.
    await engine.dispose()


# `engine.dispose()` closes what is checked in at that moment and puts a new pool in place; a
# connection checked out *then* goes back, when its holder lets go, to the old pool — which nothing
# reads again, so it stays open on the server until the garbage collector reaches it. The test's
# own session is opened before the application and closed after it, and the application's shutdown
# disposes the engine: a test that read a row through its session holds a connection across that.
# A connection is tagged with the pool that made it, and one returned to any other pool is closed.
@event.listens_for(engine.sync_engine, 'connect')
def _tag_the_pool_a_connection_was_made_for(dbapi_connection, connection_record):
    connection_record.info['pool'] = engine.pool


@event.listens_for(engine.sync_engine, 'checkin')
def _close_a_connection_returned_to_a_disposed_pool(dbapi_connection, connection_record):
    if connection_record.info.get('pool') is not engine.pool:
        connection_record.invalidate()


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


@pytest.fixture
async def app():
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
