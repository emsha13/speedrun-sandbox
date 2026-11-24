"""What a name and an address may look like, at the doors that take them."""
import pytest

from sqlalchemy import select

from app.models import User

NAMES = [
    'Ann', 'A', 'Anne-Marie', "O'Neil", 'van der Berg', 'Élodie', 'Søren', 'Łukasz', 'Нина', '田中', 'x' * 50,
    'J. R.',
]
ADDRESSES = [
    ('ann@example.com', 'ann@example.com'), ('Ann@Example.com', 'ann@example.com'),
    ('ANN.LEE@EXAMPLE.COM', 'ann.lee@example.com'), ('ann+news@example.com', 'ann+news@example.com'),
    ('ann_lee@example.co.uk', 'ann_lee@example.co.uk'), ('a@example.org', 'a@example.org'),
    ('ann-lee@sub.example.com', 'ann-lee@sub.example.com'), ('1234@example.com', '1234@example.com'),
]
NOT_ADDRESSES = [
    '', 'ann', 'ann@', '@example.com', 'ann@example', 'a b@example.com', 'ann@@example.com', 'ann@.com',
    'ann@example..com', '.ann@example.com', 'ann.@example.com', 'ann@example.com.', 'ann@-example.com',
    'x' * 250 + '@example.com',
]


@pytest.mark.parametrize('field', ['first_name', 'last_name'])
@pytest.mark.parametrize('name', NAMES)
async def test_register_takes_the_name(client, password, field, name, db_session):
    body = {'email': 'ann@example.com', 'password': password, 'first_name': 'Ann', 'last_name': 'Lee'} | {field: name}
    response = await client.post('/auth/register', json=body)

    assert response.status_code == 201
    assert getattr(await db_session.scalar(select(User)), field) == name


@pytest.mark.parametrize('field', ['first_name', 'last_name'])
@pytest.mark.parametrize('name', NAMES)
async def test_profile_takes_the_name(client, auth, field, name):
    response = await client.patch('/me', json={field: name}, headers=auth)

    assert response.status_code == 200
    assert response.json()[field] == name


@pytest.mark.parametrize('given, kept', ADDRESSES)
async def test_register_takes_the_address(client, password, given, kept):
    body = {'email': given, 'password': password, 'first_name': 'Ann', 'last_name': 'Lee'}
    response = await client.post('/auth/register', json=body)

    assert response.status_code == 201
    assert response.json()['email'] == kept


@pytest.mark.parametrize('given, kept', ADDRESSES)
async def test_change_email_takes_the_address(client, other_auth, password, code, given, kept):
    await client.post('/me/change-email', json={'new_email': given, 'password': password}, headers=other_auth)
    response = await client.post('/me/change-email/confirm', json={'code': code}, headers=other_auth)

    assert response.json()['email'] == kept


@pytest.mark.parametrize('door, field', [
    ('/auth/register', 'email'), ('/auth/login', 'email'), ('/auth/forgot-password', 'email'),
    ('/auth/resend-code', 'email'),
])
@pytest.mark.parametrize('address', NOT_ADDRESSES)
async def test_not_an_address(client, door, field, address):
    body = {'password': 'Passw0rd!', 'first_name': 'Ann', 'last_name': 'Lee', field: address}
    if door in ('/auth/forgot-password', '/auth/resend-code'):
        body = {field: address}

    assert (await client.post(door, json=body)).status_code == 422
