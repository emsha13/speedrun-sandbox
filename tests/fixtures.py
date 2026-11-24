"""The fixtures every stage shares: the data, the users, the client. None of them changes from
stage to stage — what changes is under `tests/stages/`."""
import pytest

from unittest.mock import AsyncMock, patch

from httpx import ASGITransport, AsyncClient

from app.models import User
from app.security import hash_password
from tests.utils import bearer, sign_in


@pytest.fixture(autouse=True)
def outbox():
    """No test sends a letter; each can read what would have been sent."""
    with patch('app.emails.send_email', new_callable=AsyncMock) as send_email:
        yield send_email


@pytest.fixture
def email():
    return 'ann@example.com'


@pytest.fixture
def other_email():
    return 'bob@example.com'


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
        user = User(email=email, password_hash=hash_password(password), **data)
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
async def client(app):
    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as async_client:
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
