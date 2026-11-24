"""Every door of `/auth` answers one address a limited number of times a minute."""
import pytest

from redis.exceptions import ConnectionError

from app.settings import settings

DOORS = ['register', 'verify-email', 'resend-code', 'login', 'refresh', 'logout', 'forgot-password', 'reset-password']
every_door = pytest.mark.parametrize('door', DOORS)


@pytest.fixture(autouse=True)
def three_a_minute(monkeypatch):
    monkeypatch.setattr(settings, 'DOOR_LIMIT', 3)


async def knock(client, door, times=1):
    """An empty body: the door counts a knock before it reads what was brought."""
    return [(await client.post(f'/auth/{door}', json={})) for _ in range(times)]


@every_door
async def test_door_answers_up_to_the_limit(client, door):
    assert [response.status_code for response in await knock(client, door, 3)] == [422, 422, 422]


@every_door
async def test_door_refuses_over_the_limit(client, door):
    response = (await knock(client, door, 4))[-1]

    assert response.status_code == 429
    assert response.json() == {'detail': 'too many requests'}


@every_door
@pytest.mark.freeze_time('2026-03-01 10:00:15')
async def test_refusal_says_when_to_come_back(client, door):
    response = (await knock(client, door, 4))[-1]

    assert response.headers['Retry-After'] == '45'


@every_door
@pytest.mark.freeze_time('2026-03-01 10:00:15')
async def test_door_opens_with_the_next_minute(client, door, freezer):
    await knock(client, door, 4)
    freezer.tick(45)

    assert (await knock(client, door))[0].status_code == 422


@every_door
@pytest.mark.freeze_time('2026-03-01 10:00:15')
async def test_door_stays_shut_till_the_minute_ends(client, door, freezer):
    await knock(client, door, 4)
    freezer.tick(44)

    assert (await knock(client, door))[0].status_code == 429


@every_door
async def test_limit_is_per_address(client, client_elsewhere, door):
    await knock(client, door, 4)

    assert (await knock(client_elsewhere, door))[0].status_code == 422


@every_door
async def test_limit_is_per_door(client, door):
    await knock(client, door, 4)
    another = DOORS[DOORS.index(door) - 1]

    assert (await knock(client, another))[0].status_code == 422


@every_door
async def test_door_stays_open_without_redis(client, door, fake_redis, mocker):
    mocker.patch.object(fake_redis, 'incr', side_effect=ConnectionError('gone'))

    assert [response.status_code for response in await knock(client, door, 5)] == [422] * 5


@every_door
@pytest.mark.freeze_time('2026-03-01 10:00:15')
async def test_counter_does_not_outlive_its_minute(client, door, fake_redis):
    await knock(client, door)

    (key,) = await fake_redis.keys(f'limit:door:{door}:*')
    assert await fake_redis.get(key) == '1'
    assert 0 < await fake_redis.ttl(key) <= 45


@pytest.mark.parametrize('second, left', [(0, '60'), (1, '59'), (30, '30'), (59, '1')])
async def test_retry_after_counts_down(client, freezer, second, left):
    freezer.move_to(f'2026-03-01 10:00:{second:02d}')

    assert (await knock(client, 'login', 4))[-1].headers['Retry-After'] == left


async def test_the_account_doors_are_not_counted(client, auth, fake_redis):
    for _ in range(6):
        assert (await client.get('/me', headers=auth)).status_code == 200

    assert await fake_redis.keys('limit:door:me*') == []


async def test_default_limit_is_thirty(client, monkeypatch):
    monkeypatch.undo()
    assert settings.DOOR_LIMIT == 30
