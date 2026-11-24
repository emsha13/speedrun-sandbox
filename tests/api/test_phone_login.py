"""The doors that take an address take a number as well."""
import pytest

from sqlalchemy import func, select

from app.models import LoginAttempt
from app.security import verify_password
from tests.utils import bearer, mailed_code, mailed_to, sign_in

WRONG = 'Wr0ngPassword'


async def test_login_by_phone(client, user_with_phone, phone, password, mocker):
    response = await client.post('/auth/login', json={'phone': phone, 'password': password})

    assert response.status_code == 200
    assert response.json() == {'access_token': mocker.ANY, 'refresh_token': mocker.ANY, 'token_type': 'bearer'}


async def test_login_by_phone_is_the_same_user(client, user_with_phone, phone, password):
    tokens = await sign_in(client, phone, password)

    assert (await client.get('/me', headers=bearer(tokens['access_token']))).json()['email'] == user_with_phone.email


async def test_login_by_phone_wrong_password(client, user_with_phone, phone):
    response = await client.post('/auth/login', json={'phone': phone, 'password': WRONG})

    assert response.status_code == 401
    assert response.json() == {'detail': 'wrong login or password'}


async def test_login_by_unknown_phone(client, user, phone):
    response = await client.post('/auth/login', json={'phone': phone, 'password': WRONG})

    assert response.status_code == 401
    assert response.json() == {'detail': 'wrong login or password'}


async def test_login_by_somebody_elses_phone(client, user_with_phone, other_user, phone):
    response = await client.post('/auth/login', json={'phone': phone, 'password': WRONG})

    assert response.status_code == 401


async def test_login_by_phone_inactive(client, create_user, email, phone, password):
    await create_user(email, password, phone=phone, is_active=False)
    response = await client.post('/auth/login', json={'phone': phone, 'password': password})

    assert response.status_code == 403


async def test_phone_lock(client, user_with_phone, phone, password):
    for _ in range(5):
        await client.post('/auth/login', json={'phone': phone, 'password': WRONG})
    response = await client.post('/auth/login', json={'phone': phone, 'password': password})

    assert response.status_code == 429


async def test_phone_lock_leaves_the_address_open(client, user_with_phone, phone, password):
    for _ in range(5):
        await client.post('/auth/login', json={'phone': phone, 'password': WRONG})

    assert await sign_in(client, user_with_phone.email, password)


async def test_sign_in_forgets_failures_by_both_names(client, user_with_phone, phone, password, db_session):
    for login in ({'phone': phone}, {'email': user_with_phone.email}):
        await client.post('/auth/login', json=login | {'password': WRONG})
    await sign_in(client, phone, password)

    assert await db_session.scalar(select(func.count()).select_from(LoginAttempt)) == 0


@pytest.mark.freeze_time
async def test_phone_lock_lifts(client, user_with_phone, phone, password, freezer):
    for _ in range(5):
        await client.post('/auth/login', json={'phone': phone, 'password': WRONG})
    freezer.tick(15 * 60)

    assert await sign_in(client, phone, password)


@pytest.mark.parametrize('body', [
    {'email': 'ann@example.com', 'phone': '+4915112345678', 'password': 'x'},
    {'phone': '4915112345678', 'password': 'x'},
    {'phone': '+49 151', 'password': 'x'},
    {'phone': None, 'password': 'x'},
    {'phone': '', 'password': 'x'},
    {'email': None, 'phone': None, 'password': 'x'},
])
async def test_login_neither_or_both(client, body):
    assert (await client.post('/auth/login', json=body)).status_code == 422


async def reset(client, phone, code, new_password):
    return await client.post('/auth/reset-password', json={'phone': phone, 'code': code, 'new_password': new_password})


@pytest.fixture
async def asked(client, user_with_phone, phone, code):
    response = await client.post('/auth/forgot-password', json={'phone': phone})
    assert response.status_code == 204


async def test_forgot_password_by_phone_texts_a_code(client, user_with_phone, phone, sms_outbox, outbox):
    response = await client.post('/auth/forgot-password', json={'phone': phone})

    assert response.status_code == 204
    assert mailed_to(sms_outbox) == phone
    assert len(mailed_code(sms_outbox)) == 6
    outbox.assert_not_awaited()


async def test_forgot_password_by_address_mails_not_texts(client, user_with_phone, sms_outbox, outbox):
    await client.post('/auth/forgot-password', json={'email': user_with_phone.email})

    outbox.assert_awaited_once()
    sms_outbox.assert_not_awaited()


async def test_forgot_password_unknown_phone(client, user, phone, sms_outbox):
    response = await client.post('/auth/forgot-password', json={'phone': phone})

    assert response.status_code == 204
    sms_outbox.assert_not_awaited()


async def test_reset_password_by_phone(client, user_with_phone, asked, phone, code, new_password, db_session):
    response = await reset(client, phone, code, new_password)

    assert response.status_code == 204
    await db_session.refresh(user_with_phone)
    assert verify_password(new_password, user_with_phone.password_hash)


async def test_reset_by_phone_then_sign_in_either_way(client, user_with_phone, asked, phone, code, new_password):
    await reset(client, phone, code, new_password)

    assert await sign_in(client, phone, new_password)
    assert await sign_in(client, user_with_phone.email, new_password)


async def test_a_texted_code_works_by_address_too(client, user_with_phone, asked, code, new_password):
    # The code belongs to the user, whichever name they give.
    response = await client.post(
        '/auth/reset-password', json={'email': user_with_phone.email, 'code': code, 'new_password': new_password}
    )

    assert response.status_code == 204


async def test_reset_by_phone_wrong_code(client, asked, phone, new_password):
    response = await reset(client, phone, '000000', new_password)

    assert response.status_code == 400
    assert response.json() == {'detail': 'invalid code'}


async def test_reset_by_phone_too_many_attempts(client, asked, phone, code, new_password):
    for _ in range(5):
        await reset(client, phone, '000000', new_password)

    assert (await reset(client, phone, code, new_password)).json() == {'detail': 'too many attempts'}


@pytest.mark.freeze_time
async def test_reset_by_phone_code_expires(client, asked, phone, code, new_password, freezer):
    freezer.tick(10 * 60)

    assert (await reset(client, phone, code, new_password)).json() == {'detail': 'code expired'}


async def test_reset_by_unknown_phone(client, asked, other_phone, code, new_password):
    assert (await reset(client, other_phone, code, new_password)).status_code == 400


async def test_reset_by_phone_ends_every_session(client, user_with_phone, phone, password, code, new_password):
    tokens = await sign_in(client, phone, password)
    await client.post('/auth/forgot-password', json={'phone': phone})
    await reset(client, phone, code, new_password)

    assert (await client.get('/me', headers=bearer(tokens['access_token']))).status_code == 401


async def test_reset_by_phone_lifts_the_lock(client, user_with_phone, phone, code, new_password):
    for _ in range(5):
        await client.post('/auth/login', json={'phone': phone, 'password': WRONG})
    await client.post('/auth/forgot-password', json={'phone': phone})
    await reset(client, phone, code, new_password)

    assert await sign_in(client, phone, new_password)


@pytest.mark.parametrize('body', [
    {}, {'email': 'ann@example.com', 'phone': '+4915112345678'}, {'phone': 'nonsense'}, {'email': 'nonsense'},
])
async def test_forgot_password_malformed(client, body):
    assert (await client.post('/auth/forgot-password', json=body)).status_code == 422
