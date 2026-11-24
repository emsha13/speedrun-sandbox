from typing import Annotated

from fastapi import APIRouter, Header, HTTPException, status
from sqlalchemy import delete, select

from app import security, services
from app.deps import UNAUTHORIZED, Db
from app.models import CodePurpose, LoginAttempt, RefreshSession, User, now
from app.schemas import Credentials, EmailAndCode, EmailOnly, PasswordReset, RefreshToken, Registration, Tokens, UserOut

router = APIRouter(prefix='/auth', tags=['auth'])
UserAgent = Annotated[str, Header()]


@router.post('/register', status_code=status.HTTP_201_CREATED, response_model=UserOut)
async def register(data: Registration, session: Db):
    if await services.user_by_email(session, data.email):
        raise HTTPException(status.HTTP_409_CONFLICT, 'email is taken')
    user = User(
        email=data.email, password_hash=security.hash_password(data.password),
        first_name=data.first_name, last_name=data.last_name,
    )
    session.add(user)
    await session.flush()
    await services.send_code(session, user, CodePurpose.VERIFY_EMAIL)
    return user


@router.post('/verify-email', response_model=Tokens)
async def verify_email(data: EmailAndCode, session: Db, user_agent: UserAgent = ''):
    user = await services.user_by_email(session, data.email)
    if user is None or user.is_active:
        raise services.INVALID_CODE
    await services.use_code(session, user, CodePurpose.VERIFY_EMAIL, data.code)
    user.is_active = True
    services.record(session, user, 'email_verified')
    return await services.open_session(session, user, user_agent)


@router.post('/resend-code', status_code=status.HTTP_204_NO_CONTENT)
async def resend_code(data: EmailOnly, session: Db):
    # The same answer whether or not the address is known: this door tells nobody who is registered.
    user = await services.user_by_email(session, data.email)
    if user and not user.is_active:
        await services.send_code(session, user, CodePurpose.VERIFY_EMAIL)


@router.post('/login', response_model=Tokens)
async def login(data: Credentials, session: Db, user_agent: UserAgent = ''):
    if await services.locked(session, data.email):
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, 'too many attempts, try later')
    user = await services.user_by_email(session, data.email)
    if not security.verify_password(data.password, user.password_hash if user else security.NOBODYS_HASH) or not user:
        session.add(LoginAttempt(email=data.email))
        await session.commit()
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, 'wrong email or password')
    if not user.is_active:
        raise HTTPException(status.HTTP_403_FORBIDDEN, 'email is not verified')
    await session.execute(delete(LoginAttempt).where(LoginAttempt.email == data.email))
    services.record(session, user, 'login')
    return await services.open_session(session, user, user_agent)


@router.post('/refresh', response_model=Tokens)
async def refresh(data: RefreshToken, session: Db, user_agent: UserAgent = ''):
    """A refresh token works once: it buys a new pair and stops."""
    row = await session.scalar(
        select(RefreshSession).where(RefreshSession.token_digest == security.digest(data.refresh_token))
    )
    if row is None or row.revoked_at is not None or row.expires_at <= now():
        raise UNAUTHORIZED
    row.revoked_at = now()
    user = await session.get(User, row.user_id)
    return await services.open_session(session, user, user_agent)


@router.post('/logout', status_code=status.HTTP_204_NO_CONTENT)
async def logout(data: RefreshToken, session: Db):
    row = await session.scalar(
        select(RefreshSession).where(RefreshSession.token_digest == security.digest(data.refresh_token))
    )
    if row and row.revoked_at is None:
        row.revoked_at = now()
        await session.commit()


@router.post('/forgot-password', status_code=status.HTTP_204_NO_CONTENT)
async def forgot_password(data: EmailOnly, session: Db):
    user = await services.user_by_email(session, data.email)
    if user and user.is_active:
        await services.send_code(session, user, CodePurpose.RESET_PASSWORD)


@router.post('/reset-password', status_code=status.HTTP_204_NO_CONTENT)
async def reset_password(data: PasswordReset, session: Db):
    user = await services.user_by_email(session, data.email)
    if user is None:
        raise services.INVALID_CODE
    await services.use_code(session, user, CodePurpose.RESET_PASSWORD, data.code)
    user.password_hash = security.hash_password(data.new_password)
    await services.close_sessions(session, user)
    await session.execute(delete(LoginAttempt).where(LoginAttempt.email == user.email))
    services.record(session, user, 'password_reset')
    await session.commit()
