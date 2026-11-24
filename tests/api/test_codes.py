"""What is true of every code the application sends, whatever it is for."""
import pytest

from sqlalchemy import select

from app.models import OneTimeCode
from tests.utils import mailed_code, mailed_to

FLOWS = ['verify-email', 'reset-by-email', 'reset-by-phone', 'change-email', 'change-phone']

NEW_USER = 'new@example.com'
MOVED = 'moved@example.com'


class Flow:
    """One purpose of a code: how it is asked for, where it goes, how it is handed in."""

    def __init__(self, name, client, user, auth, password, other_phone, outbox, sms_outbox):
        self.name, self.client, self.user, self.auth, self.password = name, client, user, auth, password
        self.other_phone = other_phone
        self.by_text = name.endswith('phone')
        self.outbox = sms_outbox if self.by_text else outbox
        self.destination = {
            'verify-email': NEW_USER, 'reset-by-email': user.email, 'reset-by-phone': user.phone,
            'change-email': MOVED, 'change-phone': other_phone,
        }[name]
        self.accepted = 204 if name.startswith('reset') else 200
        self.asked = False

    async def ask(self):
        client, first, self.asked = self.client, not self.asked, True
        if self.name == 'verify-email' and first:
            body = {'email': NEW_USER, 'password': self.password, 'first_name': 'New', 'last_name': 'User'}
            return await client.post('/auth/register', json=body)
        if self.name == 'verify-email':
            return await client.post('/auth/resend-code', json={'email': NEW_USER})
        if self.name == 'reset-by-email':
            return await client.post('/auth/forgot-password', json={'email': self.user.email})
        if self.name == 'reset-by-phone':
            return await client.post('/auth/forgot-password', json={'phone': self.user.phone})
        if self.name == 'change-email':
            body = {'new_email': MOVED, 'password': self.password}
            return await client.post('/me/change-email', json=body, headers=self.auth)
        body = {'new_phone': self.other_phone, 'password': self.password}
        return await client.post('/me/change-phone', json=body, headers=self.auth)

    async def hand_in(self, code):
        client = self.client
        if self.name == 'verify-email':
            return await client.post('/auth/verify-email', json={'email': NEW_USER, 'code': code})
        if self.name == 'reset-by-email':
            body = {'email': self.user.email, 'code': code, 'new_password': 'Br4ndNewOne'}
            return await client.post('/auth/reset-password', json=body)
        if self.name == 'reset-by-phone':
            body = {'phone': self.user.phone, 'code': code, 'new_password': 'Br4ndNewOne'}
            return await client.post('/auth/reset-password', json=body)
        return await client.post(f'/me/{self.name}/confirm', json={'code': code}, headers=self.auth)

    async def asked_for(self) -> str:
        """Asks, and reads the code out of what was sent."""
        await self.ask()
        return mailed_code(self.outbox)

    def wrong(self, code) -> str:
        return '000000' if code != '000000' else '111111'


@pytest.fixture
def flow(request, client, user_with_phone, phone_auth, password, other_phone, outbox, sms_outbox):
    return Flow(request.param, client, user_with_phone, phone_auth, password, other_phone, outbox, sms_outbox)


every_flow = pytest.mark.parametrize('flow', FLOWS, indirect=True)


@every_flow
async def test_code_goes_where_it_should(flow):
    code = await flow.asked_for()

    assert mailed_to(flow.outbox) == flow.destination
    assert code.isdigit() and len(code) == 6


@every_flow
async def test_code_goes_one_way_only(flow, outbox, sms_outbox):
    await flow.ask()

    assert (outbox.await_count, sms_outbox.await_count) == ((0, 1) if flow.by_text else (1, 0))


@every_flow
async def test_code_is_kept_as_a_digest(flow, db_session):
    code = await flow.asked_for()

    row = await db_session.scalar(select(OneTimeCode))
    assert code not in row.code_digest and len(row.code_digest) == 64
    assert row.target == flow.destination


@every_flow
async def test_right_code(flow):
    code = await flow.asked_for()

    assert (await flow.hand_in(code)).status_code == flow.accepted


@every_flow
async def test_wrong_code(flow):
    code = await flow.asked_for()
    response = await flow.hand_in(flow.wrong(code))

    assert response.status_code == 400
    assert response.json() == {'detail': 'invalid code'}


@every_flow
async def test_wrong_code_is_counted(flow, db_session):
    code = await flow.asked_for()
    for _ in range(3):
        await flow.hand_in(flow.wrong(code))

    assert (await db_session.scalar(select(OneTimeCode))).attempts == 3


@every_flow
async def test_right_code_after_four_wrong(flow):
    code = await flow.asked_for()
    for _ in range(4):
        await flow.hand_in(flow.wrong(code))

    assert (await flow.hand_in(code)).status_code == flow.accepted


@every_flow
async def test_right_code_after_five_wrong(flow):
    code = await flow.asked_for()
    for _ in range(5):
        await flow.hand_in(flow.wrong(code))
    response = await flow.hand_in(code)

    assert response.status_code == 400
    assert response.json() == {'detail': 'too many attempts'}


@every_flow
@pytest.mark.freeze_time
async def test_code_expires_in_ten_minutes(flow, freezer):
    code = await flow.asked_for()
    freezer.tick(10 * 60)
    response = await flow.hand_in(code)

    assert response.status_code == 400
    assert response.json() == {'detail': 'code expired'}


@every_flow
@pytest.mark.freeze_time
async def test_code_lives_ten_minutes(flow, freezer):
    code = await flow.asked_for()
    freezer.tick(10 * 60 - 1)

    assert (await flow.hand_in(code)).status_code == flow.accepted


@every_flow
async def test_code_works_once(flow):
    code = await flow.asked_for()
    await flow.hand_in(code)

    assert (await flow.hand_in(code)).status_code == 400


@every_flow
async def test_code_is_gone_once_used(flow, db_session):
    await flow.hand_in(await flow.asked_for())

    assert await db_session.scalar(select(OneTimeCode)) is None


@every_flow
async def test_no_code_was_asked_for(flow):
    response = await flow.hand_in('123456')

    assert response.status_code == 400


@every_flow
async def test_asking_again_retires_the_code(flow, mocker):
    mocker.patch('app.security.random_code', side_effect=['111111', '222222'])
    await flow.ask()
    await flow.ask()

    assert (await flow.hand_in('111111')).status_code == 400
    assert (await flow.hand_in('222222')).status_code == flow.accepted


@every_flow
async def test_asking_again_keeps_one_code(flow, db_session):
    await flow.ask()
    await flow.ask()

    assert len((await db_session.scalars(select(OneTimeCode))).all()) == 1


@every_flow
async def test_asking_again_starts_the_count_anew(flow):
    code = await flow.asked_for()
    for _ in range(5):
        await flow.hand_in(flow.wrong(code))
    code = await flow.asked_for()

    assert (await flow.hand_in(code)).status_code == flow.accepted


@every_flow
@pytest.mark.freeze_time
async def test_asking_again_starts_the_ten_minutes_anew(flow, freezer):
    await flow.ask()
    freezer.tick(6 * 60)
    code = await flow.asked_for()
    # Twelve minutes after the first code, six after the second.
    freezer.tick(6 * 60)

    assert (await flow.hand_in(code)).status_code == flow.accepted


@every_flow
@pytest.mark.parametrize('malformed', ['', '12345', '1234567', 'abcdef', '12 456', '１２３４５６'])
async def test_malformed_code(flow, malformed):
    await flow.ask()

    assert (await flow.hand_in(malformed)).status_code == 422
