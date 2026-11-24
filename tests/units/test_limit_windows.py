"""The arithmetic of a counter's window, and the counter itself against a Redis of the test's."""
import pytest

from fastapi import HTTPException
from redis.exceptions import ConnectionError, TimeoutError

from app import limits
from app.settings import settings


@pytest.mark.parametrize('moment, left', [
    ('2026-03-01 10:00:00', 60), ('2026-03-01 10:00:01', 59), ('2026-03-01 10:00:30', 30),
    ('2026-03-01 10:00:59', 1), ('2026-03-01 10:01:00', 60), ('2026-03-01 23:59:59', 1), ('2026-12-31 23:59:30', 30),
])
def test_what_is_left_of_a_minute(freezer, moment, left):
    freezer.move_to(moment)

    assert limits.window_of(60)[1] == left


@pytest.mark.parametrize('moment, left', [
    ('2026-03-01 10:00:00', 600), ('2026-03-01 10:02:00', 480), ('2026-03-01 10:09:59', 1),
    ('2026-03-01 10:10:00', 600), ('2026-03-01 10:15:30', 270), ('2026-03-01 00:00:00', 600),
])
def test_what_is_left_of_ten_minutes(freezer, moment, left):
    freezer.move_to(moment)

    assert limits.window_of(600)[1] == left


@pytest.mark.parametrize('seconds', [1, 59])
def test_a_window_holds_till_its_end(freezer, seconds):
    freezer.move_to('2026-03-01 10:00:00')
    window = limits.window_of(60)[0]
    freezer.tick(seconds)

    assert limits.window_of(60)[0] == window


@pytest.mark.parametrize('seconds, windows', [(60, 1), (61, 1), (119, 1), (120, 2), (3600, 60)])
def test_windows_follow_one_another(freezer, seconds, windows):
    freezer.move_to('2026-03-01 10:00:00')
    window = limits.window_of(60)[0]
    freezer.tick(seconds)

    assert limits.window_of(60)[0] == window + windows


async def test_count_counts(fake_redis):
    assert [await limits.count('door:login', '10.0.0.1', 60) for _ in range(4)] == [1, 2, 3, 4]


@pytest.mark.parametrize('one, another', [
    (('door:login', '10.0.0.1'), ('door:login', '10.0.0.2')),
    (('door:login', '10.0.0.1'), ('door:logout', '10.0.0.1')),
    (('send', 'ann@example.com'), ('send', 'bob@example.com')),
    (('send', '+4915112345678'), ('door:login', '+4915112345678')),
])
async def test_counters_are_apart(fake_redis, one, another):
    for _ in range(3):
        await limits.count(*one, 60)

    assert await limits.count(*another, 60) == 1


async def test_count_starts_anew_in_the_next_window(fake_redis, freezer):
    freezer.move_to('2026-03-01 10:00:59')
    await limits.count('door:login', '10.0.0.1', 60)
    freezer.tick(1)

    assert await limits.count('door:login', '10.0.0.1', 60) == 1


async def test_counter_lives_as_long_as_its_window(fake_redis, freezer):
    freezer.move_to('2026-03-01 10:00:20')
    await limits.count('door:login', '10.0.0.1', 60)

    (key,) = await fake_redis.keys('*')
    assert 0 < await fake_redis.ttl(key) <= 40


@pytest.mark.parametrize('error', [ConnectionError('gone'), TimeoutError('slow')])
async def test_count_says_nothing_without_redis(fake_redis, mocker, error):
    mocker.patch.object(fake_redis, 'incr', side_effect=error)

    assert await limits.count('door:login', '10.0.0.1', 60) is None


@pytest.mark.parametrize('sent, refused', [(1, False), (3, False), (4, True), (10, True)])
async def test_send_budget(fake_redis, sent, refused):
    for _ in range(sent - 1):
        try:
            await limits.spend_send('ann@example.com')
        except HTTPException:
            pass

    if refused:
        with pytest.raises(HTTPException) as caught:
            await limits.spend_send('ann@example.com')
        assert caught.value.status_code == 429
    else:
        await limits.spend_send('ann@example.com')


async def test_send_budget_follows_the_setting(fake_redis, monkeypatch):
    monkeypatch.setattr(settings, 'SEND_LIMIT', 1)
    await limits.spend_send('ann@example.com')

    with pytest.raises(HTTPException):
        await limits.spend_send('ann@example.com')


def test_a_refusal_says_when_to_come_back(freezer):
    freezer.move_to('2026-03-01 10:00:15')

    assert limits.refusal('too many requests', 60).headers == {'Retry-After': '45'}
