import pytest

from datetime import UTC, datetime

from sqlalchemy import func, select

from app.models import OneTimeCode, RefreshSession, User
from app.security import verify_password
from tests.utils import mailed_code, mailed_to


@pytest.fixture
def registration(email, password):
    return {'email': email, 'password': password, 'first_name': 'Ann', 'last_name': 'Lee'}


async def test_register(client, registration, email, mocker):
    response = await client.post('/auth/register', json=registration)

    assert response.status_code == 201
    assert response.json() == {
        'id': mocker.ANY, 'email': email, 'first_name': 'Ann', 'last_name': 'Lee', 'birth_date': None,
        'is_active': False, 'created_at': mocker.ANY,
    }


async def test_register_mails_a_code(client, registration, email, outbox):
    await client.post('/auth/register', json=registration)

    outbox.assert_awaited_once()
    assert mailed_to(outbox) == email
    assert mailed_code(outbox).isdigit() and len(mailed_code(outbox)) == 6


async def test_register_stores_a_hash_not_the_password(client, registration, password, db_session):
    await client.post('/auth/register', json=registration)

    user = await db_session.scalar(select(User))
    assert user.password_hash != password
    assert verify_password(password, user.password_hash)


async def test_register_stores_a_digest_not_the_code(client, registration, db_session, outbox):
    await client.post('/auth/register', json=registration)

    row = await db_session.scalar(select(OneTimeCode))
    assert row.code_digest != mailed_code(outbox)
    assert row.purpose == 'verify_email'


async def test_register_opens_no_session(client, registration, db_session):
    await client.post('/auth/register', json=registration)

    assert await db_session.scalar(select(func.count()).select_from(RefreshSession)) == 0


async def test_register_lowercases_the_address(client, registration, db_session):
    response = await client.post('/auth/register', json=registration | {'email': 'Ann@Example.COM'})

    assert response.json()['email'] == 'ann@example.com'


@pytest.mark.freeze_time('2026-03-01 10:00:00')
async def test_register_dates_the_user(client, registration, db_session):
    response = await client.post('/auth/register', json=registration)

    assert response.json()['created_at'] == '2026-03-01T10:00:00Z'
    assert (await db_session.scalar(select(User))).created_at == datetime(2026, 3, 1, 10, tzinfo=UTC)


async def test_register_taken_address(client, registration, user, outbox):
    response = await client.post('/auth/register', json=registration)

    assert response.status_code == 409
    assert response.json() == {'detail': 'email is taken'}
    outbox.assert_not_awaited()


async def test_register_address_taken_in_another_case(client, registration, user):
    response = await client.post('/auth/register', json=registration | {'email': user.email.upper()})

    assert response.status_code == 409


async def test_register_address_of_an_unverified_user(client, registration, inactive_user):
    response = await client.post('/auth/register', json=registration)

    assert response.status_code == 409


async def test_register_twice(client, registration, db_session):
    await client.post('/auth/register', json=registration)
    response = await client.post('/auth/register', json=registration)

    assert response.status_code == 409
    assert await db_session.scalar(select(func.count()).select_from(User)) == 1


@pytest.mark.parametrize('weak', ['Sh0rt!', 'nouppercase1', 'NOLOWERCASE1', 'NoDigitsHere', '', 'Aa1' + 'x' * 70])
async def test_register_weak_password(client, registration, weak, db_session):
    response = await client.post('/auth/register', json=registration | {'password': weak})

    assert response.status_code == 422
    assert await db_session.scalar(select(func.count()).select_from(User)) == 0


@pytest.mark.parametrize('address', ['', 'ann', 'ann@', '@example.com', 'ann@example', 'a b@example.com'])
async def test_register_bad_address(client, registration, address):
    response = await client.post('/auth/register', json=registration | {'email': address})

    assert response.status_code == 422


@pytest.mark.parametrize('field', ['first_name', 'last_name'])
@pytest.mark.parametrize('name', ['', ' ', ' Ann', 'Ann ', 'x' * 51])
async def test_register_bad_name(client, registration, field, name):
    response = await client.post('/auth/register', json=registration | {field: name})

    assert response.status_code == 422


@pytest.mark.parametrize('field', ['email', 'password', 'first_name', 'last_name'])
async def test_register_missing_field(client, registration, field):
    del registration[field]
    response = await client.post('/auth/register', json=registration)

    assert response.status_code == 422
