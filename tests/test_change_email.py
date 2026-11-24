import pytest

from sqlalchemy import select

from app.models import AuditEvent
from tests.utils import mailed_to, sign_in

NEW = 'ann.lee@example.com'


@pytest.fixture
async def asked(client, auth, password, code):
    """The user has asked to move to NEW; the code is known."""
    response = await client.post('/me/change-email', json={'new_email': NEW, 'password': password}, headers=auth)
    assert response.status_code == 204


async def confirm(client, auth, code):
    return await client.post('/me/change-email/confirm', json={'code': code}, headers=auth)


async def test_change_email_mails_the_new_address(client, auth, password, outbox):
    response = await client.post('/me/change-email', json={'new_email': NEW, 'password': password}, headers=auth)

    assert response.status_code == 204
    assert mailed_to(outbox) == NEW


async def test_change_email_changes_nothing_yet(client, auth, asked, email):
    assert (await client.get('/me', headers=auth)).json()['email'] == email


async def test_change_email_lowercases_the_address(client, auth, password, outbox):
    await client.post('/me/change-email', json={'new_email': NEW.upper(), 'password': password}, headers=auth)

    assert mailed_to(outbox) == NEW


async def test_confirm_email_change(client, auth, asked, code):
    response = await confirm(client, auth, code)

    assert response.status_code == 200
    assert response.json()['email'] == NEW


async def test_confirm_email_change_keeps_the_session(client, auth, asked, code):
    await confirm(client, auth, code)

    assert (await client.get('/me', headers=auth)).json()['email'] == NEW


async def test_sign_in_with_the_new_address(client, auth, asked, code, password):
    await confirm(client, auth, code)

    assert await sign_in(client, NEW, password)


async def test_the_old_address_signs_in_no_more(client, auth, asked, code, email, password):
    await confirm(client, auth, code)

    assert (await client.post('/auth/login', json={'email': email, 'password': password})).status_code == 401


async def test_the_old_address_is_free_again(client, auth, asked, code, email, password):
    await confirm(client, auth, code)
    response = await client.post(
        '/auth/register', json={'email': email, 'password': password, 'first_name': 'Ann', 'last_name': 'Two'}
    )

    assert response.status_code == 201


async def test_email_change_is_recorded(client, auth, asked, code, db_session):
    await confirm(client, auth, code)

    kinds = (await db_session.scalars(select(AuditEvent.kind).order_by(AuditEvent.id))).all()
    assert kinds == ['login', 'email_changed']


async def test_change_email_wrong_password(client, auth, outbox):
    response = await client.post(
        '/me/change-email', json={'new_email': NEW, 'password': 'Wr0ngPassword'}, headers=auth
    )

    assert response.status_code == 400
    assert response.json() == {'detail': 'wrong password'}
    outbox.assert_not_awaited()


async def test_change_email_to_the_same(client, auth, email, password):
    response = await client.post('/me/change-email', json={'new_email': email, 'password': password}, headers=auth)

    assert response.status_code == 400
    assert response.json() == {'detail': 'new email is the old one'}


async def test_change_email_to_a_taken_one(client, auth, other_user, password, outbox):
    response = await client.post(
        '/me/change-email', json={'new_email': other_user.email, 'password': password}, headers=auth
    )

    assert response.status_code == 409
    outbox.assert_not_awaited()


async def test_address_taken_between_the_request_and_the_code(client, auth, asked, code, create_user, email):
    await create_user(NEW, 'S0mebodyElse')
    response = await confirm(client, auth, code)

    assert response.status_code == 409
    assert (await client.get('/me', headers=auth)).json()['email'] == email


async def test_confirm_email_change_wrong_code(client, auth, asked, email):
    response = await confirm(client, auth, '000000')

    assert response.status_code == 400
    assert (await client.get('/me', headers=auth)).json()['email'] == email


async def test_confirm_email_change_too_many_attempts(client, auth, asked, code):
    for _ in range(5):
        await confirm(client, auth, '000000')
    response = await confirm(client, auth, code)

    assert response.status_code == 400
    assert response.json() == {'detail': 'too many attempts'}


@pytest.mark.freeze_time
async def test_confirm_email_change_code_expires(client, auth, asked, code, freezer):
    # Ten minutes for the code; the access token would last fifteen.
    freezer.tick(10 * 60)
    response = await confirm(client, auth, code)

    assert response.status_code == 400
    assert response.json() == {'detail': 'code expired'}


async def test_confirm_email_change_code_works_once(client, auth, asked, code):
    await confirm(client, auth, code)

    assert (await confirm(client, auth, code)).status_code == 400


async def test_confirm_without_asking(client, auth):
    assert (await confirm(client, auth, '123456')).status_code == 400


async def test_somebody_elses_code_moves_nobody(client, asked, code, other_auth, other_email):
    response = await confirm(client, other_auth, code)

    assert response.status_code == 400
    assert (await client.get('/me', headers=other_auth)).json()['email'] == other_email


async def test_asking_again_changes_the_destination(client, auth, password, mocker):
    mocker.patch('app.security.random_code', side_effect=['111111', '222222'])
    for address in ('first@example.com', 'second@example.com'):
        await client.post('/me/change-email', json={'new_email': address, 'password': password}, headers=auth)

    assert (await confirm(client, auth, '111111')).status_code == 400
    assert (await confirm(client, auth, '222222')).json()['email'] == 'second@example.com'


@pytest.mark.parametrize('address', ['', 'ann', 'ann@', '@example.com'])
async def test_change_email_bad_address(client, auth, password, address):
    response = await client.post('/me/change-email', json={'new_email': address, 'password': password}, headers=auth)

    assert response.status_code == 422


@pytest.mark.parametrize('path, body', [
    ('/me/change-email', {'new_email': NEW, 'password': 'Passw0rd!'}),
    ('/me/change-email/confirm', {'code': '123456'}),
])
async def test_change_email_signed_out(client, user, path, body):
    assert (await client.post(path, json=body)).status_code == 401
