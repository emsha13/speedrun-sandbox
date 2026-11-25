# fastapi-pytest-speedrun

One FastAPI service, one test suite of 3,200 tests, and a test harness put together from
independent choices — each with a slow value and a fast one. The tests never change. What changes
is the harness under them, one choice at a time, and every combination is timed.

The service is a team workspace, built to the size at which the harness starts to matter: 201
tables and 360 routes. Underneath is the part nearly every application has — registration with a
mailed code, sign-in by address or by phone number, refresh tokens, password reset, changes of
password, address and number, sessions, request limits, users as an admin sees them. On top of it
are organisations with roles and invitations, projects and tasks, documents with versions, a
calendar with rooms, a help desk with deadlines, a CRM, invoices and payments, chat and
notifications, integrations, files, and reports. FastAPI, SQLAlchemy 2 (async), asyncpg, Postgres,
Redis, bcrypt, PyJWT. The tests go through the HTTP door against a real Postgres; Redis is a fake
one.

Most of the workspace's routes are the routine five — list, read, create, update, delete — and
come from one builder that reads the model (`app/workspace/crud.py`); the routes with rules of
their own are written by hand. The tests follow the same split: `tests/workspace/test_doors.py`
runs one set of tests over every table the builder made doors for, and a file a section tests
what that section does.

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
3,206 tests, wall time of the whole `pytest` process. Every row is two harnesses run in turns on
one machine — the medians of each there and their ratio. Seconds from two different rows come
from two different machines and are not to be compared: the same harness on two machines differs
by more than most of these changes are worth. The ratios are what to read.

### One change after another

| Change | Before, s | After, s | Runs of each | This change | All so far |
|---|---:|---:|---:|---:|---:|
| + bcrypt at its lowest cost<br>`slow,hash=cheap` | 1711.5 | 872.3 | 2 | ×1.96 | ×2.0 |
| + one application for the run<br>`slow,hash=cheap,app=shared` | 856.1 | 464.4 | 5 | ×1.84 | ×3.6 |
| + the database emptied in one round trip<br>`slow,hash=cheap,app=shared,clean=one_string` | 790.1 | 358.3 | 5 | ×2.21 | ×8.0 |
| + commits that do not wait for the disk<br>`slow,hash=cheap,app=shared,clean=one_string,commit=async` | 208.2 | 191.9 | 5 | ×1.09 | ×8.7 |
| + time-machine instead of freezegun<br>`fast,freeze=all,loop=function` | 210.1 | 182.2 | 5 | ×1.15 | ×10.0 |
| + the clock stopped only where a test reads it<br>`fast,loop=function` | 309.2 | 307.1 | 5 | ×1.01 | ×10.0 |
| + one event loop, one connection pool<br>`fast` | 180.8 | 75.0 | 5 | ×2.41 | ×24.2 |
| + a process per core<br>`fast,workers=auto` | 80.2 | 46.7 | 5 | ×1.72 | ×41.6 |
| + the schema copied from a template<br>`fast,workers=auto,schema=template` | 41.5 | 41.6 | 5 | ×1.00 | ×41.5 |

### The slow harness with one brake taken off

| Change | the slow harness, s | With the change, s | Runs of each | Faster by |
|---|---:|---:|---:|---:|
| bcrypt at its lowest cost<br>`slow,hash=cheap` | 1711.5 | 872.3 | 2 | ×1.96 |
| the fixtures' hash computed once<br>`slow,hash=cached` | 1671.8 | 1066.7 | 2 | ×1.57 |
| one application for the run<br>`slow,app=shared` | 2407.4 | 1839.9 | 2 | ×1.31 |
| the database emptied in one round trip<br>`slow,clean=one_string` | 2115.6 | 1739.7 | 2 | ×1.22 |
| the database emptied by TRUNCATE<br>`slow,clean=truncate` | 1712.5 | 1787.1 | 2 | ×0.96 |
| commits that do not wait for the disk<br>`slow,commit=async` | 2344.9 | 2326.6 | 2 | ×1.01 |
| time-machine instead of freezegun<br>`slow,clock=time_machine` | 1732.8 | 1668.0 | 2 | ×1.04 |
| the clock stopped only where a test reads it<br>`slow,freeze=marked` | 2349.2 | 2277.9 | 2 | ×1.03 |
| time-machine and one event loop<br>`slow,clock=time_machine,loop=session` | 1718.1 | 1541.9 | 2 | ×1.11 |
| a process per core<br>`slow,workers=auto` | 2435.0 | 841.8 | 2 | ×2.89 |

### The fast harness with one brake put back

| Change | the fast harness, s | With the change, s | Runs of each | Slower by |
|---|---:|---:|---:|---:|
| bcrypt as in production<br>`fast,hash=prod` | 75.3 | 897.9 | 2 | ×11.93 |
| bcrypt as in production, the fixtures' hash computed once<br>`fast,hash=cached` | 76.5 | 302.6 | 2 | ×3.96 |
| an application per test<br>`fast,app=per_test` | 78.9 | 477.8 | 5 | ×6.05 |
| the database emptied table by table<br>`fast,clean=per_table` | 78.2 | 287.3 | 5 | ×3.67 |
| the database emptied by TRUNCATE<br>`fast,clean=truncate` | 84.3 | 857.6 | 5 | ×10.17 |
| commits that wait for the disk<br>`fast,commit=sync` | 99.4 | 116.4 | 5 | ×1.17 |
| freezegun<br>`fast,clock=freezegun` | 107.9 | 107.7 | 5 | ×1.00 |
| the clock stopped for every test<br>`fast,freeze=all` | 74.3 | 75.5 | 5 | ×1.02 |
| an event loop per test<br>`fast,loop=function` | 75.0 | 180.8 | 5 | ×2.41 |
<!-- /numbers -->

Three series, because the changes do not add up. Each brake hides the others: with all of them
on, taking one off gives little, and with all of them off, putting one back costs a lot. An
application per test is worth ×1.3 in the slow harness and ×6 in the fast one; emptying the
database table by table, ×1.2 and ×3.7. So there is the usual walk — one change after another —
and two more: the slow harness with one brake taken off, and the fast harness with one brake put
back.

What grows with the application: at 201 tables and 360 routes, the application built once for the
run and the database emptied in one round trip are now among the biggest of the changes —
put back into the fast harness, they make it ×6 and ×3.7 slower — where at six tables they were
worth a few per cent. bcrypt does not grow — it is paid per
user made and per sign-in — and next to everything else it shrinks. `TRUNCATE` gets worse with
every table: it is the slowest way to empty two hundred tables of three rows each.

## Run it

Postgres on `localhost` with user and password `postgres` (or your own in `.env`, see
`.env.example`), and [uv](https://docs.astral.sh/uv/). No Redis is needed.

    uv sync
    uv run pytest                                     # the fast harness, one process
    uv run python speedrun.py slow                    # the slow one, timed
    uv run python speedrun.py slow,hash=cheap fast    # any harnesses, one after another
    uv run python speedrun.py fast -- -x -k login     # what follows `--` goes to pytest

The suite creates the database `speedrun_test` at the start and drops it at the end.

## Where to look

    app/                  the service
    app/workspace/        the workspace: models, the builder of routine doors, the sections
    tests/api/            the tests of accounts and sign-in, through the application to the database
    tests/workspace/      the tests of the workspace, the same way
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
