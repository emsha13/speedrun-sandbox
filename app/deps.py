from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app import security
from app.db import get_session
from app.models import RefreshSession, Role, User

Db = Annotated[AsyncSession, Depends(get_session)]
bearer = HTTPBearer(auto_error=False)
UNAUTHORIZED = HTTPException(status.HTTP_401_UNAUTHORIZED, 'not authenticated')


@dataclass
class Signed:
    user: User
    session_id: int


async def signed_in(session: Db, credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)]):
    """Who the access token names — as long as the sign-in it came from has not been ended."""
    payload = security.read_access_token(credentials.credentials) if credentials else None
    if payload is None:
        raise UNAUTHORIZED
    row = await session.get(RefreshSession, payload['sid'])
    if row is None or row.revoked_at is not None:
        raise UNAUTHORIZED
    user = await session.get(User, row.user_id)
    if user is None or not user.is_active:
        raise UNAUTHORIZED
    return Signed(user, row.id)


Me = Annotated[Signed, Depends(signed_in)]


async def admin(me: Me) -> Signed:
    if me.user.role != Role.ADMIN:
        raise HTTPException(status.HTTP_403_FORBIDDEN, 'admins only')
    return me


Admin = Annotated[Signed, Depends(admin)]
