"""Which database the tests run on, and how it comes to be.

`point_at_the_test_database()` is called before anything imports `app.db`, which builds the
engine at import from `settings.DB_URL`. The rest of the module imports `app.db` lazily for that
reason.
"""
import os

import asyncpg

from sqlalchemy.engine import make_url

from app.settings import settings
from tests.harness import options


def point_at_the_test_database() -> None:
    # Under pytest-xdist every worker empties the database before each test, so two workers on
    # one database would destroy each other's rows: a worker takes a database of its own, named
    # with its id on the end — `…_gw0`, `…_gw1`.
    worker = os.environ.get('PYTEST_XDIST_WORKER')
    settings.DB_URL = settings.DB_URL_TEST + (f'_{worker}' if worker else '')
    # The suite drops this database. Better to refuse to start than to find out which one it was.
    assert 'test' in make_url(settings.DB_URL).database, f'tests are pointed at {settings.DB_URL}'


def _server() -> str:
    return make_url(settings.DB_URL).set(drivername='postgresql', database='postgres').render_as_string(False)


TEMPLATE = make_url(settings.DB_URL_TEST).database + '_template'


async def _build_schema() -> None:
    from app import models                                                                      # noqa: F401
    if settings.WORKSPACE:
        from app.workspace import models as workspace                                           # noqa: F401
    from app.db import Base, engine

    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    # This runs under an `asyncio.run` of its own, and a pooled connection belongs to the loop
    # that opened it.
    await engine.dispose()


async def create_template() -> None:
    """The schema, built once in a database nobody runs tests on. Called by the one process that
    starts the run; every worker then copies it, which for Postgres is copying files."""
    from sqlalchemy.ext.asyncio import create_async_engine

    from app import models                                                                      # noqa: F401
    if settings.WORKSPACE:
        from app.workspace import models as workspace                                           # noqa: F401
    from app.db import Base

    server = await asyncpg.connect(_server())
    await server.execute(f'DROP DATABASE IF EXISTS "{TEMPLATE}" WITH (FORCE)')
    await server.execute(f'CREATE DATABASE "{TEMPLATE}"')
    await server.close()
    engine = create_async_engine(make_url(settings.DB_URL_TEST).set(database=TEMPLATE))
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    await engine.dispose()


async def drop_template() -> None:
    server = await asyncpg.connect(_server())
    await server.execute(f'DROP DATABASE IF EXISTS "{TEMPLATE}" WITH (FORCE)')
    await server.close()


async def create_database() -> None:
    name = make_url(settings.DB_URL).database
    server = await asyncpg.connect(_server())
    await server.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
    if options.schema == 'template':
        await server.execute(f'CREATE DATABASE "{name}" TEMPLATE "{TEMPLATE}"')
    else:
        await server.execute(f'CREATE DATABASE "{name}"')
    if options.commit == 'async':
        # A commit that waits for the disk is what keeps a bank's money through a power cut. This
        # database is dropped at the end of the run, so its commits return at once: the setting
        # is the database's own and touches nothing else on the server.
        await server.execute(f'ALTER DATABASE "{name}" SET synchronous_commit = off')
    await server.close()
    if options.schema == 'create':
        await _build_schema()


async def drop_database() -> None:
    name = make_url(settings.DB_URL).database
    server = await asyncpg.connect(_server())
    await server.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
    await server.close()
