"""The fixtures every harness shares: the data, the users, the client. None of them changes with
HARNESS — what changes is under `tests/harness/`."""
import pytest

from unittest.mock import AsyncMock, patch

import fakeredis

from httpx import ASGITransport, AsyncClient

from app.models import Role, User
from tests.harness.hashing import hash_for_a_fixture
from tests.utils import bearer, sign_in


@pytest.fixture(autouse=True)
def outbox():
    """No test sends a letter; each can read what would have been sent."""
    with patch('app.emails.send_email', new_callable=AsyncMock) as send_email:
        yield send_email


@pytest.fixture(autouse=True)
def sms_outbox():
    """Nor a text message."""
    with patch('app.sms.send_sms', new_callable=AsyncMock) as send_sms:
        yield send_sms


@pytest.fixture
async def fake_redis(monkeypatch):
    """A Redis of the test's own. Without a server named, every fake client of the process would
    talk to one shared server, and one test's counters would be there for the next."""
    fake = fakeredis.FakeAsyncRedis(server=fakeredis.FakeServer(), decode_responses=True)
    monkeypatch.setattr('app.limits.redis', fake)
    yield fake
    await fake.aclose()


@pytest.fixture
def email():
    return 'ann@example.com'


@pytest.fixture
def other_email():
    return 'bob@example.com'


@pytest.fixture
def admin_email():
    return 'root@example.com'


@pytest.fixture
def phone():
    return '+4915112345678'


@pytest.fixture
def other_phone():
    return '+4915187654321'


@pytest.fixture
def password():
    return 'Passw0rd!'


@pytest.fixture
def new_password():
    return 'N3wPassw0rd!'


@pytest.fixture
def code(mocker):
    """The code the application will draw next, known in advance."""
    mocker.patch('app.security.random_code', return_value='123456')
    return '123456'


@pytest.fixture
def create_user(db_session):
    async def _create_user(email, password, **fields):
        data = {'first_name': 'Ann', 'last_name': 'Lee', 'is_active': True} | fields
        user = User(email=email, password_hash=hash_for_a_fixture(password), **data)
        db_session.add(user)
        await db_session.commit()
        return user
    return _create_user


@pytest.fixture
async def user(create_user, email, password):
    return await create_user(email, password)


@pytest.fixture
async def other_user(create_user, other_email, password):
    return await create_user(other_email, password, first_name='Bob', last_name='Ray')


@pytest.fixture
async def inactive_user(create_user, email, password):
    return await create_user(email, password, is_active=False)


@pytest.fixture
async def user_with_phone(create_user, email, phone, password):
    return await create_user(email, password, phone=phone)


@pytest.fixture
async def admin(create_user, admin_email, password):
    return await create_user(admin_email, password, first_name='Root', last_name='Admin', role=Role.ADMIN)


@pytest.fixture
async def client(fake_redis, app):
    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as async_client:
        yield async_client


@pytest.fixture
async def client_elsewhere(fake_redis, app):
    """The same application, reached from another address."""
    transport = ASGITransport(app=app, client=('203.0.113.7', 4321))
    async with AsyncClient(transport=transport, base_url='http://test') as async_client:
        yield async_client


@pytest.fixture
async def tokens(client, user, password):
    """The user signed in, the way a browser would be: through the door."""
    return await sign_in(client, user.email, password)


@pytest.fixture
def auth(tokens):
    return bearer(tokens['access_token'])


@pytest.fixture
async def other_auth(client, other_user, password):
    return bearer((await sign_in(client, other_user.email, password))['access_token'])


@pytest.fixture
async def phone_auth(client, user_with_phone, password):
    return bearer((await sign_in(client, user_with_phone.email, password))['access_token'])


@pytest.fixture
async def admin_auth(client, admin, password):
    return bearer((await sign_in(client, admin.email, password))['access_token'])
