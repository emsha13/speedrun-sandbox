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
| `commit` | a commit waits for the disk | it returns at once | `tests/harness/database.py` |
| `loop` | an event loop per test, and so a connection pool per test | one of each for the session | `tests/harness/pool.py` |
| `workers` | one process | one per core, a database each | `tests/harness/database.py` |
| `schema` | every process builds its schema | every process copies a template database | `tests/harness/database.py` |

Each module holds both ways side by side, with the reason in a comment.

## The numbers

<!-- numbers -->
Measured by the [speedrun workflow](.github/workflows/speedrun.yml) on GitHub's standard runners,
1,325 tests, wall time of the whole `pytest` process. Every row is two harnesses run in turns on
one machine — the medians of each there and their ratio. Seconds from two different rows come
from two different machines and are not to be compared: the same harness on two machines differs
by more than most of these changes are worth. The ratios are what to read.

### One change after another

| Change | Before, s | After, s | Runs of each | This change | All so far |
|---|---:|---:|---:|---:|---:|
| + bcrypt at its lowest cost<br>`slow,hash=cheap` | 493.4 | 62.4 | 2 | ×7.91 | ×7.9 |
| + one application for the run<br>`slow,hash=cheap,app=shared` | 43.5 | 35.7 | 5 | ×1.22 | ×9.6 |
| + the database emptied in one round trip<br>`slow,hash=cheap,app=shared,clean=one_string` | 34.1 | 31.8 | 5 | ×1.07 | ×10.3 |
| + commits that do not wait for the disk<br>`slow,hash=cheap,app=shared,clean=one_string,commit=async` | 47.4 | 43.1 | 5 | ×1.10 | ×11.4 |
| + time-machine instead of freezegun<br>`fast,freeze=all,loop=function` | 31.3 | 21.9 | 5 | ×1.43 | ×16.3 |
| + the clock stopped only where a test reads it<br>`fast,loop=function` | 21.8 | 21.5 | 5 | ×1.01 | ×16.5 |
| + one event loop, one connection pool<br>`fast` | 30.8 | 18.4 | 5 | ×1.67 | ×27.6 |
| + a process per core<br>`fast,workers=auto` | 14.6 | 8.6 | 5 | ×1.69 | ×46.6 |
| + the schema copied from a template<br>`fast,workers=auto,schema=template` | 8.3 | 8.4 | 5 | ×0.99 | ×46.2 |

### The slow harness with one brake taken off

| Change | the slow harness, s | With the change, s | Runs of each | Faster by |
|---|---:|---:|---:|---:|
| bcrypt at its lowest cost<br>`slow,hash=cheap` | 493.4 | 62.4 | 2 | ×7.91 |
| the fixtures' hash computed once<br>`slow,hash=cached` | 438.6 | 274.3 | 2 | ×1.60 |
| one application for the run<br>`slow,app=shared` | 438.1 | 426.9 | 2 | ×1.03 |
| the database emptied in one round trip<br>`slow,clean=one_string` | 439.6 | 435.7 | 2 | ×1.01 |
| the database emptied by TRUNCATE<br>`slow,clean=truncate` | 434.5 | 432.4 | 2 | ×1.00 |
| commits that do not wait for the disk<br>`slow,commit=async` | 462.9 | 449.2 | 2 | ×1.03 |
| time-machine instead of freezegun<br>`slow,clock=time_machine` | 434.4 | 421.5 | 2 | ×1.03 |
| the clock stopped only where a test reads it<br>`slow,freeze=marked` | 460.6 | 447.2 | 2 | ×1.03 |
| time-machine and one event loop<br>`slow,clock=time_machine,loop=session` | 437.1 | 414.5 | 2 | ×1.05 |
| a process per core<br>`slow,workers=auto` | 438.8 | 128.5 | 2 | ×3.42 |

### The fast harness with one brake put back

| Change | the fast harness, s | With the change, s | Runs of each | Slower by |
|---|---:|---:|---:|---:|
| bcrypt as in production<br>`fast,hash=prod` | 22.2 | 512.1 | 2 | ×23.10 |
| bcrypt as in production, the fixtures' hash computed once<br>`fast,hash=cached` | 16.0 | 239.5 | 2 | ×14.95 |
| an application per test<br>`fast,app=per_test` | 14.8 | 22.3 | 5 | ×1.51 |
| the database emptied table by table<br>`fast,clean=per_table` | 14.8 | 15.7 | 5 | ×1.06 |
| the database emptied by TRUNCATE<br>`fast,clean=truncate` | 14.5 | 17.7 | 5 | ×1.22 |
| commits that wait for the disk<br>`fast,commit=sync` | 14.4 | 14.6 | 5 | ×1.01 |
| freezegun<br>`fast,clock=freezegun` | 14.4 | 15.3 | 5 | ×1.07 |
| the clock stopped for every test<br>`fast,freeze=all` | 14.2 | 14.4 | 5 | ×1.02 |
| an event loop per test<br>`fast,loop=function` | 18.4 | 30.8 | 5 | ×1.67 |
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
