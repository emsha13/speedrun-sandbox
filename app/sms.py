import logging

logger = logging.getLogger(__name__)


async def send_sms(to: str, text: str) -> None:
    """Where the SMS provider's client would be; see `app/emails.py`."""
    logger.info('sms to %s: %s', to, text)
