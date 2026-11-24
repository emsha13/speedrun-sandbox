import pytest

from sqlalchemy import select

from app.models import AuditEvent, OneTimeCode
from tests.utils import bearer, mailed_code


@pytest.fixture
async def registered(client, email, password, code):
    """An address registered through the door, its code known."""
    response = await client.post(
        '/auth/register', json={'email': email, 'password': password, 'first_name': 'Ann', 'last_name': 'Lee'}
    )
    assert response.status_code == 201
    return response.json()


async def test_verify_email(client, registered, email, code, mocker):
    response = await client.post('/auth/verify-email', json={'email': email, 'code': code})

    assert response.status_code == 200
    assert response.json() == {'access_token': mocker.ANY, 'refresh_token': mocker.ANY, 'token_type': 'bearer'}


async def test_verify_email_signs_the_user_in(client, registered, email, code):
    tokens = (await client.post('/auth/verify-email', json={'email': email, 'code': code})).json()

    response = await client.get('/me', headers=bearer(tokens['access_token']))
    assert response.status_code == 200
    assert response.json()['is_active'] is True


async def test_verify_email_is_recorded(client, registered, email, code, db_session):
    await client.post('/auth/verify-email', json={'email': email, 'code': code})

    assert (await db_session.scalar(select(AuditEvent))).kind == 'email_verified'


async def test_verify_email_then_sign_in(client, registered, email, password, code):
    await client.post('/auth/verify-email', json={'email': email, 'code': code})

    response = await client.post('/auth/login', json={'email': email, 'password': password})
    assert response.status_code == 200


async def test_verify_email_wrong_code(client, registered, email):
    response = await client.post('/auth/verify-email', json={'email': email, 'code': '000000'})

    assert response.status_code == 400
    assert response.json() == {'detail': 'invalid code'}


async def test_verify_email_wrong_code_is_counted(client, registered, email, db_session):
    await client.post('/auth/verify-email', json={'email': email, 'code': '000000'})
    await client.post('/auth/verify-email', json={'email': email, 'code': '000001'})

    assert (await db_session.scalar(select(OneTimeCode))).attempts == 2


async def test_verify_email_right_code_after_a_wrong_one(client, registered, email, code):
    await client.post('/auth/verify-email', json={'email': email, 'code': '000000'})
    response = await client.post('/auth/verify-email', json={'email': email, 'code': code})

    assert response.status_code == 200


async def test_verify_email_too_many_attempts(client, registered, email, code):
    for _ in range(5):
        await client.post('/auth/verify-email', json={'email': email, 'code': '000000'})
    response = await client.post('/auth/verify-email', json={'email': email, 'code': code})

    assert response.status_code == 400
    assert response.json() == {'detail': 'too many attempts'}


@pytest.mark.freeze_time
async def test_verify_email_code_expires(client, registered, email, code, freezer):
    freezer.tick(10 * 60)
    response = await client.post('/auth/verify-email', json={'email': email, 'code': code})

    assert response.status_code == 400
    assert response.json() == {'detail': 'code expired'}


@pytest.mark.freeze_time
async def test_verify_email_code_lives_ten_minutes(client, registered, email, code, freezer):
    freezer.tick(10 * 60 - 1)
    response = await client.post('/auth/verify-email', json={'email': email, 'code': code})

    assert response.status_code == 200


async def test_verify_email_code_works_once(client, registered, email, code):
    await client.post('/auth/verify-email', json={'email': email, 'code': code})
    response = await client.post('/auth/verify-email', json={'email': email, 'code': code})

    assert response.status_code == 400


async def test_verify_email_unknown_address(client, registered, other_email, code):
    response = await client.post('/auth/verify-email', json={'email': other_email, 'code': code})

    assert response.status_code == 400
    assert response.json() == {'detail': 'invalid code'}


async def test_verify_email_already_verified(client, user):
    response = await client.post('/auth/verify-email', json={'email': user.email, 'code': '123456'})

    assert response.status_code == 400


@pytest.mark.parametrize('malformed', ['', '12345', '1234567', 'abcdef', '12 456'])
async def test_verify_email_malformed_code(client, registered, email, malformed):
    response = await client.post('/auth/verify-email', json={'email': email, 'code': malformed})

    assert response.status_code == 422


async def test_resend_code(client, inactive_user, outbox):
    response = await client.post('/auth/resend-code', json={'email': inactive_user.email})

    assert response.status_code == 204
    outbox.assert_awaited_once()


async def test_resent_code_verifies(client, inactive_user, outbox):
    await client.post('/auth/resend-code', json={'email': inactive_user.email})
    response = await client.post(
        '/auth/verify-email', json={'email': inactive_user.email, 'code': mailed_code(outbox)}
    )

    assert response.status_code == 200


async def test_resend_code_retires_the_one_before(client, inactive_user, mocker):
    mocker.patch('app.security.random_code', side_effect=['111111', '222222'])
    await client.post('/auth/resend-code', json={'email': inactive_user.email})
    await client.post('/auth/resend-code', json={'email': inactive_user.email})

    old = await client.post('/auth/verify-email', json={'email': inactive_user.email, 'code': '111111'})
    new = await client.post('/auth/verify-email', json={'email': inactive_user.email, 'code': '222222'})
    assert (old.status_code, new.status_code) == (400, 200)


async def test_resend_code_starts_the_count_anew(client, registered, email, code):
    for _ in range(5):
        await client.post('/auth/verify-email', json={'email': email, 'code': '000000'})
    await client.post('/auth/resend-code', json={'email': email})
    response = await client.post('/auth/verify-email', json={'email': email, 'code': code})

    assert response.status_code == 200


async def test_resend_code_unknown_address(client, email, outbox):
    response = await client.post('/auth/resend-code', json={'email': email})

    assert response.status_code == 204
    outbox.assert_not_awaited()


async def test_resend_code_verified_address(client, user, outbox):
    response = await client.post('/auth/resend-code', json={'email': user.email})

    assert response.status_code == 204
    outbox.assert_not_awaited()
