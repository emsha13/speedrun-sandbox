"""The stages, in order. Each is a whole harness; each differs from the one before by one idea."""
from typing import NamedTuple


class Stage(NamedTuple):
    module: str
    title: str
    # Whether each test gets an event loop of its own or the session shares one.
    loop_scope: str = 'function'
    # Extra arguments for pytest.
    args: tuple = ()


STAGES = [
    Stage('s0_baseline', 'Baseline'),
    Stage('s1_cheap_hashing', 'bcrypt at its lowest cost'),
    Stage('s2_shared_app', 'One application for the whole run'),
    Stage('s3_one_round_trip', 'The database emptied in one round trip'),
    Stage('s4_time_machine', 'time-machine instead of freezegun'),
    Stage('s5_freeze_where_needed', 'The clock stopped only where a test reads it'),
    Stage('s6_session_loop', 'One event loop, one connection pool', loop_scope='session'),
    Stage('s7_xdist', 'A process per core', loop_scope='session', args=('-n', 'auto')),
]
