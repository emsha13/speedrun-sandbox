from sqlalchemy import func, select

from app.models import AuditEvent, LoginAttempt, OneTimeCode, RefreshSession, User
from tests.utils import sign_in


async def delete(client, auth, password):
    return await client.request('DELETE', '/me', json={'password': password}, headers=auth)


async def count(db_session, model):
    return await db_session.scalar(select(func.count()).select_from(model))


async def test_delete_account(client, auth, password, db_session):
    response = await delete(client, auth, password)

    assert response.status_code == 204
    assert await count(db_session, User) == 0


async def test_delete_account_takes_everything_of_the_user(client, auth, password, db_session):
    await client.post('/me/change-email', json={'new_email': 'new@example.com', 'password': password}, headers=auth)
    await delete(client, auth, password)

    for model in (RefreshSession, OneTimeCode, AuditEvent):
        assert await count(db_session, model) == 0


async def test_deleted_account_signs_in_no_more(client, user, auth, password):
    await delete(client, auth, password)

    assert (await client.post('/auth/login', json={'email': user.email, 'password': password})).status_code == 401


async def test_deleted_accounts_tokens_are_dead(client, auth, tokens, password):
    await delete(client, auth, password)

    assert (await client.get('/me', headers=auth)).status_code == 401
    refreshed = await client.post('/auth/refresh', json={'refresh_token': tokens['refresh_token']})
    assert refreshed.status_code == 401


async def test_deleted_accounts_address_is_free(client, user, auth, password):
    await delete(client, auth, password)
    response = await client.post(
        '/auth/register', json={'email': user.email, 'password': password, 'first_name': 'Ann', 'last_name': 'Two'}
    )

    assert response.status_code == 201


async def test_delete_account_leaves_the_others(client, auth, other_user, other_auth, password, db_session):
    await delete(client, auth, password)

    assert await count(db_session, User) == 1
    assert (await client.get('/me', headers=other_auth)).status_code == 200
    assert await sign_in(client, other_user.email, password)


async def test_delete_account_wrong_password(client, auth, db_session):
    response = await delete(client, auth, 'Wr0ngPassword')

    assert response.status_code == 400
    assert response.json() == {'detail': 'wrong password'}
    assert await count(db_session, User) == 1


async def test_delete_account_without_a_password(client, auth):
    assert (await client.request('DELETE', '/me', json={}, headers=auth)).status_code == 422


async def test_delete_account_signed_out(client, user, password, db_session):
    response = await delete(client, {}, password)

    assert response.status_code == 401
    assert await count(db_session, User) == 1


async def test_failed_sign_ins_outlive_the_account(client, user, auth, password, db_session):
    # They are kept by address, not by user: deleting an account must not lift a lock on its address.
    await client.post('/auth/login', json={'email': user.email, 'password': 'Wr0ngPassword'})
    await delete(client, auth, password)

    assert await count(db_session, LoginAttempt) == 1
