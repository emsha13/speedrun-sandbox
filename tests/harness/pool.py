"""How long the engine's connections live.

pytest-asyncio gives every test a new event loop unless told otherwise, and an asyncpg connection
belongs to the loop that opened it. So with a loop per test the pool is thrown away after every
test and each test opens its own connections; with one loop for the session the pool lives as
long as the run. What a kept connection saves is more than its opening: a fresh Postgres backend
reads the catalogue of every table it touches anew.
"""
import asyncio

import pytest

from sqlalchemy import event

from app.db import engine
from tests.harness import options

if options.loop == 'function':

    @pytest.fixture(autouse=True)
    async def _fresh_connection_pool_per_test():
        yield
        # A connection carried over from the previous test would fail with "attached to a
        # different loop". Dropping the pool at teardown makes the next test open its own.
        await engine.dispose()

    # `engine.dispose()` closes what is checked in at that moment and puts a new pool in place; a
    # connection checked out *then* goes back, when its holder lets go, to the old pool — which
    # nothing reads again, so it stays open on the server until the garbage collector reaches it.
    # The test's own session is opened before the application and closed after it, and the
    # application's shutdown disposes the engine: a test that read a row through its session
    # holds a connection across that. A connection is tagged with the pool that made it, and one
    # returned to any other pool is closed.
    @event.listens_for(engine.sync_engine, 'connect')
    def _tag_the_pool_a_connection_was_made_for(dbapi_connection, connection_record):
        connection_record.info['pool'] = engine.pool

    @event.listens_for(engine.sync_engine, 'checkin')
    def _close_a_connection_returned_to_a_disposed_pool(dbapi_connection, connection_record):
        if connection_record.info.get('pool') is not engine.pool:
            connection_record.invalidate()

else:

    @pytest.fixture(scope='session', autouse=True)
    async def _the_pool_lives_as_long_as_the_run():
        yield
        await engine.dispose()

    @pytest.fixture(autouse=True)
    async def _nothing_outlives_its_test():
        # On the shared loop a task a test forgot would run on under the next test's name —
        # against its rows and its clock.
        before = asyncio.all_tasks()
        yield
        left = [
            task for task in asyncio.all_tasks() - before if task is not asyncio.current_task() and not task.done()
        ]
        for task in left:
            task.cancel()
        await asyncio.gather(*left, return_exceptions=True)
