import pytest

from tests.utils import bearer, sign_in


async def test_one_session(client, auth, mocker):
    response = await client.get('/me/sessions', headers=auth)

    assert response.status_code == 200
    assert response.json() == [{'id': mocker.ANY, 'user_agent': 'pytest', 'created_at': mocker.ANY, 'current': True}]


async def test_two_devices(client, user, password, auth):
    await sign_in(client, user.email, password, user_agent='Safari on macOS')

    sessions = (await client.get('/me/sessions', headers=auth)).json()
    assert [(s['user_agent'], s['current']) for s in sessions] == [('pytest', True), ('Safari on macOS', False)]


async def test_the_current_one_is_whoever_asks(client, user, password, auth):
    elsewhere = await sign_in(client, user.email, password, user_agent='Safari on macOS')

    sessions = (await client.get('/me/sessions', headers=bearer(elsewhere['access_token']))).json()
    assert [(s['user_agent'], s['current']) for s in sessions] == [('pytest', False), ('Safari on macOS', True)]


async def test_sessions_are_ones_own(client, auth, other_auth):
    assert len((await client.get('/me/sessions', headers=auth)).json()) == 1


@pytest.mark.freeze_time('2026-03-01 10:00:00')
async def test_session_is_dated(client, auth):
    assert (await client.get('/me/sessions', headers=auth)).json()[0]['created_at'] == '2026-03-01T10:00:00Z'


@pytest.mark.freeze_time
async def test_expired_session_is_not_listed(client, user, password, tokens, freezer):
    freezer.tick(27 * 24 * 3600)
    later = await sign_in(client, user.email, password, user_agent='later')
    freezer.tick(2 * 24 * 3600)
    later = (await client.post('/auth/refresh', json={'refresh_token': later['refresh_token']})).json()

    sessions = (await client.get('/me/sessions', headers=bearer(later['access_token']))).json()
    assert len(sessions) == 1


async def test_signed_out_session_is_not_listed(client, user, password, auth):
    elsewhere = await sign_in(client, user.email, password)
    await client.post('/auth/logout', json={'refresh_token': elsewhere['refresh_token']})

    assert len((await client.get('/me/sessions', headers=auth)).json()) == 1


async def test_end_another_session(client, user, password, auth):
    elsewhere = await sign_in(client, user.email, password)
    other_id = (await client.get('/me/sessions', headers=auth)).json()[1]['id']

    response = await client.delete(f'/me/sessions/{other_id}', headers=auth)

    assert response.status_code == 204
    assert (await client.get('/me', headers=bearer(elsewhere['access_token']))).status_code == 401
    refreshed = await client.post('/auth/refresh', json={'refresh_token': elsewhere['refresh_token']})
    assert refreshed.status_code == 401


async def test_ending_another_session_keeps_this_one(client, user, password, auth):
    await sign_in(client, user.email, password)
    other_id = (await client.get('/me/sessions', headers=auth)).json()[1]['id']
    await client.delete(f'/me/sessions/{other_id}', headers=auth)

    assert len((await client.get('/me/sessions', headers=auth)).json()) == 1


async def test_end_this_session(client, auth):
    own_id = (await client.get('/me/sessions', headers=auth)).json()[0]['id']
    response = await client.delete(f'/me/sessions/{own_id}', headers=auth)

    assert response.status_code == 204
    assert (await client.get('/me', headers=auth)).status_code == 401


async def test_end_a_session_twice(client, user, password, auth):
    await sign_in(client, user.email, password)
    other_id = (await client.get('/me/sessions', headers=auth)).json()[1]['id']
    await client.delete(f'/me/sessions/{other_id}', headers=auth)

    assert (await client.delete(f'/me/sessions/{other_id}', headers=auth)).status_code == 404


async def test_end_somebody_elses_session(client, auth, other_auth):
    theirs = (await client.get('/me/sessions', headers=other_auth)).json()[0]['id']
    response = await client.delete(f'/me/sessions/{theirs}', headers=auth)

    assert response.status_code == 404
    assert (await client.get('/me', headers=other_auth)).status_code == 200


@pytest.mark.parametrize('session_id, expected', [('0', 404), ('999999', 404), ('abc', 422)])
async def test_end_a_session_that_is_not(client, auth, session_id, expected):
    assert (await client.delete(f'/me/sessions/{session_id}', headers=auth)).status_code == expected


async def test_sessions_signed_out(client, user):
    assert (await client.get('/me/sessions')).status_code == 401
    assert (await client.delete('/me/sessions/1')).status_code == 401
