"""Who is asking, and what they are in the organisation they ask about."""
import functools

from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.deps import Db, Me
from app.models import User
from app.workspace.models.orgs import MemberRole, Membership

RANK = {role: rank for rank, role in enumerate(MemberRole)}
# The same answer for an organisation that is not there and for one the caller is not in: who is
# outside does not learn which numbers are taken.
NO_ORGANISATION = HTTPException(status.HTTP_404_NOT_FOUND, 'no such organisation')


@dataclass
class Context:
    session: AsyncSession
    org_id: int
    user: User
    membership: Membership

    def is_at_least(self, role: MemberRole) -> bool:
        return RANK[self.membership.role] >= RANK[role]


async def member(org_id: int, me: Me, session: Db) -> Context:
    membership = await session.scalar(
        select(Membership).where(Membership.organisation_id == org_id, Membership.user_id == me.user.id)
    ) if -2 ** 31 <= org_id < 2 ** 31 else None
    if membership is None:
        raise NO_ORGANISATION
    return Context(session, org_id, me.user, membership)


@functools.cache
def at_least(role: MemberRole):
    """A dependency: the caller is in the organisation, as that or more. One per role, so that a
    request that asks twice is answered once."""
    async def allowed(context: Annotated[Context, Depends(member)]) -> Context:
        if not context.is_at_least(role):
            raise HTTPException(status.HTTP_403_FORBIDDEN, f'{role}s only')
        return context
    return allowed


Guest = Annotated[Context, Depends(at_least(MemberRole.GUEST))]
Member = Annotated[Context, Depends(at_least(MemberRole.MEMBER))]
Admin = Annotated[Context, Depends(at_least(MemberRole.ADMIN))]
Owner = Annotated[Context, Depends(at_least(MemberRole.OWNER))]


async def is_member(context: Context, user_id: int) -> bool:
    found = select(Membership.id).where(
        Membership.organisation_id == context.org_id, Membership.user_id == user_id
    )
    return await context.session.scalar(found) is not None
