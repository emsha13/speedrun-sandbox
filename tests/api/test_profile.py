import pytest

from tests.utils import bearer


async def test_read_profile(client, user, auth):
    response = await client.get('/me', headers=auth)

    assert response.status_code == 200
    assert response.json() == {
        'id': user.id, 'email': user.email, 'phone': None, 'first_name': 'Ann', 'last_name': 'Lee',
        'birth_date': None, 'role': 'user', 'is_active': True, 'created_at': user.created_at.isoformat().replace('+00:00', 'Z'),
    }


async def test_profile_shows_no_hash(client, auth):
    assert 'password' not in (await client.get('/me', headers=auth)).text


async def test_everyone_reads_their_own(client, auth, other_auth, email, other_email):
    assert (await client.get('/me', headers=auth)).json()['email'] == email
    assert (await client.get('/me', headers=other_auth)).json()['email'] == other_email


async def test_update_first_name_only(client, auth):
    response = await client.patch('/me', json={'first_name': 'Anna'}, headers=auth)

    assert response.status_code == 200
    assert (response.json()['first_name'], response.json()['last_name']) == ('Anna', 'Lee')


async def test_update_everything(client, auth):
    changes = {'first_name': 'Anna', 'last_name': 'Li', 'birth_date': '1990-05-17'}
    response = await client.patch('/me', json=changes, headers=auth)

    assert response.status_code == 200
    assert response.json() | changes == response.json()


async def test_update_is_kept(client, auth, user, db_session):
    await client.patch('/me', json={'last_name': 'Li'}, headers=auth)

    await db_session.refresh(user)
    assert user.last_name == 'Li'
    assert (await client.get('/me', headers=auth)).json()['last_name'] == 'Li'


async def test_update_nothing(client, auth):
    response = await client.patch('/me', json={}, headers=auth)

    assert response.status_code == 200
    assert response.json()['first_name'] == 'Ann'


async def test_update_touches_nobody_else(client, auth, other_auth):
    await client.patch('/me', json={'first_name': 'Anna'}, headers=auth)

    assert (await client.get('/me', headers=other_auth)).json()['first_name'] == 'Bob'


async def test_update_cannot_change_the_address(client, auth, email):
    response = await client.patch('/me', json={'email': 'elsewhere@example.com'}, headers=auth)

    assert response.json()['email'] == email


async def test_clear_birth_date(client, auth):
    await client.patch('/me', json={'birth_date': '1990-05-17'}, headers=auth)
    response = await client.patch('/me', json={'birth_date': None}, headers=auth)

    assert response.json()['birth_date'] is None


@pytest.mark.freeze_time('2026-03-01 10:00:00')
async def test_born_today(client, auth):
    response = await client.patch('/me', json={'birth_date': '2026-03-01'}, headers=auth)

    assert response.status_code == 200


@pytest.mark.freeze_time('2026-03-01 10:00:00')
async def test_born_tomorrow(client, auth):
    response = await client.patch('/me', json={'birth_date': '2026-03-02'}, headers=auth)

    assert response.status_code == 400
    assert response.json() == {'detail': 'birth date is in the future'}


@pytest.mark.freeze_time('2026-03-01 23:59:59')
async def test_tomorrow_comes_at_midnight(client, auth, freezer):
    before = await client.patch('/me', json={'birth_date': '2026-03-02'}, headers=auth)
    freezer.tick(1)
    after = await client.patch('/me', json={'birth_date': '2026-03-02'}, headers=auth)

    assert (before.status_code, after.status_code) == (400, 200)


@pytest.mark.parametrize('day', ['', 'yesterday', '17.05.1990', '1990-13-01', '1990-02-30'])
async def test_malformed_birth_date(client, auth, day):
    assert (await client.patch('/me', json={'birth_date': day}, headers=auth)).status_code == 422


@pytest.mark.parametrize('field', ['first_name', 'last_name'])
async def test_a_name_cannot_be_removed(client, auth, field):
    response = await client.patch('/me', json={field: None}, headers=auth)

    assert response.status_code == 400


@pytest.mark.parametrize('field', ['first_name', 'last_name'])
@pytest.mark.parametrize('name', ['', ' ', ' Ann', 'Ann ', 'x' * 51])
async def test_update_bad_name(client, auth, field, name):
    assert (await client.patch('/me', json={field: name}, headers=auth)).status_code == 422


async def test_update_signed_out(client, user):
    assert (await client.patch('/me', json={'first_name': 'Anna'})).status_code == 401


async def test_profile_of_an_account_since_deactivated(client, user, tokens, db_session):
    user.is_active = False
    await db_session.commit()

    assert (await client.get('/me', headers=bearer(tokens['access_token']))).status_code == 401
