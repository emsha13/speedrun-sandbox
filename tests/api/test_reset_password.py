import pytest

from sqlalchemy import select

from app.models import AuditEvent
from app.security import verify_password
from tests.utils import bearer, mailed_code, mailed_to, sign_in


@pytest.fixture
async def asked(client, user, code):
    """The user has asked for a reset; the code is known."""
    response = await client.post('/auth/forgot-password', json={'email': user.email})
    assert response.status_code == 204


async def reset(client, email, code, new_password):
    return await client.post(
        '/auth/reset-password', json={'email': email, 'code': code, 'new_password': new_password}
    )


async def test_forgot_password_mails_a_code(client, user, outbox):
    response = await client.post('/auth/forgot-password', json={'email': user.email})

    assert response.status_code == 204
    assert mailed_to(outbox) == user.email
    assert len(mailed_code(outbox)) == 6


async def test_forgot_password_unknown_address(client, email, outbox):
    response = await client.post('/auth/forgot-password', json={'email': email})

    assert response.status_code == 204
    outbox.assert_not_awaited()


async def test_forgot_password_unverified_address(client, inactive_user, outbox):
    response = await client.post('/auth/forgot-password', json={'email': inactive_user.email})

    assert response.status_code == 204
    outbox.assert_not_awaited()


async def test_forgot_password_bad_address(client):
    assert (await client.post('/auth/forgot-password', json={'email': 'ann'})).status_code == 422


async def test_reset_password(client, user, asked, code, new_password, db_session):
    response = await reset(client, user.email, code, new_password)

    assert response.status_code == 204
    await db_session.refresh(user)
    assert verify_password(new_password, user.password_hash)


async def test_reset_password_then_sign_in(client, user, asked, code, new_password):
    await reset(client, user.email, code, new_password)

    assert (await client.post('/auth/login', json={'email': user.email, 'password': new_password})).status_code == 200


async def test_reset_password_retires_the_old_one(client, user, password, asked, code, new_password):
    await reset(client, user.email, code, new_password)

    assert (await client.post('/auth/login', json={'email': user.email, 'password': password})).status_code == 401


async def test_reset_password_ends_every_session(client, user, tokens, asked, code, new_password):
    await reset(client, user.email, code, new_password)

    assert (await client.get('/me', headers=bearer(tokens['access_token']))).status_code == 401
    refreshed = await client.post('/auth/refresh', json={'refresh_token': tokens['refresh_token']})
    assert refreshed.status_code == 401


async def test_reset_password_is_recorded(client, user, asked, code, new_password, db_session):
    await reset(client, user.email, code, new_password)

    assert (await db_session.scalar(select(AuditEvent))).kind == 'password_reset'


async def test_reset_password_lifts_the_lock(client, user, code, new_password):
    for _ in range(5):
        await client.post('/auth/login', json={'email': user.email, 'password': 'Wr0ngPassword'})
    await client.post('/auth/forgot-password', json={'email': user.email})
    await reset(client, user.email, code, new_password)

    assert await sign_in(client, user.email, new_password)


async def test_reset_password_wrong_code(client, user, password, asked, new_password):
    response = await reset(client, user.email, '000000', new_password)

    assert response.status_code == 400
    assert response.json() == {'detail': 'invalid code'}
    assert await sign_in(client, user.email, password)


async def test_reset_password_too_many_attempts(client, user, asked, code, new_password):
    for _ in range(5):
        await reset(client, user.email, '000000', new_password)
    response = await reset(client, user.email, code, new_password)

    assert response.status_code == 400
    assert response.json() == {'detail': 'too many attempts'}


@pytest.mark.freeze_time
async def test_reset_password_code_expires(client, user, asked, code, new_password, freezer):
    freezer.tick(10 * 60)
    response = await reset(client, user.email, code, new_password)

    assert response.status_code == 400
    assert response.json() == {'detail': 'code expired'}


@pytest.mark.freeze_time
async def test_reset_password_code_lives_ten_minutes(client, user, asked, code, new_password, freezer):
    freezer.tick(10 * 60 - 1)

    assert (await reset(client, user.email, code, new_password)).status_code == 204


async def test_reset_password_code_works_once(client, user, asked, code, new_password):
    await reset(client, user.email, code, new_password)
    response = await reset(client, user.email, code, 'An0therPassword')

    assert response.status_code == 400


async def test_reset_password_without_asking(client, user, new_password):
    assert (await reset(client, user.email, '123456', new_password)).status_code == 400


async def test_reset_password_unknown_address(client, asked, other_email, code, new_password):
    response = await reset(client, other_email, code, new_password)

    assert response.status_code == 400
    assert response.json() == {'detail': 'invalid code'}


async def test_reset_password_with_somebody_elses_code(client, asked, other_user, code, new_password):
    assert (await reset(client, other_user.email, code, new_password)).status_code == 400


async def test_asking_again_retires_the_first_code(client, user, new_password, mocker):
    mocker.patch('app.security.random_code', side_effect=['111111', '222222'])
    await client.post('/auth/forgot-password', json={'email': user.email})
    await client.post('/auth/forgot-password', json={'email': user.email})

    assert (await reset(client, user.email, '111111', new_password)).status_code == 400
    assert (await reset(client, user.email, '222222', new_password)).status_code == 204


async def test_a_reset_code_verifies_no_address(client, inactive_user, code, db_session):
    # The same digits, drawn for another purpose.
    await client.post('/auth/resend-code', json={'email': inactive_user.email})
    response = await reset(client, inactive_user.email, code, 'N3wPassw0rd!')

    assert response.status_code == 400


@pytest.mark.parametrize('weak', ['Sh0rt!', 'nouppercase1', 'NOLOWERCASE1', 'NoDigitsHere'])
async def test_reset_password_weak_password(client, user, password, asked, code, weak):
    response = await reset(client, user.email, code, weak)

    assert response.status_code == 422
    assert await sign_in(client, user.email, password)
