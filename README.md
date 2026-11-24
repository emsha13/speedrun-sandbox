# fastapi-pytest-speedrun

One small FastAPI service, one test suite of 232 tests, and eight versions of the test harness
under it. The tests never change. Each harness differs from the one before by a single idea, and
each is timed.

The service is the part nearly every application has: registration with a mailed code, sign-in,
refresh tokens, password reset, change of password and of address, a profile, a list of sessions,
deletion of the account. FastAPI, SQLAlchemy 2 (async), asyncpg, Postgres, bcrypt, PyJWT. The tests
go through the HTTP door against a real Postgres.

## The stages

| # | Stage | What changes | Laptop, s | × |
|---|---|---|---:|---:|
| 0 | Baseline | — | 182.7 | 1.0 |
| 1 | bcrypt at its lowest cost | the suite hashes with 4 rounds, not 12 | 32.0 | 5.7 |
| 2 | One application for the whole run | `create_app()` once, not once a test | 28.3 | 6.5 |
| 3 | The database emptied in one round trip | one string of `DELETE`s to the driver, not a statement per table | 26.0 | 7.0 |
| 4 | time-machine instead of freezegun | the `freezer` fixture is built on another library | 21.4 | 8.5 |
| 5 | The clock stopped only where a test reads it | no mark, no frozen clock | 20.3 | 9.0 |
| 6 | One event loop, one connection pool | the session shares a loop, so the engine keeps its connections | 13.7 | 13.3 |
| 7 | A process per core | `pytest -n auto`, a database per worker | — | — |

The laptop column is one run of each stage, wall time of the whole `pytest` process, on a
two-core Celeron N4020 with 3.6 GB of memory, which is too small to run stage 7. The numbers to
trust are the ones GitHub measures: the [speedrun workflow](.github/workflows/speedrun.yml) runs
every stage five times on one machine and puts the medians in the run's summary.

About two seconds of every number is the same at every stage — the interpreter starting, the
imports, the database created and dropped — so the later stages are closer to their floor than
the ratios say.

## Run it

Postgres on `localhost` with user and password `postgres` (or your own in `.env`, see
`.env.example`), and [uv](https://docs.astral.sh/uv/):

    uv sync
    uv run python speedrun.py            # every stage in order, with a table at the end
    uv run python speedrun.py 0 6        # two of them
    uv run python speedrun.py 3 -- -x -k login    # what follows `--` goes to pytest
    uv run pytest                        # the finished harness, one process
    uv run pytest -n auto                # the finished harness, a process per core

The suite creates the database `speedrun_test` at the start and drops it at the end.

## Where to look

    app/                  the service
    tests/test_*.py       the tests — the same at every stage
    tests/fixtures.py     users, client, tokens — the same at every stage
    tests/stages/         the eight harnesses
    tests/conftest.py     picks one by the STAGE environment variable
    speedrun.py           runs a stage and times it

A stage is a whole file, so a step is a diff:

    diff -u tests/stages/s0_baseline.py tests/stages/s1_cheap_hashing.py

## What each step is

**1. bcrypt at its lowest cost.** A password hash is slow on purpose: a quarter of a second at
the default cost. A test creates a user or two and signs in, so it pays that two or three times.
Inside the suite `bcrypt.gensalt` defaults to four rounds. The hashes are as real — salted, and
checked by the same `checkpw`, which reads the cost out of the hash. The application's code is
not touched. This is most of the win, here and in every suite that signs users in.

**2. One application for the whole run.** `create_app()` registers every route, and the first
request FastAPI serves builds what it needs to validate them. The harness builds the application
once; the lifespan still runs around every test. With fifteen routes this is a small step. It
grows with the application.

**3. The database emptied in one round trip.** Before each test every table is emptied. Through
SQLAlchemy that is a statement and a round trip per table; asyncpg takes one string of all the
statements and runs it in one. With five tables this is a small step too. It grows with the
schema.

**4. time-machine instead of freezegun.** freezegun stops the clock by finding every loaded module
that holds `datetime`, `date` or `time` and swapping the reference, at every start and every stop.
time-machine patches the C functions once. The tests are the same under both: the fixture gives
them `freezer.tick()` and `freezer.move_to()`. There is a second difference, which matters at
stage 6: freezegun also stops `time.monotonic`, the event loop's own clock, so under it a
timeout never fires and a test that should fail hangs instead; time-machine with `tick=False`
leaves the monotonic clock running.

**5. The clock stopped only where a test reads it.** Up to here every test runs with the clock
stopped, the way a suite ends up when the mark is put on whole modules to be safe. From here only
the tests marked `freeze_time` do: 18 of the 232.

**6. One event loop, one connection pool.** pytest-asyncio gives every test a new event loop by
default, and an asyncpg connection belongs to the loop that opened it — so the pool is thrown away
after every test and each test opens its own connections. With one loop for the session the pool
lives as long as the run. Three things come with it: the application's shutdown must not dispose
of the engine, a task a test forgot must be cancelled before the next test, and the clock library
must leave the loop's clock alone (step 4).

**7. A process per core.** pytest-xdist, with a database per worker: the worker's id goes on the
end of the database's name before the engine is built. Last, because it multiplies whatever the
other steps left — and because it is the one step that costs memory.

## What is not here

Three more things sped up the suite these steps were first worked out on, and are left out
because they change the application rather than the harness: a provider's SDK imported at the
moment of the call and not at start-up, a migration check that read the migrations directory at
every start-up, and a test that reached the real network.

How the time was found matters as much as the list. What worked: timing every fixture's setup
with a `pytest_fixture_setup` hook wrapper, and comparing the first request to a fresh
application with the second. What did not: reading the cumulative times of coroutines out of
cProfile.
