"""The application a test talks to."""
import pytest

from asgi_lifespan import LifespanManager

from app.db import engine
from app.main import create_app
from tests.harness import options

_application = None


def built_app():
    """The application, built once. A fresh one is expensive twice: `create_app` registers every
    route, and the first request FastAPI routes builds what it needs to validate them. What a test
    may expect of an application of its own is kept: the lifespan runs around every test."""
    global _application
    if _application is None:
        _application = create_app()
    return _application


class _EngineThatStays:
    """What the lifespan has in place of the engine when the pool outlives a test: the same
    connections, and a `dispose` that does nothing. Disposal is right for a process about to
    exit; here the process goes on to the next test, and the pool with it."""
    connect = engine.connect

    async def dispose(self):
        pass


@pytest.fixture
async def app(monkeypatch):
    if options.loop == 'session':
        monkeypatch.setattr('app.main.engine', _EngineThatStays())
    application = built_app() if options.app == 'shared' else create_app()
    async with LifespanManager(application):
        yield application
