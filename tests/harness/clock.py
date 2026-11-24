"""The stopped clock: the `freezer` fixture and the `freeze_time` mark.

Both libraries give a test the same two things — `freezer.tick(seconds)` and
`freezer.move_to(moment)` — so no test knows which one is underneath.

freezegun stops the clock by finding every loaded module that holds `datetime`, `date` or `time`
and swapping the reference, at every start and every stop. time-machine patches the C functions
once, and stopping the clock costs a fraction of a millisecond.

They differ in one more thing. freezegun stops `time.monotonic` too, and that is the event loop's
own clock: under it a timeout never fires, and a test that should fail hangs instead. time-machine
with `tick=False` stops the calendar and leaves the monotonic clock running.
"""
from datetime import UTC, datetime

import pytest

from tests.harness import options


def in_utc(moment) -> datetime:
    """A moment as a test names it — a string or a datetime, with a zone or without — as the UTC
    instant it means: what has no zone is UTC."""
    if isinstance(moment, str):
        moment = datetime.fromisoformat(moment)
    return moment.replace(tzinfo=UTC) if moment.tzinfo is None else moment.astimezone(UTC)


class _StoppedClock:
    """The clock a test holds under time-machine: stopped, and moved by the test alone."""

    def __init__(self, traveller):
        self._traveller = traveller

    def tick(self, delta=1) -> None:
        """Forward by seconds or by a `timedelta`."""
        self._traveller.shift(delta)

    def move_to(self, moment) -> None:
        self._traveller.move_to(in_utc(moment))


@pytest.fixture
def freezer(request):
    """The clock stopped — at the moment `@pytest.mark.freeze_time('…')` names, or at now."""
    marker = request.node.get_closest_marker('freeze_time')
    moment = in_utc(marker.args[0]) if marker and marker.args else datetime.now(UTC)
    if options.clock == 'freezegun':
        import freezegun

        with freezegun.freeze_time(moment) as frozen:
            yield frozen
    else:
        import time_machine

        with time_machine.travel(moment, tick=False) as traveller:
            yield _StoppedClock(traveller)


def stop_the_clock_for(items) -> None:
    """Called at collection. The clock stops before any other fixture of the test is set up: the
    rows they write are dated by it."""
    for item in items:
        # `all` is how a suite ends up when the mark is put on whole modules to be safe.
        if options.freeze == 'all' or item.get_closest_marker('freeze_time'):
            item.fixturenames.insert(0, 'freezer')
