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

# Which tables have a row, asked of every table in one query. A test writes to a handful of the
# tables there are; a DELETE over an empty one is cheap, but two hundred of them before every test
# are not.
FILLED = 'SELECT name FROM (VALUES ' + ', '.join(
    f"('{name}', EXISTS (SELECT FROM \"{name}\"))" for name in TABLES
) + ') AS tables (name, filled) WHERE filled'


@pytest.fixture
async def db_session():
    async with async_session() as session:
        yield session


@pytest.fixture
async def clear_db(db_session):
    if options.clean == 'per_table':
        # The obvious way: a statement per table through SQLAlchemy, each prepared and sent by
        # itself — a round trip per table, most of them over a table already empty.
        for table in reversed(Base.metadata.sorted_tables):
            await db_session.execute(table.delete())
    else:
        connection = (await (await db_session.connection()).get_raw_connection()).driver_connection
        # One string, handed straight to the driver: asyncpg runs a string of several statements
        # in one round trip and one transaction.
        if options.clean == 'one_string':
            statements = ';'.join(f'DELETE FROM "{name}"' for name in TABLES)
        elif options.clean == 'exists':
            filled = {row['name'] for row in await connection.fetch(FILLED)}
            statements = ';'.join(f'DELETE FROM "{name}"' for name in TABLES if name in filled)
        else:
            # One statement for all the tables. It also gives the files back and resets the
            # sequences, which is work a table of three rows does not need.
            statements = 'TRUNCATE ' + ', '.join(f'"{name}"' for name in TABLES) + ' RESTART IDENTITY'
        if statements:
            await connection.execute(statements)
    await db_session.commit()
