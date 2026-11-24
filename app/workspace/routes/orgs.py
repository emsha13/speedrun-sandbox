"""Organisations: making one, who is in it, and how somebody new gets in."""
from datetime import timedelta
from typing import Annotated

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app import emails, security
from app.deps import Db, Me
from app.models import User, now
from app.schemas import Email
from app.workspace.access import Admin, Context, Guest, Owner
from app.workspace.base import SLUG
from app.workspace.crud import RowId, find, out_of, resource, shapes_of
from app.workspace.models.orgs import (
    Announcement, AnnouncementRead, Decision, Invitation, MemberRole, Membership, Office, Organisation, OrgSettings,
    Plan, Team, TimeOffBalance, TimeOffRequest,
)

# The organisation itself, and the door a letter of invitation leads to.
router = APIRouter(tags=['organisations'])
# What is inside one: these are mounted under `/orgs/{org_id}`.
inside = APIRouter(tags=['organisations'])

SEATS = {Plan.FREE: 5, Plan.TEAM: 50, Plan.BUSINESS: None}
INVITATION_DAYS = 7
OrganisationOut = out_of(Organisation)
InvitationOut = out_of(Invitation)
SettingsOut, _, SettingsChanges, _ = shapes_of(OrgSettings, ())


class NewOrganisation(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    slug: str = Field(min_length=2, max_length=40, pattern=SLUG)


class OrganisationChanges(BaseModel):
    model_config = ConfigDict(extra='forbid')

    name: Annotated[str, Field(min_length=1, max_length=80)] = None
    timezone: Annotated[str, Field(min_length=1, max_length=40)] = None
    plan: Plan = None


class MemberOut(BaseModel):
    user_id: int
    email: str
    first_name: str
    last_name: str
    role: MemberRole
    title: str | None


class MemberChanges(BaseModel):
    model_config = ConfigDict(extra='forbid')

    role: MemberRole = None
    title: Annotated[str, Field(max_length=80)] | None = None


class NewInvitation(BaseModel):
    email: Email
    role: MemberRole = MemberRole.MEMBER


class Token(BaseModel):
    token: str


class Verdict(BaseModel):
    approve: bool


@router.post('/orgs', response_model=OrganisationOut, status_code=status.HTTP_201_CREATED)
async def create_organisation(data: NewOrganisation, me: Me, session: Db):
    organisation = Organisation(name=data.name, slug=data.slug)
    session.add(organisation)
    try:
        await session.flush()
    except IntegrityError:
        raise HTTPException(status.HTTP_409_CONFLICT, 'slug is taken') from None
    session.add_all([
        Membership(organisation_id=organisation.id, user_id=me.user.id, role=MemberRole.OWNER),
        OrgSettings(organisation_id=organisation.id),
    ])
    await session.commit()
    return organisation


@router.get('/orgs', response_model=list[OrganisationOut])
async def list_my_organisations(me: Me, session: Db):
    rows = await session.scalars(
        select(Organisation).join(Membership, Membership.organisation_id == Organisation.id)
        .where(Membership.user_id == me.user.id).order_by(Organisation.id)
    )
    return rows.all()


async def seats_left(session, organisation: Organisation) -> bool:
    seats = SEATS[organisation.plan]
    taken = await session.scalar(
        select(func.count()).select_from(Membership).where(Membership.organisation_id == organisation.id)
    )
    return seats is None or taken < seats


@router.post('/invitations/accept', response_model=OrganisationOut)
async def accept_invitation(data: Token, me: Me, session: Db):
    invitation = await session.scalar(
        select(Invitation).where(Invitation.token_digest == security.digest(data.token))
    )
    if invitation is None or invitation.accepted_at is not None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, 'invalid invitation')
    if invitation.expires_at <= now():
        raise HTTPException(status.HTTP_400_BAD_REQUEST, 'invitation expired')
    if invitation.email != me.user.email:
        raise HTTPException(status.HTTP_403_FORBIDDEN, 'the invitation is for another address')
    organisation = await session.get(Organisation, invitation.organisation_id)
    # Seats are counted here and not only when the letter went out: they may have gone since.
    if not await seats_left(session, organisation):
        raise HTTPException(status.HTTP_409_CONFLICT, 'the plan has no seats left')
    invitation.accepted_at = now()
    session.add(Membership(organisation_id=organisation.id, user_id=me.user.id, role=invitation.role))
    try:
        await session.commit()
    except IntegrityError:
        raise HTTPException(status.HTTP_409_CONFLICT, 'already a member') from None
    return organisation


@inside.get('', response_model=OrganisationOut)
async def read_organisation(context: Guest):
    return await context.session.get(Organisation, context.org_id)


@inside.patch('', response_model=OrganisationOut)
async def update_organisation(data: OrganisationChanges, context: Admin):
    organisation = await context.session.get(Organisation, context.org_id)
    changes = data.model_dump(exclude_unset=True)
    if 'plan' in changes and not context.is_at_least(MemberRole.OWNER):
        raise HTTPException(status.HTTP_403_FORBIDDEN, 'owners only')
    for name, value in changes.items():
        setattr(organisation, name, value)
    await context.session.commit()
    return organisation


@inside.delete('', status_code=status.HTTP_204_NO_CONTENT)
async def delete_organisation(context: Owner):
    await context.session.delete(await context.session.get(Organisation, context.org_id))
    await context.session.commit()


@inside.get('/settings', response_model=SettingsOut)
async def read_settings(context: Guest):
    return await context.session.scalar(select(OrgSettings).where(OrgSettings.organisation_id == context.org_id))


@inside.patch('/settings', response_model=SettingsOut)
async def update_settings(data: SettingsChanges, context: Admin):
    settings = await context.session.scalar(
        select(OrgSettings).where(OrgSettings.organisation_id == context.org_id)
    )
    for name, value in data.model_dump(exclude_unset=True).items():
        setattr(settings, name, value)
    settings.updated_at = now()
    await context.session.commit()
    return settings


@inside.get('/members', response_model=list[MemberOut])
async def list_members(context: Guest):
    rows = await context.session.execute(
        select(Membership, User).join(User, User.id == Membership.user_id)
        .where(Membership.organisation_id == context.org_id).order_by(Membership.id)
    )
    return [
        MemberOut(
            user_id=user.id, email=user.email, first_name=user.first_name, last_name=user.last_name,
            role=membership.role, title=membership.title,
        )
        for membership, user in rows
    ]


async def the_member(context: Context, user_id: int) -> Membership:
    membership = await context.session.scalar(
        select(Membership).where(Membership.organisation_id == context.org_id, Membership.user_id == user_id)
    )
    if membership is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, 'no such member')
    return membership


async def is_the_last_owner(context: Context, membership: Membership) -> bool:
    if membership.role != MemberRole.OWNER:
        return False
    owners = await context.session.scalar(
        select(func.count()).select_from(Membership).where(
            Membership.organisation_id == context.org_id, Membership.role == MemberRole.OWNER
        )
    )
    return owners == 1


@inside.patch('/members/{user_id}', response_model=MemberOut)
async def update_member(user_id: RowId, data: MemberChanges, context: Admin):
    membership = await the_member(context, user_id)
    changes = data.model_dump(exclude_unset=True)
    role = changes.get('role')
    if role is not None and role != membership.role:
        # Who owns the organisation is for its owners to say: an admin neither makes an owner
        # nor unmakes one.
        if MemberRole.OWNER in (role, membership.role) and not context.is_at_least(MemberRole.OWNER):
            raise HTTPException(status.HTTP_403_FORBIDDEN, 'owners only')
        if await is_the_last_owner(context, membership):
            raise HTTPException(status.HTTP_409_CONFLICT, 'an organisation keeps an owner')
    for name, value in changes.items():
        setattr(membership, name, value)
    await context.session.commit()
    user = await context.session.get(User, user_id)
    return MemberOut(
        user_id=user.id, email=user.email, first_name=user.first_name, last_name=user.last_name,
        role=membership.role, title=membership.title,
    )


@inside.delete('/members/{user_id}', status_code=status.HTTP_204_NO_CONTENT)
async def remove_member(user_id: RowId, context: Guest):
    """Anybody leaves; an admin removes somebody else — unless that somebody owns the place."""
    membership = await the_member(context, user_id)
    if user_id != context.user.id:
        if not context.is_at_least(MemberRole.ADMIN):
            raise HTTPException(status.HTTP_403_FORBIDDEN, 'admins only')
        if membership.role == MemberRole.OWNER and not context.is_at_least(MemberRole.OWNER):
            raise HTTPException(status.HTTP_403_FORBIDDEN, 'owners only')
    if await is_the_last_owner(context, membership):
        raise HTTPException(status.HTTP_409_CONFLICT, 'an organisation keeps an owner')
    await context.session.delete(membership)
    await context.session.commit()


@inside.post('/invitations', response_model=InvitationOut, status_code=status.HTTP_201_CREATED)
async def invite(data: NewInvitation, context: Admin):
    session = context.session
    if data.role == MemberRole.OWNER:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, 'nobody is invited as an owner')
    already = await session.scalar(
        select(Membership.id).join(User, User.id == Membership.user_id)
        .where(Membership.organisation_id == context.org_id, User.email == data.email)
    )
    if already is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, 'already a member')
    waiting = await session.scalar(
        select(Invitation.id).where(
            Invitation.organisation_id == context.org_id, Invitation.email == data.email,
            Invitation.accepted_at.is_(None), Invitation.expires_at > now(),
        )
    )
    if waiting is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, 'already invited')
    organisation = await session.get(Organisation, context.org_id)
    if not await seats_left(session, organisation):
        raise HTTPException(status.HTTP_409_CONFLICT, 'the plan has no seats left')
    token = security.random_token()
    invitation = Invitation(
        organisation_id=context.org_id, email=data.email, role=data.role, token_digest=security.digest(token),
        invited_by_id=context.user.id, expires_at=now() + timedelta(days=INVITATION_DAYS),
    )
    session.add(invitation)
    await session.commit()
    await emails.send_email(data.email, f'Join {organisation.name}', f'Your invitation: {token}')
    return invitation


@inside.post('/announcements/{row_id}/read', status_code=status.HTTP_204_NO_CONTENT)
async def read_announcement(row_id: RowId, context: Guest):
    await find(context, Announcement, row_id)
    seen = await context.session.scalar(
        select(AnnouncementRead.id).where(
            AnnouncementRead.announcement_id == row_id, AnnouncementRead.user_id == context.user.id
        )
    )
    if seen is None:
        context.session.add(
            AnnouncementRead(organisation_id=context.org_id, announcement_id=row_id, user_id=context.user.id)
        )
        await context.session.commit()


@inside.get('/announcements/{row_id}/readers', response_model=list[int])
async def list_readers(row_id: RowId, context: Admin):
    await find(context, Announcement, row_id)
    rows = await context.session.scalars(
        select(AnnouncementRead.user_id).where(AnnouncementRead.announcement_id == row_id)
        .order_by(AnnouncementRead.id)
    )
    return rows.all()


async def dates_in_order(context: Context, row, old) -> None:
    if row.ends_on < row.starts_on:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, 'it ends before it starts')


async def a_request_still_pending(context: Context, row: TimeOffRequest, old) -> None:
    await dates_in_order(context, row, old)
    # A new row has no status yet: the column's default arrives when the row is written.
    if old is not None and row.status != Decision.PENDING:
        raise HTTPException(status.HTTP_409_CONFLICT, 'the request is decided')


@inside.post('/time-off-requests/{row_id}/decide', response_model=out_of(TimeOffRequest))
async def decide_time_off(row_id: RowId, data: Verdict, context: Admin):
    request = await find(context, TimeOffRequest, row_id)
    if request.status != Decision.PENDING:
        raise HTTPException(status.HTTP_409_CONFLICT, 'the request is decided')
    if request.user_id == context.user.id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, 'nobody decides their own request')
    request.status = Decision.APPROVED if data.approve else Decision.REJECTED
    request.decided_by_id = context.user.id
    if data.approve and request.user_id is not None:
        balance = await context.session.scalar(
            select(TimeOffBalance).where(
                TimeOffBalance.organisation_id == context.org_id, TimeOffBalance.user_id == request.user_id,
                TimeOffBalance.kind == request.kind, TimeOffBalance.year == request.starts_on.year,
            )
        )
        if balance is not None:
            days = (request.ends_on - request.starts_on).days + 1
            if balance.days_used + days > balance.days_allowed:
                raise HTTPException(status.HTTP_409_CONFLICT, 'not enough days left')
            balance.days_used += days
    await context.session.commit()
    return request


ADMIN = MemberRole.ADMIN
resource(inside, Invitation, methods='list read delete', read=ADMIN, write=ADMIN)
resource(inside, Team, search=('name', 'description'))
resource(inside, Office, write=ADMIN, search=('name', 'city'))
resource(inside, Announcement, write=ADMIN, author='author_id', search=('title', 'body'))
resource(inside, TimeOffRequest, author='user_id', own=True, check=a_request_still_pending)
resource(inside, TimeOffBalance, methods='list create update', write=ADMIN, audited=True)
