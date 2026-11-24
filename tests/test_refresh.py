import pytest

from sqlalchemy import select

from app.models import RefreshSession
from tests.utils import bearer, sign_in


async def refresh(client, token, user_agent='pytest'):
    return await client.post('/auth/refresh', json={'refresh_token': token}, headers={'User-Agent': user_agent})


async def test_refresh(client, tokens, mocker):
    response = await refresh(client, tokens['refresh_token'])

    assert response.status_code == 200
    assert response.json() == {'access_token': mocker.ANY, 'refresh_token': mocker.ANY, 'token_type': 'bearer'}
    assert response.json()['refresh_token'] != tokens['refresh_token']


async def test_refreshed_access_token_works(client, tokens):
    fresh = (await refresh(client, tokens['refresh_token'])).json()

    assert (await client.get('/me', headers=bearer(fresh['access_token']))).status_code == 200


async def test_refresh_token_works_once(client, tokens):
    await refresh(client, tokens['refresh_token'])
    response = await refresh(client, tokens['refresh_token'])

    assert response.status_code == 401


async def test_refresh_retires_the_old_access_token(client, tokens):
    await refresh(client, tokens['refresh_token'])

    assert (await client.get('/me', headers=bearer(tokens['access_token']))).status_code == 401


async def test_refresh_chain(client, tokens):
    token = tokens['refresh_token']
    for _ in range(3):
        response = await refresh(client, token)
        assert response.status_code == 200
        token = response.json()['refresh_token']


async def test_refresh_remembers_the_new_device(client, tokens, db_session):
    await refresh(client, tokens['refresh_token'], user_agent='Safari on macOS')

    rows = (await db_session.scalars(select(RefreshSession).order_by(RefreshSession.id))).all()
    assert [(row.user_agent, row.revoked_at is None) for row in rows] == [('pytest', False), ('Safari on macOS', True)]


async def test_refresh_unknown_token(client, user):
    response = await refresh(client, 'nonsense')

    assert response.status_code == 401
    assert response.json() == {'detail': 'not authenticated'}


async def test_refresh_with_an_access_token(client, tokens):
    assert (await refresh(client, tokens['access_token'])).status_code == 401


@pytest.mark.freeze_time
async def test_refresh_token_expires(client, tokens, freezer):
    freezer.tick(28 * 24 * 3600)

    assert (await refresh(client, tokens['refresh_token'])).status_code == 401


@pytest.mark.freeze_time
async def test_refresh_token_lives_four_weeks(client, tokens, freezer):
    freezer.tick(28 * 24 * 3600 - 1)

    assert (await refresh(client, tokens['refresh_token'])).status_code == 200


async def test_refresh_leaves_other_sessions(client, user, password, tokens):
    elsewhere = await sign_in(client, user.email, password)
    await refresh(client, tokens['refresh_token'])

    assert (await client.get('/me', headers=bearer(elsewhere['access_token']))).status_code == 200


async def test_refresh_malformed(client):
    assert (await client.post('/auth/refresh', json={})).status_code == 422


async def test_logout(client, tokens):
    response = await client.post('/auth/logout', json={'refresh_token': tokens['refresh_token']})

    assert response.status_code == 204


async def test_logout_retires_the_refresh_token(client, tokens):
    await client.post('/auth/logout', json={'refresh_token': tokens['refresh_token']})

    assert (await refresh(client, tokens['refresh_token'])).status_code == 401


async def test_logout_retires_the_access_token(client, tokens):
    await client.post('/auth/logout', json={'refresh_token': tokens['refresh_token']})

    assert (await client.get('/me', headers=bearer(tokens['access_token']))).status_code == 401


async def test_logout_twice(client, tokens):
    await client.post('/auth/logout', json={'refresh_token': tokens['refresh_token']})
    response = await client.post('/auth/logout', json={'refresh_token': tokens['refresh_token']})

    assert response.status_code == 204


async def test_logout_unknown_token(client):
    assert (await client.post('/auth/logout', json={'refresh_token': 'nonsense'})).status_code == 204


async def test_logout_leaves_other_sessions(client, user, password, tokens):
    elsewhere = await sign_in(client, user.email, password)
    await client.post('/auth/logout', json={'refresh_token': tokens['refresh_token']})

    assert (await client.get('/me', headers=bearer(elsewhere['access_token']))).status_code == 200


async def test_sign_in_again_after_logout(client, user, password, tokens):
    await client.post('/auth/logout', json={'refresh_token': tokens['refresh_token']})

    again = await sign_in(client, user.email, password)
    assert (await client.get('/me', headers=bearer(again['access_token']))).status_code == 200
