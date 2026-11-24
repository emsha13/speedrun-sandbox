"""Making and dropping the tests' database. The same in every stage.

Imports `app.db`, so a stage imports this only after it has pointed `settings.DB_URL` at the
tests' database.
"""
import asyncpg

from app import models                                                                          # noqa: F401
from app.db import Base, engine

NAME = engine.url.database
SERVER = engine.url.set(drivername='postgresql', database='postgres').render_as_string(hide_password=False)

# The suite drops this database. Better to refuse to start than to find out which one it was.
assert 'test' in NAME, f'tests are pointed at database {NAME!r}'


async def create_database():
    await drop_database()
    server = await asyncpg.connect(SERVER)
    await server.execute(f'CREATE DATABASE "{NAME}"')
    await server.close()
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    # This runs under an `asyncio.run` of its own, and a pooled connection belongs to the loop
    # that opened it.
    await engine.dispose()


async def drop_database():
    server = await asyncpg.connect(SERVER)
    await server.execute(f'DROP DATABASE IF EXISTS "{NAME}" WITH (FORCE)')
    await server.close()
