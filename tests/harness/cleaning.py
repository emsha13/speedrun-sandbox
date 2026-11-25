"""An empty database before every test that uses one."""
import pytest

from app import models                                                                          # noqa: F401
from app.db import Base, async_session
from app.settings import settings
from tests.harness import options

if settings.WORKSPACE:
    from app.workspace import models as workspace                                               # noqa: F401

# Children before parents — every table there is, the workspace's too when it is wired in.
TABLES = [table.name for table in reversed(Base.metadata.sorted_tables)]
if options.clean == 'accounts_only' or options.size == 'python':
    from tests.harness.database import accounts_tables
    ACCOUNTS = {table.name for table in accounts_tables()}
    TABLES = [name for name in TABLES if name in ACCOUNTS]


FILLED = 'SELECT name FROM (VALUES ' + ', '.join(
    f"('{name}', EXISTS (SELECT FROM \"{name}\"))" for name in TABLES
) + ') AS tables (name, filled) WHERE filled'


@pytest.fixture
async def db_session():
    async with async_session() as session:
        yield session


@pytest.fixture
async def clear_db(db_session):
    if options.clean == 'exists':
        await _empty_the_filled(db_session)
    elif options.clean == 'per_table':
        # The obvious way: a statement per table through SQLAlchemy, each prepared and sent by
        # itself — a round trip per table, most of them over a table already empty.
        for table in reversed(Base.metadata.sorted_tables):
            if table.name in TABLES:
                await db_session.execute(table.delete())
    else:
        # One string, handed straight to the driver: asyncpg runs a string of several statements
        # in one round trip and one transaction.
        if options.clean in ('one_string', 'accounts_only'):
            statements = ';'.join(f'DELETE FROM "{name}"' for name in TABLES)
        elif options.clean == 'no_triggers':
            # An experiment, to be taken out: the foreign keys' triggers do not fire while emptying.
            statements = ';'.join(['SET LOCAL session_replication_role = replica',
                                   *(f'DELETE FROM "{name}"' for name in TABLES)])
        else:
            # One statement for all the tables. It also gives the files back and resets the
            # sequences, which is work a table of three rows does not need.
            statements = 'TRUNCATE ' + ', '.join(f'"{name}"' for name in TABLES) + ' RESTART IDENTITY'
        connection = await (await db_session.connection()).get_raw_connection()
        await connection.driver_connection.execute(statements)
    await db_session.commit()


async def _empty_the_filled(db_session):
    """An experiment: one query asks which tables have a row, and only those are emptied."""
    driver = (await (await db_session.connection()).get_raw_connection()).driver_connection
    filled = {row[0] for row in await driver.fetch(FILLED)}
    if filled:
        await driver.execute(';'.join(f'DELETE FROM "{name}"' for name in TABLES if name in filled))
