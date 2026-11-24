"""The users, as an admin sees them: the list with its search, filters, order and pages."""
import pytest

from datetime import UTC, datetime, timedelta

from app.models import Role, User
from tests.harness.hashing import hash_for_a_fixture

# (first name, last name, active, role, phone)
CROWD = [
    ('Alice', 'Stone', True, Role.USER, '+4915100000001'),
    ('Bruno', 'Hill', True, Role.USER, None),
    ('Carla', 'Wood', False, Role.USER, '+4915100000003'),
    ('Dmitri', 'Lake', True, Role.ADMIN, None),
    ('Elena', 'Stone', True, Role.USER, '+12025550105'),
    ('Farid', 'Hill', False, Role.USER, None),
    ('Greta', 'Wood', True, Role.USER, None),
    ('Hiro', 'Lake', True, Role.USER, '+12025550108'),
    ('Ines', 'Stone', False, Role.ADMIN, None),
    ('Jonas', 'Hill', True, Role.USER, None),
    ('Kira', 'Wood', True, Role.USER, '+4915100000011'),
    ('Leo', 'Lake', True, Role.USER, None),
]
STARTED = datetime(2026, 1, 1, tzinfo=UTC)


@pytest.fixture
async def crowd(db_session, admin, password):
    """Twelve users beside the admin, registered a day apart in the reverse of their names' order."""
    # One hash for all of them: nobody signs in as one of the crowd.
    password_hash = hash_for_a_fixture(password)
    users = [
        User(
            email=f'{first.lower()}@example.com', password_hash=password_hash, first_name=first, last_name=last,
            is_active=active, role=role, phone=phone, created_at=STARTED - timedelta(days=number),
        )
        for number, (first, last, active, role, phone) in enumerate(CROWD)
    ]
    db_session.add_all(users)
    await db_session.commit()
    return [admin, *users]


async def listed(client, auth, **params):
    response = await client.get('/users', params=params, headers=auth)
    assert response.status_code == 200, response.text
    return response.json()


def ids(users):
    return [user['id'] if isinstance(user, dict) else user.id for user in users]


async def test_list_users(client, admin_auth, crowd):
    page = await listed(client, admin_auth)

    assert page['total'] == 13
    assert ids(page['items']) == sorted(ids(crowd))


async def test_list_shows_what_a_profile_shows(client, admin_auth, crowd, mocker):
    alice = (await listed(client, admin_auth, search='alice'))['items'][0]

    assert alice == {
        'id': mocker.ANY, 'email': 'alice@example.com', 'phone': '+4915100000001', 'first_name': 'Alice',
        'last_name': 'Stone', 'birth_date': None, 'role': 'user', 'is_active': True,
        'created_at': '2026-01-01T00:00:00Z',
    }


async def test_list_shows_no_hash(client, admin_auth, crowd):
    assert 'password' not in (await client.get('/users', headers=admin_auth)).text


async def test_list_of_one(client, admin_auth, admin):
    page = await listed(client, admin_auth)

    assert (page['total'], ids(page['items'])) == (1, [admin.id])


@pytest.mark.parametrize('order', ['asc', 'desc'])
@pytest.mark.parametrize('sort', ['id', 'email', 'first_name', 'last_name', 'created_at'])
async def test_list_order(client, admin_auth, crowd, sort, order):
    page = await listed(client, admin_auth, sort=sort, order=order)

    by_id = sorted(crowd, key=lambda user: user.id)
    expected = sorted(by_id, key=lambda user: getattr(user, sort), reverse=order == 'desc')
    assert ids(page['items']) == ids(expected)


def matches(user, term):
    term = term.lower()
    return (
        term in user.email or term in user.first_name.lower() or term in user.last_name.lower()
        or term in (user.phone or '')
    )


@pytest.mark.parametrize('term', [
    'ali', 'ALI', 'Alice', 'example.com', 'stone', 'STONE', 'oo', 'e', '+49151', '555', '0000001', 'root', 'Admin',
    'zzz', '%', '_', 'a%', '@', 'hill', 'ro',
])
async def test_list_search(client, admin_auth, crowd, term):
    page = await listed(client, admin_auth, search=term, limit=100)

    expected = [user for user in crowd if matches(user, term)]
    assert page['total'] == len(expected)
    assert sorted(ids(page['items'])) == sorted(ids(expected))


@pytest.mark.parametrize('role', [None, 'user', 'admin'])
@pytest.mark.parametrize('is_active', [None, True, False])
async def test_list_filters(client, admin_auth, crowd, is_active, role):
    params = {name: value for name, value in (('is_active', is_active), ('role', role)) if value is not None}
    page = await listed(client, admin_auth, **params)

    expected = [
        user for user in crowd
        if (is_active is None or user.is_active is is_active) and (role is None or user.role == role)
    ]
    assert page['total'] == len(expected)
    assert sorted(ids(page['items'])) == sorted(ids(expected))


@pytest.mark.parametrize('offset', [0, 1, 5, 12, 13, 50])
@pytest.mark.parametrize('limit', [1, 2, 5, 13, 20, 100])
async def test_list_pages(client, admin_auth, crowd, limit, offset):
    page = await listed(client, admin_auth, limit=limit, offset=offset)

    assert page['total'] == 13
    assert ids(page['items']) == sorted(ids(crowd))[offset:offset + limit]


async def test_pages_do_not_overlap_when_names_repeat(client, admin_auth, crowd):
    seen = []
    for offset in range(0, 13, 4):
        seen += ids((await listed(client, admin_auth, sort='last_name', limit=4, offset=offset))['items'])

    assert sorted(seen) == sorted(ids(crowd))


@pytest.mark.parametrize('params, names', [
    ({'search': 'stone', 'is_active': True}, ['Alice', 'Elena']),
    ({'search': 'stone', 'role': 'admin'}, ['Ines']),
    ({'search': 'hill', 'sort': 'first_name', 'order': 'desc'}, ['Jonas', 'Farid', 'Bruno']),
    ({'role': 'user', 'is_active': False, 'sort': 'email'}, ['Carla', 'Farid']),
    ({'search': '+1202', 'sort': 'created_at'}, ['Hiro', 'Elena']),
    ({'is_active': True, 'role': 'user', 'sort': 'first_name', 'limit': 3, 'offset': 2}, ['Elena', 'Greta', 'Hiro']),
    ({'search': 'wood', 'limit': 1, 'offset': 1, 'sort': 'first_name'}, ['Greta']),
    ({'search': 'lake', 'is_active': False}, []),
])
async def test_list_everything_at_once(client, admin_auth, crowd, params, names):
    page = await listed(client, admin_auth, **params)

    assert [user['first_name'] for user in page['items']] == names


@pytest.mark.parametrize('params', [
    {'limit': 0}, {'limit': 101}, {'limit': -1}, {'limit': 'ten'}, {'offset': -1}, {'offset': 'two'},
    {'sort': 'password_hash'}, {'sort': 'nope'}, {'sort': ''}, {'order': 'up'}, {'role': 'king'},
    {'is_active': 'maybe'}, {'search': ''}, {'search': 'x' * 101}, {'page': 2},
])
async def test_list_malformed(client, admin_auth, params):
    assert (await client.get('/users', params=params, headers=admin_auth)).status_code == 422


DOORS = [('GET', '/users'), ('GET', '/users/1'), ('PATCH', '/users/1'), ('DELETE', '/users/1')]


@pytest.mark.parametrize('method, path', DOORS)
async def test_users_are_for_admins(client, auth, method, path):
    response = await client.request(method, path, json={}, headers=auth)

    assert response.status_code == 403
    assert response.json() == {'detail': 'admins only'}


@pytest.mark.parametrize('method, path', DOORS)
async def test_users_are_not_for_strangers(client, admin, method, path):
    assert (await client.request(method, path, json={})).status_code == 401


async def test_read_user(client, admin_auth, user):
    response = await client.get(f'/users/{user.id}', headers=admin_auth)

    assert response.status_code == 200
    assert response.json()['email'] == user.email


@pytest.mark.parametrize('user_id, expected', [('0', 404), ('999999', 404), ('abc', 422), ('1.5', 422)])
async def test_read_a_user_that_is_not(client, admin_auth, user_id, expected):
    assert (await client.get(f'/users/{user_id}', headers=admin_auth)).status_code == expected


async def test_deactivate(client, admin_auth, user, db_session):
    response = await client.patch(f'/users/{user.id}', json={'is_active': False}, headers=admin_auth)

    assert response.status_code == 200
    assert response.json()['is_active'] is False
    await db_session.refresh(user)
    assert user.is_active is False


async def test_deactivated_user_is_out(client, admin_auth, user, tokens, auth):
    await client.patch(f'/users/{user.id}', json={'is_active': False}, headers=admin_auth)

    assert (await client.get('/me', headers=auth)).status_code == 401
    refreshed = await client.post('/auth/refresh', json={'refresh_token': tokens['refresh_token']})
    assert refreshed.status_code == 401


async def test_deactivated_user_signs_in_no_more(client, admin_auth, user, password):
    await client.patch(f'/users/{user.id}', json={'is_active': False}, headers=admin_auth)
    response = await client.post('/auth/login', json={'email': user.email, 'password': password})

    assert response.status_code == 403


async def test_reactivated_user_signs_in_again(client, admin_auth, user, password):
    for is_active in (False, True):
        await client.patch(f'/users/{user.id}', json={'is_active': is_active}, headers=admin_auth)
    response = await client.post('/auth/login', json={'email': user.email, 'password': password})

    assert response.status_code == 200


async def test_reactivation_revives_no_session(client, admin_auth, user, auth):
    for is_active in (False, True):
        await client.patch(f'/users/{user.id}', json={'is_active': is_active}, headers=admin_auth)

    assert (await client.get('/me', headers=auth)).status_code == 401


async def test_promote(client, admin_auth, user, auth):
    response = await client.patch(f'/users/{user.id}', json={'role': 'admin'}, headers=admin_auth)

    assert response.json()['role'] == 'admin'
    assert (await client.get('/users', headers=auth)).status_code == 200


async def test_demote(client, admin_auth, user, auth):
    for role in ('admin', 'user'):
        await client.patch(f'/users/{user.id}', json={'role': role}, headers=admin_auth)

    assert (await client.get('/users', headers=auth)).status_code == 403


async def test_update_both_at_once(client, admin_auth, user):
    response = await client.patch(f'/users/{user.id}', json={'role': 'admin', 'is_active': False}, headers=admin_auth)

    assert (response.json()['role'], response.json()['is_active']) == ('admin', False)


async def test_update_with_nothing(client, admin_auth, user):
    response = await client.patch(f'/users/{user.id}', json={}, headers=admin_auth)

    assert response.status_code == 200
    assert (response.json()['role'], response.json()['is_active']) == ('user', True)


@pytest.mark.parametrize('change', [{'is_active': False}, {'role': 'user'}, {'role': 'admin'}])
async def test_an_admin_does_not_change_their_own_standing(client, admin_auth, admin, change):
    response = await client.patch(f'/users/{admin.id}', json=change, headers=admin_auth)

    assert response.status_code == 400
    assert (await client.get('/users', headers=admin_auth)).status_code == 200


@pytest.mark.parametrize('body', [
    {'role': 'king'}, {'is_active': 'maybe'}, {'email': 'x@example.com'}, {'first_name': 'X'}, {'password': 'x'},
])
async def test_update_user_malformed(client, admin_auth, user, body):
    assert (await client.patch(f'/users/{user.id}', json=body, headers=admin_auth)).status_code == 422


async def test_update_a_user_that_is_not(client, admin_auth):
    assert (await client.patch('/users/999999', json={'is_active': False}, headers=admin_auth)).status_code == 404


async def test_delete_user(client, admin_auth, user):
    response = await client.delete(f'/users/{user.id}', headers=admin_auth)

    assert response.status_code == 204
    assert (await client.get(f'/users/{user.id}', headers=admin_auth)).status_code == 404


async def test_deleted_user_is_out(client, admin_auth, user, auth, password):
    await client.delete(f'/users/{user.id}', headers=admin_auth)

    assert (await client.get('/me', headers=auth)).status_code == 401
    assert (await client.post('/auth/login', json={'email': user.email, 'password': password})).status_code == 401


async def test_delete_user_twice(client, admin_auth, user):
    await client.delete(f'/users/{user.id}', headers=admin_auth)

    assert (await client.delete(f'/users/{user.id}', headers=admin_auth)).status_code == 404


async def test_an_admin_does_not_delete_themselves_here(client, admin_auth, admin):
    assert (await client.delete(f'/users/{admin.id}', headers=admin_auth)).status_code == 400


async def test_delete_leaves_the_rest(client, admin_auth, crowd):
    await client.delete(f'/users/{crowd[3].id}', headers=admin_auth)

    assert (await listed(client, admin_auth))['total'] == 12


async def test_the_list_follows_a_registration(client, admin_auth, password):
    body = {'email': 'new@example.com', 'password': password, 'first_name': 'New', 'last_name': 'User'}
    await client.post('/auth/register', json=body)

    page = await listed(client, admin_auth, is_active=False)
    assert [user['email'] for user in page['items']] == ['new@example.com']
