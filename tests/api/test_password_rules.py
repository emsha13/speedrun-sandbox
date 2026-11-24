"""One rule for a password at every door that takes a new one."""
import pytest

from tests.utils import sign_in

DOORS = ['register', 'reset-password', 'change-password']
WEAK = [
    '', 'a', 'Sh0rt!', 'Seven7!', 'nouppercase1', 'NOLOWERCASE1', 'NoDigitsHere', '12345678', 'password',
    'PASSWORD', 'Passw0rd with space', 'Aa1' + 'x' * 70, 'Aa1' + 'é' * 35,
]
STRONG = ['Passw0rd', 'N3wPassw0rd!', 'Aa1' + 'x' * 69, 'Aa1' + 'é' * 34, 'Ünïcödé1x', 'P@$$w0rd#%^&*()', 'aB3' * 3]


@pytest.fixture
async def offer(client, door, create_user, password, code):
    """Offers the door a new password and says whether it took it."""
    auth = None
    if door != 'register':
        await create_user('ann@example.com', password)
    if door == 'change-password':
        auth = {'Authorization': 'Bearer ' + (await sign_in(client, 'ann@example.com', password))['access_token']}
    if door == 'reset-password':
        await client.post('/auth/forgot-password', json={'email': 'ann@example.com'})

    async def _offer(new):
        if door == 'register':
            body = {'email': 'ann@example.com', 'password': new, 'first_name': 'Ann', 'last_name': 'Lee'}
            return await client.post('/auth/register', json=body)
        if door == 'reset-password':
            body = {'email': 'ann@example.com', 'code': code, 'new_password': new}
            return await client.post('/auth/reset-password', json=body)
        body = {'current_password': password, 'new_password': new}
        return await client.post('/me/change-password', json=body, headers=auth)

    return _offer


@pytest.mark.parametrize('door', DOORS)
@pytest.mark.parametrize('weak', WEAK)
async def test_weak_password_is_refused(offer, weak):
    assert (await offer(weak)).status_code == 422


@pytest.mark.parametrize('door', DOORS)
@pytest.mark.parametrize('strong', STRONG)
async def test_strong_password_is_taken(offer, strong):
    assert (await offer(strong)).status_code in (201, 204)


@pytest.mark.parametrize('door', DOORS)
async def test_a_refusal_names_the_password(offer, door):
    error = (await offer('weak')).json()['detail'][0]

    assert error['loc'] == ['body', 'password' if door == 'register' else 'new_password']
