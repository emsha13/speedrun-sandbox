from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, status
from sqlalchemy import select

from app import limits, security, services
from app.deps import UNAUTHORIZED, Db
from app.models import CodePurpose, LoginAttempt, RefreshSession, User, now
from app.schemas import (
    Credentials, EmailAndCode, EmailOnly, EmailOrPhone, PasswordReset, RefreshToken, Registration, Tokens, UserOut,
)

router = APIRouter(prefix='/auth', tags=['auth'])
UserAgent = Annotated[str, Header()]


def door(name: str) -> list:
    return [Depends(limits.door(name))]


@router.post('/register', status_code=status.HTTP_201_CREATED, response_model=UserOut, dependencies=door('register'))
async def register(data: Registration, session: Db):
    await limits.spend_send(data.email)
    if await services.user_by_email(session, data.email):
        raise HTTPException(status.HTTP_409_CONFLICT, 'email is taken')
    user = User(
        email=data.email, password_hash=security.hash_password(data.password),
        first_name=data.first_name, last_name=data.last_name,
    )
    session.add(user)
    await session.flush()
    await services.send_code(session, user, CodePurpose.VERIFY_EMAIL, user.email)
    return user


@router.post('/verify-email', response_model=Tokens, dependencies=door('verify-email'))
async def verify_email(data: EmailAndCode, session: Db, user_agent: UserAgent = ''):
    user = await services.user_by_email(session, data.email)
    if user is None or user.is_active:
        raise services.INVALID_CODE
    await services.use_code(session, user, CodePurpose.VERIFY_EMAIL, data.code)
    user.is_active = True
    services.record(session, user, 'email_verified')
    return await services.open_session(session, user, user_agent)


@router.post('/resend-code', status_code=status.HTTP_204_NO_CONTENT, dependencies=door('resend-code'))
async def resend_code(data: EmailOnly, session: Db):
    # The same answer whether or not the address is known: this door tells nobody who is registered.
    await limits.spend_send(data.email)
    user = await services.user_by_email(session, data.email)
    if user and not user.is_active:
        await services.send_code(session, user, CodePurpose.VERIFY_EMAIL, user.email)


@router.post('/login', response_model=Tokens, dependencies=door('login'))
async def login(data: Credentials, session: Db, user_agent: UserAgent = ''):
    if await services.locked(session, data.login):
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, 'too many attempts, try later')
    user = await services.user_by_login(session, data.login)
    if not security.verify_password(data.password, user.password_hash if user else security.NOBODYS_HASH) or not user:
        session.add(LoginAttempt(login=data.login))
        await session.commit()
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, 'wrong login or password')
    if not user.is_active:
        raise HTTPException(status.HTTP_403_FORBIDDEN, 'account is not active')
    await services.forget_failures(session, user)
    services.record(session, user, 'login')
    return await services.open_session(session, user, user_agent)


@router.post('/refresh', response_model=Tokens, dependencies=door('refresh'))
async def refresh(data: RefreshToken, session: Db, user_agent: UserAgent = ''):
    """A refresh token works once: it buys a new pair and stops."""
    row = await session.scalar(
        select(RefreshSession).where(RefreshSession.token_digest == security.digest(data.refresh_token))
    )
    if row is None or row.revoked_at is not None or row.expires_at <= now():
        raise UNAUTHORIZED
    user = await session.get(User, row.user_id)
    if not user.is_active:
        raise UNAUTHORIZED
    row.revoked_at = now()
    return await services.open_session(session, user, user_agent)


@router.post('/logout', status_code=status.HTTP_204_NO_CONTENT, dependencies=door('logout'))
async def logout(data: RefreshToken, session: Db):
    row = await session.scalar(
        select(RefreshSession).where(RefreshSession.token_digest == security.digest(data.refresh_token))
    )
    if row and row.revoked_at is None:
        row.revoked_at = now()
        await session.commit()


@router.post('/forgot-password', status_code=status.HTTP_204_NO_CONTENT, dependencies=door('forgot-password'))
async def forgot_password(data: EmailOrPhone, session: Db):
    await limits.spend_send(data.login)
    user = await services.user_by_login(session, data.login)
    if user and user.is_active:
        await services.send_code(session, user, CodePurpose.RESET_PASSWORD, data.login)


@router.post('/reset-password', status_code=status.HTTP_204_NO_CONTENT, dependencies=door('reset-password'))
async def reset_password(data: PasswordReset, session: Db):
    user = await services.user_by_login(session, data.login)
    if user is None:
        raise services.INVALID_CODE
    await services.use_code(session, user, CodePurpose.RESET_PASSWORD, data.code)
    user.password_hash = security.hash_password(data.new_password)
    await services.close_sessions(session, user)
    await services.forget_failures(session, user)
    services.record(session, user, 'password_reset')
    await session.commit()
