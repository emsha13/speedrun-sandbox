# fastapi-pytest-speedrun

One FastAPI service, one test suite of 1,300 tests, and a test harness put together from
independent choices — each with a slow value and a fast one. The tests never change. What changes
is the harness under them, one choice at a time, and every combination is timed.

The service is the part nearly every application has: registration with a mailed code, sign-in by
address or by phone number, refresh tokens, password reset, change of password, of address and of
number, a profile, a list of sessions, request limits, and the users as an admin sees them.
FastAPI, SQLAlchemy 2 (async), asyncpg, Postgres, Redis, bcrypt, PyJWT. The tests go through the
HTTP door against a real Postgres; Redis is a fake one.

## The choices

| Choice | Slow | Fast | Where |
|---|---|---|---|
| `hash` | bcrypt at production cost | bcrypt at its lowest cost (or `cached`: the fixtures' hash computed once) | `tests/harness/hashing.py` |
| `app` | a new application for every test | one for the run | `tests/harness/application.py` |
| `clean` | a `DELETE` per table through SQLAlchemy | one string of `DELETE`s to the driver (or `truncate`) | `tests/harness/cleaning.py` |
| `clock` | freezegun | time-machine | `tests/harness/clock.py` |
| `freeze` | the clock stopped for every test | only for the tests marked `freeze_time` | `tests/harness/clock.py` |
| `loop` | an event loop per test, and so a connection pool per test | one of each for the session | `tests/harness/pool.py` |
| `workers` | one process | one per core, a database each | `tests/harness/database.py` |
| `schema` | every process builds its schema | every process copies a template database | `tests/harness/database.py` |

Each module holds both ways side by side, with the reason in a comment.

## The numbers

<!-- numbers -->
The [speedrun workflow](.github/workflows/speedrun.yml) runs every harness as a job of its own,
several times, and puts the medians in the run's summary.
<!-- /numbers -->

Three series, because the changes do not add up. From the slow harness nearly all the time is
bcrypt, and everything else looks like nothing next to it; once the hashing is cheap, the same
changes are worth a large part of what is left. So there is the usual walk — one change after
another — and two more: the slow harness with one brake taken off, and the fast harness with one
brake put back.

## Run it

Postgres on `localhost` with user and password `postgres` (or your own in `.env`, see
`.env.example`), and [uv](https://docs.astral.sh/uv/). No Redis is needed.

    uv sync
    uv run pytest                                     # the fast harness, one process
    uv run python speedrun.py slow                    # the slow one, timed
    uv run python speedrun.py slow,hash=cheap fast    # any harnesses, one after another
    uv run python speedrun.py --series minus-one      # a whole series
    uv run python speedrun.py fast -- -x -k login     # what follows `--` goes to pytest

The suite creates the database `speedrun_test` at the start and drops it at the end.

## Where to look

    app/                  the service
    tests/api/            the tests that go through the application to the database
    tests/units/          the tests that touch neither
    tests/fixtures.py     users, client, tokens — the same under every harness
    tests/harness/        the choices
    tests/conftest.py     puts a harness together by the HARNESS environment variable
    speedrun.py           runs a harness and times it; holds the three series

## What each choice is

**`hash`.** A password hash is slow on purpose: a quarter of a second at the default cost. A test
creates a user or two and signs in, so it pays that two or three times. Inside the suite
`bcrypt.gensalt` defaults to four rounds. The hashes are as real — salted, and checked by the same
`checkpw`, which reads the cost out of the hash — and the application's code is not touched.
`cached` is the half-measure for those who would rather not touch the cost: the hash the fixtures
store is computed once a run, and every sign-in still pays in full.

**`app`.** `create_app()` registers every route, and the first request FastAPI serves builds what
it needs to validate them. The harness builds the application once; the lifespan still runs
around every test. This grows with the number of routes.

**`clean`.** Before each test every table is emptied. Through SQLAlchemy that is a statement and a
round trip per table; asyncpg takes one string of all the statements and runs it in one. This
grows with the number of tables. `TRUNCATE` is there because it is the first thing everybody
suggests.

**`clock`.** freezegun stops the clock by finding every loaded module that holds `datetime`, `date`
or `time` and swapping the reference, at every start and every stop; the more is imported, the
longer it takes. time-machine patches the C functions once. The tests are the same under both: the
fixture gives them `freezer.tick()` and `freezer.move_to()`. There is a second difference:
freezegun also stops `time.monotonic`, the event loop's own clock, so under it a timeout never
fires and a test that should fail hangs instead.

**`freeze`.** A suite ends up with the clock stopped for every test when the mark is put on whole
modules to be safe. Under `marked` only the tests that read the clock have it stopped.

**`loop`.** pytest-asyncio gives every test a new event loop by default, and an asyncpg connection
belongs to the loop that opened it — so the pool is thrown away after every test and each test
opens its own connections. With one loop for the session the pool lives as long as the run. Three
things come with it: the application's shutdown must not dispose of the engine, a task a test
forgot must be cancelled before the next test, and the clock library must leave the loop's clock
alone.

**`workers`.** pytest-xdist, with a database per worker: the worker's id goes on the end of the
database's name before the engine is built. It multiplies whatever the other choices left, and it
is the one choice that costs memory.

**`schema`.** With a process per core every worker builds the schema for itself. A template
database is built once, and `CREATE DATABASE … TEMPLATE` copies files. This grows with the size of
the schema and the number of migrations.

## How to find where the time goes

What worked: timing every fixture's setup with a `pytest_fixture_setup` hook wrapper, and
comparing the first request to a fresh application with the second. What did not: `--durations`
and the cumulative times of coroutines out of cProfile. One trap: under freezegun
`time.perf_counter` is stopped too, so a fixture timed with it takes no time at all — measure
with `time.clock_gettime(time.CLOCK_MONOTONIC)`.
