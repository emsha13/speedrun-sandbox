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
| `clean` | a `DELETE` per table through SQLAlchemy | one string of `DELETE`s to the driver, for the tables with a row (or `one_string`: for every table; or `truncate`) | `tests/harness/cleaning.py` |
| `clock` | freezegun | time-machine | `tests/harness/clock.py` |
| `freeze` | the clock stopped for every test | only for the tests marked `freeze_time` | `tests/harness/clock.py` |
| `imports` | the SDKs of the services outside loaded with the application | only where they are called | `tests/harness/imports.py` |
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
| + bcrypt at its lowest cost<br>`slow,hash=cheap` | 3925.4 | 952.9 | 2 | ×4.12 | ×4.1 |
| + one application for the run<br>`slow,hash=cheap,app=shared` | 1091.8 | 641.9 | 5 | ×1.70 | ×7.0 |
| + the database emptied in one round trip<br>`slow,hash=cheap,app=shared,clean=one_string` | 540.9 | 275.5 | 5 | ×1.96 | ×13.8 |
| + commits that do not wait for the disk<br>`slow,hash=cheap,app=shared,clean=one_string,commit=async` | 261.7 | 259.9 | 5 | ×1.01 | ×13.8 |
| + only the tables with a row emptied<br>`slow,hash=cheap,app=shared,clean=exists,commit=async` | 387.6 | 392.9 | 5 | ×0.99 | ×13.7 |
| + time-machine instead of freezegun<br>`fast,freeze=all,loop=function,imports=eager` | 404.3 | 313.8 | 5 | ×1.29 | ×17.6 |
| + the SDKs loaded only where they are called<br>`fast,freeze=all,loop=function` | 338.0 | 337.0 | 5 | ×1.00 | ×17.6 |
| + the clock stopped only where a test reads it<br>`fast,loop=function` | 324.2 | 319.8 | 5 | ×1.01 | ×17.9 |
| + one event loop, one connection pool<br>`fast` | 273.1 | 103.2 | 5 | ×2.65 | ×47.3 |
| + a process per core<br>`fast,workers=auto` | 91.4 | 47.5 | 5 | ×1.92 | ×91.1 |
| + the schema copied from a template<br>`fast,workers=auto,schema=template` | 43.6 | 42.2 | 5 | ×1.03 | ×94.1 |

### The slow harness with one brake taken off

| Change | the slow harness, s | With the change, s | Runs of each | Faster by |
|---|---:|---:|---:|---:|
| bcrypt at its lowest cost<br>`slow,hash=cheap` | 3925.4 | 952.9 | 2 | ×4.12 |
| the fixtures' hash computed once<br>`slow,hash=cached` | 3920.7 | 1166.5 | 2 | ×3.36 |
| one application for the run<br>`slow,app=shared` | 3869.5 | 3485.5 | 2 | ×1.11 |
| the database emptied in one round trip<br>`slow,clean=one_string` | 4161.6 | 3825.7 | 2 | ×1.09 |
| the database emptied by TRUNCATE<br>`slow,clean=truncate` | 3920.2 | 3939.2 | 2 | ×1.00 |
| only the tables with a row emptied<br>`slow,clean=exists` | 4940.6 | 4571.3 | 2 | ×1.08 |
| commits that do not wait for the disk<br>`slow,commit=async` | 4142.7 | 4133.5 | 2 | ×1.00 |
| time-machine instead of freezegun<br>`slow,clock=time_machine` | 3437.8 | 3326.9 | 2 | ×1.03 |
| the clock stopped only where a test reads it<br>`slow,freeze=marked` | 5002.1 | 4845.2 | 2 | ×1.03 |
| time-machine and one event loop<br>`slow,clock=time_machine,loop=session` | 3591.1 | 3330.3 | 2 | ×1.08 |
| the SDKs loaded only where they are called<br>`slow,imports=lazy` | 4224.0 | 4130.7 | 2 | ×1.02 |
| a process per core<br>`slow,workers=auto` | 3913.3 | 1123.1 | 2 | ×3.48 |

### The fast harness with one brake put back

| Change | the fast harness, s | With the change, s | Runs of each | Slower by |
|---|---:|---:|---:|---:|
| bcrypt as in production<br>`fast,hash=prod` | 94.1 | 3256.1 | 2 | ×34.61 |
| bcrypt as in production, the fixtures' hash computed once<br>`fast,hash=cached` | 82.1 | 297.1 | 2 | ×3.62 |
| an application per test<br>`fast,app=per_test` | 83.4 | 487.8 | 5 | ×5.85 |
| the database emptied table by table<br>`fast,clean=per_table` | 94.6 | 408.7 | 5 | ×4.32 |
| every table emptied, in one round trip<br>`fast,clean=one_string` | 92.4 | 96.3 | 5 | ×1.04 |
| the database emptied by TRUNCATE<br>`fast,clean=truncate` | 92.8 | 873.1 | 5 | ×9.41 |
| commits that wait for the disk<br>`fast,commit=sync` | 79.0 | 79.9 | 5 | ×1.01 |
| freezegun<br>`fast,clock=freezegun` | 83.3 | 84.3 | 5 | ×1.01 |
| the clock stopped for every test<br>`fast,freeze=all` | 67.1 | 67.7 | 5 | ×1.01 |
| the SDKs loaded with the application<br>`fast,imports=eager` | 96.1 | 96.7 | 5 | ×1.01 |
| an event loop per test<br>`fast,loop=function` | 103.2 | 273.1 | 5 | ×2.65 |
<!-- /numbers -->

Three series, because the changes do not add up. Each brake hides the others: with all of them
on, taking one off gives little, and with all of them off, putting one back costs a lot. An
application per test is worth ×1.1 in the slow harness and ×6 in the fast one; emptying the
database table by table, ×1.1 and ×4.3. So there is the usual walk — one change after another —
and two more: the slow harness with one brake taken off, and the fast harness with one brake put
back.

The biggest brake is bcrypt. It is paid per user made and per sign-in, and a test of the
workspace makes the six people of an organisation, each with a hash of their own, as such
fixtures usually do. Taken off the slow harness it makes it ×4 faster; put back into the fast one,
×35 slower. Computing the fixtures' hash once takes most of it away, and what is left is the
sign-ins.

What grows with the application: at 201 tables and 360 routes, the application built once for the
run and the database emptied in one round trip are among the biggest of the changes — put back
into the fast harness, they make it ×6 and ×4.3 slower — where at six tables they were worth a few
per cent. `TRUNCATE` gets worse with every table: it is the slowest way to empty two hundred
tables of three rows each, ×9 slower than the fast way.

Some choices are here although they give next to nothing, because they are what gets suggested,
and the numbers say why:

- **Commits that do not wait for the disk**, ×1.01 either way. A test commits a few times, and on
  the runners a wait for the disk is short; it adds up to less than one runner differs from
  another.
- **time-machine, the clock stopped only where it is read, the SDKs loaded only where they are
  called** — each ×1.00–1.03 by itself. freezegun's cost is the number of modules loaded times
  the number of times the clock is stopped and let go, so it takes all three to make it big: with
  the SDKs loaded (4,430 modules against 963) and the clock stopped for every test, going over to
  time-machine is ×1.3. Take away any one of the three and the other two are cheap.
- **Only the tables with a row emptied**, ×0.99–1.08. A `DELETE` over an empty table is already
  cheap once all of them go in one round trip; asking which tables have a row costs nearly what
  it saves.
- **The schema copied from a template**, ×1.03. A process builds its schema once, in a few
  seconds; there is little to save until the schema has many migrations.

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
of accounts creates a user or two and signs in; a test of the workspace creates six people, each
with a hash of their own. Inside the suite
`bcrypt.gensalt` defaults to four rounds. The hashes are as real — salted, and checked by the same
`checkpw`, which reads the cost out of the hash — and the application's code is not touched.
`cached` is the half-measure for those who would rather not touch the cost: the hash the fixtures
store is computed once a run, and every sign-in still pays in full.

**`app`.** `create_app()` registers every route, and the first request FastAPI serves builds what
it needs to validate them. The harness builds the application once; the lifespan still runs
around every test. This grows with the number of routes.

**`clean`.** Before each test every table is emptied. Through SQLAlchemy that is a statement and a
round trip per table; asyncpg takes one string of all the statements and runs it in one. This
grows with the number of tables. A test writes to a handful of the tables, so the fast way first
asks, in one query, which tables have a row, and empties only those; `one_string` empties every
table. `TRUNCATE` is there because it is the first thing everybody suggests.

**`clock`.** freezegun stops the clock by finding every loaded module that holds `datetime`, `date`
or `time` and swapping the reference, at every start and every stop; the more is imported, the
longer it takes. time-machine patches the C functions once. The tests are the same under both: the
fixture gives them `freezer.tick()` and `freezer.move_to()`. There is a second difference:
freezegun also stops `time.monotonic`, the event loop's own clock, so under it a timeout never
fires and a test that should fail hangs instead.

**`freeze`.** A suite ends up with the clock stopped for every test when the mark is put on whole
modules to be safe. Under `marked` only the tests that read the clock have it stopped.

**`imports`.** The application imports the SDKs of the services outside — anthropic, boto3,
stripe — inside the functions that call them (`app/workspace/outside.py`), and the tests call none
of them. The usual way is to import them at the top of the module, and then every test process
loads some 3,500 modules more, and freezegun goes through every one of them each time it stops the
clock or lets it go. Under `eager` the harness loads them before the first test, as such an
application would.

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
