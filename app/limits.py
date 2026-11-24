"""Counters in Redis: how often one address knocks on a door, how many codes one mailbox is sent.

A window is a whole stretch of the clock — minute 12:07, not "the last sixty seconds" — and its
number is part of the key, so a counter needs no arithmetic and a new window starts from nothing.
"""
import logging

from fastapi import HTTPException, Request, status
from redis.asyncio import Redis
from redis.exceptions import RedisError

from app.models import now
from app.settings import settings

logger = logging.getLogger(__name__)
redis = Redis.from_url(settings.REDIS_URL, decode_responses=True)


def window_of(seconds: int) -> tuple[int, int]:
    """The number of the current window of that length, and the seconds left in it."""
    moment = int(now().timestamp())
    return moment // seconds, seconds - moment % seconds


async def count(name: str, subject: str, seconds: int) -> int | None:
    """One more in the subject's current window; how many that makes. `None` when Redis cannot
    say: a door stays open without its counter rather than shut because of it."""
    window, left = window_of(seconds)
    key = f'limit:{name}:{subject}:{window}'
    try:
        reached = await redis.incr(key)
        if reached == 1:
            await redis.expire(key, left)
        return reached
    except RedisError as error:
        logger.warning('limit %s is not counted: %s', name, error)
        return None


def refusal(detail: str, seconds: int) -> HTTPException:
    return HTTPException(
        status.HTTP_429_TOO_MANY_REQUESTS, detail, headers={'Retry-After': str(window_of(seconds)[1])}
    )


def door(name: str):
    """A dependency: the door answers one address `DOOR_LIMIT` times a minute."""
    async def limited(request: Request) -> None:
        reached = await count(f'door:{name}', request.client.host if request.client else 'unknown', 60)
        if reached is not None and reached > settings.DOOR_LIMIT:
            raise refusal('too many requests', 60)
    return limited


async def spend_send(address: str) -> None:
    """One code out of the address's budget — counted whether or not anybody lives there, so the
    answer tells nobody who is registered."""
    seconds = settings.SEND_WINDOW_MINUTES * 60
    reached = await count('send', address, seconds)
    if reached is not None and reached > settings.SEND_LIMIT:
        raise refusal('too many codes, try later', seconds)
