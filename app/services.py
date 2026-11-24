from datetime import timedelta

from fastapi import HTTPException, status
from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app import emails, security
from app.models import AuditEvent, CodePurpose, LoginAttempt, OneTimeCode, RefreshSession, User, now
from app.schemas import Tokens
from app.settings import settings

INVALID_CODE = HTTPException(status.HTTP_400_BAD_REQUEST, 'invalid code')

SUBJECTS = {
    CodePurpose.VERIFY_EMAIL: 'Confirm your address',
    CodePurpose.RESET_PASSWORD: 'Reset your password',
    CodePurpose.CHANGE_EMAIL: 'Confirm your new address',
}


async def user_by_email(session: AsyncSession, email: str) -> User | None:
    return await session.scalar(select(User).where(User.email == email))


async def send_code(session: AsyncSession, user: User, purpose: CodePurpose, target: str | None = None) -> None:
    """A new code for the purpose, mailed; the one before it stops working."""
    await session.execute(
        delete(OneTimeCode).where(OneTimeCode.user_id == user.id, OneTimeCode.purpose == purpose)
    )
    code = security.random_code()
    session.add(OneTimeCode(
        user_id=user.id, purpose=purpose, code_digest=security.digest(code), target=target,
        expires_at=now() + timedelta(minutes=settings.CODE_MINUTES),
    ))
    await session.commit()
    await emails.send_email(target or user.email, SUBJECTS[purpose], f'Your code: {code}')


async def use_code(session: AsyncSession, user: User, purpose: CodePurpose, code: str) -> OneTimeCode:
    """The user's code for the purpose, spent — or a refusal. A wrong guess is counted, and the
    count outlives the refusal."""
    row = await session.scalar(
        select(OneTimeCode).where(OneTimeCode.user_id == user.id, OneTimeCode.purpose == purpose)
    )
    if row is None:
        raise INVALID_CODE
    if row.expires_at <= now():
        raise HTTPException(status.HTTP_400_BAD_REQUEST, 'code expired')
    if row.attempts >= settings.CODE_ATTEMPTS:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, 'too many attempts')
    if row.code_digest != security.digest(code):
        row.attempts += 1
        await session.commit()
        raise INVALID_CODE
    await session.delete(row)
    return row


async def open_session(session: AsyncSession, user: User, user_agent: str) -> Tokens:
    token = security.random_token()
    row = RefreshSession(
        user_id=user.id, token_digest=security.digest(token), user_agent=user_agent[:200],
        expires_at=now() + timedelta(days=settings.REFRESH_TOKEN_DAYS),
    )
    session.add(row)
    await session.commit()
    return Tokens(access_token=security.create_access_token(user.id, row.id), refresh_token=token)


async def close_sessions(session: AsyncSession, user: User, keep: int | None = None) -> None:
    """Every sign-in of the user ends, except the one kept."""
    query = update(RefreshSession).where(RefreshSession.user_id == user.id, RefreshSession.revoked_at.is_(None))
    if keep is not None:
        query = query.where(RefreshSession.id != keep)
    await session.execute(query.values(revoked_at=now()))


async def locked(session: AsyncSession, email: str) -> bool:
    since = now() - timedelta(minutes=settings.LOGIN_LOCK_MINUTES)
    failures = await session.scalar(
        select(func.count()).select_from(LoginAttempt).where(
            LoginAttempt.email == email, LoginAttempt.created_at > since
        )
    )
    return failures >= settings.LOGIN_ATTEMPTS


def record(session: AsyncSession, user: User, kind: str) -> None:
    session.add(AuditEvent(user_id=user.id, kind=kind))
