import logging

logger = logging.getLogger(__name__)


async def send_email(to: str, subject: str, body: str) -> None:
    """Where the SMTP client would be. The example has nobody to write to, so it says what it
    would have sent; the tests stand in for this function and read what it was called with."""
    logger.info('email to %s: %s\n%s', to, subject, body)
