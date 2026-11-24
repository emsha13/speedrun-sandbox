"""The users, as an admin sees them."""
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import func, or_, select

from app import services
from app.deps import Admin, Db
from app.models import User
from app.schemas import UserAdminUpdate, UserOut, UserPage, UserQuery

router = APIRouter(prefix='/users', tags=['users'])
NOT_FOUND = HTTPException(status.HTTP_404_NOT_FOUND, 'no such user')


def escaped(text: str) -> str:
    """The text as a `LIKE` pattern that means the text itself: a percent sign looked for is a
    percent sign, not "anything"."""
    return text.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_')


@router.get('', response_model=UserPage)
async def list_users(query: Annotated[UserQuery, Query()], admin: Admin, session: Db):
    found = select(User)
    if query.search:
        pattern = f'%{escaped(query.search)}%'
        found = found.where(or_(
            User.email.ilike(pattern), User.first_name.ilike(pattern), User.last_name.ilike(pattern),
            User.phone.like(pattern),
        ))
    if query.is_active is not None:
        found = found.where(User.is_active == query.is_active)
    if query.role is not None:
        found = found.where(User.role == query.role)
    total = await session.scalar(select(func.count()).select_from(found.subquery()))
    column = getattr(User, query.sort)
    # The id last: users of one name keep one order from page to page.
    ordered = found.order_by(column.desc() if query.order == 'desc' else column.asc(), User.id)
    rows = await session.scalars(ordered.limit(query.limit).offset(query.offset))
    return UserPage(total=total, items=rows.all())


async def the_user(session: Db, user_id: int) -> User:
    user = await session.get(User, user_id)
    if user is None:
        raise NOT_FOUND
    return user


@router.get('/{user_id}', response_model=UserOut)
async def read_user(user_id: int, admin: Admin, session: Db):
    return await the_user(session, user_id)


@router.patch('/{user_id}', response_model=UserOut)
async def update_user(user_id: int, data: UserAdminUpdate, admin: Admin, session: Db):
    user = await the_user(session, user_id)
    changes = data.model_dump(exclude_none=True)
    if changes and user.id == admin.user.id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, 'an admin does not change their own standing')
    for name, value in changes.items():
        setattr(user, name, value)
    if changes.get('is_active') is False:
        await services.close_sessions(session, user)
        services.record(session, user, 'deactivated')
    await session.commit()
    return user


@router.delete('/{user_id}', status_code=status.HTTP_204_NO_CONTENT)
async def delete_user(user_id: int, admin: Admin, session: Db):
    user = await the_user(session, user_id)
    if user.id == admin.user.id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, 'an admin does not delete themselves here')
    await session.delete(user)
    await session.commit()
