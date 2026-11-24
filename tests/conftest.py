"""Picks the harness. The tests and `tests/fixtures.py` are the same at every stage; what a stage
changes is one module under `tests/stages/`, chosen by the STAGE environment variable (the last
one when unset). `python speedrun.py <stage>` sets it and times the run.

The stage is imported before anything else touches `app`: a stage decides which database the
engine is built for and what a password hash costs, and both are settled at import.
"""
import importlib
import os

from tests.stages import STAGES

stage = STAGES[int(os.environ.get('STAGE', len(STAGES) - 1))]
harness = importlib.import_module(f'tests.stages.{stage.module}')
globals().update({name: value for name, value in vars(harness).items() if not name.startswith('__')})

from tests.fixtures import *                                                                    # noqa: E402, F401, F403
