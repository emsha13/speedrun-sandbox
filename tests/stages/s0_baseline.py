"""Stage 0 — the baseline.

A harness the way they are usually first written, each choice the obvious one: a new application
for every test, passwords hashed at the cost production uses, the database emptied table by table,
the clock stopped by freezegun for every test, an event loop per test and so a connection pool per
test. Nothing here is wrong. All of it is paid for by every test.
"""
from app.settings import settings

# Before anything imports `app.db`, which builds the engine at import from `settings.DB_URL`.
settings.DB_URL = settings.DB_URL_TEST

import asyncio                                                                                  # noqa: E402

import freezegun                                                                                # noqa: E402
import pytest                                                                                   # noqa: E402

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
    # Children before parents.
    for table in reversed(Base.metadata.sorted_tables):
        await db_session.execute(table.delete())
    await db_session.commit()


@pytest.fixture
async def app():
    app = create_app()
    async with LifespanManager(app):
        yield app


def pytest_collection_modifyitems(items):
    # Every test runs with the clock stopped, and the clock stops before any other fixture of the
    # test is set up: the rows they write are dated by it.
    for item in items:
        item.fixturenames.insert(0, 'freezer')


@pytest.fixture
def freezer(request):
    """The clock stopped — at the moment `@pytest.mark.freeze_time('…')` names, or at now. The
    test moves it with `freezer.tick(seconds)` and `freezer.move_to(moment)`."""
    marker = request.node.get_closest_marker('freeze_time')
    with freezegun.freeze_time(marker.args[0] if marker and marker.args else None) as frozen:
        yield frozen
