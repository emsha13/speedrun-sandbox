import pytest

from sqlalchemy import select

from app.models import AuditEvent
from tests.utils import mailed_code, mailed_to, sign_in


@pytest.fixture
async def asked(client, auth, phone, password, code):
    """The user has asked to set the number; the code is known."""
    response = await client.post('/me/change-phone', json={'new_phone': phone, 'password': password}, headers=auth)
    assert response.status_code == 204


async def confirm(client, auth, code):
    return await client.post('/me/change-phone/confirm', json={'code': code}, headers=auth)


async def test_change_phone_texts_the_number(client, auth, phone, password, sms_outbox, outbox):
    response = await client.post('/me/change-phone', json={'new_phone': phone, 'password': password}, headers=auth)

    assert response.status_code == 204
    assert mailed_to(sms_outbox) == phone
    assert len(mailed_code(sms_outbox)) == 6
    outbox.assert_not_awaited()


async def test_change_phone_changes_nothing_yet(client, auth, asked):
    assert (await client.get('/me', headers=auth)).json()['phone'] is None


async def test_confirm_phone_change(client, auth, asked, code, phone):
    response = await confirm(client, auth, code)

    assert response.status_code == 200
    assert response.json()['phone'] == phone


async def test_the_number_is_kept(client, auth, asked, code, phone, user, db_session):
    await confirm(client, auth, code)

    await db_session.refresh(user)
    assert user.phone == phone


async def test_sign_in_with_the_new_number(client, auth, asked, code, phone, password):
    await confirm(client, auth, code)

    assert await sign_in(client, phone, password)


async def test_phone_change_is_recorded(client, auth, asked, code, db_session):
    await confirm(client, auth, code)

    kinds = (await db_session.scalars(select(AuditEvent.kind).order_by(AuditEvent.id))).all()
    assert kinds == ['login', 'phone_changed']


async def test_replace_a_number(client, phone_auth, other_phone, password, code, phone):
    await client.post('/me/change-phone', json={'new_phone': other_phone, 'password': password}, headers=phone_auth)
    response = await confirm(client, phone_auth, code)

    assert response.json()['phone'] == other_phone
    assert (await client.post('/auth/login', json={'phone': phone, 'password': password})).status_code == 401


async def test_change_phone_wrong_password(client, auth, phone, sms_outbox):
    response = await client.post(
        '/me/change-phone', json={'new_phone': phone, 'password': 'Wr0ngPassword'}, headers=auth
    )

    assert response.status_code == 400
    assert response.json() == {'detail': 'wrong password'}
    sms_outbox.assert_not_awaited()


async def test_change_phone_to_the_same(client, phone_auth, phone, password):
    response = await client.post(
        '/me/change-phone', json={'new_phone': phone, 'password': password}, headers=phone_auth
    )

    assert response.status_code == 400
    assert response.json() == {'detail': 'new phone is the old one'}


async def test_change_phone_to_a_taken_one(client, auth, create_user, phone, password, sms_outbox):
    await create_user('carol@example.com', password, phone=phone)
    response = await client.post('/me/change-phone', json={'new_phone': phone, 'password': password}, headers=auth)

    assert response.status_code == 409
    sms_outbox.assert_not_awaited()


async def test_number_taken_between_the_request_and_the_code(client, auth, asked, code, create_user, phone, password):
    await create_user('carol@example.com', password, phone=phone)
    response = await confirm(client, auth, code)

    assert response.status_code == 409
    assert (await client.get('/me', headers=auth)).json()['phone'] is None


async def test_confirm_phone_change_wrong_code(client, auth, asked):
    response = await confirm(client, auth, '000000')

    assert response.status_code == 400
    assert (await client.get('/me', headers=auth)).json()['phone'] is None


async def test_confirm_phone_change_too_many_attempts(client, auth, asked, code):
    for _ in range(5):
        await confirm(client, auth, '000000')
    response = await confirm(client, auth, code)

    assert response.status_code == 400
    assert response.json() == {'detail': 'too many attempts'}


@pytest.mark.freeze_time
async def test_confirm_phone_change_code_expires(client, auth, asked, code, freezer):
    freezer.tick(10 * 60)
    response = await confirm(client, auth, code)

    assert response.status_code == 400
    assert response.json() == {'detail': 'code expired'}


@pytest.mark.freeze_time
async def test_confirm_phone_change_code_lives_ten_minutes(client, auth, asked, code, freezer):
    freezer.tick(10 * 60 - 1)

    assert (await confirm(client, auth, code)).status_code == 200


async def test_confirm_phone_change_code_works_once(client, auth, asked, code):
    await confirm(client, auth, code)

    assert (await confirm(client, auth, code)).status_code == 400


async def test_confirm_phone_without_asking(client, auth):
    assert (await confirm(client, auth, '123456')).status_code == 400


async def test_a_phone_code_changes_no_address(client, auth, asked, code, email):
    response = await client.post('/me/change-email/confirm', json={'code': code}, headers=auth)

    assert response.status_code == 400
    assert (await client.get('/me', headers=auth)).json()['email'] == email


async def test_somebody_elses_phone_code(client, asked, code, other_auth):
    response = await confirm(client, other_auth, code)

    assert response.status_code == 400
    assert (await client.get('/me', headers=other_auth)).json()['phone'] is None


async def test_asking_again_changes_the_number(client, auth, phone, other_phone, password, mocker):
    mocker.patch('app.security.random_code', side_effect=['111111', '222222'])
    for number in (phone, other_phone):
        await client.post('/me/change-phone', json={'new_phone': number, 'password': password}, headers=auth)

    assert (await confirm(client, auth, '111111')).status_code == 400
    assert (await confirm(client, auth, '222222')).json()['phone'] == other_phone


@pytest.mark.parametrize('number', [
    '', '4915112345678', '+0915112345678', '+49 151 12345678', '+49-151-12345678', '+4915', '+1234567890123456',
    '+49151123456ab', '0049151123456',
])
async def test_change_phone_bad_number(client, auth, password, number):
    response = await client.post('/me/change-phone', json={'new_phone': number, 'password': password}, headers=auth)

    assert response.status_code == 422


@pytest.mark.parametrize('number', ['+12025550123', '+442071234567', '+4915112345678', '+81312345678', '+35812345678'])
async def test_change_phone_numbers_of_the_world(client, auth, password, number, sms_outbox):
    response = await client.post('/me/change-phone', json={'new_phone': number, 'password': password}, headers=auth)

    assert response.status_code == 204
    assert mailed_to(sms_outbox) == number


@pytest.mark.parametrize('path, body', [
    ('/me/change-phone', {'new_phone': '+4915112345678', 'password': 'Passw0rd!'}),
    ('/me/change-phone/confirm', {'code': '123456'}),
    ('/me/remove-phone', {'password': 'Passw0rd!'}),
])
async def test_phone_doors_signed_out(client, user, path, body):
    assert (await client.post(path, json=body)).status_code == 401


async def test_remove_phone(client, phone_auth, password):
    response = await client.post('/me/remove-phone', json={'password': password}, headers=phone_auth)

    assert response.status_code == 200
    assert response.json()['phone'] is None


async def test_removed_number_signs_in_no_more(client, phone_auth, phone, password):
    await client.post('/me/remove-phone', json={'password': password}, headers=phone_auth)

    assert (await client.post('/auth/login', json={'phone': phone, 'password': password})).status_code == 401


async def test_removed_number_is_free(client, phone_auth, other_auth, phone, password, code):
    await client.post('/me/remove-phone', json={'password': password}, headers=phone_auth)
    await client.post('/me/change-phone', json={'new_phone': phone, 'password': password}, headers=other_auth)

    assert (await confirm(client, other_auth, code)).json()['phone'] == phone


async def test_remove_phone_wrong_password(client, phone_auth, phone):
    response = await client.post('/me/remove-phone', json={'password': 'Wr0ngPassword'}, headers=phone_auth)

    assert response.status_code == 400
    assert (await client.get('/me', headers=phone_auth)).json()['phone'] == phone


async def test_remove_phone_when_there_is_none(client, auth, password):
    response = await client.post('/me/remove-phone', json={'password': password}, headers=auth)

    assert response.status_code == 400
    assert response.json() == {'detail': 'there is no phone to remove'}


async def test_remove_phone_is_recorded(client, phone_auth, password, db_session):
    await client.post('/me/remove-phone', json={'password': password}, headers=phone_auth)

    kinds = (await db_session.scalars(select(AuditEvent.kind).order_by(AuditEvent.id))).all()
    assert kinds == ['login', 'phone_removed']
