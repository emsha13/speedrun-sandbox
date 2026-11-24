"""What is true of every door, whatever is behind it."""
import pytest

PRIVATE = [
    ('GET', '/me'), ('PATCH', '/me'), ('DELETE', '/me'), ('POST', '/me/change-password'),
    ('POST', '/me/change-email'), ('POST', '/me/change-email/confirm'), ('POST', '/me/change-phone'),
    ('POST', '/me/change-phone/confirm'), ('POST', '/me/remove-phone'), ('GET', '/me/sessions'),
    ('DELETE', '/me/sessions/1'), ('GET', '/users'), ('GET', '/users/1'), ('PATCH', '/users/1'),
    ('DELETE', '/users/1'),
]
PUBLIC = ['register', 'verify-email', 'resend-code', 'login', 'refresh', 'logout', 'forgot-password', 'reset-password']
A_TOKEN_OF_NOBODY = (
    'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxIiwic2lkIjoxfQ.c2lnbmF0dXJlLXRoYXQtbWF0Y2hlcy1ub3RoaW5n'
)


@pytest.mark.parametrize('headers', [
    {}, {'Authorization': 'Bearer nonsense'}, {'Authorization': 'Basic YW5uOnB3'},
    {'Authorization': f'Bearer {A_TOKEN_OF_NOBODY}'}, {'Authorization': 'bearer'},
], ids=['none', 'nonsense', 'basic', 'forged', 'empty'])
@pytest.mark.parametrize('method, path', PRIVATE)
async def test_private_door_wants_a_token(client, method, path, headers):
    response = await client.request(method, path, json={}, headers=headers)

    assert response.status_code == 401
    assert response.json() == {'detail': 'not authenticated'}


@pytest.mark.parametrize('content', [b'{', b'[]', b'"text"', b'null', b'', b'12'],
                         ids=['broken', 'list', 'string', 'null', 'empty', 'number'])
@pytest.mark.parametrize('door', PUBLIC)
async def test_public_door_wants_an_object(client, door, content):
    response = await client.post(f'/auth/{door}', content=content, headers={'Content-Type': 'application/json'})

    assert response.status_code == 422


@pytest.mark.parametrize('door', PUBLIC)
async def test_public_door_takes_posts_only(client, door):
    assert (await client.get(f'/auth/{door}')).status_code == 405


@pytest.mark.parametrize('door', PUBLIC)
async def test_public_door_wants_json(client, door):
    response = await client.post(f'/auth/{door}', content=b'email=ann', headers={'Content-Type': 'text/plain'})

    assert response.status_code == 422


@pytest.mark.parametrize('path', ['/nowhere', '/auth', '/auth/nowhere', '/me/nowhere', '/users/1/nowhere'])
async def test_no_such_door(client, path):
    assert (await client.get(path)).status_code == 404


async def test_health(client):
    response = await client.get('/health')

    assert response.status_code == 200
    assert response.json() == {'status': 'ok'}


async def test_the_schema_lists_every_door(client):
    paths = (await client.get('/openapi.json')).json()['paths']

    assert {f'/auth/{door}' for door in PUBLIC} <= set(paths)
    assert {path.replace('/1', '/{user_id}') for _, path in PRIVATE if path.startswith('/users')} <= set(paths)
