"""What a process has loaded before the first test.

The application imports the SDKs of the services outside (`app/workspace/outside.py`) inside the
functions that call them, and the tests call none of them: so no test process loads them. The
usual way is to import them at the top of the module — and then every process does, and pays for
it at start-up, and every module they bring is one more that freezegun goes through each time it
stops the clock or lets it go. Under `eager` the harness loads them before the first test, as such
an application would: the same modules, the same seconds, the application's code untouched.
"""
import importlib

from tests.harness import options

# anthropic is some 3,500 modules, boto3 and stripe several hundred each.
SDKS = ('anthropic', 'boto3', 'stripe')


def load_the_sdks() -> None:
    if options.imports == 'eager':
        for name in SDKS:
            importlib.import_module(name)
