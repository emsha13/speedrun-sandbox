import jwt
import pytest

from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select

from app.models import AuditEvent, LoginAttempt, RefreshSession
from app.settings import settings
from tests.utils import bearer, sign_in

WRONG = 'Wr0ngPassword'


async def test_login(client, user, password, mocker):
    response = await client.post('/auth/login', json={'email': user.email, 'password': password})

    assert response.status_code == 200
    assert response.json() == {'access_token': mocker.ANY, 'refresh_token': mocker.ANY, 'token_type': 'bearer'}


async def test_login_address_in_another_case(client, user, password):
    response = await client.post('/auth/login', json={'email': user.email.upper(), 'password': password})

    assert response.status_code == 200


async def test_login_is_recorded(client, user, password, db_session):
    await sign_in(client, user.email, password)

    assert (await db_session.scalar(select(AuditEvent))).kind == 'login'


async def test_login_remembers_the_device(client, user, password, db_session):
    await sign_in(client, user.email, password, user_agent='Firefox on Linux')

    assert (await db_session.scalar(select(RefreshSession))).user_agent == 'Firefox on Linux'


async def test_login_stores_a_digest_not_the_token(client, user, password, db_session):
    tokens = await sign_in(client, user.email, password)

    assert (await db_session.scalar(select(RefreshSession))).token_digest != tokens['refresh_token']


async def test_every_login_is_a_session_of_its_own(client, user, password, db_session):
    first = await sign_in(client, user.email, password)
    second = await sign_in(client, user.email, password)

    assert first['refresh_token'] != second['refresh_token']
    assert await db_session.scalar(select(func.count()).select_from(RefreshSession)) == 2


async def test_login_wrong_password(client, user):
    response = await client.post('/auth/login', json={'email': user.email, 'password': WRONG})

    assert response.status_code == 401
    assert response.json() == {'detail': 'wrong email or password'}


async def test_login_unknown_address_answers_the_same(client, email):
    response = await client.post('/auth/login', json={'email': email, 'password': WRONG})

    assert response.status_code == 401
    assert response.json() == {'detail': 'wrong email or password'}


async def test_login_unverified(client, inactive_user, password):
    response = await client.post('/auth/login', json={'email': inactive_user.email, 'password': password})

    assert response.status_code == 403
    assert response.json() == {'detail': 'email is not verified'}


async def test_login_unverified_wrong_password(client, inactive_user):
    response = await client.post('/auth/login', json={'email': inactive_user.email, 'password': WRONG})

    assert response.status_code == 401


async def fail(client, email, times):
    for _ in range(times):
        response = await client.post('/auth/login', json={'email': email, 'password': WRONG})
        assert response.status_code == 401


async def test_login_locks_after_five_failures(client, user, password):
    await fail(client, user.email, 5)
    response = await client.post('/auth/login', json={'email': user.email, 'password': password})

    assert response.status_code == 429
    assert response.json() == {'detail': 'too many attempts, try later'}


async def test_login_four_failures_do_not_lock(client, user, password):
    await fail(client, user.email, 4)
    response = await client.post('/auth/login', json={'email': user.email, 'password': password})

    assert response.status_code == 200


async def test_login_success_forgets_the_failures(client, user, password, db_session):
    await fail(client, user.email, 4)
    await sign_in(client, user.email, password)
    await fail(client, user.email, 4)

    assert await db_session.scalar(select(func.count()).select_from(LoginAttempt)) == 4
    assert (await client.post('/auth/login', json={'email': user.email, 'password': password})).status_code == 200


@pytest.mark.freeze_time
async def test_login_lock_lifts_in_fifteen_minutes(client, user, password, freezer):
    await fail(client, user.email, 5)
    freezer.tick(15 * 60)
    response = await client.post('/auth/login', json={'email': user.email, 'password': password})

    assert response.status_code == 200


@pytest.mark.freeze_time
async def test_login_lock_holds_for_fifteen_minutes(client, user, password, freezer):
    await fail(client, user.email, 5)
    freezer.tick(15 * 60 - 1)
    response = await client.post('/auth/login', json={'email': user.email, 'password': password})

    assert response.status_code == 429


@pytest.mark.freeze_time
async def test_login_old_failures_do_not_count(client, user, password, freezer):
    await fail(client, user.email, 3)
    freezer.tick(15 * 60)
    await fail(client, user.email, 3)
    response = await client.post('/auth/login', json={'email': user.email, 'password': password})

    assert response.status_code == 200


async def test_login_lock_is_per_address(client, user, other_user, password):
    await fail(client, user.email, 5)
    response = await client.post('/auth/login', json={'email': other_user.email, 'password': password})

    assert response.status_code == 200


async def test_login_unknown_address_locks_too(client, email):
    await fail(client, email, 5)
    response = await client.post('/auth/login', json={'email': email, 'password': WRONG})

    assert response.status_code == 429


@pytest.mark.parametrize('body', [{}, {'email': 'ann@example.com'}, {'password': 'x'}, {'email': 'ann', 'password': 'x'}])
async def test_login_malformed(client, body):
    response = await client.post('/auth/login', json=body)

    assert response.status_code == 422


@pytest.mark.freeze_time
async def test_access_token_expires(client, tokens, freezer):
    freezer.tick(15 * 60 + 1)
    response = await client.get('/me', headers=bearer(tokens['access_token']))

    assert response.status_code == 401


@pytest.mark.freeze_time
async def test_access_token_lives_fifteen_minutes(client, tokens, freezer):
    freezer.tick(15 * 60 - 1)
    response = await client.get('/me', headers=bearer(tokens['access_token']))

    assert response.status_code == 200


@pytest.mark.parametrize('headers', [
    {}, {'Authorization': 'Bearer nonsense'}, {'Authorization': 'Basic YW5uOnB3'}, {'Authorization': 'Bearer '},
])
async def test_no_token_no_entry(client, user, headers):
    response = await client.get('/me', headers=headers)

    assert response.status_code == 401
    assert response.json() == {'detail': 'not authenticated'}


async def test_tampered_token(client, tokens):
    header, payload, signature = tokens['access_token'].split('.')
    forged = '.'.join([header, payload, signature[::-1]])

    assert (await client.get('/me', headers=bearer(forged))).status_code == 401


async def test_token_signed_with_another_key(client, user, tokens, db_session):
    session_id = (await db_session.scalar(select(RefreshSession))).id
    forged = jwt.encode(
        {'sub': str(user.id), 'sid': session_id, 'exp': datetime.now(UTC) + timedelta(minutes=5)},
        'k' * len(settings.SECRET_KEY), algorithm='HS256',
    )

    assert (await client.get('/me', headers=bearer(forged))).status_code == 401
