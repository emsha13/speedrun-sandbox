import pytest

from sqlalchemy import select

from app.models import AuditEvent
from app.security import verify_password
from tests.utils import bearer, sign_in


async def change(client, auth, current, new):
    return await client.post(
        '/me/change-password', json={'current_password': current, 'new_password': new}, headers=auth
    )


async def test_change_password(client, user, auth, password, new_password, db_session):
    response = await change(client, auth, password, new_password)

    assert response.status_code == 204
    await db_session.refresh(user)
    assert verify_password(new_password, user.password_hash)


async def test_change_password_then_sign_in(client, user, auth, password, new_password):
    await change(client, auth, password, new_password)

    assert await sign_in(client, user.email, new_password)


async def test_change_password_retires_the_old_one(client, user, auth, password, new_password):
    await change(client, auth, password, new_password)

    assert (await client.post('/auth/login', json={'email': user.email, 'password': password})).status_code == 401


async def test_change_password_keeps_this_session(client, auth, tokens, password, new_password):
    await change(client, auth, password, new_password)

    assert (await client.get('/me', headers=auth)).status_code == 200
    refreshed = await client.post('/auth/refresh', json={'refresh_token': tokens['refresh_token']})
    assert refreshed.status_code == 200


async def test_change_password_ends_the_other_sessions(client, user, auth, password, new_password):
    elsewhere = await sign_in(client, user.email, password)
    await change(client, auth, password, new_password)

    assert (await client.get('/me', headers=bearer(elsewhere['access_token']))).status_code == 401
    refreshed = await client.post('/auth/refresh', json={'refresh_token': elsewhere['refresh_token']})
    assert refreshed.status_code == 401


async def test_change_password_is_recorded(client, auth, password, new_password, db_session):
    await change(client, auth, password, new_password)

    kinds = (await db_session.scalars(select(AuditEvent.kind).order_by(AuditEvent.id))).all()
    assert kinds == ['login', 'password_changed']


async def test_change_password_leaves_other_users_alone(client, auth, other_user, password, new_password):
    await change(client, auth, password, new_password)

    assert await sign_in(client, other_user.email, password)


async def test_change_password_wrong_current(client, user, auth, password, new_password):
    response = await change(client, auth, 'Wr0ngPassword', new_password)

    assert response.status_code == 400
    assert response.json() == {'detail': 'wrong password'}
    assert await sign_in(client, user.email, password)


async def test_change_password_to_the_same(client, auth, password):
    response = await change(client, auth, password, password)

    assert response.status_code == 400
    assert response.json() == {'detail': 'new password is the old one'}


@pytest.mark.parametrize('weak', ['Sh0rt!', 'nouppercase1', 'NOLOWERCASE1', 'NoDigitsHere'])
async def test_change_password_weak(client, user, auth, password, weak):
    response = await change(client, auth, password, weak)

    assert response.status_code == 422
    assert await sign_in(client, user.email, password)


async def test_change_password_signed_out(client, user, password, new_password):
    response = await change(client, {}, password, new_password)

    assert response.status_code == 401
