"""An empty database before every test that uses one."""
import pytest

from app.db import Base, async_session
from tests.harness import options

# Children before parents.
TABLES = [table.name for table in reversed(Base.metadata.sorted_tables)]


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
        # One string, handed straight to the driver: asyncpg runs a string of several statements
        # in one round trip and one transaction.
        if options.clean == 'one_string':
            statements = ';'.join(f'DELETE FROM "{name}"' for name in TABLES)
        else:
            # One statement for all the tables. It also gives the files back and resets the
            # sequences, which is work a table of three rows does not need.
            statements = 'TRUNCATE ' + ', '.join(f'"{name}"' for name in TABLES) + ' RESTART IDENTITY'
        connection = await (await db_session.connection()).get_raw_connection()
        await connection.driver_connection.execute(statements)
    await db_session.commit()
