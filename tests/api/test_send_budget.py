"""One mailbox, or one phone, is sent three codes in ten minutes, whichever door asks."""
import pytest

from redis.exceptions import ConnectionError

from tests.utils import bearer, sign_in

SENDERS = ['register', 'resend-code', 'forgot-by-email', 'forgot-by-phone', 'change-email', 'change-phone']
every_sender = pytest.mark.parametrize('sender', SENDERS)


@pytest.fixture
async def send(client, sender, create_user, password):
    """Asks the door for a code to be sent to an address or a number."""
    auth = None
    if sender.startswith('change'):
        await create_user('owner@example.com', password)
        auth = bearer((await sign_in(client, 'owner@example.com', password))['access_token'])

    async def _send(to):
        if sender == 'register':
            body = {'email': to, 'password': password, 'first_name': 'Ann', 'last_name': 'Lee'}
            return await client.post('/auth/register', json=body)
        if sender == 'resend-code':
            return await client.post('/auth/resend-code', json={'email': to})
        if sender.startswith('forgot'):
            return await client.post('/auth/forgot-password', json={'phone' if to.startswith('+') else 'email': to})
        field = 'new_phone' if to.startswith('+') else 'new_email'
        return await client.post(f'/me/{sender}', json={field: to, 'password': password}, headers=auth)

    return _send


@pytest.fixture
def to(sender):
    return '+4915112345678' if sender.endswith('phone') else 'ann@example.com'


@pytest.fixture
def elsewhere(sender):
    return '+4915187654321' if sender.endswith('phone') else 'bob@example.com'


@every_sender
async def test_three_codes_are_sent(send, to):
    assert all((await send(to)).status_code != 429 for _ in range(3))


@every_sender
async def test_the_fourth_is_refused(send, to, outbox, sms_outbox):
    for _ in range(3):
        await send(to)
    sent = outbox.await_count + sms_outbox.await_count
    response = await send(to)

    assert response.status_code == 429
    assert response.json() == {'detail': 'too many codes, try later'}
    assert outbox.await_count + sms_outbox.await_count == sent


@every_sender
@pytest.mark.freeze_time('2026-03-01 10:02:00')
async def test_budget_refusal_says_when_to_come_back(send, to):
    for _ in range(3):
        await send(to)

    assert (await send(to)).headers['Retry-After'] == '480'


@every_sender
@pytest.mark.freeze_time('2026-03-01 10:02:00')
async def test_budget_returns_with_the_next_window(send, to, freezer):
    for _ in range(4):
        await send(to)
    freezer.tick(8 * 60)

    assert (await send(to)).status_code != 429


@every_sender
@pytest.mark.freeze_time('2026-03-01 10:02:00')
async def test_budget_is_gone_till_the_window_ends(send, to, freezer):
    for _ in range(4):
        await send(to)
    freezer.tick(8 * 60 - 1)

    assert (await send(to)).status_code == 429


@every_sender
async def test_budget_is_per_destination(send, to, elsewhere):
    for _ in range(4):
        await send(to)

    assert (await send(elsewhere)).status_code != 429


@every_sender
async def test_codes_are_sent_without_redis(send, to, fake_redis, mocker):
    mocker.patch.object(fake_redis, 'incr', side_effect=ConnectionError('gone'))

    assert all((await send(to)).status_code != 429 for _ in range(5))


async def test_budget_is_shared_by_the_doors(client, inactive_user):
    for door in ('resend-code', 'forgot-password', 'resend-code'):
        await client.post(f'/auth/{door}', json={'email': inactive_user.email})

    assert (await client.post('/auth/forgot-password', json={'email': inactive_user.email})).status_code == 429


async def test_an_address_nobody_has_is_counted_too(client, email, outbox):
    statuses = [(await client.post('/auth/forgot-password', json={'email': email})).status_code for _ in range(4)]

    assert statuses == [204, 204, 204, 429]
    outbox.assert_not_awaited()
